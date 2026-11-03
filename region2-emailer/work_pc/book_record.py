"""
The work PC's own record of every Book it carried out (_book_journal.jsonl, beside the bridge) - 03/11.

The bridge's answer to a Book goes to the dashboard, which hands it to the home PC. If the home PC has stopped waiting by
then, or the dashboard restarted, or its pictures pushed the answer's payload out, what CTMS made was known only to CTMS.
So the bridge writes each booking's outcome here BEFORE it answers, and the home PC can ask for it back (book_recall, a
read: nothing in CTMS is touched). Only the outcome is kept - orders, day, carrier, manifests, cost and revenue - never a
picture or anything typed into a sign-in.

Standard library only, like the rest of work_pc/. tests/test_book_journal.py.
"""
import json
import os
import re
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_book_journal.jsonl")
KEEP = 400                       # lines kept: weeks of bookings
FOUND_MAX = 6
TRIP_KEYS = ("manifest", "status", "revenue", "cost", "collect", "deliver", "lines", "took")


def _norm(o):
    return re.sub(r"\s+", "", str(o or "")).upper()


def keep(ask_id, orders, date, carrier, dry, ok, said, trips, stopped="", path=None, now=None):
    """One Book's outcome written down. Never raises: a full disk must not stop the answer going back."""
    p = path or PATH
    line = {"at": (now or datetime.now()).isoformat(timespec="seconds"), "id": ask_id,
            "orders": [_norm(o) for o in orders or []], "date": str(date or ""), "carrier": str(carrier or ""),
            "dry": bool(dry), "ok": bool(ok), "said": str(said or "")[:600], "stopped": str(stopped or "")[:300],
            "trips": [{k: t.get(k) for k in TRIP_KEYS if t.get(k) not in (None, "")}
                      for t in trips or [] if isinstance(t, dict)]}
    try:
        try:
            with open(p, encoding="utf-8") as f:
                old = f.readlines()
        except OSError:
            old = []
        old.append(json.dumps(line, default=str) + "\n")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(old[-KEEP:])
        os.replace(tmp, p)
    except Exception:
        pass
    return line


def recall(orders, date, ask_id=None, path=None):
    """What this PC booked for these orders on that day, newest first. With a command id, only that command's: an older
    booking of the same order says nothing about this press. Rehearsals are left out: they made nothing."""
    want = {_norm(o) for o in orders or []}
    got = []
    try:
        with open(path or PATH, encoding="utf-8") as f:
            for raw in f:
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                if e.get("dry") or str(e.get("date")) != str(date or "") or not want & set(e.get("orders") or []):
                    continue
                got.append(e)
    except OSError:
        return []
    got.reverse()
    if ask_id is not None:
        return [e for e in got if e.get("id") == ask_id][:1]
    return got[:FOUND_MAX]
