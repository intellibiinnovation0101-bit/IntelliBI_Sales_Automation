/**
 * WalkInNewProtection.gs
 * =========================================================================
 * Manual-edit restrictions for the "Student Inquiry Tracker" workbook
 * (19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ), using real Google Sheets
 * protected ranges — not formatting.
 *
 *   Walk-In New   Counsellors / regular editors may edit ONLY the counsellor
 *                 columns (WIP_COUNSELLOR_EDITABLE), from row 2 down. The header
 *                 row, every form column, the two system columns (Lead
 *                 Interaction History, Conversion Chance %) and any other column
 *                 are read-only for them.
 *   Every other   Completely read-only for regular editors (all rows and columns;
 *   tab           they cannot edit, clear, insert or delete rows/columns, rename,
 *                 or delete the tab). They can still view it.
 *
 * Who keeps full write access (the protection's editors):
 *   - the spreadsheet owner (always — Google never restricts the owner);
 *   - every account in WIP_FULL_CONTROL (admins + the account that installed the
 *     WalkInNewAutoPopulate.gs triggers, which write Lead Interaction History and
 *     Conversion Chance % — installable triggers run AS that account);
 *   - the account running this script;
 *   - per-tab integration accounts in WIP_TAB_EXTRA_EDITORS.
 *   Google Form submissions are never blocked by protection.
 *
 * Header-name based: the counsellor columns are found by their header text every
 * time the rules are applied (trimmed, spaces collapsed, case-insensitive), so a
 * moved column keeps the right rule. If any counsellor header is missing or
 * duplicated, NOTHING is changed and the run fails loudly (so a counsellor column
 * is never accidentally locked or a wrong one unlocked).
 *
 * Nothing else is touched: no values, formulas, data validation, formatting,
 * triggers or the WalkInNewAutoPopulate.gs logic. (Exception: if Walk-In New is
 * close to running out of rows, blank rows are added at the bottom so new form
 * rows stay inside the counsellor-editable range — see WIP_ROW_BUFFER.)
 *
 * SETUP (once, by the spreadsheet OWNER, in the SAME Apps Script project as
 * WalkInNewAutoPopulate.gs):  Extensions → Apps Script → add this file, then run
 *   1. auditWalkInWorkbook()            read-only: tabs, forms, existing protections
 *   2. applyWorkbookProtection()        applies + verifies the rules
 *   3. setupWorkbookProtectionTriggers() daily re-apply + form-submit coverage check
 * Anytime: verifyWorkbookProtection() (read-only check).
 * =========================================================================
 */

// ── CONFIG ────────────────────────────────────────────────────────────────
var WIP_SPREADSHEET_ID = '19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ';
var WIP_WALKIN_TAB     = 'Walk-In New';
var WIP_DESCRIPTION    = 'IntelliBI access rules (managed by WalkInNewProtection.gs)';

// Walk-In New: the ONLY columns counsellors may edit (by header text).
var WIP_COUNSELLOR_EDITABLE = [
  'Remarks', 'Lead Status', 'Admission Status', 'Counselling By',
  'Tech Counselling By', 'ScheduledOrDirectWalkIn', 'Next Follow-Up Date',
  'BackOutReason'];

// Walk-In New: written by WalkInNewAutoPopulate.gs — read-only for counsellors.
var WIP_SYSTEM_MANAGED = ['Lead Interaction History', 'Conversion Chance %'];

// Walk-In New: form-submitted columns — read-only for counsellors. Used for the
// audit / verification report (everything not editable is protected anyway).
var WIP_FORM_COLUMNS = [
  'Timestamp', 'Full Name', 'Email Address', 'Mobile Number', 'Current City',
  'Current Area / Locality', 'Preferred Contact Method', 'Highest Qualification',
  'Graduation / Passing Year', 'College / University Name',
  'Grade / Percentage / CGPA', 'Current Status', 'Current Company Name',
  'Total Years of Experience', 'Current Domain / Technology',
  'Which technology are you interested in learning?', 'What is your primary goal?',
  'How did you hear about IntelliBI?', "Referrer's Name", 'Preferred Learning Mode',
  'Preferred Batch Timing', 'When are you planning to take admission?'];

