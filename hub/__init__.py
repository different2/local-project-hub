"""Local Project Hub — a launcher for locally hosted web projects.

__version__ prefers the installed package metadata so it cannot drift from the
version that was actually packaged (which is what the About dialog shows). A
source checkout has no installed distribution, so it falls back to reading
pyproject.toml — still never a hardcoded literal, which is what silently kept
the About box on 0.1.0 for several releases.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("hub")
except PackageNotFoundError:  # running from a source tree, not an install
    __version__ = "unknown"
    try:
        from pathlib import Path

        _pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        for _line in _pyproject.read_text(encoding="utf-8").splitlines():
            _stripped = _line.strip()
            if _stripped.startswith("version") and "=" in _stripped:
                __version__ = _stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break
    except Exception:  # pragma: no cover - unreadable tree
        pass

__all__ = ["__version__"]
