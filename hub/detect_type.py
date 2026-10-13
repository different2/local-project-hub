"""Classify a project from its command and files, so the Hub launches it right.

The spec's central insight is that a project's launch behavior follows from its
TYPE, and the type is inferable from evidence that costs nothing to collect:
the command line, the entry script, and the project's own manifest files
(pyproject.toml, package.json, requirements.txt).

Classification is best-effort and never authoritative. Every consumer must
treat "unknown" as a real answer, not a failure to be papered over.

What this module deliberately does NOT do:

- It never executes project code to inspect it (spec §7). Reading files and
  parsing text is passive; running `npm install` or importing a module is not.
- It never rewrites the user's command (spec §6). Detected settings are stored
  alongside it under `detected`, so the original stays verbatim.
- It never injects a framework flag on a guess (spec §2). `--no-open` belongs
  to obs_live.py, Flask uses `--no-reload`, Vite uses `--open false`, and npm
  has no equivalent. Appending one blindly corrupts commands.

Types (spec §1):

  web      starts a local HTTP server serving a web interface
  static   serves/displays HTML, CSS and JS files
  desktop  opens its own native window
  cli      runs headless, no user-facing UI
  unknown  not enough evidence to say
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

# The type strings, in the order they appear in the spec.
WEB = "web"
STATIC = "static"
DESKTOP = "desktop"
CLI = "cli"
UNKNOWN = "unknown"

TYPES = (WEB, STATIC, DESKTOP, CLI, UNKNOWN)

# What the Hub does with each type: how it should be shown to the user.
DISPLAY = {
    WEB: "embedded web view",
    STATIC: "embedded web view (served locally)",
    DESKTOP: "launches its own window",
    CLI: "runs in the background",
    UNKNOWN: "runs in the background (type unknown)",
}


@dataclass
class Detection:
    """Best-effort classification plus the evidence that produced it.

    `confidence` is a plain 0.0-1.0 score so callers can decide when to ask the
    user versus acting on it (spec §5: "prefer automatic configuration without
    additional questions when the evidence is sufficient").
    """

    type: str = UNKNOWN
    confidence: float = 0.0
    framework: str = ""
    port: int | None = None
    browser: str = ""  # "known-suppressible" | "none" | "unknown"
    display: str = DISPLAY[UNKNOWN]
    evidence: list[str] = field(default_factory=list)
    # Absolute or cwd-relative path to the .py the command runs. Lets
    # browser_suppress_args() read the script's own argparse instead of
    # guessing a flag (spec §2). Not persisted; recomputed each detection.
    entry_script: str = field(default="", repr=False)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Detection":
        """Rebuild from a persisted record, tolerating missing/unknown keys.

        Existing registry entries have no `detected` block at all, so this must
        never raise (spec §7: "migrate existing project records safely").
        """
        data = data or {}
        t = data.get("type") or UNKNOWN
        if t not in TYPES:
            t = UNKNOWN
        port = data.get("port")
        try:
            port = int(port) if port else None
        except (TypeError, ValueError):
            port = None
        try:
            conf = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        return cls(
            type=t,
            confidence=min(max(conf, 0.0), 1.0),
            framework=str(data.get("framework") or ""),
            port=port,
            browser=str(data.get("browser") or ""),
            display=str(data.get("display") or DISPLAY.get(t, DISPLAY[UNKNOWN])),
            evidence=list(data.get("evidence") or []),
        )


# ---------- framework knowledge ----------

# Command-line tokens that mean "run a dev/HTTP server".
_SERVER_TOKENS = (
    "serve",
    "server",
    "http.server",
    "runserver",
    "dev",
    "start",
    "start:web",
    "uvicorn",
    "gunicorn",
    "waitress-serve",
    "hypercorn",
    "flask run",
    "manage.py runserver",
    "app.run",
)

# Command-line tokens that mean "open a GUI window". Deliberately does NOT
# include a bare "app.py": that is far more often a web entry point than a GUI
# one, and guessing desktop there hid real web projects.
_DESKTOP_TOKENS = (
    "pyqt",
    "pyside",
    "tkinter",
    "kivy",
    "electron",
    "tauri",
    "customtkinter",
)

# Frameworks whose documented flag genuinely suppresses the auto-open. A
# framework with no such option is simply absent: offering a guessed flag is
# worse than leaving a redundant browser window (spec §2).
BROWSER_FLAGS = {
    "streamlit": "--server.headless true",
    "panel": "--no-browser",
    "jupyter": "--no-browser",
    "marimo": "--headless",
    "shiny": "--launch-browser false",
}

# Python packages that imply a web app, from the most to least specific.
_WEB_DEPS = (
    "flask",
    "django",
    "fastapi",
    "starlette",
    "uvicorn",
    "bottle",
    "tornado",
    "aiohttp",
    "sanic",
    "pyramid",
    "streamlit",
    "gradio",
    "dash",
    "panel",
    "bokeh",
    "nicegui",
    "reflex",
)

# Python packages that imply a native GUI app.
_DESKTOP_DEPS = (
    "pyside6",
    "pyqt5",
    "pyqt6",
    "pyside2",
    "tkinter",
    "kivy",
    "wxpython",
    "pygobject",
    "customtkinter",
    "eel",
)

# npm dependencies that imply a dev server.
_WEB_NPM_DEPS = (
    "vite",
    "next",
    "react-scripts",
    "@angular/cli",
    "vue-cli-service",
    "webpack-dev-server",
    "parcel",
    "nuxt",
    "svelte-kit",
    "astro",
    "gatsby",
    "remix",
)

# npm scripts that conventionally start a dev server.
_WEB_SCRIPTS = ("dev", "start", "serve", "preview")

# npm packages that imply a native app.
_DESKTOP_NPM = ("electron", "tauri", "@tauri-apps/cli")

# Port arguments, in the forms projects actually use:
#   --port 8080  --port=8080  -p 8080  :8080
# and a bare trailing number ("python3 -m http.server 8080"), which is how
# http.server and many one-off scripts take their port.
_PORT_FLAG_RE = re.compile(r"(?:--port[=\s]+|-p[=\s]+|:)(\d{2,5})\b")
_PORT_TRAILING_RE = re.compile(r"(?:^|\s)(\d{2,5})\s*$")


def _port_from_command(text: str) -> int | None:
    for pattern in (_PORT_FLAG_RE, _PORT_TRAILING_RE):
        m = pattern.search(text or "")
        if not m:
            continue
        try:
            p = int(m.group(1))
        except ValueError:
            continue
        if 1024 <= p <= 65535:
            return p
    return None


def detect(record: dict) -> Detection:
    """Classify a project record. Never raises; returns UNKNOWN when unsure.

    `record` is a project dict (command, working_dir, args). Only its files and
    text are read — nothing is executed (spec §7).
    """
    command = str(record.get("command") or "")
    args = str(record.get("args") or "")
    cwd = str(record.get("working_dir") or "")
    haystack = f"{command} {args}".lower()

    det = Detection()
    det.port = _port_from_command(f"{command} {args}")

    # 1. Explicit desktop markers are the strongest signal.
    if any(t in haystack for t in _DESKTOP_TOKENS):
        det.type = DESKTOP
        det.confidence = 0.7
        det.browser = "none"
        det.display = DISPLAY[DESKTOP]
        det.evidence.append(f"command names a GUI toolkit: {command!r}")
        _enrich_from_deps(det, cwd)
        return det

    # 2. A python -m http.server (or any bare serve) is a static site.
    if re.search(r"http\.server|python.*-m\s+serve|http-server|live-server|serve\b", haystack):
        det.type = STATIC
        det.confidence = 0.8
        det.browser = "unknown"
        det.display = DISPLAY[STATIC]
        det.evidence.append("command serves files over HTTP")
        _enrich_from_deps(det, cwd)
        return det

    # 3. An npm/yarn/pnpm script that means "dev server".
    if _is_npm_dev_command(haystack):
        det.type = WEB
        det.confidence = 0.85
        det.browser = "unknown"
        det.display = DISPLAY[WEB]
        det.evidence.append("command runs a package.json dev/serve script")
        _enrich_from_npm(det, cwd)
        return det

    # 4. A python entry point: decide web vs cli from its dependencies.
    if _is_python(haystack) or cwd:
        dep_kind, framework = _inspect_python_project(cwd, command)
        if dep_kind == WEB:
            det.type = WEB
            det.confidence = 0.8
            det.framework = framework
            det.entry_script = _entry_script_path(command, cwd)
            det.browser = "known-suppressible" if framework in BROWSER_FLAGS else "unknown"
            # A custom server can still advertise the flag in its own argparse;
            # that is evidence, so it counts as suppressible too.
            if det.browser == "unknown" and _argparse_no_open_flag(det):
                det.browser = "known-suppressible"
                det.evidence.append(
                    f"entry script declares {_argparse_no_open_flag(det)} in its argparse"
                )
            det.display = DISPLAY[WEB]
            det.evidence.append(
                f"python project depends on a web framework ({framework or 'unrecognised'})"
            )
            return det
        if dep_kind == DESKTOP:
            det.type = DESKTOP
            det.confidence = 0.8
            det.framework = framework
            det.browser = "none"
            det.display = DISPLAY[DESKTOP]
            det.evidence.append(f"python project depends on a GUI toolkit ({framework})")
            return det

    # 5. No framework dependency, but the entry script itself implements a
    # stdlib HTTP server. This is checked BEFORE the token/name heuristics
    # below because reading the script is stronger evidence than pattern-
    # matching the command line: it also lets us read the script's own argparse
    # for a no-open flag, which the heuristics cannot do.
    #
    # A script that subclasses BaseHTTPRequestHandler or instantiates an
    # HTTPServer *is* a web app — the framework table simply has no name for it.
    # This is what makes a custom server like obs_live.py or server.py
    # detectable at all; without it the hub calls it "cli" and never looks for a
    # URL or a no-open flag.
    det.entry_script = _entry_script_path(command, cwd)
    if _script_serves_http(det.entry_script):
        det.type = WEB
        det.confidence = 0.6
        det.framework = ""
        det.browser = "unknown"
        det.display = DISPLAY[WEB]
        det.evidence.append(
            "entry script implements a stdlib HTTP server (BaseHTTPRequestHandler/HTTPServer)"
        )
        flag = _argparse_no_open_flag(det)
        if flag:
            det.browser = "known-suppressible"
            det.evidence.append(f"entry script declares {flag} in its argparse")
        return det

    # A server-ish token in the command, but no framework evidence.
    if any(t in haystack for t in _SERVER_TOKENS):
        det.type = WEB
        det.confidence = 0.5
        det.browser = "unknown"
        det.display = DISPLAY[WEB]
        det.evidence.append("command looks like it starts a server")
        return det

    # An entry point whose NAME says server/API/app-wsgi is weak-but-real web
    # evidence. A bare script with a neutral name is NOT: calling that "cli"
    # would be a guess, and "unknown" is the honest answer (spec §1).
    if re.search(r"\b(srv|server|api|app|wsgi|web|dashboard|ui)\.py\b", haystack):
        det.type = WEB
        det.confidence = 0.45
        det.browser = "unknown"
        det.display = DISPLAY[WEB]
        det.evidence.append("entry point name suggests a server")
        return det

    # 6. Nothing web-like was found. A python command running a script is
    # headless by convention, so "cli" is fair. Anything else — a binary or
    # script the hub does not recognise — is genuinely UNKNOWN: claiming "cli"
    # there would assert knowledge it does not have (spec §1).
    if command.strip():
        if _is_python(haystack) or cwd:
            det.type = CLI
            det.confidence = 0.4
            det.browser = "none"
            det.display = DISPLAY[CLI]
            det.evidence.append("python project with no web or GUI dependency")
        else:
            det.type = UNKNOWN
            det.confidence = 0.0
            det.browser = "unknown"
            det.display = DISPLAY[UNKNOWN]
            det.evidence.append("no web, GUI or server evidence found")
    return det


def browser_suppress_args(det: Detection) -> str:
    """The documented flag that stops this framework opening a browser, or "".

    Returns "" for anything not in BROWSER_FLAGS. Guessing here is exactly what
    spec §2 forbids: an unknown flag is worse than an extra browser window,
    because it can break the command outright.

    Two sources of truth, in order:
      1. BROWSER_FLAGS — the framework's own documented switch.
      2. The entry script's own ``argparse`` — if the script literally declares
         a no-open style flag, using it is quoting the program, not guessing.
    """
    if not det or det.browser != "known-suppressible":
        return ""
    if det.framework in BROWSER_FLAGS:
        return BROWSER_FLAGS[det.framework]
    return _argparse_no_open_flag(det)


# Flags that mean "do not open a browser", as a script would spell them.
_NO_OPEN_NAMES = ("no-open", "no_open", "no-browser", "no_browser",
                  "headless", "no-launch", "no-launch-browser")


def _entry_script_path(command: str, cwd: str) -> str:
    """Best-effort path to the .py file a command runs, or "".

    Only the command line is parsed — the script is never imported or run
    (spec §7: no arbitrary execution for inspection).
    """
    tokens = [t for t in command.split() if t]
    for tok in tokens:
        if tok.endswith(".py"):
            return tok if os.path.isabs(tok) else os.path.join(cwd or ".", tok)
    return ""


# stdlib HTTP-server markers. Any of these means the script serves HTTP itself,
# with no framework involved (spec §1 wants web vs cli decided from evidence).
_HTTP_SERVER_TOKENS = (
    "BaseHTTPRequestHandler",
    "ThreadingHTTPServer",
    "HTTPServer",
    "socketserver.TCPServer",
    "http.server",
)


def _script_serves_http(script: str) -> bool:
    """True when the entry script implements a stdlib HTTP server.

    Text-only: the file is read, never imported or executed (spec §7).
    """
    if not script:
        return False
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            source = fh.read(512_000)
    except (OSError, ValueError):
        return False
    return any(tok in source for tok in _HTTP_SERVER_TOKENS)


def _script_default_port(script: str) -> int | None:
    """The port a script hardcodes, when it is not on the command line.

    A project like the_sphere_project's server.py binds
    `PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8471`, so nothing the
    user types reveals 8471. Read as text only (never imported or executed).
    """
    if not script:
        return None
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            source = fh.read(256_000)
    except (OSError, ValueError):
        return None
    # `PORT = 8471` on its own line...
    m = re.search(r"^\s*(?:PORT|port)\s*=\s*(\d{2,5})\s*$", source, re.M)
    if m:
        return int(m.group(1))
    # ...or the default arm of a ternary, `... else 8471`.
    m = re.search(r"^\s*(?:PORT|port)\s*=.*?else\s+(\d{2,5})", source, re.M)
    if m:
        return int(m.group(1))
    return None


def _argparse_no_open_flag(det: Detection) -> str:
    """A no-open flag the entry script declares in its own argparse, or "".

    Text-only inspection: the script is never executed or imported. A project
    that advertises the flag is a custom server like obs_live.py, which has no
    framework but does define ``--no-open`` itself. Passing it is reading the
    program's own contract, which is evidence rather than a guess -- but if the
    file cannot be read or parsed we return "" and leave the browser alone.
    """
    script = (getattr(det, "entry_script", "") or "").strip()
    if not script:
        return ""
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            source = fh.read(512_000)  # cap: a huge file is not argparse
    except (OSError, ValueError):
        return ""
    if "argparse" not in source and "ArgumentParser" not in source:
        return ""
    for m in re.finditer(r"""add_argument\(\s*['"](--[^'"]+)['"]""", source):
        if any(name in m.group(1).lower() for name in _NO_OPEN_NAMES):
            return m.group(1)
    return ""


def _is_python(haystack: str) -> bool:
    return bool(re.search(r"\bpython[0-9.]*\b|\.py\b|pip|conda|poetry|uv\b", haystack))


def _is_npm_dev_command(haystack: str) -> bool:
    if not re.search(r"\b(npm|yarn|pnpm|bun)\b", haystack):
        return False
    return any(f" {s}" in f" {haystack} " or s in haystack for s in ("dev", "start", "serve"))


def _enrich_from_deps(det: Detection, cwd: str) -> None:
    """Fill in a framework name from a python project's manifests."""
    if not cwd:
        return
    base = Path(cwd)
    for name in ("pyproject.toml", "requirements.txt", "setup.py", "Pipfile"):
        f = base / name
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        for dep in _WEB_DEPS:
            if dep in text:
                det.framework = det.framework or dep
                det.evidence.append(f"{name} mentions {dep}")
                if det.type == DESKTOP and dep not in _DESKTOP_DEPS:
                    # A GUI command with a web dep is ambiguous; leave the type.
                    pass
                return
        for dep in _DESKTOP_DEPS:
            if dep in text:
                det.framework = det.framework or dep
                det.evidence.append(f"{name} mentions {dep}")
                return


def _inspect_python_project(cwd: str, command: str) -> tuple[str, str]:
    """Decide web / desktop / nothing for a python project. (kind, framework)."""
    base = Path(cwd) if cwd else None
    text = (command or "").lower()
    for name in ("pyproject.toml", "requirements.txt", "setup.py", "Pipfile"):
        f = (base / name) if base else None
        if f and f.is_file():
            try:
                text += "\n" + f.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                pass
    if not text.strip():
        return "", ""
    for dep in _WEB_DEPS:
        if dep in text:
            return WEB, dep
    for dep in _DESKTOP_DEPS:
        if dep in text:
            return DESKTOP, dep
    return "", ""


def _enrich_from_npm(det: Detection, cwd: str) -> None:
    """Fill in a framework name from package.json."""
    if not cwd:
        return
    f = Path(cwd) / "package.json"
    if not f.is_file():
        return
    try:
        pkg = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return
    deps = {}
    for key in ("dependencies", "devDependencies"):
        d = pkg.get(key)
        if isinstance(d, dict):
            deps.update(d)
    for dep in _WEB_NPM_DEPS:
        if dep in deps:
            det.framework = dep
            det.evidence.append(f"package.json depends on {dep}")
            return
    scripts = pkg.get("scripts") or {}
    for s in _WEB_SCRIPTS:
        if s in scripts:
            det.evidence.append(f"package.json has a {s!r} script")
            return
    for dep in _DESKTOP_NPM:
        if dep in deps:
            det.framework = dep
            det.type = DESKTOP
            det.display = DISPLAY[DESKTOP]
            det.browser = "none"
            det.evidence.append(f"package.json depends on {dep} (native app)")
            return
