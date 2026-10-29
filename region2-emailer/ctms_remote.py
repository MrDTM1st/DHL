"""
CTMS on the work PC, from the home PC - how Claude sees it and works it.

    python ctms_remote.py status                  is the bridge there, may Claude act
    python ctms_remote.py see [--all]             picture with numbers + the numbered list + words
    python ctms_remote.py text                    every word on the screen
    python ctms_remote.py find WORDS              numbered things and lines that mention WORDS
    python ctms_remote.py click N                 click a numbered thing   [--double] [--commit]
    python ctms_remote.py click --at X,Y          ...or a point on the latest picture   [--right]
    python ctms_remote.py type N "text"           replace what is in N     [--enter] [--append] [--commit]
    python ctms_remote.py key Tab|Enter|Escape|ctrl+a|...                  [--commit]
    python ctms_remote.py select N "option"       choose in a dropdown list
    python ctms_remote.py scroll down|up|left|right [--amount PX] [--in N]  |  scroll to N
    python ctms_remote.py hover N
    python ctms_remote.py goto ADDRESS | back | forward | reload           [--commit]
    python ctms_remote.py dialog accept|dismiss [--text T]                 [--commit]
    python ctms_remote.py wait SECONDS  |  wait --for "Saved" [--timeout S]
    python ctms_remote.py tabs  |  tab N
    python ctms_remote.py fields [--all]          CTMS's fields by name, through Java's Access Bridge -
                                                  works with CTMS behind other windows or minimised
    python ctms_remote.py fields-setup            the work PC fetches the 32-bit Python that fields needs
    python ctms_remote.py drag --from X,Y --to X,Y   move a Forms window aside by its title bar

The CTMS note run (CTMS's own window; each answers with a picture to check):
    python ctms_remote.py orders-page             C-TMS Modules > Order Management > Orders
    python ctms_remote.py order-find 1234567      the order's lines (then double-click -1-1's Status cell)
    python ctms_remote.py order-note " - Emailed DO 28/10"   at the END of Special Instructions
    python ctms_remote.py order-save | order-close
    python ctms_notes.py                          which notes are owed; ctms_notes.py done REF "NOTE"

An upload into CTMS, and the weight after it (CTMS's import reads no weight):
    python ctms_remote.py uploads [TEXT]          the dashboard's CSVs, newest first - the exact name
    python ctms_remote.py import-open             Administration > File Interfaces > Imports, NRHEAVY
    python ctms_remote.py import-file PATH        the CSV's full path on the work PC into Input file
    python ctms_remote.py import-go               Import - then its Yes / Yes / OK, read off the picture
    python ctms_remote.py import-close            the Import card's Close
    python upload_weights.py CSV                  each order's weight in the CSV, or why there isn't one
    python ctms_remote.py order-weight 12         the open order's item weight, typed (check the picture)
    python ctms_remote.py order-weight-save       item Save + Exit, then the order's Save; then order-close
    python ctms_remote.py update [--branch B] [--all]    the work PC pulls new code from GitHub

N is a number from the latest picture. Every action answers with a fresh one,
so the numbers to use next are always the ones just printed.

Anything that would save, book, submit, confirm, send or delete is refused
unless --commit is given, and --commit is only ever given after Delali has
said go in the chat. Looking needs nothing switched on; acting needs "Claude
can act" switched on on the dashboard's CTMS page - which only he can do, and
which this script cannot.

Everything is kept: ctms_remote/latest.jpg is the newest picture, and
ctms_remote/trace/<day>/ keeps every step - the picture, what was on the
screen, what was asked and what happened. That is the record the booking
automation gets written from.

Reads the dashboard's address and the home PC's key from cloud.json, like the
cloud agent (CTMS_DESK_URL / CTMS_DESK_KEY override both).

Exit codes: 0 done, 3 not done (refused, or needs his go-ahead), 4 the work
PC did not answer, 5 acting is switched off, 1 anything else.
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ctms_remote")          # gitignored
STATE = os.path.join(OUT, "state.json")          # the latest picture's snap id
NEEDS_SNAP = ("click", "type", "select", "scroll", "hover")


class Stop(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def _desk():
    url, key = os.environ.get("CTMS_DESK_URL"), os.environ.get("CTMS_DESK_KEY")
    if not (url and key):
        try:
            with open(os.path.join(HERE, "cloud.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            raise Stop("No cloud.json next to this script, and no CTMS_DESK_URL / CTMS_DESK_KEY set - "
                       "run it from the home PC's region2-emailer folder.")
        url, key = url or cfg.get("url"), key or cfg.get("agent_key")
    if not (url and key):
        raise Stop("cloud.json has no url / agent_key.")
    return url.rstrip("/"), key


BASE, KEY = "", ""


def http(method, path, body=None, timeout=45):
    host = (urlsplit(BASE).hostname or "").lower()
    handlers = [urllib.request.ProxyHandler({})] if host in ("127.0.0.1", "localhost") else []
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Auth": KEY, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Stop(f"Could not reach the dashboard at {BASE}: {getattr(e, 'reason', e)}", 4)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(p):
    os.makedirs(OUT, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"snap": p.get("snap"), "ppc": p.get("ppc"), "url": p.get("url"),
                   "kind": p.get("kind"), "img_w": p.get("img_w"), "img_h": p.get("img_h"),
                   "at": datetime.now().isoformat(timespec="seconds")}, f)


def ask(action, wait_total=90, **args):
    """Send one command to the work PC and wait for its answer: (result, payload)."""
    body = {k: v for k, v in args.items() if v is not None}
    body["action"] = action
    if action in NEEDS_SNAP and ("ref" in body or "at" in body):
        body["snap"] = load_state().get("snap") or ""
    code, r = http("POST", "/api/ctms/command", body)
    if code == 401:
        raise Stop("The dashboard did not accept the home PC's key from cloud.json.")
    if code == 404:
        raise Stop("This dashboard has no CTMS channel yet - it needs redeploying.")
    if code == 409:
        raise Stop(r.get("error") or "Acting is switched off.", 5)
    if code != 200:
        raise Stop(r.get("error") or f"The dashboard answered HTTP {code}.")
    cid = r["id"]
    if not r.get("online"):
        print("(the work PC bridge is offline right now - it gets 60s to check in and pick this up)")
    deadline = time.time() + wait_total
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise Stop("No answer from the work PC in time. It may still have done it - run see "
                       "before trying the same thing again.", 4)
        code, w = http("GET", f"/api/ctms/result?id={cid}&wait={max(1, min(20, int(left)))}", timeout=45)
        if code != 200:
            raise Stop(w.get("error") or f"The dashboard answered HTTP {code}.")
        if w.get("done"):
            return w["result"], w.get("payload")


# ---- what gets printed ---------------------------------------------------------
def fmt_el(e):
    s = f"[{e['n']}] {e.get('r', '?')}"
    if e.get("t"):
        s += f"({e['t']})"
    if e.get("l"):
        s += f' "{e["l"]}"'
    elif e.get("id"):
        s += f" #{e['id']}"
    elif e.get("nm"):
        s += f" [name={e['nm']}]"
    if "v" in e:
        s += f' = "{e["v"]}"'
    if "on" in e:
        s += " [x]" if e["on"] else " [ ]"
    if e.get("o"):
        s += "  {" + " | ".join(e["o"][:12]) + (" | ..." if len(e["o"]) > 12 else "") + "}"
    flags = []
    if e.get("c"):
        flags.append("SAVES/SUBMITS - needs his go-ahead")
    if e.get("pw"):
        flags.append("PASSWORD - never typed into")
    for k, word in (("dis", "disabled"), ("ro", "read-only"), ("req", "required")):
        if e.get(k):
            flags.append(word)
    if e.get("f"):
        flags.append("in frame " + e["f"])
    if e.get("off"):
        flags.append(e["off"] + " - not in view")
    href = e.get("href") or ""
    if href and not href.lower().startswith("javascript") and href != "#":
        flags.append("-> " + href[:70])
    return s + ("  (" + "; ".join(flags) + ")" if flags else "")


def _squeeze(text):
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in (text or "").splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def _ext(p):
    return ".png" if (p or {}).get("mime") == "image/png" else ".jpg"


def save_picture(p, action):
    if not p.get("img"):
        return None
    raw = base64.b64decode(p["img"])
    os.makedirs(OUT, exist_ok=True)
    latest = os.path.join(OUT, "latest" + _ext(p))
    with open(latest, "wb") as f:
        f.write(raw)
    return latest


def trace(action, args, result, payload):
    """Keep the step: the picture, the screen, what was asked, what happened."""
    try:
        now = datetime.now()
        d = os.path.join(OUT, "trace", now.strftime("%Y-%m-%d"))
        os.makedirs(d, exist_ok=True)
        stem = os.path.join(d, now.strftime("%H%M%S") + f"-{action}")
        if payload and payload.get("img"):
            with open(stem + _ext(payload), "wb") as f:
                f.write(base64.b64decode(payload["img"]))
        rec = {"at": now.isoformat(timespec="seconds"), "action": action, "args": args, "result": result,
               "screen": {k: v for k, v in (payload or {}).items() if k != "img"}}
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
    except Exception as e:
        print(f"(could not keep this step in the trace: {e})")


def print_screen(p, action, full=False, words=2500):
    if p.get("kind") == "window":
        # CTMS's own window in his Edge: a picture, read by eye - no numbered list.
        # Saved so a following click --at X,Y knows the picture its X,Y are from.
        save_state(p)
        pic = save_picture(p, action)
        w = p.get("window") or {}
        print(f"\nCTMS's window: {p.get('title') or '?'}  ({w.get('process') or w.get('kind')}, "
              f"{w.get('java', 0)} Java part(s){', in front' if w.get('foreground') else ', behind other windows'})")
        if pic:
            print(f"Picture: {pic}  ({p.get('img_w')}x{p.get('img_h')}, taken {p.get('how')})")
        print(p.get("note") or "")
        return
    if p.get("dialog"):
        d = p["dialog"]
        print(f"\nDIALOG BOX OPEN ({d.get('type')}): \"{d.get('message')}\"")
        print("  -> dialog dismiss, or dialog accept (OK on a confirm needs his go-ahead: --commit)")
    if p.get("note") and not p.get("snap"):
        print(p["note"])
    if not p.get("snap"):
        if p.get("picture_error"):
            print("No picture: " + p["picture_error"])
        return
    save_state(p)
    print(f"\n{p.get('title') or '(no title)'}  |  {p.get('url', '')}")
    pic = save_picture(p, action)
    if pic:
        print(f"Picture: {pic}  ({p.get('img_w')}x{p.get('img_h')}, numbers drawn on)  [{p['snap']}]")
    elif p.get("picture_error"):
        print("No picture: " + p["picture_error"])
    if p.get("sign_in"):
        print("SIGN-IN PAGE: a password box is showing. Delali signs in himself - nothing is "
              "clicked or typed here.")
    if p.get("focus"):
        print("Cursor in: " + p["focus"])
    els = p.get("elements") or []
    inview = [e for e in els if not e.get("off")]
    print(f"\nOn screen ({len(inview)}):")
    for e in (els if full else inview):
        print("  " + fmt_el(e))
    off = [e for e in els if e.get("off")]
    if off and not full:
        counts = {}
        for e in off:
            counts[e["off"]] = counts.get(e["off"], 0) + 1
        print("Not in view: " + ", ".join(f"{n} {w}" for w, n in counts.items())
              + " - scroll, or use the number (it scrolls by itself); see --all lists them.")
    if (p.get("total") or 0) > len(els):
        print(f"({p['total'] - len(els)} more clickable things not listed - the page is crowded)")
    for o in p.get("opaque") or []:
        print(f"A frame the bridge cannot read: {o['frame']} at {o['x']},{o['y']} ({o['w']}x{o['h']} "
              f"page px) - only click --at works inside it.")
    tabs = p.get("tabs") or []
    if len(tabs) > 1:
        print("Tabs: " + "  |  ".join(f"{t['n']}{' (this one)' if t.get('current') else ''}: "
                                      f"{t.get('title', '')[:40]}" for t in tabs))
    text = _squeeze(p.get("text"))
    if text and words:
        print("\nWords on the screen" + (" (start of)" if len(text) > words else "") + ":")
        print(text[:words])


def print_probe(p):
    wins = p.get("windows") or []
    print("\nWindows CTMS could be in:" if wins else "\nNo window CTMS could be in - is CTMS open in Edge?")
    for w in wins:
        ie = (f"  IE content: {w.get('ie')} ({'on show' if w.get('ie_showing') else 'tab not selected'}),"
              if w.get("kind") in ("edge", "ie") else "")
        print(f"  {w.get('title')[:70] or '(no title)'}  [{w.get('kind')}, {w.get('process') or w.get('class')}]"
              f"{ie} Java parts: {w.get('java')} {w.get('java_classes')}"
              + ("  MINIMISED" if w.get("minimized") else "") + ("  in front" if w.get("foreground") else ""))
    j = p.get("java") or {}
    print(f"\nJava on the work PC: {len(j.get('installs') or [])} install(s)")
    for i in j.get("installs") or []:
        print(f"  {i.get('version')} ({i.get('bits')}-bit) {i.get('home')}  jabswitch: "
              f"{'yes' if i.get('jabswitch') else 'no'}; bridge files: {', '.join(i.get('bridge_dlls') or []) or 'none'}"
              + ("; switched on for everyone" if i.get("jre_switch") else ""))
    print(f"Windows' own Access Bridge files: {j.get('system_dlls')}")
    print(f"Access Bridge switched on for this user: {'yes' if j.get('user_switch') else 'no'}")
    print(f"Processes: {p.get('processes')}")
    print(f"Access Bridge, asked live: {json.dumps(p.get('access_bridge') or {})}")


def fmt_field(e):
    s = f"[{e.get('n')}] {e.get('r', '?')}"
    if e.get("nm"):
        s += f' "{e["nm"]}"'
    if e.get("secret"):
        s += " = (withheld)"
    elif "v" in e:
        s += f" = {e['v']!r}"
    if e.get("st"):
        s += f"  ({', '.join(e['st'])})"
    return s


def print_fields(p, full=False):
    """CTMS's fields as the Access Bridge read them - and kept whole in ctms_remote/latest_fields.json."""
    els = p.get("elements") or []
    wins = {w.get("w"): w for w in p.get("windows") or []}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "latest_fields.json"), "w", encoding="utf-8") as f:
        json.dump(p, f, indent=1)
    print(f"\n{len(els)} thing(s) in {len(wins)} Java window(s) - Java {p.get('java') or '?'}, "
          f"read in {p.get('took', '?')}s" + ("  CUT SHORT" if p.get("cut") else ""))
    cur = next((e for e in els if e.get("n") == p.get("focus")), None)
    print("Cursor: " + (fmt_field(cur) if cur else "no field reports it (CTMS is not the active window?)"))
    shown = els if full else els[:300]
    w = None
    for e in shown:
        if e.get("w") != w:
            w = e.get("w")
            win = wins.get(w) or {}
            print(f"-- window {w}: {win.get('title') or '(no title)'} [{win.get('class', '')}]")
        print("  " + "  " * min(int(e.get("lv") or 0), 10) + fmt_field(e))
    if len(els) > len(shown):
        print(f"  ... {len(els) - len(shown)} more - fields --all, or ctms_remote/latest_fields.json")


