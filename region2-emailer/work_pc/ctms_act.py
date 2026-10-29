"""
Acting in CTMS's own window: the same keystrokes and mouse clicks he would make.

CTMS is Oracle Forms in Internet Explorer mode inside his normal Edge. There is
no page to drive through a debugger there (ctms_drive.py is for web pages in the
automation browser, which cannot open CTMS at all). So the bridge works the
window the way a person does: to the window he already has open and logged in it
sends the keys he would press, and clicks the point on it he would click.

The rails, in this order, every time:
  1. This PC must allow acting (--allow-control) AND he must have switched
     "Claude can act" on from the dashboard. The bridge checks both before it
     ever calls in here; without them nothing below runs.
  2. CTMS must be the FOREGROUND window, confirmed right before the keys or the
     click go. Input goes to whatever is in front, so if CTMS cannot be brought
     to the front - another app is over it, or Windows will not allow the switch
     - nothing is sent. Nothing is sent "blind" into whatever happens to be
     focused.
  3. A click (and both ends of a drag) lands by a FRACTION of CTMS's own
     picture (0..1 across and down), turned into a screen point inside CTMS's
     content area. A fraction outside that is refused, so the mouse can only
     ever act on CTMS, never on the browser frame, another window, or the desktop.
  4. F10 (Forms Save/Commit) and Ctrl+S wait for his go-ahead (commit=True),
     which Claude only passes after he has said go in the chat.
  5. Keys that act on Windows or the browser rather than on CTMS - close the
     window, switch away, paste the clipboard (which could hold a password) -
     are refused (paste_text pastes only text Claude itself supplies, and
     puts back what the clipboard held). Left click, double-click, left-button drag (to move a Forms
     window aside) and right-click. A right-click only OPENS CTMS's right-click
     menu - where Create Trip lives, so it was held back until he asked for it
     (29/10) - and every item on it is then a separate left click, picked off
     the picture while he directs. There is no right double-click.
     On the one allowed web page (the DigiHaul Job Tracker, ctms_window.
     PAGE_WORDS) the keys that would work the BROWSER instead - the address
     bar, reload, history, back/forward, other tabs - are refused as well.

Reading CTMS's fields by name (so the bridge could know a box is a password box,
or what a button says) needs Java's Access Bridge. Until that is available the
sign-in box is kept off-limits by him and by the picture Claude reads, not by
code here - so this only runs while he is directing it.

Standard library (ctypes) only, Windows only - like the rest of work_pc\\.
"""
import ctypes
import os
import time

from ctms_drive import NeedsCommit, Refused   # the bridge already catches these

IS_WIN = os.name == "nt"
GA_ROOT = 2
SW_RESTORE = 9

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
# GetSystemMetrics indices for the whole virtual desktop (all monitors)
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _INPUTunion(ctypes.Union):
        # All three, though only keys are sent: Windows checks INPUT is the size
        # of its largest member. With only the keyboard one here it came out 32
        # bytes, not 40, and SendInput refused every key (error 87, 28/10).
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
    user32.GetKeyboardLayout.restype = wintypes.HKL
    user32.VkKeyScanExW.argtypes = [wintypes.WCHAR, wintypes.HKL]
    user32.VkKeyScanExW.restype = ctypes.c_short
    user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HKL]
    user32.MapVirtualKeyExW.restype = wintypes.UINT
    user32.GetKeyState.argtypes = [ctypes.c_int]
    user32.GetKeyState.restype = ctypes.c_short
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

