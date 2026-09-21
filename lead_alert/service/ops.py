"""
Orchestration shared by the poller and the HTTP/WebSocket endpoints:
dispatching a new lead, and handling an Accept (single-claim) — plus the small
helpers that build the client payloads and check the operating window.

Blocking Google/SMTP calls are pushed to a worker thread (asyncio.to_thread) so
the event loop that serves WebSockets is never stalled.
"""
from __future__ import annotations

import asyncio
import hashlib
import urllib.parse
from datetime import datetime

from config import SETTINGS
import store
import counsellors
import google_io
import mailer
from hub import HUB

TS_FMT = "%Y-%m-%d %H:%M:%S"


def now_str() -> str:
    return datetime.now().strftime(TS_FMT)


def within_active_window(now: datetime = None) -> bool:
    """True if the local time is inside [active_from, active_to]."""
    now = now or datetime.now()
    try:
        fh, fm = [int(x) for x in SETTINGS.active_from.split(":")]
        th, tm = [int(x) for x in SETTINGS.active_to.split(":")]
    except Exception:
        return True
    cur = now.hour * 60 + now.minute
    start, end = fh * 60 + fm, th * 60 + tm
    return start <= cur <= end if start <= end else (cur >= start or cur <= end)


def _subject_for(form_type: str) -> str:
    ft = (form_type or "").strip()
    return f"New {ft} Enquiry Received" if ft else "New Program Enquiry Received"


def _lead_fingerprint(row: dict) -> str:
    """Stable identity from the lead's CONTENT (not its sheet row number), so
    deleting or reordering rows never causes a missed or duplicate alert."""
    mobile = "".join(ch for ch in str(row.get("mobile", "")) if ch.isdigit())[-10:]
    parts = [
        str(row.get("enquiry_date", "")).strip(),
        str(row.get("name", "")).strip().lower(),
        mobile,
        str(row.get("email", "")).strip().lower(),
        str(row.get("course", "")).strip().lower(),
        str(row.get("form_type", "")).strip().lower(),
    ]
    return "web:" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def build_lead_from_row(row: dict) -> dict:
    """Turn a source-sheet row (google_io.SOURCE_COLS + _row) into a lead dict."""
    form_type = row.get("form_type", "")
    preview_bits = [b for b in (
        row.get("course", ""), row.get("current_role", ""),
        row.get("message", "")) if b]
    return {
        "lead_id": _lead_fingerprint(row),
        "source_row": row["_row"],
        "received_at": now_str(),
        "enquiry_date": row.get("enquiry_date", ""),
        "name": row.get("name", ""),
        "mobile": row.get("mobile", ""),
        "email": row.get("email", ""),
        "course": row.get("course", ""),
        "form_type": form_type,
        "preview": "  •  ".join(preview_bits)[:400],
        "subject": _subject_for(form_type),
        "sender": "IntelliBI Website Enquiry Form",
    }


def lead_public(lead: dict) -> dict:
    subj = lead.get("subject", "")
    return {
        "lead_id": lead["lead_id"],
        "received_at": lead.get("received_at", ""),
        "enquiry_date": lead.get("enquiry_date", ""),
        "name": lead.get("name", ""),
        "mobile": lead.get("mobile", ""),
        "email": lead.get("email", ""),
        "course": lead.get("course", ""),
        "form_type": lead.get("form_type", ""),
        "preview": lead.get("preview", ""),
        "subject": subj,
        "sender": lead.get("sender", ""),
        "status": lead.get("status", "RECEIVED"),
        "assigned_name": lead.get("assigned_name", ""),
        "assigned_at": lead.get("assigned_at", ""),
        "open_email_url": SETTINGS.open_email_url + urllib.parse.quote(subj),
        "lead_sheet_url": SETTINGS.lead_sheet_url,
    }


async def dispatch_lead(lead: dict) -> bool:
    """Insert a new lead (dedup), record deliveries for every Active alert
    recipient, push NEW_LEAD to those currently online, and mirror to the log
    sheet. Returns True if this was a new lead."""
    if not store.insert_lead(lead):
        return False
    recips = counsellors.active_recipients()          # live Active list
    for r in recips:
        store.add_delivery(lead["lead_id"], r["email"], r["name"])
    payload = {"type": "NEW_LEAD", "lead": lead_public(lead)}
    reached = await HUB.send_to_emails([r["email"] for r in recips], payload)
    when = now_str()
    for em in reached:
        store.mark_delivered(lead["lead_id"], em, when)
    await asyncio.to_thread(google_io.log_upsert, store.get_lead(lead["lead_id"]),
                            store.delivery_summary(lead["lead_id"]))
    print(f"  [dispatch] {lead['lead_id']} -> notified {len(recips)} "
          f"(online now: {len(reached)}) : {lead.get('name','')}")
    return True


async def on_accept(device: dict, lead_id: str) -> dict:
    """Atomic single-claim. Broadcast the outcome and return a result dict."""
    email, name = device["counsellor_email"], device["counsellor_name"]
    when = now_str()
    result = store.claim_lead(lead_id, email, name, when)
    if result == "assigned":
        store.mark_acked(lead_id, email, when)
        lead = store.get_lead(lead_id)
        assigned = {"type": "ASSIGNED", "lead_id": lead_id,
                    "assigned_to": email, "assigned_name": name, "assigned_at": when}
        # tell everyone who was notified (their popup flips to "assigned")
        notified = store.delivery_summary(lead_id)["notified"]
        await HUB.send_to_emails(notified, assigned)
        await asyncio.to_thread(google_io.log_upsert, lead,
                                store.delivery_summary(lead_id))
        return {"result": "assigned", "lead_id": lead_id}
    if result == "already":
        lead = store.get_lead(lead_id)
        return {"result": "already", "lead_id": lead_id,
                "assigned_name": lead.get("assigned_name", ""),
                "assigned_at": lead.get("assigned_at", "")}
    return {"result": result, "lead_id": lead_id}       # notfound | expired
