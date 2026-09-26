"""Write-behind tests: journal drains to the sheet; failures retry without loss."""
import time

from app.fake_sheets import FakeGateway
from app.store import Store
from app.sync import SyncWorker
from app.sheets_gateway import SaveOp


def _drain(worker, store, timeout=3.0):
    t0 = time.time()
    while store.pending_count() > 0 and time.time() - t0 < timeout:
        worker._drain_once()
        time.sleep(0.02)


def test_writes_reach_the_sheet(tmp_settings, seeded_gateway):
    store = Store(tmp_settings, seeded_gateway)
    store.bootstrap()
    store.save({"Full Name": "Asha X", "Admission Status": "Admitted",
                "Candidate Type": "Fresher"}, "9876543210")
    worker = SyncWorker(tmp_settings, store)
    _drain(worker, store)

    assert store.pending_count() == 0
    # the fake "sheet" now has the update on the Active tab
    active, inactive = seeded_gateway.load()
    row = next(r for r in active if r["Mobile Number"] == "9876543210")
    assert row["Admission Status"] == "Admitted"
    # and the prior version archived to InActive
    assert any(r["Mobile Number"] == "9876543210" for r in inactive)
    store.close()


def test_byte_compatible_row_written(tmp_settings, seeded_gateway):
    """The row pushed to the sheet has exactly the production columns, in order."""
    from app.config import ACTIVE_COLUMNS
    store = Store(tmp_settings, seeded_gateway)
    store.bootstrap()
    store.save({"Full Name": "Col Check", "Admission Status": "Irrelevant"},
               "9700000009")
    worker = SyncWorker(tmp_settings, store)
    _drain(worker, store)
    header = seeded_gateway.raw_active_rows()[0]
    assert header == ACTIVE_COLUMNS
    store.close()


def test_transient_failure_then_recovery(tmp_settings):
    """If the sheet write fails, the write stays pending and syncs once healthy."""
    class FlakyGateway(FakeGateway):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.fail = True
        def apply_save(self, op: SaveOp):
            if self.fail:
                raise RuntimeError("Sheets API 503")
            return super().apply_save(op)

    gw = FlakyGateway()
    store = Store(tmp_settings, gw)
    store.bootstrap()
    store.save({"Full Name": "Retry Me", "Admission Status": "Irrelevant"},
               "9700000010")
    worker = SyncWorker(tmp_settings, store)

    # first attempts fail -> still pending, nothing lost
    try:
        worker._drain_once()
    except Exception:
        pass
    assert store.pending_count() == 1
    assert store.get("9700000010") is not None      # user still sees it

    # sheet recovers
    gw.fail = False
    _drain(worker, store)
    assert store.pending_count() == 0
    active, _ = gw.load()
    assert any(r["Mobile Number"] == "9700000010" for r in active)
    store.close()
