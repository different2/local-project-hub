"""Process lifecycle: start, stop, restart project backends; capture their logs.

Boundary (per SPEC): the hub owns *how* processes are launched and read, never
their source. The command string is split with shlex (no shell) so
`python3 server.py 8471` works without quoting problems and without exposing a
shell injection surface from the registry file.

Stdout/stderr are merged into one ring buffer per project (newest 500 lines),
kept in memory for the log drawer. Signals are emitted on the GUI thread via Qt.

Stopping is deliberately patient: SIGTERM first, then SIGKILL only after a
generous grace period. Projects that build a large index at startup
(ai-agent-observability's ~12s _scan_once over a 3.8 GB capture is the
canonical case) need room to finish; a 3s hard kill destroys them mid-warm-up.
"""

from __future__ import annotations

import codecs
import os
import ntpath
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .platform import prepend_interpreter, resolve_interpreter, split_command
from .readiness import url_host_port
from . import urldetect

LOG_HISTORY = 500

# Grace given to a project to exit after SIGTERM before we escalate to SIGKILL.
TERM_GRACE_MS = 20_000

# Windows gets a much shorter leash: terminate() posts WM_CLOSE, which a console
# process never receives, so the full POSIX grace would stall every stop. A
# well-behaved project still exits inside this window; a console one is killed.
WINDOWS_TERM_GRACE_MS = 2_000

# How often a restart re-checks whether the old process has released its port.
# 40 attempts x 250ms = 10s, which covers the Windows socket-release lag.
RESTART_PORT_RETRY_MS = 250

# A PID is only remembered as "ours" for this long after its process finished.
# The set exists so a just-exited server is not mistaken for a foreign holder
# during shutdown/restart. Keeping it forever was a PID-reuse hazard: once the
# OS reused an old PID for an unrelated listener, the conflict check would
# silently treat that stranger as ours. Two minutes is far longer than socket
# release/restart needs and short enough to bound the window.
RETIRED_PID_TTL_S = 120.0

IS_WINDOWS = sys.platform.startswith("win")

# On POSIX, launching through `setsid` gives the project its own session and
# process group (the child PID is the group leader). The group is then the
# safest thing to signal: it contains only this project's descendants, never
# the Hub's own group. `setsid` is standard on Linux; macOS usually lacks the
# command, so the tree-snapshot fallback below is used there and the limitation
# is documented.
POSIX_SETSID = None if IS_WINDOWS else shutil.which("setsid")

# Windows' signal module has no SIGKILL (it has no POSIX signal semantics).
# The POSIX-only branches below use these constants; on Windows they are never
# reached at runtime, but a guarded value keeps imports and simulated tests
# from raising AttributeError.
_SIGTERM = signal.SIGTERM
_SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)

# Names that mean "whatever Python is installed" rather than a specific file.
_PYTHON_NAMES = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}


def _qt_alive(obj) -> bool:
    """False when Qt has already deleted this object's C++ side.

    A child QProcess can deliver its last signal while the ProjectProcess that
    owns it is being destroyed. Emitting or stopping timers then raises
    RuntimeError from shiboken; there is nothing left to update, so callers
    should simply return.
    """
    try:
        from shiboken6 import isValid
    except Exception:
        return True
    try:
        return bool(isValid(obj))
    except Exception:
        return True


def _taskkill_argv(pid: int) -> list[str]:
    """The exact Windows command used to end a process TREE.

    Split out so the target PID and the `/T` (tree) / `/F` (force) flags can be
    asserted behaviourally, without running taskkill against a real process.
    """
    return ["taskkill", "/PID", str(int(pid)), "/T", "/F"]


