#!/usr/bin/env python3
"""
exotel_common.py — shared helpers for the Exotel pipeline.

Contains:
  * parse_inbox_html()  — extract per-call enrichment (Outcome, FromName,
    ToName, Notes, Assign To, CallType) from a saved Exotel Inbox
    (/callindex) HTML page. These fields are NOT in any API for this account;
    they only exist in the dashboard's rendered HTML.
  * read_existing_rows() — read the Google Sheet tab into {Sid: {col: val}}.
  * ENRICH_COLUMNS — the columns owned by the Inbox enrichment (so the API
    sync can preserve them and never blank them).
"""
import re
import os
import glob
import json
import html as _html

# Columns that come ONLY from the Inbox (not the API). The API sync preserves
# these; the enrichment fills them.
#   Transcription -> the "Here is what happened" call-flow narrative (in the
#                    call-list HTML as data-notes).
#   Notes         -> the user-entered notes (Lead info etc.); NOT in the list
#                    HTML — captured per-call by the scraper into a notes JSON.
ENRICH_COLUMNS = ["FromName", "ToName", "Outcome", "Assign To", "Lead Status",
                  "Transcription", "Notes", "CallType"]
# Columns obtainable from the light-weight live list fetch (no per-call open).
# Notes is excluded — only the scraper (which opens each call) can get it.
LIVE_COLUMNS = [c for c in ENRICH_COLUMNS if c != "Notes"]


def _attr(block, name):
    """Return the value of data-<name>="..." from an <li> block (or '')."""
    m = re.search(r'data-' + re.escape(name) + r'="([^"]*)"', block)
    return _html.unescape(m.group(1)).strip() if m else ""


def parse_inbox_html(html_text):
    """
    Parse an Exotel Inbox (/callindex) HTML page.

    Returns: dict keyed by call Sid ->
        {FromName, ToName, Outcome, Notes, "Assign To", CallType,
         From, To, Direction, TicketStatus}
    Only the enrichment fields are meant to be merged into the sheet, but the
    numbers/direction are returned too for validation.
    """
    result = {}
    # Each call is an <li ... class="ex-inbox-cl-... "> ... </li>. Split on the
    # start of each such <li> so every chunk holds exactly one call.
    chunks = re.split(r'(?=<li\s+\n?\s*class="ex-inbox-cl)', html_text)
    for block in chunks:
        if "data-callsid" not in block:
            continue
        sid = _attr(block, "callsid") or _attr(block, "id")
        if not sid:
            continue

        from_num = _attr(block, "from-org")
        to_num = _attr(block, "to-org")
        from_disp = _attr(block, "from")
        to_disp = _attr(block, "to")

        # Name only when it differs from the raw number (else leave blank —
        # never use the phone number as the name, per requirement).
        from_name = from_disp if from_disp and from_disp != from_num else ""
        to_name = to_disp if to_disp and to_disp != to_num else ""

        # Outcome: the human text in <span class="outcome-text" ...>TEXT</span>.
        m = re.search(r'class="outcome-text"[^>]*>\s*(.*?)\s*</span>', block, re.S)
        outcome = _html.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""

        result[sid] = {
            "FromName": from_name,
            "ToName": to_name,
            "Outcome": outcome,
            # data-notes is the "Here is what happened" narrative -> Transcription.
            "Transcription": _attr(block, "notes"),
            # Real user notes are per-call; the scraper fills this via notes JSON.
            "Notes": "",
            # data-assigned is the agent's numeric id; remapped to a name later
            # (via the agent map) in load_enrichment / fetch_live_enrichment.
            "Assign To": _attr(block, "assigned"),
            # Ticket/lead status: open / pending / closed.
            "Lead Status": _attr(block, "tkt-stat"),
            "CallType": _attr(block, "calltype"),
            # extras (not written unless you add them to COLUMNS):
            "From": from_num,
            "To": to_num,
            "Direction": _attr(block, "direction"),
            "MsgId": _attr(block, "msgid"),  # used to fetch this call's notes
        }
    return result


# ---------------------------------------------------------------------------
#  USER NOTES via the Inbox annotation endpoint (fast, no browser).
#  POST /messages/inbox_idx/fetchAnnotations/  msgId=..&searchQuery=..&CSRFToken=..
# ---------------------------------------------------------------------------
ANNOTATION_URL = "https://my.exotel.com/messages/inbox_idx/fetchAnnotations/"


