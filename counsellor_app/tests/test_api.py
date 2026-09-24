"""End-to-end API tests via FastAPI TestClient (auth, read, save, history)."""
import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from app.fake_sheets import FakeGateway
from app.domain import build_record


@pytest.fixture
def client(tmp_settings):
    seed = [build_record({"Full Name": "Asha Rao", "Admission Status": "Interested",
                          "Candidate Type": "Fresher"}, "9876543210")]
    gw = FakeGateway(active=seed)
    app = create_app(settings=tmp_settings, gateway=gw, start_worker=False)
    app.state._gw = gw
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/api/login", json={"email": "c1@intellibi.test", "password": "pw12345"})
    assert r.status_code == 200 and r.json()["ok"]


def test_requires_auth(client):
    assert client.get("/api/lead", params={"mobile": "9876543210"}).status_code == 401


def test_bad_login(client):
    r = client.post("/api/login", json={"email": "c1@intellibi.test", "password": "wrong"})
    assert r.status_code == 401 and not r.json()["ok"]


def test_health_is_open(client):
    j = client.get("/health").json()
    assert j["status"] == "ok" and j["leads_cached"] == 1


def test_lead_read_and_save_flow(client):
    login(client)
    j = client.get("/api/lead", params={"mobile": "+91 98765 43210"}).json()
    assert j["found"] and j["record"]["Full Name"] == "Asha Rao"

    r = client.post("/api/save", json={"mobile": "9876543210",
        "fields": {"Full Name": "Asha Rao", "Admission Status": "Admitted",
                   "Candidate Type": "Fresher",
                   "Next Follow-Up Date": "2026-10-01"}})
    assert r.status_code == 200 and r.json()["ok"]

    j2 = client.get("/api/lead", params={"mobile": "9876543210"}).json()
    assert j2["record"]["Admission Status"] == "Admitted"
    assert j2["record"]["Next Follow-Up Date"] == "01-Oct-2026"   # canonicalised
    assert len(j2["history"]) == 1                                # prior archived
    # counselling_by defaulted from the logged-in user
    assert j2["record"]["Counselling By"] == "Cee One"


def test_save_validation_error_returns_400(client):
    login(client)
    r = client.post("/api/save", json={"mobile": "9876543210",
        "fields": {"Full Name": "X", "Admission Status": "Interested"}})  # no cand type
    assert r.status_code == 400 and not r.json()["ok"]


def test_search_endpoint(client):
    login(client)
    j = client.get("/api/search", params={"q": "asha"}).json()
    assert j["results"] and j["results"][0]["Full Name"] == "Asha Rao"
