#!/usr/bin/env python3
"""
Layer 3 — Sales Reports.

Refreshes the Google Ads remarketing audience from the freshly consolidated
Layer 2 master, then generates the consolidated sales-performance and
follow-up-analysis reports:

    google_ads_campaign_remarketing/pyGoogleAdsRemarketingAudience.py
    pyConsolidatedLeadPerformanceReport.py
    pyLeadFollowUpAnalysisReport.py

The remarketing audience runs FIRST because the performance report reads its
Full Details sheet for "Repeat-Retargeting Leads". run_script() waits for each
step to finish before the next starts. If the audience refresh fails, the
reports still run: the remarketing script keeps the last good audience, and the
performance report shows the metric as "Not available" only when the sheet
itself cannot be read. Steps run sequentially so their logs stay clean and they
don't contend on the Google API. Run standalone:

    python scripts/run_layer3.py
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

LAYER = "Layer 3 — Sales Reports"


def _timeout():
    t = config_loader.get("pipeline.script_timeout_seconds", "")
    try:
        return int(t) if str(t).strip() else None
    except (TypeError, ValueError):
        return None


def run(logger=None) -> dict:
    log = logger or logging_utils.get_logger("run_layer3")
    logging_utils.section(log, f"{LAYER}: starting")
    timeout = _timeout()
    perf = paths.LAYER3_DIR / "pyConsolidatedLeadPerformanceReport.py"
    follow = paths.LAYER3_DIR / "pyLeadFollowUpAnalysisReport.py"
    remarketing = (paths.PROJECT_ROOT / "google_ads_campaign_remarketing"
                   / "pyGoogleAdsRemarketingAudience.py")
    scripts = [
        # Google Ads remarketing audience FIRST — full refresh of the production
        # phone sheet + the Full Details sheet (on any problem it keeps the last
        # audience). The performance report below reads the Full Details sheet for
        # "Repeat-Retargeting Leads", so it must run after this step completes.
        common_utils.run_script(remarketing, label="Google Ads Remarketing Audience",
                                timeout=timeout),
        common_utils.run_script(perf, label="Consolidated Lead Performance Report",
                                timeout=timeout),
        common_utils.run_script(follow, label="Lead Follow-Up Analysis Report",
                                timeout=timeout),
    ]
    ok = all(r["status"] == "SUCCESS" for r in scripts)
    log.info("%s: %s", LAYER, "SUCCESS" if ok else "one or more reports FAILED")
    return {"layer": LAYER, "ok": ok, "scripts": scripts}


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["ok"] else 1)
