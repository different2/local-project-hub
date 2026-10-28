# HANDOFF — Local Project Hub

## CURRENT — Static HTML entry + private autosave, unreleased (2026-10-28)

The owner reported a standalone HTML project opening as a directory listing,
and explicitly required changes in Hub, NOT edits to the original project.
After the page opened, testing exposed its nonstandard `window.storage` API;
the owner approved Hub-side autosave compatibility as well.

### Implemented
- `hub/static_site.py` resolves only recognized local Python `http.server`
  entry pages. File… selection persists as `entry_file` through Add/Edit/Store.
  Legacy root URLs infer only a sole visible top-level HTML file without an
  index. Explicit routes/query/fragment/credentials, another port/bind address,
  ambiguous folders, path escapes and unknown servers are left alone. Navigation,
  readiness and Open in browser share the effective URL; saved URLs stay exact.
- `hub/html_storage.py` supplies private `window.storage.get/set` only inside
  eligible local static sites. Each stable project ID gets a separate persistent
  Chromium profile under the registry's `html-storage/` directory. Injection is
  main-frame/main-world and origin-limited; native browser same-origin rules and
  quota errors remain. There is no Python filesystem bridge, shared/cloud store,
  external-browser adapter, new dependency or sandbox bypass.
- Static popups inherit their opener's profile. Ordinary non-static projects
  retain the default profile; creating/selecting a tab still starts nothing.
  Original project HTML, scripts, dependencies and saved live registrations must
  remain untouched. No per-project CSS/JS source edits are an acceptable workaround.

### Targeted evidence already collected
- Real native Cocoa source execution of the unchanged original Trade Ledger:
  upload UI and synthetic CSV review form visibly rendered. Its actual Save &
  mark reviewed handler reports saved. Normal app quit followed by a DIFFERENT
  OS process, same isolated registry/profile and re-uploaded synthetic CSV,
  restores one reviewed trade and zero left in queue.
- Removing entry resolution reproduces the directory listing; removing storage
  compatibility reproduces the original page's save-failed message. Both controls
  exit1 as expected; positive native write/restart executions exit0 and stop their
  owned servers. Original HTML hashes match before/after.
- Three new native regressions pass on Python3.9/Qt6.9.3: legacy entry/navigation/
  readiness/external target/no reload; picked-file save/Edit/reopen/folder-change;
  private get/set/reload/different-project same-origin isolation and origin guard.
  Pure detection/static-origin tests pass under Python3.9 and3.11.
- Early native presentation captures were stale, not acceptance; retained the
  failed images and improved the observer. An early observer lost its script
  during navigation; an initial Qt collection method name was corrected against
  actual Qt6 introspection. Do not erase these failed attempts.

### Verified native source acceptance
- Runtime source commit: `8aa4bca643294d6f9549ca42f5bc728946246f92`.
  Independent frozen-delta review returned clear; its schema, boolean gate and
  packet/candidate hashes were checked. This is scoped source review, not
  installer or untested-platform approval.
- Full native Cocoa source suite: **391 unique test identities,388PASS,
  3platformSKIP,0FAIL;129actual child exits0**. Every identity reconciles exactly
  against the source registry, with no missing/extra/duplicate verdicts and no
  premature Chromium-profile-release warnings. The canonical strict runner
  passed through the documented safety transport without changing assertions.
- All221 snapshotted original-project entries still match; no extra original
  project files appeared. The real saved registration resolves the intended
  page without mutation. Live registry and installed Info.plist hashes match
  their protected snapshots. Final process inspection found no owned QA survivors.
- Private durable evidence, including raw per-child logs, native control and
  write/restart PNGs, review packet/verdict and reconciled acceptance:
  `~/.local/share/local-project-hub/acceptance/static-html-20261028T101955Z/`.
  Its177copied evidence files were hash-verified; no browser caches/profiles,
  actual registry contents or credentials were archived.

### Not released or installed
- No push, new version, release, installer build or installation is authorized by
  this bug-fix request. The installed app was read back as0.7.3 during this task;
  historical installed0.7.2 statements below refer to earlier release acceptance.
- Windows/Linux source paths and new installers have NOT been retested with this
  delta. Preserve existing platform pins/floors and published release artifacts.
- Full-suite verification must NOT call the runner's destructive port cleanup on
  the owner's existing listeners. Use the separately recorded scratch safety
  wrapper; all product assertions/raw child exits still need strict acceptance.

Working evidence: `~/.hermes/cache/scratch/lph-static-html/`, including the
221-entry original-project snapshot, native-original write/restart/control
receipts and PNGs, raw targeted case exits, and protected-state hashes.

## GitHub cleanup applied; contributor cache pending (2026-10-28)

The owner authorized removing automated attribution, preserving genuine human
credit, rewriting/force-pushing `main`, and deleting incorporated branches.

