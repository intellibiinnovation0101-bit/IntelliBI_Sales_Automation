"""
Offline-boot fallback (app/store.py :: Store.bootstrap).

If Google Sheets is unreachable at start-up, the server must still come up from
the last local SQLite snapshot (so the counsellor URL stays available when the
office PC boots during an internet outage), flag itself as serving from cache,
and drop the flag once a reconcile() succeeds. With NO snapshot yet, start-up
must still fail loudly (nothing to serve).
"""
import os, tempfile
import pytest
from app.config import Settings
from app.store import Store
from app.fake_sheets import FakeGateway
from app.domain import build_record


class FlakyGateway(FakeGateway):
    """FakeGateway whose load() can be switched to fail (simulates no internet)."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fail_load = False
    def load(self):
        if self.fail_load:
            raise RuntimeError("Google Sheets unreachable (simulated)")
        return super().load()


def _settings(tmpdir):
    s = Settings()
    s.db_path = os.path.join(tmpdir, "store.db")
    return s


def test_boot_from_cache_when_google_unreachable_then_resync():
    with tempfile.TemporaryDirectory() as td:
        s = _settings(td)
        gw = FlakyGateway(active=[
            build_record({"Full Name": "Asha Rao"}, "9876543210"),
            build_record({"Full Name": "Ravi K"}, "9812345678"),
        ])
        # 1) normal boot -> snapshot persisted
        st = Store(s, gw); st.bootstrap()
        assert st.count() == 2 and not st.booted_from_cache
        st.close()

        # 2) reboot with Google DOWN -> must come up from the snapshot
        gw.fail_load = True
        st2 = Store(s, gw); st2.bootstrap()
        assert st2.count() == 2, "served from cache"
        assert st2.get("9876543210")["Full Name"] == "Asha Rao"
        assert st2.booted_from_cache is True
        assert st2._last_reconcile_ok is False      # degraded until resync

        # 3) internet returns -> reconcile succeeds and clears the flag
        gw.fail_load = False
        assert st2.reconcile() is True
        assert st2.booted_from_cache is False
        assert st2._last_reconcile_ok is True
        st2.close()


def test_first_ever_boot_with_no_snapshot_still_fails():
    with tempfile.TemporaryDirectory() as td:
        s = _settings(td)
        gw = FlakyGateway(active=[]); gw.fail_load = True
        st = Store(s, gw)
        with pytest.raises(RuntimeError):
            st.bootstrap()                            # nothing cached -> genuine failure
        st.close()
