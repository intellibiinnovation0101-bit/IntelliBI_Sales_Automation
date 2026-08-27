# pyConsolidateLeadsLoad.py — Lead Consolidation Load

**Layer 2 — Lead Consolidation** · `sales_consolidation/pyConsolidateLeadsLoad.py`

## Purpose

Merges the **four lead sources** (Walk-In, Website, WhatsApp/Interakt, Direct
Calling/Exotel) — plus the IntelliBI Lead Information form — into ONE
de-duplicated **single source of truth**, and writes it to the "IntelliBI
Consolidate Sales Tracking Report" sheet. This master is what every Layer 3
report reads.

## Inputs — source sheets (gsheet mode)

| Source key | Sheet ID | Role |
|------------|----------|------|
| `IntelliBI` | `1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw` | Lead Information form backend (highest priority for identity). |
| `Walk-In` | `19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ` | Walk-in enquiries. |
| `Website` | `1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE` | Website form. |
| `WhatsApp` | `1s6fscV531_zozRqT2sZQzJP7LxyqzySRNizMsaTUAq8` | Interakt WhatsApp. |
| `Call` | `1L-Ew4-GF7MzzAnnIhVBafOmN_DJlMBTaRI6048PUo4I` | Exotel calls. |

Only the **first tab** of each source is read (matches the CSV exports).

Also read live each run: the **Lead-Type mapping** sheet
`LEAD_TYPE_MAP_SHEET_ID = 1b7KbkJ3a8QvL2RVDyEgNdcduzGBbZ0_bsY-gZGK0UMo`
(wide layout: each column header is a Lead Type, cells list the `Current Status`
values that belong to it). Editing this sheet reclassifies leads with no code
change.

## Output

| Target | Detail |
|--------|--------|
| Google Sheet | `TARGET_SHEET_FULL = 1zZQjXnMJD96Ca0MNyfSt4-XS0z5w3rT7WPdb9qsP1Gs` ("IntelliBI Consolidate Sales Tracking Report") — fully rebuilt & overwritten each run. |
| Files | `Consolidated_Master_Lead.csv` and `.xlsx` in `output/exports/`. |

## Configuration

| Env var | config.yaml | Meaning |
|---------|-------------|---------|
| `INTELLIBI_INPUT_MODE` | `consolidation.input_mode` | `gsheet` (live) or `csv` (offline test). |
| `INTELLIBI_TARGET_SHEET_ID` | `consolidation.target_sheet_id` | Target master sheet. |
| `INTELLIBI_LEAD_TYPE_MAP_SHEET_ID` | `consolidation.lead_type_map_sheet_id` | Lead-type mapping sheet. |
| `INTELLIBI_OUT_DIR` | `consolidation.export_dir` | Where CSV/XLSX are written (`output/exports`). |
| `INTELLIBI_LOCAL_DIR` | — | Source-CSV folder in `csv` mode. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` / `GOOGLE_APPLICATION_CREDENTIALS` | `google.service_account_file` | Service-account key. |

Optional field-mapping overrides (resolved in `config/`, absent by default → the
built-in defaults are used): `notes_field_mapping.json`,
`website_field_mapping.json`, `intellibi_field_mapping.json`.

## Key rules (business logic — unchanged)

- **Cleansing**: trim, collapse whitespace, strip invisible chars, phone
  normalisation to bare 10-digit, email lowercase+validate, date standardisation
  (`dd-MMM-yyyy hh:mm a`), Yes/No + status standardisation. Counsellor names are
  title-cased so casing variants merge.
- **Duplicate detection** (stop at first hit): `Mobile Number` → `Email
  Address`. **Full Name is never a match key.**
- **Source-priority merge**: `Walk-In > Direct Calling > WhatsApp > Website`;
  each field takes the first non-blank in that order.
- **Counselling By** has its own priority and special-cases (e.g. `assign to
  Arsh` → `ArshKhan Pathan`; Call source never keeps `Sushma Kutal` when a real
  handler exists).
- **Lead Interaction History**: every enquiry listed chronologically; consecutive
  duplicate interactions collapsed; `Number of Interactions` reflects the deduped
  count.
- **Flags recomputed every run**: `IsPhoneNumberValid`, `IsLeadRelevant`
  (fuzzy). Invalid/irrelevant rows are kept for review, not dropped.
- **Business/virtual Exotel lines** (`BUSINESS_NUMBERS_SEED` + every distinct
  `To` line seen) never become leads.
- **UPSERT/rebuild**: the master is rebuilt from the current sources every run;
  insert/update/skip/removed counts are logged.

See `README_Consolidated_Master.md` (project root of the original repo) for the
full field-mapping table.

## How it runs

1. Read the 5 sources (+ lead-type map) from Google Sheets (or CSVs in `csv` mode).
2. Cleanse → detect duplicates → source-priority merge → build interaction history.
3. Recompute flags, classify Lead Type, exclude business numbers.
4. Write `output/exports/Consolidated_Master_Lead.csv`/`.xlsx` and overwrite the
   target sheet.

## Logging

Streams to `logs/pyConsolidateLeadsLoad.log` via the runner. Prints
per-source processed counts, unique master total, and insert/update/removed
counts.

## Run standalone

```bat
python sales_consolidation\pyConsolidateLeadsLoad.py
```

## Email Summary Metrics

The pipeline completion e-mail shows these business KPIs for this script (derived from the script's own run output — no business logic changed). Full technical detail stays in `logs/pyConsolidateLeadsLoad.log`.

- **Unique master leads** — count for the current run
- **New leads inserted** — count for the current run
- **Duplicates merged** — count for the current run
- **Total records processed** — volume handled this run (context, not a change count)
- **Rows removed** — count for the current run

Zero-valued KPIs are omitted to keep the e-mail concise. The script's line in the e-mail is marked **SUCCESS / FAILED / SKIPPED**; on failure an **Action Required** row shows a short business reason + retry status.
