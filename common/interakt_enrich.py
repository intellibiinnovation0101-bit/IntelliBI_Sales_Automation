"""
interakt_enrich.py
==================
Lead enrichment from Interakt's internal (web-session) APIs — the data the
public Get Users API does NOT expose. Mirrors the Exotel "API + web enrichment"
pattern: the public API gives the base contact record, this adds the rest.

Auth: the internal APIs authenticate with the browser session (a cookie plus
x-subscription-id / x-subscription-name / x-interakt-org-id headers). Those are
read from config_files/interakt_curl.txt — a paste of "Copy as cURL (bash)" of
ANY api.interakt.ai request from DevTools. The session is short-lived, so this
file is re-captured periodically, exactly like the Exotel web cookie.

What it enriches per customer id (the public API 'id' IS the internal
customer_id):
  * Agent notes         -> /customers/{id}/notes/
  * Activity + campaigns -> /customers/{id}/timelines/
  * Lead stage name      -> resolved from trait _internal_stage_id via
                            /contact-settings/stages
  * Contact owner/agent  -> resolved from trait _internal_contact_owner_id (and
                            note authors) via /members/

Chat open/closed status and full message threads live behind the Inbox
conversation-list endpoint (POST /v2/.../chats/) and are added separately once
that request is captured; this module degrades gracefully without them.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import time
from typing import Any, Dict, List, Optional

import requests

import interakt_common as ic

log = logging.getLogger("interakt")

# --- IntelliBI Sales Automation portability bootstrap (auto-inserted) ---
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap  # noqa: E402  (sys.path + env defaults + config.yaml)
from paths import CREDENTIALS_DIR, CONFIG_DIR, LOGS_DIR  # noqa: E402
# --- end bootstrap ---

HERE = os.path.dirname(os.path.abspath(__file__))
CURL_FILE = os.path.join(CREDENTIALS_DIR, "interakt_curl.txt")

_SKIP = {"accept-encoding", "content-length", "host", "connection"}
_CAMPAIGN_HINTS = ("campaign", "broadcast", "notification", "template")


class WebAuthError(RuntimeError):
    """Raised when the internal web session is missing or rejected (401/403)."""


# ---------------------------------------------------------------------------
# cURL parsing (headers incl. cookie) — same approach as the probe
# ---------------------------------------------------------------------------
def headers_from_curl(path: str) -> Dict[str, str]:
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        raise WebAuthError(
            f"{path} not found. Paste 'Copy as cURL (bash)' of any "
            "api.interakt.ai request there to enable enrichment.")
    raw = open(path, encoding="utf-8").read()
    raw = raw.replace("\\\r\n", " ").replace("\\\n", " ")
    try:
        toks = shlex.split(raw)
    except ValueError:
        toks = re.findall(r"-H|--header|-b|--cookie|'[^']*'|\"[^\"]*\"|\S+", raw)
        toks = [t[1:-1] if (t[:1] in "'\"" and t[-1:] in "'\"") else t for t in toks]
    headers, cookie = {}, None
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-H", "--header") and i + 1 < len(toks):
            hv = toks[i + 1]
            if ":" in hv:
                n, v = hv.split(":", 1)
                if n.strip().lower() not in _SKIP and not n.startswith(":"):
                    headers[n.strip()] = v.strip()
            i += 2
        elif t in ("-b", "--cookie") and i + 1 < len(toks):
            cookie = toks[i + 1]; i += 2
        else:
            i += 1
    if cookie:
        headers["Cookie"] = cookie
    return headers


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------
class InteraktEnricher:
    """Fetches per-customer enrichment using the browser session."""

    def __init__(self, curl_file: str = CURL_FILE):
        headers = headers_from_curl(curl_file)
        self.org = headers.get("x-interakt-org-id")
        if not self.org:
            raise WebAuthError("x-interakt-org-id missing from interakt_curl.txt.")
        self.s = requests.Session(); self.s.headers.update(headers)
        self.B1 = f"https://api.interakt.ai/v1/organizations/{self.org}"
        self.B2 = f"https://api.interakt.ai/v2/organizations/{self.org}"
        self._user_names: Dict[str, str] = {}
        self._stage_names: Dict[str, str] = {}
        self._label_names: Dict[str, str] = {}
        self._conv: Dict[str, Dict[str, Any]] = {}      # customer id -> conv summary

    # -- low level ----------------------------------------------------------
    def _get(self, url: str) -> Any:
        r = self.s.get(url, timeout=40)
        if r.status_code in (401, 403):
            raise WebAuthError(
                f"web session rejected (HTTP {r.status_code}); re-capture "
                "config_files/interakt_curl.txt from a fresh 'Copy as cURL'.")
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _inner_list(payload: Any) -> List[Dict[str, Any]]:
        """Extract the data list from either {data:[...]} or {results:{data:[...]}}."""
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            res = payload.get("results")
            if isinstance(res, dict) and isinstance(res.get("data"), list):
                return res["data"]
        return []

    # -- lookups (agents, stages) ------------------------------------------
    def load_lookups(self) -> None:
        """Build id->name maps for agents/users and pipeline stages."""
        try:
            members = self._get(f"{self.B1}/members/").get("data") or []
            def walk(o: Any) -> None:
                if isinstance(o, dict):
                    if o.get("id") and (o.get("first_name") or o.get("last_name")):
                        self._user_names[o["id"]] = (
                            f"{o.get('first_name','')} {o.get('last_name','')}".strip())
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for it in o:
                        walk(it)
            walk(members)
            log.info("Enrichment lookups: %s users/agents.", len(self._user_names))
        except WebAuthError:
            raise
        except Exception as exc:
            log.warning("Could not load members: %s", exc)
        try:
            stages = self._get(f"{self.B1}/contact-settings/stages").get("data") or []
            for st in stages:
                if st.get("id"):
                    self._stage_names[st["id"]] = st.get("name", "")
            log.info("Enrichment lookups: %s pipeline stages.", len(self._stage_names))
        except WebAuthError:
            raise
        except Exception as exc:
            log.warning("Could not load pipeline stages: %s", exc)
        try:
            labels = self._get(f"{self.B1}/conversation-labels/").get("data") or []
            for lb in labels:
                if lb.get("id"):
                    self._label_names[lb["id"]] = lb.get("name", "")
            log.info("Enrichment lookups: %s conversation labels.", len(self._label_names))
        except WebAuthError:
            raise
        except Exception as exc:
            log.warning("Could not load conversation labels: %s", exc)

    def user_name(self, uid: Optional[str]) -> str:
        return self._user_names.get(uid or "", uid or "")

    def stage_name(self, sid: Optional[str]) -> str:
        return self._stage_names.get(sid or "", sid or "")

    def label_name(self, lid: Optional[str]) -> str:
        return self._label_names.get(lid or "", "")

    # -- conversation summary (label / assignee / status) per customer -----
    # Inbox chat views to page through. The previous code fetched only "active"
    # chats, so every contact whose conversation had been CLOSED/resolved was
    # dropped from the map and showed a blank Conversation Label / Assigned Agent
    # / Chat Status — which mostly hit newer contacts (their chats close over
    # time). We now page BOTH views. A view the API does not recognise simply
    # returns no rows (handled below) and never affects the others, so this can
    # never regress the working "active" path.
    _CHAT_VIEWS = (["active"], ["closed"])

    def load_conversations(self) -> None:
        """Page the Inbox chats-list (active AND closed) and build customer id ->
        {Conversation Label, Assigned Agent, Chat Status, Chat Last Customer
        Message At, Chat Last Activity At}. The label is the pink 'tag' shown
        under each chat in the Interakt Inbox. When a contact has more than one
        chat, the most recent one (by last_activity_at_utc) wins."""
        base_filters = {"channel_types": ["Whatsapp"],
                        "assigned_to_user_ids": [], "conversation_label_id": [],
                        "chat_reply_status": [], "customer_service_window": None,
                        "tags": [], "unread": None, "last_message_between": None}
        # Org-level POST: drop the per-customer id header, force JSON.
        headers = {k: v for k, v in self.s.headers.items()
                   if k.lower() != "x-interakt-customer-id"}
        headers["Content-Type"] = "application/json"
        best_at: Dict[str, str] = {}          # cid -> last_activity kept (recency)
        for chat_type in self._CHAT_VIEWS:
            body = {"filters": {**base_filters, "type": chat_type},
                    "sort_data": {"field": "last_activity_at_utc", "order": "desc"}}
            offset, limit = 0, 50
            while True:
                r = self.s.post(f"{self.B2}/chats/?limit={limit}&offset={offset}",
                                json=body, headers=headers, timeout=40)
                if r.status_code in (401, 403):
                    raise WebAuthError(
                        f"web session rejected (HTTP {r.status_code}) on chats list.")
                if r.status_code != 200:
                    log.warning("chats-list [%s] HTTP %s: %s — that view skipped.",
                                ",".join(chat_type), r.status_code, r.text[:150])
                    break
                data = r.json()
                res = data.get("results") or {}
                items = res.get("data") if isinstance(res, dict) else (
                    res if isinstance(res, list) else [])
                if not items:
                    break
                for it in items:
                    cust = it.get("customer_id")
                    cid = cust.get("id") if isinstance(cust, dict) else cust
                    if not cid:
                        continue
                    la = str(it.get("last_activity_at_utc") or "")
                    # keep only the most recent chat per contact across all views
                    # (UTC ISO timestamps compare correctly as plain strings).
                    if cid in self._conv and la <= best_at.get(cid, ""):
                        continue
                    self._conv[cid] = {
                        "Conversation Label": self.label_name(it.get("conversation_label_id")),
                        "Assigned Agent": self.user_name(it.get("assigned_to_user_id")),
                        "Chat Status": it.get("chat_status")
                            or ("Closed" if it.get("is_closed") else ""),
                        "Chat Last Customer Message At":
                            it.get("last_customer_message_at_utc") or "",
                        # ANY activity on the chat — customer msg, agent reply, or a
                        # label change (this is the list's sort field). Used for the
                        # agent-inclusive "Last Activity" columns.
                        "Chat Last Activity At":
                            it.get("last_activity_at_utc") or "",
                    }
                    best_at[cid] = la
                count = data.get("count") or 0
                offset += limit
                # Stop at the last (short) page, or once we pass a returned count.
                # A MISSING/renamed count no longer ends paging early — the short-
                # page check drives termination, so a response-schema change can't
                # silently cap the map (robust against recurrence).
                if len(items) < limit or (count and offset >= count):
                    break
        log.info("Enrichment: %s conversations mapped (label/assignee/status).",
                 len(self._conv))

    # -- per-customer enrichment -------------------------------------------
    def enrich(self, cid: str) -> Dict[str, Any]:
        """Return enrichment columns (prefixed enr_) for one customer id."""
        out: Dict[str, Any] = {}
        if not cid:
            return out

        # Conversation label / assignee / status (from the pre-loaded chats map)
        out.update(self._conv.get(cid, {}))

        # Custom fields (authoritative) from the customer detail traits ----
        # The portal writes user-created custom fields onto the customer; the
        # internal detail endpoint reflects them even if the public Get Users
        # API lags. Only non-empty values are returned, so blanks never clobber
        # a value the public API already provided.
        try:
            dj = self._get(f"{self.B1}/customers/{cid}/")
            traits = ((dj.get("data") or {}).get("traits")) or {}
            out.update(ic.custom_fields_from_traits(traits))
        except WebAuthError:
            raise
        except Exception as exc:
            log.warning("detail(%s): %s", cid[:8], exc)

        # Agent notes ------------------------------------------------------
        try:
            nj = self._get(f"{self.B1}/customers/{cid}/notes/?page=1&page_size=2000")
            notes = self._inner_list(nj)
            notes.sort(key=lambda n: n.get("created_at_utc", ""), reverse=True)
            out["enr_notes_count"] = len(notes)
            if notes:
                top = notes[0]
                out["enr_note_latest"] = top.get("notes", "")
                out["enr_note_latest_at"] = top.get("created_at_utc", "")
                out["enr_note_latest_by"] = self.user_name(top.get("created_by_user_id"))
                out["enr_notes_all"] = " | ".join(
                    f'{n.get("created_at_utc","")[:16]} '
                    f'{self.user_name(n.get("created_by_user_id"))}: {n.get("notes","")}'
                    for n in notes)
        except WebAuthError:
            raise
        except Exception as exc:
            log.warning("notes(%s): %s", cid[:8], exc)

        # Timeline + campaigns/broadcasts ----------------------------------
        try:
            tj = self._get(f"{self.B1}/customers/{cid}/timelines/?offset=0&limit=100")
            tl = self._inner_list(tj)
            tl.sort(key=lambda t: t.get("created_at_utc", ""), reverse=True)
            out["enr_timeline_count"] = len(tl)
            if tl:
                out["enr_activity_latest"] = tl[0].get("description", "")
                out["enr_activity_latest_at"] = tl[0].get("created_at_utc", "")
                out["enr_activity_types"] = ", ".join(sorted(
                    {t.get("entity_type", "") for t in tl if t.get("entity_type")}))
                camp = [t for t in tl if any(
                    h in (str(t.get("entity_type", "")) + str(t.get("description", ""))).lower()
                    for h in _CAMPAIGN_HINTS)]
                out["enr_campaign_count"] = len(camp)
                if camp:
                    out["enr_campaign_history"] = " | ".join(
                        f'{c.get("created_at_utc","")[:16]} '
                        f'{c.get("entity_type","")}: {c.get("description","")}'
                        for c in camp)
        except WebAuthError:
            raise
        except Exception as exc:
            log.warning("timeline(%s): %s", cid[:8], exc)

        return out

    def resolve_traits(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Turn stage/owner trait ids on a base row into readable names."""
        out: Dict[str, Any] = {}
        sid = row.get("trait__internal_stage_id")
        if sid:
            out["enr_lead_stage"] = self.stage_name(sid)
        oid = row.get("trait__internal_contact_owner_id")
        if oid:
            out["enr_contact_owner"] = self.user_name(oid)
        return out


# Conversation columns (from the Inbox chats list). "Conversation Label" is the
# pink tag shown under each chat.
CONVERSATION_COLUMNS = [
    "Conversation Label", "Assigned Agent", "Chat Status",
    "Chat Last Customer Message At", "Chat Last Activity At",
]

# Column order for the enrichment fields (appended after base columns).
ENRICH_COLUMNS = [
    "enr_lead_stage", "enr_contact_owner",
    "enr_notes_count", "enr_note_latest", "enr_note_latest_at",
    "enr_note_latest_by", "enr_notes_all",
    "enr_timeline_count", "enr_activity_latest", "enr_activity_latest_at",
    "enr_activity_types", "enr_campaign_count", "enr_campaign_history",
]
