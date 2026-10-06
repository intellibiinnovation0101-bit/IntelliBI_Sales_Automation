"""
LAN discovery: lets counsellor apps FIND the server when its address changes.

The office PC gets a different IP whenever it joins another network (or DHCP
hands out a new address). Apps registered with the old address would otherwise
retry it forever. Instead, when an app cannot reach its saved address, it sends
a small UDP broadcast on the local network; this service answers so the app can
switch to the server's current address by itself.

Security: the app includes a short hash of its device token and a random nonce.
The service answers only for a registered, active computer, and proves it is the
real server with HMAC-SHA256(token, nonce|port). A device that does not know the
token cannot produce the proof, so it cannot lure apps (or their tokens) away.
Nothing secret is ever sent in clear.

Wire format (UDP, port lead_alert.discovery_port, default 8788):
  request  b"ILA1?" + JSON {"id": sha256(token)[:16], "nonce": "<hex>"}
  reply    b"ILA1!" + JSON {"port": 8787, "machine": "<name>", "proof": "<hex>"}
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import socket
import time

REQ, REP = b"ILA1?", b"ILA1!"


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def proof(token: str, nonce: str, port: int) -> str:
    return hmac.new(token.encode("utf-8"), f"{nonce}|{port}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def build_reply(data: bytes, tokens, port: int, machine: str):
    """Pure: the reply bytes for a request, or None (ignored). `tokens` is an
    iterable of the active device tokens."""
    if not data.startswith(REQ) or len(data) > 512:
        return None
    try:
        req = json.loads(data[len(REQ):].decode("utf-8"))
        tid, nonce = str(req["id"]), str(req["nonce"])
    except Exception:
        return None
    if not (8 <= len(nonce) <= 64):
        return None
    for tok in tokens:
        if hmac.compare_digest(token_id(tok), tid):
            return REP + json.dumps({"port": port, "machine": machine,
                                     "proof": proof(tok, nonce, port)}).encode("utf-8")
    return None


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, tokens_fn, port, machine):
        self.tokens_fn, self.port, self.machine = tokens_fn, port, machine
        self.transport = None
        self._recent = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        now = time.time()
        self._recent = [t for t in self._recent if now - t < 1.0]
        if len(self._recent) > 50:                 # flood guard
            return
        self._recent.append(now)
        try:
            rep = build_reply(data, self.tokens_fn(), self.port, self.machine)
        except Exception as e:
            print("  [discovery] error:", e)
            return
        if rep is not None:
            self.transport.sendto(rep, addr)
            print(f"  [discovery] answered app at {addr[0]} (server moved/started?)")


async def serve(tokens_fn, udp_port: int, http_port: int):
    """Listen for discovery broadcasts. Returns the transport (close on exit)."""
    loop = asyncio.get_running_loop()
    machine = socket.gethostname()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _Proto(tokens_fn, http_port, machine),
        local_addr=("0.0.0.0", udp_port), allow_broadcast=True)
    print(f"  [discovery] listening on UDP {udp_port} (apps find this server "
          f"automatically if its address changes)")
    return transport


def local_ipv4s() -> list:
    """This computer's IPv4 addresses (no external traffic is sent)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))           # picks the primary interface
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))