def _kill_process_tree(pid: int) -> None:
    """End `pid` and anything it spawned. Best-effort; never raises.

    taskkill is the only reliable route on Windows: QProcess.kill() ends the
    direct child but leaves its children (often the thing actually holding the
    port) alive. Failure here must not prevent the caller's own kill().
    """
    try:
        subprocess.run(
            _taskkill_argv(pid),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _looks_like_python(program: str) -> bool:
    """True when the program is a generic Python name, not a real path."""
    import os

    base = os.path.basename(program or "").lower()
    if os.sep in (program or "") or (os.altsep and os.altsep in (program or "")):
        return False  # an explicit path is used as-is
    return base in _PYTHON_NAMES


def _port_from_traceback(text: str) -> int | None:
    """The port named in a server's own traceback source line.

    A script that hardcodes its listener writes the port into the call that
    failed, and Python echoes that source line verbatim:

        HTTPServer(('127.0.0.1', 8787), H).serve_forever()
        self.socket.bind(('0.0.0.0', 8787))

    The address tuple is matched because that is what every socket-opening call
    in the stdlib and in the usual frameworks looks like. The same tuple can
    appear in two frames, and that is harmless: the first hit is the user's own
    frame (the outermost), which is the one that failed.

    Deliberately NOT matched: any bare number, which would match a line number.

    Guessing a port is safe by construction: the caller only acts on one that
    `_conflict_for_port()` confirms a FOREIGN process still holds, so a wrong
    number simply produces no offer rather than a wrong one.
    """
    m = re.search(r"\(\s*['\"][\da-fA-F.:\[\]]*['\"]\s*,\s*(\d{2,5})\s*\)", text)
    if m:
        return int(m.group(1))
    # Keyword form: `app.run(host="0.0.0.0", port=8481)`. Only in a traceback,
    # where the echoed source line is the failing call itself.
    m = re.search(r"\bport\s*=\s*(\d{2,5})\b", text)
    return int(m.group(1)) if m else None


def _find_foreign_port_holder(
    url: str, own_pids, fallback_port: int | None = None
) -> dict | None:
    """Shared conflict logic: None unless a process we did not launch holds it.

    Returns None when the port is free, when there is no URL, or when only our
    own processes still hold it (a restart, or the brief overlap while our own
    previous server shuts down). Only a genuinely foreign holder is reported,
    because that is the one case the user can meaningfully be asked about.

    `fallback_port` covers a project with no URL yet whose port is hardcoded in
    its script: without it the check has nothing to test and the start runs
    straight into "Address already in use".

    `own_pids` may be a set or a zero-argument callable. The callable form lets
    the (potentially process-table-reading) descendant lookup happen ONLY when
    a listener was actually found, not on every start.
    """
    try:
        host = None
        if url:
            host, port = urldetect.url_host_port(url)
        else:
            port = fallback_port
    except Exception:
        return None
    if not port or not urldetect.port_in_use(port, host):
        return None

    owners = urldetect.port_owners(port, host)
    if not owners:
        # Cannot tell who holds it. Refusing to start on an unidentifiable
        # holder would break legitimate restarts (the OS can lag releasing a
        # socket), so let the start proceed and let the server report its own
        # error if the port is truly unavailable.
        return None

    own = set(own_pids() if callable(own_pids) else own_pids)
    foreign = owners - own
    if not foreign:
        return None

    details = []
    for pid in sorted(foreign):
        details.append({"pid": pid, "command": urldetect.process_command(pid)})
    # A port recovered without a URL does not establish an address family.
    # Keep that uncertainty for consumers that recheck after termination.
    return {"port": port, "host": host, "holders": details}


def _detected_suppress_flag(rec: dict) -> str:
    """Read the current CLI contract without executing or editing the project.

    Saved descriptive evidence neither proves an option's arity nor that it
    still exists. Recompute only this runtime launch decision, including for
    pre-detection/v1 records; do not rewrite their saved configuration.
    """
    try:
        from .detect_type import detect, browser_suppress_args

        return browser_suppress_args(detect(rec))
    except Exception:
        return ""


class ProjectProcess(QObject):
    """One project's backend process + its captured output."""

    state_changed = Signal(str)  # "starting" | "running" | "stopped" | "error"
    output = Signal(str)
    # Emitted once, when the server's own output reveals its dashboard URL.
    url_detected = Signal(str)
    # A port this server failed to bind, read from its own traceback. Lets the
    # hub offer the port-conflict dialog even for projects with no configured
    # URL (the auto-detect case).
    port_conflict_from_output = Signal(int)

    def __init__(self, rec: dict, parent=None, term_grace_ms: int | None = None):
        super().__init__(parent)
        self.rec = rec
        self.proc: QProcess | None = None
        self.history: deque[str] = deque(maxlen=LOG_HISTORY)
        self._stdout_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._stdout_pending = ""
        self._start_failed = False
        self._user_stopped = False
        self._started_at = 0.0
        self._pending_restart = False
        self.detected_url: str | None = None
        # PIDs of processes this object started and is still running.
        # Kept separately from the live proc because Windows
        # QProcess.processId() returns 0 until the started signal, so
        # the live read alone can report nothing and our own server
        # then looks foreign to the port-conflict check.
        self._live_pids: set[int] = set()
        # pid -> process identity (creation/start token) captured at `started`.
        # A PID alone is not an identity; the OS can reuse it.
        self._live_identity: dict[int, str | None] = {}
        # pid -> (finished_at, identity). The TTL bounds the window; the
        # identity prevents a reused PID from being treated as ours. A missing
        # identity is never treated as proof of ownership for a live process.
        self._retired_pids: dict[int, tuple[float, str | None]] = {}
        # Which PID and identity each QProcess run got, keyed by id(proc), so
        # a late callback from an old process can still be retired correctly
        # without clobbering a replacement whose reused PID is now live.
        self._proc_pids: dict[int, int] = {}
        self._proc_identity: dict[int, str | None] = {}
        # POSIX-owned tree captured when a stop/restart begins. It lets the
        # escalation kill descendants that outlive the direct child/shell.
        self._tree_target: tuple[int, QProcess, int, dict[int, str | None]] | None = None
        # Generation of the restart currently waiting for the old port to free.
        # Repeated restart requests coalesce onto this wait instead of starting
        # a second server on a port that may still be bound.
        self._restart_waiting: int | None = None
        # Every start() gets a new generation. Escalation callbacks capture the
        # generation (and the process + PID) they were armed for, so a timer
        # left over from an earlier run can never kill its replacement.
        self._generation = 0
        self._kill_target: tuple[int, QProcess, int] | None = None
        # None uses the platform production grace; tests may inject a short one
        # without changing the shipped timeout.
        self._term_grace_ms = term_grace_ms
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(TERM_GRACE_MS)
        self._kill_timer.timeout.connect(self._on_kill_timer)

    # ---------- state ----------

    @property
    def is_stopping(self) -> bool:
        """A requested Stop is still waiting for this tracked child to exit."""
        return bool(self._user_stopped and not self._pending_restart
                    and self.proc is not None and self.proc.state() != QProcess.NotRunning)

    @property
    def state(self) -> str:
        if self.proc is None:
            return "stopped"
        s = self.proc.state()
        if s == QProcess.NotRunning:
            if self._start_failed:
                return "error"
            # Do NOT consult exitStatus(): in PySide6 it reports CrashExit even
            # for a clean SIGTERM (verified: code=15, exitStatus=CrashExit),
            # which would flag every user-initiated stop as an error. Judge by
            # who asked for the exit and the numeric code instead.
            if self._user_stopped:
                return "stopped"
            code = self.proc.exitCode()
            if code in (0, None):
                return "stopped"
            return "error"
        if s == QProcess.Starting:
            return "starting"
        return "running"

    def settings(self) -> dict:
        return self.rec

    def uptime(self) -> float:
        return 0.0 if not self._started_at else time.time() - self._started_at

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            return  # already running/starting
        # A new run supersedes any escalation armed for the previous one, even
        # if this start is refused below. Nothing from the old run may kill a
        # process this call goes on to create.
        self._generation += 1
        self._restart_waiting = None
        self._stop_kill_timer()
        self._start_failed = False
        # Refuse to start when a foreign process already holds this project's
        # port. This used to live only in HubWindow._launch(), so any other path
        # into start() -- tests, and any future headless use -- launched straight
        # into an occupied port. The child then died with "Address already in
        # use", or worse kept running and served the OTHER process's page as if
        # it were this project's dashboard. Checking here means every caller is
        # covered, and port_conflict() returns immediately when the port is free.
        conflict = self.port_conflict()
        if conflict:
            self.port_conflict_from_output.emit(0)
            self.state_changed.emit("error")
            self.output.emit(
                f"[hub] port {conflict['port']} is already in use by "
                f"{conflict.get('command') or 'another process'}; not starting.\n"
            )
            return
        try:
            argv = split_command(self.rec["command"])
        except ValueError as e:
            self.state_changed.emit("error")
            self.output.emit(f"[hub] cannot parse command: {e}\n")
            return
        if not argv:
            self.state_changed.emit("error")
            self.output.emit("[hub] empty command\n")
            return
        # Extra arguments are appended AFTER the command, so a project's own
        # flags can be set once without being retyped into the command box
        # (e.g. "--no-open" to stop a server opening its own browser, since the
        # hub already shows the dashboard in its own tab).
        extra = (self.rec.get("args") or "").strip()
        # If nothing was typed, fall back to what detection found: a server that
        # declares its own suppress flag in argparse gets it automatically, so
        # the user never has to know the flag exists (spec §2). Only ever a flag
        # the program itself declares — never a guessed one, which would break
        # the command. Skipped entirely when the user supplied args, so a
        # deliberate configuration is never second-guessed.
        if not extra:
            detected_flag = _detected_suppress_flag(self.rec)
            if detected_flag:
                extra = detected_flag
                self.output.emit(
                    f"[hub] {self.rec.get('name', 'project')} declares "
                    f"{detected_flag}; adding it so its own browser stays closed\n"
                )
        if extra:
            try:
                argv = argv + split_command(extra)
            except ValueError as e:
                self.state_changed.emit("error")
                self.output.emit(f"[hub] cannot parse extra arguments: {e}\n")
                return
        # An explicitly configured interpreter wins over whatever the command
        # names. This is what makes a project's own venv usable without typing
        # its full path into every command (release spec §3: "discovering or
        # selecting Python interpreters").
        argv = prepend_interpreter(argv, self.rec.get("interpreter") or "")
        program, args = argv[0], argv[1:]
        workdir = self.rec.get("working_dir") or None
        if workdir and os.path.dirname(program) and not os.path.isabs(program):
            # Windows resolves relative executables against the Hub, not the
            # child's setWorkingDirectory(). Anchor lexically: realpath/resolve
            # would follow a venv's Python symlink out of its environment.
            program = os.path.abspath(os.path.join(workdir, program))
        env_mods = dict(self.rec.get("env") or {})
        project_path = None
        for key, value in env_mods.items():
            if key == "PATH" or (IS_WINDOWS and key.upper() == "PATH"):
                project_path = value

        if project_path is not None and workdir:
            # PATH's relative/empty entries belong to the child's CWD. Resolve
            # lookup only; preserve the user's actual saved environment values.
            project_path = os.pathsep.join(
                os.path.abspath(os.path.join(workdir, entry)) if not os.path.isabs(entry) else entry
                for entry in project_path.split(os.pathsep)
            )
        # Resolve generic Python names using the project's effective PATH.
        # Windows also permits differently spelled Path/pAtH overrides and
        # installations exposing only python.exe or the py launcher.
        # Qt otherwise searches the Hub's parent PATH for bare tools too.
        # Keep language-neutral commands on the same explicit project PATH.
        needs_lookup = _looks_like_python(program) or (
            project_path is not None and not os.path.dirname(program)
        )
        resolved, err = (resolve_interpreter(program, path=project_path)
                         if needs_lookup else (program, None))
        if err:
            self.state_changed.emit("error")
            self.output.emit(f"[hub] {err}\n")
            return
        if (IS_WINDOWS and program.lower() in {"python3", "python3.exe"}
                and ntpath.basename(resolved or "").lower() in {"py", "py.exe"}):
            args = ["-3", *args]
        program = resolved or program

        self._stdout_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._stdout_pending = ""
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        if workdir:
            proc.setWorkingDirectory(workdir)
        env = QProcess.systemEnvironment()
        for k, v in env_mods.items():
            env.append(f"{k}={v}")
        # Python block-buffers stdout when it is not a tty, so a server launched
        # with a plain `python3 server.py` does not print its URL until the
        # buffer fills — long after the hub has given up looking, which leaves
        # the dashboard with no address to load. Unbuffered output is what the
        # project would do anyway on a terminal, so this changes no behaviour,
        # only when we get to see it. Set only if the user has not chosen one.
        if not any(e.startswith("PYTHONUNBUFFERED=") for e in env):
            env.append("PYTHONUNBUFFERED=1")
        proc.setEnvironment(env)
        # Bind each callback to the QProcess it belongs to. Reading
        # self.proc from inside a slot is what let a late `finished` from an
        # old process drain, retire and report the REPLACEMENT's state.
        proc.readyReadStandardOutput.connect(lambda p=proc: self._drain(p))
        proc.finished.connect(lambda code, status, p=proc: self._on_finished(code, status, p))
        proc.started.connect(lambda p=proc: self._on_started(p))
        proc.errorOccurred.connect(lambda error, p=proc: self._on_error(error, p))
        self._user_stopped = False
        self._started_at = time.time()
        self.proc = proc
        self.state_changed.emit("starting")
        if not IS_WINDOWS and POSIX_SETSID:
            # New session + process group, leader = the child PID. The Hub
            # itself is never in that group, so killpg() is scoped to this
            # project. setsid execs the target in place, so QProcess still
            # tracks the real process and its PID.
            proc.start(POSIX_SETSID, [program, *args])
        else:
            proc.start(program, args)

    def stop(self) -> None:
        # An explicit stop cancels a restart that is still waiting for the old
        # port to free: bumping the generation invalidates its retry chain, so
        # it cannot start the project after the user asked it to stop.
        self._pending_restart = False
        self._restart_waiting = None
        self._generation += 1
        if self.proc is None or self.proc.state() == QProcess.NotRunning:
            # Nothing to terminate — but the intent still matters. The start may
            # be in flight (the port-conflict probe launches asynchronously), so
            # record it and emit the state the caller expects; otherwise a stop
            # pressed during that window is silently dropped and the project's
            # tabs stay open.
            self._user_stopped = True
            self._pending_start = False
            # A second Stop after the launcher exited must not cancel a pending
            # descendant cleanup. If the captured tree still has verified
            # members, force them now rather than leaving an orphan.
            tree = self._tree_target
            if (
                not IS_WINDOWS
                and tree is not None
                and self._tree_has_live_members(tree[3])
            ):
                self._signal_owned_tree(tree[3], tree[2], _SIGKILL)
            self._stop_kill_timer()
            if self.state != "stopped":
                self.state_changed.emit("stopped")
            return
        self._user_stopped = True
        self.output.emit("[hub] terminating (waiting for a clean exit)...\n")
        pid = self._pid_of(self.proc)
        tree = self._snapshot_tree(pid)
        # One tracked escalation for both platforms. Windows gets the short
        # leash: terminate() posts WM_CLOSE, which a console process never
        # receives, so waiting out the POSIX grace would stall every stop.
        self._arm_escalation(self._grace_ms(), tree=tree)
        # Signal the whole owned tree, not only the direct child. On POSIX
        # this covers a shell/launcher and descendants that outlive it.
        self._signal_owned_tree(tree, pid, _SIGTERM)
        try:
            self.proc.terminate()
        except RuntimeError:
            pass

    def restart(self) -> None:
        running = self.proc is not None and self.proc.state() != QProcess.NotRunning
        if running:
            # Both Stop and Restart deliberately terminate the current child.
            # Keep that exit expected through the port-free wait; start() resets
            # the flag for the replacement so its own failures still report.
            # _pending_restart separately records the intent to launch again.
            self._user_stopped = True
            self._pending_restart = True
            self._restart_waiting = None
            self.output.emit("[hub] restarting...\n")
            pid = self._pid_of(self.proc)
            tree = self._snapshot_tree(pid)
            # Escalate on schedule rather than stalling the restart; if the
            # process exits politely first, _on_finished starts the new one.
            # Windows gets the short leash here too: terminate() cannot reach a
            # console process, so waiting out the full POSIX grace delays every
            # restart by 20s -- long enough that callers time out first and
            # report the project as stuck in 'starting'.
            self._arm_escalation(self._grace_ms(), tree=tree)
            self._signal_owned_tree(tree, pid, _SIGTERM)
            try:
                self.proc.terminate()
            except RuntimeError:
                pass
        elif self._restart_waiting == self._generation:
            # A port-free wait is already active. Coalesce: starting now would
            # bypass the wait and race the old child's socket, which is exactly
            # the failure the wait exists to prevent. The active wait will
            # start the replacement once the port is free.
            self.output.emit("[hub] restart already waiting for the port to free\n")
        else:
            self.start()

    # ---------- internals ----------

    def _grace_ms(self) -> int:
        """How long to wait after terminate() before force-killing.

        Production uses the platform constants. `term_grace_ms` exists only so
        tests can observe an escalation deadline without a 20-second wait; it
        never changes the shipped timeout.
        """
        if self._term_grace_ms is not None:
            return int(self._term_grace_ms)
        return WINDOWS_TERM_GRACE_MS if IS_WINDOWS else TERM_GRACE_MS

    def _stop_kill_timer(self) -> None:
        """Stop the escalation timer, tolerating an already-deleted QTimer.

        A child QProcess can emit its last `finished` while the Python wrapper
        (and therefore the C++ timer) is being torn down; calling stop() then
        raises RuntimeError from shiboken. There is nothing left to cancel.
        """
        try:
            self._kill_timer.stop()
        except RuntimeError:
            pass
        self._kill_target = None
        self._tree_target = None

    def _pid_of(self, proc: QProcess | None) -> int:
        if proc is None:
            return 0
        try:
            return int(proc.processId() or 0)
        except Exception:
            return 0

    def _snapshot_tree(self, pid: int) -> dict[int, str | None]:
        """Owned POSIX PIDs and their identities, captured before signalling.

        This is the fallback when a session/process group is unavailable (for
        example macOS without `setsid`) and a second safety net when a
        descendant moved to another group. Identity is recorded per PID so a
        reused number is never signalled later.
        """
        if IS_WINDOWS or not pid:
            return {}
        if pid != self._pid_of(self.proc):
            return {}
        # No recorded identity means no evidence this PID is ours. Never
        # enumerate or signal it on the strength of a number alone.
        expected = self._live_identity.get(pid)
        if expected is None:
            return {}
        rows = urldetect.process_snapshot()
        root = rows.get(pid)
        if root is None or root[1] != expected:
            return {}
        if urldetect.process_identity(pid) != expected:
            return {}
        children: dict[int, list[int]] = {}
        for member, (parent, _identity) in rows.items():
            children.setdefault(parent, []).append(member)
        out: dict[int, str | None] = {}
        queue = [pid]
        while queue:
            member = queue.pop()
            if member == os.getpid() or member in out:
                continue
            # Adopt only the identity paired with this member's ancestry row,
            # never a fresh identity read from a possibly reused PID.
            identity = rows[member][1]
            if identity is None:
                continue
            out[member] = identity
            queue.extend(children.get(member, ()))
        return out

    def _group_verified(self, pid: int, identity: str | None) -> bool:
        """True only when `pid` is the verified leader of its own group."""
        if IS_WINDOWS or not pid or not identity:
            return False
        if urldetect.process_identity(pid) != identity:
            return False
        try:
            return os.getpgid(pid) == pid
        except OSError:
            return False

    def _signal_owned_tree(
        self, tree: dict[int, str | None], root_pid: int, sig: int
    ) -> None:
        """Signal only verified members of this project's captured tree.

        A group signal is used only when the root is still the verified leader
        of its own group (created by `setsid`), so the Hub's own group can
        never be selected. Individually signalled PIDs are matched against the
        identity recorded at snapshot time; a reused PID is skipped. If no
        identity could be read, the PID is not signalled individually.
        """
        if IS_WINDOWS or not tree:
            return
        root_identity = tree.get(root_pid)
        if self._group_verified(root_pid, root_identity):
            try:
                os.killpg(root_pid, sig)
            except OSError:
                pass
        for pid, identity in tree.items():
            if pid == os.getpid() or identity is None:
                continue
            if urldetect.process_identity(pid) != identity:
                continue
            try:
                os.kill(pid, sig)
            except OSError:
                pass

    def _tree_has_live_members(self, tree: dict[int, str | None]) -> bool:
        if IS_WINDOWS or not tree:
            return False
        for pid, identity in tree.items():
            if pid == os.getpid() or identity is None:
                continue
            if urldetect.process_identity(pid) == identity:
                return True
        return False

    def _arm_escalation(
        self, delay_ms: int, tree: dict[int, str | None] | None = None
    ) -> None:
        """Schedule a force-kill that is valid only for the CURRENT run.

        The callback carries the generation, the QProcess object and its PID at
        scheduling time. Every one of those is re-checked when it fires, so an
        escalation left over from an earlier restart cannot kill the process
        that replaced it. The optional tree snapshot lets escalation reap
        descendants that outlive the direct child/launcher.
        """
        self._stop_kill_timer()
        if self.proc is None:
            return
        pid = self._pid_of(self.proc)
        self._kill_target = (self._generation, self.proc, pid)
        if not IS_WINDOWS:
            self._tree_target = (
                self._generation,
                self.proc,
                pid,
                dict(tree or {}),
            )
        try:
            self._kill_timer.start(int(delay_ms))
        except RuntimeError:
            self._kill_target = None  # timer already deleted with the object
            self._tree_target = None

    def _on_kill_timer(self) -> None:
        target, self._kill_target = self._kill_target, None
        if target is not None:
            self._force_kill_if_current(*target)

    def _force_kill_if_current(self, generation: int, proc: QProcess, pid: int) -> None:
        """Force-kill only when the target is still the run it was armed for."""
        if generation != self._generation:
            return
        if proc is None or self.proc is not proc:
            return
        try:
            state = proc.state()
        except RuntimeError:
            return  # the QProcess was already deleted
        if state == QProcess.NotRunning:
            # The direct child exited but the captured owned tree may still
            # hold descendants that outlived a shell/launcher.
            self._force_kill_tree(generation)
            return
        actual = self._pid_of(proc)
        if pid and actual and actual != pid:
            # The same QProcess now points at a different child (or the OS
            # reused the handle). Do not signal an unverified process.
            return
        self._force_kill(proc)

    def _force_kill_tree(self, generation: int) -> None:
        target = self._tree_target
        if target is None or target[0] != generation:
            return
        _generation, _proc, root_pid, tree = target
        self.output.emit(
            "[hub] still running after the grace period, killing the process tree\n"
        )
        self._signal_owned_tree(tree, root_pid, _SIGKILL)
        self._tree_target = None

    def _drain(self, proc: QProcess | None = None, *, final: bool = False) -> None:
        if not _qt_alive(self):
            return
        proc = proc if proc is not None else self.proc
        if proc is None or proc is not self.proc:
            return  # a late read from a superseded run
        try:
            raw = bytes(proc.readAllStandardOutput())
        except RuntimeError:
            return
        if not raw and not final:
            return
        data = self._stdout_decoder.decode(raw, final=final)
        if data:
            self.history.append(data)
            self.output.emit(data)
        # Pipe reads are arbitrary bytes, not complete log lines or URL tokens.
        # Never commit :8 when the next read completes :8123/dashboard.
        lines = re.split(r"[\r\n]", self._stdout_pending + data)
        tail = lines.pop()
        for line in lines:
            self._maybe_detect_url(line)
        if final:
            self._maybe_detect_url(tail)
            self._stdout_pending = ""
        else:
            boundary = max(tail.rfind(" "), tail.rfind("\t"))
            if boundary >= 0:
                self._maybe_detect_url(tail[:boundary + 1])
            # Bound an unterminated noisy line; keep original streamed logs.
            self._stdout_pending = tail[-65536:]

    # ---------- URL auto-detection ----------

    def port_conflict(self) -> dict | None:
        """A FOREIGN process holding this project's dashboard port, or None.

        Synchronous, and cheap when the port is free (it returns before running
        lsof). Callers on the GUI thread must only reach it on that fast path.
        """
        return _find_foreign_port_holder(
            self.rec.get("url"), self._own_pids, fallback_port=self._expected_port()
        )

    def _expected_port(self) -> int | None:
        """The port this project will bind, even with no URL configured.

        A fresh project has no URL yet, and its port is often hardcoded inside
        the script (`PORT = ... else 8471`) so it is not on the command line
        either. Without this the pre-start check has nothing to test, the start
        runs into a guaranteed "Address already in use", and the hub loops
        restarting a server that can never come up.
        """
        det = self.rec.get("detected") or {}
        port = det.get("port")
        if port:
            return int(port)
        # The configured URL is the next-best source, and it is the common case:
        # a project added by hand has a URL but no detected block. Without this
        # the restart port-wait silently does nothing, and on Windows the
        # replacement server dies with "Address already in use" because the old
        # child still holds the socket.
        url = str(self.rec.get("url") or "")
        if url:
            try:
                _, url_port = url_host_port(url)
                return url_port
            except ValueError:
                pass
        # No detected port: read the entry script named on the command line.
        from .detect_type import _entry_script_path, _script_default_port

        script = _entry_script_path(
            str(self.rec.get("command") or ""), str(self.rec.get("working_dir") or "")
        )
        return _script_default_port(script)

    def _own_pids(self) -> set[int]:
        """PIDs this object launched, verified by process identity.

        This stops a normal restart from being mistaken for a foreign port
        conflict — our own previous server may briefly still hold the port as
        it shuts down. A retired PID is trusted only while its recorded
        identity still matches the process currently at that PID; a reused PID
        is never treated as ours. The TTL remains a fallback bound, and an
        unreadable identity is never accepted as proof of ownership for a live
        process.
        """
        now = time.time()
        current_pid = self._pid_of(self.proc)
        running = False
        if self.proc is not None:
            try:
                running = self.proc.state() != QProcess.NotRunning
            except RuntimeError:
                running = False

        mine: set[int] = set()
        for pid, (seen_at, identity) in list(self._retired_pids.items()):
            if now - seen_at > RETIRED_PID_TTL_S:
                del self._retired_pids[pid]
                continue
            current = urldetect.process_identity(pid)
            if current is None:
                if not urldetect.process_alive(pid):
                    # The PID is unused; keeping it as a root is harmless and
                    # lets the tree lookup find a still-linked child.
                    mine.add(pid)
                continue
            if identity is not None and current == identity:
                mine.add(pid)
            # A different (or unreadable) live identity is not evidence.

        for pid in self._live_pids:
            if pid == current_pid:
                mine.add(pid)
                continue
            identity = self._live_identity.get(pid)
            if identity is None:
                continue
            if urldetect.process_identity(pid) == identity:
                mine.add(pid)

        if current_pid:
            if running:
                mine.add(current_pid)
            else:
                identity = self._live_identity.get(current_pid)
                if (
                    identity is not None
                    and urldetect.process_identity(current_pid) == identity
                ):
                    mine.add(current_pid)

        # Include descendants. On Windows a venv (or shell) launcher is the
        # direct QProcess child, while the process that binds the port is the
        # interpreter it spawns. Without these, the hub treats its OWN server
        # as a foreign holder and offers to kill it.
        return urldetect.process_tree_pids(mine)

    def _maybe_detect_url(self, text: str) -> None:
        """Learn the dashboard URL from what the server prints.

        Most servers announce themselves ("serving on http://localhost:8471"),
        so the user should not have to type it. Emits url_detected once, the
        first time a plausible URL appears; the caller decides whether to use
        it (it never overrides a URL the user configured themselves).
        """
        if self.detected_url or self.rec.get("url"):
            return
        url = urldetect.find_url(text)
        if not url:
            return
        # 0.0.0.0 means "all interfaces"; connect via localhost instead.
        self.detected_url = url.replace("0.0.0.0", "127.0.0.1")
        self.url_detected.emit(self.detected_url)

    def detect_url_from_ports(self) -> str | None:
        """Fallback for servers that start silently: ask the OS what it opened.

        Best-effort. Only consulted when nothing was learned from stdout.
        """
        if self.detected_url or self.proc is None:
            return self.detected_url
        pid = self.proc.processId()
        ports = urldetect.listening_ports(pid)
        if ports:
            self.detected_url = urldetect.url_from_port(ports[0])
            self.url_detected.emit(self.detected_url)
        return self.detected_url

    def _on_error(self, error, proc: QProcess | None = None) -> None:
        """A failed OS spawn has no finished signal; surface its actual cause."""
        if not _qt_alive(self):
            return
        proc = proc if proc is not None else self.proc
        if proc is None or proc is not self.proc or error != QProcess.FailedToStart:
            return
        self._start_failed = True
        self._started_at = 0.0
        self.output.emit(f"[hub] could not start {proc.program()}: {proc.errorString()}\n")
        self.state_changed.emit("error")

    def _on_started(self, proc: QProcess | None = None) -> None:
        # QProcess reports Running but nothing forwards it; without this the
        # window never learns the process is up, so it never starts the
        # readiness poll and the dashboard never loads ("stuck on Starting…").
        #
        # Also the moment to remember the PID as ours. On Windows
        # QProcess.processId() returns 0 until this signal fires, so reading it
        # earlier -- and anywhere in between -- would report no PID at all, and
        # port_conflict() would then see our own running server as a foreign
        # holder and refuse to start or prompt to kill it. Remembering it here
        # closes that window on every platform.
        if not _qt_alive(self):
            return
        proc = proc if proc is not None else self.proc
        if proc is None:
            return
        pid = self._pid_of(proc)
        if pid:
            # Record ownership even if this run was superseded: the PID is
            # still ours, and must not look foreign while it shuts down.
            identity = urldetect.process_identity(pid)
            self._proc_pids[id(proc)] = pid
            self._proc_identity[id(proc)] = identity
            self._live_identity[pid] = identity
            self._live_pids.add(pid)
        if proc is not self.proc:
            return  # a late `started` from an older run
        self.state_changed.emit("running")

    def _force_kill(self, proc: QProcess | None = None) -> None:
        if not _qt_alive(self):
            return
        proc = proc if proc is not None else self.proc
        if proc is None:
            return
        try:
            if proc.state() == QProcess.NotRunning:
                return
        except RuntimeError:
            return
        pid = self._pid_of(proc)
        self.output.emit("[hub] still running after the grace period, killing\n")
        # On Windows, QProcess::terminate() posts WM_CLOSE, which a console
        # application never receives -- `python server.py` simply ignores it and
        # keeps holding its port. kill() alone has the same problem for anything
        # the process spawned. taskkill /T /F is the only reliable route, and it
        # takes the whole tree so no orphaned child keeps the port bound.
        if IS_WINDOWS:
            if pid:
                _kill_process_tree(pid)
        else:
            target = self._tree_target
            if (
                target is not None
                and target[0] == self._generation
                and target[1] is proc
            ):
                self._signal_owned_tree(target[3], target[2], _SIGKILL)
                self._tree_target = None
            elif pid:
                # No snapshot (e.g. a direct caller): only signal a PID whose
                # current identity still matches the one recorded at start.
                identity = self._live_identity.get(pid)
                if (
                    identity is not None
                    and urldetect.process_identity(pid) == identity
                ):
                    try:
                        os.kill(pid, _SIGKILL)
                    except OSError:
                        pass
        try:
            proc.kill()
        except RuntimeError:
            pass  # already deleted

    def _on_finished(self, code: int, status, proc: QProcess | None = None) -> None:
        if not _qt_alive(self):
            return
        proc = proc if proc is not None else self.proc
        # `proc` may legitimately be None here (a test driving a finish from
        # recorded history, or a stop during an in-flight start). The
        # history/conflict path below does not need a process object; only the
        # PID and drain steps are skipped.
        # Retire this run's PID even when the callback arrives late. Doing it
        # for a superseded process too keeps our own old child from ever being
        # mistaken for a foreign port holder.
        pid = self._proc_pids.pop(id(proc), 0) or self._pid_of(proc)
        identity = self._proc_identity.pop(id(proc), None)
        if pid:
            # Do not clobber a replacement that reused this PID. Clear the
            # live entry only when its identity matches this finished run (or
            # neither side has an identity to distinguish them).
            if self._live_identity.get(pid) == identity:
                self._live_identity.pop(pid, None)
                self._live_pids.discard(pid)
            self._retired_pids[pid] = (time.time(), identity)
        if proc is not self.proc:
            # A late `finished` from a superseded run must not drain, reset the
            # timer, emit state, or start a restart on behalf of its
            # replacement.
            return
        # Pull whatever the process wrote last before looking at anything.
        # QProcess emits `finished` without promising that every
        # readyRead arrived first: the child's final write (for a dying Python
        # server, the whole "Address already in use" traceback) can still be in
        # the pipe. Reading it here is the only way to know it will not be
        # lost — and if it IS lost, `_failed_to_bind()` sees an empty
        # `history`, returns False, no conflict signal fires, and the user gets
        # a silent 'Address already in use' with no offer to free the port.
        # That race is lost on Windows and won on macOS, which is why this
        # looked like a Windows-only bug for days.
        self._drain(proc, final=True)
        # The `status` arg is unreliable in PySide6 (reports CrashExit for a
        # clean SIGTERM), so it is intentionally unused here; the state
        # property decides error vs stopped from _user_stopped + exit code.
        #
        # If the direct child exited but the captured POSIX tree still has
        # verified members, keep the escalation timer armed so descendants
        # that outlived a shell/launcher are eventually killed. Otherwise the
        # timer is torn down now.
        tree = self._tree_target
        if not (
            not IS_WINDOWS
            and tree is not None
            and tree[0] == self._generation
            and self._tree_has_live_members(tree[3])
        ):
            self._stop_kill_timer()
        self.output.emit(f"[hub] process exited (code={code})\n")

        # A server that dies because its port was taken is a conflict even when
        # the port cannot be read from the command ("python3 obs_live.py" binds
        # a default inside the script). Emit regardless so the window can look
        # for what is actually holding a port — otherwise a port-less command
        # silently skips the whole conflict path.
        if not self._user_stopped and code not in (0, None):
            if self._failed_to_bind():
                self.port_conflict_from_output.emit(self._port_from_failure_output() or 0)

        if self._user_stopped:
            self.state_changed.emit("stopped")
        elif code in (0, None):
            self.state_changed.emit("stopped")
        else:
            self.state_changed.emit("error")
        if self._pending_restart:
            self._pending_restart = False
            self._restart_after_port_free(generation=self._generation)

    def _restart_after_port_free(self, attempts: int = 40, generation: int | None = None) -> None:
        """Start the replacement, waiting for the old process to release the port.

        On Windows a terminated child keeps its listening socket briefly, so
        restarting the instant `finished` fires makes the new server fail with
        "Address already in use" and die -- leaving the project stuck in
        'starting' with nothing listening. This is why test_restart failed on
        Windows only: the same race is invisible on POSIX, where the socket is
        released before the process is reaped.

        Bounded, and it gives up honestly: if the port never frees, the state
        reports the failure instead of looping forever. A retry chain from a
        superseded run stops as soon as a newer generation exists.
        """
        if generation is None:
            generation = self._generation
        if generation != self._generation:
            # A newer start/stop superseded this chain. Do not touch a newer
            # wait that belongs to another generation.
            if self._restart_waiting == generation:
                self._restart_waiting = None
            return
        # Record the active wait. restart() checks this and coalesces rather
        # than starting a second server on a port the old child may still hold.
        self._restart_waiting = generation
        port = self._expected_port()
        host = None
        url = self.rec.get("url")
        if url:
            try:
                url_host, url_port = urldetect.url_host_port(url)
                if url_port == port:
                    host = url_host
            except ValueError:
                pass
        # A known literal endpoint must not be blocked by a disjoint family.
        # If only a port is known, still check both IPv4 and IPv6.
        if port and urldetect.port_in_use(port, host):
            if attempts > 0:
                QTimer.singleShot(
                    RESTART_PORT_RETRY_MS,
                    lambda: self._restart_after_port_free(attempts - 1, generation),
                )
                return
            if self._restart_waiting == generation:
                self._restart_waiting = None
            self.output.emit(
                f"[hub] port {port} is still held; cannot restart\n"
            )
            self.state_changed.emit("error")
            return
        if self._restart_waiting == generation:
            self._restart_waiting = None
        self.start()

    def _failed_to_bind(self) -> bool:
        """True when this process died because its port was already taken.

        Matched on the error text rather than a port number, because the port
        is often not recoverable from the output at all.

        Every platform words this differently, and matching only the macOS/Linux
        phrasings meant the Windows equivalent went unrecognised: the signal that
        triggers the "end that process" offer never fired, so a project whose
        port was taken just died silently. The three wordings, and the errno for
        each:

            macOS   OSError: [Errno 48] Address already in use
            Linux   OSError: [Errno 98] Address already in use
            Windows OSError: [WinError 10048] Only one usage of each socket
                    address (protocol/network address/port) is normally permitted.

        Linux is covered by the shared "Address already in use" phrase, which is
        why this only ever bit on Windows.
        """
        text = "".join(self.history)
        return (
            "Address already in use" in text
            or "Errno 48" in text
            or "WinError 10048" in text
            or "Only one usage of each socket address" in text
        )

    def _port_from_failure_output(self) -> int | None:
        """The port this server failed to bind, so the hub can offer to free it.

        Python's traceback rarely contains the literal number — it prints
        `("127.0.0.1", args.port)` and then `self.socket.bind(self.server_address)`,
        never resolving it. So the port is taken from the COMMAND instead: an
        explicit `--port N` / `-p N`, else a bare trailing number, else a
        `:N` in any URL-ish argument. Returns None when no port can be found,
        which is fine: the caller only prompts when something foreign still
        holds the port anyway.
        """
        text = "".join(self.history)
        if not self._failed_to_bind():
            return None

        argv = self.rec.get("command") or ""
        # --port 8787 / --port=8787 / -p 8787
        m = re.search(r"(?:--port|-p)(?:\s+|=)(\d{2,5})\b", argv)
        if m:
            return int(m.group(1))
        # a bare trailing number: "python3 obs_live.py 8787"
        m = re.search(r"(?:^|\s)(\d{2,5})\s*$", argv.strip())
        if m:
            return int(m.group(1))
        # a URL-ish argument carrying a port: "http://127.0.0.1:8787"
        m = re.search(r":(\d{2,5})(?![\d.])", argv)
        if m:
            return int(m.group(1))
        # The traceback itself. A script that hardcodes its listener writes it
        # into the call that failed, and Python echoes that source line:
        #     HTTPServer(('127.0.0.1', 8787), H).serve_forever()
        # so the number IS recoverable — the entry-script scan below only looks
        # for an assigned `PORT =`, which such a script never has. Without this
        # the port came back None on every platform, the signal fired with 0,
        # and the offer depended on netstat ordering happening to list the port.
        port = _port_from_traceback(text)
        if port:
            return port
        # Last resort: the entry script hardcodes its port, e.g.
        # `PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8471`. Nothing on
        # the command line reveals that, so read the script as TEXT (never
        # import or execute it) and take the default. The traceback names the
        # file, which is how we know it is safe to look.
        return self._port_from_entry_script(text)

    def _port_from_entry_script(self, text: str) -> int | None:
        """The default port a hardcoded entry script would have bound.

        Finds the .py file named in the traceback, reads it as text, and takes
        a module-level `PORT = <number>` (or `port = <number>`). Read-only: the
        script is never imported or run.
        """
        m = re.search(r'File "([^"\n]+\.py)"', text)
        if not m:
            return None
        script = m.group(1)
        try:
            with open(script, encoding="utf-8", errors="replace") as fh:
                source = fh.read(256_000)
        except (OSError, ValueError):
            return None
        # `PORT = 8471` or `port = 8471` at module level; the ternary form in
        # server.py ends in `else 8471`, so also accept that trailing number.
        m = re.search(r"^\s*(?:PORT|port)\s*=\s*(\d{2,5})\s*$", source, re.M)
        if m:
            return int(m.group(1))
        m = re.search(r"^\s*(?:PORT|port)\s*=.*?else\s+(\d{2,5})", source, re.M)
        if m:
            return int(m.group(1))
        return None
