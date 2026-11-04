# HANDOFF — Local Project Hub

## Read this checkpoint first; not the historical archive

**Publication and installed-app changes are ON HOLD.** Do not tag, draft or
publish0.7.4, install over or restart the user's app, or restart managed services
without new authorization. Public latest is still **v0.7.3** (rechecked Nov4).
The owner authorized fixing the Hub, not editing managed HTML/scripts/venvs.
Preserve the live registry, unrelated services, human attribution, renderer
sandboxing and immutable published installers. No further independent review
rounds were requested; direct regression checks are not an independent review.

Repo: `/Users/iff/Documents/Programming/local-project-hub`
GitHub: https://github.com/different2/local-project-hub

- **Current targeted-tested source: `276a26176e38679a356eb8238e022ab1947883b4`.**
  `2d91841` adds browser history/downloads; `276a261` fixes Windows packaging.
  Subsequent documentation-only commits do not change that tested source.
- **Previous full-platform-tested runtime: `77aaa1877c3c586634f572ede63f9bf7095abb08`.**
  Its installers do NOT contain the new browser fixes or Windows dependency fix.
  Do not transfer its full-suite/package acceptance to the newer source.
- Provider interruption left the changes uncommitted and the root handoff stale.
  Recovery finished Nov4. Old Oct29 scratch environments/evidence have expired;
  recovered and fresh evidence now lives outside pruneable scratch storage.
- [docs/HANDOFF_HISTORY_2026-10-29.md](docs/HANDOFF_HISTORY_2026-10-29.md)
  preserves older history. Read it only for a specific historical question.

## Current verified work

### Browser navigation and downloads — fixed in source, not installed

- Back/Forward/Reload are visible toolbar/menu actions for the selected browser
  tab, including popups/private profiles. Starter/nonbrowser controls disable.
  Page-defined same-tab links remain same-tab. Reload never restarts a backend.
- `hub/browser_downloads.py` handles actual WebEngine downloads, including blob
  raw-text exports, with native Save choice, progress/completion/failure,
  owning-project logging, and cancellation/lifetime handling. Files are never
  auto-opened; no page-accessible Python filesystem bridge was added.
- Fresh native Cocoa targeted verification against source276a261:

  | Interpreter / Qt | PASS identities | Raw child processes | Exits |
  |---|---:|---:|---|
  | Python3.11 / Qt6.9.3 | 40 | 20 | all0 |
  | Python3.9.6 / Qt6.9.3 | 33 | 13 | all0 |

  Both include all9 browser cases and all21 workflow guards;3.11 also covers
  popup ownership/nesting/deletion. The3.9 run is targeted floor coverage, not
  a complete3.9 suite. Exact planned identities/verdicts, callback errors and
  profile/QProcess lifetime warnings were checked, not just headline totals.
- Fresh original-source controls reproduce both reports on77aaa18: missing Back
  and a real blob request without a Save offer. Both exit1 with the exact expected
  assertion; their failed observations are retained separately from green tests.
- Actual native Save picker was driven,52 exact UTF-8 bytes saved, fresh native
  screenshot shows **Download saved** and the full destination, Close worked,
  normal fixture teardown and actual OS exit0. No owned test service was left.

### Windows MSI source parity — settled; real packaging defect remains

TEMP branch **`diagnose/windows-msi-native` must NEVER merge into main**.
QA-only head is **`6f036c126a7149eac48a78651ce30960ff2802a7`**.
Actual original-MSI attempt **40931912478** completed FAILURE:
https://github.com/different2/local-project-hub/actions/runs/40931912478

- All22 installed runtime files match an explicit immutable expected reference.
  The only canonical-source/payload difference is LF→CRLF:8,795 inserted CR
  bytes, no other byte changes. Raw canonical/expected/installed manifests were
  retained. Comparison still enforces exact bytes and Python-file membership;
  installed files were NOT normalized and arbitrary EOL variants are not accepted.
- Real `msiexec /i` and exact-ProductCode `/x` both exited0. Original source and
  MSI preservation passed; no remaining related product/launcher was reported.
- The app was **NOT LAUNCHED**. After parity passed, the gate correctly stopped:
  `SmokeError: installed WebEngine helper missing/ambiguous: []`.
- This is a real bundle-dependency omission, not another reason to relax the
  observer. Qt6.12 splits WebEngine into **`PySide6-WebEngine==6.12.0.140`**.
  `PySide6==6.12.0` installs it transitively in CI; Essentials+Addons alone in the
  old Briefcase package did not. Original read-only MSI inventory also lacked
  WebEngine modules/helper/resource packs. Official package metadata is retained.
