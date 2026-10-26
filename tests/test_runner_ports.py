"""Guard the test runner's own port bookkeeping.

A hand-maintained TEST_PORTS list named 7 ports while the suites actually bind
21, so a predecessor's server left holding 8801-8825 was never waited out. The
next test then failed with "readiness never fired", which reads as a bug in the
readiness code but is a port race. These tests make that class of drift fail
loudly instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import run_all  # noqa: E402


def test_gui_backend_matches_native_mac_and_keeps_explicit_overrides() -> None:
    """The observer must use Cocoa on Mac, not Qt6.9's crashing offscreen path."""
    import os

    assert hasattr(run_all, "gui_environment"), "missing platform-aware GUI test environment"
    assert run_all.gui_environment("darwin", {}) == {"QT_QPA_PLATFORM": "cocoa"}
    for platform in ("linux", "win32"):
        assert run_all.gui_environment(platform, {}) == {"QT_QPA_PLATFORM": "offscreen"}
    for platform in ("darwin", "linux", "win32"):
        assert run_all.gui_environment(platform, {"QT_QPA_PLATFORM": "minimal"}) == {
            "QT_QPA_PLATFORM": "minimal"
        }, "an explicit diagnostic backend was silently ignored"
    assert run_all.gui_environment("darwin", {"QT_QPA_PLATFORM": ""}) == {
        "QT_QPA_PLATFORM": "cocoa"
    }
    assert run_all.GUI_ENV == run_all.gui_environment(sys.platform, os.environ), (
        "run_one's actual environment is not wired to the platform selector"
    )


def test_runner_waits_for_every_port_the_suites_bind() -> None:
    """Every port a test file hardcodes must be one the runner waits out.

    The suites used to bind fixed ports (8782-8825), and the runner had to wait
    for each one to be released between runs or the next suite inherited a port
    still held by a previous child. They now take their ports from the OS via
    helpers.reserve_port(), so collisions cannot happen and the wait is belt and
    braces.

    This test still scans for hardcoded numbers, because the invariant is worth
    keeping: if someone reintroduces a fixed port, it must appear in TEST_PORTS.
    The range is deliberately a few numbers wide, so ordinary integers in
    fixtures (timeouts, sizes, ports in sample server output) are not mistaken
    for binds -- those are TEXT the parser is tested against, not ports anything
    listens on.
    """
    used: set[int] = set()
    for path in HERE.glob("test_*.py"):
        for m in re.finditer(r"\b(878\d|88[0-2]\d)\b", path.read_text(encoding="utf-8")):
            used.add(int(m.group(1)))
    missing = sorted(used - set(run_all.TEST_PORTS))
    assert not missing, f"ports used by tests but never waited out: {missing}"


def test_suites_prefer_os_assigned_ports() -> None:
    """The GUI suites must not reintroduce fixed ports.

    reserve_port() asks the OS, so no two suites can contend for one number.
    A bare `port = 8xxx` assignment in a suite is the pattern that caused the
    Windows failures, so it is banned here rather than trusted to review.
    test_runner_ports.py is exempt: it tests this very bookkeeping, so its
    numbers are the subject, not the bug.
    """
    banned = []
    for path in HERE.glob("test_*.py"):
        if path.name == "test_runner_ports.py":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*port = 8[78]\d\d$", line):
                banned.append(f"{path.name}:{i}")
    assert not banned, (
        f"hardcoded port assignments reintroduced; use reserve_port(): {banned}"
    )


def test_test_ports_are_derived_not_hardcoded() -> None:
    """The list must be discovered, so a new port in a test cannot be missed."""
    assert run_all.discover_test_ports() == run_all.TEST_PORTS, (
        "TEST_PORTS is not what discovery found — it has been hardcoded again"
    )
    # a port that appears in no test must not be in the list
    assert 8796 not in run_all.TEST_PORTS or any(
        "8796" in p.read_text(encoding="utf-8") for p in HERE.glob("test_*.py")
    ), "8796 is tracked but no test uses it"


