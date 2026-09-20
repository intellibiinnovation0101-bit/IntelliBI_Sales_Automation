/**
 * WebsiteNewAutoPopulate.gs
 * =========================================================================
 * Auto-populates ONE column on the "Website New" leads tab whenever a NEW
 * Website lead is added:
 *
 *     AC  ->  Lead Interaction History
 *
 * This is the SAME "Lead Interaction History" behaviour already implemented for
 * the Walk-In New tab (WalkInNewAutoPopulate.gs) — identical history-building,
 * format, de-duplication and update behaviour — adapted to the Website New sheet
 * structure. (The Walk-In script also writes a second "Conversion Chance %"
 * column; this Website script intentionally writes ONLY the Lead Interaction
 * History column, exactly as requested.)
 *
 *   - "Lead Interaction History" = clean_history(history): one readable line per
 *     interaction, oldest first, "dd-MMM-yyyy hh:mm a  ·  <source>  ·  <by>".
 *
 * IMPORTANT — the newly added Website record is INCLUDED in the output:
 *     Previous Lead History  +  Newly Added Website Lead  =  Latest Lead History
 * The new row is merged into the lead's master history (by normalised mobile)
 * before the history string is computed, and the FULL history is de-duplicated
 * by (source, date-to-the-minute) so nothing is duplicated or overwritten.
 *
 * Only the Lead Interaction History column (AC) is written. No existing column,
 * formula, validation, formatting or data-entry logic is touched. This script is
 * DELIBERATELY SEPARATE from the existing Website web-app receiver
 * (WebsiteNewAutoPopulateOld.gs: doPost / doGet / sendAdminNotification). That
 * receiver is not modified, re-deployed or called from here, so existing Website
 * lead-capture and admin-email behaviour is guaranteed undisturbed.
 *
 * WHY A TIME-DRIVEN TRIGGER (not just onEdit/onFormSubmit):
 *   New Website leads arrive via the web-app doPost, which adds rows
 *   PROGRAMMATICALLY (sheet.appendRow). Google's installable onEdit trigger does
 *   NOT fire for programmatic writes, and there is no Google Form, so onFormSubmit
 *   does not fire either. A time-driven trigger therefore fills the AC history for
 *   newly appended web-app rows (rows that have a mobile but a blank AC), while the
 *   onEdit trigger keeps manual edits/pastes updated instantly. Both are
 *   idempotent (dedupe by source+minute gives identical output on re-run, and the
 *   timer only fills blank rows), so nothing is duplicated or overwritten.
 *
 * SETUP (run once): open Extensions -> Apps Script, paste this file, then run
 *   setupWebsiteTriggers()   and authorise. That installs the triggers
 *   (time-driven every 5 min + onEdit, plus a harmless onFormSubmit) and ensures
 *   the "Lead Interaction History" header exists at column AC.
 * =========================================================================
 */

// ── CONFIG ────────────────────────────────────────────────────────────────
var WEBSITE_SHEET_ID = '1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE'; // Website leads spreadsheet
var WEBSITE_NEW_GID  = 1384521339;   // the target tab (matches ?gid= in the URL)
var WEBSITE_NEW_TAB  = 'Contact Us Form'; // name fallback if the gid cannot be resolved
                                          // (this is the live Website-leads tab the
                                          //  existing web-app doPost appends to)
var MASTER_SHEET_ID  = '1zZQjXnMJD96Ca0MNyfSt4-XS0z5w3rT7WPdb9qsP1Gs'; // Consolidate Sales Tracking

// The interaction source recorded for a Website lead (mirrors 'Walk-In' in the
// Walk-In script; normalises to the "Website" platform).
var LEAD_SOURCE = 'Website';

// Output column (located by header name; fallback = AC).
var COL_HISTORY_FALLBACK = 29;   // AC
var HDR_HISTORY = 'Lead Interaction History';

var TZ = 'Asia/Kolkata';         // IST — matches the Walk-In implementation
var MONTHS = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};


// ═══════════════════════════════════════════════════════════════════════════
//  SMALL HELPERS  (identical to WalkInNewAutoPopulate.gs)
// ═══════════════════════════════════════════════════════════════════════════
function s_(v) { return (v === null || v === undefined) ? '' : String(v).trim(); }

function digits10_(v) {
  if (v === null || v === undefined) return '';
  var t;
  if (typeof v === 'number') { t = (v % 1 === 0) ? String(v) : String(v); }
  else { t = String(v).trim(); var m = t.match(/^(\d+)\.0+$/); if (m) t = m[1]; }
  var d = t.replace(/\D/g, '');
  return d.length >= 10 ? d.slice(-10) : d;
}

