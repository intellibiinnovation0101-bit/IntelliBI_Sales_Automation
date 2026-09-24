/**
 * WalkInNewAutoPopulate.gs
 * =========================================================================
 * Auto-populates two columns on the "Walk-In New" tab of the
 * "Student Inquiry Tracker – Walk-in / Call / WhatsApp / Campaign / Website /
 *  Bot Reply" spreadsheet whenever a NEW Walk-In record is added:
 *
 *     AE  ->  Lead Interaction History
 *     AF  ->  Conversion Chance %
 *
 * The logic is a faithful port of pyLeadFollowUpAnalysisReport.py:
 *   - "Lead Interaction History" = clean_history(history), one line per
 *     interaction, oldest first: "dd-Mon-yyyy hh:mm a  ·  <source>  ·  <by>".
 *   - "Conversion Chance %" = the same weight-of-evidence (naive-Bayes
 *     log-odds) model, trained on the live master ("Consolidate Sales
 *     Tracking Report"), scored on the lead's LATEST feature set.
 *
 * IMPORTANT — the newly added Walk-In record is INCLUDED in both outputs:
 *     Previous Lead History  +  Newly Added Walk-In  =  Latest Lead Info
 * The new row is merged into the lead's master history (by normalised mobile)
 * before the history string and the conversion score are computed.
 *
 * Only these two columns are written. No existing column, formula, validation,
 * formatting or data-entry logic is touched.
 *
 * SETUP (run once): open Extensions -> Apps Script, paste this file, then run
 *   setupTriggers()   and authorise. That installs the trigger(s).
 * =========================================================================
 */

// ── CONFIG ────────────────────────────────────────────────────────────────
var WALKIN_NEW_TAB   = 'Walk-In New';
var MASTER_SHEET_ID  = '1zZQjXnMJD96Ca0MNyfSt4-XS0z5w3rT7WPdb9qsP1Gs'; // Consolidate Sales Tracking
var MEET_SHEET_ID    = '1dlWiU5K7kFi014p8pgH4PbMuoy4QbwMHh48YxNOqjpg'; // Google Meet form
var WALKIN_SHEET_ID  = '19Ecal2JpOL1FbzGKWlno4ZywG3HsXsiK-BmMzew5TqQ'; // this spreadsheet (Walk-In form)
var ENROLL_SHEET_ID  = '1oaXxg3JdtxFp8lFWijIMZKaMZvS0SiglI1K2JTrN2fs'; // Student Admission Responses (New Enroll) — real admission outcomes

// Output columns (located by header name; these are the fallbacks = AE, AF).
var COL_HISTORY_FALLBACK = 31;   // AE
var COL_CHANCE_FALLBACK  = 32;   // AF
var HDR_HISTORY = 'Lead Interaction History';
var HDR_CHANCE  = 'Conversion Chance %';

var TZ = 'Asia/Kolkata';         // IST — matches the Python report

// ── Conversion-model tunables (identical to the Python) ────────────────────
var SMOOTH_ALPHA = 5.0;
var SHRINK_K     = 15.0;
var WOE_DAMP     = 0.75;
var PROB_FLOOR   = 0.01, PROB_CEIL = 0.99;
var NEUTRAL_VALUES = {'Unknown': 1, 'Other': 1, 'none': 1};
var FEATURE_ORDER = ['platform_primary', 'reach', 'interactions', 'referral',
                     'work', 'timeline', 'city', 'meet', 'walkin', 'speed',
                     // richer journey + intent features (all pre-outcome, leakage-safe)
                     'tenure', 'recency', 'course', 'lead_grade', 'notes'];
var CONVERTED_STATUS_MATCH = 'admission confirmed';

// Lead Status values that ARE (or imply) the final OUTCOME. These are training
// LABELS elsewhere and must never leak in as a prediction-time feature, so
// leadGradeBucket_() maps them to the neutral 'Unknown' (0 contribution).
var LEAD_STATUS_OUTCOME_TOKENS = [
  'admission confirmed','confirmed','enrolled','enroll','joined','paid',
  'converted','not interested','irrelevant','lost','dropped','backed',
  'backout','back out','closed','rejected','declin'];
// Pre-outcome intent / objection cues read from Remarks (meaning, not raw text).
var NOTE_POS = ['interested','ready','will join','wants to join','keen','excited',
  'book','booking','seat','confirm slot','demo','syllabus','curriculum','fee',
  'fees','emi','installment','instalment','discount','scholarship','scheduled',
  'positive','follow up','call back','callback','visit','coming','start','batch'];
var NOTE_STRONG = ['emi','installment','instalment','fee','fees','discount',
  'scholarship','book','seat','ready','will join','wants to join','advance',
  'token','registration'];
var NOTE_OBJECTION = ['expensive','costly','high fee','budget','afford','think',
  'thinking','later','next month','postpone','hold','busy','no time','compare',
  'comparing','competitor','confused','decide','family','discuss','revert','get back'];

var MONTHS = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};


// ═══════════════════════════════════════════════════════════════════════════
//  SMALL HELPERS  (ports of s / digits10 / yes / sigmoid / parse_dt)
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

function yes_(v) {
  var t = s_(v).toLowerCase();
  return t === 'yes' || t === 'y' || t === 'true' || t === '1';
}

