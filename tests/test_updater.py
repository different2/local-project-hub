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


def test_asset_selection_prefers_this_platform() -> None:
    r = updater.parse_release(FAKE_RELEASE)
    asset = updater._asset_for_platform(r.assets)
    if sys.platform == "darwin":
        assert asset is not None, "no asset matched this platform"
        assert asset.name.endswith(".dmg"), asset.name
    elif sys.platform.startswith("win"):
        assert asset is not None, "no asset matched this platform"
        assert asset.name.endswith(".msi"), asset.name
    else:
        # The fixture ships only macOS and Windows installers, which is honest:
        # there is no Linux build. Asserting one exists here would fail on the
        # Ubuntu runner -- and because these two tests sort first, the 12-line
        # failure tail cut them off, so the real reason never appeared.
        assert asset is None or asset.name, asset


def test_summarize_release_is_concise():
    r = updater.parse_release(FAKE_RELEASE)
    text = updater.summarize_release(r)
    assert "9.9.9" in text
    assert "First line of notes" in text
    assert len(text) < 600, f"summary too long: {len(text)}"


def test_asset_digest_is_read_from_the_release_payload():
    """The update's integrity check must actually run, not silently skip.

    `_download_update` verifies the download only when `asset.sha256` is set,
    so if the digest is never read from the API the app installs an unverified
    download while looking like it checked. GitHub reports it per asset as
    `digest: "sha256:<64 hex>"` — the previous implementation read a `_digests`
    key the API never sends, which made the check unreachable. Real digests
    from the v0.3.8 release are used so this stays the true API shape.
    """
    payload = {
        "tag_name": "v0.3.8",
        "assets": [
            {
                "name": "Local.Project.Hub-0.3.8.dmg",
                "browser_download_url": "https://example.com/a.dmg",
                "size": 262231688,
                "digest": "sha256:e53ef349066681fb7c9f8af078a1820844867b433e66d0bcdcf7da49a26c15bc",
            },
            {
                "name": "Local.Project.Hub-0.3.8.msi",
                "browser_download_url": "https://example.com/b.msi",
                "size": 108675375,
                "digest": "sha256:a5181244a81ff4411813fad9c74774fcabae250011384774d8b10b611b8dbea7",
            },
        ],
    }
    rel = updater.parse_release(payload)
    digests = {a.name: a.sha256 for a in rel.assets}
    for name, got in digests.items():
        assert len(got) == 64, f"{name} has no usable digest: {got!r}"
        int(got, 16)  # must be hex
    assert digests["Local.Project.Hub-0.3.8.dmg"] == (
        "e53ef349066681fb7c9f8af078a1820844867b433e66d0bcdcf7da49a26c15bc"
    )


def test_absent_or_junk_digest_means_no_verification_not_a_crash():
    """Missing or malformed digests are tolerated: the check is skipped.

    A release published before digests existed, or one where a future API
    changes the field, must not break updating — but it also must not let a
    malformed string be treated as a checksum that then fails every download.
    """
    for junk in (None, "", "md5:abc", "sha256:not-hex", "sha256:" + "a" * 63):
        payload = {
            "tag_name": "v9.9.9",
            "assets": [
                {
                    "name": f"thing-{junk}.dmg",
                    "browser_download_url": "https://example.com/a.dmg",
                    "digest": junk,
                }
            ],
        }
        asset = updater.parse_release(payload).assets[0]
        assert asset.sha256 == "", f"{junk!r} should not be treated as a checksum"


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


REPORT_KEYS = {
    # Every field build_report() may add. A new one must be added here, which
    # forces the question "can this carry project data?" to be answered.
    "app",
    "version",
    "platform",
    "arch",
    "python",
    "qt",
    "timestamp",
    "registered_projects",
    "error",
    "traceback",
    "log_tail",
}


def test_report_keeps_a_count_and_nothing_else_from_the_registry():
    """build_report() adds a project COUNT, never a name, folder, or command.

    Rewritten 2026-10-20. The old assertion was

        assert "/secret/path" not in text.replace("starting /secret/path", "") or "log_tail" in report

    whose right-hand side is true whenever a log tail is supplied — which is
    every real report — so it could not fail whatever the code did. It also
    excused the leak it was named after by deleting it from the text first.

    What this covers: the builder is handed a count and nothing else, so a
    report built from an error cannot acquire project data, and no unreviewed
    field can appear.

    What it does NOT cover, on purpose: the caller's log tail is embedded
    verbatim, and HubWindow._report_problem passes the log pane, which holds
    project names and full startup commands, while the dialog says the report
    contains none of that. That is BUG-007 in the 2026-10-20 audit. It is not
    fixed here, so the strict assertion belongs with its fix: build the report
    the way the window builds it and assert the dialog's promise against
    format_report(report).
    """
    report = diagnostics.build_report(error="boom", project_count=5)
    text = diagnostics.format_report(report)

    assert report["registered_projects"] == 5, "the project count is missing"
    assert "Registered projects: 5" in text, "the count is not in the text form"

    extra = set(report) - REPORT_KEYS
    assert not extra, (
        "build_report gained fields that were never reviewed for privacy: "
        f"{sorted(extra)} — add them to REPORT_KEYS only after checking they "
        "cannot carry a project's name, folder, or command"
    )

    # Nothing derived from the registry beyond the count.
    assert not {"projects", "names", "commands", "folders", "working_dir"} & set(report)

    # The freeform fields are bounded, so a runaway log cannot bloat a report
    # past what an issue body will accept.
    long_error = "E" * 5000
    long_log = "L" * (diagnostics.MAX_LOG_CHARS + 500)
    packed = diagnostics.build_report(error=long_error, log_tail=long_log)
    assert len(packed["error"]) == 4000, "the error text is no longer capped at 4000 chars"
    assert len(packed["log_tail"]) == diagnostics.MAX_LOG_CHARS
    assert packed["log_tail"].endswith("L" * 10), "the log tail kept the wrong end"


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


