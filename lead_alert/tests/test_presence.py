"""
Presence / reachability tests — REAL uvicorn server + the counsellor app's own
WebSocket client over real TCP sockets (no Google, no GUI, synthetic data only).

Covers the 2026-10-06 incident ("status ok, 0 counsellors online, nobody gets
popups") and the permanent fix:
  * network self-check: Public network + Private-only firewall rule is detected
  * online only with a live heartbeat; silent (half-open) sockets become STALE,
    are closed and logged
  * refused connections (unknown computer / inactive counsellor) are logged,
    shown in /health and reported to the app as AUTH_FAILED
  * leads that arrived while nobody was online pop up on reconnect
  * the app reconnects by itself after a server restart / dead connection
  * the "no counsellor online" alert fires only when nobody is genuinely online
    (not during startup grace, not while the monitor is unhealthy, once per lead)
    and says "server not reachable" when the self-check found a firewall block
  * device tokens never appear in the server log

Run:  python lead_alert/tests/test_presence.py
"""
import asyncio
import json
import logging
import queue
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "service"))
sys.path.insert(0, str(_ROOT / "client"))

import config  # noqa: E402


def _free_udp():
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.bind(("127.0.0.1", 0))
    p = u.getsockname()[1]
    u.close()
    return p

config.DB_PATH = Path(tempfile.mkdtemp()) / "presence.db"
CJ = Path(tempfile.mkdtemp()) / "counsellors.json"


def write_counsellors(bravo_status="Active"):
    CJ.write_text(json.dumps({
        "counsellors": [
            {"counsellor_name": "Alpha", "emailid": "alpha@x.com", "current_status": "Active"},
            {"counsellor_name": "Bravo", "emailid": "bravo@x.com", "current_status": bravo_status},
        ],
        "intellibiadmin": [
            {"intellibi_admin_name": "Admin", "emailid": "admin@x.com", "current_status": "Active"}],
    }), encoding="utf-8")


write_counsellors()
S = config.SETTINGS
S.counsellors_json = str(CJ)
S.alert_sections = ["counsellors"]
S.escalate_to_section = "intellibiadmin"
S.enabled = False                 # no Google poller in tests
S.log_sheet_id = ""
S.enrollment_code = lambda: "CODE"
S.heartbeat_stale_seconds = 3
S.presence_sweep_seconds = 1
S.startup_grace_seconds = 2
S.no_online_alert = True          # optional per-lead alert, exercised here
S.no_online_alert_after_seconds = 0
S.no_online_alert_cooldown_min = 0
S.netcheck_minutes = 0            # self-check driven by the test
S.discovery_port = _free_udp()
_t = socket.socket()
_t.bind(("127.0.0.1", 0))
S.port = _t.getsockname()[1]          # the service advertises its real port
_t.close()

import uvicorn  # noqa: E402
import app  # noqa: E402
import background  # noqa: E402
import mailer  # noqa: E402
import netcheck  # noqa: E402
import ops  # noqa: E402
import store  # noqa: E402
import ws_client  # noqa: E402
import discovery  # noqa: E402
import discovery_client  # noqa: E402
from hub import HUB  # noqa: E402

ws_client.PING_EVERY = 1          # app heartbeat every second in tests
ws_client.DEAD_AFTER = 4
ws_client.AUTH_RETRY = 2
ws_client.DISCOVER_EVERY = 1
ws_client.DISCOVERY_TARGETS = ["127.0.0.1"]

fails = []


def check(name, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  -- {extra}"))
    if not cond:
        fails.append(name)


def wait_for(fn, timeout=12.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


# capture server log output (uvicorn + our prints are both checked)
LOG_LINES = []


class _Cap(logging.Handler):
    def emit(self, record):
        LOG_LINES.append(self.format(record))


_cap = _Cap()
for n in ("uvicorn.error", "uvicorn.access"):
    logging.getLogger(n).addHandler(_cap)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = S.port
BASE = f"http://127.0.0.1:{PORT}"


class ServerThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.server = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=PORT,
                                                    log_level="info"))
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.serve())

    def start(self):
        self.t.start()
        assert wait_for(lambda: self.server.started, 10), "server did not start"
        for n in ("uvicorn.error", "uvicorn.access"):       # uvicorn reconfigures logging
            lg = logging.getLogger(n)
            if _cap not in lg.handlers:
                lg.addHandler(_cap)
        return self

    def stop(self):
        self.server.should_exit = True
        self.t.join(10)

    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(15)


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=10).read())


