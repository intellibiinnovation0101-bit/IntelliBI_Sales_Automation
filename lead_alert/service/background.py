"""
Background loops: the source-sheet poller (lead detection) and the escalation
timer. Both respect the configured operating window and only touch Google over a
worker thread so the WebSocket event loop stays responsive.

Lead detection is by CONTENT identity (a stable per-lead fingerprint), NOT by
sheet row number — so deleting or reordering rows in the source sheet can never
cause a missed or duplicate alert. On first run every existing row is recorded
as already-seen (no historical spam); thereafter only genuinely new leads fire.
"""
from __future__ import annotations

import asyncio
import time

from config import SETTINGS
import store
import google_io
import mailer
import ops
from hub import HUB

SEED_FLAG = "seed_v2_done"
# Rows scanned from the BOTTOM of the sheet each poll. New leads are always
# appended at the bottom, so a generous trailing window always contains them
# (and easily covers an overnight backlog). Reading it is one API call.
WINDOW = 500


async def _seed_once():
    """First run of the content-id poller: record every existing sheet row as
    already-seen so only leads arriving AFTER go-live pop. Also retire any
    still-open leads left over from the previous row-number scheme."""
    if store.meta_get(SEED_FLAG):
        return
    count = await asyncio.to_thread(google_io.source_row_count)
    if count and count >= 2:
        rows = await asyncio.to_thread(google_io.read_source_rows, 2, count)
        seeded = 0
        for row in rows:
            if not (row.get("name") or row.get("mobile")):
                continue
            store.mark_seen(ops.build_lead_from_row(row))
            seeded += 1
        print(f"  [poller] seeded {seeded} existing leads as already-seen")
    # Retire leftovers from the old row-based scheme so they don't escalate.
    for l in store.open_leads():
        if not str(l.get("lead_id", "")).startswith("web:"):
            store.expire_lead(l["lead_id"])
    store.meta_set(SEED_FLAG, "1")


async def poll_loop():
    await _seed_once()
    print(f"  [poller] watching '{SETTINGS.source_tab}' every "
          f"{SETTINGS.poll_seconds}s by content-id (trailing window {WINDOW}); "
          f"active {SETTINGS.active_from}-{SETTINGS.active_to}")
    while True:
        try:
            if ops.within_active_window():
                count = await asyncio.to_thread(google_io.source_row_count)
                if count and count >= 2:
                    first = max(2, count - WINDOW + 1)
                    rows = await asyncio.to_thread(
                        google_io.read_source_rows, first, count)
                    for row in rows:
                        if not (row.get("name") or row.get("mobile")):
                            continue
                        lead = ops.build_lead_from_row(row)
                        if store.lead_exists(lead["lead_id"]):
                            continue
                        await ops.dispatch_lead(lead)
        except Exception as e:
            print("  [poller] loop error (continuing):", e)
        await asyncio.sleep(max(5, SETTINGS.poll_seconds))


async def escalation_loop():
    realert = SETTINGS.realert_after_min * 60
    escalate = SETTINGS.escalate_after_min * 60
    expire = SETTINGS.expire_after_min * 60
    tick = max(10, min(30, SETTINGS.poll_seconds))
    while True:
        try:
            if ops.within_active_window():
                now = time.time()
                for lead in store.open_leads():
                    age = now - (lead.get("created_ts") or now)
                    lid = lead["lead_id"]
                    notified = store.delivery_summary(lid)["notified"]

                    if age >= expire:
                        if store.expire_lead(lid):
                            await HUB.send_to_emails(
                                notified, {"type": "EXPIRE", "lead_id": lid})
                            await asyncio.to_thread(
                                google_io.log_upsert, store.get_lead(lid),
                                store.delivery_summary(lid))
                            print(f"  [escalation] EXPIRED {lid}")
                        continue

                    if age >= escalate and not lead.get("escalated"):
                        await asyncio.to_thread(mailer.send_escalation, lead)
                        store.mark_escalated(lid)
                        await asyncio.to_thread(
                            google_io.log_upsert, store.get_lead(lid),
                            store.delivery_summary(lid))

                    if age >= realert and not lead.get("realerted"):
                        payload = {"type": "NEW_LEAD",
                                   "lead": ops.lead_public(lead), "realert": True}
                        await HUB.send_to_emails(notified, payload)
                        store.mark_realerted(lid)
                        print(f"  [escalation] RE-ALERTED {lid}")
        except Exception as e:
            print("  [escalation] loop error (continuing):", e)
        await asyncio.sleep(tick)
