"""
The Haulier Rejection Form, read the way a screen reader reads it (11/11): Windows UI Automation on the work PC's
Edge, where he is signed in to the form - so it works whatever size the window is, behind other windows too, with no
picture taken. Only the form's own tab (ctms_window.PAGES["form"]) while it is the selected tab of an Edge window,
and only its page: the browser's bars and other tabs are never named back. A password box is never read.

  read      every control on the page, top to bottom: its kind, its words, how deep it sits, where it is, and its
            state - a tick box ticked or not, a choice selected or not, what a text box holds. Nothing is changed.

On a thread of its own, like ctms_tabs: UI Automation wants COM set up its own way, and an Edge that has stopped
answering must not stop the bridge. Standard library only, like everything else in work_pc\\.
"""
import os
import re
import threading
import time

import ctms_tabs as T
import ctms_window

IS_WIN = os.name == "nt"

# UI Automation's control types, by the names used here
KINDS = {50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combo", 50004: "edit", 50005: "link",
         50006: "image", 50007: "item", 50008: "list", 50013: "radio", 50020: "text", 50025: "custom",
         50026: "group", 50030: "document", 50033: "pane", 50036: "table"}
KEEP = ("button", "checkbox", "combo", "edit", "radio", "group", "list", "item", "text", "custom", "calendar", "link")
DOCUMENT = 50030
# Slots in UIAutomationClient.h: an element's own (counted on from ctms_tabs' 14 / 21 / 23 / 30), then each pattern's
EL_FOCUS, EL_IS_PASSWORD, EL_RECT = 3, 35, 43
PATTERN_VALUE, PATTERN_TOGGLE = 10002, 10015
IID_VALUE = "{A94CD8B1-0844-4CD6-9D2D-640537AB39E9}"
IID_TOGGLE = "{94CF8058-9B8D-4AB9-8BFD-4CD0A33C8C70}"
TOGGLE_STATE, IS_SELECTED, VALUE_GET = 4, 6, 4      # TogglePattern, SelectionItemPattern, ValuePattern getters
DO = 3                                              # Toggle / Select / SetValue: each pattern's first own method
CONFIRMED = ("response was submitted", "your response has been", "thanks!", "thank you")
MAX_NODES, MAX_DEPTH, DOC_SEARCH = 3000, 40, 1500
NAME_MAX = 160

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    T.oleaut32.SysAllocString.argtypes = [wintypes.LPCWSTR]
    T.oleaut32.SysAllocString.restype = ctypes.c_void_p

    class _Session(T._Session):
        """ctms_tabs' UI Automation session, able to read a page's controls and their state."""

        def _pattern(self, el, pid, iid):
            try:
                return self._get(el, T.EL_PATTERN_AS, (ctypes.c_int, pid), (ctypes.POINTER(T.GUID), T._guid(iid)))
            except OSError:
                return None

        def password(self, el):
            out = wintypes.BOOL()
            try:
                T._fn(el, EL_IS_PASSWORD, ctypes.POINTER(wintypes.BOOL))(el, ctypes.byref(out))
            except OSError:
                return True                       # can't tell: treated as one, never read
            return bool(out.value)

        def rect(self, el):
            r = wintypes.RECT()
            try:
                T._fn(el, EL_RECT, ctypes.POINTER(wintypes.RECT))(el, ctypes.byref(r))
            except OSError:
                return None
            return [r.left, r.top, r.right - r.left, r.bottom - r.top]

        def ticked(self, el):
            pat = self._pattern(el, PATTERN_TOGGLE, IID_TOGGLE)
            if not pat:
                return None
            out = ctypes.c_int()
            T._fn(pat, TOGGLE_STATE, ctypes.POINTER(ctypes.c_int))(pat, ctypes.byref(out))
            return out.value == 1                 # 0 off, 1 on, 2 neither

        def selected(self, el):
            pat = self._pattern(el, T.PATTERN_SELECTION_ITEM, T.IID_SELECTION_ITEM)
            if not pat:
                return None
            out = wintypes.BOOL()
            T._fn(pat, IS_SELECTED, ctypes.POINTER(wintypes.BOOL))(pat, ctypes.byref(out))
            return bool(out.value)

        def value(self, el):
            pat = self._pattern(el, PATTERN_VALUE, IID_VALUE)
            return self._text(pat, VALUE_GET) if pat else None

        def toggle(self, el):
            """Tick or untick a box - the page's own click on it."""
            pat = self._pattern(el, PATTERN_TOGGLE, IID_TOGGLE)
            if not pat:
                return False
            T._fn(pat, DO)(pat)
            return True

        def pick(self, el):
            """Select a choice - the page's own click on it."""
            pat = self._pattern(el, T.PATTERN_SELECTION_ITEM, T.IID_SELECTION_ITEM)
            if not pat:
                return False
            T._fn(pat, DO)(pat)
            return True

        def set_value(self, el, text):
            """What a text box holds, set the way a screen reader sets it (the page hears it as typed)."""
            pat = self._pattern(el, PATTERN_VALUE, IID_VALUE)
            if not pat:
                return False
            b = T.oleaut32.SysAllocString(text)
            try:
                T._fn(pat, DO, ctypes.c_void_p)(pat, b)
            finally:
                T.oleaut32.SysFreeString(b)
            return True

        def focus(self, el):
            """The page's focus put on it, as a click into it would - leaving a box is what makes the form's date
            picker take the date typed into it (11/11)."""
            try:
                T._fn(el, EL_FOCUS)(el)
            except OSError:
                return False
            return True


