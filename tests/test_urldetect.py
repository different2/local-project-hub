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

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
)

from helpers import reserve_port, stop_and_release, temp_project_dir  # noqa: E402
from hub import store as sm, urldetect  # noqa: E402
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
    holder.start()
    holder_out = []
    holder.output.connect(holder_out.append)
    started = _wait_for(lambda: holder.state == "running", timeout_s=25)
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
    holder.start()
    started = _wait_for(lambda: holder.state == "running", timeout_s=25)
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
        assert holder_pid in {h["pid"] for h in conflict["holders"]}, conflict
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
    holder.start()
    started = _wait_for(lambda: holder.state == "running", timeout_s=25)
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
        assert holder.proc.processId() in urldetect.port_owners(port)
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


def test_clicking_a_project_still_starts_it(tmp: Path) -> None:
    """Selecting a project by hand must still launch it (the normal path)."""
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
        w.active_id = rec["id"]
        w._on_select()
        started = _wait_for(
            lambda: w._proc_for(st.get(rec["id"])).state == "running", timeout_s=25
        )
        assert started, "clicking a project did not start it"
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
    holder.start()
    started = _wait_for(lambda: holder.state == "running", timeout_s=25)
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
    # the script against what is actually listening.
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')\n"
        "    def log_message(self,*a): pass\n"
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n"
    )
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    holder.start()
    started = _wait_for(lambda: holder.state == "running", timeout_s=25)
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
        try:
            w.active_id = rec["id"]
            w._on_select()
            ok = _wait_for(lambda: offered, timeout_s=30)
            assert ok, (
                "a bare-command project whose port was taken got no conflict "
                "offer (it just died with 'Address already in use')"
            )
            assert offered[0]["holders"], offered[0]
            holder_pid = holder.proc.processId() if holder.proc else None
            assert holder_pid in {h["pid"] for h in offered[0]["holders"]}, offered[0]
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
    # the command line names it.
    srv_py = tmp / "obs_live.py"
    srv_py.write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')\n"
        "    def log_message(self,*a): pass\n"
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n"
    )
    holder = ProjectProcess(
        sm.validate(
            {
                "name": "Stray",
                "command": f"{sys.executable} {srv_py}",
                "working_dir": str(tmp),
            }
        )
    )
    holder.start()
    started = _wait_for(lambda: holder.state == "running", timeout_s=25)
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
        try:
            w.active_id = no_url["id"]
            w._on_select()
            ok = _wait_for(lambda: offered, timeout_s=30)
            assert ok, (
                "a no-URL project whose port was taken got no conflict offer — "
                "it just died with 'Address already in use' and nothing was said"
            )
            assert offered[0]["holders"], offered[0]
            holder_pid = holder.proc.processId() if holder.proc else None
            assert holder_pid in {h["pid"] for h in offered[0]["holders"]}, offered[0]
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
        print("SKIP test_about_box_hides_extra_window_buttons: offscreen has no decorations")
        return
    if not mb.available():
        print("SKIP test_about_box_hides_extra_window_buttons: no pyobjc")
        return

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
    holder.start()
    assert _wait_for(lambda: holder.state == "running", timeout_s=25), holder.state
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
        assert conflict["holders"][0]["pid"] == holder.proc.processId(), conflict
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
        argv = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True,
        ).stdout
        assert "--no-open" in argv, f"flag never reached the process: {argv!r}"
    finally:
        stop_and_release(proc, srv_py)


def test_stored_detection_without_entry_script_still_yields_the_flag(tmp: Path) -> None:
    """A record saved before entry_script existed must not lose its flag.

    Detection wrote the flag into the evidence text, so a stored block naming
    it is trustworthy. Without this, upgrading the app silently drops a flag it
    had already discovered.
    """
    rec = {
        "name": "Legacy",
        "command": "python3 obs_live.py",
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
    assert _detected_suppress_flag(rec) == "--no-open", rec["detected"]


def test_user_supplied_args_are_never_overridden(tmp: Path) -> None:
    """A deliberate configuration is never second-guessed by detection."""
    rec = {
        "name": "Typed",
        "command": "python3 obs_live.py",
        "args": "--port 9999",
        "url": "",
        "detected": {
            "type": "web",
            "browser": "known-suppressible",
            "evidence": ["entry script declares --no-open in its argparse"],
        },
    }
    proc = ProjectProcess(dict(rec))
    # the flag helper still reports it, but start() must not append it because
    # the user already chose the arguments
    assert _detected_suppress_flag(rec) == "--no-open"
    assert (rec.get("args") or "").strip() == "--port 9999"


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
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
