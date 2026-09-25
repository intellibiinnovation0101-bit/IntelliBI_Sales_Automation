@echo off
setlocal
title IntelliBI Counsellor Server - remove automatic start-up
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
echo.
echo  This will STOP the server and remove its automatic start-up.
set /p SURE=  Type YES to continue: 
if /i not "%SURE%"=="YES" goto :end
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t='IntelliBI Counsellor Server'; Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*server_watchdog.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Get-Process -Name IntelliBICounsellorServer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; netsh advfirewall firewall delete rule name='IntelliBI Counsellor 8600' | Out-Null; Write-Host 'Automatic start-up removed and the server stopped. Power settings were left unchanged.'"
:end
echo.
pause
