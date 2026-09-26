# 1. Architecture & Folder Structure

## 1.1 The big picture

The counsellor app is a thin, fast layer **in front of the existing Google
Sheet**. It does not replace the sheet — Google Sheets remains the single system
of record. This is the key design decision that keeps every existing downstream
process working unchanged.

```
                    ┌─────────────────────────────────────────────┐
                    │            COUNSELLOR APP (new)             │
  Counsellor  ─────▶│  Web UI ──▶ FastAPI ──▶ In-memory index     │
  (browser)         │                          + SQLite cache      │
                    │                          + write-behind queue │
                    └───────────────┬─────────────────────────────┘
                                    │ (single writer, async batches)
                                    ▼
                    ┌─────────────────────────────────────────────┐
                    │   GOOGLE SHEET  "IntelliBI Lead Information" │
                    │   • Active tab   (current record per lead)   │
                    │   • InActive tab (archived prior versions)   │  ◀── system of record
                    └───────────────┬─────────────────────────────┘
                                    │ (read on schedule, UNCHANGED)
                                    ▼
     pyConsolidateLeadsLoad.py  →  Consolidated Master  →  Follow-Up report + ML
                    (existing production Python — not modified)
```

The existing Google Form / `LeadSubmissionForm.gs` can keep running during a
transition; the app is simply a faster, richer way to do the same edits. Once
counsellors move to the app, the app becomes the **single writer** to the Active
tab, which is what makes reconciliation trivial and writes conflict-free.

## 1.2 Why this design

- **Speed.** Counsellor reads (search, view, history) are served from an
  in-memory dictionary — no Google API call on the hot path — so they are
  effectively instant regardless of sheet size. Saves are acknowledged the
  moment they are written to a local durable journal (~1–6 ms), and the actual
  Google Sheet write happens a moment later in the background.
- **Safety / no data loss.** Every save is committed to a local SQLite journal
  *before* the counsellor sees "Saved". If the process crashes or the machine
  reboots, un-synced writes are replayed on the next startup. Google Sheets
  never loses a write, and neither does the local queue.
- **Zero disruption.** The app writes rows to the sheet that are
  **byte-compatible** with what `LeadSubmissionForm.gs` writes today — identical
  28-column schema, identical mobile normalisation, identical timestamp format,
  identical InActive versioning. So `pyConsolidateLeadsLoad.py` and the reports
  keep working with no changes.
- **Flexibility for the future.** All Google-Sheets access is behind a single
  `SheetsGateway` interface. Swapping the store for PostgreSQL (or adding a
  second store) later means writing one new gateway class — nothing else in the
  app changes.

## 1.3 Folder structure

```
counsellor_app/
├── README.md                  ← start here
├── run.py                     ← entry point (start server / --fake / --check)
├── requirements.txt
├── config.example.yaml        ← copy to config.yaml and edit
├── .gitignore                 ← keeps secrets & local state out of git
│
├── app/                       ← the application package
│   ├── config.py              ← all settings + the exact production sheet schema
│   ├── domain.py              ← business rules ported 1:1 from LeadSubmissionForm.gs
│   ├── sheets_gateway.py      ← the ONLY code that talks to Google Sheets (gspread)
│   ├── fake_sheets.py         ← in-memory stand-in for offline tests / --fake mode
│   ├── store.py               ← in-memory index + SQLite cache + write-behind journal
│   ├── sync.py                ← background worker: drains journal → Sheets, reconciles
│   ├── auth.py                ← session login (bcrypt allow-list; optional Google OAuth)
│   ├── server.py              ← FastAPI app: API endpoints + serves the UI
│   ├── manage_users.py        ← admin CLI: add counsellors, hash passwords, gen secret
│   └── web/
│       └── counsellor_page.py ← the entire single-page counsellor UI (one HTML string)
│
├── credentials/               ← put service_account.json here (git-ignored)
├── data/                      ← SQLite store.db lives here at runtime (git-ignored)
├── docs/                      ← this documentation set
└── tests/                     ← pytest suite (domain, store, sync, API, UI)
```

## 1.4 Component responsibilities

| Module | Responsibility |
|--------|----------------|
| `config.py` | Loads `config.yaml` + `INTELLIBI_APP_*` env vars. Holds `ACTIVE_COLUMNS` (the 28-column production schema, verified against the live sheet) and `INACTIVE_COLUMNS`. **Nothing else hard-codes an ID or column.** |
| `domain.py` | `normalize_mobile`, `is_valid_indian_mobile`, `build_record`, `validate_submission`, date canonicalisation, row⇄record conversion. This is the guarantee that an app-saved lead is identical to a form-saved one. |
| `sheets_gateway.py` | `GspreadGateway` — the single writer. `load()` reads Active + InActive; `apply_save(op)` archives the prior version to InActive and upserts the Active row by mobile. |
| `fake_sheets.py` | `FakeGateway` — same interface, in-memory. Lets the full system run and be tested with no credentials and no network. |
| `store.py` | The performance core. In-memory index (`mobile → record`, `mobile → history`), a durable SQLite cache, and a write-behind **journal**. `get`/`search`/`history` are instant; `save` is durable + instant-ack. |
| `sync.py` | Background thread. Drains the journal to Google Sheets in small batches with retry/backoff, and periodically **reconciles** (re-reads the sheet to catch any out-of-band edits) without losing in-flight writes. |
| `auth.py` | Password hashing/verification (bcrypt), signed expiring session cookies, optional Google Workspace OAuth hook. |
| `server.py` | FastAPI routes (`/api/login`, `/api/lead`, `/api/search`, `/api/save`, `/health`) and serves the UI at `/`. |
| `web/counsellor_page.py` | The whole counsellor UI: login → search → view current + history → edit → save. Vanilla JS, no build step, same-origin API only. |

## 1.5 Data flow of a single save

1. Counsellor edits fields in the browser and clicks **Save**.
2. `POST /api/save` → `store.save()`:
   a. `build_record()` normalises the mobile, stamps the timestamp, canonicalises
      dates, defaults *Counselling By* — producing a full 28-column record.
   b. `validate_submission()` applies the same rules as the form.
   c. The new record + the prior version (to archive) are written to the SQLite
      **journal** and cache, and the in-memory index is updated — all under one
      lock, committed to disk.
   d. The API returns `{"ok": true}` immediately. **This is the ~1–6 ms path.**
3. A moment later the background `SyncWorker`:
   a. Appends the prior version to the **InActive** tab (with `RecordVersion` +
      `ArchivedAt`).
   b. Upserts the **Active** row for that mobile.
   c. Marks the journal row synced.
4. Downstream Python (consolidation, reports) reads the sheet on its own schedule
   and sees the update — exactly as it would have if the form had written it.

## 1.6 Consistency model

The app is the **single writer** to the Active tab, so writes never conflict.
Reads are served from memory and are eventually consistent with the sheet within
the sync interval (seconds). A periodic **reconcile** re-reads the sheet to pick
up any edits made directly in Google Sheets (e.g. a manual correction), while
carefully preserving any writes that haven't synced yet. In normal operation the
sheet converges to exactly what the app holds within a couple of seconds of each
save.