# name -> (virtual-key code, is it an "extended" key)
VK = {
    "enter": (0x0D, False), "return": (0x0D, False), "tab": (0x09, False),
    "escape": (0x1B, False), "esc": (0x1B, False), "backspace": (0x08, False),
    "space": (0x20, False), "delete": (0x2E, True), "insert": (0x2D, True),
    "home": (0x24, True), "end": (0x23, True), "pageup": (0x21, True), "pagedown": (0x22, True),
    "up": (0x26, True), "arrowup": (0x26, True), "down": (0x28, True), "arrowdown": (0x28, True),
    "left": (0x25, True), "arrowleft": (0x25, True), "right": (0x27, True), "arrowright": (0x27, True),
}
VK.update({f"f{i}": (0x6F + i, False) for i in range(1, 13)})   # F1=0x70 .. F12=0x7B
MOD_VK = {"shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12}

# F10 and Ctrl+S save the record in Forms - they wait for his go-ahead.
COMMIT = {"f10", "ctrl+s"}
# Keys that work the OS or the browser, not CTMS: closing it, switching away,
# pasting the work PC's clipboard (it could hold a password). Refused outright.
BLOCKED = {"alt+f4", "alt+tab", "ctrl+w", "ctrl+f4", "f11", "ctrl+esc", "ctrl+shift+esc",
           "ctrl+v", "shift+insert", "ctrl+shift+v", "alt+space", "ctrl+p", "ctrl+n", "ctrl+t"}
# On a web page (not CTMS's Java), these reach Edge itself: the address bar, reload, history, downloads,
# bookmarks, open/save, back/forward, the browser's menus, and other tabs. Refused there - keys stay on the page.
PAGE_BLOCKED = ({"ctrl+l", "alt+d", "f6", "shift+f6", "ctrl+e", "ctrl+k", "f5", "shift+f5", "ctrl+f5", "ctrl+r",
                 "ctrl+shift+r", "ctrl+h", "ctrl+j", "ctrl+d", "ctrl+o", "ctrl+s", "ctrl+u", "f12", "f7",
                 "alt+left", "alt+right", "alt+home", "alt+f", "alt+e", "ctrl+tab", "ctrl+shift+tab",
                 "ctrl+pageup", "ctrl+pagedown", "ctrl+shift+t", "ctrl+shift+n", "ctrl+shift+b",
                 "ctrl+shift+delete", "ctrl+shift+i", "ctrl+shift+j"}
                | {f"ctrl+{d}" for d in "123456789"} | {f"alt+{d}" for d in "123456789"})


def _send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise Refused(f"Windows did not accept the keystrokes (error {ctypes.get_last_error()}) - try again, "
                      f"or bring CTMS to the front yourself.")


def _key_event(vk, scan, flags):
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


def _unit(code):
    """A UTF-16 code unit typed as itself, whatever the keyboard layout is set to."""
    return [_key_event(0, code, KEYEVENTF_UNICODE),
            _key_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]


def _vk(vk, extended, up=False):
    flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if up else 0)
    return _key_event(vk, 0, flags)


def _thread(hwnd):
    return user32.GetWindowThreadProcessId(hwnd, None)


def to_front(hwnd):
    """Bring CTMS's window to the front and confirm it got there. False = it did not."""
    if not IS_WIN:
        return False
    hwnd = wintypes.HWND(int(hwnd))
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if _is_front(int(hwnd.value)):
        return True
    # Windows blocks a background app from stealing focus; attaching to the
    # current foreground thread's input queue is the allowed way to ask.
    me = kernel32.GetCurrentThreadId()
    fg_t, tgt_t = _thread(user32.GetForegroundWindow()), _thread(hwnd)
    attached = [t for t in {fg_t, tgt_t} if t and t != me and user32.AttachThreadInput(me, t, True)]
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for t in attached:
            user32.AttachThreadInput(me, t, False)
    time.sleep(0.06)
    return _is_front(int(hwnd.value))


def _is_front(hwnd):
    fg = user32.GetForegroundWindow()
    return bool(fg) and int(user32.GetAncestor(fg, GA_ROOT) or 0) == int(hwnd)


def _require_front(hwnd):
    if not to_front(hwnd):
        raise Refused("CTMS could not be brought to the front, so no keys were sent - another window is over "
                      "it, or Windows would not allow the switch. Click CTMS yourself and try again.")


def _combo(spec):
    """'ctrl+shift+f10' -> (['ctrl','shift'], 'f10', canonical string). Raises Refused."""
    parts = [p.strip().lower() for p in str(spec or "").split("+") if p.strip()]
    if not parts:
        raise Refused("Which key?")
    name, mods = parts[-1], []
    for m in parts[:-1]:
        if m not in MOD_VK:
            raise Refused(f"'{m}' is not a modifier key (ctrl, shift, alt).")
        mods.append("ctrl" if m == "control" else m)
    canon = "+".join(sorted(set(mods)) + [name])
    return mods, name, canon


