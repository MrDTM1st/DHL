"""
What CTMS says about the orders on the map - booked or not, their dates, the Veh Type (01/11).

His ask: booked orders come off the map, the dates follow CTMS, and an order whose details came in by phone shows
ready - "sometimes I might get all the information over the phone, so reading from CTMS is good". Emails catch the
rest. So the bridge looks each one up the way he would (ctms_bridge's ctms_check):

  1. C-TMS Modules > Order Management > Orders, and Order Summary's Search card - the order-update recipe's route
  2. each order by its customer ref with a % - every line of it comes back - then Refresh
  3. the lines read through Java's Access Bridge: Schedule, Cust Ref, Status, Ready At, Deliver By. His rule (29/10):
     a scheduled line is booked in and dealt with
  4. an order still being chased: its line opened by itself - an UNSCHEDULED line only, a scheduled one asks "are you
     sure you want to modify it?" - just to see whether its Veh Type is filled (his rule 30/10: a vehicle type on the
     order means the site's details are in), then closed, unchanged
  5. Order Summary closed again, so Planning shows as it was

Nothing is typed into an order and nothing is saved. Points are the order-update recipe's, on the work PC's pictures
of 29-31/10 (the window 1910 x 915); the templates were cut from those pictures - CTMS's own words only.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_check_templates.json")
# Order Summary's columns, by the Forms item each one is - its Access Bridge name is "Enter value for : <ITEM>"
COLUMNS = {"SCHED_NAME": "schedule", "EXTERNAL_REF": "ref", "STATUS": "status", "DELIVERY_TYPE_ID": "type",
           "EARLY_AVAIL": "ready_at", "LATE_DEL": "deliver_by"}
OPEN = "UNSCHEDULED"               # the one status still to book: SCHEDULED is booked in, CANCELLED / ABORTED gone
CARD_BOX = (430, 50, 830, 270)     # where the Order Search card shows
SEARCH_BOX = (300, 600, 500, 680)  # Order Summary's Search button, on its bottom bar
VEH_BOX = (1061, 303, 1200, 318)   # an order's Veh Type box inside its border (its label at 983,303)
VEH_DARK = 40                      # dark pixels in it that mean words: empty shows none, filled 150 up (29-31/10)


def templates():
    with open(TEMPLATES, encoding="utf-8") as f:
        return json.load(f)


def _find(t, name, box, timeout, **extra):
    tp = t[name]
    return dict({"action": "find", "name": name, "box": list(box), "tpl": tp["rgb"], "tw": tp["w"], "th": tp["h"],
                 "timeout": timeout}, **extra)


def _click(x, y, **extra):
    return dict({"action": "click", "px": [x, y]}, **extra)


def search_ref(order):
    """What goes in the card's Customer Ref: an NR order by its 7-digit base and a %, so every line comes back (the
    order-update recipe's rule); any other ref - an ad hoc's - whole, with the %."""
    order = str(order).strip()
    m = re.fullmatch(r"(\d{7})(?:-\d+)*", order)
    return (m.group(1) if m else order) + "%"


# A DTS or supplier job's NN number (NN4230978-2256, NN5139446-284, N5139446-276): CTMS keeps it as the Booking Ref,
# and the lines' Customer Ref can be something else altogether (HT Rail's SU/5112026RMCV9), so a Customer Ref search
# for it can find nothing (his 03/11: "you put that in the customer reference, not the booking reference")
BOOKING_REF = re.compile(r"N{1,2}\d{6,8}-\d+(?:/\d+)?", re.I)


def by_booking_ref(order):
    """The order is one CTMS may know only by its Booking Ref."""
    return bool(BOOKING_REF.fullmatch(str(order or "").strip()))


def belongs(line_ref, order):
    """A line CTMS listed is one of this order's - the % could bring back a longer ref sharing its front."""
    base, ref = search_ref(order)[:-1], str(line_ref or "").strip()
    if base.isdigit():
        return ref == base or ref.startswith(base + "-")
    return ref.startswith(base)


def to_orders(t):
    """C-TMS Modules > Order Management > Orders, then Order Summary's Search button for its card. With Order
    Summary up already the menu does nothing, and the button is pressed all the same."""
    return [_click(121, 36, react=True, box=[60, 45, 300, 150], quiet=0.2, timeout=5),     # C-TMS Modules
            _click(135, 63, react=True, box=[280, 50, 460, 170], quiet=0.2, timeout=5),    # Order Management
            _click(245, 67, after=0.3),                                                      # Orders
            {"action": "anchor", "window": True},         # CTMS's own area can scroll its windows (30/10)
            _find(t, "os-search", SEARCH_BOX, 25, click=True, react=True)]


