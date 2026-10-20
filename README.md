# Local Project Hub

A desktop app that keeps your local projects in one window: register a folder,
press start, and its web dashboard opens in a tab. Works with anything
launchable — **Python, Node, Go, Rust, or a shell script** — and runs on macOS
and Windows.

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

Latest version: **v0.6.2**

| Platform | File | Install |
|---|---|---|
| macOS 12+ | [`Local.Project.Hub-0.6.2.dmg`](https://github.com/different2/local-project-hub/releases/download/v0.6.2/Local.Project.Hub-0.6.2.dmg) | Open the disk image, drag the app to Applications |
| Windows | [`Local.Project.Hub-0.6.2.msi`](https://github.com/different2/local-project-hub/releases/download/v0.6.2/Local.Project.Hub-0.6.2.msi) | Double-click the installer |

Older versions: [Releases](https://github.com/different2/local-project-hub/releases).

> **Read this before your first launch.** The installers are not code-signed
> yet — that needs paid certificates — so your OS will warn the first time:
>
> - **macOS:** if macOS says it cannot check the app for malicious software,
>   Control-click (right-click) the app and choose **Open → Open**. This is
>   needed once; it can come back after an update.
> - **Windows:** if SmartScreen shows *"Windows protected your PC"*, click
>   **More info → Run anyway**.

## Requirements

- The Hub itself needs **nothing installed** — no Python, no runtimes.
- Your projects need their own tooling, as usual: the Hub runs the command
  you give it and does not install or manage dependencies.
- The macOS build needs macOS 12 or newer.

## Using it

1. **Add a project** — press **+ Add** in the toolbar and give it a display
   name and the project folder — or press **File…** and pick the script that
   starts it. The Hub reads what you chose and fills in the startup command —
   adjust it if needed. Leave **Dashboard URL** blank for most projects: if
   the server prints its address, the Hub detects it.
2. **Open it** — click the project in the sidebar. If it isn't running, the
   Hub starts it, and the dashboard opens in a tab once the server answers.
3. **Drive it** — **Start**, **Stop**, **Restart**, and **Open in browser**
   act on the project you are viewing. Everything a project prints appears in
   the **log drawer** at the bottom; toggle it with **Logs**.

Worth knowing:

- Adding a project never starts it, and opening the Hub never starts anything
  by itself. A project runs when you click it, press Start, or tick **Start
  automatically when the hub opens** on it.
- Desktop apps get launched in their own window instead of a tab.
- The Hub's own tab is a short getting-started page; reopen it via the app
  menu's **Show Overview** if you close it.

## Updating

**Help → Check for Updates…** shows the newest release; **Download and
Install** fetches the installer, verifies the download against its published
checksum, and gets it ready. On macOS the app then offers **Restart and
Install**: it closes, puts the new version in place and reopens by itself —
the copy it replaces goes to the Trash, and if anything goes wrong the old
copy is put back before you see it. On Windows, the installer runs. Your
projects and settings are untouched.

## Where your data lives

| What | Where |
|---|---|
| Project registrations | macOS `~/Library/Application Support/LocalProjectHub/`, Windows `%LOCALAPPDATA%\LocalProjectHub\`, Linux `~/.local/share/local-project-hub/` |
| Your projects | untouched, in their original folders |

Updating or uninstalling the Hub never modifies a registered project.

## Problems or feedback

**Help → Report a Problem…** builds a report with the app version, your OS,
and the recent log — deliberately none of your project data — and can save it
or open a pre-filled issue. Or open an
[issue](https://github.com/different2/local-project-hub/issues/new) directly.

## License

[MIT](LICENSE). Working on the Hub itself (running from source, tests,
packaging, releases)? See [DEVELOPMENT.md](DEVELOPMENT.md).
