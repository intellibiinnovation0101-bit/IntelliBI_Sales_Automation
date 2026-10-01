"""
Verification of google_ads_campaign_remarketing/pyGoogleAdsRemarketingAudience.py
(run from the project root:  python sales_validation\\verify_google_ads_remarketing.py).

No Google access: Sheets and Drive are replaced by an in-memory emulator that
applies a batchUpdate ALL-OR-NOTHING (as Google does) and can be told to fail.
The production audience starts exactly like the real "Retargeting IntelliBi"
sheet: tab "Sheet1" (gid 0), A1 "Mobile", numbers 91XXXXXXXXXX with format "0".
Leads are synthetic, built with the master sheet's real column names and the
report's own interaction-history format.
"""
import copy
import os
import re
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "google_ads_campaign_remarketing"))
sys.path.insert(0, os.path.join(ROOT, "common"))
import pandas as pd                                          # noqa: E402
import pyGoogleAdsRemarketingAudience as G                   # noqa: E402

C = G.clpr
FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"[{'pass' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAIL.append(label)


# =============================================================================
#  In-memory Google Sheets + Drive
# =============================================================================
class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


def _a1(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n - 1


class Book:
    def __init__(self, tabs):
        self.tabs = tabs                     # [{"props":..., "cells": {(r,c): value}, "fmt": {}}]


class FakeSheets:
    def __init__(self):
        self.books, self.fail_batch, self.batches = {}, set(), []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def _tab(self, sid, rng):
        title = re.match(r"'([^']+)'", rng).group(1)
        return next(t for t in self.books[sid].tabs if t["props"]["title"] == title)

    def get(self, spreadsheetId, fields=None, range=None, valueRenderOption=None):
        if range is not None:                              # values().get
            def run():
                t = self._tab(spreadsheetId, range)
                m = re.search(r"!([A-Z]+)(\d*):([A-Z]+)(\d*)$", range)
                c0, c1 = (_a1(m.group(1)), _a1(m.group(3))) if m else (0, 999)
                r0 = int(m.group(2)) - 1 if m and m.group(2) else 0
                cells = t["cells"]
                if not cells:
                    return {"values": []}
                maxr = max(r for r, _c in cells)
                out = []
                for r in builtins_range(r0, maxr + 1):
                    row = [cells.get((r, c), "") for c in builtins_range(c0, min(c1, 60) + 1)]
                    while row and row[-1] == "":
                        row.pop()
                    out.append(row)
                while out and not out[-1]:
                    out.pop()
                return {"values": out}
            return Req(run)
        return Req(lambda: {"sheets": [{"properties": copy.deepcopy(t["props"])}
                                       for t in self.books[spreadsheetId].tabs]})

    def update(self, spreadsheetId, range, valueInputOption, body):
        def run():
            t = self._tab(spreadsheetId, range)
            for j, v in enumerate(body["values"][0]):
                t["cells"][(0, j)] = v
            return {}
        return Req(run)

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        def run():
            t = self._tab(spreadsheetId, range)
            r = max([r for r, _c in t["cells"]] or [-1]) + 1
            for j, v in enumerate(body["values"][0]):
                t["cells"][(r, j)] = v
            return {}
        return Req(run)

    def batchUpdate(self, spreadsheetId, body):
        def run():
            if spreadsheetId in self.fail_batch:
                raise RuntimeError("HttpError 500 simulated")
            book = self.books[spreadsheetId]
            work = copy.deepcopy(book.tabs)                # all-or-nothing
            for rq in body["requests"]:
                self._apply(work, rq)
            book.tabs = work
            self.batches.append((spreadsheetId, [list(r)[0] for r in body["requests"]]))
            return {}
        return Req(run)

    def _apply(self, tabs, rq):
        (kind, a), = rq.items()
        by_id = {t["props"]["sheetId"]: t for t in tabs}
        if kind == "addSheet":
            nid = max(by_id) + 1
            tabs.append({"props": {"sheetId": nid, "title": a["properties"]["title"],
                                   "gridProperties": {"rowCount": 1000, "columnCount": 26}},
                         "cells": {}, "fmt": {}})
        elif kind == "updateSheetProperties":
            p = by_id[a["properties"]["sheetId"]]["props"]
            if "title" in a["properties"]:
                p["title"] = a["properties"]["title"]
            p.setdefault("gridProperties", {}).update(a["properties"].get("gridProperties", {}))
        elif kind == "appendDimension":
            by_id[a["sheetId"]]["props"]["gridProperties"]["rowCount"] += a["length"]
        elif kind == "updateCells":
            t = by_id[(a.get("start") or a.get("range"))["sheetId"]]
            rows = t["props"]["gridProperties"]["rowCount"]
            if "rows" in a:
                r0, c0 = a["start"]["rowIndex"], a["start"]["columnIndex"]
                for i, row in enumerate(a["rows"]):
                    if r0 + i >= rows:
                        raise RuntimeError("write beyond grid")
                    for j, cell in enumerate(row["values"]):
                        v = cell["userEnteredValue"]
                        t["cells"][(r0 + i, c0 + j)] = v.get("numberValue", v.get("stringValue"))
                        if "userEnteredFormat" in cell:
                            t["fmt"][(r0 + i, c0 + j)] = cell["userEnteredFormat"]
                        if t["cells"][(r0 + i, c0 + j)] == "":
                            del t["cells"][(r0 + i, c0 + j)]
            else:                                          # clear values in range
                g = a["range"]
                for k in [k for k in t["cells"]
                          if g.get("startRowIndex", 0) <= k[0] < g.get("endRowIndex", 10 ** 9)
                          and g.get("startColumnIndex", 0) <= k[1] < g.get("endColumnIndex", 10 ** 9)]:
                    del t["cells"][k]
        # formats / filters / widths: accepted, not modelled


import builtins                                                  # noqa: E402
builtins_range = builtins.range


class FakeDrive:
    def __init__(self, sheets):
        self.sheets, self.files_meta, self.created = sheets, [], 0

    def files(self):
        return self

    def list(self, q, fields, orderBy=None, supportsAllDrives=True, includeItemsFromAllDrives=True):
        name = re.search(r"name = '(.+?)' and mimeType", q).group(1).replace("\\'", "'")
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        return Req(lambda: {"files": [f for f in self.files_meta
                                      if f["name"] == name and f["parent"] == parent]})

    def create(self, body, fields, supportsAllDrives=True):
        def run():
            self.created += 1
            fid = f"details{self.created}"
            self.files_meta.append({"id": fid, "name": body["name"], "parent": body["parents"][0],
                                    "createdTime": str(self.created)})
            self.sheets.books[fid] = Book([{"props": {"sheetId": 0, "title": "Sheet1",
                                                      "gridProperties": {"rowCount": 1000, "columnCount": 26}},
                                            "cells": {}, "fmt": {}}])
            return {"id": fid}
        return Req(run)


def production_book(phones, extra_rows=0):
    cells = {(0, 0): "Mobile"}
    for i, p in enumerate(phones, 1):
        cells[(i, 0)] = p
    return Book([{"props": {"sheetId": 0, "title": "Sheet1",
                            "gridProperties": {"rowCount": max(1000, len(phones) + 1 + extra_rows),
                                               "columnCount": 26}},
                  "cells": cells, "fmt": {(i, 0): {"numberFormat": {"type": "NUMBER", "pattern": "0"}}
                                          for i in range(1, len(phones) + 1)}}])


def prod_phones(fs):
    t = fs.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]
    maxr = max(r for r, _c in t["cells"])
    return [t["cells"].get((r, 0)) for r in range(1, maxr + 1)]


