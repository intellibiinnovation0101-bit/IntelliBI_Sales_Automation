"""
FastAPI application for the IntelliBI Website Lead Alert service.

Endpoints
  GET  /health              liveness + quick status
  POST /enroll              register a counsellor device -> issues a bearer token
  WS   /ws?token=...        real-time channel (NEW_LEAD / ASSIGNED / EXPIRE in;
                            ACCEPT / OPENED / PING out)
  POST /demo/inject         inject a fake lead to test popups (guarded by the
                            enrollment code) — safe to leave enabled

The WebSocket carries the Accept action too, so a counsellor's client needs only
ONE outbound connection and no separate HTTP client for day-to-day use.
"""
from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

from config import SETTINGS
import store
import counsellors
import ops
import background
from hub import HUB


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = []
    if SETTINGS.enabled:
        tasks.append(asyncio.create_task(background.poll_loop()))
        tasks.append(asyncio.create_task(background.escalation_loop()))
        print("  [service] background loops started")
    else:
        print("  [service] lead_alert.enabled = false — loops NOT started")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="IntelliBI Website Lead Alert", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "online_counsellors": sorted(HUB.online_emails()),
        "active_window": ops.within_active_window(),
        "alert_sections": SETTINGS.alert_sections,
        "seeded": bool(store.meta_get("seed_v2_done")),
        "last_poll": store.meta_get("last_poll_ts"),
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


@app.websocket("/ws")
async def ws(ws: WebSocket):
    token = ws.query_params.get("token", "")
    device = store.device_by_token(token)
    if not device:
        await ws.close(code=4001)
        return
    # Only Active counsellors may connect (deactivated -> refused immediately).
    if not counsellors.is_active_counsellor(device["counsellor_email"]):
        await ws.close(code=4003)
        return

    email = device["counsellor_email"]
    await ws.accept()
    await HUB.register(email, token, ws)
    store.touch_device(token, ops.now_str())

    # Resync: re-send any leads still open for this counsellor (reconnect / restart).
    for lead in store.open_leads_for(email):
        try:
            await ws.send_json({"type": "NEW_LEAD", "lead": ops.lead_public(lead),
                                "resync": True})
            store.mark_delivered(lead["lead_id"], email, ops.now_str())
        except Exception:
            break
    await ws.send_json({"type": "HELLO", "counsellor_name": device["counsellor_name"]})

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "ACCEPT":
                result = await ops.on_accept(device, str(msg.get("lead_id", "")))
                await ws.send_json({"type": "ACCEPT_RESULT", **result})
            elif mtype == "OPENED":
                store.mark_acked(str(msg.get("lead_id", "")), email, ops.now_str())
            elif mtype == "PING":
                store.touch_device(token, ops.now_str())
                await ws.send_json({"type": "PONG"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("  [ws] error:", e)
    finally:
        await HUB.unregister(email, token, ws)
