#!/usr/bin/env python3
"""
pyExotelCallDetails.py
======================
Extract Exotel call detail records (paginated) and upsert them into a Google
Sheet — reusing the IntelliBI Automation project's shared Google auth and
helpers (utils.py) and its service account
(config_files/service_account.json → intellibi-data-pipeline@intellibi-mis).

Run from the IntelliBI Automation project root (so `import utils` works):

    .venv\\Scripts\\python.exe pyExotelCallDetails.py

Design notes
------------
* Exotel credentials are NOT hard-coded. They are read from environment
  variables if present, otherwise from config_files/exotel_credentials.json
  (same pattern the project already uses for service_account.json).
* Pagination: follows Exotel's Metadata.NextPageUri cursor, and splits wide
  date ranges into <=30-day windows (Exotel caps a query at ~1 month).
* Deduplication / upsert: delegated to utils.upsert_rows(), keyed on `Sid`.
  Re-running never creates duplicates; changed calls are updated in place.
* Logging + targeted error handling for auth, API, pagination and Sheet access.
"""

# --- IntelliBI Sales Automation portability bootstrap (auto-inserted) ---
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap  # noqa: E402  (sys.path + env defaults + config.yaml)
from paths import CREDENTIALS_DIR, CONFIG_DIR, LOGS_DIR  # noqa: E402
# --- end bootstrap ---

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# Project-local shared helpers (auth, retry, upsert). Requires running from the
# project root where utils.py lives.
try:
    import utils
except ModuleNotFoundError:
    print("[ERROR] Could not import utils.py. Run this script from the "
          "IntelliBI Automation project root folder.")
    sys.exit(1)

import exotel_common as ec
try:
    import exotel_session as esess   # headless auto-login for the Inbox cookie
except Exception:                     # module missing -> feature simply off
    esess = None

try:
    from googleapiclient.errors import HttpError
except ModuleNotFoundError:
    HttpError = Exception  # fallback; will still work, just less specific


# ══════════════════════════════════════════════════════════════════════════
#  CONFIGURATION  (all non-secret, editable values in one place)
# ══════════════════════════════════════════════════════════════════════════
HERE = os.path.dirname(os.path.abspath(__file__))

# --- Google Sheet destination ---------------------------------------------
# The "Exotel Call Details" sheet created inside the IntelliBI_Sales_Data
# Drive folder. Must be shared with the service account (Editor).
SPREADSHEET_ID = "1L-Ew4-GF7MzzAnnIhVBafOmN_DJlMBTaRI6048PUo4I"
TAB_NAME = "Calls"

# --- Load mode -------------------------------------------------------------
# "incremental" -> only the recent rolling window (LOOKBACK_DAYS). Fast; use
#                  for the scheduled/recurring job.
# "full"        -> load ALL available history (FULL_LOAD_DAYS, up to Exotel's
#                  ~6 month retention). Use for the first backfill or a rebuild.
# Precedence (highest first): command-line arg > EXOTEL_LOAD_MODE env var >
# this constant. So you can run:
#     python pyExotelCallDetails.py full
#     python pyExotelCallDetails.py incremental
LOAD_MODE = "full"

# --- Exotel extraction window ---------------------------------------------
LOOKBACK_DAYS = 7            # incremental window (when DATE_FROM/DATE_TO blank)
FULL_LOAD_DAYS = 180         # full-load window (~6 months = Exotel retention)
DATE_FROM = ""               # explicit "YYYY-MM-DD" (overrides LOAD_MODE window)
DATE_TO = ""               # explicit "YYYY-MM-DD"
PAGE_SIZE = 100             # Exotel max 100
STATUS_FILTER = ""         # e.g. "completed"; blank = all statuses


