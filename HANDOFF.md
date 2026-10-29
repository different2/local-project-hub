# HANDOFF — Local Project Hub

## Read this checkpoint first; do not ingest the historical archive by default

**Publication is ON HOLD.** Do not create a v0.7.4 tag/draft/release, install an
update, or restart the user's app without new authorization. Public/installed
latest remains 0.7.3. The owner authorized fixing the Hub, not changing managed
projects. Preserve original HTML/scripts/venvs, live registry, unrelated services,
human attribution, renderer sandboxing and immutable published installers.

- Repo: `/Users/iff/Documents/Programming/local-project-hub`
- GitHub: https://github.com/different2/local-project-hub
- Tested runtime: **`77aaa1877c3c586634f572ede63f9bf7095abb08`**, version 0.7.4.
- Subsequent main changes are handoff documentation only, not new tested runtime.
- Canonical application source is unchanged by the current TEMP Windows QA work.
- The complete previous handoff is preserved verbatim in
  [docs/HANDOFF_HISTORY_2026-10-29.md](docs/HANDOFF_HISTORY_2026-10-29.md).
  Read it only for a specific historical question. This checkpoint wins.

## Verified acceptance — do not rerun these unchanged source gates

| Environment | Exact identities | PASS | Platform SKIP | Raw child exits |
|---|---:|---:|---:|---|
| Native macOS / Qt 6.9.3 | 425 | 422 | 3 | 142, all zero |
| Ubuntu 24.04 / Qt 6.7.3 | 425 | 422 | 3 | 142, all zero |
| Windows 2022 / Qt 6.12.0 | 425 | 418 | 7 | 142, all zero |
| Windows 2025 / Qt 6.12.0 | 425 | 418 | 7 | 142, all zero |

Registry/raw-verdict equality and both profile/QProcess lifetime-warning gates
were independently checked. Actual full CI **40845715963** succeeded; publication
was skipped. There are also 129 affected identities per Python 3.11/3.9, eleven
separate native Python 3.9 floor cases, and targeted RED/GREEN/mutant controls.
These floor cases are not a complete Python 3.9 suite.

- **Mac package accepted:** current DMG inspected for source/runtime/signature/
  deployment floor; copied app saved and cold-restored the owner's original,
  unchanged trading HTML. Two actual app exits zero, no forced cleanup/survivors;
  fresh native screenshots show 1 reviewed / 0 queued. Installed app untouched.
  Fresh pre-handoff protection check again matched all 221 original entries,
  complete membership, live registry and installed metadata.
- **Linux package accepted:** actual APT-installed current DEB, matching source,
  source checkout hidden, visible nonce/native screenshot, wrong-DOM rejection,
  normal exit/owned cleanup, no sandbox bypass.
- **MSI metadata accepted; installed-runtime acceptance is still OPEN.**

Current installer SHA-256 values:

| Asset | SHA-256 |
|---|---|
| `Local.Project.Hub.dmg` | `6619c046a7bc1c8f65041decd8b4d66cc23ab93a2fa385a499da0b573ed448cd` |
| `Local.Project.Hub.msi` | `ae539e3596f391b5f7dd272b024610ad7b4abf2c5b4c601aaa743ffa894eea2d` |
| `Local.Project.Hub.Ubuntu-24.04-amd64.deb` | `d56a9c1c3cb956f99bf4bf20b67ff87cc99a1be2f718dc8fd3ed3400ea3f9211` |

## Immediate next action — diagnose MSI payload/source parity before native launch

TEMP branch **`diagnose/windows-msi-native`** must NEVER merge into main. It
contains only the dispatch-only workflow and observer tooling. Actual app input
is the immutable MSI from run 40845715963 and a separate checkout of exact 77aaa18.
Only free public Windows-2025 runners are authorized; no Windows binary on Mac.

Latest QA-only head: **`90bee40510edad12cf71b8fb5ed629c0d1436158`**.
Latest actual native attempt **40888996043** COMPLETED FAILURE:
https://github.com/different2/local-project-hub/actions/runs/40888996043

- Real Windows2025-vs2026 host and expected MSI bytes/identity were verified.
- `msiexec /i` actually succeeded, exit 0; authoritative component lookup found
  the installed AMD64 PE. `msiexec /x` of its exact ProductCode also succeeded,
  exit 0, with no reboot, remaining related product or remaining launcher.
- The installed app was **NOT LAUNCHED**: strict payload comparison first rejected
  hashes for all 22 runtime source paths. Source/artifact preservation passed.
- Check Windows checkout CRLF versus the QA workflow's forced LF FIRST, but this
  is an unproved hypothesis. Inspect actual bytes/hashes; do not normalize away
  a discrepancy or assume all mismatches are harmless. Keep the parity gate.
- Mac read-only CAB inspection was attempted: embedded cabinet extracted to
  `windows-msi-native/actual-payload.cab`; `/usr/bin/tar -tf` failed with
  `Invalid CAB header`. No byte/line-ending conclusion was obtained. Do not
  repeat that unchanged decoder attempt. Use another read-only decoder or
  collect narrowly scoped payload bytes/hash/EOL diagnostics on the owned VM.

