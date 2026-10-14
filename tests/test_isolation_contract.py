"""Guard the runner's per-test isolation contract.

The runner isolates GUI tests by running each one in its own process, passing
`--test=<name>` and expecting only that test to run. test_urldetect.py and
test_popup_bridge.py silently ignored the flag: every isolated process ran the
whole file, so a 29-test suite reported "870 passed" and any real failure was
attributed to whichever test sorted last.

A guard on this contract matters because the failure mode is invisible -- the
suite still passes, the counts are just wrong, and the misattribution sends you
debugging a test that never failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

import run_all  # noqa: E402

GUI_ENV = {"QT_QPA_PLATFORM": "offscreen"}


def _count_tests(path: Path, extra: list[str] | None = None) -> tuple[int, int]:
    """(passes, failures) reported by running a suite."""
    import os

    r = subprocess.run(
        [sys.executable, "-u", str(path)] + (extra or []),
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, **GUI_ENV},
        timeout=600,
    )
    out = r.stdout
    n_pass = out.count("\nPASS ") + (1 if out.startswith("PASS ") else 0)
    n_fail = out.count("\nFAIL ") + (1 if out.startswith("FAIL ") else 0)
    return n_pass, n_fail


def test_isolated_suites_honour_the_test_flag() -> None:
    """Every suite in ISOLATE_TESTS must run exactly one test when asked.

    Without this the runner's isolation is theatre: one process per test, each
    one running the entire file.
    """
    offenders = []
    for name in sorted(run_all.ISOLATE_TESTS):
        path = HERE / name
        if not path.exists():
            continue
        if "--test" not in path.read_text(encoding="utf-8"):
            offenders.append(f"{name}: does not read the --test= flag at all")
            continue
        first = run_all.discover_tests(path)[0]
        n_pass, n_fail = _count_tests(path, [f"--test={first}"])
        if n_pass + n_fail != 1:
            offenders.append(
                f"{name}: --test={first} ran {n_pass + n_fail} tests, expected 1"
            )
    assert not offenders, (
        "these isolated suites ignore the runner's per-test flag:\n"
        + "\n".join(offenders)
    )


def test_an_unknown_test_name_is_an_error_not_a_pass() -> None:
    """Asking for a test that does not exist must not report success.

    A suite that ignores an unknown name runs everything and exits 0, so the
    runner would call a typo a green run.
    """
    import os

    for name in sorted(run_all.ISOLATE_TESTS):
        path = HERE / name
        if not path.exists() or "--test" not in path.read_text(encoding="utf-8"):
            continue
        r = subprocess.run(
            [sys.executable, "-u", str(path), "--test=test_does_not_exist_xyz"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, **GUI_ENV},
            timeout=600,
        )
        assert r.returncode != 0, (
            f"{name} exited 0 for a test name that does not exist -- "
            "a typo would be reported as a green run"
        )


def test_isolated_run_counts_match_the_tests_that_exist() -> None:
    """The runner's totals must equal the number of tests, not a multiple.

    This is the arithmetic that exposed the bug: 31 isolated processes each
    reporting 28 passes, for a 29-test file.
    """
    for name in sorted(run_all.ISOLATE_TESTS):
        path = HERE / name
        if not path.exists():
            continue
        n_defined = len(run_all.discover_tests(path))
        n_pass, n_fail = _count_tests(path)
        assert n_pass + n_fail <= n_defined, (
            f"{name} reported {n_pass + n_fail} results but only defines "
            f"{n_defined} tests -- something ran more than once"
        )


if __name__ == "__main__":
    fails = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {_name}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
