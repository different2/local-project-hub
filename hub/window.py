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

from . import __version__
from . import diagnostics as diagnostics_mod
from . import launch_at_login, store as store_mod, urldetect
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


def _entry_script(rec: dict) -> str:
    """The script filename a project runs, for matching a stray copy of it.

    "python3 obs_live.py --port 8787" -> "obs_live.py". Used only to identify
    the same project running elsewhere, never to build a command.
    """
    import os

    cmd = (rec or {}).get("command") or ""
    best = ""
    for token in cmd.split():
        base = os.path.basename(token)
        if base.endswith((".py", ".js", ".sh", ".rb", ".pl")):
            if len(base) > len(best):
                best = base
    return best


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
        # True only while the window is being constructed. Selecting a project
        # during startup (populating the sidebar) must not start it — a project
        # runs when the user asks, or when its autostart box is ticked.
        self._starting_up = True

        self._build_ui()
        self._reload_list()
        self._refresh_welcome()
        # The starter tab is already current when the window is built, so
        # currentChanged never fires for it. Apply the starter state once here:
        # show the welcome pane, hide the grey "select a project" hint.
        self.welcome.setVisible(True)
        self.placeholder.setVisible(False)
        self._restore_last_project()
        self._autostart()
        self._starting_up = False

    # ---------- menus: About / Preferences / Updates / Reports ----------

    def _show_about(self) -> None:
        from . import __version__
        from .diagnostics import describe_platform_support

        # A plain QDialog, not a QMessageBox: with no buttons a QMessageBox
        # cannot be dismissed by the keyboard at all (verified — Escape leaves
        # it open), and with a button macOS insists on highlighting it. A bare
        # dialog gets the standard window close (X) and Escape for free, which
        # is how About boxes behave in most macOS apps.
        dlg = QDialog(self)
        dlg.setWindowTitle("About Local Project Hub")
        layout = QVBoxLayout(dlg)
        label = QLabel(
            f"<h3>Local Project Hub</h3>"
            f"<p>Version <b>{__version__}</b></p>"
            f"<p>A control centre for your locally hosted projects.</p>"
            f"<p style='color: gray'>Supports {describe_platform_support()}.</p>"
        )
        label.setTextFormat(Qt.RichText)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(label)
        dlg.setMinimumWidth(380)
        # Close button only. Qt's window-button HINTS cannot do this on macOS —
        # every combination yields some set of traffic lights, never close alone
        # (Qt.Dialog gave red+green, Qt.Tool gave all three). The real buttons
        # are AppKit subviews, hidden individually below. Best-effort: without
        # pyobjc, or on other platforms, the box simply keeps its buttons.
        dlg.setWindowFlags(Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.show()
        self._close_only_window_buttons(dlg)
        dlg.exec()

    @staticmethod
    def _close_only_window_buttons(win) -> None:
        """Hide the minimise/zoom traffic lights, where AppKit is available."""
        try:
            from . import macos_buttons
        except Exception:
            return
        if not macos_buttons.available():
            return
        ns_window = macos_buttons.find_window(win)
        if ns_window is not None:
            macos_buttons.show_only_close_button(ns_window)

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
        # The hub's own tab is closable, so it needs a way back.
        act_home = QAction("Show Overview", self)
        act_home.setShortcut(QKeySequence("Ctrl+1"))
        act_home.triggered.connect(self.open_starter_tab)
        app_menu.addAction(act_home)
        app_menu.addSeparator()
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
        # pane: it explains the app instead of showing an empty grey box.
        self.placeholder = QLabel("Select a project on the left to open its dashboard")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color: gray; font-size: 15px;")
        self.welcome = self._build_welcome_pane()
        self.stack = QStackedLayout()
        self.stack.setStackingMode(QStackedLayout.StackAll)
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.welcome)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._log_tab_close_press)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        starter = QWidget()
        starter.setLayout(self.stack)
        # Mark the WIDGET, not the index. The starter tab is closable now, and
        # a stale index is how "which tab is the hub's own?" silently breaks:
        # after a close, index 0 would be a project tab, and every
        # `index == dashboard_tab_index` check would then misread it.
        starter.setProperty("hub_starter", True)
        self.dashboard_tab_index = self.tabs.addTab(starter, "Local Project Hub")
        self.starter_widget = starter
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
            # Populate the first row WITHOUT starting it: selecting fires the
            # selection handler, which launches the project. During startup the
            # list is only being filled in.
            if self._starting_up:
                self._select_id(self.list.item(0).data(Qt.UserRole), start=False)
            else:
                self.list.setCurrentRow(0)

    def _select_id(self, project_id: str, start: bool = True) -> None:
        """Select a project in the sidebar and, by default, launch it.

        `start=False` restores the selection WITHOUT launching — used at
        startup, where merely reopening the hub must not fire a project (and
        its browser) the user never asked to run.
        """
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == project_id:
                if not start:
                    # Select without launching: open the tab in view-only mode
                    # rather than letting the selection handler start it.
                    self.list.blockSignals(True)
                    self.list.setCurrentRow(i)
                    self.list.blockSignals(False)
                    self.active_id = project_id
                    self._set_controls_enabled(True)
                    self._open_project_tab(self.store.get(project_id), start=False)
                    return
                if self.list.currentRow() == i:
                    # setCurrentRow on the already-current row emits no signal,
                    # so an explicit re-select would silently do nothing. Call
                    # the handler directly.
                    self._on_select()
                else:
                    self.list.setCurrentRow(i)  # fires _on_select
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

    def _build_welcome_pane(self) -> QWidget:
        """The starter tab's content: what this app is and how to drive it.

        The tab is permanent, so it should say something useful rather than
        showing an empty grey box. It is built once; the project count is
        refreshed by _refresh_welcome() whenever projects change.
        """
        pane = QWidget()
        v = QVBoxLayout(pane)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)

        title = QLabel(f"<h2>Local Project Hub</h2><p style='color:gray'>"
                       f"version {__version__}</p>")
        title.setTextFormat(Qt.RichText)
        v.addWidget(title)

        self.welcome_count = QLabel("")
        self.welcome_count.setStyleSheet("color: gray;")
        v.addWidget(self.welcome_count)

        v.addSpacing(8)

        steps = QLabel(
            "<b>Getting started</b><br>"
            "1. Press <b>+ Add Project</b> on the left and give it a command "
            "such as <code>python3 obs_live.py</code>.<br>"
            "2. The dashboard URL is detected automatically — leave that field "
            "blank unless the project needs a fixed one.<br>"
            "3. Click a project in the list to open it here. Adding or "
            "selecting a project never starts it by itself.<br><br>"
            "<b>Things worth knowing</b><br>"
            "• Each project gets its own tab; a project that opens its own "
            "window (a sphere view, say) gets an extra tab you can close.<br>"
            "• The log drawer at the bottom shows what each project prints. "
            "Drag its edge to resize, or collapse it with the arrow.<br>"
            "• If a port is already taken, the hub offers to end the process "
            "holding it instead of failing to start.<br>"
            "• Browser-opening flags such as <code>--no-open</code> are read "
            "from your project's own code, so the app does not guess.<br>"
        )
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        steps.setAlignment(Qt.AlignTop)
        v.addWidget(steps)
        v.addStretch(1)
        return pane

    def _refresh_welcome(self) -> None:
        """Keep the starter tab's project count honest as projects change."""
        if not hasattr(self, "welcome_count"):
            return
        try:
            recs = self.store.ordered()
        except Exception:
            return
        running = sum(
            1 for r in recs
            if (self.procs.get(r["id"]) is not None
                and self.procs[r["id"]].state == "running")
        )
        n = len(recs)
        if n == 0:
            self.welcome_count.setText(
                "No projects registered yet — press + Add Project to begin."
            )
        else:
            self.welcome_count.setText(
                f"{n} project{'s' if n != 1 else ''} registered, "
                f"{running} running."
            )

    def _is_starter_index(self, index: int) -> bool:
        """True when this tab is the hub's own starter tab.

        Checks the widget's property rather than the stored index, so it stays
        correct after the starter is closed and reopened.
        """
        if index is None or index < 0 or index >= self.tabs.count():
            return False
        w = self.tabs.widget(index)
        return w is not None and w.property("hub_starter") is True

    def starter_has_close_button(self) -> bool:
        """Whether the starter tab currently shows a close button.

        The starter tab is closable on request, so this is True whenever the
        tab exists at all.
        """
        return self.starter_index() is not None

    def starter_index(self) -> int | None:
        """The starter tab's current index, or None when it is closed."""
        for i in range(self.tabs.count()):
            if self._is_starter_index(i):
                return i
        return None

    def open_starter_tab(self) -> None:
        """Reopen the hub's own tab after the user closed it.

        The pane itself is kept alive (not destroyed) so reopening is cheap and
        loses nothing. Focuses the existing tab if it is already there.
        """
        existing = self.starter_index()
        if existing is not None:
            self.tabs.setCurrentIndex(existing)
            return
        if getattr(self, "starter_widget", None) is None:
            return
        self.dashboard_tab_index = self.tabs.addTab(
            self.starter_widget, "Local Project Hub"
        )
        self.tabs.setCurrentIndex(self.dashboard_tab_index)
        self._on_tab_changed(self.dashboard_tab_index)

    def _tab_index_for_project(self, pid: str) -> int | None:
        for i in range(self.tabs.count()):
            if self._is_starter_index(i):
                continue
            w = self.tabs.widget(i)
            if w is not None and w.property("hub_project_id") == pid:
                return i
        return None

    @property
    def web(self) -> "HubWebView":
        """The webview of the ACTIVE project tab (the starter tab has none)."""
        i = self.tabs.currentIndex()
        if i < 0 or self._is_starter_index(i):
            return None
        w = self.tabs.widget(i)
        return w if isinstance(w, HubWebView) else None

    def _open_project_tab(self, rec: dict, start: bool = True) -> None:
        """Open (or focus) a tab holding this project's own dashboard view.

        A DESKTOP project is not shown in a webview at all: it opens its own
        native window, so forcing it into an embedded browser would show a blank
        pane next to the real window (spec §4). It is started, and its log is
        still visible, but no tab is created for it.

        `start=False` opens the tab WITHOUT launching the project. Restoring the
        last selection at startup must never start anything: a project should
        run only when the user asks (the Start action, or an autostart project
        whose checkbox is ticked).
        """
        kind = (rec.get("detected") or {}).get("type") or ""
        if kind == "desktop":
            if not start:
                self._append_log(
                    f"[hub] {rec['name']} is a desktop app — press Start to launch it"
                )
                return
            self._append_log(
                f"[hub] {rec['name']} looks like a desktop app — starting it in its "
                f"own window, not in a tab"
            )
            self.status.showMessage(f"{rec['name']} launched in its own window")
            proc = self._proc_for(rec)
            if proc.state != "running":
                self._start_active()
            return

        # One tab per project: re-selecting focuses the existing tab instead of
        # opening a second copy. A duplicate tab shows a stale view and, worse,
        # the stale copy's close button then stops the project out from under
        # the live tab.
        existing = self._tab_index_for_project(rec["id"])
        if existing is not None and existing >= 0:
            self.tabs.setCurrentIndex(existing)
            if start and self._proc_for(rec).state != "running":
                self._start_active()
            return

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

        if not start:
            # Restoring a selection must not launch anything. Show the tab with
            # a clear message instead of a blank pane.
            self.placeholder.setText(
                f"{rec['name']} is not running.\nPress Start, or double-click it, to launch it."
            )
            self.status.showMessage(f"{rec['name']} not started")
            return

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
                # Must go through _start_active so the port-conflict check runs:
                # calling proc.start() here skipped it and started straight into
                # a guaranteed "Address already in use".
                self._start_active()
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
            proc.port_conflict_from_output.connect(
                lambda port, p=pid: self._on_port_conflict_from_output(p, port)
            )
            self.procs[pid] = proc
        return self.procs[pid]

    def _conflict_for_port(self, port: int, exclude: set[int]) -> dict | None:
        """A conflict dict for `port`, or None if no foreign process holds it."""
        owners = urldetect.port_owners(port)
        foreign = owners - exclude
        if not owners or not foreign:
            return None
        return {
            "port": port,
            "host": "127.0.0.1",
            "holders": [
                {"pid": p, "command": urldetect.process_command(p)} for p in sorted(foreign)
            ],
        }

    def _on_port_conflict_from_output(self, pid: str, port: int) -> None:
        """A project died because its port was taken — offer to end the holder.

        This is the path for projects with NO configured URL: the pre-start
        check cannot know which port to look at, but the server's own
        traceback names it. Only prompts if something foreign still holds it.
        """
        proc = self.procs.get(pid)
        if proc is None:
            return
        own = proc._own_pids()
        conflict = self._conflict_for_port(port, own) if port else None
        if conflict is None:
            # The command named no port (e.g. "python3 obs_live.py" uses an
            # in-script default), so look for what is actually holding a port —
            # preferring the failing project's OWN script, so a stray copy of
            # it is what gets offered for ending.
            rec = self.store.get(pid) or {}
            guess = self._guess_taken_port(exclude=own, rec=rec)
            conflict = self._conflict_for_port(guess, own) if guess else None
        if conflict is None:
            # Nothing specific could be determined; say so plainly rather than
            # staying silent.
            self._append_log(
                "[hub] that process could not start because its port was already "
                "in use.\n[hub] If another copy of this project is running, stop it "
                "and press Start again."
            )
            return
        rec = self.store.get(pid)
        if not rec:
            return
        self._offer_to_free_port(rec, proc, conflict)

    def _guess_taken_port(
        self, exclude: set[int], rec: dict | None = None
    ) -> int | None:
        """A port held by a process we did not launch, for a port-less failure.

        Used when a server dies with "Address already in use" but its command
        names no port (the default lives inside the script). Two sources, in
        order of precision:

        1. Any registered project's URL port that is currently held by a
           foreign process — the failure just happened, so it is very likely it.
        2. Any listening port whose owning process runs the SAME script as the
           project that just failed. This catches a stray copy of the project
           when nothing in the registry names a port, which is the user's case.
        """
        for other in self.store.ordered():
            url = other.get("url")
            if not url:
                continue
            try:
                _, port = urldetect.url_host_port(url)
            except Exception:
                continue
            if not port:
                continue
            owners = urldetect.port_owners(port)
            if owners and (owners - exclude):
                return port

        # Fall back to matching the script name: a stray copy of this very
        # project is the usual cause, and it is identifiable by its command.
        # Deliberately narrow — this only ever runs AFTER this project has
        # already failed to bind, never as a pre-flight guess, because scanning
        # unrelated ports would block a legitimate start.
        script = _entry_script(rec or {})
        if script:
            for port in urldetect.listening_ports_all():
                owners = urldetect.port_owners(port)
                if not (owners - exclude):
                    continue
                for owner in owners - exclude:
                    if script in (urldetect.process_command(owner) or ""):
                        return port
        return None

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
            # _label_tab is the real helper; _set_tab_label never existed, so
            # this raised AttributeError on every popup tab whose title
            # resolved -- inside a JS callback, where Qt turned it into a
            # SystemError and killed the test.
            view.page().runJavaScript(
                "document.title", lambda t, i=idx: self._label_tab(i, t or s)
            )
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
        if self._is_starter_index(index):
            # Closing the hub's own tab removes the TAB but keeps the pane, so
            # it can be reopened without rebuilding it. Never deleteLater() the
            # starter widget: that would make reopening impossible.
            label = self.tabs.tabText(index)
            self.tabs.removeTab(index)
            self.dashboard_tab_index = -1
            self._append_log(f"[hub] closed tab '{label.strip()}'")
            return
        widget = self.tabs.widget(index)
        pid = widget.property("hub_project_id") if widget is not None else None
        label = self.tabs.tabText(index)
        # Closing a project's tab also stops its backend, so a stopped
        # project never leaves a process running in the background.
        if pid:
            proc = self.procs.get(pid)
            if proc is not None:
                rec = self.store.get(pid)
                name = (rec or {}).get("name") or pid
                self._append_log(f"[hub] stopping {name} (tab closed)")
                self._user_stopped_ids.add(pid)
                proc.stop()
        self.tabs.removeTab(index)
        self._append_log(f"[hub] closed tab '{label.strip()}'")
        if widget is not None:
            widget.deleteLater()

    def _log_tab_close_press(self, index: int) -> None:
        """Record a close-button press and whether it will do anything.

        Wired to tabCloseRequested BEFORE the real handler, so the log shows
        the press even when the close itself is refused. A press that never
        appears here at all means the click never reached Qt — a different bug
        from a close that is deliberately refused.
        """
        label = self.tabs.tabText(index) if 0 <= index < self.tabs.count() else "?"
        if self._is_starter_index(index):
            self._append_log(
                f"[hub] close pressed on '{label.strip()}' — reopening it is in "
                f"the File menu"
            )
        else:
            self._append_log(f"[hub] close pressed on '{label.strip()}'")

    def _close_tabs_for_project(self, pid: str) -> None:
        """Close every tab belonging to this project (used when it stops)."""
        for i in range(self.tabs.count() - 1, -1, -1):
            if self._is_starter_index(i):
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
        on_starter = self._is_starter_index(index)
        # The starter tab shows the welcome pane; the grey "select a project"
        # hint belongs on top of a project tab that has no dashboard yet.
        self.welcome.setVisible(on_starter)
        self.placeholder.setVisible(not on_starter)
        if on_starter:
            self._refresh_welcome()
        else:
            label = self.tabs.tabText(index)
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
                    # Fall back to the hub's own tab. Reopen it if the user had
                    # closed it, rather than jumping to whatever tab happens to
                    # be left.
                    if self.starter_index() is None:
                        self.open_starter_tab()
                    else:
                        self.tabs.setCurrentIndex(self.starter_index())
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
                # A URL that answers is only THIS project's dashboard if this
                # project's process is actually alive. Otherwise something else
                # owns the port and we would be showing a stranger's page.
                proc = self.procs.get(pid)
                if proc is not None and proc.state != "running":
                    self._append_log(
                        f"[hub] {rec['url']} answered, but {rec['name']} is not running —\n"
                        f"[hub] that page belongs to another process on the same port.\n"
                    )
                    return
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
            # Restore the SELECTION only. This must not start the project: a
            # project runs when the user asks (Start, or a ticked autostart),
            # never merely because it was the last one looked at.
            self._select_id(pid, start=False)
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
        # If something OUTSIDE this hub already holds the project's port, the
        # start is about to fail with "Address already in use". Offer to end
        # that process instead of starting into a guaranteed failure — the
        # usual cause is a stray copy of the same project.
        #
        # This is deliberately synchronous and only reached when the port is
        # actually occupied (port_conflict returns immediately otherwise), so
        # the free-port case — the common one — never runs lsof. An earlier
        # version did this on a QThread, which deadlocked the process under a
        # PTY (the runner), hanging the app indefinitely.
        conflict = proc.port_conflict()
        if conflict:
            self._offer_to_free_port(rec, proc, conflict)
            return
        self._append_log(f"[hub] starting {rec['name']}: {rec['command']}")
        if rec.get("url"):
            # Poll for the dashboard now; when it answers, _ready() points the
            # tab's webview at it. Do not wait on the "running" state signal
            # alone — it can be missed when this runs from the selection handler.
            self._wait_ready(rec)
        proc.start()

    def _launch(self, rec: dict, proc: ProjectProcess) -> None:
        """Start the process and begin waiting for its dashboard."""
        self._append_log(f"[hub] starting {rec['name']}: {rec['command']}")
        if rec.get("url"):
            self._wait_ready(rec)
        proc.start()

    @staticmethod
    def _can_show_dialog() -> bool:
        """Whether a modal dialog could actually be answered.

        A GUI app launched from Finder/Dock has no controlling terminal, so
        testing stdin for a tty wrongly reports "headless" and silently
        downgrades the prompt to a log line. The real test is whether Qt is
        running a GUI platform plugin and this window is on screen.

        Only the explicitly headless platforms (offscreen/minimal, used by the
        test suite) are refused.
        """
        import os

        platform = os.environ.get("QT_QPA_PLATFORM", "").lower()
        if platform in ("offscreen", "minimal", "vnc"):
            return False
        return True

    def _offer_to_free_port(self, rec: dict, proc: ProjectProcess, conflict: dict) -> None:
        """Ask whether to end the process holding this project's port.

        Falls back to a log message instead of a dialog when the environment
        cannot show one (offscreen/headless, or the test runner under a PTY):
        a modal QMessageBox there has nobody to click it and blocks forever.
        """
        holders = conflict["holders"]
        listing = "\n".join(
            f"  PID {h['pid']}: {h['command'] or '(unknown command)'}" for h in holders
        )
        reason = (
            f"port {conflict['port']} is already in use, so {rec['name']} was not "
            f"started: {listing}"
        )

        if not self._can_show_dialog():
            self._append_log(f"[hub] {reason}")
            self.status.showMessage(
                f"{rec['name']} not started — port {conflict['port']} in use"
            )
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Port already in use")
        box.setText(
            f"{rec['name']} uses port {conflict['port']}, which is already taken:"
        )
        box.setInformativeText(
            f"{listing}\n\n"
            "This is usually another copy of the same project, left running from "
            "an earlier launch. End it now?"
        )
        kill_btn = box.addButton("End that process", QMessageBox.AcceptRole)
        box.addButton("Leave it running", QMessageBox.RejectRole)
        box.setDefaultButton(kill_btn)
        box.exec()

        if box.clickedButton() is not kill_btn:
            self._append_log(
                f"[hub] port {conflict['port']} is held by another process; "
                f"{rec['name']} was not started"
            )
            return

        killed = []
        for h in holders:
            if urldetect.kill_process(h["pid"]):
                killed.append(h["pid"])
        self._append_log(
            f"[hub] ended process(es) holding port {conflict['port']}: {killed}"
        )

        def _start_after_free():
            # Give the OS a moment to release the socket.
            if not urldetect.port_in_use(conflict["port"]):
                self._launch(rec, proc)
            else:
                self._append_log(
                    f"[hub] port {conflict['port']} is still in use after ending the "
                    f"process; {rec['name']} was not started"
                )

        QTimer.singleShot(1200, _start_after_free)

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
        self._refresh_welcome()
        # Select the new project but do NOT start it. Adding a project
        # registers it; the user has not asked for it to run yet, and starting
        # here is what fired obs_live (and its own browser) the moment it was
        # added. Press Start, or click it, to launch.
        self._select_id(rec["id"], start=False)

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
        self._refresh_welcome()
        # Editing must not start it either — the project may already be running,
        # and re-selecting would restart it. Just keep the selection.
        self._select_id(pid, start=False)

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
        # The project's tabs must go with it, or a removed project leaves a
        # live dashboard tab behind that nothing can restart or close — the tab
        # outlives the thing it belongs to.
        self._close_tabs_for_project(pid)
        waiter = self.waiters.pop(pid, None)
        if waiter:
            waiter.stop()
            waiter.deleteLater()
        self._user_stopped_ids.discard(pid)
        self.store.remove(pid)
        self.active_id = None
        self._reload_list()
        self._refresh_welcome()

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
