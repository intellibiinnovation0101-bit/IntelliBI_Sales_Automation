"""
FastAPI application: the counsellor-facing API + the single web UI.

Endpoints (all JSON except the UI):
    GET  /                 -> the single-page counsellor UI
    GET  /health           -> liveness + sync/queue status (no auth)
    POST /api/login        -> {email,password} -> sets session cookie
    POST /api/logout
    GET  /api/me           -> current counsellor (auth)
    GET  /api/lead?mobile= -> current record + history for a mobile (auth)
    GET  /api/search?q=    -> quick search by mobile/name/email (auth)
    POST /api/save         -> validate + save an update (auth)  [instant ack]
    GET  /api/fields       -> field metadata for the UI (auth)

Reads are served from memory; saves are journaled and acknowledged instantly,
then synced to Google Sheets in the background.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

from . import auth
from .config import (
    Settings, load_settings, ACTIVE_COLUMNS, EDITABLE_FIELDS, DATE_FIELDS,
    MOBILE_COL, TIMESTAMP_COL,
)
from .store import Store
from .sync import SyncWorker
from .sheets_gateway import GspreadGateway
from .web.ui import INDEX_HTML

log = logging.getLogger("counsellor_app")

COOKIE = "ibi_session"


class LoginIn(BaseModel):
    email: str
    password: str


class SaveIn(BaseModel):
    mobile: str
    fields: dict

# Fields rendered as a dropdown in the UI, with their options (kept minimal &
# data-driven; unknown values are still preserved on save).
SELECT_FIELDS = {
    "IsGoogleMeetSchedule": ["", "Yes", "No"],
    "IsWalkInSchedule": ["", "Yes", "No"],
    "Is Referral": ["", "Yes", "No"],
    "Admission Status": ["", "Admitted", "In Progress", "Interested", "Not Interested",
                          "Irrelevant", "Unable To Connect", "Backed Out"],
    "Follow-Up Type": ["", "Call", "WhatsApp", "Email", "Walk-In", "Google Meet"],
}


def create_app(settings: Optional[Settings] = None, gateway=None,
               start_worker: bool = True) -> FastAPI:
    settings = settings or load_settings()
    gateway = gateway or GspreadGateway(settings)
    store = Store(settings, gateway)
    store.bootstrap()
    worker = SyncWorker(settings, store, logger=log)
    if start_worker:
        worker.start()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        worker.stop(flush=True)
        store.close()

    app = FastAPI(title="IntelliBI Counsellor App", docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker

    # -------- helpers --------
    def current_user(request: Request):
        token = request.cookies.get(COOKIE, "")
        email = auth.verify_token(settings, token)
        if not email:
            raise HTTPException(status_code=401, detail="Not logged in.")
        c = settings.counsellor_by_email(email)
        if not c or not c.active:
            raise HTTPException(status_code=401, detail="Account inactive.")
        return c

    # -------- routes --------
    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(INDEX_HTML)

    @app.get("/health")
    def health():
        # "sheet_ok" = the last Google Sheets read succeeded. False means the
        # server is serving from its local snapshot (e.g. it booted while the
        # internet was down) and will resync automatically when the link returns.
        return {
            "status": "ok",
            "leads_cached": store.count(),
            "sheet_ok": bool(getattr(store, "_last_reconcile_ok", True)),
            "booted_from_cache": bool(getattr(store, "booted_from_cache", False)),
            "sync": worker.status(),
        }

    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        ok, msg, c = auth.authenticate(settings, body.email, body.password)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=401)
        token = auth.make_token(settings, c.email)
        response.set_cookie(
            COOKIE, token, httponly=True, samesite="lax",
            max_age=settings.session_hours * 3600,
            secure=bool(os.environ.get("INTELLIBI_APP_SECURE_COOKIE")),
        )
        return {"ok": True, "name": c.name, "role": c.role}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(c=Depends(current_user)):
        return {"email": c.email, "name": c.name, "role": c.role,
                "counselling_by": c.counselling_by}

    @app.get("/api/fields")
    def fields(c=Depends(current_user)):
        return {
            "columns": ACTIVE_COLUMNS,
            "editable": EDITABLE_FIELDS,
            "date_fields": DATE_FIELDS,
            "selects": SELECT_FIELDS,
            "mobile_col": MOBILE_COL,
            "timestamp_col": TIMESTAMP_COL,
        }

    @app.get("/api/lead")
    def lead(mobile: str, c=Depends(current_user)):
        rec = store.get(mobile)
        return {
            "found": rec is not None,
            "record": rec,
            "history": store.history(mobile),
        }

    @app.get("/api/search")
    def search(q: str, c=Depends(current_user)):
        return {"results": store.search(q, limit=20)}

    @app.post("/api/save")
    def save(body: SaveIn, c=Depends(current_user)):
        ok, msg, rec = store.save(body.fields, body.mobile,
                                  counselling_by=c.counselling_by)
        status = 200 if ok else 400
        return JSONResponse({"ok": ok, "message": msg, "record": rec,
                             "pending": worker.status()["pending"]},
                            status_code=status)

    return app
