"""TEMPORARY observation workbench: remove before final verification.

Not a product test. Compare pinned Qt versions on each Windows image without
sandbox/GPU bypasses. All runtime results come from real bounded subprocesses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ("6.7.3", "6.12.0")
MARKER = "LPH_QT_COMPAT_READY"


def bare_page() -> int:
    import PySide6
    from PySide6.QtCore import QTimer, qInstallMessageHandler, qVersion
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    messages = []
    qInstallMessageHandler(lambda kind, context, message: messages.append(str(message)))
    app = QApplication(["qt-compat-probe"])
    view = QWebEngineView()
    view.resize(640, 480)
    expected = os.environ.get("LPH_EXPECTED_TITLE", MARKER)
    state = {"loaded": None, "title": "", "terminated": [], "ok": False}
    scheduled = False

    def finish():
        state["ok"] = (state["loaded"] is True and state["title"] == expected
                       and not state["terminated"])
        screenshot = os.environ.get("LPH_PROBE_SCREENSHOT")
        if screenshot:
            path = Path(screenshot)
            path.parent.mkdir(parents=True, exist_ok=True)
            state["screenshot_saved"] = bool(view.grab().save(str(path)))
        app.quit()

    def ready():
        nonlocal scheduled
        if not scheduled and state["loaded"] is True and state["title"] == expected:
            scheduled = True
            QTimer.singleShot(400, finish)

    def loaded(ok):
        state["loaded"] = bool(ok)
        ready()

    def titled(title):
        state["title"] = str(title)
        ready()

    view.loadFinished.connect(loaded)
    view.titleChanged.connect(titled)
    view.page().renderProcessTerminated.connect(
        lambda status, code: state["terminated"].append([str(status), int(code)])
    )
    view.show()
    view.setHtml("<html><head><title>" + MARKER + "</title></head>"
                 "<body style='background:#eef5ff;color:#132840;padding:30px'>"
                 "<h1>Renderer compatibility check</h1>"
                 "<p>Default sandbox. Local HTML. No project or network.</p></body></html>")
    QTimer.singleShot(15000, finish)
    app.exec()
    state.update({"qpa": app.platformName(), "qt": qVersion(),
                  "pyside": PySide6.__version__, "messages": messages,
                  "visible": view.isVisible(), "expected_title": expected,
                  "disable_sandbox_env": os.environ.get("QTWEBENGINE_DISABLE_SANDBOX"),
                  "chromium_flags": os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS")})
    print("PROBE_JSON " + json.dumps(state), flush=True)
    view.close()
    qInstallMessageHandler(None)
    return 0 if state["ok"] else 1


def observe() -> int:
    if sys.platform != "win32":
        raise RuntimeError("Parent observation workbench requires Windows")
    image = os.environ["PROBE_IMAGE"]
    report = {"diagnostic_only": True, "image": image,
              "requested_head": os.environ["PR_HEAD_SHA"],
              "windows": platform.platform(), "python": sys.version,
              "source_head": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "results": []}
    destination = ROOT / "qt-compat-report.json"

    def save():
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")

    save()
    for version in VERSIONS:
        executable = Path(os.environ["RUNNER_TEMP"]) / ("lph-qt-" + version) / "Scripts/python.exe"
        if not executable.is_file():
            raise RuntimeError(f"Missing prepared interpreter: {executable}")
        cases = [
            ("bare-offscreen", "offscreen", Path(__file__), ["--bare"], True),
            ("bare-native", "windows", Path(__file__), ["--bare"], True),
            ("hub-start-page", "offscreen", ROOT / "tests/test_window_e2e.py",
             ["--test=test_selecting_a_project_shows_a_start_page_and_runs_nothing"], True),
            ("hub-dom-start", "offscreen", ROOT / "tests/test_window_e2e.py",
             ["--test=test_pressing_start_on_the_page_runs_the_project"], True),
            ("hub-popup", "offscreen", ROOT / "tests/test_popup_bridge.py",
             ["--test=test_target_blank_link_and_closing"], True),
        ]
        if version == VERSIONS[-1]:
            cases.append(("observer-wrong-title-control", "offscreen", Path(__file__), ["--bare"], False))
        for name, qpa, script, args, positive in cases:
            env = dict(os.environ)
            for key in ("QTWEBENGINE_DISABLE_SANDBOX", "QTWEBENGINE_CHROMIUM_FLAGS", "QT_QPA_PLATFORM"):
                env.pop(key, None)
            env.update({"QT_QPA_PLATFORM": qpa, "QT_FORCE_STDERR_LOGGING": "1",
                        "PYTHONUNBUFFERED": "1"})
            if script == Path(__file__):
                env["LPH_PROBE_SCREENSHOT"] = str(ROOT / "qt-compat-images" / f"{version}-{name}.png")
            if not positive:
                env["LPH_EXPECTED_TITLE"] = "DELIBERATELY_WRONG_TITLE"
            print(f"BEGIN {image} Qt{version} {name}", flush=True)
            child = subprocess.Popen([str(executable), str(script), *args], cwd=ROOT,
                                     env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
            try:
                output, _ = child.communicate(timeout=45)
                code = child.returncode
            except subprocess.TimeoutExpired:
                # Only terminate the real child tree just created here. Keep
                # its Popen handle alive; never kill by image name or fake PID.
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                               capture_output=True, timeout=15)
                child.kill()
                output, _ = child.communicate(timeout=10)
                output = "TIMEOUT: " + output
                code = None
            state = None
            for line in output.splitlines():
                if line.startswith("PROBE_JSON "):
                    state = json.loads(line[len("PROBE_JSON "):])
            healthy = code == 0
            if script == Path(__file__):
                healthy = bool(healthy and state and state["ok"] and not state["terminated"]
                               and state["disable_sandbox_env"] is None and state["chromium_flags"] is None
                               and state["pyside"] == version)
            else:
                test_name = args[0].split("=", 1)[1]
                healthy = healthy and ("PASS " + test_name) in output
            row = {"version": version, "case": name, "qpa": qpa,
                   "positive_case": positive, "returncode": code,
                   "healthy": healthy, "bare_state": state, "output": output}
            report["results"].append(row)
            save()
            print(json.dumps(row), flush=True)
    print("OBSERVATIONS COLLECTED — inspect JSON; this is NOT full product verification", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(bare_page() if sys.argv[1:] == ["--bare"] else observe())
