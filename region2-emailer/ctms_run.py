"""
The CTMS to-do run - the ready items of the plan (ctms_run_plan) done in CTMS on the work PC one at a time, each read back
before it counts as done (Delali's ask 01/11; the Run button on the dashboard's CTMS page).

Each item is one command to the work PC, which does all of it there in one go: work_pc/ctms_items.py says what a note and an
update do. What's here is what goes round them (02/11: "the run CTMS button is really annoying me, because it's not working
smoothly" - it ran the steps from here, about 70 seconds a note, and the first thing wrong stopped everything after it):

  look-up  an update the plan marks "lookup" - its open lines or weight not known yet - is looked up first, on the work
           PC, and planned again; searches and reads only. What that turns up (a Veh Type on it, a doubt) holds it
  done     CTMS has no line left to update - ticked off, nothing typed
  one wrong: backed out of on the work PC with nothing saved, and the rest carry on. The run only stops when CTMS couldn't
           be left clean, or the work PC can't be reached
  each item done is ticked off the CTMS to-do as it goes, and the page told how it's going
  at the end, with CTMS free again, each update done has its email chain filed away - Delali's rule (30/10) - through file_chain

    python ctms_run.py run [--run N] ID [ID ...]      prints a JSON line at the end: {"ok", "said", "results", "seconds"}
"""
import contextlib
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOOK_UP_SECONDS = 420              # the bridge's own limit on a look-up (CHECK_SECONDS), and a margin
ITEM_SECONDS, LINE_SECONDS = 60, 90    # how long the work PC gets for an item: on top of its answer's own waits


class Failed(Exception):
    pass


def _client():
    import ctms_remote as R
    R.OUT = os.path.join(HERE, "ctms_remote")
    R.STATE = os.path.join(R.OUT, "state.json")
    R.BASE, R.KEY = R._desk()
    return R


def _quiet(fn, *a, **k):
    """A client call with its printing kept: (its return, what it printed)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


def do_item(R, p, first, last):
    """One item, on the work PC: {"done", "held", "clean", "said", "seconds"}."""
    item = {"kind": p["kind"], "lines": p.get("lines") or [], "set": p.get("set") or {}}
    wait = ITEM_SECONDS + LINE_SECONDS * max(1, len(item["lines"]))
    (result, payload), _ = _quiet(R.ask_waiting, "ctms_item", wait_total=wait, item=item, first=first, last=last)
    try:
        _quiet(R.trace, f"item-{p['id']}", {"item": item}, result, payload)
    except Exception:
        pass
    payload = payload or {}
    return {"done": bool(payload.get("done")), "held": bool(payload.get("held")),
            "clean": bool(payload.get("clean")), "said": str(result.get("detail") or ""), "seconds": payload.get("seconds")}


def file_emails(p):
    """Delali's rule (30/10): once an order is updated, its email chain is filed away - the site thread's mails still in
    the Inbox's top level into Region 2 > Completed (file_chain). Never fails the item - CTMS is done whatever the
    mailbox says - but says what happened."""
    try:
        import build_drafts as bd
        import ctms_todo
        import file_chain
        orders = set(p.get("orders") or [])
        recs = [r for r in ctms_todo._tracker_records()
                if r.get("kind", "delivery") == "delivery" and orders & set(r.get("orders") or [])]
        ns = bd.get_ns()
        n = sum(len(file_chain.file_chain(ns, r)) for r in recs or [{"orders": sorted(orders)}])
        return f"; {n} email(s) filed to Region 2 > Completed" if n else "; no emails left in the Inbox to file"
    except Exception as e:
        return f"; emails NOT filed ({type(e).__name__}: {e})"


FILE = file_emails                 # the tests put a stand-in here


def look_up(R, plan):
    """What only CTMS can say about these plan items - their open lines, Veh Type and weight - read on the work PC, as
    the bridge's own look-up does: searches and reads, nothing typed. Its cards are only opened for the weight when that
    isn't known: each line's Veh Type gets read as it's done (a 7-line order's look-up took 73 s). {"ref|date": what it found}."""
    orders = {f"{ref}|{p['lookup']['date']}": {"ref": ref, "date": p["lookup"]["date"], "veh": p["lookup"].get("cards", True)}
              for p in plan for ref in [p["lookup"]["ref"]] + list(p["lookup"].get("also") or [])}
    (result, payload), _ = _quiet(R.ask_waiting, "ctms_check", wait_total=LOOK_UP_SECONDS,
                                  orders=[dict(o, key=k) for k, o in orders.items()])
    if not result.get("ok"):
        raise Failed(f"CTMS could not be looked up: {result.get('detail')}")
    return (payload or {}).get("orders") or {}


def tell(R, run_id, on, results):
    """The page told how the run is going - never at the run's expense."""
    if not run_id:
        return
    try:
        _quiet(R.http, "POST", "/api/ctms/todo/progress", {"run": run_id, "on": on, "results": results})
    except Exception:
        pass


