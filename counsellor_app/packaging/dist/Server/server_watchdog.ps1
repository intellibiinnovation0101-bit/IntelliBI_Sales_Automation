# ===========================================================================
#  IntelliBI Counsellor Server - WATCHDOG (supervisor)
#  Started automatically at boot by the "IntelliBI Counsellor Server" scheduled
#  task (installed by Install Auto-Start.bat). Runs invisibly as SYSTEM.
#
#  What it does, forever:
#    * starts IntelliBICounsellorServer.exe (hidden, no window),
#    * if the server EXITS for any reason (crash, error) -> restarts it in 10 s,
#    * if the server is alive but stops ANSWERING (hang) for ~2 minutes ->
#      kills it and restarts it,
#    * writes logs\watchdog.log (events) and logs\server.log (server output),
#      rotating them at 5 MB so the disk never fills.
#  Nothing here changes the URL, port, login or data behaviour of the server.
# ===========================================================================
$ErrorActionPreference = 'Continue'
$Here   = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here
$Exe    = Join-Path $Here 'IntelliBICounsellorServer.exe'
$LogDir = Join-Path $Here 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$WLog   = Join-Path $LogDir 'watchdog.log'      # watchdog events
$Hist   = Join-Path $LogDir 'server.log'        # accumulated server output
$Out    = Join-Path $LogDir 'server.out.log'    # current run (stdout)
$Err    = Join-Path $LogDir 'server.err.log'    # current run (stderr)

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

    # If a server is ALREADY running (e.g. someone double-clicked the .exe),
    # never start a second copy on the same port - just supervise that one.
    $p = Get-Process -Name 'IntelliBICounsellorServer' -ErrorAction SilentlyContinue |
         Select-Object -First 1
    if ($p) {
        Log "found an already-running server (pid $($p.Id)); supervising it"
    } else {
        if (-not (Test-Path $Exe)) {
            Log "ERROR: $Exe not found - retrying in 60 s"
            Start-Sleep -Seconds 60
            continue
        }
        Log "starting server"
        try {
            $p = Start-Process -FilePath $Exe -ArgumentList 'serve' -WorkingDirectory $Here `
                    -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput $Out -RedirectStandardError $Err
            Log "server started (pid $($p.Id))"
        } catch {
            Log "ERROR: could not start server: $($_.Exception.Message) - retrying in 30 s"
            Start-Sleep -Seconds 30
            continue
        }
    }

    # ---- supervise: wait for exit; after a start-up grace period, probe /health
    #      so a HUNG (alive but unresponsive) server is also recovered.
    $started = Get-Date
    $fails   = 0
    while (-not $p.HasExited) {
        Start-Sleep -Seconds 15
        if (((Get-Date) - $started).TotalSeconds -lt 90) { continue }   # bootstrap grace
        try {
            $r = Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -eq 200) { $fails = 0 } else { $fails++ }
        } catch { $fails++ }
        if ($fails -ge 8) {                                              # ~2 min unresponsive
            Log "server (pid $($p.Id)) unresponsive for ~2 min - killing it to recover"
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
            Start-Sleep -Seconds 3
            break
        }
    }

    $code = 'n/a'
    try { if ($p.HasExited) { $code = $p.ExitCode } } catch {}
    Log "server stopped (pid $($p.Id), exit code $code) - restarting in 10 s"
    Start-Sleep -Seconds 10
}
