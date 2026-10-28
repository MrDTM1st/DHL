"""
CTMS's own window, in his normal Edge: found, pictured, and checked for Java's
accessibility bridge.

CTMS (Calidus TMS) is Oracle Forms. It runs in Internet Explorer mode inside
his normal Edge (the work profile, the briefcase), drawn by Java. A browser
started for automation cannot open IE mode at all - Edge says "turn off remote
debugging to open this site in Internet Explorer mode" - so the bridge cannot
reach CTMS through a browser. It works with CTMS's WINDOW instead, the way a
person would; at this step only by looking:

  find      the window CTMS is in: an Edge window with Internet Explorer
            content and a Java applet inside it, or a Java window of its own,
            or a window whose title says CTMS / Calidus / Oracle Forms. Only
            those are described - never the rest of what is open.
  picture   that window and nothing else, never the rest of the screen. Of an
            Edge window, only the CTMS part: not the tab strip (other tabs'
            titles) or the address bar. Taken straight from the window, so it
            can sit behind others; if Windows will not hand that over, taken
            off the screen - but only when CTMS is what is showing at every
            point of it.
  probe     what this PC has for reading CTMS's fields by name: Java, and
            Java's Access Bridge - the channel screen readers use with Oracle
            Forms. The live check runs in a separate Python process, so a
            fault in native code there cannot take the bridge down.

Read-only: nothing here clicks, types or changes anything on the PC.
Standard library (ctypes) only.
"""
import array
import json
import os
import struct
import subprocess
import sys
import time
import zlib

IS_WIN = os.name == "nt"
# Words in a window title that mean CTMS. Edge's title is the selected tab's.
TITLE_WORDS = ("ctms", "calidus", "oracle fusion middleware", "forms services", "frmservlet")
EDGE_CLASS = "Chrome_WidgetWin_1"
IE_CLASS = "Internet Explorer_Server"
PW_RENDERFULLCONTENT = 2
GA_ROOT = 2

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                    wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

_dpi_done = False


def dpi_aware():
    """Real pixels, not the scaled ones a laptop at 125% would report - or the
    picture is taken from the wrong place. Once per process."""
    global _dpi_done
    if _dpi_done or not IS_WIN:
        return
    _dpi_done = True
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):   # per-monitor v2
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ---- windows ---------------------------------------------------------------------
def _text(h):
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def _cls(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def _rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return [r.left, r.top, r.right, r.bottom]


def _frame(h):
    """The window as it is seen. GetWindowRect also counts the invisible resize
    borders around it - and reading the screen there picks up whatever is
    behind them: another window's text, in testing."""
    r = wintypes.RECT()
    try:
        if dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:   # EXTENDED_FRAME_BOUNDS
            return [r.left, r.top, r.right, r.bottom]
    except Exception:
        pass
    return _rect(h)


def _scale(h):
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(h)) / 96.0)
    except Exception:
        return 1.0


