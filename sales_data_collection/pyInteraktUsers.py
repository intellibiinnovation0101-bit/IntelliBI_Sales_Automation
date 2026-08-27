#!/usr/bin/env python3
"""
pyInteraktUsers.py
==================
Extract all contacts (users) from Interakt via the public Get Users API and
sync them into a Google Sheet inside a specified Google Drive folder.

Built to live in the IntelliBI Automation project and REUSE its shared
utilities, exactly like the Exotel sync:
  * utils.get_sheets_service()  -> service-account Sheets client
  * utils.upsert_rows(...)      -> upsert-by-key, auto column re-align
Only the "create the sheet inside the Drive folder" step (which utils does not
cover) is added, via interakt_common.get_or_create_spreadsheet().

Secrets are NOT hard-coded: the Interakt Secret Key is read from the
INTERAKT_API_KEY environment variable if present, otherwise from
config_files/interakt_credentials.json.

LOAD MODES
----------
  full         Pull every user (very wide date window).
  incremental  Pull only users modified within the last LOOKBACK_DAYS days.

Mode precedence (highest first):
  command-line arg  >  INTERAKT_LOAD_MODE env var  >  LOAD_MODE constant.

USAGE
-----
  python pyInteraktUsers.py                 # uses LOAD_MODE below (incremental)
  python pyInteraktUsers.py full            # force a full backfill
  python pyInteraktUsers.py incremental     # force an incremental sync
"""

from __future__ import annotations

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

import utils   # project-shared Google auth + upsert (same one Exotel uses)
import interakt_common as ic
import interakt_enrich as ie
try:
    import interakt_session as isess   # headless auto-login (optional)
except Exception:                       # module missing -> feature simply off
    isess = None

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION  (all non-secret, editable values in one place)
# ─────────────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))

# Target Google Drive folder — must be shared with the service account (Editor).
DRIVE_FOLDER_ID = "1_1d6ExCX9apj8QkMczTJZn1Ctprwf3CM"
SPREADSHEET_NAME = "Interakt_WhatsApp_Data"
TAB_NAME = "Users"

# Load window. FULL grabs everything; incremental only the recent slice.
LOAD_MODE = "full"      # "full" | "incremental"
FULL_LOAD_DAYS = 3650          # ~10 years -> effectively all users
LOOKBACK_DAYS = 7              # incremental window

# Inbox enrichment (agent notes, activity/campaign timeline, lead stage, contact
# owner). Needs a live web session in config_files/interakt_curl.txt. If that is
# missing/expired the base sync still runs; enrichment is just skipped.
ENABLE_ENRICHMENT = True

# Auto-login: when config_files/interakt_login.json + Playwright are present, the
# script signs into Interakt itself and refreshes config_files/interakt_curl.txt,
# so a scheduled run never needs a manual "Copy as cURL" paste. It refreshes when
# the session file is older than SESSION_STALE_HOURS, and again (forced) if a run
# is rejected with a 401. Set AUTO_LOGIN = False to disable and go back to manual
# cURL capture. See interakt_session.py for one-time setup.
AUTO_LOGIN = True
SESSION_STALE_HOURS = 12

# Dedup key: first of these present in the data is used to prevent duplicates.
KEY_CANDIDATES = ["id", "user_id", "userId", "phone_number", "phoneNumber"]

CRED_FILE = os.path.join(CREDENTIALS_DIR, "interakt_credentials.json")
SA_FILE = os.path.join(CREDENTIALS_DIR, "service_account.json")
STATE_FILE = os.path.join(CREDENTIALS_DIR, "interakt_spreadsheet.json")
LOG_FILE = os.path.join(str(LOGS_DIR), "interakt_sync.log")
# Marker recording the last time enrichment (web-session data) actually
# succeeded, so a run that has to skip enrichment can report how long it has
# been broken instead of degrading silently.
ENRICH_OK_MARKER = os.path.join(CREDENTIALS_DIR, "interakt_enrich_last_ok.txt")

log = logging.getLogger("interakt")


