# HANDOFF — Local Project Hub

## CURRENT: macOS-only 0.7.5 published; owner will install

- Release: https://github.com/different2/local-project-hub/releases/tag/v0.7.5
  (release ID `453837365`, published `2026-11-21T16:59:47Z`).
- Frozen release/tag source: `5188888783cf33c580c40f395a30ac359c440864`;
  bugfix source checkpoint: `38958e28c547185bbdeaeb0385cbe403d3126eef`.
  A later documentation-only main commit is NOT the tested release target.
- Only `Local.Project.Hub.dmg` was published, size `264011225` bytes, SHA-256
  `df841cb9cd0842146606b8de4318e57fa716be173d80fe6d28bc87ec4c24d093`.
- Mac artifact, real native runtime and anonymous public acceptance passed.
  Read-only code from the actual installed0.7.4 bundle sees `v0.7.5`, reports a
  newer compatible installer and downloads the exact tested bytes; correct digest
  accepted, wrong digest rejected, real downloaded DMG `hdiutil verify` exit0.
  `installed-updater-after-publication.json` / `proc_5bd8fda5a6b5` raw exit0.
  All saved release jobs are completed, not pending reruns.
- Installed Hub **0.7.4** is untouched. The user explicitly chose “Build and
  publish a macOS-only update; I'll install it.” Do not install or restart the
  user's app/dashboard. Source, release publication and installation are separate.
- Windows/Linux installers remain **0.7.4**, with working pinned README links.
  No new Windows/Linux builds, native QA or implementation were requested.

## Accepted gates and scope

Private release evidence (never upload wholesale):
`~/.local/share/local-project-hub/acceptance/macos-0.7.5/`

- Fresh pinned Python3.11/Qt6.9.3 release environment and detached source worktree;
  original build environment, old generated app/DMGs and installed copy preserved.
- Version checks (3) and targeted README/download-contract checks (2) passed.
  No new full source matrix or further independent review was run.
- `build-receipt.json`: source-bound DMG, real `hdiutil verify`, macOS12 floor,
  bundle version0.7.5 and build counter1, all23 application source files matched.
- `runtime-01/summary.json`: the exact DMG mounted read-only, copied out and
  detached; actual scratch `.app` executable launched with isolated native home,
  state/cache/temp and normal renderer sandboxing. Bundled Qt/PySide6 are6.9.3;
  main/physical WebEngine helpers have arm64, valid signatures and macOS12 floors.
- Native pixels showed the correct synthetic dashboard nonce and interaction
  count1. Wrong-content control failed as intended. A background native Stop
  action delivered Ctrl-C to the owned backend, which recorded/flushed its exit.
  Real app and supervisor exits0; no owned survivors or protected hash changes.
  Post-Stop capture predates repaint and is NOT stopped-UI evidence.
- Bundled Store loaded a copied real registry:11 records ×7 launch fields
  preserved; no managed command ran and the live registry was not edited.
- `draft-acceptance.json`: exact private draft/asset/source label and GitHub
  digest checked against local DMG, including wrong-digest rejection. Exact
  publication readback is `published-readback.json`.
- Normal three-platform CI publication gate remains unchanged. This was the
  user's explicit manual macOS-only exception; branch/tag use `[skip ci]`.
  No new Linux/Windows CI success is claimed.

Preparation failures remain evidence, not successes: the old environment failed
Qt-pin preflight; first packaging wrapper exited1 after `create` regenerated four
tracked activation/config path fields in the scratch tree. Their exact diff and
generated copies were preserved, only those files restored, then packaging alone
resumed successfully. First public-offer probe exited1 because its test expected
`0.7.5` while installed `parse_release` preserves the literal `v0.7.5`; diagnostic
showed `is_newer:true`. Only the probe expectation changed; updater code did not.

## Source/review history — retained, not reopened

The final IPv6 repair was deliberately focused-tested, not full-suite retested or
independently re-reviewed. Original/correction review verdicts remain
`concerns_found`; do not rewrite them as clear. Before that last correction the
full source matrix passed460+3skip/463 identities and170 raw-zero children.
Final scoped evidence records7 unique cases/9 positive raw-zero executions plus
three failing copied-source controls. Earlier native observability Sphere export
acceptance used the actual `modelview.py::exportObject` on synthetic data, not the
standalone Sphere project and not captures. Detailed evidence remains in
`~/.local/share/local-project-hub/acceptance/bugfixes-2026-11-20/`.

The complete preceding handoff is preserved byte-for-byte at
[the pre-publication context archive](docs/context/handoff-source-fixes-before-macos-0.7.5-publication.md)
(SHA-256 `b4ea576746878318ee435f4f3335c0241c93d0a4499d27bedf1ded5f23e9d026`).
The older0.7.4 release handoff remains linked there.

## Deferred work / safety boundaries

- Shared URL/discovery/ownership/retry/static-entry/download fixes are not proof
  of native Linux/Windows compatibility. When the user has budget, validate
  restart/IPv4+IPv6 recovery, cleanup, navigation and picker lifetime on each
  runtime; repair reproduced differences only. Windows graceful console Ctrl-C
  is still deferred; its existing terminate/taskkill path remains.
- Managed sources, dependencies/environments, live registry and active captures
  stay read-only. Never independently start/stop/restart `obs_live.py` or reopen
  completed capture/storage work. Tablet work remains on hold.
- Never run `tests/run_all.py` top-level on this Mac: its unrelated-port cleanup
  is unsafe. Do not repeat full regression/review because old history mentions it.
- Preserve unrelated untracked `graphify-out/`, sandboxing, human attribution and
  original release tags. Never merge `diagnose/windows-msi-native` or
  `diagnose/linux-input` into main.
- Reconcile saved handles with durable receipts before reporting a job as active.
  Release acceptance is complete. No further work is pending except the owner's
  installation and explicitly deferred platform follow-up.
