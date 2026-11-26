"""The CTMS job queue (his 26/11 "Yes, build it" - the faster CTMS). His 25/11: "if you have to do something in CTMS, if
you're slow about it, we're gonna end up being stuck on a task for like 20 minutes ... whilst like 4 other things pop
up in the inbox". CTMS jobs wait their turn here and run one after another by themselves on the work PC, each checked
by its own route, while email and everything else carry on.

A job is one or more routes of ctms_routes.py, run in order: "set the price, then resend" is one job of two steps, and
the resend never runs if the price stopped. A job runs only when CTMS is ready for it - the work PC online, "Claude can
act" on with time left, CTMS's window found, nothing else running on the bridge and no booking going (Book's lock).
Not ready: the queue waits, untouched, and the agent tries again a minute later. A step that stops ends its job there,
"stopped", never tried again by itself (his rule for CTMS changes: one go, read back) - Again, his tap after a look,
runs it from the step that stopped. His phone hears as each job finishes; a stop says why.

    python ctms_queue.py add [--what "..."] [--by NAME] -- ROUTE ARGS... [;; ROUTE ARGS...]
    python ctms_queue.py list
    python ctms_queue.py run           the agent's: the jobs, one at a time, while CTMS is ready
    python ctms_queue.py drop ID       a job still waiting, taken off
    python ctms_queue.py again ID      a stopped job back in the queue, from the step that stopped

The routes keep their own rails: without --commit a route only rehearses, and raw clicks (press, menu) are never
queued. Every command but list ends with one JSON line, {"ok", "said", ...}, for the home agent.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_ctms_queue.json")
DUE = os.path.join(HERE, "_ctms_queue_due")               # a job was added: the agent starts the runner now
PUSH_DUE = os.path.join(HERE, "_assist_push_due")         # the agents push the dashboard's panel now
NEVER = ("press", "menu")                                 # raw clicks: never a job
SEP = ";;"
STEP_WAIT = 900                                           # seconds one route may take
KEEP = timedelta(days=2)                                  # finished jobs are kept this long, for the card
LEFT = 120                                                # "Claude can act" must have this many seconds left
STATES = ("queued", "running", "done", "stopped", "dropped")


class Refused(RuntimeError):
    """Not a job the queue takes: said, nothing queued."""


# ---------- the store ----------
def _now():
    return datetime.now()


def _stamp(t=None):
    return (t or _now()).strftime("%Y-%m-%d %H:%M:%S")


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("jobs"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"jobs": [], "paused": "", "checked_at": ""}


def save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    for _ in range(50):
        try:
            os.replace(tmp, PATH)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(tmp, PATH)


def _touch(path):
    try:
        open(path, "w").close()
    except OSError:
        pass


def _lock(name, wait):
    try:
        import outlook_gate
        return outlook_gate.named_lock(name, wait)
    except Exception:
        return True


def _unlock(h):
    if h not in (None, True):
        try:
            import outlook_gate
            outlook_gate.release(h)
        except Exception:
            pass


def _change(fn):
    """fn(d) under the store's lock, saved. -> what fn gave."""
    h = _lock("ctms_queue_store", 30)
    if h is None:
        raise Refused("the CTMS queue is busy - try again in a moment")
    try:
        d = load()
        out = fn(d)
        save(d)
        return out
    finally:
        _unlock(h)
        _touch(PUSH_DUE)


def _prune(d, now):
    cut = _stamp(now - KEEP)
    d["jobs"] = [j for j in d["jobs"] if j.get("state") in ("queued", "running", "stopped")
                 or str(j.get("ended_at") or j.get("queued_at") or "") >= cut]


# ---------- a job ----------
def check_step(step):
    """One step as the queue takes it: a named route of ctms_routes.py, plain words after it. -> the step."""
    step = [str(x) for x in step or ()]
    if not step:
        raise Refused("an empty step")
    name = step[0]
    if name in NEVER or not re.fullmatch(r"[a-z][a-z-]{2,30}", name):
        raise Refused(f"'{name}' isn't a CTMS route the queue runs")
    try:
        import ctms_routes
        if name not in ctms_routes.ROUTES:
            raise Refused(f"there is no CTMS route '{name}' (ctms_routes.py list)")
    except ImportError:
        pass
    if any("\n" in x or len(x) > 300 for x in step):
        raise Refused("a step's words aren't plain")
    return step


def split_steps(argv):
    """`trip-price MAN 440 --commit ;; trip-resend MAN --commit` -> [[...], [...]]."""
    steps, cur = [], []
    for x in argv:
        if x == SEP:
            if cur:
                steps.append(cur)
            cur = []
        else:
            cur.append(x)
    if cur:
        steps.append(cur)
    return steps


def _what(steps):
    return " then ".join(" ".join(x for x in s if x != "--commit") for s in steps)[:160]


