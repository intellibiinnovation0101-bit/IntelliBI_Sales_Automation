#!/usr/bin/env python3
"""
================================================================================
  IntelliBI Sales Automation — Google Ads Remarketing Audience
  google_ads_campaign_remarketing/pyGoogleAdsRemarketingAudience.py
  ------------------------------------------------------------------------------
  Keeps the Google Ads remarketing audience current: every RELEVANT, NOT-ENROLLED
  lead who enquired in the last NUMBER_OF_DAYS days, with a usable mobile number.

  Two outputs, built from ONE final dataset (they always reconcile):
    1. Phone Number Audience  — the EXISTING production sheet used by Google Ads
       ("Retargeting IntelliBi", PHONE_AUDIENCE_SHEET_ID): column A "Mobile",
       numbers like 919876543210 (91 + 10-digit mobile, stored as numbers);
       column B "Email" — the lead's email when known, else blank.
    2. Full Details           — ONE persistent Google Sheet in the "Manish Leads"
       folder (FULL_DETAILS_SHEET_NAME): the same leads with their full details,
       in the same order as the phone audience.

  NO NEW BUSINESS RULES — everything is reused from the Sales project:
    * master lead data, auth, retries ...... pyConsolidatedLeadPerformanceReport
                                              (read_master_df, _creds, api_retry)
    * invalid phone => irrelevant .......... common/lead_rules.py
    * "enquired in the window" ............. pyConsolidatedLeadPerformanceReport
                                              .prepare_active (the engine of the
                                              Fresh / Repeat Lead Details tabs)
    * relevant ............................. pyConsolidatedLeadPerformanceReport
                                              .is_relevant_lead (IsLeadRelevant =
                                              Yes AND connected)
    * already enrolled ..................... phone on EITHER enrolled list:
                                              pyLeadFollowUpAnalysisReport
                                              .load_enrolled_phones (New Enroll tab)
                                              and pyConsolidatedLeadPerformanceReport
                                              .load_enrolled_mobiles (Student
                                              Admission Responses), + Admission
                                              Status "Admission Confirmed"
                                              (pyLeadFollowUpAnalysisReport
                                              .is_converted_status)
    * "Not Interested" ..................... pyLeadFollowUpAnalysisReport
                                              .is_followup_excluded_status (Admission
                                              Status or Lead Status)
    * phone normalisation / validity ....... sales_consolidation/pyConsolidateLeadsLoad
                                              .norm_phone / .is_valid_mobile (the
                                              rule that writes IsPhoneNumberValid)
    * email ................................ the master's "Email Address" (written by
                                              the consolidation), checked with its own
                                              pyConsolidateLeadsLoad.clean_email
    * Lead Journey / Platforms Used ........ pyConsolidatedLeadPerformanceReport
                                              .format_journey / .platforms_in_sequence

  PRODUCTION SAFETY
    Load → filter → normalise/de-duplicate → validate → reconcile, and ONLY THEN
    write. Each sheet is rewritten with ONE Sheets batchUpdate (all-or-nothing:
    Google applies every request or none), so the audience is never left empty or
    half-written. The run refuses to publish (and keeps the last good audience)
    when an enrolled list cannot be read, the audience would be empty, or it
    would shrink by more than MAX_AUDIENCE_DROP_PCT. Both sheets are read back and
    reconciled after writing.

  RUN
    python google_ads_campaign_remarketing/pyGoogleAdsRemarketingAudience.py
    python google_ads_campaign_remarketing/pyGoogleAdsRemarketingAudience.py --dry-run
        (--dry-run: read everything live, print the result, write NOTHING)
    Scheduled: Sales Layer 3 (scripts/run_layer3.py), after the two reports.
  Exit code: 0 = audience refreshed; 3 = nothing written, safe to re-run
  (source / Google problem); 1 = refused or failed (see log).
================================================================================
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in ("common", "sales_reports", "sales_consolidation"):
    _d = os.path.join(_ROOT, _p)
    if _d not in sys.path:
        sys.path.insert(0, _d)
import _bootstrap  # noqa: E402,F401  (sys.path + env defaults + config.yaml)
import api_retry   # noqa: E402
import lead_rules  # noqa: E402
import pyConsolidatedLeadPerformanceReport as clpr   # noqa: E402  (reused, not modified)
import pyConsolidateLeadsLoad as consolidation        # noqa: E402  (phone rules only)

lfa = clpr.lfa                                        # pyLeadFollowUpAnalysisReport

# =============================================================================
#  CONFIGURATION
# =============================================================================
# Rolling remarketing window: exactly NUMBER_OF_DAYS calendar days ending today
# (IST) — leads with at least one enquiry in those days.
# Example: today 01-Oct-2026, 40 → 23-Aug-2026 00:00 … 01-Oct-2026 23:59 (40 days).
NUMBER_OF_DAYS = 40

# 1) Production Google Ads audience — the EXISTING sheet (never replaced).
PHONE_AUDIENCE_SHEET_ID = "150HujTNz3rsSr2dZMIrs_Cdp3fsZPgJB-p3RoJVixSU"
PHONE_AUDIENCE_GID = 0                    # the tab Google Ads reads ("Sheet1")
PHONE_AUDIENCE_HEADER = "Mobile"          # A1, kept exactly as it is
EMAIL_AUDIENCE_HEADER = "Email"           # B1 — the lead's email (blank when unknown)
COUNTRY_CODE = "91"                       # 91 + 10-digit mobile, written as a number

# 2) Full Details — ONE persistent sheet, created once in this folder.
FULL_DETAILS_FOLDER_ID = "1cjhEZWbSGzNoGog33h7VnfI8K5PawMOj"     # "Manish Leads"
FULL_DETAILS_SHEET_NAME = "Google Ads Campaign Remarketing Leads Full Details"
FULL_DETAILS_SHEET_ID = None              # pin an id here to skip the lookup by name
AUDIENCE_TAB = "Remarketing Audience"
HISTORY_TAB = "Refresh History"

# Who counts as "already enrolled": phone on EITHER enrolled list (the Follow-Up
# report's New Enroll tab and the Performance report's Student Admission
# Responses), or Admission Status = Admission Confirmed.
EXCLUDE_ADMISSION_CONFIRMED = True
# "Not Interested" leads (Admission Status or Lead Status) are never targeted —
# the Follow-Up report's own exclusion rule.
EXCLUDE_NOT_INTERESTED = True

# Safety guards — the production audience is left untouched when one trips.
REQUIRE_ENROLLED_LIST = True              # an enrolled list unreadable/empty → do not publish
MIN_AUDIENCE_SIZE = 1                     # never publish an audience smaller than this
MAX_AUDIENCE_DROP_PCT = 60                # refuse if the audience shrinks by more (None = off)

EXIT_OK, EXIT_FAILED, EXIT_RETRYABLE = 0, 1, 3

FULL_COLUMNS = ["First Enquiry", "Latest Enquiry", "Full Name", "Mobile Number", "Email",
                "Platforms Used", "Interactions", "Relevant", "Is Referral",
                "Course Interested", "Notes / Remarks", "Admission Status",
                "Backout Reason", "Counselling By", "Google Meet Sch.", "Walk-in Sch.",
                "Lead Journey (Enquiry → Latest)", "Fresh / Repeat", "Google Ads Phone"]
FULL_HEADER_ROW = 3                       # rows 1-2 = title + run summary, 3 = header
FULL_WIDTHS = [150, 150, 170, 120, 200, 170, 90, 75, 85, 190, 260, 150, 170, 130, 105, 95,
               330, 100, 120]


class SourceError(Exception):
    """Source data could not be loaded — nothing written, safe to re-run."""


class AudienceRefused(Exception):
    """The new audience failed validation / a safety guard — nothing written."""


# =============================================================================
#  WINDOW
# =============================================================================
def window_bounds(today: date, days: int = None):
    """(start_date, end_date, start_dt, end_dt) of the rolling window: exactly
    `days` calendar days ending today (start 00:00, end 23:59:59), built with
    the report's own day_bounds()."""
    days = NUMBER_OF_DAYS if days is None else days
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError(f"NUMBER_OF_DAYS must be a whole number >= 1 (got {days!r})")
    start = today - timedelta(days=days - 1)
    return start, today, clpr.day_bounds(start)[0], clpr.day_bounds(today)[1]


