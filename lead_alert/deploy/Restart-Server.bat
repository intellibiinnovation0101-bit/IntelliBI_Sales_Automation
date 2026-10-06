@echo off
title IntelliBI Lead Alert - Restart Server
REM ============================================================================
REM  Restart the IntelliBI Website Lead Alert service on the OFFICE PC, e.g. after
REM  pulling new code. Right-click -> "Run as administrator" (the service runs as
REM  SYSTEM via the scheduled task "IntelliBI Lead Alert Service").
REM  Counsellor tray apps reconnect by themselves within ~30 seconds.
REM ============================================================================
net session >nul 2>&1
if errorlevel 1 (
    echo Please right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)
set "TASK=IntelliBI Lead Alert Service"

echo [1/3] Stopping the service...
schtasks /End /TN "%TASK%" >nul 2>&1
REM Ending the task can leave python.exe running, so also stop whatever listens on 8787.
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 3 /nobreak >nul

echo [2/3] Starting it again...
schtasks /Run /TN "%TASK%"

echo [3/3] Checking http://localhost:8787/health ...
powershell -NoProfile -Command "Start-Sleep 10; try { (Invoke-WebRequest -UseBasicParsing http://localhost:8787/health).Content } catch { 'Not up yet - wait a minute and open http://localhost:8787/health, or check logs\lead_alert_service.log' }"
echo.
pause
