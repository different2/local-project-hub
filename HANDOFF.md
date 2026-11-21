# HANDOFF — Local Project Hub

## CURRENT: macOS-only 0.7.5 release authorized; packaging in progress

The user explicitly chose 'Build and publish a macOS-only update; I'll install it'.
Build from the committed bugfix source with version0.7.5, using an isolated fresh
packaging worktree/environment. Preserve the existing older build environment,
generated app, old DMG and installed0.7.4 copy. No Linux/Windows builds, broad test
rerun or additional review; no installation or restart of the user's running app.
This is an explicit macOS-only exception to the normal all-platform publication
process: keep the generic three-asset CI gate unchanged, suppress tag CI and
publish manually only after actual Mac artifact/runtime/digest acceptance.
README retains Windows/Linux0.7.4 download links so a Mac-only latest release
cannot break their downloads. Durable progress/evidence is under
`~/.local/share/local-project-hub/acceptance/macos-0.7.5/`.

## PRIOR SOURCE CHECKPOINT — retained context

The user narrowed the last step to repair/test the IPv6 concern only, without
cycling through the other tests. That scope is completed. The user subsequently
authorized committing/pushing the changes to GitHub and deferring any additional
Linux/Windows work. This commit is the source checkpoint; resolve its exact ID
with `git log -1`. No full-suite rerun or further review was performed for the last
correction. The installed app is unchanged. Historical review verdicts stay
preserved rather than being rewritten as clear.

- Repo: `/Users/iff/Documents/Programming/local-project-hub`
- Verification baseline HEAD: `a8f057a6375086e8b6342b0432332f932973e634`;
  this source checkpoint commits the tested working-tree Python bytes.
- Installed Hub **0.7.4**, live registry, managed sources/environments unchanged.
- Commit/push to the existing GitHub repository is authorized. No release,
  installation or deliberate live app/dashboard restart permission.
- Preserve unrelated untracked `graphify-out/`, sandboxing and human Git attribution.
- Never run `tests/run_all.py` top-level on this Mac: its unrelated-port cleanup is
  unsafe. Verification uses isolated `run_case.py` / `run_strict_matrix.py` below.
- Never merge `diagnose/windows-msi-native` or `diagnose/linux-input` into main.

## Goal and correct target

Fix Restart/new-port reconnection, wrong-project navigation after collisions,
save crash/duplicate pickers, and Ctrl-C-like Stop. “Sphere view” means
observability's `modelview.py::exportObject`, NOT the standalone Sphere project.
Managed projects are read-only. Never independently start/stop/restart
`obs_live.py`, read/crash-test its active capture, or reopen its closed storage work.

## Platform scope and DEFERRED work — resume only when the user has budget

- URL provenance/discovery, endpoint ownership, retry budgets, static-entry handling
  and download-wrapper ownership are shared source, not macOS-only implementations.
  Their inclusion in Linux/Windows builds is not native verification on those OSes.
- SIGINT-first Stop is POSIX (macOS/Linux). Windows retains its existing
  terminate/taskkill console-tree fallback; equivalent graceful Ctrl-C delivery
  was NOT added.
- DEFERRED: native Linux/Windows validation of restart/new-port and IPv4/IPv6
  recovery, captured-child cleanup, selected-tab navigation and single-picker
  download lifetime behavior with each target's Qt runtime. Fix only platform
  differences actually reproduced then; do not assume these shared fixes fail.
- DEFERRED: investigate/implement a safe Windows graceful-console-interrupt path
  if still wanted. Do not infer it exists from the POSIX implementation.
- User explicitly requested no extra platform implementation or test cycle now.
  This push uses `[skip ci]` to avoid starting the existing Linux/Windows matrix;
  no CI success or new installer acceptance is claimed for this checkpoint.

## Accepted execution — do not rerun on delayed notifications

Private evidence root (never upload wholesale):
`~/.local/share/local-project-hub/acceptance/bugfixes-2026-11-20/`

- **Before the last IPv6 repair**, `regression-review-fixes-01`: 460 PASS + 3 platform
  SKIP, all 463 registered identities exactly once, 170 children/all raw exits 0.
  `independent-review-fixes-reconciliation.json` rereads every full child log and
  receipt; no missing/extra/duplicate identity, source drift or protected drift.
  All49 Hub/tests hashes stayed unchanged during that run. Its full-suite result
  is not current-byte coverage for the later scoped repair.
