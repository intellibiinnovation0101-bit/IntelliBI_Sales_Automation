/**
 * IntelliBI — Lead Counselling Profile  |  UI script
 * ---------------------------------------------------------
 * ONE script, two responsibilities:
 *
 *  A) beautifyLeadForm()  – restyles the form sheet in place (unchanged).
 *  B) validateMobileNumber() / the "Tick here to Save" checkbox – Validate & Save
 *     buttons that read/write the PhoneNumber_FiledMapping_Data sheet,
 *     using the Mobile Number as the primary key. Field mapping is
 *     header/label based (position-independent).
 *
 * onOpen() also adds a "Lead Form" menu (Validate / Submit / Re-format)
 * so the actions work even before the drawing buttons are wired up.
 *
 * HOW TO USE
 *   1. Open the sheet ▸ Extensions ▸ Apps Script.
 *   2. Delete any starter code, paste this whole file, Save.
 *   3. Run "beautifyLeadForm" once ▸ approve the one-time prompt.
 *   4. Reload the sheet — the "Lead Form" menu appears. To get real
 *      buttons next to Mobile Number, Insert ▸ Drawing a button, then
 *      "Assign script" ▸ validateMobileNumber. Saving is done by the
 *      "Tick here to Save" checkbox (run setupCheckboxSubmit once to create it).
 */

// ---- IntelliBI brand palette ---------------------------------------------
var NAVY     = '#0F2D4A';   // header text
var ACCENT   = '#1F6FB2';   // form table header
var LABEL_BG = '#E9F1F9';   // header / label cells
var VALUE_BG = '#FFFFFF';   // input / value cells
var PAGE_BG  = '#EEF3F8';   // page background around the card
var BORDER   = '#C8D6E3';   // grid borders
var WHITE    = '#FFFFFF';
var FONT_HEAD = 'Poppins';
var FONT_BODY = 'Roboto';

// PhoneNumber_FiledMapping_UI   (this sheet — the form)
var SHEET_ID = '1o5446I4PuZ9fmim6kT0tNYN7jy_A3-YYicNK0z7tcBE';
// PhoneNumber_FiledMapping_Data (the backing data store)
var DATA_ID  = '1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw';

// Backend column that stamps when each record was last inserted / updated.
var TIMESTAMP_COL = 'RecordTimeStamp';
var TIMESTAMP_TZ  = 'Asia/Kolkata';           // IST
var TIMESTAMP_FMT = 'dd-MMM-yyyy HH:mm:ss';    // e.g. 07-Aug-2026 14:35:09

// Active / InActive record-history tabs inside the backend Data spreadsheet.
// Active  = only the latest version of each record (what Validate reads).
// InActive = full history: every previous version is archived here on update.
var ACTIVE_SHEET_NAME    = 'IntelliBI Lead Information Active';
var INACTIVE_SHEET_NAME  = 'IntelliBI Lead Information InActive';
// Older names the Active tab may still have (used only as a fallback lookup).
var ACTIVE_SHEET_ALIASES = ['IntelliBI Lead Information Result'];
// Audit columns added (in front of the record's own columns) on the InActive
// sheet. RecordVersion increments per mobile number; ArchivedAt = archive time.
var AUDIT_FIELDS = ['RecordVersion', 'ArchivedAt'];

/** The Active data tab (by name, with aliases, else the first tab). */
function getActiveDataSheet_(dataSS) {
  var s = dataSS.getSheetByName(ACTIVE_SHEET_NAME);
  if (s) return s;
  for (var i = 0; i < ACTIVE_SHEET_ALIASES.length; i++) {
    s = dataSS.getSheetByName(ACTIVE_SHEET_ALIASES[i]);
    if (s) return s;
  }
  return dataSS.getSheets()[0];                 // final fallback
}

/** The InActive (history) tab, or null if it hasn't been created. */
function getInactiveDataSheet_(dataSS) {
  return dataSS.getSheetByName(INACTIVE_SHEET_NAME);
}

/**
 * Archive the CURRENT (about-to-be-overwritten) Active row into the InActive
 * history sheet, stamped with an incrementing RecordVersion (per mobile) and an
 * ArchivedAt time. `activeHeaders` are the Active sheet's headers; `oldRowVals`
 * is that record's existing row (pre-update). No-op if the InActive tab or the
 * old row is missing.
 */
function archiveToInactive_(inactiveSheet, activeHeaders, oldRowVals, key) {
  if (!inactiveSheet || !oldRowVals) return;

  var want = AUDIT_FIELDS.concat(activeHeaders);        // desired InActive header
  var lastRow = inactiveSheet.getLastRow();
  var lastCol = inactiveSheet.getLastColumn();
  var headers;
  if (lastRow === 0 || lastCol === 0) {
    headers = want.slice();
    writeHeaders_(inactiveSheet, headers);
  } else {
    headers = inactiveSheet.getRange(1, 1, 1, lastCol).getValues()[0]
                           .map(function (h) { return cleanLabel_(h); });
    var added = false;
    want.forEach(function (h) { if (headerIndex_(headers, h) < 0) { headers.push(h); added = true; } });
    if (added) writeHeaders_(inactiveSheet, headers);
  }

  // next version = how many history rows already exist for this mobile + 1.
  // Counted with a server-side TextFinder on the Mobile Number column (no
  // full-sheet read), so it stays fast as the history grows.
  var mColIn = headerIndex_(headers, 'mobile number');
  var version = 1;
  if (inactiveSheet.getLastRow() >= 2 && mColIn >= 0) {
    var cnt = inactiveSheet.getRange(2, mColIn + 1, inactiveSheet.getLastRow() - 1, 1)
                           .createTextFinder(key).matchEntireCell(true)
                           .useRegularExpression(false).findAll().length;
    version = cnt + 1;
  }

  // map the old Active row onto its headers, then emit in InActive header order
  var oldRec = {};
  for (var i = 0; i < activeHeaders.length; i++) {
    oldRec[activeHeaders[i].toLowerCase()] = (i < oldRowVals.length) ? oldRowVals[i] : '';
  }
  var archivedAt = Utilities.formatDate(new Date(), TIMESTAMP_TZ, TIMESTAMP_FMT);
  var rowOut = headers.map(function (h) {
    var hl = h.toLowerCase();
    if (hl === 'recordversion') return version;
    if (hl === 'archivedat')    return archivedAt;
    return (oldRec[hl] !== undefined) ? oldRec[hl] : '';
  });
  inactiveSheet.appendRow(rowOut);
}

// ---- menu (so the buttons work even before drawings are assigned) --------
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Lead Form')
    .addItem('✅ Validate Mobile Number', 'validateMobileNumber')
    .addItem('♻️ Reset Form (keep Counselling By)', 'resetForm')
    .addSeparator()
    .addItem('🎨 Re-apply formatting', 'beautifyLeadForm')
    .addItem('🗂️ Set up counsellor tabs', 'setupCounsellorTabs')
    .addItem('🔄 Sync Data columns with form', 'syncDataColumnsWithForm')
    .addItem('📅 Set up Save box + date pickers', 'setupCheckboxSubmit')
    .addToUi();
  // when the file opens, make sure each tab shows its default Counselling By
  try { ensureCounsellingDefaults_(); } catch (e) {}
}

// One tab per counsellor (all in this single spreadsheet, one script, one
// backend Data sheet). Single source of truth: the tab name and that tab's
// default "Counselling By" value. Edit here to add / rename counsellors, then
// run setupCounsellorTabs again.
var COUNSELLOR_TABS = [
  { tab: 'IntelliBI Lead Information Harish',   counsellingBy: 'Harish Rathod' },
  { tab: 'IntelliBI Lead Information Arsh',     counsellingBy: 'ArshKhan Pathan' },
  { tab: 'IntelliBI Lead Information IntelliBI', counsellingBy: 'IntelliBI Escalation' }
];

/** Default "Counselling By" value for a given tab (‘’ if the tab isn't listed). */
function defaultCounsellingBy_(sheet) {
  var n = sheet.getName();
  for (var i = 0; i < COUNSELLOR_TABS.length; i++) {
    if (COUNSELLOR_TABS[i].tab === n) return COUNSELLOR_TABS[i].counsellingBy;
  }
  return '';
}

/**
 * Write the tab's default into its "Counselling By" value cell.
 * onlyIfBlank=true leaves a value the user already typed untouched.
 */
function setCounsellingByDefault_(sheet, ctx, onlyIfBlank) {
  var def = defaultCounsellingBy_(sheet);
  if (!def) return;
  for (var i = 0; i < ctx.fields.length; i++) {
    if (ctx.fields[i].label.toLowerCase() === 'counselling by') {
      var cell = sheet.getRange(ctx.fields[i].row, ctx.fields[i].col);
      if (onlyIfBlank && String(cell.getValue()).trim() !== '') return;
      cell.setValue(def);
      return;
    }
  }
}

/** On open, ensure each counsellor tab shows its default Counselling By (if blank). */
function ensureCounsellingDefaults_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) return;
  COUNSELLOR_TABS.forEach(function (t) {
    var sheet = ss.getSheetByName(t.tab);
    if (!sheet) return;
    var ctx = getUiContext_(sheet);
    if (ctx.mobileCell) setCounsellingByDefault_(sheet, ctx, true);   // don't clobber typed values
  });
}

/**
 * OPTIONAL convenience (menu ▸ "Sync Data columns with form").
 *
 * Whenever you add a NEW field to the form (e.g. "Follow-Up Type") or rearrange
 * the C/D fields, the mapping is already handled automatically — the form is read
 * by LABEL, not by cell position, so Validate/Submit map every field to the Data
 * column of the same name and CREATE a column for any new field on the next save.
 *
 * This helper just lets you make that new column appear (and confirm the Data
 * structure) immediately, without having to submit a record first. It is fully
 * NON-DESTRUCTIVE: it only APPENDS any missing columns to the Data 'Active' and
 * 'InActive' sheets — it never renames, reorders, moves or deletes an existing
 * column, so all existing records stay exactly where they are. It changes no
 * other logic; Validate/Submit/history all continue to work as before.
 */
