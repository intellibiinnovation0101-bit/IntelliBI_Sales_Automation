"""Business-rule tests — these guarantee app-saved leads match form-saved ones."""
from app import domain as d
from app.config import ACTIVE_COLUMNS, MOBILE_COL, TIMESTAMP_COL


def test_normalize_mobile_variants():
    assert d.normalize_mobile("9876543210") == "9876543210"
    assert d.normalize_mobile("+91 98765 43210") == "9876543210"
    assert d.normalize_mobile("919876543210") == "9876543210"
    assert d.normalize_mobile("09876543210") == "9876543210"
    assert d.normalize_mobile("91-98765-43210") == "9876543210"


def test_valid_indian_mobile():
    assert d.is_valid_indian_mobile("9876543210")
    assert d.is_valid_indian_mobile("+919876543210")
    assert not d.is_valid_indian_mobile("1234567890")   # must start 6-9
    assert not d.is_valid_indian_mobile("98765")         # too short


def test_build_record_is_full_schema_and_normalises():
    rec = d.build_record({"Full Name": "  Asha  ", "Admission Status": "Interested",
                          "Candidate Type": "Fresher"},
                         "+91 98765 43210", counselling_by="Meera")
    assert set(rec.keys()) == set(ACTIVE_COLUMNS)          # all 27 columns present
    assert rec[MOBILE_COL] == "9876543210"                 # normalised
    assert rec["Counselling By"] == "Meera"                # default applied
    assert rec[TIMESTAMP_COL]                               # stamped


def test_date_field_canonicalised():
    assert d.format_date_field("2026-09-26") == "26-Sep-2026"
    assert d.format_date_field("26-Sep-2026") == "26-Sep-2026"
    assert d.format_date_field("09/26/2026") == "26-Sep-2026"
    # unparseable stays as typed (never silently dropped)
    assert d.format_date_field("next week") == "next week"


def test_validate_candidate_type_rule():
    ok, _ = d.validate_submission(d.build_record(
        {"Admission Status": "Interested"}, "9876543210"))
    assert not ok      # candidate type required
    ok, _ = d.validate_submission(d.build_record(
        {"Admission Status": "Irrelevant"}, "9876543210"))
    assert ok          # exempt status
    ok, _ = d.validate_submission(d.build_record(
        {"Admission Status": "Interested", "Candidate Type": "Fresher"}, "9876543210"))
    assert ok


def test_validate_schedule_date_rules():
    ok, msg = d.validate_submission(d.build_record(
        {"Admission Status": "Irrelevant", "IsGoogleMeetSchedule": "Yes"}, "9876543210"))
    assert not ok and "Google Meet" in msg
    ok, _ = d.validate_submission(d.build_record(
        {"Admission Status": "Irrelevant", "IsGoogleMeetSchedule": "Yes",
         "IsGoogleMeetScheduleDate": "26-Sep-2026"}, "9876543210"))
    assert ok


def test_row_roundtrip_matches_column_order():
    rec = d.build_record({"Full Name": "X"}, "9876543210")
    row = d.row_from_record(rec, ACTIVE_COLUMNS)
    assert len(row) == len(ACTIVE_COLUMNS)
    back = d.record_from_row(row, ACTIVE_COLUMNS)
    assert back[MOBILE_COL] == "9876543210"
