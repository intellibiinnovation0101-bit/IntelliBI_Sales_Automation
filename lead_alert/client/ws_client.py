"""
WebSocket client with automatic reconnect, heartbeat watchdog and clear status.

Runs in a background thread, forwards every server event onto a thread-safe queue
(the Tk main loop drains it), and exposes send() for the Accept/Opened/Ping
messages.

Status events put on the queue (besides the server's own messages):
  _CONNECTED                      connected and authenticated
  _DISCONNECTED  {kind, error}    kind = "unreachable" (network / firewall / wrong
                                  server address) or "dropped" (was connected)
  _AUTH_FAILED   {reason, ...}    the server REFUSED this computer: not registered
                                  on this server, or counsellor not Active. Retried
                                  only every 5 minutes; the app asks to re-register.

Heartbeat: the app sends PING every 25 s and expects traffic back. If nothing
arrives for 70 s the connection is treated as dead (half-open after sleep or a
Wi-Fi drop) and is reconnected. Reconnect backoff 2,4,8,16,30,30... seconds,
reset after every healthy connection.

The device token is sent in the Authorization header, never in the URL, so it
cannot end up in server or proxy logs.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import websocket   # pip: websocket-client

CONNECTED = "_CONNECTED"
DISCONNECTED = "_DISCONNECTED"
AUTH_FAILED = "_AUTH_FAILED"
SERVER_MOVED = "_SERVER_MOVED"     # {url}: server found at a new address (saved)

PING_EVERY = 25           # seconds between app-level PINGs
DEAD_AFTER = 70           # no traffic for this long -> reconnect
AUTH_RETRY = 300          # retry interval after the server refused this computer
DISCOVER_AFTER = 2        # failed attempts to the saved address before searching
DISCOVER_EVERY = 60       # seconds between LAN searches while unreachable
DISCOVERY_TARGETS = None  # None = broadcast on every local network (tests override)

log = logging.getLogger("leadalert.ws")


def _ws_url(server_url: str) -> str:
    u = server_url.strip().rstrip("/")
    if u.lower().startswith("https://"):
        u = "wss://" + u[len("https://"):]
    elif u.lower().startswith("http://"):
        u = "ws://" + u[len("http://"):]
    elif not u.lower().startswith(("ws://", "wss://")):
        u = "ws://" + u
    return f"{u}/ws"


class WSClient:
    def __init__(self, server_url: str, token: str, out_queue, version: str = "",
                 discovery_port: int = 8788):
        self.server_url = server_url
        self.token = token
        self.discovery_port = discovery_port
        self._fails = 0
        self._last_discover = 0.0
        self.url = _ws_url(server_url)
        self.headers = [f"Authorization: Bearer {token}"]
        if version:
            self.headers.append(f"X-Client-Version: {version}")
        self.q = out_queue
        self._app = None
        self._connected = False
        self._stop = False
        self._backoff = 2
        self._auth_failed = False
        self._was_connected = False
        self._last_rx = 0.0
        self._lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def stop(self):
        self._stop = True
        try:
            if self._app:
                self._app.close()
        except Exception:
            pass

    def _run(self):
        self._backoff = 2
        while not self._stop:
            self._auth_failed = False
            self._was_connected = False
            self._down_reported = False
            try:
                self._app = websocket.WebSocketApp(
                    self.url, header=self.headers,
                    on_open=self._on_open, on_message=self._on_message,
                    on_error=self._on_error, on_close=self._on_close)
                self._app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self._report_down(str(e))
            self._connected = False
            if self._stop:
                break
            if self._was_connected or self._auth_failed:
                self._fails = 0
            else:
                self._fails += 1
                if self._maybe_discover():
                    continue                     # new address -> connect right away
            wait = AUTH_RETRY if self._auth_failed else self._backoff
            time.sleep(wait)
            if not self._auth_failed:
                self._backoff = min(self._backoff * 2, 30)   # 2,4,8,16,30,30…

    def _maybe_discover(self) -> bool:
        """Saved address unreachable: look for the server on the local network
        (it may have a new IP). Returns True when it moved."""
        if self._fails < DISCOVER_AFTER or time.time() - self._last_discover < DISCOVER_EVERY:
            return False
        self._last_discover = time.time()
        try:
            from discovery_client import discover
            found = discover(self.token, self.discovery_port, targets=DISCOVERY_TARGETS)
        except Exception as e:
            log.warning("discovery failed: %s", e)
            return False
        if not found:
            log.warning("server not found on the local network (UDP %s)", self.discovery_port)
            return False
        if _ws_url(found) == self.url:
            return False
        log.warning("server moved: %s -> %s", self.server_url, found)
        self.server_url, self.url = found, _ws_url(found)
        self._fails, self._backoff = 0, 2
        self.q.put({"type": SERVER_MOVED, "url": found})
        return True

    # ── callbacks ────────────────────────────────────────────────────────────
    def _on_open(self, _app):
        self._last_rx = time.time()
        log.info("socket open to %s", self.url)

    def _on_message(self, _app, message):
        self._last_rx = time.time()
        try:
            msg = json.loads(message)
        except Exception:
            return
        t = msg.get("type")
        if t == "AUTH_FAILED":
            self._auth(msg.get("reason", "refused"), msg.get("message", ""))
            return
        if not self._connected:          # first message = accepted by the server
            self._connected = True
            self._was_connected = True
            self._backoff = 2          # healthy connection -> fast reconnect next time
            log.info("connected and authenticated")
            self.q.put({"type": CONNECTED})
        self.q.put(msg)

    def _on_error(self, _app, err):
        status = getattr(err, "status_code", None)
        if status in (401, 403):       # server older than 2026-10-06 refuses with HTTP 403
            self._auth("not_registered", f"HTTP {status}")
            return
        self._report_down(str(err))

    def _on_close(self, _app, code=None, reason=None):
        if code in (4001, 4003):
            self._auth("not_registered" if code == 4001 else "inactive", f"close {code}")
        elif code == 4008:
            log.warning("server closed the connection: heartbeat timeout")
        was = self._connected
        self._connected = False
        if was and not self._auth_failed:
            self._report_down(f"connection closed (code {code})")

    def _auth(self, reason: str, detail: str = ""):
        if not self._auth_failed:
            log.error("server REFUSED this computer: %s %s", reason, detail)
            self.q.put({"type": AUTH_FAILED, "reason": reason, "detail": detail})
        self._auth_failed = True
        self._connected = False

    def _report_down(self, error: str):
        # A refusal is reported as AUTH_FAILED only; one report per attempt.
        if self._auth_failed or getattr(self, "_down_reported", False):
            return
        self._down_reported = True
        kind = "dropped" if self._was_connected else "unreachable"
        log.warning("%s: %s (url %s)", kind, error, self.url)
        self.q.put({"type": DISCONNECTED, "kind": kind, "error": error})

    # ── outbound ─────────────────────────────────────────────────────────────
    def send(self, msg: dict) -> bool:
        with self._lock:
            if not (self._connected and self._app):
                return False
            try:
                self._app.send(json.dumps(msg))
                return True
            except Exception:
                self._connected = False
                return False

    def _ping_loop(self):
        while not self._stop:
            time.sleep(PING_EVERY)
            if self._connected:
                if time.time() - self._last_rx > DEAD_AFTER:
                    log.warning("no reply from server for %ss — reconnecting", DEAD_AFTER)
                    try:
                        self._app.close()        # run_forever returns -> reconnect
                    except Exception:
                        pass
                    continue
                self.send({"type": "PING"})

    @property
    def connected(self) -> bool:
        return self._connected
