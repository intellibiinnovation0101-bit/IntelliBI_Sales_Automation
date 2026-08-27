# intellibi_lead_cycle/ — optional historical training data

The follow-up report (`sales_reports/pyLeadFollowUpAnalysisReport.py`) trains its
conversion-chance model on the **live** master sheet, and *optionally* enlarges
that training with past exports found in this folder (`*Consolidate*Sales*Tracking*.xlsx`
and similar).

This folder is **optional**. Leave it empty and the report still runs — it just
trains on live data only, exactly as on a fresh machine. To improve the model,
drop historical `.xlsx` exports here (git-ignored). Override the location with
`reports.history_dir` in `config/config.yaml` or the `LFA_HISTORY_DIR` env var.