# =============================================================================
#  AUDIENCE  (pure — no Google I/O; unit-tested)
# =============================================================================
def audience_phone(mobile):
    """Google Ads value for a lead's mobile: 91 + the consolidation's normalised
    10-digit number, as an int — or None when the number is not a valid mobile
    under the consolidation's own rule."""
    n = consolidation.norm_phone(mobile)
    if not consolidation.is_valid_mobile(n):
        return None
    return int(COUNTRY_CODE + n)


def _last_contact(a):
    """Most recent in-window enquiry (for choosing between duplicate rows)."""
    return max((dt for _src, dt in a.get("_inper_pairs") or []), default=datetime.min)


def lead_email(a):
    """The lead's email from the master's "Email Address" column, checked with the
    consolidation's own clean_email ('' when missing / not a valid address)."""
    return consolidation.clean_email(a.get(clpr.C_EMAIL))


def full_detail_row(a, phone):
    c = clpr
    return [a.get(c.C_FIRST), a.get(c.C_LATEST), a.get(c.C_NAME), a.get(c.C_MOBILE),
            lead_email(a), c.platforms_in_sequence(a), a["_ninper"], a.get(c.C_RELEV), a.get(c.C_REF),
            a.get(c.C_COURSE), a.get(c.C_REMARKS), a.get(c.C_ADM), a.get(c.C_BACKOUT),
            a.get(c.C_COUNSEL), a.get(c.C_GMEET), a.get(c.C_WALKSCH),
            c.format_journey(a.get(c.C_HIST)), "Fresh" if a["_is_new"] else "Repeat", phone]


