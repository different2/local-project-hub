# HANDOFF — Local Project Hub

_Last written: 2026-10-18, night (release night). A fresh session should start
from this file alone: read it, run `git log --oneline -15`, then work the open
threads below. Long sessions on this project have died mid-task on provider
errors, so state belongs here and in commits — not only in chat. Developer
docs (run, test, package, release) live in DEVELOPMENT.md; the README is
user-facing._

## Where things stand (verified 2026-10-18, night)

- `main` clean and in sync at `4a4d6ff` (the update-dialog feature).
- **v0.4.1 is the latest release** — both installers, notes applied
  (`Local.Project.Hub-0.4.1.dmg` 262 MB, `.msi` 172 MB). **v0.4.0 is also
  live** — the first release whose in-app update check actually works.
- **The user runs 0.3.7 and must install by hand once** — the check in 0.3.7
  is one of the bugs fixed in 0.4.0, so it can never offer anything itself.
  From 0.4.0 onward the in-app check works; 0.4.1 adds the visible dialog.
  He was told 2026-10-18 with download links (0.4.0 vs 0.4.1 both fine);
  which one he installs is not yet known.
- Full local suite: **15/15 green, 186 tests** (exit 0; `full-suite-6.out` in
  `~/.hermes/cache/scratch/lph-verify/`) on the released tree.
- CI tonight: push-run `39196659931` green; tag run `39198718961` green (all
  four jobs) — the pipeline that failed twice on the first v0.4.0 attempt
  now runs clean end to end. The whole 0.4.1 release ran unattended via
  watcher chain (auto-tag on green → notes on publish).

## Release night 2026-10-17→18: three silent traps, fixed and guarded

The first v0.4.0 tag attempt exposed three "nothing happens" failure modes.
All are fixed and pinned (a test or a standing rule; also in the skill
`github-tag-release-traps`):

1. **A tag on a `[skip ci]` commit builds nothing.** The auto-tagger tagged
   HEAD; by then HEAD was a docs commit carrying `[skip ci]` (docs-only
   commits use it here), so GitHub created NO run at all. Rule: always tag
   the release commit by explicit sha (`git tag vX.Y.Z <sha>`) and verify a
   run appeared.
2. **`"${GITHUB_REF_NAME}"` is empty under PowerShell.** The tag/version
   guard step passed on macOS (bash) but died on the Windows runner at its
   first step ("no tag given to check") — the step was added after v0.3.8,
   so v0.4.0 was the first tag build to run it. Fixed to
   `${{ github.ref_name }}` in both build jobs + new
   `test_tag_check_gets_the_tag_on_every_shell` (negative-controlled: failed
   before, passes after).
3. **Watcher chains can grab the OLD run.** A chain finding "the run for tag
   v0.4.0" by branch prefix matched the previous failed run the moment the
   new tag was pushed, before the new run existed. Match by run id
   (discovered after the push) or by `headSha` + branch together.

Timeline: v0.4.0 live at `42dec72` (tag run `39107315507`, published
2026-10-18 07:27Z, notes applied).

## Release 0.4.1 (2026-10-18 evening): the visible update flow — DONE

User request: clicking "check for updates" showed only "checking for
updates" in the bottom bar and nothing else; he wanted "an obvious
notification box in the center of the screen" that says "checking for
updates", then "all up to date" if true, and downloads it otherwise.
Shipped in `4a4d6ff`:

- `hub/update_dialog.py` (new) — one reusable dialog per window: checking
  (busy bar) → up to date | version available (Download and Install /
  Later / release page) → downloading with a real byte-progress bar →
  error. Non-modal, centred on the screen, re-revealed on every state so
  a result can never be missed.
- `hub/updater.py` — `download_asset()`: chunked download with
  `on_progress(done, total)`; a short read vs the advertised length is an
  error (it replaced `urlretrieve`: no progress, no length check).
- `hub/window.py` — the check/offer/download flow drives the dialog (the
  old offer message box is gone); download progress crosses threads via
  counters the worker bumps and a GUI-thread timer reads; re-clicking
  while busy re-reveals the dialog instead of stacking another;
  `_update_busy` guards re-entry; `_finish` still reports callback crashes
  (the 0.4.0 lesson).