def get_load_mode():
    """Resolve the load mode: CLI arg > env var > LOAD_MODE constant."""
    candidates = list(sys.argv[1:]) + [os.environ.get("EXOTEL_LOAD_MODE", "")]
    for raw in candidates:
        val = str(raw).strip().lower()
        if val in ("full", "f"):
            return "full"
        if val in ("incremental", "inc", "i"):
            return "incremental"
    return LOAD_MODE


# ══════════════════════════════════════════════════════════════════════════
#  INBOX COOKIE AUTO-LOGIN (optional; mirrors the Interakt session refresh)
# ══════════════════════════════════════════════════════════════════════════
def ensure_exotel_session_fresh():
    """Refresh the Inbox cookie from the saved browser login if it's stale.
    Never raises — the Address-Book/API names load regardless."""
    if not (AUTO_LOGIN_EXOTEL and esess is not None):
        return
    try:
        if not esess.playwright_installed():
            return  # Inbox step off; API + Address-Book names still load
        if not esess.profile_ready():
            log.info("Exotel Inbox auto-login not set up yet — run once: "
                     ".venv\\Scripts\\python.exe exotel_session.py --setup "
                     "(names still load from the Address Book API).")
            return
        if not esess.session_is_fresh(COOKIE_STALE_HOURS):
            log.info("Exotel Inbox cookie stale — refreshing from saved login...")
            esess.refresh_session(stale_hours=COOKIE_STALE_HOURS, logger=log)
    except Exception as exc:                              # noqa: BLE001
        log.warning("Exotel auto-login failed: %s — Address-Book names still "
                    "load.", exc)


def force_exotel_login():
    """Force-refresh the Inbox cookie from the saved login (after a dead-cookie
    run). Returns True on success; False if setup is missing or it failed."""
    if not (AUTO_LOGIN_EXOTEL and esess is not None):
        return False
    try:
        if not esess.login_available():
            return False
        esess.refresh_session(force=True, logger=log)
        return True
    except Exception as exc:                              # noqa: BLE001
        log.warning("Exotel auto-login (forced) failed: %s", exc)
        return False

# --- HTTP / retry ----------------------------------------------------------
HTTP_TIMEOUT = 30
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2.0
MAX_PAGES_SAFETY = 10000

# --- Timezone handling -----------------------------------------------------
# Exotel timestamps and filters calls in IST. We anchor the extraction window
# to IST computed from UTC, so a machine whose local clock/timezone differs
# from IST cannot cap the window early and drop the most recent calls.
# UPPER_BOUND_BUFFER pushes the 'lte' bound slightly into the future as extra
# insurance against clock skew (Exotel never returns future-dated calls, so
# this is always safe).
IST = timezone(timedelta(hours=5, minutes=30))
# Small margin only — enough to catch a call created in the last moments,
# without pushing the query window into the future (Exotel rejects far-future
# DateCreated ranges with "time range is out of bounds").
UPPER_BOUND_BUFFER = timedelta(minutes=5)

# --- Credentials source ----------------------------------------------------
CRED_FILE = os.path.join(CREDENTIALS_DIR, "exotel_credentials.json")

# --- Name enrichment: OFFICIAL CCM API (primary, credential-stable) --------
# FromName / ToName / Assign To are pulled from Exotel's Cloud-Contact-Center
# "Get Call Details" API using the SAME api_key/api_token as the call pull —
# so they never depend on a browser cookie and never expire. This is the
# primary source; the Inbox cookie below is now only an optional fallback for
# the extra fields (Outcome / Notes / Transcription / Lead Status) that the CCM
# API does not expose.
#   ENRICH_VIA_CCM_API : master switch for the API name enrichment.
#   CCM_MAX_WORKERS    : parallel CCM requests (per-call endpoint).
#   CCM_MAX_CALLS      : 0 = enrich every call in the window; N = cap (testing).
# If the account does not have CCM enabled the first call returns 401/403 and
# the script logs once and continues with no regression.
ENRICH_VIA_CCM_API = True
CCM_MAX_WORKERS = 8
CCM_MAX_CALLS = 0

