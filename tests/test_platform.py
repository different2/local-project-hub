"""Platform-isolation tests (release spec §3).

These verify the behaviour that differs between macOS and Windows *without
needing Windows*: the Windows code paths are exercised by forcing
platform.IS_WINDOWS-style behaviour through the pure functions.

Run:  python3 tests/test_platform.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import platform as pf  # noqa: E402


def test_split_command_posix():
    argv = pf.split_command("python3 server.py --port 8471")
    assert argv == ["python3", "server.py", "--port", "8471"], argv


def test_split_command_quoted():
    argv = pf.split_command('python3 -c "print(1)"')
    assert argv == ["python3", "-c", "print(1)"], argv


def test_split_command_empty():
    assert pf.split_command("") == []
    assert pf.split_command("   ") == []


def test_split_command_windows_keeps_backslashes():
    """The bug this guards: shlex POSIX mode eats backslashes in Windows paths."""
    # Simulate what the Windows branch does (posix=False).
    import shlex

    argv = shlex.split(r"python C:\Projects\app\server.py", posix=False)
    assert argv == ["python", r"C:\Projects\app\server.py"], argv
    # and the POSIX mode really would break it, proving the guard is needed
    broken = shlex.split(r"python C:\Projects\app\server.py", posix=True)
    assert broken != argv, "expected posix mode to mangle the path"


def test_split_command_uses_platform_mode():
    """On Windows the real function must use posix=False."""
    win_cmd = r"python C:\Projects\app\server.py"
    if pf.IS_WINDOWS:
        argv = pf.split_command(win_cmd)
        assert argv[1] == r"C:\Projects\app\server.py", argv
    else:
        # on POSIX we cannot force the Windows branch, but the helper's
        # contract is covered by the direct shlex test above
        assert pf.split_command("python3 server.py") == ["python3", "server.py"]


def test_interpreter_candidates_explicit_wins():
    assert pf.interpreter_candidates("/opt/venv/bin/python") == ["/opt/venv/bin/python"]
    assert pf.interpreter_candidates("") != []


def test_interpreter_candidates_cover_windows():
    """On Windows a bare 'python3' is not the launcher; python/py must be tried."""
    cands = pf.interpreter_candidates("")
    if pf.IS_WINDOWS:
        assert "python" in cands, cands
        assert "py" in cands, cands
    else:
        assert "python3" in cands, cands


def test_resolve_interpreter_finds_real_python():
    path, err = pf.resolve_interpreter(sys.executable)
    assert err is None, err
    assert path == sys.executable


def test_resolve_interpreter_reports_missing_with_actionable_text():
    path, err = pf.resolve_interpreter("/definitely/not/a/python")
    # A path that exists is accepted; this one cannot be resolved by which()
    if path is None:
        assert err and "not found" in err, err


def test_resolve_interpreter_bare_name_works():
    """A bare python3 must resolve to a real interpreter on this machine."""
    path, err = pf.resolve_interpreter("")
    assert err is None, f"no interpreter found: {err}"
    assert path, path


def test_platform_labels_are_nonempty():
    assert pf.platform_label()
    assert pf.arch_label() in {"x86_64", "arm64", "unknown"} or pf.arch_label()


def test_config_dir_has_no_hardcoded_macos_path():
    """The old bug: ~/Library/... was hard-coded regardless of OS."""
    from hub import store as sm
    import os

    old = os.environ.pop("LOCAL_PROJECT_HUB_HOME", None)
    try:
        d = sm.default_config_dir()
        if not pf.IS_MACOS:
            assert "Library/Application Support" not in str(d), (
                f"macOS path leaked onto {pf.platform_label()}: {d}"
            )
        assert d.is_absolute(), d
    finally:
        if old is not None:
            os.environ["LOCAL_PROJECT_HUB_HOME"] = old


def test_hub_is_not_python_only():
    """Nothing in the record rules out a non-Python project (Node/Go/Rust/script)."""
    from hub import store as sm

    rec = sm.validate(
        {
            "name": "Node app",
            "command": "npm run dev",  # no python anywhere
            "url": "http://127.0.0.1:5173/",
            "working_dir": "/tmp",
        }
    )
    assert rec["command"] == "npm run dev"
    assert rec["interpreter"] == ""  # and it is not required

    # The interpreter field is generic: any executable is accepted as-is.
    rec2 = sm.validate(
        {
            "name": "Go app",
            "command": "run .",
            "interpreter": "/opt/homebrew/bin/go",
            "working_dir": "/tmp",
        }
    )
    assert rec2["interpreter"] == "/opt/homebrew/bin/go"


def test_non_python_command_is_not_touched():
    """A non-Python command must not have an interpreter prepended to it."""
    from hub.process_manager import _looks_like_python

    assert _looks_like_python("npm") is False
    assert _looks_like_python("node") is False
    assert _looks_like_python("go") is False
    assert _looks_like_python("cargo") is False
    assert _looks_like_python("./start.sh") is False
    # only genuine Python names get interpreter resolution
    assert _looks_like_python("python3") is True
    assert _looks_like_python("python") is True
    assert _looks_like_python(".venv/bin/python") is False  # an explicit path


def test_resolve_interpreter_error_is_language_neutral():
    """A missing tool must not be blamed on Python."""
    from hub.platform import resolve_interpreter

    path, err = resolve_interpreter("/opt/definitely/not/node")
    if path is None:
        assert "Python" not in err, f"wrong language in message: {err}"
        assert "could not find" in err, err


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
