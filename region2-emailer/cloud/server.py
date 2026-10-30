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
import hashlib, hmac, json, os, re, sys, time, threading
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


# ---- CTMS bridge channel -------------------------------------------------
# The work PC runs work_pc/ctms_bridge.py, which drives the Edge window he
# logged into CTMS with himself. It is a channel of its own, NOT more actions
# on the home agent's queue: /api/next must never hand an Outlook command to
# the work PC, and the bridge must never be able to pull one. Its key opens
# the bridge's endpoints below and nothing else.
#
# That key is DERIVED from DASH_KEY, so there is nothing new to set on Railway:
# the bridge asks for the dashboard key once, derives the same value, and keeps
# only the derived one - the work PC never holds a key that can send email.
#
# Who may ask the bridge for what:
#   the dashboard (DASH_KEY)   everything - and it ALONE can switch "Claude can
#                              act" on, for a set time
#   the home PC (AGENT_KEY)    what Claude uses through ctms_remote.py: looking
#                              at any time, acting only while that switch is on,
#                              and asking the work PC to update itself
CTMS_KEY = (hmac.new(DASH_KEY.encode(), b"ctms-bridge-v1", hashlib.sha256).hexdigest()
            if DASH_KEY else "")
CTMS_OBSERVE = ("look", "capture", "net")          # the dashboard's own buttons
CTMS_READ = ("see", "wait", "tabs", "probe", "fields", "use")   # Claude looking
CTMS_DRIVE = ("steps", "paste",          # a batch of the window steps below / Claude's own text pasted
              "click", "type", "key", "select", "scroll", "hover", "goto", "back", "forward",
              "reload", "dialog", "tab", "drag")   # Claude acting - only while the switch is on
CTMS_ADMIN = ("update", "fields_setup")
CTMS_STEP_ACTIONS = ("click", "drag", "key", "type", "wait", "paste",   # what one of a batch's steps can be
                     "anchor", "waitfor", "check", "snap", "settle")   # ... and the batch looking between them
# The bridge refuses anything else on its own side as well; this list only
# stops something queuing that would just come back refused.
CTMS_ACTIONS = CTMS_OBSERVE + CTMS_READ + CTMS_DRIVE + CTMS_ADMIN
# A CTMS command is about the screen as it is NOW. "Capture this screen" run
# ten minutes late captures whatever is up ten minutes later, filed under the
# name of the screen you meant - so an unclaimed command expires in a minute,
# online or not. (The home agent's queue deliberately keeps its backlog; this
# one deliberately does not.)
_CTMS_TTL = 60
_CTMS_MAX_CAPTURES = 20
_CTMS_MAX_CAPTURE_B64 = 80_000_000   # all held captures together, in memory
_CTMS_MAX_PAYLOADS = 8               # screens sent back for Claude, newest kept
_CTMS_MAX_PAYLOAD_BYTES = 40_000_000
_CTMS_MAX_WAIT = 20                  # longest a check-in or a wait for a result is held open
_ctms = {
    "seen": 0.0,           # last bridge check-in
    "state": {},           # what the bridge last said about itself
    "queue": [],
    # Numbering starts from the clock, not 0: a dashboard left open across a
    # redeploy still holds the old numbers, and picture 1 or command 1 of the
    # new run must not be mistaken for the one it already has.
    "next_id": int(time.time()),
    "results": [],         # newest first
    "shot": None,          # the latest picture of the CTMS tab
    "next_shot": int(time.time()),
    "watch_until": 0.0,    # a dashboard has the CTMS page open until then
    "stop": False,         # one-shot, handed to the bridge on its next check-in
    "running": None,       # the command handed out and not yet answered
    "captures": {},        # name -> {data, size, at}, oldest first
    "control_until": 0.0,  # "Claude can act" is on until then (switched on from the dashboard only)
    "control_touched": False,   # switched on/off, or Stop, since this start: a carried ticket counts no more
    "payloads": {},        # command id -> {data, size}: the screen an answer came back with
    "asked": {},           # command id -> who asked, for the activity list
    "polling": 0,          # check-ins being held open right now
}
# Wakes a held check-in when there is work, and a held wait when its answer lands.
_ctms_cv = threading.Condition(_lock)


def _ctms_online():
    # The bridge checks in every 1-10s (a check-in is held open while it waits
    # for work), and capturing a heavy page holds it for several seconds
    # between check-ins - 20s rides that out.
    return _ctms["polling"] > 0 or (time.time() - _ctms["seen"]) < 20


def _ctms_armed():
    return time.time() < _ctms["control_until"]


def _ctms_control_locked():
    left = _ctms["control_until"] - time.time()
    return {"armed": left > 0, "left": max(0, int(left))}


# A deploy restarts this server and empties its memory - "Claude can act" with it, though Delali switched it on
# until a time of his choosing (29/10: "it gets really annoying when I have to turn it back on every single time").
# So while it is on, the bridge is handed a ticket: that time, signed with the dashboard's own key, which the
# bridge's key cannot make. After a restart the bridge hands it back and the switch is on again until that same
# time - never later, never once it has been switched off or Stop pressed since the restart, and the bridge
# drops it the moment it hears the switch is off.
def _ctms_ticket(until):
    until = int(until)
    return f"{until}." + hmac.new(DASH_KEY.encode(), f"ctms-control:{until}".encode(), hashlib.sha256).hexdigest()


def _ctms_ticket_until(ticket):
    """When a ticket the dashboard signed runs out - 0 for anything else."""
    try:
        until, sig = str(ticket).split(".", 1)
        until = int(until)
    except ValueError:
        return 0
    good = hmac.new(DASH_KEY.encode(), f"ctms-control:{until}".encode(), hashlib.sha256).hexdigest()
    return until if DASH_KEY and hmac.compare_digest(sig.encode(), good.encode()) else 0


def _ctms_result_locked(res):
    res = dict(res, ts=time.time(), at=datetime.now().strftime("%H:%M:%S"))
    _ctms["results"].insert(0, res)
    del _ctms["results"][30:]


def _ctms_note_locked(detail):
    """A line in the activity list for something the dashboard did itself."""
    _ctms["next_id"] += 1
    _ctms_result_locked({"id": _ctms["next_id"], "action": "control", "name": "", "ok": True,
                         "detail": detail, "by": "dashboard"})


def _ctms_cancel_locked(why, only=None):
    keep = []
    for c in _ctms["queue"]:
        if only is None or c["action"] in only:
            _ctms_result_locked({"id": c["id"], "action": c["action"], "name": c.get("name", ""),
                                 "ok": False, "detail": why, "by": c.get("by", "")})
        else:
            keep.append(c)
    _ctms["queue"] = keep


