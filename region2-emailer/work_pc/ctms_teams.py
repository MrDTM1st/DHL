"""
A Teams message from the work PC - his asks (01/11): "with DHL NOC, instead of an email button, can we get like a Teams
message button ... I want you to send it on Teams on the work PC", then "build the quieter version". The quietest that
works: Teams' message box takes no text from UI Automation (the 01/11 dry run: Teams took the change and put its own
text straight back), only typing or a paste - so it is one paste, with the clipboard put back as it was, and Teams'
own Send button pressed through UI Automation, never Enter. The dashboard's Send in Teams hands over who and what, and
each step is checked before the next:

  open    Teams' own link for a chat with that address (msteams:/l/chat/0/0?users=..) - nothing else is opened. Not
          the link's message part: Teams typed that into the box twice in the 01/11 test
  check   a Teams window titled with that chat ("Chat | Rich Brumby | Microsoft Teams"), and its message box (found
          through UI Automation by its name) empty - his own draft there, another chat, or none in time stops it with
          nothing sent
  type    the cursor put in that box through UI Automation, one paste, and read back: this message and nothing else.
          The clipboard comes back as it was once Teams shows the text (text and its formatting, a picture, files);
          a copy a password manager marked private is not put back
  send    Teams' own Send button, and the box empty after; the window that was in front is put back, and a picture of
          the chat comes back

Once the text is in, anything that goes wrong empties the box again - it was empty, so nothing of ours is left in it.
Keys only ever go to Teams, and only while it is in front.

Opening the chat brings Teams forward for those few seconds - the link does that. Only ever Teams' own window, only the
chat the dashboard named, only the dashboard's text. A dry run does it all but Send, and empties the box again. Nothing
here runs without Look mum, no hands.

Standard library only, like everything else in work_pc\\.
"""
import os
import re
import time
import unicodedata
from urllib.parse import quote

import ctms_window

IS_WIN = os.name == "nt"
EXES = ("ms-teams.exe", "teams.exe")
TITLE_END = "| microsoft teams"
OPEN_SECONDS = 25
BOX_TYPES = (50004, 50030)          # UI Automation's Edit and Document: what Teams' message box reads as
BUTTON = 50000
BOX_WORDS = ("type a message", "type a new message", "type your message")
FIND_NODES = 6000                   # UI Automation elements looked at, at most, for the box and the Send button
PATTERN_VALUE, IID_VALUE, VALUE_GET = 10002, "{A94CD8B1-0844-4CD6-9D2D-640537AB39E9}", 4
PATTERN_LEGACY, IID_LEGACY, LEGACY_VALUE = 10018, "{828055AD-355B-4435-86D5-3B51C14A9B1B}", 8
# the clipboard, borrowed for the paste and put back as it was
CF_DIB, CF_HDROP = 8, 15
CLIP_TEXT = ("HTML Format", "Rich Text Format")                  # kept with copied text: a page's or Office's look
CLIP_OTHER = ("PNG", "HTML Format", "Preferred DropEffect", "FileNameW")    # with no text: a picture, or files
CLIP_PRIVATE = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore",
                "CanIncludeInClipboardHistory")                  # how a password manager marks its copy
PASTE_SECONDS = 4                   # for Teams to show the pasted text before the clipboard is put back


class Stop(Exception):
    pass


def chat_link(email):
    """Teams' own link for a chat with that address."""
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


def _plain(s):
    """The box's text without the invisible marks an editor keeps in it (zero-width spaces, word joiners)."""
    return "".join(ch for ch in str(s or "") if unicodedata.category(ch) != "Cf")


def _squash(s):
    return re.sub(r"\s+", " ", _plain(s)).strip().lower()


def _show(v):
    """What the box reads, for a message: its start and end as Python writes them (invisible marks show), and length."""
    v = str(v or "")
    return f"{v[:50]!r}{' ... ' + repr(v[-25:]) if len(v) > 50 else ''}, {len(v)} characters"


def same_text(box, text):
    """Does what the box reads back hold the text? Line breaks and spacing as Teams keeps them do not matter."""
    want, got = _squash(text), _squash(box)
    return bool(want) and want[:200] in got


def holds_only(box, text):
    """Does the box hold the text and nothing else - no older draft before or after it?"""
    return bool(_squash(text)) and _squash(box) == _squash(text)


