"""
CTMS bridge - CTMS on the dashboard, and within reach of the home PC.

    python ctms_bridge.py                  run it (the first run asks three things)
    python ctms_bridge.py --setup          ask them again
    python ctms_bridge.py --allow-control  let Claude act in CTMS when the dashboard switches it on
    python ctms_bridge.py --observe-only   never act - look and record only
    python ctms_bridge.py --autostart on   start by itself when you log in (off to stop that)
    python ctms_bridge.py --rollback       put back the code the last remote update replaced

Easiest of all: the dashboard's CTMS page -> "Set up this PC" downloads a setup
file made for your dashboard. Double-click it and it does all of this for you.

Leave it running in its Command Prompt while you work. What it does:

  - finds CTMS's OWN window in your normal Edge (ctms_window.py). CTMS is
    Oracle Forms in Internet Explorer mode, which no browser opened for
    automation can run - Edge refuses - so the bridge works with the window
    you use, as it is. You log in yourself, as always; your password never
    passes through any of this.
  - checks in with the Haulage Desk. Outbound only: nothing connects in to
    this PC, exactly like the home PC's agent.
  - while the CTMS page is open on the dashboard (phone or laptop), sends it
    a picture of CTMS's window every couple of seconds - of CTMS only, never
    the rest of your screen, and never other tabs' titles.
  - "Capture this screen" files a picture of CTMS for the walkthrough.
  - LETS CLAUDE LOOK at CTMS from the home PC, and check what this PC has for
    reading CTMS's fields by name ("probe": Java's Access Bridge).
  - LETS CLAUDE READ CTMS's fields by name ("fields", ctms_jab.py): each field
    and button, what is in it, where the cursor is - asked of Java itself, so
    CTMS can be behind other windows or minimised. Never a password box, never
    a sign-in screen. Needs a 32-bit Python next to the bridge, which
    "fields_setup" fetches from python.org and checks before unpacking.
  - In a web page in the automation browser (only opened if ctms_bridge.json
    says "launch_browser": true - CTMS cannot run there), Claude also gets a
    numbered list of everything clickable, and "Record what CTMS sends" logs
    the page's requests.
  - LETS CLAUDE ACT - in CTMS's own window, typing, keys, clicks (left, double,
    right) and drags (ctms_act.py): only once CTMS is confirmed as the window
    in front, a click only ever landing on CTMS itself, and F10 / Ctrl+S (save)
    only after you have said go. While acting is on, `use ctms` / `use tracker`
    also has Edge bring up CTMS's tab or the tracker's, by its name
    (ctms_tabs.py) - never any other tab. Outside CTMS, only the "open or
    save?" box its own browser puts up after an export ("prompt"): seen, and
    answered Save (or Cancel / Close) - never Open, never another program.
    In a web page: click, type, choose, scroll. Either way the way you tell it
    to in the chat, and only while BOTH are true: this PC allows it
    (--allow-control, asked once at setup) and "Claude can act" is switched on
    on the dashboard's CTMS page, which switches itself off again when its
    time is up - not when the dashboard restarts for an update. The web
    page rails are in ctms_drive.py: never on the sign-in page, never into a
    password box, never anything that books, saves, submits or deletes until
    you have said go. Stop on the dashboard cuts it off at once.
  - UPDATES ITSELF when the dashboard or the home PC asks - from GitHub only,
    tried out before it is used, and put back by itself if the new code will
    not start (ctms_update.py). Nothing to copy across by hand.
  - FILES THE UPLOAD CSVs AND THE EMAILED RAIL PLANS in the team's shared
    folders, once they are set (shared_folder.py): each new one the dashboard
    holds goes in about a minute after it is made - a CSV under its own name,
    a rail plan as the next version of that plan. Only ever adds - nothing
    there is replaced or deleted.

Standard library only, like everything else in work_pc\\. Ctrl+C stops it.
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import io
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import cdp
import ctms_act
import book_record
import ctms_book
import ctms_drive
import ctms_export
import ctms_fast
import ctms_import
import ctms_items
import ctms_jab
import ctms_orders
import ctms_tabs
import ctms_teams
import ctms_update
import ctms_window
import pip_here
import dts_book
import shared_folder
from ctms_capture import SCREENS
from ctms_probe import DEBUG_PORT, find_browser, port_open
from start_here import PROFILE, launch, wait_for_port

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "ctms_bridge.json")        # gitignored - holds the bridge key
LOG = os.path.join(HERE, "ctms_bridge_log.jsonl")       # every command, every result
CRASH = os.path.join(HERE, "ctms_bridge_crash.txt")     # the last thing that stopped it
OUTDIR = os.path.join(HERE, "ctms_capture")
VERSION = "2"
DEFAULT_DESK = "https://dhlbutbetter.up.railway.app"
# The toolkit's single-instance locks run 8785-8791; the bridge takes the next
# one, so it can share the machine with the engine once the work PC runs it.
LOCK_PORT = 8792

# Everything this bridge will do, by who may ask and what it takes.
OBSERVE = ("look", "capture", "net")          # the dashboard's own buttons
READ = ("see", "wait", "tabs", "probe", "fields", "use",   # Claude looking: no switch needed
        "prompt",            # ... at the "open or save?" box CTMS's browser puts up (ctms_window.prompts)
        "book_recall")       # ... and what this PC's Book made, from its own record (book_record): CTMS untouched
DRIVE = ("click", "type", "key", "select", "scroll", "hover", "goto", "back", "forward",
         "reload", "dialog", "tab", "drag",
         "steps", "paste",
         "prompt_press", "prompt_click",
         "export_fetch", "export_close",
         "import_csv",     # Claude acting: this PC AND the dashboard must allow it
         "ctms_check",     # ... and the map's orders looked up in CTMS (searches only, nothing saved)
         "ctms_book",      # ... and the order panel's Book: one order's trips made in one go (ctms_book)
         "ctms_item",      # ... and one item of the CTMS to-do done in one go (ctms_items)
         "teams_send")     # ... and a dashboard message sent to DHL NOC in this PC's Teams (ctms_teams)
# What one step in CTMS's own window (or the tracker's page) can be - alone, or one of a batch ("steps").
WINDOW_STEPS = ("click", "drag", "key", "type", "wait", "paste")
# ... and what only a batch can carry: looking at the screen between the steps, on this PC (ctms_fast) -
# where CTMS sits now, waiting for it to answer, a pixel it must show, a small picture kept for the answer.
BATCH_STEPS = ("anchor", "waitfor", "check", "snap", "settle", "find")
STEPS_MAX = 120         # a whole order update - times, comments, services, vehicle - is ~90 steps
SNAPS_MAX = 8
REACT_TIMEOUT = 20      # seconds a reacting step waits for CTMS to answer before the batch stops
CHECK_ORDERS = 40       # orders one CTMS look-up takes (the map holds a few dozen at most)
CHECK_SECONDS = 360     # ... and the longest it runs: what is looked up by then still goes to the map
ADMIN = ("update", "fields_setup", "shared_folder", "folder_read", "dts_add")
ACTIONS = OBSERVE + READ + DRIVE + ADMIN
# What goes in the audit log from a command (the text typed is kept - it is an
# order number or a time, never a password: the bridge will not type into one).
LOGGED = ("name", "on", "ref", "at", "to", "snap", "text", "key", "option", "url", "dir", "amount", "commit",
          "enter", "accept", "seconds", "tab", "branch", "scope", "by", "target", "steps", "folder",
          "orders", "date", "carrier", "trailer", "haulage", "vehicles", "dry", "item", "first", "last")
RESTART = 75            # the child's exit code for "updated - start me again"

SHOT_EVERY = 1.5        # seconds between pictures while the CTMS page is open
SHOT_MAX_W = 1280       # live-view pictures are scaled down to this width
WAIT_IDLE = 10          # a check-in may wait this long for a command when nobody watches
POLL_WATCHED = 1.0      # how often to check in when the dashboard cannot hold a check-in open
POLL_IDLE = 2.5
# Request types worth showing on the dashboard as they happen. Images, styles,
# scripts and fonts are kept in a capture's network.json but are noise live.
_NET_SHOWN = ("Document", "XHR", "Fetch", "Other", "EventSource", "WebSocket")


def say(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}", flush=True)


def log(kind, **kw):
    """The audit trail. Never raises - a full disk must not stop the bridge."""
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(at=datetime.now().isoformat(timespec="seconds"),
                                    kind=kind, **kw)) + "\n")
    except Exception:
        pass


# ---- keeping secrets out of everything that leaves this PC ----------------
_SECRET_KEY = re.compile(r"pass|pwd|secret|token|otp|session|^sid$|^auth|ticket|csrf|xsrf|"
                         r"saml|signature|^sig$|^code$", re.I)
_SIGN_IN = re.compile(r"log[-_ ]?[io]n|sign[-_ ]?in|logon|j_security_check|oauth|saml|"
                      r"/sso\b|/auth\b|/token\b", re.I)


def redact_url(url):
    """A web address with session ids, tokens and passwords taken out of it."""
    url = str(url or "")
    try:
        url = re.sub(r";jsessionid=[^?#;/]*", ";jsessionid=[redacted]", url, flags=re.I)
        p = urlsplit(url)
        if p.username or p.password:
            p = p._replace(netloc=(p.hostname or "") + (f":{p.port}" if p.port else ""))
        if p.query:
            q = [(k, "[redacted]" if _SECRET_KEY.search(k) else v)
                 for k, v in parse_qsl(p.query, keep_blank_values=True)]
            p = p._replace(query=urlencode(q, safe="[]/:,"))
        if p.fragment and _SECRET_KEY.search(p.fragment):
            p = p._replace(fragment="[redacted]")
        return urlunsplit(p)
    except Exception:
        return re.sub(r"[?#].*", "?[removed]", url)


def _redact_json(o):
    if isinstance(o, dict):
        return {k: "[redacted]" if _SECRET_KEY.search(str(k)) else _redact_json(v)
                for k, v in o.items()}
    if isinstance(o, list):
        return [_redact_json(v) for v in o]
    return o


def redact_post(url, body):
    """A request body fit to keep - or a note saying why it was not kept."""
    if not body:
        return ""
    if _SIGN_IN.search(str(url or "")):
        return "[not recorded - sign-in request]"
    text = str(body)
    s = text.strip()
    try:
        if s.startswith(("{", "[")):
            text = json.dumps(_redact_json(json.loads(s)))
        elif "=" in s and "\n" not in s:
            pairs = parse_qsl(s, keep_blank_values=True)
            if pairs:
                text = urlencode([(k, "[redacted]" if _SECRET_KEY.search(k) else v)
                                  for k, v in pairs], safe="[]/:,")
    except Exception:
        pass
    # A shape that could not be taken apart (multipart, XML...) and still says
    # "password" somewhere is not worth the risk of being the one that has it.
    if re.search(r"pass(word)?|pwd", text, re.I) and "[redacted]" not in text:
        return "[not recorded - it carries a password field]"
    return text[:4000]


_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.I)
_META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
_VALUE_ATTR = re.compile(r"""(\bvalue\s*=\s*)("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
# name=value after ? & ; or &amp; - wherever it sits: a link, a form's action,
# a script. Java apps put the session id IN the address (";jsessionid=..."),
# so every href and action on a CTMS screen can carry it.
_PARAM = re.compile(r"""([?&;]|&amp;)([^=&;#\s"'<>]+)=([^&;#\s"'<>]*)""")


def _scrub_params(text):
    """Blank the value of every secret-named parameter, leaving the rest byte for byte."""
    return _PARAM.sub(lambda m: m.group(1) + m.group(2) + "="
                      + ("[redacted]" if _SECRET_KEY.search(m.group(2)) else m.group(3)), text)


def redact_html(html):
    """Page HTML with password boxes, anti-forgery and session tokens blanked."""
    def fix_input(m):
        tag = m.group(0)
        names = re.findall(r"""\b(?:name|id)\s*=\s*["']?([^"'\s>]+)""", tag, re.I)
        if (re.search(r"""\btype\s*=\s*["']?password""", tag, re.I)
                or any(_SECRET_KEY.search(n) or re.search(r"viewstate|eventvalidation", n, re.I)
                       for n in names)):
            tag = _VALUE_ATTR.sub(r'\1"[redacted]"', tag)
        return tag

    def fix_meta(m):
        tag = m.group(0)
        if re.search(r"csrf|xsrf|token", tag, re.I):
            tag = re.sub(r"""(\bcontent\s*=\s*)("[^"]*"|'[^']*'|[^\s>]+)""",
                         r'\1"[redacted]"', tag, flags=re.I)
        return tag
    return _scrub_params(_META_TAG.sub(fix_meta, _INPUT_TAG.sub(fix_input, html or "")))


def friendly(e):
    if isinstance(e, RuntimeError):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        return f"The dashboard refused it (HTTP {e.code})."
    if isinstance(e, urllib.error.URLError):
        return f"Could not reach the dashboard ({e.reason})."
    if isinstance(e, TimeoutError):
        return f"The browser took too long to answer ({e})."
    if isinstance(e, (ConnectionError, OSError)):
        return (f"Lost the connection to the CTMS tab ({type(e).__name__}). It reattaches by "
                f"itself - try again in a few seconds.")
    return f"{type(e).__name__}: {e}"


def code_label():
    cur = ctms_update.current()
    return f"{cur.get('branch') or '?'}@{str(cur.get('commit') or '')[:7]}" if cur.get("commit") else ""


def _idle_now():
    """Whole seconds since this PC's keyboard or mouse was last used; -1 where that can't be asked."""
    try:
        q = ctms_window.idle_seconds()
    except Exception:
        q = None
    return -1 if q is None else int(q)


# ---- the dashboard -----------------------------------------------------------
class Desk:
    """The Haulage Desk's control plane, reached the way this PC reaches the web.

    The work PC sits behind a PAC-configured proxy, which urllib cannot read on
    its own - it would go direct and be refused, exactly as pip was. The proxy
    comes out of the PAC the same way pip_here.py gets it. TLS inspection needs
    nothing extra here: Python on Windows already trusts the machine's own
    certificate stores, which is where the corporate CA lives, so verification
    stays on. (pip needed a bundle only because it brings its own roots.)
    """

    def __init__(self, url, key):
        self.base = url.rstrip("/")
        self.key = key
        host = (urlsplit(self.base).hostname or "").lower()
        if host in ("127.0.0.1", "localhost"):
            handler = urllib.request.ProxyHandler({})
        else:
            proxy = pip_here.proxy_from_pac()
            handler = (urllib.request.ProxyHandler({"http": f"http://{proxy}", "https": f"http://{proxy}"})
                       if proxy else urllib.request.ProxyHandler())
        self.opener = urllib.request.build_opener(
            handler, urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def post(self, path, body, timeout=20):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Auth": self.key},
                                     method="POST")
        with self.opener.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")


# ---- the browser ---------------------------------------------------------------
class Bridge:
    def __init__(self, desk, port, match, allow_control=False):
        self.desk = desk
        self.port = port
        self.match = (match or "").strip().lower()
        self.allow_control = bool(allow_control)   # this PC's own say-so (--allow-control)
        self.armed = False                         # the dashboard's "Claude can act", as last heard
        self.ticket = ""     # while it is on: the dashboard's signed note of until when, handed back if it restarts
        # host AND port: the dashboard open in the automation browser must not be
        # mistaken for CTMS, but another site on the same host is not the dashboard
        self.desk_host = urlsplit(desk.base).netloc.lower()
        self.ws = None
        self.driver = None           # ctms_drive.Driver for the attached tab
        self.tab = None              # the /json entry of the tab being watched
        self.browser = ""
        self.tabs = 0
        self.checked = 0.0
        self.error = ""              # finding / attaching to the tab
        self.shot_error = ""         # the last picture that could not be taken or sent
        self.watched = False
        self.shot_at = 0.0
        self.shot_hash = None
        self.hidden_since = 0.0
        self.net_on = False
        self.net = []                # requests since recording started (ring)
        self.net_new = []            # requests since the last capture
        self.net_count = 0
        self.net_sent = -1           # net_count the dashboard last heard about
        self.screens_sent = False
        self.long_poll = False       # the dashboard holds a check-in open until there is work
        self.restart_after = False   # an update was laid down: exit so the supervisor restarts us
        self.batch = {"off": (0, 0), "snaps": []}   # the batch being run: its anchor offset and kept pictures
        self.confirmed = False
        self.rolled_back = ctms_update.rolled_back()
        # CTMS's own window in his normal Edge (ctms_window.py). CTMS runs in
        # Internet Explorer mode there, which no automation browser can open, so
        # when it is found it is what the bridge watches - ahead of any tab.
        self.win = None
        self.win_checked = 0.0
        # Which window the bridge works: CTMS's ("ctms"), or the one allowed web page ("page" - the DigiHaul
        # Job Tracker, ctms_window.PAGE_WORDS). Claude switches it with `use`; every start is CTMS.
        self.target = "ctms"
        # `use` has just had Edge bring a tab up (ctms_tabs): Edge decides where its keyboard focus lands,
        # so keys wait until Claude has clicked into the page.
        self.click_first = False

    # -- CTMS's own window --
    def scan_window(self, force=False):
        if not force and time.time() - self.win_checked < 5:
            return self.win
        self.win_checked = time.time()
        try:
            wins = ctms_window.find_windows()
        except Exception as e:
            wins = []
            self.shot_error = f"Could not look for CTMS's window ({type(e).__name__})."
        wins = [w for w in wins if (w.get("kind") == "page") == (self.target == "page")]
        old, self.win = self.win, (wins[0] if wins else None)
        if bool(old) != bool(self.win) or (old and self.win and old["hwnd"] != self.win["hwnd"]):
            if self.win:
                say(f"Found {'the tracker' if self.target == 'page' else 'CTMS'}'s window: "
                    f"{self.win['title'][:80] or '?'} ({self.win['process'] or self.win['class']})")
                log("window", title=self.win["title"][:120], window_kind=self.win["kind"], java=self.win["java"])
            else:
                say("CTMS's window has gone (closed, or not open in Edge).")
                log("window", title="")
            self.shot_hash = None
        return self.win

    def window_picture(self):
        """(BGRA, w, h, how) of the window being worked, found afresh - it may have moved."""
        if not self.scan_window(force=True):
            raise RuntimeError(self.not_found())
        return ctms_window.picture(self.win)

    def not_found(self):
        if self.target == "page":
            return ("The DigiHaul Job Tracker is not the selected tab of any Edge window - select its tab, or "
                    "`use tracker` brings it up while Claude can act (`use ctms` goes back to CTMS).")
        return ("CTMS is not open in your Edge, or another tab is selected in its window - select CTMS's tab, or "
                "`use ctms` brings it up while Claude can act; the bridge finds its window by itself.")

    # -- which tab is CTMS --
    def candidates(self):
        """The browser's web tabs that could be CTMS - never the dashboard itself."""
        pages = cdp.pages(self.port)
        self.tabs = len(pages)
        web = [p for p in pages if str(p.get("url", "")).startswith(("http://", "https://"))
               and urlsplit(p["url"]).netloc.lower() != self.desk_host]
        return [p for p in web if self.match in p["url"].lower()] if self.match else web

    def refresh(self, force=False):
        """Find the CTMS tab and stay attached to it. Cheap; runs every few seconds."""
        if not force and time.time() - self.checked < 3:
            return
        self.checked = time.time()
        if not port_open(self.port, timeout=0.5):
            if self.browser:
                say("The automation browser has closed. Run this again to reopen it.")
                log("browser_closed")
            self._detach()
            self.browser, self.tabs = "", 0
            self.error = "The automation browser is not running on the work PC."
            return
        try:
            if not self.browser:
                self.browser = cdp.http_json("/json/version", self.port).get("Browser") or "?"
            want = self.candidates()
        except Exception as e:
            self.error = f"Could not read the browser's tabs ({type(e).__name__})."
            return
        current = next((p for p in want if self.tab and p.get("id") == self.tab.get("id")), None)
        if current:
            self.tab = current           # same tab - title and address may have moved on
            if self.ws:
                self.error = ""
                return
        pick = current or (want[0] if want else None)
        if not pick:
            self._detach()
            self.error = (f"No tab in the automation browser has '{self.match}' in its address - "
                          f"open CTMS there and log in." if self.match else
                          "CTMS is not open in the automation browser - open it there and log in.")
            return
        self._attach(pick)

    def _attach(self, tab):
        self._detach()
        if not tab.get("webSocketDebuggerUrl"):
            self.error = "That tab is held by another debugger - close DevTools on it."
            return
        try:
            self.ws = cdp.WS(tab["webSocketDebuggerUrl"], timeout=15)
            self.ws.on_event = self._on_event
            self.driver = ctms_drive.Driver(self.ws)
            self.tab = tab
            # dialog boxes and page loads: what acting has to wait for and report
            self.ws.call("Page.enable")
            if self.net_on or self.allow_control:
                self.ws.call("Network.enable", {"maxPostDataSize": 65536})
            self.error = ""
            self.shot_hash = None
            say(f"Watching: {tab.get('title') or '?'} | {redact_url(tab.get('url'))[:90]}")
            log("attach", title=tab.get("title"), url=redact_url(tab.get("url")))
            remember_ctms_url(tab.get("url"))
        except Exception as e:
            self._detach()
            self.error = f"Could not attach to the CTMS tab: {friendly(e)}"

    def _detach(self):
        if self.ws:
            self.ws.close()
        self.ws, self.tab, self.driver = None, None, None

    def _visible_elsewhere(self):
        """The current tab is hidden: is another candidate the one on screen?

        /json does not say which tab is the selected one, so ask each - only
        when the current one has gone hidden, never on the normal path.
        """
        try:
            pages = self.candidates()
        except Exception:
            return
        for p in pages[:6]:
            if p.get("id") == (self.tab or {}).get("id") or not p.get("webSocketDebuggerUrl"):
                continue
            try:
                probe = cdp.WS(p["webSocketDebuggerUrl"], timeout=5)
                try:
                    vis = probe.evaluate("document.visibilityState", timeout=5)
                finally:
                    probe.close()
            except Exception:
                continue
            if vis == "visible":
                self._attach(p)
                return

    def tab_list(self):
        cur = (self.tab or {}).get("id")
        return [{"n": i + 1, "title": str(p.get("title") or "")[:100], "url": redact_url(p.get("url"))[:200],
                 "current": p.get("id") == cur} for i, p in enumerate(self.candidates()[:20])]

    def switch_tab(self, n):
        pages = self.candidates()
        try:
            p = pages[int(n) - 1]
        except (TypeError, ValueError, IndexError):
            raise ctms_drive.Refused(f"There is no tab {n} - 'tabs' lists them.")
        self._attach(p)
        if not self.ws:
            raise RuntimeError(self.error or "Could not attach to that tab.")
        self.ws.call("Page.bringToFront", timeout=8)     # a tab that is not shown cannot be pictured
        return f"Switched to tab {n}: {p.get('title') or '?'}"

    # -- events: dialogs and page loads for the driver, requests for the recording --
    def _on_event(self, msg):
        if self.driver:
            self.driver.on_event(msg)
        if not self.net_on:
            return
        m, p = msg.get("method"), msg.get("params") or {}
        if m == "Network.requestWillBeSent":
            r = p.get("request") or {}
            url = str(r.get("url") or "")
            if url.startswith(("data:", "blob:")):
                return
            body = r.get("postData") or ("[body not included by the browser]" if r.get("hasPostData") else "")
            e = {"rid": p.get("requestId"), "at": time.strftime("%H:%M:%S"),
                 "method": r.get("method") or "", "url": redact_url(url)[:500],
                 "type": p.get("type") or "", "status": "", "mime": "",
                 "post": redact_post(url, body)}
            self.net.append(e)
            del self.net[:-400]
            self.net_new.append(e)
            del self.net_new[:-1500]
            self.net_count += 1
        elif m == "Network.responseReceived":
            resp = p.get("response") or {}
            for e in reversed(self.net[-80:]):
                if e["rid"] == p.get("requestId"):
                    e["status"] = str(resp.get("status") or "")
                    e["mime"] = str(resp.get("mimeType") or "")[:60]
                    break

    def set_net(self, on):
        if on == self.net_on:
            return
        if on:
            if not self.ws:
                raise RuntimeError(self.error or "No CTMS tab to record.")
            self.ws.call("Network.enable", {"maxPostDataSize": 65536})
            self.net_on = True
        else:
            self.net_on = False
            # acting still needs to know when the page has finished loading
            if self.ws and not self.allow_control:
                try:
                    self.ws.call("Network.disable")
                except Exception:
                    pass

    def drain(self):
        if not self.ws:
            return
        try:
            self.ws.drain()
        except Exception as e:
            self._detach()
            self.error = f"Lost the CTMS tab ({type(e).__name__}) - reattaching."

    # -- pictures --
    def picture(self, fmt="jpeg", max_w=SHOT_MAX_W, quality=55):
        """The visible part of the CTMS tab, as base64. Raises with a reason."""
        if not self.ws:
            raise RuntimeError(self.error or "No CTMS tab to look at.")
        return ctms_drive.grab(self.ws, fmt, max_w, quality, self.driver.dialog if self.driver else None)

    def send_window_shot(self, force=False):
        """The live view of CTMS's own window - a PNG, made only when the window changed."""
        self.shot_at = time.time()
        try:
            bgra, w, h, _ = self.window_picture()
        except RuntimeError as e:
            self.shot_error = str(e)
            self.shot_at = time.time() + 4
            raise
        digest = hashlib.sha1(bgra).hexdigest()
        try:
            if digest == self.shot_hash and not force:
                if self.desk.post("/api/ctms/shot", {"same": True}).get("need"):
                    self.shot_hash = None
            else:
                data = base64.b64encode(ctms_window.png(bgra, w, h)).decode()
                self.desk.post("/api/ctms/shot", {"data": data, "mime": "image/png", "w": w, "h": h, "url": "",
                                                  "title": (self.win or {}).get("title") or "CTMS"}, timeout=60)
                self.shot_hash = digest
        except Exception as e:
            self.shot_error = f"The picture did not reach the dashboard: {friendly(e)}"
            raise RuntimeError(self.shot_error)
        self.shot_error = ""

    def send_shot(self, force=False):
        if self.win:
            return self.send_window_shot(force)
        self.shot_at = time.time()
        try:
            data, view = self.picture()
        except RuntimeError as e:
            self.shot_error = str(e)
            self.shot_at = time.time() + 4          # do not hammer a window that is not painting
            if "not on screen" in str(e) and time.time() - self.hidden_since > 5:
                self.hidden_since = time.time()
                self._visible_elsewhere()
            raise
        digest = hashlib.sha1(data.encode()).hexdigest()
        try:
            if digest == self.shot_hash and not force:
                if self.desk.post("/api/ctms/shot", {"same": True}).get("need"):
                    self.shot_hash = None       # the dashboard has no picture - send it whole next time
            else:
                self.desk.post("/api/ctms/shot", {"data": data, "w": view.get("w"), "h": view.get("h"),
                                                  "url": redact_url(view.get("url")),
                                                  "title": view.get("title") or ""}, timeout=30)
                self.shot_hash = digest
        except Exception as e:
            self.shot_error = f"The picture did not reach the dashboard: {friendly(e)}"
            raise RuntimeError(self.shot_error)
        self.shot_error = ""

    # -- the walkthrough --
    def capture(self, name):
        """Everything a selector gets written from, zipped, kept here and sent home."""
        if not self.ws:
            raise RuntimeError(self.error or "No CTMS tab to capture.")
        ws = self.ws
        view = json.loads(ws.evaluate(cdp.VIEW_JS, timeout=10) or "{}")
        html = redact_html(ws.evaluate(cdp.HTML_JS, timeout=60) or "")
        fields = json.loads(ws.evaluate(cdp.FIELDS_JS, timeout=60) or "[]")
        for f in fields:
            if f.get("href"):
                f["href"] = redact_url(f["href"])
            if f.get("tag") == "FRAME" and f.get("value"):
                f["value"] = redact_url(f["value"])
        text = _scrub_params(ws.evaluate(cdp.TEXT_JS, timeout=30) or "")
        png, _ = self.picture(fmt="png", max_w=0)
        net, self.net_new = self.net_new, []
        frames = sorted({f.get("where") for f in fields} - {"page"})
        meta = {"name": name, "captured": datetime.now().isoformat(timespec="seconds"),
                "url": redact_url(view.get("url")), "title": view.get("title") or "",
                "viewport": {k: view.get(k) for k in ("w", "h", "dpr")},
                "fields": len(fields), "frames": frames, "network_recorded": self.net_on,
                "requests": len(net), "bridge": VERSION, "machine": platform.node()}

        def build(with_html=True):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("meta.json", json.dumps(meta, indent=1))
                z.writestr("fields.json", json.dumps({"url": meta["url"], "title": meta["title"],
                                                      "fields": fields}, indent=1))
                if with_html:
                    z.writestr("page.html", html)
                z.writestr("page.txt", text)
                if png:
                    z.writestr("screen.png", base64.b64decode(png))
                if net:
                    z.writestr("network.json", json.dumps(net, indent=1))
            return buf.getvalue()

        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:40] or "screen"
        zname = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe}.zip"
        whole = build()
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, zname), "wb") as f:
            f.write(whole)
        sent, note = whole, ""
        if len(whole) > 12_000_000:
            sent = build(with_html=False)
            note = " The page HTML was too big to send - it is in the copy on the work PC."
        try:
            self.desk.post("/api/ctms/capture", {"name": zname, "size": len(sent),
                                                 "data": base64.b64encode(sent).decode()}, timeout=180)
        except Exception as e:
            raise RuntimeError(f"Saved on the work PC as ctms_capture\\{zname}, but it did not reach "
                               f"the dashboard ({friendly(e)}) - capture it again in a minute.")
        summary = (f"{meta['title'] or 'untitled page'} - {len(fields)} field(s)"
                   + (f" across {len(frames)} frame(s)/shadow root(s)" if frames else "")
                   + (f", {len(net)} request(s) recorded" if net else "") + "." + note)
        return zname, summary

    def window_look(self):
        """CTMS's own window as Claude gets it: the picture - no numbered list yet."""
        bgra, w, h, how = self.window_picture()
        win = self.win
        return {"kind": "window", "img": base64.b64encode(ctms_window.png(bgra, w, h)).decode(),
                "mime": "image/png", "img_w": w, "img_h": h, "title": win["title"], "how": how,
                "window": {k: win[k] for k in ("kind", "process", "java", "ie_showing", "foreground", "minimized")},
                "note": ("The DigiHaul Job Tracker (its tab is selected): only its page is pictured. Click a point "
                         "with click --at X,Y; type --focused and keys work, the browser's own keys do not."
                         if win.get("kind") == "page" else
                         "CTMS's own window: a picture, read by eye - no numbered list. Click a point on it "
                         "with click --at X,Y (--double to open an order); type --focused and keys also work.")
                        + (" Edge has just switched tabs: click into the page before any keys."
                           if self.click_first else "")}

    # -- the "open or save?" box CTMS's browser puts up (31/10) --
    def prompt_look(self):
        """(what it says, the picture) of the box CTMS's browser has up - or, with none, what is in front."""
        ps = ctms_window.prompts()
        if not ps:
            return "No box from CTMS's browser is up. " + self.front_said(), {"kind": "prompt", "prompts": []}
        p = ps[0]
        bgra, w, h, how = ctms_window.prompt_picture(p)
        said = (f"The browser's box '{p['title'] or 'untitled'}'" + ("" if p["foreground"] else " (behind other windows)")
                + (": " + " / ".join(p["words"][:3]) if p["words"] else "")
                + (" - buttons: " + ", ".join(b["text"] for b in p["buttons"]) if p["buttons"]
                   else " - no buttons it can press by name (aim at them on the picture)"))
        return said, {"kind": "prompt", "img": base64.b64encode(ctms_window.png(bgra, w, h)).decode(),
                      "mime": "image/png", "img_w": w, "img_h": h, "title": p["title"], "how": how,
                      "prompts": [dict({k: q[k] for k in ("title", "process", "foreground", "words", "parts")},
                                       buttons=[b["text"] for b in q["buttons"]]) for q in ps[:3]],
                      "note": "The browser's own box: prompt-press Save (never Open), or aim with prompt-click "
                              "--at X,Y on this picture."}

    # -- an upload CSV into CTMS in one go: the map's Upload button (31/10, ctms_import) --
    def import_csv(self, cmd, done):
        """The CSV from the dashboard into Downloads, then CTMS's whole import - commit: the real thing (his Upload
        click); without it a dry run up to Import, the card then closed. Stops at the first step CTMS does not
        answer, touching nothing more. The answer's payload says whether the import ran ("imported")."""
        name = str(cmd.get("option") or "")
        if not shared_folder.NAME.fullmatch(name):
            return done(False, f"'{name[:60]}' is not an upload CSV's name.", {"imported": False})
        if not self.scan_window(force=True) or self.target != "ctms":
            return done(False, self.not_found() if self.target == "ctms" else
                        "The bridge is working the tracker - use ctms first.", {"imported": False})
        try:
            got = self.desk.post("/api/ctms/upload", {"name": name}, timeout=60)
        except Exception as e:
            return done(False, f"Could not get {name} from the dashboard ({friendly(e)}) - if it restarted, press "
                               "Re-send on the Files card, then Upload again.", {"imported": False})
        data = base64.b64decode((got or {}).get("data") or "")
        if not data:
            return done(False, f"{name} is not on the dashboard right now - press Re-send on the Files card, then "
                               "Upload again.", {"imported": False})
        saved_as, _ = shared_folder.file_one(ctms_export.DOWNLOADS, name, data)
        path = os.path.join(ctms_export.DOWNLOADS, saved_as)
        t = ctms_import.templates()
        self.batch = {"off": (0, 0), "snaps": []}
        t0, times = time.time(), []
        said = ""                                   # what was done before the card opened - first in every answer

        def run(steps):
            for step in steps:
                ts = time.time()
                try:
                    self.window_step(step["action"], step)
                except Exception as e:
                    if step.get("why"):                 # the step says what its miss means
                        raise RuntimeError(step["why"]) from e
                    raise
                finally:
                    times.append(round(time.time() - ts, 2))

        def stopped(stage, e, imported, closed=""):
            why = str(e) if isinstance(e, (ctms_drive.Refused, ctms_drive.NeedsCommit, RuntimeError)) else friendly(e)
            return done(False, said + f"Stopped while {stage}: {why} "
                        + (closed or "Nothing more was touched - the picture shows where."),
                        dict(self._batch_look(times, t0), imported=imported))

        def close_it():
            """Before Import nothing went in: close the card this opened - only if its Close is seen there."""
            try:
                run(ctms_import.close_card(t))
                return "Nothing went into CTMS, and the Import card is closed again."
            except Exception:
                return "Nothing went into CTMS. The Import card's Close was not where it should be, so it was " \
                       "left as it is - the picture shows where."
        try:
            run([{"action": "anchor"}])
            said = self.order_filters_away(t)
        except Exception as e:
            return stopped("making sure nothing is in the way of the Import card", e, False)
        try:
            run(ctms_import.open_and_type(path, t))
        except Exception as e:
            return stopped("opening the Import card and typing the path", e, False, close_it())
        if not cmd.get("commit"):
            try:
                run(ctms_import.close_card(t))
            except Exception as e:
                return stopped("closing the Import card (dry run)", e, False)
            return done(True, said + f"Dry run: the Import card opened, NRHEAVY_Order_Import chosen and {path} "
                                     "typed - Import not pressed (no go-ahead), and the card closed.",
                        dict(self._batch_look(times, t0), imported=False))
        try:
            run(ctms_import.import_and_answer(t))
        except Exception as e:
            # past Import, CTMS may have taken the file: never press anything more, and never call it not done
            return stopped("importing (CTMS may have taken it - check before uploading again)", e, True)
        try:
            run(ctms_import.clean_checks(t))
            clean = True
        except Exception:
            clean = False
        try:
            run(ctms_import.finish(t))
        except Exception as e:
            return stopped("closing CTMS's answer and the Import card - the import itself ran", e, True)
        return done(clean, said + f"Uploaded {name} into CTMS: " + (
            "no lines failed and none were invalid." if clean else
            "SOME LINES FAILED OR WERE INVALID - CTMS's own answer is in the picture.")
            + " OK pressed and the Import card closed.", dict(self._batch_look(times, t0), imported=True))

    # -- the map's orders looked up in CTMS: booked or not, their dates, the Veh Type (01/11, ctms_orders) --
    def ctms_check(self, cmd, done):
        """Each order the dashboard sends ({ref, date, veh}) searched in Order Summary and its lines read through the
        Access Bridge - and, for one with veh (due within a fortnight), its open lines' cards opened (up to twelve: the
        weight adds up over all of them, and four of seven lines could call a 14 t order 8 t and rigid, 02/11) to
        see whether the Veh Type is filled and read the weight, which decides rigid or artic on the map. Searches and
        reads only: nothing typed into an order, nothing saved. Order Summary
        is closed after, so Planning shows as before. What was found goes to the dashboard (/api/ctms/orders), which
        hands it to the home PC to put on the map."""
        orders = [o for o in cmd.get("orders") or [] if isinstance(o, dict) and o.get("ref")][:CHECK_ORDERS]
        if not orders:
            return done(False, "No orders to look up.", {"kind": "ctms_check"})
        if not self.scan_window(force=True) or self.target != "ctms":
            return done(False, self.not_found() if self.target == "ctms" else
                        "The bridge is working the tracker - use ctms first.", {"kind": "ctms_check"})
        idle = float(cmd.get("idle") or 0)
        quiet = ctms_window.idle_seconds()
        if idle and quiet is not None and quiet < idle * 60:
            return done(False, f"Not looked up: the work PC was used {int(quiet)}s ago - it waits for "
                               f"{idle:g} quiet minutes, so CTMS is never taken from under you.",
                        {"kind": "ctms_check", "postponed": True})
        t = ctms_orders.templates()
        self.batch = {"off": (0, 0), "snaps": []}
        t0, times = time.time(), []

        def run(steps):
            for step in steps:
                ts = time.time()
                try:
                    self.window_step(step["action"], step)
                finally:
                    times.append(round(time.time() - ts, 2))

        def why(e):
            return str(e) if isinstance(e, (ctms_drive.Refused, ctms_drive.NeedsCommit, RuntimeError)) else friendly(e)
        try:
            run([{"action": "anchor"}, {"action": "click", "px": [1000, 37], "after": 0.4}])  # Java's focus
            if not self._seen(t, "os-card", ctms_orders.CARD_BOX):
                run(ctms_orders.to_orders(t))
            run(ctms_orders.card(t))
            run(ctms_orders.upto(ctms_jab.read_fields(self.win, skip=ctms_items.NOT_READ)))   # later orders listed at all
        except Exception as e:
            return done(False, f"Could not get to CTMS's Order Search: {why(e)} Nothing was looked up - the "
                               "picture shows where it stopped.", dict(self._batch_look(times, t0), kind="ctms_check"))
        found, stopped, lost = {}, "", False
        for o in orders:
            if time.time() - t0 > CHECK_SECONDS:
                stopped = f"out of time after {len(found)} of {len(orders)}"
                break
            try:
                run(ctms_orders.search(ctms_orders.search_ref(o["ref"])))
            except Exception:
                pass                    # nothing found leaves the list empty - CTMS's answer changed nothing
            try:
                rows = ctms_orders.lines(ctms_jab.read_fields(self.win, skip=ctms_items.NOT_READ))
            except Exception as e:
                stopped = f"reading {o['ref']}'s lines: {why(e)}"
                break
            if rows is None:
                stopped, lost = "Order Summary was no longer on the screen", True
                break
            got = {"lines": [r for r in rows if ctms_orders.belongs(r["ref"], o["ref"])]}
            for line in ctms_orders.open_lines(got["lines"], str(o.get("date") or "")) if o.get("veh") else []:
                try:
                    run(ctms_orders.search(line["ref"]))            # the line alone: the list's first row
                    one = [r for r in ctms_orders.lines(ctms_jab.read_fields(self.win, skip=ctms_items.NOT_READ)) or []
                           if r["ref"] == line["ref"]]
                    if one and one[0]["status"] == ctms_orders.OPEN:     # unscheduled: opening it asks nothing
                        run(ctms_orders.open_line(t))
                        bgra, w, h = self._frame()
                        got.setdefault("veh", {})[line["ref"]] = ctms_orders.veh_filled(
                            bgra, w, h, self.batch.get("off", (0, 0)))
                        kg = ctms_orders.card_weight(ctms_jab.read_fields(self.win, skip=ctms_items.NOT_READ))
                        if kg is not None:
                            got.setdefault("weight", {})[line["ref"]] = kg
                        run(ctms_orders.close_line(t))
                except Exception as e:
                    stopped, lost = f"looking at {line['ref']}'s card: {why(e)}", True
                    break
            found[o.get("key") or f"{o['ref']}|{o.get('date') or ''}"] = got
            if lost:
                break
        closed = False
        if not lost:
            try:
                if self._seen(t, "os-card", ctms_orders.CARD_BOX):
                    run([{"action": "click", "px": [509, 226], "after": 0.5}])     # the Search card's Close
                run(ctms_orders.close_summary(t))
                closed = True
            except Exception:
                pass
        payload = {"orders": found, "checked": len(found), "of": len(orders), "stopped": stopped,
                   "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        try:
            self.desk.post("/api/ctms/orders", payload, timeout=60)
            onward = " Sent to the home PC for the map."
        except Exception as e:
            onward = f" NOT sent to the dashboard ({friendly(e)}) - look them up again."
        booked = sum(1 for g in found.values() if g["lines"] and all(r["status"] != ctms_orders.OPEN
                                                                     for r in g["lines"]))
        missing = sum(1 for g in found.values() if not g["lines"])
        vehs = [v for g in found.values() for v in (g.get("veh") or {}).values()]
        kgs = [v for g in found.values() for v in (g.get("weight") or {}).values()]
        said = (f"Looked up {len(found)} of {len(orders)} order(s) in CTMS: {booked} with no line left to book, "
                f"{missing} not found" + (f", Veh Type looked at on {len(vehs)} ({sum(vehs)} filled)" if vehs else "")
                + (f", weight read on {len(kgs)}" if kgs else "")
                + "." + onward
                + (" Order Summary closed again." if closed else
                   " Order Summary was left as it is - the picture shows where." if not lost else
                   " CTMS was left as it is - the picture shows where."))
        if stopped:
            said = f"Stopped {stopped}. " + said
        return done(not stopped, said, dict(self._batch_look(times, t0), kind="ctms_check", checked=len(found),
                                            orders=found))

    # -- the order panel's Book: one order's trips made in one go, no picture between the steps (02/11, ctms_book) --
    def book_order(self, cmd, done):
        """His press of Book, the haulier and the price picked on the panel. Every click is CTMS's own on this PC; what was
        made goes back in the answer, and a stop says where, with any box left open backed out of."""
        orders = [str(o).strip() for o in cmd.get("orders") or [] if str(o).strip()]
        date, carrier = str(cmd.get("date") or ""), str(cmd.get("carrier") or "").strip()
        if not orders or not date or not carrier:
            return done(False, "Book needs the order, its date and the carrier.", {"kind": "ctms_book"})
        if not self.scan_window(force=True) or self.target != "ctms":
            return done(False, self.not_found() if self.target == "ctms" else
                        "The bridge is working the tracker - use ctms first.", {"kind": "ctms_book"})
        t = ctms_book.templates()
        self.batch = {"off": (0, 0), "snaps": []}
        t0, times = time.time(), []

        def run(steps):
            for step in steps:
                ts = time.time()
                try:
                    self.window_step(step["action"], step)
                finally:
                    times.append(round(time.time() - ts, 2))

        job = ctms_book.Booking(run, lambda tree=True: ctms_jab.read_fields(
                                    self.win, skip_roles=() if tree else ("tree",)).get("elements") or [],
                                lambda name, box: self._seen(t, name, box), t, dry=bool(cmd.get("dry")))
        stopped = ""
        try:
            job.book(orders, date, carrier, str(cmd.get("trailer") or "").strip(), cmd.get("haulage"),
                     int(cmd.get("vehicles") or 1), qty=cmd.get("qty") if isinstance(cmd.get("qty"), dict) else None)
        except Exception as e:
            stopped = str(e) if isinstance(e, (ctms_drive.Refused, ctms_drive.NeedsCommit, RuntimeError)) else friendly(e)
            try:
                job.back_out()
            except Exception:
                pass
        try:
            job.tidy()
        except Exception:
            pass
        took = round(time.time() - t0, 1)
        made = [x for x in job.trips if x.get("manifest")]
        fixed = "; ".join(n for n in job.said if "put right" in n or "put up to" in n)
        said = (f"{'Rehearsed' if cmd.get('dry') else 'Booked'} {' / '.join(orders)} in {took:g}s: "
                + ", ".join(f"{x['manifest']} {x['status']}" for x in made) if made and not stopped else
                f"Rehearsed {' / '.join(orders)} in {took:g}s with {carrier}: revenue {job.trips[0]['revenue']}, cost "
                f"{job.trips[0]['cost']}. Nothing booked." if job.trips and not stopped else
                f"Stopped after {took:g}s: {stopped}"
                + (f" Already made: {', '.join(x['manifest'] + ' ' + x['status'] for x in made)}." if made else ""))
        if job.veh_kept and (stopped or cmd.get("dry")) and not made:
            said += f" CTMS keeps {job.veh_kept} as the line's Veh Type from the carrier screen."
        if fixed:
            said += f" On the lines first: {fixed}."
        # written down before the answer goes, so the home PC can ask for it again if the answer never reaches it
        book_record.keep(cmd.get("id"), orders, date, carrier, cmd.get("dry"), not stopped, said, job.trips, stopped)
        return done(not stopped, said, dict(self._batch_look(times, t0), kind="ctms_book", trips=job.trips,
                                            stages=job.stages, notes=job.said, stopped=stopped, seconds=took,
                                            reads=job.reads))

    # -- one item of the CTMS to-do, done in one go (02/11, ctms_items) --
    def todo_item(self, cmd, done):
        """A note or an update, as the home PC's Run hands them over one at a time. Says whether it was done, held (CTMS has
        it already), or stopped - and whether CTMS was left clean, so the next item can go ahead. first and last: the
        run's first and last, which clear the way and put Planning back."""
        item = cmd.get("item") if isinstance(cmd.get("item"), dict) else {}
        kind = {"kind": "ctms_item"}
        if not item.get("lines"):
            return done(False, "That to-do item came with no order line.", dict(kind, clean=True))
        if not self.scan_window(force=True) or self.target != "ctms":
            return done(False, self.not_found() if self.target == "ctms" else
                        "The bridge is working the tracker - use ctms first.", dict(kind, clean=False))
        t = ctms_items.templates()
        self.batch = {"off": (0, 0), "snaps": []}
        t0, times = time.time(), []

        def run(steps):
            for step in steps:
                ts = time.time()
                try:
                    self.window_step(step["action"], step)
                finally:
                    times.append(round(time.time() - ts, 2))

        job = ctms_items.Items(run, lambda: ctms_jab.read_fields(self.win, skip=ctms_items.NOT_READ).get("elements") or [],
                               lambda name, box: self._seen(t, name, box), t)
        ok, held, clean, said = False, False, True, ""
        try:
            if cmd.get("first"):
                job.begin()
            said, ok = job.do(item, dry=bool(cmd.get("dry"))), True
        except ctms_items.Held as e:
            said, held = str(e), True
        except ctms_items.Busy as e:
            said, clean = str(e), False
        except Exception as e:
            said = str(e) if isinstance(e, (ctms_drive.Refused, ctms_drive.NeedsCommit, RuntimeError)) else friendly(e)
            clean = job.clear_up()
            if not clean:
                said += " CTMS is left as it is, for a look."
        if cmd.get("last") and clean:
            try:
                job.finish()
            except Exception:
                pass
        took = round(time.time() - t0, 1)
        return done(ok or held, said, dict(self._batch_look(times, t0), kind="ctms_item", done=ok, held=held, clean=clean,
                                           stages=job.stages, seconds=took))

    def _seen(self, t, name, box):
        """Whether one of the check's templates shows in that part of CTMS's window now - one look, nothing clicked."""
        tp = t[name]
        bgra, w, h = self._frame()
        tpl = ctms_fast.rgb_to_bgra(base64.b64decode(tp["rgb"]), tp["w"], tp["h"])
        return bool(ctms_fast.find(bgra, w, h, ctms_fast.shift_box(box, self.batch.get("off", (0, 0))), tpl,
                                   tp["w"], tp["h"]))

    def order_filters_away(self, t):
        """His Order Filters panel floats over every CTMS card, and on 31/10 it sat right over the Import card's
        Import button. His word: "If you see it there, close it" - so before the card opens it is closed by its own
        X, and left alone when it is parked out of the way. The picture is looked at again after each click: the
        first may only bring the panel to the front (it did, 31/10), and while its title is still there its X is
        where it was - the pointer resting on it may have drawn a box round it by then. Says what it did ('' if
        nothing); raises when the panel will not close."""
        at = None
        for clicks in range(3):
            bgra, w, h = self._frame()
            if not at:
                at = ctms_import.order_filters_x(bgra, w, h, t, self.batch.get("off", (0, 0)))
                if not at:
                    return ""
            elif not ctms_import.order_filters(bgra, w, h, t):
                return "Order Filters was over the Import card, so it was closed first. "
            if clicks < 2:
                self.window_step("click", {"action": "click", "at": [at[0] / w, at[1] / h],
                                           "name": "Order Filters' X", "after": 0.8})
        raise RuntimeError("Order Filters is over the Import card and did not close - close it yourself, then "
                           "Upload again.")

    def export_tabs_away(self, want):
        """Close the export tab(s) `want` names, by their own close buttons, and see CTMS's tab is the one showing
        again - Edge shows a neighbouring tab when one closes, which may be any. Says what was done.

        The tab's own "Internet Explorer Download" box (Open / Save / Save as / Cancel) is answered Cancel first:
        the file is taken already, and while that box is up the tab will not close (31/10: a close was pressed,
        the tab stayed, and went only once Cancel was). Closed is counted from the tabs really gone."""
        before = len(ctms_tabs.names(want))
        for _ in range(2 if before else 0):
            for p in ctms_window.prompts():
                if "download" in (p.get("title") or "").lower():
                    try:
                        ctms_act.press_button(p, "Cancel")
                    except ctms_drive.Refused:
                        pass
            ctms_tabs.close(want)
            time.sleep(0.6)
            if not ctms_tabs.names(want):
                break
        left = len(ctms_tabs.names(want)) if before else 0
        n = before - left
        said = ""
        if not ctms_tabs.is_ctms((self.scan_window(force=True) or {}).get("title")):
            ok, said = ctms_tabs.select("ctms")
            if ok:
                self.click_first = True             # where Edge's keyboard focus lands is Edge's choice
            for _ in range(12):                     # CTMS's Internet Explorer page takes a moment to come back
                if ctms_tabs.is_ctms((self.scan_window(force=True) or {}).get("title")):
                    break
                time.sleep(0.25)
        back = ctms_tabs.is_ctms((self.win or {}).get("title"))
        return ((f"Closed {n} export tab{'' if n == 1 else 's'}" if n else
                 "No export tab to close" if not before else "The export tab did not close")
                + (f" ({left} still open - close {'it' if left == 1 else 'them'} yourself)" if left and n else "")
                + ("; CTMS's tab is the one showing again." if back
                   else f"; CTMS's tab is not showing - {said or 'select it yourself'}."))

    def front_said(self):
        f = ctms_window.front()
        if not f:
            return "Nothing is in front."
        return f"In front: {f.get('process') or '?'} ({f.get('class') or '?'}" + (
            f", '{f['title']}'" if f.get("title") else "") + ")."

    # -- looking between the steps of a batch (ctms_fast) --
    def _frame(self):
        """(BGRA, w, h) of the window being worked, now - the window the batch started on, found afresh only if
        it has gone. Fast enough to look several times a second."""
        try:
            bgra, w, h, _ = ctms_window.picture(self.win)
        except Exception:
            bgra, w, h, _ = self.window_picture()
        self.batch["size"] = (w, h)
        return bgra, w, h

    def _point(self, args, at_key="at", px_key="px"):
        """Where a step aims, as the fraction ctms_act takes. A px point - the picture's own pixels, as the recipes
        were measured - moves by the batch's anchor and is taken of the window as it is now (Forms lays its windows
        out from the top left, so pixels hold where fractions would stretch); an at point is a fraction already."""
        px = args.get(px_key)
        if isinstance(px, (list, tuple)) and len(px) == 2:
            w, h = self.batch.get("size") or self._frame()[1:]
            dx, dy = self.batch.get("off", (0, 0))
            return [(float(px[0]) + dx) / w, (float(px[1]) + dy) / h]
        # a screen point, as the Access Bridge places CTMS's fields (an order well row's cell, 02/11) - taken of the
        # picture's own rectangle, so it is refused like any other point that falls off CTMS
        sc = args.get("screen") if at_key == "at" else None
        if isinstance(sc, (list, tuple)) and len(sc) == 2:
            left, top, right, bottom = (int(v) for v in ctms_window.content_area(self.win))
            return [(float(sc[0]) - left) / max(1, right - left), (float(sc[1]) - top) / max(1, bottom - top)]
        return args.get(at_key)

    def _react(self, before, args):
        """Wait for CTMS to answer the step just taken: the watched box (or the whole screen) changes from how it
        was before the step, then the screen holds still for `quiet` seconds. The box is what makes a server round
        trip safe to wait on - a menu closing or a button going down is not the answer, the window or the rows
        that box covers arriving is. Returns the seconds it took; raises if CTMS did not answer in time."""
        timeout = min(float(args.get("timeout") or REACT_TIMEOUT), 60.0)
        quiet = min(float(args["quiet"]) if args.get("quiet") is not None else 0.5, 5.0)
        base, w0, h0 = before
        box = args.get("box")
        box = (ctms_fast.shift_box(box, self.batch.get("off", (0, 0)))
               if isinstance(box, (list, tuple)) and len(box) == 4 else None)
        enough = 0 if box else ctms_fast.QUIET_BLOCKS     # anything in the box; more than a caret on the screen
        t0 = time.time()
        moved, last, still = False, base, 0.0
        while time.time() - t0 < timeout:
            cur, w, h = self._frame()
            if (w, h) != (w0, h0):                      # the window was resized under us: start again from here
                base, last, w0, h0, moved, still = cur, cur, w, h, True, time.time()
            elif not moved:
                if ctms_fast.changed(base, cur, w, h, box) > enough:
                    moved, still = True, time.time()
            elif ctms_fast.changed(last, cur, w, h) > ctms_fast.QUIET_BLOCKS:
                still = time.time()
            elif time.time() - still >= quiet:
                return round(time.time() - t0, 2)
            last = cur
            time.sleep(0.03)
        raise RuntimeError(f"CTMS did not answer within {timeout:g}s - "
                           + ("nothing changed where it should have" if not moved else "the screen never settled"))

    def batch_step(self, action, args):
        """A step only a batch has: anchor, waitfor, check, snap, settle or find. They look - only find touches
        CTMS, and only when told to click what it found, with a click's rails."""
        off = self.batch.get("off", (0, 0))
        if action == "anchor":
            bgra, w, h = self._frame()
            found = ctms_fast.anchor(bgra, w, h)
            if found is None:
                raise RuntimeError("Could not find CTMS's grey menu bar on the picture - a window is over it, or "
                                   "the page has scrolled past it.")
            dx, dy = found
            extra = ""
            if args.get("window"):           # CTMS's own area scrolls its windows; the menu bar stays put
                wy = ctms_fast.window_offset(bgra, w, h, ctms_fast.CANON_MENU_BOTTOM + dy)
                dy += wy
                extra = f" (its windows {wy:+d} of that)"
            self.batch["off"] = (dx, dy)
            return f"CTMS sits {dx:+d},{dy:+d} px from where the recipes were measured{extra}"
        if action == "find":
            name = re.sub(r"[^A-Za-z0-9._()-]+", "-", str(args.get("name") or "picture"))[:40]
            box = args.get("box")
            try:
                tw, th = int(args.get("tw") or 0), int(args.get("th") or 0)
                tpl = ctms_fast.rgb_to_bgra(base64.b64decode(str(args.get("tpl") or "")), tw, th)
            except Exception:
                raise RuntimeError(f"find '{name}' came without its picture - ctms_remote sends it from its templates.")
            if not (isinstance(box, (list, tuple)) and len(box) == 4):
                raise RuntimeError(f"find '{name}' needs the part of the screen to look in: box=X0,Y0,X1,Y1.")
            area = ctms_fast.shift_box(box, off)
            timeout = min(float(args.get("timeout") or 0), 60.0)
            t0 = time.time()
            while True:
                bgra, w, h = self._frame()
                hit = ctms_fast.find(bgra, w, h, area, tpl, tw, th)
                if hit or time.time() - t0 >= timeout:
                    break
                time.sleep(0.05)
            if not hit:
                raise RuntimeError(f"'{name}' is not on the screen where it should be"
                                   + (f" (looked for {timeout:g}s)." if timeout else "."))
            if not (args.get("click") or args.get("double")):
                return f"Found '{name}' at {hit[0]},{hit[1]}"
            cx, cy = hit[0] + tw / 2, hit[1] + th / 2
            detail = ctms_act.click(self.win["hwnd"], cx / w, cy / h, ctms_window.content_area(self.win),
                                    double=bool(args.get("double")))
            self.click_first = False
            if args.get("react"):
                return f"{detail} on '{name}' - CTMS answered in {self._react((bgra, w, h), args)}s"
            time.sleep(min(max(float(args["after"]), 0.0), 10.0) if args.get("after") is not None else 0.4)
            return f"{detail} on '{name}'"
        if action in ("waitfor", "check"):
            px, sc = args.get("px"), args.get("screen")
            if isinstance(sc, (list, tuple)) and len(sc) == 2:     # where the Access Bridge places a thing
                left, top = (int(v) for v in ctms_window.content_area(self.win)[:2])
                px, off = [sc[0] - left, sc[1] - top], (0, 0)
            if not (isinstance(px, (list, tuple)) and len(px) == 2):
                raise RuntimeError(f"{action} needs a point: {action} X,Y #RRGGBB.")
            want = ctms_fast.parse_color(args.get("color"))
            tol = int(args["tol"]) if args.get("tol") is not None else 24
            hold = not args.get("not")
            timeout = 0.0 if action == "check" else min(float(args.get("timeout") or 10), 60.0)
            x, y = int(px[0] + off[0]), int(px[1] + off[1])
            t0 = time.time()
            while True:
                bgra, w, h = self._frame()
                if not (0 <= x < w and 0 <= y < h):
                    raise RuntimeError(f"{int(px[0])},{int(px[1])} is off CTMS's picture.")
                seen = ctms_fast.rgb_at(bgra, w, x, y)
                if ctms_fast.near(seen, want, tol) == hold:
                    return (f"{'Saw' if hold else 'Gone:'} {ctms_fast.hex_color(want)} at {int(px[0])},{int(px[1])}"
                            + (f" after {time.time() - t0:.2f}s" if timeout else ""))
                if time.time() - t0 >= timeout:
                    raise RuntimeError(f"Expected {'' if hold else 'anything but '}{ctms_fast.hex_color(want)} at "
                                       f"{int(px[0])},{int(px[1])} but it is {ctms_fast.hex_color(seen)}"
                                       + (f" after {timeout:g}s" if timeout else "") + ".")
                time.sleep(0.03)
        if action == "snap":
            box = args.get("box")
            if not (isinstance(box, (list, tuple)) and len(box) == 4):
                raise RuntimeError("snap needs the part of the screen to keep: snap NAME x0,y0,x1,y1.")
            if len(self.batch["snaps"]) >= SNAPS_MAX:
                raise RuntimeError(f"At most {SNAPS_MAX} snaps in one batch.")
            x0, y0, x1, y1 = (int(v) for v in ctms_fast.shift_box(box, off))
            if not (x1 > x0 and y1 > y0) or (x1 - x0) * (y1 - y0) > 1200 * 600:
                raise RuntimeError("A snap is a small part of the screen - at most 1200 x 600 pixels.")
            bgra, w, h = self._frame()
            data, cw, ch = ctms_window.crop(bgra, w, h, (x0, y0, x1, y1))
            name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(args.get("name") or "")).strip("-.")[:30]
            name = name or f"snap{len(self.batch['snaps']) + 1}"
            self.batch["snaps"].append({"name": name, "w": cw, "h": ch,
                                        "img": base64.b64encode(ctms_window.png(data, cw, ch)).decode()})
            return f"Kept '{name}' ({cw}x{ch})"
        if action == "settle":
            quiet = min(float(args["quiet"]) if args.get("quiet") is not None else 0.5, 5.0)
            timeout = min(float(args.get("timeout") or 10), 60.0)
            last, w, h = self._frame()
            t0 = still = time.time()
            while time.time() - t0 < timeout:
                time.sleep(0.03)
                cur, w2, h2 = self._frame()
                if (w2, h2) != (w, h) or ctms_fast.changed(last, cur, w, h) > ctms_fast.QUIET_BLOCKS:
                    still, w, h = time.time(), w2, h2
                elif time.time() - still >= quiet:
                    return f"Still after {time.time() - t0:.2f}s"
                last = cur
            raise RuntimeError(f"The screen kept changing for {timeout:g}s.")
        raise RuntimeError(f"'{action}' is not a step in CTMS's window.")

    def window_step(self, action, args):
        """One step in the window being worked - click, drag, key, type, wait or paste - with the same rails
        alone or in a batch. Returns what was done; anything refused raises.

        In a batch a step can also carry react (wait for CTMS to answer it, see _react) and after (seconds to
        pause instead of the usual 0.4 after a click / 0.3 after a key), and aim with px instead of at."""
        if action in BATCH_STEPS:
            return self.batch_step(action, args)
        react = bool(args.get("react")) and action != "wait"
        if react and self.click_first and action not in ("click", "drag"):
            raise RuntimeError("Edge has just switched tabs, and where its keyboard focus landed is Edge's "
                               "choice - click into the page first (click --at X,Y), then the keys.")
        before = self._frame() if react else None
        after = args.get("after")
        if action in ("click", "drag"):
            at = self._point(args)
            if action == "click":
                if not (isinstance(at, (list, tuple)) and len(at) == 2):
                    raise RuntimeError("In CTMS's window, click a point on the picture: click --at X,Y. "
                                       "There are no numbered things to click here.")
                detail = ctms_act.click(self.win["hwnd"], at[0], at[1], ctms_window.content_area(self.win),
                                        double=bool(args.get("double")), right=bool(args.get("right")),
                                        **({"hold": args["hold"]} if args.get("hold") else {}))
            else:
                to = self._point(args, "to", "px2")
                if not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in (at, to)):
                    raise RuntimeError("A drag needs where to press and where to let go, both points on the "
                                       "picture: drag --from X,Y --to X,Y.")
                detail = ctms_act.drag(self.win["hwnd"], at, to, ctms_window.content_area(self.win))
            self.click_first = False
            pause = 0.4
        elif action == "wait":
            s = min(max(float(args.get("seconds") or 2), 0.0), 30.0)
            time.sleep(s)
            return f"Waited {s:g}s"
        else:
            if self.click_first:
                raise RuntimeError("Edge has just switched tabs, and where its keyboard focus landed is Edge's "
                                   "choice - click into the page first (click --at X,Y), then the keys.")
            if action == "key":
                detail = ctms_act.press(self.win["hwnd"], args.get("key") or "",
                                        commit=bool(args.get("commit")), page=self.win.get("kind") == "page")
            elif action == "type":
                detail = ctms_act.type_text(self.win["hwnd"], args.get("text") or "",
                                            enter=bool(args.get("enter")), commit=bool(args.get("commit")))
            elif action == "paste":
                detail = ctms_act.paste_text(self.win["hwnd"], args.get("text") or "")
            else:
                raise RuntimeError(f"'{action}' is not a step in CTMS's window.")
            pause = 0.3
        if react:
            return f"{detail} - CTMS answered in {self._react(before, args)}s"
        time.sleep(min(max(float(after), 0.0), 10.0) if after is not None else pause)
        return detail

    def window_steps(self, steps, done):
        """A batch of steps run here one after another, with ONE picture at the end - each step a round
        trip through the dashboard with a picture of its own was most of a booking's time (29/10). Stops
        at the first step that is refused or fails, and says which; the picture shows where it stopped.
        The answer also carries how long each step took and any snaps the batch kept."""
        if not isinstance(steps, list) or not steps:
            raise RuntimeError("steps needs a list of steps.")
        if len(steps) > STEPS_MAX:
            raise RuntimeError(f"At most {STEPS_MAX} steps in one go.")
        self.batch = {"off": (0, 0), "snaps": []}
        t0, times, last = time.time(), [], ""
        for i, step in enumerate(steps, 1):
            action = str((step or {}).get("action") or "") if isinstance(step, dict) else ""
            ts = time.time()
            try:
                if action not in WINDOW_STEPS + BATCH_STEPS:
                    raise RuntimeError(f"'{action[:20]}' is not a step in CTMS's window.")
                last = self.window_step(action, step)
                times.append(round(time.time() - ts, 2))
            except Exception as e:
                why = str(e) if isinstance(e, (ctms_drive.Refused, ctms_drive.NeedsCommit)) else friendly(e)
                times.append(round(time.time() - ts, 2))
                return done(False, f"Stopped at step {i} of {len(steps)} ({action or '?'}): {why}"
                                   + (f" Done before it: {i - 1} step(s)." if i > 1 else ""),
                            self._batch_look(times, t0))
        return done(True, f"Ran {len(steps)} step(s) in {time.time() - t0:.1f}s; the last: {last}",
                    self._batch_look(times, t0))

    def _batch_look(self, times, t0):
        """The picture at the end of a batch, with the step times and the snaps it kept."""
        p = self.window_look()
        p.update(times=times, took=round(time.time() - t0, 1), snaps=self.batch.get("snaps") or [])
        return p

    def capture_window(self, name):
        """A walkthrough capture of CTMS's own window: the picture and where it came from."""
        bgra, w, h, how = self.window_picture()
        win = self.win
        meta = {"name": name, "captured": datetime.now().isoformat(timespec="seconds"), "title": win["title"],
                "kind": win["kind"], "process": win["process"], "java_parts": win["java"], "picture": how,
                "size": [w, h], "bridge": VERSION, "machine": platform.node()}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("meta.json", json.dumps(meta, indent=1))
            z.writestr("screen.png", ctms_window.png(bgra, w, h))
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:40] or "screen"
        zname = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe}.zip"
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, zname), "wb") as f:
            f.write(buf.getvalue())
        try:
            self.desk.post("/api/ctms/capture", {"name": zname, "size": len(buf.getvalue()),
                                                 "data": base64.b64encode(buf.getvalue()).decode()}, timeout=180)
        except Exception as e:
            raise RuntimeError(f"Saved on the work PC as ctms_capture\\{zname}, but it did not reach "
                               f"the dashboard ({friendly(e)}) - capture it again in a minute.")
        return zname, f"{win['title'] or 'CTMS'} - a picture of CTMS's window ({w}x{h})."

    # -- what Claude gets back --
    def _finish(self, p):
        """A look at the screen, fit to leave this PC, with the tabs alongside."""
        p = dict(p)
        if p.get("url"):
            p["url"] = redact_url(p["url"])
        for e in p.get("elements") or []:
            if e.get("href"):
                e["href"] = redact_url(e["href"])
        if p.get("text"):
            p["text"] = _scrub_params(p["text"])
        try:
            p["tabs"] = self.tab_list()
        except Exception:
            pass
        return p

    def after(self):
        """The screen as it is now. Every action answers with it, so the result is seen, not assumed."""
        if self.watched:
            try:
                self.send_shot(force=True)          # the live view first: he may be watching it
            except Exception:
                pass
        if not self.driver:
            return {"picture_error": self.error or "The CTMS tab went away."}
        try:
            return self._finish(self.driver.see())
        except ctms_drive.Refused as e:
            return {"dialog": self.driver.dialog if self.driver else None, "note": str(e)}
        except Exception as e:
            return {"picture_error": friendly(e)}

    # -- commands from the dashboard and the home PC --
    def handle(self, cmd):
        action = str(cmd.get("action") or "")
        cid, name = cmd.get("id"), str(cmd.get("name") or "")
        log("command", id=cid, action=action, **{k: cmd[k] for k in LOGGED if k in cmd})

        def done(ok, detail, payload=None):
            log("result", id=cid, action=action, name=name, ok=ok, detail=detail)
            say(("OK    " if ok else "NO    ") + action + (f" '{name}'" if name else "") + f": {detail}")
            body = {"id": cid, "action": action, "name": name, "ok": ok, "detail": detail}
            if payload is not None:
                body["payload"] = payload
            try:
                self.desk.post("/api/ctms/result", body, timeout=60)
            except Exception as e:
                say(f"      (the answer did not reach the dashboard: {friendly(e)})")

        if action not in ACTIONS:
            return done(False, f"Refused: '{action[:40]}' is not something this bridge does.")
        if action in DRIVE:
            if not self.allow_control:
                return done(False, "Refused: this work PC lets the bridge look but not act (observe only). "
                                   "To let Claude act, run on the work PC:  python ctms_bridge.py --allow-control")
            if not self.armed:
                return done(False, "Refused: 'Claude can act' is switched off on the dashboard's CTMS page.")
        if action == "update":
            return self.update(cmd, done)
        if action == "shared_folder":
            return self.shared_folder(cmd, done)
        if action == "dts_add":
            return self.dts_add(cmd, done)
        if action == "book_recall":
            found = book_record.recall(cmd.get("orders") or [], cmd.get("date") or "", cmd.get("ask"))
            return done(True, f"{len(found)} booking(s) on record for {' / '.join(cmd.get('orders') or [])} on "
                              f"{cmd.get('date')}.", {"kind": "book_recall", "found": found})
        if action == "folder_read":
            try:
                said, got = shared_folder.look(cmd.get("folder"))
            except (ValueError, OSError) as e:
                return done(False, str(e))
            return done(True, said, got)
        self.refresh(force=True)
        self.scan_window(force=True)
        try:
            if action == "look":
                self.send_shot(force=True)
                return done(True, "Fresh picture sent.")
            if action == "capture":
                if self.win:
                    zname, summary = self.capture_window(name or "screen")
                else:
                    zname, summary = self.capture(name or "screen")
                return done(True, f"Captured {zname}: {summary}")
            if action == "net":
                if self.win and not self.ws and cmd.get("on"):
                    raise RuntimeError("CTMS runs in Internet Explorer mode in your own Edge, where the bridge "
                                       "cannot see its requests - recording only works in the automation browser.")
                self.set_net(bool(cmd.get("on")))
                return done(True, "Recording what CTMS sends." if self.net_on else "Stopped recording.")
            if action == "probe":
                p = ctms_window.probe()
                return done(True, probe_summary(p), p)
            if action == "fields":
                # Java's Access Bridge: works with CTMS behind other windows or minimised
                if not self.win:
                    raise RuntimeError("Reading fields works on CTMS's own window, and it is not open in your "
                                       "Edge - open CTMS there as normal.")
                p = ctms_jab.read_fields(self.win)
                return done(True, ctms_jab.summary(p), dict(p, kind="fields", title=self.win["title"]))
            if action == "fields_setup":
                return done(True, ctms_jab.setup())
            if action == "prompt":
                return done(True, *self.prompt_look())
            if action == "export_fetch":
                # the file CTMS's export opened in a tab, taken from its address into Downloads (ctms_export) -
                # then that tab closed and CTMS's brought back, so the bridge sees CTMS again
                names = ([self.win["title"]] if self.win else []) + ctms_tabs.names(ctms_export.is_export)
                got = ctms_export.take(names, cmd.get("option") or "", cmd.get("since") or "")
                data = got.pop("data")
                back = self.export_tabs_away(lambda n: got["url"] in (n or ""))
                onward = ""
                if ctms_export.RAIL_EXPORT.fullmatch(got["name"]):     # the rail plan's own report: home builds it
                    try:
                        self.desk.post("/api/ctms/export", {"name": got["name"],
                                                            "data": base64.b64encode(data).decode()}, timeout=60)
                        onward = " Sent to the home PC, which builds the rail plan from it as a preview."
                    except Exception as e:
                        onward = f" Not sent to the home PC ({friendly(e)}) - it is in Downloads."
                return done(True, (f"Took {got['name']} {got['how']} into Downloads"
                                   + ("" if got["saved_as"] == got["name"] else f" as {got['saved_as']}")
                                   + ("" if got["written"] else " - it was there already, left as it was")
                                   + f": {got['rows']} row(s), {got['bytes']:,} bytes. Header: {got['header']}. "
                                   + back + onward),
                            dict(got, kind="export"))
            if action == "export_close":
                # export tabs left open - each one blanks CTMS's window for the bridge
                return done(True, self.export_tabs_away(ctms_export.is_export))
            if action == "teams_send":
                # a dashboard message to DHL NOC, sent in this PC's Teams (his ask 01/11) - ctms_teams checks the chat,
                # the box and the text before pressing Teams' own Send, and stops with nothing sent on anything else
                try:
                    got = ctms_teams.send(cmd.get("email"), cmd.get("name"), cmd.get("text"), dry=bool(cmd.get("dry")))
                except ctms_teams.Stop as e:
                    return done(False, f"Not sent: {e}")
                return done(got["ok"], got["said"], got.get("payload") or None)
            if action == "import_csv":
                return self.import_csv(cmd, done)
            if action == "ctms_check":
                return self.ctms_check(cmd, done)
            if action == "ctms_book":
                return self.book_order(cmd, done)
            if action == "ctms_item":
                return self.todo_item(cmd, done)
            if action in ("prompt_press", "prompt_click"):
                ps = ctms_window.prompts()
                if not ps:
                    raise RuntimeError("No box from CTMS's browser is up. " + self.front_said())
                p = ps[0]
                if action == "prompt_press":
                    detail = ctms_act.press_button(p, cmd.get("option"))
                else:
                    if p["buttons"]:            # a point could land on Run or Open: its buttons go by name only
                        raise RuntimeError("This box has buttons to press by what they say ("
                                           + ", ".join(b["text"] for b in p["buttons"]) + ") - prompt-press Save. "
                                           "A point is only for a box with none to name.")
                    at = cmd.get("at")
                    if not (isinstance(at, (list, tuple)) and len(at) == 2):
                        raise RuntimeError("Aim at a point on the prompt's picture: prompt-click --at X,Y.")
                    detail = ctms_act.click(p["hwnd"], at[0], at[1], p["frame"]).replace(" CTMS ", " the prompt ")
                time.sleep(0.6)                     # the box goes, or the next one comes
                said, payload = self.prompt_look()
                return done(True, f"{detail}. Now: {said}", payload)
            if action == "use":
                # which window to work - CTMS's, or the tracker's page. Its tab not the selected one: while
                # Claude can act, Edge brings it up by its name (ctms_tabs). Not found even so: stay where we were.
                want, was = cmd.get("target"), self.target
                if want not in ("ctms", "page"):
                    raise RuntimeError("Use which window? use ctms, or use tracker.")
                self.target = want
                brought = None
                if not self.scan_window(force=True) and self.allow_control and self.armed:
                    brought = ctms_tabs.select(want)
                    if brought[0]:
                        self.click_first = True
                        for _ in range(12):             # CTMS's Internet Explorer page takes a moment to come back
                            if self.scan_window(force=True):
                                break
                            time.sleep(0.25)
                        if self.win:
                            # Edge draws a tab only while its window can be seen: switched behind other windows,
                            # the tracker stayed undrawn and CTMS's old picture lingered (work PC, 29/10)
                            ctms_act.to_front(self.win["hwnd"])
                        end = time.time() + 8
                        while self.win and time.time() < end:
                            try:
                                drawn = not ctms_window.blank(self.window_picture()[0])
                            except Exception:
                                drawn = False
                            # drawn, and on the tracker CTMS's Internet Explorer page is gone from the window
                            if drawn and (want == "ctms" or not (self.win or {}).get("ie_showing")):
                                break
                            time.sleep(0.5)
                if not self.win:
                    self.target = was
                    self.scan_window(force=True)
                    if brought:
                        why = brought[1] if not brought[0] else (
                            "Edge brought its tab up, but " + ("the tracker's page" if want == "page"
                                                               else "CTMS's window") + " did not show.")
                    else:
                        why = (("The DigiHaul Job Tracker's tab is not the selected one in Edge" if want == "page"
                                else "CTMS is not open in your Edge, or its tab is not the selected one")
                               + " - select it, or switch 'Claude can act' on and use brings it up itself.")
                    raise RuntimeError(why + " Still working " + ("the tracker." if was == "page" else "CTMS."))
                return done(True, (brought[1] + " " if brought else "") + "Now working "
                            + ("the DigiHaul Job Tracker." if want == "page" else "CTMS's window."),
                            self.window_look())
            if self.win:
                # CTMS's own window (Oracle Forms in IE mode): keys, typing, clicks
                # (left, double, right) and drags go to it through ctms_act.
                if action == "see":
                    return done(True, "Looked at " + ("the tracker." if self.target == "page" else "CTMS's window."),
                                self.window_look())
                if action in WINDOW_STEPS:
                    return done(True, self.window_step(action, cmd), self.window_look())
                if action == "steps":
                    return self.window_steps(cmd.get("steps"), done)
                if action in DRIVE:
                    return done(False, "Refused: in CTMS's own window the bridge can type, paste, press keys, "
                                       "left-click, double-click, right-click and drag, alone or as steps - "
                                       "select and scroll are the next increment, not built yet.")
            if action in ("steps", "paste"):
                raise RuntimeError(self.not_found())
            if action == "tabs":
                tabs = self.tab_list()
                return done(True, f"{len(tabs)} tab(s) could be CTMS.", {"tabs": tabs})
            if action == "tab":
                detail = self.switch_tab(cmd.get("tab"))
                return done(True, detail, self.after())
            d = self.driver
            if not d:
                raise RuntimeError(self.error or "No CTMS tab to work on.")
            if action == "see":
                p = d.see(marks=cmd.get("marks") is not False, picture=cmd.get("picture") is not False)
                return done(True, "Looked at " + (p.get("title") or "the CTMS tab") + ".", self._finish(p))
            if action == "wait":
                detail = d.wait(cmd.get("seconds"), cmd.get("text"), cmd.get("timeout") or 10)
                return done(True, detail, self.after())
            ref, snap, commit = cmd.get("ref"), cmd.get("snap"), bool(cmd.get("commit"))
            if action == "click":
                detail = d.click(ref=ref, at=cmd.get("at"), snap=snap, commit=commit,
                                 double=bool(cmd.get("double")))
            elif action == "type":
                detail = d.type_text(cmd.get("text") or "", ref=ref, snap=snap, enter=bool(cmd.get("enter")),
                                     append=bool(cmd.get("append")), paste=bool(cmd.get("paste")), commit=commit)
            elif action == "key":
                detail = d.key(cmd.get("key") or "", commit=commit)
            elif action == "select":
                detail = d.select(ref, cmd.get("option") or "", snap=snap, commit=commit)
            elif action == "scroll":
                detail = d.scroll(cmd.get("dir") or "down", cmd.get("amount"), ref, snap)
            elif action == "hover":
                detail = d.hover(ref, snap)
            elif action == "goto":
                detail = d.goto(cmd.get("url") or "", commit=commit)
            elif action in ("back", "forward"):
                detail = d.history(-1 if action == "back" else 1, commit=commit)
            elif action == "reload":
                detail = d.reload(commit=commit)
            else:                                   # dialog
                detail = d.answer_dialog(bool(cmd.get("accept")), cmd.get("text"), commit=commit)
            return done(True, detail, self.after())
        except ctms_drive.NeedsCommit as e:
            return done(False, str(e), {"needs_commit": True})
        except ctms_drive.Refused as e:
            return done(False, str(e))
        except Exception as e:
            if isinstance(e, (ConnectionError, TimeoutError)):
                self._detach()              # the socket is suspect - reattach on the next look
            return done(False, friendly(e))

    def update(self, cmd, done):
        """New code from GitHub, tried first, then restart on it (the supervisor rolls back a dud)."""
        branch = str(cmd.get("branch") or "main")
        scope = cmd.get("scope") if cmd.get("scope") in ctms_update.SCOPES else "bridge"
        say(f"Updating from GitHub ({branch}, {scope})...")
        try:
            zpath = ctms_update.download(branch)
            try:
                commit, changes = ctms_update.plan(zpath, scope)
            finally:
                shutil.rmtree(os.path.dirname(zpath), ignore_errors=True)
            if not changes:
                if ctms_update.current().get("commit") != commit:
                    ctms_update.stamp(commit, branch, scope, 0)
                return done(True, f"Already up to date with {branch} ({commit[:7]}) - nothing to change.")
            ctms_update.smoke(changes)
            ctms_update.apply(changes, commit, branch, scope)
        except ctms_update.UpdateError as e:
            return done(False, f"Not updated: {e}")
        except Exception as e:      # not friendly(): an OSError here is a file, not the CTMS tab
            return done(False, f"Not updated: {type(e).__name__}: {e}")
        names = [rel.rsplit("/", 1)[-1] for rel, _ in changes]
        log("updated", branch=branch, commit=commit, scope=scope, files=[rel for rel, _ in changes])
        self.restart_after = True
        return done(True, f"Updated to {branch} {commit[:7]} - {len(changes)} file(s): "
                          + ", ".join(names[:8]) + (" ..." if len(names) > 8 else "")
                          + ". Restarting on the new code - back in a few seconds.")

    def dts_add(self, cmd, done):
        """Rows on the team's DTS sheet, which only this PC reaches (dts_book.py): that one workbook on the team's share."""
        path = os.path.normpath(str(cmd.get("folder") or ""))
        root = os.path.normcase(shared_folder.team_root().rstrip("\\/"))
        if not root or not os.path.normcase(path).startswith(root + os.sep) or os.path.basename(path).lower() != "dts.xlsx":
            return done(False, "That isn't the DTS sheet on the team's shared folder.")
        try:
            got = dts_book.add_rows(path, cmd.get("rows") or [])
        except dts_book.Busy as e:
            return done(False, f"Not yet: {e}.")
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as e:
            return done(False, f"Not added: {e}")
        return done(True, f"{len(got['rows'])} row(s) on the {got['tab']} tab, {got['skipped']} already there.", got)

    def shared_folder(self, cmd, done):
        """Where the upload CSVs (kind "rail": the emailed rail plans, each into the folder its text names
        for it) are filed (shared_folder.py), set from the dashboard or the home PC."""
        folder = str(cmd.get("folder") or "").strip()
        kind = "rail" if cmd.get("kind") == "rail" else "csv"
        if cmd.get("on") is False:
            return done(True, shared_folder.stop(kind))
        if not folder:
            return done(True, shared_folder.describe())
        try:
            said = shared_folder.set_folder(folder, kind=kind, routes=cmd.get("text"))
        except ValueError as e:
            return done(False, str(e))
        try:        # one look now: the dashboard's list answers, and anything waiting goes in
            went = shared_folder.tick(self.desk)
        except Exception as e:
            return done(True, f"{said} First look: {shared_folder.why(e)}.")
        return done(True, said + (f" Filed {len(went)} just now." if went else " Nothing new to file yet."))

    def stop(self):
        log("stop")
        say("STOP pressed on the dashboard - recording off, queue cleared, Claude cannot act.")
        self.armed, self.ticket = False, ""
        try:
            self.set_net(False)
        except Exception:
            pass

    # -- what the dashboard sees --
    def state(self):
        d = self.driver.dialog if self.driver else None
        win = self.win
        # CTMS's own window first: it IS CTMS; a tab in the automation browser is only ever a web page
        view = "window" if win else ("browser" if self.ws and self.tab else "")
        if view == "window":
            error = self.shot_error
        elif view == "browser":
            error = self.error or self.shot_error
        else:
            error = ("CTMS is not open in your Edge - open it there as normal; the bridge finds its window "
                     "by itself.")
        st = {"attached": bool(view), "view": view, "browser": self.browser, "tabs": self.tabs,
              "tab_title": win["title"] if win else (self.tab or {}).get("title", ""),
              "tab_url": "" if win else redact_url((self.tab or {}).get("url", "")),
              "window": ({"found": True, "title": win["title"][:120], "kind": win["kind"], "java": win["java"],
                          "showing": bool(win["ie_showing"] or win["kind"] == "java"
                                          or (win["kind"] == "page" and win["content"])),
                          "minimized": win["minimized"], "foreground": win["foreground"]}
                         if win else {"found": False}),
              "target": self.target,
              "mode": "act" if self.allow_control and self.armed else "observe",
              "control": self.allow_control,
              "net": self.net_on, "net_count": self.net_count,
              "error": error, "version": VERSION,
              "code": code_label(), "code_at": ctms_update.current().get("at", ""),
              "dialog": f"{d.get('type')}: {d.get('message', '')}"[:300] if d else "",
              "autostart": autostart_on(),
              "match": self.match,
              "machine": platform.node(),
              "filing": shared_folder.state(),
              # how long since anyone touched this PC - so a job can wait until CTMS is free, never take it from him
              "idle": _idle_now()}
        if self.rolled_back:
            rb = self.rolled_back
            st["rolled_back"] = (f"{rb.get('branch')} {str(rb.get('commit') or '')[:7]} was rolled back "
                                 f"{rb.get('at', '')}: {rb.get('reason', '')}")[:300]
        if self.net_count != self.net_sent:
            st["net_tail"] = [{k: e.get(k, "") for k in ("at", "method", "url", "status", "type", "mime")}
                              for e in self.net if e.get("type") in _NET_SHOWN][-15:]
        if not self.screens_sent:
            st["screens"] = [[label, what] for label, what in SCREENS]
        return st

    def checked_in(self, st, resp):
        if "net_tail" in st:
            self.net_sent = st["net_count"]
        if "screens" in st:
            self.screens_sent = True
        if resp.get("resync"):          # the dashboard restarted and forgot
            self.screens_sent, self.net_sent, self.shot_hash = False, -1, None
        self.long_poll = bool(resp.get("long"))
        watched = bool(resp.get("watch"))
        if watched != self.watched:
            say("The CTMS page is open on the dashboard - sending pictures." if watched
                else "Nobody is watching any more - pictures stopped.")
            self.watched = watched
        armed = bool(resp.get("control"))
        # kept only while it is on: switched off, run out or Stop, and it is gone for good
        self.ticket = str(resp.get("ticket") or "")[:200] if armed else ""
        if armed != self.armed:
            self.armed = armed
            log("control", on=armed)
            if self.allow_control:
                say("Claude can act in CTMS now - switched on from the dashboard." if armed
                    else "Claude can no longer act in CTMS (switched off, timed out, or Stop).")
            elif armed:
                say("The dashboard switched 'Claude can act' on, but this PC is observe only "
                    "(python ctms_bridge.py --allow-control to allow it).")
        if not self.confirmed:
            # a check-in got through: an update that brought us here is proven
            self.confirmed = True
            if ctms_update.confirm():
                say(f"Update in place and checking in: running {code_label()}.")
                log("update_confirmed", code=code_label())


