"""TEMP dispatch transport guards; these tests do not execute CI or Windows."""
from pathlib import Path
import unittest

import yaml

PATH = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


class WorkflowTests(unittest.TestCase):
    def test_native_job_cannot_allocate_private_fork_or_main_runner_time(self):
        data = yaml.safe_load(PATH.read_text(encoding="utf-8"))
        job = data["jobs"]["msi-native"]
        self.assertEqual(job.get("if"), "github.repository == 'different2/local-project-hub' && github.event.repository.private == false && github.ref == 'refs/heads/diagnose/windows-msi-native'")

    def test_dispatch_requires_reference_digest_and_pins_source_from_validated_manifest(self):
        data = yaml.safe_load(PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(data["on"]), {"workflow_dispatch"})
        dispatch = data["on"]["workflow_dispatch"]
        self.assertIsInstance(dispatch, dict, "dispatch must require a real bound-reference SHA-256")
        self.assertTrue(dispatch["inputs"]["reference_sha256"]["required"])
        self.assertNotIn("default", dispatch["inputs"]["reference_sha256"])
        self.assertEqual(data["permissions"], {"contents": "read", "actions": "read"})
        self.assertEqual(set(data["jobs"]), {"msi-native"})
        job = data["jobs"]["msi-native"]
        self.assertEqual(job["runs-on"], "windows-2025")
        steps = job["steps"]
        source = next(step for step in steps if step.get("with", {}).get("path") == "source")
        self.assertEqual(source["with"]["ref"], "${{ steps.binding.outputs.source_sha }}")
        self.assertEqual(source["with"]["fetch-depth"], 0)
        binding = next(step for step in steps if step.get("id") == "binding")
        self.assertLess(steps.index(binding), steps.index(source))
        self.assertIn("windows_msi_candidate.py check", binding["run"])
        self.assertEqual(binding["env"]["EXPECTED_REFERENCE_SHA256"], "${{ inputs.reference_sha256 }}")
        native = next(step for step in steps if "temp_capture_windows_msi.py --msi" in step.get("run", ""))
        for flag in ("--reference", "--reference-sha256", "--build-run-json", "--build-jobs-json", "--build-artifact-json"):
            self.assertIn(flag, native["run"])
        self.assertIn("$ref.source_sha", native["run"])
        all_runs = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("windows_msi_candidate.py download", all_runs)
        self.assertIn("$ref.build.source_run_id", all_runs)
        self.assertIn("$ref.build.source_run_attempt", all_runs)
        self.assertIn("$ref.build.artifact_id", all_runs)
        for forbidden in ("gh workflow run", "gh run watch", "Start-Sleep", "gh release", "41804484621", "77aaa1877c3c586634f572ede63f9bf7095abb08"):
            self.assertNotIn(forbidden, all_runs)
        upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(upload["if"], "always()")
        paths = upload["with"]["path"]
        for required in ("report.json", "native-window.png", "native-capture.json", "binding-receipt.json", "windows_msi_candidate_reference.json"):
            self.assertIn(required, paths)
        self.assertNotIn("_runtime", paths)
        self.assertNotIn("**", paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
