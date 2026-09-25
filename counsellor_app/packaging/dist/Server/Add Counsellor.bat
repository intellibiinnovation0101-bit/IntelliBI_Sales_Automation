@echo off
setlocal
title IntelliBI Counsellor Server - add a counsellor login
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
echo.
echo  Add a counsellor login (you will be asked for a password).
echo  Counselling By = the exact name written to the sheet's Counselling By column.
echo.
set /p EMAIL=  Login email      : 
set /p NAME=  Display name     : 
set /p CBY=  Counselling By   : 
if "%EMAIL%"=="" goto :bad
if "%NAME%"=="" goto :bad
if "%CBY%"=="" goto :bad
"%~dp0IntelliBICounsellorServer.exe" adduser "%EMAIL%" "%NAME%" "%CBY%"
echo.
echo  Accounts are loaded when the server starts, so it must be restarted to accept this login.
set /p RS=  Restart the server now? [Y/N]: 
if /i "%RS%"=="Y" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_server.ps1"
goto :end
:bad
echo  All three values are required. Nothing was changed.
:end
echo.
pause
