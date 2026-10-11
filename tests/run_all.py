#!/usr/bin/env python3
"""Run the whole test suite, one suite at a time.

The GUI suites bind fixed ports so failures stay reproducible, which means
they must NOT run concurrently — two at once makes every test fail because
the port is taken. This runner goes through them serially and prints one
summary, so `python3 tests/run_all.py` is always safe.

Exit code is 0 only when every suite passes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# GUI suites need a Qt platform that works headless on macOS and Linux.
GUI_ENV = {"QT_QPA_PLATFORM": "offscreen"}

# (file, needs_gui)
SUITES = [
    ("test_store.py", False),
    ("test_platform.py", False),
    ("test_updater.py", False),
    ("test_process_e2e.py", True),
    ("test_window_e2e.py", True),
    ("test_popup_bridge.py", True),
]


def interpreter() -> str:
    """The Python that has PySide6 — the project venv if it exists.

    Using bare `sys.executable` is a trap here: whoever launches this script
    may have a different python3 first on PATH (e.g. Homebrew's, which has no
    PySide6), and the GUI suites then fail with ModuleNotFoundError even
    though the app runs fine. Prefer ./.hubenv, which is created for exactly
    this reason.
    """
    venv_py = PROJECT_ROOT / ".hubenv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def run_one(path: Path, needs_gui: bool) -> tuple[int, str]:
    env = dict(os.environ)
    if needs_gui:
        env.update(GUI_ENV)
    proc = subprocess.run(
        [interpreter(), str(path)],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print(f"Running {len(SUITES)} suites serially (GUI suites cannot overlap)\n")
    results = []
    for name, needs_gui in SUITES:
        path = HERE / name
        if not path.exists():
            print(f"  MISSING  {name}")
            results.append((name, 1))
            continue
        try:
            code, out = run_one(path, needs_gui)
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT  {name}")
            results.append((name, 1))
            continue
        # Each suite prints its own PASS/FAIL lines; count them for the summary.
        passed = out.count("\nPASS ") + (1 if out.startswith("PASS ") else 0)
        failed = out.count("\nFAIL ") + (1 if out.startswith("FAIL ") else 0)
        if failed == 0 and code == 0 and "all passed" in out:
            passed = max(passed, 1)
        status = "ok  " if code == 0 else "FAIL"
        print(f"  {status}     {name:26} {passed} passed, {failed} failed")
        if code != 0:
            if "ModuleNotFoundError" in out and "PySide6" in out:
                print(
                    "           ── PySide6 is missing for the interpreter this "
                    "runner used ──\n"
                    f"           interpreter: {interpreter()}\n"
                    "           fix: ./.hubenv/bin/pip install PySide6\n"
                    "           (or delete .hubenv and recreate it)\n"
                )
            tail = "\n".join(out.strip().splitlines()[-12:])
            print(f"           ── last output ──\n{tail}\n")
        results.append((name, code))

    ok = sum(1 for _, c in results if c == 0)
    total = len(results)
    print(f"\n{ok}/{total} suites passed")
    if ok != total:
        print("A busy port is the usual cause when GUI suites fail together —")
        print("check with: lsof -ti:8790,8791,8792,8793,8794,8782,8783,8799,8800,8801 | xargs kill")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
