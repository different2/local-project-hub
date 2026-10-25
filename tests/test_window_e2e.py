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
from hub import startpage  # noqa: E402
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
    # fired the project and its browser). Neither does selecting it — these
    # tests are about the dashboard, so start it explicitly, the way pressing
    # Start on the project's start page does.
    rec = st.ordered()[0]
    w._select_id(rec["id"], start=True)
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
        if IS_MACOS or sys.platform.startswith("win"):
            assert dlg.primary.isVisible() and "Download" in dlg.primary.text(), (
                "the update offer did not offer a download"
            )
        else:
            # Linux uses manual/APT updates. The MSI fixture must not become
            # an install action merely because this is a non-Mac platform.
            assert dlg.primary.isVisible() and dlg.primary.text() == "OK", (
                "Linux must show a dismissible result, not offer the MSI fixture"
            )
            assert "No installer" in dlg.detail.text(), dlg.detail.text()

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
    """Opening and starting a project loads its dashboard in its own tab."""
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


def _wait_for_page_text(view, needle: str, timeout_s: float = 10.0) -> bool:
    """True once the tab's rendered DOM contains `needle`.

    setHtml() is asynchronous, so a click issued right after it lands on an
    empty document. The DOM is read through document.title because this
    PySide6 build's runJavaScript takes no Python callback.
    """
    import json

    script = (
        "document.title = (document.body && "
        f"document.body.innerText.includes({json.dumps(needle)})) ? 'HUB_READY' : 'HUB_WAIT'"
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        view.page().runJavaScript(script)
        _spin(200)
        if view.title() == "HUB_READY":
            return True
    return False


def _page_html(view) -> str:
    """The hub page this tab was last asked to render.

    Deliberately not read back out of the DOM: this PySide6 build's
    runJavaScript takes no Python callback, so the page's own copy is kept as a
    property when it is set. A test that needs PROOF the button works clicks it
    and watches the project start (see test_pressing_start_on_the_page_runs...).
    """
    return view.property("hub_page_html") or ""


def test_selecting_a_project_shows_a_start_page_and_runs_nothing(tmp: Path) -> None:
    """Reported 2026-10-20: selecting a project should not start it.

    The tab opens on a page with the project's name, its command and one Start
    button — the same look as the hub's own tab, not a blank white pane. The
    project's process must still be stopped, and nothing may be listening on
    its port.
    """
    port = reserve_port()
    srv = tmp / "srv.py"
    srv.write_text(_server_src(port))
    marker = tmp / "ran.txt"
    st = sm.Store(tmp / "registry.json")
    rec = sm.validate(
        {
            "name": "Quiet One",
            "command": f"{sys.executable} -c \"open(r'{marker}','w').write('ran')\"",
            "url": f"http://127.0.0.1:{port}/",
            "working_dir": str(tmp),
        }
    )
    rec = st.add(rec)  # add() assigns the id; the validated dict has none
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(rec["id"], start=False)  # exactly what clicking the row does
        assert _wait_for(lambda: w.tabs.count() == 2), "no tab opened for the project"
        view = w.tabs.widget(1)
        proc = w._proc_for(rec)

        assert _wait_for_page_text(view, "Start"), (
            "the project tab did not show a start page"
        )
        page = _page_html(view)
        assert view.url().toString() in ("", "about:blank"), (
            f"the tab is not showing a hub page: {view.url().toString()!r}"
        )
        assert rec["name"] in page, "the start page does not name the project"
        assert "Nothing runs until you press Start" in page, page[:600]
        assert proc.state == "stopped", f"selecting the project started it: {proc.state}"
        assert not marker.exists(), "selecting the project ran its command"
    finally:
        for p in list(w.procs.values()):
            try:
                p.stop()
            except Exception:
                pass
        w.close()


def test_pressing_start_on_the_page_runs_the_project(tmp: Path) -> None:
    """The Start button's link must reach the window and launch the project."""
    port = reserve_port()
    srv = tmp / "srv.py"
    srv.write_text(_server_src(port))
    st = sm.Store(tmp / "registry.json")
    rec = sm.validate(
        {
            "name": "Press Start",
            "command": f"{sys.executable} {srv} {port}",
            "url": f"http://127.0.0.1:{port}/",
            "working_dir": str(tmp),
        }
    )
    rec = st.add(rec)  # add() assigns the id; the validated dict has none
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(rec["id"], start=False)
        assert _wait_for(lambda: w.tabs.count() == 2), "no tab opened"
        view = w.tabs.widget(1)
        proc = w._proc_for(rec)
        assert proc.state == "stopped", proc.state

        # Click the real button. A custom scheme would not work here
        # (QtWebEngine drops those clicks without asking the page), which is why
        # the page links to hub.invalid.
        assert _wait_for_page_text(view, "Start"), "the start page never rendered"
        view.page().runJavaScript("document.querySelector('a.btn').click()")

        assert _wait_for(lambda: proc.state in ("starting", "running"), 10.0), (
            f"pressing Start did nothing: {proc.state}"
        )
        assert _wait_for(
            lambda: view.url().toString() == f"http://127.0.0.1:{port}/", 25.0
        ), f"dashboard never loaded: {view.url().toString()!r}"
    finally:
        for p in list(w.procs.values()):
            try:
                p.stop()
            except Exception:
                pass
        w.close()


def test_a_project_without_a_dashboard_says_it_is_running(tmp: Path) -> None:
    """A bot has no page to show: after Start its tab says "Project is running"."""
    st = sm.Store(tmp / "registry.json")
    rec = sm.validate(
        {
            "name": "Just A Bot",
            "command": f"{sys.executable} -c \"import time; time.sleep(60)\"",
            "url": "",
            "working_dir": str(tmp),
        }
    )
    rec = st.add(rec)  # add() assigns the id; the validated dict has none
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(rec["id"], start=False)
        assert _wait_for(lambda: w.tabs.count() == 2), "no tab opened"
        view = w.tabs.widget(1)
        proc = w._proc_for(rec)

        assert _wait_for_page_text(view, "Start"), "the start page never rendered"
        view.page().runJavaScript("document.querySelector('a.btn').click()")
        assert _wait_for(lambda: proc.state == "running", 20.0), (
            f"the bot never started: {proc.state}"
        )
        assert _wait_for_page_text(view, "Project is running"), (
            "a running project with no dashboard did not get its status card"
        )
        assert "Start</a>" not in _page_html(view), "the Start button is still there"
    finally:
        for p in list(w.procs.values()):
            try:
                p.stop()
            except Exception:
                pass
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
        dashboards = [f"http://127.0.0.1:{p}/" for p in ports]

        w._select_id(ids[0])
        assert _wait_for(lambda: w.tabs.count() == 2), f"tabs={w.tabs.count()}"
        # Opening a project shows its start page; the dashboard appears only
        # once the project is running AND its port answers. about:blank counts
        # as "a URL", so waiting for url() != "" would pass on the start page.
        a_view = w.tabs.widget(1)
        assert isinstance(a_view, HubWebView), type(a_view).__name__
        a_done = {"ok": None}
        a_view.loadFinished.connect(lambda ok: a_done.update(ok=ok))
        assert _wait_for(lambda: a_view.url().toString() == dashboards[0], timeout_s=30), (
            f"A's tab never opened its dashboard (url={a_view.url().toString()!r})"
        )
        assert _wait_for(lambda: a_done["ok"] is not None, timeout_s=30), (
            f"A's page never finished loading (url={a_view.url().toString()!r})"
        )

        w._select_id(ids[1])
        assert _wait_for(lambda: w.tabs.count() == 3), f"second project got no tab: {w.tabs.count()}"
        b_view = w.tabs.widget(2)
        assert isinstance(b_view, HubWebView), type(b_view).__name__
        b_done = {"ok": None}
        b_view.loadFinished.connect(lambda ok: b_done.update(ok=ok))
        assert _wait_for(lambda: b_view.url().toString() == dashboards[1], timeout_s=30), (
            f"B's tab never opened its dashboard (url={b_view.url().toString()!r})"
        )
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
        assert urls == set(dashboards), urls
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
    """A real Restart restores the dashboard without blaming the old child."""
    from PySide6.QtCore import QProcess

    w, port = make_window(tmp)
    pid = w.active_id
    assert pid is not None
    proc = w.procs[pid]
    states = []
    exits = []
    proc.state_changed.connect(states.append)
    try:
        url = f"http://127.0.0.1:{port}/"
        view = w._view_for(pid)
        assert _wait_for_page_text(view, "HUB-WINDOW-TEST"), "initial dashboard never rendered"
        old = proc.proc
        old_pid = int(old.processId())
        assert old_pid > 0
        old.finished.connect(lambda code, status: exits.append(code))
        # Drive the actual action, not a synthetic state signal. Moving away
        # from the dashboard also proves Restart reloads it rather than merely
        # leaving the previous page visible while the child changes.
        view.setUrl(QUrl("about:blank"))
        assert w.act_restart.isEnabled(), "Restart is disabled for a running project"
        w.act_restart.trigger()
        assert _wait_for(
            lambda: proc.proc is not old and proc.state == "running", 30.0
        ), f"no replacement: states={states}, exits={exits}"
        assert int(proc.proc.processId()) not in (0, old_pid), "Restart reused the old child"
        assert exits and old.state() == QProcess.NotRunning, f"old child never exited: {exits}"
        assert _wait_for_page_text(view, "HUB-WINDOW-TEST"), "replacement dashboard never rendered"
        assert view.url().toString() == url
        assert w.tabs.currentWidget() is view and view.isVisible()
        assert view.width() > 0 and view.height() > 0
        terminal = w.log_view._edit_for(pid).toPlainText()
        assert "[hub] process exited (code=" in terminal, terminal
        assert "exited with an error" not in terminal, (
            f"Restart mislabeled its intentional exit: states={states}, exits={exits}\n{terminal}"
        )
        assert "error" not in states, states
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc.state() == QProcess.NotRunning), "fixture child leaked"
        w.close()


