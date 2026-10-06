"""
Background loops: the source-sheet poller (lead detection) and the escalation
timer. Both respect the operating window and touch Google only on a worker
thread so the WebSocket event loop is never stalled.

Lead detection is by CONTENT identity (a stable per-lead fingerprint), NOT by
sheet row number — deleting/reordering rows can never cause a missed or duplicate
alert. On first run every existing row is recorded as already-seen (no historical
spam); thereafter only genuinely new leads fire.

Resilience: the loop NEVER dies. A transient Google/network error is caught and
retried on the next tick. The one-time baseline seeding only commits once the
sheet has actually been read, so a hiccup at startup can never mis-seed or spam.
A heartbeat timestamp is recorded after every healthy poll (exposed via /health).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from config import SETTINGS
import store
import google_io
import mailer
import netcheck
import ops
import discovery
from hub import HUB
from offline_monitor import OfflineMonitor

SEED_FLAG = "seed_v2_done"
LAST_POLL_KEY = "last_poll_ts"
NO_ONLINE_KEY = "last_no_online_alert_ts"
# Rows scanned from the BOTTOM of the sheet each poll. New leads always append at
# the bottom, so a generous trailing window always contains them (and covers an
# overnight backlog). Reading it is one API call.
WINDOW = 500


async def _seed_once() -> bool:
    """Record every existing sheet row as already-seen so only leads arriving
    AFTER go-live pop. Returns True only when the sheet was actually read and the
    baseline committed; False on a transient read error (caller retries) so we
    can never mis-seed and spam historical leads."""
    count = await asyncio.to_thread(google_io.source_row_count)
    if count is None or count < 0:
        print("  [poller] seed deferred — sheet not readable yet, will retry")
        return False
    if count >= 2:
        rows = await asyncio.to_thread(google_io.read_source_rows, 2, count)
        if not rows:                      # rows exist but read failed -> retry
            print("  [poller] seed deferred — row read failed, will retry")
            return False
        seeded = 0
        for row in rows:
            if not (row.get("name") or row.get("mobile")):
                continue
            store.mark_seen(ops.build_lead_from_row(row))
            seeded += 1
        print(f"  [poller] seeded {seeded} existing leads as already-seen")
    # Retire leftovers from the old row-number scheme so they don't escalate.
    for l in store.open_leads():
        if not str(l.get("lead_id", "")).startswith("web:"):
            store.expire_lead(l["lead_id"])
    store.meta_set(SEED_FLAG, "1")
    return True


async def poll_loop():
    print(f"  [poller] watching '{SETTINGS.source_tab}' every "
          f"{SETTINGS.poll_seconds}s by content-id (trailing window {WINDOW}); "
          f"active {SETTINGS.active_from}-{SETTINGS.active_to}")
    while True:
        try:
            # One-time baseline; retried safely until the sheet reads OK.
            if not store.meta_get(SEED_FLAG):
                if not await _seed_once():
                    await asyncio.sleep(max(5, SETTINGS.poll_seconds))
                    continue
            if ops.within_active_window():
                count = await asyncio.to_thread(google_io.source_row_count)
                if count is not None and count >= 1:
                    if count >= 2:
                        first = max(2, count - WINDOW + 1)
                        rows = await asyncio.to_thread(
                            google_io.read_source_rows, first, count)
                        for row in (rows or []):
                            if not (row.get("name") or row.get("mobile")):
                                continue
                            lead = ops.build_lead_from_row(row)
                            if store.lead_exists(lead["lead_id"]):
                                continue
                            await ops.dispatch_lead(lead)
                    store.meta_set(LAST_POLL_KEY, ops.now_str())   # heartbeat
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
                await check_no_one_online()
        except Exception as e:
            print("  [escalation] loop error (continuing):", e)
        await asyncio.sleep(tick)


# ── presence ─────────────────────────────────────────────────────────────────
async def presence_loop():
    """Close connections that stopped sending heartbeats (half-open sockets after
    sleep / Wi-Fi loss). Runs on every computer, primary or standby."""
    while True:
        try:
            dropped = await HUB.sweep()
            if dropped:
                print(f"  [presence] swept stale: {', '.join(dropped)}")
        except Exception as e:
            print("  [presence] sweep error (continuing):", e)
        await asyncio.sleep(max(5, SETTINGS.presence_sweep_seconds))


async def netcheck_loop():
    """Keep counsellor PCs able to reach this server whatever network the office
    PC is on: full firewall check (+ auto-repair) at start, every
    netcheck_minutes, and IMMEDIATELY when the local IP addresses change
    (joined another network / new DHCP address)."""
    last_fp, last_full = None, 0.0
    while True:
        try:
            fp = await asyncio.to_thread(netcheck.fingerprint)
            due = time.time() - last_full >= max(60, SETTINGS.netcheck_minutes * 60)
            if fp != last_fp or due:
                reason = ("start" if last_fp is None else
                          f"network changed: {last_fp or '-'} -> {fp or '-'}"
                          if fp != last_fp else "scheduled")
                if last_fp is not None and fp != last_fp:
                    print(f"  [netcheck] {reason} — re-checking reachability now")
                await asyncio.to_thread(netcheck.run, SETTINGS.port,
                                        SETTINGS.discovery_port,
                                        SETTINGS.auto_fix_firewall, reason)
                last_fp, last_full = fp, time.time()
        except Exception as e:
            print("  [netcheck] error (continuing):", e)
        await asyncio.sleep(30)


async def check_no_one_online(now: float = None) -> bool:
    """E-mail the escalation section when website leads are waiting and NO
    counsellor is genuinely online. Guards against false alarms:
      * never during the startup grace (apps are still reconnecting),
      * never while the presence sweeper itself is not running,
      * only for leads that nobody has been shown yet and that have waited
        no_online_alert_after_seconds,
      * at most once per lead and once per cooldown period.
    If the network self-check says counsellor PCs CANNOT reach this server, the
    e-mail says so (a server problem), instead of blaming the counsellors.
    Returns True when an alert was sent."""
    if not SETTINGS.no_online_alert or HUB.in_startup_grace():
        return False
    if not HUB.sweeper_healthy():
        print("  [presence] monitor not healthy — 'no counsellor online' alert withheld")
        return False
    if HUB.online_emails():
        return False
    now = now or time.time()
    waiting = []
    for lead in store.open_leads():
        if lead.get("no_online_alerted"):
            continue
        if now - (lead.get("created_ts") or now) < SETTINGS.no_online_alert_after_seconds:
            continue
        if store.delivery_summary(lead["lead_id"])["delivered"]:
            continue
        waiting.append(lead)
    if not waiting:
        return False
    last = float(store.meta_get(NO_ONLINE_KEY, 0) or 0)
    if now - last < SETTINGS.no_online_alert_cooldown_min * 60:
        return False
    info = {"presence": ops.presence_report(), "network": dict(netcheck.LAST),
            "refused": list(HUB.rejections)[-5:]}
    sent = await asyncio.to_thread(mailer.send_no_online_alert, waiting, info)
    if sent:
        store.mark_no_online_alerted([l["lead_id"] for l in waiting])
        store.meta_set(NO_ONLINE_KEY, now)
        print(f"  [presence] 'no counsellor online' alert sent for {len(waiting)} lead(s)")
    return bool(sent)



# ── "all counsellors offline for 1 hour" ────────────────────────────────────
_MONITOR = None


def offline_monitor() -> OfflineMonitor:
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = OfflineMonitor(SETTINGS.offline_alert_days, SETTINGS.offline_alert_from,
                                  SETTINGS.offline_alert_to,
                                  SETTINGS.offline_alert_after_minutes,
                                  store.meta_get, store.meta_set)
    return _MONITOR


def offline_window_text() -> str:
    days = SETTINGS.offline_alert_days
    label = ("every day" if len({d.strip().lower()[:3] for d in days}) == 7
             else ", ".join(days))
    return f"{label} {SETTINGS.offline_alert_from}-{SETTINGS.offline_alert_to}"


async def offline_alert_step(now: datetime = None) -> str:
    """One evaluation (called every 30 s). Returns 'sent' | 'ended' | ''."""
    mon = offline_monitor()
    now = now or datetime.now()
    monitor_ok = (not HUB.in_startup_grace()) and HUB.sweeper_healthy()
    res = mon.tick(now, bool(HUB.online_emails()), monitor_ok)
    if not res:
        return ""
    if res.get("ended"):
        print("  [offline-alert] a counsellor is online again — offline timer reset")
        return "ended"
    since = res["offline_since"]
    print(f"  [offline-alert] ALL counsellors offline since {since:%H:%M} "
          f"({int((now - since).total_seconds() // 60)} min) — sending alert")
    info = {"offline_since": since, "now": now, "presence": ops.presence_report(),
            "network": dict(netcheck.LAST), "leads": store.leads_since(since.timestamp()),
            "server_urls": [f"http://{ip}:{SETTINGS.port}" for ip in discovery.local_ipv4s()],
            "window": offline_window_text(),
            "after_minutes": SETTINGS.offline_alert_after_minutes}
    if await asyncio.to_thread(mailer.send_offline_hour_alert, info):
        mon.mark_alerted(res["key"])
        return "sent"
    print("  [offline-alert] e-mail not sent — will retry in 5 minutes")
    await asyncio.sleep(270)
    return ""


async def offline_alert_loop():
    print(f"  [offline-alert] e-mail '{SETTINGS.offline_alert_section}' when ALL counsellors "
          f"are offline for {int(SETTINGS.offline_alert_after_minutes)} min "
          f"({offline_window_text()})")
    while True:
        try:
            await offline_alert_step()
        except Exception as e:
            print("  [offline-alert] error (continuing):", e)
        await asyncio.sleep(30)
