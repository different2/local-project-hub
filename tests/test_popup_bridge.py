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
from hub.window import HubWindow, HubWebView  # noqa: E402

PORT = 8782

PAGE_HTML = """<!doctype html>
<html><head><title>popup host</title></head><body>
<h1>popup test</h1>
<button id="b" onclick='window.open("http://127.0.0.1:%d/via-open/", "_blank")'>go</button>
<a id="l" href="http://127.0.0.1:%d/via-link/" target="_blank">blank link</a>
</body></html>
""" % (PORT, PORT)


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


def _start_server(dirpath: Path) -> subprocess.Popen:
    (dirpath / "index.html").write_text(PAGE_HTML)
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
        f"HTTPServer(('127.0.0.1', {PORT}), H).serve_forever()\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", server],
        cwd=str(dirpath),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _await_server() -> None:
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", PORT), 0.4):
                return
        except OSError:
            time.sleep(0.2)


def _make_window(tmp: Path) -> HubWindow:
    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {
                "name": "Popup Host",
                "command": f'{sys.executable} -c "pass"',
                "url": f"http://127.0.0.1:{PORT}/",
                "working_dir": str(tmp),
            }
        )
    )
    win = HubWindow(st)
    win.show()
    return win


def test_createwindow_returns_a_view(tmp: Path) -> None:
    """Low-level contract: createWindow yields a view that navigates."""
    srv = _start_server(tmp)
    try:
        _await_server()
        view = HubWebView()
        popups = []
        view.popup_opened.connect(lambda v: popups.append(v))
        loaded = {"ok": None}
        view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
        view.setUrl(f"http://127.0.0.1:{PORT}/")
        assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25), "page never loaded"

        done = {"ok": None}
        view.popup_opened.connect(
            lambda v: v.loadFinished.connect(lambda ok: done.update(ok=ok))
        )
        view.page().runJavaScript(
            f'window.open("http://127.0.0.1:{PORT}/via-open/", "_blank")'
        )
        assert _wait_for(lambda: popups), "window.open produced no view (dropped)"
        first = popups[0]
        assert _wait_for(
            lambda: first.url().toString() == f"http://127.0.0.1:{PORT}/via-open/"
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
    srv = _start_server(tmp)
    try:
        _await_server()
        win = _make_window(tmp)
        try:
            loaded = {"ok": None}
            win.web.loadFinished.connect(lambda ok: loaded.update(ok=ok))
            win._show_dashboard(win.store.get(win.active_id))
            assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25), "page never loaded"

            base_tabs = win.tabs.count()
            assert base_tabs == 2, f"expected starter + 1 project tab, got {base_tabs}"

            win.web.page().runJavaScript(
                f'window.open("http://127.0.0.1:{PORT}/via-open/", "_blank")'
            )
            # starter + project tab + the new popup tab
            assert _wait_for(lambda: win.tabs.count() == 3), (
                f"no tab was added: count={win.tabs.count()}"
            )

            new_view = win.tabs.widget(2)
            assert _wait_for(
                lambda: new_view.url().toString() == f"http://127.0.0.1:{PORT}/via-open/"
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
    srv = _start_server(tmp)
    try:
        _await_server()
        win = _make_window(tmp)
        try:
            loaded = {"ok": None}
            win.web.loadFinished.connect(lambda ok: loaded.update(ok=ok))
            win._show_dashboard(win.store.get(win.active_id))
            assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25)

            win.web.page().runJavaScript("document.getElementById('l').click()")
            assert _wait_for(lambda: win.tabs.count() == 3), f"tabs={win.tabs.count()}"
            view = win.tabs.widget(2)
            _wait_for(lambda: view.url().toString() == f"http://127.0.0.1:{PORT}/via-link/")

            # closing the popup tab leaves the project tab intact
            win._close_tab(2)
            assert win.tabs.count() == 2, f"tab not closed: {win.tabs.count()}"
            assert win.tabs.widget(1).property("hub_project_id") == win.active_id, (
                "project tab should remain"
            )

            # the starter tab itself cannot be closed
            win._close_tab(win.dashboard_tab_index)
            assert win.tabs.count() == 2, "starter tab was closed"
        finally:
            win.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                try:
                    fn(Path(d))
                    print(f"PASS {name}")
                except AssertionError as e:
                    fails += 1
                    print(f"FAIL {name}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