function syncDataColumnsWithForm() {
  var ui = SpreadsheetApp.getUi();
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
    var uiSheet = pickFormSheet(ss);
    var ctx = getUiContext_(uiSheet);
    if (!ctx || !ctx.mobileCell) {
      ui.alert('IntelliBI',
        'Open a lead-form tab (with "Mobile Number" / "Column Name") and run this again.',
        ui.ButtonSet.OK);
      return;
    }

    // Current form fields, in form order, de-duplicated (Mobile Number is first).
    var formFields = [];
    ctx.fields.forEach(function (f) {
      var lab = cleanLabel_(f.label);
      if (lab && formFields.indexOf(lab) === -1) formFields.push(lab);
    });
    // the submit stamp column is part of the Active/InActive structure too
    if (formFields.indexOf(TIMESTAMP_COL) === -1) formFields.push(TIMESTAMP_COL);

    var dataSS = SpreadsheetApp.openById(DATA_ID);
    var active = getActiveDataSheet_(dataSS);
    var inactive = getInactiveDataSheet_(dataSS);

    var addedActive = active ? ensureColumns_(active, formFields) : [];
    // InActive additionally carries the audit fields (RecordVersion / ArchivedAt)
    var addedInactive = inactive
      ? ensureColumns_(inactive, AUDIT_FIELDS.concat(formFields)) : null;

    var msg = 'Data columns are now in sync with the form.\n\n' +
      'Active sheet — added: ' +
      (addedActive.length ? addedActive.join(', ') : '(none — already in sync)') + '\n' +
      'InActive sheet — added: ' +
      (inactive ? (addedInactive.length ? addedInactive.join(', ')
                                        : '(none — already in sync)')
                : '(no InActive tab yet)') +
      '\n\nExisting columns and data were left untouched.';
    ui.alert('IntelliBI', msg, ui.ButtonSet.OK);
  } catch (e) {
    ui.alert('IntelliBI', 'Sync failed: ' + ((e && e.message) ? e.message : e),
             ui.ButtonSet.OK);
  }
}

/**
 * Append any of wantHeaders that are missing from `sheet`'s header row (matched
 * by name, case-insensitively). Returns the list of columns actually added.
 * Never renames, reorders or removes an existing column — append-only, so it is
 * safe to run on a sheet that already holds records.
 */
function ensureColumns_(sheet, wantHeaders) {
  var lastCol = sheet.getLastColumn();
  var headers = lastCol > 0
    ? sheet.getRange(1, 1, 1, lastCol).getValues()[0]
           .map(function (h) { return cleanLabel_(h); })
    : [];
  var added = [];
  wantHeaders.forEach(function (h) {
    h = cleanLabel_(h);
    if (h && headerIndex_(headers, h) < 0) { headers.push(h); added.push(h); }
  });
  if (added.length) writeHeaders_(sheet, headers);
  return added;
}

/**
 * Create (or verify) one form tab per counsellor by duplicating the existing
 * lead-form tab. Duplication keeps the layout, dropdowns and the Validate /
 * Submit buttons; each new tab is then blanked so it's ready for data entry.
 * Safe to re-run: existing tabs are left in place, missing ones are created.
 */
function setupCounsellorTabs() {
  var ui = SpreadsheetApp.getUi();
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
    var template = pickFormSheet(ss);
    if (!template || !sheetIsForm_(template)) {
      ui.alert('No form found',
        'Open the tab that has the lead form (with "Mobile Number" / "Column Name"), then run this again.',
        ui.ButtonSet.OK);
      return;
    }
    var names = COUNSELLOR_TABS.map(function (t) { return t.tab; });
    var templateConsumed = false;
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      var sheet = ss.getSheetByName(name);
      if (!sheet) {
        if (!templateConsumed && names.indexOf(template.getName()) === -1) {
          template.setName(name);            // reuse the existing form tab as the first
          sheet = template;
          templateConsumed = true;
        } else {
          sheet = template.copyTo(ss);       // duplicate: keeps layout, dropdowns, buttons
          sheet.setName(name);
        }
      }
      clearFormValues_(sheet);               // blank the form (also sets the tab default)
    }
    // put the counsellor tabs first, in the listed order
    for (var j = 0; j < names.length; j++) {
      var s = ss.getSheetByName(names[j]);
      if (s) { ss.setActiveSheet(s); ss.moveActiveSheet(j + 1); }
    }
    SpreadsheetApp.flush();
    ui.alert('Counsellor tabs ready',
      'These tabs are set up (same script, same backend Data sheet):\n\n• ' +
      names.join('\n• ') +
      '\n\nEach counsellor works in their own tab. If a tab is missing its ' +
      'Validate/Submit buttons, use the "Lead Form" menu, or copy the buttons over.',
      ui.ButtonSet.OK);
  } catch (e) {
    ui.alert('Setup failed', (e && e.message) ? e.message : String(e), ui.ButtonSet.OK);
  }
}

/** Blank the input value cells of one form tab (keeps labels, dropdowns, formats). */
function clearFormValues_(sheet) {
  var ctx = getUiContext_(sheet);
  if (ctx.mobileCell) {
    resetInputFields_(sheet, ctx);
    formatContactInputs_(sheet, ctx.inputRow);
  }
}

// ---- contact input cells (A2 / B2 / C2) formatting -----------------------
var INPUT_FONT   = 'Roboto';
var INPUT_SIZE   = 14;

/** Apply the required format to the three contact input cells (Mobile / Name /
 *  Email) on the given input row: Roboto 14, centered, middle-aligned. */
function formatContactInputs_(sheet, inputRow) {
  if (!inputRow || inputRow < 1) return;
  sheet.getRange(inputRow, 1, 1, 3)          // A2:C2 (C2 is the merged Email cell)
       .setFontFamily(INPUT_FONT).setFontSize(INPUT_SIZE)
       .setHorizontalAlignment('center').setVerticalAlignment('middle');
}

/** Cheap lookup of the contact input row (row below "Mobile Number"). */
function contactInputRow_(sheet) {
  var n = Math.min(sheet.getMaxRows(), 8);
  var col = sheet.getRange(1, 1, n, 1).getValues();
  for (var r = 0; r < col.length; r++) {
    if (String(col[r][0]).trim().toLowerCase() === 'mobile number') return r + 2;
  }
  return -1;
}

/**
 * Simple onEdit trigger: whenever a user types OR pastes into the contact
 * input cells (A2 / B2 / C2), re-apply the required Roboto 14 / centered /
 * middle format, so pasted content never keeps the source's formatting.
 * Runs only for user edits (not the script's own writes), so no recursion.
 */
function onEdit(e) {
  try {
    if (!e || !e.range) return;
    var sheet = e.range.getSheet();
    var inputRow = contactInputRow_(sheet);
    if (inputRow < 1) return;                             // not a lead-form tab

    var r0 = e.range.getRow(), r1 = r0 + e.range.getNumRows() - 1;
    var c0 = e.range.getColumn(), c1 = c0 + e.range.getNumColumns() - 1;
    if (inputRow < r0 || inputRow > r1) return;           // edit didn't touch the input row
    if (c1 < 1 || c0 > 3) return;                         // not columns A-C

    formatContactInputs_(sheet, inputRow);
  } catch (err) { /* never block the user's edit */ }
}

function beautifyLeadForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet() ||
           SpreadsheetApp.openById(SHEET_ID);
  var sheet = pickFormSheet(ss);
  var SOLID = SpreadsheetApp.BorderStyle.SOLID;

  // frozen rows can block row deletion — clear first
  if (sheet.getFrozenRows() > 0) sheet.setFrozenRows(0);

  // ---- 1. remove everything ABOVE the contact header --------------------
  //         (the old "IntelliBI" banner, subtitle strip and any blanks)
  var contactRow = findRowByText_(sheet, 'mobile number');
  if (contactRow > 1) {
    sheet.deleteRows(1, contactRow - 1);
  }
  // recompute after the shift
  contactRow = findRowByText_(sheet, 'mobile number');
  if (contactRow < 1) contactRow = 1;          // fallback
  var inputRow  = contactRow + 1;
  var headerRow = findRowByText_(sheet, 'column name');

  // ensure a blank INPUT row exists between the header and the form table
  if (headerRow === inputRow) {                // no gap -> insert one
    sheet.insertRowAfter(contactRow);
    headerRow = findRowByText_(sheet, 'column name');
  }

  // ---- work out the content box -----------------------------------------
  var data = sheet.getDataRange().getValues();
  var lastCol = 4;
  for (var r = 0; r < data.length; r++) {
    for (var c = data[r].length - 1; c >= 0; c--) {
      if (String(data[r][c]).trim() !== '') { if (c + 1 > lastCol) lastCol = c + 1; break; }
    }
  }
  var lastRow = 0;
  for (var r2 = 0; r2 < data.length; r2++) {
    for (var c2 = 0; c2 < data[r2].length; c2++) {
      if (String(data[r2][c2]).trim() !== '') { lastRow = r2 + 1; break; }
    }
  }

  // ---- 0. hide gridlines + page background over a generous area ----------
  sheet.setHiddenGridlines(true);
  var maxR = Math.max(lastRow + 6, 40);
  var maxC = Math.max(lastCol + 4, 10);
  sheet.getRange(1, 1, maxR, maxC)
       .setBackground(PAGE_BG)
       .setFontFamily(FONT_BODY)
       .setVerticalAlignment('middle');

  // ---- 2. contact HEADER row (Mobile Number | Full Name | Email Address)-
  //   Explicitly (re)write all three labels so none is ever missing, then
  //   widen "Email Address" across columns C:D.
  try { sheet.getRange(contactRow, 1, 1, lastCol).breakApart(); } catch (e) {}
  sheet.getRange(contactRow, 1).setValue('Mobile Number');
  sheet.getRange(contactRow, 2).setValue('Full Name');
  sheet.getRange(contactRow, 3).setValue('Email Address');
  if (lastCol > 3) {
    sheet.getRange(contactRow, 4, 1, lastCol - 3).clearContent();   // clear D..
    sheet.getRange(contactRow, 3, 1, lastCol - 2).merge();          // merge C:D
  }
  sheet.getRange(contactRow, 1, 1, lastCol)
       .setBackground(LABEL_BG).setFontColor(NAVY).setFontWeight('bold')
       .setFontFamily(FONT_HEAD).setFontSize(11)
       .setHorizontalAlignment('center').setVerticalAlignment('middle')
       .setWrap(true);
  sheet.setRowHeight(contactRow, 32);

  // ---- 3. contact INPUT row (blank cells for the three values) ----------
  safeMerge_(sheet, inputRow, 3, lastCol);
  sheet.getRange(inputRow, 1, 1, lastCol)
       .setBackground(VALUE_BG).setFontColor('#1A2B3C').setFontWeight('normal')
       .setFontFamily(FONT_BODY).setFontSize(11)
       .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sheet.setRowHeight(inputRow, 34);
  // required format for the three contact input cells (A2/B2/C2): Roboto 14
  formatContactInputs_(sheet, inputRow);

  // border around the two-row contact block
  sheet.getRange(contactRow, 1, 2, lastCol)
       .setBorder(true, true, true, true, true, true, BORDER, SOLID);

  // ---- 4. form table (Column Name | Enter Column Value | ...) -----------
  if (headerRow > 0) {
    sheet.getRange(headerRow, 1, 1, lastCol)
         .setBackground(ACCENT).setFontColor(WHITE).setFontWeight('bold')
         .setFontFamily(FONT_HEAD).setFontSize(10)
         .setHorizontalAlignment('left').setVerticalAlignment('middle');
    sheet.setRowHeight(headerRow, 30);

    var body0 = headerRow + 1;
    if (lastRow >= body0) {
      var numBody = lastRow - body0 + 1;
      [1, 3].forEach(function (col) {            // label columns A & C
        if (col <= lastCol) {
          sheet.getRange(body0, col, numBody, 1)
               .setBackground(LABEL_BG).setFontColor(NAVY).setFontWeight('bold')
               .setFontFamily(FONT_BODY).setFontSize(10)
               .setHorizontalAlignment('left').setVerticalAlignment('middle')
               .setWrap(true);
        }
      });
      [2, 4].forEach(function (col) {            // value columns B & D
        if (col <= lastCol) {
          sheet.getRange(body0, col, numBody, 1)
               .setBackground(VALUE_BG).setFontColor('#1A2B3C').setFontWeight('normal')
               .setFontFamily(FONT_BODY).setFontSize(10)
               .setHorizontalAlignment('left').setVerticalAlignment('middle')
               .setWrap(true);
        }
      });
      sheet.setRowHeights(body0, numBody, 30);
      sheet.getRange(headerRow, 1, lastRow - headerRow + 1, lastCol)
           .setBorder(true, true, true, true, true, true, BORDER, SOLID);
    }
  }

  // ---- 5. column widths --------------------------------------------------
  var widths = [210, 300, 220, 300];
  for (var i = 0; i < widths.length && (i + 1) <= lastCol; i++) {
    sheet.setColumnWidth(i + 1, widths[i]);
  }

  // ---- 6. freeze the contact header -------------------------------------
  sheet.setFrozenRows(1);

  // ---- 7. date fields: make them real, calendar-picked dates ------------
  //        (reliable commit on selection + one consistent display format)
  applyDateFieldSetup_(sheet);

  SpreadsheetApp.flush();
}

// ---- helpers --------------------------------------------------------------
// ---- date fields: real, calendar-picked dates ----------------------------
// Root-cause fix for "Next Follow-Up Date keeps the old value": the date value
// cells were plain free-text, so a date entered via the in-cell calendar (or
// typed but not yet committed) could be dropped when the Submit button is
// clicked, leaving the previously-loaded date in place. The Submit/upsert logic
// itself is correct (it always writes whatever the form cell holds) - so the fix
// is to make these cells behave as real dates: a Date data-validation shows a
// calendar whose pick COMMITS immediately, and a single number format keeps the
// stored value a real, unambiguous date. ADD-ONLY: no label, matching, update,
// submit or existing-validation logic is changed - only the date VALUE cells get
// a format + a date rule.
var DATE_VALUE_FIELDS = ['next follow-up date',
                         'isgooglemeetscheduledate',
                         'iswalkinscheduledate'];
// Date fields use a calendar date-picker (Date data-validation) so entry is
// unambiguous. The "Tick here to Save" checkbox commits the picked date before
// the record is read/saved, so the chosen date is captured reliably.
var DATE_CELL_FORMAT  = 'd-mmm-yyyy';   // e.g. 19-Sep-2026 (no M/D vs D/M ambiguity)

/**
 * Apply the date number-format + Date data-validation (calendar picker) to the
 * date VALUE cells of one lead-form sheet. Matched by cleaned label (trailing
 * colon / case-insensitive), so it follows the fields wherever they sit. Best-
 * effort and self-guarded; returns the number of date cells set up.
 */
function applyDateFieldSetup_(sheet) {
  try {
    var ctx = getUiContext_(sheet);
    if (!ctx || !ctx.fields || !ctx.fields.length) return 0;
    // A real Date data-validation shows a calendar picker and accepts only a valid
    // date, so entry is unambiguous (no more day-first / free-text in date cells).
    var rule = SpreadsheetApp.newDataValidation()
      .requireDate()
      .setAllowInvalid(false)
      .setHelpText('Pick the date from the calendar.')
      .build();
    var n = 0;
    ctx.fields.forEach(function (f) {
      var lab = cleanLabel_(f.label).toLowerCase();
      if (DATE_VALUE_FIELDS.indexOf(lab) === -1) return;
      var cell = sheet.getRange(f.row, f.col);
      try { cell.setNumberFormat(DATE_CELL_FORMAT); } catch (e) {}
      try { cell.setDataValidation(rule); } catch (e) {}
      n++;
    });
    return n;
  } catch (e) { return 0; }
}

// ===========================================================================
//  RELIABLE "TICK HERE TO SAVE" checkbox  (commits the calendar date, then saves)
// ===========================================================================
/**
 * Installable onEdit handler for the "TICK HERE TO SAVE" checkbox. Ticking a
 * checkbox is a CELL click, which commits any in-progress in-cell edit first -
 * including a calendar date pick - so the newly chosen values are captured
 * reliably (a floating drawing button does NOT commit the active cell, which is
 * why the Follow-Up Date could keep its old value). It runs the SAME runSubmit
 * logic, shows the result as a toast (no pop-up), then unticks the box.
 * Must be installed via setupCheckboxSubmit() (a simple trigger cannot open the
 * Data spreadsheet). Guarded so it only ever acts on OUR save checkbox.
 */
function onLeadFormCheckbox(e) {
  try {
    if (!e || !e.range) return;
    var rng = e.range;
    if (rng.getNumRows() !== 1 || rng.getNumColumns() !== 1) return;   // single cell
    if (rng.getValue() !== true) return;                               // only when TICKED
    var sh = rng.getSheet();
    var col = rng.getColumn();
    if (col < 2) return;
    // identify our checkbox by the marker text in the cell to its LEFT
    var marker = String(sh.getRange(rng.getRow(), col - 1).getValue()).toLowerCase();
    var isTick   = marker.indexOf('tick') !== -1;
    var isSave   = isTick && marker.indexOf('save')   !== -1;
    var isReset  = isTick && marker.indexOf('reset')  !== -1;
    var isSearch = isTick && marker.indexOf('search') !== -1;
    if (!isSave && !isReset && !isSearch) return;

    // ---- SEARCH checkbox: run the SAME Validate/Search logic, then re-arm ----
    // A modal pop-up can't be opened from an onEdit trigger, so we run
    // runValidate() directly (on THIS tab) and show a processing + result toast,
    // exactly like the Save checkbox. The validate/search logic itself is unchanged.
    if (isSearch) {
      try { rng.setValue(false); } catch (ignoreS) {}       // untick -> ready to reuse
      try {
        (e.source || SpreadsheetApp.getActiveSpreadsheet())
          .toast('Searching… Please wait.', 'IntelliBI', -1);   // -1 = stay until replaced
      } catch (ignoreS2) {}
      var vres;
      try {
        vres = runValidate(sh);                              // same Validate logic, on THIS tab
      } catch (errS) {
        vres = { ok: false, kind: 'error', title: 'Search failed',
                 message: (errS && errS.message) ? errS.message : String(errS) };
      }
      try {
        (e.source || SpreadsheetApp.getActiveSpreadsheet())
          .toast((vres && vres.message) ? vres.message : 'Done.',
                 (vres && vres.title) ? vres.title : 'IntelliBI', 5);
      } catch (ignoreS3) {}
      return;
    }

    // ---- RESET checkbox: clear the form (keep Counselling By), then re-arm ----
    if (isReset) {
      try { rng.setValue(false); } catch (ignoreR) {}       // untick -> ready to reuse
      try {
        (e.source || SpreadsheetApp.getActiveSpreadsheet())
          .toast('Clearing… Please wait.', 'IntelliBI', -1);  // processing; replaced below
      } catch (ignoreRp) {}
      try {
        resetFormOnSheet_(sh);                              // same reset core as the menu
        (e.source || SpreadsheetApp.getActiveSpreadsheet())
          .toast('Form cleared. Counselling By kept unchanged.', 'IntelliBI', 4);
      } catch (errR) {
        (e.source || SpreadsheetApp.getActiveSpreadsheet())
          .toast('Reset error: ' + ((errR && errR.message) ? errR.message : errR),
                 'IntelliBI', 5);
      }
      return;
    }

    // Processing indicator for the "TICK TO SAVE" action. A modal pop-up (like
    // the Validate/Submit dialog) cannot be opened from an onEdit trigger, so we
    // show a PERSISTENT toast with the same "Submitting… Please wait." wording:
    // it appears the moment the box is ticked, stays visible while runSubmit is
    // working, and is automatically replaced by the result toast below when the
    // save completes.
    try {
      (e.source || SpreadsheetApp.getActiveSpreadsheet())
        .toast('Submitting… Please wait.', 'IntelliBI', -1);   // -1 = stay until replaced
    } catch (ignoreProc) {}

    var res;
    try {
      res = runSubmit(sh);                     // same save logic, on THIS tab
    } catch (err) {
      res = { ok: false, kind: 'error', title: 'Submit failed',
              message: (err && err.message) ? err.message : String(err) };
    }
    try { rng.setValue(false); } catch (ignore) {}          // untick -> re-arm
    try {
      (e.source || SpreadsheetApp.getActiveSpreadsheet())
        .toast((res && res.message) ? res.message : 'Done.',
               (res && res.title) ? res.title : 'IntelliBI', 5);
    } catch (ignore2) {}
  } catch (err2) {
    try { (e.source || SpreadsheetApp.getActiveSpreadsheet())
            .toast('Save error: ' + err2, 'IntelliBI', 5); } catch (i) {}
  }
}

