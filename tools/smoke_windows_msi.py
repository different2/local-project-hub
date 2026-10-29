#!/usr/bin/env python3
"""TEMP: actual installed MSI smoke, not whole-suite or release signoff.

Only execute on an ephemeral, GitHub-hosted Windows-2025 runner. Installs the
provided MSI, launches its actual installed PE, observes an owned dashboard,
requests WM_CLOSE, and uninstalls only the exact newly owned ProductCode.
Observer dependencies: psutil + websocket-client. Never imports Qt.
Checkout hub/ and main.py are temporarily hidden and restored in finally.
Run serially, with no concurrent source tests/builds or installer activity.
"""
from __future__ import annotations

import argparse
import ast
import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from email.parser import BytesParser
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import platform
import re
import socket
import struct
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
import uuid


class SmokeError(RuntimeError):
    """A hard acceptance requirement failed."""


EXPECTED_UPGRADE_CODE = "{25F599D7-F44F-5B9D-8CC0-FC312B836125}"
EXPECTED_QT = "6.12.0"
BYPASS_FLAGS = {
    "--no-sandbox", "--disable-sandbox", "--disable-setuid-sandbox",
    "--disable-seccomp-filter-sandbox", "--disable-namespace-sandbox",
    "--disable-gpu-sandbox", "--single-process", "--in-process-gpu", "--no-zygote",
}
BASE_ENV = {
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "OS", "PATHEXT",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION",
}


def require_guid(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}", value):
        raise SmokeError("expected a literal braced MSI GUID; refusing to repair it")
    return value


def validate_no_bypass(environment: dict, argv: list[str]) -> None:
    env = {k.upper(): v for k, v in environment.items()}
    if "QTWEBENGINE_DISABLE_SANDBOX" in env:
        raise SmokeError("QTWEBENGINE_DISABLE_SANDBOX must be absent, including value '0'")
    raw = " ".join([*argv, *(env.get(k, "") for k in (
        "QTWEBENGINE_CHROMIUM_FLAGS", "CHROMIUM_FLAGS", "CHROME_FLAGS"))])
    flags = re.findall(r"--[A-Za-z][A-Za-z0-9-]*(?:=[^\s\"']*)?", raw)
    for flag in flags:
        name, _, value = flag.partition("=")
        if name.lower() in BYPASS_FLAGS:
            raise SmokeError(f"sandbox/process bypass forbidden: {name}")
        if name.lower() == "--disable-features" and any("sandbox" in item.lower() for item in value.split(",")):
            raise SmokeError("disabling a Chromium sandbox feature is forbidden")


def windows_command(argv: list[str]) -> str:
    if not argv or any(not isinstance(a, str) or "\x00" in a or "\n" in a or "\r" in a for a in argv):
        raise SmokeError("invalid native Windows argv")
    return subprocess.list2cmdline(argv)


def app_environment(original: dict, work: Path, debug_port: int) -> dict:
    validate_no_bypass(original, [])
    if not 0 < debug_port < 65536:
        raise SmokeError("invalid debugging port")
    # An allowlist, not a best-effort denylist: no CI tokens, Python injection,
    # Qt plugins/QPA overrides, proxy credentials or inherited debugging flags.
    env = {k.upper(): str(v) for k, v in original.items() if k.upper() in BASE_ENV}
    system = env.get("SYSTEMROOT", r"C:\Windows")
    env.update(PATH=ntpath.join(system, "System32") + ";" + system + ";" + ntpath.join(system, "System32", "Wbem"),
               HOME=str(work / "home"), USERPROFILE=str(work / "home"),
               APPDATA=str(work / "roaming"), LOCALAPPDATA=str(work / "local"),
               LOCAL_PROJECT_HUB_HOME=str(work / "state"),
               TEMP=str(work / "tmp"), TMP=str(work / "tmp"), TMPDIR=str(work / "tmp"),
               XDG_CACHE_HOME=str(work / "cache"), XDG_CONFIG_HOME=str(work / "config"),
               XDG_DATA_HOME=str(work / "data"),
               QTWEBENGINE_REMOTE_DEBUGGING=f"127.0.0.1:{debug_port}")
    validate_no_bypass(env, [])
    return env


def install_argv(msiexec: str, msi: Path, log: Path) -> list[str]:
    return [msiexec, "/i", str(msi), "/qn", "/norestart", "REBOOT=ReallySuppress", "/L*V!", str(log)]


def uninstall_argv(msiexec: str, product_code: str, log: Path) -> list[str]:
    return [msiexec, "/x", require_guid(product_code), "/qn", "/norestart", "REBOOT=ReallySuppress", "/L*V!", str(log)]


def validate_dom(dom: dict, *, title: str, text: str, url: str) -> None:
    if not isinstance(dom, dict):
        raise SmokeError("CDP returned no DOM object")
    for key, expected in (("title", title), ("text", text), ("url", url),
                          ("visibility", "visible"), ("ready", "complete")):
        if dom.get(key) != expected:
            raise SmokeError(f"DOM {key} mismatch: expected {expected!r}, got {dom.get(key)!r}")
    if dom.get("width", 0) <= 0 or dom.get("height", 0) <= 0:
        raise SmokeError("dashboard viewport has no visible area")


def target_endpoint(targets: list[dict], url: str, port: int) -> str | None:
    matches = [t for t in targets if t.get("type") == "page" and t.get("url") == url]
    if not matches:
        return None
    if len(matches) != 1:
        raise SmokeError("ambiguous owned CDP page")
    endpoint = matches[0].get("webSocketDebuggerUrl", "")
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port != port
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.startswith("/devtools/page/")):
        raise SmokeError("refusing non-loopback/non-owned CDP endpoint")
    return endpoint