def test_restart_replacement_startup_failure_still_reports_error(tmp: Path) -> None:
    """Restart's expected old exit must not hide a broken replacement."""
    from PySide6.QtCore import QProcess
    from hub.readiness import tcp_open

    w, port = make_window(tmp)
    pid = w.active_id
    assert pid is not None
    proc = w.procs[pid]
    states = []
    running_pids = []
    old_exit_errors = []
    proc.state_changed.connect(states.append)
    proc.state_changed.connect(
        lambda state: running_pids.append(int(proc.proc.processId())) if state == "running" else None
    )
    try:
        view = w._view_for(pid)
        assert view is not None
        assert _wait_for_page_text(view, "HUB-WINDOW-TEST"), "initial dashboard never rendered"
        old = proc.proc
        assert old is not None
        old_pid = int(old.processId())
        old.finished.connect(lambda code, status: old_exit_errors.append(states.count("error")))
        # The executable really starts, then the replacement fails during its
        # own startup. No synthetic error state or mocked start/finish handler.
        (tmp / "srv.py").write_text(
            "print('REPLACEMENT_STARTUP_FAILED', flush=True)\nraise SystemExit(23)\n"
        )
        assert w.act_restart.isEnabled()
        w.act_restart.trigger()
        assert _wait_for(
            lambda: proc.proc is not old and proc.proc.state() == QProcess.NotRunning, 30.0
        ), f"replacement did not finish: states={states}, pids={running_pids}"
        assert running_pids and running_pids[-1] not in (0, old_pid), running_pids
        assert proc.proc.exitCode() == 23, proc.proc.exitCode()
        terminal = w.log_view._edit_for(pid).toPlainText()
        assert "REPLACEMENT_STARTUP_FAILED" in terminal, terminal
        assert proc.state == "error", f"replacement failure hidden: states={states}\n{terminal}"
        assert old_exit_errors == [0], f"the deliberate old exit was blamed: {old_exit_errors}\n{terminal}"
        assert states.count("error") == 1, f"expected one replacement error: {states}\n{terminal}"
        assert terminal.count("exited with an error") == 1, terminal
        assert w._view_for(pid) is view, "failure discarded the project's terminal tab"
        assert _wait_for(lambda: not tcp_open("127.0.0.1", port, timeout=0.1)), "fixture listener leaked"
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc.state() == QProcess.NotRunning), "fixture child leaked"
        w.close()


