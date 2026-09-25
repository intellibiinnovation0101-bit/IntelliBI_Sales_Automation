IntelliBI Counsellor — SERVER (Office PC)
=========================================

This folder runs the counsellor system. The office PC does NOT need Python.

ONE-TIME SETUP
--------------
1. Put your Google service-account key file here:
        credentials\service_account.json
   (and share the Google Data sheet with that account's email as Editor)

2. Add each counsellor (a Command Prompt opens if you double-click, or run this
   in a terminal opened in this folder):
        IntelliBICounsellorServer.exe adduser someone@yourco.in "Full Name" "Counselling By"
   Repeat for each counsellor. You will be asked for a password each time.

3. Check the connection to Google Sheets:
        IntelliBICounsellorServer.exe check
   You should see: "OK — connected. Cached N leads".

EVERY DAY
---------
- Double-click  IntelliBICounsellorServer.exe  to start the server.
  Keep the black window open (minimise it). Closing it stops the server.
- Counsellors open their browser to:   http://<this-PC-ip>:8600/
  (find <this-PC-ip> by running  ipconfig  — use the IPv4 address.)

FIRST TIME the .exe runs it creates a config.yaml here. You can edit that file
(e.g. the port) and restart.

To have it start automatically on boot, see
docs\11-exe-and-office-pc-deployment.md (Task Scheduler section).

Need help? Everything is in the docs\ folder of the project.
