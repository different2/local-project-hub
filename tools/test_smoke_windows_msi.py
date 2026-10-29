"""Pure, stdlib-only tests. Native MSI/Win32 execution is NOT simulated as acceptance."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("smoke_windows_msi", HERE / "smoke_windows_msi.py")
smoke = importlib.util.module_from_spec(SPEC) if SPEC and SPEC.loader and SPEC.origin and Path(SPEC.origin).exists() else None
if smoke is not None:
    SPEC.loader.exec_module(smoke)


class LaunchSafetyTests(unittest.TestCase):
    def test_native_command_and_environment_are_isolated(self):
        self.assertIsNotNone(smoke, "MSI harness implementation is missing")
        original = {
            "SystemRoot": r"C:\Windows", "PATH": r"C:\secret\bin",
            "PYTHONPATH": "checkout", "PYTHONHOME": "wrong-python",
            "PYTHONINSPECT": "1", "QT_QPA_PLATFORM": "offscreen",
            "QTWEBENGINE_CHROMIUM_FLAGS": "--remote-debugging-port=5555",
            "GITHUB_TOKEN": "do-not-inherit", "AWS_SECRET_ACCESS_KEY": "do-not-inherit",
            "APPDATA": "real-roaming", "LOCALAPPDATA": "real-local",
        }
        env = smoke.app_environment(original, Path("owned space"), 49157)
        self.assertEqual(env["QTWEBENGINE_REMOTE_DEBUGGING"], "127.0.0.1:49157")
        for key in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "PYTHONPATH", "PYTHONHOME", "PYTHONINSPECT", "QT_QPA_PLATFORM", "QTWEBENGINE_CHROMIUM_FLAGS"):
            self.assertNotIn(key, env)
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LOCAL_PROJECT_HUB_HOME", "TEMP", "TMP", "TMPDIR", "XDG_CACHE_HOME"):
            self.assertTrue(Path(env[key]).is_relative_to(Path("owned space")), key)
        self.assertEqual(original["APPDATA"], "real-roaming")
        self.assertEqual(smoke.windows_command([r"C:\CI Python\python.exe", "-I", "-u", r"D:\owned space\dashboard.py", r"D:\owned space\fixture.json"]),
                         '"C:\\CI Python\\python.exe" -I -u "D:\\owned space\\dashboard.py" "D:\\owned space\\fixture.json"')
        smoke.validate_no_bypass(env, [r"C:\installed\hub.exe"])
        for environment, argv in (({"QTWEBENGINE_DISABLE_SANDBOX": "0"}, []), ({"qtwebengine_disable_sandbox": "1"}, []),
                                  ({"QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox"}, []), ({}, ["QtWebEngineProcess.exe --type=renderer --no-sandbox"]),
                                  ({}, ["--disable-gpu-sandbox"]), ({"CHROME_FLAGS": "--disable-features=NetworkServiceSandbox"}, [])):
            with self.subTest(environment=environment, argv=argv), self.assertRaises(smoke.SmokeError):
                smoke.validate_no_bypass(environment, argv)
        self.assertEqual(smoke.install_argv("msiexec.exe", Path("artifact.msi"), Path("install.log")),
                         ["msiexec.exe", "/i", "artifact.msi", "/qn", "/norestart", "REBOOT=ReallySuppress", "/L*V!", "install.log"])
        code = "{25F599D7-F44F-5B9D-8CC0-FC312B836125}"
        self.assertEqual(smoke.uninstall_argv("msiexec.exe", code, Path("uninstall.log")),
                         ["msiexec.exe", "/x", code, "/qn", "/norestart", "REBOOT=ReallySuppress", "/L*V!", "uninstall.log"])
        for invalid in (code.lower() + " ", "/x something", "25F599D7-F44F-5B9D-8CC0-FC312B836125"):
            with self.assertRaises(smoke.SmokeError):
                smoke.uninstall_argv("msiexec.exe", invalid, Path("uninstall.log"))


class ObservationTests(unittest.TestCase):
    def test_nonce_dom_and_debug_endpoint_reject_wrong_or_hidden_pages(self):
        self.assertTrue(hasattr(smoke, "validate_dom"), "nonce DOM observer is missing")
        url = "http://127.0.0.1:49158/nonce"
        good = dict(title="nonce title", text="nonce body", url=url, visibility="visible", ready="complete", width=800, height=600)
        smoke.validate_dom(good, title="nonce title", text="nonce body", url=url)
        for key, value in (("title", "wrong"), ("text", "wrong"), ("url", url + "other"), ("visibility", "hidden"), ("width", 0), ("height", -1)):
            with self.subTest(key=key), self.assertRaises(smoke.SmokeError):
                smoke.validate_dom(dict(good, **{key: value}), title="nonce title", text="nonce body", url=url)
        endpoint = "ws://127.0.0.1:49157/devtools/page/owned"
        target = dict(type="page", url=url, webSocketDebuggerUrl=endpoint)
        self.assertEqual(smoke.target_endpoint([target], url, 49157), endpoint)
        self.assertIsNone(smoke.target_endpoint([target], url + "wrong", 49157))
        for bad in (endpoint.replace("127.0.0.1", "example.org"), endpoint.replace("49157", "49159"), endpoint.replace("ws:", "wss:"), endpoint.replace("/page/", "/browser/")):
            with self.subTest(bad=bad), self.assertRaises(smoke.SmokeError):
                smoke.target_endpoint([dict(target, webSocketDebuggerUrl=bad)], url, 49157)
        with self.assertRaises(smoke.SmokeError):
            smoke.target_endpoint([target, target], url, 49157)


class OwnershipTests(unittest.TestCase):
    def test_process_ownership_rejects_reused_or_older_parent_identity(self):
        self.assertTrue(hasattr(smoke, "descendant_identities"), "creation-identity ownership is missing")
        rows = {10: dict(pid=10, ppid=1, created=100.0), 11: dict(pid=11, ppid=10, created=101.0),
                12: dict(pid=12, ppid=11, created=102.0), 13: dict(pid=13, ppid=10, created=99.0),
                14: dict(pid=14, ppid=50, created=104.0)}
        self.assertEqual(smoke.descendant_identities(rows, {10: 100.0}), {10: 100.0, 11: 101.0, 12: 102.0})
        self.assertEqual(smoke.descendant_identities(rows, {10: 98.0}), {})
        del rows[10]
        self.assertEqual(smoke.descendant_identities(rows, {10: 100.0, 11: 101.0}), {11: 101.0, 12: 102.0})
        good = dict(exit_code=0, forced=[], remaining={}, close_requested=True)
        smoke.validate_cleanup(good)
        for delta in (dict(exit_code=1), dict(exit_code=None), dict(forced=[11]), dict(remaining={11: 101.0}), dict(close_requested=False)):
            with self.subTest(delta=delta), self.assertRaises(smoke.SmokeError):
                smoke.validate_cleanup(dict(good, **delta))


class PayloadTests(unittest.TestCase):
    def test_payload_hashes_and_source_restoration_are_strict(self):
        self.assertTrue(hasattr(smoke, "source_manifest"), "source hash/restore safeguards are missing")
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            base = Path(directory)
            source, installed = base / "source", base / "installed"
            for root in (source, installed):
                (root / "hub").mkdir(parents=True)
                (root / "hub/__init__.py").write_bytes(b"# identical source\n")
                (root / "main.py").write_bytes(b"# entry source\n")
            manifest = smoke.source_manifest(source)
            self.assertEqual(set(manifest), {"main.py", "hub/__init__.py"})
            self.assertEqual(smoke.compare_payload(source, installed), manifest)
            (installed / "hub/__init__.py").write_bytes(b"# different source\n")
            with self.assertRaises(smoke.SmokeError):
                smoke.compare_payload(source, installed)
            (installed / "hub/__init__.py").write_bytes(b"# identical source\n")
            (installed / "hub/stale.py").write_bytes(b"# unexpected stale payload\n")
            with self.assertRaises(smoke.SmokeError):
                smoke.compare_payload(source, installed)
            report = {}
            with self.assertRaisesRegex(RuntimeError, "owned failure"):
                with smoke.hidden_source(source, report):
                    self.assertFalse((source / "hub").exists())
                    self.assertFalse((source / "main.py").exists())
                    raise RuntimeError("owned failure")
            self.assertTrue(report["source_restored"])
            self.assertEqual(smoke.source_manifest(source), manifest)
            (source / "main.py").unlink()
            with self.assertRaises(smoke.SmokeError):
                with smoke.hidden_source(source, {}):
                    self.fail("a missing source entry must not reach native launch")
            self.assertTrue((source / "hub/__init__.py").is_file())


class ArtifactGuardTests(unittest.TestCase):
    def test_msi_identity_is_literal_and_preserves_productcode(self):
        self.assertTrue(hasattr(smoke, "validate_msi_properties"), "MSI identity guard is missing")
        props = dict(ProductName="Local Project Hub", ProductCode="{01234567-89AB-CDEF-0123-456789ABCDEF}", UpgradeCode=smoke.EXPECTED_UPGRADE_CODE, ProductVersion="0.7.4")
        self.assertEqual(smoke.validate_msi_properties(props, "0.7.4"), props["ProductCode"])
        for key, wrong in (("ProductCode", props["ProductCode"] + " "), ("UpgradeCode", props["ProductCode"]), ("ProductVersion", "0.7.3"), ("ProductName", "Unrelated app")):
            with self.subTest(key=key), self.assertRaises(smoke.SmokeError):
                smoke.validate_msi_properties(dict(props, **{key: wrong}), "0.7.4")

    def test_executable_is_a_real_amd64_pe_container(self):
        self.assertTrue(hasattr(smoke, "check_pe"), "installed PE inspection is missing")
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "controlled-container.exe"
            header = bytearray(160)
            header[:2] = b"MZ"
            struct.pack_into("<I", header, 0x3c, 128)
            header[128:132] = b"PE\0\0"
            struct.pack_into("<H", header, 132, 0x8664)
            path.write_bytes(header)
            smoke.check_pe(path)
            for payload in (b"# not an executable", bytes(header).replace(b"PE\0\0", b"bad!")):
                path.write_bytes(payload)
                with self.assertRaises(smoke.SmokeError):
                    smoke.check_pe(path)


class NativeEntryTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "Mac/non-Windows refusal probe only; never installs in pure tests")
    def test_cli_refuses_non_windows_and_never_clobbers_evidence(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            output = Path(directory) / "native-refusal"
            argv = [sys.executable, "-B", str(HERE / "smoke_windows_msi.py"), "--msi", str(Path(directory) / "not-present.msi"),
                    "--output", str(output), "--expected-version", "0.7.4", "--source-sha", "77aaa1877c3c586634f572ede63f9bf7095abb08"]
            result = subprocess.run(argv, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, "native-only entry incorrectly reported success on this Mac")
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])
            self.assertIn("Windows", report["error"])
            before = (output / "report.json").read_bytes()
            again = subprocess.run(argv, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual((output / "report.json").read_bytes(), before)
            self.assertFalse((output / "install.log").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
