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


def test_project_path_selects_its_python_and_explicit_interpreter_still_wins(tmp: Path) -> None:
    """Run real isolated environments: the child's PATH must choose its Python."""
    import os
    import shlex
    import subprocess
    from unittest.mock import patch

    environments = []
    for name, marker in (("Hub environment", "HUB_ENV"), ("Project environment", "PROJECT_ENV")):
        folder = tmp / name
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(folder)], check=True)
        binary = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        purelib = Path(subprocess.check_output(
            [str(binary), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
        ).strip())
        (purelib / "hub_compat_env_marker.py").write_text(f"VALUE = {marker!r}\n", encoding="utf-8")
        environments.append(binary)
    hub_python, project_python = environments
    inherited_path = os.environ.get("PATH", "")
    parent_path = str(hub_python.parent) + os.pathsep + inherited_path
    project_path = str(project_python.parent) + os.pathsep + inherited_path
    expression = "import hub_compat_env_marker; print(hub_compat_env_marker.VALUE)"
    import hub.process_manager as pm
    for path_key in ("PATH", "Path", "pAtH"):
        for explicit, expected, marker in (("", project_python, "PROJECT_ENV"),
                                           (str(hub_python), hub_python, "HUB_ENV")):
            rec = {"id": "path-fixture", "name": "Own environments", "working_dir": str(tmp),
                   "command": ("" if explicit else "python ") + "-c " + shlex.quote(expression),
                   "interpreter": explicit, "url": "", "env": {path_key: project_path}}
            proc = ProjectProcess(rec)
            logs = []
            proc.output.connect(logs.append)
            try:
                # Mixed-case names are Windows semantics, not a POSIX override.
                # Run the actual OS process after exercising that lookup branch;
                # native Windows CI repeats it with its real environment rules.
                with patch.dict(os.environ, {"PATH": parent_path}), \
                        patch.object(pm, "IS_WINDOWS", pm.IS_WINDOWS or path_key != "PATH"):
                    proc.start()
                    assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), logs
                handle = proc.proc
                assert handle is not None, logs
                launched = handle.program()
                if pm.POSIX_SETSID and launched == pm.POSIX_SETSID:
                    launched = handle.arguments()[0]  # actual Linux launch wrapper
                # Windows resolves PATHEXT spelling (python.EXE) without
                # changing the selected environment. Keep lexical venv paths:
                # resolving symlinks would conflate distinct POSIX environments.
                assert os.path.normcase(launched) == os.path.normcase(str(expected)), (
                    f"project {path_key} chose {project_python}, explicit={explicit!r}, "
                    f"but Hub launched {launched}; output={logs}"
                )
                assert handle.exitCode() == 0 and marker in "".join(logs), logs
            finally:
                proc.stop()
                assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_legacy_full_python_command_uses_selected_interpreter_once(tmp: Path) -> None:
    import json
    import shlex

    script = tmp / "legacy entry.py"
    body = "print('HUB_LEGACY_ENTRY_OK', flush=True)\n"
    script.write_text(body, encoding="utf-8")
    original_command = "python3 " + shlex.quote(script.name)
    registry = tmp / "legacy-registry.json"
    registry.write_text(json.dumps({"version": 1, "projects": [{
        "id": "legacy-full", "name": "Legacy full command", "command": original_command,
        "interpreter": sys.executable, "working_dir": str(tmp), "env": {}
    }]}), encoding="utf-8")
    store = sm.Store(registry)
    rec = store.get("legacy-full")
    assert rec is not None
    proc = ProjectProcess(rec)
    logs = []
    proc.output.connect(logs.append)
    try:
        proc.start()
        assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), logs
        handle = proc.proc
        assert handle is not None
        assert handle.exitCode() == 0 and "HUB_LEGACY_ENTRY_OK" in "".join(logs), (
            f"configured interpreter stacked with a full legacy command; args={handle.arguments()}; output={logs}"
        )
        restored = store.get("legacy-full")
        assert restored is not None
        assert restored["command"] == original_command
        assert restored["interpreter"] == sys.executable
        assert script.read_text(encoding="utf-8") == body
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_missing_program_reports_start_error_and_recovers(tmp: Path) -> None:
    import shlex
    from unittest.mock import patch

    missing = tmp / "missing program"
    rec = {"id": "missing-tool", "name": "Missing executable", "working_dir": str(tmp),
           "command": shlex.quote(str(missing)), "url": "", "env": {}}
    proc = ProjectProcess(rec)
    states = []
    logs = []
    proc.state_changed.connect(states.append)
    proc.output.connect(logs.append)
    try:
        # Exercise Qt's actual FailedToStart signal even on Linux, where the
        # optional setsid wrapper otherwise starts successfully then exits127.
        with patch("hub.process_manager.POSIX_SETSID", None):
            proc.start()
            assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), logs
        assert "error" in states and "could not start" in "".join(logs) and str(missing) in "".join(logs), (
            f"actual FailedToStart was not surfaced; states={states}, output={logs}"
        )
        assert proc.state == "error"
        old = proc.proc
        proc.rec = dict(rec, command=shlex.quote(sys.executable) + ' -c "print(12345)"')
        proc.start()
        # A late error from the failed handle must not poison its replacement.
        proc._on_error(QProcess.FailedToStart, old)
        assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning)
        assert proc.state == "stopped" and "12345" in "".join(logs), logs
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_relative_interpreter_is_anchored_without_escaping_its_venv(tmp: Path) -> None:
    import shlex
    import subprocess
    from unittest.mock import patch

    folder = tmp / "selected venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(folder)], check=True)
    binary = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    relative = str(binary.relative_to(tmp))
    script = tmp / "env_entry.py"
    body = "import sys; print('HUB_SELECTED_PREFIX=' + sys.prefix, flush=True)\n"
    script.write_text(body, encoding="utf-8")
    for field in ("interpreter", "command"):
        rec = {"id": "relative-env", "name": "Relative environment", "working_dir": str(tmp),
               "command": shlex.quote(script.name), "url": "", "env": {}}
        if field == "interpreter":
            rec["interpreter"] = relative
        else:
            rec["command"] = shlex.quote(relative) + " " + rec["command"]
        proc = ProjectProcess(rec)
        logs = []
        proc.output.connect(logs.append)
        try:
            with patch("hub.process_manager.POSIX_SETSID", None):
                proc.start()
                assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), logs
            handle = proc.proc
            assert handle is not None
            assert handle.program() == str(binary), (
                f"{field} was not anchored to the project; got={handle.program()!r}; expected={str(binary)!r}; output={logs}"
            )
            assert handle.exitCode() == 0 and "HUB_SELECTED_PREFIX=" + str(folder) in "".join(logs), logs
            assert script.read_text(encoding="utf-8") == body
        finally:
            proc.stop()
            assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_automatic_browser_flags_match_the_current_cli_contract(tmp: Path) -> None:
    import json
    import shlex
    import subprocess

    cases = [
        ("incidental-dependency", "ap.add_argument('--port', type=int, default=0)", "streamlit\n", False, False),
        ("value-taking-prefix", "ap.add_argument('--no-open-mode', choices=['auto','off'], default='off')", "", False, False),
        ("value-taking-exact", "ap.add_argument('--no-open', choices=['auto','off'], default='off')", "", False, False),
        ("stale-cache", "ap.add_argument('--port', type=int, default=0)", "", False, True),
        ("declared-boolean", "ap.add_argument('--no-open', action='store_true')", "", True, False),
        ("declared-group", "options = ap.add_argument_group('Browser')\noptions.add_argument('--no-open', action='store_true')", "", True, False),
        ("declared-exclusive-group", "options = ap.add_mutually_exclusive_group()\noptions.add_argument('--no-open', action='store_true')", "", True, False),
        ("main-boolean", "ap.add_argument('--no-open', action='store_true')", "", True, False),
        ("main-group", "options = ap.add_argument_group('Browser')\noptions.add_argument('--no-open', action='store_true')", "", True, False),
        ("legacy-boolean", "ap.add_argument('--no-open', action='store_true')", "", True, False),
    ]
    failures = []
    for label, declaration, dependencies, expects_flag, stale in cases:
        folder = tmp / label
        folder.mkdir()
        script = folder / "app.py"
        parser_body = ("ap = argparse.ArgumentParser()\n" + declaration + "\n"
                       "args = ap.parse_args()\nprint('HUB_CLI_CONTRACT_OK', repr(vars(args)), flush=True)\n")
        if label.startswith("main-"):
            import textwrap
            parser_body = "def main():\n" + textwrap.indent(parser_body, "    ") + "\nmain()\n"
        body = "import argparse\nfrom http.server import HTTPServer\n" + parser_body
        script.write_text(body, encoding="utf-8")
        baseline = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=15)
        assert baseline.returncode == 0 and "HUB_CLI_CONTRACT_OK" in baseline.stdout, (
            label, "fixture is not a valid standalone CLI", baseline.stdout, baseline.stderr
        )
        if dependencies:
            (folder / "requirements.txt").write_text(dependencies, encoding="utf-8")
        raw = {"id": label, "name": label, "working_dir": str(folder),
               "command": "python3 " + shlex.quote(script.name), "interpreter": sys.executable, "env": {}}
        if label == "legacy-boolean":
            registry = folder / "registry.json"
            registry.write_text(json.dumps({"version": 1, "projects": [raw]}), encoding="utf-8")
            rec = sm.Store(registry).get(label)
            assert rec is not None
        else:
            rec = sm.validate(raw)
            if stale:
                rec["detected"] = {"type": "web", "browser": "known-suppressible", "evidence": [
                    "entry script declares --no-open in its argparse"]}
        proc = ProjectProcess(rec)
        logs = []
        proc.output.connect(logs.append)
        try:
            proc.start()
            done = _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning)
            handle = proc.proc
            output = "".join(logs)
            if not done or handle is None or handle.exitCode() != 0 or "HUB_CLI_CONTRACT_OK" not in output:
                failures.append((label, "Hub-added arguments broke a valid CLI", output))
            elif expects_flag and "'no_open': True" not in output:
                failures.append((label, "declared boolean flag was lost", output))
            assert script.read_text(encoding="utf-8") == body
            assert rec["command"] == raw["command"]
        finally:
            proc.stop()
            assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)
    assert not failures, failures


