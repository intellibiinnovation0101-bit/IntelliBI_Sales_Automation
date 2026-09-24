"""
The ONLY component that talks to Google Sheets. Everything else goes through this
interface, so storage is swappable (Sheets today, a DB later) without touching
counsellors or the UI.

A "save operation" carries the new Active record and (on update) the prior
version to archive, so applying it to the sheet reproduces the .gs upsert:
    - append the prior version to the InActive tab (RecordVersion, ArchivedAt),
    - overwrite the mobile's Active row (or append if new).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import config
from .config import (
    ACTIVE_COLUMNS, INACTIVE_COLUMNS, AUDIT_COLUMNS, MOBILE_COL, Settings,
)
from .domain import row_from_record, record_from_row, normalize_mobile, now_timestamp


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
        # 1) archive the prior version to InActive
        if op.archive is not None and self._inactive_ws is not None:
            arec = dict(op.archive)
            arec["RecordVersion"] = str(op.version)
            arec["ArchivedAt"] = now_timestamp()
            self._inactive_ws.append_row(
                row_from_record(arec, INACTIVE_COLUMNS),
                value_input_option="USER_ENTERED")
        # 2) upsert the Active row for this mobile
        mcol = ACTIVE_COLUMNS.index(MOBILE_COL) + 1  # 1-based
        row_vals = row_from_record(op.new_active, ACTIVE_COLUMNS)
        cell = None
        try:
            cell = self._active_ws.find(op.mobile, in_column=mcol)
        except Exception:
            cell = None
        if cell is not None:
            self._active_ws.update(
                f"A{cell.row}",
                [row_vals],
                value_input_option="USER_ENTERED")
        else:
            self._active_ws.append_row(row_vals, value_input_option="USER_ENTERED")

    def ping(self) -> bool:
        try:
            self._connect()
            _ = self._active_ws.acell("A1").value
            return True
        except Exception:
            return False