def _mark_enrichment_ok() -> None:
    """Stamp the marker file with 'now' after a successful enrichment. Never raises."""
    try:
        os.makedirs(os.path.dirname(ENRICH_OK_MARKER), exist_ok=True)
        with open(ENRICH_OK_MARKER, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).isoformat())
    except Exception:                            # noqa: BLE001 — marker is best-effort
        pass


def _last_enrichment_ok() -> "datetime | None":
    """Return the datetime of the last successful enrichment, or None if unknown."""
    try:
        raw = open(ENRICH_OK_MARKER, encoding="utf-8").read().strip()
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:                            # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  SETUP HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def setup_logging() -> None:
    fmt = "%(asctime)s | %(levelname)-7s | %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )


def get_load_mode() -> str:
    """Resolve the load mode: CLI arg > env var > LOAD_MODE constant."""
    candidates = list(sys.argv[1:]) + [os.environ.get("INTERAKT_LOAD_MODE", "")]
    for c in candidates:
        c = (c or "").strip().lower()
        if c in ("full", "incremental"):
            return c
    return LOAD_MODE


def enrichment_enabled() -> bool:
    """Enrichment on unless the ENABLE_ENRICHMENT constant is off OR the env var
    INTERAKT_ENRICH is set to 0/false/no (used by unattended scheduled runs that
    have no fresh web session)."""
    if not ENABLE_ENRICHMENT:
        return False
    return os.environ.get("INTERAKT_ENRICH", "").strip().lower() not in (
        "0", "false", "no", "off")


def auto_login_ready() -> bool:
    """True only when auto-login is switched on AND actually usable
    (interakt_session imported, login file present, Playwright installed)."""
    if not AUTO_LOGIN or isess is None:
        return False
    try:
        return isess.login_available()
    except Exception:
        return False


def ensure_session_fresh() -> None:
    """Proactively refresh the Interakt session (from the saved browser login)
    if it's missing or stale. Never raises — enrichment degrades gracefully."""
    if not (AUTO_LOGIN and isess is not None):
        return
    try:
        if not isess.playwright_installed():
            return
        if not isess.profile_ready():
            log.info("Interakt auto-login not set up yet — run once: "
                     ".venv\\Scripts\\python.exe interakt_session.py --setup "
                     "(base + custom data still load).")
            return
        if not isess.session_is_fresh(SESSION_STALE_HOURS):
            log.info("Interakt session stale — refreshing from saved login...")
            isess.refresh_session(stale_hours=SESSION_STALE_HOURS, logger=log)
    except Exception as exc:                              # noqa: BLE001
        log.warning("Auto-login (proactive) failed: %s — will try on 401.", exc)


def force_session_refresh() -> bool:
    """Force a fresh login (used after a 401). Returns True on success."""
    if not auto_login_ready():
        return False
    try:
        isess.refresh_session(force=True, logger=log)
        return True
    except Exception as exc:                              # noqa: BLE001
        log.warning("Auto-login (forced) failed: %s", exc)
        return False


