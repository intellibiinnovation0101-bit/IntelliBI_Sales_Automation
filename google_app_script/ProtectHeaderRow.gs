/**
 * ProtectHeaderRow.gs — protect the HEADER ROW (row 1) on chosen tabs so the
 * column names can't be renamed/edited. The reports look up columns BY NAME
 * (Timestamp, Full Name, Mobile Number, …), so a changed header silently breaks
 * consolidation and the walk-in reports. Locking row 1 prevents that.
 *
 * HOW TO USE
 *   1. Open the Google Sheet whose headers you want to lock.
 *   2. Extensions ▸ Apps Script → paste this file → Save.
 *   3. Edit CONFIG below (which tabs; who may still edit).
 *   4. Run lockHeaders() once. Approve the permission prompt on first run.
 *   To undo, run unlockHeaders().
 *
 * NOTES
 *   • Only the sheet OWNER/EDITORS can set protections; viewers are unaffected.
 *   • WARNING_ONLY=true  -> anyone can still edit but gets an "are you sure?"
 *     prompt (soft guard). WARNING_ONLY=false -> only EDITORS_ALLOWED may edit
 *     the header (hard lock). Start with false for a real lock.
 *   • This locks the header CELLS. Column order can still change if someone
 *     inserts/deletes a column — but the loaders match by name, so that's safe
 *     as long as the NAMES stay intact, which is exactly what this protects.
 */

// ── CONFIG ──────────────────────────────────────────────────────────────────
// Tabs to lock. Leave [] to lock the header row on EVERY tab in the file.
var TABS = [];                 // e.g. ["Walk-In New", "Walk-In Old", "Sheet1"]

// false = hard lock (only the people in EDITORS_ALLOWED can edit the header).
// true  = soft guard (edit allowed after a warning prompt).
var WARNING_ONLY = false;

// Emails allowed to edit the header when WARNING_ONLY is false. The person who
// runs the script is always allowed. Add teammates who should keep edit rights.
var EDITORS_ALLOWED = [];      // e.g. ["you@intellibiinnovationstechnologies.in"]

var HEADER_ROWS = 1;           // how many top rows are "header" (usually 1)
// ────────────────────────────────────────────────────────────────────────────

function lockHeaders() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = _targetSheets_(ss);
  var me = Session.getEffectiveUser().getEmail();
  var done = [];
  sheets.forEach(function (sh) {
    var lastCol = Math.max(sh.getLastColumn(), 1);
    var range = sh.getRange(1, 1, HEADER_ROWS, lastCol);

    // remove any existing header protection we set before (idempotent re-run)
    _removeOurProtections_(sh);

    var p = range.protect().setDescription('Locked header row — do not rename columns');
    if (WARNING_ONLY) {
      p.setWarningOnly(true);
    } else {
      // hard lock: strip everyone else, then add back the allow-list + owner
      var editors = p.getEditors().map(function (u) { return u.getEmail(); });
      if (editors.length) p.removeEditors(editors);
      if (p.canDomainEdit && p.canDomainEdit()) p.setDomainEdit(false);
      var keep = EDITORS_ALLOWED.slice();
      if (me) keep.push(me);
      keep.forEach(function (em) { try { p.addEditor(em); } catch (e) {} });
    }
    done.push(sh.getName());
  });
  SpreadsheetApp.getActive().toast('Header row locked on: ' + done.join(', '),
                                   'Done', 5);
  Logger.log('Locked header on: ' + done.join(', '));
}

function unlockHeaders() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = _targetSheets_(ss);
  var done = [];
  sheets.forEach(function (sh) { if (_removeOurProtections_(sh)) done.push(sh.getName()); });
  SpreadsheetApp.getActive().toast('Header lock removed on: ' + done.join(', '),
                                   'Done', 5);
  Logger.log('Unlocked header on: ' + done.join(', '));
}

// ── helpers ─────────────────────────────────────────────────────────────────
function _targetSheets_(ss) {
  if (TABS && TABS.length) {
    return TABS.map(function (n) { return ss.getSheetByName(n); })
               .filter(function (s) { return s; });
  }
  return ss.getSheets();
}

function _removeOurProtections_(sh) {
  var removed = false;
  sh.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function (p) {
    if ((p.getDescription() || '').indexOf('Locked header row') === 0) {
      p.remove(); removed = true;
    }
  });
  return removed;
}