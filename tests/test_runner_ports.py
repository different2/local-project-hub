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
