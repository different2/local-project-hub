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
from .detect_type import DISPLAY, detect as _detect_type

_ICONS = ["🌐", "🧪", "📈", "🎮", "🎨", "🧭", "🛠️", "📚", "🤖", "⬜"]


def _display_for(kind: str) -> str:
    return DISPLAY.get(kind, DISPLAY["unknown"])


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

        # Extra arguments, appended after the command. Deliberately NOT
        # auto-injected: the hub cannot know which flag a given server uses to
        # suppress its own browser ("--no-open" here, "--no-reload" for flask,
        # nothing at all for npm), so guessing would corrupt commands.
        self.args = QLineEdit(self._record.get("args", ""))
        self.args.setPlaceholderText("--no-open")
        args_help = QLabel(
            "Appended to the command. Useful for flags you do not want to retype: "
            "most servers have one that stops them opening their own browser, since "
            "the Hub already shows the dashboard in its own tab."
        )
        args_help.setWordWrap(True)
        args_help.setStyleSheet("color: gray; font-size: 11px;")
        args_box = QVBoxLayout()
        args_box.setContentsMargins(0, 0, 0, 0)
        args_box.setSpacing(2)
        args_box.addWidget(self.args)
        args_box.addWidget(args_help)
        form.addRow("Extra arguments (optional)", self._wrap(args_box))

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

        # ---------- automatic detection (spec §5) ----------
        # Shown live as the user types, so setup is informative without adding
        # questions. Detection is best-effort: a low-confidence or "unknown"
        # result is reported as such, and the type can be overridden below.
        self.detection = QLabel("Type a command to see what the Hub detected…")
        self.detection.setWordWrap(True)
        self.detection.setStyleSheet("color: gray; font-size: 11px;")
        det_box = QVBoxLayout()
        det_box.setContentsMargins(0, 0, 0, 0)
        det_box.setSpacing(2)
        det_box.addWidget(self.detection)
        form.addRow("Detected", self._wrap(det_box))

        self.type_override = QComboBox()
        self.type_override.addItems(["detect automatically", "web", "static", "desktop", "cli"])
        current = self._record.get("type_override") or ""
        self.type_override.setCurrentText(current or "detect automatically")
        override_help = QLabel(
            "Override only if the detection above is wrong. Your choice is saved and "
            "reused; leave it on automatic otherwise."
        )
        override_help.setWordWrap(True)
        override_help.setStyleSheet("color: gray; font-size: 11px;")
        ov_box = QVBoxLayout()
        ov_box.setContentsMargins(0, 0, 0, 0)
        ov_box.setSpacing(2)
        ov_box.addWidget(self.type_override)
        ov_box.addWidget(override_help)
        form.addRow("Project type", self._wrap(ov_box))

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        # Re-run detection whenever the fields it depends on change.
        self.command.textChanged.connect(self._refresh_detection)
        self.args.textChanged.connect(self._refresh_detection)
        self.wd.textChanged.connect(self._refresh_detection)
        self.type_override.currentIndexChanged.connect(self._refresh_detection)
        self._refresh_detection()

    def _refresh_detection(self) -> None:
        """Show what the Hub currently believes about this project."""
        override = self.type_override.currentText()
        manual = override in ("web", "static", "desktop", "cli")
        try:
            det = _detect_type(
                {
                    "command": self.command.text().strip(),
                    "args": self.args.text().strip(),
                    "working_dir": self.wd.text().strip(),
                }
            )
        except Exception:
            # Detection is advisory; a failure here must never block the dialog.
            self.detection.setText("Could not inspect this project.")
            return
        if manual:
            kind = override
            self.detection.setText(
                f"Using your choice: {kind}. Will be shown as {_display_for(kind)}."
            )
            return
        if not self.command.text().strip():
            self.detection.setText("Type a command to see what the Hub detected…")
            return
        bits = [f"Type: {det.type} (confidence {det.confidence:.0%})"]
        if det.framework:
            bits.append(f"framework: {det.framework}")
        if det.port:
            bits.append(f"port: {det.port}")
        bits.append(f"will be shown as {det.display}")
        if det.type == "unknown":
            bits.append("— the Hub could not tell; it will just run this command")
        self.detection.setText(" · ".join(bits))

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
        override = self.type_override.currentText()
        manual = override in ("web", "static", "desktop", "cli")
        # Detection is stored BESIDE the record; the user's command is never
        # rewritten with generated flags (spec §6).
        det = _detect_type(
            {
                "command": self.command.text().strip(),
                "args": self.args.text().strip(),
                "working_dir": self.wd.text().strip(),
            }
        )
        if manual:
            det.type = override
            det.display = _display_for(override)
            det.evidence = list(det.evidence) + [f"user override: {override}"]
        rec.update(
            {
                "name": self.name.text().strip(),
                "description": self.desc.text().strip(),
                "icon": self.icon.currentText().strip() or "🌐",
                "working_dir": self.wd.text().strip(),
                "interpreter": self.interp.text().strip(),
                "command": self.command.text().strip(),
                "args": self.args.text().strip(),
                "url": self.url.text().strip(),
                "autostart": self.autostart.isChecked(),
                "env": self._parse_env(self.env.toPlainText()),
                "detected": det.as_dict(),
                "type_override": override if manual else "",
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
