# 8. Testing & Validation

The system ships with an automated test suite and a set of manual checks. All
automated tests run **offline** against the in-memory `FakeGateway`, so they need
no credentials and never touch the real sheet.

## 8.1 Run the automated tests

```bash
cd counsellor_app
python -m pytest -q
```

Expected: **all tests pass** (23 at time of writing). What they cover:

| Test file | What it validates |
|-----------|-------------------|
| `validation/verify_business_rules.py` | Mobile normalisation (all `+91`/`0` variants), Indian-mobile validation, `build_record` produces the full 28-column schema with normalised mobile + stamped timestamp, date canonicalisation (`2026-10-05 → 05-Oct-2026`), and the exact validation rules from the form (candidate-type requirement, Google-Meet/Walk-In schedule-date rules). |
| `validation/verify_lead_store.py` | Instant in-memory reads, search by mobile/name, versioned saves that archive the prior version to history, validation blocking bad data, new-lead insert, **durability across a simulated restart** (an un-synced write survives), and **reconcile preserving un-synced writes**. |
| `validation/verify_sheet_sync_worker.py` | The write-behind worker actually pushes updates to the (fake) sheet, the row written has **exactly the production columns in order**, the prior version is archived to InActive, and a **transient Sheets failure is retried without data loss**. |
| `validation/verify_web_api.py` | Full HTTP flow via FastAPI's TestClient: auth required, bad login rejected, `/health` open, login → read lead → save → history, date canonicalisation end-to-end, `Counselling By` defaulted from the logged-in user, and validation errors returning HTTP 400. |
| `validation/verify_counsellor_page_search.py` | Browser test (Playwright/Chromium against the real app on a fake sheet): matching leads appear while typing in the search box without Enter/Find, the list narrows as the term changes, it is cleared the moment a lead is opened, Enter with a full mobile still opens the record directly, and Save works from a lead opened via a suggestion. Skipped automatically when Playwright is not installed. |

## 8.2 Performance validation

Reads are served from an in-memory index and saves from a local journal, so the
data layer is microsecond-scale. Reference numbers measured on a laptop-class
machine with **8,000 leads**:

| Operation | Result |
|-----------|--------|
| Bootstrap (load 8,000 leads into memory) | ~200 ms (once, at startup) |
| Read a lead (in-process) | ~2 µs average, ~4 µs p99 |
| Save a lead (durable, in-process) | ~0.1–1 ms |
| Search across 8,000 leads | < 1 ms |
| Read over HTTP (localhost) | ~3 ms |
| Save over HTTP (localhost, instant ack) | ~6 ms |

You can reproduce a scaled benchmark yourself:
```bash
python - <<'PY'
import time, random, statistics, os
from app.config import Settings
from app.fake_sheets import FakeGateway
from app.store import Store
from app.domain import build_record
seed=[build_record({"Full Name":f"Lead {i}","Admission Status":"Interested",
      "Candidate Type":"Fresher"}, str(random.randint(6,9))+
      "".join(random.choice("0123456789") for _ in range(9))) for i in range(8000)]
s=Settings(); s.db_path="/tmp/bench.db"; os.system("rm -f /tmp/bench.db*")
st=Store(s, FakeGateway(active=seed)); 
t=time.time(); st.bootstrap(); print("bootstrap ms:", round((time.time()-t)*1000))
ms=[r["Mobile Number"] for r in seed]
ts=[(lambda a=time.perf_counter(): (st.get(random.choice(ms)), (time.perf_counter()-a)*1e6)[1])() for _ in range(20000)]
print("read avg us:", round(statistics.mean(ts),2))
st.close()
PY
```

## 8.3 End-to-end validation against the real sheet (staging check)

Do this once before cutover, ideally with a **test lead** so you don't disturb
real data:

1. `python run.py` and log in.
2. Search a known test mobile; confirm the current details match the sheet.
3. Edit a field (e.g. *Counsellor Notes*) and Save. Confirm "Saved ✓".
4. In Google Sheets, confirm within a few seconds:
   - the **Active** row for that mobile shows your change and a fresh
     `RecordTimeStamp`;
   - a new row appears on the **InActive** tab with the *previous* values, a
     `RecordVersion`, and an `ArchivedAt`.
5. Run the existing `pyConsolidateLeadsLoad.py` (as you normally would) and
   confirm the lead flows into the Consolidated Master exactly as a
   form-submitted lead does, and that the Follow-Up report still runs.
6. Check `/health` shows `pending: 0` and `failed_cycles: 0`.

If all six pass, the app is producing sheet data indistinguishable from the form
and the downstream pipeline is unaffected.

## 8.4 Data-integrity checks the code enforces

- **Mobile column integrity.** Only editable fields are accepted from the
  browser; the mobile key is set server-side from the normalised number, so a
  remark or stray value can never land in the Mobile column.
- **Full schema every write.** `build_record` always emits all 28 columns in
  order, so a save can't shift or drop columns.
- **No lost history.** Every update archives the prior version before overwriting
  the Active row.
- **No lost writes.** Saves are journaled to disk before acknowledgement and
  replayed after any restart.

## 8.5 What to do if a test fails

Re-run with more detail:
```bash
python -m pytest -vv
```
A failure in `verify_business_rules` usually means a business-rule expectation changed —
compare against `LeadSubmissionForm.gs`. A failure in `verify_lead_store`/`verify_sheet_sync_worker`
points at the durability/sync path. See `docs/09-troubleshooting.md`.
