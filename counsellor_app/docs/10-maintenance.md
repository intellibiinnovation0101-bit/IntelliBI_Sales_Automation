# 10. Maintenance & Future Enhancements

## 10.1 Routine maintenance

| Task | How often | How |
|------|-----------|-----|
| Confirm health | daily / via monitor | `GET /health` → `status: ok`, `pending: 0`, `failed_cycles: 0`. |
| Review sync log | weekly | Look for repeated `sync failed` lines (indicates Sheets access issues). |
| Add / remove counsellors | as needed | `python -m app.manage_users add/list`; set `active: false` to disable. Restart after edits. |
| Rotate the session secret | occasionally / on staff change | `python -m app.manage_users secret` → update `config.yaml` → restart. (All users log in again.) |
| Update dependencies | quarterly | In the venv: `pip install -U -r requirements.txt`, then `python -m pytest -q`. |
| Verify backups | quarterly | Google Sheet version history + InActive tab are the record; confirm they look intact. |

The local `data/store.db` needs no maintenance — it's a cache/outbox rebuilt from
the sheet on startup. The journal self-prunes synced rows (keeps the last 500).

## 10.2 Applying updates safely

1. Note the running version's behaviour and confirm `/health` shows `pending: 0`.
2. Pull/copy the new code into the folder (keep `config.yaml`, `credentials/`,
   `data/` — they're git-ignored).
3. `pip install -r requirements.txt` (in case deps changed).
4. `python -m pytest -q` — must be green.
5. `python run.py --check` — confirms sheet connectivity.
6. Restart the service.

Because the sheet is the system of record, an update never risks the data: worst
case you roll back the code and restart.

## 10.3 If the production sheet schema changes

The schema lives in **one place**: `ACTIVE_COLUMNS` in `app/config.py`. If a
column is added/renamed/reordered in the sheet (and in `LeadSubmissionForm.gs`):

1. Update `ACTIVE_COLUMNS` to match the new header exactly (order matters).
2. If the new field is counsellor-editable, it automatically appears in the UI
   (add it to `SELECT_FIELDS` in `app/server.py` if it should be a dropdown, or
   to `DATE_FIELDS` in `config.py` if it's a date).
3. If it has a validation rule, add it to `validate_submission` in `app/domain.py`
   to keep parity with the form.
4. Run the tests and update expectations if needed.

Keeping this file in sync with the form is the single maintenance rule that
guarantees continued byte-compatibility.

## 10.4 Extending the system (it's built for this)

The architecture isolates every concern behind a small interface, so common
future requirements are additive, not rewrites:

- **Switch or add a storage backend (e.g. PostgreSQL).** Implement a new class
  with the same three methods as `SheetsGateway` (`load`, `apply_save`, `ping`)
  and pass it into `create_app`. Nothing in the UI, API, store logic, or auth
  changes. You could even run Sheets + a database in parallel by wrapping two
  gateways.
- **New API consumers (mobile app, dashboards).** The API is plain JSON on the
  same routes the UI uses; point any client at `/api/*`. Add API-key or token
  auth alongside the cookie session if needed.
- **Google Workspace SSO.** The hook exists (`auth.verify_google_token`); see
  `docs/04 §4.4` to turn it on.
- **Roles & admin screens.** Accounts already carry a `role`; add admin-only
  routes/pages gated on `role == "admin"`.
- **Bulk operations / imports.** Add a route that calls `store.save()` in a loop;
  the write-behind queue batches everything to the sheet safely.
- **Analytics / reporting inside the app.** Read from the in-memory index (or the
  SQLite cache) for instant dashboards without hitting Google's API.
- **Field-level audit / who-changed-what.** The InActive tab already versions
  every change; add the counsellor identity to the archived row if you want full
  attribution.
- **Search upgrades.** The in-memory search is linear and already sub-millisecond
  at thousands of leads; for tens of thousands, add an index (e.g. by name token)
  in `store.py` — again, a local change.

## 10.5 Design principles to preserve

If you or a future developer extend this, keep these invariants:

1. **Google Sheets stays the system of record.** SQLite is only a cache + outbox.
2. **The app is the single writer** to the Active tab. If another writer is ever
   added, shorten `reconcile_seconds` and treat the sheet as authoritative on
   conflict.
3. **Every sheet write goes through the gateway and `build_record`**, so rows
   stay byte-compatible with the form and downstream processing is never
   disrupted.
4. **Durability before acknowledgement.** Never tell a counsellor "Saved" before
   the write is committed to the journal.

## 10.6 Support checklist for a new maintainer

- Read `docs/01` (architecture) and this file.
- Run `python -m pytest -q` and `python run.py --fake` to see it work end-to-end
  with zero risk.
- Know the three files that matter most: `app/config.py` (schema/settings),
  `app/domain.py` (business rules), `app/store.py` (speed + durability).
- For any "does it still match the form?" question, diff the relevant rule in
  `app/domain.py` against `google_app_script/LeadSubmissionForm.gs`.
