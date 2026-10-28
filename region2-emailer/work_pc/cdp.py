"""
The Chrome DevTools Protocol, with nothing but the standard library.

Shared by ctms_capture.py (the guided walkthrough at the keyboard) and
ctms_bridge.py (the same captures, driven from the dashboard). Both attach to
the Edge window opened with a debug port and a profile of its own - the one he
logs into CTMS with himself - so no password ever passes through any of this.

Installs nothing. On a managed work PC pip sits behind a proxy and TLS
inspection (see pip_here.py), and a tool that needs a package before it can
look at a web page is a tool that does not run on the day it is needed.
"""
import base64
import json
import os
import re
import socket
import struct
import time
import urllib.request

DEBUG_PORT = 9222

# The debug port is on THIS machine. urllib picks a proxy up from the registry
# on its own, and a corporate proxy asked for 127.0.0.1 either refuses or
# answers for itself - ProxyHandler({}) means "no proxy at all", which is the
# only correct route to localhost.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(path, port=DEBUG_PORT, timeout=6):
    with _LOCAL.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.load(r)


def pages(port=DEBUG_PORT):
    """The browser's tabs - not its service workers, extensions or iframes."""
    return [t for t in http_json("/json", port) if t.get("type") == "page"]


class WS:
    """The smallest websocket client CDP needs.

    A frame is only taken off the buffer once ALL of it has arrived. The first
    version read the two-byte header and then waited for the payload, so a
    read that timed out part-way left the header consumed and the next read
    started in the middle of a frame - garbage from then on. That was harmless
    in a walkthrough that only ever waits for answers, and fatal in a bridge
    that has to poll the socket for network events without blocking.
    """

    def __init__(self, url, timeout=15):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.timeout = timeout
        self.s = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("the browser closed the debug connection")
            buf += chunk
        head, rest = buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status + " ":
            raise ConnectionError(f"the browser refused the debug connection: {status}")
        self._buf = bytearray(rest)
        self._parts = b""          # a fragmented message being put back together
        self._id = 0
        self.events = []           # CDP events, when nobody set on_event
        self.on_event = None       # callable(msg) to take events as they arrive
        self.last_js_error = ""

    # ---- frames ----
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

    def _take_frame(self):
        """One complete frame off the buffer, or None if it has not all arrived."""
        b = self._buf
        if len(b) < 2:
            return None
        ln, off = b[1] & 0x7F, 2
        if ln == 126:
            if len(b) < 4:
                return None
            ln, off = struct.unpack(">H", bytes(b[2:4]))[0], 4
        elif ln == 127:
            if len(b) < 10:
                return None
            ln, off = struct.unpack(">Q", bytes(b[2:10]))[0], 10
        masked = b[1] & 0x80                    # servers never mask; be correct anyway
        need = off + (4 if masked else 0) + ln
        if len(b) < need:
            return None
        if masked:
            mask = bytes(b[off:off + 4])
            payload = bytes(x ^ mask[i % 4] for i, x in enumerate(b[off + 4:need]))
        else:
            payload = bytes(b[off:need])
        fin, op = b[0] & 0x80, b[0] & 0x0F
        del b[:need]
        return fin, op, payload

    def _message(self):
        """The next whole message from what is already buffered, or None.

        Two things break the naive one-frame-one-message reading, and both
        broke it mid-walkthrough: the browser sends a PING that has to be
        ponged or the socket dies, and a big payload - a full-page screenshot
        is around a megabyte - arrives FRAGMENTED across several frames.
        """
        while True:
            fr = self._take_frame()
            if fr is None:
                return None
            fin, op, payload = fr
            if op == 0x9:                       # ping -> pong
                self._frame_out(0xA, payload)
                continue
            if op == 0xA:                       # pong
                continue
            if op == 0x8:
                raise ConnectionError("the browser closed the debug socket")
            self._parts += payload              # 0x1 text or 0x0 continuation
            if fin:
                raw, self._parts = self._parts, b""
                return json.loads(raw.decode("utf-8", "replace"))

    def _fill(self, timeout):
        """Read what arrives within `timeout` seconds. False if nothing did."""
        self.s.settimeout(timeout)
        try:
            chunk = self.s.recv(1 << 20)
        except (socket.timeout, BlockingIOError):
            return False
        finally:
            self.s.settimeout(self.timeout)
        if not chunk:
            raise ConnectionError("the browser closed the debug socket")
        self._buf += chunk
        return True

    def _event(self, msg):
        if self.on_event:
            self.on_event(msg)
        else:
            self.events.append(msg)
            del self.events[:-5000]

    # ---- calls ----
    def send(self, method, params=None):
        self._id += 1
        self._frame_out(0x1, json.dumps(
            {"id": self._id, "method": method, "params": params or {}}).encode())
        return self._id

    def call(self, method, params=None, timeout=None, abort=None):
        """Send one command and wait for ITS answer, keeping events that pass by.

        Anything without our id is an EVENT - they are how we find out whether
        CTMS posts its booking to a JSON API (drive that - stable) or submits a
        form (drive the DOM - brittle), so they are kept, never dropped. A
        reply to an earlier call that timed out has nobody waiting for it and
        is let go.

        abort: checked after every event; when it turns true the call returns
        None without its answer. A click that opens a confirm() box is the
        case: the browser answers the click only once the box is closed, so
        waiting for that answer would wait for the very thing we must report.
        """
        limit = timeout or self.timeout
        want = self.send(method, params)
        deadline = time.time() + limit
        while True:
            msg = self._message()
            if msg is None:
                if abort and abort():
                    return None
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(f"{method}: the browser did not answer within {limit:g}s")
                self._fill(min(left, 0.25) if abort else left)
                continue
            if msg.get("id") == want:
                if msg.get("error"):
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            if msg.get("method"):
                self._event(msg)
                if abort and abort():
                    return None

    def drain(self, max_reads=200):
        """Hand over the events that have already arrived, without waiting."""
        for _ in range(max_reads):
            if not self._fill(0.0):
                break
        while True:
            msg = self._message()
            if msg is None:
                return
            if msg.get("method"):
                self._event(msg)

    def evaluate(self, expr, timeout=None, abort=None):
        """The value of a JS expression, or None if it threw (see last_js_error)."""
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True},
                      timeout=timeout, abort=abort)
        if r is None:
            self.last_js_error = "interrupted by a dialog box"
            return None
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            self.last_js_error = ((d.get("exception") or {}).get("description")
                                  or d.get("text") or "script error")[:300]
            return None
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
#
# A password box's value is never read out - not even its length - and nor is
# a hidden field that carries a session or anti-forgery token. Links and
# role=button elements are listed too: an enterprise screen's "Search" and
# "Book" are as often <a> as they are <button>.
FIELDS_JS = r"""
(() => {
  const SECRET = /pass|pwd|token|csrf|xsrf|viewstate|eventvalidation|session|nonce|secret|otp/i;
  const out = [], seen = new Set();
  const value = (e) => {
    const t = (e.type || '').toLowerCase();
    if (t === 'password') return e.value ? '[redacted]' : '';
    if (t === 'hidden' && SECRET.test((e.name || '') + ' ' + (e.id || ''))) return e.value ? '[redacted]' : '';
    return (e.value || '').slice(0, 60);
  };
  const walk = (root, where) => {
    if (!root || seen.has(root)) return;
    seen.add(root);
    root.querySelectorAll('input,select,textarea,button,a[href],[role=button]').forEach(e => {
      if (out.length >= 2000) return;
      out.push({
        where,
        tag: e.tagName, type: e.type || '', id: e.id || '', name: e.name || '',
        cls: (typeof e.className === 'string' ? e.className : '').slice(0, 80),
        label: (e.labels && e.labels[0] ? e.labels[0].innerText : '').slice(0, 60),
        aria: e.getAttribute('aria-label') || '',
        placeholder: e.placeholder || '', value: value(e),
        text: (e.innerText || '').trim().slice(0, 40),
        href: e.tagName === 'A' ? (e.getAttribute('href') || '').slice(0, 160) : undefined,
        required: !!e.required, disabled: !!e.disabled,
        options: e.tagName === 'SELECT' ? [...e.options].map(o => o.text).slice(0, 60) : undefined
      });
    });
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
                      value: (f.src || '').slice(0, 120),
                      text: 'NOT READABLE FROM HERE (cross-origin frame)' });
    });
  };
  walk(document, 'page');
  return JSON.stringify(out);
})()
"""

