"""
Verification of "Repeat-Retargeting Leads" in
sales_reports/pyConsolidatedLeadPerformanceReport.py
(run from the project root:  python sales_validation\\verify_repeat_retargeting.py).

No Google access and no real lead data: the master rows and the remarketing
"Full Details" audience are synthetic, built with the real column names and the
report's own interaction-history format.

Checks
  1. Reading the audience tab (header found by name, numeric / text phones, the
     'Updated' time, unusable layouts rejected).
  2. Flags: same norm_phone() matching as the rest of the report; unreadable
     audience -> "N/A" (never "not retargeted"); flags survive the masked copy.
  3. Daily / Weekly / Monthly / Manual: Summary metric placed right after
     "Total Lead Interactions"; Repeat Lead Details header line + IsRetargetingLead
     column right after "Walk-in Sch."; the same column + count in every counsellor
     tab's Repeat section; all counts reconcile; other tables unchanged.
  4. Missing data: metric "Not available", column "N/A", header says so.
  5. load_remarketing_audience() never raises (switched off / offline / bad sheet).
  6. Sales Layer 3 runs the remarketing script before the performance report.
  7. Inbound filter: a repeat lead counts only when an in-period interaction came
     from a platform other than IntelliBI (outbound follow-up); IntelliBI spelling
     variations, mixed days, inbound-only-before-the-period and blank platforms.
"""
import csv
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in ("common", "sales_reports"):
    sys.path.insert(0, os.path.join(ROOT, _p))
import pandas as pd                                          # noqa: E402
import pyConsolidatedLeadPerformanceReport as C              # noqa: E402

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"[{'pass' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAIL.append(label)


# =============================================================================
#  Synthetic data
# =============================================================================
FMT = "%d-%b-%Y %I:%M %p"


def lead(name, mobile, dates, counsellor="Asha"):
    hist = (f"Lead Source: {', '.join(['Website'] * len(dates))}\n"
            f"Lead Date: {', '.join(x.strftime(FMT) for x in dates)}\n"
            f"Counselling By: {', '.join([counsellor] * len(dates))}")
    return {C.C_FIRST: min(dates).strftime(FMT), C.C_LATEST: max(dates).strftime(FMT),
            C.C_INIT: min(dates).strftime(FMT), C.C_NAME: name, C.C_MOBILE: mobile,
            C.C_EMAIL: f"{name.split()[0].lower()}@example.com", C.C_PLAT: "Website",
            C.C_NINT: str(len(dates)), C.C_VALID: "Yes", C.C_RELEV: "Yes",
            C.C_WACONNECT: "", C.C_REF: "No", C.C_REFNAME: "", C.C_COURSE: "Power BI",
            C.C_REMARKS: "note", C.C_STATUS: "Warm", C.C_ADM: "", C.C_BACKOUT: "",
            C.C_COUNSEL: counsellor, C.C_GMEET: "No", C.C_WALKSCH: "No", C.C_HIST: hist,
            C.C_LEADTYPE: "Student", "IsWalk-In": "", "IsWebsite": "Yes",
            "IsWhatsapp": "", "IsCall": ""}


DAY = date(2026, 10, 7)


def at(d, h=11):
    return datetime.combine(d, datetime.min.time()).replace(hour=h)


OLD = at(DAY - timedelta(days=60))
MASTER = pd.DataFrame([
    lead("Fresh One", "9000000001", [at(DAY)]),                              # fresh, in audience
    lead("Fresh Two", "9000000002", [at(DAY)], "Ravi"),                      # fresh, not in audience
    lead("Repeat Plain", "9000000003", [OLD, at(DAY)]),                      # repeat, in (text 91…)
    lead("Repeat Spaced", "+91 90000 00004", [OLD, at(DAY)], "Ravi"),        # repeat, in (numeric)
    lead("Repeat Float", "09000000005", [OLD, at(DAY)]),                     # repeat, in (float cell)
    lead("Repeat Outside", "9000000006", [OLD, at(DAY)]),                    # repeat, NOT in audience
    lead("Repeat NoPhone", "", [OLD, at(DAY)], "Ravi"),                      # repeat, blank mobile
    lead("Old Only", "9000000008", [OLD]),                                   # not active in period
]).astype(str)