def csrf_from_cookie(cookie):
    """Pull the CSRFToken out of the exoteloblx_session cookie value."""
    m = re.search(r'CSRFToken%22%3Bs%3A32%3A%22([0-9a-fA-F]{32})%22', cookie)
    return m.group(1) if m else ""


def _extract_note(resp_text):
    """Extract the user note(s) from a fetchAnnotations response.
    The endpoint returns JSON: {"annotes":[{"description": "...", ...}, ...]}.
    Joins all real note descriptions; drops the 'Notes Loaded:' marker.
    Falls back to HTML parsing if the response isn't JSON."""
    notes = []
    try:
        data = json.loads(resp_text)
        annotes = data.get("annotes") or []
        for a in annotes:
            desc = str(a.get("description", "")).strip()
            if desc and desc.lower().rstrip(":").strip() != "notes loaded":
                notes.append(desc)
        return "\n\n".join(notes)
    except Exception:
        pass
    # Fallback: legacy HTML shape.
    bodies = re.findall(
        r'class="ex-row"\s+style="padding:\.3em \.5em;">(.*?)</div>',
        resp_text, re.S)
    for b in bodies:
        txt = _html.unescape(re.sub(r"<[^>]+>", " ", b))
        txt = re.sub(r"[ \t]+", " ", txt).strip()
        if txt and txt.lower().rstrip(":").strip() != "notes loaded":
            notes.append(txt)
    return "\n\n".join(notes)


def fetch_annotation(msgid, cookie, csrf, user_agent, search_query="",
                     timeout=20):
    import requests
    if not msgid:
        return ""
    try:
        r = requests.post(
            ANNOTATION_URL,
            data={"msgId": msgid, "searchQuery": search_query,
                  "CSRFToken": csrf},
            headers={"Cookie": cookie, "User-Agent": user_agent,
                     "X-Requested-With": "XMLHttpRequest"},
            timeout=timeout)
        if r.status_code == 200:
            return _extract_note(r.text)
    except Exception:
        return ""
    return ""


