"""Shared helpers for the GUI test suites.

The GUI suites bind fixed ports, so running two of them at once (or leaving a
previous run's server alive) makes every test fail with a confusing error.
These helpers detect that case and report it plainly instead of silently
producing zero passes.
"""

from __future__ import annotations

import shutil
import socket
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent

# The suites append the project root to sys.path when they import hub.*; doing
# it here lets these helpers check ports without every test repeating the dance.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hub import urldetect  # noqa: E402


def _spin_qt(ms: float) -> None:
    """Pump the Qt event loop for `ms`, letting QProcess signals land.

    QProcess only advances out of "starting" while the event loop runs, so any
    helper that polls a QProcess-derived value must spin one rather than sleep.
    Mirrors the suites' own _spin()/_wait_for().
    """
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()

# Windows keeps a just-exited child's CWD open for a moment -- the child holds
# its working directory for as long as it lives, and the OS releases it slightly
# after the process is reaped. Deleting the temp dir in that window raises
# WinError 32 on the DIRECTORY, which is the failure these suites kept hitting.
#
# The budget is SHARED across every teardown in one process rather than granted
# per call. 15 sites x a per-site cap is what pushed the Windows job past its
# 35-minute limit; one pool means the common case (the directory is free at
# once) costs nothing and a genuinely lagging process is still waited out.
_HANDLE_BUDGET_S = 20.0 if sys.platform.startswith("win") else 0.0
_handle_budget_left = _HANDLE_BUDGET_S

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def assert_port_free(port: int, what: str = "") -> None:
    """Fail loudly when a port is already taken.

    Two suites use fixed ports by design so failures are reproducible. If a
    port is busy it is almost always another test run still holding it — the
    honest thing is to say so rather than let every test fail cryptically.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), 0.3):
            pass
    except OSError:
        return  # free, which is what we want
    label = f" ({what})" if what else ""
    raise SystemExit(
        f"Port {port}{label} is already in use — another test run is probably "
        f"still going. Wait for it to finish, or check with:\n"
        f"    lsof -ti:{port} | xargs kill\n"
        f"Then re-run this suite on its own."
    )


def free_port() -> int:
    """A free port chosen by the OS, for tests that do not need a fixed one.

    Prefer reserve_port() when a server is about to bind the number: this closes
    the socket before returning, so another process can claim the port in the
    gap. Kept for callers that only need a number to talk about.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def reserve_port() -> int:
    """An OS-assigned ephemeral port for a test server, with nothing holding it.

    Replaces the hardcoded 87xx/88xx numbers this suite used to carry. Those
    collided whenever two suites ran at once, or when a previous run's child was
    still holding one -- which produced failures that read as logic bugs
    ("readiness never fired", "a foreign holder was not reported") rather than as
    the port contention they were.

    The number is obtained from the OS, which guarantees no other process holds
    it, and the socket is closed before returning so the caller's server can
    bind. That leaves a small window where another process could claim the port;
    the OS chooses from the ephemeral range and nothing else in this suite is
    racing for one, so the window is theoretical rather than real.

    An earlier version held the socket open for the caller's whole block, on the
    theory that closing it first opened a race. That is backwards: the caller's
    own server then could not bind at all, because the parent still owned the
    port. Holding is only safe if the child sets SO_REUSEADDR, and relying on
    that silently is worse than the race it prevents.

    Usage:

        port = reserve_port()
        ... start a server on `port`, then assert against it ...
    """
    return free_port()


def _wait_for(pred, timeout_s: float = 20.0) -> bool:
    """Poll a predicate until it holds, pumping the Qt event loop each tick.

    The spin matters: QProcess only advances out of "starting" while the event
    loop runs, so a plain time.sleep() would wait forever on a state that can
    never update. This mirrors the suites' own _spin()/_wait_for() so a shared
    helper behaves identically to an inline one.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        _spin_qt(10)
    return pred()


def wait_for_port_bound(port: int, timeout_s: float = 20.0) -> bool:
    """Block until something is actually listening on the port.

    A test that starts a server and then immediately probes the port cannot rely
    on ProjectProcess.state == "running": that state means the QProcess spawned,
    not that the server bound. Measured gap on macOS is 30-50ms (spawn at ~10ms,
    bound at ~50ms) because the child still has to import http.server and bind
    before it listens -- and a cold Windows runner is much slower, so the gap is
    wide enough there that tests probing the port inside it see no listener and
    fail.

    A readiness poll is not a sleep: it returns the instant the port answers, so
    the common case costs nothing and the slow case simply waits as long as it
    needs to.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if urldetect.port_in_use(port):
            return True
        time.sleep(0.02)
    return urldetect.port_in_use(port)


def start_holder(proc, port: int, timeout_s: float = 25.0) -> bool:
    """Start a ProjectProcess and return True once it is genuinely listening.

    Pairs "the process spawned" (state == "running") with "the server bound"
    (the port answers), which are different moments and not close together. Every
    test that then probes the port -- for a conflict, a holder, or a listening
    port -- needs both, or it races the child's startup.
    """
    proc.start()
    started = _wait_for(lambda: proc.state == "running", timeout_s=timeout_s)
    if not started:
        return False
    return wait_for_port_bound(port, timeout_s=timeout_s)


