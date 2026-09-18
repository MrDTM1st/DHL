"""Does a cover request agree with what we hold for the order? ADVISORY ONLY.

This started as a gate that refused to send, on the belief that 6055488 had
gone to two hauliers with a collection date and a tonnage the order never
carried. That was wrong, and the way it was wrong is the point.

What actually happened (7115316, Handsacre, 14/09). The ask read "Materials:
15x aggregate, 8x ballast" and "Collection date/time: 17/09/2026". Read
against the database it looked like a doubling with a date out of nowhere,
because the upload into the database had dropped a line. The extract of 17/08
holds THREE lines: 8x 14mm pipe bedding from Bagforce, 8x track ballast from
Land Recovery, and 7x MOT Type 1 from Land Recovery, every one collecting
17/09. 8 + 7 is the 15x aggregate, and the date is the order's own. The ask
was right; the record it was being judged against was short of a line.

So nothing in here may block a send. A summary is not proof: the tracker and
the pins hold one line's worth of a multi-line order, a database can be
missing a line someone forgot to upload, and a collection date or a window is
often something the desk arranged by phone and no file will ever show. Any of
those would have this refusing correct asks - which is exactly the failure it
was built to prevent, pointed the other way.

What it does instead: print, at send time, every place the ask and the record
disagree, so the difference is seen by someone who knows which of the two is
right. A weight is always reported, because no store here knows what a
sleeper or a bag weighs, so a tonnage in an ask never came from the order.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
STORES = ("_adhocs.json", "_pins.json")

DATE_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")
QTY_RE = re.compile(r"\b(\d[\d,]*)\s*x\b", re.I)
# "1 tonne bags" and "1 tonne in 25kg bags" name the BAG, not the load - every
# bagged-ballast ask carries that wording, so without the lookahead the check
# reported "1 tonnes" on all of them and taught the desk to ignore it.
TONNES_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:t|te|tonnes?|tons?)\b"
                       r"(?!\s+(?:in\s+[\w.]+\s+)?bags?\b)", re.I)
PC_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)


# "153 x 250 x 2600" is a sleeper, not a quantity. A number-x-number chain is
# always a dimension, so it comes out before anything counts the "Nx"s -
# otherwise the checker read the ask as saying "153x" and "250x".
DIM_RE = re.compile(r"\d+(?:\.\d+)?(?:\s*[xX*]\s*\d+(?:\.\d+)?)+")


def _day(d, m, y):
    y = int(y)
    return (int(d), int(m), y + 2000 if y < 100 else y)


def _days(text):
    return {_day(*t) for t in DATE_RE.findall(str(text or ""))}


def _show(day):
    return "%02d/%02d/%d" % day


def _pcs(text):
    return {(a + b).upper().replace(" ", "") for a, b in PC_RE.findall(str(text or ""))}


def _no_dims(text):
    return DIM_RE.sub(" ", str(text or ""))


def _qtys(text):
    return {int(q.replace(",", "")) for q in QTY_RE.findall(_no_dims(text))}


def _line(message, label):
    m = re.search(rf"^[ \t]*{re.escape(label)}[ \t]*:(.*)$", message, re.I | re.M)
    return m.group(1).strip() if m else ""


def _records():
    for fn in STORES:
        try:
            with open(os.path.join(HERE, fn), encoding="utf-8") as f:
                d = json.load(f)
            for r in (d if isinstance(d, list) else []):
                yield fn, r
        except Exception:
            continue
    try:
        with open(os.path.join(HERE, "tracker.json"), encoding="utf-8") as f:
            for r in (json.load(f).get("records") or []):
                yield "tracker.json", r
    except Exception:
        pass


def facts(order):
    """Everything we hold about this order, or None if no store knows it."""
    want = str(order).strip().lower()
    for store, r in _records():
        if want not in [str(o).strip().lower() for o in (r.get("orders") or [])]:
            continue
        coll = _days(r.get("collection_date"))
        for c in (r.get("collections") or []):
            coll |= _days(c.get("date"))
        pcs = _pcs(r.get("postcode")) | _pcs(r.get("collection_pc"))
        for c in (r.get("collections") or []):
            pcs |= _pcs(c.get("pc"))
        return {
            "source": store,
            "id": r.get("id", ""),
            "collection_days": coll,
            "delivery_days": _days(r.get("delivery_date")),
            "postcodes": pcs,
            "quantities": _qtys(r.get("materials")),
            "materials": str(r.get("materials") or ""),
            "weight": str(r.get("weight") or ""),
        }
    return None


def check(message, orders):
    """[(level, text)] - differences to show a human. Nothing here blocks."""
    message = str(message or "")
    out = []
    known = {}
    for o in [str(x).strip() for x in (orders or []) if str(x).strip()]:
        f = facts(o)
        if f is None:
            out.append(("warn", f"{o}: no record in the ad hocs, the pins or the tracker, "
                               f"so nothing in this ask could be checked against the order"))
            continue
        known[o] = f
    if not known:
        return out

    coll_days = set().union(*(f["collection_days"] for f in known.values())) or set()
    del_days = set().union(*(f["delivery_days"] for f in known.values())) or set()
    all_days = coll_days | del_days
    pcs = set().union(*(f["postcodes"] for f in known.values())) or set()
    qtys = set().union(*(f["quantities"] for f in known.values())) or set()
    refs = ", ".join(known)

    for label, allowed, what in (("Collection date/time", coll_days, "collection date"),
                                 ("Delivery date/time", del_days, "delivery date")):
        if not allowed:
            continue
        for d in _days(_line(message, label)):
            if d not in allowed:
                out.append(("differs", f"\"{label}\" says {_show(d)}, but the {what} on "
                                    f"{refs} is {' / '.join(sorted(map(_show, allowed)))}"))

    if all_days:
        said = {d for _, t in out for d in _days(t)}      # already reported above
        for d in sorted(_days(message) - all_days - said):
            if not any(d in f["collection_days"] | f["delivery_days"] for f in known.values()):
                out.append(("differs", f"the ask states {_show(d)}, which is not a date held for "
                                    f"{refs} ({' / '.join(sorted(map(_show, all_days)))})"))

    if pcs:
        for pc in sorted(_pcs(message) - pcs):
            out.append(("differs", f"the ask states postcode {pc}, which is not a postcode held "
                                f"for {refs} ({', '.join(sorted(pcs))})"))

    if qtys:
        for q in _qtys(_line(message, "Materials")):
            if q not in qtys:
                out.append(("differs", f"\"Materials\" says {q}x, but the record for {refs} says "
                                    f"{' / '.join(str(x) + 'x' for x in sorted(qtys))}"))

    for t in TONNES_RE.findall(message):
        held = " ".join(f["weight"] for f in known.values()).strip()
        if not held:
            out.append(("differs", f"the ask states {t} tonnes, and no record for {refs} carries a "
                                f"weight - a haulier prices off that number, so it has to come "
                                f"from the order or from whoever you agreed it with"))
        elif t not in held:
            out.append(("differs", f"the ask states {t} tonnes; the record for {refs} says {held!r}"))
    return out


def differences(findings):
    return [t for lvl, t in findings if lvl == "differs"]


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        print("usage: python ask_check.py <order> <path to a message .txt>")
        raise SystemExit(2)
    msg = open(args[-1], encoding="utf-8").read()
    for lvl, text in check(msg, args[:-1]):
        print(f"  {lvl.upper():4} {text}")
