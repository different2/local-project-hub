"""Launch at login (release spec §9).

Opt-in and OFF by default. Implemented with each platform's supported
mechanism, never a hidden background service:

  * macOS  — a LaunchAgent plist in ~/Library/LaunchAgents
  * Windows — a Run registry key under HKCU (per-user, no admin needed)
  * Linux  — an XDG autostart .desktop file

set_enabled(False) removes the registration cleanly rather than leaving a
dangling entry.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

LABEL = "local.local-project-hub"
DISPLAY_NAME = "Local Project Hub"


def _main_script() -> Path:
    """The source entry point, next to the `hub` package."""
    return Path(__file__).resolve().parent.parent / "main.py"


def _app_argv() -> list[str]:
    """The command as SEPARATE argv entries.

    Each platform's launcher expects a list (macOS ProgramArguments) or a
    command line built from one (Windows registry value, XDG Exec=). Returning
    a single pre-quoted string forced callers to embed quotes inside an
    argument, which produced a malformed value in development mode:

        "C:\\Python\\python.exe" "C:\\app\\main.py"     # one string

    A packaged app runs its own executable with no arguments; a source checkout
    runs main.py under the current interpreter.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller/Briefcase: sys.executable is the app itself.
        return [sys.executable]
    return [sys.executable, str(_main_script())]


# ---------- macOS ----------


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _mac_set(on: bool) -> tuple[bool, str | None]:
    path = _mac_plist_path()
    if not on:
        try:
            if path.exists():
                path.unlink()
            return True, None
        except OSError as e:
            return False, f"Could not remove the login item: {e}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": LABEL,
            # One entry per argument. The old ["/usr/bin/open", "-a",
            # "\"python\" \"main.py\""] both misused `open -a` and embedded a
            # second quoted command line inside a single argument.
            "ProgramArguments": _app_argv(),
            "RunAtLoad": True,
        }
        with open(path, "wb") as fh:
            plistlib.dump(plist, fh)
        return True, None
    except OSError as e:
        return False, f"Could not create the login item: {e}"


def _mac_is_enabled() -> bool:
    return _mac_plist_path().exists()


# ---------- Windows ----------


def _win_key_name() -> str:
    return "LocalProjectHub"


def _win_command_line() -> str:
    """A correctly quoted Windows command line for the Run key.

    `subprocess.list2cmdline` is the standard-library implementation of the
    quoting rules the Windows loader uses, so an executable or script path with
    spaces is quoted once (not wrapped in a second pair of quotes).
    """
    import subprocess

    return subprocess.list2cmdline(_app_argv())


def _win_set(on: bool) -> tuple[bool, str | None]:
    try:
        import winreg
    except ImportError as e:  # pragma: no cover - non-Windows
        return False, f"Windows registry is unavailable: {e}"
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                # Per-user key needs no admin; list2cmdline quotes paths once.
                winreg.SetValueEx(
                    key, _win_key_name(), 0, winreg.REG_SZ, _win_command_line()
                )
            else:
                try:
                    winreg.DeleteValue(key, _win_key_name())
                except FileNotFoundError:
                    pass  # already absent, which is the desired state
        return True, None
    except OSError as e:
        return False, f"Could not change the Windows startup entry: {e}"


def _win_is_enabled() -> bool:
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return False
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _win_key_name())
            return True
    except OSError:
        return False


# ---------- Linux ----------


def _linux_desktop_path() -> Path:
    base = Path.home() / ".config" / "autostart"
    return base / "local-project-hub.desktop"


def _linux_set(on: bool) -> tuple[bool, str | None]:
    path = _linux_desktop_path()
    if not on:
        try:
            if path.exists():
                path.unlink()
            return True, None
        except OSError as e:
            return False, f"Could not remove the autostart entry: {e}"
    try:
        import shlex

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={DISPLAY_NAME}\n"
            # Exec= takes a shell-like command line, so quote each argv entry.
            f"Exec={shlex.join(_app_argv())}\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        return True, None
    except OSError as e:
        return False, f"Could not create the autostart entry: {e}"


def _linux_is_enabled() -> bool:
    return _linux_desktop_path().exists()


# ---------- public API ----------


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return _mac_is_enabled()
    if sys.platform.startswith("win"):
        return _win_is_enabled()
    return _linux_is_enabled()


def set_enabled(on: bool) -> tuple[bool, str | None]:
    """Enable/disable launch at login. Returns (ok, error_message)."""
    if sys.platform == "darwin":
        return _mac_set(on)
    if sys.platform.startswith("win"):
        return _win_set(on)
    return _linux_set(on)


def mechanism_name() -> str:
    """Which mechanism this platform uses, for the preferences help text."""
    if sys.platform == "darwin":
        return "a login item"
    if sys.platform.startswith("win"):
        return "the Windows startup registry entry"
    return "an autostart entry"


if __name__ == "__main__":
    print(f"launch at login: {is_enabled()} ({mechanism_name()})")
