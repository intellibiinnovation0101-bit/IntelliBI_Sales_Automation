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

import queue
import sys

import client_config
import enroll
from ws_client import WSClient, CONNECTED, DISCONNECTED

_QUIT = "_QUIT"
_REREG = "_REREG"


def _make_icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, 58, 58], fill=(27, 53, 94, 255))       # navy disc
    d.ellipse([28, 16, 36, 24], fill=(255, 255, 255, 255))  # dot of an "i"
    d.rectangle([28, 28, 36, 48], fill=(255, 255, 255, 255))  # stem of an "i"
    return img


def main():
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
    ws = WSClient(server_url, token, q)

    mgr = PopupManager(
        root,
        on_accept=lambda lid: ws.send({"type": "ACCEPT", "lead_id": lid}),
        on_open=lambda lid: ws.send({"type": "OPENED", "lead_id": lid}))

    state = {"connected": False}

    # ── tray ─────────────────────────────────────────────────────────────────
    try:
        import pystray
        from pystray import MenuItem as Item

        def status_text(_item=None):
            return (f"{my_name or my_email} — "
                    + ("Connected" if state["connected"] else "Reconnecting…"))

        icon = pystray.Icon(
            "IntelliBILeadAlert", _make_icon_image(), "IntelliBI Lead Alert",
            menu=pystray.Menu(
                Item(status_text, None, enabled=False),
                Item("Re-register this computer…", lambda: q.put({"type": _REREG})),
                Item("Quit", lambda: q.put({"type": _QUIT}))))
        import threading
        threading.Thread(target=icon.run, daemon=True).start()
    except Exception as e:
        print("  [client] tray unavailable (continuing without it):", e)
        icon = None

    # ── event pump (Tk thread) ───────────────────────────────────────────────
    def pump():
        try:
            while True:
                msg = q.get_nowait()
                try:
                    _handle(msg)
                except Exception as e:
                    print("  [client] handler error (continuing):", e)
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
            state["connected"] = True
            if icon:
                icon.update_menu()
        elif t == DISCONNECTED:
            state["connected"] = False
            if icon:
                icon.update_menu()
        elif t == "HELLO":
            state["connected"] = True
        elif t == _REREG:
            client_config.clear_token()
            messagebox.showinfo(
                "IntelliBI Lead Alert",
                "This computer has been unregistered. Please re-open "
                "IntelliBI Lead Alert to register again.")
            _quit()
        elif t == _QUIT:
            _quit()

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
