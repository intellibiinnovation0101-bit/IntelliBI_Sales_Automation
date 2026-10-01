# Google Ads Campaign Remarketing — `pyGoogleAdsRemarketingAudience.py`

Keeps the Google Ads remarketing audience current. Each run selects every **relevant, not "Not Interested", not-enrolled lead who enquired in the last `NUMBER_OF_DAYS` days and has a usable mobile number**. It then rewrites two Google Sheets from that one dataset, so the two always hold the same leads in the same order.

| Output | Where | Content |
|---|---|---|
| **Phone Number Audience** (production, used by Google Ads) | existing sheet "Retargeting IntelliBi" `150HujTNz3rsSr2dZMIrs_Cdp3fsZPgJB-p3RoJVixSU`, tab `Sheet1` (gid 0) | **A** `Mobile` (header kept as is): one number per row, `91` + 10-digit mobile (e.g. `919876543210`), stored as a **number** with format `0`, exactly as before. **B** `Email`: the lead's email from the master's `Email Address` (checked with the consolidation's `clean_email`), **blank when unknown**. A missing email never removes a lead. |
| **Full Details** (internal) | one persistent sheet "Google Ads Campaign Remarketing Leads Full Details" in the "Manish Leads" folder `1cjhEZWbSGzNoGog33h7VnfI8K5PawMOj`, created on the first run and reused afterwards | Tab **Remarketing Audience**: title, run summary, then First Enquiry, Latest Enquiry, Full Name, Mobile Number, **Email**, Platforms Used, Interactions, Relevant, Is Referral, Course Interested, Notes / Remarks, Admission Status, Backout Reason, Counselling By, Google Meet Sch., Walk-in Sch., Lead Journey (Enquiry → Latest), plus **Fresh / Repeat** and **Google Ads Phone** for reconciliation. Tab **Refresh History**: one line per run with the window, counts, added / removed and result. |

## Who is in the audience
Everything below is reused from the existing Sales code; nothing is re-implemented.

| Step | Rule | Reused from |
|---|---|---|
| Source | Consolidated master lead sheet | `pyConsolidatedLeadPerformanceReport.read_master_df` |
| Invalid phone ⇒ irrelevant | `IsPhoneNumberValid = No` ⇒ `IsLeadRelevant = No` | `common/lead_rules.apply_invalid_phone_irrelevance` |
| Window | at least one enquiry in **exactly `NUMBER_OF_DAYS` calendar days ending today** (IST), from the first day's 00:00 to today 23:59. 01-Oct with 30 days → 02-Sep … 01-Oct. | `day_bounds` + `prepare_active` (the engine of the report's Fresh / Repeat Lead Details) |
| Relevant | `IsLeadRelevant = Yes` **and** connected (a Website/WhatsApp lead with `IsWhatsAppWebConnect = No` counts as irrelevant) | `is_relevant_lead` |
| Not "Not Interested" | Admission Status or Lead Status is not "Not Interested" (`EXCLUDE_NOT_INTERESTED`) | `pyLeadFollowUpAnalysisReport.is_followup_excluded_status` |
| Not enrolled | phone on **neither** enrolled list: the Follow-Up report's ("IntelliBI — Student Admission Responses", New Enroll tab) and the Performance report's (Student Admission Responses). Admission Status is also not "Admission Confirmed" (`EXCLUDE_ADMISSION_CONFIRMED`). | `pyLeadFollowUpAnalysisReport.load_enrolled_phones` + `pyConsolidatedLeadPerformanceReport.load_enrolled_mobiles` / `is_converted_status` |
| Valid mobile | the consolidation's own rule: 10 digits starting 6–9 after removing +91 / 0 / spaces | `pyConsolidateLeadsLoad.norm_phone` / `is_valid_mobile` |
| One row per number | the same number twice → kept once, the most recent enquiry | — |
| Details | Lead Journey, Platforms Used, Interactions (= enquiries within the window), as in the report's lead-detail tabs | `format_journey`, `platforms_in_sequence`, `_ninper` |

