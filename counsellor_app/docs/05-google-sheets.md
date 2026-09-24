# 5. Google Sheets / API Configuration

The app reads and writes the existing Data sheet through a **Google service
account** (a robot account), using the `gspread` library. This section sets that
up and explains exactly what the app writes.

## 5.1 The target sheet

| Item | Value |
|------|-------|
| Spreadsheet ID | `1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw` |
| Active tab | `IntelliBI Lead Information Active` (alias also accepted: `… Result`) |
| InActive tab | `IntelliBI Lead Information InActive` (auto-created if absent) |

This is the same sheet the existing Google Form / `LeadSubmissionForm.gs` writes
to, and the same one `pyConsolidateLeadsLoad.py` reads as its top-priority
source.

## 5.2 Create a service account and key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select (or create) a project — you can reuse the project the existing
   automation already uses.
3. **APIs & Services → Enable APIs** → enable **Google Sheets API** (and
   **Google Drive API**, which gspread uses to open sheets by key).
4. **APIs & Services → Credentials → Create Credentials → Service account.**
   Give it a name like `counsellor-app`. No special roles are required.
5. Open the new service account → **Keys → Add key → Create new key → JSON**.
   A JSON file downloads. This is the key.
6. Save it as:
   ```
   counsellor_app/credentials/service_account.json
   ```
7. Open the JSON and copy the `client_email` value (looks like
   `counsellor-app@yourproject.iam.gserviceaccount.com`).

> If your organisation already has a service account used by the existing Python
> automation, you can reuse its JSON key instead of creating a new one — just
> make sure it has Editor access to the sheet (next step).

## 5.3 Share the sheet with the service account

1. Open the Data sheet in Google Sheets.
2. **Share** → paste the service account's `client_email` → set **Editor** →
   send. (Uncheck "notify" — it's a robot.)

The app needs **Editor** because it writes updates (Active tab) and archives
prior versions (InActive tab). It is the intended single writer.

## 5.4 What the app writes (byte-compatibility guarantee)

The app writes rows that are **identical in shape** to what the form writes, so
downstream processing is unaffected:

- **Active tab** — one row per lead, in this exact 27-column order:

  `RecordTimeStamp, Mobile Number, Full Name, Email Address, Candidate Type,
  Total Years of Experience, Current Domain / Technology, IsGoogleMeetSchedule,
  Course Interested In, IsGoogleMeetScheduleDate, Career Goal, IsWalkInSchedule,
  Current Company Name, IsWalkInScheduleDate, Current City, Admission Plan Time,
  Current Area / Locality, Next Follow-Up Date, Highest Qualification,
  Counsellor Notes, Graduation / Passing Year, Counselling By, Is Referral,
  Admission Status, Referrer's Name, BackOutReason, Follow-Up Type`

- **InActive tab** — the same 27 columns, prefixed with two audit columns:
  `RecordVersion, ArchivedAt`. Each time a lead is updated, its **previous**
  version is appended here, so the full interaction history is preserved.

Normalisation the app applies (matching the form exactly):
- **Mobile** is reduced to bare 10 digits (strips `+91` / `0`); used as the key.
- **Timestamp** (`RecordTimeStamp`) is `dd-MMM-yyyy HH:mm:ss` in IST
  (Asia/Kolkata), e.g. `05-Oct-2026 14:23:08`.
- **Date fields** (`Next Follow-Up Date`, `IsGoogleMeetScheduleDate`,
  `IsWalkInScheduleDate`) are stored as unambiguous `dd-MMM-yyyy`, e.g.
  `05-Oct-2026`, regardless of how the counsellor typed/picked them.

Because the schema, normalisation, timestamp and versioning match the form, the
consolidation and reports cannot tell whether a row came from the form or the
app.

## 5.5 Upsert semantics (how a save maps to the sheet)

For each save the single-writer gateway does exactly two things:
1. If the lead already existed, **append its prior version** to the InActive tab
   with the next `RecordVersion` and an `ArchivedAt` timestamp.
2. **Find the lead's row on the Active tab by mobile and overwrite it** (or
   append a new row if the mobile is new).

This mirrors the form's own "archive then update" behaviour.

## 5.6 Quotas & performance

Google Sheets API allows ~60 write requests/minute per user. Because the app
serves reads from memory and **batches** writes in the background (default up to
50 per cycle, one cycle every ~2 s), normal counsellor activity stays well under
quota. If you ever push a very large burst, the write-behind queue simply drains
over a few extra seconds — counsellors are never blocked, since their saves were
already acknowledged locally.

## 5.7 Verifying access

With the key in place and the sheet shared, run:
```bash
python run.py --check
```
Expected: `OK — bootstrapped N leads; pending writes: 0`, where N is the number
of rows on the Active tab. If you get an auth or permission error, see
`docs/09-troubleshooting.md §Google/API`.