TITLE = "Google Ads Campaign Remarketing — Eligible Leads (same audience as the Google Ads phone list)"
SUMMARY = "Window: 29-Aug-2026 → 07-Oct-2026 (last 40 days)   ·   Audience: 5 lead(s)   ·   Updated 07-Oct-2026 06:45 PM IST"
HEADER = ["First Enquiry", "Latest Enquiry", "Full Name", "Mobile Number", "Email",
          "Platforms Used", "Interactions", "Relevant", "Is Referral", "Course Interested",
          "Notes / Remarks", "Admission Status", "Backout Reason", "Counselling By",
          "Google Meet Sch.", "Walk-in Sch.", "Lead Journey (Enquiry → Latest)",
          "Fresh / Repeat", "Google Ads Phone"]


def arow(mobile, phone):
    r = [""] * len(HEADER)
    r[3], r[-1] = mobile, phone
    return r


AUDIENCE = [[TITLE], [SUMMARY], HEADER,
            arow("9000000001", 919000000001),
            arow("9000000003", "919000000003"),
            arow("+91 90000 00004", 919000000004),
            arow("09000000005", 919000000005.0),
            arow("", 919000000009)]                 # someone not in this report

# =============================================================================
print("== 1. Reading the remarketing audience tab ==")
phones, upd = C.parse_remarketing_values(AUDIENCE)
check("audience phones (10-digit keys, header found by name)", sorted(phones),
      ["9000000001", "9000000003", "9000000004", "9000000005", "9000000009"])
check("'Updated' time read from the run summary row", upd, "07-Oct-2026 06:45 PM IST")
only_ads = [[TITLE], [SUMMARY], ["Google Ads Phone"], [919000000001]]
check("works with only the Google Ads Phone column", C.parse_remarketing_values(only_ads)[0],
      {"9000000001"})
for lbl, vals in (("no phone header", [[TITLE], ["a", "b"], ["1", "2"]]),
                  ("header but no rows (empty audience)", [[TITLE], [SUMMARY], HEADER]),
                  ("empty tab", [])):
    try:
        C.parse_remarketing_values(vals)
        check(f"{lbl} → rejected", "accepted", "ValueError")
    except ValueError:
        check(f"{lbl} → rejected", "ValueError", "ValueError")

# =============================================================================
print("\n== 2. Flags ==")
INFO_OK = {"available": True, "phones": phones, "updated": upd, "sheet_id": "x", "reason": ""}
INFO_NA = {"available": False, "phones": set(), "updated": "", "sheet_id": "", "reason": "test"}
flagged = C.flag_retargeting(MASTER, INFO_OK)
check("flags per lead (Yes / blank)", list(flagged[C.RETARGET_COL]),
      ["Yes", "", "Yes", "Yes", "Yes", "", "", ""])
check("source DataFrame not modified", C.RETARGET_COL in MASTER.columns, False)
check("unavailable audience → every lead N/A",
      set(C.flag_retargeting(MASTER, INFO_NA)[C.RETARGET_COL]), {"N/A"})
check("masked copy keeps the flags",
      list(C.mask_dataframe(flagged)[C.RETARGET_COL]), list(flagged[C.RETARGET_COL]))

# =============================================================================
print("\n== 3. Report tabs — Daily / Weekly / Monthly / Manual ==")


def find(tab, first):
    return next(i for i, r in enumerate(tab.rows) if r and r[0] == first)


def table(tab, header_first):
    hi = next(i for i in sorted(tab.headers) if tab.rows[i] and tab.rows[i][0] == header_first
              or (tab.rows[i] and header_first in tab.rows[i]))
    st, en = tab.data_span(hi)
    return tab.rows[hi], tab.rows[st:en]


def build(label, df, info):
    C.REMARKETING_INFO = info
    st, en = C.day_bounds(DAY)
    if label != "Daily":
        st = st - timedelta(days=3)
    return C.build_report(label, "test range", df, st, en)