// Accounts that keep FULL write access on every tab (besides the owner).
// MUST include the account that installed the WalkInNewAutoPopulate.gs triggers.
var WIP_FULL_CONTROL = ['info@intellibiinnovationstechnologies.in'];

// Extra write access for ONE tab (e.g. an integration account that appends rows):
//   { 'Meta Lead': ['integration@example.com'] }
var WIP_TAB_EXTRA_EDITORS = {};

// Keep at least this many blank rows below the last Walk-In New row inside the
// counsellor-editable range, so the next form rows are editable at once.
// 0 = never add rows (the form-submit hook then re-applies as rows arrive).
var WIP_ROW_BUFFER = 300;
// Trigger handlers of WalkInNewAutoPopulate.gs (they write the two system columns).
var WIP_AUTOPOPULATE_HANDLERS = ['onWalkInEdit', 'onWalkInFormSubmit', 'onWalkInDailySync'];
// Hour (script time zone) of the daily re-apply — before the 6 AM onWalkInDailySync.
var WIP_DAILY_HOUR = 5;
// Re-apply from the form-submit hook when the new row is this close to the end.
var WIP_REAPPLY_MARGIN = 50;


// ── HELPERS (WIP-prefixed: this project also holds WalkInNewAutoPopulate.gs) ─
function wipNorm_(v) {
  return String(v === null || v === undefined ? '' : v)
    .replace(/[ \s]+/g, ' ').trim().toLowerCase();
}
function wipEmail_(u) {
  if (!u) return '';
  var e = (typeof u === 'string') ? u : (u.getEmail ? u.getEmail() : '');
  return String(e || '').trim().toLowerCase();
}
function wipUnique_(arr) {
  var seen = {}, out = [];
  for (var i = 0; i < arr.length; i++) {
    var e = wipEmail_(arr[i]);
    if (e && !seen[e]) { seen[e] = true; out.push(e); }
  }
  return out;
}
function wipColLetter_(c) {
  var s = '';
  while (c > 0) { var m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); }
  return s;
}
function wipOwner_(ss) {
  try { return wipEmail_(ss.getOwner()); } catch (e) { return ''; }
}
function wipMe_() {
  try { return wipEmail_(Session.getEffectiveUser()); } catch (e) { return ''; }
}

/** header text (normalised) -> [1-based columns]. */
function wipHeaderMap_(sheet) {
  var lastCol = sheet.getLastColumn();
  var map = {};
  if (lastCol < 1) return map;
  var hdr = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  for (var c = 0; c < hdr.length; c++) {
    var k = wipNorm_(hdr[c]);
    if (!k) continue;
    (map[k] = map[k] || []).push(c + 1);
  }
  return map;
}

/** Resolve the counsellor columns of Walk-In New, or throw (nothing changed). */
function wipResolveEditableColumns_(sheet) {
  var map = wipHeaderMap_(sheet), cols = [], missing = [], dup = [];
  for (var i = 0; i < WIP_COUNSELLOR_EDITABLE.length; i++) {
    var hits = map[wipNorm_(WIP_COUNSELLOR_EDITABLE[i])] || [];
    if (!hits.length) missing.push(WIP_COUNSELLOR_EDITABLE[i]);
    else if (hits.length > 1) dup.push(WIP_COUNSELLOR_EDITABLE[i] + ' (columns ' +
                                       hits.map(wipColLetter_).join(', ') + ')');
    else cols.push(hits[0]);
  }
  if (missing.length || dup.length) {
    throw new Error('Walk-In New: protection NOT changed — ' +
      (missing.length ? 'counsellor column(s) not found: ' + missing.join(', ') + '. ' : '') +
      (dup.length ? 'header(s) appear more than once: ' + dup.join('; ') + '.' : ''));
  }
  // a counsellor column must never be one of the system columns
  for (var j = 0; j < WIP_SYSTEM_MANAGED.length; j++) {
    var sys = map[wipNorm_(WIP_SYSTEM_MANAGED[j])] || [];
    for (var k = 0; k < sys.length; k++) {
      if (cols.indexOf(sys[k]) >= 0) {
        throw new Error('Walk-In New: protection NOT changed — column ' + wipColLetter_(sys[k]) +
                        ' is both a counsellor and a system column.');
      }
    }
  }
  return cols.sort(function (a, b) { return a - b; });
}