def test_runner_stops_whatever_holds_a_test_port() -> None:
    """A busy port is identified and its owner stopped, not waited out.

    Waiting used to be the behaviour: the runner slept up to 30s before EVERY
    isolated test because a Hub project (obs_live.py on 8787) never releases
    its port on its own — ~40 tests x 30s of pure stall. The runner now asks
    the OS who is listening and stops it, so the wait is only for the socket
    to actually go away.
    """
    import subprocess
    import time

    probe = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import socket, time\n"
            "s = socket.socket()\n"
            "s.bind(('127.0.0.1', 0))\n"
            "s.listen(1)\n"
            "print(s.getsockname()[1], flush=True)\n"
            "time.sleep(60)\n",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        port = int(probe.stdout.readline().strip())
        assert run_all.port_in_use(port), "the probe did not take the port"
        if run_all.IS_WINDOWS:
            return  # no lsof: the runner falls back to waiting there
        owners = run_all.port_owners([port])
        assert probe.pid in owners, f"lsof did not name the holder: {owners}"

        real = run_all.TEST_PORTS
        run_all.TEST_PORTS = (port,)
        try:
            started = time.time()
            run_all.free_test_ports()
            took = time.time() - started
        finally:
            run_all.TEST_PORTS = real

        assert took < 5, f"freeing a held port took {took:.1f}s — still waiting it out"
        probe.wait(timeout=5)
        assert probe.returncode is not None, "the holder was not stopped"
        assert not run_all.port_in_use(port), "the port is still busy after the kill"
    finally:
        if probe.poll() is None:
            probe.kill()
            probe.wait()
        probe.stdout.close()


def test_runner_returns_at_once_when_nothing_holds_a_port() -> None:
    """The common case must not sleep at all.

    Every test in every GUI suite calls this, so a fixed sleep here is paid
    ~40 times per run. With the ports free it has to return immediately.
    """
    import time

    real = run_all.TEST_PORTS
    run_all.TEST_PORTS = ()  # nothing to wait for, whatever is running
    try:
        started = time.time()
        run_all.free_test_ports()
        took = time.time() - started
    finally:
        run_all.TEST_PORTS = real
    assert took < 0.5, f"an empty port list still cost {took:.2f}s"


# ---------- INFO-005: a suite must never be green without results ----------


def test_count_results_counts_error_as_a_failure_and_skip_separately() -> None:
    assert run_all.count_results("PASS a\nPASS b\n--- all passed") == (2, 0, 0)
    assert run_all.count_results("PASS a\nFAIL b\nERROR c") == (1, 2, 0)
    assert run_all.count_results("SKIP a: no IPv6\nPASS b") == (1, 0, 1)
    # A skip is not also a pass.
    assert run_all.count_results("SKIP a: not Windows") == (0, 0, 1)


def test_classification_covers_every_suite_outcome() -> None:
    # normal pass
    assert run_all.classify_suite(0, 3, 0, 0, "PASS a\nPASS b\nPASS c")[0] == 0
    # normal failure
    assert run_all.classify_suite(1, 1, 1, 0, "PASS a\nFAIL b")[0] != 0
    # exit 0 while reporting a failure is NOT green
    assert run_all.classify_suite(0, 3, 1, 0, "PASS a\nFAIL b")[0] != 0
    # empty / malformed output with exit 0 is NOT green
    assert run_all.classify_suite(0, 0, 0, 0, "")[0] != 0
    assert (
        run_all.classify_suite(0, 0, 0, 0, "unrecognised report format")[0] != 0
    )
    # nonzero exit with no results (crash / timeout) is NOT green
    assert run_all.classify_suite(1, 0, 0, 0, "")[0] != 0
    assert run_all.classify_suite(-11, 0, 0, 0, "")[0] != 0
    # timeout has its own blocked label
    assert run_all.classify_suite(1, 0, 0, 0, "TIMEOUT after 5s")[1] == "TIMEOUT"
    # skips are not passes, but a skip-only suite is not a failure either
    code, label, reason = run_all.classify_suite(
        0, 0, 0, 2, "SKIP a: no IPv6\nSKIP b: no IPv6"
    )
    assert code == 0 and label == "ok  " and "2 test(s) skipped" in reason
    # a mixed suite is green with the skip counted separately
    assert run_all.classify_suite(0, 3, 0, 2, "PASS a\nSKIP b")[0] == 0
    # skips never excuse a real failure
    assert run_all.classify_suite(0, 3, 1, 2, "PASS a\nFAIL b\nSKIP c")[0] != 0
    # a missing result blocks the suite, even for a GUI teardown crash
    assert (
        run_all.classify_suite(0, 3, 0, 0, "PASS a", incomplete=1)[1]
        == "BLOCK"
    )
    assert (
        run_all.classify_suite(
            0, 3, 0, 0, "PASS a", incomplete=1, allow_teardown_crash=True
        )[0]
        != 0
    )
    # the known Qt teardown crash is excused only when explicitly enabled
    assert (
        run_all.classify_suite(
            -11, 5, 0, 0, "PASS a", allow_teardown_crash=True
        )[0]
        == 0
    )
    assert (
        run_all.classify_suite(
            -11, 5, 0, 0, "PASS a", allow_teardown_crash=False
        )[0]
        != 0
    )
    # a genuinely empty suite is green only when separately identified as such
    assert run_all.classify_suite(0, 0, 0, 0, "", allow_empty=True)[0] == 0


