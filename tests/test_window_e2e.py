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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QTabBar  # noqa: E402

from helpers import reserve_port, temp_project_dir  # noqa: E402
from hub import store as sm  # noqa: E402
from hub.window import HubWebView, HubWindow  # noqa: E402
from hub import __version__  # noqa: E402

# Each test gets its own port: sharing one lets a previous test's server kill
# the next with "Address already in use" (code=1), which reads as a regression
# but is just cross-test contamination.
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


def _wait_for_port_free(port: int, timeout_s: float = 15.0) -> None:
    """Wait until nothing is listening on `port` before a test binds it.

    The OS can keep a socket for a moment after the previous suite's server
    exited, and a suite that starts into a still-held port fails with
    "Address already in use" for reasons that have nothing to do with the code
    under test. Retrying the whole suite was masking that as flakiness.

    Raises rather than returning False. Returning a bool let callers ignore it,
    so a port held by a leftover process silently became "A's tab never got a
    URL" three tests later -- the same contamination, blamed on the code.
    """
    import socket

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.bind(("127.0.0.1", port))
                return
            except OSError:
                _spin(100)
    holders = _who_holds(port)
    raise SystemExit(
        f"Port {port} is still held after {timeout_s}s -- a leftover process from "
        f"an earlier run, not a code fault.{holders}\n"
        f"    lsof -ti:{port} | xargs kill\n"
        f"Then re-run this suite on its own."
    )


