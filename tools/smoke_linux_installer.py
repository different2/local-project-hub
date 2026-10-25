#!/usr/bin/env python3
"""External acceptance of the *installed* Ubuntu 24.04 amd64 .deb.

Run serially as a non-root user inside Xvfb + DBus + an EWMH window manager
(e.g. openbox; Xvfb screen at least 1280x900x24), after apt installing the exact artifact. CI-only dependencies:
websocket-client==1.8.0, Pillow==11.3.0, wmctrl, x11-utils. No Qt import or test
hook is needed in the app. This script never installs or changes system policy.

    python tools/smoke_linux_installer.py --output /path/to/evidence \
        --expected-version 0.7.1

A second invocation with --expected-text deliberately-wrong must exit nonzero.
Source hub/ and main.py are temporarily renamed only during the installed run,
then restored in finally; do not run other source tests/builds concurrently.
All state and the child project live in a disposable directory outside checkout.
"""
from __future__ import annotations

import argparse
import ast
import base64
import ctypes
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from importlib.metadata import Distribution
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


def wait_for(probe, poll, label: str, timeout: float, *,
             clock=time.monotonic, sleep=time.sleep):
    """None means not ready. Even a clean early app exit is a failed smoke."""
    end = clock() + timeout
    while clock() < end:
        code = poll()
        if code is not None:
            raise SmokeError(f"installed app exited before {label}: code={code}")
        result = probe()
        if result is not None:
            code = poll()
            if code is not None:
                raise SmokeError(f"installed app exited during {label}: code={code}")
            return result
        sleep(min(0.1, max(0, end - clock())))
    raise SmokeError(f"{label} timed out after {timeout}s")


class SmokeError(RuntimeError):
    """An acceptance requirement failed (never a successful observation)."""


BYPASS_FLAGS = {
    "--no-sandbox", "--disable-sandbox", "--disable-setuid-sandbox",
    "--disable-seccomp-filter-sandbox", "--disable-namespace-sandbox",
    "--single-process", "--in-process-gpu", "--no-zygote",
}


def validate_launch(env: dict, uid: int, euid: int, argv: list[str]) -> None:
    """Fail before Popen, including a sandbox-disable variable set to '0'."""
    if uid == 0 or euid == 0:
        raise SmokeError("refusing root: run the installed smoke as a normal user")
    if "QTWEBENGINE_DISABLE_SANDBOX" in env:
        raise SmokeError("sandbox bypass QTWEBENGINE_DISABLE_SANDBOX must be absent")
    flags = list(argv)
    for key in ("QTWEBENGINE_CHROMIUM_FLAGS", "CHROMIUM_FLAGS", "CHROME_FLAGS"):
        try:
            flags.extend(shlex.split(env.get(key, "")))
        except ValueError as exc:
            raise SmokeError(f"malformed sandbox-related flags: {key}") from exc
    for flag in flags:
        if flag.split("=", 1)[0] in BYPASS_FLAGS:
            raise SmokeError(f"sandbox/process bypass is forbidden: {flag}")


def validate_dom(dom: dict, *, title: str, text: str, url: str) -> None:
    """CDP must observe the nonce page, not an error/start/hidden page."""
    for key, expected in (("title", title), ("text", text), ("url", url),
                          ("visibility", "visible"), ("ready", "complete")):
        if dom.get(key) != expected:
            raise SmokeError(f"DOM {key}: expected {expected!r}, got {dom.get(key)!r}")
    if dom.get("width", 0) <= 0 or dom.get("height", 0) <= 0:
        raise SmokeError("DOM viewport has no exposed area")


def parse_status(text: str) -> dict:
    fields = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
    out: dict = {"name": fields.get("Name", "").strip(), "state": fields.get("State", "").strip()}
    for source, dest in (("Uid", "uids"), ("NSpid", "nspid")):
        out[dest] = [int(x) for x in fields.get(source, "").split()]
    for source, dest in (("NoNewPrivs", "no_new_privs"), ("Seccomp", "seccomp"),
                         ("Seccomp_filters", "seccomp_filters")):
        out[dest] = int(fields[source]) if source in fields else None
    return out


