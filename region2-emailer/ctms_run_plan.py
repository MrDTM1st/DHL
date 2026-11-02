"""
The CTMS to-do as a run (his ask 01/11: "turn execute CTMS into a button to save on tokens") - what each item would
type into CTMS, worked out by his rules, and what it can't be sure of.

  note     ' - Emailed DO 28/10' at the end of the -1-1 line's Special Instructions - always ready
  update   the site's reply onto its open line(s), by his rules (30/10):
             deliver   the day and window the site gave - a single time is time..time+2h. Staged over several days
                       on the one line, the window runs from the first to the last: split only at booking (his 31/10)
             collect   a morning delivery is collected the day before, in the supplier's yard hours; never on a
                       weekend - a Monday delivery collects on Friday, with STORAGE x2
             comment   LOC Detail, deliver side: date time - contact phone - HIAB required (or Moffett required) -
                       Rear steer required - W3W, no commas
             services  HIAB or MOFFETT when the site needs ours - always in Services, never a vehicle type ("whenever
                       we're adding a HIAB or a Moffett, we do it in the services tab", his rule 01/11); rear steer
                       on an artic only; PTS only ever on rails ("PTS is only for Rails", his rule 01/11)
             veh type  whatever fits, worked out rather than asked (his 02/11: "you'd be able to figure it out by what
                       the material is and how much it weighs ... sleepers weigh 7 tons, you put it under a rigid").
                       Rails by their length: over a normal trailer a 60ft artic, over 18.3 m the 80ft artic, with its
                       escort ("only the 80ft trombones need an escort", his 31/10). A stoneblower on the rigid tipper
                       JG Vesty's go on. A Moffett only ever on an artic (his 02/11). Everything else by the weight -
                       bagged ballast's bags in tonnes ("if it's 60 bags of ballast, it will always be 60 tons", his
                       01/11), else CTMS's: up to 10,000 kg a rigid, over it an artic, which the booking splits if it
                       must. A site that takes no artics gets rigids. Never RIGID MOFFETT and the like (his rule 01/11)
  booking, other   his to do - never run

What only CTMS knows - the order's open lines, its weight - isn't asked for either: the item is marked "lookup" and the
run reads CTMS on the work PC first (ctms_run.look_up), then plans it again.

Anything it can't be sure of HOLDS the item. Each doubt names the field, the site's own words from the email (only
ever their words - anything of ours goes in the reason), and the choices for a drop-down (his 01/11: "tell me
exactly what they said in the email and then give me like a drop down menu of what to select"); a choice made there
is kept on the item (ctms_todo.answer) and settles that doubt.

    python ctms_run_plan.py        the plan, as JSON
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LOOKED_UP = os.path.join(HERE, "_ctms_orders.json")
OPEN = "UNSCHEDULED"
RIGID_KG = 10000                   # what goes on a rigid (his rigid HIAB's most, 31/10) - over it an artic
RIGID_M, ARTIC_M, SIXTY_M = 12.19, 13.6, 18.3   # the longest rail on each: "Up to 40ft", a normal trailer, a 60ft flat
BAG_KG = 1000                      # a bag of ballast is a tonne, always (his 01/11)
OFFLOADING = ["HIAB", "MOFFETT", "SITE/NONE"]
YES_NO = ["yes", "no"]
VEHICLES = ["rigid", "artic"]
NO_REAR_STEER = ("rigid", "tipper")   # "If it's a rigid vehicle, we would never need rear steer" (his 30/10)
COLLECT_DAYS = ["the day before", "the same day"]
AND = " and "                      # a date picked as "18/11/2026 and 19/11/2026" - staged over both days
TICK_OFF, TYPE_ANYWAY = "Tick it off - CTMS has it", "Type it in anyway"   # an update CTMS looks to have already


def _day(v):
    """dd/mm/yyyy from 'dd/mm/yy HH:MM', 'dd/mm/yy' or 'dd/mm/yyyy'; '' when it is none of them."""
    s = str(v or "").strip()
    for fmt, n in (("%d/%m/%Y", 10), ("%d/%m/%y", 8)):
        try:
            return datetime.strptime(s[:n], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return ""


def _hm(s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(s or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _field(d, name):
    v = (d or {}).get(name)
    return v if isinstance(v, dict) else {"value": v}


def _window(day, start, end, last=""):
    """The recipe's "DD/MM/YY HH:MM-HH:MM" - or "...-DD/MM/YY HH:MM" when it runs past midnight, or on to a last day."""
    d0 = datetime.strptime(day, "%d/%m/%Y")
    if last and last != day:
        return f"{d0:%d/%m/%y} {start}-{datetime.strptime(last, '%d/%m/%Y'):%d/%m/%y} {end}"
    t0 = datetime.strptime(f"{day} {start}", "%d/%m/%Y %H:%M")
    t1 = datetime.strptime(f"{day} {end}", "%d/%m/%Y %H:%M")
    if t1 <= t0:
        t1 += timedelta(days=1)
    if t1.date() == d0.date():
        return f"{d0:%d/%m/%y} {start}-{end}"
    return f"{d0:%d/%m/%y} {start}-{t1:%d/%m/%y} {end}"


