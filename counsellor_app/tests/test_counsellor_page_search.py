"""
Browser test for the search UX: suggestions appear while typing (no Enter/Find),
update as the term changes, and the result list disappears the moment a lead is
opened. Runs the real FastAPI app (fake sheet) under uvicorn and drives it with
Playwright/Chromium. Skipped automatically when Playwright is not installed.
"""
import threading, time, socket
import pytest

pw = pytest.importorskip("playwright.sync_api")

from app.server import create_app
from app.fake_sheets import FakeGateway
from app.domain import build_record


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def live_server(tmp_settings):
    import uvicorn
    seed = [
        build_record({"Full Name": "vaibhav", "Admission Status": "Follow-up Pending",
                      "Candidate Type": "Career Break"}, "9579926410"),
        build_record({"Full Name": "tarun singh", "Admission Status": "Follow-up Pending",
                      "Candidate Type": "Career Break"}, "9922493332"),
        build_record({"Full Name": "Sanika Gaikwad", "Admission Status": "Follow-up Pending",
                      "Candidate Type": "Career Break", "Email Address": "sanika@example.com"},
                     "8999201952"),
    ]
    app = create_app(tmp_settings, gateway=FakeGateway(active=seed), start_worker=False)
    port = _free_port()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True); t.start()
    for _ in range(100):
        if server.started: break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True; t.join(timeout=5)


def test_live_suggestions_and_list_clears_on_open(live_server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(live_server)
        page.fill("#em", "c1@intellibi.test"); page.fill("#pw", "pw12345"); page.click("#go")
        page.wait_for_selector("#q")

        # 1) typing part of a mobile shows matches WITHOUT Enter / Find
        page.type("#q", "99")
        page.wait_for_selector("#hits button[data-m]")
        hits = page.locator("#hits button[data-m]")
        assert hits.count() == 3                       # all three seeded numbers contain "99"
        assert "9922493332" in page.inner_text("#hits") and "8999201952" in page.inner_text("#hits")

        # narrowing the term updates the list live
        page.type("#q", "22")                           # -> "9922"
        page.wait_for_function("document.querySelectorAll('#hits button[data-m]').length === 1")
        assert "tarun singh" in page.inner_text("#hits")

        # name / email fragments work the same way
        page.fill("#q", ""); page.type("#q", "sanika@")
        page.wait_for_function("document.querySelectorAll('#hits button[data-m]').length === 1")
        assert "Sanika Gaikwad" in page.inner_text("#hits")

        # below the minimum length nothing is suggested
        page.fill("#q", ""); page.type("#q", "v")
        page.wait_for_timeout(400)
        assert page.inner_text("#hits").strip() == ""

        # 2) Open a lead from the suggestions -> lead loads AND the list disappears
        page.fill("#q", ""); page.type("#q", "va")
        page.wait_for_selector("#hits button[data-m]")
        page.click("#hits button[data-m]")
        page.wait_for_selector("#panel #mobile")
        assert page.input_value("#panel #mobile") == "9579926410"
        assert page.inner_text("#hits").strip() == ""              # old results gone
        page.wait_for_timeout(400)                                 # no late reply re-populates it
        assert page.inner_text("#hits").strip() == ""

        # Enter with a full mobile still opens the record directly (unchanged behaviour)
        page.fill("#q", ""); page.type("#q", "9922493332"); page.press("#q", "Enter")
        page.wait_for_function("document.querySelector('#panel #mobile') && "
                               "document.querySelector('#panel #mobile').value === '9922493332'")
        assert page.inner_text("#hits").strip() == ""

        # Save still works from a lead opened via a suggestion
        page.fill("#q", ""); page.type("#q", "sanika")
        page.wait_for_selector("#hits button[data-m]"); page.click("#hits button[data-m]")
        page.wait_for_selector("#panel #save")
        page.fill("#panel [data-col='Counsellor Notes']", "opened from live search")
        page.click("#panel #save")
        page.wait_for_function("document.querySelector('#toast').classList.contains('ok')")
        b.close()
