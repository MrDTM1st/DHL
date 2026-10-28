"""
Acting in CTMS's own window - step 2, the keyboard half.

CTMS is Oracle Forms in Internet Explorer mode inside his normal Edge. There is
no page to drive through a debugger there (ctms_drive.py is for web pages in the
automation browser, which cannot open CTMS at all). So the bridge works the
window the way a person does: it sends the same keystrokes he would, to the
window he already has open and logged in.

The rails, in this order, every time:
  1. This PC must allow acting (--allow-control) AND he must have switched
     "Claude can act" on from the dashboard. The bridge checks both before it
     ever calls in here; without them nothing below runs.
  2. CTMS must be the FOREGROUND window, confirmed right before the keys go.
     Keystrokes go to whatever is in front, so if CTMS cannot be brought to the
     front - another app is over it, or Windows will not allow the switch -
     nothing is sent. Keys are never sent "blind" into whatever happens to be
     focused.
  3. F10 (Forms Save/Commit) and Ctrl+S wait for his go-ahead (commit=True),
     which Claude only passes after he has said go in the chat.
  4. Keys that act on Windows or the browser rather than on CTMS - close the
     window, switch away, paste the clipboard (which could hold a password) -
     are refused.

Reading CTMS's fields by name (so the bridge could know a box is a password box,
or what a button says) needs Java's Access Bridge, which is the next piece.
Until then the sign-in box is kept off-limits by him and by the picture Claude
reads, not by code here - so this only runs while he is directing it.

Standard library (ctypes) only, Windows only - like the rest of work_pc\\.
"""
import ctypes
import os
import time

from ctms_drive import NeedsCommit, Refused   # the bridge already catches these

IS_WIN = os.name == "nt"
GA_ROOT = 2
SW_RESTORE = 9

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

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


def _send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise Refused("Windows did not accept the keystrokes - try again, or bring CTMS to the front yourself.")


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


def press(hwnd, spec, commit=False):
    """Send one key or chord to CTMS's window. Returns what was pressed."""
    mods, name, canon = _combo(spec)
    if canon in BLOCKED:
        raise Refused(f"{canon} is not allowed: it works Windows or the browser rather than CTMS "
                      f"(close it, switch away, or paste the clipboard).")
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


def type_text(hwnd, text, enter=False, commit=False):
    """Type text into whatever field has the cursor in CTMS. He positions the cursor; this types."""
    text = str(text or "")
    if "\n" in text or "\r" in text:
        raise Refused("No line breaks in typed text - use enter to press Enter afterwards.")
    _require_front(hwnd)
    units = []
    for ch in text:
        for u in text_units_for(ch):
            units += _unit(u)
    if units:
        _send(units)
    detail = f"Typed {text!r} into CTMS"
    if enter:
        detail += "; then " + press(hwnd, "enter", commit=commit)
    return detail


def text_units_for(ch):
    """The UTF-16 code unit(s) for a character (a surrogate pair above the BMP)."""
    code = ord(ch)
    if code <= 0xFFFF:
        return [code]
    code -= 0x10000
    return [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
