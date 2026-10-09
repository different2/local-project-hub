"""Popup test: window.open(..., "_blank") must open a view, not vanish.

Background: dashboards like obs_live.py use window.open(url, "_blank") for the
🪐 spheres view, full replay, and the browser page. A plain QWebEngineView
drops those clicks silently — createWindow is never overridden — so the click
appears to do nothing inside the hub.

The fix is HubWebView.createWindow returning a real view. This test drives the
real class against a real server and asserts both window.open and
target="_blank" links produce a loaded view with the right URL.

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

from hub.window import HubWebView  # noqa: E402

PORT = 8783

PAGE_HTML = """<!doctype html>
<html><body>
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


def test_popups_open_a_real_view(tmp: Path) -> None:
    srv = _start_server(tmp)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", PORT), 0.4):
                    break
            except OSError:
                time.sleep(0.2)

        view = HubWebView()
        popups = []
        view.popup_opened.connect(lambda v: popups.append(v))

        loaded = {"ok": None}
        view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
        view.setUrl(f"http://127.0.0.1:{PORT}/")
        assert _wait_for(lambda: loaded["ok"] is True, timeout_s=25), "page never loaded"

        # 1) window.open(..., "_blank") — what the 🪐 spheres button does
        done = {"ok": None}
        popups_ready = {}

        def _watch(view):
            # Attach the listener immediately: the popup may finish loading
            # before we get a chance to connect afterwards.
            view.loadFinished.connect(lambda ok, v=view: done.update(ok=ok))

        view.popup_opened.connect(_watch)
        view.page().runJavaScript(
            f'window.open("http://127.0.0.1:{PORT}/via-open/", "_blank")'
        )
        assert _wait_for(lambda: popups), "window.open produced no view (dropped)"
        first = popups[0]
        ok = _wait_for(lambda: first.url().toString() == f"http://127.0.0.1:{PORT}/via-open/")
        assert ok, f"popup did not navigate: {first.url().toString()!r}"
        _wait_for(lambda: done["ok"] is not None, timeout_s=20)
        assert done["ok"] is True, f"popup page failed to load: {done['ok']}"

        # 2) a target="_blank" link click
        view.page().runJavaScript("document.getElementById('l').click()")
        assert _wait_for(lambda: len(popups) >= 2), f"link click produced no view: {len(popups)}"
        second = popups[1]
        ok = _wait_for(lambda: second.url().toString() == f"http://127.0.0.1:{PORT}/via-link/")
        assert ok, f"link popup wrong url: {second.url().toString()!r}"

        print("popup URLs:", [p.url().toString() for p in popups])
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
