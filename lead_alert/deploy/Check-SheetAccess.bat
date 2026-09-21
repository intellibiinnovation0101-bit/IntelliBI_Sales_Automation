@echo off
title IntelliBI - Sheet Access Check
REM This file lives in ...\lead_alert\deploy\  -> project root is two levels up.
set "ROOT=%~dp0..\.."
pushd "%ROOT%"
echo Project root: %CD%
echo.
echo Testing whether the service account can READ the Contact Us Form sheet...
echo.
".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'lead_alert/service'); import google_io; print('ROW COUNT =', google_io.source_row_count())"
echo.
echo ------------------------------------------------------------
echo  A number (e.g. ROW COUNT = 15) = the service CAN read the sheet.
echo  'permission' error with ROW COUNT = -1 = share the sheet with
echo  the service account as Viewer (see chat).
echo ------------------------------------------------------------
popd
pause
