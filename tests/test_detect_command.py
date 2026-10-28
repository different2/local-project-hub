"""Suggesting a start command from a project folder (the Add dialog's helper).

The suggestion is an OFFER, not a rewrite: these tests pin the recipes
(package.json scripts + lockfile choice, Python entries and venvs, Go, Rust,
static HTML), and the safety rules — an unrecognisable folder yields nothing,
and a suggestion never invents flags or spellings that could not run as
configured.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hub import detect_command as dc  # noqa: E402


def _mk_project(tmp: Path, files: dict[str, str]) -> Path:
    """Write a fake project tree and return its directory."""
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


# ---------- node ----------


def test_npm_dev_script() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"package.json": '{"scripts": {"dev": "next dev"}}'})
        got = dc.suggest_commands(d)
        assert got, "no suggestion for a package.json with a dev script"
        assert got[0].command == "npm run dev", got[0]
        assert "package.json" in got[0].source, got[0].source
        assert got[0].confidence >= 0.8, got[0]


def test_npm_start_when_there_is_no_dev() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"package.json": '{"scripts": {"start": "react-scripts start"}}'})
        got = dc.suggest_command(d)
        assert got and got.command == "npm run start", got


def test_dev_wins_over_start() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"package.json": '{"scripts": {"start": "x", "dev": "y"}}'},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "npm run dev", got


def test_yarn_lockfile_selects_yarn() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"package.json": '{"scripts": {"dev": "vite"}}', "yarn.lock": ""},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "yarn dev", got
        assert any("yarn.lock" in e for e in got.evidence), got.evidence


def test_pnpm_lockfile_selects_pnpm() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"package.json": '{"scripts": {"dev": "vite"}}', "pnpm-lock.yaml": ""},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "pnpm dev", got


def test_package_json_without_scripts_yields_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"package.json": '{"name": "x", "version": "1.0.0"}'})
        assert dc.suggest_commands(d) == []


def test_broken_package_json_is_tolerated() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"package.json": "{this is not json"})
        assert dc.suggest_commands(d) == []


# ---------- python ----------


def test_python_app_py() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"requirements.txt": "flask\n", "app.py": "print('hi')\n"},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "python3 app.py", got
        assert got.interpreter == "", got


def test_python_server_py_with_pyproject() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"pyproject.toml": "[project]\nname='x'\n", "server.py": "pass\n"},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "python3 server.py", got


def test_python_manage_py_is_django() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"requirements.txt": "django\n", "manage.py": "pass\n"},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "python3 manage.py runserver", got
        assert "Django" in got.source or "manage.py" in got.source, got.source


def test_python_without_a_manifest_yields_nothing() -> None:
    """A bare app.py is not enough evidence to guess a launch command."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"app.py": "pass\n"})
        assert dc.suggest_commands(d) == []


def test_python_venv_becomes_the_interpreter() -> None:
    """With a venv, the interpreter field runs the command and the command
    must not stack its own `python3` on top of it."""
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {
                "requirements.txt": "flask\n",
                "app.py": "pass\n",
                ".venv/bin/python": "#!/bin/sh\n",
            },
        )
        got = dc.suggest_command(d)
        assert got and got.command == "app.py", got
        assert got.interpreter == ".venv/bin/python", got
        assert any("virtual environment" in e for e in got.evidence), got.evidence


# ---------- go / rust / static ----------


def test_go_module() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"go.mod": "module x\n"})
        got = dc.suggest_command(d)
        assert got and got.command == "go run .", got


def test_rust_crate() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"Cargo.toml": "[package]\nname='x'\n"})
        got = dc.suggest_command(d)
        assert got and got.command == "cargo run", got


def test_static_index_html() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"index.html": "<html></html>\n"})
        got = dc.suggest_command(d)
        assert got and got.command == "python3 -m http.server 8000", got


