"""
The CTMS to-do's items, each done in one go here on the work PC (Delali, 02/11: "the run CTMS button is really annoying
me, because it's not working smoothly"). It used to come from the home PC a batch at a time, a picture with each and the
dashboard between them: about 70 seconds a note, 2 minutes a line, and a recipe with no anchor of its own typed a note
into Cost Centre when CTMS's page sat 21 pixels up.

No picture is read between the steps. CTMS's own words are found by exact pixels and what only the screen knows is read
through the Access Bridge - and a box is clicked where the Access Bridge places it. Nothing is typed until the cursor
reads as being in the right box, and nothing is saved until what was typed reads back with everything else as it was.

  note    the line opened, its Special Instructions read: ending with the note already, nothing typed - else the box
          clicked, the cursor checked, the note at its end, read back, Save, Close
  update  each line opened, its Veh Type box, deliver comment and Services read. The comment already what the plan would
          type: this line has been done. A Veh Type or another comment there: CTMS has it, HELD with nothing typed, unless
          "Type it in anyway" was picked. Else the times, the deliver side's comment, services off and on, the Veh Type
          only when the box is empty and never over another vehicle; Save (the schedule question OK'd), Close; then Order
          Summary read: Ready At and Deliver By must be what was typed

A stop backs out of whatever is open without saving, so one item going wrong needn't hold up the next.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta

import ctms_book
import ctms_orders
import ctms_rows

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_item_templates.json")

SERVICE_ROWS = 14                  # the Services grid's rows, as the Access Bridge reads them
SCHEDULE_READS = 3                 # after a Save, how many reads the schedule question gets to come up
# What a job's hours owe: what's typed in the grid (his "N / SAT / SUN + Tab", 31/10) and how its Service Id starts once it's in
OWED_SERVICES = {"NIGHT": ("N", "NIGHT"), "SATURDAY": ("SAT", "SAT"), "SUNDAY": ("SUN", "SUN")}
# The open order's Veh Type box, what it shows - only these are ever picked ("the vehicle tab, we don't use that rigid
# Moffett thing ... We just use the 40-foot rigid", 01/11: a HIAB or a Moffett goes in Services) - and each one's line in
# its list: how many presses of the list's down arrow, its thumb dragged up, bring that line into view (29-30/10). The
# list is only scrolled from an EMPTY box: on a filled one it opens at its own value.
VEH_BOX = (1052, 298, 1204, 324)
VEH_SHOWS = {"rigid": ("box-veh-rigid", "NR_Rigid (Up to 40ft)"), "artic": ("box-veh-artic", "NR_40ft Artic Flatbed"),
             "60ft": ("box-veh-60ft", "NR_60ft Artic Flat"), "80ft": ("box-veh-80ft", "NR_80ft-115ft trombone"),
             "tipper": ("box-veh-tipper", "NR_26ft 8 X 4 Rigid Tipper")}
VEH_PICK = {"rigid": ("veh-rigid-40ft", 20), "artic": ("veh-artic-40ft-flatbed", 6), "60ft": ("veh-artic-60ft", 6),
            "80ft": ("veh-artic-80ft", 9), "tipper": ("veh-tipper-26ft-8x4", 6)}
VEH_LIST = (880, 100, 1235, 330)

MENU_BAR = (1000, 37)
ORDER_SAVE, ORDER_CLOSE = (337, 733), (424, 733)
TAB_DETAIL, TAB_LOC, TAB_SERVICES = (57, 187), (365, 187), (750, 186)
TAB_BODY = [20, 200, 1250, 700]    # what a tab's click changes
LOC_COMMENTS, LOC_EDIT = (180, 643), (1080, 676)
LOC_BOX_LINE, LOC_BOX_SAVE = (575, 258), (470, 578)
TIMES_X = (185, 250, 333, 398)     # from date, from time, to date, to time
COLLECT_Y, DELIVER_Y = 357, 380
SERVICE_NEW, SERVICE_DELETE = (378, 648), (734, 648)
SERVICE_ROW_X, SERVICE_ROW_Y = 174, 295    # the grid's first row; each next one 23 px lower
DISCARD_WORDS = "discard your changes"
ANCHOR = {"action": "anchor", "window": True}
NOT_READ = ("Planning", "OPOKUD")  # the windows behind: nothing here is read off them, and they're most of a read's time
WINDOW = re.compile(r"\s*(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s*-\s*(?:(\d{2}/\d{2}/\d{2})\s+)?(\d{1,2}:\d{2})\s*")


class Stop(RuntimeError):
    """Not as expected, for this item. Its words are what Delali is told."""


class Busy(Stop):
    """Someone's work is open in CTMS: not backed out of, and the run doesn't go on over it."""


class Held(Exception):
    """CTMS has the update already - nothing typed, the item stays on the to-do."""


def templates():
    with open(TEMPLATES, encoding="utf-8") as f:
        t = json.load(f)
    t.update(ctms_book.templates())
    return t


def _click(pt, **extra):
    return dict({"action": "click", "px": list(pt)}, **extra)


def _key(name, after=0.05):
    return {"action": "key", "key": name, "after": after}


def _type(text, after=0.1):
    return {"action": "type", "text": str(text), "after": after}


def frames(els):
    return ctms_book.frames(els)


def card_of(els):
    return ctms_rows._frame(els, "Order details for")


def customer_ref(els):
    return ctms_book.card_ref(els)


def si_box(els):
    """The open order's Special Instructions box - None when no card is up."""
    for e in card_of(els) or []:
        if e.get("r") == "text" and "Special Instructions" in re.sub(r"\s+", " ", str(e.get("nm") or "")):
            return e
    return None


