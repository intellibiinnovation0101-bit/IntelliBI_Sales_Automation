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

# ---------------------------------------------------------------------------
# Dropdown fields — kept in step with the Google Sheet form automatically.
#
# The form presents these fields as dropdowns (data-validation lists). The app
# must offer the SAME options, spelled exactly the same way, so that what a
# counsellor picks here is a valid option on the form and in every report.
#
# The lists below are the BASE options, confirmed against the live form / Data
# sheet. At runtime the app adds every value that actually appears in the sheet
# for that field (Active + history) and, for "Counselling By", every configured
# counsellor — so a new option added on the form shows up here as soon as it is
# used, with no code change. Where the sheet's text differs only by case or
# spacing from a base entry, the sheet's exact text wins (the sheet is the
# source of truth). Free-text fields (notes, city, company, names, numbers) are
# deliberately NOT listed here.
# ---------------------------------------------------------------------------
YES_NO = ["Yes", "No"]
SELECT_FIELDS_BASE = {
    "Candidate Type": ["Working Professional - IT", "Working Professional - Non IT",
                       "Student - Pursuing", "Fresher - Passed Out", "Career Break",
                       "Unidentified"],
    "Total Years of Experience": ["Fresher (0 Years)", "0–1 Year", "1–2 Years",
                                  "2–3 Years", "3–5 Years", "5–7 Years",
                                  "7–10 Years", "10–15 Years", "15+ Years"],
    "Current Domain / Technology": ["Support-IT", "Development - Data/ETL", "Other"],
    "Course Interested In": ["Azure Data Engineering", "Azure Data Engineering with GenAI",
                             "Data Analytics with GenAI",
                             "Advanced Artificial Intelligence (AI) with Generative AI + "
                             "Agentic AI + Machine Learning(ML)", "Other"],
    "Career Goal": ["Get Job", "Job Switch", "Salary Hike", "Upskilling", "Project Requirement"],
    "Admission Plan Time": ["Immediately (Within 1 Week)", "Within 15 Days",
                            "Just Exploring Options"],
    "Highest Qualification": ["BA / B.Com", "BCA / BCS", "B.E. (IT, Computer)", "MBA / PGDM"],
    "IsGoogleMeetSchedule": YES_NO,
    "IsWalkInSchedule": YES_NO,
    "Is Referral": YES_NO,
    "Admission Status": ["Follow-up Pending", "Not Interested", "Unable to Connect",
                         "Irrelevant"],
    "BackOutReason": ["No Response", "Course Not Available", "Other"],
    "Follow-Up Type": ["Initial Follow-Up"],
    "Counselling By": [],            # filled from the sheet + configured counsellors
}

# Kept for callers/tests that import the old name: the base lists (no runtime union).
SELECT_FIELDS = {k: [""] + list(v) for k, v in SELECT_FIELDS_BASE.items()}


def _norm_opt(s) -> str:
    return " ".join(str(s or "").split()).lower()


def build_select_options(store, settings) -> dict:
    """{field: ["", option, ...]} — base options, then every value seen in the
    sheet for that field (sheet spelling wins), then configured counsellors for
    Counselling By. Extras are appended alphabetically so the list is tidy."""
    seen_in_sheet = store.distinct_values(list(SELECT_FIELDS_BASE.keys()))
    out = {}
    for field, base in SELECT_FIELDS_BASE.items():
        sheet_text = {}                                   # norm -> exact sheet text
        for v in seen_in_sheet.get(field, []):
            # keep the sheet's text verbatim (only outer whitespace trimmed), so the
            # app writes precisely the option the form's validation list contains
            sheet_text.setdefault(_norm_opt(v), str(v).strip())
        options, used = [""], set()
        for b in base:
            k = _norm_opt(b)
            if not k or k in used:
                continue
            options.append(sheet_text.get(k, b))          # prefer the sheet's exact text
            used.add(k)
        extras = [v for k, v in sheet_text.items() if k not in used]
        if field == "Counselling By":
            for c in getattr(settings, "counsellors", []) or []:
                cb = " ".join(str(getattr(c, "counselling_by", "") or "").split())
                if cb and _norm_opt(cb) not in used and _norm_opt(cb) not in {_norm_opt(e) for e in extras}:
                    extras.append(cb)
        options.extend(sorted(extras, key=lambda s: s.lower()))
        out[field] = options
    return out


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
            "selects": build_select_options(store, settings),   # kept in step with the form
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
