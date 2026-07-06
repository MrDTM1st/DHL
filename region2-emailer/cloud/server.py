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
        <input id="esub" placeholder="Subject" style="flex:1;">
      </div>
      <textarea id="emsg" rows="14" spellcheck="false"
        style="width:100%; box-sizing:border-box; font:inherit; font-size:.9rem; color:var(--text);
               background:transparent; border:1px solid var(--border); border-radius:10px;
               padding:.65rem .8rem; resize:vertical;"></textarea>
      <div class="controls" style="margin-top:.6rem;">
        <button class="btn go" onclick="sendEdited()">Send email</button>
        <span class="hint">edit anything above first — signature &amp; QR are added automatically</span>
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
    <pre class="output" id="output" hidden></pre>
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
  if(!confirm('Send this email (with any edits you made)?')) return;
  hideEdit();
  post({action:'order_send_edited', order:currentOrder, email:{
    to:document.getElementById('eto').value.trim(),
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
    document.getElementById('detail').textContent=s.detail||'';
    document.getElementById('time').textContent=s.at||'';
    const ad=document.getElementById('agentdot');
    ad.style.background = s.agent_online ? 'var(--go)' : 'var(--red)';
    document.getElementById('agenttext').textContent = 'home PC: ' + (s.agent_online ? 'online' : 'offline');
    const o=document.getElementById('output');
    if(s.output){ o.textContent=s.output; o.hidden=false; } else { o.hidden=true; }
    const ep=document.getElementById('editpanel');
    if(s.state==='preview_ready' && s.email && s.email.length){
      if(s.at!==lastPreviewAt){
        lastPreviewAt=s.at;
        document.getElementById('eto').value=s.email[0].to||'';
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
setInterval(poll,1500); poll();
setInterval(loadTracker,6000); loadTracker();
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
        return AGENT_KEY and self._key() == AGENT_KEY

    def do_GET(self):
        global _agent_seen
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
                out = dict(_status)
                out["agent_online"] = (time.time() - _agent_seen) < 15
            self._json(200, out)
        elif self.path == "/api/next":
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                _agent_seen = time.time()
                cmd = _queue.pop(0) if _queue else None
            self._json(200, cmd or {})
        elif self.path == "/api/tracker":
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            with _lock:
                self._json(200, _tracker)
        elif self.path == "/healthz":
            self._json(200, {"ok": True})
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
                               "email": data.get("email")})
                _status.update(state="queued", detail=f"{data.get('action')} queued",
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
        elif self.path == "/api/tracker":
            if not self._is_agent():
                return self._json(401, {"error": "auth"})
            with _lock:
                if isinstance(data, dict) and "records" in data:
                    _tracker = data
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})


if __name__ == "__main__":
    if not DASH_KEY or not AGENT_KEY:
        print("REFUSING TO START: set DASH_KEY and AGENT_KEY environment variables.")
        sys.exit(1)
    print(f"Cloud control plane on {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
