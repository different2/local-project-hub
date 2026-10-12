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
import time
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .platform import resolve_interpreter, split_command
from . import urldetect

LOG_HISTORY = 500

# Grace given to a project to exit after SIGTERM before we escalate to SIGKILL.
TERM_GRACE_MS = 20_000

# Names that mean "whatever Python is installed" rather than a specific file.
_PYTHON_NAMES = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}


def _looks_like_python(program: str) -> bool:
    """True when the program is a generic Python name, not a real path."""
    import os

    base = os.path.basename(program or "").lower()
    if os.sep in (program or "") or (os.altsep and os.altsep in (program or "")):
        return False  # an explicit path is used as-is
    return base in _PYTHON_NAMES


def _find_foreign_port_holder(url: str, own_pids: set[int]) -> dict | None:
    """Shared conflict logic: None unless a process we did not launch holds it.

    Returns None when the port is free, when there is no URL, or when only our
    own processes still hold it (a restart, or the brief overlap while our own
    previous server shuts down). Only a genuinely foreign holder is reported,
    because that is the one case the user can meaningfully be asked about.
    """
    if not url:
        return None
    try:
        host, port = urldetect.url_host_port(url)
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
    return {"port": port, "host": host, "holders": details}


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
        self.output.emit("[hub] terminating (waiting up to 20s for a clean exit)…\n")
        self.proc.terminate()
        self._kill_timer.start()

    def restart(self) -> None:
        running = self.proc is not None and self.proc.state() != QProcess.NotRunning
        if running:
            # A restart must not read as the user's intent to stop: the exit is
            # expected, and a fresh start follows in _on_finished.
            self._user_stopped = False
            self._pending_restart = True
            self._kill_timer.stop()
            self.output.emit("[hub] restarting…\n")
            self.proc.terminate()
            # Escalate on schedule rather than stalling the restart; if the
            # process exits politely first, _on_finished starts the new one.
            QTimer.singleShot(TERM_GRACE_MS, self._force_kill)
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
        return _find_foreign_port_holder(self.rec.get("url"), self._own_pids())

    def _own_pids(self) -> set[int]:
        """PIDs this object launched: the live one plus any it has retired.

        This is what stops a normal restart from being mistaken for a foreign
        port conflict — our own previous server may briefly still hold the port
        as it shuts down.
        """
        mine = set(self._retired_pids)
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
        self.state_changed.emit("running")

    def _force_kill(self) -> None:
        if self.proc is None or self.proc.state() == QProcess.NotRunning:
            return
        self.output.emit("[hub] still running after the grace period, killing\n")
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
            except Exception:
                pass
        # The `status` arg is unreliable in PySide6 (reports CrashExit for a
        # clean SIGTERM), so it is intentionally unused here; the state
        # property decides error vs stopped from _user_stopped + exit code.
        self._kill_timer.stop()
        self.output.emit(f"[hub] process exited (code={code})\n")

        # A server that dies because its port was taken names the port in its
        # own error ("[Errno 48] Address already in use"). Learn it and treat
        # it like a pre-start conflict: the port is discoverable this way even
        # for projects that have no configured URL (the auto-detect case).
        if not self._user_stopped and code not in (0, None):
            clash = self._port_from_failure_output()
            if clash:
                self.port_conflict_from_output.emit(clash)

        if self._user_stopped:
            self.state_changed.emit("stopped")
        elif code in (0, None):
            self.state_changed.emit("stopped")
        else:
            self.state_changed.emit("error")
        if self._pending_restart:
            self._pending_restart = False
            self.start()

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
        if "Address already in use" not in text and "Errno 48" not in text:
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
        return None
