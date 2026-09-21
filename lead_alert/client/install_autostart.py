"""
Register / unregister the client to start automatically with Windows.

Creates a shortcut in the current user's Startup folder pointing at either the
built IntelliBILeadAlert.exe (when frozen) or pythonw.exe + this client script.
No admin rights required (per-user Startup).

    python install_autostart.py            # install
    python install_autostart.py --remove   # remove
"""
from __future__ import annotations

import os
import sys

SHORTCUT_NAME = "IntelliBI Lead Alert.lnk"


def _startup_dir() -> str:
    return os.path.join(os.environ["APPDATA"],
                        r"Microsoft\Windows\Start Menu\Programs\Startup")


def _target():
    """Return (target_path, arguments, workdir)."""
    if getattr(sys, "frozen", False):                 # built .exe
        exe = sys.executable
        return exe, "", os.path.dirname(exe)
    # running from source -> launch with pythonw (no console)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "lead_alert_client.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    pyw = pyw if os.path.exists(pyw) else sys.executable
    return pyw, f'"{script}"', os.path.dirname(script)


def install() -> str:
    from win32com.client import Dispatch
    path = os.path.join(_startup_dir(), SHORTCUT_NAME)
    target, args, workdir = _target()
    sh = Dispatch("WScript.Shell")
    sc = sh.CreateShortcut(path)
    sc.TargetPath = target
    if args:
        sc.Arguments = args
    sc.WorkingDirectory = workdir
    sc.WindowStyle = 7                                # minimized
    sc.Description = "IntelliBI Website Lead Alert"
    sc.save()
    return path


def remove() -> bool:
    path = os.path.join(_startup_dir(), SHORTCUT_NAME)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


if __name__ == "__main__":
    if "--remove" in sys.argv:
        print("Removed." if remove() else "Nothing to remove.")
    else:
        print("Installed autostart shortcut:", install())