def _exe(h):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    ph = kernel32.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
    if not ph:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(ph, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(ph)


def _enum(parent=None):
    found = []
    cb = WNDENUMPROC(lambda h, _: found.append(h) or True)
    if parent is None:
        user32.EnumWindows(cb, 0)
    else:
        user32.EnumChildWindows(parent, cb, 0)
    return [h for h in found if h]


# Extra window classes to treat as CTMS's own - the tests' stand-in window only.
TEST_CLASSES = tuple(c for c in os.environ.get("CTMS_WINDOW_TEST_CLASS", "").split(",") if c)


def score(cls, title, ie, ie_showing, java):
    """How sure we are a top-level window is CTMS's; 0 = it is not, and it is not described.

    Only a window CTMS can actually be IN counts: Edge with Internet Explorer
    content or a Java applet inside, a Java window, Internet Explorer itself.
    A window whose title merely MENTIONS CTMS - an email about it, the
    bridge's own console - never does: its picture would not be CTMS's.
    """
    java_top = cls.startswith("SunAwt") or cls in TEST_CLASSES
    ie_frame = cls == "IEFrame"
    if not (java_top or ie_frame or ((cls == EDGE_CLASS) and (ie or java))):
        return 0
    titled = any(w in (title or "").lower() for w in TITLE_WORDS)
    return ((4 if ie and java else 0) + (3 if java_top else 0) + (2 if titled else 0)
            + (1 if ie else 0) + (1 if ie_showing else 0) + (1 if ie_frame else 0))


def find_windows():
    """The windows CTMS could be in, best first. Nothing else is described."""
    if not IS_WIN:
        return []
    dpi_aware()
    fg = user32.GetForegroundWindow()
    out = []
    for h in _enum():
        if not user32.IsWindowVisible(h):
            continue
        cls = _cls(h)
        title = _text(h)
        if not (cls in (EDGE_CLASS, "IEFrame") or cls.startswith("SunAwt") or cls in TEST_CLASSES):
            continue
        kids = _enum(h)
        kid_cls = [(k, _cls(k)) for k in kids]
        ie = [k for k, c in kid_cls if c == IE_CLASS]
        ie_showing = [k for k in ie if user32.IsWindowVisible(k)]
        java = [k for k, c in kid_cls if c.startswith("SunAwt")]
        s = score(cls, title, len(ie), len(ie_showing), len(java))
        if not s:
            continue                    # an ordinary browser window: never described
        content = None
        if ie_showing:                  # the largest Internet Explorer area on show is CTMS's page
            rects = [_rect(k) for k in ie_showing]
            content = max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        out.append({
            "hwnd": int(h), "title": title[:200], "class": cls, "process": _exe(h), "rect": _rect(h),
            "frame": _frame(h), "scale": _scale(h),
            "minimized": bool(user32.IsIconic(h)), "foreground": h == fg, "score": s,
            "kind": "edge" if cls == EDGE_CLASS else ("ie" if cls == "IEFrame" else "java"),
            "ie": len(ie), "ie_showing": bool(ie_showing), "content": content,
            "java": len(java), "java_classes": sorted({c for _, c in kid_cls if c.startswith("SunAwt")})[:8],
            "java_hwnds": [int(k) for k in java[:40]],
        })
    out.sort(key=lambda w: -w["score"])
    return out


# ---- pictures --------------------------------------------------------------------
def _grab(hwnd, rect, from_screen):
    """The window's pixels as BGRA, straight from the window or off the screen."""
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None, 0, 0
    sdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # top-down
    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(sdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not hbm:
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, sdc)
        return None, 0, 0
    old = gdi32.SelectObject(mdc, hbm)
    try:
        if from_screen:
            ok = gdi32.BitBlt(mdc, 0, 0, w, h, sdc, left, top, 0x00CC0020 | 0x40000000)   # SRCCOPY|CAPTUREBLT
        else:
            ok = user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
        data = ctypes.string_at(bits, w * h * 4) if ok else None
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, sdc)
    return data, w, h