def _lines_for(found, order, date):
    """The open lines of a delivery due `date` from the last CTMS look-up - that day's own, else (moved) the one other
    day's. None when the look-up never covered it."""
    got = [g for k, g in (found or {}).items() if k.split("|")[0] == str(order)]
    if not got:
        return None
    rows = [ln for g in got for ln in g.get("lines") or []]
    mine = [r for r in rows if _day(r.get("deliver_by")) == date]
    open_ = sorted((r for r in (mine or rows) if r.get("status") == OPEN), key=lambda r: r.get("ref", ""))
    if mine or len({_day(r.get("deliver_by")) for r in open_}) <= 1:
        return open_
    return []


def _veh_set(found, order):
    """The order's lines the last CTMS look-up saw a Veh Type on."""
    return sorted(ref for k, g in (found or {}).items() if k.split("|")[0] == str(order)
                  for ref, filled in (g.get("veh") or {}).items() if filled)


def _weight_found(found, order):
    """The weight of an order's lines the last CTMS look-up read off their cards - None when it read none."""
    kgs = {ref: kg for k, g in (found or {}).items() if k.split("|")[0] == str(order)
           for ref, kg in (g.get("weight") or {}).items()}
    return round(sum(kgs.values()), 2) if kgs else None


def _card_read(found, order):
    """Whether the last CTMS look-up opened this order's line cards, the only place its weight shows."""
    return any(g.get("veh") for k, g in (found or {}).items() if k.split("|")[0] == str(order))


def _vehicle_said(v):
    s = str(v or "").lower()
    if not s:
        return ""
    if "art" in s:
        return "artic"
    if re.search(r"rig|7\.5|18\s*t|26\s*t|transit|van", s):
        return "rigid"
    return ""


def stoneblower(rec):
    """Stoneblower stone, however the order words it."""
    return bool(re.search(r"stone\s*-?\s*blower", " ".join(
        [str(rec.get("materials") or "")] + [str(c) for c in rec.get("product_codes") or []]), re.I))


def tipped(rec):
    """Loose ballast or stoneblower stone - what goes on a tipper. 100500/001 is the loose stock code."""
    return stoneblower(rec) or bool(re.search(r"loose", str(rec.get("materials") or ""), re.I) or any(
        str(c).strip().endswith("100500/001") for c in rec.get("product_codes") or []))


def ballast_bags(rec):
    """The 1 t bags of ballast an order is, when that is all it is - none loose, nothing else on it - so their count
    is its weight in tonnes; 0 otherwise (an aggregate bag's weight isn't known)."""
    mats = str(rec.get("materials") or "")
    if tipped(rec):
        return 0
    n = 0
    for part in (p for p in re.split(r"[,;]", mats) if p.strip()):
        m = re.match(r"\s*(\d+)\s*x\s*.*\bballast\b", part, re.I)
        if not m:
            return 0
        n += int(m.group(1))
    return n


def _rail_items(rec):
    """The order's rail lines (S&C with them), by its materials and product wording. A sleeper's stock line can name
    the rail it is for ("GUARD RAIL SLEEPER") and is still a sleeper."""
    items = re.split(r"[,;]", str(rec.get("materials") or "")) + [str(c) for c in rec.get("product_codes") or []]
    return [x for x in items if not re.search(r"sleeper|bearer|trough", x, re.I)
            and re.search(r"\brails?\b|s&c|switch|crossing|half set", x, re.I)]


def is_rails(rec):
    """Rails on the order - the only loads PTS is ever for."""
    return bool(_rail_items(rec))


