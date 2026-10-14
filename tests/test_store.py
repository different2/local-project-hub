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
