/**
 * ProtectLeadResultSheet.gs
 * ---------------------------------------------------------------------------
 * Locks the lead DATA store — the "IntelliBI Lead Information Result" spreadsheet
 * (tabs "IntelliBI Lead Information Active" / "…InActive", legacy tab name
 * "IntelliBI Lead Information Result") — so that counsellors can VIEW it but
 * cannot type in it, paste over it, delete rows, insert columns or otherwise
 * change its data by hand. Data keeps flowing in ONLY through the automation:
 *
 *     "IntelliBI Lead Information" form  →  LeadSubmissionForm.gs
 *                                        →  IntelliBI Lead Information Result
 *
 * Standalone file. It does NOT modify or depend on LeadSubmissionForm.gs, the
 * data mappings or the Save / Search / Update logic. Paste it into the SAME Apps
 * Script project as LeadSubmissionForm.gs (Extensions ▸ Apps Script ▸ + File),
 * Save, then run from the editor's Run menu — AS THE FILE OWNER
 * (info@intellibiinnovationstechnologies.in), so the owner can never be locked
 * out:
 *
 *     lockLeadResultSheet()     -> protect every data tab (safe to re-run)
 *     verifyLeadResultLock()    -> report who can still write, and whether the
 *                                  automation identities are covered
 *     unlockLeadResultSheet()   -> remove ONLY the locks this file created
 *
 * ---------------------------------------------------------------------------
 * HOW THE LOCK WORKS (and why the automation keeps working)
 *
 *   • A SHEET-level protection is placed on each data tab, hard lock (not
 *     "warning only"). Only the accounts in LR_ALLOWED_EDITORS (+ the file owner)
 *     stay "editors of the protection"; every other account keeps its file
 *     access but can no longer modify these tabs.
 *
 *   • Saves from the form never run as a counsellor. The "TICK TO SAVE / SEARCH /
 *     RESET" checkboxes fire the INSTALLABLE trigger onLeadFormCheckbox, which
 *     runs as the account that installed it (menu "📅 Set up Save box + date
 *     pickers"), and that account is in the allow-list — so runSubmit() /
 *     upsertRecord_() / archiveToInactive_() write exactly as before. The menu
 *     "✅ Validate Mobile Number" runs as the counsellor but only READS the data
 *     store, which a viewer can do.
 *
 *   • The Counsellor Server (counsellor_app) writes through the service account
 *     in LR_ALLOWED_EDITORS, so its Save / Search / Update are unaffected.
 *
 *   • Recommended second layer (Drive sharing, done by hand — see README):
 *     change each counsellor account from Editor to VIEWER on the Result file.
 *     A viewer can look but cannot add tabs, delete sheets or import over the
 *     file; the protection then only has to guard the accounts that keep edit
 *     rights (admins). Nothing in the workflow needs a counsellor to be an
 *     editor of the Result file.
 *
 * Re-running lockLeadResultSheet() is safe: it removes its own previous locks
 * first, then re-applies. It never touches protections created by anything
 * else (its own are tagged with LR_PROTECT_TAG, e.g. ProtectHeaderRow.gs locks).
 * ---------------------------------------------------------------------------
 */

// ── CONFIG ──────────────────────────────────────────────────────────────────
// The data store (same file LeadSubmissionForm.gs writes to: DATA_ID).
var LR_DATA_ID = '1ReJVPl_Y8WnOl_P2sui_uC1jjZXVk0dWqNWRcXGVHCw';

// Tabs to lock. Leave [] to lock EVERY tab in the file. Missing names are skipped.
var LR_TABS = [
  'IntelliBI Lead Information Active',
  'IntelliBI Lead Information InActive',
  'IntelliBI Lead Information Result'      // legacy name of the Active tab
];

// Accounts that may still WRITE to the locked tabs. The file owner and the
// account running this script are ALWAYS kept. Everyone else with edit rights on
// the file (the counsellor accounts) is removed from the protection.
//   - the account that installed the Save/Search/Reset trigger (owner of
//     onLeadFormCheckbox) MUST be here, otherwise ticking "Save" fails;
//   - the service account is what the Counsellor Server (counsellor_app) and the
//     Sales pipeline use.
var LR_ALLOWED_EDITORS = [
  'info@intellibiinnovationstechnologies.in',                        // owner
  'intellibiinnovation0101@gmail.com',                               // admin / build account
  'intellibi-data-pipeline@intellibi-mis.iam.gserviceaccount.com'    // counsellor_app + pipeline
];

var LR_PROTECT_TAG = 'IntelliBI Lead Result Lock';
// ────────────────────────────────────────────────────────────────────────────

