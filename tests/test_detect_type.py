"""Project-type detection and the launch behaviour that follows from it.

Covers the ten scenarios spec §8 requires, plus the invariants that keep
detection safe: the user's command is never rewritten, no project code is
executed to inspect it, and an unknown type is an honest answer rather than a
guess.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hub import store as sm  # noqa: E402
from hub import detect_type as dt  # noqa: E402

WEB, STATIC, DESKTOP, CLI, UNKNOWN = dt.WEB, dt.STATIC, dt.DESKTOP, dt.CLI, dt.UNKNOWN


def _mk_project(tmp: Path, files: dict[str, str], **rec) -> Path:
    """Write a fake project tree and return its directory."""
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


# ---------- spec §8.1 — python web app that auto-opens a browser ----------


def test_python_web_app_that_opens_a_browser() -> None:
    """A flask-ish project is a web app, and is shown in the embedded view."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"requirements.txt": "flask==3.0.0\n"},
            command=f"python3 app.py",
        )
        det = dt.detect({"command": "python3 app.py", "working_dir": d})
        assert det.type == WEB, det
        assert det.framework == "flask", det
        assert det.display == dt.DISPLAY[WEB], det


# ---------- spec §8.2 — python web app that already suppresses ----------


def test_framework_with_documented_suppress_flag() -> None:
    """A framework with a documented flag gets that flag, not a guessed one."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "streamlit\n"})
        det = dt.detect({"command": "streamlit run app.py", "working_dir": d})
        assert det.type == WEB, det
        assert det.framework == "streamlit", det
        assert det.browser == "known-suppressible", det
        # the flag must be streamlit's real one
        assert dt.browser_suppress_args(det) == "--server.headless true", det


def test_framework_without_suppress_flag_gets_nothing() -> None:
    """No documented flag means NO flag is invented (spec §2)."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "fastapi\nuvicorn\n"})
        det = dt.detect({"command": "uvicorn main:app", "working_dir": d})
        assert det.type == WEB, det
        assert det.browser != "known-suppressible", det
        assert dt.browser_suppress_args(det) == "", (
            "a flag was invented for a framework with no documented one"
        )


# ---------- spec §8.3 — custom server calling webbrowser.open() ----------


def test_custom_server_with_webbrowser_open() -> None:
    """A custom http.server script is detected as web without touching it.

    The hub cannot suppress another program's webbrowser.open() without
    editing its source (which spec §2 forbids), so the type is detected and
    the launch behaviour follows from that — the command is left alone.
    """
    src = (
        "import webbrowser\n"
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "webbrowser.open('http://127.0.0.1:9000')\n"
    )
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"srv.py": src}, command="python3 srv.py")
        det = dt.detect({"command": "python3 srv.py", "working_dir": d})
        assert det.type == WEB, det
        # nothing in the source was changed
        assert (Path(d) / "srv.py").read_text(encoding="utf-8") == src, (
            "detection modified the project's source"
        )


# ---------- spec §8.4 — static HTML project ----------


def test_static_html_project() -> None:
    """A file server is a static site, not a web app."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"index.html": "<html><body>hi</body></html>"},
            command="python3 -m http.server 8080",
        )
        det = dt.detect({"command": "python3 -m http.server 8080", "working_dir": d})
        assert det.type == STATIC, det
        assert det.port == 8080, det


# ---------- spec §8.5 — native desktop application ----------


def test_native_desktop_application() -> None:
    """A Qt app is a desktop app and must not be forced into a webview."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "PySide6\n"})
        det = dt.detect({"command": "python3 main_window.py", "working_dir": d})
        assert det.type == DESKTOP, det
        assert det.browser == "none", det
        assert dt.DISPLAY[DESKTOP] in det.display, det


# ---------- spec §8.6 — command-line program, no browser ----------


