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

import re
import subprocess
import sys
import time
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .platform import resolve_interpreter, split_command
from .readiness import tcp_open, url_host_port
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

IS_WINDOWS = sys.platform.startswith("win")

# Names that mean "whatever Python is installed" rather than a specific file.
_PYTHON_NAMES = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}


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
    url: str, own_pids: set[int], fallback_port: int | None = None
) -> dict | None:
    """Shared conflict logic: None unless a process we did not launch holds it.

    Returns None when the port is free, when there is no URL, or when only our
    own processes still hold it (a restart, or the brief overlap while our own
    previous server shuts down). Only a genuinely foreign holder is reported,
    because that is the one case the user can meaningfully be asked about.

    `fallback_port` covers a project with no URL yet whose port is hardcoded in
    its script: without it the check has nothing to test and the start runs
    straight into "Address already in use".
    """
    try:
        if url:
            _, port = urldetect.url_host_port(url)
        else:
            port = fallback_port
    except Exception:
        return None
    if not port or not urldetect.port_in_use(port):
        return None

    owners = urldetect.port_owners(port)
    if not owners:
        # Cannot tell who holds it. Refusing to start on an unidentifiable
        # holder would break legitimate restarts (the OS can lag releasing a
        # socket), so let the start proceed and let the server report its own
        # error if the port is truly unavailable.
        return None

    foreign = owners - own_pids
    if not foreign:
        return None

    details = []
    for pid in sorted(foreign):
        details.append({"pid": pid, "command": urldetect.process_command(pid)})
    return {"port": port, "host": "127.0.0.1", "holders": details}


