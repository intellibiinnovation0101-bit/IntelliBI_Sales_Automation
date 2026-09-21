"""
Real-time connection hub.

Keeps the set of live WebSocket connections per counsellor (a counsellor may be
signed in on more than one device) and provides helpers to push events to a
specific set of counsellors or to everyone. Delivery is best-effort per socket;
a dead socket is dropped and simply re-syncs when it reconnects.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict


class Hub:
    def __init__(self):
        # email(lower) -> set of (websocket, token)
        self._conns = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, email: str, token: str, ws) -> None:
        async with self._lock:
            self._conns[email.lower()].add((ws, token))

    async def unregister(self, email: str, token: str, ws) -> None:
        async with self._lock:
            self._conns[email.lower()].discard((ws, token))
            if not self._conns[email.lower()]:
                self._conns.pop(email.lower(), None)

    def online_emails(self) -> set:
        return set(self._conns.keys())

    def is_online(self, email: str) -> bool:
        return email.lower() in self._conns

    async def send_to_emails(self, emails, payload: dict) -> list:
        """Send payload to every connection of the given emails. Returns the list
        of emails that had at least one live socket receive it."""
        targets = {e.lower() for e in emails}
        reached = []
        async with self._lock:
            items = [(e, list(conns)) for e, conns in self._conns.items()
                     if e in targets]
        for email, conns in items:
            ok = False
            for ws, token in conns:
                try:
                    await ws.send_json(payload)
                    ok = True
                except Exception:
                    await self.unregister(email, token, ws)
            if ok:
                reached.append(email)
        return reached

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            items = [(e, list(conns)) for e, conns in self._conns.items()]
        for email, conns in items:
            for ws, token in conns:
                try:
                    await ws.send_json(payload)
                except Exception:
                    await self.unregister(email, token, ws)


HUB = Hub()