- Tests: `test_check_for_updates_always_reports` reworked to assert each
  outcome lands in the dialog; +2 window tests (all dialog states incl.
  the download signal; download hand-off + corrupt-download launches
  nothing); +1 updater test (`download_asset` progress + short-read, via a
  file:// fixture, no network). `test_window_e2e` 14→16, `test_updater`
  15→16, suite total 186.
- Released unattended: push-run `39196659931` green → tag `v0.4.1` at
  `4a4d6ff` → tag run `39198718961` green → notes applied
  (`release-notes-0.4.1.md` in the scratch dir).

## Still-true rationale from earlier stretches

- **Pinned dependency sets** (move together — DEVELOPMENT.md "Dependency
  versions"): `briefcase==0.4.6` (CI build jobs, `.buildenv`);
  `PySide6==6.7.3` + `PySide6-Essentials==6.7.3` + `PySide6-Addons==6.7.3` +
  `Pillow==11.3.0` (CI test + build jobs, pyproject `requires`, both venvs).
  Why 6.7.3: what both shipped builds contain, supports Py 3.9/3.11, newest
  PySide6 the `macosx_11_0` bundle target can install (6.8+ ships only
  macosx_12_0+ wheels).
- **Docs split**: README is user-facing (the "Updates itself" bullet stays
  OUT, per request); DEVELOPMENT.md = run/test/package/release; this file =
  state.
- **Start-command auto-detection** (`hub/detect_command.py`, 31 tests):
  folder or File… → command; npm/yarn/pnpm/bun chosen by lockfile; Python
  venv becomes the interpreter; `manage.py` → `runserver`; go/cargo/html/sh
  recipes; §6 rule — suggestions only fill EMPTY fields and replace only
  their own earlier suggestion, never a typed/recorded command; files are
  read, never executed. `__main__.py` deliberately skipped.
- **Add-dialog diet** (user feedback): help text cut to one line or deleted;
  File… button on the folder row.
- **Test-runner truthfulness**: `tests/run_all.py` counts "exited nonzero
  without reporting" as a failure — found when a `NameError` hid for weeks
  as "12 passed" on a 13-test file. The repair also fixed
  `test_two_projects_get_two_tabs` itself.
- **Orphan sweep**: 38 leaked `srv_*.py` test servers cleaned 2026-10-16;
  the leak is still open (thread 4). Sweep rule: only `ppid=1` under
  `/var/folders` — never the user's live dashboards or the Hub.

## Open threads, in priority order

1. **"One-click update" smoothness** — the user's goal. Status now: 0.4.0+
   checks, offers, downloads and opens the installer, with visible progress.
   Remaining: the single manual install off 0.3.7 (user's to do, any time);
   unsigned-build warnings need paid certificates (messaging only until
   then); macOS drag-to-Applications is deliberate (self-replace deferred);
   whether an app-downloaded MSI triggers SmartScreen is unverified — check
   before "fixing".
2. **pyobjc-framework-Cocoa is still unpinned** in `requires` (same class of
   risk as the others were; resolves to 12.2.2 = what v0.3.8 shipped; raised
   with the user 2026-10-16 — still pending).
3. **Windows `test_urldetect` flakiness watch** — three different tests have
   failed once each on Windows (`test_detected_suppress_flag_is_applied_to_the_launch`
   run 38917634716; `test_finish_time_output_is_drained_before_deciding_conflict`
   run 39001253618; `test_bind_failure_names_the_port_from_the_command` run
   39004119373). All green on adjacent runs; all during stacked CI runs.
   Standing rule: do not stack CI runs. Tonight's sequential chain ran clean.
4. **The test suite leaks `srv_*.py` test-server children on some teardown
   paths** — 38 orphans found and cleaned on 2026-10-16; at least one path
   still leaks. Investigate next.
5. **MSI upgrade (replace-in-place) verified only from Briefcase's WiX
   template** — run one real Windows update before calling Windows done.
6. **macOS-target ↔ Qt ceiling (FYI / decision)** — the bundle's macOS target
   (`macosx_11_0`) is what caps PySide6 at 6.7.3 today; raising the target
   would unlock newer Qt (product decision, documented in DEVELOPMENT.md).

## Environment on this machine

- `.hubenv` — Python 3.9.6, dev/test env: PySide6 trio 6.7.3, Pillow 11.3.0.
- `.buildenv` — Python 3.11.10, local packaging env: same GUI set, briefcase
  0.4.6.
- `gh` CLI at `~/.local/bin/gh` (not on `PATH`), authed as `different2`.
- Single suites run directly (`.hubenv/bin/python tests/test_workflow_yaml.py`);
  GUI suites go through `tests/run_all.py`, which isolates each test in its
  own process (`--test=NAME` runs one).
- Data dirs: installed app `~/Library/Application Support/LocalProjectHub/`;
  source runs use `./.hubstate` (`LOCAL_PROJECT_HUB_HOME`).
- Docs: user-facing `README.md`, developer `DEVELOPMENT.md`; design context
  in `SPEC.md`, `PHASE1_AUDIT.md`, `hub-project-real-app-design.rtf`.

## Verify claims quickly

```bash
git fetch && git status -sb                    # clean, in sync
QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py   # 15 suites, serial, ~30 min
.hubenv/bin/python tests/test_workflow_yaml.py                  # workflow guards, seconds
~/.local/bin/gh release list                   # v0.4.1 = Latest
~/.local/bin/gh run list --branch main --limit 5
```

_Maintenance: at the end of a work session, move finished items out of Open
threads, add new ones, and refresh the status block._
