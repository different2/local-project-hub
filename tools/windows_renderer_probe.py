"""TEMPORARY Windows renderer diagnostic; remove before PR #2 merges.

Not a product test or a release workflow. Compare a bare Qt HTML page and one
existing failing Hub regression, varying one renderer setting at a time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TEST = "test_selecting_a_project_shows_a_start_page_and_runs_nothing"


def bare_page() -> int:
    import PySide6
    from PySide6.QtCore import QTimer, qInstallMessageHandler, qVersion
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    messages = []
    qInstallMessageHandler(lambda kind, context, message: messages.append(str(message)))
    app = QApplication(["renderer-probe"])
    view = QWebEngineView()
    view.resize(640, 480)
    state = {"loaded": None, "title": "", "terminated": [], "ok": False}

    def check_ready():
        if state["loaded"] is True and state["title"] == "LPH_RENDERER_PROBE":
            state["ok"] = True
            QTimer.singleShot(0, app.quit)

    def loaded(ok):
        state["loaded"] = bool(ok)
        check_ready()

    def titled(title):
        state["title"] = str(title)
        check_ready()

    view.loadFinished.connect(loaded)
    view.titleChanged.connect(titled)
    view.page().renderProcessTerminated.connect(
        lambda status, code: state["terminated"].append([str(status), int(code)])
    )
    view.show()
    view.setHtml("<html><head><title>LPH_RENDERER_PROBE</title></head>"
                 "<body>Local renderer probe. No network or project process.</body></html>")
    QTimer.singleShot(15000, app.quit)
    app.exec()
    state.update({"qpa": app.platformName(), "qt": qVersion(),
                  "pyside": PySide6.__version__, "messages": messages})
    print("PROBE_JSON " + json.dumps(state, ensure_ascii=True), flush=True)
    view.close()
    qInstallMessageHandler(None)
    return 0 if state["ok"] else 1


def diagnostic() -> int:
    if sys.platform != "win32":
        raise RuntimeError("The parent diagnostic is Windows-only; use --bare for local validation")
    base_sha = os.environ.get("BASE_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", base_sha) is None:
        raise RuntimeError("BASE_SHA must be the exact validated PR base commit")
    base = Path(os.environ["RUNNER_TEMP"]) / "lph-renderer-base"
    if base.exists():
        raise RuntimeError(f"Refusing to overwrite an existing baseline tree: {base}")
    subprocess.run(["git", "worktree", "add", "--detach", str(base), base_sha],
                   cwd=ROOT, check=True, timeout=60)
    modes = [
        ("offscreen", {"QT_QPA_PLATFORM": "offscreen"}),
        ("offscreen-logged", {"QT_QPA_PLATFORM": "offscreen",
                              "QT_FORCE_STDERR_LOGGING": "1"}),
        ("native-windows", {"QT_QPA_PLATFORM": "windows",
                             "QT_FORCE_STDERR_LOGGING": "1"}),
        ("offscreen-confirm", {"QT_QPA_PLATFORM": "offscreen",
                               "QT_FORCE_STDERR_LOGGING": "1"}),
    ]
    report = {"diagnostic_only": True, "base_sha": base_sha,
              "pr_head_sha": os.environ["PR_HEAD_SHA"],
              "checkout_sha": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "results": []}
    destination = ROOT / "renderer-probe.json"
    for name, changes in modes:
        env = dict(os.environ)
        for key in ("QT_QPA_PLATFORM", "QT_FORCE_STDERR_LOGGING", "QTWEBENGINE_CHROMIUM_FLAGS"):
            env.pop(key, None)
        env.update(changes)
        for subject, path, args in [
            ("bare-qt", Path(__file__), ["--bare"]),
            ("hub-candidate", ROOT / "tests/test_window_e2e.py", [f"--test={TEST}"]),
            *([("hub-base", base / "tests/test_window_e2e.py", [f"--test={TEST}"])]
              if name == "offscreen" else []),
        ]:
            print(f"BEGIN {name} {subject}", flush=True)
            try:
                child = subprocess.run([sys.executable, str(path), *args], cwd=ROOT,
                                       env=env, capture_output=True, text=True, timeout=30)
                code, output = child.returncode, child.stdout + child.stderr
            except subprocess.TimeoutExpired as exc:
                data = exc.stdout or b""
                output = "TIMEOUT: " + (data.decode(errors="replace")
                                        if isinstance(data, bytes) else data)
                code = None
            row = {"mode": name, "subject": subject, "returncode": code,
                   "settings": changes, "output": output}
            report["results"].append(row)
            destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(row, ensure_ascii=True), flush=True)
    print("DIAGNOSTIC COMPLETE: this is not a passing product check", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(bare_page() if sys.argv[1:] == ["--bare"] else diagnostic())