/** Parse a value (Date or many string formats) to a JS Date, or null. */
function parseDate_(v) {
  if (v instanceof Date && !isNaN(v.getTime())) return v;
  var t = s_(v);
  if (!t) return null;
  // dd-Mon-yyyy [hh:mm[:ss] AM/PM]  e.g. 01-Aug-2026 03:40 PM
  var m = t.match(/^(\d{1,2})[-\/ ]([A-Za-z]{3,})[-\/ ](\d{2,4})(?:[ ,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?)?/);
  if (m && MONTHS[m[2].slice(0,3).toLowerCase()] !== undefined) {
    var yr = parseInt(m[3], 10); if (yr < 100) yr += 2000;
    var hh = m[4] ? parseInt(m[4],10) : 0, mi = m[5] ? parseInt(m[5],10) : 0,
        ss = m[6] ? parseInt(m[6],10) : 0, ap = m[7] ? m[7].toLowerCase() : '';
    if (ap === 'pm' && hh < 12) hh += 12;
    if (ap === 'am' && hh === 12) hh = 0;
    return new Date(yr, MONTHS[m[2].slice(0,3).toLowerCase()], parseInt(m[1],10), hh, mi, ss);
  }
  // ISO yyyy-mm-dd[ hh:mm[:ss]]
  m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
  if (m) return new Date(+m[1], +m[2]-1, +m[3], m[4]?+m[4]:0, m[5]?+m[5]:0, m[6]?+m[6]:0);
  // slash m/d/yyyy or d/m/yyyy  (prefer d/m to match dayfirst=True — Website
  // "Enquriy Date" is dd/mm/yyyy hh:mm:ss, e.g. 27/06/2026 15:07:06)
  m = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:[ ,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?)?/);
  if (m) {
    var a = +m[1], b = +m[2], y = +m[3]; if (y < 100) y += 2000;
    var day = a, mon = b;                       // dayfirst
    if (a > 12 && b <= 12) { day = a; mon = b; }
    else if (b > 12 && a <= 12) { day = b; mon = a; }
    var H = m[4]?+m[4]:0, M = m[5]?+m[5]:0, S = m[6]?+m[6]:0, P = m[7]?m[7].toLowerCase():'';
    if (P === 'pm' && H < 12) H += 12; if (P === 'am' && H === 12) H = 0;
    return new Date(y, mon-1, day, H, M, S);
  }
  var d = new Date(t);
  return isNaN(d.getTime()) ? null : d;
}

function fmtDt_(d) { return Utilities.formatDate(d, TZ, 'dd-MMM-yyyy hh:mm a'); }


// ═══════════════════════════════════════════════════════════════════════════
//  INTERACTION-HISTORY PARSING  (identical to WalkInNewAutoPopulate.gs)
// ═══════════════════════════════════════════════════════════════════════════
/** Parse a master 'Lead Interaction History' cell -> [{src, dt(Date), cby}]. */
function parseHistory_(text) {
  var t = s_(text);
  if (!t) return [];
  var srcs = [], dates = [], cbys = [];
  var lines = t.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i], low = line.toLowerCase();
    if (low.indexOf('lead source:') === 0)      srcs  = splitCsv_(line);
    else if (low.indexOf('lead date:') === 0)    dates = splitCsv_(line);
    else if (low.indexOf('counselling by:') === 0) cbys = splitCsv_(line);
  }
  var out = [];
  for (var j = 0; j < dates.length; j++) {
    var dt = parseDate_(dates[j]);
    if (!dt) continue;
    out.push({ src: (j < srcs.length ? s_(srcs[j]) : ''),
               dt: dt,
               cby: (j < cbys.length ? s_(cbys[j]) : '') });
  }
  out.sort(function(a, b) { return a.dt - b.dt; });
  return out;
}
function splitCsv_(line) {
  var after = line.substring(line.indexOf(':') + 1);
  return after.split(',').map(function(x) { return x.trim(); });
}

/** One readable line per interaction, oldest first (identical to Walk-In). */
function cleanHistory_(history) {
  if (!history || !history.length) return '';
  var out = [];
  for (var i = 0; i < history.length; i++) {
    var h = history[i];
    var parts = [fmtDt_(h.dt), s_(h.src) || '—'];
    var cby = s_(h.cby);
    if (cby && cby !== '-' && cby !== '—') parts.push(cby);
    out.push(parts.join('  ·  '));
  }
  return out.join('\n');
}

/**
 * De-duplicate the FULL interaction history: if the Lead Date/Time and Lead
 * Source are the same, it is the same interaction and is shown only once (the
 * counsellor is NOT part of the identity). Keeps chronological order; if a
 * duplicate carries a counsellor and the kept one did not, the counsellor is
 * preserved. (Identical to WalkInNewAutoPopulate.gs.)
 */