def descendant_identities(rows: dict, roots: dict[int, float]) -> dict[int, float]:
    live = {pid: token for pid, token in roots.items() if pid in rows and rows[pid]["created"] == token}
    while True:
        children = {pid: row["created"] for pid, row in rows.items()
                    if pid not in live and row["ppid"] in live and row["created"] >= live[row["ppid"]]}
        if not children:
            return live
        live.update(children)


def validate_cleanup(result: dict) -> None:
    if not result.get("close_requested") or result.get("exit_code") != 0 or result.get("forced") or result.get("remaining"):
        raise SmokeError(f"normal native exit/owned-process cleanup failed: {result}")


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_manifest(root: Path) -> dict:
    if not (root / "hub").is_dir() or not (root / "main.py").is_file():
        raise SmokeError("missing hub/ or main.py Python payload")
    files = [root / "main.py", *sorted((root / "hub").rglob("*.py"))]
    if any(p.is_symlink() for p in (root / "hub").rglob("*")) or (root / "hub").is_symlink() or (root / "main.py").is_symlink():
        raise SmokeError("symlinked source payload is not accepted")
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in files}


def compare_payload(source: Path, installed: Path) -> dict:
    expected, actual = source_manifest(source), source_manifest(installed)
    if expected != actual:
        different = sorted(k for k in expected.keys() | actual.keys() if expected.get(k) != actual.get(k))
        raise SmokeError(f"installed Python source membership/hash differs from checkout: {different}")
    return actual


@contextmanager
def hidden_source(root: Path, report: dict):
    moved = []
    try:
        for name in ("hub", "main.py"):
            source = root / name
            target = root / (".msi-smoke-hidden-" + uuid.uuid4().hex + "-" + name)
            if not source.exists() or source.is_symlink() or target.exists():
                raise SmokeError(f"cannot safely hide source: {source}")
            source.rename(target)
            moved.append((source, target))
        report["source_hidden_during_launch"] = [{"source": str(a), "hidden": str(b)} for a, b in moved]
        yield
    finally:
        errors = []
        for source, target in reversed(moved):
            try:
                if source.exists() or source.is_symlink():
                    raise SmokeError(f"refusing source restoration overwrite: {source}")
                target.rename(source)
            except Exception as exc:
                errors.append(str(exc))
        report["source_restored"] = len(moved) == 2 and not errors and all(a.exists() and not b.exists() for a, b in moved)
        if errors:
            raise SmokeError("source restoration failed: " + "; ".join(errors))


def validate_msi_properties(properties: dict, expected_version: str) -> str:
    product = require_guid(properties.get("ProductCode", ""))
    upgrade = require_guid(properties.get("UpgradeCode", ""))
    if (properties.get("ProductName") != "Local Project Hub"
            or properties.get("ProductVersion") != expected_version
            or upgrade.lower() != EXPECTED_UPGRADE_CODE.lower()):
        raise SmokeError(f"MSI identity/version/upgrade family differs: {properties}")
    return product