def press(hwnd, spec, commit=False, page=False):
    """Send one key or chord to CTMS's window (page=True: the allowed web page). Returns what was pressed."""
    mods, name, canon = _combo(spec)
    if canon in BLOCKED:
        raise Refused(f"{canon} is not allowed: it works Windows or the browser rather than CTMS "
                      f"(close it, switch away, or paste the clipboard).")
    if page and canon in PAGE_BLOCKED:
        raise Refused(f"{canon} is not allowed on this page: it works the browser itself (address bar, reload, "
                      f"history, other tabs), not the page.")
    if canon in COMMIT and not commit:
        raise NeedsCommit(f"{canon.upper()} saves the record in CTMS. Not pressed - ask Delali, and re-run "
                          f"with commit if he says go.")
    if name in VK:
        vk, ext = VK[name]
    elif len(name) == 1 and name.isascii() and name.isprintable():
        vk, ext = ord(name.upper()), False
    else:
        raise Refused(f"'{spec}' is not a key the bridge knows.")
    _require_front(hwnd)
    seq = [_vk(MOD_VK[m], False) for m in mods]
    seq += [_vk(vk, ext), _vk(vk, ext, up=True)]
    seq += [_vk(MOD_VK[m], False, up=True) for m in reversed(mods)]
    _send(seq)
    return "Pressed " + "+".join([m.capitalize() for m in mods] + [name.capitalize()]) + " in CTMS"


def _mouse_event(dx, dy, flags):
    return INPUT(type=INPUT_MOUSE, u=_INPUTunion(mi=MOUSEINPUT(dx, dy, 0, flags, 0, 0)))


def _absolute(x, y):
    """A screen point as SendInput's 0..65535 coordinates over the whole virtual desktop."""
    vx, vy = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1
    nx = round((x - vx) * 65535 / (vw - 1)) if vw > 1 else 0
    ny = round((y - vy) * 65535 / (vh - 1)) if vh > 1 else 0
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _point(fx, fy, area, what="click"):
    """A fraction (across, down) of CTMS's picture as a screen point inside `area`.
    Refused unless both are 0..1 - so it can only ever be a point ON CTMS."""
    try:
        fx, fy = float(fx), float(fy)
    except (TypeError, ValueError):
        raise Refused(f"A {what} needs a point on the picture (across, down).")
    if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
        raise Refused(f"That point is off CTMS's picture, so nothing was done ({what}) - aim within the "
                      f"picture, and take a fresh one if the window has moved.")
    left, top, right, bottom = (int(v) for v in area)
    return (min(right - 1, left + round(fx * (right - left))),
            min(bottom - 1, top + round(fy * (bottom - top))))


def click(hwnd, fx, fy, area, double=False, right=False):
    """Click CTMS at a fraction (fx, fy) of its picture - 0..1 across and down.

    The fraction is turned into a screen point inside `area` (CTMS's content
    rectangle, in screen pixels). A fraction outside 0..1 is refused, so the
    click can only land on CTMS itself. He positions nothing; this is the whole
    pointer move and button, at the one point. right=True presses the right
    button instead, which opens CTMS's right-click menu there and nothing more.
    """
    if right and double:
        raise Refused("A right-click is a single press - there is no right double-click.")
    x, y = _point(fx, fy, area)
    _require_front(hwnd)
    nx, ny = _absolute(x, y)
    base = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    seq = [_mouse_event(nx, ny, MOUSEEVENTF_MOVE | base),
           _mouse_event(nx, ny, down | base),
           _mouse_event(nx, ny, up | base)]
    if double:                                  # a second press/release at the same point = a double-click
        seq += [_mouse_event(nx, ny, down | base),
                _mouse_event(nx, ny, up | base)]
    _send(seq)
    how = "Right-clicked" if right else "Double-clicked" if double else "Clicked"
    return f"{how} CTMS at {round(float(fx) * 100)}% across, {round(float(fy) * 100)}% down"