def load_credentials() -> str:
    """Interakt Secret Key from env var, else config_files/interakt_credentials.json."""
    key = os.environ.get("INTERAKT_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Accept either "api_key" (matches exotel_credentials.json style) or
        # "interakt_api_key".
        return (data.get("api_key") or data.get("interakt_api_key") or "").strip()
    raise ic.InteraktError(
        "Interakt credentials not found. Set INTERAKT_API_KEY or create "
        f"{CRED_FILE} with {{\"api_key\": \"<your Secret Key>\"}}.")


# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOM-FIELD CHANGE LOGGING
# ─────────────────────────────────────────────────────────────────────────────
def _read_tab_by_key(service, spreadsheet_id, tab, key_col) -> dict:
    """Read the sheet tab into {key_value: {column: value}} (empty if blank/missing)."""
    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{tab}!A1:ZZ").execute()
    except Exception:
        return {}
    values = resp.get("values", [])
    if not values:
        return {}
    header = values[0]
    out = {}
    for r in values[1:]:
        rowd = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        k = str(rowd.get(key_col, "")).strip()
        if k:
            out[k] = rowd
    return out


# Repeat-enquiry tracking columns (derived): the latest customer-message time and
# a per-DAY interaction history (Option 1 + Option 2 from the requirement).
# Customer-only interaction columns (days the CUSTOMER messaged — true enquiries).
INTERACTION_COLUMNS = ["Last Interaction Date", "WhatsApp Interaction History"]
# Agent-inclusive activity columns (days with ANY activity: customer msg, agent
# reply, or a label change). Kept separate so a customer enquiry is never
# confused with an agent-side touch.
ACTIVITY_COLUMNS = ["Last Activity Date", "Activity History (incl. agent)"]

# Columns sourced from the web session (label/assignee/status + enrichment) plus
# the derived interaction/activity columns. On a run that doesn't refresh them
# (no web session), keep the sheet's values.
WEB_PRESERVE_COLUMNS = (list(ie.CONVERSATION_COLUMNS) + INTERACTION_COLUMNS
                        + ACTIVITY_COLUMNS + list(ie.ENRICH_COLUMNS))

# Fields whose per-lead changes we call out in the log.
WATCHED_COLUMNS = [label for _, label in ic.CUSTOM_FIELDS] + list(ie.CONVERSATION_COLUMNS)


# ─────────────────────────────────────────────────────────────────────────────
#  REPEAT-ENQUIRY TRACKING  (capture later customer messages, not just the first)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_ts(v):
    """Parse an Interakt/ISO or display timestamp; return datetime or None."""
    from datetime import datetime
    s = str(v or "").strip()
    if not s:
        return None
    s2 = s.replace("Z", "").replace("T", " ").split("+")[0].strip()
    for f in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
              "%d-%b-%Y %I:%M %p", "%d-%b-%Y"):
        try:
            return datetime.strptime(s2, f)
        except ValueError:
            pass
    return None


def _fmt_dt(dt):
    return dt.strftime("%d-%b-%Y %I:%M %p") if dt else ""


def _fmt_day(dt):
    return dt.strftime("%d-%b-%Y") if dt else ""


# Interakt/API timestamps are UTC; the team (and the Interakt Inbox) read IST.
from datetime import timedelta as _timedelta
_IST_OFFSET = _timedelta(hours=5, minutes=30)


def _parse_ist(v):
    """Parse a UTC timestamp and shift it to IST for display."""
    dt = _parse_ts(v)
    return (dt + _IST_OFFSET) if dt else None


def _merge_history(existing_hist, *timestamps):
    """Accumulate a per-DAY interaction history ('1. dd-Mon-yyyy hh:mm a | 2. ...'),
    one entry per calendar day, in IST. Idempotent — re-running with the same data
    does not duplicate a day."""
    days = {}                                   # 'dd-Mon-yyyy' -> datetime (IST)
    # Raw UTC sources (created_at, latest customer message) -> IST; authoritative
    # for their day so previously-stored UTC times self-heal to IST.
    for ts in timestamps:
        dt = _parse_ist(ts)
        if dt:
            days[_fmt_day(dt)] = dt
    # Existing history entries are already display strings (IST) — fill any other
    # days without overriding the authoritative ones above.
    for part in str(existing_hist or "").split(" | "):
        p = part.strip()
        if not p:
            continue
        p = p.split(". ", 1)[-1]                 # drop leading 'n. '
        dt = _parse_ts(p)
        if dt:
            days.setdefault(_fmt_day(dt), dt)
    if not days:
        return str(existing_hist or "")
    ordered = sorted(days.values())
    return " | ".join(f"{i}. {_fmt_dt(dt)}" for i, dt in enumerate(ordered, 1))


