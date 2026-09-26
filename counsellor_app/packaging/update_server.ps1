# ===========================================================================
#  IntelliBI Counsellor Server - UPDATE  (run via "Update Server.bat")
#
#  One double-click does the whole "get the latest server" routine on the
#  office PC, in the only order that works:
#    1. STOP the server completely (stop_server.ps1) - git cannot replace a
#       running .exe ("Unlink of file ... failed"),
#    2. git fetch + reset the repository to the latest origin/<branch>
#       (the branch this PC is on, or -Branch),
#    3. RESTART the server (restart_server.ps1) - automatic start-up is ON again,
#    4. verify: /health must report the APP_VERSION of the code just pulled.
#  If anything fails AFTER the stop, the server is restarted again so the
#  office is never left without it, and the failure is printed in red.
#
#  This Server folder must live inside the git repository
#  (...\IntelliBI_Sales_Automation\counsellor_app\packaging\dist\Server).
#  config.yaml, credentials\ and data\ are untracked and are never touched.
#  Local edits to TRACKED files are discarded (same as the manual
#  "git reset --hard origin/dev" this replaces).
#
#  Must run as Administrator.  Exit code 0 = updated and verified.
# ===========================================================================
param(
    [string]$Branch = ''
)
$ErrorActionPreference = 'Continue'
$env:GIT_ASK_YESNO = 'false'          # never hang on "Unlink failed. Should I try again? (y/n)"
$Here     = $PSScriptRoot
$ExeName  = 'IntelliBICounsellorServer'
$Exe      = Join-Path $Here "$ExeName.exe"
$Stop     = Join-Path $Here 'stop_server.ps1'
$Restart  = Join-Path $Here 'restart_server.ps1'

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
function Run-Git([string[]]$GitArgs) {
    # stderr merged into stdout so git's progress text is not shown as errors
    $out = & cmd.exe /c "git -C `"$Root`" $($GitArgs -join ' ') 2>&1"
    return @{ code = $LASTEXITCODE; out = ($out -join "`n") }
}
function Health-Version([int]$port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 5
        $j = $r.Content | ConvertFrom-Json
        if ($j.version) { return [string]$j.version } else { return '(build without version stamp)' }
    } catch { return '(not answering)' }
}
function Exe-Stamp { if (Test-Path $Exe) { (Get-Item $Exe).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { '(missing)' } }
function Fail([string]$msg, [bool]$restart) {
    Write-Host ''
    Write-Host "FAIL: $msg" -ForegroundColor Red
    if ($restart -and (Test-Path $Restart)) {
        Write-Host '      Restarting the server so the office is not left without it ...' -ForegroundColor Yellow
        & $Restart
    }
    Write-Host ''
    Read-Host 'Press Enter to close' | Out-Null
    exit 1
}

$Port = Get-Port
Write-Host ''
Write-Host '=== Updating the IntelliBI Counsellor Server ===' -ForegroundColor Cyan
Write-Host "    Folder: $Here"

if (-not (Is-Admin)) { Fail 'this window is NOT running as Administrator. Right-click "Update Server.bat" > Run as administrator.' $false }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'git is not installed / not on PATH on this PC.' $false }

# ---- locate the repository this Server folder lives in ---------------------------
$Root = (& git -C "$Here" rev-parse --show-toplevel 2>$null)
if (-not $Root) {
    Fail "this Server folder is not inside the git repository, so git cannot update it.`n      Either run Update Server.bat from ...\counsellor_app\packaging\dist\Server inside the repository,`n      or copy the new IntelliBICounsellorServer.exe into this folder by hand after Stop Server.bat." $false
}
$Root = $Root -replace '/', '\'
if (-not $Branch) { $Branch = (& git -C "$Root" rev-parse --abbrev-ref HEAD 2>$null) }
if (-not $Branch -or $Branch -eq 'HEAD') { Fail 'could not tell which branch this PC is on - pass -Branch dev (or main / prod).' $false }

$before = (& git -C "$Root" rev-parse --short HEAD 2>$null)
Write-Host "    Repo:   $Root"
Write-Host "    Branch: $Branch   (now at $before)"
Write-Host "    Exe:    $(Exe-Stamp)   running version: $(Health-Version $Port)"

