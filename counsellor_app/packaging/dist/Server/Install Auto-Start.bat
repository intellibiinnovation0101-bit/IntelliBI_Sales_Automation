@echo off
setlocal
title IntelliBI Counsellor Server - install automatic start-up
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart.ps1"
echo.
pause
