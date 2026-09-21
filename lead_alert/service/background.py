"""
Background loops: the source-sheet poller (lead detection) and the escalation
timer. Both respect the configured operating window and only touch Google over a
worker thread so the WebSocket event loop stays responsive.
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

CURSOR_KEY = "source_cursor_row"


async def _init_cursor():
    """On first ever start, skip everything already in the sheet so we don't
    alert historical leads. Afterwards resume from the stored cursor."""
    if store.meta_get(CURSOR_KEY) is not None:
        return
    count = await asyncio.to_thread(google_io.source_row_count)
    start = count if count > 0 else 1          # rows 1..count already "seen"
    store.meta_set(CURSOR_KEY, start)
    print(f"  [poller] initialized cursor at row {start} (existing rows skipped)")


async def poll_loop():
    await _init_cursor()
    print(f"  [poller] watching '{SETTINGS.source_tab}' every "
          f"{SETTINGS.poll_seconds}s (window {SETTINGS.active_from}-{SETTINGS.active_to})")
    while True:
        try:
            if ops.within_active_window():
                cursor = int(store.meta_get(CURSOR_KEY, 1))
                count = await asyncio.to_thread(google_io.source_row_count)
                if count > cursor:
                    rows = await asyncio.to_thread(
                        google_io.read_source_rows, cursor + 1, count)
                    for row in rows:
                        # skip blank/partial rows (need a name or a mobile)
                        if not (row.get("name") or row.get("mobile")):
                            continue
                        lead = ops.build_lead_from_row(row)
                        await ops.dispatch_lead(lead)
                    store.meta_set(CURSOR_KEY, count)
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
