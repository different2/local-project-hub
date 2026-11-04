# TEMP Windows native-MSI observer (v0.7.4)

**Never merge this QA branch into main.** This is implementation/calibration of an
acceptance observer, not independent review or release acceptance. It neither
builds nor publishes a release. Only the parent may commit/push/dispatch it.
No Windows executable is run on the Mac.

## Current binding is intentionally absent

`tools/windows_msi_candidate_reference.json` is deliberately NOT supplied. The
6b88effaa4663723d3e0666f6cf3dae4437a86ba build/run41804484621 and MSI
bb2d252cec20fce93fd095a55053616d9a172bd8f8f7856c7775da30541f2a11
(218460768 bytes) were superseded by a real source-matrix cleanup failure.
They are useful calibration inputs only, never the next release candidate.
Their actual read-only binding calibration is kept in the private evidence root
as `superseded-6b88eff-reference.json`, not in this dispatch transport.

The previous demonstrated 77aaa18 vector and its tests remain unchanged as
historical positive/negative controls. They are not used by the new native entry.

## Bind the next actual source/run/job/artifact/MSI

1. Freeze the parent's corrected source, then make a **separate owned clean
   source checkout** at that exact full SHA. Do not check out the QA branch as
   runtime source. Preserve canonical LF checkout bytes (`core.autocrlf=false`).
   The generator refuses tracked, untracked and ignored source contamination.
2. Read the exact source run and its explicit run-attempt jobs using `gh api`.
   Save the API JSON without rewriting fields:
   - `repos/different2/local-project-hub/actions/runs/$BUILD_RUN_ID` -> `run.json`
   - `repos/different2/local-project-hub/actions/runs/$BUILD_RUN_ID/attempts/$BUILD_ATTEMPT/jobs?per_page=100` -> `jobs.json`
   - `repos/different2/local-project-hub/actions/artifacts/$ARTIFACT_ID` -> `artifact.json`
   Retrieve all jobs if the count exceeds one page; never discard a count mismatch.
   This transport currently refuses truncated jobs JSON rather than guessing.
3. Obtain the actual `LocalProjectHub-Windows` artifact from that source run.
   Keep the raw ZIP downloaded **by artifact ID** from
   `repos/different2/local-project-hub/actions/artifacts/$ARTIFACT_ID/zip`.
   Keep the actual extracted `Local.Project.Hub.msi` too. On the Mac, binary
   shell redirection from `gh api .../zip` is safe; do not round-trip bytes through
   a PowerShell text pipeline. Obtain the actual MSI SHA-256 and byte count.
4. Run the generator from this QA checkout, substituting only independently
   observed values. Every argument is required; there are no plausible fake
   defaults and the output must not exist:

   ```sh
   "$PY" -B "$QA/tools/windows_msi_candidate.py" bind \
     --source-root "$SOURCE" --source-sha "$SOURCE_SHA" \
     --source-run-id "$BUILD_RUN_ID" --source-run-attempt "$BUILD_ATTEMPT" \
     --source-job-id "$WINDOWS_JOB_ID" --source-artifact-id "$ARTIFACT_ID" \
     --run-json "$META/run.json" --jobs-json "$META/jobs.json" \
     --artifact-json "$META/artifact.json" --artifact-zip "$ARTIFACT_ZIP" \
     --msi "$MSI" --msi-sha256 "$MSI_SHA256" --msi-bytes "$MSI_BYTES" \
     --output "$QA/tools/windows_msi_candidate_reference.json"
   ```

   Local interpreter used for these controls:
   `/Users/iff/.hermes/cache/scratch/lph-resume-ywdcm4ch/py311/bin/python`.
   `QA` is `/Users/iff/.hermes/cache/scratch/lph-release-v074-20261104/windows-qa`.

   Binding checks the literal source SHA, repository/main/dispatch/workflow,
   successful executed Windows builder, exact run/attempt/job/artifact IDs,
   GitHub ZIP digest, ZIP membership and contained MSI digest/size/container.
   It computes a fresh complete runtime vector directly from immutable Git
   blobs, never from installed or normalized payload bytes. The LF-to-CRLF
   vector is an explicit **prospective expectation**, not installed acceptance.
   If source/build EOL policy changes, stop and investigate; do not normalize
   installed evidence or tune the expectation from those installed bytes.
5. Record the generator's printed reference SHA-256. The parent may now inspect
   the diff, add that actual manifest to this TEMP branch, commit/push it, and
   dispatch the TEMP workflow with `reference_sha256` equal to that digest.
   Do not merge the historical QA branch into main. Rebinding to another source
   or artifact always means a **new manifest and new digest**. Preserve an older
   manifest outside the checkout instead of overwriting accepted evidence.

## What the TEMP workflow does

- Validates the explicit reference digest before choosing the separate runtime
  checkout's SHA, then re-reads and checks exact source-run/job/artifact metadata.
- Accepts an exact successful Windows builder while other source jobs are queued,
  running, or failed. That is authorization for **early installer inspection only**;
  the source matrix, publication and anonymous-download verification remain
  separate gates. A red source matrix is never relabelled green.
- Downloads the artifact by ID with binary-safe Python stdout, verifies the actual
  ZIP digest and sole MSI membership, then verifies the actual MSI raw digest/size.
- Calibrates the historical vector, new immutable-vector/rebinding/corruption
  controls, transport YAML, and blank-native-image rejection before installation.
- On the ephemeral AMD64 Windows-2025 host only, installs the exact MSI, compares
  all installed Python bytes/membership against the new reference strictly, and
  inspects separate PySide6-WebEngine6.12.0.140 alongside Qt/PySide6/shiboken6.12.0.
  Actual PE modules/DLLs/helper and nonempty resources/locales are required.
- Launches the actual installed PE with source hidden and isolated app state;
  requires nonce DOM, owned listeners/renderer, native Win32 window and native
  desktop pixels. CDP capture alone does not pass native-pixel acceptance.
- Requests ordinary WM_CLOSE and requires reaped exit0 with no forced cleanup or
  owned survivors. Refuses pre-existing exact/related/name-matching installs.
  Uninstalls only the ProductCode read from this exact pinned MSI database and
  verifies product/related/launcher absence. Restores and hashes the source.
- Retains raw canonical/expected/installed manifests before strict parity refusal,
  install/uninstall logs, native PNG/receipt and binding metadata. No browser
  profile, live registry or user project is uploaded.

Sandbox evidence remains launch-environment plus actual owned renderer argv;
Windows token-level sandbox attestation and real mouse gestures are not claimed.
The observer never changes the Mac's installed app or managed services.

## Local controls (no GUI or Windows execution)

```sh
export TMPDIR=/Users/iff/.hermes/cache/scratch
"$PY" -B "$QA/tools/test_smoke_windows_msi.py"
"$PY" -B "$QA/tools/test_windows_msi_candidate.py"
"$PY" -B "$QA/tools/test_windows_msi_workflow.py"
"$PY" -B "$QA/tools/temp_capture_windows_msi.py" --self-test
```

The workflow guard uses PyYAML; pixel controls use Pillow. Candidate/helper tests
otherwise use the standard library. All simulated API/PE/container controls are
explicitly labelled in tests and must not be cited as native MSI execution.
The workflow and Windows runtime remain unexecuted until the parent binds and
runs the next actual candidate on the real Windows host.
