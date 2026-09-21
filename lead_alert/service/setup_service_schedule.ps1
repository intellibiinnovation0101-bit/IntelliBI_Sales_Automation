# =============================================================================
#  Register the IntelliBI Website Lead Alert service to start with Windows.
#  Run this ONCE in an elevated PowerShell on the office PC that hosts the
#  service. It creates a Scheduled Task that launches the service at logon and
#  keeps it running. (The service idles outside the configured active window, so
#  there is no need to stop/start it around 09:30-23:00.)
#
#      powershell -ExecutionPolicy Bypass -File setup_service_schedule.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

# Project root = two levels up from this script (lead_alert\service\ -> root)
$root   = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "lead_alert\service\run_service.py"

if (-not (Test-Path $python)) {
    Write-Host "Python venv not found at $python" -ForegroundColor Yellow
    Write-Host "Create it first:  python -m venv .venv ; .venv\Scripts\activate ; pip install -r lead_alert\requirements-service.txt"
    exit 1
}

$taskName = "IntelliBI Lead Alert Service"
$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 2) -RestartCount 3

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "IntelliBI Website Lead Alert central service" -Force

Write-Host "Registered scheduled task: '$taskName' (starts at logon)." -ForegroundColor Green
Write-Host "Start it now with:  Start-ScheduledTask -TaskName '$taskName'"
