"""
What Book checks on each order line before it makes a trip, and what it does about it (his ask 03/11: "if there are
missing parts in the order lines that are crucial for booking in, you deal with it instead of just going right by it").

The rules, his:
  - the Product Type in the Detail tab's grid is the right one; every item on Order Items must be that product - its
    Identifier put right through Ctrl+L, taking the list's TOP choice ("just use the top one just to be safe")
  - the quantity must be the order's: when it isn't, both the Detail tab's Qty and the item's Ordered are put right
  - what the desk doesn't know, Book doesn't guess: it stops and asks

Read off the order's card through the Access Bridge, the way it was learned live on 03/11 (CTMS_SCREENS.md). Pure
functions: Book (ctms_book.Booking) does the clicking. Standard library only, like the rest of work_pc/.
"""
import re

CARD = "Order details for"
ITEM_WINDOW = "Create,Edit or Delete Order Item"
LIST_WINDOW = "Product Items"
ITEM_ROW = re.compile(r"Item_Id:(.*?)\tItem_Description:(.*)", re.S)


class Doubt(RuntimeError):
    """Something the desk doesn't know the answer to: his words, a question for him. Nothing was changed."""


def _frame(els, prefix):
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


def placed(e):
    at = e.get("at") or []
    return len(at) == 4 and at[2] > 0 and at[3] > 0


