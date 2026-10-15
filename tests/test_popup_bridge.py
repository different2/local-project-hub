"""Popup-as-tab tests: window.open(..., "_blank") must become a hub TAB.

Background: dashboards like obs_live.py use window.open(url, "_blank") for the
🪐 spheres view, full replay, and the browser page. A plain QWebEngineView
drops those calls (createWindow never overridden), so the click does nothing.

The hub answers them as tabs inside its own window: HubWebView.createWindow
returns a view, and HubWindow._on_popup_opened puts it in the QTabWidget.

Run:  QT_QPA_PLATFORM=offscreen python3 tests/test_popup_bridge.py
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hub import store as sm  # noqa: E402
from helpers import reserve_port  # noqa: E402
from hub.window import HubWindow, HubWebView  # noqa: E402

# No hardcoded port. The page has to know the server's address, so it is built
# per test from the port helpers.reserve_port() handed out -- two suites can then
# never contend for the same number.
def page_html(port: int) -> str:
    return """<!doctype html>
<html><head><title>popup host</title></head><body>
<h1>popup test</h1>
<button id="b" onclick='window.open("http://127.0.0.1:%d/via-open/", "_blank")'>go</button>
<a id="l" href="http://127.0.0.1:%d/via-link/" target="_blank">blank link</a>
</body></html>
""" % (port, port)


def _spin(ms=100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_for(pred, timeout_s=20.0) -> bool:
    for _ in range(int(timeout_s * 10)):
        if pred():
            return True
        _spin(100)
    return pred()


def _start_server(dirpath: Path) -> tuple[subprocess.Popen, int]:
    """Start one static-file server and return it with its assigned port.

    Reserving the port here means the page, the server and every client all use
    the same number, and no two tests or suites can collide on a fixed one.
    """
    port = reserve_port()
    (dirpath / "index.html").write_text(page_html(port))
    server = (
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        try:\n"
        "            body = open('index.html','rb').read()\n"
        "            self.send_response(200)\n"
        "            self.send_header('Content-Type','text/html')\n"
        "            self.end_headers()\n"
        "            self.wfile.write(body)\n"
        "        except Exception:\n"
        "            self.send_error(404)\n"
        "    def log_message(self, *a):\n"
        "        pass\n"
        f"HTTPServer(('127.0.0.1', {port}), H).serve_forever()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", server],
        cwd=str(dirpath),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc, port


def _await_server(port: int) -> None:
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.4):
                return
        except OSError:
            time.sleep(0.2)


def _make_window(tmp: Path, port: int) -> HubWindow:
    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {
                "name": "Popup Host",
                "command": f'{sys.executable} -c "pass"',
                "url": f"http://127.0.0.1:{port}/",
                "working_dir": str(tmp),
            }
        )
    )
    win = HubWindow(st)
    win.show()
    return win


def test_createwindow_returns_a_view(tmp: Path) -> None:
    """Low-level contract: createWindow yields a view that navigates."""
    srv, port = _start_server(tmp)
    try:
        _await_server(port)
        view = HubWebView()
        popups = []
        view.popup_opened.connect(lambda v: popups.append(v))
        loaded = {"ok": None}
        view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
        view.setUrl(f"http://127.0.0.1:{port}/")
        assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25), "page never loaded"

        done = {"ok": None}
        view.popup_opened.connect(
            lambda v: v.loadFinished.connect(lambda ok: done.update(ok=ok))
        )
        view.page().runJavaScript(
            f'window.open("http://127.0.0.1:{port}/via-open/", "_blank")'
        )
        assert _wait_for(lambda: popups), "window.open produced no view (dropped)"
        first = popups[0]
        assert _wait_for(
            lambda: first.url().toString() == f"http://127.0.0.1:{port}/via-open/"
        ), f"did not navigate: {first.url().toString()!r}"
        _wait_for(lambda: done["ok"] is not None, timeout_s=20)
        assert done["ok"] is True, f"popup page failed to load: {done['ok']}"
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


def test_window_open_becomes_a_tab(tmp: Path) -> None:
    """window.open(..., '_blank') adds a tab INSIDE the hub window."""
    srv, port = _start_server(tmp)
    try:
        _await_server(port)
        win = _make_window(tmp, port)
        try:
            loaded = {"ok": None}
            win.web.loadFinished.connect(lambda ok: loaded.update(ok=ok))
            win._show_dashboard(win.store.get(win.active_id))
            assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25), "page never loaded"

            base_tabs = win.tabs.count()
            assert base_tabs == 2, f"expected starter + 1 project tab, got {base_tabs}"

            win.web.page().runJavaScript(
                f'window.open("http://127.0.0.1:{port}/via-open/", "_blank")'
            )
            # starter + project tab + the new popup tab
            assert _wait_for(lambda: win.tabs.count() == 3), (
                f"no tab was added: count={win.tabs.count()}"
            )

            new_view = win.tabs.widget(2)
            assert _wait_for(
                lambda: new_view.url().toString() == f"http://127.0.0.1:{port}/via-open/"
            ), f"tab did not navigate: {new_view.url().toString()!r}"
            # Selected, and re-parented into the tab widget's internal stack
            # (QTabWidget reparents pages into its own QStackedWidget, so the
            # direct parent is that, not the tab widget itself).
            assert win.tabs.currentIndex() == 2, "new tab is not selected"
            assert win.tabs.indexOf(new_view) == 2, (
                "popup view is not a page of the tab widget"
            )
            assert new_view.isVisible(), "tab content is not visible"
            assert new_view.isWindow() is False, "popup became a separate window"
            print("tab label:", win.tabs.tabText(2), "| url:", new_view.url().toString())
        finally:
            win.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


def test_target_blank_link_and_closing(tmp: Path) -> None:
    """target='_blank' links open tabs; popup tabs close; dashboard tab does not."""
    srv, port = _start_server(tmp)
    try:
        _await_server(port)
        win = _make_window(tmp, port)
        try:
            loaded = {"ok": None}
            win.web.loadFinished.connect(lambda ok: loaded.update(ok=ok))
            win._show_dashboard(win.store.get(win.active_id))
            assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25)

            win.web.page().runJavaScript("document.getElementById('l').click()")
            assert _wait_for(lambda: win.tabs.count() == 3), f"tabs={win.tabs.count()}"
            view = win.tabs.widget(2)
            _wait_for(lambda: view.url().toString() == f"http://127.0.0.1:{port}/via-link/")

            # closing the popup tab leaves the project tab intact
            win._close_tab(2)
            assert win.tabs.count() == 2, f"tab not closed: {win.tabs.count()}"
            assert win.tabs.widget(1).property("hub_project_id") == win.active_id, (
                "project tab should remain"
            )

            # the starter tab IS closable now; closing it must not take the
            # project tab with it
            starter = win.starter_index()
            assert starter is not None, "starter tab missing before the close"
            win._close_tab(starter)
            assert win.tabs.count() == 1, f"tabs={win.tabs.count()}"
            assert win.tabs.widget(0).property("hub_project_id") == win.active_id, (
                "project tab should remain after the starter closed"
            )
            assert win.starter_index() is None, "starter should be gone"
        finally:
            win.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    # Honour the runner's --test=<name> isolation flag. Without this the suite
    # ignores it and runs every test, so one isolated process ran all three --
    # defeating the isolation the flag exists to provide and misattributing any
    # failure to the last test listed.
    only = None
    for _a in sys.argv[1:]:
        if _a.startswith("--test="):
            only = _a.split("=", 1)[1]

    app = QApplication.instance() or QApplication([])
    fails = 0
    ran = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if only and name != only:
                continue
            ran += 1
            with tempfile.TemporaryDirectory() as d:
                try:
                    fn(Path(d))
                    print(f"PASS {name}")
                except AssertionError as e:
                    fails += 1
                    print(f"FAIL {name}: {e}")
    if only and not ran:
        # Running nothing silently would let the runner report a green suite for
        # a test name that does not exist.
        print(f"ERROR no such test: {only}")
        sys.exit(2)
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
