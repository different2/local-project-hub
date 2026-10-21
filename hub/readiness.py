"""Readiness checks: does a project's dashboard actually answer yet?

Two-phase check, because different servers bind at different speeds:

  1. TCP  — cheapest; tells us the port is open.
  2. HTTP — an actual GET of the dashboard URL; ANY HTTP status (even 404/500)
     counts as "serving". This matters for servers like this user's obs_live.py,
     which bind the port but take seconds to build their index, so a TCP pass
     alone would show a blank page.

Everything is async on the Qt event loop (QNetworkAccessManager), so the hub's
window never blocks while a project boots.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


def tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def url_host_port(url: str) -> tuple[str, int]:
    p = urlparse(url)
    host = p.hostname or "127.0.0.1"
    port = p.port or (443 if p.scheme == "https" else 80)
    return host, port


class ReadinessWaiter(QObject):
    """Polls a project's URL until it answers, then emits `ready`.

    Strategy: HTTP GET (cheap, takes priority); if the port is not even open
    yet, fall back to a TCP poll so we still fire as soon as the port binds,
    without hammering the server with doomed GETs.

    Signals:
        ready()                  URL answered with any HTTP status
        failed(reason: str)      gave up (timeout)
    """

    ready = Signal()
    failed = Signal(str)

    def __init__(self, url: str, timeout_ms: int = 30000, parent=None):
        super().__init__(parent)
        self.url = url
        self.timeout_ms = timeout_ms
        self._host = ""
        self._port = 0
        self._nam = QNetworkAccessManager(self)
        self._inflight: QNetworkReply | None = None
        # Set once a terminal outcome (ready/failed/cancelled) has been
        # produced, so late replies and timers cannot emit a second outcome.
        self._settled = False
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.setInterval(timeout_ms)
        self._deadline.timeout.connect(self._on_timeout)
        self._tcp_poll = QTimer(self)
        self._tcp_poll.setInterval(500)
        self._tcp_poll.timeout.connect(self._tcp_tick)

    def start(self) -> None:
        if not self.url:
            self._settled = True
            self.failed.emit("no dashboard URL configured")
            return
        self._settled = False
        self._host, self._port = url_host_port(self.url)
        self._deadline.start()
        if tcp_open(self._host, self._port):
            self._http_try()
        else:
            self._tcp_poll.start()

    def stop(self) -> None:
        """Cancel polling and settle this waiter without emitting anything.

        Callers use it to abandon a project (tab closed, project removed,
        window shutting down); the deadline and any in-flight reply are torn
        down so nothing can fire afterwards.
        """
        self._settled = True
        self._tcp_poll.stop()
        self._deadline.stop()
        if self._inflight is not None:
            try:
                self._inflight.abort()
            except RuntimeError:
                pass  # already deleted
            self._inflight = None

    # ---------- phases ----------

    def _tcp_tick(self) -> None:
        if self._settled:
            self._tcp_poll.stop()
            return
        if tcp_open(self._host, self._port):
            self._tcp_poll.stop()
            self._http_try()

    def _http_try(self) -> None:
        if self._settled or self._inflight is not None:
            return
        req = QNetworkRequest(QUrl(self.url))
        req.setMaximumRedirectsAllowed(4)
        req.setTransferTimeout(3000)
        self._inflight = self._nam.get(req)
        self._inflight.finished.connect(self._http_done)

    def _http_done(self) -> None:
        reply = self._inflight
        self._inflight = None
        if reply is None:
            return
        try:
            if self._settled:
                return
            http_status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            was_transport_error = (
                reply.error() != QNetworkReply.NoError
                and http_status is None
            )
            if was_transport_error:
                # A reset/refused/empty reply is not the end of the check: the
                # server may simply not be up yet. Re-arm the poll so another
                # HTTP attempt happens before the deadline. The previous code
                # returned here after the TCP poll had already been stopped,
                # so one transient error ended all retries and the project was
                # reported as unready even though it answered moments later.
                if not self._settled:
                    self._tcp_poll.start()
                return
            # Any HTTP status (even 404/500) means the server is serving.
            self.stop()
            self.ready.emit()
        finally:
            try:
                reply.deleteLater()
            except RuntimeError:
                pass

    def _on_timeout(self) -> None:
        if self._settled:
            return
        self.stop()
        self.failed.emit(
            f"{self.url} did not respond within {self.timeout_ms // 1000}s"
            " — check the project's logs"
        )
