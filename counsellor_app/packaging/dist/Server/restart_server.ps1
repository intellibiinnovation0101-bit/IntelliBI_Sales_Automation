# ===========================================================================
#  IntelliBI Counsellor Server - RESTART  (run via "Restart Server.bat")
#  Use after adding a counsellor (accounts are read at start-up) or after
#  editing config.yaml. Stops the supervised server cleanly and lets the
#  start-up task bring it straight back. No reboot needed.
# ===========================================================================
$ErrorActionPreference = 'Continue'
$Here     = $PSScriptRoot
$TaskName = 'IntelliBI Counsellor Server'

function Get-Port {
    $port = 8600
    $cfg = Join-Path $Here 'config.yaml'
    if (Test-Path $cfg) {
        $m = Select-String -Path $cfg -Pattern '^\s*port\s*:\s*(\d+)' | Select-Object -First 1
        if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
    }
    return $port
}
$Port = Get-Port

Write-Host ''
Write-Host '=== Restarting the IntelliBI Counsellor Server ==='
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*server_watchdog.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process -Name 'IntelliBICounsellorServer' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

try { Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop; Write-Host 'Start-up task started.' }
catch { Write-Warning "Could not start the task '$TaskName' - run 'Install Auto-Start.bat' first."; exit 1 }

$up = $false
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $up = $true; Write-Host "Server is UP:  $($r.Content)"; break }
    } catch {}
}
if (-not $up) { Write-Warning 'Server not answering yet after 2 minutes - check logs\watchdog.log and logs\server.log.' }
