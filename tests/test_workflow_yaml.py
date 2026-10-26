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

    for name in ("build-windows", "build-linux"):
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
    assert condition("publish") == "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')", (
        "dispatching a tag ref must not publish; publication requires an actual push event"
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


def _packaged_gui_pins(platform: str) -> dict[str, str]:
    """Evaluate the real PEP 508 markers, without changing sys.platform."""
    import ast
    import re
    from packaging.requirements import Requirement

    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    common = re.split(r"(?m)^\[tool\.briefcase\.app\.", text, maxsplit=1)[0]
    match = re.search(r"(?ms)^requires\s*=\s*(\[.*?^\])", common)
    assert match, "missing common Briefcase requirements array"
    requirements = ast.literal_eval(match.group(1))
    pins = {}
    for raw in requirements:
        req = Requirement(raw)
        if req.name not in ("PySide6", "PySide6-Essentials", "PySide6-Addons"):
            continue
        if req.marker is not None and not req.marker.evaluate({"sys_platform": platform}):
            continue
        assert req.name not in pins, f"multiple active {req.name} requirements on {platform}"
        version = str(req.specifier)
        assert re.fullmatch(r"==[0-9]+(?:\.[0-9]+)+", version), f"unpinned GUI requirement: {raw}"
        pins[req.name] = version[2:]
    assert {"PySide6-Essentials", "PySide6-Addons"} <= set(pins), (platform, pins)
    assert len(set(pins.values())) == 1, f"mixed Qt distributions on {platform}: {pins}"
    return pins


def test_platform_gui_versions_preserve_mac_and_fix_new_windows() -> None:
    """Fix the Mac AX cache crash without changing other runtimes or OS floor."""
    import re

    assert set(_packaged_gui_pins("win32").values()) == {"6.12.0"}, (
        "Windows still packages the incompatible Qt version instead of validated 6.12.0"
    )
    assert set(_packaged_gui_pins("darwin").values()) == {"6.9.3"}, (
        "macOS must package Qt6.9.3 with the QTBUG-134784 accessibility cache fix"
    )
    assert set(_packaged_gui_pins("linux").values()) == {"6.7.3"}, (
        "the Mac accessibility correction must not change the Linux runtime"
    )
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    mac = re.search(r"(?ms)^\[tool\.briefcase\.app\.hub\.macOS\]\n(.*?)(?=^\[|\Z)", text)
    assert mac and re.search(r'(?m)^min_os_version\s*=\s*"12\.0"\s*$', mac.group(1)), (
        "Briefcase requires min_os_version=12.0; minimum_system_version is ignored"
    )
    # Actual bundle-floor validation belongs to the local packaging helper,
    # not a hosted Mac job. Its real-file/ordering controls live alongside
    # release_artifacts tests; release acceptance still inspects the real DMG.


def test_gui_dependency_pins_are_coordinated() -> None:
    """Each OS tests and packages one matching, internally coherent Qt trio."""
    import re
    import shlex
    import yaml
    from packaging.requirements import Requirement

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job, platform in (("test", "win32"), ("test", "linux"),
                          ("build-windows", "win32"), ("build-linux", "linux")):
        commands = "\n".join(
            line for step in workflow["jobs"][job]["steps"]
            for line in str(step.get("run", "")).splitlines()
            if "pip install" in line and not line.strip().startswith("#")
        )
        pins = {}
        for line in commands.splitlines():
            for token in shlex.split(line):
                if not re.match(r"^PySide6(?:-(?:Essentials|Addons))?(?:[=<>!~;]|$)", token):
                    continue
                requirement = Requirement(token)
                if requirement.marker and not requirement.marker.evaluate({"sys_platform": platform}):
                    continue
                version = str(requirement.specifier)
                assert re.fullmatch(r"==[0-9]+(?:\.[0-9]+)+", version), (job, token)
                assert requirement.name not in pins, (job, platform, "duplicate active Qt requirement")
                pins[requirement.name] = version[2:]
        assert set(pins) == {"PySide6", "PySide6-Essentials", "PySide6-Addons"}, (job, pins)
        expected = next(iter(_packaged_gui_pins(platform).values()))
        assert set(pins.values()) == {expected}, (
            f"{job} tests/builds Qt {pins}, but {platform} packages Qt {expected}"
        )

        assert "Pillow==11.3.0" in commands, f"Pillow pin missing from {job}"
        assert not re.search(r"(?<![\w-])Pillow(?!==)", commands), f"unpinned Pillow in {job}"


def test_runtime_qt_matches_packaged_platform_pin() -> None:
    """Verify the actual interpreter, not merely the workflow's pip strings."""
    import PySide6
    from PySide6.QtCore import qVersion

    expected = next(iter(_packaged_gui_pins(sys.platform).values()))
    versions = (PySide6.__version__, qVersion())
    assert all(version == expected for version in versions), (
        f"running bindings/Qt {versions}, but {sys.platform} packages Qt {expected}"
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


def test_windows_images_cover_current_and_newer_runtime() -> None:
    """Do not hide the newer-Windows compatibility defect behind an old image."""
    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    images = workflow["jobs"]["test"]["strategy"]["matrix"]["os"]
    windows = [image for image in images if str(image).startswith("windows-")]
    assert windows == ["windows-2022", "windows-2025"], (
        f"Windows test images {windows!r} must include the old and the newer "
        "host, so the renderer compatibility fix cannot silently regress"
    )
    assert workflow["jobs"]["build-windows"]["runs-on"] == "windows-2025", (
        "Windows packaging must use the pinned newer image validated by the tests"
    )


def test_windows_ci_does_not_bypass_the_renderer_sandbox() -> None:
    """The compatibility correction must retain normal browser security."""
    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    test_job = workflow["jobs"]["test"]
    for node in (workflow, test_job, *test_job["steps"]):
        env = node.get("env") or {}
        assert "QTWEBENGINE_DISABLE_SANDBOX" not in env, "sandbox bypass in CI environment"
        flags = str(env.get("QTWEBENGINE_CHROMIUM_FLAGS", ""))
        run = str(node.get("run", ""))
        for forbidden in ("--no-sandbox", "--disable-sandbox", "QTWEBENGINE_DISABLE_SANDBOX"):
            assert forbidden not in flags + run, f"sandbox bypass {forbidden} in CI"


def test_matrix_jobs_upload_distinct_test_log_artifacts() -> None:
    """Two Windows image versions must not collide in immutable artifact names."""
    import yaml

    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]
    uploads = [step for step in job["steps"]
               if str(step.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(uploads) == 1, "expected one per-job test-log upload"
    step = uploads[0]
    assert step.get("if") == "always()", "failed suites must retain their logs"
    template = step["with"]["name"]
    names = []
    for image in job["strategy"]["matrix"]["os"]:
        host_os = "Windows" if image.startswith("windows-") else (
            "macOS" if image.startswith("macos-") else "Linux"
        )
        name = template.replace("${{ runner.os }}", host_os).replace("${{ matrix.os }}", image)
        assert "${{" not in name, f"unresolved artifact-name expression: {name}"
        names.append(name)
    assert len(names) == len(set(names)), f"matrix log artifact names collide: {names}"


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
    assert len(lines) == 3, (
        f"expected tag checks in both native builders and the Mac input step, found {len(lines)}"
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


def test_linux_release_has_real_test_build_and_publish_gates() -> None:
    """Linux support must execute, produce an artifact and gate publication."""
    import yaml

    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    images = jobs["test"]["strategy"]["matrix"]["os"]
    assert "ubuntu-24.04" in images, "Linux has no full regression runner"
    assert "build-linux" in jobs, "Linux has no packaging job"
    build = jobs["build-linux"]
    assert build["runs-on"] == "ubuntu-24.04", "Linux builder must be pinned"
    condition = str(build.get("if", ""))
    assert "workflow_dispatch" in condition and "refs/tags/v" in condition, (
        "Linux packaging must be testable without publishing and run on tags"
    )
    required = {"test", "build-windows", "build-linux"}
    assert required <= set(jobs["publish"]["needs"]), (
        "publication must wait for tests and every supported platform build"
    )
    uploads = [s for s in build["steps"]
               if str(s.get("uses", "")).startswith("actions/upload-artifact@")
               and s.get("with", {}).get("name") == "LocalProjectHub-Linux"]
    assert len(uploads) == 1 and uploads[0]["with"]["if-no-files-found"] == "error", (
        "a missing Linux installer must fail, not produce a green empty upload"
    )


def test_frontpage_downloads_are_platform_specific_latest_links() -> None:
    """No version-pinned front-page downloads or missing Linux download."""
    import re
    from urllib.parse import unquote, urlparse

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    table = readme.split("## Download\n", 1)[1].split("## Requirements", 1)[0]
    rows = [line for line in table.splitlines()
            if line.startswith("|") and any(p in line for p in ("macOS", "Windows", "Linux"))]
    assert len(rows) == 3, "front page must provide macOS, Windows and Linux downloads"
    names = set()
    for row in rows:
        links = re.findall(r"\]\((https://github\.com/[^)]+)\)", row)
        assert len(links) == 1, f"expected one platform download: {row}"
        path = urlparse(links[0]).path
        prefix = "/different2/local-project-hub/releases/latest/download/"
        assert path.startswith(prefix), f"front-page download is not latest: {links[0]}"
        name = unquote(path.removeprefix(prefix))
        assert name and "/" not in name, f"invalid latest asset name: {name}"
        assert not re.search(r"\d+\.\d+\.\d+", name), f"version-pinned filename: {name}"
        names.add(name)
    assert len(names) == 3, "platforms must not share a generic release-page link"
    assert not re.search(r"Latest version:\s*\*\*v?\d", table), (
        "a hardcoded latest-version label goes stale after the next release"
    )


def test_stable_download_names_match_packaging_and_frontpage() -> None:
    import re
    import runpy
    import yaml

    names = runpy.run_path(str(PROJECT_ROOT / "tools/release_artifacts.py"))["ASSET_NAMES"]
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    readme = (PROJECT_ROOT / "README.md").read_text()
    linked = set(re.findall(r"releases/latest/download/([^\s)]+)", readme))
    assert linked == set(names.values()), "front-page asset names differ from packaging contract"
    for platform, filename in names.items():
        if platform == "macos":
            commands = "\n".join(s.get("run", "") for s in jobs["publish"]["steps"])
            assert "release_artifacts.py collect macos --source incoming-macos --output artifacts" in commands
            assert "--file artifacts/" + filename in commands
            continue
        job = jobs["build-" + platform]
        installers = [s for s in job["steps"]
                      if s.get("with", {}).get("name", "").startswith("LocalProjectHub-")]
        assert len(installers) == 1 and installers[0]["with"]["path"] == "release-assets/" + filename, (
            "uploaded installer path differs from stable download contract", platform
        )
        assert any("release_artifacts.py collect " + platform in str(s.get("run", ""))
                   for s in job["steps"]), ("stable collector missing", platform)


def test_linux_installed_runtime_acceptance_precedes_installer_upload() -> None:
    import yaml

    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build-linux"]["steps"]
    runtime = [(i, s) for i, s in enumerate(steps)
               if "smoke_linux_installer.py" in str(s.get("run", ""))]
    assert len(runtime) == 1, "actual installed Linux runtime acceptance is missing"
    index, step = runtime[0]
    assert "if" not in step, "runtime acceptance must not be skipped on release tags"
    assert "--expected-text deliberately-wrong" in step["run"], "missing wrong-DOM observer control"
    upload = next(i for i, s in enumerate(steps)
                  if s.get("with", {}).get("name") == "LocalProjectHub-Linux")
    assert index < upload, "installer was uploaded before runtime acceptance"


def test_release_is_draft_until_all_assets_are_verified() -> None:
    import re
    import yaml

    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["publish"]["steps"]
    download = next(s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact@"))
    assert download["with"]["pattern"] == "LocalProjectHub-*", "test logs must not become release assets"
    commands = "\n".join(str(s.get("run", "")) for s in steps)
    create = next(line for line in commands.splitlines() if "--generate-notes" in line)
    assert 'if [ "$draft" = "false" ]; then' in commands and "refusing to replace published assets" in commands, (
        "rerunning a published tag must not replace live latest-download assets"
    )
    assert re.search(r"--draft(?:\s|$)", create), "new releases must start as private drafts"
    verify = commands.index("release_artifacts.py verify")
    publish = commands.index("--draft=false")
    assert verify < publish and "--allow-draft" in commands[verify:publish], (
        "a complete installer/digest check must precede publication"
    )
    assert re.search(r"--latest(?:\s|$)", commands[publish:]), "new release must explicitly become latest"
    assert "--metadata published.json" in commands[publish:], "publication must be read back and revalidated"
    assert "--json databaseId" in commands[:verify], "drafts must be resolved by release ID, not the unavailable published-tag endpoint"
    assert 'releases/$release_id' in commands[:verify] and 'releases/$release_id' in commands[publish:], (
        "draft and published readback must address the exact same release ID"
    )


def test_macos_is_built_locally_and_never_on_a_hosted_runner() -> None:
    import re
    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text())
    jobs = workflow["jobs"]
    for name, job in jobs.items():
        runners = [job.get("runs-on", "")]
        runners.extend(job.get("strategy", {}).get("matrix", {}).get("os", []))
        assert not any("macos" in str(runner).lower() for runner in runners), (
            f"{name} still uses a hosted macOS runner instead of the developer's Mac"
        )
        assert set(job.get("needs", [])) <= set(jobs), "a deleted builder still blocks a dependent job"
    publish = jobs["publish"]
    assert set(publish["needs"]) == {"test", "build-windows", "build-linux"}
    assert publish["permissions"] == {"contents": "write"}, "private draft inputs require push access"
    assert workflow["permissions"] == {"contents": "read"}
    steps = publish["steps"]
    gates = [(i, step) for i, step in enumerate(steps)
             if "verify-macos-input" in step.get("run", "")]
    assert len(gates) == 1, "the publisher needs an explicit, unskippable local Mac input gate"
    gate_index, gate = gates[0]
    assert "if" not in gate, "the prebuilt input gate must not be skipped"
    commands = gate["run"]
    assert not re.search(r"\bbriefcase\s+(?:build|create|package)\b", commands), (
        "the publisher must not rebuild the Mac binary"
    )
    assert '--source-commit "$GITHUB_SHA"' in commands, (
        "the Mac input gate must bind the installer to the actual job source SHA"
    )
    assert '--file artifacts/Local.Project.Hub.dmg' in commands
    assert commands.count("verify-macos-input") == 2
    assert commands.index("verify-macos-input") < commands.index("gh release download") < commands.index("release_artifacts.py collect macos") < commands.rindex("verify-macos-input")
    upload_index = next(i for i, step in enumerate(steps) if "gh release upload" in step.get("run", ""))
    assert gate_index < upload_index, "unverified local DMG must not become a release upload"
    publish_commands = "\n".join(step.get("run", "") for step in steps)
    assert 'Local.Project.Hub.dmg#source:$GITHUB_SHA' in publish_commands, (
        "private-draft retries must retain the Mac asset's exact source receipt"
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
