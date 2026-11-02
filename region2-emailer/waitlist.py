"""
Wait-list store for the Region 2 emailer.

Region 2 orders whose delivery date is further out than the lead time (config
waitlist.lead_days, default 21 - his rule 01/11: "start emailing people for
orders 3 weeks ahead or less") are held here instead of being emailed straight
away, then auto-SENT once delivery comes within the window. The store is a plain
JSON file on the always-on home PC, so it survives restarts - an order placed on
the wait list cannot be forgotten.

Design rules that keep it reliable:
  * add() is idempotent - the same order+date is never wait-listed twice.
  * an entry carries the FULL email payload, so it can still be sent weeks later
    even after the source spreadsheet has aged out of the mailbox scan.
  * due() is catch-up safe: if the release didn't run for a few days it still
    returns everything now within the window.
  * overdue() surfaces anything whose delivery date passed while still waiting -
    that should never happen, and if it does it must be shouted about, not hidden.

    python waitlist.py            # print the wait list
    python waitlist.py due        # show what is due to send now
"""
import os, json, re
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "waitlist.json")

try:
    _CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    LEAD_DAYS = int(_CFG.get("waitlist", {}).get("lead_days", 21))
except Exception:
    LEAD_DAYS = 21


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"entries": []}


def save(d):
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


# An address a mail can reach. A sheet's "Danny Smith email: dannysmith.co.uk" (no @) or "john@networkrail" can't.
_ADDRESS = r"[^@\s;,]+@[^@\s;,.]+(?:\.[^@\s;,.]+)+"


def has_address(to):
    return bool(re.search(_ADDRESS, str(to or "")))


def _id(orders, delivery_date):
    return "-".join(str(o).strip() for o in orders) + "|" + str(delivery_date)


def parse_date(dd):
    """'dd/mm/yyyy' -> date, or None if it can't be read."""
    try:
        return datetime.strptime(str(dd).strip()[:10], "%d/%m/%Y").date()
    except Exception:
        return None


def days_until(dd, today=None):
    d = parse_date(dd)
    if d is None:
        return None
    return (d - (today or date.today())).days


def add(email):
    """Put an email payload on the wait list. `email` is the dict build_drafts
    produces (to, subject, body, html, orders, date, ...). Idempotent: returns
    True if newly added, False if it was already waiting or already released."""
    d = load()
    k = _id(email.get("orders", []), email.get("date"))
    for e in d["entries"]:
        if e["id"] == k:
            if e.get("status") == "waiting" and not has_address(e.get("to")) and has_address(email.get("to")):
                e["to"] = email["to"]                # a later sheet has it right
                save(d)
            return False
    d["entries"].append({
        "id": k,
        "orders": email.get("orders", []),
        "po": email.get("po", {}),               # customer PO, carried to the tracker on release
        "to": email.get("to", ""),
        "contact_said": email.get("contact_said", ""),   # the sheet's own words, for when they hold no address
        "cc": email.get("cc", ""),
        "name": email.get("name", ""),
        "subject": email.get("subject", ""),
        "body": email.get("body", ""),
        "html": email.get("html", ""),
        "date": email.get("date", ""),          # delivery date, dd/mm/yyyy
        "site": email.get("site", ""),
        "worksite": email.get("worksite", ""),
        # collection rides the wait-list too - it was dropped here, which is
        # why every wait-list-released order landed on the tracker with no
        # collection location at all
        "collections": email.get("collections", []),
        "collection_site": email.get("collection_site", ""),
        "collection_pc": email.get("collection_pc", ""),
        "postcode": email.get("postcode", ""),
        "product_codes": email.get("product_codes", []),
        "materials": email.get("materials", ""),
        "source": email.get("source", ""),
        "status": "waiting",                     # waiting | sent | missed
        "added_at": _now(),
        "sent_at": None,
    })
    save(d)
    return True


def waiting(d=None):
    d = d or load()
    return [e for e in d["entries"] if e.get("status") == "waiting"]


def due(lead_days=None, today=None):
    """Waiting entries now within the lead window and not past - ready to send.
    Catch-up safe: anything at/inside the window is returned, however long ago
    it became due."""
    lead = LEAD_DAYS if lead_days is None else lead_days
    out = []
    for e in waiting():
        n = days_until(e["date"], today)
        if n is not None and 0 <= n <= lead:
            out.append(e)
    return out


def no_address(d=None):
    """Waiting entries no email can go to, soonest first - the sheet's address is mistyped or missing. The release can't
    send them, and when that only reached its log an order sat here unasked for from 21/10 to 02/11 (6055827)."""
    return sorted((e for e in waiting(d) if not has_address(e.get("to"))),
                  key=lambda e: parse_date(e.get("date")) or date.max)


def due_or_stuck(lead_days=None, today=None):
    """What a release looks at: everything due, and everything no email can go to however far off it is. Those can't be
    sent, but they close like any other once the order has been dealt with, by hand or under another email."""
    out = due(lead_days, today)
    seen = {e["id"] for e in out}
    for e in no_address():
        n = days_until(e["date"], today)
        if e["id"] not in seen and n is not None and n >= 0:
            out.append(e)
    return out


def set_address(entry_id, to):
    """The right address for a waiting entry, as he typed it. False when it isn't one address or the entry isn't waiting."""
    to = str(to or "").strip()
    if not re.fullmatch(_ADDRESS, to):
        return False
    d = load()
    for e in d["entries"]:
        if e["id"] == entry_id and e.get("status") == "waiting":
            e["to"], e["address_typed_at"] = to, _now()
            save(d)
            return True
    return False


def dealt_with(entry_id):
    """He has seen to an order no email could go to some other way: it comes off the list. Never one with an address -
    those have the release's own checks."""
    for e in no_address():
        if e["id"] == entry_id:
            return mark(entry_id, "sent", note="no address on the sheet - you dealt with it yourself")
    return False


def overdue(today=None):
    """Waiting entries whose delivery date has already passed - a reliability
    failure that must be alerted, never silently dropped."""
    out = []
    for e in waiting():
        n = days_until(e["date"], today)
        if n is not None and n < 0:
            out.append(e)
    return out


def mark(entry_id, status, note=None):
    d = load()
    for e in d["entries"]:
        if e["id"] == entry_id:
            e["status"] = status
            if status == "sent":
                e["sent_at"] = _now()
            if note:
                e["note"] = note
            save(d)
            return True
    return False


def _fmt(e, today=None):
    n = days_until(e["date"], today)
    when = f"{n}d" if n is not None else "?"
    return f"[{e['status']:7}] {' / '.join(e['orders'])} | {e['site']} {e['postcode']} | deliver {e['date']} ({when}) | to {e['to']}"


if __name__ == "__main__":
    import sys
    d = load()
    if len(sys.argv) > 1 and sys.argv[1] == "due":
        print(f"Lead window: {LEAD_DAYS} days. Due to send now:")
        for e in due():
            print("  " + _fmt(e))
        od = overdue()
        if od:
            print("\n!! OVERDUE (delivery date already passed while waiting):")
            for e in od:
                print("  " + _fmt(e))
    else:
        w = waiting(d)
        print(f"Wait list: {len(d['entries'])} entr(ies), {len(w)} still waiting (lead {LEAD_DAYS}d).")
        for e in sorted(d["entries"], key=lambda x: parse_date(x["date"]) or date.max):
            print("  " + _fmt(e))
