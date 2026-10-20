"""The one obvious dialog that an update check reports itself in.

Before this, "Check for Updates…" spoke through the status bar and separate
message boxes: while the check ran nothing was visible, and the multi-minute
download showed only a corner message -- so the app looked frozen or dead.
The user asked (2026-10-18) for a single obvious box in the centre of the
screen that walks the whole sequence:

    checking -> up to date | update available -> downloading (with progress)

The dialog holds no state beyond what it shows; the window drives it, one
method per state. It is deliberately non-modal: during a download the user
can keep using the app, and the box stays visible on top.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class UpdateDialog(QDialog):
    """Single window that walks check -> result -> download."""

    request_download = Signal()
    install_now = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.setModal(False)
        self.setMinimumWidth(440)

        v = QVBoxLayout(self)

        self.headline = QLabel("")
        f = self.headline.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        self.headline.setFont(f)
        self.headline.setWordWrap(True)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.bar = QProgressBar()
        self.bar.setVisible(False)

        row = QHBoxLayout()
        self.link = QPushButton("Open release page")
        self.secondary = QPushButton("Later")
        self.primary = QPushButton("OK")
        for b in (self.link, self.secondary, self.primary):
            b.setVisible(False)
        row.addStretch(1)
        row.addWidget(self.link)
        row.addWidget(self.secondary)
        row.addWidget(self.primary)

        v.addWidget(self.headline)
        v.addWidget(self.detail)
        v.addWidget(self.bar)
        v.addLayout(row)

        self._primary_action = None  # "download" | "close" | None
        self._link_url = ""

        self.primary.clicked.connect(self._on_primary)
        self.secondary.clicked.connect(self.close)
        self.link.clicked.connect(self._open_link)

    # ---------- states ----------

    def show_checking(self) -> None:
        self.headline.setText("Checking for updates…")
        self.detail.setText("Looking for the newest release on GitHub.")
        self._busy_bar()
        self._buttons()
        self.reveal()

    def show_up_to_date(self, version: str) -> None:
        self.headline.setText("You're up to date")
        self.detail.setText(f"Local Project Hub {version} is the latest version.")
        self._hide_bar()
        self._buttons(primary=("OK", "close"))
        self.reveal()

    def show_available(self, release, asset) -> None:
        from .platform import IS_MACOS
        from .updater import summarize_release

        self.headline.setText(f"Version {release.version} is available")
        text = summarize_release(release)
        if asset is not None:
            if IS_MACOS:
                text += (
                    f"\n\n{asset.name} will be downloaded and prepared; when "
                    "it is ready you restart the app and the new version is "
                    "in place. Your projects and settings are kept."
                )
            else:
                text += (
                    f"\n\nThe {asset.name} installer will be downloaded and opened; "
                    "your projects and settings are kept."
                )
        else:
            text += "\n\nNo installer for this platform was published in this release yet."
        self.detail.setText(text)
        self._hide_bar()
        self._link_url = release.html_url or ""
        if asset is not None:
            self._buttons(
                primary=("Download and Install", "download"),
                secondary="Later",
                link=bool(self._link_url),
            )
        else:
            self._buttons(primary=("OK", "close"), link=bool(self._link_url))
        self.reveal()

    def show_downloading(self, name: str, total: int) -> None:
        self.headline.setText(f"Downloading {name}…")
        self.detail.setText(
            "Your projects and settings are kept. You can keep using the app "
            "while it downloads."
        )
        self.bar.setRange(0, total if total > 0 else 0)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self._buttons()
        self.reveal()

    def show_preparing(self, version: str) -> None:
        self.headline.setText(f"Preparing {version}…")
        self.detail.setText(
            "Unpacking the new version. Your projects and settings are kept."
        )
        self._busy_bar()
        self._buttons()
        self.reveal()

    def show_ready_to_install(self, version: str) -> None:
        self.headline.setText(f"{version} is ready to install")
        self.detail.setText(
            "The app will close, put the new version in place, and reopen by "
            "itself — there is nothing to drag anywhere. Your projects and "
            "settings are kept."
        )
        self._hide_bar()
        self._buttons(primary=("Restart and Install", "install"), secondary="Later")
        self.reveal()

    def show_error(self, headline: str, message: str) -> None:
        self.headline.setText(headline)
        self.detail.setText(message)
        self._hide_bar()
        self._buttons(primary=("OK", "close"))
        self.reveal()

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            if self.bar.maximum() != total:
                self.bar.setRange(0, total)
            self.bar.setValue(min(done, total))
        else:
            self._busy_bar()

    def reveal(self) -> None:
        """Show, bring to the front, and centre on the screen."""
        self.show()
        self.raise_()
        self.activateWindow()
        self._center()

    # ---------- internals ----------

    def _center(self) -> None:
        parent = self.parent()
        screen = (
            parent.screen() if parent is not None else None
        ) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.adjustSize()
        geo = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geo.center())
        self.move(frame.topLeft())

    def _busy_bar(self) -> None:
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)

    def _hide_bar(self) -> None:
        self.bar.setVisible(False)

    def _buttons(self, primary=None, secondary=None, link: bool = False) -> None:
        self._primary_action = None
        if primary is not None:
            text, action = primary
            self.primary.setText(text)
            self._primary_action = action
            self.primary.setVisible(True)
        else:
            self.primary.setVisible(False)
        if secondary is not None:
            self.secondary.setText(secondary)
            self.secondary.setVisible(True)
        else:
            self.secondary.setVisible(False)
        self.link.setVisible(bool(link))

    def _on_primary(self) -> None:
        if self._primary_action == "download":
            self.request_download.emit()
        elif self._primary_action == "install":
            self.install_now.emit()
        else:
            self.close()

    def _open_link(self) -> None:
        if self._link_url:
            QDesktopServices.openUrl(QUrl(self._link_url))
