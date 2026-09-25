"""
The store is what makes the app "lightning fast" and safe at the same time.

READS  -> served from an in-memory index (mobile -> current record, and
          mobile -> history). Pure dict lookups, sub-millisecond, no network.

WRITES -> applied to the in-memory index instantly, persisted to a local SQLite
          database (durable cache + a write-behind JOURNAL of un-synced writes),
          and acknowledged to the counsellor immediately. A background worker
          (see sync.py) drains the journal to Google Sheets a moment later.

Durability: the journal is committed to disk before we acknowledge a save, so a
crash/restart never loses a counsellor's write — on startup we replay any
un-synced journal rows on top of the freshly-loaded sheet data and re-queue them
for syncing. Google Sheets stays the system of record; SQLite is only a cache +
outbox, never a second source of truth.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from .config import Settings, MOBILE_COL, EDITABLE_FIELDS
from .domain import (
    build_record, validate_submission, normalize_mobile, is_valid_indian_mobile,
    lt_norm,
)
from .sheets_gateway import SheetsGateway, SaveOp


class Store:
    def __init__(self, settings: Settings, gateway: SheetsGateway):
        self.s = settings
        self.gw = gateway
        self._lock = threading.RLock()
        # in-memory index
        self._active: Dict[str, Dict[str, str]] = {}          # mobile -> record
        self._history: Dict[str, List[Dict[str, str]]] = {}   # mobile -> [prior versions, newest first]
        self._loaded = False
        self._last_reconcile_ok = True
        # True when start-up could not reach Google Sheets and the server came up
        # from the last local snapshot instead (see bootstrap()). Cleared by the
        # first successful reconcile(). Surfaced on /health so an admin can see
        # "serving from cache" vs "fully in sync".
        self.booted_from_cache = False
        os.makedirs(os.path.dirname(self.s.db_path) or ".", exist_ok=True)
        self._db = sqlite3.connect(self.s.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_db()

    # ---------------------------------------------------------------- db setup
    def _init_db(self):
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL;")
            self._db.execute("PRAGMA synchronous=NORMAL;")
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_active(
                    mobile TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS cache_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mobile TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_hist_mobile ON cache_history(mobile);
                CREATE TABLE IF NOT EXISTS journal(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    mobile TEXT NOT NULL,
                    new_active_json TEXT NOT NULL,
                    archive_json TEXT,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_journal_status ON journal(status, seq);
                """
            )
            self._db.commit()

    # ------------------------------------------------------------- bootstrap
    def bootstrap(self):
        """Load current state from Google Sheets, then replay any un-synced
        journal writes on top so nothing in flight is lost.

        OFFLINE-BOOT FALLBACK: if Google Sheets cannot be reached at start-up
        (typically the office PC booting while the internet link is down), the
        server still comes up from the last snapshot persisted in the local
        SQLite cache, so counsellors keep their URL, login and data. Saves made
        meanwhile are journaled as usual and pushed once connectivity returns,
        and the periodic reconcile() replaces the snapshot with live sheet data
        at that point. Start-up only fails outright when there is NO snapshot
        at all (the very first run, before any successful sync).
        """
        try:
            active, inactive = self.gw.load()
        except Exception as exc:  # noqa: BLE001 - any transport/auth failure
            if self._load_from_cache():
                self.booted_from_cache = True
                self._last_reconcile_ok = False      # stale until reconcile succeeds
                logging.getLogger(__name__).warning(
                    "Google Sheets unreachable at start-up (%s); serving from the "
                    "local cache (%d leads) until the next successful sync.",
                    exc, len(self._active))
                return
            raise                                    # nothing cached -> real failure
        with self._lock:
            self._active = {}
            self._history = {}
            for rec in active:
                m = normalize_mobile(rec.get(MOBILE_COL))
                if m:
                    rec[MOBILE_COL] = m
                    self._active[m] = rec
            # inactive rows are prior versions; group by mobile, newest first
            hist_tmp: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}
            for rec in inactive:
                m = normalize_mobile(rec.get(MOBILE_COL))
                if not m:
                    continue
                try:
                    v = int(rec.get("RecordVersion") or 0)
                except ValueError:
                    v = 0
                hist_tmp.setdefault(m, []).append((v, rec))
            for m, lst in hist_tmp.items():
                lst.sort(key=lambda t: t[0], reverse=True)
                self._history[m] = [r for _, r in lst]
            self._rebuild_cache_locked()
            # replay pending journal (un-synced writes) on top of sheet state
            self._replay_pending_locked()
            self._loaded = True

    def _load_from_cache(self) -> bool:
        """Rebuild the in-memory index from the persisted SQLite snapshot
        (cache_active / cache_history) and replay un-synced journal writes on
        top. Returns False when no snapshot exists yet."""
        with self._lock:
            rows = self._db.execute(
                "SELECT mobile, record_json FROM cache_active").fetchall()
            if not rows:
                return False
            self._active = {r["mobile"]: json.loads(r["record_json"]) for r in rows}
            hist: Dict[str, List[Dict[str, str]]] = {}
            for r in self._db.execute(
                    "SELECT mobile, record_json FROM cache_history "
                    "ORDER BY version DESC, id DESC").fetchall():
                hist.setdefault(r["mobile"], []).append(json.loads(r["record_json"]))
            self._history = hist
            # the snapshot tables ARE the source right now, so leave them as-is;
            # keep in-flight (un-synced) saves visible exactly as a normal boot does.
            self._replay_pending_locked()
            self._loaded = True
            return True

    def _replay_pending_locked(self):
        rows = self._db.execute(
            "SELECT * FROM journal WHERE status='pending' ORDER BY seq ASC"
        ).fetchall()
        for r in rows:
            new_active = json.loads(r["new_active_json"])
            archive = json.loads(r["archive_json"]) if r["archive_json"] else None
            m = r["mobile"]
            if archive is not None:
                self._history.setdefault(m, []).insert(0, archive)
            self._active[m] = new_active

    def _rebuild_cache_locked(self):
        self._db.execute("DELETE FROM cache_active;")
        self._db.execute("DELETE FROM cache_history;")
        for m, rec in self._active.items():
            self._db.execute(
                "INSERT INTO cache_active(mobile, record_json, version) VALUES(?,?,?)",
                (m, json.dumps(rec), len(self._history.get(m, []))),
            )
        for m, lst in self._history.items():
            for rec in lst:
                self._db.execute(
                    "INSERT INTO cache_history(mobile, record_json, version, archived_at)"
                    " VALUES(?,?,?,?)",
                    (m, json.dumps(rec), int(rec.get("RecordVersion") or 0),
                     rec.get("ArchivedAt", "")),
                )
        self._db.commit()

    # ------------------------------------------------------------------- reads
    def get(self, mobile: str) -> Optional[Dict[str, str]]:
        m = normalize_mobile(mobile)
        with self._lock:
            rec = self._active.get(m)
            return dict(rec) if rec else None

    def history(self, mobile: str) -> List[Dict[str, str]]:
        m = normalize_mobile(mobile)
        with self._lock:
            return [dict(r) for r in self._history.get(m, [])]

    def exists(self, mobile: str) -> bool:
        return self.get(mobile) is not None

    def search(self, term: str, limit: int = 20) -> List[Dict[str, str]]:
        """Search by mobile fragment or a name/email substring."""
        t = lt_norm(term)
        tdig = normalize_mobile(term)
        out = []
        with self._lock:
            for m, rec in self._active.items():
                if (tdig and tdig in m) or \
                   (t and (t in lt_norm(rec.get("Full Name")) or
                           t in lt_norm(rec.get("Email Address")))):
                    out.append(dict(rec))
                    if len(out) >= limit:
                        break
        return out

    def count(self) -> int:
        with self._lock:
            return len(self._active)

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM journal WHERE status='pending'").fetchone()
            return int(row["n"])

    # ------------------------------------------------------------------ writes
    def save(self, fields: Dict[str, object], mobile: str,
             counselling_by: str = "") -> Tuple[bool, str, Optional[Dict[str, str]]]:
        """Validate + apply a counsellor update. Fast path: in-memory + journal,
        acknowledged immediately; the sheet is updated asynchronously."""
        m = normalize_mobile(mobile)
        if not is_valid_indian_mobile(m):
            return False, "Enter a valid 10-digit mobile number starting 6-9.", None

        # only editable fields are accepted from the client
        clean = {k: v for k, v in (fields or {}).items() if k in EDITABLE_FIELDS}
        record = build_record(clean, m, counselling_by=counselling_by)
        ok, msg = validate_submission(record)
        if not ok:
            return False, msg, None

        with self._lock:
            prior = self._active.get(m)
            version = len(self._history.get(m, [])) + 1
            archive = dict(prior) if prior else None
            # 1) durable journal write FIRST (so a crash keeps the write)
            cur = self._db.execute(
                "INSERT INTO journal(mobile,new_active_json,archive_json,version,"
                "status,created_at) VALUES(?,?,?,?, 'pending', ?)",
                (m, json.dumps(record),
                 json.dumps(archive) if archive else None,
                 version, record.get("RecordTimeStamp", "")),
            )
            # 2) update durable cache
            self._db.execute(
                "INSERT INTO cache_active(mobile,record_json,version) VALUES(?,?,?)"
                " ON CONFLICT(mobile) DO UPDATE SET record_json=excluded.record_json,"
                " version=excluded.version",
                (m, json.dumps(record), version),
            )
            if archive is not None:
                ar = dict(archive)
                ar["RecordVersion"] = str(version)
                self._db.execute(
                    "INSERT INTO cache_history(mobile,record_json,version,archived_at)"
                    " VALUES(?,?,?,?)",
                    (m, json.dumps(ar), version, ar.get("ArchivedAt", "")),
                )
            self._db.commit()
            # 3) update in-memory index (what reads see instantly)
            if archive is not None:
                ar = dict(archive)
                ar["RecordVersion"] = str(version)
                self._history.setdefault(m, []).insert(0, ar)
            self._active[m] = record
        return True, "Saved.", dict(record)

    # ------------------------------------------------ write-behind (sync.py)
    def drain_pending(self, limit: int) -> List[Tuple[int, SaveOp]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM journal WHERE status='pending' ORDER BY seq ASC LIMIT ?",
                (limit,),
            ).fetchall()
        ops = []
        for r in rows:
            op = SaveOp(
                mobile=r["mobile"],
                new_active=json.loads(r["new_active_json"]),
                archive=json.loads(r["archive_json"]) if r["archive_json"] else None,
                version=r["version"],
            )
            ops.append((r["seq"], op))
        return ops

    def mark_synced(self, seqs: List[int]):
        if not seqs:
            return
        with self._lock:
            self._db.executemany(
                "UPDATE journal SET status='synced' WHERE seq=?",
                [(s,) for s in seqs],
            )
            # keep the journal small: drop synced rows older than the last 500
            self._db.execute(
                "DELETE FROM journal WHERE status='synced' AND seq NOT IN "
                "(SELECT seq FROM journal WHERE status='synced' ORDER BY seq DESC LIMIT 500)"
            )
            self._db.commit()

    def reconcile(self) -> bool:
        """Re-read the sheet to pick up any out-of-band edits, preserving
        un-synced writes. Returns True on success."""
        try:
            active, inactive = self.gw.load()
        except Exception:
            self._last_reconcile_ok = False
            return False
        with self._lock:
            new_active: Dict[str, Dict[str, str]] = {}
            for rec in active:
                m = normalize_mobile(rec.get(MOBILE_COL))
                if m:
                    rec[MOBILE_COL] = m
                    new_active[m] = rec
            new_hist: Dict[str, List[Dict[str, str]]] = {}
            for rec in inactive:
                m = normalize_mobile(rec.get(MOBILE_COL))
                if not m:
                    continue
                try:
                    v = int(rec.get("RecordVersion") or 0)
                except ValueError:
                    v = 0
                new_hist.setdefault(m, []).append((v, rec))
            for m in list(new_hist.keys()):
                new_hist[m] = [r for _, r in sorted(new_hist[m], key=lambda t: t[0],
                                                    reverse=True)]
            self._active = new_active
            self._history = {k: v for k, v in new_hist.items()}
            self._rebuild_cache_locked()
            self._replay_pending_locked()   # keep in-flight writes visible
            self._last_reconcile_ok = True
            self.booted_from_cache = False  # live sheet data has replaced any offline snapshot
        return True

    def close(self):
        with self._lock:
            try:
                self._db.commit()
                self._db.close()
            except Exception:
                pass