def run(bridge, desk):
    down_since, rejected = None, False
    while True:
        t0 = time.time()
        bridge.refresh()
        bridge.scan_window()
        st = bridge.state()
        # The dashboard holds a check-in open until there is something to do,
        # so a command lands in well under a second without polling hard -
        # except while pictures are due, when it must come back in time.
        wait = (max(0.0, SHOT_EVERY - (time.time() - bridge.shot_at))
                if bridge.watched and (bridge.ws or bridge.win) else WAIT_IDLE)
        try:
            resp = desk.post("/api/ctms/poll", {"state": st, "wait": round(wait, 2),
                                                "watched": bridge.watched, "armed": bridge.armed,
                                                "ticket": bridge.ticket},
                             timeout=wait + 25)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                if not rejected:
                    say("The dashboard no longer accepts this bridge - its key has changed. "
                        "Run:  python ctms_bridge.py --setup")
                    log("rejected")
                rejected = True
                time.sleep(30)
                continue
            if down_since is None:
                say(f"The dashboard answered HTTP {e.code} - retrying.")
                down_since = time.time()
            time.sleep(5)
            continue
        except Exception as e:
            if down_since is None:
                say(f"Can't reach the dashboard ({type(e).__name__}) - retrying every few seconds.")
                down_since = time.time()
            time.sleep(5)
            continue
        if down_since:
            say("Back in touch with the dashboard.")
            down_since = None
        rejected = False
        bridge.checked_in(st, resp)
        acted = bool(resp.get("stop") or resp.get("cmd"))
        if resp.get("stop"):
            bridge.stop()
        if resp.get("cmd"):
            bridge.handle(resp["cmd"])
            if bridge.restart_after:
                log("restart", reason="update", code=code_label())
                bridge._detach()
                return RESTART
        if bridge.watched and (bridge.ws or bridge.win) and time.time() - bridge.shot_at >= SHOT_EVERY:
            try:
                bridge.send_shot()
            except Exception as e:
                if not isinstance(e, RuntimeError):
                    bridge.shot_error = friendly(e)
                    bridge.shot_at = time.time() + 4
        bridge.drain()
        if acted:
            continue    # check straight back in: the dashboard sees the change now, not a poll later
        if not bridge.long_poll:
            # an older dashboard answers at once - do not spin against it
            time.sleep(max(0.15, (POLL_WATCHED if bridge.watched else POLL_IDLE) - (time.time() - t0)))


