"""The entire counsellor UI as one self-contained HTML string (no build step,
no external assets, no framework). Designed for speed and minimum clicks:
    login  ->  type/scan mobile + Enter  ->  see current + history  ->  edit  ->  Save.
The page talks only to this app's JSON API on the same origin."""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>IntelliBI Counsellor</title>
<style>
  :root{--bg:#0f172a;--card:#fff;--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;
        --brand:#2563eb;--brand2:#1d4ed8;--ok:#16a34a;--warn:#b45309;--err:#dc2626;
        --chip:#f1f5f9;}
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.45 system-ui,Segoe UI,Roboto,Arial;background:#f1f5f9;color:var(--ink)}
  header{background:var(--bg);color:#fff;padding:10px 16px;display:flex;
         align-items:center;gap:12px;position:sticky;top:0;z-index:5}
  header .brand{font-weight:700;letter-spacing:.3px}
  header .sp{flex:1}
  header .who{font-size:13px;color:#cbd5e1}
  button{font:inherit;cursor:pointer;border:0;border-radius:8px;padding:9px 14px;
          background:var(--brand);color:#fff}
  button.sec{background:#e2e8f0;color:#0f172a}
  button:disabled{opacity:.55;cursor:not-allowed}
  input,select,textarea{font:inherit;width:100%;padding:8px 10px;border:1px solid var(--line);
          border-radius:8px;background:#fff;color:var(--ink)}
  textarea{min-height:64px;resize:vertical}
  .wrap{max-width:960px;margin:18px auto;padding:0 14px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
        padding:18px;margin-bottom:16px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
  .row{display:flex;gap:10px;align-items:center}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px}
  @media(max-width:640px){.grid{grid-template-columns:1fr}}
  label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px;font-weight:600}
  .f{margin-bottom:2px}
  .ro input,.ro{background:#f8fafc;color:#334155}
  .muted{color:var(--mut)}
  .pill{display:inline-block;background:var(--chip);border-radius:999px;padding:2px 10px;
        font-size:12px;color:#334155;margin-left:6px}
  .toast{position:fixed;left:50%;transform:translateX(-50%);bottom:22px;z-index:20;
         padding:11px 18px;border-radius:10px;color:#fff;background:#111827;opacity:0;
         transition:opacity .15s;pointer-events:none;max-width:90%}
  .toast.show{opacity:1}
  .toast.ok{background:var(--ok)} .toast.err{background:var(--err)}
  .hist{border-top:1px dashed var(--line);margin-top:6px;padding-top:10px}
  .hist details{margin-bottom:8px}
  .hist summary{cursor:pointer;font-weight:600}
  .kv{display:grid;grid-template-columns:210px 1fr;gap:2px 12px;font-size:13px;margin-top:6px}
  .kv div:nth-child(odd){color:var(--mut)}
  .hidden{display:none}
  .login{max-width:380px;margin:9vh auto}
  .login h1{font-size:20px;margin:0 0 4px}
  .status{font-size:12px;color:var(--mut)}
  .req label:after{content:" *";color:var(--err)}
  .savebar{position:sticky;bottom:0;background:linear-gradient(#fff0,#fff 22%);
           padding:14px 0 4px;display:flex;gap:10px;align-items:center}
</style>
</head>
<body>
<div id="app"></div>
<div id="toast" class="toast"></div>

<script>
const $ = (s,r=document)=>r.querySelector(s);
let FIELDS=null, ME=null, CURRENT=null;

function toast(msg,kind){const t=$("#toast");t.className="toast show "+(kind||"");
  t.textContent=msg;setTimeout(()=>t.className="toast",2200);}

async function api(path,opts){
  const r=await fetch(path,Object.assign({headers:{"Content-Type":"application/json"}},opts));
  if(r.status===401){renderLogin();throw new Error("auth");}
  const j=await r.json().catch(()=>({}));
  if(!r.ok && j.error) throw new Error(j.error);
  return j;
}

/* ---------- login ---------- */
function renderLogin(err){
  ME=null;
  $("#app").innerHTML=`
   <div class="wrap"><div class="card login">
     <h1>IntelliBI Counsellor</h1>
     <p class="muted" style="margin-top:0">Sign in to manage leads</p>
     <div class="f"><label>Email</label><input id="em" autocomplete="username"></div>
     <div class="f"><label>Password</label><input id="pw" type="password" autocomplete="current-password"></div>
     <div class="row" style="margin-top:12px"><button id="go">Sign in</button>
       <span id="lerr" class="status" style="color:var(--err)">${err||""}</span></div>
   </div></div>`;
  const go=async()=>{
    $("#lerr").textContent="";
    try{
      const r=await fetch("/api/login",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({email:$("#em").value.trim(),password:$("#pw").value})});
      const j=await r.json().catch(()=>({}));
      if(!r.ok){$("#lerr").textContent=j.error||("Login failed ("+r.status+")");return;}
      await boot();
    }catch(e){$("#lerr").textContent="Cannot reach the server.";}
  };
  $("#go").onclick=go;
  $("#pw").addEventListener("keydown",e=>{if(e.key==="Enter")go();});
  $("#em").focus();
}

/* ---------- main shell ---------- */
function shell(){
  $("#app").innerHTML=`
   <header><span class="brand">IntelliBI</span>
     <span class="pill" id="ver" title="build version">Counsellor</span><span class="sp"></span>
     <span class="who" id="who"></span>
     <button class="sec" id="out">Logout</button></header>
   <div class="wrap">
     <div class="card">
       <label>Search by mobile number (or name / email)</label>
       <div class="row">
         <input id="q" placeholder="e.g. 9876543210" autocomplete="off">
         <button id="find">Find</button>
       </div>
       <div id="hits" class="muted" style="margin-top:8px;font-size:13px"></div>
     </div>
     <div id="panel"></div>
   </div>`;
  $("#who").textContent=ME.name+"  ·  "+ME.counselling_by;
  if(ME.version){$("#ver").textContent="Counsellor · v"+ME.version;}
  $("#out").onclick=async()=>{await api("/api/logout",{method:"POST"});renderLogin();};
  const q=$("#q");
  $("#find").onclick=()=>doFind(q.value.trim());
  q.addEventListener("keydown",e=>{
    if(e.key==="Enter")doFind(q.value.trim());
    else if(e.key==="Escape")clearHits();
  });
  // Live search: matching leads appear as the counsellor types (no Enter/Find
  // needed). Enter / Find keep their exact behaviour (exact mobile opens directly).
  q.addEventListener("input",()=>liveSearch(q.value.trim()));
  q.focus();
}

/* ---------- search ---------- */
const LIVE_MIN_CHARS=2, LIVE_DEBOUNCE_MS=150;
let liveTimer=null, liveSeq=0;

function clearHits(){
  liveSeq++;                                   // any in-flight live lookup is now stale
  if(liveTimer){clearTimeout(liveTimer);liveTimer=null;}
  $("#hits").innerHTML="";
}

/* Open a lead from the results list and drop the list at once, so the old
   suggestions never stay on screen next to the opened record. */
async function openFromHits(mobile){
  clearHits();
  const j=await api("/api/lead?mobile="+encodeURIComponent(mobile));
  showLead(j);
}

/* Render the matching leads under the search box (shared by live search and Find). */
function renderHits(results,term){
  if(results.length===0){$("#hits").innerHTML=
     `No existing lead found. <a href="#" id="newl">Create a new lead for “${escapeHtml(term)}”.</a>`;
     const nl=$("#newl"); if(nl) nl.onclick=(e)=>{e.preventDefault();clearHits();
       showLead({found:false,record:null,history:[]},term);};
     return;}
  $("#hits").innerHTML=results.map(r=>
     `<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--line);padding:6px 0">
        <span><b>${escapeHtml(r["Mobile Number"])}</b> — ${escapeHtml(r["Full Name"]||"")}
        <span class="muted">${escapeHtml(r["Admission Status"]||"")}</span></span>
        <button class="sec" data-m="${escapeHtml(r["Mobile Number"])}">Open</button></div>`).join("");
  $("#hits").querySelectorAll("button[data-m]").forEach(b=>b.onclick=()=>openFromHits(b.dataset.m));
}

/* As-you-type suggestions: debounced, and a reply that arrives for an older
   term is ignored, so the list always matches what is in the box right now. */
function liveSearch(term){
  if(liveTimer){clearTimeout(liveTimer);liveTimer=null;}
  const seq=++liveSeq;
  if(term.length<LIVE_MIN_CHARS){$("#hits").innerHTML="";return;}
  liveTimer=setTimeout(async()=>{
    try{
      const s=await api("/api/search?q="+encodeURIComponent(term));
      if(seq!==liveSeq||$("#q").value.trim()!==term)return;      // stale reply
      renderHits(s.results,term);
    }catch(e){ if(seq===liveSeq)$("#hits").innerHTML=""; }
  },LIVE_DEBOUNCE_MS);
}

async function doFind(term){
  if(!term){return;}
  clearHits();
  $("#hits").textContent="Searching…";
  // exact mobile first
  const digits=term.replace(/\D/g,"");
  if(digits.length>=10){
    const j=await api("/api/lead?mobile="+encodeURIComponent(term));
    $("#hits").textContent="";
    if(j.found){return showLead(j);}
  }
  const s=await api("/api/search?q="+encodeURIComponent(term));
  if(s.results.length===0){$("#panel").innerHTML="";}
  renderHits(s.results,term);
}

/* ---------- lead editor ---------- */
function fieldInput(col,val){
  val=val==null?"":val;
  const editable=FIELDS.editable.includes(col);
  if(!editable){
    return `<div class="f"><label>${escapeHtml(col)}</label>
       <input class="ro" value="${escapeAttr(val)}" readonly></div>`;}
  if(FIELDS.date_fields.includes(col)){
    return `<div class="f"><label>${escapeHtml(col)}</label>
       <input type="date" data-col="${escapeAttr(col)}" value="${toISO(val)}"></div>`;}
  if(FIELDS.selects[col]){
    const opts=FIELDS.selects[col].map(o=>{
      const sel = (o.toLowerCase()===String(val).toLowerCase())?" selected":"";
      return `<option${sel}>${escapeHtml(o)}</option>`;}).join("");
    // preserve a value not in the option list
    const known=FIELDS.selects[col].some(o=>o.toLowerCase()===String(val).toLowerCase());
    const extra = (!known && val) ? `<option selected>${escapeHtml(val)}</option>`:"";
    return `<div class="f"><label>${escapeHtml(col)}</label>
       <select data-col="${escapeAttr(col)}">${extra}${opts}</select></div>`;}
  if(col==="Counsellor Notes"||col==="Career Goal"||col==="BackOutReason"){
    return `<div class="f"><label>${escapeHtml(col)}</label>
       <textarea data-col="${escapeAttr(col)}">${escapeHtml(val)}</textarea></div>`;}
  return `<div class="f"><label>${escapeHtml(col)}</label>
     <input data-col="${escapeAttr(col)}" value="${escapeAttr(val)}"></div>`;
}

function showLead(j,prefillMobile){
  CURRENT=j.found?j.record:null;
  const rec=j.record||{};
  const mobile=j.found?rec["Mobile Number"]:(prefillMobile||"").replace(/\D/g,"");
  const cols=FIELDS.columns;
  const body=cols.map(c=>{
     if(c===FIELDS.mobile_col){
       return `<div class="f"><label>${escapeHtml(c)}</label>
         <input id="mobile" value="${escapeAttr(mobile)}" ${j.found?"readonly class=ro":""}></div>`;}
     if(c===FIELDS.timestamp_col){
       return `<div class="f"><label>Last updated</label>
         <input class="ro" value="${escapeAttr(rec[c]||"—")}" readonly></div>`;}
     return fieldInput(c,rec[c]);
  }).join("");

  const hist=(j.history||[]).map((h,i)=>{
     const rows=FIELDS.columns.map(c=>
        `<div>${escapeHtml(c)}</div><div>${escapeHtml(h[c]||"")}</div>`).join("");
     return `<details><summary>Version ${escapeHtml(h.RecordVersion||"")}
        <span class="muted">· archived ${escapeHtml(h.ArchivedAt||"")}</span></summary>
        <div class="kv">${rows}</div></details>`;}).join("");

  $("#panel").innerHTML=`
   <div class="card">
     <div class="row" style="justify-content:space-between">
       <h3 style="margin:0">${j.found?"Edit lead":"New lead"}
         ${j.found?`<span class="pill">${(j.history||[]).length} prior version(s)</span>`:""}</h3>
       <span class="status" id="savedts">${j.found?("Updated "+escapeHtml(rec[FIELDS.timestamp_col]||"")):""}</span>
     </div>
     <div class="grid" style="margin-top:12px">${body}</div>
     <div class="savebar">
       <button id="save">Save</button>
       <button class="sec" id="cancel">Clear</button>
       <span class="status" id="msg"></span>
     </div>
     ${hist?`<div class="hist"><b>Interaction history</b>${hist}</div>`:""}
   </div>`;

  $("#cancel").onclick=()=>{$("#panel").innerHTML="";$("#q").focus();};
  $("#save").onclick=saveLead;
}

async function saveLead(){
  const btn=$("#save");btn.disabled=true;
  const mobile=$("#mobile").value.trim();
  const fields={};
  $("#panel").querySelectorAll("[data-col]").forEach(el=>{fields[el.dataset.col]=el.value;});
  try{
    const j=await api("/api/save",{method:"POST",
       body:JSON.stringify({mobile,fields})});
    if(j.ok){toast("Saved ✓"+(j.pending?(" · syncing ("+j.pending+")"):""),"ok");
       // refresh to show new timestamp + history
       const f=await api("/api/lead?mobile="+encodeURIComponent(mobile));showLead(f);}
    else{toast(j.message||"Could not save","err");$("#msg").textContent=j.message||"";}
  }catch(e){toast(e.message||"Save failed","err");}
  finally{btn.disabled=false;}
}

/* ---------- helpers ---------- */
function escapeHtml(s){return String(s==null?"":s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function escapeAttr(s){return escapeHtml(s).replace(/"/g,"&quot;");}
function toISO(v){ // dd-MMM-yyyy -> yyyy-mm-dd for <input type=date>
  if(!v)return"";
  const m=String(v).match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})/);
  if(!m)return"";const mo={jan:"01",feb:"02",mar:"03",apr:"04",may:"05",jun:"06",
    jul:"07",aug:"08",sep:"09",oct:"10",nov:"11",dec:"12"}[m[2].toLowerCase()];
  if(!mo)return"";return `${m[3]}-${mo}-${String(m[1]).padStart(2,"0")}`;}

/* ---------- boot ---------- */
async function boot(){
  try{ME=await api("/api/me");}catch(e){return renderLogin();}
  FIELDS=await api("/api/fields");
  shell();
}
boot();
</script>
</body>
</html>"""
