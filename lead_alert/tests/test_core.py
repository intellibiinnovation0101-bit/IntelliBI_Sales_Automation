"""
Core-logic tests that need no Google / GUI / network:
  * atomic single-claim  (two counsellors, one winner)
  * duplicate-lead dedup
  * expire transition
  * Active-only counsellor loading from counsellors.json
  * operating-window + row->lead mapping

Run:  python lead_alert/tests/test_core.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_SVC = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(_SVC))

import config                                   # noqa: E402

# isolate the DB in a temp file BEFORE importing store
_tmpdb = Path(tempfile.mkdtemp()) / "t.db"
config.DB_PATH = _tmpdb

import store       # noqa: E402
import ops         # noqa: E402
import counsellors  # noqa: E402

_failures = []


def check(name, cond):
    print(("  PASS" if cond else "  FAIL"), name)
    if not cond:
        _failures.append(name)


# ── atomic single-claim ──────────────────────────────────────────────────────
lead = {"lead_id": "L1", "name": "Asha", "received_at": ops.now_str()}
check("insert new lead", store.insert_lead(lead) is True)
check("duplicate insert rejected", store.insert_lead(lead) is False)

r1 = store.claim_lead("L1", "a@x.com", "A", ops.now_str())
r2 = store.claim_lead("L1", "b@x.com", "B", ops.now_str())
check("first claim wins", r1 == "assigned")
check("second claim loses", r2 == "already")
check("assigned_to persisted", store.get_lead("L1")["assigned_to"] == "a@x.com")

# ── expire ───────────────────────────────────────────────────────────────────
store.insert_lead({"lead_id": "L2", "name": "Ravi", "received_at": ops.now_str()})
check("expire an open lead", store.expire_lead("L2") is True)
check("cannot claim expired", store.claim_lead("L2", "c@x.com", "C",
                                               ops.now_str()) == "expired")

# ── Active-only counsellor loading ───────────────────────────────────────────
tmp_json = Path(tempfile.mkdtemp()) / "counsellors.json"
tmp_json.write_text(json.dumps({
    "counsellors": [
        {"counsellor_name": "Harish", "emailid": "h@x.com", "current_status": "Active"},
        {"counsellor_name": "Old",    "emailid": "o@x.com", "current_status": "Inactive"},
        {"counsellor_name": "Dup",    "emailid": "H@x.com", "current_status": "Active"},
    ],
    "intellibiadmin": [
        {"intellibi_admin_name": "Admin", "emailid": "admin@x.com", "current_status": "Active"},
    ],
}), encoding="utf-8")
config.SETTINGS.counsellors_json = str(tmp_json)
config.SETTINGS.alert_sections = ["counsellors"]
config.SETTINGS.escalate_to_section = "intellibiadmin"

recips = counsellors.active_recipients()
emails = [r["email"].lower() for r in recips]
check("only Active counsellors", set(emails) == {"h@x.com"})
check("inactive excluded", "o@x.com" not in emails)
check("case-insensitive dedup", emails.count("h@x.com") == 1)
check("escalation section resolves", [r["email"] for r in
      counsellors.escalation_recipients()] == ["admin@x.com"])
check("is_active_counsellor true", counsellors.is_active_counsellor("H@X.com"))
check("is_active_counsellor false", not counsellors.is_active_counsellor("o@x.com"))

# ── window + row->lead ───────────────────────────────────────────────────────
from datetime import datetime  # noqa: E402
config.SETTINGS.active_from, config.SETTINGS.active_to = "09:30", "23:00"
check("inside window", ops.within_active_window(datetime(2026, 1, 1, 12, 0)))
check("before window", not ops.within_active_window(datetime(2026, 1, 1, 8, 0)))
check("after window", not ops.within_active_window(datetime(2026, 1, 1, 23, 30)))

row = {"_row": 42, "name": "Asha K", "mobile": "9876543210", "email": "a@x.com",
       "course": "Data Science", "form_type": "Alumni 1:1", "current_role": "QA",
       "message": "call me", "enquiry_date": "01-Jul-2026"}
L = ops.build_lead_from_row(row)
check("lead_id from row", L["lead_id"].endswith("row42"))
check("subject synthesized", L["subject"] == "New Alumni 1:1 Enquiry Received")
pub = ops.lead_public({**L, "status": "RECEIVED"})
check("public has open_email_url", pub["open_email_url"].startswith("http"))
check("public preview present", "Data Science" in pub["preview"])

print()
if _failures:
    print("FAILURES:", _failures)
    sys.exit(1)
print("ALL CORE TESTS PASSED")
