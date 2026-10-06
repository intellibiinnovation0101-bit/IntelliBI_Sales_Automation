"""
IntelliBI Website Lead Alert — Windows tray client (entry point).

Runs silently in the system tray, keeps one authenticated WebSocket to the office
service, and shows a topmost, sounding popup for every new Website Lead until the
counsellor accepts it (or it's assigned to someone else / expires).

Threads:
  * Tk main loop  (main thread)  — owns all UI, drains the event queue
  * WebSocket     (bg thread)    — receives events, sends Accept/Ping
  * Tray icon     (bg thread)    — pystray menu

Server events are marshalled onto a queue and applied on the Tk thread, so the UI
is only ever touched from one place.
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import time

import client_config
import enroll
from ws_client import WSClient, CONNECTED, DISCONNECTED, AUTH_FAILED, SERVER_MOVED

log = logging.getLogger("leadalert.app")
OFFLINE_BANNER_AFTER = 120        # seconds without a connection before warning
REMIND_EVERY = 30 * 60            # repeat warnings at most this often

_QUIT = "_QUIT"
_REREG = "_REREG"


_DISC = {"connected": (26, 127, 55, 255),       # green  - alerts ON
         "connecting": (27, 53, 94, 255),       # navy
         "dropped": (214, 140, 0, 255),         # amber  - reconnecting
         "unreachable": (176, 0, 32, 255),      # red    - alerts OFF
         "auth": (176, 0, 32, 255)}


def _make_icon_image(status: str = "connecting"):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, 58, 58], fill=_DISC.get(status, _DISC["connecting"]))
    d.ellipse([28, 16, 36, 24], fill=(255, 255, 255, 255))  # dot of an "i"
    d.rectangle([28, 28, 36, 48], fill=(255, 255, 255, 255))  # stem of an "i"
    return img


def _relaunch():
    """Start a fresh copy of the app (used after clearing the registration)."""
    import subprocess
    args = [sys.executable] if getattr(sys, "frozen", False) else \
        [sys.executable, os.path.abspath(__file__)]
    try:
        subprocess.Popen(args, close_fds=True)
    except Exception as e:
        log.error("could not relaunch: %s", e)


def main():
    client_config.setup_logging()
    log.info("IntelliBI Lead Alert %s starting", client_config.CLIENT_VERSION)
    # First run (or after re-register): enroll this device.
    if not client_config.is_registered():
        if not enroll.enroll_dialog():
            return   # user cancelled

    cfg = client_config.load_config()
    token = client_config.load_token()
    my_email = (cfg.get("counsellor_email") or "").lower()
    my_name = cfg.get("counsellor_name") or ""
    server_url = cfg.get("server_url") or ""

    import tkinter as tk
    from tkinter import messagebox
    from popup import PopupManager

    root = tk.Tk()
    root.withdraw()                      # no main window; tray only

    q = queue.Queue()
    ws = WSClient(client_config.candidate_server_urls() or [server_url], token, q,
                  version=client_config.CLIENT_VERSION)
    log.info("server %s, counsellor %s", server_url, my_email)

    mgr = PopupManager(
        root,
        on_accept=lambda lid: ws.send({"type": "ACCEPT", "lead_id": lid}),
        on_open=lambda lid: ws.send({"type": "OPENED", "lead_id": lid}))

    state = {"connected": False, "status": "connecting", "down_since": time.time(),
             "banner": None, "banner_shown_at": 0.0, "auth_prompted_at": 0.0,
             "name": my_name}
    _STATUS_TEXT = {
        "connected": "Connected — lead alerts ON",
        "connecting": "Connecting…",
        "dropped": "Connection lost — reconnecting…",
        "unreachable": "Cannot reach the server — alerts OFF (retrying)",
        "auth": "Not registered on the server — alerts OFF",
    }

    # ── tray ─────────────────────────────────────────────────────────────────
    try:
        import pystray
        from pystray import MenuItem as Item

        def status_text(_item=None):
            return (f"{state['name'] or my_email} — "
                    + _STATUS_TEXT.get(state["status"], state["status"]))

        icon = pystray.Icon(
            "IntelliBILeadAlert", _make_icon_image(), "IntelliBI Lead Alert",
            menu=pystray.Menu(
                Item(status_text, None, enabled=False),
                Item("Re-register this computer…", lambda: q.put({"type": _REREG})),
                Item("Quit", lambda: q.put({"type": _QUIT}))))
        import threading
        threading.Thread(target=icon.run, daemon=True).start()
    except Exception as e:
        log.warning("tray unavailable (continuing without it): %s", e)
        icon = None

    # ── event pump (Tk thread) ───────────────────────────────────────────────
    def pump():
        try:
            while True:
                msg = q.get_nowait()
                try:
                    _handle(msg)
                except Exception as e:
                    log.exception("handler error (continuing): %s", e)
        except queue.Empty:
            pass
        root.after(200, pump)

    def _handle(msg):
        t = msg.get("type")
        if t == "NEW_LEAD":
            mgr.show_lead(msg["lead"], realert=bool(msg.get("realert")))
        elif t == "ASSIGNED":
            lid = msg.get("lead_id")
            if (msg.get("assigned_to") or "").lower() == my_email:
                mgr.accepted_by_me(lid)
            else:
                mgr.assigned_to_other(lid, msg.get("assigned_name", "a counsellor"),
                                      msg.get("assigned_at", ""))
        elif t == "ACCEPT_RESULT":
            lid = msg.get("lead_id")
            r = msg.get("result")
            if r == "assigned":
                mgr.accepted_by_me(lid)
            elif r == "already":
                mgr.assigned_to_other(lid, msg.get("assigned_name", "a counsellor"),
                                      msg.get("assigned_at", ""))
            elif r == "expired":
                mgr.expired(lid)
            else:
                mgr.reset_accept(lid, "This lead is no longer available.")
        elif t == "EXPIRE":
            mgr.expired(msg.get("lead_id"))
        elif t == CONNECTED:
            _set_status("connected")
        elif t == DISCONNECTED:
            _set_status("dropped" if msg.get("kind") == "dropped" else "unreachable",
                        msg.get("error", ""))
        elif t == SERVER_MOVED:
            url = msg.get("url", "")
            try:
                c = client_config.load_config()
                c["server_url"] = url
                client_config.save_config(c)
                log.info("saved new server address %s", url)
            except Exception as e:
                log.error("could not save new server address: %s", e)
        elif t == AUTH_FAILED:
            _set_status("auth", msg.get("reason", ""))
            _auth_prompt(msg.get("reason", ""))
        elif t == "HELLO":
            nm = msg.get("counsellor_name") or ""
            if nm and nm != state["name"]:
                state["name"] = nm
                try:
                    c = client_config.load_config()
                    c["counsellor_name"] = nm
                    client_config.save_config(c)
                except Exception:
                    pass
            _set_status("connected")
        elif t == _REREG:
            client_config.clear_token()
            messagebox.showinfo(
                "IntelliBI Lead Alert",
                "This computer has been unregistered. Please re-open "
                "IntelliBI Lead Alert to register again.")
            _quit()
        elif t == _QUIT:
            _quit()

    def _set_status(status, detail=""):
        prev = state["status"]
        state["status"] = status
        state["connected"] = status == "connected"
        if status == "connected":
            state["down_since"] = None
            _close_banner()
        elif state["down_since"] is None:
            state["down_since"] = time.time()
        if status != prev:
            log.info("status %s -> %s %s", prev, status, detail)
            if icon:
                try:
                    icon.icon = _make_icon_image(status)
                except Exception:
                    pass
        if icon:
            icon.update_menu()

    def _close_banner():
        b = state.get("banner")
        state["banner"] = None
        if b is not None:
            try:
                b.destroy()
            except Exception:
                pass

    def _show_banner():
        """Non-blocking warning window: alerts are OFF on this computer."""
        _close_banner()
        w = tk.Toplevel(root)
        w.title("IntelliBI Lead Alert — alerts are OFF")
        try:
            w.attributes("-topmost", True)
        except Exception:
            pass
        txt = ("Website lead alerts are OFF on this computer.\n\n"
               f"It cannot connect to the Lead Alert server ({ws.server_url}).\n"
               "It keeps retrying automatically and this message closes by itself "
               "once it is connected.\n\nIf this does not clear within a few "
               "minutes, please tell the admin.")
        tk.Label(w, text=txt, justify="left", padx=18, pady=14,
                 font=("Segoe UI", 10)).pack()
        tk.Button(w, text="OK", width=10, command=w.destroy).pack(pady=(0, 12))
        state["banner"] = w
        state["banner_shown_at"] = time.time()

    def _auth_prompt(reason):
        if time.time() - state["auth_prompted_at"] < REMIND_EVERY:
            return
        state["auth_prompted_at"] = time.time()
        why = ("your account is not Active on the server" if reason == "inactive"
               else "this computer is not registered on the Lead Alert server")
        if messagebox.askyesno(
                "IntelliBI Lead Alert — alerts are OFF",
                f"Website lead alerts are OFF: {why}.\n\n"
                "Re-register this computer now?"):
            client_config.clear_token()
            log.info("re-register requested by user")
            _relaunch()
            _quit()

    def watchdog():
        """Warn when this computer has been without a connection for a while."""
        try:
            ds = state["down_since"]
            if (ds and state["status"] in ("unreachable", "dropped", "connecting")
                    and time.time() - ds >= OFFLINE_BANNER_AFTER
                    and state["banner"] is None
                    and time.time() - state["banner_shown_at"] >= REMIND_EVERY):
                log.warning("no connection for %ss — showing alerts-OFF warning",
                            int(time.time() - ds))
                _show_banner()
        except Exception as e:
            log.error("watchdog error: %s", e)
        root.after(5000, watchdog)

    def _quit():
        try:
            ws.stop()
        except Exception:
            pass
        try:
            if icon:
                icon.stop()
        except Exception:
            pass
        root.quit()
        root.destroy()

    ws.start()
    root.after(200, pump)
    root.after(5000, watchdog)
    root.mainloop()


def _cli():
    # Autostart management from the same exe/script:
    #   IntelliBILeadAlert.exe --install-autostart | --remove-autostart
    if "--install-autostart" in sys.argv:
        import install_autostart
        print("Installed autostart:", install_autostart.install())
        return
    if "--remove-autostart" in sys.argv:
        import install_autostart
        print("Removed." if install_autostart.remove() else "Nothing to remove.")
        return
    main()


if __name__ == "__main__":
    try:
        _cli()
    except KeyboardInterrupt:
        sys.exit(0)