def test_unrequested_termination_still_logs_error(tmp: Path) -> None:
    """The same SIGTERM without Stop/Restart intent is a genuine error."""
    from PySide6.QtCore import QProcess
    from hub.readiness import tcp_open

    w, port = make_window(tmp)
    pid = w.active_id
    assert pid is not None
    proc = w.procs[pid]
    states = []
    proc.state_changed.connect(states.append)
    try:
        view = w._view_for(pid)
        assert view is not None
        assert _wait_for_page_text(view, "HUB-WINDOW-TEST"), "initial dashboard never rendered"
        # Terminate only our real child directly; bypassing ProjectProcess.stop
        # is intentional, because no user lifecycle request precedes this exit.
        child = proc.proc
        assert child is not None
        if sys.platform.startswith("win"):
            child.kill()  # console children do not receive terminate's WM_CLOSE
        else:
            child.terminate()  # the same SIGTERM sent by Stop/Restart
        assert _wait_for(lambda: child.state() == QProcess.NotRunning), "owned child did not exit"
        assert child.exitCode() != 0, child.exitCode()
        terminal = w.log_view._edit_for(pid).toPlainText()
        assert proc.state == "error" and states.count("error") == 1, (proc.state, states, terminal)
        assert terminal.count("exited with an error") == 1, terminal
        assert w._view_for(pid) is view, "an unexpected exit closed the terminal tab"
        assert _wait_for(lambda: not tcp_open("127.0.0.1", port, timeout=0.1)), "fixture listener leaked"
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc.state() == QProcess.NotRunning), "fixture child leaked"
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
    # Opening a project shows its start page; running it takes Start. The test
    # asks for the explicit "open and run" path rather than clicking the button.
    w._select_id(st.ordered()[0]["id"], start=True)
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
    rec = st.add(rec)  # add() assigns the id; the validated dict has none
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
    rec = st.add(rec)  # add() assigns the id; the validated dict has none
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


