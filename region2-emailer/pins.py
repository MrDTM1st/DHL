"""Orders you emailed BY HAND, pinned on the map.

The map plots two things: tracker records (orders the tool emailed) and ad hocs.
An order you emailed yourself is in neither, so it is invisible - which matters
most on the days you do the most by hand, because those are exactly the days
the map is meant to help you see.

A pin is deliberately NOT a tracker record. Tracking means chasing: the order
joins the chase sweeps, the reply checks and the send-off logic. Sometimes that
is what you want and sometimes you only want to see it on the map, so the
choice is made per order at the moment you pin it (order_pin.py `track`).

Pins carry kind="pinned" so the dashboard can label them and never offer them
a chase they have no tracker record to hang off.
"""
import json
import os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_pins.json")
KEEP_DAYS = 30          # a pin outlives its delivery date by a month, then goes


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        # A pin store that cannot be read must not be silently replaced with an
        # empty one - that is how a map quietly loses everything on it. Keep the
        # bad file so it can be looked at, and start clean alongside it.
        try:
            os.replace(PATH, PATH + ".unreadable")
            print(f"  !! {os.path.basename(PATH)} was unreadable - kept as "
                  f"{os.path.basename(PATH)}.unreadable, starting a new one")
        except Exception:
            pass
        return []


def save(pins):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pins, f, indent=1)
    os.replace(tmp, PATH)          # atomic: a concurrent read never sees a partial file


def _stale(p, today=None):
    """True once the delivery date is more than KEEP_DAYS behind us."""
    try:
        d = datetime.strptime(str(p.get("delivery_date"))[:10], "%d/%m/%Y").date()
    except Exception:
        return False               # unparseable date: never our call to bin it
    return d < (today or datetime.now().date()) - timedelta(days=KEEP_DAYS)


def add(rec):
    """Add or replace a pin. Same orders + same delivery date = the same pin."""
    pins = [p for p in load() if not _stale(p)]
    pins = [p for p in pins if p.get("id") != rec.get("id")]
    pins.insert(0, rec)
    save(pins)
    return len(pins)


def remove(pin_id):
    pins = load()
    keep = [p for p in pins if p.get("id") != str(pin_id).strip()]
    n = len(pins) - len(keep)
    if n:
        save(keep)
    return n


def make_id(orders, delivery_date):
    return "pin|" + "-".join(str(o) for o in orders) + "|" + str(delivery_date)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "remove":
        print(f"removed {remove(sys.argv[2])} pin(s)")
    else:
        for p in load():
            print(f"  {'/'.join(p.get('orders', [])):18} {p.get('delivery_date','?'):12} "
                  f"{p.get('site','?')} {p.get('postcode','')}")
        print(f"  -> {len(load())} pin(s)")
