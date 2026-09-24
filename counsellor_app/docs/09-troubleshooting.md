# 9. Troubleshooting

Start by looking at two things: the **server log** (console, or the log files if
running as a service) and **`GET /health`**. Most problems announce themselves in
one of those.

## 9.1 Startup

**`ModuleNotFoundError` / import errors**
The virtual environment isn't active or deps aren't installed.
```bash
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**`bcrypt is required to hash passwords`**
`pip install bcrypt` (it's in `requirements.txt`; the venv may not be active).

**App starts but `leads_cached` is 0 when the sheet has data**
The service account can read a sheet but the wrong tab name is configured, or it's
reading an empty tab. Confirm `active_tab` (or an alias) matches the real tab
name exactly, including spaces.

## 9.2 Google / API access

**`gspread.exceptions.APIError: 403` / `PERMISSION_DENIED`**
The sheet isn't shared with the service account. Open the sheet → Share → add the
`client_email` from `credentials/service_account.json` as **Editor**.

**`403` mentioning "Google Sheets API has not been used/enabled"**
Enable **Google Sheets API** (and **Google Drive API**) for the project in the
Cloud Console.

**`FileNotFoundError: service_account.json`**
The key isn't at `credentials/service_account.json`, or `service_account_file` in
`config.yaml` points elsewhere. Fix the path or move the file.

**`SpreadsheetNotFound`**
`data_sheet_id` is wrong, or the sheet isn't shared with the service account.

**`429` / quota errors in the sync log; `failed_cycles` climbing**
You're hitting the Sheets write quota (rare in normal use). The worker backs off
and retries automatically — no data is lost. If it's persistent, lower
`sync_batch_max` slightly or raise `sync_tick_seconds`; and confirm nothing else
is hammering the same sheet.

## 9.3 Login

**"Unknown or inactive account."**
The email isn't in `counsellors:` in `config.yaml`, or `active: false`. Add/enable
with `python -m app.manage_users add …`, then restart.

**"Incorrect password."**
Reset it: `python -m app.manage_users add <same-email> "<name>" "<counselling_by>"`
and choose a new password, then restart.

**Logged out immediately / login won't stick**
Usually a cookie issue behind a proxy. Behind HTTPS set
`INTELLIBI_APP_SECURE_COOKIE=1`; behind plain HTTP make sure that variable is
**not** set. Also confirm `session_secret` didn't change between requests (it
must be stable, and identical across any multiple instances).

## 9.4 Saving

**Save returns a validation message (HTTP 400)**
Working as intended — the same rules as the form. Common ones:
- "Candidate Type is required…" — select a Candidate Type (unless Admission
  Status is *Irrelevant* / *Unable To Connect*).
- "Please select the Google Meet / Walk-In Schedule Date." — set the date when
  the matching schedule flag is *Yes*.

**Save says "Saved ✓ · syncing (N)" and N doesn't drop to 0**
The local write is safe, but the background sync to Sheets is failing. Check the
log and `/health.sync`. See §9.2. The queue will drain once Sheets access
recovers; nothing is lost in the meantime.

**A change I made directly in Google Sheets isn't showing in the app**
The app refreshes from the sheet every `reconcile_seconds` (default 300 s = 5
min). Wait for the next reconcile, lower the interval, or restart the app to pick
it up immediately. Note: in normal operation the app is the single writer, so
direct sheet edits should be rare.

## 9.5 Data concerns

**A value appears in the wrong column / mobile shows a remark**
This app cannot produce that: only editable fields are accepted from the client
and the mobile key is set server-side. If you see it, the row predates the app or
came from another writer. Re-save the lead through the app to normalise it.

**History (InActive) row missing after an update**
History is only written when a lead **already existed** (a brand-new lead has no
prior version to archive). Confirm the mobile already had an Active row before the
edit.

**I need to rebuild the local cache**
Stop the app, confirm `/health` last showed `pending: 0` (so nothing un-synced is
in the journal), delete `data/store.db*`, and restart. It rebuilds from the sheet.
**Do not** delete it while pending writes exist.

## 9.6 Performance

**Reads feel slow**
Reads are in-memory and should be instant. Slowness is almost always the browser
↔ server network (proxy, remote host) rather than the app. Test `/health` latency
locally to isolate. Bootstrap (startup) does read the whole sheet once and can
take a few seconds for very large sheets — that's one-time.

## 9.7 Getting more detail

Run in the foreground to watch logs live:
```bash
python run.py
```
For a quick non-serving diagnosis of sheet connectivity and lead count:
```bash
python run.py --check
```
If a specific save is misbehaving, reproduce it in `--fake` mode (no risk to real
data) and, if needed, add a focused test in `tests/` mirroring the case.
