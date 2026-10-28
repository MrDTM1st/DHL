"""
CTMS's fields by name, through Java's Access Bridge - the channel screen
readers use with Oracle Forms. Read-only: nothing here clicks, types or
changes anything in CTMS.

A picture shows what CTMS looks like; the Access Bridge says what is THERE:
each field and button by name, what is in a field, which one has the cursor.
It asks Java itself, not the screen - so CTMS can be in front, behind other
windows or minimised, and his mouse and keyboard are never touched.

Two halves in one file, like ctms_window.py's live check:

  the reader   py32\\python.exe -I ctms_jab.py fields HWND...
               Runs under a 32-bit Python: the work PC's Java is 32-bit, and
               so is the only Access Bridge DLL it has. Walks CTMS's Java
               windows - the applet, and any Forms alert or list open in a
               window of its own - and prints one line of JSON. Its own
               process, so a fault in native code cannot take the bridge down.
  the bridge   read_fields(win) runs the reader and checks what comes back;
               setup() fetches the 32-bit Python it needs into py32\\ next to
               the bridge - python.org's own embeddable build, unpacked only if
               its SHA-256 matches the one pinned here.

Never read, never sent: what is in a password box, or in anything on a sign-in
(logon) screen - held back here, and checked again on the bridge's side before
anything leaves the PC. Every Java object the walk is handed is given back, so
CTMS's own Java does not fill up with them.

Once per PC, before the first read: Java's Access Bridge switched on for the
Windows user (jabswitch -enable, from Java's bin folder - or Control Panel >
Ease of Access Center > Use the computer without a display > Enable Java Access
Bridge), then CTMS closed and opened again: Java only looks for it as it starts.

Standard library only.
"""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

IS_WIN = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))
PY32_DIR = os.path.join(HERE, "py32")             # gitignored: the 32-bit Python the reader runs under
# python.org's embeddable Python, 32-bit. The fingerprint is of the very file whose
# programs were checked as signed by the Python Software Foundation (28/10).
PY32_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-win32.zip"
PY32_SHA256 = "084b9eb24cb848605c895d05b738fbc2572efc8b4c18c415a824065864a2b853"
PY32_SIZE = 9960069

LIMIT = 1500         # things sent back, at most (Planning with an order open runs to several hundred)
VISIT = 8000         # Java objects looked at, at most
KIDS = 500           # children of any one thing looked at, at most
SECONDS = 30         # the walk stops after this, and says it was cut short
VALUE_MAX = 2000     # characters of a field's contents: Special Instructions whole - the contact note goes at its END
# Never read what is in a field named like this...
PASSWORD = re.compile(r"pass ?(word|wd|code|phrase)?\b|\bpwd\b|\bpin\b|secret|credential", re.I)
# ...or what is in anything at all on a screen named like this
SIGN_IN = re.compile(r"\blog[- ]?[io]n\b|\bsign[- ]?[io]n\b|\bconnect\b|authenticat", re.I)
TITLED = ("frame", "dialog", "internal frame", "option pane", "alert", "window", "page tab")
INTERACTIVE = ("text", "password text", "push button", "toggle button", "check box", "radio button",
               "combo box", "spin box", "list", "list item", "menu", "menu item", "page tab", "table",
               "tree", "slider", "editbar", "hyperlink")
VALUED = ("text", "password text", "combo box", "spin box", "editbar", "paragraph")


class NotReady(RuntimeError):
    """Something this PC needs first - the message says what, and how."""


class SetupError(RuntimeError):
    pass


