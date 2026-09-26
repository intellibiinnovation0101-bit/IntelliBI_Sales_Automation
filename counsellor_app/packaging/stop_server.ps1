# ===========================================================================
#  IntelliBI Counsellor Server - STOP  (run via "Stop Server.bat")
#
#  Stops EVERYTHING that keeps the counsellor server alive, in this order:
#    1. pauses the "IntelliBI Counsellor Server" scheduled task (so its 5-minute
#       trigger cannot bring the server back) and stops its running instance,
#    2. kills the watchdog (server_watchdog.ps1) so it cannot restart the .exe,
#    3. kills the server .exe as a PROCESS TREE (the one-file .exe is a
#       launcher + a child - both must go) and anything still listening on the
#       server port,
#    4. WAITS until no server process is left, the port is free and
#       IntelliBICounsellorServer.exe is no longer locked - i.e. until git or
#       Explorer can replace the file,
#  and then prints PASS or FAIL with exactly what is still holding on, so a
#  failure is never silent.
#
#  Must run as Administrator (the task and the server run as SYSTEM).
#  Automatic start-up stays PAUSED until "Restart Server.bat" / "Update Server.bat".
#  Nothing here touches config.yaml, credentials\ or data\.
#
#  Parameters
#    -Quiet     : no "Press Enter" at the end (used by restart/update scripts)
#    -TimeoutSec: how long to wait for a clean stop (default 45)
#  Exit code: 0 = stopped and unlocked, 1 = something still running/locked,
#             2 = not running as Administrator
# ===========================================================================
param(
    [switch]$Quiet,
    [int]$TimeoutSec = 45
)
$ErrorActionPreference = 'Continue'
$Here     = $PSScriptRoot
$TaskName = 'IntelliBI Counsellor Server'
$ExeName  = 'IntelliBICounsellorServer'
$Exe      = Join-Path $Here "$ExeName.exe"

function Get-Port {
    $port = 8600
    $cfg = Join-Path $Here 'config.yaml'
    if (Test-Path $cfg) {
        $m = Select-String -Path $cfg -Pattern '^\s*port\s*:\s*(\d+)' | Select-Object -First 1
        if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
    }
    return $port
}
function Is-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Server-Procs { @(Get-Process -Name $ExeName -ErrorAction SilentlyContinue) }
function Watchdog-Procs {
    @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*server_watchdog.ps1*' })
}
function Port-Owners([int]$port) {
    @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}
function Exe-Locked {
    # True while some process still has the .exe open (a running image is locked).
    if (-not (Test-Path $Exe)) { return $false }
    try {
        $fs = [System.IO.File]::Open($Exe, 'Open', 'ReadWrite', 'None'); $fs.Close(); return $false
    } catch { return $true }
}
function Describe-Proc([int]$procId) {
    $c = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (-not $c) { return "pid $procId (already gone)" }
    $owner = ''
    try { $o = Invoke-CimMethod -InputObject $c -MethodName GetOwner; if ($o.User) { $owner = "$($o.Domain)\$($o.User)" } } catch {}
    "pid $procId  $($c.Name)  user=$owner  parent=$($c.ParentProcessId)  path=$($c.ExecutablePath)"
}
function Kill-Tree([int]$procId) {
    # taskkill /T takes the whole tree (launcher + child); Stop-Process is the fallback.
    & taskkill.exe /PID $procId /T /F 2>$null | Out-Null
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
function Finish([int]$code) {
    if (-not $Quiet) { Write-Host ''; Read-Host 'Press Enter to close' | Out-Null }
    exit $code
}

$Port = Get-Port
Write-Host ''
Write-Host '=== Stopping the IntelliBI Counsellor Server ===' -ForegroundColor Cyan
Write-Host "    Folder: $Here"
Write-Host "    Port:   $Port"

if (-not (Is-Admin)) {
    Write-Host ''
    Write-Host 'FAIL: this window is NOT running as Administrator.' -ForegroundColor Red
    Write-Host '      The server and its start-up task run as SYSTEM and can only be stopped'
    Write-Host '      from an elevated window. Right-click "Stop Server.bat" > Run as administrator'
    Write-Host '      and click Yes on the Windows prompt.'
    Finish 2
}

# ---- what is running right now (so a failure can be understood) ---------------
Write-Host ''
Write-Host 'Before:' -ForegroundColor DarkGray
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) { Write-Host "  task '$TaskName': state=$($task.State)" } else { Write-Host "  task '$TaskName': not installed" }
$wd = Watchdog-Procs
Write-Host "  watchdog processes: $($wd.Count)"
$sp = Server-Procs
Write-Host "  server processes:   $($sp.Count)"
foreach ($p in $sp) { Write-Host "    $(Describe-Proc $p.Id)" }
$po = Port-Owners $Port
Write-Host "  listening on port ${Port}: $(if ($po.Count) { ($po | ForEach-Object { Describe-Proc $_ }) -join '; ' } else { 'nobody' })"
Write-Host "  exe locked:         $(Exe-Locked)"

