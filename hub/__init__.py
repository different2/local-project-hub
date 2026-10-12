"""Local Project Hub — a launcher for locally hosted web projects.

__version__ is read from the installed package metadata so it cannot drift
from the version in pyproject.toml. The fallback keeps a source checkout (no
installed distribution) working; it is only ever a floor, never the value
shipped in a build.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("hub")
except PackageNotFoundError:  # running from a source tree, not an install
    __version__ = "0.1.5"

__all__ = ["__version__"]
