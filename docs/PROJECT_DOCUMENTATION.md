# IntelliBI Sales Automation — Project Documentation

A clean, layered, **portable** pipeline that collects raw sales/communication
data, consolidates it into a single lead dataset, and generates the sales
performance and follow-up reports — with centralized configuration, centralized
logging, and a one-command launcher that e-mails a run summary.

Everything resolves from the project root at run time, so the whole
`IntelliBI_Sales_Automation/` folder can be copied to another machine,
configured once, and scheduled — **without editing any source-code paths**.

---

## 1. Architecture

```
Layer 1  sales_data_collection    Interakt users  ||  Exotel inbox -> call details
   |                              (two flows run in parallel)
   v
Layer 2  sales_consolidation      merge the 4 sources -> single master lead dataset   [critical]
   |
   v
Layer 3  sales_reports            performance report  +  follow-up analysis report
```

| Layer | Folder | Scripts | Purpose |
|-------|--------|---------|---------|
| 1 | `sales_data_collection/` | `pyInteraktUsers.py`, `pyExotelInboxScrape.py`, `pyExotelCallDetails.py` | Collect raw WhatsApp (Interakt) and call (Exotel) data into their Google Sheets. |
| 2 | `sales_consolidation/` | `pyConsolidateLeadsLoad.py` | De-duplicate & merge the four sources into the single "Consolidate Sales Tracking" master. |
| 3 | `sales_reports/` | `pyConsolidatedLeadPerformanceReport.py`, `pyLeadFollowUpAnalysisReport.py` | Build the Daily/Weekly/Monthly reports, upload to Drive, and e-mail them. |

Per-script details are in `docs/layer1/`, `docs/layer2/`, `docs/layer3/`.

---

## 2. Folder structure

```
IntelliBI_Sales_Automation/
├── sales_data_collection/   Layer 1 entry scripts
├── sales_consolidation/     Layer 2 entry script
├── sales_reports/           Layer 3 entry scripts
├── common/                  shared code + portability layer
│   ├── paths.py             PROJECT_ROOT + all canonical folders (pathlib)
│   ├── _bootstrap.py        sys.path + env defaults + config.yaml (imported first by every script)
│   ├── config_loader.py     reads config/config.yaml -> environment
│   ├── logging_utils.py     centralized logger factory (logs/ + console)
│   ├── common_utils.py      subprocess runner, record-count parsing, summary e-mail
│   └── utils.py, interakt_*.py, exotel_*.py   the pipeline's shared modules
├── config/                  config.yaml, logging_config.yaml
├── credentials/             secrets & session state (git-ignored)
├── cache/  temp/  logs/     working folders (git-ignored, auto-created)
├── output/reports/          generated report files
├── output/exports/          consolidated CSV/XLSX exports
├── intellibi_lead_cycle/    optional historical training data (git-ignored)
├── scripts/                 run_layer1/2/3.py, run_all.py
├── docs/                    this documentation
├── requirements.txt  .gitignore  README.md  run_all.bat
```

---

## 3. Portability — how it works

Every script's first project import is `common/_bootstrap.py`. It:

1. Discovers `PROJECT_ROOT` from its own file location (`common/paths.py` →
   `Path(__file__).resolve().parents[1]`).
2. Puts `common/` and `credentials/` on `sys.path` so the shared modules
   (`utils`, `interakt_common`, `exotel_common`, `email_config`, …) import by
   name exactly as before.
3. Seeds environment-variable **defaults** (only if unset) for every override
   the scripts already honour — service account, output, cache, temp, history —
   all anchored to `PROJECT_ROOT`.
4. Loads `config/config.yaml` and maps operator settings onto those same
   environment variables.
5. Creates the writable working folders.

There are **no absolute machine paths** anywhere in the code. All file access is
derived from the project root or from environment variables.

---

## 4. Configuration

One file: **`config/config.yaml`** (read by `common/config_loader.py`).

Precedence, highest first:

1. A variable already set in the OS environment (ad-hoc run)
2. `config/config.yaml`
3. Project-root path defaults from `_bootstrap.py`

Key sections: `google` (service account), `consolidation` (input mode, sheet
IDs, export dir), `reports` (output dirs, history, dry-run), `interakt`,
`exotel`, `email` (log-summary recipients), `pipeline` (stop-on-failure,
per-script timeout). Some deeply-embedded per-report settings (Drive folder IDs,
`EMAIL_RECIPIENTS`, masking) remain inside the report scripts and are documented
there and in `config.yaml`'s reference block.

`config/logging_config.yaml` sets the log level (env `SALES_LOG_LEVEL` wins).

---

## 5. Credentials

All secrets live in **`credentials/`** (git-ignored via `.gitignore`). See
`credentials/README.md`. Required: `service_account.json`, `email_config.py`
(Gmail sender + app password); plus the Interakt/Exotel session files
(`interakt_curl.txt`, `exotel_web_cookie.txt`) and Playwright browser profiles
for headless auto-login. Nothing secret is stored in `config/` or in code.