def post(path, body):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=10).read())


def events(q, secs):
    out, end = [], time.time() + secs
    while time.time() < end:
        try:
            out.append(q.get(timeout=0.1))
        except queue.Empty:
            pass
    return out


# ── 1. network self-check decisions (pure) ──────────────────────────────────
INCIDENT = {"networks": [{"Name": "Classroom 5G 3", "Category": "Public"}],
            "profiles": [{"Name": "Public", "Enabled": "True", "AllowInboundRules": "True",
                          "DefaultInboundAction": "NotConfigured"},
                         {"Name": "Private", "Enabled": "True", "AllowInboundRules": "True",
                          "DefaultInboundAction": "NotConfigured"}],
            "rules": [{"Name": "IntelliBI Lead Alert 8787", "Profile": "Private",
                       "Remote": "Any", "Kind": "port"}]}
r = netcheck.evaluate(INCIDENT)
check("netcheck: incident (Public network, Private-only rule) is BLOCKED", r["ok"] is False)
check("netcheck: message names the network and the rule",
      "Classroom 5G 3" in r["summary"] and "Public" in r["summary"]
      and "IntelliBI Lead Alert 8787" in r["summary"], r["summary"])
check("netcheck: fix command offered", "Set-NetFirewallRule" in r["fix"])
fixed = json.loads(json.dumps(INCIDENT))
fixed["rules"][0]["Profile"] = "Any"
check("netcheck: rule for Any profile -> ok", netcheck.evaluate(fixed)["ok"] is True)
both = json.loads(json.dumps(INCIDENT))
both["rules"][0]["Profile"] = "Private, Public"
check("netcheck: rule 'Private, Public' -> ok", netcheck.evaluate(both)["ok"] is True)
off = json.loads(json.dumps(INCIDENT))
off["profiles"][0]["Enabled"] = "False"
check("netcheck: firewall off for Public -> ok", netcheck.evaluate(off)["ok"] is True)
shield = json.loads(json.dumps(fixed))
shield["profiles"][0]["AllowInboundRules"] = "False"
check("netcheck: 'block all incoming' -> blocked even with a rule",
      netcheck.evaluate(shield)["ok"] is False)
prog = json.loads(json.dumps(INCIDENT))
prog["rules"].append({"Name": "python", "Profile": "Public", "Kind": "program"})
check("netcheck: python program rule on Public -> ok", netcheck.evaluate(prog)["ok"] is True)
dom = {"networks": [{"Name": "corp", "Category": "DomainAuthenticated"}],
       "profiles": [{"Name": "Domain", "Enabled": "True", "AllowInboundRules": "True"}],
       "rules": [{"Name": "r", "Profile": "Private"}]}
check("netcheck: Domain network needs a Domain rule", netcheck.evaluate(dom)["ok"] is False)
check("netcheck: no network at all -> problem", netcheck.evaluate({})["ok"] is False)
single = {"networks": {"Name": "lan", "Category": "Private"},
          "profiles": {"Name": "Private", "Enabled": "True", "AllowInboundRules": "True"},
          "rules": {"Name": "r", "Profile": "Private"}}
check("netcheck: single objects (PowerShell JSON quirk) handled",
      netcheck.evaluate(single)["ok"] is True)

udp_missing = json.loads(json.dumps(fixed))
udp_missing["udp_rules"] = []
r = netcheck.evaluate(udp_missing)
check("netcheck: discovery port blocked -> warning + repairable, alerts still ok",
      r["ok"] is True and r["warnings"] and r["repairable"] is True, r)
check("netcheck: incident is auto-repairable", netcheck.evaluate(INCIDENT)["repairable"] is True)
check("netcheck: 'block all incoming' is NOT auto-changed",
      netcheck.evaluate(shield)["repairable"] is False)