def only_copies(box, text):
    """Is the box holding nothing but this same message, once or more - left there by an earlier try of this send?
    Spacing between the copies does not matter; any other word in it does."""
    v, t = re.sub(r"\s+", "", _plain(box)).lower(), re.sub(r"\s+", "", _plain(text)).lower()
    return bool(t) and bool(v) and len(v) % len(t) == 0 and v == t * (len(v) // len(t))


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


def _set_focus(box):
    """The cursor into Teams' message box through UI Automation - no click."""
    from ctms_tabs import _fn
    _fn(box, 3)(box)                                             # IUIAutomationElement::SetFocus


def _keys(hwnd, *combos):
    """Chords to Teams, which must be in front for each: ("ctrl", "v") ... - the paste, and Ctrl+A then Delete to
    empty the box of our own text. Never Enter: Send is Teams' own button."""
    import ctms_act
    for combo in combos:
        if not ctms_act.to_front(hwnd):
            raise Stop("Teams could not be brought to the front, so no keys were sent - nothing sent.")
        *mods, key = combo
        vk, ext = ctms_act.VK[key] if key in ctms_act.VK else (ord(key.upper()), False)
        seq = [ctms_act._vk(ctms_act.MOD_VK[m], False) for m in mods]
        seq += [ctms_act._vk(vk, ext), ctms_act._vk(vk, ext, up=True)]
        seq += [ctms_act._vk(ctms_act.MOD_VK[m], False, up=True) for m in reversed(mods)]
        ctms_act._send(seq)
        time.sleep(0.25)


def _clear(s, hwnd, box, label):
    """Empty the box of our own text (copies of this message, or the paste just made): its cursor, Ctrl+A, Delete ->
    is it empty now?"""
    _set_focus(box)
    time.sleep(0.3)
    _keys(hwnd, ("ctrl", "a"), ("delete",))
    time.sleep(0.5)
    return empty(_value(s, box), label)


def _clip_api():
    import ctypes
    from ctypes import wintypes
    import ctms_act
    u, k = ctms_act.user32, ctms_act.kernel32
    u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u.IsClipboardFormatAvailable.restype = wintypes.BOOL
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u.RegisterClipboardFormatW.restype = wintypes.UINT
    k.GlobalSize.argtypes = [wintypes.HGLOBAL]
    k.GlobalSize.restype = ctypes.c_size_t
    return u, k


def _clip_save():
    """What is on the clipboard, to put back straight after the paste -> [(format, bytes)]: its text with a page's or
    Office's formatting, a copied picture, copied files. A copy marked private - a password manager's - is not even
    read, and not put back: it would outlive the manager's own clearing. Read only to be put back, never sent."""
    import ctypes
    import ctms_act
    u, k = _clip_api()
    if any(u.IsClipboardFormatAvailable(u.RegisterClipboardFormatW(n)) for n in CLIP_PRIVATE):
        return []
    if u.IsClipboardFormatAvailable(ctms_act.CF_UNICODETEXT):    # text: with its formatting, never a picture of it
        kinds = [ctms_act.CF_UNICODETEXT] + [u.RegisterClipboardFormatW(n) for n in CLIP_TEXT]
    else:
        kinds = [CF_DIB, CF_HDROP] + [u.RegisterClipboardFormatW(n) for n in CLIP_OTHER]
    kinds = [f for f in kinds if f and u.IsClipboardFormatAvailable(f)]
    if not kinds:
        return []
    if not ctms_act._open_clipboard():
        raise Stop("The work PC's clipboard is busy in another program, so nothing was pasted - nothing sent.")
    saved = []
    try:
        for f in kinds:
            h = u.GetClipboardData(f)
            p = k.GlobalLock(h) if h else None
            if not p:
                continue
            try:
                saved.append((f, ctypes.string_at(p, k.GlobalSize(h))))
            finally:
                k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()
    return saved


def _clip_put(items):
    """The clipboard set to these [(format, bytes)] and nothing else - [] leaves it empty. False = it was busy, or
    Windows would not take one of them."""
    import ctypes
    import ctms_act
    u, k = _clip_api()
    if not ctms_act._open_clipboard():
        return False
    took = True
    try:
        u.EmptyClipboard()
        for f, data in items:
            h = k.GlobalAlloc(ctms_act.GMEM_MOVEABLE, max(len(data), 1))
            p = k.GlobalLock(h) if h else None
            if not p:
                if h:
                    k.GlobalFree(h)
                took = False
                continue
            ctypes.memmove(p, data, len(data))
            k.GlobalUnlock(h)
            if not u.SetClipboardData(f, h):                     # the clipboard owns h once this succeeds
                k.GlobalFree(h)
                took = False
        return took
    finally:
        u.CloseClipboard()


def _paste(s, hwnd, box, label, text):
    """The text into the box: its cursor, one paste - the clipboard put back as it was once Teams shows the text (or
    after a few seconds) -> (what the box reads, why it is still empty or "")."""
    import ctms_act
    _set_focus(box)
    time.sleep(0.4)
    keep = _clip_save()
    ours = text.replace("\r\n", "\n").replace("\n", "\r\n")
    if not _clip_put([(ctms_act.CF_UNICODETEXT, (ours + "\0").encode("utf-16-le"))]):
        _clip_put(keep)
        raise Stop("Windows would not put the message on the work PC's clipboard (busy in another program?) - "
                   "nothing pasted, nothing sent.")
    got, why = "", ""
    try:
        _keys(hwnd, ("ctrl", "v"))
        end = time.time() + PASTE_SECONDS                        # Teams reads the clipboard as it handles the keys
        while True:
            time.sleep(0.3)
            got = _value(s, box)
            if not empty(got, label) or time.time() > end:
                break
        if empty(got, label):                                    # what it was, for the stop - our own text only
            held = ctms_act._clip_text() == ours
            why = (f"the clipboard {'held' if held else 'did NOT hold'} the message and the cursor was on "
                   f"{_focused(s) or 'nothing'!r}")
    finally:
        _clip_put(keep)
    return got, why


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
    before = _value(s, box)
    if not empty(before, label):
        if not only_copies(before, text):
            raise Stop(f"The message box with {who} already holds a draft ({_show(before)}) - left as it is, nothing "
                       "sent.")
        if not _clear(s, hwnd, box, label):                      # this same message, left by an earlier try: ours
            raise Stop(f"Copies of this message left in the box with {who} by an earlier try would not clear (it "
                       f"reads {_show(_value(s, box))}) - nothing sent.")
    # from here the box was empty - anything that goes wrong empties it again, so nothing of ours is left in it
    got, why = _paste(s, hwnd, box, label, text)
    if why:
        raise Stop(f"The paste left the message box with {who} empty ({why}) - nothing sent.")
    if not holds_only(got, text):
        _clear(s, hwnd, box, label)
        raise Stop(f"The message box with {who} read back {_show(got)}, not the message - emptied, nothing sent.")
    if dry:
        left = _clear(s, hwnd, box, label)
        return {"ok": left,
                "said": f"Dry run: the chat with {who} opened and its message box took the text and read it back "
                        "exactly - emptied again, nothing sent." + ("" if left else
                                                                   " BUT the text is still in the box - empty it in Teams.")}
    button, _ = find(s, hwnd, is_send, kinds=(BUTTON,))
    if not (button and s.invoke(button)):
        _clear(s, hwnd, box, label)
        raise Stop(f"Teams' Send button could not be {'pressed' if button else 'found'} in the chat with {who} - "
                   "emptied, nothing sent.")
    time.sleep(1.5)
    try:
        box2, _ = _box(s, hwnd, who)                             # the box afresh: Teams redraws it once sent
        left = _value(s, box2)
    except (OSError, Stop):
        return {"ok": False, "said": f"Send was pressed in the chat with {who}, but its message box could not be read "
                                     "after - look at the chat in Teams to see whether it went."}
    if not empty(left, label):
        return {"ok": False, "said": f"Send was pressed in the chat with {who} but the text stayed in the box - "
                                     "look at the chat in Teams before sending again."}
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
    hwnd = None
    try:
        # the plain chat link: a message riding in the link was typed into the box twice (01/11 test), so the text
        # is pasted once the box is seen to be empty
        os.startfile(chat_link(email))
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
            except (OSError, ctms_act.Refused) as e:             # all before Send: after it, _fill_and_send says so
                raise Stop(f"Windows would not let the keys or UI Automation through to Teams ({type(e).__name__}) - "
                           f"nothing sent; if the message is in the box with {who}, empty it in Teams.")
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
