"""Window-level regression tests (offscreen, no visible window).

These cover the failure mode where a project starts fine but the dashboard
never appears — the window sits on "Starting…" forever because:

  * process_manager never emitted the "running" state, so _on_state never
    started the readiness poll, and
  * _start_active() never started it either.

The proof of the regression is `test_selecting_project_loads_dashboard`: it
asserts the webview actually receives the dashboard URL, which is the step
that was missing.

Run:  QT_QPA_PLATFORM=offscreen python3 tests/test_window_e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hub import store as sm  # noqa: E402
from hub.window import HubWindow  # noqa: E402

# Each test gets its own port: sharing one lets a previous test's server kill
# the next with "Address already in use" (code=1), which reads as a regression
# but is just cross-test contamination.
_PORTS = {"selecting": 8791, "load": 8792, "restart": 8793, "stopped": 8794}


def _server_src(port: int) -> str:
    return f'''
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"HUB-WINDOW-TEST")
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", {port}), H).serve_forever()
'''


def _spin(ms=100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_for(pred, timeout_s=20.0):
    """Spin the event loop until pred() is true. Returns True/False."""
    deadline = int(timeout_s * 10)
    for _ in range(deadline):
        if pred():
            return True
        _spin(100)
    return pred()


def make_window(tmp: Path, key: str = "selecting") -> tuple[HubWindow, int]:
    port = _PORTS[key]
    (tmp / "srv.py").write_text(_server_src(port))
    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {
                "name": "Window Test",
                "command": f"{sys.executable} {tmp / 'srv.py'}",
                "url": f"http://127.0.0.1:{port}/",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    return w, port


def test_selecting_project_loads_dashboard(tmp: Path) -> None:
    """The core regression: select a project -> webview ends up on its URL."""
    w, port = make_window(tmp, "selecting")
    try:
        assert w.active_id, "no project selected after open"
        proc = w._proc_for(w.store.get(w.active_id))

        ok = _wait_for(lambda: w.web.url().toString() == f"http://127.0.0.1:{port}/")
        assert ok, (
            "webview never got the dashboard URL — stuck on the placeholder.\n"
            f"  webview url = {w.web.url().toString()!r}\n"
            f"  proc state  = {proc.state}\n"
            f"  stack shows webview = {w.stack.currentWidget() is w.web}"
        )
        # The dashboard loaded; don't couple this to the process staying alive.
        assert w.stack.currentWidget() is w.web, "webview not visible after load"
    finally:
        w.close()


def test_load_finishes_ok(tmp: Path) -> None:
    """The page itself loads, not just the URL assignment."""
    w, port = make_window(tmp, "load")
    try:
        done = {"ok": None}
        w.web.loadFinished.connect(lambda ok: done.update(ok=ok))
        _wait_for(lambda: w.web.url().toString() == f"http://127.0.0.1:{port}/")
        _wait_for(lambda: done["ok"] is not None, timeout_s=25)
        assert done["ok"] is True, f"loadFinished={done['ok']}"
        assert w.stack.currentWidget() is w.web, "webview not shown after load"
    finally:
        w.close()


def test_restart_reloads_dashboard(tmp: Path) -> None:
    """Restart must bring the dashboard back, not leave the placeholder up."""
    w, port = make_window(tmp, "restart")
    try:
        url = f"http://127.0.0.1:{port}/"
        _wait_for(lambda: w.web.url().toString() == url)
        # force the webview off the dashboard, then restart
        w.web.setUrl(QUrl("about:blank"))
        w._restart_active()
        ok = _wait_for(lambda: w.web.url().toString() == url)
        assert ok, f"dashboard did not come back after restart: {w.web.url().toString()!r}"
    finally:
        w.close()


def test_stopped_project_shows_explanation(tmp: Path) -> None:
    """A project whose backend dies explains itself instead of hanging."""
    port = _PORTS["stopped"]
    st = sm.Store(tmp / "registry2.json")
    st.add(
        sm.validate(
            {
                "name": "Never Starts",
                "command": f'{sys.executable} -c "import sys; sys.exit(3)"',
                "url": f"http://127.0.0.1:{port}/",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        proc = w._proc_for(w.store.get(w.active_id))
        ok = _wait_for(lambda: proc.state == "error", timeout_s=15)
        assert ok, f"expected error state, got {proc.state}"
        assert w.stack.currentWidget() is w.placeholder, "no explanation shown"
        text = w.placeholder.text()
        assert "exited with an error" in text, text
    finally:
        w.close()


if __name__ == "__main__":
    import tempfile

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