def report(action, args, result, payload, full=False, words=2500):
    trace(action, args, result, payload)
    print(("DONE  " if result.get("ok") else "NOT DONE  ") + str(result.get("detail") or ""))
    if payload and payload.get("needs_commit"):
        print("  -> ask Delali first. If he says go, run the same command again with --commit.")
    if payload:
        if payload.get("tabs") and not payload.get("snap") and action == "tabs":
            for t in payload["tabs"]:
                print(f"  {t['n']}{' *' if t.get('current') else '  '} {t.get('title', '')}  |  {t.get('url', '')}")
        print_screen(payload, action, full=full, words=words)
    return 0 if result.get("ok") else 3


# ---- the commands ------------------------------------------------------------------
def cmd_uploads(text=""):
    """The dashboard's CSVs, newest first - the exact name of the one to import. The
    work PC's browser saves a download under that same name in its Downloads folder."""
    code, body = http("GET", "/api/files")
    if code == 401:
        raise Stop("The dashboard did not accept the home PC's key from cloud.json.")
    if code != 200:
        raise Stop(f"The dashboard would not list its files ({code}: {body.get('error', '')}).")
    want = str(text or "").lower()
    rows = [f for f in body.get("files") or []
            if str(f.get("name", "")).lower().endswith(".csv") and want in str(f.get("name", "")).lower()]
    for f in rows[:20]:
        print(f"{f.get('at', '?'):>11}  {f.get('size', '?'):>7}  {f['name']}")
    print(f"({len(rows)} CSV{'' if len(rows) == 1 else 's'}{' matching ' + repr(text) if text else ''})")
    return 0


