#!/usr/bin/env python3
"""
interakt_session.py
===================
Keep the Interakt web session alive for pyInteraktUsers.py WITHOUT storing any
username/password.

A dedicated persistent browser profile
(config_files/interakt_browser_profile/) is logged in ONCE by you, in a real
browser window. After that every scheduled run re-opens that profile headlessly
(already logged in), captures a live api.interakt.ai request's headers
(cookie + x-interakt-org-id + x-subscription-*), and writes them to
config_files/interakt_curl.txt in the exact "curl -H … -b …" shape the enricher
already parses. No password is ever typed into a file; you sign in yourself, one
time, so OTP / 2-factor / CAPTCHA are handled by you in the window.

--------------------------------------------------------------------------------
ONE-TIME SETUP (about 30 seconds)
--------------------------------------------------------------------------------
    .venv\\Scripts\\python.exe -m pip install playwright
    .venv\\Scripts\\python.exe -m playwright install chromium
    .venv\\Scripts\\python.exe interakt_session.py --setup
        -> a browser window opens on Interakt. Log in normally. Once the
           dashboard loads, the window closes itself and the session is saved.

After that it's fully automatic. Repeat --setup only if the saved session ever
fully expires (the log tells you when).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

log = logging.getLogger("interakt.session")

# --- IntelliBI Sales Automation portability bootstrap (auto-inserted) ---
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap  # noqa: E402  (sys.path + env defaults + config.yaml)
from paths import CREDENTIALS_DIR, CONFIG_DIR, LOGS_DIR  # noqa: E402
# --- end bootstrap ---

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(CREDENTIALS_DIR, "interakt_browser_profile")
CURL_FILE = os.path.join(CREDENTIALS_DIR, "interakt_curl.txt")
CONFIG_FILE = os.path.join(CREDENTIALS_DIR, "interakt_session_config.json")

DEFAULT_STALE_HOURS = 12
DEFAULT_LOGIN_URL = "https://app.interakt.ai/"

_DROP_HEADERS = {
    "accept-encoding", "content-length", "host", "connection",
    "content-type", "accept", "accept-language", "cache-control",
    "pragma", "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "referer",
    "origin", "user-agent",
}


class InteraktLoginError(RuntimeError):
    pass


class InteraktSetupRequired(InteraktLoginError):
    """The saved session is missing/expired — a one-time --setup login is needed."""


def _cfg() -> dict:
    cfg = {"login_url": DEFAULT_LOGIN_URL, "headless": True}
    try:
        if os.path.isfile(CONFIG_FILE):
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")) or {})
    except Exception:
        pass
    return cfg


def profile_ready() -> bool:
    return os.path.isdir(PROFILE_DIR) and bool(os.listdir(PROFILE_DIR))


def playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def login_available() -> bool:
    return playwright_installed() and profile_ready()


def session_is_fresh(stale_hours: float = DEFAULT_STALE_HOURS) -> bool:
    try:
        if not (os.path.isfile(CURL_FILE) and os.path.getsize(CURL_FILE) > 0):
            return False
        return (time.time() - os.path.getmtime(CURL_FILE)) / 3600.0 < stale_hours
    except Exception:
        return False


def _write_curl(url: str, headers: dict, cookie: str) -> None:
    lines = [f"curl '{url}' \\"]
    for name, value in headers.items():
        if not name or name.lower() in _DROP_HEADERS or name.startswith(":"):
            continue
        if not value:
            continue
        safe = str(value).replace("'", "'\\''")
        lines.append(f"  -H '{name}: {safe}' \\")
    if cookie:
        lines.append(f"  -b '{cookie.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'")
    else:
        lines[-1] = lines[-1].rstrip(" \\")
    tmp = CURL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, CURL_FILE)


def _cookie_header(context, domain_hint="interakt.ai") -> str:
    try:
        jar = context.cookies()
    except Exception:
        return ""
    pairs, seen = [], set()
    for c in jar:
        if domain_hint not in str(c.get("domain", "")):
            continue
        name = c.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        pairs.append(f"{name}={c.get('value', '')}")
    return "; ".join(pairs)


def _capture_via_profile(headless: bool):
    """Open the saved profile, load the dashboard, and capture the first
    authenticated api.interakt.ai request (url, headers) + cookie header.
    Returns (url, headers, cookie) or (None, None, cookie)."""
    from playwright.sync_api import sync_playwright
    login_url = _cfg().get("login_url", DEFAULT_LOGIN_URL)
    candidates = []

    def _on_request(req):
        try:
            if "api.interakt.ai" not in req.url:
                return
            hdrs = req.all_headers()
            if any(k.lower() == "x-interakt-org-id" for k in hdrs):
                candidates.append((req.url, hdrs))
        except Exception:
            pass

    def _attach(pg):
        # Listen on EVERY page (initial, plus any tab/popup the login flow opens),
        # so we still capture the authenticated request if the original page is
        # closed or replaced during sign-in.
        try:
            pg.on("request", _on_request)
        except Exception:
            pass

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE_DIR, headless=headless)
        ctx.on("page", _attach)                 # future tabs/popups
        for pg in ctx.pages:                    # already-open pages
            _attach(pg)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        # Wait for authenticated bootstrap calls (longer in --setup where a human
        # may still be logging in). Poll with a plain sleep — NOT page.wait_for_
        # timeout — so the loop never crashes when the login page is closed or
        # swapped out mid-sign-in (the cause of the "Target page ... has been
        # closed" error). Requests are captured at the context level regardless.
        deadline = time.time() + (300 if not headless else 45)
        while time.time() < deadline and not candidates:
            time.sleep(1)

        if not candidates and headless:
            for pg in list(ctx.pages):          # reload any live page to re-trigger
                try:
                    pg.reload(wait_until="domcontentloaded", timeout=30000)
                    break
                except Exception:
                    continue
            deadline = time.time() + 20
            while time.time() < deadline and not candidates:
                time.sleep(1)

        cookie = _cookie_header(ctx)
        best = None
        for url, hdrs in candidates:
            if "/members" in url or "/organizations/" in url:
                best = (url, hdrs)
                break
        best = best or (candidates[-1] if candidates else (None, None))
        try:
            ctx.close()
        except Exception:
            pass
    return best[0], best[1], cookie


def _persist(url, headers, cookie) -> None:
    req_cookie = ""
    for k, v in (headers or {}).items():
        if k.lower() == "cookie":
            req_cookie = v
            break
    cookie = req_cookie or cookie
    headers = {k: v for k, v in (headers or {}).items() if k.lower() != "cookie"}
    if not any(k.lower() == "x-interakt-org-id" for k in headers):
        raise InteraktLoginError("Captured request lacked x-interakt-org-id.")
    _write_curl(url, headers, cookie)


def setup_login(logger: logging.Logger | None = None) -> bool:
    lg = logger or log
    if not playwright_installed():
        raise InteraktLoginError(
            "Playwright not installed. Run:\n"
            "  .venv\\Scripts\\python.exe -m pip install playwright\n"
            "  .venv\\Scripts\\python.exe -m playwright install chromium")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print("\n" + "=" * 64)
    print(" A browser window is opening on Interakt.")
    print(" Log in normally. Nothing is stored by this script — your login is")
    print(" saved only inside the browser profile. The window closes itself")
    print(" once the dashboard has loaded.")
    print("=" * 64 + "\n")
    url, headers, cookie = _capture_via_profile(headless=False)
    if not headers:
        raise InteraktLoginError(
            "Login wasn't detected. Re-run --setup and make sure the Interakt "
            "dashboard fully loads in the window.")
    _persist(url, headers, cookie)
    lg.info("Interakt login saved to the browser profile + session exported.")
    return True


def refresh_session(force: bool = False,
                    stale_hours: float = DEFAULT_STALE_HOURS,
                    logger: logging.Logger | None = None) -> bool:
    lg = logger or log
    if not force and session_is_fresh(stale_hours):
        lg.info("Interakt session still fresh (< %.0fh) — skipping refresh.",
                stale_hours)
        return False
    if not profile_ready():
        raise InteraktSetupRequired(
            "No saved Interakt login yet. Run once:\n"
            "  .venv\\Scripts\\python.exe interakt_session.py --setup")
    url, headers, cookie = _capture_via_profile(headless=bool(_cfg().get("headless", True)))
    if not headers:
        raise InteraktSetupRequired(
            "Saved Interakt session has expired. Re-run once:\n"
            "  .venv\\Scripts\\python.exe interakt_session.py --setup")
    _persist(url, headers, cookie)
    lg.info("Interakt session refreshed from the saved login → %s", CURL_FILE)
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(message)s")
    args = [a.lower() for a in sys.argv[1:]]
    try:
        if any(a in ("--setup", "setup", "-s") for a in args):
            setup_login()
            print("SUCCESS: Interakt login saved. Scheduled runs are now automatic.")
            return 0
        force = any(a in ("-f", "--force", "force") for a in args)
        wrote = refresh_session(force=force)
        print("Fresh Interakt session exported." if wrote
              else "Session still fresh — nothing to do (use --force).")
        return 0
    except InteraktSetupRequired as exc:
        print(f"[SETUP NEEDED] {exc}")
        return 3
    except InteraktLoginError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Unexpected: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
