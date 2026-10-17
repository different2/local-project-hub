# HANDOFF — Local Project Hub

_Last written: 2026-10-16, evening. A fresh session should start from this
file alone: read it, run `git log --oneline -15`, then work the open threads
below. Long sessions on this project have died mid-task on provider errors, so
state belongs here and in commits — not only in chat. Developer docs (run,
test, package, release) live in DEVELOPMENT.md; the README is user-facing._

## Where things stand (verified 2026-10-16, evening)

- `main` clean and in sync with origin; the tip contains the evening's work
  (briefcase pin, README/DEVELOPMENT split) — `git log -1` for the hash.
- **v0.3.8 is the latest release**, with both installers attached:
  `Local.Project.Hub-0.3.8.dmg` (262 MB) and `.msi` (109 MB). No newer release
  has been cut since.
- Latest CI runs on `main`: green. Full local suite: 14/14 suites.
- Version fields: `pyproject.toml` `version = "0.3.8"`; `hub/__init__.py`
  `__version__` derives from that (never hardcoded).
- CI build toolchain is now **pinned** (`briefcase==0.4.6`, guarded by
  `tests/test_workflow_yaml.py`); not yet exercised by a real build at the
  time of writing — watch the first dispatch/tag run.

## How CI and releases work here

- Push to `main` → the suite runs on **Windows only** (deliberate); serial,
  50-minute cap (GUI suites bind fixed ports and must not overlap).
- Tag `v<version>` → builds the macOS `.dmg` and Windows `.msi` with the
  pinned toolchain, then publishes both to the release. The tag must equal the
  `pyproject.toml` version or `tools/check_tag_version.py` fails the build in
  seconds.
- Manual dispatch (`gh workflow run CI --ref main`) → builds both installers
  as artifacts and **never publishes** (`test_workflow_yaml.py` guards that).
- Cutting a release = bump `version` in `pyproject.toml`, commit, then
  `git tag vX.Y.Z && git push origin vX.Y.Z`.

## What the last work stretch (Oct 14–16) finished

- Windows port-conflict handling end-to-end (netstat port owners, PowerShell
  command-line reads, bind-wait, traceback recovery).
- Packaging pipeline: `-p msi`/`-p dmg` flags fixed, release created before
  uploads, `contents: write` on the publish job, `--adhoc-sign` so the macOS
  build cannot hang on a signing prompt, dispatch builds that never publish.
- **Update downloads are digest-verified** (previously dead code that read a
  field the GitHub API never returns); verified against the real v0.3.8.
- Tag/version guard verified live with a deliberately mismatched throwaway
  tag; no release leaked, tag deleted.
- MSI UpgradeCode trap documented in `pyproject.toml`; Gatekeeper guidance
  added to the macOS update dialog.
- **Briefcase pinned** to 0.4.6 in both CI build jobs + `test_briefcase_is_pinned`
  guard (negative-controlled: unpinned → fails, install removed → fails).
  Local `.buildenv` raised to 0.4.6 to match.
- **README split**: the README is now user-facing (what it is, install,
  first-launch warnings, usage); development material moved to the new
  **DEVELOPMENT.md**; stale claims fixed on the way (installer filenames —
  the real assets are `Local.Project.Hub-<version>.dmg/.msi`; the
  "53 tests across 6 suites" line).

## Open threads, in priority order

1. **"One-click update" smoothness across macOS/Windows** — the user's goal;
   their last instruction toward it was provider-eaten on 2026-10-16. Done so
   far: digest verification, Gatekeeper dialog text, toolchain pin. Remaining:
   - **Unsigned builds** (Gatekeeper/SmartScreen warnings) — needs paid
     certificates; messaging only until then. Not started.
   - **macOS drag-to-Applications self-replace** — deliberately deferred
     (risky, wants careful testing first). Not started.
   - Digest verification only protects updates **from 0.3.8 onward**
     (informational).
   - The Windows update dialog says nothing about SmartScreen; whether an
     app-downloaded MSI triggers it is unverified — check before "fixing".
2. **PySide6 / PySide6-Addons / PySide6-Essentials / Pillow are still
   unpinned** in the CI build jobs — the same class of from-outside risk
   briefcase had. Decide: pin them too, or keep tracking latest deliberately.
   (Raised with the user 2026-10-16 evening.)
3. **Flaky Windows test to watch**: `test_detected_suppress_flag_is_applied_to_the_launch`
   failed once (run 38917634716, commit `5d82456`, "flag never reached the
   process: ''"); green before and after, unrelated to that commit. If CI goes
   red there, start there.
4. **MSI upgrade (replace-in-place) verified only by reading Briefcase's WiX
   template** — run one real Windows update before calling Windows updates
   done.
5. **Small wording bug noted 2026-10-16**: the in-app welcome pane says
   "Adding or selecting a project never starts it by itself", but selecting
   does start it (`tests/test_window_e2e.py`: "Opening the window does not
   start anything; the user selecting it does"). The in-app sentence is stale
   — fix it when in the area.

## Environment on this machine

- `.hubenv` — Python 3.9.6, dev/test env (runs `./run.sh` and the suites).
  Contains an old briefcase 0.3.24 that packaging does not use.
- `.buildenv` — Python 3.11.10, briefcase **0.4.6** (matches the CI pin);
  what local packaging uses. CI uses Python 3.11.
- `gh` CLI at `~/.local/bin/gh` (not on `PATH`), authed as `different2`.
- Single suites run as plain scripts, no pytest needed locally:
  `.hubenv/bin/python tests/test_workflow_yaml.py`.
- Data dirs: the installed app uses `~/Library/Application Support/LocalProjectHub/`;
  source runs use `./.hubstate` (`LOCAL_PROJECT_HUB_HOME`).
- Docs: user-facing `README.md`, developer `DEVELOPMENT.md`; design context in
  `SPEC.md`, `PHASE1_AUDIT.md`, `hub-project-real-app-design.rtf`.

## Verify claims quickly

```bash
git fetch && git status -sb                    # clean, in sync
QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py   # 14 suites, serial, ~30 min
.hubenv/bin/python tests/test_workflow_yaml.py                  # workflow guards, seconds
~/.local/bin/gh release list                   # v0.3.8 = Latest
~/.local/bin/gh run list --branch main --limit 5
```

_Maintenance: at the end of a work session, move finished items out of Open
threads, add new ones, and refresh the status block._