def cmd_status(_a):
    code, st = http("GET", "/api/ctms/status")
    if code == 401:
        raise Stop("The dashboard did not accept the home PC's key from cloud.json.")
    if code == 404:
        raise Stop("This dashboard has no CTMS channel yet - it needs redeploying.")
    s, c = st.get("state") or {}, st.get("control") or {}
    if not st.get("online"):
        seen = st.get("seen_ago")
        print("Work PC bridge: OFFLINE" + (f" (last seen {seen}s ago)" if seen is not None else " (never seen)"))
    else:
        print(f"Work PC bridge: online - {s.get('machine', '?')}, {s.get('browser', '?')}")
    win = s.get("window") or {}
    if s.get("view") == "window":
        print(f"CTMS: its own window{' in Edge' if win.get('kind') == 'edge' else ''} - {win.get('title') or '?'}"
              + (" (MINIMISED - cannot be pictured)" if win.get("minimized") else "")
              + (", in front" if win.get("foreground") else ", behind other windows"))
    else:
        print("CTMS tab: " + (f"{s.get('tab_title') or '?'}  |  {s.get('tab_url', '')}" if s.get("attached")
                              else (s.get("error") or "none attached")))
    if s.get("dialog"):
        print("DIALOG BOX OPEN: " + s["dialog"])
    allowed = s.get("control")
    if c.get("armed"):
        print(f"Claude can act: ON - {c['left'] // 60} min {c['left'] % 60}s left"
              + ("" if allowed is not False else " (but the work PC is observe only)"))
    else:
        print("Claude can act: off (look only) - Delali switches it on from the dashboard's CTMS page")
    if allowed is False:
        print("Work PC setting: observe only (python ctms_bridge.py --allow-control on the work PC to allow acting)")
    print("Bridge code: " + (s.get("code") or "not known until its first remote update")
          + (f", v{s['version']}" if s.get("version") else "")
          + (f", since {s['code_at']}" if s.get("code_at") else ""))
    if s.get("rolled_back"):
        print("ROLLED BACK: " + s["rolled_back"])
    if st.get("running"):
        r = st["running"]
        print(f"Doing now: {r['action']} ({r.get('age', 0)}s)")
    for r in (st.get("results") or [])[:6]:
        who = {"home PC": "Claude", "dashboard": "dash"}.get(r.get("by"), r.get("by") or "")
        print(f"  {r.get('at')} {'ok ' if r.get('ok') else 'NO '} {who:6} {r.get('action', ''):8} {str(r.get('detail'))[:110]}")
    return 0


