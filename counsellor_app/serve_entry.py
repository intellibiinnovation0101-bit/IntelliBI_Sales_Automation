#!/usr/bin/env python3
"""
Single entry point bundled into the Windows .exe (IntelliBICounsellorServer.exe).

Double-clicking the .exe (no arguments) starts the server. The same .exe also
does every admin task, so the office PC never needs Python installed:

    IntelliBICounsellorServer.exe                 start the server
    IntelliBICounsellorServer.exe serve --fake     start with the offline demo sheet
    IntelliBICounsellorServer.exe check            verify Google Sheet access, then exit
    IntelliBICounsellorServer.exe secret           print a new session secret
    IntelliBICounsellorServer.exe adduser <email> "<Name>" "<Counselling By>"
    IntelliBICounsellorServer.exe listusers        list configured counsellors
    IntelliBICounsellorServer.exe setup            create a starter config.yaml + folders

config.yaml, credentials/ and data/ live NEXT TO the .exe (see app.config.base_dir).
"""
from __future__ import annotations

import os
import sys


def _pause_if_windowed():
    """Keep the console window open when the .exe was double-clicked, so the
    person can read any message before it closes.

    NEVER pauses when running unattended (the auto-start watchdog sets
    INTELLIBI_NO_PAUSE=1): a background server must exit on error so it can be
    restarted, not sit forever waiting for a keypress nobody will make."""
    if os.environ.get("INTELLIBI_NO_PAUSE"):
        return
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except Exception:
            pass


def _ensure_dirs(base):
    for d in ("credentials", "data"):
        try:
            os.makedirs(os.path.join(base, d), exist_ok=True)
        except Exception:
            pass


def _first_run_setup(base, force=False):
    """Create a starter config.yaml (with a strong random secret) if none exists."""
    import secrets
    cfg_path = os.path.join(base, "config.yaml")
    _ensure_dirs(base)
    if os.path.exists(cfg_path) and not force:
        return cfg_path, False
    template = f"""# IntelliBI Counsellor App — configuration (auto-created)
# Edit this file, then restart the server.
data_sheet_id: "1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw"
active_tab: "IntelliBI Lead Information Active"
active_tab_aliases:
  - "IntelliBI Lead Information Result"
inactive_tab: "IntelliBI Lead Information InActive"
service_account_file: "credentials/service_account.json"

db_path: "data/store.db"
reconcile_seconds: 300
sync_batch_max: 50
sync_tick_seconds: 2.0

session_secret: "{secrets.token_urlsafe(48)}"
session_hours: 12

host: "0.0.0.0"
port: 8600

# Add counsellors with:  IntelliBICounsellorServer.exe adduser <email> "<Name>" "<Counselling By>"
counsellors: []
"""
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(template)
    return cfg_path, True


def _cmd_serve(argv):
    # reuse the same logic as run.py
    import argparse, logging
    import uvicorn
    from app.config import load_settings, base_dir
    from app.server import create_app

    ap = argparse.ArgumentParser(prog="serve")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)

    base = base_dir()
    cfg_path, created = _first_run_setup(base)
    if created:
        print("=" * 68)
        print(" First run — I created a starter config file:")
        print("   " + cfg_path)
        print(" Next steps before counsellors can log in:")
        print("   1) Put your Google service-account key at:")
        print("        " + os.path.join(base, "credentials", "service_account.json"))
        print("   2) Add at least one counsellor:")
        print('        IntelliBICounsellorServer.exe adduser <email> "<Name>" "<Counselling By>"')
        print(" Then run this server again. (Or run with  serve --fake  to try it offline.)")
        print("=" * 68)
        if not args.fake:
            _pause_if_windowed()
            return 0

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port

    gateway = None
    if args.fake:
        from app.fake_sheets import FakeGateway
        from app.domain import build_record
        gateway = FakeGateway(active=[
            build_record({"Full Name": "Asha Rao", "Admission Status": "Interested",
                          "Candidate Type": "Fresher"}, "9876543210"),
        ])

    try:
        app = create_app(settings=settings, gateway=gateway, start_worker=True)
    except Exception as e:  # noqa: BLE001
        print("\nCould not start — check config.yaml and the service-account key.")
        print("Error:", e)
        _pause_if_windowed()
        return 1

    url_host = "localhost" if settings.host in ("0.0.0.0", "") else settings.host
    print("\n" + "=" * 68)
    print(f"  IntelliBI Counsellor server is RUNNING on port {settings.port}")
    print(f"  On THIS PC:        http://localhost:{settings.port}/")
    print(f"  From counsellors:  http://<this-pc-ip>:{settings.port}/")
    print("  (find <this-pc-ip> with `ipconfig`; keep this window open)")
    print("  Health check:      http://localhost:%d/health" % settings.port)
    print("=" * 68 + "\n")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


def _cmd_check(argv):
    from app.config import load_settings
    from app.server import create_app
    settings = load_settings()
    try:
        app = create_app(settings=settings, gateway=None, start_worker=False)
        store = app.state.store
        if getattr(store, "booted_from_cache", False):
            # The server WOULD come up (from its local snapshot), but Google is
            # not reachable right now — report that honestly so `check` still
            # means "Google access is verified".
            print(f"WARNING — Google Sheets is NOT reachable right now. The server can "
                  f"still start from its local cache ({store.count()} leads) and will "
                  f"resync automatically, but check the internet link / sheet sharing.")
            rc = 1
        else:
            print(f"OK — connected. Cached {store.count()} leads; "
                  f"pending writes: {store.pending_count()}.")
            rc = 0
        store.close()
    except Exception as e:  # noqa: BLE001
        print("FAILED to connect:", e)
        rc = 1
    _pause_if_windowed()
    return rc


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    from app.config import base_dir
    base = base_dir()

    cmd = argv[0].lower() if argv else "serve"
    rest = argv[1:]

    if cmd in ("serve", "run", "start", "--fake"):
        # allow "IntelliBICounsellorServer.exe --fake"
        return _cmd_serve(argv if cmd == "--fake" else rest)
    if cmd == "check":
        return _cmd_check(rest)
    if cmd == "setup":
        path, created = _first_run_setup(base, force=False)
        print(("Created " if created else "Already exists: ") + path)
        _pause_if_windowed()
        return 0
    if cmd in ("secret", "adduser", "listusers", "list", "hash"):
        from app import manage_users
        mapped = {"listusers": "list", "adduser": "add"}.get(cmd, cmd)
        manage_users.main([mapped] + rest)
        _pause_if_windowed()
        return 0

    print(__doc__)
    _pause_if_windowed()
    return 2


if __name__ == "__main__":
    sys.exit(main())