check("netcheck: repair() refuses off Windows (no side effects here)",
      netcheck.repair()[0] is False)

# discovery protocol (pure)
_tok = "synthetic-token-1"
_req = discovery.REQ + json.dumps({"id": discovery.token_id(_tok), "nonce": "abcdef0123456789"}).encode()
_rep = discovery.build_reply(_req, [_tok, "other"], 8787, "OFFICE")
check("discovery: answers a registered computer with an HMAC proof",
      _rep is not None and json.loads(_rep[len(discovery.REP):])["proof"]
      == discovery.proof(_tok, "abcdef0123456789", 8787))
check("discovery: ignores unknown computers",
      discovery.build_reply(_req, ["other"], 8787, "OFFICE") is None)
check("discovery: ignores junk", discovery.build_reply(b"hello", [_tok], 8787, "X") is None)

# firewall scope: a rule limited to the same subnet is widened by auto-repair
narrow = json.loads(json.dumps(fixed))
narrow["rules"][0]["Remote"] = "LocalSubnet"
r = netcheck.evaluate(narrow)
check("netcheck: 'LocalSubnet only' rule -> still ok here, but flagged + repairable",
      r["ok"] is True and r["repairable"] is True and any("only admits" in w for w in r["warnings"]), r)
wide = json.loads(json.dumps(fixed))
wide["rules"][0]["Remote"] = ("LocalSubnet,10.0.0.0/255.0.0.0,172.16.0.0/255.240.0.0,"
                              "192.168.0.0/255.255.0.0,100.64.0.0/255.192.0.0")
check("netcheck: rule as written by repair (Windows mask format) -> no warning",
      netcheck.evaluate(wide)["warnings"] == [], netcheck.evaluate(wide))
check("netcheck: repair scope includes private-network (Tailscale) range",
      "100.64.0.0/10" in netcheck.REMOTE)

# shipped server addresses (server_url.txt next to the app)
import client_config  # noqa: E402
_d = tempfile.mkdtemp()
Path(_d, "server_url.txt").write_text("# comment\n\n192.168.1.202:8787\nhttp://office-pc:8787/  # name\n"
                                      "http://192.168.1.202:8787\n", encoding="utf-8")
client_config._app_dir = lambda: _d
check("server_url.txt: comments skipped, http:// added, duplicates removed",
      client_config.bundled_server_urls() == ["http://192.168.1.202:8787", "http://office-pc:8787"],
      client_config.bundled_server_urls())

# ── 2. token redaction filter ───────────────────────────────────────────────
rec = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1,
                        '%s - "WebSocket %s" [accepted]',
                        ("1.2.3.4:5", "/ws?token=SECRET123&v=1"), None)
app._RedactTokens().filter(rec)
check("log filter redacts ?token=", "SECRET123" not in rec.getMessage()
      and "token=***" in rec.getMessage(), rec.getMessage())

# ── 3. live server ──────────────────────────────────────────────────────────
mail_calls = []
mailer.send_no_online_alert = lambda leads, info: mail_calls.append((leads, info)) or True
netcheck.LAST.update({"ok": True, "summary": "counsellor computers can reach port 8787",
                      "problems": [], "fix": ""})

srv = ServerThread().start()
h = get("/health")
check("health: legacy keys kept", all(k in h for k in (
    "status", "online_counsellors", "active_window", "alert_sections", "seeded", "last_poll")))
check("health: both counsellors not_registered at start",
      h["presence"]["counts"]["not_registered"] == 2, h["presence"]["counts"])

# a lead arrives while NOBODY is online
lead_id = post("/demo/inject", {"code": "CODE", "name": "Synthetic Lead",
                                "mobile": "0000000000", "form_type": "Web"})["injected"]
check("dispatch with nobody online is logged",
      True)  # printed to stdout: "[dispatch] ... NOBODY"

# no alert during startup grace
check("no-online alert withheld during startup grace",
      srv.call(background.check_no_one_online()) is False and not mail_calls)
time.sleep(S.startup_grace_seconds + 0.5)

