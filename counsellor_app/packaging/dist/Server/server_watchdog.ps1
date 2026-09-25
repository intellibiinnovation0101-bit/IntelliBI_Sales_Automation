# ===========================================================================
#  IntelliBI Counsellor Server - WATCHDOG (supervisor)
#  Started automatically at boot by the "IntelliBI Counsellor Server" scheduled
#  task (installed by Install Auto-Start.bat). Runs invisibly as SYSTEM.
#
#  What it does, forever:
#    * starts IntelliBICounsellorServer.exe (hidden, no window, NO keyboard - so
#      it can never sit waiting for "Press Enter"),
#    * if the server EXITS for any reason (crash, no internet yet) -> restarts it
#      in 10 s, and writes a plain-English hint if the cause is missing DNS/internet,
#    * if the server is alive but stops ANSWERING (hang) for ~2 minutes ->
#      kills the WHOLE process tree (the .exe is a launcher + a child) and restarts,
#    * never adopts a stray process that is not actually listening on the port,
#    * writes logs\watchdog.log (events) and logs\server.log (server output),
#      rotating them at 5 MB so the disk never fills.
#  Nothing here changes the URL, port, login or data behaviour of the server.
# ===========================================================================
$ErrorActionPreference = 'Continue'
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here
$Exe     = Join-Path $Here 'IntelliBICounsellorServer.exe'
$ExeName = 'IntelliBICounsellorServer'
$LogDir  = Join-Path $Here 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$WLog    = Join-Path $LogDir 'watchdog.log'      # watchdog events
$Hist    = Join-Path $LogDir 'server.log'        # accumulated server output
$Out     = Join-Path $LogDir 'server.out.log'    # current run (stdout)
$Err     = Join-Path $LogDir 'server.err.log'    # current run (stderr)
$EmptyIn = Join-Path $LogDir 'stdin.empty'       # empty stdin -> the exe never waits for a key
if (-not (Test-Path $EmptyIn)) { New-Item -ItemType File -Path $EmptyIn -Force | Out-Null }

# Tell (newer builds of) the exe it is unattended, so it never pauses for Enter.
$env:INTELLIBI_NO_PAUSE = '1'

function Log([string]$m) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Add-Content -Path $WLog
}
function Rotate([string]$p) {
    if ((Test-Path $p) -and ((Get-Item $p).Length -gt 5MB)) {
        Move-Item -Force $p ($p -replace '\.log$', '.prev.log')
    }
}
function Get-Port {
    $port = 8600
    $cfg = Join-Path $Here 'config.yaml'
    if (Test-Path $cfg) {
        $m = Select-String -Path $cfg -Pattern '^\s*port\s*:\s*(\d+)' | Select-Object -First 1
        if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
    }
    return $port
}
function Server-Procs { @(Get-Process -Name $ExeName -ErrorAction SilentlyContinue) }
function Port-Listening([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function Stop-ServerTree {
    # The one-file .exe runs as a launcher + a child; always stop BOTH.
    foreach ($pr in (Server-Procs)) {
        try { Stop-Process -Id $pr.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    Start-Sleep -Seconds 2
}
function Dns-Hint {
    # After a fast failure, say in plain words whether the PC can resolve Google.
    try {
        $null = [System.Net.Dns]::GetHostAddresses('oauth2.googleapis.com')
        Log "hint: DNS for oauth2.googleapis.com works now - the server should come up on the next try"
    } catch {
        Log "hint: this PC cannot resolve oauth2.googleapis.com right now (no internet/DNS yet). Will keep retrying every 10 s. If this persists: check the network cable / that the Wi-Fi profile is saved for ALL users (not just one login) / the router's DNS."
    }
}

$Port   = Get-Port
$Health = "http://127.0.0.1:$Port/health"
Log "watchdog started (pid $PID) exe=$Exe port=$Port"

while ($true) {
    Rotate $WLog; Rotate $Hist
    # fold the previous run's output into the history log
    foreach ($f in @($Out, $Err)) {
        if (Test-Path $f) {
            try { Get-Content $f | Add-Content -Path $Hist } catch {}
            Remove-Item $f -Force -ErrorAction SilentlyContinue
        }
    }

    $p = $null
    $existing = Server-Procs
    if ($existing.Count -gt 0 -and (Port-Listening $Port)) {
        # A healthy server is already up (e.g. started by hand) - supervise it, don't duplicate it.
        Log "found a running server that is listening on $Port (pid $($existing[0].Id)); supervising it"
    } else {
        if ($existing.Count -gt 0) {
            Log "found $($existing.Count) stale server process(es) NOT listening on $Port - stopping them"
            Stop-ServerTree
        }
        if (-not (Test-Path $Exe)) {
            Log "ERROR: $Exe not found - retrying in 60 s"
            Start-Sleep -Seconds 60
            continue
        }
        Log "starting server"
        try {
            $p = Start-Process -FilePath $Exe -ArgumentList 'serve' -WorkingDirectory $Here `
                    -WindowStyle Hidden -PassThru `
                    -RedirectStandardInput $EmptyIn `
                    -RedirectStandardOutput $Out -RedirectStandardError $Err
            Log "server started (pid $($p.Id))"
        } catch {
            Log "ERROR: could not start server: $($_.Exception.Message) - retrying in 30 s"
            Start-Sleep -Seconds 30
            continue
        }
    }

    # ---- supervise: any server process alive? after a grace period, is /health answering?
    $started = Get-Date
    $fails   = 0
    $reason  = ''
    while ($true) {
        Start-Sleep -Seconds 15
        if ((Server-Procs).Count -eq 0) { $reason = 'process exited'; break }
        if (((Get-Date) - $started).TotalSeconds -lt 90) { continue }   # bootstrap grace
        try {
            $r = Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -eq 200) { $fails = 0 } else { $fails++ }
        } catch { $fails++ }
        if ($fails -ge 8) { $reason = 'unresponsive for ~2 min'; break }     # hang
    }

    $code = 'n/a'
    try { if ($p -and $p.HasExited) { $code = $p.ExitCode } } catch {}
    $ran = [int]((Get-Date) - $started).TotalSeconds
    Log "server stopped ($reason, exit code $code, ran ${ran}s) - restarting in 10 s"
    Stop-ServerTree                                     # never leave a launcher/child behind
    if ($ran -lt 60) { Dns-Hint }                       # died quickly: most likely no internet yet
    Start-Sleep -Seconds 10
}
