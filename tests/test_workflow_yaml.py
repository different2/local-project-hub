"""Guard the GitHub Actions workflow against silent YAML corruption.

A `yaml.safe_dump()` round-trip rewrote the workflow's `on:` trigger key as
`true:`, because PyYAML follows YAML 1.1 where `on` is a boolean. GitHub
rejected the whole file with:

    Invalid workflow file (Line: 2, Col: 1): Unexpected value 'true'

The consequence was badly misleading: runs #14 and #15 "completed" in 0 seconds
with zero jobs, which is indistinguishable from GitHub refusing to allocate a
runner. That signature was investigated as a billing/concurrency problem while
the real cause sat in the repository the whole time.

These tests assert the workflow on its RAW TEXT as well as its parsed shape,
because the corruption is only visible before a YAML 1.1 loader normalises it.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

# Keys YAML 1.1 coerces to booleans. Any of these appearing as a bare mapping
# key in a workflow means a round-trip has already corrupted it.
BOOLEAN_KEYS = ("true", "false", "yes", "no", "on", "off")


def test_workflow_declares_an_on_trigger() -> None:
    """The trigger key must be present and correctly named."""
    import yaml

    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "on" in d, (
        f"no 'on' trigger key; top-level keys are {sorted(d)} -- a YAML 1.1 "
        "round-trip has renamed it (PyYAML turns 'on' into True)"
    )
    triggers = d["on"]
    for required in ("push", "workflow_dispatch"):
        assert required in triggers, f"the '{required}' trigger is missing"


def test_raw_text_has_no_boolean_corrupted_keys() -> None:
    """Scan the raw file for mapping keys a YAML 1.1 loader would coerce.

    Parsing alone cannot catch this: PyYAML happily loads `true:` as the key
    True, so the corruption is invisible after a round-trip. Read the text.
    """
    offenders = []
    for lineno, line in enumerate(
        WORKFLOW.read_text(encoding="utf-8").splitlines(), 1
    ):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # a bare `<key>:` at the start of a line, unquoted
        for key in BOOLEAN_KEYS:
            if stripped == f"{key}:":
                offenders.append(f"line {lineno}: bare mapping key {key!r}")
    assert not offenders, (
        "these bare keys will be read as booleans, not strings:\n"
        + "\n".join(offenders)
    )


def test_workflow_survives_a_yaml_round_trip() -> None:
    """Dumping and reloading must not change the trigger key.

    This is the operation that broke the file. If a future edit round-trips the
    workflow through PyYAML without care, the key comes back as `true:` and
    GitHub rejects the workflow outright.
    """
    import yaml

    original = WORKFLOW.read_text(encoding="utf-8")
    dumped = yaml.safe_dump(yaml.safe_load(original), sort_keys=False)

    # GitHub reads the parsed document, so the trigger must survive as "on"
    reparsed = yaml.safe_load(dumped)
    assert "on" in reparsed, (
        "a YAML round-trip renames the 'on' trigger. Quote the key in the file "
        "and never re-dump the workflow with PyYAML."
    )
    # and the file on disk must not be the dumped form
    assert original.strip() != dumped.strip(), (
        "the committed file looks like PyYAML output; it will drift"
    )


def test_every_job_has_runnable_steps() -> None:
    """A job with no steps cannot run, which is the other silent-CI-killer."""
    import yaml

    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for name, job in d["jobs"].items():
        steps = job.get("steps") or []
        assert steps, f"job {name!r} has no steps and can never execute"
        for step in steps:
            assert "uses" in step or "run" in step, (
                f"job {name!r} has a step with neither 'uses' nor 'run'"
            )


def test_manual_dispatch_builds_but_never_publishes() -> None:
    """A manual run may exercise packaging, but must never cut a release.

    The build jobs are tag-gated, which made them unreachable until a release
    was actually being cut — that is how a `--msi` typo sat in the workflow
    unnoticed: nothing could run the command to find out. They now also accept
    `workflow_dispatch`, so packaging changes can be tested on demand.

    The safety half matters more than the convenience half. `publish` creates
    the GitHub release and attaches installers; if a dispatch could reach it, a
    stray click would publish a release from whatever the branch happened to
    contain. It must stay tag-gated, and this test is what stops a future edit
    from quietly widening it.
    """
    import yaml

    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = d["jobs"]

    def condition(name):
        return str(jobs[name].get("if") or "")

    for name in ("build-macos", "build-windows"):
        assert "workflow_dispatch" in condition(name), (
            f"{name!r} cannot be run on demand, so a packaging change is still "
            "only testable by cutting a release"
        )
        assert "refs/tags/v" in condition(name), (
            f"{name!r} must still build on a version tag"
        )

    assert "workflow_dispatch" not in condition("publish"), (
        "publish must never run on a manual dispatch — that would let a stray "
        "click create a release; it is tag-gated on purpose"
    )
    assert "refs/tags/v" in condition("publish"), (
        "publish must run on a version tag"
    )


def test_briefcase_is_pinned() -> None:
    """The release toolchain must not float to whatever PyPI serves that day.

    briefcase produces the release artifacts, so an unpinned install lets a new
    version silently change (or break) packaging while nothing in the repository
    changed — the same class of from-outside risk the tag/version guard exists
    for. The pin turns an upgrade into a deliberate, reviewed change.
    """
    lines = [
        line.strip()
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "briefcase" in line and not line.strip().startswith("#")
    ]
    installs = [ln for ln in lines if "pip install" in ln]
    assert installs, (
        "no briefcase install line found in the workflow — the release build "
        "would fail, or the toolchain step changed shape"
    )
    for ln in installs:
        assert "briefcase==" in ln, (
            f"unpinned briefcase install: {ln!r}\n"
            "A bare 'briefcase' lets a new version change the release build "
            "silently; pin it (briefcase==<version>) and bump deliberately."
        )


def test_gui_dependency_pins_are_coordinated() -> None:
    """The GUI stack must be pinned to ONE version, everywhere.

    PySide6 ships as three distributions in lockstep (PySide6, -Essentials,
    -Addons); mixing them is unsupported, and the packaged app must run exactly
    the version the suite is tested against — otherwise CI quietly tests a
    different Qt than users get. The pins live in the workflow (what CI
    installs) and in pyproject's `requires` (what briefcase bundles); this
    test fails when they drift apart or go unpinned. See DEVELOPMENT.md
    "Dependency versions" for how to bump them deliberately.
    """
    import re

    text = WORKFLOW.read_text(encoding="utf-8")
    cmd = "\n".join(
        ln for ln in text.splitlines()
        if "pip install" in ln and not ln.strip().startswith("#")
    )

    versions = sorted(set(
        re.findall(r"PySide6(?:-(?:Essentials|Addons))?==([0-9][0-9.]*)", cmd)
    ))
    assert versions, "no pinned PySide6 packages found in the workflow"
    assert len(versions) == 1, (
        f"the PySide6 trio is pinned to different versions: {versions} — it "
        "ships in lockstep and mixing versions is unsupported"
    )
    version = versions[0]

    for name in ("PySide6", "PySide6-Essentials", "PySide6-Addons", "Pillow"):
        assert f"{name}==" in cmd, f"{name} must be pinned in the workflow"

    for name in ("PySide6-Essentials", "PySide6-Addons", "Pillow"):
        assert not re.search(re.escape(name) + r"(?!==)", cmd), (
            f"{name} appears unpinned somewhere in the workflow — pin it "
            "like the rest of the set"
        )
    assert not re.search(r"(?<![\w\-])PySide6(?![\w=\-])", cmd), (
        "a bare PySide6 appears unpinned in the workflow"
    )

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    req = sorted(set(
        re.findall(r'"PySide6-(?:Essentials|Addons)==([0-9][0-9.]*)"', pyproject)
    ))
    assert req == [version], (
        f"pyproject `requires` pins {req} but CI pins {version} — the packaged "
        "app would not run the version the suite was tested against"
    )


def test_certifi_and_pyobjc_pins_are_coordinated() -> None:
    """certifi (the app's CA trust store) and pyobjc must be pinned, in step.

    certifi is not optional polish: the packaged app's Python has no default
    CA store inside the bundle, so without certifi every HTTPS request dies
    as CERTIFICATE_VERIFY_FAILED and the update check reports "could not
    reach the update server" on a healthy connection (reproduced in the
    shipped bundle, 2026-10-18). pyobjc is the AppKit dependency of the
    About-box fix. Both float to the newest release unless pinned, so a
    rebuild could silently swap either; the workflow (what CI tests
    against) and pyproject (what briefcase bundles) must name the same
    versions, and pyobjc must keep its darwin marker so the Linux and
    Windows runners do not try to install it.
    """
    import re

    text = WORKFLOW.read_text(encoding="utf-8")
    cmd = "\n".join(
        ln for ln in text.splitlines()
        if "pip install" in ln and not ln.strip().startswith("#")
    )
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for name in ("certifi", "pyobjc-framework-Cocoa"):
        versions = sorted(set(re.findall(re.escape(name) + r"==([0-9][0-9.]*)", cmd)))
        assert versions, f"{name} is not pinned in the workflow"
        assert len(versions) == 1, f"{name} pinned at several versions: {versions}"
        version = versions[0]
        assert (
            f'"{name}=={version}"' in pyproject or f"{name}=={version};" in pyproject
        ), (
            f"pyproject does not pin {name}=={version} (the workflow pins it) — "
            "the packaged app would not run what CI tested"
        )

    assert re.search(
        r"pyobjc-framework-Cocoa==[0-9.]+;\s*sys_platform == 'darwin'", pyproject
    ), "pyobjc must stay macOS-only in pyproject (it is a darwin dependency)"
    assert re.search(
        r"pyobjc-framework-Cocoa==[0-9.]+;\s*sys_platform == 'darwin'", cmd
    ), (
        "pyobjc install in the workflow needs the darwin marker, or the Linux "
        "and Windows runners fail the install step"
    )


def test_tag_check_gets_the_tag_on_every_shell() -> None:
    """The version guard must receive the tag on EVERY runner OS.

    The step read `"${GITHUB_REF_NAME}"`, which bash expands but PowerShell
    does not: on the Windows runner it arrived empty, the guard refused with
    "no tag given to check", and the first tag build that ever ran this step
    (v0.4.0, 2026-10-18) died there with every Windows build step skipped
    behind it. The step was added after v0.3.8 shipped, which is why no
    earlier tag build could have found it. `${{ github.ref_name }}` is
    expanded by the runner itself, so both shells see the tag.
    """
    lines = [
        ln.strip()
        for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "check_tag_version.py" in ln and not ln.strip().startswith("#")
    ]
    assert len(lines) == 2, (
        f"expected the tag check in both build jobs, found {len(lines)}"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "${GITHUB_REF_NAME}" not in text, (
        "bash-only expansion: PowerShell expands GITHUB_REF_NAME to nothing, "
        "so the tag check fails on the Windows runner. Use the "
        "runner-expanded form (dollar-brace-brace github.ref_name)."
    )
    for ln in lines:
        assert '"${{ github.ref_name }}"' in ln, (
            f"tag check does not pass the runner-expanded tag: {ln!r}"
        )


if __name__ == "__main__":
    fails = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {_name}: {e}")
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "N passed, 1 failed" with no FAIL line naming
                # the 1. An unexpected error is a failure -- report it as one.
                fails += 1
                print(f"ERROR {_name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
