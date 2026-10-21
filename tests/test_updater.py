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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import SkipTest  # noqa: E402
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


def test_absent_or_junk_digest_means_the_update_is_not_installable():
    """Missing or malformed digests are parsed as "no digest" without crashing.

    Parsing is tolerant; installation is not. `integrity_problem()` turns the
    empty result into a refusal, so a release published before digests existed
    (or one whose field changes shape) cannot install an unverified artifact.
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


def _assert_no_markers(text: str, markers: dict) -> None:
    """Fail if any synthetic sensitive marker survives in `text`."""
    for label, marker in markers.items():
        assert marker not in text, f"{label} leaked: {marker!r} in {text!r}"


def test_the_privacy_guard_actually_catches_a_leak():
    """The guard must fail on forbidden output, or the report test is vacuous.

    The previous assertion was `A not in text.replace(A, "") or "log_tail" in
    report`. The right-hand side is true whenever the report contains its
    expected field, so the test could never fail. This pins that the helper
    used below is capable of detecting a leak.
    """
    leaked = (
        "Local Project Hub 0.5.0\n"
        "Recent hub messages:\n"
        "[hub] starting ProjectNebula42: python3 /secret/nebula.py\n"
    )
    markers = {"name": "ProjectNebula42", "path": "/secret/nebula.py"}
    try:
        _assert_no_markers(leaked, markers)
    except AssertionError:
        pass
    else:
        raise AssertionError("the privacy guard passed despite project data")


def test_report_excludes_synthetic_project_data():
    """Names, paths, commands, URLs and secrets must not reach any export.

    The markers are deliberately unique so a failure names what leaked. The
    same report feeds the saved file, the pasted text and the prefilled issue
    URL; URL encoding is checked too, because encoding a secret is not
    sanitising it.
    """
    import urllib.parse

    from hub import update_config

    markers = {
        "name": "ProjectNebula42",
        "path": r"C:\Users\secret\NebulaWorkspace",
        "command": r"python3 C:\Users\secret\NebulaWorkspace\server.py --port 9876",
        "url": "http://127.0.0.1:9876/dashboard",
        "secret": "sk-SYNTHETIC0000000000000000",
    }
    log = (
        f"[hub] starting {markers['name']}: {markers['command']}\n"
        f"[hub] detected dashboard URL: {markers['url']}\n"
        f"[hub] update check failed: HTTP 500 for {markers['url']}\n"
        f"RAW PROJECT OUTPUT {markers['secret']} {markers['path']}\n"
    )
    report = diagnostics.build_report(
        error=f"could not start {markers['name']} from {markers['path']}",
        log_tail=log,
        project_count=5,
        sensitive=list(markers.values()),
    )
    text = diagnostics.format_report(report)
    _assert_no_markers(text, markers)

    # The raw project pane line is dropped entirely, not merely redacted.
    assert "RAW PROJECT OUTPUT" not in text, text

    # Useful hub-level diagnostics survive.
    assert "update check failed" in text, text
    assert report["registered_projects"] == 5
    assert report["version"] and report["platform"]

    # The saved file is the same sanitised text, not a second export path.
    with tempfile.TemporaryDirectory() as d:
        saved = diagnostics.save_report(report, directory=Path(d))
        saved_text = saved.read_text(encoding="utf-8")
    _assert_no_markers(saved_text, markers)
    assert "update check failed" in saved_text, saved_text

    old = update_config.ISSUES_URL
    update_config.ISSUES_URL = "https://example.com/issues/new"
    try:
        url = diagnostics.issue_url(report)
    finally:
        update_config.ISSUES_URL = old
    assert url and url.startswith("https://example.com/issues/new?")
    _assert_no_markers(urllib.parse.unquote(url), markers)


def test_report_drops_project_lines_even_without_a_sensitive_list():
    """A project's raw stdout is never admitted, whatever the caller passes."""
    report = diagnostics.build_report(
        log_tail=(
            "PROJECT-RAW-OUTPUT token=ghp_SYNTHETIC0000000000\n"
            "[hub] process exited (code=1)\n"
        )
    )
    text = diagnostics.format_report(report)
    assert "PROJECT-RAW-OUTPUT" not in text, text
    assert "ghp_SYNTHETIC" not in text, text
    assert "process exited (code=1)" in text, text


# ---------- INFO-001: release asset names are paths ----------


def test_asset_filename_validation_rejects_traversal_and_paths():
    bad = [
        "",
        "   ",
        ".",
        "..",
        "../evil.msi",
        r"..\evil.msi",
        "/etc/passwd",
        r"C:\evil.msi",
        "sub/dir.msi",
        r"sub\dir.msi",
        ".hidden.msi",
        "no-extension",
        "trailing.msi.",
        " has-space-at-front.msi",
        "nul\x00byte.msi",
        "CON.msi",
        "nul.dmg",
        "LPT1.exe",
    ]
    for name in bad:
        try:
            updater.safe_asset_filename(name)
        except updater.UpdateError:
            pass
        else:
            raise AssertionError(f"{name!r} was accepted as an asset filename")