EXPECT_REPEAT, EXPECT_RT = 5, 3                    # 5 repeat leads, 3 in the audience
for label in ("Daily", "Weekly", "Monthly", "Manual"):
    tabs, active = build(label, flagged, INFO_OK)
    summ = tabs["Summary"]
    ti = find(summ, "Total Lead Interactions")
    es = dict((r[0], r[1]) for r in summ.rows if len(r) == 3)
    check(f"{label}: metric directly below Total Lead Interactions",
          summ.rows[ti + 1][:1], [C.RETARGET_METRIC])
    check(f"{label}: metric value / % of total leads", summ.rows[ti + 1][1:],
          [EXPECT_RT, C.pct(EXPECT_RT, len(active))])
    check(f"{label}: Executive Summary Repeat Leads", es["Repeat Leads"], EXPECT_REPEAT)
    rep = tabs["Repeat Lead Details"]
    line = rep.rows[1][0]
    check(f"{label}: Repeat tab header line",
          ("Total Repeat Leads:  5" in line, f"{C.RETARGET_METRIC}:  3  (60.0% of repeat leads)" in line,
           "07-Oct-2026 06:45 PM IST" in line), (True, True, True))
    hdr, rows = table(rep, "Lead Journey (Enquiry → Latest)")
    ci = hdr.index(C.RETARGET_HEADER)
    check(f"{label}: IsRetargetingLead right after Walk-in Sch.", hdr[ci - 1], "Walk-in Sch.")
    check(f"{label}: Lead Information Status still last", hdr[-1], "Lead Information Status")
    yes_rows = sorted(r[hdr.index("Full Name")] for r in rows if r[ci] == "Yes")
    check(f"{label}: 'Yes' rows = metric (reconciles)", (len(rows), len(yes_rows)),
          (EXPECT_REPEAT, EXPECT_RT))
    check(f"{label}: which repeat leads are Yes", yes_rows,
          ["Repeat Float", "Repeat Plain", "Repeat Spaced"])
    check(f"{label}: other values blank", {r[ci] for r in rows if r[ci] != "Yes"}, {""})
    check(f"{label}: status cell colour column still the last column",
          {c for (_r, c) in rep.cell_fills}, {len(hdr) - 1})
    fhdr, _ = table(tabs["Fresh Lead Details"], "Lead Journey (Enquiry → Latest)")
    check(f"{label}: Fresh Lead Details unchanged (no new column)", C.RETARGET_HEADER in fhdr, False)
    cb = {n: t for n, t in tabs.items() if n.startswith("CB - ")}
    cb_yes = 0
    for n, t in cb.items():
        heads = [i for i in sorted(t.headers) if "Lead Journey (Enquiry → Latest)" in t.rows[i]]
        fresh_h, rep_h = heads[0], heads[-1]
        rep_title = t.rows[rep_h - 1][0]
        rows = t.rows[slice(*t.data_span(rep_h))]
        hdr = t.rows[rep_h]
        ci = hdr.index(C.RETARGET_HEADER)
        n_yes = sum(1 for r in rows if r[ci] == "Yes")
        cb_yes += n_yes
        check(f"{label}: {n} repeat section — column after Walk-in Sch., status last",
              (hdr[ci - 1], hdr[-1]), ("Walk-in Sch.", "Lead Information Status"))
        check(f"{label}: {n} repeat title count = Yes rows",
              rep_title.endswith(f"{C.RETARGET_METRIC}:  {n_yes}"), True)
        check(f"{label}: {n} fresh section unchanged (no column)",
              C.RETARGET_HEADER in t.rows[fresh_h], False)
        check(f"{label}: {n} Executive Summary unchanged (no metric)",
              any(r and r[0] == C.RETARGET_METRIC for r in t.rows), False)
    check(f"{label}: counsellor Yes rows add up to the Summary metric", cb_yes, EXPECT_RT)
    with tempfile.TemporaryDirectory() as td:
        C.write_local_xlsx(os.path.join(td, "r.xlsx"), tabs)
        check(f"{label}: workbook writes", os.path.getsize(os.path.join(td, "r.xlsx")) > 0, True)