# =============================================================================
#  Synthetic master leads (real column names, the report's history format)
# =============================================================================
COLS = list(pd.read_csv(os.path.join(ROOT, "sales_validation", "_master_header.csv")).columns) \
    if os.path.exists(os.path.join(ROOT, "sales_validation", "_master_header.csv")) else None


def lead(name, mobile, dates, relevant="Yes", valid="Yes", connect="", adm="", srcs=None,
         ref="No", status="Warm"):
    """dates: list of datetimes (enquiries); srcs: matching sources."""
    srcs = srcs or ["Website"] * len(dates)
    fmt = "%d-%b-%Y %I:%M %p"
    hist = (f"Lead Source: {', '.join(srcs)}\nLead Date: {', '.join(d.strftime(fmt) for d in dates)}\n"
            f"Counselling By: {', '.join(['Asha'] * len(dates))}")
    return {C.C_FIRST: min(dates).strftime(fmt), C.C_LATEST: max(dates).strftime(fmt),
            C.C_INIT: min(dates).strftime(fmt), C.C_NAME: name, C.C_MOBILE: mobile,
            C.C_EMAIL: "", C.C_PLAT: ", ".join(dict.fromkeys(srcs)), C.C_NINT: str(len(dates)),
            C.C_VALID: valid, C.C_RELEV: relevant, C.C_WACONNECT: connect, C.C_REF: ref,
            C.C_REFNAME: "", C.C_COURSE: "Power BI", C.C_REMARKS: "note", C.C_STATUS: status,
            C.C_ADM: adm, C.C_BACKOUT: "", C.C_COUNSEL: "Asha", C.C_GMEET: "No",
            C.C_WALKSCH: "No", C.C_HIST: hist, C.C_LEADTYPE: "Student",
            "IsWalk-In": "", "IsWebsite": "Yes", "IsWhatsapp": "", "IsCall": ""}


