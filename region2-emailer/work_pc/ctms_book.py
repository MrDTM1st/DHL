"""
The order panel's Book button, run here on the work PC in one go (his 02/11: "It takes me around 40 seconds to 1 minute
to book in something like that. That needs to be the target for you ... you've got to be faster than I am").

No picture is read between the steps: CTMS's own words on its menus and box titles are found by exact pixels
(ctms_book_templates.json) and what only the screen knows - which row is the order, which manifest is new - is read
through the Access Bridge. In order, the way he books:

  1. the order well's own To and the manifest tree's Sched both on the delivery day - one doesn't reliably follow the other
  2. the order's unscheduled lines for that day found in the well: as it stands, then with the Deliver column pressed
     (his tip: latest first, so the day's orders are on top), then with the well's own Refresh
  3. the delivery type put up when the real date makes it more urgent than the order says - "the delivery type has to
     be set before you create the trip"
  4. one line going on several vehicles: split equally through Order Summary, which brings the weight down with it
     (his rule: "whatever weight it had when it initially came into CTMS is the original weight you're supposed to be
     splitting it down to" - nothing is typed into a weight here)
  5. each vehicle's trip: its lines selected in one go (his way 03/11: Shift-click down to the last, Ctrl-click when
     others sit between them), Create New Trip, the carrier, the trailer, the haulage (typed only when he gave one: tier 1
     comes off the matrix, DHL NOC stays 0), Create Trip, Yes once the box names the right carrier and a real cost; Save;
     Planned Orders says what the trip took - a line of ours it didn't gets Apply to Trip, one that isn't ours stops it
  6. every line checked on the manifest, set Accepted, Save, read back

Anything not as expected stops there with what was done so far, and any box left open is backed out of so nothing goes
on half made. dry runs it all but presses No at the last box, so a run can be tried with nothing booked - but CTMS keeps a
trailer picked on the carrier screen as that line's Veh Type, whatever the last box is answered (seen 02/11).

Every px point is on the recipes' pictures - the batch's anchor moves it to wherever CTMS sits now; a screen point is
where the Access Bridge placed the thing.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta

import ctms_filters
import ctms_lines
import ctms_orders
import ctms_rows

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_book_templates.json")

CARRIER_FRAME = "Select a Carrier"
ROW_MENU = (430, 25, 810, 880)     # a well row's menu: beside the row, as far up as it has to go
TREE_MENU = (190, 25, 430, 880)    # a manifest's menu, likewise
STATUS_MENU = (400, 25, 520, 880)  # its Set Status list
SUMMARY_MENU = (150, 200, 345, 760)  # an Order Summary line's menu
CARRIER_TITLE = (430, 40, 700, 90)
PAYMENT_TITLE = (500, 370, 800, 420)
SPLIT_TITLE = (350, 370, 600, 420)

MENU_BAR = (1000, 37)              # an empty bit of it: gives Java the focus, closes a menu left open
SCHED_ARROW = (162, 133)
TRAILER_BOX = (1228, 319)
TRAILER_UP = (1347, 165)           # the open trailer list's up arrow - a row a click
ALT_CARRIER_BOX = (971, 400)
SELECT_CARRIER, CARRIER_EXIT = (912, 363), (1042, 363)
CREATE_TRIP, PAYMENT_CANCEL = (1015, 449), (1015, 479)
PLANNING_SAVE = (1337, 98)
ORDERS_BUTTON = (1360, 166)
PLANNED_X, PLANNED_Y = 13, 10      # Planned Orders' own X, from its top right corner: the panel doesn't open in one place
ORDER_SAVE, ORDER_CLOSE = (337, 733), (424, 733)
CURRENT_ROW = "#FFCC00"            # the well's current row, from its From Loc across

RANK = {"STANDARD": 0, "NEXT DAY": 1, "EMERGENCY": 2}
NOC = "DHL_NOC"
NIGHT_FROM = 20                    # a delivery starting this late sits on the next day's schedule (seen 30/10, 02/11)
PAGES = 6                          # pages of the well looked through
LIST_PAGES = 8                     # looks down a drop-down: a letter of the carrier list can run to dozens
MANIFEST = re.compile(r"(MAN-\d+)\s*\((\w+)\)")
SCHEDULED_ON = re.compile(r"scheduled on trip:\s*(\d+)\s*/\s*(MAN-\d+)", re.I)
ANCHOR = {"action": "anchor", "window": True}
# What a read leaves out (03/11, measured live): Planning's Stops and Resources tab pages, never read by Book; with an
# order's card up, Planning and the OPOKUD window behind it altogether - the card is all that's wanted then
PLANNING_SKIP = ("Stops", "Resources")
CARD_SKIP = ("Planning", "OPOKUD")


class Stop(RuntimeError):
    """Not as expected: stop here. Its words are what he is told."""


def templates():
    with open(TEMPLATES, encoding="utf-8") as f:
        t = json.load(f)
    t.update(ctms_orders.templates())
    return t


def _find(t, name, box, timeout, **extra):
    return ctms_orders._find(t, name, box, timeout, **extra)


def _click(pt, **extra):
    return dict({"action": "click", "px": list(pt)}, **extra)


def _key(name, after=0.05):
    return {"action": "key", "key": name, "after": after}


def _at(element):
    """The screen point at the middle of something the Access Bridge placed."""
    x, y, w, h = element["at"]
    return [x + w // 2, y + h // 2]


def placed(element):
    """Whether it is on the screen: what isn't comes with -1s."""
    at = element.get("at") or []
    return len(at) == 4 and at[2] > 0 and at[3] > 0


def belongs(ref, orders):
    return any(ctms_orders.belongs(ref, o) for o in orders)


def lines_of(rows, orders, date=""):
    """The well's rows that are these orders' lines, and on that day when one is given - his dated records: another day's
    lines of one order are another delivery."""
    got = (r for r in rows if belongs(r.get("cust_ref"), orders))
    return sorted((r for r in got if not date or ctms_orders.day(r.get("deliver")) == date), key=lambda r: r["cust_ref"])


def sched_for_day(date):
    """The tree's yymmdd for a dd/mm/yyyy."""
    return datetime.strptime(date, "%d/%m/%Y").strftime("%y%m%d")


