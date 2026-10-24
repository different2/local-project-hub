"""Non-GUI socket and process-ownership regressions.

All real listeners use OS-assigned ports. PID-reuse scenarios must mock both
os.kill and os.killpg; no fake PID may receive a real signal.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import SkipTest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hub import process_manager as pm  # noqa: E402
from hub import urldetect  # noqa: E402
from hub.readiness import tcp_open  # noqa: E402


def _project_double(**attributes) -> pm.ProjectProcess:
    """Exercise lifecycle methods without constructing Qt processes/windows."""
    return cast(pm.ProjectProcess, SimpleNamespace(**attributes))


def _restart_probe(port: int, url: str = ""):
    started, states, output = [], [], []
    owner = _project_double(
        _generation=0, _restart_waiting=None,
        rec={"url": url},
        _expected_port=lambda: port,
        start=lambda: started.append(True),
        state_changed=SimpleNamespace(emit=states.append),
        output=SimpleNamespace(emit=output.append),
    )
    pm.ProjectProcess._restart_after_port_free(owner, attempts=0, generation=0)
    return started, states, output


def test_restart_ignores_time_wait_without_a_listener() -> None:
    # The server actively closes the connection, leaving its local endpoint in
    # TIME_WAIT. SO_REUSEADDR lets a normal replacement rebind that endpoint.
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        assert urldetect.port_in_use(port), "a live reusable listener was missed"
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            accepted, _ = listener.accept()
            with accepted:
                accepted.settimeout(2)
                accepted.sendall(b"x")
                accepted.shutdown(socket.SHUT_WR)
                while client.recv(1024):
                    pass
                client.close()
                while accepted.recv(1024):
                    pass

    assert not tcp_open("127.0.0.1", port), "fixture still has a TCP listener"
    assert not urldetect.port_owners(port), "fixture still has a LISTEN owner"
    with socket.socket() as replacement:
        replacement.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        replacement.bind(("127.0.0.1", port))
        replacement.listen(1)

    started, states, output = _restart_probe(port)
    assert started == [True], (
        "listener-free TIME_WAIT blocked a reusable replacement: "
        f"port={port}, states={states}, output={output}"
    )
    assert states == [], states
    assert urldetect.port_in_use(port) is False, "TIME_WAIT was counted as LISTEN"


def _ipv6_listener(host: str = "::1", *, v6only: bool = True):
    try:
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError as exc:
        raise SkipTest(f"IPv6 unavailable: {exc}")
    try:
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, int(v6only))
        listener.bind((host, 0))
        listener.listen(1)
    except OSError as exc:
        listener.close()
        raise SkipTest(f"IPv6 listener unavailable: {exc}")
    return listener


def test_ipv4_project_is_not_blocked_by_an_ipv6_only_listener() -> None:
    with _ipv6_listener() as v6:
        port = v6.getsockname()[1]
        url = f"http://127.0.0.1:{port}/"
        with socket.socket() as v4:
            v4.bind(("127.0.0.1", port))
            v4.listen(1)  # proves these endpoints really are disjoint
        assert urldetect.port_in_use(port), "generic check lost IPv6 coverage"
        conflict = pm._find_foreign_port_holder(url, set())
        assert conflict is None, (
            f"IPv4 endpoint blocked by disjoint IPv6-only listener: {conflict}"
        )
        started, states, output = _restart_probe(port, url)
        assert started == [True], (
            f"IPv4 restart blocked by IPv6-only listener: {states}, {output}"
        )


def test_disjoint_foreign_owner_is_not_adopted_as_an_endpoint_conflict() -> None:
    # A project can already own IPv4 while a foreign service owns only IPv6
    # at the same port. Finding an IPv4 listener must not authorize reporting
    # (or subsequently offering to kill) the unrelated IPv6 owner.
    own, foreign = os.getpid(), 4100002
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def lsof(argv, **kwargs):
            assert argv[0] == "lsof", argv
            if "-t" in argv:
                return SimpleNamespace(stdout=f"{own}\n{foreign}\n", returncode=0, stderr="")
            return SimpleNamespace(stdout=(
                f"p{own}\ntIPv4\nn127.0.0.1:{port}\n"
                f"p{foreign}\ntIPv6\nn[::1]:{port}\n"
            ), returncode=0, stderr="")

        with mock.patch.object(urldetect, "IS_WINDOWS", False), \
             mock.patch.object(pm.subprocess, "run", side_effect=lsof), \
             mock.patch.object(urldetect, "process_command", return_value="fixture"):
            conflict = pm._find_foreign_port_holder(
                f"http://127.0.0.1:{port}/", {own}
            )
        assert conflict is None, f"disjoint IPv6 owner reported as conflict: {conflict}"


def test_ipv6_project_is_not_blocked_by_an_ipv4_listener() -> None:
    with _ipv6_listener():  # capability check before requiring IPv6 below
        pass
    with socket.socket() as v4:
        v4.bind(("127.0.0.1", 0))
        v4.listen(1)
        port = v4.getsockname()[1]
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as v6:
            v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            v6.bind(("::1", port))
            v6.listen(1)
        url = f"http://[::1]:{port}/"
        assert pm._find_foreign_port_holder(url, set()) is None
        started, states, output = _restart_probe(port, url)
        assert started == [True], (states, output)


def _assert_real_conflict(port: int, host: str) -> None:
    url_host = f"[{host}]" if ":" in host else host
    url = f"http://{url_host}:{port}/"
    assert urldetect.port_in_use(port, host), (host, port)
    conflict = pm._find_foreign_port_holder(url, set())
    assert conflict is not None, f"real listener missed: {host}:{port}"
    assert {holder["pid"] for holder in conflict["holders"]} == {os.getpid()}, conflict
    started, states, output = _restart_probe(port, url)
    assert started == [] and states == ["error"], (started, states, output)


def test_ipv4_wildcard_still_blocks_a_real_conflict() -> None:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 0))
        listener.listen(1)
        _assert_real_conflict(listener.getsockname()[1], "127.0.0.1")


def test_dual_stack_wildcard_still_blocks_both_families() -> None:
    with _ipv6_listener("::", v6only=False) as listener:
        port = listener.getsockname()[1]
        # Prove this socket really accepts IPv4 as well as IPv6 on this OS.
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            accepted, _ = listener.accept()
            accepted.close()
        _assert_real_conflict(port, "127.0.0.1")
        _assert_real_conflict(port, "::1")


def test_unknown_host_keeps_either_family_fallback() -> None:
    with _ipv6_listener() as listener:
        port = listener.getsockname()[1]
        for host in (None, "localhost", "unresolved.invalid"):
            assert urldetect.port_in_use(port, host), host
        conflict = pm._find_foreign_port_holder("", set(), fallback_port=port)
        assert conflict is not None, "port-only fallback missed IPv6 listener"
        started, states, output = _restart_probe(port)
        assert started == [] and states == ["error"], (started, states, output)


def test_windows_listener_table_filters_only_explicitly_disjoint_endpoints() -> None:
    port = 53001  # mocked table only; never bound
    rows = [(f"127.0.0.1:{port}", 101), (f"[::1]:{port}", 102)]
    with mock.patch.object(urldetect, "IS_WINDOWS", True), \
         mock.patch.object(urldetect, "_netstat_listening_rows", return_value=rows):
        assert urldetect.port_owners(port, "127.0.0.1") == {101}
        assert urldetect.port_owners(port, "::1") == {102}
        assert urldetect.port_owners(port) == {101, 102}
        rows[:] = [(f"[::1]:{port}", 102)]
        assert not urldetect.port_in_use(port, "127.0.0.1")
        assert urldetect.port_in_use(port, "::1")
        rows[:] = [(f"0.0.0.0:{port}", 103)]
        assert urldetect.port_in_use(port, "127.0.0.1")
        assert not urldetect.port_in_use(port, "::1")
        rows[:] = [(f"[::]:{port}", 104)]
        for host in (None, "127.0.0.1", "::1"):
            assert urldetect.port_in_use(port, host), host
            assert urldetect.port_owners(port, host) == {104}, host


def test_tree_capture_does_not_adopt_a_reused_descendant_pid() -> None:
    root, child = 4100001, 4100002
    root_start = "Sat Oct 24 12:00:00 2026"
    child_start = "Sat Oct 24 12:00:01 2026"
    original_root = f"ps:{root_start}"
    original_child = f"ps:{child_start}"
    replacement = "ps:Sat Oct 24 12:01:00 2026"
    owner = _project_double(
        _live_identity={root: original_root}, proc=object(),
        _pid_of=lambda _: root, _group_verified=lambda *_: False,
    )

    def process_table(argv, **kwargs):
        assert argv[0] == "ps", argv
        # The OS ancestry record saw our child. Before a later per-PID query,
        # it exited and that PID was reused by an unrelated replacement.
        if any("lstart" in arg for arg in argv):
            out = f"{root} 1 {root_start}\n{child} {root} {child_start}\n"
        else:
            out = f"{root} 1\n{child} {root}\n"
        return SimpleNamespace(stdout=out, returncode=0)

    with mock.patch.object(pm, "IS_WINDOWS", False), \
         mock.patch.object(urldetect, "IS_WINDOWS", False), \
         mock.patch.object(urldetect, "IS_LINUX", False), \
         mock.patch.object(pm.subprocess, "run", side_effect=process_table), \
         mock.patch.object(urldetect, "process_identity", side_effect=lambda pid:
                           {root: original_root, child: replacement}.get(pid)), \
         mock.patch.object(pm.os, "kill") as kill, \
         mock.patch.object(pm.os, "killpg") as killpg:
        captured = pm.ProjectProcess._snapshot_tree(owner, root)
        pm.ProjectProcess._signal_owned_tree(owner, captured, root, pm._SIGTERM)
        signalled = [call.args[0] for call in kill.call_args_list]
        assert child not in signalled, (
            "unrelated replacement adopted between ancestry and identity reads: "
            f"captured={captured}, signalled={signalled}"
        )
        assert captured.get(root) == original_root, captured
        assert captured.get(child) == original_child, captured
        kill.assert_called_once_with(root, pm._SIGTERM)
        killpg.assert_not_called()


def test_tree_capture_rejects_an_unverified_root() -> None:
    root, child = 4100001, 4100002
    owner = _project_double(
        _live_identity={root: "original-root"}, proc=object(),
        _pid_of=lambda _: root, _group_verified=lambda *_: False,
    )
    cases = [
        ({root: (1, "replacement-root"), child: (root, "stranger")}, "replacement-root"),
        ({root: (1, "original-root"), child: (root, "owned-child")}, "replacement-root"),
        ({root: (1, "original-root"), child: (root, "owned-child")}, None),
        ({child: (root, "owned-child")}, "original-root"),
        ({}, "original-root"),
    ]
    with mock.patch.object(pm, "IS_WINDOWS", False), \
         mock.patch.object(pm.os, "kill") as kill, \
         mock.patch.object(pm.os, "killpg") as killpg:
        for rows, current in cases:
            with mock.patch.object(urldetect, "process_snapshot", return_value=rows), \
                 mock.patch.object(urldetect, "process_identity", return_value=current):
                tree = pm.ProjectProcess._snapshot_tree(owner, root)
                assert tree == {}, (rows, current, tree)
                pm.ProjectProcess._signal_owned_tree(owner, tree, root, pm._SIGTERM)
        kill.assert_not_called()
        killpg.assert_not_called()


def test_tree_capture_still_signals_verified_descendants() -> None:
    root, child, grandchild, unrelated = 4100001, 4100002, 4100003, 4100004
    identities = {root: "root", child: "child", grandchild: "grandchild"}
    rows = {root: (1, "root"), child: (root, "child"),
            grandchild: (child, "grandchild"), unrelated: (1, "stranger")}
    owner = _project_double(
        _live_identity={root: "root"}, proc=object(),
        _pid_of=lambda _: root, _group_verified=lambda *_: False,
    )
    with mock.patch.object(pm, "IS_WINDOWS", False), \
         mock.patch.object(urldetect, "process_snapshot", return_value=rows), \
         mock.patch.object(urldetect, "process_identity", side_effect=identities.get), \
         mock.patch.object(pm.os, "kill") as kill, \
         mock.patch.object(pm.os, "killpg") as killpg:
        captured = pm.ProjectProcess._snapshot_tree(owner, root)
        assert captured == identities, captured
        pm.ProjectProcess._signal_owned_tree(owner, captured, root, pm._SIGTERM)
        assert {call.args[0] for call in kill.call_args_list} == set(identities)
        killpg.assert_not_called()


def test_linux_snapshot_pairs_parent_and_start_time_from_one_stat_read() -> None:
    root, child = 4100001, 4100002
    proc = Path("/proc")

    def stat(pid: int, parent: int, start: int) -> str:
        # State is field 3; PPID is field 4; starttime is field 22. Include a
        # tricky comm value so splitting on the first ')' would be caught.
        fields = ["S", str(parent)] + ["0"] * 17 + [str(start)]
        return f"{pid} (name with ) parentheses) " + " ".join(fields)

    files = {
        str(proc / "sys/kernel/random/boot_id"): "test-boot\n",
        str(proc / str(root) / "stat"): stat(root, 1, 100),
        str(proc / str(child) / "stat"): stat(child, root, 101),
    }
    reads = []

    def read(path, **kwargs):
        reads.append(str(path))
        if str(path) not in files:
            raise FileNotFoundError(str(path))
        return files[str(path)]

    with mock.patch.object(urldetect, "IS_WINDOWS", False), \
         mock.patch.object(urldetect, "IS_LINUX", True), \
         mock.patch.object(Path, "iterdir", return_value=[proc / str(root), proc / str(child), proc / "gone"]), \
         mock.patch.object(Path, "read_text", autospec=True, side_effect=read):
        rows = urldetect.process_snapshot()
    assert rows == {root: (1, "linux:test-boot:100"),
                    child: (root, "linux:test-boot:101")}, rows
    assert reads.count(str(proc / str(child) / "stat")) == 1, reads


def test_native_process_snapshot_matches_the_current_process_identity() -> None:
    if urldetect.IS_WINDOWS:
        raise SkipTest("POSIX snapshot fallback is not used on Windows")
    rows = urldetect.process_snapshot()
    assert rows.get(os.getpid()) == (os.getppid(), urldetect.process_identity(os.getpid())), (
        "snapshot must preserve the native identity format used at launch"
    )


def test_unreadable_posix_listener_table_stays_conservatively_busy() -> None:
    with mock.patch.object(urldetect, "IS_WINDOWS", False), \
         mock.patch.object(urldetect, "_bind_state", return_value="in_use"), \
         mock.patch.object(pm.subprocess, "run", side_effect=OSError("lsof unavailable")):
        assert urldetect.port_in_use(53001, "127.0.0.1") is True
        assert urldetect.port_owners(53001, "127.0.0.1") == set()


def test_accepted_conflict_launch_ignores_a_disjoint_ipv6_listener() -> None:
    """The GUI's delayed launch must use the endpoint it offered to free.

    The dialog and timer are seams only: two real sockets establish that IPv4
    can be freed while a disjoint IPv6-only listener survives. No Qt window or
    real process signal is needed to drive the actual dialog callback.
    """
    from hub import window as wm

    with _ipv6_listener() as v6, socket.socket() as v4:
        port = v6.getsockname()[1]
        v4.bind(("127.0.0.1", port))
        v4.listen(1)
        ended, scheduled, launched, logs = [], [], [], []
        selected = object()

        class AcceptedDialog:
            Warning = AcceptRole = RejectRole = 0

            def __init__(self, *_args):
                pass

            def __getattr__(self, _name):
                return lambda *_args: None

            def addButton(self, label, *_args):
                return selected if label == "End that process" else object()

            def clickedButton(self):
                return selected

        def end_overlapping_holder(pid):
            assert pid == 4100001, "attempted to end a disjoint listener"
            ended.append(pid)
            v4.close()
            return True

        def launch(rec, _proc):
            with socket.socket() as replacement:
                replacement.bind(("127.0.0.1", port))
                replacement.listen(1)
            launched.append(rec["id"])

        owner = SimpleNamespace(
            _can_show_dialog=lambda: True,
            _append_log=lambda *args: logs.append(args),
            _launch=launch,
        )
        rec = {"id": "fixture", "name": "IPv4 fixture"}
        conflict = {
            "port": port, "host": "127.0.0.1",
            "holders": [{"pid": 4100001, "command": "overlapping IPv4 fixture"}],
        }
        with mock.patch.object(wm, "QMessageBox", AcceptedDialog), \
             mock.patch.object(wm, "QTimer", SimpleNamespace(
                 singleShot=lambda _ms, callback: scheduled.append(callback))), \
             mock.patch.object(urldetect, "kill_process", side_effect=end_overlapping_holder):
            wm.HubWindow._offer_to_free_port(
                cast(wm.HubWindow, owner), rec,
                cast(pm.ProjectProcess, object()), conflict,
            )
            assert ended == [4100001], ended
            assert len(scheduled) == 1, scheduled
            scheduled[0]()

        assert urldetect.port_in_use(port, "::1"), "disjoint listener was lost"
        assert launched == [rec["id"]], (
            "accepted IPv4 conflict did not launch after freeing IPv4: "
            f"launched={launched}, logs={logs}"
        )


if __name__ == "__main__":
    only = next((arg.split("=", 1)[1] for arg in sys.argv[1:]
                 if arg.startswith("--test=")), None)
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)
             and (only is None or name == only)]
    if not tests:
        print(f"ERROR no such test: {only}")
        sys.exit(2)
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except SkipTest as exc:
            print(f"SKIP {name}: {exc}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {name}")
    sys.exit(1 if failed else 0)