### Applied and independently read back
- Removed ONLY the automated co-author footer from Tahir Masood's original
  `174e90c55b696f592d58ed83f5f5e8552a51242a`; his human author/committer identity
  and dates remain exact. Clean equivalent:
  `b616a79d19dd94ec266fd7a8320de17433dc804a`. GitHub maps BOTH roles to
  `tahirmasood2`. The README acknowledgement and LICENSE blobs are unchanged.
- All194 original commits remain:41commit IDs changed,1message changed, every
  source tree/human identity/date/parent mapping preserved. Two invalidated
  historical merge signatures necessarily disappear. Pre-policy main
  `6601c32e1e546ebfd977e990bb1b14ded6595809` maps to
  `e4254e9fc054ae7e1e3cc4be22dde014bead3890`, with identical whole source tree.
- Policy commit `3178fa5d9f8b90b00688bee9da3f696c34a18c4a` was published by
  one atomic explicit `--force-with-lease` push, together with deletion of the
  already-merged `feat/linux-release` and `fix/windows-qt-compatibility` refs.
  GitHub now has ONLY `main`. All10 obsolete local branch refs were also removed.
- Complete branch audit found no missing intended source:10refs already merged,
  1alternate patch equivalent,2superseded with features preserved. Do not merge
  old snapshots back. All old worktree directories/files/venv links were retained;
  branch-bound worktrees were detached at the SAME original HEAD, not removed.
- A fresh clone directly from GitHub rechecked all194old/newcommit objects and
  the exact reviewed policy files. Actual canonical commit-hook tests pass on
  Python3.9 and3.11, including real rejected bot commits and accepted human
  primary/coauthor/sign-off cases. Scoped independent review was clear; no new
  application runtime/full-GUI/build acceptance is claimed for this metadata task.

### Future attribution
`AGENTS.md` records human-only authorship and no tool/model/agent advertising in
commits or pull requests. The executable `.githooks/commit-msg` is enabled by
LOCAL `core.hooksPath=.githooks` in this checkout. It rejects common bot credit
without editing messages or source notices. New clones must opt in; local hooks
can be bypassed, so retain the written rule. See DEVELOPMENT.md. The owner's
cross-project preference is also recorded outside the repository.

### Pending external display refresh — do not rewrite again
Actual remote `main` contains no automated credit, and GitHub's contributor REST
API includes Tahir and no automated contributor. However, a browser read after
publication still showed the old automated entry in the homepage sidebar.
GitHub documents that contributor displays can take about24hours after a history
rewrite. Do NOT report the visible sidebar as already cleared; if still stale
roughly24hours after the 2026-10-28 publication, the next step is a fresh check and,
if needed, GitHub Support—not another history rewrite. No watcher/server is left
running for this wait. Other clones/forks must rebase or re-clone rather than
merge the old history back.

### Original releases remain unchanged
All13 published tag objects and release/asset IDs, sizes, digests and metadata
remain exact. In particular, `v0.7.3` STILL points at original released source
`21e5f498dff0993ee58e4617c40584f9b33ca240`, tag object
`2df5daf7f0b119413b85dbe548c7411858096e2d`. Historical release tags/PR references
can retain the old metadata; this cleanup targeted default-branch contribution
attribution, not retagging or replacing shipped artifacts. No installed app,
project registration, running service or release asset was changed.

**Durable private rollback/evidence:**
`~/.local/share/local-project-hub/history-backups/20261027T183120Z/` contains
verified original local/remote ALL-ref Git bundles, original refs/releases,
old-to-new commit map and cleanup receipts. Do not publish these backups or push
backup refs to GitHub. Scratch working evidence is under
`~/.hermes/cache/scratch/lph-history-cleanup/`. The completed original release
acceptance below remains valid for the ORIGINAL release source, not a new build.

## v0.7.3 release acceptance — completed (2026-10-27)

**Released:** https://github.com/different2/local-project-hub/releases/tag/v0.7.3
ReleaseID425706169 is public/latest with exactly3complete stable assets:
`Local.Project.Hub.dmg`, `Local.Project.Hub.msi`,
`Local.Project.Hub.Ubuntu-24.04-amd64.deb`.

**Immutable source:** `21e5f498dff0993ee58e4617c40584f9b33ca240`.
Annotated tag object `2df5daf7f0b119413b85dbe548c7411858096e2d`.
Later `[skip ci]` docs commits do not replace the release source or installers.

### Final acceptance — complete, do not rerun historical work
- Main sourceCI40506817730 and exact tagCI40539877288 passed. All6tag jobs
  succeeded, including gated complete-three promotion. All3distinct tag raw
  artifacts independently reconcile377unique IDs/126actual child exits0 each,
  with no missing/extra/duplicate. Ubuntu374PASS/3platformSKIP;
  both Windows2022/2025370PASS/7platformSKIP. Local nativeMac374PASS/3SKIP.
