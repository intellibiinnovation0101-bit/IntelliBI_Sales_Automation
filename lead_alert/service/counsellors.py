"""
Active-counsellor loader — the SAME dynamic config approach used by the report
scripts (pyConsolidatedLeadPerformanceReport.py / pyLeadFollowUpAnalysisReport.py).

Reads config/counsellors.json LIVE on every call so that adding, removing,
activating or deactivating a counsellor takes effect with NO code change and NO
restart. Only records with current_status == "Active" are returned, and only the
sections configured under lead_alert.alert_sections (default: "counsellors").
"""
from __future__ import annotations

import json

from config import SETTINGS

# Per-section display-name field, mirroring the report scripts.
_NAME_FIELD = {
    "counsellors": "counsellor_name",
    "digitalmarketingspecialist": "digital_marketing_specialist_name",
    "intellibiadmin": "intellibi_admin_name",
}


def _read() -> dict:
    try:
        with open(SETTINGS.counsellors_json, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        print("  [counsellors] could NOT read counsellors.json:", e)
        return {}


def _active_from_section(cfg: dict, section: str) -> list:
    name_field = _NAME_FIELD.get(section, "counsellor_name")
    out, seen = [], set()
    for rec in (cfg.get(section) or []):
        if str(rec.get("current_status", "")).strip().lower() != "active":
            continue
        em = str(rec.get("emailid", "")).strip()
        nm = str(rec.get(name_field, "")).strip()
        if not em or em.lower() in seen:
            continue
        seen.add(em.lower())
        out.append({"email": em, "name": nm})
    return out


def active_recipients() -> list:
    """[{email, name}] of Active counsellors in the alert sections (deduped)."""
    cfg = _read()
    out, seen = [], set()
    for section in SETTINGS.alert_sections:
        for rec in _active_from_section(cfg, section):
            if rec["email"].lower() not in seen:
                seen.add(rec["email"].lower())
                out.append(rec)
    return out


def escalation_recipients() -> list:
    """[{email, name}] of the Active members of the escalation section
    (default 'intellibiadmin') — who receives the unacknowledged-lead email."""
    cfg = _read()
    return _active_from_section(cfg, SETTINGS.escalate_to_section)


def is_active_counsellor(email: str) -> bool:
    email = (email or "").strip().lower()
    return any(r["email"].lower() == email for r in active_recipients())


def name_for_email(email: str) -> str:
    """Display name of the ACTIVE record for an emailid in counsellors.json, using
    the per-section display-name field; '' if no Active record has that email.

    Inactive records are ignored. A mailbox can be handed over to a new counsellor
    (old record set to Inactive, new record Active with the same emailid), so the
    old person's name must never be used. The alert sections are searched first,
    then every other section. Used for 'Counselling By', the "accepted by" name
    shown to other counsellors, and the client greeting."""
    email = (email or "").strip().lower()
    if not email:
        return ""
    cfg = _read()
    sections = list(SETTINGS.alert_sections) + [
        s for s, rows in cfg.items()
        if isinstance(rows, list) and s not in SETTINGS.alert_sections]
    for section in sections:
        for rec in _active_from_section(cfg, section):
            if rec["email"].lower() == email and rec["name"]:
                return rec["name"]
    return ""


def section_recipients(section: str) -> list:
    """[{email, name}] of the Active members of any counsellors.json section."""
    return _active_from_section(_read(), section)