def drag(hwnd, start, end, area, steps=12):
    """Press the left button at one point of CTMS's picture, move to another and
    let go - how a Forms window (the Order Search card, say) is moved out of the
    way by its title bar. Both points are fractions of the picture, so both are
    on CTMS. The pointer travels in small steps, so Java sees a real drag."""
    x0, y0 = _point(start[0], start[1], area, "drag")
    x1, y1 = _point(end[0], end[1], area, "drag")
    _require_front(hwnd)
    base = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    nx, ny = _absolute(x0, y0)
    _send([_mouse_event(nx, ny, MOUSEEVENTF_MOVE | base), _mouse_event(nx, ny, MOUSEEVENTF_LEFTDOWN | base)])
    try:
        for i in range(1, steps + 1):
            time.sleep(0.02)
            nx, ny = _absolute(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
            _send([_mouse_event(nx, ny, MOUSEEVENTF_MOVE | base)])
    finally:
        _send([_mouse_event(nx, ny, MOUSEEVENTF_LEFTUP | base)])     # never leave the button held down
    return (f"Dragged in CTMS from {round(float(start[0]) * 100)}%,{round(float(start[1]) * 100)}% "
            f"to {round(float(end[0]) * 100)}%,{round(float(end[1]) * 100)}%")


def type_text(hwnd, text, enter=False, commit=False):
    """Type text into whatever field has the cursor in CTMS. He positions the cursor; this types."""
    text = str(text or "")
    if "\n" in text or "\r" in text:
        raise Refused("No line breaks in typed text - use enter to press Enter afterwards.")
    _require_front(hwnd)
    hkl = user32.GetKeyboardLayout(_thread(int(hwnd)))      # CTMS's own keyboard layout
    caps = bool(user32.GetKeyState(0x14) & 1)               # Caps Lock
    events = [e for ch in text for e in _typed(ch, hkl, caps)]
    if events:
        _send(events)
    detail = f"Typed {text!r} into CTMS"
    if enter:
        detail += "; then " + press(hwnd, "enter", commit=commit)
    return detail


def _typed(ch, hkl, caps):
    """The key presses that type one character the way his keyboard would - Java
    takes those as typing like any other. A Unicode packet only for a character
    his keyboard layout has no key for (or only an AltGr one)."""
    r = user32.VkKeyScanExW(ch, hkl) if hkl and len(ch) == 1 else -1
    if r == -1 or (r >> 8) & ~1:
        return [e for u in text_units_for(ch) for e in _unit(u)]
    vk, shift = r & 0xFF, bool((r >> 8) & 1)
    if caps and ch.isalpha():
        shift = not shift                       # Caps Lock on: Shift gives lower case
    scan = user32.MapVirtualKeyExW(vk, 0, hkl)
    ev = [_key_event(vk, scan, 0), _key_event(vk, scan, KEYEVENTF_KEYUP)]
    if shift:
        s = user32.MapVirtualKeyExW(0x10, 0, hkl)
        ev = [_key_event(0x10, s, 0)] + ev + [_key_event(0x10, s, KEYEVENTF_KEYUP)]
    return ev


def text_units_for(ch):
    """The UTF-16 code unit(s) for a character (a surrogate pair above the BMP)."""
    code = ord(ch)
    if code <= 0xFFFF:
        return [code]
    code -= 0x10000
    return [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]


# ---- paste: a block of Claude's own text in one go (29/10) ------------------------------------
# The tracker takes a row a booking, six cells across; typed cell by cell that was a dozen round trips
# each. Pasted, the rows of every job just booked go in at once ("just select the cells you need for all
# the jobs ... and then just copy and paste it"). Ctrl+V itself stays refused (BLOCKED): what the work
# PC's clipboard holds could be a password, so only text Claude supplies is ever pasted - put on the
# clipboard for the moment the paste takes, and the text that was there before put back.
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
PASTE_MAX = 6000

if IS_WIN:
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]


def _open_clipboard():
    for _ in range(20):                 # another program may hold it for a moment
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.05)
    return False


def _clip_text():
    """The text on the clipboard now, or None. Read only to be put back - never sent anywhere."""
    if not _open_clipboard():
        raise Refused("The clipboard is busy in another program, so nothing was pasted - try again.")
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else None
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def _clip_set(text):
    """Put text on the clipboard (None: leave it empty)."""
    if not _open_clipboard():
        raise Refused("The clipboard is busy in another program, so nothing was pasted - try again.")
    try:
        user32.EmptyClipboard()
        if text is None:
            return
        data = ctypes.create_unicode_buffer(text)
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, ctypes.sizeof(data))
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, ctypes.sizeof(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):   # the clipboard owns h once this succeeds
            kernel32.GlobalFree(h)
            raise Refused("Windows would not take the text onto the clipboard, so nothing was pasted.")
    finally:
        user32.CloseClipboard()


def paste_text(hwnd, text):
    """Paste Claude's own text where the cursor is - a block of cells in the tracker, rows split by line
    breaks and cells by tabs. The window must be in front, as for any key."""
    text = str(text or "")
    if not text.strip():
        raise Refused("Nothing to paste.")
    if len(text) > PASTE_MAX:
        raise Refused(f"That is more than {PASTE_MAX} characters - paste it in parts.")
    _require_front(hwnd)
    before = _clip_text()
    _clip_set(text.replace("\r\n", "\n").replace("\n", "\r\n"))
    try:
        _send([_vk(MOD_VK["ctrl"], False), _vk(ord("V"), False), _vk(ord("V"), False, up=True),
               _vk(MOD_VK["ctrl"], False, up=True)])
        time.sleep(1.0)                 # the page reads the clipboard as it handles the keys
    finally:
        _clip_set(before)
    rows = text.strip("\r\n").count("\n") + 1
    return f"Pasted {rows} row(s), {len(text)} characters"
