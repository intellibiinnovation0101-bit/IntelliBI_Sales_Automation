"""
================================================================================
  IntelliBI — shared lead-quality rules  (common/lead_rules.py)
  ------------------------------------------------------------------------------
  One definition of the record-quality rules that more than one script applies,
  so the consolidation (which WRITES the flags into the master sheet) and the
  reports (which READ them) can never disagree.

  Rule: invalid phone number  =>  lead is irrelevant
      IsPhoneNumberValid = No   ->   IsLeadRelevant = No
  This is an ADDITIONAL condition on top of the existing relevance logic
  (remark / Admission Status / Lead Status based). It only ever turns a lead
  Irrelevant; it never makes an Irrelevant lead Relevant, and a valid or blank
  IsPhoneNumberValid leaves IsLeadRelevant exactly as the other rules set it.

  Flag values are compared after normalisation: Unicode NFKC, invisible /
  zero-width characters removed, whitespace collapsed and trimmed, case-folded
  — so "No", "no", " NO ", "No​" all count as No. Blank / missing values
  are NOT treated as No.
================================================================================
"""
from __future__ import annotations

import re
import unicodedata

PHONE_VALID_FIELD = "IsPhoneNumberValid"
LEAD_RELEVANT_FIELD = "IsLeadRelevant"

_INVISIBLE_RE = re.compile(r"[​-‏‪-‮⁠-⁤﻿­]")
_WS_RE = re.compile(r"\s+")


def norm_flag(value) -> str:
    """Normalised, case-folded text of a Yes/No flag ('' for None/NaN/blank)."""
    if value is None:
        return ""
    s = str(value)
    if s.strip().lower() in ("nan", "none", "null"):
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _INVISIBLE_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return s.casefold()


def is_flag_no(value) -> bool:
    """True only when the flag explicitly reads No (blank is NOT No)."""
    return norm_flag(value) == "no"


def is_phone_invalid(phone_valid_flag) -> bool:
    """True when IsPhoneNumberValid = No (robust to case / spaces / invisibles)."""
    return is_flag_no(phone_valid_flag)


def apply_invalid_phone_irrelevance(df, phone_col: str = PHONE_VALID_FIELD,
                                    relevant_col: str = LEAD_RELEVANT_FIELD):
    """DataFrame form of the rule, for readers of the master sheet: where
    IsPhoneNumberValid = No, IsLeadRelevant is set to "No". Returns
    (df, n_changed). Works in place on a copy-safe basis; a frame without both
    columns is returned unchanged."""
    if df is None or getattr(df, "empty", True):
        return df, 0
    if phone_col not in df.columns or relevant_col not in df.columns:
        return df, 0
    invalid = df[phone_col].map(is_phone_invalid)
    change = invalid & ~df[relevant_col].map(is_flag_no)
    n = int(change.sum())
    if n:
        df.loc[change, relevant_col] = "No"
    return df, n