def check_pe(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SmokeError(f"missing/non-regular installed executable: {path}")
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise SmokeError(f"not a native PE executable: {path}")
        offset = struct.unpack_from("<I", header, 0x3c)[0]
        if offset < 64 or offset > 16_000_000:
            raise SmokeError("invalid PE header offset")
        stream.seek(offset)
        signature = stream.read(6)
        if len(signature) != 6 or signature[:4] != b"PE\0\0" or struct.unpack_from("<H", signature, 4)[0] != 0x8664:
            raise SmokeError(f"installed launcher/helper is not AMD64 PE: {path}")


class MsiApi:
    """Built-in Windows Installer API. OpenDatabase uses read-only mode."""
    def __init__(self):
        self.dll = ctypes.WinDLL("msi", use_last_error=True)
        uint, dword = ctypes.c_uint32, wintypes.DWORD
        specs = {
            "MsiOpenDatabaseW": ([wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(uint)], uint),
            "MsiDatabaseOpenViewW": ([uint, wintypes.LPCWSTR, ctypes.POINTER(uint)], uint),
            "MsiViewExecute": ([uint, uint], uint), "MsiViewFetch": ([uint, ctypes.POINTER(uint)], uint),
            "MsiRecordGetStringW": ([uint, uint, wintypes.LPWSTR, ctypes.POINTER(dword)], uint),
            "MsiCloseHandle": ([uint], uint),
            "MsiQueryProductStateW": ([wintypes.LPCWSTR], ctypes.c_int),
            "MsiEnumRelatedProductsW": ([wintypes.LPCWSTR, dword, dword, wintypes.LPWSTR], uint),
            "MsiGetComponentPathW": ([wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(dword)], ctypes.c_int),
        }
        for name, (args, result) in specs.items():
            fn = getattr(self.dll, name)
            fn.argtypes, fn.restype = args, result

    @staticmethod
    def check(code: int, label: str) -> None:
        if code != 0:
            raise SmokeError(f"Windows Installer {label} failed: {code}")

    def rows(self, msi: Path, sql: str, columns: int) -> list[list[str]]:
        db, view = ctypes.c_uint32(), ctypes.c_uint32()
        self.check(self.dll.MsiOpenDatabaseW(str(msi), None, ctypes.byref(db)), "read-only database open")
        result = []
        try:
            self.check(self.dll.MsiDatabaseOpenViewW(db, sql, ctypes.byref(view)), "database query")
            self.check(self.dll.MsiViewExecute(view, 0), "query execute")
            while True:
                record = ctypes.c_uint32()
                code = self.dll.MsiViewFetch(view, ctypes.byref(record))
                if code == 259:
                    return result
                self.check(code, "fetch")
                try:
                    row = []
                    for field in range(1, columns + 1):
                        size = wintypes.DWORD(0)
                        code = self.dll.MsiRecordGetStringW(record, field, None, ctypes.byref(size))
                        if code not in (0, 234):
                            self.check(code, "field size")
                        buffer = ctypes.create_unicode_buffer(size.value + 1)
                        size.value += 1
                        self.check(self.dll.MsiRecordGetStringW(record, field, buffer, ctypes.byref(size)), "field read")
                        row.append(buffer.value)
                    result.append(row)
                finally:
                    self.dll.MsiCloseHandle(record)
        finally:
            if view.value:
                self.dll.MsiCloseHandle(view)
            self.dll.MsiCloseHandle(db)

    def state(self, product: str) -> int:
        return int(self.dll.MsiQueryProductStateW(require_guid(product)))

    def related(self, upgrade: str) -> list[str]:
        result = []
        for index in range(1000):
            buffer = ctypes.create_unicode_buffer(39)
            code = self.dll.MsiEnumRelatedProductsW(require_guid(upgrade), 0, index, buffer)
            if code == 259:
                return result
            self.check(code, "related-product enumeration")
            result.append(require_guid(buffer.value))
        raise SmokeError("unbounded related-product enumeration")

    def installed_launcher(self, product: str, files: list[list[str]]) -> tuple[Path, dict]:
        candidates = [row for row in files if row[1].split("|")[-1].lower() in (
            "local project hub.exe", "localprojecthub.exe", "hub.exe")]
        if len(candidates) != 1:
            raise SmokeError(f"MSI main File-table candidate is missing/ambiguous: {candidates}")
        file_id, filename, component, keypath, attributes = candidates[0]
        require_guid(component)
        if not keypath or int(attributes or 0) & 4:
            raise SmokeError("main executable component has no authoritative file key path")
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        state = int(self.dll.MsiGetComponentPathW(product, component, buffer, ctypes.byref(size)))
        if state != 3 or not buffer.value:
            raise SmokeError(f"MSI executable component is not installed locally: state={state}")
        key = Path(buffer.value)
        leaf = filename.split("|")[-1]
        path = key if keypath == file_id else key.parent / leaf
        if not path.is_absolute() or path.name.lower() != leaf.lower():
            raise SmokeError("unexpected MSI component/File-table path")
        check_pe(path)
        return path.resolve(), dict(file_id=file_id, filename=filename, component=component,
                                    component_keypath=keypath, observed_component_path=str(key), component_state=state)


def preexisting_names() -> list[dict]:
    # Read-only; never use Win32_Product (it can trigger MSI repair actions).
    import winreg
    matches = []
    for hive, label in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                root = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            with root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    name = winreg.EnumKey(root, index)
                    with winreg.OpenKey(root, name) as item:
                        try:
                            display = winreg.QueryValueEx(item, "DisplayName")[0]
                        except FileNotFoundError:
                            continue
                        if str(display).strip().lower() == "local project hub":
                            matches.append(dict(hive=label, key=name, display=display, view=view))
    return matches


def installed_payload(source: Path, launcher: Path, expected_version: str) -> dict:
    app, packages = launcher.parent / "app", launcher.parent / "app_packages"
    if any(p.is_symlink() for p in (app, packages)):
        raise SmokeError("installed application directories must not be symlinks")
    hashes = compare_payload(source, app)
    metadata = {}
    for folder, names in ((app, {"hub": expected_version}), (packages, {
        "pyside6-essentials": EXPECTED_QT, "pyside6-addons": EXPECTED_QT, "shiboken6": EXPECTED_QT})):
        found = {}
        for path in folder.glob("*.dist-info/METADATA"):
            parsed = BytesParser().parsebytes(path.read_bytes())
            normalized = re.sub(r"[-_.]+", "-", str(parsed.get("Name", ""))).lower()
            if normalized in names:
                if normalized in found or parsed.get_all("Version") != [names[normalized]] or len(parsed.get_all("Name", [])) != 1:
                    raise SmokeError(f"missing/duplicate/wrong bundled distribution identity: {path}")
                found[normalized] = dict(name=parsed["Name"], version=parsed["Version"], metadata=str(path), sha256=sha256_file(path))
        if set(found) != set(names):
            raise SmokeError(f"installed metadata missing: {sorted(set(names) - set(found))}")
        metadata.update(found)
    pyside = packages / "PySide6"
    qt_version = None
    for node in ast.parse((pyside / "__init__.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
            qt_version = ast.literal_eval(node.value)
    if qt_version != EXPECTED_QT:
        raise SmokeError(f"bundled PySide6 literal version differs: {qt_version}")
    helpers = list(pyside.rglob("QtWebEngineProcess.exe"))
    if len(helpers) != 1:
        raise SmokeError(f"installed WebEngine helper missing/ambiguous: {helpers}")
    helper = helpers[0].resolve()
    check_pe(helper)
    if not list(pyside.rglob("qtwebengine_resources.pak")) or not list(pyside.rglob("qtwebengine_locales/en-US.pak")):
        raise SmokeError("installed QtWebEngine resources/locales missing")
    return dict(launcher=str(launcher), launcher_sha256=sha256_file(launcher), app=str(app),
                app_version=metadata["hub"]["version"], qt_version=qt_version,
                helper=str(helper), distributions=metadata, source_hashes=hashes)


# Only this synthetic, stdlib-only project is ever registered or executed.
FIXTURE_SOURCE = '''from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import html, json, os, sys, time
config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
page = ('<!doctype html><meta charset="utf-8"><title>' + html.escape(config["title"])
        + '</title><style>body{margin:0;background:#123646;color:#f8f0d0;display:grid;'
        'place-items:center;height:100vh;font:32px sans-serif}</style><body>'
        + html.escape(config["text"]) + '</body>').encode("utf-8")
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/" + config["nonce"] else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
    def log_message(self, *args): pass
class Server(HTTPServer):
    allow_reuse_address = False
with Server(("127.0.0.1", 0), Handler) as server:
    server.timeout = 0.25
    url = "http://127.0.0.1:" + str(server.server_address[1]) + "/" + config["nonce"]
    meta = Path(config["metadata"])
    tmp = meta.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(pid=os.getpid(), ppid=os.getppid(), python=sys.executable,
                                  cwd=os.getcwd(), url=url, nonce=config["nonce"])), encoding="utf-8")
    tmp.replace(meta)
    print(url, flush=True)
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline: server.handle_request()
'''


def seed_fixture(root: Path, work: Path) -> dict:
    # Load validator and its pure relative imports before the checkout is hidden.
    # No sys.path fallback to an observer-installed 'hub' package is permitted.
    package = "_lph_msi_seed_" + uuid.uuid4().hex
    prior_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(package, root / "hub/__init__.py", submodule_search_locations=[str(root / "hub")])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    try:
        spec.loader.exec_module(module)
        from importlib import import_module
        store_module = import_module(package + ".store")
        # Ensure the lazy relative import inside validate is loaded as well.
        import_module(package + ".detect_type")
        project, state = work / "project", work / "state"
        project.mkdir()
        state.mkdir()
        script = project / "dashboard.py"
        script.write_text(FIXTURE_SOURCE, encoding="utf-8", newline="\n")
        ast.parse(FIXTURE_SOURCE)
        nonce = uuid.uuid4().hex
        config = dict(nonce=nonce, title="LPH installed MSI " + nonce, text="Installed MSI dashboard " + nonce,
                      metadata=str(project / "listening.json"), script=str(script))
        config_path = project / "fixture.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        argv = [str(Path(sys.executable).absolute()), "-I", "-u", str(script), str(config_path)]
        command = windows_command(argv)
        launch_module = import_module(package + ".platform")
        # The actual Windows parser is pure and can be calibrated off-platform.
        if launch_module._windows_argv(command) != argv:
            raise SmokeError("native Windows command failed checkout parser round trip")
        store = store_module.Store(state / "registry.json")
        record = store.add(store_module.validate(dict(name="Owned MSI smoke dashboard", working_dir=str(project),
            command=command, interpreter="", env={}, url="", autostart=True,
            detected={"type": "web", "evidence": ["owned synthetic stdlib HTTP fixture"]}, type_override="")))
        (state / "ui.json").write_text(json.dumps(dict(last_project=record["id"])), encoding="utf-8")
        if store_module.Store(state / "registry.json").get(record["id"]) != record:
            raise SmokeError("checkout Store fixture did not persist byte-preserving configuration")
        return dict(config, record=record, argv=argv, python=argv[0])
    finally:
        sys.dont_write_bytecode = prior_bytecode
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                del sys.modules[name]


class NativeWindows:
    """Win32 native geometry/WM_CLOSE and handle-pinned last-resort cleanup."""
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        specs = {
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        }
        for name, (args, result) in specs.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        specs = {
            "EnumWindows": ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "IsIconic": ([wintypes.HWND], wintypes.BOOL),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "GetClientRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        }
        for name, (args, result) in specs.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result

    def handle_time(self, handle) -> int:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (created.dwHighDateTime << 32) | created.dwLowDateTime

    def creation_time(self, pid: int) -> int:
        handle = self.kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return self.handle_time(handle)
        finally:
            self.kernel.CloseHandle(handle)

    def terminate_captured(self, pid: int, filetime: int) -> bool:
        if pid <= 4 or pid == os.getpid():
            raise SmokeError("refusing unsafe cleanup PID")
        handle = self.kernel.OpenProcess(0x1001, False, pid)  # QUERY_LIMITED_INFORMATION | TERMINATE
        if not handle:
            if ctypes.get_last_error() == 87:
                return False  # Task has already exited.
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.handle_time(handle) != filetime:
                return False  # PID reuse: never act on the new task.
            if not self.kernel.TerminateProcess(handle, 91):
                raise ctypes.WinError(ctypes.get_last_error())
            return True
        finally:
            self.kernel.CloseHandle(handle)

    def window(self, pid: int) -> dict | None:
        matches = []
        @self.callback_type
        def visit(hwnd, unused):
            owner = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not self.user.IsWindowVisible(hwnd) or self.user.IsIconic(hwnd):
                return True
            title = ctypes.create_unicode_buffer(1024)
            self.user.GetWindowTextW(hwnd, title, len(title))
            if title.value != "Local Project Hub":
                return True
            frame, client = wintypes.RECT(), wintypes.RECT()
            if self.user.GetWindowRect(hwnd, ctypes.byref(frame)) and self.user.GetClientRect(hwnd, ctypes.byref(client)):
                width, height = client.right - client.left, client.bottom - client.top
                if width > 300 and height > 200:
                    matches.append(dict(hwnd=int(hwnd), pid=pid, title=title.value, visible=True, minimized=False,
                                        frame=[frame.left, frame.top, frame.right, frame.bottom], width=width, height=height,
                                        source="Win32 EnumWindows/GetWindowThreadProcessId/GetClientRect"))
            return True
        if not self.user.EnumWindows(visit, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return matches[0] if len(matches) == 1 else None

    def close_window(self, pid: int, window: dict) -> bool:
        current = self.window(pid)
        if not current or current["hwnd"] != window["hwnd"]:
            return False
        if not self.user.PostMessageW(current["hwnd"], 0x0010, 0, 0):  # WM_CLOSE, not a simulated mouse gesture.
            raise ctypes.WinError(ctypes.get_last_error())
        return True


class OwnedProcesses:
    def __init__(self, psutil, native: NativeWindows, home: str, fixture_script: str, install_root: Path):
        self.psutil, self.native, self.home = psutil, native, home
        self.fixture_script, self.install_root = fixture_script, install_root
        self.owned, self.filetimes = {}, {}
        self.started = time.time()
        self.baseline = {(p.pid, p.info["create_time"]) for p in psutil.process_iter(["create_time"])}

    def capture(self, pid: int, created: float | None = None) -> None:
        process = self.psutil.Process(pid)
        identity = process.create_time()
        if created is not None and identity != created:
            raise SmokeError("process changed identity before capture")
        token = self.native.creation_time(pid)
        if process.create_time() != identity:
            raise SmokeError("process changed identity during capture")
        self.owned[pid], self.filetimes[pid] = identity, token

    def refresh(self) -> dict:
        rows = {}
        for process in self.psutil.process_iter(["pid", "ppid", "create_time"]):
            try:
                rows[process.pid] = dict(pid=process.pid, ppid=process.info["ppid"], created=process.info["create_time"])
            except self.psutil.NoSuchProcess:
                continue
        rows = {pid: row for pid, row in rows.items() if isinstance(row["created"], (int, float)) and isinstance(row["ppid"], int)}
        live = descendant_identities(rows, self.owned)
        # Recovery is restricted to NEW processes with this random state marker.
        # This catches an owned orphan even if its parent exited between polls.
        for pid, row in rows.items():
            if pid in live or row["created"] < self.started - 1 or (pid, row["created"]) in self.baseline:
                continue
            try:
                process = self.psutil.Process(pid)
                name = process.name().lower()
                if name not in {"qtwebengineprocess.exe", "local project hub.exe", "localprojecthub.exe", "hub.exe", "python.exe", "pythonw.exe"}:
                    continue
                env = process.environ()
                if env.get("LOCAL_PROJECT_HUB_HOME") != self.home:
                    continue
                exe, argv = Path(process.exe()), process.cmdline()
                if exe.is_relative_to(self.install_root) or self.fixture_script in argv:
                    live[pid] = row["created"]
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied, OSError):
                continue
        for pid, created in live.items():
            if self.owned.get(pid) != created:
                try:
                    self.capture(pid, created)
                except (self.psutil.NoSuchProcess, OSError):
                    continue
        return {pid: created for pid, created in live.items() if self.owned.get(pid) == created}

    def evidence(self, pid: int) -> dict:
        process = self.psutil.Process(pid)
        created = self.owned[pid]
        if process.create_time() != created or self.native.creation_time(pid) != self.filetimes[pid]:
            raise SmokeError("refusing evidence from reused process PID")
        env = process.environ()
        safe = {k: v for k, v in env.items() if k.startswith(("QTWEBENGINE", "PYTHON")) or k in (
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LOCAL_PROJECT_HUB_HOME", "TEMP", "TMP", "TMPDIR", "CHROMIUM_FLAGS", "CHROME_FLAGS")}
        row = dict(pid=pid, ppid=process.ppid(), created=created, creation_filetime=self.filetimes[pid],
                   exe=process.exe(), cwd=process.cwd(), argv=process.cmdline(), environment=safe)
        validate_no_bypass(safe, row["argv"])
        if process.create_time() != created:
            raise SmokeError("process changed during evidence capture")
        return row


def wait_for(probe, poll, label: str, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = poll()
        if code is not None:
            raise SmokeError(f"installed app exited before {label}: code={code}")
        result = probe()
        if result is not None:
            code = poll()
            if code is not None:
                raise SmokeError(f"installed app exited during {label}: code={code}")
            return result
        time.sleep(0.1)
    raise SmokeError(f"{label} timed out after {timeout}s")


def assert_listener(psutil, port: int, pid: int) -> list[dict]:
    matches = [c for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.laddr.port == port]
    if not matches or any(c.pid != pid or c.laddr.ip != "127.0.0.1" for c in matches):
        raise SmokeError(f"loopback TCP listener is absent, exposed, or not owned by expected PID {pid} on {port}")
    return [dict(pid=c.pid, ip=c.laddr.ip, port=c.laddr.port, status=c.status) for c in matches]


DOM_EXPRESSION = """({title:document.title,text:document.body?.innerText,url:location.href,
visibility:document.visibilityState,ready:document.readyState,width:innerWidth,height:innerHeight})"""


def cdp_call(wire, method: str, params: dict) -> dict:
    wire.send(json.dumps(dict(id=1, method=method, params=params)))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        wire.settimeout(max(0.1, deadline - time.monotonic()))
        raw = wire.recv()
        if len(raw) > 24_000_000:
            raise SmokeError("oversize CDP response")
        response = json.loads(raw)
        if response.get("id") == 1:
            if "error" in response:
                raise SmokeError(f"CDP {method}: {response['error']}")
            return response["result"]
    raise SmokeError(f"CDP {method} timed out")


def page_evidence(port: int, url: str, screenshot: Path | None = None) -> dict | None:
    import websocket
    try:
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise SmokeError("oversize CDP discovery")
        targets = json.loads(raw)
        if not isinstance(targets, list) or len(targets) > 16:
            raise SmokeError("invalid CDP target inventory")
        endpoint = target_endpoint(targets, url, port)
        if endpoint is None:
            return None
        wire = websocket.create_connection(endpoint, timeout=5, suppress_origin=True, http_proxy_host=None, http_no_proxy=["127.0.0.1"])
        try:
            result = cdp_call(wire, "Runtime.evaluate", dict(expression=DOM_EXPRESSION, returnByValue=True))
            if "exceptionDetails" in result:
                raise SmokeError("CDP DOM evaluation raised")
            dom = result.get("result", {}).get("value")
            if not isinstance(dom, dict) or dom.get("ready") != "complete":
                return None
            evidence = dict(endpoint=endpoint, dom=dom)
            if screenshot is not None:
                image = cdp_call(wire, "Page.captureScreenshot", dict(format="png", fromSurface=True))
                data = base64.b64decode(image["data"], validate=True)
                if len(data) < 32 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
                    raise SmokeError("CDP did not supply an actual PNG screenshot")
                width, height = struct.unpack_from(">II", data, 16)
                if width <= 0 or height <= 0:
                    raise SmokeError("CDP screenshot has an empty viewport")
                with screenshot.open("xb") as stream:
                    stream.write(data)
                evidence["screenshot"] = dict(path=str(screenshot), width=width, height=height,
                                               sha256=hashlib.sha256(data).hexdigest(),
                                               scope="CDP actual rendered page; NOT native desktop pixels or a native gesture")
            return evidence
        finally:
            wire.close()
    except (OSError, websocket.WebSocketException):
        if screenshot is not None:
            raise
        return None


def cleanup_owned(app, tracker: OwnedProcesses, native: NativeWindows, window: dict | None) -> dict:
    result = dict(close_requested=False, forced=[], remaining={}, exit_code=None)
    try:
        tracker.refresh()
        if app.poll() is None and tracker.native.creation_time(app.pid) == tracker.filetimes.get(app.pid):
            window = window or native.window(app.pid)
            if window:
                result["close_requested"] = native.close_window(app.pid, window)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            live = tracker.refresh()
            app.poll()
            if not live and app.poll() is not None:
                break
            time.sleep(0.1)
        live = tracker.refresh()
        # Never taskkill /T, terminate-by-name, or kill an unobserved numeric PID.
        for pid, created in sorted(live.items(), reverse=True):
            if tracker.native.terminate_captured(pid, tracker.filetimes[pid]):
                result["forced"].append(dict(pid=pid, created=created, creation_filetime=tracker.filetimes[pid]))
        if result["forced"]:
            deadline = time.monotonic() + 5
            while tracker.refresh() and time.monotonic() < deadline:
                app.poll()
                time.sleep(0.1)
        result["remaining"] = tracker.refresh()
        try:
            result["exit_code"] = app.wait(timeout=2)
        except subprocess.TimeoutExpired:
            result["remaining"][app.pid] = tracker.owned.get(app.pid)
    except Exception as exc:
        result["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        result["remaining"] = dict(tracker.owned)
    return result


def validate_runner_environment(environment: dict) -> dict:
    observed = {key: environment.get(key) for key in
                ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "RUNNER_OS", "ImageOS")}
    # runner-images maps Windows2025 and Windows2025_vs2026 to these exact IDs.
    if (observed["GITHUB_ACTIONS"] != "true" or observed["RUNNER_ENVIRONMENT"] != "github-hosted"
            or observed["RUNNER_OS"] != "Windows"
            or str(observed["ImageOS"] or "").lower() not in {"win25", "win25-vs2026"}):
        raise SmokeError("refusing non-ephemeral/non-Windows-2025 runner: " + json.dumps(observed, sort_keys=True))
    return observed


def native_preflight() -> dict:
    if sys.platform != "win32":
        raise SmokeError("requires actual native Windows-2025 on an ephemeral GitHub-hosted runner; no Windows acceptance on this host")
    if ctypes.sizeof(ctypes.c_void_p) != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SmokeError("requires an AMD64 observer on Windows-2025")
    validate_runner_environment(dict(os.environ))
    import psutil
    import websocket
    validate_no_bypass(dict(os.environ), [])
    return dict(system=platform.platform(), machine=platform.machine(), observer_python=sys.executable,
                image_os=os.environ["ImageOS"], image_version=os.environ.get("ImageVersion"),
                github_run_id=os.environ.get("GITHUB_RUN_ID"), github_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
                psutil_version=psutil.__version__, websocket_version=websocket.__version__)


def checkpoint(output: Path, report: dict) -> None:
    # This report belongs to this exclusive new evidence directory only.
    temporary = output / "report.json.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    temporary.replace(output / "report.json")


def git_read(root: Path, *argv: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise SmokeError(f"source git command failed ({result.returncode}): {argv}")
    return result.stdout.strip()


def installer_run(argv: list[str], environment: dict, timeout: float) -> dict:
    started = time.monotonic()
    try:
        child = subprocess.run(argv, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return dict(argv=argv, exit_code=child.returncode, duration_seconds=round(time.monotonic() - started, 3),
                    reboot_requested=child.returncode in (1641, 3010), timed_out=False)
    except subprocess.TimeoutExpired:
        # Killing the msiexec CLIENT on timeout does not prove its service stopped.
        # Acceptance fails and the exact ProductCode still gets uninstall in finally.
        return dict(argv=argv, exit_code=None, duration_seconds=round(time.monotonic() - started, 3), timed_out=True,
                    error="msiexec client timed out; service completion is unproven")


def run_smoke(args, report: dict) -> None:
    report["host"] = native_preflight()  # Before touching source, installer, state or Win32 APIs.
    import psutil
    root, msi, output = args.source_root.resolve(), args.msi.resolve(), args.output
    if output.is_relative_to(root):
        raise SmokeError("evidence/runtime must be outside the source checkout")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise SmokeError("--source-sha must be literal 40 lowercase hex characters")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.expected_version):
        raise SmokeError("--expected-version must be a literal three-component version")
    head = git_read(root, "rev-parse", "--verify", "HEAD")
    if head != args.source_sha:
        raise SmokeError(f"source checkout HEAD differs from --source-sha: {head}")
    if git_read(root, "status", "--porcelain", "--untracked-files=no", "--", "hub", "main.py", "pyproject.toml"):
        raise SmokeError("checkout runtime/packaging source has tracked modifications")
    source_before = source_manifest(root)
    report["source"] = dict(root=str(root), sha=head, hashes=source_before)
    if not msi.is_file() or args.msi.is_symlink():
        raise SmokeError("--msi must identify a regular actual artifact")
    with msi.open("rb") as stream:
        if stream.read(8) != bytes.fromhex("d0cf11e0a1b11ae1"):
            raise SmokeError("--msi is not an MSI compound-file container")
    api, native = MsiApi(), NativeWindows()
    properties = dict(api.rows(msi, "SELECT `Property`, `Value` FROM `Property`", 2))
    product = validate_msi_properties(properties, args.expected_version)
    files = api.rows(msi, "SELECT `File`.`File`, `File`.`FileName`, `Component`.`ComponentId`, `Component`.`KeyPath`, `Component`.`Attributes` FROM `File`, `Component` WHERE `File`.`Component_` = `Component`.`Component`", 5)
    report["msi"] = dict(path=str(msi), sha256=sha256_file(msi), bytes=msi.stat().st_size,
                         properties={k: properties[k] for k in ("ProductCode", "UpgradeCode", "ProductName", "ProductVersion")})
    baseline = dict(product_state=api.state(product), related=api.related(properties["UpgradeCode"]), names=preexisting_names())
    report["preinstall"] = baseline
    checkpoint(output, report)
    if baseline["product_state"] != -1 or baseline["related"] or baseline["names"]:
        raise SmokeError("refusing pre-existing exact/related/name-matching installation; nothing installed or uninstalled")
    work = output / "_runtime"
    work.mkdir()
    fixture = seed_fixture(root, work)
    report["fixture"] = fixture
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        debug_port = listener.getsockname()[1]
    environment = app_environment(dict(os.environ), work, debug_port)
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    installer_environment = {k: v for k, v in environment.items() if k in BASE_ENV or k in ("PATH", "TEMP", "TMP")}
    # Preserve the runner's actual installer context, but never its credentials.
    installer_environment.update({k.upper(): v for k, v in os.environ.items() if k.upper() in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME")})
    msiexec = str(Path(environment["SYSTEMROOT"]) / "System32/msiexec.exe")
    launcher, install_attempted = None, False
    report["cleanup_errors"] = []
    try:
        install_attempted = True
        report["install"] = installer_run(install_argv(msiexec, msi, output / "install.log"), installer_environment, 240)
        report["install"]["product_state_after"] = api.state(product)
        checkpoint(output, report)
        if report["install"]["exit_code"] != 0 or report["install"]["product_state_after"] != 5:
            raise SmokeError(f"msiexec install did not finish successfully without reboot: {report['install']}")
        if not (output / "install.log").is_file() or not (output / "install.log").stat().st_size:
            raise SmokeError("full verbose install log is missing")
        launcher, component = api.installed_launcher(product, files)
        if launcher.is_relative_to(root) or launcher.is_relative_to(output):
            raise SmokeError("MSI resolved executable is not an independent installed application")
        report["installed_component"] = component
        inventory = installed_payload(root, launcher, args.expected_version)
        report["installed"] = inventory
        argv = [str(launcher)]  # Actual installed PE only, never source '-m' or an injected Python hook.
        validate_no_bypass(environment, argv)
        report["launch"] = dict(argv=argv, cwd=str(work), environment=environment, debug_port=debug_port)
        tracker = OwnedProcesses(psutil, native, environment["LOCAL_PROJECT_HUB_HOME"], fixture["script"], launcher.parent)
        app, window = None, None
        with hidden_source(root, report):
            checkpoint(output, report)
            try:
                with (output / "app.log").open("xb") as log:
                    app = subprocess.Popen(argv, cwd=work, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                tracker.capture(app.pid)
                def poll():
                    tracker.refresh()
                    return app.poll()
                origin = tracker.evidence(app.pid)
                if ntpath.normcase(origin["exe"]) != ntpath.normcase(str(launcher)) or ntpath.normcase(origin["cwd"]) != ntpath.normcase(str(work)):
                    raise SmokeError("native process does not originate from the MSI-installed PE/outside-checkout cwd")
                report["native_process"] = origin
                def listening():
                    path = Path(fixture["metadata"])
                    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
                metadata = wait_for(listening, poll, "Hub-autostarted synthetic listener", 45)
                live = tracker.refresh()
                if (not isinstance(metadata.get("pid"), int) or metadata["pid"] not in live
                        or metadata.get("nonce") != fixture["nonce"]
                        or ntpath.normcase(metadata.get("python", "")) != ntpath.normcase(fixture["python"])):
                    raise SmokeError("fixture metadata does not identify an owned backend under the exact CI Python")
                backend = tracker.evidence(metadata["pid"])
                if backend["argv"][-4:] != fixture["argv"][-4:]:
                    raise SmokeError("actual owned backend argv did not preserve exact isolated Python/script/config arguments")
                parsed = urlsplit(metadata.get("url", ""))
                if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path != "/" + fixture["nonce"]
                        or parsed.username or parsed.password or parsed.query or parsed.fragment):
                    raise SmokeError("fixture announced an unexpected URL")
                report["fixture_listener"] = dict(metadata=metadata, process=backend, tcp=assert_listener(psutil, parsed.port, metadata["pid"]))
                wait_for(lambda: page_evidence(debug_port, metadata["url"]), poll, "installed WebEngine dashboard DOM", 45)
                report["debug_listener"] = assert_listener(psutil, debug_port, app.pid)
                window = wait_for(lambda: native.window(app.pid), poll, "visible native Win32 main window", 15)
                report["native_window"] = window
                page = page_evidence(debug_port, metadata["url"], output / "webview.png")
                if page is None:
                    raise SmokeError("actual dashboard vanished before screenshot")
                report["page"] = page
                validate_dom(page["dom"], title=fixture["title"], text=fixture["text"], url=metadata["url"])
                try:
                    validate_dom(page["dom"], title=fixture["title"], text=fixture["text"] + "-deliberately-wrong", url=metadata["url"])
                except SmokeError as exc:
                    report["wrong_dom_negative_control"] = dict(rejected=True, error=str(exc), scope="same actual DOM with deliberately wrong expected body")
                else:
                    raise SmokeError("wrong-DOM negative control was incorrectly accepted")
                live = tracker.refresh()
                processes = []
                for pid in sorted(live):
                    try:
                        processes.append(tracker.evidence(pid))
                    except psutil.NoSuchProcess:
                        report.setdefault("exited_during_snapshot", []).append(pid)
                report["owned_processes"] = processes
                renderers = [row for row in processes if ntpath.normcase(row["exe"]) == ntpath.normcase(inventory["helper"])
                             and re.search(r"(?:^|\s)--type=renderer(?:\s|$)", " ".join(row["argv"]))]
                if not renderers:
                    raise SmokeError("no actual owned installed QtWebEngine renderer process was observed")
                report["renderers"] = renderers
                report["sandbox_scope"] = "normal launch environment + actual owned renderer argv checked for bypass; no Windows token-level sandbox attestation"
                saved = json.loads((work / "state/registry.json").read_text(encoding="utf-8"))
                records = [r for r in saved["projects"] if r["id"] == fixture["record"]["id"]]
                if len(records) != 1 or records[0]["url"] != metadata["url"] or records[0]["command"] != fixture["record"]["command"]:
                    raise SmokeError("installed Hub failed stdout URL discovery persistence or changed the fixture command")
                report["persisted_fixture"] = records[0]
                if args.expected_text is not None:
                    validate_dom(page["dom"], title=fixture["title"], text=args.expected_text, url=metadata["url"])
                if app.poll() is not None:
                    raise SmokeError(f"installed process exited before requested native close: {app.returncode}")
                report["runtime_observed"] = True
                checkpoint(output, report)
            finally:
                if app is not None:
                    report["cleanup"] = cleanup_owned(app, tracker, native, window)
                    try:
                        validate_cleanup(report["cleanup"])
                    except SmokeError as exc:
                        report["cleanup_errors"].append(str(exc))
                checkpoint(output, report)
        if not report.get("source_restored") or source_manifest(root) != source_before or git_read(root, "rev-parse", "HEAD") != args.source_sha:
            raise SmokeError("source restoration/hash/HEAD preservation failed")
    finally:
        # Pre-existing installations never enter this ownership scope. Even a
        # partial install only authorizes THIS exact ProductCode.
        if install_attempted:
            try:
                report["uninstall"] = installer_run(uninstall_argv(msiexec, product, output / "uninstall.log"), installer_environment, 180)
                report["uninstall"].update(product_code=product, product_state_after=api.state(product),
                    related_after=api.related(properties["UpgradeCode"]), launcher_still_present=launcher.exists() if launcher else None)
                if (report["uninstall"]["exit_code"] != 0 or report["uninstall"]["product_state_after"] != -1
                        or report["uninstall"]["related_after"] or report["uninstall"]["launcher_still_present"] is True
                        or not (output / "uninstall.log").is_file()):
                    report["cleanup_errors"].append("exact owned MSI uninstall failed or requested reboot; inspect actual uninstall receipt/log")
            except Exception as exc:
                report["uninstall_error"] = f"{type(exc).__name__}: {exc}"
                report["cleanup_errors"].append("exact owned ProductCode uninstall raised")
        report["source_preserved_after"] = (root / "hub").is_dir() and (root / "main.py").is_file() and source_manifest(root) == source_before
        report["msi_preserved_after"] = sha256_file(msi) == report["msi"]["sha256"]
        if not report["source_preserved_after"] or not report["msi_preserved_after"]:
            report["cleanup_errors"].append("source/artifact content preservation failed")
        checkpoint(output, report)
    if report["cleanup_errors"]:
        raise SmokeError("; ".join(report["cleanup_errors"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--msi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory, outside checkout; must not exist")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1], help="checkout at the exact source SHA, not the TEMP workflow commit")
    parser.add_argument("--expected-text", help="optional deliberate wrong-body full-run failure control")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        print("refusing to clobber existing --output", file=sys.stderr)
        return 2
    args.output = args.output.resolve()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f"cannot create exclusive evidence directory: {exc}", file=sys.stderr)
        return 2
    report = dict(passed=False, scope="actual installed MSI smoke only; NOT whole-suite/release signoff",
                  expected_version=args.expected_version, source_sha=args.source_sha,
                  limitations=["CDP screenshot is rendered-page evidence, not native desktop pixels or a real mouse/keyboard gesture",
                               "normal environment and renderer argv checked; Windows token-level sandbox attestation is outside this smoke"],
                  reboot_permitted=False)
    try:
        checkpoint(args.output, report)
        run_smoke(args, report)
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        checkpoint(args.output, report)
    print(json.dumps(dict(passed=report["passed"], report=str(args.output / "report.json"), error=report.get("error"))))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
