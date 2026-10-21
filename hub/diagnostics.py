"""Diagnostics and error reports (the "send error logs" feature).

Privacy-preserving by construction. The report contains the app's version,
platform, a project COUNT, and a sanitised summary of HUB-LEVEL messages. It
never contains:

  * a project's stdout/stderr or its terminal pane,
  * anything a dashboard was showing,
  * a project's name,
  * a working directory or any other filesystem path,
  * a complete startup command,
  * a dashboard URL,
  * credentials or token-shaped strings.

Sanitisation happens HERE, where the export is assembled -- not in one display
-- so the saved file, the copied/pasted text, and the prefilled GitHub issue
URL all inherit exactly the same redactions. URL-encoding a secret for the
issue link is not sanitisation; the value has to be removed before it reaches
either path.

The standalone crash-report path (`current_exception_report`) uses the same
registered project context as Help → Report a Problem. Project names are kept
separate from other sensitive values so a one-character name can be redacted
as a whole word without replacing every occurrence of that letter in ordinary
prose.

Two ways to send, both user-initiated and both visible:
  1. Save to a file the user can attach anywhere (works offline, no account).
  2. Open a prefilled GitHub issue in the browser (needs ISSUES_URL set).

Nothing is ever transmitted without the user pressing the button.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__
from .platform import IS_MACOS, IS_WINDOWS, arch_label, platform_label

MAX_LOG_CHARS = 20000

# Only the hub's own messages are considered. Project output is never admitted
# to a report, even when a caller passes a combined log by mistake.
_HUB_PREFIX = "[hub]"

# Patterns that identify data which must not leave the machine.
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_WINDOWS_PATH_RE = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/][^\s\"'<>|]+|\\\\[^\s\"'<>|]+)"
)
_POSIX_PATH_RE = re.compile(r"(?<![\w])/(?:[^\s/\"'<>]+/)+[^\s\"'<>]*")
_SECRET_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
        r"secret|password|passwd)\b\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
)


# The last known project identity, registered by the Hub window. Both the
# Help → Report a Problem path and the standalone crash-report path use this
# unless they pass an explicit context. It is cleared when the window closes.
_CONTEXT_SENSITIVE: tuple[str, ...] = ()
_CONTEXT_NAMES: tuple[str, ...] = ()


def _clean_values(values, min_len: int) -> tuple[str, ...]:
    cleaned = {
        str(v).strip()
        for v in (values or ())
        if v is not None and len(str(v).strip()) >= min_len
    }
    return tuple(sorted(cleaned, key=len, reverse=True))


def set_project_context(sensitive=(), project_names=()) -> None:
    """Register the current project identity for every report path.

    `sensitive` holds commands, folders, URLs and environment values (values
    shorter than two characters are ignored). `project_names` allows a
    one-character name: those are redacted only as whole words, so ordinary
    prose is not destroyed character by character.
    """
    global _CONTEXT_SENSITIVE, _CONTEXT_NAMES
    _CONTEXT_SENSITIVE = _clean_values(sensitive, min_len=2)
    _CONTEXT_NAMES = _clean_values(project_names, min_len=1)


def clear_project_context() -> None:
    set_project_context()


def _redact_exact(text: str, value: str) -> str:
    """Remove a known value without turning short names into character soup."""
    if len(value) >= 3:
        return text.replace(value, "<redacted>")
    # One- and two-character names: only whole tokens. Do not replace every
    # occurrence of a common letter inside unrelated words.
    return re.sub(
        rf"(?<!\w){re.escape(value)}(?!\w)", "<redacted>", text
    )


def sanitise_text(
    text: str | None, sensitive=(), project_names=()
) -> str:
    """Remove known-sensitive values, paths, URLs and secret-shaped strings.

    `sensitive` holds exact commands, paths, URLs and environment values.
    `project_names` is separate so a one-character project name can be
    redacted with word boundaries without treating every occurrence of that
    letter as sensitive. Longest values are replaced first so a command
    containing a path is removed whole rather than leaving fragments.
    """
    if not text:
        return ""
    out = text
    values = [
        (value, False) for value in _clean_values(sensitive, min_len=2)
    ] + [
        (value, True) for value in _clean_values(project_names, min_len=1)
    ]
    values.sort(key=lambda item: len(item[0]), reverse=True)
    for value, _is_name in values:
        out = _redact_exact(out, value)
    out = _URL_RE.sub("<url>", out)
    out = _WINDOWS_PATH_RE.sub("<path>", out)
    out = _POSIX_PATH_RE.sub("<path>", out)
    for pattern in _SECRET_RES:
        out = pattern.sub("<secret>", out)
    return out


def _sanitise_hub_log(
    text: str | None, sensitive=(), project_names=()
) -> str:
    """Keep only the hub's own log lines, sanitised.

    Project panes carry raw stdout/stderr and are never part of a report. The
    hub pane is what remains useful for diagnosis: "update check failed",
    "could not parse command", "process exited (code=...)", and similar.
    """
    kept = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith(_HUB_PREFIX):
            continue
        kept.append(sanitise_text(stripped, sensitive, project_names))
    return "\n".join(kept)


def build_report(
    error: str | None = None,
    traceback_text: str | None = None,
    log_tail: str | None = None,
    project_count: int | None = None,
    sensitive=None,
    project_names=None,
) -> dict:
    """Assemble a sanitised report. Contains no project data by design.

    When `sensitive`/`project_names` are omitted, the last context registered
    with `set_project_context()` is used. That makes the Help menu, a saved
    report and the standalone crash-report path follow the same policy instead
    of the crash path silently missing project names.

    `log_tail` is expected to be hub-level text (the window passes only the
    hub terminal pane). Any line that is not a hub message is dropped here as
    a second line of defence, so a future caller cannot accidentally attach a
    project's raw output.
    """
    if sensitive is None:
        sensitive = _CONTEXT_SENSITIVE
    if project_names is None:
        project_names = _CONTEXT_NAMES
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
        report["registered_projects"] = int(project_count)
    if error:
        cleaned = sanitise_text(error, sensitive, project_names).strip()
        if cleaned:
            report["error"] = cleaned[:4000]
    if traceback_text:
        cleaned = sanitise_text(
            traceback_text, sensitive, project_names
        ).strip()
        if cleaned:
            report["traceback"] = cleaned[:MAX_LOG_CHARS]
    if log_tail:
        cleaned = _sanitise_hub_log(log_tail, sensitive, project_names)
        if cleaned.strip():
            report["log_tail"] = cleaned[-MAX_LOG_CHARS:]
    return report


def format_report(report: dict) -> str:
    """Human-readable text form, for saving or pasting into an issue.

    Every value in `report` has already been sanitised by build_report(); this
    function adds no new data.
    """
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
        lines += ["", "Recent hub messages:", report["log_tail"]]
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
    """A prefilled new-issue URL, or None when no tracker is configured.

    The body is the same sanitised text format_report() produces; nothing
    extra is added for the browser.
    """
    from .update_config import ISSUES_URL

    if not ISSUES_URL:
        return None
    from urllib.parse import quote

    title = f"Error report — {report.get('version')} on {report.get('platform')}"
    body = format_report(report)
    return f"{ISSUES_URL}?title={quote(title)}&body={quote(body)}"


def current_exception_report(
    sensitive=None, project_names=None
) -> dict:
    """Capture the in-flight exception under the same privacy policy.

    Omitted identity arguments use the context registered by the Hub window,
    so a project name embedded in an exception message is redacted just as it
    is in Help → Report a Problem.
    """
    exc_type, exc, tb = sys.exc_info()
    if exc is None:
        return build_report(
            error="(no active exception)",
            sensitive=sensitive,
            project_names=project_names,
        )
    return build_report(
        error=f"{exc_type.__name__}: {exc}" if exc_type else str(exc),
        traceback_text="".join(traceback.format_exception(exc_type, exc, tb)),
        sensitive=sensitive,
        project_names=project_names,
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