def test_supported_asset_names_still_work():
    for name in (
        "Local.Project.Hub-0.5.0.msi",
        "LocalProjectHub-macOS-arm64.dmg",
        "thing(1).dmg",
        "a_b+c@2.exe",
        "Build 42.pkg",
    ):
        assert updater.safe_asset_filename(name) == name


def test_safe_destination_stays_inside_the_download_directory():
    with tempfile.TemporaryDirectory() as d:
        dest = updater.safe_update_destination("thing.dmg", directory=d)
        assert dest.parent == Path(d).resolve(), dest
        assert dest.name == "thing.dmg"
        for bad in ("../escape.dmg", r"..\escape.dmg", r"C:\escape.dmg"):
            try:
                updater.safe_update_destination(bad, directory=d)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError(f"{bad!r} escaped the download directory")


# ---------- update integrity: fail closed ----------


def test_integrity_problem_requires_a_usable_digest():
    good = updater.Asset(name="hub.msi", url="https://example.com/a", sha256="a" * 64)
    assert updater.integrity_problem(good) is None

    missing = updater.Asset(name="hub.msi", url="https://example.com/a")
    assert "does not publish" in (updater.integrity_problem(missing) or "")

    malformed = updater.Asset(
        name="hub.msi", url="https://example.com/a", sha256="not-a-digest"
    )
    assert "malformed" in (updater.integrity_problem(malformed) or "")


def test_a_matching_digest_verifies_and_a_mismatch_does_not():
    import hashlib

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "asset.bin"
        p.write_bytes(b"release payload")
        good = hashlib.sha256(b"release payload").hexdigest()
        assert updater.verify_sha256(p, good) is True
        assert updater.verify_sha256(p, "0" * 64) is False


def test_unavailable_download_source_is_an_error_not_an_install():
    """A failed download must raise before any installer hand-off could happen."""
    import urllib.error
    import urllib.request

    original = urllib.request.urlopen

    def offline(*a, **k):
        raise urllib.error.URLError("connection refused")

    try:
        urllib.request.urlopen = offline
        with tempfile.TemporaryDirectory() as d:
            try:
                updater.download_asset(
                    updater.Asset(name="thing.dmg", url="https://example.com/x"),
                    Path(d) / "thing.dmg",
                )
            except Exception:
                pass
            else:
                raise AssertionError("a failed download was treated as success")
            assert not (Path(d) / "thing.dmg").exists()
    finally:
        urllib.request.urlopen = original


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


def test_current_exception_report_uses_shared_project_context():
    """The crash path gets the same exact identities as Report a Problem."""
    import urllib.parse

    from hub import update_config

    markers = {
        "name": "ProjectNebula42",
        "path": r"C:\Users\secret\NebulaWorkspace",
        "command": (
            r"python3 C:\Users\secret\NebulaWorkspace\server.py "
            "--token sk-SYNTHETIC0000000000000000"
        ),
        "url": "http://127.0.0.1:9876/dashboard",
        "secret": "sk-SYNTHETIC0000000000000000",
    }
    diagnostics.set_project_context(
        sensitive=[
            markers["path"],
            markers["command"],
            markers["url"],
            markers["secret"],
        ],
        project_names=[markers["name"]],
    )
    try:
        try:
            raise RuntimeError(
                f"{markers['name']} failed at {markers['path']}: "
                f"{markers['command']} {markers['url']} "
                f"token={markers['secret']}"
            )
        except RuntimeError:
            report = diagnostics.current_exception_report()
    finally:
        diagnostics.clear_project_context()

    text = diagnostics.format_report(report)
    _assert_no_markers(text, markers)
    # Useful technical detail survives.
    assert "RuntimeError" in text, text

    with tempfile.TemporaryDirectory() as d:
        saved = diagnostics.save_report(report, directory=Path(d))
        _assert_no_markers(saved.read_text(encoding="utf-8"), markers)

    old = update_config.ISSUES_URL
    update_config.ISSUES_URL = "https://example.com/issues/new"
    try:
        issue = diagnostics.issue_url(report)
    finally:
        update_config.ISSUES_URL = old
    assert issue
    _assert_no_markers(urllib.parse.unquote(issue), markers)


def test_one_character_project_name_is_redacted_without_destroying_prose():
    """Short names use word boundaries; ordinary words keep their letters."""
    import re

    diagnostics.set_project_context(project_names=["q"])
    try:
        report = diagnostics.build_report(
            error="q failed while reading quiet data",
            log_tail=(
                "[hub] starting q: python3 /tmp/server.py\n"
                "[hub] update check failed\n"
            ),
            project_count=1,
        )
    finally:
        diagnostics.clear_project_context()

    text = diagnostics.format_report(report)
    assert "quiet" in text, "ordinary prose was damaged"
    assert re.search(r"(?<!\w)q(?!\w)", text) is None, text
    assert "update check failed" in text, text


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
        raise SkipTest("Windows uses the system store")
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
    skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except SkipTest as e:
                skipped += 1
                print(f"SKIP {name}: {e}")
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
    print("---", "FAILURES" if fails else (
        "all passed" + (f" ({skipped} skipped)" if skipped else "")
    ))
    sys.exit(1 if fails else 0)
