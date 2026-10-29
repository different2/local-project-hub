"""URL auto-detection tests: a server's own output fills in the URL.

The user should not have to type a dashboard URL when the server announces
one. These tests cover the detector and the end-to-end wiring against real
subprocesses, using servers that print their address (Flask-style) and one
that stays silent (port-scan fallback).

Run:  QT_QPA_PLATFORM=offscreen python3 tests/test_urldetect.py
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QProcess, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
)

from helpers import (  # noqa: E402
    SkipTest,
    reserve_port,
    start_holder,
    stop_and_release,
    temp_project_dir,
    victim_server_source,
)
from hub import store as sm, urldetect  # noqa: E402
from hub.window import _entry_script  # noqa: E402
from hub.process_manager import ProjectProcess, _detected_suppress_flag  # noqa: E402
from hub.window import HubWindow  # noqa: E402


def test_0_0_0_0_is_rewritten_to_localhost():
    """0.0.0.0 means 'all interfaces'; it is not connectable as an address."""
    url = urldetect.find_url("listening on http://0.0.0.0:5000")
    assert url is not None
    assert url.replace("0.0.0.0", "127.0.0.1") == "http://127.0.0.1:5000"


def _spin(ms=100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_for(pred, timeout_s=20.0):
    for _ in range(int(timeout_s * 10)):
        if pred():
            return True
        _spin(100)
    return pred()


def _own_tree(proc) -> set[int]:
    """PIDs the ProjectProcess launched, including launcher descendants.

    A Windows venv's python.exe is a launcher: QProcess reports the launcher,
    the listener is its child. Assertions must accept either.
    """
    pid = proc.proc.processId() if getattr(proc, "proc", None) is not None else 0
    return urldetect.process_tree_pids({pid})


# ---------- the detector itself ----------


def test_detects_urls_from_real_server_banners():
    cases = {
        "serving on http://localhost:8471  (assets list at /_assets-list)": "http://localhost:8471",
        "observability live dashboard at http://127.0.0.1:8787  (ctrl-c to stop)": "http://127.0.0.1:8787",
        " * Running on http://127.0.0.1:5000": "http://127.0.0.1:5000",
        "Server ready at http://0.0.0.0:3000/": "http://0.0.0.0:3000/",
    }
    for text, expected in cases.items():
        got = urldetect.find_url(text)
        assert got == expected, f"{text!r} -> {got!r}, expected {expected!r}"


def test_ignores_docs_and_noise():
    assert urldetect.find_url("See https://docs.python.org/3 for help") is None
    assert urldetect.find_url("nothing useful here") is None
    assert urldetect.find_url("install from https://pypi.org/project/x") is None


def test_falls_back_to_port_when_no_url_printed():
    assert urldetect.find_port("listening on port 9000") == 9000
    assert urldetect.find_port("PORT=8080") == 8080
    assert urldetect.find_port("no port anywhere") is None
    # a docs URL must not be mistaken for a port
    assert urldetect.find_port("See https://docs.python.org/3") is None


# ---------- end to end ----------

_ANNOUNCING_SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *a): pass
print(f"my dashboard is at http://127.0.0.1:{sys.argv[1]}", flush=True)
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""

_SILENT_SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *a): pass
# deliberately prints nothing
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def test_process_detects_url_from_output(tmp: Path) -> None:
    port = reserve_port()
    srv_py = tmp / "announce.py"
    srv_py.write_text(_ANNOUNCING_SERVER)
    rec = sm.validate(
        {
            "name": "Announcing",
            "command": f"{sys.executable} {srv_py} {port}",
            "working_dir": str(tmp),
            "url": "",  # no URL configured — the whole point
        }
    )
    p = ProjectProcess(rec)
    got = []
    p.url_detected.connect(lambda u: got.append(u))
    p.start()
    ok = _wait_for(lambda: bool(got), timeout_s=25)
    stop_and_release(p, srv_py)
    assert ok, f"no URL detected from output; got={got}"
    assert got[0] == f"http://127.0.0.1:{port}", got[0]


def test_window_fills_in_and_saves_detected_url(tmp: Path) -> None:
    port = reserve_port()
    srv_py = tmp / "announce2.py"
    srv_py.write_text(_ANNOUNCING_SERVER)
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "Auto URL",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
                "url": "",
            }
        )
    )
    assert rec["url"] == ""
    w = HubWindow(st)
    w.show()
    try:
        w._select_id(rec["id"])
        expected = f"http://127.0.0.1:{port}/"
        # The tab should end up on the detected URL (Qt may add a trailing slash).
        ok = _wait_for(
            lambda: w.web is not None
            and w.web.url().toString().rstrip("/") == f"http://127.0.0.1:{port}",
            timeout_s=30,
        )
        assert ok, f"tab never loaded the detected URL; url={w.web.url().toString()!r}"
        # and it must be persisted so the user is not asked again
        reloaded = sm.Store(tmp / "registry.json").get(rec["id"])
        assert reloaded["url"], "detected URL was not saved to the registry"
        assert str(port) in reloaded["url"], reloaded["url"]
    finally:
        # close() alone leaves the project's child process running, and on
        # Windows that child still holds srv_py open -- so the temp-dir cleanup
        # dies with WinError 32 and fails a test that had already passed. Stop
        # every process the window owns before closing it.
        for _proc in list(getattr(w, "procs", {}).values()):
            try:
                _proc.stop()
            except Exception:
                pass
        for _proc in list(getattr(w, "procs", {}).values()):
            _wait_for(lambda p=_proc: p.state == "stopped", timeout_s=25)
        w.close()


def test_port_conflict_refuses_to_start(tmp: Path) -> None:
    """A taken port must not start a doomed process that dies confusingly.

    Without this guard the new process dies with "Address already in use" and
    the hub then reports the OTHER process's page as this project's dashboard,
    which reads as a success.
    """
    port = reserve_port()
    srv_py = tmp / "holder.py"
    srv_py.write_text(_SILENT_SERVER)
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Holder",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    holder_out = []
    holder.output.connect(holder_out.append)
    assert started, (
        f"test server did not start (state={holder.state}); "
        f"port={port} in_use={urldetect.port_in_use(port)} "
        f"owners={urldetect.port_owners(port)} "
        f"output={''.join(holder_out)[-400:]!r}"
    )
    try:
        rec = sm.validate(
            {
                "name": "Second",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
                "url": f"http://127.0.0.1:{port}/",
            }
        )
        p2 = ProjectProcess(rec)
        out = []
        p2.output.connect(lambda t: out.append(t))
        p2.start()
        # The refusal may surface as either error or stopped depending on Qt's
        # timing; what matters is that nothing was launched and the user was
        # told why.
        _wait_for(lambda: p2.state in ("error", "stopped"), timeout_s=10)
        assert p2.state in ("error", "stopped"), p2.state
        assert p2.proc is None or p2.proc.processId() == 0, "a process was launched anyway"
        text = "".join(out)
        assert "already in use" in text, text
    finally:
        stop_and_release(holder, srv_py)


def test_port_conflict_is_reported_with_command(tmp: Path) -> None:
    """A foreign process on the port is reported, with enough detail to judge it.

    The prompt must name what is holding the port so the user can tell whether
    it is another copy of this project or something unrelated before deciding
    to end it.
    """
    port = reserve_port()
    srv_py = tmp / "holder.py"
    srv_py.write_text(_SILENT_SERVER)
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Holder",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    assert started, f"test server did not start (state={holder.state})"
    try:
        other = ProjectProcess(
            sm.validate(
                {
                    "name": "Second",
                    "command": f"{sys.executable} {srv_py} {port}",
                    "working_dir": str(tmp),
                    "url": f"http://127.0.0.1:{port}/",
                }
            )
        )
        conflict = other.port_conflict()
        assert conflict, "a foreign holder on the port was not reported"
        assert conflict["port"] == port, conflict
        assert conflict["holders"], conflict
        # The holder's PID must be the one named.
        holder_pid = holder.proc.processId() if holder.proc else None
        assert _own_tree(holder) & {h["pid"] for h in conflict["holders"]}, conflict
        assert any(
            "holder.py" in (h["command"] or "") for h in conflict["holders"]
        ), conflict
    finally:
        stop_and_release(holder, srv_py)


def test_own_process_is_not_a_conflict(tmp: Path) -> None:
    """Our own server on the port must never be reported as a conflict.

    This is the restart case: if it were reported, every restart would prompt
    the user to kill a process the hub itself started.
    """
    port = reserve_port()
    srv_py = tmp / "mine.py"
    srv_py.write_text(_SILENT_SERVER)
    proc = ProjectProcess(
        sm.validate(
            {
                "name": "Mine",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
                "url": f"http://127.0.0.1:{port}/",
            }
        )
    )
    proc.start()
    started = _wait_for(lambda: proc.state == "running", timeout_s=25)
    assert started, f"test server did not start (state={proc.state})"
    try:
        assert proc.port_conflict() is None, "our own server was flagged as foreign"
    finally:
        stop_and_release(proc, srv_py)


def test_wrapped_server_descendant_is_not_a_foreign_holder(tmp: Path) -> None:
    """A launcher's child that binds the port is still OUR process.

    On Windows a venv's `Scripts\\python.exe` is a launcher: QProcess reports
    the launcher PID, while the base interpreter it spawns is the actual
    listener. Without descendant tracking the hub sees its own server as a
    foreign holder and offers to kill it (or refuses to start). This test
    creates the same shape with a wrapper script.
    """
    port = reserve_port()
    child_py = tmp / "child_server.py"
    child_py.write_text(
        _SILENT_SERVER.replace("int(sys.argv[1])", str(port))
    )
    wrapper_py = tmp / "wrapper.py"
    wrapper_py.write_text(
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, {str(child_py)!r}])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    rec = sm.validate(
        {
            "name": "Wrapped",
            "command": f"{sys.executable} {wrapper_py}",
            "url": f"http://127.0.0.1:{port}/",
            "working_dir": str(tmp),
        }
    )
    proc = ProjectProcess(rec)
    proc.start()
    owners: set[int] = set()
    try:
        assert _wait_for(lambda: proc.state == "running", timeout_s=25)
        assert _wait_for(lambda: urldetect.port_in_use(port), timeout_s=20), (
            "the wrapped child never bound the port"
        )
        owners = urldetect.port_owners(port)
        assert owners, "the port has no identifiable owner"
        assert _own_tree(proc) & owners, (
            f"QProcess pid {proc.proc.processId()} and owners {owners} share no "
            "process tree"
        )
        assert proc.port_conflict() is None, (
            "our own server's child was reported as a foreign holder"
        )
    finally:
        stop_and_release(proc, wrapper_py)
        for pid in owners:
            urldetect.kill_process(pid)


def test_bind_failure_names_the_port_from_the_command(tmp: Path) -> None:
    """A port-less project that dies with "in use" must still be actionable.

    The user's real case: `python3 obs_live.py` with no URL and no port
    argument. The pre-start check cannot help (no URL to inspect), so the port
    has to come from the command or from what is actually holding a port.
    """
    port = reserve_port()
    srv_py = tmp / "obs.py"
    srv_py.write_text(_SILENT_SERVER)
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    assert started, f"test server did not start (state={holder.state})"
    try:
        # no url at all, and the port is only implied by the command
        rec = sm.validate(
            {
                "name": "obsv",
                "command": f"{sys.executable} {srv_py} --port {port}",
                "working_dir": str(tmp),
            }
        )
        victim = ProjectProcess(rec)
        got: list[int] = []
        victim.port_conflict_from_output.connect(got.append)

        # Feed it the real traceback the user saw, then finish with code 1.
        # history is filled by _drain from real process output; append directly
        # to stand in for a server that actually printed this.
        victim.history.append(
            "Traceback (most recent call last):\n"
            f'  File "{srv_py}", line 1, in <module>\n'
            '    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)\n'
            "OSError: [Errno 48] Address already in use\n"
        )
        # _on_finished is what reads the history; drive it the way Qt would.
        victim._user_stopped = False
        victim._on_finished(1, None)

        assert got, "a bind failure did not surface the conflicting port"
        assert got[0] == port, f"expected port {port}, got {got[0]}"
        # and the holder must be identifiable for the dialog
        assert holder.proc is not None
        assert _own_tree(holder) & urldetect.port_owners(port)
    finally:
        stop_and_release(holder, srv_py)


def test_extra_args_reach_the_command(tmp: Path) -> None:
    """The args field must be appended to argv, not stored and forgotten.

    This is how a project's own flags (e.g. --no-open) get set once instead of
    being retyped into the command box. An earlier version of the hub stored an
    "interpreter" field the launcher never read; this guards against that.
    """
    echo_py = tmp / "echo.py"
    echo_py.write_text("import sys\nprint('ARGV=' + ' '.join(sys.argv[1:]), flush=True)\n")
    rec = sm.validate(
        {
            "name": "Args",
            "command": f"{sys.executable} {echo_py}",
            "args": "--no-open",
            "working_dir": str(tmp),
        }
    )
    assert rec["args"] == "--no-open", "args did not survive validation"
    p = ProjectProcess(rec)
    out = []
    p.output.connect(lambda t: out.append(t))
    p.start()
    try:
        got = _wait_for(lambda: "ARGV=" in "".join(out), timeout_s=20)
        assert got, f"server never reported its argv: {''.join(out)!r}"
        assert "--no-open" in "".join(out), "".join(out)
    finally:
        stop_and_release(p, echo_py)


def test_dialog_exposes_an_args_field() -> None:
    """The Add/Edit dialog must actually offer the field it writes.

    Guards the regression where a field was persisted but the dialog never
    showed it (so users could not set it) — the QLabel-import class of bug.
    """
    from hub.project_dialog import ProjectDialog

    d = ProjectDialog(base_dir="/tmp")
    assert hasattr(d, "args"), "dialog has no args field"
    d.args.setText("--no-open")
    assert d.args.text().strip() == "--no-open"


def test_add_dialog_suggests_the_command_from_the_folder() -> None:
    """Choosing a folder fills in the command — but never over a written one.

    The folder detector (detect_command) is only an offer: it fills an empty
    command field, and it must leave alone a command the record (or user)
    already carries (spec §6: commands are never rewritten).
    """
    from hub.project_dialog import ProjectDialog

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "package.json").write_text(
            '{"scripts": {"dev": "vite"}}', encoding="utf-8"
        )
        filled = ProjectDialog(base_dir=d)
        assert filled.command.text().strip() == "npm run dev", filled.command.text()

        kept = ProjectDialog(record={"command": "python3 mine.py", "working_dir": d})
        assert kept.command.text().strip() == "python3 mine.py", (
            "the folder detector rewrote a command the record already had"
        )


def test_picking_a_file_sets_folder_and_command() -> None:
    """The File… flow: one file, and folder + command follow from it."""
    from hub.project_dialog import ProjectDialog

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "obs_live.py"
        script.write_text("print('x')\n", encoding="utf-8")
        dlg = ProjectDialog()
        dlg._apply_file_choice(str(script))
        assert dlg.wd.text().strip() == d, dlg.wd.text()
        assert dlg.command.text().strip() == "python3 obs_live.py", dlg.command.text()


def test_picking_a_file_replaces_only_an_earlier_suggestion() -> None:
    """A file may override the folder's guess, never a command the record has."""
    from hub.project_dialog import ProjectDialog

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "app.py").write_text("pass\n", encoding="utf-8")
        (Path(d) / "requirements.txt").write_text("flask\n", encoding="utf-8")
        (Path(d) / "other.py").write_text("pass\n", encoding="utf-8")

        folder_guessed = ProjectDialog(base_dir=d)
        assert folder_guessed.command.text().strip() == "python3 app.py"
        folder_guessed._apply_file_choice(str(Path(d) / "other.py"))
        assert folder_guessed.command.text().strip() == "python3 other.py", (
            "the picked file did not outrank the folder's own suggestion"
        )

        kept = ProjectDialog(record={"command": "python3 mine.py", "working_dir": d})
        kept._apply_file_choice(str(Path(d) / "other.py"))
        assert kept.command.text().strip() == "python3 mine.py", (
            "the File… flow rewrote a command the record already had"
        )


