"""Evidence log for the toolkit - every send, save, catch and skip, appended to
_metrics.jsonl so the value of the system accumulates as hard numbers (for the
role/pay case: errors prevented, orders never forgotten, time returned).

    python metrics.py             # summary - all time + last 7 / 30 days
    python metrics.py dump 20     # last N raw events

Design rule: metrics must NEVER break the tool. log() swallows every error -
losing a data point beats losing an email send.
"""
import os, sys, json
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_metrics.jsonl")

# honest minutes-by-hand per event kind, for the time-returned estimate.
# Sources: Delali's own workflow (outreach written by hand ~5-10 min, rail plan
# per SOP ~30-60 min, brief ~5 min). Deliberately the LOW end of each range.
MINUTES = {
    "email_sent": 5, "chase_sent": 4, "collection_sent": 5, "brief_drafted": 5,
    "waitlist_released": 5, "rail_plan_built": 30, "synergy_mapped": 15,
    "reply_parsed": 3, "booked_removed": 2, "order_recovered": 10,
    "dedup_skip": 3, "handover_sent": 10, "materials_repaired": 2,
    "date_corrected": 3,
}
# kinds that represent a PREVENTED mistake (the error-reduction story)
ERROR_KINDS = ("dedup_skip", "booked_removed", "offlimits_skip", "region_skip",
               "date_corrected", "order_recovered", "materials_repaired")


def log(kind, **fields):
    """Append one event. Never raises."""
    try:
        rec = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "kind": str(kind)}
        for k, v in fields.items():
            try:
                json.dumps(v)
                rec[k] = v
            except Exception:
                rec[k] = str(v)
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _load():
    out = []
    try:
        with open(PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _count(e):
    """An event counts as `n` occurrences if it carries one (batch events)."""
    try:
        return max(1, int(e.get("n", 1)))
    except Exception:
        return 1


def summary(days=None):
    evs = _load()
    if days:
        cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        evs = [e for e in evs if e.get("at", "") >= cut]
    by = {}
    for e in evs:
        by[e["kind"]] = by.get(e["kind"], 0) + _count(e)
    mins = sum(MINUTES.get(k, 0) * n for k, n in by.items())
    errs = sum(n for k, n in by.items() if k in ERROR_KINDS)
    return by, mins, errs


def print_summary():
    for label, days in (("ALL TIME", None), ("LAST 30 DAYS", 30), ("LAST 7 DAYS", 7)):
        by, mins, errs = summary(days)
        print(f"\n=== {label} ===")
        if not by:
            print("  (no events yet)")
            continue
        for k in sorted(by, key=by.get, reverse=True):
            print(f"  {k:22} {by[k]:5}")
        print(f"  {'-'*30}")
        print(f"  mistakes prevented     {errs:5}")
        print(f"  est. time returned     {mins/60:5.1f} h  (~{mins/60/7.5:.1f} working days)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "dump":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for e in _load()[-n:]:
            print(json.dumps(e))
    else:
        print_summary()
