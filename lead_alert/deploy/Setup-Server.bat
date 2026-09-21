@echo off
setlocal EnableDelayedExpansion
title IntelliBI Lead Alert - Server Setup
REM This file lives in ...\lead_alert\deploy\  -> project root is two levels up.
set "ROOT=%~dp0..\.."
pushd "%ROOT%"
set "ROOT=%CD%"

echo ============================================================
echo   IntelliBI Website Lead Alert - SERVER setup
echo   Root: %ROOT%
echo   (Run this file as Administrator)
echo ============================================================
echo.

echo [1/5] Python environment + service dependencies...
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>&1
pip install -r "lead_alert\requirements-service.txt"
echo.

echo [2/5] Enrollment code (shared secret counsellors type once)...
if not exist "credentials\lead_alert_secrets.py" (
    copy "credentials\lead_alert_secrets.example.py" "credentials\lead_alert_secrets.py" >nul
    echo   Created credentials\lead_alert_secrets.py - set ENROLLMENT_CODE, save, close Notepad.
    notepad "credentials\lead_alert_secrets.py"
) else (
    echo   Found existing credentials\lead_alert_secrets.py  ^(leaving as-is^)
)
echo.

echo [3/5] Firewall rule for TCP 8787 (Private networks)...
netsh advfirewall firewall show rule name="IntelliBI Lead Alert 8787" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="IntelliBI Lead Alert 8787" dir=in action=allow protocol=TCP localport=8787 profile=private
) else (
    echo   Rule already present.
)
echo.

echo [4/5] Registering auto-start service (starts with Windows)...
powershell -ExecutionPolicy Bypass -File "lead_alert\service\setup_service_schedule.ps1"
powershell -Command "Start-ScheduledTask -TaskName 'IntelliBI Lead Alert Service'"
echo.

echo [5/5] Server address to give counsellors:
for /f "tokens=2 delims=:" %%I in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    set "IP=%%I"
    set "IP=!IP: =!"
    echo        http://!IP!:8787
)
echo.
echo Done. Service is running and will auto-start with Windows.
popd
pause
