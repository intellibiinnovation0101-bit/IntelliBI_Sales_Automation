"""
Verification of the Interakt enrichment data flow for the three columns that
had stopped populating - "Assigned Agent", "Conversation Label" and
"enr_contact_owner" - and of the guard that keeps every web-session column
from being blanked when a source returns nothing.

Covers, offline (no Interakt / Google access needed):
  1. id extraction from every shape the web API has used (string / object / list)
  2. Inbox chats list -> conversation map: label & agent resolved to names; an
     unlabelled / unassigned chat gives an authoritative blank; an id the lookup
     cannot resolve (list failed to load) leaves the key OUT (sheet value kept)
  3. enr_contact_owner / enr_lead_stage resolved from the customer DETAIL
     traits (public Get-Users API carries them for only a few contacts), never
     written as a raw UUID
  4. preserve_web_columns(): enriched run keeps values the source had nothing
     for and still writes authoritative blanks; base-only run unchanged
  5. the sheet read retries transient errors and ABORTS (instead of pretending
     the sheet is empty) on a persistent one
  6. end-to-end row assembly for an enriched run against an existing sheet

Run from the project root (no extra packages needed):
    python sales_validation\\verify_interakt_enrichment.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.join(ROOT, "sales_data_collection"))

import api_retry                                   # noqa: E402
import interakt_enrich as ie                       # noqa: E402

api_retry._sleep = lambda s: None                  # no real waiting

AG1, AG2 = "11111111-aaaa-4bbb-8ccc-000000000001", "11111111-aaaa-4bbb-8ccc-000000000002"
LB1 = "22222222-aaaa-4bbb-8ccc-000000000001"
ST1 = "33333333-aaaa-4bbb-8ccc-000000000001"


def make_enricher(users=True, labels=True, stages=True):
    """An InteraktEnricher without touching the network / cURL file."""
    e = ie.InteraktEnricher.__new__(ie.InteraktEnricher)
    e.org, e.B1, e.B2 = "org", "https://x/v1/organizations/org", "https://x/v2/organizations/org"
    e._user_names = {AG1: "ArshKhan Pathan", AG2: "Riya Sharma"} if users else {}
    e._label_names = {LB1: "assign to Arsh"} if labels else {}
    e._stage_names = {ST1: "New Lead"} if stages else {}
    e._conv = {}
    return e


# ── 1. id shapes ──────────────────────────────────────────────────────────────
assert ie._scalar_id("abc") == "abc"
assert ie._scalar_id({"id": "abc", "name": "x"}) == "abc"
assert ie._scalar_id(["abc"]) == "abc"
assert ie._scalar_id([{"id": "abc"}]) == "abc"
assert ie._scalar_id(None) == "" and ie._scalar_id([]) == "" and ie._scalar_id("") == ""
print("[pass] id extraction handles string / object / list shapes")


# ── 2. chats list -> conversation map ─────────────────────────────────────────
class FakeResp:
    def __init__(self, status, payload): self.status_code, self._p, self.text = status, payload, ""
    def json(self): return self._p


class FakeSession:
    """Serves one page of chats for the 'active' view, nothing for 'closed'."""
    def __init__(self, items): self.items, self.headers, self.calls = items, {}, 0
    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        if json["filters"]["type"] == ["active"] and "offset=0" in url:
            return FakeResp(200, {"count": len(self.items), "results": {"data": self.items}})
        return FakeResp(200, {"count": 0, "results": {"data": []}})


chats = [
    # c1: label + agent, ids as plain strings (the usual shape)
    {"customer_id": "c1", "conversation_label_id": LB1, "assigned_to_user_id": AG1,
     "chat_status": "Active", "last_customer_message_at_utc": "2026-09-28T05:00:00+0000",
     "last_activity_at_utc": "2026-09-28T05:00:01+0000"},
    # c2: unlabelled + unassigned -> authoritative blanks
    {"customer_id": {"id": "c2"}, "conversation_label_id": None, "assigned_to_user_id": None,
     "chat_status": "Active", "last_activity_at_utc": "2026-09-27T05:00:00+0000"},
    # c3: nested object ids (customer / label / agent as objects)
    {"customer": {"id": "c3"}, "conversation_label": {"id": LB1, "name": "assign to Arsh"},
     "assigned_to_user": {"id": AG2}, "is_closed": True,
     "last_activity_at_utc": "2026-09-26T05:00:00+0000"},
    # c4: label id the lookup does not know (deleted label) -> key omitted
    {"customer_id": "c4", "conversation_label_id": "99999999-0000-0000-0000-000000000000",
     "assigned_to_user_id": AG1, "chat_status": "Active",
     "last_activity_at_utc": "2026-09-25T05:00:00+0000"},
    # c1 again but OLDER chat -> must not override the newer one
    {"customer_id": "c1", "conversation_label_id": None, "assigned_to_user_id": None,
     "chat_status": "Closed", "last_activity_at_utc": "2026-01-01T00:00:00+0000"},
]
e = make_enricher()
e.s = FakeSession(chats)
e.load_conversations()
assert e._conv["c1"]["Conversation Label"] == "assign to Arsh"
assert e._conv["c1"]["Assigned Agent"] == "ArshKhan Pathan"
assert e._conv["c1"]["Chat Status"] == "Active"
assert e._conv["c2"]["Conversation Label"] == "" and e._conv["c2"]["Assigned Agent"] == ""
assert e._conv["c3"]["Conversation Label"] == "assign to Arsh"
assert e._conv["c3"]["Assigned Agent"] == "Riya Sharma" and e._conv["c3"]["Chat Status"] == "Closed"
assert "Conversation Label" not in e._conv["c4"], "unknown label id must be left unknown"
assert e._conv["c4"]["Assigned Agent"] == "ArshKhan Pathan"
print("[pass] chats list -> label/agent names; blanks only when the chat really has none")

# lookup lists failed to load (the 28-Aug '/members/ Read timed out' case)
e0 = make_enricher(users=False, labels=False)
e0.s = FakeSession(chats)
e0.load_conversations()
assert "Assigned Agent" not in e0._conv["c1"] and "Conversation Label" not in e0._conv["c1"]
assert e0._conv["c2"]["Assigned Agent"] == ""            # still authoritative: nobody assigned
assert e0._conv["c1"]["Chat Status"] == "Active"          # unaffected columns still refreshed
print("[pass] lookup failure -> label/agent left unknown (never a UUID, never a blank)")


# ── 3. enr_contact_owner / enr_lead_stage from the DETAIL traits ─────────────
def fake_get_factory(detail_traits):
    def _get(url):
        if url.endswith("/customers/c1/"):
            return {"data": {"traits": detail_traits}}
        return {"data": []}                                   # notes / timeline: none
    return _get

e = make_enricher()
e._get = fake_get_factory({"_internal_contact_owner_id": AG2, "_internal_stage_id": ST1,
                           "course_advised": "Azure DE"})
out = e.enrich("c1")
assert out["enr_contact_owner"] == "Riya Sharma", out
assert out["enr_lead_stage"] == "New Lead"
assert out["Course Advised"] == "Azure DE"                    # existing custom-field path intact
assert out["enr_notes_count"] == 0 and out["enr_timeline_count"] == 0
# public-API copy (resolve_traits) still works, and never emits a raw UUID
assert e.resolve_traits({"trait__internal_contact_owner_id": AG1})["enr_contact_owner"] == "ArshKhan Pathan"
e0 = make_enricher(users=False)
assert "enr_contact_owner" not in e0.resolve_traits({"trait__internal_contact_owner_id": AG1})
e0._get = fake_get_factory({"_internal_contact_owner_id": AG1})
assert "enr_contact_owner" not in e0.enrich("c1")
print("[pass] enr_contact_owner / enr_lead_stage resolved from the detail record, no raw ids")


# ── 4 + 5 + 6. pyInteraktUsers row assembly ───────────────────────────────────
# Import the script module without its Google dependencies (utils is only used
# inside main()).
sys.modules.setdefault("utils", types.ModuleType("utils"))
sys.modules.setdefault("interakt_session", types.ModuleType("interakt_session"))
import pyInteraktUsers as pu                       # noqa: E402

existing = {
    "c1": {"id": "c1", "Conversation Label": "assign to Arsh", "Assigned Agent": "ArshKhan Pathan",
           "enr_contact_owner": "Riya Sharma", "enr_notes_count": "2", "Last Interaction Date": "01-Sep-2026 10:00 AM"},
    "c2": {"id": "c2", "Conversation Label": "assign to Arsh", "Assigned Agent": "ArshKhan Pathan",
           "enr_contact_owner": AG2},                       # raw id left by the failed-lookup run
    "c9": {"id": "c9", "Conversation Label": "follow up", "Assigned Agent": "Riya Sharma",
           "enr_contact_owner": "Riya Sharma", "enr_notes_count": "1"},
}
# enriched run: c1 in the chats map (still labelled), c2 in the map but now
# unlabelled/unassigned (authoritative blank), c9 NOT in the map at all
rows = [{"id": "c1", "Conversation Label": "assign to Arsh", "Assigned Agent": "ArshKhan Pathan"},
        {"id": "c2", "Conversation Label": "", "Assigned Agent": ""},
        {"id": "c9"}]
pu.preserve_web_columns(existing, rows, "id", only_missing=True)
assert rows[0]["enr_contact_owner"] == "Riya Sharma" and rows[0]["enr_notes_count"] == "2"
assert rows[1]["Conversation Label"] == "" and rows[1]["Assigned Agent"] == ""   # blank kept = authoritative
assert rows[2]["Conversation Label"] == "follow up" and rows[2]["Assigned Agent"] == "Riya Sharma"
assert rows[2]["enr_contact_owner"] == "Riya Sharma" and rows[2]["enr_notes_count"] == "1"
# base-only run (no web session): absent OR blank -> taken from the sheet (unchanged)
rows = [{"id": "c9", "Conversation Label": ""}]
pu.preserve_web_columns(existing, rows, "id", only_missing=False)
assert rows[0]["Conversation Label"] == "follow up" and rows[0]["Assigned Agent"] == "Riya Sharma"
print("[pass] enriched run keeps values the source had nothing for; base-only run unchanged")


class FakeHttpError(Exception):
    def __init__(self, status):
        super().__init__(f'<HttpError {status} returned "unavailable">')
        self.resp = types.SimpleNamespace(status=status)


class FakeService:
    def __init__(self, fails, payload):
        self.fails, self.payload, self.calls = fails, payload, 0
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, spreadsheetId=None, range=None): return self
    def execute(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise FakeHttpError(503)
        return self.payload

payload = {"values": [["id", "Conversation Label"], ["c1", "assign to Arsh"], ["", ""]]}
svc = FakeService(fails=2, payload=payload)
ex = pu._read_tab_by_key(svc, "sid", "Users", "id")
assert ex == {"c1": {"id": "c1", "Conversation Label": "assign to Arsh"}} and svc.calls == 3
svc = FakeService(fails=99, payload=payload)
try:
    pu._read_tab_by_key(svc, "sid", "Users", "id"); raise AssertionError("must not return {}")
except FakeHttpError:
    pass                                                    # persistent failure aborts the run
print("[pass] sheet read retries transient errors and aborts on a persistent one (never 'empty sheet')")

print("ALL CHECKS PASSED")
