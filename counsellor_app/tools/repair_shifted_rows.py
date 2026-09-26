#!/usr/bin/env python3
"""
repair_shifted_rows.py — put back rows that an OLD counsellor-app build wrote
one column to the left.

WHAT HAPPENED
    "Alternative Mobile Number" was inserted into the Data sheet (column D on the
    Active tab, column F on the InActive tab). The counsellor-app .exe built
    before 25-Sep-2026 10:26 did not know that column and wrote its 27 values by
    POSITION, so on every row it saved, everything from "Email Address" onward
    landed one column to the LEFT (Email in the Alternative-Mobile column,
    Candidate Type in the Email column, ... Counselling By in "Graduation /
    Passing Year", and the real "Follow-Up Type" column left untouched).

HOW A SHIFTED ROW IS RECOGNISED (both conditions must hold — no false positives)
    * "Graduation / Passing Year" contains a counsellor NAME (a year column can
      never legitimately hold one), AND
    * "Counselling By" holds Yes / No / blank (i.e. the Is-Referral value).

WHAT THE REPAIR DOES
    For each shifted row: keep the columns before "Alternative Mobile Number",
    set "Alternative Mobile Number" to blank (the old build had no value for it),
    and move every later value one column to the RIGHT. Nothing else is touched.

USAGE (run on a PC that has Python + the service-account key, e.g. your dell):
    cd counsellor_app
    .venv\\Scripts\\activate            (any env with gspread + google-auth + pyyaml)
    python tools\\repair_shifted_rows.py                 <- DRY RUN: lists the rows, writes nothing
    python tools\\repair_shifted_rows.py --apply         <- fixes them (backs up originals first)

    Options: --tab active|inactive|both (default both)
             --names "Name A,Name B"   extra counsellor names to recognise
Backups: tools\\repair_backup_<tab>_<timestamp>.csv (the ORIGINAL rows, with row numbers).
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # counsellor_app/
sys.path.insert(0, ROOT)

ALT_COL   = "Alternative Mobile Number"
GRAD_COL  = "Graduation / Passing Year"
CBY_COL   = "Counselling By"
MOBILE    = "Mobile Number"
NAME_COL  = "Full Name"
# Names seen on the live sheet; the sheet's own Counselling By column is added at runtime.
FALLBACK_NAMES = ["IntelliBI Escalation", "Harish Rathod", "ArshKhan Pathan",
                  "Akash Sahu", "Rajneesh Pandey"]
YES_NO_BLANK = {"", "yes", "no"}


def norm(s) -> str:
    return " ".join(str(s or "").split()).lower()


def known_counsellor_names(header: List[str], rows: List[List[str]],
                           extra: List[str]) -> set:
    """Distinct real names from the sheet's Counselling By column (+ fallbacks)."""
    names = {norm(n) for n in FALLBACK_NAMES + list(extra)}
    if CBY_COL in header:
        ci = header.index(CBY_COL)
        for r in rows:
            v = r[ci] if ci < len(r) else ""
            n = norm(v)
            if n and n not in YES_NO_BLANK and not re.fullmatch(r"[\d\s/.-]+", n):
                names.add(n)
    return names


def is_shifted(header: List[str], row: List[str], names: set) -> bool:
    gi, ci = header.index(GRAD_COL), header.index(CBY_COL)
    grad = norm(row[gi] if gi < len(row) else "")
    cby  = norm(row[ci] if ci < len(row) else "")
    return (grad in names) and (cby in YES_NO_BLANK)


def repair_row(header: List[str], row: List[str]) -> List[str]:
    """Shift everything from the Alternative-Mobile column one place to the right."""
    base = header.index(ALT_COL)
    n = len(header)
    row = list(row) + [""] * (n - len(row))            # pad short rows
    return row[:base] + [""] + row[base:n - 1]


def col_letter(idx0: int) -> str:
    s, i = "", idx0 + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def scan(header: List[str], rows: List[List[str]], names: set) -> List[Tuple[int, List[str]]]:
    """(1-based sheet row number, original row) for every shifted row."""
    out = []
    for i, r in enumerate(rows, start=2):               # data starts at row 2
        if is_shifted(header, r, names):
            out.append((i, r))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the fixes (default is a dry run)")
    ap.add_argument("--tab", choices=["active", "inactive", "both"], default="both")
    ap.add_argument("--names", default="", help="extra counsellor names, comma-separated")
    args = ap.parse_args(argv)

    from app.config import load_settings                # sheet id + key path from config.yaml
    import gspread
    from google.oauth2.service_account import Credentials

    s = load_settings()
    creds = Credentials.from_service_account_file(
        s.service_account_file, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    ss = gspread.authorize(creds).open_by_key(s.data_sheet_id)
    extra = [x.strip() for x in args.names.split(",") if x.strip()]

    tabs = []
    if args.tab in ("active", "both"):
        tabs.append(("active", [s.active_tab] + list(s.active_tab_aliases)))
    if args.tab in ("inactive", "both"):
        tabs.append(("inactive", [s.inactive_tab]))

    grand = 0
    for label, titles in tabs:
        ws = next((w for w in ss.worksheets() if w.title in titles), None)
        if ws is None:
            print(f"[{label}] tab not found ({titles}) - skipped"); continue
        values = ws.get_all_values()
        if not values:
            print(f"[{label}] empty - skipped"); continue
        header = [str(h).strip() for h in values[0]]
        for need in (ALT_COL, GRAD_COL, CBY_COL):
            if need not in header:
                print(f"[{label}] header has no '{need}' column - nothing to do here"); break
        else:
            rows = values[1:]
            names = known_counsellor_names(header, rows, extra)
            hits = scan(header, rows, names)
            print(f"\n[{label}] '{ws.title}': {len(rows)} data rows, {len(hits)} shifted row(s) found.")
            mi = header.index(MOBILE); ni = header.index(NAME_COL); gi = header.index(GRAD_COL)
            for rn, r in hits[:200]:
                print(f"   row {rn:>5}  mobile={r[mi] if mi < len(r) else '':<12} "
                      f"name={r[ni] if ni < len(r) else '':<22} "
                      f"(found '{r[gi] if gi < len(r) else ''}' in '{GRAD_COL}')")
            if len(hits) > 200:
                print(f"   ... and {len(hits) - 200} more")
            grand += len(hits)
            if not hits or not args.apply:
                continue

            # --- apply: back up originals, then write the repaired rows -----------
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bpath = os.path.join(HERE, f"repair_backup_{label}_{stamp}.csv")
            with open(bpath, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh); w.writerow(["sheet_row"] + header)
                for rn, r in hits:
                    w.writerow([rn] + list(r) + [""] * (len(header) - len(r)))
            print(f"   backup of the ORIGINAL rows written to {bpath}")

            last = col_letter(len(header) - 1)
            payload = [{"range": f"A{rn}:{last}{rn}", "values": [repair_row(header, r)]}
                       for rn, r in hits]
            for i in range(0, len(payload), 200):        # batches keep API calls small
                ws.batch_update(payload[i:i + 200], value_input_option="USER_ENTERED")
            print(f"   FIXED {len(hits)} row(s) on '{ws.title}'.")

    print()
    if grand == 0:
        print("Nothing to repair.")
    elif not args.apply:
        print(f"DRY RUN: {grand} row(s) would be repaired. Re-run with --apply to fix them.")
    else:
        print(f"Done: {grand} row(s) repaired. Re-run without --apply to confirm it now reports 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