- Local Mac DMG source/runtime/helpers/signatures/macOS12floor and ACTUAL copied
  bundle UI accepted: decoded upload survives native A→Z, owners/logs aligned,
  visible dates/Clear/futureoutput, normal OSexit0/no forced cleanup/survivors.
- Actual native Windows MSI0.7.3 x64/unchanged UpgradeCode inspected read-only on
  Mac. Actual APT-installed Linux0.7.3/Qt6.7.3 pixels/nonce/default sandbox/
  calibrated wrongtext/clean exit/source restoration verified on Ubuntu24.04.
- Anonymous latestAPI/page and all3README latest-download links resolve0.7.3.
  Actual full downloaded bytes, sizes, digests and containers equal the accepted
  installers; downloaded publishedDMG also passes hdiutilverify. Public notes
  match prepared release notes. No published0.7.2 assets were replaced.
- The ACTUAL installed0.7.2 updater modules fetch public0.7.3, select the Mac
  asset and verify its downloaded hash; wrongdigest is rejected. Copied0.7.3
  correctly does not offer itself. No app or installer was launched by these
  read-only updater probes. **Installed `/Applications` is still0.7.2/build1**
  with its original Info.plist hash. Owner installs the update themselves.
- All6real registrations roundtripped through shippedStore0.7.3 on an isolated
  private copy without running commands or altering live data. That owned700/600
  private QA copy was moved to Trash, not deleted/uploaded. No owned QA GUI/server
  remains. README correctly distinguishes selection from Start/autostart.

### Remaining limits / separate work
- Original intermittent permanent bot survivor is still unreproduced and
  undiagnosed, NOT fixed/refuted. Tested ownership/log attribution and truthful
  Stopping feedback are different fixes; termination mechanism remains unchanged.
- Sphere's readable native-option CSS/guard is LOCAL ONLY commit
  `d37f0d1e2ece3519174372892b79da06a1459535`, not in Hub installers. No Sphere
  push/reload; unrelated dirty scripts/art preserved.
- Installers remain not notarized/Authenticode-signed; first-launch guidance is
  in README. Actions v5 upload/download emit Node20→24 deprecation warnings but
  alljobs passed; future CI maintenance is separate, not a reason to retag.

**Receipts:** `~/.hermes/cache/scratch/lph-release-0.7.3/` holds
`tag-ci-final.json`, `tag-source-reconciliation.json`, `release073-public.json`,
`public-download-acceptance.json`, `public-page-acceptance.json`, actual installed/
copied updater results and `release-final-cleanup.json`; full native/review/
negative-control artifacts retained there. Earlier failed runs remain historical
failures, not silently relabelled green. No verifier/debug code was added to the
application. All older checkpoints below are superseded by this completed status.

## Previous staging checkpoint — v0.7.3 (historical)

**Immutable release source:** `21e5f498dff0993ee58e4617c40584f9b33ca240`.
Annotated tagv0.7.3 was pushed and read back: tag object
`2df5daf7f0b119413b85dbe548c7411858096e2d`, peeled exact21e5f49.
Later documentation HEADs must never replace this tag or Mac source receipt.

### Completed gates — do not repeat
- Local native Cocoa/Qt6.9.3 full:377exact IDs,374PASS/3platformSKIP,126actual
  children exit0. Main source CI40506817730 SUCCESS on all3native platforms:
  Ubuntu24.04=374PASS/3SKIP; Windows2022+2025=370PASS/7SKIP each. Every platform's
  distinct raw artifact independently reconciled377IDs/126clean exits, no
  missing/extra/duplicate. All scoped reviews audited and complete.
- Actual local DMG263975668bytes, SHA256
  `0b35a5a3acb5737e1c25bfa7d5b8b94182ec3a3bc638c91ac57799148eeaf73a`.
  Read-only mounted/copied/source20files/version0.7.3/build1/Qt6.9.3/signatures/
  both physical WebEngine helpers/Mach-O12 floors verified and own mount detached.
- Actual copied executable `native-runtime-v2` passed: genuine decoded upload,
  native A→Z focus with unchanged page session/PNG/backendPID; own tab/sidebar/
  log header aligned; visible dates, real Clear then fresh dated output; requested
  normal quit/actual OS exit0, no forced cleanup/survivors. Actual screenshots
  and raw report retained. First unanswered/expired QA remains FAILED history,
  not an app regression; no owner gesture was needed for final accepted run.
- The shipped Store0.7.3 read-save-reloaded a private copy of all6real records,
  preserving order/name/command/URL/env/interpreter/etc; no real commands ran and
  the live registry was unchanged. Private snapshot is700directory/600file,
  never upload it. Installed0.7.2/build1 remains untouched.