def test_node_beats_static_when_both_are_present() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"package.json": '{"scripts": {"dev": "vite"}}', "index.html": "<html></html>\n"},
        )
        got = dc.suggest_command(d)
        assert got and got.command == "npm run dev", got


# ---------- safety rules ----------


def test_non_directory_yields_nothing() -> None:
    # Path("") is Path(".") — an empty path must NOT scan the current
    # working directory; it means "nothing chosen yet".
    assert dc.suggest_commands("") == [], "an empty path scanned the cwd"
    assert dc.suggest_commands("/definitely/not/a/real/folder-xyz") == []
    assert dc.suggest_command(None) is None, "None scanned the cwd"


def test_unrecognised_folder_yields_nothing() -> None:
    """An empty folder is an honest 'no idea', not a guess."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "notes.txt").write_text("hello\n", encoding="utf-8")
        assert dc.suggest_commands(d) == []


# ---------- a specific file (the dialog's File… button) ----------


def test_a_picked_python_file_is_the_start_command() -> None:
    """A file the user points at needs no manifest to be believed."""
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "obs_live.py"
        script.write_text("print('x')\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "python3 obs_live.py", got
        assert got[0].interpreter == "", got


def test_a_picked_python_file_in_a_venv_becomes_the_interpreter() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / ".venv" / "bin").mkdir(parents=True)
        (Path(d) / ".venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        script = Path(d) / "tool.py"
        script.write_text("pass\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "tool.py", got
        assert got[0].interpreter == ".venv/bin/python", got


def test_a_picked_manage_py_gets_runserver() -> None:
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "manage.py"
        script.write_text("pass\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "python3 manage.py runserver", got


def test_a_picked_html_file_is_served() -> None:
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "demo.html"
        page.write_text("<html></html>\n", encoding="utf-8")
        got = dc.suggest_for_file(str(page))
        assert got and got[0].command == "python3 -m http.server 8000", got


def test_a_picked_shell_or_command_file_runs_with_bash() -> None:
    with tempfile.TemporaryDirectory() as d:
        for name in ("deploy.sh", "start_dashboard.command"):
            script = Path(d) / name
            script.write_text("echo hi\n", encoding="utf-8")
            got = dc.suggest_for_file(str(script))
            assert got and got[0].command == f"bash {name}", (name, got)


def test_a_picked_go_file_runs_with_go_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "server.go"
        script.write_text("package main\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "go run server.go", got


def test_a_picked_js_file_without_a_package_is_node() -> None:
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "server.js"
        script.write_text("// x\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "node server.js", got


def test_a_picked_js_file_inside_a_node_project_uses_its_script() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"package.json": '{"scripts": {"dev": "vite"}}'})
        script = Path(d) / "server.js"
        script.write_text("// x\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "npm run dev", got


def test_picking_the_manifest_means_the_whole_project() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"package.json": '{"scripts": {"dev": "vite"}}'})
        got = dc.suggest_for_file(str(Path(d) / "package.json"))
        assert got and got[0].command == "npm run dev", got


def test_an_unrecognised_file_falls_back_to_the_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        _mk_project(
            Path(d),
            {"requirements.txt": "flask\n", "app.py": "pass\n", "notes.txt": "hi\n"},
        )
        got = dc.suggest_for_file(str(Path(d) / "notes.txt"))
        assert got and got[0].command == "python3 app.py", got


def test_an_unrecognised_file_in_a_plain_folder_yields_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "notes.txt").write_text("hi\n", encoding="utf-8")
        assert dc.suggest_for_file(str(Path(d) / "notes.txt")) == []


def test_a_picked_file_name_with_spaces_is_quoted() -> None:
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "my server.py"
        script.write_text("pass\n", encoding="utf-8")
        got = dc.suggest_for_file(str(script))
        assert got and got[0].command == "python3 'my server.py'", got


def test_suggest_for_file_rejects_things_that_are_not_files() -> None:
    with tempfile.TemporaryDirectory() as d:
        assert dc.suggest_for_file(str(Path(d))) == [], "a folder is not a file"
    assert dc.suggest_for_file("") == []
    assert dc.suggest_for_file(None) == []


# ---------- standalone HTML URL resolution ----------


def test_static_html_does_not_retarget_a_different_configured_port() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"report.html": "<main>report</main>"})
        rec = {"command": "python3 -m http.server 8000", "working_dir": d,
               "url": "http://127.0.0.1:9000/"}
        assert dashboard_url(rec) == rec["url"], "a different explicit endpoint was retargeted"


def test_static_html_picked_path_is_relative_to_the_project() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"public/chosen.html": "chosen", "public/other.html": "other"})
        rec = {"command": "python3 -m http.server 8000 --directory public", "working_dir": d,
               "url": "http://127.0.0.1:8000/", "entry_file": "public/chosen.html"}
        assert dashboard_url(rec) == "http://127.0.0.1:8000/chosen.html", (
            "the picked project-relative file was resolved against the server root twice"
        )
        _mk_project(Path(d), {"chosen.html": "outside", "public/chosen.html": "different"})
        rec["entry_file"] = "chosen.html"
        assert dashboard_url(rec) == rec["url"], "a different same-named served file replaced the picked file"


def test_static_html_named_page_is_read_only_and_url_encoded() -> None:
    from copy import deepcopy
    from hub.static_site import dashboard_url

    # Windows cannot create '?'; all platforms still exercise spaces, '#', '%'
    # and Unicode. Keep the extra POSIX filename coverage where it is legal.
    cases = [("review #1 50% café.htm", "review%20%231%2050%25%20caf%C3%A9.htm")]
    if sys.platform != "win32":
        cases.append(("review #1 ? 50% café.htm", "review%20%231%20%3F%2050%25%20caf%C3%A9.htm"))
    for name, encoded in cases:
        with tempfile.TemporaryDirectory() as d:
            body = "<main>Original page</main>"
            _mk_project(Path(d), {name: body, ".hidden.html": "hidden", "notes.txt": "notes"})
            rec = {"command": "python3 -m http.server 8000", "working_dir": d, "url": "http://[::]:8000/"}
            before = deepcopy(rec)
            assert dashboard_url(rec) == "http://[::]:8000/" + encoded
            assert rec == before and (Path(d) / name).read_text() == body


def test_static_html_explicit_routes_and_other_servers_stay_unchanged() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"app.html": "app"})
        base = {"command": "python3 -m http.server 8000", "working_dir": d, "url": "http://localhost:8000/"}
        for url in ("http://localhost:8000/chosen", "http://localhost:8000/?view=files",
                    "http://localhost:8000/#anchor", "https://localhost:8000/", "http://example.com:8000/"):
            rec = dict(base, url=url)
            assert dashboard_url(rec) == url, url
        for command in ("npm run dev", "python3 server.py", "python3 server.py -m http.server",
                        "python3 -m other http.server", "python3 -m http.server 8000 --cgi",
                        "python3 -m http.server 8000 && echo no", "python3 -m http.server --directory"):
            rec = dict(base, command=command)
            assert dashboard_url(rec) == rec["url"], command


def test_static_html_ambiguous_and_default_index_folders_stay_unchanged() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        rec = {"command": "python3 -m http.server 8000", "working_dir": d, "url": "http://localhost:8000/"}
        assert dashboard_url(rec) == rec["url"]
        _mk_project(Path(d), {"one.html": "one", "two.html": "two"})
        assert dashboard_url(rec) == rec["url"], "ambiguous folder was guessed"
        _mk_project(Path(d), {"index.html": "index"})
        assert dashboard_url(rec) == rec["url"], "conventional index route was changed"
        rec["entry_file"] = "two.html"
        assert dashboard_url(rec).endswith("/two.html"), "explicit picked file did not outrank index"


def test_static_html_served_directory_and_interpreter_are_respected() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"wrong.html": "wrong", "served pages/right.html": "right"})
        base = {"working_dir": d, "url": "http://127.0.0.1:8123/"}
        for command, extra in (("python3 -m http.server 8123 --directory 'served pages'", ""),
                               ("python3 -u -m http.server", "8123 -b 127.0.0.1 -d 'served pages'"),
                               ("python3 -m http.server 8123 --directory='served pages' --protocol HTTP/1.1", "")):
            rec = dict(base, command=command, args=extra)
            assert dashboard_url(rec).endswith("/right.html"), (command, extra)
        rec = dict(base, interpreter=".venv/bin/python", command="-m http.server 8123", args="-d 'served pages'")
        assert dashboard_url(rec).endswith("/right.html")


def test_static_html_missing_files_and_path_escapes_fail_closed() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "root"
        root.mkdir()
        _mk_project(root, {"one.html": "one"})
        outside = Path(d) / "outside.html"
        outside.write_text("outside")
        base = {"command": "python3 -m http.server 8000", "working_dir": str(root), "url": "http://localhost:8000/"}
        for entry in ("missing.html", "../outside.html", str(outside)):
            rec = dict(base, entry_file=entry)
            assert dashboard_url(rec) == rec["url"], entry
        assert dashboard_url(dict(base, working_dir="")) == base["url"]
        assert dashboard_url(dict(base, url="http://[broken")) == "http://[broken"


def test_static_html_authenticated_addresses_are_not_inferred() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"one.html": "one"})
        rec = {"command": "python3 -m http.server 8000", "working_dir": d,
               "url": "http://user:password@localhost:8000/"}
        assert dashboard_url(rec) == rec["url"], "explicit authenticated address was retargeted"


def test_static_html_does_not_retarget_a_different_bound_address() -> None:
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        _mk_project(Path(d), {"one.html": "one"})
        for bind in ("--bind 127.0.0.2", "--bind=::1", "-b localhost"):
            rec = {"command": "python3 -m http.server 8000 " + bind,
                   "working_dir": d, "url": "http://127.0.0.1:8000/"}
            assert dashboard_url(rec) == rec["url"], "a different or uncertain bind address was retargeted"


def test_static_html_storage_origin_is_canonical_and_conservative() -> None:
    from hub.static_site import static_site_origin

    with tempfile.TemporaryDirectory() as d:
        base = {"command": "python3 -m http.server 8000", "working_dir": d,
                "url": "http://LOCALHOST:8000/report.html?view=1#section"}
        assert static_site_origin(base) == "http://localhost:8000"
        assert static_site_origin(dict(base, command="python3 -m http.server 80", url="http://127.0.0.1:80/")) == "http://127.0.0.1"
        assert static_site_origin(dict(base, url="http://[::1]:8000/")) == "http://[::1]:8000"
        for url in ("http://example.com:8000/", "https://localhost:8000/", "http://localhost:9000/",
                    "http://name:password@localhost:8000/", "http://[broken", ""):
            assert not static_site_origin(dict(base, url=url)), url
        assert not static_site_origin(dict(base, command="python3 server.py"))


def test_static_html_path_resolution_failures_are_advisory() -> None:
    from unittest.mock import patch
    from hub.static_site import dashboard_url

    with tempfile.TemporaryDirectory() as d:
        rec = {"command": "python3 -m http.server 8000", "working_dir": d, "url": "http://localhost:8000/"}
        # Path.resolve raises RuntimeError for symlink loops on supported Python3.9.
        with patch("hub.static_site.Path.resolve", side_effect=RuntimeError("Symlink loop")):
            try:
                actual = dashboard_url(rec)
            except RuntimeError as exc:
                raise AssertionError("an advisory filesystem failure escaped into the GUI") from exc
        assert actual == rec["url"]


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
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "N passed, 1 failed" with no FAIL line naming
                # the 1. An unexpected error is a failure -- report it as one.
                fails += 1
                print(f"ERROR {_name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
