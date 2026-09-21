@echo off
setlocal
title IntelliBI Lead Alert - Install on this PC
set "HERE=%~dp0"

echo ============================================================
echo   IntelliBI Website Lead Alert - install on THIS computer
echo ============================================================
echo.
echo Registering auto-start with Windows...
"%HERE%IntelliBILeadAlert.exe" --install-autostart
echo.
echo Opening the app. In the small window that appears, enter:
echo     Server URL      :  http://OFFICE-PC-IP:8787
echo     Your email      :  your Active counsellor email
echo     Enrollment code :  the shared code from admin
echo.
start "" "%HERE%IntelliBILeadAlert.exe"
echo You may close this window after registering. The app sits in the system tray.
pause