/** Contiguous column runs: [3,4,5,9] -> [[3,5],[9,9]]. */
function wipRuns_(cols) {
  var runs = [];
  for (var i = 0; i < cols.length; i++) {
    var last = runs[runs.length - 1];
    if (last && cols[i] === last[1] + 1) last[1] = cols[i];
    else runs.push([cols[i], cols[i]]);
  }
  return runs;
}

/** Our sheet-level protection on a tab (adopting a pre-existing sheet protection,
 *  since a tab can hold only one). Returns {protection, created, adopted, previousEditors}. */
function wipSheetProtection_(sheet) {
  var list = sheet.getProtections(SpreadsheetApp.ProtectionType.SHEET);
  if (list.length) {
    var p = list[0];
    var adopted = p.getDescription() !== WIP_DESCRIPTION;
    var prev = adopted ? p.getEditors().map(wipEmail_) : [];
    for (var i = 1; i < list.length; i++) list[i].remove();   // never more than one
    return { protection: p, created: false, adopted: adopted, previousEditors: prev };
  }
  return { protection: sheet.protect(), created: true, adopted: false, previousEditors: [] };
}

/** The exact editor set a tab's protection must have (owner is implicit). */
function wipWantedEditors_(tabName, owner, me) {
  return wipUnique_([].concat(WIP_FULL_CONTROL, [me], WIP_TAB_EXTRA_EDITORS[tabName] || []))
    .filter(function (e) { return e && e !== owner; });
}

function wipSetEditors_(p, wanted, owner, me) {
  var current = p.getEditors().map(wipEmail_);
  var toAdd = wanted.filter(function (e) { return current.indexOf(e) < 0; });
  if (toAdd.length) p.addEditors(toAdd);
  var toRemove = current.filter(function (e) {
    return wanted.indexOf(e) < 0 && e !== owner && e !== me;   // Google keeps owner/me anyway
  });
  if (toRemove.length) p.removeEditors(toRemove);
  if (p.canDomainEdit && p.canDomainEdit()) p.setDomainEdit(false);
  return { added: toAdd, removed: toRemove };
}

/** Range protections on a tab (left as they are; reported). */
function wipRangeProtections_(sheet) {
  return sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE).map(function (rp) {
    var r = rp.getRange();
    return { range: r ? r.getA1Notation() : '?', description: rp.getDescription(),
             firstColumn: r ? r.getColumn() : 0,
             lastColumn: r ? r.getColumn() + r.getNumColumns() - 1 : 0,
             firstRow: r ? r.getRow() : 0,
             lastRow: r ? r.getRow() + r.getNumRows() - 1 : 0 };
  });
}


