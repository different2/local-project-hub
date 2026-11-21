# HANDOFF — Local Project Hub

## Current checkpoint: v0.7.4 is published and downloads are verified

Read this file first, not the historical archive. The authorized rebuild/publication
is complete. **No user installation or restart was performed.** Managed sources,
dependencies, virtual environments, registry and running services were not changed.
No independent review was requested or run. Preserve human attribution and sandboxing.

Repo: `/Users/iff/Documents/Programming/local-project-hub`
Release: https://github.com/different2/local-project-hub/releases/tag/v0.7.4
GitHub release ID: **434329137**, public/non-prerelease, explicitly marked latest.
Published timestamp: **2026-11-04T19:10:58Z**.

## Immutable identities and actual downloadable bytes

Annotated **v0.7.4** targets **`052033e46ed014482b3ecf7c0fee337beb9b91cd`**.
Later README/handoff/development-doc commits are not the release source.
Mac actual build/runtime: **`c37f9d573a1d5a044248d3fe67143681110889f8`**.
Every packaged source byte and all version/package inputs are identical to052033e;
the only Git differences are HANDOFF.md and a browser test's Reload-readiness wait.
That changed test separately passed on native Mac Python3.11 and3.9.6.

| Stable filename | Bytes | SHA-256 |
|---|---:|---|
| Local.Project.Hub.dmg | 263983761 | `24f0f49fbdcfc57d3fb9e95501ac72e0a4bdc749ec17fadd45471a0fb5704281` |
| Local.Project.Hub.msi | 218460768 | `de6c3d2a5040b84d377cd0335c3e79a65cb938c70b90cefbea663521907b89eb` |
| Local.Project.Hub.Ubuntu-24.04-amd64.deb | 172587392 | `ed5e8733d2c107f6de393f4ed081d9267e1fb3493a4b93c43e7449bab4bf5ccd` |

The front-page URLs are `/releases/latest/download/<stable-filename>`. All three
were downloaded **anonymously in full** after publication:HTTP200 and exact sizes/
hashes above. Anonymous latest metadata names0.7.4/434329137. Do not rebuild,
replace or clobber published0.7.4 assets; fixes need a new release/version.

## Accepted gates — do not rerun because delayed notifications arrive

- **Windows source**, run41869103664: Windows2022 and2025 each437 unique identities
  =430PASS+7SKIP;152 actual children/all0/clean, independently reconciled.
- **Actual MSI native**, run41880047847, QA083f71f7b8710af6a6499cabf4260016eba19985:
  all23 exact immutable-source→CRLF-installed byte hashes and membership matched;
  separate WebEngine6.12.0.140/modules/helper/resources present; source-hidden
  installed nonce/native rendering, wrong-DOM refusal and sandbox guards passed.
  Actual screenshot inspected; install/normal WM_CLOSE/reaped exit/uninstall all0,
  no forced cleanup/survivors/errors; source/MSI preserved. Builder job126710974806,
  artifact13343587457; all identity/API/ZIP/MSI receipts retained.
- **Linux full native-display source**, run41883712775: immutable052033e,
  Ubuntu24.04/Python3.12.16/Qt6.7.3, actual `qt_platform=xcb`, unchanged source,
  437 identities=434PASS+3SKIP;152 actual children/all0/clean/strict_exit0,
  independently reconciled. No source/assertion/sandbox/exit-policy changes.
- **Actual installed Linux DEB**, run41869103664: APT-installed source-hidden launch,
  nonce/native X11 pixels, sandbox, wrong-text refusal and normal close0/no survivors/
  source restoration. Screenshot independently inspected. Artifact13344670313 is
  the same file installed before upload.
- **Mac full native Cocoa c37 source**:437 identities=434PASS+3SKIP;152 actual
  children/all0/clean, unchanged source; safety adapter replaces unrelated-port
  housekeeping only. Actual DMG read-only mount/copy, signature,23-source membership,
  dependency/renderer-helper/deployment checks passed.
