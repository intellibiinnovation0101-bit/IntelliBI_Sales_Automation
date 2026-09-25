# 11. Office-PC Server Deployment & One-Click `.exe` Packaging

This covers two questions: **will it run reliably on an office PC as the
server**, and **can we make deployment one-click with `.exe` files** so nobody
installs Python, dependencies, or runs scripts. Short answers: **yes**, and
**yes for the server; the counsellor side needs no app at all** — see below.

## 11.1 Will it run reliably on an office PC?

Yes, for a single-office setup this is exactly what the system was designed for.
Why it holds up:

- **Counsellor reads are served from memory** and saves are acknowledged in
  milliseconds, so many counsellors on the office LAN are handled comfortably.
- **No data is lost on a crash or power cut.** Every save is written to a local
  durable journal *before* the counsellor sees "Saved", and Google Sheets stays
  the system of record. On restart the server replays anything not yet synced.
- **The existing pipeline is untouched.** The server writes the same sheet in the
  same format, so consolidation, reports and the ML model keep working.

What "reliable" requires of the office PC (normal for any on-prem server):

1. **It stays on during working hours.** It is the single server; while it is
   off, counsellors can't reach it (their data is safe — it's in Google Sheets).
2. **A stable address on the LAN.** Give the PC a static IP (or a fixed DHCP
   reservation) so the counsellor shortcut keeps working. A wired connection is
   best.
3. **Port 8600 allowed through the firewall** (one-time rule, below).
4. **Internet access** (the server syncs to Google Sheets in the background).
5. Recommended: start it automatically on boot (Task Scheduler, below) and put
   the PC on a UPS so a brief power blip doesn't stop it.

This is a single-server design (no automatic failover). If the office PC ever
dies, you copy the same `Server` folder to any other Windows PC, run the `.exe`,
and point the counsellor shortcuts at the new address — nothing is lost because
all data lives in Google Sheets.

## 11.2 The packaging approach (important)

- **Server / Office PC → one `.exe`.** `IntelliBICounsellorServer.exe` bundles
  Python, all dependencies and the web UI. The office PC needs **no** Python.
- **Counsellor machines → nothing to install.** The counsellor app is a *web*
  app. Counsellors just open a browser to the server. We give them a **desktop
  shortcut**, not an installer. This is simpler, safer, and updates centrally
  (fix the server, everyone gets it — no re-installing on each PC).

> Why the counsellors don't get an `.exe`: there is no per-machine program to
> run. Packaging a browser into an `.exe` on each counsellor PC would add weight
> and maintenance for zero benefit. A one-line desktop shortcut does the job.

### One build step (done once, by you)

A Windows `.exe` must be built on Windows. So **once**, on any one Windows PC that
has Python, you run the provided build script; it produces the `.exe`, which you
then copy to the office PC (and to a backup) freely — those machines never need
Python.

```
counsellor_app\packaging\build_windows.bat      <-- double-click it once
```

It creates `counsellor_app\packaging\dist\Server\` containing
`IntelliBICounsellorServer.exe` and empty `credentials\` and `data\` folders.
That whole `Server` folder is what you put on the office PC.

(If you'd rather not build at all, an alternative no-build route using an embedded
Python is described in §11.8.)

## 11.3 Deploy on the Office PC (server)

1. Copy the built `Server\` folder onto the office PC, e.g. `C:\IntelliBI\Server\`.
2. Put your Google service-account key at
   `C:\IntelliBI\Server\credentials\service_account.json`
   (and share the Data sheet with that account's email as **Editor** — see
   `docs/05`).
3. Open that folder, and in the address bar type `cmd` and press Enter to get a
   command prompt there. Add each counsellor:
   ```
   IntelliBICounsellorServer.exe adduser meera@yourco.in "Meera Nair" "Meera Nair"
   ```
   (You're prompted for a password. Repeat per counsellor.)
4. Verify Google access:
   ```
   IntelliBICounsellorServer.exe check
   ```
   Expect `OK — connected. Cached N leads`.
5. Start the server: **double-click `IntelliBICounsellorServer.exe`.** A window
   opens showing the address. Keep it open (minimise it).
6. Find the PC's address with `ipconfig` (use the IPv4 address, e.g.
   `192.168.1.50`).

The very first run auto-creates `config.yaml` next to the `.exe`; you can edit it
(e.g. change the port) and restart.

### Open the firewall (one time)

Run this once in an **Administrator** command prompt so counsellors can reach the
server:
```
netsh advfirewall firewall add rule name="IntelliBI Counsellor 8600" dir=in action=allow protocol=TCP localport=8600
```

### Start automatically on boot (recommended)

Use Task Scheduler so the server comes back after a reboot:
1. Task Scheduler → **Create Task**.
2. General: "Run whether user is logged on or not."
3. Triggers: **At startup**.
4. Actions: Start a program → browse to `IntelliBICounsellorServer.exe`;
   "Start in" = its folder.
5. Settings: "If the task fails, restart every 1 minute."

## 11.4 Set up a Counsellor machine (no install)

On each counsellor PC, run once:
```
packaging\Create Counsellor Shortcut.bat
```
It asks for the server's IP (e.g. `192.168.1.50`) and port, then puts an
**"IntelliBI Counsellor"** shortcut on the desktop. Counsellors double-click it to
open the login screen in their browser. That's the entire counsellor setup.

(No script? Just make a browser bookmark to `http://<server-ip>:8600/`.)

## 11.5 Everyday operation

- Server: the `.exe` is running (or auto-starts on boot). Nothing else to do.
- Counsellors: double-click the desktop shortcut → log in → work.
- Health check any time: `http://<server-ip>:8600/health`.

## 11.6 Updating the system later

Because counsellors use a browser, **updates happen only on the server**: build a
new `.exe`, stop the old one (close its window / stop the scheduled task), replace
the `.exe` in the `Server` folder (keep `config.yaml`, `credentials\`, `data\`),
and start it again. Every counsellor gets the update automatically on their next
page load.

## 11.7 Troubleshooting

- **Counsellor can't reach the site** → confirm the server window is open; check
  the firewall rule (§11.3); confirm they used the server's current IPv4 and port;
  ping the office PC. `http://<server-ip>:8600/health` from the counsellor's
  browser is the quickest test.
- **`.exe` won't start / antivirus flags it** → PyInstaller one-file exes are
  sometimes flagged by AV heuristics. Allow-list the file, or rebuild with
  `--onedir` (edit `build_windows.bat`, change `--onefile` to `--onedir`) which AV
  tends to trust more and which also starts faster.
- **"Could not start — check config.yaml and the service-account key"** → the key
  is missing/misplaced or the sheet isn't shared with it (see `docs/05` and
  `docs/09`).
- **Address changed after reboot** → give the PC a static IP / DHCP reservation so
  the counsellor shortcuts keep working.

## 11.8 Alternative: no-build "embedded Python" bundle

If you prefer not to build an `.exe` at all, you can ship the source with a
self-contained **embeddable Python** for Windows: unzip Python-embed next to the
project and use a `Start Server.bat` that calls that bundled `python.exe run.py`.
No system-wide Python install, no `.exe` build. It's a few more files than a
single `.exe`, but needs no build machine. Ask and this can be provided as a
ready `Server-NoInstall.zip` layout.