def validate_renderers(processes: list[dict], helper: str) -> list[dict]:
    renderers = []
    for row in processes:
        validate_launch(row.get("environment", {}), 1, 1, row.get("argv", []))
        if row.get("exe") != helper or "--type=renderer" not in row.get("argv", []):
            continue
        status = row["status"]
        if (len(status["uids"]) != 4 or 0 in status["uids"]
                or status["no_new_privs"] != 1 or status["seccomp"] != 2):
            raise SmokeError(f"renderer {row['pid']} lacks non-root NoNewPrivs=1 + Seccomp=2: {status}")
        renderers.append(row)
    if not renderers:
        raise SmokeError("no actual installed QtWebEngine renderer descendant was observed")
    return renderers


def parse_stat(text: str) -> dict:
    prefix, _, suffix = text.rpartition(") ")
    values = suffix.split()
    return {"pid": int(prefix.split(" (", 1)[0]), "ppid": int(values[1]),
            "start_time": values[19], "state": values[0]}


def verified_identities(rows: dict, owned: dict[int, str]) -> dict[int, str]:
    return {pid: token for pid, token in owned.items()
            if pid in rows and rows[pid]["start_time"] == token}


def descendant_identities(rows: dict, roots: dict[int, str]) -> dict[int, str]:
    owned = verified_identities(rows, roots)
    while True:
        children = {pid: row["start_time"] for pid, row in rows.items()
                    if row["ppid"] in owned and pid not in owned}
        if not children:
            return owned
        owned.update(children)


def app_environment(original: dict, work: Path, debug_port: int) -> dict:
    env = {key: value for key, value in original.items()
           if not key.startswith(("PYTHON", "QT_", "QML", "QTWEBENGINE", "LD_"))
           and key not in ("VIRTUAL_ENV", "CONDA_PREFIX", "CHROMIUM_FLAGS", "CHROME_FLAGS")}
    env.update(HOME=str(work / "home"), LOCAL_PROJECT_HUB_HOME=str(work / "state"),
               XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"),
               XDG_DATA_HOME=str(work / "data"), XDG_RUNTIME_DIR=str(work / "runtime"),
               PATH="/usr/bin:/bin", QT_QPA_PLATFORM="xcb",
               QTWEBENGINE_REMOTE_DEBUGGING=f"127.0.0.1:{debug_port}")
    return env


# This is a real disposable user project, not code injected into the application.
FIXTURE_SOURCE = '''from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import html, json, os, sys, time
config = json.loads(Path(sys.argv[1]).read_text())
page = ('<!doctype html><meta charset="utf-8"><title>' + html.escape(config["title"])
        + '</title><style>body{margin:0;background:#123646;color:#f8f0d0;display:grid;'
        'place-items:center;height:100vh;font:32px sans-serif}</style><body>'
        + html.escape(config["text"]) + '</body>').encode()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/" + config["nonce"] else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
    def log_message(self, *args):
        pass
with HTTPServer(("127.0.0.1", 0), Handler) as server:
    server.timeout = 0.5
    url = "http://127.0.0.1:" + str(server.server_address[1]) + "/" + config["nonce"]
    meta = Path(config["metadata"])
    tmp = meta.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "url": url}))
    tmp.replace(meta)
    print(url, flush=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        server.handle_request()
'''


def seed_fixture(root: Path, work: Path, python: str, nonce: str) -> dict:
    sys.path.insert(0, str(root))
    try:
        from hub.store import Store, validate
    finally:
        sys.path.pop(0)
    project = work / "project"
    project.mkdir()
    state = work / "state"
    state.mkdir()
    script = project / "dashboard.py"
    script.write_text(FIXTURE_SOURCE, encoding="utf-8")
    config = dict(nonce=nonce, title=f"LPH installed smoke {nonce}",
                  text=f"Installed dashboard {nonce}",
                  metadata=str(project / "listening.json"), script=str(script))
    config_path = project / "fixture.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    store = Store(state / "registry.json")
    rec = store.add(validate(dict(name="Installed smoke fixture", working_dir=str(project),
                                  command=shlex.join([python, "-I", "-u", str(script), str(config_path)]),
                                  interpreter="", env={}, url="", autostart=True,
                                  detected={"type": "web", "evidence": ["synthetic stdlib HTTP fixture"]},
                                  type_override="")))
    (state / "ui.json").write_text(json.dumps({"last_project": rec["id"]}), encoding="utf-8")
    if Store(state / "registry.json").get(rec["id"]) != rec:
        raise SmokeError("Store seed failed its persistence readback")
    return dict(config, record=rec)


