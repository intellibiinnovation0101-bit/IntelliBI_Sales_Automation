# Scheduling — IntelliBI Sales Automation

The Sales pipeline runs the full `scripts/run_all.py` **five times a day**, with
overlap protection so a new run never starts while the previous one is still
going.

| Trigger | 11:00 | 14:00 | 17:00 | 20:00 | 23:00 |
|---------|-------|-------|-------|-------|-------|

Each run executes the complete pipeline in dependency order (Layer 1 → 2 → 3) and
e-mails the detailed summary log to `info@intellibiinnovationstechnologies.in`.

## One-time setup (on the target machine, after deployment)

Open **PowerShell as Administrator**, `cd` into the project folder, and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_schedule.ps1
```

That registers a single Task Scheduler task named **"IntelliBI Sales Automation"**
with the five daily triggers. All paths are derived from the script's own
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

If you prefer the Task Scheduler UI: create a task, add five **Daily** triggers
at the times above, Action = *Start a program* → `run_all.bat` with **Start in**
= the project folder, and set *"Do not start a new instance"* under Settings.
(The PowerShell registrar above is preferred because it also wires in the file
lock via `run_scheduled.py`.)

## Change history
- 2026-08-24 — Added scheduling (5×/day, overlap-protected) via `run_scheduled.py` + `setup_schedule.ps1`.
