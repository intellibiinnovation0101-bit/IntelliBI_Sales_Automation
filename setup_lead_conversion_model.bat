@echo off
REM ============================================================================
REM  IntelliBI — one-shot setup + verify for the enhanced Conversion Chance %%
REM  (self-learning ML) model. RUN THIS ONCE on each machine after copying the
REM  updated code (dev PC and the production PC).
REM
REM  What it does:
REM    1) Finds the project's Python venv (or the parent-folder .venv, or makes one)
REM    2) Installs everything in requirements.txt  (scikit-learn, PyYAML, numpy, ...)
REM    3) Verifies scikit-learn + PyYAML actually import in THAT venv
REM    4) Runs the Follow-Up report ONCE in SAFE mode: LFA_ML_MODE=shadow +
REM       LFA_DRY_RUN=1  ->  builds locally, logs ML metrics, sends NO email/upload
REM
REM  Just double-click it, or run it from a terminal. It never emails in this mode.
REM  After it succeeds, see the console + output\conversion_model_metrics.csv.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PROJ=%~dp0"

REM ---- safe test settings for this run (do NOT email / upload) ----------------
set "LFA_ML_MODE=shadow"
set "LFA_DRY_RUN=1"

echo.
echo ============================================================
echo  IntelliBI Conversion-Chance ML - setup ^& verify
echo ============================================================

REM 1) locate a Python venv (project first, then the parent "IntelliBI Automation")
set "PYEXE="
if exist "%PROJ%.venv\Scripts\python.exe"   set "PYEXE=%PROJ%.venv\Scripts\python.exe"
if not defined PYEXE if exist "%PROJ%..\.venv\Scripts\python.exe" set "PYEXE=%PROJ%..\.venv\Scripts\python.exe"

if not defined PYEXE (
    echo No .venv found - creating one at "%PROJ%.venv" ...
    where py >nul 2>&1 && ( py -3 -m venv "%PROJ%.venv" ) || ( python -m venv "%PROJ%.venv" )
    set "PYEXE=%PROJ%.venv\Scripts\python.exe"
)
if not exist "%PYEXE%" (
    echo [ERROR] Could not find or create a Python venv. Install Python 3.10+ first.
    pause
    exit /b 1
)
echo Using Python: "%PYEXE%"

REM 2) install / update dependencies
echo.
echo === Installing dependencies from requirements.txt ===
"%PYEXE%" -m pip install --upgrade pip
"%PYEXE%" -m pip install -r "%PROJ%requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed - read the messages above.
    pause
    exit /b 1
)

REM 3) verify the ML libraries import in THIS venv
echo.
echo === Verifying scikit-learn + PyYAML ===
"%PYEXE%" -c "import sklearn, yaml, numpy; print('OK: scikit-learn', sklearn.__version__, '| numpy', numpy.__version__, '| PyYAML present')"
if errorlevel 1 (
    echo [WARN] scikit-learn / PyYAML did not import. The report still runs, but the
    echo        enhanced model will fall back to the built-in weight-of-evidence model.
)

REM 4) SAFE test run of the Follow-Up report (shadow + dry-run: no email/upload)
echo.
echo === Test run: LFA_ML_MODE=%LFA_ML_MODE%  LFA_DRY_RUN=%LFA_DRY_RUN%  (no emails) ===
"%PYEXE%" "%PROJ%sales_reports\pyLeadFollowUpAnalysisReport.py"

echo.
echo ============================================================
echo  Done. Look for a line like:  [ml] mode=shadow ... sklearn=True
echo  Metrics history: "%PROJ%output\conversion_model_metrics.csv"
echo.
echo  TO ENABLE IT FOR SCHEDULED RUNS (once the metrics look good):
echo    add an environment variable  LFA_ML_MODE=on  to your Task Scheduler
echo    action (or to run_all.bat). Your normal scheduled pipeline already runs
echo    this report - you do NOT run this setup file on a schedule.
echo ============================================================
pause
endlocal
