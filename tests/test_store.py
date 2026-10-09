"""Registry tests — no GUI needed, so these run anywhere.

Run:  python3 -m pytest tests/ -q      (or: python3 tests/test_store.py)
"""

from __future__ import annotations

import json
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
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