def apply_interaction_tracking(rows, existing, key_col):
    """Populate 'Last Interaction Date' (latest customer message) and append the
    per-day 'WhatsApp Interaction History' for each row. Never raises."""
    for row in rows:
        try:
            old = (existing or {}).get(str(row.get(key_col, "")).strip(), {})
            last_at = (str(row.get("Chat Last Customer Message At", "") or "").strip()
                       or str(old.get("Chat Last Customer Message At", "") or "").strip())
            created = (str(row.get("created_at_utc", "") or "").strip()
                       or str(old.get("created_at_utc", "") or "").strip())
            dt_last = _parse_ist(last_at)
            if dt_last:
                row["Last Interaction Date"] = _fmt_dt(dt_last)
            elif old.get("Last Interaction Date"):
                row["Last Interaction Date"] = old.get("Last Interaction Date")
            row["WhatsApp Interaction History"] = _merge_history(
                old.get("WhatsApp Interaction History", ""), created, last_at)

            # Agent-inclusive activity (customer msg OR agent reply OR label change).
            last_act = (str(row.get("Chat Last Activity At", "") or "").strip()
                        or str(old.get("Chat Last Activity At", "") or "").strip())
            dt_act = _parse_ist(last_act)
            if dt_act:
                row["Last Activity Date"] = _fmt_dt(dt_act)
            elif old.get("Last Activity Date"):
                row["Last Activity Date"] = old.get("Last Activity Date")
            # Activity history accumulates every activity day (customer + agent).
            # Seed it with the customer-message days too, so it is always a
            # superset of the customer-only history.
            row["Activity History (incl. agent)"] = _merge_history(
                old.get("Activity History (incl. agent)", ""),
                created, last_at, last_act)
        except Exception:                        # noqa: BLE001 — tracking must never break the sync
            continue


def build_repeat_refresh_rows(conv_map, existing, windowed_rows):
    """Repeat-enquiry capture (Option 1): a customer who messages again does NOT
    bump their profile 'modified_at', so the incremental Get-Users window misses
    them. But the Inbox chats list DOES carry their latest message. For every
    contact in the chats list that is not in this run's windowed rows, rebuild a
    FULL row from the existing sheet + refreshed conversation columns so their
    latest interaction is written. Matches on the internal customer id."""
    extra = []
    if not conv_map or not existing:
        return extra
    existing_by_id = {}
    for r in existing.values():
        cid = str(r.get("id", "")).strip()
        if cid:
            existing_by_id[cid] = r
    windowed_ids = {str(r.get("id", "")).strip() for r in windowed_rows}
    for cid, conv in conv_map.items():
        cid = str(cid).strip()
        if not cid or cid in windowed_ids:
            continue
        old = existing_by_id.get(cid)
        if not old:
            continue                             # not in sheet & not windowed -> skip
        row = dict(old)                          # keep all base/custom/enrich values
        for c in ("Conversation Label", "Assigned Agent", "Chat Status",
                  "Chat Last Customer Message At", "Chat Last Activity At"):
            val = conv.get(c)
            if val not in (None, ""):
                row[c] = val
        extra.append(row)
    return extra


def preserve_web_columns(existing: dict, rows, key_col) -> None:
    """Backfill web-session columns from the existing sheet when the current run
    left them blank, so a base-only (no-enrichment) sync never wipes a value
    (e.g. a Conversation Label) captured on a previous enriched run."""
    if not existing:
        return
    for row in rows:
        old = existing.get(str(row.get(key_col, "")).strip())
        if not old:
            continue
        for col in WEB_PRESERVE_COLUMNS:
            if not str(row.get(col, "") or "").strip() and str(old.get(col, "") or "").strip():
                row[col] = old[col]


