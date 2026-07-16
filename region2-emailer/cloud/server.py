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
_upload = None       # one pending browser->agent file upload {name, data(b64), at}
_agent_seen = 0.0
_files = {}          # name -> {"data": b64, "size": int, "at": str}
_MAX_FILES = 12
try:
    _QUEUE_TTL = int(os.environ.get("QUEUE_TTL", "600"))   # seconds an unclaimed command stays queued
except ValueError:
    _QUEUE_TTL = 600


_dropped = []        # expired-unrun commands, kept until dismissed from the dashboard
_MAX_DROPPED = 8
_panel = {}          # agent-pushed persistent panel state: site decisions, handover, team


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
    --bg:#f4f4f2; --card:#ffffff; --text:#1b1c1e; --muted:#8a8b88; --faint:#a3a49e; --ink:#4b4c48;
    --border:#e9e8e4; --border2:#e3e2dd; --line:#f0efec; --input:#fbfbfa; --seg:#ebeae6;
    --yellow:#ffcc00; --red:#d40511; --go:#1da35e; --goink:#18804a; --gobg:#eef6ef; --gobd:#dcebdf;
    --amber:#d99e00; --amberink:#93650a; --dark:#1b1c1e; --dark2:#323335;
    --radius:16px;
    --shadow:0 1px 2px rgba(25,25,20,.03), 0 12px 32px rgba(25,25,20,.04);
  }
  body{ margin:0; background:var(--bg); color:var(--text); -webkit-font-smoothing:antialiased;
        font-family:'Geist',-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; line-height:1.5; }
  ::placeholder{ color:#b4b4ae; opacity:1; }
  .mono{ font-family:'Geist Mono',ui-monospace,"SF Mono",Menlo,monospace; }
  .topband{ height:3px; background:var(--yellow); }
  .wrap{ max-width:1080px; margin:0 auto; padding:22px 28px 60px; }
  @media (max-width:680px){ .wrap{ padding:18px 14px 48px; } }

  header.app{ display:flex; align-items:center; gap:14px; margin-bottom:16px; padding:15px 20px;
        background:var(--card); border:1px solid var(--border); border-radius:14px; box-shadow:var(--shadow); flex-wrap:wrap; }
  .mark{ width:38px; height:38px; border-radius:11px; background:var(--yellow); color:var(--dark); flex:none;
         display:flex; align-items:center; justify-content:center; font-weight:750; font-size:14px; letter-spacing:-.02em; }
  .title{ flex:1; min-width:170px; }
  .title h1{ font-size:16px; font-weight:650; margin:0; letter-spacing:-.02em; line-height:1.2; }
  .title p{ margin:2px 0 0; color:var(--muted); font-size:12px; }
  .pill{ display:flex; align-items:center; gap:.5rem; font-size:12px; font-weight:550;
         color:var(--muted); border:1px solid var(--border); border-radius:999px; padding:6px 12px; background:var(--input); white-space:nowrap; }
  .pill.online{ color:var(--goink); background:var(--gobg); border-color:var(--gobd); }
  .pill.offline{ color:var(--red); background:#fdeef0; border-color:#f6d9dc; }
  .pdot{ width:7px; height:7px; border-radius:50%; background:currentColor; flex:none; }

  .grid{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:14px; }
  @media (max-width:860px){ .grid{ grid-template-columns:1fr 1fr; } }
  @media (max-width:520px){ .grid{ grid-template-columns:1fr; } }
  .cmd{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:15px 17px; box-shadow:var(--shadow); }
  .lbl{ font-size:10.5px; text-transform:uppercase; letter-spacing:.1em; color:var(--faint); font-weight:650; margin-bottom:10px; }
  .col{ display:flex; flex-direction:column; gap:8px; }

  .btn{ font:inherit; font-size:13px; font-weight:550; cursor:pointer; border-radius:10px; padding:9px 13px;
        border:1px solid var(--border2); background:var(--card); color:var(--text); text-align:left;
        transition:border-color .12s, background .12s, color .12s, transform .1s; }
  .btn:hover{ border-color:#c8c7c0; background:var(--input); }
  .btn:active{ transform:scale(.98); }
  .btn.primary{ border-color:var(--dark); background:var(--dark); color:#fff; font-weight:600; }
  .btn.primary:hover{ background:var(--dark2); border-color:var(--dark2); color:#fff; }
  .btn.go{ border-color:var(--go); background:var(--go); color:#fff; font-weight:600; }
  .btn.go:hover{ filter:brightness(1.06); color:#fff; border-color:var(--go); }
  .btn.mini{ font-size:12px; padding:6px 11px; border-radius:9px; }

  input, textarea, select{ font:inherit; font-size:13px; color:var(--text); background:var(--input); border:1px solid var(--border2);
        border-radius:10px; padding:9px 12px; width:100%; box-sizing:border-box; }
  input:focus, textarea:focus, select:focus{ outline:none; border-color:var(--dark); box-shadow:0 0 0 3px rgba(27,28,30,.08); }

  .card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:18px 22px; margin-bottom:14px; box-shadow:var(--shadow); }
  .statuscard{ font-size:13px; line-height:1.65; padding:14px 18px; }
  .statushd{ display:flex; align-items:center; gap:10px; margin-bottom:5px; }
  .sdot{ width:8px; height:8px; border-radius:50%; flex:none; background:var(--faint); transition:background .2s; }
  .sstate{ text-transform:uppercase; letter-spacing:.08em; font-weight:700; font-size:11px; color:var(--faint); }
  .stime{ color:var(--faint); margin-left:auto; font-size:11.5px; font-family:'Geist Mono',ui-monospace,Menlo,monospace; }
  .sdetail{ color:var(--text); }
  pre.output{ margin:10px 0 0; padding:12px 14px; background:var(--input); border:1px solid var(--border); border-radius:10px;
        white-space:pre-wrap; font-size:12px; line-height:1.5; color:var(--ink); max-height:340px; overflow:auto;
        font-family:'Geist Mono',ui-monospace,"SF Mono",Menlo,Consolas,monospace; }

  .tkhd{ display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:14px; flex-wrap:wrap; }
  .tkhd .lbl{ margin-bottom:0; font-size:15px; text-transform:none; letter-spacing:-.01em; color:var(--text); font-weight:650; }
  .tkrows{ display:flex; flex-direction:column; gap:0; }
  .tkrow{ border-bottom:1px solid var(--line); padding:13px 2px; display:flex; align-items:center; gap:20px; }
  .tkrow:last-child{ border-bottom:none; }
  @media (max-width:760px){ .tkrow{ flex-direction:column; align-items:stretch; gap:.8rem; } }
  .tkmeta{ width:270px; flex:none; }
  @media (max-width:760px){ .tkmeta{ width:auto; } }
  .ord{ font-weight:600; font-size:13.5px; }
  .sub{ color:var(--muted); font-size:12px; }
  .tkmeta .ord{ font-weight:600; font-size:13.5px; }
  .tkmeta .ord .mat{ color:var(--muted); font-weight:450; }
  .tkmeta .sub{ color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; margin-top:1px; }
  .pipe{ flex:1; display:flex; align-items:center; gap:5px; min-width:0; }
  .seg{ flex:1; height:5px; border-radius:99px; background:var(--seg); min-width:12px; }
  .seg.done{ background:var(--go); }
  .seg.chased{ background:var(--amber); }
  .seg.pending{ background:var(--seg); }
  .tktime{ width:120px; flex:none; text-align:right; font-family:'Geist Mono',ui-monospace,Menlo,monospace; font-size:11.5px; color:var(--muted); }
  .tktime b{ font-family:'Geist',-apple-system,system-ui,sans-serif; font-weight:600; font-size:12.5px; }
  @media (max-width:760px){ .tktime{ width:auto; text-align:left; } }
  .tktime.amber, .tktime.amber b{ color:var(--amberink); }
  .brow.urgent, .tkrow.urgent{ background:#fdeef0; border-left:3px solid var(--red); padding-left:9px; }
  .pri{ display:inline-block; font-size:9.5px; font-weight:700; letter-spacing:.04em; color:#fff;
        background:var(--red); border-radius:6px; padding:2px 7px; margin-left:3px; white-space:nowrap; }

  .files{ display:flex; align-items:center; gap:8px; margin-top:14px; padding-top:12px; border-top:1px solid var(--line);
          font-family:'Geist Mono',ui-monospace,"SF Mono",Menlo,monospace; font-size:11.5px; color:var(--faint); flex-wrap:wrap; }
  .files>span:first-child{ font-family:'Geist',-apple-system,system-ui,sans-serif; font-size:10px; font-weight:650; text-transform:uppercase; letter-spacing:.1em; color:var(--faint); }
  .files .fname{ color:var(--ink); cursor:pointer; background:#f6f6f3; border:1px solid var(--border); border-radius:8px; padding:5px 10px; }
  .files .fname:hover{ border-color:#c8c7c0; color:var(--text); }
  .files .dlall{ margin-left:auto; color:var(--text); font-weight:600; cursor:pointer; }
  .files .dlall:hover{ color:var(--red); }

  .hint{ color:var(--muted); font-size:12px; }
  .warn{ color:var(--red); font-size:13px; }

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
    <div class="mark">HD</div>
    <div class="title">
      <h1>Haulage Desk</h1>
      <p>DHL &middot; Region 2 &middot; review &amp; send in Outlook web</p>
    </div>
    <div class="pill" id="agentpill"><span class="pdot"></span><span id="agenttext">HOME PC &middot; CHECKING…</span></div>
    <div class="pill mono"><span id="clock">--:--:--</span></div>
  </header>

  <div class="grid">
    <div class="cmd">
      <div class="lbl">Today's extract</div>
      <div class="col">
        <button class="btn primary" onclick="previewBatch()">Scan, preview &amp; send</button>
        <button class="btn" onclick="cmd('commit')">Save as drafts</button>
      </div>
    </div>
    <div class="cmd">
      <div class="lbl">Upcoming weeks</div>
      <div class="col">
        <button class="btn" onclick="previewBatch('next')">Next week</button>
        <button class="btn" onclick="previewBatch('after')">Week after</button>
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
    <div class="cmd">
      <div class="lbl">Rail plan</div>
      <div class="col">
        <input type="file" id="rpfile" accept=".csv" style="font-size:.74rem;">
        <select id="rpweek" style="font:inherit; font-size:.8rem; padding:.4rem;">
          <option value="next">Next week — new plan</option>
          <option value="current">Current week — update</option>
        </select>
        <div style="display:flex; gap:.4rem;">
          <button class="btn" onclick="railPlan('preview')">Preview</button>
          <button class="btn primary" onclick="railPlan('send')">Build &amp; send</button>
        </div>
      </div>
    </div>
    <div class="cmd">
      <div class="lbl">Order upload</div>
      <div class="col">
        <input type="file" id="oufile" accept=".xlsx,.xls" style="font-size:.74rem;">
        <button class="btn primary" onclick="orderUpload()">Map &amp; build CSV</button>
      </div>
    </div>
    <div class="cmd">
      <div class="lbl">Holiday cover</div>
      <div class="col">
        <button class="btn" id="holbtn" onclick="toggleHoliday()">Set up handover</button>
      </div>
    </div>
  </div>

  <div class="card" id="matchpanel" style="display:none;">
    <div class="lbl" style="margin-bottom:.8rem;">Delivery site decisions — no exact Synergy match, pick where each should go</div>
    <div class="col" id="matchrows" style="gap:.6rem;"></div>
  </div>

  <div class="card" id="holiday" style="display:none;">
    <div class="lbl" style="margin-bottom:.8rem;">Holiday / send-off handover</div>
    <div id="holform" class="col" style="gap:.6rem;">
      <div style="display:flex; gap:.6rem; flex-wrap:wrap;">
        <input id="hdays" type="number" min="1" max="60" value="5" style="width:110px;" title="Days away">
        <select id="hcover" style="flex:1; min-width:220px;"><option value="">Covering team member…</option></select>
      </div>
      <textarea id="hnotes" rows="3" placeholder="Notes / instructions for whoever covers (optional)"></textarea>
      <label class="hint" style="display:flex; align-items:center; gap:.45rem; cursor:pointer;">
        <input id="hfwd" type="checkbox" checked style="width:auto;"> auto-forward incoming replies while away
      </label>
      <div style="display:flex; gap:.6rem; align-items:center; flex-wrap:wrap;">
        <button class="btn go" onclick="startHandover()">Start handover</button>
        <span class="hint">sends the outstanding-work batch email to your cover now, then forwards replies until your return date</span>
      </div>
    </div>
    <div id="holactive" style="display:none;">
      <div class="sdetail" id="holinfo" style="margin-bottom:.6rem;"></div>
      <button class="btn" onclick="stopHandover()">End handover now</button>
    </div>
  </div>

  <div class="card" id="sitespanel" style="display:none;">
    <div class="lbl" style="margin-bottom:.6rem;">Unknown collection sites — add details, then re-process</div>
    <div id="siterows"></div>
    <div style="margin-top:.7rem;"><button class="btn go" onclick="saveSites()">Save &amp; re-process</button></div>
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
    <div class="hint" style="margin:-6px 0 12px; font-size:11.5px;">Progress: Drafted &rarr; Emailed &rarr; Reply &rarr; Send-off</div>
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
const COLORS={idle:'var(--muted)',queued:'var(--amber)',running:'var(--amber)',done:'var(--go)',error:'var(--red)',preview_ready:'var(--red)',batch_ready:'var(--amber)',sites_needed:'var(--red)'};
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
function previewBatch(week){ hideEdit(); hideBatch(); lastPreviewAt=''; post({action:'extract_preview', week: week||''}); }
function batchAll(on){ document.querySelectorAll('.bchk').forEach(c=>c.checked=on); }
function toggleB(i){ const el=document.getElementById('bbody'+i); if(el) el.hidden=!el.hidden; }
function days3(dd){ const n=wlDays(dd); return n!==null && n>=0 && n<=3; }
function isUrgent(e){ return days3(e.date||e.delivery_date) || !!e.loose_ballast; }
function urgScore(e){ return (days3(e.date||e.delivery_date)?2:0)+(e.loose_ballast?1:0); }
function priBadges(e){
  return (e.loose_ballast?'<span class="pri">LOOSE BALLAST</span>':'')
       + (days3(e.date||e.delivery_date)?'<span class="pri">&le;3 DAYS</span>':'');
}
function renderBatch(list){
  batchCache=list||[];
  document.getElementById('bcount').textContent = (list.length===1?'1 email':list.length+' emails');
  const rows=(list||[]).map((e,i)=>({e,i}));
  rows.sort((a,b)=>urgScore(b.e)-urgScore(a.e));   // priority (loose ballast / <=3 days) first
  document.getElementById('batchrows').innerHTML = rows.map(({e,i})=>
    '<div class="brow'+(isUrgent(e)?' urgent':'')+'" style="padding:.5rem; border-bottom:1px solid var(--line); display:flex; gap:.55rem; align-items:center; flex-wrap:wrap;">'
    + '<input type="checkbox" class="bchk" data-i="'+i+'" checked style="width:16px; height:16px;">'
    + '<span class="ord">'+esc((e.orders||[]).join(" / "))+'</span>'
    + priBadges(e)
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
async function railPlan(mode){
  const f=document.getElementById('rpfile').files[0];
  const week=document.getElementById('rpweek').value;
  if(!f){ alert('Pick the CTMS rail-plan CSV first.'); return; }
  if(mode==='send' && !confirm('Build and SEND the rail plan to all suppliers, hauliers and your DHL colleagues?')) return;
  try{
    const data=await new Promise((res,rej)=>{ const r=new FileReader(); r.onload=()=>res(String(r.result).split(',')[1]); r.onerror=rej; r.readAsDataURL(f); });
    await api('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name,data})});
    post({action:'rail_plan', mode, week});
  }catch(e){ alert('Upload failed: '+e); }
}
async function orderUpload(){
  const f=document.getElementById('oufile').files[0];
  if(!f){ alert('Pick the Synergy extract (.xlsx) first.'); return; }
  try{
    const data=await new Promise((res,rej)=>{ const r=new FileReader(); r.onload=()=>res(String(r.result).split(',')[1]); r.onerror=rej; r.readAsDataURL(f); });
    await api('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name,data})});
    lastPreviewAt=''; post({action:'order_upload'});
  }catch(e){ alert('Upload failed: '+e); }
}
function siteField(site,key,ph){ return '<input data-site="'+encodeURIComponent(site)+'" data-k="'+key+'" placeholder="'+ph+'" style="font:inherit; font-size:.75rem; padding:.35rem;">'; }
function renderSites(list){
  document.getElementById('siterows').innerHTML=list.map(u=>{
    const s=(u&&u.site)||u; const n=(u&&u.count)||0;
    return '<div style="border:1px solid var(--border); border-radius:8px; padding:.6rem; margin-bottom:.5rem;">'
      +'<div class="ord" style="margin-bottom:.4rem;">'+esc(s)+(n?' <span class="sub">('+n+' order'+(n>1?'s':'')+')</span>':'')+'</div>'
      +'<div style="display:grid; grid-template-columns:1fr 1fr; gap:.4rem;">'
      +siteField(s,'contact','Contact name')+siteField(s,'postcode','Postcode')
      +siteField(s,'telephone','Telephone')+siteField(s,'email','Email')
      +siteField(s,'start_hours','Start hrs 07:00:00')+siteField(s,'close_hours','Close hrs 17:00:00')
      +'</div><div style="margin-top:.4rem;">'+siteField(s,'notes','Notes (optional)')+'</div></div>';
  }).join('');
  document.getElementById('sitespanel').style.display='block';
}
function saveSites(){
  const sites={};
  document.querySelectorAll('#siterows input').forEach(inp=>{
    const s=decodeURIComponent(inp.dataset.site);
    (sites[s]=sites[s]||{})[inp.dataset.k]=inp.value.trim();
  });
  if(!Object.keys(sites).length) return;
  document.getElementById('sitespanel').style.display='none';
  lastPreviewAt=''; post({action:'add_sites', sites});
}
let panelCache={};
let panelJson='';
let holidayOpen=false;
function toggleHoliday(){ holidayOpen=!holidayOpen; renderPanel(); }
function renderPanel(){
  const p=panelCache||{};
  const decs=p.decisions||[];
  const mp=document.getElementById('matchpanel');
  if(decs.length){
    document.getElementById('matchrows').innerHTML=decs.map((d,i)=>{
      const opts=(d.options||[]).concat((p.sites||[]).filter(s=>!(d.options||[]).includes(s)));
      return '<div style="display:flex; gap:.6rem; align-items:center; flex-wrap:wrap;">'
        +'<span style="min-width:220px;"><span class="ord">'+esc(d.raw)+'</span>'
        +(d.context?' <span class="sub">'+esc(d.context)+'</span>':'')+'</span>'
        +'<select id="dsel'+i+'" style="flex:1; min-width:220px;">'
        +opts.map(o=>'<option>'+esc(o)+'</option>').join('')
        +'</select>'
        +'<button class="btn mini go" onclick="saveDecision('+i+')">Save</button></div>';
    }).join('');
    mp.style.display='block';
  } else { mp.style.display='none'; }
  const h=p.handover||{};
  const active=!!h.active;
  document.getElementById('holform').style.display = active?'none':'flex';
  document.getElementById('holactive').style.display = active?'block':'none';
  if(active){
    document.getElementById('holinfo').textContent =
      'Handover active — '+(h.cover_name||h.cover_email||'?')+' covers until '+(h.end||'?')
      +(h.forward?' · replies auto-forward':' · no forwarding');
  }
  document.getElementById('holbtn').textContent = active ? 'Handover: ON' : (holidayOpen?'Hide handover':'Set up handover');
  document.getElementById('holiday').style.display = (active||holidayOpen) ? 'block' : 'none';
  const hc=document.getElementById('hcover');
  if(hc){
    const cur=hc.value;   // keep the current pick across the 30s panel refresh
    hc.innerHTML='<option value="">Covering team member…</option>'
      +(p.team||[]).map(m=>'<option value="'+esc(m.name||'')+'">'+esc(m.name||'')+'</option>').join('');
    if(cur) hc.value=cur;
  }
}
function saveDecision(i){
  const d=(panelCache.decisions||[])[i]; if(!d) return;
  const site=document.getElementById('dsel'+i).value; if(!site) return;
  post({action:'site_decision', data:{raw:d.raw, site:site}});
}
function startHandover(){
  const cover=document.getElementById('hcover').value.trim();
  if(!cover){ alert('Who is covering? Pick a team member.'); return; }
  const days=parseInt(document.getElementById('hdays').value,10)||5;
  if(!confirm('Start handover: '+cover+' covers for '+days+' day(s)?\\n\\nThis sends them the outstanding-work email now.')) return;
  holidayOpen=false;
  post({action:'handover_start', data:{days:days, cover:cover,
    notes:document.getElementById('hnotes').value,
    forward:document.getElementById('hfwd').checked}});
}
function stopHandover(){
  if(!confirm('End the handover now and stop forwarding?')) return;
  post({action:'handover_stop', data:{}});
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
    const sp=document.getElementById('sitespanel');
    if(s.state==='sites_needed' && s.email && s.email.length){
      if(s.at!==lastPreviewAt){ lastPreviewAt=s.at; renderSites(s.email); }
      sp.style.display='block';
    } else if(s.state!=='sites_needed'){ if(sp) sp.style.display='none'; }
    const pj=JSON.stringify(s.panel||{});
    if(pj!==panelJson){ panelJson=pj; panelCache=s.panel||{}; renderPanel(); }
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
function seg(state){ return '<span class="seg '+state+'"></span>'; }
async function loadTracker(){
  try{
    const d = await (await api('/api/tracker')).json();
    const recs = d.records || [];
    document.getElementById('tkcount').textContent =
      recs.length===1 ? '1 open order group' : recs.length+' open order groups';
    const host = document.getElementById('tracker');
    if(!recs.length){ host.innerHTML='<span class="hint">Nothing tracked yet — sent orders will appear here.</span>'; return; }
    const sorted = recs.slice().sort((a,b)=>urgScore(b)-urgScore(a));   // <=3-day deliveries first
    host.innerHTML = sorted.map(r=>{
      const emailed = !!r.emailed_at;
      const chased  = (r.chases||0) > 0;
      const reply   = !!r.reply_at;
      const ooo     = !!r.ooo_at;
      const sendoff = !!r.sendoff_ready;
      const b2 = chased?'chased':(emailed?'done':'pending');
      const b3 = ooo?'chased':(reply?'done':'pending');
      const b4 = sendoff?'done':'pending';
      const pipe = '<div class="pipe">'+seg('done')+seg(b2)+seg(b3)+seg(b4)+'</div>';
      const status = sendoff?'Sent off':(ooo?'Out of office':(chased?('Chased ×'+r.chases):(reply?'Replied':'Awaiting reply')));
      const amber = (ooo||chased);
      const u = days3(r.delivery_date);
      const mat = r.materials ? ' <span class="mat">· '+esc(r.materials)+'</span>' : '';
      const t = fmtDt(r.emailed_at);
      return '<div class="tkrow'+(u?' urgent':'')+'">'
        + '<div class="tkmeta"><div class="ord">'+esc((r.orders||[]).join(' / '))+mat+(u?' <span class="pri">&le;3 DAYS</span>':'')+'</div>'
        + '<div class="sub">'+esc(r.to||'')+'</div>'
        + '<button class="btn mini" style="margin-top:.45rem" onclick="bookedCall(\\''+encodeURIComponent(r.id||'')+'\\')">Booked via call</button>'
        + '</div>'
        + pipe
        + '<div class="tktime'+(amber?' amber':'')+'"><b>'+esc(status)+'</b><br>'+esc(t)+'</div>'
        + '</div>';
    }).join('');
  }catch(e){}
}
function bookedCall(encId){
  const id = decodeURIComponent(encId);
  if(!id) return;
  const ord = id.split('|')[0];
  if(!confirm('Mark '+ord+' as booked over the phone and remove it from the tracker?')) return;
  post({action:'booked_call', order:id});
  document.getElementById('tracker').style.opacity='.6';
  setTimeout(loadTracker, 2500);
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
                out["panel"] = _panel
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
        elif self.path == "/api/pull_upload":
            # agent collects a file the browser uploaded (rail-plan CSV etc.)
            global _upload
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                up = _upload
                _upload = None
            self._json(200, up or {})
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
        global _tracker, _waitlist, _upload
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
                               "email": data.get("email"), "sel": data.get("sel"),
                               "mode": data.get("mode"), "week": data.get("week"),
                               "sites": data.get("sites"), "data": data.get("data"),
                               "queued_at": time.time()})
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
        elif self.path == "/api/panel":
            # agent replaces the persistent panel state (decisions/handover/team)
            global _panel
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            if isinstance(data, dict) and length < 400_000:
                with _lock:
                    _panel = data
            self._json(200, {"ok": True})
        elif self.path == "/api/upload":
            # browser uploads a file for the agent to process (rail-plan CSV etc.)
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            name = str(data.get("name", ""))[:150]
            if name and data.get("data"):
                with _lock:
                    _upload = {"name": name, "data": data["data"],
                               "at": datetime.now().strftime("%H:%M:%S")}
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
