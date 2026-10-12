"""The version the app reports must match the version that was packaged.

The About dialog reads hub.__version__, while the DMG/filename comes from
pyproject.toml. Those two drifted apart for several releases — the About box
kept saying 0.1.0 while the builds were 0.1.2 through 0.1.5 — because the
version was hardcoded in two places. __version__ now reads the installed
package metadata, so this test is the guard that they agree.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _pyproject_version() -> str:
    text = (REPO / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "could not find version in pyproject.toml"
    return m.group(1)


def test_reported_version_matches_pyproject() -> None:
    """__version__ must equal the version in pyproject.toml.

    A mismatch means the About dialog is lying about what the user installed.
    """
    from hub import __version__

    declared = _pyproject_version()
    assert __version__ == declared, (
        f"About dialog would report {__version__} but the build is {declared}. "
        "hub/__init__.py must not hardcode a version."
    )


def test_reported_version_is_not_stale() -> None:
    """Guard the specific regression: a hardcoded old version."""
    from hub import __version__

    assert __version__ != "0.1.0", (
        "hub.__version__ is the old hardcoded value; it must read the package "
        "metadata so it tracks pyproject.toml."
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
