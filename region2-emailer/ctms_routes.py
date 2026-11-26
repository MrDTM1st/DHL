"""CTMS routes (23/11): every CTMS job as one named, tested command. His words: "sometimes one chat knows how to use
CTMS better than the other chat. I want to stop that from happening. I just also want the process to be quicker."

How a route works. CTMS's own Java window is read through the Access Bridge (`fields`: every menu, button, tab, box and
grid cell with its name, value and place on the screen, about two seconds). The next moves are aimed at what was read,
by NAME, never at remembered pixels: the window changed size on 23/11 and pixel recipes drift. They go to the work PC
as one batch of steps, and CTMS is read again to check it did what was meant. A route stops, and says what it saw, on
anything it doesn't expect: a box it doesn't know, a different order than asked for, a discard prompt.

The rails are the bridge's own: nothing moves unless "Look mum, no hands" is on, and CTMS must be in front. A route
that would save, book, cancel or send stops before that press and says what it would press, unless it was given
--commit. --commit is for jobs he has said yes to; the standing go-aheads are in memory (ctms-routes).

    python ctms_routes.py list                      the routes, one line each
    python ctms_routes.py where                     what's open in CTMS now, where the cursor is, any box up
    python ctms_routes.py find TEXT                 every menu, button, box or cell whose name or value has TEXT
    python ctms_routes.py press NAME                click a button, tab or cell by its name (--double, --right)
    python ctms_routes.py menu "C-TMS Modules > Order Management > Orders"
    python ctms_routes.py <route> [args]            e.g. order-read 1234567-1-1 (see list)

Every route ends with one JSON line, ROUTE_RESULT {...}, for a caller that wants the answer.
"""
import argparse
import json
import os
import re
import sys
import time

import ctms_remote as R

HERE = os.path.dirname(os.path.abspath(__file__))
SUFFIX = re.compile(r"\s+(?:mnemonic|ALT)\s+\S+$")       # "Orders mnemonic O" -> "Orders", "Action ALT A" -> "Action"
ROUTES = {}                                                # name -> (function, one-line help, argparse builder)


class Fail(Exception):
    """A route stopped: what it expected, and what CTMS showed instead."""


def route(name, help_text):
    def wrap(fn):
        ROUTES[name] = (fn, help_text)
        return fn
    return wrap


# ---------- reading CTMS ----------
TAB_PREFIX = re.compile(r"^(?:[\w &/]+? tab page )+")   # "Detail tab page Cost Centre" -> "Cost Centre"


def clean(name):
    name = re.sub(r"\s+", " ", SUFFIX.sub("", str(name or ""))).strip()
    name = TAB_PREFIX.sub("", name)
    return re.sub(r"\s+(?:Multiline|Required)$", "", name).strip()


class Screen:
    """One Access Bridge read of CTMS: its elements in tree order, found by role, name and value."""

    def __init__(self, payload):
        self.p = payload or {}
        self.els = list(self.p.get("elements") or [])
        self.windows = list(self.p.get("windows") or [])
        self.took = self.p.get("took")
        focus = self.p.get("focus")
        self.focus = next((e for e in self.els if e.get("n") == focus), None)

    def find(self, name=None, role=None, value=None, contains=False, placed=True, enabled=None, window=None,
             within=None):
        """Elements matching all that is given. name/value: exact (after the mnemonic suffix is cut) or, with
        contains, a case-blind substring. placed: only what is on the screen now. within: an element whose
        children (by the tree) are searched."""
        pool = self.children(within) if within is not None else self.els
        out = []
        for e in pool:
            if role and e.get("r") != role and not (isinstance(role, (tuple, list)) and e.get("r") in role):
                continue
            if window is not None and e.get("w") != window:
                continue
            if placed and not on_screen(e):
                continue
            if enabled is not None and (("disabled" in (e.get("st") or [])) == enabled):
                continue
            if name is not None and not _match(clean(e.get("nm")), name, contains):
                continue
            if value is not None and not _match(str(e.get("v") or ""), value, contains):
                continue
            out.append(e)
        return out

    def one(self, what="", **kw):
        got = self.find(**kw)
        if len(got) == 1:
            return got[0]
        desc = what or ", ".join(f"{k}={v!r}" for k, v in kw.items() if v is not None)
        if not got:
            raise Fail(f"CTMS shows no {desc} ({self.summary()})")
        raise Fail(f"CTMS shows {len(got)} of {desc}: " + "; ".join(describe(e) for e in got[:5]))

    def first(self, **kw):
        got = self.find(**kw)
        return got[0] if got else None

    def children(self, el):
        """Everything under el in the tree: the elements after it with a deeper level, up to the next one that isn't."""
        if el is None:
            return []
        i = next((k for k, e in enumerate(self.els) if e.get("n") == el.get("n")), None)
        if i is None:
            return []
        out = []
        for e in self.els[i + 1:]:
            if e.get("lv", 0) <= el.get("lv", 0):
                break
            out.append(e)
        return out

    def frames(self):
        """The windows open inside CTMS (Planning, Order Summary, Order details for ...), top one first: the Access
        Bridge lists them in Java's stacking order (seen 23/11: the Order Search card, then the order over it)."""
        return [e for e in self.els if e.get("r") == "internal frame"]

    def frame_of(self, el):
        """The CTMS window (internal frame) something sits in, or None."""
        if not hasattr(self, "_owner"):
            self._owner, stack = {}, []
            for e in self.els:
                while stack and stack[-1].get("lv", 0) >= e.get("lv", 0):
                    stack.pop()
                frame = next((f for f in reversed(stack) if f.get("r") == "internal frame"), None)
                self._owner[e.get("n")] = frame
                stack.append(e)
        return self._owner.get(el.get("n")) if el else None

    def covered(self, el):
        """The CTMS window lying over el's middle, if one does - a click there would land on it, not on el (the
        Order Search card over an order's Services tab, 23/11). The Access Bridge can't see that; this can."""
        own = self.frame_of(el)
        if own is None or not on_screen(el):
            return None
        x, y = centre(el)
        for f in self.frames():
            if f.get("n") == own.get("n"):
                return None                               # everything above it has been checked
            fx, fy, fw, fh = f.get("at") or (0, 0, 0, 0)
            if fx <= x < fx + fw and fy <= y < fy + fh and "iconified" not in (f.get("st") or []):
                return f
        return None

    def frame(self, name, contains=True):
        got = [f for f in self.frames() if _match(clean(f.get("nm")), name, contains)]
        return got[0] if got else None

    def boxes(self):
        """Forms' own pop-up boxes (alerts, questions, lists of values): what is in any Java window but the main one,
        with its words and buttons."""
        out = []
        for w in sorted({e.get("w") for e in self.els if e.get("w") not in (None, 1)}):
            els = [e for e in self.els if e.get("w") == w and on_screen(e)]
            if not els:
                continue
            words = [str(e.get("nm") or e.get("v") or "") for e in els if e.get("r") in ("label", "text")
                     and (e.get("nm") or e.get("v"))]
            buttons = [clean(e.get("nm")) for e in els if e.get("r") == "push button"]
            title = next((clean(e.get("nm")) for e in els if e.get("r") in ("dialog", "frame", "window")), "")
            out.append({"window": w, "title": title, "words": " ".join(words)[:400], "buttons": buttons,
                        "els": els})
        return out

    def question(self):
        """A Forms question up in CTMS's own window: a window with an option pane straight under it (the schedule
        question, "discard your changes?", Confirm Create Trip). -> {"window", "words", "buttons": {first word, lower:
        element}} or None. Its words sit in the window's name, the pane's name and its labels."""
        for pane in (e for e in self.els if e.get("r") == "option pane"):
            # the question's OWN window: the innermost one round its pane. A question can sit inside another window
            # (Split Order's "continue to split?", 23/11) - that window's Process must never be taken for its OK
            f = self.frame_of(pane)
            if f is None:
                continue
            kids = self.children(f)
            words = []
            for w in [str(f.get("nm") or ""), str(pane.get("nm") or "")] + [str(x.get("nm") or "") for x in kids
                                                                              if x.get("r") == "label"]:
                w = re.sub(r"\s+", " ", w).strip()
                if w and w != "Forms" and not any(w in x for x in words):
                    words.append(w)
            buttons = {clean(b.get("nm")).split()[0].lower(): b for b in kids
                       if b.get("r") == "push button" and clean(b.get("nm"))}
            return {"window": clean(f.get("nm")), "words": " ".join(words), "buttons": buttons}
        return None

    def summary(self):
        frames = [clean(f.get("nm")) for f in self.frames()]
        boxes = [b["title"] or b["words"][:60] for b in self.boxes()]
        cur = describe(self.focus) if self.focus else "nowhere"
        return (f"open: {', '.join(frames) or 'nothing'}; cursor in {cur}"
                + (f"; box up: {' | '.join(boxes)}" if boxes else ""))


def _match(have, want, contains):
    have, want = str(have or ""), str(want or "")
    return want.lower() in have.lower() if contains else have == want


def on_screen(e):
    at = e.get("at") or []
    return len(at) == 4 and at[2] > 0 and at[3] > 0 and not (at[0] == -1 and at[1] == -1)