/**
 * Run ONCE (menu: "Set up Save box + date pickers"): sets up the reliable save
 * flow on every lead-form tab -
 *   - date fields become calendar date-pickers (applyDateFieldSetup_),
 *   - a "TICK HERE TO SAVE" label + checkbox is placed to the right of the
 *     Mobile Number box,
 *   - one installable onEdit trigger runs the save when the box is ticked.
 * Safe to re-run (removes our previously-installed trigger first).
 */
function setupCheckboxSubmit() {
  var ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
  var existing = ScriptApp.getProjectTriggers();
  for (var i = 0; i < existing.length; i++) {
    if (existing[i].getHandlerFunction() === 'onLeadFormCheckbox')
      ScriptApp.deleteTrigger(existing[i]);
  }
  ScriptApp.newTrigger('onLeadFormCheckbox').forSpreadsheet(ss).onEdit().create();

  var sheets = ss.getSheets(), tabs = 0;
  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    if (!sheetIsForm_(sh)) continue;
    try { applyDateFieldSetup_(sh); } catch (e) {}          // calendar date pickers
    try {
      var ctx = getUiContext_(sh);
      if (ctx && ctx.mobileCell) {
        var r  = ctx.mobileCell.row;                        // the mobile input row
        // All three actions are checkbox controls in columns E (label) / F (box),
        // stacked on the rows just below the contact input row:
        //   Save   -> E,F of (input row + 1)   [E3/F3 in the standard layout]
        //   Search -> E,F of (input row + 2)   [E4/F4]
        //   Reset  -> E,F of (input row + 3)   [E5/F5]
        // Remove ANY previously-placed Save/Search/Reset controls first (these
        // rows AND the older F/G positions) so re-running never duplicates them.
        var base = r + 1;
        for (var srow = r; srow <= r + 3; srow++) {
          for (var cc = 5; cc <= 60; cc++) {
            var mk = String(sh.getRange(srow, cc).getValue()).toLowerCase();
            if (mk.indexOf('tick') !== -1 &&
                (mk.indexOf('save')  !== -1 || mk.indexOf('reset') !== -1 ||
                 mk.indexOf('search') !== -1)) {
              sh.getRange(srow, cc, 1, 2).clearContent().clearFormat().clearDataValidations();
            }
          }
        }
        // Same shape/size/formatting, distinct hue: green Save, blue Search, red Reset.
        placeTickControl_(sh, base,     '✅ TICK TO SAVE ▶',   '#188038', '#0B5A28');
        placeTickControl_(sh, base + 1, '🔍 TICK TO SEARCH ▶', '#1967D2', '#0B3A8B');
        placeTickControl_(sh, base + 2, '♻️ TICK TO RESET ▶',  '#B7472A', '#7A2E1B');
        try { sh.setColumnWidth(5, 175); } catch (e) {}     // E = label
        try { sh.setColumnWidth(6, 54);  } catch (e) {}     // F = checkbox
        tabs++;
      }
    } catch (e2) {}
  }
  SpreadsheetApp.flush();
  try {
    SpreadsheetApp.getUi().alert('IntelliBI',
      'Three tick controls are set up on ' + tabs + ' form tab(s) (columns E/F), with ' +
      'calendar date pickers:\n\n' +
      '🔍 TICK TO SEARCH  - enter a Mobile Number, then tick to fetch the lead.\n' +
      '✅ TICK TO SAVE    - after editing, tick to save the lead.\n' +
      '♻️ TICK TO RESET   - tick to clear the form (keeps Counselling By).\n\n' +
      'Each box runs its action, then unticks itself. (The old Validate button is no ' +
      'longer needed - you can delete that drawing.)',
      SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (e3) {}
  return { tabs: tabs };
}

/** Place one "tick to <action>" control: a coloured label in column E and a
 *  checkbox in column F on the given row. Identical shape/size/formatting for all
 *  three actions (Save / Search / Reset); only the label text + colour differ, so
 *  they match visually while staying easy to tell apart. */
function placeTickControl_(sh, row, labelText, bgHex, borderHex) {
  var lab = sh.getRange(row, 5);   // E = label
  var box = sh.getRange(row, 6);   // F = checkbox
  lab.setValue(labelText)
     .setFontFamily(FONT_HEAD).setFontSize(12).setFontWeight('bold')
     .setFontColor(WHITE).setBackground(bgHex)
     .setHorizontalAlignment('center').setVerticalAlignment('middle').setWrap(true)
     .setBorder(true, true, true, true, false, false,
               borderHex, SpreadsheetApp.BorderStyle.SOLID_THICK);
  box.insertCheckboxes();
  box.setValue(false);
  box.setBackground('#FFD400')
     .setHorizontalAlignment('center').setVerticalAlignment('middle')
     .setBorder(true, true, true, true, false, false,
               borderHex, SpreadsheetApp.BorderStyle.SOLID_THICK);
  try { sh.setRowHeight(row, 42); } catch (e) {}
}

function pickFormSheet(ss) {
  // Always prefer the tab the user is actually on — this makes a single
  // spreadsheet with one tab per counsellor work (each counsellor's buttons act
  // on their OWN tab, never the first tab). Resolve the active tab two ways for
  // robustness across button/menu contexts, then fall back to the first
  // form-shaped tab only if neither is available.
  var active = ss.getActiveSheet();
  if (active && sheetIsForm_(active)) return active;
  try {
    var rngSheet = ss.getActiveRange() && ss.getActiveRange().getSheet();
    if (rngSheet && sheetIsForm_(rngSheet)) return rngSheet;
  } catch (e) {}
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheetIsForm_(sheets[i])) return sheets[i];
  }
  return active || sheets[0];
}

/** True if a sheet looks like the lead form (has the Mobile Number / Column Name markers). */
function sheetIsForm_(sh) {
  var rows = Math.min(sh.getMaxRows(), 40);
  var col = sh.getRange(1, 1, rows, 1).getValues();
  for (var r = 0; r < col.length; r++) {
    var v = String(col[r][0]).trim().toLowerCase();
    if (v === 'column name' || v === 'mobile number') return true;
  }
  return false;
}

function findRowByText_(sheet, text) {
  var t = text.trim().toLowerCase();
  var rows = Math.min(sheet.getMaxRows(), 200);
  var col = sheet.getRange(1, 1, rows, 1).getValues();
  for (var r = 0; r < col.length; r++) {
    if (String(col[r][0]).trim().toLowerCase() === t) return r + 1;
  }
  return -1;
}

/** Break any merges in the row, then merge columns [fromCol..lastCol]. */
function safeMerge_(sheet, row, fromCol, lastCol) {
  try { sheet.getRange(row, 1, 1, lastCol).breakApart(); } catch (e) {}
  if (lastCol > fromCol) {
    try { sheet.getRange(row, fromCol, 1, lastCol - fromCol + 1).merge(); } catch (e) {}
  }
}

// ===========================================================================
//  VALIDATE  &  SUBMIT   (Mobile Number is the primary key)
// ===========================================================================

/** VALIDATE button:
 *  - checks the entered mobile number (Indian rules)
 *  - if valid, looks it up in the Data sheet and loads any existing record
 *    (editable); if none, leaves the fields for manual entry.
 */
function validateMobileNumber() { showOpDialog_('validate'); }

/** Core validate logic — runs inside the popup via google.script.run and
 *  RETURNS a small result object {ok, kind, title, message}. */
function runValidate(uiSheetOverride) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
    // uiSheetOverride lets the "TICK TO SEARCH" checkbox validate on ITS OWN tab
    // (same pattern as runSubmit). With no argument the behaviour is unchanged
    // (the popup/menu path still resolves the sheet via pickFormSheet).
    var uiSheet = uiSheetOverride || pickFormSheet(ss);
    var ctx = getUiContext_(uiSheet);
    if (!ctx.mobileCell) {
      return { ok: false, kind: 'error', title: 'Setup issue',
        message: 'Could not find the "Mobile Number" field. Run "beautifyLeadForm" first.' };
    }
    var mc = ctx.mobileCell;
    // reuse the value already fetched by getUiContext_ (same committed state as a
    // live read) instead of a second single-cell round-trip to the sheet.
    var raw = (ctx.values[mc.row - 1] || [])[mc.col - 1];

    if (String(raw == null ? '' : raw).trim() === '') {
      return { ok: false, kind: 'warn', title: 'Mobile Number required',
        message: 'Enter a mobile number in the box under "Mobile Number", press ' +
                 'Enter, then click Validate.' };
    }
    if (!isValidIndianMobile_(raw)) {
      return { ok: false, kind: 'error', title: 'Invalid Mobile Number',
        message: 'Enter a valid 10-digit number starting 6-9 (+91 / 0 is fine).' };
    }

    var key = normalizeMobile_(raw);
    var dataSheet = getActiveDataSheet_(SpreadsheetApp.openById(DATA_ID));  // Active only
    var rec = findRecord_(dataSheet, key);

    if (rec.found) {
      // The record's OWN (primary) Mobile Number, used to fill the Mobile Number
      // box. When the search matched on the primary number this equals `key`
      // (behaviour unchanged); when it matched on the Alternative Mobile Number,
      // this shows the real primary number instead of the alternate the counsellor
      // typed — so the form, and any subsequent Save (which keys on this box),
      // act on the correct lead rather than creating a record under the alt number.
      var recMobile = rec.map['mobile number'];
      recMobile = (recMobile !== null && recMobile !== undefined &&
                   String(recMobile).trim() !== '')
                    ? normalizeMobile_(recMobile) : key;
      // clear + populate every value cell in a few batched writes
      applyValueCells_(uiSheet, ctx, function (f) {
        if (f.row === mc.row && f.col === mc.col) return recMobile;
        var val = rec.map[f.label.toLowerCase()];
        if (val !== null && val !== undefined && String(val) !== '') return val;
        // blank in the stored record: seed the tab default for Counselling By
        if (f.label.toLowerCase() === 'counselling by') return defaultCounsellingBy_(uiSheet);
        return '';
      });
      applyWalkInOverlay_(uiSheet, recMobile);   // pre-fill from Walk-In New (additive)
      return { ok: true, kind: 'success', title: 'Validation completed successfully.',
        message: 'Record found — you can edit the fields, then Submit.' };
    }
    // no record for this number: CLEAR every field first so the PREVIOUS lead's
    // data never remains on the form, keep the normalised mobile, seed the tab's
    // Counselling By default, then let the Walk-In overlay pre-fill if applicable.
    // (Same batched clear the "found" branch performs, but with no stored values.)
    applyValueCells_(uiSheet, ctx, function (f) {
      if (f.row === mc.row && f.col === mc.col) return key;               // keep the new mobile
      if (f.label.toLowerCase() === 'counselling by') return defaultCounsellingBy_(uiSheet);
      return '';                                                          // clear everything else
    });
    applyWalkInOverlay_(uiSheet, key);   // pre-fill from Walk-In New (additive)
    return { ok: true, kind: 'success', title: 'Validation completed successfully.',
      message: 'New number — enter the details, then Submit.' };
  } catch (e) {
    return { ok: false, kind: 'error', title: 'Validate failed',
      message: (e && e.message) ? e.message : String(e) };
  }
}

