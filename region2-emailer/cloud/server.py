"""
Hosted control plane for the Region 2 emailer (work-laptop access).

Same dashboard as the local control plane, hardened for the internet:
- access key login for the browser (DASH_KEY), separate key for the home
  agent (AGENT_KEY) - both REQUIRED via environment variables
- binds 0.0.0.0 on $PORT (set by the hosting platform, HTTPS terminated there)
- tracker data is pushed up by the home agent; everything held in memory only,
  nothing is written to disk on the host
- shows whether the home PC's agent is online (polled within the last 15s)

    DASH_KEY=... AGENT_KEY=... PORT=8080 python server.py
"""
import json, os, sys, time, threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
DASH_KEY = os.environ.get("DASH_KEY", "")
AGENT_KEY = os.environ.get("AGENT_KEY", "")

_lock = threading.Lock()
_queue = []
_status = {"state": "idle", "detail": "Waiting for a command.", "at": "", "output": "", "email": None}
_tracker = {"records": []}
_waitlist = {"entries": []}
_agent_seen = 0.0
_files = {}          # name -> {"data": b64, "size": int, "at": str}
_MAX_FILES = 12
try:
    _QUEUE_TTL = int(os.environ.get("QUEUE_TTL", "600"))   # seconds an unclaimed command stays queued
except ValueError:
    _QUEUE_TTL = 600


_dropped = []        # expired-unrun commands, kept until dismissed from the dashboard
_MAX_DROPPED = 8


def _agent_online():
    # 30s tolerates the odd missed heartbeat / a redeploy blip; the agent
    # pings every 5s via /api/heartbeat, so this stays green whenever it lives.
    return (time.time() - _agent_seen) < 30


def _ttl_text():
    return f"{_QUEUE_TTL // 60} min" if _QUEUE_TTL >= 60 else f"{_QUEUE_TTL} s"


def _sweep_queue_locked(agent_seen=None):
    """Drop commands nobody picked up, and record it durably (call holding _lock).

    A command expires only when BOTH it is older than the TTL and the agent has
    been away for at least the TTL — an online-but-busy home PC keeps its
    backlog. /api/next passes the pre-request agent_seen, because merely
    authenticating that request already refreshed _agent_seen and would
    otherwise let a reconnecting agent revive arbitrarily stale commands.
    """
    now = time.time()
    seen = _agent_seen if agent_seen is None else agent_seen
    if now - seen <= _QUEUE_TTL:
        return
    dropped = [c for c in _queue if now - c.get("queued_at", now) > _QUEUE_TTL]
    if dropped:
        _queue[:] = [c for c in _queue if c not in dropped]
        at = datetime.now().strftime("%H:%M:%S")
        for c in dropped:
            _dropped.append({"action": str(c.get("action", "?"))[:40],
                             "order": str(c.get("order", ""))[:40], "at": at})
        del _dropped[:-_MAX_DROPPED]
        acts = ", ".join(c.get("action", "?") for c in dropped)
        _status.update(state="error",
                       detail=f"Expired unrun — the home PC did not pick this up within "
                              f"{_ttl_text()}: {acts}. Nothing was sent; re-run it if still needed.",
                       at=at, output="", email=None)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DHL Haulage Desk</title>
