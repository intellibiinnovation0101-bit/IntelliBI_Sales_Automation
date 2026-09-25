@echo off
REM ===========================================================================
REM  Counsellor machine setup — NO installation, NO Python.
REM  This creates a desktop shortcut "IntelliBI Counsellor" that opens the
REM  counsellor screen in the default browser. Run it once per counsellor PC.
REM ===========================================================================
setlocal enabledelayedexpansion

echo(
echo   IntelliBI Counsellor - desktop shortcut setup
echo   ---------------------------------------------
echo   Enter the office server address (the PC running the server).
echo   Example:  192.168.1.50    (or a name like  office-pc )
echo(
set /p SERVER=  Server IP or name:
if "%SERVER%"=="" (echo No address entered. & pause & exit /b 1)

set /p PORT=  Port [8600]:
if "%PORT%"=="" set PORT=8600

set URL=http://%SERVER%:%PORT%/
set LINK=%USERPROFILE%\Desktop\IntelliBI Counsellor.url

> "%LINK%" echo [InternetShortcut]
>>"%LINK%" echo URL=%URL%
>>"%LINK%" echo IconIndex=0

echo(
echo   Created desktop shortcut:  "IntelliBI Counsellor"
echo   It opens:  %URL%
echo(
echo   Double-click it any time to log in. Nothing else to install.
echo(
pause