// ═══════════════════════════════════════════════════════════════════════════
//  1. AUDIT (read-only)
// ═══════════════════════════════════════════════════════════════════════════
/** Read-only report of the workbook before (or after) applying the rules. */
function auditWalkInWorkbook() {
  var ss = SpreadsheetApp.openById(WIP_SPREADSHEET_ID);
  var owner = wipOwner_(ss), me = wipMe_();
  var lines = ['Workbook: ' + ss.getName(), 'Owner: ' + (owner || '(shared drive / unknown)'),
               'Running as: ' + me, ''];
  ss.getSheets().forEach(function (sh) {
    var form = '';
    try { form = sh.getFormUrl() || ''; } catch (e) {}
    var sp = sh.getProtections(SpreadsheetApp.ProtectionType.SHEET).map(function (p) {
      return '[tab-protection "' + p.getDescription() + '" editors: ' +
             p.getEditors().map(wipEmail_).join(', ') + (p.isWarningOnly() ? ' (warning only)' : '') + ']';
    });
    var rp = wipRangeProtections_(sh).map(function (r) { return '[range ' + r.range + ']'; });
    lines.push(sh.getName() + (sh.isSheetHidden() ? ' (hidden)' : '') +
               ' | rows ' + sh.getLastRow() + '/' + sh.getMaxRows() +
               (form ? ' | Google Form linked' : '') +
               (sp.length || rp.length ? ' | ' + sp.concat(rp).join(' ') : ' | no protection'));
  });
  var wn = ss.getSheetByName(WIP_WALKIN_TAB);
  if (wn) {
    var map = wipHeaderMap_(wn);
    lines.push('');
    lines.push('Walk-In New headers:');
    [['counsellor-editable', WIP_COUNSELLOR_EDITABLE], ['system', WIP_SYSTEM_MANAGED],
     ['form', WIP_FORM_COLUMNS]].forEach(function (g) {
      var found = [], missing = [];
      g[1].forEach(function (h) {
        var c = map[wipNorm_(h)];
        if (c && c.length) found.push(h + '=' + c.map(wipColLetter_).join('/')); else missing.push(h);
      });
      lines.push('  ' + g[0] + ': ' + found.join(', ') + (missing.length ? '  | MISSING: ' + missing.join(', ') : ''));
    });
  } else {
    lines.push('', 'Walk-In New tab NOT FOUND');
  }
  lines.push('', 'Auto-populate triggers owned by the running account: ' +
             (wipAutoPopulateTriggers_().join(', ') || 'NONE (see the warning in the doc)'));
  var report = lines.join('\n');
  console.log(report);
  return report;
}

function wipAutoPopulateTriggers_() {
  try {
    return ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); })
      .filter(function (f) { return WIP_AUTOPOPULATE_HANDLERS.indexOf(f) >= 0; });
  } catch (e) { return []; }
}


// ═══════════════════════════════════════════════════════════════════════════
//  2. APPLY
// ═══════════════════════════════════════════════════════════════════════════
/**
 * Apply (or re-apply) the rules to every tab, then verify them. Safe to run any
 * number of times. Throws (→ Google e-mails the owner for a trigger run) when the
 * rules could not be applied or do not verify.
 */
