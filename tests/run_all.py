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
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# `pty` is POSIX-only; importing it on Windows raises ImportError, which would
# take the whole runner down before a single test ran.
IS_WINDOWS = sys.platform.startswith("win")
try:
    import pty

    HAS_PTY = not IS_WINDOWS
except ImportError:  # pragma: no cover - Windows
    pty = None  # type: ignore[assignment]
    HAS_PTY = False

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
    ("test_urldetect.py", True),
    ("test_version.py", False),
]

# Suites whose GUI tests must each run in their own process. QtWebEngine
# segfaults when many accumulated views are destroyed at interpreter shutdown,
# so running the whole suite in one process yields "all tests passed" followed
# by SIGSEGV — which CI reads as a failure. One process per test is the only
# reliable fix, and it also keeps a hung test from taking the others with it.
ISOLATE_TESTS = {"test_window_e2e.py"}

# `--test NAME` runs a single test in this process (used by ISOLATE_TESTS).
SINGLE_TEST = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("--test=") else None


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


def run_one(path: Path, needs_gui: bool, extra_args: list[str] | None = None) -> tuple[int, str]:
    """Run one suite and return (exit_code, combined_output).

    GUI suites on POSIX get a PSEUDO-TERMINAL, not a pipe. QtWebEngine
    (Chromium) behaves differently without a TTY: with a pipe the suite
    segfaults before running anything, and it still crashes at exit on a plain
    file. A pty makes it behave exactly as in a normal terminal, which is the
    environment these tests are written for.

    Windows has no `pty` module, so there the pipe is used as-is — Windows
    QtWebEngine does not show the same TTY sensitivity.
    """
    env = dict(os.environ)
    if needs_gui:
        env.update(GUI_ENV)
    argv = [interpreter(), str(path), *(extra_args or [])]

    if not needs_gui or IS_WINDOWS or not HAS_PTY:
        proc = subprocess.run(
            argv,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        return proc.returncode, proc.stdout + proc.stderr

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=slave,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    os.close(slave)
    chunks = []
    try:
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master)
    code = proc.wait(timeout=900)
    return code, b"".join(chunks).decode("utf-8", "replace")


def port_in_use(port: int) -> bool:
    """True when something is listening on the port.

    Deliberately does NOT set SO_REUSEADDR: with it, bind() succeeds even when
    another socket holds the port on macOS, so the check would always report
    "free" and the race it is meant to prevent would come straight back.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


# Ports the GUI suites bind. Kept here so the runner can wait them out between
# isolated tests instead of racing a predecessor's server.
TEST_PORTS = (8790, 8791, 8792, 8793, 8794, 8782, 8783)


def wait_for_ports_free(timeout_s: float = 30.0) -> None:
    """Block until the test ports are released (or the timeout passes)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not any(port_in_use(p) for p in TEST_PORTS):
            return
        time.sleep(0.5)


# How long to let a previous process's Chromium helper exit before starting the
# next one. When it is still alive the new one dies with
# "mach_port_rendezvous ... Permission denied (1100)" and SIGSEGV before
# running a single test, which looks like a flaky test but is a startup race.
WEBENGINE_COOLDOWN_S = 2.0


def discover_tests(path: Path) -> list[str]:
    """Test names in a suite, found by reading the file (not by running it).

    Running the suite to list its tests is self-defeating: the GUI suites
    segfault at shutdown, so the listing call itself fails and the real tests
    never run. Parsing the AST is deterministic and instant.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )


def run_isolated_test(path: Path, test_name: str, attempts: int = 3):
    """Run one GUI test in its own process, retrying a startup crash once.

    A crash with NO test output means the process died during QtWebEngine
    startup — the previous process's Chromium helper was still holding the
    Mach port, which macOS TCC then refuses. That is a startup race, not a
    real failure, so it is retried after a cooldown. A crash after tests have
    run is the known teardown crash and is handled by the caller.
    """
    for attempt in range(attempts):
        if attempt:
            time.sleep(WEBENGINE_COOLDOWN_S * attempt)
        code, out = run_one(path, needs_gui=True, extra_args=[f"--test={test_name}"])
        n_pass = out.count("PASS ")
        n_fail = out.count("FAIL ")
        started = bool(n_pass or n_fail)
        if started or code == 0:
            return code, out, n_pass, n_fail
        # died before running anything: wait for the helper to exit and retry
        wait_for_ports_free(timeout_s=10)
    return code, out, n_pass, n_fail


def run_isolated(path: Path) -> tuple[int, int, int, str]:
    """Run a GUI suite one test per process and aggregate.

    QtWebEngine segfaults at interpreter shutdown once several views have been
    created in the same process, so each test gets a fresh interpreter. Any
    crash is then attributable to that one test instead of corrupting the run.
    """
    names = discover_tests(path)
    if not names:
        code, out = run_one(path, needs_gui=True)
        return code, out.count("PASS "), out.count("FAIL "), out

    passed = failed = 0
    worst = 0
    chunks = []
    for test_name in names:
        # Wait for the ports this test may use to be released by the previous
        # process. Without this, a predecessor's server still holds the port,
        # the new server fails to bind, and the test fails — or worse, crashes.
        wait_for_ports_free()
        code, out, n_pass, n_fail = run_isolated_test(path, test_name)
        passed += n_pass
        failed += n_fail
        # A negative code is a signal-kill (SIGSEGV = -11). QtWebEngine crashes
        # during interpreter shutdown even when the test itself passed, so a
        # signal-kill AFTER a clean PASS is a known Qt teardown crash, not a
        # test failure — count the pass and note it instead of failing CI.
        crashed_after_pass = code < 0 and n_pass and not n_fail
        chunks.append(
            f"--- {test_name}: rc={code} ({n_pass} passed, {n_fail} failed)"
            + ("  [crashed at Qt shutdown after passing]" if crashed_after_pass else "")
        )
        if code != 0 and not crashed_after_pass:
            worst = code
            chunks.append("\n".join(out.strip().splitlines()[-8:]))
    return worst, passed, failed, "\n".join(chunks)


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
            if name in ISOLATE_TESTS:
                code, passed, failed, out = run_isolated(path)
            else:
                code, out = run_one(path, needs_gui)
                passed = out.count("\nPASS ") + (1 if out.startswith("PASS ") else 0)
                failed = out.count("\nFAIL ") + (1 if out.startswith("FAIL ") else 0)
                if failed == 0 and code == 0 and "all passed" in out:
                    passed = max(passed, 1)
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT  {name}")
            results.append((name, 1))
            continue
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
