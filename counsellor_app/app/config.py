"""
Central configuration for the IntelliBI Counsellor App.

Everything environment-specific is read here (from config.yaml + environment
variables), so the rest of the code never hard-codes an ID or a secret.

IMPORTANT — byte-compatibility with the existing production Data sheet:
    The column list, tab names, timestamp format and mobile normalisation below
    MUST match what LeadSubmissionForm.gs writes today, so the existing Python
    consolidation and the Follow-Up report keep reading the sheet unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import yaml  # PyYAML
except Exception:  # pragma: no cover
    yaml = None


# --- The production Data-sheet schema (ORDER MATTERS - do not reorder) --------
# This is the header row of "IntelliBI Lead Information Active", verified against
# the live sheet (27 columns). The InActive tab is the SAME columns prefixed with
# the two audit columns below.
ACTIVE_COLUMNS: List[str] = [
    "RecordTimeStamp",
    "Mobile Number",
    "Full Name",
    "Email Address",
    "Candidate Type",
    "Total Years of Experience",
    "Current Domain / Technology",
    "IsGoogleMeetSchedule",
    "Course Interested In",
    "IsGoogleMeetScheduleDate",
    "Career Goal",
    "IsWalkInSchedule",
    "Current Company Name",
    "IsWalkInScheduleDate",
    "Current City",
    "Admission Plan Time",
    "Current Area / Locality",
    "Next Follow-Up Date",
    "Highest Qualification",
    "Counsellor Notes",
    "Graduation / Passing Year",
    "Counselling By",
    "Is Referral",
    "Admission Status",
    "Referrer's Name",
    "BackOutReason",
    "Follow-Up Type",
]

AUDIT_COLUMNS: List[str] = ["RecordVersion", "ArchivedAt"]
INACTIVE_COLUMNS: List[str] = AUDIT_COLUMNS + ACTIVE_COLUMNS

MOBILE_COL = "Mobile Number"
TIMESTAMP_COL = "RecordTimeStamp"

# Timestamp format used by the existing form (dd-MMM-yyyy HH:mm:ss, IST).
TIMESTAMP_FMT = "%d-%b-%Y %H:%M:%S"
TIMEZONE = "Asia/Kolkata"

# Date fields the UI shows as a date picker and stores as dd-MMM-yyyy text
# (unambiguous; the existing reports parse this fine).
DATE_FIELDS = [
    "Next Follow-Up Date",
    "IsGoogleMeetScheduleDate",
    "IsWalkInScheduleDate",
]
DATE_DISPLAY_FMT = "%d-%b-%Y"  # e.g. 26-Sep-2026

# Fields the counsellor is allowed to edit through the app. Everything else is
# read-only/derived. (Mobile Number is the key; RecordTimeStamp is stamped by
# the server; Counselling By defaults to the logged-in user.)
EDITABLE_FIELDS = [c for c in ACTIVE_COLUMNS if c not in (TIMESTAMP_COL, MOBILE_COL)]


@dataclass
class Counsellor:
    email: str
    name: str
    counselling_by: str          # value written to the "Counselling By" column
    role: str = "counsellor"     # counsellor | admin
    password_hash: str = ""      # bcrypt hash (set via manage_users)
    active: bool = True


@dataclass
class Settings:
    # --- Google Sheets (system of record) ---
    data_sheet_id: str = "1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw"
    active_tab: str = "IntelliBI Lead Information Active"
    active_tab_aliases: List[str] = field(
        default_factory=lambda: ["IntelliBI Lead Information Result"]
    )
    inactive_tab: str = "IntelliBI Lead Information InActive"
    service_account_file: str = "credentials/service_account.json"

    # --- optional Walk-In pre-fill source (read-only) ---
    walkin_sheet_id: str = "19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ"
    walkin_tab: str = "Walk-In New"
    walkin_prefill_enabled: bool = True

    # --- performance / durability ---
    db_path: str = "data/store.db"          # SQLite cache + write-behind journal
    reconcile_seconds: int = 300            # re-read the sheet to catch out-of-band edits
    sync_batch_max: int = 50                # max queued writes flushed per cycle
    sync_tick_seconds: float = 2.0          # how often the write-behind worker runs

    # --- auth / security ---
    session_secret: str = "CHANGE_ME_TO_A_LONG_RANDOM_STRING"
    session_hours: int = 12
    google_oauth_enabled: bool = False      # optional; see docs/04
    google_client_id: str = ""
    allowed_email_domain: str = ""          # e.g. intellibiinnovationstechnologies.in

    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8600

    counsellors: List[Counsellor] = field(default_factory=list)

    # ---------------------------------------------------------------
    def counsellor_by_email(self, email: str) -> Optional[Counsellor]:
        e = (email or "").strip().lower()
        for c in self.counsellors:
            if c.email.strip().lower() == e:
                return c
        return None


def _project_root() -> str:
    # counsellor_app/ (one level up from app/)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_settings(config_path: Optional[str] = None) -> Settings:
    """Load Settings from config.yaml (if present) then override with env vars."""
    root = _project_root()
    cfg = {}
    path = config_path or os.path.join(root, "config.yaml")
    if yaml is not None and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}

    s = Settings()
    for key, val in (cfg.items() if isinstance(cfg, dict) else []):
        if key == "counsellors":
            s.counsellors = [Counsellor(**c) for c in (val or [])]
        elif hasattr(s, key):
            setattr(s, key, val)

    # env overrides (INTELLIBI_APP_*)
    def env(name, cast=str):
        v = os.environ.get(name)
        return cast(v) if v is not None else None

    for name, attr, cast in [
        ("INTELLIBI_APP_DATA_SHEET_ID", "data_sheet_id", str),
        ("INTELLIBI_APP_SERVICE_ACCOUNT", "service_account_file", str),
        ("INTELLIBI_APP_SESSION_SECRET", "session_secret", str),
        ("INTELLIBI_APP_PORT", "port", int),
        ("INTELLIBI_APP_HOST", "host", str),
        ("INTELLIBI_APP_DB_PATH", "db_path", str),
    ]:
        v = env(name, cast)
        if v is not None:
            setattr(s, attr, v)

    # make relative paths absolute against the project root
    if not os.path.isabs(s.service_account_file):
        s.service_account_file = os.path.join(root, s.service_account_file)
    if not os.path.isabs(s.db_path):
        s.db_path = os.path.join(root, s.db_path)
    return s
