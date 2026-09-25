"""
Regression tests for the header-aligned Google-Sheets write path
(app/sheets_gateway.py :: GspreadGateway.apply_save).

These guard the behaviour added when an "Alternative Mobile Number" column was
inserted at column F (before Email Address) in the live Data sheet:

  * writes align to the LIVE header row by NAME, so a column inserted / moved
    never misaligns any field,
  * a column the app does not manage (any header not in ACTIVE_COLUMNS) is
    PRESERVED on update and left blank on insert — never blanked/corrupted,
  * the prior version archived to InActive keeps full fidelity (all columns).

No network: a tiny in-memory fake stands in for a gspread Worksheet, and the
gateway's _connect() is neutralised so no credentials are needed.
"""
from app.sheets_gateway import GspreadGateway, SaveOp
from app import config


class _Cell:
    def __init__(self, row):
        self.row = row


class _FakeWS:
    """Just enough of a gspread Worksheet for apply_save()."""
    def __init__(self, title, grid):
        self.title = title
        self.grid = [list(r) for r in grid]        # grid[0] == header row

    def row_values(self, r):
        return list(self.grid[r - 1])

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def find(self, query, in_column=None):
        c = in_column - 1
        for i in range(1, len(self.grid)):
            if c < len(self.grid[i]) and str(self.grid[i][c]) == str(query):
                return _Cell(i + 1)
        return None

    def update(self, a1, values, value_input_option=None):
        row = int(a1[1:])
        vals = values[0]
        while len(self.grid) < row:
            self.grid.append([])
        r = self.grid[row - 1]
        while len(r) < len(vals):
            r.append("")
        for j, v in enumerate(vals):
            r[j] = v
        self.grid[row - 1] = r

    def append_row(self, vals, value_input_option=None):
        self.grid.append(list(vals))


# Live header order is deliberately UNLIKE config.ACTIVE_COLUMNS, and includes the
# new "Alternative Mobile Number" column at index 5 (column F), before Email.
_ACTIVE_HEADER = [
    "RecordTimeStamp", "Mobile Number", "Full Name", "Candidate Type",
    "Total Years of Experience", "Alternative Mobile Number", "Email Address",
    "Counselling By", "Admission Status",
]
_INACT_HEADER = ["RecordVersion", "ArchivedAt"] + _ACTIVE_HEADER


def _make_gateway(active_grid, inactive_grid):
    gw = GspreadGateway(config.Settings())
    gw._ss = object()
    gw._active_ws = _FakeWS("IntelliBI Lead Information Active", active_grid)
    gw._inactive_ws = _FakeWS("IntelliBI Lead Information InActive", inactive_grid)
    gw._connect = lambda: None          # already "connected"
    return gw


def _managed_record(**overrides):
    rec = {c: "" for c in config.ACTIVE_COLUMNS}
    rec.update(overrides)
    return rec


def test_update_preserves_unmanaged_column_and_stays_aligned():
    existing = ["01-Sep-2026 10:00:00", "9876543210", "Old Name", "Fresher", "",
                "9000000001", "old@x.com", "Harish Rathod", "Follow-Up"]
    gw = _make_gateway([_ACTIVE_HEADER, existing], [_INACT_HEADER])

    op = SaveOp(
        mobile="9876543210",
        new_active=_managed_record(
            **{"RecordTimeStamp": "25-Sep-2026 12:00:00",
               "Mobile Number": "9876543210", "Full Name": "New Name",
               "Email Address": "new@x.com", "Candidate Type": "Fresher",
               "Counselling By": "Harish Rathod", "Admission Status": "Interested"}),
        archive={"Mobile Number": "9876543210"}, version=1)
    gw.apply_save(op)

    row = dict(zip(_ACTIVE_HEADER, gw._active_ws.grid[1]))
    assert row["Full Name"] == "New Name"                    # managed field updated
    assert row["Email Address"] == "new@x.com"               # NOT misaligned by col F
    assert row["Alternative Mobile Number"] == "9000000001"  # unmanaged col preserved


def test_update_archives_prior_version_with_full_fidelity():
    existing = ["01-Sep-2026 10:00:00", "9876543210", "Old Name", "Fresher", "",
                "9000000001", "old@x.com", "Harish Rathod", "Follow-Up"]
    gw = _make_gateway([_ACTIVE_HEADER, existing], [_INACT_HEADER])

    gw.apply_save(SaveOp(
        mobile="9876543210",
        new_active=_managed_record(**{"Mobile Number": "9876543210",
                                      "Full Name": "New Name"}),
        archive={"Mobile Number": "9876543210"}, version=3))

    arch = dict(zip(_INACT_HEADER, gw._inactive_ws.grid[1]))
    assert arch["RecordVersion"] == "3"
    assert arch["Full Name"] == "Old Name"
    assert arch["Email Address"] == "old@x.com"
    assert arch["Alternative Mobile Number"] == "9000000001"  # history keeps it


def test_insert_leaves_unmanaged_column_blank_and_aligned():
    gw = _make_gateway([_ACTIVE_HEADER], [_INACT_HEADER])
    gw.apply_save(SaveOp(
        mobile="9811111111",
        new_active=_managed_record(**{"Mobile Number": "9811111111",
                                      "Full Name": "Fresh Lead",
                                      "Email Address": "fresh@x.com"}),
        archive=None, version=0))

    row = dict(zip(_ACTIVE_HEADER, gw._active_ws.grid[-1]))
    assert row["Mobile Number"] == "9811111111"
    assert row["Email Address"] == "fresh@x.com"
    assert row["Alternative Mobile Number"] == ""            # unmanaged -> blank on insert