T = date(2026, 10, 1)


def d(day, h=10, m=0):
    return datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)


BASE = [
    lead("A Fresh", "9876500001", [d(T - timedelta(days=3))]),
    lead("B Repeat", "+91 98765 00002", [d(T - timedelta(days=90)), d(T - timedelta(days=5))]),
    lead("C Edge start", "9876500003", [d(T - timedelta(days=29), 0, 0)]),        # 02-Sep 00:00 → in
    lead("D Before window", "9876500004", [d(T - timedelta(days=30), 23, 59)]),  # 01-Sep 23:59 → out
    lead("E Today late", "9876500005", [d(T, 23, 59)]),                           # today 23:59 → in
    lead("F Irrelevant", "9876500006", [d(T - timedelta(days=2))], relevant="No"),
    lead("G Not connected", "9876500007", [d(T - timedelta(days=2))], connect="No"),
    lead("H Invalid flag", "9876500008", [d(T - timedelta(days=2))], valid="No"),   # lead_rules → irrelevant
    lead("I Enrolled", "09876500009", [d(T - timedelta(days=2))]),
    lead("J Confirmed", "9876500010", [d(T - timedelta(days=2))], adm="Admission Confirmed"),
    lead("K Bad mobile", "5876500011", [d(T - timedelta(days=2))]),                 # not 6-9 start
    lead("L Short", "98765", [d(T - timedelta(days=2))]),
    lead("M Dup old", "9876500013", [d(T - timedelta(days=9))]),
    lead("M Dup new", "919876500013", [d(T - timedelta(days=1))]),                 # same phone, newer
    lead("O Not interested", "9876500015", [d(T - timedelta(days=2))], adm="Not Interested"),
    lead("P Lead status NI", "9876500016", [d(T - timedelta(days=2))], status="Not Interested"),
    lead("Q Enrolled (Perf list)", "9876500017", [d(T - timedelta(days=2))]),
]
ENROLLED_FU = {"9876500009"}                 # Follow-Up report's New Enroll tab
ENROLLED_PERF = {"9876500017"}               # Performance report's Student Admission Responses
ENROLLED = ENROLLED_FU | ENROLLED_PERF


def df_of(rows):
    return pd.DataFrame(rows).astype(str)


