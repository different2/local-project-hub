# Local Project Hub

A cross-platform desktop app that registers local projects, launches their
backends, and shows their web dashboards in one window (PySide6 + QtWebEngine).

Any project works: **Python, Node, Go, Rust, or a shell script** — the hub runs
the startup command you configure and waits for the dashboard URL to answer.

Your projects stay exactly where they are. The Hub never touches their source,
their virtual environments, or their dependencies.

[![CI](https://github.com/different2/local-project-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/different2/local-project-hub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Download

Grab the latest installer from
[Releases](https://github.com/different2/local-project-hub/releases):

| Platform | File | Notes |
|---|---|---|
| macOS | `LocalProjectHub-macOS-*.dmg` | Open the disk image, drag the app to Applications |
| Windows | `LocalProjectHub-Windows-*.msi` | Double-click to install |

No Python installation is needed to *run* the Hub. You do need the relevant
runtime installed for the projects you register (Python for Python projects,
Node for Node projects).

> **Windows note:** the installer is not code-signed yet, so SmartScreen shows
> "Windows protected your PC". Click **More info → Run anyway**. Code signing
> needs a paid certificate; see [Signing](#signing) below.

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

## Tests

```bash
python3 tests/run_all.py
```

53 tests across 6 suites. The GUI suites bind fixed ports, so they run
serially — `run_all.py` handles that and is what CI calls.

## Where your data lives

| What | Where |
|---|---|
| Project registrations | macOS `~/Library/Application Support/LocalProjectHub/`, Windows `%LOCALAPPDATA%\LocalProjectHub\`, Linux `~/.local/share/local-project-hub/` |
| Your projects | untouched, in their original folders |

Updating or uninstalling the Hub never modifies a registered project.

## Building the installers

Briefcase builds each platform on its own OS, so the Windows installer is
produced by GitHub Actions rather than locally:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The tagged release builds the macOS `.dmg` and Windows `.msi` in parallel and
attaches them to the release, which is also what the in-app updater checks.

To test packaging **without** cutting a release, run the workflow by hand:

```bash
gh workflow run CI --ref main
```

Both platform builds run and upload their installers as downloadable artifacts.
Nothing is published: only a `v*` tag creates a release, so a manual run can
never ship anything. This exists because the build jobs were previously
reachable only via a tag, which meant a broken packaging change could not be
discovered except by spending a release on it.

To build locally on macOS:

```bash
pip install briefcase
briefcase create macOS && briefcase build macOS && briefcase package macOS -p dmg
```

`-p dmg` is the packaging format (`-p/--packaging-format` takes `zip`, `dmg` or
`pkg`). A GUI app already defaults to `dmg`, but state it so the command does
not depend on that default. Note there is no `--dmg` flag — briefcase rejects
it, and a build script that used it would fail.

Icons are regenerated from source art with:

```bash
python3 tools/make_icons.py path/to/artwork.png
```

## Signing

Unsigned builds work but trigger OS trust warnings. For a signed release you
need:

- **macOS** — an Apple Developer account (paid). Sign with
  `briefcase package macOS -i "Developer ID Application: …"`; notarization
  then runs as part of packaging once credentials are configured. There is no
  `--notarize` flag — `--no-notarize` opts out, which is the default when no
  identity is available.
- **Windows** — an Authenticode code-signing certificate (paid)

Certificates and passwords must never be committed; they belong in CI secrets.

## Contributing

Contributions are welcome. Please run `python3 tests/run_all.py` before opening
a pull request, and keep platform-specific code inside `hub/platform.py` so the
rest of the app stays OS-agnostic.

Found a bug? Use **Help → Report a Problem** in the app — it writes a report
with the version and your OS, and deliberately contains none of your project
data. Or open an
[issue](https://github.com/different2/local-project-hub/issues/new).

## Layout

```
main.py                app entry point
hub/
  store.py             project registry (JSON) + validation
  process_manager.py   process spawn / stop / status / log capture
  readiness.py         TCP + HTTP readiness polling
  window.py            main window: sidebar, tabs, log drawer
  project_dialog.py    add/edit project form
  platform.py          every OS difference, isolated here
  updater.py           in-app update check against GitHub Releases
  diagnostics.py       error reports (no project data by design)
  launch_at_login.py   opt-in launch at login, per platform
tools/
  make_icons.py        resize + wrap the approved artwork
tests/                 run with python3 tests/run_all.py
```

## License

[MIT](LICENSE)
