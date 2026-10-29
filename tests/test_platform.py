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


def test_prepend_interpreter_preserves_tokens_and_shared_legacy_semantics():
    cases = [
        (["python3", "-u", "-m", "http.server"], "/selected/.venv/bin/python",
         ["/selected/.venv/bin/python", "-u", "-m", "http.server"]),
        (["PYTHON3.EXE", "app.py", "two words"], r"C:\selected env\Scripts\python.exe",
         [r"C:\selected env\Scripts\python.exe", "app.py", "two words"]),
        (["app.py", "--label=exact"], "/selected/python", ["/selected/python", "app.py", "--label=exact"]),
        (["./start.sh", "two words"], "/bin/bash", ["/bin/bash", "./start.sh", "two words"]),
        (["node", "app.js"], "", ["node", "app.js"]),
    ]
    for argv, interpreter, expected in cases:
        original = list(argv)
        assert pf.prepend_interpreter(argv, interpreter) == expected
        assert argv == original, "composition mutated parsed/saved tokens"


def test_split_command_empty():
    assert pf.split_command("") == []
    assert pf.split_command("   ") == []


def test_split_command_windows_keeps_backslashes() -> None:
    """The bug this guards: shlex POSIX mode eats backslashes in Windows paths."""
    import shlex

    # Drive the platform helper, not shlex directly: an earlier version of this
    # test called shlex.split(posix=False) itself and so passed while the real
    # split_command was broken on Windows.
    got = pf._windows_argv(r"python C:\Projects\app\server.py")
    assert got == ["python", r"C:\Projects\app\server.py"], got

    # and the POSIX mode really would break it, proving the guard is needed
    broken = shlex.split(r"python C:\Projects\app\server.py", posix=True)
    assert broken != got, "expected posix mode to mangle the path"


def test_split_command_windows_strips_quotes() -> None:
    """posix=False keeps the quote characters; the child must not see them.

    This is the Windows failure CI reported:

        FAIL test_split_command_quoted: ['python3', '-c', '"print(1)"']

    The same command on POSIX gives 'print(1)'. Left unfixed, every quoted
    argument on Windows arrives with literal quotes attached, so
    `python -c "print(1)"` fails with a syntax error inside the child.
    """
    got = pf._windows_argv('python3 -c "print(1)"')
    assert got == ["python3", "-c", "print(1)"], got
    # identical to what the POSIX branch produces
    assert got == pf.split_command('python3 -c "print(1)"'), (
        "Windows and POSIX branches disagree on a quoted argument"
    )


def test_windows_argv_keeps_interior_quotes_intact() -> None:
    """Only a matching SURROUNDING pair is removed, never an interior one.

    Guarded with a case that has no ambiguous escaping: a quoted argument
    containing a single-quoted word. The important property is that the
    surrounding double quotes go while the inner ones stay.
    """
    got = pf._windows_argv("python -c \"print('hi')\"")
    assert got == ["python", "-c", "print('hi')"], got


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

    # /tmp is not a directory on a fresh Windows runner. This test validates
    # records without launching them; the suite's own folder exists everywhere.
    working_dir = str(Path(__file__).resolve().parent)
    rec = sm.validate(
        {
            "name": "Node app",
            "command": "npm run dev",  # no python anywhere
            "url": "http://127.0.0.1:5173/",
            "working_dir": working_dir,
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
            "working_dir": working_dir,
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


def test_windows_generic_python_fallback_preserves_explicit_choices():
    from unittest.mock import patch

    child_path = r"C:\project\tools"
    found = r"C:\project\tools\python.exe"
    calls = []

    def which(name, *, path=None):
        calls.append((name, path))
        return found if name == "python" else None

    with patch.object(pf, "IS_WINDOWS", True), patch.object(pf.shutil, "which", which):
        for name in ("python3", "python3.exe", "python", "python.exe"):
            path, error = pf.resolve_interpreter(name, path=child_path)
            assert (path, error) == (found, None), (name, path, error, calls)
        assert calls and all(path == child_path for name, path in calls), calls
        calls.clear()
        chosen = r"C:\chosen\venv\Scripts\python.exe"
        assert pf.resolve_interpreter(chosen, path=child_path) == (chosen, None)
        assert calls == [], "an explicitly selected executable must never be substituted"
        path, error = pf.resolve_interpreter("missing-node", path=child_path)
        assert path is None and error and "Python" not in error, (path, error)


def test_windows_commands_round_trip_suggestions_and_native_arguments():
    import random
    import subprocess
    import tempfile
    from hub import detect_command as dc

    failures = []
    with tempfile.TemporaryDirectory() as folder:
        for name in ("my server.py", "owner's app.py", "O'Brien.py", "café's tool.py"):
            script = Path(folder) / name
            script.write_text("pass\n", encoding="utf-8")
            suggestion = dc.suggest_for_file(str(script))[0]
            actual = pf._windows_argv(suggestion.command)
            if actual != ["python3", name]:
                failures.append(("Hub-generated command", suggestion.command, actual, ["python3", name]))

    cases = [[], [""], ["plain's.py"], [r"C:\new\theme.json"],
             [r"C:\Program Files\site\\"], ['print("hi")'], ["a b", 'c"d', "e\\\"f"],
             ["two\twords", "café", "a#b%20"]]
    rng = random.Random(741)
    for _ in range(80):
        values = []
        for _ in range(rng.randrange(1, 5)):
            value = "".join(rng.choice("ab ç'\"\\\t") for _ in range(rng.randrange(0, 20)))
            # A leading unquoted apostrophe is reserved for legacy POSIX-style
            # Hub commands. Literal such values can use surrounding double quotes.
            values.append("arg" + value if value.startswith("'") else value)
        cases.append(values)
    for args in cases:
        expected = ["program.exe", *args]
        line = subprocess.list2cmdline(expected)
        try:
            actual = pf._windows_argv(line)
        except ValueError as error:
            failures.append((line, str(error), expected))
            continue
        if actual != expected:
            failures.append((line, actual, expected))
    assert not failures, failures


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
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "N passed, 1 failed" with no FAIL line to name
                # the 1. An unexpected error is a failure -- report it as one.
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