### ACTIVE — tag source matrix / publication gate
- **Tag run40539877288**, exactv0.7.3+21e5f49:
  https://github.com/different2/local-project-hub/actions/runs/40539877288
- BOTH native installer jobs SUCCESS and actual artifacts independently accepted
  in `native-artifact-acceptance.json`. MSI0.7.3 x64/unchanged UpgradeCode, SHA256
  `b97e8f5899c5d0f055375c787b627974f1912c4cff53f2cc40a9fc25c91e979d`.
  DEB0.7.3/amd64, SHA256
  `fc4e1c3365fa956b57d088512ccfa75250b876fe46b7c660d4d54ccd651d7fe8`.
  Actual APT-installed Linux native pixels/nonce/default renderer seccomp2/
  no_new_privs1/nonroot/wrong-text control/clean exits/source restoration accepted.
  No Windows binary was executed on Mac; native Windows source tests remain distinct.
- Native-only waiter proc_07ff9bf9434f finished. ONE whole-tag notified waiter is
  now **proc_4716b61102fb** (PID4053), `gh run watch40539877288 --exit-status`.
  Do not duplicate. Latest tag job read: Ubuntu sourceSUCCESS, Windows2022 suite
  actually running, Windows2025 queued; globalqueued is not allocation failure.
- PRIVATE draft release **425706169** read back by ID, draft=true. Actual DMG
  uploaded with exact `source:21e5f498dff0993ee58e4617c40584f9b33ca240` label,
  size/digest verified. Real `verify-macos-input` metadata+local-byte gate PASSED.
  Preview reference `untagged-464974871f339b4b1d60` is valid draft state, not a
  missing public release. Do not replace public assets or touch0.7.2.

### NEXT ACTIONS
1. When notified tag waiter ends, read the real run/jobs by exact tag+SHA. Download
   all3tag test-log artifacts and reconcile377IDs/raw exits independently as with
   mainCI; retain any failing retries or explicitly named platform skips. Installer
   artifacts were ALREADY independently accepted; no source/full native redo.
2. The tag workflow itself requires all serial source tests, native builders/
   installed Linux acceptance and verified Mac input before complete-three
   publication. One whole-run waiter already exists above; don't start another.
3. After publication read release425706169 back, validate exactly3stable assets,
   anonymous latest/download links+actual bytes/digests/container/metadata, and
   installed0.7.2 updater discovery without installation. User installs themselves.
4. Finish docs/checklist/GitHub/local owned-QA cleanup. README's docs-only
   correction makes the existing contract explicit: selection does not launch,
   Start/autostart do. README+this checkpoint are the docs-only `[skip ci]`
   checkpoint; all homepage links already use latest/stable names. Source/tag
   stays21e5f49 regardless of later documentation HEAD.

Live authority/evidence: `~/.hermes/cache/scratch/lph-release-0.7.3/STATUS.md` and
`pre-tag-acceptance.json`, `real-registry-roundtrip.json`, `native-runtime-v2/`.
No UI/server is left from owned Mac QA. Original intermittent permanent bot
survivor remains undiagnosed/unreproduced; do not claim otherwise. Sphere CSS
commitd37f0d1 is local-only, not bundled, unrelated dirty scripts/art preserved.
All older sections below are historical and superseded by this checkpoint.

## Previous pre-tag checkpoint — v0.7.3 (historical)

**Release/build/tag source is exactly `21e5f498dff0993ee58e4617c40584f9b33ca240`.**
Do NOT tag a later `[skip ci]` documentation HEAD. The owner authorized publishing
v0.7.3 once all checks pass, not installing it. Installed0.7.2/build1 remains
unchanged. No0.7.3 tag/draft/publication has happened at this checkpoint.

### Verified
- Source fast-forward pushed to GitHub main and the exact remote ref read back.
- Complete local native Cocoa/Qt6.9.3 regression at that exact clean source:
  **21suites,377unique test IDs,374PASS/3explicit platformSKIP/0FAIL,126actual
  runner children all exit0**. All identities reconciled with no missing/extra/
  duplicate; strict/ordinary/outer exits0; no owned live survivors; installed
  Info.plist SHA256 unchanged (`940156833bc82d91581c0fe5d9bf13fb98623cdc672a133a7c0dc700a205805a`).
- Review findings F1/F2 were corrected, scoped correction review CLEAR and audited.
  Initial full0719ca1's2failures were retained, not relabelled green: one obsolete
  no-tab fixture expectation and one real dated-Hub-log export omission. Both
  corrected with load-bearing negative controls; new bounded integration review
  CLEAR, all2221packet lines/6permitted tools/schema/boolean/hashes verified.
  Final30-case updater/diagnostics suites match final bytes on actual3.11 and3.9.