def test_legacy_commands_never_get_flags_from_inactive_parsers(tmp: Path) -> None:
    import ast
    import json
    import shlex
    import subprocess

    cases = {
        "subcommand": ("ap = argparse.ArgumentParser()\n"
                       "commands = ap.add_subparsers(dest='action', required=True)\n"
                       "commands.add_parser('run')\n"
                       "export = commands.add_parser('export')\n"
                       "export.add_argument('--no-open', action='store_true')\n"),
        "other-parser": ("unused = argparse.ArgumentParser()\n"
                         "unused.add_argument('--no-open', action='store_true')\n"
                         "ap = argparse.ArgumentParser()\n"
                         "ap.add_argument('action', choices=['run'])\n"),
        "shadowed-helper": ("def configure_export(ap):\n"
                            "    ap.add_argument('--no-open', action='store_true')\n"
                            "ap = argparse.ArgumentParser()\n"
                            "ap.add_argument('action', choices=['run'])\n"),
        "other-receiver": ("class Unrelated:\n"
                           "    def add_argument(self, *args, **kwargs): pass\n"
                           "unused = Unrelated()\n"
                           "unused.add_argument('--no-open', action='store_true')\n"
                           "ap = argparse.ArgumentParser()\n"
                           "ap.add_argument('action', choices=['run'])\n"),
    }
    failures = []
    for label, declarations in cases.items():
        folder = tmp / label
        folder.mkdir()
        script = folder / "own cli.py"
        source = ("import argparse\nfrom http.server import HTTPServer\n" + declarations +
                  "args = ap.parse_args()\nprint('HUB_ACTIVE_COMMAND', args.action, flush=True)\n")
        ast.parse(source)
        script.write_text(source, encoding="utf-8")
        control = subprocess.run([sys.executable, str(script), "run"], capture_output=True, text=True, timeout=15)
        assert control.returncode == 0 and "HUB_ACTIVE_COMMAND run" in control.stdout, (
            "fixture is not a valid standalone command", label, control.stdout, control.stderr
        )
        if label == "subcommand":
            export = subprocess.run([sys.executable, str(script), "export", "--no-open"],
                                    capture_output=True, text=True, timeout=15)
            assert export.returncode == 0 and "HUB_ACTIVE_COMMAND export" in export.stdout
        raw = {"id": label, "name": label, "command": shlex.quote(script.name) + " run",
               "interpreter": sys.executable, "working_dir": str(folder), "env": {}}
        path = folder / "registry.json"
        path.write_text(json.dumps({"version": 1, "projects": [raw]}), encoding="utf-8")
        store = sm.Store(path)
        rec = store.get(label)
        assert rec is not None
        proc = ProjectProcess(rec)
        logs = []
        proc.output.connect(logs.append)
        try:
            proc.start()
            assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), logs
            child = proc.proc
            if child is None or child.exitCode() != 0 or "HUB_ACTIVE_COMMAND run" not in "".join(proc.history):
                failures.append((label, "inactive parser flag broke a standalone-valid legacy command", list(logs)))
            assert script.read_text(encoding="utf-8") == source
            saved = store.get(label)
            assert saved is not None and saved["command"] == raw["command"] and saved["interpreter"] == raw["interpreter"]
        finally:
            proc.stop()
            assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)
    assert not failures, failures