def point(e):
    x, y, w, h = e["at"]
    return [x + w // 2, y + h // 2]


def number(text):
    """16 from '   16.000', 24000 from '  24,000.00'; None when it isn't a number."""
    s = str(text or "").replace(",", "").strip()
    try:
        return float(s) if s else None
    except ValueError:
        return None


def same(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.0005


def _name(e):
    """A field's name without the tab page it sits on ("Order Items tab page Identifier Required" -> "Identifier")."""
    nm = re.sub(r"^.*? tab page ", "", str(e.get("nm") or "")).strip()
    return re.sub(r"\s+Required$", "", nm)


def _columns(frame, names):
    """{column name: [cells top down]} for these names - each placed text cell, by its name."""
    out = {n: [] for n in names}
    for e in frame or []:
        if e.get("r") == "text" and placed(e) and _name(e) in out:
            out[_name(e)].append(e)
    for n in out:
        out[n].sort(key=lambda e: e["at"][1])
    return out


def _rows(cols, key):
    """The grid's rows, top down, as {column: cell}: one a height of the key column, the others matched by height."""
    rows = []
    for k in cols.get(key) or []:
        row = {key: k}
        for n, cells in cols.items():
            if n != key:
                c = next((c for c in cells if abs(c["at"][1] - k["at"][1]) <= 6), None)
                if c is not None:
                    row[n] = c
        rows.append(row)
    return rows


# -- what the card says
def detail(els):
    """The Detail tab's product grid: [{"product", "qty", "weight", "qty_box"}] for each row with a product - None when the
    card's Detail tab isn't what's showing."""
    frame = _frame(els, CARD)
    if frame is None or not any(e.get("r") == "page tab" and _name(e) == "Detail" and "selected" in (e.get("st") or [])
                                for e in frame):
        return None
    rows = _rows(_columns(frame, ("Product Type", "Qty", "Weight")), "Product Type")
    out = []
    for r in rows:
        product = str(r["Product Type"].get("v") or "").strip()
        if product:
            out.append({"product": product, "qty": number((r.get("Qty") or {}).get("v")),
                        "weight": number((r.get("Weight") or {}).get("v")), "qty_box": r.get("Qty")})
    return out


def items(els):
    """Order Items' grid: [{"identifier", "product", "ordered", "cell"}] for each item - None when that tab isn't showing."""
    frame = _frame(els, CARD)
    if frame is None or not any(e.get("r") == "page tab" and _name(e) == "Order Items" and "selected" in (e.get("st") or [])
                                for e in frame):
        return None
    out = []
    for r in _rows(_columns(frame, ("Identifier", "Product", "Ordered", "Weight")), "Identifier"):
        ident = str(r["Identifier"].get("v") or "").strip()
        if ident:
            out.append({"identifier": ident, "product": str((r.get("Product") or {}).get("v") or "").strip(),
                        "ordered": number((r.get("Ordered") or {}).get("v")), "cell": r["Identifier"]})
    return out


def tab(els, name):
    """The card's page tab of that name, or None."""
    return next((e for e in _frame(els, CARD) or [] if e.get("r") == "page tab" and _name(e) == name and placed(e)), None)


def button(els, window, name):
    """A push button of that window, enabled and on the screen - by its words before any ALT shortcut."""
    for e in _frame(els, window) or []:
        if (e.get("r") == "push button" and placed(e) and "disabled" not in (e.get("st") or [])
                and re.sub(r"\s+ALT\s+\w$", "", str(e.get("nm") or "")).strip() == name):
            return e
    return None


def field(els, window, name):
    """A text box of that window by its name (its tab page and "Required" aside), the top one when a grid has several."""
    got = [e for e in _frame(els, window) or [] if e.get("r") == "text" and placed(e) and _name(e) == name]
    return min(got, key=lambda e: e["at"][1]) if got else None


def item_window(els):
    """The open item window: {"identifier", "ordered"} - None when it isn't up."""
    frame = _frame(els, ITEM_WINDOW)
    if frame is None:
        return None
    ident, ordered = field(els, ITEM_WINDOW, "Identifier"), field(els, ITEM_WINDOW, "Ordered")
    return {"identifier": str((ident or {}).get("v") or "").strip(), "ordered": number((ordered or {}).get("v"))}


def choices(els):
    """Ctrl+L's Product Items list, top first: [(item id, description)] - None when it isn't up."""
    frame = _frame(els, LIST_WINDOW)
    if frame is None:
        return None
    out = []
    for e in frame:
        m = ITEM_ROW.fullmatch(str(e.get("nm") or "")) if e.get("r") == "label" else None
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


# -- what has to change
def plan(ref, rows, its, want=None):
    """What has to change on one line, from its Detail grid and Order Items: {"items": [(index, identifier or None,
    ordered or None)], "qty": new Detail Qty or None, "said": [...]}. want: the order's quantity for this line, when the desk
    knows it. Raises Doubt for what the desk can't settle."""
    if not rows:
        raise Doubt(f"{ref}: its Detail tab shows no Product Type, so there's nothing to check Order Items against.")
    if not its:
        raise Doubt(f"{ref}: Order Items has no item on it.")
    products = {r["product"].upper() for r in rows}
    fix, said = [], []
    for i, it in enumerate(its):
        new_id = None
        if it["identifier"].upper() not in products:
            if len(products) != 1:
                raise Doubt(f"{ref}: item {it['identifier']} isn't one of the Detail tab's products "
                            f"({', '.join(sorted(products))}) - which should it be?")
            new_id = rows[0]["product"]
            said.append(f"{ref}: item {it['identifier']} put right to {new_id}")
        fix.append([i, new_id, None])
    have = sum(r["qty"] or 0 for r in rows)
    ordered = sum(it["ordered"] or 0 for it in its)
    new_qty = None
    if want is not None:
        if not same(have, want) or not same(ordered, want):
            if len(rows) != 1 or len(its) != 1:
                raise Doubt(f"{ref}: the order is for {want:g}, but CTMS has {have:g} on the Detail tab and {ordered:g} on "
                            f"Order Items over {len(rows)} product row(s) and {len(its)} item(s) - which goes where?")
            if not same(have, want):
                new_qty = want
                said.append(f"{ref}: Detail Qty {have:g} put right to {want:g}")
            if not same(ordered, want):
                fix[0][2] = want
                said.append(f"{ref}: Ordered {ordered:g} put right to {want:g}")
    elif not same(have, ordered):
        raise Doubt(f"{ref}: the Detail tab says {have:g} and Order Items says {ordered:g}, and the desk doesn't know "
                    "the order's quantity - which is right?")
    return {"items": [tuple(f) for f in fix if f[1] or f[2] is not None], "qty": new_qty, "said": said}
