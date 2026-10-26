"""Release transport contracts; fixtures are NOT real installer verification."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
import tempfile
from pathlib import Path
from unittest import SkipTest

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    path = ROOT / "tools" / "release_artifacts.py"
    assert path.is_file(), "stable release artifact collector is not implemented"
    spec = importlib.util.spec_from_file_location("release_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample(platform):
    # Only transport/header fixtures. CI must inspect/install the REAL packages.
    if platform == "macos":
        return b"fixture" + b"koly" + b"\0" * 508
    if platform == "windows":
        return bytes.fromhex("d0cf11e0a1b11ae1") + b"fixture"
    return b"!<arch>\n" + b"fixture"


def test_collection_uses_stable_names_and_preserves_source_bytes():
    tool = _tool()
    expected = {
        "macos": "Local.Project.Hub.dmg",
        "windows": "Local.Project.Hub.msi",
        "linux": "Local.Project.Hub.Ubuntu-24.04-amd64.deb",
    }
    assert tool.ASSET_NAMES == expected
    for platform, name in expected.items():
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "dist"
            source.mkdir()
            original = source / ("versioned-0.7.1" + Path(name).suffix)
            original.write_bytes(_sample(platform))
            dest = tool.collect_installer(platform, source, root / "assets")
            assert dest.name == name
            assert dest.read_bytes() == original.read_bytes() == _sample(platform)
            assert original.is_file(), "collection must not move away the build output"


def test_collection_rejects_bad_headers_and_never_clobbers_output():
    tool = _tool()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "dist"
        source.mkdir()
        candidate = source / "installer.deb"
        candidate.write_bytes(b"not an installer")
        try:
            tool.collect_installer("linux", source, root / "out")
        except ValueError as exc:
            assert "header" in str(exc)
        else:
            raise AssertionError("collector accepted a non-installer header")
        candidate.write_bytes(_sample("linux"))
        dest = tool.collect_installer("linux", source, root / "out")
        dest.write_bytes(b"must survive")
        try:
            tool.collect_installer("linux", source, root / "out")
        except FileExistsError:
            pass
        else:
            raise AssertionError("collector overwrote an existing output")
        assert dest.read_bytes() == b"must survive"


def _release_payload():
    tool = _tool()
    tag = "v0.7.1"
    return {
        "tag_name": tag, "draft": True, "prerelease": False,
        "html_url": "https://github.com/different2/local-project-hub/releases/tag/" + tag,
        "assets": [{
            "name": name, "state": "uploaded", "size": 100,
            "digest": "sha256:" + "a" * 64,
            "browser_download_url": "https://github.com/different2/local-project-hub/releases/download/" + tag + "/" + name,
        } for name in tool.ASSET_NAMES.values()],
    }


def test_publication_rejects_partial_unverifiable_or_wrong_release():
    import copy

    tool = _tool()
    assert hasattr(tool, "validate_release"), "complete release publication gate is not implemented"
    payload = _release_payload()
    tool.validate_release(payload, "0.7.1", "different2/local-project-hub", allow_draft=True)
    mutations = [
        lambda p: p["assets"].pop(),
        lambda p: p["assets"].append(copy.deepcopy(p["assets"][0])),
        lambda p: p["assets"][0].update(digest=""),
        lambda p: p["assets"][0].update(digest="sha256:nope"),
        lambda p: p["assets"][0].update(size=0),
        lambda p: p["assets"][0].update(state="new"),
        lambda p: p["assets"][0].update(browser_download_url="https://example.com/installer.dmg"),
        lambda p: p.update(tag_name="v0.7.0"),
        lambda p: p.update(prerelease=True),
    ]
    for mutate in mutations:
        bad = copy.deepcopy(payload)
        mutate(bad)
        try:
            tool.validate_release(bad, "0.7.1", "different2/local-project-hub", allow_draft=True)
        except ValueError:
            pass
        else:
            raise AssertionError("publication gate accepted corrupt/partial release: " + repr(bad))
    try:
        tool.validate_release(payload, "0.7.1", "different2/local-project-hub")
    except ValueError:
        pass
    else:
        raise AssertionError("published-release verification accepted a draft")
    payload["draft"] = False
    tool.validate_release(payload, "0.7.1", "different2/local-project-hub")


def test_draft_preview_urls_do_not_relax_public_release_contract():
    import copy

    tool = _tool()
    payload = _release_payload()
    preview = "untagged-fixture"
    payload["html_url"] = "https://github.com/different2/local-project-hub/releases/tag/" + preview
    for asset in payload["assets"]:
        asset["browser_download_url"] = asset["browser_download_url"].replace("/v0.7.1/", "/" + preview + "/")
    # This is GitHub's actual draft shape, not a published download URL.
    tool.validate_release(payload, "0.7.1", "different2/local-project-hub", allow_draft=True)
    mutations = [
        lambda p: p.update(draft=False),
        lambda p: p.update(html_url="https://example.com/releases/tag/" + preview),
        lambda p: p.update(html_url="https://github.com/another/repo/releases/tag/" + preview),
        lambda p: p.update(html_url="https://github.com/different2/local-project-hub/releases/tag/v0.7.0"),
        lambda p: p.update(html_url=p["html_url"] + "?not-allowed=1"),
        lambda p: p.pop("html_url"),
        lambda p: p["assets"][0].update(browser_download_url=p["assets"][0]["browser_download_url"].replace(preview, "untagged-other")),
        lambda p: p["assets"][0].update(digest=""),
    ]
    for mutate in mutations:
        bad = copy.deepcopy(payload)
        mutate(bad)
        try:
            tool.validate_release(bad, "0.7.1", "different2/local-project-hub", allow_draft=True)
        except ValueError:
            pass
        else:
            raise AssertionError("draft preview exception accepted a wrong release/URL/digest")


def _macos_input_payload():
    """Private API metadata fixture, never a real release/installer receipt."""
    import hashlib

    payload = _release_payload()
    payload["target_commitish"] = "main"  # GitHub need not expand this branch.
    payload["html_url"] = payload["html_url"].replace("v0.7.1", "untagged-fixture")
    payload["assets"] = [payload["assets"][0]]
    payload["assets"][0].update(
        label="source:" + "a" * 40,
        size=len(_sample("macos")),
        digest="sha256:" + hashlib.sha256(_sample("macos")).hexdigest(),
    )
    payload["assets"][0]["browser_download_url"] = payload["assets"][0]["browser_download_url"].replace(
        "v0.7.1", "untagged-fixture"
    )
    return payload


def _rejects(call, message=None):
    try:
        call()
    except ValueError as exc:
        if message is not None:
            assert message.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError("invalid fixture was accepted")


def test_macos_input_is_a_private_source_bound_gate_not_publication():
    import copy

    tool = _tool()
    assert hasattr(tool, "validate_macos_input"), "private macOS input gate is not implemented"
    payload = _macos_input_payload()
    validate = lambda p, sha="a" * 40: tool.validate_macos_input(
        p, "0.7.1", "different2/local-project-hub", sha
    )
    validate(payload)
    resumed = copy.deepcopy(payload)
    other_assets = _release_payload()["assets"][1:]
    for asset in other_assets:
        asset["browser_download_url"] = asset["browser_download_url"].replace("/v0.7.1/", "/untagged-fixture/")
    resumed["assets"].extend(other_assets)
    validate(resumed)  # Existing Windows/Linux uploads do not block resumption.
    tagged = copy.deepcopy(payload)
    tagged["html_url"] = tagged["html_url"].replace("untagged-fixture", "v0.7.1")
    tagged["assets"][0]["browser_download_url"] = tagged["assets"][0]["browser_download_url"].replace(
        "untagged-fixture", "v0.7.1"
    )
    validate(tagged)
    mutations = [
        lambda p: p.update(draft=False),
        lambda p: p.update(draft=1),
        lambda p: p.pop("draft"),
        lambda p: p.update(prerelease=True),
        lambda p: p.update(prerelease=0),
        lambda p: p.update(tag_name="v0.7.0"),
        lambda p: p.update(html_url=p["html_url"].replace("different2/", "other/")),
        lambda p: p.update(html_url=p["html_url"].replace("https://", "http://")),
        lambda p: p.update(html_url=p["html_url"] + "?preview=1"),
        lambda p: p.update(html_url=p["html_url"] + "#preview"),
        lambda p: p.update(html_url=p["html_url"] + ";not-allowed=1"),
        lambda p: p.update(html_url=p["html_url"].replace("untagged-fixture", "v0.7.0")),
        lambda p: p.pop("html_url"),
        lambda p: p.update(assets=[]),
        lambda p: p["assets"].append(copy.deepcopy(p["assets"][0])),
        lambda p: p["assets"][0].update(name="other.dmg"),
        lambda p: p["assets"][0].update(state="new"),
        lambda p: p["assets"][0].update(size=0),
        lambda p: p["assets"][0].update(size=-1),
        lambda p: p["assets"][0].update(size=True),
        lambda p: p["assets"][0].update(size=1.5),
        lambda p: p["assets"][0].update(size="100"),
        lambda p: p["assets"][0].update(digest=""),
        lambda p: p["assets"][0].update(digest="sha256:nope"),
        lambda p: p["assets"][0].update(label="source:" + "b" * 40),
        lambda p: p["assets"][0].update(label="source:" + "a" * 40 + " "),
        lambda p: p["assets"][0].pop("label"),
        lambda p: p["assets"][0].update(browser_download_url="https://example.com/installer.dmg"),
        lambda p: p["assets"][0].update(browser_download_url=p["assets"][0]["browser_download_url"].replace(
            "untagged-fixture", "untagged-other")),
        lambda p: p["assets"][0].update(browser_download_url=p["assets"][0]["browser_download_url"] + "?download=1"),
        lambda p: p["assets"][0].update(browser_download_url=p["assets"][0]["browser_download_url"] + "#download"),
        lambda p: p["assets"][0].update(browser_download_url=p["assets"][0]["browser_download_url"] + ";not-allowed=1"),
    ]
    for mutate in mutations:
        bad = copy.deepcopy(payload)
        mutate(bad)
        _rejects(lambda: validate(bad))
    for sha in ("main", "a" * 39, "A" * 40, "a" * 40 + "\n", "g" * 40):
        _rejects(lambda: validate(payload, sha))
    for version, repo in (("v0.7.1", "different2/local-project-hub"), ("0.7.1", "invalid"),
                          ("0.7.1", "other/repo")):
        _rejects(lambda: tool.validate_macos_input(payload, version, repo, "a" * 40))
    # A single Mac receipt must NEVER pass the full three-installer gate.
    _rejects(lambda: tool.validate_release(payload, "0.7.1", "different2/local-project-hub", allow_draft=True))
    published_preview = copy.deepcopy(resumed)
    published_preview["draft"] = False
    _rejects(lambda: tool.validate_release(published_preview, "0.7.1", "different2/local-project-hub", allow_draft=True))


def test_macos_input_file_checks_real_bytes_and_dmg_footer():
    import copy
    import hashlib

    tool = _tool()
    payload = _macos_input_payload()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        installer = root / "fixture.dmg"
        installer.write_bytes(_sample("macos"))
        validate = lambda p=payload, path=installer: tool.validate_macos_input(
            p, "0.7.1", "different2/local-project-hub", "a" * 40, installer=path
        )
        validate()
        bad_size = copy.deepcopy(payload)
        bad_size["assets"][0]["size"] += 1
        _rejects(lambda: validate(bad_size), "size")
        bad_digest = copy.deepcopy(payload)
        bad_digest["assets"][0]["digest"] = "sha256:" + "0" * 64
        _rejects(lambda: validate(bad_digest), "SHA-256")
        # Same length, valid footer, corrupted leading bytes: hash ALL bytes.
        installer.write_bytes(b"changed" + _sample("macos")[7:])
        _rejects(validate, "SHA-256")
        for bad_bytes in (b"short", b"fixture" + b"nope" + b"\0" * 508):
            installer.write_bytes(bad_bytes)
            matching = copy.deepcopy(payload)
            matching["assets"][0].update(size=len(bad_bytes), digest="sha256:" + hashlib.sha256(bad_bytes).hexdigest())
            _rejects(lambda: validate(matching), "DMG")
        installer.write_bytes(_sample("macos"))
        link = root / "linked.dmg"
        link.symlink_to(installer)
        for path in (root / "missing.dmg", root, link):
            _rejects(lambda: validate(path=path), "regular")


def test_macos_input_cli_routes_private_and_file_validation():
    import json
    import subprocess

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        metadata = root / "fixture-release.json"
        metadata.write_text(json.dumps(_macos_input_payload()), encoding="utf-8")
        installer = root / "fixture.dmg"
        installer.write_bytes(_sample("macos"))
        args = [sys.executable, str(ROOT / "tools" / "release_artifacts.py"),
                "verify-macos-input", "--metadata", str(metadata), "--version", "0.7.1",
                "--repo", "different2/local-project-hub", "--source-commit", "a" * 40]
        metadata_only = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
        assert metadata_only.returncode == 0, metadata_only.stderr
        assert "private" in metadata_only.stdout.lower()
        with_file = subprocess.run([*args, "--file", str(installer)], capture_output=True, text=True, cwd=ROOT)
        assert with_file.returncode == 0, with_file.stderr
        installer.write_bytes(b"bad fixture")
        bad_file = subprocess.run([*args, "--file", str(installer)], capture_output=True, text=True, cwd=ROOT)
        assert bad_file.returncode != 0, "CLI failed to validate the downloaded bytes"
        payload = _macos_input_payload()
        payload["draft"] = False
        metadata.write_text(json.dumps(payload), encoding="utf-8")
        public = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
        assert public.returncode != 0, "CLI accepted public input"


def _macos_bundle_fixture(root):
    """Filesystem-only fixture; NOT a built .app or runtime acceptance."""
    import plistlib

    app = root / "Fixture.app"
    info = app / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True)
    info.write_bytes(plistlib.dumps({
        "CFBundleShortVersionString": "0.7.1", "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "12.0",
    }))
    bundled = app / "Contents" / "Resources" / "app"
    dist_info = bundled / "hub-0.7.1.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: hub\nVersion: 0.7.1\n", encoding="utf-8")
    helper = app / "Contents" / "Resources" / "app_packages" / "PySide6" / "Qt" / "lib" / "QtWebEngineCore.framework" / "Versions" / "A" / "Helpers" / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"fixture, not a real Mach-O executable")
    helper.chmod(0o755)
    return app, info, dist_info, helper


def test_macos_bundle_validates_main_plist_installed_metadata_and_helper():
    import plistlib

    tool = _tool()
    assert hasattr(tool, "validate_macos_bundle"), "real-files macOS bundle gate is not implemented"
    with tempfile.TemporaryDirectory() as temp:
        app, info, dist_info, helper = _macos_bundle_fixture(Path(temp))
        result = tool.validate_macos_bundle(app, "0.7.1")
        assert result["app_path"] == str(app.resolve())
        assert result["version"] == "0.7.1"
        assert result["minimum_system_version"] == "12.0"
        assert result["dist_info"] == str(dist_info.resolve())
        assert result["qtwebengine_process"] == str(helper.resolve())
        original = info.read_bytes()
        for field, value in (("CFBundleShortVersionString", "0.7.0"), ("CFBundleVersion", "bad-build"),
                             ("LSMinimumSystemVersion", "11.0"), ("LSMinimumSystemVersion", 12)):
            data = plistlib.loads(original)
            data[field] = value
            info.write_bytes(plistlib.dumps(data))
            _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), field)
        info.write_bytes(b"malformed plist fixture")
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "Info.plist")
        info.unlink()
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "Info.plist")
        # A valid nested helper plist cannot stand in for the missing MAIN plist.
        (helper.parent.parent / "Info.plist").write_bytes(original)
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "Info.plist")
        info.write_bytes(original)
        metadata = dist_info / "METADATA"
        for content in ("Name: hub\nVersion: 0.7.0\n", "Name: other\nVersion: 0.7.1\n",
                        "Name: hub\n", "Name: hub\nVersion: 0.7.1\nVersion: 0.7.0\n"):
            metadata.write_text(content, encoding="utf-8")
            _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "metadata")
        metadata.write_text("Name: hub\nVersion: 0.7.1\n", encoding="utf-8")
        duplicate = dist_info.with_name("hub-0.7.0.dist-info")
        duplicate.mkdir()
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "dist-info")
        duplicate.rmdir()
        metadata.unlink()
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "metadata")
        metadata.write_text("Name: hub\nVersion: 0.7.1\n", encoding="utf-8")
        if sys.platform != "win32":  # Windows cannot represent the Unix executable-bit negative control.
            helper.chmod(0o644)
            _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "QtWebEngineProcess")
        helper.unlink()
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "QtWebEngineProcess")


def _bundle_source_fixture(root, app):
    """Unimported Python byte fixtures for source/bundle parity controls."""
    source = root / "source-fixture"
    bundled = app / "Contents" / "Resources" / "app"
    for relative, content in {"main.py": b"# fixture entry point\n", "hub/__init__.py": b"# fixture package\n",
                              "hub/nested/feature.py": b"# fixture project ordering\n"}.items():
        for base in (source, bundled):
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return source, bundled


def test_macos_bundle_compares_entrypoint_and_every_recursive_source_byte():
    tool = _tool()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        app, _, _, _ = _macos_bundle_fixture(root)
        source, bundled = _bundle_source_fixture(root, app)
        validate = lambda: tool.validate_macos_bundle(app, "0.7.1", source_root=source)
        result = validate()
        expected = ["hub/__init__.py", "hub/nested/feature.py", "main.py"]
        assert result.get("source_files") == expected, "bundle gate did not compare real source files"
        for relative in expected:
            path = bundled / relative
            original = path.read_bytes()
            path.write_bytes(original + b"# stale fixture\n")
            _rejects(validate, relative)
            path.unlink()
            _rejects(validate, relative)
            path.symlink_to(source / relative)
            _rejects(validate, relative)
            path.unlink()
            path.write_bytes(original)
        missing_source = root / "missing-source-fixture"
        _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1", source_root=missing_source), "source")


def _macos_builder():
    from unittest import mock

    if sys.version_info < (3, 11):
        raise SkipTest("macOS packaging checks require Python 3.11; pure/app checks remain supported")
    path = ROOT / "tools" / "build_macos_release.py"
    assert path.is_file(), "local-only macOS release CLI is not implemented"
    spec = importlib.util.spec_from_file_location("build_macos_release", path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(ROOT / "tools"), *sys.path]):
        spec.loader.exec_module(tool)
    return tool


def _build_config_fixture():
    """Small config fixture with the REAL pinned macOS requirements."""
    import tomllib

    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _installed_versions_fixture():
    """Mock installed metadata, not a claim about the build environment."""
    return {"briefcase": "0.4.6", "PySide6-Essentials": "6.7.3", "PySide6-Addons": "6.7.3",
            "PySide6": "6.7.3", "shiboken6": "6.7.3", "certifi": "2026.10.18",
            "pyobjc-framework-Cocoa": "12.2.2"}


def test_local_macos_environment_requires_existing_pinned_buildenv():
    from unittest import mock

    tool = _macos_builder()
    assert hasattr(tool, "check_environment"), "local build environment gate is not implemented"
    config = _build_config_fixture()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / ".buildenv").mkdir()
        versions = _installed_versions_fixture()
        with mock.patch.object(tool.sys, "platform", "darwin"), \
                mock.patch.object(tool.sys, "version_info", (3, 11, 10)), \
                mock.patch.object(tool.sys, "prefix", str(root / ".buildenv")), \
                mock.patch.object(tool.metadata, "version", side_effect=lambda name: versions[name]) as lookup:
            tool.check_environment(root, config)
            assert set(versions).issubset({call.args[0] for call in lookup.call_args_list})
            for platform in ("linux", "win32"):
                with mock.patch.object(tool.sys, "platform", platform):
                    _rejects(lambda: tool.check_environment(root, config), "Darwin")
            for python in ((3, 10, 14), (3, 12, 0)):
                with mock.patch.object(tool.sys, "version_info", python):
                    _rejects(lambda: tool.check_environment(root, config), "3.11")
            with mock.patch.object(tool.sys, "prefix", str(root / "other-env")):
                _rejects(lambda: tool.check_environment(root, config), ".buildenv")
            for package in versions:
                original = versions[package]
                versions[package] = "0.0.0"
                _rejects(lambda: tool.check_environment(root, config), package)
                versions[package] = original
            with mock.patch.object(tool.metadata, "version", side_effect=tool.metadata.PackageNotFoundError("fixture")):
                _rejects(lambda: tool.check_environment(root, config), "installed")


def _local_build_fixture(root):
    """Arrange a Briefcase-shaped tree, NOT actual build/package outputs."""
    import shutil

    # The fixture stays at 0.7.1 even when the real release version is bumped.
    config = re.sub(r'(?m)^version = "[^"]+"$', 'version = "0.7.1"',
                    (ROOT / "pyproject.toml").read_text(encoding="utf-8"), count=1)
    (root / "pyproject.toml").write_text(config, encoding="utf-8")
    app, _, _, _ = _macos_bundle_fixture(root)
    source, _ = _bundle_source_fixture(root, app)
    for path in source.rglob("*.py"):
        dest = root / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    arranged = root / "build" / "hub" / "macos" / "app" / "Local Project Hub.app"
    arranged.parent.mkdir(parents=True)
    app.rename(arranged)
    return arranged


def test_local_macos_build_checks_bundle_before_packaging_and_verifies_collected_dmg():
    import subprocess
    from unittest import mock

    tool = _macos_builder()
    assert hasattr(tool, "build_release"), "bounded local release pipeline is not implemented"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve()
        app = _local_build_fixture(root)
        output = root / "custom-assets"
        events = []
        def command(argv, *, capture_output=False):
            events.append(tuple(argv))
            stdout = str(root) + "\n" if argv[:2] == ["git", "rev-parse"] else ""
            if argv[1:4] == ["-m", "briefcase", "package"]:
                (root / "dist").mkdir()
                (root / "dist" / "fixture-0.7.1.dmg").write_bytes(_sample("macos"))
            return subprocess.CompletedProcess(argv, 0, stdout=stdout)
        validate = tool.validate_macos_bundle
        def inspect(path, version, source_root=None):
            events.append(("validate-bundle", path, version, source_root))
            return validate(path, version, source_root=source_root)
        with mock.patch.object(tool, "REPO_ROOT", root), \
                mock.patch.object(tool.Path, "cwd", return_value=root), \
                mock.patch.object(tool, "check_environment") as environment, \
                mock.patch.object(tool, "_run", side_effect=command), \
                mock.patch.object(tool, "validate_macos_bundle", side_effect=inspect), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            dest = tool.build_release("v0.7.1", output)
        environment.assert_called_once()
        assert dest == output / tool.ASSET_NAMES["macos"]
        assert dest.read_bytes() == _sample("macos")
        build = (sys.executable, "-m", "briefcase", "build", "macOS", "--no-input")
        package = (sys.executable, "-m", "briefcase", "package", "macOS", "-p", "dmg", "--adhoc-sign", "--no-input")
        inspection = ("validate-bundle", app, "0.7.1", root)
        verify = ("hdiutil", "verify", str(dest))
        assert events.index(build) < events.index(inspection) < events.index(package) < events.index(verify), events
        assert ("git", "status", "--porcelain", "--untracked-files=no") in events
        assert not any("install" in arg or "upgrade" in arg for event in events for arg in event if isinstance(arg, str))


def test_local_macos_build_refuses_dirty_source_wrong_root_or_tag_and_bad_bundle():
    import subprocess
    from unittest import mock

    tool = _macos_builder()
    assert hasattr(tool, "build_release"), "bounded local release pipeline is not implemented"
    for case in ("dirty-worktree", "dirty-index", "wrong-git-root", "wrong-cwd", "wrong-tag", "bad-bundle"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = _local_build_fixture(root)
            if case == "bad-bundle":
                (app / "Contents" / "Resources" / "app" / "hub" / "nested" / "feature.py").write_bytes(b"# stale fixture\n")
            commands = []
            def command(argv, *, capture_output=False):
                commands.append(argv)
                stdout = ""
                if argv[:2] == ["git", "rev-parse"]:
                    stdout = str(root / "other" if case == "wrong-git-root" else root) + "\n"
                elif argv[:2] == ["git", "status"]:
                    stdout = {"dirty-worktree": " M hub/order.py\n", "dirty-index": "M  hub/order.py\n"}.get(case, "")
                return subprocess.CompletedProcess(argv, 0, stdout=stdout)
            with mock.patch.object(tool, "REPO_ROOT", root), \
                    mock.patch.object(tool.Path, "cwd", return_value=root / "other" if case == "wrong-cwd" else root), \
                    mock.patch.object(tool, "check_environment"), \
                    mock.patch.object(tool, "_run", side_effect=command), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                expected = {"dirty-worktree": "dirty", "dirty-index": "dirty", "wrong-git-root": "repository root",
                            "wrong-cwd": "repository root", "wrong-tag": "tag", "bad-bundle": "hub/nested/feature.py"}[case]
                _rejects(lambda: tool.build_release("v9.9.9" if case == "wrong-tag" else "v0.7.1", root / "assets"), expected)
            assert not any(argv[1:4] == ["-m", "briefcase", "package"] for argv in commands), case
            if case != "bad-bundle":
                assert not any(argv[1:4] == ["-m", "briefcase", "build"] for argv in commands), case
            assert not (root / "assets").exists(), case


def test_local_macos_cli_supports_output_and_preserves_external_exit_codes():
    import subprocess
    from unittest import mock

    tool = _macos_builder()
    assert hasattr(tool, "main"), "local-only macOS CLI entry point is not implemented"
    output = io.StringIO()
    errors = io.StringIO()
    with mock.patch.object(tool, "build_release", return_value=Path("fixture-output.dmg")) as build, \
            contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        assert tool.main(["v0.7.1", "--output", "custom-output"]) == 0
        build.assert_called_once_with("v0.7.1", Path("custom-output"))
    assert "fixture-output.dmg" in output.getvalue()
    for rc in (7, 23):
        with mock.patch.object(tool, "build_release", side_effect=subprocess.CalledProcessError(rc, ["hdiutil", "verify", "fixture.dmg"])), \
                contextlib.redirect_stderr(errors):
            assert tool.main(["v0.7.1"]) == rc, "CLI swallowed the actual hdiutil exit"
    with mock.patch.object(tool, "build_release", side_effect=ValueError("invalid fixture bundle")), \
            contextlib.redirect_stderr(errors):
        assert tool.main(["v0.7.1"]) == 1
    help_result = subprocess.run([sys.executable, str(ROOT / "tools" / "build_macos_release.py"), "--help"],
                                 capture_output=True, text=True, cwd=ROOT)
    assert help_result.returncode == 0, help_result.stderr
    assert "--output" in help_result.stdout
    failure = subprocess.CalledProcessError(19, ["fixture-command"])
    with mock.patch.object(tool.subprocess, "run", side_effect=failure) as run:
        try:
            tool._run(["fixture-command"])
        except subprocess.CalledProcessError as exc:
            assert exc is failure
        else:
            raise AssertionError("real command failures must propagate")
        run.assert_called_once_with(["fixture-command"], cwd=tool.REPO_ROOT, check=True, text=True, capture_output=False)
    # Exercise the real command seam only with a harmless Python child, never Briefcase/hdiutil.
    try:
        tool._run([sys.executable, "-c", "raise SystemExit(23)"])
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 23
    else:
        raise AssertionError("real child exit 23 was concealed")


def test_collection_never_follows_a_dangling_output_symlink():
    tool = _tool()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "dist"
        source.mkdir()
        (source / "fixture.dmg").write_bytes(_sample("macos"))
        output = root / "assets"
        output.mkdir()
        target = root / "must-not-be-created.dmg"
        dest = output / tool.ASSET_NAMES["macos"]
        dest.symlink_to(target)
        try:
            tool.collect_installer("macos", source, output)
        except FileExistsError:
            pass
        else:
            raise AssertionError("collector followed a dangling destination symlink")
        assert dest.is_symlink()
        assert not target.exists()


def test_local_macos_build_refuses_stale_dmg_or_existing_output_before_build():
    import subprocess
    from unittest import mock

    tool = _macos_builder()
    for case in ("stale-dmg", "existing-output", "dangling-output"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            _local_build_fixture(root)
            output = root / "assets"
            dest = output / tool.ASSET_NAMES["macos"]
            if case == "stale-dmg":
                (root / "dist").mkdir()
                (root / "dist" / "fixture-old.dmg").write_bytes(_sample("macos"))
            else:
                output.mkdir()
                if case == "existing-output":
                    dest.write_bytes(b"existing fixture must survive")
                else:
                    dest.symlink_to(root / "missing-fixture.dmg")
            commands = []
            def command(argv, *, capture_output=False):
                commands.append(argv)
                assert argv[0] == "git", "a build ran despite stale or occupied release paths"
                return subprocess.CompletedProcess(argv, 0, stdout=str(root) + "\n" if argv[1] == "rev-parse" else "")
            with mock.patch.object(tool, "REPO_ROOT", root), \
                    mock.patch.object(tool.Path, "cwd", return_value=root), \
                    mock.patch.object(tool, "check_environment"), \
                    mock.patch.object(tool, "_run", side_effect=command), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    tool.build_release("v0.7.1", output)
                except (ValueError, FileExistsError):
                    pass
                else:
                    raise AssertionError("local builder accepted stale or occupied release paths")
            if case == "existing-output":
                assert dest.read_bytes() == b"existing fixture must survive"
            elif case == "dangling-output":
                assert dest.is_symlink() and not dest.exists()


def test_macos_bundle_rejects_external_metadata_and_symlinked_source_directories():
    tool = _tool()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        app, info, dist_info, _ = _macos_bundle_fixture(root)
        source, bundled = _bundle_source_fixture(root, app)
        validate = lambda: tool.validate_macos_bundle(app, "0.7.1", source_root=source)
        for path in (info, dist_info / "METADATA"):
            original = path.read_bytes()
            outside = root / ("external-" + path.name)
            outside.write_bytes(original)
            path.unlink()
            path.symlink_to(outside)
            _rejects(validate, path.name)
            path.unlink()
            path.write_bytes(original)
        nested = bundled / "hub" / "nested"
        original = (nested / "feature.py").read_bytes()
        (nested / "feature.py").unlink()
        nested.rmdir()
        nested.symlink_to(source / "hub" / "nested", target_is_directory=True)
        _rejects(validate, "hub/nested/feature.py")
        nested.unlink()
        nested.mkdir()
        (nested / "feature.py").write_bytes(original)
        # A symlinked SOURCE subtree must not disappear from rglob's comparison.
        source_nested = source / "hub" / "nested"
        moved = root / "external-source-fixture"
        source_nested.rename(moved)
        source_nested.symlink_to(moved, target_is_directory=True)
        _rejects(validate, "source")


def test_full_verify_cli_still_requires_all_three_installers_and_public_tag_urls():
    import json
    import subprocess

    with tempfile.TemporaryDirectory() as temp:
        metadata = Path(temp) / "fixture-release.json"
        args = [sys.executable, str(ROOT / "tools" / "release_artifacts.py"), "verify",
                "--metadata", str(metadata), "--version", "0.7.1", "--repo", "different2/local-project-hub"]
        payload = _release_payload()
        payload["draft"] = False
        metadata.write_text(json.dumps(payload), encoding="utf-8")
        complete = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
        assert complete.returncode == 0, complete.stderr
        payload["assets"].pop()
        metadata.write_text(json.dumps(payload), encoding="utf-8")
        partial = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
        assert partial.returncode != 0, "full verify CLI accepted a partial release"
        payload = _release_payload()
        payload["draft"] = False
        for asset in payload["assets"]:
            asset["browser_download_url"] = asset["browser_download_url"].replace("/v0.7.1/", "/untagged-fixture/")
        metadata.write_text(json.dumps(payload), encoding="utf-8")
        public_preview = subprocess.run([*args, "--allow-draft"], capture_output=True, text=True, cwd=ROOT)
        assert public_preview.returncode != 0, "--allow-draft relaxed the PUBLIC URL contract"


def test_strict_regression_observer_rejects_crashes_after_pass():
    path = ROOT / "tools" / "run_regression_strict.py"
    assert path.is_file(), "raw-child regression exit audit is not implemented"
    spec = importlib.util.spec_from_file_location("strict_regression", path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.child_is_clean(0, "PASS test_real\n")
    assert tool.child_is_clean(0, "SKIP test_platform\n")
    assert not tool.child_is_clean(-11, "PASS test_real\n"), "PASS must not conceal a shutdown segfault"
    assert not tool.child_is_clean(23, "PASS test_real\n")
    assert not tool.child_is_clean(0, "FAIL test_real: nope\n")
    assert not tool.child_is_clean(0, "ERROR test_real: nope\n")
    assert not tool.child_is_clean(0, ""), "zero verdicts must not pass"


def test_macos_bundle_separates_release_version_from_the_real_build_counter():
    import plistlib

    tool = _tool()
    with tempfile.TemporaryDirectory() as temp:
        app, info, _, _ = _macos_bundle_fixture(Path(temp))
        fields = plistlib.loads(info.read_bytes())
        # Actual Briefcase 0.4.6 DMG metadata from v0.7.1 has short version
        # 0.7.1 but build counter "1"; these are not the same field/value.
        fields["CFBundleVersion"] = "1"
        info.write_bytes(plistlib.dumps(fields))
        result = tool.validate_macos_bundle(app, "0.7.1")
        assert result["version"] == "0.7.1"
        assert result["bundle_build_version"] == "1"
        for value in (None, False, "", "not-a-build"):
            fields["CFBundleVersion"] = value
            if value is None:
                fields.pop("CFBundleVersion")
            info.write_bytes(plistlib.dumps(fields))
            _rejects(lambda: tool.validate_macos_bundle(app, "0.7.1"), "CFBundleVersion")


def test_packaging_only_checks_skip_explicitly_before_python_311():
    from unittest import SkipTest, mock

    with mock.patch.object(sys, "version_info", (3, 9, 6)):
        try:
            _macos_builder()
        except SkipTest as exc:
            assert "Python 3.11" in str(exc)
        else:
            raise AssertionError("Python-3.11-only packaging checks did not explicitly skip on Python 3.9")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except SkipTest as exc:
                print("SKIP", name, str(exc))
            except Exception as exc:
                failures += 1
                print("FAIL", name, type(exc).__name__, str(exc))
    raise SystemExit(bool(failures))