- **Actual Mac package attempt3**: freshly activated native Replay/Back/Spheres/
  Forward/Replay/Reload screenshots inspected, matching nonce, real Reload timeOrigin
  change with unchanged owned backend PID/creation identity. Owner explicitly
  confirmed **native Save and Close** (human-assisted, not fully automated);42 UTF-8
  export bytes matched independently. Correct `NSRunningApplication.terminate()`
  requested normal quit; parent reaped0, no survivors/callback/lifetime errors or
  forced cleanup. Installed executable/Info.plist/registry hashes unchanged against
  fresh pre-attempt3 baseline. All owned native fixtures exited.

## Publication scope and historical failures — keep the distinction honest

Original full run **41869103664 remains failed overall**: offscreen Ubuntu input.
Both Windows source hosts/builders succeeded. A32-child unchanged bare-Qt/app input
comparison41881546465 found one3.12.15/offscreen failure, all16 xcb children0; it was
not a3.12.16-only regression or product fix. The full native X11 run above supplied
Linux source acceptance. The ordinary workflow still defaults Qt to offscreen even
when Xvfb is started; explicit native backend is a future CI-maintenance option.
Never describe the failed ordinary run or a diagnostic-collection job as green app CI.

Publication was a deliberate **maintainer promotion of the retained accepted files**,
not a fresh tag build. The tested commit carries `[skip ci]`; the annotated tag is
immutable and no tag workflow appeared. No manual dispatch was made publish-capable.
The exact private draft/Mac input was read by release ID, Mac uploaded and redownloaded
and validated with source-equivalence proof, then all three assets/digests/notes were
validated before promotion. The same public release ID/assets were read back and
validated afterward. No public asset was overwritten. DEVELOPMENT.md documents this
maintainer recovery path separately from normal automated tag publication.

Earlier failed native attempts (WebSocket context-manager misuse, invalid
`terminate_` selector, stale inactive-window captures) remain failed evidence, not
app regressions or acceptance. The owner helped with native Save/Close. Do not
continue asking for the old foreground permission or rerun completed Windows/Linux
checks. Preserve original superseded6b88eff/c37 build failures and original MSI
missing-WebEngine rejection; never redispatch those as the published candidate.

## Installed update offer and limits

The user's installed bundle is still **0.7.3**. A fresh process outside the checkout
imported its actual hub/updater modules and fetched public0.7.4, selected the Mac
DMG and saw a strictly newer, digest-verifiable update. That installed verifier
accepted the anonymously downloaded real DMG and rejected a deliberately wrong hash.
This was **read-only**, not a GUI click, download/install or restart of the user app.
The user may update via Help → Check for Updates or the public Mac download.

Mac target remains Apple silicon/macOS12+; Windows x86-64; Linux Ubuntu24.04 amd64
only. Paid trusted signing/notarization is not present; README trust prompts remain.
The owner corrected historical observability attribution: those fixed project-side
errors were not Hub defects. No managed-project source edits were used here.

## Durable private evidence and continuing protections

Root (never upload wholesale):
`~/.local/share/local-project-hub/acceptance/release-0.7.4-2026-11-04/`
Read CURRENT.json, then `publication/{frozen-artifacts,pre-promotion-acceptance,
published-release-by-id,anonymous-verification,installed-updater-offer}.json`.
Mac: `candidate2/mac-native-attempt3/{report,interaction-verification,
independent-acceptance}.json`; source/build evidence in candidate2/.
Windows/Linux full raw manifests and independent reconciliations are in candidate3/.
A verified `windows-qa-083f71f.bundle` preserves Windows QA source/history.
An unrelated composited capture was excluded and moved to private Trash.

**Never merge `diagnose/windows-msi-native` or `diagnose/linux-input` into main.**
**Never run tests/run_all.py top-level on this Mac**: its unrelated-port cleanup
still lacks fixture ownership. Keep installed Hub/services untouched unless newly
authorized. Preserve untracked graphify-out/, .githooks, human acknowledgements,
failed evidence and provenance. Existing .hubenv/.buildenv were not upgraded.

No outstanding release/publication gate remains. Any future CI-backend maintenance
is separate from this completed release. Prior checkpoint: `git show d5ca73a:HANDOFF.md`.
