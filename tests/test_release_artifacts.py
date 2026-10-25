"""Release transport contracts; fixtures are NOT real installer verification."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

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


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:
                failures += 1
                print("FAIL", name, type(exc).__name__, str(exc))
    raise SystemExit(bool(failures))