function sigmoid_(x) {
  if (x >= 0) { var z = Math.exp(-x); return 1 / (1 + z); }
  var e = Math.exp(x); return e / (1 + e);
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
  // slash m/d/yyyy or d/m/yyyy  (prefer d/m to match the Python dayfirst=True)
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
//  INTERACTION-HISTORY PARSING  (ports of parse_history / clean_history)
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

/** One readable line per interaction, oldest first (port of clean_history). */
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

function platformsInSequence_(history, fallbackCsv) {
  var seq = [];
  for (var i = 0; i < history.length; i++) {
    var n = s_(history[i].src);
    if (n && n !== '—' && seq.indexOf(n) === -1) seq.push(n);
  }
  var fb = s_(fallbackCsv).split(',');
  for (var k = 0; k < fb.length; k++) {
    var p = fb[k].trim();
    if (p && seq.indexOf(p) === -1) seq.push(p);
  }
  return seq;
}

function responseSpeedBucket_(history) {
  if (history.length < 2) return 'single_touch';
  var gaps = [];
  for (var i = 1; i < history.length; i++) {
    var g = (history[i].dt - history[i-1].dt) / 86400000.0;
    if (g >= 0) gaps.push(g);
  }
  if (!gaps.length) return 'single_touch';
  gaps.sort(function(a,b){ return a-b; });
  var med = gaps[Math.floor(gaps.length / 2)];
  if (med < 1) return 'same_day';
  if (med <= 3) return 'fast_3d';
  if (med <= 7) return 'week';
  return 'delayed';
}

/** Engagement SPAN: days from first to last interaction (port of tenure_bucket).
 *  Intrinsic to the journey, so it means the same at training and scoring. */
function tenureBucket_(history) {
  if (!history || history.length < 2) return 'single_touch';
  var span = (history[history.length - 1].dt - history[0].dt) / 86400000.0;
  if (span < 1) return 'same_day';
  if (span <= 7) return 'within_week';
  if (span <= 30) return 'within_month';
  if (span <= 90) return '1-3_months';
  return 'over_3_months';
}

/** Recency of the latest interaction (port of recency_bucket).
 *   • scoring (asOf = a Date): days since the LAST interaction — real staleness.
 *   • training (asOf = null) : the TRAILING gap (last minus second-last touch).
 *  Both measure the same "most-recent-silence" length, so no time leakage between
 *  old and new leads. */
function recencyBucket_(history, asOf) {
  if (!history || !history.length) return 'Unknown';
  var last = history[history.length - 1].dt;
  var days;
  if (asOf) {
    days = (asOf - last) / 86400000.0;
  } else if (history.length >= 2) {
    days = (last - history[history.length - 2].dt) / 86400000.0;
  } else {
    return 'Unknown';
  }
  if (days < 0) days = 0;
  if (days <= 3) return 'fresh_3d';
  if (days <= 7) return 'week';
  if (days <= 30) return 'month';
  if (days <= 90) return 'cooling';
  return 'cold';
}

/** Course/technology family (port of norm_course). */
function normCourse_() {
  var t = '';
  for (var i = 0; i < arguments.length; i++) t += ' ' + s_(arguments[i]).toLowerCase();
  if (!t.trim()) return 'Unknown';
  function has(ks){ for (var j=0;j<ks.length;j++) if (t.indexOf(ks[j])>=0) return true; return false; }
  var ai = has(['artificial intelligence','gen ai','genai','generative','machine learning','(ml)',' ml','agentic']);
  var de = has(['data engineer','azure data','etl','databrick','spark']);
  var da = has(['data analy','analytics','power bi','powerbi','tableau']);
  var fs = has(['full stack','fullstack','.net','dotnet','java','python dev','frontend','front end','backend','web dev']);
  var test = has(['testing','qa ','automation test','selenium']);
  if (de && ai) return 'DataEngineering_AI';
  if (de) return 'DataEngineering';
  if (da && ai) return 'DataAnalytics_AI';
  if (da) return 'DataAnalytics';
  if (ai) return 'AI_ML';
  if (fs) return 'FullStack';
  if (test) return 'Testing';
  return 'OtherCourse';
}

/** Lead Status -> pre-outcome INTENT grade (port of lead_grade_bucket). Terminal
 *  outcome values are neutralised to 'Unknown' so the finalized outcome can never
 *  leak into an active lead's features. */
function leadGradeBucket_(leadStatus) {
  var a = s_(leadStatus).toLowerCase();
  if (!a) return 'Unknown';
  for (var i = 0; i < LEAD_STATUS_OUTCOME_TOKENS.length; i++) {
    if (a.indexOf(LEAD_STATUS_OUTCOME_TOKENS[i]) >= 0) return 'Unknown';   // outcome -> neutral
  }
  if (a.indexOf('hot') >= 0) return 'Hot';
  if (a.indexOf('warm') >= 0) return 'Warm';
  if (a.indexOf('cold') >= 0) return 'Cold';
  if (a.indexOf('casual') >= 0 || a.indexOf('explor') >= 0) return 'Casual';
  if (a.indexOf('follow') >= 0) return 'FollowUp';
  if (a.indexOf('unable') >= 0 || a.indexOf('not reach') >= 0 ||
      a.indexOf('unreach') >= 0 || a.indexOf('no response') >= 0) return 'Unreachable';
  if (a.indexOf('interest') >= 0) return 'Interested';   // "interested" (negation neutralised above)
  return 'Other';
}

/** Remarks -> pre-outcome intent bucket (port of notes_signal):
 *  strong_positive | positive | objection | mixed | neutral | none. Deterministic
 *  intent reading — captures meaning, not raw text; terminal outcomes not encoded. */
function notesSignal_(remarks) {
  var a = s_(remarks).toLowerCase();
  if (!a) return 'none';
  function has(ks){ for (var j=0;j<ks.length;j++) if (a.indexOf(ks[j])>=0) return true; return false; }
  var strong = has(NOTE_STRONG), pos = has(NOTE_POS), obj = has(NOTE_OBJECTION);
  if (strong && !obj) return 'strong_positive';
  if (pos && !obj) return 'positive';
  if (obj && !pos) return 'objection';
  if (obj && pos) return 'mixed';
  return 'neutral';
}


// ═══════════════════════════════════════════════════════════════════════════
//  NORMALISERS (feature bucketing — identical rules to the Python)
// ═══════════════════════════════════════════════════════════════════════════
function normPlatform_(name) {
  var n = s_(name).toLowerCase();
  if (!n) return 'Unknown';
  if (n.indexOf('referr') >= 0) return 'Referral';
  if (n.indexOf('walk') >= 0) return 'Walk-In';
  if (n.indexOf('website') >= 0 || n === 'web') return 'Website';
  if (n.indexOf('whats') >= 0) return 'WhatsApp';
  if (n.indexOf('call') >= 0) return 'Call';
  if (n.indexOf('meta') >= 0 || n.indexOf('facebook') >= 0 || n.indexOf('insta') >= 0) return 'Meta';
  if (n.indexOf('intellibi') >= 0) return 'IntelliBI';
  if (n.indexOf('bot') >= 0) return 'Bot';
  if (n.indexOf('campaign') >= 0) return 'Campaign';
  if (n.indexOf('master') >= 0) return 'Masterclass';
  if (n.indexOf('re-targ') >= 0 || n.indexOf('retarg') >= 0) return 'Re-Targeting';
  return s_(name);
}

function normWork_() {
  var t = '';
  for (var i = 0; i < arguments.length; i++) t += ' ' + s_(arguments[i]).toLowerCase();
  if (!t.trim()) return 'Unknown';
  if (t.indexOf('working') >= 0 || t.indexOf('employ') >= 0 || t.indexOf('job') >= 0 || t.indexOf('professional') >= 0) return 'Working';
  if (t.indexOf('break') >= 0) return 'CareerBreak';
  if (t.indexOf('student') >= 0) return 'Student';
  if (t.indexOf('fresher') >= 0 || t.indexOf('passed out') >= 0 || t.indexOf('pass out') >= 0) return 'Fresher';
  return 'Other';
}

function normTimeline_(v) {
  var t = s_(v).toLowerCase();
  if (!t) return 'Unknown';
  if (t.indexOf('immediat') >= 0 || t.indexOf('within 1 week') >= 0 || t.indexOf('1 week') >= 0) return 'Immediate';
  if (t.indexOf('15') >= 0) return 'Within15Days';
  if (t.indexOf('1 month') >= 0 || t.indexOf('one month') >= 0) return 'Within1Month';
  if (t.indexOf('2 month') >= 0 || t.indexOf('two month') >= 0) return 'Within2Months';
  if (t.indexOf('explor') >= 0 || t.indexOf('decid') >= 0) return 'Exploring';
  return 'Other';
}

function normCity_(v) {
  var t = s_(v).toLowerCase();
  if (!t) return 'Unknown';
  if (t.indexOf('pune') >= 0 || t.indexOf('pimpri') >= 0 || t.indexOf('chinchwad') >= 0 || t.indexOf('pcmc') >= 0) return 'Pune';
  return 'OtherCity';
}

function interactionsBucket_(n) {
  var x = parseInt(n, 10); if (isNaN(x)) x = 0;
  if (x <= 1) return '1';
  if (x === 2) return '2';
  if (x <= 4) return '3-4';
  return '5+';
}

function meetState_(scheduled, attendanceStatus) {
  var a = s_(attendanceStatus).toLowerCase();
  if (a) {
    if (a.indexOf('attended') >= 0 || a.indexOf('present') >= 0 || a.indexOf('joined') >= 0 || a.indexOf('done') >= 0 || a.indexOf('completed') >= 0) return 'attended';
    if (a.indexOf('no show') >= 0 || a.indexOf('no-show') >= 0 || a.indexOf('noshow') >= 0 || a.indexOf('absent') >= 0 || a.indexOf('not attend') >= 0 || a.indexOf('missed') >= 0) return 'noshow';
    return 'scheduled';
  }
  return scheduled ? 'scheduled' : 'none';
}

function walkinState_(scheduled, attended) {
  if (attended) return 'attended';
  return scheduled ? 'scheduled' : 'none';
}

function isConvertedStatus_(admissionStatus) {
  return s_(admissionStatus).toLowerCase().indexOf(CONVERTED_STATUS_MATCH) >= 0;
}

/** LOST outcome = not-interested / backed-out / dropped (port of is_lost_status).
 *  Together with "converted", this defines a RESOLVED lead — a lead whose final
 *  outcome is known, so the model never trains on still-open (unknown) leads. */
function isLostStatus_(admissionStatus, leadStatus, backout) {
  var a = s_(admissionStatus).toLowerCase();
  var l = s_(leadStatus).toLowerCase();
  if (a.indexOf('not interested') >= 0 || a.indexOf('irrelevant') >= 0 ||
      a.indexOf('backed out') >= 0 || a.indexOf('backout') >= 0 ||
      a.indexOf('dropped') >= 0 || a.indexOf('lost') >= 0) return true;
  if (l === 'not interested' || l === 'lost' || l === 'dropped') return true;
  if (s_(backout)) return true;
  return false;
}


// ═══════════════════════════════════════════════════════════════════════════
//  FEATURE EXTRACTION  (port of build_features)
// ═══════════════════════════════════════════════════════════════════════════
function buildFeatures_(o) {
  var prim = (o.platforms && o.platforms.length) ? normPlatform_(o.platforms[0]) : 'Unknown';
  return {
    platform_primary: o.referral ? 'Referral' : prim,
    reach: (o.platforms && o.platforms.length > 1) ? 'multi' : 'single',
    interactions: interactionsBucket_(o.num_interactions),
    referral: o.referral ? 'yes' : 'no',
    work: o.work,
    timeline: o.timeline,
    city: o.city,
    meet: o.meet_state,
    walkin: o.walkin_state,
    speed: responseSpeedBucket_(o.history),       // cadence (median gap)
    tenure: tenureBucket_(o.history),             // engagement span
    recency: recencyBucket_(o.history, o.as_of || null),  // latest-interaction recency
    course: normCourse_(o.course || ''),          // course/technology family
    lead_grade: leadGradeBucket_(o.lead_status || ''),    // intent grade (outcome-safe)
    notes: notesSignal_(o.notes || '')            // remarks intent / sentiment
  };
}


// ═══════════════════════════════════════════════════════════════════════════
//  WEIGHT-OF-EVIDENCE CONVERSION MODEL  (port of ConversionModel)
// ═══════════════════════════════════════════════════════════════════════════
function trainModel_(samples) {
  var nTrain = samples.length;
  var nPos = 0;
  for (var i = 0; i < nTrain; i++) if (samples[i].y) nPos++;
  var baseRate = nTrain ? (nPos / nTrain) : 0.05;
  var br = Math.min(Math.max(baseRate, 1e-4), 1 - 1e-4);
  var baseLogodds = Math.log(br / (1 - br));

  var woe = {};
  for (var fi = 0; fi < FEATURE_ORDER.length; fi++) {
    var feat = FEATURE_ORDER[fi];
    var cells = {};                              // value -> [n, pos]
    for (var j = 0; j < nTrain; j++) {
      var v = samples[j].f[feat]; if (v === undefined) v = 'Unknown';
      if (!cells[v]) cells[v] = [0, 0];
      cells[v][0] += 1;
      if (samples[j].y) cells[v][1] += 1;
    }
    var table = {};
    for (var val in cells) {
      var n = cells[val][0], pos = cells[val][1];
      var rate = (pos + SMOOTH_ALPHA * br) / (n + SMOOTH_ALPHA);
      rate = Math.min(Math.max(rate, 1e-4), 1 - 1e-4);
      if (NEUTRAL_VALUES[val]) { table[val] = 0.0; continue; }   // contributes nothing
      var w = Math.log(rate / (1 - rate)) - baseLogodds;
      var shrink = n / (n + SHRINK_K);
      table[val] = w * shrink;
    }
    woe[feat] = table;
  }
  return { woe: woe, baseLogodds: baseLogodds, baseRate: baseRate,
           nTrain: nTrain, nPos: nPos };
}

function scoreModel_(model, features) {
  var shift = 0.0;
  for (var fi = 0; fi < FEATURE_ORDER.length; fi++) {
    var feat = FEATURE_ORDER[fi];
    var v = features[feat]; if (v === undefined) v = 'Unknown';
    var tbl = model.woe[feat] || {};
    shift += (tbl[v] !== undefined ? tbl[v] : 0.0);
  }
  var p = sigmoid_(model.baseLogodds + WOE_DAMP * shift);
  return Math.min(Math.max(p, PROB_FLOOR), PROB_CEIL);
}


// ═══════════════════════════════════════════════════════════════════════════
//  DATA LOADING  (master index, meet attendance, walk-in attendance)
// ═══════════════════════════════════════════════════════════════════════════
/** Find the 0-based column index whose header matches any candidate (trimmed,
 *  case-insensitive), or -1. */
function findCol_(header, candidates) {
  var norm = header.map(function(h){ return s_(h).toLowerCase(); });
  for (var c = 0; c < candidates.length; c++) {
    var want = candidates[c].toLowerCase();
    var idx = norm.indexOf(want);
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

/** mobile10 -> master lead record (history, features inputs, converted flag). */
function readMasterIndex_() {
  var g = readGrid_(MASTER_SHEET_ID, null);        // first tab
  var H = g.header;
  var cMob   = findCol_(H, ['Mobile Number','Mobile','Phone Number','Phone']);
  var cHist  = findCol_(H, ['Lead Interaction History']);
  var cPlat  = findCol_(H, ['Platforms Used']);
  var cNint  = findCol_(H, ['Number of Interactions','No of Interactions']);
  var cRef   = findCol_(H, ['IsReferral','Is Referral']);
  var cRefn  = findCol_(H, ["Referrer's Name",'Referrer Name']);
  var cStat  = findCol_(H, ['Current Status','Candidate Type']);
  var cExp   = findCol_(H, ['Total Years of Experience','Experience']);
  var cCity  = findCol_(H, ['Current City','City']);
  var cTl    = findCol_(H, ['When are you planning to take admission?','Admission Plan Time','Planning to take admission']);
  var cAdmit = findCol_(H, ['Admission Status']);
  var cLead  = findCol_(H, ['Lead Status']);
  var cBack  = findCol_(H, ['Backout Reason','BackOutReason']);
  var cGmsch = findCol_(H, ['IsGoogleMeetSchedule','Google Meet Schedule']);
  var cCourse  = findCol_(H, ['Course Advised','Which technology are you interested in learning?','Course Interested In']);
  var cCourse2 = findCol_(H, ['Which technology are you interested in learning?','Course Advised','Course Interested In']);
  var cRem   = findCol_(H, ['Remarks','Counsellor Notes']);

  var idx = {};
  if (cMob < 0) return idx;
  for (var r = 0; r < g.rows.length; r++) {
    var row = g.rows[r];
    var mob = digits10_(row[cMob]);
    if (!mob) continue;
    var hist = cHist >= 0 ? parseHistory_(row[cHist]) : [];
    var plats = platformsInSequence_(hist, cPlat >= 0 ? row[cPlat] : '');
    idx[mob] = {                                   // live master row (authoritative)
      mobile: mob,
      history: hist,
      platforms: plats,
      num_interactions: (cNint >= 0 && s_(row[cNint])) ? s_(row[cNint]) : String(hist.length),
      referral: (cRef >= 0 && yes_(row[cRef])) || (cRefn >= 0 && !!s_(row[cRefn])),
      work: normWork_(cStat >= 0 ? row[cStat] : '', cExp >= 0 ? row[cExp] : ''),
      status_raw: cStat >= 0 ? s_(row[cStat]) : '',
      experience_raw: cExp >= 0 ? s_(row[cExp]) : '',
      city_raw: cCity >= 0 ? s_(row[cCity]) : '',
      timeline_raw: cTl >= 0 ? s_(row[cTl]) : '',
      platforms_csv: cPlat >= 0 ? s_(row[cPlat]) : '',
      admission_status: cAdmit >= 0 ? s_(row[cAdmit]) : '',
      lead_status: cLead >= 0 ? s_(row[cLead]) : '',
      backout: cBack >= 0 ? s_(row[cBack]) : '',
      gmeet_sched: cGmsch >= 0 ? yes_(row[cGmsch]) : false,
      course: (cCourse >= 0 && s_(row[cCourse])) ? s_(row[cCourse])
              : (cCourse2 >= 0 ? s_(row[cCourse2]) : ''),
      remarks: cRem >= 0 ? s_(row[cRem]) : ''
    };
  }
  return idx;
}

/** mobile10 -> Google-Meet attendance status string. */
function loadMeetAttendance_() {
  var out = {};
  try {
    var g = readGrid_(MEET_SHEET_ID, null);
    var H = g.header;
    var cPh = findCol_(H, ['Phone Number','Mobile Number','Mobile','Phone','Contact Number']);
    var cAt = findCol_(H, ['LeadAttendanceStatus','Lead Attendance Status','Attendance Status','Attendance']);
    if (cPh < 0) return out;
    for (var r = 0; r < g.rows.length; r++) {
      var m = digits10_(g.rows[r][cPh]);
      if (m) out[m] = cAt >= 0 ? s_(g.rows[r][cAt]) : 'Scheduled';
    }
  } catch (e) { /* meet form optional */ }
  return out;
}

/** Set (as a map) of mobile10 present in the Walk-In form (presence == attended). */
function loadWalkinAttended_() {
  var out = {};
  try {
    var g = readGrid_(WALKIN_SHEET_ID, null);       // first tab of the tracker
    var H = g.header;
    var cPh = findCol_(H, ['Phone Number','Mobile Number','Mobile','Phone','Contact Number','Contact']);
    if (cPh < 0) return out;
    for (var r = 0; r < g.rows.length; r++) {
      var m = digits10_(g.rows[r][cPh]);
      if (m) out[m] = true;
    }
  } catch (e) { /* optional */ }
  return out;
}

/** Map (mobile10 -> true) of leads that ACTUALLY enrolled — the real admission
 *  outcome — read from the Student Admission Responses / New Enroll sheet. These
 *  become extra POSITIVE labels so the model learns from confirmed admissions,
 *  exactly like the enhanced Python pipeline. Tries the known tab names, then the
 *  first tab. Optional: any failure just yields no extra positives. */
function loadEnrolledMobiles_() {
  var out = {};
  var tabs = ['New Enroll', 'Enroll', 'Enrolled', 'Student Admission Responses',
              'Admission Responses', 'Responses', null];
  for (var ti = 0; ti < tabs.length; ti++) {
    try {
      var g = readGrid_(ENROLL_SHEET_ID, tabs[ti]);
      var H = g.header;
      if (!H || !H.length) continue;
      var cPh = findCol_(H, ['Phone Number','Mobile Number','Mobile','Phone','Contact Number','Contact']);
      if (cPh < 0) continue;
      for (var r = 0; r < g.rows.length; r++) {
        var m = digits10_(g.rows[r][cPh]);
        if (m) out[m] = true;
      }
      if (Object.keys(out).length) return out;     // found the enrolment data
    } catch (e) { /* try the next candidate tab */ }
  }
  return out;
}

/** Neutral feature set for an OLDER enrolled lead that has NO Consolidated match,
 *  so missing history never fabricates signal (neutral values score to nothing). */
function minimalFeatures_() {
  return {
    platform_primary: 'Unknown', reach: 'single',
    interactions: interactionsBucket_(0), referral: 'no',
    work: 'Unknown', timeline: 'Unknown', city: 'Unknown',
    meet: 'none', walkin: 'none', speed: responseSpeedBucket_([])
  };
}

/** Build (features, converted) training samples — ENHANCED, self-learning:
 *    • Duplicate-safe: the master is keyed by mobile (one row per lead); enrolled
 *      leads with no master match are added once.
 *    • Enrolled positives: a lead counts as CONVERTED if Admission Status =
 *      "Admission Confirmed" OR its phone is in the enrolled sheet.
 *    • Resolved-only: train ONLY on leads whose outcome is known (converted OR
 *      lost); still-open leads are skipped — no data leakage.
 *    • Consolidated journey enrichment: features come from the master lead journey
 *      wherever a match exists.
 *    • The enrolled sheet corrects the label ONLY for a lead that HAS a real
 *      journey (a master match). Enrolled phones with NO journey are NOT injected
 *      as neutral-feature positives — they carry nothing to learn from and only
 *      distort the base rate (the same fix applied in the Python pipeline).
 *  Retrained on every run, so it keeps improving as admissions/leads grow. */
function buildTrainingSamples_(masterIdx, meetMap, walkinSet, enrolledSet) {
  enrolledSet = enrolledSet || {};
  var samples = [];
  for (var mob in masterIdx) {
    var m = masterIdx[mob];
    var converted = isConvertedStatus_(m.admission_status) || !!enrolledSet[mob];
    var lost = isLostStatus_(m.admission_status, m.lead_status, m.backout);
    if (!(converted || lost)) continue;            // resolved-only: skip still-open leads
    var mstate = meetState_(false, meetMap[mob] || '');
    var wstate = walkinState_(false, !!walkinSet[mob]);
    var feats = buildFeatures_({
      history: m.history, platforms: m.platforms,
      num_interactions: (m.num_interactions || String(m.history.length)),
      referral: !!m.referral,
      work: m.work || 'Unknown',
      timeline: normTimeline_(m.timeline_raw),
      city: normCity_(m.city_raw),
      meet_state: mstate, walkin_state: wstate,
      course: m.course, lead_status: m.lead_status, notes: m.remarks,
      as_of: null                                  // training: trailing-gap recency
    });
    samples.push({ f: feats, y: converted });
  }
  return samples;
}


// ═══════════════════════════════════════════════════════════════════════════
//  CORE  —  compute the two columns for one Walk-In New row
// ═══════════════════════════════════════════════════════════════════════════
/**
 * Compute + write "Lead Interaction History" (AE) and "Conversion Chance %"
 * (AF) for one row of the Walk-In New tab. Includes the row's own data merged
 * with the lead's prior master history. Safe on blanks; never throws upward.
 */
function processWalkInRow_(sheet, rowNum, header) {
  header = header || sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];

  var cMob  = findCol_(header, ['Mobile Number','Mobile','Phone Number','Phone','Contact Number']);
  var cTs   = findCol_(header, ['Timestamp','Time Stamp','Walk-In Date & Time','Date']);
  var cCoun = findCol_(header, ['Counselling By','Counsellor']);
  var cStat = findCol_(header, ['Current Status','Candidate Type']);
  var cExp  = findCol_(header, ['Total Years of Experience','Experience']);
  var cCity = findCol_(header, ['Current City','City']);
  var cTl   = findCol_(header, ['When are you planning to take admission?','Admission Plan Time']);
  var cRef  = findCol_(header, ['IsReferral','Is Referral']);
  var cRefn = findCol_(header, ["Referrer's Name",'Referrer Name']);
  var cCourse = findCol_(header, ['Course Interested In','Course Advised','Which technology are you interested in learning?']);
  var cNotes  = findCol_(header, ['Counsellor Notes','Remarks']);
  var cLead   = findCol_(header, ['Lead Status']);

  var lastCol = sheet.getLastColumn();
  var rowVals = sheet.getRange(rowNum, 1, 1, lastCol).getValues()[0];

  var mob = cMob >= 0 ? digits10_(rowVals[cMob]) : '';
  if (!mob) return;                                  // no phone -> nothing to compute

  // --- load master (training + prior history) and attendance lookups ---
  var masterIdx = readMasterIndex_();
  var meetMap   = loadMeetAttendance_();
  var walkinSet = loadWalkinAttended_();
  var enrolledSet = loadEnrolledMobiles_();          // real admission outcomes (positives)

  // --- lead's PREVIOUS history from the master (by normalised mobile) ---
  var m = masterIdx[mob] || null;
  var prevHistory = m ? m.history.slice() : [];

  // --- the NEWLY added Walk-In interaction (included in both outputs) ---
  var wDt = cTs >= 0 ? parseDate_(rowVals[cTs]) : null;
  if (!wDt) wDt = new Date();                        // fall back to "now" if blank
  var wCby = cCoun >= 0 ? s_(rowVals[cCoun]) : '';
  var combined = prevHistory.concat([{ src: 'Walk-In', dt: wDt, cby: wCby }]);

  // de-duplicate identical (source, minute, by) touches, then sort oldest-first
  combined = dedupeHistory_(combined);

  // --- LATEST feature inputs: the Walk-In value wins where present, else master ---
  var statusRaw = (cStat >= 0 && s_(rowVals[cStat])) ? s_(rowVals[cStat]) : (m ? m.status_raw : '');
  var expRaw    = (cExp  >= 0 && s_(rowVals[cExp]))  ? s_(rowVals[cExp])  : (m ? m.experience_raw : '');
  var cityRaw   = (cCity >= 0 && s_(rowVals[cCity])) ? s_(rowVals[cCity]) : (m ? m.city_raw : '');
  var tlRaw     = (cTl   >= 0 && s_(rowVals[cTl]))   ? s_(rowVals[cTl])   : (m ? m.timeline_raw : '');
  var refFlag   = (cRef >= 0 && yes_(rowVals[cRef])) ||
                  (cRefn >= 0 && !!s_(rowVals[cRefn])) ||
                  (m ? !!m.referral : false);
  var platsCsv  = m ? m.platforms_csv : '';
  var courseRaw = (cCourse >= 0 && s_(rowVals[cCourse])) ? s_(rowVals[cCourse]) : (m ? m.course : '');
  var notesRaw  = (cNotes  >= 0 && s_(rowVals[cNotes]))  ? s_(rowVals[cNotes])  : (m ? m.remarks : '');
  var leadRaw   = (cLead   >= 0 && s_(rowVals[cLead]))   ? s_(rowVals[cLead])   : (m ? m.lead_status : '');

  var feats = buildFeatures_({
    history: combined,
    platforms: platformsInSequence_(combined, platsCsv),
    num_interactions: String(combined.length),      // includes the new Walk-In
    referral: refFlag,
    work: normWork_(statusRaw, expRaw),
    timeline: normTimeline_(tlRaw),
    city: normCity_(cityRaw),
    meet_state: meetState_(m ? m.gmeet_sched : false, meetMap[mob] || ''),
    walkin_state: 'attended',                        // this lead just walked in
    course: courseRaw, lead_status: leadRaw, notes: notesRaw,
    as_of: wDt                                       // scoring: recency vs the walk-in time
  });

  // --- train the same WoE model on the master and score this lead ---
  var model = trainModel_(buildTrainingSamples_(masterIdx, meetMap, walkinSet, enrolledSet));
  var p = scoreModel_(model, feats);
  var chance = Math.round(p * 1000) / 10;            // e.g. 42.3

  // --- write ONLY the two output columns ---
  var colHist = findCol_(header, [HDR_HISTORY]);
  var colChan = findCol_(header, [HDR_CHANCE]);
  var histCol1 = (colHist >= 0 ? colHist + 1 : COL_HISTORY_FALLBACK);
  var chanCol1 = (colChan >= 0 ? colChan + 1 : COL_CHANCE_FALLBACK);
  sheet.getRange(rowNum, histCol1).setValue(cleanHistory_(combined));

  // Conversion Chance %: show with the "%" symbol (55 -> "55%", 42.5 -> "42.5%")
  // and make it BOLD when strictly greater than 50%, else normal font.
  var chanCell = sheet.getRange(rowNum, chanCol1);
  chanCell.setValue(String(chance) + '%');
  chanCell.setFontWeight(chance > 50 ? 'bold' : 'normal');
}

/**
 * De-duplicate the FULL interaction history: if the Lead Date/Time and Lead
 * Source are the same, it is the same interaction and is shown only once
 * (the counsellor is NOT part of the identity). Applied to the whole history,
 * not just the new Walk-In. Keeps chronological order; if a duplicate carries a
 * counsellor and the kept one did not, the counsellor is preserved.
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
//  TRIGGER HANDLERS  (installable — attach via setupTriggers)
// ═══════════════════════════════════════════════════════════════════════════
/** Installable onFormSubmit handler (use when Walk-In New is fed by a Form). */
function onWalkInFormSubmit(e) {
  try {
    var sh = e && e.range ? e.range.getSheet() : null;
    if (!sh) {
      sh = SpreadsheetApp.openById(WALKIN_SHEET_ID).getSheetByName(WALKIN_NEW_TAB);
      if (sh) processWalkInRow_(sh, sh.getLastRow());
      return;
    }
    if (sh.getName() !== WALKIN_NEW_TAB) return;
    processWalkInRow_(sh, e.range.getRow());
  } catch (err) {
    console.error('onWalkInFormSubmit: ' + err);
  }
}

/** Installable onEdit handler (use when rows are typed/pasted manually). */
function onWalkInEdit(e) {
  try {
    if (!e || !e.range) return;
    var sh = e.range.getSheet();
    if (sh.getName() !== WALKIN_NEW_TAB) return;
    var row = e.range.getRow();
    if (row < 2) return;                              // header
    var header = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
    // Ignore edits to the two output columns themselves (avoids redundant work).
    var colHist = findCol_(header, [HDR_HISTORY]); colHist = colHist >= 0 ? colHist + 1 : COL_HISTORY_FALLBACK;
    var colChan = findCol_(header, [HDR_CHANCE]);  colChan = colChan >= 0 ? colChan + 1 : COL_CHANCE_FALLBACK;
    if (e.range.getColumn() === colHist || e.range.getColumn() === colChan) return;
    var cMob = findCol_(header, ['Mobile Number','Mobile','Phone Number','Phone','Contact Number']);
    if (cMob < 0) return;
    // Only act once the row actually has a mobile number.
    if (!digits10_(sh.getRange(row, cMob + 1).getValue())) return;
    processWalkInRow_(sh, row, header);
  } catch (err) {
    console.error('onWalkInEdit: ' + err);
  }
}


// ═══════════════════════════════════════════════════════════════════════════
//  SETUP + UTILITIES
// ═══════════════════════════════════════════════════════════════════════════
/**
 * Run ONCE to install the trigger(s). Installs an onFormSubmit trigger if this
 * spreadsheet is linked to a Form, and always installs an onEdit trigger so
 * manually-entered rows are handled too. Safe to re-run (removes duplicates).
 */
function setupTriggers() {
  var ss = SpreadsheetApp.openById(WALKIN_SHEET_ID);
  // remove our previously-installed triggers to avoid duplicates
  var existing = ScriptApp.getProjectTriggers();
  for (var i = 0; i < existing.length; i++) {
    var fn = existing[i].getHandlerFunction();
    if (fn === 'onWalkInFormSubmit' || fn === 'onWalkInEdit' || fn === 'onWalkInDailySync') ScriptApp.deleteTrigger(existing[i]);
  }
  var installed = [];
  // Form submit (only meaningful if a Form is attached; harmless otherwise).
  try {
    ScriptApp.newTrigger('onWalkInFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
    installed.push('onFormSubmit');
  } catch (e) {}
  // Edit (manual entry / paste).
  ScriptApp.newTrigger('onWalkInEdit').forSpreadsheet(ss).onEdit().create();
  installed.push('onEdit');
  // Daily sync: once every morning, re-check EXISTING Walk-In rows and refresh
  // BOTH "Lead Interaction History" and "Conversion Chance %" where they have
  // changed (updates only where required; never duplicates history entries).
  // Runs ~06:00 in the Apps Script project time zone (set it to Asia/Kolkata
  // under Project Settings).
  ScriptApp.newTrigger('onWalkInDailySync').timeBased().everyDays(1).atHour(6).create();
  installed.push('dailySync(06:00)');
  SpreadsheetApp.getActiveSpreadsheet && SpreadsheetApp.getActiveSpreadsheet();
  Logger.log('Installed triggers: ' + installed.join(', '));
  return installed;
}

/** Optional: (re)compute the two columns for the LAST row — handy for testing. */
function testLastRow() {
  var sh = SpreadsheetApp.openById(WALKIN_SHEET_ID).getSheetByName(WALKIN_NEW_TAB);
  processWalkInRow_(sh, sh.getLastRow());
}

/**
 * Optional one-off backfill for EXISTING rows that are still blank in AE/AF.
 * Not used by the trigger (which handles only new records). Reads the master
 * once and reuses the trained model for every row for speed.
 */
function backfillBlankRows() {
  var sh = SpreadsheetApp.openById(WALKIN_SHEET_ID).getSheetByName(WALKIN_NEW_TAB);
  var header = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  var colHist = findCol_(header, [HDR_HISTORY]); colHist = colHist >= 0 ? colHist + 1 : COL_HISTORY_FALLBACK;
  var last = sh.getLastRow();
  for (var r = 2; r <= last; r++) {
    if (s_(sh.getRange(r, colHist).getValue())) continue;   // already filled
    processWalkInRow_(sh, r, header);
    SpreadsheetApp.flush();
  }
}


// ===========================================================================
//  DAILY SYNC  -  keep BOTH output columns current for EXISTING Walk-In rows
// ===========================================================================
/**
 * Re-check EVERY existing Walk-In New row that has a mobile and refresh both
 * "Lead Interaction History" (AE) and "Conversion Chance %" (AF) from the LATEST
 * master ("Consolidate Sales Tracking") + attendance/enrolment lookups, updating
 * a cell ONLY when the freshly-computed value actually differs from what is
 * already there. This is what keeps already-populated rows current as more
 * interactions are logged (history) and as admissions/leads grow (the self-
 * learning conversion model is retrained on every run).
 *
 * It reproduces processWalkInRow_()'s per-row computation EXACTLY, with one
 * crucial efficiency difference for GAS execution limits: the master is read
 * once and the conversion model is trained ONCE, then reused to score every row
 * (processWalkInRow_ retrains per row, which is fine for a single new lead but
 * far too heavy for a whole-sheet daily pass). History is de-duped by
 * (source, minute) via dedupeHistory_(), so no entry is ever duplicated
 * (idempotent). Reads the sheet once and writes each changed column back in a
 * SINGLE batched call, and only when at least one cell in it changed. If the
 * master reads back empty (a transient problem), it ABORTS without writing, so a
 * bad read can never wipe good histories or scores.
 * Returns the number of column-cells updated (history + chance).
 */
function syncWalkInAll_() {
  var sh = SpreadsheetApp.openById(WALKIN_SHEET_ID).getSheetByName(WALKIN_NEW_TAB);
  if (!sh) return 0;
  var lastRow = sh.getLastRow(), lastCol = sh.getLastColumn();
  if (lastRow < 2) return 0;
  var grid = sh.getRange(1, 1, lastRow, lastCol).getValues();
  var header = grid[0];

  // Same column resolution as processWalkInRow_ (identical candidate lists).
  var cMob  = findCol_(header, ['Mobile Number','Mobile','Phone Number','Phone','Contact Number']);
  if (cMob < 0) return 0;
  var cTs   = findCol_(header, ['Timestamp','Time Stamp','Walk-In Date & Time','Date']);
  var cCoun = findCol_(header, ['Counselling By','Counsellor']);
  var cStat = findCol_(header, ['Current Status','Candidate Type']);
  var cExp  = findCol_(header, ['Total Years of Experience','Experience']);
  var cCity = findCol_(header, ['Current City','City']);
  var cTl   = findCol_(header, ['When are you planning to take admission?','Admission Plan Time']);
  var cRef  = findCol_(header, ['IsReferral','Is Referral']);
  var cRefn = findCol_(header, ["Referrer's Name",'Referrer Name']);
  var cCourse = findCol_(header, ['Course Interested In','Course Advised','Which technology are you interested in learning?']);
  var cNotes  = findCol_(header, ['Counsellor Notes','Remarks']);
  var cLead   = findCol_(header, ['Lead Status']);

  var colHist0 = findCol_(header, [HDR_HISTORY]); colHist0 = colHist0 >= 0 ? colHist0 : (COL_HISTORY_FALLBACK - 1);
  var colChan0 = findCol_(header, [HDR_CHANCE]);  colChan0 = colChan0 >= 0 ? colChan0 : (COL_CHANCE_FALLBACK - 1);

  // ---- load master + lookups ONCE, train the model ONCE (key efficiency) ----
  var masterIdx = readMasterIndex_();
  var hasMaster = false;
  for (var kk in masterIdx) { if (masterIdx.hasOwnProperty(kk)) { hasMaster = true; break; } }
  if (!hasMaster) { Logger.log('syncWalkInAll_: master empty - skipping (no rows touched).'); return 0; }
  var meetMap     = loadMeetAttendance_();
  var walkinSet   = loadWalkinAttended_();
  var enrolledSet = loadEnrolledMobiles_();
  var model = trainModel_(buildTrainingSamples_(masterIdx, meetMap, walkinSet, enrolledSet));

  // Current chance-column font weights (values come from grid; weights do not).
  var chanWts = sh.getRange(2, colChan0 + 1, lastRow - 1, 1).getFontWeights();

  var outHist = [], outChan = [], outWt = [];
  var histChanged = 0, chanChanged = 0;

  for (var r = 1; r < grid.length; r++) {                 // r=1 -> sheet row 2
    var i = r - 1;                                        // 0-based into weight/out arrays
    var rowVals = grid[r];
    var curHistCell = grid[r][colHist0];
    var curChanCell = grid[r][colChan0];
    var curHist = (curHistCell === null || curHistCell === undefined) ? '' : String(curHistCell);
    var curChan = (curChanCell === null || curChanCell === undefined) ? '' : String(curChanCell);
    var curWt   = chanWts[i][0] || 'normal';

    var mob = cMob >= 0 ? digits10_(rowVals[cMob]) : '';
    if (!mob) {                                           // no phone -> leave both as-is
      outHist.push([curHistCell]); outChan.push([curChanCell]); outWt.push([curWt]);
      continue;
    }

    // ---- replicate processWalkInRow_ EXACTLY, but with the shared model ----
    var m = masterIdx[mob] || null;
    var prevHistory = m ? m.history.slice() : [];
    var wDt = cTs >= 0 ? parseDate_(rowVals[cTs]) : null; if (!wDt) wDt = new Date();
    var wCby = cCoun >= 0 ? s_(rowVals[cCoun]) : '';
    var combined = dedupeHistory_(prevHistory.concat([{ src: 'Walk-In', dt: wDt, cby: wCby }]));

    var statusRaw = (cStat >= 0 && s_(rowVals[cStat])) ? s_(rowVals[cStat]) : (m ? m.status_raw : '');
    var expRaw    = (cExp  >= 0 && s_(rowVals[cExp]))  ? s_(rowVals[cExp])  : (m ? m.experience_raw : '');
    var cityRaw   = (cCity >= 0 && s_(rowVals[cCity])) ? s_(rowVals[cCity]) : (m ? m.city_raw : '');
    var tlRaw     = (cTl   >= 0 && s_(rowVals[cTl]))   ? s_(rowVals[cTl])   : (m ? m.timeline_raw : '');
    var refFlag   = (cRef >= 0 && yes_(rowVals[cRef])) ||
                    (cRefn >= 0 && !!s_(rowVals[cRefn])) ||
                    (m ? !!m.referral : false);
    var platsCsv  = m ? m.platforms_csv : '';
    var courseRaw = (cCourse >= 0 && s_(rowVals[cCourse])) ? s_(rowVals[cCourse]) : (m ? m.course : '');
    var notesRaw  = (cNotes  >= 0 && s_(rowVals[cNotes]))  ? s_(rowVals[cNotes])  : (m ? m.remarks : '');
    var leadRaw   = (cLead   >= 0 && s_(rowVals[cLead]))   ? s_(rowVals[cLead])   : (m ? m.lead_status : '');

    var feats = buildFeatures_({
      history: combined,
      platforms: platformsInSequence_(combined, platsCsv),
      num_interactions: String(combined.length),
      referral: refFlag,
      work: normWork_(statusRaw, expRaw),
      timeline: normTimeline_(tlRaw),
      city: normCity_(cityRaw),
      meet_state: meetState_(m ? m.gmeet_sched : false, meetMap[mob] || ''),
      walkin_state: 'attended',
      course: courseRaw, lead_status: leadRaw, notes: notesRaw,
      as_of: wDt
    });
    var p = scoreModel_(model, feats);
    var chance = Math.round(p * 1000) / 10;

    var newHist = cleanHistory_(combined);
    var newChan = String(chance) + '%';
    var newWt   = (chance > 50) ? 'bold' : 'normal';

    if (newHist !== curHist) { outHist.push([newHist]); histChanged++; }
    else { outHist.push([curHistCell]); }

    if (newChan !== curChan || newWt !== curWt) { outChan.push([newChan]); outWt.push([newWt]); chanChanged++; }
    else { outChan.push([curChanCell]); outWt.push([curWt]); }
  }

  if (histChanged > 0) {
    sh.getRange(2, colHist0 + 1, outHist.length, 1).setValues(outHist);
  }
  if (chanChanged > 0) {
    var rng = sh.getRange(2, colChan0 + 1, outChan.length, 1);
    rng.setValues(outChan);
    rng.setFontWeights(outWt);
  }
  SpreadsheetApp.flush();
  Logger.log('syncWalkInAll_: history updated ' + histChanged + ', chance updated ' + chanChanged +
             ' of ' + (grid.length - 1) + ' row(s).');
  return histChanged + chanChanged;
}

/** Time-driven (daily) handler - refreshes existing rows' History + Conversion
 *  Chance. Wrapped so a transient error is logged, never thrown upward. */
function onWalkInDailySync() {
  try {
    syncWalkInAll_();
  } catch (err) {
    console.error('onWalkInDailySync: ' + err);
  }
}

/** Optional: run the daily sync on demand (handy for testing from the editor). */
function syncWalkInNow() {
  return syncWalkInAll_();
}