def is_form(name):
    """Is this (a page's or a tab's name) the rejection form?"""
    n = (name or "").lower()
    return any(w in n for w in ctms_window.PAGES["form"])


def _document(s, hwnd):
    """The form's page in this Edge window: the first document named as the form, else the first document - found
    breadth first, through the browser's own bars only as far as the page."""
    level, seen, first = [s.element(hwnd)], 0, None
    for _ in range(T.MAX_DEPTH):
        deeper = []
        for el in level:
            for child in s.children(el):
                seen += 1
                if s.control_type(child) == DOCUMENT:
                    if is_form(s.name(child)):
                        return child
                    first = first or child
                    continue                      # a page: not walked into here
                deeper.append(child)
                if seen >= DOC_SEARCH:
                    return first
        if not deeper:
            break
        level = deeper
    return first


def _area(s, el):
    """Where it sits on screen: [left, top, right, bottom], or None."""
    r = s.rect(el)
    return [r[0], r[1], r[0] + r[2], r[1] + r[3]] if r and r[2] > 0 and r[3] > 0 else None


def _item(s, el, kind, depth):
    """One control as it is read: its kind, words, depth, place, and state where it has one."""
    it = {"k": kind, "nm": s.name(el)[:NAME_MAX], "d": depth, "at": s.rect(el)}
    if kind == "checkbox":
        it["on"] = s.ticked(el)
    elif kind == "radio":
        it["on"] = s.selected(el)
    elif kind in ("edit", "combo"):
        if s.password(el):
            it["password"] = True                 # never read, never typed into
        else:
            v = s.value(el)
            it["v"] = (v or "")[:NAME_MAX] if v is not None else None
    return it


def _walk(s, doc):
    """The page's controls, top to bottom (depth first, in the page's own order): [(item, its element)]."""
    out, stack, seen = [], [(child, 1) for child in reversed(list(s.children(doc)))], 0
    while stack and seen < MAX_NODES:
        el, depth = stack.pop()
        seen += 1
        kind = KINDS.get(s.control_type(el), "other")
        if kind in KEEP and (kind != "text" or s.name(el).strip()):
            out.append((_item(s, el, kind, depth), el))
        if depth < MAX_DEPTH and kind not in ("checkbox", "radio", "edit", "button"):
            stack.extend((child, depth + 1) for child in reversed(list(s.children(el))))
    return out


def _page(s, hwnd):
    """The form's page in this window, waited for while Edge turns its page on for UI Automation (it does so from
    the first ask, 11/11). Raises RuntimeError when it isn't there or isn't the form."""
    doc = None
    for _ in range(4):
        doc = _document(s, hwnd)
        if doc is not None:
            break
        time.sleep(0.8)
    if doc is None:
        raise RuntimeError("Edge's window has no page to read.")
    name = s.name(doc)
    if not is_form(name):
        raise RuntimeError(f"the page showing isn't the rejection form ({name[:60] or 'no name'}).")
    return doc, name


# -- what goes in, worked out from the page before anything is touched
def _norm(text):
    return " ".join(str(text or "").replace("*", " ").split()).lower()


