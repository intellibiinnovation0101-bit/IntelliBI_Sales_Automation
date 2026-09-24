# 7. Step-by-Step Deployment Guide

This is the end-to-end checklist to take the app from an empty folder to an
always-on service, without touching the existing production system.

## 7.1 Pre-flight checklist

- [ ] Python 3.10+ installed on the host.
- [ ] `counsellor_app/` folder present inside `IntelliBI_Sales_Automation/`.
- [ ] Google service-account JSON at `credentials/service_account.json`.
- [ ] Data sheet shared with the service account's `client_email` as **Editor**.
- [ ] `config.yaml` created, `session_secret` set, at least one counsellor added.

## 7.2 Deploy (first time)

```bash
cd counsellor_app
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: . .venv/bin/activate
pip install -r requirements.txt

python -m pytest -q               # 1) all green
python run.py --check             # 2) connects to the real sheet, prints lead count
python run.py                     # 3) starts serving; open /health then /
```

If steps 1–3 pass, you have a working deployment. Everything below is about
making it always-on and secure.

## 7.3 Run as an always-on service

### Windows — Task Scheduler (simplest)

1. Create `start_counsellor_app.bat` in the folder:
   ```bat
   @echo off
   cd /d "%~dp0"
   call .venv\Scripts\activate
   python run.py
   ```
2. Open **Task Scheduler → Create Task**:
   - General: "Run whether user is logged on or not", "Run with highest
     privileges".
   - Triggers: **At startup** (and optionally "At log on").
   - Actions: Start a program → the `.bat` above.
   - Settings: "If the task fails, restart every 1 minute", up to 3 times.
3. Save (you'll be asked for the account password). Start the task once to test.

### Windows — NSSM (nicer, true service with auto-restart)

1. Download NSSM, then:
   ```bat
   nssm install CounsellorApp "C:\…\counsellor_app\.venv\Scripts\python.exe" "C:\…\counsellor_app\run.py"
   nssm set CounsellorApp AppDirectory "C:\…\counsellor_app"
   nssm set CounsellorApp AppStdout "C:\…\counsellor_app\logs\app.log"
   nssm set CounsellorApp AppStderr "C:\…\counsellor_app\logs\app.err.log"
   nssm start CounsellorApp
   ```
2. NSSM restarts the app automatically if it exits.

### Linux — systemd

`/etc/systemd/system/counsellor-app.service`:
```ini
[Unit]
Description=IntelliBI Counsellor App
After=network-online.target

[Service]
WorkingDirectory=/opt/counsellor_app
ExecStart=/opt/counsellor_app/.venv/bin/python run.py
Restart=always
RestartSec=3
Environment=INTELLIBI_APP_SECURE_COOKIE=1

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now counsellor-app
sudo systemctl status counsellor-app
```

## 7.4 HTTPS / exposing beyond localhost

Serve the app on `127.0.0.1` and put a reverse proxy in front for TLS. This keeps
login cookies encrypted in transit. Also set `INTELLIBI_APP_SECURE_COOKIE=1`.

**Nginx example:**
```nginx
server {
    listen 443 ssl;
    server_name counsellor.intellibi.internal;
    ssl_certificate     /etc/ssl/certs/counsellor.crt;
    ssl_certificate_key /etc/ssl/private/counsellor.key;
    location / {
        proxy_pass http://127.0.0.1:8600;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
On Windows without Nginx, Caddy is a simple alternative (automatic HTTPS).

For LAN-only use behind a trusted network, plain HTTP on `0.0.0.0:8600` is
acceptable, but HTTPS is recommended wherever feasible.

## 7.5 Rollout strategy (zero disruption)

Because the app writes byte-compatible rows and Google Sheets stays the system of
record, you can adopt it gradually:

1. **Shadow / pilot.** Run the app; have one or two counsellors use it while the
   rest keep using the existing form. Both write the same sheet; consolidation
   and reports keep working.
2. **Verify.** Spot-check that leads saved via the app appear correctly in the
   Active tab, archive to InActive, and flow through `pyConsolidateLeadsLoad.py`
   into the master and reports (see `docs/08`).
3. **Cut over.** Move all counsellors to the app. From here the app is the single
   writer to the Active tab — the cleanest state.
4. **Rollback (if ever needed).** Simply have counsellors use the old form again.
   Nothing in the existing system was changed, so rollback is instantaneous and
   riskless. You can stop or delete the app folder at any time.

## 7.6 Backups

- The **Google Sheet** is the system of record; its own version history is your
  primary backup, and the InActive tab preserves every prior lead version.
- The local `data/store.db` is only a cache/outbox and does not need backing up —
  it is rebuilt from the sheet on startup. (Do not delete it while pending writes
  exist; check `/health` shows `pending: 0` first.)
