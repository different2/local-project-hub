# HANDOFF — Local Project Hub

## Current correction — Mac accessibility runtime (supersedes checkpoints below)

The owner chose **"Test the Mac runtime fix, then finish the release"** after
the actual0.7.2 Mac installer crashed on native row changes following AX cell
inspection. Bare native Qt reproduced it; mouse-only/model-move and stable-row
workarounds did not fix it and were removed. Ordinary pixel-only packaged drag
worked but did NOT clear accessibility. The native fault resolves to
`QMacAccessibilityElement dealloc+44`, strongly matching QTBUG-134784.

Mac-only pins are now6.9.3, including the upstream cached-element ownership fix;
Windows stays6.12.0/Linux6.7.3/macOS minimum12.0/Python3.9 source support retained.
In the SAME minimized native control with AX observation and stable C++ item
identities, actual process exits are6.7.3=-11 versus6.9.3=0. A first scratch
probe used ephemeral Python-wrapper ids, raised an invalid identity assertion,
and was rejected/stopped; only the corrected comparison is acceptance evidence.
The application code remains reviewed `b6dec8c`, without a sidebar shim or any
sandbox/accessibility bypass. New pin guard failed RED against6.7.3; all20
workflow guards and20 packaging/helper cases pass under the6.9.3 Python3.11
environment; ordinary3.9 packaging suite still gives15PASS/5explicitSKIP/exit0.

Previous release prep was reviewed/committed/pushed as `a1dcd80`. Its strict
local source run and all3 remote source jobs reconciled21suites/360uniqueIDs and
111clean actual runner children each. Its original DMG is retained as historical
evidence, not the new runtime installer. The current runtime correction still
needs bounded review/freeze/commit, real rebuilt Mac DMG with native AX+drag and
clean shutdown, fresh strict source acceptance at the final source, then the
immutable tag/private exact-SHA Mac input and Windows/Linux installer gates.
No0.7.2 tag/publication yet; installed user app is untouched0.7.0/build1.
Scratch evidence/status: `~/.hermes/cache/scratch/lph-release-0.7.2/STATUS.md`.

## Active release preparation — v0.7.2 (not published yet)

The owner authorized publishing the saved sidebar-ordering update and asked
for macOS builds/tests to run locally, not on a hosted Mac runner. Version is
now 0.7.2. The application code below remains unchanged from reviewed/tested
`b6dec8c`; this release preparation changes packaging transport and guards.

- Hosted `build-macos` is removed. The existing Ubuntu24.04 publisher runs
  only on a tag push, after source tests/native builders, and requires the local DMG
  in a private draft with an exact `source:<candidate SHA>` asset label.
  It validates draft/tag/repo/URL/upload state/digest and downloaded full bytes
  before release upload. It never compiles or executes a Mac binary. Private
  drafts need push access, so reuse the publisher's existing privileged token
  rather than adding a second privileged transport job.
- `publish.needs` requires tests/Windows/Ubuntu builders; the local Mac input
  is an unskippable step before any release upload, not a dangling job name.
  Three complete stable installers are still mandatory. Upload retries stay
  private-only, preserve the Mac source label and resolve drafts by release ID.
  Manual dispatches, including tag refs, cannot stage or publish a release.
- Local `tools/build_macos_release.py v0.7.2 --output <directory>` requires the
  existing pinned Python3.11 .buildenv and clean tracked source. It checks the
  real built app's short version, independent numeric build counter, macOS12
  floor, hub metadata, renderer helper and byte-identical source before packaging;
  then collects without clobbering and invokes real `hdiutil verify`.
- Tight checks: 20 release-artifact/helper cases, 20 workflow guards and all
  three version cases pass. Six explicit unsafe workflow fixture controls are
  rejected. These are pure/transport checks, NOT new installer/runtime signoff.
- The first release-preparation review found a Python3.9 developer-test
  regression. Owner authorized fixing it. Shared receipt hashing now uses a
  portable streaming SHA-256; only genuine Python3.11 packaging checks skip on
  older Python. The retained ordinary runner passes15 cases/skips5 on3.9;
  Python3.11 runs all20. Application support/code and build pins are unchanged.
