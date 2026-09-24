"""
Business rules for the Counsellor App — ported 1:1 from LeadSubmissionForm.gs so
that a lead saved through the app is byte-identical to one saved through the old
form (same normalisation, same validation, same columns, same timestamp, same
InActive versioning). This is what keeps the downstream consolidation + reports
working with zero changes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

# Fixed India Standard Time offset (+05:30). India observes no daylight saving,
# so this is always correct. Used as a fallback when the IANA timezone database
# isn't installed — notably on Windows, where Python ships without it unless the
# `tzdata` package is present. This makes timestamps work on any machine.
_IST_FIXED = timezone(timedelta(hours=5, minutes=30))


def _ist_tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TIMEZONE)
        except Exception:
            return _IST_FIXED
    return _IST_FIXED

from . import config
from .config import (
    ACTIVE_COLUMNS, MOBILE_COL, TIMESTAMP_COL, TIMESTAMP_FMT, TIMEZONE,
    DATE_FIELDS, DATE_DISPLAY_FMT,
)

_DIGITS = re.compile(r"\D+")
_VALID_MOBILE = re.compile(r"^[6-9]\d{9}$")
_SPACES = re.compile(r"\s+")

# Admission-Status values that make "Candidate Type" optional (mirrors the .gs).
CT_EXEMPT = {"irrelevant", "unable to connect"}

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


# --- small helpers -----------------------------------------------------------
def s_(v) -> str:
    return "" if v is None else str(v).strip()


def lt_norm(v) -> str:
    """trim + collapse spaces + lowercase (the .gs _ltNorm)."""
    return _SPACES.sub(" ", "" if v is None else str(v)).strip().lower()


def normalize_mobile(v) -> str:
    """Reduce any Indian mobile input to its bare 10 digits (strip +91 / 0)."""
    d = _DIGITS.sub("", "" if v is None else str(v))
    if len(d) == 13 and d[:3] == "910":
        d = d[3:]
    elif len(d) == 12 and d[:2] == "91":
        d = d[2:]
    elif len(d) == 11 and d[:1] == "0":
        d = d[1:]
    return d


def is_valid_indian_mobile(v) -> bool:
    return bool(_VALID_MOBILE.match(normalize_mobile(v)))


def now_timestamp() -> str:
    return datetime.now(_ist_tz()).strftime(TIMESTAMP_FMT)


def parse_any_date(v) -> Optional[datetime]:
    """Best-effort parse of the date formats seen in the sheet."""
    t = s_(v)
    if not t:
        return None
    if isinstance(v, datetime):
        return v
    fmts = ["%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",
            "%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]
    for f in fmts:
        try:
            return datetime.strptime(t, f)
        except ValueError:
            pass
    # dd-Mon-yyyy loose
    m = re.match(r"^(\d{1,2})[-/ ]([A-Za-z]{3,})[-/ ](\d{2,4})", t)
    if m and m.group(2)[:3].lower() in _MONTHS:
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        return datetime(y, _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    return None


def format_date_field(v) -> str:
    """Store date fields as an unambiguous 'dd-MMM-yyyy' string (or keep as-is
    if it isn't parseable — e.g. a note the counsellor typed)."""
    d = parse_any_date(v)
    return d.strftime(DATE_DISPLAY_FMT) if d else s_(v)


# --- record construction + validation ----------------------------------------
def empty_record() -> Dict[str, str]:
    return {c: "" for c in ACTIVE_COLUMNS}


def build_record(fields: Dict[str, object], mobile: str,
                 counselling_by: str = "") -> Dict[str, str]:
    """Build a full Active record (all 27 columns) from submitted UI fields.
    Mobile is forced to the normalised key; RecordTimeStamp is stamped now;
    date fields are canonicalised; Counselling By defaults to the counsellor.
    """
    rec = empty_record()
    for k, v in (fields or {}).items():
        if k in rec:
            rec[k] = s_(v)
    rec[MOBILE_COL] = normalize_mobile(mobile)
    if not s_(rec.get("Counselling By")) and counselling_by:
        rec["Counselling By"] = counselling_by
    for df in DATE_FIELDS:
        if s_(rec.get(df)):
            rec[df] = format_date_field(rec[df])
    rec[TIMESTAMP_COL] = now_timestamp()
    return rec


def validate_submission(record: Dict[str, str]) -> Tuple[bool, str]:
    """Return (ok, message). Mirrors the .gs submit-time rules exactly."""
    if not is_valid_indian_mobile(record.get(MOBILE_COL)):
        return False, "Enter a valid 10-digit mobile number starting 6-9."

    admission = lt_norm(record.get("Admission Status"))
    candidate = lt_norm(record.get("Candidate Type"))
    if candidate == "" and admission not in CT_EXEMPT:
        return False, ("Candidate Type is required for the selected Admission "
                       "Status. Please select a Candidate Type before saving.")

    if lt_norm(record.get("IsGoogleMeetSchedule")) == "yes" \
            and lt_norm(record.get("IsGoogleMeetScheduleDate")) == "":
        return False, "Please select the Google Meet Schedule Date."

    if lt_norm(record.get("IsWalkInSchedule")) == "yes" \
            and lt_norm(record.get("IsWalkInScheduleDate")) == "":
        return False, "Please select the Walk-In Schedule Date."

    return True, ""


def row_from_record(record: Dict[str, str], columns: List[str]) -> List[str]:
    """Order a record dict into a row for the given column list."""
    return [s_(record.get(c, "")) for c in columns]


def record_from_row(row: List[object], columns: List[str]) -> Dict[str, str]:
    out = {}
    for i, c in enumerate(columns):
        out[c] = s_(row[i]) if i < len(row) else ""
    return out
