"""Stable download names shared by packaging, publication and README guards."""
from __future__ import annotations

import argparse
import json
import re
import shutil
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
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite {dest}")
    shutil.copy2(candidate, dest)
    return dest


def validate_release(payload: dict, version: str, repository: str, *, allow_draft=False) -> None:
    """Reject partial, wrong-version or unverifiable release metadata."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError(f"invalid declared release version: {version!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identifier")
    tag = "v" + version
    if payload.get("tag_name") != tag or payload.get("prerelease") is not False:
        raise ValueError("release tag/version or prerelease status does not match")
    if payload.get("draft") is not False and not (allow_draft and payload.get("draft") is True):
        raise ValueError("release is not published")
    assets = payload.get("assets") or []
    names = [asset.get("name") for asset in assets]
    if len(names) != len(ASSET_NAMES) or set(names) != set(ASSET_NAMES.values()):
        raise ValueError(f"expected exactly all platform installers; received {names}")
    for asset in assets:
        if asset.get("state") != "uploaded" or not isinstance(asset.get("size"), int) or asset["size"] <= 0:
            raise ValueError(f"asset is incomplete: {asset.get('name')}")
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(asset.get("digest", ""))):
            raise ValueError(f"asset has no usable SHA-256 digest: {asset.get('name')}")
        url = urlparse(str(asset.get("browser_download_url", "")))
        expected = f"/{repository}/releases/download/{tag}/{asset['name']}"
        if url.scheme != "https" or url.netloc != "github.com" or unquote(url.path) != expected or url.query or url.fragment:
            raise ValueError(f"asset download URL does not match this release: {asset.get('name')}")


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
    args = parser.parse_args()
    if args.command == "collect":
        print(collect_installer(args.platform, args.source, args.output))
    else:
        validate_release(json.loads(args.metadata.read_text()), args.version, args.repo,
                         allow_draft=args.allow_draft)
        print("All platform installers, upload states, URLs and SHA-256 digests verified.")


if __name__ == "__main__":
    main()
