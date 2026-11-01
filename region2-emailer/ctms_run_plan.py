"""
The CTMS to-do as a run (his ask 01/11: "turn execute CTMS into a button to save on tokens") - what each item would
type into CTMS, worked out by his rules, and what it can't be sure of.

  note     ' - Emailed DO 28/10' at the end of the -1-1 line's Special Instructions - always ready
  update   the site's reply onto its open line(s), by his rules (30/10):
             deliver   the day and window the site gave - a single time is time..time+2h
             collect   a morning delivery is collected the day before, in the supplier's yard hours; never on a
                       weekend - a Monday delivery collects on Friday, with STORAGE x2
             comment   LOC Detail, deliver side: date time - contact phone - HIAB required (or Moffett required) -
                       Rear steer required - W3W, no commas
             services  HIAB or MOFFETT when the site needs ours - always in Services, never a vehicle type ("whenever
                       we're adding a HIAB or a Moffett, we do it in the services tab", his rule 01/11); rear steer
                       on an artic only; PTS never on ballast
             veh type  as stated, else by the CTMS weight - a HIAB load of 10,000 kg or less goes on a rigid. Only
                       ever NR_Rigid (Up to 40ft) or NR_40ft Artic Flatbed - never RIGID MOFFETT and the like (his
                       rule 01/11). A Moffett job goes on a 40ft artic ("Moffetts are usually on 40ft artics", his
                       01/11) - picked only when the site takes no artics
  booking, other   his to do - never run

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
RIGID_HIAB_KG = 10000
OFFLOADING = ["HIAB", "MOFFETT", "SITE/NONE"]
YES_NO = ["yes", "no"]
VEHICLES = ["rigid", "artic"]
COLLECT_DAYS = ["the day before", "the same day"]


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


def _window(day, start, end):
    """The recipe's "DD/MM/YY HH:MM-HH:MM" - or "...-DD/MM/YY HH:MM" when it runs past midnight."""
    d0 = datetime.strptime(day, "%d/%m/%Y")
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