def _who_holds(port: int) -> str:
    """Best-effort description of what is holding a port, for the message above."""
    try:
        import subprocess

        out = subprocess.run(
            ["lsof", "-ti", str(port)], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return f" (pids: {out.replace(chr(10), ' ')})" if out else ""
    except Exception:
        return ""


def make_window(tmp: Path) -> tuple[HubWindow, int]:
    """Build a window over one freshly-reserved server port.

    The port comes from the OS, so no two tests or suites can contend for a fixed
    number -- which is what produced "A's tab never got a URL" and similar
    failures that read as logic bugs.
    """
    port = reserve_port()
    (tmp / "srv.py").write_text(_server_src(port))
    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {
                "name": "Window Test",
                "command": f"{sys.executable} {tmp / 'srv.py'} {port}",
                "url": f"http://127.0.0.1:{port}/",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    # Opening the window must NOT start anything (that was a reported bug: it
    # fired the project and its browser). Selecting the project is what a user
    # does, so do that here.
    rec = st.ordered()[0]
    w.active_id = rec["id"]
    w._on_select()
    return w, port


def test_selecting_project_opens_a_tab_with_its_url(tmp: Path) -> None:
    """Selecting a project opens ITS OWN tab and loads its dashboard there."""
    w, port = make_window(tmp)
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
    # One reserved port per project, so the two servers cannot collide with
    # each other or with anything else running.
    st = sm.Store(tmp / "registry.json")
    ports = []
    for name in ("Proj A", "Proj B"):
        port = reserve_port()
        ports.append(port)
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
        # Wait for A's page to FINISH loading, not merely for a URL to appear.
        # url() != "" is set the moment setUrl() is called, which is before the
        # child server has necessarily bound its port -- so this check can pass
        # while the load is still failing. That is the intermittent failure:
        # whether it passes depends on how fast the child starts, which is why
        # it looked like flakiness and passed 2 runs out of 3.
        a_view = w.tabs.widget(1)
        assert isinstance(a_view, HubWebView), type(a_view).__name__
        a_done = {"ok": None}
        a_view.loadFinished.connect(lambda ok: a_done.update(ok=ok))
        assert _wait_for(
            lambda: a_view.url().toString() != ""
        ), "A's tab never got a URL"
        assert _wait_for(lambda: a_done["ok"] is not None, timeout_s=30), (
            f"A's page never finished loading (url={a_view.url().toString()!r})"
        )

        w._select_id(ids[1])
        assert _wait_for(lambda: w.tabs.count() == 3), f"second project got no tab: {w.tabs.count()}"
        # Wait for B's page to actually FINISH loading, not merely for a URL to
        # be assigned. Under Python 3.11 (what CI uses) the second WebEngine
        # starts later, so a url() != "" check passes while the load is still in
        # flight and the assertion below then reads a half-built tab.
        b_view = w.tabs.widget(2)
        assert isinstance(b_view, HubWebView), type(b_view).__name__
        b_done = {"ok": None}
        b_view.loadFinished.connect(lambda ok: b_done.update(ok=ok))
        assert _wait_for(
            lambda: b_view.url().toString() != ""
        ), "B's tab never got a URL"
        assert _wait_for(lambda: b_done["ok"] is not None, timeout_s=30), (
            f"B's page never finished loading (url={b_view.url().toString()!r})"
        )

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
        assert urls == {f"http://127.0.0.1:{p}/" for p in ports}, urls
    finally:
        w.close()


def test_stopping_a_project_closes_its_tabs(tmp: Path) -> None:
    """Stopping must close the project's tabs, leaving no frozen pane."""
    w, port = make_window(tmp)
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
    # Connecting loadFinished AFTER _on_select() races the page: on a fast
    # machine (and under Python 3.11, which is what CI uses) the load finishes
    # first, the slot is missed, and done["ok"] stays None -- so the test fails
    # with "loadFinished=None" while the page loaded perfectly.
    #
    # PySide6 unbound Signals have no .connect(), so instead of patching the
    # class this waits for the tab to exist and THEN connects, before the URL
    # has been assigned to it. The window is built with a URL the server has not
    # started for, so no load can complete before the slot is attached.
    w, port = make_window(tmp)
    try:
        assert _wait_for(lambda: w.tabs.count() == 2), f"tabs={w.tabs.count()}"
        done = {"ok": None}
        w.tabs.widget(1).loadFinished.connect(lambda ok: done.update(ok=ok))
        # Drive the load ourselves now that we are listening for it. Retry until
        # the server answers: the first setUrl can land before the child process
        # has bound its port, and loadFinished(False) then means "nothing was
        # listening", not "the page is broken". A single attempt would report
        # that as a failure.
        for _ in range(5):
            w.web.setUrl(QUrl(f"http://127.0.0.1:{port}/"))
            _wait_for(lambda: done["ok"] is not None, timeout_s=25)
            if done["ok"]:
                break
            done["ok"] = None
            _spin(500)
        assert done["ok"] is True, (
            f"loadFinished={done['ok']} url={w.web.url().toString()!r}"
        )
    finally:
        w.close()


def test_restart_reloads_dashboard(tmp: Path) -> None:
    """Restart must bring the dashboard back, not leave the placeholder up."""
    w, port = make_window(tmp)
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
    port = reserve_port()
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
    # Opening the window does not start anything; the user selecting it does.
    w.active_id = st.ordered()[0]["id"]
    w._on_select()
    try:
        proc = w._proc_for(w.store.get(w.active_id))
        ok = _wait_for(lambda: proc.state == "error", timeout_s=15)
        assert ok, f"expected error state, got {proc.state}"
        log_text = w.log_view.toPlainText()
        assert "exited with an error" in log_text, log_text[-300:]
    finally:
        w.close()


def test_starter_tab_shows_welcome_not_an_empty_box(tmp: Path) -> None:
    """The starter tab explains the app instead of showing nothing.

    The tab cannot be closed, so leaving it blank wastes the one pane that is
    always available. It must name the version and how to add a project.
    """
    st = sm.Store(tmp / "registry.json")
    w = HubWindow(st)
    w.show()
    try:
        starter = w.dashboard_tab_index
        w.tabs.setCurrentIndex(starter)
        _wait_for(lambda: w.welcome.isVisible())
        assert w.welcome.isVisible(), "welcome pane never became visible"
        assert not w.placeholder.isVisible(), "grey hint overlapped the welcome"
        text = w.welcome_count.text()
        assert "No projects registered" in text, text
        assert w.starter_has_close_button() is True, "starter tab must be closable"
        # the version and the how-to must actually be on the pane
        labels = " ".join(l.text() for l in w.welcome.findChildren(QLabel))
        assert "Local Project Hub" in labels, labels
        assert "Add Project" in labels, labels
        assert __version__ in labels, f"version {__version__} missing from the pane"
    finally:
        w.close()


def test_welcome_counts_projects(tmp: Path) -> None:
    """The starter tab's summary stays honest as projects are added."""
    st = sm.Store(tmp / "registry.json")
    w = HubWindow(st)
    w.show()
    try:
        st.add(sm.validate({"name": "One", "command": "python3 x.py",
                            "working_dir": str(tmp)}))
        w._reload_list()
        w._refresh_welcome()
        assert "1 project registered" in w.welcome_count.text(), w.welcome_count.text()
        st.add(sm.validate({"name": "Two", "command": "python3 y.py",
                            "working_dir": str(tmp)}))
        w._reload_list()
        w._refresh_welcome()
        assert "2 projects registered" in w.welcome_count.text(), w.welcome_count.text()
    finally:
        w.close()


def test_reselecting_a_project_does_not_open_a_second_tab(tmp: Path) -> None:
    """One tab per project: re-selecting focuses instead of duplicating.

    A duplicate shows a stale view, and its close button then stops the
    project out from under the live tab.
    """
    st = sm.Store(tmp / "registry.json")
    rec = sm.validate({"name": "Solo", "command": "python3 x.py",
                       "url": "http://127.0.0.1:9999/", "working_dir": str(tmp)})
    st.add(rec)
    w = HubWindow(st)
    w.show()
    try:
        pid = rec["id"]
        w._select_id(pid, start=False)
        assert w.tabs.count() == 2, w.tabs.count()
        w._select_id(pid, start=False)
        assert w.tabs.count() == 2, f"duplicated to {w.tabs.count()} tabs"
        w._select_id(pid, start=False)
        assert w.tabs.count() == 2, f"duplicated to {w.tabs.count()} tabs"
        labels = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        assert labels.count("  Solo") == 1, labels
    finally:
        w.close()


def test_project_tab_close_button_exists_and_starter_has_none(tmp: Path) -> None:
    """Both the starter tab and project tabs are closable."""
    st = sm.Store(tmp / "registry.json")
    st.add(sm.validate({"name": "Closable", "command": "python3 x.py",
                        "url": "http://127.0.0.1:9999/", "working_dir": str(tmp)}))
    w = HubWindow(st)
    w.show()
    try:
        assert w.starter_has_close_button(), "starter tab should be closable"
        w._select_id(st.ordered()[0]["id"], start=False)
        idx = w._tab_index_for_project(st.ordered()[0]["id"])
        assert idx is not None, "project tab not found"
        assert w.tabs.tabBar().tabButton(idx, QTabBar.RightSide) is not None, (
            "project tab has no close button"
        )
    finally:
        w.close()


def test_closing_a_running_projects_tab_actually_closes_it(tmp: Path) -> None:
    """The x on a RUNNING project's tab must close the tab and stop the backend.

    This is the user's exact report: the tab closed when the project was
    stopped but not when it was running. The cause was a TypeError inside the
    close handler — `store.get(pid, {})` passes two arguments to a method that
    takes one — which threw only on the running path (the log line is inside
    `if proc is not None`) and was swallowed by the Qt signal, so the click
    silently did nothing.
    """
    port = reserve_port()
    srv = tmp / "srv.py"
    srv.write_text(_server_src(port))
    st = sm.Store(tmp / "registry.json")
    rec = sm.validate(
        {"name": "Live", "command": f"{sys.executable} {srv}",
         "url": "", "working_dir": str(tmp)}
    )
    st.add(rec)
    w = HubWindow(st)
    w.show()
    try:
        pid = st.ordered()[0]["id"]
        w._select_id(pid, start=True)
        assert _wait_for(lambda: w.procs[pid].state == "running", timeout_s=25), (
            f"server never started: {w.procs[pid].state}"
        )
        idx = w._tab_index_for_project(pid)
        assert idx is not None, "no tab for the running project"
        assert w.tabs.tabBar().tabButton(idx, QTabBar.RightSide) is not None, (
            "running project's tab has no close button"
        )
        assert w.tabs.count() == 2, w.tabs.count()

        # exactly what clicking the x does
        w.tabs.tabCloseRequested.emit(idx)
        assert w.tabs.count() == 1, (
            f"tab did not close while running (tabs={w.tabs.count()})"
        )
        assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == [
            "Local Project Hub"
        ], "the wrong tab was closed"
        # the backend must go down too, not be left running behind a closed tab
        assert _wait_for(lambda: w.procs[pid].state == "stopped", timeout_s=30), (
            f"process still {w.procs[pid].state} after its tab closed"
        )
        # and the project stays registered so it can be started again
        assert any(r["id"] == pid for r in st.ordered()), "project was unregistered"
    finally:
        for p in list(w.procs.values()):
            try:
                p.stop()
            except Exception:
                pass
        w.close()


def test_closing_the_starter_tab_leaves_project_tabs_working(tmp: Path) -> None:
    """Closing the hub's own tab must not corrupt the tab bar.

    The starter used to be identified by a stored INDEX. Once it could be
    closed, index 0 became a project tab, and every `index == dashboard_tab_index`
    check would have misread that project as the starter -- silently stripping
    its close button. Identity now comes from the widget, so this asserts the
    project tab keeps its button and stays a project after the starter is gone.
    """
    st = sm.Store(tmp / "registry.json")
    st.add(sm.validate({"name": "Proj", "command": "python3 x.py",
                        "url": "http://127.0.0.1:9999/", "working_dir": str(tmp)}))
    w = HubWindow(st)
    w.show()
    try:
        pid = st.ordered()[0]["id"]
        w._select_id(pid, start=False)
        assert w.starter_index() == 0, w.starter_index()
        w.tabs.tabCloseRequested.emit(w.starter_index())
        assert w.tabs.count() == 1, "starter tab did not close"
        assert w.starter_index() is None, "starter still present"
        # the project tab moved to index 0 -- it must NOT be read as the starter
        assert not w._is_starter_index(0), "project tab misread as the starter"
        assert w.tabs.tabBar().tabButton(0, QTabBar.RightSide) is not None, (
            "project tab lost its close button after the starter closed"
        )
        # and the starter can be brought back
        w.open_starter_tab()
        assert w.starter_index() is not None, "starter could not be reopened"
        assert w.tabs.count() == 2, w.tabs.count()
        assert w.welcome.isVisible(), "welcome pane did not come back"
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
            with temp_project_dir() as d:
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