function dedupeHistory_(history) {
  var seen = {}, out = [];
  var arr = history.slice().sort(function(a, b){ return a.dt - b.dt; });
  for (var i = 0; i < arr.length; i++) {
    var h = arr[i];
    if (!(h.dt instanceof Date) || isNaN(h.dt.getTime())) continue;
    // identity = source + date/time (to the minute) ONLY
    var key = s_(h.src).toLowerCase() + '|' + Utilities.formatDate(h.dt, TZ, 'yyyyMMddHHmm');
    if (seen[key] !== undefined) {
      var kept = out[seen[key]];
      if (!s_(kept.cby) && s_(h.cby)) kept.cby = h.cby;   // fill in a missing counsellor
      continue;
    }
    seen[key] = out.length;
    out.push({ src: h.src, dt: h.dt, cby: h.cby });
  }
  return out;
}


// ═══════════════════════════════════════════════════════════════════════════
//  DATA LOADING  (master history by mobile) + sheet/column resolution
// ═══════════════════════════════════════════════════════════════════════════
/** Find the 0-based column index whose header matches any candidate (trimmed,
 *  case-insensitive), or -1. (Identical to Walk-In.) */
function findCol_(header, candidates) {
  var norm = header.map(function(h){ return s_(h).toLowerCase(); });
  for (var c = 0; c < candidates.length; c++) {
    var idx = norm.indexOf(candidates[c].toLowerCase());
    if (idx >= 0) return idx;
  }
  return -1;
}

/** Read a sheet's first tab into {header:[], rows:[[...]]}. */
function readGrid_(spreadsheetId, tabName) {
  var ss = SpreadsheetApp.openById(spreadsheetId);
  var sh = tabName ? ss.getSheetByName(tabName) : ss.getSheets()[0];
  if (!sh) return { header: [], rows: [] };
  var lastRow = sh.getLastRow(), lastCol = sh.getLastColumn();
  if (lastRow < 1 || lastCol < 1) return { header: [], rows: [] };
  var values = sh.getRange(1, 1, lastRow, lastCol).getValues();
  return { header: values[0] || [], rows: values.slice(1) };
}

/** mobile10 -> the lead's PRIOR interaction history parsed from the master
 *  ("Consolidate Sales Tracking" → "Lead Interaction History"). */
function readMasterHistory_() {
  var g = readGrid_(MASTER_SHEET_ID, null);          // first tab
  var H = g.header;
  var cMob  = findCol_(H, ['Mobile Number','Mobile','Phone Number','Phone']);
  var cHist = findCol_(H, ['Lead Interaction History']);
  var idx = {};
  if (cMob < 0) return idx;
  for (var r = 0; r < g.rows.length; r++) {
    var mob = digits10_(g.rows[r][cMob]);
    if (!mob) continue;
    idx[mob] = cHist >= 0 ? parseHistory_(g.rows[r][cHist]) : [];
  }
  return idx;
}

/** Resolve the Website New sheet by its exact gid (falls back to name). */
function getWebsiteSheet_() {
  var ss = SpreadsheetApp.openById(WEBSITE_SHEET_ID);
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId() === WEBSITE_NEW_GID) return sheets[i];
  }
  return ss.getSheetByName(WEBSITE_NEW_TAB) || ss.getSheets()[0];
}

/** Ensure the "Lead Interaction History" header exists at column AC (only when
 *  it is not already present somewhere in the header row). Never touches data. */
function ensureHistoryHeader_(sheet, header) {
  header = header || sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), COL_HISTORY_FALLBACK)).getValues()[0];
  if (findCol_(header, [HDR_HISTORY]) >= 0) return;
  sheet.getRange(1, COL_HISTORY_FALLBACK).setValue(HDR_HISTORY);
}


// ═══════════════════════════════════════════════════════════════════════════
//  CORE  —  compute + write "Lead Interaction History" (AC) for one row
// ═══════════════════════════════════════════════════════════════════════════
/**
 * Compute + write the Lead Interaction History (AC) for one row of the Website
 * New tab. Merges the row's own Website interaction with the lead's prior master
 * history (by normalised mobile), de-dupes, and writes the readable string.
 * Safe on blanks; never throws upward. ONLY column AC is written.
 */