# --- Name enrichment: CONTACTS / ADDRESS BOOK API (stable, no cookie) ------
# Fills FromName / ToName from the Exotel Address Book using the same
# api_key/api_token. Works with zero session, so names load even when the Inbox
# cookie login can't run. Non-destructive (only fills blanks).
ENRICH_VIA_CONTACTS = True

# --- Inbox cookie AUTO-LOGIN (headless) ------------------------------------
# When config_files/exotel_login.json + Playwright are present, the script logs
# into my.exotel.com itself and refreshes config_files/exotel_web_cookie.txt, so
# the full Inbox enrichment (Outcome / Notes / Transcription / Assign To / Lead
# Status + names) loads on a schedule with no manual cookie paste. Refreshes when
# the cookie is older than COOKIE_STALE_HOURS, and again if a run finds it dead.
# Set AUTO_LOGIN_EXOTEL = False to disable and use a manually-pasted cookie.
AUTO_LOGIN_EXOTEL = True
COOKIE_STALE_HOURS = 12

# --- Inbox NOTES (per-call annotations) ------------------------------------
# The "Notes" column is NOT part of the Inbox list page — each call's notes live
# behind a separate annotation endpoint. After the live Inbox fetch (which gives
# every call's message id), the script fetches notes for those calls with the
# same cookie + CSRF and fills any blank Notes. Only calls present on the Inbox
# page can be fetched this way (older calls need their Inbox HTML saved).
#   ENRICH_NOTES     : master switch for the per-call notes fetch.
#   NOTES_MAX_CALLS  : 0 = every call on the Inbox page; N = cap (testing).
#   NOTES_WORKERS    : parallel annotation requests.
ENRICH_NOTES = True
NOTES_MAX_CALLS = 0
NOTES_WORKERS = 12

# --- Inbox enrichment (optional fallback) ---------------------------------
# The Outcome / Notes / Transcription / Lead Status / CallType columns are not
# in any API; they come from the dashboard Inbox (/callindex) HTML. Two
# sources, both optional and combined (live overrides saved):
#   1) INBOX_HTML_DIR    — folder of manually saved Inbox .html pages.
#   2) WEB_COOKIE_FILE   — a saved my.exotel.com login cookie; if present the
#      script fetches the live Inbox page itself each run. The cookie expires
#      periodically; when it does the script logs a warning and continues
#      (FromName/ToName/Assign To still come from the CCM API above; the other
#      Inbox-only fields are simply preserved from previous runs).
INBOX_HTML_DIR = os.path.join(CREDENTIALS_DIR, "inbox_html")
WEB_COOKIE_FILE = os.path.join(CREDENTIALS_DIR, "exotel_web_cookie.txt")
WEB_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/150.0.0.0 Safari/537.36")

# --- Logging ---------------------------------------------------------------
LOG_FILE = os.path.join(str(LOGS_DIR), "exotel_call_sync.log")

# --- Output schema (order written to the sheet). 'synced_at' is excluded
#     from utils' change-detection automatically. 'Sid' is the upsert key. ---
COLUMNS = [
    "Sid",
    "ParentCallSid",
    "DateCreated",
    "DateUpdated",
    "Direction",
    # --- parties (numbers kept unchanged; *Name added, blank if no source) ---
    "From",
    "FromName",
    "To",
    "ToName",
    "PhoneNumber",
    "PhoneNumberSid",
    # --- status / outcome ---
    "Status",
    "Outcome",          # blank: not exposed by the API for these calls
    # --- timing ---
    "StartTime",
    "EndTime",
    "Duration",
    "ConversationDuration",
    "Price",
    # --- leg-level status (the API's closest thing to a per-leg outcome) ---
    "AnsweredBy",
    "Leg1Status",
    "Leg2Status",
    # --- contact-center fields ---
    "Assign To",
    "Lead Status",       # ticket status: open / pending / closed
    "Notes",
    "Transcription",
    # --- misc / existing ---
    "ForwardedFrom",
    "CallerName",
    "CustomField",
    "CallType",
    "RecordingUrl",
    "synced_at",
]
MATCH_KEYS = ["Sid"]