def test_python3_fallback_to_py_requests_version_three(tmp: Path) -> None:
    from unittest.mock import patch
    import hub.process_manager as pm

    launches = []
    def capture(handle, program, args):
        launches.append((program, list(args)))

    launcher = r"C:\Python\py.exe"
    with patch.object(pm, "IS_WINDOWS", True), \
            patch.object(pm, "resolve_interpreter", return_value=(launcher, None)), \
            patch.object(QProcess, "start", capture):
        for command, interpreter, expected_program, expected_args in (
                ("python3 app.py", "", launcher, ["-3", "app.py"]),
                ("python app.py", "", launcher, ["app.py"]),
                ("python3 app.py", sys.executable, sys.executable, ["app.py"])):
            proc = ProjectProcess({"id": "py-fallback", "name": "Python alias", "command": command,
                                   "interpreter": interpreter, "working_dir": str(tmp), "env": {}})
            proc.start()
            assert launches[-1] == (expected_program, expected_args), launches
            proc.stop()


def test_generated_apostrophe_command_reaches_real_child_argv(tmp: Path) -> None:
    import json
    import subprocess
    from unittest.mock import patch
    from hub import platform as pf, detect_command as dc

    script = tmp / "owner's café app.py"
    body = "import json, sys; print('HUB_EXACT_ARGV=' + json.dumps(sys.argv[1:], ensure_ascii=False), flush=True)\n"
    script.write_text(body, encoding="utf-8")
    suggestion = dc.suggest_for_file(str(script))[0]
    # Exact quote/backslash argv plus a real Unicode filename. Arbitrary Unicode
    # argument normalization is an upstream macOS QProcess property, separately
    # calibrated with raw QProcess vs subprocess; do not hide it as a Hub pass.
    arguments = [r"C:\new\theme.json", "a b", 'literal"quote', "slash\\\"quote"]
    rec = {"id": "quoted-child", "name": "Quoted child", "command": suggestion.command,
           "interpreter": sys.executable, "working_dir": str(tmp),
           "args": subprocess.list2cmdline(arguments), "env": {}}
    proc = ProjectProcess(rec)
    logs = []
    proc.output.connect(logs.append)
    try:
        with patch.object(pf, "IS_WINDOWS", True):
            proc.start()
            assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), logs
        expected = "HUB_EXACT_ARGV=" + json.dumps(arguments, ensure_ascii=False)
        assert proc.proc is not None and proc.proc.exitCode() == 0 and expected in "".join(logs), logs
        assert rec["command"] == suggestion.command
        assert script.read_text(encoding="utf-8") == body
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_stdout_url_and_utf8_survive_every_pipe_boundary(tmp: Path) -> None:
    class Pipe:
        data = b""
        def readAllStandardOutput(self):
            data, self.data = self.data, b""
            return data
        def processId(self):
            return 0
        def state(self):
            return QProcess.NotRunning
        def exitCode(self):
            return 0

    expected = "http://127.0.0.1:8123/dashboard?x=1%202"
    failures = []
    for ending in ("\n", "\r\n", " "):
        text = "café server at " + expected + ending
        payload = text.encode("utf-8")
        for cut in range(1, len(payload)):
            proc = ProjectProcess({"name": "Pipe framing", "command": "node server.js",
                                   "working_dir": str(tmp), "detected": {"type": "web"}})
            pipe = Pipe()
            proc.proc = pipe
            seen = []
            proc.url_detected.connect(seen.append)
            for chunk in (payload[:cut], payload[cut:]):
                pipe.data = chunk
                proc._drain(pipe)
                if any(url != expected for url in seen):
                    failures.append((ending, cut, "partial URL emitted", list(seen)))
                    break
            if seen != [expected] or "".join(proc.history) != text:
                failures.append((ending, cut, "lost URL or damaged UTF8", seen, "".join(proc.history)))
    assert not failures, failures

    # A final unterminated token becomes complete only at actual stream end.
    proc = ProjectProcess({"name": "Final pipe", "command": "node server.js", "detected": {"type": "web"}})
    pipe = Pipe()
    proc.proc = pipe
    seen = []
    proc.url_detected.connect(seen.append)
    pipe.data = ("Serving on " + expected).encode()
    proc._drain(pipe)
    assert seen == [], ("unterminated token was committed early", seen)
    proc._on_finished(0, None, pipe)
    assert seen == [expected], ("final output was lost", seen)


