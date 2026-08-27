# pyExotelCallDetails.py — Exotel Call Details Sync

**Layer 1 — Source Data Collection** · `sales_data_collection/pyExotelCallDetails.py`

## Purpose

Fetches **Exotel call records** (inbound/outbound call log), merges in the notes
and agent assignments captured by `pyExotelInboxScrape.py`, and upserts the
result into a Google Sheet. This is the **second half** of the Exotel flow and
depends on the inbox scraper having run first:

```
pyExotelInboxScrape.py  -->  pyExotelCallDetails.py
```

## Inputs

| Source | Access |
|--------|--------|
| Exotel API | `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_SID`, `EXOTEL_SUBDOMAIN` (env / `config.yaml`), else `credentials/exotel_credentials.json`. |
| Exotel web cookie | `credentials/exotel_web_cookie.txt` (via `exotel_common.load_cookie`). |
| Inbox notes/agents | `credentials/inbox_html/inbox_notes.json`, `inbox_agents.json` (from the scraper). |

## Output

| Target | Detail |
|--------|--------|
| Google Sheet | Spreadsheet `SPREADSHEET_ID = 1L-Ew4-GF7MzzAnnIhVBafOmN_DJlMBTaRI6048PUo4I`, tab **`Calls`**. |
| Upsert | `utils.upsert_rows()`, **keyed on `Sid`** (unique call id) → de-duplicated. |

This sheet is also the **Call** source read by Layer 2 consolidation.

## Configuration

In-script constants: `SPREADSHEET_ID`, `TAB_NAME` (`Calls`), `LOAD_MODE`,
`DATE_FROM`, `DATE_TO`, `STATUS_FILTER`.

Environment / `config.yaml`:

| Env var | config.yaml | Meaning |
|---------|-------------|---------|
| `EXOTEL_API_KEY` / `EXOTEL_API_TOKEN` / `EXOTEL_SID` / `EXOTEL_SUBDOMAIN` | `exotel.*` | API credentials. |
| `EXOTEL_LOAD_MODE` | `exotel.load_mode` | Fetch window / mode. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `google.service_account_file` | Service-account key. |

## Dependencies (project modules)

`utils` (Google auth + upsert), `exotel_common` (API + parsing), `exotel_session`
(headless auto-login for the web cookie).

## How it runs

1. Resolve API credentials (env → `exotel_credentials.json`).
2. Fetch the call records for the configured window/mode.
3. Merge in `inbox_notes.json` / `inbox_agents.json`.
4. `upsert_rows` into the `Calls` tab, keyed on `Sid`.

## Logging

`logs/exotel_call_sync.log` (+ console). Records calls fetched, notes merged,
rows upserted, and elapsed time.

## Notes & troubleshooting

- Company/virtual Exotel lines are handled downstream (Layer 2) so they never
  become leads.
- **Config/sheet error**: ensure the `Calls` sheet is shared with the service
  account and the Exotel credentials are valid.
- Run **after** `pyExotelInboxScrape.py` for the freshest notes; the runner does
  this automatically.

## Run standalone

```bat
python sales_data_collection\pyExotelCallDetails.py
```

## Email Summary Metrics

The pipeline completion e-mail shows these business KPIs for this script (derived from the script's own run output — no business logic changed). Full technical detail stays in `logs/pyExotelCallDetails.log`.

- **Calls fetched** — volume handled this run (context, not a change count)
- **Notes applied** — count for the current run
- **New** — count for the current run
- **Updated** — count for the current run
- **Unchanged** — already up to date / no change this run

Zero-valued KPIs are omitted to keep the e-mail concise. The script's line in the e-mail is marked **SUCCESS / FAILED / SKIPPED**; on failure an **Action Required** row shows a short business reason + retry status.
