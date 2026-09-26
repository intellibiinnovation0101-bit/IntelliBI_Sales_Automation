"""
The ONLY component that talks to Google Sheets. Everything else goes through this
interface, so storage is swappable (Sheets today, a DB later) without touching
counsellors or the UI.

A "save operation" carries the new Active record and (on update) the prior
version to archive, so applying it to the sheet reproduces the .gs upsert:
    - append the prior version to the InActive tab (RecordVersion, ArchivedAt),
    - overwrite the mobile's Active row (or append if new).

HEADER-ALIGNED WRITES (order-independent, insertion-safe)
--------------------------------------------------------
Both reading AND writing map to the sheet's LIVE header row by column NAME, never
by a fixed position. This means the physical column order can change — a column
inserted, moved or renamed-elsewhere — without ever misaligning a write. Two
consequences worth stating:
  * A column the app does not manage (i.e. any header not in ACTIVE_COLUMNS, e.g.
    the new "Alternative Mobile Number") is PRESERVED on update and left blank on
    insert — the app never blanks or corrupts a column it doesn't own.
  * The prior version archived to InActive is taken from the REAL current Active
    row (all its columns), so history keeps full fidelity even for columns the
    app doesn't manage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import config
from .config import (
    ACTIVE_COLUMNS, INACTIVE_COLUMNS, AUDIT_COLUMNS, MOBILE_COL, Settings,
)
from .domain import row_from_record, record_from_row, normalize_mobile, now_timestamp, s_


@dataclass
class SaveOp:
    mobile: str
    new_active: Dict[str, str]
    archive: Optional[Dict[str, str]]   # prior Active row -> InActive (None on insert)
    version: int                        # RecordVersion for the archive


class SheetsGateway:
    """Interface. Implementations: GspreadGateway (prod) / FakeGateway (tests)."""

    def load(self) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        raise NotImplementedError

    def apply_save(self, op: SaveOp) -> None:
        raise NotImplementedError

    def ping(self) -> bool:
        raise NotImplementedError


# --- production implementation (gspread) -------------------------------------
class GspreadGateway(SheetsGateway):
    # Fields the app OWNS. Any live-sheet column whose header is NOT in this set
    # is treated as external (e.g. "Alternative Mobile Number", filled by the
    # Google-Form/.gs side): it is preserved on update and never written by the app.
    _MANAGED = set(ACTIVE_COLUMNS)

    def __init__(self, settings: Settings):
        self.s = settings
        self._gc = None
        self._ss = None
        self._active_ws = None
        self._inactive_ws = None

    # lazy connect so importing this module never needs network/credentials
    def _connect(self):
        if self._ss is not None:
            return
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(
            self.s.service_account_file, scopes=scopes)
        self._gc = gspread.authorize(creds)
        self._ss = self._gc.open_by_key(self.s.data_sheet_id)
        self._active_ws = self._find_ws([self.s.active_tab] + list(self.s.active_tab_aliases))
        self._inactive_ws = self._find_ws([self.s.inactive_tab], create_cols=len(INACTIVE_COLUMNS))
        if self._active_ws is None:
            raise RuntimeError("Active tab not found in the Data sheet.")

    def _find_ws(self, names, create_cols: int = 0):
        for w in self._ss.worksheets():
            if w.title in names:
                return w
        if create_cols and names:
            return self._ss.add_worksheet(title=names[0], rows=1, cols=create_cols)
        return None

    # --- live header helpers (read row 1 fresh; order can change out-of-band) --
    @staticmethod
    def _live_header(ws) -> List[str]:
        """The worksheet's current header row, as a list of cleaned names."""
        if ws is None:
            return []
        return [s_(h) for h in ws.row_values(1)]

    @staticmethod
    def _row_map(header: List[str], row: List[object]) -> Dict[str, str]:
        """{header name -> cell value} for one row (first occurrence wins)."""
        out: Dict[str, str] = {}
        for i, h in enumerate(header):
            if h and h not in out:
                out[h] = s_(row[i]) if i < len(row) else ""
        return out

    def load(self):
        self._connect()
        active_rows = self._active_ws.get_all_values()
        active = self._rows_to_records(active_rows, ACTIVE_COLUMNS)
        inactive = []
        if self._inactive_ws is not None:
            inactive_rows = self._inactive_ws.get_all_values()
            inactive = self._rows_to_records(inactive_rows, INACTIVE_COLUMNS)
        return active, inactive

    @staticmethod
    def _rows_to_records(rows, columns):
        if not rows:
            return []
        header = [str(h).strip() for h in rows[0]]
        # map by header name (robust to extra/reordered columns)
        idx = {h: i for i, h in enumerate(header)}
        out = []
        for r in rows[1:]:
            rec = {}
            for c in columns:
                j = idx.get(c, -1)
                rec[c] = str(r[j]).strip() if 0 <= j < len(r) else ""
            # skip fully-blank rows
            if any(v for v in rec.values()):
                out.append(rec)
        return out

    def apply_save(self, op: SaveOp) -> None:
        self._connect()

        # Live Active header + the mobile's current row (if any). Everything below
        # is aligned to THIS header by name, so column order/insertions never
        # misalign a write.
        header = self._live_header(self._active_ws)
        if not header:
            raise RuntimeError("Active tab has no header row.")
        try:
            mcol0 = header.index(MOBILE_COL)              # 0-based
        except ValueError:
            raise RuntimeError(
                'Active tab header has no "%s" column.' % MOBILE_COL)

        cell = None
        try:
            cell = self._active_ws.find(op.mobile, in_column=mcol0 + 1)
        except Exception:
            cell = None

        existing_row: List[object] = []
        if cell is not None:
            try:
                existing_row = self._active_ws.row_values(cell.row)
            except Exception:
                existing_row = []

        # 1) archive the prior version to InActive — taken from the REAL current
        #    Active row so ALL columns (incl. ones the app doesn't manage) are
        #    preserved in history. Only on update (op.archive signals a prior row).
        if op.archive is not None and self._inactive_ws is not None and cell is not None:
            old = self._row_map(header, existing_row)          # prior values, by name
            old["RecordVersion"] = str(op.version)
            old["ArchivedAt"] = now_timestamp()
            iheader = self._live_header(self._inactive_ws)
            if not iheader:
                # brand-new / empty InActive tab: write a header row FIRST so every
                # later write (ours or the form's) can align to it by name.
                self._inactive_ws.append_row(list(INACTIVE_COLUMNS), value_input_option="RAW")
                iheader = list(INACTIVE_COLUMNS)
            irow = [s_(old.get(h, "")) for h in iheader]       # aligned to InActive header
            self._inactive_ws.append_row(irow, value_input_option="USER_ENTERED")

        # 2) upsert the Active row for this mobile, aligned to the live header.
        if cell is not None:
            newrow = []
            for i, h in enumerate(header):
                if h in self._MANAGED:
                    newrow.append(s_(op.new_active.get(h, "")))       # app owns it
                else:
                    newrow.append(s_(existing_row[i]) if i < len(existing_row) else "")  # preserve
            self._active_ws.update(
                f"A{cell.row}", [newrow], value_input_option="USER_ENTERED")
        else:
            newrow = [s_(op.new_active.get(h, "")) if h in self._MANAGED else ""
                      for h in header]
            self._active_ws.append_row(newrow, value_input_option="USER_ENTERED")

    def ping(self) -> bool:
        try:
            self._connect()
            _ = self._active_ws.acell("A1").value
            return True
        except Exception:
            return False
