"""
An order with several pick-ups and/or several delivery days (his rule 02/11): the update goes on the earliest day, the
rest is kept on the tracker record (its `collections`, each with its date, and the reply's date options), anyone we email
is told it is separate pick-ups, and Book splits it down by day.

What is here is the wording; ctms_run_plan.py sets the earliest day, book_run.py tells the site and the planner.
"""
from datetime import datetime


def short(d):
    return datetime.strptime(d, "%d/%m/%Y").strftime("%d/%m/%y")


def pickups(rec):
    """The record's pick-ups as [{"site", "date"}], a pick-up with neither site nor date left out."""
    out = []
    for c in (rec or {}).get("collections") or []:
        site = str(c.get("site") or c.get("pc") or "").strip(" -")
        if site or c.get("date"):
            out.append({"site": site, "date": c.get("date") or ""})
    return out


def days(rec):
    """Every delivery day the reply named, earliest first ("dd/mm/yyyy")."""
    opts = (((rec or {}).get("details") or {}).get("date") or {}).get("options") or []
    got = set()
    for o in opts:
        try:
            got.add(datetime.strptime(str(o).strip(), "%d/%m/%Y"))
        except ValueError:
            continue
    return [d.strftime("%d/%m/%Y") for d in sorted(got)]


def is_split(rec):
    return len(pickups(rec)) > 1 or len(days(rec)) > 1


def note(rec, day=""):
    """The sentence for an email: '' when the order is one pick-up on one day."""
    if not is_split(rec):
        return ""
    bits = []
    ps = pickups(rec)
    if len(ps) > 1:
        what = "; ".join(p["site"] + (f" on {p['date']}" if p["date"] else "") for p in ps)
        bits.append(f"This order is {len(ps)} separate pick-ups ({what}).")
    others = [d for d in days(rec) if d != day]
    if len(days(rec)) > 1 and others:
        bits.append("The rest is booked for " + " and ".join(others) + " separately.")
    return " ".join(bits)
