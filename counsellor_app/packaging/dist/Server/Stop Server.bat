@echo off
setlocal
title IntelliBI Counsellor Server - stop
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
  echo.
  echo  Administrator permission was refused - the server was NOT stopped.
  echo  Right-click "Stop Server.bat" ^> Run as administrator and click Yes.
  pause
)
exit /b
:run
cd /d "%~dp0"
echo.
echo  This STOPS the counsellor server and PAUSES its automatic start-up
echo  until you run Restart Server.bat (or Update Server.bat).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_server.ps1"
