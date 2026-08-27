# IntelliBI Sales Automation

A **clean, layered, portable** sales pipeline: collect raw communication data
(Interakt + Exotel), consolidate it into a single lead dataset, and generate the
sales-performance and follow-up reports — with centralized config, centralized
logging, and a one-command launcher that e-mails a run summary.

Everything resolves from the project root at run time (`common/paths.py`), so you
can **copy this whole folder to another machine, configure it once, and schedule
it** without editing a single line of source code.

```
Layer 1  sales_data_collection    Interakt users  ||  Exotel inbox -> call details
   |
Layer 2  sales_consolidation      consolidate the 4 sources -> master lead dataset
   |
Layer 3  sales_reports            performance report + follow-up analysis report
```

## 1. Requirements

- **Python 3.10+**
- The packages in `requirements.txt`
- A Google **service account** with access to the source & target sheets
- (Layer 1 auto-login) a one-time **Playwright** browser login for Interakt/Exotel

## 2. Install

```bat
cd IntelliBI_Sales_Automation
python -m venv .venv
.venv\Scripts\activate            REM Windows   (source .venv/bin/activate on Linux/mac)
pip install -r requirements.txt
python -m playwright install chromium
```

## 3. Configure once

1. **Secrets** → put the real files in `credentials/` (see `credentials/README.md`):
   - `service_account.json`
   - `email_config.py`  (copy `email_config.example.py`, add the Gmail app password)
   - Interakt/Exotel session files (`interakt_curl.txt`, `exotel_web_cookie.txt`, browser profiles)
2. **Settings** → edit `config/config.yaml`: Google sheet IDs, input mode, e-mail
   recipients, report toggles, per-script timeout, `stop_on_failure`. Values here
   are applied automatically; the file documents which settings still live inside
   the report scripts.
3. Nothing else. All paths (cache, logs, output, temp) are created automatically
   under the project root.

## 4. Folder structure

```
IntelliBI_Sales_Automation/
├── sales_data_collection/   Layer 1: pyInteraktUsers, pyExotelInboxScrape, pyExotelCallDetails
├── sales_consolidation/     Layer 2: pyConsolidateLeadsLoad
├── sales_reports/           Layer 3: pyConsolidatedLeadPerformanceReport, pyLeadFollowUpAnalysisReport
├── common/                  shared code: paths, config_loader, logging_utils, common_utils,
│                            _bootstrap  +  the pipeline's shared modules (utils, interakt_*, exotel_*)
├── config/                  config.yaml, logging_config.yaml
├── credentials/             secrets & session state (git-ignored)
├── cache/  temp/  logs/     working folders (git-ignored, auto-created)
├── output/reports/          generated report files
├── output/exports/          consolidated CSV/XLSX exports
├── intellibi_lead_cycle/    optional historical training data (git-ignored)
├── scripts/                 run_layer1, run_layer2, run_layer3, run_all
├── requirements.txt  .gitignore  README.md
```

## 5. Run

Each layer standalone (from the project root):

```bat
python scripts\run_layer1.py     REM data collection (Interakt || Exotel Inbox->Calls)
python scripts\run_layer2.py     REM consolidation
python scripts\run_layer3.py     REM reports
```

The **full pipeline** (Layer 1 → 2 → 3, in dependency order):

```bat
python scripts\run_all.py
```

`run_all.py`:
- runs Layer 1's two flows in parallel,
- treats Layer 2 (consolidation) as **critical** — if it fails and
  `pipeline.stop_on_failure` is true, Layer 3 is skipped so no stale numbers get
  published,
- writes a per-script log to `logs/`,
- e-mails a **run summary** (status, timings, record counts, per-layer logs) to
  `email.log_recipients` in `config.yaml` (default
  `info@intellibiinnovationstechnologies.in`),
- exits 0 if every layer succeeded, 1 otherwise.

### Ad-hoc overrides

Any setting can be overridden for a single run via its environment variable
(these win over `config.yaml`), e.g. a dry run that builds locally without
uploading/e-mailing:

```bat
set LFA_DRY_RUN=1
set REPORT_DRY_RUN=1
python scripts\run_layer3.py
```

## 6. Logging

`common/logging_utils.py` sends every script's output to both the console and
`logs/<script>.log`. Log locations are derived from the project root — never
hard-coded. Level is `INFO` (set `SALES_LOG_LEVEL=DEBUG` or edit
`config/logging_config.yaml`). The `logs/` folder is git-ignored and safe to
clear anytime.

## 7. Schedule with Windows Task Scheduler

1. **Create Task** (not *Basic*) → General: "Run whether user is logged on or
   not", "Run with highest privileges".
2. **Triggers** → New → e.g. Daily at 06:30.
3. **Actions** → New → *Start a program*:
   - Program/script: `C:\Users\<you>\Documents\IntelliBI Automation\IntelliBI_Sales_Automation\.venv\Scripts\python.exe`
   - Add arguments: `scripts\run_all.py`
   - **Start in**: `C:\Users\<you>\Documents\IntelliBI Automation\IntelliBI_Sales_Automation`
4. **Settings** → "If the task fails, restart every 5 min, up to 3 times" is a
   good default. The summary e-mail tells you the outcome each run.

Because every path is project-root-relative, the same task definition works
verbatim after you copy the folder to a different machine — just fix the drive/
user portion of the two absolute fields above (or use a relative launcher `.bat`
placed in the project root).

> Tip: a one-line `run_all.bat` in the project root
> (`.venv\Scripts\python.exe scripts\run_all.py`) lets Task Scheduler point at the
> folder with **Start in** set and no absolute python path.
