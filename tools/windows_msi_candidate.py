#!/usr/bin/env python3
"""TEMP v0.7.4 MSI reference binding; no installation or Qt import on this host.

Expected source bytes come only from immutable Git blobs, never an installed app.
The prospective CRLF vector is NOT accepted until strict installed parity passes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

import smoke_windows_msi as smoke


REPOSITORY = "different2/local-project-hub"
WORKFLOW = ".github/workflows/ci.yml"
JOB_NAME = "Build Windows installer"
ARTIFACT_NAME = "LocalProjectHub-Windows"
MSI_NAME = "Local.Project.Hub.msi"
VERSION = "0.7.4"
POLICY = "exact-LF-to-CRLF-expansion-from-pinned-Git-blobs-only"
SCHEMA = "lph-temp-msi-candidate-v2"


def canonical_vector(root: Path, *, source_sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise smoke.SmokeError("source SHA must be a literal 40-character lowercase Git identity")
    if smoke.git_read(root, "rev-parse", "--verify", "HEAD") != source_sha:
        raise smoke.SmokeError("candidate source checkout HEAD differs from frozen source")
    if smoke.git_read(root, "status", "--porcelain", "--untracked-files=all", "--ignored"):
        raise smoke.SmokeError("dirty candidate source checkout, including untracked/ignored files")
    tree = smoke.git_read(root, "ls-tree", "-r", source_sha, "--", "hub", "main.py")
    files = {}
    for line in tree.splitlines():
        identity, name = line.split("\t", 1)
        mode, kind, blob = identity.split()
        if mode != "100644" or kind != "blob" or not name.endswith(".py"):
            raise smoke.SmokeError("unexpected immutable runtime membership/mode")
        raw = smoke.git_blob(root, blob)
        if b"\r" in raw or (root / name).read_bytes() != raw:
            raise smoke.SmokeError(f"noncanonical LF candidate source: {name}")
        expected = raw.replace(b"\n", b"\r\n")
        files[name] = dict(git_blob=blob, canonical_sha256=hashlib.sha256(raw).hexdigest(),
                           canonical_bytes=len(raw), expected_sha256=hashlib.sha256(expected).hexdigest(),
                           expected_bytes=len(expected), lf=raw.count(b"\n"))
    if "hub/__init__.py" not in files or "main.py" not in files:
        raise smoke.SmokeError("candidate runtime must include its package and entry point")
    if smoke.source_manifest(root) != {name: row["canonical_sha256"] for name, row in files.items()}:
        raise smoke.SmokeError("canonical runtime membership/hash differs from immutable Git")
    return files


def positive_id(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise smoke.SmokeError(f"{label} must be a literal positive integer")
    return value


def validate_artifact_window(started, completed, created) -> None:
    times = []
    for label, value in (("builder started", started), ("builder completed", completed), ("artifact created", created)):
        if not isinstance(value, str) or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
            raise smoke.SmokeError(f"{label} timestamp must be explicit RFC3339 with timezone")
        try:
            times.append(datetime.fromisoformat(value))
        except ValueError as exc:
            raise smoke.SmokeError(f"invalid {label} timestamp") from exc
    if not times[0] <= times[2] <= times[1]:
        raise smoke.SmokeError("artifact was not created during the exact builder attempt; refusing a stale/cross-attempt artifact")


def validate_build_metadata(run: dict, jobs: dict, artifact: dict, *, source_sha: str, run_id: int,
                            attempt: int, job_id: int, artifact_id: int) -> dict:
    for label, value in (("run_id", run_id), ("attempt", attempt), ("job_id", job_id), ("artifact_id", artifact_id)):
        positive_id(value, label)
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise smoke.SmokeError("source SHA must be literal lowercase hex")
    if (run.get("id") != run_id or run.get("run_attempt") != attempt
            or run.get("head_sha") != source_sha or run.get("head_branch") != "main"
            or run.get("event") != "workflow_dispatch" or run.get("path") != WORKFLOW
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("repository", {}).get("private") is not False):
        raise smoke.SmokeError("source run/repository/SHA/event/workflow/attempt binding differs")
    # No full-matrix wait: a successful exact builder is sufficient for early QA.
    if run.get("status") not in {"queued", "in_progress", "completed"}:
        raise smoke.SmokeError("source run has an unknown status")
    # The overall run may finish red because another matrix job failed. That is
    # a release blocker, not a reason to skip explicitly authorized installer QA.
    # Only this exact native builder's executed successful steps authorize QA.
    rows = jobs.get("jobs", [])
    if not isinstance(rows, list) or jobs.get("total_count") != len(rows):
        raise smoke.SmokeError("jobs metadata incomplete; retrieve all attempt jobs")
    matches = [row for row in rows if row.get("id") == job_id or row.get("name") == JOB_NAME]
    if len(matches) != 1:
        raise smoke.SmokeError("source Windows builder missing/ambiguous")
    job = matches[0]
    if (job.get("id") != job_id or job.get("run_id") != run_id or job.get("head_sha") != source_sha
            or job.get("name") != JOB_NAME or job.get("status") != "completed"
            or job.get("conclusion") != "success" or "windows-2025" not in job.get("labels", [])
            or "self-hosted" in job.get("labels", [])
            or not job.get("completed_at") or job.get("run_attempt") != attempt):
        raise smoke.SmokeError("exact native Windows builder has not completed successfully")
    for name in ("Build the MSI installer", "Collect the installer"):
        steps = [step for step in job.get("steps", []) if step.get("name") == name]
        if len(steps) != 1 or steps[0].get("status") != "completed" or steps[0].get("conclusion") != "success":
            raise smoke.SmokeError(f"native builder step did not execute successfully: {name}")
    repository_id = positive_id(run["repository"].get("id"), "repository_id")
    origin = artifact.get("workflow_run", {})
    if (artifact.get("id") != artifact_id or artifact.get("name") != ARTIFACT_NAME
            or artifact.get("expired") is not False or not artifact.get("created_at")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest") or "")
            or origin.get("id") != run_id or origin.get("head_sha") != source_sha
            or origin.get("head_branch") != "main" or origin.get("repository_id") != repository_id
            or origin.get("head_repository_id") != repository_id):
        raise smoke.SmokeError("exact unexpired artifact identity/digest/source-run binding differs")
    validate_artifact_window(job.get("started_at"), job.get("completed_at"), artifact.get("created_at"))
    return dict(repository=REPOSITORY, repository_id=repository_id, source_sha=source_sha,
                workflow=WORKFLOW, event="workflow_dispatch", branch="main",
                source_run_id=run_id, source_run_attempt=attempt, source_job_id=job_id,
                source_job_name=JOB_NAME, source_job_started_at=job["started_at"], source_job_completed_at=job["completed_at"],
                artifact_id=artifact_id, artifact_name=ARTIFACT_NAME,
                artifact_digest=artifact["digest"], artifact_created_at=artifact["created_at"])


def validate_reference(reference: dict) -> None:
    if (reference.get("schema") != SCHEMA or not re.fullmatch(r"[0-9a-f]{40}", reference.get("source_sha") or "")
            or reference.get("version") != VERSION or reference.get("policy") != POLICY
            or reference.get("scope") != "early installer inspection only; NOT source-matrix/release acceptance"):
        raise smoke.SmokeError("candidate reference schema/source/version/policy/scope differs")
    build, msi = reference.get("build", {}), reference.get("msi", {})
    fixed = dict(repository=REPOSITORY, source_sha=reference["source_sha"],
                 source_job_name=JOB_NAME, artifact_name=ARTIFACT_NAME,
                 workflow=WORKFLOW, event="workflow_dispatch", branch="main")
    if any(build.get(key) != value for key, value in fixed.items()):
        raise smoke.SmokeError("candidate reference build identity differs")
    for key in ("repository_id", "source_run_id", "source_run_attempt", "source_job_id", "artifact_id"):
        positive_id(build.get(key), key)
    if (not re.fullmatch(r"sha256:[0-9a-f]{64}", build.get("artifact_digest") or "")
            or not build.get("source_job_completed_at") or not build.get("artifact_created_at")):
        raise smoke.SmokeError("candidate reference lacks real artifact digest/completed builder identity")
    validate_artifact_window(build.get("source_job_started_at"), build.get("source_job_completed_at"), build.get("artifact_created_at"))
    if msi.get("filename") != MSI_NAME or not re.fullmatch(r"[0-9a-f]{64}", msi.get("sha256") or ""):
        raise smoke.SmokeError("candidate reference MSI filename/digest invalid")
    positive_id(msi.get("bytes"), "msi_bytes")
    if not isinstance(reference.get("files"), dict) or not reference["files"]:
        raise smoke.SmokeError("candidate reference must enumerate exact runtime files")


def load_reference(path: Path, expected_sha256: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        raise smoke.SmokeError("reference SHA-256 must be literal lowercase hex")
    if path.is_symlink() or not path.is_file():
        raise smoke.SmokeError("reference must be an actual regular file")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise smoke.SmokeError("candidate reference digest differs from explicit pin")
    reference = json.loads(raw)
    validate_reference(reference)
    return reference


def verify_msi(path: Path, reference: dict) -> None:
    expected = reference["msi"]
    if (path.is_symlink() or not path.is_file() or path.name != expected["filename"]
            or path.stat().st_size != expected["bytes"] or smoke.sha256_file(path) != expected["sha256"]):
        raise smoke.SmokeError("actual MSI filename/size/raw digest differs from pinned candidate")
    with path.open("rb") as stream:
        if stream.read(8) != bytes.fromhex("d0cf11e0a1b11ae1"):
            raise smoke.SmokeError("candidate is not an MSI compound-file container")


def verify_archive(path: Path, reference: dict) -> None:
    if path.is_symlink() or not path.is_file() or "sha256:" + smoke.sha256_file(path) != reference["build"]["artifact_digest"]:
        raise smoke.SmokeError("actual downloaded artifact ZIP digest differs from GitHub binding")
    expected = reference["msi"]
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        if len(rows) != 1:
            raise smoke.SmokeError("artifact archive must contain exactly the MSI, with no stale/extra entries")
        row = rows[0]
        if (row.filename != MSI_NAME or row.is_dir() or row.file_size != expected["bytes"]
                or stat.S_IFMT(row.external_attr >> 16) not in {0, stat.S_IFREG} or row.flag_bits & 1):
            raise smoke.SmokeError("artifact archive MSI membership/type/size differs")
        digest = hashlib.sha256()
        with archive.open(row) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected["sha256"]:
            raise smoke.SmokeError("archive MSI bytes differ from explicit MSI pin")


def bind_reference(root: Path, msi: Path, archive: Path, run: dict, jobs: dict, artifact: dict, *,
                   source_sha: str, run_id: int, attempt: int, job_id: int, artifact_id: int,
                   msi_sha256: str, msi_bytes: int) -> dict:
    build = validate_build_metadata(run, jobs, artifact, source_sha=source_sha, run_id=run_id, attempt=attempt,
                                    job_id=job_id, artifact_id=artifact_id)
    reference = dict(schema=SCHEMA, source_sha=source_sha, version=VERSION, policy=POLICY,
        scope="early installer inspection only; NOT source-matrix/release acceptance",
        build=build, msi=dict(filename=MSI_NAME, sha256=msi_sha256, bytes=msi_bytes),
        files=canonical_vector(root, source_sha=source_sha))
    validate_reference(reference)
    verify_msi(msi, reference)
    verify_archive(archive, reference)
    return reference


def derive_candidate_reference(root: Path, destination: Path, reference: dict) -> dict:
    validate_reference(reference)
    files = canonical_vector(root, source_sha=reference["source_sha"])
    if files != reference["files"]:
        raise smoke.SmokeError("candidate vector differs from immutable Git blobs/membership/byte transform")
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(root.resolve()):
        raise smoke.SmokeError("expected reference must be a new directory outside source")
    destination.mkdir(parents=True, exist_ok=False)
    for name, row in files.items():
        raw = smoke.git_blob(root, row["git_blob"]).replace(b"\n", b"\r\n")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return dict(source_sha=reference["source_sha"], msi_sha256=reference["msi"]["sha256"], policy=POLICY,
                canonical_hashes={name: row["canonical_sha256"] for name, row in files.items()},
                expected_hashes=smoke.source_manifest(destination), build=reference["build"])


def verify_build_binding(reference: dict, run: dict, jobs: dict, artifact: dict) -> dict:
    validate_reference(reference)
    build = reference["build"]
    actual = validate_build_metadata(run, jobs, artifact, source_sha=reference["source_sha"], run_id=build["source_run_id"],
        attempt=build["source_run_attempt"], job_id=build["source_job_id"], artifact_id=build["artifact_id"])
    if actual != build:
        raise smoke.SmokeError("fresh build/artifact metadata differs from exact bound identities")
    return dict(build=actual, source_matrix_status=run["status"], source_matrix_conclusion=run.get("conclusion"),
                scope=reference["scope"])


def extract_archive(archive: Path, reference: dict, destination: Path) -> Path:
    verify_archive(archive, reference)
    if destination.exists() or destination.is_symlink():
        raise smoke.SmokeError("refusing existing artifact extraction directory")
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / MSI_NAME
    with zipfile.ZipFile(archive) as bundle, bundle.open(MSI_NAME) as source, target.open("xb") as output:
        shutil.copyfileobj(source, output, 1024 * 1024)
    verify_msi(target, reference)
    return target


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise smoke.SmokeError(f"metadata must be a regular file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind", help="bind real MSI + GitHub artifact ZIP + API identities; no placeholder values")
    bind.add_argument("--source-root", type=Path, required=True)
    bind.add_argument("--source-sha", required=True)
    bind.add_argument("--msi", type=Path, required=True)
    bind.add_argument("--artifact-zip", type=Path, required=True)
    bind.add_argument("--source-run-id", type=int, required=True)
    bind.add_argument("--source-run-attempt", type=int, required=True)
    bind.add_argument("--source-job-id", type=int, required=True)
    bind.add_argument("--source-artifact-id", type=int, required=True)
    bind.add_argument("--msi-sha256", required=True)
    bind.add_argument("--msi-bytes", type=int, required=True)
    bind.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("check", help="validate explicitly pinned reference identity")
    verify = commands.add_parser("verify-build", help="check fresh exact job/artifact metadata, without waiting for the matrix")
    download = commands.add_parser("download", help="read exact GitHub artifact ZIP by ID; verify before safe extraction")
    download.add_argument("--output-dir", type=Path, required=True)
    for command in (check, verify, download):
        command.add_argument("--reference", type=Path, required=True)
        command.add_argument("--reference-sha256", required=True)
    for command in (bind, verify, download):
        command.add_argument("--run-json", type=Path, required=True)
        command.add_argument("--jobs-json", type=Path, required=True)
        command.add_argument("--artifact-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "bind":
            if args.output.exists() or args.output.is_symlink() or args.output.resolve().is_relative_to(args.source_root.resolve()):
                raise smoke.SmokeError("manifest must be a new file outside the runtime/source checkout")
            reference = bind_reference(args.source_root, args.msi, args.artifact_zip,
                read_json(args.run_json), read_json(args.jobs_json), read_json(args.artifact_json),
                source_sha=args.source_sha, run_id=args.source_run_id, attempt=args.source_run_attempt, job_id=args.source_job_id,
                artifact_id=args.source_artifact_id, msi_sha256=args.msi_sha256, msi_bytes=args.msi_bytes)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(reference, stream, indent=2, sort_keys=True)
                stream.write("\n")
            print(json.dumps(dict(reference=str(args.output), sha256=smoke.sha256_file(args.output),
                                  msi=reference["msi"], scope=reference["scope"])))
        else:
            reference = load_reference(args.reference, args.reference_sha256)
            if args.command == "check":
                print(json.dumps(reference))
            else:
                receipt = verify_build_binding(reference, read_json(args.run_json), read_json(args.jobs_json), read_json(args.artifact_json))
                if args.command == "download":
                    if args.output_dir.exists() or args.output_dir.is_symlink():
                        raise smoke.SmokeError("download destination must be new")
                    args.output_dir.mkdir(parents=True, exist_ok=False)
                    archive = args.output_dir / "artifact.zip"
                    endpoint = f"repos/{REPOSITORY}/actions/artifacts/{reference['build']['artifact_id']}/zip"
                    with archive.open("xb") as stream:
                        result = subprocess.run(["gh", "api", endpoint], stdout=stream, stderr=subprocess.PIPE, timeout=240, check=False)
                    if result.returncode != 0:
                        raise smoke.SmokeError(f"read-only artifact download failed: gh exit {result.returncode}")
                    receipt["msi"] = str(extract_archive(archive, reference, args.output_dir / "files"))
                    receipt["archive_sha256"] = smoke.sha256_file(archive)
                    with (args.output_dir / "binding-receipt.json").open("x", encoding="utf-8", newline="\n") as stream:
                        json.dump(receipt, stream, indent=2)
                        stream.write("\n")
                print(json.dumps(receipt))
        return 0
    except (smoke.SmokeError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