# masked copy gives the same numbers
tabs_m, _ = build("Weekly", C.mask_dataframe(flagged), INFO_OK)
ti = find(tabs_m["Summary"], "Total Lead Interactions")
check("masked copy: same metric value", tabs_m["Summary"].rows[ti + 1][1], EXPECT_RT)

# =============================================================================
print("\n== 4. Remarketing data unavailable ==")
for label in ("Daily", "Monthly"):
    tabs, active = build(label, C.flag_retargeting(MASTER, INFO_NA), INFO_NA)
    summ = tabs["Summary"]
    ti = find(summ, "Total Lead Interactions")
    check(f"{label}: metric shows Not available", summ.rows[ti + 1], [C.RETARGET_METRIC, "Not available", ""])
    rep = tabs["Repeat Lead Details"]
    check(f"{label}: header says Not available", "Not available  (remarketing sheet could not be read)"
          in rep.rows[1][0], True)
    hdr, rows = table(rep, "Lead Journey (Enquiry → Latest)")
    check(f"{label}: column shows N/A (not blank)", {r[hdr.index(C.RETARGET_HEADER)] for r in rows}, {"N/A"})
    cbt = [t for n, t in tabs.items() if n.startswith("CB - ")]
    check(f"{label}: counsellor repeat titles say Not available",
          all(any(str(r[0]).endswith(f"{C.RETARGET_METRIC}:  Not available") for r in t.rows if r)
              for t in cbt), True)
# A DataFrame without the helper column (e.g. an old caller) is treated as unavailable.
C.REMARKETING_INFO = None
tabs, _ = C.build_report("Daily", "x", MASTER, *C.day_bounds(DAY))
ti = find(tabs["Summary"], "Total Lead Interactions")
check("no flags attached → Not available", tabs["Summary"].rows[ti + 1][1], "Not available")