if ($sp.Count -eq 0 -and $wd.Count -eq 0 -and $po.Count -eq 0 -and -not (Exe-Locked)) {
    if ($task) { Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null }
    Write-Host ''
    Write-Host 'PASS: nothing was running. Automatic start-up is PAUSED (run Restart Server.bat to resume).' -ForegroundColor Green
    Finish 0
}

# ---- 1) pause + stop the scheduled task -----------------------------------------
Write-Host ''
Write-Host '[1/4] Pausing the start-up task (its 5-minute trigger must not bring the server back) ...'
if ($task) {
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Stop-ScheduledTask    -TaskName $TaskName -ErrorAction SilentlyContinue
    $st = (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue).State
    Write-Host "      task state now: $st"
    if ($st -ne 'Disabled') { Write-Host '      WARNING: the task could not be disabled - it may restart the server within 5 minutes.' -ForegroundColor Yellow }
}

# ---- 2) kill the watchdog ------------------------------------------------------
Write-Host '[2/4] Stopping the watchdog ...'
foreach ($w in (Watchdog-Procs)) {
    Write-Host "      killing $(Describe-Proc $w.ProcessId)"
    Kill-Tree $w.ProcessId
}

# ---- 3) kill the server tree + whoever holds the port -----------------------------
Write-Host '[3/4] Stopping the server process tree ...'
foreach ($p in (Server-Procs)) {
    Write-Host "      killing $(Describe-Proc $p.Id)"
    Kill-Tree $p.Id
}
foreach ($procId in (Port-Owners $Port)) {
    $c = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (-not $c) { continue }
    if ($c.Name -match '^(IntelliBICounsellorServer|python|pythonw|uvicorn)(\.exe)?$') {
        Write-Host "      killing port owner $(Describe-Proc $procId)"
        Kill-Tree $procId
    } else {
        Write-Host "      WARNING: port $Port is held by an unrelated program - not touching it: $(Describe-Proc $procId)" -ForegroundColor Yellow
    }
}

# ---- 4) wait until really stopped and unlocked ------------------------------------
Write-Host "[4/4] Waiting (up to $TimeoutSec s) until no server process is left, port $Port is free and the .exe is unlocked ..."
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$clean = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    $sp = Server-Procs; $wd = Watchdog-Procs; $po = Port-Owners $Port; $lk = Exe-Locked
    if ($sp.Count -eq 0 -and $wd.Count -eq 0 -and $po.Count -eq 0 -and -not $lk) { $clean = $true; break }
    # something came back (or never died): hit it again
    foreach ($w in $wd) { Kill-Tree $w.ProcessId }
    foreach ($p in $sp) { Kill-Tree $p.Id }
}

Write-Host ''
if ($clean) {
    Write-Host 'PASS: server STOPPED, port free, IntelliBICounsellorServer.exe unlocked.' -ForegroundColor Green
    Write-Host '      Automatic start-up is PAUSED (it will not come back after a reboot).'
    Write-Host '      Run Restart Server.bat to start it again, or Update Server.bat to pull + restart.'
    Finish 0
}

Write-Host 'FAIL: the server is NOT fully stopped. Still holding on:' -ForegroundColor Red
$sp = Server-Procs; $wd = Watchdog-Procs; $po = Port-Owners $Port
foreach ($p in $sp) { Write-Host "  server process:  $(Describe-Proc $p.Id)" -ForegroundColor Red }
foreach ($w in $wd) { Write-Host "  watchdog:        $(Describe-Proc $w.ProcessId)" -ForegroundColor Red }
foreach ($o in $po) { Write-Host "  port $Port owner: $(Describe-Proc $o)" -ForegroundColor Red }
if (Exe-Locked) {
    Write-Host "  exe still locked: $Exe" -ForegroundColor Red
    if ($sp.Count -eq 0) {
        Write-Host '     (no server process is left, so the lock is most likely the antivirus scanning'
        Write-Host '      the file, or a process that is still terminating - wait 10 s and run this again;'
        Write-Host '      if it stays locked, restart the PC with the task still paused, then update.)'
    }
}
$st = (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue).State
if ($st -and $st -ne 'Disabled') { Write-Host "  start-up task is '$st' (expected Disabled)" -ForegroundColor Red }
Write-Host ''
Write-Host 'Send the text above to support if this keeps happening.'
Finish 1