# =============================================================================
print("\n== 1. Window ==")
for n, want in ((30, ("02-Sep-2026", "01-Oct-2026")), (7, ("25-Sep-2026", "01-Oct-2026")),
                (1, ("01-Oct-2026", "01-Oct-2026")), (60, ("03-Aug-2026", "01-Oct-2026"))):
    s, e, sdt, edt = G.window_bounds(T, n)
    check(f"NUMBER_OF_DAYS = {n}: window", (f"{s:%d-%b-%Y}", f"{e:%d-%b-%Y}"), want)
    check(f"NUMBER_OF_DAYS = {n}: exactly {n} calendar day(s)", (e - s).days + 1, n)
s, e, sdt, edt = G.window_bounds(T, 30)
check("bounds are inclusive: start 00:00, end 23:59:59 (the report's day_bounds)",
      (sdt.time().isoformat(), edt.time().isoformat()[:8]), ("00:00:00", "23:59:59"))
check("default is NUMBER_OF_DAYS = 30", G.NUMBER_OF_DAYS, 30)
for bad in (0, -1):
    try:
        G.window_bounds(T, bad)
        check(f"NUMBER_OF_DAYS = {bad} rejected", False, True)
    except ValueError:
        check(f"NUMBER_OF_DAYS = {bad} rejected", True, True)

# =============================================================================
print("\n== 2. Eligibility (reused rules) ==")
aud = G.build_audience(df_of(BASE), T, ENROLLED, 30)
names = [r[2] for r in aud["rows"]]
check("final audience = in-window, relevant, connected, not enrolled, valid mobile, de-duplicated",
      sorted(names), sorted(["A Fresh", "B Repeat", "C Edge start", "E Today late", "M Dup new"]))
st = aud["stats"]
check("counts: evaluated / irrelevant / not interested / enrolled / confirmed / invalid / duplicates / final",
      (st["evaluated"], st["excluded_irrelevant"], st["excluded_not_interested"], st["excluded_enrolled"],
       st["excluded_admission_confirmed"], st["excluded_invalid_phone"], st["duplicates_removed"],
       st["final"]),
      (16, 3, 2, 2, 1, 2, 1, 5))
check("'Not Interested' excluded — by Admission Status AND by Lead Status (Follow-Up report's rule)",
      ("O Not interested" in names, "P Lead status NI" in names), (False, False))
check("enrolled on EITHER list excluded (New Enroll / Student Admission Responses)",
      ("I Enrolled" in names, "Q Enrolled (Perf list)" in names), (False, False))
check("out-of-window lead (01-Sep 23:59) not evaluated; 02-Sep 00:00 and today 23:59 included",
      ("D Before window" in names, "C Edge start" in names, "E Today late" in names), (False, True, True))
check("IsWhatsAppWebConnect = No excluded (report's is_relevant_lead)", "G Not connected" in names, False)
check("IsPhoneNumberValid = No excluded (common/lead_rules invalid-phone rule)", "H Invalid flag" in names, False)
check("enrolled matched whatever the phone format (09876500009 vs 9876500009)", "I Enrolled" in names, False)
check("duplicate phone (9876500013 / 919876500013) → one row, the most recent enquiry",
      [r[2] for r in aud["rows"] if r[-1] == 919876500013], ["M Dup new"])
check("phones are 91 + 10-digit mobile, as numbers, unique",
      all(isinstance(p, int) and len(str(p)) == 12 and str(p).startswith("91") for p in aud["phones"])
      and len(set(aud["phones"])) == len(aud["phones"]), True)
check("Full Details rows ↔ phones: same leads, same order", [r[-1] for r in aud["rows"]], aud["phones"])
check("Full Details columns (as specified, + Fresh/Repeat, Google Ads Phone)",
      G.FULL_COLUMNS[:16], ["First Enquiry", "Latest Enquiry", "Full Name", "Mobile Number",
                            "Platforms Used", "Interactions", "Relevant", "Is Referral",
                            "Course Interested", "Notes / Remarks", "Admission Status",
                            "Backout Reason", "Counselling By", "Google Meet Sch.", "Walk-in Sch.",
                            "Lead Journey (Enquiry → Latest)"])
