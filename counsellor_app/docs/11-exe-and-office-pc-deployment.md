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

### Start automatically on boot — fully hands-off (recommended)

Double-click **`Install Auto-Start.bat`** in the `Server` folder once (accept the
Windows admin prompt). Nothing to download — it uses only built-in Windows
features, and it is the same proven design as the IntelliBI Lead Alert service
on the office PC. After it runs, the server:

- **starts by itself whenever the PC boots** — before anyone logs in, with no
  visible window (a Task Scheduler task running as `SYSTEM`, trigger *at
  start-up* + *at logon* + a 5-minute re-check tick);
- **restarts itself if it crashes** (a supervisor, `server_watchdog.ps1`,
  relaunches it within ~10 s) and **if it hangs** (alive but not answering
  `/health` for ~2 min, it is killed and relaunched);
- is never stopped by Windows on its own (the task's "stop after 3 days" default
  is disabled — this default silently kills long-running tasks; the installer
  verifies it is off);
- has its **firewall port open on every network profile** (so a network being
  re-classified Public does not cut counsellors off);
- keeps the PC awake: **sleep/hibernate off, Fast Start-up off**, network-adapter
  power-saving off.

It also starts the server immediately, probes it, and writes **`SERVER
ADDRESS.txt`** with the URL to give counsellors. Then run **`Verify Server.bat`**
(all lines should be PASS), reboot once, and run it again — that is the proof
that the automatic start-up works.

Everyday operations: `Add Counsellor.bat` (adds a login and offers to restart),
`Restart Server.bat` (after editing `config.yaml`), `Stop Server.bat` (full stop,
start-up paused, waits until the `.exe` is unlocked), `Update Server.bat`
(stop → git pull → restart → version check, §11.6), `Uninstall Auto-Start.bat`.
Logs: `logs\watchdog.log` (start/stop/restart events) and `logs\server.log`.

> The manual alternative (double-clicking the `.exe`) still works, but then the
> server only runs while that window is open. Use the installer.

### What can take the URL down while the PC is on — and what is done about it

| Cause | Handled by | Anything left for you / IT |
|---|---|---|
| Server crashes or exits | Watchdog restarts it in ~10 s; task also has restart-on-failure | — |
| Server hangs (alive, not answering) | Watchdog kills + restarts after ~2 min unresponsive | — |
| PC reboots (Windows Update, power cut) | Task runs at boot, as SYSTEM, no login needed | Put the PC on a UPS; set Windows Update *active hours* to office time |
| Windows stops long tasks after 3 days | Time limit disabled (installer verifies `PT0S`) | — |
| PC goes to sleep / hibernates | Timeouts set to *never*, hibernate + Fast Start-up off | Don't press the sleep button; if it's a laptop, lid-close action → *Do nothing* |
| Firewall blocks the port | Rule added for **all** profiles (Domain/Private/Public) | A third-party firewall/AV must also allow TCP 8600 |
| Another program grabs port 8600 | Installer warns; watchdog log shows the bind error | Stop that program or change `port:` in `config.yaml` and re-run the installer |
| **PC's IP address changes** (DHCP) | Counsellor shortcut uses the **PC name**, which follows the PC | Ask IT for a **DHCP reservation / static IP** — the only fully reliable fix; needed if a counsellor PC cannot resolve the name |
| Internet down while running | Server keeps serving from memory; saves are journaled and pushed later | Depends on the office internet provider |
| **PC boots while internet is down** | Server boots from its local cache and resyncs when the link returns (requires the rebuilt `.exe`, see below) | Depends on the office internet provider |
| Google key missing / sheet not shared | `check` / `Verify` fail clearly; watchdog keeps retrying | Fix the key/sharing |
| Antivirus quarantines the `.exe` | — | Allow-list `IntelliBICounsellorServer.exe` (see §11.7) |
| Counsellor on a different network/VLAN or Wi-Fi guest network | — | Counsellor PCs must be on the same office LAN (or IT must route/allow TCP 8600) |

**Depends on the office network / internet provider (cannot be fixed in this
setup):** the office LAN and router being up; counsellor PCs being on the same
LAN; the internet link for syncing to Google Sheets (the URL itself stays up
without it); and the DHCP reservation, which only IT/the router can set.

> The offline-boot fallback and the `sheet_ok` health flag are in the app source;
> run `build_windows.bat` once more and replace the `.exe` to include them. The
> automatic start-up scripts work with the existing `.exe` as-is.

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

Because counsellors use a browser, **updates happen only on the server**. The
office PC runs the server from the repository clone itself
(`…\IntelliBI_Sales_Automation\counsellor_app\packaging\dist\Server`), so an
update is: build a new `.exe` on the build PC → push → on the office PC run
**`Update Server.bat`** (in that `Server` folder, as administrator). It does, in
the only order that works:

1. `stop_server.ps1` — pauses the start-up task (so its 5-minute trigger cannot
   bring the server back), kills the watchdog, kills the server as a **process
   tree** (`taskkill /T` — the one-file `.exe` is a launcher + a child), and waits
   until no server process is left, the port is free **and the `.exe` file is
   unlocked**. It prints PASS, or FAIL with the exact process / port owner /
   lock that is still there. A window that is not elevated fails loudly instead
   of silently doing nothing.
2. `git fetch` + `git reset --hard origin/<branch this PC is on>`. Untracked
   files (`config.yaml`, `credentials\`, `data\`, `logs\`) are never touched.
3. `restart_server.ps1` — start-up task enabled and started again.
4. `/health` must report the `APP_VERSION` of the source just pulled; otherwise
   a warning says the `.exe` in origin was not rebuilt.

If anything fails after the stop, the server is restarted so the office is not
left without it. The manual equivalent is `Stop Server.bat` → wait for PASS →
`git reset --hard origin/dev` → `Restart Server.bat`. Never pull while the
server runs: git cannot replace a locked `.exe` and stops with
`Unlink of file '…IntelliBICounsellorServer.exe' failed` (answer `n`, stop the
server properly, run the update again).

**Confirm which build is running.** Every build carries `APP_VERSION`
(`app/config.py`, bumped whenever a new `.exe` is shipped). It is shown in three
places: `http://<office-pc>:8600/health` (`"version": "…"`), the output of
`Verify Server.bat`, and the page header pill ("Counsellor · v…") after login.
If the version there is older than the one in the source you just built, the
server is still running the previous `.exe` — the usual causes are pulling while
the server was running (see above) or an installed `Server` folder outside the
repository that was not given the new `.exe`. A stale browser page is ruled out
with a hard reload (Ctrl+F5).

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
