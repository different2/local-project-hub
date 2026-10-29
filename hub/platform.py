"""Platform differences, isolated in one module (release spec §3).

The rest of the app must never branch on `sys.platform`. Anything that
genuinely differs between macOS, Windows and Linux lives here behind a small
function, so supporting another platform later is a change to this file only.
"""

from __future__ import annotations

import os
import ntpath
import re
import shlex
import shutil
import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def split_command(command: str) -> list[str]:
    """Split a command line into argv, honouring the platform's quoting rules.

    shlex defaults to POSIX rules, which mangle Windows paths — a backslash is
    an escape character there, so `C:\\Projects\\app\\server.py` loses its
    separators. On Windows use native double-quote/backslash rules, plus the
    legacy single-quote syntax used by Hub-generated suggestions and records.
    """
    command = (command or "").strip()
    if not command:
        return []
    if IS_WINDOWS:
        return _windows_argv(command)
    return shlex.split(command, posix=True)


def prepend_interpreter(argv: list[str], interpreter: str = "") -> list[str]:
    """Compose saved launch fields consistently, without lookup or mutation.

    Legacy records can name Python in both fields. A selected Python replaces
    only that redundant executable; script-only and other-language forms keep
    the ordinary interpreter-prepending contract.
    """
    tokens = list(argv)
    interpreter = (interpreter or "").strip()
    if not interpreter:
        return tokens
    python_name = r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?"
    if (tokens and re.fullmatch(python_name, ntpath.basename(interpreter), re.I)
            and re.fullmatch(python_name, ntpath.basename(tokens[0]), re.I)):
        tokens = tokens[1:]
    return [interpreter, *tokens]


def _windows_argv(command: str) -> list[str]:
    """Parse Windows double quotes and legacy Hub single-quoted fragments.

    The latter include shlex.quote's concatenated spans for apostrophes. Treat
    an unquoted interior apostrophe literally; no shell metacharacters execute.
    """
    argv: list[str] = []
    token: list[str] = []
    quote = ""
    started = False
    legacy_single = False
    i = 0
    while i < len(command):
        char = command[i]
        if not quote and char in " \t":
            if started:
                argv.append("".join(token))
                token = []
            started = legacy_single = False
            i += 1
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                token.append(char)
            i += 1
            continue
        if char == "'" and not quote and (not started or legacy_single):
            quote = "'"
            started = legacy_single = True
            i += 1
            continue
        if char == "\\":
            started = True
            end = i
            while end < len(command) and command[end] == "\\":
                end += 1
            count = end - i
            if end < len(command) and command[end] == '"':
                token.append("\\" * (count // 2))
                i = end
                if count % 2:
                    token.append('"')
                    i += 1
                # An even run leaves the following quote as a delimiter.
            else:
                token.append("\\" * count)
                i = end
            continue
        if char == '"':
            started = True
            if quote == '"' and i + 1 < len(command) and command[i + 1] == '"':
                token.append('"')
                i += 2
            else:
                quote = "" if quote == '"' else '"'
                i += 1
            continue
        token.append(char)
        started = True
        i += 1
    if quote:
        raise ValueError("No closing quotation")
    if started:
        argv.append("".join(token))
    return argv


def interpreter_candidates(explicit: str = "") -> list[str]:
    """Python interpreters to try, best first.

    `explicit` (the project's configured interpreter) always wins. On Windows
    the bare name `python3` does not exist — the launcher is `python`, plus the
    Microsoft Store alias and the `py` launcher — so those are substituted for
    a bare python3 rather than failing with "No such file".
    """
    explicit = (explicit or "").strip()
    if explicit:
        return [explicit]
    if IS_WINDOWS:
        return ["python", "py", "python3"]
    return ["python3", "python"]


def resolve_interpreter(explicit: str = "", *, path: str | None = None) -> tuple[str | None, str | None]:
    """Find a usable interpreter, searching the child's PATH when supplied.

    Returns (path_or_name, error). When nothing is found the error explains
    what to install, which the UI surfaces instead of a bare "file not found"
    (release spec §8: "handles ... missing interpreters").

    The "no interpreter" message only mentions Python when the thing being
    resolved actually *is* Python; for any other command the hub should not
    lecture the user about installing Python.
    """
    explicit = (explicit or "").strip()
    path_rules = ntpath if IS_WINDOWS else os.path
    if explicit and path_rules.dirname(explicit):
        # Explicit paths are never substituted with a different installation.
        # The launch layer anchors relative paths to the project's directory.
        return explicit, None

    candidates = [explicit] if explicit else interpreter_candidates()
    if IS_WINDOWS and explicit.lower() in {"python", "python.exe", "python3", "python3.exe"}:
        # Existing/auto-detected commands commonly say python3, even when the
        # Windows installation exposes only python.exe or the py launcher.
        candidates.extend(interpreter_candidates())
    for candidate in dict.fromkeys(candidates):
        found = shutil.which(candidate, path=path)
        if found:
            return found, None

    if explicit:
        return None, (
            f"could not find “{explicit}”. Check the path, or put the tool on "
            "your PATH."
        )

    if IS_WINDOWS:
        return None, (
            "no Python interpreter found on PATH. Install Python from "
            "python.org (tick 'Add python.exe to PATH') and try again."
        )
    return None, (
        "no Python interpreter found on PATH. Install Python 3 and try again."
    )


def open_in_file_manager(path: str) -> bool:
    """Reveal a folder in the OS file manager. False if it could not be done."""
    if not path or not os.path.isdir(path):
        return False
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: SLF001 - Windows-only, guarded
        elif IS_MACOS:
            import subprocess

            subprocess.Popen(["open", path])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def platform_label() -> str:
    """Human-readable platform name for logs and error reports."""
    if IS_WINDOWS:
        return f"Windows {sys.getwindowsversion().major}.{sys.getwindowsversion().minor}"  # type: ignore[attr-defined]
    if IS_MACOS:
        import platform

        return f"macOS {platform.mac_ver()[0]}"
    import platform

    return f"Linux {platform.release()}"


def arch_label() -> str:
    import platform

    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine, machine or "unknown"
    )
