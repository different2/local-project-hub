"""Resolve a standalone HTML entry page without changing project files.

A server banner supplies an origin, not necessarily the application's page.
Only Python's known static-file server and an unambiguous local root URL are
eligible; explicit routes, remote URLs and uncertain commands remain untouched.
"""
from __future__ import annotations

import ntpath
from pathlib import Path
import re
from urllib.parse import quote, urlsplit, urlunsplit

from .platform import prepend_interpreter, split_command


def _served_directory(record: dict, expected_host: str, expected_port: int) -> Path | None:
    cwd = str(record.get("working_dir") or "")
    if not cwd:
        return None
    try:
        tokens = split_command(str(record.get("command") or ""))
        tokens += split_command(str(record.get("args") or ""))
        tokens = prepend_interpreter(tokens, str(record.get("interpreter") or ""))
        if not tokens or not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", ntpath.basename(tokens[0]), re.I):
            return None
        module = tokens.index("-m")
        if tokens[module + 1] != "http.server":
            return None
        if any(t not in {"-u", "-B", "-I", "-E", "-s", "-S", "-P", "-O", "-OO", "-q"} for t in tokens[1:module]):
            return None
        directory = Path(cwd)
        port = 8000  # http.server's own default, not a guessed project port.
        bind = None
        tail = iter(tokens[module + 2:])
        for token in tail:
            if token in ("--directory", "-d"):
                directory = Path(cwd) / next(tail)
            elif token.startswith("--directory="):
                directory = Path(cwd) / token.partition("=")[2]
            elif token in ("--bind", "-b"):
                bind = next(tail).lower()
            elif token.startswith("--bind="):
                bind = token.partition("=")[2].lower()
            elif token in ("--protocol", "-p"):
                next(tail)
            elif token.startswith("--protocol="):
                continue
            elif token.isdecimal():
                port = int(token)
            else:
                return None  # CGI/TLS/unknown switches are not this static recipe.
        if port != expected_port:
            return None
        if bind not in (None, "::", "0.0.0.0", expected_host):
            return None  # Do not assume two different bind names are equivalent.
        if bind == "0.0.0.0" and ":" in expected_host:
            return None  # An IPv4-only listener cannot serve an IPv6 URL.
        return directory.resolve() if directory.is_dir() else None
    except (OSError, ValueError, IndexError, StopIteration, RuntimeError):
        return None


def static_site_origin(record: dict) -> str:
    """Canonical browser origin for a known local Python static server, or empty.

    Unlike entry selection this also allows explicit page routes: their URL is
    preserved, while HTML compatibility remains confined to the known origin.
    """
    try:
        url = urlsplit(str(record.get("url") or ""))
        host = url.hostname
        if (url.scheme != "http" or host not in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"}
                or url.username is not None or url.password is not None
                or _served_directory(record, host, url.port or 80) is None):
            return ""
        authority = f"[{host}]" if ":" in host else host
        if url.port is not None and url.port != 80:
            authority += f":{url.port}"
        return "http://" + authority
    except (OSError, ValueError, RuntimeError):
        return ""


def dashboard_url(record: dict) -> str:
    """Effective navigation URL; the saved record and all project files stay intact.

    For older registrations without a picked filename, infer only a sole visible
    top-level HTML file when the server has no conventional index page.
    """
    original = str(record.get("url") or "")
    try:
        url = urlsplit(original)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"}
                or url.path not in ("", "/") or url.query or url.fragment
                or url.username is not None or url.password is not None):
            return original
        root = _served_directory(record, url.hostname, url.port or 80)
        if root is None:
            return original
        chosen = str(record.get("entry_file") or "")
        if chosen:
            # File… stores its path relative to the project's working directory,
            # which may differ from http.server's explicit --directory root.
            page = (Path(str(record["working_dir"])) / chosen).resolve()
        else:
            if any((root / name).is_file() for name in ("index.html", "index.htm")):
                return original
            pages = []
            for count, page in enumerate(root.iterdir()):
                if count >= 512:
                    return original  # Do not guess from a partial large directory.
                if not page.name.startswith(".") and page.suffix.lower() in (".html", ".htm") and page.is_file():
                    pages.append(page.resolve())
                    if len(pages) > 1:
                        return original
            if not pages:
                return original
            page = pages[0]
        relative = page.relative_to(root)
        if not page.is_file() or page.suffix.lower() not in (".html", ".htm"):
            return original
        return urlunsplit((url.scheme, url.netloc, "/" + quote(relative.as_posix(), safe="/"), "", ""))
    except (OSError, ValueError, RuntimeError):
        return original