---

## 6. Execution

Run a single layer (from the project root):

```bat
python scripts\run_layer1.py     REM Interakt || Exotel Inbox->Calls  (parallel)
python scripts\run_layer2.py     REM consolidation
python scripts\run_layer3.py     REM reports
```

Run the full pipeline in dependency order:

```bat
python scripts\run_all.py        REM  or:  run_all.bat
```

`run_all.py`:
- runs Layer 1's two flows in parallel;
- treats **Layer 2 as critical** — if it fails and `pipeline.stop_on_failure`
  is true, Layer 3 is skipped so no stale numbers are published;
- lets Layer 1 failures pass with a warning (consolidation reads the source
  sheets live; the collectors only refresh them);
- writes each script's output to `logs/`;
- e-mails a **run summary** (per-layer status, timings, record counts, logs
  attached) to `email.log_recipients`
  (default `info@intellibiinnovationstechnologies.in`);
- exits `0` if every layer succeeded, else `1`.

### Ad-hoc overrides

Any run can be tuned via environment variables (they win over `config.yaml`),
e.g. a local dry run without upload/e-mail:

```bat
set LFA_DRY_RUN=1
set REPORT_DRY_RUN=1
python scripts\run_layer3.py
```

---

## 7. Logging & completion e-mail

Two clearly separated channels:

**Detailed technical logs → the `logs/` folder (for developers).**
`common/logging_utils.py` writes every script's full output to both the console
and `logs/<name>.log`: start/end, API calls & errors, exceptions/tracebacks,
warnings, processing detail, **retry information**, and execution duration. The
three collectors also route their internal logs (`interakt_sync.log`,
`exotel_scrape.log`, `exotel_call_sync.log`) into `logs/`. Log locations derive
from the project root; `logs/` is git-ignored and safe to clear. Nothing is
removed from the logs — they are the troubleshooting source of truth.

**Meaningful business summary → the completion e-mail (for management/ops).**
`scripts/run_all.py` sends ONE concise e-mail built by
`common/exec_summary.py` + `common/common_utils.build_summary_html`, with no
debug/technical noise. Top to bottom:

- **Pipeline / Status / Started / Completed / Duration** and a one-line result
  (N succeeded • N failed • N skipped).
- **Execution Summary** — a section per script with *business* KPIs (below).
  Counts are for the **current run** (new / updated / merged / scored / e-mailed),
  parsed from each script's own end-of-run summary — never the whole existing
  dataset.
- **Action Required** — only when something failed or was skipped: process, a
  short business-readable reason (e.g. "Google Sheets API rate limit (429)"),
  and retry status. Full tracebacks stay in the attached log file.

`common/exec_summary.py` derives these KPIs by reading what each script already
prints — **no business logic was changed** to produce them.

### Status criteria
- **SUCCESS** — every executed script succeeded and nothing was skipped.
- **PARTIAL** — mixed (some succeeded, something failed/skipped).
- **FAILED** — every executed script failed.

### Per-script e-mail KPIs (Sales)

| Script | E-mail KPIs (current-run) |
|--------|---------------------------|
| Interakt WhatsApp Users | Users fetched & upserted, New / Updated / Unchanged, Repeat-enquiry updated |
| Exotel Inbox Scrape | Call rows scraped, Notes captured |
| Exotel Call Details | Calls fetched, Notes applied, New / Updated / Unchanged |
| Lead Consolidation | Unique master leads, New leads inserted, Duplicates merged, Total records processed |
| Lead Performance Report | Reports generated, Master rows read, E-mailed |
| Follow-Up Analysis Report | Reports generated, Active leads scored, E-mailed |

A zero-valued KPI is omitted to keep the e-mail clean (except a few where 0 is
itself meaningful, e.g. Reports generated).

---

## 8. Scheduling (Windows Task Scheduler)

1. **Create Task** → General: "Run whether user is logged on or not", highest
   privileges.
2. **Triggers** → Daily (e.g. 06:30).
3. **Actions** → Start a program → `run_all.bat`, with **Start in** set to the
   project folder (so no absolute paths are needed).
4. **Settings** → restart on failure a few times. The summary e-mail reports
   each run's outcome.

Because all paths are project-root-relative, the same task works after copying
the folder to another machine (adjust only the drive/user portion of the
Start-in path).

---

## 9. Dependencies

Python 3.10+ and the packages in `requirements.txt`:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium      REM for Interakt/Exotel auto-login
```

---

## 10. Deploy to a new machine

1. Copy the whole `IntelliBI_Sales_Automation/` folder.
2. Create a venv and `pip install -r requirements.txt` (+ `playwright install chromium`).
3. Put the real secrets in `credentials/` (see `credentials/README.md`).
4. Review `config/config.yaml`.
5. `python scripts\run_all.py` — or schedule `run_all.bat`.

No source-code path edits are ever required.
