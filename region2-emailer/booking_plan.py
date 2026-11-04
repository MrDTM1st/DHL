"""
A booking plan - what goes on which vehicle, and what CTMS needs to book each one - worked out on the home PC
before anything in CTMS is touched, so a booking run only ever carries out a plan Delali has seen.

His loading rules (31/10/2026):
  - fill each vehicle to its maximum before starting the next - never part-loads spread over several vehicles;
  - different materials keep their own lines, even of one kind: two sleeper types of 50 are two lines of 50 on the
    manifest, never one line of 100;
  - whether the vehicle needs a HIAB changes its maximum weight.
A Moffett job goes "only for the hauliers who have Moffats" (31/10/2026) - the contact list's Moffett column - and
its maximum is asked until he gives it. A vehicle carries one pick-up to one drop on one day, so lines are grouped by
those first. Different materials
share a vehicle to fill it - "you can split some of the materials to go onto other vehicles to make the capacity
full" - except rails of different types: "you can't put 56 E1s with 60 E2s" (31/10/2026). A site's own limit -
"X84 EG47s and EG47 GR2s on each lorry" - rides as a per-vehicle count beside the weight.

    python booking_plan.py JOB.json          the plan, as he reads it before the booking

JOB.json: {"job": "...", "booked": "dd/mm/yyyy HH:MM" (default now),
           "vehicle": {"kind": "artic", "hiab": false, "moffett": false, "max_kg": 26000, "max_units": 84},
           "book": {"carrier": "...", "trailer": "...", "amount": 0},
           "lines": [{"ref": "...", "material": "...", "qty": 77, "kg_each": 300,
                      "collect": "...", "deliver": "dd/mm/yyyy HH:MM",
                      "rail": "60E2" (a rail line's type, when its material doesn't say)}, ...]}
"""
import json
import re
import sys
from datetime import datetime

import hauliers

# The most a vehicle carries, kg, as Delali has given it, by what it offloads with - a HIAB's crane takes weight off,
# and so does a Moffett carried on the back. One that is not here is a question for him: the plan never guesses a
# maximum.
MAX_KG = {
    ("artic", "hiab"): 20280,   # "an artic HIAB with NOC, for what I know, is 20,280 kilos" (31/10/2026)
    ("artic", ""): 25500,       # "the max load without a HIAB is 25,500" (31/10/2026)
    ("rigid", "hiab"): 10000,   # the NOC rigids took 10 x 1 t bags each (30/10/2026)
    ("tipper", ""): 21000,      # NR_R_TIP26_8 "has a max load of 21" (04/11/2026)
}
KIT = {"hiab": "a HIAB", "moffett": "a Moffett"}


def kit(veh):
    """What the vehicle offloads with: "moffett", "hiab", or "" for neither."""
    return "moffett" if veh.get("moffett") else "hiab" if veh.get("hiab") else ""


def max_kg(kind, offload=""):
    return MAX_KG.get((str(kind or "").strip().lower(), offload or ""))


def moffett_hauliers(directory=None):
    """The only hauliers a Moffett job goes to: the contact list's Moffett column ticked, never a do-not-use one -
    our own fleet, then tier 1, then tier 2."""
    d = hauliers.load() if directory is None else directory
    able = [h for h in d.get("hauliers", []) if "Moffett" in h.get("caps", []) and not h.get("do_not_use")]
    return sorted(able, key=lambda h: (hauliers.rank_of(h), bool(h.get("rarely")), h["name"].lower()))


def _code(carrier):
    """A carrier code to compare by: CTMS books a carrier's _DH version ("ABCHAULAGE_DH") where the contact list has
    its plain id ("ABC_HAULAGE"), with or without the underscores."""
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"_DH$", "", str(carrier or "").strip().upper()))


_RAIL = re.compile(r"\brails?\b", re.I)
# A sleeper's or a fitting's line can name the rail it is for - "GUARD RAIL SLEEPER", "BASEPLATE FOR INCLINED CEN56
# RAIL", "EG47 GR2 guard rail + pad" - and is still not a rail (as the map reads them, cloud/web/src/lib/orders.js).
_NOT_A_RAIL = re.compile(r"sleeper|bearer|trough|guard\s*rail|\bpads?\b|clip|chair|plate|fasten|anchor|\bcomp", re.I)
_PROFILE = re.compile(r"(?<!\d)(\d{2}\s?E\s?\d|\d{3}\s?A)(?!\w)", re.I)