# ---- the reader: runs under a Python as many bits as CTMS's Java -------------------
def bridge_dll():
    """The Access Bridge DLL a Python of this bitness can load: Windows' own copy, else Java's."""
    want = "WindowsAccessBridge-64.dll" if struct.calcsize("P") == 8 else "WindowsAccessBridge-32.dll"
    windir = os.environ.get("WINDIR", r"C:\Windows")
    paths = [os.path.join(windir, "System32", want)]          # a 32-bit process is shown SysWOW64 here
    for pf in {os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432")} - {None}:
        java = os.path.join(pf, "Java")
        if os.path.isdir(java):
            paths += [os.path.join(java, n, "bin", want) for n in sorted(os.listdir(java), reverse=True)]
    return next((p for p in paths if os.path.isfile(p)), None)


class Api:
    """The Access Bridge's calls, as the reader uses them. Every Java object it
    hands out is a reference held inside CTMS's Java until release() gives it back."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt
        self.c, self.wt = ctypes, wt
        long_, short = 1024, 256                                 # AccessBridgePackages.h, in wchar_t

        class Info(ctypes.Structure):
            _fields_ = [("name", ctypes.c_wchar * long_), ("description", ctypes.c_wchar * long_),
                        ("role", ctypes.c_wchar * short), ("role_en_US", ctypes.c_wchar * short),
                        ("states", ctypes.c_wchar * short), ("states_en_US", ctypes.c_wchar * short),
                        ("indexInParent", ctypes.c_int), ("childrenCount", ctypes.c_int),
                        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int),
                        ("height", ctypes.c_int), ("accessibleComponent", wt.BOOL),
                        ("accessibleAction", wt.BOOL), ("accessibleSelection", wt.BOOL),
                        ("accessibleText", wt.BOOL), ("accessibleInterfaces", wt.BOOL)]

        class Version(ctypes.Structure):
            _fields_ = [(n, ctypes.c_wchar * short) for n in ("vm", "java_class", "java_dll", "win_dll")]

        class TextInfo(ctypes.Structure):
            _fields_ = [("charCount", ctypes.c_int), ("caretIndex", ctypes.c_int), ("indexAtPoint", ctypes.c_int)]

        self.Info, self.Version, self.TextInfo = Info, Version, TextInfo
        self.dll_path = bridge_dll()
        if not self.dll_path:
            raise RuntimeError("no Access Bridge DLL this Python can load - is Java's Access Bridge installed?")
        d = self.dll = ctypes.CDLL(self.dll_path)
        obj, vm, ptr = ctypes.c_int64, ctypes.c_long, ctypes.POINTER     # the -32/-64 DLLs pass objects as 64-bit
        for name, res, args in (
                ("Windows_run", None, []),
                ("isJavaWindow", wt.BOOL, [wt.HWND]),
                ("getAccessibleContextFromHWND", wt.BOOL, [wt.HWND, ptr(vm), ptr(obj)]),
                ("getTopLevelObject", obj, [vm, obj]),
                ("isSameObject", wt.BOOL, [vm, obj, obj]),
                ("getAccessibleContextInfo", wt.BOOL, [vm, obj, ptr(Info)]),
                ("getAccessibleChildFromContext", obj, [vm, obj, ctypes.c_int]),
                ("getAccessibleTextInfo", wt.BOOL, [vm, obj, ptr(TextInfo), ctypes.c_int, ctypes.c_int]),
                ("getAccessibleTextRange", wt.BOOL, [vm, obj, ctypes.c_int, ctypes.c_int, ptr(ctypes.c_wchar),
                                                     ctypes.c_short]),
                ("getVersionInfo", wt.BOOL, [vm, ptr(Version)]),
                ("releaseJavaObject", None, [vm, obj])):
            f = getattr(d, name)
            f.restype, f.argtypes = res, args
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        u.EnumWindows.argtypes = [self.enum_proc, wt.LPARAM]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ptr(wt.DWORD)]
        u.PeekMessageW.argtypes = [ptr(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        u.TranslateMessage.argtypes = [ptr(wt.MSG)]
        u.DispatchMessageW.argtypes = [ptr(wt.MSG)]
        d.Windows_run()
        self.pump(1.5)                  # while it finds the Java VMs that have the bridge on

    def pump(self, seconds):
        """The bridge talks through window messages - they only arrive inside a message loop."""
        msg, end, ref = self.wt.MSG(), time.time() + seconds, self.c.byref
        while True:
            while self.user32.PeekMessageW(ref(msg), None, 0, 0, 1):     # PM_REMOVE
                self.user32.TranslateMessage(ref(msg))
                self.user32.DispatchMessageW(ref(msg))
            if time.time() >= end:
                return
            time.sleep(0.02)

    def java_window(self, h):
        return bool(self.dll.isJavaWindow(h))

    def context(self, h):
        vm, ac = self.c.c_long(), self.c.c_int64()
        if self.dll.getAccessibleContextFromHWND(h, self.c.byref(vm), self.c.byref(ac)) and ac.value:
            return vm.value, ac.value
        return None

    def top(self, vm, ac):
        return self.dll.getTopLevelObject(vm, ac) or 0

    def same(self, vm, a, b):
        return bool(self.dll.isSameObject(vm, a, b))

    def info(self, vm, ac):
        i = self.Info()
        if not self.dll.getAccessibleContextInfo(vm, ac, self.c.byref(i)):
            return None
        return {"role": i.role_en_US, "name": i.name.strip(), "description": i.description.strip(),
                "states": {s for s in i.states_en_US.split(",") if s}, "children": max(0, i.childrenCount),
                "x": i.x, "y": i.y, "w": i.width, "h": i.height, "text": bool(i.accessibleText)}

    def child(self, vm, ac, k):
        return self.dll.getAccessibleChildFromContext(vm, ac, k) or 0

    def text(self, vm, ac, most):
        t = self.TextInfo()
        if not self.dll.getAccessibleTextInfo(vm, ac, self.c.byref(t), 0, 0):
            return None
        n = t.charCount
        if n <= 0:
            return ""
        m = min(n, most)
        buf = self.c.create_unicode_buffer(m + 2)
        if not self.dll.getAccessibleTextRange(vm, ac, 0, m - 1, buf, m + 1):
            return None
        return buf.value[:m] + ("..." if n > m else "")

    def release(self, vm, ac):
        if ac:
            self.dll.releaseJavaObject(vm, ac)

    def version(self, vm):
        v = self.Version()
        return v.vm if self.dll.getVersionInfo(vm, self.c.byref(v)) else ""

    def pid(self, h):
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(h, self.c.byref(pid))
        return pid.value

    def cls(self, h):
        buf = self.c.create_unicode_buffer(256)
        self.user32.GetClassNameW(h, buf, 256)
        return buf.value

    def title(self, h):
        buf = self.c.create_unicode_buffer(512)
        self.user32.GetWindowTextW(h, buf, 512)
        return buf.value

    def top_windows(self):
        """Java's own top-level windows - where a Forms alert or list of values opens."""
        found = []
        cb = self.enum_proc(lambda h, _: found.append(h) or True)
        self.user32.EnumWindows(cb, 0)
        return [h for h in found if h and self.cls(h).startswith("SunAwt")]


def flags(states, role):
    out = [s for s in ("focused", "selected", "checked", "expanded", "pressed") if s in states]
    if "enabled" not in states:
        out.append("disabled")
    if role in ("text", "editbar") and "editable" not in states:
        out.append("read-only")
    return out


def walk(api, vm, ac, out, ctx, win, level=0, sign_in=False, depth=0):
    """Depth first through one Java window; out gets everything worth naming."""
    if ctx["visited"] >= VISIT or len(out) >= LIMIT or time.time() > ctx["deadline"] or depth > 80:
        ctx["cut"] = True
        return
    ctx["visited"] += 1
    i = api.info(vm, ac)
    if not i or "visible" not in i["states"]:
        return                                  # a hidden canvas or tab page: not on the screen
    role, name, desc = i["role"], i["name"], i["description"]
    sign_in = sign_in or (role in TITLED and bool(SIGN_IN.search(name)))
    secret = (sign_in or role == "password text" or bool(PASSWORD.search(name)) or bool(PASSWORD.search(desc)))
    below = level
    if name or role in INTERACTIVE:
        e = {"n": len(out) + 1, "w": win, "lv": level, "r": role, "nm": name[:200]}
        if desc and desc != name:
            e["ds"] = desc[:200]
        if role in VALUED and (i["text"] or role == "password text"):
            if secret:
                e["secret"] = True              # never read: not even its length leaves Java
            else:
                v = api.text(vm, ac, VALUE_MAX)
                if v is not None:
                    e["v"] = v
        st = flags(i["states"], role)
        if st:
            e["st"] = st
        e["at"] = [i["x"], i["y"], i["w"], i["h"]]
        out.append(e)
        if "focused" in i["states"] and ctx["focus"] is None:
            ctx["focus"] = e["n"]
        below = level + 1
    for k in range(min(i["children"], KIDS)):
        kid = api.child(vm, ac, k)
        if not kid:
            continue
        try:
            walk(api, vm, kid, out, ctx, win, below, sign_in, depth + 1)
        finally:
            api.release(vm, kid)
        if ctx["cut"]:
            return
    if i["children"] > KIDS:
        ctx["cut"] = True


def read(hwnds, api=None):
    """Everything worth naming in CTMS's Java windows - the reader's whole answer."""
    t0 = time.time()
    api = api or Api()
    java = [h for h in hwnds if api.java_window(h)]
    if java:
        # Forms alerts and lists of values open as Java windows of their own, owned
        # by the applet rather than inside it: the same Java, so the same process
        pids = {api.pid(h) for h in java}
        java += [h for h in api.top_windows() if h not in java and api.pid(h) in pids and api.java_window(h)]
    out = {"ok": True, "java_windows": len(java), "windows": [], "elements": [],
           "reader": f"{struct.calcsize('P') * 8}-bit Python {sys.version.split()[0]}"}
    ctx = {"visited": 0, "cut": False, "deadline": t0 + SECONDS, "focus": None}
    tops = []
    try:
        for h in java:
            got = api.context(h)
            if not got:
                continue
            vm, ac = got
            top = api.top(vm, ac)
            if top:
                api.release(vm, ac)
            else:
                top = ac
            if any(v == vm and api.same(vm, t, top) for v, t in tops):
                api.release(vm, top)            # another part of a window already read
                continue
            tops.append((vm, top))
            title = api.title(h)
            out["windows"].append({"w": len(out["windows"]) + 1, "title": title[:120], "class": api.cls(h)})
            if not out.get("java"):
                out["java"] = api.version(vm)
            walk(api, vm, top, out["elements"], ctx, len(out["windows"]), sign_in=bool(SIGN_IN.search(title)))
    finally:
        for vm, t in tops:
            api.release(vm, t)
    out.update(cut=ctx["cut"], focus=ctx["focus"], visited=ctx["visited"], took=round(time.time() - t0, 2))
    return out


# ---- the bridge's side: runs in the bridge's own Python ----------------------------
def python32():
    """The Python the reader runs under, if this PC has it."""
    exe = os.environ.get("CTMS_PY32") or os.path.join(PY32_DIR, "python.exe")
    return exe if os.path.isfile(exe) else None


def _run(args, timeout):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=HERE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def bits(exe, timeout=30):
    """32 or 64 - how that Python runs - or None if it will not."""
    try:
        r = _run([exe, "-I", "-c", "import struct; print(struct.calcsize('P') * 8)"], timeout)
        return int(r.stdout.strip())
    except Exception:
        return None


def need_python():
    return NotReady(
        "Reading CTMS's fields needs a 32-bit Python on this PC (CTMS's Java is 32-bit), and it is not "
        f"here yet. Claude can fetch it with fields-setup: python.org's own embeddable Python "
        f"({PY32_URL.rsplit('/', 1)[1]}, {PY32_SIZE / 1e6:.1f} MB), unpacked into py32 next to the "
        "bridge only if it matches its known fingerprint.")


def switch_advice():
    """Why CTMS's Java did not answer, and what to do about it, in his words."""
    try:
        import ctms_window
        rep = ctms_window.java_report()
    except Exception:
        rep = {}
    if rep.get("switched_on"):
        return ("Java's Access Bridge is switched on, but CTMS's Java has not picked it up - it only looks as "
                "it starts. Close CTMS (and the Edge window it is in), wait a few seconds, then open it again.")
    jab = next((os.path.join(i["home"], "bin", "jabswitch.exe") for i in rep.get("installs") or []
                if i.get("jabswitch")), "jabswitch.exe")
    return ("Java's Access Bridge is switched off for your Windows user, so CTMS's Java does not answer it. "
            f"Switch it on once - in a Command Prompt:  \"{jab}\" -enable  (or Control Panel > Ease of Access "
            "Center > Use the computer without a display > tick Enable Java Access Bridge) - then close CTMS "
            "and open it again.")


def scrub(out):
    """The bridge's own check on the reader's answer, before any of it leaves the PC."""
    closed = {w.get("w") for w in out.get("windows") or [] if SIGN_IN.search(w.get("title") or "")}
    stack = []                                  # (level, on a sign-in screen) of what this sits inside
    for e in out.get("elements") or []:
        lv = e.get("lv", 0)
        while stack and stack[-1][0] >= lv:
            stack.pop()
        name = e.get("nm") or ""
        here = e.get("r") in TITLED and bool(SIGN_IN.search(name))
        sign_in = e.get("w") in closed or here or any(s for _, s in stack)
        if (sign_in or e.get("r") == "password text" or PASSWORD.search(name)
                or PASSWORD.search(e.get("ds") or "")):
            if e.pop("v", None) is not None or e.get("r") in VALUED:
                e["secret"] = True
        stack.append((lv, sign_in))
    return out


def read_fields(win, timeout=90):
    """CTMS's fields, read by the reader in its own 32-bit Python, checked again here."""
    if not IS_WIN:
        raise NotReady("Reading CTMS's fields works on Windows only.")
    py = python32()
    if not py:
        raise need_python()
    hwnds = [int(win["hwnd"])] + [int(h) for h in win.get("java_hwnds") or []]
    try:
        r = _run([py, "-I", os.path.abspath(__file__), "fields"] + [str(h) for h in hwnds], timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"CTMS's Java did not answer the Access Bridge within {timeout}s - it may be busy "
                           "(a search running?). Try again in a moment.")
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("{")]
    if not lines:
        raise RuntimeError(f"The fields reader stopped (exit {r.returncode}): {(r.stderr or '').strip()[-300:]}")
    out = json.loads(lines[-1])
    if not out.get("ok"):
        raise RuntimeError("The fields reader could not read CTMS: " + str(out.get("error"))[:300])
    if not out.get("java_windows"):
        raise NotReady(switch_advice())
    return scrub(out)


