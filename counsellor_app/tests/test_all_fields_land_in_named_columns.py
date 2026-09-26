"""
End-to-end column-mapping proof against the LIVE sheet layout (28 columns,
"Alternative Mobile Number" at column D, as read from the production sheet on
26-Sep-2026): every one of the 28 fields must land under the column whose
HEADER matches — on insert, on update, and in the InActive archive — and the
result must be identical when the sheet's columns are shuffled, because nothing
in the write path may depend on position.
"""
import os, tempfile, random
from app.config import Settings, ACTIVE_COLUMNS, AUDIT_COLUMNS
from app.sheets_gateway import GspreadGateway, SaveOp
from app.domain import build_record

LIVE_ACTIVE_HEADER = [
    "RecordTimeStamp", "Mobile Number", "Full Name", "Alternative Mobile Number",
    "Email Address", "Candidate Type", "Total Years of Experience",
    "Current Domain / Technology", "IsGoogleMeetSchedule", "Course Interested In",
    "IsGoogleMeetScheduleDate", "Career Goal", "IsWalkInSchedule", "Current Company Name",
    "IsWalkInScheduleDate", "Current City", "Admission Plan Time", "Current Area / Locality",
    "Next Follow-Up Date", "Highest Qualification", "Counsellor Notes",
    "Graduation / Passing Year", "Counselling By", "Is Referral", "Admission Status",
    "Referrer's Name", "BackOutReason", "Follow-Up Type",
]
LIVE_INACTIVE_HEADER = ["RecordVersion", "ArchivedAt"] + LIVE_ACTIVE_HEADER
assert sorted(LIVE_ACTIVE_HEADER) == sorted(ACTIVE_COLUMNS), "app schema must cover the live header"


class _Cell:
    def __init__(self, row): self.row = row


class _FakeWS:
    def __init__(self, grid): self.grid = [list(r) for r in grid]
    def row_values(self, r): return list(self.grid[r - 1]) if r <= len(self.grid) else []
    def get_all_values(self): return [list(r) for r in self.grid]
    def find(self, q, in_column=None):
        c = in_column - 1
        for i in range(1, len(self.grid)):
            if c < len(self.grid[i]) and str(self.grid[i][c]) == str(q): return _Cell(i + 1)
        return None
    def update(self, a1, values, value_input_option=None):
        row = int(a1[1:]); vals = values[0]
        while len(self.grid) < row: self.grid.append([])
        r = self.grid[row - 1]
        while len(r) < len(vals): r.append("")
        for j, v in enumerate(vals): r[j] = v
    def append_row(self, vals, value_input_option=None): self.grid.append(list(vals))


def _gateway(active_header, inactive_header, active_rows=()):
    gw = GspreadGateway(Settings())
    gw._ss = object(); gw._connect = lambda: None
    gw._active_ws = _FakeWS([active_header, *active_rows])
    gw._inactive_ws = _FakeWS([inactive_header])
    return gw


def _distinct_record(mobile="9561851313"):
    """A record with a unique, recognisable value in EVERY field (like the
    screenshot's test save, but for all 28 columns)."""
    fields = {c: f"<<{c}>>" for c in ACTIVE_COLUMNS
              if c not in ("Mobile Number", "RecordTimeStamp")}
    fields["Email Address"] = "Test@gmail.com"
    fields["Alternative Mobile Number"] = "9000000009"
    fields["IsGoogleMeetSchedule"] = "Yes"
    fields["IsGoogleMeetScheduleDate"] = "27-Sep-2026"
    fields["IsWalkInSchedule"] = "No"
    fields["Candidate Type"] = "Career Break"
    fields["Admission Status"] = "Follow-up Pending"
    rec = build_record(fields, mobile, counselling_by="ArshKhan Pathan")
    return rec


def _check_row(header, row, rec):
    got = dict(zip(header, row + [""] * (len(header) - len(row))))
    for col in ACTIVE_COLUMNS:
        assert got[col] == rec[col], f"'{col}' should be {rec[col]!r} but column holds {got[col]!r}"


def test_insert_puts_all_28_values_under_their_own_headers():
    gw = _gateway(LIVE_ACTIVE_HEADER, LIVE_INACTIVE_HEADER)
    rec = _distinct_record()
    gw.apply_save(SaveOp(mobile=rec["Mobile Number"], new_active=rec, archive=None, version=0))
    row = gw._active_ws.grid[-1]
    _check_row(LIVE_ACTIVE_HEADER, row, rec)
    # the two the screenshot showed going wrong, spelled out:
    assert row[LIVE_ACTIVE_HEADER.index("Email Address")] == "Test@gmail.com"
    assert row[LIVE_ACTIVE_HEADER.index("Alternative Mobile Number")] == "9000000009"


def test_update_puts_all_28_values_under_their_own_headers_and_archives_prior():
    prior = _distinct_record()
    prior_row = [prior[h] for h in LIVE_ACTIVE_HEADER]
    gw = _gateway(LIVE_ACTIVE_HEADER, LIVE_INACTIVE_HEADER, [prior_row])
    new = dict(prior); new["Email Address"] = "new@gmail.com"; new["Counsellor Notes"] = "updated"
    new["Alternative Mobile Number"] = "9000000010"
    gw.apply_save(SaveOp(mobile=new["Mobile Number"], new_active=new,
                         archive=prior, version=1))
    _check_row(LIVE_ACTIVE_HEADER, gw._active_ws.grid[1], new)
    # archived prior version, aligned to the InActive header (audit cols first)
    arch = dict(zip(LIVE_INACTIVE_HEADER, gw._inactive_ws.grid[1]))
    assert arch["RecordVersion"] == "1" and arch["ArchivedAt"]
    for col in ACTIVE_COLUMNS:
        assert arch[col] == prior[col], f"archived '{col}' wrong"


def test_mapping_is_independent_of_column_order():
    """Shuffle the sheet's columns: values must still land under their headers."""
    shuffled = LIVE_ACTIVE_HEADER[:]; random.Random(7).shuffle(shuffled)
    gw = _gateway(shuffled, ["RecordVersion", "ArchivedAt"] + shuffled)
    rec = _distinct_record()
    gw.apply_save(SaveOp(mobile=rec["Mobile Number"], new_active=rec, archive=None, version=0))
    _check_row(shuffled, gw._active_ws.grid[-1], rec)


def test_empty_inactive_tab_gets_a_header_before_first_archive():
    prior = _distinct_record()
    gw = _gateway(LIVE_ACTIVE_HEADER, [], [[prior[h] for h in LIVE_ACTIVE_HEADER]])
    gw._inactive_ws = _FakeWS([])                     # completely empty tab
    new = dict(prior); new["Full Name"] = "Changed"
    gw.apply_save(SaveOp(mobile=new["Mobile Number"], new_active=new, archive=prior, version=1))
    assert gw._inactive_ws.grid[0] == AUDIT_COLUMNS + ACTIVE_COLUMNS      # header written first
    arch = dict(zip(gw._inactive_ws.grid[0], gw._inactive_ws.grid[1]))
    assert arch["Full Name"] == prior["Full Name"] and arch["RecordVersion"] == "1"