def build_audience(df, today: date, enrolled_phones, days: int = None) -> dict:
    """The ONE final dataset both sheets are written from.
    Returns {window, stats, leads, phones, rows}; phones[i] belongs to rows[i]."""
    start, end, start_dt, end_dt = window_bounds(today, days)
    stats = {"master_rows": len(df)}
    df, stats["invalid_phone_irrelevant"] = lead_rules.apply_invalid_phone_irrelevance(
        df, clpr.C_VALID, clpr.C_RELEV)
    active = clpr.prepare_active(df, start_dt, end_dt)       # ≥1 enquiry in the window
    stats["evaluated"] = len(active)
    enrolled = {p for p in (enrolled_phones or set()) if p}
    kept, excl = [], {"irrelevant": 0, "not_interested": 0, "enrolled": 0,
                      "admission_confirmed": 0, "invalid_phone": 0}
    for a in active:
        if not clpr.is_relevant_lead(a):
            excl["irrelevant"] += 1
            continue
        if EXCLUDE_NOT_INTERESTED and lfa.is_followup_excluded_status(
                a.get(clpr.C_ADM), a.get(clpr.C_STATUS)):
            excl["not_interested"] += 1
            continue
        if lfa.digits10(a.get(clpr.C_MOBILE)) in enrolled:
            excl["enrolled"] += 1
            continue
        if EXCLUDE_ADMISSION_CONFIRMED and lfa.is_converted_status(a.get(clpr.C_ADM)):
            excl["admission_confirmed"] += 1
            continue
        phone = audience_phone(a.get(clpr.C_MOBILE))
        if phone is None:
            excl["invalid_phone"] += 1
            continue
        kept.append((phone, a))
    stats["relevant"] = stats["evaluated"] - excl["irrelevant"]
    stats.update({f"excluded_{k}": v for k, v in excl.items()})
    # one row per phone — keep the lead's most recent in-window enquiry
    best = {}
    for phone, a in kept:
        cur = best.get(phone)
        if cur is None or (_last_contact(a), a["_ninper"]) > (_last_contact(cur), cur["_ninper"]):
            best[phone] = a
    stats["duplicates_removed"] = len(kept) - len(best)
    ordered = sorted(best.items(), key=lambda pa: _last_contact(pa[1]), reverse=True)
    leads = [a for _p, a in ordered]
    phones = [p for p, _a in ordered]
    emails = [lead_email(a) for _p, a in ordered]          # emails[i] belongs to phones[i]
    rows = [full_detail_row(a, p) for p, a in ordered]
    stats["final"] = len(phones)
    stats["with_email"] = sum(1 for e in emails if e)
    return {"window": (start, end), "days": NUMBER_OF_DAYS if days is None else days,
            "stats": stats, "leads": leads, "phones": phones, "emails": emails, "rows": rows}


