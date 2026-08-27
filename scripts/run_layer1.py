#!/usr/bin/env python3
"""
Layer 1 — Source Data Collection.

Collects raw sales/communication data from Interakt and Exotel.  Two independent
flows run in PARALLEL:

    Flow A:  pyInteraktUsers.py
    Flow B:  pyExotelInboxScrape.py  ->  pyExotelCallDetails.py   (sequential)

Run standalone:   python scripts/run_layer1.py
Or via run_all.py (imported as a module).
"""
import os
import sys

# ── portable bootstrap: put common/ on the path, seed env + config ───────────
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap            # noqa: E402
import paths                 # noqa: E402
import logging_utils         # noqa: E402
import common_utils          # noqa: E402
import config_loader         # noqa: E402

LAYER = "Layer 1 — Data Collection"


def _timeout():
    t = config_loader.get("pipeline.script_timeout_seconds", "")
    try:
        return int(t) if str(t).strip() else None
    except (TypeError, ValueError):
        return None


def run(logger=None) -> dict:
    log = logger or logging_utils.get_logger("run_layer1")
    logging_utils.section(log, f"{LAYER}: starting two parallel flows")
    timeout = _timeout()
    l1 = paths.LAYER1_DIR
    interakt = l1 / "pyInteraktUsers.py"
    inbox = l1 / "pyExotelInboxScrape.py"
    calls = l1 / "pyExotelCallDetails.py"

    def interakt_flow():
        return [common_utils.run_script(interakt, label="Interakt Users",
                                        timeout=timeout)]

    def exotel_flow():
        r1 = common_utils.run_script(inbox, label="Exotel Inbox Scrape",
                                     timeout=timeout)
        if r1["status"] != "SUCCESS":
            log.warning("Exotel inbox scrape did not succeed; call-details will "
                        "run on the existing cookie/notes (degraded).")
        r2 = common_utils.run_script(calls, label="Exotel Call Details",
                                     timeout=timeout)
        return [r1, r2]

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(interakt_flow)
        fb = ex.submit(exotel_flow)
        scripts = fa.result() + fb.result()

    ok = all(r["status"] == "SUCCESS" for r in scripts)
    log.info("%s: %s", LAYER, "SUCCESS" if ok else "one or more collectors FAILED")
    return {"layer": LAYER, "ok": ok, "scripts": scripts}


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["ok"] else 1)
