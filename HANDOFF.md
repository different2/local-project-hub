# HANDOFF — Local Project Hub

_Last written: 2026-10-24, resume checkpoint — **v0.7.0 IS LIVE: opening a project no
longer starts it.** A click in the sidebar now only opens the project's tab,
on a page in the app's own colours with the project's name, its command and
one **Start** button in the middle; the project runs when Start is pressed.
Projects with no dashboard (a Discord bot) show "Project is running" instead
of a button once they are up. Before this, selecting a row called
`_start_active()`, so every click in the sidebar was a hidden "run this".
Carried in: self-installing updates (0.6.0), the detected-URL fix (0.6.1),
Rename in the sidebar (0.6.2), per-project terminals, the display name taken
from the pick and editable in the sidebar, the simpler Add-project dialog, and
the test runner that stops what holds a test port. A
fresh session should start from this file alone: read it, run
`git log --oneline -15`, then work the open threads below. Long sessions on
this project have died mid-task on provider errors, so state belongs here
and in commits — not only in chat. Developer docs (run, test, package,
release) live in DEVELOPMENT.md; the README is user-facing. Latest addition:
the forensic-audit triage (test-quality findings fixed, product bugs open and
recorded with file:line)._

## PR #2 integration in progress (2026-10-24 — supersedes the resume checkpoint)

**Temporary diagnostic head — DO NOT MERGE:** PR #2 is now at
`7c383fe4f9c1a837cb1008248b9d90921905ddf9`. Application code and the ordinary
CI runner remain identical to `edfc1f0`; only a temporary renderer probe and
its PR-only, read-only workflow were added. They must be removed before merge.

- Final application-code Mac run passed **19/19 suites, 309 passed, 3 skipped,
  zero failures/blocked/not-run**, exit 0, log
  `~/.hermes/cache/scratch/lph-pr2-final/macos-edfc1f0-py311.log`.
- **Both Windows attempts failed identically:** 17/19 suites, 299 passed,
  6 skipped, 7 failed (four window and three popup page-load cases). The
  process-safety suite passed, 16 passed/1 skip. The Windows mock setup bugs
  and reviewed process/endpoint corrections are not the remaining failures.
  Full artifacts are in `lph-pr2-final/windows-edfc1f0-attempt{1,2}/`.
- No further blind full reruns. Narrow diagnostic run **40142997866** is
  underway: bare Qt vs the exact failing Hub test vs unchanged main, with
  offscreen/native Windows settings and reversion controls. Its observer was
  calibrated locally positive → deliberate wrong-title failure → positive.
  It persists real results in the `TEMP-windows-renderer-probe` artifact.
  **Diagnostic completion is not a passing product check.** Ordinary CI
  `40142997779` on the TEMP head is deliberately unapproved.
- Read CURRENT in `~/.hermes/cache/scratch/lph-pr2-review/STATUS.md` for the
  next action. Diagnose from the probe, make only a supported correction,
  archive/remove `.github/workflows/windows-renderer-probe.yml` and
  `tools/windows_renderer_probe.py`, then run final ordinary verification.
- Two allowed independent-review passes completed; confirmed endpoint findings
  were minimally corrected with observed RED/GREEN regressions. No more
  review loop. Native Cocoa Start/Restart/Stop was also exercised during review
  with inspected screenshots plus HTTP/PID/listener checks.
