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


def test_a_suite_that_runs_no_tests_is_not_green() -> None:
    """0 passed, 0 failed and exit 0 must be a failure, not a green suite.

    A test renamed past its suite's `__main__` loop, a `--test=` filter that
    matched nothing, and a module that imported and returned without running
    anything all exited 0 and printed "ok 0 passed, 0 failed", so the runner
    counted a suite it had not actually run. The Windows audit (2026-10-20)
    flagged that as a test-quality defect: the count line is the only evidence
    that a suite ran.
    """
    import contextlib
    import io

    def run(code: int, passed: int, failed: int) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            final = run_all.report_suite("test_nothing.py", code, passed, failed, "")
        return final, buf.getvalue()

    final, printed = run(0, 0, 0)
    assert final != 0, f"a suite that ran no tests was reported green:\n{printed}"
    assert "FAIL" in printed, f"the empty suite's line did not say FAIL:\n{printed}"

    # Positive control: the same call with real results stays green, so the
    # assertion above is about emptiness and not about report_suite failing
    # everything.
    final, printed = run(0, 3, 0)
    assert final == 0, f"a suite with 3 passing tests was failed:\n{printed}"

    # And the teardown-crash rule that must survive: a signal-killed process
    # after every test passed is a Qt crash, not a red suite.
    final, printed = run(-11, 3, 0)
    assert final == 0, f"a Qt teardown crash after 3 passes failed the run:\n{printed}"


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
