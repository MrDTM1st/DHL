"""Haulier quote memory - log what hauliers charge per lane (collection ->
delivery), then ESTIMATE the cost of a new order from past quotes around the
same places. The more quotes logged, the sharper the estimates get.

    python quotes.py add <haulier> <from pc> <to pc> <price> [order] [vehicle] [notes...]
    python quotes.py est <from pc> <to pc>
    python quotes.py list [n]

Matching is postcode-based, most-specific first:
    district->district  (ST6 -> B9)      exact lane
    area->area          (ST  -> B)       same lane, nearby ends
    reverse lane        (B   -> ST)      haulage is roughly symmetric
    same delivery area  (*   -> B)       weakest - flagged as rough

Quotes live in _quotes.json (gitignored). Every estimate names the quotes it
came from, so a number is never unexplained.
"""
import os, re, sys, json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_quotes.json")


def _outward(pc):
    """'ST6 4NU' -> 'ST6' (district); '' when unparseable."""
    m = re.match(r"\s*([A-Za-z]{1,2}\d[A-Za-z\d]?)", str(pc or ""))
    return m.group(1).upper() if m else ""


def _area(pc):
    """'ST6 4NU' -> 'ST' (area)."""
    m = re.match(r"\s*([A-Za-z]{1,2})", str(pc or ""))
    return m.group(1).upper() if m else ""


def _load():
    try:
        return json.load(open(PATH, encoding="utf-8"))
    except Exception:
        return {"quotes": []}


def _save(d):
    tmp = PATH + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, PATH)


def add(haulier, from_pc, to_pc, price, order="", vehicle="", notes=""):
    """Log one quote. Price accepts '£450', '450.00', '450'."""
    p = float(re.sub(r"[^\d.]", "", str(price)))
    d = _load()
    d["quotes"].append({
        "at": datetime.now().strftime("%Y-%m-%d"),
        "haulier": str(haulier).strip(), "order": str(order).strip(),
        "from_pc": str(from_pc).strip().upper(), "to_pc": str(to_pc).strip().upper(),
        "from_d": _outward(from_pc), "to_d": _outward(to_pc),
        "from_a": _area(from_pc), "to_a": _area(to_pc),
        "price": p, "vehicle": str(vehicle).strip(), "notes": str(notes).strip(),
    })
    _save(d)
    return p


def estimate(from_pc, to_pc):
    """-> dict(price_low, price_high, typical, basis, quotes) or None when
    nothing comparable has been logged yet."""
    qs = _load()["quotes"]
    if not qs:
        return None
    fd, td, fa, ta = _outward(from_pc), _outward(to_pc), _area(from_pc), _area(to_pc)
    tiers = [
        ("exact lane", [q for q in qs if q["from_d"] == fd and q["to_d"] == td]),
        ("same-area lane", [q for q in qs if q["from_a"] == fa and q["to_a"] == ta]),
        ("reverse lane", [q for q in qs if q["from_a"] == ta and q["to_a"] == fa]),
        ("same delivery area (rough)", [q for q in qs if q["to_a"] == ta]),
    ]
    for basis, hit in tiers:
        if not hit:
            continue
        hit = sorted(hit, key=lambda q: q["at"], reverse=True)[:8]   # recent quotes count
        prices = [q["price"] for q in hit]
        return {
            "basis": basis, "n": len(hit),
            "price_low": min(prices), "price_high": max(prices),
            "typical": round(sorted(prices)[len(prices) // 2], 2),   # median
            "quotes": [{"haulier": q["haulier"], "price": q["price"], "at": q["at"],
                        "lane": f"{q['from_d']}->{q['to_d']}"} for q in hit],
        }
    return None


def main():
    a = sys.argv[1:]
    if a and a[0] == "add" and len(a) >= 5:
        p = add(a[1], a[2], a[3], a[4], *(a[5:8]), notes=" ".join(a[8:]))
        print(f"logged: {a[1]} {_outward(a[2])}->{_outward(a[3])} £{p:.2f}")
    elif a and a[0] == "est" and len(a) >= 3:
        e = estimate(a[1], a[2])
        if not e:
            print("no comparable quotes logged yet - log some with: quotes.py add")
            return
        print(f"estimate {_outward(a[1])} -> {_outward(a[2])}:  "
              f"~£{e['typical']:.0f}  (range £{e['price_low']:.0f}-£{e['price_high']:.0f}, "
              f"{e['n']} quote(s), basis: {e['basis']})")
        for q in e["quotes"]:
            print(f"    {q['at']}  {q['haulier']:24} {q['lane']:12} £{q['price']:.2f}")
    elif a and a[0] == "list":
        qs = _load()["quotes"][-int(a[1] if len(a) > 1 else 20):]
        for q in qs:
            print(f"  {q['at']}  {q['haulier']:24} {q['from_d']:5}->{q['to_d']:5} "
                  f"£{q['price']:8.2f}  {q.get('vehicle','')}")
        print(f"({len(_load()['quotes'])} total)")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