@contextmanager
def hidden_source(root: Path, *, report: dict | None = None):
    moved = []
    try:
        for name in ("hub", "main.py"):
            source = root / name
            target = root / (".smoke-hidden-" + uuid.uuid4().hex + "-" + name)
            if not source.exists() or target.exists():
                raise SmokeError(f"cannot safely hide source: {source}")
            source.rename(target)
            moved.append((source, target))
        yield [{"source": str(src), "hidden": str(dst)} for src, dst in moved]
    finally:
        for source, target in reversed(moved):
            if source.exists():
                raise SmokeError(f"refusing to overwrite source during restoration: {source}")
            target.rename(source)
        if report is not None:
            report["source_restored"] = all(source.exists() and not target.exists() for source, target in moved)


def process_table(proc: Path = Path("/proc")) -> dict:
    rows = {}
    for entry in proc.iterdir():
        if entry.name.isdecimal():
            try:
                row = parse_stat((entry / "stat").read_text())
                rows[row["pid"]] = row
            except (OSError, ValueError, IndexError):
                continue  # Processes may exit during enumeration.
    return rows


def process_identity(pid: int, proc: Path = Path("/proc")) -> str | None:
    try:
        return parse_stat((proc / str(pid) / "stat").read_text())["start_time"]
    except (OSError, ValueError, IndexError):
        return None


def process_evidence(pid: int, token: str, proc: Path = Path("/proc")) -> dict:
    base = proc / str(pid)
    if process_identity(pid, proc) != token:
        raise SmokeError(f"process {pid} identity changed before evidence capture")
    row = parse_stat((base / "stat").read_text())
    row["status"] = parse_status((base / "status").read_text())
    row["argv"] = (base / "cmdline").read_bytes().decode("utf-8", "replace").strip("\0").split("\0")
    for name in ("exe", "cwd"):
        try:
            row[name] = os.readlink(base / name)
        except OSError as exc:
            row[name] = f"unreadable: {exc}"
    row["environment"] = {}
    try:
        for entry in (base / "environ").read_bytes().decode("utf-8", "replace").split("\0"):
            key, _, value = entry.partition("=")
            if key.startswith(("QTWEBENGINE", "PYTHON", "LD_")) or key in (
                    "LOCAL_PROJECT_HUB_HOME", "CHROMIUM_FLAGS", "CHROME_FLAGS", "QT_QPA_PLATFORM"):
                row["environment"][key] = value
    except OSError as exc:
        row["environment_error"] = str(exc)
    row["namespaces"] = {}
    for name in ("user", "pid", "mnt", "net", "ipc", "uts", "cgroup"):
        try:
            row["namespaces"][name] = os.readlink(base / "ns" / name)
        except OSError as exc:
            row["namespaces"][name] = f"unreadable: {exc}"
    if process_identity(pid, proc) != token:
        raise SmokeError(f"process {pid} identity changed during evidence capture")
    return row


def signal_owned(pid: int, token: str, sig: int, *, identity=process_identity,
                 open_fd=None, send_fd=None, close_fd=os.close) -> bool:
    """Never kill by a remembered numeric PID; a pidfd pins the verified task."""
    if pid <= 1 or pid == os.getpid() or identity(pid) != token:
        return False
    open_fd = open_fd or getattr(os, "pidfd_open")
    send_fd = send_fd or getattr(signal, "pidfd_send_signal")
    try:
        fd = open_fd(pid, 0)
    except ProcessLookupError:
        return False
    try:
        if identity(pid) != token:
            return False
        try:
            send_fd(fd, sig)
            return True
        except ProcessLookupError:
            return False
    finally:
        close_fd(fd)