# ---- setup -------------------------------------------------------------------
def probe_summary(p):
    """The probe in one line, for the activity list."""
    w, j, ab = p.get("windows") or [], p.get("java") or {}, p.get("access_bridge") or {}
    parts = [f"CTMS's window: {w[0]['title'][:60] or '?'} ({w[0]['kind']}, {w[0]['java']} Java part(s))"
             if w else "CTMS's window: not found"]
    parts.append(f"Java installs: {len(j.get('installs') or [])}; Access Bridge switched on: "
                 + ("yes" if j.get("switched_on") else "no"))
    if ab.get("tried"):
        parts.append("Access Bridge can read CTMS: " + ("yes" if ab.get("java_windows") else "no")
                     + (f" ({ab['error']})" if ab.get("error") else ""))
    return "; ".join(parts) + "."


def bridge_key(dash_key):
    """The bridge's own key. server.py derives the same one (CTMS_KEY)."""
    return hmac.new(dash_key.strip().encode(), b"ctms-bridge-v1", hashlib.sha256).hexdigest()


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if cfg.get("url") and cfg.get("key") else None
    except Exception:
        return None


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)


def remember_ctms_url(url):
    """Where CTMS lives, so the automation browser can open straight on it next time.

    Only the site and the app's own folder (https://host/app/): a deep link
    from yesterday's session tends to land on an error page, the app root on
    the sign-in page - which is where a new day starts anyway.
    """
    p = urlsplit(str(url or ""))
    if p.scheme not in ("http", "https") or not p.netloc:
        return
    seg = [s for s in p.path.split(";")[0].split("/") if s]
    start = f"{p.scheme}://{p.netloc}/" + (seg[0] + "/" if len(seg) > 1 else "")
    cfg = load_config()
    if cfg and cfg.get("ctms_url") != start:
        cfg["ctms_url"] = start
        try:
            save_config(cfg)
        except OSError:
            pass