# monitor unhealthy -> withheld
_orig = HUB.sweeper_healthy
HUB.sweeper_healthy = lambda: False
check("no-online alert withheld while presence monitor unhealthy",
      srv.call(background.check_no_one_online()) is False and not mail_calls)
HUB.sweeper_healthy = _orig

# genuine: nobody online, lead waiting -> alert once
check("no-online alert sent when nobody is genuinely online",
      srv.call(background.check_no_one_online()) is True and len(mail_calls) == 1)
check("alert lists the waiting lead",
      mail_calls and [l["lead_id"] for l in mail_calls[0][0]] == [lead_id])
check("alert carries presence + network context",
      mail_calls and "presence" in mail_calls[0][1] and "network" in mail_calls[0][1])
check("same lead never alerted twice",
      srv.call(background.check_no_one_online()) is False and len(mail_calls) == 1)

# ── register Alpha and connect with the REAL app client ─────────────────────
tok_a = post("/enroll", {"email": "alpha@x.com", "code": "CODE", "machine": "PC-A"})["token"]
qa = queue.Queue()
ca = ws_client.WSClient(BASE, tok_a, qa, version="test")
ca.start()
ev = events(qa, 3)
types = [e.get("type") for e in ev]
check("app connects (header auth)", ws_client.CONNECTED in types, types)
check("lead that arrived while offline pops up on connect (resync)",
      any(e.get("type") == "NEW_LEAD" and e["lead"]["lead_id"] == lead_id
          and e.get("resync") for e in ev), types)
h = get("/health")
check("health: Alpha online", h["online_counsellors"] == ["alpha@x.com"], h["online_counsellors"])
alpha = [c for c in h["presence"]["counsellors"] if c["email"] == "alpha@x.com"][0]
check("health: Alpha state online with computer + IP",
      alpha["state"] == "online" and alpha["connections"][0]["machine"] == "PC-A"
      and alpha["connections"][0]["ip"] == "127.0.0.1", alpha)
check("health: app version recorded", alpha["connections"][0]["app_version"] == "test")
check("token not in server log", not any(tok_a in l for l in LOG_LINES))

# LAN discovery against the live server
check("discovery: app finds the real server",
      discovery_client.discover(tok_a, S.discovery_port, targets=["127.0.0.1"]) == BASE)
check("discovery: unknown token gets no answer",
      discovery_client.discover("nope", S.discovery_port, timeout=1.0,
                                targets=["127.0.0.1"]) == "")
_rogue = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_rogue.bind(("127.0.0.1", 0))
_rport = _rogue.getsockname()[1]


def _rogue_answer():
    data, addr = _rogue.recvfrom(2048)
    _rogue.sendto(discovery.REP + json.dumps({"port": 9999, "proof": "0" * 64}).encode(), addr)


threading.Thread(target=_rogue_answer, daemon=True).start()
check("discovery: a fake server's reply is rejected",
      discovery_client.discover(tok_a, _rport, timeout=1.5, targets=["127.0.0.1"]) == "")
_rogue.close()

# stays online across several heartbeat periods (no false offline)
time.sleep(S.heartbeat_stale_seconds * 2 + 1)
check("Alpha stays online over 2x the stale window (heartbeats work)",
      get("/health")["online_counsellors"] == ["alpha@x.com"])

# someone online -> never the no-online alert
lead2 = post("/demo/inject", {"code": "CODE", "name": "Synthetic Lead 2",
                              "mobile": "0000000001", "form_type": "Web"})["injected"]
got2 = events(qa, 2)
check("online app gets a new lead immediately",
      any(e.get("type") == "NEW_LEAD" and e["lead"]["lead_id"] == lead2 for e in got2))
check("no no-online alert while a counsellor is online",
      srv.call(background.check_no_one_online()) is False and len(mail_calls) == 1)

# ── half-open connection: connects, then goes silent -> STALE -> removed ────
import websocket  # noqa: E402
tok_b = post("/enroll", {"email": "bravo@x.com", "code": "CODE", "machine": "PC-B"})["token"]
raw = websocket.create_connection(BASE.replace("http", "ws") + "/ws",
                                  header=[f"Authorization: Bearer {tok_b}"])
