"""
The order panel's Book button, run here on the work PC in one go (his 02/11: "It takes me around 40 seconds to 1 minute
to book in something like that. That needs to be the target for you ... you've got to be faster than I am").

No picture is read between the steps: CTMS's own words on its menus and box titles are found by exact pixels
(ctms_book_templates.json) and what only the screen knows - which row is the order, which manifest is new - is read
through the Access Bridge. In order, the way he books:

  1. the manifest tree's Sched on the delivery day - the well's To follows it
  2. the order's unscheduled lines for that day found in the well: as it stands, then with the Deliver column pressed
     (his tip: latest first, so the day's orders are on top), then with the well's own Refresh
  3. the delivery type put up when the real date makes it more urgent than the order says - "the delivery type has to
     be set before you create the trip"
  4. one line going on several vehicles: split equally through Order Summary, which brings the weight down with it
     (his rule: "whatever weight it had when it initially came into CTMS is the original weight you're supposed to be
     splitting it down to" - nothing is typed into a weight here)
  5. each vehicle's trip: Create New Trip on its first line, the carrier, the trailer, the haulage (typed only when he
     gave one: tier 1 comes off the matrix, DHL NOC stays 0), Create Trip, Yes once the box names the right carrier and
     a real cost; the vehicle's other lines by Apply to Trip; Save
  6. the order checked on the manifest in Planned Orders, set Accepted, Save, read back

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

import ctms_orders
import ctms_rows

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_book_templates.json")

CARRIER_FRAME = "Select a Carrier"
ROW_MENU = (430, 25, 810, 880)     # a well row's menu: beside the row, as far up as it has to go
TREE_MENU = (190, 25, 430, 880)    # a manifest's menu, likewise
STATUS_MENU = (400, 25, 520, 880)  # its Set Status list
SUMMARY_MENU = (150, 200, 345, 760)  # an Order Summary line's menu
ALERT = (700, 380, 1200, 480)      # where a Forms question shows
WINDOW_LIST = (355, 130, 560, 260)  # the Window menu's list of windows
CARRIER_TITLE = (430, 40, 700, 90)
PAYMENT_TITLE = (500, 370, 800, 420)
CONFIRM_TITLE = (780, 330, 1000, 380)
SPLIT_TITLE = (350, 370, 600, 420)

MENU_BAR = (1000, 37)              # an empty bit of it: gives Java the focus, closes a menu left open
WINDOW_MENU = (386, 37)
SCHED_ARROW = (162, 133)
TRAILER_BOX = (1228, 319)
TRAILER_UP = (1347, 165)           # the open trailer list's up arrow - a row a click
ALT_CARRIER_BOX = (971, 400)
SELECT_CARRIER, CARRIER_EXIT = (912, 363), (1042, 363)
CREATE_TRIP, PAYMENT_CANCEL = (1015, 449), (1015, 479)
CONFIRM_YES, CONFIRM_NO = (984, 529), (1039, 529)
PLANNING_SAVE = (1337, 98)
FORMS_OK = (1035, 505)
ORDERS_BUTTON, PLANNED_CLOSE = (1360, 166), (1493, 447)
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
        self.trips = []
        self.veh_kept = ""         # what CTMS now keeps as the Veh Type of the line taken to the carrier screen
        self.said = []
        self.stages = []
        self._t = time.time()

    def stage(self, name):
        """How long that part took, for the seconds he is shown."""
        now = time.time()
        self.stages.append([name, round(now - self._t, 1)])
        self._t = now

    def look(self):
        self.els = self.read()
        return self.els

    # -- getting about
    def start(self):
        """CTMS with Planning up and nothing open over it - an order left open with changes stops the run, untouched."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.4), ANCHOR])
        self.look()
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
            self.look()
            asked = next((f for f in frames(self.els) if "discard your changes" in f), None)
            if asked:
                cancel = next((e for e in ctms_rows._frame(self.els, asked) or [] if e.get("r") == "push button"
                               and str(e.get("nm") or "").startswith("Cancel")), None)
                if cancel is not None:
                    self.run([{"action": "click", "screen": _at(cancel), "after": 0.5}])
                raise Stop("An order is open in CTMS with changes not saved. Nothing was touched: save or close it and "
                           "press Book again.")
        if any(f.startswith("Order Summary") for f in frames(self.els)):       # the to-do's Run leaves it up, and its card
            if self.seen("os-card", ctms_orders.CARD_BOX):
                self.run([_click((509, 226), after=0.5)])
            self.run(ctms_orders.close_summary(self.t))
            self.look()
        self.carrier_window_away()

    def carrier_window_away(self):
        """A carrier window left behind Planning by the last Create Trip: brought forward by the Window menu and closed by
        its own Exit, which changes nothing."""
        if not any(f.startswith(CARRIER_FRAME) for f in frames(self.els)):
            return
        if not self.seen("sc-title", CARRIER_TITLE):
            self.run([{"action": "anchor"}, _click(WINDOW_MENU, after=0.4),
                      _find(self.t, "wn-carrier", WINDOW_LIST, 2, click=True, after=0.4), ANCHOR,
                      _find(self.t, "sc-title", CARRIER_TITLE, 5)])
        self.run([_click(CARRIER_EXIT, after=0.8)])
        self.look()

    def set_sched(self, want):
        """The tree on that schedule: its list runs newest first, a day a row, so Up once per day ahead, Enter, read
        back (his walkthrough 29/10; a click on an open list's row can pick nothing). The well's To moves with it."""
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
            top = rows[0]["cust_ref"]
            self.page_down(rows)
            rows = self.well()
            if not rows or rows[0]["cust_ref"] == top:
                break
        return [got[k] for k in sorted(got)]

    def latest_first(self):
        """His way to an order in the well: "put the schedule to date on the delivery date, and then you press the deliver
        column, it reverses the sort order" - the latest first, so with To on its day the order is on top."""
        days = [datetime.strptime(r["deliver"][:8], "%d/%m/%y") for r in self.well()
                if re.match(r"\d{2}/\d{2}/\d{2}", str(r.get("deliver") or ""))]
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
            raise Stop("Planning's order well is empty as it is filtered - check its filters.")
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

    def row_menu(self, row, template):
        """The row made current - shown by its colour, as a right-click works on the current record - then its menu's
        item (the menu's place moves with the row)."""
        pt = ctms_rows.point(row)
        x, y = row["cell"][:2]
        self.run([{"action": "click", "screen": pt, "after": 0.2},
                  {"action": "waitfor", "screen": [x + ctms_rows.OFFSETS["to_reg"] + 30, y + 2], "color": CURRENT_ROW, "timeout": 5},
                  {"action": "click", "screen": pt, "right": True, "after": 0.3},
                  _find(self.t, template, ROW_MENU, 3, click=True, after=0.2)])

    def back_out(self):
        """Any box of the trip still up closed without booking, each looked for first: a click that finds its box gone lands
        on Planning behind it (the Confirm's No shuts the payment box too). A menu left open goes with the first click;
        on a box that wants an answer that click does nothing."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.3), ANCHOR])
        if self.seen("cc-title", CONFIRM_TITLE):
            self.run([_click(CONFIRM_NO, after=0.8)])
        if self.seen("cp-title", PAYMENT_TITLE):
            self.run([_click(PAYMENT_CANCEL, after=0.8)])
        if self.seen("sc-title", CARRIER_TITLE):
            self.run([_click(CARRIER_EXIT, after=0.8)])

    def tidy(self):
        """As he left it: the Deliver column back, no carrier window behind Planning."""
        self.run([ANCHOR])
        self.look()
        self.carrier_window_away()
        if self.flipped:
            self.press_deliver()

    # -- what goes on the order first
    def raise_type(self, ref):
        """The delivery type, when the date makes it more urgent: the line opened from the well - its own card proved by
        name before anything goes in, the well being able to move under a stored place - set, saved, closed."""
        row = self.on_screen(ref)
        typ = wanted_type(row.get("del_type"), row.get("deliver"), self.now)
        if not typ:
            return False
        self.run([{"action": "click", "screen": ctms_rows.point(row), "double": True, "react": True,
                   "box": [20, 121, 1250, 171], "timeout": 20},
                  ANCHOR, _find(self.t, "od-vehtype", (940, 250, 1100, 380), 5)])
        got = card_ref(self.look())
        if got.upper() != ref.upper():
            self.run([_click(ORDER_CLOSE, react=True, timeout=15), ANCHOR])
            raise Stop(f"The well opened {got or 'no order'} for {ref}: closed it again, unchanged. Nothing was booked.")
        self.run([_click((288, 187), react=True, box=[20, 200, 1250, 700], timeout=10),   # Add Detail
                  _click((273, 252), react=True, timeout=10),                              # Delivery Type's list
                  _click((960, 299), after=0.2), _key("home"), _key("shift+end"),
                  {"action": "type", "text": typ + "%", "after": 0.1},
                  _click((887, 721), react=True, timeout=10),                              # its Find
                  _click((978, 721), react=True, timeout=10),                              # its OK
                  _click(ORDER_SAVE, react=True, quiet=1, timeout=15),
                  _click(ORDER_CLOSE, react=True, timeout=15), ANCHOR])
        self.look()
        self.said.append(f"{ref} put up to {typ}")
        return True

    def split(self, ref, parts):
        """One line into equal parts, through Order Summary: its menu's Split Orders, the number, Process, OK, Exit, and
        back to Planning with the well refreshed. CTMS names them _S1, _S2 ... and halves the weight itself."""
        self.run([{"action": "anchor"}, _click(MENU_BAR, after=0.4)] + ctms_orders.to_orders(self.t) + ctms_orders.card(self.t))
        try:
            self.run(ctms_orders.search(ref))
        except RuntimeError:
            pass                               # the same line listed already: nothing changes on the screen
        self.look()
        one = [r for r in ctms_orders.lines({"elements": self.els}) or [] if r["ref"] == ref]
        if len(one) != 1 or one[0]["status"] != ctms_orders.OPEN:
            raise Stop(f"Order Summary doesn't show {ref} as one unscheduled line - nothing was split.")
        self.run([_click((509, 226), after=0.5),            # the card closed
                  _click((155, 238), after=0.3), _click((155, 238), right=True, after=0.3),
                  _find(self.t, "os-split", SUMMARY_MENU, 3, click=True, after=0.2),
                  _find(self.t, "split-title", SPLIT_TITLE, 8),
                  _click((580, 533), after=0.2), _key("home"), _key("shift+end"), {"action": "type", "text": str(parts), "after": 0.1},
                  _click((417, 656), after=0.2), _find(self.t, "split-ok", ALERT, 20),
                  _click(FORMS_OK, after=0.8), _click((648, 654), after=1.5), ANCHOR])
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

    def create(self, row, carrier, trailer, haulage):
        """Create New Trip for this row, up to the manifest. Returns {"manifest", "carrier", "revenue", "cost"} - on a
        dry run the box's figures, the last box answered No."""
        before = manifests(self.els)
        self.row_menu(row, "wm-create-trip")
        self.run([_find(self.t, "sc-title", CARRIER_TITLE, 10)])
        self.carrier(carrier, trailer)
        self.stage("the carrier")
        steps = []
        if haulage is not None:          # the cursor sits in Haulage Amount, its 0.00 selected
            steps = [{"action": "type", "text": f"{float(haulage):g}", "after": 0.1}, _key("tab", 0.3)]
        self.run(steps + [_click(CREATE_TRIP, after=0.1), _find(self.t, "cc-title", CONFIRM_TITLE, 8)])
        self.look()
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
        self.run([_click(CONFIRM_YES, react=True, timeout=20, quiet=0.4), _click(PLANNING_SAVE, after=0.8)])
        for _ in range(4):
            man = new_manifest(self.look(), before)
            if man:
                return dict(box, manifest=man)
        raise Stop("The trip was confirmed and saved, but no new manifest showed on the tree - look at Planning. "
                   "Pressing Book again would not make another: the line has gone from the well.")

    def check_order(self, manifest, ref):
        """Planned Orders: the manifest's order is the one meant."""
        self.run([_click(ORDERS_BUTTON, after=0.9)])
        self.look()
        self.run([_click(PLANNED_CLOSE, after=0.4)])
        if ref not in planned_refs(self.els):
            raise Stop(f"{manifest} doesn't show {ref} in Planned Orders, so it's still PLANNED: look at it before anything else.")

    def accept(self, manifest):
        """Set Status > Accepted, its OK, Save, read back. The manifest has to be on the screen: it is the one just made."""
        got = manifests(self.els).get(manifest)
        box = tree_box(self.els)
        if not got or not placed(got) or (box and not box[1] <= got["at"][1] <= box[1] + box[3] - got["at"][3]):
            raise Stop(f"{manifest} is made, but isn't on the screen in the tree to accept: it's still PLANNED.")
        pt = _at(got)
        self.run([{"action": "click", "screen": pt, "after": 0.5}, {"action": "click", "screen": pt, "right": True, "after": 0.3},
                  _find(self.t, "mt-set-status", TREE_MENU, 3, click=True, after=0.3),
                  _find(self.t, "st-accepted", STATUS_MENU, 3, click=True, after=0.2),
                  _find(self.t, "al-accepted", ALERT, 5), _click(FORMS_OK, react=True, timeout=10),
                  _click(PLANNING_SAVE, after=0.8)])
        for _ in range(4):
            if (manifests(self.look()).get(manifest) or {}).get("status") == "ACCEPTED":
                return
        raise Stop(f"{manifest} did not read back as ACCEPTED: look at it in Planning.")

    def trip(self, refs, carrier, trailer, haulage):
        """One vehicle: its first line's new trip, the others applied to it, the check, Accepted."""
        self.carrier_window_away()         # the last vehicle's
        row = self.on_screen(refs[0])
        when = {"collect": row.get("collect", ""), "deliver": row.get("deliver", "")}
        got = self.create(row, carrier, trailer, haulage)
        if self.dry:
            self.trips.append(dict(got, lines=list(refs), status="rehearsed", **when))
            return
        done = dict(got, lines=refs[:1], status="PLANNED", **when)
        self.trips.append(done)
        for ref in refs[1:]:
            self.row_menu(self.on_screen(ref), "wm-apply-trip")
            self.run([{"action": "settle", "quiet": 0.4, "timeout": 15}, _click(PLANNING_SAVE, after=0.8)])
            self.look()
            done["lines"].append(ref)
        self.stage("the trip")
        self.check_order(got["manifest"], refs[0])
        self.accept(got["manifest"])
        done["status"] = "ACCEPTED"
        self.stage("accepted")

    def book(self, orders, date, carrier, trailer, haulage, vehicles):
        """The whole booking. self.trips says what was made, however it ended."""
        self.start()
        self.set_sched(sched_for_day(date))
        self.stage("the date")
        lines = self.lines(orders, date)
        if not lines:
            ahead = (datetime.strptime(date, "%d/%m/%Y") + timedelta(days=1)).strftime("%y%m%d")
            self.set_sched(ahead)          # a night delivery sits on the next day's schedule, past the well's To
            lines = self.lines(orders, date)
        named = " / ".join(orders)
        if not lines:
            other = sorted({f"{r['cust_ref']} on {ctms_orders.day(r.get('deliver'))}" for r in lines_of(self.well(), orders)})
            raise Stop((f"CTMS has {', '.join(other)}, not {date}: run its update first or check the date." if other else
                        f"{named} isn't in the order well for {date}. It may be booked already, not in CTMS yet, or kept out "
                        "by the well's filters (Business Type, To Plan Reg).") + " Nothing was booked.")
        want = sched_for_delivery(lines[0].get("deliver"))
        if want and want != sched_of(self.els):
            self.set_sched(want)
        if vehicles > 1 and len(lines) > 1 and len(lines) != vehicles:
            raise Stop(f"{named} has {len(lines)} lines to share over {vehicles} vehicles: the button can't split that yet. "
                       "Nothing was booked.")
        self.stage("the order")
        refs = [r["cust_ref"] for r in lines]
        if sum([self.raise_type(ref) for ref in refs]):
            self.stage("the delivery type")
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
