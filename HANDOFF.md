# HANDOFF — Local Project Hub

_Last written: 2026-10-17, evening. A fresh session should start from this
file alone: read it, run `git log --oneline -15`, then work the open threads
below. Long sessions on this project have died mid-task on provider errors, so
state belongs here and in commits — not only in chat. Developer docs (run,
test, package, release) live in DEVELOPMENT.md; the README is user-facing._

## Where things stand (verified 2026-10-17, evening)

- `main` clean and in sync; the tip contains the evening's work: the briefcase
  and GUI dependency pins, the docs split, two test-infrastructure fixes, and
  the new command detector (`git log -1` for the hash).
- **v0.3.8 is the latest release** with both installers attached
  (`Local.Project.Hub-0.3.8.dmg` 262 MB, `.msi` 109 MB). No newer release cut.
- Latest CI runs on `main`: green — including a workflow-dispatch run that
  verified the pinned build path end-to-end — apart from three one-off flaky
  Windows failures, explained in the open threads.
- Full local suite: **14/14 green** (exit 0) on the pre-feature tree, and
  **15/15 green** (exit 0) on the 16th's tree. The 17th's dialog polish (see
  below) grew `tests/test_detect_command.py` to 31 tests and `test_urldetect`
  by 2 — the full suite was re-running at writing. The scratch briefcase
  build also finished green with the pinned requires (PySide6 6.7.3 trio +
  pyobjc 12.2.2 — exactly what v0.3.8 ships).
- **Pinned dependency sets** (move together — see DEVELOPMENT.md
  "Dependency versions"):
  - `briefcase==0.4.6` — CI build jobs; local `.buildenv` matches
  - `PySide6==6.7.3`, `PySide6-Essentials==6.7.3`, `PySide6-Addons==6.7.3`,
    `Pillow==11.3.0` — CI test + build jobs, pyproject `requires`, both venvs

## How CI and releases work here

- Push to `main` → the suite runs on **Windows only** (deliberate); serial,
  50-minute cap (GUI suites bind fixed ports and must not overlap).
- Tag `v<version>` → builds the macOS `.dmg` and Windows `.msi` with the
  pinned toolchain, then publishes both to the release. The tag must equal the
  `pyproject.toml` version or `tools/check_tag_version.py` fails in seconds.
- Manual dispatch (`gh workflow run CI --ref main`) → builds both installers
  as artifacts and **never publishes**.
- Workflow guards in `tests/test_workflow_yaml.py`: trigger integrity,
  dispatch-never-publishes, briefcase pinned, GUI set pinned and coordinated
  with pyproject's `requires`.
- Cutting a release = bump `version` in `pyproject.toml`, commit, then
  `git tag vX.Y.Z && git push origin vX.Y.Z`.

## What the last work stretch (Oct 14–17) finished

- Windows port-conflict handling end-to-end (netstat, PowerShell, bind-wait,
  traceback recovery).
- Packaging pipeline: `-p msi`/`-p dmg` fixes, release created before upload,
  publish permissions, `--adhoc-sign`, dispatch builds that never publish.
- Update downloads digest-verified (against the real v0.3.8); tag/version
  guard verified live with a throwaway mismatched tag; MSI UpgradeCode trap
  documented in `pyproject.toml`; Gatekeeper guidance in the macOS updater.
- **Briefcase pinned to 0.4.6** in CI (+ guard test, negative-controlled); a
  dispatch run then verified the pinned build path green.
- **GUI dependency set pinned** to the PySide6 6.7.3 trio + Pillow 11.3.0
  across CI, `pyproject.toml` `requires`, and both local venvs (+ a
  coordinated-pins guard, negative-controlled three ways). Why 6.7.3: it is
  what both shipped builds already contain, it supports Python 3.9 and 3.11,
  and it is the newest PySide6 the bundle can install — briefcase installs app
  dependencies with `pip --platform macosx_11_0_<arch>`, and 6.8+ ships only
  macOS-12+/13+/14+ wheels (see DEVELOPMENT.md "Dependency versions").
- **README split stayed clean**: the "Updates itself" bullet was removed on
  request; README is user-facing, dev material lives in DEVELOPMENT.md.
- **Welcome pane text fixed** — it claimed selecting never starts a project;
  it now matches behaviour (clicking starts it if not already running; adding
  never starts it).
- **Two test-infrastructure fixes** (found this evening):
  1. `test_two_projects_get_two_tabs` raised `NameError` on *every* run since
     commit `1c9a454` (stale `port_a`/`port_b` refs after the ephemeral-port
     refactor), silently: no PASS/FAIL line → the isolated runner counted
     0/0 → the teardown-crash rule turned the suite green. The only symptom
     was "12 passed" for a 13-test file. Test repaired; window suite reports
     13/13.
  2. `tests/run_all.py`: "exited nonzero without ever reporting" now counts as
     a failure (traceback attached) instead of neither-passed-nor-failed —
     verified against a deliberately broken fake suite, which now goes red
     instead of green.
- **Test-server orphan cleanup**: 38 leaked `srv_*.py` test servers (`ppid=1`,
  under test temp dirs, oldest ~1½ days) were terminated; the leak itself is
  an open thread below. The user's live dashboards and the Hub were not
  touched.