def _ctms_sweep_locked():
    now = time.time()
    keep = []
    for c in _ctms["queue"]:
        if now - c["queued_at"] > _CTMS_TTL:
            _ctms_result_locked({"id": c["id"], "action": c["action"], "name": c.get("name", ""),
                                 "ok": False, "by": c.get("by", ""),
                                 "detail": f"Not run - the work PC did not pick this up within "
                                           f"{_CTMS_TTL}s, so nothing was done. Ask again "
                                           f"once the bridge shows online."})
        else:
            keep.append(c)
    _ctms["queue"] = keep
    if not _ctms_armed() and any(c["action"] in CTMS_DRIVE for c in keep):
        _ctms_cancel_locked("Cancelled - Look mum, no hands mode ran out before the work PC got to it.",
                            only=CTMS_DRIVE)


def _ctms_args(action, data):
    """What a command may carry, each field checked and cut to size. Anything else is dropped."""
    out = {}

    def num(k, lo, hi, kind=float):
        try:
            v = kind(data[k])
        except (KeyError, TypeError, ValueError):
            return
        if lo <= v <= hi:
            out[k] = v
    if action == "capture":
        name = re.sub(r"[^A-Za-z0-9 ._-]+", "-", str(data.get("name") or ""))[:48].strip(" .-")
        out["name"] = name or "screen"
    for k in ("on", "commit", "enter", "append", "paste", "double", "right", "accept", "marks", "picture",
              "react", "not"):
        if k in data:
            out[k] = bool(data[k])
    num("ref", 1, 100000, int)
    num("tab", 1, 50, int)
    num("amount", 1, 20000, int)
    num("seconds", 0, 30)
    num("timeout", 0, 60)
    num("quiet", 0, 5)                     # a reacting step: how long the screen must hold still
    num("after", 0, 10)                    # a step's own pause instead of the usual one
    num("tol", 0, 255, int)                # how near a waited-for colour must be
    # a point (at/to: fractions; px/px2: the picture's own pixels, which the bridge moves by its anchor)
    for k in ("at", "to", "px", "px2"):
        pt = data.get(k)
        if isinstance(pt, (list, tuple)) and len(pt) == 2:
            try:
                out[k] = [max(0.0, min(float(pt[0]), 20000.0)), max(0.0, min(float(pt[1]), 20000.0))]
            except (TypeError, ValueError):
                pass
    box = data.get("box")                  # a part of the screen: watched by react, kept by snap
    if isinstance(box, (list, tuple)) and len(box) == 4:
        try:
            out["box"] = [max(0.0, min(float(v), 20000.0)) for v in box]
        except (TypeError, ValueError):
            pass
    if re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(data.get("color") or "")):
        out["color"] = "#" + str(data["color"]).lstrip("#").upper()
    if action == "snap":
        out["name"] = re.sub(r"[^A-Za-z0-9._-]+", "-", str(data.get("name") or ""))[:30].strip(".-") or "snap"
    for k, n in (("text", 2000), ("key", 40), ("option", 200), ("url", 2000)):
        if data.get(k) is not None:
            out[k] = str(data[k])[:n]
    snap = str(data.get("snap") or "")
    if re.fullmatch(r"s\d{1,9}", snap):
        out["snap"] = snap
    if data.get("dir") in ("up", "down", "left", "right", "to"):
        out["dir"] = data["dir"]
    if data.get("target") in ("ctms", "page"):      # which window the bridge works
        out["target"] = data["target"]
    branch = str(data.get("branch") or "")
    if re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch) and ".." not in branch:
        out["branch"] = branch
    if data.get("scope") in ("bridge", "all"):
        out["scope"] = data["scope"]
    if action == "paste" and data.get("text") is not None:
        out["text"] = str(data["text"])[:6000]          # rows for the tracker, tabs and line breaks kept
    if action == "steps" and isinstance(data.get("steps"), list):
        # each step checked like a command of its own; nothing but the window's own steps goes through
        out["steps"] = [dict(_ctms_args(s["action"], s), action=s["action"]) for s in data["steps"][:60]
                        if isinstance(s, dict) and s.get("action") in CTMS_STEP_ACTIONS]
    return out


# "Set up this PC": the work PC's whole setup as one file to double-click, with
# the bridge's own key already in it - so nothing is typed on the work PC. The
# template is ordinary Python next to this file (ctms_setup.py); one line of
# batch goes in front, which Windows runs and Python skips (python -x).
_SETUP_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctms_setup.py")
_SETUP_HEAD = '@python -x "%~f0" %* & pause & goto :eof\r\n'