- Native source screenshots/controls showed readable Sphere menu options, dated
  log lines and Clear log. Actual packaged0.7.3 acceptance is still separate.

### IN FLIGHT at writing — do not duplicate
- Source CI **40506817730** at exact release SHA/main:
  https://github.com/different2/local-project-hub/actions/runs/40506817730
  Serial Ubuntu24.04/Windows2022/Windows2025, no hosted Mac. Background notified
  `gh run watch` is `proc_cf45f35d13e4` (PID72010). Current conclusion/raw artifacts
  must be read after it completes; local green is not remote acceptance.
- Local Mac build `proc_63c63469a4f0` (PID72034), clean detached source worktree
  `~/.hermes/cache/scratch/lph-release-0.7.3/tree`, pinned existing Qt6.9.3 env.
  Log `.../lph-release-0.7.3/macos-build.log`; expected no-clobber output
  `tree/release-assets/Local.Project.Hub.dmg`. Read real exit/artifact, not a
  completed wrapper. No actual Mac installer/runtime signoff yet.

### NEXT ACTIONS
1. On local build completion inspect the actual DMG with the prepared read-only
   `.../lph-release-0.7.3/inspect_macos_qt693.py --source-sha <exact21e5f49> --dmg
   <actualDMG> --output <fresh-owned-dir>`. Require source parity, bundled version/
   Qt/physical helpers/signatures/Mach-O12 floors, read-only mount detach, then
   exercise the actual copied bundle in isolated native HOME/registry/cache.
   Verify visible UI, uploaded-state focus behavior and actual exits/owned cleanup.
   Never modify bundled source to fake acceptance or replace `/Applications`.
2. On source CI completion download every distinct test-log artifact and reconcile
   each actual raw identity/exit against exact release source; all3platform jobs
   must pass. Use `reconcile_strict.py` in the new release workspace; it is calibrated
   and preserves retries/skips rather than trusting aggregate counts.
3. Only after those gates, follow DEVELOPMENT.md release steps: annotated NEW tag
   v0.7.3 at explicit21e5f49, push/verify its exact tag run, immediately create or
   resume PRIVATE DRAFT only and upload verified Mac DMG label `source:<fullSHA>`.
   Read draft BY release ID and run the real Mac-input metadata/file/hash gate.
   No public replacement, retagging or0.7.2 asset changes.
4. Tag workflow requires serial source matrix, native Windows MSI build, native
   DEB/APT-installed Linux renderer/sandbox/negative/cleanup and Mac input before
   complete-three publication. Watch one notified waiter, inspect actual MSI
   version/UpgradeCode and Linux runtime evidence, then verify anonymous latest/
   download bytes/digests/metadata and installed0.7.2 updater discovery. User installs.

The original intermittent permanent bot-survivor report is still undiagnosed and
unreproduced, not fixed/refuted; tested ownership/log attribution and truthful
Stopping feedback are distinct. Test cleanup stopped the old8787 dashboard after
the owner was warned; no auto restart was issued.

Separate Sphere fix is local-only commit `d37f0d1e2ece3519174372892b79da06a1459535`
(CSS/guard/secret-ignore); unrelated dirty scripts/art preserved, no Sphere push
or live-page reload. It is NOT part of the Hub installer.

**Live continuation authority:** `~/.hermes/cache/scratch/lph-release-0.7.3/STATUS.md`.
All sections below retain historical evidence and are superseded by this section.

## Previous source-preparation checkpoint — v0.7.3 (historical)

**LATEST GATE:** full native candidate0719ca1486f396f2f722acf9815acef3060f0b3b
FAILED with371PASS/3SKIP/2FAIL across376exact unique IDs/126actual children.
All15new native cases passed. The two failures were a stale no-tab test setup
(it expected the removed owner to remain selected) and an actual diagnostic-log
integration omission (the new date prefix no longer passed the `[hub]` filter).
The fixture now asserts normal owner synchronization then explicitly injects
the historical stale-owner condition; restoring the bad dashboard fallback
makes its original safety assertion fail. Diagnostics now classifies after one
known timestamp while retaining the dated original for unchanged redaction.
Full30-case updater/diagnostics suites and both original failing native cases
pass on actual Python3.11 and3.9. A deliberately permissive date filter is
rejected for admitting raw/malformed output, then restored bytes pass again.
Their scoped integration review (`deleg_db060046`, gpt-6.1-sol/openai-codex) is
CLEAR: schema/actual boolean, all2221packet lines,6permitted read-only calls and
frozen hashes audited. The final strengthened30-case test file also passed again
on Python3.9, closing the review's historical test-hash caveat. A NEW clean-source
full run remains REQUIRED. The previous F1/F2 checkpoint is complete, not being
looped again. No source push/tag/draft/publication/install has occurred.

