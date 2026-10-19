# HANDOFF — Local Project Hub

_Last written: 2026-10-19, morning — **v0.5.0 IS LIVE** (per-project
terminals, the display name taken from the pick and editable in the
sidebar, and a simpler Add-project dialog — the user's three UI requests;
plus the test runner that stops what holds a test port instead of waiting
30 s). A fresh session should start from this file alone: read it, run
`git log --oneline -15`, then work the open threads below. Long sessions on
this project have died mid-task on provider errors, so state belongs here
and in commits — not only in chat. Developer docs (run, test, package,
release) live in DEVELOPMENT.md; the README is user-facing._

## Where things stand (verified 2026-10-19, morning)

- `main` clean and pushed through `91348b6` (the 0.5.0 version bump). The
  UI work is `0b9ed4d` (4 files, +734/−147), the runner fix is `0d9a5f0`,
  the release commit `91348b6`; tag `v0.5.0` points at `91348b6` by design
  — tag the code, never a `[skip ci]` docs commit.
- **v0.5.0 IS LIVE — released and verified:**
  - push run for `91348b6` (`#39256864511`): green;
  - tag run (`#39260486253`): all four jobs green; release notes applied;
    assets dmg 262,410,392 B / msi 172,077,960 B both HTTP 200
    unauthenticated.
  - local full suite on the same tree: **15/15 suites, 197 tests, exit 0,
    13m 54s** (`full-suite-ui3.out` in the scratch dir). The 53-minute
    run before it (`full-suite-ui2.out`) is what exposed the port-wait
    bug — 30 s per isolated test because the user's own `obs_live.py`
    held port 8787.
- **The user's 0.4.2 click is the one to watch:** `/Applications` now has
  **0.4.2** (installed 2026-10-19 00:16), so his update click lands on the
  first build that can actually self-update. The 0.4.2 → 0.5.0 check,
  download-with-progress and dmg hand-off is the flow to verify on his
  machine. **Record the outcome here once known.**

## 2026-10-18 late: "could not reach update server" — the bundle had no CA store

The user's real click in 0.4.0 returned "Could not reach the update server"
on a healthy connection (curl from the same Mac fine). Root cause,
reproduced inside the shipped bundle's own Python: Briefcase's framework
build resolves its CA bundle to the python.org location
(`/Library/Frameworks/Python.framework/.../etc/openssl/cert.pem`), which
does not exist inside the app, so `ssl.get_default_verify_paths()` there
reports `cafile=None`, there is no certifi, and EVERY HTTPS request died
`CERTIFICATE_VERIFY_FAILED` (the download step would fail identically). The
check maps that to "could not reach", so it read as a network problem.
Scope: any installed build making this request on a Mac without a
python.org-installed cert bundle (his included).

Fix (`e1ea9d6`, shipped in v0.4.2): the bundle ships `certifi` (pinned) and
`hub/updater.py` builds its SSL context from it (`_ssl_context()`, with the
system CA files as fallback for source runs); a TLS failure now reports a
certificate problem, not the user's connection. Guards: trust-store-is-real
(>=40 loaded CAs), fallback test, message split, and the ci.yml↔pyproject
pin coordination test.

Reproduction harness (reusable, in `~/.hermes/cache/scratch/lph-verify/`):
`hubprobe.app` is a CLONE of the installed app with `main.py` replaced by a
probe — run the clone, never the real app. `appcheck_result.json` = the
user's failure reproduced in the OLD bundle (copy: `*_prefix.txt`); the NEW
bundle gives `app_fetch_latest_release: OK` with default-store CAS still 0
and helper CAS 117. To verify any future build the same way: `briefcase
build macOS`, clone `build/hub/macos/app/Local Project Hub.app`, drop in
`probe_main.py`, run the stub with a clean env (`env -i HOME=$HOME
PATH=/usr/bin:/bin`). Probe caveat: a probe without a `main()` function
makes the app abort into a modal dialog after writing its JSON — data lands
first and the process must be killed; `probe_main.py` exits cleanly.

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
  file:// fixture, no network). Suite total 186.
- Released unattended: push-run `39196659931` green → tag `v0.4.1` at
  `4a4d6ff` → tag run `39198718961` green → notes applied.

## Release 0.5.0 (2026-10-19): the three UI requests + the port-wait fix — DONE

User requests: each project should get its own terminal pane instead of one
shared drawer; the project's display name should come from the folder/file
picked and stay editable in the sidebar "whenever I want"; and most
Add-project options should hide behind one optional-settings control, with
no truncated sentences. Shipped in `0b9ed4d` (4 files, +734/−147):

- `hub/window.py` — every `_append_log(...)` call now carries an owner id
  (`rec["id"]`, `pid`, or `self.active_id`); `LogDrawer` keeps one pane per
  project and shows the owner in its header (`Logs — <project>`). Switching
  projects switches panes; nothing carries over. Sidebar rename via
  `itemDoubleClicked` + `setEditTriggers`; `_retitle_tab()` follows.
  `_item_label` still uses an empty icon for iconless records (a `•`
  fallback was tried and reverted — it changed sidebar/tab text and broke
  `test_reselecting_a_project_does_not_open_a_second_tab`).
