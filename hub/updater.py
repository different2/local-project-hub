"""In-app update check against a GitHub Releases endpoint (release spec §5).

Design constraints from the spec, and how each is met:

  * "Prefer a secure, established update system over a custom implementation
    that executes arbitrary downloaded scripts" — this module only *reads*
    release metadata and hands the artifact to the platform installer. It
    never executes a downloaded payload itself.
  * "Do not rely on HTTPS alone" — the release endpoint may publish a
    checksum (SHA-256) alongside the artifact, which is verified here.
    Signature verification is delegated to the installer where the platform
    supports it (see PHASE plan: macOS notarization / Windows Authenticode).
  * "Never replace a running executable in an unsafe manner" — the download is
    staged to a temp file, then the OS installer is invoked; the running app
    is never overwritten in place.
  * "Do not claim an update succeeded until the installed version has been
    verified" — callers re-read __version__ after restart.

The endpoint is configured in hub/update_config.py so a fork can point at its
own repo without editing logic.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import __version__
from .platform import IS_MACOS, IS_WINDOWS, arch_label


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    sha256: str = ""


@dataclass
class Release:
    version: str
    notes: str = ""
    assets: list[Asset] = field(default_factory=list)
    html_url: str = ""


class UpdateError(Exception):
    """A check failed in a way worth showing the user."""


def _version_tuple(v: str) -> tuple:
    """'1.2.3' -> (1, 2, 3) for comparison; tolerant of 'v' prefixes and suffixes."""
    v = (v or "").strip().lstrip("vV")
    parts = []
    for chunk in v.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def is_newer(candidate: str, current: str | None = None) -> bool:
    current = current or __version__
    return _version_tuple(candidate) > _version_tuple(current)


def _asset_for_platform(assets: list[Asset]) -> Asset | None:
    """Pick the right artifact for this OS and CPU (release spec §5)."""
    arch = arch_label()
    wanted_ext = []
    if IS_MACOS:
        wanted_ext = [".dmg", ".pkg"]
    elif IS_WINDOWS:
        wanted_ext = [".msi", ".exe"]

    # Prefer an arch-specific name, then any matching extension.
    for want in wanted_ext:
        for a in assets:
            n = a.name.lower()
            if n.endswith(want) and arch in n:
                return a
    for want in wanted_ext:
        for a in assets:
            if a.name.lower().endswith(want):
                return a
    return None


def parse_release(payload: dict) -> Release:
    """Turn a GitHub Releases API object into a Release."""
    version = (payload.get("tag_name") or payload.get("name") or "").strip()
    assets = []
    for a in payload.get("assets") or []:
        assets.append(
            Asset(
                name=a.get("name", ""),
                url=a.get("browser_download_url") or a.get("url", ""),
                size=a.get("size", 0) or 0,
                sha256=_sha256_from_asset(a),
            )
        )
    return Release(
        version=version,
        notes=(payload.get("body") or "").strip(),
        assets=assets,
        html_url=payload.get("html_url", ""),
    )


def _sha256_from_asset(a: dict) -> str:
    """The sha256 for a release asset, or "" when the API supplied none.

    GitHub reports the digest of an uploaded asset under `digest` as
    `"sha256:<64 hex chars>"`. This is the only checksum a release carries
    unless a separate SHA256SUMS file is published alongside the installers.

    Reading it is what makes the integrity check real. `_download_update` only
    verifies when `asset.sha256` is non-empty, so a release with no digest and
    no SHA256SUMS file meant EVERY update installed an unverified download
    while the code looked like it was checking. The previous implementation
    read a `_digests` key that the GitHub API never returns, so the check could
    not have fired even once.
    """
    digest = str(a.get("digest") or "").strip()
    if not digest.lower().startswith("sha256:"):
        return ""
    hexdigest = digest.split(":", 1)[1].strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", hexdigest):
        return hexdigest.lower()
    return ""


def fetch_latest_release(timeout: float = 12.0) -> Release:
    """Fetch and parse the latest release. Raises UpdateError on failure."""
    from .update_config import RELEASE_API_URL

    if not RELEASE_API_URL:
        raise UpdateError(
            "No update endpoint is configured for this build, so updates "
            "cannot be checked."
        )
    req = urllib.request.Request(
        RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"LocalProjectHub/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(
                "No published releases were found yet, so there is nothing to update to."
            ) from e
        raise UpdateError(f"Update check failed (HTTP {e.code}).") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(
            "Could not reach the update server. Check your connection and try again."
        ) from e
    except json.JSONDecodeError as e:
        raise UpdateError("The update server returned an unreadable response.") from e

    release = parse_release(data)
    if not release.version:
        raise UpdateError("The latest release has no version number.")
    return release


def verify_sha256(path, expected: str) -> bool:
    """Constant-time-ish integrity check of a downloaded artifact."""
    if not expected:
        return False
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.strip().lower()


def summarize_release(release: Release) -> str:
    """Short, human release summary for the dialog (spec: 'concise summary')."""
    lines = [f"Version {release.version} is available."]
    notes = (release.notes or "").strip()
    if notes:
        first = notes.splitlines()
        kept = [ln for ln in first[:6] if ln.strip()]
        if kept:
            lines.append("")
            lines.extend(kept)
        if len(first) > 6:
            lines.append(f"…and {len(first) - 6} more lines")
    return "\n".join(lines)
