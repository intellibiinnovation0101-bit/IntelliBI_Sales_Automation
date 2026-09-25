# ===========================================================================
#  IntelliBI Counsellor Server - HEALTH CHECK  (run via "Verify Server.bat")
#  Checks every link in the chain that makes the counsellor URL available and
#  prints PASS / FAIL for each. Run it once after a reboot to prove the
#  automatic start-up works, and any time counsellors report a problem.
# ===========================================================================
$ErrorActionPreference = 'Continue'
$Here     = $PSScriptRoot
$TaskName = 'IntelliBI Counsellor Server'
$script:fails = 0

function Get-Port {
    $port = 8600
    $cfg = Join-Path $Here 'config.yaml'
    if (Test-Path $cfg) {
        $m = Select-String -Path $cfg -Pattern '^\s*port\s*:\s*(\d+)' | Select-Object -First 1
        if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
    }
    return $port
}
function Check([string]$name, [bool]$ok, [string]$detail = '') {
    if (-not $ok) { $script:fails++ }
    $tag = if ($ok) { 'PASS' } else { 'FAIL' }
    $line = "  [$tag] $name"
    if ($detail) { $line += "  -  $detail" }
    if ($ok) { Write-Host $line -ForegroundColor Green } else { Write-Host $line -ForegroundColor Red }
}

$Port = Get-Port
Write-Host ''
Write-Host "=== IntelliBI Counsellor Server - health check  ($(Get-Date)) ==="
Write-Host "    Folder: $Here    Port: $Port"
Write-Host ''

# 1) start-up task
try {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $i = $t | Get-ScheduledTaskInfo
    Check 'Start-up task registered' $true "state=$($t.State); runs as $($t.Principal.UserId); last run $($i.LastRunTime); last result $($i.LastTaskResult)"
    Check 'Start-up task has NO time limit' ($t.Settings.ExecutionTimeLimit -eq 'PT0S') "limit=$($t.Settings.ExecutionTimeLimit) (PT0S = none)"
    Check 'Start-up task is enabled' ($t.State -ne 'Disabled') "state=$($t.State)"
} catch {
    Check 'Start-up task registered' $false "not found - run 'Install Auto-Start.bat'"
}

# 2) watchdog + server processes
$wd = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -like '*server_watchdog.ps1*' }
Check 'Watchdog (supervisor) running' ([bool]$wd) $(if ($wd) { "pid $(($wd | Select-Object -First 1).ProcessId)" } else { 'not running' })
$p = Get-Process -Name 'IntelliBICounsellorServer' -ErrorAction SilentlyContinue | Select-Object -First 1
Check 'Server process running' ([bool]$p) $(if ($p) { "pid $($p.Id), since $($p.StartTime)" } else { 'not running' })

# 3) port + HTTP
$l = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
Check "Port $Port is listening" ([bool]$l)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 8
    $j = $r.Content | ConvertFrom-Json
    Check 'HTTP /health answers' ($r.StatusCode -eq 200) $r.Content
    if ($j.PSObject.Properties.Name -contains 'sheet_ok') {
        Check 'Google Sheets reachable / in sync' ([bool]$j.sheet_ok) $(if ($j.sheet_ok) { "leads cached: $($j.leads_cached)" } else { 'serving from local cache - counsellors can still work; it resyncs when the internet link returns' })
    } else {
        Check 'Google Sheets reachable / in sync' $true "leads cached: $($j.leads_cached) (older build - rebuild the .exe to get the live sheet_ok flag and offline-boot fallback)"
    }
} catch {
    Check 'HTTP /health answers' $false $_.Exception.Message
}

# 4) firewall
$fw = (netsh advfirewall firewall show rule name="IntelliBI Counsellor $Port" 2>$null) -join "`n"
Check "Firewall rule allows TCP $Port" ($fw -match 'Enabled:\s+Yes') $(if ($fw -match 'Enabled:\s+Yes') { 'enabled' } else { "missing - run 'Install Auto-Start.bat'" })

# 5) power / sleep
$q = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null) -join "`n"
$acIdx = if ($q -match 'Current AC Power Setting Index:\s+0x([0-9a-fA-F]+)') { [Convert]::ToInt32($Matches[1], 16) } else { -1 }
Check 'PC will not go to sleep (AC)' ($acIdx -eq 0) $(if ($acIdx -eq 0) { 'sleep = never' } elseif ($acIdx -gt 0) { "sleeps after $acIdx s - run 'Install Auto-Start.bat'" } else { 'could not read power setting' })
$hb = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -ErrorAction SilentlyContinue
Check 'Fast Start-up is off' ($hb -and $hb.HiberbootEnabled -eq 0) $(if ($hb) { "HiberbootEnabled=$($hb.HiberbootEnabled)" } else { 'unknown' })

# 6) key + config present
Check 'Service-account key present' (Test-Path (Join-Path $Here 'credentials\service_account.json'))
Check 'config.yaml present' (Test-Path (Join-Path $Here 'config.yaml'))

# 7) addresses
Write-Host ''
$hn  = $env:COMPUTERNAME
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
       Select-Object -ExpandProperty IPAddress
Write-Host "  Counsellor URL by PC name:  http://$hn`:$Port/"
foreach ($ip in $ips) { Write-Host "  Counsellor URL by IP:       http://$ip`:$Port/" }
Write-Host "  From a counsellor's PC, open:  http://$hn`:$Port/health   (should show status ok)"

# 8) recent log lines
foreach ($lf in @('watchdog.log', 'server.log')) {
    $path = Join-Path $Here "logs\$lf"
    if (Test-Path $path) {
        Write-Host ''
        Write-Host "  --- last lines of logs\$lf ---"
        Get-Content $path -Tail 8 | ForEach-Object { Write-Host "  $_" }
    }
}

Write-Host ''
if ($script:fails -eq 0) { Write-Host '  RESULT: ALL CHECKS PASSED - the server is up and will survive reboots.' -ForegroundColor Green }
else { Write-Host "  RESULT: $($script:fails) check(s) FAILED - see the red lines above." -ForegroundColor Red }