def validate_audience(aud, current_phones=None):
    """Raise AudienceRefused unless the dataset is safe to publish."""
    phones, rows = aud["phones"], aud["rows"]
    problems = []
    if len(phones) != len(set(phones)):
        problems.append("duplicate phone numbers in the final audience")
    bad = [p for p in phones if not (isinstance(p, int) and len(str(p)) == 12
                                     and str(p).startswith(COUNTRY_CODE)
                                     and consolidation.is_valid_mobile(str(p)[2:]))]
    if bad:
        problems.append(f"{len(bad)} phone value(s) not in the 91XXXXXXXXXX format")
    if [r[-1] for r in rows] != phones:
        problems.append("Full Details rows do not match the phone audience")
    if [r[FULL_COLUMNS.index("Email")] for r in rows] != aud.get("emails", []):
        problems.append("Full Details emails do not match the audience emails")
    if len(phones) < MIN_AUDIENCE_SIZE:
        problems.append(f"audience has {len(phones)} lead(s) — below MIN_AUDIENCE_SIZE "
                        f"({MIN_AUDIENCE_SIZE})")
    if current_phones and MAX_AUDIENCE_DROP_PCT is not None:
        drop = 100.0 * (len(current_phones) - len(phones)) / len(current_phones)
        if drop > MAX_AUDIENCE_DROP_PCT:
            problems.append(f"audience would shrink from {len(current_phones)} to "
                            f"{len(phones)} ({drop:.0f}% > MAX_AUDIENCE_DROP_PCT "
                            f"{MAX_AUDIENCE_DROP_PCT}%)")
    if problems:
        raise AudienceRefused("; ".join(problems))


# =============================================================================
#  GOOGLE I/O
# =============================================================================
def sheets_writer():
    """Sheets client acting as the Workspace user (drive scope, the same delegated
    credentials the reports use for Drive) — edits show as info@."""
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=clpr._creds(clpr.DRIVE_SCOPES, impersonate=True),
                 cache_discovery=False)


def _cell(v):
    if isinstance(v, bool) or v is None or v == "":
        return {"userEnteredValue": {"stringValue": "" if v in (None, "") else str(v)}}
    if isinstance(v, int):
        return {"userEnteredValue": {"numberValue": v}}
    return {"userEnteredValue": {"stringValue": str(v)}}


def _sheet_props(sheets, sid):
    meta = api_retry.execute(sheets.spreadsheets().get(
        spreadsheetId=sid, fields="sheets(properties(sheetId,title,gridProperties))"),
        "Sheets: audience metadata")
    return [s["properties"] for s in meta.get("sheets", [])]


def read_phone_audience(sheets):
    """(tab properties, current numbers) of the production audience; refuses if
    its structure is not the expected "Mobile" | "Email" columns (column B may still
    be empty — the first run after Email was added creates it)."""
    props = next((p for p in _sheet_props(sheets, PHONE_AUDIENCE_SHEET_ID)
                  if p["sheetId"] == PHONE_AUDIENCE_GID), None)
    if props is None:
        raise AudienceRefused(f"audience tab gid {PHONE_AUDIENCE_GID} not found in the "
                              f"production sheet — structure changed, not touching it")
    vals = api_retry.execute(sheets.spreadsheets().values().get(
        spreadsheetId=PHONE_AUDIENCE_SHEET_ID, range=f"'{props['title']}'",
        valueRenderOption="UNFORMATTED_VALUE"), "Sheets: read audience").get("values", [])
    header = str(vals[0][0]).strip() if vals and vals[0] else ""
    if header != PHONE_AUDIENCE_HEADER:
        raise AudienceRefused(f"production sheet A1 is {header!r}, expected "
                              f"{PHONE_AUDIENCE_HEADER!r} — structure changed, not touching it")
    b1 = str(vals[0][1]).strip() if vals and len(vals[0]) > 1 else ""
    if b1 not in ("", EMAIL_AUDIENCE_HEADER):
        raise AudienceRefused(f"production sheet B1 is {b1!r}, expected "
                              f"{EMAIL_AUDIENCE_HEADER!r} — structure changed, not touching it")
    if not b1 and any(len(r) > 1 and str(r[1]).strip() for r in vals[1:]):
        raise AudienceRefused("production sheet has data in column B without the "
                              f"{EMAIL_AUDIENCE_HEADER!r} header — structure changed, not touching it")
    if any(str(c).strip() for r in vals for c in r[2:]):
        raise AudienceRefused("production sheet has data outside columns A-B — "
                              "structure changed, not touching it")
    current = [int(r[0]) if isinstance(r[0], (int, float)) else str(r[0]).strip()
               for r in vals[1:] if r and str(r[0]).strip()]
    return props, current