def command(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    if result.returncode:
        raise SmokeError(f"{argv!r} failed ({result.returncode}): {result.stderr}")
    return result.stdout


def literal_version(path: Path) -> str:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
            return str(ast.literal_eval(node.value))
    raise SmokeError(f"missing literal installed version: {path}")


def installed_inventory(expected_version: str, *, prefix=Path("/"), run=command) -> dict:
    raw = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\t${Status}\n", "hub"])
    parts = raw.strip().split("\t")
    if (len(parts) != 4 or parts[0] != "hub" or parts[1].split("-", 1)[0] != expected_version
            or parts[2:] != ["amd64", "install ok installed"]):
        raise SmokeError(f"unexpected installed package/version/architecture/status: {raw!r}")
    launcher = prefix / "usr/bin/hub"
    app = prefix / "usr/lib/hub/app"
    qt = prefix / "usr/lib/hub/app_packages/PySide6/Qt"
    helper = qt / "libexec/QtWebEngineProcess"
    for path in (launcher, helper):
        with path.open("rb") as handle:
            if handle.read(4) != b"\x7fELF":
                raise SmokeError(f"installed launcher/helper is not native ELF: {path}")
    for path in (app / "main.py", app / "hub/__main__.py"):
        if not path.is_file():
            raise SmokeError(f"missing installed app source: {path}")
    resources = sorted(p.name for p in (qt / "resources").glob("*.pak"))
    locales = sorted(p.name for p in (qt / "translations/qtwebengine_locales").glob("*.pak"))
    if "qtwebengine_resources.pak" not in resources or "en-US.pak" not in locales:
        raise SmokeError("missing installed QtWebEngine resources/locales")
    # The actual application derives __version__ from installed metadata;
    # parsing a made-up literal in hub/__init__.py would reject every real build.
    metadata = list(app.glob("hub-*.dist-info"))
    if len(metadata) != 1:
        raise SmokeError(f"missing/ambiguous installed hub metadata: {metadata}")
    distribution = Distribution.at(metadata[0])
    if distribution.metadata.get("Name") != "hub":
        raise SmokeError("installed distribution identity is not hub")
    app_version = distribution.version
    qt_version = literal_version(qt.parent / "__init__.py")
    if app_version != expected_version or qt_version != "6.7.3":
        raise SmokeError(f"installed source/Qt versions differ: app={app_version}, Qt={qt_version}")
    linkage = run(["ldd", str(launcher)])
    if "not found" in linkage or not re.search(r"libpython3\.12\.so[.\d]*\s+=>\s+/(?:usr/)?lib/", linkage):
        raise SmokeError(f"native launcher must link system Python 3.12: {linkage}")
    return dict(package="hub", package_version=parts[1], architecture=parts[2],
                app_version=app_version, qt_version=qt_version, launcher=str(launcher),
                launcher_realpath=str(launcher.resolve()), helper=str(helper.resolve()),
                resources=resources, locales=locales, ldd=linkage)


def x_geometry(raw: str) -> dict:
    names = {"x": "Absolute upper-left X", "y": "Absolute upper-left Y",
             "width": "Width", "height": "Height"}
    out = {}
    for key, name in names.items():
        match = re.search(r"^\s*" + name + r":\s*(-?\d+)", raw, re.M)
        if not match:
            raise SmokeError(f"incomplete X11 geometry: {raw}")
        out[key] = int(match.group(1))
    out["viewable"] = bool(re.search(r"Map State:\s*IsViewable", raw))
    return out


def native_window(pid: int, *, run=command) -> dict | None:
    listing = run(["wmctrl", "-lpG"])
    matches = []
    for line in listing.splitlines():
        fields = line.split(None, 8)
        if len(fields) == 9 and fields[2] == str(pid) and fields[8] == "Local Project Hub":
            matches.append(fields[0])
    if len(matches) != 1:
        return None
    window_id = matches[0]
    run(["wmctrl", "-ia", window_id])
    raw = run(["xwininfo", "-id", window_id, "-stats"])
    root_raw = run(["xwininfo", "-root", "-stats"])
    properties = run(["xprop", "-id", window_id, "_NET_WM_PID", "_NET_WM_STATE", "_NET_FRAME_EXTENTS", "WM_CLASS"])
    active = run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    current = re.search(r"0x[0-9a-fA-F]+", active)
    owner = re.search(r"_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)", properties)
    geometry, root = x_geometry(raw), x_geometry(root_raw)
    if (not geometry["viewable"] or "_NET_WM_STATE_HIDDEN" in properties
            or not current or int(current.group(0), 16) != int(window_id, 16)
            or not owner or int(owner.group(1)) != pid):
        return None
    extents = re.search(r"_NET_FRAME_EXTENTS\(CARDINAL\)\s*=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", properties)
    if not extents:
        return None  # A real window manager must expose the whole native frame.
    left, right, top, bottom = map(int, extents.groups())
    x, y, width, height = (geometry[k] for k in ("x", "y", "width", "height"))
    frame = [x - left, y - top, x + width + right, y + height + bottom]
    if (width < 300 or height < 200 or frame[0] < 0 or frame[1] < 0
            or frame[2] > root["width"] or frame[3] > root["height"]):
        return None
    return dict(id=window_id, pid=pid, geometry=geometry, frame=frame,
                xwininfo=raw, root_xwininfo=root_raw, properties=properties,
                active=active, wmctrl=listing)


def validate_native_pixels(pixels) -> int:
    count = sum(pixel == (18, 54, 70) for pixel in pixels)  # Fixture's #123646 background.
    if count < 20_000:
        raise SmokeError(f"native screenshot lacks painted fixture area: {count} matching pixels")
    return count


def target_endpoint(targets: list[dict], url: str, port: int) -> str | None:
    matches = [t for t in targets if t.get("type") == "page" and t.get("url") == url]
    if not matches:
        return None
    if len(matches) != 1:
        raise SmokeError("ambiguous own fixture CDP target")
    endpoint = matches[0]["webSocketDebuggerUrl"]
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port != port
            or parsed.username or parsed.password or not parsed.path.startswith("/devtools/page/")):
        raise SmokeError(f"refusing non-owned/non-loopback CDP endpoint: {endpoint}")
    return endpoint


