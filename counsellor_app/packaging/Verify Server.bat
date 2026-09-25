@echo off
setlocal
title IntelliBI Counsellor Server - health check
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_server.ps1"
echo.
pause
