# IntelliBI Counsellor Lead Management System (Counsellor App)

A fast, robust web application that lets counsellors search a lead by mobile
number, see the current details **and full interaction history**, update the
lead, and save — with the save acknowledged in milliseconds.

It sits **in front of the existing Google Sheet** (the same "IntelliBI Lead
Information" Data sheet the current Google Form writes to). Google Sheets stays
the system of record, so **everything that works today keeps working**: the
Python consolidation (`pyConsolidateLeadsLoad.py`), the Follow-Up analysis
report, and the ML conversion model all keep reading the same sheet, unchanged.

This folder is **self-contained and completely separate** from the production
system. Nothing here modifies the existing `.gs` scripts, the consolidation, or
the reports. You can run, stop, or delete this app without any impact on current
operations.

---

## Why it is fast (and safe)

| Operation | How it's served | Typical latency |
|-----------|-----------------|-----------------|
| Search / view a lead | Pure in-memory index (RAM) | ~2 microseconds in-process; ~3 ms over HTTP |
| Save an update | In-memory + durable local journal, **instant ack** | ~1–6 ms |
| Sync to Google Sheet | Background write-behind worker | a second or two later, automatically |

Reads never touch Google's API, so they are effectively instant even with
thousands of leads (measured: 8,000 leads bootstrap in ~200 ms, reads ~2 µs,
saves sub-millisecond). Writes are journaled to a local SQLite file **before**
the counsellor is told "Saved", so a crash or restart never loses a write — on
restart the app replays any un-synced writes and pushes them to the sheet.

---

## Documentation

Read these in order the first time. They are written so you can set up, deploy,
maintain, and troubleshoot the system independently.

1. [`docs/01-architecture.md`](docs/01-architecture.md) — architecture & folder structure
2. [`docs/02-configuration.md`](docs/02-configuration.md) — configuration & prerequisites
3. [`docs/03-installation.md`](docs/03-installation.md) — installation / setup
4. [`docs/04-authentication.md`](docs/04-authentication.md) — authentication & access
5. [`docs/05-google-sheets.md`](docs/05-google-sheets.md) — Google Sheets / API configuration
6. [`docs/06-running.md`](docs/06-running.md) — how to run the system
7. [`docs/07-deployment.md`](docs/07-deployment.md) — step-by-step deployment guide
8. [`docs/08-validation.md`](docs/08-validation.md) — validation suite
9. [`docs/09-troubleshooting.md`](docs/09-troubleshooting.md) — troubleshooting
10. [`docs/10-maintenance.md`](docs/10-maintenance.md) — maintenance & future enhancements

---

## 60-second quick start (offline demo, no credentials needed)

```bash
cd counsellor_app
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --fake                               # starts on http://localhost:8600
```

Open http://localhost:8600, log in with a demo account (see
`docs/06-running.md`), search `9876543210`, edit, and Save. The `--fake` flag
uses an in-memory sheet so you can try the whole flow without touching Google.

To run against the **real** Google Sheet, follow `docs/03` → `docs/05`, then run
`python run.py`.
