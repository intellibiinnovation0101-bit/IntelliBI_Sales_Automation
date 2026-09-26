@echo off
setlocal
title IntelliBI Counsellor Server - restart
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
  echo.
  echo  Administrator permission was refused - the server was NOT restarted.
  echo  Right-click "Restart Server.bat" ^> Run as administrator and click Yes.
  pause
)
exit /b
:run
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_server.ps1"
echo.
pause