def card(t):
    """The Order Search card is up - known by its labels."""
    return [{"action": "anchor", "window": True}, _find(t, "os-card", CARD_BOX, 12)]


UPTO_DAYS = 120                    # how far ahead "up to" is put: the wait list holds orders a fortnight out and more


def upto(fields, now=None, days=UPTO_DAYS):
    """Order Summary's "up to", put far enough ahead that a later order is listed at all (03/11: it sat on tomorrow,
    so the 10/11 wheelsets and a 13/11 order came back as nothing whatever the ref). The box is found by its name and
    clicked where the Access Bridge places it - never a stored point that could land in another box. [] when it is
    already far enough ahead, or isn't on the screen (the search goes on as it always did)."""
    from datetime import datetime, timedelta
    els = (fields or {}).get("elements") if isinstance(fields, dict) else fields
    box = next((e for e in els or [] if e.get("r") == "text" and str(e.get("nm") or "").strip() == "up to"
                and len(e.get("at") or []) == 4 and e["at"][2] > 0 and e["at"][3] > 0), None)
    if box is None:
        return []
    now = now or datetime.now()
    want = now + timedelta(days=days)
    try:
        if datetime.strptime(str(box.get("v") or "").strip(), "%d/%m/%y") >= now + timedelta(days=days // 2):
            return []
    except ValueError:
        pass
    x, y, w, h = box["at"]
    return [{"action": "click", "screen": [x + w // 2, y + h // 2], "after": 0.15},
            {"action": "key", "key": "home", "after": 0.05}, {"action": "key", "key": "shift+end", "after": 0.05},
            {"action": "type", "text": want.strftime("%d/%m/%y"), "after": 0.1}]


def search(ref, booking=False):
    """One search: Clear (the last one's lines go), the ref typed over whatever the box holds, Refresh - waited on
    until the list's first line changes. Nothing found leaves it empty: that wait then runs out. booking: the ref goes
    in the card's Booking Ref box, the one under Customer Ref, instead."""
    return [_click(626, 226, after=0.4),
            _click(728, 147 if booking else 122, after=0.15), {"action": "key", "key": "home", "after": 0.05},
            {"action": "key", "key": "shift+end", "after": 0.05}, {"action": "type", "text": ref, "after": 0.1},
            _click(742, 226, react=True, box=[30, 228, 395, 250], timeout=15)]


# -- the Order Search card where the Access Bridge places it (10/11/2026)
# CTMS as its own app draws the card shorter than Edge did (its Clear and Refresh about 24 px higher) and not always
# where Edge had it (sometimes on the right of the window), so search()'s stored points clicked beside the buttons and
# every search "found nothing": the to-do's Run, Book's split and the map's look-up alike. The card's parts are found
# by their names and clicked where the Access Bridge places them; the stored points stay as the fallback for a read
# that hasn't got the card in it.
CARD_TITLE = "Order Search"
FIRST_ROW_BOX = [30, 228, 395, 250]   # Order Summary's first line, as the recipes were measured: what a Refresh changes


def _els(fields):
    return ((fields or {}).get("elements") if isinstance(fields, dict) else fields) or []


def _frame_els(fields, title):
    """The elements inside the window whose title starts with `title`; None when that window isn't there."""
    els = _els(fields)
    i0 = next((i for i, e in enumerate(els) if e.get("r") == "internal frame"
               and str(e.get("nm") or "").startswith(title)), None)
    if i0 is None:
        return None
    lv0, out = els[i0].get("lv", 0), []
    for e in els[i0 + 1:]:
        if e.get("lv", 0) <= lv0:
            break
        out.append(e)
    return out


def _placed(e):
    at = (e or {}).get("at") or []
    return len(at) == 4 and at[2] > 0 and at[3] > 0


def _mid(e):
    x, y, w, h = e["at"]
    return [x + w // 2, y + h // 2]


def card_parts(fields):
    """The Search card's boxes and buttons the Access Bridge places on the screen: {customer, booking, close, clear,
    refresh}, each only when it is there (the app names its boxes "Enter a Customer Ref to search for" and so on).
    None when the card's window isn't there at all."""
    part = _frame_els(fields, CARD_TITLE)
    if part is None:
        return None
    got = {}
    for e in part:
        nm, r = str(e.get("nm") or ""), e.get("r")
        key = ("customer" if r == "text" and "Customer Ref" in nm else
               "booking" if r == "text" and "Booking Ref" in nm else
               nm.lower() if r == "push button" and nm in ("Close", "Clear", "Refresh") else None)
        if key and key not in got and _placed(e):
            got[key] = e
    return got


def card_up(fields):
    """The Search card is on the screen, wherever it sits: its window there with something of it placed."""
    return bool(card_parts(fields))


def search_at(fields, ref, booking=False):
    """search(), each click where the Access Bridge places the card's parts in `fields` (a read taken with the card
    up). Without them (an older read, a card it couldn't read) search() itself. No anchor here: with the card up the
    window offset could read the card's title bar - the batch's anchor, taken before, places the watched box."""
    p = card_parts(fields) or {}
    box = p.get("booking" if booking else "customer")
    if not (box and p.get("clear") and p.get("refresh")):
        return search(ref, booking=booking)
    return [{"action": "click", "screen": _mid(p["clear"]), "after": 0.4},
            {"action": "click", "screen": _mid(box), "after": 0.15}, {"action": "key", "key": "home", "after": 0.05},
            {"action": "key", "key": "shift+end", "after": 0.05}, {"action": "type", "text": ref, "after": 0.1},
            {"action": "click", "screen": _mid(p["refresh"]), "react": True, "box": list(FIRST_ROW_BOX), "timeout": 15}]


def card_close_at(fields):
    """The Search card's Close where the Access Bridge places it; the stored point when the read hasn't got it."""
    p = card_parts(fields) or {}
    if p.get("close"):
        return [{"action": "click", "screen": _mid(p["close"]), "after": 0.5}]
    return [_click(509, 226, after=0.5)]


def first_status(fields):
    """Order Summary's first line's Status cell where the Access Bridge places it; None when none is read."""
    part = _frame_els(fields, "Order Summary") or []
    cells = [e for e in part if e.get("r") == "text" and _placed(e)
             and re.fullmatch(r"Enter value for : STATUS(?:\s+Required)?", str(e.get("nm") or ""))]
    return min(cells, key=lambda e: e["at"][1]) if cells else None


def open_line_at(fields, t):
    """open_line(), the card's Close and the line's Status cell where the Access Bridge places them in `fields` (a read
    taken after the search). Without the cell, open_line()'s stored point for it (after the card's own Close, if read)."""
    cell = first_status(fields)
    if cell is None:
        return card_close_at(fields) + open_line(t)[1:]       # open_line's first step is the card's stored Close
    return card_close_at(fields) + [
        {"action": "click", "screen": _mid(cell), "double": True, "react": True, "box": [20, 121, 1250, 171],
         "timeout": 20},
        {"action": "anchor", "window": True},
        _find(t, "od-vehtype", (940, 250, 1100, 380), 5)]


def open_line(t):
    """The one line the last search found, opened: the card closed first (left open it sits over the order), the
    line's Status cell double-clicked, the order's own card waited for - its Veh Type label seen there."""
    return [_click(509, 226, after=0.5),
            _click(267, 238, double=True, react=True, box=[20, 121, 1250, 171], timeout=20),
            {"action": "anchor", "window": True},
            _find(t, "od-vehtype", (940, 250, 1100, 380), 5)]


def close_line(t, then_card=True):
    """The order's Close - nothing was changed, so nothing is asked - then Order Summary's Search card again.
    then_card=False: the card's labels aren't waited for here - the app can open the card elsewhere (10/11), so the
    caller looks for it through the Access Bridge as well."""
    return [_click(424, 733, react=True, timeout=15),
            {"action": "anchor", "window": True},
            _find(t, "os-search", SEARCH_BOX, 10, click=True, react=True)] + (card(t) if then_card else [])


def close_summary(t):
    """Order Summary's own Close, pressed only once its label is seen there: Planning shows again."""
    return [{"action": "anchor", "window": True},
            _find(t, "os-close", (1100, 600, 1260, 680), 5, click=True, react=True)]


def lines(fields):
    """Order Summary's lines from an Access Bridge read: {schedule, ref, status, type, ready_at, deliver_by} for each
    row with a customer ref. None when Order Summary is not on the screen. Its columns come as lists down the
    screen, so the n-th cell of each is the n-th line."""
    els = (fields or {}).get("elements") or []
    i0 = next((i for i, e in enumerate(els) if e.get("r") == "internal frame" and e.get("nm") == "Order Summary"),
              None)
    if i0 is None:
        return None
    lv0, cols = els[i0].get("lv", 0), {}
    for e in els[i0 + 1:]:
        if e.get("lv", 0) <= lv0:
            break
        # the app adds " Required" to a required column's name ("Enter value for : STATUS Required", 10/11): left
        # unread, every status came back blank - and a blank status is never UNSCHEDULED, so an open line read as booked
        m = re.fullmatch(r"Enter value for : (\w+)(?:\s+Required)?", e.get("nm") or "")
        if e.get("r") == "text" and m and m.group(1) in COLUMNS and e.get("at"):
            cols.setdefault(COLUMNS[m.group(1)], []).append((e["at"][1], str(e.get("v") or "").strip()))
    down = {k: [v for _, v in sorted(cells)] for k, cells in cols.items()}
    n = max((len(v) for v in down.values()), default=0)
    rows = [{k: (down.get(k) or [])[i] if i < len(down.get(k) or []) else "" for k in COLUMNS.values()}
            for i in range(n)]
    return [r for r in rows if r["ref"]]


def day(v):
    """The dd/mm/yyyy of CTMS's "dd/mm/yy HH:MM"."""
    m = re.match(r"\s*(\d{2})/(\d{2})/(\d{2})\b", str(v or ""))
    return f"{m.group(1)}/{m.group(2)}/20{m.group(3)}" if m else ""


def open_lines(rows, date, most=12):
    """The open lines whose cards are opened for a delivery due `date` (dd/mm/yyyy) - for the Veh Type and the
    weight: that day's own - none when that day's lines are all scheduled, booked already - else, CTMS having no
    line that day (the delivery moved) and every open line on one other day, that day's. [] when nothing is open, or
    there is no telling which. At most `most`, by ref."""
    mine = [r for r in rows if day(r.get("deliver_by")) == date]
    open_ = sorted((r for r in (mine or rows) if r.get("status") == OPEN), key=lambda r: r["ref"])
    if mine:
        return open_[:most]
    if open_ and len({day(r.get("deliver_by")) for r in open_}) == 1:
        return open_[:most]
    return []


def line_for(rows, date):
    """The first of open_lines - the one line to look at for a delivery due `date` - or None."""
    got = open_lines(rows, date, 1)
    return got[0] if got else None


def card_weight(fields):
    """The open order's weight in kg from an Access Bridge read: its product lines' planned Weight cells added up.
    The card's own window only ("Order details for ..."): Planning's order well has a Weight column of its own, and
    the card's second Weight column, after Delivered, is what was carried. None when the card shows no weight."""
    els = (fields or {}).get("elements") or []
    i0 = next((i for i, e in enumerate(els) if e.get("r") == "internal frame"
               and str(e.get("nm") or "").startswith("Order details for")), None)
    if i0 is None:
        return None
    lv0, total, seen = els[i0].get("lv", 0), 0.0, False
    for e in els[i0 + 1:]:
        if e.get("lv", 0) <= lv0:
            break
        if e.get("r") != "text":
            continue
        if e.get("nm") == "Delivered":
            break                       # the carried columns start here
        if e.get("nm") == "Weight":
            try:
                total, seen = total + float(str(e.get("v") or "").replace(",", "").strip()), True
            except ValueError:
                pass                    # an empty row
    return round(total, 2) if seen else None


def veh_filled(bgra, w, h, off=(0, 0)):
    """Whether the open order's Veh Type box has words in it - dark pixels inside its border."""
    x0, y0, x1, y1 = VEH_BOX[0] + off[0], VEH_BOX[1] + off[1], VEH_BOX[2] + off[0], VEH_BOX[3] + off[1]
    x0, x1 = max(0, x0), min(w, x1)
    dark = 0
    for y in range(max(0, y0), min(h, y1)):
        row = bgra[(y * w + x0) * 4:(y * w + x1) * 4]
        dark += sum(1 for i in range(0, len(row), 4) if row[i] + row[i + 1] + row[i + 2] < 300)
    return dark >= VEH_DARK
