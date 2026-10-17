# HANDOFF — Local Project Hub

_Last written: 2026-10-16, end of day. A fresh session should be able to start
from this file alone: read it, run `git log --oneline -15`, then check the open
threads below. Earlier sessions on this project ran long and twice died on
provider errors mid-task, so state belongs here and in commits, not only in chat._

## Where things stand (verified 2026-10-16)

- `main` @ `ab793db` — working tree clean, in sync with `origin/main`. Nothing uncommitted.
- **v0.3.8 is the latest release**, with both installers attached:
  `Local.Project.Hub-0.3.8.dmg` (262 MB) and `Local.Project.Hub-0.3.8.msi` (109 MB).
- Latest CI run on `main` is green. Full local suite passed: **14 suites, all green**
  (`tests/run_all.py`, 144 tests on macOS).
- `pyproject.toml` version: `0.3.8`.

## How CI and releases work here

- **Push to `main`** → the test job runs the suite on **Windows only** (the matrix is
  deliberately Windows-only for now; macOS/Linux are covered off-runner). Serial run,
  50-minute cap (GUI suites bind fixed ports and must not overlap).
- **Tag `v<version>`** → builds the macOS `.dmg` and Windows `.msi`, then publishes both
  to the GitHub release. The tag **must equal the `pyproject.toml` version** or
  `tools/check_tag_version.py` fails the build in seconds (a mismatch ships an app that
  offers the same update forever).
- **Manual dispatch** (`gh workflow run CI --ref main`) → builds both installers as
  artifacts and **never publishes** (`test_workflow_yaml.py` guards that).
- Cutting a release = bump `version` in `pyproject.toml`, commit, then
  `git tag vX.Y.Z && git push origin vX.Y.Z`.

## What the last work stretch (Oct 14–16) finished

- Windows port-conflict handling end-to-end (netstat port owners, PowerShell
  command-line reads, bind-wait, traceback recovery).
- Packaging pipeline: `-p msi` / `-p dmg` flags fixed, release created before uploads,
  `contents: write` on the publish job, `--adhoc-sign` so the macOS build can't hang on
  a signing prompt, dispatch builds that never publish.
- **Update downloads are now digest-verified.** (The check previously read a field the
  GitHub API never returns — dead code that looked safe.) Verified against the real
  v0.3.8 release.
- Tag/version guard (`tools/check_tag_version.py`), verified by pushing a deliberately
  mismatched throwaway tag and watching it fail in ~1 minute; no release leaked.
- MSI upgrade trap documented in `pyproject.toml`: the UpgradeCode derives from
  `bundle`, so changing that field silently stops Windows upgrades from replacing.
- macOS update dialog now names the Control-click → Open gesture for when Gatekeeper
  refuses a new copy.

## Open threads, in priority order

1. **The goal that got dropped: "one-click update" smoothness across Windows and macOS.**
   The user's last instruction — "make sure this is a one click update this app install
   thing across windows and macos. If there is anything you think to make that job go
   smoothly then do it" — was never processed; provider errors ended the session right
   then. Remaining items:
   - **Pin Briefcase in CI** (e.g. `briefcase==0.4.6` in both build jobs). It is
     currently unpinned — the last silent-change risk on the release path.
     (`.buildenv` here has 0.4.5.)
   - **Unsigned builds** → Gatekeeper/SmartScreen warnings. The only real fix is paid
     certificates (Apple $99/yr; a Windows cert); everything else is messaging. Not started.
   - **macOS drag-to-Applications is manual on purpose** — automating a self-replace in
     `/Applications` from an unsigned build was deferred until it can be tested carefully.
     Not started.
   - Digest verification only protects updates **from 0.3.8 onward** (the update *into*
     0.3.8 runs the old, unverified code). Informational.
   - The Windows update dialog gives no SmartScreen guidance (macOS got the Gatekeeper
     text). Whether an app-downloaded MSI even triggers the prompt is unverified —
     check before "fixing".
2. **README says "53 tests across 6 suites" — stale.** The runner reports 14 suites
   (~144 tests). Small doc fix whenever.
3. **One flaky Windows CI failure so far** (run 38917634716, commit `5d82456`):
   `test_detected_suppress_flag_is_applied_to_the_launch` — "flag never reached the
   process: ''". The two runs after it passed and that commit's changes were unrelated.
   If it recurs, start here.
4. **MSI upgrade-replaces-install is verified only by reading Briefcase's WiX template,
   not on a real Windows machine.** Run one real Windows update before calling Windows
   updates done.

## Environment on this Mac

- `.hubenv` — Python **3.9.6**, used by `./run.sh`. Suite runs use
  `QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py`.
- `.buildenv` — Python **3.11.10**, briefcase **0.4.5**; what local packaging uses.
  CI uses Python 3.11.
- `gh` CLI lives at `~/.local/bin/gh` (not on `PATH`), authed as `different2`.
- Project registrations / app data: `~/Library/Application Support/LocalProjectHub/`.
- Design context docs: `SPEC.md`, `PHASE1_AUDIT.md`, `hub-project-real-app-design.rtf`.

## Verify claims quickly

```bash
git fetch && git status -sb                    # clean, in sync
QT_QPA_PLATFORM=offscreen .hubenv/bin/python tests/run_all.py   # 14 suites, serial, ~30 min
~/.local/bin/gh release list                   # v0.3.8 = Latest
~/.local/bin/gh run list --branch main --limit 5
```

_Maintenance: update this file at the end of a work session — move finished items out
of "Open threads", add new ones, refresh the status block._
