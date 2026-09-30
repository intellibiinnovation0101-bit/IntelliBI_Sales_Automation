"""
Verification of the "invalid phone => irrelevant" lead rule
(common/lead_rules.py), used by pyConsolidateLeadsLoad.py (writes the flags into
the master) and pyConsolidatedLeadPerformanceReport.py (reads them).

Run from the project root (no Google access needed):
    python sales_validation\\verify_invalid_phone_irrelevance.py [master.csv]

With a CSV export of the consolidated master as argument it also prints how many
leads the rule turns Irrelevant and confirms no Irrelevant lead becomes Relevant.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))

import pandas as pd                      # noqa: E402
import lead_rules as lr                  # noqa: E402

# 1. robust comparison
for v in ("No", "no", " NO ", "No​", " No ", "nO"):
    assert lr.is_phone_invalid(v), repr(v)
for v in ("Yes", "", None, "nan", "None", "  ", "N/A", "Not sure"):
    assert not lr.is_phone_invalid(v), repr(v)
print("[pass] IsPhoneNumberValid = No detected regardless of case / spaces / invisibles; blank is not No")

# 2. DataFrame rule: only Yes -> No, never No -> Yes, other columns untouched
df = pd.DataFrame({
    "Mobile Number":      ["9876543210", "12345", "0000000000", "9123456780", "555"],
    "IsPhoneNumberValid": ["Yes",        " no ",  "NO",         "",           "No"],
    "IsLeadRelevant":     ["Yes",        "Yes",   "No",         "Yes",        "yes"],
    "Remarks":            ["",           "",      "irrelevant", "",           ""],
})
before = df.copy()
out, n = lr.apply_invalid_phone_irrelevance(df.copy())
assert list(out["IsLeadRelevant"]) == ["Yes", "No", "No", "Yes", "No"], list(out["IsLeadRelevant"])
assert n == 2, n
assert out.drop(columns=["IsLeadRelevant"]).equals(before.drop(columns=["IsLeadRelevant"]))
_df, n0 = lr.apply_invalid_phone_irrelevance(pd.DataFrame({"x": [1]}))
assert n0 == 0                                            # frame without the columns: unchanged
print("[pass] invalid-phone leads become Irrelevant; valid / blank ones and every other column unchanged")

# 3. optional: real master export
if len(sys.argv) > 1:
    m = pd.read_csv(sys.argv[1], dtype=str, keep_default_na=False)
    rel_before = m["IsLeadRelevant"].map(lr.norm_flag)
    m2, n = lr.apply_invalid_phone_irrelevance(m.copy())
    rel_after = m2["IsLeadRelevant"].map(lr.norm_flag)
    assert not ((rel_before == "no") & (rel_after == "yes")).any()
    assert not ((m2["IsPhoneNumberValid"].map(lr.is_phone_invalid)) & (rel_after == "yes")).any()
    print(f"[pass] master: {len(m)} leads | IsLeadRelevant Yes {int((rel_before=='yes').sum())} -> "
          f"{int((rel_after=='yes').sum())}, No {int((rel_before=='no').sum())} -> "
          f"{int((rel_after=='no').sum())} | {n} invalid-phone lead(s) turned Irrelevant")

print("ALL CHECKS PASSED")
