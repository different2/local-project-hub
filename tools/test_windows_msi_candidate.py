"""Pure candidate controls; fixtures are NOT native MSI acceptance evidence."""
from __future__ import annotations

import hashlib

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE_SHA = "6b88effaa4663723d3e0666f6cf3dae4437a86ba"  # superseded immutable control only
sys.path.insert(0, str(HERE))
import smoke_windows_msi as smoke

import windows_msi_candidate as candidate


class CanonicalCandidateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(candidate, "candidate reference implementation is missing")
        self.tmp = tempfile.TemporaryDirectory(prefix="candidate-reference-", dir=HERE)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.source = self.base / "source"
        sha = "6b88effaa4663723d3e0666f6cf3dae4437a86ba"
        repositories = (HERE.parent, HERE.parent.parent / "source", HERE.parent.parent / "windows-source")
        repository = next((p for p in repositories if subprocess.run(
            ["git", "-C", str(p), "cat-file", "-e", sha + "^{commit}"], capture_output=True).returncode == 0), None)
        self.assertIsNotNone(repository, "immutable candidate commit must be locally available")
        subprocess.run(["git", "clone", "--shared", "--no-checkout", str(repository), str(self.source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "core.autocrlf=false", "checkout", "--detach", sha], check=True, capture_output=True)

    def test_new_vector_comes_only_from_exact_candidate_git_blobs(self):
        before = smoke.source_manifest(self.source)
        vector = candidate.canonical_vector(self.source, source_sha=SOURCE_SHA)
        self.assertEqual(len(vector), 23)
        self.assertIn("hub/browser_downloads.py", vector)
        self.assertEqual(set(vector), set(before))
        old = smoke.load_payload_reference()
        self.assertNotEqual(set(vector), set(old["files"]))
        for name, row in vector.items():
            canonical = subprocess.check_output(["git", "-C", str(self.source), "show", SOURCE_SHA + ":" + name])
            expected = canonical.replace(b"\n", b"\r\n")
            self.assertNotIn(b"\r", canonical)
            self.assertEqual(row["canonical_sha256"], hashlib.sha256(canonical).hexdigest())
            self.assertEqual(row["expected_sha256"], hashlib.sha256(expected).hexdigest())
            self.assertEqual(row["canonical_bytes"], len(canonical))
            self.assertEqual(row["expected_bytes"], len(expected))
            self.assertEqual(row["lf"], canonical.count(b"\n"))
            self.assertEqual((self.source / name).read_bytes(), canonical)
        self.assertEqual(smoke.source_manifest(self.source), before)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.source), "status", "--porcelain", "--ignored"]), b"")

    def controlled_binding(self):
        import zipfile
        msi = self.base / "Local.Project.Hub.msi"
        msi.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"SIMULATED CONTAINER CONTROL ONLY; NOT AN INSTALLER")
        archive = self.base / "controlled-artifact.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.write(msi, msi.name)
        run, jobs, artifact = simulated_build_metadata()
        artifact["digest"] = "sha256:" + smoke.sha256_file(archive)
        self.assertTrue(hasattr(candidate, "bind_reference"), "actual artifact binding/manifest generator is missing")
        reference = candidate.bind_reference(self.source, msi, archive, run, jobs, artifact,
            source_sha=SOURCE_SHA, run_id=41804484621, attempt=1, job_id=126488018155, artifact_id=321,
            msi_sha256=smoke.sha256_file(msi), msi_bytes=msi.stat().st_size)
        return reference, msi, archive

    def test_bound_reference_materializes_new_payload_and_rejects_raw_corruption(self):
        import copy
        reference, msi, archive = self.controlled_binding()
        manifest = self.base / "controlled-reference.json"
        manifest.write_text(json.dumps(reference), encoding="utf-8")
        loaded = candidate.load_reference(manifest, smoke.sha256_file(manifest))
        expected = self.base / "expected"
        receipt = candidate.derive_candidate_reference(self.source, expected, loaded)
        self.assertEqual(len(receipt["expected_hashes"]), 23)
        self.assertEqual(receipt["msi_sha256"], smoke.sha256_file(msi))
        installed = self.base / "installed"
        shutil.copytree(expected, installed)
        evidence = self.base / "evidence"
        evidence.mkdir()
        report = {}
        smoke.observe_payload_parity(self.source, expected, installed, report, evidence)
        path = installed / "hub/browser_downloads.py"
        original = path.read_bytes()
        for corrupt in (original.replace(b"\r\n", b"\n", 1), original + b"# corruption", original.replace(b"\r\n", b"\r\r\n", 1)):
            path.write_bytes(corrupt)
            with self.assertRaises(smoke.SmokeError):
                smoke.observe_payload_parity(self.source, expected, installed, report, evidence)
            self.assertEqual(path.read_bytes(), corrupt, "installed bytes must never be normalized")
            saved = json.loads((evidence / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(saved["payload_parity"]["matched"])
            self.assertIn("installed", saved["payload_parity"])
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(smoke.SmokeError):
            smoke.compare_payload(expected, installed)
        path.write_bytes(original)
        (installed / "hub/stale.py").write_bytes(b"# stale\r\n")
        with self.assertRaises(smoke.SmokeError):
            smoke.compare_payload(expected, installed)
        (installed / "hub/stale.py").unlink()
        self.assertEqual(smoke.compare_payload(expected, installed), receipt["expected_hashes"])
        for mutation in ("canonical_sha256", "expected_sha256", "git_blob", "lf"):
            bad = copy.deepcopy(reference)
            row = bad["files"]["hub/browser_downloads.py"]
            row[mutation] = "0" * len(row[mutation]) if isinstance(row[mutation], str) else row[mutation] + 1
            with self.subTest(mutation=mutation), self.assertRaises(smoke.SmokeError):
                candidate.derive_candidate_reference(self.source, self.base / ("bad-" + mutation), bad)
        for name in ("missing", "extra"):
            bad = copy.deepcopy(reference)
            if name == "missing":
                del bad["files"]["hub/browser_downloads.py"]
            else:
                bad["files"]["hub/extra.py"] = bad["files"]["main.py"]
            with self.assertRaises(smoke.SmokeError):
                candidate.derive_candidate_reference(self.source, self.base / name, bad)
        with self.assertRaises(smoke.SmokeError):
            candidate.load_reference(manifest, "0" * 64)
        with self.assertRaises(smoke.SmokeError):
            candidate.derive_candidate_reference(self.source, self.source / "build/reference", reference)
        with self.assertRaises(smoke.SmokeError):
            candidate.derive_candidate_reference(self.source, expected, reference)

    def test_archive_identity_and_exact_payload_are_required_before_binding(self):
        import zipfile
        reference, msi, archive = self.controlled_binding()
        candidate.verify_archive(archive, reference)
        original = msi.read_bytes()
        msi.write_bytes(original + b"bad")
        with self.assertRaises(smoke.SmokeError):
            candidate.verify_msi(msi, reference)
        msi.write_bytes(original)
        for entries in ((MSI := "Local.Project.Hub.msi", "../escape"), ("other.msi",), (MSI, "stale.txt")):
            bad = self.base / "bad.zip"
            with zipfile.ZipFile(bad, "w") as stream:
                for name in entries:
                    stream.writestr(name, original)
            mutated = json.loads(json.dumps(reference))
            mutated["build"]["artifact_digest"] = "sha256:" + smoke.sha256_file(bad)
            with self.subTest(entries=entries), self.assertRaises(smoke.SmokeError):
                candidate.verify_archive(bad, mutated)
        archive.write_bytes(archive.read_bytes() + b"tampered archive")
        with self.assertRaises(smoke.SmokeError):
            candidate.verify_archive(archive, reference)

    def test_dirty_source_and_wrong_commit_are_rejected_before_materialization(self):
        reference, _, _ = self.controlled_binding()
        for name in ("README.md", "unknown.txt", "build/ignored.txt"):
            path = self.source / name
            before = path.read_bytes() if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"control dirty source\n")
            try:
                with self.subTest(name=name), self.assertRaises(smoke.SmokeError):
                    candidate.derive_candidate_reference(self.source, self.base / "dirty", reference)
                self.assertFalse((self.base / "dirty").exists())
            finally:
                if before is not None:
                    path.write_bytes(before)
                else:
                    path.unlink()
                    if name.startswith("build/"):
                        path.parent.rmdir()
        subprocess.run(["git", "-C", str(self.source), "-c", "core.autocrlf=false", "checkout", "--detach", smoke.PINNED_SOURCE_SHA], check=True, capture_output=True)
        with self.assertRaises(smoke.SmokeError):
            candidate.derive_candidate_reference(self.source, self.base / "wrong-head", reference)

    def test_binding_cli_uses_real_files_and_never_overwrites_or_accepts_partial_input(self):
        reference, msi, archive = self.controlled_binding()
        run, jobs, artifact = simulated_build_metadata()
        artifact["digest"] = "sha256:" + smoke.sha256_file(archive)
        paths = {}
        for name, data in (("run", run), ("jobs", jobs), ("artifact", artifact)):
            paths[name] = self.base / (name + ".json")
            paths[name].write_text(json.dumps(data), encoding="utf-8")
        output = self.base / "bound.json"
        command = [sys.executable, "-B", str(HERE / "windows_msi_candidate.py"), "bind",
            "--source-root", str(self.source), "--source-sha", SOURCE_SHA, "--msi", str(msi), "--artifact-zip", str(archive),
            "--run-json", str(paths["run"]), "--jobs-json", str(paths["jobs"]), "--artifact-json", str(paths["artifact"]),
            "--source-run-id", "41804484621", "--source-run-attempt", "1", "--source-job-id", "126488018155",
            "--source-artifact-id", "321", "--msi-sha256", smoke.sha256_file(msi), "--msi-bytes", str(msi.stat().st_size),
            "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_file(), "bind CLI must actually create the bound manifest")
        self.assertEqual(json.loads(output.read_text()), reference)
        before = output.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(result.stdout, "")
        partial = subprocess.run([sys.executable, "-B", str(HERE / "windows_msi_candidate.py"), "bind"], capture_output=True, text=True)
        self.assertNotEqual(partial.returncode, 0)
        self.assertEqual(partial.stdout, "")
        digest = smoke.sha256_file(output)
        check = [sys.executable, "-B", str(HERE / "windows_msi_candidate.py"), "check",
                 "--reference", str(output), "--reference-sha256", digest]
        result = subprocess.run(check, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["msi"], reference["msi"])
        verify = check[:3] + ["verify-build", *check[4:], "--run-json", str(paths["run"]),
                    "--jobs-json", str(paths["jobs"]), "--artifact-json", str(paths["artifact"])]
        result = subprocess.run(verify, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["source_matrix_status"], "in_progress")
        artifact["digest"] = "sha256:" + "0" * 64
        paths["artifact"].write_text(json.dumps(artifact), encoding="utf-8")
        result = subprocess.run(verify, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        extracted = self.base / "extracted"
        candidate.extract_archive(archive, reference, extracted)
        self.assertEqual((extracted / msi.name).read_bytes(), msi.read_bytes())
        with self.assertRaises(smoke.SmokeError):
            candidate.extract_archive(archive, reference, extracted)

    def test_native_entry_routes_exact_binding_before_any_installer_api(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        reference, msi, archive = self.controlled_binding()
        run, jobs, artifact = simulated_build_metadata()
        artifact["digest"] = "sha256:" + smoke.sha256_file(archive)
        manifest = self.base / "native-reference.json"
        manifest.write_text(json.dumps(reference), encoding="utf-8")
        paths = {}
        for name, data in (("run", run), ("jobs", jobs), ("artifact", artifact)):
            paths[name] = self.base / ("native-" + name + ".json")
            paths[name].write_text(json.dumps(data), encoding="utf-8")
        output = self.base / "native-output"
        output.mkdir()
        args = SimpleNamespace(source_root=self.source, msi=msi, output=output,
            source_sha=SOURCE_SHA, expected_version="0.7.4", reference=manifest,
            reference_sha256=smoke.sha256_file(manifest), build_run_json=paths["run"],
            build_jobs_json=paths["jobs"], build_artifact_json=paths["artifact"])
        report = {}
        # This is only a pure pre-install routing control. No Win32 API can run.
        with patch.object(smoke, "native_preflight", return_value={}), patch.dict(sys.modules, {"psutil": SimpleNamespace()}), \
                patch.object(smoke, "MsiApi", side_effect=RuntimeError("BEFORE-NATIVE-INSTALL-CONTROL")) as api:
            with self.assertRaisesRegex(RuntimeError, "BEFORE-NATIVE-INSTALL-CONTROL"):
                smoke.run_smoke(args, report)
            self.assertEqual(api.call_count, 1)
            self.assertEqual(report["artifact_binding"]["build"], reference["build"])
            self.assertEqual(report["artifact_binding"]["source_matrix_status"], "in_progress")
            args.reference_sha256 = "0" * 64
            with self.assertRaises(smoke.SmokeError):
                smoke.run_smoke(args, {})
            self.assertEqual(api.call_count, 1, "bad binding must fail before installer API")
        args.reference_sha256 = smoke.sha256_file(manifest)
        self.assertTrue(hasattr(smoke, "preinstall_candidate_binding"))
        args.reference = None
        with self.assertRaises(smoke.SmokeError):
            smoke.preinstall_candidate_binding(args, self.source, msi, {})

    def test_rebinding_requires_explicit_fresh_immutable_source_run_and_job(self):
        import inspect
        self.assertIn("source_sha", inspect.signature(candidate.bind_reference).parameters,
                      "generic rebinding must require an explicit source SHA, not the superseded 6b vector")
        previous, msi, archive = self.controlled_binding()
        new_file = self.source / "hub/rebinding_control.py"
        new_file.write_bytes(b"# owned synthetic rebind control, NOT production source\n")
        subprocess.run(["git", "-C", str(self.source), "add", "hub/rebinding_control.py"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=different", "-c", "user.email=isamud@hotmail.com",
                        "commit", "-m", "Owned synthetic rebinding control"], check=True, capture_output=True)
        new_sha = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True).strip()
        run, jobs, artifact = simulated_build_metadata()
        run.update(id=7, head_sha=new_sha, status="completed", conclusion="failure")
        jobs["jobs"][0].update(id=8, run_id=7, head_sha=new_sha)
        artifact["workflow_run"].update(id=7, head_sha=new_sha)
        artifact["digest"] = "sha256:" + smoke.sha256_file(archive)
        reference = candidate.bind_reference(self.source, msi, archive, run, jobs, artifact,
            source_sha=new_sha, run_id=7, attempt=1, job_id=8, artifact_id=321,
            msi_sha256=smoke.sha256_file(msi), msi_bytes=msi.stat().st_size)
        self.assertEqual(reference["source_sha"], new_sha)
        self.assertEqual(reference["build"]["source_run_id"], 7)
        self.assertEqual(len(reference["files"]), 24)
        candidate.derive_candidate_reference(self.source, self.base / "rebound", reference)
        with self.assertRaises(smoke.SmokeError):
            candidate.derive_candidate_reference(self.source, self.base / "superseded", previous)
        with self.assertRaises(smoke.SmokeError):
            candidate.bind_reference(self.source, msi, archive, run, jobs, artifact,
                source_sha=SOURCE_SHA, run_id=7, attempt=1, job_id=8, artifact_id=321,
                msi_sha256=smoke.sha256_file(msi), msi_bytes=msi.stat().st_size)

    def test_download_cli_preserves_binary_bytes_and_verifies_before_extraction(self):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        from unittest.mock import patch
        reference, msi, archive = self.controlled_binding()
        run, jobs, artifact = simulated_build_metadata()
        artifact["digest"] = "sha256:" + smoke.sha256_file(archive)
        manifest = self.base / "download-reference.json"
        manifest.write_text(json.dumps(reference), encoding="utf-8")
        metadata_args = []
        for name, data in (("run", run), ("jobs", jobs), ("artifact", artifact)):
            path = self.base / ("download-" + name + ".json")
            path.write_text(json.dumps(data), encoding="utf-8")
            metadata_args.extend(["--" + name + "-json", str(path)])
        def transport(argv, **kwargs):
            self.assertEqual(argv, ["gh", "api", "repos/different2/local-project-hub/actions/artifacts/321/zip"])
            self.assertNotIn("text", kwargs, "archive bytes must not be decoded")
            kwargs["stdout"].write(archive.read_bytes())
            return SimpleNamespace(returncode=0)
        output = self.base / "downloaded"
        argv = ["download", "--reference", str(manifest), "--reference-sha256", smoke.sha256_file(manifest),
                *metadata_args, "--output-dir", str(output)]
        stdout, stderr = StringIO(), StringIO()
        with patch.object(candidate.subprocess, "run", side_effect=transport), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(candidate.main(argv), 0, stderr.getvalue())
        self.assertEqual((output / "artifact.zip").read_bytes(), archive.read_bytes())
        self.assertEqual((output / "files" / msi.name).read_bytes(), msi.read_bytes())
        receipt = json.loads((output / "binding-receipt.json").read_text())
        self.assertEqual(receipt["build"]["artifact_id"], 321)
        def corrupted_transport(argv, **kwargs):
            kwargs["stdout"].write(b"CONTROL corrupted transport; not an archive")
            return SimpleNamespace(returncode=0)
        bad = self.base / "bad-download"
        stdout, stderr = StringIO(), StringIO()
        with patch.object(candidate.subprocess, "run", side_effect=corrupted_transport), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(candidate.main([*argv[:-1], str(bad)]), 1)
        self.assertFalse((bad / "files").exists())
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("digest", stderr.getvalue())


class SplitWebEnginePayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="webengine-payload-control-", dir=HERE)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.expected, self.install = self.base / "expected", self.base / "install"
        for root in (self.expected, self.install / "app"):
            (root / "hub").mkdir(parents=True)
            (root / "hub/__init__.py").write_bytes(b"# controlled payload\r\n")
            (root / "main.py").write_bytes(b"# controlled entry\r\n")
        app_metadata = self.install / "app/hub-0.7.4.dist-info/METADATA"
        app_metadata.parent.mkdir()
        app_metadata.write_text("Name: hub\nVersion: 0.7.4\n", encoding="utf-8")
        packages = self.install / "app_packages"
        for name, version in (("PySide6_Essentials", "6.12.0"), ("PySide6_Addons", "6.12.0"),
                              ("shiboken6", "6.12.0"), ("PySide6_WebEngine", "6.12.0.140")):
            metadata = packages / (name + "-" + version + ".dist-info/METADATA")
            metadata.parent.mkdir(parents=True)
            metadata.write_text(f"Name: {name.replace('_', '-')}\nVersion: {version}\n", encoding="utf-8")
        self.pyside = packages / "PySide6"
        self.pyside.mkdir()
        (self.pyside / "__init__.py").write_text('__version__ = "6.12.0"\n', encoding="utf-8")
        header = bytearray(160)
        header[:2] = b"MZ"
        import struct
        struct.pack_into("<I", header, 0x3c, 128)
        header[128:132] = b"PE\0\0"
        struct.pack_into("<H", header, 132, 0x8664)
        self.launcher = self.install / "Local Project Hub.exe"
        self.launcher.write_bytes(header)
        for name in ("QtWebEngineProcess.exe", "QtWebEngineCore.pyd", "QtWebEngineWidgets.pyd",
                     "Qt6WebEngineCore.dll", "Qt6WebEngineWidgets.dll", "Qt6Core.dll"):
            (self.pyside / name).write_bytes(header)
        for name in ("resources/qtwebengine_resources.pak", "resources/qtwebengine_resources_100p.pak",
                     "resources/qtwebengine_resources_200p.pak", "translations/qtwebengine_locales/en-US.pak"):
            path = self.pyside / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"CONTROL resource only")

    def test_separate_webengine_version_and_real_modules_resources_are_required(self):
        result = smoke.installed_payload(self.expected, self.launcher, "0.7.4")
        self.assertIn("pyside6-webengine", result["distributions"], "split WebEngine distribution must be inspected explicitly")
        self.assertEqual(result["distributions"]["pyside6-webengine"]["version"], "6.12.0.140")
        self.assertEqual(set(result["webengine_modules"]), {"QtWebEngineCore.pyd", "QtWebEngineWidgets.pyd"})
        metadata = self.install / "app_packages/PySide6_WebEngine-6.12.0.140.dist-info/METADATA"
        original = metadata.read_bytes()
        for corrupted in (b"Name: PySide6-WebEngine\nVersion: 6.12.0\n", b"Name: unrelated\nVersion: 6.12.0.140\n"):
            metadata.write_bytes(corrupted)
            with self.assertRaises(smoke.SmokeError):
                smoke.installed_payload(self.expected, self.launcher, "0.7.4")
        metadata.write_bytes(original)
        for name in ("QtWebEngineCore.pyd", "QtWebEngineWidgets.pyd", "QtWebEngineProcess.exe", "Qt6WebEngineCore.dll",
                     "resources/qtwebengine_resources.pak", "translations/qtwebengine_locales/en-US.pak"):
            path = self.pyside / name
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(missing=name), self.assertRaises(smoke.SmokeError):
                smoke.installed_payload(self.expected, self.launcher, "0.7.4")
            path.write_bytes(raw)
        (self.pyside / "QtWebEngineCore.pyd").write_bytes(b"not an AMD64 module")
        with self.assertRaises(smoke.SmokeError):
            smoke.installed_payload(self.expected, self.launcher, "0.7.4")


def simulated_build_metadata() -> tuple[dict, dict, dict]:
    """Controlled API-shaped data, not retrieved build/artifact evidence."""
    run = dict(id=41804484621, run_attempt=1, head_sha="6b88effaa4663723d3e0666f6cf3dae4437a86ba",
               head_branch="main", event="workflow_dispatch", path=".github/workflows/ci.yml",
               status="in_progress", conclusion=None, repository=dict(full_name="different2/local-project-hub", id=123, private=False))
    job = dict(id=126488018155, run_id=run["id"], head_sha=run["head_sha"], name="Build Windows installer",
               status="completed", conclusion="success", labels=["windows-2025"], run_attempt=1,
               started_at="2026-11-04T09:55:00Z", completed_at="2026-11-04T10:00:00Z", steps=[
                   dict(name=name, status="completed", conclusion="success")
                   for name in ("Build the MSI installer", "Collect the installer")])
    artifact = dict(id=321, name="LocalProjectHub-Windows", expired=False,
                    digest="sha256:" + hashlib.sha256(b"SIMULATED ARCHIVE CONTROL ONLY").hexdigest(),
                    created_at="2026-11-04T10:00:00Z", workflow_run=dict(id=run["id"], repository_id=123,
                        head_repository_id=123, head_branch="main", head_sha=run["head_sha"]))
    return run, dict(total_count=1, jobs=[job]), artifact


class EarlyBuildBindingTests(unittest.TestCase):
    def validate(self, run, jobs, artifact):
        self.assertIsNotNone(candidate)
        self.assertTrue(hasattr(candidate, "validate_build_metadata"), "exact early-builder/artifact binding is missing")
        return candidate.validate_build_metadata(run, jobs, artifact, run_id=41804484621,
                                                 source_sha=SOURCE_SHA, attempt=1, job_id=126488018155, artifact_id=321)

    def test_successful_exact_builder_is_accepted_while_source_matrix_runs(self):
        run, jobs, artifact = simulated_build_metadata()
        build = self.validate(run, jobs, artifact)
        self.assertEqual(build["source_run_id"], 41804484621)
        self.assertEqual(build["source_job_id"], 126488018155)
        self.assertEqual(build["artifact_id"], 321)
        self.assertEqual(build["artifact_digest"], artifact["digest"])
        self.assertNotIn("release_accepted", build)
        # A different source-matrix job failing blocks release, not this explicitly
        # requested early installer inspection. Preserve that state in the receipt.
        run.update(status="completed", conclusion="failure")
        self.assertEqual(self.validate(run, jobs, artifact), build)

    def test_missing_job_attempt_cannot_inherit_the_requested_attempt(self):
        run, jobs, artifact = simulated_build_metadata()
        del jobs["jobs"][0]["run_attempt"]
        with self.assertRaisesRegex(smoke.SmokeError, "builder|attempt"):
            self.validate(run, jobs, artifact)

    def test_artifact_creation_must_fall_inside_the_exact_builder_attempt(self):
        run, jobs, artifact = simulated_build_metadata()
        self.validate(run, jobs, artifact)
        for timestamp in ("2026-11-04T09:54:59Z", "2026-11-04T10:00:01Z",
                          "2026-11-04T09:59:00", "not-a-timestamp", ""):
            run, jobs, artifact = simulated_build_metadata()
            artifact["created_at"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(smoke.SmokeError, "artifact|timestamp|builder"):
                self.validate(run, jobs, artifact)
        for start in (None, "2026-11-04T10:00:01Z", "2026-11-04T09:55:00"):
            run, jobs, artifact = simulated_build_metadata()
            jobs["jobs"][0]["started_at"] = start
            with self.subTest(start=start), self.assertRaises(smoke.SmokeError):
                self.validate(run, jobs, artifact)

    def test_build_metadata_refuses_private_or_self_hosted_runner_substitutions(self):
        for private in (True, None):
            run, jobs, artifact = simulated_build_metadata()
            if private is None:
                del run["repository"]["private"]
            else:
                run["repository"]["private"] = private
            with self.subTest(private=private), self.assertRaises(smoke.SmokeError):
                self.validate(run, jobs, artifact)
        run, jobs, artifact = simulated_build_metadata()
        jobs["jobs"][0]["labels"] = ["self-hosted", "windows-2025"]
        with self.assertRaises(smoke.SmokeError):
            self.validate(run, jobs, artifact)

    def test_run_job_event_source_and_artifact_disagreements_fail_closed(self):
        import copy
        controls = (("run", "id", 1), ("run", "head_sha", smoke.PINNED_SOURCE_SHA),
                    ("run", "head_branch", "diagnose/windows-msi-native"), ("run", "event", "push"),
                    ("run", "path", ".github/workflows/other.yml"), ("run", "run_attempt", 2),
                    ("job", "id", 2), ("job", "run_id", 1), ("job", "head_sha", smoke.PINNED_SOURCE_SHA),
                    ("job", "name", "Tests (windows-2025)"), ("job", "conclusion", None),
                    ("job", "status", "in_progress"), ("job", "labels", ["self-hosted"]),
                    ("artifact", "id", 322), ("artifact", "name", "LocalProjectHub-Linux"),
                    ("artifact", "expired", True), ("artifact", "digest", ""))
        for target, key, value in controls:
            with self.subTest(target=target, key=key):
                run, jobs, artifact = copy.deepcopy(simulated_build_metadata())
                {"run": run, "job": jobs["jobs"][0], "artifact": artifact}[target][key] = value
                with self.assertRaises(smoke.SmokeError):
                    self.validate(run, jobs, artifact)
        for key, value in (("id", 1), ("head_sha", smoke.PINNED_SOURCE_SHA), ("head_branch", "other"),
                           ("repository_id", 456), ("head_repository_id", 456)):
            run, jobs, artifact = simulated_build_metadata()
            artifact["workflow_run"][key] = value
            with self.subTest(artifact_run=key), self.assertRaises(smoke.SmokeError):
                self.validate(run, jobs, artifact)
        run, jobs, artifact = simulated_build_metadata()
        jobs["jobs"].append(dict(jobs["jobs"][0]))
        jobs["total_count"] = 2
        with self.assertRaises(smoke.SmokeError):
            self.validate(run, jobs, artifact)
        run, jobs, artifact = simulated_build_metadata()
        jobs["total_count"] = 2
        with self.assertRaises(smoke.SmokeError):
            self.validate(run, jobs, artifact)
        run, jobs, artifact = simulated_build_metadata()
        jobs["jobs"][0]["steps"][0]["conclusion"] = "skipped"
        with self.assertRaises(smoke.SmokeError):
            self.validate(run, jobs, artifact)


class NativeCaptureReceiptTests(unittest.TestCase):
    def test_wrapper_calls_composite_gate_and_refusal_preserves_prior_evidence(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        from unittest.mock import patch
        import temp_capture_windows_msi as capture
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            output = Path(directory) / "wrapper-output"
            def controlled_msi_result():
                output.mkdir()
                smoke.checkpoint(output, {"passed": True, "scope": "SIMULATED routing control only"})
                return 0
            original = smoke.NativeWindows.window
            fake_ctypes = SimpleNamespace(windll=SimpleNamespace(user32=SimpleNamespace(SetProcessDPIAware=lambda: None)))
            with patch.object(sys, "argv", [str(HERE / "temp_capture_windows_msi.py"), "--output", str(output)]), \
                    patch.object(smoke, "main", side_effect=controlled_msi_result), patch.object(capture, "ctypes", fake_ctypes), \
                    redirect_stdout(StringIO()):
                self.assertEqual(capture.main(), 1, "MSI-only success with no native capture must fail")
            report = json.loads((output / "report.json").read_text())
            self.assertFalse(report["passed"], "wrapper must call the composite verdict, not just change its exit")
            self.assertFalse(report["native_capture"]["attempted"])
            self.assertIs(smoke.NativeWindows.window, original)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with patch.object(sys, "argv", [str(HERE / "temp_capture_windows_msi.py"), "--output", str(output)]), \
                    patch.object(smoke, "main", return_value=2), patch.object(capture, "ctypes", fake_ctypes), redirect_stdout(StringIO()):
                self.assertEqual(capture.main(), 2)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_native_pixel_failure_cannot_leave_a_passing_msi_report(self):
        import temp_capture_windows_msi as capture
        self.assertTrue(hasattr(capture, "finalize_capture"), "native-pixel verdict must be part of the final report")
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            for native_code, pixels, expected in ((0, False, 1), (0, True, 0), (1, True, 1)):
                output = Path(directory) / f'case-{native_code}-{pixels}'
                output.mkdir()
                smoke.checkpoint(output, {"passed": native_code == 0})
                status = dict(attempted=True, passed=pixels)
                code = capture.finalize_capture(output, status, native_code)
                report = json.loads((output / "report.json").read_text())
                self.assertEqual(code, expected)
                self.assertEqual(report["passed"], expected == 0)
                self.assertEqual(report["native_capture"]["passed"], pixels)
                self.assertEqual(report["native_msi_passed"], native_code == 0)
            before = (output / "report.json").read_bytes()
            self.assertNotEqual(capture.finalize_capture(output, dict(attempted=False, passed=False), 2, preexisting=True), 0)
            self.assertEqual((output / "report.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
