IntelliBI Counsellor — SERVER (Office PC)
=========================================

This folder runs the counsellor system. The office PC does NOT need Python.
Everything below uses only built-in Windows features - nothing to download.

ONE-TIME SETUP  (about 5 minutes, then never again)
--------------------------------------------------
1. Put your Google service-account key file here:
        credentials\service_account.json
   and share the Google Data sheet with that account's email as Editor.

2. Double-click   Add Counsellor.bat   once per counsellor (asks for a password).
   (Or, in a command prompt opened in this folder:
        IntelliBICounsellorServer.exe adduser someone@yourco.in "Full Name" "Counselling By")

3. Double-click   Install Auto-Start.bat   (click "Yes" on the Windows prompt).
   This makes the server start BY ITSELF every time the PC boots - no login,
   no double-clicking, no window to keep open - and restarts it automatically if
   it ever crashes or stops responding. It also opens the firewall port, stops the
   PC from sleeping/hibernating, and starts the server right away.
   It writes  SERVER ADDRESS.txt  with the URL to give counsellors.

4. Double-click   Verify Server.bat   - every line should say PASS.
   Then restart the PC once and run Verify Server.bat again: still all PASS
   = the automatic start-up is proven.

EVERY DAY
---------
Nothing. The PC being switched on is enough. Counsellors open their shortcut:
        http://<this-PC-name>:8600/        (see SERVER ADDRESS.txt)

WHEN YOU NEED TO
----------------
  Add Counsellor.bat      add a login (offers to restart the server for you)
  Restart Server.bat      restart after editing config.yaml
  Verify Server.bat       full health check (run this first if anything seems wrong)
  Uninstall Auto-Start.bat  stop the server and remove the automatic start-up
  logs\watchdog.log, logs\server.log   what happened and when

COUNSELLOR PCs
--------------
Nothing to install. Run  Create Counsellor Shortcut.bat  once on each counsellor
PC and enter this server's PC NAME (from SERVER ADDRESS.txt) - it puts an
"IntelliBI Counsellor" shortcut on their desktop.

Full details: docs\11-exe-and-office-pc-deployment.md in the project.