def _announcing_src(port: int) -> str:
    return f'''
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *a): pass
print("my dashboard is at http://127.0.0.1:{port}", flush=True)
HTTPServer(("127.0.0.1", {port}), H).serve_forever()
'''


def test_background_project_url_is_saved_to_its_own_record(tmp: Path) -> None:
    """BUG-006: a detected URL belongs to the project that emitted it.

    Two projects have no configured URL. Alpha starts and announces its
    address; Beta is the ACTIVE project when the announcement arrives. The old
    handler read self.active_id, so Alpha's URL would have been stored on
    Beta's record (and Beta's tab pointed at it). The test drives the real tab
    selection rather than setting active_id by hand, so the defect is actually
    exercised.
    """
    from hub import diagnostics

    port = reserve_port()
    (tmp / "announce.py").write_text(_announcing_src(port))
    st = sm.Store(tmp / "registry.json")
    alpha = st.add(
        sm.validate(
            {
                "name": "Alpha",
                "command": f"{sys.executable} {tmp / 'announce.py'} {port}",
                "url": "",
                "working_dir": str(tmp),
            }
        )
    )
    beta = st.add(
        sm.validate(
            {
                "name": "Beta",
                "command": f'{sys.executable} -c "pass"',
                "url": "",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(alpha["id"])
        assert _wait_for(
            lambda: w._tab_index_for_project(alpha["id"]) is not None
        ), "Alpha never got a tab"
        assert _wait_for(
            lambda: w.procs.get(alpha["id"]) is not None
            and w.procs[alpha["id"]].state == "running",
            timeout_s=25,
        ), "Alpha never started"

        # Switch to Beta WITHOUT starting it. This is the user-viewed project
        # when Alpha's server announces itself.
        w._select_id(beta["id"], start=False)
        assert w.active_id == beta["id"], w.active_id

        expected = f"http://127.0.0.1:{port}/"
        ok = _wait_for(
            lambda: (st.get(alpha["id"]) or {}).get("url") != "", timeout_s=30
        )
        assert ok, "Alpha's detected URL was never saved"
        assert st.get(alpha["id"])["url"].rstrip("/") == expected.rstrip("/"), (
            st.get(alpha["id"])["url"]
        )
        # Beta's record must be untouched.
        assert st.get(beta["id"])["url"] == "", st.get(beta["id"])["url"]

        # Alpha's OWN tab navigates, even while Beta is active.
        alpha_view = w._view_for(alpha["id"])
        assert alpha_view is not None, "Alpha lost its tab"
        assert _wait_for(
            lambda: alpha_view.url().toString().rstrip("/") == expected.rstrip("/"),
            timeout_s=30,
        ), f"Alpha's tab went to {alpha_view.url().toString()!r}"
        beta_view = w._view_for(beta["id"])
        assert beta_view is None or beta_view.url().toString() in ("", "about:blank"), (
            f"Beta's tab was pointed at Alpha's URL: "
            f"{beta_view.url().toString()!r}"
        )

        # The report path must not leak either project's data either.
        report = w._diagnostic_report()
        text = diagnostics.format_report(report)
        assert "Alpha" not in text and "Beta" not in text, text
        assert report["registered_projects"] == 2
    finally:
        for proc in list(w.procs.values()):
            try:
                proc.stop()
            except Exception:
                pass
        for proc in list(w.procs.values()):
            _wait_for(lambda p=proc: p.state == "stopped", timeout_s=20)
        w.close()


def test_no_tab_dashboard_does_not_navigate_the_active_tab(tmp: Path) -> None:
    """A project with no tab must never redirect another project's dashboard.

    Reproduces the window between removing a project's tab and the state
    handler clearing active_id: active_id still names the removed project, but
    the current webview belongs to the other project. The old fallback used
    self.web here and pointed the wrong tab at the URL.
    """
    st = sm.Store(tmp / "registry.json")
    a = st.add(
        sm.validate(
            {"name": "Alpha", "command": f'{sys.executable} -c "pass"',
             "working_dir": str(tmp)}
        )
    )
    b = st.add(
        sm.validate(
            {"name": "Beta", "command": f'{sys.executable} -c "pass"',
             "working_dir": str(tmp)}
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(a["id"], start=False)
        w._select_id(b["id"], start=False)
        w._select_id(a["id"], start=False)  # make Alpha the active tab
        assert w.active_id == a["id"]
        beta_view = w._view_for(b["id"])
        assert beta_view is not None
        idx = w._tab_index_for_project(a["id"])
        assert idx is not None
        removed = w.tabs.widget(idx)
        w.tabs.removeTab(idx)  # direct removal leaves active_id == Alpha
        if removed is not None:
            removed.deleteLater()
        assert w.active_id == a["id"], w.active_id
        assert w._view_for(a["id"]) is None
        assert w.web is beta_view, "the test did not select Beta's view"

        before = beta_view.url().toString()
        st.get(a["id"])["url"] = "http://127.0.0.1:9876/alpha"
        w._show_dashboard(st.get(a["id"]))
        assert beta_view.url().toString() == before, (
            "a no-tab project redirected the active project's dashboard"
        )
    finally:
        w.close()


def test_window_registers_context_for_crash_reports(tmp: Path) -> None:
    """The live window's project identity reaches current_exception_report."""
    import re

    from hub import diagnostics

    st = sm.Store(tmp / "registry.json")
    st.add(
        sm.validate(
            {"name": "Q", "command": f'{sys.executable} -c "pass"',
             "working_dir": str(tmp)}
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        try:
            raise RuntimeError("Q crashed while loading")
        except RuntimeError:
            report = diagnostics.current_exception_report()
        text = diagnostics.format_report(report)
        assert "RuntimeError" in text, text
        assert re.search(r"(?<!\w)Q(?!\w)", text) is None, text
    finally:
        w.close()
        diagnostics.clear_project_context()


def test_report_problem_exports_no_project_data(tmp: Path) -> None:
    """BUG-007: the real Report a Problem report is sanitised end to end.

    Synthetic markers are placed in a project's name, working directory,
    startup command, URL and environment, and in its raw terminal output. The
    report the Help menu actually builds must contain none of them, while
    keeping the useful hub-level error message.
    """
    import urllib.parse

    from hub import diagnostics

    markers = {
        "name": "ProjectNebula42",
        "path": str(tmp / "ProjectNebula42-Workspace"),
        "url": "http://127.0.0.1:9876/nebula-dashboard",
        "secret": "sk-SYNTHETIC0000000000000000",
    }
    workdir = Path(markers["path"])
    workdir.mkdir(exist_ok=True)
    script = workdir / "nebula_server.py"
    script.write_text("print('x')\n", encoding="utf-8")
    markers["command"] = f"{sys.executable} {script} --token {markers['secret']}"

    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": markers["name"],
                "command": markers["command"],
                "working_dir": markers["path"],
                "url": markers["url"],
                "env": {"API_KEY": markers["secret"]},
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        # A project's own terminal carries raw output; the hub pane carries the
        # diagnostic messages. Only the latter may contribute to the report.
        w.log_view.append_for(
            f"RAW-PROJECT-OUTPUT {markers['secret']} {markers['path']}",
            rec["id"],
        )
        w._append_log(f"[hub] starting {markers['name']}: {markers['command']}")
        w._append_log(
            f"[hub] update check failed: HTTP 500 for {markers['url']}"
        )

        report = w._diagnostic_report()
        text = diagnostics.format_report(report)
        for label, marker in markers.items():
            assert marker not in text, f"{label} leaked into the report: {text!r}"
        assert "RAW-PROJECT-OUTPUT" not in text, text
        assert "update check failed" in text, text
        assert report["registered_projects"] == 1

        url = diagnostics.issue_url(report)
        if url:
            decoded = urllib.parse.unquote(url)
            for label, marker in markers.items():
                assert marker not in decoded, (
                    f"{label} leaked into the prefilled issue URL"
                )
    finally:
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


def test_sidebar_internal_move_saves_order_and_keeps_project_identity(tmp: Path) -> None:
    from PySide6.QtCore import QModelIndex

    st = sm.Store(tmp / "registry.json")
    records = [
        st.add({"name": name, "command": "echo unused", "icon": "🌐"})
        for name in ("discordbot", "obs", "sphere")
    ]
    original = [r["id"] for r in records]
    wanted = original[1:] + original[:1]
    w = HubWindow(st)
    w.show()
    try:
        _spin(100)
        assert w.list.dragDropMode() == QAbstractItemView.InternalMove, (
            "the Projects list does not allow internal drag-and-drop reordering"
        )
        assert w.list.dragEnabled() and w.list.acceptDrops()
        assert w.list.showDropIndicator(), "there is no visible insertion indicator"
        assert not (w.list.item(0).flags() & Qt.ItemIsDropEnabled), (
            "flat project rows must accept insertion between rows, not child drops"
        )
        selected = w.list.currentItem().data(Qt.UserRole)
        tabs = [w.tabs.widget(i) for i in range(w.tabs.count())]
        processes = dict(w.procs)

        assert w.list.model().moveRow(QModelIndex(), 0, QModelIndex(), 3), (
            "the actual QListWidget model refused to move the top row to the bottom"
        )
        _spin(100)
        visible = [w.list.item(i).data(Qt.UserRole) for i in range(w.list.count())]
        assert visible == wanted, f"wrong visible project order: {visible}"
        assert [r["id"] for r in sm.Store(st.path).ordered()] == wanted, (
            "the widget moved, but its new order was not saved"
        )
        assert w.list.currentItem().data(Qt.UserRole) == selected
        assert w.active_id == selected, "moving a row switched the active project"
        assert [w.tabs.widget(i) for i in range(w.tabs.count())] == tabs
        assert w.procs == processes, "moving a row replaced a project's process object"
        assert all(p.state == "stopped" for p in w.procs.values()), (
            "rearranging the sidebar started a project"
        )
        w._reload_list()
        assert [w.list.item(i).data(Qt.UserRole) for i in range(w.list.count())] == wanted
    finally:
        w.close()


def test_sidebar_restores_custom_order_on_startup(tmp: Path) -> None:
    st = sm.Store(tmp / "registry.json")
    ids = [
        st.add({"name": name, "command": "echo unused"})["id"]
        for name in ("discordbot", "obs", "sphere")
    ]
    wanted = ids[1:] + ids[:1]
    st.reorder(wanted)
    w = HubWindow(sm.Store(st.path))
    w.show()
    try:
        _spin(100)
        assert [w.list.item(i).data(Qt.UserRole) for i in range(w.list.count())] == wanted
        assert w.list.currentItem().data(Qt.UserRole) == wanted[0]
        assert all(p.state == "stopped" for p in w.procs.values())
    finally:
        w.close()


def test_sidebar_failed_order_save_restores_rows_and_reports_error(tmp: Path) -> None:
    from PySide6.QtCore import QModelIndex

    st = sm.Store(tmp / "registry.json")
    ids = [
        st.add({"name": name, "command": "echo unused"})["id"]
        for name in ("discordbot", "obs", "sphere")
    ]
    ids = ids[1:] + ids[:1]
    st.reorder(ids)
    before = st.path.read_bytes()
    w = HubWindow(st)
    w.show()
    save = st.save

    def fail_save():
        raise OSError("test disk is full")

    try:
        _spin(100)
        selected = w.active_id
        st.save = fail_save
        assert w.list.model().moveRow(QModelIndex(), 0, QModelIndex(), 3)
        _spin(100)
        assert [w.list.item(i).data(Qt.UserRole) for i in range(w.list.count())] == ids, (
            "the list still shows an order that failed to save"
        )
        assert list(st.projects) == ids
        assert st.path.read_bytes() == before
        assert w.active_id == selected and w.list.currentItem().data(Qt.UserRole) == selected
        assert "Couldn't save project order" in w.status.currentMessage()
        assert "test disk is full" in w.log_view.hub_text()
        assert all(p.state == "stopped" for p in w.procs.values())
    finally:
        st.save = save
        w.close()


def test_sidebar_reorder_keeps_a_running_project_running(tmp: Path) -> None:
    from PySide6.QtCore import QModelIndex, QProcess
    from urllib.request import urlopen

    w, port = make_window(tmp)
    proc = None
    try:
        rec = w.store.ordered()[0]
        proc = w.procs[rec["id"]]
        assert _wait_for(lambda: proc.state == "running" and proc.proc is not None)
        assert _wait_for(lambda: w.web.url().toString() == rec["url"])
        child = proc.proc
        assert child is not None
        pid = int(child.processId())
        assert pid > 0
        other = w.store.add({"name": "AAA idle project", "command": "echo unused"})
        w._reload_list()
        tabs = [w.tabs.widget(i) for i in range(w.tabs.count())]

        assert w.list.model().moveRow(QModelIndex(), 0, QModelIndex(), 2)
        _spin(100)

        assert [w.list.item(i).data(Qt.UserRole) for i in range(w.list.count())] == [other["id"], rec["id"]]
        assert w.active_id == rec["id"]
        assert [w.tabs.widget(i) for i in range(w.tabs.count())] == tabs
        assert w.procs[rec["id"]] is proc and proc.proc is child
        assert proc.state == "running" and int(child.processId()) == pid, (
            "rearranging the sidebar stopped or restarted the running project"
        )
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert response.read() == b"HUB-WINDOW-TEST"
    finally:
        w.close()
        if proc is not None:
            assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning), (
                "the isolated test server was not cleaned up"
            )


def test_sidebar_rename_keeps_the_saved_custom_position(tmp: Path) -> None:
    st = sm.Store(tmp / "registry.json")
    ids = [st.add({"name": name, "command": "echo unused"})["id"]
           for name in ("discordbot", "obs", "sphere")]
    wanted = ids[1:] + ids[:1]
    st.reorder(wanted)
    w = HubWindow(st)
    w.show()
    try:
        item = w.list.item(2)
        w.list.setCurrentItem(item)
        w.list.editItem(item)
        assert _wait_for(lambda: w.list.state() == QAbstractItemView.EditingState, 3)
        editor = w.list.findChild(QLineEdit)
        assert editor is not None and editor.isVisible()
        assert editor.text() == "discordbot"
        editor.setText("AAA renamed bot")
        index = w.list.model().index(2, 0)
        w.list.itemDelegate().setModelData(editor, w.list.model(), index)
        saved = st.get(ids[0])
        assert saved is not None and saved["name"] == "AAA renamed bot"
        assert [w.list.item(i).data(Qt.UserRole) for i in range(w.list.count())] == wanted
        assert [r["id"] for r in sm.Store(st.path).ordered()] == wanted
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
