"""
Same-day collection (his rule 16/11): "within like a 65-mile radius should be same day ... if it's like a daytime order",
and it "should also depend on the opening times of the collection site and then the ETA that we'd see on the map".

A delivery is collected the SAME DAY as it's delivered when all of these hold:
  * it's a daytime delivery (starts DAY_FROM..DAY_TO) - a night job keeps the day before
  * the road run from the collection to the delivery is MAX_MILES or less
  * the yard's opening time plus the drive gets there by the delivery's start
The road run is the map's own: postcodes.io for the points, OSRM for the road miles and drive time (the brief's
"mi · drive" line). Each pair is asked once and kept in _road_cache.json. No road answer = no same-day decision, and
the old rule stands.

When the day changes only the day changes - the collection keeps the time CTMS has (his 16/11).
"""
import json
import os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_road_cache.json")
MAX_MILES = 65
DAY_FROM, DAY_TO = "06:00", "18:00"
METRES_PER_MILE = 1609.344


def _hm(text):
    try:
        return datetime.strptime(str(text or "").strip()[:5], "%H:%M")
    except ValueError:
        return None


def _load():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(cache):
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE)


def _osrm(a, b):
    import urllib.request
    url = (f"https://router.project-osrm.org/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}?overview=false")
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.loads(r.read())
    rt = (d.get("routes") or [None])[0]
    if not rt:
        return None
    return {"miles": round(rt["distance"] / METRES_PER_MILE, 1), "seconds": int(rt["duration"])}


def road(c_pc, d_pc, router=None, geocode=None):
    """{miles, seconds} by road from one postcode to the other - None when it can't be worked out."""
    import hauliers
    norm = hauliers._norm_pc
    a, b = norm(c_pc or ""), norm(d_pc or "")
    if not a or not b:
        return None
    key = f"{a}|{b}"
    cache = _load()
    if cache.get(key):
        return cache[key]
    try:
        geo = (geocode or hauliers.geocode)([a, b])
        pa, pb = geo.get(a), geo.get(b)
        got = (router or _osrm)(pa, pb) if pa and pb else None
    except Exception:
        got = None
    if got:
        cache[key] = got
        _save(cache)
    return got


def drive_text(seconds):
    m = int(round(seconds / 60))
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


def check(c_pc, d_pc, yard_open, start, run=None):
    """(same day?, why) for a delivery starting at `start` (HH:MM) from a yard opening at `yard_open`. (None, why)
    when it can't be told - the old rule stands."""
    t0, t_open = _hm(start), _hm(yard_open)
    if t0 is None or t_open is None:
        return None, ""
    if not (_hm(DAY_FROM) <= t0 < _hm(DAY_TO)):
        return False, ""                                  # a night job: the day before, as ever
    run = run if run is not None else road(c_pc, d_pc)
    if not run:
        return None, "The road run couldn't be worked out, so the same-day rule wasn't used"
    miles, drive = run["miles"], drive_text(run["seconds"])
    if miles > MAX_MILES:
        return False, f"Collected the day before: {miles:g} miles, over {MAX_MILES}"
    there = t_open + timedelta(seconds=run["seconds"])
    if there > t0:
        return False, (f"Collected the day before: {miles:g} miles, but the yard opens {yard_open} and the "
                       f"{drive} drive gets there {there:%H:%M}, after the {start} delivery")
    return True, (f"Collected the same day: {miles:g} miles, yard opens {yard_open} + {drive} drive, "
                  f"there by {there:%H:%M} for the {start} delivery (your 65-mile rule)")
