"""Behavioural tests for the Windows process-stop path.

QProcess::terminate() on Windows posts WM_CLOSE. A console application -- which
is exactly what `python server.py` is -- has no window and never receives it,
so terminate() is a no-op and the process keeps holding its port. The Windows
path therefore escalates to `taskkill /T /F`, which takes the whole tree.

Earlier versions of this file asserted that the source text contained
"taskkill", "/T" and "/F". That proves nothing about the target PID, argument
separation, failure handling, or whether the command is ever reached. These
tests exercise the code instead, with controlled doubles for the Windows-only
subprocess call, plus one real tree-kill integration test where taskkill
exists. The only static assertion left is the grace-period ordering, which
cannot be verified behaviourally without waiting out the production timeout.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QCoreApplication, QEventLoop, QProcess, QTimer  # noqa: E402

from helpers import SkipTest, reserve_port  # noqa: E402
from hub import process_manager as pm  # noqa: E402
from hub import store as sm  # noqa: E402
from hub import urldetect  # noqa: E402


def _spin(ms: int = 100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_until(pred, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        _spin(50)
    return pred()


def _rec(**kw) -> dict:
    base = {
        "name": "P",
        "command": f'{sys.executable} -c "pass"',
        "working_dir": "",
    }
    base.update(kw)
    return sm.validate(base)


class _FakeProc:
    """The QProcess surface the escalation code uses; no real signal is sent."""

    def __init__(self, pid: int = 4242, running: bool = True):
        self.pid = pid
        self._state = QProcess.Running if running else QProcess.NotRunning
        self.terminated = 0
        self.killed = 0

    def state(self):
        return self._state

    def processId(self):
        return self.pid

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1
        self._state = QProcess.NotRunning

    def readAllStandardOutput(self):
        return b""


def test_windows_grace_is_shorter_than_the_posix_grace() -> None:
    """Static by necessity: proving this behaviourally means a 20s wait.

    The invariant matters: waiting out the POSIX grace on Windows would stall
    every stop, because terminate() cannot end a console child there.
    """
    assert pm.WINDOWS_TERM_GRACE_MS < pm.TERM_GRACE_MS, (
        f"Windows grace ({pm.WINDOWS_TERM_GRACE_MS}ms) must be shorter than the "
        f"POSIX grace ({pm.TERM_GRACE_MS}ms)"
    )


def test_taskkill_argv_targets_the_pid_and_the_tree() -> None:
    assert pm._taskkill_argv(4321) == ["taskkill", "/PID", "4321", "/T", "/F"]
    # /PID takes the numeric target as its own argument, not a joined string.
    assert pm._taskkill_argv("4321")[1:3] == ["/PID", "4321"]


def test_kill_process_tree_runs_the_expected_command() -> None:
    calls = []
    real_run = pm.subprocess.run

    class _Result:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Result()

    pm.subprocess.run = fake_run
    try:
        pm._kill_process_tree(4321)
    finally:
        pm.subprocess.run = real_run

    assert len(calls) == 1, calls
    argv, kwargs = calls[0]
    assert argv == ["taskkill", "/PID", "4321", "/T", "/F"], argv
    assert kwargs.get("capture_output") is True, kwargs
    assert kwargs.get("timeout") == 10, kwargs
    assert kwargs.get("check") is False, kwargs


def test_kill_process_tree_survives_taskkill_failures() -> None:
    real_run = pm.subprocess.run

    def missing(*a, **k):
        raise OSError("taskkill not found")

    def timed_out(*a, **k):
        raise subprocess.TimeoutExpired(cmd="taskkill", timeout=10)

    try:
        pm.subprocess.run = missing
        pm._kill_process_tree(4321)  # must not raise
        pm.subprocess.run = timed_out
        pm._kill_process_tree(4321)  # must not raise
    finally:
        pm.subprocess.run = real_run


def test_force_kill_targets_the_process_it_was_given() -> None:
    proc = _FakeProc(pid=4242)
    trees = []
    real_tree = pm._kill_process_tree
    real_windows = pm.IS_WINDOWS
    pm._kill_process_tree = trees.append
    pm.IS_WINDOWS = True
    try:
        pm.ProjectProcess(_rec(), term_grace_ms=50)._force_kill(proc)
    finally:
        pm._kill_process_tree = real_tree
        pm.IS_WINDOWS = real_windows

    assert trees == [4242], f"taskkill was not given the target PID: {trees}"
    assert proc.killed == 1, "kill() was not called after taskkill"


def test_force_kill_without_a_pid_skips_taskkill_but_still_kills() -> None:
    proc = _FakeProc(pid=0)
    trees = []
    real_tree = pm._kill_process_tree
    real_windows = pm.IS_WINDOWS
    pm._kill_process_tree = trees.append
    pm.IS_WINDOWS = True
    try:
        pm.ProjectProcess(_rec(), term_grace_ms=50)._force_kill(proc)
    finally:
        pm._kill_process_tree = real_tree
        pm.IS_WINDOWS = real_windows

    assert trees == [], f"taskkill was called without a PID: {trees}"
    assert proc.killed == 1


def test_force_kill_ignores_an_already_exited_process() -> None:
    proc = _FakeProc(pid=4242, running=False)
    trees = []
    real_tree = pm._kill_process_tree
    pm._kill_process_tree = trees.append
    try:
        pm.ProjectProcess(_rec(), term_grace_ms=50)._force_kill(proc)
    finally:
        pm._kill_process_tree = real_tree

    assert trees == [] and proc.killed == 0


def test_stop_escalates_after_the_short_grace() -> None:
    """stop() must terminate, then force-kill when the child does not exit."""
    proc = pm.ProjectProcess(_rec(), term_grace_ms=60)
    fake = _FakeProc(pid=4242)
    proc.proc = fake
    proc._generation = 1

    trees = []
    real_tree = pm._kill_process_tree
    real_windows = pm.IS_WINDOWS
    pm._kill_process_tree = trees.append
    pm.IS_WINDOWS = True
    try:
        proc.stop()
        assert fake.terminated == 1, "the child was never asked to terminate"
        assert _wait_until(lambda: fake.killed == 1, timeout_s=2), (
            "the escalation timer never force-killed the child"
        )
    finally:
        pm._kill_process_tree = real_tree
        pm.IS_WINDOWS = real_windows

    assert trees == [4242], trees


def test_restart_waits_for_the_port_to_free_before_starting() -> None:
    port = reserve_port()
    proc = pm.ProjectProcess(
        _rec(url=f"http://127.0.0.1:{port}/"), term_grace_ms=50
    )
    probes = []
    started = []

    def busy_twice_then_free(p, host=None):
        probes.append(p)
        return len(probes) <= 2

    real_probe = pm.urldetect.port_in_use
    real_start = proc.start
    pm.urldetect.port_in_use = busy_twice_then_free
    proc.start = lambda: started.append(True)
    try:
        proc._restart_after_port_free(attempts=5, generation=proc._generation)
        assert _wait_until(lambda: bool(started), timeout_s=5), (
            f"the replacement never started; probes={probes}"
        )
    finally:
        pm.urldetect.port_in_use = real_probe
        proc.start = real_start

    assert len(probes) >= 3, f"the port was not re-probed: {probes}"
    assert all(p == port for p in probes), probes


def test_restart_gives_up_when_the_port_never_frees() -> None:
    port = reserve_port()
    proc = pm.ProjectProcess(
        _rec(url=f"http://127.0.0.1:{port}/"), term_grace_ms=50
    )
    states = []
    started = []
    proc.state_changed.connect(states.append)
    real_probe = pm.urldetect.port_in_use
    real_start = proc.start
    pm.urldetect.port_in_use = lambda p, host=None: True  # never free
    proc.start = lambda: started.append(True)
    try:
        proc._restart_after_port_free(attempts=0, generation=proc._generation)
    finally:
        pm.urldetect.port_in_use = real_probe
        proc.start = real_start

    assert not started, "a restart ran while the port was still held"
    assert "error" in states, states


_CHILD_TREE_SRC = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(child.pid, flush=True)
time.sleep(120)
"""


