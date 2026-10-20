"""The page a project's tab shows before it runs (and while it runs, if it has
no dashboard).

The window tests assert the behaviour; these keep the page itself honest —
the button has to point where the window is listening, and a project name is
user data that must never be pasted into HTML unescaped.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import startpage  # noqa: E402

REC = {"id": "abc123", "name": "My Server", "command": "python3 server.py"}


def test_the_start_button_points_at_the_intercepted_url() -> None:
    html = startpage.start_page_html(REC)
    href = startpage.action_url("abc123", "start")
    assert href == "https://hub.invalid/start/abc123", href
    assert f'href="{href}"' in html, "the page has no Start link to the action URL"
    assert ">Start<" in html, "the button is not labelled Start"


def test_the_page_names_the_project_and_its_command() -> None:
    html = startpage.start_page_html(REC)
    assert "My Server" in html
    assert "python3 server.py" in html
    assert "Nothing runs until you press Start" in html


def test_a_running_project_without_a_dashboard_gets_a_status_card() -> None:
    html = startpage.start_page_html(REC, state="running")
    assert "Project is running" in html
    assert 'class="btn"' not in html, "a running project still offers Start"
    assert "terminal" in html, "it does not say where the output went"


def test_starting_and_error_states_say_something_useful() -> None:
    starting = startpage.start_page_html(REC, state="starting")
    assert "Starting" in starting and 'class="btn"' not in starting

    failed = startpage.start_page_html(REC, state="error", detail="Traceback: boom")
    assert "Traceback: boom" in failed
    assert 'class="btn"' in failed, "a failed project cannot be retried"


def test_project_names_are_escaped_not_injected() -> None:
    html = startpage.start_page_html(
        {"id": "x", "name": "<script>alert(1)</script>", "command": "a & b"}
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html


def test_ids_are_url_quoted() -> None:
    assert startpage.action_url("a b/c") == "https://hub.invalid/start/a%20b%2Fc"


def test_page_uses_the_colours_it_is_given() -> None:
    html = startpage.start_page_html(REC, colors={"bg": "#123456", "fg": "#abcdef"})
    assert "background: #123456" in html
    assert "color: #abcdef" in html


def test_page_survives_a_record_with_missing_fields() -> None:
    html = startpage.start_page_html({"id": "only-an-id"})
    assert "Project" in html
    assert 'class="btn"' in html


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("---", "all passed" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
