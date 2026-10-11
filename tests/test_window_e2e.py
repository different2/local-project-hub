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
from hub.window import HubWebView, HubWindow  # noqa: E402

# Each test gets its own port: sharing one lets a previous test's server kill
# the next with "Address already in use" (code=1), which reads as a regression
# but is just cross-test contamination.
_PORTS = {"selecting": 8791, "load": 8792, "restart": 8793, "stopped": 8794, "stopping": 8790}


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


def test_selecting_project_opens_a_tab_with_its_url(tmp: Path) -> None:
    """Selecting a project opens ITS OWN tab and loads its dashboard there."""
    w, port = make_window(tmp, "selecting")
    try:
        assert w.active_id, "no project selected after open"
        proc = w._proc_for(w.store.get(w.active_id))

        # a new tab was created for the project (starter tab + 1)
        ok = _wait_for(lambda: w.tabs.count() == 2)
        assert ok, f"no tab was opened for the project: {w.tabs.count()}"

        view = w.tabs.widget(1)
        assert view.property("hub_project_id") == w.active_id, "tab is not bound to the project"
        ok = _wait_for(lambda: view.url().toString() == f"http://127.0.0.1:{port}/")
        assert ok, (
            "project tab never got the dashboard URL.\n"
            f"  url = {view.url().toString()!r}\n"
            f"  proc state = {proc.state}"
        )
    finally:
        w.close()


def test_two_projects_get_two_tabs(tmp: Path) -> None:
    """Each project has its own tab; re-selecting focuses instead of duplicating."""
    port_a, port_b = _PORTS["selecting"], _PORTS["load"]
    st = sm.Store(tmp / "registry.json")
    for name, port in (("Proj A", port_a), ("Proj B", port_b)):
        (tmp / f"srv_{port}.py").write_text(_server_src(port))
        st.add(
            sm.validate(
                {
                    "name": name,
                    "command": f"{sys.executable} {tmp / f'srv_{port}.py'}",
                    "url": f"http://127.0.0.1:{port}/",
                    "working_dir": str(tmp),
                }
            )
        )
    w = HubWindow(st)
    w.show()
    try:
        ids = [r["id"] for r in st.ordered()]
        w._select_id(ids[0])
        assert _wait_for(lambda: w.tabs.count() == 2), f"tabs={w.tabs.count()}"
        # let A's dashboard actually load before switching
        assert _wait_for(
            lambda: isinstance(w.tabs.widget(1), HubWebView)
            and w.tabs.widget(1).url().toString() != ""
        ), "A's tab never loaded"

        w._select_id(ids[1])
        assert _wait_for(lambda: w.tabs.count() == 3), f"second project got no tab: {w.tabs.count()}"
        assert _wait_for(
            lambda: isinstance(w.tabs.widget(2), HubWebView)
            and w.tabs.widget(2).url().toString() != ""
        ), "B's tab never loaded"

        # re-selecting the first project must NOT open a third tab
        w._select_id(ids[0])
        _spin(400)
        assert w.tabs.count() == 3, f"duplicate tab opened: {w.tabs.count()}"

        # each tab holds its own dashboard URL (skip the starter tab at 0)
        urls = set()
        for i in range(1, w.tabs.count()):
            v = w.tabs.widget(i)
            if isinstance(v, HubWebView):
                urls.add(v.url().toString())
        assert urls == {f"http://127.0.0.1:{port_a}/", f"http://127.0.0.1:{port_b}/"}, urls
    finally:
        w.close()


def test_stopping_a_project_closes_its_tabs(tmp: Path) -> None:
    """Stopping must close the project's tabs, leaving no frozen pane."""
    w, port = make_window(tmp, "stopping")
    try:
        assert _wait_for(lambda: w.tabs.count() == 2), f"tabs={w.tabs.count()}"
        pid = w.active_id
        w._stop_active()
        ok = _wait_for(lambda: w.tabs.count() == 1, timeout_s=30)
        assert ok, f"tab was not closed on stop: {w.tabs.count()}"
        assert w.tabs.currentIndex() == w.dashboard_tab_index, "did not fall back to the starter tab"
    finally:
        w.close()