- During preflight the new helper's counter-equals-release assumption was caught:
  the actual previous DMG has short version0.7.1/build counter1. A missing-behavior
  RED then passing numeric-counter guard fixes that assumption. Mocked test roots
  were canonicalized for /var versus /private/var aliases. Use explicit
  `TMPDIR=/Users/iff/.hermes/cache/scratch` for local verification commands.
- Worktree/evidence: `~/.hermes/cache/scratch/lph-release-0.7.2/`, branch
  `release/0.7.2`. No v0.7.2 tag, draft, source push, actual Mac build or installer
  execution has happened at this checkpoint. Installed Mac app is still0.7.0/build1.

**NEXT:** review/freeze this preparation, build/test the real DMG locally,
then push the exact source candidate and require Windows2022/2025 + Ubuntu source
CI. Only after that green run and actual Mac acceptance, push a NEW immutable
v0.7.2 tag, immediately create its PRIVATE draft and upload the verified Mac DMG
with its source label. The tag pipeline builds Windows/Ubuntu, stages the Mac
input in the publisher, validates all three assets and promotes latest. Verify real downloads
and the update offer without installing it. See DEVELOPMENT.md for exact steps.

## Previous local-source checkpoint — saved project ordering (then unreleased)

The Projects sidebar can be rearranged by dragging rows. Order is stored in
its existing registry array, survives restarting/renaming/export to a fresh
registry, and new projects append at the bottom. No schema bump or project
configuration rewrite is needed. The UI saves stable IDs after `rowsMoved`
through a queued connection; a failed write restores saved order and reports
an error in the status bar and hub log.

Targeted tests have passed for persistence, legacy files, invalid orders,
atomic save failure, visible widget order, inline rename, and moving a real
running HTTP project without changing its PID, tab or HTTP response. A native
Cocoa test window was exposed; real mouse/drag/drop events, changed visible
order and saved registry order were observed. Earlier automation no-ops were
not counted as successful drags; its tracker supplied no native exit status.
Final verification on source commit
`b6dec8c372aebfd85d2884e82d860a200b87e3bc`:

- Full strict macOS source run: **21 suites, 340 passed, 4 skipped, 0 failed**.
  All **344 unique source test IDs** were accounted for exactly once; no
  missing, extra or duplicate verdicts. All **111 actual test-process exits**
  were zero, with strict exit 0 and unchanged tested source.
- The pure Store suite also passes under the existing Python 3.9.6 development
  interpreter. GUI/full-suite execution used Python 3.11.10 and Qt 6.7.3.
- Three deliberate controls were caught: alphabetical re-sorting, disconnected
  move-save wiring, and missing UI rollback. Production code was restored and
  the positive paths rerun before the complete suite.
- Review Checkpoint `deleg_33f4c049` returned **clear**, with no findings.
  It reviewed the complete changed diff, complete Store and supplied Window
  consumers through a frozen packet, not the whole repository or an
  independent test run. Transcript audit confirmed only that packet read and
  mandatory read-only skill loads. No new Windows/Linux binary or installer
  acceptance is claimed for this source-only UI change.
- Evidence: `~/.hermes/cache/scratch/lph-project-order/strict-macos/`,
  `full-identity-audit.json`, `mutation-results.json`, `review-result.json`,
  `review-transcript-audit.json`, and native observations/screenshots.
  Tests use isolated fixture registries and processes.

**This is a source update, not a published release or installed-app update.**
The installed app, user registry, published v0.7.1 assets, tag, download links,
platform dependencies and contributor history are unchanged. The release
closeout below describes v0.7.1; it does not claim this new UI is in that release.

## Previous release closeout — v0.7.1 is public; Linux/latest-download deliverables verified

**This section supersedes every older checkpoint below.** Release:
https://github.com/different2/local-project-hub/releases/tag/v0.7.1

- User's Linux release and always-latest front-page requests are delivered.
  Release ID423602327 is public/non-prerelease and was read back as `latest`.
- Immutable annotated tag `v0.7.1` (object
  `ba3646d6e7d3c096d7231ad6da86ae7573837f07`) peels to tested installer source
  `b8d6e1b7039a2a0a70d6302ba0d2e025aa4cb6ac`. No force push or retag occurred.