# ---- starting by itself when he logs in -------------------------------------------
def startup_file():
    """A one-line .cmd in his own Startup folder: no admin rights, no registry, deleted to undo."""
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "CTMS bridge.cmd")


def autostart_on():
    return os.path.isfile(startup_file())


def set_autostart(on):
    path = startup_file()
    if on:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
            f.write("@rem Starts the CTMS bridge when you log in - made by its setup. Delete this file to stop that.\n")
            f.write(f'@start "CTMS bridge" /min "{sys.executable}" "{os.path.abspath(__file__)}"\n')
        log("autostart", on=True, file=path)
    elif os.path.isfile(path):
        os.remove(path)
        log("autostart", on=False)
    return path


def _cloud_json_url():
    try:
        with open(os.path.join(os.path.dirname(HERE), "cloud.json"), encoding="utf-8") as f:
            return json.load(f).get("url")
    except Exception:
        return None


def setup(old=None):
    print("\nCTMS bridge - setup. Three questions, once.\n")
    default = (old or {}).get("url") or _cloud_json_url() or DEFAULT_DESK
    url = (input(f"The Haulage Desk's address [{default}]: ").strip() or default).rstrip("/")
    desk = Desk(url, "")
    while True:
        dash = getpass.getpass("The key you log into the Haulage Desk with (it won't show as you type): ")
        if not dash.strip():
            print("  nothing typed - try again")
            continue
        key = desk.key = bridge_key(dash)
        try:
            desk.post("/api/ctms/poll", {"state": {"version": VERSION, "mode": "observe",
                                                   "machine": platform.node()}})
            print("  accepted.")
            break
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("  the dashboard did not accept that - check the key and try again.")
                continue
            if e.code == 404:
                print("  that dashboard is running older code with no CTMS bridge yet - "
                      "it needs redeploying first.")
                sys.exit(1)
            raise
        except Exception as e:
            print(f"  could not reach {url}: {type(e).__name__}: {e}")
            sys.exit(1)
    match = input("\nOptional: a word from the CTMS web address, so the bridge always picks the\n"
                  "CTMS tab even with others open (e.g. ctms). ENTER to skip: ").strip()
    allow = input("\nLet Claude click and type in CTMS - only while you switch 'Claude can act' on\n"
                  "from the dashboard, and never anything that books, saves or submits without\n"
                  "your go-ahead? [y/N]: ").strip().lower().startswith("y")
    cfg = {"url": url, "key": key, "match": match, "allow_control": allow}
    save_config(cfg)
    print(f"\nSaved to {CONFIG}.\nYour dashboard key itself was NOT saved - only a key made from it that opens "
          f"the bridge's own channel and nothing else (it cannot send email or run the desk).\n")
    log("setup", url=url, match=match, allow_control=allow)
    return cfg


