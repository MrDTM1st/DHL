"""
CTMS screen capture - the walkthrough, without you saving anything by hand.

With the debug browser open (run start_here.py first) and CTMS logged in,
run this and just USE CTMS normally: search an order, open it, start a
booking. Every time you name a screen here it snapshots the current tab -
URL, title, full HTML, a PNG screenshot, and every form field on screen
including the ones inside frames and web components.

    python ctms_capture.py

Snapshots land in .\\ctms_capture\\ . Zip that folder and email it to
yourself, subject: CTMS walkthrough.

Standard library only. READ-ONLY: it takes pictures, it never clicks,
types, or submits anything.

NOTE the capture includes page text and field values - so before you
capture, avoid screens showing anything you would not want to email to
yourself (it goes to your own DHL mailbox, but check anyway).
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


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    print(__doc__)
    n = 0
    while True:
        label = input("\nName this screen (e.g. order-search) or ENTER to finish: ").strip()
        if not label:
            break
        page = pick_page()
        ws = WS(page["webSocketDebuggerUrl"])
        try:
            ws.call("Runtime.enable")
            url = ws.evaluate("location.href")
            title = ws.evaluate("document.title")
            html = ws.evaluate(HTML_JS) or ""
            fields = json.loads(ws.evaluate(FIELDS_JS) or "[]")
            shot = None
            try:
                # Replaces the Win+Shift+S step: a picture of the screen the
                # fields came from is what makes the field list readable later.
                ws.call("Page.enable")
                shot = ws.call("Page.captureScreenshot", {"format": "png"}).get("data")
            except Exception as e:
                print(f"  (no screenshot: {type(e).__name__}: {e})")
        finally:
            ws.close()

        n += 1
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)[:40]
        stamp = datetime.now().strftime("%H%M%S")
        base = os.path.join(OUTDIR, f"{n:02d}_{safe}_{stamp}")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(html)
        with open(base + "_fields.json", "w", encoding="utf-8") as f:
            f.write(json.dumps({"url": url, "title": title,
                                "fields": fields}, indent=1))
        if shot:
            with open(base + ".png", "wb") as f:
                f.write(base64.b64decode(shot))
        frames = sorted({f.get("where") for f in fields} - {"page"})
        print(f"  captured: {title} | {url}")
        print(f"  {len(fields)} field(s)" + (f" across {len(frames)} frame/shadow root(s)" if frames else ""))
        print(f"  -> {os.path.basename(base)}.html + _fields.json"
              + (" + .png" if shot else ""))
    print(f"\nDone. {n} screen(s) in {OUTDIR}")
    print("Zip that folder and email it to yourself, subject: CTMS walkthrough")


if __name__ == "__main__":
    main()
