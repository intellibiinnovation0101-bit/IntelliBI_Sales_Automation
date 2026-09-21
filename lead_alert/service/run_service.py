"""
Launch the IntelliBI Website Lead Alert service.

Run from the project root (or anywhere — paths self-resolve):

    .venv\\Scripts\\python.exe lead_alert\\service\\run_service.py

Binds to lead_alert.host:port from config/config.yaml (default 0.0.0.0:8787) so
counsellor machines on the office LAN can connect. The poller + escalation loops
start automatically (see app.lifespan).
"""
from __future__ import annotations

import os
import sys

# Make this folder importable as a flat module set, and load the project config.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config          # noqa: E402  (sets up common/ on sys.path, reads config.yaml)


def main():
    import uvicorn
    s = config.SETTINGS
    print("=" * 68)
    print(" IntelliBI Website Lead Alert service")
    print(f"   bind        : {s.host}:{s.port}")
    print(f"   source sheet: {s.source_tab}  (poll {s.poll_seconds}s)")
    print(f"   alert to    : {', '.join(s.alert_sections)} (Active only)")
    print(f"   window      : {s.active_from}-{s.active_to}")
    print(f"   escalate    : re-alert {s.realert_after_min}m / email "
          f"{s.escalate_after_min}m -> {s.escalate_to_section} / expire "
          f"{s.expire_after_min}m")
    print("=" * 68)
    uvicorn.run("app:app", host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