raw.settimeout(5)
check("silent client counted online at first",
      wait_for(lambda: "bravo@x.com" in get("/health")["online_counsellors"], 3))
check("silent client becomes stale and is dropped",
      wait_for(lambda: "bravo@x.com" not in get("/health")["online_counsellors"], 10))
check("stale connection is closed by the sweeper",
      wait_for(lambda: [c for c in get("/health")["presence"]["counsellors"]
                        if c["email"] == "bravo@x.com"][0]["state"] == "offline", 5))
bravo = [c for c in get("/health")["presence"]["counsellors"] if c["email"] == "bravo@x.com"][0]
check("dropped client shows offline with STALE reason",
      bravo["state"] == "offline"
      and "STALE" in (bravo["computers"][0]["last_disconnect_reason"] or ""), bravo)
raw.close()

# ── refused connections ─────────────────────────────────────────────────────
qx = queue.Queue()
cx = ws_client.WSClient(BASE, "not-a-real-token", qx)
cx.start()
evx = events(qx, 2)
check("unknown computer -> app told AUTH_FAILED (not silent)",
      any(e.get("type") == ws_client.AUTH_FAILED and e.get("reason") == "not_registered"
          for e in evx), [e.get("type") for e in evx])
check("refusal is not mis-reported as 'cannot reach server'",
      ws_client.DISCONNECTED not in [e.get("type") for e in evx], [e.get("type") for e in evx])
cx.stop()
h = get("/health")
check("refusal recorded in /health",
      any("not registered" in r["reason"] for r in h["recent_refused_connections"]))

write_counsellors(bravo_status="Inactive")
qb = queue.Queue()
cb = ws_client.WSClient(BASE, tok_b, qb)
cb.start()
evb = events(qb, 2)
check("inactive counsellor -> AUTH_FAILED reason inactive",
      any(e.get("type") == ws_client.AUTH_FAILED and e.get("reason") == "inactive"
          for e in evb), [e.get("type") for e in evb])
cb.stop()
write_counsellors()

# old-style app (?token= in URL) still accepted, and the token is redacted in logs
old = websocket.create_connection(BASE.replace("http", "ws") + f"/ws?token={tok_b}")
old.settimeout(5)
got_old = [json.loads(old.recv()) for _ in range(3)]
check("app built before the fix (token in URL) still connects",
      any(m.get("type") == "HELLO" for m in got_old), got_old)
check("old-style token redacted in uvicorn log",
      not any(tok_b in l for l in LOG_LINES) and any("token=***" in l for l in LOG_LINES),
      [l for l in LOG_LINES if "WebSocket" in l][-2:])
old.close()

# ── server restart: app reconnects by itself ────────────────────────────────
srv.stop()
evd = events(qa, 3)
check("app notices the server went away",
      any(e.get("type") == ws_client.DISCONNECTED for e in evd), [e.get("type") for e in evd])
srv = ServerThread().start()
evr = events(qa, 12)
check("app reconnects automatically after server restart",
      ws_client.CONNECTED in [e.get("type") for e in evr], [e.get("type") for e in evr])
check("presence restored after restart",
      wait_for(lambda: get("/health")["online_counsellors"] == ["alpha@x.com"], 5))
# several addresses: the first is dead, the app moves on to the next and keeps it
qlist = queue.Queue()
clist = ws_client.WSClient([f"http://127.0.0.1:{free_port()}", BASE], tok_a, qlist)
clist.start()
evl = events(qlist, 10)
check("address list: unreachable first address -> connects via the next one and saves it",
      any(e.get("type") == ws_client.SERVER_MOVED and e.get("url") == BASE for e in evl)
      and ws_client.CONNECTED in [e.get("type") for e in evl], [e.get("type") for e in evl])
clist.stop()

# registration refused (wrong code) is reported as such, not as "cannot reach"
import enroll  # noqa: E402
client_config._app_dir = lambda: tempfile.mkdtemp()
msg = enroll.do_enroll(BASE, "alpha@x.com", "WRONG-CODE")
check("registration with a wrong code says so (not 'could not reach')",
      "invalid enrollment code" in msg and "Could not reach" not in msg, msg)

