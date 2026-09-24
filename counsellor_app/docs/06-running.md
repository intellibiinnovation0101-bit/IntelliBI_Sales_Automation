# 6. How to Run the System

Run all commands from the `counsellor_app/` folder with the virtual environment
active (`\.venv\Scripts\activate` on Windows, `. .venv/bin/activate` elsewhere).

## 6.1 Run modes

| Command | What it does |
|---------|--------------|
| `python run.py` | Start the server against the **real** Google Sheet. |
| `python run.py --fake` | Start with an **in-memory** demo sheet — no credentials, no network. Great for demos and UI testing. |
| `python run.py --check` | Bootstrap only (load the sheet, print status), then exit. A quick health check. |
| `python run.py --port 9000` | Override the port for this run. |
| `python run.py --host 127.0.0.1` | Bind local-only for this run. |

When the server is running you'll see Uvicorn logs and periodic
`[sync] synced N write(s)` / `[sync] reconciled with sheet` lines.

## 6.2 Using the app (counsellor flow)

1. Open `http://<host>:8600/` in a browser.
2. **Log in** with your email + password.
3. **Search** by mobile number (paste or type, any format — `+91`, spaces and
   `0` prefixes are handled). Press **Enter** or click **Find**.
   - If an exact lead exists, it opens immediately.
   - Otherwise you get quick matches by name/email, or the option to **create a
     new lead** for that number.
4. **Review** the current details and the **Interaction history** (each prior
   version is expandable, newest first).
5. **Edit** the fields you need. Date fields use a date picker; Yes/No and
   status fields use dropdowns.
6. Click **Save**. You'll see **"Saved ✓"** within a moment; the page refreshes
   to show the new timestamp and adds the previous version to history.

The save is durable the instant you see "Saved" — even if it briefly shows
"syncing (N)", the write is already safe locally and will reach the Google Sheet
automatically.

## 6.3 Demo accounts for `--fake` mode

`--fake` mode still requires a login. Add a throwaway account to `config.yaml`
(or a separate config) with the CLI, e.g.:
```bash
python -m app.manage_users add demo@intellibi.test "Demo Counsellor" "Demo Counsellor"
```
Then log in with `demo@intellibi.test` and the password you chose. The fake sheet
is seeded with two sample leads (`9876543210`, `9812345678`).

## 6.4 Health & monitoring endpoint

`GET /health` (no login required) returns live status, e.g.:
```json
{
  "status": "ok",
  "leads_cached": 481,
  "sync": {"pending": 0, "synced_total": 37, "failed_cycles": 0, "backoff_s": 0.0}
}
```
- `leads_cached` — leads currently held in memory.
- `sync.pending` — writes acknowledged locally but not yet in the sheet
  (normally 0, briefly >0 right after a save).
- `sync.failed_cycles` / `backoff_s` — non-zero means Sheets writes are
  currently failing and being retried; check `docs/09`.

Point any uptime monitor at `/health`.

## 6.5 Stopping the server

Press `Ctrl+C`. On shutdown the app does a **final flush** of any pending writes
to the sheet and closes the database cleanly. If it's ever killed hard (power
loss), no data is lost — pending writes are replayed on the next startup.

## 6.6 Running it always-on

For production you'll want it to start on boot and restart on failure. See
`docs/07-deployment.md` for a Windows Task Scheduler / NSSM service setup and a
Linux `systemd` unit, plus optional HTTPS via a reverse proxy.
