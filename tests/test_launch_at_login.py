"""Launch-at-login command construction (INFO-003).

Development mode used to return one pre-quoted string:

    "C:\\Python\\python.exe" "C:\\app\\main.py"

macOS then put that whole string into a single ProgramArguments entry after
`open -a`, and Windows wrapped it in a second pair of quotes in the Run value.
These tests assert the structure each platform actually consumes: separate
argv entries on macOS, a correctly quoted Windows command line, and a
shell-parsed Exec= line on Linux.

They are unit tests with test doubles for the OS integration; no real login
item is created on this machine.
"""

from __future__ import annotations

import plistlib
import shlex
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import launch_at_login as lat  # noqa: E402


def _set_env(executable: str, module_file: Path, frozen: bool | None = None):
    """Temporarily point the module at a fake executable/script layout.

    Returns a restore function. `frozen=None` means "leave sys.frozen alone".
    """
    old_exe = sys.executable
    old_file = lat.__file__
    had_frozen = hasattr(sys, "frozen")
    old_frozen = getattr(sys, "frozen", None)

    sys.executable = executable
    lat.__file__ = str(module_file)
    if frozen is True:
        sys.frozen = True  # type: ignore[attr-defined]
    elif frozen is False and had_frozen:
        del sys.frozen  # type: ignore[attr-defined]

    def restore() -> None:
        sys.executable = old_exe
        lat.__file__ = old_file
        if had_frozen:
            sys.frozen = old_frozen  # type: ignore[attr-defined]
        elif hasattr(sys, "frozen"):
            del sys.frozen  # type: ignore[attr-defined]

    return restore


def test_dev_mode_is_separate_executable_and_script_arguments() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = (Path(d) / "Local Project Hub").resolve()
        module_file = root / "hub" / "launch_at_login.py"
        exe = r"C:\Program Files\Python\python.exe"
        restore = _set_env(exe, module_file, frozen=False)
        try:
            argv = lat._app_argv()
        finally:
            restore()
        assert argv == [exe, str(root / "main.py")], argv
        assert len(argv) == 2
        assert '"' not in argv[0] and '"' not in argv[1]


def test_packaged_mode_runs_the_app_itself() -> None:
    exe = r"C:\Program Files\Local Project Hub\Local Project Hub.exe"
    restore = _set_env(exe, Path("ignored.py"), frozen=True)
    try:
        argv = lat._app_argv()
    finally:
        restore()
    assert argv == [exe], argv


def test_windows_command_line_quotes_each_element_once() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = (Path(d) / "Local Project Hub").resolve()
        module_file = root / "hub" / "launch_at_login.py"
        exe = r"C:\Program Files\Python\python.exe"
        restore = _set_env(exe, module_file, frozen=False)
        try:
            line = lat._win_command_line()
            argv = lat._app_argv()
        finally:
            restore()
    expected = subprocess.list2cmdline([exe, str(root / "main.py")])
    assert line == expected, line
    assert argv[0] in line and str(root / "main.py") in line
    assert line.startswith('"') and line.endswith('"'), line
    assert '""' not in line, f"doubled quotes in {line!r}"
    assert line.count('" "') == 1, f"arguments are not separated correctly: {line!r}"


class _FakeKeyContext:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


class _FakeWinreg(types.ModuleType):
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 1
    REG_SZ = 1

    def __init__(self):
        super().__init__("winreg")
        self.set_values: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def OpenKey(self, root, path, reserved=0, access=0):
        return _FakeKeyContext()

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.set_values.append((name, value))

    def DeleteValue(self, key, name):
        self.deleted.append(name)


def test_windows_run_value_is_written_as_one_correct_command() -> None:
    fake = _FakeWinreg()
    saved = sys.modules.get("winreg")
    sys.modules["winreg"] = fake
    with tempfile.TemporaryDirectory() as d:
        root = (Path(d) / "Local Project Hub").resolve()
        module_file = root / "hub" / "launch_at_login.py"
        exe = r"C:\Program Files\Python\python.exe"
        restore = _set_env(exe, module_file, frozen=False)
        try:
            ok, err = lat._win_set(True)
            assert ok, err
            ok_off, err_off = lat._win_set(False)
            assert ok_off, err_off
        finally:
            restore()
            if saved is None:
                sys.modules.pop("winreg", None)
            else:
                sys.modules["winreg"] = saved

    assert len(fake.set_values) == 1, fake.set_values
    name, value = fake.set_values[0]
    assert name == lat._win_key_name()
    assert value == subprocess.list2cmdline([exe, str(root / "main.py")]), value
    assert not value.startswith('""'), value
    assert fake.deleted == [lat._win_key_name()], fake.deleted


def test_macos_plist_stores_separate_program_arguments() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = (Path(d) / "Local Project Hub").resolve()
        module_file = root / "hub" / "launch_at_login.py"
        plist_path = Path(d) / "login.plist"
        exe = "/Applications/Local Project Hub.app/Contents/MacOS/Hub"
        restore = _set_env(exe, module_file, frozen=False)
        original_path = lat._mac_plist_path
        lat._mac_plist_path = lambda: plist_path
        try:
            ok, err = lat._mac_set(True)
            assert ok, err
            with open(plist_path, "rb") as fh:
                data = plistlib.load(fh)
            ok_off, err_off = lat._mac_set(False)
            assert ok_off, err_off
        finally:
            lat._mac_plist_path = original_path
            restore()

    assert data["ProgramArguments"] == [exe, str(root / "main.py")], data
    assert "/usr/bin/open" not in data["ProgramArguments"]
    assert data["Label"] == lat.LABEL
    assert data["RunAtLoad"] is True
    assert not plist_path.exists(), "disabling did not remove the login item"


def test_linux_desktop_exec_round_trips_to_argv() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = (Path(d) / "Local Project Hub").resolve()
        module_file = root / "hub" / "launch_at_login.py"
        desktop_path = Path(d) / "autostart" / "local-project-hub.desktop"
        exe = str(Path(d) / "Program Files" / "python")
        restore = _set_env(exe, module_file, frozen=False)
        original_path = lat._linux_desktop_path
        lat._linux_desktop_path = lambda: desktop_path
        try:
            ok, err = lat._linux_set(True)
            assert ok, err
            text = desktop_path.read_text(encoding="utf-8")
            ok_off, err_off = lat._linux_set(False)
            assert ok_off, err_off
        finally:
            lat._linux_desktop_path = original_path
            restore()

    exec_line = next(
        line for line in text.splitlines() if line.startswith("Exec=")
    )
    parsed = shlex.split(exec_line[len("Exec="):], posix=True)
    assert parsed == [exe, str(root / "main.py")], parsed
    assert not desktop_path.exists(), "disabling did not remove the autostart entry"


if __name__ == "__main__":
    import inspect

    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                sig = inspect.signature(fn)
                if len(sig.parameters) > 0:
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
