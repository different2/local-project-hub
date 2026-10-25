"""TEMPORARY: actual Linux child-exit comparison, never release acceptance."""
from __future__ import annotations
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = "464a95df75bf6d303ebbb700a992389b76449599"
RESELECT = "test_reselecting_a_project_does_not_open_a_second_tab"
UPDATE = "test_check_for_updates_always_reports"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    assert sys.platform == "linux" and os.getuid() != 0
    assert "QTWEBENGINE_DISABLE_SANDBOX" not in os.environ
    baseline = subprocess.check_output(["git", "show", BASE + ":tests/test_window_e2e.py"], cwd=root, text=True)
    original = out / "baseline.py"
    original.write_text(baseline)
    target = next(n for n in ast.parse(baseline).body if isinstance(n, ast.FunctionDef) and n.name == RESELECT)
    lines = baseline.splitlines(keepends=True)
    block = "".join(lines[target.lineno-1:target.end_lineno])
    assert block.endswith("        w.close()\n")
    replaced = block + "        from PySide6.QtCore import QCoreApplication, QEvent\n        w.deleteLater()\n        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)\n        _spin(100)\n"
    cleanup = out / "deferred-cleanup.py"
    cleanup.write_text(baseline.replace(block, replaced, 1))
    old = '''        assert dlg.primary.isVisible() and "Download" in dlg.primary.text(), (
            "the update offer did not offer a download"
        )'''
    new = '''        if IS_MACOS or sys.platform.startswith("win"):
            assert dlg.primary.isVisible() and "Download" in dlg.primary.text(), (
                "the update offer did not offer a download"
            )
        else:
            assert dlg.primary.isVisible() and dlg.primary.text() == "OK", (
                "Linux must show a dismissible result, not offer the MSI fixture"
            )
            assert "No installer" in dlg.detail.text(), dlg.detail.text()'''
    assert old in baseline
    fixed_update = out / "platform-update.py"
    fixed_update.write_text(baseline.replace(old, new, 1))
    for p in (original, cleanup, fixed_update):
        ast.parse(p.read_text())
    os.environ["PYTHONPATH"] = os.pathsep.join((str(root / "tests"), str(root)))
    os.environ["LOCAL_PROJECT_HUB_HOME"] = str(out / "state")
    spec = importlib.util.spec_from_file_location("diagnostic_runner", root / "tests/run_all.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.interpreter = lambda: sys.executable
    records = []
    cases = [("update-baseline", "offscreen", original, UPDATE, 1),
             ("update-platform-aware", "offscreen", fixed_update, UPDATE, 1),
             ("reselect-baseline", "offscreen", original, RESELECT, 20),
             ("reselect-baseline", "xcb", original, RESELECT, 20),
             ("reselect-deferred-cleanup", "offscreen", cleanup, RESELECT, 20)]
    for label, platform, source, test, repeats in cases:
        runner.GUI_ENV = {"QT_QPA_PLATFORM": platform}
        for index in range(repeats):
            code, output = runner.run_one(source, True, ["--test=" + test])
            log = out / f"{len(records):03d}-{label}-{platform}.log"
            log.write_text(output)
            record = {"label": label, "platform": platform, "repeat": index,
                      "code": code, "pass_printed": "PASS " + test in output, "log": log.name}
            records.append(record)
            (out / "actual-results.json").write_text(json.dumps(records, indent=2))
            print(json.dumps(record), flush=True)
    summary = []
    for label, platform, source, test, repeats in cases:
        rows = [r for r in records if r["label"] == label and r["platform"] == platform]
        summary.append({"label": label, "platform": platform, "count": len(rows),
                        "clean": sum(r["code"] == 0 and r["pass_printed"] for r in rows),
                        "crashes": sum(r["code"] < 0 for r in rows)})
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    # Collection success is NOT app acceptance. Every raw nonzero is retained.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