The owner reported dashboard upload loss on sidebar focus/Add, tab/sidebar action
mismatch, wrong bot-close log attribution, unreadable Sphere asset choices, and
one unreproduced bot survivor; requested dated/clearable logs. They explicitly
selected **Publish v0.7.3 after all checks pass**. This source is not published yet;
installed0.7.2 and real bot registrations must remain untouched. The owner has
standing permission for test runs to stop running apps: the unchanged full runner
may deliberately free legacy test port8787 (the observability dashboard). Warn
before that launch, record the stop as test setup and do not restart it automatically.

- Sidebar focus no longer refreshes an existing page; list rebuilding/Add are
  registration-only and preserve the actual visible tab and in-memory uploads.
- Tab ownership now synchronizes the sidebar, controls and terminal, including
  child/nested popups; mutable titles/indices cannot identify a project in logs.
  Last-project/Remove transitions preserve a valid overview or remaining owner.
- Date/time formatting is centralized per event/line. Clear log affects only
  the visible stored pane, not other logs, the backend or its current page.
- Reopening during a requested shutdown now says Stopping, based on actual live
  child + Stop intent, without changing signal/identity/grace logic. A real
  TERM-ignoring owned fixture is force-reaped after close/reopen. This does NOT
  diagnose or refute the original one-off permanent-survivor report.
- Sphere's dropdown is a separate local page-CSS correction in
  `the_sphere_project/styles.css`: explicit opaque option/optgroup colours, not
  Hub HTML rewriting. Native popup screenshots/pixel controls and a source guard
  discriminate the fix. Other pre-existing dirty Sphere files/art are untouched.
- Fifteen new native cases have each passed under actual Python3.11 and3.9 /
  Qt6.9.3 across development (30 historical case/interpreter observations, NOT
  exact-final-source full acceptance). The independent review's F1 opener-lifetime
  and F2 stale stopped-Edit findings were both reproduced RED, then fixed after
  the owner selected Fix both before release. Popup registration now belongs to
  the long-lived Hub, not an opener; explicit Edit refreshes saved launch content
  without restoring sidebar reload. Both correction cases pass on both interpreters;
  coupled sidebar-upload/Add/nested-once controls also pass. Original evidence is
  retained in `review-073-raw.json` / `review-073-audit.json` and native case logs.
  Actual pixels show readable options, dated log lines and Clear log. The single
  scoped correction re-review (`deleg_c2c8a837`, gpt-6.1-sol/openai-codex) is CLEAR;
  boolean verdict/schema, all3271packet lines, permitted-only8tool audit and all
  frozen hashes were independently checked. Exact-source full strict regression
  and real0.7.3 installer acceptance remain REQUIRED. Review is not release signoff.
- Version/changelog are prepared for0.7.3. Existing Windows/Ubuntu CI stays
  max-parallel1; local Mac build only, unchanged pins/sandbox/deployment floor.
  README downloads already track the latest complete published release.

**NEXT:** commit the reviewed post-full-run integration source/test/docs delta. Launch
`~/.hermes/cache/scratch/lph-release-0.7.3/run_native_strict.py` using the NEW
exact clean candidate SHA and label `full-native-v073-v2`, then reconcile all
identities/raw exits. Push/read back that candidate to main and require serial
Ubuntu/Windows source CI. Build/inspect and actually exercise its Mac DMG locally
in isolated scratch state. Only then create NEW immutablev0.7.3/exact-SHA private
Mac input; require native Windows/Linux builders/runtime gates, publish all3
assets together, verify anonymous latest/download hashes and installed0.7.2
updater discovery without installing. Never retag v0.7.2 or replace its assets.
Evidence/progress: `~/.hermes/cache/scratch/lph-ui-followup-072/STATUS.md`.
Older checkpoints below retain their historical scope.

## Previous release closeout — v0.7.2 public and verified (2026-10-26)

**This section supersedes the historical checkpoints below. No v0.7.2 release
verification remains pending. Installation is left to the owner.**

Release: https://github.com/different2/local-project-hub/releases/tag/v0.7.2

- Public, non-prerelease release **424229358** is `latest`. Immutable annotated
  tag `v0.7.2` (object `f4e323ccd264db7432ced2114c7ef3da03d5f8af`) peels to
  exact tested/built source `5aae648c3457868399a154633387766279c2033e`.
  No force push, retag, public-asset replacement or installed-app update occurred.
- Delivers persisted Projects-sidebar drag-to-reorder. New projects append;
  renaming retains position, and failed saves restore the saved ordering.