def sched_for_delivery(deliver):
    """The schedule a well row's "dd/mm/yy HH:MM" sits on: its own day - a night delivery's the next ("CTMS puts a night
    delivery on the NEXT day's schedule"). None when it can't be read."""
    try:
        when = datetime.strptime(str(deliver or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return None
    return (when + timedelta(days=1 if when.hour >= NIGHT_FROM else 0)).strftime("%y%m%d")


def wanted_type(current, deliver, now):
    """The delivery type to set, or None when the order's will do. His bands, from now to the delivery's start: under 24
    hours EMERGENCY, up to 72 NEXT DAY, else STANDARD - only ever moved up: a Friday order for Monday can sit at 75 hours
    and he leaves it NEXT DAY as it came (30/10)."""
    try:
        when = datetime.strptime(str(deliver or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return None
    hours = (when - now).total_seconds() / 3600
    want = "EMERGENCY" if hours < 24 else "NEXT DAY" if hours <= 72 else "STANDARD"
    have = next((k for k in RANK if str(current or "").strip().upper().startswith(k[:6])), "STANDARD")
    return want if RANK[want] > RANK[have] else None


def manifests(els):
    """Every manifest on the tree: {MAN-...: {"status", "at", "selected"}} - its labels read 'Level 0 05/11/26 08:00
    MAN-01000036  (ACCEPTED)', with their place on the screen (off it above or below when scrolled away)."""
    out = {}
    for e in els:
        nm = str(e.get("nm") or "")
        if e.get("r") == "label" and nm.startswith("Level "):
            m = MANIFEST.search(nm)
            if m:
                out[m.group(1)] = {"status": m.group(2), "at": e.get("at"), "selected": "selected" in (e.get("st") or [])}
    return out


def tree_box(els):
    return next((e.get("at") for e in els if e.get("r") == "tree"), None)


def new_manifest(els, before):
    """The manifest a Create Trip just made: CTMS's own status line if it still shows, else the one the tree didn't have."""
    for e in els:
        m = SCHEDULED_ON.search(str(e.get("nm") or "") + " " + str(e.get("v") or ""))
        if m:
            return m.group(2)
    now = manifests(els)
    new = [m for m in now if m not in before]
    picked = [m for m in new if now[m]["selected"]]     # a colleague's can turn up at the same moment
    return new[0] if len(new) == 1 else picked[0] if len(picked) == 1 else None


def card_ref(els):
    """The Customer Ref on the open order's card - its window is named by the internal number, not the ref."""
    return next((str(e.get("v") or "").strip() for e in ctms_rows._frame(els, "Order details for") or []
                 if e.get("r") == "text" and str(e.get("nm") or "").strip() == "Customer Ref"), "")


def planned_refs(els):
    """The customer refs on the Planned Orders panel, a window of its own."""
    return {str(e.get("v") or "").strip() for e in ctms_rows._frame(els, "Planned Orders") or []
            if e.get("r") == "text" and e.get("nm") == "Cust Ref"} - {""}


def frames(els):
    return [str(e.get("nm") or "") for e in els if e.get("r") == "internal frame"]


def sched_of(els):
    """The tree's Sched as it stands."""
    return next((str(e.get("v") or "").strip() for e in els if e.get("r") == "text" and e.get("nm") == "Sched"), "")


def carrier_cell(els, name):
    """His carrier's row on the carrier screen, by its cell - None when it isn't one of the lane's rows."""
    want = str(name).strip().upper()
    return next((e for e in ctms_rows._frame(els, CARRIER_FRAME) or [] if e.get("r") == "text" and placed(e)
                 and str(e.get("v") or "").strip().upper() == want), None)


def list_row(els, name):
    """An open drop-down's row with exactly these words, or None. Its rows come as labels with their places; those of a
    list opened earlier stay among them, placed nowhere."""
    want = str(name).strip().upper()
    return next((e for e in ctms_rows._frame(els, CARRIER_FRAME) or []
                 if e.get("r") == "label" and placed(e) and str(e.get("nm") or "").strip().upper() == want), None)


def confirm_box(els):
    """{"carrier", "revenue", "cost"} off the Confirm Create Trip box, or None when it can't be read. A Forms question comes
    as a window of its own, its words in its name: "Confirm Create Trip Carrier  X\\nRevenue  1.00\\nCost  2.00\\n..."."""
    m = re.search(r"Confirm Create Trip\s+Carrier\s+(\S+)\s+Revenue\s+([\d,.]+)\s+Cost\s+([\d,.]+)", " ".join(frames(els)))
    if not m:
        return None
    return {"carrier": m.group(1), "revenue": m.group(2).replace(",", ""), "cost": m.group(3).replace(",", "")}


def line_wants(refs, orders, qty):
    """Each line's quantity as the desk knows the order's: an order of one line has the order's whole quantity; an order
    over several lines has no figure a line (only the total could be checked, and which line is short can't be told), so
    those lines are checked Detail against Order Items alone."""
    out = {}
    for o in orders:
        if qty.get(str(o)) in (None, ""):
            continue
        mine = [r for r in refs if belongs(r, [o])]
        if len(mine) == 1:
            out[mine[0]] = float(qty[str(o)])
    return out


class Booking:
    """One Book press. run(steps): steps carried out in CTMS's window, raising when one fails; read(): the Access Bridge's
    elements; seen(name, box): whether a template shows there now; t: the templates."""

    def __init__(self, run, read, seen, t, now=None, dry=False):
        self.run, self.read, self.seen, self.t = run, read, seen, t
        self.now = now or datetime.now()
        self.dry = dry
        self.els = []
        self.sched = ""
        self.flipped = False       # the Deliver column pressed: pressed again at the end, so it's as he left it
        self.to_was = ""           # the well's To as he had it: put back at the end
        self.trips = []
        self.reads = 0             # Access Bridge reads this booking took: the seconds he waits are mostly these
        self.filters_was = {}      # the well's filters as he had them, while Book has them cleared: {window: {name: value}}
        self.has_tree = False
        self.veh_kept = ""         # what CTMS now keeps as the Veh Type of the line taken to the carrier screen
        self.said = []
        self.stages = []
        self._t = time.time()

    def stage(self, name):
        """How long that part took, for the seconds he is shown."""
        now = time.time()
        self.stages.append([name, round(now - self._t, 1)])
        self._t = now

    def look(self, tree=False, asking=False, card=False):
        """CTMS as it is now, through the Access Bridge. tree: Planning's manifest tree as well - only wanted around a
        trip being made (the manifests before, the new one after, Accepted): 112 rows on a weekday (03/11), read for
        nothing everywhere else. asking: a question of CTMS's is expected on this read (Confirm Create Trip, "discard
        your changes?") - any other one stops the booking, answered the way that changes nothing. card: an order's card
        is what's wanted - Planning behind it isn't read (850 things, 03/11)."""
        self.els = self.read(tree, CARD_SKIP if card else PLANNING_SKIP)
        self.has_tree = tree
        self.reads += 1
        if not asking:
            self.unasked()
        return self.els

    def unasked(self):
        """A Forms question nobody asked for (03/11, live: "A schedule must be selected." when a list ran off its end):
        read, answered OK when that's all it offers, else No / Cancel - never Yes - and the booking stopped with CTMS's
        own words, so nothing goes on over it."""
        q = ctms_rows.question(self.els)
        if not q:
            return
        words, buttons = q
        said = re.sub(r"\s+", " ", words).strip()
        pick = next((buttons[k] for k in ("ok", "no", "cancel") if k in buttons), None)
        if pick is not None and placed(pick):
            try:
                self.run([{"action": "click", "screen": _at(pick), "after": 0.5}])
            except Exception:
                pass
        raise Stop(f"CTMS asked something unexpected: \"{said[:200]}\" - answered "
                   f"{(str(pick.get('nm')).split() or ['nothing'])[0] if pick is not None else 'nothing'} and stopped "
                   "there.")

    def asked(self, words="", seconds=8):
        """A Forms question with these words, once it's up, found through the Access Bridge: these sit in the middle of CTMS's
        window, so they move with its size (his 04/11). None if none came; one with other words stops the booking."""
        end = time.time() + seconds
        while True:
            self.look(asking=True)
            q = ctms_rows.question(self.els)
            if q and words.lower() in q[0].lower():
                return q
            if q:
                self.unasked()
            if time.time() >= end:
                return None
            time.sleep(0.2)

    def ok_step(self, q, **extra):
        """The step that presses a question's OK. One without an OK is not what was expected: it stops the booking."""
        ok = q[1].get("ok")
        if ok is None or not placed(ok):
            self.unasked()
            raise Stop(f"CTMS asked \"{q[0][:200]}\" and its OK couldn't be found - look at it.")
        return dict({"action": "click", "screen": _at(ok)}, **extra)

    # -- getting about
    def start(self):
        """CTMS with Planning up and nothing open over it - an order left open with changes stops the run, untouched."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.4), ANCHOR])
        self.look(asking=True)
        left = ctms_rows.question(self.els)
        if left and set(left[1]) == {"ok"} and placed(left[1]["ok"]):
            # a notice already up before this booking began (live 03/11: "FRM-92220: access to system clipboard
            # denied"): not this booking's - OK'd, said, and on we go
            self.run([{"action": "click", "screen": _at(left[1]["ok"]), "after": 0.5}, ANCHOR])
            words = re.sub(r"\s+", " ", left[0]).strip()[:120]
            self.said.append(f"CTMS had \"{words}\" up from before: OK'd it")
            self.look()
        else:
            self.unasked()
        if not any(f.startswith("Planning") for f in frames(self.els)):
            self.run([{"action": "anchor"}, _click((121, 36), react=True, box=[60, 45, 300, 150], quiet=0.2, timeout=5),
                      _click((128, 87), react=True, box=[280, 60, 460, 300], quiet=0.2, timeout=5),
                      _click((249, 258), after=0.3), ANCHOR])                      # Trip Management > Planning
            for _ in range(10):
                if any(f.startswith("Planning") for f in frames(self.look())):
                    break
            else:
                raise Stop("Planning would not open in CTMS.")
        if any(f.startswith("Order details for") for f in frames(self.els)):
            self.run([_click(ORDER_CLOSE, after=1.0)])
            self.look(asking=True)
            asked = next((f for f in frames(self.els) if "discard your changes" in f), None)
            if asked:
                cancel = next((e for e in ctms_rows._frame(self.els, asked) or [] if e.get("r") == "push button"
                               and str(e.get("nm") or "").startswith("Cancel")), None)
                if cancel is not None:
                    self.run([{"action": "click", "screen": _at(cancel), "after": 0.5}])
                raise Stop("An order is open in CTMS with changes not saved. Nothing was touched: save or close it and "
                           "press Book again.")
        if any(f.startswith("Order Summary") for f in frames(self.els)):       # the to-do's Run leaves it up, and its card
            if self.seen("os-card", ctms_orders.CARD_BOX) or ctms_orders.card_up(self.els):
                self.run(ctms_orders.card_close_at(self.els))
            self.run(ctms_orders.close_summary(self.t))
            self.look()
        self.carrier_window_away()

    def carrier_window_away(self):
        """A carrier window up in front is closed by its own Exit, which changes nothing. One behind Planning stays there:
        CTMS's Window menu is never opened for it (his call 04/11)."""
        if not any(f.startswith(CARRIER_FRAME) for f in frames(self.els)):
            return
        if self.seen("sc-title", CARRIER_TITLE):
            self.run([_click(CARRIER_EXIT, after=0.8)])
            self.look()

    def set_sched(self, want):
        """The tree on that schedule: its list runs newest first, a day a row, so Up once per day ahead, Enter, read
        back (his walkthrough 29/10; a click on an open list's row can pick nothing)."""
        for _ in range(3):
            have = sched_of(self.els)
            if have == want:
                self.sched = want
                return
            try:
                days = (datetime.strptime(want, "%y%m%d") - datetime.strptime(have, "%y%m%d")).days
            except ValueError:
                raise Stop(f"Could not read the manifest tree's Sched ('{have}').")
            self.run([ANCHOR, _click(SCHED_ARROW, after=0.5)] + [_key("up" if days > 0 else "down")] * abs(days)
                     + [_key("enter", 0.3), {"action": "settle", "quiet": 0.6, "timeout": 15}])
            self.look()
        raise Stop(f"The manifest tree wouldn't go to schedule {want}: it shows {sched_of(self.els)}.")

    def to_box(self):
        """The well's To: its arrow, and its list's rows when open. Only an open list hands over what To says."""
        frame = ctms_rows._frame(self.els) or []
        at = next((i for i, e in enumerate(frame) if e.get("r") == "combo box" and e.get("nm") == "To" and placed(e)), None)
        if at is None:
            raise Stop("Could not find the order well's To date in Planning. Nothing was booked.")
        rows = []
        for e in frame[at + 1:]:
            if e.get("lv", 0) <= frame[at].get("lv", 0):
                break
            if e.get("r") == "label" and placed(e) and re.fullmatch(r"\d{6}", str(e.get("nm") or "")):
                rows.append(e)
        x, y, w, h = frame[at]["at"]
        return [x + w - 10, y + h // 2], rows

    def move_to(self, want):
        """The well's To on that schedule, the way the tree's goes: its list runs oldest first, a day a row, so Down once per
        day ahead, Enter (seen live 02/11). True when it was there already, the list shut again; the well re-queries if not."""
        arrow, rows = self.to_box()[0], []
        for _ in range(3):                               # a click without the focus may only give it the focus
            self.run([{"action": "click", "screen": arrow, "after": 0.5}])
            self.look()
            arrow, rows = self.to_box()
            if rows:
                break
        have = next((str(e["nm"]) for e in rows if "selected" in (e.get("st") or [])), "")
        if not have:
            if rows:
                self.run([{"action": "click", "screen": arrow, "after": 0.3}])
            raise Stop("Could not read the order well's To date. Nothing was booked.")
        self.to_was = self.to_was or have
        if have == want:
            self.run([{"action": "click", "screen": arrow, "after": 0.3}])
            return True
        days = (datetime.strptime(want, "%y%m%d") - datetime.strptime(have, "%y%m%d")).days
        self.run([_key("down" if days > 0 else "up")] * abs(days)
                 + [_key("enter", 0.3), {"action": "settle", "quiet": 0.6, "timeout": 15}])
        return False

    def set_day(self, want):
        """The well's To and the tree's Sched on that schedule (his 02/11: the order is found by the well's own date, and "the
        manifest tree, you have to do the same thing"). To is read back last: a change of the tree's Sched can move it."""
        self.move_to(want)
        self.set_sched(want)
        for _ in range(3):
            if self.move_to(want):
                return
        raise Stop(f"The order well's To wouldn't go to {want}. Nothing was booked.")

    def well(self):
        return ctms_rows.rows(self.els)

    def page_down(self, rows):
        self.run([{"action": "click", "screen": ctms_rows.point(rows[0]), "after": 0.3}, _key("pagedown", 0.8)])
        self.look()

    def scan(self, orders, date, hunt=True):
        """The orders' lines for that day from the page on the screen on, downwards. hunt False: only further down when
        this page has some of them and they run off its end."""
        got, rows = {}, self.well()
        for _ in range(PAGES):
            got.update((r["cust_ref"], r) for r in lines_of(rows, orders, date))
            if not rows or (not got and not hunt) or (got and not belongs(rows[-1]["cust_ref"], orders)):
                break                          # the last of them is above the page's end: there are no more under it
            if not got and date and self.all_before(rows, date):
                break                          # latest first and this page is already before that day
            top = rows[0]["cust_ref"]
            self.page_down(rows)
            rows = self.well()
            if not rows or rows[0]["cust_ref"] == top:
                break
        return [got[k] for k in sorted(got)]

    def well_days(self, rows):
        """The delivery days of these rows, in the order they show."""
        return [datetime.strptime(r["deliver"][:8], "%d/%m/%y") for r in rows
                if re.match(r"\d{2}/\d{2}/\d{2}", str(r.get("deliver") or ""))]

    def all_before(self, rows, date):
        """Whether a page running latest first has nothing as late as that dd/mm/yyyy."""
        days = self.well_days(rows)
        return bool(days) and days[0] >= days[-1] and days[0] < datetime.strptime(date, "%d/%m/%Y")

    def latest_first(self):
        """His way to an order in the well: "put the schedule to date on the delivery date, and then you press the deliver
        column, it reverses the sort order" - the latest first, so with To on its day the order is on top."""
        days = self.well_days(self.well())
        if len(days) < 2 or days[0] <= days[-1]:
            self.press_deliver()

    def press_deliver(self):
        """The Deliver column's heading pressed: it turns the well's order round."""
        hdr = next((e for e in self.els if e.get("r") == "push button" and e.get("nm") == "Deliver From" and placed(e)), None)
        if hdr is None:
            return False
        self.run([{"action": "click", "screen": _at(hdr), "after": 0.3}, {"action": "settle", "quiet": 0.5, "timeout": 15}])
        self.flipped = not self.flipped
        self.look()
        return True

    def refresh_well(self):
        """The well's own Refresh, off a row's menu - it isn't live: an import or a split only shows after it."""
        rows = self.well()
        if not rows:
            return                         # nothing delivering by that day as it is filtered: no row to right-click
        pt = ctms_rows.point(rows[0])
        self.run([{"action": "click", "screen": pt, "after": 0.7}, {"action": "click", "screen": pt, "right": True, "after": 0.3},
                  _find(self.t, "wm-refresh", ROW_MENU, 3, click=True, after=0.3),
                  {"action": "settle", "quiet": 0.6, "timeout": 20}])
        self.look()

    def lines(self, orders, date):
        """The orders' lines for that day - as the well stands, then latest first, then refreshed. [] when it hasn't got
        them."""
        got = self.scan(orders, date, hunt=False)
        if not got:
            self.latest_first()
            got = self.scan(orders, date)
        if not got:
            self.refresh_well()
            got = self.scan(orders, date)
        return got

    def on_screen(self, ref):
        """A line's row on the screen now, the well paged to it."""
        row = ctms_rows.find(self.well(), ref)
        if row:
            return row
        rows = self.well()
        if rows:
            self.run([{"action": "click", "screen": ctms_rows.point(rows[0]), "after": 0.3}] + [_key("pageup", 0.2)] * PAGES
                     + [{"action": "wait", "seconds": 0.5}])
            self.look()
        for _ in range(PAGES):
            rows = self.well()
            row = ctms_rows.find(rows, ref)
            if row or not rows:
                break
            top = rows[0]["cust_ref"]
            self.page_down(rows)
            if self.well() and self.well()[0]["cust_ref"] == top:
                break
        row = ctms_rows.find(self.well(), ref)
        if not row:
            raise Stop(f"{ref} went from the order well.")
        return row

    def row_menu(self, row, template, keep=False):
        """The row made current - shown by its colour, as a right-click works on the current record - then its menu's
        item (the menu's place moves with the row). keep: it was the last of several selected, and a plain click would
        lose the others."""
        pt = ctms_rows.point(row)
        self.run(([] if keep else self.make_current(row)) + [{"action": "click", "screen": pt, "right": True, "after": 0.3},
                                                             _find(self.t, template, ROW_MENU, 3, click=True, after=0.2)])

    def make_current(self, row):
        x, y = row["cell"][:2]
        return [{"action": "click", "screen": ctms_rows.point(row), "after": 0.2},
                {"action": "waitfor", "screen": [x + ctms_rows.OFFSETS["to_reg"] + 30, y + 2], "color": CURRENT_ROW, "timeout": 5}]

    def showing(self, refs):
        """Those of these lines the well shows now, top down."""
        return [r for r in self.well() if r.get("cust_ref") in refs]

    def select_lines(self, refs):
        """His way: all of a vehicle's lines selected before Create New Trip. Returns (the row for the menu, the refs
        selected). Lines a page apart can't all be clicked: the trip then picks them up by Apply to Trip."""
        first = self.on_screen(refs[0])
        got = self.showing(refs)
        if len(refs) == 1 or len(got) == len(refs):
            pass
        else:
            self.page_down(self.well())
            below = self.showing(refs)
            if len(below) > len(got):
                got = below
            else:
                first = self.on_screen(refs[0])
                got = self.showing(refs)
        if len(got) < 2:
            return first, [refs[0]]
        rows = self.well()
        at = [i for i, r in enumerate(rows) if r.get("cust_ref") in refs]
        steps = self.make_current(got[0])
        if at[-1] - at[0] == len(at) - 1:
            steps.append({"action": "click", "screen": ctms_rows.point(got[-1]), "hold": ["shift"], "after": 0.3})
        else:
            steps += [{"action": "click", "screen": ctms_rows.point(r), "hold": ["ctrl"], "after": 0.2} for r in got[1:]]
        self.run(steps)
        return got[-1], [r["cust_ref"] for r in got]

    def back_out(self):
        """Any box of the trip still up closed without booking, each looked for first: a click that finds its box gone lands
        on Planning behind it (the Confirm's No shuts the payment box too). A menu left open goes with the first click;
        on a box that wants an answer that click does nothing."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR])
        q = ctms_rows.question(self.look(asking=True))
        if q and "confirm create trip" in q[0].lower() and placed(q[1].get("no") or {}):
            self.run([{"action": "click", "screen": _at(q[1]["no"]), "after": 0.8}])
        if self.seen("cp-title", PAYMENT_TITLE):
            self.run([_click(PAYMENT_CANCEL, after=0.8)])
        if self.seen("sc-title", CARRIER_TITLE):
            self.run([_click(CARRIER_EXIT, after=0.8)])

    def tidy(self):
        """As he left it: the Deliver column back, the well's To back, no carrier window left in front. A trip not saved
        keeps the well as it is: a new To re-queries it."""
        self.run([ANCHOR])
        self.look()
        self.carrier_window_away()
        self.restore_filters()
        if self.to_was and not self.unsaved():
            self.move_to(self.to_was)
            self.look()
        days = self.well_days(self.well())             # the carrier screen can put the sort back itself (seen 02/11)
        if self.flipped and (len(days) < 2 or days[0] >= days[-1]):
            self.press_deliver()
        self.flipped = False

    def unsaved(self):
        """Whether Planning's Save is lit."""
        save = next((e for e in ctms_rows._frame(self.els) or [] if e.get("r") == "push button" and e.get("nm") == "Save"), None)
        return save is not None and "disabled" not in (save.get("st") or [])

    # -- what goes on the order first: each line's card, once
    def open_card(self, ref):
        """A line's own card, opened from the well and proved by its Customer Ref before anything goes in - the well can
        move under a stored place."""
        row = self.on_screen(ref)
        self.run([{"action": "click", "screen": ctms_rows.point(row), "double": True, "react": True,
                   "box": [20, 121, 1250, 171], "timeout": 20},
                  ANCHOR, _find(self.t, "od-vehtype", (940, 250, 1100, 380), 5)])
        got = card_ref(self.look(card=True))
        if got.upper() != ref.upper():
            self.run([_click(ORDER_CLOSE, react=True, timeout=15), ANCHOR])
            raise Stop(f"The well opened {got or 'no order'} for {ref}: closed it again, unchanged. Nothing was booked.")
        return row

    def card_tab(self, name):
        """One of the card's tabs, clicked where the Access Bridge places it, and read."""
        t = ctms_lines.tab(self.els, name)
        if t is None:
            raise Stop(f"The order's {name} tab couldn't be found on its card. Nothing was booked.")
        self.run([{"action": "click", "screen": ctms_lines.point(t), "react": True, "box": [20, 200, 1250, 700],
                   "quiet": 0.2, "timeout": 8}])
        return self.look(card=True)

    def type_into(self, box, text):
        """A box clicked where the Access Bridge places it, what it holds selected, the text typed over it."""
        self.run([{"action": "click", "screen": ctms_lines.point(box), "after": 0.15}, _key("home"), _key("shift+end"),
                  {"action": "type", "text": str(text), "after": 0.15}])

    def fix_item(self, ref, it, identifier, ordered):
        """One Order Items row put right in its own window (Edit/Delete): the Identifier through Ctrl+L's list, its top
        choice taken (his rule 03/11); Ordered typed. Read back, Save, Exit."""
        self.run([{"action": "click", "screen": ctms_lines.point(it["cell"]), "after": 0.3}])
        edit = ctms_lines.button(self.look(card=True), ctms_lines.CARD, "Edit/Delete")
        if edit is None:
            raise Stop(f"{ref}: Order Items' Edit/Delete couldn't be found. Nothing was booked.")
        self.run([{"action": "click", "screen": ctms_lines.point(edit), "react": True, "box": [20, 50, 850, 560],
                   "quiet": 0.2, "timeout": 10}])
        win = ctms_lines.item_window(self.look(card=True))
        if win is None or win["identifier"].upper() != it["identifier"].upper():
            raise Stop(f"{ref}: the item window that opened isn't {it['identifier']}'s. Nothing was changed.")
        if identifier:
            self.type_into(ctms_lines.field(self.els, ctms_lines.ITEM_WINDOW, "Identifier"), identifier)
            self.run([_key("ctrl+l", 0.3), {"action": "settle", "quiet": 0.3, "timeout": 8}])
            listed = ctms_lines.choices(self.look(asking=True, card=True))
            if not listed:
                cancel = ctms_lines.button(self.els, ctms_lines.LIST_WINDOW, "Cancel")
                if cancel is not None:
                    self.run([{"action": "click", "screen": ctms_lines.point(cancel), "after": 0.4}])
                raise Stop(f"{ref}: CTMS has no product item for {identifier} (Ctrl+L listed none). Nothing was saved.")
            ok = ctms_lines.button(self.els, ctms_lines.LIST_WINDOW, "OK")
            if ok is None:
                raise Stop(f"{ref}: Ctrl+L's list had no OK to press. Nothing was saved.")
            self.run([{"action": "click", "screen": ctms_lines.point(ok), "after": 0.4}])  # its top row is the one picked
            identifier = listed[0][0]
        if ordered is not None:
            self.type_into(ctms_lines.field(self.look(card=True), ctms_lines.ITEM_WINDOW, "Ordered"), f"{ordered:g}")
            self.run([_key("tab", 0.2)])
            # his rule (03/11, forgotten on 7116293 06/11): a new quantity means the weight is cleared, so the Save fills it
            # back in from the quantity - a split copies the old weight into every part otherwise. A Delivered 0 goes too
            for name in ("Weight", "Delivered"):
                box = ctms_lines.field(self.look(card=True), ctms_lines.ITEM_WINDOW, name)
                if box is not None and (name == "Weight" or str(box.get("v") or "").strip() in ("0", "0.0", ".0")):
                    self.run([{"action": "click", "screen": ctms_lines.point(box), "after": 0.15}, _key("home"),
                              _key("shift+end"), _key("delete", 0.2)])
        win = ctms_lines.item_window(self.look(card=True))
        if (identifier and win["identifier"].upper() != identifier.upper()) or (
                ordered is not None and not ctms_lines.same(win["ordered"], ordered)):
            raise Stop(f"{ref}: the item didn't read back as typed (Identifier {win['identifier']}, Ordered "
                       f"{win['ordered']}). Nothing was saved.")
        save = ctms_lines.button(self.els, ctms_lines.ITEM_WINDOW, "Save")
        self.run([{"action": "click", "screen": ctms_lines.point(save), "after": 0.6},
                  {"action": "settle", "quiet": 0.4, "timeout": 10}])
        self.answer_schedule(self.look(asking=True, card=True))
        leave = ctms_lines.button(self.els, ctms_lines.ITEM_WINDOW, "Exit")
        if leave is not None:
            self.run([{"action": "click", "screen": ctms_lines.point(leave), "after": 0.5}])
        if ctms_lines.item_window(self.look(asking=True, card=True)) is not None:
            raise Stop(f"{ref}: the item window wouldn't close after its Save - look at it in CTMS.")
        self.unasked()

    def answer_schedule(self, els):
        """CTMS's "Change schedule to ...?" after a save is answered OK, as the to-do update does; anything else asked
        stops the booking (answered the safe way)."""
        q = ctms_rows.question(els)
        if q and "schedule" in q[0].lower() and "ok" in q[1]:
            self.run([{"action": "click", "screen": _at(q[1]["ok"]), "after": 0.6}])
            self.look(asking=True, card=True)
        self.unasked()

    def check_line(self, ref, want=None):
        """His line checks on the card that is open (03/11): every item the Detail tab's product, the quantity the
        order's. What can't be settled stops before anything is typed. Returns whether anything was changed."""
        rows = ctms_lines.detail(self.els)
        if rows is None:
            rows = ctms_lines.detail(self.card_tab("Detail"))
        its = ctms_lines.items(self.card_tab("Order Items"))
        try:
            todo = ctms_lines.plan(ref, rows, its, want)
        except ctms_lines.Doubt as e:
            raise Stop(f"{e} Nothing was booked.")
        if self.dry:
            self.said += [w.replace(" put right", " would be put right") for w in todo["said"]]
            return False
        for i, identifier, ordered in todo["items"]:
            self.fix_item(ref, its[i], identifier, ordered)
            its = ctms_lines.items(self.look(card=True))
        if todo["qty"] is not None:
            box = (ctms_lines.detail(self.card_tab("Detail")) or [{}])[0].get("qty_box")
            if box is None:
                raise Stop(f"{ref}: the Detail tab's Qty couldn't be found. Nothing more was typed.")
            self.type_into(box, f"{todo['qty']:g}")
            self.run([_key("tab", 0.2)])
            got = ctms_lines.detail(self.look(card=True))
            if not got or not ctms_lines.same(got[0]["qty"], todo["qty"]):
                raise Stop(f"{ref}: the Detail tab's Qty didn't read back as {todo['qty']:g}. Not saved.")
        self.said += todo["said"]
        return bool(todo["items"] or todo["qty"] is not None)

    def set_type(self, ref, typ):
        """The delivery type up to his band on the card that is open (Add Detail), not saved yet."""
        self.run([_click((288, 187), react=True, box=[20, 200, 1250, 700], timeout=10),   # Add Detail
                  _click((273, 252), react=True, timeout=10),                              # Delivery Type's list
                  _click((960, 299), after=0.2), _key("home"), _key("shift+end"),
                  {"action": "type", "text": typ + "%", "after": 0.1},
                  _click((887, 721), react=True, timeout=10),                              # its Find
                  _click((978, 721), react=True, timeout=10), ANCHOR])                     # its OK
        self.said.append(f"{ref} put up to {typ}")

    def prepare_line(self, ref, want=None):
        """One line made ready to book on its own card, opened once: the checks (Order Items' product, the quantity), the
        delivery type when the date makes it more urgent, one Save, Close. Returns whether anything was changed."""
        row = self.open_card(ref)
        typ = wanted_type(row.get("del_type"), row.get("deliver"), self.now)
        try:
            changed = self.check_line(ref, want)
        except Stop:
            self.close_card(saved=False)
            raise
        if typ and not self.dry:
            self.set_type(ref, typ)
            changed = True
        elif typ:
            self.said.append(f"{ref} would be put up to {typ}")
        if changed:
            self.run([_click(ORDER_SAVE, react=True, quiet=1, timeout=15), ANCHOR])
            self.answer_schedule(self.look(asking=True, card=True))
        self.close_card(saved=changed)
        return changed

    def close_card(self, saved):
        """The card's Close. A "discard your changes?" means what was typed didn't save: Yes, it goes - and if the card
        was meant to be saved, the booking stops there."""
        self.run([_click(ORDER_CLOSE, react=True, timeout=15), ANCHOR])
        self.look(asking=True)
        asked = ctms_rows.question(self.els)
        if asked and "discard" in asked[0].lower():
            yes = asked[1].get("yes") or asked[1].get("ok")
            if yes is not None:
                self.run([{"action": "click", "screen": _at(yes), "after": 0.6}, ANCHOR])
                self.look(asking=True)
            if saved:
                raise Stop("The order's changes didn't save, so they were thrown away and nothing was booked: look at it "
                           "in CTMS.")
        self.unasked()

    # -- why the well hasn't got it: Order Summary asked, the filters cleared when they're what hides it
    def search_card(self, card=False):
        """Order Search's card up after to_orders: known by its labels where Edge drew it, or through the Access Bridge
        wherever the app opens it (10/11). The read taken with it up, for where its boxes are."""
        try:
            self.run(ctms_orders.card(self.t))
        except RuntimeError:
            if not ctms_orders.card_up(self.look(card=card)):
                raise
            return self.els
        return self.look(card=card)

    def summary_lines(self, orders):
        """Every line of these orders as Order Summary lists them (searches and reads only), then back to Planning."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.4)] + ctms_orders.to_orders(self.t))
        card = self.search_card(card=True)
        far = ctms_orders.upto(card, self.now)
        if far:
            self.run(far)
        got = []
        for o in orders:
            try:
                self.run(ctms_orders.search_at(card, ctms_orders.search_ref(o)))
            except RuntimeError:
                pass                           # nothing found leaves the list empty
            got += [r for r in ctms_orders.lines({"elements": self.look(card=True)}) or [] if ctms_orders.belongs(r["ref"], o)]
        self.run(ctms_orders.card_close_at(card) + ctms_orders.close_summary(self.t) + [ANCHOR])
        self.look()
        return got

    def why_missing(self, orders, date):
        """What Order Summary says about orders the well hasn't shown for that day: "hidden" when they ARE there,
        unscheduled, on that day - the well's filters must be keeping them out - else the words he is told."""
        rows = self.summary_lines(orders)
        named = " / ".join(orders)
        mine = [r for r in rows if ctms_orders.day(r.get("deliver_by")) == date]
        if any(r["status"] == ctms_orders.OPEN for r in mine):
            return "hidden"
        if mine:
            return f"{named} is booked in already on {date} (CTMS: {', '.join(sorted({r['status'] for r in mine}))})."
        other = sorted({f"{r['ref']} on {ctms_orders.day(r.get('deliver_by'))}" for r in rows if r["status"] == ctms_orders.OPEN})
        if other:
            return f"CTMS has {', '.join(other)}, not {date}: run its update first or check the date."
        return f"{named} isn't in CTMS for {date} at all: its upload may not have gone in yet."

    def filter_window(self, window):
        """Order Filters (Planning's button) or Advanced Order Filters (the panel's button) up: their boxes read."""
        if ctms_filters.boxes(self.els, window) is not None:
            return self.els
        if window == ctms_filters.PANEL:
            btn = next((e for e in ctms_rows._frame(self.els) or [] if e.get("r") == "push button"
                        and e.get("nm") == "Order Filters" and placed(e)), None)
        else:
            btn = ctms_lines.button(self.els, ctms_filters.PANEL, "Advanced Filters")
        if btn is None:
            raise Stop(f"Planning's {window} couldn't be found to look at.")
        self.run([{"action": "click", "screen": _at(btn), "after": 0.8}, {"action": "settle", "quiet": 0.3, "timeout": 8}])
        if ctms_filters.boxes(self.look(), window) is None:
            raise Stop(f"{window} didn't open.")
        return self.els

    def set_box(self, window, name, want):
        """One filter box to want - a tick clicked, words typed, a drop-down moved by its keys - and read back."""
        box = (ctms_filters.boxes(self.els, window) or {}).get(name)
        if box is None:
            return False
        have = ctms_filters.value(box)
        if have == want:
            return True
        if box.get("r") == "check box":
            self.run([{"action": "click", "screen": _at(box), "after": 0.3}])
        elif box.get("r") == "text":
            self.type_into(box, want or "")
            self.run([_key("tab", 0.2)])
        else:
            rows = None
            for _ in range(2):                         # a click without the focus may only give it the focus
                self.run([{"action": "click", "screen": [box["at"][0] + box["at"][2] - 10, box["at"][1] + box["at"][3] // 2],
                           "after": 0.5}])
                box = (ctms_filters.boxes(self.look(), window) or {}).get(name) or box
                rows = ctms_filters.list_rows(self.els, box) or ctms_filters.frame_rows(self.els, window, box)
                if rows:
                    break
            keys = ctms_filters.moves(rows or [], want or "")
            if keys is None:
                if rows:
                    self.run([_key("escape", 0.3)])
                return False
            self.run([_key(k, 0.04) for k in keys] + [_key("enter", 0.3), {"action": "settle", "quiet": 0.4, "timeout": 10}])
        got = (ctms_filters.boxes(self.look(), window) or {}).get(name)
        return got is not None and ctms_filters.value(got) == want

    def apply_filters(self, window):
        """The window's own button that puts its filters on the well: Advanced's Search, the panel's Refresh."""
        btn = ctms_lines.button(self.els, window, "Search" if window == ctms_filters.ADVANCED else "Refresh")
        if btn is not None:
            self.run([{"action": "click", "screen": _at(btn), "after": 0.6}, {"action": "settle", "quiet": 0.6, "timeout": 20}])
            self.look()

    def close_filters(self):
        """Advanced's Close, then the panel by its own X (where it sits: it doesn't open in one place)."""
        btn = ctms_lines.button(self.els, ctms_filters.ADVANCED, "Close")
        if btn is not None:
            self.run([{"action": "click", "screen": _at(btn), "after": 0.5}])
            self.look()
        head, _ = ctms_filters._frame(self.els, ctms_filters.PANEL)
        if head is not None and placed(head):
            x, y, w, _h = head["at"]
            self.run([{"action": "click", "screen": [x + w - 13, y + 11], "after": 0.5}])
            self.look()

    def clear_filters(self):
        """The filters he has on, kept, then cleared the way a clean well has them, and the well re-queried. True when
        any were on (and are off now); False when none were - a filter isn't what hides the order."""
        self.filter_window(ctms_filters.PANEL)
        self.filter_window(ctms_filters.ADVANCED)
        was = {w: ctms_filters.set_ones(ctms_filters.values(self.els, w)) for w in (ctms_filters.ADVANCED, ctms_filters.PANEL)}
        was = {w: v for w, v in was.items() if v}
        if not was:
            self.close_filters()
            return False
        if self.dry:
            self.said.append("the well's filters would be cleared and put back: " + "; ".join(
                ctms_filters.said(v) for v in was.values()))
            self.close_filters()
            return False
        self.filters_was = was
        stuck = []
        for w in (ctms_filters.ADVANCED, ctms_filters.PANEL):
            for name in was.get(w, {}):
                if w == ctms_filters.PANEL and ctms_filters.boxes(self.els, w) is None:
                    self.filter_window(w)
                if not self.set_box(w, name, ctms_filters.CLEAN.get(name, False if isinstance(was[w][name], bool) else "")):
                    stuck.append(name)
            if w in was:
                self.apply_filters(w)
                if w == ctms_filters.ADVANCED and ctms_filters.boxes(self.els, ctms_filters.PANEL) is None:
                    self.filter_window(ctms_filters.PANEL)
        self.close_filters()
        self.said.append("the well's filters cleared to find it: " + "; ".join(ctms_filters.said(v) for v in was.values()))
        if stuck:
            raise Stop(f"The well's filters wouldn't all clear ({', '.join(stuck)}). Nothing was booked.")
        return True

    def set_filters(self, region=None, strategy=None):
        """His way to an order (02/11, again 09/11: "you know what region it belongs to ... you go to order filters, you put
        on a region, and you go to a strategy if you know what strategy it is. Instead of just like blindly going into the
        order while hoping it's going to be there"): To Plan Reg on the delivery end's region, Business Type on the
        order's strategy when it's known - each only when it isn't on it already - applied, closed. Left as set: the next
        booking sets its own."""
        reg = ctms_filters.plan_reg(region)
        if not reg and not strategy:
            return
        self.look()
        self.filter_window(ctms_filters.PANEL)
        changed, stuck = [], []
        if reg and ctms_filters.values(self.els, ctms_filters.PANEL).get(ctms_filters.REGION) != reg:
            if self.set_box(ctms_filters.PANEL, ctms_filters.REGION, reg):
                changed.append(ctms_filters.PANEL)
            else:
                stuck.append(f"{ctms_filters.REGION} {reg}")
        if strategy:
            self.filter_window(ctms_filters.ADVANCED)
            if ctms_filters.values(self.els, ctms_filters.ADVANCED).get(ctms_filters.STRATEGY) != strategy:
                if self.set_box(ctms_filters.ADVANCED, ctms_filters.STRATEGY, strategy):
                    changed.append(ctms_filters.ADVANCED)
                else:
                    stuck.append(f"{ctms_filters.STRATEGY} {strategy}")
        if ctms_filters.ADVANCED in changed:
            self.apply_filters(ctms_filters.ADVANCED)
        if changed:                        # the panel's Refresh re-queries the well, whichever was changed
            if ctms_filters.boxes(self.els, ctms_filters.PANEL) is None:
                self.filter_window(ctms_filters.PANEL)
            self.apply_filters(ctms_filters.PANEL)
        self.close_filters()
        if stuck:
            raise Stop(f"The well's filters wouldn't go to {', '.join(stuck)}. Nothing was booked.")
        self.said.append(f"the well on {' / '.join(x for x in (reg, strategy) if x)}"
                         + ("" if changed else " already"))

    def restore_filters(self):
        """His filters put back as he had them, each read back. What won't go back is said, for him to put back."""
        if not self.filters_was:
            return
        was, self.filters_was, missed = self.filters_was, {}, []
        try:
            self.look()
            self.filter_window(ctms_filters.PANEL)
            for w in (ctms_filters.ADVANCED, ctms_filters.PANEL):
                if w not in was:
                    continue
                self.filter_window(w)
                for name, v in was[w].items():
                    if not self.set_box(w, name, v):
                        missed.append(f"{name} {v!r}")
                self.apply_filters(w)
            self.close_filters()
        except (Stop, RuntimeError) as e:
            missed.append(f"(stopped: {e})")
        if missed:
            self.said.append("PUT BACK BY HAND on the well's filters: " + ", ".join(missed))
        else:
            self.said.append("the well's filters put back as they were")

    def split(self, ref, parts):
        """One line into equal parts, through Order Summary: its menu's Split Orders, the number, Process, OK, Exit, and
        back to Planning with the well refreshed. CTMS names them _S1, _S2 ... and halves the weight itself."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.4)] + ctms_orders.to_orders(self.t))
        card = self.search_card()
        far = ctms_orders.upto(card, self.now)
        if far:
            self.run(far)
        try:
            self.run(ctms_orders.search_at(card, ref))
        except RuntimeError:
            pass                               # the same line listed already: nothing changes on the screen
        self.look()
        one = [r for r in ctms_orders.lines({"elements": self.els}) or [] if r["ref"] == ref]
        if len(one) != 1 or one[0]["status"] != ctms_orders.OPEN:
            raise Stop(f"Order Summary doesn't show {ref} as one unscheduled line - nothing was split.")
        self.run(ctms_orders.card_close_at(card) + [       # the card closed
                  _click((155, 238), after=0.3), _click((155, 238), right=True, after=0.3),
                  _find(self.t, "os-split", SUMMARY_MENU, 3, click=True, after=0.2),
                  _find(self.t, "split-title", SPLIT_TITLE, 8),
                  _click((580, 533), after=0.2), _key("home"), _key("shift+end"), {"action": "type", "text": str(parts), "after": 0.1},
                  _click((417, 656), after=0.2)])
        q = self.asked(seconds=20)
        if q is None:
            raise Stop(f"Split gave no answer for {ref}: look at it in CTMS.")
        self.run([self.ok_step(q, after=0.8), _click((648, 654), after=1.5), ANCHOR])
        self.look()
        if any(f.startswith("Order details for") for f in frames(self.els)):       # Exit opens a part's card: nothing done on it
            self.run([_click(ORDER_CLOSE, react=True, timeout=15), ANCHOR])
        self.run(ctms_orders.close_summary(self.t) + [ANCHOR])
        self.look()
        self.refresh_well()
        self.said.append(f"{ref} split into {parts}")
        return [f"{ref}_S{i}" for i in range(1, parts + 1)]

    # -- the trip
    def pick_from(self, box, name, what, letter="", up=False):
        """One row of the carrier screen's drop-downs, by its words: opened, jumped by its first letter when it takes one
        (never a whole word: each letter jumps again), read, clicked. The trailer list opens at its end, so looks further
        up; the carrier list, jumped, further down. Its read is the screen's, for whoever needs it next."""
        self.run([_click(box, after=0.5)] + ([{"action": "type", "text": letter, "after": 0.4}] if letter else []))
        for _ in range(LIST_PAGES):
            row = list_row(self.look(), name)
            if row:
                self.run([{"action": "click", "screen": [row["at"][0] + 40, row["at"][1] + row["at"][3] // 2], "after": 0.7}])
                return
            self.run([_click(TRAILER_UP, after=0.1)] * 6 if up else [_key("down", 0.03)] * 7)
        self.run([_key("escape", 0.4)])
        raise Stop(f"{name} isn't on CTMS's {what} list for this order - nothing was booked.")

    def carrier(self, name, trailer):
        """The carrier screen: the trailer, then his carrier's row (picking a trailer moves off it) - or the Alternative
        Carrier list when his carrier isn't one of the lane's rows. Select Carrier."""
        self.run([ANCHOR])
        if trailer:
            self.pick_from(TRAILER_BOX, trailer, "trailer", up=True)
        else:
            self.look()
        cell = carrier_cell(self.els, name)
        if cell is not None:
            self.run([{"action": "click", "screen": _at(cell), "after": 0.3}])
        else:
            self.pick_from(ALT_CARRIER_BOX, name, "carrier", letter=name[:1])
        self.run([_click(SELECT_CARRIER, after=0.1), _find(self.t, "cp-title", PAYMENT_TITLE, 8)])
        self.veh_kept = trailer

    def create(self, row, carrier, trailer, haulage, keep=False):
        """Create New Trip for this row, up to the manifest. Returns {"manifest", "carrier", "revenue", "cost"} - on a
        dry run the box's figures, the last box answered No."""
        before = manifests(self.els if self.has_tree else self.look(tree=True))
        self.row_menu(row, "wm-create-trip", keep=keep)
        self.run([_find(self.t, "sc-title", CARRIER_TITLE, 10)])
        self.carrier(carrier, trailer)
        self.stage("the carrier")
        steps = []
        if haulage is not None:          # the cursor sits in Haulage Amount, its 0.00 selected
            steps = [{"action": "type", "text": f"{float(haulage):g}", "after": 0.1}, _key("tab", 0.3)]
        self.run(steps + [_click(CREATE_TRIP, after=0.1)])
        asked = self.asked("Confirm Create Trip")
        box = confirm_box(self.els)
        if box is None:
            raise Stop("CTMS's Confirm Create Trip box could not be read, so nothing was booked. On the screen: "
                       + " | ".join(frames(self.els))[:240])
        if box["carrier"].upper() != carrier.upper():
            raise Stop(f"CTMS's box says the carrier is {box['carrier']}, not {carrier} - nothing was booked.")
        if float(box["cost"]) <= 0 and carrier.upper() != NOC:
            raise Stop(f"CTMS has a cost of {box['cost']} for {carrier}: no matrix price, so nothing was booked. "
                       "Press Book again with the price.")
        if haulage is not None and float(box["cost"]) + 0.005 < float(haulage):
            raise Stop(f"CTMS's box says the cost is {box['cost']}, under the {float(haulage):g} typed - nothing was booked.")
        self.stage("the price")
        if self.dry:
            self.back_out()
            return box
        yes = asked[1].get("yes")
        if yes is None or not placed(yes):
            self.back_out()
            raise Stop("CTMS's Confirm Create Trip box had no Yes to press, so nothing was booked.")
        self.run([{"action": "click", "screen": _at(yes), "react": True, "timeout": 20, "quiet": 0.4},
                  _click(PLANNING_SAVE, after=0.8)])
        for _ in range(4):
            man = new_manifest(self.look(tree=True), before)
            if man:
                return dict(box, manifest=man)
        raise Stop("The trip was confirmed and saved, but no new manifest showed on the tree - look at Planning. "
                   "Pressing Book again would not make another: the line has gone from the well.")

    def planned(self):
        """The lines Planned Orders shows on the manifest just made."""
        self.run([_click(ORDERS_BUTTON, after=0.9)])
        self.look()
        there = planned_refs(self.els)
        panel = next((e for e in self.els if e.get("r") == "internal frame" and str(e.get("nm") or "").startswith("Planned Orders")
                      and placed(e)), None)
        if panel is None:
            raise Stop("Planned Orders didn't open on the manifest, so it's still PLANNED: look at it before anything else.")
        x, y, w, _ = panel["at"]
        self.run([{"action": "click", "screen": [x + w - PLANNED_X, y + PLANNED_Y], "after": 0.4}])
        self.look(tree=True)                       # what Accepted works from next
        if any(f.startswith(("Planned Orders", "Order details for")) for f in frames(self.els)):
            raise Stop("Planned Orders wouldn't close, so the manifest is still PLANNED: look at it before anything else.")
        return there

    def check_order(self, manifest, refs):
        """Planned Orders: the manifest's lines are the ones meant."""
        there = self.planned()
        for ref in refs:
            if ref not in there:
                raise Stop(f"{manifest} doesn't show {ref} in Planned Orders, so it's still PLANNED: look at it before anything else.")

    def accept(self, manifest):
        """Set Status > Accepted, its OK, Save, read back. The manifest has to be on the screen: it is the one just made."""
        got = manifests(self.els if self.has_tree else self.look(tree=True)).get(manifest)
        box = tree_box(self.els)
        if not got or not placed(got) or (box and not box[1] <= got["at"][1] <= box[1] + box[3] - got["at"][3]):
            raise Stop(f"{manifest} is made, but isn't on the screen in the tree to accept: it's still PLANNED.")
        pt = _at(got)
        self.run([{"action": "click", "screen": pt, "after": 0.5}, {"action": "click", "screen": pt, "right": True, "after": 0.3},
                  _find(self.t, "mt-set-status", TREE_MENU, 3, click=True, after=0.3),
                  _find(self.t, "st-accepted", STATUS_MENU, 3, click=True, after=0.2)])
        q = self.asked(seconds=5)
        if q is None:
            raise Stop(f"{manifest}: Set Status asked nothing, so it's still PLANNED: look at it before anything else.")
        self.run([self.ok_step(q, react=True, timeout=10), _click(PLANNING_SAVE, after=0.8)])
        for _ in range(4):
            if (manifests(self.look(tree=True)).get(manifest) or {}).get("status") == "ACCEPTED":
                return
        raise Stop(f"{manifest} did not read back as ACCEPTED: look at it in Planning.")

    def trip(self, refs, carrier, trailer, haulage):
        """One vehicle: its first line's new trip, the others applied to it, the check, Accepted."""
        self.carrier_window_away()         # the last vehicle's, if it's in front
        row, picked = self.select_lines(refs)
        when = {"collect": row.get("collect", ""), "deliver": row.get("deliver", "")}
        got = self.create(row, carrier, trailer, haulage, keep=len(picked) > 1)
        if self.dry:
            self.trips.append(dict(got, lines=list(refs), status="rehearsed", picked=len(picked), **when))
            return
        done = dict(got, lines=refs[:1], status="PLANNED", picked=len(picked), **when)
        self.trips.append(done)
        if len(refs) > 1:
            there = self.planned()
            strays = sorted(there - set(refs))
            if strays:
                raise Stop(f"{got['manifest']} has {', '.join(strays)} on it as well as what was meant, so it's still PLANNED: "
                           "look at it before anything else.")
            done["lines"] = [r for r in refs if r in there] or refs[:1]
            done["took"] = len(done["lines"])
            left = [r for r in refs if r not in done["lines"]]
            if left:
                self.refresh_well()        # the well isn't live: what the trip took has to go from it first
            for ref in left:
                self.row_menu(self.on_screen(ref), "wm-apply-trip")
                self.run([{"action": "settle", "quiet": 0.4, "timeout": 15}, _click(PLANNING_SAVE, after=0.8)])
                self.look()
                done["lines"].append(ref)
        self.stage("the trip")
        self.check_order(got["manifest"], refs)
        self.accept(got["manifest"])
        done["status"] = "ACCEPTED"
        self.stage("accepted")
        try:                               # the booking's carrier window goes too, if it's in front
            self.look()
            self.carrier_window_away()
        except (Stop, RuntimeError) as e:
            self.said.append(str(e))

    def book(self, orders, date, carrier, trailer, haulage, vehicles, qty=None, region=None, strategy=None):
        """The whole booking. self.trips says what was made, however it ended."""
        self.start()
        self.set_filters(region, strategy)
        self.set_day(sched_for_day(date))
        self.stage("the date")
        lines = self.lines(orders, date)
        if not lines:
            ahead = (datetime.strptime(date, "%d/%m/%Y") + timedelta(days=1)).strftime("%y%m%d")
            self.set_day(ahead)            # a night delivery sits on the next day's schedule, past the well's To
            lines = self.lines(orders, date)
        named = " / ".join(orders)
        if not lines:
            if self.to_was:                # a later date than the day asked for sits past that To
                self.move_to(self.to_was)
                self.look()
            other = sorted({f"{r['cust_ref']} on {ctms_orders.day(r.get('deliver'))}" for r in self.scan(orders, "")})
            if other:
                raise Stop(f"CTMS has {', '.join(other)}, not {date}: run its update first or check the date. "
                           "Nothing was booked.")
            why = self.why_missing(orders, date)          # Order Summary asked, not guessed (03/11)
            if why == "hidden" and self.clear_filters():
                self.set_day(sched_for_day(date))
                lines = self.lines(orders, date)
            if not lines:
                raise Stop((f"{named} is in CTMS, unscheduled for {date}, but the order well won't show it even with its "
                            "filters as a clean well has them - look at the well's layout." if why == "hidden" else why)
                           + " Nothing was booked.")
        want = sched_for_delivery(lines[0].get("deliver"))
        if want and want != sched_of(self.els):
            self.set_day(want)
        if vehicles > 1 and len(lines) > 1 and len(lines) != vehicles:
            raise Stop(f"{named} has {len(lines)} lines to share over {vehicles} vehicles: the button can't split that yet. "
                       "Nothing was booked.")
        self.stage("the order")
        refs = [r["cust_ref"] for r in lines]
        wants = line_wants(refs, orders, qty or {})
        if sum([self.prepare_line(ref, wants.get(ref)) for ref in refs]):
            self.stage("the lines put right")
        else:
            self.stage("the lines checked")
        if vehicles > 1 and len(lines) == 1:
            if self.dry:
                self.said.append(f"{refs[0]} would be split into {vehicles}: rehearsing one of them")
                self.trip(refs, carrier, trailer, haulage)
                return self.trips
            refs = self.split(refs[0], vehicles)
            self.stage("the split")
        if vehicles > 1:
            for ref in refs:
                self.trip([ref], carrier, trailer, haulage)
                self.look()
        else:
            self.trip(refs, carrier, trailer, haulage)
        return self.trips
