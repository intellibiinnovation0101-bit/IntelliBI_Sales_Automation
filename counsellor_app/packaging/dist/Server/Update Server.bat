@echo off
setlocal
title IntelliBI Counsellor Server - update to the latest build
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
  echo.
  echo  Administrator permission was refused - nothing was changed.
  echo  Right-click "Update Server.bat" ^> Run as administrator and click Yes.
  pause
)
exit /b
:run
cd /d "%~dp0"
echo.
echo  This STOPS the server, pulls the latest build from GitHub (git reset --hard
echo  origin/^<current branch^>), RESTARTS the server and checks its version.
echo  config.yaml, credentials\ and data\ are kept.
REM  "& exit /b" on the SAME line: git may replace this .bat while it runs, and cmd
REM  must not read anything from the file after PowerShell returns.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_server.ps1" & exit /b
