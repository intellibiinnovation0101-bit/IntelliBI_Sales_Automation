# google_app_script/ — Apps Script files used by the Sales workflow

Paste each file into the Apps Script project of the Google Sheet it belongs to
(Extensions ▸ Apps Script). They are kept here so the deployed code is versioned.

| File | Lives in | Purpose |
|---|---|---|
| `LeadSubmissionForm.gs` | **IntelliBI Lead Information** (the counsellor form, `SHEET_ID`) | The form UI + Validate / Save / Search / Reset logic. Writes to the **IntelliBI Lead Information Result** data store (`DATA_ID`, tabs `…Active` / `…InActive`). |
| `ProtectCounsellorForm.gs` | same project as above | Locks the form's *label* cells so counsellors cannot rename/move fields. |
| `ProtectLeadResultSheet.gs` | same project as above | Locks the **Result** data store so counsellors can view it but not edit it by hand (see below). |
| `ProtectHeaderRow.gs` | any sheet whose header row must not change | Locks row 1 on chosen tabs (reports look columns up by name). |
| `WebsiteFormWebhook.gs`, `WebsiteNewAutoPopulate.gs`, `WalkInNewAutoPopulate.gs` | website / walk-in lead sheets | Intake automation for website and walk-in leads. |
| `WalkInNewProtection.gs` | **Student Inquiry Tracker** (Walk-In workbook), same project as `WalkInNewAutoPopulate.gs` | Walk-In New: counsellors edit only the 8 counsellor columns (found by header name); every other tab read-only. Setup, rules and test checklist: `WalkInNewProtection.md`; offline tests: `node test_walkin_protection.js`. |

## Result data store — who may write, and how it is locked

Requirement: `IntelliBI Lead Information Result` is updated **only** through
`IntelliBI Lead Information` form → `LeadSubmissionForm.gs` → Result. Counsellors may
view it but must not edit, delete or overwrite its data by hand.

How the data actually gets written today (nothing here changes it):

* **Save / Search / Reset checkboxes** on the form fire the *installable* trigger
  `onLeadFormCheckbox` (installed by the menu item "📅 Set up Save box + date
  pickers"). An installable trigger runs **as the account that installed it**, not
  as the counsellor who ticked the box. `runSubmit()` → `upsertRecord_()` /
  `archiveToInactive_()` therefore write to the Result file under that account.
* **Menu "✅ Validate Mobile Number"** runs as the counsellor but only *reads* the
  Result file (`runValidate()` → `findRecord_()`); a viewer can do that.
* **Counsellor Server** (`counsellor_app`, `http://<office-pc>:8600`) reads and
  writes through the service account
  `intellibi-data-pipeline@intellibi-mis.iam.gserviceaccount.com`.
* Nothing in the workflow needs a counsellor account to be an *editor* of the
  Result file.

Lock = two layers:

1. **Sheet protection** (`ProtectLeadResultSheet.gs`, run `lockLeadResultSheet()`
   from the Apps Script editor **as the file owner**). Every data tab gets a
   hard, sheet-level protection whose editors are only the owner +
   `LR_ALLOWED_EDITORS` (admin account, service account). Every other editor of
   the file is removed from the protection and can no longer change those tabs.
   `verifyLeadResultLock()` prints who can still write and whether the
   Save-trigger owner and the service account are covered;
   `unlockLeadResultSheet()` removes only these locks. Re-running is safe; other
   protections (e.g. header locks) are never touched.
2. **Drive sharing (manual, recommended)**: on the Result file, Share ▸ change each
   counsellor account (`salesintellibi*@gmail.com`) from *Editor* to **Viewer**. A
   viewer cannot add/delete tabs or import over the file, so the protection only
   has to guard the admin accounts that keep edit rights. Keep at least Viewer —
   the menu Validate opens the Result file as the counsellor.

Before locking, make sure the account that owns the Save trigger is in
`LR_ALLOWED_EDITORS` (simplest: run "📅 Set up Save box + date pickers" once from
the owner account, which re-creates the trigger under the owner), then run
`lockLeadResultSheet()` and test one Search + one Save from a counsellor login.