function applyWorkbookProtection() {
  var lock = LockService.getDocumentLock() || LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('Another protection run is in progress.');
  try {
    var ss = SpreadsheetApp.openById(WIP_SPREADSHEET_ID);
    var owner = wipOwner_(ss), me = wipMe_();
    if (me !== owner && WIP_FULL_CONTROL.map(wipEmail_).indexOf(me) < 0) {
      throw new Error('Run this as the spreadsheet owner or an account in WIP_FULL_CONTROL ' +
                      '(running as ' + (me || 'unknown') + '). Nothing was changed.');
    }
    var walkin = ss.getSheetByName(WIP_WALKIN_TAB);
    if (!walkin) throw new Error('Tab "' + WIP_WALKIN_TAB + '" not found. Nothing was changed.');

    // ---- validate everything BEFORE changing anything ----
    var editableCols = wipResolveEditableColumns_(walkin);
    var report = { owner: owner, runningAs: me, tabs: [], warnings: [] };

    // keep a blank-row buffer so new form rows land inside the editable range
    var lastRow = Math.max(walkin.getLastRow(), 1), maxRows = walkin.getMaxRows();
    if (WIP_ROW_BUFFER > 0 && maxRows - lastRow < WIP_ROW_BUFFER) {
      walkin.insertRowsAfter(maxRows, WIP_ROW_BUFFER - (maxRows - lastRow));
      report.warnings.push('Walk-In New: added ' + (WIP_ROW_BUFFER - (maxRows - lastRow)) +
                           ' blank rows at the bottom (row buffer).');
      maxRows = walkin.getMaxRows();
    }

    ss.getSheets().forEach(function (sh) {
      var name = sh.getName(), isWalkin = (name === WIP_WALKIN_TAB);
      var got = wipSheetProtection_(sh), p = got.protection;
      p.setDescription(WIP_DESCRIPTION);
      p.setWarningOnly(false);
      var unprot = [];
      if (isWalkin) {
        unprot = wipRuns_(editableCols).map(function (run) {
          return sh.getRange(2, run[0], maxRows - 1, run[1] - run[0] + 1);
        });
      }
      p.setUnprotectedRanges(unprot);
      var ed = wipSetEditors_(p, wipWantedEditors_(name, owner, me), owner, me);
      var entry = { tab: name, created: got.created, adopted: got.adopted,
                    previousEditors: got.previousEditors, editorsAdded: ed.added,
                    editorsRemoved: ed.removed,
                    editable: unprot.map(function (r) { return r.getA1Notation(); }) };
      report.tabs.push(entry);
      wipRangeProtections_(sh).forEach(function (r) {
        // a header-only lock (e.g. ProtectHeaderRow.gs) never touches lead rows
        var overlaps = isWalkin && r.lastRow >= 2 && editableCols.some(function (c) {
          return c >= r.firstColumn && c <= r.lastColumn;
        });
        report.warnings.push(name + ': existing range protection ' + r.range +
          (overlaps ? ' covers a counsellor column — it may still block counsellors there'
                    : ' left as it is'));
      });
    });

    if (!wipAutoPopulateTriggers_().length) {
      report.warnings.push('The running account owns none of the WalkInNewAutoPopulate triggers (' + WIP_AUTOPOPULATE_HANDLERS.join(' / ') + '). ' +
        'Make sure the account that installed them is in WIP_FULL_CONTROL, otherwise Lead ' +
        'Interaction History and Conversion Chance % stop updating.');
    }

    var check = verifyWorkbookProtection();
    report.verified = check.ok;
    report.problems = check.problems;
    console.log(JSON.stringify(report, null, 2));
    if (!check.ok) throw new Error('Protection applied but NOT verified: ' + check.problems.join(' | '));
    return report;
  } finally {
    lock.releaseLock();
  }
}


// ═══════════════════════════════════════════════════════════════════════════
//  3. VERIFY (read-only)
// ═══════════════════════════════════════════════════════════════════════════
/** Read back every tab's protection and compare it with the rules. */
function verifyWorkbookProtection() {
  var ss = SpreadsheetApp.openById(WIP_SPREADSHEET_ID);
  var owner = wipOwner_(ss), me = wipMe_();
  var problems = [];
  var walkin = ss.getSheetByName(WIP_WALKIN_TAB);
  if (!walkin) problems.push('Walk-In New tab not found');
  var editableCols = [];
  if (walkin) {
    try { editableCols = wipResolveEditableColumns_(walkin); }
    catch (e) { problems.push(e.message); }
  }
  ss.getSheets().forEach(function (sh) {
    var name = sh.getName(), isWalkin = (name === WIP_WALKIN_TAB);
    var list = sh.getProtections(SpreadsheetApp.ProtectionType.SHEET);
    if (list.length !== 1 || list[0].getDescription() !== WIP_DESCRIPTION) {
      problems.push(name + ': tab protection missing'); return;
    }
    var p = list[0];
    if (p.isWarningOnly()) problems.push(name + ': protection is warning-only');
    if (p.canDomainEdit && p.canDomainEdit()) problems.push(name + ': whole domain can edit');
    var wanted = wipWantedEditors_(name, owner, me).sort();
    var actual = p.getEditors().map(wipEmail_)
      .filter(function (e) { return e !== owner && e !== me; }).sort();
    var wantedNoMe = wanted.filter(function (e) { return e !== me; });
    if (actual.join(',') !== wantedNoMe.join(',')) {
      problems.push(name + ': editors are [' + actual.join(', ') + '], expected [' +
                    wantedNoMe.join(', ') + '] (+ owner)');
    }
    var cols = {}, rowsOk = true;
    p.getUnprotectedRanges().forEach(function (r) {
      if (r.getRow() < 2) problems.push(name + ': header row is editable (' + r.getA1Notation() + ')');
      if (r.getRow() + r.getNumRows() - 1 < sh.getLastRow()) rowsOk = false;
      for (var c = r.getColumn(); c < r.getColumn() + r.getNumColumns(); c++) cols[c] = true;
    });
    var editable = Object.keys(cols).map(Number).sort(function (a, b) { return a - b; });
    if (!isWalkin) {
      if (editable.length) problems.push(name + ': should be fully read-only but columns ' +
                                         editable.map(wipColLetter_).join(', ') + ' are editable');
      return;
    }
    if (editable.join(',') !== editableCols.join(',')) {
      problems.push('Walk-In New: editable columns are [' + editable.map(wipColLetter_).join(', ') +
                    '], expected [' + editableCols.map(wipColLetter_).join(', ') + ']');
    }
    if (!rowsOk) problems.push('Walk-In New: some data rows lie below the counsellor-editable range');
    var map = wipHeaderMap_(sh);
    WIP_SYSTEM_MANAGED.concat(WIP_FORM_COLUMNS).forEach(function (h) {
      (map[wipNorm_(h)] || []).forEach(function (c) {
        if (cols[c]) problems.push('Walk-In New: "' + h + '" (' + wipColLetter_(c) + ') is editable');
      });
    });
  });
  var result = { ok: problems.length === 0, problems: problems };
  console.log(result.ok ? 'Protection verified on all tabs.' : 'PROBLEMS:\n' + problems.join('\n'));
  return result;
}


