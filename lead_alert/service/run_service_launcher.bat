@echo off
REM Launcher for the scheduled task. Lives in lead_alert\service\ ; project root
REM is two levels up. Runs the service with the project venv and appends all
REM output to logs\lead_alert_service.log for easy diagnosis.
cd /d "%~dp0..\.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" "lead_alert\service\run_service.py" >> "logs\lead_alert_service.log" 2>&1
