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
    """TEST_PORTS must cover every port the test files reference."""
    used: set[int] = set()
    for path in HERE.glob("test_*.py"):
        for m in re.finditer(r"\b(\d{4,5})\b", path.read_text(encoding="utf-8")):
            port = int(m.group(1))
            if 8782 <= port <= 8830:
                used.add(port)
    missing = sorted(used - set(run_all.TEST_PORTS))
    assert not missing, f"ports used by tests but never waited out: {missing}"
    assert len(run_all.TEST_PORTS) >= 20, (
        f"only {len(run_all.TEST_PORTS)} ports tracked; expected ~23"
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
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
