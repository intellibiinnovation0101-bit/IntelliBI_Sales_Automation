# IntelliBI Website Lead Alert

Instant, dedicated desktop popups for new **Website Leads** so active counsellors
attend them fast — with a first-click **claim** that assigns each lead to exactly
one counsellor and updates everyone else.

This is the approved **Option A** design: a small always-on **central service**
on the office PC + a tiny **Windows tray client** on each counsellor's PC.

---

## How it works (this build)

```
Website form ─► Apps Script ─► "Contact Us Form" Google Sheet
                                        │
              (the service polls this sheet every ~20s — outbound only,
               reuses the existing service account, no Apps Script change,
               no inbound port-forwarding, no Gmail scope)
                                        ▼
        ┌──────────────  CENTRAL SERVICE  (office PC)  ──────────────┐
        │  • detects new rows -> new leads                           │
        │  • reads Active counsellors from config/counsellors.json   │
        │  • SQLite lifecycle DB — atomic single-claim               │
        │  • pushes NEW_LEAD to online counsellors over WebSocket    │
        │  • re-alerts / escalates (email intellibiadmin) / expires  │
        │  • best-effort mirror to a "Website Lead Alert Log" sheet  │
        └────────────────────────────────────────────────────────────┘
                                        │  WebSocket (office LAN)
                                        ▼
           Counsellor tray client  →  topmost popup + sound
              [ Open Email ]   [ Acknowledge / Accept Lead ]
```

**Why sheet-polling instead of a Gmail webhook:** the host PC sits behind your
office network with no public URL and is on only ~09:30–23:00. Polling the sheet
the Apps Script already fills is outbound-only, needs no new credentials or
Google setup, and inherently avoids duplicate-email problems. Detection latency
is the poll interval (~20s) — far faster than a human noticing an email.

---

## A. Central service — one-time setup (office PC)

1. **Config** is already added to `config/config.yaml` under `lead_alert:` — review
   the port (default `8787`), the `active_from`/`active_to` window, escalation
   minutes, and (optionally) `log_sheet_id`.

2. **Secret:** copy the template and set a shared enrollment code:
   ```
   copy credentials\lead_alert_secrets.example.py credentials\lead_alert_secrets.py
   REM edit it: ENROLLMENT_CODE = "your-shared-code"
   ```

3. **Python env + deps** (a dedicated venv is fine, or reuse the project one):
   ```
   cd IntelliBI_Sales_Automation
   .venv\Scripts\activate
   pip install -r lead_alert\requirements-service.txt
   ```

4. **Run it:**
   ```
   .venv\Scripts\python.exe lead_alert\service\run_service.py
   ```
   You should see it bind to `0.0.0.0:8787` and start watching the sheet.

5. **Auto-start with Windows** (elevated PowerShell, once):
   ```
   powershell -ExecutionPolicy Bypass -File lead_alert\service\setup_service_schedule.ps1
   ```

6. **Firewall + LAN address:** allow inbound TCP `8787` for Private networks, and
   note the PC's LAN IP (`ipconfig` → IPv4). Counsellors will use
   `http://<that-IP>:8787`. (Only needed on the LAN; nothing is exposed publicly.)

7. **(Optional) Audit/metrics sheet:** create a Google Sheet, share it with the
   **service account** (the `client_email` in `credentials/service_account.json`)
   as **Editor**, put its id in `lead_alert.log_sheet_id`. The service then keeps
   one row per lead with received/ack/assigned times and response seconds — ready
   for your reporting layer.

> The service account must already have **read** access to the "Contact Us Form"
> sheet (it does, since the pipeline reads project sheets). If not, share that
> sheet with the service account as Viewer.

---

## B. Counsellor client — build once, install per PC

**Build the .exe once** on any Windows machine with Python:
```
cd IntelliBI_Sales_Automation\lead_alert\client
python -m venv .venv
.venv\Scripts\activate
pip install -r ..\requirements-client.txt
build.bat            REM -> dist\IntelliBILeadAlert.exe
```

**On each counsellor PC** (no Python needed):
1. Copy `IntelliBILeadAlert.exe` anywhere (e.g. the Desktop) and run it.
2. First launch shows **Register this computer**: enter the **Server URL**
   (`http://<office-PC-IP>:8787`), the counsellor's **email** (must be an *Active*
   `counsellors` record in `counsellors.json`), and the **enrollment code**.
