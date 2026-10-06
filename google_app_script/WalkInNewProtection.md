# Walk-In workbook protection (`WalkInNewProtection.gs`)

Sheet: Student Inquiry Tracker (`19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ`).
The rules are real Google Sheets protections, applied by script and matched to columns by header name.

## Rules

| Tab / columns | Counsellors & regular editors | Owner, `WIP_FULL_CONTROL`, automation |
|---|---|---|
| **Walk-In New**: Remarks, Lead Status, Admission Status, Counselling By, Tech Counselling By, ScheduledOrDirectWalkIn, Next Follow-Up Date, BackOutReason (row 2 down) | Edit | Edit |
| **Walk-In New**: header row, the 22 form columns, Lead Interaction History, Conversion Chance %, any other column | View only | Edit |
| **Every other tab**, including any tab added later (the daily run picks it up) | View only: no editing, clearing, inserting or deleting rows/columns, renaming or deleting the tab | Edit |

The following are unaffected:

- Google Form submissions are never blocked by protection.
- `WalkInNewAutoPopulate.gs` triggers run as the account that installed them. That account is in `WIP_FULL_CONTROL`, so history and score updates continue.
- Formulas, pivots, dropdowns, data validation and formatting keep working, because protection blocks only manual edits.
- Python reads only from this workbook, so it is unaffected.

## Setup (once, as the spreadsheet owner)

1. Open the Apps Script project that holds `WalkInNewAutoPopulate.gs` and add a new file `WalkInNewProtection.gs` with this code. Leave the existing files unchanged.
2. Check `WIP_FULL_CONTROL`. It must include every admin and the account that installed the `onWalkInEdit` / `onWalkInFormSubmit` / `onWalkInDailySync` triggers (Apps Script → Triggers → "Owned by").
3. Run `auditWalkInWorkbook()`. It is read-only and lists the tabs, the form link, existing protections and the header mapping. Fix anything shown as **MISSING** first.
4. If any other tab is filled by an integration account (Meta Lead, Website, Bot Reply, …), add it per tab:
   `WIP_TAB_EXTRA_EDITORS = { 'Bot Reply': ['integration@…'] };`
5. Run `applyWorkbookProtection()`. It applies the rules, verifies them, and logs what changed, including editors removed from earlier protections.
6. Run `setupWorkbookProtectionTriggers()`. It installs a daily re-apply (about 5 AM, before the 6 AM `onWalkInDailySync`) and a form-submit coverage check.

`verifyWorkbookProtection()` is a read-only check you can run at any time.

## Behaviour notes

- **Header-based:** columns are found by header text (trimmed, spaces collapsed, case-insensitive). If a counsellor column is moved, the next run follows it. If a counsellor header is missing, duplicated or renamed, nothing changes, and the run fails and e-mails the owner.
- **New rows:** the editable range runs to the bottom of the sheet, and the script keeps at least 300 blank rows (`WIP_ROW_BUFFER`). If the form ever gets within 50 rows of the end, the form-submit hook re-applies straight away.
- **Re-runs:** every run is idempotent. It reuses its own protection, and adopts any older tab protection instead of duplicating it.
- **Existing range protections** are left in place and reported. A header-row lock from `ProtectHeaderRow.gs` is compatible (row 1 is locked by this script anyway). If one covers a counsellor column, counsellors stay blocked there until you remove it.
- **Filtering and sorting:** counsellors can't change the shared filter or sort on protected tabs. They can use **Data → Filter views → Create new filter view**, which is personal.
- **Workbook-level controls:** counsellors still have edit access to the file, so they can add a new tab, which is protected on the next daily run. To stop them re-sharing the file, turn off *Share → ⚙ → "Editors can change permissions and share"*.

## Manual test (with a counsellor account)

| Test | Expected |
|---|---|
| Edit Remarks / Lead Status on a lead row | Allowed |
| Edit Full Name, Mobile, Timestamp, Lead Interaction History, Conversion Chance %, or the header row | Blocked |
| Insert or delete a row in Walk-In New | Blocked |
| Edit any cell on any other tab, or rename/delete a tab | Blocked |
| Submit a test form entry | Row appears; history and score fill in; counsellor can edit its Remarks |
| Change Lead Status as the counsellor | History and score recalculate (trigger still writes) |

## Tests

`test_walkin_protection.js` (Node, mocked SpreadsheetApp, synthetic data only): `node test_walkin_protection.js`.