def _groups(items):
    """{index of a group: [indexes of what sits inside it]}, by depth as read top to bottom."""
    out = {}
    for i, it in enumerate(items):
        if it["k"] in ("group", "list"):
            inside = []
            for j in range(i + 1, len(items)):
                if items[j]["d"] <= it["d"]:
                    break
                inside.append(j)
            out[i] = inside
    return out


def _question(name):
    """A question's words with its number taken off: '10. Rejection Reason Required to answer' reads
    'rejection reason required to answer'."""
    return re.sub(r"^\d+\s*[.)]\s*", "", _norm(name))


def _found(named, q):
    """Indexes from [(index, name)] that are question q: its words first (number aside), else anywhere in it."""
    first = [i for i, nm in named if _question(nm).startswith(q)]
    return first or [i for i, nm in named if q in _norm(nm)]


def _is_choice(name, label):
    """A choice by its own words, exactly - the form's Other reads 'Other answer' (11/11)."""
    n, want = _norm(name), _norm(label)
    return n == want or (want == "other" and n == "other answer")


def plan(items, answers):
    """[(how, index, value)] for answers [{"q", "tick": [labels]} | {"q", "pick", "other"?} | {"q", "text"}], each
    question found by its words and each choice by its exact words. Raises ValueError naming whatever isn't on the
    page - and then nothing at all is done."""
    groups, steps, missing = _groups(items), [], []
    boxes = [(i, it["nm"]) for i, it in enumerate(items) if it["k"] in ("edit", "combo") and not it.get("password")]
    for a in answers:
        q = _norm(a["q"])
        if "text" in a:                                   # a text box, or the date's combo box (the real form)
            found = _found(boxes, q)
            if not found:
                missing.append(f"{a['q']}: its box")
            else:
                steps.append(("text", found[0], str(a["text"])))
            continue
        kind, how = ("checkbox", "tick") if "tick" in a else ("radio", "pick")
        # the question's own group holds choices of its kind - a choice that only shares its words is not it
        # ('No Availability - Vehicle Type' is a Rejection Reason, not the Vehicle Type question)
        asking = [(g, items[g]["nm"]) for g in groups if any(items[k]["k"] == kind for k in groups[g])]
        hits = _found(asking, q)
        if not hits:
            missing.append(f"{a['q']}: the question")
            continue
        inside = groups[min(hits, key=lambda g: len(groups[g]))]          # the innermost: the question itself
        for label in (a["tick"] if "tick" in a else [a["pick"]]):
            opt = next((k for k in inside if items[k]["k"] == kind and _is_choice(items[k]["nm"], label)), None)
            if opt is None:
                missing.append(f"{a['q']}: {label}")
            else:
                steps.append((how, opt, label))
        if a.get("other") is not None:
            box = next((k for k in inside if items[k]["k"] == "edit" and not items[k].get("password")), None)
            if box is None:
                missing.append(f"{a['q']}: its Other box")
            else:
                steps.append(("text", box, str(a["other"])))
    if missing:
        raise ValueError("not on the form, so nothing was filled in: " + "; ".join(missing))
    return steps


def check(items, steps):
    """What doesn't read back as filled in: [words], [] when every answer is there."""
    off = []
    for how, i, value in steps:
        it = items[i]
        if how in ("tick", "pick") and not it.get("on"):
            off.append(f"{value} isn't {'ticked' if how == 'tick' else 'selected'}")
        elif how == "text" and (it.get("v") or "").strip() != value.strip():
            off.append(f"'{it['nm'][:40]}' reads '{it.get('v') or ''}', not '{value}'")
    return off


def confirmed(items):
    """The page's words once it has taken the response, or "" while it hasn't."""
    words = " ".join(it["nm"] for it in items if it["k"] == "text")
    gone = not any(it["k"] == "button" and _norm(it["nm"]) == "submit" for it in items)
    return words[:300] if gone and any(w in words.lower() for w in CONFIRMED) else ""


# -- doing it, on a thread of its own
def _session(work):
    hr = T.ole32.CoInitializeEx(None, 0)          # COINIT_MULTITHREADED, as UI Automation clients are told to
    try:
        s = _Session()
        try:
            return work(s)
        finally:
            s.close()
    except (ValueError, RuntimeError) as e:
        return e
    except OSError as e:
        return RuntimeError(f"UI Automation could not reach Edge ({e}).")
    finally:
        if hr >= 0:
            T.ole32.CoUninitialize()