// ═══════════════════════════════════════════════════════════════════════════
//  4. KEEP IT CURRENT (triggers)
// ═══════════════════════════════════════════════════════════════════════════
/** Installable onFormSubmit: if a new Walk-In row lands near/below the end of the
 *  counsellor-editable range, re-apply at once so counsellors can edit it. Never
 *  throws (the WalkInNewAutoPopulate.gs form trigger is independent of this). */
function onWalkInProtectionFormSubmit(e) {
  try {
    var sh = e && e.range ? e.range.getSheet() : null;
    if (sh && sh.getName() !== WIP_WALKIN_TAB) return;
    var ss = SpreadsheetApp.openById(WIP_SPREADSHEET_ID);
    var wn = ss.getSheetByName(WIP_WALKIN_TAB);
    if (!wn) return;
    var row = e && e.range ? e.range.getRow() + e.range.getNumRows() - 1 : wn.getLastRow();
    var end = 0;
    wn.getProtections(SpreadsheetApp.ProtectionType.SHEET).forEach(function (p) {
      p.getUnprotectedRanges().forEach(function (r) {
        end = Math.max(end, r.getRow() + r.getNumRows() - 1);
      });
    });
    if (row > end - WIP_REAPPLY_MARGIN) applyWorkbookProtection();
  } catch (err) {
    console.error('onWalkInProtectionFormSubmit: ' + err);
  }
}

/** Daily re-apply (also protects any NEW tab and re-aligns moved columns). */
function onWorkbookProtectionDaily() {
  applyWorkbookProtection();       // throws on failure → Google e-mails the owner
}

/** Run ONCE (as the owner). Installs only this file's triggers; safe to re-run. */
function setupWorkbookProtectionTriggers() {
  var mine = ['onWalkInProtectionFormSubmit', 'onWorkbookProtectionDaily'];
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (mine.indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t);
  });
  var ss = SpreadsheetApp.openById(WIP_SPREADSHEET_ID);
  ScriptApp.newTrigger('onWalkInProtectionFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
  ScriptApp.newTrigger('onWorkbookProtectionDaily').timeBased().everyDays(1).atHour(WIP_DAILY_HOUR).create();
  console.log('Installed: onWalkInProtectionFormSubmit (form submit), onWorkbookProtectionDaily (daily ~' + WIP_DAILY_HOUR + ' AM).');
  return mine;
}