def test_cleanup_waiter_actually_reaps_the_owned_qprocess(tmp: Path) -> None:
    import shlex
    from helpers import stop_and_release

    expression = "import time; print('HUB_CLEANUP_READY', flush=True); time.sleep(60)"
    proc = ProjectProcess({"id": "cleanup-owned", "name": "Owned cleanup", "working_dir": str(tmp),
                           "command": shlex.quote(sys.executable) + " -c " + shlex.quote(expression), "env": {}},
                          term_grace_ms=100)
    output = []
    proc.output.connect(output.append)
    try:
        proc.start()
        assert _wait_for(lambda: "HUB_CLEANUP_READY" in "".join(output)), output
        stop_and_release(proc, timeout_s=3)
        state = proc.proc.state() if proc.proc is not None else None
        assert state == QProcess.NotRunning, (
            "cleanup returned before Qt reaped the owned child; blocking sleep starved its finished signal", state, list(output)
        )
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_non_python_program_uses_the_project_path(tmp: Path) -> None:
    """A generic executable must use the same PATH as its actual environment."""
    import os
    import shlex
    import shutil
    import subprocess
    from unittest.mock import patch

    tools = []
    for label in ("parent", "project"):
        folder = tmp / label
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(folder)], check=True)
        binary = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        tool = binary.with_name("hub-compat-tool.exe" if sys.platform == "win32" else "hub-compat-tool")
        if sys.platform == "win32":
            shutil.copy2(binary, tool)
        else:
            # macOS framework Python is not a relocatable binary. Use an owned
            # executable shim; forward argv unchanged to the intact test venv.
            tool.write_text("#!" + sys.executable + "\nimport os, sys\nos.execv(" +
                            repr(str(binary)) + ", [" + repr(str(binary)) + "] + sys.argv[1:])\n", encoding="utf-8")
            tool.chmod(0o700)
        expression = "import sys; print('HUB_GENERIC_PREFIX=' + sys.prefix, flush=True)"
        control = subprocess.run([str(tool), "-c", expression], capture_output=True, text=True, timeout=15)
        assert control.returncode == 0 and str(folder) in control.stdout, (
            "fixture is not a working standalone generic executable", control.stdout, control.stderr
        )
        tools.append(tool)
    parent_tool, project_tool = tools
    inherited = os.environ.get("PATH", "")
    rec = {"id": "generic-path", "name": "Generic tool", "working_dir": str(tmp),
           "command": project_tool.name + " -c " + shlex.quote(expression),
           "env": {"PATH": str(project_tool.parent) + os.pathsep + inherited}}
    original = dict(rec)
    proc = ProjectProcess(rec)
    output = []
    proc.output.connect(output.append)
    try:
        with patch.dict(os.environ, {"PATH": str(parent_tool.parent) + os.pathsep + inherited}):
            proc.start()
            assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), output
        assert proc.proc is not None and proc.proc.exitCode() == 0
        assert "HUB_GENERIC_PREFIX=" + str(project_tool.parent.parent) in "".join(output), (
            "generic command did not use its project PATH", list(output)
        )
        assert rec == original, "launch rewrote the saved command or environment"
        # Relative PATH entries are interpreted from the child's working folder,
        # not the Hub's own directory; keep the saved spelling unchanged.
        relative_env = {"PATH": os.path.relpath(project_tool.parent, tmp) + os.pathsep + inherited}
        proc.rec = dict(rec, env=relative_env)
        output.clear()
        with patch.dict(os.environ, {"PATH": str(parent_tool.parent) + os.pathsep + inherited}):
            proc.start()
            assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), output
        assert "HUB_GENERIC_PREFIX=" + str(project_tool.parent.parent) in "".join(output), (
            "relative project PATH was resolved from the Hub instead of the project", list(output)
        )
        assert proc.rec["env"] == relative_env
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_existing_node_and_bash_commands_keep_their_cli_contract(tmp: Path) -> None:
    """Use installed tools only; optional languages are not app dependencies."""
    import json
    import os
    import shlex
    import shutil

    cases = []
    node = shutil.which("node")
    if node:
        script = tmp / "own node fixture.js"
        script.write_text("console.log(JSON.stringify({args:process.argv.slice(2), marker:process.env.HUB_FIXTURE_MARKER}));\n", encoding="utf-8")
        cases.append((node, [str(script), "a b", "literal" + chr(34) + "quote"], "node"))
    bash = shutil.which("bash") if sys.platform != "win32" else None
    if bash:
        script = tmp / "own bash fixture.sh"
        script.write_text('printf "HUB_BASH=%s|%s\\n" "$HUB_FIXTURE_MARKER" "$1"\n', encoding="utf-8")
        cases.append((bash, [str(script), "a b"], "bash"))
    if not cases:
        raise SkipTest("Node/Bash not installed; no extra language runtime installed by tests")
    for tool, args, language in cases:
        rec = {"id": "generic-" + language, "name": language, "working_dir": str(tmp),
               "command": " ".join(shlex.quote(value) for value in [tool, *args]),
               "env": {"HUB_FIXTURE_MARKER": "OWNED_COMPAT"}}
        proc = ProjectProcess(rec)
        output = []
        proc.output.connect(output.append)
        try:
            proc.start()
            assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), output
            text = "".join(proc.history)  # child bytes, not Hub's exit-status decoration
            assert proc.proc is not None and proc.proc.exitCode() == 0, (language, text)
            if language == "node":
                value = json.loads(text)
                assert value == {"args": ["a b", 'literal"quote'], "marker": "OWNED_COMPAT"}, value
            else:
                assert text == "HUB_BASH=OWNED_COMPAT|a b" + os.linesep or text == "HUB_BASH=OWNED_COMPAT|a b\n", text
        finally:
            proc.stop()
            assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


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