def test_load_finishes_ok(tmp: Path) -> None:
    """The page itself loads, not just the URL assignment."""
    w, port = make_window(tmp, "load")
    try:
        assert _wait_for(lambda: w.tabs.count() == 2), f"tabs={w.tabs.count()}"
        done = {"ok": None}
        w.tabs.widget(1).loadFinished.connect(lambda ok: done.update(ok=ok))
        _wait_for(lambda: w.web.url().toString() == f"http://127.0.0.1:{port}/")
        _wait_for(lambda: done["ok"] is not None, timeout_s=25)
        assert done["ok"] is True, f"loadFinished={done['ok']}"
    finally:
        w.close()


def test_restart_reloads_dashboard(tmp: Path) -> None:
    """Restart must bring the dashboard back, not leave the placeholder up."""
    w, port = make_window(tmp, "restart")
    try:
        url = f"http://127.0.0.1:{port}/"
        assert _wait_for(lambda: w.tabs.count() == 2), f"tabs={w.tabs.count()}"
        _wait_for(lambda: w.web.url().toString() == url)
        # force the webview off the dashboard, then restart
        w.web.setUrl(QUrl("about:blank"))
        w._restart_active()
        ok = _wait_for(lambda: w.web.url().toString() == url)
        assert ok, f"dashboard did not come back after restart: {w.web.url().toString()!r}"
    finally:
        w.close()


def test_log_drawer_can_be_resized_and_collapsed(tmp: Path) -> None:
    """The log drawer must be draggable/collapsible like the left sidebar.

    It lives in the outer vertical splitter, so the divider can be moved and
    the drawer collapsed to zero height; the dashboard keeps the rest.
    """
    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {
                "name": "Drawer Test",
                "command": f'{sys.executable} -c "pass"',
                "url": "",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        w.resize(1200, 800)
        _spin(300)
        # the drawer is a splitter child, not a fixed-height widget
        assert w.outer_split.indexOf(w.log_view) == 1, "log drawer is not in the splitter"
        assert w.log_view.maximumHeight() > 500 or w.log_view.maximumHeight() == 16777215, (
            f"drawer is height-capped at {w.log_view.maximumHeight()}, cannot be dragged tall"
        )

        def _drawer_h() -> int:
            return w.outer_split.sizes()[1]

        # collapse via the toolbar action
        w._toggle_logs(False)
        _spin(200)
        assert _drawer_h() == 0, f"drawer did not collapse: {_drawer_h()}"
        assert w.log_view.isVisible() is False or _drawer_h() == 0

        # restore
        w._toggle_logs(True)
        _spin(200)
        assert _drawer_h() > 0, f"drawer did not restore: {_drawer_h()}"

        # and it can be dragged to an arbitrary height (the real gesture)
        w.outer_split.setSizes([400, 400])
        _spin(200)
        assert 350 <= _drawer_h() <= 450, f"drawer did not accept a dragged size: {_drawer_h()}"
    finally:
        w.close()


def test_erroring_project_logs_the_error(tmp: Path) -> None:
    """A project that dies right away is reported, not left spinning."""
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
        log_text = w.log_view.toPlainText()
        assert "exited with an error" in log_text, log_text[-300:]
    finally:
        w.close()


if __name__ == "__main__":
    import tempfile

    # `--test=NAME` runs one test only. tests/run_all.py uses this to isolate
    # GUI tests in separate processes, which is the only reliable way past
    # QtWebEngine's shutdown segfault with several views alive.
    only = None
    for arg in sys.argv[1:]:
        if arg.startswith("--test="):
            only = arg.split("=", 1)[1]

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
    if only and ran == 0:
        print(f"FAIL no such test: {only}")
        sys.exit(2)
    print("---", "FAILURES" if fails else "all passed")

    # QtWebEngine segfaults when several views are destroyed together during
    # interpreter shutdown: every test above passes, then the process dies with
    # SIGSEGV (-11) — which CI reads as a failure. There is no reliable way to
    # tear down a dozen accumulated WebEngine views in one process, so the
    # runner isolates each test in its own instead. Run standalone this prints
    # the results and then may crash on exit; the runner's exit code is the
    # authoritative one.
    sys.exit(1 if fails else 0)
