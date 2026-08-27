#!/usr/bin/env python3
"""
Layer 2 — Lead Consolidation.

Consolidates the four sources into the single source-of-truth dataset used by
the Layer 3 reports:

    pyConsolidateLeadsLoad.py

Run standalone:   python scripts/run_layer2.py
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap            # noqa: E402
import paths                 # noqa: E402
import logging_utils         # noqa: E402
import common_utils          # noqa: E402
import config_loader         # noqa: E402

LAYER = "Layer 2 — Lead Consolidation"


def _timeout():
    t = config_loader.get("pipeline.script_timeout_seconds", "")
    try:
        return int(t) if str(t).strip() else None
    except (TypeError, ValueError):
        return None


def run(logger=None) -> dict:
    log = logger or logging_utils.get_logger("run_layer2")
    logging_utils.section(log, f"{LAYER}: starting")
    script = paths.LAYER2_DIR / "pyConsolidateLeadsLoad.py"
    r = common_utils.run_script(script, label="Consolidate Leads Load",
                                timeout=_timeout())
    ok = r["status"] == "SUCCESS"
    log.info("%s: %s", LAYER, "SUCCESS" if ok else "FAILED")
    return {"layer": LAYER, "ok": ok, "scripts": [r]}


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["ok"] else 1)
