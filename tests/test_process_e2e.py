"""End-to-end check of process_manager + readiness WITHOUT a GUI.

Spawns a real stdlib HTTP server via QProcess, exactly like a registered
project would, and asserts:
  * state goes starting -> running
  * captured stdout appears in the log history
  * stop() terminates it and the port frees up

Run:  QT_QPA_PLATFORM=offscreen python3 tests/test_process_e2e.py
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from hub import store as sm  # noqa: E402
from hub.process_manager import ProjectProcess  # noqa: E402
from hub.readiness import ReadinessWaiter, tcp_open  # noqa: E402

PORT = 8799
SERVER_SRC = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"HUB-TEST-OK")
    def log_message(self, *a):
        sys.stdout.write("serving\\n"); sys.stdout.flush()

HTTPServer(("127.0.0.1", %d), H).serve_forever()
""" % PORT


def _spin(ms=200) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_process_lifecycle(tmp: Path) -> None:
    server_py = tmp / "fake_project_server.py"
    server_py.write_text(SERVER_SRC)

    rec = sm.validate(
        {
            "name": "Fake",
            "command": f"{sys.executable} {server_py}",
            "url": f"http://127.0.0.1:{PORT}/",
            "working_dir": str(tmp),
            "env": {},
        }
    )
    proc = ProjectProcess(rec)
    states = []
    logs = []
    proc.state_changed.connect(states.append)
    proc.output.connect(lambda t: logs.append(t))

    proc.start()
    _spin(300)
    assert "starting" in states, states

    # wait for running
    for _ in range(50):
        if proc.state == "running":
            break
        _spin(100)
    assert proc.state == "running", f"state stuck at {proc.state}"

    # readiness waiter should fire
    got = {"ready": False}
    waiter = ReadinessWaiter(rec["url"], timeout_ms=4000)
    waiter.ready.connect(lambda: got.update(ready=True))
    waiter.start()
    for _ in range(40):
        if got["ready"]:
            break
        _spin(100)
    assert got["ready"], "readiness never fired"    # TCP check
    assert tcp_open("127.0.0.1", PORT)

    # log capture
    assert any("serving" in t for t in logs), logs

    proc.stop()
    for _ in range(50):
        if proc.state == "stopped":
            break
        _spin(100)
    assert proc.state == "stopped", proc.state

    # port freed
    for _ in range(30):
        if not tcp_open("127.0.0.1", PORT):
            break
        _spin(100)
    assert not tcp_open("127.0.0.1", PORT), "port still open after stop"


def test_restart(tmp: Path) -> None:
    server_py = tmp / "restart_server.py"
    server_py.write_text(SERVER_SRC.replace(str(PORT), str(PORT + 1)))
    rec = sm.validate(
        {
            "name": "Restartable",
            "command": f"{sys.executable} {server_py}",
            "url": f"http://127.0.0.1:{PORT + 1}/",
            "working_dir": str(tmp),
        }
    )
    proc = ProjectProcess(rec)
    starts = []
    proc.state_changed.connect(lambda s: starts.append(s))
    proc.start()
    for _ in range(50):
        if proc.state == "running":
            break
        QTimer_single = 50
        _spin(100)
    assert proc.state == "running"

    proc.restart()  # stop then start again
    for _ in range(80):
        if starts.count("starting") >= 2 and proc.state == "running":
            break
        _spin(100)
    assert starts.count("starting") >= 2, starts
    assert proc.state == "running", proc.state
    proc.stop()
    for _ in range(50):
        if proc.state == "stopped":
            break
        _spin(100)


def test_bad_command_reports_error(tmp: Path) -> None:
    rec = sm.validate(
        {
            "name": "Broken",
            "command": f"{sys.executable} /no/such/file.py",
            "working_dir": str(tmp),
        }
    )
    proc = ProjectProcess(rec)
    out = []
    proc.output.connect(out.append)
    proc.start()
    for _ in range(50):
        if proc.state == "error" or any("No such file" in t for t in out):
            break
        _spin(100)
    assert proc.state == "error", proc.state
    assert any("No such file" in t for t in out), out


if __name__ == "__main__":
    import tempfile

    app = QCoreApplication([])
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