function processWebsiteRow_(sheet, rowNum, header) {
  if (rowNum < 2) return;                                // header row
  header = header || sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), COL_HISTORY_FALLBACK)).getValues()[0];

  var cMob  = findCol_(header, ['Mobile Number','Mobile','Phone Number','Phone','Contact Number']);
  var cTs   = findCol_(header, ['Enquriy Date','Enquiry Date','Timestamp','Time Stamp','Lead Date','Date']);
  var cCoun = findCol_(header, ['Counselling By','Counseling By','Counsellor']);

  var lastCol = Math.max(sheet.getLastColumn(), COL_HISTORY_FALLBACK);
  var rowVals = sheet.getRange(rowNum, 1, 1, lastCol).getValues()[0];

  var mob = cMob >= 0 ? digits10_(rowVals[cMob]) : '';
  if (!mob) return;                                      // no phone -> nothing to compute

  // --- lead's PREVIOUS history from the master (by normalised mobile) ---
  var masterIdx = readMasterHistory_();
  var prevHistory = masterIdx[mob] ? masterIdx[mob].slice() : [];

  // --- the NEWLY added Website interaction (included in the output) ---
  var wDt = cTs >= 0 ? parseDate_(rowVals[cTs]) : null;
  if (!wDt) wDt = new Date();                            // fall back to "now" if blank
  var wCby = cCoun >= 0 ? s_(rowVals[cCoun]) : '';
  var combined = prevHistory.concat([{ src: LEAD_SOURCE, dt: wDt, cby: wCby }]);

  // de-duplicate identical (source, minute) touches, then sort oldest-first
  combined = dedupeHistory_(combined);

  // --- write ONLY the Lead Interaction History column (AC) ---
  ensureHistoryHeader_(sheet, header);
  var colHist = findCol_(header, [HDR_HISTORY]);
  var histCol1 = (colHist >= 0 ? colHist + 1 : COL_HISTORY_FALLBACK);
  sheet.getRange(rowNum, histCol1).setValue(cleanHistory_(combined));
}


// ═══════════════════════════════════════════════════════════════════════════
//  TRIGGER HANDLERS  (installable — attach via setupWebsiteTriggers)
// ═══════════════════════════════════════════════════════════════════════════
/** Installable onFormSubmit handler (when Website New is fed by a Form). */
function onWebsiteFormSubmit(e) {
  try {
    var target = getWebsiteSheet_();
    var sh = e && e.range ? e.range.getSheet() : null;
    if (sh && sh.getSheetId && sh.getSheetId() !== WEBSITE_NEW_GID) return;  // other tab
    if (!sh) sh = target;
    processWebsiteRow_(sh, e && e.range ? e.range.getRow() : sh.getLastRow());
  } catch (err) {
    console.error('onWebsiteFormSubmit: ' + err);
  }
}

/**
 * Time-driven handler. Fills the AC history for rows that have a mobile but a
 * still-blank AC — this is what covers NEW web-app (doPost/appendRow) leads,
 * which no edit/form trigger sees. Idempotent and cheap when idle (it reads the
 * master history only if there is at least one blank row to fill).
 */
function onWebsiteTimer() {
  try {
    fillBlankWebsiteHistory_();
  } catch (err) {
    console.error('onWebsiteTimer: ' + err);
  }
}

/** Installable onEdit handler (when rows are typed/pasted manually). */
function onWebsiteEdit(e) {
  try {
    if (!e || !e.range) return;
    var sh = e.range.getSheet();
    if (!sh.getSheetId || sh.getSheetId() !== WEBSITE_NEW_GID) return;       // only the Website New tab
    var row = e.range.getRow();
    if (row < 2) return;                                  // header
    var header = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), COL_HISTORY_FALLBACK)).getValues()[0];
    // Ignore edits to the history output column itself (avoids redundant work).
    var colHist = findCol_(header, [HDR_HISTORY]);
    colHist = colHist >= 0 ? colHist + 1 : COL_HISTORY_FALLBACK;
    if (e.range.getColumn() === colHist) return;
    var cMob = findCol_(header, ['Mobile Number','Mobile','Phone Number','Phone','Contact Number']);
    if (cMob < 0) return;
    // Only act once the row actually has a mobile number.
    if (!digits10_(sh.getRange(row, cMob + 1).getValue())) return;
    processWebsiteRow_(sh, row, header);
  } catch (err) {
    console.error('onWebsiteEdit: ' + err);
  }
}


// ═══════════════════════════════════════════════════════════════════════════
//  SETUP + UTILITIES
// ═══════════════════════════════════════════════════════════════════════════
/**
 * Run ONCE to install the trigger(s) and ensure the AC header exists. Installs
 * an onFormSubmit trigger (only meaningful if a Form is attached; harmless
 * otherwise) and always an onEdit trigger for manual entry. Safe to re-run
 * (removes our previously-installed duplicates first).
 */
