"""
What CTMS says about the map's orders, put on the map (01/11).

The work PC's bridge looks every order on the map up in CTMS (work_pc/ctms_orders.py) and the dashboard hands what
it found to the home PC as a "ctms_orders" job. His rules decide what it means:

  * booked: a delivery with no line left UNSCHEDULED - "if the trip's already been scheduled, it's already been
    booked in and dealt with" (29/10), and a cancelled or aborted line is dealt with too. It comes off the map and
    the tracker, remembered so no sweep brings it back - the same as a "this order has been arranged with" email
  * the date: a delivery whose day CTMS no longer has, every open line of the order now on one other day, moves to
    that day (tracker.move_date) - the dashboard follows CTMS, unless a site's reply moved it and CTMS is still to be
    updated from that reply
  * ready: a Veh Type filled on its open line - "if there's a vehicle type in there, it already means that we've
    got all the details for it and we just need to book it in" (30/10) - for details that came by phone
  * the weight: its open lines' weights off their cards, added up - the map decides rigid or artic from it (his
    "if you read how much it weighs on the CTMS", 01/11)

An order CTMS does not know (not imported yet, a typo), or one whose open lines are on several other days, is left
as it is. Runs as its own process under the tracker's lock, so a reply check saving at the same moment can never
put back what this took off.

    python ctms_sync.py apply FILE.json      # FILE: the bridge's answer
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN = "UNSCHEDULED"


def _day(v):
    """dd/mm/yyyy from CTMS's "dd/mm/yy HH:MM"."""
    s = str(v or "").strip()
    try:
        return datetime.strptime(s[:8], "%d/%m/%y").strftime("%d/%m/%Y")
    except ValueError:
        return ""


def judge(lines, date):
    """What one delivery's lines in CTMS say: ("booked", None), ("moved", new date), ("open", None), or (None, None)
    when there is no telling."""
    if not lines:
        return None, None
    mine = [ln for ln in lines if _day(ln.get("deliver_by")) == date]
    open_ = [ln for ln in lines if ln.get("status") == OPEN]
    if mine:
        return ("open", None) if any(ln.get("status") == OPEN for ln in mine) else ("booked", None)
    if not open_:
        return "booked", None                   # every line of the order is scheduled, cancelled or done
    days = {_day(ln.get("deliver_by")) for ln in open_}
    if len(days) == 1 and "" not in days:
        return "moved", days.pop()
    return None, None


def plan(found, records, jobs=()):
    """What to change, from the bridge's answer `found` ({"ref|date": {"lines": [...], "veh": {ref: bool},
    "weight": {ref: kg}}}): {"booked": [record ids], "moved": [(record id, new date)], "veh": {record id: bool},
    "weight": {record id: {"kg", "lines"}}, "jobs": [job ids booked], "unknown": [orders CTMS does not know]}.
    `jobs`: the map's ad hocs and pins, booked or left alone."""
    out = {"booked": [], "moved": [], "veh": {}, "weight": {}, "jobs": [], "unknown": [], "looked": []}
    for r in records:
        if r.get("kind") == "collection" or not r.get("orders"):
            continue
        date = str(r.get("delivery_date") or "").strip()
        got = [found[k] for k in (f"{o}|{date}" for o in r["orders"]) if k in found]
        if not got:
            continue                            # not looked up this time
        out["looked"].append(r["id"])
        lines = [ln for g in got for ln in g.get("lines") or []]
        if not lines:
            out["unknown"].extend(str(o) for o in r["orders"])
            continue
        what, new = judge(lines, date)
        if what == "booked":
            out["booked"].append(r["id"])
            continue
        vehs = [v for g in got for v in (g.get("veh") or {}).values()]
        # a site's reply moved it and CTMS hasn't been updated from that reply yet: the reply's day stands, or the look-up
        # would put the order back on the day the site has just changed
        if what == "moved" and (any(vehs) or r.get("date_moved_by") != "the site's reply"):
            out["moved"].append((r["id"], new))
        if vehs:
            out["veh"][r["id"]] = any(vehs)
        kgs = {ref: kg for g in got for ref, kg in (g.get("weight") or {}).items()}
        if kgs:
            out["weight"][r["id"]] = {"kg": round(sum(kgs.values()), 2), "lines": kgs}
    for j in jobs:
        date = str(j.get("delivery_date") or "").strip()
        got = [found[k] for k in (f"{o}|{date}" for o in j.get("orders") or []) if k in found]
        lines = [ln for g in got for ln in g.get("lines") or []]
        if lines and not any(ln.get("status") == OPEN for ln in lines):
            out["jobs"].append(j.get("id"))
    return out