<style>
  *{ box-sizing:border-box; }
  :root{
    --bg:#f7f6f2; --card:#ffffff; --text:#24211b; --muted:#6e6a60; --faint:#a09a8c; --ink:#514c42;
    --border:#e7e4dc; --border2:#ddd8cc; --line:#e0dccf; --input:#f7f6f2;
    --yellow:#ffcc00; --red:#d40511; --go:#1a9a4a; --amber:#e0a92e; --amberink:#9a6a00;
    --radius:12px;
  }
  body{ margin:0; background:var(--bg); color:var(--text); -webkit-font-smoothing:antialiased;
        font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; line-height:1.5; }
  ::placeholder{ color:#a7a294; opacity:1; }
  .topband{ height:6px; background:var(--yellow); }
  .wrap{ max-width:1000px; margin:0 auto; padding:32px 32px 60px; }
  @media (max-width:680px){ .wrap{ padding:24px 16px 48px; } }

  header.app{ display:flex; align-items:center; gap:.85rem; margin-bottom:1.7rem; flex-wrap:wrap; }
  .mark{ width:44px; height:44px; border-radius:12px; background:var(--yellow); color:var(--red); flex:none;
         display:flex; align-items:center; justify-content:center; font-weight:800; font-size:.82rem; letter-spacing:.02em; }
  .title{ flex:1; min-width:180px; }
  .title h1{ font-size:1.25rem; font-weight:650; margin:0; letter-spacing:-.01em; }
  .title p{ margin:.1rem 0 0; color:var(--muted); font-size:.85rem; }
  .pill{ display:flex; align-items:center; gap:.5rem; font-family:ui-monospace,"SF Mono",Menlo,monospace;
         font-size:.74rem; color:var(--muted); border:1px solid var(--border); border-radius:8px; padding:.45rem .8rem; background:#fff; white-space:nowrap; }
  .pill.online{ color:var(--go); }
  .pill.offline{ color:var(--red); }
  .pdot{ width:8px; height:8px; border-radius:50%; background:currentColor; flex:none; }

  .grid{ display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:.7rem; margin-bottom:.9rem; }
  @media (max-width:860px){ .grid{ grid-template-columns:1fr 1fr; } }
  @media (max-width:520px){ .grid{ grid-template-columns:1fr; } }
  .cmd{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:.9rem 1rem; }
  .lbl{ font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); font-weight:600; margin-bottom:.6rem; }
  .col{ display:flex; flex-direction:column; gap:.4rem; }

  .btn{ font:inherit; font-size:.8rem; font-weight:550; cursor:pointer; border-radius:8px; padding:.5rem .7rem;
        border:1px solid var(--border2); background:transparent; color:var(--text); text-align:left;
        transition:border-color .12s, color .12s, filter .12s, transform .1s; }
  .btn:hover{ border-color:var(--red); color:var(--red); }
  .btn:active{ transform:scale(.98); }
  .btn.primary{ border-color:var(--red); background:var(--red); color:#fff; }
  .btn.primary:hover{ filter:brightness(1.08); color:#fff; border-color:var(--red); }
  .btn.go{ border-color:var(--go); background:var(--go); color:#fff; }
  .btn.go:hover{ filter:brightness(1.08); color:#fff; border-color:var(--go); }
  .btn.mini{ font-size:.74rem; padding:.3rem .7rem; }

  input, textarea{ font:inherit; font-size:.8rem; color:var(--text); background:var(--input); border:1px solid var(--border);
        border-radius:8px; padding:.5rem .7rem; width:100%; box-sizing:border-box; }
  input:focus, textarea:focus{ outline:none; border-color:var(--red); box-shadow:0 0 0 3px rgba(212,5,17,.15); }

  .card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:1.1rem 1.2rem; margin-bottom:.9rem; }
  .statuscard{ font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:.76rem; line-height:1.7; padding:.9rem 1.1rem; }
  .statushd{ display:flex; align-items:center; gap:.6rem; margin-bottom:.35rem; }
  .sdot{ width:8px; height:8px; border-radius:50%; flex:none; background:var(--muted); transition:background .2s; }
  .sstate{ text-transform:uppercase; letter-spacing:.08em; font-weight:600; font-size:.7rem; color:var(--muted); }
  .stime{ color:var(--muted); margin-left:auto; font-size:.7rem; }
  .sdetail{ color:var(--ink); }
  pre.output{ margin:.6rem 0 0; padding:.8rem .9rem; background:var(--input); border:1px solid var(--border); border-radius:8px;
        white-space:pre-wrap; font-size:.72rem; line-height:1.5; color:var(--ink); max-height:340px; overflow:auto;
        font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }

  .tkhd{ display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:1rem; }
  .tkhd .lbl{ margin-bottom:0; }
  .tkrows{ display:flex; flex-direction:column; gap:.6rem; }
  .tkrow{ background:var(--input); border:1px solid var(--border); border-radius:10px; padding:.85rem 1rem;
          display:flex; align-items:center; gap:1.2rem; }
  @media (max-width:760px){ .tkrow{ flex-direction:column; align-items:stretch; gap:.8rem; } }
  .tkmeta{ width:250px; flex:none; }
  @media (max-width:760px){ .tkmeta{ width:auto; } }
  .tkmeta .ord{ font-weight:650; font-size:.88rem; }
  .tkmeta .ord .mat{ color:var(--muted); font-weight:400; }
  .tkmeta .sub{ color:var(--muted); font-size:.74rem; overflow:hidden; text-overflow:ellipsis; }
  .pipe{ flex:1; display:flex; align-items:center; min-width:0; }
  .stage{ display:flex; flex-direction:column; align-items:center; gap:.25rem; width:70px; flex:none; }
  .stage .cdot{ width:11px; height:11px; border-radius:50%; box-sizing:border-box; }
  .stage .slbl{ font-size:.62rem; text-transform:uppercase; letter-spacing:.06em; text-align:center; white-space:nowrap; }
  .stage.done .cdot{ background:var(--go); } .stage.done .slbl{ color:var(--text); }
  .stage.chased .cdot{ background:var(--yellow); } .stage.chased .slbl{ color:var(--amberink); }
  .stage.pending .cdot{ background:transparent; border:2px solid var(--border2); } .stage.pending .slbl{ color:var(--faint); }
  .pline{ flex:1; height:2px; margin-bottom:1rem; background:var(--line); min-width:14px; }
  .pline.on{ background:var(--go); }
  .tktime{ width:90px; flex:none; text-align:right; font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:.7rem; color:var(--muted); }
  @media (max-width:760px){ .tktime{ width:auto; text-align:left; } }
  .tktime.amber{ color:var(--amberink); }

  .files{ display:flex; align-items:center; gap:1rem; margin-top:1rem; padding-top:.8rem; border-top:1px solid var(--border);
          font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:.7rem; color:var(--faint); flex-wrap:wrap; }
  .files .fname{ color:var(--ink); cursor:pointer; }
  .files .fname:hover{ color:var(--red); }
  .files .dlall{ margin-left:auto; color:var(--red); cursor:pointer; }
  .files .dlall:hover{ text-decoration:underline; }

  .hint{ color:var(--muted); font-size:.78rem; }
  .warn{ color:var(--red); font-size:.8rem; }

  #login{ position:fixed; inset:0; background:var(--bg); display:none; align-items:center; justify-content:center; z-index:10; }
  #login .lcard{ width:min(420px,90vw); background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:1.3rem 1.4rem; }
  #login h2{ font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); font-weight:600; margin:0 0 1rem; }
  .lrow{ display:flex; gap:.6rem; align-items:center; }
</style></head><body>
<div class="topband"></div>
<div id="login">
  <div class="lcard">
    <h2>Access key</h2>
    <div class="lrow">
      <input id="keyin" type="password" placeholder="Enter your access key" onkeydown="if(event.key==='Enter')saveKey()">
      <button class="btn primary" style="flex:none; text-align:center;" onclick="saveKey()">Unlock</button>
    </div>
    <div class="hint" style="margin-top:.6rem;">This dashboard is private. The key was set when it was deployed.</div>
  </div>
</div>

<div class="wrap">
  <header class="app">
    <div class="mark">DHL</div>
    <div class="title">
      <h1>DHL Haulage Desk</h1>
      <p>Region 2 &middot; review &amp; send in Outlook web</p>
    </div>
    <div class="pill" id="agentpill"><span class="pdot"></span><span id="agenttext">HOME PC &middot; CHECKING…</span></div>
    <div class="pill"><span id="clock">--:--:--</span></div>
  </header>

  <div class="grid">
    <div class="cmd">
      <div class="lbl">Today's extract</div>
      <div class="col">
        <button class="btn primary" onclick="previewBatch()">Preview &amp; send</button>
        <button class="btn" onclick="cmd('commit')">Save as drafts</button>
      </div>
    </div>
    <div class="cmd">
      <div class="lbl">Send order(s)</div>
      <div class="col">
        <input id="ord" placeholder="Order no(s). — space-separate to group" autocomplete="off" onkeydown="if(event.key==='Enter')findOrder()">
        <button class="btn" onclick="findOrder()">Find &amp; preview</button>
      </div>
    </div>
    <div class="cmd">
      <div class="lbl">Process DTS</div>
      <div class="col">
        <input id="dts" placeholder="NN reference" autocomplete="off" onkeydown="if(event.key==='Enter')processDts()">
        <button class="btn primary" onclick="processDts()">Process</button>
      </div>
    </div>
    <div class="cmd">
      <div class="lbl">Ad hoc form</div>
      <div class="col">
        <input id="frm" placeholder="Blank = latest" autocomplete="off" onkeydown="if(event.key==='Enter')processForm()">
        <button class="btn primary" onclick="processForm()">Build CSV</button>
      </div>
    </div>
  </div>

  <div class="card" id="editpanel" style="display:none;">
    <div class="lbl" style="margin-bottom:.8rem;">Review &amp; send</div>
    <div class="col" style="gap:.6rem;">
      <input id="eto" placeholder="To">
      <input id="ecc" placeholder="Cc (optional)">
      <input id="esub" placeholder="Subject">
      <textarea id="emsg" rows="14" spellcheck="false" style="line-height:1.55; font-size:.85rem; resize:vertical;"></textarea>
      <div style="display:flex; gap:.6rem; align-items:center; flex-wrap:wrap;">
        <button class="btn go" onclick="sendEdited()">Send email</button>
        <span class="hint">edit anything above first — signature &amp; QR are added automatically. Cc and multi-order grouping need the HOMEPC_CHANGES.md update on the home PC.</span>
      </div>
    </div>
  </div>

  <div class="card" id="batchpanel" style="display:none;">
    <div class="tkhd">
      <div class="lbl">Today's batch — <span id="bcount">…</span> <span class="hint" style="font-weight:400">· tick the ones to send, then Send</span></div>
      <div style="display:flex; gap:.4rem;">
        <button class="btn mini" onclick="batchAll(true)">All</button>
        <button class="btn mini" onclick="batchAll(false)">None</button>
        <button class="btn go" onclick="sendBatch()">Send selected</button>
      </div>
    </div>
    <div id="batchrows"></div>
  </div>

  <div class="card statuscard">
    <div class="statushd">
      <span class="sdot" id="dot"></span>
      <span class="sstate" id="state">idle</span>
      <span class="stime" id="time"></span>
    </div>
    <div class="sdetail" id="detail">Waiting for a command.</div>
    <div id="dropped" hidden style="margin-top:.6rem;"></div>
    <pre class="output" id="output" hidden></pre>
  </div>

  <div class="card">
    <div class="tkhd">
      <div class="lbl">Tracker — <span id="tkcount">…</span></div>
      <div style="display:flex; gap:.4rem;">
        <button class="btn mini" onclick="runChasers()">Run chasers</button>
        <button class="btn mini" onclick="refreshTracker()">Check replies</button>
      </div>
    </div>
    <div class="tkrows" id="tracker"><span class="hint">Loading…</span></div>
    <div class="files" id="files"><span>FILES:</span><span style="color:var(--faint)">loading…</span></div>
  </div>

  <div class="card">
    <div class="tkhd">
      <div class="lbl">Wait list — <span id="wlcount">…</span> <span class="hint" style="font-weight:400">· held until ~14 days before delivery, then auto-sent</span></div>
      <div style="display:flex; gap:.4rem;">
        <button class="btn mini" onclick="releaseWaitlist()">Release due now</button>
      </div>
    </div>
    <div class="tkrows" id="waitlist"><span class="hint">Loading…</span></div>
  </div>
</div>

<script>
const COLORS={idle:'var(--muted)',queued:'var(--amber)',running:'var(--amber)',done:'var(--go)',error:'var(--red)',preview_ready:'var(--red)',batch_ready:'var(--amber)'};
let currentOrder='';
let lastPreviewAt='';
let agentOnline=false;
let queueTtl=600;
let filesCache=[];
function ttlText(){ return queueTtl>=60 ? Math.floor(queueTtl/60)+' minutes' : queueTtl+' seconds'; }
function esc(t){ return String(t).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function clearDropped(){ try{ await api('/api/dropped_clear',{method:'POST'}); poll(); }catch(e){} }
function ago(s){
  if(s<60) return s+'s ago';
  if(s<3600) return Math.floor(s/60)+' min ago';
  if(s<86400) return Math.floor(s/3600)+' h '+Math.floor((s%3600)/60)+' min ago';
  return Math.floor(s/86400)+' day'+(s<172800?'':'s')+' ago';
}
function fmtDt(s){
  if(!s) return '';
  const m = String(s).match(/(\\d{4})-(\\d{2})-(\\d{2})[ T](\\d{2}:\\d{2})/);
  return m ? m[3]+'/'+m[2]+' '+m[4] : String(s);
}
function fsize(n){ return n>1048576 ? (n/1048576).toFixed(1)+' MB' : Math.max(1,Math.round(n/1024))+' KB'; }
function key(){ return localStorage.getItem('r2key')||''; }
function showLogin(){ document.getElementById('login').style.display='flex'; }
function saveKey(){
  localStorage.setItem('r2key', document.getElementById('keyin').value.trim());
  document.getElementById('login').style.display='none';
  poll(); loadTracker(); loadWaitlist(); loadFiles();
}
async function api(path, opts){
  opts=opts||{}; opts.headers=Object.assign({}, opts.headers||{}, {'X-Auth':key()});
  const r=await fetch(path, opts);
  if(r.status===401){ showLogin(); throw new Error('auth'); }
  return r;
}
async function post(body){
  await api('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  setTimeout(poll,250);
}
function hideEdit(){ document.getElementById('editpanel').style.display='none'; }
function hideBatch(){ const b=document.getElementById('batchpanel'); if(b) b.style.display='none'; }
function cmd(a){ hideEdit(); hideBatch(); post({action:a}); }
let batchCache=[];
function previewBatch(){ hideEdit(); hideBatch(); lastPreviewAt=''; post({action:'extract_preview'}); }
function batchAll(on){ document.querySelectorAll('.bchk').forEach(c=>c.checked=on); }
function toggleB(i){ const el=document.getElementById('bbody'+i); if(el) el.hidden=!el.hidden; }
function renderBatch(list){
  batchCache=list||[];
  document.getElementById('bcount').textContent = (list.length===1?'1 email':list.length+' emails');
  document.getElementById('batchrows').innerHTML = list.map((e,i)=>
    '<div style="padding:.5rem 0; border-bottom:1px solid var(--line); display:flex; gap:.55rem; align-items:center; flex-wrap:wrap;">'
    + '<input type="checkbox" class="bchk" data-i="'+i+'" checked style="width:16px; height:16px;">'
    + '<span class="ord">'+esc((e.orders||[]).join(" / "))+'</span>'
    + '<span class="sub" style="flex:1; min-width:140px;">'+esc(e.to||'(no recipient)')+' · '+esc(e.date||'')+(e.materials?' · '+esc(e.materials):'')+'</span>'
    + '<button class="btn mini" onclick="toggleB('+i+')">view</button>'
    + '<pre id="bbody'+i+'" hidden style="flex-basis:100%; white-space:pre-wrap; background:rgba(0,0,0,.045); padding:.6rem; margin:.35rem 0 0; font-size:.8rem; line-height:1.5; border-radius:6px;">'
      +esc('Subject: '+(e.subject||'')+'\\n\\n'+(e.message||''))+'</pre>'
    + '</div>').join('');
  document.getElementById('batchpanel').style.display='block';
}
function sendBatch(){
  const sel=[...document.querySelectorAll('.bchk')].filter(c=>c.checked).map(c=>c.dataset.i);
  if(!sel.length){ alert('Nothing ticked — select at least one email.'); return; }
  const q = agentOnline
    ? 'Send '+sel.length+' email'+(sel.length>1?'s':'')+' now from your DHL account?'
    : 'The home PC is OFFLINE — nothing can send right now.\\n\\nQueue it anyway? It sends if the home PC reconnects within '+ttlText()+', otherwise it is discarded.';
  if(!confirm(q)) return;
  hideBatch();
  post({action:'extract_send', sel: sel.join(',')});
}
function findOrder(){
  // several order numbers (any of space , ; / + &) become one grouped email
  const o=document.getElementById('ord').value.trim().split(/[\\s,;\\/+&]+/).filter(Boolean).join(' ');
  if(!o) return;
  currentOrder=o; hideEdit(); lastPreviewAt='';
  post({action:'order_preview',order:o});
}
function processDts(){
  const r=document.getElementById('dts').value.trim(); if(!r) return;
  post({action:'dts', order:r});
}
function processForm(){
  post({action:'form', order:(document.getElementById('frm').value.trim()||'latest')});
}
function sendEdited(){
  const q = agentOnline
    ? 'Send this email (with any edits you made)?'
    : 'The home PC is OFFLINE — nothing can send right now.\\n\\nQueue it anyway? It sends if the home PC reconnects within '+ttlText()+', otherwise it is discarded and you will see an error here.';
  if(!confirm(q)) return;
  hideEdit();
  post({action:'order_send_edited', order:currentOrder, email:{
    to:document.getElementById('eto').value.trim(),
    cc:document.getElementById('ecc').value.trim(),
    subject:document.getElementById('esub').value.trim(),
    message:document.getElementById('emsg').value
  }});
}
async function poll(){
  try{
    const s=await (await api('/api/status')).json();
    const c=COLORS[s.state]||'var(--muted)';
    document.getElementById('dot').style.background=c;
    const st=document.getElementById('state'); st.textContent=(s.state||'idle').replace('_',' '); st.style.color=c;
    agentOnline = !!s.agent_online;
    if(s.queue_ttl) queueTtl = s.queue_ttl;
    let det = s.detail||'';
    if(s.queued>0 && !agentOnline) det += ' ('+s.queued+' waiting for home PC)';
    document.getElementById('detail').textContent=det;
    document.getElementById('time').textContent=s.at||'';
    const pill=document.getElementById('agentpill');
    pill.classList.toggle('online', agentOnline);
    pill.classList.toggle('offline', !agentOnline);
    document.getElementById('agenttext').textContent = 'HOME PC ' + (agentOnline ? 'ONLINE' : 'OFFLINE');
    pill.title = agentOnline ? 'home PC online'
      : (s.agent_seen_ago==null ? 'not seen since the app last restarted' : 'last seen '+ago(s.agent_seen_ago));
    const o=document.getElementById('output');
    if(s.output){ o.textContent=s.output; o.hidden=false; } else { o.hidden=true; }
    const dr=document.getElementById('dropped');
    if(s.dropped && s.dropped.length){
      dr.innerHTML = s.dropped.map(d=>'<div class="warn">&#9888; NOT sent/run: '
          +esc(d.action)+(d.order?' ('+esc(d.order)+')':'')+' — expired '+esc(d.at)+' before the home PC picked it up</div>').join('')
        +'<button class="btn mini" style="margin-top:.5rem;" onclick="clearDropped()">Dismiss</button>';
      dr.hidden=false;
    } else { dr.hidden=true; }
    const ep=document.getElementById('editpanel');
    if(s.state==='preview_ready' && s.email && s.email.length){
      if(s.at!==lastPreviewAt){
        lastPreviewAt=s.at;
        document.getElementById('eto').value=s.email[0].to||'';
        document.getElementById('ecc').value=s.email[0].cc||'';
        document.getElementById('esub').value=s.email[0].subject||'';
        document.getElementById('emsg').value=s.email[0].message||'';
      }
      ep.style.display='block';
    } else if(s.state!=='preview_ready'){ ep.style.display='none'; }
    const bp=document.getElementById('batchpanel');
    if(s.state==='batch_ready' && s.email && s.email.length){
      if(s.at!==lastPreviewAt){ lastPreviewAt=s.at; renderBatch(s.email); }
      bp.style.display='block';
    } else if(s.state!=='batch_ready'){ if(bp) bp.style.display='none'; }
  }catch(e){}
}
function refreshTracker(){
  post({action:'tracker_refresh'});
  document.getElementById('tracker').innerHTML='<span class="hint">Checking replies & drafting send-off briefs…</span>';
  setTimeout(loadTracker, 6000);
}
function runChasers(){
  if(!confirm('Send follow-up chasers to every order that is 2+ business days overdue a reply?')) return;
  post({action:'run_chasers'});
}
function stage(cls,label){ return '<div class="stage '+cls+'"><span class="cdot"></span><span class="slbl">'+label+'</span></div>'; }
function pline(on){ return '<div class="pline'+(on?' on':'')+'"></div>'; }
async function loadTracker(){
  try{
    const d = await (await api('/api/tracker')).json();
    const recs = d.records || [];
    document.getElementById('tkcount').textContent =
      recs.length===1 ? '1 open order group' : recs.length+' open order groups';
    const host = document.getElementById('tracker');
    if(!recs.length){ host.innerHTML='<span class="hint">Nothing tracked yet — sent orders will appear here.</span>'; return; }
    host.innerHTML = recs.map(r=>{
      const emailed = !!r.emailed_at;
      const chased  = (r.chases||0) > 0;
      const reply   = !!r.reply_at;
      const ooo     = !!r.ooo_at;
      const sendoff = !!r.sendoff_ready;
      const s1 = stage('done','Drafted');
      const s2 = chased ? stage('chased','Chased ×'+r.chases) : stage(emailed?'done':'pending','Emailed');
      const s3 = ooo ? stage('chased','Out of office') : stage(reply?'done':'pending','Reply');
      const s4 = stage(sendoff?'done':'pending','Send-off');
      const pipe = '<div class="pipe">'+s1+pline(emailed||chased)+s2+pline(reply)+s3+pline(sendoff)+s4+'</div>';
      const mat = r.materials ? ' <span class="mat">· '+esc(r.materials)+'</span>' : '';
      const t = fmtDt(r.emailed_at);
      return '<div class="tkrow">'
        + '<div class="tkmeta"><div class="ord">'+esc((r.orders||[]).join(' / '))+mat+'</div>'
        + '<div class="sub">'+esc(r.to||'')+'</div></div>'
        + pipe
        + '<div class="tktime'+(chased?' amber':'')+'">'+esc(t)+'</div>'
        + '</div>';
    }).join('');
  }catch(e){}
}
function releaseWaitlist(){
  if(!confirm('Send now any wait-listed order already within its 14-day window? (Already-emailed and past-date ones are skipped automatically.)')) return;
  post({action:'waitlist_release'});
}
function wlDays(dd){
  const m=String(dd).match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})/); if(!m) return null;
  const today=new Date(); today.setHours(0,0,0,0);
  const dt=new Date(+m[3],+m[2]-1,+m[1]);
  return Math.round((dt-today)/86400000);
}
async function loadWaitlist(){
  try{
    const d = await (await api('/api/waitlist')).json();
    const show = (d.entries||[]).filter(e=>e.status==='waiting'||e.status==='missed');
    const host=document.getElementById('waitlist');
    const isOver = e => e.status==='missed' || (wlDays(e.date)!==null && wlDays(e.date)<0);
    const over = show.filter(isOver).length;
    document.getElementById('wlcount').textContent =
      (show.length===1?'1 held':show.length+' held') + (over? ' · '+over+' NEED ATTENTION':'');
    if(!show.length){ host.innerHTML='<span class="hint">Nothing waiting — far-ahead orders appear here and auto-send ~14 days before delivery.</span>'; return; }
    show.sort((a,b)=>((wlDays(a.date)??1e9)-(wlDays(b.date)??1e9)));
    host.innerHTML = show.map(e=>{
      const n=wlDays(e.date);
      const overdue = isOver(e);
      const due = !overdue && n!==null && n>=0 && n<=14;
      const col = overdue?'var(--red)':(due?'var(--amber)':'var(--line)');
      const tagcol = overdue?'var(--red)':(due?'var(--amber)':'var(--muted)');
      const tag = e.status==='missed' ? 'MISSED — action needed'
                : (n!==null && n<0) ? ('OVERDUE '+Math.abs(n)+'d — action needed')
                : (due?('DUE in '+n+'d'):(n+'d away'));
      return '<div class="tkrow" style="border-left:3px solid '+col+'; padding-left:.6rem;">'
        + '<div class="tkmeta"><div class="ord">'+esc((e.orders||[]).join(' / '))+'</div>'
        + '<div class="sub">'+esc(e.site||'')+' '+esc(e.postcode||'')+' · '+esc(e.to||'')+'</div></div>'
        + '<div class="tktime" style="color:'+tagcol+'; text-align:right">deliver '+esc(e.date)
        + '<br><b>'+tag+'</b></div>'
        + '</div>';
    }).join('');
  }catch(e){}
}
async function loadFiles(){
  try{
    const d = await (await api('/api/files')).json();
    const fs = d.files || [];
    filesCache = fs;
    const host = document.getElementById('files');
    if(!fs.length){ host.innerHTML='<span>FILES:</span><span style="color:var(--faint)">none yet</span>'; return; }
    host.innerHTML = '<span>FILES:</span>'
      + fs.map(f=>'<span class="fname" onclick="dl(&quot;'+encodeURIComponent(f.name)+'&quot;)" title="'
          +esc(f.name)+' · '+fsize(f.size)+' · '+esc(f.at)+'">'+esc(f.name)+'</span>').join('')
      + '<span class="dlall" onclick="dlAll()">download all ↓</span>';
  }catch(e){}
}
function dlAll(){ filesCache.forEach((f,i)=> setTimeout(()=>dl(encodeURIComponent(f.name)), i*350)); }
async function dl(encName){
  try{
    const d = await (await api('/api/file?name='+encName)).json();
    const bin = atob(d.data);
    const arr = new Uint8Array(bin.length);
    for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr]));
    const a = document.createElement('a'); a.href=url; a.download=d.name;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }catch(e){}
}
function tick(){ document.getElementById('clock').textContent = new Date().toTimeString().slice(0,8); }
setInterval(tick,1000); tick();
setInterval(poll,1500); poll();
setInterval(loadTracker,6000); loadTracker();
setInterval(loadWaitlist,6000); loadWaitlist();
setInterval(loadFiles,6000); loadFiles();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _key(self):
        return self.headers.get("X-Auth", "")

    def _is_dash(self):
        return DASH_KEY and self._key() == DASH_KEY

    def _is_agent(self):
        global _agent_seen
        if AGENT_KEY and self._key() == AGENT_KEY:
            _agent_seen = time.time()
            return True
        return False

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            with _lock:
                _sweep_queue_locked()
                out = dict(_status)
                out["agent_online"] = _agent_online()
                out["agent_seen_ago"] = int(time.time() - _agent_seen) if _agent_seen else None
                out["queued"] = len(_queue)
                out["queue_ttl"] = _QUEUE_TTL
                out["dropped"] = list(_dropped)
            self._json(200, out)
        elif self.path == "/api/next":
            seen_before = _agent_seen
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                _sweep_queue_locked(agent_seen=seen_before)
                cmd = _queue.pop(0) if _queue else None
            if cmd:
                cmd.pop("queued_at", None)
            self._json(200, cmd or {})
        elif self.path == "/api/tracker":
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            with _lock:
                self._json(200, _tracker)
        elif self.path == "/api/waitlist":
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            with _lock:
                self._json(200, _waitlist)
        elif self.path == "/api/files":
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            with _lock:
                lst = [{"name": n, "size": f["size"], "at": f["at"]}
                       for n, f in reversed(list(_files.items()))]
            self._json(200, {"files": lst})
        elif self.path.startswith("/api/file?name="):
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            from urllib.parse import unquote
            name = unquote(self.path.split("name=", 1)[1])
            with _lock:
                f = _files.get(name)
            if not f:
                return self._json(404, {"error": "gone"})
            self._json(200, {"name": name, "data": f["data"]})
        elif self.path == "/api/heartbeat":
            # agent liveness ping - _is_agent() refreshes the last-seen clock
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            self._json(200, {"ok": True})
        elif self.path == "/healthz":
            self._json(200, {"ok": True, "files": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global _tracker, _waitlist
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        if self.path == "/api/command":
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            with _lock:
                _queue.append({"action": data.get("action", "preview"), "order": data.get("order", ""),
                               "email": data.get("email"), "sel": data.get("sel"), "queued_at": time.time()})
                det = f"{data.get('action')} queued"
                if not _agent_online():
                    det += f" — home PC is offline; runs when it reconnects or expires after {_ttl_text()}"
                _status.update(state="queued", detail=det,
                               at=datetime.now().strftime("%H:%M:%S"), output="", email=None)
            self._json(200, {"ok": True})
        elif self.path == "/api/status":
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                _status.update(state=data.get("state", "idle"), detail=data.get("detail", ""),
                               at=datetime.now().strftime("%H:%M:%S"), output=data.get("output", ""),
                               email=data.get("email"))
            self._json(200, {"ok": True})
        elif self.path == "/api/dropped_clear":
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            with _lock:
                _dropped.clear()
            self._json(200, {"ok": True})
        elif self.path == "/api/tracker":
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                if isinstance(data, dict) and "records" in data:
                    _tracker = data
            self._json(200, {"ok": True})
        elif self.path == "/api/waitlist":
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                if isinstance(data, dict) and "entries" in data:
                    _waitlist = data
            self._json(200, {"ok": True})
        elif self.path == "/api/files":
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            name = str(data.get("name", ""))[:120]
            if name and data.get("data"):
                with _lock:
                    _files.pop(name, None)
                    _files[name] = {"data": data["data"], "size": int(data.get("size", 0)),
                                    "at": datetime.now().strftime("%d/%m %H:%M")}
                    while len(_files) > _MAX_FILES:
                        _files.pop(next(iter(_files)))
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})


if __name__ == "__main__":
    if not DASH_KEY or not AGENT_KEY:
        print("REFUSING TO START: set DASH_KEY and AGENT_KEY environment variables.")
        sys.exit(1)
    print(f"Cloud control plane on {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