# Columns that have no *base-call* API field, so they start blank and are then
# filled by enrichment. FromName / ToName / Assign To are now filled from the
# official CCM API (primary); Outcome / Notes / Transcription remain Inbox-only
# (optional cookie fallback) and stay blank until that source is present.
UNAVAILABLE_BLANK = ["FromName", "ToName", "Outcome",
                     "Assign To", "Notes", "Transcription"]


# ══════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════
def setup_logging():
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except Exception as exc:
        print(f"WARNING: could not open log file {LOG_FILE}: {exc}")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        handlers=handlers,
    )
    return logging.getLogger("exotel_call_sync")


log = setup_logging()


# ══════════════════════════════════════════════════════════════════════════
#  CREDENTIALS
# ══════════════════════════════════════════════════════════════════════════
def load_credentials():
    """Read Exotel creds from env vars, falling back to the JSON key file."""
    key = os.environ.get("EXOTEL_API_KEY")
    tok = os.environ.get("EXOTEL_API_TOKEN")
    sid = os.environ.get("EXOTEL_SID")
    sub = os.environ.get("EXOTEL_SUBDOMAIN")

    if not (key and tok and sid):
        try:
            with open(CRED_FILE, encoding="utf-8") as f:
                c = json.load(f)
        except FileNotFoundError:
            raise RuntimeError(
                f"Exotel credentials not found. Set EXOTEL_API_KEY / "
                f"EXOTEL_API_TOKEN / EXOTEL_SID env vars, or create {CRED_FILE}."
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in {CRED_FILE}: {exc}")
        key = key or c.get("api_key")
        tok = tok or c.get("api_token")
        sid = sid or c.get("sid")
        sub = sub or c.get("subdomain")

    sub = sub or "api.exotel.com"
    missing = [n for n, v in
               [("api_key", key), ("api_token", tok), ("sid", sid)] if not v]
    if missing:
        raise RuntimeError(f"Missing Exotel credential(s): {', '.join(missing)}")
    return key, tok, sid, sub


# ══════════════════════════════════════════════════════════════════════════
#  EXOTEL CLIENT
# ══════════════════════════════════════════════════════════════════════════
class ExotelAuthError(Exception):
    pass


class ExotelAPIError(Exception):
    pass


class ExotelClient:
    def __init__(self, api_key, api_token, sid, subdomain):
        self.base_url = f"https://{subdomain}/v1/Accounts/{sid}"
        self.subdomain = subdomain
        self.session = requests.Session()
        self.session.auth = (api_key, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def _request(self, url, params=None):
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.get(url, params=params, timeout=HTTP_TIMEOUT)
            except requests.RequestException as exc:
                if attempt > MAX_RETRIES:
                    raise ExotelAPIError(f"Network error after {attempt} "
                                         f"attempts: {exc}")
                wait = RETRY_BACKOFF_BASE ** attempt
                log.warning("Network error (%s). Retry %d/%d in %.0fs",
                            exc, attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            if resp.status_code in (401, 403):
                raise ExotelAuthError(
                    f"Exotel authentication failed (HTTP {resp.status_code}). "
                    f"Check API key/token/SID/region. Body: {resp.text[:250]}")

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt > MAX_RETRIES:
                    raise ExotelAPIError(
                        f"Exotel API error HTTP {resp.status_code} after "
                        f"{attempt} attempts. Body: {resp.text[:250]}")
                retry_after = resp.headers.get("Retry-After")
                wait = (float(retry_after) if retry_after and
                        retry_after.isdigit() else RETRY_BACKOFF_BASE ** attempt)
                log.warning("HTTP %s from Exotel. Retry %d/%d in %.0fs",
                            resp.status_code, attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                raise ExotelAPIError(f"Unexpected HTTP {resp.status_code} from "
                                     f"Exotel. Body: {resp.text[:250]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise ExotelAPIError(f"Could not parse Exotel JSON: {exc}. "
                                     f"Body: {resp.text[:250]}")

    @staticmethod
    def _parse_payload(payload):
        if not isinstance(payload, dict):
            return {}, []
        metadata = payload.get("Metadata") or payload.get("metadata") or {}
        calls = (payload.get("Calls") or payload.get("calls")
                 or payload.get("Call") or [])
        if isinstance(calls, dict):
            calls = [calls]
        return metadata, calls

    def _fetch_window(self, start, end):
        date_filter = (f"gte:{start.strftime('%Y-%m-%d %H:%M:%S')};"
                       f"lte:{end.strftime('%Y-%m-%d %H:%M:%S')}")
        params = {"DateCreated": date_filter, "PageSize": PAGE_SIZE,
                  "SortBy": "DateCreated:asc", "Details": "true"}
        if STATUS_FILTER:
            params["Status"] = f"eq:{STATUS_FILTER}"

        next_url = f"{self.base_url}/Calls.json"
        next_params = params
        page = 0
        while next_url and page < MAX_PAGES_SAFETY:
            page += 1
            payload = self._request(next_url, params=next_params)
            metadata, calls = self._parse_payload(payload)
            log.info("Window %s..%s | page %d | %d records",
                     start.date(), end.date(), page, len(calls))
            for call in calls:
                yield call
            next_page = (metadata.get("NextPageUri")
                         or metadata.get("nextPageUri")
                         or metadata.get("next_page_uri"))
            if not next_page:
                break
            next_url = (next_page if next_page.startswith("http")
                        else f"https://{self.subdomain}{next_page}")
            next_params = None
        if page >= MAX_PAGES_SAFETY:
            log.warning("Hit MAX_PAGES_SAFETY (%d).", MAX_PAGES_SAFETY)

    def fetch_calls(self):
        start, end = resolve_date_range()
        # Never query past 'now'. Exotel rejects a DateCreated range whose upper
        # bound is in the future with HTTP 400 "time range is out of bounds"; that
        # error used to propagate out of this generator and abort the WHOLE sync,
        # so on those runs nothing (including today's calls) reached the sheet.
        # Clamping the end to now removes the degenerate future trailing window
        # that provoked it, while the per-window guard below tolerates any that
        # still slips through due to clock skew.
        now = _now_ist()
        if end > now:
            end = now
        log.info("Extraction range: %s -> %s", start, end)
        windows = []
        cursor = start
        span = timedelta(days=30)
        while cursor < end:
            w_end = min(cursor + span, end)
            windows.append((cursor, w_end))
            cursor = w_end + timedelta(seconds=1)

        seen = set()

        def _emit(a, b):
            for call in self._fetch_window(a, b):
                sid = call.get("Sid") or call.get("sid")
                if sid and sid in seen:
                    continue
                if sid:
                    seen.add(sid)
                yield call

        for w_start, w_end in windows:
            # A window that begins in the future carries no calls and would only
            # trigger an out-of-bounds rejection — skip it outright.
            if w_start > now:
                continue
            try:
                yield from _emit(w_start, w_end)
            except ExotelAPIError as exc:
                m = str(exc).lower()
                if "out of bounds" not in m and "invalid parameter" not in m:
                    raise   # a genuine API error must still surface
                # Out-of-bounds on a window that starts in the PAST (it may hold
                # today's calls) — retry once with the end pulled safely below now
                # so a small clock skew can't drop this window's data. Only truly
                # unrecoverable windows are skipped, never silently losing history.
                safe_end = min(w_end, now - timedelta(minutes=2))
                if safe_end <= w_start:
                    log.warning("Skipping out-of-bounds window %s..%s: %s",
                                w_start.date(), w_end.date(), exc)
                    continue
                log.warning("Window %s..%s rejected as out-of-bounds; retrying "
                            "with end clamped to %s.",
                            w_start.date(), w_end.date(), safe_end)
                try:
                    yield from _emit(w_start, safe_end)
                except ExotelAPIError as exc2:
                    log.warning("Retry also failed for window %s..%s (%s) — "
                                "skipping.", w_start.date(), w_end.date(), exc2)


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════
def _now_ist():
    """Current time as IST wall-clock (naive), derived from UTC so it is
    correct regardless of the machine's configured local timezone."""
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def resolve_date_range():
    if DATE_FROM and DATE_TO:
        # Explicit dates are treated as IST calendar dates (Exotel's timezone).
        start = datetime.strptime(DATE_FROM, "%Y-%m-%d")
        end = datetime.strptime(DATE_TO, "%Y-%m-%d") + timedelta(
            hours=23, minutes=59, seconds=59)
        return start, end
    now_ist = _now_ist()
    days = FULL_LOAD_DAYS if get_load_mode() == "full" else LOOKBACK_DAYS
    start = now_ist - timedelta(days=days)
    end = now_ist + UPPER_BOUND_BUFFER
    return start, end


def normalise_call(call, synced_at):
    def g(*keys):
        for k in keys:
            if k in call and call[k] not in (None, ""):
                return call[k]
        return ""

    # Leg-level details (only present when the request asks for Details=true).
    details = call.get("Details") or call.get("details") or {}
    if not isinstance(details, dict):
        details = {}

    def clean(v):
        # Treat Exotel's "N/A" placeholder as empty for tidiness.
        return "" if str(v).strip().upper() in ("N/A", "NA", "NONE") else v

    row = {
        "Sid": g("Sid", "sid"),
        "ParentCallSid": g("ParentCallSid", "parent_call_sid"),
        "DateCreated": g("DateCreated", "date_created"),
        "DateUpdated": g("DateUpdated", "date_updated"),
        "Direction": g("Direction", "direction"),
        "From": g("From", "from"),
        "To": g("To", "to"),
        "PhoneNumber": g("PhoneNumber", "phone_number"),
        "PhoneNumberSid": g("PhoneNumberSid", "phone_number_sid"),
        "Status": g("Status", "status"),
        "StartTime": g("StartTime", "start_time"),
        "EndTime": g("EndTime", "end_time"),
        "Duration": g("Duration", "duration"),
        "ConversationDuration": details.get("ConversationDuration", ""),
        "Price": g("Price", "price"),
        "AnsweredBy": g("AnsweredBy", "answered_by"),
        "Leg1Status": details.get("Leg1Status", ""),
        "Leg2Status": details.get("Leg2Status", ""),
        "ForwardedFrom": g("ForwardedFrom", "forwarded_from"),
        "CallerName": g("CallerName", "caller_name"),
        "CustomField": clean(g("CustomField", "custom_field")),
        "CallType": g("CallType", "call_type"),
        "RecordingUrl": g("RecordingUrl", "recording_url"),
        "synced_at": synced_at,
    }
    # Columns with no API source stay blank (never fail the record).
    for col in UNAVAILABLE_BLANK:
        row.setdefault(col, "")
    return {c: row.get(c, "") for c in COLUMNS}


def preflight_sheet_access(service):
    """Verify the service account can actually reach the target sheet, so we
    can give a clear 'share the sheet' message instead of a silent no-op."""
    try:
        meta = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID).execute()
        log.info("Target spreadsheet OK: '%s'",
                 meta.get("properties", {}).get("title", SPREADSHEET_ID))
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status in (403, 404):
            raise RuntimeError(
                "Service account cannot access the spreadsheet "
                f"(HTTP {status}). Share the sheet "
                f"(ID {SPREADSHEET_ID}) — or the IntelliBI_Sales_Data folder — "
                "with intellibi-data-pipeline@intellibi-mis.iam.gserviceaccount.com "
                "as Editor, then re-run.")
        raise


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    mode = get_load_mode()
    log.info("Starting Exotel -> Google Sheet sync  [LOAD_MODE=%s]", mode.upper())
    if mode == "full":
        log.info("Full load: pulling up to %d days of history.", FULL_LOAD_DAYS)
    started = time.time()
    try:
        synced_at = _now_ist().strftime("%Y-%m-%d %H:%M:%S")

        key, tok, sid, sub = load_credentials()
        # Keep a stable copy: the enrichment loop below rebinds `key` to a Sid.
        key_tok_sid = (key, tok, sid, sub)
        log.info("Exotel account SID=%s host=%s", sid, sub)

        client = ExotelClient(key, tok, sid, sub)
        raw = list(client.fetch_calls())
        log.info("Fetched %d call records from Exotel.", len(raw))
        if not raw:
            log.info("No records for the configured range. Done.")
            return 0

        rows = [normalise_call(c, synced_at) for c in raw]

        # Two enrichment sources:
        #  - scrape_enrich: from saved/scraped Inbox HTML + per-call notes JSON.
        #    COMPLETE (includes real Notes) -> authoritative for a call.
        #  - live_enrich: from the light live list fetch. Has everything EXCEPT
        #    the per-call user Notes -> fills LIVE_COLUMNS, must not touch Notes.
        scrape_enrich = ec.load_enrichment(INBOX_HTML_DIR)
        inbox_url = f"https://my.exotel.com/{sid}/callindex"
        # Auto-login refreshes the cookie when missing/stale so the Inbox scrape
        # (FromName/ToName/Outcome/Notes/Assign To/Lead Status) works unattended.
        ensure_exotel_session_fresh()
        live_enrich = ec.fetch_live_enrichment(inbox_url, WEB_COOKIE_FILE,
                                               WEB_USER_AGENT, logger=log)
        if not live_enrich and force_exotel_login():
            log.info("Retrying live Inbox fetch after fresh login...")
            live_enrich = ec.fetch_live_enrichment(inbox_url, WEB_COOKIE_FILE,
                                                   WEB_USER_AGENT, logger=log)
        if live_enrich:
            log.info("Fetched live Inbox enrichment for %d calls.",
                     len(live_enrich))

        applied = 0
        for r in rows:
            key = r["Sid"]
            if key in scrape_enrich:
                e = scrape_enrich[key]
                for col in ec.ENRICH_COLUMNS:
                    r[col] = e.get(col, "")   # authoritative (blank clears stale)
                applied += 1
            elif key in live_enrich:
                e = live_enrich[key]
                for col in ec.LIVE_COLUMNS:   # everything except Notes
                    if e.get(col):
                        r[col] = e[col]
                applied += 1
        if applied:
            log.info("Applied Inbox enrichment to %d of %d calls.",
                     applied, len(rows))

        # NOTES: the Inbox list page does NOT carry per-call notes — fetch them
        # from the annotation endpoint (same cookie + CSRF) for the calls on the
        # Inbox page, and fill any row whose Notes is still blank. Non-destructive:
        # a real note captured from saved HTML (scrape_enrich) is never overwritten.
        if ENRICH_NOTES and live_enrich:
            cookie = ec.load_cookie(WEB_COOKIE_FILE)
            sid_to_msgid = {sid: e.get("MsgId", "")
                            for sid, e in live_enrich.items() if e.get("MsgId")}
            if cookie and sid_to_msgid:
                notes = ec.fetch_all_notes(sid_to_msgid, cookie, WEB_USER_AGENT,
                                           max_calls=NOTES_MAX_CALLS,
                                           workers=NOTES_WORKERS, logger=log)
                napplied = 0
                for r in rows:
                    note = notes.get(r["Sid"])
                    if note and not str(r.get("Notes", "")).strip():
                        r["Notes"] = note
                        napplied += 1
                log.info("Applied Inbox Notes to %d of %d calls.", napplied, len(rows))
            elif not cookie:
                log.info("Notes fetch skipped: no Inbox cookie available.")
            elif not sid_to_msgid:
                log.info("Notes fetch skipped: no message ids on the Inbox page.")

        # PRIMARY name source: the official CCM API (stable key/token, no cookie).
        # Fills FromName / ToName / Assign To wherever the (usually unavailable)
        # cookie scrape left them blank — never overwrites a real scraped value.
        if ENRICH_VIA_CCM_API:
            ccm_enrich = ec.fetch_ccm_enrichment(
                key_tok_sid[0], key_tok_sid[1], key_tok_sid[3], key_tok_sid[2],
                rows, max_workers=CCM_MAX_WORKERS, max_calls=CCM_MAX_CALLS,
                logger=log)
            if ccm_enrich:
                ccm_applied = 0
                for r in rows:
                    e = ccm_enrich.get(r["Sid"])
                    if not e:
                        continue
                    touched = False
                    for col in ec.CCM_COLUMNS:      # FromName / ToName / Assign To
                        if e.get(col) and not str(r.get(col, "")).strip():
                            r[col] = e[col]
                            touched = True
                    if touched:
                        ccm_applied += 1
                log.info("Applied CCM API names to %d of %d calls.",
                         ccm_applied, len(rows))

        # BACKUP name source: the Address Book / Contacts API (stable key/token,
        # no cookie). Fills FromName/ToName from a number->name map wherever they
        # are still blank — so names load even if the Inbox login can't run.
        if ENRICH_VIA_CONTACTS:
            contacts = ec.fetch_contacts_map(
                key_tok_sid[0], key_tok_sid[1], key_tok_sid[3], key_tok_sid[2],
                logger=log)
            if contacts:
                c_applied = 0
                for r in rows:
                    touched = False
                    f10 = ec._digits10(r.get("From", ""))
                    t10 = ec._digits10(r.get("To", ""))
                    if not str(r.get("FromName", "")).strip() and contacts.get(f10):
                        r["FromName"] = contacts[f10]
                        touched = True
                    if not str(r.get("ToName", "")).strip() and contacts.get(t10):
                        r["ToName"] = contacts[t10]
                        touched = True
                    if touched:
                        c_applied += 1
                log.info("Applied Address-Book names to %d of %d calls.",
                         c_applied, len(rows))

        # Reuse the project's shared, authenticated Sheets client.
        service = utils.get_sheets_service()
        preflight_sheet_access(service)

        # Non-destructive preserve: keep enrichment already in the sheet so an
        # API/live-only run never blanks it. Skip calls the scraper fully
        # supplied (their values, incl. intentional blanks, are authoritative).
        existing = ec.read_existing_rows(service, SPREADSHEET_ID, TAB_NAME)
        if existing:
            for r in rows:
                if r["Sid"] in scrape_enrich:
                    continue
                ex = existing.get(r["Sid"])
                if not ex:
                    continue
                for col in ec.ENRICH_COLUMNS:
                    if not str(r.get(col, "")).strip() and str(ex.get(col, "")).strip():
                        r[col] = ex[col]

        # Reuse the project's dedupe + append/update-by-key logic.
        utils.upsert_rows(service, SPREADSHEET_ID, TAB_NAME,
                          COLUMNS, rows, match_keys=MATCH_KEYS)

        log.info("Done in %.1fs. Sheet: "
                 "https://docs.google.com/spreadsheets/d/%s",
                 time.time() - started, SPREADSHEET_ID)
        return 0

    except ExotelAuthError as exc:
        log.error("EXOTEL AUTH ERROR: %s", exc)
        return 2
    except ExotelAPIError as exc:
        log.error("EXOTEL API ERROR: %s", exc)
        return 3
    except RuntimeError as exc:
        log.error("CONFIG/SHEET ERROR: %s", exc)
        return 4
    except Exception as exc:
        log.exception("UNEXPECTED ERROR: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