- Mac uses Qt6.9.3 with the upstream QTBUG-134784 accessibility-cache ownership
  fix. Windows stays6.12.0, Ubuntu6.7.3; macOS floor12.0 is preserved.
  The Mac test runner defaults to native Cocoa, not the offscreen backend that
  reproduced a separate renderer crash. Only three native-style-dependent
  tab-button test observers were corrected to check both sides; application
  behavior and actual close/backend/persistence assertions were not weakened.
- Source CI **40315788326** and tag CI **40323612397** both passed all required
  jobs at that SHA. The tag run's six individual jobs, including both native
  builders and the Ubuntu publisher, were freshly read back as successful.
  Mac was built/tested locally, not on a hosted Mac runner.

### Exact-source regression acceptance

| Environment | Suites | Unique test IDs | Passed | Skipped | Failed | Actual runner children |
|---|---:|---:|---:|---:|---:|---|
| Local macOS / Cocoa / Qt6.9.3 |21|361|358|3|0|111/111 exit0|
| GitHub Ubuntu24.04 |21|361|358|3|0|111/111 exit0|
| GitHub Windows2022 |21|361|354|7|0|111/111 exit0|
| GitHub Windows2025 |21|361|354|7|0|111/111 exit0|

Every identity ledger was reconciled with no missing, extra or duplicate verdicts;
strict and ordinary runners exited0. Remote rows were separately reconciled for
both the final source run and tag run. Python3.9.6 separately passed the three
original native WebEngine cases with Qt6.9.3/actualexit0, runner11 cases, and
portable release helpers15PASS/5explicit packaging-only SKIP. This is targeted
Python3.9 coverage, not a full Python3.9 packaged-app or full-suite claim.

### Actual installers and public-byte acceptance

| Stable latest-download asset | Bytes | SHA-256 |
|---|---:|---|
|Local.Project.Hub.dmg|264207177|58f50d05dda10b1aa12e946fffde2ba8bb4fb99b2deb3341260e2e7e69d6bda7|
|Local.Project.Hub.msi|108754933|7927b5a2c5309687e5aa6c239734398f3e955a3c1d254c6ae393277c05698338|
|Local.Project.Hub.Ubuntu-24.04-amd64.deb|172599736|ae9447fd88cd7e457344e46dd90b6bac0b2ee578a7ab1120b0a26b75f97c315e|

- **Mac:** actual final DMG inspected for byte-identical source, version0.7.2,
  numeric build counter1, bundled Qt6.9.3, all physical renderer helpers/signatures
  and Mach-O macOS12 floors. Actual scratch bundle was observed through AX;
  the owner performed one native drag Z/A/M → A/M/Z. Fresh pixels, saved stable
  IDs, unchanged live backend identity, real nonce DOM and sandboxed renderer
  verified it landed. Reopen used the same saved registry without reseeding.
  Both launches quit normally with actual app/wrapper exit0 and no owned survivors.
- **Windows:** built on native Windows CI, genuine x64 MSI/version0.7.2 inspected
  read-only on the Mac. UpgradeCode remains
  `{25F599D7-F44F-5B9D-8CC0-FC312B836125}`. No Windows installer was executed on
  the Mac, and no installed Windows GUI/hardware acceptance is claimed.
- **Linux:** actual APT-installed `/usr/bin/hub`0.7.2/Qt6.7.3 on Ubuntu24.04
  rendered real nonce DOM and matching native screenshot pixels with checkout
  sources hidden/restored. Renderer NoNewPrivs1/Seccomp2 and unchanged runner
  security policy verified. Wrong-text negative control was rejected; real
  application exit0, empty owned cleanup and source restoration verified.
- All three `/releases/latest/download/...` URLs were anonymously downloaded
  **in full** after publication: HTTP200, sizes/hashes match both these accepted
  installers and the public API digests. Anonymous latest API returned v0.7.2;
  published release notes match the intended notes. README already uses these
  three version-independent links; no version-pinned front-page link was added.

### Updater, review and local state

- Installed `/Applications/Local Project Hub.app` remains **0.7.0/build1**.
  Its actual updater module, imported with bytecode writes disabled under an
  isolated host Python3.11 and using its installed certifi CA bundle, fetched
  live metadata over verified TLS, detected v0.7.2 as newer, selected the exact
  Mac DMG/digest and accepted its downloaded bytes while rejecting a wrong
  digest. All three release digests parsed correctly. Selected installed-file
  hashes/mtimes were unchanged. This checks module/network/discovery/integrity,
  not a fresh GUI click or an installation; the owner updates the app themselves.
- Review Checkpoint ran for the feature and separate Python3.9, Mac runtime,
  native runner and tab-observer corrections; all final scoped results were
  clear. Frozen packets, source hashes and complete reviewer transcripts were
  audited. A clear code review is not substituted for the actual acceptance above.