# =============================================================================
print("\n== 5. load_remarketing_audience() never raises ==")
_saved = (C.REMARKETING_CHECK, C.LOCAL_REMARKETING_CSV, C.LOCAL_MASTER_CSV)
try:
    C.REMARKETING_CHECK = False
    check("switched off → unavailable", C.load_remarketing_audience()["available"], False)
    C.REMARKETING_CHECK = True
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "aud.csv")
        with open(p, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(AUDIENCE)
        C.LOCAL_REMARKETING_CSV = p
        got = C.load_remarketing_audience()
        check("local CSV export → available, same phones", (got["available"], got["phones"]),
              (True, phones))
        with open(p, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows([[TITLE], [SUMMARY], HEADER])
        check("empty audience CSV → unavailable", C.load_remarketing_audience()["available"], False)
    C.LOCAL_REMARKETING_CSV = None
    C.LOCAL_MASTER_CSV = "offline.csv"
    check("offline run (no CSV) → unavailable", C.load_remarketing_audience()["available"], False)
    C.LOCAL_MASTER_CSV = None

    class _Boom:
        def __getattr__(self, _n):
            raise RuntimeError("HttpError 404 not found")

    _orig_creds, _orig_ids = C._creds, C._remarketing_sheet_ids
    C._creds = lambda *a, **k: (_ for _ in ()).throw(SystemExit("no service account"))
    C._remarketing_sheet_ids = lambda drive: ["sheet-id"]
    got = C.load_remarketing_audience(sheets=_Boom(), drive=object())
    check("unreadable sheet / no credentials → unavailable, no exception",
          (got["available"], bool(got["reason"])), (False, True))
    C._creds, C._remarketing_sheet_ids = _orig_creds, _orig_ids
finally:
    C.REMARKETING_CHECK, C.LOCAL_REMARKETING_CSV, C.LOCAL_MASTER_CSV = _saved

# =============================================================================
print("\n== 6. Sales Layer 3 order ==")
src = open(os.path.join(ROOT, "scripts", "run_layer3.py"), encoding="utf-8").read()
steps = src[src.find("scripts = ["):]
check("remarketing → performance report → follow-up report",
      0 <= steps.find("run_script(remarketing") < steps.find("run_script(perf")
      < steps.find("run_script(follow"), True)

# =============================================================================
print("\n== 7. Inbound filter (IntelliBI = outbound follow-up) ==")
# Synthetic numbers; the interaction PATTERNS mirror the business examples.


def lead_src(name, mobile, steps, counsellor="Asha"):
    """steps: list of (datetime, platform, counselled_by)."""
    base = lead(name, mobile, [d for d, _p, _c in steps], counsellor)
    base[C.C_HIST] = (f"Lead Source: {', '.join(p for _d, p, _c in steps)}\n"
                      f"Lead Date: {', '.join(d.strftime(FMT) for d, _p, _c in steps)}\n"
                      f"Counselling By: {', '.join(c for _d, _p, c in steps)}")
    base[C.C_PLAT] = ", ".join(dict.fromkeys(p for _d, p, _c in steps))
    return base


D8 = date(2026, 10, 8)


def t_(d, h, m=0):
    return datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m)


IN_LEADS = pd.DataFrame([
    # Example 1 pattern: old Website enquiry, returns via Website → Yes
    lead_src("Ex1 Website", "9111100001", [(t_(date(2026, 7, 10), 11, 4), "Website", ""),
                                           (t_(D8, 1, 54), "Website", "Arshkhan")]),
    # Example 2 pattern: two old Calls, returns as Walk-In → Yes
    lead_src("Ex2 WalkIn", "9111100002", [(t_(date(2026, 8, 3), 12, 29), "Call", "Harish"),
                                          (t_(date(2026, 8, 3), 13, 10), "Call", "Harish"),
                                          (t_(D8, 17, 4), "Walk-In", "Harish")], "Harish"),
    # Example 3 pattern: old WhatsApp, in-period ONLY IntelliBI → blank
    lead_src("Ex3 IntelliBI", "9111100003", [(t_(date(2026, 9, 30), 11, 42), "WhatsApp", ""),
                                             (t_(D8, 14, 23), "IntelliBI", "Arshkhan")]),
    # IntelliBI spelling variations only in period → blank
    lead_src("Var IntelliBI", "9111100004", [(t_(date(2026, 8, 1), 10), "Call", ""),
                                             (t_(D8, 10), " intellibi ", "Asha"),
                                             (t_(D8, 12), "Intelli BI", "Asha")]),
    # IntelliBI follow-up AND an inbound WhatsApp the same day → Yes
    lead_src("Mixed", "9111100005", [(t_(date(2026, 8, 1), 10), "Website", ""),
                                     (t_(D8, 9), "IntelliBI", "Asha"),
                                     (t_(D8, 15), "WhatsApp", "Asha")]),
    # Inbound Website only BEFORE the period, IntelliBI in period → blank
    lead_src("Old Inbound", "9111100006", [(t_(date(2026, 8, 1), 10), "Website", ""),
                                           (t_(date(2026, 9, 20), 10), "Website", ""),
                                           (t_(D8, 11), "IntelliBI", "Asha")]),
    # Inbound repeat but NOT in the audience → blank
    lead_src("Not In Audience", "9111100007", [(t_(date(2026, 8, 1), 10), "Website", ""),
                                               (t_(D8, 11), "Call", "Asha")]),
    # Fresh lead via Website, in the audience → never counted (not a repeat lead)
    lead_src("Fresh Inbound", "9111100008", [(t_(D8, 11), "Website", "")]),
    # Blank platform in period (unknown) → cannot be confirmed inbound → blank
    lead_src("Blank Platform", "9111100009", [(t_(date(2026, 8, 1), 10), "Website", ""),
                                              (t_(D8, 11), "", "Asha")]),
]).astype(str)
IN_AUD = {"9111100001", "9111100002", "9111100003", "9111100004", "9111100005",
          "9111100006", "9111100008", "9111100009"}
INFO_IN = {"available": True, "phones": IN_AUD, "updated": "", "sheet_id": "x", "reason": ""}
IN_FLAGS = C.flag_retargeting(IN_LEADS, INFO_IN)

check("platform classification", [C.is_inbound_src(x) for x in
      ("Website", "WhatsApp", "Call", "Walk-In", "IntelliBI", "intellibi", " INTELLIBI ",
       "Intelli BI", "Intelli-BI", "", "—")],
      [True, True, True, True, False, False, False, False, False, False, False])

PERIODS = {   # label -> (start, end); Daily = 08-Oct; others contain 08-Oct but not 30-Sep
    "Daily": C.day_bounds(D8),
    "Weekly": (C.day_bounds(date(2026, 10, 5))[0], C.day_bounds(date(2026, 10, 11))[1]),
    "Monthly": (C.day_bounds(date(2026, 10, 1))[0], C.day_bounds(date(2026, 10, 31))[1]),
    "Manual": (C.day_bounds(date(2026, 10, 2))[0], C.day_bounds(D8)[1]),
}
WANT_YES = ["Ex1 Website", "Ex2 WalkIn", "Mixed"]
for label, (st, en) in PERIODS.items():
    C.REMARKETING_INFO = INFO_IN
    tabs, active = C.build_report(label, "test range", IN_FLAGS, st, en)
    rep = tabs["Repeat Lead Details"]
    hdr, rows = table(rep, "Lead Journey (Enquiry → Latest)")
    ci, ni = hdr.index(C.RETARGET_HEADER), hdr.index("Full Name")
    got = {r[ni]: r[ci] for r in rows}
    check(f"{label}: Yes leads (inbound repeat + in audience)",
          sorted(n for n, v in got.items() if v == "Yes"), WANT_YES)
    check(f"{label}: Example-3 pattern / IntelliBI-only / old-inbound / blank platform → blank",
          [got.get(n) for n in ("Ex3 IntelliBI", "Var IntelliBI", "Old Inbound", "Blank Platform")],
          ["", "", "", ""])
    check(f"{label}: IntelliBI-only leads are still Repeat Leads (classification unchanged)",
          ("Ex3 IntelliBI" in got, len(rows)), (True, 8))
    summ = tabs["Summary"]
    ti = find(summ, "Total Lead Interactions")
    check(f"{label}: Summary metric = Yes rows", summ.rows[ti + 1][1], len(WANT_YES))
    check(f"{label}: Repeat header = Yes rows",
          f"{C.RETARGET_METRIC}:  {len(WANT_YES)}  (" in rep.rows[1][0], True)
    cb_yes = 0
    for n, tb in tabs.items():
        if not n.startswith("CB - "):
            continue
        heads = [i for i in sorted(tb.headers) if "Lead Journey (Enquiry → Latest)" in tb.rows[i]]
        h = tb.rows[heads[-1]]
        if C.RETARGET_HEADER in h:
            cb_yes += sum(1 for r in tb.rows[slice(*tb.data_span(heads[-1]))]
                          if r[h.index(C.RETARGET_HEADER)] == "Yes")
    check(f"{label}: counsellor Yes rows add up to the metric", cb_yes, len(WANT_YES))

# Example-3 pattern in a period that does NOT contain its IntelliBI touch but does
# contain the old WhatsApp enquiry as a repeat → depends only on in-period platforms.
C.REMARKETING_INFO = INFO_IN
_t, _a = C.build_report("Daily", "x", IN_FLAGS, *C.day_bounds(date(2026, 9, 20)))
_h, _r = table(_t["Repeat Lead Details"], "Lead Journey (Enquiry → Latest)")
check("in-period platform decides: Old Inbound on 20-Sep (Website) → Yes",
      {r[_h.index("Full Name")]: r[_h.index(C.RETARGET_HEADER)] for r in _r}.get("Old Inbound"), "Yes")
# Audience unavailable still wins over the inbound rule → N/A, not blank
C.REMARKETING_INFO = INFO_NA
_t, _a = C.build_report("Daily", "x", C.flag_retargeting(IN_LEADS, INFO_NA), *C.day_bounds(D8))
_h, _r = table(_t["Repeat Lead Details"], "Lead Journey (Enquiry → Latest)")
check("audience unavailable → N/A for inbound and IntelliBI-only alike",
      {r[_h.index(C.RETARGET_HEADER)] for r in _r}, {"N/A"})

print("\nALL CHECKS PASSED" if not FAIL else f"\n{len(FAIL)} CHECK(S) FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