def single_instance():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print("The CTMS bridge is already running on this PC - exiting.")
        sys.exit(0)
    return s


# ---- the two processes ------------------------------------------------------------
# The window you started runs a small SUPERVISOR; the bridge itself runs as its
# child. That split is what makes remote updates safe: an update ends the
# child (exit 75) and the supervisor - old code, already in memory - starts
# the new one. If the new one dies before it ever checks in, the supervisor
# puts the previous files back and starts that instead.
def supervise(args):
    cmd = [sys.executable, os.path.abspath(__file__), "--child", "--port", str(args.port),
           "--profile", args.profile] + (["--no-launch"] if args.no_launch else [])
    crashes = []
    while True:
        p = subprocess.Popen(cmd)
        try:
            while p.poll() is None:
                time.sleep(0.5)          # interruptible, unlike a bare wait() on Windows
        except KeyboardInterrupt:
            try:
                p.wait(timeout=15)
            except Exception:
                p.kill()
            return 0
        code = p.returncode
        if code == RESTART:
            say("Restarting on the updated code...")
            continue
        if code == 0:
            return 0
        if ctms_update.pending():
            say(f"The updated bridge stopped (exit code {code}) before it checked in - "
                f"putting the previous code back.")
            try:
                say(ctms_update.rollback(f"the updated bridge stopped with exit code {code} before checking in"))
                log("rolled_back", code=code)
            except Exception as e:
                say(f"Could not roll back ({e}). Run:  python update_from_github.py apply")
                return code
            continue
        crashes = [t for t in crashes if time.time() - t < 600] + [time.time()]
        if len(crashes) >= 3:
            say("The bridge has stopped three times in ten minutes - not restarting it again. "
                "What stopped it is above, and in ctms_bridge_crash.txt.")
            return code
        say(f"The bridge stopped unexpectedly (exit code {code}) - starting it again in 5s.")
        time.sleep(5)


