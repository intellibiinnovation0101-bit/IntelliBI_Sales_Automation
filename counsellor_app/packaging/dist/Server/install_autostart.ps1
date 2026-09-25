# ===========================================================================
#  IntelliBI Counsellor Server - AUTOMATIC START-UP INSTALLER
#  Run via "Install Auto-Start.bat" (it asks for administrator permission).
#  Uses only built-in Windows features (Task Scheduler, PowerShell, netsh,
#  powercfg) - nothing to download.
#
#  After this runs ONCE, the server:
#    * starts by itself every time the PC boots - nobody has to log in,
#      double-click anything, or keep a window open,
#    * is restarted automatically if it crashes or hangs (see server_watchdog.ps1),
#    * is reachable through the firewall on its port,
#    * and the PC will not sleep / hibernate / "fast start-up" itself offline.
#  The URL, port, login and data behaviour of the server are unchanged.
# ===========================================================================
$ErrorActionPreference = 'Stop'
$Here     = $PSScriptRoot
$Exe      = Join-Path $Here 'IntelliBICounsellorServer.exe'
$Watchdog = Join-Path $Here 'server_watchdog.ps1'
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

Write-Host ''
Write-Host '=== IntelliBI Counsellor Server - automatic start-up setup ==='
Write-Host "    Folder: $Here"
if (-not (Test-Path $Exe))      { throw "IntelliBICounsellorServer.exe was not found in this folder." }
if (-not (Test-Path $Watchdog)) { throw "server_watchdog.ps1 was not found in this folder." }
$Port     = Get-Port
$RuleName = "IntelliBI Counsellor $Port"

# --- 1) Firewall -------------------------------------------------------------
Write-Host "[1/6] Firewall: allow incoming TCP $Port (all network profiles) ..."
netsh advfirewall firewall delete rule name="$RuleName" | Out-Null
netsh advfirewall firewall add rule name="$RuleName" dir=in action=allow protocol=TCP localport=$Port profile=any | Out-Null

# --- 2) Power: the PC must stay awake while it is on -------------------------
Write-Host '[2/6] Power: never sleep or hibernate; Fast Start-up off; network adapter power-saving off ...'
powercfg /change standby-timeout-ac 0   | Out-Null
powercfg /change standby-timeout-dc 0   | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-dc 0 | Out-Null
powercfg /hibernate off                 | Out-Null
# Fast Start-up makes "Shut down" a hibernate; boot-time tasks may then not run. Off:
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' `
    -Name HiberbootEnabled -PropertyType DWord -Value 0 -Force | Out-Null
# Stop Windows switching the network card off to save power (best effort):
try {
    Get-NetAdapter -Physical -ErrorAction Stop | Where-Object Status -eq 'Up' | ForEach-Object {
        Disable-NetAdapterPowerManagement -Name $_.Name -NoRestart -ErrorAction SilentlyContinue
    }
} catch {}

# --- 3) Port conflict check ---------------------------------------------------
Write-Host "[3/6] Checking nothing else is using port $Port ..."
$conflict = $false
foreach ($c in (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    $pr = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($pr -and $pr.ProcessName -ne 'IntelliBICounsellorServer') {
        $conflict = $true
        Write-Warning "Port $Port is already used by '$($pr.ProcessName)' (PID $($pr.Id)). The server cannot start until that program is stopped, or change 'port:' in config.yaml and re-run this installer."
    }
}
if (-not $conflict) { Write-Host "      OK - port $Port is available." }

# --- 4) Start-up task (runs as SYSTEM: no login, no password, no window) ------
Write-Host "[4/6] Registering start-up task '$TaskName' ..."
$action    = New-ScheduledTaskAction -Execute 'powershell.exe' `
                -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Watchdog`"" `
                -WorkingDirectory $Here
# Same proven trigger set as the IntelliBI Lead Alert service on this PC:
#   * at boot (+30 s so the network stack is up)   -> starts before anyone logs in
#   * at any logon                                  -> belt-and-suspenders
#   * every 5 minutes, forever                      -> if the whole task ever dies,
#     the next tick restarts it (IgnoreNew below means it does NOTHING while the
#     server is already running, so there is never a second copy).
$tBoot  = New-ScheduledTaskTrigger -AtStartup
$tBoot.Delay = 'PT30S'
$tLogon = New-ScheduledTaskTrigger -AtLogOn
$tWatch = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
                -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                -MultipleInstances IgnoreNew -StartWhenAvailable `
                -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -Hidden -Priority 4
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($tBoot, $tLogon, $tWatch) `
    -Principal $principal -Settings $settings `
    -Description 'Keeps the IntelliBI Counsellor web server running: starts at boot without login and restarts it if it crashes or hangs.' | Out-Null

# read back the settings that matter and confirm them
$t   = Get-ScheduledTask -TaskName $TaskName
$etl = $t.Settings.ExecutionTimeLimit
Write-Host "      registered. Runs as: $($t.Principal.UserId)   Triggers: at boot (+30 s), at logon, every 5 min   Time limit: $etl"
if ($etl -ne 'PT0S') {
    Write-Warning "Time limit is '$etl' (expected PT0S = none). Windows would stop the server after that. Fix: Task Scheduler > '$TaskName' > Settings > untick 'Stop the task if it runs longer than'."
} else {
    Write-Host '      OK - no time limit (Windows will never stop it on its own).'
}

# --- 5) Start it now (no reboot needed) ---------------------------------------
Write-Host '[5/6] Starting the server now ...'
Start-ScheduledTask -TaskName $TaskName
$up = $false; $body = ''
for ($i = 0; $i -lt 24; $i++) {                                    # up to 2 minutes
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $up = $true; $body = $r.Content; break }
    } catch {}
}
if ($up) { Write-Host "      OK - server is UP:  $body" }
else     { Write-Warning 'Server not answering after 2 minutes. Look at logs\watchdog.log and logs\server.log in this folder (a missing service-account key or an unshared sheet is the usual cause).' }

# --- 6) The address counsellors use ------------------------------------------
Write-Host '[6/6] Counsellor URL'
$hn  = $env:COMPUTERNAME
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
       Select-Object -ExpandProperty IPAddress
Write-Host "      By PC name (recommended - keeps working if the IP changes):  http://$hn`:$Port/"
foreach ($ip in $ips) { Write-Host "      By IP address:                                               http://$ip`:$Port/" }
$lines = @(
    'IntelliBI Counsellor server address',
    '',
    "Recommended (stable):  http://$hn`:$Port/",
    ''
) + ($ips | ForEach-Object { "By IP address:         http://$_`:$Port/" }) + @(
    '',
    "Generated $(Get-Date).",
    'Give counsellors the PC-name URL. If a counsellor PC cannot open it by name, use',
    'the IP URL and ask IT to give this PC a DHCP reservation / static IP so it never changes.'
)
$lines | Set-Content -Path (Join-Path $Here 'SERVER ADDRESS.txt')

Write-Host ''
Write-Host 'DONE.  The server now starts by itself every time this PC boots - no login, no window.'
Write-Host '       It is restarted automatically if it ever crashes or stops responding.'
Write-Host '       Saved the URLs to  SERVER ADDRESS.txt  in this folder.'
Write-Host "       Run  'Verify Server.bat'  any time to check everything (do it once after a reboot)."
