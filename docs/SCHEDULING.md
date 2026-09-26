# Scheduling — IntelliBI Sales Automation

The Sales pipeline runs the full `scripts/run_all.py` **six times a day**, with
overlap protection so a new run never starts while the previous one is still
going.

| Trigger | 11:00 | 14:00 | 17:00 | 18:45 | 21:00 | 23:00 |
|---------|-------|-------|-------|-------|-------|-------|

Each run executes the complete pipeline in dependency order (Layer 1 → 2 → 3) and
e-mails the detailed summary log to `info@intellibiinnovationstechnologies.in`.

## One-time setup (on the target machine, after deployment)

Open **PowerShell as Administrator**, `cd` into the project folder, and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_schedule.ps1
```

That registers a single Task Scheduler task named **"IntelliBI Sales Automation"**
with the six daily triggers. All paths are derived from the script's own
location, so it works on any machine/folder with nothing to edit. It uses the
project's `.venv\Scripts\python.exe` if present, else `python`.

## Overlap protection (how "no double-run" is guaranteed)

Two independent layers:
1. **Task setting** — `MultipleInstances = IgnoreNew`: Task Scheduler will not
   start a new instance while one is running.
2. **File lock** — `scripts/run_scheduled.py` (the wrapper the task calls) takes
   an OS advisory lock (`cache/scheduler/sales.lock`). If a previous run still
   holds it, the new trigger logs *"a previous run is still in progress —
   skipping"* and exits without launching a second pipeline. The lock is released
   automatically by the OS even if a run crashes, so it never gets stuck.

## What runs

Task action → `python scripts\run_scheduled.py --label sales` → which launches
`scripts\run_all.py`. You get one e-mail per actual run (success or failure);
a skipped (overlapping) trigger is logged in `logs/run_scheduled.log` but does
not e-mail.

## Verify / manage

```powershell
Get-ScheduledTask -TaskName "IntelliBI Sales Automation" | Get-ScheduledTaskInfo   # last result / next run
Start-ScheduledTask -TaskName "IntelliBI Sales Automation"                          # run now (test)
Disable-ScheduledTask -TaskName "IntelliBI Sales Automation"                        # pause
Unregister-ScheduledTask -TaskName "IntelliBI Sales Automation"                     # remove
```

Manual test without the scheduler:
```bat
.venv\Scripts\python.exe scripts\run_scheduled.py --label sales
```

## Manual GUI alternative

If you prefer the Task Scheduler UI: create a task, add six **Daily** triggers
at the times above, Action = *Start a program* → `run_all.bat` with **Start in**
= the project folder, and set *"Do not start a new instance"* under Settings.
(The PowerShell registrar above is preferred because it also wires in the file
lock via `run_scheduled.py`.)

## Failure handling and automatic retry (report layer)

Production logs showed the report process dying on errors that are transient on
Google's side — `HttpError 500 … drive/v3/files … "Internal Error"` while uploading
a report, and `HttpError 503 … "The service is currently unavailable."` while reading
a sheet. One such response, with no retry, ended the whole run (rc=1): reports
later in the same run were never generated or e-mailed, even though the next
scheduled run succeeded. Since 26-Sep-2026 both report scripts and the runner
handle this as follows (tunables in `config.yaml` → `pipeline:`).

1. **Every network call is retried on transient errors** (`common/api_retry.py`):
   HTTP 429/500/502/503/504, rate-limit 403, timeouts, connection resets, SMTP 4xx —
   waits 10s, 20s, 40s, 80s (`api_retry_attempts`, `api_retry_base_wait_sec`).
   Permanent errors (403 permission, 404, bad credentials such as SMTP 535,
   storage quota) fail immediately, exactly as before. Each retry is logged as
   `[retry] <operation>: transient error (…) — retry n/m in Ns`.
2. **A Drive upload retry can never duplicate a file**: before re-sending, the
   script looks for a file with the same name in the target folder and reuses it
   if the failed attempt had in fact been stored.
3. **Each report is delivered as remembered steps** — Drive folder → upload → share
   → masked copy → one e-mail per recipient. A transient failure re-runs only the
   steps still pending (`delivery_retry_attempts`, `delivery_retry_wait_sec`); a
   recipient who was already e-mailed is never e-mailed again.
4. **One failed report no longer aborts the run**: it is logged as
   `[FAILED] <type> report (<period>) — step '<step>' failed: <root error>` and the
   next report (e.g. Weekly / Monthly after Daily) still runs. At the end the script
   prints a `[FAILED] n of m report(s) could not be fully delivered` summary and exits
   **1**. If it failed before anything was uploaded or e-mailed (source read, auth) it
   exits **3**.
5. **The runner (`common_utils.run_script`) re-runs a script only when nothing was
   delivered** (exit 3, or a quota error with no delivery in the output) after
   `report_retry_wait_seconds`, up to `report_retries` times. A run whose output
   shows an upload or a sent e-mail is never re-run automatically — the log says why —
   because a second run would duplicate the reports and e-mails already sent. The
   failure still surfaces in the completion e-mail for follow-up.

Verification script: `python sales_validation\verify_report_retry_handling.py` (no Google access needed).

## Change history
- 2026-08-24 — Added scheduling (5×/day, overlap-protected) via `run_scheduled.py` + `setup_schedule.ps1`.
- 2026-09-26 — Transient-error retry + per-report delivery isolation for the report layer (see "Failure handling and automatic retry"); runner re-runs only when nothing was delivered.
- 2026-09-10 — Schedule changed to 6×/day: added 18:45 and moved 20:00 → 21:00 (now 11:00, 14:00, 17:00, 18:45, 21:00, 23:00). Re-run `setup_schedule.ps1` as Administrator to apply.