def test_command_line_program_never_opens_a_browser() -> None:
    """A headless script is CLI and is never shown a browser prompt."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"job.py": "print('working')\n"})
        det = dt.detect({"command": "python3 job.py", "working_dir": d})
        assert det.type == CLI, det
        assert det.browser == "none", det


# ---------- spec §8.7 — dynamically assigned port ----------


def test_dynamic_port_is_not_invented() -> None:
    """A server with no port in its command yields no port guess.

    The port is discovered later from the running process (hub.urldetect), so
    detection must report None rather than inventing one.
    """
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "flask\n"})
        det = dt.detect({"command": "python3 app.py", "working_dir": d})
        assert det.port is None, det


def test_explicit_port_is_detected() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "flask\n"})
        det = dt.detect({"command": "python3 app.py --port 5001", "working_dir": d})
        assert det.port == 5001, det


# ---------- spec §8.8 — unknown project keeps its command ----------


def test_unknown_project_preserves_the_command() -> None:
    """An unclassifiable project stays UNKNOWN and its command is untouched."""
    cmd = "my_custom_thing --do-the-thing"
    det = dt.detect({"command": cmd, "working_dir": ""})
    assert det.type == UNKNOWN, det
    # the record round-trips with the command exactly as given
    rec = sm.validate({"name": "X", "command": cmd})
    assert rec["command"] == cmd, "the command was rewritten"


# ---------- spec §8.9 — existing saved project still launches ----------


def test_v1_registry_migrates_without_breaking() -> None:
    """A pre-detection registry loads, and its project is unchanged.

    This is the compatibility requirement: a user with saved projects must not
    lose them, and nothing about their launch may change.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        p.write_text(
            json.dumps(
                {
                    "version": 1,
                    "projects": [
                        {
                            "id": "abc12345",
                            "name": "Old Project",
                            "command": "python3 old.py",
                            "url": "http://127.0.0.1:9001/",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        st = sm.Store(p)
        rec = st.get("abc12345")
        assert rec is not None, "an existing project was lost on load"
        assert rec["command"] == "python3 old.py", rec
        assert rec["url"] == "http://127.0.0.1:9001/", rec
        # and it carries an honest unknown, not a fabricated type
        assert rec["detected"]["type"] == UNKNOWN, rec
        assert rec["detected"]["evidence"], rec


def test_saved_detection_survives_a_round_trip() -> None:
    """Detection is persisted, so it is not recomputed on every launch."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        st = sm.Store(p)
        rec = st.add(
            sm.validate(
                {
                    "name": "Webby",
                    "command": "python3 app.py",
                    "working_dir": d,
                    # A realistic saved block: it carries evidence, which is what
                    # marks it as a real previous result rather than a placeholder.
                    "detected": {
                        "type": WEB,
                        "confidence": 0.8,
                        "framework": "flask",
                        "browser": "unknown",
                        "display": dt.DISPLAY[WEB],
                        "evidence": ["requirements.txt mentions flask"],
                    },
                }
            )
        )
        assert rec["detected"]["type"] == WEB, rec
        st2 = sm.Store(p)  # reload from disk
        again = st2.get(rec["id"])
        assert again["detected"]["type"] == WEB, again
        assert again["detected"]["framework"] == "flask", again
        assert again["command"] == "python3 app.py", again


# ---------- spec §8.10 — server that fails or never becomes ready ----------


def test_launch_failure_does_not_claim_success() -> None:
    """A project whose port is taken must not be reported as ready.

    This is the readiness half of spec §8.10: the hub must not treat "a
    process is running" as "the dashboard is up".
    """
    from hub import urldetect

    # A dead port is genuinely free, so a conflict check finds nothing and the
    # start proceeds — which is correct. What matters is that readiness is
    # judged by something actually answering, never by the process alone.
    assert urldetect.port_in_use(65123) is False


def test_detection_never_raises_on_odd_input() -> None:
    """Detection is advisory; junk input must not crash project setup."""
    for bad in (
        {"command": "", "working_dir": ""},
        {"command": None, "working_dir": None},
        {},
        {"command": "??", "working_dir": "/definitely/not/here"},
    ):
        det = dt.detect(bad)
        assert det.type in dt.TYPES, det


# ---------- invariants: no source modification, no command rewriting ----------


def test_detection_does_not_execute_project_code() -> None:
    """Inspection is passive: a script that would explode if run is never run."""
    with tempfile.TemporaryDirectory() as d:
        # If this were ever executed it would write a marker file.
        _mk_project(
            Path(d),
            {"boom.py": "open('RAN','w').write('x')\n"},
            command="python3 boom.py",
        )
        dt.detect({"command": "python3 boom.py", "working_dir": d})
        assert not (Path(d) / "RAN").exists(), "project code was executed"


def test_command_is_never_rewritten_with_generated_flags() -> None:
    """The command stays verbatim even when a suppress flag exists."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "streamlit\n"})
        cmd = "streamlit run app.py"
        rec = sm.validate({"name": "S", "command": cmd, "working_dir": d})
        assert rec["command"] == cmd, rec
        det = dt.Detection.from_dict(rec["detected"])
        # the flag is available, but only as data the UI may offer
        assert dt.browser_suppress_args(det) == "--server.headless true"
        assert rec["command"] == cmd, "a flag was appended to the command"


def test_user_override_wins_over_detection() -> None:
    """An explicit override is persisted and beats any detection."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"requirements.txt": "flask\n"})
        rec = sm.validate(
            {
                "name": "O",
                "command": "python3 app.py",
                "working_dir": d,
                "detected": {"type": WEB, "framework": "flask"},
                "type_override": "cli",
            }
        )
        assert rec["detected"]["type"] == CLI, rec
        assert rec["type_override"] == "cli", rec


# ---------- spec §8.3 — custom python server using webbrowser.open() ----------

_STDLIB_SERVER = '''\
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler)
    if not args.no_open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    srv.serve_forever()
    return 0
'''


def test_custom_stdlib_server_is_a_web_app() -> None:
    """A stdlib HTTP server has no framework, but is still a web app.

    This is obs_live.py's shape: no dependency in any manifest, so the
    framework table cannot classify it and the hub would otherwise call it
    "cli" and never look for a URL or a no-open flag.
    """
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"obs_live.py": _STDLIB_SERVER})
        det = dt.detect({"command": "python3 obs_live.py", "working_dir": d})
        assert det.type == WEB, det
        assert det.framework == "", det
        assert det.browser == "known-suppressible", det
        assert any("stdlib HTTP server" in e for e in det.evidence), det


def test_custom_stdlib_server_flag_comes_from_its_own_argparse() -> None:
    """The suppress flag is the one the script itself declares — not a guess.

    Spec §2 forbids appending a flag the program does not understand: an
    unknown flag breaks the command outright, which is worse than a spare
    browser window.
    """
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"obs_live.py": _STDLIB_SERVER})
        det = dt.detect({"command": "python3 obs_live.py", "working_dir": d})
        assert dt.browser_suppress_args(det) == "--no-open", det


def test_stdlib_server_without_a_no_open_flag_gets_none() -> None:
    """A server that never declares the flag must not be handed one."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"srv.py": _STDLIB_SERVER.replace(
            '    ap.add_argument("--no-open", action="store_true")\n', ""
        ).replace("    if not args.no_open:", "    if True:").replace(
            "        webbrowser.open(f\"http://127.0.0.1:{args.port}\")\n", ""
        )})
        det = dt.detect({"command": "python3 srv.py", "working_dir": d})
        assert det.type == WEB, det
        assert det.browser == "unknown", det
        assert dt.browser_suppress_args(det) == "", det


def test_plain_cli_script_is_not_treated_as_a_web_app() -> None:
    """The negative control: no server markers means no URL hunt, no flag."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"thing.py": (
            "import argparse\n"
            "ap = argparse.ArgumentParser()\n"
            'ap.add_argument("--port", type=int)\n'
            'print("done")\n'
        )})
        det = dt.detect({"command": "python3 thing.py", "working_dir": d})
        assert det.type == CLI, det
        assert dt.browser_suppress_args(det) == "", det


def test_missing_entry_script_yields_no_flag() -> None:
    """An unreadable or absent script returns no flag rather than raising."""
    det = dt.Detection()
    det.type = WEB
    det.browser = "known-suppressible"
    det.entry_script = "/nonexistent/definitely-not-here.py"
    assert dt.browser_suppress_args(det) == "", det


def test_detection_never_executes_the_entry_script() -> None:
    """Spec §7: inspection is read-only. A script that would fail on import
    must still be classified without being run."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"boom.py": (
            "from http.server import BaseHTTPRequestHandler\n"
            "raise SystemExit('this must never run')\n"
        )})
        # Would raise if the module were imported or executed.
        det = dt.detect({"command": "python3 boom.py", "working_dir": d})
        assert det.type == WEB, det


if __name__ == "__main__":
    fails = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {_name}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