- `hub/project_dialog.py` — 490-line rewrite (was 381): two required
  fields (folder, command), the name auto-derived from the pick's basename
  and never overwritten once typed, every auto-decided field behind a
  `QToolButton` "Optional settings" disclosure, help text given
  `heightForWidth` so sentences are no longer sliced.
- Guard tests first: 3 dialog tests in `test_urldetect.py` (one drives the
  real `_pick_dir()` with a monkeypatched `QFileDialog`), 2 e2e tests in
  `test_window_e2e.py` (each project's pane gets only its own output;
  renaming in the sidebar sticks). Suite 190 → 195.
- Proof beyond the suite: `render_dialog.py` rendered the dialog collapsed
  and expanded to PNG and both were read back (no clipping, nothing past
  the right edge); `probe_perproject_drawer.py` drove a real `HubWindow`
  with two live processes and confirmed Alpha's pane held `ALPHA-ONLY` only,
  Beta's was empty until its output arrived, and switching back restored
  Alpha's history.

`0d9a5f0` (separate commit): `tests/run_all.py` `wait_for_ports_free()`
became `free_test_ports()` — `port_owners()` (`lsof -nP -sTCP:LISTEN -t`),
`stop_process()` (SIGTERM, then SIGKILL after 1.5 s), bounded wait only
while a port is still bound; added `test_runner_stops_whatever_holds_a_test_port`.
Why: a 53-minute suite run exposed a 30 s wait before every isolated test,
caused by the user's own `obs_live.py` on port 8787. After the fix the same
suite took 13m 54s and printed one
`freed test ports [8787]: stopped pid 73750`. Windows keeps the wait-only
path (no lsof; CI has no stray listeners).

Released 2026-10-19: `91348b6` (version bump only — `hub.__version__` falls
back to pyproject when no dist metadata is installed) → push run
`#39256864511` green → tag `v0.5.0` at `91348b6` → tag run `#39260486253`
all four jobs green → notes applied → README Download pins bumped
(`[skip ci]` docs commit).

## Still-true rationale from earlier stretches

- **Pinned dependency sets** (move together — DEVELOPMENT.md "Dependency
  versions"): `briefcase==0.4.6` (CI build jobs, `.buildenv`);
  `PySide6==6.7.3` + `PySide6-Essentials==6.7.3` + `PySide6-Addons==6.7.3` +
  `Pillow==11.3.0`, and (since 0.4.2) `certifi==2026.10.18` +
  `pyobjc-framework-Cocoa==12.2.2` (CI test job, pyproject `requires`, both
  venvs; `.hubenv` on 3.9 keeps pyobjc 11.1 — 12.x ships no 3.9 wheels).
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

1. **Watch the user's first real update click** (see Where-things-stand):
   0.4.2 is installed, 0.5.0 is the release to reach — check → download
   with progress → dmg hand-off, and record the outcome here.
2. **"One-click update" smoothness** — this 0.4.2 → 0.5.0 run is the
   FIRST genuinely end-to-end flow (offer → TLS-clean download with progress
   → dmg hand-off). Remaining beyond that: unsigned-build warnings need
   paid certificates (messaging only until then); macOS
   drag-to-Applications is deliberate (self-replace deferred); whether an
   app-downloaded MSI triggers SmartScreen is unverified — check before
   "fixing".
3. **Windows `test_urldetect` flakiness watch** — three different tests have
   failed once each on Windows (`test_detected_suppress_flag_is_applied_to_the_launch`
   run 38917634716; `test_finish_time_output_is_drained_before_deciding_conflict`
   run 39001253618; `test_bind_failure_names_the_port_from_the_command` run
   39004119373). All green on adjacent runs; all during stacked CI runs.
   Standing rule: do not stack CI runs. (Clean through the v0.4.2 runs.)
4. **The test suite leaks `srv_*.py` test-server children on some teardown
   paths** — 38 orphans found and cleaned on 2026-10-16; at least one path
   still leaks (none visible at the 2026-10-19 late-night sweep either).
   Investigate next.
5. **MSI upgrade (replace-in-place) verified only from Briefcase's WiX
   template** — run one real Windows update before calling Windows done.
6. **macOS-target ↔ Qt ceiling (FYI / decision)** — the bundle's macOS target
   (`macosx_11_0`) is what caps PySide6 at 6.7.3 today; raising the target
   would unlock newer Qt (product decision, documented in DEVELOPMENT.md).
   (DONE since the list was first written: the pyobjc pin; the TLS fix.)

## Environment on this machine

- `.hubenv` — Python 3.9.6, dev/test env: PySide6 trio 6.7.3, Pillow 11.3.0,
  certifi 2026.10.18, pyobjc 11.1 (12.x has no 3.9 wheels).
- `.buildenv` — Python 3.11.10, local packaging env: same set with
  pyobjc-framework-Cocoa 12.2.2, briefcase 0.4.6.
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
QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py   # 15 suites, serial, ~15 min
.hubenv/bin/python tests/test_workflow_yaml.py                  # workflow guards, seconds
~/.local/bin/gh release list                   # v0.5.0 = Latest (verified)
~/.local/bin/gh run list --branch main --limit 5
# bundle probe (see the TLS section): rebuild, clone the built .app,
# drop in probe_main.py, run the stub — app_fetch_latest_release must say
# OK (this is how 0.4.2 was proven)
```

_Maintenance: at the end of a work session, move finished items out of Open
threads, add new ones, and refresh the status block._
