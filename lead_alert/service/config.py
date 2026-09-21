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
