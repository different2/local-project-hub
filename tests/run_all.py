#!/usr/bin/env python3
"""Run the whole test suite, one suite at a time.

The GUI suites create QtWebEngine views, which cannot run concurrently — two
runs at once make tests fail in port-shaped ways — and a couple still bind
fixed ports so failures stay reproducible. This runner goes through them
serially and prints one summary, so `python3 tests/run_all.py` is always safe.

Exit code is 0 only when every suite passes.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _ascii_safe(text: str) -> str:
    """Replace non-ASCII characters with ASCII equivalents.

    The Windows console defaults to cp1252, which cannot encode the box-drawing
    characters this runner used for its section rules. Printing one raised
    UnicodeEncodeError from inside the failure path, so CI reported exit code 1
    with a traceback and never showed which test actually failed.

    Everything is mapped rather than dropped so the output stays readable:
    box rules become '--', em dashes become '-', quotes become ASCII quotes.
    """
    replacements = {
        "\u2500": "-",  # ─ box drawings light horizontal
        "\u2501": "=",  # ━
        "\u2502": "|",  # │
        "\u250c": "+",  # ┌
        "\u2514": "+",  # └
        "\u251c": "+",  # ├
        "\u2014": "-",  # — em dash
        "\u2013": "-",  # – en dash
        "\u2018": "'",  # ' left single quote
        "\u2019": "'",  # ' right single quote
        "\u201c": '"',  # " left double quote
        "\u201d": '"',  # " right double quote
        "\u2026": "...",  # … ellipsis
        "\u00b7": "-",  # · middle dot
        "\u2192": "->",  # → rightwards arrow
        "\u2713": "ok",  # ✓ check mark
        "\u2717": "x",  # ✗ ballot x
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    # Anything still outside ASCII is dropped rather than allowed to raise.
    return text.encode("ascii", "replace").decode("ascii")


def emit(text: str = "") -> None:
    """Print text that cannot fail on a non-UTF-8 console.

    Also tolerates a stdout that has already been closed, which happens when the
    runner is killed mid-suite: a traceback about a closed stream would hide the
    real result.
    """
    try:
        print(_ascii_safe(text))
    except (UnicodeEncodeError, ValueError, OSError):
        pass


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
    ("test_detect_type.py", False),
    ("test_detect_command.py", False),
    ("test_version.py", False),
    ("test_runner_ports.py", False),
    ("test_selfupdate.py", False),
    ("test_output_encoding.py", False),
    ("test_windows_process_stop.py", False),
    ("test_isolation_contract.py", False),
    ("test_workflow_yaml.py", False),
]

# Suites whose GUI tests must each run in their own process. QtWebEngine
# segfaults when many accumulated views are destroyed at interpreter shutdown,
# so running the whole suite in one process yields "all tests passed" followed
# by SIGSEGV — which CI reads as a failure. One process per test is the only
# reliable fix, and it also keeps a hung test from taking the others with it.
#
# Every suite that builds a QWebEngineView belongs here, not just the window
# suite: test_urldetect and test_popup_bridge create views too and were exiting
# -11 with all tests green, which the non-isolated path scored as a failure.
ISOLATE_TESTS = {
    "test_window_e2e.py",
    "test_urldetect.py",
    "test_popup_bridge.py",
}

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
#
# This list had drifted badly: it named 7 ports while the suites actually bind
# 21, so a predecessor's server left holding 8801-8825 was never waited out and
# the next test failed with "readiness never fired" — a port race that reads as
# a logic bug. Derived from the suite files by discover_test_ports() below, so
# adding a port to a test cannot silently fall out of the list again.
TEST_PORT_RANGE = (8782, 8830)


def discover_test_ports() -> tuple[int, ...]:
    """Every port the test files reference, as a sorted tuple.

    Read from the suite sources rather than hand-maintained: a literal list
    goes stale the moment a new test picks a port, and the failure it causes
    (a port race) looks nothing like a missing entry in a list.
    """
    import re

    lo, hi = TEST_PORT_RANGE
    found: set[int] = set()
    for path in HERE.glob("test_*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in re.finditer(r"\b(\d{4,5})\b", text):
            port = int(m.group(1))
            if lo <= port <= hi:
                found.add(port)
    return tuple(sorted(found))


TEST_PORTS = discover_test_ports()


def port_owners(ports) -> set[int]:
    """PIDs LISTENING on these ports (empty where lsof is unavailable).

    -sTCP:LISTEN matters: without it lsof also names every process merely
    connected TO the port — the Hub's own webview included — and the caller
    would then kill innocent bystanders instead of the server.
    """
    if IS_WINDOWS:
        return set()
    args = ["lsof", "-nP", "-sTCP:LISTEN", "-t"]
    for port in ports:
        args.append(f"-iTCP:{port}")
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set()
    pids: set[int] = set()
    for token in out.stdout.split():
        try:
            pids.add(int(token))
        except ValueError:
            pass
    return pids


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_process(pid: int, wait_s: float = 1.5) -> None:
    """SIGTERM the holder, then SIGKILL it if it will not go."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            return
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.05)


