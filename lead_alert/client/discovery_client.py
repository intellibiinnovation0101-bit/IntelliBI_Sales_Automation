"""
Find the Lead Alert server on the local network when its saved address stops
working (the office PC joined another network / got a new IP).

Broadcasts a small UDP request and accepts ONLY a reply that proves knowledge of
this computer's device token (HMAC), so a stranger on the network cannot pose as
the server. See service/discovery.py for the protocol.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import socket
import time

REQ, REP = b"ILA1?", b"ILA1!"
DEFAULT_PORT = 8788
log = logging.getLogger("leadalert.discovery")


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _proof(token: str, nonce: str, port: int) -> str:
    return hmac.new(token.encode("utf-8"), f"{nonce}|{port}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _broadcast_targets() -> list:
    """255.255.255.255 plus the /24 broadcast of every local IPv4 address
    (Windows sends the limited broadcast on one interface only)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    out = ["255.255.255.255"]
    for ip in ips:
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        out.append(".".join(ip.split(".")[:3] + ["255"]))
    return sorted(set(out))


def discover(token: str, port: int = DEFAULT_PORT, timeout: float = 2.5,
             targets=None):
    """Return 'http://<ip>:<port>' of the verified server, or '' if none answered."""
    nonce = os.urandom(12).hex()
    req = REQ + json.dumps({"id": _token_id(token), "nonce": nonce}).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.3)
        for t in (targets or _broadcast_targets()):
            try:
                sock.sendto(req, (t, port))
            except Exception:
                pass
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception:
                break
            if not data.startswith(REP):
                continue
            try:
                rep = json.loads(data[len(REP):].decode("utf-8"))
                http_port = int(rep["port"])
                ok = hmac.compare_digest(str(rep["proof"]), _proof(token, nonce, http_port))
            except Exception:
                ok = False
            if ok:
                url = f"http://{addr[0]}:{http_port}"
                log.info("server found at %s (%s)", url, rep.get("machine", "?"))
                return url
            log.warning("ignored a discovery reply from %s with an invalid proof", addr[0])
    finally:
        sock.close()
    return ""