def cdp_call(wire, method: str, params: dict) -> dict:
    wire.send(json.dumps({"id": 1, "method": method, "params": params}))
    end = time.monotonic() + 3
    while time.monotonic() < end:
        wire.settimeout(max(0.01, end - time.monotonic()))
        raw = wire.recv()
        if len(raw) > 16_000_000:
            raise SmokeError("oversize CDP response")
        response = json.loads(raw)
        if response.get("id") == 1:
            if "error" in response:
                raise SmokeError(f"CDP {method}: {response['error']}")
            return response["result"]
    raise SmokeError(f"CDP {method} timed out")


DOM_EXPRESSION = """({title:document.title, text:document.body?.innerText,
url:location.href, visibility:document.visibilityState, ready:document.readyState,
width:innerWidth, height:innerHeight})"""


def page_evidence(port: int, url: str, *, screenshot: Path | None = None) -> dict | None:
    import websocket  # CI-only; pure tests never require Qt or this dependency.
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=2) as handle:
            raw = handle.read(1_000_001)
        if len(raw) > 1_000_000:
            raise SmokeError("oversize CDP discovery response")
        targets = json.loads(raw)
        if not isinstance(targets, list) or len(targets) > 16:
            raise SmokeError("unexpected CDP target list")
        endpoint = target_endpoint(targets, url, port)
        if endpoint is None:
            return None
        wire = websocket.create_connection(endpoint, timeout=3, suppress_origin=True,
                                           http_proxy_host=None, http_no_proxy=["127.0.0.1"])
        try:
            response = cdp_call(wire, "Runtime.evaluate", {"expression": DOM_EXPRESSION, "returnByValue": True})
            if "exceptionDetails" in response:
                raise SmokeError(f"DOM evaluation failed: {response}")
            dom = response.get("result", {}).get("value")
            if not isinstance(dom, dict) or dom.get("ready") != "complete":
                return None
            if screenshot:
                image = cdp_call(wire, "Page.captureScreenshot", {"format": "png"})
                screenshot.write_bytes(base64.b64decode(image["data"], validate=True))
            return dict(endpoint=endpoint, targets=targets, dom=dom)
        finally:
            wire.close()
    except (OSError, websocket.WebSocketException):
        if screenshot:
            raise  # A final evidence failure cannot become a successful probe.
        return None


def refresh_owned(owned: dict[int, str], home: str) -> dict[int, str]:
    rows = process_table()
    owned.update(descendant_identities(rows, owned))
    # As a subreaper, this observer adopts orphaned grandchildren if the native
    # launcher crashes before the first poll. Adopt only this invocation's
    # random state directory + own UID, not arbitrary other child processes.
    for pid, row in rows.items():
        if row["ppid"] == os.getpid() and pid not in owned:
            try:
                evidence = process_evidence(pid, row["start_time"])
                if (evidence["environment"].get("LOCAL_PROJECT_HUB_HOME") == home
                        and evidence["status"]["uids"] == [os.getuid()] * 4):
                    owned[pid] = row["start_time"]
            except (OSError, SmokeError):
                continue
    owned.update(descendant_identities(rows, owned))
    return verified_identities(rows, owned)


