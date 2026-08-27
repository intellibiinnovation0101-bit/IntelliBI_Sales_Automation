<#
================================================================================
  IntelliBI Sales Automation — schedule status dashboard
  ------------------------------------------------------------------------------
  Shows the scheduled task's next run, last run + decoded result, missed count,
  and the tail of the most recent scheduler log.

        powershell -ExecutionPolicy Bypass -File scripts\status.ps1
================================================================================
#>
$ErrorActionPreference = "SilentlyContinue"
$proj     = Split-Path -Parent $PSScriptRoot
$taskName = "IntelliBI Sales Automation"
$logDir   = Join-Path $proj "logs"

function Decode-Result($code) {
  switch ($code) {
    0          { "SUCCESS (0)" }
    267008     { "Ready (never run yet)" }
    267009     { "RUNNING NOW" }
    267010     { "Disabled" }
    267011     { "Not yet run" }
    267012     { "No more scheduled runs" }
    267014     { "Last run terminated" }
    2147750687 { "Skipped - instance already running" }
    $null      { "n/a" }
    default    { "FAILED (0x{0:X})" -f $code }
  }
}

Write-Host "==================================================================="
Write-Host " IntelliBI Sales Automation - schedule status" -ForegroundColor Cyan
Write-Host "==================================================================="

$task = Get-ScheduledTask -TaskName $taskName
if (-not $task) {
  Write-Host "Task '$taskName' is NOT registered. Run scripts\setup_schedule.ps1." -ForegroundColor Yellow
} else {
  $i = $task | Get-ScheduledTaskInfo
  Write-Host ("State        : {0}" -f $task.State)
  Write-Host ("Last run     : {0}" -f $i.LastRunTime)
  Write-Host ("Last result  : {0}" -f (Decode-Result $i.LastTaskResult))
  Write-Host ("Next run     : {0}" -f $i.NextRunTime)
  Write-Host ("Missed runs  : {0}" -f $i.NumberOfMissedRuns)
  Write-Host  "Trigger times: 11:00, 14:00, 17:00, 20:00, 23:00 (daily)"
}

Write-Host ""
Write-Host "--- latest scheduler log (logs\run_scheduled.log) ------------------" -ForegroundColor DarkGray
$log = Join-Path $logDir "run_scheduled.log"
if (Test-Path $log) { Get-Content $log -Tail 15 } else { Write-Host "(no run_scheduled.log yet)" }
Write-Host ""
Write-Host "Tip: History for every firing is in Task Scheduler (taskschd.msc) -> History tab."
