# Development — Local Project Hub

Everything about building, testing, packaging, and releasing the Hub. If you
just want to use the app, see the [README](README.md). The project's current
state and open threads live in [HANDOFF.md](HANDOFF.md).

## Run from source

```bash
./run.sh          # uses ./.hubenv if present, else $PATH python3
```

Or set up the venv once on macOS (recommended — avoids PATH surprises):

```bash
python3 -m venv .hubenv
.hubenv/bin/pip install "PySide6==6.9.3" "PySide6-Essentials==6.9.3" "PySide6-Addons==6.9.3" "Pillow==11.3.0" "certifi==2026.10.18"
.hubenv/bin/pip install "pyobjc-framework-Cocoa==12.2.2; sys_platform == 'darwin'"   # Python >= 3.10; on 3.9 pip has no 12.x wheel (see "Dependency versions")
.hubenv/bin/python main.py
```

Windows uses Python 3.11 and the separately validated Windows Qt version:

```powershell
py -3.11 -m venv .hubenv
.\.hubenv\Scripts\python.exe -m pip install "PySide6==6.12.0" "PySide6-Essentials==6.12.0" "PySide6-Addons==6.12.0" "Pillow==11.3.0" "certifi==2026.10.18"
$env:LOCAL_PROJECT_HUB_HOME = Join-Path $PWD '.hubstate'
.\.hubenv\Scripts\python.exe main.py
```

See "Dependency versions" below before changing either platform's pins.

Notes:

- `run.sh` points the app's state at `./.hubstate` (via
  `LOCAL_PROJECT_HUB_HOME`), so a source run does not disturb the registry of
  an installed copy.
- The packaged app and Windows development use Python 3.11+. The macOS source
  checkout also supports the existing 3.9.6 dev interpreter with Qt 6.9.3;
  the newer Windows Qt is not compatible with Python 3.9.

## Dependency versions (updated deliberately)

The GUI stack is pinned to **one coordinated set per OS**. Within each OS,
CI, packaging and the local venv must agree; do not mix versions of the three
PySide6 distributions.

| Dependency | macOS | Windows | Ubuntu 24.04 amd64 |
|---|---|---|---|
| PySide6, PySide6-Essentials, PySide6-Addons | 6.9.3 | 6.12.0 | 6.7.3 |
| Pillow (build/test tool) | 11.3.0 | 11.3.0 | 11.3.0 |
| certifi | 2026.10.18 | 2026.10.18 | 2026.10.18 |
| pyobjc-framework-Cocoa | 12.2.2 (Python 3.10+; see dev exception below) | not installed | not installed |

The `sys_platform` markers in `pyproject.toml` select the platform's pair.
Windows CI/build use 6.12.0; macOS uses 6.9.3; Linux retains 6.7.3. The test
install evaluates the same platform markers. Linux source development uses the
same venv recipe above with all three PySide6 versions set to 6.7.3.

Where the pins live (they move together):

| File | Pins |
|---|---|
| `.github/workflows/ci.yml` | the coordinated test set and Windows/Linux builders; the local Mac helper checks package pins |
| `pyproject.toml` → `requires` | the PySide6 pair, certifi and pyobjc — what briefcase bundles into the app |
| local venvs (`.hubenv`, `.buildenv`) | the whole set, installed by hand |

