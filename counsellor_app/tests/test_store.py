"""Store tests: instant reads, versioned writes, durability, reconcile."""
from app.config import Settings, Counsellor
from app.fake_sheets import FakeGateway
from app.store import Store
from app.domain import build_record
from app import auth


def test_reads_from_memory(store):
    rec = store.get("+91 98765 43210")     # any format resolves to the key
    assert rec and rec["Full Name"] == "Asha Rao"
    assert store.count() == 2
    assert store.get("9000000000") is None


def test_search(store):
    assert store.search("9876")[0]["Mobile Number"] == "9876543210"
    assert store.search("vikram")[0]["Full Name"] == "Vikram Singh"


def test_save_creates_version_and_history(store):
    ok, msg, rec = store.save(
        {"Full Name": "Asha R", "Admission Status": "Admitted",
         "Candidate Type": "Fresher"}, "9876543210", counselling_by="Cee")
    assert ok, msg
    assert store.get("9876543210")["Admission Status"] == "Admitted"
    hist = store.history("9876543210")
    assert len(hist) == 1 and hist[0]["Admission Status"] == "Interested"
    assert hist[0]["RecordVersion"] == "1"


def test_save_validation_blocks_bad_data(store):
    ok, msg, rec = store.save({"Admission Status": "Interested"},  # no candidate type
                              "9876543210")
    assert not ok and "Candidate Type" in msg


def test_new_lead_insert(store):
    ok, _, _ = store.save({"Full Name": "New Person", "Admission Status": "Irrelevant"},
                          "9700000001")
    assert ok
    assert store.count() == 3
    assert store.get("9700000001")["Full Name"] == "New Person"


def test_durability_across_restart(tmp_settings):
    """A write survives a process restart even before it syncs to the sheet."""
    gw = FakeGateway()
    st = Store(tmp_settings, gw)
    st.bootstrap()
    st.save({"Full Name": "Durable", "Admission Status": "Irrelevant"}, "9700000002")
    assert st.pending_count() == 1
    st.close()

    # brand-new Store, SAME db, gateway still empty (never synced)
    gw2 = FakeGateway()
    st2 = Store(tmp_settings, gw2)
    st2.bootstrap()
    assert st2.get("9700000002")["Full Name"] == "Durable"   # replayed from journal
    assert st2.pending_count() == 1                          # still needs syncing
    st2.close()


def test_reconcile_preserves_unsynced_writes(store, seeded_gateway):
    store.save({"Full Name": "Local Only", "Admission Status": "Irrelevant"},
               "9700000003")
    assert store.pending_count() == 1
    store.reconcile()                       # re-reads sheet (doesn't have it yet)
    assert store.get("9700000003") is not None   # still visible after reconcile
