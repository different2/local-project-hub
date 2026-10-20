"""Install a downloaded update by replacing this app's own bundle (macOS).

The user asked (2026-10-19): instead of opening the disk image and dragging
the app across, can a restart just do it? It can, because the app never has
to overwrite itself while it is running: it stages the new bundle, leaves a
small shell script behind, and quits. The script waits for this process to
disappear, moves the old bundle to the Trash, drops the new one in its
place, and reopens it.

Nothing is deleted and no step can leave the user without a working app:

  * the old bundle is *moved* to ``~/.Trash`` (a timestamped name), not
    removed;
  * the new bundle is copied to a sibling of the target first, so the final
    step is a rename rather than a long copy into a live location;
  * if the copy or the rename fails, the old bundle is put back and opened;
  * the wait for the app to exit is bounded (``timeout_s``), so a stuck
    quit cannot make the script act on a running app.

Every step is appended to ``~/Library/Logs/LocalProjectHub/update.log`` so a
failed update can be explained afterwards.

Only used on macOS; Windows keeps its MSI, which installs itself. A source
run has no bundle to replace, so ``can_self_install()`` says so and the
caller falls back to opening the disk image.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__


def bundle_path() -> Path | None:
    """The .app this process runs from, or None when running from source."""
    exe = Path(sys.executable).resolve()
    for candidate in (exe, *exe.parents):
        if candidate.suffix == ".app" and (candidate / "Contents" / "MacOS").is_dir():
            return candidate
    return None


def can_self_install(target: Path | None = None) -> tuple[bool, str]:
    """Can this copy replace itself? Returns (ok, reason-when-not)."""
    if sys.platform != "darwin":
        return False, "self-install is only used on macOS"
    target = target or bundle_path()
    if target is None:
        return False, "this is a source run, not a bundled app"
    parent = target.parent
    if not os.access(parent, os.W_OK | os.X_OK):
        return False, f"{parent} is not writable by this user"
    return True, ""


def workdir() -> Path:
    """A fresh temp directory for one update."""
    return Path(tempfile.mkdtemp(prefix="lph-update-"))


def stage_app_from_dmg(dmg: Path, work: Path) -> Path:
    """Mount ``dmg``, copy the app inside it into ``work``, unmount.

    Returns the staged .app. Raises RuntimeError with a sentence worth
    showing the user when the disk image holds no app.
    """
    dmg, work = Path(dmg), Path(work)
    mount = work / "mnt"
    mount.mkdir(parents=True, exist_ok=True)
    attached = False
    try:
        subprocess.run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-readonly",
                "-noverify",
                "-mountpoint",
                str(mount),
                str(dmg),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        attached = True
        apps = sorted(p for p in mount.iterdir() if p.suffix == ".app")
        if not apps:
            raise RuntimeError(f"{dmg.name} does not contain an app")
        staged = work / apps[0].name
        subprocess.run(["ditto", str(apps[0]), str(staged)], check=True, timeout=900)
    finally:
        if attached:
            subprocess.run(
                ["hdiutil", "detach", str(mount), "-quiet"],
                capture_output=True,
                timeout=180,
            )
    # A copy made by this process carries no quarantine, but a disk image that
    # came from a browser may; dropping it keeps the new copy launchable.
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(staged)],
        capture_output=True,
        timeout=120,
    )
    return staged


def install_script(
    staged: Path,
    target: Path,
    pid: int,
    *,
    trash_dir: Path,
    log_path: Path,
    timeout_s: float = 60,
    open_cmd: str = "/usr/bin/open",
) -> str:
    """The shell script that performs the swap. Separate so it can be tested."""
    q = shlex.quote
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    stamp = f"{stamp}-{os.getpid()}"
    backup = Path(trash_dir) / f"{target.stem} (before {__version__}) {stamp}.app"
    incomplete = Path(trash_dir) / f"{target.stem} (incomplete update) {stamp}.app"
    incoming = target.with_name(f".{target.name}.incoming-{stamp}")
    ticks = max(1, int(timeout_s * 10))

    return f"""#!/bin/sh
# Written by Local Project Hub {__version__} to install an update while the
# app is closed. Safe to delete once it has run; it logs to LOG below.
LOG={q(str(log_path))}
APP={q(str(target))}
NEW={q(str(staged))}
BACKUP={q(str(backup))}
INCOMPLETE={q(str(incomplete))}
INCOMING={q(str(incoming))}

log() {{ printf '%s %s\\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }}
mkdir -p "$(dirname "$LOG")"

log "waiting for pid {pid} to exit"
i=0
while kill -0 {pid} 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -gt {ticks} ]; then
        log "the app did not exit within {timeout_s}s; nothing was changed"
        exit 1
    fi
    sleep 0.1
done

if [ ! -d "$NEW" ]; then
    log "staged app is missing ($NEW); nothing was changed"
    exit 1
fi

log "copying the new version beside the old one"
if ! /usr/bin/ditto "$NEW" "$INCOMING"; then
    log "copy failed; moving the partial copy to the Trash and reopening the old app"
    /bin/mv "$INCOMING" "$INCOMPLETE" 2>/dev/null
    {q(open_cmd)} "$APP"
    exit 1
fi

log "moving the old version to the Trash ($BACKUP)"
if ! /bin/mv "$APP" "$BACKUP"; then
    log "could not move the old version aside; nothing was changed"
    /bin/mv "$INCOMING" "$INCOMPLETE" 2>/dev/null
    {q(open_cmd)} "$APP"
    exit 1
fi

if /bin/mv "$INCOMING" "$APP"; then
    log "installed; reopening $APP"
    {q(open_cmd)} "$APP"
    exit 0
fi

log "could not put the new version in place; restoring the old one"
/bin/mv "$BACKUP" "$APP"
/bin/mv "$INCOMING" "$INCOMPLETE" 2>/dev/null
{q(open_cmd)} "$APP"
exit 1
"""


def schedule_install(
    staged: Path,
    target: Path,
    pid: int,
    *,
    trash_dir: Path | None = None,
    log_path: Path | None = None,
    timeout_s: float = 60,
    open_cmd: str = "/usr/bin/open",
) -> Path:
    """Write the script and start it detached, so it outlives this process."""
    staged, target = Path(staged), Path(target)
    if not staged.is_dir():
        raise RuntimeError(f"nothing staged at {staged}")
    if staged.resolve() == target.resolve():
        raise RuntimeError("the staged bundle is the app that is running")
    trash_dir = Path(trash_dir) if trash_dir else Path.home() / ".Trash"
    log_path = (
        Path(log_path)
        if log_path
        else Path.home() / "Library" / "Logs" / "LocalProjectHub" / "update.log"
    )
    trash_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    script = staged.parent / "install-update.sh"
    script.write_text(
        install_script(
            staged,
            target,
            pid,
            trash_dir=trash_dir,
            log_path=log_path,
            timeout_s=timeout_s,
            open_cmd=open_cmd,
        )
    )
    script.chmod(0o755)
    # start_new_session detaches it from this process group, so quitting the
    # app does not take the installer down with it.
    subprocess.Popen(
        ["/bin/sh", str(script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    return script
