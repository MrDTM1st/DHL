"""
A Teams message from the work PC - his asks (01/11): "with DHL NOC, instead of an email button, can we get like a Teams
message button ... I want you to send it on Teams on the work PC", then "build the quieter version": no keyboard and
no clipboard, so nothing he is doing on the work PC can get in the way. The dashboard's Send in Teams hands over who and
what, and each step is checked before the next:

  open    Teams' own link for a chat with that address, the text riding in it (msteams:/l/chat/0/0?users=..&message=..)
          - Teams opens the chat with the text in its message box; nothing else is opened
  check   a Teams window titled with that chat ("Chat | Rich Brumby | Microsoft Teams"), and its message box (found
          through UI Automation by its name) reading back the text and nothing else - an older draft there, another
          chat, or none in time stops it with nothing sent. Where the link leaves the box empty, the text is put in
          through UI Automation instead, and must read back the same
  send    Teams' own Send button pressed through UI Automation - never a key - and the box empty after; the window that
          was in front is put back, and a picture of the chat comes back

Opening the chat brings Teams forward for those few seconds - the link does that. Only ever Teams' own window, only the
chat the dashboard named, only the dashboard's text. A dry run does it all but Send, and empties the box again. Nothing
here runs without Look mum, no hands.

Standard library only, like everything else in work_pc\\.
"""
import os
import re
import time
from urllib.parse import quote

import ctms_window

IS_WIN = os.name == "nt"
EXES = ("ms-teams.exe", "teams.exe")
TITLE_END = "| microsoft teams"
OPEN_SECONDS = 25
FILL_SECONDS = 8                    # Teams puts the link's text in the box a moment after the chat shows
LINK_MAX = 2000                     # a longer link than this is not handed to Windows: the text goes in afterwards
BOX_TYPES = (50004, 50030)          # UI Automation's Edit and Document: what Teams' message box reads as
BUTTON = 50000
BOX_WORDS = ("type a message", "type a new message", "type your message")
FIND_NODES = 6000                   # UI Automation elements looked at, at most, for the box and the Send button
PATTERN_VALUE, IID_VALUE, VALUE_SET, VALUE_GET = 10002, "{A94CD8B1-0844-4CD6-9D2D-640537AB39E9}", 3, 4
PATTERN_LEGACY, IID_LEGACY, LEGACY_VALUE = 10018, "{828055AD-355B-4435-86D5-3B51C14A9B1B}", 8


class Stop(Exception):
    pass


def chat_link(email, text=""):
    """Teams' own link for a chat with that address - with the message for its box when there is one."""
    link = "msteams:/l/chat/0/0?users=" + quote(str(email or "").strip(), safe="@.")
    return link + ("&message=" + quote(str(text), safe="") if text else "")


def name_words(email, name=""):
    """The words a chat's title must carry for this person: their first name and the surname out of their address
    (rich.brumby@... -> rich, brumby) - a display name can be "Brumby, Rich" or carry a company after it."""
    local = str(email or "").split("@")[0].lower()
    words = [w for w in re.split(r"[._-]+", local) if len(w) > 1]
    first = str(name or "").strip().split(" ")[0].lower()
    if first and first not in words:
        words.insert(0, first)
    return words


def is_chat_with(title, words):
    """Is this Teams window title the chat with that person? "Chat | Rich Brumby | Microsoft Teams" """
    t = str(title or "").lower()
    if not t.endswith(TITLE_END) or not words:
        return False
    parts = [p.strip() for p in t[: -len(TITLE_END)].split("|") if p.strip()]
    chat = parts[-1] if parts else ""
    return all(w in chat for w in words)