/** Lock every data tab so only LR_ALLOWED_EDITORS (+ owner) can change it. */
function lockLeadResultSheet() {
  var ss = SpreadsheetApp.openById(LR_DATA_ID);
  var me = lr_me_();
  var keep = lr_keepList_(ss, me);
  var report = ['File: ' + ss.getName(), 'Run by: ' + (me || '(unknown)'), ''];

  var sheets = lr_targetSheets_(ss);
  if (!sheets.length) {
    lr_notify_('No matching tab found in "' + ss.getName() + '" — check LR_TABS.');
    return;
  }

  for (var i = 0; i < sheets.length; i++) {
    var sh = sheets[i];
    lr_removeOurProtections_(sh);                                   // idempotent re-run

    var p = sh.protect().setDescription(LR_PROTECT_TAG + ' — ' + sh.getName());
    try { p.setWarningOnly(false); } catch (e0) {}                  // hard lock
    try { if (p.canDomainEdit()) p.setDomainEdit(false); } catch (e1) {}

    // 1) add the allowed accounts (each must already have edit access to the file)
    var added = [], notAdded = [];
    for (var a = 0; a < keep.length; a++) {
      try { p.addEditor(keep[a]); added.push(keep[a]); }
      catch (e2) { notAdded.push(keep[a] + ' (' + lr_msg_(e2) + ')'); }
    }
    // 2) remove everybody else (counsellor accounts). The owner cannot be removed.
    var removed = [];
    try {
      var eds = p.getEditors();
      for (var e = 0; e < eds.length; e++) {
        var em = String(eds[e].getEmail() || '').toLowerCase();
        if (em && keep.indexOf(em) === -1) {
          try { p.removeEditor(em); removed.push(em); } catch (x) {}
        }
      }
    } catch (e3) {}

    report.push('LOCKED  ' + sh.getName());
    report.push('   may still write : ' + lr_editorList_(p).join(', '));
    if (removed.length)  report.push('   blocked now     : ' + removed.join(', '));
    if (notAdded.length) report.push('   NOT added (share the file with them as Editor first): ' + notAdded.join(', '));
  }
  SpreadsheetApp.flush();

  report.push('');
  report = report.concat(lr_automationChecks_(ss, keep));
  lr_notify_(report.join('\n'));
}

/** Remove the locks this file created (only these). Run lockLeadResultSheet() again after. */
function unlockLeadResultSheet() {
  var ss = SpreadsheetApp.openById(LR_DATA_ID);
  var sheets = ss.getSheets(), done = [];
  for (var i = 0; i < sheets.length; i++) {
    if (lr_removeOurProtections_(sheets[i])) done.push(sheets[i].getName());
  }
  SpreadsheetApp.flush();
  lr_notify_('UNLOCKED: ' + (done.join(', ') || '(nothing was locked by this script)'));
}

/** Read-only report: which tabs are locked, who can still write, and whether the
 *  automation identities (trigger owner, service account) are covered. */
function verifyLeadResultLock() {
  var ss = SpreadsheetApp.openById(LR_DATA_ID);
  var me = lr_me_();
  var keep = lr_keepList_(ss, me);
  var out = ['File: ' + ss.getName(), 'Run by: ' + (me || '(unknown)'), ''];

  var sheets = lr_targetSheets_(ss);
  for (var i = 0; i < sheets.length; i++) {
    var sh = sheets[i];
    var ours = lr_ourProtections_(sh);
    if (!ours.length) { out.push('NOT LOCKED  ' + sh.getName()); continue; }
    for (var k = 0; k < ours.length; k++) {
      var p = ours[k];
      out.push((p.isWarningOnly() ? 'WARNING-ONLY ' : 'LOCKED  ') + sh.getName());
      out.push('   may still write : ' + lr_editorList_(p).join(', '));
    }
  }
  out.push('');
  out = out.concat(lr_automationChecks_(ss, keep));
  lr_notify_(out.join('\n'));
}

// ===========================================================================
//  Helpers (prefixed lr_ so they never clash with LeadSubmissionForm.gs)
// ===========================================================================

function lr_me_() {
  try { return String(Session.getEffectiveUser().getEmail() || '').toLowerCase(); } catch (e) { return ''; }
}

/** owner + runner + LR_ALLOWED_EDITORS, lower-cased, de-duplicated. */
function lr_keepList_(ss, me) {
  var keep = [];
  function add(x) { x = String(x || '').toLowerCase(); if (x && keep.indexOf(x) === -1) keep.push(x); }
  try { var o = ss.getOwner(); if (o) add(o.getEmail()); } catch (e) {}
  add(me);
  for (var i = 0; i < LR_ALLOWED_EDITORS.length; i++) add(LR_ALLOWED_EDITORS[i]);
  return keep;
}

