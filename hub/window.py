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

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
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

from . import store as store_mod
from .process_manager import ProjectProcess
from .project_dialog import ProjectDialog
from .readiness import ReadinessWaiter

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

        self._build_ui()
        self._reload_list()
        self._restore_last_project()
        self._autostart()

    # ---------- UI ----------

    def _build_ui(self) -> None:
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

        # right: tab bar over the webview. The project's dashboard is a
        # permanent first tab; _blank popups (🪐 spheres, full replay) become
        # additional tabs inside the hub instead of separate OS windows.
        self.web = HubWebView()
        self.web.popup_opened.connect(self._on_popup_opened)
        self.web.loadFinished.connect(self._on_load_finished)
        self.placeholder = QLabel("No project selected")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color: gray; font-size: 15px;")
        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.addWidget(self.web)
        stack.addWidget(self.placeholder)
        self.stack = stack

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        dash_w = QWidget()
        dash_w.setLayout(stack)
        self.dashboard_tab_index = self.tabs.addTab(dash_w, "Dashboard")
        self.tabs.tabBar().setTabButton(self.dashboard_tab_index, QTabBar.RightSide, None)

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
        if proc.state in ("stopped", "error"):
            self._start_active()
        else:
            self._show_dashboard(rec)

    def _proc_for(self, rec: dict) -> ProjectProcess:
        pid = rec["id"]
        if pid not in self.procs:
            proc = ProjectProcess(rec)
            proc.state_changed.connect(lambda s, p=pid: self._on_state(p, s))
            proc.output.connect(self._append_log)
            self.procs[pid] = proc
        return self.procs[pid]

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
        view.titleChanged.connect(lambda t, i=idx: self._set_tab_label(i, t))

    def _set_tab_label(self, index: int, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Keep labels short so several tabs stay readable.
        label = text if len(text) <= 22 else text[:21] + "…"
        self.tabs.setTabText(index, label)
        self.tabs.setTabToolTip(index, text)

    def _close_tab(self, index: int) -> None:
        if index == self.dashboard_tab_index:
            return  # the project dashboard tab is permanent
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

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
        if pid == self.active_id and rec:
            self.status.showMessage(f"{rec['name']}: {_STATE_LABEL.get(state, state)}")
            # A process that dies right away must not leave "Starting…" up:
            # show why instead of an apparently hung window.
            if state == "error":
                self.placeholder.setText(
                    f"{rec['name']} exited with an error.\n"
                    "Check the log below for the startup output."
                )
                self.stack.setCurrentWidget(self.placeholder)
            elif state == "stopped" and pid in self.waiters:
                w = self.waiters.pop(pid, None)
                if w:
                    w.stop()
                    w.deleteLater()
                self.placeholder.setText(
                    f"{rec['name']} is stopped.\nPress Start to launch it again."
                )
                self.stack.setCurrentWidget(self.placeholder)
        if state == "running" and rec and rec.get("url"):
            self._wait_ready(rec)

    # ---------- dashboard display ----------

    def _show_dashboard(self, rec: dict) -> None:
        if not rec.get("url"):
            self.placeholder.setText(f"{rec['name']} has no dashboard URL")
            self.stack.setCurrentWidget(self.placeholder)
            return
        self.stack.setCurrentWidget(self.web)
        if self.web.url().toString() != rec["url"]:
            self.web.setUrl(QUrl(rec["url"]))

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self.stack.setCurrentWidget(self.web)
        else:
            rec = self.store.get(self.active_id) or {}
            name = rec.get("name", "project")
            proc = self.procs.get(self.active_id)
            if proc is not None and proc.state == "running":
                # Server says it's up but the page failed — could be a slow
                # first render. Give it one automatic reload before bothering
                # the user.
                self._append_log(f"[hub] {name} page failed to load; retrying\n")
                self.stack.setCurrentWidget(self.placeholder)
                self.placeholder.setText(f"{name}: page did not load, retrying…")
                QTimer.singleShot(1200, lambda: self.web.reload())
            else:
                self.placeholder.setText(
                    f"{name} is not reachable at that address yet.\n"
                    "Its backend may still be starting — the page will load "
                    "automatically once it answers.\n"
                    "Check the log below if this persists."
                )
                self.stack.setCurrentWidget(self.placeholder)

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
        self._append_log(f"[hub] starting {rec['name']}: {rec['command']}\n")
        if rec.get("url"):
            self.placeholder.setText(f"Starting {rec['name']}…")
            self.stack.setCurrentWidget(self.placeholder)
            # Poll for the dashboard now; when it answers, _ready() swaps the
            # webview in. Do not wait on the "running" state signal alone —
            # it can be missed when this runs from the selection handler.
            self._wait_ready(rec)
        proc.start()

    def _stop_active(self) -> None:
        pid = self.active_id
        if not pid:
            return
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