def special_instructions(els):
    box = si_box(els)
    return None if box is None else str(box.get("v") or "")


def focused(els):
    """What has the cursor on the open order's card, or None."""
    return next((e for e in card_of(els) or [] if "focused" in (e.get("st") or [])), None)


def other_fields(els):
    """What the card's boxes hold, all but Special Instructions: nothing else may change when a note goes on."""
    box = si_box(els)
    return [(tuple(e.get("at") or ()), str(e.get("v") or "")) for e in card_of(els) or [] if e.get("r") == "text" and e is not box]


def deliver_comment(els):
    """The deliver-side comment (LOC Detail > Comments): the right-hand of the two boxes under the selected Comments tab -
    None when that tab isn't up."""
    card = card_of(els)
    if card is None:
        return None
    i = next((k for k, e in enumerate(card) if e.get("r") == "page tab" and e.get("nm") == "Comments"
              and "selected" in (e.get("st") or [])), None)
    if i is None:
        return None
    boxes = []
    for e in card[i + 1:]:
        if e.get("r") == "page tab":
            break
        if e.get("r") == "text" and ctms_book.placed(e):   # by its size: a monitor left of or above the main one is all minus
            boxes.append(e)
    if len(boxes) < 2:
        return None
    return str(max(boxes, key=lambda e: e["at"][0]).get("v") or "")


def services(els):
    """The open order's Service Ids, top row first - the Services tab's first column. None when that tab isn't up."""
    card = card_of(els) or []
    i = next((k for k, e in enumerate(card) if e.get("r") == "push button" and e.get("nm") == "Charge Revenue"), None)
    if i is None:
        return None
    texts = [e for e in card[i + 1:] if e.get("r") == "text"][:SERVICE_ROWS]
    return [str(e.get("v") or "").strip().upper() for e in texts if str(e.get("v") or "").strip()]


def summary_line(els, ref):
    """Order Summary's row for one line: {ready_at, deliver_by} - None when it isn't listed."""
    frame = ctms_rows._frame(els, "Order Summary")
    if frame is None:
        return None
    cols = {}
    for e in frame:
        m = re.fullmatch(r"Enter value for : (\w+)(?:\s+Required)?", str(e.get("nm") or ""))   # the app's " Required"
        if e.get("r") == "text" and m and m.group(1) in ("EXTERNAL_REF", "EARLY_AVAIL", "LATE_DEL") and e.get("at"):
            cols.setdefault(m.group(1), []).append((e["at"][1], str(e.get("v") or "").strip()))
    down = {k: [v for _, v in sorted(c)] for k, c in cols.items()}
    for n, r in enumerate(down.get("EXTERNAL_REF") or []):
        if r == ref:
            pick = lambda k: (down.get(k) or [""] * (n + 1))[n] if n < len(down.get(k) or []) else ""  # noqa: E731
            return {"ready_at": pick("EARLY_AVAIL"), "deliver_by": pick("LATE_DEL")}
    return None