- Main was fast-forwarded and pushed through release-plumbing correction
  `6cbf16f329cd903e7d045b5f4c9c628a7d6c054b`. Its application code, version and
  packaging configuration match the released tag. Only the publisher helper,
  workflow, associated pure guards and handoff differ after that tag.
- The remote main README was read back byte-for-byte and contains exactly the
  three stable `/releases/latest/download/...` links. Each was anonymously
  downloaded in full, returned200/non-HTML, resolved through v0.7.1, and matched
  its published API size and SHA-256. Links were integrated only after those
  assets were live and checked.
- Installed `/Applications/Local Project Hub.app` remains **0.7.0/build1**;
  installation was not requested or performed. Shared user projects/config/art
  were not changed. Original Tahir Masood174e90c attribution/history is retained.

### Delivered platforms and acceptance

Linux is **Ubuntu24.04 LTS amd64 only**, native Briefcase0.4.6/systemPython3.12,
Qt6.7.3. It is not a generic Linux/ARM/AppImage release. Updates initially use
manual download/APT. macOS stays Apple silicon/Qt6.7.3 with an effective12.0
bundle floor; Windows x64 uses Qt6.12.0. No sandbox bypass or global security
policy weakening was introduced.

| Environment at released b8d6e1b | Suites | Passed | Skipped | Failed | Actual child exits |
|---|---:|---:|---:|---:|---|
| Local macOS source/offscreen |21/21|329|4|0|106/106 zero|
| Ubuntu24.04 GitHub |21/21|330|3|0|106/106 zero|
| Windows2022 GitHub |21/21|326|7|0|106/106 zero|
| Windows2025 GitHub |21/21|326|7|0|106/106 zero|

Every environment's333 unique case identities were independently reconciled
against its exact source registry; no duplicate/missing verdict or nonzero child
was hidden. Full manual CI40214609068 passed. Tagged CI40219691409 separately
passed all test/build jobs; its publication-only failure and recovery are below.
The installed .deb was launched outside its checkout with isolated state and
source hidden: exact nonce DOM plus actual native screenshot pixels, renderer
NoNewPrivs1/Seccomp2, deliberately wrong-DOM rejection, clean owned shutdown and
source restoration all verified. Actual tagged Mac DMG checksum/mount/version12.0
floor/helper/codesign and Windows MSI container metadata were checked. Full
anonymous published-file hashes match the same tagged build outputs.

### Published installer identities

| Asset | SHA-256 |
|---|---|
|Local.Project.Hub.dmg|9e2431de4c481fbcf95a01080c66628ecb37d08bb89933a6e69533c675f5c99a|
|Local.Project.Hub.msi|f7359def96af16663370fec59f2b5c7ccdaa8f1c6697c3fef185f2fd4d3721b7|
|Local.Project.Hub.Ubuntu-24.04-amd64.deb|a99c24fe074ef6cef220c799d65a403b1610832702f92d11a353780217ac114d|

### Publication recovery, review and remaining limits

GitHub draft423602327 used an `untagged-*` preview reference; the published-tag
REST lookup returned404. Historical tagged CI therefore remains red at its
publisher, not falsely relabelled green. The release-ID/strict-draft-preview
correction6cbf16f was developed RED/GREEN against the real untouched draft API
payload,19 workflow guards,5 artifact/audit controls and targeted negative
mutations. The exact repaired publisher step was then executed: complete private
metadata/digests verified BEFORE promotion, same release ID read back public with
strict version-tag URLs AFTER promotion. Same files, no rebuilding/retagging or
bypass. Release notes and latest status were read back after publication.

Two bounded packet-only review checkpoints returned clear; JSON and read-only
activity were audited. Their coverage is limited, not exhaustive. The later
publisher transport correction additionally has live API recovery evidence and
pure regression controls.

Native macOS top-level on-screen exposure remains an older disclosed limit;
offscreen source tests do not prove new physical-window exposure. One earlier
Linux offscreen child segfaulted after PASS;60 targeted repeats did not reproduce
it, and both subsequent full released-source runs were clean. Its cause was NOT
declared fixed; the strict audit still rejects every nonzero child. No physical
Linux desktop/compositor or arbitrary-distro compatibility is claimed.