def _ref(v):
    try:
        return int(str(v).strip("[]"))
    except ValueError:
        raise Stop(f"'{v}' is not a number from the picture.")


def _xy(text, flag):
    try:
        x, y = (float(v) for v in str(text).split(","))
        return x, y
    except ValueError:
        raise Stop(f"{flag} takes X,Y - a point on the latest picture, e.g. {flag} 640,300")


def _window_point(x, y):
    """A point read off the latest picture of CTMS's own window, as the fraction the
    bridge takes - so it lands right even if the window has moved or resized since."""
    st = load_state()
    iw, ih = st.get("img_w") or 0, st.get("img_h") or 0
    if st.get("kind") != "window" or not (iw and ih):
        raise Stop("Take a picture of CTMS's window first (see), then aim at a point on it.")
    return [max(0.0, min(1.0, x / iw)), max(0.0, min(1.0, y / ih))]


# ---- the CTMS note run, one fixed step-sequence at a time ---------------------------
# Where things are on CTMS's screens, in pixels of the work PC's picture. Forms lays its
# windows out at fixed positions from the top left, so these hold until someone moves a
# window - and every sequence answers with a picture, so a moved one is seen before the
# next sequence types anything. Calibrated on the live screens 29/10.
CTMS_AT = {
    "menu_modules": (121, 37), "menu_order_mgmt": (135, 63), "menu_orders": (240, 67),
    "search_clear": (626, 226), "search_custref": (728, 123), "search_refresh": (742, 226),
    "si_end": (1000, 639), "order_save": (337, 733), "order_close": (424, 733),
    # Administration > File Interfaces > Imports, and the Import card (File Type's list
    # opens downward from AUTO, so NRHEAVY_Order_Import is its second line)
    "menu_admin": (230, 37), "menu_file_ifaces": (231, 159), "menu_imports": (362, 163),
    "imp_type_arrow": (575, 226), "imp_type_nrheavy": (217, 251), "imp_file": (357, 267),
    "imp_import": (405, 438), "imp_close": (1030, 139),
    # an open order's Order Items tab and its "Create, Edit or Delete Order Item" box
    "items_tab": (136, 187), "item_edit": (200, 525), "item_weight": (182, 405),
    "item_save": (182, 499), "item_exit": (663, 499),
}