def rail_metres(rec):
    """The longest rail named on the order, in metres ("18.288M", "60ft") - None when none is."""
    text = " ".join(_rail_items(rec))
    got = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*m\b", text, re.I)]
    got += [float(n) * 0.3048 for n in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ft|feet)\b", text, re.I)]
    got = [m for m in got if 0 < m < 200]
    return max(got) if got else None


def plan_note(it):
    return {"id": it["id"], "kind": "note", "orders": it.get("orders") or [], "what": it.get("what") or "",
            "status": "ready", "lines": [it.get("ref")], "set": {"note": it.get("note") or ""}, "explain": [],
            "checks": []}


def plan_update(it, rec, found):
    """One reply's update: what it would type, and every doubt. rec: the tracker's record for the delivery (fresher
    than the copy on the item - corrections land there), found: the last CTMS look-up."""
    rec = rec or {}
    answers = it.get("answers") or {}
    d = rec.get("details") or ((it.get("details") or {}).get("details")) or {}
    order = (it.get("orders") or [""])[0]
    explain, checks, s = [], [], {}

    def doubt(field, label, quote, options=(), why="", text=False):
        if field in answers:
            return answers[field]
        checks.append({"field": field, "label": label, "quote": str(quote or ""), "options": list(options),
                       "why": why, "text": text})
        return None

    # -- the delivery day
    dv = _field(d, "date")
    date = answers.get("date") or ""
    if not date:
        opts = [o for o in dv.get("options") or [] if _day(o)]
        if dv.get("value") and dv.get("confidence") == "high" and not dv.get("flexible") and len(opts) <= 1:
            date = _day(dv["value"])
        else:
            date = doubt("date", "Delivery date", dv.get("raw") or dv.get("value"),
                         opts + ([AND.join(opts)] if len(opts) > 1 else []),
                         "Not one firm day" if opts else "No delivery date the parser could be sure of",
                         text=not opts) or ""
    days = sorted({_day(x) for x in str(date).split(AND) if _day(x)}, key=lambda x: datetime.strptime(x, "%d/%m/%Y"))
    date, last = (days[0], days[-1]) if days else ("", "")
    if len(days) > 1:
        explain.append(f"Staged over {len(days)} days, all on this line - it's split at booking (your rule)")
    # -- its lines in CTMS, from the last look-up
    lines = _lines_for(found, order, date or _day(rec.get("delivery_date")))
    look_up = lines is None            # what only CTMS can say is read when the run starts, never asked for
    if lines is not None and not lines:
        return {"id": it["id"], "kind": "update", "orders": it.get("orders") or [], "what": it.get("what") or "",
                "status": "done", "lines": [], "set": {}, "explain": ["CTMS has no line left to update"],
                "checks": []}
    # -- typed in already? A Veh Type is the last thing an update puts on (his rule: Veh Type filled = the site's
    # details are in) - a reply seen again, or a later one, is held for him rather than typed over what CTMS has
    # (his 02/11 "yeah, fix it": the 01/11 repeats of 7116527/8 would have lost a second contact from the comment)
    already = _veh_set(found, order)
    if already:
        pick = answers.get("already")
        if pick == TICK_OFF:
            return {"id": it["id"], "kind": "update", "orders": it.get("orders") or [], "what": it.get("what") or "",
                    "status": "done", "lines": [], "set": {},
                    "explain": ["You ticked it off - CTMS has it already"], "checks": []}
        if pick == TYPE_ANYWAY:
            s["anyway"] = True
            explain.append("You said type it in anyway - what CTMS has is typed over")
        else:
            checks.append({"field": "already", "label": "Already in CTMS?", "quote": "", "text": False,
                           "options": [TICK_OFF, TYPE_ANYWAY],
                           "why": f"CTMS already has a Veh Type on {', '.join(already)} - this reply looks typed in "
                                  "already, and running it would type over the deliver comment"})
    # -- the delivery window
    tv = _field(d, "time")
    start, end = _hm(tv.get("earliest")), _hm(tv.get("latest"))
    if end == start:                     # a single time read as "08:00 to 08:00" - not a window into the next day
        end = ""                         # (7116527's "13/11/26 @ 0800", 02/11)
    said_window = bool(start and end and not tv.get("expanded"))
    if answers.get("time"):
        m = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*(?:-\s*(\d{1,2}:\d{2}))?\s*", answers["time"])
        start, end = (_hm(m.group(1)), _hm(m.group(2) or "")) if m else ("", "")
        said_window = bool(end)
    elif not start or tv.get("confidence") not in ("high", None):
        doubt("time", "Delivery time", tv.get("raw"), (), "No delivery time the parser could be sure of - type it "
              "as HH:MM or HH:MM-HH:MM", text=True)
        start = ""
    if start and not end:
        end = (datetime.strptime(start, "%H:%M") + timedelta(hours=2)).strftime("%H:%M")
        explain.append(f"Delivery {start} becomes {start}-{end} (your +2h rule)")
    if date and start:
        s["deliver"] = _window(date, start, end, last)
    # -- offloading, rear steer, PTS
    ov = _field(d, "offloading")
    off = answers.get("offloading") or (ov.get("value") if ov.get("confidence") == "high" else None)
    if off not in OFFLOADING:
        off = doubt("offloading", "Offloading", ov.get("raw") or ov.get("value"), OFFLOADING,
                    "Both named - which one?" if ov.get("value") == "BOTH" else "Not certain what they need")
    rv = _field(d, "rear_steer")
    rear = answers.get("rear_steer") or (rv.get("value") if rv.get("confidence") in ("high", None) else None)
    if rear not in YES_NO:
        rear = doubt("rear_steer", "Rear steer", rv.get("raw") or rv.get("value"), YES_NO,
                     "Not certain" if rv.get("raw") or rv.get("value") else "Their email doesn't say")
    pv = _field(d, "pts")
    pts = answers.get("pts") or (pv.get("value") if pv.get("confidence") in ("high", None) else None)
    if not is_rails(rec):
        pts = "no"
        if pv.get("value") == "yes":
            explain.append("PTS left off: PTS is only for rails (your rule)")
    elif pts not in YES_NO:
        pts = doubt("pts", "PTS", pv.get("raw") or pv.get("value"), YES_NO,
                    "Not certain" if pv.get("raw") or pv.get("value") else "Their email doesn't say")
    # -- the vehicle: whatever fits - rails by their length, the rest by the weight (see the top of this file). Only
    #    what the site's own words rule out, or what nothing on the order can say, comes to him
    bags = ballast_bags(rec)
    kg = bags * BAG_KG or rec.get("ctms_weight") or _weight_found(found, order)
    weighs = f"{bags} bags of ballast at 1 t each - {bags * BAG_KG:,} kg" if bags else f"{float(kg or 0):,.0f} kg in CTMS"
    artics = _field(d, "artic_access")
    no_artics = artics.get("value") == "no"
    said = _vehicle_said(_field(d, "vehicle").get("value"))
    rails, metres = _rail_items(rec), rail_metres(rec)
    veh, weighing = answers.get("veh") or "", False
    if veh:
        pass
    elif stoneblower(rec):
        veh = "tipper"
        explain.append("A stoneblower - the rigid tipper they all go on")
    elif tipped(rec):
        checks.append({"field": "veh_tipper", "label": "Vehicle", "quote": "", "options": [], "text": False,
                       "why": "Loose ballast goes on a tipper, and which one isn't set - do the vehicle by hand"})
    elif rails and metres is None:
        veh = doubt("veh", "Vehicle", "", VEHICLES + ["60ft", "80ft"], "The order's wording doesn't say how long its "
                    "rails are, so which vehicle fits can't be worked out")
    elif metres and metres > RIGID_M:
        fits, named = (("80ft", "the 80ft artic") if metres > SIXTY_M else ("60ft", "a 60ft artic")
                       if metres > ARTIC_M else ("artic", "an artic"))
        if no_artics or said == "rigid":
            veh = doubt("veh", "Vehicle", artics.get("raw") or _field(d, "vehicle").get("raw"), [fits],
                        f"{metres:g} m rails only fit {named}, but the site says it takes no artics"
                        + (" - though it asks for rear steer, which only an artic has" if rear == "yes" else "")
                        + ". Pick it to go ahead, or ring them")
        else:
            veh = fits
            explain.append(f"{metres:g} m rails - {named}, the shortest that takes them")
    elif off == "MOFFETT":             # "the Moffetts only go on artics, so you don't put it on a rigid" (his 02/11)
        if no_artics or said == "rigid":
            veh = doubt("veh", "Vehicle", artics.get("raw") or _field(d, "vehicle").get("raw"), ["artic"],
                        "A Moffett only goes on an artic, but the site says it takes no artics. Pick it to go ahead, "
                        "or ring them")
        else:
            veh = "artic"
            explain.append("A Moffett job - on a 40ft artic, the only thing a Moffett goes on (your rule)")
    elif said:
        veh = said
        explain.append(f"A {said} - the site said so")
    elif off not in OFFLOADING:
        pass                           # the vehicle waits for the offloading: a Moffett goes on an artic
    elif no_artics:
        veh = "rigid"
        explain.append("No artic access - a rigid" + (
            f": {weighs} is over one rigid's {RIGID_KG:,} kg, so the booking splits it" if float(kg or 0) > RIGID_KG else ""))
    elif kg:
        veh = "rigid" if float(kg) <= RIGID_KG else "artic"
        explain.append(f"{weighs} - " + (f"a rigid (up to {RIGID_KG:,} kg)" if veh == "rigid"
                                         else f"an artic (over {RIGID_KG:,} kg)"))
    elif _card_read(found, order):
        veh = doubt("veh", "Vehicle", "", VEHICLES, "CTMS shows no weight on its lines, so which vehicle fits can't be "
                    "worked out")
    else:
        weighing = look_up = True
    if look_up:
        explain.append("Read from CTMS when you press Run: " + (
            "its open lines and its weight, which picks the vehicle" if lines is None and weighing else
            "its open lines" if lines is None else "its weight, which picks the vehicle"))
    if veh in NO_REAR_STEER and rear not in YES_NO:      # nothing to ask: it never needs it
        checks[:] = [c for c in checks if c["field"] != "rear_steer"]
        rear = "no"
    if veh == "tipper":                # tipped off: no offloading to ask about, and never a HIAB on a tipper
        checks[:] = [c for c in checks if c["field"] != "offloading"]
        off = "SITE/NONE"
    if veh:
        s["veh"] = veh
    # -- services: HIAB or MOFFETT when ours is needed (Services, never a vehicle type), rear steer on an artic only,
    #    PTS only on rails
    if off in OFFLOADING and rear in YES_NO and pts in YES_NO and veh:
        s["services"] = {"HIAB": off == "HIAB", "MOFFETT": off == "MOFFETT",
                         "REAR STEER": rear == "yes" and veh not in NO_REAR_STEER, "PTS": pts == "yes"}
        if rear == "yes" and veh in NO_REAR_STEER:
            explain.append("Rear steer left off: the site said yes, but a rigid never needs it (your rule)")
        if veh == "80ft":
            s["services"]["ESCORTS"] = True
            explain.append("The 80ft artic needs an escort (your rule) - ESCORTS added")
    # -- the collection: a morning delivery the day before in yard hours, never on a weekend
    colls = rec.get("collections") or []
    if len(colls) != 1:
        checks.append({"field": "collect", "label": "Collection", "quote": "", "options": [], "text": False,
                       "why": f"{len(colls)} pick-ups - do the collection by hand" if colls else
                              "No collection on the record - do it by hand"})
    elif date and start:
        yard0, yard1 = _hm(colls[0].get("from")), _hm(colls[0].get("to"))
        when = answers.get("collect")
        if not when:
            when = "the day before" if start < "12:00" else doubt(
                "collect", "Collection day", "", COLLECT_DAYS,
                f"A delivery at {start} on {date[:5]} - no rule for which day to collect: pick one")
        if when in COLLECT_DAYS and yard0 and yard1:
            day = datetime.strptime(date, "%d/%m/%Y") - timedelta(days=1 if when == "the day before" else 0)
            storage = 0
            if day.weekday() == 6 and when == "the day before":       # a Monday delivery: Friday, STORAGE x2
                day -= timedelta(days=2)
                storage = 2
                explain.append("Monday delivery - collected Friday with STORAGE x2 (your rule)")
            elif day.weekday() >= 5:
                checks.append({"field": "collect_weekend", "label": "Collection day", "quote": "", "options": [],
                               "text": False, "why": f"The collection would be {day:%a %d/%m}, a weekend - no rule "
                                                     "for that: do it by hand"})
            upto = datetime.strptime(last, "%d/%m/%Y") - timedelta(days=1 if when == "the day before" else 0)
            while upto.weekday() >= 5:         # the last load's collection, off the weekend like the first's
                upto -= timedelta(days=1)
            s["collect"] = _window(day.strftime("%d/%m/%Y"), yard0, yard1, upto.strftime("%d/%m/%Y"))
            if storage:
                s["storage"] = storage
            if when == "the day before":
                explain.append(f"Collected the day before, in the yard's {yard0}-{yard1}")
        elif when in COLLECT_DAYS:
            checks.append({"field": "yard", "label": "Yard hours", "quote": "", "options": [], "text": False,
                           "why": "The supplier's yard hours aren't on the record - do the collection by hand"})
    # -- the deliver-side comment
    cv = _field(d, "contact")
    import site_contacts
    sheet_name = str(rec.get("site_contact") or "").strip()
    name, phone, how = site_contacts.fill_contact(cv, sheet_name, rec.get("site_phone"))
    name = " ".join(w.capitalize() for w in name.split())
    phone = re.sub(r"\D", "", phone)
    if how == "sheet":
        explain.append(f"No site contact in the reply - {name}, the order's contact, on the sheet's number (your rule)")
    elif how == "sheet phone":
        explain.append(f"{name}'s number from the order's sheet - the reply had none")
    if answers.get("contact"):
        name, phone = answers["contact"].strip(), ""          # typed as name and number together
    if not name:
        name = doubt("contact", "Contact", cv.get("raw"), (), "Nobody named and no contact on the order's sheet - "
                     "type the name and number", text=True)
        phone = ""
    elif not phone and not answers.get("contact"):
        name = doubt("contact", "Contact", cv.get("raw"), (), f"No number for {name} in the reply or on the order's "
                     "sheet - type the name and number", text=True)
    w3w = str(_field(d, "what3words").get("value") or "").strip()
    if date and start and name:
        when_said = f"{start}-{end}" if said_window else start
        who = f"{name} {phone}".strip()
        alt = _field(d, "alt_contact")
        if alt.get("phone") and not answers.get("contact"):     # both contacts, as he types them (his 30/10)
            who += " / " + " ".join(w.capitalize() for w in f"{alt.get('name') or ''} {re.sub(r'[^0-9]', '', alt['phone'])}".split())
        said_days = AND.join(f"{datetime.strptime(x, '%d/%m/%Y'):%d/%m/%y}" for x in days)
        bits = [f"{said_days} {when_said}", who]
        if off == "HIAB":
            bits.append("HIAB required")
        if off == "MOFFETT":
            bits.append("Moffett required")
        if (s.get("services") or {}).get("REAR STEER"):
            bits.append("Rear steer required")
        if w3w:
            bits.append(f"W3W {w3w if w3w.startswith('///') else '///' + w3w}")
        extra = str(_field(d, "comment_extra").get("value") or "").strip()
        if extra:                      # the site's own instruction for the load ("X84 per lorry", 6055858)
            bits.append(extra)
        s["comments"] = " - ".join(bits).replace(",", "")
    status = "held" if checks else "ready"
    return {"id": it["id"], "kind": "update", "orders": it.get("orders") or [], "what": it.get("what") or "",
            "status": status, "lines": [ln.get("ref") for ln in lines or []], "set": s, "explain": explain,
            "checks": checks,
            "lookup": {"ref": str(order), "date": _day(rec.get("delivery_date"))} if look_up else None}