/** Core submit logic — runs inside the popup via google.script.run and
 *  RETURNS a small result object {ok, kind, title, message}. */
function runSubmit(uiSheetOverride) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
    var uiSheet = uiSheetOverride || pickFormSheet(ss);
    var ctx = getUiContext_(uiSheet);
    if (!ctx.mobileCell) {
      return { ok: false, kind: 'error', title: 'Setup issue',
        message: 'Could not find the "Mobile Number" field. Run "beautifyLeadForm" first.' };
    }
    var mc = ctx.mobileCell;
    // reuse the value already fetched by getUiContext_ (same committed state as a
    // live read) instead of a second single-cell round-trip to the sheet.
    var raw = (ctx.values[mc.row - 1] || [])[mc.col - 1];

    if (String(raw == null ? '' : raw).trim() === '') {
      return { ok: false, kind: 'warn', title: 'Mobile Number required',
        message: 'Enter a mobile number (press Enter after typing) before submitting.' };
    }
    if (!isValidIndianMobile_(raw)) {
      return { ok: false, kind: 'error', title: 'Invalid Mobile Number',
        message: 'Enter a valid 10-digit number starting 6-9 before submitting.' };
    }
    var key = normalizeMobile_(raw);

    // Build the record from the grid already in memory (no per-cell reads).
    var record = {};
    var ordered = ['Mobile Number'];
    ctx.fields.forEach(function (f) {
      var lab = f.label;
      if (lab.toLowerCase() === 'mobile number') { record[lab] = key; return; }
      if (ordered.indexOf(lab) === -1) ordered.push(lab);
      record[lab] = (ctx.values[f.row - 1] || [])[f.col - 1];
    });
    record['Mobile Number'] = key;

    // --- Candidate Type required unless Admission Status is exempt -----------
    // Business rule: Candidate Type must NOT be empty when the Admission Status
    // is anything other than "Irrelevant" or "Unable to Connect". Comparison is
    // trimmed, extra-space-collapsed, case-insensitive and blank/null-safe. When
    // it fails, submission is blocked (return before the record is saved) and the
    // popup shows the notification below. All other submit logic is unchanged.
    var _ltNorm = function (v) {
      return String(v == null ? '' : v).replace(/\s+/g, ' ').trim().toLowerCase();
    };
    var _ltByLabel = function (name) {
      var t = _ltNorm(name);
      for (var k in record) {
        if (record.hasOwnProperty(k) && _ltNorm(k) === t) return record[k];
      }
      return '';
    };
    var _admissionStatus = _ltNorm(_ltByLabel('Admission Status'));
    var _candidateType   = _ltNorm(_ltByLabel('Candidate Type'));
    var _CT_EXEMPT = ['irrelevant', 'unable to connect'];
    if (_candidateType === '' && _CT_EXEMPT.indexOf(_admissionStatus) === -1) {
      return { ok: false, kind: 'warn', title: 'Candidate Type required',
        message: 'Candidate Type is required for the selected Admission Status. ' +
                 'Please select a Candidate Type before submitting.' };
    }

    // --- Google Meet / Walk-In schedule DATE required when scheduled ----------
    // If IsGoogleMeetSchedule = Yes  -> IsGoogleMeetScheduleDate is mandatory.
    // If IsWalkInSchedule    = Yes  -> IsWalkInScheduleDate    is mandatory.
    // Only the value "Yes" makes the date mandatory (trimmed, case-insensitive,
    // blank/null-safe); any other value leaves the date optional. When the date
    // is missing, submission is blocked (return before the record is saved) and
    // the popup below is shown. All other submit logic is unchanged.
    var _isYes = function (v) { return _ltNorm(v) === 'yes'; };
    if (_isYes(_ltByLabel('IsGoogleMeetSchedule')) &&
        _ltNorm(_ltByLabel('IsGoogleMeetScheduleDate')) === '') {
      return { ok: false, kind: 'warn', title: 'Google Meet Schedule Date required',
        message: 'Please select the Google Meet Schedule Date.' };
    }
    if (_isYes(_ltByLabel('IsWalkInSchedule')) &&
        _ltNorm(_ltByLabel('IsWalkInScheduleDate')) === '') {
      return { ok: false, kind: 'warn', title: 'Walk-In Schedule Date required',
        message: 'Please select the Walk-In Schedule Date.' };
    }

    // stamp insert/update time (consistent IST date-time) on every submit
    record[TIMESTAMP_COL] = Utilities.formatDate(new Date(), TIMESTAMP_TZ, TIMESTAMP_FMT);
    if (ordered.indexOf(TIMESTAMP_COL) === -1) ordered.push(TIMESTAMP_COL);

    // --- record-level concurrency guard ------------------------------------
    // Lock ONLY this mobile number. Different numbers never block each other;
    // a second user trying to save the SAME number right now is asked to retry.
    var recLock = acquireRecordLock_(key);
    if (!recLock.ok) {
      return { ok: false, kind: 'warn', title: 'Record in use',
        message: 'This record is currently being updated by another user. ' +
                 'Please try again in a few moments.' };
    }
    var res;
    try {
      var dataSS = SpreadsheetApp.openById(DATA_ID);
      var dataSheet = getActiveDataSheet_(dataSS);            // latest records live here
      var inactiveSheet = getInactiveDataSheet_(dataSS);     // history (may be null)
      res = upsertRecord_(dataSheet, ordered, record, key, inactiveSheet);
      SpreadsheetApp.flush();            // commit before releasing the record lock
    } finally {
      releaseRecordLock_(recLock);
    }

    // success -> reset the form for the next entry (batched, input values only),
    // but KEEP the current "Counselling By" so the counsellor need not re-select
    // it. resetFormOnSheet_ is the same clear-except-Counselling-By core used by
    // the Reset checkbox (blanks every value cell, preserves the current
    // Counselling By, protects formulas).
    resetFormOnSheet_(uiSheet);
    try { uiSheet.getRange(mc.row, mc.col).activate(); } catch (ignore) {}

    return { ok: true, kind: 'success', title: 'Submission completed successfully.',
      message: (res.updated ? 'Record updated. ' : 'Record saved. ') +
               'Form cleared for the next entry.' };
  } catch (e) {
    return { ok: false, kind: 'error', title: 'Submit failed',
      message: (e && e.message) ? e.message : String(e) };
  }
}

// ---- styled processing / result popup ------------------------------------
/** Open the small modal popup that shows "…please wait", runs the operation,
 *  then swaps to a success / error card that auto-closes. */
function showOpDialog_(mode) {
  var html = HtmlService.createHtmlOutput(buildOpDialogHtml_(mode))
    .setWidth(300).setHeight(196);
  SpreadsheetApp.getUi().showModalDialog(html, 'IntelliBI');
}

/** Build the self-contained popup HTML for a given mode ('validate'|'submit'). */
function buildOpDialogHtml_(mode) {
  var isSubmit = (mode === 'submit');
  var proc = isSubmit ? 'Submitting… Please wait.' : 'Validating… Please wait.';
  var fn = isSubmit ? 'runSubmit' : 'runValidate';
  return [
'<!DOCTYPE html><html><head><meta charset="utf-8"><base target="_top"><style>',
'*{box-sizing:border-box;}',
'html,body{margin:0;padding:0;height:100%;background:#fff;',
'  font-family:Poppins,"Segoe UI",Roboto,Arial,sans-serif;}',
'.wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;',
'  height:100%;min-height:150px;padding:14px 16px;text-align:center;}',
'.spin{width:34px;height:34px;border-radius:50%;border:3px solid #E3EAF2;',
'  border-top-color:#1F6FB2;animation:sp .8s linear infinite;margin-bottom:11px;}',
'@keyframes sp{to{transform:rotate(360deg);}}',
'.ptext{color:#33475b;font-size:13px;font-weight:600;}',
'.icon{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;',
'  justify-content:center;font-size:25px;color:#fff;margin-bottom:9px;',
'  box-shadow:0 3px 10px rgba(0,0,0,.15);animation:pop .28s ease;}',
'@keyframes pop{0%{transform:scale(.4);opacity:0;}100%{transform:scale(1);opacity:1;}}',
'.title{font-size:13.5px;font-weight:700;color:#0F2D4A;margin:0 0 4px;',
'  max-width:256px;line-height:1.3;word-wrap:break-word;}',
'.msg{font-size:11.5px;color:#5a6a7a;line-height:1.4;margin-bottom:12px;max-width:256px;}',
'.ok{border:none;border-radius:7px;padding:6px 20px;font-size:12px;font-weight:600;',
'  color:#fff;cursor:pointer;font-family:inherit;box-shadow:0 2px 7px rgba(0,0,0,.15);}',
'.ok:hover{filter:brightness(1.07);}',
'</style></head><body>',
'<div class="wrap" id="wrap">',
'  <div class="spin"></div>',
'  <div class="ptext">' + proc + '</div>',
'</div>',
'<script>',
'var FN="' + fn + '";',
'function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}',
'function col(k){return k==="success"?"#1E9E5A":k==="info"?"#1F6FB2":k==="warn"?"#C77700":"#C0392B";}',
'function ico(k){return k==="warn"?"!":k==="error"?"\\u2715":"\\u2713";}',
'function done(r){r=r||{};var k=r.kind||"success";var c=col(k);',
'  document.getElementById("wrap").innerHTML=',
'    \'<div class="icon" style="background:\'+c+\'">\'+ico(k)+\'</div>\'+',
'    \'<div class="title">\'+esc(r.title)+\'</div>\'+',
'    \'<div class="msg">\'+esc(r.message)+\'</div>\'+',
'    \'<button class="ok" style="background:\'+c+\'" onclick="bye()">OK</button>\';',
'  var ms=(k==="success"||k==="info")?2400:6000;',
'  window.__t=setTimeout(bye,ms);}',
'function bye(){try{clearTimeout(window.__t);}catch(e){}google.script.host.close();}',
'function run(){google.script.run.withSuccessHandler(done).withFailureHandler(function(e){',
'  done({ok:false,kind:"error",title:"Something went wrong",',
'        message:(e&&e.message)?e.message:String(e)});})[FN]();}',
'window.addEventListener("load",run);',
'</script></body></html>'
  ].join('\n');
}

