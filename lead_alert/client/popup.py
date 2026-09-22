"""
Topmost, persistent Website-Lead popup (Tkinter).

One popup per lead. It stays above other windows and keeps sounding a gentle
alert until the counsellor acts. It resolves in exactly three ways:
  * this counsellor clicks Accept  -> "Assigned to you" -> auto-closes
  * another counsellor accepts      -> "Assigned to <name> at <time>" -> closes
  * the lead expires unacknowledged -> "No longer available" -> closes

"Open Email" opens the lead in Gmail/the lead sheet but never claims it.

All methods run on the Tk main thread (the client marshals server events onto it
through a queue), so there is no cross-thread Tk access.
"""
from __future__ import annotations

import webbrowser
import threading

try:
    import winsound          # Windows only
except Exception:            # pragma: no cover - non-Windows dev
    winsound = None

import tkinter as tk
from tkinter import ttk

NAVY = "#1B355E"
RED = "#b00020"
GREEN = "#1a7f37"
BG = "#ffffff"


class PopupManager:
    def __init__(self, root: tk.Tk, on_accept, on_open):
        self.root = root
        self.on_accept = on_accept        # callback(lead_id)
        self.on_open = on_open            # callback(lead_id)
        self.popups = {}                  # lead_id -> dict
        self._sound_job = None
        self._playing = False
        self._arm_sound()

    # ── sound: LOUD alarm while any popup is still awaiting action ───────────────
    def _play_alert(self):
        # Runs on a background thread so the loud pattern never freezes the UI.
        try:
            if winsound is not None:
                # Two-tone siren via the sound-card tone generator (full level,
                # regardless of the notification-sound scheme), repeated, then the
                # system exclamation - as loud/noticeable as winsound allows.
                for _ in range(3):
                    winsound.Beep(1180, 320)
                    winsound.Beep(880, 320)
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass
        finally:
            self._playing = False

    def _arm_sound(self):
        active = any(p["state"] == "open" for p in self.popups.values())
        if active and winsound is not None and not self._playing:
            self._playing = True
            threading.Thread(target=self._play_alert, daemon=True).start()
        self._sound_job = self.root.after(1500, self._arm_sound)

    # ── create / raise ───────────────────────────────────────────────────────
    def show_lead(self, lead: dict, realert: bool = False):
        lid = lead["lead_id"]
        if lid in self.popups and self.popups[lid]["state"] == "open":
            self._raise(self.popups[lid]["win"])       # re-alert -> bring forward
            return
        if lid in self.popups:
            self._destroy(lid)
        self._build(lead)

    def _build(self, lead: dict):
        lid = lead["lead_id"]
        win = tk.Toplevel(self.root)
        win.title("NEW WEBSITE LEAD")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # no easy dismiss
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        # header
        head = tk.Frame(win, bg=RED)
        head.pack(fill="x")
        tk.Label(head, text="  NEW WEBSITE LEAD", bg=RED, fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(side="left", padx=8, pady=8)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)

        def row(label, value):
            if not value:
                return
            fr = tk.Frame(body, bg=BG)
            fr.pack(fill="x", anchor="w", pady=1)
            tk.Label(fr, text=f"{label}:", width=14, anchor="w", bg=BG,
                     fg="#5b6b86", font=("Segoe UI", 9)).pack(side="left")
            tk.Label(fr, text=value, anchor="w", bg=BG, fg="#1a2a48",
                     font=("Segoe UI", 10, "bold"), justify="left",
                     wraplength=360).pack(side="left")

        row("Name", lead.get("name"))
        row("Mobile", lead.get("mobile"))
        row("Email", lead.get("email"))
        row("Course", lead.get("course"))
        row("Form", lead.get("form_type"))
        row("Sender", lead.get("sender"))
        row("Received", lead.get("received_at"))
        if lead.get("preview"):
            tk.Label(body, text=lead["preview"], bg="#f4f8fd", fg="#33415c",
                     font=("Segoe UI", 9), justify="left", wraplength=380,
                     padx=8, pady=6).pack(fill="x", pady=(8, 4))

        status = tk.Label(body, text="", bg=BG, fg=NAVY,
                          font=("Segoe UI", 10, "bold"))
        status.pack(anchor="w", pady=(6, 0))

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=16, pady=(0, 14))
        open_btn = ttk.Button(btns, text="Open Email",
                              command=lambda: self._open(lid, lead))
        open_btn.pack(side="left")
        accept_btn = tk.Button(
            btns, text="Acknowledge / Accept Lead", bg=NAVY, fg="#ffffff",
            activebackground="#274a86", activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=6,
            command=lambda: self._accept(lid))
        accept_btn.pack(side="right")

        self.popups[lid] = {"win": win, "status": status, "accept": accept_btn,
                            "open": open_btn, "state": "open", "lead": lead}
        self._raise(win)

    # ── actions ──────────────────────────────────────────────────────────────
    def _accept(self, lid):
        p = self.popups.get(lid)
        if not p or p["state"] != "open":
            return
        p["accept"].config(state="disabled", text="Accepting…")
        p["status"].config(text="Claiming this lead…", fg="#5b6b86")
        try:
            self.on_accept(lid)
        except Exception as e:
            p["status"].config(text=f"Could not reach server: {e}", fg=RED)
            p["accept"].config(state="normal", text="Acknowledge / Accept Lead")

    def _open(self, lid, lead):
        url = lead.get("open_email_url") or lead.get("lead_sheet_url")
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            self.on_open(lid)
        except Exception:
            pass

    # ── server-driven state changes ──────────────────────────────────────────
    def accepted_by_me(self, lid):
        p = self.popups.get(lid)
        if not p:
            return
        p["state"] = "resolved"
        p["status"].config(text="✔ Assigned to you. Opening the lead…", fg=GREEN)
        p["accept"].config(state="disabled", text="Assigned to you")
        self._auto_close(lid, 2500)

    def assigned_to_other(self, lid, name, at):
        p = self.popups.get(lid)
        if not p:
            return
        p["state"] = "resolved"
        when = f" at {at}" if at else ""
        p["status"].config(
            text=f"Lead Assigned — accepted by {name}{when}. No action required.",
            fg=NAVY)
        p["accept"].config(state="disabled", text="Already assigned")
        self._auto_close(lid, 4000)

    def expired(self, lid):
        p = self.popups.get(lid)
        if not p:
            return
        p["state"] = "resolved"
        p["status"].config(text="This lead is no longer available.", fg="#5b6b86")
        p["accept"].config(state="disabled", text="Expired")
        self._auto_close(lid, 3000)

    def reset_accept(self, lid, message=""):
        p = self.popups.get(lid)
        if not p or p["state"] != "open":
            return
        p["accept"].config(state="normal", text="Acknowledge / Accept Lead")
        if message:
            p["status"].config(text=message, fg=RED)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _raise(self, win):
        try:
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
            win.focus_force()
            win.bell()
        except Exception:
            pass

    def _auto_close(self, lid, ms):
        self.root.after(ms, lambda: self._destroy(lid))

    def _destroy(self, lid):
        p = self.popups.pop(lid, None)
        if p:
            try:
                p["win"].destroy()
            except Exception:
                pass
