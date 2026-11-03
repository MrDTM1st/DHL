"""
The order well - Planning's grid of orders - read as text (his "yes, build it", 02/11, after asking whether the code
could see: "it would allow it to make it easier to find orders in the order well").

CTMS's Java hands each cell of the grid to the Access Bridge as a nameless text field with its value and where it sits
on the screen. So the columns are told by where they sit: the order number column is under its Cust Ref heading - or,
that not handed over, the leftmost whose cells read like order numbers - and every other column by how far across from
it it sits (as laid out on the Planning screen, 02/11). Rows are the cells at one height. Only the rows on screen are there - the
grid shows 15 - so a longer list is read a page at a time (ctms_remote.py well --all: Page Down, read, merge()).

    rows(elements)            the rows on screen: [{cust_ref, booking_ref, from_loc, ..., "cell": [x, y, w, h]}]
    find(rows, ref)           the row for an order number (Cust Ref), or None
    point(row)                the screen point at the middle of its order number - for a click or a double-click
"""
import re

FRAME = "Planning"
# Each column's distance across from the Cust Ref column's left edge, in screen pixels (Planning, 02/11).
OFFSETS = {"cust_ref": 0, "booking_ref": 100, "from_loc": 200, "from_post": 284, "to_loc": 368, "to_post": 450,
           "to_reg": 534, "fr": 576, "collect": 616, "deliver": 684, "del_type": 750, "weight": 818, "dus": 870,
           "product": 918, "vehicle": 1008, "length": 1076, "di": 1132}
NEAR = 20                      # how far a column may sit from where it is expected, in pixels
ROW_NEAR = 6                   # cells this close in height are one row
ORDER_REF = re.compile(r"[A-Z]{0,4}\d{5,8}(?:-\d+-\d+)?(?:_C\d+)?", re.I)


def _frame(els, prefix=FRAME):
    i0 = next((i for i, e in enumerate(els) if e.get("r") == "internal frame"
               and str(e.get("nm") or "").startswith(prefix)), None)
    if i0 is None:
        return None
    lv0, out = els[i0].get("lv", 0), []
    for e in els[i0 + 1:]:
        if e.get("lv", 0) <= lv0:
            break
        out.append(e)
    return out


def _cells(frame):
    """The grid's cells: nameless text fields below the filter row (Order Filters), with a place on the screen."""
    filters = next((e for e in frame if e.get("r") == "push button" and e.get("nm") == "Order Filters"), None)
    floor = (filters["at"][1] + 20) if filters and filters.get("at") else None
    out = []
    for e in frame:
        at = e.get("at") or []
        if (e.get("r") == "text" and not str(e.get("nm") or "").strip() and len(at) == 4 and at[2] > 0
                and at[3] > 0 and (floor is None or at[1] >= floor)):
            out.append(e)
    return out


def _columns(cells):
    """{x: [cells]} - the grid's columns by where they start across."""
    cols = {}
    for c in cells:
        x = c["at"][0]
        key = next((k for k in cols if abs(k - x) <= 2), x)
        cols.setdefault(key, []).append(c)
    return cols


def rows(els):
    """The order well's rows on screen, top first - each the columns it could name, and "cell", where its order number
    sits. [] when Planning isn't up or its grid can't be told apart."""
    frame = _frame(els)
    if not frame:
        return []
    cols = _columns(_cells(frame))
    head = next((e for e in frame if e.get("r") == "push button" and e.get("nm") == "Cust Ref"
                 and (e.get("at") or [0])[0] > 0), None)
    refs = sorted(x for x, cs in cols.items()
                  if any(ORDER_REF.fullmatch(str(c.get("v") or "").strip()) for c in cs))
    if head:                                         # a page of ad hocs alone has nothing that reads like an order number
        x0 = next((x for x in cols if abs(x - head["at"][0]) <= 2), None)
    else:
        x0 = refs[0] if refs else None               # the leftmost column of order numbers: Cust Ref
    if x0 is None:
        return []
    named = {}
    for x, cs in cols.items():
        name = min(OFFSETS, key=lambda n: abs(x - x0 - OFFSETS[n]))
        if abs(x - x0 - OFFSETS[name]) <= NEAR and name not in named:
            named[name] = cs
    lines = {}
    for c in named.get("cust_ref", []):
        v = str(c.get("v") or "").strip()
        if v:
            lines[c["at"][1]] = {"cust_ref": v, "cell": list(c["at"])}
    for name, cs in named.items():
        if name == "cust_ref":
            continue
        for c in cs:
            y = next((k for k in lines if abs(k - c["at"][1]) <= ROW_NEAR), None)
            if y is not None:
                lines[y][name] = str(c.get("v") or "").strip()
    return [lines[y] for y in sorted(lines)]


def find(rows_, ref):
    """The row whose order number is `ref` (exact, whatever its case) - None when it isn't on screen."""
    want = str(ref or "").strip().upper()
    return next((r for r in rows_ if r.get("cust_ref", "").upper() == want), None)


def point(row):
    """The screen point at the middle of a row's order number."""
    x, y, w, h = row["cell"]
    return [x + w // 2, y + h // 2]


def merge(seen, page):
    """Rows from a further page added to those seen - by order number, each once. Returns how many were new."""
    have = {r["cust_ref"] for r in seen}
    new = [r for r in page if r["cust_ref"] not in have]
    seen.extend(new)
    return len(new)


def question(els):
    """A Forms question up on the screen: (its window's name, {its buttons' first word, lower case: element}), or None. It
    comes as a window inside the one that asked, its words in its name and an option pane straight under it."""
    window = None
    for e in els:
        if e.get("r") == "internal frame":
            window = str(e.get("nm") or "")
        elif e.get("r") == "option pane" and window is not None:
            inside = _frame(els, window) or []
            return window, {str(b.get("nm") or "").split()[0].lower(): b for b in inside
                            if b.get("r") == "push button" and str(b.get("nm") or "").strip()}
    return None
