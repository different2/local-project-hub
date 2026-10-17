"""Propose a startup command by reading a project folder.

This is the folder-scanning counterpart to detect_type.py. detect_type decides
what a project IS from a command the user has already typed; this module
proposes that command in the first place, from evidence that costs nothing to
collect: package.json scripts, Python entry files, manifests, lockfiles, and a
root index.html.

The rules are the same as detect_type's:

- Files are read, never executed (spec §7); no `npm install`, no imports.
- A suggestion is only ever OFFERED into an empty field. A command the user
  (or a stored project) already has is never rewritten (spec §6).
- Nothing clever is appended: the suggestion is the plainest command that
  conventionally starts the project (spec §2 — a guessed flag can corrupt a
  command outright).

An empty result means "nothing recognisable", never "this project is broken".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Read cap: manifests are small files; a huge one at these names is not a
# manifest, and this module must never read megabytes to answer.
_MAX_READ = 262_144


@dataclass
class Suggestion:
    """One candidate startup command, and where it came from."""

    command: str
    interpreter: str = ""  # "" = leave the dialog's interpreter field alone
    source: str = ""  # short phrase naming the evidence, for the dialog
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0


# npm needs the literal `run`; the other package managers accept the script
# name directly, which is their idiomatic spelling.
_PM_COMMAND = {
    "npm": "npm run {script}",
    "yarn": "yarn {script}",
    "pnpm": "pnpm {script}",
    "bun": "bun {script}",
}

# First lockfile found decides the package manager; npm is the default
# because it is the one whose spelling is guaranteed to exist.
_LOCKFILES = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("package-lock.json", "npm"),
)

# package.json scripts that conventionally start a dev server, best first.
_NPM_SCRIPTS = ("dev", "start", "serve")
_NPM_CONFIDENCE = {"dev": 0.85, "start": 0.8, "serve": 0.75}

# Python manifests. A Python project without one of these has no dependency
# story to read, and a bare folder of .py files is not enough evidence to
# guess a command (spec §1: unknown is an honest answer).
_PY_MANIFESTS = ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")

# Root-level Python entry points, in priority order. manage.py is handled
# separately, ahead of these, because it is Django's own launcher and carries
# its real command (`runserver`).
_PY_ENTRIES = ("app.py", "server.py", "main.py")

# Virtualenv interpreters a project might ship, checked in this order. The
# interpreter field takes an executable that RUNS the command, so when one of
# these exists the suggested command drops its own `python3` — otherwise the
# interpreter would be prepended to it and run `python3` as a script.
_VENV_PYTHONS = (
    ".venv/bin/python",
    "venv/bin/python",
    "env/bin/python",
    ".venv/Scripts/python.exe",
    "venv/Scripts/python.exe",
)


def suggest_commands(folder) -> list[Suggestion]:
    """Candidate commands for a project folder, most likely first.

    Best-effort and side-effect-free: reads a handful of small files. Any
    filesystem error at any step simply removes that candidate.
    """
    if not folder:
        return []
    try:
        base = Path(str(folder))
        if not base.is_dir():
            return []
    except (OSError, ValueError, TypeError):
        return []

    found: list[Suggestion] = []
    found.extend(_node_suggestions(base))
    found.extend(_python_suggestions(base))
    found.extend(_manifest_command(base, "go.mod", "go run .", "a Go module"))
    found.extend(_manifest_command(base, "Cargo.toml", "cargo run", "a Rust crate"))
    found.extend(_static_suggestions(base))

    # One candidate per command; detectors may overlap on odd trees.
    seen: set[str] = set()
    unique: list[Suggestion] = []
    for s in found:
        if s.command and s.command not in seen:
            seen.add(s.command)
            unique.append(s)
    return unique


def suggest_command(folder) -> Suggestion | None:
    """The single best suggestion for a folder, or None."""
    got = suggest_commands(folder)
    return got[0] if got else None


# ---------- detectors ----------


def _node_suggestions(base: Path) -> list[Suggestion]:
    pkg = base / "package.json"
    if not pkg.is_file():
        return []
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace")[:_MAX_READ])
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return []

    pm, lock = _package_manager(base)
    for script in _NPM_SCRIPTS:
        value = scripts.get(script)
        if not isinstance(value, str) or not value.strip():
            continue
        evidence = [f"package.json defines a {script!r} script"]
        if lock:
            evidence.append(f"{lock} selects {pm}")
        return [
            Suggestion(
                command=_PM_COMMAND[pm].format(script=script),
                source=f"the {script!r} script in package.json",
                evidence=evidence,
                confidence=_NPM_CONFIDENCE[script],
            )
        ]
    return []


def _package_manager(base: Path) -> tuple[str, str]:
    """(package manager, the lockfile that chose it). Defaults to npm."""
    for name, pm in _LOCKFILES:
        if (base / name).is_file():
            return pm, name
    return "npm", ""


def _python_suggestions(base: Path) -> list[Suggestion]:
    if not any((base / m).is_file() for m in _PY_MANIFESTS):
        return []
    interpreter, venv = _venv_python(base)

    if (base / "manage.py").is_file():
        return [
            _python_suggestion(
                base,
                "manage.py runserver",
                interpreter,
                venv,
                entry="manage.py",
                source="manage.py (Django)",
                confidence=0.8,
            )
        ]
    for name in _PY_ENTRIES:
        if (base / name).is_file():
            return [
                _python_suggestion(
                    base,
                    name,
                    interpreter,
                    venv,
                    entry=name,
                    source=f"the {name} entry point",
                    confidence=0.7,
                )
            ]
    # NOTE: a package whose entry point is __main__.py (`python3 -m pkg`) is
    # deliberately not suggested: that spelling only works from the folder's
    # PARENT, and a hub project's working directory is the folder itself, so
    # the suggestion would not run as configured.
    return []


def _python_suggestion(
    base: Path,
    run: str,
    interpreter: str,
    venv: str,
    entry: str,
    source: str,
    confidence: float,
) -> Suggestion:
    """A python command with or without a project venv.

    With a venv, the interpreter field runs the command, so the command must
    NOT name its own `python3` (the two would stack); without one, the
    command spells the interpreter itself.
    """
    manifests = [m for m in _PY_MANIFESTS if (base / m).is_file()]
    evidence = [f"{manifests[0]} found", f"{entry} is a Python entry point"]
    if interpreter:
        command = run
        evidence.append(f"a virtual environment exists ({venv})")
    else:
        command = f"python3 {run}"
    return Suggestion(
        command=command,
        interpreter=interpreter,
        source=source,
        evidence=evidence,
        confidence=confidence,
    )


def _venv_python(base: Path) -> tuple[str, str]:
    """The first project virtualenv interpreter that exists, or ("", "")."""
    for rel in _VENV_PYTHONS:
        if (base / rel).is_file():
            return rel, rel.split("/")[0]
    return "", ""


def _manifest_command(base: Path, filename: str, command: str, source: str) -> list[Suggestion]:
    if (base / filename).is_file():
        return [
            Suggestion(
                command=command,
                source=source,
                evidence=[f"{filename} found"],
                confidence=0.7,
            )
        ]
    return []


def _static_suggestions(base: Path) -> list[Suggestion]:
    """A root index.html with nothing more specific means a static site.

    The hub embeds dashboards in a web view, so a static site needs a local
    URL: Python's built-in server gives it one without installing anything.
    """
    if (base / "index.html").is_file():
        return [
            Suggestion(
                command="python3 -m http.server 8000",
                source="index.html at the project root",
                evidence=["index.html found; served with Python's built-in HTTP server"],
                confidence=0.5,
            )
        ]
    return []