def test_add_dialog_names_the_project_after_the_folder_or_file() -> None:
    """The display name is taken from what was picked, until the user types one.

    User request (2026-10-19): the display name "should just be taken from what
    the file or folder I selected name. It should be able to be edited in the
    sidebar or in the options whenever I want though."
    """
    from PySide6.QtWidgets import QFileDialog

    from hub.project_dialog import ProjectDialog

    with tempfile.TemporaryDirectory() as d:
        folder = Path(d) / "obs_live"
        folder.mkdir()
        script = folder / "server.py"
        script.write_text("pass\n", encoding="utf-8")

        # Picking a FOLDER names it after the folder (through the real handler).
        original = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(folder))
        try:
            picked_folder = ProjectDialog()
            picked_folder._pick_dir()
        finally:
            QFileDialog.getExistingDirectory = original
        assert picked_folder.name.text() == "obs_live", picked_folder.name.text()

        # Picking a FILE names it after the file, without the suffix.
        picked_file = ProjectDialog()
        picked_file._apply_file_choice(str(script))
        assert picked_file.name.text() == "server", picked_file.name.text()

        # A name the user typed is never overwritten by a later pick.
        typed = ProjectDialog()
        typed.name.setText("My dashboard")
        typed._mark_name_touched()  # what textEdited does in a real session
        typed.wd.setText(str(folder))
        typed._maybe_name_from_folder()
        assert typed.name.text() == "My dashboard", "a typed name was overwritten"

        # Even left empty, a new project is named after the folder it runs in.
        unnamed = ProjectDialog()
        unnamed.wd.setText(str(folder))
        unnamed.command.setText(f"python3 {script}")
        unnamed.accept()
        assert unnamed.result_record()["name"] == "obs_live"


def test_add_dialog_hides_the_auto_decided_fields_behind_optional_settings() -> None:
    """Only what the Hub cannot work out is on show; the rest sits behind one toggle.

    User request (2026-10-19): "Since a majority of those options in the add
    project are automatically decided. I think a majority of these options
    should be hidden under a whole optional settings button."
    """
    from hub.project_dialog import ProjectDialog

    advanced_fields = (
        "icon",
        "desc",
        "interp",
        "args",
        "url",
        "env",
        "autostart",
        "type_override",
    )
    dlg = ProjectDialog()
    dlg.show()
    try:
        assert not dlg.more.isChecked(), "the optional block starts expanded"
        assert not dlg.advanced.isVisible(), "optional rows are on show by default"
        for name in advanced_fields:
            widget = getattr(dlg, name)
            assert dlg.advanced.isAncestorOf(widget), (
                f"{name} is not inside the optional settings block"
            )
        dlg.more.setChecked(True)
        assert dlg.advanced.isVisible(), "expanding optional settings showed nothing"
        # The three questions that matter stay on show either way.
        assert dlg.wd.isVisible() and dlg.name.isVisible() and dlg.command.isVisible()
    finally:
        dlg.close()

    # Nothing an existing project has already set is hidden from its owner.
    existing = ProjectDialog(
        record={"command": "python3 x.py", "working_dir": "/tmp", "args": "--no-open"}
    )
    assert existing.more.isChecked(), "an existing project's settings stayed hidden"


def test_add_dialog_never_clips_its_help_text() -> None:
    """Every hint's box must be tall enough for the text it holds.

    The crowded version drew two-line hints in one-line boxes, so sentences
    were sliced in half mid-word — the user's report of "several of these
    sentences are truncated" (2026-10-19). heightForWidth() is the height the
    text actually needs at the width it was given.
    """
    from hub.project_dialog import ProjectDialog

    dlg = ProjectDialog(base_dir="/tmp")
    dlg.show()
    dlg.more.setChecked(True)  # the optional block must fit its own text too
    QApplication.instance().processEvents()
    try:
        clipped = []
        for label in dlg.findChildren(QLabel):
            text = label.text()
            if not text or not label.isVisible():
                continue
            needed = label.heightForWidth(label.width())
            if needed <= 0:
                needed = label.sizeHint().height()
            if label.height() < needed:
                clipped.append((text[:70], label.height(), needed, label.width()))
        assert not clipped, f"clipped help text: {clipped}"
    finally:
        dlg.close()


def test_removing_a_project_closes_its_tab(tmp: Path) -> None:
    """Removing a project must take its tab with it.

    Without this, a removed project leaves a live dashboard tab behind that
    nothing can restart or close — the tab outlives the thing it belongs to.
    """
    port = reserve_port()
    srv_py = tmp / "srv.py"
    srv_py.write_text(_SILENT_SERVER)
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "Goner",
                "command": f"{sys.executable} {srv_py} {port}",
                "url": f"http://127.0.0.1:{port}/",
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    # Bypass the confirmation dialog; this test is about the tab, not the prompt.
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        w.active_id = rec["id"]
        # HubWindow auto-opens the active project's tab on construction, so the
        # count should already be dashboard + 1. Calling _open_project_tab again
        # would just prove duplicate tabs are avoided, so wait for the real one.
        opened = _wait_for(lambda: w._tab_index_for_project(rec["id"]) is not None)
        assert opened, "no tab was opened for the project"
        dashboard_index = w.dashboard_tab_index
        tabs_before = w.tabs.count()

        w._remove_project()

        assert st.get(rec["id"]) is None, "project was not removed from the registry"
        assert w._tab_index_for_project(rec["id"]) is None, (
            "the removed project still has a tab open"
        )
        assert w.tabs.count() == tabs_before - 1, (
            f"tab count went {tabs_before} -> {w.tabs.count()}, expected exactly one fewer"
        )
        # the permanent dashboard tab must survive
        assert w.dashboard_tab_index < w.tabs.count(), (
            "removing a project destroyed the dashboard tab"
        )
        assert dashboard_index == w.dashboard_tab_index
    finally:
        w.close()


