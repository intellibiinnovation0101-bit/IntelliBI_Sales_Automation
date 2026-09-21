"""
First-run enrollment for the IntelliBI Lead Alert client.

Shows a small dialog asking for:
  * Server URL   (e.g. http://192.168.1.50:8787  — the office PC running the service)
  * Counsellor email  (must be an Active counsellor in counsellors.json)
  * Enrollment code   (the shared one-time code your admin gives out)

On success it stores the server URL + the returned device token (DPAPI-encrypted)
and returns True. No Google credentials are involved.
"""
from __future__ import annotations

import json
import socket
import urllib.request

import client_config


def _machine_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown-pc"


def enroll_request(server_url: str, email: str, code: str) -> dict:
    """POST /enroll. Returns the parsed JSON (may contain 'error')."""
    url = server_url.rstrip("/") + "/enroll"
    body = json.dumps({"email": email, "code": code,
                       "machine": _machine_name()}).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def do_enroll(server_url: str, email: str, code: str) -> str:
    """Enroll and persist. Returns '' on success, else an error message."""
    server_url = server_url.strip()
    email = email.strip()
    code = code.strip()
    if not (server_url and email and code):
        return "All three fields are required."
    if not server_url.lower().startswith(("http://", "https://")):
        server_url = "http://" + server_url
    try:
        data = enroll_request(server_url, email, code)
    except Exception as e:
        return f"Could not reach the server: {e}"
    if data.get("error"):
        return data["error"]
    token = data.get("token", "")
    if not token:
        return "Server did not return a token."
    client_config.save_config({
        "server_url": server_url,
        "counsellor_email": data.get("counsellor_email", email),
        "counsellor_name": data.get("counsellor_name", ""),
    })
    client_config.save_token(token)
    return ""


def enroll_dialog() -> bool:
    """Tkinter enrollment dialog. Returns True if enrollment succeeded."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    cfg = client_config.load_config()
    result = {"ok": False}

    root = tk.Tk()
    root.title("IntelliBI Lead Alert — Register this computer")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    frm = ttk.Frame(root, padding=16)
    frm.grid()
    ttk.Label(frm, text="Register this computer for Website Lead alerts",
              font=("Segoe UI", 11, "bold")).grid(column=0, row=0, columnspan=2,
                                                   sticky="w", pady=(0, 12))

    ttk.Label(frm, text="Server URL").grid(column=0, row=1, sticky="w")
    e_url = ttk.Entry(frm, width=40)
    e_url.insert(0, cfg.get("server_url") or "http://")
    e_url.grid(column=1, row=1, pady=4)

    ttk.Label(frm, text="Your email").grid(column=0, row=2, sticky="w")
    e_mail = ttk.Entry(frm, width=40)
    e_mail.insert(0, cfg.get("counsellor_email") or "")
    e_mail.grid(column=1, row=2, pady=4)

    ttk.Label(frm, text="Enrollment code").grid(column=0, row=3, sticky="w")
    e_code = ttk.Entry(frm, width=40, show="•")
    e_code.grid(column=1, row=3, pady=4)

    status = ttk.Label(frm, text="", foreground="#b00020")
    status.grid(column=0, row=4, columnspan=2, sticky="w", pady=(6, 0))

    def submit():
        status.config(text="Registering…", foreground="#555")
        root.update_idletasks()
        err = do_enroll(e_url.get(), e_mail.get(), e_code.get())
        if err:
            status.config(text=err, foreground="#b00020")
            return
        result["ok"] = True
        messagebox.showinfo("IntelliBI Lead Alert",
                            "This computer is registered. You'll now receive "
                            "Website Lead alerts.")
        root.destroy()

    ttk.Button(frm, text="Register", command=submit).grid(
        column=1, row=5, sticky="e", pady=(12, 0))
    root.bind("<Return>", lambda _e: submit())
    root.mainloop()
    return result["ok"]


if __name__ == "__main__":
    enroll_dialog()
