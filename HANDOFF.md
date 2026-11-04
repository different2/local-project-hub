# HANDOFF — Local Project Hub

## Read this checkpoint first, not the historical archive

The owner authorized rebuilding and publishing the downloadable **0.7.4** releases.
This does **not** authorize installing/restarting the user's Hub, managed services,
or changing managed sources, dependencies, registry or virtual environments.
No further independent review. Preserve human attribution and sandbox/raw-exit gates.

Repo: `/Users/iff/Documents/Programming/local-project-hub`
GitHub: https://github.com/different2/local-project-hub

## Frozen identities — don't replace these with a later docs-only HEAD

- Release source **`052033e46ed014482b3ecf7c0fee337beb9b91cd`**, pushed/read back.
- Runtime/build settings are byte-identical to **`c37f9d573a1d5a044248d3fe67143681110889f8`**.
  Independent `git diff --name-only c37f9d5 052033e` contains only `HANDOFF.md` and
  `tests/test_browser_controls.py`. The latter waits for the real Reload-ready state
  after Forward; title arrival precedes load completion. Its changed case passed
  on native Mac Python3.11 and3.9.6. Do not imply the full Mac suite ran on052033e.
- Full source/build run **41869103664** is **failed overall** (Ubuntu input cases).
  Both Windows full source matrices and both native builders succeeded. A successful
  build or scoped QA job is not whole-release acceptance.
- Public latest was **v0.7.3** at the Nov4 10:04PST check. No0.7.4 tag/release has
  been published and the user's app has not been installed/restarted.

## Accepted Windows replacement — finished, do not rerun the old rejected MSI

- Source run41869103664: Windows2022 and2025 **each437 unique identities =430PASS +
  7SKIP;152 actual children/all0/clean**. Parent independently reconciled the full
  source registry against each raw artifact (no missing/duplicate verdicts).
- Actual MSI:218460768 bytes, SHA-256
  **`de6c3d2a5040b84d377cd0335c3e79a65cb938c70b90cefbea663521907b89eb`**.
  Build job126710974806; artifact13343587457. Raw ZIP/API metadata retained.
- Native acceptance **41880047847**, QA commit
  `083f71f7b8710af6a6499cabf4260016eba19985`, reference digest
  `a9a88442c3aff9efee5287a1c8e72972dc282449a5961798e874b2ec38ba66b6`.
- Parent re-derived **all23 exact installed CRLF hashes from immutable Git blobs**
  and matched membership; no normalized or arbitrary EOL variants. Actual separate
  WebEngine6.12.0.140, Qt modules/helper/resources, source-hidden installed launch,
  nonce DOM/native pixels, wrong-DOM refusal and renderer sandbox guards passed.
  Screenshot independently viewed. Install/normal WM_CLOSE/reaped exit/uninstall all0;
  no forced cleanup/survivors/errors; source and MSI preserved.
- **Never merge `diagnose/windows-msi-native` or `diagnose/linux-input` into main.**
  Private verified `windows-qa-083f71f.bundle` preserves observer source/history.
  Calibration:30 helper/workflow tests plus pixel controls, all raw0. No review.

## Open gates, in priority order

### 1. Linux full source under an actually selected native display backend

Actual052033e APT-installed DEB smoke passed: source hidden, nonce/native X11 pixels,
sandbox evidence, normal close0/no survivors/source restored; wrong-text control
rejected. Its ordinary full source job failed raw GUI input cases, not packaging.
The workflow starts Xvfb, but Qt still inherits its **offscreen** default.

Bounded unchanged-case calibration **41881546465** compared bare Qt and the exact
app cases on Python3.12.15/16 and offscreen/xcb. The retained observations show an
app input failure on3.12.15/offscreen; both xcb groups passed. This does not establish
a3.12.16 regression or a product fix. A green diagnostic means collection finished.