def _vehicle_said(v):
    s = str(v or "").lower()
    if not s:
        return ""
    if "art" in s:
        return "artic"
    if re.search(r"rig|7\.5|18\s*t|26\s*t|transit|van", s):
        return "rigid"
    return ""


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
            date = _day(doubt("date", "Delivery date", dv.get("raw") or dv.get("value"), opts,
                              "Not one firm day" if opts else "No delivery date the parser could be sure of",
                              text=not opts) or "")
    date = _day(date)
    # -- its lines in CTMS, from the last look-up
    lines = _lines_for(found, order, date or _day(rec.get("delivery_date")))
    if lines is None:
        checks.append({"field": "lines", "label": "CTMS lines", "quote": "", "options": [], "text": False,
                       "why": "Not looked up in CTMS yet - press Check CTMS now first"})
    elif not lines:
        return {"id": it["id"], "kind": "update", "orders": it.get("orders") or [], "what": it.get("what") or "",
                "status": "done", "lines": [], "set": {}, "explain": ["CTMS has no line left to update"],
                "checks": []}
    # -- the delivery window
    tv = _field(d, "time")
    start, end = _hm(tv.get("earliest")), _hm(tv.get("latest"))
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
        s["deliver"] = _window(date, start, end)
    # -- offloading, rear steer, PTS
    ov = _field(d, "offloading")
    off = answers.get("offloading") or (ov.get("value") if ov.get("confidence") == "high" else None)
    if off not in OFFLOADING:
        off = doubt("offloading", "Offloading", ov.get("raw") or ov.get("value"), OFFLOADING,
                    "Both named - which one?" if ov.get("value") == "BOTH" else "Not certain what they need")
    mats = (str(rec.get("materials") or "") + " " + " ".join(rec.get("product_codes") or [])).lower()
    ballast = bool(re.search(r"ballast|aggregate|stone\s*-?\s*blower", mats))
    rv = _field(d, "rear_steer")
    rear = answers.get("rear_steer") or (rv.get("value") if rv.get("confidence") in ("high", None) else None)
    if rear not in YES_NO:
        rear = doubt("rear_steer", "Rear steer", rv.get("raw") or rv.get("value"), YES_NO, "Not certain")
    pv = _field(d, "pts")
    pts = answers.get("pts") or (pv.get("value") if pv.get("confidence") in ("high", None) else None)
    if ballast:
        pts = "no"
        if pv.get("value") == "yes":
            explain.append("PTS left off: a ballast order never gets it (your rule)")
    elif pts not in YES_NO:
        pts = doubt("pts", "PTS", pv.get("raw") or pv.get("value"), YES_NO, "Not certain")
    # -- the vehicle: as stated, else by the CTMS weight
    veh = answers.get("veh") or _vehicle_said(_field(d, "vehicle").get("value"))
    kg = rec.get("ctms_weight")
    no_artics = _field(d, "artic_access").get("value") == "no"
    if not veh:
        if off == "MOFFETT":
            # "Moffetts are usually on 40ft artics" (his 01/11) - a site that takes no artics is his pick
            if no_artics:
                veh = doubt("veh", "Vehicle", _field(d, "artic_access").get("raw"), VEHICLES,
                            "A Moffett usually goes on a 40ft artic, but the site takes no artics - pick the vehicle")
            else:
                veh = "artic"
                explain.append("A Moffett job - on a 40ft artic (Moffetts usually are, your rule)")
        elif off == "HIAB" and kg:
            veh = "rigid" if float(kg) <= RIGID_HIAB_KG else "artic"
            explain.append(f"{float(kg):,.0f} kg in CTMS - " + ("a rigid HIAB (up to 10,000 kg)" if veh == "rigid"
                                                                 else "an artic HIAB (over 10,000 kg)"))
            if veh == "artic" and no_artics:
                veh = doubt("veh", "Vehicle", _field(d, "artic_access").get("raw"), VEHICLES,
                            f"{float(kg):,.0f} kg in CTMS - over a rigid HIAB's 10,000 kg - but the site takes "
                            "no artics")
        elif no_artics and (not kg or float(kg) <= RIGID_HIAB_KG):
            veh = "rigid"
            explain.append("No artic access - a rigid")
        elif off == "HIAB":
            veh = doubt("veh", "Vehicle", "", VEHICLES, "Weight not read from CTMS yet - press Check CTMS now, "
                        "or pick")
        elif off == "SITE/NONE":
            veh = doubt("veh", "Vehicle", "", VEHICLES,
                        (f"{float(kg):,.0f} kg in CTMS - " if kg else "") + "no HIAB: the most a rigid takes "
                        "without one isn't set")
        # offloading not settled yet: the vehicle waits for it
    if veh:
        s["veh"] = veh
    # -- services: HIAB or MOFFETT when ours is needed (Services, never a vehicle type), rear steer on an artic only,
    #    PTS never on ballast
    if off in OFFLOADING and rear in YES_NO and pts in YES_NO and veh:
        s["services"] = {"HIAB": off == "HIAB", "MOFFETT": off == "MOFFETT",
                         "REAR STEER": rear == "yes" and veh == "artic", "PTS": pts == "yes"}
        if rear == "yes" and veh == "rigid":
            explain.append("Rear steer left off: the site said yes, but a rigid never needs it (your rule)")
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
            s["collect"] = _window(day.strftime("%d/%m/%Y"), yard0, yard1)
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
        bits = [f"{datetime.strptime(date, '%d/%m/%Y'):%d/%m/%y} {when_said}", f"{name} {phone}".strip()]
        if off == "HIAB":
            bits.append("HIAB required")
        if off == "MOFFETT":
            bits.append("Moffett required")
        if (s.get("services") or {}).get("REAR STEER"):
            bits.append("Rear steer required")
        if w3w:
            bits.append(f"W3W {w3w if w3w.startswith('///') else '///' + w3w}")
        s["comments"] = " - ".join(bits).replace(",", "")
    status = "held" if checks else "ready"
    return {"id": it["id"], "kind": "update", "orders": it.get("orders") or [], "what": it.get("what") or "",
            "status": status, "lines": [ln.get("ref") for ln in lines or []], "set": s, "explain": explain,
            "checks": checks}


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


def load():
    """The plan from this PC's files: the CTMS to-do, the tracker and the last look-up."""
    import ctms_todo
    try:
        with open(LOOKED_UP, encoding="utf-8") as f:
            found = (json.load(f) or {}).get("orders") or {}
    except (OSError, ValueError):
        found = {}
    import site_contacts
    recs = site_contacts.enrich({"records": ctms_todo._tracker_records()})["records"]   # each order's sheet contact
    return plan(ctms_todo.listing(), recs, found)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(load(), indent=1))