def took(seconds):
    return f"{int(seconds // 60)} min {int(seconds % 60)} s" if seconds >= 60 else f"{int(seconds)} s"


def run(ids, run_id=0):
    import ctms_run_plan
    import ctms_todo
    t0 = time.time()
    want = [str(i) for i in ids]
    plan = [p for p in ctms_run_plan.load() if p["id"] in want]
    results, R, not_looked = [], None, ""
    if any(p.get("lookup") and p["status"] == "ready" for p in plan):
        try:
            R = _client()
            found = look_up(R, [p for p in plan if p.get("lookup") and p["status"] == "ready"])
            plan = [p for p in ctms_run_plan.load(found) if p["id"] in want]
        except Exception as e:             # a Stop, a lost connection, a look-up refused: those items wait
            not_looked = f"{type(e).__name__}: {e}" if not isinstance(e, Failed) else str(e)
    order = sorted(plan, key=lambda p: want.index(p["id"]))
    typed = [p for p in order if p["status"] == "ready" and not p.get("lookup")]
    to_file, stopped = [], ""
    for p in order:
        if p["status"] == "done":
            ctms_todo.done(p["id"])
            why = (p.get("explain") or ["CTMS has no line left to update"])[0]
            results.append({"id": p["id"], "ok": True, "said": f"{why} - ticked off"})
            to_file.append((results[-1], p))
            continue
        if p["status"] != "ready":
            why = "; ".join(c["why"] for c in p.get("checks") or [] if c.get("why"))
            results.append({"id": p["id"], "ok": False, "waits": True,
                            "said": f"not run - {p['status']}" + (f": {why}" if why else "")})
            continue
        if p.get("lookup"):                # looked up and still not known, or the look-up itself failed
            results.append({"id": p["id"], "ok": False, "waits": True,
                            "said": f"not run - {not_looked or 'the CTMS look-up did not reach it'}"})
            continue
        try:
            R = R or _client()
            tell(R, run_id, " / ".join(p.get("lines") or p.get("orders") or []), results)
            out = do_item(R, p, first=p is typed[0], last=p is typed[-1])
        except Exception as e:             # the client's own Stop, a lost connection
            results.append({"id": p["id"], "ok": False, "said": f"{type(e).__name__}: {e}"})
            stopped = results[-1]["said"]
            break
        if out["done"]:
            ctms_todo.done(p["id"])
            results.append({"id": p["id"], "ok": True, "said": out["said"]})
            if p["kind"] == "update":
                to_file.append((results[-1], p))
        else:
            results.append({"id": p["id"], "ok": False, "held": out["held"], "said": out["said"]})
            if not out["clean"] and not out["held"]:
                stopped = out["said"]
                break
    if R is not None:
        tell(R, run_id, "the email chains" if to_file else "", results)
    for r, p in to_file:
        r["said"] += FILE(p)
    ok = sum(1 for r in results if r["ok"])
    held = [r["said"] for r in results if r.get("held")]
    waits = [r["said"] for r in results if r.get("waits")]
    wrong = [r["said"] for r in results if not r["ok"] and not r.get("held") and not r.get("waits")]
    left = len(want) - len(results)
    seconds = round(time.time() - t0, 1)
    said = (f"{ok} of {len(want)} done in CTMS in {took(seconds)}"
            + (f"; held, CTMS has it already: {' | '.join(held)}" if held else "")
            + (f"; {' | '.join(waits)}" if waits else "")
            + (("; stopped at: " if stopped else "; not done: ") + " | ".join(wrong) if wrong else "")
            + (f"; {left} not started" if left else ""))
    return {"ok": ok == len(want), "said": said, "results": results, "seconds": seconds}


def main(argv):
    if len(argv) < 3 or argv[1] != "run":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args, run_id = argv[2:], 0
    if args[0] == "--run":
        run_id = int(args[1]) if str(args[1]).isdigit() else 0
        args = args[2:]
    out = run(args, run_id)
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
