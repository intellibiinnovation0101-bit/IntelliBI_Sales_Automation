"""
End-to-end service test (no Google, no GUI) using Starlette's TestClient:
  enroll two counsellor devices -> both connect via WebSocket -> a lead is
  injected -> BOTH receive NEW_LEAD -> counsellor A accepts -> A gets 'assigned',
  B receives 'ASSIGNED (by A)', and B's later accept attempt returns 'already'.

Run:  python lead_alert/tests/test_app_integration.py
"""
import json
import sys
import tempfile
from pathlib import Path

_SVC = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(_SVC))

import config  # noqa: E402

# isolate DB + config BEFORE importing store/app
config.DB_PATH = Path(tempfile.mkdtemp()) / "it.db"

cj = Path(tempfile.mkdtemp()) / "counsellors.json"
cj.write_text(json.dumps({"counsellors": [
    {"counsellor_name": "Alpha", "emailid": "alpha@x.com", "current_status": "Active"},
    {"counsellor_name": "Bravo", "emailid": "bravo@x.com", "current_status": "Active"},
]}), encoding="utf-8")
config.SETTINGS.counsellors_json = str(cj)
config.SETTINGS.alert_sections = ["counsellors"]
config.SETTINGS.enabled = False          # don't start the Google poller in the test
config.SETTINGS.log_sheet_id = ""        # disable sheet mirror
config.SETTINGS.enrollment_code = lambda: "CODE"   # patch the shared code

import app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

fails = []


def check(name, cond):
    print(("  PASS" if cond else "  FAIL"), name)
    if not cond:
        fails.append(name)


def drain_until(ws, wanted, tries=6):
    """Read messages until one of type `wanted` arrives (skipping HELLO etc.)."""
    for _ in range(tries):
        m = ws.receive_json()
        if m.get("type") == wanted:
            return m
    return None


with TestClient(app.app) as client:
    a = client.post("/enroll", json={"email": "alpha@x.com", "code": "CODE",
                                     "machine": "PC-A"}).json()
    b = client.post("/enroll", json={"email": "bravo@x.com", "code": "CODE",
                                     "machine": "PC-B"}).json()
    check("A enrolled", bool(a.get("token")))
    check("B enrolled", bool(b.get("token")))

    bad = client.post("/enroll", json={"email": "alpha@x.com", "code": "WRONG",
                                       "machine": "PC-A"})
    check("wrong code rejected", bad.status_code == 403)
    notc = client.post("/enroll", json={"email": "nobody@x.com", "code": "CODE",
                                        "machine": "PC-X"})
    check("non-counsellor rejected", notc.status_code == 403)

    with client.websocket_connect(f"/ws?token={a['token']}") as wsa, \
         client.websocket_connect(f"/ws?token={b['token']}") as wsb:
        # both should greet
        check("A HELLO", drain_until(wsa, "HELLO") is not None)
        check("B HELLO", drain_until(wsb, "HELLO") is not None)

        inj = client.post("/demo/inject", json={"code": "CODE", "name": "Lead1",
                                                "mobile": "9", "form_type": "Web"}).json()
        lid = inj["injected"]

        na = drain_until(wsa, "NEW_LEAD")
        nb = drain_until(wsb, "NEW_LEAD")
        check("A got NEW_LEAD", na and na["lead"]["lead_id"] == lid)
        check("B got NEW_LEAD", nb and nb["lead"]["lead_id"] == lid)

        # A accepts
        wsa.send_json({"type": "ACCEPT", "lead_id": lid})
        ra = drain_until(wsa, "ACCEPT_RESULT")
        check("A accept assigned", ra and ra["result"] == "assigned")

        # B should be told it's assigned to Alpha
        asg = drain_until(wsb, "ASSIGNED")
        check("B got ASSIGNED", asg and asg["assigned_to"] == "alpha@x.com")
        check("ASSIGNED names winner", asg and asg["assigned_name"] == "Alpha")

        # B tries to accept the same lead -> already
        wsb.send_json({"type": "ACCEPT", "lead_id": lid})
        rb = drain_until(wsb, "ACCEPT_RESULT")
        check("B accept -> already", rb and rb["result"] == "already")
        check("already names winner", rb and rb["assigned_name"] == "Alpha")

    h = client.get("/health").json()
    check("health ok", h.get("status") == "ok")

print()
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
print("ALL INTEGRATION TESTS PASSED")
