"""Who have we already asked to cover this job?

Chasing haulage means emailing round several hauliers for one order, often over
two days, sometimes from the dashboard and sometimes straight from Outlook. The
tool remembered none of it: send_haulier is deliberately not tracker-logged
(the tracker chases DELIVERY contacts, and enrolling a haulier there would
chase them as if they were the customer), so nothing anywhere knew who had
already been asked - and the same haulier gets the same job twice.

This works it out from SENT ITEMS rather than from a log the tool has to
remember to write. That matters: most of these go out by hand, and a log would
only ever know about the ones that went through the dashboard. Sent Items knows
about both, and it knows retrospectively - every haulier you have already
emailed is found on the first run.

A hit is: a sent mail whose SUBJECT carries the order number, addressed to an
address (or display name) belonging to a known haulier.

    python haulier_asks.py                  refresh from Sent Items, print it
    python haulier_asks.py 7115220          just that order
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_haulier_asks.json")
SCAN_DAYS = 45
SCAN_ITEMS = 900


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, PATH)


def _directory():
    """[(name, [emails])] for every haulier and courier we know."""
    import hauliers
    d = hauliers.load()
    out = []
    for group in ("hauliers", "couriers"):
        for h in d.get(group, []) or []:
            name = str(h.get("name") or "").strip()
            mails = [str(e).strip().lower() for e in (h.get("emails") or []) if e]
            if name:
                out.append((name, mails))
    return out


def record(orders, name, email, how="dashboard", when=None):
    """Note an ask straight away, so the dashboard reflects it before the next
    Sent Items sweep catches up."""
    d = load()
    when = when or datetime.now().strftime("%d/%m/%Y %H:%M")
    for o in orders or []:
        row = d.setdefault(str(o).strip(), [])
        if any((a.get("email") or "").lower() == str(email or "").lower()
               and a.get("name") == name for a in row):
            continue
        row.append({"name": name, "email": email, "when": when, "how": how})
    save(d)
    return d


def scan(ns, orders, limit=SCAN_ITEMS, days=SCAN_DAYS):
    """Sweep Sent Items and return {order: [{name, email, when, how}]}."""
    import build_drafts as bd
    wanted = {str(o).strip() for o in orders if str(o).strip()}
    if not wanted:
        return {}
    directory = _directory()
    dhl = bd.dhl_store(ns)
    sent = bd.sub(dhl, "Sent Items") if dhl else None
    if sent is None:
        return {}
    items = sent.Items
    try:
        items.Sort("[SentOn]", True)
    except Exception:
        pass
    cutoff = datetime.now() - timedelta(days=days)
    found = {}
    n = 0
    for it in items:
        n += 1
        if n > limit:
            break
        try:
            when = it.SentOn.replace(tzinfo=None)
            if when < cutoff:
                break
            subj = str(it.Subject or "")
            to_cc = (str(getattr(it, "To", "") or "") + " ; "
                     + str(getattr(it, "CC", "") or "")).lower()
        except Exception:
            continue
        hits = [o for o in wanted if o in subj]
        if not hits or not to_cc.strip(" ;"):
            continue
        for name, mails in directory:
            match = any(m and m in to_cc for m in mails)
            if not match and len(name) >= 5 and name.lower() in to_cc:
                match = True          # Outlook shows a resolved contact by name
            if not match:
                continue
            stamp = when.strftime("%d/%m/%Y %H:%M")
            for o in hits:
                row = found.setdefault(o, [])
                if not any(a["name"] == name for a in row):
                    row.append({"name": name, "email": (mails or [""])[0],
                                "when": stamp, "how": "sent items"})
    return found


def refresh(ns, orders):
    """Merge a fresh Sent Items sweep over what we already had, and save."""
    d = load()
    for order, asks in scan(ns, orders).items():
        row = d.setdefault(order, [])
        for a in asks:
            if not any(x["name"] == a["name"] for x in row):
                row.append(a)
    save(d)
    return d


def _tracked_orders():
    """Every order currently worth scanning: tracker + pins + ad hocs."""
    out = set()
    try:
        import tracker
        for r in tracker.load().get("records", []):
            out |= {str(o).strip() for o in r.get("orders", [])}
    except Exception:
        pass
    for mod, attr in (("pins", "load"), ):
        try:
            m = __import__(mod)
            for r in getattr(m, attr)():
                out |= {str(o).strip() for o in r.get("orders", [])}
        except Exception:
            pass
    try:
        with open(os.path.join(HERE, "_adhocs.json"), encoding="utf-8") as f:
            for r in json.load(f):
                out |= {str(o).strip() for o in r.get("orders", [])}
    except Exception:
        pass
    return {o for o in out if o}


if __name__ == "__main__":
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if arg:
        d = load()
        for a in d.get(arg, []):
            print(f"  {a['when']}  {a['name']:32} {a.get('how','')}")
        print(f"  -> {len(d.get(arg, []))} haulier(s) already asked about {arg}")
    else:
        import build_drafts as bd
        orders = _tracked_orders()
        print(f"scanning Sent Items for {len(orders)} order(s)...")
        d = refresh(bd.get_ns(), orders)
        total = sum(len(v) for v in d.values())
        for order in sorted(d):
            if d[order]:
                print(f"  {order}: " + ", ".join(a["name"] for a in d[order]))
        print(f"  -> {total} ask(s) across {len([k for k,v in d.items() if v])} order(s)")
