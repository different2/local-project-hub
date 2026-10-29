# Local Project Hub

A desktop app that keeps your local projects in one window: register a folder,
press start, and its web dashboard opens in a tab. Works with anything
launchable — **Python, Node, Go, Rust, or a shell script** — and runs on macOS,
Windows, and Linux (Ubuntu 24.04 x86-64).

[![CI](https://github.com/different2/local-project-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/different2/local-project-hub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

- **One window for every dashboard.** Each project gets its own tab — select
  one in the sidebar, then start, stop, restart, or open it in a real browser
  from the toolbar.
- **Fills in the startup command.** Point the Hub at a project folder — or at
  the file that starts it — and it fills in the command that runs the project
  (Node, Python, Go, Rust, a plain HTML page). You can always edit what it
  suggests.
- **Waits until the dashboard actually answers.** The Hub polls the URL until
  the server responds, then shows the page — no blank pane, no guessed
  success.
- **Finds the dashboard URL for you.** Most servers print their address when
  they start; the Hub reads it from the output and fills it in. Leave the URL
  field blank and it looks after itself.
- **Handles port conflicts.** If another program already holds a project's
  port, the Hub spots it and offers to end that process — or leaves it alone.
  Nothing is killed without asking.
- **Remembers each project.** Folder, command, environment, options — saved
  per project and reused on every launch.

Your projects stay exactly where they are. The Hub runs the startup command
you configure, from the folder you point it at, and never touches your
projects' source, virtual environments, or dependencies.

## Download

[Latest release and release notes](https://github.com/different2/local-project-hub/releases/latest).
These download links always follow the latest published release.

| Platform | File | Install |
|---|---|---|
| macOS 12+ (Apple silicon) | [Download `.dmg`](https://github.com/different2/local-project-hub/releases/latest/download/Local.Project.Hub.dmg) | Open the disk image, drag the app to Applications |
| Windows x86-64 | [Download `.msi`](https://github.com/different2/local-project-hub/releases/latest/download/Local.Project.Hub.msi) | Double-click the installer |
| Linux: Ubuntu 24.04 LTS x86-64 | [Download `.deb`](https://github.com/different2/local-project-hub/releases/latest/download/Local.Project.Hub.Ubuntu-24.04-amd64.deb) | In the download folder: `sudo apt install ./Local.Project.Hub.Ubuntu-24.04-amd64.deb` |

Older versions: [Releases](https://github.com/different2/local-project-hub/releases).

> **Read this before your first launch.** The macOS/Windows installers do not
> yet have trusted publishing signatures — those require paid developer
> credentials — so these operating systems warn on the first launch:
>
> - **macOS:** if macOS says it cannot check the app for malicious software,
>   Control-click (right-click) the app and choose **Open → Open**. This is
>   needed once; it can come back after an update.
> - **Windows:** if SmartScreen shows *"Windows protected your PC"*, click
>   **More info → Run anyway**.

## Requirements

- macOS/Windows installers bundle the runtime. On Ubuntu, APT installs the
  required system Python and libraries automatically; no manual Python setup.
- Your projects need their own tooling, as usual: the Hub runs the command
  you give it and does not install or manage dependencies.
- The macOS build needs macOS 12 or newer.
- The Linux package targets **Ubuntu 24.04 on x86-64**, not every Linux
  distribution or CPU. A graphical desktop and working Qt WebEngine sandbox
  support are required. Do not run the Hub as root or disable its sandbox.

## Using it

1. **Add a project** — press **+ Add** in the toolbar and give it a display
   name and the project folder — or press **File…** and pick the script that
   starts it. The Hub reads what you chose and fills in the startup command —
   adjust it if needed. Leave **Dashboard URL** blank for most projects: if
   the server prints its address, the Hub detects it.
2. **Open it** — click the project in the sidebar to view its dashboard or
   launch page. Press **Start** to launch it; the dashboard opens in a tab once
   the server answers.
3. **Drive it** — **Start**, **Stop**, **Restart**, and **Open in browser**
   act on the project you are viewing. Everything a project prints appears in
   the **log drawer** at the bottom; toggle it with **Logs**.

Worth knowing:

- Drag projects up or down in the sidebar to arrange them. The order is saved
  across restarts; new projects are added at the bottom. Double-click a name
  to rename it without changing its position.
- Adding or selecting a project does not start it. Press **Start** to run it,
  or tick **Start automatically when the hub opens** to opt that project into
  autostart.
- Desktop apps get launched in their own window instead of a tab.
- The Hub's own tab is a short getting-started page; reopen it via the app
  menu's **Show Overview** if you close it.

### Project opening — 0.7.4 release candidate

The candidate also corrects project-specific PATH/interpreter selection, Windows
command quoting and Python aliases, old saved Python commands, actual startup
error reporting, safe automatic browser flags, silent-server discovery and stale
readiness checks after Edit/Restart. Split stdout deliveries no longer save a
partial dashboard address. These changes are **not yet in published installers**.

For custom Python scripts, automatic browser flags are skipped when multiple
parsers, subcommands or cross-scope declarations make the option's applicability
uncertain. Explicit extra arguments are always left alone.

Commands are launched without an implicit shell: for shell operators, activation
or variable expansion, explicitly invoke the shell yourself. A silent server's
port discovery is best-effort; set **Dashboard URL** when its address cannot be
discovered. On macOS, the bundled Qt runtime may normalize Unicode command-line
arguments to a canonically equivalent form; exact Unicode code-point preservation
is not guaranteed. Hub does not rewrite the saved values or the project's files.

### Standalone HTML — 0.7.4 release candidate

**File…** remembers the HTML page you picked, including folders with several
pages. For older Python `http.server` registrations, a sole HTML page opens
instead of a folder listing; explicit routes and uncertain choices stay intact.

Inside Hub, local Python static sites also get private, persistent
`window.storage.get/set` compatibility for generated HTML that uses that API.
Each project has its own browser storage under Hub's settings directory, not
inside your project. Browser storage quotas still apply; shared/cloud storage
is not provided. This compatibility does not extend to an external browser.
These changes are not yet in the published installers.

## Updating

**Help → Check for Updates…** shows the newest release; **Download and
Install** fetches the installer and continues only when the release publishes a
SHA-256 digest and the downloaded file matches it. A release with no usable
digest is reported as unverifiable and is **not** installed. On macOS the app
then offers **Restart and Install**: it closes, puts the new version in place
and reopens by itself — the copy it replaces goes to the Trash, and if anything
goes wrong the old copy is put back before you see it. On Windows, the
installer runs. Your projects and settings are untouched.

**Linux:** download the latest `.deb` above and run the same `sudo apt install`
command again. Linux updates currently use APT/manual installation, not the
macOS/Windows in-app installer flow.

## Where your data lives

| What | Where |
|---|---|
| Project registrations | macOS `~/Library/Application Support/LocalProjectHub/`, Windows `%LOCALAPPDATA%\LocalProjectHub\`, Linux `~/.local/share/local-project-hub/` |
| Your projects | untouched, in their original folders |

Updating or uninstalling the Hub never modifies a registered project.

## Problems or feedback

**Help → Report a Problem…** builds a report with the app version, your OS,
and a sanitised summary of the hub's own messages — never your projects'
names, folders, commands, raw output, dashboard contents, or URLs — and can
save it or open a pre-filled issue. Or open an
[issue](https://github.com/different2/local-project-hub/issues/new) directly.

## Acknowledgements

Thanks to [Tahir Masood (@tahirmasood2)](https://github.com/tahirmasood2) for
investigating bugs and contributing the audit-remediation fixes and regression
tests in [PR #2](https://github.com/different2/local-project-hub/pull/2).

## License

[MIT](LICENSE). Working on the Hub itself (running from source, tests,
packaging, releases)? See [DEVELOPMENT.md](DEVELOPMENT.md).