def write_phone_audience(sheets, props, phones, emails, old_rows):
    """Rewrite A2:B with the new audience in ONE atomic batchUpdate: A = numbers
    (format "0", as today), B = email or blank, B1 = "Email", leftover old rows
    cleared, A1 untouched."""
    gid = props["sheetId"]
    need = len(phones) + 1
    grid = props.get("gridProperties", {})
    have = grid.get("rowCount", 1000)
    reqs = []
    if need > have:
        reqs.append({"appendDimension": {"sheetId": gid, "dimension": "ROWS", "length": need - have}})
    if grid.get("columnCount", 26) < 2:
        reqs.append({"appendDimension": {"sheetId": gid, "dimension": "COLUMNS",
                                         "length": 2 - grid.get("columnCount", 1)}})
    reqs.append({"updateCells": {                       # B1 header
        "start": {"sheetId": gid, "rowIndex": 0, "columnIndex": 1},
        "rows": [{"values": [{"userEnteredValue": {"stringValue": EMAIL_AUDIENCE_HEADER}}]}],
        "fields": "userEnteredValue"}})
    reqs.append({"updateCells": {
        "start": {"sheetId": gid, "rowIndex": 1, "columnIndex": 0},
        "rows": [{"values": [{"userEnteredValue": {"numberValue": p},
                              "userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}}},
                             {"userEnteredValue": {"stringValue": e or ""}}]}
                 for p, e in zip(phones, emails)],
        "fields": "userEnteredValue,userEnteredFormat.numberFormat"}})
    last = max(old_rows + 1, need)
    if last > need:                                    # clear what the new list no longer covers
        reqs.append({"updateCells": {"range": {"sheetId": gid, "startRowIndex": need,
                                               "endRowIndex": last, "startColumnIndex": 0,
                                               "endColumnIndex": 2},
                                     "fields": "userEnteredValue"}})
    api_retry.execute(sheets.spreadsheets().batchUpdate(
        spreadsheetId=PHONE_AUDIENCE_SHEET_ID, body={"requests": reqs}),
        "Sheets: update phone audience")


def find_or_create_full_details(drive):
    """(spreadsheet id, created?) — the ONE persistent Full Details sheet."""
    if FULL_DETAILS_SHEET_ID:
        return FULL_DETAILS_SHEET_ID, False
    name = FULL_DETAILS_SHEET_NAME.replace("'", "\\'")
    q = (f"'{FULL_DETAILS_FOLDER_ID}' in parents and name = '{name}' and "
         f"mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false")
    files = api_retry.execute(drive.files().list(
        q=q, fields="files(id,name,createdTime)", orderBy="createdTime",
        supportsAllDrives=True, includeItemsFromAllDrives=True),
        "Drive: find Full Details sheet").get("files", [])
    if files:
        if len(files) > 1:
            print(f"  [details] WARNING {len(files)} sheets named '{FULL_DETAILS_SHEET_NAME}' "
                  f"— using the oldest ({files[0]['id']}).")
        return files[0]["id"], False
    f = api_retry.execute(drive.files().create(
        body={"name": FULL_DETAILS_SHEET_NAME, "parents": [FULL_DETAILS_FOLDER_ID],
              "mimeType": "application/vnd.google-apps.spreadsheet"},
        fields="id", supportsAllDrives=True), "Drive: create Full Details sheet")
    print(f"  [details] Full Details sheet created once in the remarketing folder: {f['id']}")
    return f["id"], True


def _ensure_tabs(sheets, sid):
    """{tab title: sheetId} with AUDIENCE_TAB and HISTORY_TAB present (a new
    sheet's default first tab is renamed to AUDIENCE_TAB)."""
    props = _sheet_props(sheets, sid)
    titles = {p["title"]: p for p in props}
    reqs = []
    if AUDIENCE_TAB not in titles:
        if len(props) == 1 and props[0]["title"] not in (HISTORY_TAB,):
            reqs.append({"updateSheetProperties": {
                "properties": {"sheetId": props[0]["sheetId"], "title": AUDIENCE_TAB},
                "fields": "title"}})
        else:
            reqs.append({"addSheet": {"properties": {"title": AUDIENCE_TAB, "index": 0}}})
    if HISTORY_TAB not in titles:
        reqs.append({"addSheet": {"properties": {"title": HISTORY_TAB}}})
    if reqs:
        api_retry.execute(sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}),
                          "Sheets: prepare Full Details tabs")
        props = _sheet_props(sheets, sid)
    if HISTORY_TAB not in titles:                          # header of the new history tab
        api_retry.execute(sheets.spreadsheets().values().update(
            spreadsheetId=sid, range=f"'{HISTORY_TAB}'!A1", valueInputOption="RAW",
            body={"values": [HISTORY_HEADER]}), "Sheets: Refresh History header")
    return {p["title"]: p for p in props}