// ---- UI context / field mapping ------------------------------------------
/**
 * Map the UI sheet's fields to their value cells (header/label based).
 * Returns { fields:[{label,row,col}], mobileCell:{row,col}, ... }.
 *   - contact block: labels in the "Mobile Number" header row, values in the
 *     row directly below (Mobile | Full Name | Email Address).
 *   - form table: "Column Name | value | Column Name | value" pairs, i.e.
 *     label in col A -> value col B, label in col C -> value col D.
 */
function getUiContext_(uiSheet) {
  var values = uiSheet.getDataRange().getValues();
  var nRows = values.length;
  var lastCol = 4;
  for (var r = 0; r < nRows; r++) {
    for (var c = values[r].length - 1; c >= 0; c--) {
      if (String(values[r][c]).trim() !== '') { if (c + 1 > lastCol) lastCol = c + 1; break; }
    }
  }
  var lastRow = 0;
  for (var rr = 0; rr < nRows; rr++) {
    for (var cc = 0; cc < values[rr].length; cc++) {
      if (String(values[rr][cc]).trim() !== '') { lastRow = rr + 1; break; }
    }
  }
  function rowOf(text) {
    for (var i = 0; i < nRows; i++) {
      if (String(values[i][0]).trim().toLowerCase() === text) return i + 1;
    }
    return -1;
  }
  var contactRow = rowOf('mobile number');
  var headerRow  = rowOf('column name');
  var inputRow   = contactRow > 0 ? contactRow + 1 : -1;

  var fields = [];
  var mobileCell = null;

  // contact block (values sit one row below the labels)
  if (contactRow > 0) {
    for (var c1 = 1; c1 <= lastCol; c1++) {
      var lab = cleanLabel_(values[contactRow - 1][c1 - 1]);
      if (lab) {
        fields.push({ label: lab, row: inputRow, col: c1 });
        if (lab.toLowerCase() === 'mobile number') mobileCell = { row: inputRow, col: c1 };
      }
    }
  }

  // form table pairs (start just below the "Column Name" header row)
  if (headerRow > 0) {
    for (var ri = headerRow; ri < nRows; ri++) {   // ri is 0-based -> body rows
      var labA = cleanLabel_(values[ri][0]);
      var labC = lastCol >= 3 ? cleanLabel_(values[ri][2]) : '';
      if (labA && labA.toLowerCase() !== 'column name') {
        fields.push({ label: labA, row: ri + 1, col: 2 });
      }
      if (labC && labC.toLowerCase() !== 'column name') {
        fields.push({ label: labC, row: ri + 1, col: 4 });
      }
    }
  }
  return { values: values, lastCol: lastCol, lastRow: lastRow,
           contactRow: contactRow, inputRow: inputRow, headerRow: headerRow,
           fields: fields, mobileCell: mobileCell };
}

/**
 * Write value cells in as FEW Sheet calls as possible (batched by column),
 * instead of one getRange().setValue() per cell.
 *   provider(field) -> string to write for that field's value cell.
 *   fmuls (optional) -> a getFormulas() grid; when supplied, any value cell
 *     that currently holds a formula is left intact (its formula is re-written).
 * Non-value cells (labels) are never touched. Typically 3-4 API writes total.
 */
function applyValueCells_(uiSheet, ctx, provider, fmuls) {
  var v = ctx.values, lastCol = ctx.lastCol;
  var inputRow = ctx.inputRow, headerRow = ctx.headerRow, lastRow = ctx.lastRow;
  var fmap = {};
  ctx.fields.forEach(function (f) { fmap[f.row + ',' + f.col] = f; });

  function cur(r, c) { return (v[r - 1] && v[r - 1][c - 1] != null) ? v[r - 1][c - 1] : ''; }
  function resolve(r, c) {
    var f = fmap[r + ',' + c];
    if (!f) return { write: false };
    if (fmuls) {
      var fm = (fmuls[r - 1] && fmuls[r - 1][c - 1]) || '';
      if (fm !== '') return { write: true, value: fm };   // keep formula intact
    }
    return { write: true, value: provider(f) };
  }

  // contact input row: A,B in one call; C (merged Email) on its own
  if (inputRow > 0) {
    var w = Math.min(2, lastCol), rowArr = [];
    for (var c = 1; c <= w; c++) { var rz = resolve(inputRow, c); rowArr.push(rz.write ? rz.value : cur(inputRow, c)); }
    uiSheet.getRange(inputRow, 1, 1, w).setValues([rowArr]);
    if (lastCol >= 3) { var r3 = resolve(inputRow, 3); if (r3.write) uiSheet.getRange(inputRow, 3).setValue(r3.value); }
  }

  // form-table value columns B (2) and D (4): one setValues() per column
  var body0 = headerRow + 1;
  if (headerRow > 0 && lastRow >= body0) {
    var n = lastRow - body0 + 1;
    [2, 4].forEach(function (col) {
      if (col > lastCol) return;
      var arr = [];
      for (var r = body0; r <= lastRow; r++) {
        var rz2 = resolve(r, col);
        arr.push([rz2.write ? rz2.value : cur(r, col)]);
      }
      uiSheet.getRange(body0, col, n, 1).setValues(arr);
    });
  }
}

/**
 * Reset the form after a successful Submit: blanks ONLY the user-input value
 * cells (including the Mobile Number box), so the sheet is ready for the next
 * entry. Batched (a few setValues calls). Data-validation dropdowns and cell
 * formatting are preserved (only the value is cleared), and any cell holding a
 * formula is left intact. Static labels are never in the value-cell set.
 */
function resetInputFields_(uiSheet, ctx) {
  var fmuls = uiSheet.getDataRange().getFormulas();     // 1 read -> protect formulas
  applyValueCells_(uiSheet, ctx, function () { return ''; }, fmuls);
  setCounsellingByDefault_(uiSheet, ctx, false);        // re-seed the tab's default
}

/**
 * Reset button (menu: "Reset Form", or assign a drawing to resetForm).
 * Clears every entered/loaded value in the form EXCEPT "Counselling By", which
 * is kept exactly as it currently is so the counsellor does not have to select
 * it again. Uses the SAME sheet + field mapping + batched writer as Validate/
 * Save, so nothing about those flows, the mappings, or any other logic changes.
 * Dropdowns, cell formatting and any formula cells are preserved (only values
 * are cleared). The Mobile Number box and all other fields are blanked.
 */
function resetForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
  var uiSheet = pickFormSheet(ss);
  // Running this straight from the Apps Script editor has no "active tab", so
  // guard clearly instead of failing on a non-form sheet. In normal use the
  // "TICK TO RESET" checkbox (below) is what counsellors click — no manual run.
  if (!uiSheet || !sheetIsForm_(uiSheet)) {
    try {
      ss.toast('Open a counsellor lead-form tab, then click Reset (or tick "TICK TO RESET").',
               'IntelliBI', 6);
    } catch (e) {}
    return;
  }
  resetFormOnSheet_(uiSheet);
  try {
    ss.toast('Form cleared. Counselling By kept unchanged.', 'IntelliBI', 4);
  } catch (ignore) {}
}

/**
 * Core reset used by BOTH resetForm() (menu / manual) and the "TICK TO RESET"
 * checkbox: on the given form sheet, clear every entered/loaded value EXCEPT the
 * "Counselling By" field, which is kept exactly as-is. Uses the same field
 * mapping + batched writer as Validate/Save; dropdowns, formatting and any
 * formula cells are preserved (only values are cleared).
 */
function resetFormOnSheet_(uiSheet) {
  var ctx = getUiContext_(uiSheet);
  var fmuls = uiSheet.getDataRange().getFormulas();     // 1 read -> protect formulas
  applyValueCells_(uiSheet, ctx, function (f) {
    if (String(f.label).trim().toLowerCase() === 'counselling by') {
      var row = ctx.values[f.row - 1];
      return (row && row[f.col - 1] != null) ? row[f.col - 1] : '';
    }
    return '';
  }, fmuls);
}

// ---- Data sheet read / upsert --------------------------------------------
// ---- fast lookup infrastructure (scales to millions of rows) --------------
// The old code pulled the ENTIRE sheet into memory (getDataRange().getValues())
// on every Validate/Submit — O(rows x cols) transfer. Instead we:
//   * read only the 1-row header,
//   * find the matching row with a server-side TextFinder on the Mobile Number
//     column (no bulk data transfer), backed by a per-mobile CacheService index
//     for instant repeat lookups,
//   * then read/write ONLY that single row.
// Net: a Validate/Submit costs a small, constant number of API calls regardless
// of how many rows the sheet holds.

