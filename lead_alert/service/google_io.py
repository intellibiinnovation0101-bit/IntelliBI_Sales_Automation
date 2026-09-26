"""
Google Sheets I/O for the alert service — reuses the project's service account
(credentials/service_account.json) exactly like the report scripts.

  * read_source_rows()  -> reads the "Contact Us Form" sheet the Apps Script fills
  * log_upsert(lead)    -> best-effort mirror of a lead's lifecycle into the
                           "Website Lead Alert Log" sheet (for reporting)

All calls are best-effort and defensive: a Google hiccup must never crash the
alerting path, so failures are logged and swallowed.
"""
from __future__ import annotations

from config import SETTINGS, SERVICE_ACCOUNT_FILE, READ_WRITE_SCOPES

_sheets = None

# Column order of the "Contact Us Form" sheet (A:N), matching WebsiteFormWebhook.gs (Apps Script web app).
SOURCE_COLS = [
    "enquiry_date", "name", "mobile", "email", "current_role", "preferred_time",
    "course", "career_goal", "total_experience", "consultation_mode",
    "candidate_type", "message", "whatsapp_updates", "form_type",
]

# Header of the audit/metrics log sheet.
LOG_HEADER = [
    "Lead ID", "Received At", "Enquiry Date", "Full Name", "Mobile", "Email",
    "Course Interested", "Form Type", "Notified Counsellors", "Delivered To",
    "First Acknowledged By", "Acknowledged At", "Assigned To", "Status",
    "Response Seconds",
]


def _service():
    global _sheets
    if _sheets is None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=READ_WRITE_SCOPES)
        _sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _sheets


def source_row_count() -> int:
    """Current number of rows (including header) in the source tab, or -1 on error."""
    try:
        resp = _service().spreadsheets().values().get(
            spreadsheetId=SETTINGS.source_sheet_id,
            range=f"'{SETTINGS.source_tab}'!A:A").execute()
        return len(resp.get("values", []))
    except Exception as e:
        print("  [google_io] source_row_count failed:", e)
        return -1


def read_source_rows(first_row: int, last_row: int) -> list:
    """Read data rows [first_row..last_row] (1-based, inclusive) as dicts keyed by
    SOURCE_COLS, each carrying its 1-based sheet row number in '_row'. []=error."""
    if last_row < first_row:
        return []
    rng = f"'{SETTINGS.source_tab}'!A{first_row}:N{last_row}"
    try:
        resp = _service().spreadsheets().values().get(
            spreadsheetId=SETTINGS.source_sheet_id, range=rng).execute()
    except Exception as e:
        print("  [google_io] read_source_rows failed:", e)
        return []
    out = []
    for i, raw in enumerate(resp.get("values", [])):
        rec = {"_row": first_row + i}
        for j, key in enumerate(SOURCE_COLS):
            rec[key] = (raw[j] if j < len(raw) else "").strip()
        out.append(rec)
    return out


# write-back: stamp the accepting counsellor into the 'Counselling By' column
_CB_COL_LETTER = None


def _col_letter(idx0: int) -> str:
    s, n = "", idx0 + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _counselling_col() -> str:
    """A1 column letter of the 'Counselling By' column in the source tab, detected
    from the header row (case-insensitive) so it survives column reordering. Cached
    after the first successful lookup. '' if not present/unreadable."""
    global _CB_COL_LETTER
    if _CB_COL_LETTER:
        return _CB_COL_LETTER
    try:
        resp = _service().spreadsheets().values().get(
            spreadsheetId=SETTINGS.source_sheet_id,
            range=f"'{SETTINGS.source_tab}'!1:1").execute()
        header = (resp.get("values") or [[]])[0]
        for i, nm in enumerate(header):
            if str(nm).strip().lower() == "counselling by":
                _CB_COL_LETTER = _col_letter(i)
                return _CB_COL_LETTER
        print("  [google_io] 'Counselling By' column not found in source header")
    except Exception as e:
        print("  [google_io] counselling-col detect failed:", e)
    return ""


def set_counselling_by(row_number: int, counsellor_name: str) -> bool:
    """Write counsellor_name into the 'Counselling By' cell of the given 1-based row
    in the source tab. Best-effort; returns True on success, never raises."""
    col = _counselling_col()
    if not col or not row_number:
        return False
    try:
        _service().spreadsheets().values().update(
            spreadsheetId=SETTINGS.source_sheet_id,
            range=f"'{SETTINGS.source_tab}'!{col}{int(row_number)}",
            valueInputOption="RAW",
            body={"values": [[counsellor_name]]}).execute()
        return True
    except Exception as e:
        print("  [google_io] set_counselling_by failed:", e)
        return False


# ── audit/metrics mirror (optional) ──────────────────────────────────────────
def _ensure_log_header():
    resp = _service().spreadsheets().values().get(
        spreadsheetId=SETTINGS.log_sheet_id,
        range=f"'{SETTINGS.log_tab}'!A1:O1").execute()
    if not resp.get("values"):
        _service().spreadsheets().values().update(
            spreadsheetId=SETTINGS.log_sheet_id,
            range=f"'{SETTINGS.log_tab}'!A1",
            valueInputOption="RAW", body={"values": [LOG_HEADER]}).execute()


def log_upsert(lead: dict, delivery: dict) -> None:
    """Find the row whose 'Lead ID' == lead_id and update it, else append. Keeps
    exactly one audit row per lead. Best-effort — never raises."""
    if not SETTINGS.log_sheet_id:
        return
    try:
        _ensure_log_header()
        resp = _service().spreadsheets().values().get(
            spreadsheetId=SETTINGS.log_sheet_id,
            range=f"'{SETTINGS.log_tab}'!A2:A").execute()
        ids = [r[0] if r else "" for r in resp.get("values", [])]
        resp_sec = None
        if lead.get("assigned_at") and lead.get("received_at"):
            resp_sec = _response_seconds(lead["received_at"], lead["assigned_at"])
        row = [
            lead.get("lead_id", ""), lead.get("received_at", ""),
            lead.get("enquiry_date", ""), lead.get("name", ""),
            lead.get("mobile", ""), lead.get("email", ""), lead.get("course", ""),
            lead.get("form_type", ""),
            ", ".join(delivery.get("notified", [])),
            ", ".join(delivery.get("delivered", [])),
            lead.get("assigned_name", "") or "",
            lead.get("assigned_at", "") or "",
            lead.get("assigned_to", "") or "",
            lead.get("status", ""),
            "" if resp_sec is None else str(resp_sec),
        ]
        if lead.get("lead_id") in ids:
            r = 2 + ids.index(lead["lead_id"])
            _service().spreadsheets().values().update(
                spreadsheetId=SETTINGS.log_sheet_id,
                range=f"'{SETTINGS.log_tab}'!A{r}:O{r}",
                valueInputOption="RAW", body={"values": [row]}).execute()
        else:
            _service().spreadsheets().values().append(
                spreadsheetId=SETTINGS.log_sheet_id,
                range=f"'{SETTINGS.log_tab}'!A1",
                valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                body={"values": [row]}).execute()
    except Exception as e:
        print("  [google_io] log_upsert failed (non-fatal):", e)


def _response_seconds(received_at: str, assigned_at: str):
    from datetime import datetime
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        return int((datetime.strptime(assigned_at, fmt)
                    - datetime.strptime(received_at, fmt)).total_seconds())
    except Exception:
        return None