def test_real_skipped_test_is_reported_as_skip_not_pass() -> None:
    """End-to-end: a host-specific skip must not be counted as a pass.

    The suite harnesses used to print SKIP and then fall through to PASS. This
    runs a real test that is guaranteed to skip offscreen, on every platform,
    and checks the aggregate parser sees one skip and no pass.
    """
    # test_urldetect honours --test; this test skips before touching any
    # platform-specific code, and run_one supplies the GUI environment.
    suite = HERE / "test_urldetect.py"
    name = "test_about_box_hides_extra_window_buttons"
    # This test's subject is a genuine OFFSCREEN skip, even on a Mac whose
    # ordinary GUI suite now exercises Cocoa and actually verifies the buttons.
    real = run_all.GUI_ENV
    try:
        run_all.GUI_ENV = {**real, "QT_QPA_PLATFORM": "offscreen"}
        _code, out = run_all.run_one(
            suite, needs_gui=True, extra_args=[f"--test={name}"]
        )
    finally:
        run_all.GUI_ENV = real
    assert f"SKIP {name}" in out, out
    assert f"PASS {name}" not in out, out
    assert run_all.count_results(out) == (0, 0, 1), out


def _with_fake_runner(result_or_exc, fn):
    real_one = run_all.run_one
    real_iso = run_all.run_isolated

    def fake(path, needs_gui, extra_args=None):
        if isinstance(result_or_exc, BaseException):
            raise result_or_exc
        return result_or_exc

    run_all.run_one = fake
    run_all.run_isolated = lambda path: result_or_exc
    try:
        return fn()
    finally:
        run_all.run_one = real_one
        run_all.run_isolated = real_iso


def test_run_suite_empty_exit_zero_is_not_green() -> None:
    import subprocess

    def run():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert (code, passed, failed, skipped) == (0, 0, 0, 0)
        assert run_all.classify_suite(code, passed, failed, skipped, out)[0] != 0

    _with_fake_runner((0, ""), run)

    def run_malformed():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert run_all.classify_suite(code, passed, failed, skipped, out)[0] != 0

    _with_fake_runner((0, "not a test report"), run_malformed)

    def run_timeout():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert code != 0 and "TIMEOUT" in out
        assert (
            run_all.classify_suite(code, passed, failed, skipped, out)[1]
            == "TIMEOUT"
        )

    _with_fake_runner(subprocess.TimeoutExpired("python", 5), run_timeout)


def test_run_suite_normal_and_failing_runs() -> None:
    def passing():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert run_all.classify_suite(code, passed, failed, skipped, out)[0] == 0
        assert (passed, failed, skipped) == (2, 0, 0)

    _with_fake_runner((0, "PASS a\nPASS b\n--- all passed"), passing)

    def skipped():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert run_all.classify_suite(code, passed, failed, skipped, out)[0] == 0
        assert (passed, failed, skipped) == (0, 0, 1)

    _with_fake_runner((0, "SKIP a: not Windows\n--- all passed (1 skipped)"), skipped)

    def failing():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert run_all.classify_suite(code, passed, failed, skipped, out)[0] != 0
        assert (passed, failed, skipped) == (1, 1, 0)

    _with_fake_runner((1, "PASS a\nFAIL b"), failing)

    def crash():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), False
        )
        assert code != 0
        assert run_all.classify_suite(code, passed, failed, skipped, out)[0] != 0

    _with_fake_runner((-11, ""), crash)

    def nonzero_after_passes_is_only_ok_for_gui():
        code, passed, failed, skipped, out = run_all.run_suite(
            "test_fake.py", Path("test_fake.py"), True
        )
        assert run_all.classify_suite(
            code, passed, failed, skipped, out, allow_teardown_crash=False
        )[0] != 0
        assert run_all.classify_suite(
            code, passed, failed, skipped, out, allow_teardown_crash=True
        )[0] == 0

    _with_fake_runner((-11, "PASS a"), nonzero_after_passes_is_only_ok_for_gui)


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
