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

# Windows keeps a just-exited child's CWD open for a moment -- the child holds
# its working directory for as long as it lives, and the OS releases it slightly
# after the process is reaped. Deleting the temp dir in that window raises
# WinError 32 on the DIRECTORY, which is the failure these suites kept hitting.
# Generous on Windows, zero cost elsewhere: on POSIX the directory is released
# with the process, so the probe passes on the first try and returns at once.
_HANDLE_SETTLE_S = 12.0 if sys.platform.startswith("win") else 0.0

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
    """A free port chosen by the OS, for tests that do not need a fixed one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stop_and_release(proc, script_path=None, timeout_s: float = 25.0) -> None:
    """Stop a ProjectProcess and wait until the OS has released its port.

    Two separate things have to happen, and only the first is what Qt reports:

      1. the process exits            -> proc.state == "stopped"
      2. the OS closes its handles    -> the port is bindable again

    On Windows (2) lags (1). Code that stops a process and immediately deletes
    its working directory therefore dies with

        PermissionError: [WinError 32] The process cannot access the file
        because it is being used by another process

    long after the test's real assertions passed, which is why this was
    mistaken for a test failure.

    The port wait is deliberately short and only runs when a port is known:
    with 15 teardown sites across the GUI suites, waiting the full teardown
    budget at each one pushed CI past its 20-minute job limit -- the suites
    were correct, they were just slow. Most processes release immediately, so
    this exits on the first successful probe.
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
    deadline = time.time() + _HANDLE_SETTLE_S
    while time.time() < deadline:
        if _dir_is_free(script_path):
            return
        time.sleep(0.2)


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


def remove_tree_retry(path, attempts: int = 12, delay: float = 0.4) -> None:
    """Delete a directory, retrying while a child process still holds a file.

    On Windows a just-terminated child keeps its script file open briefly, so
    the temp-dir cleanup raises

        PermissionError: [WinError 32] The process cannot access the file
        because it is being used by another process

    which fails the test long after the thing it was checking succeeded. This
    waits the handle out instead of failing, and reports honestly if it never
    frees rather than silently leaving a directory behind.
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
    # Leave it in place rather than crash: a leftover temp dir is noise, a
    # failed test is a lie about what the suite was checking.
    print(f"NOTE: could not remove {path} ({last}); leaving it in place")


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
        if self._tmp is not None:
            # suppress TemporaryDirectory's own cleanup error, then retry
            self._tmp.cleanup()
            remove_tree_retry(self.path)
            # A child that is still exiting keeps its script file open, so even
            # the retry can lose the race. Give the OS a moment to release the
            # handle; the directory is already gone by now, this only stops the
            # next test's cleanup from hitting a dying process.
            time.sleep(_HANDLE_SETTLE_S)
