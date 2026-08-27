<#
================================================================================
  IntelliBI Sales Automation — Task Scheduler registrar
  ------------------------------------------------------------------------------
  Registers ONE scheduled task that runs the full Sales pipeline five times a
  day (11:00, 14:00, 17:00, 20:00, 23:00). Overlap protection is enforced two
  ways: the task's MultipleInstances policy is IgnoreNew, AND scripts/run_scheduled.py
  holds an OS file lock — so a new trigger never starts while a previous run is
  still in progress.

  RUN THIS ONCE, from an **elevated (Administrator) PowerShell**, on the target
  machine after deployment:

        powershell -ExecutionPolicy Bypass -File scripts\setup_schedule.ps1

  All paths are derived from this script's own location, so it works verbatim on
  any machine / any folder — nothing to edit.
================================================================================
#>
$ErrorActionPreference = "Stop"

$proj    = Split-Path -Parent $PSScriptRoot          # project root (scripts\ -> parent)
$wrapper = Join-Path $PSScriptRoot "run_scheduled.py"
$py      = Join-Path $proj ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$taskName = "IntelliBI Sales Automation"
$times    = @("11:00","14:00","17:00","20:00","23:00")

Write-Host "Project : $proj"
Write-Host "Python  : $py"
Write-Host "Task    : $taskName  @ $($times -join ', ')"

$action   = New-ScheduledTaskAction -Execute $py `
              -Argument "`"$wrapper`" --label sales" -WorkingDirectory $proj
$triggers = foreach ($t in $times) { New-ScheduledTaskTrigger -Daily -At $t }
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
              -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
              -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "OK - '$taskName' registered (runs whether logged on or not, overlap-protected)."
Write-Host "Verify:  Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