- Native Cocoa/Python 3.11, installed Qt6.9.3 libraries imported read-only; no retries
  or unsafe top-level housekeeping. `proc_fa533cdf3d1d` is consumed, not running.
- Existing Python3.9.6/Qt6.7.3: `review-py39-process-final` passes all 42 process
  cases; five new URL/ownership cases also passed during the correction phase.
  Earlier 41-case process coverage is superseded, not additional coverage.
- Correct native observability inspector baseline: three actual saves plus clean
  fixture confirmation, one NSSavePanel per export, valid stable profile, UTF-8
  output, raw exit0. Removing the ownership repair fails profile validity/raw1.
  Native labels: `native-observability-02`, `native-observability-clean`,
  `native-observability-mutant`. No captures or live dashboard were used. These are
  prior native gates on unchanged download/renderer code, not installed-app signoff.
- Copies of 11 real registrations preserved 77 launch-field comparisons without
  modifying the live registry or launching managed projects. Existing environments
  were not upgraded. Failed matrices, fixture diagnostics and wrong-target probes
  remain preserved; `checkpoint.md` has their clearly superseded history.

## Review history and subsequent targeted repair

Original review: canonical message86518 under `review-source-01/`; its original
`concerns_found` verdict and exact findings remain unchanged. The user then chose:
“Fix — reproduce and address all three, test, then run one scoped re-review.”

Correction re-review: `deleg_56872162` / `sa-0-15369dbf`, completed native session
`20261121_042200_139da9`, canonical message86852. Files under `review-corrections-01/`:
`final-canonical-verdict.txt`, `final-native-audit.json`, `final-validation.json`.
Audit: all 4447 actual packet lines covered; only allowed packet/mandatory-skill/
gate calls; no boundary violations or candidate/protected changes. Native requested
model/provider/reported endpoint match parent `gpt-6.1-sol` / `openai-codex`; actual
upstream is not independently disclosed. Isolation was policy-constrained, not
capability-enforced. No reviewer is running. The one approved re-review is used.

The reviewer marks the original cleanup-loss, rejected-legacy latch and mixed-owner
acceptance mechanisms **resolved**. Targeted reproductions/positives/controls are
mapped in `review-fix-progress.json`, including Stop→Start cleanup and its complete
INT+TERM/reap budget. At that checkpoint it reported this additional defect:

**MEDIUM, confidence 94% — Hostname rejection cannot recover an IPv6-only owned backend.**
With owned `::1:P` and foreign `127.0.0.1:P`, fallback incorrectly manufactured
an IPv4 URL after rejecting ambiguous localhost. The user then explicitly asked
to repair/test this concern only. A focused regression failed with that exact
wrong-family URL, and now passes after the repair. Discovery verifies each
loopback literal's owners and emits a bracketed IPv6 URL when appropriate.
Both rejection consumers share one per-run deadline; a new launch resets it.

`ipv6-focused-final/{manifest.json,summary.json,closeout.json}`: **7 unique focused
cases, 9 positive executions/all raw exits0**, covering auto/legacy records in both
family directions, deadline reuse/reset, expiry/cancellation. The two reverse
cases also pass on existing Python3.9.6/Qt6.7.3. Three copied-source controls
restore the separate defects and fail the exact intended assertions/raw1.
All49 source hashes stayed frozen during these focused checks, all16 protected
hashes match and no matching owned test processes remain. These final bytes are
targeted-tested, not fully rerun or independently re-reviewed, per user direction.

## Stop here unless the user asks for more

The repair/test and source-checkpoint scope is complete. No reviewer or QA job is
running. Do not start another review, full suite, platform work, release,
installation or live dashboard restart merely because old history mentions it.

External `checkpoint.md` CURRENT section controls after interruptions. Preserve
both frozen review packets and source vectors; do not overwrite accepted evidence.
The original release handoff is preserved at
[docs/context/handoff-release-0.7.4-before-bugfixes-2026-11-21.md](docs/context/handoff-release-0.7.4-before-bugfixes-2026-11-21.md).
The prior longer bugfix handoff is preserved as `handoff-before-correction-review-result.md`
in the private evidence root (SHA256 `fbf9cd5bc9a240c43a6ca0284b73018ce14ad8387214bf72976fd1e7892fac3d`).
