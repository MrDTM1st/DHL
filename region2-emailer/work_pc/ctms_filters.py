"""
The order well's filters, when they hide the order being booked (his 03/11: "Yes, and put mine back").

Book only comes here once Order Summary has said the order IS in CTMS, UNSCHEDULED, on that day, and the well still
hasn't shown it - so a filter must be what keeps it out. Then:

  read      Order Filters and Advanced Order Filters, every box by its name (or, unnamed, by where it sits in its
            window), now that the Access Bridge hands a drop-down's value over (ctms_jab, 03/11)
  clear     each one set put back to how a clean well has it - Delivery Type and Service Type "All", Show All Orders and
            Inc Nulls? ticked, everything else blank - and the well refreshed
  restore   after the booking, however it ended: each one put back to what he had, each read back. What won't go back is
            said, value by value, for him to put back by hand

A drop-down is changed the way To is (live 02/11): its list opened, its rows and the picked one read, Down / Up as many
times as the rows between them, Enter - a click on an open list's row can pick nothing. Pure decisions here; Booking
(ctms_book) runs the steps and reads the screen. Standard library only.
"""
import re

PANEL = "Order Filters"
ADVANCED = "Advanced Order Filters"
# A clean well, as seen 03/11: what each box holds when nothing is filtered
CLEAN = {"Delivery Type": "All", "Service Type": "All", "Show All Orders": True, "Inc Nulls?": True}
# Boxes the Access Bridge hands over with no name: told by where they sit from their window's top left (03/11)
UNNAMED = {PANEL: {(120, 35): "From Plan Reg", (255, 35): "From Plan Reg 2", (118, 150): "Postcode"},
           ADVANCED: {(128, 287): "Business Type", (128, 323): "Booking Status", (368, 393): "PCL",
                      (368, 425): "WS", (368, 488): "Carrier", (438, 290): "Inc Nulls?"}}
NEAR = 14
KEYS_MAX = 60                     # rows a drop-down is moved at most: a list longer than that is said, not scrolled
ROLES = ("combo box", "text", "check box")


def _frame(els, prefix):
    i0 = next((i for i, e in enumerate(els) if e.get("r") == "internal frame"
               and str(e.get("nm") or "").startswith(prefix)), None)
    if i0 is None:
        return None, None
    lv0, out = els[i0].get("lv", 0), []
    for e in els[i0 + 1:]:
        if e.get("lv", 0) <= lv0:
            break
        out.append(e)
    return els[i0], out


def placed(e):
    at = e.get("at") or []
    return len(at) == 4 and at[2] > 0 and at[3] > 0


def point(e):
    x, y, w, h = e["at"]
    return [x + w // 2, y + h // 2]


def name_of(e, window, origin):
    """A box's name: its own, or where it sits in its window when it has none."""
    nm = str(e.get("nm") or "").strip()
    if nm:
        return nm
    dx, dy = e["at"][0] - origin[0], e["at"][1] - origin[1]
    return next((n for (x, y), n in UNNAMED.get(window, {}).items() if abs(dx - x) <= NEAR and abs(dy - y) <= NEAR), None)


def boxes(els, window):
    """{name: element} of the window's filter boxes on the screen - None when the window isn't up. The radio buttons
    (From / To, > < =) are left alone: they only say how a value is used, never hide anything on their own."""
    head, inside = _frame(els, window)
    if head is None:
        return None
    out = {}
    for e in inside:
        if e.get("r") in ROLES and placed(e) and "disabled" not in (e.get("st") or []):
            nm = name_of(e, window, head["at"])
            if nm and nm not in out:
                out[nm] = e
    return out


def value(e):
    if e.get("r") == "check box":
        return "checked" in (e.get("st") or [])
    return str(e.get("v") or "").strip()


def values(els, window):
    got = boxes(els, window)
    return None if got is None else {n: value(e) for n, e in got.items()}


def set_ones(vals):
    """Those boxes not as a clean well has them: {name: what he has}."""
    out = {}
    for n, v in (vals or {}).items():
        clean = CLEAN.get(n, False if isinstance(v, bool) else "")
        if v != clean:
            out[n] = v
    return out


def list_rows(els, box):
    """An open drop-down's rows, top down, as (name, picked): the labels right under the box. None when it isn't open."""
    i = next((k for k, e in enumerate(els) if e is box), None)
    if i is None:
        return None
    rows = []
    for e in els[i + 1:]:
        if e.get("lv", 0) <= box.get("lv", 0):
            break
        if e.get("r") == "label":
            rows.append((str(e.get("nm") or "").strip(), "selected" in (e.get("st") or [])))
    return rows or None


def moves(rows, want):
    """The keys that move an open list from its picked row to the row named want: ["down", ...] - None when want isn't a
    row, nothing is picked, or it is further than KEYS_MAX."""
    names = [n for n, _ in rows]
    at = next((k for k, (_, on) in enumerate(rows) if on), None)
    if at is None or want not in names:
        return None
    to = names.index(want)
    if abs(to - at) > KEYS_MAX:
        return None
    return ["down" if to > at else "up"] * abs(to - at)


def said(vals):
    return ", ".join(f"{n} {'ticked' if v is True else 'not ticked' if v is False else repr(v)}" for n, v in vals.items())
