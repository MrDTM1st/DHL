"""
The quantities an ask states, checked against CTMS's own weights (his 27/11).

An ask to DHL NOC said 6 rails for a delivery CTMS holds 4 for: the list was built from the tracker, whose materials are
the extract's ("6x rails"), while CTMS's two lines for that day weighed 2 rails each. His words: "Make sure when you're
getting like quantities, you actually get from where you're supposed to get from." CTMS is where: its lines for the
delivery day. Where a weight can tell a count - rails (their profile's kg a metre times their length) and bagged
ballast (a tonne a bag) - the count is worked out from the weight the CTMS look-up put on the record, and a count that
isn't the extract's is said. The dashboard's cover request and NOC Teams message do the same (orders.js ctmsCount).

    python ask_quantities.py                 every delivery on the tracker whose CTMS weight says another count
    python ask_quantities.py 9100001 ...     these orders: the count each ask should state, and where it came from

Reads the tracker; never writes it.
"""
import json
import re
import sys

# kg a metre by rail profile, as CTMS's rail codes name them
RAIL_KG_M = {"56E1": 56.0, "60E2": 60.03, "113A": 56.4, "CEN56": 56.0, "CEN60": 60.0, "UIC60": 60.0}
SLACK = 0.05                     # a weight within 5% of a count's is that count (rounding, plates, a heavier batch)


def rail_units(codes):
    """The weight of one rail of each rail code here (kg), [] for no rail - None when a rail's profile or length can't
    be read, so no count is worked out from it."""
    out = []
    for raw in codes or []:
        code = str(raw or "").upper()
        if not re.search(r"\bRAIL\b", code) or re.search(r"S&C|SWITCH|CROSSING", code):
            continue
        prof = next((p for p in RAIL_KG_M if re.search(rf"\b{p}\b", code)), None)
        length = re.search(r"(\d+(?:\.\d+)?)\s*M\b", code)
        if not prof or not length:
            return None
        out.append(RAIL_KG_M[prof] * float(length.group(1)))
    return out


def _kg(v):
    return f"{round(v):,} kg"


def ctms_count(rec):
    """{"count", "what", "said"} - what CTMS's weight says this delivery holds when it can tell and that isn't the
    extract's count (count None: the weight doesn't fit the extract's count, but how many of each length can't be
    told). None when they agree, CTMS hasn't been looked at, or a weight can't tell (sleepers, mixed loads)."""
    try:
        kg = float(rec.get("ctms_weight") or 0)
    except (TypeError, ValueError):
        kg = 0
    m = re.fullmatch(r"(\d+)x (rails|ballast)", str(rec.get("materials") or "").strip())
    if not kg or not m:
        return None
    said = int(m.group(1))
    codes = [str(c) for c in rec.get("product_codes") or []]
    if m.group(2) == "ballast":
        if rec.get("loose_ballast") or re.search(r"\bloose\b|100500/001", " ".join([rec.get("materials") or ""] + codes),
                                                re.I):
            return None                          # loose ballast goes by the tonne on a tipper, not by the bag
        count = round(kg / 1000)
        return None if count == said else {
            "count": count, "what": "ballast",
            "said": f"CTMS weighs it {_kg(kg)}: {count} bags of ballast, not the {said} the extract says"}
    units = rail_units(codes)
    if not units:
        return None
    lo, hi = min(units), max(units)
    if abs(lo - hi) < 0.01:
        count = round(kg / lo)
        return None if count == said else {
            "count": count, "what": "rails",
            "said": f"CTMS weighs them {_kg(kg)}: {count} rails, not the {said} the extract says"}
    if said * lo * (1 - SLACK) <= kg <= said * hi * (1 + SLACK):
        return None
    return {"count": None, "what": "rails",
            "said": f"CTMS weighs them {_kg(kg)}, which isn't {said} rails (they'd weigh {_kg(said * lo)} to "
                    f"{_kg(said * hi)})"}


def ask_line(rec):
    """(what an ask should say, where it came from): CTMS's count when its weight tells one and the extract differs."""
    c = ctms_count(rec)
    if c and c["count"] is not None:
        return f"{c['count']}x {c['what']}", "CTMS's weight"
    if c:
        return str(rec.get("materials") or ""), "the extract - CHECK the count in CTMS before you ask: " + c["said"]
    return str(rec.get("materials") or ""), "the extract" + ("" if rec.get("ctms_weight") else " (CTMS not looked at yet)")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import tracker
    want = {str(a).strip() for a in (argv if argv is not None else sys.argv[1:]) if str(a).strip()}
    recs = [r for r in tracker.load().get("records", []) if r.get("kind", "delivery") == "delivery"
            and (not want or want & {str(o) for o in r.get("orders") or []})]
    shown = 0
    for r in recs:
        line, source = ask_line(r)
        if not want and source.startswith("the extract"):
            continue                              # the list: only the deliveries whose CTMS weight says otherwise
        shown += 1
        print(f"{' / '.join(r.get('orders') or [])} {r.get('delivery_date')}: {line}  <- {source}")
    if want and not recs:
        print("None of those is on the tracker: read the order's lines in CTMS (order-read) for its quantities.")
    elif not want and not shown:
        print("Every delivery's CTMS weight fits its count (or CTMS can't tell it from the weight).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