function setupWebsiteTriggers() {
  var ss = SpreadsheetApp.openById(WEBSITE_SHEET_ID);
  try { ensureHistoryHeader_(getWebsiteSheet_()); } catch (e) {}
  var existing = ScriptApp.getProjectTriggers();
  for (var i = 0; i < existing.length; i++) {
    var fn = existing[i].getHandlerFunction();
    if (fn === 'onWebsiteFormSubmit' || fn === 'onWebsiteEdit' || fn === 'onWebsiteTimer')
      ScriptApp.deleteTrigger(existing[i]);
  }
  var installed = [];
  // Time-driven: covers NEW web-app (doPost/appendRow) leads, which fire no
  // edit/form trigger. Runs every 5 minutes; idle runs are cheap (no master read
  // unless a blank AC row exists).
  ScriptApp.newTrigger('onWebsiteTimer').timeBased().everyMinutes(5).create();
  installed.push('timer(5m)');
  // onEdit: keeps manually typed/pasted rows updated instantly.
  ScriptApp.newTrigger('onWebsiteEdit').forSpreadsheet(ss).onEdit().create();
  installed.push('onEdit');
  // onFormSubmit: harmless — only fires if a Google Form is ever attached.
  try {
    ScriptApp.newTrigger('onWebsiteFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
    installed.push('onFormSubmit');
  } catch (e) {}
  Logger.log('Installed Website triggers: ' + installed.join(', '));
  return installed;
}

/** Optional: (re)compute the history for the LAST row — handy for testing. */
function testLastWebsiteRow() {
  var sh = getWebsiteSheet_();
  processWebsiteRow_(sh, sh.getLastRow());
}

/**
 * Fill the AC history for EVERY row that has a mobile but a still-blank AC.
 * Shared by the time-driven trigger (onWebsiteTimer) and the manual backfill.
 * Reads the whole tab once, and reads the master history ONLY if there is at
 * least one blank row to fill (so idle timer runs are cheap). Never overwrites a
 * row that already has history, so it is safe to run on any schedule.
 * Returns the number of rows filled.
 */
function fillBlankWebsiteHistory_() {
  var sh = getWebsiteSheet_();
  ensureHistoryHeader_(sh);
  var lastRow = sh.getLastRow(), lastCol = Math.max(sh.getLastColumn(), COL_HISTORY_FALLBACK);
  if (lastRow < 2) return 0;
  var grid = sh.getRange(1, 1, lastRow, lastCol).getValues();
  var header = grid[0];

  var colHist = findCol_(header, [HDR_HISTORY]);
  colHist = colHist >= 0 ? colHist : (COL_HISTORY_FALLBACK - 1);   // 0-based
  var cMob  = findCol_(header, ['Mobile Number','Mobile','Phone Number','Phone','Contact Number']);
  var cTs   = findCol_(header, ['Enquriy Date','Enquiry Date','Timestamp','Time Stamp','Lead Date','Date']);
  var cCoun = findCol_(header, ['Counselling By','Counseling By','Counsellor']);
  if (cMob < 0) return 0;

  // First pass: find rows needing a fill (mobile present, AC blank) — no master read yet.
  var todo = [];
  for (var r = 1; r < grid.length; r++) {                 // r=1 -> sheet row 2
    if (s_(grid[r][colHist])) continue;                   // already filled
    if (!digits10_(grid[r][cMob])) continue;              // no usable mobile
    todo.push(r);
  }
  if (!todo.length) return 0;                             // nothing to do -> skip master read

  var masterIdx = readMasterHistory_();                   // read master once, only when needed
  var filled = 0;
  for (var k = 0; k < todo.length; k++) {
    var rr = todo[k], sheetRow = rr + 1;
    var mob = digits10_(grid[rr][cMob]);
    var prev = masterIdx[mob] ? masterIdx[mob].slice() : [];
    var wDt = cTs >= 0 ? parseDate_(grid[rr][cTs]) : null; if (!wDt) wDt = new Date();
    var wCby = cCoun >= 0 ? s_(grid[rr][cCoun]) : '';
    var combined = dedupeHistory_(prev.concat([{ src: LEAD_SOURCE, dt: wDt, cby: wCby }]));
    sh.getRange(sheetRow, colHist + 1).setValue(cleanHistory_(combined));
    filled++;
  }
  SpreadsheetApp.flush();
  return filled;
}

/**
 * Optional one-off backfill for EXISTING blank AC rows. Thin wrapper around the
 * shared fill so behaviour is identical to the time-driven trigger.
 */
function backfillBlankWebsiteRows() {
  return fillBlankWebsiteHistory_();
}