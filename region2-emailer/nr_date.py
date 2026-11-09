"""
The Network Rail team email when a site asks for a different delivery date than the one we offered.

His rule (09/11/2026). We email a site: the order is available on e.g. the 20th.
- The site sends details for an EARLIER day (the 7th, anything before the 20th): the Network Rail team that sent the
  order down is asked whether that is allowed and whether the stock will be ready by then - and the order is NOT moved
  until they say yes. 6055887 went wrong on 09/11 because it was brought forward without anyone confirming the
  goods were ready (the supplier turned the driver away).
- The site sends details for a LATER day in a different week (a different week commencing): the team is told the
  order now delivers on that day instead, so nobody chases a delivery that "didn't happen" when it was moved.
  A later day in the SAME week is just a move - nobody needs telling.

What lives on the tracker record, as r["nr_date"] (the dashboard shows it on the order's panel and its own card):
    kind      "earlier" | "later"
    offered   the day we offered (dd/mm/yyyy)        asked   the day the site wants
    state     "to_send"  drafted, waiting for his Send on the dashboard
              "sent"     gone to Network Rail (for "earlier": waiting for their answer)
              "allowed" / "not_allowed"   their answer (earlier only), pressed by him
              "dismissed"  he said no email is needed
    team, to, cc, subject, message      the email, which he can edit before Send
    reply_eid  the site's own email, forwarded underneath so the team sees the whole trail

Nothing is sent from here by itself: the email goes when he presses Send on the dashboard (agent action "nr_date").
Never copies DHL Road. No em dashes in anything written.

    python nr_date.py send <record id> <json file with to/cc/subject/message>
    python nr_date.py answer <record id> yes|no
    python nr_date.py dismiss <record id>
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
TEAMS_FILE = os.path.join(HERE, "_nr_teams.json")   # home-only additions (people's own addresses), gitignored

# The team that sends each kind of material down to us, from the real threads in the mailbox. Team mailboxes only
# here (the repo is public); a named person who is always copied goes in _nr_teams.json as {"sleepers": {"add":
# ["..."]}}. S&C and anything else has no team on the list: the email is drafted with nobody in To and the card
# asks him who it goes to, rather than guessing.
TEAMS = {
    "sleepers": {"name": "SCO Sleepers & Troughing",
                 "to": ["SCOSleepers&Troughing@networkrail.co.uk", "SleeperContractManagementTeam@networkrail.co.uk"]},
    "rails": {"name": "Steel Materials", "to": ["SteelMaterials@networkrail.co.uk"]},
    "ballast": {"name": "Track Aggregates", "to": ["Track.Aggregates@networkrail.co.uk"]},
}
KIND_OF = (
    (re.compile(r"sleeper|bearer|trough", re.I), "sleepers"),
    (re.compile(r"\brails?\b", re.I), "rails"),
    (re.compile(r"ballast|aggregate|chipping|granite|stone", re.I), "ballast"),
)
NEVER = re.compile(r"dhlroad@", re.I)      # his rule: never copy DHL Road on these

OPEN = ("to_send", "sent")                 # still something for him (or Network Rail) to do


def _d(s):
    try:
        return datetime.strptime(str(s or "").strip(), "%d/%m/%Y")
    except ValueError:
        return None


def week_of(day):
    """The Monday of the week a day is in (the week commencing)."""
    return (day - timedelta(days=day.weekday())).date()


def classify(offered, asked):
    """"earlier" when the site asks before the day we offered, "later" when it asks for a day in a later week,
    None otherwise (the same day, a later day in the same week, or either not a date)."""
    o, a = _d(offered), _d(asked)
    if not (o and a):
        return None
    if a < o:
        return "earlier"
    if week_of(a) > week_of(o):
        return "later"
    return None


def _material_kind(r):
    text = " ".join([str(r.get("materials") or "")] + [str(x) for x in r.get("product_types") or []])
    if re.search(r"s&c|switch|crossing", text, re.I):
        return None
    for rx, k in KIND_OF:
        if rx.search(text):
            return k
    return None


def _extra():
    try:
        with open(TEAMS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def team_for(r):
    """{"key", "name", "to": [...]} for the order's Network Rail team, or None when nobody is known."""
    k = _material_kind(r)
    if not k:
        return None
    t = TEAMS[k]
    to = list(t["to"]) + [a for a in (_extra().get(k) or {}).get("add") or [] if a not in t["to"]]
    return {"key": k, "name": t["name"], "to": [a for a in to if not NEVER.search(a)]}


def _addrs(v):
    parts = v if isinstance(v, (list, tuple)) else re.split(r"[;,]", str(v or ""))
    return "; ".join(p.strip() for p in parts if str(p).strip() and not NEVER.search(str(p)))


def _long(day):
    d = _d(day)
    return d.strftime("%A %d/%m/%Y") if d else str(day or "")


