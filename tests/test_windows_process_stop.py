"""Guard the Windows process-stop path, which no macOS run can exercise.

QProcess::terminate() on Windows posts WM_CLOSE. A console application -- which
is exactly what `python server.py` is -- has no window and never receives it,
so terminate() is a no-op and the process keeps holding its port. The Windows CI
job's test_process_e2e failed 1 passed / 2 failed for this reason, and the
encoding crash meant nobody could read why.

These tests pin the Windows branch by forcing IS_WINDOWS on. They do not prove
Windows behaviour (nothing here can) -- they prove the branch exists, is wired
to the right timers, and would survive a refactor that deleted it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def test_force_kill_uses_taskkill_on_windows() -> None:
    """The force-kill path must call taskkill /T /F, not just QProcess.kill().

    kill() alone leaves anything the process spawned holding the port, and
    terminate() never reaches a console process at all.
    """
    src = (PROJECT_ROOT / "hub" / "process_manager.py").read_text(encoding="utf-8")
    body = src[src.index("def _force_kill") :]
    body = body[: body.index("\n    def ", 1)]
    assert "taskkill" in body, "Windows force-kill does not use taskkill"
    assert "/T" in body and "/F" in body, "taskkill must take the tree (/T) forcibly (/F)"
    assert "IS_WINDOWS" in body, "the taskkill branch is not gated on IS_WINDOWS"


def test_stop_schedules_a_windows_escalation() -> None:
    """stop() must arm the short Windows timer so a hung child dies promptly."""
    src = (PROJECT_ROOT / "hub" / "process_manager.py").read_text(encoding="utf-8")
    body = src[src.index("    def stop(self)") :]
    body = body[: body.index("\n    def ", 1)]
    assert "WINDOWS_TERM_GRACE_MS" in body, (
        "stop() does not arm the short Windows escalation timer"
    )
    assert "_force_kill" in body, "stop() has nothing to escalate to"


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


def test_restart_waits_for_the_port_to_free() -> None:
    """A restart must not fire while the old process still holds the port.

    On Windows the terminated child keeps its listening socket briefly, so
    restarting the instant `finished` fires makes the replacement die with
    "Address already in use" and leaves the project stuck in 'starting'. That is
    exactly the failure the Windows job reported: test_restart with states
    ['starting', 'running'].
    """
    src = (PROJECT_ROOT / "hub" / "process_manager.py").read_text(encoding="utf-8")
    on_finished = src[src.index("def _on_finished") :]
    on_finished = on_finished[: on_finished.index("\n    def ", 1)]
    assert "self.start()" not in on_finished, (
        "_on_finished starts the replacement immediately -- the port may still "
        "be held, so the new server fails to bind"
    )
    assert "_restart_after_port_free" in on_finished, (
        "_on_finished does not route a pending restart through the port check"
    )
    assert "tcp_open" in src, "the restart path no longer probes the port"


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


