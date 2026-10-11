"""Add/Edit project dialog.

Fields map 1:1 to the store's record. Validation runs through hub.store.validate
so the rules live in exactly one place; registry errors are shown to the user
instead of silently failing.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import store as store_mod

_ICONS = ["🌐", "🧪", "📈", "🎮", "🎨", "🧭", "🛠️", "📚", "🤖", "⬜"]


class ProjectDialog(QDialog):
    def __init__(self, parent=None, record: dict | None = None, base_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Edit project" if record else "Add project")
        self._record = dict(record) if record else {}
        self.setMinimumWidth(540)

        form = QFormLayout()

        self.name = QLineEdit(self._record.get("name", ""))
        self.name.setPlaceholderText("Sphere Project")
        form.addRow("Display name", self.name)

        self.icon = QComboBox()
        self.icon.addItems(_ICONS)
        self.icon.setEditable(True)
        self.icon.setCurrentText(self._record.get("icon", "🌐"))
        self.desc = QLineEdit(self._record.get("description", ""))
        self.desc.setPlaceholderText("optional description")
        row_icon = QHBoxLayout()
        row_icon.addWidget(self.icon)
        row_icon.addWidget(self.desc, 1)
        form.addRow("Icon / description", self._wrap(row_icon))

        self.wd = QLineEdit(self._record.get("working_dir", base_dir))
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._pick_dir)
        row_wd = QHBoxLayout()
        row_wd.addWidget(self.wd)
        row_wd.addWidget(browse)
        form.addRow("Project folder", self._wrap(row_wd))

        self.interp = QLineEdit(self._record.get("interpreter", ""))
        self.interp.setPlaceholderText(
            "optional — e.g. .venv/bin/python, /opt/homebrew/bin/node, C:\\Python312\\python.exe"
        )
        interp_help = QLabel(
            "Any executable that should run your command. Leave blank to use whatever "
            "the command names itself (python3, node, npm, go…). Use it for a "
            "project's own virtual environment or a specific toolchain."
        )
        interp_help.setWordWrap(True)
        interp_help.setStyleSheet("color: gray; font-size: 11px;")
        interp_box = QVBoxLayout()
        interp_box.setContentsMargins(0, 0, 0, 0)
        interp_box.setSpacing(2)
        interp_box.addWidget(self.interp)
        interp_box.addWidget(interp_help)
        form.addRow("Interpreter (optional)", self._wrap(interp_box))

        self.command = QLineEdit(self._record.get("command", ""))
        self.command.setPlaceholderText("python3 server.py 8471  ·  npm run dev  ·  go run .")
        form.addRow("Startup command", self.command)

        cmd_help = QLabel(
            "Runs from the project folder. Python, Node, Go, Rust, a shell script — "
            "whatever starts your dashboard."
        )
        cmd_help.setWordWrap(True)
        cmd_help.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", cmd_help)

        self.env = QPlainTextEdit()
        self.env.setPlaceholderText("KEY=VALUE, one per line (optional)")
        self.env.setMaximumHeight(80)
        self.env.setPlainText(
            "\n".join(f"{k}={v}" for k, v in self._record.get("env", {}).items())
        )
        form.addRow("Env vars", self.env)

        self.url = QLineEdit(self._record.get("url", ""))
        self.url.setPlaceholderText("leave blank to detect it automatically")
        url_help = QLabel(
            "Optional. Most servers print their address when they start — the Hub "
            "reads that and fills this in for you. Set it only if your project "
            "starts silently."
        )
        url_help.setWordWrap(True)
        url_help.setStyleSheet("color: gray; font-size: 11px;")
        url_box = QVBoxLayout()
        url_box.setContentsMargins(0, 0, 0, 0)
        url_box.setSpacing(2)
        url_box.addWidget(self.url)
        url_box.addWidget(url_help)
        form.addRow("Dashboard URL (optional)", self._wrap(url_box))

        self.autostart = QCheckBox("Start automatically when the hub opens")
        self.autostart.setChecked(self._record.get("autostart", False))
        form.addRow("", self.autostart)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Project folder", self.wd.text() or os.path.expanduser("~")
        )
        if d:
            self.wd.setText(d)

    def result_record(self) -> dict | None:
        if self.result() != QDialog.Accepted:
            return None
        rec = dict(self._record)
        rec.update(
            {
                "name": self.name.text().strip(),
                "description": self.desc.text().strip(),
                "icon": self.icon.currentText().strip() or "🌐",
                "working_dir": self.wd.text().strip(),
                "interpreter": self.interp.text().strip(),
                "command": self.command.text().strip(),
                "url": self.url.text().strip(),
                "autostart": self.autostart.isChecked(),
                "env": self._parse_env(self.env.toPlainText()),
            }
        )
        return store_mod.validate(rec)

    @staticmethod
    def _parse_env(text: str) -> dict:
        env = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
        return env
