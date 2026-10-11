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


def _app_executable() -> str:
    """The command to run at login: the packaged app if there is one."""
    if getattr(sys, "frozen", False):
        # PyInstaller/Briefcase: sys.executable is the app itself.
        return sys.executable
    # Development: run main.py with the same interpreter.
    return f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "main.py"}"'


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
            "ProgramArguments": ["/usr/bin/open", "-a", _app_executable()],
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


def _win_set(on: bool) -> tuple[bool, str | None]:
    try:
        import winreg
    except ImportError as e:  # pragma: no cover - non-Windows
        return False, f"Windows registry is unavailable: {e}"
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                # Quote the path so spaces survive; per-user key needs no admin.
                winreg.SetValueEx(key, _win_key_name(), 0, winreg.REG_SZ, f'"{_app_executable()}"')
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={DISPLAY_NAME}\n"
            f"Exec={_app_executable()}\n"
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