- Canonical main was fast-forwarded to the released source before this docs-only
  closeout. Existing canonical development/build venvs were **not** upgraded:
  follow DEVELOPMENT.md's Mac6.9.3 pins for future source work. The isolated
  verified6.9.3 environments remain in the release scratch area while retained.
- Original Tahir Masood / @tahirmasood2 commit
  `174e90c55b696f592d58ed83f5f5e8552a51242a`, CommandCodeBot trailer, ancestry
  and README acknowledgement remain intact. User projects/settings/art were not
  changed. Prior failed probes and superseded runs are retained, not relabelled.
- Platform limits remain: Mac Apple silicon/macOS12+, Windows x64, Linux
  Ubuntu24.04 amd64 only; Linux updates are manual/APT. Installers are not
  notarized/Authenticode-signed; README first-launch warnings still apply.

Evidence root (scratch, subject to cache retention):
`~/.hermes/cache/scratch/lph-release-0.7.2/`. Key records:
`macos-final-acceptance.json`, `native-full-macos-v2-identities.json`,
`py39-native-cases/report.json`, `sourceci-5a-reconciled.json`,
`release072-tag-completed.json`, `release072-tag-tests-reconciled.json`,
`release072-package-acceptance.json`, `release072-published.json`,
`release072-anonymous-latest.json`, `release072-public-downloads.json`,
`release072-installed-updater.json`. GitHub run/release links and the identities
above remain the durable public re-verification points after scratch expiry.

## Historical native verification checkpoint — platform tab-button placement

Qt6.9.3 runtime correction07a1c7f and native-backend correction60c1c76 both
passed their separate bounded reviews and are pushed to origin/main at60c1c76.
The full native Cocoa run at that SHA is retained as FAILED:355PASS/3SKIP/
3FAIL,111actual children. Only three tab-close tests failed, each querying only
`QTabBar.RightSide`; no raw child in this run crashed. This is not acceptance.

A separate actual minimal Qt control shows the default macOS/Cocoa CloseButton
object on LEFT, while Fusion/offscreen puts it on RIGHT. Both objects have
nonzero geometry and close the tab when clicked, and both actual processes exit0.
The saved native screenshot does not prove an always-visible x glyph; no such
appearance claim is made. The follow-up changes ONLY the three test-side button
existence queries to inspect both sides. All original close/backend/registry/
starter-identity assertions and application behavior remain unchanged. The same
three original cases now pass with actualexit0 on Python3.11.10 AND3.9.6,
Qt6.9.3/Cocoa; an intentionally disabled real HubWindow close button is still
rejected with the exact missing-button error (separate negative-control exit1).
No app/pin/workflow/sandbox/source-runner changes are part of this correction.

This small observation correction still needs its bounded review/commit and a
fresh FULL strict native run. Prior failed runs remain on disk. Source CI
40290038065 tests60c1c76 (Ubuntu step succeeded; Windows jobs not yet reconciled
at writing), not this follow-up. Finish the final-SHA full native/remote evidence,
then rebuild/inspect the exact-source DMG and complete actual packaged AX/native
mouse drag/persistence/reopen/normal-OS-exit acceptance before staging any private
v0.7.2 input or tag. No0.7.2 tag/draft/publication; installed user0.7.0 untouched.
Newest scratch state: `~/.hermes/cache/scratch/lph-release-0.7.2/STATUS.md`.

## Current verification correction — native Mac test backend

Runtime correction07a1c7f was independently reviewed clear and committed locally,
not yet pushed/tagged. The real rebuilt6.9.3 DMG passed mounted source/version,
signature, actual dependency and Mach-O macOS12-floor inspection. Its actual
packaged AX+drag/reopen acceptance is still pending; installed0.7.0 untouched.

The first full strict6.9.3 run retained354PASS/4SKIP but7actual-11 children in
3window cases (115invocations including retries); it is NOT acceptance. OS
stacks identify VizCompositorThread/QtWebEngineCore, not the old Cocoa AX crash.
Without any concurrent build, two cases still crash offscreen; all3 exact
source cases pass with Cocoa/actualexit0. The test runner now defaults to native
Cocoa ONLY on Mac and keeps Windows/Linux offscreen; explicit backend overrides
remain possible. Assertions, isolation/PTY, retry policy, raw-exit strict gate,
sandbox flags and application code are unchanged. Strict evidence now names its
backend. The genuine skip-control test explicitly selects offscreen and restores
the environment afterward, rather than assuming every Mac test is offscreen.

New platform/backend guard first failed RED; the runner suite passes all11
cases under actual Python3.11 and3.9. This correction still needs bounded review,
commit/fresh full strict acceptance and exact-source installer/release gates.
Retain the failed offscreen run and original native comparison evidence; do not
claim that switching the test backend repaired a production rendering bug.
Scratch STATUS.md names exact reports, paths and next actions.

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
