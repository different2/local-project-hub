"""End-to-end check of process_manager + readiness WITHOUT a GUI.

Spawns a real stdlib HTTP server via QProcess, exactly like a registered
project would, and asserts:
  * state goes starting -> running
  * captured stdout appears in the log history
  * stop() terminates it and the port frees up

Run:  QT_QPA_PLATFORM=offscreen python3 tests/test_process_e2e.py
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEventLoop, QProcess, QTimer  # noqa: E402

from helpers import SkipTest, reserve_port, stop_and_release, temp_project_dir  # noqa: E402
from hub import store as sm  # noqa: E402
from hub import urldetect  # noqa: E402
from hub.process_manager import ProjectProcess  # noqa: E402
from hub.readiness import ReadinessWaiter, tcp_open  # noqa: E402

# No hardcoded port: each test reserves an ephemeral one from the OS via
# helpers.reserve_port(). The fixed 8799 this used to carry collided whenever
# two suites ran at once, or when a previous run's child still held it, which
# produced failures reading as logic bugs ("readiness never fired") rather than
# as the port contention they were.
SERVER_SRC = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"HUB-TEST-OK")
    def log_message(self, *a):
        sys.stdout.write("serving\\n"); sys.stdout.flush()

# The port always comes from argv; there is no default to fall back to, so a
# missing argument fails loudly instead of silently binding somewhere else.
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def _spin(ms=200) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_for(pred, timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        _spin(50)
    return pred()


def test_process_lifecycle(tmp: Path) -> None:
    port = reserve_port()
    server_py = tmp / "fake_project_server.py"
    server_py.write_text(SERVER_SRC)

    rec = sm.validate(
        {
            "name": "Fake",
            "command": f"{sys.executable} {server_py} {port}",
            "url": f"http://127.0.0.1:{port}/",
            "working_dir": str(tmp),
            "env": {},
        }
    )
    proc = ProjectProcess(rec)
    states = []
    logs = []
    proc.state_changed.connect(states.append)
    proc.output.connect(lambda t: logs.append(t))

    proc.start()
    _spin(300)
    assert "starting" in states, states

    # wait for running
    for _ in range(50):
        if proc.state == "running":
            break
        _spin(100)
    assert proc.state == "running", f"state stuck at {proc.state}"

    # readiness waiter should fire
    got = {"ready": False}
    waiter = ReadinessWaiter(rec["url"], timeout_ms=4000)
    waiter.ready.connect(lambda: got.update(ready=True))
    waiter.start()
    for _ in range(40):
        if got["ready"]:
            break
        _spin(100)
    assert got["ready"], "readiness never fired"    # TCP check
    assert tcp_open("127.0.0.1", port)

    # log capture
    assert any("serving" in t for t in logs), logs

    proc.stop()
    for _ in range(50):
        if proc.state == "stopped":
            break
        _spin(100)
    assert proc.state == "stopped", proc.state

    # port freed
    for _ in range(30):
        if not tcp_open("127.0.0.1", port):
            break
        _spin(100)
    assert not tcp_open("127.0.0.1", port), "port still open after stop"


def test_restart(tmp: Path) -> None:
    server_py = tmp / "restart_server.py"
    port = reserve_port()
    server_py.write_text(SERVER_SRC)
    rec = sm.validate(
        {
            "name": "Restartable",
            "command": f"{sys.executable} {server_py} {port}",
            "url": f"http://127.0.0.1:{port}/",
            "working_dir": str(tmp),
        }
    )
    proc = ProjectProcess(rec)
    starts = []
    proc.state_changed.connect(lambda s: starts.append(s))
    proc.start()
    for _ in range(50):
        if proc.state == "running":
            break
        QTimer_single = 50
        _spin(100)
    assert proc.state == "running"

    proc.restart()  # stop then start again
    for _ in range(80):
        if starts.count("starting") >= 2 and proc.state == "running":
            break
        _spin(100)
    assert starts.count("starting") >= 2, starts
    assert proc.state == "running", proc.state
    proc.stop()
    for _ in range(50):
        if proc.state == "stopped":
            break
        _spin(100)


def test_bad_command_reports_error(tmp: Path) -> None:
    rec = sm.validate(
        {
            "name": "Broken",
            "command": f"{sys.executable} /no/such/file.py",
            "working_dir": str(tmp),
        }
    )
    proc = ProjectProcess(rec)
    out = []
    proc.output.connect(out.append)
    proc.start()
    # Wait for the STATE, not merely for the error text: the child prints
    # "No such file" while QProcess still reports Running, so breaking on the
    # text made this assert a state the process had not reached yet.
    for _ in range(50):
        if proc.state == "error":
            break
        _spin(100)
    assert proc.state == "error", proc.state
    assert any("No such file" in t for t in out), out


# ---------- BUG-004: stale restart escalation ----------

class _FakeProc:
    """The slice of QProcess that the escalation logic touches.

    Deterministic and safe: no real process is signalled. `kill()` is recorded
    so a stale timer that fires at the WRONG process is visible as a count.
    """

    def __init__(self, pid: int, running: bool = True, exit_code: int = 0):
        self.pid = pid
        self._state = QProcess.Running if running else QProcess.NotRunning
        self._exit_code = exit_code
        self.terminated = 0
        self.killed = 0

    def state(self):
        return self._state

    def exitCode(self):
        return self._exit_code

    def processId(self):
        return self.pid

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1
        self._state = QProcess.NotRunning

    def readAllStandardOutput(self):
        return b""


def _restartable(grace_ms: int = 120) -> ProjectProcess:
    rec = sm.validate(
        {
            "name": "Restartable",
            "command": f'{sys.executable} -c "pass"',
            "working_dir": "",
        }
    )
    # term_grace_ms is a TEST-ONLY override; the shipped grace period is
    # unchanged (asserted below).
    return ProjectProcess(rec, term_grace_ms=grace_ms)


def _fake_tree_kill(monkey_target):
    """Replace the Windows tree kill with a recorder (never taskkill a fake PID)."""
    from hub import process_manager as pm

    calls: list[int] = []
    original = pm._kill_process_tree
    pm._kill_process_tree = lambda pid: calls.append(pid)
    return pm, original, calls


def test_restart_exit_is_expected_while_waiting_for_the_port(tmp: Path) -> None:
    """Exit intent survives consuming the restart request, until a new run."""
    from unittest.mock import patch
    from hub import process_manager as pm

    p = _restartable()
    old = _FakeProc(1001, exit_code=15)
    p.proc = old
    p._generation = 1
    p.rec["url"] = f"http://127.0.0.1:{reserve_port()}/"
    states = []
    conflicts = []
    p.state_changed.connect(states.append)
    p.port_conflict_from_output.connect(conflicts.append)
    # Old output must not manufacture a bind-conflict offer during a deliberate
    # shutdown, even if the history contains a previous startup traceback.
    p.history.append("OSError: [Errno 48] Address already in use\n")
    with patch.object(pm.os, "kill"), patch.object(pm.os, "killpg", create=True), \
            patch.object(pm.urldetect, "port_in_use", return_value=True):
        try:
            p.restart()
            old._state = QProcess.NotRunning
            before_finished = p.state
            p._on_finished(15, QProcess.CrashExit, old)
            assert p._pending_restart is False, "finish never consumed the restart"
            assert p._restart_waiting == p._generation, "replacement did not wait for its port"
            assert (before_finished, p.state, states, conflicts) == (
                "stopped", "stopped", ["stopped"], []
            ), (before_finished, p.state, states, conflicts)
        finally:
            p.stop()  # cancel the owned timer/retry chain before mocks leave


def test_explicit_stop_still_classifies_requested_nonzero_exit_as_stopped(tmp: Path) -> None:
    from unittest.mock import patch
    from hub import process_manager as pm

    p = _restartable()
    old = _FakeProc(1001, exit_code=15)
    p.proc = old
    states = []
    p.state_changed.connect(states.append)
    with patch.object(pm.os, "kill"), patch.object(pm.os, "killpg", create=True):
        p.stop()
        old._state = QProcess.NotRunning
        p._on_finished(15, QProcess.CrashExit, old)
        assert p.state == "stopped" and states == ["stopped"], (p.state, states)
        assert not p._pending_restart
        assert p._restart_waiting is None


def test_unexpected_nonzero_exits_remain_errors_regardless_of_qt_status(tmp: Path) -> None:
    """Neither exit code 15 nor CrashExit is a substitute for exit intent."""
    for code in (1, 15, 23):
        for status in (QProcess.NormalExit, QProcess.CrashExit):
            p = _restartable()
            child = _FakeProc(1001, running=False, exit_code=code)
            p.proc = child
            states = []
            p.state_changed.connect(states.append)
            p._on_finished(code, status, child)
            assert p.state == "error" and states == ["error"], (code, status, p.state, states)


def test_late_finished_cannot_consume_replacement_restart_intent(tmp: Path) -> None:
    """A superseded child's finish cannot act on the current run's intent."""
    from unittest.mock import patch
    from hub import process_manager as pm

    p = _restartable()
    old = _FakeProc(1001, running=False, exit_code=15)
    new = _FakeProc(2002, exit_code=23)
    p.proc = new
    p._generation = 2
    states = []
    p.state_changed.connect(states.append)
    waits = []
    p._restart_after_port_free = lambda **kwargs: waits.append(kwargs)
    with patch.object(pm.os, "kill") as kill, patch.object(pm.os, "killpg", create=True) as killpg:
        try:
            p.restart()
            target = p._kill_target
            p._on_finished(15, QProcess.CrashExit, old)
            assert states == [] and waits == [], (states, waits)
            assert p.proc is new and p._generation == 2
            assert p._pending_restart, "old finish consumed the replacement's pending restart"
            assert p._kill_target is target, "old finish canceled the replacement's escalation"
            # It must remain the CURRENT child's intentional exit, not the late
            # old one, that causes the next replacement to be scheduled.
            new._state = QProcess.NotRunning
            p._on_finished(23, QProcess.CrashExit, new)
            assert states == ["stopped"] and waits == [{"generation": 2}], (states, waits)
            kill.assert_not_called()
            killpg.assert_not_called()
        finally:
            p._stop_kill_timer()


def test_default_grace_period_is_the_production_value(tmp: Path) -> None:
    """The test seam must not have moved the shipped timeout."""
    from hub import process_manager as pm

    p = ProjectProcess(
        sm.validate({"name": "G", "command": f'{sys.executable} -c "pass"',
                     "working_dir": ""})
    )
    expected = pm.WINDOWS_TERM_GRACE_MS if pm.IS_WINDOWS else pm.TERM_GRACE_MS
    assert p._grace_ms() == expected, p._grace_ms()
    assert pm._taskkill_argv(4242) == ["taskkill", "/PID", "4242", "/T", "/F"]


def test_restart_replacement_survives_the_old_escalation_deadline(tmp: Path) -> None:
    """A normal restart must not let the old grace timer kill the new child."""
    p = _restartable(grace_ms=120)
    old = _FakeProc(1001)
    p.proc = old
    p._generation = 1
    states: list[str] = []
    p.state_changed.connect(states.append)
    new = _FakeProc(2002)

    def fake_start():
        p._generation += 1
        p.proc = new
        p.state_changed.emit("starting")
        p.state_changed.emit("running")

    p.start = fake_start
    pm, original, trees = _fake_tree_kill(None)
    try:
        p.restart()
        assert old.terminated == 1, "the old process was not asked to stop"
        # The old child exits politely: _on_finished starts its replacement.
        old._state = QProcess.NotRunning
        p._on_finished(0, None, old)
        assert p.proc is new, "the replacement did not become current"
        assert "stopped" in states, states
        # Wait past the whole (shortened) grace period.
        _spin(400)
        assert new.killed == 0, "an obsolete escalation killed the replacement"
        # Other ProjectProcess instances from earlier tests may still have a
        # timer of their own; assert about THIS run's target, not the recorder
        # globally.
        assert old.pid not in trees, f"an obsolete escalation ran taskkill: {trees}"
        assert p.proc is new and p.state == "running", (p.proc is new, p.state)
    finally:
        pm._kill_process_tree = original


def test_two_rapid_restarts_do_not_kill_the_replacement(tmp: Path) -> None:
    p = _restartable(grace_ms=120)
    old = _FakeProc(1001)
    p.proc = old
    p._generation = 1
    new = _FakeProc(2002)

    def fake_start():
        p._generation += 1
        p.proc = new

    p.start = fake_start
    pm, original, trees = _fake_tree_kill(None)
    try:
        p.restart()
        p.restart()  # a second restart supersedes the first's timer
        old._state = QProcess.NotRunning
        p._on_finished(0, None, old)
        _spin(400)
        assert p.proc is new
        assert new.killed == 0, "a superseded timer killed the replacement"
        assert old.pid not in trees, trees
    finally:
        pm._kill_process_tree = original


def _waiting_project() -> tuple[ProjectProcess, dict[str, bool]]:
    from hub import process_manager as pm

    p = _restartable(grace_ms=120)
    p.rec["url"] = "http://127.0.0.1:12345/"
    p.proc = _FakeProc(1001, running=False)
    p._generation = 1
    busy = {"value": True}
    pm.urldetect.port_in_use = lambda port, host=None: busy["value"]
    return p, busy


def test_restart_during_port_wait_coalesces_and_starts_once(tmp: Path) -> None:
    from hub import process_manager as pm

    real_probe = pm.urldetect.port_in_use
    p, busy = _waiting_project()
    starts: list[int] = []
    p.start = lambda: starts.append(p._generation)
    try:
        p._restart_after_port_free(attempts=3, generation=1)
        assert p._restart_waiting == 1
        p.restart()  # must coalesce, not bypass the wait
        assert starts == [], "restart bypassed the active port-free wait"
        assert p._restart_waiting == 1
        busy["value"] = False
        _spin(400)
        assert starts == [1], f"replacement did not start exactly once: {starts}"
        assert p._restart_waiting is None
    finally:
        pm.urldetect.port_in_use = real_probe


def test_stop_cancels_an_active_port_wait(tmp: Path) -> None:
    from hub import process_manager as pm

    real_probe = pm.urldetect.port_in_use
    p, busy = _waiting_project()
    starts: list[int] = []
    p.start = lambda: starts.append(p._generation)
    try:
        p._restart_after_port_free(attempts=3, generation=1)
        p.stop()
        busy["value"] = False
        _spin(400)
        assert starts == [], "a stale wait restarted a stopped project"
        assert p._restart_waiting is None
    finally:
        pm.urldetect.port_in_use = real_probe


def test_port_wait_gives_up_without_starting(tmp: Path) -> None:
    from hub import process_manager as pm

    real_probe = pm.urldetect.port_in_use
    p, busy = _waiting_project()
    starts: list[int] = []
    states: list[str] = []
    p.start = lambda: starts.append(p._generation)
    p.state_changed.connect(states.append)
    try:
        p._restart_after_port_free(attempts=1, generation=1)
        _spin(500)  # first attempt schedules; second has no attempts left
        assert starts == [], "started while the port was still held"
        assert "error" in states, states
        assert p._restart_waiting is None
    finally:
        pm.urldetect.port_in_use = real_probe


def test_repeated_stop_forces_a_remaining_owned_tree(tmp: Path) -> None:
    """A second Stop must not cancel the pending descendant cleanup."""
    from hub import process_manager as pm

    p = _restartable(grace_ms=100)
    fake = _FakeProc(1001, running=False)
    p.proc = fake
    p._generation = 1
    tree = {1001: "id-A", 2002: "id-B"}
    p._tree_target = (1, fake, 1001, tree)
    signals: list[tuple[int, int]] = []
    p._tree_has_live_members = lambda members: True
    p._signal_owned_tree = lambda members, root, sig: signals.append((root, sig))
    real_windows = pm.IS_WINDOWS
    pm.IS_WINDOWS = False
    try:
        p.stop()
    finally:
        pm.IS_WINDOWS = real_windows

    assert signals == [(1001, pm._SIGKILL)], signals
    assert p._tree_target is None, "the remaining tree target was not cleared"


def test_stale_port_wait_cannot_start_a_new_generation(tmp: Path) -> None:
    from hub import process_manager as pm

    real_probe = pm.urldetect.port_in_use
    p, busy = _waiting_project()
    starts: list[int] = []
    p.start = lambda: starts.append(p._generation)
    try:
        p._restart_after_port_free(attempts=3, generation=1)
        p._generation = 2  # a newer start/stop superseded the wait
        busy["value"] = False
        _spin(400)
        assert starts == [], "a stale wait started a superseded generation"
        assert p._restart_waiting is None
    finally:
        pm.urldetect.port_in_use = real_probe


def test_old_process_exiting_before_its_deadline_is_not_force_killed(tmp: Path) -> None:
    p = _restartable(grace_ms=120)
    old = _FakeProc(1001)
    p.proc = old
    p._generation = 1
    new = _FakeProc(2002)
    p.start = lambda: (setattr(p, "_generation", p._generation + 1),
                       setattr(p, "proc", new))
    pm, original, trees = _fake_tree_kill(None)
    try:
        p.restart()
        old._state = QProcess.NotRunning
        p._on_finished(0, None, old)
        _spin(400)
        assert old.killed == 0, "the old process was killed after it had exited"
        assert old.pid not in trees, trees
        assert p.proc is new
    finally:
        pm._kill_process_tree = original


def test_genuinely_unresponsive_process_is_still_force_killed(tmp: Path) -> None:
    """The fix must not disable escalation for a child that ignores terminate."""
    p = _restartable(grace_ms=120)
    old = _FakeProc(1001)  # stays Running after terminate()
    p.proc = old
    p._generation = 1
    pm, original, trees = _fake_tree_kill(None)
    try:
        p.restart()
        _spin(350)
        assert old.killed >= 1, "an unresponsive process was never killed"
        if pm.IS_WINDOWS:
            # Only Windows needs the tree kill; POSIX terminate/kill is enough.
            assert trees == [1001], f"the tree kill did not target the old PID: {trees}"
    finally:
        pm._kill_process_tree = original


def test_retired_pid_ownership_uses_identity_and_expiry(tmp: Path) -> None:
    """Ownership needs matching identity, not just a remembered PID.

    A reused PID whose current creation/start identity differs must not be
    treated as ours. A missing identity is not evidence either; it is claimed
    only when the PID is provably unused. The TTL remains a fallback bound.
    """
    from hub import process_manager as pm

    p = ProjectProcess(
        sm.validate({"name": "R", "command": f'{sys.executable} -c "pass"',
                     "working_dir": ""})
    )
    real_tree = pm.urldetect.process_tree_pids
    real_identity = pm.urldetect.process_identity
    real_alive = pm.urldetect.process_alive
    pm.urldetect.process_tree_pids = lambda roots: set(roots)
    try:
        # An active owned child.
        p._live_pids = {111}
        p._live_identity = {111: "id-A"}
        pm.urldetect.process_identity = lambda pid: "id-A"
        assert 111 in p._own_pids()

        # A retired child whose identity still matches.
        p._live_pids = set()
        p._live_identity = {}
        p._retired_pids = {4242: (time.time(), "id-A")}
        pm.urldetect.process_identity = lambda pid: "id-A"
        assert 4242 in p._own_pids()

        # The PID was reused by a different process.
        pm.urldetect.process_identity = lambda pid: "id-B"
        assert 4242 not in p._own_pids()

        # Identity unreadable while the PID is alive: no evidence, no claim.
        pm.urldetect.process_identity = lambda pid: None
        pm.urldetect.process_alive = lambda pid: True
        assert 4242 not in p._own_pids()

        # Identity unreadable but the PID is provably unused: harmless root.
        pm.urldetect.process_alive = lambda pid: False
        assert 4242 in p._own_pids()

        # Expired ownership is pruned even if an identity would match.
        p._retired_pids = {
            4242: (time.time() - pm.RETIRED_PID_TTL_S - 1, "id-A")
        }
        pm.urldetect.process_identity = lambda pid: "id-A"
        pm.urldetect.process_alive = lambda pid: True
        assert 4242 not in p._own_pids()
        assert 4242 not in p._retired_pids

        # Failure to inspect the process table is conservative: roots only,
        # and an unreadable live identity is not claimed.
        p._retired_pids = {4242: (time.time(), "id-A")}
        pm.urldetect.process_identity = lambda pid: None
        pm.urldetect.process_alive = lambda pid: True
        assert 4242 not in p._own_pids()
    finally:
        pm.urldetect.process_tree_pids = real_tree
        pm.urldetect.process_identity = real_identity
        pm.urldetect.process_alive = real_alive


def test_process_identity_is_stable_and_clears(tmp: Path) -> None:
    """The identity really distinguishes a live process from a reused PID."""
    import subprocess

    from hub import process_manager as pm

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    try:
        first = pm.urldetect.process_identity(child.pid)
        assert first, "no identity for a live child"
        assert pm.urldetect.process_identity(child.pid) == first
        child.terminate()
        child.wait(timeout=10)
        after = pm.urldetect.process_identity(child.pid)
        if pm.IS_WINDOWS:
            # Popen still holds a process handle, so Windows can keep the
            # process object (and its creation token) alive after exit. The
            # token must never silently become a DIFFERENT process; the
            # identity-mismatch ownership test covers reuse directly.
            assert after is None or after == first, (first, after)
        else:
            # /proc and ps stop reporting an exited process.
            assert after is None, after
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_posix_stop_kills_parent_and_child(tmp: Path) -> None:
    """Integration: stopping a project kills its whole POSIX tree.

    The parent and child both ignore SIGTERM, so this exercises escalation as
    well as descendant killing. On Linux the child is in a setsid group; on
    macOS (no setsid command) the captured-tree fallback is used.
    """
    from hub import process_manager as pm

    if pm.IS_WINDOWS:
        raise SkipTest("POSIX-only process-tree integration")

    parent = tmp / "tree_parent.py"
    parent.write_text(
        "import signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = subprocess.Popen([\n"
        "    sys.executable, '-c',\n"
        "    'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(120)',\n"
        "])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    rec = sm.validate(
        {
            "name": "Tree",
            "command": f"{sys.executable} {parent}",
            "working_dir": str(tmp),
        }
    )
    p = ProjectProcess(rec, term_grace_ms=800)
    child_pid: int | None = None

    def _child_seen() -> bool:
        nonlocal child_pid
        for line in "".join(p.history).splitlines():
            value = line.strip()
            if value.isdigit():
                child_pid = int(value)
                return True
        return False

    p.start()
    try:
        assert _wait_for(lambda: p.state == "running", timeout_s=20)
        assert _wait_for(_child_seen, timeout_s=20), p.history
        assert child_pid and urldetect.process_alive(child_pid)
        p.stop()
        assert _wait_for(lambda: p.state == "stopped", timeout_s=20)
        assert _wait_for(
            lambda: not urldetect.process_alive(child_pid), timeout_s=10
        ), "the child outlived the project stop"
    finally:
        if p.proc is not None and p.proc.state() != QProcess.NotRunning:
            p.stop()
        if child_pid and urldetect.process_alive(child_pid):
            urldetect.kill_process(child_pid, timeout_s=2)


def test_delayed_callback_from_an_older_generation_is_ignored(tmp: Path) -> None:
    p = _restartable(grace_ms=120)
    old = _FakeProc(1001)
    p.proc = old
    p._generation = 5
    p._arm_escalation(120)
    token = p._kill_target
    assert token is not None

    newer = _FakeProc(2002)
    p.proc = newer
    p._generation = 6  # a newer run has started
    pm, original, trees = _fake_tree_kill(None)
    try:
        p._force_kill_if_current(*token)
        assert old.killed == 0 and newer.killed == 0, "a stale token killed a process"
        assert old.pid not in trees, trees
        # Same generation but a different process is equally stale.
        p._force_kill_if_current(6, old, 1001)
        assert old.killed == 0
    finally:
        pm._kill_process_tree = original


def test_restart_replacement_survives_the_deadline_for_real(tmp: Path) -> None:
    """The same property against a real child process and socket.

    Uses a test-only short grace on a real ProjectProcess. On Windows this
    exercises terminate() -> taskkill tree kill -> replacement; on POSIX it
    exercises terminate() -> replacement. The production timeout is untouched.
    """
    port = reserve_port()
    server_py = tmp / "restart_survivor.py"
    server_py.write_text(SERVER_SRC)
    rec = sm.validate(
        {
            "name": "Survivor",
            "command": f"{sys.executable} {server_py} {port}",
            "url": f"http://127.0.0.1:{port}/",
            "working_dir": str(tmp),
        }
    )
    proc = ProjectProcess(rec, term_grace_ms=600)
    starts: list[str] = []
    proc.state_changed.connect(starts.append)
    proc.start()
    try:
        assert _wait_for_state(proc, "running", timeout_s=25), proc.state
        proc.restart()
        deadline = time.time() + 25
        while time.time() < deadline:
            if starts.count("starting") >= 2 and proc.state == "running":
                break
            _spin(100)
        assert starts.count("starting") >= 2, starts
        assert proc.state == "running", proc.state
        # Past the whole shortened grace period: the replacement must still be
        # alive and answering, not killed by the old run's timer.
        _spin(1500)
        assert proc.state == "running", f"replacement died: {proc.state} {starts}"
        assert tcp_open("127.0.0.1", port), "replacement is not serving"
    finally:
        stop_and_release(proc, server_py)


def _wait_for_state(proc, state: str, timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.state == state:
            return True
        _spin(100)
    return proc.state == state


def _wait_until(pred, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        _spin(100)
    return pred()


# ---------- BUG-005: readiness retries a transient transport error ----------

class _ResetServer:
    """A raw TCP server that resets the first N HTTP requests, then answers.

    A reset is a genuine transport error (not an HTTP status), which is the
    exact case the old readiness code stopped retrying on. Built on sockets so
    no extra dependency or test server framework is needed.
    """

    def __init__(self, reset_requests: int = 1, ignore_first_seconds: float = 0.0):
        import threading

        self._reset_until = reset_requests
        self._ignore_first_seconds = ignore_first_seconds
        self.requests = 0
        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        import struct

        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.requests += 1
            try:
                conn.settimeout(1.0)
                try:
                    conn.recv(65536)
                except OSError:
                    pass
                if self.requests == 1 and self._ignore_first_seconds:
                    # Hold the first request past the client's 3s transfer
                    # timeout, then drop it. Qt retries a plain connection
                    # reset on its own, so only a timeout exercises the
                    # APPLICATION's retry.
                    time.sleep(self._ignore_first_seconds)
                elif self.requests <= self._reset_until:
                    # SO_LINGER with a zero timeout makes close() send RST.
                    try:
                        conn.setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_LINGER,
                            struct.pack("ii", 1, 0),
                        )
                    except OSError:
                        pass
                else:
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                        b"Connection: close\r\n\r\nok"
                    )
            finally:
                conn.close()

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(timeout=2)


def test_readiness_succeeds_after_the_first_request_is_dropped(tmp: Path) -> None:
    """A dropped (timed-out) first attempt must not end readiness polling.

    The old _http_done() returned on a transport error AFTER the TCP poll had
    been stopped. Nothing re-armed it, so one transient failure made the
    project permanently unready even though it answered moments later.

    A plain connection reset is a weak test: Qt's HTTP layer retries it
    internally, so the old code also became ready. Holding the first request
    past the 3s transfer timeout produces a transport error Qt does NOT retry
    by itself, which is what the application's retry has to cover. Against the
    audited revision this scenario reports a single failure at the 9s deadline
    with two connections and no successful request.
    """
    srv = _ResetServer(reset_requests=0, ignore_first_seconds=4.0)
    waiter = ReadinessWaiter(f"http://127.0.0.1:{srv.port}/", timeout_ms=9000)
    outcomes: list = []
    waiter.ready.connect(lambda: outcomes.append("ready"))
    waiter.failed.connect(lambda reason: outcomes.append(("failed", reason)))
    try:
        waiter.start()
        assert _wait_until(lambda: bool(outcomes), timeout_s=12), (
            f"readiness never settled; requests={srv.requests}"
        )
        assert outcomes == ["ready"], outcomes
        assert srv.requests >= 2, f"no retry was made (requests={srv.requests})"
    finally:
        waiter.stop()
        srv.close()


def test_readiness_survives_a_connection_reset(tmp: Path) -> None:
    """The reset variant: Qt retries once itself, and the app must still cope."""
    srv = _ResetServer(reset_requests=1)
    waiter = ReadinessWaiter(f"http://127.0.0.1:{srv.port}/", timeout_ms=8000)
    outcomes: list = []
    waiter.ready.connect(lambda: outcomes.append("ready"))
    waiter.failed.connect(lambda reason: outcomes.append(("failed", reason)))
    try:
        waiter.start()
        assert _wait_until(lambda: bool(outcomes), timeout_s=10), (
            f"readiness never settled; requests={srv.requests}"
        )
        assert outcomes == ["ready"], outcomes
        assert srv.requests >= 2, f"no retry was made (requests={srv.requests})"
    finally:
        waiter.stop()
        srv.close()


def test_readiness_reports_one_failure_after_the_deadline(tmp: Path) -> None:
    """A service that never answers produces exactly one bounded failure."""
    srv = _ResetServer(reset_requests=10**6)  # reset every request
    waiter = ReadinessWaiter(f"http://127.0.0.1:{srv.port}/", timeout_ms=1200)
    outcomes: list = []
    waiter.ready.connect(lambda: outcomes.append("ready"))
    waiter.failed.connect(lambda reason: outcomes.append(("failed", reason)))
    try:
        waiter.start()
        assert _wait_until(lambda: bool(outcomes), timeout_s=6), (
            f"no outcome within the deadline; requests={srv.requests}"
        )
        assert srv.requests >= 2, f"the retry loop did not run (requests={srv.requests})"
        # Keep the loop alive a bit longer: a duplicate failure or a late ready
        # would show up here.
        _spin(600)
        assert len(outcomes) == 1, f"duplicate outcomes: {outcomes}"
        assert isinstance(outcomes[0], tuple) and outcomes[0][0] == "failed", outcomes
    finally:
        waiter.stop()
        srv.close()


def test_readiness_with_no_listener_fails_once_at_the_deadline(tmp: Path) -> None:
    port = reserve_port()
    waiter = ReadinessWaiter(f"http://127.0.0.1:{port}/", timeout_ms=900)
    outcomes: list = []
    waiter.ready.connect(lambda: outcomes.append("ready"))
    waiter.failed.connect(lambda reason: outcomes.append(("failed", reason)))
    try:
        waiter.start()
        assert _wait_until(lambda: bool(outcomes), timeout_s=5), outcomes
        _spin(500)
        assert len(outcomes) == 1, f"duplicate outcomes: {outcomes}"
        assert outcomes[0][0] == "failed", outcomes
    finally:
        waiter.stop()


if __name__ == "__main__":
    import tempfile

    app = QCoreApplication([])
    fails = 0
    skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with temp_project_dir() as d:
                try:
                    fn(Path(d))
                    print(f"PASS {name}")
                except SkipTest as e:
                    skipped += 1
                    print(f"SKIP {name}: {e}")
                except AssertionError as e:
                    fails += 1
                    print(f"FAIL {name}: {e}")
                except Exception as e:
                    # Only AssertionError used to be caught, so any other
                    # exception killed the runner mid-suite: later tests never
                    # printed and the summary lied about the counts. An
                    # unexpected error is a failure -- report it as one.
                    fails += 1
                    print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else (
        "all passed" + (f" ({skipped} skipped)" if skipped else "")
    ))
    sys.exit(1 if fails else 0)