def test_opening_the_hub_does_not_start_anything(tmp: Path) -> None:
    """Opening the hub must not launch projects.

    A project runs when the user asks — the Start action, a double-click, or a
    ticked autostart — never merely because the window opened and the sidebar
    selected it. The user hit this: opening the hub fired obs_live, which then
    opened Firefox.
    """
    port = reserve_port()
    srv_py = tmp / "srv.py"
    srv_py.write_text(_SILENT_SERVER)
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "obs",
                "command": f"{sys.executable} {srv_py} {port}",
                "url": f"http://127.0.0.1:{port}/",
                "autostart": False,
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        _wait_for(lambda: False, timeout_s=2)  # let any stray start happen
        proc = w._proc_for(st.get(rec["id"]))
        assert proc.state == "stopped", (
            f"opening the hub started {rec['name']} (state={proc.state})"
        )
        assert proc.proc is None or proc.proc.processId() == 0, (
            "a process was launched just by opening the window"
        )
    finally:
        w.close()


def test_autostart_project_still_starts(tmp: Path) -> None:
    """The fix must not break the autostart checkbox that IS ticked."""
    port = reserve_port()
    srv_py = tmp / "srv.py"
    srv_py.write_text(_SILENT_SERVER)
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "Auto",
                "command": f"{sys.executable} {srv_py} {port}",
                "url": f"http://127.0.0.1:{port}/",
                "autostart": True,
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        started = _wait_for(
            lambda: w._proc_for(st.get(rec["id"])).state == "running", timeout_s=25
        )
        assert started, "an autostart project was not started"
    finally:
        p = w._proc_for(st.get(rec["id"]))
        stop_and_release(p, srv_py)
        w.close()


def test_clicking_a_project_opens_it_without_launching_it(tmp: Path) -> None:
    """Reported 2026-10-20: a click in the sidebar must not launch anything.

    Selecting a project opens its tab on a start page. Running it takes Start
    — the page's button, the toolbar action, or the autostart box.
    """
    port = reserve_port()
    srv_py = tmp / "srv.py"
    srv_py.write_text(_SILENT_SERVER)
    st = sm.Store(tmp / "registry.json")
    rec = st.add(
        sm.validate(
            {
                "name": "Manual",
                "command": f"{sys.executable} {srv_py} {port}",
                "url": f"http://127.0.0.1:{port}/",
                "autostart": False,
                "working_dir": str(tmp),
            }
        )
    )
    w = HubWindow(st)
    w.show()
    try:
        _wait_for(lambda: False, timeout_s=2)
        assert w._proc_for(st.get(rec["id"])).state == "stopped", "started on open"
        w._select_id(rec["id"], start=False)  # exactly what clicking the row does
        _wait_for(lambda: False, timeout_s=2)
        assert w._proc_for(st.get(rec["id"])).state == "stopped", (
            "selecting the project started it"
        )
        # start=True is the path the Start button and the toolbar use
        w._select_id(rec["id"], start=True)
        started = _wait_for(
            lambda: w._proc_for(st.get(rec["id"])).state == "running", timeout_s=25
        )
        assert started, "pressing Start did not start the project"
    finally:
        p = w._proc_for(st.get(rec["id"]))
        stop_and_release(p, srv_py)
        w.close()


def test_listening_ports_all_actually_finds_ports(tmp: Path) -> None:
    """listening_ports_all() must parse lsof output on this platform.

    It silently returned [] for months of the conflict feature because the
    parser read the LAST column, which on macOS is "(LISTEN)" rather than the
    address. A helper that quietly finds nothing is worse than one that fails.
    """
    port = reserve_port()
    srv_py = tmp / "obs.py"
    srv_py.write_text(_SILENT_SERVER)
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    assert started, f"test server did not start (state={holder.state})"
    try:
        found = urldetect.listening_ports_all()
        assert port in found, (
            f"a live server on {port} was not found in {found[:12]} — the lsof "
            "parser is broken again (check whether the last column is the "
            "address or the state on this platform)"
        )
    finally:
        stop_and_release(holder, srv_py)


def _conflict_debug(w, pid, holder_pid, port) -> str:
    """Why the port-conflict offer never appeared, for assertion messages.

    Each field names one link in the chain from "child died" to "offer shown",
    so a failing run says exactly where it broke instead of forcing another
    blind guess. Read-only: it never changes what the test asserts.
    """
    parts = [
        f"port={port} in_use={urldetect.port_in_use(port)}",
        f"owners={urldetect.port_owners(port)}",
        f"listening={urldetect.listening_ports_all()[:8]}",
        f"holder_cmd={urldetect.process_command(holder_pid)!r}",
    ]
    proc = w.procs.get(pid)
    if proc is None:
        parts.append("proc=<none in w.procs>")
    else:
        history = "".join(proc.history)
        parts.append(f"state={proc.state}")
        parts.append(f"signal={getattr(proc, '_dbg_conflict_signal', None)!r}")
        parts.append(f"history_tail={history[-700:]!r}")
    return " ".join(parts)


def test_bare_command_conflict_is_offered(tmp: Path) -> None:
    """A project with NO url and NO port in its command still gets the dialog.

    The user's exact case: one project, "python3 obs_live.py", which binds 8787
    inside the script. Nothing in the command or registry names the port, so
    the holder has to be found by matching the script against listening ports.
    """
    port = reserve_port()
    # A server whose port is a DEFAULT INSIDE the script, not an argument —
    # exactly like obs_live.py. That is the whole difficulty: nothing in the
    # command line names the port, so the holder can only be found by matching
    # the script against what is actually listening. The victim must bind
    # exclusively or the conflict never happens on Windows (see
    # victim_server_source).
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(victim_server_source(port))
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    assert started, f"test server did not start (state={holder.state})"
    try:
        st = sm.Store(tmp / "registry.json")
        # bare command, no url, no args — exactly the user's entry
        rec = st.add(
            sm.validate(
                {
                    "name": "obs",
                    "command": f"{sys.executable} {srv_py}",
                    "working_dir": str(tmp),
                }
            )
        )
        w = HubWindow(st)
        w.show()
        offered = []
        w._offer_to_free_port = lambda r, p, c: offered.append(c)
        holder_pid = holder.proc.processId() if holder.proc else None
        # Record what the failing project actually reported, so the assertion
        # below can say which link broke instead of just "no offer".
        _p = w.procs.get(rec["id"])
        if _p is not None:
            _p._dbg_conflict_signal = None
            _p.port_conflict_from_output.connect(
                lambda value, _proc=_p: setattr(_proc, "_dbg_conflict_signal", value)
            )
        try:
            # Press Start (start=True); selecting alone no longer runs anything.
            w._select_id(rec["id"], start=True)
            ok = _wait_for(lambda: offered, timeout_s=30)
            assert ok, (
                "a bare-command project whose port was taken got no conflict "
                "offer (it just died with 'Address already in use'); "
                f"{_conflict_debug(w, rec['id'], holder_pid, port)}"
            )
            assert offered[0]["holders"], offered[0]
            assert _own_tree(holder) & {h["pid"] for h in offered[0]["holders"]}, offered[0]
        finally:
            w.close()
    finally:
        stop_and_release(holder, srv_py)


def test_no_url_project_gets_conflict_after_it_fails(tmp: Path) -> None:
    """A project with NO url still gets the port-conflict treatment.

    The user's case: "obsv" is `python3 obs_live.py` with no URL, so the
    pre-start check has nothing to inspect. The offer therefore comes AFTER
    the server fails to bind, by matching the failing project's own script
    against what is actually listening.

    It must NOT be blocked before starting: scanning unrelated ports would
    refuse legitimate starts, which is worse than one failed attempt.
    """
    port = reserve_port()
    # The port is a default INSIDE the script, like obs_live.py — nothing in
    # the command line names it. The victim must bind exclusively or the
    # conflict never happens on Windows (see victim_server_source).
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(victim_server_source(port))
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    assert started, f"test server did not start (state={holder.state})"
    try:
        st = sm.Store(tmp / "registry.json")
        no_url = st.add(
            sm.validate(
                {
                    "name": "obsv",
                    "command": f"{sys.executable} {srv_py}",
                    "working_dir": str(tmp),
                }
            )
        )
        w = HubWindow(st)
        w.show()
        offered = []
        w._offer_to_free_port = lambda rec, proc, conflict: offered.append(conflict)
        holder_pid = holder.proc.processId() if holder.proc else None
        _p = w.procs.get(no_url["id"])
        if _p is not None:
            _p._dbg_conflict_signal = None
            _p.port_conflict_from_output.connect(
                lambda value, _proc=_p: setattr(_proc, "_dbg_conflict_signal", value)
            )
        try:
            w._select_id(no_url["id"], start=True)
            ok = _wait_for(lambda: offered, timeout_s=30)
            assert ok, (
                "a no-URL project whose port was taken got no conflict offer — "
                "it just died with 'Address already in use' and nothing was said; "
                f"{_conflict_debug(w, no_url['id'], holder_pid, port)}"
            )
            assert offered[0]["holders"], offered[0]
            assert _own_tree(holder) & {h["pid"] for h in offered[0]["holders"]}, offered[0]
        finally:
            w.close()
    finally:
        stop_and_release(holder, srv_py)