b = next(r for r in aud["rows"] if r[2] == "B Repeat")
check("Repeat lead: Interactions = in-window enquiries (as the report), Journey = report's format",
      (b[5], b[16], b[15].count("\n") + 1, b[15] == C.format_journey(BASE[1][C.C_HIST])), (1, "Repeat", 2, True))
check("Platforms Used = report's platforms_in_sequence", b[4], C.platforms_in_sequence(BASE[1]))
check("newest enquiry first", names[0], "E Today late")
check("same input → same audience (deterministic)", G.build_audience(df_of(BASE), T, ENROLLED, 30)["phones"],
      aud["phones"])
check("NUMBER_OF_DAYS = 7 → only the last week's leads",
      sorted(r[2] for r in G.build_audience(df_of(BASE), T, ENROLLED, 7)["rows"]),
      sorted(["A Fresh", "B Repeat", "E Today late", "M Dup new"]))

# =============================================================================
print("\n== 3. Full refresh against the emulated production sheet ==")
OLD = [919000000101 + i for i in range(8)]                    # synthetic "current" audience


def setup(old=OLD):
    fs = FakeSheets()
    fs.books[G.PHONE_AUDIENCE_SHEET_ID] = production_book(old)
    return fs, FakeDrive(fs)


def run(fs, dr, rows=BASE, enrolled=ENROLLED, today=T, dry=False, master_fail=False):
    G.clpr.read_master_df = (lambda sheets: (_ for _ in ()).throw(RuntimeError("503 unavailable"))) \
        if master_fail else (lambda sheets: df_of(rows))
    fu, perf = (enrolled if isinstance(enrolled, tuple) else
                (set(enrolled) & ENROLLED_FU | (set(enrolled) - ENROLLED_PERF), set(enrolled) & ENROLLED_PERF))
    G.lfa.load_enrolled_phones = lambda sheets: set(fu)
    G.clpr.load_enrolled_mobiles = lambda sheets=None: set(perf)
    G.clpr.now_ist = lambda: datetime.combine(today, datetime.min.time()).replace(hour=21)
    return G.refresh(fs, fs, dr, today, dry_run=dry)


G.MAX_AUDIENCE_DROP_PCT = None
fs, dr = setup()
rc = run(fs, dr)
check("run 1: success", rc, G.EXIT_OK)
check("production: A1 'Mobile' kept, values = new audience, nothing else",
      (fs.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]["cells"][(0, 0)], prod_phones(fs)),
      ("Mobile", aud["phones"]))
t0 = fs.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]
check("production: same tab (gid 0, 'Sheet1'), only column A used, old leftover rows cleared",
      (t0["props"]["title"], t0["props"]["sheetId"], {c for _r, c in t0["cells"]},
       max(r for r, _c in t0["cells"])), ("Sheet1", 0, {0}, len(aud["phones"])))
check("production: numbers keep the '0' format", {f["numberFormat"]["pattern"] for (r, _c), f in t0["fmt"].items()
                                                if r <= len(aud["phones"])}, {"0"})
check("production updated in ONE batchUpdate (atomic)",
      [k for sid, k in fs.batches if sid == G.PHONE_AUDIENCE_SHEET_ID], [["updateCells", "updateCells"]])
check("Full Details created once in the remarketing folder, with the agreed name",
      (dr.created, dr.files_meta[0]["parent"], dr.files_meta[0]["name"]),
      (1, G.FULL_DETAILS_FOLDER_ID, "Google Ads Campaign Remarketing Leads Full Details"))
