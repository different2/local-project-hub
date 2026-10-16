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
