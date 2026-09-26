import os
import tempfile

import pytest

from app.config import Settings, Counsellor
from app.fake_sheets import FakeGateway
from app.store import Store
from app.domain import build_record
from app import auth


@pytest.fixture
def tmp_settings(tmp_path):
    s = Settings()
    s.db_path = str(tmp_path / "store.db")
    s.session_secret = "test-secret-xyz"
    s.reconcile_seconds = 9999
    s.sync_tick_seconds = 0.05
    s.counsellors = [Counsellor(
        email="c1@intellibi.test", name="Cee One", counselling_by="Cee One",
        role="counsellor", password_hash=auth.hash_password("pw12345"), active=True)]
    return s


@pytest.fixture
def seeded_gateway():
    seed = [
        build_record({"Full Name": "Asha Rao", "Admission Status": "Interested",
                      "Candidate Type": "Fresher"}, "9876543210"),
        build_record({"Full Name": "Vikram Singh", "Admission Status": "In Progress",
                      "Candidate Type": "Experienced"}, "9812345678"),
    ]
    return FakeGateway(active=seed)


@pytest.fixture
def store(tmp_settings, seeded_gateway):
    st = Store(tmp_settings, seeded_gateway)
    st.bootstrap()
    yield st
    st.close()
