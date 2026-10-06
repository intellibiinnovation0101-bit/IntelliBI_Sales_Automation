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

echo [3/5] Firewall rule for TCP 8787 (ALL network types, local subnet only)...
REM Must not be limited to "Private": Windows often classifies office Wi-Fi as
REM "Public", which silently blocked every counsellor PC (2026-10-06).
netsh advfirewall firewall show rule name="IntelliBI Lead Alert 8787" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="IntelliBI Lead Alert 8787" dir=in action=allow protocol=TCP localport=8787 profile=any remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
) else (
    netsh advfirewall firewall set rule name="IntelliBI Lead Alert 8787" new enable=yes profile=any remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
)
REM LAN discovery: counsellor apps find this PC again after its IP changes.
netsh advfirewall firewall delete rule name="IntelliBI Lead Alert discovery" >nul 2>&1
netsh advfirewall firewall add rule name="IntelliBI Lead Alert discovery" dir=in action=allow protocol=UDP localport=8788 profile=any remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
echo.

echo Keeping this PC awake on mains power (alerts stop while the server sleeps)...
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
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
echo   This computer's name (put it in config.yaml lead_alert.server_machine): %COMPUTERNAME%
echo.
echo Done. Service is running and will auto-start with Windows.
echo Check: http://localhost:8787/health  ("network.ok" must be true)
popd
pause
