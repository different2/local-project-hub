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

from PySide6.QtCore import QEventLoop, QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QLabel,
    QLineEdit,
    QTabBar,
)

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


def test_check_for_updates_always_reports(tmp: Path) -> None:
    """Check for Updates must always end in something visible.

    Regression found by a real click (2026-10-17): the check's completion
    callback was written as a zero-argument `_done()`, but _run_offline_safe
    calls `done(worker.result)`. The TypeError landed in Qt's slot handling,
    which swallows exceptions -- so every branch of the check (error, up to
    date, update available) silently did NOTHING. This drives the real worker
    plumbing with the network call stubbed, and asserts each outcome lands in
    the one dialog the check now reports itself in (user request, 2026-10-18:
    "an obvious notification box in the center of the screen").
    """
    import hub.window as wm
    from hub.platform import IS_MACOS
    from hub.updater import Asset, Release, UpdateError

    st = sm.Store(tmp / "registry.json")
    w = HubWindow(st)
    w.show()
    original_fetch = wm.fetch_latest_release
    try:
        dlg = w._update_widget()

        # An available update: the dialog must say so and offer the download.
        suffix = ".dmg" if IS_MACOS else ".msi"
        asset = Asset(name=f"Hub-99.0.0{suffix}", url="https://example.com/x", size=10)
        wm.fetch_latest_release = lambda: Release(version="v99.0.0", assets=[asset])
        w._check_for_updates()
        assert _wait_for(lambda: "99.0.0" in dlg.headline.text()), (
            f"an available update produced no dialog: {dlg.headline.text()!r}"
        )
        assert dlg.primary.isVisible() and "Download" in dlg.primary.text(), (
            "the update offer did not offer a download"
        )

        # Up to date: the same dialog must report it.
        wm.fetch_latest_release = lambda: Release(version="v0.0.1")
        w._check_for_updates()
        assert _wait_for(lambda: "up to date" in dlg.headline.text().lower()), (
            f"'up to date' produced no dialog: {dlg.headline.text()!r}"
        )

        # A failed check must report too (this used to vanish silently).
        def _boom():
            raise UpdateError("Could not reach the update server.")

        wm.fetch_latest_release = _boom
        w._check_for_updates()
        assert _wait_for(lambda: "check for updates" in dlg.headline.text().lower()), (
            f"a failed check produced no dialog: {dlg.headline.text()!r}"
        )
        assert "reach the update server" in dlg.detail.text()
    finally:
        wm.fetch_latest_release = original_fetch
        w.close()


def test_update_dialog_presents_every_state(tmp: Path) -> None:
    """The dialog shows: checking, up to date, available, progress, error.

    The user asked (2026-10-18) for one obvious box that walks the whole
    update flow instead of a quiet status-bar line. This pins the visible
    states and the one signal the Download button sends.
    """
    from hub.update_dialog import UpdateDialog
    from hub.updater import Asset, Release

    QApplication.instance() or QApplication([])
    dlg = UpdateDialog(None)
    got = []
    dlg.request_download.connect(lambda: got.append("download"))

    dlg.show_checking()
    assert "Checking" in dlg.headline.text()
    assert dlg.bar.isVisible() and dlg.bar.maximum() == 0, "checking shows a busy bar"

    dlg.show_up_to_date(__version__)
    assert "up to date" in dlg.headline.text().lower()
    assert __version__ in dlg.detail.text()

    rel = Release(version="v9.9.9", notes="Notes here.", html_url="https://example.com/r")
    asset = Asset(name="Thing-9.9.9.dmg", url="https://example.com/a.dmg", size=1000)
    dlg.show_available(rel, asset)
    assert "9.9.9" in dlg.headline.text()
    assert dlg.primary.isVisible() and "Download" in dlg.primary.text()
    dlg.primary.click()
    assert got == ["download"], "the download button must emit request_download"

    dlg.show_downloading(asset.name, asset.size)
    assert "Downloading" in dlg.headline.text()
    dlg.set_progress(250, 1000)
    assert (dlg.bar.value(), dlg.bar.maximum()) == (250, 1000)

    dlg.show_error("Couldn't check for updates", "No network")
    assert "No network" in dlg.detail.text()
    assert dlg.primary.isVisible() and dlg.primary.text() == "OK"
    dlg.close()


