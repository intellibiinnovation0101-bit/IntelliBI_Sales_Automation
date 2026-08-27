# pyExotelInboxScrape.py — Exotel Inbox Scraper

**Layer 1 — Source Data Collection** · `sales_data_collection/pyExotelInboxScrape.py`

## Purpose

Scrapes the **Exotel inbox web UI** (`my.exotel.com`) for per-call notes and the
agent assignment that the Exotel **API does not expose**. It writes a local HTML
snapshot plus parsed notes/agents JSON, which `pyExotelCallDetails.py` then
merges into the call records. This is the **first half** of the Exotel flow:

```
pyExotelInboxScrape.py  -->  pyExotelCallDetails.py
```

## Inputs

| Source | Access |
|--------|--------|
| Exotel inbox web session | Cookie in `credentials/exotel_web_cookie.txt`. The Playwright profile `credentials/exotel_browser_profile/` auto-refreshes it (headless) when expired — no manual cookie paste needed. |

Account SID: `SID = intellibiinnovations1`.

## Outputs (into `credentials/inbox_html/`)

| File | Content |
|------|---------|
| `inbox_scraped.html` | Raw HTML snapshot of the inbox. |
| `inbox_notes.json` | Parsed per-call notes. |
| `inbox_agents.json` | Parsed per-call agent assignments. |

## Configuration

Environment overrides:

| Env var | Meaning |
|---------|---------|
| `FETCH_NOTES` | Whether to expand and fetch per-call notes. |
| `NOTES_MAX_CALLS` | Cap on how many calls' notes to fetch. |
| `NOTE_LOAD_MS` | Wait (ms) for each note panel to load. |
| `HEADFUL` | Run the browser visibly (for first-time login / debugging). |

## Dependencies (project modules)

`exotel_common` (parsing helpers), `exotel_session` (headless Playwright
auto-login, imported on demand).

## How it runs

1. Load the saved cookie / auto-login via the browser profile.
2. Open the Exotel inbox, page through the calls.
3. Optionally expand each call to capture its note and assigned agent.
4. Write `inbox_scraped.html`, `inbox_notes.json`, `inbox_agents.json`.

## Logging

`logs/exotel_scrape.log` (+ console). Records pages scraped, notes captured, and
auto-login events.

## Troubleshooting

- **Playwright not installed**: `python -m playwright install chromium`.
- **Login expired**: run once with `HEADFUL=1` to log in, so the profile can
  refresh the session for scheduled runs.
- A failure here is **non-fatal** for the pipeline: `pyExotelCallDetails.py`
  still runs (call records come from the API/cookie), just without the freshest
  inbox notes.

## Run standalone

```bat
python sales_data_collection\pyExotelInboxScrape.py
```

## Email Summary Metrics

The pipeline completion e-mail shows these business KPIs for this script (derived from the script's own run output — no business logic changed). Full technical detail stays in `logs/pyExotelInboxScrape.log`.

- **Call rows scraped** — count for the current run
- **Notes captured** — count for the current run

Zero-valued KPIs are omitted to keep the e-mail concise. The script's line in the e-mail is marked **SUCCESS / FAILED / SKIPPED**; on failure an **Action Required** row shows a short business reason + retry status.
