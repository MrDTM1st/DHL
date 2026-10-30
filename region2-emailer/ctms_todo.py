"""
What CTMS still owes - the desk's memory of it, so "execute on CTMS" knows exactly which orders to touch.

Every email the desk sends about an order leaves something to do in CTMS. His ask (30/10): "when we send off
emails, and chases and stuff, I want the dashboard to remember it. So then when I say execute on CTMS, you know
exactly what emails to update and what orders to update."

    the first ask, a chase      a note at the end of Special Instructions (" - Emailed DO 28/10",
                                " - Chased DO 30/10") - ctms_notes works these out of the tracker
    an escalation               " - Escalated DO 30/10" (his rule 30/10) - remembered when the email goes
    a site's reply              the order to update from it (times, location comments, services, vehicle)
    a booking / anything else   added by hand, or by the desk when it learns of one

The tracker's notes are worked out afresh each time; the rest live in _ctms_todo.json (gitignored) until done.
listing() puts them together for the dashboard's CTMS page ("To do on CTMS") and for the run.

    python ctms_todo.py                          the list, oldest first
    python ctms_todo.py add KIND ORDER "WHAT"    KIND: note | update | booking | other
                                                 (a note: --note " - Escalated DO 30/10")
    python ctms_todo.py done ID                  done - a note is also marked written for ctms_notes
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

import ctms_notes

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "_ctms_todo.json")
TRACKER = os.path.join(HERE, "tracker.json")
KINDS = ("note", "update", "booking", "other")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _id(*parts):
    return "t" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8]


def _bases(orders):
    """1234567-1-1 -> 1234567, order kept, no repeats."""
    return list(dict.fromkeys(str(o).split("-")[0].strip() for o in orders or [] if str(o).strip()))


def load(path=None):
    try:
        with open(path or STORE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("items"), list) else {"items": []}
    except (OSError, ValueError):
        return {"items": []}


def _save(d, path=None):
    path = path or STORE
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, path)


def _key(kind, orders, note, what):
    return kind, tuple(orders), note if kind == "note" else what


def add(kind, orders, what, note="", details=None, source="hand", path=None, when=None):
    """Remember one thing CTMS owes - never the same open thing twice. Returns the item."""
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    orders = _bases(orders)
    if not orders:
        raise ValueError("which order?")
    d = load(path)
    want = _key(kind, orders, note, what)
    for it in d["items"]:
        if not it.get("done_at") and _key(it["kind"], it["orders"], it.get("note"), it.get("what")) == want:
            return it
    it = {"id": _id(kind, orders, note, what, when or _now()), "kind": kind, "orders": orders,
          "ref": ctms_notes.first_line(orders[0]) if kind == "note" else "", "note": note, "what": what,
          "details": details or None, "source": source, "added": when or _now(), "done_at": None}
    d["items"].append(it)
    _save(d, path)
    return it


def escalated(orders, when=None, path=None):
    """An escalation email went (his rule 30/10): each order owes ' - Escalated DO dd/mm' at the end of its -1-1
    line's Special Instructions."""
    day = datetime.strptime(when, "%Y-%m-%d %H:%M") if when else datetime.now()
    note = f" - Escalated {ctms_notes.INITIALS} {day:%d/%m}"
    return [add("note", [o], f"Add '{note.strip(' -')}' to {ctms_notes.first_line(o)}'s Special Instructions",
                note=note, source="escalation", path=path, when=when) for o in _bases(orders)]


def replied(rec, path=None, when=None):
    """A site answered: the order is to be updated from the reply. Its parsed answers ride along, so the run has
    what it needs without reading the email again."""
    if rec.get("kind", "delivery") != "delivery" or not rec.get("orders"):
        return None
    who = rec.get("name") or rec.get("to") or "The site"
    day = str(rec.get("reply_at") or when or _now())[:10]
    try:
        day = datetime.strptime(day, "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        pass
    return add("update", rec["orders"], f"{who} replied {day} - update the order from it",
               details={"details": rec.get("details"), "missing": rec.get("missing"),
                        "site": rec.get("site"), "to": rec.get("to")},
               source="reply", path=path, when=when)


def _tracker_records(tracker_path=None):
    try:
        with open(tracker_path or TRACKER, encoding="utf-8") as f:
            t = json.load(f)
    except (OSError, ValueError):
        return []
    recs = t.get("records", t) if isinstance(t, dict) else t
    return list(recs.values()) if isinstance(recs, dict) else list(recs or [])


def listing(tracker_path=None, path=None, notes_done=None):
    """Everything CTMS still owes, oldest first: the tracker's Emailed/Chased notes and the remembered rest."""
    done = ctms_notes.load_done(notes_done)
    out = [{"id": _id("n", n["ref"], n["note"]), "kind": "note", "orders": [n["order"]], "ref": n["ref"],
            "note": n["note"], "what": f"Add '{n['note'].strip(' -')}' to {n['ref']}'s Special Instructions",
            "source": n["kind"], "added": n["date"]}
           for n in ctms_notes.owed(_tracker_records(tracker_path), done)]
    written = {(d.get("ref"), d.get("note")) for d in done}
    for it in load(path)["items"]:
        if it.get("done_at"):
            continue
        if it["kind"] == "note" and (it.get("ref"), it.get("note")) in written:
            continue                    # the note run has written it since
        out.append({k: it.get(k) for k in ("id", "kind", "orders", "ref", "note", "what", "source", "added",
                                            "details")})
    out.sort(key=lambda i: (str(i.get("added") or ""), i["id"]))
    return out


def done(item_id, path=None, tracker_path=None, notes_done=None):
    """Mark one done. A note is also marked written for ctms_notes, so it never comes back."""
    d = load(path)
    for it in d["items"]:
        if it["id"] == item_id and not it.get("done_at"):
            it["done_at"] = _now()
            _save(d, path)
            if it["kind"] == "note":
                ctms_notes.mark_done(it["ref"], it["note"], notes_done)
            return it
    for it in listing(tracker_path, path, notes_done):
        if it["id"] == item_id and it["kind"] == "note":
            ctms_notes.mark_done(it["ref"], it["note"], notes_done)
            return it
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="What CTMS still owes.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("add")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("order")
    p.add_argument("what")
    p.add_argument("--note", default="")
    sub.add_parser("done").add_argument("id")
    p = sub.add_parser("list")
    p.add_argument("--tracker")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.cmd == "add":
        it = add(a.kind, [a.order], a.what, note=a.note)
        print(f"Remembered {it['id']}: {it['kind']} {'/'.join(it['orders'])} - {it['what']}")
        return 0
    if a.cmd == "done":
        it = done(a.id)
        print(f"Done: {it['what']}" if it else f"No open item {a.id}.")
        return 0 if it else 1
    items = listing(getattr(a, "tracker", None))
    print(f"{len(items)} thing(s) to do on CTMS:")
    for it in items:
        print(f"  {it['id']}  {it['kind']:<8} {'/'.join(it['orders']):<10} {it['what']}  ({it.get('added')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
