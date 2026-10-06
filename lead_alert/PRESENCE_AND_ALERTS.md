# Lead Alert — presence, reachability and offline alerts

## 2026-10-06 incident: "status ok, 0 counsellors online, nobody gets popups"

**Root cause.** The office PC (server, `192.168.1.202`) was on Wi-Fi **"Classroom 5G 3"**, which Windows classified as **Public**. The only firewall rule opening TCP 8787 (**"IntelliBI Lead Alert 8787"**) was created by `deploy/Setup-Server.bat` with `profile=private`. So Windows dropped every connection from counsellor PCs. `http://localhost:8787/health` still answered, because traffic from a PC to itself is never filtered.

Nothing in the system could see this:

- Presence was "a socket is in memory right now".
- The counsellor app retried silently with no message.
- The server logged nothing useful.
- On the dell's copy of the service, 105 leads were recorded, all UNACKNOWLEDGED, with 0 delivered.

## What prevents it now

| Failure | Detection | Automatic recovery | Who is told |
|---|---|---|---|
| Firewall blocks counsellor PCs (any network type) | `service/netcheck.py`: at start, every 10 min, and immediately when the PC's IP addresses change | Service (runs as SYSTEM) recreates the rules for **all** network types, local/private addresses only | `/health` → `network`, server log `[netcheck]`, offline e-mail says *server not reachable* |
| Office PC gets a new IP / joins another network | App cannot reach its saved address | App broadcasts on the LAN (UDP 8788); the server answers with an HMAC proof using that computer's token; the app saves the new address and connects | client.log, server log `[discovery]` |
| Laptop sleeps / Wi-Fi drops (half-open socket) | Server: no heartbeat for 75 s → STALE; app: no reply for 70 s | Server closes the connection; the app reconnects with backoff 2→30 s | `/health` → `presence`, server log `[presence] OFFLINE … STALE` |
| Computer not registered on this server / counsellor Inactive | Server refuses with a reason (AUTH_FAILED) | App asks "Re-register now?" (at most every 30 min) | red tray icon, client.log, `/health` → `recent_refused_connections` |
| App can't connect for 2 minutes | App watchdog | Keeps retrying | Counsellor sees an "alerts are OFF" window; tray icon turns red |
| Server restarted / app restarted | — | Apps reconnect; every lead still open pops up again (resync) | — |
| Two PCs running the service | `lead_alert.server_machine` | Other PCs run as STANDBY (no polling, no e-mails) | `/health` → `server.role` |

**Presence states** (`/health` → `presence.counsellors[].state`):

- **online:** connected, with a heartbeat within 75 s.
- **stale:** connected but silent; it is closed within about 15 s.
- **offline:** registered computer, not connected; `last_seen` and `last_disconnect_reason` are shown.
- **not_registered:** no computer registered on this server.

`online_counsellors` lists only **online** counsellors.

## "All counsellors offline for 1 hour" e-mail

The e-mail goes to the Active members of `offline_alert_section` (default `intellibiadmin`, which is info@…).

**Rules:**

- Monitoring runs **every day (Mon–Sun), 10:00–19:00**. Only offline time inside that window counts. The 19:00 minute is included.
- The alert is sent once **no counsellor has been online for 60 continuous minutes**. Shorter periods never alert.
- The timer **resets** as soon as one counsellor is online.
- **One e-mail per offline period.** After someone comes online, a new full hour offline sends a new alert.

**Boundaries:**

- **Offline before 10:00:** the clock starts at 10:00, so the alert goes at 11:00.
- **Near closing time:** an incident starting at 18:00 alerts at 19:00, the last possible alert. One starting at 18:30 never alerts, and nothing carries over to the next day.
- **Each day starts fresh.** Offline from Saturday 18:30 to Sunday gives one alert, Sunday at 11:00 (Sundays are monitored; any day can be removed via `offline_alert_days`).
- **Downtime doesn't count.** Time while the service was down or blind (2-minute start-up grace, presence sweeper not running) is never counted as counsellor absence.
- **Restarts don't duplicate.** A restart during an already-alerted period sends no second e-mail; the incident is identified by "when someone was last online", which is stored in the database.
- **Precision:** the hour starts at the first 30-second check that finds nobody online, so an alert can be a few seconds late but never early.

**E-mail contents:**

- When everyone went offline, and the alert time.
- How many website leads arrived since then, and how many are still waiting.
- The server self-check verdict and the server address.
- Each counsellor's status (offline / connection lost / not registered), computer, last seen and last disconnect reason.
- The leads received meanwhile, with their status.
- What to do.

If the self-check says the server is not reachable, the subject and text say it's a **server problem**, not the counsellors.

## Settings (`config/config.yaml` → `lead_alert`)

| Key | Default | Meaning |
|---|---|---|
| `heartbeat_stale_seconds` | 75 | silent this long → stale (app PINGs every 25 s) |
| `presence_sweep_seconds` | 15 | how often stale connections are closed |
| `startup_grace_seconds` | 120 | no offline counting right after a (re)start |
| `offline_alert_enabled` | true | 1-hour offline e-mail |
| `offline_alert_days` / `_from` / `_to` | Mon–Sun, 10:00, 19:00 | monitoring window |
| `offline_alert_after_minutes` | 60 | continuous offline time before the e-mail |
| `offline_alert_section` | intellibiadmin | counsellors.json section that receives it |
| `netcheck_minutes` | 10 | firewall self-check interval (also runs on every network change) |
| `auto_fix_firewall` | true | let the service repair its own firewall rules |
| `discovery_port` | 8788 | UDP port for LAN discovery |
| `server_machine` | "" | office PC's computer name; any other PC runs as STANDBY |
| `no_online_alert` | false | optional extra e-mail per waiting lead when nobody is online |

## Tests (synthetic data only)

```
python lead_alert/tests/test_presence.py       # real uvicorn + real app client over TCP
python lead_alert/tests/test_offline_alert.py  # every 1-hour rule and boundary, simulated clock
python lead_alert/tests/test_core.py
python lead_alert/tests/test_app_integration.py
```

## Logs

- **Server:** `logs/lead_alert_service.log`, with tags `[presence]`, `[netcheck]`, `[discovery]`, `[offline-alert]`, `[dispatch]` and `[resync]`. Tokens are redacted.
- **Counsellor PC:** `%APPDATA%\IntelliBILeadAlert\client.log`.
