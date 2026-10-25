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
.hubenv/bin/pip install "PySide6==6.7.3" "PySide6-Essentials==6.7.3" "PySide6-Addons==6.7.3" "Pillow==11.3.0" "certifi==2026.10.18"
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
  checkout also supports the existing 3.9.6 dev interpreter with Qt 6.7.3;
  the newer Windows Qt is not compatible with Python 3.9.

## Dependency versions (updated deliberately)

The GUI stack is pinned to **one coordinated set per OS**. Within each OS,
CI, packaging and the local venv must agree; do not mix versions of the three
PySide6 distributions.

| Dependency | macOS | Windows | Ubuntu 24.04 amd64 |
|---|---|---|---|
| PySide6, PySide6-Essentials, PySide6-Addons | 6.7.3 | 6.12.0 | 6.7.3 |
| Pillow (build/test tool) | 11.3.0 | 11.3.0 | 11.3.0 |
| certifi | 2026.10.18 | 2026.10.18 | 2026.10.18 |
| pyobjc-framework-Cocoa | 12.2.2 (Python 3.10+; see dev exception below) | not installed | not installed |

The `sys_platform` markers in `pyproject.toml` select the platform's pair.
Windows CI/build use 6.12.0; macOS and Linux retain 6.7.3. The test install
evaluates the same platform markers rather than forcing the Windows pin on Linux.

Where the pins live (they move together):

| File | Pins |
|---|---|
| `.github/workflows/ci.yml` | the coordinated set in the test job and all three build jobs |
| `pyproject.toml` → `requires` | the PySide6 pair, certifi and pyobjc — what briefcase bundles into the app |
| local venvs (`.hubenv`, `.buildenv`) | the whole set, installed by hand |

**Why retain 6.7.3 on macOS:** briefcase installs the bundle's dependencies
with `pip --platform macosx_11_0_{arch}` (its macOS target comes from the
support settings), and PySide6 moved its macOS wheels to macOS-12+ tags in
6.8, macOS-13+ in 6.10 and macOS-14+ in 6.12. So 6.7.3 is the newest PySide6
the current macOS bundle can actually install — and it is what the shipped builds
contain. Choosing newer Qt means changing what macOS the app targets, which
is a product decision, not a dependency bump. (6.12 also requires Python
≥3.10, which the 3.9 dev venv cannot take.)

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

Briefcase builds each platform on its own OS. Windows and Ubuntu binaries are
built/executed on GitHub runners, never on the developer's Mac:

- **Test packaging without cutting a release:**
  `gh workflow run CI --ref main` — all three platforms build and upload their
  installers as downloadable artifacts. Nothing is published; only a `v*` tag
  creates a release (`tests/test_workflow_yaml.py` guards that property).
- **Linux-only packaging diagnosis:**
  `gh workflow run CI --ref <branch> -f linux_only=true` skips the regression
  matrix and other builders, but still installs/runs the Linux package. It can
  never publish and is not a substitute for final full regression acceptance.
- **Build locally on macOS:**

  ```bash
  pip install "briefcase==0.4.6"   # keep this matching the CI pin
  briefcase create macOS && briefcase build macOS && briefcase package macOS -p dmg
  ```

  `-p dmg` is the packaging format (`zip`/`dmg`/`pkg`). There is no `--dmg`
  flag — briefcase rejects it.
- **The toolchain is pinned:** CI installs `briefcase==0.4.6`, the version
  v0.3.7/v0.3.8 were built with, so releases cannot silently depend on
  whatever PyPI resolves that day. Bump the pin as its own reviewed change;
  `tests/test_workflow_yaml.py` fails if the install goes unpinned.
- **Icons:** `python3 tools/make_icons.py path/to/artwork.png`
- **Do not change `bundle` in `pyproject.toml`** (or rename the app key): the
  Windows MSI's UpgradeCode is derived from it, and changing it silently stops
  MSI upgrades from replacing older installs. The comment there has details.

## Releasing

1. Bump `version` in `pyproject.toml` — it must match the tag exactly. All three
   build jobs run `tools/check_tag_version.py` first, which fails in seconds
   if they disagree (a mismatch ships an app that offers the same update
   forever).
2. Commit, then tag the **release commit by explicit sha** and push:

   ```bash
   git tag vX.Y.Z <sha> && git push origin vX.Y.Z
   ```

   Two traps make tag pushes silently do nothing (both hit for real on
   2026-10-18 — see HANDOFF "release night"):

   - A `[skip ci]` marker in the tagged commit's message suppresses the whole
     build. Docs-only commits here use that marker — never let one be the tag
     target (hence the explicit sha; never tag bare HEAD without checking
     `git log -1`).
   - After pushing, **verify a run appeared** (`gh run list --limit 5`). No
     run means it was skipped, not queued.

3. CI waits for full tests and every platform builder, then creates a private
   draft and attaches macOS `.dmg`, Windows `.msi` and Ubuntu `.deb`. It filters
   installer artifacts rather than publishing test logs. Only after all three
   names, upload states, URLs, sizes and SHA-256 digests validate does it publish
   and explicitly mark the release latest; published metadata is read back.
   The release is the macOS/Windows in-app update channel; Linux initially uses
   manual download plus APT. Do not silently imply Linux one-click updates.

   Workflow steps run under bash on macOS but **PowerShell on Windows** —
   reference the tag as `${{ github.ref_name }}` in `run:` lines, never
   `"${GITHUB_REF_NAME}"` (that expands to nothing under PowerShell; it is
   exactly how the tag/version guard died at its first step on the Windows
   runner). `tests/test_workflow_yaml.py` pins the correct form.

4. Once the release is published (tag run green), apply/read back release notes
   (`gh release edit vX.Y.Z --notes-file <file>`) and verify every README link
   anonymously. The front page uses `/releases/latest/download/<stable-name>`;
   filenames must match `tools/release_artifacts.py::ASSET_NAMES`, not include
   the app version. There is no hardcoded latest-version label to go stale.
   For the first switch to these names, publish the verified branch/tag before
   merging its README, so the live front page never advertises missing assets.

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
