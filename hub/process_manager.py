"""Process lifecycle: start, stop, restart project backends; capture their logs.

Boundary (per SPEC): the hub owns *how* processes are launched and read, never
their source. The command string is split with shlex (no shell) so
`python3 server.py 8471` works without quoting problems and without exposing a
shell injection surface from the registry file.

Stdout/stderr are merged into one ring buffer per project (newest 500 lines),
kept in memory for the log drawer. Signals are emitted on the GUI thread via
Qt.
"""

from __future__ import annotations

import shlex
import time
from collections import deque

from PySide6.QtCore import QObject, QProcess, Signal

LOG_HISTORY = 500


def _no_decoration() -> dict:
    # Keep Terminal.app windows out of it: this is a background service.
    return {}


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

    # ---------- state ----------

    @property
    def state(self) -> str:
        if self.proc is None:
            return "stopped"
        s = self.proc.state()
        if s == QProcess.NotRunning:
            return "error" if self.proc.exitCode() not in (0, None) and not self._user_stopped else "stopped"
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
        if self.proc is None:
            return
        self._user_stopped = True
        if self.proc.state() == QProcess.NotRunning:
            return
        self.output.emit("[hub] terminating...\n")
        self.proc.terminate()
        # If it ignores SIGTERM, force-kill after 3s.
        from PySide6.QtCore import QTimer

        def _kill():
            if self.proc is not None and self.proc.state() != QProcess.NotRunning:
                self.output.emit("[hub] did not exit in 3s, killing\n")
                self.proc.kill()

        QTimer.singleShot(3000, _kill)

    def restart(self) -> None:
        was_running = self.proc is not None and self.proc.state() != QProcess.NotRunning
        if was_running:
            self._user_stopped = False
            self.stop()
            # Wait for the finished signal, then start again (see _on_finished).
            self._pending_restart = True
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

    def _on_finished(self, code: int, status) -> None:
        self.output.emit(f"[hub] process exited (code={code})\n")
        self.state_changed.emit("stopped" if self._user_stopped else "error")
        if getattr(self, "_pending_restart", False):
            self._pending_restart = False
            self.start()
