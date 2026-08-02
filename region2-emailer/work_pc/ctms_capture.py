"""
CTMS screen capture - the walkthrough, without you saving anything by hand.

With the debug browser open (see ctms_attach_test.py) and CTMS logged in,
run this and just USE CTMS normally: search an order, open it, start a
booking. Every time you press ENTER here it snapshots the current tab -
URL, title, full HTML, and the form fields on screen.

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

    def send(self, method, params=None):
        self._id += 1
        payload = json.dumps({"id": self._id, "method": method, "params": params or {}}).encode()
        head = b"\x81"
        n, mask = len(payload), os.urandom(4)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        return self._id

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        b1, b2 = self._read(2)
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read(8))[0]
        return json.loads(self._read(ln).decode("utf-8", "replace"))

    def call(self, method, params=None):
        want = self.send(method, params)
        while True:
            msg = self.recv()
            if msg.get("id") == want:
                return msg.get("result", {})

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return (r.get("result") or {}).get("value")


FIELDS_JS = """
JSON.stringify([...document.querySelectorAll('input,select,textarea,button')].map(e => ({
  tag: e.tagName, type: e.type || '', id: e.id || '', name: e.name || '',
  label: (e.labels && e.labels[0] ? e.labels[0].innerText : '').slice(0,60),
  placeholder: e.placeholder || '', value: (e.value || '').slice(0,60),
  text: (e.innerText || '').slice(0,40),
  options: e.tagName === 'SELECT' ? [...e.options].map(o => o.text).slice(0,40) : undefined
})))
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
        ws.call("Runtime.enable")
        url = ws.evaluate("location.href")
        title = ws.evaluate("document.title")
        html = ws.evaluate("document.documentElement.outerHTML") or ""
        fields = ws.evaluate(FIELDS_JS) or "[]"
        n += 1
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)[:40]
        stamp = datetime.now().strftime("%H%M%S")
        base = os.path.join(OUTDIR, f"{n:02d}_{safe}_{stamp}")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(html)
        with open(base + "_fields.json", "w", encoding="utf-8") as f:
            f.write(json.dumps({"url": url, "title": title,
                                "fields": json.loads(fields)}, indent=1))
        print(f"  captured: {title} | {url}")
        print(f"  -> {os.path.basename(base)}.html + _fields.json")
    print(f"\nDone. {n} screen(s) in {OUTDIR}")
    print("Zip that folder and email it to yourself, subject: CTMS walkthrough")


if __name__ == "__main__":
    main()
