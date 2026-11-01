"""
A Teams message from the work PC - his ask (01/11): "with DHL NOC, instead of an email button, can we get like a Teams
message button ... I want you to send it on Teams on the work PC." The dashboard's Send in Teams hands over who and
what; this opens that person's chat in the work PC's Teams (signed in as him), puts the text in, and sends it - each
step checked before the next:

  open    Teams' own link for a chat with that address (msteams:/l/chat/0/0?users=...) - nothing else is opened
  check   a Teams window titled with that chat ("Chat | Rich Brumby | Microsoft Teams"): any other chat, or none in
          time, stops it with nothing typed
  type    the box that has the cursor must be Teams' message box (UI Automation says what has the focus); the text
          is pasted (the clipboard put back after) and read back from the box
  send    Enter, and the box must read empty again - then a picture of the chat comes back

Only ever Teams' own window (ms-teams.exe / Teams.exe), only the chat the dashboard named, only the dashboard's text.
A dry run does all of it but Enter, and empties the box again. Nothing here runs without Look mum, no hands.

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
BOX_TYPES = (50004, 50030)          # UI Automation's Edit and Document: what Teams' message box reads as
PATTERN_VALUE, IID_VALUE, VALUE_GET = 10002, "{A94CD8B1-0844-4CD6-9D2D-640537AB39E9}", 4
PATTERN_LEGACY, IID_LEGACY, LEGACY_VALUE = 10018, "{828055AD-355B-4435-86D5-3B51C14A9B1B}", 8


class Stop(Exception):
    pass


def chat_link(email):
    return "msteams:/l/chat/0/0?users=" + quote(str(email or "").strip(), safe="@.")


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


def same_text(box, text):
    """Does what the box reads back hold the text? Line breaks and spacing as Teams keeps them do not matter."""
    squash = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().lower()     # noqa: E731
    want, got = squash(text), squash(box)
    return bool(want) and want[:200] in got


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


BOX_WORDS = ("type a message", "type a new message", "type your message")
FIND_NODES = 6000                    # UI Automation elements looked at, at most, for the box and the Send button


def _focused(s):
    """(control type, name) of what has the keyboard focus - for saying what was there instead."""
    el = s._get(s.uia, 8)                                       # IUIAutomation::GetFocusedElement
    return (s.control_type(el), s.name(el)) if el else (0, "")


def is_box(name):
    return str(name or "").strip().lower().startswith(BOX_WORDS)


def empty(value, name=""):
    """Is the message box empty? An empty one reads back its own prompt ("Type a message") as its value."""
    v = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return not v or v == re.sub(r"\s+", " ", str(name or "")).strip().lower() or v in BOX_WORDS


def is_send(name):
    """Teams' own Send button - "Send" or "Send (Ctrl+Enter)" - never "Send feedback" and the like."""
    n = str(name or "").strip().lower()
    return n == "send" or n.startswith("send (")


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
                if kind in BOX_TYPES + (50000,):              # edit boxes, documents and buttons: named back
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


def _set_focus(el):
    from ctms_tabs import _fn
    _fn(el, 3)(el)                                              # IUIAutomationElement::SetFocus


def _value(s, el):
    import ctypes
    from ctms_tabs import GUID, _fn, _guid
    for pattern, iid, slot in ((PATTERN_VALUE, IID_VALUE, VALUE_GET), (PATTERN_LEGACY, IID_LEGACY, LEGACY_VALUE)):
        try:
            pat = s._get(el, 14, (ctypes.c_int, pattern), (ctypes.POINTER(GUID), _guid(iid)))
            if pat:
                return s._text(pat, slot)
        except OSError:
            continue
    return ""


def _keys(hwnd, *combos):
    """Chords to Teams, which must be in front for each: ("ctrl", "v"), ("return",) ..."""
    import ctms_act
    for combo in combos:
        if not ctms_act.to_front(hwnd):
            raise Stop("Teams could not be brought to the front, so no keys were sent.")
        *mods, key = combo
        vk, ext = ctms_act.VK[key] if key in ctms_act.VK else (ord(key.upper()), False)
        seq = [ctms_act._vk(ctms_act.MOD_VK[m], False) for m in mods]
        seq += [ctms_act._vk(vk, ext), ctms_act._vk(vk, ext, up=True)]
        seq += [ctms_act._vk(ctms_act.MOD_VK[m], False, up=True) for m in reversed(mods)]
        ctms_act._send(seq)
        time.sleep(0.25)


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
    os.startfile(chat_link(email))
    hwnd, end = None, time.time() + OPEN_SECONDS
    while time.time() < end and not hwnd:
        hwnd = next((h for h, t in windows() if is_chat_with(t, words)), None)
        if not hwnd:
            time.sleep(0.5)
    if not hwnd:
        seen = "; ".join(t for _, t in windows()) or "no Teams window"
        raise Stop(f"Teams did not open the chat with {who} in time (it shows: {seen}) - nothing typed.")
    if not ctms_act.to_front(hwnd):
        raise Stop("Teams could not be brought to the front - nothing typed.")
    time.sleep(1.5)                                              # the chat draws its message box
    hr = ctms_tabs.ole32.CoInitializeEx(None, 0)
    try:
        s = ctms_tabs._Session()
        try:
            box, names = None, []
            for _ in range(3):                                   # Teams draws its page for UI Automation on asking
                box, names = find(s, hwnd, is_box)
                if box:
                    break
                time.sleep(1.0)
            if not box:
                kind, label = _focused(s)
                raise Stop(f"Teams' message box could not be found in the chat with {who} (the cursor is on "
                           f"{label or 'nothing'!r}; boxes and buttons seen: {'; '.join(names[:15]) or 'none'}) - "
                           "nothing typed.")
            label = s.name(box)
            before = _value(s, box)
            if not empty(before, label):
                raise Stop(f"The message box with {who} already holds text ({before[:60]!r}) - left as it is, "
                           "nothing typed.")
            _set_focus(box)
            time.sleep(0.4)
            keep = ctms_act._clip_text()
            ctms_act._clip_set(text.replace("\r\n", "\n").replace("\n", "\r\n"))
            try:
                _keys(hwnd, ("ctrl", "v"))
                time.sleep(1.0)
            finally:
                ctms_act._clip_set(keep)
            typed = _value(s, box)
            if not same_text(typed, text):
                _keys(hwnd, ("ctrl", "a"), ("delete",))
                kind, label = _focused(s)
                raise Stop(f"The message box did not read back the text (it reads {typed[:60]!r}; the cursor is on "
                           f"{label or 'nothing'!r}) - emptied, nothing sent.")
            if dry:
                _keys(hwnd, ("ctrl", "a"), ("delete",))
                left = _value(s, box)
                return {"ok": empty(left, label), "said": f"Dry run: the chat with {who} opened and its message box "
                        "took the text and read it back - emptied again, nothing sent." + (
                            "" if empty(left, label) else " BUT the box still holds text - empty it in Teams."),
                        "payload": _picture(hwnd)}
            button, _ = find(s, hwnd, is_send, kinds=(50000,))
            if not (button and s.invoke(button)):
                _keys(hwnd, ("return",))                         # no Send button to press: Teams sends on Enter
            time.sleep(1.5)
            left = _value(s, box)
        finally:
            s.close()
    finally:
        if hr >= 0:
            ctms_tabs.ole32.CoUninitialize()
    if not empty(left, label):
        return {"ok": False, "said": f"Send was pressed in the chat with {who} but the box still holds text - "
                "look at Teams before sending again.", "payload": _picture(hwnd)}
    return {"ok": True, "said": f"Sent to {who} on Teams.", "payload": _picture(hwnd)}
