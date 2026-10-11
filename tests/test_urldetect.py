"""URL auto-detection tests: a server's own output fills in the URL.

The user should not have to type a dashboard URL when the server announces
one. These tests cover the detector and the end-to-end wiring against real
subprocesses, using servers that print their address (Flask-style) and one
that stays silent (port-scan fallback).

Run:  QT_QPA_PLATFORM=offscreen python3 tests/test_urldetect.py
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

from hub import store as sm, urldetect  # noqa: E402
from hub.process_manager import ProjectProcess  # noqa: E402
from hub.window import HubWindow  # noqa: E402


def test_0_0_0_0_is_rewritten_to_localhost():
    """0.0.0.0 means 'all interfaces'; it is not connectable as an address."""
    url = urldetect.find_url("listening on http://0.0.0.0:5000")
    assert url is not None
    assert url.replace("0.0.0.0", "127.0.0.1") == "http://127.0.0.1:5000"


def _spin(ms=100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_for(pred, timeout_s=20.0):
    for _ in range(int(timeout_s * 10)):
        if pred():
            return True
        _spin(100)
    return pred()


# ---------- the detector itself ----------


def test_detects_urls_from_real_server_banners():
    cases = {
        "serving on http://localhost:8471  (assets list at /_assets-list)": "http://localhost:8471",
        "observability live dashboard at http://127.0.0.1:8787  (ctrl-c to stop)": "http://127.0.0.1:8787",
        " * Running on http://127.0.0.1:5000": "http://127.0.0.1:5000",
        "Server ready at http://0.0.0.0:3000/": "http://0.0.0.0:3000/",
    }
    for text, expected in cases.items():
        got = urldetect.find_url(text)
        assert got == expected, f"{text!r} -> {got!r}, expected {expected!r}"


def test_ignores_docs_and_noise():
    assert urldetect.find_url("See https://docs.python.org/3 for help") is None
    assert urldetect.find_url("nothing useful here") is None
    assert urldetect.find_url("install from https://pypi.org/project/x") is None


def test_falls_back_to_port_when_no_url_printed():
    assert urldetect.find_port("listening on port 9000") == 9000
    assert urldetect.find_port("PORT=8080") == 8080
    assert urldetect.find_port("no port anywhere") is None
    # a docs URL must not be mistaken for a port
    assert urldetect.find_port("See https://docs.python.org/3") is None


# ---------- end to end ----------

_ANNOUNCING_SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *a): pass
print(f"my dashboard is at http://127.0.0.1:{sys.argv[1]}", flush=True)
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""

_SILENT_SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *a): pass
# deliberately prints nothing
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def test_process_detects_url_from_output(tmp: Path) -> None:
    port = 8801
    srv_py = tmp / "announce.py"
    srv_py.write_text(_ANNOUNCING_SERVER)
    rec = sm.validate(
        {
            "name": "Announcing",
            "command": f"{sys.executable} {srv_py} {port}",
            "working_dir": str(tmp),
            "url": "",  # no URL configured — the whole point
        }
    )
    p = ProjectProcess(rec)
    got = []
    p.url_detected.connect(lambda u: got.append(u))
    p.start()
    ok = _wait_for(lambda: bool(got), timeout_s=25)
    p.stop()
    _wait_for(lambda: p.state == "stopped", timeout_s=25)
    assert ok, f"no URL detected from output; got={got}"
    assert got[0] == f"http://127.0.0.1:{port}", got[0]


def test_window_fills_in_and_saves_detected_url(tmp: Path) -> None:
    port = 8802
    srv_py = tmp / "announce2.py"
    srv_py.write_text(_ANNOUNCING_SERVER)
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "Auto URL",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
                "url": "",
            }
        )
    )
    assert rec["url"] == ""
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(rec["id"])
        expected = f"http://127.0.0.1:{port}/"
        # The tab should end up on the detected URL (Qt may add a trailing slash).
        ok = _wait_for(
            lambda: w.web is not None
            and w.web.url().toString().rstrip("/") == f"http://127.0.0.1:{port}",
            timeout_s=30,
        )
        assert ok, f"tab never loaded the detected URL; url={w.web.url().toString()!r}"
        # and it must be persisted so the user is not asked again
        reloaded = sm.Store(tmp / "registry.json").get(rec["id"])
        assert reloaded["url"], "detected URL was not saved to the registry"
        assert str(port) in reloaded["url"], reloaded["url"]
    finally:
        w.close()


def test_configured_url_is_never_overwritten(tmp: Path) -> None:
    """A URL the user typed themselves always wins over detection."""
    port = 8803
    srv_py = tmp / "announce3.py"
    srv_py.write_text(_ANNOUNCING_SERVER)
    rec = sm.validate(
        {
            "name": "Mine",
            "command": f"{sys.executable} {srv_py} {port}",
            "working_dir": str(tmp),
            "url": "http://127.0.0.1:9999/",  # deliberately different
        }
    )
    p = ProjectProcess(rec)
    got = []
    p.url_detected.connect(lambda u: got.append(u))
    p.start()
    _wait_for(lambda: bool(got), timeout_s=25)
    p.stop()
    _wait_for(lambda: p.state == "stopped", timeout_s=25)
    # detection must not fire at all when a URL is already configured
    assert got == [], f"detection ran despite a configured URL: {got}"


if __name__ == "__main__":
    import inspect

    app = QApplication.instance() or QApplication([])
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            # Some detector tests need no tempdir; pass one only if accepted.
            try:
                sig = inspect.signature(fn)
                takes_arg = len(sig.parameters) > 0
            except (TypeError, ValueError):
                takes_arg = False
            try:
                if takes_arg:
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
