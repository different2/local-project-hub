"""Main window: project list + toolbar + embedded webview + log drawer.

Design notes (matching SPEC's separation principle):
  * One sidebar list of projects. Selecting a row OPENS it — it does not start
    it. The tab shows a start page (project name, command, one Start button)
    and the project runs only when Start is pressed, or when its autostart box
    is ticked. Selecting a row used to launch the backend, which made every
    click in the sidebar a hidden "run this".
  * Toolbar: Start/Stop, Restart, Open in Browser, Add, Edit, Remove.
  * Log drawer at the bottom is a TERMINAL PER PROJECT: each project's
    stdout/stderr goes to its own pane and switching projects switches the
    pane, so one project's output never shows up under another. Hub-level
    messages have their own pane. The drawer is collapsible.
  * A project's failure never blocks another project: every process is its own
    QProcess, and the webview just shows an error page on load failure.
"""

from __future__ import annotations

import json
import os
import weakref
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPalette
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QStatusBar,
    QStyledItemDelegate,
    QTabBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from . import diagnostics as diagnostics_mod
from . import launch_at_login, startpage, store as store_mod, urldetect
from .diagnostics import build_report, format_report, save_report
from .html_storage import HtmlStorageProfiles
from .platform import IS_MACOS, IS_WINDOWS
from .process_manager import ProjectProcess
from .project_dialog import ProjectDialog
from .readiness import ReadinessWaiter
from .static_site import dashboard_url
from .update_dialog import UpdateDialog
from .updater import (
    UpdateError,
    _asset_for_platform,
    fetch_latest_release,
    integrity_problem,
    is_newer,
    verify_sha256,
)

_STATE_LABEL = {
    "stopped": "● stopped",
    "starting": "◌ starting…",
    "stopping": "◌ stopping…",
    "running": "● running",
    "error": "✕ error",
}

# Sidebar rows show "<icon>  <name>", so the name gets a role of its own:
# renaming a project must change the name and nothing else.
_NAME_ROLE = Qt.UserRole + 1


def _short_label(text: str, limit: int = 22) -> str:
    """Trim a tab label, leaving the tooltip to carry the full text."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cancel_readiness(waiters: dict[str, ReadinessWaiter], pid: str) -> None:
    waiter = waiters.pop(pid, None)
    if waiter is not None:
        waiter.stop()
        waiter.deleteLater()


class _PopupBridge(QObject):
    """Kept for import compatibility; the popup path now uses createWindow."""


class _HubPage(QWebEnginePage):
    """Intercepts the buttons drawn on the start/status page.

    A custom `hub://` scheme cannot be used for this: QtWebEngine drops clicks
    on an unknown scheme without ever calling acceptNavigationRequest for them
    (verified with a probe — the request never arrives). An ordinary https URL
    on a host that does not resolve does reach us, so the page links to
    `https://hub.invalid/start/<id>` and this refuses the navigation while
    emitting what was asked for.
    """

    start_requested = Signal(str)
    stop_requested = Signal(str)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        if url.host() == startpage.ACTION_HOST:
            parts = [p for p in url.path().split("/") if p]
            action = parts[0] if parts else ""
            pid = unquote(parts[1]) if len(parts) > 1 else ""
            if pid and action == "start":
                # Emitting while this navigation callback is still on the stack
                # runs start(), which emits "starting", which renders the start
                # page with setHtml() -- re-entering QtWebEngine mid-navigation.
                # On Windows that crashes with 0x80000003. Defer one event-loop
                # turn so the page callback has returned first.
                QTimer.singleShot(0, lambda p=pid: self.start_requested.emit(p))
            elif pid and action == "stop":
                QTimer.singleShot(0, lambda p=pid: self.stop_requested.emit(p))
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


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
    #: Emitted when the user presses Start (or Stop) on a page this view shows.
    start_requested = Signal(str)
    stop_requested = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        page = _HubPage(self)
        page.start_requested.connect(self.start_requested)
        page.stop_requested.connect(self.stop_requested)
        self.setPage(page)

    def use_profile(self, profile: QWebEngineProfile) -> None:
        """Install a project's profile only when it actually changes."""
        if self.page().profile() is profile:
            return
        page = _HubPage(profile, self)
        page.start_requested.connect(self.start_requested)
        page.stop_requested.connect(self.stop_requested)
        self.setPage(page)

    def createWindow(self, window_type):
        # NOTE: PySide6 expects the QWebEngineView itself here, not .page() —
        # returning a page raises RuntimeWarning and the popup never navigates.
        # No show(): as a tab child the QTabWidget owns visibility. Calling
        # show() here would pop a floating window.
        view = HubWebView()
        view.use_profile(self.page().profile())
        # Child tabs share the opener's project for controls/logs, but are not
        # another primary dashboard: closing one must not stop its backend.
        view.setProperty("hub_owner_project_id", self.property("hub_project_id")
                         or self.property("hub_owner_project_id"))
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


class _NameEditDelegate(QStyledItemDelegate):
    """Inline-edit a project's NAME, not the icon glued onto its row text.

    A QListWidgetItem hands its whole display string ("icon  name") to the
    editor, so double-clicking would put "🌐  obs_live" in the box and let the
    icon be deleted by accident. The name lives in its own role; this delegate
    edits only that.
    """

    def setEditorData(self, editor, index) -> None:  # noqa: N802 - Qt API
        editor.setText(index.data(_NAME_ROLE) or "")

    def setModelData(self, editor, model, index) -> None:  # noqa: N802 - Qt API
        name = editor.text().strip()
        if name:
            model.setData(index, name, _NAME_ROLE)


