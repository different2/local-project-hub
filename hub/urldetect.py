"""Detect a project's dashboard URL without the user typing it.

Three signals, in order of reliability:

  1. The server's OWN OUTPUT. Most servers announce themselves — Flask prints
     "Running on http://127.0.0.1:5000", this user's projects print
     "serving on http://localhost:8471" and "dashboard at ...". The hub
     already captures stdout for the log drawer; this module mines it.
  2. LISTENING PORTS opened by the child process. Works when a server starts
     silently (no banner), by asking the OS which TCP ports the process owns.
  3. A configured URL, which always wins — auto-detection only fills a gap.

Auto-detection is deliberately advisory: the detected URL is offered, and the
hub remembers it so the user is only asked once per project.
"""

from __future__ import annotations

import re

# A URL as servers tend to print it: http(s)://host[:port][/path]
_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")

# Trailing punctuation that is sentence punctuation, not part of the URL.
_URL_TRIM = ".,;:!?)\"'>]}"

# "on port 8471", "port=8787", ":8080", "listening on 8080"
_PORT_RE = re.compile(
    r"(?:port\s*(?:number)?\s*(?:is\s*)?[:=]?\s*|listening\s+on\s+|:\s*)(\d{2,5})\b",
    re.IGNORECASE,
)

# Ports that are almost never a dashboard.
_UNLIKELY_PORTS = {0, 22, 25, 53, 123, 443, 3306, 5432, 6379, 27017}


def _clean(url: str) -> str:
    return url.rstrip(_URL_TRIM)


def find_url(text: str) -> str | None:
    """The first plausible dashboard URL in a chunk of server output."""
    if not text:
        return None
    for match in _URL_RE.finditer(text):
        url = _clean(match.group(0))
        if _is_plausible(url):
            return url
    return None


def find_all_urls(text: str) -> list[str]:
    """Every plausible URL, in the order they appeared (deduplicated)."""
    seen: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = _clean(match.group(0))
        if url not in seen and _is_plausible(url):
            seen.append(url)
    return seen


def find_port(text: str) -> int | None:
    """A port number mentioned in output, when no full URL was printed."""
    if not text:
        return None
    for match in _PORT_RE.finditer(text):
        try:
            port = int(match.group(1))
        except ValueError:
            continue
        if 1024 <= port <= 65535 and port not in _UNLIKELY_PORTS:
            return port
    return None


def _is_plausible(url: str) -> bool:
    """Filter out URLs that are clearly not a local dashboard."""
    low = url.lower()
    # Localhost/private addresses are what a dev server binds.
    local_markers = (
        "127.0.0.1",
        "localhost",
        "0.0.0.0",
        "[::1]",
        "::1",
    )
    if any(m in low for m in local_markers):
        return True
    # A private LAN address is also plausible (the user's own machine).
    if re.match(r"https?://(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", low):
        return True
    # Documentation links, changelogs and package registries are noise.
    noise = (
        "github.com",
        "docs.",
        "readthedocs",
        "pypi.org",
        "npmjs.com",
        "example.com",
        "wikipedia.org",
        "stackoverflow.com",
        "python.org",
        "schemas.",
        "xmlns",
        "w3.org",
    )
    if any(n in low for n in noise):
        return False
    # Anything else with a real host is accepted but ranked last by callers.
    return True


def listening_ports(pid: int) -> list[int]:
    """TCP ports a process is listening on, per platform.

    Uses `lsof` because it ships with macOS and is available on most Linux
    boxes, avoiding a psutil dependency. Returns [] if it cannot be determined
    — callers must treat detection as best-effort, never as a guarantee.
    """
    if not pid:
        return []
    import subprocess

    cmd = ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", str(pid)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=6).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: list[int] = []
    for line in out.splitlines()[1:]:
        # NAME column looks like "localhost:8471" or "*:8787"
        name = line.split()[-1] if line.split() else ""
        if ":" not in name:
            continue
        tail = name.rsplit(":", 1)[-1]
        if tail.isdigit():
            port = int(tail)
            if port not in ports:
                ports.append(port)
    return [p for p in ports if p not in _UNLIKELY_PORTS]


def listening_ports_all() -> list[int]:
    """Every TCP port something is listening on, via lsof.

    Used to find a stray copy of a project when nothing in the registry names
    a port. Returns [] when it cannot be determined — callers must treat this
    as best-effort.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=8,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: list[int] = []
    for line in out.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        # Depending on the platform the last column is either the address
        # ("*:7000") or the state ("(LISTEN)") followed by the address, so scan
        # the tail for anything that looks like host:port.
        for token in reversed(fields[-2:]):
            if ":" not in token:
                continue
            tail = token.rsplit(":", 1)[-1]
            if tail.isdigit():
                port = int(tail)
                if port not in ports and port not in _UNLIKELY_PORTS:
                    ports.append(port)
                break
    return ports


def url_from_port(port: int, host: str = "127.0.0.1") -> str:
    return f"http://{host}:{port}/"


def url_host_port(url: str) -> tuple[str, int]:
    """Split a URL into (host, port), filling in the scheme's default port."""
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def process_command(pid: int) -> str:
    """The command line for a PID, or "" when it cannot be read.

    Used to show the user WHAT is holding a port before offering to kill it.
    """
    if not pid:
        return ""
    import subprocess

    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=6,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.splitlines()[0].strip() if out else ""


def kill_process(pid: int, timeout_s: float = 4.0) -> bool:
    """End a process, politely then firmly. True if it is gone.

    SIGTERM first so the process can clean up (close sockets, flush logs);
    SIGKILL only if it is still there after `timeout_s`. Used only after the
    user has confirmed they want the process ended.
    """
    import os
    import signal
    import subprocess
    import time

    if not pid or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        # Already gone, or not ours to signal — either way nothing to wait for.
        return True

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    time.sleep(0.3)
    return not _process_alive(pid)


def _process_alive(pid: int) -> bool:
    import subprocess

    try:
        return (
            subprocess.run(
                ["kill", "-0", str(pid)],
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def port_in_use(port: int) -> bool:
    """True when something is listening on the port.

    Deliberately does NOT set SO_REUSEADDR: with it, bind() can succeed even
    when another socket holds the port on macOS, so the check would report a
    busy port as free and the guarded start would proceed into the very
    "Address already in use" failure it is meant to prevent.
    """
    import socket

    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def port_owners(port: int) -> set[int]:
    """PIDs listening on the port, via lsof. Empty set when undeterminable."""
    if not port:
        return set()
    import subprocess

    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=6,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for line in out.split():
        if line.strip().isdigit():
            pids.add(int(line.strip()))
    return pids


if __name__ == "__main__":
    samples = [
        "serving on http://localhost:8471  (assets list at /_assets-list)",
        "observability live dashboard at http://127.0.0.1:8787  (ctrl-c to stop)",
        " * Running on http://127.0.0.1:5000",
        "See https://docs.python.org/3 for help, then listening on port 9000",
        "Server ready at http://0.0.0.0:3000/",
        "nothing useful here",
    ]
    for s in samples:
        print(f"{find_url(s) or find_port(s) or '-':<40} <- {s[:60]}")
