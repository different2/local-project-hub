"""Private browser-backed compatibility for standalone HTML autosave.

No Python bridge or filesystem API is exposed to JavaScript. A project gets its
own persistent Chromium profile; native same-origin storage rules still apply.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript

from .static_site import static_site_origin

_SCRIPT_NAME = "hub.private-html-storage"
_STORAGE_JS = r"""
(() => {
  if (window !== window.top || location.origin !== ORIGIN || typeof window.storage !== 'undefined') return;
  const prefix = 'hub.private-html-storage:';
  function privateKey(key, shared) {
    if (shared) throw new Error('Shared/cloud storage is not available in Local Project Hub.');
    if (typeof key !== 'string' || !key.length) throw new TypeError('Storage key must be a nonempty string.');
    return prefix + key;
  }
  window.storage = {
    async get(key, shared = false) {
      const value = localStorage.getItem(privateKey(key, shared));
      return value === null ? null : {key, value, shared: false};
    },
    async set(key, value, shared = false) {
      const storageKey = privateKey(key, shared);
      if (typeof value !== 'string') throw new TypeError('Storage value must be a string.');
      localStorage.setItem(storageKey, value); // Quota/I/O errors reject, never claim a save.
      return {key, value, shared: false};
    }
  };
})();
"""


class HtmlStorageProfiles:
    """Profiles owned by the Hub window, outliving its project-tab pages."""

    def __init__(self, state_dir: Path, owner):
        self.state_dir = Path(state_dir)
        self.owner = owner
        self._profiles: dict[str, QWebEngineProfile] = {}
        self._origins: dict[str, str] = {}

    def for_record(self, record: dict) -> QWebEngineProfile | None:
        origin = static_site_origin(record)
        project_id = str(record.get("id") or "")
        if not origin or not project_id:
            return None
        profile = self._profiles.get(project_id)
        if profile is None:
            # Hash the stable identifier: never treat a record value as a path.
            identity = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
            base = self.state_dir / "html-storage"
            base.mkdir(parents=True, exist_ok=True, mode=0o700)
            folder = base / identity
            folder.mkdir(exist_ok=True, mode=0o700)
            profile = QWebEngineProfile("hub-html-" + identity, self.owner)
            profile.setPersistentStoragePath(str(folder / "data"))
            profile.setCachePath(str(folder / "cache"))
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            self._profiles[project_id] = profile
        if self._origins.get(project_id) != origin:
            for previous in profile.scripts().find(_SCRIPT_NAME):
                profile.scripts().remove(previous)
            script = QWebEngineScript()
            script.setName(_SCRIPT_NAME)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(False)
            script.setSourceCode(_STORAGE_JS.replace("ORIGIN", json.dumps(origin)))
            profile.scripts().insert(script)
            self._origins[project_id] = origin
        return profile