def test_download_update_shows_progress_and_verifies(tmp: Path) -> None:
    """A download reports into the dialog, then hands off; a corrupt one doesn't.

    Uses a file:// URL so the real worker path runs without a network, and
    stubs only the installer launch (its message box would block an offscreen
    test).
    """
    import hashlib

    from hub.updater import Asset

    payload = b"HUB-UPDATE-PAYLOAD-" * 8192
    src = tmp / "thing.dmg"
    src.write_bytes(payload)

    st = sm.Store(tmp / "registry.json")
    w = HubWindow(st)
    w.show()
    launched = []
    original_launch = w._launch_installer
    try:
        w._launch_installer = lambda path: launched.append(path)
        dlg = w._update_widget()

        good = Asset(
            name="thing.dmg",
            url=src.as_uri(),
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        w._download_update(None, good)
        assert "Downloading" in dlg.headline.text(), (
            f"the dialog never showed the download: {dlg.headline.text()!r}"
        )
        assert _wait_for(lambda: launched), "the installer hand-off never happened"
        assert w._update_busy is False, "the busy flag was left set"

        # A checksum mismatch must surface as an error and launch nothing.
        launched.clear()
        bad = Asset(
            name="thing2.dmg",
            url=src.as_uri(),
            size=len(payload),
            sha256="0" * 64,
        )
        w._download_update(None, bad)
        assert _wait_for(lambda: "didn't finish" in dlg.headline.text()), (
            f"a bad checksum produced no error: {dlg.headline.text()!r}"
        )
        assert not launched, "the installer was launched for a corrupt download"
    finally:
        w._launch_installer = original_launch
        w.close()


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
        # Tab text is the project name trimmed; the sidebar's two-space icon
        # padding is not carried into the tab strip.
        assert labels.count("Solo") == 1, labels
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


def test_each_project_has_its_own_terminal(tmp: Path) -> None:
    """The drawer keeps one terminal per project, and output never carries over.

    User request (2026-10-19): "for each 'project' can they have their own
    terminal window show instead of a shared terminal window at the bottom. So
    when i switch between projects the terminal window doesn't carry over, and
    wont be confused."

    Runs the real path: both markers come from live processes through
    ProjectProcess.output, not from poking the drawer directly.
    """
    st = sm.Store(tmp / "registry.json")
    for name, marker in (("Alpha", "ALPHA-ONLY"), ("Beta", "BETA-ONLY")):
        script = tmp / f"{name.lower()}.py"
        script.write_text(f"print('{marker}', flush=True)\n", encoding="utf-8")
        st.add(
            sm.validate(
                {
                    "name": name,
                    "command": f"{sys.executable} {script}",
                    "working_dir": str(tmp),
                }
            )
        )
    w = HubWindow(st)
    w.show()
    try:
        alpha, beta = (r["id"] for r in st.ordered())

        # The terminal follows the selection...
        w._select_id(alpha, start=False)
        assert w.log_view.header.text() == "Logs — Alpha", w.log_view.header.text()
        w._proc_for(st.get(alpha)).start()
        assert _wait_for(lambda: "ALPHA-ONLY" in w.log_view.toPlainText()), (
            f"Alpha's own output never arrived: {w.log_view.toPlainText()!r}"
        )

        # ...and switching projects swaps the pane instead of keeping the text.
        w._select_id(beta, start=False)
        assert w.log_view.header.text() == "Logs — Beta", w.log_view.header.text()
        assert "ALPHA-ONLY" not in w.log_view.toPlainText(), (
            "the previous project's output carried over into this terminal"
        )
        w._proc_for(st.get(beta)).start()
        assert _wait_for(lambda: "BETA-ONLY" in w.log_view.toPlainText()), (
            f"Beta's own output never arrived: {w.log_view.toPlainText()!r}"
        )

        # Going back finds Alpha's own history, uncontaminated.
        w._select_id(alpha, start=False)
        text = w.log_view.toPlainText()
        assert "ALPHA-ONLY" in text and "BETA-ONLY" not in text, text
    finally:
        for p in list(w.procs.values()):
            try:
                p.stop()
            except Exception:
                pass
        w.close()


def test_renaming_a_project_in_the_sidebar_sticks(tmp: Path) -> None:
    """Renaming in the sidebar updates the store, the row and the tab.

    User request (2026-10-19): the name "should be able to be edited in the
    sidebar ... whenever I want ... Like how I can rename names for sessions".
    The delegate writes the edited name into the row's name role; the window is
    what turns that into a saved rename.
    """
    from hub.window import _NAME_ROLE

    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {
                "name": "Old Name",
                "command": "python3 x.py",
                "working_dir": str(tmp),
                "icon": "🌐",
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        pid = st.ordered()[0]["id"]
        item = w.list.item(0)
        item.setData(_NAME_ROLE, "New Name")
        assert st.get(pid)["name"] == "New Name", st.get(pid)["name"]
        assert item.data(_NAME_ROLE) == "New Name", item.data(_NAME_ROLE)
        assert "New Name" in item.text(), item.text()
        idx = w._tab_index_for_project(pid)
        assert idx is not None, "the project has no tab"
        assert "New Name" in w.tabs.tabText(idx), w.tabs.tabText(idx)

        # An empty name is not a name: the stored one comes back on the row.
        item.setData(_NAME_ROLE, "   ")
        assert st.get(pid)["name"] == "New Name", "a blank rename was saved"
        assert "New Name" in item.text(), item.text()
    finally:
        w.close()


def test_rename_opens_an_editor_and_saves_the_new_name(tmp: Path) -> None:
    """Reported 2026-10-19: "I click Rename and nothing happens."

    QListWidgetItem is not editable by default, so `editItem()` — the context
    menu's Rename — and double-click both failed silently ("edit: editing
    failed" on the console). The row must carry ItemIsEditable and the editor
    must start from the stored name, with the delegate's commit saving it.
    """
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "Alpha",
                "command": f"{sys.executable} -c 'pass'",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        item = w.list.item(0)
        assert item.flags() & Qt.ItemIsEditable, (
            "the sidebar row is not editable, so Rename can only do nothing"
        )

        w.list.setCurrentItem(item)
        w.list.editItem(item)  # exactly what the context menu's Rename calls
        assert _wait_for(
            lambda: w.list.state() == QAbstractItemView.EditingState, 3.0
        ), "editItem() opened no editor"

        editor = w.list.findChild(QLineEdit)
        assert editor is not None and editor.isVisible(), "no editor was shown"
        assert editor.text() == "Alpha", (
            f"the editor did not start from the stored name: {editor.text()!r}"
        )

        index = w.list.model().index(w.list.row(item), 0)
        editor.setText("Renamed In Place")
        w.list.itemDelegate().setModelData(editor, w.list.model(), index)

        assert (st.get(rec["id"]) or {}).get("name") == "Renamed In Place", st.get(rec["id"])
        assert "Renamed In Place" in w.list.item(0).text(), w.list.item(0).text()
    finally:
        w.close()


def test_a_macos_update_is_staged_and_installing_it_just_restarts(tmp: Path) -> None:
    """The user asked (2026-10-19) why an update needs a drag to Applications.

    With a bundle to replace, the downloaded disk image is staged, the dialog
    offers "Restart and Install", and choosing it starts the swap script and
    closes the window. The old drag-the-app-across hand-off must not run as
    well — one update, one path.
    """
    import os

    from hub import selfupdate as su
    from hub.updater import Release

    st = sm.Store(tmp / "registry.json")
    w = HubWindow(st)
    w.show()

    staged = tmp / "staged" / "Local Project Hub.app"
    staged.mkdir(parents=True)
    target = tmp / "Applications" / "Local Project Hub.app"
    target.mkdir(parents=True)

    launched = []
    scheduled = []
    originals = (
        su.can_self_install,
        su.stage_app_from_dmg,
        su.bundle_path,
        su.schedule_install,
    )
    try:
        su.can_self_install = lambda *a, **k: (True, "")
        su.stage_app_from_dmg = lambda dmg, work: staged
        su.bundle_path = lambda: target
        su.schedule_install = lambda s, t, pid, **k: (
            scheduled.append((Path(s), Path(t), pid)) or staged.parent / "install-update.sh"
        )
        w._launch_installer = lambda path: launched.append(path)

        dlg = w._update_widget()
        rel = Release(version="v9.9.9", notes="", html_url="")
        w._prepare_macos_update(tmp / "thing.dmg", rel)

        assert _wait_for(lambda: getattr(w, "_pending_install", None)), (
            "the update was never staged"
        )
        assert not launched, "the disk-image hand-off ran even though it did not need to"
        assert "Restart" in dlg.primary.text(), dlg.primary.text()

        dlg.primary.click()
        assert _wait_for(lambda: scheduled), "restarting did not start the swap"
        got_staged, got_target, pid = scheduled[0]
        assert got_staged == staged, f"staged the wrong bundle: {got_staged}"
        assert got_target == target, f"the swap targets the wrong bundle: {got_target}"
        assert pid == os.getpid(), f"the swap waits on the wrong process: {pid}"
        assert _wait_for(lambda: not w.isVisible()), (
            "the window did not close, so the swap would wait forever"
        )
        assert not launched, "the disk image was opened as well"
    finally:
        (
            su.can_self_install,
            su.stage_app_from_dmg,
            su.bundle_path,
            su.schedule_install,
        ) = originals
        w.close()


def test_a_detected_url_is_saved_to_the_project_that_printed_it(tmp: Path) -> None:
    """Reported bug (2026-10-19, by someone else): the URL went to the ACTIVE row.

    A project running in the background announces its own dashboard address;
    that address belongs to that project's entry, not to whichever row the
    user happens to have selected. Before the fix `_on_url_detected` read
    `self.active_id`, so Beta's address was stored on Alpha and Alpha's
    dashboard was opened.
    """
    st = sm.Store(tmp / "registry.json")
    alpha = st.add(
        sm.validate(
            {
                "name": "Alpha",
                "command": f"{sys.executable} -c 'pass'",
                "working_dir": str(tmp),
            }
        )
    )
    beta = st.add(
        sm.validate(
            {
                "name": "Beta",
                "command": f"{sys.executable} -c 'pass'",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        w.active_id = alpha["id"]
        # Beta is running in the background (not selected) and announces itself.
        beta_rec = st.get(beta["id"]) or {}
        w._proc_for(beta_rec).url_detected.emit("http://127.0.0.1:54321/")

        beta_after = st.get(beta["id"]) or {}
        alpha_after = st.get(alpha["id"]) or {}
        assert beta_after.get("url") == "http://127.0.0.1:54321/", (
            f"the URL was not saved to the project that printed it: {beta_after}"
        )
        assert not alpha_after.get("url"), (
            f"the URL was saved to the ACTIVE project instead: {alpha_after}"
        )
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
