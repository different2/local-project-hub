"""User-approved WebEngine downloads, including page-generated blob exports.

The renderer keeps its normal sandbox. The user chooses the final destination;
Chromium may stage temporary data while the save picker is open. Files are never
auto-opened and no Python filesystem bridge is exposed to pages.
"""
from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QObject, Qt, QStandardPaths, Signal, Slot
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout


class _DownloadDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, parent, destination: Path):
        super().__init__(parent)
        self.in_progress = True
        self.cancelled_by_user = False
        self.setWindowTitle("Browser download")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.message = QLabel("Saving " + destination.name + "…")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        self.path = QLabel(str(destination))
        self.path.setWordWrap(True)
        self.path.setTextFormat(Qt.PlainText)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.button = QPushButton("Cancel")
        self.button.clicked.connect(self.cancel)
        for widget in (self.message, self.path, self.bar, self.button):
            layout.addWidget(widget)

    def cancel(self):
        self.cancelled_by_user = True
        self.cancel_requested.emit()

    def reject(self):
        if self.in_progress:
            self.cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.in_progress:
            event.ignore()
            self.cancel()
        else:
            super().closeEvent(event)


class BrowserDownloads(QObject):
    """One signal subscription per profile, with exact originating-tab ownership."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._profiles = set()
        self._active = {}
        self._dialogs = set()

    def watch(self, profile):
        if profile not in self._profiles:
            self._profiles.add(profile)
            profile.downloadRequested.connect(self._requested)

    def shutdown(self):
        # Clear ownership before cancelling: late Chromium signals must not
        # re-enter widgets while their parent window is being destroyed.
        for request in list(self._active):
            dialog, _, _ = self._active.pop(request)
            dialog.in_progress = False
            dialog.close()
            request.cancel()
            request.deleteLater()
        for profile in self._profiles:
            profile.downloadRequested.disconnect(self._requested)
        self._profiles.clear()

    def _report(self, message, project_id):
        self.window.status.showMessage(message, 10000)
        self.window._append_log("[hub] " + message, project_id)

    def _requested(self, request):
        page = request.page()
        view = QWebEngineView.forPage(page) if page is not None else None
        if view is None or self.window.tabs.indexOf(view) < 0:
            # The default Chromium profile can serve more than one Hub window.
            # A different owner must decide; never show a duplicate save dialog.
            return
        project_id = view.property("hub_project_id") or view.property("hub_owner_project_id")
        name = re.split(r"[/\\]", request.suggestedFileName())[-1]
        if not name or name in (".", ".."):
            name = "download"
        folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home())
        try:
            chosen, _ = QFileDialog.getSaveFileName(self.window, "Save download", str(Path(folder) / name))
            if not chosen:
                request.cancel()
                self._report("Download cancelled: " + name, project_id)
                return
            destination = Path(chosen)
            request.setDownloadDirectory(str(destination.parent))
            request.setDownloadFileName(destination.name)
            dialog = _DownloadDialog(self.window, destination)
            self._dialogs.add(dialog)
            dialog.destroyed.connect(lambda: self._dialogs.discard(dialog))
            self._active[request] = (dialog, destination, project_id)
            dialog.cancel_requested.connect(request.cancel)
            request.receivedBytesChanged.connect(self._download_changed)
            request.totalBytesChanged.connect(self._download_changed)
            request.isFinishedChanged.connect(self._download_changed)
            dialog.show()
            self._report("Downloading " + destination.name + "…", project_id)
            request.accept()
            self._update(request)
        except Exception as exc:
            request.cancel()
            self._report("Couldn't save download: " + str(exc), project_id)

    @Slot()
    def _download_changed(self):
        # A QObject receiver disconnects automatically before window teardown;
        # a lambda capturing widgets can outlive their native objects.
        self._update(self.sender())

    def _update(self, request):
        current = self._active.get(request)
        if current is None:
            return
        dialog, destination, project_id = current
        if not request.isFinished():
            total = request.totalBytes()
            if total > 0:
                dialog.bar.setRange(0, 100)
                dialog.bar.setValue(min(100, request.receivedBytes() * 100 // total))
            return
        state = request.state()
        if state == QWebEngineDownloadRequest.DownloadCompleted and destination.is_file():
            message = "Download saved: " + str(destination)
            headline = "Download saved"
            dialog.bar.setRange(0, 100)
            dialog.bar.setValue(100)
        elif state == QWebEngineDownloadRequest.DownloadCancelled and dialog.cancelled_by_user:
            message = "Download cancelled: " + destination.name
            headline = "Download cancelled"
            dialog.bar.setRange(0, 100)
            dialog.bar.setValue(0)
        else:
            message = "Download failed: " + (request.interruptReasonString() or "the file could not be saved")
            headline = message
            dialog.bar.setRange(0, 100)
            dialog.bar.setValue(0)
        dialog.message.setText(headline)
        dialog.in_progress = False
        dialog.button.clicked.disconnect(dialog.cancel)
        dialog.button.setText("Close")
        dialog.button.clicked.connect(dialog.close)
        dialog.adjustSize()
        self._report(message, project_id)
        self._active.pop(request)
        request.deleteLater()
