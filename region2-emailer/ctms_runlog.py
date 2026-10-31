"""
How every CTMS run went - the evidence for making the updates and the bookings automatic. His plan (31/10/2026):
"I'm going to leave that to you for now, see how that goes, and then based on the data that we'll collect over
time, we'll make it automatic when we don't have any errors."

One line per recipe run in ctms_remote/runs.jsonl (gitignored, with the run's traces): the kind of run, its orders,
clean or not, and the step it stopped at.

    python ctms_runlog.py          each kind of run: how many, how many clean, the clean streak, where the rest stopped
"""
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "ctms_remote", "runs.jsonl")
_STEP = re.compile(r"step (\d+) of (\d+) \(([^)]+)\)")


def record(kind, refs, ok, detail="", seconds=None, path=None, when=None):
    """Append one run - its step is the one it stopped at ("5/6 click"), blank when it ran clean."""
    m = _STEP.search(str(detail or ""))
    row = {"at": when or datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
           "refs": [str(r) for r in refs or []], "ok": bool(ok),
           "step": "" if ok or not m else f"{m.group(1)}/{m.group(2)} {m.group(3)}",
           "detail": str(detail or "")[:300], "seconds": seconds}
    path = path or LOG
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def load(path=None):
    rows = []
    try:
        with open(path or LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def summary(path=None):
    """{kind: {runs, clean, streak, stopped: {step: n}, last_stop}} - the streak is the clean runs since the last
    one that stopped."""
    out = {}
    for r in load(path):
        k = out.setdefault(r.get("kind", "?"), {"runs": 0, "clean": 0, "streak": 0, "stopped": {}, "last_stop": None})
        k["runs"] += 1
        if r.get("ok"):
            k["clean"] += 1
            k["streak"] += 1
        else:
            k["streak"] = 0
            k["stopped"][r.get("step") or "?"] = k["stopped"].get(r.get("step") or "?", 0) + 1
            k["last_stop"] = {"at": r.get("at"), "refs": r.get("refs"), "detail": r.get("detail")}
    return out


def main(argv=None):
    s = summary()
    if not s:
        print("No CTMS runs logged yet.")
        return 0
    for kind, k in sorted(s.items()):
        print(f"{kind}: {k['runs']} run(s), {k['clean']} clean, {k['streak']} clean in a row")
        for step, n in sorted(k["stopped"].items(), key=lambda x: -x[1]):
            print(f"    stopped at {step}: {n}")
        if k["last_stop"]:
            print(f"    last stop {k['last_stop']['at']} {', '.join(k['last_stop']['refs'])}: {k['last_stop']['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