def _short(day):
    d = _d(day)
    return d.strftime("%d/%m") if d else str(day or "")


def _what(r):
    where = ", ".join(x for x in [r.get("worksite") or r.get("site"), r.get("postcode")] if x)
    bits = [str(r.get("materials") or "").strip(), ("to " + where) if where else ""]
    return " ".join(b for b in bits if b)


def draft(r, kind, offered, asked):
    """(subject, message) - his plain wording, no em dashes; the signature is added when it is sent."""
    orders = " / ".join(r.get("orders") or [])
    what = _what(r)
    about = f"order {orders}" + (f" ({what})" if what else "")
    if kind == "earlier":
        subject = f"{orders} - site asking for an earlier delivery ({_short(asked)} instead of {_short(offered)})"
        message = "\n".join([
            "Hi all,", "",
            f"The site has come back on {about} asking for delivery on {_long(asked)}. "
            f"We have it down as available from {_long(offered)}, so this is earlier than the date it was sent "
            "down as.", "",
            f"Please could you confirm whether delivering on {_short(asked)} is allowed, and whether the stock will "
            "be ready for collection in time? I will keep the order on "
            f"{_short(offered)} until I hear back from you.", "",
            "The site's email is below."])
    else:
        subject = f"{orders} - delivery moved to {_short(asked)} (was {_short(offered)})"
        message = "\n".join([
            "Hi all,", "",
            f"Just to let you know, the site on {about} has asked for delivery on {_long(asked)} instead of "
            f"{_long(offered)}, when it was available. The delivery is now planned for {_short(asked)}, so it "
            f"will not be going on {_short(offered)}.", "",
            "The site's email is below."])
    return subject, message


def on_new_date(d, r, new, why, reply_eid=None):
    """The one place a site's date (by reply, by his confirm of a parsed date, by phone) lands on a delivery record.
    Earlier than offered: the order stays put and the "is this allowed" email is drafted. A later week: the order
    moves and the "now delivering on X" notice is drafted. Anything else: it just moves. Returns True when the
    order's date changed. `d` is the loaded tracker (the caller saves it)."""
    import tracker
    new = str(new or "").strip()
    if not _d(new) or r.get("kind", "delivery") != "delivery":
        return tracker.move_date(d, r, new, why) if _d(new) else False
    offered = str(r.get("delivery_date") or "").strip()
    cur = r.get("nr_date") or {}
    if cur.get("kind") == "earlier" and cur.get("asked") == new:
        if cur.get("state") == "allowed":
            return tracker.move_date(d, r, new, why)
        if cur.get("state") in OPEN or cur.get("state") == "not_allowed":
            return False        # already asked (or refused) for this very day: nothing new
    kind = classify(offered, new)
    if kind is None:
        return tracker.move_date(d, r, new, why)
    if cur.get("kind") == kind and cur.get("asked") == new and cur.get("offered") == offered:
        return kind == "later" and tracker.move_date(d, r, new, why)
    team = team_for(r)
    subject, message = draft(r, kind, offered, new)
    nd = {"kind": kind, "offered": offered, "asked": new, "why": why, "at": tracker._now(),
          "state": "to_send", "team": team["name"] if team else "", "to": _addrs(team["to"]) if team else "",
          "cc": "", "subject": subject, "message": message,
          "reply_eid": str(reply_eid or "") or str(r.get("orig_entryid") or "")}
    if cur:
        nd["prev"] = {k: cur.get(k) for k in ("kind", "offered", "asked", "state", "at")}
    r["nr_date"] = nd
    try:
        import metrics
        metrics.log("nr_date_" + kind, orders=r.get("orders", []), offered=offered, asked=new)
    except Exception:
        pass
    if kind == "later":
        return tracker.move_date(d, r, new, why)
    return False


def held(r):
    """The day an order is held on while Network Rail is asked about an earlier one - the CTMS run and the map go by
    this. None when nothing is held."""
    nd = (r or {}).get("nr_date") or {}
    if nd.get("kind") == "earlier" and nd.get("state") in OPEN:
        return nd.get("offered") or r.get("delivery_date")
    return None


def waiting(records):
    """The records with a Network Rail date email still to send, or an earlier date still to be answered."""
    return [r for r in records if ((r.get("nr_date") or {}).get("state") in OPEN)]


# ---------- the dashboard's buttons (agent action "nr_date") ----------
def _find(d, rid):
    for r in d["records"]:
        if r.get("id") == rid:
            return r
    return None


