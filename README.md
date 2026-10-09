# Local Project Hub

A macOS desktop app that registers local Python projects, launches their backends,
and shows their web dashboards in one window (PySide6 + QtWebEngine).

See SPEC.md for the full requirements this repo implements.

## Run

```bash
./run.sh          # uses ./.hubenv if present, else system python3
```

Or explicitly:

```bash
python3 -m venv .hubenv && .hubenv/bin/pip install PySide6
.hubenv/bin/python main.py
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
