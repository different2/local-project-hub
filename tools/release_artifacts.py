"""Stable download names shared by packaging, publication and README guards."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import unquote, urlparse

ASSET_NAMES = {
    "macos": "Local.Project.Hub.dmg",
    "windows": "Local.Project.Hub.msi",
    "linux": "Local.Project.Hub.Ubuntu-24.04-amd64.deb",
}


def collect_installer(platform: str, source: Path, output: Path) -> Path:
    name = ASSET_NAMES[platform]
    candidates = list(Path(source).glob("*" + Path(name).suffix))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one {platform} installer, found {candidates}")
    candidate = candidates[0]
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("installer must be a regular build output")
    with candidate.open("rb") as stream:
        header = stream.read(8)
        if platform == "macos":
            if candidate.stat().st_size < 512:
                raise ValueError("invalid DMG header/footer")
            stream.seek(-512, 2)
            valid = stream.read(4) == b"koly"
        elif platform == "windows":
            valid = header == bytes.fromhex("d0cf11e0a1b11ae1")
        else:
            valid = header == b"!<arch>\n"
    if not valid:
        raise ValueError(f"invalid {platform} installer header/footer")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    dest = output / name
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"refusing to overwrite {dest}")
    # Exclusive creation also closes the check/copy race and rejects dead links.
    with candidate.open("rb") as source_stream, dest.open("xb") as dest_stream:
        shutil.copyfileobj(source_stream, dest_stream)
    shutil.copystat(candidate, dest)
    return dest


def _release_reference(payload: dict, version: str, repository: str, *, allow_draft=False) -> str:
    """Validate shared release fields without projecting or inventing assets."""
    if not isinstance(payload, dict):
        raise ValueError("release metadata must be an object")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError(f"invalid declared release version: {version!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identifier")
    tag = "v" + version
    if payload.get("tag_name") != tag or payload.get("prerelease") is not False:
        raise ValueError("release tag/version or prerelease status does not match")
    if payload.get("draft") is not False and not (allow_draft and payload.get("draft") is True):
        raise ValueError("release is not published")
    # Unpublished GitHub drafts use an opaque untagged-* preview reference.
    # Match that exact draft's own preview URL; published releases still MUST
    # use their declared version tag, even when allow_draft was requested.
    reference = tag
    if payload.get("draft") is True:
        preview = urlparse(str(payload.get("html_url", "")))
        prefix = f"/{repository}/releases/tag/"
        path = unquote(preview.path)
        if (preview.scheme != "https" or preview.netloc != "github.com"
                or preview.params or preview.query or preview.fragment or not path.startswith(prefix)):
            raise ValueError("draft preview URL does not match this repository")
        reference = path[len(prefix):]
        if reference != tag and not re.fullmatch(r"untagged-[A-Za-z0-9_-]+", reference):
            raise ValueError("draft preview reference does not match this release")
    return reference


def _release_assets(payload: dict) -> list[dict]:
    assets = payload.get("assets")
    if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
        raise ValueError("release assets must be a list of objects")
    return assets


def _validate_asset(asset: dict, repository: str, reference: str) -> None:
    if asset.get("state") != "uploaded" or type(asset.get("size")) is not int or asset["size"] <= 0:
        raise ValueError(f"asset is incomplete: {asset.get('name')}")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(asset.get("digest", ""))):
        raise ValueError(f"asset has no usable SHA-256 digest: {asset.get('name')}")
    url = urlparse(str(asset.get("browser_download_url", "")))
    expected = f"/{repository}/releases/download/{reference}/{asset['name']}"
    if url.scheme != "https" or url.netloc != "github.com" or unquote(url.path) != expected or url.params or url.query or url.fragment:
        raise ValueError(f"asset download URL does not match this release: {asset.get('name')}")


def validate_release(payload: dict, version: str, repository: str, *, allow_draft=False) -> None:
    """Reject partial, wrong-version or unverifiable release metadata."""
    reference = _release_reference(payload, version, repository, allow_draft=allow_draft)
    assets = _release_assets(payload)
    names = [asset.get("name") for asset in assets]
    if len(names) != len(ASSET_NAMES) or set(names) != set(ASSET_NAMES.values()):
        raise ValueError(f"expected exactly all platform installers; received {names}")
    for asset in assets:
        _validate_asset(asset, repository, reference)


def validate_macos_input(payload: dict, version: str, repository: str, source_commit: str,
                         installer: Path | None = None) -> None:
    """Gate a source-bound Mac upload in a PRIVATE draft, not publication."""
    reference = _release_reference(payload, version, repository, allow_draft=True)
    if payload.get("draft") is not True:
        raise ValueError("macOS input must be a private draft")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source commit must be literal 40 lowercase hex characters")
    macos = [asset for asset in _release_assets(payload) if asset.get("name") == ASSET_NAMES["macos"]]
    if len(macos) != 1:
        raise ValueError("expected exactly one macOS installer in the private draft")
    asset = macos[0]
    _validate_asset(asset, repository, reference)
    if asset.get("label") != "source:" + source_commit:
        raise ValueError("macOS asset label does not match the source commit")
    if installer is not None:
        installer = Path(installer)
        if not installer.is_file() or installer.is_symlink():
            raise ValueError("macOS installer must be a regular non-symlink file")
        if installer.stat().st_size != asset["size"]:
            raise ValueError("macOS installer size does not match the API asset")
        with installer.open("rb") as stream:
            # The shared collector/receipt checks also run in the retained
            # Python 3.9 development suite; file_digest only exists in 3.11+.
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != asset["digest"].split(":", 1)[1].lower():
                raise ValueError("macOS installer SHA-256 does not match the API asset")
            if installer.stat().st_size < 512:
                raise ValueError("invalid DMG footer")
            stream.seek(-512, 2)
            if stream.read(4) != b"koly":
                raise ValueError("invalid DMG footer")


def _regular_file_in_tree(path: Path, root: Path) -> bool:
    return (path.is_file() and path.is_relative_to(root) and path.resolve().is_relative_to(root)
            and not any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(root)))


def validate_macos_bundle(app_path: Path, version: str, source_root: Path | None = None) -> dict:
    """Inspect real bundle files without importing or launching bundled code."""
    app_path = Path(app_path).resolve()
    info_path = app_path / "Contents" / "Info.plist"
    if not _regular_file_in_tree(info_path, app_path):
        raise ValueError("main Contents/Info.plist must be a regular file inside the bundle")
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        raise ValueError(f"cannot read main Contents/Info.plist: {exc}") from exc
    for field, expected in (("CFBundleShortVersionString", version), ("LSMinimumSystemVersion", "12.0")):
        if not isinstance(info, dict) or info.get(field) != expected:
            raise ValueError(f"main Info.plist {field} must equal {expected!r}")
    # Briefcase's independent build counter defaults to "1", not app.version.
    build_version = info.get("CFBundleVersion")
    if not isinstance(build_version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", build_version):
        raise ValueError("main Info.plist CFBundleVersion must be a numeric build counter")
    bundled = app_path / "Contents" / "Resources" / "app"
    dist_infos = list(bundled.glob("hub-*.dist-info"))
    if len(dist_infos) != 1 or not dist_infos[0].is_dir():
        raise ValueError("expected exactly one bundled hub dist-info directory")
    dist_info = dist_infos[0]
    metadata_path = dist_info / "METADATA"
    if not _regular_file_in_tree(metadata_path, app_path):
        raise ValueError("bundled hub METADATA must be a regular file inside the bundle")
    try:
        metadata = BytesParser().parsebytes(metadata_path.read_bytes())
    except OSError as exc:
        raise ValueError(f"cannot read bundled hub metadata: {exc}") from exc
    if metadata.get_all("Name") != ["hub"] or metadata.get_all("Version") != [version]:
        raise ValueError("bundled hub metadata name/version does not match")
    helpers = sorted({path.resolve() for path in (app_path / "Contents" / "Resources").rglob(
        "QtWebEngineProcess.app/Contents/MacOS/QtWebEngineProcess"
    ) if path.is_file() and os.access(path, os.X_OK) and path.resolve().is_relative_to(app_path)})
    if not helpers:
        raise ValueError("bundled QtWebEngineProcess.app executable is missing or not executable")
    compared = []
    if source_root is not None:
        source_root = Path(source_root).resolve()
        source_hub = source_root / "hub"
        if not source_hub.is_dir() or source_hub.is_symlink():
            raise ValueError("source root must contain the real hub source directory")
        if any(path.is_symlink() for path in source_hub.rglob("*")):
            raise ValueError("source hub tree contains symlinks; source comparison would be incomplete")
        sources = [source_root / "main.py", *source_hub.rglob("*.py")]
        for source in sorted(sources):
            relative = source.relative_to(source_root)
            target = bundled / relative
            if not _regular_file_in_tree(source, source_root) or not _regular_file_in_tree(target, app_path):
                raise ValueError(f"source/bundle file is missing or not regular: {relative.as_posix()}")
            if source.read_bytes() != target.read_bytes():
                raise ValueError(f"bundled source bytes differ: {relative.as_posix()}")
            compared.append(relative.as_posix())
    return {
        "app_path": str(app_path), "version": metadata["Version"], "bundle_build_version": build_version,
        "minimum_system_version": info["LSMinimumSystemVersion"],
        "dist_info": str(dist_info.resolve()), "qtwebengine_process": str(helpers[0]),
        "source_files": compared,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("platform", choices=ASSET_NAMES)
    collect.add_argument("--source", type=Path, default=Path("dist"))
    collect.add_argument("--output", type=Path, default=Path("release-assets"))
    verify = commands.add_parser("verify")
    verify.add_argument("--metadata", type=Path, required=True)
    verify.add_argument("--version", required=True)
    verify.add_argument("--repo", required=True)
    verify.add_argument("--allow-draft", action="store_true")
    macos = commands.add_parser("verify-macos-input", help="validate a private, source-bound Mac upload")
    macos.add_argument("--metadata", type=Path, required=True)
    macos.add_argument("--version", required=True)
    macos.add_argument("--repo", required=True)
    macos.add_argument("--source-commit", required=True)
    macos.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        print(collect_installer(args.platform, args.source, args.output))
    elif args.command == "verify-macos-input":
        validate_macos_input(json.loads(args.metadata.read_text(encoding="utf-8")), args.version,
                             args.repo, args.source_commit, installer=args.file)
        print("Private macOS input and source receipt verified (not publication approval).")
    else:
        validate_release(json.loads(args.metadata.read_text()), args.version, args.repo,
                         allow_draft=args.allow_draft)
        print("All platform installers, upload states, URLs and SHA-256 digests verified.")


if __name__ == "__main__":
    main()