**Why 6.9.3 on macOS:** Qt6.7.3 can crash after an accessibility client has
enumerated list cells and their values/order change. The native stack reaches
`QMacAccessibilityElement dealloc`; the upstream
[QTBUG-134784 fix](https://code.qt.io/cgit/qt/qtbase.git/commit/?id=b1ed5f656f064e553b33752f8e87d2f5b9553e38)
corrects cached-element reference counting (first public fix in Qt6.9.1).
The exact same minimized native AX/mutation/normal-quit control exits-11 with
6.7.3 and0 with6.9.3. This is not a mouse-only workaround or disabled accessibility.
The owner authorized a Mac-only runtime correction before finishing0.7.2.

Qt6.9 supports [macOS12+](https://doc.qt.io/qt-6.9/supported-platforms.html);
the6.9.3 Essentials/Addons wheels are `macosx_12_0_universal2`/`cp39-abi3`.
The correctly configured `min_os_version = "12.0"` selects that deployment
floor; an older claim that the builder was necessarily targeting11.0 is stale.
Neither the macOS12.0 floor nor Python3.9 source support is raised. Keep the
local dev/build environments on the matching trio (older6.7.3 environments
are not updated automatically). Runtime verification must still exercise the
actual rebuilt installer with AX observation, native drag, persistence and a
clean real process exit; source tests alone cannot verify this defect.

**Why 6.12.0 on Windows:** the old 6.7.3 renderer crashes on the Windows 2025
host, even for a bare WebEngine page. In the
[controlled old/new comparison](https://github.com/different2/local-project-hub/actions/runs/40168797374),
6.12.0 passed bare native/offscreen rendering and the real Hub start-page,
Start and popup cases on both Windows hosts with the sandbox enabled. The old
version failed those same cases on the newer host. Deliberately wrong-title
controls remained red, so successful observation collection was not confused
with successful rendering. This is a platform-specific dependency correction,
not a sandbox bypass or an increase in the macOS 12.0 support floor.

**Why certifi:** the packaged app's Python has no default CA store — its
compiled-in paths point at the python.org framework location, which is not
inside the app — so without certifi every HTTPS request from the app dies as
`CERTIFICATE_VERIFY_FAILED`. That is how 0.4.0 and 0.4.1 shipped: the in-app
update check reported "Could not reach the update server" on a perfectly
healthy connection (reproduced inside the shipped bundle, 2026-10-18). The
updater builds its SSL context from certifi
(`hub/updater.py::_ssl_context`) and falls back to the system CA files for
source runs without it.

**Why pyobjc 12.2.2:** it is what the shipped bundles (0.3.8, 0.4.x) contain;
a floating pin would let a rebuild silently change the AppKit behaviour the
About box was verified against. pyobjc 12.x ships wheels for Python 3.10+
only, so the 3.9 dev venv (`.hubenv`) keeps 11.1 — the newest it can take —
and the AppKit path is exercised against 12.2.2 in the packaged app.

**To update the set, deliberately, as one change:**

1. Pick the OS and version; check its Python/wheel/deployment requirements.
   A Windows update must not silently raise the macOS or dev-Python floor.
2. Bump that OS's CI install lines, matching `sys_platform` requirements in
   `pyproject.toml`, and its local venvs together. Keep the PySide6 trio in
   lockstep. certifi and pyobjc remain coordinated in the same places.
3. Run the suite (`python3 tests/run_all.py`); `test_workflow_yaml.py` also
   fails if the pins drift apart or go unpinned.
4. Exercise packaging without releasing: `gh workflow run CI --ref main`.
5. Release only when separately intended; a dependency fix or merge is not
   itself authorization to publish or replace an installed copy.

`pytest` and `PyYAML` are test-only tools and deliberately not part of the
set — they never ship.

## Tests

```bash
python3 tests/run_all.py
```

- **21 suites, run serially**: the GUI suites bind fixed ports on 127.0.0.1
  and cannot run concurrently — `run_all.py` serialises them and is what CI
  calls. A full run takes about half an hour on the author's Mac, more on CI
  runners.
- A single suite runs directly: `.hubenv/bin/python tests/test_store.py`.
- On a headless machine, prepend `QT_QPA_PLATFORM=offscreen`.
- CI runs the full suite on **Ubuntu 24.04, Windows 2022 and Windows 2025**,
  serially across the matrix; macOS is verified locally. Linux uses Python 3.12
  to match the native package; Windows uses 3.11.
- CI invokes `tools/run_regression_strict.py --output NEW_DIRECTORY`, which
  wraps the real runner, records every raw child exit/output, and refuses a
  crash after printed PASS or a child with no verdicts. The ordinary runner's
  older Qt-shutdown tolerance is not treated as release acceptance. The audit's
  simulated calibration cases remain separate from actual result artifacts.
- `test_linux_smoke.py` adapts 17 pure unittest observer controls to one
  Linux-only PASS-protocol case. Other OSes explicitly skip that Linux observer
  case; this is distinct from the actual installed-app smoke below.
- Windows images are pinned rather than `windows-latest`; the Windows builder
  uses 2025 too. The older-image pin originally avoided a Qt 6.7.3 CI blocker,
  but did not fix newer-Windows compatibility. The platform-specific Qt update
  now addresses that failure without disabling the renderer sandbox.
- `test_workflow_yaml.py` checks per-OS package/CI/build coherence, the actual
  loaded Qt version, both Windows images, absence of CI sandbox bypasses and
  preservation of the macOS dependency/support floor. Handoff records name
  the exact heads and full-suite results; targeted controls alone are not a
  full product regression pass.

## Repo layout

```
main.py                  app entry point
hub/
  store.py               project registry (JSON) + validation
  process_manager.py     process spawn / stop / status / log capture
  readiness.py           TCP + HTTP readiness polling
  urldetect.py           reads the dashboard URL from a server's output
  detect_type.py         project type detection (web/static/desktop/cli)
  detect_command.py      proposes a start command by reading a folder or file
  window.py              main window: sidebar, tabs, log drawer
  project_dialog.py      add/edit project form
  platform.py            every OS difference, isolated here
  updater.py             in-app update check against GitHub Releases
  update_config.py       update endpoint + issues URL (public URLs, not secrets)
  selfupdate.py          stages a downloaded .app, swaps it in after the app quits
  diagnostics.py         error reports (no project data, by design)
  launch_at_login.py     opt-in launch at login, per platform
  macos_buttons.py       AppKit helpers (About box window buttons)
tools/
  make_icons.py          resize + wrap the approved artwork
  check_tag_version.py   fails a release build when the tag != pyproject version
tests/                   run with python3 tests/run_all.py
```

## Packaging

Shared release transport/bundle checks remain compatible with the Python 3.9
development environment. Only the five local macOS packaging/toolchain checks
explicitly report SKIP below Python 3.11; run the suite with the Python 3.11
build environment for those checks. This does not change application support.

macOS is built and tested **locally on the developer's Mac**. No hosted
macOS runner is used. Windows and Ubuntu binaries are built/executed on their
actual GitHub runners, never on the Mac. An Ubuntu job only relays the already
built, source-bound DMG into the complete release artifact set.

- **Build macOS locally with the existing pinned build environment:**

  ```bash
  .buildenv/bin/python tools/build_macos_release.py vX.Y.Z --output release-assets
  ```

  The helper requires Darwin, Python 3.11, clean tracked source, Briefcase
  0.4.6 and the platform dependency pins. It builds the actual app, checks its
  main Info.plist version and macOS 12.0 floor, bundled hub metadata, renderer
  helper and byte-identical application sources **before** packaging. It uses
  `-p dmg --adhoc-sign --no-input`, collects `Local.Project.Hub.dmg` without
  clobbering an existing output, and runs `hdiutil verify`. It never installs
  into Applications or restarts the user's app. Also exercise the packaged
  app locally with isolated state before publishing; header fixtures are not
  installer/runtime acceptance.
- **Test Windows/Linux packaging without publishing:**
  `gh workflow run CI --ref <candidate>` runs their native builders and source
  regression. A dispatch never stages a Mac release input or publishes,
  including when the selected ref is already a version tag.
- **Linux-only packaging diagnosis:**
  `gh workflow run CI --ref <branch> -f linux_only=true` skips the regression
  matrix and other jobs, but still installs/runs the Linux package. It is not
  a substitute for final full regression acceptance.
- **The toolchain is pinned:** Briefcase 0.4.6 is checked locally and installed
  by the Windows/Linux builders. Qt platform pins stay coordinated with
  `pyproject.toml`; macOS uses Qt 6.9.3 while retaining the macOS 12 support floor.
- **Icons:** `python3 tools/make_icons.py path/to/artwork.png`.
- **Do not change `bundle` in `pyproject.toml`** (or rename the app key): the
  Windows MSI's UpgradeCode is derived from it. Changing it silently stops
  MSI upgrades from replacing older installs.

## Releasing

1. Bump `version` in `pyproject.toml` and update the changelog. Freeze/review
   the candidate and run local source checks. Keep the release commit clean;
   application source, version and package inputs must not change after the
   local Mac build. The tag/version guard runs locally and in both native
   builders plus the publisher's Mac-input step.
2. Build and exercise the actual macOS installer locally, retaining its source
   SHA and full digest. Do not change the installed user app to test it.
3. Push the source candidate and require a successful CI source run for that
   exact SHA (Windows 2022/2025 and Ubuntu). Do not push a commit and tag
   together or overlap duplicate full runs.
4. Create a **new immutable annotated tag**, targeting the explicit tested SHA:

   ```bash
   sha="$(git rev-parse HEAD)"
   tag=vX.Y.Z
   git tag -a "$tag" "$sha" -m "$tag"
   git push origin "$tag"
   ```

   Never force/retag a release. A `[skip ci]` marker in the tagged commit
   suppresses push/tag workflows; do not tag such a commit. Verify the tag
   run actually appeared and that it uses the tested SHA.
5. Immediately prepare the private draft and upload the already-verified Mac
   DMG with its exact source receipt; it must be ready before staging starts:

   ```bash
   gh release create "$tag" --verify-tag --target "$sha" --draft \
     --prerelease=false --latest=false --title "$tag" --notes-file release-notes.md
   gh release upload "$tag" "release-assets/Local.Project.Hub.dmg#source:$sha"
   ```

   For an existing draft, resume only after reading `isDraft=true`; never
   replace assets of a public release. The `source:<40-hex-SHA>` asset label
   binds the prebuilt DMG to the exact tag job's source. The publisher waits for
   source tests/native builders, checks the private release by **release ID**, validates
   tag/repository/preview URL/source label/upload state/size/digest, downloads
   and collects the DMG, and checks its actual size/full hash/footer before
   any release upload. It does not compile or execute macOS binaries. Draft
   visibility needs push access; reuse only the publisher's existing write
   token, leaving source/build jobs read-only (GitHub CLI issue3037).
6. CI requires source tests, the Windows build and installed Ubuntu runtime
   acceptance, then the unskippable local-Mac input gate. Publication preserves the Mac source
   label and resumes only a private draft. All **three** stable installer names,
   upload states, URLs, sizes and SHA-256 digests must validate before the
   release is made public and explicitly marked latest; the same release ID
   is read back and revalidated afterward. Only an actual tag **push** may
   publish; manual dispatches, even of a tag ref, cannot.
7. Read back the final title/notes/assets and verify every latest-download URL
   anonymously. URLs use `/releases/latest/download/<stable-name>` and match
   `tools/release_artifacts.py::ASSET_NAMES`; never add a hardcoded version
   label to the front page. Confirm the installed version is offered the new
   release through the updater, without installing it unless authorized.

The release is the macOS/Windows in-app update channel. Ubuntu currently uses
manual download and APT, not one-click in-app installation. Workflow tag
arguments use `${{ github.ref_name }}`, not bash-only `${GITHUB_REF_NAME}`,
so the Windows PowerShell builder receives the literal correct tag.

### Ubuntu package and installed-runtime acceptance

The first Linux target is **Ubuntu 24.04 amd64 only** (glibc 2.39, system Python
3.12), not a portable AppImage or a package for arbitrary distributions. The
pinned Briefcase AppImage backend explicitly discourages binary-wheel GUI apps.
Native `linux system` builds must run under a venv created by `/usr/bin/python3`:
Briefcase compares the complete interpreter version, not only its minor number.
`CHANGELOG.md` is required by the native backend. Noble runtime dependencies are
declared in `pyproject.toml` and installed by APT; Xvfb/openbox/observer libraries
are CI tools, not desktop-user package dependencies.

CI packages with `briefcase package linux system -p deb --adhoc-sign --no-input`,
installs the exact `.deb`, then starts installed `/usr/bin/hub` as a normal user
outside checkout under Xvfb/DBus/openbox. The source app is hidden/restored to
prove it was not accidentally tested. `tools/smoke_linux_installer.py` verifies
installed metadata (the app's version is not a literal), real project launch,
URL discovery, exact nonce DOM, a visible native frame/screenshot and renderer
NoNewPrivs/Seccomp evidence. A wrong-text invocation must fail for that reason,
with source restored and all owned processes cleaned. Evidence is uploaded even
on failure. Never accept diagnostic collection alone as successful app runtime.

Sandbox-disabling flags, root execution and global AppArmor weakening are not
accepted workarounds. Record the runner's policy and scope the support claim;
GitHub acceptance is not evidence for every Linux desktop/security policy.

## Signing

Current builds are ad-hoc signed (macOS) and unsigned (Windows): they run, but
Gatekeeper/SmartScreen warn on first launch. For a signed release you need
paid certificates:

- **macOS** — an Apple Developer account. Sign with
  `briefcase package macOS -i "Developer ID Application: …"`; notarisation
  then runs as part of packaging once credentials are configured. There is no
  `--notarize` flag — `--no-notarize` opts out, which is the default when no
  identity is available.
- **Windows** — an Authenticode code-signing certificate.

Certificates and passwords must never be committed; they belong in CI secrets.

## Contributing

Contributions are welcome. Please run `python3 tests/run_all.py` before opening
a pull request, and keep platform-specific code inside `hub/platform.py` so the
rest of the app stays OS-agnostic.
