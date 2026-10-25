"""Pure external-smoke controls; no Qt imports, processes, GUI or servers.

Run with Python 3.11+: python -m unittest discover -s tests -p test_linux_smoke.py -v
The actual installed-app acceptance runs only on Ubuntu CI.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def harness() -> Any:
    path = ROOT / "tools" / "smoke_linux_installer.py"
    assert path.is_file(), "installed Linux smoke harness is missing"
    spec = importlib.util.spec_from_file_location("linux_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SafetyTests(unittest.TestCase):
    def test_refuses_root_and_sandbox_bypasses_before_launch(self):
        smoke = harness()
        for uid, euid, env, argv in (
            (0, 1001, {}, []),
            (1001, 0, {}, []),
            (1001, 1001, {"QTWEBENGINE_DISABLE_SANDBOX": "0"}, []),
            (1001, 1001, {"QTWEBENGINE_DISABLE_SANDBOX": ""}, []),
            (1001, 1001, {"QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox"}, []),
            (1001, 1001, {"CHROMIUM_FLAGS": "--disable-seccomp-filter-sandbox"}, []),
            (1001, 1001, {}, ["hub", "--no-sandbox=true"]),
            (1001, 1001, {}, ["helper", "--disable-setuid-sandbox"]),
            (1001, 1001, {}, ["helper", "--single-process"]),
            (1001, 1001, {}, ["helper --type=renderer --no-sandbox"]),
        ):
            with self.subTest(uid=uid, euid=euid, env=env, argv=argv):
                with self.assertRaisesRegex(smoke.SmokeError, "root|sandbox|single-process"):
                    smoke.validate_launch(env, uid, euid, argv)
        smoke.validate_launch({"DISPLAY": ":99"}, 1001, 1001, ["/usr/bin/hub"])


class DomTests(unittest.TestCase):
    def test_requires_exact_title_body_url_and_exposed_webview(self):
        smoke = harness()
        check = getattr(smoke, "validate_dom", None)
        self.assertTrue(callable(check), "exact DOM acceptance is missing")
        expected = {"title": "LPH nonce", "text": "Installed nonce", "url": "http://127.0.0.1:12345/nonce"}
        dom = dict(expected, visibility="visible", width=900, height=600, ready="complete")
        check(dom, **expected)
        for delta in (
            {"title": "LPH wrong"}, {"text": "Installed nonce extra"},
            {"text": "wrong"}, {"url": expected["url"] + "other"},
            {"visibility": "hidden"}, {"width": 0}, {"height": 0}, {"ready": "loading"},
        ):
            with self.subTest(delta=delta):
                with self.assertRaises(smoke.SmokeError):
                    check(dict(dom, **delta), **expected)
        with self.assertRaisesRegex(smoke.SmokeError, "text"):
            check(dom, **dict(expected, text="negative-control"))


class ProcessTests(unittest.TestCase):
    def test_renderer_evidence_requires_real_helper_and_proc_sandbox(self):
        smoke = harness()
        parse = getattr(smoke, "parse_status", None)
        self.assertTrue(callable(parse), "proc status acceptance is missing")
        assert callable(parse)
        status = parse("Name:\tQtWebEngineProc\nState:\tS (sleeping)\nUid:\t1001 1001 1001 1001\nNoNewPrivs:\t1\nSeccomp:\t2\nSeccomp_filters:\t1\nNSpid:\t123 4\n")
        self.assertEqual(status["uids"], [1001] * 4)
        self.assertEqual(status["nspid"], [123, 4])
        helper = "/usr/lib/hub/app_packages/PySide6/Qt/libexec/QtWebEngineProcess"
        renderer = {"pid": 123, "exe": helper, "argv": [helper, "--type=renderer"], "status": status, "environment": {}, "namespaces": {"user": "user:[123]"}}
        self.assertEqual(smoke.validate_renderers([renderer], helper), [renderer])
        # Actual Chromium /proc cmdline can be one rewritten process-title
        # field, not separate NUL-delimited argument fields (CI40197205064).
        titled = dict(renderer, argv=[helper + " --type=renderer --lang=en"])
        self.assertEqual(smoke.validate_renderers([titled], helper), [titled])
        for rows in (
            [], [dict(renderer, exe="/source/QtWebEngineProcess")],
            [dict(renderer, argv=[helper, "--type=zygote"])],
            [dict(renderer, status=dict(status, uids=[0] * 4))],
            [dict(renderer, status=dict(status, no_new_privs=0))],
            [dict(renderer, status=dict(status, seccomp=0))],
            [dict(renderer, status=parse("Name:\tx\n"))],
            [dict(renderer, argv=renderer["argv"] + ["--no-sandbox"])],
            [dict(renderer, environment={"QTWEBENGINE_DISABLE_SANDBOX": "1"})],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(smoke.SmokeError):
                    smoke.validate_renderers(rows, helper)

    def test_proc_stat_and_ancestry_reject_reused_or_unrelated_pids(self):
        smoke = harness()
        parse = getattr(smoke, "parse_stat", None)
        self.assertTrue(callable(parse), "PID identity parsing is missing")
        assert callable(parse)
        row = parse("41 (hub ) with spaces) S 40 " + " ".join(["0"] * 17 + ["900"]))
        self.assertEqual((row["pid"], row["ppid"], row["start_time"]), (41, 40, "900"))
        rows = {41: row, 42: {"pid": 42, "ppid": 41, "start_time": "901"}, 43: {"pid": 43, "ppid": 42, "start_time": "902"}, 99: {"pid": 99, "ppid": 2, "start_time": "903"}}
        self.assertEqual(smoke.descendant_identities(rows, {41: "900"}), {41: "900", 42: "901", 43: "902"})
        self.assertEqual(smoke.descendant_identities(rows, {41: "old"}), {})
        self.assertEqual(smoke.verified_identities(rows, {41: "old", 42: "901", 1: "fake"}), {42: "901"})


class WaitTests(unittest.TestCase):
    def test_missing_renderer_times_out_and_crashes_fail_immediately(self):
        smoke = harness()
        wait = getattr(smoke, "wait_for", None)
        self.assertTrue(callable(wait), "bounded crash-aware wait is missing")
        assert callable(wait)
        now = [0.0]
        def clock():
            return now[0]
        def sleep(seconds):
            now[0] += seconds
        with self.assertRaisesRegex(smoke.SmokeError, "renderer.*timed out"):
            wait(lambda: None, lambda: None, "renderer", 1, clock=clock, sleep=sleep)
        self.assertLessEqual(now[0], 1.1)
        for exitcode in (0, 1, -11):
            with self.subTest(exitcode=exitcode):
                with self.assertRaisesRegex(smoke.SmokeError, "exited.*" + str(exitcode)):
                    wait(lambda: {"looks": "ready"}, lambda: exitcode, "DOM", 1, clock=clock, sleep=sleep)
        self.assertEqual(wait(lambda: {"ready": True}, lambda: None, "DOM", 1, clock=clock, sleep=sleep), {"ready": True})


class FixtureTests(unittest.TestCase):
    def test_fixture_uses_validated_store_autostart_and_dynamic_port(self):
        smoke = harness()
        seed = getattr(smoke, "seed_fixture", None)
        self.assertTrue(callable(seed), "isolated Store fixture is missing")
        assert callable(seed)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            result = seed(ROOT, work, "/ci/python", "nonce123")
            registry = json.loads((work / "state" / "registry.json").read_text())
            rec, = registry["projects"]
            self.assertTrue(rec["autostart"])
            self.assertNotIn("auto_start", rec)
            self.assertEqual(rec["url"], "")  # Must exercise stdout URL discovery.
            self.assertEqual(rec["detected"]["type"], "web")
            self.assertIn("/ci/python", rec["command"])
            self.assertIn("-I", rec["command"])
            self.assertEqual(json.loads((work / "state" / "ui.json").read_text())["last_project"], rec["id"])
            self.assertEqual(result["text"], "Installed dashboard nonce123")
            script = Path(result["script"]).read_text()
            ast.parse(script)
            self.assertIn('("127.0.0.1", 0)', script)
            self.assertIn("server_address[1]", script)
            self.assertIn("flush=True", script)

    def test_app_environment_cannot_import_from_checkout_or_actions_python(self):
        smoke = harness()
        make_env = getattr(smoke, "app_environment", None)
        self.assertTrue(callable(make_env), "clean installed environment is missing")
        assert callable(make_env)
        original = {"DISPLAY": ":99", "DBUS_SESSION_BUS_ADDRESS": "unix:path=test", "XAUTHORITY": "/own/auth", "HOME": "/real/user", "PYTHONPATH": "/checkout", "PYTHONHOME": "/actions", "LD_LIBRARY_PATH": "/actions/lib", "LD_PRELOAD": "/alien.so", "QTWEBENGINEPROCESS_PATH": "/source/helper", "QT_PLUGIN_PATH": "/source/plugins"}
        env = make_env(original, Path("/disposable"), 43210)
        for key in ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "LD_PRELOAD", "QTWEBENGINEPROCESS_PATH", "QT_PLUGIN_PATH"):
            self.assertNotIn(key, env)
        self.assertEqual(env["QTWEBENGINE_REMOTE_DEBUGGING"], "127.0.0.1:43210")
        self.assertEqual(env["QT_QPA_PLATFORM"], "xcb")
        self.assertEqual(env["LOCAL_PROJECT_HUB_HOME"], "/disposable/state")
        self.assertEqual(env["HOME"], "/disposable/home")
        self.assertEqual(env["XAUTHORITY"], original["XAUTHORITY"])
        self.assertEqual(original["PYTHONPATH"], "/checkout")

    def test_source_hiding_is_restored_even_when_acceptance_fails(self):
        smoke = harness()
        hide = getattr(smoke, "hidden_source", None)
        self.assertTrue(callable(hide), "source unavailability control is missing")
        assert callable(hide)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hub").mkdir()
            (root / "hub" / "sentinel").write_text("preserve")
            (root / "main.py").write_text("preserve main")
            provenance = {}
            with self.assertRaisesRegex(RuntimeError, "negative control"):
                with hide(root, report=provenance) as paths:
                    self.assertFalse((root / "hub").exists())
                    self.assertFalse((root / "main.py").exists())
                    self.assertEqual(len(paths), 2)
                    raise RuntimeError("negative control")
            self.assertIs(provenance["source_restored"], True)
            self.assertEqual((root / "hub" / "sentinel").read_text(), "preserve")
            self.assertEqual((root / "main.py").read_text(), "preserve main")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["hub", "main.py"])


class ProcFilesystemTests(unittest.TestCase):
    def test_records_only_verified_owned_processes_and_readable_namespaces(self):
        smoke = harness()
        read = getattr(smoke, "process_evidence", None)
        self.assertTrue(callable(read), "external proc evidence reader is missing")
        assert callable(read)
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            pid = proc / "41"
            (pid / "ns").mkdir(parents=True)
            (pid / "stat").write_text("41 (Qt helper) S 40 " + " ".join(["0"] * 17 + ["900"]))
            (pid / "status").write_text("Uid:\t1001 1001 1001 1001\nNoNewPrivs:\t1\nSeccomp:\t2\n")
            (pid / "cmdline").write_bytes(b"/installed/helper\0--type=renderer\0")
            (pid / "environ").write_bytes(b"LOCAL_PROJECT_HUB_HOME=/own/state\0PRIVATE_KEY=not-reported\0")
            (pid / "exe").symlink_to("/installed/helper")
            (pid / "cwd").symlink_to("/outside-checkout")
            (pid / "ns" / "user").symlink_to("user:[77]")
            row = read(41, "900", proc)
            self.assertEqual(row["exe"], "/installed/helper")
            self.assertEqual(row["status"]["seccomp"], 2)
            self.assertEqual(row["namespaces"]["user"], "user:[77]")
            self.assertIn("unreadable", row["namespaces"]["pid"])
            self.assertNotIn("PRIVATE_KEY", row["environment"])
            self.assertEqual(smoke.process_table(proc)[41]["start_time"], "900")
            with self.assertRaisesRegex(smoke.SmokeError, "identity"):
                read(41, "old", proc)

    def test_signalling_uses_pidfd_and_rechecks_start_identity(self):
        smoke = harness()
        send = getattr(smoke, "signal_owned", None)
        self.assertTrue(callable(send), "PID-reuse-safe signalling is missing")
        assert callable(send)
        events = []
        def opened(pid, flags):
            events.append(("open", pid))
            return 7
        def delivered(fd, sig):
            events.append(("signal", fd, sig))
        def closed(fd):
            events.append(("close", fd))
        self.assertFalse(send(41, "old", 15, identity=lambda pid: "new", open_fd=opened, send_fd=delivered, close_fd=closed))
        self.assertEqual(events, [])
        tokens = iter(["900", "reused"])
        self.assertFalse(send(41, "900", 15, identity=lambda pid: next(tokens), open_fd=opened, send_fd=delivered, close_fd=closed))
        self.assertEqual(events, [("open", 41), ("close", 7)])
        events.clear()
        self.assertTrue(send(41, "900", 15, identity=lambda pid: "900", open_fd=opened, send_fd=delivered, close_fd=closed))
        self.assertEqual(events, [("open", 41), ("signal", 7, 15), ("close", 7)])


class InstalledPackageTests(unittest.TestCase):
    def test_inventory_requires_native_launcher_version_and_bundled_qt_assets(self):
        smoke = harness()
        inventory = getattr(smoke, "installed_inventory", None)
        self.assertTrue(callable(inventory), "installed native inventory is missing")
        assert callable(inventory)
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            qt = prefix / "usr/lib/hub/app_packages/PySide6/Qt"
            for relative, content in {
                "usr/bin/hub": b"\x7fELFfake-unit-fixture",
                "usr/lib/hub/app/main.py": b"# fixture",
                "usr/lib/hub/app/hub/__main__.py": b"# fixture",
                # Match the REAL app: version is metadata-derived, not literal.
                "usr/lib/hub/app/hub/__init__.py": (ROOT / "hub/__init__.py").read_bytes(),
                "usr/lib/hub/app/hub-0.7.1.dist-info/METADATA": b"Name: hub\nVersion: 0.7.1\n",
                "usr/lib/hub/app_packages/PySide6/__init__.py": b'__version__ = "6.7.3"',
                "usr/lib/hub/app_packages/PySide6/Qt/libexec/QtWebEngineProcess": b"\x7fELFunit",
                "usr/lib/hub/app_packages/PySide6/Qt/resources/qtwebengine_resources.pak": b"unit",
                "usr/lib/hub/app_packages/PySide6/Qt/translations/qtwebengine_locales/en-US.pak": b"unit",
            }.items():
                path = prefix / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            package = ["hub\t0.7.1-1\tamd64\tinstall ok installed\n"]
            def run(argv):
                if argv[0] == "dpkg-query":
                    return package[0]
                return "libpython3.12.so.1.0 => /lib/x86_64-linux-gnu/libpython3.12.so.1.0 (0x123)\n"
            evidence = inventory("0.7.1", prefix=prefix, run=run)
            self.assertEqual(evidence["package_version"], "0.7.1-1")
            self.assertEqual(evidence["app_version"], "0.7.1")
            self.assertEqual(evidence["qt_version"], "6.7.3")
            for invalid in ("hub\t0.7.0\tamd64\tinstall ok installed", "hub\t0.7.1\tarm64\tinstall ok installed", "hub\t0.7.1\tamd64\tdeinstall ok config-files"):
                package[0] = invalid
                with self.assertRaises(smoke.SmokeError):
                    inventory("0.7.1", prefix=prefix, run=run)
            package[0] = "hub\t0.7.1\tamd64\tinstall ok installed"
            (prefix / "usr/bin/hub").write_text("#!/usr/bin/python3")
            with self.assertRaisesRegex(smoke.SmokeError, "ELF"):
                inventory("0.7.1", prefix=prefix, run=run)
            (prefix / "usr/bin/hub").write_bytes(b"\x7fELFunit")
            (qt / "resources/qtwebengine_resources.pak").unlink()
            with self.assertRaisesRegex(smoke.SmokeError, "resources"):
                inventory("0.7.1", prefix=prefix, run=run)


class NativeWindowTests(unittest.TestCase):
    def test_requires_fixture_pixels_on_the_real_native_screenshot(self):
        smoke = harness()
        check = getattr(smoke, "validate_native_pixels", None)
        self.assertTrue(callable(check), "native painted-page acceptance is missing")
        assert callable(check)
        self.assertEqual(check([(18, 54, 70)] * 20_000), 20_000)
        for pixels in ([(0, 0, 0)] * 40_000, [(18, 54, 70)] * 100):
            with self.assertRaisesRegex(smoke.SmokeError, "native screenshot"):
                check(pixels)

    def test_requires_owned_mapped_active_window_wholly_on_root(self):
        smoke = harness()
        native = getattr(smoke, "native_window", None)
        self.assertTrue(callable(native), "native X11 exposure check is missing")
        assert callable(native)
        listing = ["0x00120003  0 41 10 30 1180 780 ci Local Project Hub\n"]
        state = ["IsViewable"]
        active = ["0x120003"]
        x = [10]
        def run(argv):
            if argv[:2] == ["wmctrl", "-lpG"]:
                return listing[0]
            if argv[:2] == ["wmctrl", "-ia"]:
                return ""
            if argv[:2] == ["xprop", "-root"]:
                return "_NET_ACTIVE_WINDOW(WINDOW): window id # " + active[0]
            if argv[:2] == ["xprop", "-id"]:
                return "_NET_WM_PID(CARDINAL) = 41\n_NET_WM_STATE(ATOM) = \n_NET_FRAME_EXTENTS(CARDINAL) = 1, 1, 20, 1"
            if "-root" in argv:
                return "Absolute upper-left X: 0\nAbsolute upper-left Y: 0\nWidth: 1280\nHeight: 900\nMap State: IsViewable"
            return f"Absolute upper-left X: {x[0]}\nAbsolute upper-left Y: 30\nWidth: 1180\nHeight: 780\nMap State: {state[0]}"
        evidence = native(41, run=run)
        self.assertEqual(evidence["pid"], 41)
        self.assertEqual(evidence["frame"], [9, 10, 1191, 811])
        self.assertIsNone(native(42, run=run))
        state[0] = "IsUnMapped"
        self.assertIsNone(native(41, run=run))
        state[0] = "IsViewable"
        active[0] = "0x99999"
        self.assertIsNone(native(41, run=run))
        active[0] = "0x120003"
        x[0] = -100
        self.assertIsNone(native(41, run=run))


class CdpTests(unittest.TestCase):
    def test_cdp_is_bounded_read_only_and_restricted_to_own_loopback_page(self):
        smoke = harness()
        call = getattr(smoke, "cdp_call", None)
        self.assertTrue(callable(call), "bounded external CDP client is missing")
        assert callable(call)
        messages = iter([json.dumps({"method": "Page.event"}), json.dumps({"id": 1, "result": {"result": {"value": {"title": "nonce"}}}})])
        class Wire:
            def __init__(self):
                self.sent = []
            def send(self, payload):
                self.sent.append(json.loads(payload))
            def settimeout(self, value):
                self.timeout = value
            def recv(self):
                return next(messages)
        wire = Wire()
        self.assertEqual(call(wire, "Runtime.evaluate", {"expression": "document.title"}), {"result": {"value": {"title": "nonce"}}})
        self.assertEqual(wire.sent[0]["id"], 1)
        own_url = "http://127.0.0.1:12345/nonce"
        target = {"type": "page", "url": own_url, "webSocketDebuggerUrl": "ws://127.0.0.1:23456/devtools/page/own"}
        self.assertEqual(smoke.target_endpoint([target], own_url, 23456), target["webSocketDebuggerUrl"])
        self.assertIsNone(smoke.target_endpoint([dict(target, url="about:blank")], own_url, 23456))
        for endpoint in ("ws://example.org:23456/devtools/page/own", "ws://127.0.0.1:9999/devtools/page/own", "ws://127.0.0.1:23456/other"):
            with self.assertRaises(smoke.SmokeError):
                smoke.target_endpoint([dict(target, webSocketDebuggerUrl=endpoint)], own_url, 23456)
        messages = iter([json.dumps({"id": 1, "error": {"message": "renderer gone"}})])
        with self.assertRaisesRegex(smoke.SmokeError, "renderer gone"):
            call(Wire(), "Runtime.evaluate", {})


class LifecycleTests(unittest.TestCase):
    def test_cli_returns_nonzero_and_records_errors_not_green_observations(self):
        smoke = harness()
        main = getattr(smoke, "main", None)
        self.assertTrue(callable(main), "external smoke CLI is missing")
        assert callable(main)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "wrong-dom"
            with patch.object(smoke, "run_smoke", side_effect=smoke.SmokeError("DOM text: wrong")), patch("builtins.print"):
                self.assertEqual(main(["--output", str(out), "--expected-version", "0.7.1", "--expected-text", "wrong"]), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertIs(report["passed"], False)
            self.assertIn("DOM text", report["error"])
            self.assertEqual(report["expected_text"], "wrong")
            self.assertEqual(report["expected_version"], "0.7.1")

    def test_cleanup_never_reaps_a_reused_pid(self):
        smoke = harness()
        owned = {41: "900", 42: "old"}
        class App:
            pid = 41
            def poll(self):
                return 0
            def wait(self, timeout):
                return 0
        with patch.object(smoke, "refresh_owned", return_value={}), patch.object(smoke, "process_identity", return_value="reused"), patch.object(smoke.os, "waitpid") as waitpid:
            smoke.cleanup_owned(App(), owned, "/own/state")
        waitpid.assert_not_called()

    def test_cleanup_reaps_only_owned_tasks_even_after_app_crash(self):
        smoke = harness()
        cleanup = getattr(smoke, "cleanup_owned", None)
        self.assertTrue(callable(cleanup), "bounded owned cleanup is missing")
        assert callable(cleanup)
        owned = {41: "900", 42: "901"}
        live = dict(owned)
        reaped = []
        signalled = []
        class App:
            pid = 41
            def poll(self):
                return -11  # Already crashed; a surviving renderer still needs cleanup.
            def wait(self, timeout):
                reaped.append(41)
                return -11
        def refresh(owned, home):
            return dict(live)
        def send(pid, token, sig):
            signalled.append((pid, token, sig))
            live.pop(pid, None)
            return True
        def reap(pid, flags):
            reaped.append(pid)
            return (pid, 0)
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        with patch.object(smoke, "refresh_owned", side_effect=refresh), patch.object(smoke, "process_identity", side_effect=lambda pid: owned.get(pid)), patch.object(smoke, "signal_owned", side_effect=send), patch.object(smoke.os, "waitpid", side_effect=reap), patch.object(smoke.time, "monotonic", side_effect=lambda: now[0]), patch.object(smoke.time, "sleep", side_effect=sleep):
            evidence = cleanup(App(), owned, "/own/state")
        self.assertEqual(evidence["remaining"], {})
        self.assertIn("unexpected_exit", evidence, "cleanup must classify a real crash")
        self.assertTrue(evidence["unexpected_exit"], "a real crash cannot become a green cleanup")
        self.assertEqual({pid for pid, token, sig in signalled}, {41, 42})
        self.assertTrue({41, 42}.issubset(reaped))
        self.assertNotIn(99, reaped)


def test_linux_smoke_controls():
    """Adapt Linux-only unittest controls to the repository's PASS protocol."""
    if sys.platform != "linux":
        print("SKIP test_linux_smoke_controls: installed Linux observer controls")
        return
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    expected = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert expected > 0 and result.testsRun == expected and result.wasSuccessful()
    print("PASS test_linux_smoke_controls")


if __name__ == "__main__":
    test_linux_smoke_controls()