# ---- 1) stop ---------------------------------------------------------------------
Write-Host ''
Write-Host '--- Step 1/4: stop the server -------------------------------------------' -ForegroundColor Cyan
if (-not (Test-Path $Stop)) { Fail "stop_server.ps1 not found next to this script." $false }
& $Stop -Quiet -TimeoutSec 60
if ($LASTEXITCODE -ne 0) { Fail 'the server could not be stopped/unlocked, so the update was NOT attempted (see above).' $true }

# ---- 2) fetch + reset ------------------------------------------------------------
Write-Host ''
Write-Host "--- Step 2/4: git fetch + reset --hard origin/$Branch ------------------" -ForegroundColor Cyan
$r = Run-Git @('fetch', 'origin', '--prune')
if ($r.code -ne 0) { Write-Host $r.out; Fail 'git fetch failed (no internet / GitHub login?). Nothing was changed.' $true }

$dirty = (& git -C "$Root" status --porcelain 2>$null)
if ($dirty) {
    $n = @($dirty).Count
    Write-Host "    note: $n locally modified tracked file(s) will be discarded (untracked files such as config.yaml, credentials\, data\ are kept):" -ForegroundColor Yellow
    @($dirty) | Select-Object -First 8 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    if ($n -gt 8) { Write-Host "      ... and $($n - 8) more" -ForegroundColor DarkGray }
}
$cur = (& git -C "$Root" rev-parse --abbrev-ref HEAD 2>$null)
if ($cur -ne $Branch) {
    $r = Run-Git @('checkout', '-f', $Branch)
    if ($r.code -ne 0) { Write-Host $r.out; Fail "git checkout $Branch failed." $true }
}
$r = Run-Git @('reset', '--hard', "origin/$Branch")
Write-Host $r.out
if ($r.code -ne 0 -or $r.out -match 'Unlink of file|Permission denied|error:') {
    Fail "git reset --hard origin/$Branch failed - a file is still locked (see above). Run Stop Server.bat, wait 10 s, then Update Server.bat again." $true
}
$after = (& git -C "$Root" rev-parse --short HEAD 2>$null)
Write-Host "    repository: $before -> $after"
Write-Host "    exe:        $(Exe-Stamp)"

# expected version = APP_VERSION in the source just pulled
$expected = ''
$cfgPy = Join-Path $Root 'counsellor_app\app\config.py'
if (Test-Path $cfgPy) {
    $m = Select-String -Path $cfgPy -Pattern '^\s*APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($m) { $expected = $m.Matches[0].Groups[1].Value }
}

# ---- 3) restart ------------------------------------------------------------------
Write-Host ''
Write-Host '--- Step 3/4: restart the server ----------------------------------------' -ForegroundColor Cyan
if (-not (Test-Path $Restart)) { Fail 'restart_server.ps1 not found next to this script - start the server by hand (Install Auto-Start.bat).' $false }
& $Restart

# ---- 4) verify -------------------------------------------------------------------
Write-Host ''
Write-Host '--- Step 4/4: verify ------------------------------------------------------' -ForegroundColor Cyan
$running = Health-Version $Port
Write-Host "    running version:  $running"
Write-Host "    expected version: $(if ($expected) { $expected } else { '(APP_VERSION not found in source)' })"
Write-Host ''
if ($running -eq '(not answering)') {
    Fail 'the server is not answering on /health after the restart - check logs\watchdog.log and logs\server.log.' $false
} elseif ($expected -and $running -ne $expected) {
    Write-Host "WARNING: the running .exe reports '$running' but the source is '$expected'." -ForegroundColor Yellow
    Write-Host '         The .exe in origin was not rebuilt after that source change: rebuild it on the'
    Write-Host '         build PC (packaging\build_windows.bat), push, and run Update Server.bat again.'
    Read-Host 'Press Enter to close' | Out-Null
    exit 1
} else {
    Write-Host "PASS: server updated to $after and running version $running." -ForegroundColor Green
    Write-Host '      Counsellors get the new page on their next load (Ctrl+F5 if a page looks old).'
    Read-Host 'Press Enter to close' | Out-Null
    exit 0
}
