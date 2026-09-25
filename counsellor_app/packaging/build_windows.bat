@echo off
REM ===========================================================================
REM  Build IntelliBICounsellorServer.exe  (run this ONCE on any Windows PC that
REM  has Python 3.10+; the resulting .exe then runs on office PCs WITHOUT Python)
REM
REM  Usage:  double-click this file, or run it from a terminal in the
REM          counsellor_app\packaging folder.
REM  Output: counsellor_app\packaging\dist\IntelliBICounsellorServer.exe
REM          plus a ready-to-copy "Server" folder next to it.
REM ===========================================================================
setlocal
cd /d "%~dp0\.."                                 REM -> counsellor_app\

echo(
echo === [1/5] Checking Python ===
python --version 1>nul 2>nul || (
  echo Python was not found on this PC. Install Python 3.10+ from python.org
  echo ^(tick "Add Python to PATH" during install^), then run this again.
  pause & exit /b 1
)

echo(
echo === [2/5] Creating a clean build environment ===
if exist build_venv rmdir /s /q build_venv
python -m venv build_venv
call build_venv\Scripts\activate.bat
python -m pip install --upgrade pip 1>nul

echo(
echo === [3/5] Installing dependencies + PyInstaller ===
pip install -r requirements.txt pyinstaller tzdata || (echo pip install failed & pause & exit /b 1)

echo(
echo === [4/5] Building the single-file server .exe (this takes a few minutes) ===
pyinstaller --noconfirm --clean --onefile ^
  --name IntelliBICounsellorServer ^
  --collect-all uvicorn ^
  --collect-all anyio ^
  --collect-all certifi ^
  --collect-all bcrypt ^
  --collect-all gspread ^
  --collect-all google.auth ^
  --collect-all google.oauth2 ^
  --collect-all tzdata ^
  --collect-submodules app ^
  --hidden-import app.web.ui ^
  --distpath packaging\dist ^
  --workpath packaging\build ^
  --specpath packaging ^
  serve_entry.py || (echo Build failed & pause & exit /b 1)

echo(
echo === [5/5] Assembling a ready-to-copy "Server" folder ===
set OUT=packaging\dist\Server
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%" "%OUT%\credentials" "%OUT%\data"
copy /y packaging\dist\IntelliBICounsellorServer.exe "%OUT%\" 1>nul
copy /y config.example.yaml "%OUT%\config.example.yaml" 1>nul
copy /y packaging\READ_ME_FIRST_Server.txt "%OUT%\READ ME FIRST.txt" 1>nul 2>nul

echo(
echo ===========================================================================
echo  DONE.
echo  Give the office PC this whole folder:
echo     %CD%\packaging\dist\Server
echo  It contains IntelliBICounsellorServer.exe and empty credentials\ + data\.
echo  See docs\11-exe-and-office-pc-deployment.md for the next steps.
echo ===========================================================================
pause
