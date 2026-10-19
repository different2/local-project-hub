"""Add/Edit project dialog.

The dialog asks for the two things it cannot work out by itself — which folder
(or file) the project lives in, and what command starts it — and derives the
rest, including the display name. Everything else is real but optional, so it
sits behind one "Optional settings" toggle instead of crowding the form with
rows nobody has to fill in (user request, 2026-10-19: "a majority of these
options should be hidden under a whole optional settings button").

Validation runs through hub.store.validate so the rules live in exactly one
place; registry errors are shown to the user instead of silently failing.
"""

from __future__ import annotations

import os
from pathlib import Path

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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import store as store_mod
from .detect_command import suggest_command as _suggest_command
from .detect_command import suggest_for_file as _suggest_for_file
from .detect_type import DISPLAY, detect as _detect_type

_ICONS = ["🌐", "🧪", "📈", "🎮", "🎨", "🧭", "🛠️", "📚", "🤖", "⬜"]

_HINT_STYLE = "color: gray; font-size: 11px;"


def _display_for(kind: str) -> str:
    return DISPLAY.get(kind, DISPLAY["unknown"])


def name_from_folder(path: str) -> str:
    """The display name implied by a chosen folder: its own name."""
    p = Path(path.rstrip("/") or "/")
    if p.name:
        return p.name
    return str(p)  # a filesystem root has no basename


def name_from_file(path: str) -> str:
    """The display name implied by a chosen file: its name, without suffix.

    "obs_live.py" reads better as "obs_live" in the sidebar than as a filename,
    and a file with no suffix keeps its whole name.
    """
    p = Path(path)
    return p.stem or p.name


