"""
CTMS screen capture - the walkthrough, without you saving anything by hand.

With the debug browser open (run start_here.py first) and CTMS logged in:

    python ctms_capture.py

It walks you through the screens the booking automation needs, in the order
you would meet them doing the job. Get each one on screen in the browser,
press ENTER here, and it snapshots: URL, title, full HTML including inside
frames, every field with its id/name/label/dropdown options, a PNG, and the
network calls the page made.

You drive CTMS. This only ever takes pictures - it never clicks, types or
submits. The one screen it asks you to fill in yourself is the booking form,
and it asks you NOT to submit it.

Guided rather than free-form on purpose: a walkthrough that comes back
without the filled-in booking form has to be done again, and the point is
that this takes one pass.

NOTE it records page text, field values, and (if you say yes) request URLs
and POST bodies from your own session - so it will contain order data.
Avoid capturing screens showing anything you would not want in your own
mailbox.
"""
import base64
import json
import os
import re
import struct
import sys
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "ctms_capture")
WS_URL = None


def http_json(path):
    with urllib.request.urlopen("http://127.0.0.1:9222" + path, timeout=6) as r:
        return json.load(r)


# ---- the smallest possible websocket client (stdlib sockets) ----
class WS:
    def __init__(self, url):
        import socket
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.s = socket.create_connection((host, port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self._buf = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0
        self.events = []

    def _frame_out(self, opcode, payload):
        head = bytes([0x80 | opcode])
        n, mask = len(payload), os.urandom(4)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, method, params=None):
        self._id += 1
        self._frame_out(0x1, json.dumps(
            {"id": self._id, "method": method, "params": params or {}}).encode())
        return self._id

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _frame_in(self):
        b1, b2 = self._read(2)
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read(8))[0]
        return b1 & 0x80, b1 & 0x0F, self._read(ln)

    def recv(self):
        # A CDP reply is usually one clean text frame, so the first version of
        # this just json.loads()'d whatever arrived. Two things break that, and
        # both break it mid-walkthrough with CTMS half-captured: the browser
        # sends a PING that has to be ponged or the socket dies, and a big
        # payload - a full-page screenshot is around a megabyte - arrives
        # FRAGMENTED across several frames that have to be joined first.
        buf = b""
        while True:
            fin, op, payload = self._frame_in()
            if op == 0x9:                      # ping -> pong, keep waiting
                self._frame_out(0xA, payload)
                continue
            if op == 0xA:                      # pong, ignore
                continue
            if op == 0x8:                      # close
                raise ConnectionError("the browser closed the debug socket")
            buf += payload                     # 0x1 text or 0x0 continuation
            if fin:
                return json.loads(buf.decode("utf-8", "replace"))

    def call(self, method, params=None):
        want = self.send(method, params)
        while True:
            msg = self.recv()
            if msg.get("id") == want:
                if msg.get("error"):
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            # Anything without our id is an EVENT. The first version dropped
            # these on the floor; they are how we find out whether CTMS posts
            # its booking to a JSON API (drive that - stable) or submits a form
            # (drive the DOM - brittle). That single fact decides the shape of
            # the whole automation, so keep them.
            if msg.get("method"):
                self.events.append(msg)

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return (r.get("result") or {}).get("value")

    def close(self):
        try:
            self._frame_out(0x8, b"")
        except Exception:
            pass
        try:
            self.s.close()
        except Exception:
            pass


# The fields are what selectors get written from, so a field the walk cannot
# see is a field the booking bot will not be able to fill. Enterprise screens
# put their real form in an IFRAME and their controls behind a SHADOW ROOT, and
# a plain document.querySelectorAll walks straight past both and reports a page
# with almost nothing on it. Descend into everything same-origin, and where a
# frame is cross-origin say so out loud rather than leaving a silent gap.
FIELDS_JS = """
(() => {
  const out = [], seen = new Set();
  const walk = (root, where) => {
    if (!root || seen.has(root)) return;
    seen.add(root);
    root.querySelectorAll('input,select,textarea,button').forEach(e => out.push({
      where,
      tag: e.tagName, type: e.type || '', id: e.id || '', name: e.name || '',
      label: (e.labels && e.labels[0] ? e.labels[0].innerText : '').slice(0,60),
      aria: e.getAttribute('aria-label') || '',
      placeholder: e.placeholder || '', value: (e.value || '').slice(0,60),
      text: (e.innerText || '').slice(0,40),
      required: !!e.required, disabled: !!e.disabled,
      options: e.tagName === 'SELECT' ? [...e.options].map(o => o.text).slice(0,40) : undefined
    }));
    root.querySelectorAll('*').forEach(e => {
      if (e.shadowRoot) walk(e.shadowRoot, where + ' > shadow:' + e.tagName.toLowerCase());
    });
    root.querySelectorAll('iframe,frame').forEach((f, i) => {
      const tag = where + ' > frame:' + (f.name || f.id || i);
      let d = null;
      try { d = f.contentDocument; } catch (err) { d = null; }
      if (d) walk(d, tag);
      else out.push({ where: tag, tag: 'FRAME', type: 'cross-origin', id: f.id || '',
                      name: f.name || '', label: '', placeholder: '',
                      value: (f.src || '').slice(0,120),
                      text: 'NOT READABLE FROM HERE (cross-origin frame)' });
    });
  };
  walk(document, 'page');
  return JSON.stringify(out);
})()
"""

