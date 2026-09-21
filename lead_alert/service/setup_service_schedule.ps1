# =============================================================================
#  Register the IntelliBI Website Lead Alert service to run RELIABLY and
#  FULLY AUTOMATICALLY on the office PC. Run ONCE in an elevated PowerShell:
#
#      powershell -ExecutionPolicy Bypass -File setup_service_schedule.ps1
#
#  Robustness built in:
#    * Runs as SYSTEM at STARTUP  -> starts on boot even before anyone logs in.
#    * Also starts AtLogOn        -> belt-and-suspenders.
#    * 5-minute watchdog trigger  -> if the process ever dies, it is restarted
#      within ~5 min (MultipleInstances=IgnoreNew: never a second copy).
#    * StartWhenAvailable + Restart-on-failure + no execution time limit.
#    * All output is logged to logs\lead_alert_service.log.
# =============================================================================
$ErrorActionPreference = "Stop"

$root     = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python   = Join-Path $root ".venv\Scripts\python.exe"
$launcher = Join-Path $root "lead_alert\service\run_service_launcher.bat"

if (-not (Test-Path $python)) {
    Write-Host "Python venv not found at $python" -ForegroundColor Yellow
    Write-Host "Create it first:  python -m venv .venv ; .venv\Scripts\activate ; pip install -r lead_alert\requirements-service.txt"
    exit 1
}

$taskName = "IntelliBI Lead Alert Service"

$action = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $root

$tStart = New-ScheduledTaskTrigger -AtStartup
$tLogon = New-ScheduledTaskTrigger -AtLogOn
# Watchdog: fire every 5 minutes forever; IgnoreNew keeps a single instance.
$tWatch = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
               -LogonType ServiceAccount -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
               -DontStopIfGoingOnBatteries -StartWhenAvailable `
               -MultipleInstances IgnoreNew `
               -RestartInterval (New-TimeSpan -Minutes 2) -RestartCount 3 `
               -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($tStart, $tLogon, $tWatch) -Principal $principal `
    -Settings $settings -Description "IntelliBI Website Lead Alert central service" -Force

Write-Host "Registered '$taskName' — runs as SYSTEM at startup, re-checks every 5 min." -ForegroundColor Green
Write-Host "Starting it now..."
Start-ScheduledTask -TaskName $taskName
Write-Host "Done. Health: http://localhost:8787/health   Log: $root\logs\lead_alert_service.log"