class ProjectDialog(QDialog):
    def __init__(self, parent=None, record: dict | None = None, base_dir: str = ""):
        super().__init__(parent)
        self._record = dict(record) if record else {}
        self._editing = bool(record)
        self.setWindowTitle("Edit project" if record else "Add project")
        # Wide enough that no hint has to wrap into a clipped second line.
        self.setMinimumWidth(640)

        # ---------- the three questions that matter ----------
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.wd = QLineEdit(self._record.get("working_dir", base_dir))
        self.wd.setPlaceholderText("Choose the project's folder…")
        self.wd.setToolTip("The folder the startup command runs in.")
        browse = QPushButton("Folder…")
        browse.setToolTip("Choose the project's folder")
        browse.clicked.connect(self._pick_dir)
        pick_file = QPushButton("File…")
        pick_file.setToolTip("Choose the file that starts the project")
        pick_file.clicked.connect(self._pick_file)
        row_wd = QHBoxLayout()
        row_wd.addWidget(self.wd, 1)
        row_wd.addWidget(browse)
        row_wd.addWidget(pick_file)
        form.addRow("Folder", self._wrap(row_wd))

        self.name = QLineEdit(self._record.get("name", ""))
        self.name.setPlaceholderText("taken from the folder or file you choose")
        self.name.setToolTip(
            "How this project is listed. Filled in from your choice of folder or "
            "file; you can also rename it in the sidebar at any time."
        )
        form.addRow("Display name", self.name)

        self.command = QLineEdit(self._record.get("command", ""))
        self.command.setPlaceholderText("python3 server.py  ·  npm run dev  ·  go run .")
        self.command.setToolTip(
            "The command that starts this project. Filled in when the Hub "
            "recognises the folder or file — edit it freely."
        )
        self.detection = QLabel("")
        self.detection.setWordWrap(True)
        self.detection.setStyleSheet(_HINT_STYLE)
        cmd_box = QVBoxLayout()
        cmd_box.setContentsMargins(0, 0, 0, 0)
        cmd_box.setSpacing(2)
        cmd_box.addWidget(self.command)
        cmd_box.addWidget(self.detection)
        form.addRow("Startup command", self._wrap(cmd_box))

        # ---------- everything else, behind one toggle ----------
        self.more = QToolButton()
        self.more.setText("Optional settings")
        self.more.setCheckable(True)
        self.more.setChecked(False)
        self.more.setArrowType(Qt.RightArrow)
        self.more.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more.setAutoRaise(True)
        self.more.toggled.connect(self._toggle_advanced)

        self.advanced = QWidget()
        adv = QFormLayout(self.advanced)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.icon = QComboBox()
        self.icon.addItems(_ICONS)
        self.icon.setEditable(True)
        self.icon.setCurrentText(self._record.get("icon", "🌐"))
        self.icon.setToolTip("Shown next to the project's name in the sidebar.")
        self.desc = QLineEdit(self._record.get("description", ""))
        self.desc.setPlaceholderText("optional description")
        row_icon = QHBoxLayout()
        row_icon.addWidget(self.icon)
        row_icon.addWidget(self.desc, 1)
        adv.addRow("Icon / description", self._wrap(row_icon))

        self.interp = QLineEdit(self._record.get("interpreter", ""))
        self.interp.setPlaceholderText(".venv/bin/python, /opt/homebrew/bin/node")
        self.interp.setToolTip("Only if the command must run through a specific interpreter.")
        adv.addRow("Interpreter", self.interp)

        self.args = QLineEdit(self._record.get("args", ""))
        self.args.setPlaceholderText("--no-open")
        self.args.setToolTip(
            "Appended to the command — e.g. a flag that stops the server opening "
            "its own browser."
        )
        adv.addRow("Extra arguments", self.args)

        self.url = QLineEdit(self._record.get("url", ""))
        self.url.setPlaceholderText("auto-detected")
        self.url.setToolTip(
            "The address to show inside the Hub. Leave blank and it is detected "
            "from the server's own output."
        )
        adv.addRow("Dashboard URL", self.url)

        self.env = QPlainTextEdit()
        self.env.setPlaceholderText("KEY=VALUE, one per line")
        self.env.setMaximumHeight(70)
        self.env.setToolTip("Environment variables for this project only.")
        self.env.setPlainText(
            "\n".join(f"{k}={v}" for k, v in self._record.get("env", {}).items())
        )
        adv.addRow("Env vars", self.env)

        self.autostart = QCheckBox("Start automatically when the hub opens")
        self.autostart.setChecked(self._record.get("autostart", False))
        adv.addRow("", self.autostart)

        self.type_override = QComboBox()
        self.type_override.addItems(
            ["detect automatically", "web", "static", "desktop", "cli"]
        )
        current = self._record.get("type_override") or ""
        self.type_override.setCurrentText(current or "detect automatically")
        self.type_override.setToolTip(
            "How the Hub shows this project. Detection is usually right."
        )
        adv.addRow("Project type", self.type_override)

        self.advanced_note = QLabel(
            "These are worked out automatically. Set one only to override that."
        )
        self.advanced_note.setWordWrap(True)
        self.advanced_note.setStyleSheet(_HINT_STYLE)
        adv.addRow("", self.advanced_note)

        self.advanced.setVisible(False)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.more)
        layout.addWidget(self.advanced)
        layout.addWidget(self.buttons)

        # Re-run detection whenever the fields it depends on change.
        self.command.textChanged.connect(self._refresh_detection)
        self.args.textChanged.connect(self._refresh_detection)
        self.wd.textChanged.connect(self._refresh_detection)
        self.type_override.currentIndexChanged.connect(self._refresh_detection)

        # The chosen folder can suggest the command (detect_command). textEdited
        # fires only for user typing, so a filled-in suggestion never counts as
        # the user having "written" the command.
        self._suggestion = None
        self._suggested_interpreter = ""
        self._command_touched = False
        self.command.textEdited.connect(self._mark_command_touched)
        self.wd.textChanged.connect(self._maybe_suggest_from_folder)

        # The name follows the folder/file the user picks until they type their
        # own. Only a USER edit turns that off, so a pre-filled folder (base_dir)
        # never silently names the project after the user's home directory.
        self._name_auto = not self._editing
        self.name.textEdited.connect(self._mark_name_touched)
        self.wd.textEdited.connect(self._maybe_name_from_folder)

        self._refresh_detection()
        self._maybe_suggest_from_folder()

        if self._editing and self._advanced_has_values():
            # Nothing the user has already set is hidden from them.
            self.more.setChecked(True)
        self._refresh_more_label()

    # ---------- optional settings ----------

    def _toggle_advanced(self, shown: bool) -> None:
        self.advanced.setVisible(shown)
        self.more.setArrowType(Qt.DownArrow if shown else Qt.RightArrow)
        self._refresh_more_label()
        # Grow/shrink to fit instead of squeezing the new rows into the old
        # height, which is what clipped the help text in the crowded version.
        self.adjustSize()

    def _advanced_has_values(self) -> bool:
        return bool(
            self.desc.text().strip()
            or self.interp.text().strip()
            or self.args.text().strip()
            or self.url.text().strip()
            or self.env.toPlainText().strip()
            or self.autostart.isChecked()
            or self.type_override.currentText() != "detect automatically"
            or (self.icon.currentText().strip() not in ("", "🌐"))
        )

    def _refresh_more_label(self) -> None:
        text = "Optional settings"
        if self.more.isChecked() or not self._advanced_has_values():
            self.more.setText(text)
        else:
            self.more.setText(f"{text} (set)")

    # ---------- name ----------

    def _mark_name_touched(self) -> None:
        """The user named it themselves; never overwrite that."""
        self._name_auto = False

    def _maybe_name_from_folder(self) -> None:
        if not self._name_auto:
            return
        folder = self.wd.text().strip()
        if folder:
            self.name.setText(name_from_folder(folder))

    def _maybe_name_from_file(self, path: str) -> None:
        if not self._name_auto:
            return
        self.name.setText(name_from_file(path))

    # ---------- detection ----------

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
            self.detection.setText(
                self._with_suggestion_note(f"Shown as {_display_for(override)}")
            )
            return
        if not self.command.text().strip():
            self.detection.setText("Filled in when the Hub recognises the folder.")
            return
        bits = [f"{det.type} ({det.confidence:.0%})"]
        if det.framework:
            bits.append(det.framework)
        if det.port:
            bits.append(f"port {det.port}")
        bits.append(f"shown as {det.display}")
        self.detection.setText(self._with_suggestion_note(" · ".join(bits)))

    def _mark_command_touched(self) -> None:
        """The user has written their own command; stop offering suggestions."""
        self._command_touched = True

    def _maybe_suggest_from_folder(self) -> None:
        """Fill the command in from the chosen folder, when nothing is lost.

        Only ever fills an EMPTY command field — or replaces a previous
        suggestion of our own when the folder changes (so picking the wrong
        folder first costs nothing). A command the user typed, or one an
        existing project already carries, is never rewritten (spec §6).
        """
        if self._command_touched:
            return
        current = self.command.text().strip()
        old = self._suggestion
        if current and (old is None or current != old.command):
            return  # a real user command is never replaced
        folder = self.wd.text().strip()
        if not folder:
            return
        try:
            sug = _suggest_command(folder)
        except Exception:
            return  # a suggestion is advisory; it must never break the dialog
        self._suggestion = sug
        self._clear_suggested_interpreter()
        if sug is None:
            if current:
                # Our previous suggestion no longer fits this folder.
                self.command.setText("")
            return
        self.command.setText(sug.command)
        if sug.interpreter and not self.interp.text().strip():
            self.interp.setText(sug.interpreter)
            self._suggested_interpreter = sug.interpreter
        self._refresh_detection()

    def _clear_suggested_interpreter(self) -> None:
        """Remove an interpreter WE filled in, unless the user changed it."""
        if (
            self._suggested_interpreter
            and self.interp.text().strip() == self._suggested_interpreter
        ):
            self.interp.setText("")
        self._suggested_interpreter = ""

    def _with_suggestion_note(self, text: str) -> str:
        """Credit the detector while its suggestion is still intact."""
        s = self._suggestion
        if s and self.command.text().strip() == s.command:
            return f"{text} · from {s.source}"
        return text

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    # ---------- picking ----------

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Project folder", self.wd.text() or os.path.expanduser("~")
        )
        if d:
            self.wd.setText(d)
            self._maybe_name_from_folder()

    def _pick_file(self) -> None:
        """Pick one file; its folder and startup command follow from it."""
        start = self.wd.text().strip() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the file that starts the project", start
        )
        if path:
            self._apply_file_choice(path)

    def _apply_file_choice(self, path: str) -> None:
        """Load one file: set its folder, then suggest from the file itself.

        Split from _pick_file so tests can drive it without a file dialog.
        The picked file outranks the folder's own guess — it replaces only
        an empty field or an earlier suggestion of ours, never a command the
        user wrote (spec §6). It also names the project, since the file is
        what the user actually chose.
        """
        parent = os.path.dirname(os.path.abspath(path))
        if parent and parent != self.wd.text().strip():
            self.wd.setText(parent)  # may fill a folder suggestion first
        self._maybe_name_from_file(path)
        if self._command_touched:
            return
        current = self.command.text().strip()
        old = self._suggestion
        if current and (old is None or current != old.command):
            return  # a real user command is never replaced
        try:
            sugs = _suggest_for_file(path)
        except Exception:
            return  # a suggestion is advisory; it must never break the dialog
        sug = sugs[0] if sugs else None
        self._suggestion = sug
        self._clear_suggested_interpreter()
        if sug is None:
            return
        self.command.setText(sug.command)
        if sug.interpreter and not self.interp.text().strip():
            self.interp.setText(sug.interpreter)
            self._suggested_interpreter = sug.interpreter
        self._refresh_detection()

    # ---------- result ----------

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
        name = self.name.text().strip()
        if not name:
            # Never make the user answer a question we can answer ourselves:
            # an unnamed project is named after the folder it runs in.
            folder = self.wd.text().strip()
            name = name_from_folder(folder) if folder else ""
        rec.update(
            {
                "name": name,
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
