# Development — Local Project Hub

Everything about building, testing, packaging, and releasing the Hub. If you
just want to use the app, see the [README](README.md). The project's current
state and open threads live in [HANDOFF.md](HANDOFF.md).

## Run from source

```bash
./run.sh          # uses ./.hubenv if present, else $PATH python3
```

Or set up the venv once (recommended — avoids PATH surprises):

```bash
python3 -m venv .hubenv
.hubenv/bin/pip install "PySide6==6.7.3" "PySide6-Essentials==6.7.3" "PySide6-Addons==6.7.3" "Pillow==11.3.0" "certifi==2026.10.18"
.hubenv/bin/pip install "pyobjc-framework-Cocoa==12.2.2; sys_platform == 'darwin'"   # Python >= 3.10; on 3.9 pip has no 12.x wheel (see "Dependency versions")
.hubenv/bin/python main.py
```

(Those are the project's pinned versions — see "Dependency versions" below.)

Notes:

- `run.sh` points the app's state at `./.hubstate` (via
  `LOCAL_PROJECT_HUB_HOME`), so a source run does not disturb the registry of
  an installed copy.
- The packaged app runs Python 3.11+ (wheels for arm64 macOS); this checkout
  also runs on the dev interpreter (3.9.6 on the author's machine), and the
  suite is kept green on both 3.9 and 3.11.

## Dependency versions (updated deliberately)

The GUI stack and the app's HTTPS trust store are pinned to **one coordinated
set** — CI, the packaged app, and both local venvs must all use exactly these:

```
PySide6==6.7.3
PySide6-Essentials==6.7.3   # the trio ships in lockstep; always the same version
PySide6-Addons==6.7.3
Pillow==11.3.0
certifi==2026.10.18         # CA trust store for the app's own HTTPS (see below)
pyobjc-framework-Cocoa==12.2.2   # macOS only; needs Python >= 3.10 (see below)
```

Where the pins live (they move together):

| File | Pins |
|---|---|
| `.github/workflows/ci.yml` | the whole set, in the test job and both build jobs |
| `pyproject.toml` → `requires` | the PySide6 pair, certifi and pyobjc — what briefcase bundles into the app |
| local venvs (`.hubenv`, `.buildenv`) | the whole set, installed by hand |

**Why 6.7.3 and not the latest:** briefcase installs the bundle's dependencies
with `pip --platform macosx_11_0_{arch}` (its macOS target comes from the
support settings), and PySide6 moved its macOS wheels to macOS-12+ tags in
6.8, macOS-13+ in 6.10 and macOS-14+ in 6.12. So 6.7.3 is the newest PySide6
the app bundle can actually install — and it is what the shipped builds
contain. Choosing newer Qt means changing what macOS the app targets, which
is a product decision, not a dependency bump. (6.12 also requires Python
≥3.10, which the 3.9 dev venv cannot take.)

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

1. Pick the version; check it against every consumer: the 3.9 dev venv, CI's
   3.11, Windows wheels, and the bundle (`pip --platform macosx_11_0_*`).
2. Bump every pin together: the install lines in `ci.yml`, `requires` in
   `pyproject.toml`, and both venvs —
   `.hubenv/bin/pip install "PySide6==X" …`, same for `.buildenv`. certifi
   and pyobjc live in the same places (pyobjc needs Python >= 3.10, so the
   3.9 dev venv cannot take 12.x).
3. Run the suite (`python3 tests/run_all.py`); `test_workflow_yaml.py` also
   fails if the pins drift apart or go unpinned.
4. Exercise packaging without releasing: `gh workflow run CI --ref main`.
5. Release as usual.

`pytest` and `PyYAML` are test-only tools and deliberately not part of the
set — they never ship.

## Tests

```bash
python3 tests/run_all.py
```

- **15 suites, run serially**: the GUI suites bind fixed ports on 127.0.0.1
  and cannot run concurrently — `run_all.py` serialises them and is what CI
  calls. A full run takes about half an hour on the author's Mac, more on CI
  runners.
- A single suite runs directly: `.hubenv/bin/python tests/test_store.py`.
- On a headless machine, prepend `QT_QPA_PLATFORM=offscreen`.
- CI currently runs the suite on **Windows only** — deliberately: that is
  where the open failures still are, macOS/Linux are covered by running the
  suite locally, and each extra platform costs runner capacity the others
  compete for. See the comment in `.github/workflows/ci.yml` before changing
  this.

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

Briefcase builds each platform on its own OS, so the Windows installer is
produced by GitHub Actions rather than locally:

- **Test packaging without cutting a release:**
  `gh workflow run CI --ref main` — both platforms build and upload their
  installers as downloadable artifacts. Nothing is published; only a `v*` tag
  creates a release (`tests/test_workflow_yaml.py` guards that property).
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

1. Bump `version` in `pyproject.toml` — it must match the tag exactly. Both
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

3. CI builds the macOS `.dmg` and Windows `.msi` and attaches both to the
   release. That release is also the update channel the in-app updater checks,
   so the next Check for Updates picks it up.

   Workflow steps run under bash on macOS but **PowerShell on Windows** —
   reference the tag as `${{ github.ref_name }}` in `run:` lines, never
   `"${GITHUB_REF_NAME}"` (that expands to nothing under PowerShell; it is
   exactly how the tag/version guard died at its first step on the Windows
   runner). `tests/test_workflow_yaml.py` pins the correct form.

4. Once the release is published (tag run green): apply the release notes
   (`gh release edit vX.Y.Z --notes-file <file>`) and bump the README's
   **Download** section — it is version-pinned on purpose, so the front page
   always names a concrete latest build.

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
