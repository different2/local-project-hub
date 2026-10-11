# Phase 1 — Architecture Assessment (Audit)

Status: complete. Findings verified against the code on disk (commit `b15314b`).
Scope: answer §2 of the release spec — what can be retained, what needs
adaptation for Windows, what genuinely needs replacement — plus the framework
recommendation.

## 1. Current implementation

| Aspect | Finding |
|---|---|
| GUI framework | PySide6 6.10.3 (Qt WebEngine), installed into system Python 3.9 |
| Entry point | `main.py` → `hub.window.HubWindow` (QMainWindow) |
| UI code | `hub/window.py` (645 lines), `hub/project_dialog.py` (138) |
| Process mgmt | `hub/process_manager.py` (174) — `QProcess`, shlex split, no shell |
| Readiness | `hub/readiness.py` (132) — TCP poll then async HTTP GET via QNAM |
| Storage | `hub/store.py` (171) — JSON registry + `ui.json`, atomic writes |
| Tests | 4 files, 22 tests, all passing (store/process/window/popup) |
| Python syntax | 3.10-style annotations, but every module has `from __future__ import annotations`, so it runs on 3.9 |
| Assets | **none** — no icon, no .icns/.ico, no `assets/` directory |
| Version | `hub/__init__.py` `__version__ = "0.1.0"` — single source, unused by packaging |

## 2. Verdict per spec §2

### Retain without modification (the bulk of the app)
- **`hub/window.py`, `hub/project_dialog.py`, `hub/readiness.py`** — pure Qt, no
  OS assumptions. Qt is the cross-platform layer; these files need no Windows
  changes. The tab model, popup bridge, and log drawer all work unchanged.
- **All 22 tests** — they exercise real Qt objects and real subprocesses, so
  they are the regression net for every later phase.
- **`hub/process_manager.py`'s core** — `QProcess.terminate()`/`kill()` already
  map to the right OS calls, and `MergedChannels` + no `shell=True` means no
  terminal dependency. This satisfies spec §8's "process tracking does not
  depend on a terminal window" on both platforms.

### Adapt (small, well-isolated changes)
1. **`hub/store.py:35` config directory** — hard-codes
   `~/Library/Application Support/LocalProjectHub`. This is the only
   genuinely macOS-specific path in the codebase. Fix: resolve per-platform
   behind `default_config_dir()`, so Windows uses `%LOCALAPPDATA%`.
2. **`run.sh`** — macOS/shell-only launcher. For release it is replaced by the
   packaged app, but keep it for development.
3. **`SIGTERM` semantics** — `stop()` uses SIGTERM then SIGKILL, correct on
   macOS/Linux. On Windows `terminate()` posts WM_CLOSE, which works for most
   servers but not all. Acceptable for now; document as a known difference.

### Replace (nothing in the app itself)
- No application code needs replacing for distribution. What is *missing*
  rather than broken: an icon, version plumbing into the package, an updater,
  and the packaging toolchain. Those are additions, not rewrites.

## 3. Known functional gaps (not packaging issues, but they matter for release)

| Gap | Detail | Impact on release |
|---|---|---|
| **`interpreter` field is dead** | `project_dialog.py` collects it, `store.py` stores it, `process_manager.py` **never reads it**. The command's `python3` always comes from PATH. | The placeholder text promises a feature that does not work. Users registering a venv-based project must type the full path into the command. |
| **No `autostart` implementation** | `store.py` validates the field; `window.py:_autostart()` starts *projects* flagged autostart. But the spec's §9 "Launch at Login" (app-level) is unimplemented. | Phase 5 work. |
| **Logs are memory-only** | 500-line ring buffer per process, lost on restart. | Spec §7 wants history retained; a log file per project is a Phase 5 addition. |
| **`.hubstate` inside the repo** | `run.sh` defaults state into the repo for dev portability. | Fine for dev; the packaged app must use the OS per-user dir (see §2.1). |

## 4. Framework recommendation

**Keep PySide6.** The spec allows a migration only for a concrete technical
reason, and there is none that outweighs the cost:

| Consideration | PySide6 (keep) | Tauri (migrate) |
|---|---|---|
| Working UI to preserve | 780 lines of Qt code, 22 passing tests, 3 bug fixes you watched land | **Total rewrite** of window, tabs, dialogs, popup bridge |
| Bundled runtime size | ~90–120 MB (Qt + Python) | ~5–10 MB |
| Built-in signed updater | none — needs a library (pyupdx / custom) | yes, first-class |
| Process management | `QProcess` already proven on your real projects | shell-out to Rust, rewrite + re-verify |
| Distribution friction | briefcase / PyInstaller; Qt licensing (LGPL) is satisfied by dynamic linking | needs Rust toolchain on the build machine |

The decisive fact: the GUI is the part that works. The parts that are *missing*
(icon, menus, About, updater, packaging) are additions that PySide6 supports
natively — menus and About dialogs are ~40 lines. Only the updater is genuinely
easier in Tauri, and it is solvable here with `pyupdx`-style version-check plus
platform installers, which is what §5 describes anyway (check endpoint → verify
signature → install per-OS artifact).

**Recommendation: stay on PySide6, package with Briefcase (macOS .app + Windows
MSI), add an updater that checks a GitHub Releases endpoint.**

## 5. Phase plan

- **Phase 2 — Compatibility**: platform config dir; verify no Windows-only
  breakage (paths, `shutil.which`, exit-code handling); fix or clearly document
  the dead `interpreter` field.
- **Phase 3 — Packaging**: Briefcase `.app` + `.dmg` on macOS, `.msi` on
  Windows, with icon and version metadata.
- **Phase 4 — Updater**: version check against GitHub Releases, signature
  verification, download/install/restart, failure recovery.
- **Phase 5 — Polish**: icon, native menus, About dialog with version, launch
  at login (opt-in), persistent per-project logs.
- **Phase 6 — Release**: code signing/notarization notes, CI workflow,
  clean-machine install and update tests, documented limitations.
