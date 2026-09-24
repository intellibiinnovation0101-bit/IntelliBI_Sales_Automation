#!/usr/bin/env python3
"""
Entry point for the IntelliBI Counsellor App.

    python run.py                 # start the server (real Google Sheets)
    python run.py --fake          # start with an in-memory fake sheet (demo/offline)
    python run.py --check         # bootstrap only, print status, exit (health check)

Configuration is read from config.yaml + INTELLIBI_APP_* environment variables.
"""
from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from app.config import load_settings
from app.server import create_app


def _demo_gateway(settings):
    """A small, realistic in-memory sheet for --fake mode."""
    from app.fake_sheets import FakeGateway
    from app.domain import build_record
    seed = [
        build_record({"Full Name": "Asha Rao", "Email Address": "asha@example.com",
                      "Admission Status": "Interested", "Candidate Type": "Fresher",
                      "Course Interested In": "Data Science",
                      "Counselling By": "Demo Counsellor"}, "9876543210"),
        build_record({"Full Name": "Vikram Singh", "Email Address": "vikram@example.com",
                      "Admission Status": "In Progress", "Candidate Type": "Experienced",
                      "Course Interested In": "Full Stack",
                      "Counselling By": "Demo Counsellor"}, "9812345678"),
    ]
    return FakeGateway(active=seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="use an in-memory fake sheet")
    ap.add_argument("--check", action="store_true", help="bootstrap and exit")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port

    gateway = _demo_gateway(settings) if args.fake else None

    if args.check:
        app = create_app(settings=settings, gateway=gateway, start_worker=False)
        store = app.state.store
        print(f"OK — bootstrapped {store.count()} leads; "
              f"pending writes: {store.pending_count()}")
        store.close()
        return

    app = create_app(settings=settings, gateway=gateway, start_worker=True)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
