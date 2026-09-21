"""
WebSocket client with automatic reconnect.

Runs in a background thread, forwards every server event onto a thread-safe queue
(the Tk main loop drains it), and exposes send() for the Accept/Opened/Ping
messages. Reconnects with backoff so a counsellor PC that sleeps, loses Wi-Fi, or
starts before the server simply re-attaches when it can — and the server re-syncs
any still-open leads on reconnect.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse

import websocket   # pip: websocket-client

CONNECTED = "_CONNECTED"
DISCONNECTED = "_DISCONNECTED"


def _ws_url(server_url: str, token: str) -> str:
    u = server_url.strip().rstrip("/")
    if u.lower().startswith("https://"):
        u = "wss://" + u[len("https://"):]
    elif u.lower().startswith("http://"):
        u = "ws://" + u[len("http://"):]
    elif not u.lower().startswith(("ws://", "wss://")):
        u = "ws://" + u
    return f"{u}/ws?token={urllib.parse.quote(token)}"


class WSClient:
    def __init__(self, server_url: str, token: str, out_queue):
        self.url = _ws_url(server_url, token)
        self.q = out_queue
        self._app = None
        self._connected = False
        self._stop = False
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
        backoff = 2
        while not self._stop:
            try:
                self._app = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close)
                self._app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self.q.put({"type": DISCONNECTED, "error": str(e)})
            self._connected = False
            if self._stop:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)      # 2,4,8,16,30,30…

    # ── callbacks ────────────────────────────────────────────────────────────
    def _on_open(self, _app):
        self._connected = True
        self.q.put({"type": CONNECTED})

    def _on_message(self, _app, message):
        try:
            self.q.put(json.loads(message))
        except Exception:
            pass

    def _on_error(self, _app, err):
        self.q.put({"type": DISCONNECTED, "error": str(err)})

    def _on_close(self, _app, *_a):
        self._connected = False
        self.q.put({"type": DISCONNECTED})

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
            time.sleep(25)
            self.send({"type": "PING"})

    @property
    def connected(self) -> bool:
        return self._connected
