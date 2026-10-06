// Offline tests for WalkInNewProtection.gs — a mocked SpreadsheetApp; SYNTHETIC data only.
'use strict';
const fs = require('fs'), vm = require('vm'), path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, 'WalkInNewProtection.gs'), 'utf8');

const OWNER = 'info@intellibiinnovationstechnologies.in';
const COUNSELLOR = 'counsellor.one@example.com';
const OTHER = 'someone.else@example.com';

const FORM = ['Timestamp', 'Full Name', 'Email Address', 'Mobile Number', 'Current City',
  'Current Area / Locality', 'Preferred Contact Method', 'Highest Qualification',
  'Graduation / Passing Year', 'College / University Name', 'Grade / Percentage / CGPA',
  'Current Status', 'Current Company Name', 'Total Years of Experience',
  'Current Domain / Technology', 'Which technology are you interested in learning?',
  'What is your primary goal?', 'How did you hear about IntelliBI?', "Referrer's Name",
  'Preferred Learning Mode', 'Preferred Batch Timing',
  'When are you planning to   take admission?  '];          // extra spaces, like the real header
const EDIT = ['Remarks', 'Lead Status', 'Admission Status', 'Counselling By', 'Tech Counselling By',
  'ScheduledOrDirectWalkIn', 'Next Follow-Up Date', 'BackOutReason'];
const SYS = ['Lead Interaction History', 'Conversion Chance %'];
const OTHER_TABS = ['Walk-In Old', 'Organic Customer Call Log', 'WebsiteCallback -New(Manish)',
  'Only WebsiteCallback', 'Prospect Re-Targeting Lead', ' Meta Lead', 'Form Responses 2', 'Website',
  'Campaign', 'Bot Reply', 'Masterclass Data', 'junk', 'Calc_Data', 'Dashboard',
  'Monthly Enquiries Report', 'Month Wise Visit Report'];

