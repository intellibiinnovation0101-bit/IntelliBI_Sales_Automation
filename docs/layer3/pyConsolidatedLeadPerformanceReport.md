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
| Google Ads remarketing audience (read-only) | `REMARKETING_SHEET_ID = 1uGR3ZTKjr5PgPxtUXHG_ABFPzF3KKT7W1BJ30xq8W0g` — "Google Ads Campaign Remarketing Leads Full Details", tab "Remarketing Audience" |

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

- **% Fresh Contribution** (Summary tab → Lead Source Performance and Counsellor
  Performance, right after `% Contribution`) = the row's `Fresh (New) Leads` ÷ total
  Fresh (New) Leads × 100. The total uses the same basis as that table's
  `% Contribution`: for sources, the four acquisition channels (Walk-In + Website +
  WhatsApp + Call) so the channel shares sum to ~100%; for counsellors, all fresh
  active leads. The per-counsellor tabs are unchanged.
- **Invalid phone ⇒ irrelevant**: right after the master sheet is read, every lead
  with `IsPhoneNumberValid = No` is treated as `IsLeadRelevant = No`
  (`common/lead_rules.apply_invalid_phone_irrelevance`). The master is normally
  already correct (Layer 2 applies the same rule); this guard keeps the report
  right even before the next consolidation run. All Relevant / Irrelevant /
  Fresh-Relevant counts, rates and detail rows use the adjusted value. The run
  log prints how many leads the guard changed.
- Deeply-embedded settings (sheet IDs, folder IDs, `EMAIL_RECIPIENTS`, masking)
  live in the script by design and are mirrored in `config/config.yaml`'s
  reference block.
- Missing service account → the script exits early with a clear error; ensure
  `credentials/service_account.json` exists and the sheets/folders are shared
  with it.

- 07-Oct-2026: a lead with no Counselling By whose `IsPhoneNumberValid` = No is grouped as **(Invalid number)** instead of **(Unassigned)** (counsellor table and tabs). Totals are unchanged; `(Unassigned)` now means a valid lead that nobody has worked.

## Repeat-Retargeting Leads (added 08-Oct-2026)

**What it shows.** A *Repeat-Retargeting Lead* is a **repeat lead of the reporting
period** (first enquiry before the period, enquired again in it — the same rule as
the "Repeat Leads" metric) whose mobile number is in the Google Ads remarketing
audience **and** who came back **inbound** in the period (rule below). Being in the audience means the lead **could have been influenced** by our
retargeting ads; it is **not** confirmed ad attribution (Google Ads does not tell us
which lead saw or clicked an ad).

**Inbound rule (added 08-Oct-2026).** At least one of the lead's interactions
**inside the reporting period** (from *Lead Interaction History*, the same
in-period interactions the Lead Source Performance table counts) must be from a
platform other than **IntelliBI** — Website, WhatsApp, Call, Walk-In, etc.
IntelliBI entries are outbound counsellor follow-ups, so a repeat lead whose
in-period interactions are **only** IntelliBI is not counted (IsRetargetingLead
blank), even when it is in the audience. Only the period's own interactions are
checked — an inbound enquiry before the period does not qualify. IntelliBI is
recognised in any spelling (`IntelliBI`, `intellibi`, `Intelli BI`, `Intelli-BI`).
An interaction with a blank platform cannot be confirmed as inbound and does not
qualify on its own. The lead stays a Repeat Lead either way; only the
retargeting flag and counts change.

| In-period interactions of a repeat lead in the audience | IsRetargetingLead |
|---|---|
| Website / WhatsApp / Call / Walk-In (any of them) | Yes |
| IntelliBI and an inbound platform | Yes |
| IntelliBI only | blank |

**Where it appears.**

| Tab | Change |
|-----|--------|
| Summary → Executive Summary | New row **Repeat-Retargeting Leads**, directly below *Total Lead Interactions*; % = of Total Leads, like the other rows. |
| Repeat Lead Details | Header line: **Total Repeat Leads** · **Repeat-Retargeting Leads** (count and % of repeat leads) · time the audience was last updated. New column **IsRetargetingLead** right after *Walk-in Sch.*: `Yes` = in the audience with an in-period inbound interaction, blank = not. |
| Counsellor tabs (CB - …) → Repeat Lead Details section | Same **IsRetargetingLead** column; the section title adds that counsellor's **Repeat-Retargeting Leads** count. |

Same for Daily, Weekly, Monthly and Manual, and for the masked copy. Fresh Lead
Details, the Fresh sections and Executive Summaries of the counsellor tabs, and the
e-mail are unchanged.

**Reconciliation.** Total Repeat Leads = Executive Summary *Repeat Leads* = rows in
Repeat Lead Details. Repeat-Retargeting Leads (Summary) = the header figure = the
number of `Yes` rows in *IsRetargetingLead* = the sum of the counsellor tabs'
Repeat-Retargeting counts (when every counsellor has a tab, i.e. at most
`MAX_COUNSELLOR_TABS`). Each lead row is counted once.

**Data source.** `google_ads_campaign_remarketing/pyGoogleAdsRemarketingAudience.py`
rebuilds the sheet as the first step of Sales Layer 3, right before this report.
The report reads it once per run (read-only, the same impersonated Drive-scope
access the remarketing script writes with; falls back to the service account) by
`REMARKETING_SHEET_ID`, or by name in the "Manish Leads" folder if that id cannot be
read. Phones are matched on both the *Google Ads Phone* and *Mobile Number* columns
using this report's `norm_phone()` (last 10 digits) — the same key used for the
enrolled-student exclusion.

**When the audience cannot be read** (sheet missing / not shared, Google error,
unrecognised layout, or an empty audience — the remarketing script never publishes
an empty one): the report still runs; the Summary shows **Not available**, the
Repeat tab header and the counsellor Repeat titles say *Not available*, and
every *IsRetargetingLead* cell is **N/A** — leads are never reported as "not
retargeted" by mistake. The log line starts with `[remarketing]`. If the
remarketing refresh itself fails, its last good audience stays in the sheet and is
used.

**Limits.** The audience is a rolling 40-day list of relevant, not-enrolled,
not-"Not Interested" leads as of the latest refresh. For a back-dated or long
period (an old `DAILY_REPORT_DATE`, a past month, a Manual range) the flags reflect
**today's** audience, not the audience on the day the lead returned.

Settings (top of the script): `REMARKETING_CHECK` (False = show Not available),
`REMARKETING_SHEET_ID`, `REMARKETING_FOLDER_ID`, `REMARKETING_SHEET_NAME`,
`REMARKETING_TAB_NAME`, `REMARKETING_PHONE_HEADERS`. Offline test runs can pass a CSV
export of the tab with env `REPORT_LOCAL_REMARKETING_CSV`.

Verification (no Google access, synthetic data):
`python sales_validation\verify_repeat_retargeting.py`.

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