question = ctms_rows.question       # shared with Book, which stops on one it didn't expect


def window_parts(text):
    """(from date, from time, to date, to time) of "DD/MM/YY HH:MM-HH:MM" or "DD/MM/YY HH:MM-DD/MM/YY HH:MM"."""
    m = WINDOW.fullmatch(text or "")
    if not m:
        raise Stop(f"'{text}' isn't a time window.")
    d1, t1, d2, t2 = m.groups()
    return d1, t1.zfill(5), d2 or d1, t2.zfill(5)


def ends(window):
    """("dd/mm/yy HH:MM" start, "dd/mm/yy HH:MM" end) of a window."""
    if not window:
        return "", ""
    d1, t1, d2, t2 = window_parts(window)
    return f"{d1} {t1}", f"{d2} {t2}"


def _when(text):
    try:
        return datetime.strptime(str(text or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return None


def collection_fix(ref, s, line):
    """The collection has to come before the delivery, or CTMS doesn't keep the dates (his 03/11, 6055827: delivery pulled
    forward a day past a collection nobody touched), and a morning delivery isn't collected that same morning (his 03/11).
    {} when it does as it stands; else what the collection's dates move to, by his rule: the day before, a Monday's on the
    Friday with STORAGE x2. A collection the plan itself has wrong, or one that can't be told or can't be moved by the rule,
    stops the line with nothing typed."""
    if not s.get("deliver"):
        return {}
    start = _when(ends(s["deliver"])[0])
    if s.get("collect"):
        if _when(ends(s["collect"])[0]) >= start:
            raise Stop(f"{ref}: the collection ({s['collect']}) isn't before the delivery ({s['deliver']}), so nothing was typed.")
        return {}
    ready = _when((line or {}).get("ready_at"))
    if ready is None:
        raise Stop(f"{ref}: its collection couldn't be read to check it against the new delivery, so nothing was typed.")
    if ready < start and (ready.date() != start.date() or start.hour >= 12):
        return {}
    day = start.replace(hour=0, minute=0) - timedelta(days=1)
    storage = 0
    if day.weekday() == 6:
        day -= timedelta(days=2)
        storage = 2
    elif day.weekday() == 5:
        raise Stop(f"{ref}: its collection ({line['ready_at']}) has to move for the new delivery, and the day before is a Saturday - "
                   "no rule for that, so nothing was typed. Do this one by hand.")
    shown = day.strftime("%d/%m/%y")
    return {"day": shown, "storage": storage, "was": line["ready_at"], "ready_at": f"{shown} {ready:%H:%M}"}


def has_service(have, code):
    """That service on these Service Ids - a Night, Saturday or Sunday under either of its names."""
    typed, shown = OWED_SERVICES.get(code, (code, code))
    return any(sid == typed or sid.startswith(shown) for sid in have)


def rails(s, adds):
    """Delali's rules on what an update may type - the plan keeps to them, and nothing is typed that doesn't."""
    if "," in str(s.get("comments") or ""):
        return "No commas in CTMS comments (30/10)."
    if s.get("veh") in ("rigid", "tipper") and ("REAR STEER" in adds or "rear steer" in str(s.get("comments") or "").lower()):
        return "A rigid never needs rear steer (30/10)."
    if any(a.startswith("STOR") for a in adds) and s.get("collect") and s.get("deliver") \
            and window_parts(s["collect"])[0] == window_parts(s["deliver"])[0]:
        return "Storage is for a load collected before its delivery day (the AP06-B clean up sent eleven of those back)."
    return ""


class Items:
    """The to-do's items, one at a time. run(steps): steps carried out in CTMS's window, raising when one fails; read(): the
    Access Bridge's elements; seen(name, box): whether a template shows there now; t: the templates."""

    def __init__(self, run, read, seen, t):
        self.run, self.read, self.seen, self.t = run, read, seen, t
        self.els = []
        self.refs = []             # the lines of the item in hand: the only cards ever discarded
        self.stages = []
        self._t = time.time()

    def stage(self, name):
        now = time.time()
        self.stages.append([name, round(now - self._t, 1)])
        self._t = now

    def look(self):
        self.els = self.read()
        return self.els

    def shows(self, name, box, timeout):
        """Whether a template comes up there within so long."""
        try:
            self.run([ctms_orders._find(self.t, name, box, timeout)])
            return True
        except RuntimeError:
            return False

    # -- getting about
    def begin(self):
        """A run's start: nothing of someone's left open over Order Summary. An order with changes not saved stops the run,
        untouched; a carrier window up in front is closed by its own Exit, which changes nothing."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.4), ANCHOR])
        self.look()
        if card_of(self.els) is not None:
            self.run([_click(ORDER_CLOSE, after=1.0)])
            self.look()
            q = question(self.els)
            if q:
                self.press(q[1].get("cancel"))
                raise Busy("An order is open in CTMS with changes not saved. Nothing was touched: save or close it and press "
                           "Run again.")
        # Booking reads CTMS with (tree, skip); the Run's own read takes neither - every read of the Run's is the
        # whole window bar its own skips (11/11: a carrier window left up was closed by its Exit, found by name, and
        # the read after it stopped the Run on a TypeError)
        booking = ctms_book.Booking(self.run, lambda tree=False, skip=(): self.read(), self.seen, self.t)
        booking.els = self.els
        booking.carrier_window_away()
        self.els = booking.els

    def press(self, button):
        """A button where the Access Bridge places it."""
        if button is None or not ctms_book.placed(button):
            raise Stop("CTMS asked something it wouldn't take an answer to: look at it.")
        self.run([{"action": "click", "screen": ctms_book._at(button), "after": 1.0}])

    def to_search(self):
        """Order Summary's Search card up, whichever way it has to be got to."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR])
        if not self.seen("os-card", ctms_orders.CARD_BOX):
            if self.seen("os-search", ctms_orders.SEARCH_BOX):
                self.run([ctms_orders._find(self.t, "os-search", ctms_orders.SEARCH_BOX, 5, click=True, react=True)])
            else:
                self.run([{"action": "anchor"}] + ctms_orders.to_orders(self.t))
        try:
            self.run(ctms_orders.card(self.t))
        except RuntimeError:
            if not ctms_orders.card_up(self.look()):    # the app's card can open away from where Edge's sat (10/11)
                raise
        far = ctms_orders.upto(self.look())       # a later order isn't listed at all under tomorrow's "up to"
        if far:
            self.run(far)

    def open(self, ref, read_line=False):
        """One line's card, proved to be that line's by its Customer Ref. A scheduled line asks "are you sure?" instead of
        opening, and stops here. read_line: Order Summary's times for it kept first, as self.line."""
        self.to_search()
        parts = ctms_orders.card_parts(self.els)          # to_search's read: the card up
        if parts and not parts.get("customer"):
            raise Stop(f"{ref}: CTMS's Order Search card is up without its Customer Ref box. Open the card's fields "
                       "(its Layout) and press Run again.")
        try:
            self.run(ctms_orders.search_at(self.els, ref))
        except RuntimeError:
            raise Stop(f"{ref}: CTMS's search found nothing for it.")
        if read_line:
            self.line = summary_line(self.look(), ref)
        try:
            self.run(ctms_orders.open_line_at(self.els if read_line else self.look(), self.t))
        except RuntimeError:
            raise Stop(f"{ref}: its card wouldn't open - it may have been booked since.")
        self.look()
        got = customer_ref(self.els)
        if got.upper() != ref.upper():
            raise Stop(f"{ref}: the card that opened reads {got or 'no order'}.")

    def close_quietly(self):
        """The card's Close, nothing typed: back on Order Summary."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR, _click(ORDER_CLOSE, react=True, timeout=15)])

    def save_close(self, ref):
        """Save (the schedule question OK'd: a delivery moved to another day asks "Change schedule to"), Close. A plain save
        CTMS answers by moving the cursor, no message, so a Close that asks nothing is what says it saved."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR, _click(ORDER_SAVE, react=True, quiet=1, timeout=15)])
        for _ in range(SCHEDULE_READS):
            if self.answer_schedule():
                break
            time.sleep(0.4)
        try:
            self.close_quietly()
        except RuntimeError:               # asked late, and the Close got nothing while it was up
            if not self.answer_schedule():
                raise
            self.close_quietly()
        asked = question(self.look())
        if asked and DISCARD_WORDS in asked[0]:
            raise Stop(f"{ref}: the save did not go through, so nothing of this line was kept.")

    def answer_schedule(self):
        """CTMS's "Change schedule to ...?" pressed OK, where the Access Bridge places it: it sits in the middle of CTMS's
        window, so it moves with the window's size (his 04/11, the fixed point missed it). True if it was up."""
        asked = question(self.look())
        if asked and "schedule" in asked[0].lower():
            self.press(asked[1].get("ok"))
            return True
        return False

    def clear_up(self):
        """After a stop: whatever is open backed out of, NOTHING saved. True when CTMS is clean; False, left as it is for a
        look, when something won't go - or when it isn't this item's: only its own lines' changes are ever discarded. A menu
        or list left open goes with the first click."""
        mine = {str(r).upper() for r in self.refs}
        try:
            self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR])
            for _ in range(4):
                self.look()
                q = question(self.els)
                if q:
                    words, buttons = q
                    if DISCARD_WORDS in words and customer_ref(self.els).upper() not in mine:
                        self.press(buttons.get("cancel"))
                        return False
                    self.press(buttons.get("ok") if DISCARD_WORDS in words else
                               buttons.get("cancel") or buttons.get("no") or buttons.get("ok"))
                elif card_of(self.els) is not None:
                    self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR, _click(ORDER_CLOSE, after=1.0)])
                else:
                    return True
        except Exception:
            pass
        return False

    def finish(self):
        """The run's end: Order Summary and its card closed, Planning as it was."""
        self.run([{"action": "anchor"}, ANCHOR])
        try:
            self.look()                       # the app's card can be up away from where Edge's sat (10/11)
        except Exception:
            self.els = []
        if self.seen("os-card", ctms_orders.CARD_BOX) or ctms_orders.card_up(self.els):
            self.run(ctms_orders.card_close_at(self.els))
        self.run(ctms_orders.close_summary(self.t))

    # -- the items
    def do(self, item, dry=False):
        """One item. dry: an update's first line typed and thrown away, for trying the run with nothing kept - not the deliver
        comment, whose box saves by itself."""
        s = item.get("set") or {}
        self.refs = list(item.get("lines") or [])
        if item.get("kind") == "note":
            return self.note(item["lines"][0], s.get("note") or "")
        if dry:
            return self.update(item["lines"][0], s, dry=True)
        lines, saved = list(item.get("lines") or []), []
        for i, ref in enumerate(lines):
            try:
                saved.append(self.update(ref, s))
            except Exception as e:
                if not saved:
                    raise
                # a later line stopped: the lines before it ARE saved in CTMS, and the answer must say so
                rest = lines[i + 1:]
                said = (f"Saved first: {'; '.join(saved)}. Then {ref} was not: {e}"
                        + (f" Not tried: {', '.join(rest)}." if rest else ""))
                raise (type(e) if isinstance(e, (Stop, Held)) else Stop)(said) from e
        return "; ".join(saved)

    def note(self, ref, note):
        self.open(ref)
        self.stage("opened")
        before = special_instructions(self.els)
        if before is None:
            raise Stop(f"{ref}: its card did not read.")
        if before.rstrip().endswith(note.strip()):
            self.close_quietly()
            return f"{ref}: '{note.strip()}' was there already"
        fields = other_fields(self.els)
        x, y, w, h = si_box(self.els)["at"]
        for _ in range(2):                 # the first click after CTMS comes to the front can only give its Java the focus
            self.run([{"action": "click", "screen": [x + w - 40, y + h - 8], "after": 0.3}])
            self.look()
            if focused(self.els) is not None and focused(self.els) == si_box(self.els):
                break
        else:
            raise Stop(f"{ref}: the cursor wouldn't go into Special Instructions, so nothing was typed.")
        # End alone stops at the end of the line clicked, and a long one wraps (02/11)
        self.run([_key("ctrl+end", 0.1), _type(note, 0.2)])
        self.look()
        if not (special_instructions(self.els) or "").rstrip().endswith(note.strip()) or other_fields(self.els) != fields:
            raise Stop(f"{ref}: the note did not read back, so it was not saved.")
        self.stage("typed")
        self.save_close(ref)
        self.stage("saved")
        return f"{ref}: '{note.strip()}' added"

    def veh_now(self):
        """What the open order's Veh Type box shows: a key of VEH_SHOWS, "" when empty - or None, another vehicle."""
        if self.seen("box-veh-empty", VEH_BOX):
            return ""
        return next((k for k, (tpl, _) in VEH_SHOWS.items() if self.seen(tpl, VEH_BOX)), None)

    def update(self, ref, s, dry=False):
        self.open(ref, read_line=True)
        line = self.line
        fix = collection_fix(ref, s, line)
        now = self.veh_now()
        self.stage("opened")
        comments = str(s.get("comments") or "")
        if not s.get("anyway"):
            self.run([ANCHOR, _click(TAB_LOC, react=True, box=TAB_BODY, timeout=10),
                      _click(LOC_COMMENTS, react=True, box=[20, 500, 1250, 760], timeout=10)])
            said = deliver_comment(self.look())
            if said is None:
                raise Stop(f"{ref}: its LOC Detail comments would not read, so nothing was typed.")
            if comments and said.strip() == comments.strip():
                # this very update went in before: a run stopped part way, or a repeat - unless CTMS didn't keep its dates
                if not s.get("deliver") or (line or {}).get("deliver_by") == ends(s["deliver"])[1]:
                    self.close_quietly()
                    return f"{ref}: has this update already"
            elif now != "" or said.strip():
                self.close_quietly()
                there = [f"Veh Type {VEH_SHOWS[now][1] if now in VEH_SHOWS else 'set'}" if now != "" else "",
                         f"deliver comment '{said.strip()}'" if said.strip() else ""]
                raise Held(f"{ref}: CTMS has it already ({', '.join(x for x in there if x)}) - nothing typed; tick it off, or "
                           "pick 'Type it in anyway' on the item")
        # the vehicle: never over one that's there - a vehicle already on it that isn't the plan's is Delali's
        veh = s.get("veh")
        if veh:
            if now == veh:
                veh = None
            elif now != "":
                raise Stop(f"{ref}: its Veh Type is already "
                           + (VEH_SHOWS[now][1] if now else "a vehicle other than the ones the run picks")
                           + f", not {VEH_SHOWS[veh][1]} - left as it is, nothing typed.")
        self.run([ANCHOR, _click(TAB_SERVICES, react=True, box=TAB_BODY, timeout=10)])
        have = services(self.look())
        if have is None:
            raise Stop(f"{ref}: its Services tab did not read, so nothing was typed.")
        want = s.get("services") or {}
        removes = sorted((i + 1 for i, sid in enumerate(have) if sid in want and not want[sid]), reverse=True)
        adds = [code for code, on in want.items() if on and not has_service(have, code)]
        storage = s.get("storage") or fix.get("storage")
        if storage and "STORAGE" not in have:
            adds.append(f"STORAGE:{storage}")
        wrong = rails(s, adds)
        if wrong:
            raise Stop(f"{ref}: {wrong} Nothing was typed.")
        self.stage("read")
        only = not (fix or removes or any(s.get(k) for k in ("collect", "deliver", "comments", "veh")))
        if only and not adds:              # services alone, and they're on it
            self.close_quietly()
            return f"{ref}: has {' + '.join(want)} already"
        # services first, the tab being up: bottom rows first, as rows move up
        steps = [ANCHOR]
        for row in removes:
            steps += [_click((SERVICE_ROW_X, SERVICE_ROW_Y + 23 * (row - 1)), after=0.2), _click(SERVICE_DELETE, react=True, timeout=8)]
        for code in adds:
            code, _, qty = code.partition(":")     # "STORAGE:2" - a quantity of its own
            steps += [_click(SERVICE_NEW, react=True, box=[100, 270, 1100, 600], timeout=8), _type(OWED_SERVICES.get(code, (code,))[0]),
                      dict(_key("tab"), react=True, timeout=8), _type(qty or 1), _key("tab", 0.2)]
        if only:                           # services alone: read back in the grid, or nothing is kept
            try:
                self.run(steps)
            except RuntimeError as e:
                raise Stop(f"{ref}: CTMS did not take {', '.join(adds)} ({e}), so nothing was saved.")
            there = services(self.look()) or []
            lost = [c for c in adds if not has_service(there, c)]
            if lost:
                raise Stop(f"{ref}: {', '.join(lost)} did not read back in its Services, so nothing was saved.")
            self.stage("typed")
            if dry:
                if not self.clear_up():
                    raise Stop(f"{ref}: rehearsed, but CTMS wouldn't let it go - look at it.")
                return f"{ref}: rehearsed, nothing kept"
            self.save_close(ref)
            self.stage("saved")
            return f"{ref}: +{'+'.join(adds)}"
        # the times
        steps += [_click(TAB_DETAIL, react=True, box=TAB_BODY, timeout=10)]
        if fix:                            # its dates only: the hours stay the yard's
            for x in (TIMES_X[0], TIMES_X[2]):
                steps += [_click((x, COLLECT_Y), after=0.15), _key("home"), _key("shift+end"), _type(fix["day"])]
        times = [(s.get("collect"), COLLECT_Y), (s.get("deliver"), DELIVER_Y)]
        was, new = _when((line or {}).get("deliver_by")), _when(ends(s.get("deliver"))[1])
        if was and new and new > was:      # going later: the delivery first, so the two are never the wrong way round
            times.reverse()
        for val, y in times:
            if val:
                for x, v in zip(TIMES_X, window_parts(val)):
                    steps += [_click((x, y), after=0.15), _key("home"), _key("shift+end"), _type(v)]
        # the vehicle, the list only opened on an empty box
        if veh:
            name, downs = VEH_PICK[veh]
            steps += [_click((1212, 310), react=True, timeout=8),
                      {"action": "drag", "px": [1195, 299], "px2": [1195, 228], "after": 0.4}]
            steps += [_click((1195, 312), after=0.08)] * downs
            steps += [ctms_orders._find(self.t, name, VEH_LIST, 3, click=True, react=True)]
        # the comment: LOC Detail > Comments, the deliver side's Edit, its own Save. Only there (where it's read, 30/10)
        if comments and not dry:
            steps += [_click(TAB_LOC, react=True, box=TAB_BODY, timeout=10), _click(LOC_COMMENTS, after=0.6),
                      _click(LOC_EDIT, react=True, timeout=10), _click(LOC_BOX_LINE, after=0.3), _key("home"), _key("shift+end"),
                      _type(comments), _click(LOC_BOX_SAVE, react=True, timeout=10)]
        try:
            self.run(steps)
        except RuntimeError as e:
            raise Stop(f"{ref}: the update stopped part way ({e}), so nothing of this line was saved.")
        self.stage("typed")
        if dry:
            if not self.clear_up():
                raise Stop(f"{ref}: rehearsed, but CTMS wouldn't let it go - look at it.")
            return f"{ref}: rehearsed, nothing kept"
        self.save_close(ref)
        self.stage("saved")
        got = summary_line(self.look(), ref)
        c0, _ = ends(s.get("collect"))
        c0 = c0 or fix.get("ready_at", "")
        _, d1 = ends(s.get("deliver"))
        if got is None:
            raise Stop(f"{ref}: saved, but Order Summary did not list it to check.")
        if (c0 and got["ready_at"] != c0) or (d1 and got["deliver_by"] != d1):
            raise Stop(f"{ref}: saved, but CTMS reads Ready At {got['ready_at']} / Deliver By {got['deliver_by']} - not {c0} / {d1}.")
        self.stage("checked")
        bits = [f"collect {s['collect']}" if s.get("collect") else "",
                f"collection moved to {fix['day']} (it was {fix['was']})" if fix else "",
                f"deliver {s['deliver']}" if s.get("deliver") else "",
                VEH_SHOWS[veh][1] if veh else (f"{VEH_SHOWS[s['veh']][1]} already" if s.get("veh") else ""),
                ("+" + "+".join(c.split(":")[0] for c in adds)) if adds else "", f"-{len(removes)} service(s)" if removes else ""]
        return f"{ref}: {', '.join(x for x in bits if x)}"