def blank(bgra):
    """Not a real picture: all one colour, or a quarter of it never drawn at all
    (transparent black) - what Windows hands back for a window, or a part of
    one, that it would not draw."""
    px = array.array("I")
    px.frombytes(bgra)
    if not px:
        return True
    sample = px[::max(1, len(px) // 4000)]
    first = sample[0] & 0xFFFFFF
    if sum(1 for p in sample if p & 0xFFFFFF == first) > 0.98 * len(sample):
        return True
    return sum(1 for p in sample if p == 0) > 0.25 * len(sample)


def drawn_size(bgra, w, h):
    """How much of a straight-from-the-window picture the window really drew.

    A window that does not know about display scaling draws itself at its
    unscaled size, top left, and leaves the rest transparent - at 125% that is
    a picture four-fifths the size inside a black frame. Its alpha says where.
    (0, 0) = no alpha to go by."""
    px = array.array("I")
    px.frombytes(bgra)
    dw = max((x + 1 for y in (h // 4, h // 2, 3 * h // 4) for x in range(w) if px[y * w + x] >> 24), default=0)
    dh = max((y + 1 for x in (w // 4, w // 2, 3 * w // 4) for y in range(h) if px[y * w + x] >> 24), default=0)
    return dw, dh


def round_corners(bgra, w, h, r):
    """Grey out the rounded corners of a window read off the screen: Windows 11
    rounds them, so what is behind shows through a few pixels at each."""
    import math
    px = array.array("I")
    px.frombytes(bgra)
    grey, r = 0xFF808080, max(0, min(int(r), w // 2, h // 2))
    for y in range(r):
        cut = r - int(math.sqrt(max(0, r * r - (r - y) * (r - y))))
        for x in range(cut):
            for yy, xx in ((y, x), (y, w - 1 - x), (h - 1 - y, x), (h - 1 - y, w - 1 - x)):
                px[yy * w + xx] = grey
    return px.tobytes()


def crop(bgra, w, h, box):
    """The part of a BGRA picture inside box = (x0, y0, x1, y1), in the picture's own pixels."""
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(w, box[2]), min(h, box[3])
    if x1 <= x0 or y1 <= y0:
        return bgra, w, h
    px = array.array("I")
    px.frombytes(bgra)
    out = array.array("I")
    for y in range(y0, y1):
        out.extend(px[y * w + x0:y * w + x1])
    return out.tobytes(), x1 - x0, y1 - y0


def png(bgra, w, h):
    """A PNG of BGRA pixels - zlib and struct are all a PNG needs."""
    rgb = bytearray(w * h * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    stride = w * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def showing(root, area):
    """Is the window `root` what is on screen at every point of `area`? The
    screen is only ever read where this says yes - so nothing else is pictured.
    A 12 x 12 grid edge to edge: a notification or a corner of another window
    lying over CTMS is caught, not just one over its middle."""
    left, top, right, bottom = area
    steps = [0.004 + i * (0.992 / 11) for i in range(12)]
    for fx in steps:
        for fy in steps:
            pt = wintypes.POINT(int(left + (right - left) * fx), int(top + (bottom - top) * fy))
            h = user32.WindowFromPoint(pt)
            if not h or int(user32.GetAncestor(h, GA_ROOT) or 0) != int(root):
                return False
    return True


def picture(win):
    """(BGRA pixels, width, height, how) of CTMS - of its window and nothing else."""
    if win.get("minimized"):
        raise RuntimeError("CTMS's window is minimised - restore it (it can sit behind other windows).")
    rect = win["rect"]
    whole = win.get("kind") not in ("edge", "ie")
    if whole:
        area = win.get("frame") or rect
    else:
        if not win.get("content"):
            raise RuntimeError("CTMS is not the selected tab in its window - select the CTMS tab "
                               "(the window can sit behind others).")
        area = win["content"]           # CTMS's page only: not the tab strip or the address bar
    data, w, h = _grab(win["hwnd"], rect, from_screen=False)
    how = "from the window"
    if data is not None:                # judged only once cropped: the unscaled frame is not CTMS
        dw, dh = drawn_size(data, w, h)
        sx, sy = (dw / w, dh / h) if dw and dh and (dw < w - 2 or dh < h - 2) else (1.0, 1.0)
        data, w, h = crop(data, w, h, (round((area[0] - rect[0]) * sx), round((area[1] - rect[1]) * sy),
                                       round((area[2] - rect[0]) * sx), round((area[3] - rect[1]) * sy)))
    if data is None or blank(data):
        if not showing(win["hwnd"], area):
            raise RuntimeError("Windows would not hand over a picture of CTMS's window, and something else is "
                               "in front of it - bring CTMS to the front to let me see it.")
        data, w, h = _grab(win["hwnd"], area, from_screen=True)
        how = "off the screen, where CTMS is showing"
        if data is None:
            raise RuntimeError("Windows would not give a picture of CTMS's window.")
        if whole:
            data = round_corners(data, w, h, 8 * win.get("scale", 1.0))
    return data, w, h, how


def content_area(win):
    """The screen rectangle the picture covers - what a click's fraction is taken of.

    The same choice picture() makes: for CTMS in Edge it is the Internet Explorer
    content only (not the tab strip or the address bar); for a Java window of its
    own it is the whole frame.
    """
    whole = win.get("kind") not in ("edge", "ie")
    if whole:
        return win.get("frame") or win["rect"]
    if not win.get("content"):
        raise RuntimeError("CTMS is not the selected tab in its window - select the CTMS tab (it can sit "
                           "behind other windows), then try again.")
    return win["content"]


# ---- Java, and its Access Bridge -------------------------------------------------------
def _java_homes():
    """Every Java on this PC, from the registry and the usual folders."""
    homes = {}
    if not IS_WIN:
        return homes
    import winreg
    for base, bits in ((r"SOFTWARE\JavaSoft", 64), (r"SOFTWARE\WOW6432Node\JavaSoft", 32)):
        for product in ("Java Runtime Environment", "JRE", "Java Development Kit", "JDK"):
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + product)
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        ver = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, ver) as k:
                            home = winreg.QueryValueEx(k, "JavaHome")[0]
                    except OSError:
                        continue
                    homes.setdefault(os.path.normcase(home), {"home": home, "version": ver, "bits": bits})
    for pf, bits in ((os.environ.get("ProgramFiles", r"C:\Program Files"), 64),
                     (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), 32)):
        java = os.path.join(pf, "Java")
        if os.path.isdir(java):
            for n in os.listdir(java):
                home = os.path.join(java, n)
                if os.path.isfile(os.path.join(home, "bin", "java.exe")):
                    homes.setdefault(os.path.normcase(home), {"home": home, "version": n, "bits": bits})
    return homes


def _bridge_on(path):
    try:
        with open(path, encoding="latin-1") as f:
            return any("AccessBridge" in ln and not ln.lstrip().startswith("#") for ln in f)
    except OSError:
        return None


def java_report():
    """What this PC has for reading CTMS's fields by name. Files and settings only."""
    out = {"installs": [], "user_switch": None, "system_dlls": {}}
    for j in _java_homes().values():
        b = os.path.join(j["home"], "bin")
        j = dict(j, jabswitch=os.path.isfile(os.path.join(b, "jabswitch.exe")),
                 bridge_dlls=sorted(n for n in (os.listdir(b) if os.path.isdir(b) else [])
                                    if "accessbridge" in n.lower()),
                 jre_switch=_bridge_on(os.path.join(j["home"], "lib", "accessibility.properties"))
                 or _bridge_on(os.path.join(j["home"], "conf", "accessibility.properties")))
        out["installs"].append(j)
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name, folder in (("WindowsAccessBridge-64.dll", "System32"), ("WindowsAccessBridge-32.dll", "SysWOW64")):
        out["system_dlls"][name] = os.path.isfile(os.path.join(windir, folder, name))
    # jabswitch -enable writes this file; the Java in IE mode reads it when it starts
    out["user_switch"] = _bridge_on(os.path.join(os.path.expanduser("~"), ".accessibility.properties"))
    out["switched_on"] = bool(out["user_switch"] or any(j.get("jre_switch") for j in out["installs"]))
    return out


def processes():
    """How many of the processes that matter here are running - names only."""
    want = ("iexplore.exe", "jp2launcher.exe", "java.exe", "javaw.exe", "msedge.exe")
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=30)
    except Exception as e:
        return {"error": type(e).__name__}
    counts = dict.fromkeys(want, 0)
    for ln in r.stdout.splitlines():
        name = ln.split('","')[0].strip('"').lower()
        if name in counts:
            counts[name] += 1
    return counts


def _bridge_dll():
    """The Access Bridge DLL a Python of this bitness can load."""
    want = "WindowsAccessBridge-64.dll" if struct.calcsize("P") == 8 else "WindowsAccessBridge-32.dll"
    windir = os.environ.get("WINDIR", r"C:\Windows")
    paths = [os.path.join(windir, "System32", want)]
    paths += [os.path.join(j["home"], "bin", want) for j in _java_homes().values()]
    return next((p for p in paths if os.path.isfile(p)), None)


if IS_WIN:
    class AccessibleContextInfo(ctypes.Structure):
        # AccessBridgePackages.h: MAX_STRING_SIZE 1024, SHORT_STRING_SIZE 256, wchar_t
        _fields_ = [("name", ctypes.c_wchar * 1024), ("description", ctypes.c_wchar * 1024),
                    ("role", ctypes.c_wchar * 256), ("role_en_US", ctypes.c_wchar * 256),
                    ("states", ctypes.c_wchar * 256), ("states_en_US", ctypes.c_wchar * 256),
                    ("indexInParent", ctypes.c_int), ("childrenCount", ctypes.c_int),
                    ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                    ("accessibleComponent", ctypes.c_int), ("accessibleAction", ctypes.c_int),
                    ("accessibleSelection", ctypes.c_int), ("accessibleText", ctypes.c_int),
                    ("accessibleInterfaces", ctypes.c_int)]


def _jab_probe(hwnds):
    """Run in its own process (see jab_check): can the Access Bridge read CTMS's window?"""
    dll = _bridge_dll()
    if not dll:
        return {"tried": False, "why": "no Access Bridge DLL this Python can load"}
    jab = ctypes.CDLL(dll)
    jab.Windows_run.restype = None
    jab.Windows_run()
    # the bridge answers through window messages - pump them while it finds the Java VMs
    msg, end = wintypes.MSG(), time.time() + 2.5
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)
    jab.isJavaWindow.argtypes = [wintypes.HWND]
    jab.isJavaWindow.restype = wintypes.BOOL
    java = [h for h in hwnds if jab.isJavaWindow(h)]
    out = {"tried": True, "dll": dll, "java_windows": len(java), "of": len(hwnds)}
    if java:
        vm, ac = ctypes.c_long(), ctypes.c_int64()
        jab.getAccessibleContextFromHWND.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.c_long),
                                                     ctypes.POINTER(ctypes.c_int64)]
        jab.getAccessibleContextFromHWND.restype = wintypes.BOOL
        if jab.getAccessibleContextFromHWND(java[0], ctypes.byref(vm), ctypes.byref(ac)):
            info = AccessibleContextInfo()
            jab.getAccessibleContextInfo.argtypes = [ctypes.c_long, ctypes.c_int64,
                                                     ctypes.POINTER(AccessibleContextInfo)]
            jab.getAccessibleContextInfo.restype = wintypes.BOOL
            if jab.getAccessibleContextInfo(vm, ac, ctypes.byref(info)):
                out["sample"] = {"role": info.role_en_US, "name": info.name[:80],
                                 "children": info.childrenCount}
            jab.releaseJavaObject.argtypes = [ctypes.c_long, ctypes.c_int64]
            jab.releaseJavaObject(vm, ac)
    return out


def jab_check(hwnds, timeout=25):
    """Ask Java's Access Bridge, from a separate Python process, whether it can read CTMS's window."""
    if not IS_WIN:
        return {"tried": False, "why": "not Windows"}
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--jab-probe"]
                           + [str(int(h)) for h in hwnds], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"tried": True, "error": f"no answer within {timeout}s"}
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        return {"tried": True, "error": f"the check stopped (exit {r.returncode}): {(r.stderr or '').strip()[-200:]}"}
    return json.loads(lines[-1])


def probe():
    """Everything step 2 needs to know, in one read-only report."""
    wins = find_windows()
    best = wins[0] if wins else None
    jab = (jab_check([best["hwnd"]] + best["java_hwnds"]) if best and (best["java"] or best["kind"] == "java")
           else {"tried": False, "why": "no Java window found in CTMS to ask about"})
    return {"windows": [{k: v for k, v in w.items() if k != "java_hwnds"} for w in wins[:5]],
            "java": java_report(), "processes": processes(), "access_bridge": jab}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--jab-probe":
        try:
            print(json.dumps(_jab_probe([int(x) for x in sys.argv[2:]])))
        except Exception as e:
            print(json.dumps({"tried": True, "error": f"{type(e).__name__}: {e}"}))
    else:
        print(json.dumps(probe(), indent=1))