Post-integration main CI40225868881 at6cbf16f completed **SUCCESS**. Its actual
artifacts were independently checked against334 current-source case identities
in21 suites per image: Ubuntu331 passed/3 skipped, Windows2022 and2025 each327
passed/7 skipped, zero failures/missing/duplicates, all106 actual children per
image exited0. This includes the publisher recovery's additional pure test.
Build/publication jobs correctly skipped on an ordinary main push; all released
installers had already passed their tagged builds and runtime/metadata gates.
Only HANDOFF.md differs after the tested6cbf16f code tree. The final docs-only
closeout uses `[skip ci]`; no verification, release or link work remains open.

Evidence is in `~/.hermes/cache/scratch/lph-linux-release/`: acceptance-b8d6e1b.json,
tag-0.7.1-acceptance.json, publication-recovery/{before,release,published,latest}.json,
anonymous-latest-downloads-0.7.1.json, main-frontpage-0.7.1-readback.json and review
results. Git/release/CI identifiers above remain durable if scratch expires.

## Historical checkpoints — retained verbatim; not current pending work

_Resume checkpoint — **v0.7.0 IS LIVE: opening a project no
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
PR #3's two source fixes are merged; the installed release is unchanged. Read the
current task and integration status below; the older audit triage is historical._

## Current task — first Linux release and always-latest downloads (in progress)

User explicitly authorized Linux distribution and a new release on 2026-10-25;
this supersedes the previous task's Linux exclusion/no-release restriction.
No replacement of the installed Mac app was requested. The planned coherent
next version is 0.7.1, including the already-merged source fixes on all platforms.

Worktree `~/.hermes/cache/scratch/lph-linux-release/tree`, branch
`feat/linux-release`; scratch `STATUS.md` carries detailed run/head/evidence state.
The first Linux binary is narrowly scoped to Ubuntu 24.04 amd64, native-system
Briefcase 0.4.6, system Python 3.12 and Qt 6.7.3. AppImage is discouraged by the
pinned builder for binary-wheel GUI stacks; no all-distro support is claimed.
macOS remains Qt 6.7.3/minimum12.0 and Windows Qt 6.12.0; no sandbox bypass.

Initial guards reproduced both missing features RED; current workflow guards
and ten isolated negative controls pass. Stable installer names and the
complete-asset/digest draft-before-publication gate have pure controls too.
Preflight CI40195477042 at86b0865 built and APT-installed the real .deb. Its
downloaded control/payload, actual version/Qt metadata, ELF architecture and
browser resources were independently inspected (artifact12599174943).
Runtime CI40197205064 at6f18bcd rendered the installed dashboard visibly with
non-root NoNewPrivs1/Seccomp2 and clean WM_DELETE_WINDOW shutdown/source restore.
It failed in the observer: Chromium rewrote /proc cmdline into one process-title
field, while the verifier required an exact separate renderer-flag element.
Parent preserved raw fields and added flag-only token classification (never
execution), with RED/GREEN real-format and hidden-bypass controls plus saved
process-snapshot replay. Fresh full CI40199127356 at464a95d then passed the
actual installed positive AND deliberately wrong-DOM controls: native screenshot
visually inspected, renderer3784 UID1001/NoNewPrivs1/Seccomp2, both clean
WM_DELETE_WINDOW exit0/no owned survivors/source restored. All three installers
built. Both Windows strict suites passed326/7 with106 actual child exits0 each.
The Linux source suite failed: its updater fixture assumed non-Mac meant MSI,
and one re-selection test segfaulted after printing PASS. The strict audit did
not hide that crash. Publication remains blocked on a fresh clean full run.

Tight actual-Ubuntu diagnosis40214120292 at24120fa compared62 child launches:
the original updater expectation failed, the platform-aware expectation passed,
and20 re-selection repetitions each under stock offscreen, XCB and explicit
DeferredDelete all exited0. The shutdown crash was NOT reproduced or declared
fixed; no speculative cleanup/backend change was shipped. TEMP diagnostic code
is retired outside the repository and the complete release workflow restored.
The first TEMP run40213908259 failed before tests because shallow checkout lacked
the baseline object; full-history diagnostic checkout corrected that fixture.