def _at(name):
    return {"at_px": CTMS_AT[name]}


def _search_ref(order):
    """What goes in Order Search's Customer Ref box, ahead of the %. An NR order is
    searched by its 7-digit base so every line comes back (1234567-1-1 -> 1234567).
    Any other ref - an ad hoc's AH01/01/2026/AB-CD, a DTS's - goes in whole: cut at
    its first dash, it would bring back every other job sharing the front of it."""
    order = str(order).strip()
    m = re.fullmatch(r"(\d{7})(?:-\d+)*", order)
    return m.group(1) if m else order


RUN_STEPS = {
    # Order Management > Orders: the Order Summary page with its Order Search card
    "orders-page": lambda a: [("click", _at("menu_modules")), ("click", _at("menu_order_mgmt")),
                              ("click", _at("menu_orders")), ("wait", {"seconds": 8})],
    # the order's lines, by customer ref with a % (all its lines come back - NOT in line
    # order, so pick the -1-1 row off the picture and double-click its Status cell).
    # The card's Clear empties the results, not the Customer Ref box - so select the box's
    # text (Home, then Shift+End) and let the new ref replace it, rather than appending.
    "order-find": lambda a: [("click", _at("search_custref")), ("key", {"key": "home"}),
                             ("key", {"key": "shift+end"}),
                             ("type", {"text": _search_ref(a.order) + "%"}),
                             ("click", _at("search_refresh")), ("wait", {"seconds": 4})],
    # the contact note at the END of Special Instructions on the open order
    "order-note": lambda a: [("click", _at("si_end")), ("key", {"key": "end"}), ("type", {"text": a.note})],
    "order-save": lambda a: [("click", _at("order_save")), ("wait", {"seconds": 3})],
    "order-close": lambda a: [("click", _at("order_close")), ("wait", {"seconds": 2})],
    # Administration > File Interfaces > Imports with File Type NRHEAVY_Order_Import.
    # Picking it fills Input file with a default c:\temp path - never import that;
    # import-file replaces it.
    "import-open": lambda a: [("click", _at("menu_admin")), ("click", _at("menu_file_ifaces")),
                              ("click", _at("menu_imports")), ("wait", {"seconds": 8}),
                              ("click", _at("imp_type_arrow")), ("wait", {"seconds": 1}),
                              ("click", _at("imp_type_nrheavy")), ("wait", {"seconds": 2})],
    # the CSV's full path, typed. Browse opens a file window outside CTMS that Claude
    # can neither see nor click, and a typed path imports just the same (29/10).
    "import-file": lambda a: [("click", _at("imp_file")), ("key", {"key": "home"}),
                              ("key", {"key": "shift+end"}), ("type", {"text": a.path})],
    # Import. CTMS then asks twice - send the file to the server? import it now? - and
    # reports how many lines went in. Each answer sits where its message puts it, so
    # they are read off the picture and clicked one at a time, never blind.
    "import-go": lambda a: [("click", _at("imp_import")), ("wait", {"seconds": 4})],
    "import-close": lambda a: [("click", _at("imp_close")), ("wait", {"seconds": 2})],
    # The weight on the open order's item. CTMS's import reads no weight, so an order
    # comes in at its quantity (upload_weights says what it should be). Typed only -
    # the picture is checked before order-weight-save.
    "order-weight": lambda a: [("click", _at("items_tab")), ("wait", {"seconds": 2}),
                               ("click", _at("item_edit")), ("wait", {"seconds": 3}),
                               ("click", _at("item_weight")), ("key", {"key": "home"}),
                               ("key", {"key": "shift+end"}), ("type", {"text": str(a.kg)})],
    # Save and Exit the item box, then Save the order: its Planned line and total follow
    # the item. order-close after - no discard prompt means it saved.
    "order-weight-save": lambda a: [("click", _at("item_save")), ("wait", {"seconds": 3}),
                                    ("click", _at("item_exit")), ("wait", {"seconds": 2}),
                                    ("click", _at("order_save")), ("wait", {"seconds": 3})],
}