def test_taskkill_ends_a_real_child_tree() -> None:
    """Integration: taskkill /T really ends the child and its descendant.

    Runs only where taskkill exists (Windows). The tree is one this test
    started, so nothing unrelated is signalled.
    """
    if not pm.IS_WINDOWS:
        raise SkipTest("not Windows")
    parent = subprocess.Popen(
        [sys.executable, "-u", "-c", _CHILD_TREE_SRC],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        line = parent.stdout.readline().strip()
        assert line.isdigit(), f"child pid was not reported: {line!r}"
        child_pid = int(line)
        assert urldetect._windows_process_alive(parent.pid) is True
        assert urldetect._windows_process_alive(child_pid) is True

        pm._kill_process_tree(parent.pid)

        assert _wait_until(
            lambda: not urldetect._windows_process_alive(parent.pid), timeout_s=10
        ), "the parent survived taskkill"
        assert _wait_until(
            lambda: not urldetect._windows_process_alive(child_pid), timeout_s=10
        ), "the child survived taskkill /T"
    finally:
        if parent.poll() is None:
            parent.kill()
        try:
            parent.wait(timeout=10)
        except subprocess.SubprocessError:
            pass
        if parent.stdout is not None:
            parent.stdout.close()


if __name__ == "__main__":
    QCoreApplication.instance() or QCoreApplication([])
    fails = 0
    skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except SkipTest as e:
                skipped += 1
                print(f"SKIP {name}: {e}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else (
        "all passed" + (f" ({skipped} skipped)" if skipped else "")
    ))
    sys.exit(1 if fails else 0)