# Same reason: outerHTML stops at the frame boundary, so a booking form living
# in a frame would arrive as a one-line <iframe> tag and nothing else.
HTML_JS = r"""
(() => {
  const parts = ['<!-- page: ' + location.href + ' -->\n'
                 + document.documentElement.outerHTML];
  document.querySelectorAll('iframe,frame').forEach((f, i) => {
    let d = null;
    try { d = f.contentDocument; } catch (err) { d = null; }
    if (d) parts.push('\n\n<!-- frame[' + (f.name || f.id || i) + '] '
                      + (f.src || '') + ' -->\n' + d.documentElement.outerHTML);
  });
  return parts.join('\n');
})()
"""

# The words on the screen, frames included - the quickest thing to read when
# working out what a screen is for, and the thing a lookup will parse.
TEXT_JS = r"""
(() => {
  const parts = [document.body ? document.body.innerText : ''];
  document.querySelectorAll('iframe,frame').forEach((f, i) => {
    let d = null;
    try { d = f.contentDocument; } catch (err) { d = null; }
    if (d && d.body) parts.push('\n\n----- frame ' + (f.name || f.id || i) + ' -----\n' + d.body.innerText);
  });
  return parts.join('');
})()
"""

# Where the visible part of the page is, so a screenshot can be framed to it.
VIEW_JS = r"""
JSON.stringify({ w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1,
                 x: window.scrollX, y: window.scrollY, url: location.href, title: document.title,
                 visible: document.visibilityState })
"""
