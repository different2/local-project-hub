"""Project registry: persistent store of project definitions.

A project record (dict) looks like:

    {
        "id": "a1b2c3d4",                    # 8-char stable id
        "name": "Sphere Project",             # display name in the sidebar
        "description": "optional",
        "icon": "🌐",                         # any text, shown next to name
        "working_dir": "/abs/path",           # must exist at load time
        "interpreter": "",                    # "" = system python3
        "command": "python3 server.py 8471",  # argv-style string, shell-free
        "env": {"KEY": "VALUE"},              # extra env vars
        "url": "http://127.0.0.1:8471/",      # dashboard URL
        "autostart": false,                   # start when the hub opens
    }

Storage: one JSON file, written atomically (tmp + rename) so a crash mid-write
cannot corrupt the registry.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

SCHEMA_VERSION = 2


def migrate_to_v2(rec: dict) -> dict:
    """Add the v2 `detected` block to a v1 record, with safe defaults.

    Existing registries have no `detected` key at all. Rather than re-running
    detection on load (which would re-read files and could change a user's
    saved choices), an absent block becomes an explicit "unknown" so the app
    can tell "never inspected" from "inspected and inconclusive" (spec §7).
    """
    rec = dict(rec)
    if not isinstance(rec.get("detected"), dict):
        rec["detected"] = {
            "type": "unknown",
            "confidence": 0.0,
            "framework": "",
            "port": None,
            "browser": "",
            "display": "runs in the background (type unknown)",
            "evidence": ["migrated from a registry without detection data"],
        }
    return rec


def default_config_dir() -> Path:
    """Per-user application state directory, resolved per platform.

    Kept in one place (spec §3/§7) so platform differences never leak into
    the rest of the app. LOCAL_PROJECT_HUB_HOME still overrides everything,
    which is how the tests and `run.sh` stay isolated.
    """
    override = os.environ.get("LOCAL_PROJECT_HUB_HOME")
    if override:
        return Path(override)

    system = sys.platform
    if system == "darwin":
        # macOS: the conventional per-user Application Support location.
        return Path.home() / "Library" / "Application Support" / "LocalProjectHub"
    if system.startswith("win"):
        # Windows: LOCALAPPDATA is per-user and never touched by installers
        # (Program Files is), which is what spec §7 requires.
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "LocalProjectHub"
    # Linux and anything else: XDG, falling back to a dotfile in $HOME.
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "local-project-hub"


def default_registry_path() -> Path:
    return default_config_dir() / "registry.json"


def new_id() -> str:
    return uuid.uuid4().hex[:8]


class RegistryError(Exception):
    """Raised for malformed registry data or invalid project records."""


class Store:
    """Load/save the registry and hand out validated project records."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_registry_path()
        self.projects: dict[str, dict] = {}
        self.load()

    # ---------- persistence ----------

    def load(self) -> None:
        self.projects = {}
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise RegistryError(f"could not read registry {self.path}: {e}") from e
        version = raw.get("version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            if version == 1 and SCHEMA_VERSION == 2:
                # v1 -> v2 is additive and safe: fill the new `detected` block
                # with honest "unknown" defaults rather than refusing to load a
                # registry the user has already populated (spec §7).
                pass
            else:
                raise RegistryError(
                    f"registry version {version} != {SCHEMA_VERSION}; "
                    "move it aside and re-register your projects"
                )
        for rec in raw.get("projects", []):
            # Migrate BEFORE validate: validate() normalises the `detected`
            # block, and running it on a v1 record would replace the migration's
            # honest "unknown" with a blank one.
            if version == 1:
                rec = migrate_to_v2(rec)
            rec = validate(rec)
            self.projects[rec["id"]] = rec

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": SCHEMA_VERSION, "projects": self.ordered()}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on POSIX

    # ---------- queries ----------

    def ordered(self) -> list[dict]:
        """Records sorted by name, for stable sidebar order."""
        return [self.projects[k] for k in sorted(self.projects, key=lambda i: self.projects[i]["name"].lower())]

    def get(self, project_id: str) -> dict | None:
        return self.projects.get(project_id)

    # ---------- mutations ----------

    def add(self, rec: dict) -> dict:
        rec = validate(rec)
        if "id" not in rec or not rec["id"]:
            rec["id"] = new_id()
        if rec["id"] in self.projects:
            raise RegistryError(f"project id {rec['id']} already exists")
        self.projects[rec["id"]] = rec
        self.save()
        return rec

    def update(self, rec: dict) -> dict:
        rec = validate(rec)
        pid = rec.get("id")
        if pid not in self.projects:
            raise RegistryError(f"no project with id {pid}")
        self.projects[pid] = rec
        self.save()
        return rec

    def remove(self, project_id: str) -> None:
        if project_id not in self.projects:
            raise RegistryError(f"no project with id {project_id}")
        del self.projects[project_id]
        self.save()

    def export_json(self) -> str:
        return json.dumps({"version": SCHEMA_VERSION, "projects": self.ordered()}, indent=2)

    def import_json(self, text: str) -> int:
        """Merge projects from an export. Returns how many were added/updated."""
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise RegistryError(f"not valid JSON: {e}") from e
        recs = raw.get("projects", raw if isinstance(raw, list) else [])
        n = 0
        for rec in recs:
            rec = validate(rec)
            rec["id"] = rec.get("id") or new_id()
            self.projects[rec["id"]] = rec
            n += 1
        self.save()
        return n


_STR_FIELDS = (
    "name",
    "description",
    "icon",
    "working_dir",
    "interpreter",
    "command",
    "args",
    "url",
)
_BOOL_FIELDS = ("autostart",)


def validate(rec: dict) -> dict:
    """Coerce and check a project record. Raises RegistryError on bad input."""
    if not isinstance(rec, dict):
        raise RegistryError("project record must be an object")
    out: dict = {"id": str(rec.get("id") or "")}
    for f in _STR_FIELDS:
        out[f] = str(rec.get(f) or "")
    for f in _BOOL_FIELDS:
        out[f] = bool(rec.get(f))
    env = rec.get("env") or {}
    if not isinstance(env, dict):
        raise RegistryError("env must be an object of KEY: VALUE")
    out["env"] = {str(k): str(v) for k, v in env.items()}

    # Detection results are stored BESIDE the record, never merged into it, so
    # the user's original command stays verbatim (spec §6: "do not overwrite
    # the original command with automatically generated flags").
    #
    # Detection is (re)run HERE rather than only in the dialog, so a record
    # added by any path — the dialog, import_json, the API — gets classified
    # identically. A record that already carries a `detected` block is trusted
    # unless it has no evidence at all, so a saved result is not recomputed on
    # every load (spec §6: "reuse the saved configuration").
    from .detect_type import detect as _detect, Detection

    existing = rec.get("detected")
    if isinstance(existing, dict) and existing.get("evidence"):
        det = Detection.from_dict(existing)
    else:
        try:
            det = _detect(rec)
        except Exception:
            # Detection is advisory and must never block saving a project.
            det = Detection()
    # A user override wins over anything detected; it is explicit intent.
    override = rec.get("type_override")
    if isinstance(override, str) and override:
        det.type = override
        det.evidence = list(det.evidence) + [f"user override: {override}"]
        det.display = Detection.from_dict({"type": override}).display
    out["detected"] = det.as_dict()
    out["type_override"] = str(rec.get("type_override") or "")

    if not out["name"].strip():
        raise RegistryError("project needs a name")
    if not out["command"].strip():
        raise RegistryError("project needs a command")
    wd = out["working_dir"]
    if wd and not Path(wd).is_dir():
        raise RegistryError(f"working directory does not exist: {wd}")
    url = out["url"]
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise RegistryError(f"dashboard URL must start with http(s)://: {url}")
    return out
