"""
SQLite lifecycle store for the Website Lead Alert service.

This is the SINGLE SOURCE OF TRUTH for lead assignment. The "one lead -> one
counsellor" guarantee comes from an atomic conditional UPDATE inside a
transaction (claim_lead) — the database, not the clients, decides the winner,
so two counsellors clicking Accept at the same instant can never both succeed.

Tables
  leads       one row per website lead + its lifecycle state
  deliveries  one row per (lead, counsellor) — who was notified / acknowledged
  devices     registered counsellor devices (opaque bearer tokens, revocable)
  meta        small key/value store (e.g. the source-sheet row cursor)
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from config import DB_PATH

_LOCK = threading.Lock()          # serialize writers (SQLite + our own safety)
_conn: Optional[sqlite3.Connection] = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA busy_timeout=5000;")
        _init(_conn)
    return _conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            lead_id       TEXT PRIMARY KEY,
            source_row    INTEGER,
            received_at   TEXT,
            enquiry_date  TEXT,
            name          TEXT,
            mobile        TEXT,
            email         TEXT,
            course        TEXT,
            form_type     TEXT,
            preview       TEXT,
            subject       TEXT,
            sender        TEXT,
            status        TEXT DEFAULT 'RECEIVED',   -- RECEIVED | ASSIGNED | UNACKNOWLEDGED
            assigned_to   TEXT,
            assigned_name TEXT,
            assigned_at   TEXT,
            realerted     INTEGER DEFAULT 0,
            escalated     INTEGER DEFAULT 0,
            created_ts    REAL
        );
        CREATE TABLE IF NOT EXISTS deliveries (
            lead_id          TEXT,
            counsellor_email TEXT,
            counsellor_name  TEXT,
            delivered        INTEGER DEFAULT 0,
            delivered_at     TEXT,
            acked            INTEGER DEFAULT 0,
            acked_at         TEXT,
            PRIMARY KEY (lead_id, counsellor_email)
        );
        CREATE TABLE IF NOT EXISTS devices (
            token            TEXT PRIMARY KEY,
            counsellor_email TEXT,
            counsellor_name  TEXT,
            machine          TEXT,
            created_at       TEXT,
            last_seen        TEXT,
            active           INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS meta (
            k TEXT PRIMARY KEY,
            v TEXT
        );
        """
    )
    conn.commit()


# ── meta (cursor) ────────────────────────────────────────────────────────────
def meta_get(key: str, default=None):
    cur = _connect().execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return cur["v"] if cur else default