def add(steps, what="", by="", assist=None, now=None):
    """A job at the back of the queue. -> the job. The agent starts the runner (DUE)."""
    now = now or _now()
    steps = [check_step(s) for s in steps or ()]
    if not steps:
        raise Refused("a job needs at least one route")
    job = {"id": "q" + hashlib.sha1(f"{steps}|{_stamp(now)}|{time.time()}".encode()).hexdigest()[:8],
           "what": (str(what or "").strip() or _what(steps))[:200], "by": str(by or "")[:40], "steps": steps,
           "state": "queued", "step": 0, "queued_at": _stamp(now), "started_at": "", "ended_at": "", "said": "",
           "notices": [], "results": []}
    if assist:
        job["assist"] = {"sid": str(assist.get("sid") or ""), "n": int(assist.get("n") or 0)}

    def go(d):
        _prune(d, now)
        d["jobs"].append(job)
        return job
    _change(go)
    _touch(DUE)
    return job


def waiting(d=None):
    """Jobs in the queue still to run."""
    return [j for j in (d or load())["jobs"] if j.get("state") == "queued"]


def drop(jid):
    def go(d):
        j = next((x for x in d["jobs"] if x.get("id") == jid), None)
        if j is None:
            raise Refused("that job isn't in the queue")
        if j["state"] != "queued":
            raise Refused(f"it's {j['state']} - only a job still waiting can be taken off")
        j.update(state="dropped", ended_at=_stamp(), said="Taken off the queue.")
        return j
    return _change(go)


def again(jid):
    def go(d):
        j = next((x for x in d["jobs"] if x.get("id") == jid), None)
        if j is None:
            raise Refused("that job isn't in the queue")
        if j["state"] != "stopped":
            raise Refused(f"it's {j['state']} - Again is for a job that stopped")
        j.update(state="queued", queued_at=_stamp(), said=f"Again, from step {j.get('step', 0) + 1}.")
        return j
    out = _change(go)
    _touch(DUE)
    return out


# ---------- ready? ----------
def ready():
    """(True, "") when CTMS can take a job now; (False, why not in his words)."""
    h = _lock("book_run", 0)
    if h is None:
        return False, "a booking is running"
    _unlock(h)
    try:
        import ctms_remote as R
        if not R.BASE:
            R.BASE, R.KEY = R._desk()
        code, st = R.http("GET", "/api/ctms/status")
    except Exception as e:
        return False, f"the dashboard couldn't be asked ({str(e)[:80]})"
    if code != 200:
        return False, f"the dashboard answered {code}"
    s, c = st.get("state") or {}, st.get("control") or {}
    if not st.get("online"):
        return False, "the work PC is offline"
    if s.get("control") is False:
        return False, "the work PC is set to look only"
    if not c.get("armed"):
        return False, '"Claude can act" is off'
    if int(c.get("left") or 0) < LEFT:
        return False, '"Claude can act" is about to run out'
    if not (s.get("window") or {}).get("found"):
        return False, "CTMS isn't open on the work PC"
    if st.get("running"):
        return False, f"the work PC is busy ({(st['running'] or {}).get('action') or 'a job'})"
    return True, ""


# ---------- running ----------
def run_step(step):
    """One route, to its end. -> {"ok", "said", "seconds", "notices"} from its ROUTE_RESULT."""
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "ctms_routes.py")] + list(step), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=STEP_WAIT, cwd=HERE,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        out = str(p.stdout or "")
    except subprocess.TimeoutExpired:
        return {"ok": False, "said": f"it took over {STEP_WAIT // 60} minutes - look at CTMS before anything else",
                "seconds": round(time.time() - t0, 1), "notices": []}
    except OSError as e:
        return {"ok": False, "said": f"the route couldn't start ({e})", "seconds": 0, "notices": []}
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("ROUTE_RESULT ")), "")
    try:
        r = json.loads(line[len("ROUTE_RESULT "):]) if line else {}
    except ValueError:
        r = {}
    if not r:
        tail = (out.strip().splitlines() or [str(p.stderr or "").strip() or "no answer"])[-1]
        return {"ok": False, "said": tail[:300], "seconds": round(time.time() - t0, 1), "notices": []}
    return {"ok": bool(r.get("ok")), "said": str(r.get("said") or "")[:300],
            "seconds": r.get("seconds") or round(time.time() - t0, 1),
            "notices": [str(x)[:160] for x in r.get("notices") or []]}


def _ring(title, body):
    """His phone (push_notify), never in the tests."""
    if os.environ.get("R2_NO_PUSH"):
        return
    try:
        import push_notify
        if push_notify.count():
            push_notify.notify(title[:80], body[:160], "/", "ctms-queue")
    except Exception:
        pass


def _tell_assist(job):
    """A CTMS change he said yes to on an email's job: the job hears how it went."""
    a = job.get("assist") or {}
    if not a.get("sid"):
        return
    try:
        import inbox_assist
        inbox_assist.ctms_done(a["sid"], int(a.get("n") or 0), job["state"] == "done", job.get("said") or "")
    except Exception:
        pass


