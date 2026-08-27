#!/usr/bin/env python3
"""
================================================================================
  IntelliBI Sales Automation — master pipeline launcher  (scripts/run_all.py)
  ------------------------------------------------------------------------------
  Runs the three layers in strict dependency order and stops safely if a
  critical upstream layer fails:

        Layer 1  sales_data_collection   (Interakt || Exotel Inbox -> Calls)
              |
              v
        Layer 2  sales_consolidation     (pyConsolidateLeadsLoad.py)   [critical]
              |
              v
        Layer 3  sales_reports           (performance + follow-up reports)

  * Layer 1's two flows run in parallel (see run_layer1.py).
  * Layer 2 is the dataset every report depends on: if it fails and
    pipeline.stop_on_failure is true (config.yaml), Layer 3 is skipped.
  * Layer 1 failures are logged prominently but do NOT block Layer 2/3, because
    consolidation reads the source Google Sheets live (the collectors only
    refresh them) — a stale-but-present dataset still yields reports.
  * On completion (success OR failure) a summary e-mail with each layer's log
    is sent to the recipients in config.yaml (email.log_recipients).

  Run:   python scripts/run_all.py
  Exit code 0 = every layer succeeded, 1 = something failed.
================================================================================
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap            # noqa: E402
import paths                 # noqa: E402
import logging_utils         # noqa: E402
import common_utils          # noqa: E402
import config_loader         # noqa: E402
import exec_summary          # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sibling runners
import run_layer1            # noqa: E402
import run_layer2            # noqa: E402
import run_layer3            # noqa: E402


def _skipped_layer(name, reason):
    return {"layer": name, "ok": False, "skipped": True,
            "scripts": [{
                "name": name, "label": name, "script": "", "status": "SKIPPED",
                "returncode": None, "started": "-", "ended": "-",
                "duration": "-", "counts": [reason], "log_file": "",
                "error": reason}]}


def main() -> int:
    log = logging_utils.get_logger("run_all")
    started = datetime.now()
    logging_utils.section(log, "IntelliBI Sales Automation — FULL PIPELINE START")

    stop_on_failure = bool(config_loader.get("pipeline.stop_on_failure", True))
    results = []

    # ── Layer 1 (parallel data collection) ───────────────────────────────────
    l1 = run_layer1.run(logger=logging_utils.get_logger("run_layer1"))
    results.append(l1)
    if not l1["ok"]:
        log.warning("Layer 1 had failures — continuing (consolidation reads the "
                    "source sheets live). See the summary for which collector failed.")

    # ── Layer 2 (critical) ───────────────────────────────────────────────────
    l2 = run_layer2.run(logger=logging_utils.get_logger("run_layer2"))
    results.append(l2)

    # ── Layer 3 (gated on Layer 2) ───────────────────────────────────────────
    if l2["ok"] or not stop_on_failure:
        if not l2["ok"]:
            log.warning("Layer 2 failed but stop_on_failure is false — running "
                        "Layer 3 anyway (reports may use the previous dataset).")
        l3 = run_layer3.run(logger=logging_utils.get_logger("run_layer3"))
    else:
        log.error("Layer 2 (consolidation) FAILED — skipping Layer 3 reports to "
                  "avoid publishing stale/incorrect numbers.")
        l3 = _skipped_layer("Layer 3 — Sales Reports",
                            "skipped: Layer 2 consolidation failed")
    results.append(l3)

    ended = datetime.now()
    overall_ok = all(layer["ok"] for layer in results)
    logging_utils.section(
        log, f"FULL PIPELINE {'SUCCESS' if overall_ok else 'FAILED'} in "
        f"{common_utils.fmt_duration((ended - started).total_seconds())}")

    # ── completion e-mail ────────────────────────────────────────────────────
    if config_loader.get("email.send_log_summary", True):
        recipients = config_loader.get(
            "email.log_recipients", ["info@intellibiinnovationstechnologies.in"])
        if isinstance(recipients, str):
            recipients = [recipients]
        attach = []
        if config_loader.get("email.attach_layer_logs", True):
            for layer in results:
                for r in layer["scripts"]:
                    lf = r.get("log_file")
                    if lf and os.path.exists(lf) and lf not in attach:
                        attach.append(lf)
        subject = (f"IntelliBI Sales Automation — {exec_summary.pipeline_status(results)}"
                   f" — {ended.strftime('%d-%b-%Y %H:%M')}")
        html = common_utils.build_summary_html(
            results, overall_ok,
            started.strftime("%Y-%m-%d %H:%M:%S"),
            ended.strftime("%Y-%m-%d %H:%M:%S"))
        common_utils.send_summary_email(subject, html, recipients, logger=log,
                                        attach_logs=attach)
    else:
        log.info("email.send_log_summary is false — no summary e-mail sent.")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
