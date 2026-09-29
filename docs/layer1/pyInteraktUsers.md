# pyInteraktUsers.py — Interakt WhatsApp Users Sync

**Layer 1 — Source Data Collection** · `sales_data_collection/pyInteraktUsers.py`

## Purpose

Pulls the WhatsApp contact/user list from **Interakt** and upserts it into a
Google Sheet, so the WhatsApp source is fresh before consolidation. Optionally
**enriches** each contact (conversation label → assigned agent / owner) from the
Interakt inbox.

## Inputs

| Source | Access |
|--------|--------|
| Interakt API | API key in `credentials/interakt_credentials.json` (`{"api_key": "..."}`), or env `INTERAKT_API_KEY`. |
| Interakt web session | `credentials/interakt_curl.txt` — a "Copy as cURL (bash)" paste of a logged-in inbox request; the enricher reads the auth headers from it. Auto-refreshed via the Playwright profile when expired. |

## Output

| Target | Detail |
|--------|--------|
| Google Sheet | Spreadsheet **`Interakt_WhatsApp_Data`**, tab **`Users`**, in Drive folder `DRIVE_FOLDER_ID = 1_1d6ExCX9apj8QkMczTJZn1Ctprwf3CM`. Created if missing (`interakt_common.get_or_create_spreadsheet`). |
| Upsert | `utils.upsert_rows()` — upsert-by-key with automatic column re-alignment (no duplicate rows, resilient to column order changes). |

The cached spreadsheet id is stored in `credentials/interakt_spreadsheet.json`;
the last successful enrichment marker in `credentials/interakt_enrich_last_ok.txt`.

## Configuration

In-script constants (top of file): `DRIVE_FOLDER_ID`, `SPREADSHEET_NAME`
(`Interakt_WhatsApp_Data`), `TAB_NAME` (`Users`), `LOAD_MODE` (`full` |
`incremental`).

Environment / `config.yaml` overrides:

| Env var | config.yaml | Meaning |
|---------|-------------|---------|
| `INTERAKT_API_KEY` | `interakt.api_key` | API key (blank → use web session). |
| `INTERAKT_LOAD_MODE` | `interakt.load_mode` | `full` or `incremental`. |
| `INTERAKT_ENRICH` | — | Toggle inbox enrichment. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `google.service_account_file` | Service-account key (default `credentials/service_account.json`). |

## Dependencies (project modules)

`utils` (Google auth + upsert), `interakt_common` (spreadsheet create/lookup),
`interakt_enrich` (inbox enrichment), `interakt_session` (headless auto-login,
optional).

## How it runs

1. Resolve auth (API key or web-session cURL).
2. Fetch the Interakt users/contacts (all pages).
3. Optionally enrich with conversation-label → agent/owner mapping.
4. `get_or_create_spreadsheet` → resolve the target sheet id.
5. `upsert_rows` into the `Users` tab, keyed on the contact key.

## Logging

`logs/interakt_sync.log` (+ console). Records fetched/enriched/upserted counts,
auto-login refreshes, and errors.

## Troubleshooting

- **401 / expired session**: refresh `credentials/interakt_curl.txt` from a new
  "Copy as cURL", or run the one-time headful Playwright login so the profile
  can auto-refresh it.
- **Sheet not found / permission**: the target Drive folder and sheet must be
  shared with the service account (`intellibi-data-pipeline@intellibi-mis.iam.gserviceaccount.com`).
- **Assigned Agent / Conversation Label / enr_contact_owner blank** (fixed
  29-Sep-2026). These come from the web session, not the public Get-Users API:
  label + agent from the Inbox chats list (ids resolved through the
  `/conversation-labels/` and `/members/` lookups), contact owner from the
  `_internal_contact_owner_id` trait. Three defects used to empty them:
  (1) on an *enriched* run the sheet values were **not** preserved, so every
  contact missing from that run's chats map (no chat, or a view/endpoint that
  returned nothing) was written blank; (2) a failed `/members/` lookup made
  the resolver fall back to the raw UUID (that is the `dcc0e033-…` text seen in
  `enr_contact_owner`) and an unknown label id became a blank; (3) the public
  API carries `_internal_contact_owner_id` for only a handful of contacts, and
  the customer detail record — which has it for all — was read only for the
  custom fields. Now: `preserve_web_columns()` runs on every run (an enriched
  run keeps a web column the source had nothing for, and still writes a real
  blank when a chat is unlabelled/unassigned); ids that cannot be resolved are
  left *unknown* (sheet value kept) instead of a UUID/blank; owner and stage
  are also resolved from the detail traits; raw ids already in the sheet are
  translated to names on the next run whose lookups load; and the sheet read
  in `_read_tab_by_key()` retries and aborts on failure instead of treating a
  failed read as an empty sheet (which used to blank those columns and drop the
  `enr_*` columns). None of this fills a value the web session cannot see: the
  session must be valid (`interakt_session.py --setup`) for these columns to
  refresh at all — the log prints "ENRICHMENT SKIPPED" otherwise.
  Verify offline: `python sales_validation\verify_interakt_enrichment.py`.

## Run standalone

```bat
python sales_data_collection\pyInteraktUsers.py
```

## Email Summary Metrics

The pipeline completion e-mail shows these business KPIs for this script (derived from the script's own run output — no business logic changed). Full technical detail stays in `logs/pyInteraktUsers.log`.

- **Users fetched & upserted** — volume handled this run (context, not a change count)
- **New** — count for the current run
- **Updated** — count for the current run
- **Unchanged** — already up to date / no change this run
- **Repeat-enquiry updated** — count for the current run

Zero-valued KPIs are omitted to keep the e-mail concise. The script's line in the e-mail is marked **SUCCESS / FAILED / SKIPPED**; on failure an **Action Required** row shows a short business reason + retry status.