def run(step_run=run_step, is_ready=ready, ring=_ring, now=None):
    """The jobs, oldest first, one at a time, while CTMS is ready. One runner at a time. -> what it did, in words."""
    h = _lock("ctms_queue_run", 0)
    if h is None:
        return "a runner is going already"
    did = []
    try:
        while True:
            d = load()
            if not waiting(d):
                break
            ok, why = is_ready()
            if not ok:
                def pause(d):
                    d.update(paused=why, checked_at=_stamp(now))
                _change(pause)
                break

            def start(d):
                j = next((x for x in d["jobs"] if x.get("state") == "queued"), None)
                if j is not None:
                    j.update(state="running", started_at=_stamp(now), said="")
                    d.update(paused="", checked_at=_stamp(now))
                return dict(j) if j else None
            job = _change(start)
            if job is None:
                break
            for i in range(int(job.get("step") or 0), len(job["steps"])):
                res = step_run(job["steps"][i])

                def note(d, i=i, res=res):
                    j = next(x for x in d["jobs"] if x["id"] == job["id"])
                    j.setdefault("results", []).append(dict(res, route=job["steps"][i][0], at=_stamp(now)))
                    j["notices"] = (j.get("notices") or []) + res.get("notices", [])
                    if res["ok"]:
                        j["step"] = i + 1
                    else:
                        j.update(state="stopped", ended_at=_stamp(now),
                                 said=f"{job['steps'][i][0]} stopped: {res['said']}")
                    return dict(j)
                job = _change(note)
                if not res["ok"]:
                    break
            if job["state"] == "running":
                def finish(d):
                    j = next(x for x in d["jobs"] if x["id"] == job["id"])
                    last = (j.get("results") or [{}])[-1]
                    j.update(state="done", ended_at=_stamp(now), said=str(last.get("said") or "done")[:300])
                    return dict(j)
                job = _change(finish)
            did.append(job)
            _tell_assist(job)
            if job["state"] == "done":
                extra = (" CTMS said: " + "; ".join(job["notices"])) if job.get("notices") else ""
                ring("CTMS done: " + job["what"], (job.get("said") or "done") + extra)
            else:
                ring("CTMS stopped: " + job["what"], job.get("said") or "look at CTMS")
    finally:
        _unlock(h)
        _touch(PUSH_DUE)
    if not did:
        return "nothing ran" + (f" - waiting: {load().get('paused')}" if waiting() else "")
    stopped = sum(1 for j in did if j["state"] != "done")
    return f"{len(did) - stopped} done" + (f", {stopped} stopped" if stopped else "") + \
        (f"; still waiting: {len(waiting())} ({load().get('paused')})" if waiting() else "")


# ---------- the dashboard ----------
def panel(d=None):
    d = d or load()
    jobs = sorted(d["jobs"], key=lambda j: str(j.get("queued_at") or ""), reverse=True)
    order = {"running": 0, "queued": 1, "stopped": 2}
    jobs.sort(key=lambda j: order.get(j.get("state"), 3))
    keep = ("id", "what", "by", "state", "step", "queued_at", "started_at", "ended_at", "said", "notices")
    return {"jobs": [dict({k: j.get(k) for k in keep}, steps=len(j.get("steps") or []),
                          seconds=round(sum(float(r.get("seconds") or 0) for r in j.get("results") or []), 1))
                     for j in jobs[:20]],
            "waiting": len(waiting(d)), "paused": d.get("paused") or "", "checked_at": d.get("checked_at") or ""}


def _say(ok, said, **extra):
    print(json.dumps(dict({"ok": ok, "said": said}, **extra), ensure_ascii=False))
    return 0 if ok else 1


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        p = panel()
        print(f"{p['waiting']} waiting" + (f" - paused: {p['paused']}" if p["paused"] else ""))
        for j in p["jobs"]:
            print(f"  {j['id']} {j['state']:8} {j['what'][:70]} | {j['said'][:80]}")
        return 0
    if cmd == "add":
        rest = argv[2:]
        if "--" not in rest:
            return _say(False, "add [--what \"...\"] [--by NAME] -- ROUTE ARGS... [;; ROUTE ARGS...]")
        i = rest.index("--")
        opts, steps = rest[:i], split_steps(rest[i + 1:])
        what = opts[opts.index("--what") + 1] if "--what" in opts and opts.index("--what") + 1 < len(opts) else ""
        by = opts[opts.index("--by") + 1] if "--by" in opts and opts.index("--by") + 1 < len(opts) else "Claude"
        try:
            job = add(steps, what, by)
        except Refused as e:
            return _say(False, f"Not queued: {e}")
        n = len(waiting())
        return _say(True, f"Queued ({job['id']}): {job['what']} - {n} waiting; it runs when CTMS is ready.",
                    id=job["id"])
    if cmd == "run":
        try:
            said = run()
        except Exception as e:
            return _say(False, f"The CTMS queue stopped ({type(e).__name__}: {e}).")
        return _say(True, "CTMS queue: " + said)
    if cmd in ("drop", "again"):
        jid = argv[2] if len(argv) > 2 else ""
        try:
            j = (drop if cmd == "drop" else again)(jid)
        except Refused as e:
            return _say(False, str(e))
        return _say(True, ("Taken off: " if cmd == "drop" else "Back in the queue: ") + j["what"])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))
