# HANDOFF — Local Project Hub

## Read this current checkpoint first, not the historical archive

**The owner authorized rebuilding and publishing the downloadable0.7.4 releases.**
That supersedes the earlier publication hold. It does **not** authorize installing
or restarting the user's app, changing managed projects/venvs, or restarting live
services. Keep human attribution, renderer sandboxing, strict byte/raw-exit gates,
and immutable published assets. No further independent review was requested.

Repo: `/Users/iff/Documents/Programming/local-project-hub`
GitHub: https://github.com/different2/local-project-hub

## Frozen candidate and current acceptance

- **Release/runtime source: `c37f9d573a1d5a044248d3fe67143681110889f8`.**
  Pushed and independently read back on Nov4 after a confirmed GitHub outage.
  Later checkpoint-only commits are not the tested runtime or release target.
- **Fresh full CI/build run:41862859859**, explicit `workflow_dispatch`, exactc37.
  https://github.com/different2/local-project-hub/actions/runs/41862859859
  Build-job waiter: `proc_460fc066bff0`; private receipt below. Native Windows,
  fresh Linux/source-matrix acceptance and publication are still pending.
- **Mac full native Cocoa source accepted:**437 registered identities =434PASS +
  3SKIP;152 actual children, all OS exits0. Exact registry/counts, no duplicates,
  missing verdicts, callback tracebacks or lifetime warnings; unchanged source.
  The disclosed scratch adapter replaces unrelated-port housekeeping only.
- **Actual Mac DMG built and container-verified**,263983761 bytes, SHA-256
  `24f0f49fbdcfc57d3fb9e95501ac72e0a4bdc749ec17fadd45471a0fb5704281`.
  Its packaged-app native interaction/normal-close gate is still pending.
- **Public latest remainsv0.7.3**, freshly checked Nov4. Nothing new has been
  published or installed. Do not describe source/build success as release success.

## What the source contains

- Selected-tab Back/Forward/Reload, including popups/private profiles; page-defined
  same-tab/new-tab behavior is preserved and Reload does not restart a backend.
- Generic Chromium downloads, including blob/raw-text exports, with native Save
  choice, progress, concise completion/error, owner logging and cancellation.
- Windows package/CI explicitly include the separate
  `PySide6-WebEngine==6.12.0.140`, alongside Qt/PySide6/shiboken6.12.0.
- c37 adds safe destruction tracking/isValid checks for Qt-deleted download profiles.
  Full first-candidate Ubuntu evidence exposed this real shutdown defect.
- Popup tests now observe loadFinished before clicking; a streamed header/body
  fixture proves title-before-body lost the old click. The isolation contract uses
  the real platform backend/PTY/PID and rejects PASS with raw child exit7.
- Each correction has retained RED/GREEN evidence. New lifetime/raw-exit guards
  also pass on actual Python3.9.6/Qt6.9.3 (targeted floor checks, not a full3.9 run).

The owner corrected the earlier observability attribution: he fixed project-side
errors and said they were the observability project's fault, not Hub's. Do not
continue treating that historical report as an outstanding Hub defect. The
independently reproduced browser/navigation/download defects remain valid fixes.

## Windows QA: keep separate from main

**Never merge `diagnose/windows-msi-native` into main.** Owned preparation tree:
`~/.hermes/cache/scratch/lph-release-v074-20261104/windows-qa/`.
The original child completed generic binding tooling; a recovery child hit429
mid-TDD. Parent observed the remaining public/self-hosted controls RED, completed
two guard conditions, then reran30 actual helper/workflow tests plus pixel controls,
all raw0. This is QA-tool calibration, not Windows runtime acceptance or review.

The final `tools/windows_msi_candidate_reference.json` is intentionally absent
until the actual new MSI exists. Follow `tools/windows_msi_observer_README.md`:
bind clean immutablec37 source, exact run/attempt/Windows job/artifact ID/API JSON,
raw artifact ZIP/digest and independently measured MSI digest/size. Commit/push
only the QA transport/reference; dispatch with its explicit reference digest.
Require exact installed Python membership/bytes, separate WebEngine version and
actual modules/helper/resources, source-hidden installed launch, nonce DOM/native
pixels/wrong-DOM controls, sandbox evidence, normal WM_CLOSE/OS exit0, no forced
cleanup/survivors, exact-ProductCode uninstall and source/MSI preservation.
Never normalize installed bytes or widen accepted EOL variants.

## Superseded attempts — retain, do not redispatch as the current candidate

- First new source6b88eff/run41804484621 failed full acceptance: Ubuntu profile
  shutdown; Mac popup/isolation fixture; Windows2022 popup fixture failures.
  Windows2025 source and both builders passed, not the overall release.
- Its218460768-byte MSI, SHA-256
  `bb2d252cec20fce93fd095a55053616d9a172bd8f8f7856c7775da30541f2a11`,
  is superseded. The delayed successful old Mac build notification is likewise
  not acceptance ofc37; candidate2 has its own accepted source/build receipts.
- Original77aaa18 MSI/run40931912478 passed strict22-file installed parity after
  exact CRLF reference correction, then correctly refused missing WebEngine before
  launch. Never re-run that rejected installer unchanged or relax its guards.

## Durable checkpoint and next actions

Private owner-only evidence root (never upload its contents wholesale):
`~/.local/share/local-project-hub/acceptance/release-0.7.4-2026-11-04/`

Read **CURRENT.json** first for updated process/run handles and stage receipts.
- `candidate2/macos-source/`: complete accepted registry/raw logs/reconciliation.
- `candidate2/macos-stages.json`, `candidate2/installers/`: actual Mac build/digest.
- `candidate2/ci-build-status.json`: exact fresh job-level status.
- `regressions/`: failed controls and GREEN corrections, kept separately.
- `windows-observer-prep/`, `windows-qa-parent-validation/`: recovered tooling/tests.
- `protected-before-native-c37.json`: installed app/registry hashes match original
  baseline; native checks must preserve them.

Next: accept fresh builders; bind/run native Windows QA; inspect/launch the exact
Mac DMG copy with private state; accept Linux installed-runtime/source artifacts;
then stage/validate/promote the immutable release and verify anonymous downloads,
hashes and a read-only installed-updater offer. Never install/restart the user app.
Use an explicit source SHA: c37 carries `[skip ci]`, so a tag push must not be
assumed to execute anything. Builds/source gates use explicit dispatch; publication
must not bypass any pending gate.

**Never run `tests/run_all.py` top-level on this Mac:** its unrelated-port killer
still lacks fixture ownership. Full native verification used the recorded safety
adapter and strict actual child exits. Default repo `.hubenv`/`.buildenv` remain
older Qt6.7.3; fresh release Qt6.9.3 envs are isolated scratch builds, not an update
to the user's environments. Preserve untracked `graphify-out/`, `.githooks`, real
human acknowledgements and all historical failures. No blanket restore/removal.

Older checkpoint details remain in `git show c37f9d5:HANDOFF.md`; the older
[historical archive](docs/HANDOFF_HISTORY_2026-10-29.md) is reference only.