def describe(e):
    s = f"{e.get('r', '?')} '{e.get('nm') or ''}'"
    if e.get("secret"):
        return s + " (withheld)"
    return s + (f" = '{e['v']}'" if "v" in e else "")


DROPPED = re.compile(r"FRM-9210\d|network error or server failure", re.I)


def state_notes(out):
    """What the screen says about CTMS itself: its session dropped, or it is waiting at Logon."""
    notes = []
    if any(DROPPED.search(f"{e.get('nm') or ''} {e.get('v') or ''}") for e in out.get("elements") or []):
        notes.append("CTMS has lost its connection to the server (FRM-92102) - it needs reloading, and you "
                     "logging in again.")
    if any(SIGN_IN.search(w.get("title") or "") for w in out.get("windows") or []) or any(
            e.get("r") in TITLED and SIGN_IN.search(e.get("nm") or "") for e in out.get("elements") or []):
        notes.append("CTMS is at its Logon screen - you log in yourself; nothing in it was read.")
    return notes


def summary(out):
    els = out.get("elements") or []
    focus = next((e for e in els if e.get("n") == out.get("focus")), None)
    return (f"Read {len(els)} thing(s) in CTMS's {len(out.get('windows') or [])} Java window(s) through the Access "
            f"Bridge in {out.get('took', '?')}s - "
            + (f"the cursor is in {describe(focus)}." if focus else "no field reports the cursor (CTMS is not "
               "the active window, or nothing in it has focus).")
            + (f" CUT SHORT at {len(els)} - not everything was read." if out.get("cut") else "")
            + "".join(" " + n for n in state_notes(out)))