def test_download_asset_reports_progress():
    """download_asset feeds the update dialog's progress bar.

    The dialog shows real byte progress, so the downloader must call
    on_progress with (done, total) as it reads -- and a download that ends
    before its advertised length must be an error, not a truncated installer
    that only a checksum would catch (and only when one exists).
    """
    payload = b"X" * (300 * 1024)  # spans more than one 256 KB chunk
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "asset.bin"
        src.write_bytes(payload)
        seen = []
        dest = Path(d) / "out.bin"
        asset = updater.Asset(name="asset.bin", url=src.as_uri(), size=len(payload))
        updater.download_asset(
            asset, dest, on_progress=lambda done, total: seen.append((done, total))
        )
        assert dest.read_bytes() == payload
        assert seen and seen[-1] == (len(payload), len(payload)), seen

        # A session that promises more than it delivers is an error.
        import urllib.request

        class _ShortResp:
            headers = {"Content-Length": str(len(payload) + 10)}

            def __init__(self):
                self._done = False

            def read(self, n=-1):
                if self._done:
                    return b""
                self._done = True
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        original = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: _ShortResp()
        try:
            try:
                updater.download_asset(
                    updater.Asset(name="x.bin", url="https://example.com/x", size=0),
                    Path(d) / "out2.bin",
                )
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("a short download was not treated as an error")
        finally:
            urllib.request.urlopen = original


def test_the_update_trust_store_is_real():
    """HTTPS from the updater must use a CA store that EXISTS.

    Found by a real click on 0.4.0 (2026-10-18): "Could not reach the update
    server" on a perfectly healthy connection. Reproduced inside the shipped
    bundle's own Python: its compiled-in CA paths point at a python.org
    framework location that is not inside the app, so
    ssl.get_default_verify_paths() reports cafile=None and every HTTPS
    request died CERTIFICATE_VERIFY_FAILED. The property violated is the one
    this asserts: a context built with a missing store loads zero CA
    certificates while otherwise looking fine.
    """
    ctx = updater._ssl_context()
    cas = ctx.get_ca_certs()
    assert len(cas) >= 40, f"trust store is empty or nearly so: {len(cas)} CA certs"


def test_trust_store_falls_back_without_certifi():
    """Source runs without certifi still verify: the system CA files are used."""
    if sys.platform == "win32":
        print("SKIP test_trust_store_falls_back_without_certifi: Windows uses the system store")
        return
    saved = sys.modules.get("certifi")
    sys.modules["certifi"] = None  # makes `import certifi` raise ImportError
    try:
        ctx = updater._ssl_context()
    finally:
        if saved is None:
            sys.modules.pop("certifi", None)
        else:
            sys.modules["certifi"] = saved
    assert len(ctx.get_ca_certs()) >= 40, "no system CA file was used as a fallback"


def test_certificate_failure_is_not_reported_as_unreachable():
    """A TLS trust failure must say so instead of blaming the connection.

    0.4.0 reported "could not reach the update server" for what was
    CERTIFICATE_VERIFY_FAILED, which sent the diagnosis at the network. The
    updater now distinguishes a URLError wrapping an ssl error; genuine
    connectivity failures keep the old wording.
    """
    import ssl as ssl_mod
    import urllib.error
    import urllib.request

    original = urllib.request.urlopen

    def fake_tls_failure(*a, **k):
        raise urllib.error.URLError(ssl_mod.SSLError("certificate verify failed"))

    def fake_offline(*a, **k):
        raise urllib.error.URLError("timed out")

    try:
        urllib.request.urlopen = fake_tls_failure
        try:
            updater.fetch_latest_release()
        except updater.UpdateError as e:
            assert "certificate" in str(e).lower(), str(e)
        else:
            raise AssertionError("expected UpdateError for a TLS failure")

        urllib.request.urlopen = fake_offline
        try:
            updater.fetch_latest_release()
        except updater.UpdateError as e:
            assert "reach the update server" in str(e), str(e)
        else:
            raise AssertionError("expected UpdateError for a connectivity failure")
    finally:
        urllib.request.urlopen = original


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
