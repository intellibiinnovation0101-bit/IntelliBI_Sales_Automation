@echo off
setlocal
title IntelliBI Counsellor Server - stop
net session >nul 2>&1
if %errorlevel% equ 0 goto :run
echo.
echo  This step needs administrator permission. A Windows prompt will appear - click Yes.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
echo.
echo  This STOPS the counsellor server and PAUSES its automatic start-up
echo  until you run Restart Server.bat.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t='IntelliBI Counsellor Server'; Disable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null; Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*server_watchdog.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Get-Process -Name IntelliBICounsellorServer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2; if (Get-Process -Name IntelliBICounsellorServer -ErrorAction SilentlyContinue) { Write-Host 'WARNING: a server process is still running.' -ForegroundColor Red } else { Write-Host 'Server STOPPED and automatic start-up PAUSED (it will not come back after a reboot). Run Restart Server.bat to start it again and resume automatic start-up.' -ForegroundColor Yellow }"
echo.
pause