3. It then lives in the **system tray** and shows a popup on every new lead.
4. **Auto-start:** run once (from the folder holding the exe):
   ```
   IntelliBILeadAlert.exe  --install-autostart
   ```
   …or run `python install_autostart.py` from source. (Right-click the tray icon
   → *Re-register this computer…* to move to a new PC or re-enroll.)

---

## Test it end-to-end (before going live)

* **Inject a demo lead** (from the office PC) — every online counsellor pops:
  ```
  curl -X POST http://localhost:8787/demo/inject -H "Content-Type: application/json" ^
       -d "{\"code\":\"your-shared-code\",\"name\":\"Test Lead\",\"course\":\"Data Science\",\"form_type\":\"Program Enquiry\"}"
  ```
* **Automated checks** (run on any machine with the web deps):
  ```
  python lead_alert\tests\test_core.py            REM atomic claim, dedup, Active filter, window
  python lead_alert\tests\test_app_integration.py REM enroll -> WS -> first-accept-wins -> others updated
  ```

---

## Behaviour & the scenarios it covers

* **One lead → one counsellor:** the Accept is an atomic conditional DB update.
  Two clicks at the same instant → exactly one `assigned`, the other `already`.
* **Others updated on assignment:** every notified counsellor's popup flips to
  *“Lead Assigned — accepted by <name> at <time>. No action required.”* and closes.
* **Offline / reconnect / PC restart:** the client reconnects automatically and
  the server **re-syncs** any still-open leads; an already-assigned lead never
  re-pops as "new".
* **Re-alert & escalate:** unclaimed after `realert_after_min` → re-alert online
  counsellors; after `escalate_after_min` → email the **intellibiadmin** section;
  after `expire_after_min` → mark `UNACKNOWLEDGED` and close popups.
* **Duplicate detection:** each lead has a stable `lead_id` (its sheet row), so a
  re-read never double-alerts.
* **Open ≠ Accept:** *Open Email* opens Gmail/the lead sheet but never claims.
* **Config-driven roster:** add / remove / activate / deactivate a counsellor in
  `counsellors.json` (Active only) — no code change, no restart. A deactivated
  counsellor is dropped from new alerts and can no longer claim.
* **New PC:** just enroll the new device (old token can be revoked).

**Not implemented (per your instruction):** lead *reassignment*. Once a lead is
assigned it stays with that counsellor; there is no reassign action in this build.

---

## Security

* All Google/Gmail/service-account credentials stay **on the server only**. The
  client holds just a per-device token (DPAPI-encrypted) — no Google secrets.
* Enrollment requires the shared **enrollment code** *and* the email must be an
  Active counsellor. Unknown devices/emails are refused.
* Every WebSocket action is authorized server-side by the device token + live
  Active status, so a deactivated counsellor or an unknown device cannot claim.
* Keep the service on the **office LAN** (bind is `0.0.0.0` for LAN reach, not the
  public internet). If you ever need remote counsellors, put it behind a VPN or a
  TLS reverse proxy rather than opening the port to the world.

---

## Files in this module

```
lead_alert/
├── README.md                     this file
├── requirements-service.txt      server deps
├── requirements-client.txt       client + build deps
├── service/
│   ├── config.py                 settings (reads config.yaml + paths + secrets)
│   ├── counsellors.py            Active-counsellor loader (counsellors.json)
│   ├── store.py                  SQLite lifecycle + ATOMIC single-claim
│   ├── google_io.py              read source sheet + best-effort audit mirror
│   ├── mailer.py                 escalation email (reuses email_config.py)
│   ├── hub.py                    WebSocket connection manager
│   ├── ops.py                    dispatch + accept orchestration
│   ├── background.py             sheet poller + escalation loops
│   ├── app.py                    FastAPI app (enroll / ws / accept / demo)
│   ├── run_service.py            launcher
│   └── setup_service_schedule.ps1  Windows auto-start for the service
├── client/
│   ├── lead_alert_client.py      tray entry point
│   ├── popup.py                  topmost, sounding lead popup
│   ├── ws_client.py              reconnecting WebSocket
│   ├── client_config.py          server URL + DPAPI token store
│   ├── enroll.py                 first-run registration dialog
│   ├── install_autostart.py      Startup-folder shortcut
│   └── build.bat                 PyInstaller one-file build
└── tests/                        core + end-to-end tests (no Google/GUI needed)
```

**Also changed/added outside this folder:**
* `config/config.yaml` — new `lead_alert:` block.
* `credentials/lead_alert_secrets.example.py` — enrollment-code template (copy to
  `lead_alert_secrets.py`, git-ignored).

Nothing in the existing report pipeline, Apps Script, or email/sharing behaviour
was modified.
