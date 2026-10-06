"""
Real-time connection hub + PRESENCE.

Keeps every live WebSocket connection (a counsellor may be signed in on more than
one computer) and decides who is genuinely ONLINE:

  online   the connection is open AND the app sent something (PING every 25 s,
           ACCEPT, OPENED...) within SETTINGS.heartbeat_stale_seconds;
  stale    the connection is still registered but has gone silent (laptop
           asleep, Wi-Fi dropped without closing the socket). The sweeper closes
           it, logs it, and the app reconnects on its own when it can;
  offline  no connection. When a counsellor was last seen comes from the
           devices table (store.list_devices).

Only ONLINE connections count for /health, for delivering leads and for the
"no counsellor online" alert, so a dead socket can never make someone look
online, and a reconnect is picked up immediately.

Every transition is logged with counsellor, computer, IP and reason, and the last
rejected connection attempts (unknown computer, inactive counsellor) are kept
for /health. Tokens are never logged.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from config import SETTINGS


def _now() -> float:
    return time.time()


def _ts(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else ""


class Conn:
    __slots__ = ("ws", "token", "email", "name", "machine", "ip", "version",
                 "connected_at", "last_beat")

    def __init__(self, ws, token, email, name, machine, ip, version):
        self.ws, self.token = ws, token
        self.email, self.name, self.machine = email.lower(), name, machine
        self.ip, self.version = ip, version
        self.connected_at = self.last_beat = _now()

    def age_silent(self, now=None) -> float:
        return (now or _now()) - self.last_beat

    def fresh(self, now=None) -> bool:
        return self.age_silent(now) <= SETTINGS.heartbeat_stale_seconds


class Hub:
    def __init__(self):
        self._conns = {}                      # id(ws) -> Conn
        self._lock = asyncio.Lock()
        self.rejections = deque(maxlen=50)    # recent refused connection attempts
        self.started_at = _now()
        self.last_sweep = 0.0
        self._close_reasons = {}              # id(ws) -> why the server closed it

    # ── registration ────────────────────────────────────────────────────────
    async def register(self, email: str, token: str, ws, name: str = "",
                       machine: str = "", ip: str = "", version: str = "") -> Conn:
        c = Conn(ws, token, email, name, machine, ip, version)
        async with self._lock:
            self._conns[id(ws)] = c
        print(f"  [presence] ONLINE  {name or email} <{c.email}> on {machine or '?'} "
              f"from {ip or '?'}{' (app ' + version + ')' if version else ''}"
              f" — online now: {len(self.online_emails())}")
        return c

    async def unregister(self, email: str, token: str, ws, reason: str = "closed") -> None:
        async with self._lock:
            c = self._conns.pop(id(ws), None)
        if c is not None:
            dur = int(_now() - c.connected_at)
            print(f"  [presence] OFFLINE {c.name or c.email} <{c.email}> on "
                  f"{c.machine or '?'} — {reason} after {dur}s"
                  f" — online now: {len(self.online_emails())}")

    def heartbeat(self, ws) -> None:
        c = self._conns.get(id(ws))
        if c is not None:
            c.last_beat = _now()

    def take_close_reason(self, ws) -> str:
        """Why the SERVER closed this connection (e.g. stale), if it did."""
        return self._close_reasons.pop(id(ws), "")

    def reject(self, reason: str, ip: str = "", email: str = "", machine: str = "") -> None:
        self.rejections.append({"at": _ts(_now()), "reason": reason, "ip": ip,
                                "email": email, "machine": machine})
        print(f"  [presence] REFUSED connection from {ip or '?'}"
              f"{' <' + email + '>' if email else ''}: {reason}")

    # ── queries ─────────────────────────────────────────────────────────────
    def online_emails(self) -> set:
        now = _now()
        return {c.email for c in list(self._conns.values()) if c.fresh(now)}

    def is_online(self, email: str) -> bool:
        return (email or "").lower() in self.online_emails()

    def connections(self) -> list:
        """Snapshot of every registered connection (fresh or not), no tokens."""
        now = _now()
        return [{"email": c.email, "name": c.name, "machine": c.machine, "ip": c.ip,
                 "app_version": c.version, "connected_since": _ts(c.connected_at),
                 "last_heartbeat": _ts(c.last_beat),
                 "silent_seconds": int(c.age_silent(now)),
                 "state": "online" if c.fresh(now) else "stale"}
                for c in list(self._conns.values())]

    def in_startup_grace(self) -> bool:
        return _now() - self.started_at < SETTINGS.startup_grace_seconds

    def sweeper_healthy(self) -> bool:
        """True when the stale-connection sweeper ran recently (the presence
        monitor itself is working)."""
        return _now() - self.last_sweep <= max(60, 4 * SETTINGS.presence_sweep_seconds)

    # ── stale sweeper ───────────────────────────────────────────────────────
    async def sweep(self) -> list:
        """Close connections that stopped sending heartbeats. Returns the emails
        that were dropped."""
        now = _now()
        self.last_sweep = now
        stale = [c for c in list(self._conns.values()) if not c.fresh(now)]
        dropped = []
        for c in stale:
            silent = int(c.age_silent(now))
            why = f"STALE (no heartbeat for {silent}s)"
            self._close_reasons[id(c.ws)] = why
            try:
                await c.ws.close(code=4008)     # app reconnects by itself
            except Exception:
                pass
            await self.unregister(c.email, c.token, c.ws, reason=why)
            dropped.append(c.email)
        return dropped

    # ── delivery ────────────────────────────────────────────────────────────
    async def send_to_emails(self, emails, payload: dict) -> list:
        """Send payload to every ONLINE connection of the given emails. Returns
        the emails that had at least one connection accept it."""
        targets = {(e or "").lower() for e in emails}
        now = _now()
        conns = [c for c in list(self._conns.values())
                 if c.email in targets and c.fresh(now)]
        reached = set()
        for c in conns:
            try:
                await c.ws.send_json(payload)
                reached.add(c.email)
            except Exception as e:
                await self.unregister(c.email, c.token, c.ws, reason=f"send failed: {e}")
        return sorted(reached)

    async def broadcast(self, payload: dict) -> None:
        now = _now()
        for c in [c for c in list(self._conns.values()) if c.fresh(now)]:
            try:
                await c.ws.send_json(payload)
            except Exception as e:
                await self.unregister(c.email, c.token, c.ws, reason=f"send failed: {e}")


HUB = Hub()