Private durable attempt evidence is already retained at:
`~/.local/share/local-project-hub/acceptance/windows-msi-77aaa18-incomplete/`.
Read `attempt-3/report.json` there first; its manifest explicitly leaves native
runtime verification false. It also preserves earlier failures and a verified
QA-source Git bundle. Scratch copies remain in
`~/.hermes/cache/scratch/lph-release-0.7.4/candidate-v6/windows-msi-native/run-v3/`.
No QA worker or CI watcher remains pending. Do not redispatch the same source.
After a demonstrated observer correction, run only this installer gate, requiring
installed source/Qt parity, nonce DOM/native pixels, normal WM_CLOSE/zero exit,
no forced cleanup/survivors, source restoration and exact-ProductCode uninstall.

Earlier native attempts **40866713835** and **40888259985** FAILED BEFORE MSI
installation. Their concrete QA problems were corrected, not application bugs:
1. Old guard rejected the real Windows-2025-vs2026 runner image.
2. A follow-up copied Windows `os.environ` into a case-sensitive dict and lost
   lookup of `ImageOS` because the actual copied key was uppercase `IMAGEOS`.
Current eight helper tests pass, including both real image variants, uppercase
keys and self-hosted/wrong-OS rejection; the uppercase case was RED first.

Retain failed and accepted observations separately. On eventual completion,
remove owned TEMP refs only after verified evidence + a private Git bundle;
keep worktree files. Do not rebuild the MSI or rerun the full source matrix
merely to repair this observer. Runtime acceptance remains OPEN.

## Important limits and owner decisions

- The owner explicitly chose direct regression verification and **no further
  independent review rounds**. Both earlier concerns-found review verdicts remain
  failed; later direct tests must not be relabelled an independently clear review.
- Historical Linux nested-popup child -11 failures remain failed. The bounded
  diagnostic did not reproduce the segfault or capture a fault stack. A separate,
  deterministic deleted-widget title callback was corrected by guarding invalid
  JavaScript `None`; ordinary/empty-title behavior and a removed-guard mutant were
  tested. The clean current full run does not establish the old segfault's cause.
- Old Linux diagnostic refs are deleted, never merged. Its worktree, all tracked
  bytes, raw evidence and verified private complete-history bundle are preserved.
- Qt on macOS can normalize Unicode argv canonically; do not promise byte-exact
  Unicode arguments or modify user scripts to hide this upstream limitation.
- Source credit is human-only; preserve Tahir's acknowledgement and `.githooks`.
  GitHub's contributor sidebar still cached CommandCodeBot at the last read-only
  check. No further history rewrite, watcher or support request was authorized.
- A future release needs explicit owner approval and deliberate eligible source/
  artifact binding; do not tag this skip-CI development checkpoint automatically.

## Evidence and tools — load details only when needed

Private durable accepted evidence (not public repo content):
- `~/.local/share/local-project-hub/acceptance/platforms-77aaa18/` — verified
  631-file manifest, all source raw logs, current three installers, Mac/Linux QA.
- `~/.local/share/local-project-hub/acceptance/callback-77aaa18-targeted/` — direct
  proof, real failed prior results, owner decision and diagnostic limitations.
- `~/.local/share/local-project-hub/acceptance/linux-popup-diagnostic-6b240e1/`

Scratch current root: `~/.hermes/cache/scratch/lph-release-0.7.4/candidate-v6/`.
The detailed live ledger is `../compatibility-pass/STATUS.md`; read its CURRENT
block only, not all historical checkpoints. Native MSI results live under
`windows-msi-native/` (first attempt), `run-v2/`, and current `run-v3/`.

`gh`: `/Users/iff/.local/bin/gh` (different2). Packaging/observer Python:
`~/.hermes/cache/scratch/lph-release-0.7.2/qt693-buildenv/bin/python`.
Existing `tests/run_all.py` can kill unrelated port holders; do not run it on
this Mac. Accepted QA used a disclosed scratch safety transport instead.
Never restart the gateway or user services to work around provider limits.

## Graphify — available and actually queried now

Existing untracked `graphify-out/graph.json` belongs to this repo; preserve it.
It contains 1,928 nodes / 4,864 edges, valid unique IDs/endpoints, and all 22
runtime-file manifest hashes matched current code. Actual CLI query and reverse
`calls` traversal identified `prepend_interpreter` consumers at
`hub/process_manager.py:394`, `hub/static_site.py:24`, and its platform test.
Source checks confirmed the two runtime consumers. This is useful architecture
navigation, not runtime proof; it did not diagnose the Windows environment bug.

Use only for relationship/navigation work, not every small edit. Keep
`GRAPHIFY_NO_AUTO_REFRESH=1` so the CLI preserves the owner's updated skill.
A focused command (no rebuild/model extraction needed):

```sh
GRAPHIFY_NO_AUTO_REFRESH=1 graphify affected hub_platform_prepend_interpreter --relation calls --depth 1 --graph graphify-out/graph.json
```