class LogDrawer(QWidget):
    """The bottom drawer: one terminal panel per project, plus one for the hub.

    Every project's output goes to its OWN pane, and switching projects
    switches the pane, so a line printed by one project can never appear under
    another (the single shared view is what made them indistinguishable).
    Panes are created on first use and kept, so a project's history is still
    there when the user comes back to it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.header = QLabel("Logs")
        self.header.setStyleSheet("color: gray; font-size: 11px; padding: 2px 6px;")
        self.clear_button = QPushButton("Clear log")
        self.clear_button.setToolTip("Clear this pane's past events; running projects are unaffected")
        self.clear_button.clicked.connect(self.clear_current)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 6, 0)
        header_row.addWidget(self.header, 1)
        header_row.addWidget(self.clear_button)
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(header_row)
        lay.addWidget(self.stack, 1)
        self._edits: dict[str, QPlainTextEdit] = {}
        self._hub = self._make_edit()
        self._edits[""] = self._hub
        self.stack.addWidget(self._hub)
        self._current = ""

    def _make_edit(self) -> QPlainTextEdit:
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setStyleSheet("font-family: Menlo, monospace; font-size: 11px;")
        return edit

    def _edit_for(self, key) -> QPlainTextEdit:
        k = key or ""
        edit = self._edits.get(k)
        if edit is None:
            edit = self._make_edit()
            self._edits[k] = edit
            self.stack.addWidget(edit)
        return edit

    def show_page(self, key) -> None:
        """Show one project's terminal (key=None shows the hub's own)."""
        self._current = key or ""
        self.stack.setCurrentWidget(self._edit_for(key))

    def drop_page(self, key) -> None:
        """Forget a project's pane; nothing stale lingers for a re-add."""
        k = key or ""
        edit = self._edits.pop(k, None)
        if edit is None:
            return
        self.stack.removeWidget(edit)
        edit.deleteLater()
        if self._current == k:
            self.show_page(None)

    def set_header(self, text: str) -> None:
        self.header.setText(text)

    def clear_current(self) -> None:
        """Clear the displayed pane's stored history, not any process state."""
        self._edit_for(self._current).clear()

    def append_for(self, text: str, key=None) -> None:
        # Timestamp at ingestion, including background output. Switching panes
        # must not restamp history or leave multiline tracebacks undated.
        stamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        lines = text.rstrip("\r\n").splitlines()
        if lines:
            self._edit_for(key).appendPlainText(
                "\n".join(f"{stamp} {line}" for line in lines)
            )

    # The rest of the window (and the tests) talk to the drawer as if it were
    # the old single QPlainTextEdit: these use the visible pane.
    def appendPlainText(self, text: str) -> None:
        self.append_for(text, self._current)

    def toPlainText(self) -> str:
        return self._edit_for(self._current).toPlainText()

    def hub_text(self) -> str:
        """The hub's own pane only — never a project's raw terminal output."""
        return self._hub.toPlainText()