A **strict full unchanged052033e source** run has now been dispatched from temporary
`diagnose/linux-input` workflow **`af3fdb7b697776a4e4a5a321033919742a6373f0`**:
Ubuntu24.04/Python3.12.16/Qt6.7.3, explicit `QT_QPA_PLATFORM=xcb` under Xvfb.
Recover that new run ID, watch once, then download `full-source-linux-xcb` and
reconcile every identity/raw exit before accepting it. No assertion, sandbox,
source or exit-policy changes. Never merge the temporary transport into main.

### 2. Mac actual-package interaction still needs a usable approved input route

Full native Cocoa **c37** source accepted:437 identities=434PASS+3SKIP;152 actual
children/all0/clean, unchanged source. Actual DMG263983761 bytes, SHA-256
`24f0f49fbdcfc57d3fb9e95501ac72e0a4bdc749ec17fadd45471a0fb5704281`.
Read-only mount/copy, bundle source/membership/dependency/helper inspection passed.

The owned DMG-derived app painted its initial nonce fixture. CDP trusted pointer
observed Replay navigation, but native background pixels stayed stale; native
Back/Forward/Reload, download Save/exact bytes/result/Close are not accepted yet.
The foreground tool session expired. **One permission question timed out**; do not
bypass the session grant or re-ask automatically. This is an unverified interaction,
not a confirmed application painting defect. Needs owner permission/help for a brief
isolated-package foreground check. Never activate or replace the installed Hub.

All owned attempt2 app/backend/renderer/harness processes exited. The scratch harness
used invalid `NSRunningApplication.terminate_`; the correct no-argument selector is
`terminate()`, which requested normal quit successfully. Its failed report is not
native package acceptance; keep failed/invalid attempts separate from green results.

### 3. Publish only after all acceptance gates

Publish the immutable accepted installers, validate the actual private draft before
promotion, then read back public metadata, anonymous downloads/digests/links and a
read-only updater offer. Never overwrite published assets. No install/restart.
Use explicit source identity; `[skip ci]` can suppress tag-triggered builds, so do
not assume tagging rebuilt anything. Build/test dispatches must not publish.

## What changed in the app / attribution correction

Selected-tab Back/Forward/Reload preserve project navigation/popup semantics.
Generic native browser downloads handle blob/raw text, progress, results and close
cancellation. Windows explicitly includes split WebEngine6.12.0.140. c37 guards Qt-
deleted watched download profiles with destruction tracking/isValid. Retained
RED/GREEN controls cover lifetime, actual load readiness and PASS+raw-exit7 refusal.

The owner fixed observability-project errors and said those were that project's
fault, not Hub's. Do not revive that report as an outstanding Hub defect. The
independently reproduced browser defects remain valid fixes. No managed-source edits.

## Durable evidence and protections

Private root (never upload wholesale):
`~/.local/share/local-project-hub/acceptance/release-0.7.4-2026-11-04/`
Read **CURRENT.json** for current exact handles; prior ledger retained separately.
- `candidate3/windows-{binding,native}/`, `windows-independent-acceptance.json`.
- `candidate3/windows-source-reconciliation.json`, separate per-host raw audits.
- `candidate3/linux-runtime/`, `source-ubuntu/`, `linux-input-calibration/`.
- `candidate2/macos-source/`, `macos-stages.json`, `installers/`, native failed attempts.
- `candidate3/protected-after-native.json` equals the protected pre-native baseline
  for installed app Info.plist/executable and the user's registry.

**Never run `tests/run_all.py` top-level on this Mac**: unrelated-port cleanup has no
ownership. Full Mac transport changes unsafe housekeeping only, retaining all real
assertions/child exits. Existing `.hubenv`/`.buildenv` remain untouched Qt6.7.3;
release Qt6.9.3 envs are owned scratch builds. Preserve untracked `graphify-out/`,
`.githooks`, human acknowledgements, failed artifacts and source provenance.
Previous checkpoint: `git show 052033e:HANDOFF.md`; historical archive is reference only.
