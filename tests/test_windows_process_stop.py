"""Guard the Windows process-stop path, which no macOS run can exercise.

QProcess::terminate() on Windows posts WM_CLOSE. A console application -- which
is exactly what `python server.py` is -- has no window and never receives it,
so terminate() is a no-op and the process keeps holding its port. The Windows CI
job's test_process_e2e failed 1 passed / 2 failed for this reason, and the
encoding crash meant nobody could read why.

These tests pin the Windows branch by forcing IS_WINDOWS on. They do not prove
Windows behaviour (nothing here can) -- they prove the branch exists, is wired
to the right timers, and would survive a refactor that deleted it.

Rewritten 2026-10-20 (Windows audit, INFO-006): three of these tests used to
read process_manager.py as text and assert that words like "taskkill",
"WINDOWS_TERM_GRACE_MS" and "_restart_after_port_free" appeared in the right
function body. That cannot fail when the call is deleted but the word is left in
a comment, and it cannot pass after a harmless rename. They now run the code
against a fake QProcess instead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

from hub import process_manager as pm  # noqa: E402


def test_windows_escalates_before_the_full_grace_period() -> None:
    """Windows must not wait out the 20s POSIX grace to force-kill.

    Waiting would stall every stop on Windows, since terminate() cannot end a
    console child there.
    """
    # Do NOT assert the host is non-Windows: this suite has to pass on the
    # Windows runner too, and an earlier version did assert it, so the guard
    # failed exactly on the platform it exists to protect.
    assert pm.WINDOWS_TERM_GRACE_MS < pm.TERM_GRACE_MS, (
        f"Windows grace ({pm.WINDOWS_TERM_GRACE_MS}ms) must be shorter than the "
        f"POSIX grace ({pm.TERM_GRACE_MS}ms) or every Windows stop stalls"
    )


class _FakeProc:
    """The slice of QProcess these kill paths touch. No child is ever started.

    The previous version of this suite read `hub/process_manager.py` as text and
    asserted that the words "taskkill", "/T" and "_restart_after_port_free"
    appeared in the right function bodies. That proves a string was typed, not
    that anything is wired: deleting the call and leaving the word in a comment
    would have kept the suite green, and a refactor that renamed a helper broke
    it for no reason. These fakes let the code actually run.
    """

    def __init__(self, state=None, pid: int = 4321, code: int = 0):
        self._state = pm.QProcess.Running if state is None else state
        self._pid = pid
        self._code = code
        self.terminated = False
        self.killed = False

    def state(self):
        return self._state

    def exitCode(self) -> int:
        return self._code

    def processId(self) -> int:
        return self._pid

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._state = pm.QProcess.NotRunning

    def readAllStandardOutput(self) -> bytes:
        return b""

    def readAllStandardError(self) -> bytes:
        return b""


def _fake_process() -> pm.ProjectProcess:
    rec = {"name": "server", "command": "python3 server.py", "working_dir": str(PROJECT_ROOT)}
    proc = pm.ProjectProcess(rec)
    proc.proc = _FakeProc()
    return proc


def test_force_kill_uses_taskkill_on_windows() -> None:
    """The force-kill path must call taskkill /T /F, not just QProcess.kill().

    kill() alone leaves anything the process spawned holding the port, and
    terminate() never reaches a console process at all.
    """
    argv_seen: list[list[str]] = []

    class _Completed:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(argv, **kwargs):
        argv_seen.append(list(argv))
        return _Completed()

    proc = _fake_process()
    with mock.patch.object(pm.subprocess, "run", fake_run), mock.patch.object(
        pm, "IS_WINDOWS", True
    ):
        proc._force_kill()

    assert argv_seen, (
        "the Windows force-kill never ran taskkill; kill() alone leaves every "
        "child the server spawned holding its port"
    )
    argv = argv_seen[0]
    assert argv[:3] == ["taskkill", "/PID", "4321"], f"taskkill was aimed wrong: {argv}"
    assert "/T" in argv and "/F" in argv, f"taskkill must take the tree forcibly: {argv}"
    assert proc.proc.killed, "taskkill ran but QProcess.kill() was never called"


def test_stop_schedules_a_windows_escalation() -> None:
    """stop() must arm the short Windows timer so a hung child dies promptly."""
    scheduled: list[tuple[int, object]] = []

    class _TimerSpy:
        @staticmethod
        def singleShot(ms, fn):
            scheduled.append((ms, fn))

    proc = _fake_process()
    with mock.patch.object(pm, "IS_WINDOWS", True), mock.patch.object(pm, "QTimer", _TimerSpy):
        proc.stop()

    assert proc.proc.terminated, "stop() never asked the child to terminate"
    assert scheduled, (
        "stop() armed no Windows escalation: terminate() posts WM_CLOSE, which a "
        "console child never receives, so the stop would hang for the full POSIX grace"
    )
    ms, fn = scheduled[0]
    assert ms == pm.WINDOWS_TERM_GRACE_MS, (
        f"the escalation waits {ms}ms, not the short {pm.WINDOWS_TERM_GRACE_MS}ms "
        "Windows grace"
    )
    assert getattr(fn, "__name__", "") == "_force_kill", (
        "the Windows escalation is not wired to the force-kill path"
    )
    proc._kill_timer.stop()


def test_restart_waits_for_the_port_to_free() -> None:
    """A restart must not fire while the old process still holds the port.

    On Windows the terminated child keeps its listening socket briefly, so
    restarting the instant `finished` fires makes the replacement die with
    "Address already in use" and leaves the project stuck in 'starting'. That is
    exactly the failure the Windows job reported: test_restart with states
    ['starting', 'running'].
    """
    proc = _fake_process()
    proc.proc = _FakeProc(state=pm.QProcess.NotRunning)
    proc._pending_restart = True
    proc._user_stopped = True  # a user stop, so the exit is not reported as an error

    routed: list[int] = []
    started: list[bool] = []
    proc._restart_after_port_free = lambda attempts=40: routed.append(attempts)
    proc.start = lambda: started.append(True)

    proc._on_finished(0, pm.QProcess.NormalExit)

    assert routed, "_on_finished did not route the pending restart through the port check"
    assert not started, (
        "_on_finished started the replacement immediately, before the old child "
        "released its port"
    )


def test_taskkill_command_shape() -> None:
    """The taskkill argv must be well-formed if it ever runs.

    Checked by calling the real command on a PID that does not exist: taskkill
    fails cleanly, proving the arguments parse rather than erroring on syntax.
    Skipped where taskkill is absent (every non-Windows host), since only its
    shape can be verified here.
    """
    try:
        subprocess.run(["taskkill", "--help"], capture_output=True, timeout=5, check=False)
    except (FileNotFoundError, OSError):
        # taskkill is Windows-only; the argument shape is still asserted above
        # from source, which is all a macOS host can honestly do.
        return
    argv = ["taskkill", "/PID", "999999", "/T", "/F"]
    r = subprocess.run(argv, capture_output=True, timeout=10, check=False)
    # A nonexistent PID fails, but must fail as "no such process", not because
    # the command line was malformed.
    out = (r.stdout + r.stderr).decode("utf-8", "replace").lower()
    assert "invalid" not in out, f"taskkill rejected the argv shape: {out[:200]}"


def test_restart_gives_up_honestly_when_the_port_never_frees() -> None:
    """When the port stays held, the restart must report it instead of looping.

    This exercises the real probe: a socket holds the project's port, so the
    bounded retry runs out at once (attempts=0) and the project must end in
    'error' with nothing launched, rather than starting into a busy port.
    """
    import socket

    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        proc = pm.ProjectProcess(
            {
                "name": "held",
                "command": "python3 held.py",
                "working_dir": str(PROJECT_ROOT),
                "url": f"http://127.0.0.1:{port}/",
            }
        )
        states: list[str] = []
        started: list[bool] = []
        proc.state_changed.connect(states.append)
        proc.start = lambda: started.append(True)

        proc._restart_after_port_free(attempts=0)

        assert not started, "the replacement was started while the port was still held"
        assert "error" in states, f"giving up on a held port reported no error: {states}"
    finally:
        holder.close()


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "N passed, 1 failed" with no FAIL line to name
                # the 1. An unexpected error is a failure -- report it as one.
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)


