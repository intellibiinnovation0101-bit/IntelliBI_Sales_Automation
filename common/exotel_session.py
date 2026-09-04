#!/usr/bin/env python3
"""
exotel_session.py
=================
Keep the my.exotel.com Inbox session alive for pyExotelCallDetails.py WITHOUT
storing any username/password.

How it works: a dedicated, persistent browser profile
(config_files/exotel_browser_profile/) is logged in ONCE by you, in a real
browser window. After that every scheduled run re-opens that same profile
headlessly — it's already logged in — refreshes the session, and exports the
current cookie to config_files/exotel_web_cookie.txt (the file the scraper
reads). No password is ever typed into a file; you sign in yourself, one time,
so OTP / 2-factor / CAPTCHA are handled by you in the window.

--------------------------------------------------------------------------------
ONE-TIME SETUP (about 30 seconds)
--------------------------------------------------------------------------------
    .venv\\Scripts\\python.exe -m pip install playwright
    .venv\\Scripts\\python.exe -m playwright install chromium
    .venv\\Scripts\\python.exe exotel_session.py --setup
        -> a browser window opens on my.exotel.com. Log in normally (incl. any
           OTP). Once the Inbox loads, the window closes itself and the session
           is saved. Done.

After that it is fully automatic — the scheduled sync reuses the saved login and
refreshes it every run. You only repeat --setup if you ever fully log out /
the saved session finally expires (the log tells you when).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

log = logging.getLogger("exotel.session")

# --- IntelliBI Sales Automation portability bootstrap (auto-inserted) ---
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import _bootstrap  # noqa: E402  (sys.path + env defaults + config.yaml)
from paths import CREDENTIALS_DIR, CONFIG_DIR, LOGS_DIR  # noqa: E402
# --- end bootstrap ---

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(CREDENTIALS_DIR, "exotel_browser_profile")
COOKIE_FILE = os.path.join(CREDENTIALS_DIR, "exotel_web_cookie.txt")
CRED_FILE = os.path.join(CREDENTIALS_DIR, "exotel_credentials.json")
CONFIG_FILE = os.path.join(CREDENTIALS_DIR, "exotel_session_config.json")

DEFAULT_STALE_HOURS = 12
DEFAULT_LOGIN_URL = "https://my.exotel.com/"

# Which browser Playwright drives for the saved login profile.
#   "msedge"  -> the real Microsoft Edge installed on the machine (default on
#                Windows; behaves like a normal browser, which the Exotel login
#                accepts more reliably than the bundled automation Chromium).
#   "chrome"  -> the installed Google Chrome.
#   ""/"chromium" -> Playwright's bundled Chromium (the old behaviour).
# Override per-machine with the EXOTEL_BROWSER_CHANNEL environment variable.
BROWSER_CHANNEL = os.environ.get("EXOTEL_BROWSER_CHANNEL", "msedge").strip()


def _open_profile(p, headless):
    """Open the persistent login profile in the configured browser channel,
    falling back to Playwright's bundled Chromium if that channel is not
    installed on this machine."""
    if BROWSER_CHANNEL and BROWSER_CHANNEL.lower() != "chromium":
        try:
            return p.chromium.launch_persistent_context(
                PROFILE_DIR, headless=headless, channel=BROWSER_CHANNEL)
        except Exception as _e:  # channel not found -> bundled Chromium
            log.info("Browser channel %r not available (%s) - using bundled "
                     "Chromium instead.", BROWSER_CHANNEL, _e)
    return p.chromium.launch_persistent_context(PROFILE_DIR, headless=headless)


class ExotelLoginError(RuntimeError):
    pass


class ExotelSetupRequired(ExotelLoginError):
    """The saved session is missing/expired — a one-time --setup login is needed."""


# ---------------------------------------------------------------------------
def _cfg() -> dict:
    cfg = {"login_url": DEFAULT_LOGIN_URL, "headless": True}
    try:
        if os.path.isfile(CONFIG_FILE):
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")) or {})
    except Exception:
        pass
    return cfg


def _account_sid() -> str:
    try:
        return (json.load(open(CRED_FILE, encoding="utf-8")).get("sid") or "").strip()
    except Exception:
        return ""


def profile_ready() -> bool:
    """True once a login has been saved into the persistent profile."""
    return os.path.isdir(PROFILE_DIR) and bool(os.listdir(PROFILE_DIR))


def playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def login_available() -> bool:
    """Auto-refresh is possible only after a one-time --setup (profile exists)
    and with Playwright installed."""
    return playwright_installed() and profile_ready()


def session_is_fresh(stale_hours: float = DEFAULT_STALE_HOURS) -> bool:
    try:
        if not (os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0):
            return False
        return (time.time() - os.path.getmtime(COOKIE_FILE)) / 3600.0 < stale_hours
    except Exception:
        return False


def _cookie_header(context, domain_hint="exotel.com") -> str:
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


def _write_cookie(cookie: str) -> None:
    tmp = COOKIE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(cookie.strip() + "\n")
    os.replace(tmp, COOKIE_FILE)


def _inbox_logged_in(page, sid, settle_ms=3500) -> bool:
    """Load the Inbox and report whether it shows call rows (i.e. we're in)."""
    if not sid:
        # No sid to check against; treat a non-login URL as good enough.
        return "login" not in (page.url or "").lower()
    try:
        page.goto(f"https://my.exotel.com/{sid}/callindex",
                  wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(settle_ms)
        html = page.content()
        return ("data-callsid" in html) or ("ex-inbox-cl-list" in html)
    except Exception:
        return False


def setup_login(logger: logging.Logger | None = None) -> bool:
    """Interactive ONE-TIME login into the persistent profile (visible window)."""
    lg = logger or log
    if not playwright_installed():
        raise ExotelLoginError(
            "Playwright not installed. Run:\n"
            "  .venv\\Scripts\\python.exe -m pip install playwright\n"
            "  .venv\\Scripts\\python.exe -m playwright install chromium")
    from playwright.sync_api import sync_playwright
    os.makedirs(PROFILE_DIR, exist_ok=True)
    sid = _account_sid()
    login_url = _cfg().get("login_url", DEFAULT_LOGIN_URL)

    print("\n" + "=" * 64)
    print(" A browser window is opening on my.exotel.com.")
    print(" Log in normally (including any OTP). Nothing is stored by this")
    print(" script — your login is saved only inside the browser profile.")
    print(" The window closes itself once the Inbox is detected.")
    print("=" * 64 + "\n")

    with sync_playwright() as p:
        ctx = _open_profile(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        # Poll for up to 5 minutes for a logged-in Inbox.
        deadline = time.time() + 300
        ok = False
        while time.time() < deadline:
            if sid and _inbox_logged_in(page, sid):
                ok = True
                break
            time.sleep(3)
        cookie = _cookie_header(ctx)
        if not ok and cookie and "exoteloblx" in cookie.lower():
            ok = True  # cookie is present even if the inbox check was racy
        if ok and cookie:
            _write_cookie(cookie)
        try:
            ctx.close()
        except Exception:
            pass

    if not ok:
        raise ExotelLoginError(
            "Login wasn't detected within 5 minutes. Re-run --setup and make "
            "sure you reach the Exotel Inbox in the window.")
    lg.info("Exotel login saved to the browser profile + cookie exported.")
    return True


def refresh_session(force: bool = False,
                    stale_hours: float = DEFAULT_STALE_HOURS,
                    logger: logging.Logger | None = None) -> bool:
    """Headless: reuse the saved profile (no password) and export a fresh cookie.
    Raises ExotelSetupRequired if the saved session is gone/expired."""
    lg = logger or log
    if not force and session_is_fresh(stale_hours):
        lg.info("Exotel cookie still fresh (< %.0fh) — skipping refresh.",
                stale_hours)
        return False
    if not profile_ready():
        raise ExotelSetupRequired(
            "No saved Exotel login yet. Run once:\n"
            "  .venv\\Scripts\\python.exe exotel_session.py --setup")
    from playwright.sync_api import sync_playwright
    sid = _account_sid()
    headless = bool(_cfg().get("headless", True))

    with sync_playwright() as p:
        ctx = _open_profile(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        logged_in = _inbox_logged_in(page, sid)
        cookie = _cookie_header(ctx)
        try:
            ctx.close()
        except Exception:
            pass

    if not logged_in and not (cookie and "exoteloblx" in cookie.lower()):
        raise ExotelSetupRequired(
            "Saved Exotel session has expired. Re-run once:\n"
            "  .venv\\Scripts\\python.exe exotel_session.py --setup")
    if not cookie:
        raise ExotelLoginError("Could not export a cookie from the saved profile.")
    _write_cookie(cookie)
    lg.info("Exotel Inbox cookie refreshed from the saved login → %s", COOKIE_FILE)
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(message)s")
    args = [a.lower() for a in sys.argv[1:]]
    try:
        if any(a in ("--setup", "setup", "-s") for a in args):
            setup_login()
            print("SUCCESS: Exotel login saved. Scheduled runs are now automatic.")
            return 0
        force = any(a in ("-f", "--force", "force") for a in args)
        wrote = refresh_session(force=force)
        print("Fresh Exotel cookie exported." if wrote
              else "Cookie still fresh — nothing to do (use --force).")
        return 0
    except ExotelSetupRequired as exc:
        print(f"[SETUP NEEDED] {exc}")
        return 3
    except ExotelLoginError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Unexpected: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