def plan(items, records, found):
    """The run plan for every open to-do item, oldest first."""
    by_order = {}
    for r in records:
        if r.get("kind", "delivery") == "delivery":
            for o in r.get("orders") or []:
                by_order.setdefault(str(o), r)
    out = []
    for it in items:
        if it.get("kind") == "note":
            out.append(plan_note(it))
        elif it.get("kind") == "update":
            order = str((it.get("orders") or [""])[0])
            out.append(plan_update(it, by_order.get(order), found))
        else:
            out.append({"id": it["id"], "kind": it.get("kind"), "orders": it.get("orders") or [],
                        "what": it.get("what") or "", "status": "yours", "lines": [], "set": {}, "explain": [],
                        "checks": []})
    return out


def load(fresh=None):
    """The plan from this PC's files: the CTMS to-do, the tracker and the last look-up - and `fresh`, what a look-up has
    just found (ctms_run), in place of what the last one had for those orders."""
    import ctms_todo
    try:
        with open(LOOKED_UP, encoding="utf-8") as f:
            found = (json.load(f) or {}).get("orders") or {}
    except (OSError, ValueError):
        found = {}
    if fresh:
        now = {k.split("|")[0] for k in fresh}
        found = dict({k: v for k, v in found.items() if k.split("|")[0] not in now}, **fresh)
    import site_contacts
    recs = site_contacts.enrich({"records": ctms_todo._tracker_records()})["records"]   # each order's sheet contact
    return plan(ctms_todo.listing(), recs, found)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(load(), indent=1))