def centre(e):
    x, y, w, h = e["at"]
    return [x + w // 2, y + h // 2]


def describe(e):
    if not e:
        return "nothing"
    bits = [e.get("r") or "?"]
    if clean(e.get("nm")):
        bits.append(repr(clean(e.get("nm"))))
    if e.get("v") not in (None, ""):
        bits.append("= " + repr(str(e.get("v"))[:60]))
    return " ".join(bits)


# ---------- talking to the bridge ----------
def connect():
    if not R.BASE:
        R.BASE, R.KEY = R._desk()


# ---------- fewer reads (his 26/11 "Yes, build it", the faster CTMS) ----------
# Most of a read's time is the windows behind: the Run has skipped "Planning" and the main "OPOKUD" window on every
# read of an order card since 02/11 (ctms_items.NOT_READ). A route that works on an order card asks the bridge for the
# same; a menu (open_menu) is always read whole. A bridge older than 26/11 ignores the ask and reads everything, as
# before. Off until it has been timed live on the work PC: the home flag file _ctms_fast_reads.on switches it on.
FAST_FLAG = os.path.join(HERE, "_ctms_fast_reads.on")
CARD_ROUTES = ("order-find", "order-read", "order-open", "order-close", "order-note", "order-qty", "order-item",
               "order-deltype", "order-services", "order-nc", "order-split", "order-cancel", "order-copy")
CARD_SKIP = {"skip": ["Planning", "OPOKUD"]}
PROFILE = {}                                              # what this route's reads may skip (main() sets it)
_WHOLE = [0]                                              # > 0: inside a menu - every read whole


def _skips():
    return dict(PROFILE) if PROFILE and not _WHOLE[0] and os.path.exists(FAST_FLAG) else {}


def read(wait=150):
    """CTMS as the Access Bridge sees it now."""
    connect()
    result, payload = R.ask("fields", wait_total=wait, **_skips())
    if not result.get("ok") or not payload or payload.get("kind") != "fields":
        raise Fail(f"CTMS couldn't be read: {result.get('detail')}")
    return Screen(payload)


# ---------- CTMS's harmless notices (his 26/11 "Yes, build it", the faster CTMS) ----------
# Notices that only inform - one OK button, nothing decided by pressing it. 25/11's resend stopped on "Missed
# delivery window: Order N stop 2." and was finished by hand: now it is OK'd, the window's Save pressed again ONCE if
# it is still there to press (the press the notice interrupted), and the job carries on - the notice's words go in
# the route's answer (ROUTE_RESULT "notices"), so he still hears what CTMS said. Anything else still stops the route.
HARMLESS = re.compile(r"missed delivery window|FRM-41091", re.I)
NOTICES = []                                              # what this run OK'd, for its answer
_RESAVED = set()                                          # the windows whose Save was pressed again: never a third


def harmless(q):
    """A Forms notice that is only information: its words known, OK its one button."""
    return (q is not None and "ok" in q["buttons"] and set(q["buttons"]) <= {"ok"}
            and bool(HARMLESS.search(q["words"])))


def settle(s, frame=None):
    """After a press: each harmless notice up now OK'd - its own OK, clicked where it is (the Access Bridge can list
    Planning over it when it isn't, 25/11) - then `frame`'s Save pressed again once, if it is enabled. -> (the
    screen, the question still up or None)."""
    oked = False
    for _ in range(3):
        q = s.question()
        if not harmless(q):
            break
        act([click(q["buttons"]["ok"], after=0.8)], "OK the notice: " + q["words"][:60])
        NOTICES.append(re.sub(r"\s+", " ", q["words"]).strip()[:160])
        oked = True
        s = read()
    if oked and frame and frame not in _RESAVED:
        save = s.find(name="Save", role="push button", within=s.frame(frame), enabled=True)
        if save:
            _RESAVED.add(frame)
            act([click(save[0], after=1.2)], f"{frame} Save again (the notice stopped the first)")
            return settle(read(), None)                   # a notice it raises is OK'd too, never a third Save
    return s, s.question()


def act(steps, name="route"):
    """One batch of steps on the work PC. Raises Fail with the bridge's words if a step was refused or failed."""
    connect()
    result, payload = R.ask("steps", wait_total=90 + 10 * len(steps), steps=steps)
    R.trace(f"route-{name}", {"steps": steps}, result, payload)
    if not result.get("ok"):
        raise Fail(f"{name}: {result.get('detail')}")
    return result


def click(e, double=False, right=False, react=False, after=None, box=None, timeout=None):
    step = {"action": "click", "screen": centre(e)}
    if double:
        step["double"] = True
    if right:
        step["right"] = True
    if react:
        step["react"] = True
        if timeout:
            step["timeout"] = timeout
        if box:
            step["box"] = box
    if after is not None:
        step["after"] = after
    return step


def key(k, commit=False, after=None):
    step = {"action": "key", "key": k}
    if commit:
        step["commit"] = True
    if after is not None:
        step["after"] = after
    return step


def typed(text, after=None):
    step = {"action": "type", "text": str(text)}
    if after is not None:
        step["after"] = after
    return step


def wait(seconds):
    return {"action": "wait", "seconds": seconds}


def fill(e, text):
    """Steps that replace a box's value with text: into it, everything selected, typed over."""
    return [click(e, after=0.3), key("home", after=0.05), key("shift+end", after=0.05), typed(text, after=0.2)]


def until(test, what, tries=6, pause=0.0):
    """Read CTMS until test(screen) gives something truthy; -> (that, screen). Fail after tries reads."""
    s = None
    for i in range(tries):
        if pause and i:
            time.sleep(pause)
        s = read()
        got = test(s)
        if got:
            return got, s
    raise Fail(f"waited for {what}, but {s.summary() if s else 'CTMS could not be read'}")


# ---------- the by-name moves every route is made of ----------
def open_menu(path, s=None):
    """C-TMS's menus by name: "C-TMS Modules > Order Management > Orders". Each level is read once it is open (its
    items have no place on the screen until then)."""
    parts = [p.strip() for p in re.split(r">|/", path) if p.strip()]
    if not parts:
        raise Fail("no menu given")
    partial = bool(_skips())                              # this route's reads skip things: a menu needs a whole one
    _WHOLE[0] += 1                                        # a menu is read whole, whatever the route skips
    try:
        _open_menu(path, parts, read() if partial or s is None else s)
    finally:
        _WHOLE[0] -= 1


def _open_menu(path, parts, s):
    top = s.one(f"menu '{parts[0]}'", name=parts[0], role="menu", window=1)
    act([click(top, after=0.6)], f"menu {parts[0]}")
    for depth, part in enumerate(parts[1:], 1):
        last = depth == len(parts) - 1
        el, s = until(lambda sc: sc.first(name=part, role=("menu", "menu item"), window=1),
                      f"menu item '{part}'", tries=4)
        if last:
            act([click(el, react=True, timeout=30, after=0.3)], f"menu {path}")
        else:
            act([click(el, after=0.6)], f"menu {part}")
    return path


def clear_to(el, s, what="it"):
    """Refuse a click that another CTMS window would catch."""
    over = s.covered(el)
    if over is not None:
        raise Fail(f"the '{clean(over.get('nm'))}' window lies over {what} - close or move it first")


def press(name, role=("push button", "page tab"), double=False, right=False, s=None, within=None, contains=False,
          react=False):
    """Click a button, tab or cell by its name (or a grid cell by its value) - one that is on the screen, enabled and
    not under another CTMS window."""
    s = s or read()
    got = s.find(name=name, role=role, enabled=True, within=within, contains=contains)
    if not got:
        got = s.find(value=name, role=role if role != ("push button", "page tab") else "text", within=within,
                     contains=contains)
    if len(got) > 1:                                      # the same name in two windows: the one on top, if only one shows
        shown = [e for e in got if s.covered(e) is None]
        if len(shown) == 1 and len({(s.frame_of(e) or {}).get("n") for e in got}) == len(got):
            got = shown
    if len(got) != 1:
        raise Fail(f"{'no' if not got else len(got)} {name!r} to press: "
                   + ("; ".join(f"{describe(e)} in {clean((s.frame_of(e) or {}).get('nm'))}" for e in got[:5])
                      if got else s.summary()))
    clear_to(got[0], s, repr(name))
    act([click(got[0], double=double, right=right, react=react, after=0.4)], f"press {name}")
    return got[0]


def tab(name, frame, s=None):
    """Bring one of a window's tabs up by name, and check it came: CTMS sometimes takes a click as focus only.
    -> (the tab, the screen with it up)."""
    s = s or read()
    for attempt in range(3):
        f = s.frame(frame) if isinstance(frame, str) else frame
        got = s.find(role="page tab", name=name, within=f)
        if not got:
            raise Fail(f"no '{name}' tab in {clean((f or {}).get('nm'))} ({s.summary()})")
        t = min(got, key=lambda e: e["at"][1])              # Planning has a second Finance tab below: the top row's
        if "selected" in (t.get("st") or []):
            return t, s
        clear_to(t, s, f"the '{name}' tab")
        act([click(t, after=1.0)], f"tab {name}")
        s = read()
        if isinstance(frame, dict):
            frame = clean(frame.get("nm"))
    raise Fail(f"the '{name}' tab didn't come up ({s.summary()})")


# ---------- orders: Order Summary and its search card ----------
ORDERS_MENU = "C-TMS Modules > Order Management > Orders"
SUMMARY_COLS = {"SCHED_NAME": "sched", "EXTERNAL_REF": "ref", "STATUS": "status", "DELIVERY_TYPE_ID": "type",
                "EARLY_AVAIL": "ready", "LATE_DEL": "deliver_by"}
COLUMN = re.compile(r"Enter value for : (\w+)")


def summary_rows(s):
    """Order Summary's result rows, top to bottom: [{ref, status, sched, type, ready, deliver_by, cells}]. Each column
    is read by its Forms name and lined up by row, never by pixel: the Locations tab's grid sits 6 px off the left one."""
    f = s.frame("Order Summary")
    if f is None:
        return []
    cols = {}
    for e in s.children(f):
        m = COLUMN.search(str(e.get("nm") or ""))
        if m and m.group(1) in SUMMARY_COLS and on_screen(e):
            cols.setdefault(SUMMARY_COLS[m.group(1)], []).append(e)
    for k in cols:
        cols[k].sort(key=lambda e: e["at"][1])
    rows = []
    for i in range(max((len(v) for v in cols.values()), default=0)):
        row = {"cells": {}}
        for k, cells in cols.items():
            if i < len(cells):
                row[k] = str(cells[i].get("v") or "")
                row["cells"][k] = cells[i]
        if row.get("ref"):
            rows.append(row)
    return rows


def ensure_orders(s=None):
    """Order Summary open with its search card up. -> the screen."""
    s = s or read()
    if s.frame("Order Summary") is None:
        open_menu(ORDERS_MENU, s)
        _, s = until(lambda sc: sc.frame("Order Search"), "the Order Search card", tries=5)
    if s.frame("Order Search") is None:
        summ = s.frame("Order Summary")
        act([click(s.one("Order Summary's Search button", name="Search", role="push button", within=summ),
                   after=1.0)], "order search card")
        _, s = until(lambda sc: sc.frame("Order Search"), "the Order Search card", tries=4)
    return s


def order_search(ref, s=None):
    """Search Order Summary by Customer Ref: every line of the order (ref% - an order's lines are -1-1, -2-1, its
    splits _S1...). -> (rows, screen)."""
    s = ensure_orders(s)
    card = s.frame("Order Search")
    box = s.one("the Customer Ref box", role="text", name="Enter a Customer Ref to search for", within=card)
    refresh = s.one("the search card's Refresh", role="push button", name="Refresh", within=card)
    want = str(ref).strip()
    act(fill(box, want if want.endswith("%") else base_ref(want) + "%")
        + [click(refresh, react=True, timeout=40, after=0.5)], f"order search {want}")
    s = read()
    return summary_rows(s), s


def base_ref(ref):
    """1234567-1-1_S2 -> 1234567; an ad hoc or DTS ref is searched whole."""
    m = re.match(r"(\d{7})(?:-\d+-\d+)?(?:_S\d+)?$", str(ref).strip())
    return m.group(1) if m else str(ref).strip()


GONE = ("CANCELLED", "ABORTED")      # a line CTMS has finished with: never changed (his 24/11)


def pick_line(rows, ref, gone=False):
    """Order Summary's row for `ref`. A Customer Ref can be on two lines - a CANCELLED one and the live one (a line on
    26/11: the cancelled one was listed first, and it was the one updated): the live line, unless `gone` (a restore wants
    the cancelled one). None when no row has that ref."""
    want = str(ref).strip().lower()
    exact = [r for r in rows if str(r.get("ref") or "").strip().lower() == want]
    done = [r for r in exact if str(r.get("status") or "").strip().upper() in GONE]
    live = [r for r in exact if r not in done]
    order = done + live if gone else live + done
    return order[0] if order else None


# his 26/11: "we don't do 75% cancellations ... we don't mention the price [in] special instructions either. We don't
# mention the price of the nonconformance either" - a 23/11 comment carried a haulier's 75% and its price, and he
# was told off for it
PRICE = re.compile(r"£|\bGBP\b|\bpounds?\b|\d\s*%|\bper ?cent\b", re.I)


def no_price(text, what):
    """A comment, note or non-conformance going into CTMS never carries a price, a charge or a percentage."""
    if PRICE.search(str(text or "")):
        raise Fail(f"no prices, charges or percentages in {what} (his 26/11 rule: we don't mention the price) - say it "
                   "without them")


def _row_text(r):
    return (f"{r.get('ref', ''):18} {r.get('status', ''):13} sched {r.get('sched', ''):7} {r.get('type', ''):10} "
            f"ready {r.get('ready', ''):15} deliver by {r.get('deliver_by', '')}")


def details_frame(s):
    return next((f for f in s.frames() if clean(f.get("nm")).startswith("Order details for")), None)


def open_order(ref, modify_scheduled=False, gone_ok=False):
    """The order's own window from Order Summary: its row found by its exact Cust Ref, its Status cell double-clicked
    (his tip: the most reliable cell). A scheduled order asks "already scheduled on a trip ... modify it?": without
    modify_scheduled that is answered Cancel and the route stops - nothing opened, nothing changed. A ref on two lines
    opens the live one (pick_line); a CANCELLED or ABORTED line is never opened unless gone_ok (the routes that only
    read)."""
    rows, s = order_search(ref)
    row = pick_line(rows, ref)
    if row is None:
        lines = ", ".join(r["ref"] for r in rows) or "none"
        raise Fail(f"no line {ref} in Order Summary (lines found: {lines})")
    if str(row.get("status") or "").strip().upper() in GONE and not gone_ok:
        raise Fail(f"{ref} is {row.get('status')} in CTMS - left alone, nothing opened (his rule: a cancelled or aborted "
                   "line is never touched)")
    card = s.frame("Order Search")
    steps = []
    if card is not None:                                  # it floats over the order's tabs once that opens: shut it first
        steps.append(click(s.one("the search card's Close", role="push button", name="Close", within=card), after=0.8))
    steps.append(click(row["cells"]["status"], double=True, after=1.5))
    act(steps, f"open {ref}")
    for _ in range(6):
        s = read()
        f = details_frame(s)
        if f is not None:
            return f, s, row
        asks = []
        q = s.question()                                  # CTMS asks inside its own window (seen 23/11)
        if q is not None:
            asks.append((q["words"], q["buttons"]))
        for b in s.boxes():
            asks.append((b["words"], {clean(e.get("nm")).split()[0].lower(): e for e in b["els"]
                                      if e.get("r") == "push button" and clean(e.get("nm"))}))
        for words, buttons in asks:
            if "scheduled" in words.lower() or "modify" in words.lower():
                if not modify_scheduled:
                    if "cancel" in buttons:
                        act([click(buttons["cancel"], after=0.8)], "not modifying a scheduled order")
                    raise Fail(f"{ref} is {row.get('status')}: CTMS asks '{words[:120]}'. Answered Cancel, nothing "
                               "opened (--modify to open it anyway; nothing is saved by opening it).")
                if "ok" not in buttons:
                    raise Fail(f"a question with no OK: {words[:120]}")
                act([click(buttons["ok"], after=1.5)], "open the scheduled order")
                break
            raise Fail(f"a question came up opening {ref}: {words[:160]} ({', '.join(buttons)}) - left up")
    raise Fail(f"{ref}'s window didn't open ({s.summary()})")


DISCARD = re.compile(r"discard|save (?:your )?changes|changes (?:have been|were) made|do you want to save", re.I)


def close_window(frame_name, s=None):
    """Close one CTMS window with its own Close button. If CTMS asks about unsaved changes, the answer is always the
    one that KEEPS them (Cancel) and the route stops: nobody's unsaved work is ever thrown away by a route."""
    s = s or read()
    f = s.frame(frame_name)
    if f is None:
        return False
    btn = s.find(name="Close", role="push button", within=f, enabled=True)
    if not btn:
        raise Fail(f"'{clean(f.get('nm'))}' has no Close button showing")
    clear_to(btn[-1], s, f"'{clean(f.get('nm'))}'s Close")
    act([click(btn[-1], after=1.0)], f"close {clean(f.get('nm'))}")
    for _ in range(3):
        s = read()
        q = s.question()
        asks = [(q["words"], q["buttons"].get("cancel"))] if q else []
        asks += [(b["words"], next((e for e in b["els"] if e.get("r") == "push button"
                                    and clean(e.get("nm")).lower() == "cancel"), None)) for b in s.boxes()]
        for words, keep in asks:
            if DISCARD.search(words):
                if keep is not None:
                    act([click(keep, after=0.8)], "keep the unsaved changes")
                raise Fail(f"'{clean(f.get('nm'))}' has unsaved changes (CTMS: '{words[:100]}'). Left it open, "
                           "changes kept - save or discard them by hand.")
        if s.frame(clean(f.get("nm"))) is None:
            return True
    raise Fail(f"'{clean(f.get('nm'))}' didn't close ({s.summary()})")


def close_orders(s=None):
    """Every open order window closed (none with unsaved changes - see close_window)."""
    s = s or read()
    n = 0
    while True:
        f = details_frame(s)
        if f is None:
            return n
        close_window(clean(f.get("nm")), s)
        n += 1
        s = read()
        if n > 5:
            raise Fail("order windows keep coming back")


def _after(s, el, k=1):
    """The element k places after el in the tree (a time box after its date box, a name after its code)."""
    i = next((j for j, e in enumerate(s.els) if e.get("n") == el.get("n")), None)
    return s.els[i + k] if i is not None and i + k < len(s.els) else {}


ITEM_COLS = ("Product Type", "DU Type", "Qty", "Weight", "Cases", "RPE", "Packed", "Despatched", "Delivered", "Volume",
             "Special Flag")


def read_detail(s, f):
    """The order window's header and its Detail tab, as plain values."""
    kids = [e for e in s.children(f) if on_screen(e)]

    def val(name, role=None):
        e = next((e for e in kids if clean(e.get("nm")) == name and (role is None or e.get("r") == role)), None)
        return str(e.get("v") or "").strip() if e else ""

    def pair(name):
        e = next((e for e in kids if clean(e.get("nm")) == name), None)
        if not e:
            return {}
        return {"code": str(e.get("v") or "").strip(), "name": str(_after(s, e).get("v") or "").strip()}

    def window(name):
        e = next((e for e in kids if clean(e.get("nm")) == name), None)
        if not e:
            return ""
        d1, t1, d2, t2 = (str(_after(s, e, k).get("v") or "").strip() for k in (0, 1, 2, 3))
        return f"{d1} {t1} - {d2} {t2}".strip()

    booked = next((e for e in kids if clean(e.get("nm")) == "Booked In" and e.get("r") == "check box"), None)
    strategy = next((str(e.get("v")) for e in kids if str(e.get("v") or "").startswith("Strategy")), "")
    cols = {c: sorted((e for e in kids if clean(e.get("nm")) == c and e.get("r") == "text"), key=lambda e: e["at"][1])
            for c in ITEM_COLS}
    items = []
    for i in range(max((len(v) for v in cols.values()), default=0)):
        line = {c: str(cols[c][i].get("v") or "").strip() for c in ITEM_COLS if i < len(cols[c])}
        if line.get("Product Type"):
            items.append(line)
    return {"window": clean(f.get("nm")), "status": val("Status"), "oms": val("Oms Ref"), "ref": val("Customer Ref"),
            "booking_ref": val("Booking Ref"), "booked_in": bool(booked and "checked" in (booked.get("st") or [])),
            "cost_centre": val("Cost Centre"), "customer": val("Customer"), "schedule": val("Schedule"),
            "collect_from": pair("Collect From"), "deliver_to": pair("Deliver To"),
            "collect": window("Collect Times"), "deliver": window("Delivery Times"),
            "veh_type": val("Veh Type"), "service_level": val("Service Level"), "business_type": strategy,
            "special_instructions": val("Special Instructions"), "items": items}


def _rows_by_y(cells, gap=10):
    """Cells grouped into rows, top to bottom: a new row when a cell sits more than gap px below the row's top."""
    rows, top = [], None
    for c in sorted(cells, key=lambda e: (e["at"][1], e["at"][0])):
        if top is None or c["at"][1] - top > gap:
            rows.append([])
            top = c["at"][1]
        rows[-1].append(c)
    return rows


def header_grid(s, within, headers):
    """A grid whose cells have no names (Services): each cell's column is the header button above it, by x; rows by y.
    -> [{header: value}] for the rows with anything in them."""
    kids = [e for e in s.children(within) if on_screen(e)]
    heads = [e for e in kids if e.get("r") == "push button" and clean(e.get("nm")) in headers]
    if not heads:
        return []
    below = max(h["at"][1] for h in heads)
    cells = [e for e in kids if e.get("r") in ("text", "combo box") and e["at"][1] > below]
    out = []
    for row in _rows_by_y(cells):
        line = {}
        for c in row:
            cx = c["at"][0] + c["at"][2] // 2
            h = next((h for h in heads if h["at"][0] <= cx < h["at"][0] + h["at"][2]), None)
            if h is not None and str(c.get("v") or "").strip():
                line[clean(h.get("nm"))] = str(c.get("v")).strip()
        if line:
            out.append(line)
    return out


def named_grid(s, within, names):
    """A grid whose cells carry their column's name (Trip Detail, Order Items, Non Conformance) -> [{name: value}]."""
    kids = [e for e in s.children(within) if on_screen(e) and e.get("r") == "text"]
    cols = {n: sorted((e for e in kids if clean(e.get("nm")) == n), key=lambda e: e["at"][1]) for n in names}
    out = []
    for i in range(max((len(v) for v in cols.values()), default=0)):
        line = {n: str(cols[n][i].get("v") or "").strip() for n in names if i < len(cols[n])}
        if any(line.values()):
            out.append({k: v for k, v in line.items() if v})
    return out


def named_values(s, within, names):
    """The first box of each name under within -> {name: value} (blank ones left out)."""
    kids = [e for e in s.children(within) if on_screen(e)]
    out = {}
    for n in names:
        e = next((e for e in kids if clean(e.get("nm")) == n), None)
        if e is not None and str(e.get("v") or "").strip():
            out[n] = str(e.get("v")).strip()
    return out


TABS = {
    # route's word: (the tab's name in CTMS, how it is read)
    "services": ("Services", lambda s, t: header_grid(s, t, ("Service Id", "Name", "Qty", "Value", "Adjusted Value",
                                                               "Inherited"))),
    "trip": ("Trip Detail", lambda s, t: named_grid(s, t, ("Sched", "Trip ID", "Carrier ID", "Trip Status", "Trip Cost",
                                                           "Load Location", "Unload Location", "Consignor",
                                                           "Consignee"))),
    "items": ("Order Items", lambda s, t: named_grid(s, t, ("Identifier", "Product", "Item Description", "Ordered",
                                                            "To Deliver", "Delivered", "Diff", "Weight",
                                                            "Location"))),
    "add": ("Add Detail", lambda s, t: named_values(s, t, ("Delivery Type", "Order Comments", "Last Error",
                                                           "STD Cost Data", "Revenue Data", "Lane Comments",
                                                           "Interface Id", "Original From", "Final To"))),
    "loc": ("LOC Detail", lambda s, t: [named_values_at(s, t, x) for x in ("left", "right")]),
    "refs": ("Add Refs", lambda s, t: header_grid(s, t, ("Additional Reference", "Value"))),
    "finance": ("Finance", lambda s, t: named_values(s, t, ("Currency", "Cost", "Revenue", "Allocated from Trip",
                                                            "Standard Cost", "VS Revenue"))),
    "nc": ("Non Conformance", lambda s, t: named_grid(s, t, ("Schedule Name", "Trip ID", "Reason", "Description",
                                                             "Reason Comments", "Qty", "DU Type", "Product Type",
                                                             "Created By", "Created Date"))),
}
LOC_FIELDS = ("Location Id", "Location Name", "Address Line1", "Address Line2", "Address Line3", "Town", "Postcode",
              "Phone", "Contact", "Comments", "Email Address")


def named_values_at(s, within, side):
    """LOC Detail has the collection point on the left and the delivery point on the right, with the same names."""
    kids = [e for e in s.children(within) if on_screen(e)]
    ids = sorted((e for e in kids if clean(e.get("nm")) == "Location Id"), key=lambda e: e["at"][0])
    mid = (ids[0]["at"][0] + ids[-1]["at"][0]) / 2 + 1 if len(ids) >= 2 else 600
    out = {"point": "collect" if side == "left" else "deliver"}
    for n in LOC_FIELDS:
        got = [e for e in kids if clean(e.get("nm")) == n and ((e["at"][0] < mid) == (side == "left"))]
        if got and str(got[0].get("v") or "").strip():
            out[n] = str(got[0].get("v")).strip()
    return out


def read_tabs(words, frame_name):
    """Each named tab brought up and read: {word: what it holds}. Ends back on Detail."""
    out = {}
    for w in words:
        name, reader = TABS[w]
        t, s = tab(name, frame_name)
        out[w] = reader(s, t)
    tab("Detail", frame_name)
    return out


def _short(v, n=160):
    v = re.sub(r"\s+", " ", str(v)).strip()
    return v if len(v) <= n else v[:n] + "..."


def print_tabs(got):
    for w, v in got.items():
        print(f"  [{TABS[w][0]}]" + ("" if v else " (nothing)"))
        for line in (v if isinstance(v, list) else [v] if v else []):
            print("    " + ("; ".join(f"{k}: {_short(x)}" for k, x in line.items()) if isinstance(line, dict)
                            else _short(line)))


def print_detail(d):
    print(f"{d['ref']}  OMS {d['oms']}  {d['status']}  booking ref {d['booking_ref'] or '-'}"
          f"{'  (booked in)' if d['booked_in'] else ''}")
    print(f"  collect {d['collect_from'].get('code', '')} {d['collect_from'].get('name', '')}  {d['collect']}")
    print(f"  deliver {d['deliver_to'].get('code', '')} {d['deliver_to'].get('name', '')}  {d['deliver']}")
    print(f"  vehicle {d['veh_type'] or '(blank)'}   {d['business_type']}   cost centre {d['cost_centre']}")
    for it in d["items"]:
        print(f"  item {it.get('Product Type', '')} {it.get('DU Type', '')} qty {it.get('Qty', '').strip()} "
              f"weight {it.get('Weight', '').strip()}")
    print(f"  special instructions: {d['special_instructions']}")


# ---------- trips: Planning's tree, its Find box ----------
PLANNING_MENU = "C-TMS Modules > Trip Management > Planning"
TREE_ROW = re.compile(r"^Level \d+\s+(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s+(M[AF][NR]-\d{8})\S*\s.*?\(([A-Z][A-Z _]*)\)\s*$")


def tree_rows(s):
    """Planning's manifest tree: [{man, day, time, status, selected, el}] as the Access Bridge labels them ('Level 0
    18/11/26 10:00 MAN-01000001  (ACCEPTED)'), placed or scrolled away."""
    out = []
    for e in s.els:
        m = TREE_ROW.match(str(e.get("nm") or ""))
        if e.get("r") == "label" and m:
            out.append({"man": m.group(3), "day": m.group(1), "time": m.group(2), "status": m.group(4).strip(),
                        "selected": "selected" in (e.get("st") or []), "el": e})
    return out


def man_number(text):
    m = re.search(r"(\d{8})", str(text))
    if not m:
        raise Fail(f"'{text}' isn't a manifest number (MAN-01234567)")
    return m.group(1)


SAFE_TO_CLOSE = ("Order Search", "Order Summary", "FIND", "Find Trip")   # windows that hold no typing of anyone's
CANCEL_BOXES = ("Trailer Type", "Delivery Types")         # small boxes whose Cancel takes nothing
OWN_BOXES = {"Planning": ("FIND", "Find Trip", "Planned Orders", "Payments for Trip", "Order Revenue for trip"),
             "Order Summary": ("Order Search", "Split Order")}   # a window's own boxes, which sit on top of it


def bring_forward(name, s=None):
    """Make one CTMS window the top one: a click on its own title strip if that shows, else the windows over it closed
    when they are ones that hold nobody's typing (Order Summary, its search card, Find); an order window over it is
    closed only if it has nothing unsaved (close_window stops otherwise). -> the screen."""
    s = s or read()
    for _ in range(4):
        f = s.frame(name)
        if f is None:
            raise Fail(f"no '{name}' window open")
        above = []
        for g in s.frames():
            if g.get("n") == f.get("n"):
                break
            above.append(clean(g.get("nm")))
        if all(a.startswith(OWN_BOXES.get(name, ("\0",))) for a in above):
            return s                                      # nothing over it but its own boxes (Planning's FIND)
        x, y, w, h = f["at"]
        strip = {"at": [x + 60, y + 2, min(300, w - 120), 14], "n": f.get("n"), "lv": f.get("lv", 0) + 1}
        over = None
        for g in s.frames():
            if g.get("n") == f.get("n"):
                break
            gx, gy, gw, gh = g["at"]
            cx, cy = centre(strip)
            if gx <= cx < gx + gw and gy <= cy < gy + gh:
                over = g
                break
        top = s.frames()[0] if s.frames() else None
        if top is not None and clean(top.get("nm")).startswith(CANCEL_BOXES):
            cancel_box(clean(top.get("nm")), s)           # a small box left up: its Cancel takes nothing
        elif over is None:
            act([click(strip, after=0.6)], f"bring {name} forward")
        elif clean(over.get("nm")).startswith(SAFE_TO_CLOSE):
            close_window(clean(over.get("nm")), s)
        elif clean(over.get("nm")).startswith("Order details for"):
            close_window(clean(over.get("nm")), s)          # stops, changes kept, if it has unsaved ones
        else:
            raise Fail(f"'{clean(over.get('nm'))}' lies over {name} - close it first")
        s = read()
    raise Fail(f"couldn't bring {name} to the front ({s.summary()})")


def ensure_planning(s=None):
    s = s or read()
    if s.frame("Planning") is None:
        open_menu(PLANNING_MENU, s)
        _, s = until(lambda sc: sc.frame("Planning"), "Planning", tries=8, pause=1.0)
    return bring_forward("Planning", s)


def set_list(s, frame, value, combo_name=None):
    """A Forms list box set by typing the first letter of what's wanted and reading it back each time (a list opens
    on its last row; scrolling it with arrows took two minutes on 16/11). -> the screen with it set."""
    def combo_of(sc):
        f = sc.frame(frame)
        got = sc.find(role="combo box", within=f, name=combo_name) if combo_name else sc.find(role="combo box", within=f)
        return got[0] if got else None
    c = combo_of(s)
    if c is None:
        raise Fail(f"no list box in '{frame}'")
    if str(c.get("v") or "").strip() == value:
        return s
    act([click(c, after=0.8)], f"open the list in {frame}")
    s = read()
    opts = [e for lst in s.find(role="list") for e in s.children(lst)
            if e.get("r") == "label" and on_screen(e) and clean(e.get("nm")) == value]
    if len(opts) == 1:                                    # the list's own line, clicked by its name (seen 23/11)
        act([click(opts[0], after=0.6)], f"'{value}' in the list")
        s = read()
        c = combo_of(s)
        if c is not None and str(c.get("v") or "").strip() == value:
            return s
    for _ in range(40):
        act([typed(value[0], after=0.4)], f"'{value[0]}' in the list")
        s = read()
        c = combo_of(s)
        if c is not None and str(c.get("v") or "").strip() == value:
            act([key("enter", after=0.6)], "take it")
            s = read()
            c = combo_of(s)
            if c is not None and str(c.get("v") or "").strip() == value:
                return s
            raise Fail(f"after Enter the list in '{frame}' reads {c.get('v') if c else None!r}, not {value!r}")
    raise Fail(f"the list in '{frame}' never came to {value!r} - left open for a look")


def find_trip(field, value):
    """Planning's Find box: the field picked, the value typed, Find pressed. -> ("selected", tree row) when the tree
    jumped to one trip, ("list", the Find Trip box's words) when several match, or raises when none do."""
    s = ensure_planning()
    if s.frame("FIND") is None:
        planning = s.frame("Planning")
        btn = s.one("Planning's Find", role="push button", name="Find", within=planning)
        clear_to(btn, s, "Planning's Find")
        act([click(btn, after=1.5)], "Planning Find")
        _, s = until(lambda sc: sc.frame("FIND"), "the FIND box", tries=6, pause=0.5)
    s = set_list(s, "FIND", field)
    f = s.frame("FIND")
    box = next((e for e in s.find(role="text", within=f) if "read-only" not in (e.get("st") or [])), None)
    if box is None:
        raise Fail("the FIND box has no place to type")
    act(fill(box, value), "FIND value")
    s = read()
    f = s.frame("FIND")
    typed_in = next((str(e.get("v") or "").strip() for e in s.find(role="text", within=f)
                     if "read-only" not in (e.get("st") or [])), "")
    if typed_in != value:
        raise Fail(f"the FIND box reads {typed_in!r}, not {value!r} - left up")
    go = s.one("FIND's Find", role="push button", name="Find", within=f)
    act([click(go, after=3.0)], "Find")
    for _ in range(10):
        s = read()
        listed = s.frame("Find Trip")
        if listed is not None:
            words = [str(e.get("v") or e.get("nm") or "") for e in s.children(listed)
                     if on_screen(e) and e.get("r") in ("text", "label") and (e.get("v") or e.get("nm"))]
            return "list", words, s
        for b in s.boxes():
            raise Fail(f"CTMS says: {b['words'][:160]}")
        q = s.question()
        if q is not None and "no entries" in q["words"].lower() and "ok" in q["buttons"]:
            act([click(q["buttons"]["ok"], after=0.8)], "OK: nothing found")
            s = read()
            f = s.frame("FIND")
            if f is not None:
                cancel = s.find(name="Cancel", role="push button", within=f)
                if cancel:
                    act([click(cancel[0], after=0.8)], "close FIND")
            raise Fail(f"Find by {field} = {value} found nothing"
                       + (" (a DHL NOC trip, or one made today, has no EFX ref - find it by one of its lines: "
                          "trip-find --order <line ref>)" if field.startswith("EFX") else ""))
        if q is not None:
            raise Fail(f"CTMS asks: {q['words'][:160]} - left up for a look")
        if s.frame("FIND") is None:
            picked = [r for r in tree_rows(s) if r["selected"]]
            return "selected", picked, s
        time.sleep(0.5)
    raise Fail(f"the FIND box is still up ({s.summary()})")


TRIP_LEFT = (("Owning Depot", 0), ("Cost Centre", 23), ("Trip Ref", 50), ("Route Code", 78), ("Status", 108),
             ("Carrier", 138), ("Carrier Ref", 168), ("PO Number", 198))   # px below Owning Depot, read off 23/11


def read_trip_detail(s, t):
    """Planning's Trip Detail tab. Its boxes have no names of their own (most read 'Enter value for : TRIP_STATUS'),
    so the left column is read by its place under Owning Depot, which has one."""
    kids = [e for e in s.children(t) if on_screen(e) and e.get("r") == "text"]
    anchor = next((e for e in kids if clean(e.get("nm")) == "Owning Depot"), None)
    out = {}
    if anchor is not None:
        col = [e for e in kids if abs(e["at"][0] - anchor["at"][0]) <= 6]
        for label, dy in TRIP_LEFT:
            want = anchor["at"][1] + dy
            e = min(col, key=lambda c: abs(c["at"][1] - want), default=None)
            if e is not None and abs(e["at"][1] - want) <= 9:
                out[label] = str(e.get("v") or "").strip()
    dt = next((e for e in kids if "Delivery Type" in str(e.get("nm") or "")), None)
    if dt is not None:
        out["Delivery Type"] = str(dt.get("v") or "").strip()
    return out


STOP_COLS = ("P Arr", "P Dep", "A Arr", "A Dep", "Type", "Location", "Trailer Type", "Trailer Id", "Wait")


def read_stops(s, t):
    """Planning's Stops tab: each stop's planned and actual times, type (SU start, CL collect, DL deliver...),
    location and trailer. The stop number and date have no names: they are the cells left of P Arr on the row."""
    rows = named_grid(s, t, STOP_COLS)
    kids = [e for e in s.children(t) if on_screen(e) and e.get("r") == "text" and not clean(e.get("nm"))]
    parr = sorted((e for e in s.children(t) if on_screen(e) and clean(e.get("nm")) == "P Arr"), key=lambda e: e["at"][1])
    for i, row in enumerate(rows):
        if i < len(parr):
            y = parr[i]["at"][1]
            left = sorted((e for e in kids if abs(e["at"][1] - y) <= 3 and e["at"][0] < parr[i]["at"][0]),
                          key=lambda e: e["at"][0])
            vals = [str(e.get("v") or "").strip() for e in left if str(e.get("v") or "").strip()]
            if vals:
                row["Stop"] = vals[0]
            if len(vals) > 1:
                row["Date"] = vals[1]
    return rows


def read_trip_status(s, t):
    hist = header_grid(s, t, ("Action", "Trip Status", "Carrier", "Action Date", "Actioned By"))
    sent = named_values(s, t, ("Manifest Sent",))
    return {"history": hist, **sent}


def read_trip_finance(s, t):
    """Planning's Finance tab: the trip's cost, its VAT, revenue. The cost boxes have no names: the first two
    values in the Currency column are cost and its VAT (read 23/11)."""
    kids = [e for e in s.children(t) if on_screen(e) and e.get("r") == "text"]
    cur = next((e for e in kids if clean(e.get("nm")) == "Currency"), None)
    out = named_values(s, t, ("Currency", "Trip Revenue", "VAT"))
    if cur is not None:
        col = sorted((e for e in kids if abs(e["at"][0] - cur["at"][0]) <= 6 and e["at"][1] > cur["at"][1]),
                     key=lambda e: e["at"][1])
        if col:
            out["Trip Cost"] = str(col[0].get("v") or "").strip()
        if len(col) > 1:
            out["Cost VAT"] = str(col[1].get("v") or "").strip()
    return out


PAYMENTS = "Payments for Trip"


def _amount(text):
    try:
        return float(str(text).replace(",", "").strip() or 0)
    except ValueError:
        return None


def payment_lines(s):
    """The carrier's Payments window: ([{"cells": [left to right], "amount", "el"}], total) - its rows are the ones
    with an AMOUNT, read by their place (the grid's cells have no other names); 30/10's pay_clear.py read it so."""
    f = s.frame(PAYMENTS)
    if f is None:
        return None, None
    part = [e for e in s.children(f) if on_screen(e) and e.get("r") == "text"]
    amounts = [e for e in part if "AMOUNT" in str(e.get("nm") or "") and str(e.get("v") or "").strip()]
    rows = []
    for line in _rows_by_y(amounts, gap=3):              # two AMOUNT cells a row (the amount and its VAT): one row
        a_el = min(line, key=lambda e: e["at"][0])        # the amount is the left one
        y = a_el["at"][1]
        cells = sorted((e for e in part if abs(e["at"][1] - y) <= 3), key=lambda e: e["at"][0])
        rows.append({"cells": [str(e.get("v") or "").strip() for e in cells], "amount": _amount(a_el.get("v")),
                     "el": cells[0], "amount_el": a_el})
    total = next((str(e.get("v") or "").strip() for e in part if clean(e.get("nm")) == "Total"), "")
    return rows, total


HAULAGE = re.compile(r"\s*trip haul", re.I)   # "Trip Haulage" - or "Trip Haul Ma" on a trip Book made (23/11)


def haulage_lines(rows):
    """The carrier's haulage line(s) among a trip's payment rows, by their type: "Trip Haulage", or "Trip Haul Ma" as both
    the grid and its Edit box show it on a trip Book made (MAN of 23/11: the route took only "Trip Haulage" and refused)."""
    return [r for r in rows if any(HAULAGE.match(str(c or "")) for c in r["cells"])]


def price_plan(rows, want):
    """How a trip's carrier lines come to want: (the haulage row, the other lines' sum, the haulage's new amount). The
    other lines - a carrier's HIAB, NIGHT, SAT, SUN, escort - stay; only the haulage moves (his rule: a quote is the
    trip's TOTAL). Fail unless there is exactly one haulage line and the others leave it something."""
    haul = haulage_lines(rows)
    if len(haul) != 1:
        raise Fail(f"{len(haul)} haulage lines - a price change needs exactly one (lines: "
                   + "; ".join(" ".join(c for c in r["cells"][2:4] if c) or "?" for r in rows) + ")")
    others = round(sum(r["amount"] or 0 for r in rows if r is not haul[0]), 2)
    new = round(want - others, 2)
    if new <= 0:
        raise Fail(f"the other lines already come to {others:.2f} - more than {want:.2f}")
    return haul[0], others, new


def cut_short(name, tab_name):
    """Whether a name is only what is left of "<tab> tab page" once the Access Bridge cut it off. Late on 23/11 the
    carrier's Payments on Planning's Finance tab read "Finance tab page Finance tab page ... Finance tab p": the name
    gains a prefix as the tab is used, and in time ends before its own word."""
    n = str(name or "").strip()
    return bool(n) and f"{tab_name} tab page".startswith(n)


def carrier_payments(s, t):
    """The carrier's Payments on Planning's Finance tab, or None: the button on the revenue figure's row, left of it - the
    one right of it is the revenue's Payments, and Calc Costs (never pressed) sits under that. Its name reads "Payments"
    or is cut short (23/11, when the old by-name pick opened Order Revenue instead)."""
    pays = [e for e in s.find(role="push button", within=t)
            if clean(e.get("nm")) == "Payments" or cut_short(clean(e.get("nm")), "Finance")]
    rev = s.first(name="Trip Revenue", within=t)
    if rev is not None:
        mid = rev["at"][1] + rev["at"][3] / 2
        row = [e for e in pays if abs(e["at"][1] + e["at"][3] / 2 - mid) <= 10 and e["at"][0] + e["at"][2] <= rev["at"][0]]
        return row[0] if len(row) == 1 else None
    named = sorted((e for e in pays if clean(e.get("nm")) == "Payments"), key=lambda e: e["at"][0])
    return named[0] if len(named) == 2 else None


def open_payments():
    """Planning's Finance tab, then the carrier's Payments (the left-hand one: the right one is revenue).
    -> (rows, total, screen)."""
    t, s = tab("Finance", "Planning")
    pay = carrier_payments(s, t)
    if pay is None:
        raise Fail("couldn't tell the carrier's Payments on Planning's Finance tab (buttons: "
                   + "; ".join(f"{clean(e.get('nm'))!r} at {e['at'][:2]}" for e in s.find(role="push button", within=t))
                   + ")")
    clear_to(pay, s, "the carrier's Payments")
    act([click(pay, after=2.0)], "carrier Payments")
    _, s = until(lambda sc: sc.frame(PAYMENTS), "the Payments window", tries=6, pause=0.8)
    rows, total = payment_lines(s)
    return rows, total, s


def close_payments(s=None):
    s = s or read()
    f = s.frame(PAYMENTS)
    if f is None:
        return
    btn = s.find(name="Close", role="push button", within=f)
    if btn:
        act([click(btn[0], after=1.0)], "close Payments")


def trip_tabs(words):
    readers = {"detail": ("Trip Detail", read_trip_detail), "stops": ("Stops", read_stops),
               "status": ("Status", read_trip_status), "finance": ("Finance", read_trip_finance)}
    out = {}
    for w in words:
        name, fn = readers[w]
        t, s = tab(name, "Planning")
        out[w] = fn(s, t)
    tab("Trip Detail", "Planning")
    return out


STATUS_TPL = {"planned": "st-planned", "accepted": "st-accepted", "abandoned": "st-abandoned"}
TREE_MENU = (190, 25, 430, 10000)       # a manifest's right-click menu, in the recipes' picture pixels (ctms_book's)
STATUS_MENU = (380, 25, 560, 10000)     # its Set Status list (seen 23/11: Planned ... Abandoned)
NEAR_START = 80                         # minutes: his rule, ask him before touching a manifest this close to its start


def tpl_find(name, box, **kw):
    """A find step for a template of CTMS's own words (ctms_templates.json): right-click menus aren't in the Access
    Bridge, so they are found by their picture (Book does the same)."""
    t = R.load_templates()
    if name not in t:
        raise Fail(f"no template '{name}'")
    tp = t[name]
    return dict({"action": "find", "name": name, "box": list(box), "tpl": tp["rgb"], "tw": tp["w"], "th": tp["h"],
                 "timeout": 3}, **kw)


def _starts_in(row, now=None):
    """Minutes until a tree row's trip starts (negative once started), or None."""
    from datetime import datetime
    try:
        start = datetime.strptime(f"{row['day']} {row['time']}", "%d/%m/%y %H:%M")
    except (KeyError, ValueError):
        return None
    return (start - (now or datetime.now())).total_seconds() / 60


def set_status(man, target, commit, near_ok=False):
    """Set Status on the manifest selected in the tree: one OK, Save, read back - never retried (his rule 31/10 and
    17/11: a second try hit 'locked' and an abandon that didn't take had to be his). Without commit the menu path is
    checked as far as the item and closed with Escape: nothing chosen."""
    target = target.lower()
    if target not in STATUS_TPL:
        raise Fail(f"status '{target}' - the routes set {', '.join(STATUS_TPL)}")
    s = read()
    rows = [r for r in tree_rows(s) if r["selected"]]
    if len(rows) != 1 or man_number(rows[0]["man"]) != man_number(man):
        raise Fail(f"the tree hasn't got {man} selected (selected: {[r['man'] for r in rows]})")
    row = rows[0]
    if row["status"].lower() == target:
        return {"status": row["status"], "changed": False, "said": f"{row['man']} is already {row['status']}"}
    mins = _starts_in(row)
    if mins is not None and 0 <= mins <= NEAR_START and not near_ok:
        raise Fail(f"{row['man']} starts in {mins:.0f} min - his rule: ask him first inside {NEAR_START} min "
                   "(--near-start once he has said so)")
    clear_to(row["el"], s, "the trip's row")
    pt = centre(row["el"])
    path = [{"action": "anchor"}, {"action": "click", "screen": pt, "after": 0.5},
            {"action": "click", "screen": pt, "right": True, "after": 0.5},
            tpl_find("mt-set-status", TREE_MENU, click=True, after=0.6)]
    if not commit:
        act(path + [tpl_find(STATUS_TPL[target], STATUS_MENU)] + [key("escape", after=0.3)] * 3,
            f"check Set Status > {target}")
        return {"status": row["status"], "changed": False,
                "said": f"{row['man']} {row['status']} -> {target.upper()}: the menu path is there; nothing chosen "
                        "(no --commit)"}
    act(path + [tpl_find(STATUS_TPL[target], STATUS_MENU, click=True, after=1.0)], f"Set Status > {target}")
    q = None
    for _ in range(4):
        s = read()
        q = s.question()
        if q is not None:
            break
    if q is None:
        raise Fail(f"Set Status > {target} asked nothing - {row['man']} is still {row['status']}; look at it "
                   "before anything else")
    if target.upper() not in q["words"].upper() or "ok" not in q["buttons"]:
        raise Fail(f"CTMS asked something else: '{q['words'][:150]}' - left up, nothing pressed")
    planning = s.frame("Planning")
    act([click(q["buttons"]["ok"], react=True, timeout=20, after=0.8)], "OK (once)")
    s = read()
    save = s.find(name="Save", role="push button", within=s.frame("Planning"), enabled=True)
    if save:
        act([click(save[0], after=1.0)], "Planning Save")
    for _ in range(5):
        s, _q = settle(read(), "Planning")               # "Missed delivery window": OK'd, saved again once
        now = next((r for r in tree_rows(s) if man_number(r["man"]) == man_number(man)), None)
        if now and now["status"].lower() == target:
            return {"status": now["status"], "changed": True, "said": f"{now['man']} is now {now['status']}"}
        time.sleep(0.8)
    raise Fail(f"{man} did not read back as {target.upper()} after one OK and Save - NOT retried (his rule): look at "
               "it in Planning" + (f" (planning: {clean(planning.get('nm'))})" if planning else ""))


# ---------- a trip's Planned Orders: unschedule ----------
PLANNED = "Planned Orders"


def close_x(name, s=None):
    """A CTMS window that has no Close button of its own (Planned Orders) shut with its corner X: the X's place
    worked out from the window's own place (the research's (1478,455) on a window at 483,442 1006x332)."""
    s = s or read()
    f = s.frame(name)
    if f is None:
        return
    x, y, w, h = f["at"]
    act([{"action": "click", "screen": [x + w - 11, y + 12], "after": 1.0}], f"close {name}")
    s = read()
    if s.frame(name) is not None:
        raise Fail(f"'{name}' didn't close with its X - close it by hand")


def planned_orders():
    """The selected trip's orders: Stops > Orders opens Planned Orders. -> ([{seq, activity, ref, to, service, el}],
    screen)."""
    t, s = tab("Stops", "Planning")
    if s.frame(PLANNED) is None:
        btn = s.one("Stops' Orders button", role="push button", name="Orders", within=t)
        clear_to(btn, s, "Stops' Orders")
        act([click(btn, after=2.0)], "Stops > Orders")
        _, s = until(lambda sc: sc.frame(PLANNED), "Planned Orders", tries=5, pause=0.6)
    rows = named_grid(s, s.frame(PLANNED), ("Seq", "Activity", "Cust Ref", "To Location", "Service"))
    refs = sorted((e for e in s.children(s.frame(PLANNED)) if on_screen(e) and clean(e.get("nm")) == "Cust Ref"
                   and str(e.get("v") or "").strip()), key=lambda e: e["at"][1])
    out = []
    for r, el in zip(rows, refs):
        out.append({"seq": r.get("Seq", ""), "activity": r.get("Activity", ""), "ref": r.get("Cust Ref", ""),
                    "to": r.get("To Location", ""), "service": r.get("Service", ""), "el": el})
    return out, s


def _menu_box(el, below=600, above=700):
    """Where a right-click menu opens round a clicked element, generously, in the picture's pixels: below it, or above
    it when the row is low on the screen (the well's menu opened upward, 23/11)."""
    x, y = centre(el)
    return (max(0, x - 300), max(0, y - above), x + 520, y + below)


TRAILER_BOX = "Trailer Type"


def cancel_box(name, s=None):
    """A small CTMS box shut by its own Cancel, nothing taken."""
    s = s or read()
    f = s.frame(name)
    if f is None:
        return
    btn = s.find(name="Cancel", role="push button", within=f)
    if btn:
        act([click(btn[0], after=0.8)], f"Cancel {name}")


def well_row(s, ref):
    """Planning's order well: the Cust Ref cell of ref, found under the well's own Cust Ref header (not the Order
    Summary's), or None when the well doesn't show it (its Sched From/To or Order Filters keep it out)."""
    pl = s.frame("Planning")
    heads = [e for e in s.children(pl) if e.get("r") == "push button" and clean(e.get("nm")) == "Cust Ref"]
    if not heads:
        return None
    h = max(heads, key=lambda e: e["at"][1])
    for e in s.children(pl):
        if (e.get("r") == "text" and on_screen(e) and str(e.get("v") or "").strip().upper() == ref.upper()
                and h["at"][0] <= e["at"][0] + e["at"][2] // 2 < h["at"][0] + h["at"][2] and e["at"][1] > h["at"][1]):
            return e
    return None


# ---------- Order Summary's right-click menu: split ----------
SUMMARY_MENU = (100, 150, 400, 10000)   # where its menu opens, in the recipes' picture pixels (seen 23/11)
SPLIT_BOX = "Split Order"


def summary_menu(row, item, s):
    """A line in Order Summary right-clicked and one item of its menu clicked by the item's picture (the menu isn't in
    the Access Bridge). The search card is shut first: it floats over the rows' right-hand side."""
    card = s.frame("Order Search")
    if card is not None:
        act([click(s.one("the search card's Close", role="push button", name="Close", within=card), after=0.8)],
            "close the card")
        s = read()
        row = next((r for r in summary_rows(s) if r["ref"] == row["ref"]), None)
        if row is None:
            raise Fail("the line went from Order Summary when the card closed")
    cell = row["cells"]["ref"]
    clear_to(cell, s, f"{row['ref']}'s row")
    act([click(cell, after=0.5), click(cell, right=True, after=0.6),
         tpl_find(item, SUMMARY_MENU, click=True, after=1.5)], f"{row['ref']}: {item}")


def exit_box(name, s=None):
    """Split Order / Copy Order shut with nothing done. Learnt live 23/11: Exit with No of Orders filled asks
    "Information has been entered - continue to split the order?", and that question's Cancel empties the box (OK would
    carry on - never pressed); the window's own Cancel empties it too; Exit on an empty box just closes it."""
    for _ in range(5):
        s = s or read()
        q = s.question()
        if q is not None and ("continue" in q["words"].lower() or "information has been entered" in q["words"].lower()):
            if set(q["buttons"]) != {"ok", "cancel"}:
                raise Fail(f"the question has buttons {sorted(q['buttons'])} - left up for a look")
            act([click(q["buttons"]["cancel"], after=1.0)], "don't carry on")
            s = None
            continue
        if s.frame(name) is None:
            return
        box = s.frame(name)
        filled = [e for e in s.children(box) if e.get("r") == "text" and "read-only" not in (e.get("st") or [])
                  and str(e.get("v") or "").strip()]
        if filled:
            own_cancel = s.find(name="Cancel", role="push button", within=box)
            if own_cancel and s.covered(own_cancel[0]) is None:
                act([click(own_cancel[0], after=0.8)], f"empty {name}")
                s = None
                continue
        try:
            s = bring_forward(name, s)
        except Fail:
            if read().frame(name) is None:
                return                                    # it went with Order Summary (closing that shuts it too)
            raise
        if s.frame(name) is None:
            return
        btn = s.find(name="Exit", role="push button", within=s.frame(name))
        if not btn:
            raise Fail(f"the {name} window has no Exit showing")
        act([click(btn[0], after=1.0)], f"Exit {name}")
        s = None
    raise Fail(f"the {name} window won't close - look at it")


def exit_split(s=None):
    exit_box(SPLIT_BOX, s)


COPY_BOX = "Copy Order"
WINDOW_TEXT = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s*-\s*(?:(\d{2}/\d{2}/\d{2})\s+)?(\d{1,2}:\d{2})\s*$")


def window_ends(text, what):
    """'DD/MM/YY HH:MM - [DD/MM/YY] HH:MM' -> ((day, time), (day, time))."""
    m = WINDOW_TEXT.match(str(text or ""))
    if not m:
        raise Fail(f"{what} should read 'DD/MM/YY HH:MM - HH:MM' (or with a second date), not {text!r}")
    d1, t1, d2, t2 = m.groups()
    return (d1, t1.zfill(5)), (d2 or d1, t2.zfill(5))


# ---------- an order line's quantity ----------
ITEM_BOX = "Create,Edit or Delete Order Item"


def clear_box(e):
    """Steps that empty a box: into it, all selected, Delete."""
    return [click(e, after=0.3), key("home", after=0.05), key("shift+end", after=0.05), key("delete", after=0.2)]


def item_box_values(s):
    box = s.frame(ITEM_BOX)
    if box is None:
        return None, {}
    return box, named_values(s, box, ("Oms Ref", "Identifier", "Product", "Ordered", "To Deliver", "Delivered",
                                      "Weight", "Description"))


def exit_item_box(s=None):
    s = s or read()
    box = s.frame(ITEM_BOX)
    if box is None:
        return
    act([click(s.one("the item box's Exit", role="push button", name="Exit", within=box), after=1.0)], "Exit item box")
    s = read()
    q = s.question()
    if q is not None:
        raise Fail(f"Exit asked: {q['words'][:150]} - left up, nothing answered")


# ---------- an order line's item: created, or put right (order-item) ----------
LIST_BOX = "Product Items"                                  # Ctrl+L's list on an item's Identifier
LIST_ROW = re.compile(r"Item_Id:(.*?)\s+Item_Description:(.*)", re.S)
ZEROS = ("0", "0.0", "0.00", "0.000", ".0")


def product_name(text):
    """A product as the item box's drop-down and the Detail tab both read, compared: PARCEL = Parcel, CABLE_DRUMS = Cable
    Drums. The drop-down shows Maintenance > Products' NAME, the Detail tab the CODE; where those differ in more than case
    and "_" (STEE_SLEEPER is STEEL SLEEPERS), --product gives the name."""
    return re.sub(r"[\s_]+", " ", str(text or "")).strip().upper()


def product_items(s):
    """Ctrl+L's Product Items list, top row first: [(item id, description)]. Its rows come as labels with no place of their
    own (23/11); the top one is the one taken (his rule 03/11)."""
    f = s.frame(LIST_BOX)
    out = []
    for e in s.children(f):
        m = LIST_ROW.fullmatch(str(e.get("nm") or "").strip()) if e.get("r") == "label" else None
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def item_plan(now, product, qty=None, weight=None, ident=False):
    """What one item box needs, from what it holds now (his rules 03/11, 09/11, 16/11) -> [(box, value)] in the order they
    go in: Product (the Detail tab's), Identifier (always from Ctrl+L's list, never typed text - when the product is new,
    the box is empty, or ident), Ordered, a Delivered 0 cleared, Weight. Fail when the item has no weight and none was
    given: an ad hoc's weight only lives in its Special Instructions."""
    todo = []
    if product_name(now.get("Product")) != product_name(product):
        todo.append(("Product", product_name(product)))
    have_id = str(now.get("Identifier") or "").strip()
    if todo or ident or not have_id or have_id.lower() == "please select":
        todo.append(("Identifier", "Ctrl+L"))
    if qty is not None and abs((_amount(now.get("Ordered")) or 0) - qty) > 0.0005:
        todo.append(("Ordered", f"{qty:g}"))
    if str(now.get("Delivered") or "").strip() in ZEROS:
        todo.append(("Delivered", ""))
    have = _amount(now.get("Weight")) or 0
    if weight is not None and abs(have - weight) > 0.005:
        todo.append(("Weight", f"{weight:g}"))
    elif weight is None and not have:
        raise Fail("the item has no weight: give --weight KG, the line's total (an ad hoc's is in its Special "
                   "Instructions, e.g. 2 x 600 kg = 1200)")
    return todo


def read_patiently(seconds=45):
    """A read once CTMS answers again: while it saves an item, its Java stops answering the Access Bridge for a few
    seconds, which the bridge words as "CTMS's Java has not picked it up" (23/11) - a wait, not a fault."""
    end = time.time() + seconds
    while True:
        try:
            return read()
        except Fail:
            if time.time() >= end:
                raise
            time.sleep(3)


# ---------- services ----------
SERVICE_HEADS = ("Service Id", "Name", "Qty", "Value", "Inherited")


def service_rows(s, t):
    """A Services tab's lines (an order's or a trip's): [{"id", "name", "qty", "cell"}] - the Service Id cell kept for
    selecting the line."""
    heads = [e for e in s.children(t) if e.get("r") == "push button" and clean(e.get("nm")) == "Service Id"]
    if not heads:
        return []
    h = heads[0]
    cells = sorted((e for e in s.children(t) if e.get("r") == "text" and on_screen(e) and e["at"][1] > h["at"][1]
                    and h["at"][0] <= e["at"][0] + e["at"][2] // 2 < h["at"][0] + h["at"][2]
                    and str(e.get("v") or "").strip()), key=lambda e: e["at"][1])
    grid = header_grid(s, t, SERVICE_HEADS)
    out = []
    for c in cells:
        line = next((g for g in grid if g.get("Service Id") == str(c.get("v")).strip()), {})
        out.append({"id": str(c.get("v")).strip(), "name": line.get("Name", ""), "qty": line.get("Qty", ""),
                    "cell": c})
    return out


def service_rails(adds, d):
    """His rules on services, before anything is typed: PTS only on rails and S&C, never on ballast; rear steer only on
    an artic, never a rigid."""
    products = " ".join(str(i.get("Product Type", "")) for i in d.get("items") or []).upper()
    veh = str(d.get("veh_type") or "").upper()
    for code in adds:
        if code == "PTS" and ("BALLAST" in products or not any(w in products for w in ("RAIL", "S&C", "SWITCH"))):
            raise Fail(f"PTS is only for rails and S&C (this line carries {products or 'nothing read'}) - his rule")
        if code == "REAR STEER" and "RIGID" in veh:
            raise Fail(f"rear steer never goes on a rigid ({d.get('veh_type')}) - his rule")


# ---------- delivery type ----------
TYPES_BOX = "Delivery Types"
DEL_TYPES = ("STANDARD", "NEXT DAY", "EMERGENCY")       # his bands: under 24 h, 24-72 h, the rest
TYPE_ROW = re.compile(r"[^:\t]+:([^\t]*)")              # a list row as the Access Bridge names it: "Column:value"


def type_rows(s):
    """The Delivery Types list's rows, top first, as their first column reads (Book's way, live 03/11)."""
    win = s.frame(TYPES_BOX)
    if win is None:
        return None
    rows = (TYPE_ROW.match(str(e.get("nm") or "")) for e in s.children(win) if e.get("r") == "label")
    return [m.group(1).strip() for m in rows if m]


def pick_type(code, commit):
    """With the Delivery Types list up: Find CODE%, and the top row must read CODE exactly ("EMERGENCY", never the
    "Emergency" beside it). commit: its OK; else its Cancel - nothing picked."""
    s = read()
    win = s.frame(TYPES_BOX)
    box = next((e for e in s.children(win) if e.get("r") == "text" and clean(e.get("nm")) == "Find"
                and "read-only" not in (e.get("st") or [])), None)
    find = next((e for e in s.children(win) if e.get("r") == "push button" and clean(e.get("nm")) == "Find"), None)
    if box is None or find is None:
        raise Fail("the Delivery Types list's Find isn't there by name - left up for a look")
    act(fill(box, code + "%") + [click(find, after=0.6), {"action": "settle", "quiet": 0.3, "timeout": 8}],
        f"Find {code}%")
    s = read()
    rows = type_rows(s) or []
    win = s.frame(TYPES_BOX)
    btn = {clean(e.get("nm")).lower(): e for e in s.children(win) if e.get("r") == "push button"}
    if not rows or rows[0] != code or "ok" not in btn:
        if "cancel" in btn:
            act([click(btn["cancel"], after=0.6)], "Cancel the list")
        raise Fail(f"the Delivery Types list gave {rows[0] if rows else 'no row'} for {code} - nothing picked")
    act([click(btn["ok" if commit else "cancel"], after=0.8)], "OK" if commit else "Cancel (no --commit)")
    return rows


# ---------- non-conformance ----------
NC_BOX = "Non conformance"


def list_selected(s):
    """The line an open drop-down list has selected, by its name, or None."""
    for lst in s.find(role="list"):
        for e in s.children(lst):
            if e.get("r") == "label" and "selected" in (e.get("st") or []) and clean(e.get("nm")):
                return clean(e.get("nm"))
    return None


def pick_from_list(combo, want, what):
    """A Forms drop-down set to want: opened by its arrow, the first letter typed, then Down until the selected line
    reads want (a long list opens on its last line; the first-letter jump beats two minutes of arrow presses, 16/11),
    Enter. Fails, list closed, if it never reads want."""
    x, y, w, h = combo["at"]
    act([{"action": "click", "screen": [x + w - 8, y + h // 2], "after": 0.9}], f"open {what}")
    s = read()
    opts = [e for lst in s.find(role="list") for e in s.children(lst) if e.get("r") == "label" and on_screen(e)
            and clean(e.get("nm")) == want]
    if len(opts) == 1:
        act([click(opts[0], after=0.7)], f"{what}: {want}")
        return
    act([typed(want[0], after=0.6)], f"{what}: '{want[0]}'")
    for _ in range(40):
        s = read()
        sel = list_selected(s)
        if sel == want:
            act([key("enter", after=0.6)], f"{what}: {want}")
            return
        act([key("down", after=0.3)], f"{what}: down")
    act([key("escape", after=0.4)], f"{what}: give up")
    raise Fail(f"{what} never came to {want!r} (CTMS spells codes exactly - check the code's spelling)")


def nc_rows(s):
    """The Non conformance box's rows: [{reason, activity, comment, combos}] top to bottom."""
    box = s.frame(NC_BOX)
    if box is None:
        return []
    kids = [e for e in s.children(box) if on_screen(e)]
    combos = sorted((e for e in kids if e.get("r") == "combo box"), key=lambda e: (e["at"][1], e["at"][0]))
    out = []
    for line in _rows_by_y(combos, gap=3):
        line.sort(key=lambda e: e["at"][0])
        y = line[0]["at"][1]
        texts = sorted((e for e in kids if e.get("r") == "text" and abs(e["at"][1] - y) <= 4),
                       key=lambda e: -e["at"][2])
        out.append({"reason": str(line[0].get("v") or "").strip(),
                    "activity": str(line[1].get("v") or "").strip() if len(line) > 1 else "",
                    "comment": str(texts[0].get("v") or "").strip() if texts else "",
                    "enabled": "disabled" not in (line[0].get("st") or []), "combos": line,
                    "comment_box": texts[0] if texts else None, "y": y})
    return out


def ok_known_questions(tries=4):
    """After a non-conformance's OK: CTMS's own notices answered OK (the 49-hour prompt). Anything that isn't plainly
    an OK-only notice stops the route, left up."""
    for _ in range(tries):
        s = read()
        q = s.question()
        if q is None:
            return s
        if set(q["buttons"]) <= {"ok"} and "ok" in q["buttons"]:
            act([click(q["buttons"]["ok"], after=1.0)], "OK the notice")
            continue
        raise Fail(f"CTMS asks: '{q['words'][:150]}' ({', '.join(q['buttons'])}) - left up, not answered")
    return read()


# ---------- the work PC's own proven jobs, behind the same front door ----------
VEHICLES = ("rigid", "artic", "60ft", "80ft", "tipper")


def run_item(item, commit):
    """A note or an update done by the work PC itself (ctms_items: the same job the dashboard's to-do Run sends - it
    opens the line, proves its Customer Ref, types, reads back, saves and closes, and never types a vehicle over
    another). Without commit an update is a dry run on its first line: typed, read back, thrown away.
    The work PC's dry run does NOT cover a note (it saves anyway - found 23/11 when a test note was saved and had to
    be taken back) nor the delivery comment (its box saves by itself), so without commit those are not sent at all:
    the route only says what it would do."""
    s = item.get("set") or {}
    # a note's dry run is honoured by the work PC since main 88c132c (23/11); the LOC comment box still saves by itself
    if not commit and s.get("comments"):
        what = f"set the delivery comment '{s['comments']}' on {', '.join(item['lines'])}"
        print(f"NOT SENT: this would {what} and save it straight away (CTMS has no dry run for that). "
              "Run again with --commit to do it.")
        return {"done": False, "dry": True, "said": f"not sent - would {what}"}
    connect()
    wait = 120 + 90 * max(1, len(item.get("lines") or []))
    result, payload = R.ask_waiting("ctms_item", wait_total=wait, item=item, first=True, last=True, dry=not commit)
    payload = payload or {}
    R.trace(f"route-item-{item['kind']}", {"item": item, "dry": not commit}, result, payload)
    said = str(result.get("detail") or "")
    out = {"done": bool(payload.get("done")), "held": bool(payload.get("held")), "clean": bool(payload.get("clean")),
           "dry": not commit, "work_pc_seconds": payload.get("seconds"), "said": said}
    print(("DRY RUN (nothing saved): " if not commit else "") + said)
    if payload.get("held"):
        print("HELD: CTMS already had something different - it's for you to decide, nothing was changed.")
    if not payload.get("done") and not payload.get("held"):
        raise Fail(said or "the work PC didn't finish it")
    return out


# ---------- the routes ----------
@route("order-note", "add a note to the end of a line's Special Instructions, e.g. \" - Emailed DO 24/11\" "
                     "(dry run unless --commit)")
def r_order_note(a):
    no_price(a.note, "Special Instructions")
    note = a.note if a.note.startswith((" - ", "- ")) else " - " + a.note.strip()
    if note.startswith("- "):
        note = " " + note
    if not a.modify:
        return run_item({"kind": "note", "lines": [a.ref], "set": {"note": note}}, a.commit)
    # a booked line: the work PC's note job won't open it, so it's done here - the 23/11 way (si_add.py)
    close_orders()
    f, s, row = open_order(a.ref, modify_scheduled=True)
    name = clean(f.get("nm"))
    si = next((e for e in s.children(f) if clean(e.get("nm")) == "Special Instructions" and on_screen(e)), None)
    if si is None:
        close_window(name, s)
        raise Fail("no Special Instructions box on the order's Detail tab")
    before = str(si.get("v") or "").rstrip()
    if before.endswith(note.strip()):
        close_window(name, s)
        return {"ref": a.ref, "changed": False, "said": f"'{note.strip()}' is there already"}
    if not a.commit:
        close_window(name, s)
        print(f"WOULD ADD '{note}' to the end of {a.ref}'s Special Instructions (now ending ...{before[-50:]!r}), "
              "then Save - nothing typed (no --commit)")
        return {"ref": a.ref, "changed": False}
    x, y, w, h = si["at"]
    act([{"action": "click", "screen": [x + w - 40, y + h - 8], "after": 0.4}], "into Special Instructions")
    s = read()
    f = s.frame(name)
    si = next(e for e in s.children(f) if clean(e.get("nm")) == "Special Instructions" and on_screen(e))
    if s.focus is None or s.focus.get("n") != si.get("n"):
        raise Fail(f"the cursor isn't in Special Instructions ({describe(s.focus)}) - nothing typed, left open")
    act([key("ctrl+end", after=0.1), typed(note, after=0.3)], "the note")
    s = read()
    f = s.frame(name)
    after = str(next(e for e in s.children(f) if clean(e.get("nm")) == "Special Instructions").get("v") or "")
    if not after.rstrip().endswith(note.strip()) or not after.startswith(before[:40]):
        raise Fail(f"Special Instructions read ...{after[-60:]!r} - not saved, left open for a look")
    act([click(s.one("the order's Save", role="push button", name="Save", within=f), after=2.0)], "order Save")
    s = ok_known_questions()
    close_window(name, s)
    print(f"ADDED to {a.ref}: '{note}'")
    return {"ref": a.ref, "changed": True}


@route("order-update", "set times, LOC comment, vehicle and services on one or more lines in one go "
                       "(dry run unless --commit)")
def r_order_update(a):
    s = {}
    if a.collect:
        s["collect"] = a.collect
    if a.deliver:
        s["deliver"] = a.deliver
    if a.comments:
        no_price(a.comments, "a CTMS comment")
        s["comments"] = a.comments.replace(",", "")          # CTMS's own rule on these: no commas
    if a.veh:
        s["veh"] = a.veh
    services = {x.upper(): True for x in a.service or []}
    services.update({x.upper(): False for x in a.no_service or []})
    if services:
        s["services"] = services
    if a.storage:
        s["storage"] = a.storage
    if a.anyway:
        s["anyway"] = True
    if a.same_day:
        s["collect_same_day"] = True
    if not s:
        raise Fail("nothing to set - give --collect, --deliver, --comments, --veh, --service or --no-service")
    return run_item({"kind": "update", "lines": a.refs, "set": s}, a.commit)


@route("trip-find", "select a manifest in Planning's tree from anywhere: Find by EFX Ref (Trip) = OM-MAN-n "
                    "(the 6-second way; --order REF finds it by Customer Ref instead) - reads only")
def r_trip_find(a):
    if a.order:
        how, got, s = find_trip("Customer Ref", a.order)
    else:
        how, got, s = find_trip("EFX Ref (Trip)", "OM-MAN-" + man_number(a.man))
    if how == "list":
        print("Several trips match - CTMS's Find Trip list is up:")
        for w in got[:30]:
            print("  " + w)
        return {"found": "list", "words": got[:60]}
    if not got:
        raise Fail("Find closed but no trip is selected in the tree")
    row = got[0]
    if a.man and not a.order and man_number(row["man"]) != man_number(a.man):
        raise Fail(f"the tree selected {row['man']}, not {a.man}")
    print(f"Selected: {row['man']}  {row['day']} {row['time']}  ({row['status']})")
    return {"found": "selected", "man": row["man"], "day": row["day"], "time": row["time"], "status": row["status"]}


TRIP_TABS = ("detail", "stops", "status", "finance")


@route("trip-read", "find a manifest and read it back: carrier, status, stops and times, trailer, status history, "
                    "cost and revenue (reads only)")
def r_trip_read(a):
    tabs = [t.strip() for t in str(getattr(a, "tabs", "") or ",".join(TRIP_TABS)).split(",") if t.strip()]
    if not tabs or any(t not in TRIP_TABS for t in tabs):
        raise Fail(f"--tabs takes {', '.join(TRIP_TABS)}")
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    got = trip_tabs(tabs)
    d, f = got.get("detail"), got.get("finance")
    if d is not None:
        print(f"  carrier {d.get('Carrier', '?')}  status {d.get('Status', '?')}  trip ref {d.get('Trip Ref', '')}  "
              f"delivery type {d.get('Delivery Type', '')}  cost centre {d.get('Cost Centre', '')}")
    for st in got.get("stops") or []:
        print(f"  stop {st.get('Stop', '?')} {st.get('Type', ''):3} {st.get('Date', '')} {st.get('P Arr', '')}-"
              f"{st.get('P Dep', '')}  {st.get('Location', '')}  {st.get('Trailer Type', '')}")
    if f is not None:
        print(f"  cost {f.get('Trip Cost', '?')} (+VAT {f.get('Cost VAT', '?')})  revenue {f.get('Trip Revenue', '?')}")
    hist = (got.get("status") or {}).get("history") or []
    if hist:
        last = hist[-1]
        print(f"  last status change: {last.get('Action', '')} -> {last.get('Trip Status', '')} by "
              f"{last.get('Actioned By', '')} at {last.get('Action Date', '')}; manifest sent "
              f"{got['status'].get('Manifest Sent', '?')}")
    return dict(found, **got)


@route("trip-payments", "a manifest's carrier payments: every line (Trip Haulage, escort, night...) and the total "
                        "(reads only; the window is closed again)")
def r_trip_payments(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    rows, total, s = open_payments()
    for r in rows:
        print("  " + " | ".join(c for c in r["cells"] if c))
    print(f"  total {total}")
    close_payments()
    tab("Trip Detail", "Planning")
    return dict(found, lines=[r["cells"] for r in rows], total=total)


@route("trip-price", "set a manifest's carrier total: works out the haulage line (Trip Haulage, or Trip Haul Ma on a "
                     "trip Book made) so all its lines add up to "
                     "TOTAL (escort, night, HIAB lines stay). Shows the sum unless --commit; resend it after")
def r_trip_price(a):
    want = _amount(a.total)
    if want is None or want <= 0:
        raise Fail(f"'{a.total}' isn't a total")
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    rows, total, s = open_payments()
    try:
        line, others, new = price_plan(rows, want)
    except Fail:
        close_payments(s)
        raise
    kind = next(c for c in line["cells"] if HAULAGE.match(str(c or "")))
    plan = (f"{kind} {line['amount']:.2f} -> {new:.2f}: with the other lines ({others:.2f}) the total is {want:.2f} "
            f"(now {total})")
    print(plan)
    if abs(new - (line["amount"] or 0)) < 0.005:
        close_payments(s)
        return dict(found, said="already that total", plan=plan)
    if not a.commit:
        close_payments(s)
        print("NOT CHANGED (no --commit). Run again with --commit to set it, then trip-resend to send the manifest.")
        return dict(found, plan=plan, changed=False)
    f = s.frame(PAYMENTS)
    act([click(line["el"], after=0.6), click(s.one("Payments' Edit", role="push button", name="Edit", within=f),
                                              after=1.5)], "edit the haulage line")
    _, s = until(lambda sc: next((x for x in sc.frames() if clean(x.get("nm")).startswith("Payment ")
                                  and not clean(x.get("nm")).startswith(PAYMENTS)), None), "the payment's box", tries=5)
    box_win = next(x for x in s.frames() if clean(x.get("nm")).startswith("Payment ") and not
                   clean(x.get("nm")).startswith(PAYMENTS))
    typ = next((e for e in s.children(box_win) if e.get("r") == "combo box" and clean(e.get("nm")) == "Type"), None)
    if typ is None or not HAULAGE.match(str(typ.get("v") or "")):
        raise Fail(f"the box that opened isn't the haulage payment ({describe(typ)}) - left up for a look")
    amt = [e for e in s.children(box_win) if e.get("r") == "text" and on_screen(e)
           and "read-only" not in (e.get("st") or []) and _amount(e.get("v")) is not None
           and abs((_amount(e.get("v")) or 0) - (line["amount"] or 0)) < 0.005]
    if len(amt) != 1:
        raise Fail(f"couldn't tell the amount box ({len(amt)} hold {line['amount']}) - left up for a look")
    act(fill(amt[0], f"{new:.2f}") + [key("tab", after=0.5)], "the new amount")
    s = read()
    box_win = s.frame(clean(box_win.get("nm")))
    now = [e for e in s.children(box_win) if e.get("r") == "text" and on_screen(e)
           and abs((_amount(e.get("v")) or -1) - new) < 0.005 and "read-only" not in (e.get("st") or [])]
    if not now:
        raise Fail(f"the amount didn't read back as {new:.2f} - not OK'd, left up for a look")
    act([click(s.one("the payment's OK", role="push button", name="OK", within=box_win), after=2.0)], "OK")
    s, q = settle(read())
    if q is not None:
        raise Fail(f"CTMS asks after OK: {q['words'][:160]} - left up for a look")
    rows, total = payment_lines(s)
    got = round(sum(r["amount"] or 0 for r in rows or []), 2)
    close_payments(s)
    if abs(got - want) > 0.005:
        raise Fail(f"the lines now add up to {got:.2f}, not {want:.2f} - look at it")
    print(f"Set: total {total}. Now resend it: trip-resend {found.get('man')}")
    return dict(found, plan=plan, changed=True, total=total)


@route("trip-status", "set a manifest's status (planned / accepted / abandoned): one OK, Save, read back, never "
                      "retried; checks the menu only unless --commit")
def r_trip_status(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    got = set_status(found["man"], a.status, a.commit, a.near_start)
    print(got["said"])
    return dict(found, **got)


@route("trip-resend", "resend a manifest to its haulier: Planned, Save, then Accepted, Save (his 30/10 way), read "
                      "back; checks the menu only unless --commit")
def r_trip_resend(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    if found["status"].upper() not in ("ACCEPTED", "PLANNED"):
        raise Fail(f"{found['man']} is {found['status']} - resend is for an accepted or planned trip")
    if not a.commit:
        first = set_status(found["man"], "planned", False, a.near_start) if found["status"].upper() == "ACCEPTED" \
            else {"said": "already PLANNED"}
        print(f"Would set PLANNED then ACCEPTED: {first['said']}")
        return dict(found, changed=False)
    steps = []
    if found["status"].upper() == "ACCEPTED":
        steps.append(set_status(found["man"], "planned", True, a.near_start))
    steps.append(set_status(found["man"], "accepted", True, a.near_start))
    t, s = tab("Status", "Planning")
    st = read_trip_status(s, t)
    print(f"{found['man']}: " + "; ".join(x["said"] for x in steps) + f"; manifest sent {st.get('Manifest Sent', '?')}")
    tab("Trip Detail", "Planning")
    return dict(found, changed=True, manifest_sent=st.get("Manifest Sent"))


@route("order-nc", "add a non-conformance to a line: reason code, activity, comment (no commas, under 250 "
                   "characters); fills it and reads it back, then cancels unless --commit. Never presses Re-book")
def r_order_nc(a):
    if "," in a.comment:
        raise Fail("no commas in a CTMS comment (his rule) - say it without them")
    no_price(a.comment, "a non-conformance comment")
    if len(a.comment) > 250:
        raise Fail(f"the comment is {len(a.comment)} characters - CTMS cuts it silently at about 255")
    close_orders()
    f, s, row = open_order(a.ref, modify_scheduled=a.modify)
    d = read_detail(s, f)
    if d["ref"].upper() != a.ref.upper():
        raise Fail(f"opened {d['ref']}, not {a.ref}")
    btn = s.one("the order's Non Conformance button", role="push button", name="Non Conformance", within=f)
    clear_to(btn, s, "Non Conformance")
    act([click(btn, after=1.5)], "Non Conformance")
    _, s = until(lambda sc: sc.frame(NC_BOX), "the Non conformance box", tries=5)
    rows = nc_rows(s)
    free = next((r for r in rows if r["enabled"] and not r["reason"]), None)
    if free is None:
        raise Fail("no empty row in the Non conformance box - left up for a look")
    pick_from_list(free["combos"][0], a.reason, "Reason Code")
    s = read()
    free = next(r for r in nc_rows(s) if abs(r["y"] - free["y"]) <= 3)
    if len(free["combos"]) < 2:
        raise Fail("the row has no Activity box")
    pick_from_list(free["combos"][1], a.activity, "Activity")
    s = read()
    free = next(r for r in nc_rows(s) if abs(r["y"] - free["y"]) <= 3)
    if free["comment_box"] is None:
        raise Fail("the row has no comment box")
    act(fill(free["comment_box"], a.comment) + [key("tab", after=0.5)], "the comment")
    s = read()
    got = next(r for r in nc_rows(s) if abs(r["y"] - free["y"]) <= 3)
    said = f"{a.ref}: {got['reason']} / {got['activity']} / '{got['comment']}'"
    if got["reason"] != a.reason or got["activity"] != a.activity or got["comment"] != a.comment:
        raise Fail(f"the row reads {said} - not what was asked; left up, OK not pressed")
    box = s.frame(NC_BOX)
    if not a.commit:
        act([click(s.one("the box's Cancel", role="push button", name="Cancel", within=box), after=1.0)], "Cancel")
        close_orders()
        print(f"FILLED AND CANCELLED (no --commit): {said}")
        return {"ref": a.ref, "row": said, "changed": False}
    act([click(s.one("the box's OK", role="push button", name="OK", within=box), after=1.5)], "OK")
    s = ok_known_questions()
    f = details_frame(s)
    save = s.find(name="Save", role="push button", within=f, enabled=True)
    if save:
        act([click(save[0], after=1.5)], "order Save")
        s = ok_known_questions()
    close_window(clean(details_frame(s).get("nm")), s)
    print(f"ADDED: {said}")
    return {"ref": a.ref, "row": said, "changed": True}


@route("order-split", "split an unscheduled line into N equal parts (Order Summary > Split Orders); shows the box "
                      "and exits unless --commit, then lists the new parts (they number onward: S1 split makes S4, S5)")
def r_order_split(a):
    if a.parts < 2:
        raise Fail("a split is into 2 or more parts")
    exit_split()                                          # one left from before
    rows, s = order_search(a.ref)
    row = pick_line(rows, a.ref)                          # a ref on two lines: the live one (26/11)
    if row is None:
        raise Fail(f"no line {a.ref} in Order Summary (lines: {', '.join(r['ref'] for r in rows) or 'none'})")
    if row["status"] != "UNSCHEDULED":
        raise Fail(f"{a.ref} is {row['status']} - unschedule it first (and Save Planning), then split")
    before = {r["ref"] for r in rows}
    summary_menu(row, "os-split-orders", s)
    _, s = until(lambda sc: sc.frame(SPLIT_BOX), "the Split Order window", tries=5)
    box = s.frame(SPLIT_BOX)
    n = s.one("No of Orders", role="text", name="No of Orders", within=box)
    act(fill(n, str(a.parts)) + [key("tab", after=0.4)], "No of Orders")
    s = read()
    box = s.frame(SPLIT_BOX)
    got = str(s.one("No of Orders", role="text", name="No of Orders", within=box).get("v") or "").strip()
    oms = str((s.first(name="OMS Ref", role="text", within=box) or {}).get("v") or "")
    if got != str(a.parts):
        exit_split(s)
        raise Fail(f"No of Orders reads {got!r}, not {a.parts} - nothing split")
    if not a.commit:
        exit_split(s)
        print(f"WOULD SPLIT {a.ref} (OMS {oms}) into {a.parts} equal parts - exited, nothing split (no --commit)")
        return {"ref": a.ref, "parts": a.parts, "changed": False}
    act([click(s.one("Process", role="push button", name="Process", within=box), after=2.0)], "Process")
    s = ok_known_questions()
    exit_split(s)
    rows, s = order_search(a.ref)
    new = [r for r in rows if r["ref"] not in before]
    print(f"SPLIT {a.ref} into {a.parts}: new lines " + ", ".join(f"{r['ref']} ({r['status']})" for r in new))
    return {"ref": a.ref, "parts": a.parts, "changed": True, "new": [r["ref"] for r in new]}


@route("trip-unschedule", "take an order (--line REF, or every one) off a manifest: Planned Orders > Unschedule "
                          "Order, OK, Planning Save at once (his rule); checks the menu only unless --commit")
def r_trip_unschedule(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    rows, s = planned_orders()
    want = [r for r in rows if not a.line or r["ref"].upper() == a.line.upper()]
    if not want:
        close_x(PLANNED, s)
        raise Fail(f"{a.line} isn't on {found['man']} (it has: {', '.join(r['ref'] for r in rows) or 'nothing'})")
    print(f"{found['man']} has: " + ", ".join(f"{r['ref']} ({r['activity']})" for r in rows))
    if not a.commit:
        r = want[0]
        act([click(r["el"], after=0.5), click(r["el"], right=True, after=0.7),
             tpl_find("po-unschedule", _menu_box(r["el"])), key("escape", after=0.4)], "check Unschedule Order")
        close_x(PLANNED)
        tab("Trip Detail", "Planning")
        print(f"WOULD UNSCHEDULE {', '.join(r['ref'] for r in want)} from {found['man']}, Saving Planning after "
              "each - nothing changed (no --commit)")
        return dict(found, lines=[r["ref"] for r in want], changed=False)
    done = []
    for r in want:
        rows, s = planned_orders()
        row = next((x for x in rows if x["ref"] == r["ref"]), None)
        if row is None:
            continue
        act([click(row["el"], after=0.5), click(row["el"], right=True, after=0.7),
             tpl_find("po-unschedule", _menu_box(row["el"]), click=True, after=1.2)], f"unschedule {row['ref']}")
        s = read()
        q = s.question()
        if q is None or "unschedul" not in q["words"].lower() or set(q["buttons"]) != {"ok"}:
            raise Fail(f"after Unschedule Order CTMS shows: {q and q['words'][:150]} - left up for a look")
        act([click(q["buttons"]["ok"], after=0.8)], "OK")
        s = read()
        save = s.find(name="Save", role="push button", within=s.frame("Planning"), enabled=True)
        if not save:
            raise Fail(f"{row['ref']} unscheduled but Planning's Save isn't there to press - SAVE PLANNING BY HAND NOW")
        act([click(save[0], after=1.2)], "Planning Save (at once)")
        settle(read(), "Planning")
        done.append(row["ref"])
    rows, s = planned_orders()
    left = [r["ref"] for r in rows]
    close_x(PLANNED, s)
    print(f"UNSCHEDULED {', '.join(done)} from {found['man']}; still on it: {', '.join(left) or 'nothing'}"
          + (" - an empty trip can be closed by CTMS: abandon it next (trip-status ... abandoned)" if not left else ""))
    return dict(found, unscheduled=done, left=left, changed=bool(done))


@route("trip-payments-clear", "delete every carrier payment line on a manifest (his haulier-swap step, after "
                              "unschedule and abandon); lists them only unless --commit")
def r_trip_payments_clear(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    rows, total, s = open_payments()
    print(f"{found['man']} payments: " + "; ".join(f"{r['cells'][2] if len(r['cells']) > 2 else '?'} {r['amount']}"
                                                 for r in rows) + f" (total {total})")
    if not a.commit:
        close_payments(s)
        tab("Trip Detail", "Planning")
        print(f"WOULD DELETE all {len(rows)} line(s) - nothing changed (no --commit)")
        return dict(found, lines=len(rows), changed=False)
    for _ in range(len(rows) + 2):
        s = read()
        rows, total = payment_lines(s)
        if not rows:
            break
        f = s.frame(PAYMENTS)
        act([click(rows[0]["el"], after=0.6),
             click(s.one("Payments' Delete", role="push button", name="Delete", within=f), after=1.2)], "Delete")
        s = read()
        q = s.question()
        if q is None or "delete" not in q["words"].lower() or "yes" not in q["buttons"]:
            raise Fail(f"Delete asked something else: {q and q['words'][:150]} - left up for a look")
        act([click(q["buttons"]["yes"], after=1.5)], "Yes")
        s = read()
        if s.question() is not None:
            raise Fail(f"CTMS asked after Yes: {s.question()['words'][:150]} - left up for a look")
    rows, total = payment_lines(read())
    close_payments()
    tab("Trip Detail", "Planning")
    if rows:
        raise Fail(f"{len(rows)} payment line(s) still there - look at it")
    print(f"CLEARED: {found['man']} has no carrier payments now (total {total or '0.00'})")
    return dict(found, changed=True)


@route("order-qty", "set a line's quantity the way CTMS takes it (Order Items: Ordered, Tab, Delivered 0 cleared, "
                    "Tab, Weight cleared so CTMS refills it, item Save; then Detail Qty, order Save); shows unless --commit")
def r_order_qty(a):
    close_orders()
    f, s, row = open_order(a.ref, modify_scheduled=a.modify)
    name = clean(f.get("nm"))
    t, s = tab("Order Items", name, s)
    items = [e for e in s.children(t) if on_screen(e) and clean(e.get("nm")) == "Identifier"
             and str(e.get("v") or "").strip()]
    if a.item:
        items = [e for e in items if str(e.get("v")).strip() == a.item]
    if len(items) != 1:
        close_window(name)
        raise Fail(f"{len(items)} item(s) to set - give --item IDENTIFIER (items: "
                   + ", ".join(str(e.get('v')).strip() for e in items) + ")")
    eds = sorted(s.find(name="Edit/Delete", role="push button", within=t, enabled=True), key=lambda e: e["at"][1])
    act([click(items[0], after=0.5), click(eds[0], after=1.5)], "item Edit/Delete")
    _, s = until(lambda sc: sc.frame(ITEM_BOX), "the item box", tries=5)
    box, now = item_box_values(s)
    print(f"{a.ref} item {now.get('Identifier', '?')}: ordered {now.get('Ordered', '?').strip()}, delivered "
          f"{now.get('Delivered', '').strip() or '(blank)'}, weight {now.get('Weight', '?').strip()}")
    if not a.commit:
        exit_item_box(s)
        close_window(name)
        print(f"WOULD SET ordered {a.qty}, clear delivered and weight, save, then Detail Qty {a.qty} and save - "
              "nothing changed (no --commit)")
        return {"ref": a.ref, "before": now, "changed": False}
    kids = {clean(e.get("nm")): e for e in s.children(box) if on_screen(e) and e.get("r") == "text"}
    steps = fill(kids["Ordered"], str(a.qty)) + [key("tab", after=0.4)]
    if str(now.get("Delivered", "")).strip() in ("0", "0.00", "0.000"):
        steps += clear_box(kids["Delivered"]) + [key("tab", after=0.4)]
    steps += clear_box(kids["Weight"]) + [key("tab", after=0.5)]
    act(steps, "ordered / delivered / weight")
    s = read()
    box, got = item_box_values(s)
    if str(got.get("Ordered", "")).strip() != str(a.qty):
        raise Fail(f"Ordered reads {got.get('Ordered')!r}, not {a.qty} - item not saved, box left up")
    act([click(s.one("the item box's Save", role="push button", name="Save", within=box), after=1.5)], "item Save")
    s = read()
    q = s.question()
    if q is not None:
        raise Fail(f"item Save asked: {q['words'][:150]} - left up, nothing answered")
    exit_item_box(s)
    t, s = tab("Detail", name)
    f = s.frame(name)
    qty = sorted((e for e in s.children(f) if on_screen(e) and clean(e.get("nm")) == "Qty" and e.get("r") == "text"
                  and "read-only" not in (e.get("st") or [])), key=lambda e: e["at"][1])
    if not qty:
        raise Fail("the Detail tab's Qty box isn't there - the item is saved, the order isn't: look at it")
    act(fill(qty[0], str(a.qty)) + [key("tab", after=0.5)], "Detail Qty")
    s = read()
    save = s.one("the order's Save", role="push button", name="Save", within=s.frame(name))
    act([click(save, after=2.0)], "order Save")
    for _ in range(4):
        s = read()
        q = s.question()
        if q is None:
            break
        if "schedule" in q["words"].lower() and "ok" in q["buttons"]:
            act([click(q["buttons"]["ok"], after=1.2)], "schedule OK")
            continue
        if harmless(q):                                   # OK'd, the order saved again once (settle)
            settle(s, name)
            continue
        raise Fail(f"order Save asked: {q['words'][:150]} - left up, nothing answered")
    d = read_detail(s, s.frame(name))
    close_window(name)
    line = (d["items"] or [{}])[0]
    print(f"SET {a.ref}: qty {line.get('Qty', '?').strip()}, weight {line.get('Weight', '?').strip()} (CTMS's)")
    return {"ref": a.ref, "changed": True, "after": line}


@route("order-item", "put a line's Order Items right, or create its item when it has none (an ad hoc upload can come "
                     "with none, and Book stops on it): Product = the Detail tab's, Identifier from Ctrl+L's list, "
                     "Ordered, Weight, item Save, order Save. Shows the plan unless --commit")
def r_order_item(a):
    close_orders()
    f, s, row = open_order(a.ref, modify_scheduled=a.modify)
    name = clean(f.get("nm"))
    d = read_detail(s, f)
    if len(d["items"]) != 1:
        close_window(name)
        raise Fail(f"{a.ref} has {len(d['items'])} product rows on its Detail tab - this route does a line with one")
    line = d["items"][0]
    product = (a.product or line.get("Product Type") or "").strip()
    print(f"{a.ref}: Detail {line.get('Product Type') or '?'} / {line.get('DU Type') or '?'}, qty {line.get('Qty') or '?'}, "
          f"weight {line.get('Weight') or '(blank)'}. Special Instructions: {_short(d['special_instructions'], 220)}")
    t, s = tab("Order Items", name, s)
    items = [e for e in s.children(t) if on_screen(e) and clean(e.get("nm")) == "Identifier"
             and str(e.get("v") or "").strip()]
    if len(items) > 1:
        close_window(name)
        raise Fail(f"{len(items)} items on {a.ref} - this route does a line with one item, or none")
    how = "Edit/Delete" if items else "Create"
    # creating, Ordered is the Detail tab's quantity; an item there already keeps its own (order-qty changes that)
    qty = (a.qty if a.qty is not None else _amount(line.get("Qty"))) if not items else None
    if not product or (not items and not qty):
        close_window(name)
        raise Fail(f"{a.ref}'s Detail tab gives no product or quantity - give --product / --qty")
    btn = sorted(s.find(name=how, role="push button", within=t, enabled=True), key=lambda e: e["at"][1])
    if not btn:
        close_window(name)
        raise Fail(f"Order Items has no {how} to press ({s.summary()})")
    clear_to(btn[0], s, f"Order Items' {how}")
    act(([click(items[0], after=0.5)] if items else []) + [click(btn[0], after=1.5)], f"item {how}")
    _, s = until(lambda sc: sc.frame(ITEM_BOX), "the item box", tries=5)
    box, now = item_box_values(s)
    print(f"item box ({how}): product {now.get('Product') or '(none)'}, identifier {now.get('Identifier') or '(none)'}, "
          f"ordered {now.get('Ordered') or '(blank)'}, delivered {now.get('Delivered') or '(blank)'}, weight "
          f"{now.get('Weight') or '(blank)'}")
    try:
        todo = item_plan(now, product, qty, a.weight, a.ident)
    except Fail:
        exit_item_box(s)
        close_window(name)
        raise
    print("TO DO: " + ("; ".join(f"{k} {v}".strip() for k, v in todo) or "nothing - it is right"))
    if not todo or not a.commit:
        exit_item_box(s)
        close_window(name)
        if todo:
            print("NOT CHANGED (no --commit): run again with --commit to type it in and save it")
        return {"ref": a.ref, "how": how, "before": now, "todo": todo, "changed": False}

    def boxes(sc):
        return {clean(e.get("nm")): e for e in sc.children(sc.frame(ITEM_BOX)) if on_screen(e)
                and e.get("r") in ("text", "combo box") and clean(e.get("nm"))}

    for what, value in todo:                              # anything unexpected: the box is left up, nothing saved
        k = boxes(s)
        if what == "Product":                             # its list jumps to what is typed fast (his 09/11)
            act([click(k["Product"], after=0.8), typed(value, after=0.6), key("enter", after=0.8)], "Product")
            s = read()
            _, now = item_box_values(s)
            if product_name(now.get("Product")) != value:
                raise Fail(f"the Product list gave {now.get('Product')!r} for {value} - give --product with the list's own "
                           "name; the item box is left up, nothing saved")
        elif what == "Identifier":
            act([click(k["Identifier"], after=0.4), key("ctrl+l", after=1.5)], "Identifier Ctrl+L")
            lst, s = until(lambda sc: sc.frame(LIST_BOX), "Ctrl+L's Product Items list", tries=5)
            rows = product_items(s)
            if not rows:
                cancel_box(LIST_BOX, s)
                raise Fail(f"Ctrl+L lists no item for {product} - the item box is left up, nothing saved")
            act([click(s.one("the list's OK", role="push button", name="OK", within=lst), after=1.2)], "list OK")
            s = read()
            _, now = item_box_values(s)
            if s.frame(LIST_BOX) is not None or str(now.get("Identifier") or "").upper() != rows[0][0].upper():
                raise Fail(f"the Identifier reads {now.get('Identifier')!r}, not {rows[0][0]} - the item box is left up, "
                           "nothing saved")
            print(f"Identifier {rows[0][0]} ({rows[0][1]}): the list's top row of {len(rows)}")
        elif what == "Delivered":
            act(clear_box(k["Delivered"]) + [key("tab", after=0.4)], "Delivered 0 cleared")
            s = read()
        else:                                             # Ordered, then Weight - each left by Tab (09/11)
            act(fill(k[what], value) + [key("tab", after=0.5)], what)
            s = read()
    box, now = item_box_values(s)
    off = [w for w, v in todo if w in ("Ordered", "Weight") and abs((_amount(now.get(w)) or 0) - float(v)) > 0.005]
    if off:
        raise Fail(f"{' and '.join(off)} didn't read back as typed ({now}) - the item box is left up, nothing saved")
    act([click(s.one("the item box's Save", role="push button", name="Save", within=box), after=2.0)], "item Save")
    s = read_patiently()
    q = s.question()
    if q is not None:
        raise Fail(f"item Save asked: {q['words'][:150]} - left up, nothing answered")
    exit_item_box(s)
    t, s = tab("Order Items", name)
    got = named_grid(s, t, ("Identifier", "Product", "Ordered", "Weight"))
    if not got:
        raise Fail(f"the item box closed, but Order Items shows no item - look at {a.ref} (left open)")
    print("Order Items now: " + "; ".join(", ".join(f"{k} {v}" for k, v in r.items()) for r in got))
    t, s = tab("Detail", name)
    act([click(s.one("the order's Save", role="push button", name="Save", within=s.frame(name)), after=2.0)],
        "order Save")
    for _ in range(4):
        s = read_patiently()
        q = s.question()
        if q is None:
            break
        if "schedule" in q["words"].lower() and "ok" in q["buttons"]:
            act([click(q["buttons"]["ok"], after=1.2)], "schedule OK")
            continue
        if harmless(q):                                   # OK'd, the order saved again once (settle)
            settle(s, name)
            continue
        raise Fail(f"order Save asked: {q['words'][:150]} - left up, nothing answered")
    d = read_detail(s, s.frame(name))
    close_window(name)
    after = (d["items"] or [{}])[0]
    print(f"SET {a.ref}: Detail {after.get('Product Type', '?')} qty {after.get('Qty', '?')}, weight "
          f"{after.get('Weight') or '(blank)'}")
    return {"ref": a.ref, "how": how, "todo": todo, "items": got, "detail": after, "changed": True}


@route("order-cancel", "cancel an order line (or --restore one) with Order Summary's Cancel/Restore: CTMS's question "
                       "read each time (the button toggles); answered Cancel unless --commit")
def r_order_cancel(a):
    rows, s = order_search(a.ref)
    row = pick_line(rows, a.ref, gone=a.restore)          # a ref on two lines: the live one, or the cancelled one to restore
    if row is None:
        raise Fail(f"no line {a.ref} in Order Summary (lines: {', '.join(r['ref'] for r in rows) or 'none'})")
    was = row["status"]
    if a.restore and was != "CANCELLED":
        raise Fail(f"{a.ref} is {was}, not cancelled - nothing to restore")
    if not a.restore and was == "CANCELLED":
        return {"ref": a.ref, "status": was, "changed": False, "said": f"{a.ref} is already CANCELLED"}
    if not a.restore and was not in ("UNSCHEDULED", "NEW"):
        raise Fail(f"{a.ref} is {was} - take it off its trip first (trip-unschedule), then cancel it")
    card = s.frame("Order Search")
    if card is not None:
        act([click(s.one("the search card's Close", role="push button", name="Close", within=card), after=0.8)],
            "close the card")
        s = read()
        row = pick_line(summary_rows(s), a.ref, gone=a.restore)
        if row is None:
            raise Fail(f"{a.ref} wasn't in Order Summary once its search card closed - nothing pressed")
    summ = s.frame("Order Summary")
    btn = s.one("Cancel/Restore", role="push button", name="Cancel/Restore", within=summ)
    clear_to(row["cells"]["ref"], s, f"{a.ref}'s row")
    clear_to(btn, s, "Cancel/Restore")
    act([click(row["cells"]["ref"], after=0.6), click(btn, after=1.2)], "Cancel/Restore")
    q = None
    for _ in range(4):
        s = read()
        q = s.question()
        if q is not None:
            break
    if q is None:
        raise Fail("Cancel/Restore asked nothing - look at the line")
    verb = "restore" if a.restore else "cancel"
    if verb not in q["words"].lower() or set(q["buttons"]) != {"ok", "cancel"}:
        if "cancel" in q["buttons"]:
            act([click(q["buttons"]["cancel"], after=0.8)], "not that")
        raise Fail(f"CTMS asked '{q['words'][:120]}' - not the {verb} expected; answered Cancel")
    if not a.commit:
        act([click(q["buttons"]["cancel"], after=0.8)], "Cancel: changes nothing")
        print(f"CTMS asked '{q['words'][:100]}' - answered Cancel, {a.ref} still {was} (no --commit)")
        return {"ref": a.ref, "status": was, "changed": False}
    act([click(q["buttons"]["ok"], after=1.5)], f"OK: {verb}")
    rows, s = order_search(a.ref)
    now = next((r["status"] for r in rows if r["ref"].upper() == a.ref.upper()), "?")
    ok = (now == "CANCELLED") != bool(a.restore)
    print(f"{a.ref}: {was} -> {now}")
    if not ok:
        raise Fail(f"{a.ref} reads {now} after OK - look at it (not retried)")
    return {"ref": a.ref, "status": now, "changed": True}


@route("order-copy", "copy a line to new dates (Order Summary > Copy Orders): No of Orders = copies + 1, early/late "
                     "collection and delivery typed and read back; exits unless --commit, then lists the new _C line(s)")
def r_order_copy(a):
    (c1, c2) = window_ends(a.collect, "--collect")
    (d1, d2) = window_ends(a.deliver, "--deliver")
    exit_box(COPY_BOX)                                    # one left from before
    rows, s = order_search(a.ref)
    row = pick_line(rows, a.ref)                          # a ref on two lines: the live one (26/11)
    if row is None:
        raise Fail(f"no line {a.ref} in Order Summary (lines: {', '.join(r['ref'] for r in rows) or 'none'})")
    before = {r["ref"] for r in rows}
    summary_menu(row, "os-copy-orders", s)
    _, s = until(lambda sc: sc.frame(COPY_BOX), "the Copy Order window", tries=5)
    box = s.frame(COPY_BOX)
    want = {"No of Orders": str(a.copies + 1)}
    steps = []
    n = s.one("No of Orders", role="text", name="No of Orders", within=box)
    steps += fill(n, want["No of Orders"]) + [key("tab", after=0.3)]
    for label, (day, hhmm) in (("Early Collection", c1), ("Late Collection", c2), ("Early Delivery", d1),
                               ("Late Delivery", d2)):
        d_el = s.one(label, role="text", name=label, within=box)
        t_el = _after(s, d_el)
        if t_el.get("r") != "text" or clean(t_el.get("nm")):
            raise Fail(f"no time box after {label} - left up for a look")
        steps += fill(d_el, day) + [key("tab", after=0.3)] + fill(t_el, hhmm) + [key("tab", after=0.3)]
        want[label] = (day, hhmm)
    act(steps, "the copy's dates")
    s = read()
    box = s.frame(COPY_BOX)
    got = {"No of Orders": str(s.one(name="No of Orders", role="text", within=box).get("v") or "").strip()}
    for label in ("Early Collection", "Late Collection", "Early Delivery", "Late Delivery"):
        d_el = s.one(name=label, role="text", within=box)
        got[label] = (str(d_el.get("v") or "").strip(), str(_after(s, d_el).get("v") or "").strip())
    if got != want:
        exit_box(COPY_BOX, s)
        raise Fail(f"the box reads {got}, not {want} - nothing copied")
    plan = (f"{a.ref} x{a.copies}: collect {c1[0]} {c1[1]}-{c2[0]} {c2[1]}, deliver {d1[0]} {d1[1]}-{d2[0]} {d2[1]}")
    if not a.commit:
        exit_box(COPY_BOX, s)
        print(f"WOULD COPY {plan} - exited, nothing copied (no --commit)")
        return {"ref": a.ref, "plan": plan, "changed": False}
    act([click(s.one("Process", role="push button", name="Process", within=box), after=2.5)], "Process")
    s = ok_known_questions()
    exit_box(COPY_BOX, s)
    rows, s = order_search(a.ref)
    new = [r for r in rows if r["ref"] not in before]
    print(f"COPIED {plan}: new " + ", ".join(f"{r['ref']} ({r['status']}, ready {r.get('ready', '')})" for r in new)
          + " - check its Order Items (product, weight) and the delivery time (it once came across as 00:00)")
    return {"ref": a.ref, "plan": plan, "changed": True, "new": [r["ref"] for r in new]}


@route("order-deltype", "set an UNSCHEDULED line's delivery type (STANDARD / NEXT DAY / EMERGENCY) from Add Detail's "
                         "list, the capitals row only; checks the list and cancels unless --commit")
def r_order_deltype(a):
    code = a.type.upper()
    if code not in DEL_TYPES:
        raise Fail(f"delivery type is one of {', '.join(DEL_TYPES)}")
    close_orders()
    f, s, row = open_order(a.ref)
    name = clean(f.get("nm"))
    if row.get("status") != "UNSCHEDULED":
        close_window(name)
        raise Fail(f"{a.ref} is {row.get('status')}: the type is read-only on a booked line. His way: trip-unschedule "
                   f"--line {a.ref}, order-deltype, trip-apply, trip-trailer, trip-deltype, then trip-resend")
    t, s = tab("Add Detail", name, s)
    box = next((e for e in s.children(t) if clean(e.get("nm")) == "Delivery Type"), None)
    if box is None:
        raise Fail("Add Detail has no Delivery Type box")
    now = str(box.get("v") or "").strip()
    if now == code:
        tab("Detail", name)
        close_window(name)
        return {"ref": a.ref, "type": now, "changed": False, "said": f"{a.ref} is already {now}"}
    lov = _after(s, box)
    if lov.get("r") != "push button":
        raise Fail("no list button beside Delivery Type")
    act([click(lov, after=1.5)], "Delivery Types list")
    until(lambda sc: sc.frame(TYPES_BOX), "the Delivery Types list", tries=5)
    pick_type(code, a.commit)
    if not a.commit:
        tab("Detail", name)
        close_window(name)
        print(f"WOULD SET {a.ref} {now} -> {code} (the list gives {code}) - cancelled, nothing changed (no --commit)")
        return {"ref": a.ref, "type": now, "changed": False}
    s = read()
    t = next(e for e in s.children(s.frame(name)) if e.get("r") == "page tab" and clean(e.get("nm")) == "Add Detail")
    got = next((str(e.get("v") or "").strip() for e in s.children(t) if clean(e.get("nm")) == "Delivery Type"), "")
    if got != code:
        raise Fail(f"Delivery Type reads {got!r}, not {code} - not saved, left open for a look")
    save = s.one("the order's Save", role="push button", name="Save", within=s.frame(name))
    act([click(save, after=2.0)], "order Save")
    for _ in range(4):
        s = read()
        q = s.question()
        if q is None:
            break
        if "schedule" in q["words"].lower() and "ok" in q["buttons"]:
            act([click(q["buttons"]["ok"], after=1.2)], "schedule OK")
            continue
        if harmless(q):                                   # OK'd, the order saved again once (settle)
            settle(s, name)
            continue
        raise Fail(f"order Save asked: {q['words'][:150]} - left up, nothing answered")
    close_window(name)
    rows, _ = order_search(a.ref)
    after = next((r.get("type") for r in rows if r["ref"].upper() == a.ref.upper()), "?")
    print(f"{a.ref}: {now} -> {after}")
    return {"ref": a.ref, "type": after, "changed": True}


@route("trip-deltype", "set a manifest's own delivery type on Planning's Trip Detail (after its orders' types are set);"
                       " shows it unless --commit")
def r_trip_deltype(a):
    code = a.type.upper()
    if code not in DEL_TYPES:
        raise Fail(f"delivery type is one of {', '.join(DEL_TYPES)}")
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    t, s = tab("Trip Detail", "Planning")
    box = next((e for e in s.children(t) if "Delivery Type" in str(e.get("nm") or "") and e.get("r") == "text"), None)
    if box is None:
        raise Fail("Trip Detail has no Delivery Type box")
    now = str(box.get("v") or "").strip()
    if now == code:
        return dict(found, type=now, changed=False, said=f"{found['man']} is already {now}")
    if not a.commit:
        print(f"WOULD SET {found['man']}'s delivery type {now} -> {code} - nothing typed (no --commit)")
        return dict(found, type=now, changed=False)
    mins = _starts_in({"day": found["day"], "time": found["time"]})
    if mins is not None and 0 <= mins <= NEAR_START and not a.near_start:
        raise Fail(f"{found['man']} starts in {mins:.0f} min - ask him first (--near-start once he has)")
    act(fill(box, code) + [key("tab", after=1.0)], "trip delivery type")
    s = read()
    if s.frame(TYPES_BOX) is not None:                    # CTMS asks which: the capitals one
        pick_type(code, True)
        s = read()
    q = s.question()
    if q is not None and "lov" in q["words"].lower() and set(q["buttons"]) <= {"ok"}:
        act([click(q["buttons"]["ok"], after=0.8)], "OK the FRM-41091 notice (harmless, 10/11)")
        s = read()
    s, _q = settle(s)
    t, s = tab("Trip Detail", "Planning", s)
    got = next((str(e.get("v") or "").strip() for e in s.children(t) if "Delivery Type" in str(e.get("nm") or "")), "")
    if got != code:
        raise Fail(f"Trip Detail's Delivery Type reads {got!r}, not {code} - not saved, look at it")
    save = s.find(name="Save", role="push button", within=s.frame("Planning"), enabled=True)
    if save:
        act([click(save[0], after=1.2)], "Planning Save")
        s, _q = settle(read(), "Planning")
    refresh = s.find(name="Refresh Trip", role="push button", within=s.frame("Planning"), enabled=True)
    if refresh:
        act([click(refresh[0], after=2.0)], "Refresh Trip")
    print(f"{found['man']}: delivery type {now} -> {code}; resend it if it was accepted (trip-resend)")
    return dict(found, type=code, changed=True)


@route("trip-trailer", "set a manifest's trailer type (Stops: right-click stop 1, Assign Trailer Type - it sets every "
                       "stop), e.g. NR_TROM_80FT; opens the box and cancels unless --commit")
def r_trip_trailer(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    cancel_box(TRAILER_BOX)
    t, s = tab("Stops", "Planning")
    stops = sorted((e for e in s.children(t) if on_screen(e) and clean(e.get("nm")) == "Location"
                    and str(e.get("v") or "").strip()), key=lambda e: e["at"][1])
    if not stops:
        raise Fail(f"{found['man']} shows no stops")
    now = sorted((e for e in s.children(t) if on_screen(e) and clean(e.get("nm")) == "Trailer Type"
                  and e.get("r") == "text"), key=lambda e: e["at"][1])
    was = str(now[0].get("v") or "").strip() if now else ""
    if was == a.code and not a.commit:
        return dict(found, trailer=was, changed=False, said=f"{found['man']} already has {was}")
    clear_to(stops[0], s, "stop 1")
    act([click(stops[0], after=0.5), click(stops[0], right=True, after=0.7),
         tpl_find("stop-assign-trailer-type", _menu_box(stops[0]), click=True, after=1.5)], "Assign Trailer Type")
    _, s = until(lambda sc: sc.frame(TRAILER_BOX), "the Trailer Type box", tries=4)
    box = s.frame(TRAILER_BOX)
    trip = str((s.first(name="Trip", role="text", within=box) or {}).get("v") or "")
    if man_number(trip or "x00000000") != man_number(found["man"]):
        cancel_box(TRAILER_BOX, s)
        raise Fail(f"the Trailer Type box is for {trip}, not {found['man']} - cancelled")
    if not a.commit:
        cancel_box(TRAILER_BOX, s)
        tab("Trip Detail", "Planning")
        print(f"WOULD SET {found['man']}'s trailer {was or '(none)'} -> {a.code} - box opened and cancelled (no --commit)")
        return dict(found, trailer=was, changed=False)
    mins = _starts_in({"day": found["day"], "time": found["time"]})
    if mins is not None and 0 <= mins <= NEAR_START and not a.near_start:
        cancel_box(TRAILER_BOX, s)
        raise Fail(f"{found['man']} starts in {mins:.0f} min - ask him first (--near-start once he has)")
    field = s.one("the Trailer Type box", role="text", name="Trailer Type", within=box)
    act(fill(field, a.code) + [key("tab", after=0.6)], "the trailer code")
    s = read()
    box = s.frame(TRAILER_BOX)
    if box is None or str((s.first(name="Trailer Type", role="text", within=box) or {}).get("v") or "").strip() != a.code:
        raise Fail(f"the Trailer Type box doesn't read {a.code} - not OK'd, left up for a look")
    act([click(s.one("its OK", role="push button", name="OK", within=box), after=1.5)], "OK")
    s, q = settle(read())
    if q is not None:
        raise Fail(f"CTMS asks after OK: {q['words'][:150]} - left up for a look")
    save = s.find(name="Save", role="push button", within=s.frame("Planning"), enabled=True)
    if save:
        act([click(save[0], after=1.2)], "Planning Save")
        settle(read(), "Planning")
    t, s = tab("Stops", "Planning")
    got = [str(e.get("v") or "").strip() for e in sorted((e for e in s.children(t) if on_screen(e)
           and clean(e.get("nm")) == "Trailer Type" and e.get("r") == "text"), key=lambda e: e["at"][1])]
    got = [g for g in got if g]
    tab("Trip Detail", "Planning")
    print(f"{found['man']}: trailer now {', '.join(got) or '?'}; resend it if it was accepted (trip-resend)")
    if not got or any(g != a.code for g in got):
        raise Fail(f"the stops read {got}, not all {a.code} - look at it")
    return dict(found, trailer=a.code, changed=True)


@route("trip-apply", "put an unscheduled line onto an existing manifest (Planning: the trip selected, the line's well "
                     "row right-clicked, Apply to Trip, Save); checks the menu only unless --commit")
def r_trip_apply(a):
    found = r_trip_find(argparse.Namespace(man=a.man, order=None))
    if found.get("found") != "selected":
        return found
    s = read()
    cell = well_row(s, a.ref)
    if cell is None:
        raise Fail(f"{a.ref} isn't in Planning's order well - its Sched From/To or Order Filters keep it out; set them "
                   "so the line shows (it must be UNSCHEDULED), then run this again")
    clear_to(cell, s, f"{a.ref}'s well row")
    mins = _starts_in({"day": found["day"], "time": found["time"]})
    if a.commit and mins is not None and 0 <= mins <= NEAR_START and not a.near_start:
        raise Fail(f"{found['man']} starts in {mins:.0f} min - ask him first (--near-start once he has)")
    if not a.commit:
        act([click(cell, after=0.5), click(cell, right=True, after=0.7),
             tpl_find("well-apply-trip", _menu_box(cell)), key("escape", after=0.4)], "check Apply to Trip")
        print(f"WOULD APPLY {a.ref} to {found['man']} ({found['status']}), then Save - menu checked, nothing chosen "
              "(no --commit). After: trip-trailer, and trip-resend if it was accepted")
        return dict(found, ref=a.ref, changed=False)
    act([click(cell, after=0.5), click(cell, right=True, after=0.7),
         tpl_find("well-apply-trip", _menu_box(cell), click=True, after=1.5),
         {"action": "settle", "quiet": 0.5, "timeout": 15}], f"Apply {a.ref} to Trip")
    s, q = settle(read())
    if q is not None:
        raise Fail(f"CTMS asks after Apply to Trip: {q['words'][:150]} - left up for a look")
    save = s.find(name="Save", role="push button", within=s.frame("Planning"), enabled=True)
    if save:
        act([click(save[0], after=1.2)], "Planning Save")
        settle(read(), "Planning")
    rows, s = planned_orders()
    on = [r["ref"] for r in rows]
    close_x(PLANNED, s)
    tab("Trip Detail", "Planning")
    if a.ref.upper() not in (r.upper() for r in on):
        raise Fail(f"{found['man']}'s Planned Orders show {', '.join(on) or 'nothing'}, not {a.ref} - look at it")
    print(f"APPLIED {a.ref} to {found['man']}: it now carries {', '.join(on)}. Next: trip-trailer {found['man']} CODE, "
          "and trip-resend if it was accepted")
    return dict(found, ref=a.ref, on=on, changed=True)


@route("order-services", "add or take off services on a line, booked or not (Services tab: New + the code, or Delete), "
                         "his rules checked, order Save; shows the plan unless --commit (a booked line then needs a resend)")
def r_order_services(a):
    adds = [x.upper() for x in a.add or []]
    removes = [x.upper() for x in a.remove or []]
    if not adds and not removes:
        raise Fail("nothing to do - give --add CODE and/or --remove CODE")
    close_orders()
    f, s, row = open_order(a.ref, modify_scheduled=a.modify)
    name = clean(f.get("nm"))
    d = read_detail(s, f)
    try:
        service_rails(adds, d)
    except Fail:
        close_window(name, s)                             # refused before anything was typed: nothing to keep
        raise
    t, s = tab("Services", name, s)
    have = service_rows(s, t)
    ids = [x["id"] for x in have]
    todo_add = [c for c in adds if c not in ids]
    todo_rm = [c for c in removes if c in ids]
    print(f"{a.ref} ({row.get('status')}) has: {', '.join(ids) or 'no services'}")
    if not todo_add and not todo_rm:
        tab("Detail", name)
        close_window(name)
        return {"ref": a.ref, "services": ids, "changed": False, "said": "nothing to change"}
    if not a.commit:
        tab("Detail", name)
        close_window(name)
        print(f"WOULD ADD {', '.join(todo_add) or '-'}, TAKE OFF {', '.join(todo_rm) or '-'}, then Save"
              + (" and resend its trip" if row.get("status") == "SCHEDULED" else "") + " - nothing typed (no --commit)")
        return {"ref": a.ref, "services": ids, "changed": False}
    for code in todo_rm:
        line = next(x for x in service_rows(read(), t) if x["id"] == code)
        s = read()
        t = next(e for e in s.children(s.frame(name)) if e.get("r") == "page tab" and clean(e.get("nm")) == "Services")
        delete = s.one("the Services tab's Delete", role="push button", name="Delete", within=t)
        act([click(line["cell"], after=0.5), click(delete, after=1.0)], f"take {code} off")
    for code in todo_add:
        s = read()
        t = next(e for e in s.children(s.frame(name)) if e.get("r") == "page tab" and clean(e.get("nm")) == "Services")
        new = s.one("the Services tab's New", role="push button", name="New", within=t)
        act([click(new, after=1.0), typed(code, after=0.3), key("tab", after=1.0)], f"add {code}")
        s = read()
        t = next(e for e in s.children(s.frame(name)) if e.get("r") == "page tab" and clean(e.get("nm")) == "Services")
        line = next((x for x in service_rows(s, t) if x["id"] == code), None)
        if line is None:
            raise Fail(f"{code} didn't take in the Services list - not saved, the order left open for a look")
        grid_qty = [e for e in s.children(t) if e.get("r") == "text" and on_screen(e)
                    and abs(e["at"][1] - line["cell"]["at"][1]) <= 3 and str(e.get("v") or "").strip() in ("", "0")
                    and "read-only" not in (e.get("st") or [])]
        if grid_qty:
            act(fill(grid_qty[0], "1") + [key("tab", after=0.5)], f"{code} qty 1")
    s = read()
    t = next(e for e in s.children(s.frame(name)) if e.get("r") == "page tab" and clean(e.get("nm")) == "Services")
    now = [x["id"] for x in service_rows(s, t)]
    want = [c for c in ids if c not in todo_rm] + todo_add
    if sorted(now) != sorted(want):
        raise Fail(f"the Services list reads {now}, not {want} - not saved, the order left open for a look")
    act([click(s.one("the order's Save", role="push button", name="Save", within=s.frame(name)), after=2.0)],
        "order Save")
    s = ok_known_questions()
    close_window(name)
    print(f"{a.ref}: services now {', '.join(now) or 'none'}"
          + (" - its trip needs a resend (trip-resend)" if row.get("status") == "SCHEDULED" else ""))
    return {"ref": a.ref, "services": now, "changed": True}


@route("trip-services", "a manifest's own services (Planning's Services tab): list them, or take some off (--remove; "
                        "do the trip before its orders - they pass on both ways); shows unless --commit")
def r_trip_services(a):
    found = r_trip_find(a)
    if found.get("found") != "selected":
        return found
    t, s = tab("Services", "Planning")
    have = service_rows(s, t)
    ids = [x["id"] for x in have]
    print(f"{found['man']} services: " + "; ".join(f"{x['id']} x{x['qty']}" for x in have) if have
          else f"{found['man']} has no services")
    removes = [x.upper() for x in a.remove or []]
    todo = [c for c in removes if c in ids]
    if not todo:
        tab("Trip Detail", "Planning")
        return dict(found, services=ids, changed=False)
    if not a.commit:
        tab("Trip Detail", "Planning")
        print(f"WOULD TAKE OFF {', '.join(todo)}, Save, Refresh Trip - nothing changed (no --commit)")
        return dict(found, services=ids, changed=False)
    for code in todo:
        t, s = tab("Services", "Planning")
        line = next(x for x in service_rows(s, t) if x["id"] == code)
        delete = s.one("the Services tab's Delete", role="push button", name="Delete", within=t)
        act([click(line["cell"], after=0.5), click(delete, after=1.0)], f"take {code} off the trip")
    t, s = tab("Services", "Planning")
    panel_save = s.find(name="Save", role="push button", within=t, enabled=True)
    if panel_save:
        act([click(panel_save[0], after=1.5)], "the Services tab's Save")
    s = ok_known_questions()
    refresh = s.find(name="Refresh Trip", role="push button", within=s.frame("Planning"), enabled=True)
    if refresh:
        act([click(refresh[0], after=2.0)], "Refresh Trip")
    t, s = tab("Services", "Planning")
    now = [x["id"] for x in service_rows(s, t)]
    tab("Trip Detail", "Planning")
    left = [c for c in todo if c in now]
    print(f"{found['man']}: services now {', '.join(now) or 'none'}")
    if left:
        raise Fail(f"{', '.join(left)} still on {found['man']} after Save - look at it")
    return dict(found, services=now, changed=True)


@route("order-close", "close the open order window(s); stops, keeping the changes, if any are unsaved")
def r_order_close(a):
    n = close_orders()
    return {"closed": n, "said": f"closed {n}"}


@route("order-read", "open an order by its line ref, read it all back (Detail, header), close it again - changes nothing")
def r_order_read(a):
    close_orders()
    f, s, row = open_order(a.ref, modify_scheduled=a.modify, gone_ok=True)
    d = read_detail(s, f)
    print_detail(d)
    words = list(TABS) if a.all else [w.strip() for w in (a.tabs or "").split(",") if w.strip()]
    bad = [w for w in words if w not in TABS]
    if bad:
        raise Fail(f"no tab '{bad[0]}' - tabs: {', '.join(TABS)}")
    if words:
        d["tabs"] = read_tabs(words, d["window"])
        print_tabs(d["tabs"])
    if not a.keep_open:
        close_window(d["window"])
    return {"order": d}


@route("order-find", "every line of an order in Order Summary: status, schedule, type, ready, deliver by (reads only)")
def r_order_find(a):
    rows, _ = order_search(a.ref)
    for r in rows:
        print("  " + _row_text(r))
    return {"lines": [{k: v for k, v in r.items() if k != "cells"} for r in rows]}


@route("order-open", "open an order's own window by its line ref (e.g. 1234567-1-1) and read it back")
def r_order_open(a):
    f, s, row = open_order(a.ref, modify_scheduled=a.modify, gone_ok=True)
    print(f"Open: {clean(f.get('nm'))} ({row.get('status')})")
    return {"window": clean(f.get("nm")), "line": {k: v for k, v in row.items() if k != "cells"}}



@route("where", "what's open in CTMS now: its windows, the cursor, any box up (reads only)")
def r_where(a):
    s = read()
    out = {"open": [clean(f.get("nm")) for f in s.frames()], "cursor": describe(s.focus),
           "boxes": [{k: b[k] for k in ("title", "words", "buttons")} for b in s.boxes()], "took": s.took}
    print(s.summary())
    return out


@route("find", "every menu, button, box or cell whose name or value has TEXT (reads only)")
def r_find(a):
    s = read()
    hits = [e for e in s.els if (a.text.lower() in clean(e.get("nm")).lower()
                                 or a.text.lower() in str(e.get("v") or "").lower())]
    for e in hits[:60]:
        print(f"  [{e.get('n')}] w{e.get('w')} lv{e.get('lv')} {describe(e)}  at {e.get('at')}"
              + (f"  {e.get('st')}" if e.get("st") else ""))
    return {"hits": len(hits)}


@route("show", "everything on the screen in one CTMS window (e.g. \"Order Search\"), by name and value (reads only)")
def r_show(a):
    s = read()
    f = s.frame(a.window)
    if f is None:
        boxes = [b for b in s.boxes() if a.window.lower() in (b["title"] + " " + b["words"]).lower()]
        if not boxes:
            raise Fail(f"no window '{a.window}' open ({s.summary()})")
        els = boxes[0]["els"]
    else:
        els = [e for e in s.children(f) if on_screen(e)]
    shown = 0
    for e in els:
        if not a.all and e.get("r") == "text" and not clean(e.get("nm")) and e.get("v") in (None, ""):
            continue                                      # an empty unnamed grid cell: noise
        print(f"  [{e.get('n')}] lv{e.get('lv')} {describe(e)}  at {e.get('at')}"
              + (f"  {e.get('st')}" if e.get("st") else ""))
        shown += 1
    return {"window": a.window, "shown": shown}


@route("press", "click a button, tab or cell by its name (--double opens a row, --right its menu)")
def r_press(a):
    e = press(a.name, double=a.double, right=a.right, role=None if a.any else ("push button", "page tab"))
    return {"pressed": describe(e)}


@route("menu", 'open a menu path, e.g. "C-TMS Modules > Order Management > Orders"')
def r_menu(a):
    open_menu(a.path)
    s = read()
    print(s.summary())
    return {"menu": a.path, "open": [clean(f.get("nm")) for f in s.frames()]}


def _args(name):
    p = argparse.ArgumentParser(prog=f"ctms_routes.py {name}")
    if name == "find":
        p.add_argument("text")
    elif name == "show":
        p.add_argument("window")
        p.add_argument("--all", action="store_true", help="empty unnamed cells too")
    elif name == "press":
        p.add_argument("name")
        p.add_argument("--double", action="store_true")
        p.add_argument("--right", action="store_true")
        p.add_argument("--any", action="store_true", help="any element, not only buttons and tabs")
    elif name == "menu":
        p.add_argument("path")
    elif name in ("trip-find", "trip-read", "trip-payments", "trip-price", "trip-status", "trip-resend",
                  "trip-unschedule", "trip-payments-clear", "trip-deltype"):
        p.add_argument("man", nargs="?", default="", help="the manifest, e.g. MAN-01000001")
        if name == "trip-deltype":
            p.add_argument("type", help="STANDARD, NEXT DAY or EMERGENCY")
            p.add_argument("--commit", action="store_true", help="set it (his go-ahead)")
            p.add_argument("--near-start", action="store_true", help="he has said yes inside 80 min of its start")
        if name == "trip-unschedule":
            p.add_argument("--line", help="only this order line (default: every one on the trip)")
        if name in ("trip-unschedule", "trip-payments-clear"):
            p.add_argument("--commit", action="store_true", help="really do it (his go-ahead for this trip)")
        if name == "trip-price":
            p.add_argument("total", help="the agreed total for the whole trip, e.g. 850")
            p.add_argument("--commit", action="store_true", help="change it (his figure, his go-ahead)")
        if name == "trip-status":
            p.add_argument("status", choices=sorted(STATUS_TPL))
        if name in ("trip-status", "trip-resend"):
            p.add_argument("--commit", action="store_true", help="really change it (his go-ahead for this trip)")
            p.add_argument("--near-start", action="store_true",
                           help=f"he has said yes although it starts within {NEAR_START} min")
        p.add_argument("--order", help="find it by an order line's Customer Ref instead")
        if name == "trip-read":
            p.add_argument("--tabs", default="", help="only these tabs, e.g. stops (default: "
                                                      "detail,stops,status,finance)")
    elif name == "order-services":
        p.add_argument("ref", help="the line")
        p.add_argument("--add", action="append", help="a service code to add, e.g. NIGHT, SAT, SUN, HIAB (repeatable)")
        p.add_argument("--remove", action="append", help="a service code to take off (repeatable)")
        p.add_argument("--modify", action="store_true", help="the line is scheduled: open it anyway (CTMS asks)")
        p.add_argument("--commit", action="store_true", help="change and save it (his go-ahead)")
    elif name == "trip-services":
        p.add_argument("man", nargs="?", default="", help="the manifest")
        p.add_argument("--order", help="find the manifest by an order line instead")
        p.add_argument("--remove", action="append", help="a service code to take off the trip (repeatable)")
        p.add_argument("--commit", action="store_true", help="take them off (his go-ahead)")
    elif name == "trip-trailer":
        p.add_argument("man", help="the manifest, e.g. MAN-01000001")
        p.add_argument("code", help="the trailer type code, e.g. NR_TROM_80FT")
        p.add_argument("--order", help="find the manifest by an order line instead")
        p.add_argument("--commit", action="store_true", help="set it (his go-ahead)")
        p.add_argument("--near-start", action="store_true", help="he has said yes inside 80 min of its start")
    elif name == "trip-apply":
        p.add_argument("ref", help="the UNSCHEDULED line, showing in Planning's order well")
        p.add_argument("man", help="the manifest to put it on")
        p.add_argument("--commit", action="store_true", help="apply it (his go-ahead)")
        p.add_argument("--near-start", action="store_true", help="he has said yes inside 80 min of its start")
    elif name == "order-deltype":
        p.add_argument("ref", help="an UNSCHEDULED line")
        p.add_argument("type", help="STANDARD, NEXT DAY or EMERGENCY")
        p.add_argument("--commit", action="store_true", help="set and save it (his go-ahead)")
    elif name == "order-copy":
        p.add_argument("ref", help="the line to copy, e.g. 1234567-1-1_S2")
        p.add_argument("--collect", required=True, help='"DD/MM/YY HH:MM - HH:MM" (or with a second date)')
        p.add_argument("--deliver", required=True, help='"DD/MM/YY HH:MM - HH:MM"')
        p.add_argument("--copies", type=int, default=1, help="how many copies (CTMS's No of Orders is this + 1)")
        p.add_argument("--commit", action="store_true", help="make the copy (his go-ahead)")
    elif name == "order-cancel":
        p.add_argument("ref", help="one line, e.g. 1234567-2-1 (every line is its own order)")
        p.add_argument("--restore", action="store_true", help="restore a cancelled line instead")
        p.add_argument("--commit", action="store_true", help="really cancel / restore it (his go-ahead)")
    elif name == "order-qty":
        p.add_argument("ref", help="the line, e.g. 1234567-1-1_S4")
        p.add_argument("qty", type=int, help="the line's new quantity")
        p.add_argument("--item", help="the item's Identifier, when the line has several")
        p.add_argument("--modify", action="store_true", help="the line is scheduled: open it anyway (CTMS asks)")
        p.add_argument("--commit", action="store_true", help="set it (his go-ahead)")
    elif name == "order-item":
        p.add_argument("ref", help="the line, e.g. AH24/11/26ABC or 1234567-1-1")
        p.add_argument("--weight", type=float, help="the line's total weight in kg (an ad hoc's is in its Special "
                                                    "Instructions) - needed when the item has none")
        p.add_argument("--product", help="the item drop-down's own name when it isn't the Detail tab's code with spaces "
                                         "for _ (default: the Detail tab's Product Type)")
        p.add_argument("--qty", type=float, help="Ordered, when creating the item (default: the Detail tab's Qty)")
        p.add_argument("--ident", action="store_true", help="take the Identifier from Ctrl+L's list again")
        p.add_argument("--modify", action="store_true", help="the line is scheduled: open it anyway (CTMS asks)")
        p.add_argument("--commit", action="store_true", help="type it in and save it (his go-ahead)")
    elif name == "order-split":
        p.add_argument("ref", help="the unscheduled line, e.g. 1234567-1-1")
        p.add_argument("parts", type=int, help="how many equal parts")
        p.add_argument("--commit", action="store_true", help="split it (his go-ahead)")
    elif name == "order-nc":
        p.add_argument("ref", help="the line, e.g. 1234567-1-1_S1")
        p.add_argument("--reason", required=True, help="the Reason Code exactly as CTMS spells it")
        p.add_argument("--activity", default="Load", help="the Activity (Load unless he says otherwise)")
        p.add_argument("--comment", required=True, help="no commas, no prices, under 250 characters")
        p.add_argument("--modify", action="store_true", help="the line is scheduled: open it anyway (CTMS asks)")
        p.add_argument("--commit", action="store_true", help="add it (his go-ahead for this one)")
    elif name == "order-note":
        p.add_argument("ref", help="the line, e.g. 1234567-1-1")
        p.add_argument("note", help='e.g. "Emailed DO 24/11" (" - " is put in front if missing)')
        p.add_argument("--commit", action="store_true", help="save it (his go-ahead: contact notes always have it)")
        p.add_argument("--modify", action="store_true", help="a booked line (the Run won't open one): done here, "
                                                             "the Ctrl+End way")
    elif name == "order-update":
        p.add_argument("refs", nargs="+", help="the lines, e.g. 1234567-1-1 1234567-2-1")
        p.add_argument("--collect", help='"DD/MM/YY HH:MM - HH:MM" (or with a second date)')
        p.add_argument("--deliver", help='"DD/MM/YY HH:MM - HH:MM"')
        p.add_argument("--comments", help="the delivery point's LOC comment (contact, phone, W3W...)")
        p.add_argument("--veh", choices=VEHICLES, help="only typed into an empty Veh Type")
        p.add_argument("--service", action="append", help="add a service, e.g. HIAB, REAR STEER, PTS (repeatable)")
        p.add_argument("--no-service", action="append", help="take a service off (repeatable)")
        p.add_argument("--storage", type=int, help="storage days")
        p.add_argument("--anyway", action="store_true", help="services even where CTMS has others (his call)")
        p.add_argument("--same-day", action="store_true", help="collect on the delivery day (the 65-mile rule)")
        p.add_argument("--commit", action="store_true", help="save it (only with his go-ahead for this job)")
    elif name in ("order-find", "order-open", "order-read"):
        p.add_argument("ref")
        if name in ("order-open", "order-read"):
            p.add_argument("--modify", action="store_true", help="open a scheduled order anyway (CTMS asks first)")
        if name == "order-read":
            p.add_argument("--keep-open", action="store_true", help="leave the order's window open afterwards")
            p.add_argument("--tabs", help="also read these tabs: " + ", ".join(TABS))
            p.add_argument("--all", action="store_true", help="read every tab")
    return p


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "list"):
        print(__doc__.split("\n\n")[0])
        print()
        for n, (fn, h) in ROUTES.items():
            print(f"  {n:18} {h}")
        return 0
    name = argv[0]
    if name not in ROUTES:
        print(f"No route '{name}'. Routes: {', '.join(ROUTES)}")
        return 2
    fn, _ = ROUTES[name]
    a = _args(name).parse_args(argv[1:])
    if name in CARD_ROUTES:
        PROFILE.update(CARD_SKIP)                         # its reads skip the windows behind (once switched on)
    t0 = time.time()
    try:
        out = fn(a) or {}
        ok, said = True, out.get("said", "done")
    except Fail as e:
        out, ok, said = {}, False, str(e)
        print("STOPPED: " + said)
    except R.Stop as e:
        out, ok, said = {}, False, str(e)
        print("STOPPED: " + said)
    secs = round(time.time() - t0, 1)
    for n in NOTICES:
        print(f"OK'd CTMS's notice: {n}")
    print(f"{'DONE' if ok else 'STOPPED'} {name} in {secs}s")
    extra = {"notices": list(NOTICES)} if NOTICES else {}
    print("ROUTE_RESULT " + json.dumps(dict(out, ok=ok, said=said, route=name, seconds=secs, **extra),
                                       ensure_ascii=False, default=str))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
