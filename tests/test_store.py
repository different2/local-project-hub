"""Registry tests — no GUI needed, so these run anywhere.

Run:  python3 -m pytest tests/ -q      (or: python3 tests/test_store.py)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import store as sm  # noqa: E402


def _store(tmp: Path) -> sm.Store:
    return sm.Store(tmp / "registry.json")


def _rec(**kw) -> dict:
    base = dict(
        name="Sphere",
        command="python3 server.py 8471",
        url="http://127.0.0.1:8471/",
        working_dir=str(Path(__file__).resolve().parent.parent),
    )
    base.update(kw)
    return base


def make_rec(**kw):
    """Validate a fresh record the way the dialog would."""
    return sm.validate(_rec(**kw))


def test_add_get_remove():
    with tempfile.TemporaryDirectory() as d:
        s = _store(Path(d))
        rec = s.add(make_rec())
        assert s.get(rec["id"])["name"] == "Sphere"
        s.remove(rec["id"])
        assert s.get(rec["id"]) is None


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        s = _store(Path(d))
        s.add(make_rec(name="A"))
        s.add(make_rec(name="B", icon="🧪", autostart=True, env={"X": "1"}))
        s2 = sm.Store(Path(d) / "registry.json")
        names = [r["name"] for r in s2.ordered()]
        assert names == ["A", "B"]  # alphabetical order
        assert s2.get([r for r in s2.projects if s2.projects[r]["name"] == "B"][0])["env"] == {"X": "1"}


def test_update_keeps_id():
    with tempfile.TemporaryDirectory() as d:
        s = _store(Path(d))
        rec = s.add(make_rec())
        rec["name"] = "Renamed"
        s.update(rec)
        assert list(s.projects) == [rec["id"]]
        assert s.get(rec["id"])["name"] == "Renamed"


def test_validation_rejects_bad_url():
    try:
        sm.validate(_rec(url="localhost:8471"))
    except sm.RegistryError as e:
        assert "http" in str(e)
    else:
        raise AssertionError("bad url accepted")


def test_validation_rejects_missing_command():
    try:
        sm.validate(_rec(command="  "))
    except sm.RegistryError:
        pass
    else:
        raise AssertionError("empty command accepted")


def test_validation_rejects_missing_dir():
    try:
        sm.validate(_rec(working_dir="/definitely/not/here"))
    except sm.RegistryError:
        pass
    else:
        raise AssertionError("nonexistent working_dir accepted")


def test_env_coerced_to_strings():
    r = sm.validate(_rec(env={"N": 5}))
    assert r["env"] == {"N": "5"}


def test_export_import_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        s = _store(Path(d))
        s.add(make_rec(name="One"))
        text = s.export_json()
        s2 = _store(Path(d) / "other.json")
        n = s2.import_json(text)
        assert n == 1
        assert [r["name"] for r in s2.ordered()] == ["One"]


def test_empty_working_dir_allowed():
    r = sm.validate(_rec(working_dir=""))
    assert r["working_dir"] == ""


def test_save_is_atomic_no_tmp_left_behind():
    with tempfile.TemporaryDirectory() as d:
        s = sm.Store(Path(d) / "registry.json")
        s.add(make_rec())
        p = Path(d) / "registry.json"
        assert not p.with_suffix(".json.tmp").exists()
        json.loads(p.read_text())  # valid json


def test_env_override_wins():
    """LOCAL_PROJECT_HUB_HOME must override the platform default."""
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("LOCAL_PROJECT_HUB_HOME")
        os.environ["LOCAL_PROJECT_HUB_HOME"] = d
        try:
            assert sm.default_config_dir() == Path(d)
            assert sm.default_registry_path() == Path(d) / "registry.json"
        finally:
            if old is None:
                os.environ.pop("LOCAL_PROJECT_HUB_HOME", None)
            else:
                os.environ["LOCAL_PROJECT_HUB_HOME"] = old


def test_config_dir_is_per_platform():
    """The platform default must follow the OS convention (release spec §3/§7)."""
    old = os.environ.pop("LOCAL_PROJECT_HUB_HOME", None)
    try:
        d = sm.default_config_dir()
        if sys.platform == "darwin":
            assert "Library/Application Support" in str(d), d
        elif sys.platform.startswith("win"):
            assert "LocalProjectHub" in str(d), d
            # must NOT be a system-wide path an installer could replace
            assert "Program Files" not in str(d), d
        else:
            assert "local-project-hub" in str(d), d
        assert d.is_absolute(), d
    finally:
        if old is not None:
            os.environ["LOCAL_PROJECT_HUB_HOME"] = old


# ---------- BUG-001: invalid registry structure ----------


def test_load_rejects_non_object_json_with_a_registry_error():
    """Parsable JSON with a non-object top level must not crash as AttributeError.

    A registry edited by hand (or truncated by another tool) can contain `[]`,
    `"s"`, `42` or `null`. The loader used `.get()` on it and raised a bare
    AttributeError, which escaped main.py's RegistryError handler and killed the
    app at startup instead of explaining the problem.
    """
    for payload in ("[]", '"s"', "42", "null"):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "registry.json"
            p.write_text(payload, encoding="utf-8")
            try:
                sm.Store(p)
            except sm.RegistryError:
                pass
            except AttributeError as e:
                raise AssertionError(
                    f"{payload!r} escaped as AttributeError: {e}"
                ) from e
            else:
                raise AssertionError(f"{payload!r} was accepted as a registry")
            # An invalid structure must never be silently reset or rewritten.
            assert p.read_text(encoding="utf-8") == payload


def test_load_rejects_a_non_list_projects_value():
    for payload in ('{"projects": {}}', '{"projects": "nope"}'):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "registry.json"
            p.write_text(payload, encoding="utf-8")
            try:
                sm.Store(p)
            except sm.RegistryError:
                pass
            else:
                raise AssertionError(f"{payload!r} was accepted as a registry")


def test_load_accepts_a_valid_registry_and_a_legacy_v1_file():
    """The stricter structure check must not disturb supported formats."""
    with tempfile.TemporaryDirectory() as d:
        valid = Path(d) / "valid.json"
        valid.write_text(
            json.dumps(
                {
                    "version": sm.SCHEMA_VERSION,
                    "projects": [
                        {
                            "id": "valid001",
                            "name": "Valid",
                            "command": "python3 x.py",
                            "working_dir": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        loaded = sm.Store(valid)
        assert loaded.get("valid001")["name"] == "Valid"

        legacy = Path(d) / "legacy.json"
        legacy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "projects": [
                        {
                            "id": "legacy01",
                            "name": "Legacy",
                            "command": "python3 x.py",
                            "working_dir": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        migrated = sm.Store(legacy)
        rec = migrated.get("legacy01")
        assert rec["name"] == "Legacy"
        assert rec["detected"]["type"] == "unknown"
        assert rec["detected"]["evidence"]


# ---------- BUG-002: bare-array import ----------


def test_import_accepts_a_bare_json_array():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        s = sm.Store(p)
        n = s.import_json(json.dumps([_rec(name="Bare")]))
        assert n == 1
        assert [r["name"] for r in s.ordered()] == ["Bare"]
        # and it was actually persisted, not only staged in memory
        assert sm.Store(p).ordered()[0]["name"] == "Bare"


def test_import_accepts_an_object_export_and_an_empty_projects_list():
    with tempfile.TemporaryDirectory() as d:
        s = sm.Store(Path(d) / "registry.json")
        assert s.import_json(json.dumps({"version": 2, "projects": [_rec(name="Obj")]})) == 1
        assert [r["name"] for r in s.ordered()] == ["Obj"]
        assert s.import_json(json.dumps({"version": 2, "projects": []})) == 0


def test_import_rejects_unrelated_json_shapes():
    """A stray JSON document must not read as a successful empty import."""
    bad_payloads = (
        "42",
        '"s"',
        "null",
        "{}",  # object with no projects list
        '{"projects": {}}',  # projects is not a list
        '{"projects": "nope"}',
    )
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        s = sm.Store(p)
        for payload in bad_payloads:
            try:
                s.import_json(payload)
            except sm.RegistryError:
                pass
            else:
                raise AssertionError(f"{payload!r} was accepted as an import")
            assert s.projects == {}, f"{payload!r} modified the registry"
        assert not p.exists(), "a rejected import wrote a registry file"


# ---------- BUG-003: import atomicity ----------


def test_import_invalid_later_record_leaves_existing_registry_unchanged():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        s = sm.Store(p)
        existing = s.add(make_rec(name="Existing"))
        before = p.read_bytes()

        try:
            s.import_json(
                json.dumps({"projects": [_rec(name="First"), _rec(name="")]})
            )
        except sm.RegistryError:
            pass
        else:
            raise AssertionError("a batch with an invalid record was accepted")

        assert list(s.projects) == [existing["id"]], "memory kept the earlier record"
        assert p.read_bytes() == before, "disk changed despite a rejected batch"


def test_import_invalid_record_on_empty_registry_leaves_nothing_behind():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        s = sm.Store(p)
        try:
            s.import_json(
                json.dumps([_rec(name="First"), {"name": "", "command": "x"}])
            )
        except sm.RegistryError:
            pass
        else:
            raise AssertionError("a batch with an invalid record was accepted")

        assert s.projects == {}, "memory kept a partially imported batch"
        assert not p.exists(), "a rejected batch created a registry file"


def test_import_duplicate_ids_are_staged_then_last_wins():
    with tempfile.TemporaryDirectory() as d:
        s = sm.Store(Path(d) / "registry.json")
        first = dict(_rec(name="First"), id="dupe0001")
        second = dict(_rec(name="Second"), id="dupe0001")
        n = s.import_json(json.dumps([first, second]))
        assert n == 2
        assert s.get("dupe0001")["name"] == "Second"


def test_import_updates_an_existing_record_by_id():
    """Import is a merge, so an id already present is updated (not duplicated)."""
    with tempfile.TemporaryDirectory() as d:
        s = sm.Store(Path(d) / "registry.json")
        rec = s.add(make_rec(name="Before"))
        rec["name"] = "After"
        assert s.import_json(json.dumps([rec])) == 1
        assert s.get(rec["id"])["name"] == "After"
        assert len(s.projects) == 1


def test_failed_atomic_replace_cleans_tmp_and_restores_memory():
    """A failed replace keeps the old file, memory, and no temp artifact."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        s = sm.Store(p)
        existing = s.add(make_rec(name="Existing"))
        before = p.read_bytes()

        real_replace = sm.os.replace

        def failing_replace(src, dst):
            raise OSError("registry is locked")

        sm.os.replace = failing_replace
        try:
            try:
                s.add(make_rec(name="New"))
            except sm.RegistryError:
                pass
            else:
                raise AssertionError("a failed replace was reported as success")
        finally:
            sm.os.replace = real_replace

        assert list(s.projects) == [existing["id"]], "memory was not rolled back"
        assert p.read_bytes() == before, "the original registry changed"
        leftovers = list(p.parent.glob(p.name + ".*.tmp"))
        assert not leftovers, f"temporary file leaked: {leftovers}"


def test_import_rolls_memory_back_when_save_fails():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "registry.json"
        s = sm.Store(p)
        existing = s.add(make_rec(name="Existing"))
        before = p.read_bytes()

        original_save = s.save

        def failing_save():
            raise OSError("disk full")

        s.save = failing_save
        try:
            try:
                s.import_json(json.dumps([_rec(name="New")]))
            except sm.RegistryError as e:
                assert "save" in str(e).lower(), str(e)
            else:
                raise AssertionError("a save failure was reported as success")
        finally:
            s.save = original_save

        assert list(s.projects) == [existing["id"]], "memory kept the unsaved batch"
        assert p.read_bytes() == before, "disk changed after a failed save"


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
