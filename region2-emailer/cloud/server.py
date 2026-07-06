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
    return (time.time() - _agent_seen) < 15


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
<title>Region 2 emailer</title>
<style>
  *{ box-sizing:border-box; }
  :root{
    --bg:#f3f4f6; --card:#ffffff; --text:#1f2430; --muted:#6b7280; --border:#e6e8ec;
    --accent:#2f6bff; --go:#17a34a; --amber:#d68112; --red:#dc2b2b;
    --radius:14px; --shadow:0 1px 2px rgba(16,24,40,.05), 0 4px 12px rgba(16,24,40,.04);
  }
  @media (prefers-color-scheme:dark){
    :root{ --bg:#0d0f13; --card:#171a20; --text:#e8eaed; --muted:#98a0ab; --border:#262a31;
           --accent:#5a8bff; --go:#2ec25f; --amber:#eaa53c; --red:#f0574f;
           --shadow:0 1px 2px rgba(0,0,0,.5); }
  }
  body{ margin:0; background:var(--bg); color:var(--text); -webkit-font-smoothing:antialiased;
        font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; line-height:1.55; }
  .wrap{ max-width:640px; margin:0 auto; padding:2.75rem 1.25rem 4rem; }
  header{ display:flex; align-items:center; gap:.85rem; margin-bottom:1.9rem; }
  .mark{ width:44px; height:44px; border-radius:12px; background:var(--accent); color:#fff; flex:none;
         display:flex; align-items:center; justify-content:center; font-weight:700; font-size:.95rem; }
  header h1{ font-size:1.3rem; font-weight:650; margin:0; letter-spacing:-.01em; }
  header p{ margin:.15rem 0 0; color:var(--muted); font-size:.9rem; }
  .agentdot{ display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--muted); margin-right:.35rem; }
  .card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
         box-shadow:var(--shadow); padding:1.3rem 1.4rem; margin-bottom:1.1rem; }
  .card h2{ font-size:.76rem; text-transform:uppercase; letter-spacing:.07em; color:var(--muted);
            font-weight:600; margin:0 0 1rem; }
  .controls{ display:flex; gap:.6rem; flex-wrap:wrap; align-items:center; }
  input{ flex:1; min-width:200px; font:inherit; color:var(--text); background:transparent;
         border:1px solid var(--border); border-radius:10px; padding:.65rem .8rem; }
  input:focus{ outline:none; border-color:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 20%,transparent); }
  .btn{ font:inherit; font-weight:550; cursor:pointer; border-radius:10px; padding:.65rem 1.05rem;
        border:1px solid var(--border); background:transparent; color:var(--text); transition:transform .1s, border-color .12s, color .12s; }
  .btn:hover{ border-color:var(--accent); color:var(--accent); }
  .btn:active{ transform:scale(.98); }
  .btn.primary{ background:var(--accent); border-color:var(--accent); color:#fff; }
  .btn.go{ background:var(--go); border-color:var(--go); color:#fff; }
  .btn.primary:hover, .btn.go:hover{ filter:brightness(1.06); color:#fff; }
  .hint{ color:var(--muted); font-size:.85rem; align-self:center; }
  .statusline{ display:flex; align-items:center; gap:.6rem; flex-wrap:wrap; }
  .dot{ width:9px; height:9px; border-radius:50%; background:var(--muted); flex:none; transition:background .2s; }
  .state{ font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; font-weight:650; }
  .detail{ font-size:.92rem; }
  .time{ color:var(--muted); font-size:.8rem; margin-left:auto; }
  pre.output{ margin:1rem 0 0; padding:.95rem 1.05rem; background:var(--bg); border:1px solid var(--border);
              border-radius:10px; white-space:pre-wrap; font-size:.8rem; line-height:1.5; color:var(--muted);
              font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; max-height:360px; overflow:auto; }
  .tk-wrap{ overflow-x:auto; }
  table.tk{ width:100%; border-collapse:collapse; font-size:.8rem; }
  table.tk th{ text-align:left; color:var(--muted); font-weight:600; padding:.45rem .5rem; border-bottom:1px solid var(--border); white-space:nowrap; }
  table.tk td{ padding:.5rem .5rem; border-bottom:1px solid var(--border); vertical-align:top; }
  .ok{ color:var(--go); font-weight:600; }
  .no{ color:var(--muted); }
  .chip{ display:inline-block; background:var(--amber); color:#fff; border-radius:6px; padding:0 .4rem; font-size:.7rem; margin-left:.3rem; }
  .rf{ float:right; padding:.32rem .7rem; font-size:.78rem; text-transform:none; letter-spacing:normal; }
  #login{ position:fixed; inset:0; background:var(--bg); display:none; align-items:center; justify-content:center; z-index:10; }
  #login .card{ width:min(420px, 90vw); }
</style></head><body>
<div id="login">
  <div class="card">
    <h2>Access key</h2>
    <div class="controls">
      <input id="keyin" type="password" placeholder="Enter your access key"
             onkeydown="if(event.key==='Enter')saveKey()">
      <button class="btn primary" onclick="saveKey()">Unlock</button>
    </div>
    <div class="hint" style="margin-top:.6rem;">This dashboard is private. The key was set when it was deployed.</div>
  </div>
</div>
<div class="wrap">
  <header>
    <div class="mark">R2</div>
    <div>
      <h1>Region 2 emailer</h1>
      <p><span class="agentdot" id="agentdot"></span><span id="agenttext">home PC: checking…</span> &middot; review &amp; send in Outlook web</p>
    </div>
  </header>

  <div class="card">
    <h2>Today's extract</h2>
    <div class="controls">
      <button class="btn" onclick="cmd('preview')">Build today's drafts (preview)</button>
      <button class="btn primary" onclick="cmd('commit')">Build &amp; save drafts</button>
    </div>
  </div>

  <div class="card">
    <h2>Send one order</h2>
    <div class="controls">
      <input id="ord" placeholder="Order number, e.g. 6054999" autocomplete="off"
             onkeydown="if(event.key==='Enter')findOrder()">
      <button class="btn" onclick="findOrder()">Find &amp; preview</button>
    </div>
    <div id="editpanel" style="display:none; margin-top:.9rem;">
      <div class="controls" style="margin-bottom:.6rem;">
        <input id="eto" placeholder="To" style="flex:1;">
      </div>
      <div class="controls" style="margin-bottom:.6rem;">
        <input id="ecc" placeholder="Cc (optional)" style="flex:1;">
      </div>
      <div class="controls" style="margin-bottom:.6rem;">
        <input id="esub" placeholder="Subject" style="flex:1;">
      </div>
      <textarea id="emsg" rows="14" spellcheck="false"
        style="width:100%; box-sizing:border-box; font:inherit; font-size:.9rem; color:var(--text);
               background:transparent; border:1px solid var(--border); border-radius:10px;
               padding:.65rem .8rem; resize:vertical;"></textarea>
      <div class="controls" style="margin-top:.6rem;">
        <button class="btn go" onclick="sendEdited()">Send email</button>
        <span class="hint">edit anything above first — signature &amp; QR are added automatically. Cc only works once the home PC has the HOMEPC_CHANGES.md update.</span>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Process DTS</h2>
    <div class="controls">
      <input id="dts" placeholder="NN reference, e.g. NN5139446-260" autocomplete="off"
             onkeydown="if(event.key==='Enter')processDts()">
      <button class="btn primary" onclick="processDts()">Process DTS</button>
    </div>
    <div class="hint" style="margin-top:.6rem;">Finds the DTS PDF in your email, fills the Haulage Request Form and builds the upload CSV. Both land in the outbox on the home PC (auto-cleared after 2 days).</div>
  </div>

  <div class="card">
    <h2>Ad hoc form (already filled)</h2>
    <div class="controls">
      <input id="frm" placeholder="Reference or filename — blank = latest form" autocomplete="off"
             onkeydown="if(event.key==='Enter')processForm()">
      <button class="btn primary" onclick="processForm()">Build upload CSV</button>
    </div>
    <div class="hint" style="margin-top:.6rem;">Reads the filled Haulage Request Form from your email and builds the upload CSV in the outbox.</div>
  </div>

  <div class="card">
    <h2>Status</h2>
    <div class="statusline">
      <span class="dot" id="dot"></span>
      <span class="state" id="state">idle</span>
      <span class="detail" id="detail">Waiting for a command.</span>
      <span class="time" id="time"></span>
    </div>
    <div id="dropped" hidden style="margin-top:.8rem;"></div>
    <pre class="output" id="output" hidden></pre>
  </div>

  <div class="card">
    <h2>Files from home PC</h2>
    <div class="tk-wrap" id="files"><span class="hint">Files created by DTS / form jobs appear here to download.</span></div>
  </div>

  <div class="card">
    <h2>Tracker <button class="btn rf" onclick="refreshTracker()">Refresh from Outlook</button></h2>
    <div class="tk-wrap" id="tracker"><span class="hint">Loading…</span></div>
  </div>
</div>
<script>
const COLORS={idle:'var(--muted)',queued:'var(--amber)',running:'var(--amber)',done:'var(--go)',error:'var(--red)',preview_ready:'var(--accent)'};
let currentOrder='';
let lastPreviewAt='';
let agentOnline=false;
let queueTtl=600;
function ttlText(){ return queueTtl>=60 ? Math.floor(queueTtl/60)+' minutes' : queueTtl+' seconds'; }
function esc(t){ return String(t).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function clearDropped(){ try{ await api('/api/dropped_clear',{method:'POST'}); poll(); }catch(e){} }
function ago(s){
  if(s<60) return s+'s ago';
  if(s<3600) return Math.floor(s/60)+' min ago';
  if(s<86400) return Math.floor(s/3600)+' h '+Math.floor((s%3600)/60)+' min ago';
  return Math.floor(s/86400)+' day'+(s<172800?'':'s')+' ago';
}
function key(){ return localStorage.getItem('r2key')||''; }
function showLogin(){ document.getElementById('login').style.display='flex'; }
function saveKey(){
  localStorage.setItem('r2key', document.getElementById('keyin').value.trim());
  document.getElementById('login').style.display='none';
  poll(); loadTracker();
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
function cmd(a){ hideEdit(); post({action:a}); }
function findOrder(){
  const o=document.getElementById('ord').value.trim(); if(!o) return;
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
    const ad=document.getElementById('agentdot');
    ad.style.background = agentOnline ? 'var(--go)' : 'var(--red)';
    let at = 'home PC: ' + (agentOnline ? 'online' : 'offline');
    if(!agentOnline) at += (s.agent_seen_ago==null)
      ? ' — not seen since the app last restarted'
      : ' — last seen '+ago(s.agent_seen_ago);
    document.getElementById('agenttext').textContent = at;
    const o=document.getElementById('output');
    if(s.output){ o.textContent=s.output; o.hidden=false; } else { o.hidden=true; }
    const dr=document.getElementById('dropped');
    if(s.dropped && s.dropped.length){
      dr.innerHTML = s.dropped.map(d=>'<div style="color:var(--red); font-size:.85rem;">&#9888; NOT sent/run: '
          +esc(d.action)+(d.order?' ('+esc(d.order)+')':'')+' — expired '+esc(d.at)+' before the home PC picked it up</div>').join('')
        +'<button class="btn" style="margin-top:.5rem; padding:.3rem .8rem; font-size:.78rem;" onclick="clearDropped()">Dismiss</button>';
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
  }catch(e){}
}
function refreshTracker(){
  post({action:'tracker_refresh'});
  document.getElementById('tracker').innerHTML='<span class="hint">Refreshing from Outlook…</span>';
  setTimeout(loadTracker, 5000);
}
async function loadTracker(){
  try{
    const d = await (await api('/api/tracker')).json();
    const recs = d.records || [];
    if(!recs.length){ document.getElementById('tracker').innerHTML='<span class="hint">Nothing tracked yet — sent orders will appear here.</span>'; return; }
    const rows = recs.map(r => '<tr>'
      + '<td>'+r.orders.join(' / ')+'</td>'
      + '<td>'+(r.to||'')+'</td>'
      + '<td>'+(r.materials||'')+'</td>'
      + '<td>'+(r.source||'')+'</td>'
      + '<td>'+(r.emailed_at||'')+(r.chases?'<span class="chip">+'+r.chases+'</span>':'')+'</td>'
      + '<td>'+(r.reply_at?'<span class="ok">yes</span>':'<span class="no">—</span>')+'</td>'
      + '<td>'+(r.sendoff_ready?'<span class="ok">ready</span>':'<span class="no">—</span>')+'</td>'
      + '</tr>').join('');
    document.getElementById('tracker').innerHTML =
      '<table class="tk"><thead><tr><th>Order(s)</th><th>To</th><th>Materials</th><th>Synergy upload</th><th>Emailed</th><th>Reply</th><th>Send-off</th></tr></thead><tbody>'+rows+'</tbody></table>';
  }catch(e){}
}
async function loadFiles(){
  try{
    const d = await (await api('/api/files')).json();
    const fs = d.files || [];
    if(!fs.length){ document.getElementById('files').innerHTML='<span class="hint">Files created by DTS / form jobs appear here to download.</span>'; return; }
    const rows = fs.map(f => '<tr>'
      + '<td>'+f.name+'</td>'
      + '<td>'+(f.size>1048576 ? (f.size/1048576).toFixed(1)+' MB' : Math.max(1,Math.round(f.size/1024))+' KB')+'</td>'
      + '<td>'+f.at+'</td>'
      + '<td><button class="btn" style="padding:.3rem .8rem;font-size:.78rem;" onclick="dl(\\''+encodeURIComponent(f.name)+'\\')">Download</button></td>'
      + '</tr>').join('');
    document.getElementById('files').innerHTML =
      '<table class="tk"><thead><tr><th>File</th><th>Size</th><th>Created</th><th></th></tr></thead><tbody>'+rows+'</tbody></table>';
  }catch(e){}
}
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
setInterval(poll,1500); poll();
setInterval(loadTracker,6000); loadTracker();
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
        elif self.path == "/healthz":
            self._json(200, {"ok": True, "files": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global _tracker
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
                               "email": data.get("email"), "queued_at": time.time()})
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