// ── mock ────────────────────────────────────────────────────────────────
function letter(c) { let s = ''; while (c > 0) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); } return s; }
class Range {
  constructor(sh, r, c, nr, nc) { Object.assign(this, { sh, r, c, nr, nc }); }
  getRow() { return this.r; } getColumn() { return this.c; }
  getNumRows() { return this.nr; } getNumColumns() { return this.nc; } getSheet() { return this.sh; }
  getA1Notation() { return letter(this.c) + this.r + ':' + letter(this.c + this.nc - 1) + (this.r + this.nr - 1); }
  getValues() {
    const out = [];
    for (let i = 0; i < this.nr; i++) { const row = this.sh.data[this.r - 1 + i] || []; const o = [];
      for (let j = 0; j < this.nc; j++) o.push(row[this.c - 1 + j] === undefined ? '' : row[this.c - 1 + j]); out.push(o); }
    return out;
  }
}
class Protection {
  constructor(env, sh, type, range) {
    Object.assign(this, { env, sh, type, range, description: '', warning: false, domain: true, unprot: [] });
    this.editors = [...new Set([env.owner, env.me, ...env.collaborators])];  // Google copies editors
  }
  getDescription() { return this.description; } setDescription(d) { this.description = d; return this; }
  isWarningOnly() { return this.warning; } setWarningOnly(w) { this.warning = w; return this; }
  canDomainEdit() { return this.domain; } setDomainEdit(d) { this.domain = d; return this; }
  getEditors() { return this.editors.map(e => ({ getEmail: () => e })); }
  addEditors(list) { this.env.calls.push('addEditors'); list.forEach(e => { if (!this.editors.includes(e)) this.editors.push(e); }); return this; }
  removeEditors(list) { this.env.calls.push('removeEditors');
    this.editors = this.editors.filter(e => !list.includes(e) || e === this.env.owner || e === this.env.me); return this; }
  getUnprotectedRanges() { return this.unprot.slice(); }
  setUnprotectedRanges(rs) { if (this.type !== 'SHEET') throw new Error('range protection'); this.unprot = rs.slice(); return this; }
  getRange() { return this.range; }
  remove() { this.sh.prots = this.sh.prots.filter(p => p !== this); }
}
class Sheet {
  constructor(env, name, data, maxRows) { Object.assign(this, { env, name, data, maxRows, prots: [], formUrl: '' }); }
  getName() { return this.name; } isSheetHidden() { return false; } getFormUrl() { return this.formUrl; }
  getLastRow() { for (let i = this.data.length; i > 0; i--) if ((this.data[i - 1] || []).some(v => v !== '')) return i; return 0; }
  getLastColumn() { return Math.max(0, ...this.data.map(r => { let k = r.length; while (k > 0 && r[k - 1] === '') k--; return k; })); }
  getMaxRows() { return this.maxRows; }
  getRange(r, c, nr, nc) { return new Range(this, r, c, nr || 1, nc || 1); }
  insertRowsAfter(after, n) { this.env.calls.push('insertRowsAfter:' + n); this.maxRows += n; }
  protect() { const p = new Protection(this.env, this, 'SHEET', null); this.prots.push(p); return p; }
  protectRange(a1r) { const p = new Protection(this.env, this, 'RANGE', a1r); this.prots.push(p); return p; }
  getProtections(t) { return this.prots.filter(p => p.type === t); }
}
function makeEnv(opts = {}) {
  const env = { owner: OWNER, me: opts.me || OWNER, collaborators: [COUNSELLOR, OTHER], calls: [], logs: [], triggers: [] };
  const headers = opts.headers || [...FORM, ...EDIT, ...SYS];
  const rows = opts.rows === undefined ? 40 : opts.rows;
  const data = [headers];
  for (let i = 1; i <= rows; i++) data.push(headers.map((h, j) => j === 0 ? '01/01/2026 10:00:00' : (j === 3 ? '90000000' + String(i).padStart(2, '0') : 'x')));
  const walkin = new Sheet(env, 'Walk-In New', data, opts.maxRows || 1000);
  walkin.formUrl = 'https://docs.google.com/forms/d/synthetic/viewform';
  const sheets = [walkin, ...OTHER_TABS.map(n => new Sheet(env, n, [['A', 'B'], ['1', '2']], 100))];
  env.sheets = sheets; env.walkin = walkin;
  env.ss = { getName: () => 'Synthetic Tracker', getOwner: () => ({ getEmail: () => env.owner }),
    getSheets: () => env.sheets, getSheetByName: n => env.sheets.find(s => s.name === n) || null };
  if (opts.autoTriggers !== false) (opts.autoTriggers || ['onWalkInEdit', 'onWalkInFormSubmit']).forEach(fn => env.triggers.push({ fn }));
  const trig = t => ({ getHandlerFunction: () => t.fn, _t: t });
  const builder = fn => { const t = { fn }; const b = { forSpreadsheet: () => b, onFormSubmit: () => b, timeBased: () => b,
    everyDays: () => b, atHour: () => b, create: () => { env.triggers.push(t); return trig(t); } }; return b; };
  const ctx = {
    console: { log: m => env.logs.push(String(m)), error: m => env.logs.push('ERR ' + m) },
    SpreadsheetApp: { openById: () => env.ss, ProtectionType: { SHEET: 'SHEET', RANGE: 'RANGE' } },
    Session: { getEffectiveUser: () => ({ getEmail: () => env.me }) },
    LockService: { getDocumentLock: () => null, getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    ScriptApp: { getProjectTriggers: () => env.triggers.map(trig), newTrigger: builder,
      deleteTrigger: t => { env.triggers = env.triggers.filter(x => x !== t._t); } },
  };
  vm.createContext(ctx); vm.runInContext(SRC, ctx);
  if (opts.config) vm.runInContext(opts.config, ctx);
  env.ctx = ctx;
  return env;
}

// ── helpers ─────────────────────────────────────────────────────────────
let pass = 0, fail = 0;
function check(name, cond, extra) { if (cond) pass++; else { fail++; console.log('FAIL: ' + name + (extra ? ' — ' + extra : '')); } }
function sheetProt(sh) { return sh.getProtections('SHEET'); }
function editableCols(sh) { const s = new Set(); sheetProt(sh)[0].unprot.forEach(r => { for (let c = r.c; c < r.c + r.nc; c++) s.add(c); }); return [...s].sort((a, b) => a - b); }
function canEdit(env, sh, user, row, col) {           // what Google enforces for `user`
  const ps = sh.prots;
  if (user === env.owner) return true;
  for (const p of ps) {
    if (p.warning) continue;
    if (p.editors.includes(user)) continue;
    if (p.type === 'SHEET') { if (!p.unprot.some(r => row >= r.r && row < r.r + r.nr && col >= r.c && col < r.c + r.nc)) return false; }
    else if (row >= p.range.r && row < p.range.r + p.range.nr && col >= p.range.c && col < p.range.c + p.range.nc) return false;
  }
  return true;
}
function colOf(env, h) { return env.walkin.data[0].findIndex(x => x.replace(/\s+/g, ' ').trim().toLowerCase() === h.toLowerCase()) + 1; }
function throws(fn) { try { fn(); return null; } catch (e) { return e.message; } }

// ── 1. fresh apply ───────────────────────────────────────────────────────
{
  const env = makeEnv();
  const rep = env.ctx.applyWorkbookProtection();
  const wn = env.walkin;
  check('fresh: verified', rep.verified === true, JSON.stringify(rep.problems));
  check('fresh: one tab protection on Walk-In New', sheetProt(wn).length === 1);
  check('fresh: not warning-only, domain off', !sheetProt(wn)[0].warning && !sheetProt(wn)[0].domain);
  check('fresh: editable = W..AD', editableCols(wn).join(',') === '23,24,25,26,27,28,29,30', editableCols(wn).join(','));
  check('fresh: merged into one contiguous range', sheetProt(wn)[0].unprot.length === 1 && sheetProt(wn)[0].unprot[0].getA1Notation() === 'W2:AD1000',
        sheetProt(wn)[0].unprot.map(r => r.getA1Notation()).join(' '));
  check('fresh: counsellor removed from editors', !sheetProt(wn)[0].editors.includes(COUNSELLOR) && !sheetProt(wn)[0].editors.includes(OTHER));
  EDIT.forEach(h => check('counsellor can edit ' + h, canEdit(env, wn, COUNSELLOR, 5, colOf(env, h))));
  FORM.forEach(h => check('counsellor cannot edit form col ' + h.trim(), !canEdit(env, wn, COUNSELLOR, 5, colOf(env, h.replace(/\s+/g, ' ').trim()))));
  SYS.forEach(h => check('counsellor cannot edit system col ' + h, !canEdit(env, wn, COUNSELLOR, 5, colOf(env, h))));
  SYS.forEach(h => check('owner/automation can write ' + h, canEdit(env, wn, OWNER, 5, colOf(env, h))));
  check('counsellor cannot edit header row', !canEdit(env, wn, COUNSELLOR, 1, colOf(env, 'Remarks')));
  check('counsellor cannot edit column beyond AF', !canEdit(env, wn, COUNSELLOR, 5, 40));
  env.sheets.slice(1).forEach(sh => {
    const p = sheetProt(sh);
    check(sh.name + ': protected', p.length === 1 && p[0].unprot.length === 0 && !p[0].domain && !p[0].warning);
    check(sh.name + ': counsellor read-only', !canEdit(env, sh, COUNSELLOR, 2, 1) && !canEdit(env, sh, COUNSELLOR, 50, 20));
    check(sh.name + ': owner can write', canEdit(env, sh, OWNER, 2, 1));
  });
  check('fresh: no row insert needed (1000 rows)', !env.calls.some(c => c.startsWith('insertRowsAfter')));
  check('fresh: no data values changed', env.walkin.data.length === 41 && env.walkin.data[5][23] === 'x');
}

// ── 2. idempotent re-run ─────────────────────────────────────────────────
{
  const env = makeEnv();
  env.ctx.applyWorkbookProtection();
  const before = env.sheets.map(s => s.prots.length).join(',');
  env.calls.length = 0;
  const rep = env.ctx.applyWorkbookProtection();
  check('rerun: verified', rep.verified);
  check('rerun: no duplicate protections', env.sheets.map(s => s.prots.length).join(',') === before);
  check('rerun: no editor churn', !env.calls.includes('addEditors') && !env.calls.includes('removeEditors'), env.calls.join(','));
  check('rerun: nothing adopted', rep.tabs.every(t => !t.adopted && !t.created));
}

// ── 3. header moved → rule follows the header ────────────────────────────
{
  const hdr = [...FORM.slice(0, 5), 'Remarks', ...FORM.slice(5), ...EDIT.slice(1), ...SYS];
  const env = makeEnv({ headers: hdr });
  const rep = env.ctx.applyWorkbookProtection();
  check('moved: verified', rep.verified, JSON.stringify(rep.problems));
  check('moved: Remarks at F editable', canEdit(env, env.walkin, COUNSELLOR, 3, 6));
  check('moved: two editable runs', sheetProt(env.walkin)[0].unprot.map(r => r.getA1Notation()).join(' ') === 'F2:F1000 X2:AD1000',
        sheetProt(env.walkin)[0].unprot.map(r => r.getA1Notation()).join(' '));
  check('moved: old W (now a form col) read-only', !canEdit(env, env.walkin, COUNSELLOR, 3, 23 - 0) || colOf(env, 'Lead Status') === 23);
}

// ── 4. header whitespace / case tolerance ────────────────────────────────
{
  const hdr = [...FORM, '  remarks ', 'Lead  Status', ...EDIT.slice(2), ...SYS];
  const env = makeEnv({ headers: hdr });
  const rep = env.ctx.applyWorkbookProtection();
  check('whitespace: verified', rep.verified, JSON.stringify(rep.problems));
  check('whitespace: still W..AD', editableCols(env.walkin).join(',') === '23,24,25,26,27,28,29,30');
}

// ── 5. missing / duplicate header → abort, nothing changed ────────────────
{
  const env = makeEnv({ headers: [...FORM, ...EDIT.filter(h => h !== 'BackOutReason'), ...SYS] });
  const err = throws(() => env.ctx.applyWorkbookProtection());
  check('missing: aborts', err && /BackOutReason/.test(err), err);
  check('missing: no protection created anywhere', env.sheets.every(s => s.prots.length === 0));
  const env2 = makeEnv({ headers: [...FORM, ...EDIT, 'Remarks', ...SYS] });
  const err2 = throws(() => env2.ctx.applyWorkbookProtection());
  check('duplicate: aborts', err2 && /more than once/.test(err2), err2);
  check('duplicate: nothing changed', env2.sheets.every(s => s.prots.length === 0));
  // a previously applied state survives an aborted run
  const env3 = makeEnv();
  env3.ctx.applyWorkbookProtection();
  env3.walkin.data[0][29] = 'Back Out Reason (renamed)';
  const snap = JSON.stringify(sheetProt(env3.walkin)[0].unprot.map(r => r.getA1Notation()));
  check('renamed header: aborts', !!throws(() => env3.ctx.applyWorkbookProtection()));
  check('renamed header: previous rules kept', JSON.stringify(sheetProt(env3.walkin)[0].unprot.map(r => r.getA1Notation())) === snap);
  check('renamed header: verify reports it', !env3.ctx.verifyWorkbookProtection().ok);
}

// ── 6. adopt existing protections ────────────────────────────────────────
{
  const env = makeEnv();
  const old = env.sheets[3].protect();                   // pre-existing tab protection
  old.setDescription('old manual protection'); old.editors.push('integration@example.com'); old.warning = true;
  const rng = env.walkin.protectRange(env.walkin.getRange(2, 24, 10, 1));   // range protection on Lead Status
  rng.setDescription('legacy');
  const rep = env.ctx.applyWorkbookProtection();
  const t = rep.tabs.find(x => x.tab === env.sheets[3].name);
  check('adopt: reused, not duplicated', env.sheets[3].getProtections('SHEET').length === 1 && t.adopted);
  check('adopt: previous editors reported', t.previousEditors.includes('integration@example.com'));
  check('adopt: warning-only switched off', !env.sheets[3].prots[0].warning);
  check('adopt: integration removed unless configured', !env.sheets[3].prots[0].editors.includes('integration@example.com'));
  check('overlap: warning raised', rep.warnings.some(w => /covers a counsellor column/.test(w)), rep.warnings.join(' | '));
  check('overlap: range protection left untouched', env.walkin.getProtections('RANGE').length === 1);
}

// ── 6b. ProtectHeaderRow.gs header lock coexists ────────────────────────
{
  const env = makeEnv();
  const hp = env.walkin.protectRange(env.walkin.getRange(1, 1, 1, 32));
  hp.setDescription('Locked header row — do not rename columns');
  const rep = env.ctx.applyWorkbookProtection();
  check('header lock: verified', rep.verified, JSON.stringify(rep.problems));
  check('header lock: not reported as blocking counsellors', !rep.warnings.some(w => /covers a counsellor column/.test(w)), rep.warnings.join(' | '));
  check('header lock: left in place', env.walkin.getProtections('RANGE').length === 1);
  check('header lock: counsellor can still edit Remarks', canEdit(env, env.walkin, COUNSELLOR, 5, colOf(env, 'Remarks')));
}

// ── 7. per-tab extra editors ─────────────────────────────────────────────
{
  const env = makeEnv({ config: "WIP_TAB_EXTRA_EDITORS = {'Bot Reply': ['Bot.Writer@Example.com']};" });
  const rep = env.ctx.applyWorkbookProtection();
  const bot = env.ctx.SpreadsheetApp.openById().getSheetByName('Bot Reply');
  check('extra: verified', rep.verified, JSON.stringify(rep.problems));
  check('extra: bot account can write Bot Reply', canEdit(env, bot, 'bot.writer@example.com', 2, 1));
  check('extra: bot account cannot write Website', !canEdit(env, env.ss.getSheetByName('Website'), 'bot.writer@example.com', 2, 1));
  check('extra: bot account cannot write Walk-In New form cols', !canEdit(env, env.walkin, 'bot.writer@example.com', 2, 1));
}

// ── 8. full-control admin + refused runner ───────────────────────────────
{
  const env = makeEnv({ me: COUNSELLOR });
  const err = throws(() => env.ctx.applyWorkbookProtection());
  check('non-admin: refused', err && /Nothing was changed/.test(err), err);
  check('non-admin: nothing changed', env.sheets.every(s => s.prots.length === 0));
  const env2 = makeEnv({ config: "WIP_FULL_CONTROL = ['info@intellibiinnovationstechnologies.in', 'admin@example.com'];" });
  env2.ctx.applyWorkbookProtection();
  env2.sheets.forEach(sh => check(sh.name + ': admin keeps write', canEdit(env2, sh, 'admin@example.com', 3, 3)));
}

// ── 9. row buffer + form-submit hook ─────────────────────────────────────
{
  const env = makeEnv({ rows: 990, maxRows: 1000 });
  const rep = env.ctx.applyWorkbookProtection();
  check('buffer: rows added', env.calls.includes('insertRowsAfter:291'), env.calls.join(','));
  check('buffer: range covers new rows', sheetProt(env.walkin)[0].unprot[0].getA1Notation() === 'W2:AD1291');
  check('buffer: warning mentions it', rep.warnings.some(w => /row buffer/.test(w)));
  // a new form row far from the end → no re-apply
  env.calls.length = 0;
  env.walkin.data.push(env.walkin.data[1].slice());
  env.ctx.onWalkInProtectionFormSubmit({ range: env.walkin.getRange(992, 1, 1, 32) });
  check('hook: no re-apply when far from end', env.calls.length === 0, env.calls.join(','));
  // simulate the form appending past the range (Google added rows itself)
  env.walkin.maxRows = 1300;
  for (let i = 0; i < 270; i++) env.walkin.data.push(env.walkin.data[1].slice());
  const lastRow = env.walkin.getLastRow();
  check('hook precondition: row now near end', lastRow > 1291 - 50, String(lastRow));
  env.ctx.onWalkInProtectionFormSubmit({ range: env.walkin.getRange(lastRow, 1, 1, 32) });
  check('hook: re-applied, new row editable', canEdit(env, env.walkin, COUNSELLOR, lastRow, colOf(env, 'Remarks')));
  check('hook: system col of new row still locked', !canEdit(env, env.walkin, COUNSELLOR, lastRow, colOf(env, 'Conversion Chance %')));
  // event for another tab is ignored; errors never escape
  env.calls.length = 0;
  env.ctx.onWalkInProtectionFormSubmit({ range: env.sheets[7].getRange(2, 1, 1, 2) });
  check('hook: other tab ignored', env.calls.length === 0);
  env.walkin.data[0][29] = 'broken';
  const endRow = sheetProt(env.walkin)[0].unprot[0].getRow() + sheetProt(env.walkin)[0].unprot[0].getNumRows() - 1;
  let threw = false; try { env.ctx.onWalkInProtectionFormSubmit({ range: env.walkin.getRange(endRow, 1, 1, 32) }); } catch (e) { threw = true; }
  check('hook: never throws', !threw);
  check('hook: error logged', env.logs.some(l => l.startsWith('ERR onWalkInProtectionFormSubmit')));
}

// ── 10. buffer disabled ──────────────────────────────────────────────────
{
  const env = makeEnv({ rows: 995, maxRows: 1000, config: 'WIP_ROW_BUFFER = 0;' });
  env.ctx.applyWorkbookProtection();
  check('buffer 0: no rows inserted', !env.calls.some(c => c.startsWith('insertRowsAfter')));
}

// ── 11. trigger-owner warning ────────────────────────────────────────────
{
  const env = makeEnv({ autoTriggers: false });
  const rep = env.ctx.applyWorkbookProtection();
  check('trigger warning raised', rep.warnings.some(w => /owns none of the WalkInNewAutoPopulate triggers/.test(w)));
  const env3 = makeEnv({ autoTriggers: ['onWalkInDailySync'] });
  check('daily-sync trigger counts as owned', !env3.ctx.applyWorkbookProtection().warnings.some(w => /owns none/.test(w)));
  const env2 = makeEnv();
  check('no trigger warning when owned', !env2.ctx.applyWorkbookProtection().warnings.some(w => /owns none/.test(w)));
}

// ── 12. drift detection by verify ────────────────────────────────────────
{
  const env = makeEnv();
  env.ctx.applyWorkbookProtection();
  check('verify ok after apply', env.ctx.verifyWorkbookProtection().ok);
  sheetProt(env.sheets[2])[0].editors.push(COUNSELLOR);
  let v = env.ctx.verifyWorkbookProtection();
  check('drift: extra editor detected', !v.ok && v.problems.some(p => /editors are/.test(p)));
  env.ctx.applyWorkbookProtection();
  check('drift: re-apply fixes it', env.ctx.verifyWorkbookProtection().ok && !sheetProt(env.sheets[2])[0].editors.includes(COUNSELLOR));
  sheetProt(env.walkin)[0].unprot.push(env.walkin.getRange(2, 32, 10, 1));
  v = env.ctx.verifyWorkbookProtection();
  check('drift: editable system column detected', !v.ok && v.problems.some(p => /Conversion Chance %/.test(p)), v.problems.join(' | '));
  sheetProt(env.walkin)[0].unprot = [env.walkin.getRange(1, 23, 1000, 8)];
  v = env.ctx.verifyWorkbookProtection();
  check('drift: editable header detected', v.problems.some(p => /header row/.test(p)));
  sheetProt(env.walkin)[0].warning = true;
  check('drift: warning-only detected', env.ctx.verifyWorkbookProtection().problems.some(p => /warning-only/.test(p)));
  env.ctx.applyWorkbookProtection();
  check('drift: re-apply restores', env.ctx.verifyWorkbookProtection().ok);
  // a new tab added by someone
  env.sheets.push(new Sheet(env, 'New Tab', [['a'], ['1']], 50));
  check('new tab: verify flags it', env.ctx.verifyWorkbookProtection().problems.some(p => /New Tab: tab protection missing/.test(p)));
  env.ctx.onWorkbookProtectionDaily();
  check('new tab: daily run protects it', env.ctx.verifyWorkbookProtection().ok && !canEdit(env, env.sheets[env.sheets.length - 1], COUNSELLOR, 2, 1));
}

// ── 13. triggers setup ───────────────────────────────────────────────────
{
  const env = makeEnv();
  env.ctx.setupWorkbookProtectionTriggers();
  env.ctx.setupWorkbookProtectionTriggers();
  const fns = env.triggers.map(t => t.fn).sort();
  check('triggers: de-duplicated, auto-populate untouched',
        fns.join(',') === 'onWalkInEdit,onWalkInFormSubmit,onWalkInProtectionFormSubmit,onWorkbookProtectionDaily', fns.join(','));
  check('triggers: daily hour before the 6 AM auto-populate sync', env.ctx.WIP_DAILY_HOUR < 6);
}

// ── 14. audit is read-only ───────────────────────────────────────────────
{
  const env = makeEnv();
  const report = env.ctx.auditWalkInWorkbook();
  check('audit: no protections created', env.sheets.every(s => s.prots.length === 0));
  check('audit: finds all groups', /counsellor-editable: Remarks=W/.test(report) && !/MISSING/.test(report), report.split('\n').filter(l => /MISSING/.test(l)).join(' '));
  check('audit: form flagged', /Walk-In New \| rows 41\/1000 \| Google Form linked/.test(report));
  check('audit: no lead data in report', !/90000000/.test(report));
}

// ── 15. no name clashes with WalkInNewAutoPopulate.gs ─────────────────────
{
  const auto = ['onWalkInDailySync', 'onWalkInFormSubmit', 'onWalkInEdit', 'setupTriggers', 'testLastRow', 'backfillBlankRows',
                'processWalkInRow_', 'onOpen', 'onEdit', 'WALKIN_NEW_TAB', 'WALKIN_SHEET_ID', 'MASTER_SHEET_ID', 'HDR_HISTORY', 'HDR_CHANCE'];
  for (const f of fs.readdirSync(__dirname).filter(f => f.endsWith('.gs') && f !== 'WalkInNewProtection.gs')) {
    const other = fs.readFileSync(path.join(__dirname, f), 'utf8');
    [...other.matchAll(/^(?:function|var|const|let)\s+([A-Za-z0-9_$]+)/gm)].forEach(m => auto.push(m[1]));
  }
  const declared = [...SRC.matchAll(/^(?:function|var)\s+([A-Za-z0-9_]+)/gm)].map(m => m[1]);
  const clash = declared.filter(n => auto.includes(n));
  check('no global-name clashes', clash.length === 0, clash.join(','));
  check('all globals WIP-prefixed or wip-prefixed / public entry points',
        declared.every(n => /^(WIP_|wip)/.test(n) || ['auditWalkInWorkbook', 'applyWorkbookProtection', 'verifyWorkbookProtection',
          'onWalkInProtectionFormSubmit', 'onWorkbookProtectionDaily', 'setupWorkbookProtectionTriggers'].includes(n)),
        declared.filter(n => !/^(WIP_|wip)/.test(n)).join(','));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
