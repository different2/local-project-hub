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

import shlex
import time
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

LOG_HISTORY = 500

# Grace given to a project to exit after SIGTERM before we escalate to SIGKILL.
TERM_GRACE_MS = 20_000


class ProjectProcess(QObject):
    """One project's backend process + its captured output."""

    state_changed = Signal(str)  # "starting" | "running" | "stopped" | "error"
    output = Signal(str)

    def __init__(self, rec: dict, parent=None):
        super().__init__(parent)
        self.rec = rec
        self.proc: QProcess | None = None
        self.history: deque[str] = deque(maxlen=LOG_HISTORY)
        self._user_stopped = False
        self._started_at = 0.0
        self._pending_restart = False
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
            argv = shlex.split(self.rec["command"])
        except ValueError as e:
            self.state_changed.emit("error")
            self.output.emit(f"[hub] cannot parse command: {e}\n")
            return
        if not argv:
            self.state_changed.emit("error")
            self.output.emit("[hub] empty command\n")
            return
        program, args = argv[0], argv[1:]
        env_mods = dict(self.rec.get("env") or {})

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
        self._user_stopped = False
        self._started_at = time.time()
        self.proc = proc
        self.state_changed.emit("starting")
        proc.start(program, args)

    def stop(self) -> None:
        if self.proc is None or self.proc.state() == QProcess.NotRunning:
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

    def _force_kill(self) -> None:
        if self.proc is None or self.proc.state() == QProcess.NotRunning:
            return
        self.output.emit("[hub] still running after the grace period, killing\n")
        self.proc.kill()

    def _on_finished(self, code: int, status) -> None:
        # The `status` arg is unreliable in PySide6 (reports CrashExit for a
        # clean SIGTERM), so it is intentionally unused here; the state
        # property decides error vs stopped from _user_stopped + exit code.
        self._kill_timer.stop()
        self.output.emit(f"[hub] process exited (code={code})\n")
        if self._user_stopped:
            self.state_changed.emit("stopped")
        elif code in (0, None):
            self.state_changed.emit("stopped")
        else:
            self.state_changed.emit("error")
        if self._pending_restart:
            self._pending_restart = False
            self.start()