# Same reason: outerHTML stops at the frame boundary, so a booking form living
# in a frame would arrive as a one-line <iframe> tag and nothing else.
HTML_JS = """
(() => {
  const parts = ['<!-- page: ' + location.href + ' -->\\n'
                 + document.documentElement.outerHTML];
  document.querySelectorAll('iframe,frame').forEach((f, i) => {
    let d = null;
    try { d = f.contentDocument; } catch (err) { d = null; }
    if (d) parts.push('\\n\\n<!-- frame[' + (f.name || f.id || i) + '] '
                      + (f.src || '') + ' -->\\n' + d.documentElement.outerHTML);
  });
  return parts.join('\\n');
})()
"""


def pick_page():
    pages = [t for t in http_json("/json") if t.get("type") == "page"]
    if not pages:
        print("No tabs found - is the debug browser open?")
        sys.exit(1)
    if len(pages) == 1:
        return pages[0]
    print("\nWhich tab?")
    for i, t in enumerate(pages):
        print(f"  [{i}] {t.get('title','?')[:55]} | {t.get('url','?')[:60]}")
    return pages[int(input("number: ").strip() or 0)]


# The exact screens CTMS_BOOKING_SPEC needs, in the order you would meet them
# doing the job. Guided rather than free-form because a walkthrough that comes
# back missing the filled-in booking form is a walkthrough that has to be done
# again - and the whole point is that this takes one pass.
SCREENS = [
    ("home", "the landing page after you log in"),
    ("order-search", "the order search screen, BEFORE you search"),
    ("search-results", "the results list for a real order"),
    ("order-open", "one order opened, showing its detail"),
    ("booking-form-empty", "the booking form, before you type anything"),
    ("booking-form-filled", "the SAME form filled in for a real job - do NOT submit yet."
                            "  *** the most important capture of the lot ***"),
    ("confirmation", "after you submit it by hand - the confirmation/reference"),
    ("booked-job", "an already-booked job reopened (the update flow)"),
    ("validation-error", "a form with a validation error, if one is easy to provoke"),
]


def capture(ws, label, n, want_network):
    """One screen: URL, title, HTML (frames included), fields, PNG, network."""
    ws.call("Runtime.enable")
    url = ws.evaluate("location.href")
    title = ws.evaluate("document.title")
    html = ws.evaluate(HTML_JS) or ""
    fields = json.loads(ws.evaluate(FIELDS_JS) or "[]")
    shot = None
    try:
        ws.call("Page.enable")
        shot = ws.call("Page.captureScreenshot", {"format": "png"}).get("data")
    except Exception as e:
        print(f"  (no screenshot: {type(e).__name__}: {e})")

    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)[:40]
    stamp = datetime.now().strftime("%H%M%S")
    base = os.path.join(OUTDIR, f"{n:02d}_{safe}_{stamp}")
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(base + "_fields.json", "w", encoding="utf-8") as f:
        f.write(json.dumps({"url": url, "title": title, "fields": fields}, indent=1))
    if shot:
        with open(base + ".png", "wb") as f:
            f.write(base64.b64decode(shot))

    calls = []
    if want_network:
        for ev in ws.events:
            if ev.get("method") == "Network.requestWillBeSent":
                r = ev["params"].get("request", {})
                calls.append({"method": r.get("method"), "url": (r.get("url") or "")[:300],
                              "postData": (r.get("postData") or "")[:2000],
                              "type": ev["params"].get("type")})
        ws.events.clear()
        if calls:
            with open(base + "_network.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(calls, indent=1))

    frames = sorted({f.get("where") for f in fields} - {"page"})
    print(f"  captured: {title} | {url}")
    print(f"  {len(fields)} field(s)"
          + (f" across {len(frames)} frame/shadow root(s)" if frames else "")
          + (f", {len(calls)} network call(s)" if calls else ""))
    return base


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    print(__doc__)

    want_network = input(
        "Also record the network calls CTMS makes? That tells us whether it\n"
        "posts bookings to an API (much more reliable to automate) or submits\n"
        "a form. It records URLs and POST bodies of YOUR OWN session - so it\n"
        "may include order data. [Y/n]: ").strip().lower() not in ("n", "no")

    page = pick_page()
    ws = WS(page["webSocketDebuggerUrl"])
    if want_network:
        try:
            ws.call("Network.enable")
            print("  network recording on")
        except Exception as e:
            print(f"  network recording unavailable: {type(e).__name__}: {e}")
            want_network = False

    n = 0
    print("\nWork through CTMS as normal. For each screen below, get it on")
    print("screen in the browser, then press ENTER here. 's' skips one.\n")
    try:
        for label, what in SCREENS:
            ans = input(f"  [{label}] {what}\n  ENTER to capture / s to skip: ").strip().lower()
            if ans == "s":
                print("  skipped\n")
                continue
            n += 1
            base = capture(ws, label, n, want_network)
            print(f"  -> {os.path.basename(base)}.*\n")

        while True:
            extra = input("Any other screen worth having? Name it, or ENTER to finish: ").strip()
            if not extra:
                break
            n += 1
            capture(ws, extra, n, want_network)
    finally:
        ws.close()
    print(f"\nDone. {n} screen(s) in {OUTDIR}")
    print("Zip that folder and email it to yourself, subject: CTMS walkthrough")
    return


if __name__ == "__main__":
    main()
