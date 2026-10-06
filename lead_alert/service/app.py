"""
FastAPI application for the IntelliBI Website Lead Alert service.

Endpoints
  GET  /health              status, who is online / stale / offline / not
                            registered, network self-check, 1-hour offline
                            monitor, recent refused connections, warnings
  POST /enroll              register a counsellor device -> issues a bearer token
  WS   /ws                  real-time channel; token in "Authorization: Bearer"
                            (apps before 2026-10-06: ?token=..., still accepted
                            and redacted from logs)
  POST /demo/inject         inject a fake lead to test popups (guarded by the
                            enrollment code)
  UDP  discovery_port       LAN discovery so apps find the server after an IP
                            change (service/discovery.py)

Reliability (see lead_alert/PRESENCE_AND_ALERTS.md): heartbeat-based presence
with a stale sweeper, firewall/network self-check with auto-repair, LAN
discovery, reconnect resync of open leads, the "all counsellors offline for 1
hour" e-mail, and a STANDBY role for any PC that is not lead_alert.server_machine.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

from config import SETTINGS
import store
import counsellors
import ops
import background
from hub import HUB
import netcheck
import discovery


# ── never write device tokens to the log ─────────────────────────────────────
# uvicorn logs every request path, and older counsellor apps put the token in
# the WebSocket URL (?token=...). Redact it before it reaches the log file.
_TOKEN_RE = re.compile(r"(token=)[^&\s\"']+")


class _RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if "token=" in msg:
            record.msg, record.args = _TOKEN_RE.sub(r"\1***", msg), ()
        return True


for _name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
    logging.getLogger(_name).addFilter(_RedactTokens())


def _this_machine() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def is_primary() -> bool:
    """True when this computer is the configured server (or none is configured)."""
    want = SETTINGS.server_machine
    return not want or want.lower() == _this_machine().lower()


@asynccontextmanager
async def lifespan(app: FastAPI):
    HUB.started_at = time.time()
    tasks = [asyncio.create_task(background.presence_loop())]
    print(f"  [service] presence: online = heartbeat within "
          f"{SETTINGS.heartbeat_stale_seconds}s; sweep every "
          f"{SETTINGS.presence_sweep_seconds}s; startup grace "
          f"{SETTINGS.startup_grace_seconds}s")
    if not SETTINGS.server_machine:
        print("  [service] NOTE: lead_alert.server_machine is not set — any computer "
              "that starts this service will poll the sheet and send e-mails.")
    if not SETTINGS.enabled:
        print("  [service] lead_alert.enabled = false — poller/escalation NOT started")
    elif not is_primary():
        print(f"  [service] STANDBY: this computer is {_this_machine()!r}, the "
              f"configured server is {SETTINGS.server_machine!r} — not polling the "
              f"sheet or sending e-mails here.")
    else:
        tasks.append(asyncio.create_task(background.poll_loop()))
        tasks.append(asyncio.create_task(background.escalation_loop()))
        if SETTINGS.offline_alert_enabled:
            tasks.append(asyncio.create_task(background.offline_alert_loop()))
        print("  [service] background loops started")
    if SETTINGS.netcheck_minutes > 0:
        tasks.append(asyncio.create_task(background.netcheck_loop()))
    udp = None
    if SETTINGS.discovery_port > 0:
        try:
            udp = await discovery.serve(store.active_tokens, SETTINGS.discovery_port,
                                        SETTINGS.port)
        except Exception as e:
            print(f"  [discovery] could not listen on UDP {SETTINGS.discovery_port}: {e}")
    urls = [f"http://{ip}:{SETTINGS.port}" for ip in discovery.local_ipv4s()]
    print(f"  [service] counsellor apps connect to: {', '.join(urls) or '(no network)'}")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        if udp is not None:
            udp.close()


app = FastAPI(title="IntelliBI Website Lead Alert", lifespan=lifespan)


@app.get("/health")
async def health():
    pres = ops.presence_report()
    online = sorted(HUB.online_emails())
    net = dict(netcheck.LAST)
    warnings = []
    if net.get("ok") is False:
        warnings.append(net.get("summary", ""))
    warnings.extend(net.get("warnings") or [])
    if not online and not HUB.in_startup_grace():
        not_reg = [c["email"] for c in pres["counsellors"] if c["state"] == "not_registered"]
        if not_reg:
            warnings.append("not registered on this server: " + ", ".join(not_reg))
    if not HUB.sweeper_healthy() and not HUB.in_startup_grace():
        warnings.append("presence sweeper is not running")
    return {
        "status": "ok" if not warnings else "degraded",
        "online_counsellors": online,
        "active_window": ops.within_active_window(),
        "alert_sections": SETTINGS.alert_sections,
        "seeded": bool(store.meta_get("seed_v2_done")),
        "last_poll": store.meta_get("last_poll_ts"),
        "server": {"machine": _this_machine(),
                   "urls": [f"http://{ip}:{SETTINGS.port}" for ip in discovery.local_ipv4s()],
                   "role": ("primary" if is_primary() else "standby"),
                   "started_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(HUB.started_at)),
                   "in_startup_grace": HUB.in_startup_grace()},
        "network": net,
        "offline_alert": dict(background.offline_monitor().status(datetime.now()),
                              enabled=SETTINGS.offline_alert_enabled,
                              window=background.offline_window_text()),
        "presence": pres,
        "recent_refused_connections": list(HUB.rejections)[-10:],
        "warnings": warnings,
    }


@app.post("/enroll")
async def enroll(req: Request):
    body = await req.json()
    email = str(body.get("email", "")).strip()
    code = str(body.get("code", "")).strip()
    machine = str(body.get("machine", "")).strip()

    expected = SETTINGS.enrollment_code()
    if not expected or not secrets.compare_digest(code, expected):
        return JSONResponse({"error": "invalid enrollment code"}, status_code=403)

    match = next((r for r in counsellors.active_recipients()
                  if r["email"].lower() == email.lower()), None)
    if not match:
        return JSONResponse(
            {"error": "email is not an Active counsellor in counsellors.json"},
            status_code=403)

    token = secrets.token_urlsafe(32)
    store.add_device(token, match["email"], match["name"], machine, ops.now_str())
    print(f"  [enroll] {match['name']} <{match['email']}> on {machine!r}")
    return {"token": token, "counsellor_name": match["name"],
            "counsellor_email": match["email"]}


@app.post("/demo/inject")
async def demo_inject(req: Request):
    body = await req.json()
    if not secrets.compare_digest(str(body.get("code", "")),
                                  SETTINGS.enrollment_code() or "\0"):
        return JSONResponse({"error": "invalid code"}, status_code=403)
    row = {
        "_row": 1_000_000 + secrets.randbelow(900000),   # unique fake row id
        "name": body.get("name", "Test Lead"),
        "mobile": body.get("mobile", "9999999999"),
        "email": body.get("email", "test@example.com"),
        "course": body.get("course", "Data Science"),
        "current_role": body.get("current_role", ""),
        "message": body.get("message", "This is a demo Website Lead."),
        "form_type": body.get("form_type", "Program Enquiry"),
        "enquiry_date": ops.now_str(),
    }
    lead = ops.build_lead_from_row(row)
    await ops.dispatch_lead(lead)
    return {"injected": lead["lead_id"]}


def _client_ip(ws: WebSocket) -> str:
    try:
        return ws.client.host if ws.client else ""
    except Exception:
        return ""


def _token_from(ws: WebSocket) -> str:
    """Bearer token from the Authorization header (current app) or the ?token=
    query (apps built before 2026-10-06 — still accepted)."""
    auth = ws.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ws.query_params.get("token", "")


@app.websocket("/ws")
async def ws(ws: WebSocket):
    ip = _client_ip(ws)
    token = _token_from(ws)
    version = ws.headers.get("x-client-version", "") or ws.query_params.get("v", "")
    # Accept first, so a refused app gets a clear reason instead of a bare HTTP 403.
    await ws.accept()
    device = store.device_by_token(token) if token else None
    if not device:
        HUB.reject("unknown computer — not registered on THIS server "
                   "(re-register the app)", ip=ip)
        await ws.send_json({"type": "AUTH_FAILED", "reason": "not_registered",
                            "message": "This computer is not registered on the Lead "
                                       "Alert server. Please re-register."})
        await ws.close(code=4001)
        return
    email = device["counsellor_email"]
    # Only Active counsellors may connect (deactivated -> refused immediately).
    if not counsellors.is_active_counsellor(email):
        HUB.reject("counsellor is not Active in counsellors.json", ip=ip,
                   email=email, machine=device.get("machine") or "")
        await ws.send_json({"type": "AUTH_FAILED", "reason": "inactive",
                            "message": f"{email} is not an Active counsellor."})
        await ws.close(code=4003)
        return

    name = counsellors.name_for_email(email) or device["counsellor_name"]
    conn = await HUB.register(email, token, ws, name=name,
                              machine=device.get("machine") or "", ip=ip,
                              version=version)
    store.device_connected(token, ip, ops.now_str(), version)
    reason = "closed"
    try:
        # Resync: every lead still waiting for a counsellor is shown again
        # (reconnect after a network drop, app/PC/server restart).
        await ops.resync_open_leads(ws, email, name)
        await ws.send_json({"type": "HELLO", "counsellor_name": name})
        while True:
            msg = await ws.receive_json()
            HUB.heartbeat(ws)                       # any message = alive
            mtype = msg.get("type")
            if mtype == "ACCEPT":
                result = await ops.on_accept(device, str(msg.get("lead_id", "")))
                await ws.send_json({"type": "ACCEPT_RESULT", **result})
            elif mtype == "OPENED":
                store.mark_acked(str(msg.get("lead_id", "")), email, ops.now_str())
            elif mtype == "PING":
                store.touch_device(token, ops.now_str())
                await ws.send_json({"type": "PONG"})
    except WebSocketDisconnect as e:
        reason = f"app disconnected (code {getattr(e, 'code', '?')})"
    except Exception as e:
        reason = f"connection error: {e}"
    finally:
        reason = HUB.take_close_reason(ws) or reason
        await HUB.unregister(email, token, ws, reason=reason)
        store.device_disconnected(token, ops.now_str(), reason)
