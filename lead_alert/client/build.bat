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
REM  Output: dist\IntelliBILeadAlert.exe  (copy this to each counsellor PC).
REM ============================================================================
setlocal
pyinstaller --noconsole --onefile ^
  --name IntelliBILeadAlert ^
  --hidden-import win32timezone ^
  --collect-submodules pystray ^
  --collect-submodules PIL ^
  lead_alert_client.py
echo.
echo Done. See dist\IntelliBILeadAlert.exe
endlocal
