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


def test_release_tag_must_match_pyproject_version() -> None:
    """A tag that disagrees with pyproject must be refused, not shipped.

    The tag is what the updater compares against the INSTALLED app's version,
    and the app's version comes from pyproject.toml. Tag `v0.3.9` while
    pyproject still says `0.3.8` and every user is offered the same update
    forever with a version number that never moves — with nothing erroring
    anywhere. `tools/check_tag_version.py` runs as the first step of both build
    jobs so that mistake fails in seconds instead of publishing quietly.

    Exercised through the real CLI entry point, so a broken argument name or a
    wrong exit code is caught here rather than in CI.
    """
    import subprocess

    tool = REPO / "tools" / "check_tag_version.py"
    assert tool.exists(), "the tag/version guard is missing"

    declared = _pyproject_version()

    def run(tag: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(tool), tag],
            capture_output=True,
            text=True,
            timeout=60,
        )

    matching = run(f"v{declared}")
    assert matching.returncode == 0, (
        f"a matching tag was refused: {matching.stdout}{matching.stderr}"
    )

    # A tag ahead of the declared version is the exact mistake this guards.
    ahead = run("v9.9.9")
    assert ahead.returncode == 1, (
        "a tag that disagrees with pyproject.toml was accepted — the release "
        "would ship an installer whose app reports the wrong version"
    )
    combined = ahead.stdout + ahead.stderr
    assert declared in combined, (
        "the failure must name the version pyproject actually declares, or the "
        f"fix is guesswork: {combined}"
    )
    assert "9.9.9" in combined, combined


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
