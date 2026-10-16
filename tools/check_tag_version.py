#!/usr/bin/env python3
"""Fail a release when its tag disagrees with the version in pyproject.toml.

Why this exists: the version in `pyproject.toml` becomes the version the
INSTALLED app reports, and the in-app updater decides whether an update is
available by comparing the release tag against that installed version. Tag
`v0.3.9` while `pyproject.toml` still says `0.3.8` and the release ships an
installer whose app reports `0.3.8` — so every user is offered the same update
forever and their version number never moves. It looks like a broken updater
and is miserable to diagnose, because nothing errors: the tag is valid, the
build succeeds, the release publishes.

That mistake is one forgotten edit away on every release, so it is checked
mechanically instead of being remembered.

Usage:
    python3 tools/check_tag_version.py v0.3.9
    python3 tools/check_tag_version.py v0.3.9 --pyproject path/to/pyproject.toml

Exit codes: 0 when they agree, 1 when they do not (with an explanation), and 2
for a malformed tag or unreadable version.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def pyproject_version(pyproject: Path) -> str:
    """The `version = "x.y.z"` declared in the [tool.briefcase] block."""
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"cannot read {pyproject}: {e}")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise SystemExit(f"could not find a version in {pyproject}")
    return m.group(1).strip()


def normalise(tag: str) -> str:
    """A tag minus its leading `v`, so `v0.3.9` compares with `0.3.9`."""
    return re.sub(r"^[vV]", "", tag.strip())


def check(tag: str, pyproject: Path) -> int:
    if not tag:
        print("no tag given to check", file=sys.stderr)
        return 2
    declared = pyproject_version(pyproject)
    if normalise(tag) == normalise(declared):
        print(f"tag {tag!r} matches pyproject version {declared!r}")
        return 0

    print(
        f"\nThis release tag does not match the version in {pyproject.name}.\n\n"
        f"    tag                : {tag}\n"
        f"    pyproject version  : {declared}\n\n"
        "The app reports the pyproject version, and the updater compares the\n"
        "release tag against it. Shipping these two disagreeing means users are\n"
        "offered the same update forever, and their version never changes.\n\n"
        f"Fix: set version = \"{normalise(tag)}\" in {pyproject.name}, commit it,\n"
        "then move the tag to that commit:\n\n"
        f"    git tag -d {tag} && git push origin :refs/tags/{tag}\n"
        f"    git tag -a {tag} -m \"{tag}\" && git push origin {tag}\n",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail a release when its tag disagrees with pyproject.toml."
    )
    ap.add_argument("tag", help="the release tag, e.g. v0.3.9")
    ap.add_argument(
        "--pyproject",
        type=Path,
        default=REPO_ROOT / "pyproject.toml",
        help="path to pyproject.toml (defaults to the repo's)",
    )
    args = ap.parse_args(argv)
    return check(args.tag, args.pyproject)


if __name__ == "__main__":
    raise SystemExit(main())
