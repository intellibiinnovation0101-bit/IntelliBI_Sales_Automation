# pyLeadFollowUpAnalysisReport.py — Lead Follow-Up Analysis Report

**Layer 3 — Sales Reports** · `sales_reports/pyLeadFollowUpAnalysisReport.py`

## Purpose

Builds the **follow-up analysis report** (Daily / Weekly / Monthly): follow-up
pending/done, Google Meet & Walk-In scheduling and attendance, a per-counsellor
performance scorecard, one tab per counsellor, and a **Conversion Chance %**
score from a weight-of-evidence (naive-Bayes log-odds) model trained on lead
history. Uploads each report to Drive and e-mails it.

## Inputs

| Source | ID |
|--------|-----|
| Active + Inactive leads (Lead Information Result) | `RESULT_SHEET_ID = 1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw` |
| Master (Consolidate Sales Tracking) | `MASTER_SHEET_ID = 1zZQjXnMJD96Ca0MNyfSt4-XS0z5w3rT7WPdb9qsP1Gs` |
| Google Meet form responses | `MEET_SHEET_ID = 1dlWiU5K7kFi014p8pgH4PbMuoy4QbwMHh48YxNOqjpg` |
| Walk-In form responses | `WALKIN_SHEET_ID = 19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ` |
| Optional history | `intellibi_lead_cycle/` — past exports that enlarge model training (optional). |

## Output tabs

`Summary` · `Priority & Actions` · `Google Meet & Walk-In` · `Counsellor
Performance` · one tab **per counsellor** · `Conversion Model`.

| Target | Detail |
|--------|--------|
| Local file | `<name>.xlsx` in `output/reports/` (env `LFA_OUTPUT_DIR`). |
| Google Drive | Uploaded as a Google Sheet under `OUTPUT_PARENT_FOLDER_ID = 1UPsCa-i_KV_ynoRSRULNp6WbHOrwhCMJ`. |
| E-mail | Sent to `EMAIL_RECIPIENTS` via Gmail SMTP (`credentials/email_config.py`). |

## Configuration

Period toggles (in-script):

| Constant | Default | Meaning |
|----------|---------|---------|
| `GENERATE_DAILY` | `True` | Daily report. |
| `GENERATE_WEEKLY` | `True` | Weekly report. |
| `GENERATE_MONTHLY` | `True` | Monthly report. |
| `GENERATE_MANUAL` | `False` | Custom date range (`MANUAL_START_DATE`/`MANUAL_END_DATE`). |
| `DAILY_DATE` | e.g. `2026-08-22` | The "as-of" date for the daily report. |
| `SEND_EMAIL` | `True` | Send the report e-mail. |
| `MAX_FOLLOW_UPS` | `5` | Follow-up target per open lead. |
| `MAX_COUNSELLOR_TABS` | `40` | Cap on per-counsellor tabs. |

E-mail & masking: `EMAIL_RECIPIENTS`, `MASK_RECIPIENTS =
{"163manish.sharma@gmail.com"}` — restricted recipients get a masked copy + a
shared masked Drive file; others get the normal report.

Environment / `config.yaml`:

| Env var | config.yaml | Meaning |
|---------|-------------|---------|
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `google.service_account_file` | Service-account key. |
| `LFA_OUTPUT_DIR` | `reports.followup_output_dir` | Output folder (`output/reports`). |
| `LFA_HISTORY_DIR` | `reports.history_dir` | Historical training data (`intellibi_lead_cycle`). |
| `LFA_LOCAL_DIR` | — | Read all sources from local `.xlsx` (offline mode). |
| `LFA_DRY_RUN` | `reports.followup_dry_run` | `1` = build locally, no upload/e-mail. |

## Key logic (unchanged)

- **Conversion Chance %**: weight-of-evidence log-odds model with smoothing &
  shrinkage; priority bands anchored to the base conversion rate. Full factor
  weights are shown in the `Conversion Model` tab.
- **Counsellor Performance**: weighted score (Follow-Up 40%, Walk-In 25%, GMeet
  15%, Conversion 20%; N/A components re-weighted; 0% counted when scheduled=0),
  ranked, with dynamic "Doing Good / Area of Improvement" comments and colour
  coding.
- **Counsellor-name normalization**: casing/spacing variants merge to one
  canonical name (e.g. `Arshkhan Pathan` → `ArshKhan Pathan`) so each counsellor
  gets a single tab and merged metrics.
- **Google Meet & Walk-In**: scheduled records up to the report date only;
  attendance from the Meet form / Walk-In tab.

## How it runs

1. Train the conversion model on live master (+ optional history).
2. Read active/inactive leads, meet & walk-in forms.
3. For each enabled period, build the tabs and score leads.
4. Save to `output/reports/`, upload to Drive, and (if `SEND_EMAIL`) send normal
   + masked e-mails.

## Logging

Streamed to `logs/pyLeadFollowUpAnalysisReport.log` by the runner (model base
rate, leads scored, upload ids, e-mail status).

## Run standalone

```bat
python sales_reports\pyLeadFollowUpAnalysisReport.py
```

## Email Summary Metrics

The pipeline completion e-mail shows these business KPIs for this script (derived from the script's own run output — no business logic changed). Full technical detail stays in `logs/pyLeadFollowUpAnalysisReport.log`.

- **Reports generated** — count for the current run
- **Active leads scored** — count for the current run
- **E-mailed** — Yes/No — whether it was sent/uploaded this run

Zero-valued KPIs are omitted to keep the e-mail concise. The script's line in the e-mail is marked **SUCCESS / FAILED / SKIPPED**; on failure an **Action Required** row shows a short business reason + retry status.