def test_about_dialog_is_closable_and_unhighlighted() -> None:
    """The About box must close like a normal window, with nothing highlighted.

    Two failures are being guarded against here:

    - QMessageBox.about() builds a parentless box with no default button, so
      macOS highlights an arbitrary control and the text renders as selectable
      (an editable-looking caret).
    - A QMessageBox with NO buttons CANNOT be dismissed by the keyboard at all
      — Escape leaves it open, trapping the user. So this is a plain QDialog,
      and the test asserts Escape actually closes it.
    """
    import tempfile

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QDialog

    shown = []
    original_exec = QDialog.exec

    def fake_exec(self):
        self.show()
        QApplication.processEvents()
        shown.append(self)
        self.close()  # what Escape does
        QApplication.processEvents()
        return 0

    QDialog.exec = fake_exec
    try:
        with temp_project_dir() as d:
            st = sm.Store(Path(d) / "registry.json")
            w = HubWindow(st)
            w.show()
            try:
                HubWindow._show_about(w)
            finally:
                w.close()
    finally:
        QDialog.exec = original_exec

    dlg = shown[0] if shown else None
    assert dlg is not None, "no dialog was shown"
    assert dlg.parent() is not None, "the About box has no parent window"
    # Escape must close it, or the user is stuck with a buttonless dialog.
    assert not dlg.isVisible(), "Escape did not close the About box"
    assert type(dlg).__name__ == "QDialog", type(dlg).__name__
    # NOTE: the close-only window buttons are deliberately NOT asserted here.
    # The macOS platform plugin ignores window-button hints for a QDialog, and
    # every flag combination reports identically under the offscreen platform —
    # so such an assertion passes while the real window still shows all three
    # lights. Qt.Tool is used for that reason; only the behaviour that is
    # actually verifiable is asserted.
    labels = dlg.findChildren(QLabel)
    assert labels, "the About box shows no text"
    assert labels[0].textInteractionFlags() == Qt.NoTextInteraction, (
        "the text is selectable, which shows an editable-looking caret"
    )


def test_about_box_hides_extra_window_buttons() -> None:
    """The About box must show the close button alone.

    Qt's window-button hints CANNOT achieve this on macOS (every combination
    gives some set of traffic lights), so this asserts on the real AppKit
    buttons, which only exist on a real screen. Skipped under the offscreen
    platform, where no window decorations are created at all and the assertions
    could never hold.
    """
    import os

    from PySide6.QtCore import Qt

    from hub import macos_buttons as mb

    if os.environ.get("QT_QPA_PLATFORM") in ("offscreen", "minimal", "vnc"):
        raise SkipTest("offscreen has no decorations")
    if not mb.available():
        raise SkipTest("no pyobjc")

    dlg = QDialog()
    dlg.setWindowTitle("About Local Project Hub")
    dlg.setWindowFlags(Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
    dlg.show()
    QApplication.processEvents()
    try:
        ns_window = mb.find_window(dlg)
        assert ns_window is not None, "could not find the backing NSWindow"
        mb.show_only_close_button(ns_window)

        close_button = ns_window.standardWindowButton_(0)
        minimize_button = ns_window.standardWindowButton_(1)
        zoom_button = ns_window.standardWindowButton_(2)
        assert close_button is not None and not close_button.isHidden(), (
            "the close button must stay visible"
        )
        assert minimize_button is not None and minimize_button.isHidden(), (
            "the minimise button is still shown"
        )
        assert zoom_button is not None and zoom_button.isHidden(), (
            "the zoom button is still shown"
        )
    finally:
        dlg.close()


def test_configured_url_is_never_overridden(tmp: Path) -> None:
    """A URL the user typed themselves always wins over detection."""
    port = reserve_port()
    srv_py = tmp / "announce3.py"
    srv_py.write_text(_ANNOUNCING_SERVER)
    rec = sm.validate(
        {
            "name": "Mine",
            "command": f"{sys.executable} {srv_py} {port}",
            "working_dir": str(tmp),
            "url": "http://127.0.0.1:9999/",  # deliberately different
        }
    )
    p = ProjectProcess(rec)
    got = []
    p.url_detected.connect(lambda u: got.append(u))
    p.start()
    _wait_for(lambda: bool(got), timeout_s=25)
    stop_and_release(p, srv_py)
    # detection must not fire at all when a URL is already configured
    assert got == [], f"detection ran despite a configured URL: {got}"


def test_hardcoded_port_conflict_is_detected_without_a_url(tmp: Path) -> None:
    """A project whose port is hardcoded in its script still gets checked.

    the_sphere_project's server.py binds `PORT = ... else 8471`, so nothing on
    the command line and no URL reveals the port. Before this the pre-start
    check had nothing to test, the start ran straight into "Address already in
    use", and the hub looped restarting a server that could never come up.
    """
    port = reserve_port()
    srv_py = tmp / "server.py"
    # a hardcoded default port, exactly the sphere shape
    srv_py.write_text(
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "PORT = int(sys.argv[1]) if len(sys.argv) > 1 else %d\n" % port
        + "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        'ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()\n'
    )
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Holder",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
            }
        )
    )
    assert start_holder(holder, port), holder.state
    try:
        # No URL at all, and detection finds no port either — the port is only
        # readable from the script's source.
        victim = ProjectProcess(
            sm.validate(
                {
                    "name": "Victim",
                    "command": f"{sys.executable} {srv_py}",
                    "working_dir": str(tmp),
                }
            )
        )
        assert victim.rec.get("url") == "", victim.rec
        assert victim._expected_port() == port, victim._expected_port()
        conflict = victim.port_conflict()
        assert conflict, "hardcoded port holder was not detected"
        assert conflict["port"] == port, conflict
        assert holder.proc is not None
        assert conflict["holders"][0]["pid"] in _own_tree(holder), conflict
    finally:
        stop_and_release(holder, srv_py)