Checked on the 30-Sep master export: in the same window, the counts of leads and of relevant leads are identical to the Lead Performance report's.

## Production safety
1. Everything is loaded, filtered, normalised, de-duplicated, validated and reconciled **before anything is written**.
2. Each sheet is rewritten with **one Sheets `batchUpdate`**. Google applies all of it or none of it, so the audience is never empty or half-written, even if the network drops mid-update.
3. The run **refuses to publish**, leaving the last good audience in place, when any of these happens:
   - the master or either enrolled list cannot be read (an empty enrolled list is treated as unreadable);
   - the audience would be empty (`MIN_AUDIENCE_SIZE`);
   - it would shrink by more than `MAX_AUDIENCE_DROP_PCT` (60%);
   - the production sheet's structure changed: A1 isn't `Mobile`, B1 isn't `Email` (or blank before the first run that adds it), or there is data outside columns A–B.
4. Order: Full Details first, then the production audience. If Full Details fails, production is not touched.
5. Both sheets are read back after writing and compared with the dataset.
6. Exit codes: `0` refreshed; `3` nothing changed and safe to re-run (source or Google problem; the Layer 3 runner re-runs it like the reports); `1` refused or failed (see the log).

## Run
```
python google_ads_campaign_remarketing\pyGoogleAdsRemarketingAudience.py --dry-run   # read live, print, write nothing
python google_ads_campaign_remarketing\pyGoogleAdsRemarketingAudience.py             # refresh both sheets
```
**Scheduled** as the last step of Sales Layer 3 (`scripts/run_layer3.py`), after the two reports, so it uses the master the same run has just consolidated.

- **When:** on every run of the Windows task "IntelliBI Sales Automation" (`scripts/setup_schedule.ps1`): **11:00, 14:00, 17:00, 18:45, 21:00 and 23:00** daily, local time of the production PC. The task calls `run_scheduled.py`, which runs `run_all.py`: Layer 1 → Layer 2 → Layer 3.
- **Not refreshed on a run when:**
  - Layer 2 (consolidation) failed, because Layer 3 is skipped (`pipeline.stop_on_failure`);
  - the previous run is still in progress, because the trigger is skipped (overlap lock).

  In both cases the last audience stays as it is. A trigger missed while the PC was off runs once when it is back (`StartWhenAvailable`).
- **Failure handling:** it uses the existing logging (`logs/pyGoogleAdsRemarketingAudience.log`), the runner's automatic re-runs on exit 3 (up to 2, 5 minutes apart) and the completion e-mail (KPIs: Audience, Added, Removed, Google Ads sheet updated). It runs after both reports and its failure never stops them; the run is reported as PARTIAL.

Settings are at the top of the script: `NUMBER_OF_DAYS` (30), sheet / folder ids, `EXCLUDE_NOT_INTERESTED`, `EXCLUDE_ADMISSION_CONFIRMED`, `REQUIRE_ENROLLED_LIST`, `MIN_AUDIENCE_SIZE`, `MAX_AUDIENCE_DROP_PCT`. Pin `FULL_DETAILS_SHEET_ID` if the Full Details sheet is ever renamed.

## Access
The service account `intellibi-data-pipeline@…` and `info@` are editors on the production sheet and on the "Manish Leads" folder. Writes act as `info@`, through the same delegated credentials the reports use for Drive. Keep these shares; removing them stops the refresh, but the last audience stays as it was.

## Verification
`python sales_validation\verify_google_ads_remarketing.py` runs offline against an in-memory Google Sheets/Drive that applies a batch update all-or-nothing. It covers:
- windows of 30, 7, 1 and 60 days (each exactly that many days), the window edges, and 0 / negative values rejected;
- every eligibility rule (including Not Interested by Admission Status and by Lead Status, and both enrolled lists);
- duplicates, the `91` format, the production structure and number format;
- the same sheets reused on every run;
- both sheets reconciling;
- leads leaving and joining the audience, including newly enrolled ones;
- every failure path leaving the live audience untouched;
- the Layer 3 wiring and the summary e-mail.