def log_field_changes(existing: dict, rows, key_col) -> None:
    """Log which existing lead rows change because a custom field or conversation
    label/assignee/status changed (field + old -> new). New leads are logged by
    the upsert as inserts, so they are skipped here."""
    if not existing:
        return
    changed = 0
    for row in rows:
        k = str(row.get(key_col, "")).strip()
        old = existing.get(k)
        if not old:
            continue
        diffs = []
        for col in WATCHED_COLUMNS:
            nv = str(row.get(col, "") or "").strip()
            ov = str(old.get(col, "") or "").strip()
            if nv != ov:
                diffs.append((col, ov, nv))
        if diffs:
            changed += 1
            who = row.get("phone_number") or row.get("trait_name") or k
            for col, ov, nv in diffs:
                log.info("FIELD CHANGE | lead %s | '%s': %r -> %r", who, col, ov, nv)
    if changed:
        log.info("Fields changed on %s existing lead(s) this run.", changed)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    setup_logging()
    started = time.time()
    mode = get_load_mode()
    log.info("=" * 68)
    log.info("Starting Interakt -> Google Sheet sync  [LOAD_MODE=%s]", mode.upper())

    try:
        api_key = load_credentials()

        # --- date filter --------------------------------------------------
        now = datetime.now(timezone.utc)
        window_days = FULL_LOAD_DAYS if mode == "full" else LOOKBACK_DAYS
        modified_after = now - timedelta(days=window_days)
        log.info("Fetching users modified after %s UTC (%s-day window).",
                 modified_after.strftime("%Y-%m-%d %H:%M:%S"), window_days)

        # --- pull + flatten -----------------------------------------------
        client = ic.InteraktClient(api_key)
        body = client.build_filters(modified_after=modified_after)
        rows = [ic.flatten_user(u) for u in client.iter_users(body)]

        if not rows:
            log.info("No users returned for this window. Nothing to write.")
            log.info("Done in %.1fs.", time.time() - started)
            return 0

        # --- choose dedup key + column order ------------------------------
        available = set().union(*(r.keys() for r in rows))
        key_col = next((k for k in KEY_CANDIDATES if k in available), None)
        if key_col is None:
            key_col = sorted(available)[0]
            log.warning("No standard id column found; deduping on '%s'.", key_col)
        log.info("Deduplicating on key column: '%s'", key_col)

        # --- enrich each lead via the Inbox APIs (optional) ---------------
        enrichment_ran = False
        enrich_expected = enrichment_enabled()     # was enrichment supposed to run?
        conv_map = {}                              # customer id -> latest chat summary
        if enrich_expected:
            # Auto-login refreshes config_files/interakt_curl.txt when it's
            # missing/stale, so a scheduled run needs no manual cURL paste.
            ensure_session_fresh()
            for attempt in (1, 2):
                try:
                    enr = ie.InteraktEnricher()
                    enr.load_lookups()
                    enr.load_conversations()  # labels / assignee / status / last msg
                    log.info("Enriching %s leads via Interakt Inbox APIs...", len(rows))
                    for i, row in enumerate(rows, 1):
                        row.update(enr.resolve_traits(row))
                        row.update(enr.enrich(row.get("id", "")))
                        if i % 20 == 0:
                            log.info("  enriched %s/%s", i, len(rows))
                        time.sleep(0.15)   # stay under the per-minute cap
                    enrichment_ran = True
                    conv_map = dict(getattr(enr, "_conv", {}) or {})
                    _mark_enrichment_ok()          # record that the session worked
                    log.info("Enrichment complete.")
                    break
                except ie.WebAuthError as exc:
                    # Session missing/expired. On the first try, auto-log-in and
                    # retry once; else degrade gracefully (base data still writes).
                    if attempt == 1 and force_session_refresh():
                        log.warning("Session rejected (%s) — re-logged in, "
                                    "retrying enrichment once.", exc)
                        continue
                    log.warning("Enrichment skipped — %s Base data still written.",
                                exc)
                    break
                except Exception as exc:                  # noqa: BLE001
                    log.warning("Enrichment error — %s Base data still written.",
                                exc)
                    break

        # --- find-or-create the sheet + read existing rows (needed for the
        #     repeat-enquiry refresh + per-day history below) ---------------
        spreadsheet_id = ic.get_or_create_spreadsheet(
            SA_FILE, DRIVE_FOLDER_ID, SPREADSHEET_NAME, TAB_NAME,
            state_file=STATE_FILE)
        service = utils.get_sheets_service()
        existing = _read_tab_by_key(service, spreadsheet_id, TAB_NAME, key_col)

        # --- capture REPEAT enquiries (Option 1): update contacts whose chat
        #     shows a newer message even though their profile 'modified_at' did
        #     not change (so the windowed Get-Users call skipped them). --------
        try:
            refresh = build_repeat_refresh_rows(conv_map, existing, rows)
            if refresh:
                log.info("Repeat-enquiry refresh: %s contact(s) updated from the "
                         "Inbox chats list (outside the modified window).", len(refresh))
                rows.extend(refresh)
        except Exception as exc:                          # noqa: BLE001
            log.warning("Repeat-enquiry refresh skipped: %s", exc)

        # --- Last Interaction Date + per-day WhatsApp Interaction History
        #     (Option 2) for every row --------------------------------------
        apply_interaction_tracking(rows, existing, key_col)

        # --- column order: base | custom | conversation | interaction | enrich
        present = set().union(*(r.keys() for r in rows))
        skip = (set(ic.CUSTOM_LABEL_SET) | set(ie.CONVERSATION_COLUMNS)
                | set(INTERACTION_COLUMNS) | set(ACTIVITY_COLUMNS))
        base_rows = [{k: v for k, v in r.items()
                      if not k.startswith("enr_") and k not in skip}
                     for r in rows]
        base_cols = ic.order_columns(base_rows, key_col)
        custom_cols = list(ic.CUSTOM_LABEL_ORDER)     # always all, in defined order
        conv_cols = list(ie.CONVERSATION_COLUMNS)     # always present (blank if none)
        # Retain enrichment columns even on a session-less (base-only) run so a
        # 401 web session never STRIPS previously-captured enr_* data. Their
        # values are preserved by preserve_web_columns() below.
        existing_cols = set().union(*(r.keys() for r in existing.values())) if existing else set()
        enr_pool = present | existing_cols
        enrich_cols = ([c for c in ie.ENRICH_COLUMNS if c in enr_pool]
                       + sorted(c for c in enr_pool
                                if c.startswith("enr_") and c not in ie.ENRICH_COLUMNS))
        columns = (base_cols + custom_cols + conv_cols
                   + INTERACTION_COLUMNS + ACTIVITY_COLUMNS + enrich_cols)

        # --- write via the shared project upsert --------------------------
        if not enrichment_ran:
            # Don't blank previously-captured web/interaction columns on a
            # base-only run (no web session).
            preserve_web_columns(existing, rows, key_col)
        log_field_changes(existing, rows, key_col)
        utils.upsert_rows(service, spreadsheet_id, TAB_NAME,
                          columns, rows, match_keys=[key_col])

        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        log.info("Spreadsheet: %s", url)

        # --- loud, dated alert when enrichment was expected but skipped -------
        # (expired/rejected web session). Prevents the silent multi-day
        # degradation where Conversation Label / Assigned Agent / Chat Status
        # and the enr_* columns quietly stop refreshing for new records.
        enrich_note = ""
        if enrich_expected and not enrichment_ran:
            last_ok = _last_enrichment_ok()
            if last_ok:
                when = last_ok.strftime("%d-%b-%Y %H:%M UTC")
                ago = f"{(datetime.now(timezone.utc) - last_ok).days} day(s) ago"
            else:
                when, ago = "unknown", "date unknown"
            bar = "!" * 68
            log.warning(bar)
            log.warning("ENRICHMENT SKIPPED — the Interakt web session is not working.")
            log.warning("Conversation Label / Assigned Agent / Chat Status and every")
            log.warning("enr_* column were NOT refreshed this run (new records stay blank).")
            log.warning("Last successful enrichment: %s (%s).", when, ago)
            log.warning("ONE-TIME FIX so this stops recurring:")
            log.warning("   .venv\\Scripts\\python.exe interakt_session.py --setup")
            log.warning(bar)
            enrich_note = f"  |  ⚠ ENRICHMENT SKIPPED (last OK: {when}) — see warning above"

        log.info("Summary: %s users fetched -> upserted into '%s'.%s",
                 len(rows), TAB_NAME, enrich_note)
        log.info("Done in %.1fs.", time.time() - started)
        return 0

    except ic.InteraktError as exc:
        log.error("CONFIG/API ERROR: %s", exc)
        return 2
    except Exception as exc:                      # noqa: BLE001
        log.exception("UNEXPECTED FAILURE: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
