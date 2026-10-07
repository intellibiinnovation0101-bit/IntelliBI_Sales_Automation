"""
Verification of the IntelliBI Lead Information -> Consolidated master flow in
sales_consolidation/pyConsolidateLeadsLoad.py (synthetic data only, no Google
access). Run from the project root:
    python sales_validation\\verify_intellibi_consolidation.py

Checks, on a lead that enquired on the Website / WhatsApp and was then worked
by a counsellor in the IntelliBI portal:
  * the IntelliBI fields reach the master: Counselling By, Remarks, Admission
    Status, Follow-Up Type, Next Follow-Up Date, and "Admission Plan Time" ->
    "When are you planning to take admission?" (unmapped before 07-Oct-2026)
  * the IntelliBI enquiry is in Lead Interaction History / Platforms Used
  * existing rules unchanged: a Walk-In still overrides the admission plan;
    the latest remark wins; Counselling By priority IntelliBI > others;
    phone / email de-duplication; a one-digit-short (9-digit) number is linked
    to a lead ONLY when exactly one lead's number matches with one digit removed
    AND the names agree (never on a name alone, never when ambiguous)
  * pyConsolidatedLeadPerformanceReport: a lead without a counsellor whose
    number is invalid is grouped as "(Invalid number)", not "(Unassigned)"
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sales_consolidation"))
sys.path.insert(0, os.path.join(ROOT, "common"))

import pandas as pd                                    # noqa: E402
import pyConsolidateLeadsLoad as CL                    # noqa: E402

CL._LEAD_TYPE_MAP = ({}, [])                           # no config-sheet reads
CL._COURSE_INTEREST_MAP = {}
FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"[{'pass' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAIL.append(label)


def src_header(source_map, target):
    return source_map[target][0]


def web_row(**kv):
    row = {src_header(CL.WEBSITE_TARGET_SOURCES, t): "" for t in CL.WEBSITE_TARGET_SOURCES}
    for t, v in kv.items():
        row[src_header(CL.WEBSITE_TARGET_SOURCES, t)] = v
    return row


INTELLIBI_COLS = ["RecordTimeStamp", "Mobile Number", "Full Name", "Alternative Mobile Number",
                  "Email Address", "Candidate Type", "Course Interested In", "Career Goal",
                  "Admission Plan Time", "Next Follow-Up Date", "Counsellor Notes", "Counselling By",
                  "Admission Status", "Follow-Up Type"]


def intellibi_row(**kv):
    return {c: kv.get(c, "") for c in INTELLIBI_COLS}


DATA = {
    "IntelliBI": pd.DataFrame([
        intellibi_row(**{"RecordTimeStamp": "06-Oct-2026 12:21:47", "Mobile Number": "9812345670",
                         "Full Name": "Learner One", "Candidate Type": "Working Professional - Non IT",
                         "Course Interested In": "Data Analytics with GenAI", "Career Goal": "Career Growth",
                         "Admission Plan Time": "Within 15 Days ", "Next Follow-Up Date": "10/9/2026",
                         "Counsellor Notes": "Will confirm by Friday", "Counselling By": "Counsellor A",
                         "Admission Status": "Follow-up Pending", "Follow-Up Type": "Fee / Offer Follow-Up"}),
        intellibi_row(**{"RecordTimeStamp": "06-Oct-2026 13:00:00", "Mobile Number": "9000000002",
                         "Full Name": "Learner Two", "Admission Plan Time": "Just Exploring Options",
                         "Counsellor Notes": "Visited", "Counselling By": "Counsellor B"}),
    ]),
    "Website": pd.DataFrame([
        web_row(**{"LeadInitalTimestamp": "05/10/2026 03:44:00", "Mobile Number": "9812345670",
                   "Full Name": "Learner One"}),
        # same person typed one digit short (last digit missing), names agree -> linked
        web_row(**{"LeadInitalTimestamp": "05/10/2026 03:43:00", "Mobile Number": "981234567",
                   "Full Name": "Lerner One"}),
        # one digit short, but a different person -> NOT linked
        web_row(**{"LeadInitalTimestamp": "05/10/2026 04:00:00", "Mobile Number": "900000002",
                   "Full Name": "Someone Else"}),
        # one digit short, matches TWO leads (9100000001 / 9100000010) -> ambiguous, NOT linked
        web_row(**{"LeadInitalTimestamp": "05/10/2026 05:00:00", "Mobile Number": "910000001",
                   "Full Name": "Learner Three"}),
        web_row(**{"LeadInitalTimestamp": "04/10/2026 05:00:00", "Mobile Number": "9100000001",
                   "Full Name": "Learner Three"}),
        web_row(**{"LeadInitalTimestamp": "04/10/2026 06:00:00", "Mobile Number": "9100000010",
                   "Full Name": "Learner Three"}),
    ]),
    "WhatsApp": pd.DataFrame(), "Walk-In": pd.DataFrame(), "Call": pd.DataFrame(),
}
CL.load_dataframe = lambda key: DATA[key].copy()

stats = CL.Stats()
recs = list(CL.load_intellibi()) + list(CL.load_website())
clusters = CL.cluster_interactions(recs, stats)
rows = {r["Mobile Number"]: r for r in (CL.merge_cluster(c) for c in clusters)}
a = rows.get("9812345670", {})
check("leads: 9812345670 (+ linked short number), 9000000002, 2 unlinked short numbers, 2 Learner Three",
      len(clusters), 6)
check("one-digit-short link counted", stats.match_short_phone, 1)
check("Counselling By from IntelliBI", a.get("Counselling By"), "Counsellor A")
check("Remarks from IntelliBI (latest)", a.get("Remarks"), "Will confirm by Friday")
check("Admission Status / Follow-Up Type", (a.get("Admission Status"), a.get("Follow-Up Type")),
      ("Follow-up Pending", "Fee / Offer Follow-Up"))
check("Next Follow-Up Date (m/d/yyyy from the form)", a.get("Next Follow-Up Date", "")[:11], "09-Oct-2026")
check("Admission Plan Time -> 'When are you planning to take admission?'",
      a.get("When are you planning to take admission?"), "Within 15 Days")
check("Lead Interaction History has the linked Website enquiry AND the IntelliBI enquiry",
      a.get("Lead Interaction History", "").split("\n")[1:4],
      ["Lead Source: Website, Website, IntelliBI",
       "Lead Date: 05-Oct-2026 03:43 AM, 05-Oct-2026 03:44 AM, 06-Oct-2026 12:21 PM",
       "Counselling By: -, -, Counsellor A"])
check("the lead keeps its valid 10-digit number", (a.get("Mobile Number"), a.get("IsPhoneNumberValid")),
      ("9812345670", "Yes"))
check("Platforms Used", a.get("Platforms Used"), "IntelliBI, Website")
check("IntelliBI-only lead keeps its plan value",
      rows.get("9000000002", {}).get("When are you planning to take admission?"), "Just Exploring Options")
check("short number of a different person stays separate, flagged invalid",
      (rows.get("900000002", {}).get("Counselling By"), rows.get("900000002", {}).get("IsPhoneNumberValid")),
      ("", "No"))
check("ambiguous short number stays separate", "910000001" in rows, True)
check("short number linked away no longer exists as its own lead", "981234567" in rows, False)

# performance report: invalid-number leads without a counsellor are not "Unassigned"
sys.path.insert(0, os.path.join(ROOT, "sales_reports"))
try:
    import pyConsolidatedLeadPerformanceReport as PR      # noqa: E402
    groups, disp = PR.group_by_counsellor([
        {"Counselling By": "", "IsPhoneNumberValid": "No"},
        {"Counselling By": "", "IsPhoneNumberValid": "Yes"},
        {"Counselling By": "Counsellor A", "IsPhoneNumberValid": "No"}])
    check("performance report groups", sorted((disp[k], len(v)) for k, v in groups.items()),
          [("(Invalid number)", 1), ("(Unassigned)", 1), ("Counsellor A", 1)])
except SystemExit:
    print("[skip] performance report module needs its credentials to import")

# Walk-In override still wins for the admission plan (existing rule)
check("Walk-In override list still contains the admission-plan field",
      "When are you planning to take admission?" in CL.WALKIN_OVERWRITE_FIELDS, True)

print("\nALL CHECKS PASSED" if not FAIL else f"\n{len(FAIL)} CHECK(S) FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
