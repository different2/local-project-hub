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


def _count_tests(
    path: Path, extra: list[str] | None = None
) -> tuple[int, int, int]:
    """(passes, failures, skips) reported by running a suite."""
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
    n_skip = out.count("\nSKIP ") + (1 if out.startswith("SKIP ") else 0)
    return n_pass, n_fail, n_skip


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
        n_pass, n_fail, n_skip = _count_tests(path, [f"--test={first}"])
        if n_pass + n_fail + n_skip != 1:
            offenders.append(
                f"{name}: --test={first} ran "
                f"{n_pass + n_fail + n_skip} tests, expected 1"
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
    """Each isolated process must report exactly one result.

    This is the arithmetic that exposed the bug: 31 isolated processes each
    reporting 28 passes, for a 29-test file.

    The old version ran the WHOLE file once per suite to compare the total with
    the number of tests. On Windows that no longer fits the suite's budget --
    test_urldetect alone takes over ten minutes in one process, so the test
    timed out and verified nothing. The property is per-process, so the first,
    middle and last test of each isolated suite are run separately: a suite
    that ignores `--test` still runs everything and fails here.
    """
    for name in sorted(run_all.ISOLATE_TESTS):
        path = HERE / name
        if not path.exists():
            continue
        names = run_all.discover_tests(path)
        assert names, f"{name} defines no discoverable tests"
        sample = {names[0], names[len(names) // 2], names[-1]}
        for test_name in sorted(sample):
            n_pass, n_fail, n_skip = _count_tests(path, [f"--test={test_name}"])
            total = n_pass + n_fail + n_skip
            assert total == 1, (
                f"{name}: --test={test_name} reported {total} "
                "results; each isolated process must run exactly one test"
            )


# A small suite with the same --test harness shape as the real GUI files. The
# real suites are sampled above because a full-file run of test_urldetect takes
# over ten minutes on Windows; this bounded suite lets the SAME contract be
# checked for every single test name, deterministically, in a few seconds.
_SYNTHETIC_SUITE = """
import sys

ONLY = None
for _arg in sys.argv[1:]:
    if _arg.startswith("--test="):
        ONLY = _arg.split("=", 1)[1]


def test_00(): pass
def test_01(): pass
def test_02(): pass
def test_03(): pass
def test_04(): pass
def test_05(): pass
def test_06(): pass
def test_07(): pass
def test_08(): pass
def test_09(): pass
def test_10(): pass
def test_11(): pass


if __name__ == "__main__":
    names = sorted(
        n for n, f in globals().items()
        if n.startswith("test_") and callable(f)
    )
    if ONLY is not None and ONLY not in names:
        print(f"ERROR no such test: {ONLY}")
        sys.exit(2)
    for name in names:
        if ONLY and name != ONLY:
            continue
        globals()[name]()
        print(f"PASS {name}")
"""


def test_selected_real_test_runs_in_its_own_process_and_alone() -> None:
    """A real suite's selected test runs in a distinct process, alone.

    This is bounded to one selected test per real isolated suite. It checks the
    actual child PID and that no other test name produced a result, which is
    stronger than the count-only sample above. It does not claim every real
    test was exercised here; the aggregate runner does that separately.
    """
    import os

    for name in sorted(run_all.ISOLATE_TESTS):
        path = HERE / name
        if not path.exists():
            continue
        names = run_all.discover_tests(path)
        assert names, f"{name} defines no discoverable tests"
        selected = names[0]
        proc = subprocess.Popen(
            [sys.executable, "-u", str(path), f"--test={selected}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, **GUI_ENV},
        )
        try:
            out, _ = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise AssertionError(f"{name}: --test={selected} timed out")
        assert proc.pid != os.getpid(), f"{name} did not run in a child process"

        results = [
            line for line in out.splitlines()
            if line.startswith(("PASS ", "FAIL ", "ERROR ", "SKIP "))
        ]
        assert any(
            line.split(" ", 1)[1].split(":", 1)[0].strip() == selected
            for line in results
        ), f"{name}: selected test produced no result:\n{out}"
        for other in names[1:]:
            assert not any(
                line.startswith(
                    (f"PASS {other}", f"FAIL {other}",
                     f"ERROR {other}", f"SKIP {other}")
                )
                for line in results
            ), f"{name}: --test={selected} also ran {other}:\n{out}"


_BROKEN_SUITE = """
import sys

ONLY = None
for _arg in sys.argv[1:]:
    if _arg.startswith("--test="):
        ONLY = _arg.split("=", 1)[1]


def test_pass(): pass
def test_fail(): pass
def test_silent(): pass
def test_skip(): pass


if __name__ == "__main__":
    names = sorted(
        n for n, f in globals().items()
        if n.startswith("test_") and callable(f)
    )
    if ONLY is not None and ONLY not in names:
        print(f"ERROR no such test: {ONLY}")
        sys.exit(2)
    fails = 0
    for name in names:
        if ONLY and name != ONLY:
            continue
        if name == "test_silent":
            continue
        if name == "test_skip":
            print("SKIP test_skip: synthetic")
            continue
        if name == "test_fail":
            fails += 1
            print("FAIL test_fail: deliberate")
            continue
        print("PASS " + name)
    sys.exit(1 if fails else 0)
"""


def test_runner_detects_failure_and_missing_results_in_isolation() -> None:
    """The isolated runner must not hide a FAIL or a genuinely silent test."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "test_broken_synthetic.py"
        path.write_text(_BROKEN_SUITE, encoding="utf-8")
        worst, passed, failed, skipped, out = run_all.run_isolated(path)

    assert passed == 1, (passed, failed, skipped, out)
    assert failed == 2, f"expected the FAIL and the silent test: {out}"
    assert skipped == 1, out
    assert "test_silent" in out and "0 passed, 0 skipped, 1 failed" in out, out
    # Do not call report_suite() here: its diagnostic output contains raw
    # `FAIL ...` lines, which the OUTER suite parser would count as a failure
    # even though this test passed. classify_suite is the decision point.
    assert (
        run_all.classify_suite(worst, passed, failed, skipped, out)[0] != 0
    ), "the runner reported a failed isolated run as green"


def test_full_isolation_contract_on_a_bounded_suite() -> None:
    """Every name in a bounded suite is selectable; the full run reports all.

    This covers the complete isolation matrix (every `--test=` value, plus the
    unfiltered run and an unknown name) without running a slow GUI suite in one
    process.
    """
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "test_synthetic.py"
        path.write_text(_SYNTHETIC_SUITE, encoding="utf-8")
        names = run_all.discover_tests(path)
        assert len(names) == 12, names

        for test_name in names:
            n_pass, n_fail, n_skip = _count_tests(path, [f"--test={test_name}"])
            assert (n_pass, n_fail, n_skip) == (1, 0, 0), (
                f"--test={test_name} reported "
                f"({n_pass} passed, {n_fail} failed, {n_skip} skipped); "
                "each isolated process must run exactly that one test"
            )

        n_pass, n_fail, n_skip = _count_tests(path)
        assert (n_pass, n_fail, n_skip) == (12, 0, 0), (
            f"unfiltered run reported {n_pass} passes, {n_fail} failures, "
            f"{n_skip} skips; expected all 12 tests"
        )

        r = subprocess.run(
            [sys.executable, "-u", str(path), "--test=test_does_not_exist_xyz"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, **GUI_ENV},
            timeout=60,
        )
        assert r.returncode != 0, "an unknown --test name exited 0"


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
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "N passed, 1 failed" with no FAIL line naming
                # the 1. An unexpected error is a failure -- report it as one.
                fails += 1
                print(f"ERROR {_name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
