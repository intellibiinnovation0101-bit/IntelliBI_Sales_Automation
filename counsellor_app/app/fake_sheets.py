"""
An in-memory stand-in for Google Sheets, used by the test-suite and by the
`--fake` run mode so the whole system can be exercised offline (no credentials,
no network). It implements the exact same SheetsGateway interface and the same
upsert/archive semantics as the real gspread gateway, so a test that passes here
is meaningful for production.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Tuple

from .config import ACTIVE_COLUMNS, INACTIVE_COLUMNS, MOBILE_COL
from .domain import row_from_record, record_from_row, now_timestamp
from .sheets_gateway import SheetsGateway, SaveOp


class FakeGateway(SheetsGateway):
    def __init__(self, active=None, inactive=None, latency: float = 0.0):
        # stored as ordered rows (list-of-lists), header first, exactly like a sheet
        self._active: List[List[str]] = [list(ACTIVE_COLUMNS)]
        self._inactive: List[List[str]] = [list(INACTIVE_COLUMNS)]
        self._latency = latency
        self._lock = threading.RLock()
        self.apply_calls = 0                 # tests assert on how often we hit "sheets"
        for rec in (active or []):
            self._active.append(row_from_record(rec, ACTIVE_COLUMNS))
        for rec in (inactive or []):
            self._inactive.append(row_from_record(rec, INACTIVE_COLUMNS))

    def _sleep(self):
        if self._latency:
            import time
            time.sleep(self._latency)

    def load(self) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        self._sleep()
        with self._lock:
            active = [record_from_row(r, ACTIVE_COLUMNS) for r in self._active[1:]
                      if any(str(v).strip() for v in r)]
            inactive = [record_from_row(r, INACTIVE_COLUMNS) for r in self._inactive[1:]
                        if any(str(v).strip() for v in r)]
        return active, inactive

    def apply_save(self, op: SaveOp) -> None:
        self._sleep()
        with self._lock:
            self.apply_calls += 1
            # 1) archive prior version
            if op.archive is not None:
                arec = dict(op.archive)
                arec["RecordVersion"] = str(op.version)
                arec["ArchivedAt"] = now_timestamp()
                self._inactive.append(row_from_record(arec, INACTIVE_COLUMNS))
            # 2) upsert active by mobile
            midx = ACTIVE_COLUMNS.index(MOBILE_COL)
            row_vals = row_from_record(op.new_active, ACTIVE_COLUMNS)
            found = -1
            for i in range(1, len(self._active)):
                if i < len(self._active) and midx < len(self._active[i]) \
                        and str(self._active[i][midx]).strip() == op.mobile:
                    found = i
                    break
            if found >= 0:
                self._active[found] = row_vals
            else:
                self._active.append(row_vals)

    def ping(self) -> bool:
        return True

    # --- test helpers (not part of the interface) ---
    def raw_active_rows(self) -> List[List[str]]:
        with self._lock:
            return [list(r) for r in self._active]

    def raw_inactive_rows(self) -> List[List[str]]:
        with self._lock:
            return [list(r) for r in self._inactive]