def _on_thread(work, timeout, what):
    if not IS_WIN:
        raise RuntimeError("The rejection form is worked on Windows only.")
    out = []
    t = threading.Thread(target=lambda: out.append(_session(work)), daemon=True, name="ctms-form")
    t.start()
    t.join(timeout)
    if not out:
        raise RuntimeError(f"Edge did not answer in time, so the form wasn't {what}.")
    if isinstance(out[0], ValueError):
        raise RuntimeError(str(out[0]))
    if isinstance(out[0], Exception):
        raise RuntimeError(f"The form couldn't be {what}: {out[0]}")
    return out[0]


def read(hwnd, timeout=25.0):
    """{"items": [{"k", "nm", "d", "at", "on" / "v"}], "doc", "took"} for the form showing in this Edge window.
    Raises RuntimeError with what went wrong; nothing on the page is changed either way."""
    def work(s):
        t0 = time.time()
        doc, name = _page(s, hwnd)
        return {"items": [it for it, _ in _walk(s, doc)], "doc": name[:NAME_MAX], "took": round(time.time() - t0, 2),
                "area": _area(s, doc)}
    return _on_thread(work, timeout, "read")


def page_area(hwnd, timeout=10.0):
    """Where the page showing in this Edge window sits on screen, [left, top, right, bottom], or None - any page,
    the tracker's too. Edge gives a normal tab no window of its own to measure (the work PC's), and CTMS - an app of
    its own since 10/11 - no longer leaves a tab beside it to borrow the area from (11/11)."""
    def work(s):
        for _ in range(4):
            doc = _document(s, hwnd)
            if doc is not None:
                return _area(s, doc)
            time.sleep(0.8)
        return None
    return _on_thread(work, timeout, "measured")


def fill(hwnd, answers, submit=False, timeout=60.0):
    """The answers put in by name, read back, and - only with submit, and only when every one reads back - Submit
    pressed and the page's confirmation waited for. {"filled", "off": [what didn't read back], "submitted",
    "said", "items"}. A question or choice not on the page raises before anything is touched."""
    def work(s):
        doc, _ = _page(s, hwnd)
        pairs = _walk(s, doc)
        items = [it for it, _ in pairs]
        if confirmed(items):                          # still thanking for the last response: a fresh form first
            again = next((el for it, el in pairs if it["k"] in ("link", "button")
                          and "another response" in _norm(it["nm"])), None)
            if again is None or not s.invoke(again):
                raise RuntimeError("the form is still showing its thanks for the last response, with no way on to a "
                                   "fresh one - reload its tab.")
            end = time.time() + 10
            while time.time() < end:
                time.sleep(0.8)
                doc, _ = _page(s, hwnd)
                pairs = _walk(s, doc)
                items = [it for it, _ in pairs]
                if any(it["k"] == "button" and _norm(it["nm"]) == "submit" for it in items):
                    break
        steps = plan(items, answers)
        for how, i, value in steps:
            el = pairs[i][1]
            s.focus(el)                               # into it first, as a click would
            if how == "tick" and not items[i].get("on"):
                s.toggle(el)
            elif how == "pick" and not items[i].get("on"):
                s.pick(el)
            elif how == "text":
                s.set_value(el, value)
            time.sleep(0.15)
        away = next((pairs[i][1] for how, i, _ in steps if how != "text"), None)
        if away is not None:
            s.focus(away)                             # and out of the last box: the date picker takes its date then
        time.sleep(0.6)
        pairs = _walk(s, doc)
        items = [it for it, _ in pairs]
        out = {"filled": len(steps), "off": check(items, plan(items, answers)), "submitted": False, "said": "",
               "items": items}
        if out["off"] or not submit:
            return out
        button = next((el for it, el in pairs if it["k"] == "button" and _norm(it["nm"]) == "submit"), None)
        if button is None or not s.invoke(button):
            out["off"] = ["the form's Submit couldn't be pressed"]
            return out
        end = time.time() + 15
        while time.time() < end:
            time.sleep(0.8)
            page = _document(s, hwnd)
            said = confirmed([it for it, _ in _walk(s, page)]) if page is not None else ""
            if said:
                out.update(submitted=True, said=said)
                return out
        out["off"] = ["Submit was pressed but the form didn't confirm it - look at the form before trying again"]
        return out
    return _on_thread(work, timeout, "filled in")