/** Header names (cleaned) + column count, from row 1 only. */
function readHeaders_(sheet) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < 1) return { headers: [], lastCol: 0 };
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0]
                     .map(function (h) { return cleanLabel_(h); });
  return { headers: headers, lastCol: lastCol };
}

function _rowCacheKey_(sheet, key) {
  return 'AROW_' + sheet.getSheetId() + '_' + key;
}

/**
 * Row number (>=2) of the record whose Mobile Number == key, or -1.
 * Cache-first (verified), then a column-scoped TextFinder. No full-sheet read.
 */
function findRowByMobile_(sheet, mobileCol1, key) {
  var cache = CacheService.getScriptCache();
  var ck = _rowCacheKey_(sheet, key);
  var cached = cache.get(ck);
  if (cached) {
    var rn = parseInt(cached, 10);
    if (rn >= 2 && rn <= sheet.getLastRow()) {
      var v = sheet.getRange(rn, mobileCol1).getValue();
      if (normalizeMobile_(v) === key) return rn;    // verified hit
    }
    cache.remove(ck);                                 // stale -> drop
  }
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return -1;
  var finder = sheet.getRange(2, mobileCol1, lastRow - 1, 1)
                    .createTextFinder(key).matchEntireCell(true).useRegularExpression(false);
  var hit = finder.findNext();
  if (hit) {
    var row = hit.getRow();
    try { cache.put(ck, String(row), 21600); } catch (e) {}   // 6h
    return row;
  }
  return -1;
}

function _cacheRow_(sheet, key, row) {
  try { CacheService.getScriptCache().put(_rowCacheKey_(sheet, key), String(row), 21600); } catch (e) {}
}

/**
 * Column index (0-based) of the "Alternative Mobile Number" field in a header
 * row, or -1 if the sheet has no such column. Tolerant of minor naming so the
 * lookup still works whether the column is titled "Alternative Mobile Number",
 * "Alternate Mobile Number", "Alt Mobile Number", etc. Uses the same cleaned /
 * lower-cased comparison as everywhere else (headerIndex_).
 */
function altMobileColIndex_(headers) {
  var candidates = ['alternative mobile number', 'alternate mobile number',
                    'alternative mobile no', 'alternate mobile no',
                    'alt mobile number', 'alt mobile no',
                    'alternative mobile', 'alternate mobile',
                    'alternative contact number', 'alternate contact number',
                    'alternative number', 'alternate number'];
  for (var i = 0; i < candidates.length; i++) {
    var idx = headerIndex_(headers, candidates[i]);
    if (idx >= 0) return idx;
  }
  return -1;
}

/**
 * Row number (>=2) of the record whose ALTERNATIVE Mobile Number == key, or -1.
 * Used ONLY as a fallback when the primary Mobile Number lookup misses.
 *
 * Fast + robust to formatting: the Alternative Mobile Number is entered free-form
 * on the form (it is NOT normalised on save), so a stored value may carry a +91,
 * a leading 0, spaces, hyphens or brackets. We use a server-side regex TextFinder
 * whose pattern is the key's digits separated by "\D*" (any run of non-digits),
 * so "9000000001" also matches "+91 90000-00001", "0 9000000001", "(9000)000001",
 * etc. — anywhere in the cell. Matches are normally none or one; each candidate is
 * then confirmed by exact NORMALISED equality, so a longer number that merely
 * contains the key can never be mistaken for a real match. No full-sheet read:
 * the finder runs server-side and only the (few) matched cells are inspected.
 */
function findRowByAltMobile_(sheet, altCol1, key) {
  if (!key || altCol1 < 1) return -1;
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return -1;
  // key is all digits (it came from normalizeMobile_), so nothing to escape.
  var pattern = String(key).split('').join('\\D*');
  var matches = sheet.getRange(2, altCol1, lastRow - 1, 1)
                     .createTextFinder(pattern).matchEntireCell(false)
                     .useRegularExpression(true).findAll();
  for (var i = 0; i < matches.length; i++) {
    if (normalizeMobile_(matches[i].getValue()) === key) return matches[i].getRow();
  }
  return -1;
}

/** Find one record by mobile (Validate). Reads only the header + the one row.
 *  Primary key is the Mobile Number; if that misses, the Alternative Mobile
 *  Number column is tried as a fallback (see findRowByAltMobile_). */
function findRecord_(dataSheet, key) {
  var hdr = readHeaders_(dataSheet);
  if (!hdr.lastCol) return { found: false, map: {}, headers: [], rowIndex: -1 };
  var mCol0 = headerIndex_(hdr.headers, 'mobile number');
  if (mCol0 < 0) return { found: false, map: {}, headers: hdr.headers, rowIndex: -1 };
  var row = findRowByMobile_(dataSheet, mCol0 + 1, key);
  if (row < 0) {
    // Primary Mobile Number miss -> try the Alternative Mobile Number column.
    // This runs ONLY on a miss (a new number, or a deliberate search by an alt
    // number), so the common "existing primary mobile" search is completely
    // unchanged and pays nothing extra. The fallback is itself a server-side
    // TextFinder (no full-sheet read), so even a new-number search adds just one
    // cheap finder call regardless of how many rows the sheet holds.
    var aCol0 = altMobileColIndex_(hdr.headers);
    if (aCol0 >= 0) row = findRowByAltMobile_(dataSheet, aCol0 + 1, key);
  }
  if (row < 0) return { found: false, map: {}, headers: hdr.headers, rowIndex: -1 };
  var vals = dataSheet.getRange(row, 1, 1, hdr.lastCol).getValues()[0];
  var map = {};
  for (var c = 0; c < hdr.headers.length; c++) map[hdr.headers[c].toLowerCase()] = vals[c];
  return { found: true, map: map, headers: hdr.headers, rowIndex: row };
}

function upsertRecord_(dataSheet, ordered, record, key, inactiveSheet) {
  // Header from row 1 only; row located via TextFinder/cache; single-row I/O.
  var empty = (dataSheet.getLastRow() === 0);
  var headers, needHeader = false;

  if (empty) {                                      // no header yet -> create it
    headers = ordered.slice();
    needHeader = true;
  } else {
    headers = readHeaders_(dataSheet).headers;
    ordered.forEach(function (lab) {
      if (headerIndex_(headers, lab) < 0) { headers.push(lab); needHeader = true; }
    });
  }
  if (needHeader) writeHeaders_(dataSheet, headers);

  function rowArray() {
    return headers.map(function (h) {
      var hl = h.toLowerCase(), val = '';
      for (var k in record) { if (k.toLowerCase() === hl) { val = record[k]; break; } }
      return val;
    });
  }

  var mCol0 = headerIndex_(headers, 'mobile number');
  var foundRow = empty ? -1 : findRowByMobile_(dataSheet, mCol0 + 1, key);

  if (foundRow > 0) {
    // UPDATE: archive the current (old) Active row to InActive FIRST (reading
    // just that one row), then overwrite it with the latest values.
    var oldVals = dataSheet.getRange(foundRow, 1, 1, headers.length).getValues()[0];
    try { archiveToInactive_(inactiveSheet, headers, oldVals, key); } catch (e) {}
    dataSheet.getRange(foundRow, 1, 1, headers.length).setValues([rowArray()]);
    _cacheRow_(dataSheet, key, foundRow);
    return { updated: true };
  }
  // INSERT: new record -> Active only (no InActive entry).
  dataSheet.appendRow(rowArray());
  _cacheRow_(dataSheet, key, dataSheet.getLastRow());
  return { updated: false };
}

function writeHeaders_(dataSheet, headers) {
  dataSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  dataSheet.getRange(1, 1, 1, headers.length)
           .setFontWeight('bold').setFontColor(WHITE).setBackground(ACCENT);
  dataSheet.setFrozenRows(1);
}

// ---- per-record (per mobile number) lock ---------------------------------
/**
 * Acquire a short-lived lock for ONE mobile number, so two users can't update
 * the SAME record at the same moment. Different numbers are never blocked.
 *
 * Coordination uses the script cache (shared across everyone working in this
 * one script project) plus a very brief script lock — held only for the tiny
 * check-and-set, NOT for the sheet write — so throughput stays parallel.
 * The lock auto-expires after 40s in case a run dies mid-write.
 *
 * NOTE: this shares state only within a single Apps Script project (i.e. one
 * spreadsheet / one bound script, even with a tab per counsellor). Separate
 * spreadsheet copies are separate projects and would need a shared Web App.
 *
 * Returns { ok:true, cacheKey, token } on success, or { ok:false }.
 */
function acquireRecordLock_(key) {
  var cache = CacheService.getScriptCache();
  var cacheKey = 'REC_LOCK_' + key;
  var guard = LockService.getScriptLock();
  try { guard.waitLock(5000); } catch (e) { return { ok: false }; }
  try {
    if (cache.get(cacheKey)) return { ok: false };     // this record is in use
    var token = Utilities.getUuid();
    cache.put(cacheKey, token, 40);                     // TTL 40s (auto-release)
    return { ok: true, cacheKey: cacheKey, token: token };
  } finally {
    guard.releaseLock();
  }
}

/** Release a record lock (best-effort; only if it is still ours). */
function releaseRecordLock_(recLock) {
  if (!recLock || !recLock.ok) return;
  try {
    var cache = CacheService.getScriptCache();
    if (cache.get(recLock.cacheKey) === recLock.token) cache.remove(recLock.cacheKey);
  } catch (e) {}
}

// ---- small helpers --------------------------------------------------------
/** Trim + drop a trailing colon so "IsWalkInSchedule:" -> "IsWalkInSchedule". */
function cleanLabel_(v) {
  return String(v == null ? '' : v).trim().replace(/:\s*$/, '').trim();
}

function headerIndex_(headers, name) {
  var n = String(name).trim().toLowerCase();
  for (var i = 0; i < headers.length; i++) {
    if (String(headers[i]).trim().toLowerCase() === n) return i;
  }
  return -1;
}

