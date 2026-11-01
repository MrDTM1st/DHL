"""
Tracker store for the Region 2 emailer.

Logs every order the tool emails (order numbers, who, product code, which Synergy
upload it came from, when), and a refresh that checks Outlook to fill in whether a
reply has come back and whether the Send-out brief is ready.

    python tracker.py             # print the current tracker
    python tracker.py refresh     # update reply / send-off status from Outlook
"""
import os, json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "tracker.json")
DHL_SMTP = "delali.opoku@dhl.com"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"records": []}


def save(d):
    # write-then-swap: a reader that catches a half-written file used to see
    # an empty tracker, and a save after that wiped it
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, PATH)


def _key(orders, date):
    return "-".join(orders) + "|" + str(date)


# Orders removed from the tracker because YOU booked them stay removed. The
# enrol sweeps (by-hand recovery, collection requests) re-discover the same
# Sent Items every run, and without this memory they re-added booked orders
# each check just for the sweep to remove them again - endless churn, and a
# booked_removed metric that fired every tick.
DROPS = os.path.join(HERE, "_booked_drops.json")


def booked_drops():
    try:
        with open(DROPS, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def remember_drops(orders):
    s = booked_drops() | {str(o) for o in orders}
    with open(DROPS, "w", encoding="utf-8") as f:
        json.dump(sorted(s)[-400:], f)


def log(orders, to, name, product_codes, materials, site, postcode, delivery_date, source,
        status="drafted", emailed_at=None, only_if_new=False, kind="delivery", orig_entryid=None,
        worksite="", collection_site="", collection_pc="", collections=None, po=None):
    """Record an email. If the same order+date is already tracked it counts as a
    re-send (chase) - UNLESS only_if_new, when the existing record is left
    untouched (used when enrolling emails you sent by hand, so they don't get a
    phantom chase bump). emailed_at overrides the send timestamp so a by-hand
    email is chased from when YOU actually sent it, not now. kind is 'delivery'
    (chased by rebuilding from the extract) or 'collection' (chased in-thread);
    orig_entryid points at the exact Sent item so a collection chase can reply on
    the same thread."""
    if only_if_new and any(str(o) in booked_drops() for o in orders):
        return   # booked and dropped - an enrol sweep must never resurrect it
    d = load()
    k = _key(orders, delivery_date)
    for r in d["records"]:
        if r["id"] == k:
            if po and not r.get("po"):
                r["po"] = dict(po)    # a later send or rebuild learnt the customer PO
                save(d)
            if only_if_new:
                return
            r["chases"] = r.get("chases", 0) + 1
            r["last_emailed_at"] = _now()
            r["status"] = status
            save(d)
            return
    when = emailed_at or _now()
    d["records"].append({
        "id": k, "orders": orders, "to": to, "name": name,
        "product_codes": product_codes, "materials": materials, "site": site, "postcode": postcode,
        "worksite": worksite, "collection_site": collection_site, "collection_pc": collection_pc,
        "collections": collections or ([{"site": collection_site, "pc": collection_pc}]
                                       if (collection_site or collection_pc) else []),
        "delivery_date": delivery_date, "source": source, "kind": kind, "orig_entryid": orig_entryid,
        "po": dict(po or {}),     # {order: customer PO} - quoted again on every chase
        "emailed_at": when, "last_emailed_at": when, "status": status,
        "chases": 0, "reply_at": None, "sendoff_ready": False,
    })
    save(d)


def escalated(orders, when=None):
    """The materials team was asked for another contact for these orders: their records stop showing the escalation
    as due (his rule 01/11: due after 4 working days without a reply). Returns how many were marked."""
    want = {str(o).strip() for o in orders or []}
    d = load()
    n = 0
    for r in d["records"]:
        if want & {str(o).strip() for o in r.get("orders") or []} and not r.get("escalated_at"):
            r["escalated_at"] = when or _now()
            n += 1
    if n:
        save(d)
    return n


def book(record_id):
    """Booked over the phone: the order is handled even though no email reply
    will ever arrive, so drop it from the tracker. Matched by record id.
    Returns how many records were removed (0 if the id wasn't found)."""
    rid = str(record_id).strip()
    d = load()
    before = len(d["records"])
    d["records"] = [r for r in d["records"] if r.get("id") != rid]
    n = before - len(d["records"])
    if n:
        save(d)
    return n


# A replied order (send-off brief ready) is ready to BOOK, not finished - his map, 31/10: purple until it is booked.
# It stays until a booking takes it off (the booked sweeps), and only leaves on its own once its delivery date is
# this many days gone, when it can be nothing but stale.
STALE_DAYS = 7


def _days_past(date):
    """How many days a dd/mm/yyyy delivery date is behind today - None when it is not a date."""
    try:
        return (datetime.now() - datetime.strptime(str(date or "").strip(), "%d/%m/%Y")).days
    except ValueError:
        return None


def drop_completed(d, keep_ids=()):
    """Remove replied orders whose delivery date is STALE_DAYS gone. keep_ids are never removed - the ones finished
    during this very check must survive to be saved. Mutates `d` in place; returns how many were removed."""
    before = len(d["records"])
    d["records"] = [r for r in d["records"]
                    if not (r.get("sendoff_ready") and r.get("id") not in keep_ids
                            and (_days_past(r.get("delivery_date")) or 0) > STALE_DAYS)]
    return before - len(d["records"])


def move_date(d, r, date, why=""):
    """The order's delivery moved to `date` (dd/mm/yyyy): the record takes the new date AND the id that goes with
    it, so the map shows one dot on the new day instead of a second beside the old. A record already on the new id
    (an earlier chase or send for the same orders and day) is folded into this one. The old date is kept in
    date_was. Returns True when the date changed."""
    date = str(date or "").strip()
    try:
        datetime.strptime(date, "%d/%m/%Y")
    except ValueError:
        return False
    if date == str(r.get("delivery_date") or "").strip():
        return False
    new_id = _key(r.get("orders") or [], date)
    for other in [o for o in d["records"] if o is not r and o.get("id") == new_id]:
        r["chases"] = max(r.get("chases", 0), other.get("chases", 0))
        d["records"].remove(other)
    r["date_was"] = r.get("delivery_date")
    r["date_moved_at"] = _now()
    if why:
        r["date_moved_by"] = why
    r["delivery_date"], r["id"] = date, new_id
    return True


# ---------- refresh from Outlook ----------
def _dhl(ns):
    for i in range(1, ns.Folders.Count + 1):
        if ns.Folders.Item(i).Name.lower() == DHL_SMTP:
            return ns.Folders.Item(i)


def _sub(f, name):
    if f is None:
        return None
    for i in range(1, f.Folders.Count + 1):
        c = f.Folders.Item(i)
        if c.Name.strip().lower() == name.strip().lower():
            return c


def _subjects(folder, limit=250):
    out = []
    if folder is None:
        return out
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        try:
            items.Sort("[LastModificationTime]", True)
        except Exception:
            pass
    n = 0
    for it in items:
        n += 1
        if n > limit:
            break
        try:
            out.append(str(it.Subject or ""))
        except Exception:
            pass
    return out


def refresh():
    import win32com.client
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    dhl = _dhl(ns)
    inbox = _sub(dhl, "Inbox")
    region2 = _sub(_sub(inbox, "Regions"), "Region 2")
    sendout = _sub(region2, "Send out") or _sub(region2, "Send Out")
    inbox_subjects = _subjects(inbox)
    sendout_subjects = _subjects(sendout)
    d = load()
    for r in d["records"]:
        orders = r["orders"]
        if not r.get("reply_at"):
            for s in inbox_subjects:
                if any(o in s for o in orders):
                    r["reply_at"] = _now()
                    break
        r["sendoff_ready"] = any(any(o in s for o in orders) for s in sendout_subjects)
    drop_completed(d)   # a send-off order stays until it is booked - only a stale one goes
    save(d)
    return d


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        data = refresh()
        print(f"Refreshed {len(data['records'])} record(s).")
    elif len(sys.argv) > 2 and sys.argv[1] == "book":
        n = book(sys.argv[2])
        print(f"Booked via call - removed {n} record(s).")
    else:
        print(json.dumps(load(), indent=2)[:2500])