NAVY = {"red": 0.106, "green": 0.208, "blue": 0.369}
PALE = {"red": 0.902, "green": 0.937, "blue": 0.984}


def write_full_details(sheets, sid, tabs, aud, stamp):
    """Rewrite the Audience tab in ONE atomic batchUpdate (clear + write + format)."""
    p = tabs[AUDIENCE_TAB]
    gid = p["sheetId"]
    nrows = FULL_HEADER_ROW + len(aud["rows"])
    ncols = len(FULL_COLUMNS)
    grid = p.get("gridProperties", {})
    start, end = aud["window"]
    title = "Google Ads Campaign Remarketing — Eligible Leads (same audience as the Google Ads phone list)"
    summary = (f"Window: {start:%d-%b-%Y} → {end:%d-%b-%Y} (last {aud['days']} days)   ·   "
               f"Audience: {len(aud['phones'])} lead(s)   ·   Relevant, not Not-Interested, not enrolled, valid mobile   ·   "
               f"Interactions = enquiries within the window   ·   Updated {stamp}")
    rows = [[title], [summary], FULL_COLUMNS] + aud["rows"]
    reqs = [{"updateSheetProperties": {"properties": {"sheetId": gid, "gridProperties": {
                "rowCount": max(grid.get("rowCount", 0), nrows + 1),
                "columnCount": max(grid.get("columnCount", 0), ncols),
                "frozenRowCount": FULL_HEADER_ROW}},
             "fields": "gridProperties(rowCount,columnCount,frozenRowCount)"}},
            {"updateCells": {"range": {"sheetId": gid}, "fields": "userEnteredValue"}},
            {"updateCells": {"start": {"sheetId": gid, "rowIndex": 0, "columnIndex": 0},
                             "rows": [{"values": [_cell(v) for v in r]} for r in rows],
                             "fields": "userEnteredValue"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 13,
                                                           "foregroundColor": NAVY}}},
                            "fields": "userEnteredFormat.textFormat"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 1, "endRowIndex": 2},
                            "cell": {"userEnteredFormat": {"textFormat": {"italic": True}}},
                            "fields": "userEnteredFormat.textFormat"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": FULL_HEADER_ROW - 1,
                                      "endRowIndex": FULL_HEADER_ROW, "startColumnIndex": 0,
                                      "endColumnIndex": ncols},
                            "cell": {"userEnteredFormat": {
                                "backgroundColor": NAVY, "wrapStrategy": "WRAP",
                                "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER",
                                "textFormat": {"bold": True, "foregroundColor":
                                               {"red": 1, "green": 1, "blue": 1}}}},
                            "fields": "userEnteredFormat(backgroundColor,wrapStrategy,"
                                      "verticalAlignment,horizontalAlignment,textFormat)"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": FULL_HEADER_ROW,
                                      "startColumnIndex": 0, "endColumnIndex": ncols},
                            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP",
                                                           "verticalAlignment": "TOP"}},
                            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": FULL_HEADER_ROW,
                                      "startColumnIndex": ncols - 1, "endColumnIndex": ncols},
                            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"},
                                                           "backgroundColor": PALE}},
                            "fields": "userEnteredFormat(numberFormat,backgroundColor)"}},
            {"setBasicFilter": {"filter": {"range": {"sheetId": gid,
                                                     "startRowIndex": FULL_HEADER_ROW - 1,
                                                     "endRowIndex": nrows,
                                                     "startColumnIndex": 0, "endColumnIndex": ncols}}}}]
    reqs += [{"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                                                      "startIndex": i, "endIndex": i + 1},
                                            "properties": {"pixelSize": w}, "fields": "pixelSize"}}
             for i, w in enumerate(FULL_WIDTHS[:ncols])]
    api_retry.execute(sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}),
                      "Sheets: update Full Details")


def read_back(sheets, sid, rng):
    return api_retry.execute(sheets.spreadsheets().values().get(
        spreadsheetId=sid, range=rng, valueRenderOption="UNFORMATTED_VALUE"),
        "Sheets: verify").get("values", [])


def append_history(sheets, sid, row):
    """Best-effort: one line per run in the Refresh History tab (never fails a run)."""
    try:
        api_retry.execute(sheets.spreadsheets().values().append(
            spreadsheetId=sid, range=f"'{HISTORY_TAB}'!A1", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}), "Sheets: refresh history")
    except Exception as exc:                               # noqa: BLE001
        print(f"  [details] could not add the Refresh History line ({exc}).")


