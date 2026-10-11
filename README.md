# Local Project Hub

A cross-platform desktop app that registers local projects, launches their
backends, and shows their web dashboards in one window (PySide6 + QtWebEngine).

Any project works: Python, Node, Go, Rust, or a shell script — the hub runs the
startup command you configure and waits for the dashboard URL to answer.

See SPEC.md for the full requirements this repo implements.

## Run

```bash
./run.sh          # uses ./.hubenv (recommended — already has PySide6), else $PATH python3
```

Note: `./run.sh` on a fresh clone will fall back to `python3` from your PATH,
which may be a different interpreter (e.g. Homebrew's) than the one that has
PySide6. Create the venv once and the fallback is never used:

```bash
python3 -m venv .hubenv && .hubenv/bin/pip install PySide6
.hubenv/bin/python main.py    # equivalent to ./run.sh
```

## Layout

```
main.py                app entry point
hub/
  store.py             project registry (JSON) + validation
  process_manager.py   process spawn / stop / status / log capture
  readiness.py         TCP + HTTP readiness polling
  window.py            main window: sidebar, webview, log drawer
  project_dialog.py    add/edit project form
tests/
  test_store.py        registry tests (pytest, no GUI needed)
```