- **Start-command auto-detection** (user request, inspired by Dev-Router —
  github.com/Angelov1314/Dev-Router, MIT): new `hub/detect_command.py` fills
  the Add dialog's startup command from the project folder. Recipes:
  `package.json` scripts dev > start > serve (package manager from the
  lockfile: npm `npm run dev`, yarn/pnpm/bun spell it directly); Python —
  `manage.py` → `manage.py runserver` (Django), then app/server/main.py, a
  manifest required, and a project venv becomes the **interpreter** field
  (the command then drops its own `python3` — the interpreter runs it);
  `go.mod` → `go run .`; `Cargo.toml` → `cargo run`; root `index.html` →
  `python3 -m http.server 8000` (the web view needs a URL). `__main__.py` is
  deliberately skipped (`python3 -m pkg` needs the parent directory, which is
  not a hub project's working dir). Safety: a suggestion only ever fills an
  EMPTY command field and replaces only its own previous suggestion — a typed
  or recorded command is never rewritten (spec §6); files are read, never
  executed (§7). New suite (18 tests — 31 after the 17th's polish) + dialog
  tests in `test_urldetect.py`; suite count 14 → 15.
- **Add-dialog polish (Oct 17, from user feedback)**: every help paragraph
  cut to one line or deleted (auto-detection had made them noise; the
  type-override paragraph is gone entirely — its dropdown is
  self-explanatory), and the folder row gained a **File…** button — pick one
  file and the folder (its parent) and command (from the file itself)
  follow: `.py` → `python3 <file>` (a venv still becomes the interpreter;
  `manage.py` gets `runserver`), `.html` → served, `.sh`/`.command` →
  `bash`, `.go` → `go run`, bare `.js` → `node` (inside a package project
  its own script wins), manifests → the folder recipes; names with spaces
  are quoted. Same §6 rule: never rewrites a typed or recorded command.
  `detect_command` is now 31 tests; `test_urldetect` +2.

## Open threads, in priority order

1. **"One-click update" smoothness across macOS/Windows** — the user's goal.
   Remaining: unsigned-build warnings need paid certificates (messaging only
   until then); macOS drag-to-Applications self-replace deliberately deferred;
   digest protection only from 0.3.8 onward (informational); the Windows
   update dialog says nothing about SmartScreen — whether an app-downloaded
   MSI even triggers it is unverified; check before "fixing".
2. **pyobjc-framework-Cocoa is still unpinned** in `requires` (same class of
   risk as the others were; raised with the user 2026-10-16 — pending).
3. **Windows `test_urldetect` flakiness watch** — three different tests have
   now failed once each on Windows: `test_detected_suppress_flag_is_applied_to_the_launch`
   (run 38917634716), `test_finish_time_output_is_drained_before_deciding_conflict`
   (run 39001253618) and `test_bind_failure_names_the_port_from_the_command`
   (run 39004119373, "test server did not start (state=running)"). All three
   were green on adjacent runs, and all three failed while several CI runs
   were executing concurrently — looks load/timing-shaped. Standing rule for
   now: do not stack CI runs; if it recurs anyway, start here.
4. **The test suite leaks `srv_*.py` test-server children on some paths** —
   38 orphans (`ppid=1`, test temp dirs, oldest ~1½ days) were found and
   cleaned up on 2026-10-16; at least one teardown path still leaks.
   Investigate next. (When sweeping: only `ppid=1` under `/var/folders` —
   never the user's live dashboards or the Hub.)
5. **MSI upgrade (replace-in-place) is still only verified from Briefcase's
   WiX template** — run one real Windows update before calling Windows done.
6. **macOS-target ↔ Qt ceiling (FYI / decision)** — the bundle's macOS target
   (macosx_11_0) is what caps PySide6 at 6.7.3 today. Raising the macOS target
   would unlock newer Qt — a product decision, documented in DEVELOPMENT.md.

## Environment on this machine

- `.hubenv` — Python 3.9.6, dev/test env: PySide6 trio 6.7.3, Pillow 11.3.0.
- `.buildenv` — Python 3.11.10, local packaging env: same GUI set, briefcase
  0.4.6 (the 6.12-era split wheels `PySide6_WebEngine`/`PySide6_Pdf` removed).
- `gh` CLI at `~/.local/bin/gh` (not on `PATH`), authed as `different2`.
- Single suites run directly (`.hubenv/bin/python tests/test_workflow_yaml.py`);
  GUI suites go through `tests/run_all.py`, which isolates each test in its own
  process (`--test=NAME` runs one).
- Data dirs: installed app `~/Library/Application Support/LocalProjectHub/`;
  source runs use `./.hubstate` (`LOCAL_PROJECT_HUB_HOME`).
- Docs: user-facing `README.md`, developer `DEVELOPMENT.md`; design context in
  `SPEC.md`, `PHASE1_AUDIT.md`, `hub-project-real-app-design.rtf`.

## Verify claims quickly

```bash
git fetch && git status -sb                    # clean, in sync
QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py   # 15 suites, serial, ~30 min
.hubenv/bin/python tests/test_workflow_yaml.py                  # workflow guards, seconds
~/.local/bin/gh release list                   # v0.3.8 = Latest
~/.local/bin/gh run list --branch main --limit 5
```

_Maintenance: at the end of a work session, move finished items out of Open
threads, add new ones, and refresh the status block._
