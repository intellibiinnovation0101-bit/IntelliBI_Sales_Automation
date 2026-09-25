/**
 * ProtectCounsellorForm.gs
 * ---------------------------------------------------------------------------
 * Locks ONLY the counsellor form's LABEL / field-name cells (and the action
 * labels) so counsellors cannot rename or move them. EVERYTHING ELSE stays
 * editable — every value/input cell, and the Save / Search / Reset checkboxes —
 * so counsellors keep entering data and using the actions exactly as before.
 *
 * Standalone file. It does NOT modify or depend on LeadSubmissionForm.gs. Paste
 * it into the SAME Apps Script project as an extra file, then run manually from
 * the editor's Run menu:
 *
 *     lockCounsellorForm()     -> lock the labels on every counsellor form tab
 *     unlockCounsellorForm()   -> remove the locks (to edit the form), then re-run lock
 *
 * ---------------------------------------------------------------------------
 * WHAT GETS LOCKED (read-only for counsellors):
 *   • the contact header labels        : Mobile Number | Full Name | Email Address
 *   • the table header labels          : Column Name | Enter Column Value  (x2)
 *   • every field-name label (column A and column C of the form table), e.g.
 *     Candidate Type, Total Years of Experience, IsGoogleMeetSchedule:,
 *     Counselling By, Admission Status, BackOutReason, …
 *   • the three action labels          : ✅ TICK TO SAVE ▶ / 🔍 TICK TO SEARCH ▶ / ♻️ TICK TO RESET ▶
 *
 * WHAT STAYS EDITABLE (unchanged for counsellors):
 *   • every VALUE cell (the input row, and the two "Enter Column Value" columns)
 *   • the Save / Search / Reset CHECKBOXES
 *   • everything else on the sheet
 *
 * WHY IT DOESN'T BREAK THE AUTOMATION:
 *   The locks list ONLY the owner as editor. LeadSubmissionForm.gs runs AS THE
 *   OWNER (its installable trigger + menu functions), so it can still populate,
 *   update, clear, search, save and reset ANY cell. The locks only stop a
 *   counsellor's own manual edit of a label. Because only the label cells are
 *   protected, value entry is never affected.
 *
 * Re-running lockCounsellorForm() is safe: it removes its own previous locks
 * first, then re-applies. It never touches protections created by anything else
 * (its own are tagged with PF_PROTECT_TAG).
 * ---------------------------------------------------------------------------
 */

var PF_PROTECT_TAG = 'IntelliBI Form Label Lock';

/** Lock the label / field-name cells on every counsellor form tab. Run once. */
function lockCounsellorForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var myEmail = '';
  try { myEmail = Session.getEffectiveUser().getEmail() || ''; } catch (e) {}

  var sheets = ss.getSheets(), done = [], skipped = [];
  for (var i = 0; i < sheets.length; i++) {
    var sh = sheets[i];
    if (!pf_isFormSheet_(sh)) continue;

    pf_removeOurProtections_(sh);                    // idempotent re-run

    var labelRanges = pf_labelRanges_(sh);
    if (!labelRanges.length) { skipped.push(sh.getName()); continue; }

    for (var k = 0; k < labelRanges.length; k++) {
      var rng = labelRanges[k];
      var p = rng.protect()
                 .setDescription(PF_PROTECT_TAG + ' — ' + sh.getName() +
                                 ' — ' + rng.getA1Notation());
      try { if (p.canDomainEdit()) p.setDomainEdit(false); } catch (e2) {}
      // Owner-only: remove every other editor so counsellors can't edit labels.
      try {
        var eds = p.getEditors();
        for (var e = 0; e < eds.length; e++) {
          var em = eds[e].getEmail();
          if (em && em !== myEmail) { try { p.removeEditor(em); } catch (x) {} }
        }
      } catch (e3) {}
    }
    done.push(sh.getName());
  }
  SpreadsheetApp.flush();

  var msg = 'Field-name labels LOCKED on: ' + (done.join(', ') || '(no form tabs found)');
  if (skipped.length) msg += '\nSkipped (layout not recognised): ' + skipped.join(', ');
  pf_notify_(ss, msg);
}

/** Remove the label locks from every tab (so you can edit the form). Only
 *  removes locks created by THIS script. Run lockCounsellorForm() again after. */
function unlockCounsellorForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = ss.getSheets(), done = [];
  for (var i = 0; i < sheets.length; i++) {
    if (pf_removeOurProtections_(sheets[i])) done.push(sheets[i].getName());
  }
  SpreadsheetApp.flush();
  pf_notify_(ss, 'Field-name labels UNLOCKED on: ' + (done.join(', ') || '(nothing was locked)'));
}

// ===========================================================================
//  Helpers (prefixed pf_ so they never clash with LeadSubmissionForm.gs)
// ===========================================================================

/** A tab is a counsellor form if column A contains "Mobile Number" or "Column Name". */
function pf_isFormSheet_(sh) {
  var n = Math.min(sh.getMaxRows(), 60);
  if (n < 1) return false;
  var col = sh.getRange(1, 1, n, 1).getValues();
  for (var r = 0; r < col.length; r++) {
    var v = String(col[r][0]).trim().toLowerCase();
    if (v === 'column name' || v === 'mobile number') return true;
  }
  return false;
}

/** Remove ONLY the protections this script created (matched by description tag). */
function pf_removeOurProtections_(sh) {
  var removed = false;
  var groups = [
    sh.getProtections(SpreadsheetApp.ProtectionType.RANGE),
    sh.getProtections(SpreadsheetApp.ProtectionType.SHEET)
  ];
  for (var g = 0; g < groups.length; g++) {
    for (var i = 0; i < groups[g].length; i++) {
      var d = groups[g][i].getDescription() || '';
      if (d.indexOf(PF_PROTECT_TAG) === 0) {
        try { groups[g][i].remove(); removed = true; } catch (e) {}
      }
    }
  }
  return removed;
}

/**
 * Return ONLY the LABEL cells to lock:
 *   1) contact header row labels  (Mobile Number | Full Name | Email Address),
 *   2) the "Column Name | Enter Column Value" header row,
 *   3) the field-name labels in column A and column C of the form table,
 *   4) each "TICK TO …" action label (column E).
 * Value cells, the input row, checkboxes and everything else are NOT included,
 * so they stay fully editable.
 */
function pf_labelRanges_(sh) {
  var values = sh.getDataRange().getValues();
  var nRows = values.length;
  if (!nRows) return [];

  function rowOf(text) {
    for (var i = 0; i < nRows; i++) {
      if (String(values[i][0]).trim().toLowerCase() === text) return i + 1;   // 1-based
    }
    return -1;
  }

  var lastRow = 0;
  for (var r = 0; r < nRows; r++) {
    for (var c = 0; c < values[r].length; c++) {
      if (String(values[r][c]).trim() !== '') { lastRow = r + 1; break; }
    }
  }

  var contactRow = rowOf('mobile number');   // the LABEL row (values sit one row below)
  var headerRow  = rowOf('column name');     // "Column Name | Enter Column Value | …"
  var ranges = [];

  // 1) contact header labels (Mobile Number | Full Name | Email Address)
  if (contactRow > 0) ranges.push(sh.getRange(contactRow, 1, 1, 4));

  // 2) the table header labels ("Column Name | Enter Column Value" x2)
  if (headerRow > 0) ranges.push(sh.getRange(headerRow, 1, 1, 4));

  // 3) the field-name labels: column A and column C of the form BODY
  if (headerRow > 0 && lastRow > headerRow) {
    var nBody = lastRow - headerRow;
    ranges.push(sh.getRange(headerRow + 1, 1, nBody, 1));   // column A labels
    ranges.push(sh.getRange(headerRow + 1, 3, nBody, 1));   // column C labels
  }

  // 4) the three action LABELS ("TICK TO …") — lock the label cell only, NOT the
  //    checkbox to its right.
  for (var rr = 0; rr < nRows; rr++) {
    var rowVals = values[rr];
    for (var cc = 0; cc < rowVals.length; cc++) {
      var t = String(rowVals[cc]).toLowerCase();
      if (t.indexOf('tick') !== -1 &&
          (t.indexOf('save') !== -1 || t.indexOf('search') !== -1 ||
           t.indexOf('reset') !== -1)) {
        ranges.push(sh.getRange(rr + 1, cc + 1));           // the label cell itself
      }
    }
  }
  return ranges;
}

/** Small toast + log so you get feedback when running from the editor. */
function pf_notify_(ss, msg) {
  try { ss.toast(msg, 'IntelliBI — Form Protection', 8); } catch (e) {}
  Logger.log(msg);
}
