"""Shared helpers for the GUI test suites.

The GUI suites bind fixed ports, so running two of them at once (or leaving a
previous run's server alive) makes every test fail with a confusing error.
These helpers detect that case and report it plainly instead of silently
producing zero passes.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent

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
