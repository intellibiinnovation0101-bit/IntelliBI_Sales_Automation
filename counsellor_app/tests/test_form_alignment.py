"""
Alignment with the latest LeadSubmissionForm.gs + Google Sheet form:

  * "Alternative Mobile Number" is a first-class field (schema, UI fields,
    save round-trip, history),
  * Search finds a lead by its Alternative Mobile Number exactly like the form's
    TICK TO SEARCH (primary first; alt fallback; the record returned carries the
    lead's REAL primary number so Save keys on the right lead),
  * dropdown options are kept in step with the sheet (base list + values in use,
    sheet spelling wins, configured counsellors included),
  * the existing validations and Counselling By behaviour are unchanged.
"""
import os, tempfile
from app.config import Settings, Counsellor, ACTIVE_COLUMNS, EDITABLE_FIELDS, ALT_MOBILE_COL
from app.store import Store
from app.fake_sheets import FakeGateway
from app.domain import build_record, validate_submission
from app.server import build_select_options, SELECT_FIELDS_BASE


def _settings(td):
    s = Settings()
    s.db_path = os.path.join(td, "store.db")
    s.counsellors = [
        Counsellor(email="a@x.in", name="Akash", counselling_by="Akash Sahu"),
        Counsellor(email="r@x.in", name="Rajneesh", counselling_by="Rajneesh Pandey"),
    ]
    return s


def _store(td, recs):
    st = Store(_settings(td), FakeGateway(active=recs))
    st.bootstrap()
    return st


# ---------------------------------------------------------------- schema
def test_alt_mobile_is_in_schema_right_after_full_name_and_editable():
    i = ACTIVE_COLUMNS.index("Full Name")
    assert ACTIVE_COLUMNS[i + 1] == ALT_MOBILE_COL == "Alternative Mobile Number"
    assert ACTIVE_COLUMNS[i + 2] == "Email Address"       # live sheet order (col D)
    assert ALT_MOBILE_COL in EDITABLE_FIELDS
    assert len(ACTIVE_COLUMNS) == 28


# ---------------------------------------------------------------- search
def test_search_by_alternative_number_returns_lead_with_real_primary():
    with tempfile.TemporaryDirectory() as td:
        st = _store(td, [
            build_record({"Full Name": "Asha", ALT_MOBILE_COL: ""}, "9876543210"),
            build_record({"Full Name": "Ravi", ALT_MOBILE_COL: "+91 90000-00001"}, "9812345678"),
        ])
        # primary still wins and is unchanged
        assert st.get("9876543210")["Full Name"] == "Asha"
        # alternate number, typed with formatting -> Ravi, with his REAL primary
        rec = st.get("9000000001")
        assert rec and rec["Full Name"] == "Ravi"
        assert rec["Mobile Number"] == "9812345678"
        # +91 prefix on the typed number is fine too
        assert st.get("+919000000001")["Full Name"] == "Ravi"
        # a number that is nobody's primary or alternate -> not found
        assert st.get("9999999999") is None
        # quick-search matches a fragment of the alternate number as well
        hits = st.search("00000001")
        assert [h["Full Name"] for h in hits] == ["Ravi"]
        st.close()


def test_history_resolves_via_alternative_number():
    with tempfile.TemporaryDirectory() as td:
        st = _store(td, [build_record({"Full Name": "Ravi", ALT_MOBILE_COL: "9000000001"},
                                      "9812345678")])
        # the UI always submits every editable field (like the form saves the whole
        # form), so the alternate number travels with the edit
        ok, msg, rec = st.save({"Full Name": "Ravi K", ALT_MOBILE_COL: "9000000001",
                                "Candidate Type": "Career Break"},
                               "9812345678", counselling_by="Akash Sahu")
        assert ok, msg
        assert len(st.history("9812345678")) == 1          # by primary
        assert len(st.history("9000000001")) == 1          # by alternate -> same lead
        st.close()


# ---------------------------------------------------------------- save
def test_save_round_trips_alternative_number_and_keeps_validations():
    with tempfile.TemporaryDirectory() as td:
        st = _store(td, [])
        # validations unchanged: Candidate Type required unless status exempt
        ok, msg, _ = st.save({"Admission Status": "Follow-up Pending"}, "9811111111",
                             counselling_by="Akash Sahu")
        assert not ok and "Candidate Type" in msg
        ok, msg, _ = st.save({"IsGoogleMeetSchedule": "Yes", "Candidate Type": "Career Break"},
                             "9811111111", counselling_by="Akash Sahu")
        assert not ok and "Google Meet" in msg
        # a valid save carries the alternate number through, and Counselling By
        # defaults to the logged-in counsellor when left blank
        ok, msg, rec = st.save({"Candidate Type": "Career Break",
                                ALT_MOBILE_COL: "0 98000 00002",
                                "Admission Status": "Follow-up Pending"},
                               "9811111111", counselling_by="Akash Sahu")
        assert ok, msg
        assert rec[ALT_MOBILE_COL] == "0 98000 00002"        # stored as entered (like the form)
        assert rec["Counselling By"] == "Akash Sahu"
        assert st.get("9800000002")["Mobile Number"] == "9811111111"   # searchable at once
        st.close()


# ---------------------------------------------------------------- dropdowns
def test_select_options_follow_the_sheet():
    with tempfile.TemporaryDirectory() as td:
        st = _store(td, [
            build_record({"Candidate Type": "Fresher -  Passed Out",       # sheet's exact text
                          "Admission Status": "Unable to Connect",        # sheet's case
                          "Follow-Up Type": "Second Follow-Up",           # not in base list
                          "Counselling By": "Harish Rathod"}, "9876543210"),
        ])
        opts = build_select_options(st, _settings(td))
        # every dropdown field on the form is offered as a dropdown
        for f in ("Candidate Type", "Total Years of Experience", "Course Interested In",
                  "Career Goal", "Admission Plan Time", "Highest Qualification",
                  "Admission Status", "BackOutReason", "Follow-Up Type", "Counselling By"):
            assert f in opts and opts[f][0] == ""
        # sheet spelling/case wins over the base entry (no duplicates)
        ct = opts["Candidate Type"]
        assert "Fresher -  Passed Out" in ct and "Fresher - Passed Out" not in ct
        st_ = opts["Admission Status"]
        assert "Unable to Connect" in st_ and "Unable To Connect" not in st_
        # a value in use that the base list doesn't know is added
        assert "Second Follow-Up" in opts["Follow-Up Type"]
        assert "Initial Follow-Up" in opts["Follow-Up Type"]
        # Counselling By = values in the sheet + configured counsellors
        assert {"Harish Rathod", "Akash Sahu", "Rajneesh Pandey"} <= set(opts["Counselling By"])
        # old, non-form options are gone
        assert "Admitted" not in st_ and "WhatsApp" not in opts["Follow-Up Type"]
        st.close()
