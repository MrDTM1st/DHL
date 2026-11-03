"""
The booking journal: what each press of Book did, step by step, kept on the home PC (_book_journal.json).

Why it exists (03/11). A press of Book is a CTMS booking on the work PC and then four or five things here: the DigiHaul row,
Parcel Pass told, the site's email, the chain filed, off the map. Each was tried once and said in words, and nothing kept
what had been done. So:

  - the home PC giving up waiting before the work PC was done left a trip ACCEPTED in CTMS and nobody told: no row, no
    email, still on the map, and the work PC's answer arriving a minute later went nowhere;
  - a second vehicle stopping after the first was ACCEPTED came back as "not booked", and the first one's email was never
    sent;
  - a step that failed once (Outlook busy, the site thread not found yet) became "do it by hand".

Now every press is written down before anything is asked of CTMS and after every step. A press of Book on an order the
journal already has booked does not book it again: it finishes what is left. An answer that never came is asked for again
(the dashboard keeps it by its id, the work PC keeps its own copy). Outlook's steps that fail are tried again by the home
PC's timer, a few minutes apart, and only then put in front of him with a Retry button.

Pure Python, no Outlook, no CTMS: book_run.py does the work and tells the journal; tests/test_book_journal.py.

States of a job:
  asking    written before the work PC is asked; ask_id once the dashboard numbered the command
  booked    CTMS has ACCEPTED trips for it; steps say what follows them
  clear     CTMS made nothing: a press of Book starts afresh
  half      a manifest was made but never reached ACCEPTED: only he can say what to do with it in CTMS
  unknown   asked, and neither the dashboard nor the work PC can say what came of it: he looks in CTMS
  done      everything that follows the booking is done, or he took the rest on by hand
"""
import json
import os
import re
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_book_journal.json")

ACCEPTED = "ACCEPTED"
# what follows a booking, in the order book_run does them
STEPS = ("digihaul", "pass_email", "site_email", "filed", "off_map")
# the ones the home PC's timer may try again on its own: Outlook only. The DigiHaul row is typed on the work PC, which
# needs Look mum, no hands on - only his press (Retry) switches that on
AUTO = ("pass_email", "site_email", "filed", "off_map")
TRIES = 3                      # by the timer; after that it waits for his Retry
BACKOFF = (0, 180, 600)        # seconds before the 1st, 2nd, 3rd try: a busy Outlook is usually free in minutes
LOST_AFTER = 20 * 60           # asked this long ago and still nothing back: the answer is looked for again
KEEP_DONE = 14 * 86400         # finished jobs are forgotten after a fortnight
HISTORY = 30

LABEL = {"digihaul": "DigiHaul row", "pass_email": "Parcel Pass email", "site_email": "site email",
         "filed": "chain filed", "off_map": "off the map"}


def _now():
    return time.time()


def _stamp(t=None):
    return datetime.fromtimestamp(t or _now()).strftime("%d/%m %H:%M")


def _base(o):
    """An order as the journal keys it: as the panel names it, case and spaces aside. Not cut down to a base number: an ad
    hoc's ref has dashes of its own (AH30-7-26G5ML), and Book always names a job by its record's orders."""
    return re.sub(r"\s+", "", str(o or "")).upper()


def key(orders, date):
    """One job: its orders (any order, any spelling of a line) and its delivery day."""
    return "|".join(sorted({_base(o) for o in orders or [] if str(o).strip()})) + "@" + str(date or "").strip()


