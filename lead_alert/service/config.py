"""
IntelliBI Website Lead Alert — service configuration.

Reuses the existing project conventions:
  * common/paths.py           -> PROJECT_ROOT, CONFIG_DIR, CREDENTIALS_DIR
  * common/config_loader.py   -> config/config.yaml  (the `lead_alert:` block)
  * credentials/service_account.json  -> Google Sheets read/write
  * credentials/email_config.py       -> SMTP (escalation email)
  * credentials/lead_alert_secrets.py -> ENROLLMENT_CODE (device enrollment)

Nothing machine-specific is hard-coded; every path is derived from the project
root, so the folder stays portable exactly like the rest of the pipeline.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── make the project's common/ importable (same bootstrap the scripts use) ────
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]                     # lead_alert/service -> project root
_COMMON = _PROJECT_ROOT / "common"
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))

import paths            # noqa: E402  (from common/)
import config_loader    # noqa: E402  (from common/)

PROJECT_ROOT = paths.PROJECT_ROOT
CONFIG_DIR = paths.CONFIG_DIR
CREDENTIALS_DIR = paths.CREDENTIALS_DIR

# Data / log folders for the alert service (auto-created, git-ignored).
DATA_DIR = PROJECT_ROOT / "lead_alert" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "lead_alert.db"

SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    str(CREDENTIALS_DIR / "service_account.json"))
READ_WRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _c(key, default):
    """Read lead_alert.<key> from config.yaml, falling back to `default`."""
    val = config_loader.get(f"lead_alert.{key}", None)
    return default if val is None or val == "" else val


class Settings:
    """Resolved settings for one run (read once at service start)."""

    def __init__(self):
        self.enabled = bool(_c("enabled", True))
        self.host = str(_c("host", "0.0.0.0"))
        self.port = int(_c("port", 8787))

        # Source: the Google Sheet the Apps Script fills on every submission.
        self.source_sheet_id = str(_c("source_sheet_id",
                                      "1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE"))
        self.source_tab = str(_c("source_tab", "Contact Us Form"))
        self.poll_seconds = int(_c("poll_seconds", 20))

        # Audit / metrics mirror (optional). Blank id -> mirror disabled.
        self.log_sheet_id = str(_c("log_sheet_id", "")).strip()
        self.log_tab = str(_c("log_tab", "Website Lead Alert Log"))

        # Which counsellors.json sections get alerted (order preserved).
        secs = _c("alert_sections", ["counsellors"])
        self.alert_sections = list(secs) if isinstance(secs, (list, tuple)) else [str(secs)]

        # Escalation (minutes) + who receives the escalation email.
        self.realert_after_min = float(_c("realert_after_min", 3))
        self.escalate_after_min = float(_c("escalate_after_min", 8))
        self.expire_after_min = float(_c("expire_after_min", 30))
        self.escalate_to_section = str(_c("escalate_to_section", "intellibiadmin"))

        # Operating window (local clock). Outside it the poller idles.
        self.active_from = str(_c("active_from", "09:30"))
        self.active_to = str(_c("active_to", "23:00"))
        # ── Presence (who is online) ─────────────────────────────────────────
        # A counsellor is ONLINE only while their app has an open connection AND
        # has sent something (the app PINGs every 25 s) within this many seconds.
        # Silent connections (sleeping laptop, dropped Wi-Fi) become STALE, are
        # closed by the sweeper, and the app reconnects by itself.
        self.heartbeat_stale_seconds = int(_c("heartbeat_stale_seconds", 75))
        self.presence_sweep_seconds = int(_c("presence_sweep_seconds", 15))
        # After a (re)start, apps need a moment to reconnect: no "nobody online"
        # alert is sent during this window.
        self.startup_grace_seconds = int(_c("startup_grace_seconds", 120))
        # OPTIONAL per-lead e-mail when a lead cannot be shown to ANYONE because
        # no counsellor is online (off by default: the 1-hour offline alert below
        # and the existing unacknowledged-lead escalation already cover it).
        self.no_online_alert = bool(_c("no_online_alert", False))
        self.no_online_alert_cooldown_min = float(_c("no_online_alert_cooldown_min", 30))
        # A lead must have waited this long with nobody online before alerting
        # (rides out a momentary reconnect).
        self.no_online_alert_after_seconds = int(_c("no_online_alert_after_seconds", 60))
        # "All counsellors offline for 1 hour" e-mail (see offline_monitor.py).
        self.offline_alert_enabled = bool(_c("offline_alert_enabled", True))
        days = _c("offline_alert_days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self.offline_alert_days = list(days) if isinstance(days, (list, tuple)) else \
            [d.strip() for d in str(days).split(",")]
        self.offline_alert_from = str(_c("offline_alert_from", "10:00"))
        self.offline_alert_to = str(_c("offline_alert_to", "19:00"))
        self.offline_alert_after_minutes = float(_c("offline_alert_after_minutes", 60))
        self.offline_alert_section = str(_c("offline_alert_section", "intellibiadmin"))
        # Windows firewall / network self-check (detects "counsellor PCs cannot
        # reach this server"); minutes between checks.
        self.netcheck_minutes = float(_c("netcheck_minutes", 10))
        # Repair the Windows firewall rules automatically when the self-check
        # finds them missing/wrong (the service runs as SYSTEM). Keeps counsellor
        # PCs able to connect whatever network the office PC joins.
        self.auto_fix_firewall = bool(_c("auto_fix_firewall", True))
        # UDP port for LAN discovery (apps find the server after an IP change).
        self.discovery_port = int(_c("discovery_port", 8788))
        # Which computer is THE server (its Windows computer name). When set,
        # any other computer that starts the service runs as STANDBY: it does
        # not poll the sheet or send e-mails, so two PCs never double-process.
        self.server_machine = str(_c("server_machine", "")).strip()

        # Links the popup can open.
        self.open_email_url = str(_c("open_email_url",
                                     "https://mail.google.com/mail/u/0/#search/"))
        self.lead_sheet_url = str(_c(
            "lead_sheet_url",
            "https://docs.google.com/spreadsheets/d/" + self.source_sheet_id))

        self.counsellors_json = str(CONFIG_DIR / "counsellors.json")

    def enrollment_code(self) -> str:
        """Shared one-time code a counsellor types when registering a device.
        Read from credentials/lead_alert_secrets.py (never committed)."""
        try:
            sys.path.insert(0, str(CREDENTIALS_DIR))
            import lead_alert_secrets  # type: ignore
            return str(getattr(lead_alert_secrets, "ENROLLMENT_CODE", "")).strip()
        except Exception:
            return ""


SETTINGS = Settings()