def cleanup_owned(app, owned: dict[int, str], home: str, window: dict | None = None) -> dict:
    actions = []
    if window and app.poll() is None and process_identity(app.pid) == owned.get(app.pid):
        try:
            current = native_window(app.pid)
            if current and current["id"] == window["id"]:
                command(["wmctrl", "-ic", current["id"]])  # WM_DELETE_WINDOW, not a macOS menu action.
                actions.append("WM_DELETE_WINDOW")
        except (OSError, SmokeError, subprocess.SubprocessError):
            pass  # Bounded verified termination below is still required.
    for sig, grace in ((None, 1.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
        end = time.monotonic() + grace
        while True:
            live = refresh_owned(owned, home)
            if sig is not None:
                for pid, token in live.items():
                    if signal_owned(pid, token, sig):
                        actions.append({"pid": pid, "start_time": token, "signal": int(sig)})
            # waitpid is restricted to identities already proven ours. Never -1
            # and never an arbitrary PID supplied by a fixture/CLI argument.
            for pid, token in owned.items():
                if pid != app.pid and process_identity(pid) == token:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
            app.poll()  # Reaps the direct Popen child.
            if not live or time.monotonic() >= end:
                break
            time.sleep(0.1)
        if not refresh_owned(owned, home):
            break
    remaining = refresh_owned(owned, home)
    try:
        app.wait(timeout=1)
    except subprocess.TimeoutExpired:
        remaining[app.pid] = owned.get(app.pid, "unreadable")
    code = app.poll()
    expected_signals = {-a["signal"] for a in actions if isinstance(a, dict) and a["pid"] == app.pid}
    return dict(actions=actions, remaining=remaining, exit_code=code,
                unexpected_exit=code != 0 and code not in expected_signals)


def run_smoke(args, report: dict) -> None:
    argv = ["/usr/bin/hub"]  # Native embedding launcher; never use '-c' or '-m'.
    validate_launch(dict(os.environ), os.getuid(), os.geteuid(), argv)
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise SmokeError("requires Ubuntu 24.04 amd64; native acceptance is not portable")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise SmokeError(f"unsupported smoke host: {release}")
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise SmokeError("run inside Xvfb + a DBus session + openbox (or equivalent EWMH WM)")
    for tool in ("dpkg-query", "ldd", "wmctrl", "xwininfo", "xprop"):
        if not shutil.which(tool):
            raise SmokeError(f"missing CI prerequisite: {tool}")
    import websocket  # noqa: F401 - check CI-only dependency before launching.
    from PIL import ImageGrab

    inventory = installed_inventory(args.expected_version)
    report["installed"] = inventory
    report["host"] = dict(os_release=release, machine=platform.machine(), observer_python=sys.executable)
    # Linux-only and per-process: make orphan renderers reapable, not a policy change.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise SmokeError(f"cannot become child subreaper: errno={ctypes.get_errno()}")
    report["subreaper"] = True
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lph-installed-smoke-") as directory:
        work = Path(directory).resolve()
        if work.is_relative_to(root):
            raise SmokeError("temporary installed working directory must be outside checkout")
        fixture = seed_fixture(root, work, sys.executable, uuid.uuid4().hex)
        report["fixture"] = fixture
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = app_environment(dict(os.environ), work, port)
        validate_launch(env, os.getuid(), os.geteuid(), argv)
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
            Path(env[key]).mkdir(mode=0o700)
        report["launch"] = dict(argv=argv, cwd=str(work), debug_port=port,
                                environment={k: v for k, v in env.items() if k.startswith(("QT", "PYTHON", "LD_", "XDG_")) or k in ("HOME", "PATH", "LOCAL_PROJECT_HUB_HOME")})
        app, owned, window = None, {}, None
        with hidden_source(root, report=report) as hidden:
            report["source_hidden_during_launch"] = hidden
            try:
                with (args.output / "app.log").open("xb") as log:
                    app = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT)
                    def poll():
                        refresh_owned(owned, env["LOCAL_PROJECT_HUB_HOME"])
                        return app.poll()
                    token = wait_for(lambda: process_identity(app.pid), poll, "native process identity", 3)
                    owned[app.pid] = token
                    native = process_evidence(app.pid, token)
                    if native["exe"] != inventory["launcher_realpath"] or native["cwd"] != str(work):
                        raise SmokeError(f"unexpected native installed origin: {native}")
                    report["native_process"] = native
                    def listening():
                        path = Path(fixture["metadata"])
                        return json.loads(path.read_text()) if path.is_file() else None
                    metadata = wait_for(listening, poll, "autostarted fixture listener", 45)
                    if metadata["pid"] not in refresh_owned(owned, env["LOCAL_PROJECT_HUB_HOME"]):
                        raise SmokeError("fixture listener PID is not a verified installed-app descendant")
                    child = process_evidence(metadata["pid"], owned[metadata["pid"]])
                    if fixture["script"] not in child["argv"]:
                        raise SmokeError("app did not launch the seeded CI Python script")
                    parsed = urlsplit(metadata["url"])
                    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path != "/" + fixture["nonce"]:
                        raise SmokeError("fixture published an unexpected loopback URL")
                    report["fixture_listener"] = dict(metadata, process=child)
                    wait_for(lambda: page_evidence(port, metadata["url"]), poll, "discovered dashboard CDP page", 45)
                    window = wait_for(lambda: native_window(app.pid), poll, "exposed native X11 window", 10)
                    report["native_window"] = window
                    def painted_native():
                        image = ImageGrab.grab(xdisplay=os.environ["DISPLAY"])
                        image.save(args.output / "root.png")
                        window_image = image.crop(tuple(window["frame"])).convert("RGB")
                        window_image.save(args.output / "window.png")
                        try:
                            return validate_native_pixels(window_image.getdata())
                        except SmokeError:
                            return None  # DOM readiness may precede the first compositor frame.
                    report["native_fixture_pixels"] = wait_for(painted_native, poll, "native fixture paint", 10)
                    page = page_evidence(port, metadata["url"], screenshot=args.output / "webview.png")
                    if page is None:
                        raise SmokeError("dashboard disappeared during final screenshot")
                    report["page"] = page
                    live = refresh_owned(owned, env["LOCAL_PROJECT_HUB_HOME"])
                    processes = []
                    for pid, identity in sorted(live.items()):
                        try:
                            processes.append(process_evidence(pid, identity))
                        except (OSError, SmokeError) as exc:
                            report.setdefault("exited_during_snapshot", []).append(str(exc))
                    report["processes"] = processes
                    report["renderers"] = validate_renderers(processes, inventory["helper"])
                    saved = json.loads((work / "state/registry.json").read_text())
                    record = next(r for r in saved["projects"] if r["id"] == fixture["record"]["id"])
                    report["discovered_registry_url"] = record["url"]
                    if record["url"] != metadata["url"]:
                        raise SmokeError("installed app did not persist stdout URL discovery")
                    validate_dom(page["dom"], title=fixture["title"],
                                 text=args.expected_text if args.expected_text is not None else fixture["text"],
                                 url=metadata["url"])
                    if app.poll() is not None:
                        raise SmokeError(f"installed app crashed after evidence: {app.returncode}")
            finally:
                signal.alarm(0)  # Cleanup has its own bounded stages, even after the total deadline.
                if app is not None:
                    report["cleanup"] = cleanup_owned(app, owned, env["LOCAL_PROJECT_HUB_HOME"], window)
                    if report["cleanup"]["remaining"]:
                        raise SmokeError(f"owned processes survived cleanup: {report['cleanup']['remaining']}")
                    if report["cleanup"]["unexpected_exit"]:
                        raise SmokeError(f"installed app exited unexpectedly: {report['cleanup']['exit_code']}")
        report["source_restored"] = all((root / name).exists() for name in ("hub", "main.py"))
        if not report["source_restored"]:
            raise SmokeError("source restoration was incomplete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory (must not exist)")
    parser.add_argument("--expected-version", default="0.7.1")
    parser.add_argument("--expected-text", help="exact body expectation; wrong text is a safe negative control")
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, expected_version=args.expected_version, expected_text=args.expected_text)
    handlers = {}
    def interrupted(signum, frame):
        raise SmokeError(f"bounded smoke interrupted by signal {signum}")
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            handlers[sig] = signal.signal(sig, interrupted)
        signal.alarm(120)
        run_smoke(args, report)
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        signal.alarm(0)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(args.output / "report.json"), "error": report.get("error")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