HISTORY_HEADER = ["Refreshed (IST)", "Window Start", "Window End", "Days", "Leads Evaluated",
                  "Relevant", "Not Interested Excluded", "Enrolled Excluded",
                  "Admission Confirmed Excluded",
                  "Invalid Phone Excluded", "Duplicates Removed", "Final Audience",
                  "Added", "Removed", "Result"]


# =============================================================================
#  RUN
# =============================================================================
def print_stats(aud):
    s, (start, end) = aud["stats"], aud["window"]
    print(f"Window: {start:%d-%b-%Y} → {end:%d-%b-%Y} (last {aud['days']} days, today included)")
    print(f"Master rows loaded: {s['master_rows']}  (invalid-phone rule: "
          f"{s['invalid_phone_irrelevant']} counted as irrelevant)")
    print(f"Leads evaluated (enquired in window): {s['evaluated']}")
    print(f"Relevant leads: {s['relevant']}  (irrelevant excluded: {s['excluded_irrelevant']})")
    print(f"Not Interested leads excluded: {s['excluded_not_interested']}")
    print(f"Enrolled leads excluded: {s['excluded_enrolled']}  "
          f"(Admission Confirmed excluded: {s['excluded_admission_confirmed']})")
    print(f"Invalid/unusable phone numbers excluded: {s['excluded_invalid_phone']}")
    print(f"Duplicate phone numbers removed: {s['duplicates_removed']}")
    print(f"Final eligible audience: {s['final']}  (with email: {s.get('with_email', 0)})")


def refresh(sheets_read, sheets_write, drive, today, dry_run=False) -> int:
    stamp = clpr.now_ist().strftime("%d-%b-%Y %I:%M %p IST")
    # ── 1. load sources (nothing written yet) ────────────────────────────────
    try:
        df = clpr.read_master_df(sheets_read)
        if df is None or not len(df):
            raise SourceError("master lead sheet returned no rows")
        enrolled_fu = lfa.load_enrolled_phones(sheets_read)          # New Enroll tab
        enrolled_perf = clpr.load_enrolled_mobiles(sheets_read)      # Student Admission Responses
    except SourceError as exc:
        print(f"[audience] FAILED before any update — {exc}. Last audience kept.")
        return EXIT_RETRYABLE
    except Exception as exc:                               # noqa: BLE001
        print(f"[audience] FAILED loading source data ({exc}). Last audience kept.")
        return EXIT_RETRYABLE
    missing = [n for n, v in (("New Enroll (Follow-Up report)", enrolled_fu),
                              ("Student Admission Responses (Performance report)", enrolled_perf))
               if not v]
    if REQUIRE_ENROLLED_LIST and missing:
        print(f"[audience] FAILED — enrolled-students list not readable (or empty): "
              f"{', '.join(missing)}; publishing now could re-target enrolled students. "
              f"Last audience kept.")
        return EXIT_RETRYABLE
    enrolled = set(enrolled_fu) | set(enrolled_perf)
    print(f"Enrolled phones loaded: {len(enrolled)} unique  (New Enroll: {len(enrolled_fu)}, "
          f"Student Admission Responses: {len(enrolled_perf)})")
    # ── 2. eligibility → normalise → de-duplicate ────────────────────────────
    aud = build_audience(df, today, enrolled)
    print_stats(aud)
    # ── 3. validate against the live audience (still nothing written) ────────
    try:
        props, current = read_phone_audience(sheets_write if not dry_run else sheets_read)
    except AudienceRefused as exc:
        print(f"[audience] REFUSED — {exc}. Last audience kept.")
        return EXIT_FAILED
    except Exception as exc:                               # noqa: BLE001
        print(f"[audience] FAILED reading the production audience ({exc}). Last audience kept.")
        return EXIT_RETRYABLE
    cur_set, new_set = set(current), set(aud["phones"])
    added, removed = len(new_set - cur_set), len(cur_set - new_set)
    print(f"Phone audience change: +{added} added, -{removed} removed, "
          f"{len(new_set & cur_set)} unchanged (was {len(current)}, now {len(new_set)})")
    try:
        validate_audience(aud, current)
    except AudienceRefused as exc:
        print(f"[audience] REFUSED — {exc}. Last audience kept.")
        return EXIT_FAILED
    print("Reconciliation (before writing): OK — phone audience and Full Details are the same "
          f"{len(aud['phones'])} lead(s).")
    if dry_run:
        print("[audience] DRY RUN — nothing written.")
        return EXIT_OK
    # ── 4. write: Full Details first (internal), then the production audience ─
    try:
        sid, _created = find_or_create_full_details(drive)
        tabs = _ensure_tabs(sheets_write, sid)
        write_full_details(sheets_write, sid, tabs, aud, stamp)
        back = read_back(sheets_write, sid, f"'{AUDIENCE_TAB}'!A{FULL_HEADER_ROW + 1}:"
                                            f"{clpr._a1col(len(FULL_COLUMNS) - 1)}")
        got = [int(r[-1]) for r in back if len(r) == len(FULL_COLUMNS) and str(r[-1]).strip()]
        if got != aud["phones"]:
            raise RuntimeError(f"Full Details read-back has {len(got)} phone(s), expected "
                               f"{len(aud['phones'])}")
        print(f"[details] Full Details sheet updated: {len(got)} lead(s) "
              f"(https://docs.google.com/spreadsheets/d/{sid})")
    except Exception as exc:                               # noqa: BLE001
        print(f"[details] FAILED to update the Full Details sheet ({exc}). "
              f"Production audience NOT changed.")
        return EXIT_RETRYABLE
    try:
        write_phone_audience(sheets_write, props, aud["phones"], aud["emails"], len(current))
        back = read_back(sheets_write, PHONE_AUDIENCE_SHEET_ID, f"'{props['title']}'!A:B")
        live = [int(r[0]) for r in back[1:] if r and str(r[0]).strip()]
        live_em = [str(r[1]).strip() if len(r) > 1 else "" for r in back[1:] if r and str(r[0]).strip()]
        ok = (str(back[0][0]).strip() == PHONE_AUDIENCE_HEADER
              and len(back[0]) > 1 and str(back[0][1]).strip() == EMAIL_AUDIENCE_HEADER
              and live == aud["phones"] and live_em == aud["emails"])
    except Exception as exc:                               # noqa: BLE001
        print(f"[audience] FAILED to update the production audience ({exc}). The batch is "
              f"all-or-nothing, so the previous audience is still in place.")
        append_history(sheets_write, sid, _history_row(stamp, aud, added, removed,
                                                       "FAILED — production audience not updated"))
        return EXIT_RETRYABLE
    if not ok:
        print("[audience] FAILED — production sheet read-back does not match the new audience.")
        append_history(sheets_write, sid, _history_row(stamp, aud, added, removed,
                                                       "FAILED — read-back mismatch"))
        return EXIT_FAILED
    print(f"[audience] production sheet updated: {len(live)} phone number(s), "
          f"{sum(1 for e in live_em if e)} with email")
    print(f"Reconciliation (after writing): OK — both sheets hold the same {len(live)} lead(s).")
    append_history(sheets_write, sid, _history_row(stamp, aud, added, removed, "SUCCESS"))
    return EXIT_OK


