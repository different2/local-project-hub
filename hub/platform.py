"""Platform differences, isolated in one module (release spec §3).

The rest of the app must never branch on `sys.platform`. Anything that
genuinely differs between macOS, Windows and Linux lives here behind a small
function, so supporting another platform later is a change to this file only.
"""

from __future__ import annotations

import os
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
    separators. On Windows we use posix=False, which keeps backslashes intact
    and treats only double quotes as quoting.
    """
    command = (command or "").strip()
    if not command:
        return []
    if IS_WINDOWS:
        return shlex.split(command, posix=False)
    return shlex.split(command, posix=True)


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


def resolve_interpreter(explicit: str = "") -> tuple[str | None, str | None]:
    """Find a usable interpreter.

    Returns (path_or_name, error). When nothing is found the error explains
    what to install, which the UI surfaces instead of a bare "file not found"
    (release spec §8: "handles ... missing interpreters").

    The "no interpreter" message only mentions Python when the thing being
    resolved actually *is* Python; for any other command the hub should not
    lecture the user about installing Python.
    """
    explicit = (explicit or "").strip()
    if explicit:
        # A path was given: accept it if it exists, else let the OS try it as
        # a name so a venv-relative entry still works from the project folder.
        if os.path.exists(explicit) or os.sep in explicit or (os.altsep and os.altsep in explicit):
            return explicit, None
        found = shutil.which(explicit)
        if found:
            return found, None
        return None, (
            f"could not find “{explicit}”. Check the path, or put the tool on "
            "your PATH."
        )

    # Nothing configured: only hunt for Python when the caller is asking about
    # a Python command (see process_manager._looks_like_python).
    for candidate in interpreter_candidates():
        found = shutil.which(candidate)
        if found:
            return found, None
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
