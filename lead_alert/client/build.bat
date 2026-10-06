@echo off
REM ============================================================================
REM  Build the IntelliBI Lead Alert client into a single, no-console .exe.
REM  Run this ONCE on a build machine that has the client venv set up:
REM
REM     cd lead_alert\client
REM     python -m venv .venv
REM     .venv\Scripts\activate
REM     pip install -r ..\requirements-client.txt
REM     build.bat
REM
REM  Output: dist\IntelliBILeadAlert.exe, also copied to ..\deploy\ (the copy
REM  counsellors install from), so the shipped exe always matches the code.
REM ============================================================================
setlocal
pyinstaller --noconsole --onefile ^
  --name IntelliBILeadAlert ^
  --hidden-import win32timezone ^
  --collect-submodules pystray ^
  --collect-submodules PIL ^
  lead_alert_client.py
if errorlevel 1 (
    echo BUILD FAILED - deploy\IntelliBILeadAlert.exe left unchanged.
    exit /b 1
)
copy /Y "dist\IntelliBILeadAlert.exe" "..\deploy\IntelliBILeadAlert.exe" >nul
echo.
echo Done. dist\IntelliBILeadAlert.exe  (copied to ..\deploy\)
endlocal
