#!/usr/bin/env python3
"""
pyExotelInboxScrape.py — Full-history Inbox scraper (headless browser).

The Exotel Inbox (/callindex) paginates and date-filters entirely via in-page
JavaScript (no URL/POST params work — proven by diag_pagination.py). So to
enrich the FULL history we drive a real (headless) browser with your saved
login cookie, set a wide date range, and click through every page, capturing
the rendered rows. The captured HTML is written to
config_files/inbox_html/inbox_scraped.html, which the normal sync then merges.

ONE-TIME SETUP (in the project folder):
    .venv\\Scripts\\python.exe -m pip install playwright
    .venv\\Scripts\\python.exe -m playwright install chromium

RUN (backfill everything, then the sync enriches it):
    .venv\\Scripts\\python.exe pyExotelInboxScrape.py
    .venv\\Scripts\\python.exe pyExotelCallDetails.py full

You can also schedule this scraper (e.g. daily) so enrichment stays complete
without any manual step.
"""
# --- IntelliBI Sales Automation portability bootstrap (auto-inserted) ---
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap  # noqa: E402  (sys.path + env defaults + config.yaml)
from paths import CREDENTIALS_DIR, CONFIG_DIR, LOGS_DIR  # noqa: E402
# --- end bootstrap ---

import os
import re
import sys
import logging
from datetime import datetime, timezone, timedelta

import exotel_common as ec

HERE = os.path.dirname(os.path.abspath(__file__))
SID = "intellibiinnovations1"
INBOX_URL = f"https://my.exotel.com/{SID}/callindex"
COOKIE_FILE = os.path.join(CREDENTIALS_DIR, "exotel_web_cookie.txt")
OUT_FILE = os.path.join(CREDENTIALS_DIR, "inbox_html", "inbox_scraped.html")
NOTES_FILE = os.path.join(CREDENTIALS_DIR, "inbox_html", "inbox_notes.json")
AGENTS_FILE = os.path.join(CREDENTIALS_DIR, "inbox_html", "inbox_agents.json")

# How far back to scrape (days). Keep <= ~180 (Exotel retention).
SCRAPE_DAYS = 190
# Safety cap on pages (25 rows each). 200 pages = 5000 calls.
MAX_PAGES = 200
# Capture per-call user Notes (opens each row — slower). Set FETCH_NOTES=0 to skip.
FETCH_NOTES = os.environ.get("FETCH_NOTES", "1") != "0"
# Cap how many calls (newest first) to open for Notes. 0 = all. For routine
# runs set e.g. NOTES_MAX_CALLS=100 — old notes don't change once captured, and
# prior notes are preserved in the sheet anyway.
NOTES_MAX_CALLS = int(os.environ.get("NOTES_MAX_CALLS", "0") or "0")
# Max wait (ms) for a call's Notes annotation to load after opening it.
NOTE_LOAD_MS = int(os.environ.get("NOTE_LOAD_MS", "1200") or "1200")
# Headless by default; set HEADFUL=1 env to watch it.
HEADLESS = os.environ.get("HEADFUL", "") != "1"

import json as _json

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(
                                  os.path.join(str(LOGS_DIR), "exotel_scrape.log"),
                                  encoding="utf-8")])
log = logging.getLogger("inbox_scrape")


def _now_ist():
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(timezone.utc).astimezone(IST).replace(tzinfo=None)


def parse_cookies(cookie_str):
    """Turn 'a=b; c=d' into Playwright cookie dicts for my.exotel.com."""
    cookies = []
    for part in cookie_str.strip().split("; "):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({"name": name.strip(), "value": value,
                        "domain": "my.exotel.com", "path": "/"})
    return cookies


def first_sid(page):
    try:
        return page.eval_on_selector(
            ".ex-inbox-cl-list li", "el => el.getAttribute('data-callsid')")
    except Exception:
        return None