def _squash(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def same_text(box, text):
    """Does what the box reads back hold the text? Line breaks and spacing as Teams keeps them do not matter."""
    want, got = _squash(text), _squash(box)
    return bool(want) and want[:200] in got


def holds_only(box, text):
    """Does the box hold the text and nothing else - no older draft before or after it?"""
    return bool(_squash(text)) and _squash(box) == _squash(text)


def is_box(name):
    return str(name or "").strip().lower().startswith(BOX_WORDS)


def empty(value, name=""):
    """Is the message box empty? An empty one reads back its own prompt ("Type a message") as its value."""
    v = _squash(value)
    return not v or v == _squash(name) or v in BOX_WORDS


def is_send(name):
    """Teams' own Send button - "Send" or "Send (Ctrl+Enter)" - never "Send feedback" and the like."""
    n = str(name or "").strip().lower()
    return n == "send" or n.startswith("send (")


def windows():
    """[(hwnd, title)] of Teams' own top-level windows that are up."""
    out = []
    for h in ctms_window._enum():
        try:
            if ctms_window._exe(h) in EXES and ctms_window.user32.IsWindowVisible(h):
                title = ctms_window._text(h)
                if title.lower().endswith(TITLE_END) or title.lower() == "microsoft teams":
                    out.append((h, title))
        except Exception:
            continue
    return out


def find(s, hwnd, match, kinds=(), cap=FIND_NODES):
    """The first element in Teams' window whose name `match` passes (and of one of `kinds`, if given), walking the
    window breadth first -> (element or None, [names of the edit boxes and buttons seen])."""
    seen, level, names = 0, [s.element(hwnd)], []
    while level and seen < cap:
        deeper = []
        for el in level:
            for child in s.children(el):
                seen += 1
                kind = s.control_type(child)
                if kind in BOX_TYPES + (BUTTON,):              # edit boxes, documents and buttons: named back
                    nm = s.name(child)
                    if nm and len(names) < 40:
                        names.append(nm[:60])
                    if (not kinds or kind in kinds) and match(nm):
                        return child, names
                deeper.append(child)
                if seen >= cap:
                    break
        level = deeper
    return None, names


def _focused(s):
    """The name of what has the keyboard focus - for saying what was there instead."""
    el = s._get(s.uia, 8)                                       # IUIAutomation::GetFocusedElement
    return s.name(el) if el else ""


def _pattern(s, el, pattern, iid):
    import ctypes
    from ctms_tabs import GUID, _guid
    return s._get(el, 14, (ctypes.c_int, pattern), (ctypes.POINTER(GUID), _guid(iid)))


def _value(s, el):
    for pattern, iid, slot in ((PATTERN_VALUE, IID_VALUE, VALUE_GET), (PATTERN_LEGACY, IID_LEGACY, LEGACY_VALUE)):
        try:
            pat = _pattern(s, el, pattern, iid)
            if pat:
                return s._text(pat, slot)
        except OSError:
            continue
    return ""


def _set_value(s, el, text):
    """Put text in the box through UI Automation's Value pattern - no keys, no clipboard. False = it would not."""
    import ctypes
    from ctms_tabs import _fn, oleaut32
    try:
        pat = _pattern(s, el, PATTERN_VALUE, IID_VALUE)
    except OSError:
        return False
    if not pat:
        return False
    oleaut32.SysAllocString.argtypes = [ctypes.c_wchar_p]
    oleaut32.SysAllocString.restype = ctypes.c_void_p
    b = oleaut32.SysAllocString(str(text))
    try:
        _fn(pat, VALUE_SET, ctypes.c_void_p)(pat, b)
        return True
    except OSError:
        return False
    finally:
        oleaut32.SysFreeString(b)


def _picture(hwnd):
    import base64
    rect = ctms_window._rect(hwnd)
    data, w, h = ctms_window._grab(hwnd, rect, from_screen=False)
    if data is None or ctms_window.blank(data):
        data, w, h = ctms_window._grab(hwnd, rect, from_screen=True)
    if data is None:
        return {}
    return {"kind": "teams", "img": base64.b64encode(ctms_window.png(data, w, h)).decode(), "mime": "image/png",
            "img_w": w, "img_h": h}


def _box(s, hwnd, who):
    """Teams' message box in that chat -> (element, its name). Stop when it cannot be found."""
    names = []
    for _ in range(3):                                           # Teams draws its page for UI Automation on asking
        box, names = find(s, hwnd, is_box)
        if box:
            return box, s.name(box)
        time.sleep(1.0)
    raise Stop(f"Teams' message box could not be found in the chat with {who} (the cursor is on "
               f"{_focused(s) or 'nothing'!r}; boxes and buttons seen: {'; '.join(names[:15]) or 'none'}) - nothing sent.")


def _fill_and_send(s, hwnd, who, text, dry):
    box, label = _box(s, hwnd, who)
    got, end = "", time.time() + FILL_SECONDS
    while time.time() < end:
        got = _value(s, box)
        if not empty(got, label):
            break
        time.sleep(0.5)
    if empty(got, label):                                        # the link left the box empty: the text another way
        if not _set_value(s, box, text):
            raise Stop(f"Teams left the message box with {who} empty and would not take the text through UI "
                       "Automation - nothing sent.")
        time.sleep(0.7)
        got = _value(s, box)
    if not holds_only(got, text):
        raise Stop(f"The message box with {who} reads {got[:80]!r} - not just this message (an older draft, or Teams "
                   "changed it). Nothing sent: look at the chat in Teams.")
    if dry:
        _set_value(s, box, "")
        time.sleep(0.7)
        left = _value(s, box)
        return {"ok": empty(left, label),
                "said": f"Dry run: the chat with {who} opened with the text in its message box, read back exactly - "
                        "emptied again, nothing sent." + ("" if empty(left, label) else
                                                         " BUT the text is still in the box - empty it in Teams.")}
    button, _ = find(s, hwnd, is_send, kinds=(BUTTON,))
    if not button:
        raise Stop(f"Teams' Send button could not be found in the chat with {who} - the text is in the box, NOT sent.")
    if not s.invoke(button):
        raise Stop(f"Teams' Send button would not press in the chat with {who} - the text is in the box, NOT sent.")
    time.sleep(1.5)
    left = _value(s, _box(s, hwnd, who)[0])                      # the box afresh: Teams redraws it once sent
    if not empty(left, label):
        return {"ok": False, "said": f"Send was pressed in the chat with {who} but the box still holds text - look "
                                     "at Teams before sending again."}
    return {"ok": True, "said": f"Sent to {who} on Teams."}


def send(email, name, text, dry=False):
    """The message to that person in the work PC's Teams -> {"ok", "said", "payload"}. Stop says where it stopped."""
    import ctms_act
    import ctms_tabs
    text = str(text or "").strip()
    words = name_words(email, name)
    if not (re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", str(email or "").strip()) and words):
        raise Stop("No address to message.")
    if not text or len(text) > 4000:
        raise Stop("No text to send, or far too long for a chat.")
    who = " ".join(w.capitalize() for w in words)
    before = ctms_window.user32.GetForegroundWindow()            # put back once it is done
    link = chat_link(email, text)
    hwnd = None
    try:
        os.startfile(link if len(link) <= LINK_MAX else chat_link(email))
        end = time.time() + OPEN_SECONDS
        while time.time() < end and not hwnd:
            hwnd = next((h for h, t in windows() if is_chat_with(t, words)), None)
            if not hwnd:
                time.sleep(0.5)
        if not hwnd:
            seen = "; ".join(t for _, t in windows()) or "no Teams window"
            raise Stop(f"Teams did not open the chat with {who} in time (it shows: {seen}) - nothing sent.")
        hr = ctms_tabs.ole32.CoInitializeEx(None, 0)
        try:
            s = ctms_tabs._Session()
            try:
                out = _fill_and_send(s, hwnd, who, text, dry)
            finally:
                s.close()
        finally:
            if hr >= 0:
                ctms_tabs.ole32.CoUninitialize()
        out["payload"] = _picture(hwnd)
        return out
    finally:
        if before and hwnd and int(before) != int(hwnd):
            try:
                ctms_act.to_front(before)                        # the screen handed back as it was
            except Exception:
                pass
