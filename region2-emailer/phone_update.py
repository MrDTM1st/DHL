"""
"Updated over the phone" - his ask (01/11): "instead of a booked over the phone button, that is now useless since ...
you book it in now ... change it to updated over the phone ... ask me questions on ... what information we've
received. And instead of me typing it in, whenever you can just give me a quick drop down ... and then when you have
the information, you will create a to-do list on the CTMS tab to update that order."

The order's brief asks what the site said on the call - drop-downs wherever there is a choice, filled in with what is
known already (an emailed reply, the order's sheet). The answers land on the tracker record the way a parsed reply
does, each one certain (he picked it), over anything an earlier email gave; the date moves the order as a reply's
would; and the order owes CTMS an update from them - the CTMS page's to-do list, for its Run button
(ctms_todo.phoned). Every answer is checked here: the dashboard is only where they were picked.

    python phone_update.py apply RECORD_ID ANSWERS.json      prints a JSON line at the end: {"ok", "said"}
"""
import json
import re
import sys
from datetime import datetime

import delivery_details as dd

OFFLOADING = ("HIAB", "MOFFETT", "SITE/NONE")
YES_NO = ("yes", "no")
VEHICLES = ("", "rigid", "artic")
RAW = "told on the phone"
LABELS = {"date": "the delivery date", "from": "the delivery time", "to": "the time it runs to",
          "offloading": "offloading", "artic_access": "artic access", "rear_steer": "rear steer", "pts": "PTS",
          "vehicle": "the vehicle", "contact_name": "the contact's name", "contact_phone": "the contact's number",
          "what3words": "the What3Words", "notes": "the notes", "collect": "the collection day",
          "already": "whether to type over CTMS"}


def _hm(v):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _phone(v):
    """A UK number as digits (a leading + kept) - '' when it isn't one."""
    s = re.sub(r"[\s()-]", "", str(v or ""))
    return s if re.fullmatch(r"\+?\d{10,13}", s) else ""


def _w3w(v):
    s = str(v or "").strip().lstrip("/").strip().lower()
    return f"///{s}" if re.fullmatch(r"[a-z]+\.[a-z]+\.[a-z]+", s) else ""


def details_from(form, rails):
    """The call's answers as the parser's details -> (details, problems). PTS only on a rail order (his rule 01/11);
    What3Words and notes may be left blank."""
    got, problems = {}, []

    def one(name, allowed, needed=True):
        v = str(form.get(name) or "").strip()
        if v in allowed and v:
            return v
        if v or needed:
            problems.append(name)
        return None
    day = str(form.get("date") or "").strip()
    try:
        datetime.strptime(day, "%d/%m/%Y")
    except ValueError:
        problems.append("date")
    start, end = _hm(form.get("from")), _hm(form.get("to"))
    if not start:
        problems.append("from")
    if form.get("to") and (not end or end == start):      # earlier than the start: it runs past midnight
        problems.append("to")
    off = one("offloading", OFFLOADING)
    artic = one("artic_access", YES_NO)
    rear = one("rear_steer", YES_NO)
    pts = one("pts", YES_NO) if rails else None
    veh = str(form.get("vehicle") or "").strip()
    if veh not in VEHICLES:
        problems.append("vehicle")
    name = re.sub(r"\s+", " ", str(form.get("contact_name") or "")).strip()
    if not name or len(name) > 60 or not re.search(r"[A-Za-z]", name):
        problems.append("contact_name")
    phone = _phone(form.get("contact_phone"))
    if not phone:
        problems.append("contact_phone")
    w3w = _w3w(form.get("what3words"))
    if form.get("what3words") and not w3w:
        problems.append("what3words")
    notes = re.sub(r"\s+", " ", str(form.get("notes") or "")).strip()
    if len(notes) > 300:
        problems.append("notes")
    if problems:
        return None, problems

    def cell(value):
        return {"value": value, "confidence": dd.HIGH, "raw": RAW}
    got["date"] = dict(cell(day), flexible=False, options=[day])
    got["time"] = {"earliest": start, "latest": end or None, "confidence": dd.HIGH, "raw": RAW, "expanded": False}
    got["offloading"], got["artic_access"], got["rear_steer"] = cell(off), cell(artic), cell(rear)
    got["vehicle"] = cell(veh or None)
    got["contact"] = {"name": name, "phone": phone, "confidence": dd.HIGH, "raw": f"{name} {phone}"}
    if rails:
        got["pts"] = cell(pts)
    if w3w:
        got["what3words"] = cell(w3w)
    if notes:
        got["notes"] = cell(notes)
    return got, []