def rail_type(ln):
    """A rail line's type for loading - its profile, "56E1", "60E2" - or "?" when its words don't say (a "rail" on
    the job's line says it outright). "" for anything that isn't a rail, sleepers included."""
    if ln.get("rail"):
        return re.sub(r"\s", "", str(ln["rail"])).upper()
    text = f"{ln.get('material', '')} {ln.get('product', '')}".replace("_", " ")     # SHORT_RAIL is a rail
    if not _RAIL.search(text) or _NOT_A_RAIL.search(text):
        return ""
    m = _PROFILE.search(text)
    return re.sub(r"\s", "", m.group(1)).upper() if m else "?"


def load_plan(lines, limit_kg=None, limit_units=None):
    """[[(line, qty), ...] per vehicle]. Lines are taken in order and each vehicle is filled to its limit before
    the next; a line that does not fit what is left goes on in part, the rest on the next vehicle - its own line on
    both. Materials mix to fill a vehicle, but two types of rail never share one: each type has vehicles of its own,
    the last of them topped up with what isn't a rail before the next type starts. Raises when there is no limit at
    all, or when one unit outweighs a whole vehicle."""
    if not limit_kg and not limit_units:
        raise ValueError("a vehicle needs a maximum - a weight, a count, or both")
    for ln in lines:
        if limit_kg and float(ln["kg_each"]) > limit_kg:
            raise ValueError(f"one of {ln['ref']} ({float(ln['kg_each']):g} kg) is more than a vehicle carries "
                             f"({limit_kg:g} kg)")
    vehicles = [[]]

    def load(todo, top_up=False):
        for item in todo:                       # [line, how many of it are still to go on]
            ln, each = item[0], float(item[0]["kg_each"])
            while item[1] > 0:
                room = item[1]
                if limit_kg and each:
                    kg = sum(q * float(x["kg_each"]) for x, q in vehicles[-1])
                    room = min(room, int(round(limit_kg - kg, 6) // each))
                if limit_units:
                    room = min(room, limit_units - sum(q for _, q in vehicles[-1]))
                if room <= 0:
                    if top_up:                  # a top-up only fills what is left of this vehicle
                        break
                    vehicles.append([])         # this vehicle is full - start the next
                    continue
                vehicles[-1].append((ln, room))
                item[1] -= room

    todo = [[ln, int(ln["qty"])] for ln in lines]
    # a rail of no known type shares with no other rail - a type of its own, by its place in the job
    types = [t if t != "?" else f"?{i}" for i, t in enumerate(map(rail_type, lines))]
    rails = list(dict.fromkeys(t for t in types if t))
    if len(rails) < 2:
        load(todo)
    else:
        rest = [item for item, t in zip(todo, types) if not t]
        for rail in rails:
            if vehicles[-1]:
                vehicles.append([])
            load([item for item, t in zip(todo, types) if t == rail])
            load(rest, top_up=True)
        load(rest)
    return [v for v in vehicles if v]


def delivery_type(booked, deliver):
    """CTMS's Delivery Type from booking to delivery - under 24 h EMERGENCY, 24-72 h NEXT DAY, over 72 h STANDARD
    (his rule 30/10; set on the order before Create New Trip)."""
    hours = (deliver - booked).total_seconds() / 3600
    return "EMERGENCY" if hours < 24 else "NEXT DAY" if hours <= 72 else "STANDARD"


def _when(v):
    try:
        return datetime.strptime(str(v).strip(), "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def plan(job, now=None, directory=None):
    """The plan for a job: its vehicles (one manifest each), and the questions that stop it being booked yet.
    `directory` is the haulier contact list (hauliers.load() when not given), read only for a Moffett job."""
    veh = job.get("vehicle") or {}
    off = kit(veh)
    limit_kg = veh.get("max_kg") or max_kg(veh.get("kind"), off)
    limit_units = veh.get("max_units")
    booked = _when(job.get("booked")) or now or datetime.now()
    questions = []
    if not limit_kg:
        kind = veh.get("kind") or "vehicle"
        questions.append(f"What's the most {'an' if kind[:1].lower() in 'aeiou' else 'a'} {kind} "
                         f"{'with ' + KIT[off] if off else 'without a HIAB'} carries?")
    book = job.get("book") or {}
    if off == "moffett":
        able = moffett_hauliers(directory)
        names = ", ".join(h["name"] for h in able) or "nobody on the contact list has one"
        if book.get("carrier") in (None, ""):
            questions.append(f"Which haulier - it needs a Moffett: {names}?")
        elif not any(h.get("ctms") and _code(h["ctms"]) == _code(book["carrier"]) for h in able):
            questions.append(f"{book['carrier']} has no Moffett on the contact list - which of these: {names}?")
    elif book.get("carrier") in (None, ""):
        questions.append("Which haulier - its CTMS carrier code?")
    if book.get("amount") in (None, ""):
        questions.append("What haulage amount (the agreed quote ex VAT, 0 for NOC, the matrix for tier 1)?")
    groups = {}
    for ln in job.get("lines") or []:
        groups.setdefault((ln.get("collect", ""), ln.get("deliver", "")), []).append(ln)
    for lines in groups.values():
        rails = [ln for ln in lines if rail_type(ln)]
        questions += [f"What rail type is {ln['ref']}? Two types never share a vehicle, so it has one of its own "
                      f"till I know." for ln in rails if len(rails) > 1 and rail_type(ln) == "?"]
    vehicles = []
    if limit_kg or limit_units:
        for (collect, deliver), lines in groups.items():
            due = _when(deliver)
            loads = load_plan(lines, limit_kg, limit_units)
            for n, load in enumerate(loads, 1):
                vehicles.append({
                    "collect": collect, "deliver": deliver,
                    "delivery_type": delivery_type(booked, due) if due else "",
                    "lines": [{"ref": ln["ref"], "material": ln.get("material", ""), "qty": q,
                               "kg": q * float(ln["kg_each"])} for ln, q in load],
                    "kg": sum(q * float(ln["kg_each"]) for ln, q in load),
                    "units": sum(q for _, q in load),
                    "last": n == len(loads)})       # nothing else for this pick-up, drop and day to fill it
    return {"job": job.get("job", ""), "vehicle": veh, "limit_kg": limit_kg, "limit_units": limit_units,
            "book": book, "vehicles": vehicles, "questions": questions}


def card(p):
    """The plan as he reads it: each vehicle, its lines, how full it is - and what is still to answer."""
    veh = p["vehicle"]
    limits = [f"{p['limit_kg']:,.0f} kg" if p["limit_kg"] else "", f"{p['limit_units']} a vehicle"
              if p["limit_units"] else ""]
    off = kit(veh)
    out = [f"{p['job']} - {len(p['vehicles'])} vehicle(s): {veh.get('kind') or 'vehicle'}, "
           f"{'with ' + KIT[off] if off else 'no HIAB'}, at most {' / '.join(x for x in limits if x)}"]
    book = p["book"]
    if any(book.values()):
        out.append("  Book with: " + ", ".join(f"{k} {v}" for k, v in book.items() if v not in (None, "")))
    for q in p["questions"]:
        out.append(f"  ? {q}")
    for i, v in enumerate(p["vehicles"], 1):
        full = f" ({v['kg'] / p['limit_kg']:.0%})" if p["limit_kg"] else ""
        why = (f", full at {p['limit_units']}" if p["limit_units"] and v["units"] >= p["limit_units"]
               else ", last load" if v.get("last") else "")
        out.append(f"  {i:>2}. {v['collect']} -> {v['deliver']}  {v['delivery_type']}  "
                   f"{v['units']} / {v['kg']:,.0f} kg{full}{why}")
        for ln in v["lines"]:
            out.append(f"        {ln['ref']}  {ln['qty']} x {ln['material']}  {ln['kg']:,.0f} kg")
    return "\n".join(out)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        print(card(plan(json.load(f))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