def _detected_suppress_flag(rec: dict) -> str:
    """The browser-suppress flag this project's own code declares, or "".

    Prefers the stored detection (already computed, no re-read), and falls back
    to running detection when a record has none — so a project added before the
    `detected` block existed still benefits. Returns "" for anything that does
    not declare a flag, which is what keeps spec §2's "never guess a flag"
    honest.
    """
    det_block = rec.get("detected")
    if isinstance(det_block, dict) and det_block.get("evidence"):
        try:
            from .detect_type import Detection, browser_suppress_args

            return browser_suppress_args(Detection.from_dict(det_block))
        except Exception:
            return ""
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

    def __init__(self, rec: dict, parent=None):
        super().__init__(parent)
        self.rec = rec
        self.proc: QProcess | None = None
        self.history: deque[str] = deque(maxlen=LOG_HISTORY)
        self._user_stopped = False
        self._started_at = 0.0
        self._pending_restart = False
        self.detected_url: str | None = None
        # PIDs this object launched that have since exited, so a restart does
        # not mistake its own shutting-down server for a foreign port conflict.
        self._retired_pids: set[int] = set()
        # PIDs of processes this object started and is still running.
        # Kept separately from the live proc because Windows
        # QProcess.processId() returns 0 until the started signal, so
        # the live read alone can report nothing and our own server
        # then looks foreign to the port-conflict check.
        self._live_pids: set[int] = set()
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(TERM_GRACE_MS)
        self._kill_timer.timeout.connect(self._force_kill)

    # ---------- state ----------

    @property
    def state(self) -> str:
        if self.proc is None:
            return "stopped"
        s = self.proc.state()
        if s == QProcess.NotRunning:
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
        interpreter = (self.rec.get("interpreter") or "").strip()
        if interpreter:
            argv = [interpreter] + argv
        program, args = argv[0], argv[1:]
        env_mods = dict(self.rec.get("env") or {})

        # A bare "python3" does not exist on Windows (the launcher is "python"
        # or "py"), and the hub's own bundled interpreter must win when the
        # command says "python3" but none is on PATH. Resolve it once here so
        # the error the user sees names the fix instead of "file not found".
        resolved, err = resolve_interpreter(program) if _looks_like_python(program) else (program, None)
        if err:
            self.state_changed.emit("error")
            self.output.emit(f"[hub] {err}\n")
            return
        program = resolved or program

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        workdir = self.rec.get("working_dir") or None
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
        proc.readyReadStandardOutput.connect(self._drain)
        proc.finished.connect(self._on_finished)
        proc.started.connect(self._on_started)
        self._user_stopped = False
        self._started_at = time.time()
        self.proc = proc
        self.state_changed.emit("starting")
        proc.start(program, args)

    def stop(self) -> None:
        if self.proc is None or self.proc.state() == QProcess.NotRunning:
            # Nothing to terminate — but the intent still matters. The start may
            # be in flight (the port-conflict probe launches asynchronously), so
            # record it and emit the state the caller expects; otherwise a stop
            # pressed during that window is silently dropped and the project's
            # tabs stay open.
            self._user_stopped = True
            self._pending_start = False
            if self.state != "stopped":
                self.state_changed.emit("stopped")
            return
        self._user_stopped = True
        self.output.emit("[hub] terminating (waiting up to 20s for a clean exit)...\n")
        self.proc.terminate()
        self._kill_timer.start()
        if IS_WINDOWS:
            # On Windows terminate() posts WM_CLOSE, which a console process
            # never receives, so waiting out the full grace would stall every
            # stop. Escalate promptly instead: kill() is the only signal that
            # reliably ends a Windows console child, and the shortened grace
            # still gives a well-behaved project room to exit on its own.
            QTimer.singleShot(WINDOWS_TERM_GRACE_MS, self._force_kill)

    def restart(self) -> None:
        running = self.proc is not None and self.proc.state() != QProcess.NotRunning
        if running:
            # A restart must not read as the user's intent to stop: the exit is
            # expected, and a fresh start follows in _on_finished.
            self._user_stopped = False
            self._pending_restart = True
            self._kill_timer.stop()
            self.output.emit("[hub] restarting...\n")
            self.proc.terminate()
            # Escalate on schedule rather than stalling the restart; if the
            # process exits politely first, _on_finished starts the new one.
            # Windows gets the short leash here too: terminate() cannot reach a
            # console process, so waiting out the full POSIX grace delays every
            # restart by 20s -- long enough that callers time out first and
            # report the project as stuck in 'starting'.
            QTimer.singleShot(
                WINDOWS_TERM_GRACE_MS if IS_WINDOWS else TERM_GRACE_MS,
                self._force_kill,
            )
        else:
            self.start()

    # ---------- internals ----------

    def _drain(self) -> None:
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self.history.append(data)
            self.output.emit(data)
            self._maybe_detect_url(data)

    # ---------- URL auto-detection ----------

    def port_conflict(self) -> dict | None:
        """A FOREIGN process holding this project's dashboard port, or None.

        Synchronous, and cheap when the port is free (it returns before running
        lsof). Callers on the GUI thread must only reach it on that fast path.
        """
        return _find_foreign_port_holder(
            self.rec.get("url"), self._own_pids(), fallback_port=self._expected_port()
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
        """PIDs this object launched: the live one plus any it has retired.

        This is what stops a normal restart from being mistaken for a foreign
        port conflict — our own previous server may briefly still hold the port
        as it shuts down.
        """
        mine = set(self._retired_pids) | set(self._live_pids)
        if self.proc is not None:
            try:
                pid = self.proc.processId()
                if pid:
                    mine.add(pid)
            except Exception:
                pass
        return mine

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

    def _on_started(self) -> None:
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
        try:
            pid = self.proc.processId() if self.proc is not None else 0
        except Exception:
            pid = 0
        if pid:
            self._live_pids.add(pid)
        self.state_changed.emit("running")

    def _force_kill(self) -> None:
        if self.proc is None or self.proc.state() == QProcess.NotRunning:
            return
        self.output.emit("[hub] still running after the grace period, killing\n")
        # On Windows, QProcess::terminate() posts WM_CLOSE, which a console
        # application never receives -- `python server.py` simply ignores it and
        # keeps holding its port. kill() alone has the same problem for anything
        # the process spawned. taskkill /T /F is the only reliable route, and it
        # takes the whole tree so no orphaned child keeps the port bound.
        if IS_WINDOWS and self.proc.processId():
            subprocess.run(
                ["taskkill", "/PID", str(self.proc.processId()), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        self.proc.kill()

    def _on_finished(self, code: int, status) -> None:
        # Remember the PID so port_conflict() does not mistake our own
        # just-exited server for a foreign process holding the port. This is
        # what keeps a normal restart from prompting the user to kill anything.
        if self.proc is not None:
            try:
                pid = self.proc.processId()
                if pid:
                    self._retired_pids.add(pid)
                    self._live_pids.discard(pid)
            except Exception:
                pass
        # The `status` arg is unreliable in PySide6 (reports CrashExit for a
        # clean SIGTERM), so it is intentionally unused here; the state
        # property decides error vs stopped from _user_stopped + exit code.
        self._kill_timer.stop()
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
            self._restart_after_port_free()

    def _restart_after_port_free(self, attempts: int = 40) -> None:
        """Start the replacement, waiting for the old process to release the port.

        On Windows a terminated child keeps its listening socket briefly, so
        restarting the instant `finished` fires makes the new server fail with
        "Address already in use" and die -- leaving the project stuck in
        'starting' with nothing listening. This is why test_restart failed on
        Windows only: the same race is invisible on POSIX, where the socket is
        released before the process is reaped.

        Bounded, and it gives up honestly: if the port never frees, the state
        reports the failure instead of looping forever.
        """
        port = self._expected_port()
        # Reuse the readiness helper rather than opening a second socket path:
        # a busy port is a busy port, however it is probed.
        if port and tcp_open("127.0.0.1", port):
            if attempts > 0:
                QTimer.singleShot(RESTART_PORT_RETRY_MS, lambda: self._restart_after_port_free(attempts - 1))
                return
            self.output.emit(
                f"[hub] port {port} is still held; cannot restart\n"
            )
            self.state_changed.emit("error")
            return
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