def run_steps(name, steps):
    """A fixed sequence of steps in CTMS's own window, stopping at the first that is not
    done. Every step is kept in the trace; the last picture is shown."""
    result = payload = None
    for action, args in steps:
        args = dict(args)
        if "at_px" in args:
            args["at"] = _window_point(*args.pop("at_px"))
        result, payload = ask(action, **args)
        trace(f"{name}:{action}", args, result, payload)
        if payload and payload.get("kind") == "window":
            save_state(payload)
        if not result.get("ok"):
            print(f"STOPPED at {action}: {result.get('detail')}")
            if payload:
                print_screen(payload, name)
            return 3
    print(f"DONE  {name}: {result.get('detail') if result else 'nothing to do'}")
    if payload:
        print_screen(payload, name)
    return 0


def main(argv=None):
    global BASE, KEY
    if hasattr(sys.stdout, "reconfigure"):
        # piped (as Claude runs it), Windows would write the codepage, and
        # CTMS's middle dots and pound signs arrive as question marks
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="ctms_remote.py", description="CTMS on the work PC, from the home PC.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("see")
    p.add_argument("--all", action="store_true", help="list what is out of view too")
    p.add_argument("--no-marks", action="store_true", help="a picture without the numbers drawn on")
    sub.add_parser("text")
    p = sub.add_parser("find")
    p.add_argument("words", nargs="+")
    p = sub.add_parser("click")
    p.add_argument("ref", nargs="?")
    p.add_argument("--at", help="X,Y on the latest picture")
    p.add_argument("--double", action="store_true")
    p.add_argument("--right", action="store_true", help="right-click: opens CTMS's right-click menu there")
    p.add_argument("--commit", action="store_true")
    p = sub.add_parser("type")
    p.add_argument("ref", nargs="?")
    p.add_argument("text", nargs="?")
    p.add_argument("--focused", metavar="TEXT", help="type into whatever has the cursor")
    p.add_argument("--enter", action="store_true")
    p.add_argument("--append", action="store_true", help="add to what is there instead of replacing it")
    p.add_argument("--paste", action="store_true", help="put it in at once instead of key by key")
    p.add_argument("--commit", action="store_true")
    p = sub.add_parser("key")
    p.add_argument("key")
    p.add_argument("--commit", action="store_true")
    p = sub.add_parser("select")
    p.add_argument("ref")
    p.add_argument("option")
    p.add_argument("--commit", action="store_true")
    p = sub.add_parser("scroll")
    p.add_argument("dir", nargs="?", default="down", choices=["down", "up", "left", "right", "to"])
    p.add_argument("ref", nargs="?")
    p.add_argument("--amount", type=int)
    p.add_argument("--in", dest="inside", help="scroll inside numbered thing N (a list, a panel)")
    p = sub.add_parser("hover")
    p.add_argument("ref")
    p = sub.add_parser("goto")
    p.add_argument("url")
    p.add_argument("--commit", action="store_true")
    for name in ("back", "forward", "reload"):
        sub.add_parser(name).add_argument("--commit", action="store_true")
    p = sub.add_parser("dialog")
    p.add_argument("answer", choices=["accept", "dismiss"])
    p.add_argument("--text")
    p.add_argument("--commit", action="store_true")
    p = sub.add_parser("wait")
    p.add_argument("seconds", nargs="?", type=float)
    p.add_argument("--for", dest="text")
    p.add_argument("--timeout", type=float, default=10)
    sub.add_parser("tabs")
    sub.add_parser("probe", help="what the work PC has for reading CTMS's fields (Java's Access Bridge)")
    p = sub.add_parser("fields", help="CTMS's fields by name, through Java's Access Bridge")
    p.add_argument("--all", action="store_true", help="every one, not just the first 300")
    sub.add_parser("fields-setup", help="the work PC fetches the 32-bit Python that reading fields needs")
    p = sub.add_parser("drag", help="press at one point of CTMS's picture and let go at another")
    p.add_argument("--from", dest="start", required=True, help="X,Y on the latest picture")
    p.add_argument("--to", dest="end", required=True, help="X,Y on the latest picture")
    sub.add_parser("orders-page", help="C-TMS Modules > Order Management > Orders (the Order Search card)")
    sub.add_parser("order-find", help="list an order's lines by customer ref").add_argument("order")
    sub.add_parser("order-note", help="add a note at the END of the open order's Special Instructions"
                   ).add_argument("note")
    sub.add_parser("order-save", help="the open order's Save button")
    sub.add_parser("order-close", help="the open order's Close button")
    sub.add_parser("uploads", help="the dashboard's CSVs, newest first").add_argument("text", nargs="?", default="")
    sub.add_parser("import-open", help="Administration > File Interfaces > Imports, File Type NRHEAVY_Order_Import")
    sub.add_parser("import-file", help="the CSV's full path on the work PC, typed into Input file"
                   ).add_argument("path")
    sub.add_parser("import-go", help="the Import button (its questions are answered off the picture)")
    sub.add_parser("import-close", help="the Import card's Close button")
    sub.add_parser("order-weight", help="type the open order's item weight (not saved)").add_argument("kg")
    sub.add_parser("order-weight-save", help="item Save + Exit, then the order's Save")
    p = sub.add_parser("tab")
    p.add_argument("n", type=int)
    p = sub.add_parser("update")
    p.add_argument("--branch", default="main")
    p.add_argument("--all", action="store_true", help="the whole toolkit, not just the bridge's folder")
    a = ap.parse_args(argv)
    try:
        BASE, KEY = _desk()
        return run(a)
    except Stop as e:
        print(str(e))
        return e.code


