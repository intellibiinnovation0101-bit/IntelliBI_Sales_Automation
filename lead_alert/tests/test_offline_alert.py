"""
"All counsellors offline for 1 hour" alert — every rule and boundary, driven by a
simulated clock (30-second ticks, like the service). Synthetic data only.

Run:  python lead_alert/tests/test_offline_alert.py
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_SVC = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(_SVC))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "offline.db"
from offline_monitor import OfflineMonitor  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  -- {extra}"))
    if not cond:
        fails.append(name)


MON = datetime(2026, 10, 5)          # Monday
SAT = datetime(2026, 10, 10)
SUN = datetime(2026, 10, 11)


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return day.replace(hour=h, minute=m)


def new_monitor(meta=None, days=None):
    meta = {} if meta is None else meta
    days = days or config.SETTINGS.offline_alert_days      # the production default
    return OfflineMonitor(days, "10:00", "19:00", 60, meta.get, meta.__setitem__), meta


def run(mon, start, end, online=lambda t: False, ok=lambda t: True, step=30):
    """Simulate; returns the list of alert times (alert is 'sent' and marked)."""
    alerts, t = [], start
    while t <= end:
        r = mon.tick(t, online(t), ok(t))
        if r and not r.get("ended"):
            alerts.append(t)
            mon.mark_alerted(r["key"])
        t += timedelta(seconds=step)
    return alerts


def online_between(*ranges):
    return lambda t: any(a <= t < b for a, b in ranges)


# 1. basic: someone online until 10:30, then all offline -> alert at 11:30, only once
m, _ = new_monitor()
a = run(m, at(MON, "09:00"), at(MON, "18:00"), online_between((at(MON, "09:00"), at(MON, "10:30"))))
check("alert exactly 1 hour after the last counsellor went offline", a == [at(MON, "11:30")], a)
check("only ONE e-mail for a continuous offline period (no repeats until 18:00)", len(a) == 1, a)

# 2. shorter than an hour never alerts
m, _ = new_monitor()
a = run(m, at(MON, "10:00"), at(MON, "13:00"), online_between(
    (at(MON, "10:00"), at(MON, "10:30")), (at(MON, "11:29"), at(MON, "13:00"))))
check("59 minutes offline -> no alert", a == [], a)

# 3. timer resets as soon as one counsellor comes online
m, _ = new_monitor()
a = run(m, at(MON, "10:00"), at(MON, "13:00"), online_between(
    (at(MON, "10:00"), at(MON, "10:10")), (at(MON, "11:00"), at(MON, "11:05"))))
check("reset by a brief login: alert 1 h after the LAST departure (12:05), not 11:10",
      a == [at(MON, "12:05")], a)

# 4. new incident after someone came online -> new alert
m, _ = new_monitor()
a = run(m, at(MON, "10:00"), at(MON, "16:00"), online_between(
    (at(MON, "10:00"), at(MON, "10:15")), (at(MON, "12:00"), at(MON, "12:20"))))
check("second offline period after a login -> second alert", a == [at(MON, "11:15"), at(MON, "13:20")], a)

# 5. offline since before 10:00 -> counting starts at 10:00
m, _ = new_monitor()
a = run(m, at(MON, "07:00"), at(MON, "12:00"), online_between((at(MON, "07:00"), at(MON, "08:00"))))
check("offline since 08:00 -> clock starts 10:00 -> alert 11:00", a == [at(MON, "11:00")], a)

# 6. never online all day (app never connected) -> alert 11:00
m, _ = new_monitor()
a = run(m, at(MON, "09:58"), at(MON, "19:30"))
check("nobody online all day -> one alert at 11:00", a == [at(MON, "11:00")], a)

# 7. window end: incident from 18:00 alerts at 19:00 (last possible)
m, _ = new_monitor()
a = run(m, at(MON, "17:00"), at(MON, "20:00"), online_between((at(MON, "17:00"), at(MON, "18:00"))))
check("offline from 18:00 -> alert at 19:00 (boundary included)", a == [at(MON, "19:00")], a)

# 8. incident from 18:30 -> no alert today, not carried to tomorrow's 10:00
m, _ = new_monitor()
tue = MON + timedelta(days=1)
a = run(m, at(MON, "18:00"), at(tue, "10:59"), online_between((at(MON, "18:00"), at(MON, "18:30"))))
check("offline from 18:30 -> no alert by 19:00, none at tomorrow 10:00-10:59", a == [], a)
a = run(m, at(tue, "10:59") + timedelta(seconds=30), at(tue, "11:30"))
check("...next day counts fresh from 10:00 -> alert 11:00", a == [at(tue, "11:00")], a)

# 9. Sunday IS monitored (counsellors work on Sundays); a day left out is skipped
check("default monitoring days include Sunday",
      [d[:3].lower() for d in config.SETTINGS.offline_alert_days]
      == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], config.SETTINGS.offline_alert_days)
m, _ = new_monitor()
a = run(m, at(SUN, "09:00"), at(SUN, "20:00"))
check("Sunday 10:00-19:00 monitored -> alert at 11:00", a == [at(SUN, "11:00")], a)
m, _ = new_monitor(days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
a = run(m, at(SUN, "09:00"), at(SUN, "20:00"))
check("a day removed from offline_alert_days is not monitored", a == [], a)
m, _ = new_monitor()
a = run(m, at(SAT, "09:00"), at(SAT, "12:00"))
check("Saturday is monitored", a == [at(SAT, "11:00")], a)

# 10. offline Saturday evening to Monday -> one alert Saturday? none (after 18:00), one Monday 11:00
m, _ = new_monitor()
a = run(m, at(SAT, "17:00"), at(MON + timedelta(days=7), "12:00"),
        online_between((at(SAT, "17:00"), at(SAT, "18:30"))), step=60)
check("Sat 18:30 -> Mon: Saturday evening never alerts; one alert per day, Sun 11:00 and Mon 11:00",
      a == [at(SUN, "11:00"), at(MON + timedelta(days=7), "11:00")], a)

# 11. restart after an alert, same incident -> no duplicate
meta = {}
m1, _ = new_monitor(meta)
run(m1, at(MON, "10:00"), at(MON, "10:20"), online_between((at(MON, "10:00"), at(MON, "10:10"))))
a1 = run(m1, at(MON, "10:20"), at(MON, "11:30"))
m2, _ = new_monitor(meta)                     # service restarted, same database
a2 = run(m2, at(MON, "11:31"), at(MON, "15:00"))
check("restart during an alerted incident -> no second e-mail", a1 == [at(MON, "11:10")] and a2 == [], (a1, a2))

# 12. service down / monitor blind: downtime does not count
meta = {}
m, _ = new_monitor(meta)
blind = online_between((at(MON, "10:00"), at(MON, "10:40")))   # monitor not ok 10:00-10:40
a = run(m, at(MON, "10:00"), at(MON, "12:00"), ok=lambda t: not blind(t))
check("blind period (startup grace / server down) never counts -> alert 11:40", a == [at(MON, "11:40")], a)

# 13. a blind blip mid-incident restarts the count (never alerts early)
m, _ = new_monitor()
a = run(m, at(MON, "10:00"), at(MON, "12:30"),
        ok=lambda t: not (at(MON, "10:50") <= t < at(MON, "10:52")))
check("monitor unhealthy mid-way -> counting restarts after it recovers", a == [at(MON, "11:52")], a)

# 14. exactness: alert never earlier than a full hour after the last online tick
m, _ = new_monitor()
last_online = at(MON, "10:30") - timedelta(seconds=30)
a = run(m, at(MON, "10:00"), at(MON, "12:00"), online_between((at(MON, "10:00"), at(MON, "10:30"))))
check("never alerts before a full hour has passed", a and a[0] - last_online >= timedelta(minutes=60), a)

# 15. status for /health
m, _ = new_monitor()
run(m, at(MON, "10:00"), at(MON, "10:20"))
st = m.status(at(MON, "10:20"))
check("status shows monitoring + offline-since", st["monitoring_now"] and st["all_offline_since"].endswith("10:00:00"), st)

# 16. e-mail content (rendered, not sent)
import json  # noqa: E402
import mailer  # noqa: E402
cj = Path(tempfile.mkdtemp()) / "counsellors.json"
cj.write_text(json.dumps({"intellibiadmin": [{"intellibi_admin_name": "Admin", "emailid": "info@x.com",
                                              "current_status": "Active"}]}))
config.SETTINGS.counsellors_json = str(cj)
captured = []
mailer._send = lambda r, subj, plain, html: captured.append((r, subj, plain, html)) or True
info = {"offline_since": at(MON, "10:30"), "now": at(MON, "11:30"),
        "presence": {"counsellors": [
            {"name": "Alpha", "email": "alpha@x.com", "state": "offline",
             "computers": [{"machine": "PC-A", "last_seen": "2026-10-05 10:29:40",
                            "last_disconnect_reason": "STALE (no heartbeat for 80s)"}]},
            {"name": "Bravo", "email": "bravo@x.com", "state": "not_registered", "computers": []}]},
        "network": {"ok": True, "summary": "counsellor computers can reach port 8787"},
        "leads": [{"received_at": "2026-10-05 10:45:00", "name": "Synthetic", "course": "SQL",
                   "status": "RECEIVED"}],
        "server_urls": ["http://192.168.1.202:8787"], "window": "every day 10:00-19:00",
        "after_minutes": 60}
ok = mailer.send_offline_hour_alert(info)
r, subj, plain, html = captured[-1]
check("e-mail goes to the configured info address", ok and r == ["info@x.com"], r)
check("subject says all offline for 1 h with start time",
      "All counsellors offline for 1 h 00 min" in subj and "10:30" in subj, subj)
check("body lists each counsellor with status, computer, last seen, reason",
      all(x in html for x in ("Alpha", "PC-A", "2026-10-05 10:29:40", "STALE", "Bravo",
                              "App not registered on this server")), "")
check("body lists leads received meanwhile", "Synthetic" in html and "1 (1 still waiting)" in html)
check("body states the monitoring rules", "every day 10:00-19:00" in html and "One e-mail per offline period" in html)
info["network"] = {"ok": False, "summary": "COUNSELLOR COMPUTERS CANNOT REACH THIS SERVER: ...",
                   "fix": "Fix-Firewall.bat"}
mailer.send_offline_hour_alert(info)
r, subj, plain, html = captured[-1]
check("server unreachable -> e-mail says server problem, not counsellors",
      "server not reachable" in subj and "CANNOT reach" in html and "Fix-Firewall.bat" in html, subj)
Path(tempfile.gettempdir(), "offline_alert_sample.html").write_text(captured[0][3], encoding="utf-8")

print()
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
print("ALL OFFLINE-ALERT TESTS PASSED")
