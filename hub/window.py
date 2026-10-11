"""Main window: project list + toolbar + embedded webview + log drawer.

Design notes (matching SPEC's separation principle):
  * One sidebar list of projects. Selecting a row = "open it": starts the
    backend if needed, waits for readiness, then points the webview at the URL.
  * Toolbar: Start/Stop, Restart, Open in Browser, Add, Edit, Remove.
  * Log drawer at the bottom shows merged stdout/stderr of the active project,
    plus hub messages. It is collapsible so it stays unobtrusive.
  * A project's failure never blocks another project: every process is its own
    QProcess, and the webview just shows an error page on load failure.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStackedLayout,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import diagnostics as diagnostics_mod
from . import launch_at_login, store as store_mod
from .diagnostics import build_report, format_report, save_report
from .platform import IS_MACOS, IS_WINDOWS
from .process_manager import ProjectProcess
from .project_dialog import ProjectDialog
from .readiness import ReadinessWaiter
from .updater import UpdateError, _asset_for_platform, fetch_latest_release, is_newer, verify_sha256

_STATE_LABEL = {
    "stopped": "● stopped",
    "starting": "◌ starting…",
    "running": "● running",
    "error": "✕ error",
}


class _PopupBridge(QObject):
    """Kept for import compatibility; the popup path now uses createWindow."""


class HubWebView(QWebEngineView):
    """A webview that answers window.open(..., "_blank") instead of dropping it.

    Dashboards use _blank for the 🪐 spheres view, full replay, etc. Plain
    QWebEngineView swallows those clicks (createWindow is not overridden), so
    the click appears to do nothing. Overriding it and returning a real view
    opens the page — verified for both window.open and target="_blank" links.

    The child view is owned by the hub window (see HubWindow._on_popup_opened)
    so popups stay alive independently of the dashboard that spawned them.
    """

    popup_opened = Signal(QWebEngineView)

    def createWindow(self, window_type):
        # NOTE: PySide6 expects the QWebEngineView itself here, not .page() —
        # returning a page raises RuntimeWarning and the popup never navigates.
        # No show(): as a tab child the QTabWidget owns visibility. Calling
        # show() here would pop a floating window.
        view = HubWebView()
        view.popup_opened.connect(self.popup_opened)
        self.popup_opened.emit(view)
        return view


class HubWindow(QMainWindow):
    def __init__(self, store: store_mod.Store):
        super().__init__()
        self.setWindowTitle("Local Project Hub")
        self.resize(1180, 780)
        self.store = store
        self.procs: dict[str, ProjectProcess] = {}
        self.active_id: str | None = None
        self.waiters: dict[str, ReadinessWaiter] = {}
        # Projects the user explicitly stopped, so an unrequested exit is not
        # mistaken for one (only an explicit stop closes the project's tabs).
        self._user_stopped_ids: set[str] = set()

        self._build_ui()
        self._reload_list()
        self._restore_last_project()
        self._autostart()

    # ---------- menus: About / Preferences / Updates / Reports ----------

    def _show_about(self) -> None:
        from . import __version__
        from .diagnostics import describe_platform_support

        QMessageBox.about(
            self,
            "About Local Project Hub",
            f"<h3>Local Project Hub</h3>"
            f"<p>Version <b>{__version__}</b></p>"
            f"<p>A control centre for your locally hosted projects.</p>"
            f"<p style='color: gray'>Supports {describe_platform_support()}.</p>",
        )

    def _show_preferences(self) -> None:
        """Application preferences (release spec §4).

        Launch-at-login is the one real setting today (spec §9). It is opt-in
        and off by default, and toggling it off removes the registration.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Preferences")
        form = QVBoxLayout(dlg)

        self.chk_launch = QCheckBox("Launch Local Project Hub at login")
        self.chk_launch.setChecked(launch_at_login.is_enabled())
        self.chk_launch.setToolTip("Starts the Hub when you log in. Off by default.")
        self.chk_launch.toggled.connect(self._toggle_launch_at_login)
        form.addWidget(self.chk_launch)

        note = QLabel(
            "Launching at login starts the Hub only. Projects are never "
            "started automatically unless you tick 'Start automatically' on "
            "the project itself."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        form.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dlg.accept)
        form.addWidget(buttons)
        dlg.exec()

    def _toggle_launch_at_login(self, on: bool) -> None:
        ok, err = launch_at_login.set_enabled(on)
        if not ok:
            QMessageBox.warning(self, "Launch at login", err or "Could not change that setting.")
            self.chk_launch.setChecked(launch_at_login.is_enabled())

    def _check_for_updates(self) -> None:
        """Help → Check for Updates (release spec §5)."""
        self.status.showMessage("Checking for updates…")
        result = {"release": None, "error": None}

        def _work():
            try:
                result["release"] = fetch_latest_release()
            except UpdateError as e:
                result["error"] = str(e)
            except Exception as e:  # never let a check crash the app
                result["error"] = f"Update check failed: {e}"

        def _done():
            err, release = result["error"], result["release"]
            if err:
                self.status.clearMessage()
                QMessageBox.information(self, "Check for Updates", err)
                return
            if not is_newer(release.version):
                self.status.clearMessage()
                QMessageBox.information(
                    self,
                    "Check for Updates",
                    f"Local Project Hub {__version__} is up to date.",
                )
                return
            self._offer_update(release)

        self._run_offline_safe(_work, _done)

    def _offer_update(self, release) -> None:
        from .updater import summarize_release

        asset = _asset_for_platform(release.assets)
        msg = QMessageBox(self)
        msg.setWindowTitle("Update available")
        msg.setText(summarize_release(release))
        msg.setInformativeText(
            "Download and install now?\n\n"
            + (
                f"The {asset.name} installer will open; your projects and "
                "settings are kept."
                if asset
                else "No installer for this platform was published in this release yet."
            )
        )
        download = msg.addButton("Download and Install", QMessageBox.AcceptRole)
        msg.addButton("Later", QMessageBox.RejectRole)
        if release.html_url:
            msg.addButton("Open release page", QMessageBox.HelpRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is download:
            self._download_update(release, asset)
        elif release.html_url and clicked is not None and msg.buttonRole(clicked) == QMessageBox.HelpRole:
            QDesktopServices.openUrl(QUrl(release.html_url))

    def _download_update(self, release, asset) -> None:
        """Download to a temp file, verify, then hand off to the OS installer.

        Never replaces the running executable in place (release spec §5): the
        artifact is staged, integrity-checked, and the platform installer is
        launched, which asks the user before touching anything.
        """
        if asset is None:
            QMessageBox.warning(
                self,
                "Update",
                "This release does not include an installer for your platform yet.",
            )
            return
        self.status.showMessage(f"Downloading {asset.name}…")
        self._append_log(f"[hub] downloading update {asset.name}")

        def _work():
            import tempfile
            import urllib.request

            dest = Path(tempfile.gettempdir()) / asset.name
            try:
                urllib.request.urlretrieve(asset.url, dest)
            except Exception as e:
                return None, f"Download failed: {e}"
            if asset.sha256:
                if not verify_sha256(dest, asset.sha256):
                    return None, (
                        "The downloaded file did not match its published checksum, "
                        "so it was discarded."
                    )
            return dest, None

        def _done(res):
            dest, err = res if res else (None, "Download failed.")
            if err:
                self.status.clearMessage()
                self._append_log(f"[hub] update failed: {err}")
                QMessageBox.warning(self, "Update", err)
                return
            self.status.clearMessage()
            self._append_log(f"[hub] update downloaded to {dest}")
            self._launch_installer(dest)

        self._run_offline_safe(_work, _done)

    def _launch_installer(self, path: Path) -> None:
        """Hand the artifact to the OS. The running app is never overwritten."""
        try:
            if IS_MACOS:
                # Opening a .dmg mounts it; the user drags the app across.
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                QMessageBox.information(
                    self,
                    "Install the update",
                    "The disk image has been opened.\n\n"
                    "Drag Local Project Hub over your existing copy to replace it, "
                    "then reopen it. Your projects and settings are untouched.",
                )
            elif IS_WINDOWS:
                # .msi/.exe installers elevate themselves when needed.
                os.startfile(str(path))  # noqa: SLF001 - Windows-only, guarded
                QMessageBox.information(
                    self,
                    "Install the update",
                    "The installer has started.\n\n"
                    "Follow its prompts; your projects and settings are kept. "
                    "You can finish now and restart the Hub when it is done.",
                )
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:
            QMessageBox.warning(
                self,
                "Update",
                f"Could not start the installer automatically.\n\n"
                f"The file is saved at:\n{path}\n\n({e})",
            )

    def _report_problem(self) -> None:
        """Help → Report a Problem: save a report, or open a prefilled issue."""
        from . import diagnostics

        report = diagnostics.build_report(
            log_tail=self.log_view.toPlainText(),
            project_count=len(self.store.projects),
        )

        box = QMessageBox(self)
        box.setWindowTitle("Report a problem")
        box.setText(
            "This creates a report with the app version, your operating system, "
            "and the recent log.\n\n"
            "It does <b>not</b> include your projects, their folders, commands, "
            "or anything a dashboard was showing."
        )
        save_btn = box.addButton("Save report file…", QMessageBox.AcceptRole)
        issue_btn = None
        if diagnostics.issue_url(report):
            issue_btn = box.addButton("Open in browser…", QMessageBox.HelpRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() is save_btn:
            path = diagnostics.save_report(report)
            self.status.showMessage(f"Report saved to {path}", 8000)
            self._append_log(f"[hub] error report saved to {path}")
            QMessageBox.information(
                self,
                "Report saved",
                f"Saved to:\n{path}\n\nAttach it wherever you were asked to send it.",
            )
        elif issue_btn is not None and box.clickedButton() is issue_btn:
            url = diagnostics.issue_url(report)
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def _run_offline_safe(self, work, done) -> None:
        """Run blocking work off the GUI thread, then apply the result.

        Kept tiny on purpose: a QThread wrapper would be more code than the
        two call sites need, and a crash inside `work` is reported rather than
        taking the window down with it.
        """
        from PySide6.QtCore import QThread

        class _Worker(QThread):
            def __init__(self):
                super().__init__()
                self.result = None
                self.failure = None

            def run(self) -> None:
                try:
                    self.result = work()
                except Exception as e:  # noqa: BLE001 - surfaced to the user
                    self.failure = f"{type(e).__name__}: {e}"

        worker = _Worker()
        self._workers = getattr(self, "_workers", [])
        self._workers.append(worker)

        def _finish():
            if worker.failure:
                self.status.clearMessage()
                QMessageBox.warning(self, "Something went wrong", worker.failure)
                return
            done(worker.result)

        worker.finished.connect(_finish)
        worker.start()

    # ---------- UI ----------

    def _build_menus(self) -> None:
        """Native application menus (release spec §4).

        On macOS the app menu is prepended automatically; on Windows and Linux
        the same items live under Help so the feature is discoverable either
        way (spec §4: "following platform conventions").
        """
        menubar = self.menuBar()

        # --- App / File ---
        app_menu = menubar.addMenu("Local Project Hub") if IS_MACOS else menubar.addMenu("File")
        act_about = QAction("About Local Project Hub", self)
        act_about.triggered.connect(self._show_about)
        app_menu.addAction(act_about)
        app_menu.addSeparator()
        act_prefs = QAction("Preferences…", self)
        act_prefs.setMenuRole(QAction.PreferencesRole)
        act_prefs.triggered.connect(self._show_preferences)
        app_menu.addAction(act_prefs)
        if IS_MACOS:
            app_menu.addSeparator()
            act_quit = QAction("Quit", self)
            act_quit.setShortcut(QKeySequence.Quit)
            act_quit.setMenuRole(QAction.QuitRole)
            act_quit.triggered.connect(self.close)
            app_menu.addAction(act_quit)

        # --- Help ---
        help_menu = menubar.addMenu("Help")
        act_update = QAction("Check for Updates…", self)
        act_update.triggered.connect(self._check_for_updates)
        help_menu.addAction(act_update)
        help_menu.addSeparator()
        act_report = QAction("Report a Problem…", self)
        act_report.triggered.connect(self._report_problem)
        help_menu.addAction(act_report)

    def _build_ui(self) -> None:
        self._build_menus()
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_start = QAction("▶︎ Start", self)
        self.act_start.triggered.connect(self._start_active)
        self.act_stop = QAction("■ Stop", self)
        self.act_stop.triggered.connect(self._stop_active)
        self.act_restart = QAction("↻ Restart", self)
        self.act_restart.triggered.connect(self._restart_active)
        self.act_ext = QAction("↗ Open in browser", self)
        self.act_ext.triggered.connect(self._open_external)
        self.act_add = QAction("+ Add", self)
        self.act_add.triggered.connect(self._add_project)
        self.act_edit = QAction("Edit", self)
        self.act_edit.triggered.connect(self._edit_project)
        self.act_remove = QAction("− Remove", self)
        self.act_remove.triggered.connect(self._remove_project)
        self.act_logs = QAction("Logs", self)
        self.act_logs.setCheckable(True)
        self.act_logs.setChecked(True)
        self.act_logs.triggered.connect(self._toggle_logs)
        for a in (
            self.act_start,
            self.act_stop,
            self.act_restart,
            self.act_ext,
            None,
            self.act_add,
            self.act_edit,
            self.act_remove,
            None,
            self.act_logs,
        ):
            if a is None:
                toolbar.addSeparator()
            else:
                toolbar.addAction(a)

        # left: project list
        self.list = QListWidget()
        self.list.setMaximumWidth(280)
        self.list.setStyleSheet("font-size: 13px;")
        self.list.itemSelectionChanged.connect(self._on_select)

        left = QVBoxLayout()
        left.addWidget(QLabel("Projects"))
        left.addWidget(self.list, 1)
        left_w = QWidget()
        left_w.setLayout(left)

        # right: tab bar. Each selected project gets its OWN tab and its OWN
        # webview, so several dashboards can be open side by side (and a
        # _blank popup becomes just another tab). The first tab is a starter
        # pane shown before any project is opened.
        self.placeholder = QLabel("No project selected")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color: gray; font-size: 15px;")
        self.stack = QStackedLayout()
        self.stack.setStackingMode(QStackedLayout.StackAll)
        self.stack.addWidget(self.placeholder)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        starter = QWidget()
        starter.setLayout(self.stack)
        self.dashboard_tab_index = self.tabs.addTab(starter, "Local Project Hub")
        self.tabs.tabBar().setTabButton(self.dashboard_tab_index, QTabBar.RightSide, None)
        # Connect AFTER the starter tab exists: currentChanged can fire during
        # construction, before dashboard_tab_index is set.
        self.tabs.currentChanged.connect(self._on_tab_changed)

        right_w = QWidget()
        right_w.setLayout(QVBoxLayout())
        right_w.layout().setContentsMargins(0, 0, 0, 0)
        right_w.layout().addWidget(self.tabs)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left_w)
        split.addWidget(right_w)
        split.setSizes([260, 900])

        # logs drawer, below the main area. Putting it in the SAME splitter
        # mechanism as the left sidebar means it can be dragged taller/shorter
        # and collapsed out of the way by dragging the divider down, instead
        # of being stuck at a fixed height.
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Menlo, monospace; font-size: 11px;")

        outer = QSplitter(Qt.Vertical)
        outer.addWidget(split)
        outer.addWidget(self.log_view)
        outer.setSizes([620, 160])
        # Let the drawer collapse fully but not the main area.
        outer.setCollapsible(0, False)
        outer.setCollapsible(1, True)
        self.outer_split = outer

        center = QVBoxLayout()
        center.setContentsMargins(6, 6, 6, 0)
        center.addWidget(outer, 1)
        c = QWidget()
        c.setLayout(center)
        self.setCentralWidget(c)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._set_controls_enabled(False)

    # ---------- list ----------

    def _reload_list(self) -> None:
        keep = self.active_id
        self.list.clear()
        for rec in self.store.ordered():
            item = QListWidgetItem(f"{rec['icon']}  {rec['name']}")
            item.setData(Qt.UserRole, rec["id"])
            item.setToolTip(rec.get("description") or rec["command"])
            self.list.addItem(item)
        if keep:
            self._select_id(keep)
        elif self.list.count() and not self.list.currentItem():
            self.list.setCurrentRow(0)

    def _select_id(self, project_id: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == project_id:
                self.list.setCurrentRow(i)
                return

    def _on_select(self) -> None:
        item = self.list.currentItem()
        pid = item.data(Qt.UserRole) if item else None
        self.active_id = pid
        self._set_controls_enabled(pid is not None)
        if pid is None:
            self.stack.setCurrentWidget(self.placeholder)
            self.placeholder.setText("No project selected")
            self.status.showMessage("")
            return
        rec = self.store.get(pid)
        proc = self._proc_for(rec)
        self.status.showMessage(f"{rec['name']}: {_STATE_LABEL.get(proc.state, proc.state)}")

        # If this project already has a tab, just focus it (re-selecting a
        # project should never spawn duplicates). Otherwise open a new tab.
        existing = self._tab_index_for_project(pid)
        if existing is not None:
            self.tabs.setCurrentIndex(existing)
            if proc.state in ("stopped", "error"):
                self._start_active()
            return
        self._open_project_tab(rec)

    def _tab_index_for_project(self, pid: str) -> int | None:
        for i in range(self.tabs.count()):
            if i == self.dashboard_tab_index:
                continue
            if self.tabs.widget(i).property("hub_project_id") == pid:
                return i
        return None

    @property
    def web(self) -> "HubWebView":
        """The webview of the ACTIVE project tab (the starter tab has none)."""
        i = self.tabs.currentIndex()
        if i < 0 or i == self.dashboard_tab_index:
            return None
        w = self.tabs.widget(i)
        return w if isinstance(w, HubWebView) else None

    def _open_project_tab(self, rec: dict) -> None:
        """Open (or focus) a tab holding this project's own dashboard view."""
        view = HubWebView()
        view.setProperty("hub_project_id", rec["id"])
        view.popup_opened.connect(self._on_popup_opened)
        view.loadFinished.connect(self._on_load_finished)
        view.titleChanged.connect(
            lambda t, v=view: self._label_tab(self.tabs.indexOf(v), t or rec["name"])
        )
        idx = self.tabs.addTab(view, f"{rec['icon']}  {rec['name']}")
        self.tabs.setTabToolTip(idx, rec.get("description") or rec["command"])
        self.tabs.setCurrentIndex(idx)

        proc = self._proc_for(rec)
        if not rec.get("url"):
            # No URL configured: start it anyway and learn the address from the
            # server itself (its own output, or the port it opens). Returning
            # here without starting would leave nothing to detect.
            self.status.showMessage(
                f"{rec['name']} has no dashboard URL yet — starting it to find one…"
            )
            self._append_log(
                f"[hub] {rec['name']} has no dashboard URL; starting it to detect one"
            )
            if proc.state != "running":
                self._append_log(f"[hub] starting {rec['name']}: {rec['command']}")
                proc.start()
            # Fallback for a server that never prints its address.
            self._scan_ports_after(rec, proc)
            return
        if proc.state == "running":
            # Already up: load it directly, no polling needed.
            self._show_dashboard(rec)
        else:
            # stopped / error / starting: (re)start and poll for readiness.
            # _start_active() handles the already-running case itself.
            self._start_active()

    def _scan_ports_after(self, rec: dict, proc: ProjectProcess, delay_ms: int = 6000) -> None:
        """For a silent server: look at what ports it opened, once it is up.

        Only runs when no URL is known yet, and gives the server time to bind
        before asking the OS. Best-effort — silence here is not an error.
        """

        def _scan():
            if rec.get("url"):  # meanwhile it announced itself
                return
            url = proc.detect_url_from_ports()
            if url:
                self._append_log(f"[hub] detected listening port: {url}")

        QTimer.singleShot(delay_ms, _scan)

    def _proc_for(self, rec: dict) -> ProjectProcess:
        pid = rec["id"]
        if pid not in self.procs:
            proc = ProjectProcess(rec)
            proc.state_changed.connect(lambda s, p=pid: self._on_state(p, s))
            proc.output.connect(self._append_log)
            proc.url_detected.connect(self._on_url_detected)
            self.procs[pid] = proc
        return self.procs[pid]

    def _on_url_detected(self, url: str) -> None:
        """A server announced its own address — use it and remember it.

        Only fills a gap: if the user configured a URL themselves, theirs wins
        and nothing is overwritten. Saves to the registry so the URL field is
        filled in for next time instead of asking again.
        """
        pid = self.active_id
        rec = self.store.get(pid) if pid else None
        if rec is None or rec.get("url"):
            return
        self._append_log(f"[hub] detected dashboard URL: {url}")
        rec["url"] = url
        try:
            self.store.update(rec)
        except store_mod.RegistryError:
            pass
        self.status.showMessage(f"Detected {rec['name']} at {url}", 6000)
        self._show_dashboard(rec)

    # ---------- popups as tabs (window.open / target="_blank") ----------

    def _on_popup_opened(self, view: "HubWebView") -> None:
        """A dashboard asked for a new view (e.g. the 🪐 spheres page).

        Instead of a separate OS window, the view becomes a tab in this hub
        window. createWindow fires BEFORE QtWebEngine navigates, so the URL is
        empty here; the tab label is set from urlChanged once it is real.
        """
        idx = self.tabs.addTab(view, "New tab")
        self.tabs.setCurrentIndex(idx)
        self._append_log("[hub] opened a new tab")
        # Popups of popups: keep chaining into tabs rather than windows.
        view.popup_opened.connect(self._on_popup_opened)

        def _update(url: QUrl) -> None:
            s = url.toString()
            if not s or s == "about:blank":
                return
            # Label with the page title once known, else a shortened URL.
            view.page().runJavaScript("document.title", lambda t, i=idx: self._set_tab_label(i, t or s))
            self._append_log(f"[hub] new tab: {s}")
            self.status.showMessage(f"New tab: {s}", 6000)

        view.urlChanged.connect(_update)
        view.titleChanged.connect(lambda t, i=idx: self._label_tab(i, t))

    def _label_tab(self, index: int, text: str) -> None:
        text = (text or "").strip()
        if not text or index < 0:
            return
        label = text if len(text) <= 22 else text[:21] + "…"
        self.tabs.setTabText(index, label)
        self.tabs.setTabToolTip(index, text)

    def _close_tab(self, index: int) -> None:
        if index == self.dashboard_tab_index:
            return  # the starter tab is permanent
        widget = self.tabs.widget(index)
        pid = widget.property("hub_project_id") if widget is not None else None
        # Closing a project's tab also stops its backend, so a stopped
        # project never leaves a process running in the background.
        if pid:
            proc = self.procs.get(pid)
            if proc is not None:
                self._append_log(f"[hub] stopping {self.store.get(pid, {}).get('name', pid)} (tab closed)")
                self._user_stopped_ids.add(pid)
                proc.stop()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    def _close_tabs_for_project(self, pid: str) -> None:
        """Close every tab belonging to this project (used when it stops)."""
        for i in range(self.tabs.count() - 1, -1, -1):
            if i == self.dashboard_tab_index:
                continue
            w = self.tabs.widget(i)
            if w is not None and w.property("hub_project_id") == pid:
                self.tabs.removeTab(i)
                w.deleteLater()

    def _on_tab_changed(self, index: int) -> None:
        # The toolbar acts on the project; nothing to do when a popup tab is
        # selected, but keep the title useful.
        if index < 0:
            return
        label = self.tabs.tabText(index)
        if index != self.dashboard_tab_index:
            self.status.showMessage(f"Viewing: {label}", 4000)

    def _on_state(self, pid: str, state: str) -> None:
        rec = self.store.get(pid)
        if rec is None:
            return
        if pid == self.active_id:
            self.status.showMessage(f"{rec['name']}: {_STATE_LABEL.get(state, state)}")
        if state == "error":
            self._append_log(
                f"[hub] {rec['name']} exited with an error — see the log below"
            )
        elif state == "stopped":
            # Close the tabs only for an EXPLICIT stop. A project that exits
            # on its own (or died during startup) keeps its tab so the user
            # can see what happened and press Start again — silently
            # destroying the tab is what left frozen/empty panes before.
            if pid in self._user_stopped_ids:
                self._user_stopped_ids.discard(pid)
                self._close_tabs_for_project(pid)
                w = self.waiters.pop(pid, None)
                if w:
                    w.stop()
                    w.deleteLater()
                if pid == self.active_id:
                    self.active_id = None
                    self.tabs.setCurrentIndex(self.dashboard_tab_index)
        if state == "running" and rec.get("url"):
            self._wait_ready(rec)

    # ---------- dashboard display ----------

    def _show_dashboard(self, rec: dict) -> None:
        if not rec.get("url"):
            return
        view = self.web
        if view is None:
            return
        if view.url().toString() != rec["url"]:
            view.setUrl(QUrl(rec["url"]))

    def _on_load_finished(self, ok: bool) -> None:
        view = self.sender()
        rec = self.store.get(self.active_id) or {}
        if ok:
            return  # the tab is already the visible page
        name = rec.get("name", "project")
        proc = self.procs.get(self.active_id)
        if proc is not None and proc.state == "running":
            # Server says it's up but the page failed — could be a slow
            # first render. Give it one automatic reload before bothering
            # the user.
            self._append_log(f"[hub] {name} page failed to load; retrying\n")
            if view is not None:
                QTimer.singleShot(1200, view.reload)
        else:
            self._append_log(
                f"[hub] {name} is not reachable at {rec.get('url','?')} yet "
                "— the backend may still be starting\n"
            )

    def _wait_ready(self, rec: dict) -> None:
        pid = rec["id"]
        if pid in self.waiters:
            return
        waiter = ReadinessWaiter(rec["url"], timeout_ms=45000)
        self.waiters[pid] = waiter

        def _cleanup():
            w = self.waiters.pop(pid, None)
            if w:
                w.deleteLater()

        def _ready():
            _cleanup()
            if pid == self.active_id:
                self._append_log(f"[hub] {rec['name']} answered at {rec['url']}\n")
                self._show_dashboard(rec)
        def _fail(reason: str):
            _cleanup()
            self._append_log(f"[hub] {reason}\n")
            if pid == self.active_id:
                self.status.showMessage(f"{rec['name']}: {reason}")
                self.placeholder.setText(reason)
                self.stack.setCurrentWidget(self.placeholder)

        waiter.ready.connect(_ready)
        waiter.failed.connect(_fail)
        waiter.start()

    # ---------- logs ----------

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text.rstrip("\n"))

    def _toggle_logs(self, shown: bool) -> None:
        # Collapse the splitter child rather than hiding the widget: a hidden
        # splitter child leaves a dead gap and a divider you can still grab,
        # while collapsing hands the space back to the dashboard.
        total = self.outer_split.size().height()
        if shown:
            self.outer_split.setSizes([max(total - 160, 300), 160])
        else:
            self.outer_split.setSizes([total, 0])

    # ---------- autostart / last project ----------

    def _autostart(self) -> None:
        for rec in self.store.ordered():
            if rec.get("autostart"):
                self._append_log(f"[hub] autostarting {rec['name']}\n")
                proc = self._proc_for(rec)
                proc.start()

    def _restore_last_project(self) -> None:
        pid = self._settings_last()
        if pid and self.store.get(pid):
            self._select_id(pid)
        elif self.list.count():
            self.list.setCurrentRow(0)

    def _settings_path(self):
        return store_mod.default_config_dir() / "ui.json"

    def _settings_last(self) -> str | None:
        try:
            return json.loads(self._settings_path().read_text()).get("last_project")
        except (OSError, json.JSONDecodeError):
            return None

    # ---------- toolbar actions ----------

    def _start_active(self) -> None:
        pid = self.active_id
        if not pid:
            return
        rec = self.store.get(pid)
        proc = self._proc_for(rec)
        if proc.state == "running":
            return
        self._append_log(f"[hub] starting {rec['name']}: {rec['command']}")
        if rec.get("url"):
            # Poll for the dashboard now; when it answers, _ready() points the
            # tab's webview at it. Do not wait on the "running" state signal
            # alone — it can be missed when this runs from the selection handler.
            self._wait_ready(rec)
        proc.start()

    def _stop_active(self) -> None:
        pid = self.active_id
        if not pid:
            return
        # Mark it so _on_state knows this exit was requested (and so the tabs
        # should close). A crash or self-exit must not be treated as a stop.
        self._user_stopped_ids.add(pid)
        self._proc_for(self.store.get(pid)).stop()

    def _restart_active(self) -> None:
        pid = self.active_id
        if not pid:
            return
        rec = self.store.get(pid)
        self._append_log(f"[hub] restarting {rec['name']}\n")
        self.placeholder.setText(f"Restarting {rec['name']}…")
        self.stack.setCurrentWidget(self.placeholder)
        self._proc_for(rec).restart()

    def _open_external(self) -> None:
        pid = self.active_id
        if not pid:
            return
        url = self.store.get(pid).get("url")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _add_project(self) -> None:
        dlg = ProjectDialog(self, base_dir=os.path.expanduser("~"))
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            rec = dlg.result_record()
        except store_mod.RegistryError as e:
            QMessageBox.warning(self, "Invalid project", str(e))
            return
        try:
            self.store.add(rec)
        except store_mod.RegistryError as e:
            QMessageBox.warning(self, "Could not add", str(e))
            return
        self._reload_list()
        self._select_id(rec["id"])

    def _edit_project(self) -> None:
        pid = self.active_id
        if not pid:
            return
        dlg = ProjectDialog(self, record=self.store.get(pid))
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            rec = dlg.result_record()
        except store_mod.RegistryError as e:
            QMessageBox.warning(self, "Invalid project", str(e))
            return
        self.store.update(rec)
        old = self.procs.pop(pid, None)
        if old:
            old.stop()
        self._reload_list()
        self._select_id(pid)

    def _remove_project(self) -> None:
        pid = self.active_id
        if not pid:
            return
        rec = self.store.get(pid)
        if (
            QMessageBox.question(
                self,
                "Remove project",
                f"Remove “{rec['name']}” from the hub?\nFiles are never touched.",
            )
            != QMessageBox.Yes
        ):
            return
        proc = self.procs.pop(pid, None)
        if proc:
            proc.stop()
        self.store.remove(pid)
        self.active_id = None
        self._reload_list()

    def _set_controls_enabled(self, on: bool) -> None:
        for a in (
            self.act_start,
            self.act_stop,
            self.act_restart,
            self.act_ext,
            self.act_edit,
            self.act_remove,
        ):
            a.setEnabled(on)

    # ---------- shutdown ----------

    def closeEvent(self, event) -> None:
        try:
            p = self._settings_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"last_project": self.active_id}, indent=2))
            os.replace(tmp, p)
        except OSError:
            pass
        for proc in self.procs.values():
            proc.stop()
        super().closeEvent(event)
