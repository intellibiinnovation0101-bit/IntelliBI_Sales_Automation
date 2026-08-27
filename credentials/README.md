# credentials/ — secrets & session state (never commit)

Everything in this folder is git-ignored (see the project `.gitignore`).
Copy the real files here **once per machine**; the pipeline reads them from here
via `common/paths.py`, so no source-code paths ever change.

## Required

| File | Purpose | How to get it |
|------|---------|---------------|
| `service_account.json` | Google service-account key (Sheets v4 + Drive v3). Account: `intellibi-data-pipeline@intellibi-mis.iam.gserviceaccount.com` | Google Cloud console → the pipeline service account → Keys. The four source sheets **and** the target sheet must be shared with this account. |
| `email_config.py` | Gmail SMTP sender + app password used for report and summary e-mails. | Copy `email_config.example.py` → `email_config.py` and fill in the 16-char app password (`myaccount.google.com/apppasswords`). |

## Interakt (Layer 1 — pyInteraktUsers.py)

| File | Purpose |
|------|---------|
| `interakt_credentials.json` | Optional API key (`{"api_key": "..."}`); blank → use the web session below. |
| `interakt_curl.txt` | A "Copy as cURL (bash)" paste of a logged-in Interakt inbox request; the enricher reads the auth headers from it. |
| `interakt_spreadsheet.json` | Cached target-spreadsheet id for the Interakt tab. |
| `interakt_browser_profile/` | Playwright profile logged in once for headless auto-refresh of `interakt_curl.txt`. |

## Exotel (Layer 1 — pyExotelInboxScrape.py / pyExotelCallDetails.py)

| File | Purpose |
|------|---------|
| `exotel_credentials.json` | Exotel API key/token/sid/subdomain (or set `EXOTEL_*` env / config.yaml). |
| `exotel_web_cookie.txt` | Cookie for the Exotel inbox web session (auto-refreshed by the browser profile). |
| `exotel_browser_profile/` | Playwright profile logged in once for headless auto-refresh of the cookie. |
| `inbox_html/` | Runtime scrape cache written by the inbox scraper. |

Auto-login uses Playwright:  `python -m playwright install chromium`, then run the
relevant collector once **headful** to log in; subsequent scheduled runs refresh
the session automatically.
