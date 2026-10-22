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

from .platform import IS_LINUX, IS_WINDOWS

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

    lsof ships with macOS and is on most Linux boxes, so it is used there; on
    Windows it does not exist at all, and netstat -ano is the equivalent. Using
    one command that only exists on half the platforms made this return [] on
    Windows for every caller — including the tests that start a real server and
    assert it shows up.

    The PID is the process QProcess launched, which may be a launcher (a
    Windows venv's `Scripts\\python.exe`, a shell wrapper); the listener is a
    descendant. The whole tree is matched, otherwise a silently-started venv
    server is never found.

    Returns [] when it cannot be determined — callers must treat detection as
    best-effort, never as a guarantee.
    """
    if not pid:
        return []
    tree = process_tree_pids({pid})
    if IS_WINDOWS:
        ports = []
        for local, owner in _netstat_listening_rows() or []:
            if owner not in tree:
                continue
            port = _netstat_local_port(local)
            if port and port not in ports and port not in _UNLIKELY_PORTS:
                ports.append(port)
        return ports

    import subprocess

    cmd = ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a"]
    for member in sorted(tree):
        cmd += ["-p", str(member)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=6).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: list[int] = []
    for line in out.splitlines()[1:]:
        # NAME is the address column (\"127.0.0.1:8471\"), but the LAST field on
        # the line is \"(LISTEN)\" — taking split()[-1] grabs that instead and
        # silently finds no ports. Take the field before it.
        parts = line.split()
        name = parts[-2] if len(parts) >= 2 else ""
        if ":" not in name:
            continue
        tail = name.rsplit(":", 1)[-1]
        if tail.isdigit():
            port = int(tail)
            if port not in ports:
                ports.append(port)
    return [p for p in ports if p not in _UNLIKELY_PORTS]


def listening_ports_all() -> list[int]:
    """Every TCP port something is listening on, per platform.

    lsof on macOS/Linux, netstat -ano on Windows, where lsof does not exist.
    Used to find a stray copy of a project when nothing in the registry names a
    port. Returns [] when it cannot be determined — callers must treat this as
    best-effort.
    """
    if IS_WINDOWS:
        ports: list[int] = []
        for local, _owner in _netstat_listening_rows() or []:
            port = _netstat_local_port(local)
            if port and port not in ports and port not in _UNLIKELY_PORTS:
                ports.append(port)
        return ports

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


def process_tree_pids(root_pids) -> set[int]:
    """The given PIDs plus every descendant that still exists.

    A Windows venv's `Scripts\\python.exe` is a launcher: QProcess reports the
    launcher's PID, but the process that actually binds the port is the base
    interpreter it spawns. Without the descendants, the hub sees its OWN server
    as a foreign holder and offers to kill it (or refuses to start). The same
    applies to shell wrappers and `npm start`.

    Returns the roots unchanged when the process table cannot be read; it never
    invents a descendant.
    """
    roots = {int(p) for p in (root_pids or []) if p}
    if not roots:
        return set()
    import subprocess

    pairs: list[tuple[int, int]] = []
    if IS_WINDOWS:
        import json

        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,ParentProcessId | "
                    "ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=8,
            ).stdout
            data = json.loads(out or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return set(roots)
        if isinstance(data, dict):
            data = [data]
        for row in data:
            try:
                pairs.append(
                    (int(row["ProcessId"]), int(row["ParentProcessId"]))
                )
            except (KeyError, TypeError, ValueError):
                continue
    else:
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid=,ppid="],
                capture_output=True,
                text=True,
                timeout=6,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return set(roots)
        for line in out.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
                pairs.append((int(fields[0]), int(fields[1])))

    children: dict[int, list[int]] = {}
    for pid, parent in pairs:
        children.setdefault(parent, []).append(pid)
    found = set(roots)
    queue = list(roots)
    while queue:
        parent = queue.pop()
        for child in children.get(parent, ()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def _windows_process_identity(pid: int, kernel32=None, last_error=None) -> str | None:
    """A stable creation-time token for the process currently at `pid`."""
    import ctypes

    if not pid:
        return None
    if kernel32 is None:
        kernel32 = _windows_kernel32()
    if last_error is None:
        last_error = ctypes.get_last_error
    handle = kernel32.OpenProcess(
        _WIN_PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid)
    )
    if not handle:
        return None
    try:
        creation = ctypes.c_uint64()
        exit_time = ctypes.c_uint64()
        kernel_time = ctypes.c_uint64()
        user_time = ctypes.c_uint64()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.pointer(creation),
            ctypes.pointer(exit_time),
            ctypes.pointer(kernel_time),
            ctypes.pointer(user_time),
        )
        if not ok:
            return None
        return f"win:{int(creation.value)}"
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _linux_process_identity(pid: int) -> str | None:
    """PID + kernel start time + boot id, from /proc."""
    from pathlib import Path

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        # Field 22 (starttime), after the parenthesised comm field.
        fields = stat.rsplit(")", 1)[1].split()
        starttime = fields[19]
    except (IndexError, ValueError):
        return None
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        boot = ""
    return f"linux:{boot}:{starttime}"


def _ps_process_identity(pid: int) -> str | None:
    """PID + stable start timestamp via ps (macOS and other POSIX)."""
    import os
    import subprocess

    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=6,
            env={**os.environ, "LC_ALL": "C"},
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.splitlines()[0].strip() if out else ""
    return f"ps:{line}" if line else None


def process_identity(pid: int) -> str | None:
    """A stable identity for the process currently at `pid`, or None.

    A PID alone is not an identity: the OS can reuse it. This returns a token
    that changes when the PID is reused, using the strongest portable source
    available: Win32 process creation time, Linux `/proc` starttime + boot id,
    or macOS/`ps` start time. Callers must still tolerate None (process gone or
    table unreadable) and must not claim ownership without evidence.
    """
    if not pid:
        return None
    if IS_WINDOWS:
        return _windows_process_identity(pid)
    if IS_LINUX:
        return _linux_process_identity(pid)
    return _ps_process_identity(pid)


def process_alive(pid: int) -> bool:
    """Public liveness check; False only when the OS proves the PID is gone."""
    return _process_alive(pid)


def process_command(pid: int) -> str:
    """The command line for a PID, or "" when it cannot be read.

    Used to show the user WHAT is holding a port before offering to kill it --
    an empty string here makes the dialog useless ("end this process?" with no
    indication of what it is), and it also fails the conflict tests that assert
    the holder's script is named.

    ps is Unix-only. On it, `ps -o command= -p PID` gives the full command line.
    On Windows the equivalent is PowerShell's Win32_Process CIM class, which is
    always present on a Windows runner where ps is not.
    """
    if not pid:
        return ""
    import subprocess

    if IS_WINDOWS:
        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter 'ProcessId=%d' "
                    "| Select-Object -ExpandProperty CommandLine" % pid,
                ],
                capture_output=True,
                text=True,
                timeout=8,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.splitlines()[0].strip() if out else ""

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


def _is_already_gone_error(error: OSError) -> bool:
    """True only when the OS says this PID no longer exists."""
    if isinstance(error, ProcessLookupError):
        return True
    # Windows ERROR_INVALID_PARAMETER from OpenProcess/TerminateProcess.
    return getattr(error, "winerror", None) == 87


def kill_process(pid: int, timeout_s: float = 4.0) -> bool:
    """End a process, politely then firmly. True only if it is gone.

    SIGTERM first so the process can clean up (close sockets, flush logs);
    SIGKILL only if it is still there after `timeout_s`. Used only after the
    user has confirmed they want the process ended.

    A signal we are not allowed to send (PermissionError) is NOT success: the
    old code returned True for every OSError, so an inaccessible process was
    reported as ended. Only "no such process" counts as already gone.
    """
    import os
    import signal
    import time

    if not pid or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        return _is_already_gone_error(e)

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError as e:
        return _is_already_gone_error(e)
    time.sleep(0.3)
    return not _process_alive(pid)


_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_STILL_ACTIVE = 259
_WIN_ERROR_ACCESS_DENIED = 5
_WIN_ERROR_INVALID_PARAMETER = 87


def _windows_kernel32():
    """The kernel32 entry points used for a liveness check (Windows only)."""
    import ctypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    k.GetExitCodeProcess.restype = ctypes.c_int
    k.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    k.GetProcessTimes.restype = ctypes.c_int
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CloseHandle.restype = ctypes.c_int
    return k


def _windows_process_alive(pid: int, kernel32=None, last_error=None) -> bool:
    """True when the process exists (or its status cannot be determined).

    `kill -0` does not exist on Windows: `kill.exe` is not a normal Windows
    tool, so the previous check either failed to run or found an unrelated
    executable and interpreted its exit code as a liveness answer. This uses
    the documented Win32 API instead.

    Returns False ONLY when Windows says the PID does not exist. Access denied
    and any unexpected failure are reported as "alive" (undetermined), because
    claiming a process is gone when it is not would let kill_process() report a
    successful kill it never performed.
    """
    import ctypes

    if not pid:
        return False
    if kernel32 is None:
        kernel32 = _windows_kernel32()
    if last_error is None:
        last_error = ctypes.get_last_error
    handle = kernel32.OpenProcess(
        _WIN_PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid)
    )
    if not handle:
        err = int(last_error() or 0)
        if err == _WIN_ERROR_INVALID_PARAMETER:
            return False  # no such PID
        if err == _WIN_ERROR_ACCESS_DENIED:
            return True  # exists, but not ours to inspect
        return True  # undetermined: do not claim it is gone
    try:
        code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.pointer(code)):
            return True  # undetermined
        return int(code.value) == _WIN_STILL_ACTIVE
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _posix_process_alive(pid: int) -> bool:
    """True when the process exists (or its status cannot be determined).

    `PermissionError` means the process exists but belongs to another user;
    only `ProcessLookupError` proves it is gone.
    """
    import os

    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True  # undetermined
    return True


def _process_alive(pid: int) -> bool:
    """Cross-platform liveness: False only when the OS proves the PID is gone."""
    if not pid:
        return False
    if IS_WINDOWS:
        return _windows_process_alive(pid)
    return _posix_process_alive(pid)


def _is_addr_in_use(error: OSError) -> bool:
    import errno

    if error.errno in (errno.EADDRINUSE, errno.EACCES):
        return True
    # Windows surfaces Winsock codes, sometimes without mapping them to errno.
    return getattr(error, "winerror", None) in (10048, 10013)


def _is_unsupported_address(error: OSError) -> bool:
    """True when the family/address simply does not exist on this machine."""
    import errno

    unsupported = {errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT}
    eproto = getattr(errno, "EPROTONOSUPPORT", None)
    if eproto is not None:
        unsupported.add(eproto)
    if error.errno in unsupported:
        return True
    return getattr(error, "winerror", None) in (10049, 10047)


def _bind_state(family: int, host: str, port: int) -> str:
    """'free', 'in_use', or 'unsupported' for one address family."""
    import socket

    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        return "unsupported"
    try:
        sock.settimeout(0.3)
        try:
            # Deliberately NOT SO_REUSEADDR: with it, bind() can succeed even
            # when another socket holds the port on macOS, so a busy port
            # would be reported free.
            sock.bind((host, port))
        except OSError as e:
            if _is_addr_in_use(e):
                return "in_use"
            if _is_unsupported_address(e):
                return "unsupported"
            # Could not bind for any other reason: treat it as busy rather than
            # promising the port is free.
            return "in_use"
        return "free"
    finally:
        sock.close()


def port_in_use(port: int) -> bool:
    """True when something is listening on the port, IPv4 OR IPv6.

    Checking only 127.0.0.1 missed a listener bound solely to ::1 (a common
    `--host ::1` or `localhost`-first setup), so the hub would start a second
    server straight into "Address already in use". Both loopback addresses are
    probed; an address family the OS does not support is skipped rather than
    counted as busy.

    A dual-stack listener is still ONE service: this returns a boolean, so it
    cannot double-count the IPv4 and IPv6 views of the same socket.
    """
    if not port:
        return False
    if IS_WINDOWS:
        # Windows permits a second bind of a specific address even while a
        # wildcard or dual-stack listener already owns the endpoint, so bind()
        # answers "free" for a port that is genuinely in use. The kernel's
        # LISTENING table is authoritative and covers IPv4, IPv6 and
        # dual-stack listeners.
        rows = _netstat_listening_rows()
        if rows is None:
            # The table could not be read. Do not claim the port is free:
            # callers treat "busy" as "do not start yet" and retry/report.
            return True
        return any(_netstat_local_port(local) == port for local, _owner in rows)
    import socket

    if _bind_state(socket.AF_INET, "127.0.0.1", port) == "in_use":
        return True
    if _bind_state(socket.AF_INET6, "::1", port) == "in_use":
        return True
    return False


def port_owners(port: int) -> set[int]:
    """PIDs listening on the port. Empty set when undeterminable.

    lsof is a Unix tool and is not present on Windows runners, where the port
    check would then always fall through to "cannot tell who holds it" and every
    conflict would look like no conflict at all. netstat is the equivalent on
    Windows, so each platform gets its own path rather than one command that
    silently reports nothing.
    """
    if not port:
        return set()
    import subprocess

    if IS_WINDOWS:
        return _port_owners_netstat(port)

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


def _netstat_listening_rows() -> list[tuple[str, int]] | None:
    """(local_address, owning_pid) for every LISTENING TCP row, via netstat.

    netstat -ano is present on every Windows machine and is the equivalent of
    lsof, which is not. Without it the listening-port helpers all return [] on
    Windows, and every caller then concludes nothing is listening -- which turns
    a detected port conflict into a silent one.

    Returns None (not []) when the table could not be read, so callers can tell
    "nothing is listening" apart from "cannot determine".

    One parse serves all three callers (find the holder, the ports for one PID,
    every listening port), because running netstat per call would repeat the same
    table scan several times per start.

    Local addresses look like `0.0.0.0:8787` or `[::]:8787`; the port is after
    the final colon so both forms parse. Only LISTENING rows are wanted: TCP also
    shows outbound connections whose ephemeral local port can coincide with a
    server's.
    """
    import subprocess

    try:
        # No `-p TCP`: that filter shows IPv4 TCP only, so an IPv6-ONLY
        # listener (`--host ::1`) was invisible and the port looked free. UDP
        # rows are filtered out below instead.
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=8,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows: list[tuple[str, int]] = []
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != "TCP":
            continue
        local = parts[1]
        if ":" not in local:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        rows.append((local, pid))
    return rows


def _netstat_local_port(local: str) -> int | None:
    """The port in a netstat local address, handling `[::]:8787` and `0.0.0.0:8787`."""
    if ":" not in local:
        return None
    tail = local.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _port_owners_netstat(port: int) -> set[int]:
    """PIDs listening on the port, via `netstat -ano` (Windows).

    netstat prints one row per local endpoint, with the owning PID last:

        TCP    0.0.0.0:8787    0.0.0.0:0    LISTENING    12345

    The local column is `host:port`, and can be IPv6 (`[::]:8787`), so the port
    is matched after the final colon. Only LISTENING rows count: a port is also
    used for outbound connections, whose ephemeral local port can coincide.
    """
    return {
        pid
        for local, pid in (_netstat_listening_rows() or [])
        if _netstat_local_port(local) == port
    }


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