def child(args):
    cfg = load_config()
    if not cfg:
        print("Not set up yet - run:  python ctms_bridge.py")
        return 2
    desk = Desk(cfg["url"], cfg["key"])
    ctms_window.dpi_aware()             # real pixels for CTMS's window, before anything measures it
    # CTMS needs Internet Explorer mode, which a browser opened for automation
    # cannot run - so the automation browser only opens if asked for
    # ("launch_browser": true in ctms_bridge.json), for other web pages.
    if cfg.get("launch_browser") and not port_open(args.port) and not args.no_launch:
        exe = find_browser("Edge") or find_browser("Chrome")
        if not exe:
            say("No Edge or Chrome found to open - start the automation browser yourself.")
        else:
            say("Opening the automation browser - its own window; your normal Edge is untouched.")
            launch(exe, port=args.port, profile=args.profile, url=cfg.get("ctms_url"))
            if wait_for_port(port=args.port):
                say("Open. Log into CTMS in THAT window; the bridge finds it by itself.")
            else:
                say("Its debug port never opened - group policy may block remote debugging here.")
    bridge = Bridge(desk, args.port, cfg.get("match"), cfg.get("allow_control"))
    log("start", version=VERSION, code=code_label(), url=desk.base, match=bridge.match,
        control=bridge.allow_control)
    say(f"Bridge v{VERSION}{' (' + code_label() + ')' if code_label() else ''} checking in with "
        f"{desk.base}. " + ("Claude may act when you switch it on from the dashboard."
                            if bridge.allow_control else "Observe only."))
    shared_folder.start(desk, say=say, log=log)
    say(shared_folder.describe())
    try:
        return run(bridge, desk)
    except KeyboardInterrupt:
        log("exit")
        bridge._detach()
        say("Stopped.")
        return 0
    except Exception:
        tb = traceback.format_exc()
        log("crash", error=tb[-3000:])
        try:
            with open(CRASH, "w", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')}  {code_label()}\n{tb}")
        except Exception:
            pass
        raise


def main():
    ap = argparse.ArgumentParser(description="CTMS on the dashboard, from the work PC.")
    ap.add_argument("--setup", action="store_true", help="ask the setup questions again")
    ap.add_argument("--allow-control", action="store_true",
                    help="let Claude act in CTMS while the dashboard switches it on")
    ap.add_argument("--observe-only", action="store_true", help="never act - look and record only")
    ap.add_argument("--rollback", action="store_true", help="put back the code the last update replaced")
    ap.add_argument("--autostart", choices=["on", "off"], help="start the bridge by itself when you log in")
    ap.add_argument("--no-launch", action="store_true", help="never open the automation browser")
    ap.add_argument("--port", type=int, default=DEBUG_PORT, help=argparse.SUPPRESS)
    ap.add_argument("--profile", default=PROFILE, help=argparse.SUPPRESS)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        return child(args)
    if args.autostart:
        path = set_autostart(args.autostart == "on")
        print(f"Starts by itself when you log in: {args.autostart} ({path})")
        return 0
    _lock = single_instance()   # noqa: F841 - held for the life of the supervisor
    if os.name == "nt":
        try:                    # so the window says what it is, however it was started
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("CTMS bridge")
        except Exception:
            pass
    if args.rollback:
        try:
            print(ctms_update.rollback("rolled back by hand on the work PC"))
        except ctms_update.UpdateError as e:
            print(f"Nothing rolled back: {e}")
    print(__doc__)
    cfg = load_config()
    if args.setup or not cfg:
        cfg = setup(cfg)
    if args.allow_control or args.observe_only:
        cfg["allow_control"] = bool(args.allow_control)
        save_config(cfg)
        log("control_setting", allow_control=cfg["allow_control"])
    say("This PC lets Claude act in CTMS while you switch it on from the dashboard." if cfg.get("allow_control")
        else "This PC is observe only - to let Claude act:  python ctms_bridge.py --allow-control")
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