- Repository package requirements and Windows test/build install commands now
  explicitly pin that split wheel. Mac/Linux requirements/support floors stay
  unchanged.21 workflow tests per interpreter and6 isolated config controls pass;
  all12 immutable-reference observer helper tests pass in their proper Git layout.
  A failed helper replay from a plain file copy is retained as a harness-layout
  failure, not a new product failure or accepted helper result.

**Next Windows gate:** build a replacement MSI bound to the corrected source,
then inspect the actual package and repeat native installed-runtime acceptance.
The old MSI is immutable and rejected; do not redispatch it unchanged. A new
candidate needs a newly bound exact payload reference, not the hard-pinned77aaa18
vector or a normalization fallback. Check the split distribution's exact
6.12.0.140 version separately from Qt6.12.0. Require actual installed WebEngine,
source/Qt parity, nonce DOM/native pixels, wrong-DOM rejection, sandbox evidence,
normal WM_CLOSE/zero exit, no forced cleanup/survivors and exact uninstall.
Only free public Windows2025 runners are authorized; never run Windows binaries
on this Mac. No replacement build, new full matrix or publication has run yet.

### Unexpected observability backend exit — cause still OPEN

Recovered installed-terminal evidence confirms two unrequested code15 exits on
Oct28 at21:47:54 and22:30:44, without a preceding Hub terminating line. A deliberate
stop at22:19:57 has that line and is correctly not classified as an error.
Sender/cause is unknown; do not equate a currently live server with refuting the
report, or claim a selection regression explains the historical terminations.

The strengthened real sidebar select-away/back test preserves uploaded DOM,
manager/QProcess/PID, no finished event, and an independent fresh HTTP200 response.
The unrequested-termination positive control still reports genuine failure.
Both pass on3.11 and3.9. Managed sources/services were not changed or restarted.

**Test-runner safety:** `tests/run_all.py` still has an unrelated-port killer:
its source-literal inventory can include8787 and cleanup lacks fixture ownership.
This is a demonstrated hazard, NOT proof it caused those historical exits. Do
not run its top-level main on this Mac. Scoped checks used only `run_one`, isolated
homes/state/temp, serial native children and strict raw exits; no port cleanup.

## Durable evidence and recovery tools

Current private evidence root (owner-only; never add its contents to public Git):
`~/.local/share/local-project-hub/acceptance/browser-followup-2026-11-03/`

- `native-py311-final/`, `native-py39-final/`: plans, raw logs/exits/source hashes.
- `negative-baseline/`: actual original-source failures, separate from green tests.
- `native-ui/`: observations, exact saved export, native screenshots and normal exit.
- `msi-attempt-4/`: recovered actual run40931912478 report/install/uninstall logs.
- `qa-source/` and verified `qa-source-6f036c1.bundle`: exact QA tooling/history.
- `windows-proof-v2/`: raw installed parity,12 helper checks, official PyPI metadata
  and6 isolated dependency controls. `windows-proof/` retains the failed replay.
- `historical-observability-terminal.txt`: original installed-app exit evidence.
- `CHECKPOINT.md`, verification summary and file manifest: current acceptance scope.

Previous durable evidence remains under `acceptance/platforms-77aaa18/`,
`callback-77aaa18-targeted/` and `windows-msi-77aaa18-incomplete/`.
Prior full-source CI40845715963 accepted425 identities per platform: Mac/Linux
422PASS+3SKIP, each Windows418PASS+7SKIP,142 actual children/all0 per platform.
Mac/Linux installed-package acceptance belongs to that old source only.
The original MSI SHA256 remains
`ae539e3596f391b5f7dd272b024610ad7b4abf2c5b4c601aaa743ffa894eea2d`.

Fresh test envs are scratch-only under `~/.hermes/cache/scratch/lph-resume-ywdcm4ch/`
(`py311/bin/python`, `py39/bin/python`), both Qt6.9.3. They may expire. Reproduction
transport sources are preserved with evidence; no browser profiles/venvs were
archived. Existing repo `.hubenv`/`.buildenv` still contain Qt6.7.3 and were NOT
updated: default `run.sh` is not the fresh verified runtime. `gh` is
`/Users/iff/.local/bin/gh`; installed Hub PID14530 still dates from Oct27.

Keep Tahir's human acknowledgement and `.githooks`. No history rewrite or extra
review is authorized. Earlier Linux nested-popup -11 failures remain failures:
later clean runs do not explain their cause. Preserve `graphify-out/`; it is
untracked and predates these changes, so it is navigation data, not current
runtime acceptance. Do not auto-refresh its models or ingest old history to resume.
