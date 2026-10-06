"""
Per-machine config + secure token storage for the IntelliBI Lead Alert client.

Lives under %APPDATA%\\IntelliBILeadAlert\\ :
  config.json   server URL + the counsellor this device is registered as
  token.bin     the device bearer token, encrypted with Windows DPAPI (only this
                Windows user on this machine can decrypt it). Falls back to a
                plain token.txt if pywin32/DPAPI is unavailable (with a warning).

No Gmail/Google credentials are ever stored on the counsellor machine.
"""
from __future__ import annotations

import json
import os

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "IntelliBILeadAlert")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
TOKEN_BIN = os.path.join(APP_DIR, "token.bin")
TOKEN_TXT = os.path.join(APP_DIR, "token.txt")

DEFAULTS = {"server_url": "", "counsellor_email": "", "counsellor_name": ""}

CLIENT_VERSION = "2026.10.07"
SERVER_URL_FILE = "server_url.txt"


def _app_dir() -> str:
    import sys
    if getattr(sys, "frozen", False):                      # the built .exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def normalise_url(u: str) -> str:
    u = (u or "").strip().rstrip("/")
    if u and not u.lower().startswith(("http://", "https://")):
        u = "http://" + u
    return u


def bundled_server_urls() -> list:
    """Server addresses shipped in server_url.txt next to the app (one per line,
    '#' = comment). The admin edits this ONE file; every install picks it up."""
    path = os.path.join(_app_dir(), SERVER_URL_FILE)
    out = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line and normalise_url(line) not in out:
                    out.append(normalise_url(line))
    except Exception:
        pass
    return out


def candidate_server_urls() -> list:
    """Saved address first, then the shipped ones (no duplicates)."""
    out = []
    for u in [load_config().get("server_url", "")] + bundled_server_urls():
        u = normalise_url(u)
        if u and u not in out:
            out.append(u)
    return out
LOG_PATH = os.path.join(APP_DIR, "client.log")


def setup_logging() -> str:
    """Rotating log at %APPDATA%\\IntelliBILeadAlert\\client.log (the .exe has no
    console, so this is where connection problems are recorded)."""
    import logging
    from logging.handlers import RotatingFileHandler
    _ensure_dir()
    root = logging.getLogger("leadalert")
    if not root.handlers:
        h = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2,
                                encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
        root.setLevel(logging.INFO)
    return LOG_PATH


def _ensure_dir():
    os.makedirs(APP_DIR, exist_ok=True)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception:
        d = {}
    out = dict(DEFAULTS)
    out.update({k: d.get(k, v) for k, v in DEFAULTS.items()})
    return out


def save_config(cfg: dict) -> None:
    _ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ── token (DPAPI-encrypted) ──────────────────────────────────────────────────
def _dpapi_protect(raw: bytes):
    import win32crypt  # pywin32
    return win32crypt.CryptProtectData(raw, "IntelliBILeadAlert",
                                       None, None, None, 0)


def _dpapi_unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]


def save_token(token: str) -> None:
    _ensure_dir()
    raw = token.encode("utf-8")
    try:
        blob = _dpapi_protect(raw)
        with open(TOKEN_BIN, "wb") as f:
            f.write(blob)
        if os.path.exists(TOKEN_TXT):
            os.remove(TOKEN_TXT)
    except Exception as e:
        print("  [client] DPAPI unavailable, storing token in plain file:", e)
        with open(TOKEN_TXT, "w", encoding="utf-8") as f:
            f.write(token)


def load_token() -> str:
    if os.path.exists(TOKEN_BIN):
        try:
            with open(TOKEN_BIN, "rb") as f:
                return _dpapi_unprotect(f.read()).decode("utf-8")
        except Exception as e:
            print("  [client] could not decrypt token.bin:", e)
    if os.path.exists(TOKEN_TXT):
        try:
            with open(TOKEN_TXT, encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


def clear_token() -> None:
    for p in (TOKEN_BIN, TOKEN_TXT):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def is_registered() -> bool:
    cfg = load_config()
    return bool(cfg.get("server_url")) and bool(load_token())
