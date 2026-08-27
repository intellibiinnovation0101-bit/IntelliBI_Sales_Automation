# pyConsolidatedLeadPerformanceReport.py — Consolidated Lead Performance Report

**Layer 3 — Sales Reports** · `sales_reports/pyConsolidatedLeadPerformanceReport.py`

## Purpose

Builds the **consolidated sales-performance report** (Daily / Weekly / Monthly)
from the master lead dataset and the enrolled-students sheet, uploads it to the
matching Google Drive folder as a Google Sheet, and e-mails it. Covers lead
source share, course interest, conversion funnel, and related KPIs.

## Inputs

| Source | ID |
|--------|-----|
| Master (Consolidate Sales Tracking) | `MASTER_SHEET_ID = 1zZQjXnMJD96Ca0MNyfSt4-XS0z5w3rT7WPdb9qsP1Gs` |
| Enrolled students | `ENROLLED_SHEET_ID = 1oaXxg3JdtxFp8lFWijIMZKaMZvS0SiglI1K2JTrN2fs` |

## Outputs

| Target | Detail |
|--------|--------|
| Local file | `<name>.xlsx` in `output/reports/` (env `REPORT_OUTPUT_DIR`). |
| Google Drive | Uploaded as a Google Sheet into the period folder: `DAILY_FOLDER_ID = 1kuGgoyseH49tiEnwmKBgz8xceF5u7uJP`, `WEEKLY_FOLDER_ID = 1iUzEaoOS2ViCC7qH4W8Kj-DcXh3RQM_I`, `MONTHLY_FOLDER_ID = 1DICOV0iW5W2oIs7tKvsFfVUKlsfz4TxW`. |
| E-mail | Sent to `EMAIL_RECIPIENTS` via Gmail SMTP (`credentials/email_config.py`). |

## Configuration

Period toggles (in-script, top of file):

| Constant | Default | Meaning |
|----------|---------|---------|
| `GENERATE_DAILY_REPORT` | `True` | Build the daily report. |
| `GENERATE_WEEKLY_REPORT` | `False` | Build the weekly report. |
| `GENERATE_MONTHLY_REPORT` | `False` | Build the monthly report. |
| `WEEKLY_REPORT_REFERENCE_DATE` | `None` | Any day in the wanted week. |
| `MONTHLY_REPORT_MONTH` / `_YEAR` | `None` | Target month/year. |
| `SEND_EMAIL` | `True` | Send the report e-mail. |

E-mail & masking (in-script): `EMAIL_RECIPIENTS`, `MASK_RECIPIENTS =
{"163manish.sharma@gmail.com"}` — restricted recipients receive a **masked**
copy (mobile/email obfuscated) plus Editor access to a separate masked Drive
file; all other recipients get the normal report.

Environment / `config.yaml`:

| Env var | config.yaml | Meaning |
|---------|-------------|---------|
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `google.service_account_file` | Service-account key. |
| `REPORT_OUTPUT_DIR` | `reports.output_dir` | Output folder (`output/reports`). |
| `REPORT_DRY_RUN` | `reports.dry_run` | `1` = build locally, no upload/e-mail. |
| `REPORT_LOCAL_MASTER_CSV` | — | Read the master from a local CSV instead of Sheets. |

## How it runs

1. Read master + enrolled sheets (or local master CSV).
2. For each enabled period, compute the metrics and build the workbook tabs.
3. Save to `output/reports/`, upload to the period's Drive folder as a Google
   Sheet.
4. If `SEND_EMAIL`: send to normal recipients; send the masked variant + share
   the masked file with restricted recipients.

## Logging

Streamed to `logs/pyConsolidatedLeadPerformanceReport.log` by the runner (record
counts, upload ids, e-mail status).

## Notes

- Deeply-embedded settings (sheet IDs, folder IDs, `EMAIL_RECIPIENTS`, masking)
  live in the script by design and are mirrored in `config/config.yaml`'s
  reference block.
- Missing service account → the script exits early with a clear error; ensure
  `credentials/service_account.json` exists and the sheets/folders are shared
  with it.

## Run standalone

```bat
python sales_reports\pyConsolidatedLeadPerformanceReport.py
```

## Email Summary Metrics

The pipeline completion e-mail shows these business KPIs for this script (derived from the script's own run output — no business logic changed). Full technical detail stays in `logs/pyConsolidatedLeadPerformanceReport.log`.

- **Reports generated** — count for the current run
- **Master rows read** — volume handled this run (context, not a change count)
- **E-mailed** — Yes/No — whether it was sent/uploaded this run

Zero-valued KPIs are omitted to keep the e-mail concise. The script's line in the e-mail is marked **SUCCESS / FAILED / SKIPPED**; on failure an **Action Required** row shows a short business reason + retry status.