def setup(url=None):
    """Fetch the 32-bit Python the reader runs under. Returns what was done, in words."""
    if not IS_WIN:
        raise SetupError("The fields reader's Python is for Windows only.")
    exe = os.path.join(PY32_DIR, "python.exe")
    if os.path.isfile(exe) and bits(exe) == 32:
        return f"The 32-bit Python for reading CTMS's fields is already here ({PY32_DIR}) - nothing to do."
    import ctms_update                          # the bridge's side only: it knows this PC's proxy
    url = url or PY32_URL
    folder = tempfile.mkdtemp(prefix="ctms-py32-")
    stage = PY32_DIR + ".new"
    try:
        dest, h = os.path.join(folder, "py32.zip"), hashlib.sha256()
        try:
            with ctms_update.opener_for(url).open(url, timeout=180) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    if f.tell() + len(chunk) > 3 * PY32_SIZE:
                        raise SetupError(f"{url} sent far more than the Python it should be - stopped, "
                                         "nothing unpacked.")
                    h.update(chunk)
                    f.write(chunk)
        except SetupError:
            raise
        except Exception as e:
            raise SetupError(f"Could not download {url}: {type(e).__name__}: {e}")
        if h.hexdigest() != PY32_SHA256:
            raise SetupError(f"What came back from {url} is not the Python it should be (its fingerprint does "
                             "not match - a proxy page, most likely), so nothing was unpacked.")
        shutil.rmtree(stage, ignore_errors=True)
        with zipfile.ZipFile(dest) as z:
            for n in z.namelist():
                parts = n.replace("\\", "/").split("/")
                if n.startswith(("/", "\\")) or ":" in n or ".." in parts:
                    raise SetupError(f"The ZIP holds a path that would land outside its folder ({n[:60]}) - "
                                     "nothing unpacked.")
            z.extractall(stage)
        got = bits(os.path.join(stage, "python.exe"))
        if got != 32:
            raise SetupError(f"The Python unpacked but does not run as 32-bit here ({got or 'it would not run'}) "
                             "- not kept.")
        old = PY32_DIR + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(PY32_DIR):
            os.rename(PY32_DIR, old)
        os.rename(stage, PY32_DIR)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)
    return (f"Fetched python.org's 32-bit embeddable Python ({PY32_SIZE / 1e6:.1f} MB, fingerprint matched) "
            f"into {PY32_DIR}. Reading CTMS's fields can run now.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fields":
        try:
            print(json.dumps(read([int(x) for x in sys.argv[2:]])))
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
    else:
        print(__doc__)
