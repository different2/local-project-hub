#!/usr/bin/env python3
"""Local-only macOS release build; never installs or upgrades build dependencies."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from check_tag_version import check as check_tag_version
from release_artifacts import ASSET_NAMES, collect_installer, validate_macos_bundle

from packaging.markers import default_environment
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(argv: list[str], *, capture_output=False) -> subprocess.CompletedProcess:
    """Single slow-command seam; real nonzero exits must propagate unchanged."""
    return subprocess.run(argv, cwd=REPO_ROOT, check=True, text=True, capture_output=capture_output)


def build_release(tag: str, output: Path = Path("release-assets")) -> Path:
    """Build, inspect source parity, package and verify on this Mac only."""
    root = REPO_ROOT
    if Path.cwd().resolve() != root:
        raise ValueError("run from the repository root")
    pyproject = root / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    check_environment(root, config)
    git_root = _run(["git", "rev-parse", "--show-toplevel"], capture_output=True).stdout.strip()
    if Path(git_root).resolve() != root:
        raise ValueError("repository root does not match the source checkout")
    if _run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True).stdout.strip():
        raise ValueError("tracked source is dirty; commit or restore it before building")
    version = config["tool"]["briefcase"]["version"]
    if check_tag_version(tag, pyproject) != 0:
        raise ValueError("release tag does not match pyproject version")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or tag != "v" + version:
        raise ValueError("release tag must be exactly vVERSION")
    output = Path(output)
    if not output.is_absolute():
        output = root / output
    dest = output / ASSET_NAMES["macos"]
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"refusing to overwrite {dest}")
    if list((root / "dist").glob("*.dmg")):
        raise ValueError("dist already contains DMG files; move them aside before building this release")
    _run([sys.executable, "-m", "briefcase", "build", "macOS", "--no-input"])
    formal_name = config["tool"]["briefcase"]["app"]["hub"]["formal_name"]
    app = root / "build" / "hub" / "macos" / "app" / (formal_name + ".app")
    validate_macos_bundle(app, version, source_root=root)
    _run([sys.executable, "-m", "briefcase", "package", "macOS", "-p", "dmg", "--adhoc-sign", "--no-input"])
    installer = collect_installer("macos", root / "dist", output)
    _run(["hdiutil", "verify", str(installer)])
    return installer


def check_environment(root: Path, config: dict) -> None:
    """Require the existing Python 3.11 .buildenv and coherent pinned packages."""
    if sys.platform != "darwin":
        raise ValueError("macOS releases must be built locally on Darwin")
    if sys.version_info[:2] != (3, 11):
        raise ValueError("use the existing Python 3.11 .buildenv")
    buildenv = Path(root) / ".buildenv"
    if not buildenv.is_dir() or Path(sys.prefix).resolve() != buildenv.resolve():
        raise ValueError("run with this repository's existing .buildenv/bin/python")
    briefcase = config["tool"]["briefcase"]
    app = briefcase["app"]["hub"]
    environment = {key: str(value) for key, value in default_environment().items()}
    environment.update(sys_platform="darwin", platform_system="Darwin", python_version="3.11")
    expected = {"briefcase": "0.4.6"}
    for declaration in [*briefcase.get("requires", []), *app.get("requires", []),
                        *app.get("macOS", {}).get("requires", [])]:
        requirement = Requirement(declaration)
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        pins = list(requirement.specifier)
        if requirement.url or len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
            raise ValueError(f"macOS dependency must have an exact pin: {declaration}")
        expected[requirement.name] = pins[0].version
    qt_version = expected.get("PySide6-Essentials")
    if not qt_version or expected.get("PySide6-Addons") != qt_version:
        raise ValueError("PySide6-Essentials and PySide6-Addons must have matching macOS pins")
    expected.update(PySide6=qt_version, shiboken6=qt_version)
    for package, pinned in expected.items():
        try:
            installed = metadata.version(package)
        except metadata.PackageNotFoundError as exc:
            raise ValueError(f"required package is not installed: {package}=={pinned}") from exc
        if installed != pinned:
            raise ValueError(f"installed {package}=={installed} does not match required {pinned}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="candidate release tag, exactly vVERSION (does not create a tag)")
    parser.add_argument("--output", type=Path, default=Path("release-assets"), help="no-clobber installer output directory")
    args = parser.parse_args(argv)
    try:
        installer = build_release(args.tag, args.output)
    except subprocess.CalledProcessError as exc:
        print(f"command failed with exit {exc.returncode}: {exc.cmd}", file=sys.stderr)
        return exc.returncode
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(installer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