det = fs.books["details1"]
tabs = {t["props"]["title"]: t for t in det.tabs}
check("Full Details tabs", sorted(tabs), sorted([G.AUDIENCE_TAB, G.HISTORY_TAB]))
A = tabs[G.AUDIENCE_TAB]["cells"]
check("Full Details header row (row 3)", [A.get((2, c)) for c in range(len(G.FULL_COLUMNS))], G.FULL_COLUMNS)
det_phones = [A[(r, len(G.FULL_COLUMNS) - 1)] for r in range(3, 3 + len(aud["phones"]))]
check("Full Details holds EXACTLY the production audience (same phones, same order)", det_phones, prod_phones(fs))
check("Full Details Mobile Number reconciles with the audience after normalisation",
      [int("91" + G.consolidation.norm_phone(A[(r, 3)])) for r in range(3, 3 + len(aud["phones"]))], prod_phones(fs))
H = tabs[G.HISTORY_TAB]["cells"]
_hi = {H[(0, c)]: c for c in range(len(G.HISTORY_HEADER))}
check("Refresh History: header + one SUCCESS line",
      ([H[(0, c)] for c in range(len(G.HISTORY_HEADER))] == G.HISTORY_HEADER,
       H[(1, _hi["Result"])], H[(1, _hi["Final Audience"])], H[(1, _hi["Not Interested Excluded"])]),
      (True, "SUCCESS", len(aud["phones"]), 2))

print("\n-- run 2: next week (old leads leave, a new lead and a newly-enrolled lead) --")
T2 = T + timedelta(days=7)
rows2 = BASE + [lead("N New", "9876500014", [d(T2 - timedelta(days=1))])]
rc = run(fs, dr, rows=rows2, enrolled=ENROLLED | {"9876500001"}, today=T2)
aud2 = G.build_audience(df_of(rows2), T2, ENROLLED | {"9876500001"}, 30)
names2 = [r[2] for r in aud2["rows"]]
check("run 2: success, SAME production sheet & SAME Full Details sheet (no new files)",
      (rc, dr.created, list(fs.books)), (G.EXIT_OK, 1, [G.PHONE_AUDIENCE_SHEET_ID, "details1"]))
check("lead now outside the window removed (C Edge start: enquired 02-Sep)", "C Edge start" in names2, False)
check("newly eligible lead added (N New)", "N New" in names2, True)
check("newly enrolled lead removed (A Fresh)", "A Fresh" in names2, False)
check("production = Full Details after run 2", prod_phones(fs),
      [fs.books["details1"].tabs[0]["cells"][(r, len(G.FULL_COLUMNS) - 1)] for r in range(3, 3 + len(aud2["phones"]))])
check("Full Details has no rows left over from run 1",
      max(r for r, _c in fs.books["details1"].tabs[0]["cells"]), 2 + len(aud2["phones"]))
check("Refresh History: one line per run", max(r for r, _c in H) if False else
      max(r for r, _c in {t["props"]["title"]: t for t in fs.books["details1"].tabs}[G.HISTORY_TAB]["cells"]), 2)

print("\n-- grows beyond the sheet's rows → rows appended in the same atomic batch --")
fs3, dr3 = setup(old=[])
fs3.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]["props"]["gridProperties"]["rowCount"] = 3
check("audience larger than the grid: success", run(fs3, dr3), G.EXIT_OK)
check("… all numbers present", prod_phones(fs3), aud["phones"])

print("\n-- dry run --")
fs4, dr4 = setup()
check("dry run: success, writes nothing", (run(fs4, dr4, dry=True), prod_phones(fs4), dr4.created),
      (G.EXIT_OK, OLD, 0))

# =============================================================================
print("\n== 4. Failures never wipe the live audience ==")
fsx, drx = setup()
check("master unreadable → exit 3 (retryable), audience untouched",
      (run(fsx, drx, master_fail=True), prod_phones(fsx)), (G.EXIT_RETRYABLE, OLD))
check("New Enroll list unreadable/empty → exit 3, audience untouched",
      (run(fsx, drx, enrolled=(set(), ENROLLED_PERF)), prod_phones(fsx)), (G.EXIT_RETRYABLE, OLD))