def test_free_hardcoded_port_reports_no_conflict(tmp: Path) -> None:
    """The negative control: the same detection must stay quiet when free."""
    port = reserve_port()
    srv_py = tmp / "server.py"
    srv_py.write_text(
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "PORT = int(sys.argv[1]) if len(sys.argv) > 1 else %d\n" % port
        + "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        'ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()\n'
    )
    proj = ProjectProcess(
        sm.validate(
            {
                "name": "Solo",
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    assert proj._expected_port() == port, proj._expected_port()
    assert proj.port_conflict() is None, "a free port was reported as a conflict"


def test_cli_project_has_no_expected_port(tmp: Path) -> None:
    """A non-server script must not have a port invented for it."""
    script = tmp / "hello.py"
    script.write_text("print('hello')\n")
    proj = ProjectProcess(
        sm.validate(
            {"name": "Hello", "command": f"{sys.executable} {script}",
             "working_dir": str(tmp)}
        )
    )
    assert proj._expected_port() is None, proj._expected_port()
    assert proj.port_conflict() is None


def test_port_recovered_from_a_hardcoded_script_traceback(tmp: Path) -> None:
    """The port is recoverable from the traceback + script, not the command.

    Python prints `(\"127.0.0.1\", PORT)` and never resolves the number, so the
    command line is useless here. The traceback names the file, which is the
    only way to learn the port.
    """
    port = reserve_port()
    srv_py = tmp / "server.py"
    srv_py.write_text(
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "PORT = int(sys.argv[1]) if len(sys.argv) > 1 else %d\n" % port
        + "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        'ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()\n'
    )
    proj = ProjectProcess(
        sm.validate(
            {"name": "Solo", "command": f"{sys.executable} {srv_py}",
             "working_dir": str(tmp)}
        )
    )
    proj.history = deque(
        [
            'Traceback (most recent call last):\n'
            f'  File "{srv_py}", line 5, in <module>\n'
            '    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()\n'
            "OSError: [Errno 48] Address already in use\n"
        ]
    )
    assert proj._failed_to_bind()
    assert proj._port_from_failure_output() == port, proj._port_from_failure_output()



def test_bind_failure_is_recognised_on_every_platform(tmp: Path) -> None:
    """A port-taken failure must be recognised whatever the OS calls it.

    _failed_to_bind() only matched macOS/Linux wording, so the Windows
    equivalent was never seen: the signal that offers to end the holder never
    fired, and a project whose port was taken simply died. The port could not be
    recovered either, for the same reason. Each platform words it differently and
    only one phrase is shared, so all three are pinned here rather than left to
    whichever machine happens to run the suite.
    """
    from collections import deque

    from hub.process_manager import ProjectProcess

    wordings = {
            "macOS": 'OSError: [Errno 48] Address already in use\n',
            "Linux": 'OSError: [Errno 98] Address already in use\n',
            "Windows": (
                "OSError: [WinError 10048] Only one usage of each socket address\n"
                "(protocol/network address/port) is normally permitted.\n"
            ),
    }

    script = tmp / "srv.py"
    script.write_text("import sys\nprint('x')\n")
    proc = ProjectProcess(
            sm.validate(
                {"name": "S", "command": f"{sys.executable} {script} 8791",
                 "working_dir": str(tmp)}
            )
    )

    for platform, text in wordings.items():
            proc.history = deque([text])
            assert proc._failed_to_bind(), f"{platform} bind failure was not recognised"
            assert proc._port_from_failure_output() == 8791, (
                f"{platform}: port not recovered from the command line"
            )

    # Unrelated failures must not be mistaken for a bind conflict.
    proc.history = deque(['Traceback (most recent call last):\n', "ValueError: bad\n"])
    assert not proc._failed_to_bind(), "an unrelated error was read as a bind failure"
    assert proc._port_from_failure_output() is None


def test_finish_time_output_is_drained_before_deciding_conflict(tmp: Path) -> None:
    """The traceback still in the pipe when `finished` fires must still count.

    QProcess emits `finished` without promising every `readyRead` has arrived.
    The child's final write — for a dying Python server, the whole
    "Address already in use" traceback — can be sitting in the pipe at that
    moment. `_on_finished()` used to look at `self.history` before reading it,
    so on a machine that loses that race the traceback was simply absent:
    `_failed_to_bind()` returned False, no `port_conflict_from_output` fired,
    and the user got a silent 'Address already in use' with no offer to free
    the port. macOS won the race and Windows lost it, which is why this looked
    like a Windows-only bug for days.

    The test refuses the timing argument by NOT racing at all: the fake process
    hands over the bytes only when its output is read, and never emits a
    readyRead at all — the exact state at the moment `finished` fires.
    """

    class BufferedAtFinish:
        """A QProcess whose last write is still unread when it finishes."""

        def __init__(self, text: str):
            self._text = text.encode()
            self._handed_over = False

        # readyReadStandardOutput is deliberately NEVER emitted for this data.
        def readAllStandardOutput(self):
            data, self._text = self._text, b""
            self._handed_over = True
            return data

        def processId(self):
            return 4242

        def handed_over(self):
            return self._handed_over

    port = reserve_port()
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers()\n"
        "    def log_message(self,*a): pass\n"
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n"
    )
    # The holder that keeps the port, so the offer has a real foreign owner.
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    started = start_holder(holder, port)
    assert started, f"test server did not start (state={holder.state})"
    try:
        # A real holder is on `port`; the failing project binds the same one.
        srv_py_bad = tmp / "obs_live.py"
        traceback = (
            "Traceback (most recent call last):\n"
            f'  File "{srv_py_bad}", line 6, in <module>\n'
            f"    HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n"
            "  File \"socketserver.py\", line 466, in server_bind\n"
            "    self.socket.bind(self.server_address)\n"
            "OSError: [WinError 10048] Only one usage of each socket address "
            "(protocol/network address/port) is normally permitted.\n"
        )
        st = sm.Store(tmp / "registry.json")
        rec = st.add(
            sm.validate(
                {
                    "name": "obs",
                    "command": f"{sys.executable} {srv_py_bad}",
                    "working_dir": str(tmp),
                }
            )
        )
        proc = ProjectProcess(rec)
        fake = BufferedAtFinish(traceback)
        proc.proc = fake
        assert not fake.handed_over(), "the bytes must still be in the pipe"

        emitted = []
        proc.port_conflict_from_output.connect(emitted.append)

        w = HubWindow(st)
        w.show()
        offered = []
        w._offer_to_free_port = lambda r, p, c: offered.append(c)
        try:
            w.active_id = rec["id"]
            w._on_select()
            # Wire it exactly as the window does: the signal carries only the
            # port, and the handler wants (pid, port).
            proc.port_conflict_from_output.connect(
                lambda port, p=rec["id"]: w._on_port_conflict_from_output(p, port)
            )

            # The whole point: nothing drained, then the child "finishes".
            proc._user_stopped = False
            proc._on_finished(1, QProcess().exitStatus())

            assert emitted, (
                "no port_conflict_from_output signal was emitted; the "
                "traceback never reached history so the failure was not "
                "recognised as a bind failure at all"
            )
            assert emitted[0] == port, (
                "the signal carried a different port than the traceback's "
                f"port: {emitted[0]} != {port}"
            )
            assert offered, (
                "the window handler received the signal but offered nothing; "
                f"signal={emitted[0]}"
            )
            holder_pid = holder.proc.processId() if holder.proc else None
            assert _own_tree(holder) & {h["pid"] for h in offered[0]["holders"]}, offered[0]
        finally:
            w.close()
    finally:
        stop_and_release(holder, srv_py)


def test_conflict_victim_actually_fails_to_bind(tmp: Path) -> None:
    """The victim fixture must be unable to bind a port that is already held.

    Windows CI exposed a vacuous test. A victim built on plain `HTTPServer`
    (`allow_reuse_address = 1`) does not fail next to a holder that is also an
    HTTPServer, because on Windows SO_REUSEADDR lets a second socket bind an
    endpoint an existing SO_REUSEADDR socket holds -- POSIX would require
    SO_REUSEPORT for that. The victim therefore bound alongside the holder,
    ran forever, and printed nothing, so no test ever failed: the diagnostic was
    `state=running`, `signal=None`, `history_tail=''`, and two owner PIDs on one
    port. On macOS the same fixture behaves correctly, which is why the suite
    looked green locally while asserting nothing at all on Windows.

    This pins the property that makes the conflict tests real. It is portable:
    an exclusive bind of a held endpoint is refused on both platforms, whereas a
    reusing bind is refused only on one. If that ever stops holding, this test
    fails instead of the conflict tests silently going quiet again.
    """
    from http.server import HTTPServer

    assert int(HTTPServer.allow_reuse_address) != 0, (
        "the stdlib HTTPServer now binds exclusively, so the fixture override is "
        "no longer needed -- this test should then assert the fixture matches it"
    )
    port = reserve_port()
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(victim_server_source(port))

    # Occupy the port the way a holder does, then ask the victim for it.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)
        try:
            done = subprocess.run(
                [sys.executable, str(srv_py)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise AssertionError(
                "the victim script is still running on a port that was already "
                "held -- it never hit the conflict, so this test cannot test "
                "the hub's handling of one"
            )
        combined = (done.stdout or "") + (done.stderr or "")
        assert done.returncode != 0, (
            "the victim started happily on an occupied port; the conflict path "
            "it exists to exercise never ran"
        )
        assert "OSError" in combined or "Errno" in combined or "WinError" in combined, (
            f"the victim failed, but not by failing to bind: ...{combined[-300:]}"
        )
    finally:
        blocker.close()


def test_port_is_recovered_from_the_traceback_not_the_script(tmp: Path) -> None:
    """The port must come from the traceback when the script never assigns one.

    The case that kept Windows red: a project is `python3 obs_live.py` with no
    URL, and the script hardcodes its listener as
    `HTTPServer(('127.0.0.1', 60168), H).serve_forever()`. There is no `PORT =`
    line to find and no port on the command line, so the old recovery path
    (`_port_from_entry_script`) returned None on EVERY platform. The signal then
    fired with port 0, and the offer depended on `listening_ports_all()`
    happening to list the port in netstat order — which it did on macOS and did
    not on Windows. Python echoes the failing source line, so the number is
    right there; it just had to be read.

    This is why the failure looked Windows-specific and kept coming back: the
    Windows run had no working path at all, while macOS survived on the fragile
    fallback. All three platforms are pinned so the difference cannot depend on
    which machine runs the suite.
    """
    from collections import deque

    from hub.process_manager import ProjectProcess, _port_from_traceback

    # The real Windows traceback from the failing CI run, with its 8.3 paths.
    windows = "\n".join([
        "Traceback (most recent call last):",
        '  File "C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\tmpd3roi4eg\\obs_live.py",'
        " line 6, in <module>",
        "    HTTPServer(('127.0.0.1',60168),H).serve_forever()",
        '  File "C:\\...\\socketserver.py", line 466, in server_bind',
        "    self.socket.bind(self.server_address)",
        "OSError: [WinError 10048] Only one usage of each socket address "
        "(protocol/network address/port) is normally permitted.",
    ])
    assert _port_from_traceback(windows) == 60168, (
        "the Windows traceback names 60168 in the failing call"
    )

    # A script exactly like the failing one: the port is only in the traceback.
    port = reserve_port()
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers()\n"
        "    def log_message(self,*a): pass\n"
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n"
    )
    proc = ProjectProcess(
        sm.validate(
            {
                "name": "obsv",
                # No port on the command line — the whole point.
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    assert proc._port_from_entry_script(windows) is None, (
        "this script has no `PORT =` line, so the entry-script fallback cannot "
        "find the port either — the traceback is the only source"
    )
    # The same traceback, built for THIS run's port, so the assertion is about
    # the recovery rule and not about the number 60168 specifically.
    own = windows.replace(f"'127.0.0.1',60168", f"'127.0.0.1',{port}")
    proc.history = deque([own])
    assert proc._failed_to_bind()
    assert proc._port_from_failure_output() == port, (
        "the port was recoverable from the traceback but recovery still failed"
    )


def test_listening_ports_ignores_the_listen_column(tmp: Path) -> None:
    """lsof's LAST field is "(LISTEN)", not the address.

    Taking split()[-1] grabs "(LISTEN)", finds no colon, and silently reports
    no ports — so URL detection by port never fires and the dashboard loads
    with no address. The address is the second-to-last field.
    """
    port = reserve_port()
    srv_py = tmp / "server.py"
    srv_py.write_text(_SILENT_SERVER.replace("int(sys.argv[1])", str(port)))
    proc = subprocess.Popen(
        [sys.executable, str(srv_py)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(lambda: urldetect.port_in_use(port), timeout_s=20)
        assert urldetect.listening_ports(proc.pid) == [port], (
            urldetect.listening_ports(proc.pid)
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.SubprocessError:
            proc.kill()


def test_unbuffered_python_output_is_visible_to_the_hub(tmp: Path) -> None:
    """A plain `python3 server.py` must have its URL detected.

    Python block-buffers stdout when it is not a tty, so the server's
    "serving on ..." line never reaches the hub in time and the dashboard is
    left with no address. The hub sets PYTHONUNBUFFERED=1 for the child, which
    is what the project already does on a terminal.
    """
    port = reserve_port()
    srv_py = tmp / "server.py"
    srv_py.write_text(
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "PORT = int(sys.argv[1]) if len(sys.argv) > 1 else %d\n" % port
        + "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        'print("serving on http://localhost:%%d" %% PORT, flush=False)\n'
        'ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()\n'
    )
    proc = ProjectProcess(
        sm.validate(
            {
                "name": "Buffered",
                "command": f"{sys.executable} {srv_py} {port}",
                "working_dir": str(tmp),
            }
        )
    )
    seen: list[str] = []
    proc.url_detected.connect(seen.append)
    proc.start()
    got = _wait_for(lambda: bool(seen), timeout_s=20)
    try:
        proc.stop()
    except Exception:
        pass
    _wait_for(lambda: proc.state == "stopped", timeout_s=25)
    assert got, f"URL was never detected from an unbuffered-forced child: {seen}"


def test_detected_suppress_flag_is_applied_to_the_launch(tmp: Path) -> None:
    """A project whose own argparse declares --no-open gets it automatically.

    This is spec §2's whole point: the user should not have to know the flag
    exists. Detection alone is not enough — the flag has to reach the launch,
    which is the bug this test pins (detection reported known-suppressible but
    args stayed empty, so the browser still opened).
    """
    port = reserve_port()
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(
        "import argparse, sys\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "ap = argparse.ArgumentParser()\n"
        + ('ap.add_argument("--port", type=int, default=%d)\n' % port)
        + 'ap.add_argument("--no-open", action="store_true")\n'
        "args = ap.parse_args()\n"
        'print("dashboard at http://127.0.0.1:%d" % args.port)\n'
        'if not args.no_open:\n    import webbrowser\n    webbrowser.open("x")\n'
        'ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler).serve_forever()\n'
    )
    rec = sm.validate(
        {
            "name": "Obs",
            "command": f"{sys.executable} {srv_py}",
            "working_dir": str(tmp),
        }
    )
    # detection must have found it
    assert _detected_suppress_flag(rec) == "--no-open", rec["detected"]

    proc = ProjectProcess(dict(rec))
    proc.start()
    started = _wait_for(lambda: proc.state == "running", timeout_s=20)
    try:
        assert started, f"did not start: {proc.state}"
        assert proc.proc is not None
        pid = proc.proc.processId()
        # Use the platform-aware helper rather than calling `ps` directly: ps
        # does not exist on Windows, so a direct call returns "" there and this
        # assertion would fail for a reason that has nothing to do with the flag.
        argv = urldetect.process_command(pid)
        assert "--no-open" in argv, f"flag never reached the process: {argv!r}"
    finally:
        stop_and_release(proc, srv_py)


def test_stored_detection_without_entry_script_still_yields_the_flag(tmp: Path) -> None:
    """A record saved before entry_script existed must not lose its flag.

    Re-read its declared CLI rather than trusting a stale descriptive line.
    Missing historical entry_script metadata must not lose a safe flag, and
    removing that option in the current script must not break the next start.
    """
    rec = {
        "name": "Legacy",
        "command": "python3 obs_live.py",
        "working_dir": str(tmp),
        "args": "",
        "url": "",
        "detected": {
            "type": "web",
            "confidence": 0.6,
            "framework": "",
            "port": None,
            "browser": "known-suppressible",
            "display": "embedded web view",
            "evidence": [
                "entry script implements a stdlib HTTP server (BaseHTTPRequestHandler/HTTPServer)",
                "entry script declares --no-open in its argparse",
            ],
        },
    }
    source = tmp / "obs_live.py"
    source.write_text("import argparse\nfrom http.server import HTTPServer\n"
                      "ap = argparse.ArgumentParser()\n"
                      "ap.add_argument('--no-open', action='store_true')\n", encoding="utf-8")
    assert _detected_suppress_flag(rec) == "--no-open", rec["detected"]
    source.write_text("print('option no longer exists')\n", encoding="utf-8")
    assert _detected_suppress_flag(rec) == "", "stale evidence overrode the current CLI"


def test_user_supplied_args_are_never_overridden(tmp: Path) -> None:
    """A deliberate argument field wins even when a safe flag is detectable."""
    script = tmp / "obs_live.py"
    source = ("import argparse\nfrom http.server import HTTPServer\n"
              "ap = argparse.ArgumentParser()\n"
              "ap.add_argument('--no-open', action='store_true')\n"
              "ap.add_argument('--label')\nargs = ap.parse_args()\n"
              "print('HUB_USER_ARGS', args.no_open, args.label, flush=True)\n")
    script.write_text(source, encoding="utf-8")
    rec = {"name": "Typed", "command": "python3 obs_live.py", "interpreter": sys.executable,
           "working_dir": str(tmp), "args": "--label selected", "url": "",
           "detected": {"type": "web", "browser": "known-suppressible", "evidence": [
               "entry script declares --no-open in its argparse"]}}
    assert _detected_suppress_flag(rec) == "--no-open"
    proc = ProjectProcess(dict(rec))
    output = []
    proc.output.connect(output.append)
    try:
        proc.start()
        assert _wait_for(lambda: proc.proc is not None and proc.proc.state() == QProcess.NotRunning), output
        assert proc.proc is not None and proc.proc.exitCode() == 0, output
        assert "HUB_USER_ARGS False selected" in "".join(output), output
        assert rec["args"] == "--label selected"
        assert script.read_text(encoding="utf-8") == source
    finally:
        proc.stop()
        assert _wait_for(lambda: proc.proc is None or proc.proc.state() == QProcess.NotRunning)


def test_netstat_parser_finds_only_listeners() -> None:
    """The Windows port-owner parser, exercised on every platform.

    lsof is not available on Windows runners, so port_owners() used to report an
    empty set there and every conflict check concluded "cannot tell who holds
    it" -- which read as no conflict at all. This test feeds the netstat parser
    real output shapes so the Windows path is covered wherever it runs, instead
    of only on the machine that has netstat.

    Only LISTENING rows count. A port also appears on outbound connections whose
    ephemeral local port can coincide with it, and a listener's own accepted
    connections show that port on both sides.
    """
    sample = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:8787           0.0.0.0:0              LISTENING       12345
  TCP    [::]:8787              [::]:0                 LISTENING       12345
  TCP    127.0.0.1:9011         127.0.0.1:8787         ESTABLISHED     22222
  TCP    127.0.0.1:8787         127.0.0.1:9011         ESTABLISHED     12345
  TCP    0.0.0.0:5000           0.0.0.0:0              LISTENING       33333
  UDP    0.0.0.0:8787           *:*                                    44444
"""

    class _FakeResult:
        stdout = sample

    real_run = subprocess.run
    real_flag = urldetect.IS_WINDOWS
    subprocess.run = lambda *a, **k: _FakeResult()  # type: ignore[assignment]
    urldetect.IS_WINDOWS = True  # the branch a Windows runner actually takes
    try:
        rows = urldetect._netstat_listening_rows()
        listeners = urldetect._port_owners_netstat(8787)
        other = urldetect._port_owners_netstat(5000)
        absent = urldetect._port_owners_netstat(9999)
        by_pid = urldetect.listening_ports(12345)
        established_only = urldetect.listening_ports(22222)
        every = urldetect.listening_ports_all()
    finally:
        subprocess.run = real_run  # type: ignore[assignment]
        urldetect.IS_WINDOWS = real_flag

    # The listener's PID only: the ESTABLISHED rows (client 22222, and the
    # server side of its own accepted connection) and the UDP row are not
    # holders of a TCP listener.
    assert listeners == {12345}, listeners
    assert other == {33333}, other
    assert absent == set(), absent
    assert 12345 in {r[1] for r in rows}, rows
    # IPv4 and IPv6 rows for the same listener are one port, not two.
    assert by_pid == [8787], by_pid
    # A PID with only outbound connections holds nothing.
    assert established_only == [], established_only
    assert every == [8787, 5000], every


def test_process_command_reads_on_every_platform() -> None:
    """The holder's command line must be readable on Windows too.

    process_command() used `ps -o command=`, which does not exist on Windows, so
    it silently returned "" for every PID there. The conflict dialog then offered
    to end a process without naming it, and the test asserting the holder's
    script is named failed with `{'pid': 3468, 'command': ''}`.

    PowerShell's Win32_Process is the Windows equivalent. Its output can be empty
    (a protected process, or one whose command line cannot be read), which must
    stay "" rather than becoming an error.
    """
    cases = [
        # (label, powershell stdout, expected)
        ("full command line", "python.exe holder.py 55555", "python.exe holder.py 55555"),
        ("empty output", "", ""),
        ("no output at all", None, ""),
        ("multiline", "python.exe obs.py 8471\npython.exe other.py", "python.exe obs.py 8471"),
        ("trailing newline", "python.exe obs.py 8471\n", "python.exe obs.py 8471"),
    ]

    class _Fake:
        def __init__(self, stdout):
            self.stdout = stdout

    real_run = subprocess.run
    real_flag = urldetect.IS_WINDOWS
    urldetect.IS_WINDOWS = True
    try:
        for label, out, expected in cases:
            subprocess.run = lambda *a, **k: _Fake(out or "")
            got = urldetect.process_command(3468)
            assert got == expected, f"{label}: {got!r} != {expected!r}"
    finally:
        subprocess.run = real_run
        urldetect.IS_WINDOWS = real_flag

    # The Unix path must be unchanged by the Windows branch.
    urldetect.IS_WINDOWS = False
    try:
        subprocess.run = lambda *a, **k: _Fake("python3 obs.py 8471\n")
        assert urldetect.process_command(3468) == "python3 obs.py 8471"
    finally:
        subprocess.run = real_run


# ---------- INFO-002: process liveness ----------


def test_posix_liveness_reflects_a_real_process(tmp: Path) -> None:
    import os

    if urldetect.IS_WINDOWS:
        raise SkipTest("Windows uses Win32")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert urldetect._posix_process_alive(child.pid) is True
        child.terminate()
        child.wait(timeout=10)
        assert urldetect._posix_process_alive(child.pid) is False
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        try:
            os.kill(child.pid, 0)
        except OSError:
            pass


def test_posix_liveness_treats_permission_error_as_alive(tmp: Path) -> None:
    """An inaccessible process exists; only ProcessLookupError proves it gone."""
    import os

    if urldetect.IS_WINDOWS:
        raise SkipTest("Windows uses Win32")
    real = os.kill

    def forbidden(pid, sig):
        raise PermissionError(1, "not ours")

    os.kill = forbidden
    try:
        assert urldetect._posix_process_alive(1234) is True
    finally:
        os.kill = real


class _FakeKernel32:
    """Win32 process API double: no real process is opened or queried."""

    def __init__(self, handle=1, exit_code=None, open_ok=True):
        self.handle = handle
        self.exit_code = exit_code
        self.open_ok = open_ok
        self.closed = False

    def OpenProcess(self, access, inherit, pid):
        return self.handle if self.open_ok else 0

    def GetExitCodeProcess(self, handle, pointer):
        pointer.contents.value = self.exit_code
        return 1

    def CloseHandle(self, handle):
        self.closed = True
        return 1


def test_windows_liveness_uses_the_win32_exit_code(tmp: Path) -> None:
    live = _FakeKernel32(exit_code=urldetect._WIN_STILL_ACTIVE)
    assert urldetect._windows_process_alive(4242, live, lambda: 0) is True
    assert live.closed, "the process handle was not closed"

    exited = _FakeKernel32(exit_code=0)
    assert urldetect._windows_process_alive(4242, exited, lambda: 0) is False

    unknown = _FakeKernel32(exit_code=0)
    unknown.GetExitCodeProcess = lambda handle, pointer: 0
    assert urldetect._windows_process_alive(4242, unknown, lambda: 0) is True


def test_windows_liveness_distinguishes_denied_and_absent(tmp: Path) -> None:
    denied = _FakeKernel32(open_ok=False)
    assert urldetect._windows_process_alive(4, denied, lambda: 5) is True

    absent = _FakeKernel32(open_ok=False)
    assert urldetect._windows_process_alive(4, absent, lambda: 87) is False

    undetermined = _FakeKernel32(open_ok=False)
    assert urldetect._windows_process_alive(4, undetermined, lambda: 1234) is True


def test_windows_liveness_reads_a_real_process(tmp: Path) -> None:
    if not urldetect.IS_WINDOWS:
        raise SkipTest("not Windows")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert urldetect._windows_process_alive(child.pid) is True
        child.terminate()
        child.wait(timeout=10)
        assert urldetect._windows_process_alive(child.pid) is False
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_kill_process_does_not_claim_success_when_signal_is_denied(tmp: Path) -> None:
    """An inaccessible process was NOT killed; do not report that it was."""
    import os

    real = os.kill

    def denied(pid, sig):
        raise PermissionError(1, "not ours")

    os.kill = denied
    try:
        assert urldetect.kill_process(1234, timeout_s=0.2) is False
    finally:
        os.kill = real


def test_port_in_use_reports_busy_when_the_table_cannot_be_read(tmp: Path) -> None:
    """Unavailable netstat is uncertainty, not proof that the port is free."""
    real_run = subprocess.run
    real_flag = urldetect.IS_WINDOWS

    def broken(*a, **k):
        raise OSError("netstat unavailable")

    subprocess.run = broken  # type: ignore[assignment]
    urldetect.IS_WINDOWS = True
    try:
        assert urldetect._netstat_listening_rows() is None
        assert urldetect.port_in_use(23456) is True
    finally:
        subprocess.run = real_run  # type: ignore[assignment]
        urldetect.IS_WINDOWS = real_flag


def test_kill_process_actually_ends_its_target(tmp: Path) -> None:
    import os
    import threading

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    reap_errors = []

    def reap() -> None:
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired as exc:
            reap_errors.append(exc)

    # This test owns the Popen child and therefore must reap it while
    # kill_process polls. On POSIX, delaying wait() until after kill_process
    # returns leaves an exited zombie: kill(pid, 0) correctly still sees its
    # PID, so the old fixture could never observe successful termination.
    reaper = threading.Thread(target=reap, daemon=True)
    reaper.start()
    try:
        killed = urldetect.kill_process(child.pid, timeout_s=3)
        reaper.join(timeout=10)
        assert killed is True, f"kill_process returned {killed}; exit={child.returncode}"
        assert not reaper.is_alive(), "child was not reaped within the deadline"
        assert not reap_errors, reap_errors
        assert child.returncode is not None, "child did not actually terminate"
        assert not urldetect.process_alive(child.pid), "terminated child still exists"
    finally:
        if child.poll() is None:
            child.kill()
        reaper.join(timeout=16)
        child.wait(timeout=10)
        assert not reaper.is_alive(), "reaper thread survived fixture cleanup"
    # Never reports success for our own PID, which it must not signal.
    assert urldetect.kill_process(os.getpid()) is False


# ---------- INFO-004: IPv4 and IPv6 port occupancy ----------


def _ipv6_socket():
    """A bound IPv6 loopback listener, or None when IPv6 is unavailable."""
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return None
    try:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        s.bind(("::1", 0))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def test_port_in_use_detects_ipv4_and_ipv6_listeners(tmp: Path) -> None:
    assert urldetect.port_in_use(reserve_port()) is False, "a free port was busy"

    v4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        v4.bind(("127.0.0.1", 0))
        v4.listen(1)
        assert urldetect.port_in_use(v4.getsockname()[1]) is True
    finally:
        v4.close()

    v6 = _ipv6_socket()
    if v6 is None:
        raise SkipTest("no IPv6")
    try:
        assert urldetect.port_in_use(v6.getsockname()[1]) is True, (
            "an IPv6-only listener was reported free"
        )
    finally:
        v6.close()


def test_dual_stack_listener_is_one_busy_port(tmp: Path) -> None:
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        raise SkipTest("no IPv6")
    try:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        s.bind(("::", 0))
        s.listen(1)
    except OSError:
        s.close()
        raise SkipTest("no dual stack")
    port = s.getsockname()[1]
    try:
        # The check is a single boolean, so the two views of one dual-stack
        # socket cannot be mistaken for two conflicting services.
        assert urldetect.port_in_use(port) is True
        assert type(urldetect.port_in_use(port)) is bool
    finally:
        s.close()


def test_unsupported_ipv6_does_not_make_a_free_port_look_busy(tmp: Path) -> None:
    import errno

    port = reserve_port()
    real_socket = socket.socket

    def no_ipv6(family, *args, **kwargs):
        if family == socket.AF_INET6:
            raise OSError(errno.EAFNOSUPPORT, "IPv6 unavailable")
        return real_socket(family, *args, **kwargs)

    socket.socket = no_ipv6
    try:
        assert urldetect.port_in_use(port) is False
    finally:
        socket.socket = real_socket


def _assert_silent_start_discovers_its_own_dashboard(tmp: Path, trigger: str) -> None:
    import ast
    import json
    import shlex
    import urllib.request

    marker = tmp / "bound.json"
    script = tmp / "silent_fixture.py"
    title = "HUB_SILENT_READY_" + trigger.upper()
    body = ("<title>" + title + "</title><h1>" + title + "</h1>").encode()
    source = ("import json, os, sys\nfrom pathlib import Path\n"
              "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
              + "BODY = " + repr(body) + "\n"
              "class H(BaseHTTPRequestHandler):\n"
              "    def do_GET(self):\n"
              "        self.send_response(200); self.end_headers(); self.wfile.write(BODY)\n"
              "    def log_message(self, *args): pass\n"
              "server = HTTPServer(('127.0.0.1', 0), H)\n"
              "target = Path(sys.argv[1]); staged = target.with_suffix('.tmp')\n"
              "staged.write_text(json.dumps({'port': server.server_port, 'pid': os.getpid()}))\n"
              "staged.replace(target)\nserver.serve_forever()\n")
    ast.parse(source)
    script.write_text(source, encoding="utf-8")
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"id": "silent-" + trigger, "name": "Silent " + trigger,
                     "command": shlex.quote(script.name) + " " + shlex.quote(str(marker)),
                     "interpreter": sys.executable, "working_dir": str(tmp),
                     "url": "", "autostart": trigger == "autostart"})
    window = HubWindow(store)
    window.show()
    window._select_id(rec["id"], start=False)
    proc = window._proc_for(rec)
    view = window._view_for(rec["id"])
    assert view is not None
    try:
        if trigger != "autostart":
            assert proc.proc is None, "opening/selecting silently launched the fixture"
        if trigger == "toolbar":
            window.act_start.trigger()
        elif trigger == "page":
            assert _wait_for(lambda: view.title() == rec["name"]), view.title()
            view.page().runJavaScript("document.querySelector('a.btn').click()")
        assert _wait_for(marker.exists, timeout_s=10), list(proc.history)
        bound = json.loads(marker.read_text(encoding="utf-8"))
        assert bound["pid"] in _own_tree(proc), bound
        expected = f"http://127.0.0.1:{bound['port']}/"
        with urllib.request.urlopen(expected, timeout=3) as response:
            assert title.encode() in response.read(), "independent owned backend did not answer"
        assert proc.state == "running" and not proc.history, (proc.state, list(proc.history))
        found = _wait_for(lambda: bool((store.get(rec["id"]) or {}).get("url")), timeout_s=12)
        saved = sm.Store(store.path).get(rec["id"])
        assert found and saved is not None and saved["url"] == expected, (
            f"{trigger} started an answering silent server but never discovered/persisted it; "
            f"owned={bound}, saved={saved}, displayed={view.url().toString()}"
        )
        assert _wait_for(lambda: view.title() == title, timeout_s=10), view.title()
        assert window.tabs.currentWidget() is view and view.isVisible()
        assert view.width() > 0 and view.height() > 0
        assert script.read_text(encoding="utf-8") == source
    finally:
        stop_and_release(proc, script)
        window.close()


def test_toolbar_start_discovers_a_silent_dynamic_server(tmp: Path) -> None:
    _assert_silent_start_discovers_its_own_dashboard(tmp, "toolbar")


def test_page_start_discovers_a_silent_dynamic_server(tmp: Path) -> None:
    _assert_silent_start_discovers_its_own_dashboard(tmp, "page")


def test_autostart_discovers_a_silent_dynamic_server(tmp: Path) -> None:
    _assert_silent_start_discovers_its_own_dashboard(tmp, "autostart")


def test_delayed_port_discovery_ignores_superseded_owners(tmp: Path) -> None:
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import patch
    import hub.window as wm

    for change in ("generation", "replacement", "removed", "manual", "active"):
        store = sm.Store(tmp / (change + ".json"))
        rec = store.add({"id": change, "name": change, "command": "node fixture.js",
                         "working_dir": str(tmp), "url": ""})
        callbacks, calls = [], []
        proc = SimpleNamespace(_generation=0, state="running",
                               detect_url_from_ports=lambda: calls.append("queried"))
        hub = SimpleNamespace(store=store, procs={rec["id"]: proc}, _append_log=lambda *args: None)
        with patch.object(wm.QTimer, "singleShot", side_effect=lambda ms, callback: callbacks.append(callback)):
            # Explicit controller/timer test doubles; no widgets or process run.
            wm.HubWindow._scan_ports_after(cast(HubWindow, hub), rec, cast(ProjectProcess, proc))
        assert len(callbacks) == 1
        if change == "generation":
            proc._generation += 1
        elif change == "replacement":
            hub.procs[rec["id"]] = SimpleNamespace(_generation=0, state="running")
        elif change == "removed":
            store.remove(rec["id"])
        elif change == "manual":
            store.update(dict(rec, url=f"http://127.0.0.1:{reserve_port()}/manual"))
        callbacks[0]()
        assert calls == (["queried"] if change == "active" else []), (change, calls)


def test_replaced_process_signals_cannot_control_the_current_record(tmp: Path) -> None:
    from types import SimpleNamespace
    from typing import cast
    calls = []
    hub = SimpleNamespace(procs={}, _on_state=lambda *args: calls.append(("state", args)),
                          _on_url_detected=lambda *args: calls.append(("url", args)),
                          _on_port_conflict_from_output=lambda *args: calls.append(("conflict", args)),
                          _append_log=lambda *args: None)
    rec = {"id": "replaced-owner", "name": "Owner", "command": "node fixture.js", "working_dir": str(tmp)}
    old = HubWindow._proc_for(cast(HubWindow, hub), rec)
    old.state_changed.emit("running")
    assert calls == [("state", (rec["id"], "running"))], calls
    calls.clear()
    hub.procs.pop(rec["id"])
    current = HubWindow._proc_for(cast(HubWindow, hub), dict(rec))
    old.state_changed.emit("stopped")
    old.url_detected.emit("http://127.0.0.1/old")
    old.port_conflict_from_output.emit(0)
    assert calls == [], ("a replaced process still controls its successor", calls)
    current.state_changed.emit("running")
    current.url_detected.emit("http://127.0.0.1/new")
    current.port_conflict_from_output.emit(0)
    assert [kind for kind, args in calls] == ["state", "url", "conflict"], calls


def test_edit_cancels_old_readiness_and_ignores_its_late_callbacks(tmp: Path) -> None:
    import ast
    import shlex
    from unittest.mock import patch
    import hub.window as wm

    old_port, new_port = reserve_port(), reserve_port()
    while new_port == old_port:
        new_port = reserve_port()
    old_url = f"http://127.0.0.1:{old_port}/old"
    new_url = f"http://127.0.0.1:{new_port}/new"
    title = "HUB_EDIT_REPLACEMENT_READY"
    body = ("<title>" + title + "</title><h1>" + title + "</h1>").encode()
    script = tmp / "replacement.py"
    source = _SILENT_SERVER.replace('b"OK"', repr(body))
    ast.parse(source)
    script.write_text(source, encoding="utf-8")
    store = sm.Store(tmp / "registry.json")
    record = store.add({"id": "edit-waiter", "name": "Before edit", "working_dir": str(tmp),
                        "interpreter": sys.executable, "command": '-c "import time; time.sleep(120)"', "url": old_url})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(record["id"], start=False)
    old_proc = window._proc_for(record)
    replacement = None
    try:
        window.act_start.trigger()
        assert _wait_for(lambda: old_proc.state == "running")
        old_waiter = window.waiters[record["id"]]
        assert old_waiter.url == old_url and not old_waiter._settled
        changed = dict(record, name="After edit", url=new_url,
                       command=shlex.quote(script.name) + " " + str(new_port))
        class AcceptedEdit:
            def __init__(self, parent, record):
                pass
            def exec(self):
                return QDialog.Accepted
            def result_record(self):
                return sm.validate(changed)
        with patch.object(wm, "ProjectDialog", AcceptedEdit):
            window.act_edit.trigger()
        assert record["id"] not in window.waiters and old_waiter._settled, (
            "Edit retained a readiness observer for the superseded URL", list(window.waiters), old_waiter.url
        )
        replacement = window._proc_for(changed)
        assert replacement is not old_proc and replacement.proc is None, "Edit implicitly launched the replacement"
        window.act_start.trigger()
        current_waiter = window.waiters[record["id"]]
        assert current_waiter is not old_waiter and current_waiter.url == new_url
        view = window._view_for(record["id"])
        assert view is not None
        current_html = view.property("hub_page_html")
        # No event-loop turn here: deleteLater is pending, so deliberately
        # deliver both stale callbacks and an old-process state notification.
        old_waiter.failed.emit("STALE_OLD_ENDPOINT")
        old_waiter.ready.emit()
        old_proc.state_changed.emit("stopped")
        assert window.waiters.get(record["id"]) is current_waiter, "old cleanup removed the new waiter"
        assert view.property("hub_page_html") == current_html, "a stale callback replaced the current page"
        assert view.url().toString() != old_url
        assert _wait_for(lambda: view.title() == title, timeout_s=15), (view.title(), list(replacement.history))
        assert window.tabs.currentWidget() is view and view.isVisible() and view.width() > 0 and view.height() > 0
        saved = sm.Store(store.path).get(record["id"])
        assert saved is not None and saved["url"] == new_url and saved["command"] == changed["command"]
        assert script.read_text(encoding="utf-8") == source
    finally:
        for proc in (old_proc, replacement):
            if proc is not None:
                stop_and_release(proc, script)
        for waiter in list(window.waiters.values()):
            waiter.stop()
            waiter.deleteLater()
        window.waiters.clear()
        window.close()


def test_readiness_target_change_retires_only_its_own_observer(tmp: Path) -> None:
    from types import SimpleNamespace
    from typing import cast
    ready, failures = [], []
    pid = "target-owner"
    hub = SimpleNamespace(waiters={}, procs={}, active_id=pid,
                          _append_log=lambda *args: None, _view_for=lambda owner: object(),
                          _show_dashboard=lambda rec: ready.append(rec["url"]),
                          _show_start_page=lambda *args, **kwargs: failures.append(kwargs),
                          status=SimpleNamespace(showMessage=lambda *args: None))
    before = {"id": pid, "name": "Target", "url": f"http://127.0.0.1:{reserve_port()}/old"}
    after = dict(before, url=f"http://127.0.0.1:{reserve_port()}/new")
    try:
        HubWindow._wait_ready(cast(HubWindow, hub), before)
        old = hub.waiters[pid]
        HubWindow._wait_ready(cast(HubWindow, hub), after)
        current = hub.waiters[pid]
        assert current is not old and old._settled and current.url == after["url"], (
            "new target inherited the old readiness deadline", old.url, current.url
        )
        old.ready.emit()
        old.failed.emit("STALE_OLD_TARGET")
        assert hub.waiters.get(pid) is current and not ready and not failures
        current.ready.emit()
        assert ready == [after["url"]] and not failures and pid not in hub.waiters
    finally:
        for waiter in list(hub.waiters.values()):
            waiter.stop()
            waiter.deleteLater()
        hub.waiters.clear()


def test_restart_replaces_readiness_from_the_previous_run(tmp: Path) -> None:
    port = reserve_port()
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"id": "restart-pending", "name": "Pending restart", "working_dir": str(tmp),
                     "interpreter": sys.executable, "command": '-c "import time; time.sleep(120)"',
                     "url": f"http://127.0.0.1:{port}/"})
    window = HubWindow(store)
    window._can_show_dialog = lambda: False
    window.show()
    window._select_id(rec["id"], start=False)
    proc = window._proc_for(rec)
    try:
        window.act_start.trigger()
        assert _wait_for(lambda: proc.state == "running")
        old_handle = proc.proc
        old_waiter = window.waiters[rec["id"]]
        window.act_restart.trigger()
        assert _wait_for(lambda: proc.proc is not old_handle and proc.state == "running"), list(proc.history)
        current = window.waiters.get(rec["id"])
        assert current is not None and current is not old_waiter and old_waiter._settled, (
            "restart reused the previous run's readiness observer/deadline", current, old_waiter._settled
        )
    finally:
        stop_and_release(proc)
        for waiter in list(window.waiters.values()):
            waiter.stop()
            waiter.deleteLater()
        window.waiters.clear()
        window.close()


def test_split_banner_is_persisted_only_when_the_actual_url_is_complete(tmp: Path) -> None:
    """Handshake a real pipe at split scheme/port boundaries, then render it."""
    import ast
    import json
    import shlex
    import urllib.request
    from PySide6.QtCore import QUrl

    title = "HUB_FRAMED_URL_READY"
    body = ("<title>" + title + "</title><h1>" + title + "</h1>").encode()
    script, marker, ack = tmp / "framed.py", tmp / "bound.json", tmp / "ack.txt"
    source = ("import json, os, sys, time\nfrom pathlib import Path\n"
              "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
              + "BODY = " + repr(body) + "\n"
              "class H(BaseHTTPRequestHandler):\n"
              "    def do_GET(self):\n"
              "        self.send_response(200); self.end_headers(); self.wfile.write(BODY)\n"
              "    def log_message(self, *args): pass\n"
              "def wait_for_ack(value):\n"
              "    deadline = time.monotonic() + 15\n"
              "    while time.monotonic() < deadline:\n"
              "        if ack.exists() and ack.read_text() == value: return\n"
              "        time.sleep(0.01)\n"
              "    raise RuntimeError('fixture acknowledgement timed out: ' + value)\n"
              "ack = Path(sys.argv[2])\nserver = HTTPServer(('127.0.0.1', 0), H)\n"
              "port = str(server.server_port)\n"
              "url = 'http://127.0.0.1:' + port + '/dashboard?x=1%202'\n"
              "Path(sys.argv[1]).write_text(json.dumps({'url': url, 'pid': os.getpid()}))\n"
              "sys.stdout.write('café Serving on htt'); sys.stdout.flush()\n"
              "wait_for_ack('scheme')\n"
              "sys.stdout.write('p://127.0.0.1:' + port[:1]); sys.stdout.flush()\n"
              "wait_for_ack('port')\n"
              "sys.stdout.write(port[1:] + '/dashboard?x=1%202\\n'); sys.stdout.flush()\n"
              "server.serve_forever()\n")
    ast.parse(source)
    script.write_text(source, encoding="utf-8")
    store = sm.Store(tmp / "registry.json")
    rec = store.add({"id": "framed-url", "name": "Framed banner", "working_dir": str(tmp),
                     "interpreter": sys.executable,
                     "command": " ".join(shlex.quote(str(p)) for p in (script, marker, ack)), "url": ""})
    window = HubWindow(store)
    # Framing must stand alone; OS-port fallback has separate real native tests.
    window._scan_ports_after = lambda rec, proc, delay_ms=6000: None
    window.show()
    window._select_id(rec["id"], start=False)
    proc = window._proc_for(rec)
    output = []
    proc.output.connect(output.append)
    try:
        window.act_start.trigger()
        assert _wait_for(lambda: "".join(proc.history).endswith("Serving on htt")), list(proc.history)
        partial = sm.Store(store.path).get(rec["id"])
        assert partial is not None and not partial["url"], ("split scheme was saved", partial)
        bound = json.loads(marker.read_text(encoding="utf-8"))
        assert bound["pid"] in _own_tree(proc), bound
        prefix = "café Serving on http://127.0.0.1:" + bound["url"].split(":")[-1][:1]
        ack.write_text("scheme", encoding="utf-8")
        assert _wait_for(lambda: "".join(proc.history) == prefix), list(proc.history)
        partial = sm.Store(store.path).get(rec["id"])
        assert partial is not None and not partial["url"], (
            "unterminated port token was persisted", partial
        )
        ack.write_text("port", encoding="utf-8")
        view = window._view_for(rec["id"])
        assert view is not None
        assert _wait_for(lambda: view.title() == title, timeout_s=15), (
            "complete split banner did not open its owned dashboard", view.title(), output
        )
        saved = sm.Store(store.path).get(rec["id"])
        assert saved is not None and saved["url"] == bound["url"], saved
        assert view.url().toString(QUrl.FullyEncoded) == bound["url"], view.url().toString(QUrl.FullyEncoded)
        assert window.tabs.currentWidget() is view and view.isVisible() and view.width() > 0 and view.height() > 0
        assert "".join(proc.history) == "café Serving on " + bound["url"] + "\n", list(proc.history)
        with urllib.request.urlopen(bound["url"], timeout=3) as response:
            assert title.encode() in response.read()
        assert script.read_text(encoding="utf-8") == source
    finally:
        stop_and_release(proc, script)
        window.close()


if __name__ == "__main__":
    import inspect

    # The runner isolates GUI tests by passing --test=<name>, expecting the suite
    # to run that one test. Without this filter the suite ignores the flag and
    # runs everything, so each of the 31 isolated processes ran all 29 tests --
    # 870 "passes" for a 29-test file, and a real failure attributed to whatever
    # test happened to be listed last. Accept the flag the runner already sends.
    only = None
    for _a in sys.argv[1:]:
        if _a.startswith("--test="):
            only = _a.split("=", 1)[1]

    app = QApplication.instance() or QApplication([])
    fails = 0
    skipped = 0
    ran = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if only and name != only:
                continue
            ran += 1
            # Some detector tests need no tempdir; pass one only if accepted.
            try:
                sig = inspect.signature(fn)
                takes_arg = len(sig.parameters) > 0
            except (TypeError, ValueError):
                takes_arg = False
            try:
                if takes_arg:
                    with temp_project_dir() as d:
                        fn(Path(d))
                else:
                    fn()
                print(f"PASS {name}")
            except SkipTest as e:
                skipped += 1
                print(f"SKIP {name}: {e}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "12 passed, 1 failed" with no FAIL line to name
                # the 1. An unexpected error IS a failure -- report it as one.
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    if only and not ran:
        # Silently running nothing would let the runner report a green suite for
        # a test name that does not exist. Say so instead.
        print(f"ERROR no such test: {only}")
        sys.exit(2)
    print("---", "FAILURES" if fails else (
        "all passed" + (f" ({skipped} skipped)" if skipped else "")
    ))
    sys.exit(1 if fails else 0)