/** Reduce any Indian mobile input to its bare 10 digits (strip +91 / 0 / spaces). */
function normalizeMobile_(v) {
  var d = String(v == null ? '' : v).replace(/\D/g, '');
  if (d.length === 13 && d.substring(0, 3) === '910') d = d.substring(3);
  else if (d.length === 12 && d.substring(0, 2) === '91') d = d.substring(2);
  else if (d.length === 11 && d.charAt(0) === '0') d = d.substring(1);
  return d;
}

/** Valid Indian mobile = 10 digits, first digit 6-9 (after normalisation). */
function isValidIndianMobile_(v) {
  return /^[6-9]\d{9}$/.test(normalizeMobile_(v));
}


// ===========================================================================
//  Walk-In New auto-populate  (ADDITIVE - runs at the end of Validate only)
//  After the existing Validate logic finishes, look the SAME normalised mobile
//  up in the "Walk-In New" tab and pre-fill the mapped counselling fields, but
//  ONLY where the Walk-In record actually holds a value. A blank / missing
//  Walk-In value never overwrites what is already in the form. Counselling By
//  and every "Not Applicable" field are never touched here. The whole thing is
//  best-effort and self-guarded, so a Walk-In read issue can never break or
//  slow the existing Validate/Submit flow.
// ===========================================================================
var WALKIN_SHEET_ID = '19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ';
var WALKIN_NEW_TAB  = 'Walk-In New';

// form-field label (any spelling) <- Walk-In New source column (any spelling).
// derive:'referral' converts the hear-about answer into Yes / No.
var WALKIN_FIELD_MAP = [
  { form: ['candidate type'],                                walk: ['Current Status', 'Candidate Type'] },
  { form: ['total years of experience'],                     walk: ['Total Years of Experience', 'Experience'] },
  { form: ['current domain / technology', 'current domain/technology'],
                                                             walk: ['Current Domain / Technology', 'Current Domain/Technology'] },
  { form: ['course interested in'],                          walk: ['Which technology are you interested in learning?'] },
  { form: ['career goal'],                                   walk: ['What is your primary goal?'] },
  { form: ['current company name'],                          walk: ['Current Company Name'] },
  { form: ['current city'],                                  walk: ['Current City', 'City'] },
  { form: ['current area / locality', 'current area/locality'],
                                                             walk: ['Current Area / Locality', 'Current Area/Locality'] },
  { form: ['highest qualification'],                         walk: ['Highest Qualification'] },
  { form: ['graduation / passing year', 'graduation/passing year'],
                                                             walk: ['Graduation / Passing Year', 'Graduation/Passing Year'] },
  { form: ['is referral', 'isreferral'],
    walk: ['How did you hear about IntelliBI?', 'How did you hear about IntelliBI'], derive: 'referral' },
  { form: ["referrer's name", 'referrers name', 'referrer name'],
                                                             walk: ["Referrer's Name", 'Referrers Name', 'Referrer Name'] },
  { form: ['admission plan time'],                           walk: ['When are you planning to take admission?', 'Admission Plan Time'] },
  { form: ['counsellor notes', 'counselor notes'],           walk: ['Remarks'] },
  { form: ['backoutreason', 'back out reason'],              walk: ['BackOutReason', 'Back Out Reason'] }
];

// Per-field value translation for EXISTING Walk-In records whose wording differs
// from the counselling form's dropdown. Keys are normalised via _wiOpt_
// (dash / space / case-insensitive). Going forward the Walk-In form stores the
// exact dropdown text, which needs no entry here (it matches the dropdown
// directly). Values are the exact dropdown options.
var WALKIN_VALUE_MAP = {
  'total years of experience': {
    '0-2 years':  '1–2 Years',
    '2-4 years':  '2–3 Years',
    '2-5 years':  '3–5 Years',
    '5-8 years':  '5–7 Years',
    '8-10 years': '7–10 Years',
    '10+ years':  '10–15 Years'
  }
};

/** Translate a raw Walk-In value to the form's wording for a given field label
 *  when a mapping exists; otherwise return it unchanged (exact / future values
 *  pass straight through to the dropdown match). */
function _wiTranslate_(labelNorm, val) {
  var t = WALKIN_VALUE_MAP[labelNorm];
  if (!t) return val;
  var k = _wiOpt_(val);
  return t.hasOwnProperty(k) ? t[k] : val;
}

/** Normalise a label / header for tolerant comparison. */
function _wiNorm_(s) {
  return String(s == null ? '' : s).replace(/\s+/g, ' ').replace(/:\s*$/, '').trim().toLowerCase();
}

/**
 * Look one lead up in the "Walk-In New" tab by normalised mobile. Reads only the
 * header, the mobile column and the single matched row, so it stays fast at any
 * size. Returns { found, get(candidates) }; get() yields the trimmed value of the
 * first matching source column. Picks the LAST matching row (latest walk-in).
 */
function walkInLookup_(key) {
  var out = { found: false, get: function () { return ''; } };
  if (!key) return out;
  var ss, sh;
  try { ss = SpreadsheetApp.openById(WALKIN_SHEET_ID); } catch (e) { return out; }
  sh = ss.getSheetByName(WALKIN_NEW_TAB);
  if (!sh) return out;
  var lastRow = sh.getLastRow(), lastCol = sh.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return out;
  var header = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(_wiNorm_);
  function col(cands) {
    for (var i = 0; i < cands.length; i++) {
      var idx = header.indexOf(_wiNorm_(cands[i]));
      if (idx >= 0) return idx;
    }
    return -1;
  }
  var cMob = col(['Mobile Number', 'Mobile', 'Phone Number', 'Phone', 'Contact Number', 'Contact']);
  if (cMob < 0) return out;
  var mobVals = sh.getRange(2, cMob + 1, lastRow - 1, 1).getValues();
  var matchRow = -1;
  for (var r = 0; r < mobVals.length; r++) {
    if (normalizeMobile_(mobVals[r][0]) === key) matchRow = r;   // keep last (latest)
  }
  if (matchRow < 0) return out;
  var rowVals = sh.getRange(matchRow + 2, 1, 1, lastCol).getValues()[0];
  out.found = true;
  out.get = function (cands) {
    var i = col(cands);
    return i >= 0 ? String(rowVals[i] == null ? '' : rowVals[i]).trim() : '';
  };
  return out;
}

/**
 * Overlay the mapped Walk-In New values onto the form AFTER the normal Validate
 * population. Writes ONLY the fields for which the Walk-In record actually has a
 * value; every other cell is rewritten with its current value (formulas kept
 * intact), so nothing existing is cleared. Counselling By and the N/A fields are
 * never in the map, so they are left exactly as the existing Validate left them.
 * Best-effort: any error is swallowed so the existing Validate result stands.
 */
/** Normalise a dropdown option / value for tolerant comparison (unifies the
 *  various dash characters and whitespace). */
function _wiOpt_(s) {
  return String(s == null ? '' : s)
           .replace(/[‐-―−]/g, '-')   // hyphen/en/em/minus -> '-'
           .replace(/\s+/g, ' ').trim().toLowerCase();
}

/** Allowed values for a require-value-in-list / -range validation, else null
 *  (null => the cell has no fixed option list; write is attempted, guarded). */
function _wiValidationOptions_(dv) {
  try {
    var t = dv.getCriteriaType();
    var cv = dv.getCriteriaValues();
    if (t === SpreadsheetApp.DataValidationCriteria.VALUE_IN_LIST) {
      return cv[0] || [];
    }
    if (t === SpreadsheetApp.DataValidationCriteria.VALUE_IN_RANGE) {
      var rng = cv[0], flat = [];
      if (rng && rng.getValues) {
        rng.getValues().forEach(function (row) {
          row.forEach(function (c) { if (String(c).trim() !== '') flat.push(c); });
        });
      }
      return flat;
    }
  } catch (e) {}
  return null;
}

/**
 * Overlay the mapped Walk-In New values onto the form AFTER the normal Validate
 * population. Writes each mapped field individually and ONLY when the Walk-In
 * record has a value for it. If the target cell has a dropdown / value-in-list
 * (or -range) validation, the value is written only when it matches an allowed
 * option (dash/space-tolerant, writing the exact option); otherwise that field
 * is skipped and left exactly as-is — so a Walk-In value in a different format
 * can never trip the cell's data validation. Counselling By and the N/A fields
 * are never in the map. Every write is guarded and the whole thing is
 * best-effort, so it can never break or slow the existing Validate.
 */
function applyWalkInOverlay_(uiSheet, key) {
  try {
    var lk = walkInLookup_(key);
    if (!lk.found) return;

    var ovByLabel = {};
    WALKIN_FIELD_MAP.forEach(function (m) {
      var val;
      if (m.derive === 'referral') {
        var hear = lk.get(m.walk);
        if (hear === '') return;                       // source unavailable -> leave as-is
        val = (_wiNorm_(hear) === 'friend / referral') ? 'Yes' : 'No';
      } else {
        val = lk.get(m.walk);
        if (val === '' || val == null) return;         // unavailable -> leave as-is
      }
      m.form.forEach(function (lbl) {
        var ln = _wiNorm_(lbl);
        ovByLabel[ln] = _wiTranslate_(ln, val);
      });
    });

    var fresh = getUiContext_(uiSheet);
    var dvs;
    try { dvs = uiSheet.getDataRange().getDataValidations(); } catch (e) { dvs = null; }

    fresh.fields.forEach(function (f) {
      var ll = _wiNorm_(f.label);
      if (!ovByLabel.hasOwnProperty(ll)) return;
      var value = ovByLabel[ll];

      var dv = (dvs && dvs[f.row - 1]) ? dvs[f.row - 1][f.col - 1] : null;
      if (dv) {
        var opts = _wiValidationOptions_(dv);
        if (opts && opts.length) {
          var want = _wiOpt_(value), canon = null;
          for (var i = 0; i < opts.length; i++) {
            if (_wiOpt_(opts[i]) === want) { canon = opts[i]; break; }
          }
          if (canon === null) return;                  // not an allowed option -> skip field
          value = canon;                               // write the exact allowed option
        }
      }
      try { uiSheet.getRange(f.row, f.col).setValue(value); } catch (e2) { /* rejected -> skip */ }
    });
  } catch (e) {
    // best-effort; never disturb the existing Validate
  }
}