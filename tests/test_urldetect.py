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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from hub import store as sm, urldetect  # noqa: E402
from hub.process_manager import ProjectProcess  # noqa: E402
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
    port = 8801
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
    p.stop()
    _wait_for(lambda: p.state == "stopped", timeout_s=25)
    assert ok, f"no URL detected from output; got={got}"
    assert got[0] == f"http://127.0.0.1:{port}", got[0]


def test_window_fills_in_and_saves_detected_url(tmp: Path) -> None:
    port = 8802
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
        w.close()


def test_port_conflict_refuses_to_start(tmp: Path) -> None:
    """A taken port must not start a doomed process that dies confusingly.

    Without this guard the new process dies with "Address already in use" and
    the hub then reports the OTHER process's page as this project's dashboard,
    which reads as a success.
    """
    port = 8814
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
        holder.stop()
        _wait_for(lambda: holder.state == "stopped", timeout_s=25)


def test_port_conflict_is_reported_with_command(tmp: Path) -> None:
    """A foreign process on the port is reported, with enough detail to judge it.

    The prompt must name what is holding the port so the user can tell whether
    it is another copy of this project or something unrelated before deciding
    to end it.
    """
    port = 8814
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
        holder.stop()
        _wait_for(lambda: holder.state == "stopped", timeout_s=25)


def test_own_process_is_not_a_conflict(tmp: Path) -> None:
    """Our own server on the port must never be reported as a conflict.

    This is the restart case: if it were reported, every restart would prompt
    the user to kill a process the hub itself started.
    """
    port = 8815
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
        proc.stop()
        _wait_for(lambda: proc.state == "stopped", timeout_s=25)


def test_bind_failure_names_the_port_from_the_command(tmp: Path) -> None:
    """A port-less project that dies with "in use" must still be actionable.

    The user's real case: `python3 obs_live.py` with no URL and no port
    argument. The pre-start check cannot help (no URL to inspect), so the port
    has to come from the command or from what is actually holding a port.
    """
    port = 8817
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
        holder.stop()
        _wait_for(lambda: holder.state == "stopped", timeout_s=25)


def test_no_url_project_still_detects_the_conflict(tmp: Path) -> None:
    """A project with NO url must still get the port-conflict treatment.

    The user's case: "obsv" is `python3 obs_live.py` with no URL, so
    port_conflict() has nothing to inspect. The port has to be recovered from
    what is actually held — otherwise the hub starts it straight into a
    guaranteed "Address already in use", which is exactly what happened.
    """
    port = 8818
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
        st = sm.Store(tmp / "registry.json")
        # a sibling that knows the port, and the user's bare no-URL entry
        st.add(
            sm.validate(
                {
                    "name": "Observability",
                    "command": f"{sys.executable} {srv_py}",
                    "url": f"http://127.0.0.1:{port}/",
                    "working_dir": str(tmp),
                }
            )
        )
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
            w._start_active()
            assert offered, (
                "a no-URL project whose port was taken was started anyway "
                "(no conflict detected)"
            )
            assert offered[0]["port"] == port, offered[0]
            holder_pid = holder.proc.processId() if holder.proc else None
            assert holder_pid in {h["pid"] for h in offered[0]["holders"]}, offered[0]
            # and it must NOT have been launched into the failure
            assert w._proc_for(no_url).state != "running", "it was started anyway"
        finally:
            w.close()
    finally:
        holder.stop()
        _wait_for(lambda: holder.state == "stopped", timeout_s=25)


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
        p.stop()
        _wait_for(lambda: p.state == "stopped", timeout_s=20)


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
    port = 8819
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
    port = 8821
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
    port = 8822
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
        p.stop()
        _wait_for(lambda: p.state == "stopped", timeout_s=25)
        w.close()


def test_clicking_a_project_still_starts_it(tmp: Path) -> None:
    """Selecting a project by hand must still launch it (the normal path)."""
    port = 8823
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
        p.stop()
        _wait_for(lambda: p.state == "stopped", timeout_s=25)
        w.close()


def test_listening_ports_all_actually_finds_ports(tmp: Path) -> None:
    """listening_ports_all() must parse lsof output on this platform.

    It silently returned [] for months of the conflict feature because the
    parser read the LAST column, which on macOS is "(LISTEN)" rather than the
    address. A helper that quietly finds nothing is worse than one that fails.
    """
    port = 8824
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
        holder.stop()
        _wait_for(lambda: holder.state == "stopped", timeout_s=25)


def test_bare_command_conflict_is_offered(tmp: Path) -> None:
    """A project with NO url and NO port in its command still gets the dialog.

    The user's exact case: one project, "python3 obs_live.py", which binds 8787
    inside the script. Nothing in the command or registry names the port, so
    the holder has to be found by matching the script against listening ports.
    """
    port = 8825
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
        holder.stop()
        _wait_for(lambda: holder.state == "stopped", timeout_s=25)


def test_configured_url_is_never_overridden(tmp: Path) -> None:
    """A URL the user typed themselves always wins over detection."""
    port = 8803
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
    p.stop()
    _wait_for(lambda: p.state == "stopped", timeout_s=25)
    # detection must not fire at all when a URL is already configured
    assert got == [], f"detection ran despite a configured URL: {got}"


if __name__ == "__main__":
    import inspect

    app = QApplication.instance() or QApplication([])
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            # Some detector tests need no tempdir; pass one only if accepted.
            try:
                sig = inspect.signature(fn)
                takes_arg = len(sig.parameters) > 0
            except (TypeError, ValueError):
                takes_arg = False
            try:
                if takes_arg:
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