function lr_targetSheets_(ss) {
  var all = ss.getSheets();
  if (!LR_TABS.length) return all;
  var want = LR_TABS.map(function (n) { return String(n).trim().toLowerCase(); });
  return all.filter(function (sh) { return want.indexOf(sh.getName().trim().toLowerCase()) !== -1; });
}

function lr_ourProtections_(sh) {
  var out = [];
  var groups = [
    sh.getProtections(SpreadsheetApp.ProtectionType.SHEET),
    sh.getProtections(SpreadsheetApp.ProtectionType.RANGE)
  ];
  for (var g = 0; g < groups.length; g++) {
    for (var i = 0; i < groups[g].length; i++) {
      if ((groups[g][i].getDescription() || '').indexOf(LR_PROTECT_TAG) === 0) out.push(groups[g][i]);
    }
  }
  return out;
}

/** Remove ONLY the protections this script created (matched by description tag). */
function lr_removeOurProtections_(sh) {
  var ours = lr_ourProtections_(sh), removed = false;
  for (var i = 0; i < ours.length; i++) { try { ours[i].remove(); removed = true; } catch (e) {} }
  return removed;
}

function lr_editorList_(p) {
  try { return p.getEditors().map(function (u) { return u.getEmail(); }).filter(String).sort(); }
  catch (e) { return ['(could not read editors: ' + lr_msg_(e) + ')']; }
}

/**
 * Sanity checks that the automation is not blocked:
 *   • the Save/Search/Reset trigger (onLeadFormCheckbox) — if THIS account owns
 *     it, saves run as this account, which is kept; if this account has no such
 *     trigger, whoever installed it must be in LR_ALLOWED_EDITORS;
 *   • every allowed account (incl. the service account) still has edit access
 *     to the file — a protection editor must be a file editor;
 *   • lists the file editors that are now blocked on the data tabs (the
 *     counsellors), with the reminder to make them Viewers.
 */
function lr_automationChecks_(ss, keep) {
  var out = ['Automation checks:'];

  var hasTrigger = false, canSeeTriggers = true;
  try {
    var trs = ScriptApp.getProjectTriggers();
    for (var i = 0; i < trs.length; i++) if (trs[i].getHandlerFunction() === 'onLeadFormCheckbox') hasTrigger = true;
  } catch (e) { canSeeTriggers = false; }
  if (!canSeeTriggers) {
    out.push('  ? could not read project triggers (is this file inside the LeadSubmissionForm project?)');
  } else if (hasTrigger) {
    out.push('  OK  Save/Search/Reset trigger (onLeadFormCheckbox) is owned by this account — saves keep working.');
  } else {
    out.push('  !!  This account owns NO onLeadFormCheckbox trigger. The account that ran');
    out.push('      "Set up Save box + date pickers" is the one that saves; it MUST be in');
    out.push('      LR_ALLOWED_EDITORS — or run that menu item from this account now.');
  }

  var fileEditors = [];
  try { fileEditors = ss.getEditors().map(function (u) { return String(u.getEmail() || '').toLowerCase(); }); } catch (e2) {}
  try { var o = ss.getOwner(); if (o) fileEditors.push(String(o.getEmail()).toLowerCase()); } catch (e3) {}

  for (var k = 0; k < keep.length; k++) {
    if (fileEditors.indexOf(keep[k]) === -1)
      out.push('  !!  ' + keep[k] + ' is in LR_ALLOWED_EDITORS but is NOT an editor of the file — share the file with it as Editor, then re-run lock.');
  }
  var blocked = fileEditors.filter(function (e) { return keep.indexOf(e) === -1; });
  if (blocked.length) {
    out.push('  i   File editors now blocked on the data tabs: ' + blocked.join(', '));
    out.push('      Recommended: change them to VIEWER on the Result file (Share ▸ role) — nothing in the workflow needs them to be editors of it.');
  } else {
    out.push('  OK  No other file editor — only the allowed accounts can write.');
  }
  return out;
}

function lr_msg_(e) { return (e && e.message) ? e.message : String(e); }

/** Log + (when run from a sheet) toast, so you get feedback from the editor's Run menu. */
function lr_notify_(msg) {
  Logger.log(msg);
  try {
    var active = SpreadsheetApp.getActiveSpreadsheet();
    if (active) active.toast(msg.split('\n').slice(0, 6).join('\n'), 'IntelliBI — Result lock', 10);
  } catch (e) {}
}
