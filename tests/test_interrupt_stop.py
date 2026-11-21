"""Ctrl-C-first Stop regressions using only real, case-owned child processes."""
from __future__ import annotations

import inspect
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QCoreApplication, QEventLoop, QProcess, QTimer
from hub import store as sm
from hub.process_manager import ProjectProcess


def wait_for(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return predicate()


def cleanup(proc):
    if proc.proc is not None and proc.proc.state() != QProcess.NotRunning:
        proc._force_kill()
        assert wait_for(lambda: proc.proc.state() == QProcess.NotRunning), "owned child was not reaped"


def test_stop_delivers_one_ctrl_c_and_allows_cleanup(tmp):
    if os.name != "posix":
        return "POSIX signal semantics; Windows retains its separate stop path"
    script, events = tmp / "interrupt.py", tmp / "events.txt"
    script.write_text('''import signal, sys, time
from pathlib import Path
out = Path(sys.argv[1])
stopping = False
def record(value):
    with out.open("a") as stream:
        stream.write(value + "\\n")
        stream.flush()
def interrupted(signum, frame):
    global stopping
    record("INT")
    stopping = True
def terminated(signum, frame):
    record("TERM")
    sys.exit(88)
signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, terminated)
print("READY_FOR_STOP", flush=True)
while not stopping:
    time.sleep(0.01)
time.sleep(0.1)
record("FLUSHED")
''')
    rec = sm.validate({"name": "Graceful capture", "working_dir": str(tmp), "interpreter": sys.executable,
                       "command": " ".join(shlex.quote(str(p)) for p in (script, events))})
    proc = ProjectProcess(rec, term_grace_ms=1000)
    try:
        proc.start()
        assert wait_for(lambda: "READY_FOR_STOP" in "".join(proc.history)), list(proc.history)
        proc.stop()
        assert wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning)
        assert events.exists() and events.read_text().splitlines() == ["INT", "FLUSHED"], (
            "Stop did not act like one Ctrl-C with a cleanup grace", events.read_text() if events.exists() else "no signal")
        assert proc.proc.exitCode() == 0 and proc.state == "stopped", (proc.proc.exitCode(), proc.state)
    finally:
        cleanup(proc)


def test_stop_escalates_to_term_before_force_kill(tmp):
    if os.name != "posix":
        return "POSIX signal semantics; Windows retains its separate stop path"
    script, events = tmp / "term_fallback.py", tmp / "events.txt"
    script.write_text('''import signal, sys, time
from pathlib import Path
out = Path(sys.argv[1])
def record(value):
    with out.open("a") as stream:
        stream.write(value + "\\n")
        stream.flush()
def interrupted(signum, frame): record("INT")
def terminated(signum, frame):
    record("TERM")
    time.sleep(0.05)
    record("FLUSHED")
    sys.exit(0)
signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, terminated)
print("READY_FOR_STOP", flush=True)
while True: time.sleep(0.02)
''')
    # The real Python3.9/macOS child can oversleep its requested 50ms cleanup
    # (observed 132-177ms), racing a 180ms test-only grace before the final write.
    # Preserve signal/order/flush/exit assertions; production's 20s/5s is unchanged.
    proc = ProjectProcess(sm.validate({"name": "TERM fallback", "working_dir": str(tmp),
                          "interpreter": sys.executable,
                          "command": " ".join(shlex.quote(str(p)) for p in (script, events))}), term_grace_ms=1000)
    try:
        proc.start()
        assert wait_for(lambda: "READY_FOR_STOP" in "".join(proc.history))
        proc.stop()
        assert wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning)
        assert events.read_text().splitlines() == ["INT", "TERM", "FLUSHED"], (
            "Stop skipped polite TERM escalation before kill", events.read_text(), list(proc.history))
        assert proc.proc.exitCode() == 0
    finally:
        cleanup(proc)


def test_group_members_receive_one_interrupt_not_group_plus_individual(tmp):
    if os.name != "posix":
        return "POSIX process groups"
    import signal
    from unittest.mock import patch
    from hub import process_manager as pm
    proc = ProjectProcess(sm.validate({"name": "Signal ownership", "command": "python3 -c pass"}))
    tree = {10001: "root", 10002: "same-group", 10003: "escaped-group"}
    sent = []
    with patch.object(proc, "_group_verified", return_value=True), \
         patch.object(pm.urldetect, "process_identity", side_effect=lambda pid: tree.get(pid)), \
         patch.object(pm.os, "getpgid", side_effect=lambda pid: 10003 if pid == 10003 else 10001), \
         patch.object(pm.os, "killpg", side_effect=lambda pid, sig: sent.append(("group", pid, sig))), \
         patch.object(pm.os, "kill", side_effect=lambda pid, sig: sent.append(("pid", pid, sig))):
        proc._signal_owned_tree(tree, 10001, signal.SIGINT)
    assert sent == [("group", 10001, signal.SIGINT), ("pid", 10003, signal.SIGINT)], (
        "group members received duplicate Ctrl-C signals", sent)


if __name__ == "__main__":
    app = QCoreApplication.instance() or QCoreApplication([])
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--test=")), None)
    names = sorted(name for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn))
    if only:
        if only not in names:
            raise SystemExit("unknown test: " + only)
        names = [only]
    failed = 0
    for name in names:
        try:
            with tempfile.TemporaryDirectory(prefix="hub-stop-") as directory:
                reason = globals()[name](Path(directory))
            print(("SKIP " + name + ": " + reason) if reason else "PASS " + name, flush=True)
        except Exception as exc:
            failed += 1
            print("FAIL " + name + ": " + repr(exc), flush=True)
    raise SystemExit(1 if failed else 0)