def todo_done(found, items):
    """The CTMS to-do's "update the order from the reply" items CTMS shows are done (his ask 01/11: "you didn't update
    the to-do list"): the order's open line has its Veh Type filled - his rule 30/10, the details are in - or no line
    is left UNSCHEDULED at all (booked, or cancelled). Their ids."""
    out = []
    for it in items:
        if it.get("kind") != "update" or it.get("done_at"):
            continue
        got = [v for k, v in found.items() for o in it.get("orders") or [] if k.split("|")[0] == str(o)]
        lines = [ln for g in got for ln in g.get("lines") or []]
        if not lines:
            continue
        if not any(ln.get("status") == OPEN for ln in lines) or any(
                v for g in got for v in (g.get("veh") or {}).values()):
            out.append(it["id"])
    return out


def apply(found, at=""):
    """Put the plan on the tracker, under its lock. Returns the plan with what was done."""
    import outlook_gate as gate
    import tracker
    if gate.named_lock("phase2_tracker", wait=60) is None:
        raise RuntimeError("a reply check is still writing the tracker - look CTMS up again in a minute")
    d = tracker.load()
    jobs = []
    for name in ("_adhocs.json", "_pins.json"):
        try:
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                jobs += [j for j in json.load(f) if isinstance(j, dict)]
        except (OSError, ValueError):
            pass
    p = plan(found, d["records"], jobs)
    by_id = {r["id"]: r for r in d["records"]}
    gone = [by_id[i] for i in p["booked"] if i in by_id]
    d["records"] = [r for r in d["records"] if r["id"] not in set(p["booked"])]
    for rid in p["looked"]:
        if rid in by_id:
            by_id[rid]["ctms_at"] = at          # when CTMS last said something about it
    for rid, filled in p["veh"].items():
        if rid in by_id:
            by_id[rid]["ctms_veh"] = filled
    for rid, w in p["weight"].items():
        if rid in by_id:
            by_id[rid]["ctms_weight"], by_id[rid]["ctms_weight_lines"] = w["kg"], w["lines"]
    for rid, new in p["moved"]:                 # last: a move changes the record's id
        if rid in by_id and any(r is by_id[rid] for r in d["records"]):
            tracker.move_date(d, by_id[rid], new, "CTMS")
    tracker.save(d)
    if gone:
        tracker.remember_drops(sorted({str(o) for r in gone for o in r.get("orders") or []}))
    p["booked_orders"] = [" / ".join(r.get("orders") or []) for r in gone]
    import ctms_todo
    p["todo_done"] = [it["what"] for it in (ctms_todo.done(i) for i in todo_done(found, ctms_todo.load()["items"]))
                      if it]
    return p


def main(argv):
    if len(argv) != 3 or argv[1] != "apply":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    with open(argv[2], encoding="utf-8") as f:
        data = json.load(f)
    p = apply(data.get("orders") or {}, str(data.get("at") or ""))
    print(json.dumps({"booked": p["booked_orders"], "moved": p["moved"], "veh": p["veh"],
                      "weight": {k: v["kg"] for k, v in p["weight"].items()}, "jobs": p["jobs"],
                      "unknown": sorted(set(p["unknown"])), "todo_done": p["todo_done"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
