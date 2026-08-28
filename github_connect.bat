@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   Connect IntelliBI_Sales_Automation to GitHub
echo   repo: https://github.com/intellibiinnovation0101-bit/IntelliBI_Sales_Automation
echo ============================================================
echo.

REM --- 0. clear any stale git lock from an interrupted operation ---
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM --- 0b. make sure a commit identity exists ---
set "GITEMAIL="
for /f "delims=" %%i in ('git config user.email 2^>nul') do set "GITEMAIL=%%i"
if not defined GITEMAIL call :setid

REM --- 1. this is already a git repo; show state ---
echo --- current status ---
git status
echo.

REM --- 2. point 'origin' at the CORRECT Sales repo (fix if wrong) ---
git remote remove origin 2>nul
git remote add origin https://github.com/intellibiinnovation0101-bit/IntelliBI_Sales_Automation.git
echo --- remote (must say IntelliBI_Sales_Automation) ---
git remote -v
echo.

REM --- 3. rename current branch to main ---
git branch -M main

echo ============================================================
echo   Ready to publish your local project to GitHub 'main'.
echo   This uses a force-push, which ONLY replaces GitHub's empty
echo   placeholder README. Your local code and history are kept.
echo   Close this window now to abort, or
pause
echo ============================================================

git push -u origin main --force
if errorlevel 1 goto :err

REM --- 4. create dev and prod from main and publish them ---
git branch dev 2>nul
git branch prod 2>nul
git push -u origin dev
git push -u origin prod

REM --- 5. verify ---
echo.
echo --- verification: branches (local + remote) ---
git fetch --all --prune
git branch -a
echo --- upstream tracking ---
git branch -vv
echo.
echo DONE.  main / dev / prod are on GitHub (IntelliBI_Sales_Automation).
goto :end

:setid
echo No git identity found. Enter it once (used on your commits):
set /p GNAME=Your name :
set /p GEMAIL=Your email:
git config --global user.name "%GNAME%"
git config --global user.email "%GEMAIL%"
goto :eof

:err
echo.
echo *** PUSH FAILED ***
echo Check that PyCharm/Git is logged in to GitHub as an account with
echo WRITE access to intellibiinnovation0101-bit/IntelliBI_Sales_Automation.
echo (GitHub needs OAuth login or a Personal Access Token - not a password.)

:end
echo.
pause
endlocal