def _ctms_setup_file(desk, allow, autostart):
    try:
        with open(_SETUP_TEMPLATE, encoding="utf-8") as f:
            tpl = f.read()
    except OSError:
        return None
    if "CONFIG = {}" not in tpl:
        return None
    cfg = {"desk": desk, "key": CTMS_KEY, "allow_control": bool(allow), "autostart": bool(autostart),
           "made": datetime.now().strftime("%d/%m/%Y %H:%M")}
    body = tpl.replace("CONFIG = {}", "CONFIG = " + repr(cfg), 1)
    return (_SETUP_HEAD + body.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8")


def _ctms_take_state_locked(s):
    """Keep what the bridge says about itself - known keys only, sizes capped.

    A check-in carries only what changed for the bulky parts (the network tail,
    the walkthrough screen list), so absent keys keep their last value.
    """
    if not isinstance(s, dict):
        return
    st = _ctms["state"]
    for k in ("attached", "net", "control", "autostart"):
        if k in s:
            st[k] = bool(s[k])
    for k in ("tabs", "net_count"):
        if k in s:
            try:
                st[k] = int(s[k])
            except (TypeError, ValueError):
                pass
    for k, n in (("browser", 80), ("tab_title", 200), ("tab_url", 500), ("mode", 20),
                 ("error", 300), ("version", 20), ("match", 80), ("machine", 60),
                 ("code", 60), ("code_at", 30), ("dialog", 300), ("rolled_back", 300), ("view", 20),
                 ("target", 10)):
        if k in s:
            st[k] = str(s[k] or "")[:n]
    if isinstance(s.get("window"), dict):
        w = s["window"]
        st["window"] = {"found": bool(w.get("found")), "title": str(w.get("title") or "")[:120],
                        "kind": str(w.get("kind") or "")[:10], "java": int(w.get("java") or 0)
                        if str(w.get("java") or "0").isdigit() else 0,
                        "showing": bool(w.get("showing")), "minimized": bool(w.get("minimized")),
                        "foreground": bool(w.get("foreground"))}
    if isinstance(s.get("net_tail"), list):
        st["net_tail"] = [{k: str(e.get(k) or "")[:300] for k in ("at", "method", "url", "status", "type", "mime")}
                          for e in s["net_tail"][-20:] if isinstance(e, dict)]
    if isinstance(s.get("screens"), list):
        st["screens"] = [[str(x)[:160] for x in pair[:2]] for pair in s["screens"][:20]
                         if isinstance(pair, (list, tuple)) and pair]


# ---- front end -----------------------------------------------------------
# The dashboard UI is the React app in ./web (built with Vite into a single
# self-contained index.html). We serve that built file at "/" and fall back to
# the inline PAGE below if the build is absent (e.g. running server.py straight
# from a checkout without building). The REST API is unchanged either way, so
# the home agent and the deployment model are untouched.
_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB_INDEX_CANDIDATES = [
    os.environ.get("WEB_INDEX", ""),          # explicit override
    os.path.join(_HERE, "web_index.html"),    # where the Dockerfile copies the build
    os.path.join(_HERE, "web", "dist", "index.html"),  # local `npm run build`
]


def _load_web_index():
    for p in _WEB_INDEX_CANDIDATES:
        if p and os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    return f.read(), p
            except OSError:
                pass
    return None, None


_WEB_INDEX, _WEB_INDEX_PATH = _load_web_index()

# ---- PWA assets (manifest / service worker / icons) ----------------------
# Served so the dashboard installs as an app on a phone. Files come from the
# Vite build's public/ dir: the Dockerfile copies the whole dist to ./web_dist,
# and a local checkout serves straight from web/dist after `npm run build`.
_PWA_FILES = {
    "/manifest.webmanifest": "application/manifest+json",
    "/sw.js": "text/javascript",
    "/icon-192.png": "image/png",
    "/icon-512.png": "image/png",
    "/apple-touch-icon.png": "image/png",
}


def _pwa_asset(path):
    name = path.lstrip("/")
    for base in (os.path.join(_HERE, "web_dist"), os.path.join(_HERE, "web", "dist"),
                 os.path.join(_HERE, "web", "public")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    return f.read()
            except OSError:
                pass
    return None


def _index_bytes():
    return _WEB_INDEX if _WEB_INDEX is not None else PAGE.encode()


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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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
  .tkitem{ border-bottom:1px solid var(--line); }
  .tkitem:last-child{ border-bottom:none; }
  .tkrow{ padding:13px 2px 6px 2px; display:flex; align-items:center; gap:20px; }
  .tkdet{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:0 2px 12px 2px; }
  .dchip{ font-size:11px; padding:3px 8px; border-radius:99px; background:var(--seg); color:var(--muted); }
  .dchip b{ color:var(--ink); font-weight:600; }
  .dchip.amber{ background:#fff4e5; color:var(--amberink); }
  .dchip a{ text-decoration:none; margin-left:5px; font-weight:700; }
  .dmiss{ font-size:11px; color:var(--red); font-weight:600; }
  #map{ height:400px; border-radius:12px; background:var(--seg); z-index:0; }
  /* ---- order detail overlay ---- */
  .ovl{ position:fixed; inset:0; background:rgba(20,20,18,.45); z-index:900;
        display:none; align-items:flex-start; justify-content:center; padding:24px 16px; overflow:auto; }
  .ovl.on{ display:flex; }
  .sheet{ background:var(--card); border-radius:var(--radius); box-shadow:var(--shadow);
          width:100%; max-width:920px; padding:20px 22px 22px; }
  .sheet h3{ margin:0 0 2px; font-size:17px; }
  .sheetsub{ color:var(--muted); font-size:12.5px; margin-bottom:14px; }
  .sheetgrid{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:760px){ .sheetgrid{ grid-template-columns:1fr; } }
  #dmap{ height:300px; border-radius:12px; background:var(--seg); z-index:0; }
  .kv{ display:grid; grid-template-columns:112px 1fr; gap:5px 10px; font-size:12.5px; }
  .kv dt{ color:var(--muted); }
  .kv dd{ margin:0; font-weight:600; }
  .runbar{ display:flex; align-items:center; gap:8px; margin:10px 0 4px; font-size:12px; color:var(--muted); }
  .runbar b{ color:var(--text); font-weight:600; }
  .hrow{ display:flex; align-items:center; gap:10px; padding:7px 2px; border-bottom:1px solid var(--line); font-size:12.5px; }
  .hrow:last-child{ border-bottom:none; }
  .hmi{ width:56px; text-align:right; font-family:'Geist Mono',ui-monospace,monospace; color:var(--muted); }
  .hnm{ flex:1; min-width:0; }
  .hnm b{ font-weight:600; }
  .hnm span{ color:var(--muted); }
  .fleet,.t1,.t2{ font-size:9.5px; font-weight:700; letter-spacing:.04em;
          border-radius:99px; padding:1px 6px; margin-left:6px; white-space:nowrap; }
  .fleet{ background:var(--gobg); color:var(--goink); border:1px solid var(--gobd); }
  .t1{ background:#eef2fb; color:#3a5185; border:1px solid #dde5f5; }
  .t2{ background:var(--seg); color:var(--muted); border:1px solid var(--border2); }
  .xbtn{ float:right; cursor:pointer; color:var(--muted); font-size:20px; line-height:1; }
  .leaflet-container{ font:inherit; }
  .maplegend{ font-size:11.5px; color:var(--muted); margin-top:8px; }
  .maplegend b{ font-weight:600; }
  .dotl{ display:inline-block; width:9px; height:9px; border-radius:99px; margin:0 3px 0 10px; vertical-align:baseline; }
  @media (max-width:760px){ .tkrow{ flex-direction:column; align-items:stretch; gap:.8rem; } }
  .tkmeta{ width:270px; flex:none; }
  @media (max-width:760px){ .tkmeta{ width:auto; } }
  .ord{ font-weight:600; font-size:13.5px; }
  .sub{ color:var(--muted); font-size:12px; }
  .tkmeta .ord{ font-weight:600; font-size:13.5px; }
  .tkmeta .ord .mat{ color:var(--muted); font-weight:450; }
  .tkmeta .sub{ color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; margin-top:1px; }
  .pipewrap{ flex:1; display:flex; flex-direction:column; gap:5px; min-width:0; }
  .pipe{ width:100%; display:flex; align-items:center; gap:5px; min-width:0; }
  .pipecap{ font-family:'Geist Mono',ui-monospace,Menlo,monospace; font-size:10.5px; color:var(--muted); text-align:center; letter-spacing:.02em; }
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

  <div class="card">
    <div class="tkhd">
      <div class="lbl">Map — deliveries &amp; collections</div>
      <div class="hint" id="maphint" style="font-weight:400"></div>
    </div>
    <div id="map"></div>
    <div class="maplegend"><b>Legend:</b><span class="dotl" style="background:#d40511"></span>tracked delivery
      <span class="dotl" style="background:#d99e00"></span>today's batch
      <span class="dotl" style="background:#1b1c1e"></span>collection depot
      <span class="dotl" style="background:#1da35e"></span>haulier (when the contact sheet is loaded)</div>
  </div>
</div>

<div class="ovl" id="detail" onclick="if(event.target===this)closeDetail()">
  <div class="sheet">
    <span class="xbtn" onclick="closeDetail()">&times;</span>
    <h3 id="dttl">Order</h3>
    <div class="sheetsub" id="dsub"></div>
    <div class="sheetgrid">
      <div>
        <dl class="kv" id="dkv"></dl>
        <div class="runbar" id="drun"></div>
      </div>
      <div>
        <div id="dmap"></div>
        <div class="maplegend" style="margin-top:6px;">
          <span class="dotl" style="background:#1b1c1e"></span>collection
          <span class="dotl" style="background:#d40511"></span>delivery
          <span class="dotl" style="background:#1da35e"></span>recommended haulier</div>
      </div>
    </div>
    <div class="lbl" style="margin:16px 0 2px;">Who to contact <span class="hint" style="font-weight:400" id="dneed"></span></div>
    <div id="drecs"><span class="hint">…</span></div>
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
function fmtDate(s){
  if(!s) return '';
  const m = String(s).match(/(\\d{4})-(\\d{2})-(\\d{2})/);
  return m ? m[3]+'/'+m[2] : String(s);
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
  _mapBatch=list||[]; renderMap();
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
  if((p.hauliers||[]).length !== _mapHauliers.length){ _mapHauliers=p.hauliers||[]; _mapSig=''; renderMap(); }
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
// ---- map: deliveries + collection depots (hauliers layer once the contact
// sheet with locations is provided). Geocoding via postcodes.io, cached.
// Carto "Positron" - the clean, low-contrast basemap. Roads are muted and
// minor detail drops away, so pins read clearly (OSM's default is far too
// road-dense for this).
const TILES='https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
const TILEATTR='&copy; OpenStreetMap &copy; CARTO';
let MAP=null, MLAYER=null, _mapSig='';
const GEO=JSON.parse(localStorage.getItem('r2geo')||'{}');
// depots carry fixed coords - industrial postcodes are sometimes terminated
// and fail geocoding, and these three must always be on the map
const DEPOTS=[['British Steel — Scunthorpe','DN16 1BP',53.579,-0.617],
              ['Inframat / VAS — Askern','DN6 0AA',53.616,-1.155],
              ['Arcelor Mittal — Marchwood','SO40 4UT',50.895,-1.442]];
function pcNorm(p){ return String(p||'').toUpperCase().replace(/\\s+/g,' ').trim(); }
function mapInit(){
  if(MAP || typeof L==='undefined' || !document.getElementById('map')) return;
  MAP=L.map('map',{scrollWheelZoom:false}).setView([52.8,-1.4],6);
  L.tileLayer(TILES,{maxZoom:19, subdomains:'abcd', attribution:TILEATTR}).addTo(MAP);
  MLAYER=L.layerGroup().addTo(MAP);
}
function outcodeOf(p){ const m=String(p||'').toUpperCase().replace(/\\s+/g,'').match(/^([A-Z]{1,2}\\d[A-Z\\d]?)/); return m?m[1]:''; }
async function geocode(pcs){
  const want=[...new Set(pcs.map(pcNorm).filter(Boolean))];
  const need=want.filter(p=>GEO[p]===undefined);
  for(let i=0;i<need.length;i+=90){
    try{
      const r=await fetch('https://api.postcodes.io/postcodes',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({postcodes:need.slice(i,i+90)})});
      const d=await r.json();
      (d.result||[]).forEach(x=>{ GEO[pcNorm(x.query)] = x.result ? {la:x.result.latitude,lo:x.result.longitude} : null; });
    }catch(e){}
  }
  // industrial sites often have TERMINATED postcodes that resolve to nothing
  // (DN16 1BP - British Steel). Fall back to the OUTCODE centroid so a run
  // still measures instead of silently showing nothing.
  for(const p of want){
    if(GEO[p]) continue;
    const oc=outcodeOf(p); if(!oc) continue;
    const key='OC:'+oc;
    if(GEO[key]===undefined){
      try{
        const r=await fetch('https://api.postcodes.io/outcodes/'+oc);
        const d=await r.json();
        GEO[key]= d.result ? {la:d.result.latitude, lo:d.result.longitude} : null;
      }catch(e){ GEO[key]=null; }
    }
    if(GEO[key]) GEO[p]=GEO[key];
  }
  try{ localStorage.setItem('r2geo',JSON.stringify(GEO)); }catch(e){}
}
let _mapRecs=[], _mapBatch=[], _mapHauliers=[];
async function renderMap(){
  mapInit(); if(!MAP) return;
  const pts=[];
  _mapRecs.forEach(r=>{ if(r.postcode) pts.push({pc:r.postcode, kind:'tracker',
    label:(r.orders||[]).join(' / ')+' — '+(r.site||'')+(r.delivery_date?(' · due '+r.delivery_date):'')}); });
  _mapBatch.forEach(e=>{ if(e.postcode) pts.push({pc:e.postcode, kind:'batch',
    label:(e.orders||[]).join(' / ')+' — '+((e.worksite||e.site)||'')+(e.date?(' · '+e.date):'')}); });
  DEPOTS.forEach(d=>pts.push({pc:d[1], kind:'depot', label:d[0], la:d[2], lo:d[3]}));
  (_mapHauliers||[]).forEach(h=>{ if(h.pc) pts.push({pc:h.pc, kind:'haulier',
    label:(h.tier==='tier1'?'FLEET · ':'')+h.name+(h.loc?' — '+h.loc:'')+(h.phone?'<br>'+h.phone:'')}); });
  const sig=JSON.stringify(pts.map(p=>[p.pc,p.kind]));
  if(sig===_mapSig) return;              // nothing changed - don't churn markers
  await geocode(pts.map(p=>p.pc));
  _mapSig=sig;
  MLAYER.clearLayers();
  const st={tracker:'#d40511', batch:'#d99e00', depot:'#1b1c1e', haulier:'#1da35e'};
  let shown=0;
  pts.forEach(p=>{
    const g=(p.la!==undefined) ? {la:p.la, lo:p.lo} : GEO[pcNorm(p.pc)];
    if(!g) return;
    shown++;
    L.circleMarker([g.la,g.lo],{radius:p.kind==='depot'?9:7, color:st[p.kind],
        weight:2, fillColor:st[p.kind], fillOpacity:.7})
     .addTo(MLAYER).bindPopup(esc(p.label)+'<br>'+esc(pcNorm(p.pc)));
  });
  document.getElementById('maphint').textContent = shown+' pinned';
}
// parsed delivery details - amber ones carry a one-click confirm that teaches it
const DFIELDS=[['date','Date'],['time','Time'],['offloading','Offload'],['artic_access','Artic'],
               ['rear_steer','Rear steer'],['vehicle','Vehicle'],['pts','PTS'],
               ['what3words','W3W'],['contact','Contact']];
function detVal(k,v){
  if(!v) return '';
  if(k==='time') return v.earliest ? (v.latest ? v.earliest+'-'+v.latest : v.earliest) : '';
  if(k==='contact') return [v.name,v.phone].filter(Boolean).join(' ');
  return v.value||'';
}
function detChips(r){
  const d=r.details; let out='';
  if(d){
    out = DFIELDS.map(function(p){
      const k=p[0], v=d[k], val=detVal(k,v);
      if(!val) return '';
      const amb = v && v.confidence==='amber';
      const id=encodeURIComponent(r.id||''), ev=encodeURIComponent(val);
      let s='<span class="dchip'+(amb?' amber':'')+'">'+esc(p[1])+': <b>'+esc(val)+'</b>';
      if(amb){
        s+=' <a href="#" title="Correct" onclick="confirmDetail(\\''+id+'\\',\\''+k+'\\',\\''+ev+'\\',1);return false">&#10003;</a>';
        s+='<a href="#" title="Fix" onclick="confirmDetail(\\''+id+'\\',\\''+k+'\\',\\''+ev+'\\',0);return false">&#9998;</a>';
      }
      return s+'</span>';
    }).join('');
  }
  const miss=r.missing||[];
  if(miss.length) out+='<span class="dmiss">still needed: '+esc(miss.join(', '))+'</span>';
  return out ? '<div class="tkdet">'+out+'</div>' : '';
}
// ---- order detail view: the job, the run on a map, and who to ring ----
let DMAP=null, DLAYER=null;
function milesBetween(a,b){
  if(!a||!b) return null;
  const R=3958.8, t=Math.PI/180;
  const dla=(b.la-a.la)*t, dlo=(b.lo-a.lo)*t;
  const h=Math.sin(dla/2)**2 + Math.cos(a.la*t)*Math.cos(b.la*t)*Math.sin(dlo/2)**2;
  return Math.round(2*R*Math.asin(Math.sqrt(h))*10)/10;
}
// what this job actually needs, from the order + whatever the customer told us
function needsFor(r){
  const need=[], d=r.details||{};
  const mats=((r.materials||'')+' '+(r.product_codes||[]).join(' ')).toLowerCase();
  // sleepers and bearers are not rails and not S&C - rigid or artic hiab
  if(/rail|s&c|switch|crossing/.test(mats)) need.push('rail / s&c');
  if(/sleeper|bearer/.test(mats) && !((r.details&&r.details.offloading&&r.details.offloading.value)||''))
    need.push(['rigid hiab','artic hiab']);
  // loose ballast is tipped, not bagged - it needs a tipper (see orders.js)
  // 0057/100500/001 = loose, /002 = 1 tonne bags (see orders.js)
  const looseCode=(r.product_codes||[]).some(c=>String(c).trim().endsWith('100500/001'));
  const loose = !!r.loose_ballast || (/ballast/.test(mats) && /loose/.test(mats)) || looseCode;
  if(loose) need.push('tipper');
  else if(/ballast|bag/.test(mats)) need.push('bags');
  const off=(d.offloading||{}).value||'';
  if(off==='MOFFETT') need.push('moffett');
  else if(off==='HIAB') need.push(((d.artic_access||{}).value==='no') ? 'rigid hiab' : 'artic hiab');
  if(((d.rear_steer||{}).value)==='yes') need.push('rear steer');
  if(((d.pts||{}).value)==='yes') need.push('pts');
  return need;
}
function recommendFor(r, geo){
  const need=needsFor(r);
  const from=pcNorm(r.collection_pc||''), to=pcNorm(r.postcode||'');
  const origin=geo[from]||geo[to];        // rank from the collection end when we have it
  const out=(_mapHauliers||[]).filter(h=>{
    const caps=(h.caps||[]).map(c=>c.toLowerCase());
    return need.every(n=>caps.some(c=>c.includes(n)));
  }).map(h=>{
    const g=geo[pcNorm(h.pc||'')];
    return Object.assign({}, h, {miles: origin&&g ? milesBetween(origin,g) : null});
  });
  // order of approach: OUR fleet (DHL NOC) -> tier 1 -> tier 2. Distance only
  // breaks ties inside a band, so a nearer tier-2 never jumps a tier-1.
  out.forEach(h=>{ h.rank = h.fleet ? 0 : (h.tier==='tier1' ? 1 : 2); });
  out.sort((a,b)=>a.rank-b.rank || (a.miles===null)-(b.miles===null) || (a.miles||9e9)-(b.miles||9e9));
  return {need, list: out.slice(0,6)};
}
async function viewOrder(encId){
  const id=decodeURIComponent(encId);
  const r=(_mapRecs||[]).find(x=>x.id===id);
  if(!r) return;
  document.getElementById('detail').classList.add('on');
  document.getElementById('dttl').textContent=(r.orders||[]).join(' / ');
  document.getElementById('dsub').textContent=[r.worksite,r.site,r.postcode].filter(Boolean).join(' · ');
  const d=r.details||{}, v=k=>detVal(k,d[k]);
  const rows=[['Materials',r.materials],['Delivery date',r.delivery_date],
    ['Time',v('time')],['Contact',r.to],['Site contact',v('contact')],
    ['Collection',[r.collection_site,r.collection_pc].filter(Boolean).join(' ')],
    ['Offloading',v('offloading')],['Artic access',v('artic_access')],
    ['Rear steer',v('rear_steer')],['PTS',v('pts')],['What3Words',v('what3words')]];
  document.getElementById('dkv').innerHTML=rows.filter(x=>x[1])
    .map(x=>'<dt>'+esc(x[0])+'</dt><dd>'+esc(x[1])+'</dd>').join('');
  document.getElementById('drecs').innerHTML='<span class="hint">finding hauliers…</span>';

  const pcs=[r.collection_pc,r.postcode].concat((_mapHauliers||[]).map(h=>h.pc)).filter(Boolean);
  await geocode(pcs);
  const cg=GEO[pcNorm(r.collection_pc||'')], dg=GEO[pcNorm(r.postcode||'')];
  const run=milesBetween(cg,dg);
  document.getElementById('drun').innerHTML = run!==null
    ? 'Run: <b>'+esc(r.collection_site||'collection')+'</b> &rarr; <b>'+esc(r.worksite||r.site||'site')+'</b> &nbsp;<b>'+run+' mi</b>'
    : (r.collection_pc ? '' : '<i>collection end not on this record (added for orders built from now on)</i>');

  // map: collection, delivery, the line between, and the top recommendations
  if(!DMAP){
    DMAP=L.map('dmap',{scrollWheelZoom:false}).setView([52.8,-1.4],6);
    L.tileLayer(TILES,{maxZoom:19,subdomains:'abcd',attribution:TILEATTR}).addTo(DMAP);
    DLAYER=L.layerGroup().addTo(DMAP);
  }
  DLAYER.clearLayers();
  const {need, list}=recommendFor(r, GEO);
  document.getElementById('dneed').textContent = need.length ? '· needs '+need.join(', ') : '';
  const pts=[];
  if(cg){ L.circleMarker([cg.la,cg.lo],{radius:8,color:'#1b1c1e',weight:2,fillColor:'#1b1c1e',fillOpacity:.75})
          .addTo(DLAYER).bindPopup('Collection<br>'+esc(r.collection_site||'')); pts.push([cg.la,cg.lo]); }
  if(dg){ L.circleMarker([dg.la,dg.lo],{radius:8,color:'#d40511',weight:2,fillColor:'#d40511',fillOpacity:.75})
          .addTo(DLAYER).bindPopup('Delivery<br>'+esc(r.worksite||r.site||'')); pts.push([dg.la,dg.lo]); }
  if(cg&&dg) L.polyline([[cg.la,cg.lo],[dg.la,dg.lo]],{color:'#8a8b88',weight:2,dashArray:'5,6'}).addTo(DLAYER);
  list.slice(0,4).forEach(h=>{ const g=GEO[pcNorm(h.pc||'')]; if(!g) return;
    L.circleMarker([g.la,g.lo],{radius:6,color:'#1da35e',weight:2,fillColor:'#1da35e',fillOpacity:.6})
     .addTo(DLAYER).bindPopup(esc(h.name)+'<br>'+esc(h.loc||'')+'<br>'+esc(h.phone||''));
    pts.push([g.la,g.lo]); });
  setTimeout(()=>{ DMAP.invalidateSize(); if(pts.length) DMAP.fitBounds(pts,{padding:[28,28]}); }, 60);

  const BADGE=['<span class="fleet">OUR FLEET</span>','<span class="t1">TIER 1</span>','<span class="t2">TIER 2</span>'];
  document.getElementById('drecs').innerHTML = list.length ? list.map(h=>
      '<div class="hrow"><span class="hmi">'+(h.miles!==null?h.miles+' mi':'—')+'</span>'
      +'<span class="hnm"><b>'+esc(h.name)+'</b>'+BADGE[h.rank]
      +'<br><span>'+esc(h.loc||'')+' · '+esc(h.phone||'')+(h.email?' · '+esc(h.email):'')+'</span></span></div>'
    ).join('')
    : '<span class="hint">No haulier in the list matches '+esc(need.join(', ')||'this job')+'.</span>';
}
function closeDetail(){ document.getElementById('detail').classList.remove('on'); }
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeDetail(); });

function confirmDetail(encId, field, encVal, asIs){
  let v=decodeURIComponent(encVal);
  if(!asIs){ const nv=prompt('Correct value for '+field+':', v); if(nv===null||!nv.trim()) return; v=nv.trim(); }
  post({action:'learn_detail', id:decodeURIComponent(encId), field:field, value:v});
  setTimeout(loadTracker, 1800);
}
async function loadTracker(){
  try{
    const d = await (await api('/api/tracker')).json();
    const recs = d.records || [];
    _mapRecs = recs; renderMap();
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
      const emailedCap = r.emailed_at ? '1st emailed '+esc(fmtDate(r.emailed_at)) : '';
      const due = r.delivery_date ? 'Due '+esc(r.delivery_date) : '';
      return '<div class="tkitem"><div class="tkrow'+(u?' urgent':'')+'">'
        + '<div class="tkmeta"><div class="ord">'+esc((r.orders||[]).join(' / '))+mat+(u?' <span class="pri">&le;3 DAYS</span>':'')+'</div>'
        + '<div class="sub">'+esc(r.to||'')+'</div>'
        + '<button class="btn mini" style="margin-top:.45rem" onclick="viewOrder(\\''+encodeURIComponent(r.id||'')+'\\')">View</button>'
        + '<button class="btn mini" style="margin-top:.45rem; margin-left:.3rem" onclick="bookedCall(\\''+encodeURIComponent(r.id||'')+'\\')">Booked via call</button>'
        + '</div>'
        + '<div class="pipewrap">'+pipe+'<div class="pipecap">'+emailedCap+'</div></div>'
        + '<div class="tktime'+(amber?' amber':'')+'"><b>'+esc(status)+'</b><br>'+due+'</div>'
        + '</div>' + detChips(r) + '</div>';
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

    def _is_ctms(self):
        # The work PC's bridge. Deliberately does NOT touch _agent_seen - the
        # pill that says "Home PC online" must not light up because the work
        # PC checked in.
        return bool(CTMS_KEY) and hmac.compare_digest(
            self._key().encode("utf-8", "replace"), CTMS_KEY.encode())

    def _agent_key_ok(self):
        # The home PC's key, WITHOUT refreshing "Home PC online": Claude using
        # ctms_remote.py says nothing about whether the home agent is running.
        return bool(AGENT_KEY) and hmac.compare_digest(
            self._key().encode("utf-8", "replace"), AGENT_KEY.encode())

    # ---- CTMS bridge channel (see _ctms above) ----
    def _ctms_get(self):
        from urllib.parse import parse_qs
        path, _, query = self.path.partition("?")
        q = parse_qs(query)
        if path == "/api/ctms/status":
            dash = self._is_dash()
            if not (dash or self._agent_key_ok()):
                return self._json(401, {"error": "auth"})
            now = time.time()
            with _lock:
                if dash and "watch=1" in query.split("&"):
                    # the CTMS page is open somewhere: keep pictures coming
                    if _ctms["watch_until"] < now:
                        _ctms_cv.notify_all()       # a held check-in hears it now, not in 10s
                    _ctms["watch_until"] = now + 10
                _ctms_sweep_locked()
                shot = _ctms["shot"]
                out = {
                    "online": _ctms_online(),
                    "seen_ago": int(now - _ctms["seen"]) if _ctms["seen"] else None,
                    "state": dict(_ctms["state"]),
                    "control": _ctms_control_locked(),
                    "queued": [{"id": c["id"], "action": c["action"], "name": c.get("name", ""),
                                "by": c.get("by", ""), "age": int(now - c["queued_at"])} for c in _ctms["queue"]],
                    "running": (dict({k: v for k, v in _ctms["running"].items() if k != "since"},
                                     age=int(now - _ctms["running"]["since"]))
                                if _ctms["running"] else None),
                    "results": [dict({k: v for k, v in r.items() if k != "ts"}, ago=int(now - r["ts"]))
                                for r in _ctms["results"]],
                    "shot": (dict({k: shot[k] for k in ("id", "w", "h", "url", "title")},
                                  ago=round(now - shot["ts"], 1)) if shot else None),
                    "captures": [{"name": n, "size": c["size"], "at": c["at"]}
                                 for n, c in reversed(list(_ctms["captures"].items()))],
                    "ttl": _CTMS_TTL,
                }
            return self._json(200, out)
        if path == "/api/ctms/result":
            # Claude waits here for the answer to one command - held open
            # until it lands, so an action and its result are one round trip
            if not (self._is_dash() or self._agent_key_ok()):
                return self._json(401, {"error": "auth"})
            try:
                cid = int((q.get("id") or [""])[0])
            except ValueError:
                return self._json(400, {"error": "which command? ?id=..."})
            try:
                wait = max(0.0, min(float((q.get("wait") or ["0"])[0]), _CTMS_MAX_WAIT))
            except ValueError:
                wait = 0.0
            deadline = time.time() + wait
            with _lock:
                while True:
                    _ctms_sweep_locked()
                    res = next((r for r in _ctms["results"] if r.get("id") == cid), None)
                    left = deadline - time.time()
                    if res or left <= 0:
                        break
                    _ctms_cv.wait(min(left, 5))
                out = {"done": bool(res), "online": _ctms_online()}
                if res:
                    out["result"] = {k: v for k, v in res.items() if k != "ts"}
                    held = _ctms["payloads"].get(cid)
                    if held:
                        out["payload"] = held["data"]
                else:
                    out["queued"] = any(c["id"] == cid for c in _ctms["queue"])
                    out["running"] = bool(_ctms["running"] and _ctms["running"]["id"] == cid)
            return self._json(200, out)
        if path == "/api/ctms/shot":
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            with _lock:
                shot = _ctms["shot"]
                out = (dict({k: v for k, v in shot.items() if k != "ts"},
                            ago=round(time.time() - shot["ts"], 1)) if shot else {})
            return self._json(200, out)
        if path == "/api/ctms/setup":
            # the dashboard's key only: the file carries the bridge's key
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            from urllib.parse import urlsplit
            desk = (q.get("desk") or [""])[0].rstrip("/")
            d = urlsplit(desk)
            # the address the work PC will call is this dashboard's own, as the
            # browser asking for the file reached it - never one passed in from elsewhere
            hosts = {(self.headers.get(h) or "").lower() for h in ("Host", "X-Forwarded-Host")} - {""}
            if d.scheme not in ("http", "https") or d.netloc.lower() not in hosts:
                return self._json(400, {"error": "the setup is made for this dashboard's own address"})
            body = _ctms_setup_file(desk, (q.get("allow") or ["1"])[0] == "1",
                                    (q.get("autostart") or ["1"])[0] == "1")
            if body is None:
                return self._json(500, {"error": "the setup template is missing from this deployment"})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="CTMS bridge setup.cmd"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return None
        if path == "/api/ctms/captures":
            # the home agent collects these, so the walkthrough lands on the
            # home PC with nobody zipping or emailing anything
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            with _lock:
                lst = [{"name": n, "size": c["size"], "at": c["at"]}
                       for n, c in reversed(list(_ctms["captures"].items()))]
            return self._json(200, {"captures": lst})
        if path == "/api/ctms/capture":
            if not (self._is_dash() or self._is_agent()):
                return self._json(401, {"error": "auth"})
            name = (q.get("name") or [""])[0]
            with _lock:
                c = _ctms["captures"].get(name)
            if not c:
                return self._json(404, {"error": "gone"})
            return self._json(200, {"name": name, "data": c["data"]})
        return self._json(404, {"error": "not found"})

    def _ctms_post(self, data, length):
        path = self.path.partition("?")[0]
        if not isinstance(data, dict):
            data = {}
        # ---- from the dashboard, or from Claude on the home PC ----
        if path == "/api/ctms/command":
            dash = self._is_dash()
            if not (dash or self._agent_key_ok()):
                return self._json(401, {"error": "auth"})
            action = str(data.get("action") or "")
            if action not in CTMS_ACTIONS:
                return self._json(400, {"error": f"the CTMS bridge does not do '{action[:40]}'"})
            refused = None
            with _lock:
                _ctms_sweep_locked()
                if action in CTMS_DRIVE and not _ctms_armed():
                    refused = ("The haulage desk can't run CTMS right now: Look mum, no hands mode is off on the "
                               "dashboard's CTMS page. Only Delali can turn it on, from there.", "control")
                elif action in CTMS_DRIVE and _ctms["state"].get("control") is False:
                    refused = ("The work PC is set to look only. To let the haulage desk run CTMS, run this on the "
                               "work PC:  python ctms_bridge.py --allow-control", "allow")
                else:
                    # one picture request in the queue is plenty
                    cmd = next((c for c in _ctms["queue"] if action == "look" and c["action"] == "look"), None)
                    if cmd is None:
                        _ctms["next_id"] += 1
                        cmd = dict(_ctms_args(action, data), id=_ctms["next_id"], action=action,
                                   by="dashboard" if dash else "home PC", queued_at=time.time())
                        _ctms["queue"].append(cmd)
                        _ctms["asked"][cmd["id"]] = cmd["by"]
                        for old in list(_ctms["asked"])[:-100]:
                            _ctms["asked"].pop(old, None)
                        _ctms_cv.notify_all()
                    online = _ctms_online()
            if refused:
                return self._json(409, {"error": refused[0], "need": refused[1]})
            return self._json(200, {"ok": True, "id": cmd["id"], "online": online})
        if path == "/api/ctms/control":
            # "Look mum, no hands" (once "Claude can act") - the dashboard's switch, and nobody else's
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            on = bool(data.get("on"))
            try:
                minutes = max(5, min(int(data.get("minutes") or 60), 480))
            except (TypeError, ValueError):
                minutes = 60
            with _lock:
                _ctms["control_touched"] = True
                if on:
                    _ctms["control_until"] = time.time() + minutes * 60
                    _ctms_note_locked(f"Look mum, no hands mode switched on for {minutes} min.")
                else:
                    _ctms["control_until"] = 0.0
                    _ctms_cancel_locked("Cancelled - Look mum, no hands mode was switched off.", only=CTMS_DRIVE)
                    _ctms_note_locked("Look mum, no hands mode switched off.")
                _ctms_cv.notify_all()
                out = {"ok": True, "control": _ctms_control_locked()}
            return self._json(200, out)
        if path == "/api/ctms/stop":
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            with _lock:
                _ctms_cancel_locked("Cancelled - Stop was pressed.")
                _ctms["stop"] = True
                if _ctms_armed():
                    _ctms_note_locked("Stop pressed - Look mum, no hands mode switched off.")
                _ctms["control_until"] = 0.0
                _ctms["control_touched"] = True
                _ctms_cv.notify_all()
            return self._json(200, {"ok": True})
        # ---- from the work PC's bridge ----
        if not self._is_ctms():
            return self._json(401, {"error": "auth"})
        if path == "/api/ctms/hello":
            # the setup asking "can this PC reach the dashboard?" - nothing
            # handed out, nothing marked as running
            return self._json(200, {"ok": True})
        if path == "/api/ctms/poll":
            if length > 200_000:
                return self._json(413, {"error": "check-in too large"})
            try:
                wait = max(0.0, min(float(data.get("wait") or 0), _CTMS_MAX_WAIT))
            except (TypeError, ValueError):
                wait = 0.0
            watched, armed = bool(data.get("watched")), bool(data.get("armed"))
            with _lock:
                _ctms["seen"] = time.time()
                if data.get("ticket") and not _ctms["control_touched"] and not _ctms_armed():
                    until = _ctms_ticket_until(data["ticket"])        # restarted while it was on (see _ctms_ticket)
                    if until > time.time():
                        _ctms["control_until"], _ctms["control_touched"] = float(until), True
                        _ctms_note_locked("Look mum, no hands mode kept on through the dashboard restarting - "
                                          f"{max(1, round((until - time.time()) / 60))} min left, as it was.")
                _ctms_take_state_locked(data.get("state"))
                _ctms_sweep_locked()
                # Held open until there is work, or something the bridge has
                # to know changes (pictures wanted, the switch flipped).
                deadline = time.time() + wait
                _ctms["polling"] += 1
                try:
                    while not _ctms["queue"] and not _ctms["stop"]:
                        now = time.time()
                        if ((now < _ctms["watch_until"]) != watched or _ctms_armed() != armed
                                or now >= deadline):
                            break
                        _ctms_cv.wait(min(deadline - now, 5))
                        _ctms_sweep_locked()
                finally:
                    _ctms["polling"] -= 1
                _ctms["seen"] = time.time()
                cmd = _ctms["queue"].pop(0) if _ctms["queue"] else None
                # The bridge does one thing at a time, so a check-in means the
                # last thing it was handed is over, answered or not.
                _ctms["running"] = ({"id": cmd["id"], "action": cmd["action"], "name": cmd.get("name", ""),
                                     "by": cmd.get("by", ""), "since": time.time()} if cmd else None)
                stop, _ctms["stop"] = _ctms["stop"], False
                watch = time.time() < _ctms["watch_until"]
                control = _ctms_armed()
                ticket = _ctms_ticket(_ctms["control_until"]) if control and DASH_KEY else ""
                # A restart empties this memory; the bridge only sends its bulky
                # parts when they change, so tell it to send them again.
                resync = not _ctms["state"].get("screens")
            if cmd:
                cmd = {k: v for k, v in cmd.items() if k != "queued_at"}
            return self._json(200, {"cmd": cmd, "watch": watch, "stop": stop, "resync": resync,
                                    "control": control, "ticket": ticket, "long": True})
        if path == "/api/ctms/shot":
            if length > 6_000_000:
                return self._json(413, {"error": "picture too large"})
            need = False
            with _lock:
                _ctms["seen"] = time.time()
                if data.get("same"):
                    if _ctms["shot"]:
                        _ctms["shot"]["ts"] = time.time()     # unchanged screen - just fresher
                    else:
                        # "same as before" - but a restart emptied before. Ask for
                        # the whole picture, or the live view waits until the
                        # CTMS screen happens to change.
                        need = True
                elif data.get("data"):
                    _ctms["next_shot"] += 1
                    try:
                        w, h = int(data.get("w") or 0), int(data.get("h") or 0)
                    except (TypeError, ValueError):
                        w = h = 0
                    _ctms["shot"] = {"id": _ctms["next_shot"], "ts": time.time(),
                                     "data": str(data["data"]), "w": w, "h": h,
                                     "url": str(data.get("url") or "")[:500],
                                     "title": str(data.get("title") or "")[:200],
                                     # CTMS's own window comes as PNG; a browser tab as JPEG
                                     "mime": "image/png" if data.get("mime") == "image/png" else "image/jpeg"}
            return self._json(200, {"ok": True, "need": True} if need else {"ok": True})
        if path == "/api/ctms/result":
            if length > 12_000_000:
                return self._json(413, {"error": "answer too large"})
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else None
            with _lock:
                _ctms["seen"] = time.time()
                cid = data.get("id")
                if _ctms["running"] and _ctms["running"]["id"] == cid:
                    _ctms["running"] = None
                _ctms_result_locked({"id": cid, "action": str(data.get("action") or "")[:20],
                                     "name": str(data.get("name") or "")[:60], "ok": bool(data.get("ok")),
                                     "detail": str(data.get("detail") or "")[:1000],
                                     "by": _ctms["asked"].get(cid, ""),
                                     "pic": bool(payload and payload.get("img"))})
                if payload is not None and isinstance(cid, int):
                    held = _ctms["payloads"]
                    held.pop(cid, None)
                    held[cid] = {"data": payload, "size": length}
                    while len(held) > 1 and (len(held) > _CTMS_MAX_PAYLOADS or
                                             sum(h["size"] for h in held.values()) > _CTMS_MAX_PAYLOAD_BYTES):
                        held.pop(next(iter(held)))
                _ctms_cv.notify_all()
            return self._json(200, {"ok": True})
        if path == "/api/ctms/capture":
            name = str(data.get("name") or "")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}\.zip", name) or not data.get("data"):
                return self._json(400, {"error": "a capture needs a .zip name and data"})
            with _lock:
                _ctms["seen"] = time.time()
                caps = _ctms["captures"]
                caps.pop(name, None)
                try:
                    size = int(data.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                caps[name] = {"data": str(data["data"]), "size": size,
                              "at": datetime.now().strftime("%d/%m %H:%M")}
                while len(caps) > 1 and (len(caps) > _CTMS_MAX_CAPTURES or
                                         sum(len(c["data"]) for c in caps.values()) > _CTMS_MAX_CAPTURE_B64):
                    caps.pop(next(iter(caps)))
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = _index_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path in _PWA_FILES:
            body = _pwa_asset(self.path)
            if body is None:
                return self._json(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", _PWA_FILES[self.path])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")   # SW/manifest must update on deploy
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
                out["ctms_online"] = _ctms_online()
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
            # ctms_setup: the work PC's setup template made it into this build
            # (it is a COPY line in both Dockerfiles - easy to lose)
            self._json(200, {"ok": True, "files": True, "ctms_setup": os.path.isfile(_SETUP_TEMPLATE)})
        elif self.path.startswith("/api/ctms/"):
            self._ctms_get()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global _tracker, _waitlist, _upload
        length = int(self.headers.get("Content-Length", 0))
        # Everything legitimate is far below this (the biggest are an outbox
        # file and a CTMS capture, a few MB each). Without a ceiling any
        # client, signed in or not, could make this read a body of any size
        # into memory before the auth check below ever ran.
        if length > 40_000_000:
            return self._json(413, {"error": "too large"})
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        if self.path.startswith("/api/ctms/"):
            self._ctms_post(data, length)
        elif self.path == "/api/command":
            if not self._is_dash():
                return self._json(401, {"error": "auth"})
            with _lock:
                _queue.append({"action": data.get("action", "preview"), "order": data.get("order", ""),
                               "email": data.get("email"), "sel": data.get("sel"),
                               "mode": data.get("mode"), "week": data.get("week"),
                               "sites": data.get("sites"), "data": data.get("data"),
                               # the Auto follow-ups switch's on/off - it was
                               # left out, so every click arrived as "off"
                               "on": data.get("on"),
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
            if not (name and data.get("data")):
                # Used to answer 200 {"ok": True} here regardless - so a body
                # that arrived empty or failed to parse (data = {} in the
                # handler above) was reported to the browser as a successful
                # upload. The browser then fired form_upload at the agent,
                # which pulled an empty slot and said "No form received" - the
                # failure surfacing two hops from where it happened, blamed on
                # the form. Say it here, where it is actually known.
                return self._json(400, {"error": "upload had no name or data"})
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
    ui = f"React build ({_WEB_INDEX_PATH})" if _WEB_INDEX is not None else "inline fallback page"
    print(f"Cloud control plane on {HOST}:{PORT} — serving {ui}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
