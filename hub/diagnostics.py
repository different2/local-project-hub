"""Diagnostics and error reports (the "send error logs" feature).

Deliberately privacy-preserving: the report contains the app's own version,
platform, and the error text — NOT the user's projects, commands, paths,
environment variables, or anything a dashboard was showing. Project names are
included only as a count.

Two ways to send, both user-initiated and both visible:
  1. Save to a file the user can attach anywhere (works offline, no account).
  2. Open a prefilled GitHub issue in the browser (needs ISSUES_URL set).

Nothing is ever transmitted without the user pressing the button.
"""

from __future__ import annotations

import json
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__
from .platform import IS_MACOS, IS_WINDOWS, arch_label, platform_label

MAX_LOG_CHARS = 20000


def build_report(
    error: str | None = None,
    traceback_text: str | None = None,
    log_tail: str | None = None,
    project_count: int | None = None,
) -> dict:
    """Assemble a report dict. Contains no project data by design."""
    report = {
        "app": "Local Project Hub",
        "version": __version__,
        "platform": platform_label(),
        "arch": arch_label(),
        "python": platform.python_version(),
        "qt": _qt_version(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    if project_count is not None:
        # A count only — never names, paths, or commands.
        report["registered_projects"] = project_count
    if error:
        report["error"] = error.strip()[:4000]
    if traceback_text:
        report["traceback"] = traceback_text.strip()[:MAX_LOG_CHARS]
    if log_tail:
        report["log_tail"] = log_tail[-MAX_LOG_CHARS:]
    return report


def format_report(report: dict) -> str:
    """Human-readable text form, for saving or pasting into an issue."""
    lines = [
        f"{report.get('app')} {report.get('version')} — error report",
        f"Platform: {report.get('platform')} ({report.get('arch')})",
        f"Python: {report.get('python')}   Qt: {report.get('qt')}",
        f"When: {report.get('timestamp')}",
    ]
    if "registered_projects" in report:
        lines.append(f"Registered projects: {report['registered_projects']}")
    if report.get("error"):
        lines += ["", "What happened:", report["error"]]
    if report.get("traceback"):
        lines += ["", "Traceback:", report["traceback"]]
    if report.get("log_tail"):
        lines += ["", "Recent log:", report["log_tail"]]
    return "\n".join(lines).strip() + "\n"


def save_report(report: dict, directory: Path | None = None) -> Path:
    """Write the report to a file and return its path."""
    directory = directory or Path.home() / "Desktop"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"local-project-hub-report-{stamp}.txt"
    path.write_text(format_report(report), encoding="utf-8")
    return path


def issue_url(report: dict) -> str | None:
    """A prefilled new-issue URL, or None when no tracker is configured."""
    from .update_config import ISSUES_URL

    if not ISSUES_URL:
        return None
    from urllib.parse import quote

    title = f"Error report — {report.get('version')} on {report.get('platform')}"
    body = format_report(report)
    return f"{ISSUES_URL}?title={quote(title)}&body={quote(body)}"


def current_exception_report() -> dict:
    """Capture the in-flight exception, for the global error handler."""
    exc_type, exc, tb = sys.exc_info()
    if exc is None:
        return build_report(error="(no active exception)")
    return build_report(
        error=f"{exc_type.__name__}: {exc}" if exc_type else str(exc),
        traceback_text="".join(traceback.format_exception(exc_type, exc, tb)),
    )


def _qt_version() -> str:
    try:
        from PySide6.QtCore import qVersion

        return qVersion()
    except Exception:
        return "unknown"


def describe_platform_support() -> str:
    """One line stating what this build supports, for the About dialog."""
    names = []
    if IS_MACOS:
        names.append("macOS")
    if IS_WINDOWS:
        names.append("Windows")
    if not names:
        names.append("this platform")
    return " and ".join(names)


if __name__ == "__main__":
    print(json.dumps(build_report(error="example", project_count=2), indent=2))