def free_test_ports(timeout_s: float = 8.0) -> None:
    """Make the ports this run needs free instead of waiting them out.

    The suites take their ports from the OS (helpers.reserve_port), so a busy
    test port is nearly always something OUTSIDE this run: a Hub project left
    running (obs_live.py sits on 8787), a stray demo server, a leftover child.
    Waiting for such a process to exit on its own cost the full timeout before
    every isolated test — 30s x ~40 tests — for a port it was never going to
    release. Ask the OS who holds it and stop that process instead. What is
    left is a short wait for the socket to actually go away, and it ends the
    moment the port frees.
    """
    deadline = time.time() + timeout_s
    while True:
        busy = [p for p in TEST_PORTS if port_in_use(p)]
        if not busy:
            return
        stopped = []
        for pid in sorted(port_owners(busy)):
            if pid in (os.getpid(), os.getppid()):
                continue
            stop_process(pid)
            stopped.append(pid)
        if stopped:
            names = ", ".join(str(pid) for pid in stopped)
            emit(f"  freed test ports {busy}: stopped pid {names}\n")
        if time.time() >= deadline:
            emit(f"  (warning) test ports still busy after {timeout_s:g}s: {busy}\n")
            return
        time.sleep(0.25)


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
        free_test_ports(timeout_s=10)
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
        free_test_ports()
        code, out, n_pass, n_fail = run_isolated_test(path, test_name)
        passed += n_pass
        failed += n_fail
        if code != 0 and not (n_pass or n_fail):
            # Retries exhausted and this test never reported at all. That is not
            # the known teardown crash (which happens AFTER a test prints PASS
            # and surfaces as a signal-kill), it is a crash the runner would
            # otherwise count as neither passed nor failed — and report_suite's
            # teardown-crash rule (nonzero exit, failed == 0, passed > 0) would
            # then quietly turn the suite green, hiding whatever broke. Count it
            # as a failure; the output, which includes the traceback, is
            # appended below.
            failed += 1
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
            # 8 lines is too few for a test whose failure message is the only
            # useful evidence, and the Windows conflict failures needed the whole
            # message to be diagnosable from the artifact.
            chunks.append("\n".join(out.strip().splitlines()[-25:]))
    return worst, passed, failed, "\n".join(chunks)


