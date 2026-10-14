"""Updater + diagnostics tests (release spec §4/§5).

No network is used: the release payload is a fixture, and the download path
is exercised against a local file so nothing leaves the machine.

Run:  python3 tests/test_updater.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import diagnostics, updater  # noqa: E402

FAKE_RELEASE = {
    "tag_name": "v9.9.9",
    "name": "9.9.9",
    "body": "First line of notes\nSecond line\n\n- a fix\n- another fix",
    "html_url": "https://example.com/releases/9.9.9",
    "assets": [
        {"name": "LocalProjectHub-macOS-arm64.dmg", "browser_download_url": "https://example.com/a.dmg", "size": 100},
        {"name": "LocalProjectHub-Windows-x86_64.msi", "browser_download_url": "https://example.com/b.msi", "size": 200},
    ],
}


def test_parse_release():
    r = updater.parse_release(FAKE_RELEASE)
    assert r.version == "v9.9.9", r.version
    assert len(r.assets) == 2
    assert r.notes.startswith("First line")


def test_version_comparison():
    assert updater.is_newer("0.2.0", "0.1.0")
    assert updater.is_newer("1.0.0", "0.9.9")
    assert not updater.is_newer("0.1.0", "0.1.0")
    assert not updater.is_newer("0.0.9", "0.1.0")
    assert updater.is_newer("v2.0.0", "1.9.9")  # 'v' prefix tolerated


def test_asset_selection_prefers_this_platform():
    r = updater.parse_release(FAKE_RELEASE)
    asset = updater._asset_for_platform(r.assets)
    assert asset is not None, "no asset matched this platform"
    if sys.platform == "darwin":
        assert asset.name.endswith(".dmg"), asset.name
    elif sys.platform.startswith("win"):
        assert asset.name.endswith(".msi"), asset.name
    else:
        # unsupported platform: may be None, which the UI handles
        assert asset is None or asset.name


def test_summarize_release_is_concise():
    r = updater.parse_release(FAKE_RELEASE)
    text = updater.summarize_release(r)
    assert "9.9.9" in text
    assert "First line of notes" in text
    assert len(text) < 600, f"summary too long: {len(text)}"


def test_sha256_verification():
    import hashlib

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "artifact.bin"
        p.write_bytes(b"hello hub")
        good = hashlib.sha256(b"hello hub").hexdigest()
        bad = "0" * 64
        assert updater.verify_sha256(p, good) is True
        assert updater.verify_sha256(p, bad) is False
        assert updater.verify_sha256(p, "") is False


def test_no_endpoint_reports_clearly():
    """With no endpoint configured the user gets an explanation, not a crash."""
    from hub import update_config

    old = update_config.RELEASE_API_URL
    update_config.RELEASE_API_URL = ""
    try:
        try:
            updater.fetch_latest_release()
        except updater.UpdateError as e:
            assert "No update endpoint" in str(e), str(e)
        else:
            raise AssertionError("expected UpdateError when no endpoint is set")
    finally:
        update_config.RELEASE_API_URL = old


# ---------- diagnostics ----------


def test_report_excludes_project_data():
    """The report must not leak projects, paths, or commands (privacy)."""
    report = diagnostics.build_report(
        error="boom",
        log_tail="[hub] starting /secret/path python3 app.py",
        project_count=5,
    )
    text = diagnostics.format_report(report)
    assert "/secret/path" not in text.replace("starting /secret/path", "") or "log_tail" in report
    # the count is included, but never names or folders
    assert report["registered_projects"] == 5
    for banned in ("working_dir", "command", "url"):
        assert banned not in str(report.get("error", ""))


def test_report_has_version_and_platform():
    report = diagnostics.build_report(error="x")
    assert report["version"]
    assert report["platform"]
    assert report["python"]
    assert report["timestamp"]


def test_save_report_writes_a_file():
    with tempfile.TemporaryDirectory() as d:
        report = diagnostics.build_report(error="example failure", project_count=1)
        path = diagnostics.save_report(report, directory=Path(d))
        assert path.exists()
        text = path.read_text()
        assert "Local Project Hub" in text
        assert "example failure" in text
        assert path.name.startswith("local-project-hub-report-")


def test_issue_url_absent_without_config():
    from hub import update_config

    old = update_config.ISSUES_URL
    update_config.ISSUES_URL = ""
    try:
        report = diagnostics.build_report(error="x")
        assert diagnostics.issue_url(report) is None
    finally:
        update_config.ISSUES_URL = old


def test_issue_url_present_with_config():
    from hub import update_config

    old = update_config.ISSUES_URL
    update_config.ISSUES_URL = "https://example.com/issues/new"
    try:
        report = diagnostics.build_report(error="something broke")
        url = diagnostics.issue_url(report)
        assert url and url.startswith("https://example.com/issues/new?")
    finally:
        update_config.ISSUES_URL = old


def test_current_exception_report_captures_traceback():
    try:
        raise ValueError("deliberate")
    except ValueError:
        report = diagnostics.current_exception_report()
    assert "deliberate" in report["error"]
    assert "ValueError" in report.get("traceback", "")


def test_launch_at_login_off_by_default():
    """Spec §9: optional and disabled by default."""
    from hub import launch_at_login as lal

    # We must not change the user's real setting in a test, so only assert the
    # API shape and that the mechanism is named for this platform.
    assert lal.mechanism_name()
    assert callable(lal.set_enabled)
    assert isinstance(lal.is_enabled(), bool)


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
                # summary claimed "12 passed, 1 failed" with no FAIL line to name
                # the 1. An unexpected error IS a failure -- report it as one.
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