class HubWindow(QMainWindow):
    def __init__(self, store: store_mod.Store):
        super().__init__()
        self.setWindowTitle("Local Project Hub")
        self.resize(1180, 780)
        self.store = store
        self._html_storage = HtmlStorageProfiles(store.path.parent, self)
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
        # True while the sidebar is being (re)filled: a programmatic text
        # change must not be mistaken for the user renaming a project.
        self._loading_list = False

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
        """Help → Check for Updates (release spec §5).

        Everything this does is shown in one obvious dialog (user request,
        2026-10-18): it appears on the click and stays for the whole
        sequence -- checking, up to date / version available, download
        progress -- instead of hiding behind the status bar.
        """
        dlg = self._update_widget()
        if getattr(self, "_update_busy", False):
            # A check or a download is already running; just bring its dialog
            # back instead of stacking a second one.
            dlg.reveal()
            return
        self._update_busy = True
        self.status.showMessage("Checking for updates…")
        dlg.show_checking()
        result = {"release": None, "error": None}

        def _work():
            try:
                result["release"] = fetch_latest_release()
            except UpdateError as e:
                result["error"] = str(e)
            except Exception as e:  # never let a check crash the app
                result["error"] = f"Update check failed: {e}"

        def _done(res=None):
            # `res` is the worker's return value -- unused here, since the
            # check records its outcome in the `result` dict instead. The
            # parameter must exist anyway: _run_offline_safe calls
            # done(worker.result), and without it every branch of this check
            # died as a TypeError inside a Qt slot, which swallows exceptions
            # -- the feature silently did nothing (found by a real click,
            # 2026-10-17).
            self._update_busy = False
            err, release = result["error"], result["release"]
            self.status.clearMessage()
            if err:
                self._append_log(f"[hub] update check failed: {err}")
                dlg.show_error("Couldn't check for updates", err)
                return
            if not is_newer(release.version):
                dlg.show_up_to_date(__version__)
                return
            self._pending_update = (release, _asset_for_platform(release.assets))
            dlg.show_available(release, self._pending_update[1])

        self._run_offline_safe(_work, _done)

    def _update_widget(self) -> UpdateDialog:
        """One reusable update dialog per window (created on first use)."""
        dlg = getattr(self, "_update_dialog", None)
        if dlg is None:
            dlg = self._update_dialog = UpdateDialog(self)
            dlg.request_download.connect(self._download_pending_update)
            dlg.install_now.connect(self._restart_and_install)
        return dlg

    def _download_pending_update(self) -> None:
        release, asset = getattr(self, "_pending_update", (None, None))
        if release is not None:
            self._download_update(release, asset)



    def _download_update(self, release, asset) -> None:
        """Download to a temp file, verify, then hand off to the OS installer.

        Never replaces the running executable in place (release spec §5): the
        artifact is staged, integrity-checked, and the platform installer is
        launched, which asks the user before touching anything. Progress goes
        to the update dialog, which stays up for the whole download -- a
        250 MB silence made the app look frozen (user report, 2026-10-18).
        """
        dlg = self._update_widget()
        if asset is None:
            dlg.show_error(
                "No installer for this platform",
                "This release does not include an installer for your platform yet.",
            )
            return
        # Fail closed BEFORE downloading: without a trustworthy expected digest
        # there is no way to know the installer is the one the release
        # published, so it must not be run.
        unverifiable = integrity_problem(asset)
        if unverifiable:
            self.status.clearMessage()
            self._append_log(f"[hub] update not started: {unverifiable}")
            dlg.show_error("The update can't be verified", unverifiable)
            return
        self._update_busy = True
        self.status.showMessage(f"Downloading {asset.name}…")
        self._append_log(f"[hub] downloading update {asset.name}")
        dlg.show_downloading(asset.name, asset.size or 0)

        # The worker thread only bumps these counters; a GUI-thread timer
        # reads them into the dialog. The worker must never touch widgets.
        progress = {"done": 0, "total": asset.size or 0}

        def _work():
            from .updater import download_asset, safe_update_destination

            try:
                # The release asset name is metadata, not a trusted path. It is
                # validated as a plain filename and resolved inside the temp
                # directory before anything is written.
                dest = safe_update_destination(asset.name)
            except UpdateError as e:
                return None, str(e)
            try:
                download_asset(
                    asset,
                    dest,
                    on_progress=lambda done, total: progress.update(
                        done=done, total=total or progress["total"]
                    ),
                )
            except Exception as e:
                # A partial download is never left staged for an installer.
                try:
                    dest.unlink()
                except OSError:
                    pass
                return None, f"Download failed: {e}"
            if not verify_sha256(dest, asset.sha256):
                try:
                    dest.unlink()
                except OSError:
                    pass
                return None, (
                    "The downloaded file did not match its published checksum, "
                    "so it was discarded."
                )
            return dest, None

        timer = QTimer(self)
        timer.setInterval(250)
        timer.timeout.connect(
            lambda: dlg.set_progress(progress["done"], progress["total"])
        )
        timer.start()

        def _done(res):
            timer.stop()
            timer.deleteLater()
            self._update_busy = False
            dest, err = res if res else (None, "Download failed.")
            if err:
                self.status.clearMessage()
                self._append_log(f"[hub] update failed: {err}")
                dlg.show_error("The update didn't finish", err)
                return
            self.status.clearMessage()
            self._append_log(f"[hub] update downloaded to {dest}")
            if IS_MACOS:
                # Stage the new .app now, so "restart" is all the user has to
                # do; the disk-image hand-off stays as the fallback.
                self._prepare_macos_update(dest, release)
            else:
                dlg.close()
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
                    "then reopen it. Your projects and settings are untouched.\n\n"
                    "If macOS refuses to open the new copy — \"Apple cannot check "
                    "it for malicious software\" — Control-click the app and choose "
                    "Open once to allow it. This build is not notarised, so macOS "
                    "asks the first time it sees a new copy.",
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

    def _prepare_macos_update(self, dmg: Path, release) -> None:
        """Stage the new .app so that a restart is all the user has to do.

        The swap itself happens in ``hub.selfupdate``'s script after this
        process is gone. Anything that goes wrong here falls back to the
        disk-image hand-off, so an update is never left half offered.
        """
        from . import selfupdate

        ok, why = selfupdate.can_self_install()
        if not ok:
            self._append_log(f"[hub] self-install not available: {why}")
            self._update_widget().close()
            self._launch_installer(dmg)
            return

        dlg = self._update_widget()
        dlg.show_preparing(release.version)

        def _work():
            try:
                return selfupdate.stage_app_from_dmg(dmg, selfupdate.workdir()), None
            except Exception as e:  # noqa: BLE001 - reported in the dialog
                return None, f"{type(e).__name__}: {e}"

        def _done(res):
            staged, err = res
            if err:
                self._append_log(f"[hub] could not prepare the update: {err}")
                dlg.show_error(
                    "Could not prepare the update",
                    f"{err}\n\nThe downloaded disk image has been opened "
                    "instead — drag the app across to finish.",
                )
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(dmg)))
                return
            self._pending_install = str(staged)
            self._pending_install_version = release.version
            self._append_log(f"[hub] update staged at {staged}")
            dlg.show_ready_to_install(release.version)

        self._run_offline_safe(_work, _done)

    def _restart_and_install(self) -> None:
        """Quit so the staged script can swap the bundle and reopen the app."""
        from . import selfupdate

        staged = getattr(self, "_pending_install", None)
        target = selfupdate.bundle_path()
        if not staged or target is None:
            return
        try:
            script = selfupdate.schedule_install(Path(staged), target, os.getpid())
        except Exception as e:  # noqa: BLE001 - the user must see what happened
            self._append_log(f"[hub] could not start the installer: {e}")
            QMessageBox.warning(
                self,
                "Update",
                f"Could not start the installer.\n\n{e}\n\nThe update is "
                f"staged at:\n{staged}",
            )
            return
        self._append_log(f"[hub] restarting to install the update ({script})")
        self._update_widget().close()
        self.status.showMessage("Installing the update…")
        QTimer.singleShot(100, self.close)

    def _sensitive_context(self) -> tuple[list[str], list[str]]:
        """Project-specific values and names for every report path."""
        sensitive: list[str] = []
        names: list[str] = []
        for rec in self.store.projects.values():
            name = rec.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name)
            for key in (
                "description",
                "command",
                "args",
                "working_dir",
                "interpreter",
                "url",
            ):
                value = rec.get(key)
                if isinstance(value, str) and value.strip():
                    sensitive.append(value)
            env = rec.get("env")
            if isinstance(env, dict):
                sensitive.extend(str(v) for v in env.values())
        return sensitive, names

    def _refresh_diagnostic_context(self) -> tuple[list[str], list[str]]:
        """Publish the current identity for the crash-report path too."""
        sensitive, names = self._sensitive_context()
        diagnostics_mod.set_project_context(sensitive, names)
        return sensitive, names

    def _diagnostic_report(self) -> dict:
        """Build the sanitised report that Report a Problem actually exports.

        Only the hub's own log pane is passed, and every project-specific value
        is supplied as an exact sensitive value or a project name so the
        formatter can remove it. This is the single source for the saved file,
        the copied text and the prefilled issue URL; the same context is
        registered for exception reports.
        """
        sensitive, names = self._refresh_diagnostic_context()
        return diagnostics_mod.build_report(
            log_tail=self.log_view.hub_text(),
            project_count=len(self.store.projects),
            sensitive=sensitive,
            project_names=names,
        )

    def _report_problem(self) -> None:
        """Help → Report a Problem: save a sanitised report, or open an issue."""
        from . import diagnostics

        report = self._diagnostic_report()

        box = QMessageBox(self)
        box.setWindowTitle("Report a problem")
        box.setText(
            "This creates a report with the app version, your operating system, "
            "and a sanitised summary of the hub's own messages.\n\n"
            "It does <b>not</b> include your projects' names, folders, commands, "
            "raw output, dashboard contents, or URLs."
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
        two call sites need, and a crash inside `work` -- or inside `done` --
        is reported rather than silently swallowed.

        Contract: `done` is called on the GUI thread as `done(worker.result)`,
        receiving whatever `work()` returned.
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
            try:
                done(worker.result)
            except Exception as e:  # noqa: BLE001 - a callback bug must not vanish
                # Qt swallows exceptions raised inside slots, which is how a
                # callback-signature mistake made Check for Updates silently do
                # nothing for weeks. Report it like any other failure.
                self.status.clearMessage()
                QMessageBox.warning(
                    self, "Something went wrong", f"{type(e).__name__}: {e}"
                )

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
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        # Save after the model finishes moving rows. In particular, a failed
        # write must not rebuild the list from inside its own move notification.
        self.list.model().rowsMoved.connect(self._on_list_reordered, Qt.QueuedConnection)
        self.list.itemSelectionChanged.connect(self._on_select)
        # Double-click (or Return) renames a project in place, the way a
        # session is renamed in the sidebar. The icon is part of the row's
        # display text, so the delegate edits a separate role and only the
        # name changes.
        self.list.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.list.setItemDelegate(_NameEditDelegate(self.list))
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_list_menu)

        left = QVBoxLayout()
        left.addWidget(QLabel("Projects"))
        rename_hint = QLabel("Drag to reorder · Double-click to rename")
        rename_hint.setStyleSheet("color: gray; font-size: 10px;")
        left.addWidget(rename_hint)
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
        # One terminal pane per project (LogDrawer): switching projects
        # switches the pane, so output cannot carry over between them.
        self.log_view = LogDrawer()

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
        """Repaint registrations without navigating or activating a project."""
        keep = self.active_id
        self._loading_list = True
        was_blocked = self.list.blockSignals(True)
        try:
            self.list.clear()
            for rec in self.store.ordered():
                item = QListWidgetItem(self._item_label(rec))
                item.setData(Qt.UserRole, rec["id"])
                item.setData(_NAME_ROLE, rec["name"])
                # This is a flat list: drop BETWEEN rows, not onto a parent.
                item.setFlags((item.flags() | Qt.ItemIsEditable) & ~Qt.ItemIsDropEnabled)
                item.setToolTip(rec.get("description") or rec["command"])
                self.list.addItem(item)
                if rec["id"] == keep:
                    self.list.setCurrentItem(item)
        finally:
            self.list.blockSignals(was_blocked)
            self._loading_list = False
        # Opening/restoring a tab is a separate action. In particular, Add and
        # failed-order rollback must not focus an old sidebar selection over
        # the browser tab the user is actually viewing.
        self._refresh_diagnostic_context()

    def _on_list_reordered(self) -> None:
        """Persist the visible ID order without touching project tabs/processes."""
        if self._loading_list:
            return
        project_ids = [
            self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
        ]
        try:
            self.store.reorder(project_ids)
        except store_mod.RegistryError as e:
            self._reload_list()
            message = f"Couldn't save project order: {e}"
            self.status.showMessage(message, 8000)
            self._append_log(f"[hub] {message}")
            return
        self.status.showMessage("Project order saved", 3000)

    def _item_label(self, rec: dict) -> str:
        return f"{rec.get('icon') or ''}  {rec.get('name') or ''}"

    def _paint_item(self, item: QListWidgetItem, rec: dict) -> None:
        """Rewrite a row (icon + name) without it looking like a rename."""
        self._loading_list = True
        try:
            item.setData(_NAME_ROLE, rec.get("name") or "")
            item.setText(self._item_label(rec))
            item.setToolTip(rec.get("description") or rec.get("command") or "")
        finally:
            self._loading_list = False

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """The sidebar's inline editor committed a new display name."""
        if self._loading_list:
            return
        pid = item.data(Qt.UserRole)
        rec = self.store.get(pid) if pid else None
        if rec is None:
            return
        wanted = str(item.data(_NAME_ROLE) or "").strip()
        old = rec.get("name") or ""
        if not wanted or wanted == old:
            self._paint_item(item, rec)
            if not wanted:
                self.status.showMessage(
                    "A project needs a name — kept the old one.", 6000
                )
            return
        updated = dict(rec)
        updated["name"] = wanted
        try:
            self.store.update(updated)
        except store_mod.RegistryError as e:
            self._paint_item(item, rec)
            QMessageBox.warning(self, "Couldn't rename", str(e))
            return
        self._paint_item(item, updated)
        self._retitle_tab(pid, self._item_label(rec), updated)
        self.status.showMessage(f"Renamed to “{wanted}”", 6000)

    def _retitle_tab(self, pid: str, old_label: str, rec: dict) -> None:
        """Update a project's tab title if it still shows the old default."""
        idx = self._tab_index_for_project(pid)
        if idx is None or self.tabs.tabText(idx) != _short_label(old_label):
            return
        self.tabs.setTabText(idx, _short_label(self._item_label(rec)))
        self.tabs.setTabToolTip(idx, rec.get("description") or rec["command"])

    def _on_list_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        edit = menu.addAction("Edit project…")
        menu.addSeparator()
        remove = menu.addAction("Remove…")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is rename:
            self.list.setFocus()
            self.list.editItem(item)
        elif chosen is edit:
            self._edit_project()
        elif chosen is remove:
            self._remove_project()

    def _select_id(self, project_id: str, start: bool = True) -> None:
        """Select a project in the sidebar; with `start=True`, also run it.

        Selecting alone never launches anything any more — the tab opens on its
        start page. `start=True` is the explicit "open and run" path used by
        tests and by the toolbar; `start=False` restores a selection without
        launching, which is what startup does.
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
                    self._sync_log_page(project_id)
                    self._open_project_tab(self.store.get(project_id), start=False)
                    return
                if self.list.currentRow() == i:
                    # setCurrentRow on the already-current row emits no signal,
                    # so an explicit re-select would silently do nothing. Call
                    # the handler directly.
                    self._on_select()
                else:
                    self.list.setCurrentRow(i)  # fires _on_select
                if start:
                    self._start_active()
                return

    def _on_select(self) -> None:
        item = self.list.currentItem()
        pid = item.data(Qt.UserRole) if item else None
        self.active_id = pid
        self._set_controls_enabled(pid is not None)
        # The terminal follows the project: each one has its own pane.
        self._sync_log_page(pid)
        if pid is None:
            self.stack.setCurrentWidget(self.placeholder)
            self.placeholder.setText("No project selected")
            self.status.showMessage("")
            return
        rec = self.store.get(pid)
        proc = self._proc_for(rec)

        display_state = "stopping" if proc.is_stopping else proc.state
        self.status.showMessage(f"{rec['name']}: {_STATE_LABEL.get(display_state, display_state)}")

        # Opening a project's tab must not start anything. Selecting a row was
        # a hidden "run this" button: one click in the sidebar launched a
        # server, or a bot, or both. The tab opens on a start page instead and
        # the project runs when Start is pressed (reported 2026-10-20).
        self._open_project_tab(rec, start=False)

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
            "3. Click a project in the list to open its tab, then press "
            "<b>Start</b> on that page. Opening a project — or adding one — "
            "never starts it.<br><br>"
            "<b>Things worth knowing</b><br>"
            "• Each project gets its own tab; a project that opens its own "
            "window (a sphere view, say) gets an extra tab you can close.<br>"
            "• Each project has its own terminal in the drawer at the bottom; "
            "switching projects switches the terminal. Drag its edge to "
            "resize, or collapse it with the arrow.<br>"
            "• Drag projects in the list to reorder them; double-click a name to rename it.<br>"
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
                    f"[hub] {rec['name']} is a desktop app — press Start to launch it",
                    rec["id"],
                )
                return
            self._append_log(
                f"[hub] {rec['name']} looks like a desktop app — starting it in its "
                f"own window, not in a tab",
                rec["id"],
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
            # Focusing is not navigation. Refreshing here can reload a live
            # dashboard (including URL normalization/redirects) and discard its
            # uploaded images or other in-memory state. Process state changes
            # and explicit Restart already update the project's own page.
            self.tabs.setCurrentIndex(existing)
            if start and self._proc_for(rec).state != "running":
                self._start_active()
            return

        view = HubWebView()
        view.use_profile(self._profile_for(rec))
        view.setProperty("hub_project_id", rec["id"])
        view.popup_opened.connect(self._on_popup_opened)
        view.loadFinished.connect(self._on_load_finished)
        view.start_requested.connect(self._on_start_requested)
        view.stop_requested.connect(self._on_stop_requested)
        view.titleChanged.connect(
            lambda t, v=view: self._label_tab(self.tabs.indexOf(v), t or rec["name"])
        )
        idx = self.tabs.addTab(view, _short_label(self._item_label(rec)))
        self.tabs.setTabToolTip(idx, rec.get("description") or rec["command"])
        self.tabs.setCurrentIndex(idx)

        proc = self._proc_for(rec)
        if not start:
            # Opening a tab never launches anything: show the start page and
            # let the user decide (or, if it is already running, show what it
            # has to show).
            self._refresh_project_page(rec)
            return

        if rec.get("url"):
            if proc.state == "running":
                self._show_dashboard(rec)
            else:
                self._start_active()
            return

        # No URL configured: start it and learn the address from the server
        # itself (its own output, or the port it opens).
        self.status.showMessage(
            f"{rec['name']} has no dashboard URL yet — starting it to find one…"
        )
        self._append_log(
            f"[hub] {rec['name']} has no dashboard URL; starting it to detect one",
            rec["id"],
        )
        if proc.state != "running":
            # Must go through _start_active so the port-conflict check runs:
            # calling proc.start() here skipped it and started straight into
            # a guaranteed "Address already in use".
            self._start_active()
        # Fallback for a server that never prints its address.
        self._scan_ports_after(rec, proc)

    # ---------- the page a tab shows when it has no dashboard ----------

    def _page_colors(self) -> dict:
        """The app's own colours, so a start page looks like the rest of it."""
        pal = self.palette()
        bg = pal.color(QPalette.Window)
        fg = pal.color(QPalette.WindowText)
        return {
            "bg": bg.name(),
            "fg": fg.name(),
            "muted": pal.color(QPalette.PlaceholderText).name(),
            "accent": pal.color(QPalette.Highlight).name(),
            "accent_fg": pal.color(QPalette.HighlightedText).name(),
        }

    def _view_for(self, pid: str) -> "HubWebView | None":
        """The webview of THIS project's tab, whichever tab is on screen."""
        idx = self._tab_index_for_project(pid)
        if idx is None:
            return None
        w = self.tabs.widget(idx)
        return w if isinstance(w, HubWebView) else None

    def _set_tab_page(self, rec: dict, html_text: str) -> None:
        view = self._view_for(rec["id"])
        if view is None:
            return
        # Remember what was rendered: a hub page is not a dashboard, so the URL
        # alone cannot say which of the two a tab is showing.
        view.setProperty("hub_page_html", html_text)
        # setHtml with a base URL: without one the page has an opaque origin
        # and relative links/log lines behave oddly.
        view.setHtml(html_text, QUrl("about:blank"))

    def _show_start_page(self, rec: dict, state: str = "stopped", detail: str = "") -> None:
        self._set_tab_page(
            rec,
            startpage.start_page_html(
                rec, state=state, detail=detail, colors=self._page_colors()
            ),
        )

    def _refresh_project_page(self, rec: dict) -> None:
        """Show the right page for a project's tab, given how it is running."""
        if (rec.get("detected") or {}).get("type") == "desktop":
            return  # desktop projects have no tab of their own
        proc = self._proc_for(rec)
        if proc.is_stopping:
            self._show_start_page(rec, state="stopping")
        elif proc.state == "running":
            if rec.get("url"):
                self._show_dashboard(rec)
            else:
                self._show_start_page(rec, state="running")
        elif proc.state == "starting":
            self._show_start_page(rec, state="starting")
        else:
            self._show_start_page(rec, state="stopped")

    def _on_start_requested(self, pid: str) -> None:
        """The Start button on a project's own page was pressed."""
        if not pid:
            return
        if pid != self.active_id:
            self._select_project(pid)
        self._start_active()

    def _on_stop_requested(self, pid: str) -> None:
        if not pid:
            return
        self._select_project(pid)
        self._stop_active()

    def _scan_ports_after(self, rec: dict, proc: ProjectProcess, delay_ms: int = 6000) -> None:
        """For a silent server: look at what ports it opened, once it is up.

        Only runs when no URL is known yet, and gives the server time to bind
        before asking the OS. Best-effort — silence here is not an error.
        """

        pid, generation = rec["id"], proc._generation

        def _scan():
            current = self.store.get(pid)
            if (current is None or current.get("url")
                    or self.procs.get(pid) is not proc
                    or proc._generation != generation or proc.state != "running"
                    or (current.get("detected") or {}).get("type") == "desktop"):
                return
            url = proc.detect_url_from_ports()
            if url:
                self._append_log(f"[hub] detected listening port: {url}", rec["id"])

        QTimer.singleShot(delay_ms, _scan)

    def _proc_for(self, rec: dict) -> ProjectProcess:
        pid = rec["id"]
        if pid not in self.procs:
            proc = ProjectProcess(rec)
            # Edit/Remove replaces this owner. Late events from the old process
            # must not change its successor; a weak origin avoids a new cycle.
            owner = weakref.ref(proc)
            proc.state_changed.connect(
                lambda s, p=pid, origin=owner: self._on_state(p, s)
                if origin() is not None and self.procs.get(p) is origin() else None
            )
            proc.output.connect(lambda text, p=pid: self._append_log(text, p))
            # Carry the originating project id through the signal. Without it
            # the handler used self.active_id, so a background project's URL
            # was saved against whichever project the user happened to be
            # viewing when the server announced itself.
            proc.url_detected.connect(
                lambda u, p=pid, origin=owner: self._on_url_detected(u, p)
                if origin() is not None and self.procs.get(p) is origin() else None
            )
            proc.port_conflict_from_output.connect(
                lambda port, p=pid, origin=owner: self._on_port_conflict_from_output(p, port)
                if origin() is not None and self.procs.get(p) is origin() else None
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
            # The port came from output, not a verified endpoint address.
            "host": None,
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
                "and press Start again.",
                pid,
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

    def _on_url_detected(self, url: str, pid: str | None = None) -> None:
        """A project announced its own address — use it and remember it.

        `pid` is the project whose process emitted the signal, NOT whatever is
        selected now: autostart can leave several projects running and the user
        can switch tabs before one prints its banner.

        The address belongs to the project whose process printed it, which is
        not necessarily the selected one: a project running in the background
        announces itself too. Writing that URL onto the active row both loses
        it and points the wrong dashboard at it (reported 2026-10-19).

        Only fills a gap: if the user configured a URL themselves, theirs wins
        and nothing is overwritten. Saves to the registry so the URL field is
        filled in for next time instead of asking again.
        """
        pid = pid or self.active_id
        rec = self.store.get(pid) if pid else None
        if rec is None or rec.get("url"):
            return
        self._append_log(f"[hub] detected dashboard URL: {url}", rec["id"])
        rec["url"] = url
        try:
            self.store.update(rec)
        except store_mod.RegistryError:
            pass
        if pid == self.active_id:
            self.status.showMessage(f"Detected {rec['name']} at {url}", 6000)
        # Navigate the emitting project's own tab, wherever it is in the tab
        # bar. _show_dashboard() used to read self.web (the ACTIVE tab), so a
        # background detection either did nothing or pointed the wrong tab at
        # the URL.
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
        owner = view.property("hub_owner_project_id")
        self._append_log("[hub] opened a new tab", owner)
        # Every adopted view reports directly to the Hub, exactly once. An
        # opener can be deleted while its nested tabs survive, so forwarding
        # through that opener would silently disconnect their future popups.
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
            # PySide6 6.7.3 (the pinned version) has no two-argument
            # runJavaScript(script, callable) overload; the callback form is
            # (script, worldId, callback). The newer two-argument form raised
            # TypeError inside a Qt slot on 6.7.3, so the title callback
            # silently never ran and popup tabs kept their placeholder label.
            view.page().runJavaScript(
                "document.title", 0,
                lambda t, v=view: self._label_tab(self.tabs.indexOf(v), t or s)
            )
            self._append_log(f"[hub] new tab: {s}", owner)
            if self.tabs.currentWidget() is view:
                self.status.showMessage(f"New tab: {s}", 6000)

        view.urlChanged.connect(_update)
        view.titleChanged.connect(lambda t, v=view: self._label_tab(self.tabs.indexOf(v), t))

    def _label_tab(self, index: int, text: str) -> None:
        text = (text or "").strip()
        if not text or index < 0:
            return
        self.tabs.setTabText(index, _short_label(text))
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
        rec = self.store.get(pid) if pid else None
        label = (rec or {}).get("name") or self.tabs.tabText(index)
        # Closing a project's tab also stops its backend, so a stopped
        # project never leaves a process running in the background.
        if pid:
            proc = self.procs.get(pid)
            if proc is not None:
                rec = self.store.get(pid)
                name = (rec or {}).get("name") or pid
                self._append_log(f"[hub] stopping {name} (tab closed)", pid)
                self._user_stopped_ids.add(pid)
                proc.stop()
        self.tabs.removeTab(index)
        self._append_log(f"[hub] closed tab '{label.strip()}'", pid)
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
            widget = self.tabs.widget(index)
            pid = widget.property("hub_project_id") if widget is not None else None
            rec = self.store.get(pid) if pid else None
            name = (rec or {}).get("name") or label.strip()
            self._append_log(f"[hub] close pressed on '{name}'", pid)

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
        on_starter = index >= 0 and self._is_starter_index(index)
        widget = self.tabs.widget(index) if index >= 0 else None
        pid = (widget.property("hub_project_id") or widget.property("hub_owner_project_id")) \
            if widget is not None else None
        if not pid or self.store.get(pid) is None:
            pid = None
        # Active browser tab, sidebar selection, terminal and toolbar share one
        # owner. Block the sidebar callback: reflecting tab focus must not open
        # or refresh a page, start a project, or recursively switch tabs.
        self.active_id = pid
        was_blocked = self.list.blockSignals(True)
        try:
            row = next((i for i in range(self.list.count())
                        if self.list.item(i).data(Qt.UserRole) == pid), -1)
            self.list.setCurrentRow(row)
        finally:
            self.list.blockSignals(was_blocked)
        self._set_controls_enabled(pid is not None)
        self._sync_log_page(pid)
        if index < 0:
            return
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
        if state in ("error", "stopped"):
            _cancel_readiness(self.waiters, pid)
        if pid == self.active_id:
            self.status.showMessage(f"{rec['name']}: {_STATE_LABEL.get(state, state)}")
        if state == "error":
            self._append_log(
                f"[hub] {rec['name']} exited with an error — its terminal has the details",
                pid,
            )
        elif state == "stopped":
            # Close the tabs only for an EXPLICIT stop. A project that exits
            # on its own (or died during startup) keeps its tab so the user
            # can see what happened and press Start again — silently
            # destroying the tab is what left frozen/empty panes before.
            if pid in self._user_stopped_ids:
                self._user_stopped_ids.discard(pid)
                self._close_tabs_for_project(pid)
                if pid == self.active_id or self.tabs.count() == 0:
                    self.active_id = None
                    # Removing the active project can synchronously clear its
                    # owner in currentChanged. Still restore the overview when
                    # there is no remaining tab to provide an action target.
                    # Fall back to the hub's own tab. Reopen it if the user had
                    # closed it, rather than jumping to whatever tab happens to
                    # be left.
                    if self.starter_index() is None:
                        self.open_starter_tab()
                    else:
                        self.tabs.setCurrentIndex(self.starter_index())
            else:
                # It exited on its own: keep the tab (so the terminal is still
                # there to read) but put the Start button back.
                self._show_start_page(rec, state="stopped")
        if state == "running" and not rec.get("url"):
            proc = self.procs.get(pid)
            if proc is not None and (rec.get("detected") or {}).get("type") != "desktop":
                self._scan_ports_after(rec, proc)
        if state == "running" and rec.get("url"):
            self._wait_ready(rec)
        elif state in ("error", "starting", "running"):
            # Keep the project's own tab honest: "Starting…" while it comes up,
            # the status card while it runs without a dashboard, and the Start
            # button again if it failed. A tab that is showing a real dashboard
            # is never touched here — only the hub's OWN pages are.
            view = self._view_for(pid)
            if view is not None and not self._tab_shows_dashboard(view, rec):
                if state == "error":
                    self._show_start_page(
                        rec, state="error",
                        detail="It stopped with an error — its terminal has the details.",
                    )
                else:
                    self._show_start_page(rec, state=state)

    def _tab_shows_dashboard(self, view: "HubWebView", rec: dict) -> bool:
        """True when this tab is showing a live dashboard, not a hub page."""
        url = view.url().toString()
        if not url:
            return False
        if url.startswith("data:") or url == "about:blank":
            return False
        configured = (rec.get("url") or "").rstrip("/")
        return bool(configured) and url.rstrip("/").startswith(configured)

    # ---------- dashboard display ----------

    def _profile_for(self, rec: dict) -> QWebEngineProfile:
        try:
            profile = self._html_storage.for_record(rec)
        except OSError as exc:
            self._append_log(f"[hub] HTML autosave storage unavailable: {exc}", rec["id"])
            self.status.showMessage("HTML autosave storage is unavailable; see this project's log", 8000)
            profile = None
        return profile if profile is not None else QWebEngineProfile.defaultProfile()

    def _show_dashboard(self, rec: dict) -> None:
        """Point this project's OWN tab at its URL (not the active tab's).

        If this project has no webview (a desktop app, a background autostart
        project, or a tab the user just closed), do nothing. Falling back to
        the current tab would navigate a DIFFERENT project's dashboard to this
        project's URL -- for example when a closed tab's readiness callback
        lands while another tab is selected.
        """
        if not rec.get("url"):
            return
        view = self._view_for(rec["id"])
        if view is None:
            return
        view.use_profile(self._profile_for(rec))
        target = QUrl(dashboard_url(rec))
        if view.url() != target:
            view.setUrl(target)

    def _on_load_finished(self, ok: bool) -> None:
        view = self.sender()
        # A background tab can finish loading while another project is on
        # screen; its message must land in ITS OWN terminal, not the
        # visible one.
        pid = view.property("hub_project_id") if view is not None else None
        pid = pid or self.active_id
        rec = self.store.get(pid) or {}
        if ok:
            return  # the tab is already the visible page
        name = rec.get("name", "project")
        proc = self.procs.get(pid)
        if proc is not None and proc.state == "running":
            # Server says it's up but the page failed — could be a slow
            # first render. Give it one automatic reload before bothering
            # the user.
            self._append_log(f"[hub] {name} page failed to load; retrying\n", pid)
            if view is not None:
                QTimer.singleShot(1200, view.reload)
        else:
            self._append_log(
                f"[hub] {name} is not reachable at {rec.get('url','?')} yet "
                "— the backend may still be starting\n",
                pid,
            )

    def _wait_ready(self, rec: dict) -> None:
        pid = rec["id"]
        target = dashboard_url(rec)
        existing = self.waiters.get(pid)
        if existing is not None:
            if existing.url == target:
                return
            _cancel_readiness(self.waiters, pid)
        waiter = ReadinessWaiter(target, timeout_ms=45000)
        self.waiters[pid] = waiter

        def _cleanup():
            if self.waiters.get(pid) is not waiter:
                return False
            _cancel_readiness(self.waiters, pid)
            return True

        def _ready():
            if not _cleanup():
                return
            # A URL that answers is only THIS project's dashboard if this
            # project's process is actually alive. Otherwise something else
            # owns the port and we would be showing a stranger's page.
            proc = self.procs.get(pid)
            # "starting" counts as ours too: the waiter can answer in the gap
            # between the port opening and the process being marked running,
            # and treating that as a stranger's page would leave the tab stuck
            # on "Starting…" forever.
            if proc is not None and proc.state not in ("starting", "running"):
                self._append_log(
                    f"[hub] {rec['url']} answered, but {rec['name']} is not running —\n"
                    f"[hub] that page belongs to another process on the same port.\n",
                    pid,
                )
                return
            own_tab = self._view_for(pid)
            if own_tab is None and pid != self.active_id:
                # Nothing of this project's is on screen, so there is nowhere
                # to put the dashboard. Never repoint the visible tab: that is
                # how one background project used to take over another one's
                # page. Its tab appears (already pointed at the URL) when the
                # user opens it.
                self._append_log(f"[hub] {rec['name']} answered at {rec['url']}\n", pid)
                return
            self._append_log(f"[hub] {rec['name']} answered at {rec['url']}\n", pid)
            self._show_dashboard(rec)
        def _fail(reason: str):
            if not _cleanup():
                return
            self._append_log(f"[hub] {reason}\n", pid)
            if pid == self.active_id:
                self.status.showMessage(f"{rec['name']}: {reason}")
            # Put the reason on the project's own page, next to a working Start
            # button — the old code wrote it to the starter tab's placeholder,
            # which is not on screen while a project tab is open.
            self._show_start_page(rec, state="error", detail=reason)

        waiter.ready.connect(_ready)
        waiter.failed.connect(_fail)
        waiter.start()

    # ---------- logs ----------

    def _append_log(self, text: str, pid: str | None = None) -> None:
        """Write to one project's terminal (pid=None → the hub's pane)."""
        self.log_view.append_for(text, pid)

    def _sync_log_page(self, pid: str | None) -> None:
        """Point the drawer at the terminal belonging to what is on screen."""
        self.log_view.show_page(pid)
        if pid:
            rec = self.store.get(pid) or {}
            self.log_view.set_header(f"Logs — {rec.get('name') or pid}")
        else:
            self.log_view.set_header("Logs — hub")

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
                self._append_log(f"[hub] autostarting {rec['name']}\n", rec["id"])
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
        self._append_log(f"[hub] starting {rec['name']}: {rec['command']}", rec["id"])
        if rec.get("url"):
            # Poll for the dashboard now; when it answers, _ready() points the
            # tab's webview at it. Do not wait on the "running" state signal
            # alone — it can be missed when this runs from the selection handler.
            self._wait_ready(rec)
        proc.start()
        # Starting from the toolbar should have somewhere to look: open the
        # project's tab on its start page so it can turn into "Starting…" and
        # then either the dashboard or the running card.
        if (
            (rec.get("detected") or {}).get("type") != "desktop"
            and self._tab_index_for_project(pid) is None
        ):
            self._open_project_tab(rec, start=False)

    def _launch(self, rec: dict, proc: ProjectProcess) -> None:
        """Start the process and begin waiting for its dashboard."""
        self._append_log(f"[hub] starting {rec['name']}: {rec['command']}", rec["id"])
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
            self._append_log(f"[hub] {reason}", rec["id"])
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
                f"{rec['name']} was not started",
                rec["id"],
            )
            return

        killed = []
        for h in holders:
            if urldetect.kill_process(h["pid"]):
                killed.append(h["pid"])
        self._append_log(
            f"[hub] ended process(es) holding port {conflict['port']}: {killed}",
            rec["id"],
        )

        def _start_after_free():
            # Recheck the endpoint whose overlapping holder was ended, not a
            # disjoint IPv4/IPv6 listener that the conflict deliberately spared.
            if not urldetect.port_in_use(conflict["port"], conflict.get("host")):
                self._launch(rec, proc)
            else:
                self._append_log(
                    f"[hub] port {conflict['port']} is still in use after ending the "
                    f"process; {rec['name']} was not started",
                    rec["id"],
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
        self._append_log(f"[hub] restarting {rec['name']}\n", pid)
        self._show_start_page(rec, state="starting")
        self._proc_for(rec).restart()

    def _select_project(self, pid: str) -> None:
        """Select a project's row in the sidebar (opening its tab if needed)."""
        if not pid:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == pid:
                if self.list.currentItem() is item:
                    # Already selected: _on_select will not fire, so make sure
                    # active_id is right for whatever acts on it next. Its tab
                    # is already open — do not reload the page under the click
                    # that got us here.
                    self.active_id = pid
                else:
                    self.list.setCurrentItem(item)
                return

    def _open_external(self) -> None:
        pid = self.active_id
        if not pid:
            return
        rec = self.store.get(pid)
        url = dashboard_url(rec) if rec else ""
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
            rec = self.store.add(rec)
        except store_mod.RegistryError as e:
            QMessageBox.warning(self, "Could not add", str(e))
            return
        self._reload_list()
        self._refresh_welcome()
        # Registration is not navigation: leave the user's current tab and its
        # in-memory dashboard state intact. The new row is available to open.
        self.status.showMessage(f"Added {rec['name']}", 6000)

    def _edit_project(self) -> None:
        pid = self.active_id
        if not pid:
            return
        before = self.store.get(pid) or {}
        dlg = ProjectDialog(self, record=before)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            rec = dlg.result_record()
        except store_mod.RegistryError as e:
            QMessageBox.warning(self, "Invalid project", str(e))
            return
        assert rec is not None  # exec() accepted; result_record's rejected branch cannot apply.
        self.store.update(rec)
        self._retitle_tab(pid, self._item_label(before), rec)
        _cancel_readiness(self.waiters, pid)
        old = self.procs.pop(pid, None)
        if old:
            old.stop()
        self._reload_list()
        self._refresh_welcome()
        # Editing must not start it either — the project may already be running,
        # and re-selecting would restart it. Just keep the selection.
        self._select_id(pid, start=False)
        # Edit explicitly changed the saved launch content. Refresh it here,
        # not on ordinary sidebar focus, which must preserve live dashboards.
        self._refresh_project_page(rec)

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
        _cancel_readiness(self.waiters, pid)
        self._user_stopped_ids.discard(pid)
        self.store.remove(pid)
        self.log_view.drop_page(pid)
        self._reload_list()
        # Removing a tab selects its neighbour synchronously. Reflect the
        # remaining visible tab instead of clearing its newly selected owner.
        self._on_tab_changed(self.tabs.currentIndex())
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
        diagnostics_mod.clear_project_context()
        super().closeEvent(event)
