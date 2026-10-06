@echo off
setlocal
title IntelliBI Lead Alert - Install on this PC
set "HERE=%~dp0"

echo ============================================================
echo   IntelliBI Website Lead Alert - install on THIS computer
echo ============================================================
echo.
echo Closing an older copy of the app (if running)...
taskkill /IM IntelliBILeadAlert.exe /F >nul 2>&1
echo Registering auto-start with Windows...
"%HERE%IntelliBILeadAlert.exe" --install-autostart
echo.
echo Opening the app. If a registration window appears:
echo     Server URL      :  already filled in (from server_url.txt)
echo     Your email      :  your Active counsellor email
echo     Enrollment code :  the shared code from admin
echo.
start "" "%HERE%IntelliBILeadAlert.exe"
echo Done. The tray icon turns GREEN when lead alerts are ON.
pause
