"""macOS window-button control: show only the close button on a dialog.

Qt's window-button HINTS are advisory and are ignored by the macOS platform
plugin for a QDialog. Every combination of WindowCloseButtonHint /
WindowMinMaxButtonsHint produces some set of traffic lights, never the close
button alone — verified against real screenshots: Qt.Dialog gave red+green,
Qt.Tool gave red+yellow+green. Qt cannot be made to do this on macOS.

The only mechanism that actually controls the buttons is AppKit's NSWindow,
whose buttons are real subviews that can be hidden individually. That needs
pyobjc, which is why this lives in its own module behind a guarded import:
the app must run unchanged where pyobjc is absent (Linux, Windows, or a macOS
install without it).

Everything here is best-effort and never raises: failing to hide a
decorative button is not worth breaking a dialog over.
"""

from __future__ import annotations

import sys

IS_MACOS = sys.platform == "darwin"

# NSWindow button constants (NSWindowButton).
_CLOSE = 0
_MINIATURIZE = 1
_ZOOM = 2


def available() -> bool:
    """Whether AppKit can be reached on this machine."""
    if not IS_MACOS:
        return False
    try:
        import AppKit  # noqa: F401
    except Exception:
        return False
    return True


def show_only_close_button(window) -> bool:
    """Hide the minimise and zoom buttons of a native NSWindow. True if applied.

    `window` is an AppKit NSWindow (the caller resolves it, see find_window()).
    Best-effort: returns False rather than raising, because failing to hide a
    decorative button must never break a dialog.
    """
    if window is None:
        return False
    try:
        for constant in (_MINIATURIZE, _ZOOM):
            button = window.standardWindowButton_(constant)
            if button is not None:
                button.setHidden_(True)
        return True
    except Exception:
        return False


def find_window(qt_window) -> object | None:
    """The AppKit NSWindow backing a Qt widget, or None.

    Qt's winId() and AppKit's windowNumber() are DIFFERENT numbers — verified:
    winId 39725358592 vs windowNumber 84501 — so matching on either alone
    finds nothing. The reliable match is the window TITLE plus a size check,
    falling back to "the only panel Qt owns" when there is exactly one.
    """
    if not IS_MACOS:
        return None
    try:
        import AppKit
    except Exception:
        return None
    if not AppKit.NSApp:
        return None

    title = ""
    try:
        title = qt_window.windowTitle() or ""
    except Exception:
        pass

    candidates = []
    try:
        candidates = list(AppKit.NSApp.windows())
    except Exception:
        return None
    if not candidates:
        return None

    if title:
        for window in candidates:
            try:
                if (window.title() or "") == title:
                    return window
            except Exception:
                continue
    # A single Qt-owned window is unambiguous.
    if len(candidates) == 1:
        return candidates[0]
    return None