- Original `174e90c`, Tahir Masood's authorship and existing co-author trailer
  remain intact. README acknowledgement is in the PR, and explicit credit and
  honest progress were [posted/read back](https://github.com/different2/local-project-hub/pull/2#issuecomment-6390548019).
  **PR still open/unmerged. No release/install has happened.**

### Earlier integration checkpoint (historical)

- User authorized checking and merging the existing contribution, with explicit
  credit, and then approved appending narrowly scoped corrective commits to the
  same PR after review reproduced three blockers. **Not merged yet.**
- PR head is `ada1c9946a0777b01dbb96d853e7f2bdd9ce8971`. The contributor's original
  `174e90c` is retained unchanged, including Tahir Masood's authorship and the
  CommandCodeBot co-author trailer. Maintainer followup `ada1c99` corrects
  TIME_WAIT restart refusal, explicit IPv4/IPv6 endpoint conflict ownership,
  coherent ancestry/identity capture, and two platform-specific test fixtures.
  README now explicitly acknowledges [@tahirmasood2](https://github.com/tahirmasood2)
  and links the contribution. Progress/thanks were posted on [PR #2](https://github.com/different2/local-project-hub/pull/2#issuecomment-6387132320).
- Native Cocoa Start → rendered dashboard / HTTP 200 → Restart with a new PID
  → rendered dashboard → Stop / tab closed / no listener: **passed**, exit 0;
  screenshots inspected. The 14 safety and 17 platform tests passed on real
  Python 3.9 and 3.11. Eight remove-fix controls went RED and restored GREEN.
- **Still running:** full corrected macOS suite, 19 suites, log
  `~/.hermes/cache/scratch/lph-pr2-fixes/macos-corrected-py311.log` (process
  `proc_91f0f254b239`); corrected Windows PR run `40116836083` at the exact head
  above (watcher `proc_bdb5473db03a`). Original-head Windows run `39731581450`
  failed and is superseded, not evidence about the corrections.
- Independent read-only review checkpoint `deleg_70627ccd` is also pending.
  Detailed working checkpoint and artifacts:
  `~/.hermes/cache/scratch/lph-pr2-review/STATUS.md`. Review/fix worktrees live
  beside it in `lph-pr2-review/tree` and `lph-pr2-fixes/tree`; `.hubenv` there
  is an untracked test-environment symlink, never a file to stage.
- **NEXT ACTION:** read the actual final Mac log and exact-head Windows result,
  inspect the review checkpoint, then merge **the existing PR** with a merge
  commit pinned to the tested head if those checks justify it. Preserve original
  commit ancestry and read back remote merged state. If Windows shows only the
  previously recorded page-never-loaded Chromium pattern, one failed-job rerun
  precedes any diagnosis; do not excuse a persistent failure. Refresh this
  section with the final result. **Do not release or install a new app** as part
  of this request; installed/latest released version remains 0.7.0.

## Resume checkpoint (2026-10-24 — read this before the historical sections)

- The prior session is `20261018_231911_c86025`. Its last user question was
  whether the test fixes would interfere with the product fixes being worked
  on separately; it was answered. There is no dropped implementation request
  at that session's end. Do not start competing audit fixes by default.
- At this check, local `main` and `origin/main` were both `75e9fb6`, with a
  clean worktree. The only change in this resume is this handoff refresh.
- Latest main CI remains run `39552285135`, testing `fc41b0d`: the Windows
  test job is successful after the previously documented rerun; installer and
  publish jobs were skipped on that push. Latest release remains **v0.7.0**,
  with both the DMG and MSI assets uploaded. The full local suite was **not
  rerun** during this resume; the 220-test result below is historical.
- **New since the prior session: [PR #2](https://github.com/different2/local-project-hub/pull/2)**,
  "Fix forensic audit findings and process lifecycle defects", is **OPEN**,
  based on `75e9fb6`, head `174e90c55b696f592d58ed83f5f5e8552a51242a`, branch
  `fix/forensic-audit-remediation`. GitHub reports it mergeable, but
  `gh pr checks 2` reports **no checks**. No merge or review was performed here.
  Its description reports 18/18 suites, 290 passed / 5 skipped on Windows 11,
  Python 3.13.14; those are the contributor's results, not verified locally.
  macOS/Linux runtime, packaging and real login-item integration are explicitly
  unverified there. It also changes all four files from our test-fix commit;
  check that the guards' intent survives rather than blindly reapplying them.
- **Installed app is now 0.7.0**, not 0.6.2: the live bundle's Info.plist
  reports 0.7.0; update.log records the third self-install at 2026-10-20
  12:24:04–12:24:08, and the old 0.6.2 bundle is present in the Trash.
- Next decision for the user: review and test PR #2 on this Mac before any
  merge/release, or work on a different request. Do not treat an open PR or its
  self-reported test results as fixes already present in `main` or the app.

## Where things stand (verified 2026-10-20, evening)

- **v0.7.0 IS LIVE — released and verified** (2026-10-20): opening a project
  no longer starts it (the section below). Tag `v0.7.0` at `b25329e`; tag run
  `#39475032062`: all four jobs green (`Build macOS installer`,
  `Tests (windows-latest)`, `Build Windows installer`, `Publish to the GitHub
  release`). Assets dmg **262,551,326 B** / msi **172,086,176 B**, both HTTP
  200 unauthenticated; `releases/latest` = `v0.7.0`; notes applied.
  Local suite on the same tree: **17/17 suites, 218 tests, exit 0**
  (`full-suite-0.7.0b.out`). After the audit test fixes (`fc41b0d`) it is
  **220 tests**, still 17/17.
- **A forensic audit arrived** (2026-10-20, read-only, audited v0.5.0): three
  test-quality findings are fixed in `fc41b0d`; the product bugs it reports
  are still open and belong to someone else. Triage table below.
- The installed app on this Mac is **0.7.0** (rechecked 2026-10-24); the third
  self-install, 0.6.2 → 0.7.0, completed at 12:24 on 2026-10-20. The log and
  preserved old bundle are recorded in the resume checkpoint above.
- `main` carries `b25329e` (0.7.0). Earlier: `bc8295c` (the 0.6.2 fix). The 0.5.0 work
  is `0b9ed4d` (UI), `0d9a5f0` (runner) and `91348b6` (bump); the
  self-install work is `ec655a2` (tag `v0.6.0`); the detected-URL fix is
  `fd69d81` (tag `v0.6.1`), `bc8295c` (tag `v0.6.2`) — tag the code, never a
  `[skip ci]` docs commit.
- **v0.6.2 IS LIVE — released and verified:** tag `v0.6.2` at `bc8295c`; the
  Rename fix (below) landed red-test-first. Tag run `#39377116143`: all four
  jobs green (`Tests (windows-latest)`, `Build macOS installer`, `Build
  Windows installer`, `Publish to the GitHub release`). Assets dmg
  262,420,721 B / msi 172,086,164 B, both HTTP 200 unauthenticated;
  `releases/latest` = `v0.6.2`; notes applied.
- **v0.6.1:**
  - tag run (`#39372517820`): all four jobs green — `Tests (windows-latest)`,
    `Build Windows installer`, `Build macOS installer`, `Publish to the
    GitHub release`;
  - assets dmg 262,489,943 B / msi 172,082,068 B, both HTTP 200
    unauthenticated; `releases/latest` = `v0.6.1`; notes applied.
  - local full suite on the same tree: **16/16 suites, 206 tests, exit 0**
    (`full-suite-0.6.1.out` in the scratch dir).
- **v0.6.0** (previous, same day): tag `v0.6.0` at `ec655a2`, tag run
  `#39368233018` green, assets 262,419,588 B dmg / 172,086,164 B msi;
  suite then was 16/16, 204 tests.
- **The self-install has run for real and worked** (verified 2026-10-20 from
  the bundle and the log, after wrongly reporting "still 0.4.2" from a stale
  reading): `/Applications/Local Project Hub.app` is **0.6.1**, bundle dated
  Oct 19 22:01, and `~/Library/Logs/LocalProjectHub/update.log` ends with
  ```
  2026-10-19 22:29:12 waiting for pid 155 to exit
  2026-10-19 22:29:12 copying the new version beside the old one
  2026-10-19 22:29:17 moving the old version to the Trash (… (before 0.6.0) …)
  2026-10-19 22:29:17 installed; reopening /Applications/Local Project Hub.app
  ```
  with `~/.Trash/Local Project Hub (before 0.6.0) 2026-10-19 22-29-12-155.app`
  on disk. So 0.4.2 → 0.6.0 was the last manual drag, and **0.6.0 → 0.6.1
  self-installed exactly as designed** — the window closed, the swap happened,
  the old copy went to the Trash, the app reopened. The next update
  (0.6.1 → 0.6.2) is the same path again; the only untested step left in the
  chain is a swap that *fails*, which by design restores and reopens.

## Release 0.7.0 (2026-10-20): opening a project no longer starts it — DONE

Reported by the user:

> *"when I navigate to a project in the side view it shouldn't automatically
> start up … Instead I'd like it to open a blank browser tab with the window
> the same color as the rest of the app, similar to the first tab with the
> instructions on them, and in the center if the tab there is a start button.
> Then when it starts up it runs the project. For projects that don't run in
> the window, like the discord bots I run just replace the button with
> 'project is now running' or something that sounds nice once it starts up."*

**What changed.** `_on_select` used to call `_start_active()` (or start the
project from `_open_project_tab`), so a click in the sidebar launched servers,
bots and their browsers. Now selection only opens the project's tab, and the
tab lands on a **start page**:

- `hub/startpage.py` (new) renders it: the project's name, the command it
  runs, one Start button in the middle, styled from the app palette
  (`_page_colors()` reads `QPalette.Window/WindowText/Highlight`) so it looks
  like the instructions tab rather than a white webview.
- The button is an ordinary link to `https://hub.invalid/start/<project id>`,
  and `_HubPage.acceptNavigationRequest` (a `QWebEnginePage` subclass now
  installed on every `HubWebView`) refuses that navigation and emits
  `start_requested` / `stop_requested`. **A custom `hub://` scheme cannot be
  used**: a probe (`probe_startpage_nav.py`) showed QtWebEngine drops clicks on
  an unknown scheme without ever calling `acceptNavigationRequest`; the
  https-on-a-dead-host form does reach it.
- No dashboard (a bot): the same page becomes a status card — green dot,
  **Project is running**, "its output is in its terminal below". While
  starting it says "Starting …"; a failed start shows the reason next to a
  working Start button.
- One tab per project: re-selecting focuses the existing tab and refreshes its
  page. `_show_dashboard` and `_on_state` now target the project's **own**
  view, so a background project becoming ready cannot repoint the tab on
  screen. `_ready()` no longer requires the project to be the active one (it
  just needs its own tab); it treats `starting` as ours as well as `running`,
  so a fast port cannot leave the tab stuck on "Starting…".
- A project that exits by itself keeps its tab and terminal and shows the
  stopped page; a user Stop closes the tabs and returns to the starter tab.
- Desktop projects (an app in its own window) still get no tab: they log
  "press Start to launch it" and start from the toolbar.

**Tests.** Three existing tests assumed selection auto-started and now start
explicitly (`test_clicking_a_project_opens_it_without_launching_it`, the two
port-conflict tests in `test_urldetect.py`); the clicking one asserts the new
contract both ways (select ≠ start, Start = start). New: `tests/test_startpage.py`
(8) for the link and the page text, `test_startpage.py` registered in
`run_all.py`, and three window e2e tests (page shown and nothing running; the
button actually starting the project; the running card).

**Two traps worth remembering.**

- `st.add(rec)` returns a **new** dict (`validate()` copies), so
  `rec = st.add(validate({...}))` is required before `rec["id"]` means
  anything. A test that kept the pre-add dict silently used `id == ""`, so
  `_select_id` matched no row and the assertions passed for the wrong reason.
- `setHtml()` is asynchronous: a click issued right after it lands on an empty
  document. `_wait_for_page_text()` polls `document.title` (this PySide6 build's
  `runJavaScript` takes no Python callback) until the DOM really contains the
  text, then clicks. The real app was fine all along — only the test clicked
  too early.

## Forensic audit triage (2026-10-20): tests fixed, product bugs open — DONE

A third-party read-only audit of `6206e22` (v0.5.0, run on Windows) arrived
with CONFIRMED 6 / HIGH-CONFIDENCE 1 / TEST-QUALITY 1 / INFORMATIONAL 6 /
DISMISSED 2. Scope set by the user: **fix the test-quality findings only** —
"someone else might fix the other ones" — and BUG-006 is already fixed. The
audit file is `~/.hermes/attachments/local_hub_forensic.txt`.

Re-checked against HEAD (`fc41b0d`, 0.7.0), never against the audited commit:

| Finding | On 0.7.0 | Where |
|---|---|---|
| BUG-001 non-object `registry.json` → raw `AttributeError` at startup | **reproduces** — `[]`, `"s"`, `42`, `null` all raise it | `hub/store.py:112` (`raw.get` before any type check); `main.py` catches only `RegistryError` |
| BUG-002 `import_json` on a bare JSON array | **reproduces** | `hub/store.py:185` — `raw.get(...)` is evaluated before the `isinstance` that sits in its *default argument* |
| BUG-003 rejected import leaves phantom projects | **reproduces** — `in-memory: ['good']`, nothing on disk | `hub/store.py:187-192` mutates `self.projects` per record; `save()` runs last |
| BUG-004 stale restart timer force-kills the replacement | **present by source** — `restart()` arms an untracked `QTimer.singleShot`, `_force_kill` acts on whatever `self.proc` is then, with no generation check. Mechanism reproduced by the audit on Windows; not re-run here | `hub/process_manager.py:355-367, 494-510` |
| BUG-005 readiness never retries after a transient HTTP error | **present by source** — `_http_done` returns on a transport error, `_tcp_tick` already stopped `_tcp_poll`, and only `_on_timeout` is armed | `hub/readiness.py:105-131` |
| BUG-006 detected URL written to the wrong project | **FIXED in 0.6.1** — the signal carries the project id (`lambda u, p=pid: …`) and only the project in view gets its tab loaded | `hub/window.py:1383, 1484-1511` |
| BUG-007 "Report a Problem" contradicts its own privacy claim | **reproduces** — `log_tail` *is* the log pane: `[hub] starting <name>: <command>` plus raw project output, and the issue URL carries it | `hub/window.py:641-650`; `hub/diagnostics.py:53-54, 72-73` |
| TEST-001 vacuous privacy guard | **fixed, `fc41b0d`** | `tests/test_updater.py` |
| INFO-005 a 0-test suite counted as green | **fixed, `fc41b0d`** | `tests/run_all.py` `report_suite` |
| INFO-006 "guards" assert source substrings | **fixed, `fc41b0d`** — 3 of the 5 tests (the audit said 5; two were honest) | `tests/test_windows_process_stop.py` |

What `fc41b0d` changed in the tests:

- **TEST-001**: the old line was
  `assert "…" not in text.replace("starting /secret/path", "") or "log_tail" in report`
  — the right side is true for every real report, and the `replace()` excused
  the leak it was named after. It now pins the builder's own contract: a
  project **count**, no registry fields, and a whitelist of report keys so a
  new field has to be reviewed for privacy. **It does not cover BUG-007** —
  the docstring says so and names the strict assertion to add with that fix.
- **INFO-005**: `report_suite` now fails a suite that exits 0 having reported
  no tests, and the "`all passed` means one pass" fudge that masked it is gone.
  Precedent: `test_popup_bridge` already refuses to run nothing.
- **INFO-006**: the three text-scraping tests now drive `_force_kill`,
  `stop()` and `_on_finished` against a fake `QProcess` — taskkill's argv and
  pid, the escalation timer's interval and target, a pending restart routed
  through the port check, and a port that never frees ending in `error`.

All five rewritten guards were checked **red-first**: with the behaviour
removed (taskkill disabled, the escalation deleted, `_on_finished` calling
`start()`, the 0/0 guard disabled, an unreviewed field added) each FAILS.
Script: `~/.hermes/cache/scratch/lph-verify/negctl_tests.py`. Full suite after:
**17/17 suites, 220 tests, exit 0**.

CI on the same commit: the first Windows attempt failed **4 window tests + all
3 popup tests** with page-load errors ("the start page never rendered", "page
never loaded") while everything else passed; `gh run rerun --failed` came back
**17/17 green**. Both webview suites failing at once ("page never loaded" is
Chromium, not an assertion), with every non-webview suite green and no code
change between the attempts, points at the runner's Chromium rather than the
tests — the audit hit the same class of failure (`0xC0000409` at QtWebEngine
startup) on its own Windows host. Treat it as a flake to watch, not a
regression: rerun before investigating.

Still open from the audit and deliberately untouched: BUG-001/002/003/004/
005/007 above, plus INFO-001 (unsanitised release-asset name), INFO-002
(`kill -0` does not exist on Windows), INFO-003 (LaunchAgent quoting in dev
mode), INFO-004 (IPv4-only port probe).

## Release 0.6.2 (2026-10-19): Rename was a no-op — DONE

Reported by the user: *"selecting rename for a project apparently doesn't do
anything in the side bar view? I click it and nothing happens."*

**Cause.** Sidebar rows were built without `Qt.ItemIsEditable`.
`QListWidgetItem` is not editable by default, so `editItem()` — exactly what
the context menu's **Rename…** calls — was refused by Qt and dropped, with
only `edit: editing failed` on the console. Double-click failed identically,
so the hint *"Double-click a name to rename it"* described something that
could not happen. Note the asymmetry that hid it:

- `test_renaming_a_project_in_the_sidebar_sticks` passed throughout, because
  it writes through the model (`item.setData(_NAME_ROLE, …)`) and never asks
  the view for an editor. **A model-level test cannot see a view-level
  refusal** — the guard has to drive `editItem()`.

**Fix** (`hub/window.py`): `item.setFlags(item.flags() | Qt.ItemIsEditable)`
on row creation, and the menu focuses the list (`self.list.setFocus()`) before
starting the editor so typing lands in it. Probe: flags 53 → 55, `editItem()`
reaches `EditingState`, editor pre-filled with the stored name.

**Guard:** `test_rename_opens_an_editor_and_saves_the_new_name` asserts the
flag, calls `editItem()` like the menu does, checks the editor text, then
commits through the delegate (`setModelData`) and asserts the registry and the
row text. Proven red first: *"the sidebar row is not editable, so Rename can
only do nothing"*.

Local suite: **16/16 suites, 207 tests** (`full-suite-0.6.2.out`); window
suite 21 (was 20). Released 2026-10-19 night: `bc8295c` (fix + version bump) →
tag `v0.6.2` → tag run `#39377116143` green → notes applied → README pins
bumped in a `[skip ci]` docs commit. Note the CI quirk seen twice now: the
`Publish to the GitHub release` job finishes before `Tests (windows-latest)`,
so a published release is not yet a passed run — watch the run, not the assets.

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

## Release 0.6.0 (2026-10-19): an update is a restart, not a drag — DONE

User request: *"For the install part is there any way that instead of click
to drag over to applications folder I just need to restart the app?"*

The app never overwrites itself while running. `hub/selfupdate.py` (new,
243 lines) stages the `.app` out of the downloaded dmg (`hdiutil attach` →
`ditto` → `detach`, quarantine dropped), writes a `/bin/sh` script and quits.
The script waits for the pid (bounded, `timeout_s=60`), copies the new bundle
to a sibling `.<name>.incoming-<stamp>` so the final step is a rename, moves
the old bundle to `~/.Trash/<App> (before <old version>) <stamp>.app`, renames
the new one in and `/usr/bin/open`s it. A failed copy or rename restores the
old bundle and opens it; nothing is deleted; every step appends to
`~/Library/Logs/LocalProjectHub/update.log`.

- `hub/update_dialog.py` — `install_now` signal; `show_preparing(version)`
  ("Unpacking the new version…") and `show_ready_to_install(version)` with one
  primary button, **Restart and Install**; `_on_primary` dispatches it. On
  macOS `show_available` now says the download is "downloaded and prepared"
  and a restart finishes it (Windows keeps the installer wording).
- `hub/window.py` — after a verified download, macOS calls
  `_prepare_macos_update(dmg, release)` (gated by `can_self_install()`; any
  failure logs `[hub] could not prepare the update: …`, shows the error and
  falls back to the old `_launch_installer` hand-off). `_restart_and_install`
  schedules the swap, closes the dialog and the window 100 ms later; if the
  script cannot start, the user gets a warning naming the staged path.
- Guard tests: `tests/test_selfupdate.py` (new, 7 tests) runs the REAL script
  against throwaway bundles — a swap keeps the old copy in the Trash, a
  missing staged bundle changes nothing, an app that will not exit is waited
  for only so long, an unwritable folder leaves the old bundle in place, plus
  the dialog contract. Off macOS (CI is Windows) the same tests assert the
  module refuses loudly and that every guard is still in the script text.
  `test_window_e2e.py` gained a case that drives the staged flow through the
  dialog and asserts the window closes so the swap can run.

Released 2026-10-19: `ec655a2` (feature + version bump + README/DEVELOPMENT
text) → tag `v0.6.0` at `ec655a2` → tag run `#39368233018` (four jobs, incl.
publish) green → notes applied from scratch `release-notes-0.6.0.md` → README
Download pins bumped in the `[skip ci]` docs commit.

**Not yet exercised against a real signed bundle:** the swap is proven with a
real `hdiutil` dmg round-trip plus a synthetic `Fake Hub.app`; the first true
run is the user's next update *after* he is on 0.6.0. The installed
`/Applications` copy must never be modified by a probe.

## Release 0.6.1 (2026-10-19): the detected URL belongs to the right project — DONE

Reported by someone else (2026-10-19): *"A detected dashboard URL is written
to the active project, not the one that printed it"* — `hub/window.py:1191,
1292-1309`. Real, and older than 0.6.0: `_on_url_detected` had read
`self.active_id` since URL auto-detection landed (`1ce591b`), so a project
running in the background that announced its own address wrote it onto the
selected project. The announcer kept no URL (asked again next launch) and the
selected project's dashboard could point at the wrong server.

Fix (`fd69d81`): the `url_detected` signal is connected with the emitting
project's id (`lambda u, p=pid: self._on_url_detected(u, p)`), the handler
takes `pid: str | None = None` (falls back to `active_id` for direct calls)
and only calls `_show_dashboard` when that project is the one in view — a
background project's address is saved and used on selection, so it never
pulls the window to its tab. A user-typed URL still wins. The reporter's
second range (`_on_port_conflict_from_output`) was already owner-aware and is
unchanged.

Guard test: `test_a_detected_url_is_saved_to_the_project_that_printed_it`
(two projects, Alpha selected, Beta emits, registry must move on Beta only).
It failed on the old code with "the URL was not saved to the project that
printed it".

Released 2026-10-19: `fd69d81` (fix + version bump) → tag `v0.6.1` → tag run
`#39372517820` (four jobs incl. publish) green → notes applied from
`release-notes-0.6.1.md` → README pins bumped in the `[skip ci]` docs commit.

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

1. **The self-installing update — PROVEN on 2026-10-19 22:29.** The user's
   0.6.0 → 0.6.1 update ran the whole flow unaided: `update.log` shows
   `waiting for pid 155 to exit` → `copying` → `moving the old version to the
   Trash` → `installed; reopening`, and the installed bundle is 0.6.1. The
   0.6.1 → 0.6.2 update did the same at 10:14 on 2026-10-20 (pid 9030, old
   copy `… (before 0.6.1) 2026-10-20 10-14-33-9030.app`), so the path has now
   worked twice from a released build. **0.6.2 → 0.7.0 also completed** at
   12:24 on 2026-10-20 (pid 96146, old copy
   `Local Project Hub (before 0.6.2) 2026-10-20 12-24-04-96146.app` in the
   Trash), as rechecked from the live bundle, log and old copy on 2026-10-24.
   What is still unproven is the **failure** half — restore-and-reopen when the copy or
   the rename fails — because it has never happened outside a test. If a future
   update leaves the app closed, look for the old bundle in `~/.Trash` and read
   the log's last line; `did not exit` means the quit path, anything else means
   the swap.
2. **"One-click update" smoothness, what's left** — unsigned-build warnings
   need paid certificates (messaging only until then); whether an
   app-downloaded MSI triggers SmartScreen is unverified — check before
   "fixing". The macOS drag-to-Applications path now exists only as the
   fallback for the cases where self-install cannot work (source run,
   unwritable `/Applications`, a staging error).
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
QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py   # 17 suites, serial, ~14 min
.hubenv/bin/python tests/test_workflow_yaml.py                  # workflow guards, seconds
~/.local/bin/gh release list                   # v0.7.0 = Latest (verified)
~/.local/bin/gh run list --branch main --limit 5
# bundle probe (see the TLS section): rebuild, clone the built .app,
# drop in probe_main.py, run the stub — app_fetch_latest_release must say
# OK (this is how 0.4.2 was proven)
```

_Maintenance: at the end of a work session, move finished items out of Open
threads, add new ones, and refresh the status block._