def _history_row(stamp, aud, added, removed, result):
    s, (start, end) = aud["stats"], aud["window"]
    return [stamp, f"{start:%d-%b-%Y}", f"{end:%d-%b-%Y}", aud["days"], s["evaluated"],
            s["relevant"], s["excluded_not_interested"], s["excluded_enrolled"],
            s["excluded_admission_confirmed"],
            s["excluded_invalid_phone"], s["duplicates_removed"], s["final"], added, removed,
            result]


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Refresh the Google Ads remarketing audience.")
    ap.add_argument("--dry-run", action="store_true",
                    help="read everything live and print the result; write nothing")
    a = ap.parse_args(argv)
    today = clpr.now_ist().date()
    print(f"Google Ads Remarketing Audience — run {clpr.now_ist():%d-%b-%Y %I:%M %p} IST"
          f"{'  (DRY RUN)' if a.dry_run else ''}")
    try:
        sheets_read = clpr.get_read_service()
        sheets_write = None if a.dry_run else sheets_writer()
        drive = None if a.dry_run else clpr.get_drive_service()
    except BaseException as exc:                           # noqa: BLE001 (incl. sys.exit)
        print(f"[audience] FAILED — Google authentication ({exc}). Last audience kept.")
        return EXIT_RETRYABLE
    rc = refresh(sheets_read, sheets_write, drive, today, dry_run=a.dry_run)
    print({EXIT_OK: "RESULT: SUCCESS", EXIT_FAILED: "RESULT: FAILED",
           EXIT_RETRYABLE: "RESULT: FAILED (nothing changed; safe to re-run)"}[rc])
    return rc


if __name__ == "__main__":
    sys.exit(main())
