"""Browser history and downloads through the real Hub window.

Each case runs in its own process via tests/run_all.py; owned HTTP fixtures bind
port zero directly and never inspect or stop an unrelated listener.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QPoint, QTimer, QUrl, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEnginePage
from PySide6.QtWidgets import QApplication, QToolBar

from hub import store as sm
from hub.window import HubWindow

RAW_TEXT = "# Raw skill\nPreserve UTF-8: 雪 / café\nSecond line\n"


def _spin(ms=20):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_for(predicate, seconds=10):
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        _spin()
    return predicate()


@contextmanager
def _browser(tmp: Path, private=False, popup_gate=None):
    counts = {}
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            counts[path] = counts.get(path, 0) + 1
            if path in ("/raw.txt", "/slow.txt"):
                body = RAW_TEXT.encode("utf-8") * (4096 if path == "/slow.txt" else 1)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="raw-skill.txt"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    if path == "/slow.txt":
                        self.wfile.write(body[:4096])
                        self.wfile.flush()
                        release.wait(15)
                        self.wfile.write(body[4096:])
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Owned cancellation fixture, not an application error.
                return
            title = "Replay" if path == "/replay" else "Spheres"
            body = (
                '<!doctype html><html><head><title>' + title + '</title></head>'
                '<body><h1>' + title + '</h1><style>#raw {position:absolute;left:24px;top:100px;width:160px;height:40px}</style>'
                '<a id="raw" href="/replay">raw skill</a> '
                '<a id="popup" href="/spheres" target="_blank">Open spheres tab</a>'
                '<button id="download" style="position:absolute;left:24px;top:164px;width:180px;height:40px" onclick="saveRaw()">Download raw text</button>'
                '<a id="slow" href="/slow.txt" style="position:absolute;left:24px;top:228px;width:180px;height:40px">Slow download</a>'
                '<a id="network" href="/raw.txt" style="position:absolute;left:24px;top:292px;width:180px;height:40px">HTTP raw download</a>'
                '<script>function saveRaw() { const blob = new Blob([' + json.dumps(RAW_TEXT) + '], {type:"text/plain;charset=utf-8"});'
                'const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "raw-skill.txt";'
                'document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }</script>'
                '</body></html>'
            ).encode("utf-8")
            head = body_rest = b""
            delayed_popup = popup_gate is not None and path == "/spheres" and counts[path] > 1
            if delayed_popup:
                head, body_rest = body.split(b"<body>", 1)
                head += b"<!--" + b" " * 4096 + b"-->"
                body = head + b"<body>" + body_rest
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if delayed_popup and popup_gate is not None:
                self.wfile.write(head)
                self.wfile.flush()
                counts["popup_gate_waiting"] = True
                popup_gate.wait(4)
                counts["popup_gate_waiting"] = False
                self.wfile.write(b"<body>" + body_rest)
            else:
                self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_port)
    store = sm.Store(tmp / "state" / "registry.json")
    record = store.add({
        "name": "Browser fixture", "command": ("python3 -m http.server " + str(server.server_port)) if private else "echo unused",
        "url": base + "/spheres", "working_dir": str(tmp),
    })
    window = HubWindow(store)
    window.show()
    try:
        window._select_id(record["id"], start=False)
        view = window.web
        loaded = []
        view.loadFinished.connect(loaded.append)
        window._show_dashboard(record)
        assert _wait_for(lambda: view.title() == "Spheres" and loaded and loaded[-1] and not view.page().isLoading()), "owned fixture did not load"
        yield window, view, base, counts
    finally:
        release.set()
        if popup_gate is not None:
            popup_gate.set()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        _spin()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "owned HTTP fixture thread survived teardown"


def _toolbar_button(window, name):
    action = getattr(window, name, None)
    assert action is not None, "Hub has no " + name + " browser control"
    toolbar = next(t for t in window.findChildren(QToolBar) if action in t.actions())
    button = toolbar.widgetForAction(action)
    assert button is not None and button.isVisible(), name + " is not visible"
    assert button.width() > 0 and button.height() > 0, name + " has no geometry"
    assert window.rect().contains(button.mapTo(window, button.rect().center())), name + " is outside the window"
    return button


def test_same_tab_raw_link_has_visible_back_forward_reload(tmp):
    with _browser(tmp) as (window, view, base, counts):
        back = _toolbar_button(window, "act_back")
        forward = _toolbar_button(window, "act_forward")
        reload_button = _toolbar_button(window, "act_reload")
        original_tabs = window.tabs.count()
        # Ordinary links retain their page-defined same-tab behavior.
        view.setFocus()
        QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(80, 116))
        assert _wait_for(lambda: view.title() == "Replay" and back.isEnabled()), "raw link did not enter history"
        assert window.tabs.count() == original_tabs and window.web is view
        before_back = {"url": view.url().toString(), "title": view.title(), "loading": view.page().isLoading(),
                       "can_back": view.history().canGoBack(), "can_forward": view.history().canGoForward(),
                       "back_enabled": back.isEnabled(), "forward_enabled": forward.isEnabled()}
        back.click()
        assert _wait_for(lambda: view.title() == "Spheres" and forward.isEnabled()), (
            "Back did not return to spheres", before_back,
            {"url": view.url().toString(), "title": view.title(), "loading": view.page().isLoading(),
             "can_back": view.history().canGoBack(), "can_forward": view.history().canGoForward(),
             "back_enabled": back.isEnabled(), "forward_enabled": forward.isEnabled()})
        assert window.web is view and view.isVisible()
        forward.click()
        assert _wait_for(lambda: view.title() == "Replay"), "Forward did not restore replay"
        # Title changes before loading completes; Qt intentionally disables
        # Reload while a navigation is in flight. Do not click a disabled button.
        assert _wait_for(lambda: not view.page().isLoading() and reload_button.isEnabled()), (
            "Replay did not become reload-ready", view.url().toString(),
            view.page().isLoading(), reload_button.isEnabled(), counts)
        before = counts["/replay"]
        reload_button.click()
        assert _wait_for(lambda: counts.get("/replay", 0) > before), "Reload did not reload the selected page"
        assert all(proc.proc is None for proc in window.procs.values()), "browser navigation launched a backend"


def test_blob_raw_text_download_prompts_and_saves_exact_bytes(tmp):
    with _browser(tmp) as (window, view, base, counts):
        destination = tmp / "saved raw skill.txt"
        requests = []
        profile = view.page().profile()
        def observe(request):
            requests.append(request.url().toString())
        profile.downloadRequested.connect(observe)
        try:
            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(destination), "")) as chooser:
                view.setFocus()
                QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(90, 184))
                assert _wait_for(lambda: chooser.call_count > 0), (
                    "Raw export never offered a save dialog", requests, window.status.currentMessage())
                assert chooser.call_count == 1, "download prompted more than once"
                assert _wait_for(lambda: destination.is_file() and destination.read_bytes() == RAW_TEXT.encode("utf-8")), (
                    "Raw export did not save its original UTF-8 bytes", requests, window.status.currentMessage())
                assert _wait_for(lambda: window.status.currentMessage().startswith("Download saved:")), "no visible completed-download outcome"
                assert str(destination) in window.log_view.toPlainText(), "saved path missing from the owning project's log"
                dialogs = list(window._browser_downloads._dialogs)
                assert len(dialogs) == 1 and dialogs[0].message.text() == "Download saved", (
                    "completion headline duplicates the long path and clips its label",
                    [d.message.text() for d in dialogs])
                assert dialogs[0].path.text() == str(destination), "complete destination is not shown separately"
                assert view.title() == "Spheres" and window.web is view, "download navigated away from the source page"
        finally:
            profile.downloadRequested.disconnect(observe)


def test_closing_in_progress_download_cancels_without_deleted_widget_callback(tmp):
    errors = []
    with patch("sys.excepthook", lambda *exc: errors.append(str(exc[1]))):
        with _browser(tmp) as (window, view, base, counts):
            states = []
            def observe(request):
                request.stateChanged.connect(lambda state: states.append(state))
            profile = view.page().profile()
            profile.downloadRequested.connect(observe)
            try:
                with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(tmp / "cancelled.txt"), "")):
                    QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(90, 244))
                    assert _wait_for(lambda: bool(window._browser_downloads._active)), "slow download never started"
                    request, (dialog, _, _) = next(iter(window._browser_downloads._active.items()))
                    assert dialog.isVisible() and not request.isFinished()
                    dialog.close()
                    assert _wait_for(lambda: QWebEngineDownloadRequest.DownloadCancelled in states, 3), (
                        "Closing the download window did not cancel the transfer", [str(s) for s in states])
                    assert _wait_for(lambda: not window._browser_downloads._active), "cancelled request remained active"
                    assert window.status.currentMessage().startswith("Download cancelled:"), window.status.currentMessage()
                    _spin()
                    assert not errors, errors
            finally:
                profile.downloadRequested.disconnect(observe)
        assert not errors, errors


def test_popup_history_and_starter_controls_follow_selected_tab(tmp):
    popup_gate = threading.Event()
    with _browser(tmp, private=True, popup_gate=popup_gate) as (window, main, base, counts):
        from PySide6.QtWebEngineCore import QWebEngineProfile
        assert main.page().profile() is not QWebEngineProfile.defaultProfile(), "private profile fixture was not exercised"
        loaded = []
        main.popup_opened.connect(lambda child: child.loadFinished.connect(loaded.append))
        main.page().runJavaScript("document.getElementById('popup').click()")
        assert _wait_for(lambda: window.web is not main and window.web is not None and window.web.title() == "Spheres")
        popup = window.web
        assert popup.page().profile() is main.page().profile()
        assert counts.get("popup_gate_waiting") and popup.page().isLoading(), "delayed popup fixture did not hold its body"
        QTimer.singleShot(200, popup_gate.set)
        assert _wait_for(lambda: loaded and loaded[-1] and not popup.page().isLoading()), "popup body never finished loading"
        QTest.mouseClick(popup.focusProxy(), Qt.LeftButton, pos=QPoint(80, 116))
        assert _wait_for(lambda: popup.title() == "Replay" and window.act_back.isEnabled()), (
            "popup raw link did not navigate", popup.url().toString(), popup.page().isLoading(), counts)
        _toolbar_button(window, "act_back").click()
        assert _wait_for(lambda: popup.title() == "Spheres" and window.act_forward.isEnabled())
        window.tabs.setCurrentWidget(main)
        assert not window.act_forward.isEnabled(), "popup history leaked to the main tab"
        window.tabs.setCurrentWidget(popup)
        assert window.act_forward.isEnabled(), "popup history not restored on focus"
        window.open_starter_tab()
        assert not any(a.isEnabled() for a in (window.act_back, window.act_forward, window.act_reload)), "browser actions enabled on the nonbrowser starter"
        window.tabs.setCurrentWidget(popup)
        _toolbar_button(window, "act_forward").click()
        assert _wait_for(lambda: popup.title() == "Replay")
        assert main.title() == "Spheres", "popup navigation changed the original dashboard"


def test_private_popup_download_has_one_chooser_and_owning_log(tmp):
    with _browser(tmp, private=True) as (window, main, base, counts):
        record = window.store.get(window.active_id)
        for _ in range(3):
            assert window._profile_for(record) is main.page().profile()
        loaded = []
        main.popup_opened.connect(lambda child: child.loadFinished.connect(loaded.append))
        main.page().runJavaScript("document.getElementById('popup').click()")
        assert _wait_for(lambda: window.web is not main and window.web is not None and window.web.title() == "Spheres")
        popup = window.web
        assert _wait_for(lambda: loaded and loaded[-1] and not popup.page().isLoading()), "popup body never finished loading"
        destination = tmp / "private popup export.txt"
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(destination), "")) as chooser:
            QTest.mouseClick(popup.focusProxy(), Qt.LeftButton, pos=QPoint(90, 184))
            assert _wait_for(lambda: window.status.currentMessage().startswith("Download saved:")), window.status.currentMessage()
            assert chooser.call_count == 1, "shared/private profile prompted repeatedly"
            assert destination.read_bytes() == RAW_TEXT.encode("utf-8")
            assert str(destination) in window.log_view._edit_for(record["id"]).toPlainText()
            assert str(destination) not in window.log_view.hub_text(), "download was attributed to Hub rather than project"
            assert window.web is popup and popup.isVisible()


def test_network_attachment_uses_same_save_path(tmp):
    with _browser(tmp) as (window, view, base, counts):
        destination = tmp / "network raw.txt"
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(destination), "")) as chooser:
            QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(90, 308))
            assert _wait_for(lambda: window.status.currentMessage().startswith("Download saved:")), (
                "HTTP attachment did not complete", chooser.call_count, counts,
                window.status.currentMessage(), window.log_view.toPlainText(), view.url().toString())
            assert destination.read_bytes() == RAW_TEXT.encode("utf-8")
            assert chooser.call_count == 1
            assert view.title() == "Spheres", "attachment replaced the dashboard"


def test_cancelled_save_dialog_does_not_write_or_start_transfer(tmp):
    with _browser(tmp) as (window, view, base, counts):
        before = set(tmp.rglob("*"))
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("", "")) as chooser:
            QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(90, 184))
            assert _wait_for(lambda: window.status.currentMessage().startswith("Download cancelled:")), window.status.currentMessage()
            assert chooser.call_count == 1 and not window._browser_downloads._active
            assert set(tmp.rglob("*")) == before, "cancelled chooser wrote project files"
            assert view.title() == "Spheres"


def test_unwritable_download_has_visible_failure_not_success(tmp):
    with _browser(tmp) as (window, view, base, counts):
        blocker = tmp / "not-a-directory"
        blocker.write_bytes(b"keep this existing file")
        destination = blocker / "raw.txt"
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
            QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(90, 184))
            assert _wait_for(lambda: window.status.currentMessage().startswith("Download failed:")), (
                window.status.currentMessage(),
                [(str(r.state()), r.isFinished(), r.interruptReasonString(), d.message.text())
                 for r, (d, _, _) in window._browser_downloads._active.items()])
            assert not destination.exists()
            dialogs = list(window._browser_downloads._dialogs)
            assert dialogs and any(d.isVisible() and d.message.text().startswith("Download failed:") and d.button.text() == "Close" for d in dialogs)
            assert "Download saved:" not in window.log_view.toPlainText()


def test_download_shutdown_tolerates_a_profile_deleted_by_qt(tmp):
    """The shutdown seam must tolerate Qt deleting a watched native object."""
    from PySide6.QtCore import QObject, Signal
    from shiboken6 import delete, isValid
    from hub.browser_downloads import BrowserDownloads
    class ProfileLifetime(QObject):
        downloadRequested = Signal(object)
    # Exercise real QObject/signal deletion directly. Forcing a live Chromium
    # context to die inside a QWidget callback can crash Cocoa before an assertion.
    owner = QObject()
    controller = BrowserDownloads(owner)
    profile = ProfileLifetime(owner)
    controller.watch(profile)
    delete(profile)
    assert not isValid(profile)
    try:
        controller.shutdown()
        controller.shutdown()  # Repeated close must be harmless too.
    finally:
        delete(owner)


def test_hub_close_cancels_in_progress_download(tmp):
    with _browser(tmp) as (window, view, base, counts):
        states = []
        def observe(request):
            request.stateChanged.connect(lambda state: states.append(state))
        profile = view.page().profile()
        profile.downloadRequested.connect(observe)
        try:
            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(tmp / "shutdown.txt"), "")):
                QTest.mouseClick(view.focusProxy(), Qt.LeftButton, pos=QPoint(90, 244))
                assert _wait_for(lambda: bool(window._browser_downloads._active))
                window.close()
                assert _wait_for(lambda: QWebEngineDownloadRequest.DownloadCancelled in states, 3), "closing Hub left its download writing in the background"
                assert not window._browser_downloads._active
        finally:
            profile.downloadRequested.disconnect(observe)


if __name__ == "__main__":
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--test=")), None)
    names = sorted(n for n, f in globals().items() if n.startswith("test_") and callable(f))
    if only is not None and only not in names:
        print("FAIL no such test: " + only)
        raise SystemExit(2)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    failures = 0
    for name in names:
        if only is not None and name != only:
            continue
        with tempfile.TemporaryDirectory() as directory:
            try:
                globals()[name](Path(directory))
                print("PASS " + name, flush=True)
            except Exception as exc:
                failures += 1
                print("FAIL " + name + ": " + str(exc), flush=True)
                traceback.print_exc()
    raise SystemExit(1 if failures else 0)
