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
.hubenv/bin/pip install PySide6 PySide6-Addons PySide6-Essentials Pillow
.hubenv/bin/python main.py
```

Notes:

- `run.sh` points the app's state at `./.hubstate` (via
  `LOCAL_PROJECT_HUB_HOME`), so a source run does not disturb the registry of
  an installed copy.
- The packaged app runs Python 3.11+ (wheels for arm64 macOS); this checkout
  also runs on the dev interpreter (3.9.6 on the author's machine), and the
  suite is kept green on both 3.9 and 3.11.

## Tests

```bash
python3 tests/run_all.py
```

- **14 suites, run serially**: the GUI suites bind fixed ports on 127.0.0.1
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
  window.py              main window: sidebar, tabs, log drawer
  project_dialog.py      add/edit project form
  platform.py            every OS difference, isolated here
  updater.py             in-app update check against GitHub Releases
  update_config.py       update endpoint + issues URL (public URLs, not secrets)
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
2. Commit, then tag and push:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

3. CI builds the macOS `.dmg` and Windows `.msi` and attaches both to the
   release. That release is also the update channel the in-app updater checks,
   so the next Check for Updates picks it up.

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
