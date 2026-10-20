"""Guard tests for installing an update by restarting the app (macOS).

The user asked (2026-10-19) why finishing an update needs a drag to
Applications when a restart could do it. `hub.selfupdate` answers that with a
small detached script: it waits for this process to exit, moves the old
bundle to the Trash, drops the new one in place, and reopens it.

On macOS these tests run that script for real against throwaway bundles,
because the failure that would matter -- an update that leaves the user
without a working app -- cannot be caught by asserting on the script's text:

  * a successful swap keeps the old bundle in the Trash (never deleted);
  * a missing staged bundle changes nothing;
  * an app that refuses to exit is waited for only so long;
  * a copy that cannot be made leaves the old bundle exactly where it was.

Off macOS (CI runs on Windows) the same tests check the parts that are not
platform-bound: the module refuses loudly instead of half-working, and the
script still carries every guard, so a later edit cannot quietly drop one.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hub import selfupdate  # noqa: E402

MAC = sys.platform == "darwin"


@contextlib.contextmanager
def _sandbox(label: str):
    """A throwaway directory; the suite runner passes no fixtures."""
    root = Path(tempfile.mkdtemp(prefix=f"lph-selfupdate-{label}-"))
    try:
        yield root
    finally:
        for p in root.rglob("*"):
            try:
                if p.is_dir():
                    p.chmod(0o755)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)


def _bundle(parent: Path, name: str, marker: str) -> Path:
    app = parent / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / name).write_text("#!/bin/sh\n", encoding="utf-8")
    (app / marker).write_text(marker, encoding="utf-8")
    return app


def _wait_for(pred, timeout_s: float = 15.0) -> bool:
    end = time.time() + timeout_s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _run_script_text(script: str, work: Path) -> int:
    """Write a script body and run it, the way schedule_install would."""
    path = work / "manual.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return subprocess.run(
        ["/bin/sh", str(path)], capture_output=True, timeout=60
    ).returncode


def _guards_present(script: str, *phrases: str) -> None:
    """The off-macOS half of the script tests: every guard is still there."""
    for phrase in phrases:
        assert phrase in script, f"{phrase!r} is missing from the install script"


def test_a_source_run_has_no_bundle_to_replace() -> None:
    """`sys.executable` outside a .app means: fall back to the disk image."""
    real = sys.executable
    try:
        sys.executable = "/usr/bin/python3"
        assert selfupdate.bundle_path() is None
        ok, why = selfupdate.can_self_install()
        assert ok is False
        if MAC:
            assert "source run" in why, why
        else:
            assert "macOS" in why, why
    finally:
        sys.executable = real


def test_a_bundle_whose_folder_is_not_writable_cannot_be_replaced() -> None:
    with _sandbox("readonly") as root:
        apps = root / "Applications"
        apps.mkdir()
        target = _bundle(apps, "Fake Hub", "old.txt")
        apps.chmod(0o555)
        try:
            ok, why = selfupdate.can_self_install(target)
        finally:
            apps.chmod(0o755)
        assert ok is False
        if MAC:
            assert "not writable" in why, why


def test_the_script_waits_for_the_app_to_exit() -> None:
    """A running app must never have its bundle swapped underneath it."""
    with _sandbox("wait") as root:
        target = _bundle(root / "Apps", "Fake Hub", "old.txt")
        staged = _bundle(root / "staged", "Fake Hub", "new.txt")
        log = root / "update.log"

        script = selfupdate.install_script(
            staged,
            target,
            os.getpid(),  # this test process is very much alive
            trash_dir=root / "Trash",
            log_path=log,
            timeout_s=0.3,
            open_cmd="true",
        )
        if not MAC:
            _guards_present(script, "kill -0", "did not exit", "sleep 0.1")
            return

        selfupdate.schedule_install(
            staged,
            target,
            os.getpid(),
            trash_dir=root / "Trash",
            log_path=log,
            timeout_s=0.3,
            open_cmd="true",
        )

        assert _wait_for(lambda: "did not exit" in _log(log))
        assert (target / "old.txt").exists(), "the old bundle must be untouched"
        assert not (target / "new.txt").exists()


def test_the_script_swaps_the_bundle_and_keeps_the_old_one_in_the_trash() -> None:
    with _sandbox("swap") as root:
        apps = root / "Apps"
        apps.mkdir()
        target = _bundle(apps, "Fake Hub", "old.txt")
        staged = _bundle(root / "staged", "Fake Hub", "new.txt")
        trash = root / "Trash"
        log = root / "update.log"

        # This test is about the swap, not about the wait (which
        # test_the_script_waits_for_the_app_to_exit covers): a pid that
        # cannot exist makes the wait end at once, with no pid-reuse race.
        script = selfupdate.install_script(
            staged,
            target,
            999999,
            trash_dir=trash,
            log_path=log,
            open_cmd="true",
        )
        if not MAC:
            _guards_present(
                script, "ditto", "/bin/mv", "(before ", "installed; reopening"
            )
            return

        selfupdate.schedule_install(
            staged,
            target,
            999999,
            trash_dir=trash,
            log_path=log,
            open_cmd="true",
        )
        assert _wait_for(
            lambda: (target / "new.txt").exists()
        ), f"the swap never happened; log:\n{_log(log)}"

        assert (target / "Contents" / "MacOS" / "Fake Hub").exists(), _log(log)
        assert not (target / "old.txt").exists(), _log(log)

        kept = [
            p for p in trash.iterdir() if p.name.startswith("Fake Hub (before ")
        ]
        assert len(kept) == 1, f"expected one backup in the Trash, found {kept}"
        assert (kept[0] / "old.txt").read_text(encoding="utf-8") == "old.txt"
        assert "installed; reopening" in _log(log), _log(log)


def test_a_missing_staged_bundle_changes_nothing() -> None:
    with _sandbox("missing") as root:
        target = _bundle(root / "Apps", "Fake Hub", "old.txt")
        log = root / "update.log"

        try:
            selfupdate.schedule_install(
                root / "staged" / "Nope.app",
                target,
                os.getpid(),
                trash_dir=root / "Trash",
                log_path=log,
                open_cmd="true",
            )
        except RuntimeError as e:
            # The Python-side guard is the first line of defence, on every
            # platform: the refusing happens before any script is written.
            assert "nothing staged" in str(e), e
        else:  # pragma: no cover - only if the guard is removed
            assert _wait_for(lambda: "staged app is missing" in _log(log))

        assert (target / "old.txt").exists()


def test_a_copy_that_cannot_be_made_leaves_the_old_bundle_in_place() -> None:
    """The dangerous case: the new bundle cannot be put beside the old one."""
    with _sandbox("copyfail") as root:
        apps = root / "Apps"
        apps.mkdir()
        target = _bundle(apps, "Fake Hub", "old.txt")
        staged = _bundle(root / "staged", "Fake Hub", "new.txt")
        log = root / "update.log"

        script = selfupdate.install_script(
            staged,
            target,
            999999,  # no such process: the wait loop exits at once
            trash_dir=root / "Trash",
            log_path=log,
            open_cmd="true",
        )
        if not MAC:
            _guards_present(script, "copy failed", "moving the old version")
            return

        apps.chmod(0o555)  # the copy target's folder refuses new entries
        try:
            rc = _run_script_text(script, root)
        finally:
            apps.chmod(0o755)

        assert rc == 1
        assert (target / "old.txt").exists(), "the old app must survive a failed copy"
        assert not (target / "new.txt").exists()
        assert "copy failed" in _log(log)


def test_the_dialog_offers_a_restart_and_not_a_drag() -> None:
    """What the user sees: one button, and it means 'restart and install'."""
    from PySide6.QtWidgets import QApplication

    from hub.update_dialog import UpdateDialog

    app = QApplication.instance() or QApplication([])
    dlg = UpdateDialog()
    try:
        fired = []
        dlg.install_now.connect(lambda: fired.append(True))
        dlg.show_ready_to_install("0.6.0")
        assert "Restart" in dlg.primary.text()
        assert "ready to install" in dlg.headline.text()
        assert "drag" not in dlg.primary.text()
        dlg.primary.click()
        app.processEvents()
        assert fired == [True]
    finally:
        dlg.close()


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
                fails += 1
                print(f"ERROR {_name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