check("Student Admission Responses unreadable/empty → exit 3, audience untouched",
      (run(fsx, drx, enrolled=(ENROLLED_FU, set())), prod_phones(fsx)), (G.EXIT_RETRYABLE, OLD))
check("audience would be empty → refused (exit 1), untouched",
      (run(fsx, drx, rows=[lead("F", "9876500006", [d(T)], relevant="No")]), prod_phones(fsx)),
      (G.EXIT_FAILED, OLD))
G.MAX_AUDIENCE_DROP_PCT = 60
check("audience would shrink by > 60% (8 → 1) → refused, untouched",
      (run(fsx, drx, rows=[BASE[0]]), prod_phones(fsx)), (G.EXIT_FAILED, OLD))
G.MAX_AUDIENCE_DROP_PCT = None
fsx.fail_batch.add(G.PHONE_AUDIENCE_SHEET_ID)
check("Google error while writing the audience → exit 3, previous audience still complete",
      (run(fsx, drx), prod_phones(fsx)), (G.EXIT_RETRYABLE, OLD))
fsx.fail_batch.clear()
fsy, dry_ = setup()
fsy.fail_batch.add("details1")
check("Full Details write fails → production audience NOT changed (exit 3)",
      (run(fsy, dry_), prod_phones(fsy)), (G.EXIT_RETRYABLE, OLD))
fsz, drz = setup()
fsz.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]["cells"][(0, 0)] = "Phone"
check("production structure changed (A1 not 'Mobile') → refused, untouched",
      (run(fsz, drz), fsz.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]["cells"][(0, 0)], len(prod_phones(fsz))),
      (G.EXIT_FAILED, "Phone", len(OLD)))
fsw, drw = setup()
fsw.books[G.PHONE_AUDIENCE_SHEET_ID].tabs[0]["cells"][(1, 1)] = "x"
check("data outside column A → refused, untouched", (run(fsw, drw), prod_phones(fsw)), (G.EXIT_FAILED, OLD))

# =============================================================================
print("\n== 5. Scheduler / run summary ==")
src = open(os.path.join(ROOT, "scripts", "run_layer3.py"), encoding="utf-8").read()
check("Sales Layer 3 runs the remarketing refresh after the two reports",
      (src.find("pyConsolidatedLeadPerformanceReport") < src.find("pyLeadFollowUpAnalysisReport")
       < src.find("pyGoogleAdsRemarketingAudience")), True)
import exec_summary                                                         # noqa: E402
import io                                                                   # noqa: E402
import contextlib                                                           # noqa: E402
fsl, drl = setup()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    run(fsl, drl)
out = buf.getvalue()
summ = exec_summary.summarize("pyGoogleAdsRemarketingAudience", out)
check("run-summary e-mail shows the audience KPIs", summ["kpis"],
      [("Audience (phones)", 5), ("Added", 5), ("Removed", 8), ("Google Ads sheet updated", "Yes")])
refused = exec_summary.summarize("pyGoogleAdsRemarketingAudience",
                                 "[audience] REFUSED — x. Last audience kept.")
check("… and flags a refused / failed run", (refused["note"], dict(refused["kpis"]).get("Google Ads sheet updated")),
      ("Audience NOT changed (last good audience kept) — see log", "No"))
check("log shows window, counts, both updates and reconciliation",
      all(x in out for x in ("Window: 02-Sep-2026 → 01-Oct-2026 (last 30 days", "Leads evaluated",
                             "Relevant leads", "Not Interested leads excluded: 2",
                             "Enrolled phones loaded: 2 unique  (New Enroll: 1, Student Admission Responses: 1)",
                             "Enrolled leads excluded", "Invalid/unusable phone numbers excluded",
                             "Duplicate phone numbers removed", "Final eligible audience: 5",
                             "[details] Full Details sheet updated", "[audience] production sheet updated",
                             "Reconciliation (after writing): OK")), True)

print("\nALL CHECKS PASSED" if not FAIL else f"\n{len(FAIL)} CHECK(S) FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