def fetch_all_notes(sid_to_msgid, cookie, user_agent, search_query="",
                    max_calls=0, workers=12, logger=None):
    """Fetch notes for many calls concurrently. Returns {Sid: note_text}
    (only non-empty). Order of sid_to_msgid is preserved for max_calls."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    csrf = csrf_from_cookie(cookie)
    if not csrf:
        if logger:
            logger.warning("No CSRF token in cookie — cannot fetch notes.")
        return {}
    items = [(s, m) for s, m in sid_to_msgid.items() if m]
    if max_calls:
        items = items[:max_calls]
    notes = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_annotation, m, cookie, csrf, user_agent,
                          search_query): s for s, m in items}
        for fut in as_completed(futs):
            sid = futs[fut]
            note = fut.result()
            done += 1
            if note:
                notes[sid] = note
    if logger:
        logger.info("Fetched notes: %d calls checked, %d with notes.",
                    done, len(notes))
    return notes


def parse_agents(html_text):
    """Build {agent_id: name} from the '#ex-inbox-msg-assign' select options in
    the Inbox page (used to turn Assign-To ids into names)."""
    agents = {}
    m = re.search(r'id="ex-inbox-msg-assign"[^>]*>(.*?)</select>',
                  html_text, re.S)
    block = m.group(1) if m else html_text
    for opt in re.finditer(r'<option\s+value="(\d+)"[^>]*>(.*?)</option>',
                           block, re.S):
        aid = opt.group(1).strip()
        name = _html.unescape(re.sub(r"\s+", " ", opt.group(2)).strip())
        if aid and name:
            agents[aid] = name
    return agents


def _remap_assignees(enrich, agents):
    """Replace numeric Assign-To ids with agent names where known."""
    if not agents:
        return
    for e in enrich.values():
        aid = str(e.get("Assign To", "")).strip()
        if aid and aid in agents:
            e["Assign To"] = agents[aid]


def load_enrichment(html_dir):
    """Parse every *.html/*.htm file in html_dir and merge into one Sid map.
    Later files override earlier ones. Returns {} if the dir is missing."""
    enrich = {}
    agents = {}
    if not html_dir or not os.path.isdir(html_dir):
        return enrich
    for path in sorted(glob.glob(os.path.join(html_dir, "*.htm*"))):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            enrich.update(parse_inbox_html(text))
            agents.update(parse_agents(text))  # in case a full page was saved
        except Exception:
            continue
    # JSON side-cars written by the scraper: agents map + per-call notes.
    for path in sorted(glob.glob(os.path.join(html_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        if "agent" in os.path.basename(path).lower():
            agents.update({str(k): v for k, v in obj.items()})
        else:  # notes: {Sid: note_text}
            for sid, note in obj.items():
                if note:
                    enrich.setdefault(sid, {})["Notes"] = note
    _remap_assignees(enrich, agents)
    return enrich


def load_cookie(cookie_file):
    """Read the saved my.exotel.com session cookie header (or '')."""
    if not cookie_file or not os.path.isfile(cookie_file):
        return ""
    with open(cookie_file, encoding="utf-8") as f:
        return f.read().strip()


def fetch_inbox_html(url, cookie, user_agent="Mozilla/5.0", timeout=30):
    """GET the Inbox /callindex page using the login cookie.
    Returns (html_text, error). error is a string if the fetch failed or the
    session is not logged in (so the caller can fall back gracefully)."""
    import requests
    if not cookie:
        return None, "no cookie configured"
    try:
        r = requests.get(
            url,
            headers={
                "Cookie": cookie,
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception as e:  # network / TLS / timeout
        return None, f"request error: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    text = r.text or ""
    # A valid Inbox page contains call rows; a login/redirect page does not.
    if "data-callsid" not in text and "ex-inbox-cl-list" not in text:
        return None, ("session expired or not logged in "
                      "(no call rows in response) — re-capture the cookie")
    return text, None


def fetch_live_enrichment(url, cookie_file, user_agent="Mozilla/5.0",
                          timeout=30, logger=None):
    """Fetch the live Inbox page and parse it into a Sid->enrichment map.
    Returns {} (and logs a warning) if no cookie or the session expired."""
    cookie = load_cookie(cookie_file)
    if not cookie:
        return {}
    html_text, err = fetch_inbox_html(url, cookie, user_agent, timeout)
    if err:
        if logger:
            logger.warning("Live Inbox fetch skipped: %s", err)
        return {}
    enrich = parse_inbox_html(html_text)
    _remap_assignees(enrich, parse_agents(html_text))
    return enrich


# ---------------------------------------------------------------------------
#  OFFICIAL CCM API enrichment  (contact name + agent name — NO web cookie)
#
#  The Exotel Cloud-Contact-Center "Get Call Details" API returns the two
#  fields the Inbox scrape used to give us, but authenticates with the SAME
#  stable api_key / api_token the call pull already uses — so it never expires:
#
#    GET https://<key>:<token>@ccm-api[.in].exotel.com/v2/accounts/<sid>/calls/<call_sid>
#    -> { "response": { "data": {
#           "customer_details":       {"contact_name": ..., "contact_uri": ...},
#           "assigned_agent_details": {"user_name": ..., "contact_uri": ...},
#           "direction": ..., "call_status": ... } } }
#
#  contact_name  -> the customer party's saved name  (FromName / ToName)
#  user_name     -> the agent who handled the call    (the other side + Assign To)
#
#  This is direction-proof: we match contact_uri to the row's From/To (by the
#  last 10 digits) to decide which side is the customer and which is the agent,
#  rather than assuming inbound vs outbound.
# ---------------------------------------------------------------------------
CCM_COLUMNS = ["FromName", "ToName", "Assign To"]


def ccm_base_url(subdomain, account_sid):
    """Derive the CCM API base from the voice api subdomain/region.
    api.exotel.com / api.in.exotel.com -> ccm-api.exotel.com / ccm-api.in.exotel.com
    (a Mumbai '.in.' account keeps the '.in.'; everything else uses the global host).
    """
    sub = (subdomain or "").lower()
    host = "ccm-api.in.exotel.com" if ".in." in sub or sub.endswith(".in.exotel.com") \
        else "ccm-api.exotel.com"
    return f"https://{host}/v2/accounts/{account_sid}/calls"


def _digits10(value):
    """Last 10 digits of a phone-ish string (for matching numbers across formats)."""
    d = re.sub(r"\D", "", str(value or ""))
    return d[-10:] if len(d) >= 10 else d


def _unwrap_ccm(payload):
    """Return the inner call-detail dict from a CCM response envelope.
    Handles {"response":{"data":{...}}}, {"response":{...}}, {"data":{...}}, {...}."""
    if not isinstance(payload, dict):
        return {}
    node = payload
    for _ in range(4):
        if not isinstance(node, dict):
            return {}
        if "customer_details" in node or "assigned_agent_details" in node:
            return node
        nxt = node.get("response", node.get("data"))
        if nxt is None or nxt is node:
            break
        node = nxt
    return node if isinstance(node, dict) else {}


def ccm_names_from_detail(detail, row_from="", row_to=""):
    """Map one CCM call-detail dict -> {FromName, ToName, "Assign To"} using the
    row's own From/To numbers to place the customer name on the correct side.
    Only non-empty values are returned (so blanks never clobber existing data)."""
    d = _unwrap_ccm(detail)
    cust = d.get("customer_details") or {}
    agent = d.get("assigned_agent_details") or {}
    if not isinstance(cust, dict):
        cust = {}
    if not isinstance(agent, dict):
        agent = {}

    def _clean(v):
        s = str(v or "").strip()
        return "" if s.lower() in ("", "null", "none", "n/a", "na") else s

    contact_name = _clean(cust.get("contact_name"))
    agent_name = _clean(agent.get("user_name") or agent.get("name"))
    cust_uri = _digits10(cust.get("contact_uri"))
    f10, t10 = _digits10(row_from), _digits10(row_to)

    out = {}
    # Decide which side the customer sits on. Prefer an explicit number match;
    # otherwise fall back to direction (customer = From on inbound, To on outbound).
    cust_side = None
    if cust_uri and cust_uri == f10:
        cust_side = "from"
    elif cust_uri and cust_uri == t10:
        cust_side = "to"
    else:
        direction = str(d.get("direction", "")).lower()
        cust_side = "to" if "out" in direction else "from"

    if contact_name:
        if cust_side == "to":
            out["ToName"] = contact_name
            if agent_name:
                out["FromName"] = agent_name
        else:
            out["FromName"] = contact_name
            if agent_name:
                out["ToName"] = agent_name
    elif agent_name:
        # No customer name, but we know the agent -> put it on the non-customer side.
        if cust_side == "to":
            out["FromName"] = agent_name
        else:
            out["ToName"] = agent_name

    if agent_name:
        out["Assign To"] = agent_name
    return out


def fetch_ccm_enrichment(api_key, api_token, subdomain, account_sid, rows,
                         max_workers=8, max_calls=0, timeout=20, logger=None):
    """Fetch {Sid: {FromName, ToName, 'Assign To'}} from the official CCM API for
    the given rows (each a dict with Sid/From/To). Credential-stable (no cookie).

    Degrades gracefully: on 401/403/404 for the FIRST call it assumes CCM is not
    enabled for this account, logs once, and returns whatever it already has
    (usually {}) so the caller falls back to the cookie/existing behaviour with
    no regression.
    """
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    base = ccm_base_url(subdomain, account_sid)
    session = requests.Session()
    session.auth = (api_key, api_token)
    session.headers.update({"Accept": "application/json"})

    targets = [r for r in rows if r.get("Sid")]
    if max_calls:
        targets = targets[:max_calls]
    if not targets:
        return {}

    disabled = {"flag": False, "reason": ""}

    def _one(r):
        sid = r["Sid"]
        try:
            resp = session.get(f"{base}/{sid}", timeout=timeout)
        except Exception as exc:  # network/TLS/timeout -> skip this call only
            return sid, None, f"network: {exc}"
        if resp.status_code in (401, 403):
            return sid, None, f"auth HTTP {resp.status_code} (CCM not enabled?)"
        if resp.status_code == 404:
            return sid, {}, None      # call simply not in CCM; not fatal
        if resp.status_code != 200:
            return sid, None, f"HTTP {resp.status_code}"
        try:
            data = resp.json()
        except ValueError:
            return sid, None, "non-JSON body"
        return sid, ccm_names_from_detail(data, r.get("From", ""), r.get("To", "")), None

    out = {}
    ok = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        futs = {ex.submit(_one, r): r for r in targets}
        for fut in as_completed(futs):
            sid, mapped, err = fut.result()
            if err and ("auth HTTP" in err):
                # Treat a hard auth failure as 'CCM unavailable' and stop early.
                if not disabled["flag"]:
                    disabled["flag"] = True
                    disabled["reason"] = err
                continue
            if mapped:
                out[sid] = mapped
                ok += 1
    if disabled["flag"]:
        if logger:
            logger.warning("CCM API unavailable (%s) — skipping API name "
                           "enrichment; falling back to cookie/existing.",
                           disabled["reason"])
        return {}
    if logger:
        logger.info("CCM API name enrichment: %d of %d calls returned a "
                    "contact/agent name.", ok, len(targets))
    return out


# ---------------------------------------------------------------------------
#  CONTACTS / ADDRESS BOOK  (stable key/token name map — no cookie)
#
#  Exotel resolves a call's From/To to a display name via the account Address
#  Book. The Contacts API exposes it with the same api_key/api_token:
#     GET https://<key>:<token>@<subdomain>/v2/accounts/<sid>/contacts?limit=20&offset=N
#  Each contact carries number + first_name/last_name (+ company_name). We build
#  {last-10-digits -> name} once per run and use it to fill FromName/ToName
#  whenever a number is a saved contact. This works with zero session, so names
#  still load even if the Inbox cookie login can't run (OTP/CAPTCHA).
# ---------------------------------------------------------------------------
def _contact_name(c):
    if not isinstance(c, dict):
        return ""
    inner = c.get("data") if isinstance(c.get("data"), dict) else c
    name = " ".join(x for x in (inner.get("first_name"), inner.get("last_name"))
                    if x).strip()
    return name or str(inner.get("company_name") or "").strip()


def _contact_number(c):
    inner = c.get("data") if isinstance(c, dict) and isinstance(c.get("data"), dict) else c
    if not isinstance(inner, dict):
        return ""
    return _digits10(inner.get("number") or inner.get("phone")
                     or inner.get("contact_uri") or "")


def _extract_contact_list(payload):
    """Find the list of contacts inside whatever envelope the API returns."""
    for node in (payload.get("response") if isinstance(payload, dict) else None,
                 payload):
        if isinstance(node, dict):
            for k in ("data", "contacts", "results"):
                v = node.get(k)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict) and isinstance(v.get("data"), list):
                    return v["data"]
    return []


def fetch_contacts_map(api_key, api_token, subdomain, account_sid,
                       max_pages=1000, timeout=20, logger=None):
    """Return {last10digits: name} from the Exotel Address Book (or {} if the
    account has no Contacts / the API is unavailable)."""
    import requests
    session = requests.Session()
    session.auth = (api_key, api_token)
    session.headers.update({"Accept": "application/json"})
    base = f"https://{subdomain}/v2/accounts/{account_sid}/contacts"

    out = {}
    offset, limit, pages = 0, 20, 0
    while pages < max_pages:
        try:
            r = session.get(f"{base}?limit={limit}&offset={offset}", timeout=timeout)
        except Exception as exc:
            if logger and pages == 0:
                logger.warning("Contacts API error: %s", exc)
            break
        if r.status_code != 200:
            if logger and pages == 0:
                logger.info("Contacts API HTTP %s — skipping address-book names.",
                            r.status_code)
            break
        try:
            items = _extract_contact_list(r.json())
        except ValueError:
            break
        if not items:
            break
        for it in items:
            num, name = _contact_number(it), _contact_name(it)
            if num and name:
                out.setdefault(num, name)
        pages += 1
        offset += limit
        if len(items) < limit:
            break
    if logger and out:
        logger.info("Contacts/address-book: %d named numbers loaded.", len(out))
    return out


def read_existing_rows(service, spreadsheet_id, tab_name, key="Sid"):
    """Read a worksheet into {key_value: {column: value}} using the header row."""
    from googleapiclient.errors import HttpError  # local import
    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{tab_name}!A1:ZZ"
        ).execute()
    except HttpError:
        return {}
    values = resp.get("values", [])
    if not values:
        return {}
    header = values[0]
    try:
        key_idx = header.index(key)
    except ValueError:
        return {}
    out = {}
    for row in values[1:]:
        if key_idx < len(row) and row[key_idx]:
            out[row[key_idx]] = {
                header[i]: (row[i] if i < len(row) else "")
                for i in range(len(header))
            }
    return out