The actual downloaded Mac DMG advertised11.0, despite a configured12.0 floor:
Briefcase0.4.6 reads `min_os_version`, not `minimum_system_version`. A red-first
guard now checks the effective option, and the Mac build checks its real
Info.plist before packaging. Actual rebuilt DMG verification is still required.
The updater test now asserts Linux's visible dismissible/manual result rather
than offering an MSI; Mac/Windows download assertions remain unchanged. No hub
application code changed. Independent frozen464a95d packet review returned clear;
JSON validated, transcript read-only (only mandatory review-skill load). Updated
full acceptance and one bounded correction review remain pending.
Do NOT equate a packaging-only manual green with runtime or release acceptance.

The external installed-app smoke harness from local delegate2a83988 is integrated;
parent corrected its literal-version assumption using the real metadata-derived
app source (RED then17pure tests GREEN). The unittest controls adapt to one
Linux-only PASS case; other OSes skip this observer case. No product hooks or
Mac GUI execution occurred. Strict CI auditing records every real child exit.
README latest links are staged on this branch, not yet main: retain the old
working front page until the new assets are actually published. No tag/release
has been created. Linux updates are initially APT/manual, not one-click in-app.

### Tagged release: publication-transport recovery

Tag `v0.7.1` points to tested `b8d6e1b`; it is not rewritten. Tagged CI
40219691409 passed all three builders and Linux/Windows2022/Windows2025 full
strict regressions (333 unique cases and106 actual clean children per image).
Its publisher created draft423602327 and uploaded all three matching installers,
then failed before publication: GitHub draft metadata uses an `untagged-*`
preview URL and cannot be fetched through the published-tag REST endpoint.
The real draft is readable by release ID; its actual assets/digests were checked
against all three downloaded tagged build outputs. No installer rebuild is needed.

A red-first transport correction resolves `databaseId` via `gh release view`,
reads the same release ID before/after promotion, and validates a draft's exact
own preview reference without relaxing public version-tag URL checks. Five
artifact/audit controls,19 workflow guards and draft/public negative mutations
pass, including the unchanged real draft API payload. Tagged installer/app source
remains b8d6e1b; the correction is release plumbing for recovery/future builds.
The historical tag run remains red at publication, not misreported green.
Equivalent private verification must run before manually promoting that existing
draft; then public metadata, all file hashes and anonymous latest links must be
verified before integrating main. Source application and installed Mac app remain
unchanged. Detailed current state is in scratch STATUS.md.

## Historical: PR #3 merged — both requested source fixes complete

This section supersedes the older deferred/known-issue statuses below.
Linux was explicitly excluded. No release, version tag, package installation,
or replacement of the installed app was requested or performed.