# -- the file
def load(path=None):
    try:
        with open(path or PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("jobs"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"jobs": {}}


def _save(d, path=None):
    p = path or PATH
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
    os.replace(tmp, p)                 # never half written: the journal is what stops a second booking


def _prune(d, now):
    for k in [k for k, e in d["jobs"].items()
              if e.get("state") in ("done", "clear") and now - float(e.get("updated") or 0) > KEEP_DONE]:
        del d["jobs"][k]


def _note(e, line, now):
    e.setdefault("history", []).append([_stamp(now), str(line)[:300]])
    del e["history"][:-HISTORY]
    e["updated"] = now


def get(k, path=None):
    return load(path)["jobs"].get(k)


def _change(k, fn, path=None, now=None):
    now = now or _now()
    d = load(path)
    e = d["jobs"].get(k)
    if e is None:
        return None
    fn(e, now)
    _prune(d, now)
    _save(d, path)
    return e


# -- what a press of Book finds
def verdict(e):
    """What a press of Book should do with what the journal has: "book" (nothing in the way), "resume" (booked, steps
    left), "finished" (booked, nothing left), "recall" (asked, answer not had yet), or "hold" (half / unknown: him)."""
    if not e:
        return "book"
    st = e.get("state")
    if st == "booked":
        return "resume" if left(e) else "finished"
    if st == "done":
        return "finished" if accepted(e) else "book"
    if st == "asking":
        return "recall"
    if st in ("half", "unknown"):
        return "hold"
    return "book"


def accepted(e):
    return [t for t in (e or {}).get("trips") or [] if t.get("status") == ACCEPTED and t.get("manifest")]


def needs(carrier):
    """What follows a booking with this carrier."""
    c = str(carrier or "").strip().upper()
    want = []
    if c.endswith("_DH"):
        want.append("digihaul")
    if c == "PASS_DH":
        want.append("pass_email")
    return want + ["site_email", "filed", "off_map"]


def left(e):
    """Steps not done yet, in order."""
    steps = (e or {}).get("steps") or {}
    return [s for s in STEPS if s in steps and not steps[s].get("ok") and not steps[s].get("by_hand")]


# -- what book_run tells it
JOB_KEYS = ("record", "orders", "date", "carrier", "haulier", "trailer", "haulage", "vehicles", "site_to")


def asking(job, path=None, now=None):
    """Before the work PC is asked: written first, so a home PC that dies waiting still has it on file."""
    now = now or _now()
    k = key(job.get("orders"), job.get("date"))
    d = load(path)
    old = d["jobs"].get(k) or {}
    e = {"key": k, "state": "asking", "created": old.get("created") or now, "asked_at": now, "ask_id": None,
         "trips": [], "steps": {}, "history": old.get("history") or [], "presses": int(old.get("presses") or 0) + 1}
    e.update({x: job.get(x) for x in JOB_KEYS if job.get(x) not in (None, "")})
    _note(e, f"asked the work PC to book with {job.get('carrier')}", now)
    d["jobs"][k] = e
    _prune(d, now)
    _save(d, path)
    return e


def asked(k, ask_id, path=None, now=None):
    """The dashboard numbered the command: that number is how its answer is found again."""
    def fn(e, now):
        e["ask_id"] = ask_id
    return _change(k, fn, path, now)


def _trip(t):
    keep = ("manifest", "status", "revenue", "cost", "collect", "deliver", "lines", "took")
    return {x: t.get(x) for x in keep if t.get(x) not in (None, "")}


def answered(k, ok, said, trips, carrier=None, path=None, now=None):
    """What the work PC made. Any ACCEPTED trip makes the job booked, even when the run stopped after it - its steps
    still have to follow. A manifest left short of ACCEPTED is half made: held for him."""
    def fn(e, now):
        e["trips"] = [_trip(t) for t in trips or [] if isinstance(t, dict)]
        e["ctms_said"] = str(said or "")[:600]
        e["ctms_ok"] = bool(ok)
        e["answered_at"] = now
        made = accepted(e)
        short = [t for t in e["trips"] if t.get("manifest") and t.get("status") != ACCEPTED]
        if made:
            e["state"] = "booked"
            for s in needs(carrier or e.get("carrier")):
                e["steps"].setdefault(s, {"ok": False, "tries": 0, "said": "", "next_at": now})
            if short:
                e["short"] = [f"{t['manifest']} {t.get('status') or '?'}" for t in short]
            _note(e, f"CTMS: {', '.join(t['manifest'] for t in made)} ACCEPTED"
                     + (f"; left short: {', '.join(e['short'])}" if short else "")
                     + ("" if ok else f"; it stopped after: {said}"), now)
        elif short:
            e["state"] = "half"
            e["short"] = [f"{t['manifest']} {t.get('status') or '?'}" for t in short]
            _note(e, f"CTMS made {', '.join(e['short'])} and stopped there: {said}", now)
        else:
            e["state"] = "clear"
            _note(e, f"CTMS booked nothing: {said}", now)
    return _change(k, fn, path, now)


def lost(k, why, path=None, now=None):
    """Neither the dashboard nor the work PC can say what came of the ask."""
    def fn(e, now):
        e["state"] = "unknown"
        _note(e, f"no answer to be had: {why}", now)
    return _change(k, fn, path, now)


def step(k, name, ok, said="", path=None, now=None, auto=False, **extra):
    """One step tried. A failure is given a time to be tried again by the timer, while it has tries left (AUTO steps only)."""
    def fn(e, now):
        s = e.setdefault("steps", {}).setdefault(name, {"ok": False, "tries": 0, "said": "", "next_at": now})
        s["tries"] = int(s.get("tries") or 0) + 1
        s["ok"], s["said"], s["at"] = bool(ok), str(said or "")[:300], now
        s.update(extra)
        if not ok:
            n = s["tries"]
            s["next_at"] = now + BACKOFF[n] if name in AUTO and n < TRIES else None
        _note(e, f"{LABEL.get(name, name)}: {'done' if ok else 'not done'}"
                 + (f" ({said})" if said else "") + (" [timer]" if auto else ""), now)
        _settle(e, now)
    return _change(k, fn, path, now)


def written(k, manifest, path=None, now=None):
    """One manifest's DigiHaul row went on: kept at once, so a retry never pastes it twice."""
    def fn(e, now):
        s = e.setdefault("steps", {}).setdefault("digihaul", {"ok": False, "tries": 0, "said": "", "next_at": None})
        got = s.setdefault("written", [])
        if manifest not in got:
            got.append(manifest)
    return _change(k, fn, path, now)


def _settle(e, now):
    if e.get("state") == "booked" and not left(e):
        e["state"] = "done"
        _note(e, "everything after the booking done", now)


def by_hand(k, step_name=None, path=None, now=None):
    """He took it on: one step (or every step left) done by hand; an unknown / half job cleared after he looked in CTMS -
    "clear" if CTMS has nothing, so the next press books it."""
    def fn(e, now):
        if e.get("state") in ("unknown", "half", "asking") and not step_name:
            e["state"] = "booked" if accepted(e) else "clear"
            _note(e, "he looked in CTMS and cleared it", now)
        for s in [step_name] if step_name else left(e):
            if s in (e.get("steps") or {}):
                e["steps"][s]["by_hand"] = True
                _note(e, f"{LABEL.get(s, s)}: he does it by hand", now)
        _settle(e, now)
    return _change(k, fn, path, now)


# -- what the timer looks for
def due(path=None, now=None):
    """(key, [steps]) the timer may try now: Outlook steps of booked jobs, failed, tries left, their time come."""
    now = now or _now()
    out = []
    for k, e in load(path)["jobs"].items():
        if e.get("state") != "booked":
            continue
        ready = [s for s in left(e) if s in AUTO and (e["steps"][s].get("next_at") is not None)
                 and float(e["steps"][s]["next_at"]) <= now and int(e["steps"][s].get("tries") or 0) < TRIES]
        if ready:
            out.append((k, ready))
    return out


def unanswered(path=None, now=None):
    """Jobs asked of the work PC long enough ago that its answer should be in: looked for again."""
    now = now or _now()
    return [k for k, e in load(path)["jobs"].items()
            if e.get("state") == "asking" and now - float(e.get("asked_at") or now) >= LOST_AFTER]


# -- what the dashboard shows
def open_items(path=None, now=None):
    """Jobs that need him or are still being finished, newest first - the dashboard's Bookings card."""
    now = now or _now()
    out = []
    for k, e in load(path)["jobs"].items():
        st = e.get("state")
        if st not in ("asking", "booked", "half", "unknown"):
            continue
        steps = e.get("steps") or {}
        todo = [{"step": s, "label": LABEL[s], "tries": int(steps[s].get("tries") or 0), "said": steps[s].get("said") or "",
                 "auto": s in AUTO and steps[s].get("next_at") is not None and int(steps[s].get("tries") or 0) < TRIES}
                for s in left(e)]
        if st == "asking":
            need = "waiting for the work PC's answer"
        elif st == "half":
            need = f"{', '.join(e.get('short') or [])} not ACCEPTED: finish or remove it in CTMS, then clear"
        elif st == "unknown":
            need = ("no answer from the work PC: look in CTMS. Booked there: finish it by hand, then Clear. Not booked: "
                    "Clear, and press Book again")
        elif any(not t["auto"] for t in todo):
            need = "needs your Retry, or Done by hand"
        else:
            need = "being finished: the home PC tries again in a few minutes"
        out.append({"key": k, "record": e.get("record") or "", "orders": e.get("orders") or [], "date": e.get("date") or "",
                    "carrier": e.get("carrier") or "", "haulier": e.get("haulier") or "", "state": st, "need": need,
                    "manifests": [t["manifest"] for t in accepted(e)], "short": e.get("short") or [], "todo": todo,
                    "job": {x: e.get(x) for x in JOB_KEYS if e.get(x) not in (None, "")},
                    "history": (e.get("history") or [])[-6:], "updated": _stamp(float(e.get("updated") or now)),
                    "_t": float(e.get("updated") or now)})
    out.sort(key=lambda x: x["_t"], reverse=True)
    for x in out:
        del x["_t"]
    return out[:20]