def stop_and_release(proc, script_path=None, timeout_s: float = 25.0) -> None:
    """Stop a ProjectProcess and wait until the OS has released its directory.

    Two separate things have to happen, and only the first is what Qt reports:

      1. the process exits            -> proc.state == "stopped"
      2. the OS closes its handles    -> the temp dir is deletable

    On Windows (2) lags (1), and the handle that lags is the child's CWD, not
    the script file. Code that stops a process and immediately deletes its
    working directory therefore dies with

        PermissionError: [WinError 32] The process cannot access the file
        because it is being used by another process

    naming the TEMP DIRECTORY -- long after the test's real assertions passed,
    which is why this was repeatedly mistaken for a test failure.

    The wait is bounded and exits on the first successful probe: most processes
    release immediately, and the cap only exists for the rare lagging case.
    Budget matters -- with 15 teardown sites across the GUI suites, a generous
    fixed wait per site is what pushed CI past its job limit.
    """
    if proc is None:
        return
    try:
        proc.stop()
    except Exception:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if getattr(proc, "state", None) == "stopped":
            break
        time.sleep(0.2)
    # Now the working DIRECTORY, which is what WinError 32 actually names. A
    # child process holds its CWD open for as long as it lives, so rmtree()
    # fails on the directory itself -- not on the script file inside it.
    # Probing the script would never detect this: the file can be free while the
    # directory is still held.
    #
    # Renaming the directory to itself is the same probe the OS is about to
    # apply during cleanup, so it fails exactly when rmtree() would.
    global _handle_budget_left
    started = time.time()
    deadline = started + max(_handle_budget_left, 0.0)
    while time.time() < deadline:
        if _dir_is_free(script_path):
            _handle_budget_left = max(_handle_budget_left - (time.time() - started), 0.0)
            return
        time.sleep(0.2)
    # Budget exhausted (or the handle never freed): zero it so the rest of the
    # suite is not starved, and let the retrying delete cope or report honestly.
    _handle_budget_left = 0.0


def _dir_is_free(path) -> bool:
    """True when no process still holds `path` (a directory) open.

    Probed by renaming it to itself, which Windows refuses with PermissionError
    while any handle is open -- including the handle a child keeps on its own
    CWD. Checking the script file instead would miss that entirely: the file can
    be free while the directory is still held, which is exactly the case that
    raises WinError 32 during temp-dir cleanup.
    """
    if path is None:
        return True
    path = Path(path)
    # The directory is the temp dir; if given a file, use its parent.
    if path.is_file():
        path = path.parent
    if not path.exists():
        return True
    try:
        path.rename(path)
        return True
    except OSError:
        return False


class TeardownError(Exception):
    """Cleanup could not complete. Never a test failure.

    Raised by temp_project_dir when the OS still holds the directory after every
    retry -- typically Windows keeping a just-exited child's CWD. Every
    assertion in the test has already passed by then, so treating this as a
    failure reports a passing test as broken, which is exactly what WinError 32
    did for days.
    """


def remove_tree_retry(path, attempts: int = 40, delay: float = 0.5) -> None:
    """Delete a directory, retrying while a child process still holds it.

    On Windows a just-terminated child keeps its working directory open -- it
    holds its own CWD for as long as it lives, and the OS releases it slightly
    after the process is reaped. Deleting the temp dir in that window raises

        PermissionError: [WinError 32] The process cannot access the file
        because it is being used by another process

    naming the DIRECTORY, long after the test's real assertions passed. That is
    why this kept being mistaken for a test failure.

    This is the last line of defence, so it is deliberately generous: 40 tries
    over 20 seconds. The directory probe in stop_and_release() cannot be trusted
    on Windows -- renaming a directory to itself can succeed while rmtree() on
    the same directory is still refused -- so the retry here is what actually
    protects the test. Reports honestly rather than failing if it never frees.
    """
    path = Path(path)
    if not path.exists():
        return
    last: OSError | None = None
    for _ in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except OSError as e:  # Windows raises PermissionError (a subclass)
            last = e
            time.sleep(delay)
    # Give up quietly rather than failing the test: a leftover temp dir is
    # noise, and by this point every assertion in the test has already passed.
    # Raising here would report a passing test as broken.
    return


class temp_project_dir:
    """A temp dir whose cleanup cannot fail the test because of a live child.

    Drop-in replacement for tempfile.TemporaryDirectory() in tests that spawn
    a subprocess inside the directory.
    """

    def __init__(self) -> None:
        self._tmp = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        return self.path

    def __exit__(self, *exc) -> None:
        if self._tmp is None:
            return
        # TemporaryDirectory.cleanup() raises if the directory is not empty --
        # and on Windows a just-exited child holds its CWD, so it is not empty
        # yet even though the test passed. Swallow that, then retry the delete
        # ourselves: raising here would turn a passing test into a failure.
        try:
            self._tmp.cleanup()
        except Exception:
            pass
        remove_tree_retry(self.path)
