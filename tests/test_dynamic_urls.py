"""Restart/address regressions through real Hub actions and owned servers.

Run one native WebEngine case per process with --test=<name>. All listeners use
OS-assigned ports and every registry/server belongs to the case, never the user.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import shlex
import sys
import tempfile
import time
from unittest import SkipTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QEventLoop, QProcess, QTimer
from PySide6.QtWidgets import QApplication
from hub import store as sm, urldetect
from hub.window import HubWindow


def spin(ms=30):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        spin()
    return predicate()


SERVER = '''from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import json, os, sys
marker = Path(sys.argv[1])
previous = json.loads(marker.read_text()) if marker.exists() else {}
run = previous.get("run", 0) + 1
title = "OWNED_AUTO_RUN_" + str(run)
body = ("<title>" + title + "</title><h1>" + title + "</h1>").encode()
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
server = HTTPServer(("127.0.0.1", 0), H)
# Make the regression independent of a platform reusing the last ephemeral port.
while server.server_port == previous.get("port"):
    server.server_close()
    server = HTTPServer(("127.0.0.1", 0), H)
url = "http://127.0.0.1:" + str(server.server_port) + "/"
marker.write_text(json.dumps({"run": run, "port": server.server_port, "pid": os.getpid(), "url": url}))
print("Local dashboard at " + url, flush=True)
server.serve_forever()
'''


def close_window(window):
    for waiter in list(window.waiters.values()):
        waiter.stop()
        waiter.deleteLater()
    window.waiters.clear()
    procs = list(window.procs.values())
    for proc in procs:
        proc.stop()
    assert wait_for(lambda: all(p.proc is None or p.proc.state() == QProcess.NotRunning for p in procs), 25), "owned backend did not exit"
    window.close()
    spin(100)


def _restart_rediscovery(tmp, source):
    script, marker = tmp / "serve.py", tmp / "bound.json"
    script.write_text(source)
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Automatic backend", "working_dir": str(tmp),
                     "interpreter": sys.executable,
                     "command": " ".join(shlex.quote(str(p)) for p in (script, marker)), "url": ""})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    try:
        window.act_start.trigger()
        view = window._view_for(rec["id"])
        assert view is not None
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_1"), (view.title(), list(window.procs[rec["id"]].history))
        first = json.loads(marker.read_text())
        assert store.get(rec["id"])["url"] == first["url"]
        window.act_restart.trigger()
        assert wait_for(lambda: marker.exists() and json.loads(marker.read_text())["run"] == 2), list(window.procs[rec["id"]].history)
        second = json.loads(marker.read_text())
        assert second["port"] != first["port"]
        # Silent backends use the existing six-second listening-port fallback.
        assert wait_for(lambda: store.get(rec["id"])["url"] == second["url"], 12), (
            "restart kept the previous run's saved port", store.get(rec["id"])["url"], second["url"])
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_2"), (view.url().toString(), view.title())
        assert window.tabs.currentWidget() is view and view.isVisible() and view.width() > 0 and view.height() > 0
        assert sm.Store(store.path).get(rec["id"])["url"] == second["url"]
    finally:
        close_window(window)


def test_restart_rediscover_saved_automatic_url(tmp):
    _restart_rediscovery(tmp, SERVER)


def test_silent_backend_rediscovers_its_port_after_restart(tmp):
    _restart_rediscovery(tmp, SERVER.replace('print("Local dashboard at " + url, flush=True)', 'pass'))


def test_restart_does_not_treat_last_auto_port_as_a_launch_requirement(tmp):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import urllib.request

    script, marker = tmp / "serve.py", tmp / "bound.json"
    script.write_text(SERVER)
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Moving backend", "working_dir": str(tmp), "interpreter": sys.executable,
                     "command": " ".join(shlex.quote(str(p)) for p in (script, marker)), "url": ""})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    foreign = None
    thread = None
    try:
        window.act_start.trigger()
        view = window._view_for(rec["id"])
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_1")
        first = json.loads(marker.read_text())
        proc = window.procs[rec["id"]]
        proc.stop()
        assert wait_for(lambda: proc.proc.state() == QProcess.NotRunning)

        class Other(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"UNRELATED_PROJECT")
            def log_message(self, *args): pass

        foreign = HTTPServer(("127.0.0.1", first["port"]), Other)
        thread = threading.Thread(target=foreign.serve_forever, daemon=True)
        thread.start()
        window.act_restart.trigger()
        assert wait_for(lambda: json.loads(marker.read_text())["run"] == 2, 5), (
            "an old detected port blocked a backend that chooses its own free port", list(proc.history))
        second = json.loads(marker.read_text())
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_2")
        assert view.url().port() == second["port"] != first["port"]
        with urllib.request.urlopen(first["url"], timeout=2) as response:
            assert response.read() == b"UNRELATED_PROJECT"
        assert store.get(rec["id"])["url"] == second["url"]
    finally:
        close_window(window)
        if foreign is not None:
            foreign.shutdown()
            foreign.server_close()
        if thread is not None:
            thread.join(timeout=3)
            assert not thread.is_alive()


def test_legacy_local_address_follows_its_owned_backend_not_a_foreign_page(tmp):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    from unittest.mock import patch
    from urllib.parse import urlsplit

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<title>UNRELATED_PROJECT</title>wrong backend"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, format, *args): pass

    foreign = HTTPServer(("127.0.0.1", 0), Other)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    thread.start()
    script, marker = tmp / "serve.py", tmp / "bound.json"
    script.write_text(SERVER)
    old_url = "http://127.0.0.1:" + str(foreign.server_port) + "/view?keep=yes#panel"
    raw = {"id": "legacy", "name": "Existing registration", "working_dir": str(tmp),
           "interpreter": sys.executable, "command": " ".join(shlex.quote(str(p)) for p in (script, marker)),
           "url": old_url}
    path = tmp / "registry.json"
    path.write_text(json.dumps({"version": 2, "projects": [raw]}))
    store = sm.Store(path)
    rec = store.get("legacy")
    assert rec is not None
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    view = window._view_for(rec["id"])
    assert view is not None
    seen = []
    view.titleChanged.connect(seen.append)
    try:
        window.act_start.trigger()
        assert wait_for(marker.exists, 5), "old detected port was treated as a fixed launch requirement"
        bound = json.loads(marker.read_text())
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_1"), (view.title(), seen)
        saved = store.get("legacy")
        assert saved is not None
        actual = urlsplit(saved["url"])
        assert actual.port == bound["port"] != foreign.server_port
        assert (actual.path, actual.query, actual.fragment) == ("/view", "keep=yes", "panel")
        assert "UNRELATED_PROJECT" not in seen, seen
        opened = []
        with patch("hub.window.QDesktopServices.openUrl", side_effect=lambda u: opened.append(u.toString()) or True):
            window._open_external()
        assert opened == [saved["url"]], opened
        assert sm.Store(path).get("legacy")["url"] == saved["url"]
    finally:
        close_window(window)
        foreign.shutdown()
        foreign.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_configurable_static_server_uses_a_free_port_without_changing_its_command(tmp):
    _static_server_free_port(tmp, "index.html")


def test_static_port_fallback_preserves_picked_html_entry_and_private_profile(tmp):
    _static_server_free_port(tmp, "chosen page.html")


def _static_server_free_port(tmp, filename):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import urllib.request

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OTHER_SERVER_STAYS_RUNNING")
        def log_message(self, format, *args): pass

    foreign = HTTPServer(("127.0.0.1", 0), Other)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    thread.start()
    (tmp / filename).write_text("<title>OWNED_STATIC_PAGE</title>our static site")
    command = "-m http.server " + str(foreign.server_port) + " --bind 127.0.0.1"
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Static page", "working_dir": str(tmp), "interpreter": sys.executable,
                     "command": command, "url": "",
                     "entry_file": filename if filename != "index.html" else ""})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    try:
        window.act_start.trigger()
        view = window._view_for(rec["id"])
        assert view is not None
        assert wait_for(lambda: view.title() == "OWNED_STATIC_PAGE", 6), (
            "configurable server did not recover from an occupied port", view.title(),
            list(window.procs[rec["id"]].history))
        assert view.url().port() != foreign.server_port
        saved = sm.Store(store.path).get(rec["id"])
        assert saved is not None and saved["command"] == command and saved["interpreter"] == sys.executable
        assert view.url().path() == ("/" if filename == "index.html" else "/" + filename)
        assert view.page().profile().storageName().startswith("hub-html-"), (
            "free-port launch lost the static project's private browser profile", view.url().toString())
        with urllib.request.urlopen("http://127.0.0.1:" + str(foreign.server_port), timeout=2) as response:
            assert response.read() == b"OTHER_SERVER_STAYS_RUNNING"
    finally:
        close_window(window)
        foreign.shutdown()
        foreign.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_static_port_taken_after_preflight_recovers_without_ending_the_holder(tmp):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import socket
    import threading
    import urllib.request
    from unittest.mock import patch

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"RACE_HOLDER_UNTOUCHED")
        def log_message(self, format, *args): pass

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        requested = reservation.getsockname()[1]
    foreign = HTTPServer(("127.0.0.1", requested), Other, bind_and_activate=False)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    (tmp / "index.html").write_text("<title>RACE_RECOVERED</title>owned static page")
    store = sm.Store(tmp / "registry.json")
    command = "-m http.server " + str(requested) + " --bind 127.0.0.1"
    rec = store.add({"name": "Port race", "working_dir": str(tmp), "interpreter": sys.executable,
                     "command": command})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    original_start = QProcess.start
    calls = []
    proc = window.procs[rec["id"]]
    states = []
    proc.state_changed.connect(lambda state: states.append((state, proc.proc)))
    def steal_after_preflight(child, program, args):
        calls.append(list(args))
        if len(calls) == 1:
            assert str(requested) in args, args
            foreign.server_bind()
            foreign.server_activate()
            thread.start()
        return original_start(child, program, args)
    try:
        with patch.object(QProcess, "start", steal_after_preflight):
            window.act_start.trigger()
            view = window._view_for(rec["id"])
            assert view is not None
            assert wait_for(lambda: view.title() == "RACE_RECOVERED", 5), (
                "bind race was not retried on an OS-selected port", list(window.procs[rec["id"]].history),
                window.log_view.toPlainText())
        assert len(calls) == 2 and "0" in calls[1], calls
        assert not any(state == "error" and child is proc.proc for state, child in states), (
            "the old finished callback reported an error on the replacement", [state for state, _ in states])
        assert view.url().port() != requested
        saved = store.get(rec["id"])
        assert saved is not None and saved["command"] == command
        with urllib.request.urlopen("http://127.0.0.1:" + str(requested), timeout=2) as response:
            assert response.read() == b"RACE_HOLDER_UNTOUCHED"
    finally:
        close_window(window)
        if thread.is_alive():
            foreign.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()
        foreign.server_close()


def test_a_live_child_does_not_make_another_process_dashboard_its_own(tmp):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<title>FOREIGN_DASHBOARD</title>not our backend"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, format, *args): pass
    foreign = HTTPServer(("127.0.0.1", 0), Other)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    thread.start()
    foreign_url = "http://127.0.0.1:" + str(foreign.server_port) + "/"
    script, marker = tmp / "serve.py", tmp / "bound.json"
    script.write_text(SERVER.replace('print("Local dashboard at " + url, flush=True)',
                                     'print(' + repr(foreign_url) + ', flush=True)'))
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Ownership proof", "working_dir": str(tmp), "interpreter": sys.executable,
                     "command": " ".join(shlex.quote(str(p)) for p in (script, marker))})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    view = window._view_for(rec["id"])
    assert view is not None
    seen = []
    view.titleChanged.connect(seen.append)
    try:
        window.act_start.trigger()
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_1", 8), (
            "the living child was used as proof of ownership for a foreign HTTP listener", view.title(), seen)
        assert "FOREIGN_DASHBOARD" not in seen, seen
        assert view.url().port() == json.loads(marker.read_text())["port"]
    finally:
        close_window(window)
        foreign.shutdown()
        foreign.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_address_settings_keep_auto_until_an_explicit_manual_edit(tmp):
    from PySide6.QtWidgets import QDialogButtonBox
    from hub.project_dialog import ProjectDialog
    base = sm.validate({"name": "Address intent", "working_dir": str(tmp), "command": "echo unused",
                        "url": "http://127.0.0.1:12345/view", "url_mode": "auto"})
    for text, mode in ((base["url"], "auto"), ("http://127.0.0.1:23456/custom", "manual"), ("", "auto")):
        dialog = ProjectDialog(record=base)
        dialog.show()
        try:
            dialog.url.setText(text)
            dialog.buttons.button(QDialogButtonBox.Ok).click()
            result = dialog.result_record()
            assert result is not None and (result["url"], result["url_mode"]) == (text, mode), result
        finally:
            dialog.close()
            dialog.deleteLater()
            spin()


def test_empty_address_never_produces_a_blank_unreachable_url_message(tmp):
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Not yet detected", "command": "echo unused"})
    window = HubWindow(store)
    window.show()
    window._select_id(rec["id"], start=False)
    try:
        view = window._view_for(rec["id"])
        assert view is not None
        view.loadFinished.emit(False)
        text = window.log_view._edit_for(rec["id"]).toPlainText()
        assert "not reachable at" not in text, ("an empty address was reported as a failed dashboard", text)
    finally:
        close_window(window)


def test_old_auto_address_is_not_opened_while_restart_is_rediscovering(tmp):
    from unittest.mock import patch

    script, marker = tmp / "serve.py", tmp / "bound.json"
    script.write_text(SERVER.replace(
        'print("Local dashboard at " + url, flush=True)',
        'import time\nif run > 1:\n    while not marker.with_suffix(".ready").exists(): time.sleep(0.02)\n'
        'print("Local dashboard at " + url, flush=True)'))
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Delayed replacement", "working_dir": str(tmp),
                     "interpreter": sys.executable,
                     "command": " ".join(shlex.quote(str(p)) for p in (script, marker)), "url": ""})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    try:
        window.act_start.trigger()
        view = window._view_for(rec["id"])
        assert view is not None and wait_for(lambda: view.title() == "OWNED_AUTO_RUN_1")
        opened = []
        with patch("hub.window.QDesktopServices.openUrl", side_effect=lambda u: opened.append(u.toString()) or True):
            window.act_restart.trigger()
            window._open_external()
            assert opened == [], ("opened the old address during requested restart", opened)
            assert wait_for(lambda: json.loads(marker.read_text())["run"] == 2)
            window._refresh_project_page(store.get(rec["id"]))
            window._open_external()
            assert opened == [], ("opened the last saved address before rediscovery", opened)
            marker.with_suffix(".ready").touch()
            assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_2")
            window._open_external()
        assert opened == [json.loads(marker.read_text())["url"]], opened
    finally:
        marker.with_suffix(".ready").touch()
        close_window(window)


def test_ambiguous_localhost_is_rejected_and_owned_literal_is_displayed(tmp):
    _disjoint_hostname_ownership(tmp, legacy=False)


def test_ambiguous_legacy_hostname_is_not_persisted(tmp):
    _disjoint_hostname_ownership(tmp, legacy=True)


def test_ipv6_owned_listener_recovers_beside_foreign_ipv4(tmp):
    _disjoint_hostname_ownership(tmp, legacy=False, reverse=True)


def test_legacy_ipv6_owned_listener_recovers_beside_foreign_ipv4(tmp):
    _disjoint_hostname_ownership(tmp, legacy=True, reverse=True)


def test_rejected_candidates_share_one_recovery_deadline(tmp):
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import patch
    import hub.window as wm
    from hub.process_manager import ProjectProcess

    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Recovery budget", "working_dir": str(tmp), "command": "node fixture.js",
                     "url": "http://127.0.0.1/view", "url_mode": "legacy"})
    candidate = "http://localhost/"
    proc = SimpleNamespace(_generation=0, detected_url=candidate, _url_recovery_until=None,
                           _own_pids=lambda: set())
    requests = []
    hub = SimpleNamespace(store=store, procs={rec["id"]: proc}, active_id=rec["id"],
                          _scan_ports_after=lambda *args, **kwargs: requests.append(kwargs["retry_until"]))
    hub._recover_url_discovery = lambda record, owner: wm.HubWindow._recover_url_discovery(
        cast(HubWindow, hub), record, cast(ProjectProcess, owner))
    with patch.object(wm.urldetect, "port_owners", return_value=set()), \
            patch.object(wm.time, "monotonic", return_value=100.0) as clock:
        wm.HubWindow._on_url_detected(cast(HubWindow, hub), candidate, rec["id"], _attempts=0)
        assert proc.detected_url is None
        clock.return_value = 120.0
        proc.detected_url = candidate
        wm.HubWindow._on_url_detected(cast(HubWindow, hub), candidate, rec["id"], _attempts=0)
    assert requests == [145.0, 145.0], ("rejection renewed the overall recovery budget", requests)


def test_new_launch_resets_url_recovery_deadline(tmp):
    from hub.process_manager import ProjectProcess
    rec = sm.validate({"name": "Recovery reset", "working_dir": str(tmp), "command": "python3 -c pass"})
    proc = ProjectProcess(rec)
    proc._url_recovery_until = 145.0
    # Refuse the launch before spawning; the new generation must still reset
    # its discovery budget rather than inheriting an expired previous run.
    proc.rec["command"] = ""
    try:
        proc.start()
        assert proc._url_recovery_until is None, ("new launch kept old recovery deadline", proc._url_recovery_until)
    finally:
        proc.stop()


def _disjoint_hostname_ownership(tmp, *, legacy, reverse=False):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import socket
    import threading
    import urllib.request
    from urllib.parse import urlsplit

    if reverse:
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as capability:
                capability.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                capability.bind(("::1", 0))
        except OSError as exc:
            raise SkipTest("IPv6-only owned listener unavailable: " + str(exc))
    script, marker = tmp / ("ipv6.py" if reverse else "ipv4.py"), tmp / "bound.json"
    source = SERVER.replace("import json, os, sys", "import json, os, sys, threading, time")
    if reverse:
        source = source.replace("from http.server import HTTPServer, BaseHTTPRequestHandler\n", '''from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
class HTTPServer(HTTPServer):
    address_family = socket.AF_INET6
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()
''').replace('"127.0.0.1"', '"::1"').replace("http://127.0.0.1:", "http://[::1]:")
    source = source.replace('print("Local dashboard at " + url, flush=True)\nserver.serve_forever()', '''threading.Thread(target=server.serve_forever, daemon=True).start()
while not marker.with_suffix(".announce").exists(): time.sleep(0.01)
print("Dashboard http://localhost:" + str(server.server_port) + "/", flush=True)
while True: time.sleep(0.1)''')
    script.write_text(source)
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"name": "Family ownership", "working_dir": str(tmp),
                     "interpreter": sys.executable,
                     "command": " ".join(shlex.quote(str(x)) for x in (script, marker))})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    view = window._view_for(rec["id"])
    assert view is not None
    proc = window._proc_for(rec)
    # Hold the optional initial scan so the real stdout banner is the first
    # discovery even on a slow test host. Rejection recovery remains real.
    real_scan = window._scan_ports_after
    def scans_after_rejection(rec, proc, delay_ms=6000, **kwargs):
        if delay_ms != 6000:
            real_scan(rec, proc, delay_ms, **kwargs)
    window._scan_ports_after = scans_after_rejection
    foreign = thread = None
    seen, observations = [], []
    view.titleChanged.connect(seen.append)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        window.act_start.trigger()
        assert wait_for(marker.exists, 5), list(proc.history)
        bound = json.loads(marker.read_text())
        class Other(BaseHTTPRequestHandler):
            def do_GET(self):
                body = ("<title>" + foreign_title + "</title>other backend").encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, format, *args): pass
        class V6Server(HTTPServer):
            address_family = socket.AF_INET6
            def server_bind(self):
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                super().server_bind()
        foreign_title = "FOREIGN_IPV4" if reverse else "FOREIGN_IPV6"
        foreign_url = ("http://127.0.0.1:" if reverse else "http://[::1]:") + str(bound["port"]) + "/"
        try:
            foreign = HTTPServer(("127.0.0.1", bound["port"]), Other) if reverse else V6Server(("::1", bound["port"]), Other)
        except OSError as exc:
            raise SkipTest("IPv6-only paired listener unavailable: " + str(exc))
        thread = threading.Thread(target=foreign.serve_forever, daemon=True)
        thread.start()
        own, owners = proc._own_pids(), urldetect.port_owners(bound["port"], "localhost")
        assert bound["pid"] in own and own & owners and owners - own, (own, owners, bound)
        for url, expected in ((bound["url"], b"OWNED_AUTO_RUN_1"),
                              (foreign_url, foreign_title.encode())):
            with opener.open(url, timeout=2) as response:
                assert expected in response.read(), ("fixture endpoint mismatch", url)
        if legacy:
            rec = store.update(dict(rec, url=bound["url"] + "view?keep=yes#panel", url_mode="legacy"))
            proc.rec = rec
        alias = "http://localhost:" + str(bound["port"]) + "/"
        real_detected = window._on_url_detected
        def observe(url, pid=None, _attempts=12):
            real_detected(url, pid, _attempts)
            if url == alias and _attempts == 12:
                current = store.get(rec["id"])
                assert current is not None
                observations.append((current["url"], window._current_dashboard_url(current)))
        window._on_url_detected = observe
        marker.with_suffix(".announce").touch()
        assert wait_for(lambda: bool(observations), 3), list(proc.history)
        if legacy:
            assert observations[0][0] == rec["url"], ("ambiguous hostname was persisted", observations, owners, own)
        assert observations[0][1] == "", ("ambiguous hostname passed ownership", observations, owners, own)
        assert wait_for(lambda: view.title() == "OWNED_AUTO_RUN_1", 6), (
            "owned endpoint was not recovered", view.title(), proc.detected_url,
            (store.get(rec["id"]) or {}).get("url"), list(proc.history))
        assert window.tabs.currentWidget() is view and view.isVisible()
        assert view.width() > 0 and view.height() > 0
        saved = sm.Store(store.path).get(rec["id"])
        assert saved is not None
        address = urlsplit(saved["url"])
        assert address.hostname == ("::1" if reverse else "127.0.0.1") and address.port == bound["port"], saved["url"]
        if legacy:
            assert (address.path, address.query, address.fragment) == ("/view", "keep=yes", "panel")
        assert foreign_title not in seen, seen
        with opener.open(foreign_url, timeout=2) as response:
            assert foreign_title.encode() in response.read(), "foreign listener was disturbed"
    finally:
        marker.with_suffix(".announce").touch()
        close_window(window)
        if foreign is not None:
            foreign.shutdown()
            foreign.server_close()
        if thread is not None:
            thread.join(timeout=3)
            assert not thread.is_alive()


def test_recovery_scan_stops_at_deadline_or_owner_state_change(tmp):
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import patch
    import hub.window as wm
    from hub.process_manager import ProjectProcess

    for change in ("deadline", "generation", "owner", "removed", "manual", "accepted", "stopped"):
        store = sm.Store(tmp / (change + ".json"))
        rec = store.add({"name": change, "command": "node fixture.js", "working_dir": str(tmp)})
        probes, callbacks = [], []
        def probe():
            probes.append(True)
            return None
        proc = SimpleNamespace(_generation=0, state="running", detected_url=None,
                               detect_url_from_ports=probe)
        hub = SimpleNamespace(store=store, procs={rec["id"]: proc}, _append_log=lambda *a: None)
        with patch.object(wm.QTimer, "singleShot", side_effect=lambda ms, cb: callbacks.append(cb)), \
                patch.object(wm.time, "monotonic", return_value=100.0) as clock:
            wm.HubWindow._scan_ports_after(cast(HubWindow, hub), rec, cast(ProjectProcess, proc),
                                          delay_ms=0, retry_until=101.0)
            callbacks.pop(0)()
            assert len(probes) == 1 and len(callbacks) == 1
            if change == "deadline": clock.return_value = 102.0
            elif change == "generation": proc._generation += 1
            elif change == "owner": hub.procs[rec["id"]] = object()
            elif change == "removed": store.remove(rec["id"])
            elif change == "manual": store.update(dict(rec, url="http://127.0.0.1/", url_mode="manual"))
            elif change == "accepted": proc.detected_url = "http://127.0.0.1/"
            elif change == "stopped": proc.state = "stopped"
            callbacks.pop(0)()
            assert len(probes) == 1 and not callbacks, ("recovery kept probing", change, probes)


def test_legacy_early_banner_recovers_after_initial_scan_expired(tmp):
    _legacy_discovery_after_rejection(tmp, misleading=False)


def test_legacy_unrelated_first_url_does_not_block_owned_announcement(tmp):
    _legacy_discovery_after_rejection(tmp, misleading=True)


def _legacy_discovery_after_rejection(tmp, *, misleading):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import urllib.request
    from urllib.parse import urlsplit

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<title>UNRELATED_EARLY_URL</title>foreign"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, format, *args): pass

    foreign = HTTPServer(("127.0.0.1", 0), Other)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    thread.start()
    marker, script = tmp / "announced.json", tmp / "late_bind.py"
    script.write_text('''import json, sys, time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
marker = Path(sys.argv[1])
body = b"<title>OWNED_RECOVERED_LEGACY</title>correct backend"
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
server = HTTPServer(("127.0.0.1", 0), H, bind_and_activate=False)
server.server_bind()
url = "http://127.0.0.1:" + str(server.server_port) + "/"
first = Path(sys.argv[2]).read_text() or url
pending = marker.with_suffix(".pending")
pending.write_text(json.dumps({"url": url, "first": first, "port": server.server_port}))
pending.replace(marker)
print("Early announcement " + first, flush=True)
while not marker.with_suffix(".ready").exists(): time.sleep(0.01)
server.server_activate()
marker.with_suffix(".bound").touch()
if first != url: print("Actual dashboard " + url, flush=True)
server.serve_forever()
''', encoding="utf-8")
    first = "http://localhost:" + str(foreign.server_port) + "/" if misleading else ""
    first_path = tmp / "first-url.txt"
    first_path.write_text(first)
    raw = {"id": "old-registration", "name": "Delayed legacy", "working_dir": str(tmp),
           "interpreter": sys.executable,
           "command": " ".join(shlex.quote(str(x)) for x in (script, marker, first_path)),
           "url": "http://127.0.0.1:" + str(foreign.server_port) + "/view?keep=yes#panel"}
    path = tmp / "registry.json"
    path.write_text(json.dumps({"version": 2, "projects": [raw]}))
    store = sm.Store(path)
    rec = store.get(raw["id"])
    assert rec is not None and rec["url_mode"] == "legacy"
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    view = window._view_for(rec["id"])
    assert view is not None
    proc = window._proc_for(rec)
    rejected, seen = [], []
    view.titleChanged.connect(seen.append)
    real_detected = window._on_url_detected
    def observe_rejection(url, pid=None, _attempts=12):
        real_detected(url, pid, _attempts)
        if _attempts == 0:
            rejected.append(url)
    window._on_url_detected = observe_rejection
    real_scan = window._scan_ports_after
    def initial_scan_soon(rec, proc, delay_ms=6000, **kwargs):
        # Test-only: expire the original one-shot scan while binding is held.
        # Production ownership retries and future recovery deadlines are intact.
        return real_scan(rec, proc, delay_ms=min(delay_ms, 200), **kwargs)
    window._scan_ports_after = initial_scan_soon
    try:
        window.act_start.trigger()
        assert wait_for(marker.exists, 5), ("backend never announced", proc.state,
                                              proc._expected_port(), list(proc.history))
        announced = json.loads(marker.read_text())
        assert wait_for(lambda: announced["first"] in rejected, 5), (rejected, list(proc.history))
        marker.with_suffix(".ready").touch()
        assert wait_for(marker.with_suffix(".bound").exists, 3), list(proc.history)
        with urllib.request.urlopen(announced["url"], timeout=2) as response:
            assert b"OWNED_RECOVERED_LEGACY" in response.read(), "fixture backend is not healthy"
        assert wait_for(lambda: view.title() == "OWNED_RECOVERED_LEGACY", 4), (
            "healthy legacy backend stayed undiscovered after rejection", view.title(),
            proc.detected_url, rejected, list(proc.history))
        assert window.tabs.currentWidget() is view and view.isVisible()
        assert view.width() > 0 and view.height() > 0
        saved = sm.Store(path).get(rec["id"])
        assert saved is not None
        url = urlsplit(saved["url"])
        assert url.port == announced["port"]
        assert (url.path, url.query, url.fragment) == ("/view", "keep=yes", "panel")
        assert "UNRELATED_EARLY_URL" not in seen, seen
        with urllib.request.urlopen("http://127.0.0.1:" + str(foreign.server_port), timeout=2) as response:
            assert b"UNRELATED_EARLY_URL" in response.read(), "foreign listener was disturbed"
    finally:
        marker.with_suffix(".ready").touch()
        close_window(window)
        foreign.shutdown()
        foreign.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--test=")), None)
    names = sorted(name for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn))
    if only:
        if only not in names:
            raise SystemExit("unknown test: " + only)
        names = [only]
    failed = 0
    for name in names:
        try:
            with tempfile.TemporaryDirectory(prefix="hub-dynamic-") as directory:
                fn = globals()[name]
                fn(Path(directory)) if inspect.signature(fn).parameters else fn()
            print("PASS " + name, flush=True)
        except SkipTest as exc:
            print("SKIP " + name + ": " + str(exc), flush=True)
        except Exception as exc:
            failed += 1
            print("FAIL " + name + ": " + repr(exc), flush=True)
    raise SystemExit(1 if failed else 0)