def run_answers(form, rec, start):
    """What the to-do's Run would otherwise stop and ask him (his 03/11: "shouldn't you be asking me that on the ... form?")
    -> (answers kept on the item, problems). The same rule as the plan's: an afternoon delivery has no rule for its
    collection day."""
    import ctms_run_plan as plan
    got, problems = {}, []
    collect = str(form.get("collect") or "").strip()
    if collect in plan.COLLECT_DAYS:
        got["collect"] = collect
    elif collect or (start >= "12:00" and len(rec.get("collections") or []) == 1):
        problems.append("collect")
    already = str(form.get("already") or "").strip()
    if already in (plan.TICK_OFF, plan.TYPE_ANYWAY):
        got["already"] = already
    elif already:
        problems.append("already")
    if str(form.get("vehicle") or "").strip() in plan.VEHICLES:    # his pick on the call: nothing left to work out or ask
        got["veh"] = str(form["vehicle"]).strip()
    return got, problems


def apply(record_id, form, now=None):
    """The call's answers onto the order and the CTMS to-do -> {"ok", "said"}. The caller holds the tracker's lock."""
    import ctms_run_plan
    import ctms_todo
    import tracker
    d = tracker.load()
    rec = next((r for r in d["records"] if r.get("id") == record_id), None)
    if rec is None or rec.get("kind", "delivery") != "delivery":
        return {"ok": False, "said": "That order is no longer on the tracker - nothing saved."}
    rails = ctms_run_plan.is_rails(rec)
    got, problems = details_from(form or {}, rails)
    answers = {}
    if got:
        answers, problems = run_answers(form, rec, got["time"]["earliest"])
    if problems:
        return {"ok": False, "said": "Not saved - check " + ", ".join(LABELS.get(p, p) for p in problems) + "."}
    stamp = now or tracker._now()
    merged = dict(rec.get("details") or {})
    merged.update(got)
    rec["details"] = merged
    # What3Words is optional on the call's form, so going without one doesn't leave the order "still needing" it (his 03/11:
    # a phoned order stayed red on the map for this alone)
    rec["missing"] = [m for m in dd.missing(merged, "rails" if rails else None) if m != "What3Words"]
    rec["phoned_at"] = stamp
    rec["reply_at"] = rec.get("reply_at") or stamp              # answered: never chased again
    rec["sendoff_ready"] = True
    moved = tracker.move_date(d, rec, got["date"]["value"], "your phone call")
    tracker.save(d)
    ctms_todo.phoned(rec, when=stamp, answers=answers)
    orders = " / ".join(rec.get("orders") or [])
    return {"ok": True, "said": f"{orders}: the call's details are on the order"
                                + (f", its delivery moved to {got['date']['value']}" if moved else "")
                                + " - on the CTMS to-do list to update."}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 4 or argv[1] != "apply":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    with open(argv[3], encoding="utf-8") as f:
        form = json.load(f)
    import outlook_gate as gate
    if gate.named_lock("phase2_tracker", wait=30) is None:      # a reply check or chase holds the tracker
        out = {"ok": False, "said": "Not saved - the reply check is updating the tracker; press Save again in a minute."}
    else:
        out = apply(argv[2], form if isinstance(form, dict) else {})
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