def _forward_send(nd, to, cc, subject, message):
    """Forward the site's email (the whole trail underneath) to the team, from the DHL account. Falls back to a new
    email when the site's email is gone. Returns (ok, said)."""
    import win32com.client
    import build_drafts as bd
    import send_order
    from mail_ops import insert_top
    ns = bd.get_ns()
    acct = send_order.dhl_account(ns)
    if acct is None:
        return False, "The DHL account was not found in Outlook - nothing sent."
    m = None
    if nd.get("reply_eid"):
        try:
            store = bd.dhl_store(ns)
            src = ns.GetItemFromID(nd["reply_eid"], store.StoreID)
            m = src.Forward()
            m.HTMLBody = insert_top(m.HTMLBody, bd.html_from_message(message))
        except Exception:
            m = None
    if m is None:
        m = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
        m.HTMLBody = bd.html_from_message(message)
    to, cc, _ = bd.clean_to_cc(to, cc)
    m.To = to
    m.CC = cc or ""
    m.Subject = subject
    bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        return False, "Could not send from the DHL account - nothing sent."
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    return True, f"sent to {to}"


def send(rid, edits, sender=None):
    """His Send: the (edited) email goes, and the record says so. sender(nd, to, cc, subject, message) -> (ok,
    said) is the Outlook part (tests pass a stand-in)."""
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd:
        return {"ok": False, "said": "That order has no Network Rail email waiting - nothing sent."}
    if nd.get("state") != "to_send":
        return {"ok": False, "said": f"Already {nd.get('state', '').replace('_', ' ')} - nothing sent."}
    edits = edits or {}
    to = _addrs(edits.get("to", nd.get("to")))
    cc = _addrs(edits.get("cc", nd.get("cc")))
    subject = str(edits.get("subject") or nd.get("subject") or "").strip()
    message = str(edits.get("message") or nd.get("message") or "").replace("—", "-").replace("–", "-")
    if not to:
        return {"ok": False, "said": "Who is the Network Rail team for this order? Type their address in To."}
    ok, said = (sender or _forward_send)(nd, to, cc, subject, message)
    if not ok:
        return {"ok": False, "said": said}
    nd.update(state="sent", sent_at=tracker._now(), to=to, cc=cc, subject=subject, message=message)
    tracker.save(d)
    orders = " / ".join(r.get("orders") or [])
    return {"ok": True, "said": f"{orders}: Network Rail emailed ({said})"
            + (f" - the order stays on {_short(nd['offered'])} until they say yes." if nd["kind"] == "earlier" else ".")}


def answer(rid, yes):
    """Network Rail's answer to an earlier date, as he presses it. Yes: the order moves to the site's day. No: it
    stays on the day we offered, and the CTMS update types that day (the parsed reply's date is set back to it)."""
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd or nd.get("kind") != "earlier" or nd.get("state") not in OPEN:
        return {"ok": False, "said": "That order has no earlier date waiting on Network Rail."}
    orders = " / ".join(r.get("orders") or [])
    nd["answered_at"] = tracker._now()
    if yes:
        nd["state"] = "allowed"
        moved = tracker.move_date(d, r, nd["asked"], "Network Rail's OK")
        tracker.save(d)
        return {"ok": True, "said": f"{orders}: allowed - " + (f"moved to {_short(nd['asked'])}." if moved
                                                               else f"it is on {_short(nd['asked'])}.")}
    nd["state"] = "not_allowed"
    cell = (r.get("details") or {}).get("date")
    if isinstance(cell, dict):
        cell["asked"] = cell.get("value")
        cell["value"] = nd["offered"]
    tracker.save(d)
    return {"ok": True, "said": f"{orders}: not allowed - it stays on {_short(nd['offered'])}. Let the site know."}


def dismiss(rid):
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd or nd.get("state") != "to_send":
        return {"ok": False, "said": "Nothing to dismiss on that order."}
    nd.update(state="dismissed", answered_at=tracker._now())
    if nd.get("kind") == "earlier":       # no email, so no hold: the site's day stands as any other reply's
        tracker.move_date(d, r, nd["asked"], "the site's reply")
    tracker.save(d)
    return {"ok": True, "said": f"{' / '.join(r.get('orders') or [])}: no Network Rail email."}


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(argv) < 3 or argv[1] not in ("send", "answer", "dismiss"):
        print(__doc__.strip().splitlines()[-3].strip())
        return 2
    import outlook_gate as gate
    if gate.named_lock("phase2_tracker", wait=30) is None:      # a reply check or chase holds the tracker
        out = {"ok": False, "said": "Not done - the reply check is updating the tracker; press it again in a minute."}
    elif argv[1] == "send":
        edits = {}
        if len(argv) > 3:
            with open(argv[3], encoding="utf-8") as f:
                edits = json.load(f)
        out = send(argv[2], edits if isinstance(edits, dict) else {})
    elif argv[1] == "answer":
        out = answer(argv[2], len(argv) > 3 and argv[3].lower() in ("yes", "y", "allowed", "1", "true"))
    else:
        out = dismiss(argv[2])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