def run(a):
    c = a.cmd
    if c == "status":
        return cmd_status(a)
    if c == "see":
        args = {"marks": not a.no_marks}
        return report(c, args, *ask("see", **args), full=a.all)
    if c in ("text", "find"):
        result, payload = ask("see", picture=False, marks=False)
        trace(c, {"words": getattr(a, "words", None)}, result, payload)
        if not result.get("ok") or not payload:
            return report(c, {}, result, payload)
        save_state(payload)
        text = _squeeze(payload.get("text"))
        if c == "text":
            print(f"{payload.get('title') or '(no title)'}  |  {payload.get('url', '')}  [{payload.get('snap')}]\n")
            print(text or "(no words on the screen)")
            return 0
        want = " ".join(a.words).lower()
        hits = [e for e in payload.get("elements") or []
                if want in " ".join(str(e.get(k) or "") for k in ("l", "v", "id", "nm", "href")).lower()
                or any(want in str(o).lower() for o in e.get("o") or [])]
        print(f"Numbered things mentioning \"{want}\" [{payload.get('snap')}]:")
        for e in hits:
            print("  " + fmt_el(e))
        if not hits:
            print("  none")
        lines = [ln for ln in text.splitlines() if want in ln.lower()]
        print(f"\nLines of text mentioning it ({len(lines)}):")
        for ln in lines[:40]:
            print("  " + ln[:200])
        return 0
    if c == "click":
        args = {"commit": a.commit, "double": a.double, "right": getattr(a, "right", False)}
        if a.at:
            x, y = _xy(a.at, "--at")
            args["at"] = _window_point(x, y) if load_state().get("kind") == "window" else [x, y]
        elif a.ref is not None:
            args["ref"] = _ref(a.ref)
        else:
            raise Stop("Click what? A number from the picture, or --at X,Y.")
        return report(c, args, *ask("click", **args))
    if c == "drag":
        args = {"at": _window_point(*_xy(a.start, "--from")), "to": _window_point(*_xy(a.end, "--to"))}
        return report(c, args, *ask("drag", **args))
    if c in RUN_STEPS:
        return run_steps(c, RUN_STEPS[c](a))
    if c == "uploads":
        return cmd_uploads(a.text)
    if c == "type":
        if a.focused is not None:
            args = {"text": a.focused}
        else:
            if a.ref is None or a.text is None:
                raise Stop('type N "text" - or type --focused "text" for wherever the cursor is.')
            args = {"ref": _ref(a.ref), "text": a.text}
        args.update(enter=a.enter, append=a.append, paste=a.paste, commit=a.commit)
        return report(c, args, *ask("type", **args))
    if c == "key":
        args = {"key": a.key, "commit": a.commit}
        return report(c, args, *ask("key", **args))
    if c == "select":
        args = {"ref": _ref(a.ref), "option": a.option, "commit": a.commit}
        return report(c, args, *ask("select", **args))
    if c == "scroll":
        args = {"dir": a.dir, "amount": a.amount}
        if a.dir == "to":
            if a.ref is None:
                raise Stop("scroll to N - which number?")
            args["ref"] = _ref(a.ref)
        elif a.inside is not None:
            args["ref"] = _ref(a.inside)
        return report(c, args, *ask("scroll", **args))
    if c == "hover":
        args = {"ref": _ref(a.ref)}
        return report(c, args, *ask("hover", **args))
    if c == "goto":
        args = {"url": a.url, "commit": a.commit}
        return report(c, args, *ask("goto", **args))
    if c in ("back", "forward", "reload"):
        args = {"commit": a.commit}
        return report(c, args, *ask(c, **args))
    if c == "dialog":
        args = {"accept": a.answer == "accept", "text": a.text, "commit": a.commit}
        return report(c, args, *ask("dialog", **args))
    if c == "wait":
        args = {"seconds": a.seconds, "text": a.text, "timeout": a.timeout}
        return report(c, args, *ask("wait", wait_total=120, **args))
    if c == "tabs":
        return report(c, {}, *ask("tabs"))
    if c == "probe":
        result, payload = ask("probe", wait_total=120)
        trace(c, {}, result, payload)
        print(("DONE  " if result.get("ok") else "NOT DONE  ") + str(result.get("detail") or ""))
        if payload:
            print_probe(payload)
        return 0 if result.get("ok") else 3
    if c == "fields":
        result, payload = ask("fields", wait_total=150)
        trace(c, {}, result, payload)
        print(("DONE  " if result.get("ok") else "NOT DONE  ") + str(result.get("detail") or ""))
        if payload and payload.get("kind") == "fields":
            print_fields(payload, full=a.all)
        return 0 if result.get("ok") else 3
    if c == "fields-setup":
        result, payload = ask("fields_setup", wait_total=400)
        return report(c, {}, result, payload)
    if c == "tab":
        args = {"tab": a.n}
        return report(c, args, *ask("tab", **args))
    if c == "update":
        return cmd_update(a)
    raise Stop(f"Unknown command {c}")


def cmd_update(a):
    """The work PC fetches the branch from GitHub, tries it, restarts on it - then wait to hear from it."""
    args = {"branch": a.branch, "scope": "all" if a.all else "bridge"}
    code, before = http("GET", "/api/ctms/status")
    old = ((before or {}).get("state") or {}).get("code", "")
    result, payload = ask("update", wait_total=300, **args)
    rc = report("update", args, result, payload)
    if not result.get("ok") or "Restarting" not in str(result.get("detail")):
        return rc
    print("Waiting for the bridge to come back on the new code...")
    deadline = time.time() + 120
    time.sleep(5)
    while time.time() < deadline:
        code, st = http("GET", "/api/ctms/status")
        s = (st or {}).get("state") or {}
        if code == 200 and st.get("online") and s.get("code") and s.get("code") != old:
            print(f"Back, running {s['code']}.")
            return 0
        if s.get("rolled_back") and s.get("code") == old:
            print("ROLLED BACK: " + s["rolled_back"])
            return 3
        time.sleep(3)
    print("Not heard from the bridge on the new code yet - check status in a minute "
          "(if it would not start, it rolls itself back).")
    return 4


if __name__ == "__main__":
    sys.exit(main())