# server "moved": an app saved with a dead address finds the server by itself
dead = f"http://127.0.0.1:{free_port()}"
qmv = queue.Queue()
cmv = ws_client.WSClient(dead, tok_a, qmv, discovery_port=S.discovery_port)
cmv.start()
evm = events(qmv, 15)
check("app with an outdated server address finds the server and connects",
      any(e.get("type") == ws_client.SERVER_MOVED and e.get("url") == BASE for e in evm)
      and ws_client.CONNECTED in [e.get("type") for e in evm], [e.get("type") for e in evm])
cmv.stop()
ca.stop()
check("app closed -> offline promptly",
      wait_for(lambda: get("/health")["online_counsellors"] == [], 6))

# 1-hour offline alert loop, live (window = all day, "hour" shortened to 3 s)
from offline_monitor import OfflineMonitor  # noqa: E402
off_calls = []
mailer.send_offline_hour_alert = lambda info: off_calls.append(info) or True
background._MONITOR = OfflineMonitor(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                                     "00:00", "23:59", 0.05, store.meta_get, store.meta_set)
time.sleep(S.startup_grace_seconds + 0.5)
srv.call(background.offline_alert_step())
time.sleep(3.5)
check("live: all offline for the full period -> offline alert sent",
      srv.call(background.offline_alert_step()) == "sent" and len(off_calls) == 1)
check("live: alert carries presence, network, leads",
      off_calls and all(k in off_calls[0] for k in ("presence", "network", "leads", "offline_since")))
time.sleep(3.5)
check("live: still offline -> no second e-mail",
      srv.call(background.offline_alert_step()) == "" and len(off_calls) == 1)
qo = queue.Queue()
co = ws_client.WSClient(BASE, tok_a, qo)
co.start()
check("live: counsellor online again -> timer reset",
      wait_for(lambda: srv.call(background.offline_alert_step()) == "ended", 8))
co.stop()
wait_for(lambda: get("/health")["online_counsellors"] == [], 6)
srv.call(background.offline_alert_step())
time.sleep(3.5)
check("live: offline again for the full period -> NEW alert",
      srv.call(background.offline_alert_step()) == "sent" and len(off_calls) == 2)
check("health shows offline-alert status",
      "offline_alert" in get("/health") and get("/health")["offline_alert"]["enabled"] is True)

# network self-check says blocked -> alert wording is SERVER problem
netcheck.LAST.update(netcheck.evaluate(INCIDENT))
h = get("/health")
check("health degraded with firewall reason",
      h["status"] == "degraded" and any("CANNOT REACH" in w for w in h["warnings"]), h["warnings"])
time.sleep(S.startup_grace_seconds + 0.5)
post("/demo/inject", {"code": "CODE", "name": "Synthetic Lead 3", "mobile": "0000000002",
                      "form_type": "Web"})
mail_calls.clear()
check("blocked server -> alert still sent",
      srv.call(background.check_no_one_online()) is True and len(mail_calls) == 1)
check("...and it carries the firewall verdict (server problem, not counsellors)",
      mail_calls and mail_calls[0][1]["network"]["ok"] is False)
srv.stop()

# ── 4. client watchdog: server stops answering (half-open from the app side) ─
from websockets.sync.server import serve  # noqa: E402

conns = []


def mute_handler(sock):
    conns.append(time.time())
    sock.send(json.dumps({"type": "HELLO", "counsellor_name": "x"}))
    try:
        for _ in sock:          # read and ignore everything, never answer PING
            pass
    except Exception:
        pass


mport = free_port()
msrv = serve(mute_handler, "127.0.0.1", mport)
threading.Thread(target=msrv.serve_forever, daemon=True).start()
qm = queue.Queue()
cm = ws_client.WSClient(f"http://127.0.0.1:{mport}", "t", qm)
cm.start()
check("app detects a mute server and reconnects (heartbeat watchdog)",
      wait_for(lambda: len(conns) >= 2, 15), f"connections={len(conns)}")
cm.stop()
msrv.shutdown()

print()
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
print("ALL PRESENCE TESTS PASSED")