[PR #3](https://github.com/different2/local-project-hub/pull/3) merged at
`2026-10-25T09:45:42Z`, merge commit
`3ecbc1178581e7ce9e0ee95b514d620dc8c68f4a`, from exact tested head
`4aa2d55f45bb704da8ea51ff770f82910a75b113`.
The merge's parents and complete Git tree were read back: its tree is identical
to the tested head. The primary project folder was fast-forwarded to that merge.
Only documentation closeout follows it; source/tests/workflow remain the tested
versions. Original contributor history and README acknowledgement are retained.

### Fixes and evidence

- **Restart false error:** the old child's termination is requested for Restart
  as well as Stop. Intent survives the port-free wait and resets before the
  replacement starts; unexpected exits and a genuinely failing replacement
  remain errors. Real QAction/QProcess/terminal regressions and remove-fix,
  sticky-intent, blanket-code15 and stale-finish controls were exercised.
- **Newer Windows renderer compatibility:** Windows selects the coordinated
  Qt/PySide6 6.12.0 stack. macOS retains 6.7.3 and its macOS 12.0 support floor.
  Windows tests ran on actual GitHub Windows runners, never locally on this Mac.
  Default renderer sandboxing remains enabled.
- **CI coverage/logging:** ordinary full tests cover pinned Windows 2022/2025.
  Log names use `matrix.os`, so both immutable artifacts are retained. The old
  shared-name defect was proven RED and the corrected real uploads both passed.
  TEMP workflows/helpers were removed; diagnostic files remain archived outside
  the repository. Superseded run40175476590 was deliberately canceled, not
  labelled an application failure.
- Independent packet-only review and its one bounded CI correction review were
  clear (`deleg_98befe9b`, `deleg_517e1bbb`, gpt-6.1-sol/openai-codex); JSON was
  validated and reviewer activity audited. Configuration guards pass on actual
  Python 3.11/3.9 with load-bearing negative controls.

### Final verification at 4aa2d55

| Platform | Suites | Passed | Skipped | Failed / blocked / not-run |
|---|---:|---:|---:|---:|
| macOS, local Python 3.11 / Qt 6.7.3 | 19/19 | 320 | 3 | 0 / 0 / 0 |
| Windows 2022, GitHub / Qt 6.12.0 | 19/19 | 317 | 6 | 0 / 0 / 0 |
| Windows 2025, GitHub / Qt 6.12.0 | 19/19 | 317 | 6 | 0 / 0 / 0 |

Every suite identity and total was independently checked against the registered
suite list and 323 source-defined test slots per platform. The Mac strict audit
captured all 104 actual child exits and verified every one was zero; no printed
PASS was allowed to conceal a shutdown crash.

[Final ordinary CI40178221090](https://github.com/different2/local-project-hub/actions/runs/40178221090)
passed both test jobs and uploads. Separate artifacts were downloaded/read:
`test-log-windows-2022` ID12593971668 and `test-log-windows-2025` ID12594114520.
The earlier [old/new controls40168797374](https://github.com/different2/local-project-hub/actions/runs/40168797374)
remain supporting evidence, not substitutes for that full product run.

Raw evidence/report: `~/.hermes/cache/scratch/lph-followup-two-bugs/`, especially
`verification-4aa2d55.json`, `strict-macos-4aa2d55/`, and
`windows-4aa2d55/{windows-2022,windows-2025}/test-output.log`.
Automatic main CI40181982514 was queued at closeout on the merge's identical
already-tested tree; it is a repeat, not being reported as another completed pass.

### Explicit limits / installed version

Cocoa lifecycle/DOM/PID/HTTP/listener/terminal assertions pass with no false error
and fixture cleanup confirmed. The strict native smoke nevertheless exits 1
because top-level `isExposed` is false: **full on-screen exposure is unverified**.
This is a disclosed verification limitation, not a confirmed product regression;
do not keep trying activation flags or claim a full visible-native pass.

Latest release remains **v0.7.0**; installed app is **0.7.0, build 1** (read back). These
source fixes are not installed in that older app. Rebuilt packages, installation,
real OS login integration and Linux are not newly verified here; unknowns are
not confirmed bugs. Releasing/updating the installed copy is a separate action.


## Historical: PR #2 merged (2026-10-24 — follow-ups superseded by PR #3 above)

[PR #2](https://github.com/different2/local-project-hub/pull/2) was merged at
`2026-10-25T00:44:45Z` with merge commit
`143bd36862c53ebf460b1adfa24f8a3d34127a14`, after both final platform gates passed.
The primary project folder was fast-forwarded to the merged source. Issue #1
was automatically closed by the merge; its closed state was read back.

### Attribution and review

- Tahir Masood / [@tahirmasood2](https://github.com/tahirmasood2)'s original
  `174e90c55b696f592d58ed83f5f5e8552a51242a` remains unchanged, including
  `Co-authored-by: CommandCodeBot <noreply@commandcode.ai>`. It and the tested
  head are ancestors of remote main. No squash, force push, reauthoring or
  contributor-branch deletion was used. The README acknowledgement is on main.
- Separate maintainer commits correct TIME_WAIT restart refusal, explicit and
  unknown endpoint scope throughout delayed conflict retries, coherent process
  ancestry/identity capture, and cross-platform test fixtures. Load-bearing
  RED/GREEN and remove-fix controls were observed. Independent review checkpoints
  ran and their confirmed findings were addressed; do not start another review loop.
- [Formal approval and final evidence](https://github.com/different2/local-project-hub/pull/2#pullrequestreview-5640804357)
  and [merged/credit summary](https://github.com/different2/local-project-hub/pull/2#issuecomment-6391578599)
  were posted and read back.

### Final pre-merge verification

Tested head: `9d4e75ad5fc82470d3436ff25a45a75317f36825`. The merge differs from
that tree **only in HANDOFF.md**; runtime, tests, dependencies and workflows match.
Both full logs were parsed against all 19 registered suite identities, with
unique rows and independently summed totals matching each runner summary.

| Platform | Suites | Passed | Skipped | Failed / blocked / not-run |
|---|---:|---:|---:|---:|
| macOS, Python 3.11 / PySide6 6.7.3 | 19/19 | 310 | 3 | 0 / 0 / 0 |
| Windows 2022 CI, Python 3.11 / PySide6 6.7.3 | 19/19 | 307 | 6 | 0 / 0 / 0 |

- [Ordinary Windows CI 40145634640](https://github.com/different2/local-project-hub/actions/runs/40145634640)
  passed, including all 28 window and 3 popup tests. This is a real full product
  check, not a diagnostic completion badge.
- Native Cocoa Start → HTTP 200/rendered dashboard → Restart/new PID/rendered
  dashboard → Stop/tab closure/no listener also passed on the tested head;
  screenshots were inspected and fixture listeners cleaned up.
- Evidence under `~/.hermes/cache/scratch/lph-pr2-final/`:
  `macos-9d4e75a-py311.log`, `windows-9d4e75a/test-output.log`,
  `verification-9d4e75a.json`, and `native-9d4e75a/` (JSON plus four screenshots).

### Windows CI correction and limits

The user required fixing CI before merge. Bare Qt and unchanged main reproduced
renderer crashes on the moving Windows 2025 image. Identical-version controlled
run [40144633615](https://github.com/different2/local-project-hub/actions/runs/40144633615)
observed 15/15 healthy cases on Windows 2022 with normal sandboxing; the newer
image passed only its four sandbox-disabled cases. CI therefore pins
`windows-2022` and guards that image with a regression test. The guard went RED,
GREEN and RED under the exact old-config mutation, then GREEN on restoration;
all 10 workflow guards passed actual Python 3.9 and 3.11. Production sandboxing
and dependency pins were not weakened or changed. Both TEMP diagnostic files
were archived and removed; their source remains in Git history (`19da3e6`).

**Not verified here:** native Linux, rebuilt DMG/MSI packages, real OS login-item
integration, or a solution for Qt sandbox compatibility on the newer Windows
image. Do not claim the image pin fixes shipped Windows 2025 compatibility.
A misleading error log during an otherwise successful intentional code15 Restart
was separately reproduced on unchanged main with the same native harness. It is
a **pre-existing, nonblocking follow-up**, not fixed in this PR. Baseline evidence
is in `native-baseline-main/`; the shared `lph-pr2-review/native-*` paths now contain
that baseline, so use archived sibling filenames for the candidate screenshots.

**No release, tag or installation was performed.** Installed app metadata was
read back as **0.7.0, build 1** after the merge; source integration does not update
that installed application.

### Post-merge main CI — PASSED; integration closed out

[Run 40147888074](https://github.com/different2/local-project-hub/actions/runs/40147888074)
completed successfully on exact merge `143bd36`, job `Tests (windows-2022)`.
Its own downloaded artifact reports **19/19 suites, 307 passed, 6 skipped,
zero failures/blocked/not-run**. All 19 unique registered suite identities and
row totals were independently validated; the result matches the passing PR
run. Full log: `lph-pr2-final/windows-main-143bd36/test-output.log`.
The notified watcher exited 0; no verification remains in flight for this merge.

Subsequent main commits update **HANDOFF.md only**, marked `[skip ci]`; the
runtime/test/dependency/workflow tree remains identical to the tested head.
Build/publish jobs were skipped, as expected for a branch push, not verified.
No source-integration action remains pending. A new release, installer testing,
additional platform validation or the documented follow-up bugs are separate
work; do not release or install anything automatically.

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

## Historical resume checkpoint (2026-10-24 — superseded by PR integration above)

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

## Historical forensic audit triage (2026-10-20, before PR #2)

The statuses and file:line references below describe the pre-contribution tree,
not the merged source. PR #2 subsequently implemented the remediation; use the
current integration/verification section above rather than repeating these fixes.

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

## Previously tracked follow-ups (not revalidated by PR #2)

These are retained context, not claims that every old symptom still reproduces
after the source integration. The current status above takes precedence;
revalidate a historical concern before changing code for it.

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