def capture_page_notes(page, notes_map, log):
    """Open each call on the current page and capture its user Notes.
    Optimized: reads the annotation via text_content (works while the Notes tab
    is hidden, so no tab-click/extra wait per row). Robust: one bad row is
    skipped, not fatal. Honours NOTES_MAX_CALLS (newest-first cap)."""
    if NOTES_MAX_CALLS and len(notes_map) >= NOTES_MAX_CALLS:
        return
    handles = page.query_selector_all(".ex-inbox-cl-list li")
    for rh in handles:
        if NOTES_MAX_CALLS and len(notes_map) >= NOTES_MAX_CALLS:
            break
        try:
            sid = rh.get_attribute("data-callsid")
        except Exception:
            sid = None
        if not sid or sid in notes_map:
            continue
        note = ""
        try:
            rh.click(timeout=3000)
            # Wait until the detail panel shows THIS call's reference id.
            page.wait_for_function(
                """s => { const el =
                     document.querySelector('.ex-inbox-msg-con-callsid');
                     return el && el.textContent &&
                            el.textContent.indexOf(s) !== -1; }""",
                arg=sid[:12], timeout=6000)
            # Exotel only FETCHES the annotation when you switch ONTO the Notes
            # tab. After the first call the tab is already "Notes", so a second
            # click is a no-op. Clear the panel, then force a real
            # Transcription -> Notes switch so the fetch fires for every call.
            try:
                page.evaluate(
                    "() => { const e = document.querySelector"
                    "('.ex-inbox-msg-con-annotes'); if (e) e.textContent=''; }")
            except Exception:
                pass
            try:
                page.click("#transcription-button", timeout=1200)
                page.wait_for_timeout(120)
                page.click("#notes-button", timeout=1200)
            except Exception:
                pass
            # Wait for the annotation to populate (calls without notes time out
            # quickly and are recorded as blank).
            try:
                page.wait_for_function(
                    """() => { const el =
                         document.querySelector('.ex-inbox-msg-con-annotes');
                         return el && el.textContent.trim().length > 0; }""",
                    timeout=NOTE_LOAD_MS)
            except Exception:
                pass
            note = (page.text_content(".ex-inbox-msg-con-annotes") or "").strip()
        except Exception:
            note = ""
        notes_map[sid] = note  # record (even blank) so we don't re-open it


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        log.error("Playwright not installed. Run:\n"
                  "  .venv\\Scripts\\python.exe -m pip install playwright\n"
                  "  .venv\\Scripts\\python.exe -m playwright install chromium")
        return 1

    # Zero-touch: refresh the Inbox cookie from the saved browser login profile
    # (config_files/exotel_browser_profile) so this needs no manual cookie paste —
    # the same one-time `exotel_session.py --setup` used by pyExotelCallDetails.py.
    try:
        import exotel_session as _es
        if _es.login_available():
            _es.refresh_session(stale_hours=6, logger=log)
    except Exception as _e:                              # noqa: BLE001
        log.info("Auto-login refresh skipped (%s) — using existing cookie file.", _e)

    if not os.path.isfile(COOKIE_FILE):
        log.error("Cookie file missing: %s — run exotel_session.py --setup once, "
                  "or paste a cookie into %s", COOKIE_FILE, COOKIE_FILE)
        return 1
    cookie_str = open(COOKIE_FILE, encoding="utf-8").read().strip()
    cookies = parse_cookies(cookie_str)

    now = _now_ist()
    from_str = (now - timedelta(days=SCRAPE_DAYS)).strftime("%d/%m/%Y")
    to_str = now.strftime("%d/%m/%Y")
    log.info("Scraping Inbox %s .. %s (headless=%s)", from_str, to_str, HEADLESS)

    collected_html = []
    seen_sids = set()
    notes_map = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/150.0.0.0 Safari/537.36"))
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(INBOX_URL, wait_until="domcontentloaded", timeout=60000)

        # Confirm we're logged in.
        try:
            page.wait_for_selector(".ex-inbox-cl-list li", timeout=20000)
        except Exception:
            log.error("No call rows loaded — cookie likely expired. "
                      "Re-capture the cookie and retry.")
            browser.close()
            return 2

        # --- Capture the agent id->name map (for Assign To) ---------------
        try:
            pairs = page.eval_on_selector_all(
                "#ex-inbox-msg-assign option",
                "opts => opts.filter(o => o.value)"
                ".map(o => [o.value, o.textContent.trim()])")
            agents_map = {v: n for v, n in pairs if v and n}
            os.makedirs(os.path.dirname(AGENTS_FILE), exist_ok=True)
            with open(AGENTS_FILE, "w", encoding="utf-8") as f:
                _json.dump(agents_map, f, ensure_ascii=False, indent=1)
            log.info("Captured %d agents (Assign-To names): %s",
                     len(agents_map), ", ".join(agents_map.values()) or "none")
        except Exception as e:
            log.warning("Could not capture agent map: %s", e)

        # --- Set a wide custom date range via the filter UI ---------------
        # Set values via JS (works even while the filter panel is hidden), then
        # force-click Apply.
        try:
            try:
                page.click("#ex-inbox-adv-srch-togl", timeout=3000)
                page.wait_for_timeout(400)
            except Exception:
                pass
            page.evaluate(
                """([f,t]) => {
                    const set=(sel,val)=>{const e=document.querySelector(sel);
                      if(e){e.value=val;
                        e.dispatchEvent(new Event('change',{bubbles:true}));}};
                    set('select[name=clPeriod]','custom');
                    set('input[name=clFromDate]', f);
                    set('input[name=clToDate]', t);
                }""", [from_str, to_str])
            page.wait_for_timeout(300)
            try:
                page.click(".ex-inbox-menu-srch-act .inbox-query-btn",
                           timeout=4000, force=True)
            except Exception:
                page.click(".inbox-query-btn", timeout=4000, force=True)
            page.wait_for_selector(".ex-inbox-cl-list li", timeout=20000)
            page.wait_for_timeout(1800)
            try:
                tot = page.get_attribute(".inbox-totalelement", "rel")
            except Exception:
                tot = "?"
            log.info("Applied custom date range (total now: %s).", tot)
        except Exception as e:
            log.warning("Could not set custom date range (%s). Falling back to "
                        "the default Inbox view.", e)

        # --- Page through, capturing each page's rows ---------------------
        try:
            total = int(page.get_attribute(".inbox-totalelement", "rel") or 0)
        except Exception:
            total = 0
        log.info("Reported total records: %s", total or "unknown")

        for i in range(MAX_PAGES):
            try:
                page.wait_for_selector(".ex-inbox-cl-list li", timeout=15000)
            except Exception:
                break
            ul_html = page.inner_html(".ex-inbox-cl-list")
            page_sids = re.findall(r'data-callsid="([^"]+)"', ul_html)
            new = [s for s in page_sids if s not in seen_sids]
            collected_html.append(ul_html)
            seen_sids.update(page_sids)
            log.info("Page %d: %d rows (%d new) | total unique so far: %d",
                     i + 1, len(page_sids), len(new), len(seen_sids))

            # Decide whether to advance.
            try:
                next_off = int(page.get_attribute(".inbox-offset-right", "rel")
                               or 0)
            except Exception:
                next_off = 0
            if total and next_off and next_off >= total:
                log.info("Reached last page (offset %d >= total %d).",
                         next_off, total)
                break
            if not new and i > 0:
                log.info("No new records on this page — stopping.")
                break

            before = first_sid(page)
            try:
                page.click(".inbox-offset-right", timeout=5000)
            except Exception:
                log.info("No 'Older' control — stopping.")
                break
            # Wait until the first row changes (AJAX finished).
            try:
                page.wait_for_function(
                    """prev => {
                        const el = document.querySelector('.ex-inbox-cl-list li');
                        return el && el.getAttribute('data-callsid') !== prev;
                    }""", arg=before, timeout=15000)
            except Exception:
                log.info("Page did not advance — stopping.")
                break

        browser.close()

    if not collected_html:
        log.error("No rows captured.")
        return 3

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    full = ("<html><body><ul class=\"ex-inbox-cl-list\">"
            + "".join(collected_html) + "</ul></body></html>")
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(full)
    log.info("Wrote %d unique call rows to %s", len(seen_sids), OUT_FILE)

    # --- Fetch user Notes via the annotation endpoint (fast, concurrent) ---
    if FETCH_NOTES:
        parsed = ec.parse_inbox_html(full)  # gives Sid -> {..., MsgId}
        sid_msgid = {s: v.get("MsgId", "") for s, v in parsed.items()
                     if v.get("MsgId")}
        search_query = (f",created:{from_str.replace('/', '-')} 00:00:00..."
                        f"{to_str.replace('/', '-')} 23:59:59")
        log.info("Fetching notes for %d calls via annotation endpoint%s ...",
                 len(sid_msgid),
                 f" (cap {NOTES_MAX_CALLS})" if NOTES_MAX_CALLS else "")
        notes_out = ec.fetch_all_notes(
            sid_msgid, cookie_str, ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/150.0.0.0 Safari/537.36"),
            search_query=search_query, max_calls=NOTES_MAX_CALLS, logger=log)
    else:
        notes_out = {}
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        _json.dump(notes_out, f, ensure_ascii=False, indent=1)
    log.info("Wrote %d user-notes to %s", len(notes_out), NOTES_FILE)
    log.info("Now run:  .venv\\Scripts\\python.exe pyExotelCallDetails.py full")
    return 0


if __name__ == "__main__":
    sys.exit(main())