def report_failure(name: str, out: str) -> None:
    """Print the detail that explains why a suite failed.

    Extracted from main() so it can be tested directly. This is the code path
    that crashed the Windows job: it printed box-drawing characters to a cp1252
    console, raising UnicodeEncodeError from inside the failure handler and
    destroying the very output needed to diagnose the failure.
    """
    if "ModuleNotFoundError" in out and "PySide6" in out:
        emit(
            "           -- PySide6 is missing for the interpreter this "
            "runner used --\n"
            f"           interpreter: {interpreter()}\n"
            "           fix: ./.hubenv/bin/pip install PySide6\n"
            "           (or delete .hubenv and recreate it)\n"
        )
    # Keep every failure line, not just the ones that survived into the tail.
    # The isolated path attributes a single test's FAIL message to its
    # neighbours in the printed order, and a tail of 12 lines can drop the only
    # line that names the actual error, leaving "rc=1 (0 passed, 1 failed)" and
    # nothing to diagnose from. Full failure lines plus a generous tail make the
    # artifact self-explanatory without a rerun.
    bad = [
        l
        for l in out.splitlines()
        if l.startswith(("FAIL ", "ERROR ", "Traceback")) or "AssertionError" in l
    ]
    if bad:
        emit("           -- failures --")
        for line in bad[:40]:
            emit(f"           {line}")
        emit("")
    tail = "\n".join(out.strip().splitlines()[-25:])
    emit(f"           -- last output --\n{tail}\n")


def report_suite(name: str, code: int, passed: int, failed: int, out: str) -> int:
    """Print one suite's result line plus failure detail. Returns the final code.

    A QtWebEngine segfault at interpreter shutdown exits non-zero even when
    every test passed, so that case is reported as ok rather than failing CI.
    """
    status = "ok  " if code == 0 else "FAIL"
    if code != 0 and failed == 0 and passed > 0:
        status = "ok  "
        code = 0
    emit(f"  {status}     {name:26} {passed} passed, {failed} failed")
    if code != 0:
        report_failure(name, out)
    return code


def main() -> int:
    emit(f"Running {len(SUITES)} suites serially (GUI suites cannot overlap)\n")
    results = []
    for name, needs_gui in SUITES:
        path = HERE / name
        if not path.exists():
            emit(f"  MISSING  {name}")
            results.append((name, 1))
            continue
        # Wait for the PREVIOUS suite's servers to release their ports before
        # starting this one. This has to happen between suites, not only inside
        # an isolated suite: a GUI suite's Qt child can outlive its own exit, so
        # the next suite's server fails to bind and every test in it reports a
        # port-shaped failure ("readiness never fired", "a foreign holder was
        # not reported", "dashboard did not come back") that reads like a logic
        # bug. That is what macOS CI was hitting.
        if results:
            free_test_ports()
        try:
            if name in ISOLATE_TESTS:
                code, passed, failed, out = run_isolated(path)
            else:
                code, out = run_one(path, needs_gui)
                passed = out.count("\nPASS ") + (1 if out.startswith("PASS ") else 0)
                failed = out.count("\nFAIL ") + (1 if out.startswith("FAIL ") else 0)
                # Safety net for a suite not listed in ISOLATE_TESTS that still
                # segfaults at Qt teardown. Without this the next view-creating
                # suite silently turns CI red while every test passes.
                if code != 0 and passed and not failed:
                    emit(
                        f"  NOTE     {name} exited {code} with all "
                        f"{passed} tests passing - a QtWebEngine teardown crash. "
                        f"Add it to ISOLATE_TESTS."
                    )
                    code = 0
                if failed == 0 and code == 0 and "all passed" in out:
                    passed = max(passed, 1)
        except subprocess.TimeoutExpired:
            emit(f"  TIMEOUT  {name}")
            results.append((name, 1))
            continue
        code = report_suite(name, code, passed, failed, out)
        results.append((name, code))

    ok = sum(1 for _, c in results if c == 0)
    total = len(results)
    emit(f"\n{ok}/{total} suites passed")
    if ok != total:
        emit("A busy port is the usual cause when GUI suites fail together.")
        emit("The runner stops whatever holds a test port before each test;")
        emit("if this persists, see what is still bound:")
        emit("    lsof -nP -iTCP:8782-8830 -sTCP:LISTEN")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
