"""
"All counsellors offline for 1 hour" alert.

Rules (config: lead_alert.offline_alert_*):
  * Monitored days/hours: every day (Monday-Sunday), 10:00-19:00 (local time, to the
    minute, 19:00 included).
  * An alert is e-mailed to the escalation section (the configured "info"
    address) when NO counsellor has been online for a full hour, continuously,
    inside the monitoring window.
  * Offline periods shorter than the hour never alert.
  * The timer resets as soon as at least one counsellor is online.
  * One e-mail per continuous offline incident; after someone comes online and
    everyone is offline again for another full hour, a new alert is sent.

Boundary behaviour (defined explicitly):
  * Offline time only counts inside the window. Offline since before 10:00 ->
    counting starts at 10:00 -> alert at 11:00 if still nobody online.
  * An incident starting at 18:00 alerts at 19:00 (the last possible alert);
    one starting at 18:30 does not alert, and its 30 minutes are NOT carried
    over to the next day.
  * Each monitoring day starts fresh: counsellors offline from Saturday evening
    to Monday 11:00 produce one alert on Monday at 11:00.
  * Time while the service itself was not running or not able to see presence
    (start-up grace, presence sweeper not running) never counts — apps cannot
    connect to a server that is down, so that is not counsellor absence.
  * The incident is identified by "when was someone last online" (persisted),
    so a service restart during an already-alerted incident sends no second
    e-mail.

The decision logic is a pure state machine (OfflineMonitor.tick) driven by a
clock, so every rule above is unit-tested without waiting an hour.
"""
from __future__ import annotations

from datetime import datetime, timedelta

LAST_ONLINE_KEY = "offline_alert_last_online_ts"     # epoch seconds, persisted
ALERTED_KEY = "offline_alert_alerted_key"            # last incident alerted

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _hm(s: str) -> tuple:
    h, m = [int(x) for x in str(s).split(":")]
    return h, m


class OfflineMonitor:
    def __init__(self, days, start: str, end: str, after_minutes: float,
                 meta_get, meta_set):
        self.days = {_DAYS[d.strip().lower()[:3]] for d in days}
        self.start, self.end = _hm(start), _hm(end)
        self.after = timedelta(minutes=float(after_minutes))
        self.meta_get, self.meta_set = meta_get, meta_set
        self.monitor_ok_since = None      # datetime when presence became trustworthy
        self._last_saved = None
        self._seen_online_at = None       # last tick that saw someone online
        self.offline_since = None         # for /health

    # ── window ──────────────────────────────────────────────────────────────
    def window_start(self, now: datetime) -> datetime:
        return now.replace(hour=self.start[0], minute=self.start[1], second=0, microsecond=0)

    def window_end(self, now: datetime) -> datetime:
        return now.replace(hour=self.end[0], minute=self.end[1], second=59, microsecond=999999)

    def in_window(self, now: datetime) -> bool:
        return (now.weekday() in self.days
                and self.window_start(now) <= now <= self.window_end(now))

    # ── persisted "someone was online" marker ───────────────────────────────
    def _last_online(self):
        v = self.meta_get(LAST_ONLINE_KEY)
        try:
            return datetime.fromtimestamp(float(v)) if v else None
        except Exception:
            return None

    def _save_online(self, now: datetime, force: bool = False):
        if force or self._last_saved is None or now - self._last_saved >= timedelta(seconds=60):
            self.meta_set(LAST_ONLINE_KEY, now.timestamp())
            self._last_saved = now

    # ── the state machine ───────────────────────────────────────────────────
    def tick(self, now: datetime, any_online: bool, monitor_ok: bool):
        """Call every ~30 s. Returns an incident dict when the alert must be sent
        now (the caller sends it, then calls mark_alerted), else None."""
        if any_online:
            was_offline = self.offline_since is not None
            self._seen_online_at = now
            self._save_online(now, force=was_offline)
            self.offline_since = None
            return {"ended": True} if was_offline else None
        if self._seen_online_at is not None:
            # First tick that finds nobody online: the offline hour starts NOW.
            # (Counting from the last online tick could alert up to one tick
            # before a full hour; counting from here can only be a few seconds
            # late, never early.)
            self.meta_set(LAST_ONLINE_KEY, now.timestamp())
            self._last_saved = now
            self._seen_online_at = None
        if not monitor_ok:
            self.monitor_ok_since = None             # downtime / blind time never counts
            self.offline_since = None
            return None
        if self.monitor_ok_since is None:
            self.monitor_ok_since = now
        if not self.in_window(now):
            self.offline_since = None
            return None
        last_on = self._last_online()
        since = max(t for t in (last_on, self.window_start(now), self.monitor_ok_since) if t)
        self.offline_since = since
        if now - since < self.after:
            return None
        key = f"{now.date().isoformat()}|{last_on.timestamp() if last_on else 'never'}"
        if self.meta_get(ALERTED_KEY) == key:
            return None                               # this incident already alerted
        return {"key": key, "offline_since": since, "last_online": last_on, "now": now}

    def mark_alerted(self, key: str):
        self.meta_set(ALERTED_KEY, key)

    def status(self, now: datetime) -> dict:
        return {"monitoring_now": self.in_window(now),
                "all_offline_since": self.offline_since.strftime("%Y-%m-%d %H:%M:%S")
                if self.offline_since else "",
                "alert_after_minutes": int(self.after.total_seconds() // 60)}