def meta_set(key: str, value) -> None:
    with _LOCK:
        c = _connect()
        c.execute("INSERT INTO meta(k,v) VALUES(?,?) "
                  "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, str(value)))
        c.commit()


# ── leads ────────────────────────────────────────────────────────────────────
def lead_exists(lead_id: str) -> bool:
    return _connect().execute(
        "SELECT 1 FROM leads WHERE lead_id=?", (lead_id,)).fetchone() is not None


def insert_lead(lead: dict) -> bool:
    """Insert a new RECEIVED lead. Returns False if it already exists (dedup)."""
    with _LOCK:
        c = _connect()
        if c.execute("SELECT 1 FROM leads WHERE lead_id=?",
                     (lead["lead_id"],)).fetchone():
            return False
        c.execute(
            """INSERT INTO leads(lead_id, source_row, received_at, enquiry_date,
                   name, mobile, email, course, form_type, preview, subject,
                   sender, status, created_ts)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'RECEIVED', ?)""",
            (lead["lead_id"], lead.get("source_row"), lead.get("received_at"),
             lead.get("enquiry_date"), lead.get("name"), lead.get("mobile"),
             lead.get("email"), lead.get("course"), lead.get("form_type"),
             lead.get("preview"), lead.get("subject"), lead.get("sender"),
             time.time()))
        c.commit()
        return True


def mark_seen(lead: dict) -> None:
    """Record a lead id as already-known WITHOUT dispatching it — used to seed
    the baseline of pre-existing sheet rows on first run. Stored with status
    'SEEN' so it never appears in open_leads()/escalation."""
    with _LOCK:
        c = _connect()
        c.execute(
            """INSERT OR IGNORE INTO leads(lead_id, source_row, received_at,
                   enquiry_date, name, mobile, email, course, form_type,
                   preview, subject, sender, status, created_ts)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'SEEN', ?)""",
            (lead["lead_id"], lead.get("source_row"), lead.get("received_at"),
             lead.get("enquiry_date"), lead.get("name"), lead.get("mobile"),
             lead.get("email"), lead.get("course"), lead.get("form_type"),
             lead.get("preview"), lead.get("subject"), lead.get("sender"),
             time.time()))
        c.commit()


def get_lead(lead_id: str) -> Optional[dict]:
    row = _connect().execute(
        "SELECT * FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    return dict(row) if row else None


def open_leads() -> list:
    """All leads still awaiting acceptance (RECEIVED)."""
    rows = _connect().execute(
        "SELECT * FROM leads WHERE status='RECEIVED' ORDER BY created_ts").fetchall()
    return [dict(r) for r in rows]


def open_leads_for(email: str) -> list:
    """RECEIVED leads a given counsellor was notified about (for reconnect resync)."""
    rows = _connect().execute(
        """SELECT l.* FROM leads l JOIN deliveries d ON d.lead_id=l.lead_id
           WHERE l.status='RECEIVED' AND lower(d.counsellor_email)=lower(?)
           ORDER BY l.created_ts""", (email,)).fetchall()
    return [dict(r) for r in rows]


def claim_lead(lead_id: str, email: str, name: str, when: str) -> str:
    """ATOMIC single-claim. Returns:
         'assigned' – this counsellor won,
         'already'  – someone already has it,
         'notfound' – no such lead,
         'expired'  – lead is no longer acceptable (UNACKNOWLEDGED)."""
    with _LOCK:
        c = _connect()
        row = c.execute("SELECT status FROM leads WHERE lead_id=?",
                        (lead_id,)).fetchone()
        if not row:
            return "notfound"
        cur = c.execute(
            """UPDATE leads SET status='ASSIGNED', assigned_to=?, assigned_name=?,
                   assigned_at=? WHERE lead_id=? AND status='RECEIVED'""",
            (email, name, when, lead_id))
        c.commit()
        if cur.rowcount == 1:
            return "assigned"
        return "already" if row["status"] in ("ASSIGNED",) else "expired"


def mark_realerted(lead_id: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("UPDATE leads SET realerted=1 WHERE lead_id=?", (lead_id,))
        c.commit()


def mark_escalated(lead_id: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("UPDATE leads SET escalated=1 WHERE lead_id=?", (lead_id,))
        c.commit()


def expire_lead(lead_id: str) -> bool:
    with _LOCK:
        c = _connect()
        cur = c.execute(
            "UPDATE leads SET status='UNACKNOWLEDGED' "
            "WHERE lead_id=? AND status='RECEIVED'", (lead_id,))
        c.commit()
        return cur.rowcount == 1


# ── deliveries ───────────────────────────────────────────────────────────────
def add_delivery(lead_id: str, email: str, name: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("INSERT OR IGNORE INTO deliveries(lead_id, counsellor_email, "
                  "counsellor_name) VALUES(?,?,?)", (lead_id, email, name))
        c.commit()


def mark_delivered(lead_id: str, email: str, when: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("UPDATE deliveries SET delivered=1, delivered_at=? "
                  "WHERE lead_id=? AND lower(counsellor_email)=lower(?)",
                  (when, lead_id, email))
        c.commit()


def mark_acked(lead_id: str, email: str, when: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("UPDATE deliveries SET acked=1, acked_at=? "
                  "WHERE lead_id=? AND lower(counsellor_email)=lower(?)",
                  (when, lead_id, email))
        c.commit()


def delivery_summary(lead_id: str) -> dict:
    rows = _connect().execute(
        "SELECT counsellor_email, delivered FROM deliveries WHERE lead_id=?",
        (lead_id,)).fetchall()
    notified = [r["counsellor_email"] for r in rows]
    delivered = [r["counsellor_email"] for r in rows if r["delivered"]]
    return {"notified": notified, "delivered": delivered}


# ── devices ──────────────────────────────────────────────────────────────────
def add_device(token: str, email: str, name: str, machine: str, when: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("INSERT OR REPLACE INTO devices(token, counsellor_email, "
                  "counsellor_name, machine, created_at, last_seen, active) "
                  "VALUES(?,?,?,?,?,?,1)", (token, email, name, machine, when, when))
        c.commit()


def device_by_token(token: str) -> Optional[dict]:
    row = _connect().execute(
        "SELECT * FROM devices WHERE token=? AND active=1", (token,)).fetchone()
    return dict(row) if row else None


def touch_device(token: str, when: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("UPDATE devices SET last_seen=? WHERE token=?", (when, token))
        c.commit()


def revoke_device(token: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("UPDATE devices SET active=0 WHERE token=?", (token,))
        c.commit()
