"""In-app update check against a GitHub Releases endpoint (release spec §5).

Design constraints from the spec, and how each is met:

  * "Prefer a secure, established update system over a custom implementation
    that executes arbitrary downloaded scripts" — this module only *reads*
    release metadata and hands the artifact to the platform installer. It
    never executes a downloaded payload itself.
  * "Do not rely on HTTPS alone" — the only integrity metadata this updater
    trusts is the per-asset SHA-256 digest GitHub reports in the release API
    (`assets[].digest`, shaped `sha256:<64 hex>`). There is no separate
    SHA256SUMS asset support. An update is FAIL-CLOSED: if the release gives
    no usable digest, `integrity_problem()` refuses to install it, and a
    downloaded file whose digest does not match is discarded. Missing metadata
    is never treated as successful verification. Signature verification is
    delegated to the installer where the platform supports it (see PHASE plan:
    macOS notarization / Windows Authenticode).
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
import os
import re
import ssl
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


_UNREACHABLE = (
    "Could not reach the update server. Check your connection and try again."
)
_CERT_FAILED = (
    "The update server's security certificate could not be verified on this "
    "system, so the connection was refused."
)

# CA bundles tried in order when certifi is unavailable (source checkouts);
# the packaged app always ships certifi -- see _ssl_context().
_CA_FILE_CANDIDATES = (
    "/etc/ssl/cert.pem",  # macOS (and some BSDs)
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora/RHEL
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
)


def _ssl_context() -> ssl.SSLContext:
    """An SSL context whose trust store actually EXISTS inside this build.

    The packaged app's Python has no default CA store: its compiled-in paths
    point at the python.org framework location, which is not where Briefcase
    puts the framework inside the bundle, so
    `ssl.get_default_verify_paths()` reports cafile=None there and every
    HTTPS request died as CERTIFICATE_VERIFY_FAILED. That is what the 0.4.0
    update check hit: it reported "could not reach the update server" on a
    perfectly healthy connection (reproduced inside the shipped bundle on
    2026-10-18). The bundle therefore ships certifi (pinned in
    pyproject.toml); the system CA files are the fallback for source runs.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    for path in _CA_FILE_CANDIDATES:
        try:
            if os.path.exists(path):
                return ssl.create_default_context(cafile=path)
        except Exception:
            continue
    return ssl.create_default_context()


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
    `"sha256:<64 hex chars>"`. This is the ONLY checksum source this updater
    trusts; a separate SHA256SUMS asset is not read.

    Reading it is what makes the integrity check real. The previous
    implementation read a `_digests` key that the GitHub API never returns, so
    the check could not have fired even once. Missing or malformed digests now
    make the update non-installable (see integrity_problem), rather than
    silently bypassing verification.
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
        with urllib.request.urlopen(
            req, timeout=timeout, context=_ssl_context()
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(
                "No published releases were found yet, so there is nothing to update to."
            ) from e
        raise UpdateError(f"Update check failed (HTTP {e.code}).") from e
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise UpdateError(_CERT_FAILED) from e
        raise UpdateError(_UNREACHABLE) from e
    except ssl.SSLError as e:
        raise UpdateError(_CERT_FAILED) from e
    except (TimeoutError, OSError) as e:
        raise UpdateError(_UNREACHABLE) from e
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


def integrity_problem(asset: Asset) -> str | None:
    """Why this asset cannot be verified, or None when its digest is usable.

    Fail-closed policy: an automated update must not install a download whose
    expected digest is absent or malformed. The user is told plainly instead
    of being handed an unverified installer.
    """
    digest = (asset.sha256 or "").strip()
    if not digest:
        return (
            "This release does not publish a SHA-256 digest for the installer, "
            "so the download cannot be verified and will not be installed."
        )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        return (
            "This release's published SHA-256 digest is malformed, so the "
            "download cannot be verified and will not be installed."
        )
    return None


_ALLOWED_ASSET_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9 ._()+@-]*\.[A-Za-z0-9]{2,8}"
)

# Windows treats these stems as device names, so writing `CON.msi` targets a
# device rather than a file. The download runs on the user's platform, so the
# name is rejected everywhere for consistency.
_WINDOWS_RESERVED_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_asset_filename(name: str) -> str:
    """Validate a release asset name as a plain filename.

    Release metadata is attacker-influenced if the repository or its release
    is ever compromised, and the name is used to build a download path. Reject
    anything that is not a simple filename: absolute paths, directory
    separators, traversal segments, control characters and shell-ish names.
    """
    raw = name or ""
    if raw != raw.strip() or not raw:
        raise UpdateError("The update asset has no usable filename.")
    if "\x00" in raw or any(ch in raw for ch in ("/", "\\")):
        raise UpdateError(
            f"The update asset name {raw!r} contains a path separator; "
            "refusing to write it."
        )
    if raw in (".", "..") or raw.startswith(".") or re.match(r"^[A-Za-z]:", raw):
        raise UpdateError(
            f"The update asset name {raw!r} is not a plain filename; "
            "refusing to write it."
        )
    if not _ALLOWED_ASSET_NAME.fullmatch(raw):
        raise UpdateError(
            f"The update asset name {raw!r} is not a supported filename; "
            "refusing to write it."
        )
    if raw.split(".", 1)[0].upper() in _WINDOWS_RESERVED_STEMS:
        raise UpdateError(
            f"The update asset name {raw!r} is a reserved device name; "
            "refusing to write it."
        )
    return raw


def safe_update_destination(name: str, directory=None) -> "Path":
    """A destination inside the temporary directory for this asset name."""
    import tempfile
    from pathlib import Path

    filename = safe_asset_filename(name)
    base = Path(directory or tempfile.gettempdir()).resolve()
    dest = (base / filename).resolve()
    # Belt and braces: even a name that passed the pattern must resolve to a
    # direct child of the intended directory.
    if dest.parent != base:
        raise UpdateError(
            f"The update asset name {name!r} escapes the download directory; "
            "refusing to write it."
        )
    return dest


def download_asset(asset: Asset, dest, on_progress=None, chunk_size: int = 256 * 1024) -> None:
    """Download `asset` to `dest`, reporting (done, total) bytes as it goes.

    Chunked rather than urlretrieve so a long download can show real progress
    (the update dialog does). A download that ends before the advertised
    length is an error, not a silently-truncated file: without that check a
    dropped connection would only be caught by the checksum -- and only when
    the release actually carries one.

    Raises UpdateError (or a urllib error) on failure; the caller decides
    what to do about it.
    """
    import urllib.request

    req = urllib.request.Request(
        asset.url, headers={"User-Agent": f"LocalProjectHub/{__version__}"}
    )
    expected = 0
    done = 0
    with urllib.request.urlopen(
        req, timeout=60, context=_ssl_context()
    ) as resp, open(dest, "wb") as fh:
        try:
            expected = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            expected = 0
        expected = expected or int(asset.size or 0)
        while True:
            buf = resp.read(chunk_size)
            if not buf:
                break
            fh.write(buf)
            done += len(buf)
            if on_progress is not None:
                on_progress(done, expected)
    if expected and done != expected:
        raise UpdateError(
            f"The download ended early ({done} of {expected} bytes), so it was discarded."
        )


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
