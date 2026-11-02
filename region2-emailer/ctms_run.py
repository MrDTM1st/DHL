"""
The CTMS to-do run - the ready items of the plan (ctms_run_plan) typed into CTMS on the work PC one at a time, each
read back before it counts as done (his ask 01/11; the Run button on the dashboard's CTMS page).

  note     the -1-1 line opened and its Special Instructions read: ending with the note already - nothing to type -
           else the note at its end, read back, Save, Close; opened again, it must end with the note
  look-up  an update the plan marks "lookup" - its open lines or weight not known yet - is looked up first, on the work
           PC, and planned again; searches and reads only. What that turns up (a Veh Type on it, a doubt) holds it
  update   for each open line: opened, its Veh Type box, deliver comment and Services read, closed - a Veh Type or a
           comment already there means CTMS has it: HELD, nothing typed, the run goes on (his 02/11), unless he
           picked "Type it in anyway"; then the one order-update batch -
           times, the deliver side's comment, services off and on (HIAB and MOFFETT live there), the Veh Type only
           when the box is empty (never a Moffett vehicle - his rule 01/11) - Save
           (the schedule question OK'd) and Close; then Order Summary read: Ready At and Deliver By must be what was
           typed. A Veh Type already set to another vehicle stops it before anything is typed
  done     CTMS has no line left to update - ticked off, nothing typed

An update done (or found done) files its email chain away - his rule (30/10) - through file_chain.

The first thing that isn't as expected stops the run, and CTMS is left as it is for him to look at - nothing is
saved past that point and the rest wait. Each item done is ticked off the CTMS to-do.

    python ctms_run.py run ID [ID ...]      prints a JSON line at the end: {"ok", "said", "results"}
"""
import contextlib
import io
import json
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROWS = 14                  # the Services grid's rows, as the Access Bridge reads them
# The open order's Veh Type box (its Detail tab), and what it shows - pictures of CTMS's own vehicle names, cut 01-02/11.
# Only these are ever picked: "the vehicle tab, we don't use that rigid Moffett thing ... We just use the 40-foot
# rigid" (his rule 01/11) - a HIAB or a Moffett goes in Services.
VEH_BOX = "1052,298,1204,324"
VEH_SHOWS = {"rigid": ("box-veh-rigid", "NR_Rigid (Up to 40ft)"), "artic": ("box-veh-artic", "NR_40ft Artic Flatbed"),
             "60ft": ("box-veh-60ft", "NR_60ft Artic Flat"), "80ft": ("box-veh-80ft", "NR_80ft-115ft trombone"),
             "tipper": ("box-veh-tipper", "NR_26ft 8 X 4 Rigid Tipper")}
LOOK_UP_SECONDS = 420              # the bridge's own limit on a look-up (CHECK_SECONDS), and a margin


class Failed(Exception):
    pass


class Held(Exception):
    """CTMS has the update already - nothing typed, the item stays for him, the run goes on to the next."""


# LOC Detail, then its Comments sub-tab - where the deliver side's comment is read before anything is typed
LOC_COMMENTS = ["anchor", "anchor window", "click 365,187 react box=20,200,1250,700 timeout=10",
                "click 180,643 react box=20,500,1250,760 timeout=10"]


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


def _elements(R):
    result, payload = R.ask("fields", wait_total=150)
    if not result.get("ok") or not payload:
        raise Failed(f"CTMS's fields could not be read: {result.get('detail')}")
    return payload.get("elements") or []


def _frame(els, prefix):
    """The elements inside the first internal frame whose name starts with `prefix`."""
    i0 = next((i for i, e in enumerate(els) if e.get("r") == "internal frame"
               and str(e.get("nm") or "").startswith(prefix)), None)
    if i0 is None:
        return None
    lv0, out = els[i0].get("lv", 0), []
    for e in els[i0 + 1:]:
        if e.get("lv", 0) <= lv0:
            break
        out.append(e)
    return out


def special_instructions(els):
    """The open order's Special Instructions - None when no order card is up."""
    card = _frame(els, "Order details for")
    if card is None:
        return None
    for e in card:
        nm = re.sub(r"\s+", " ", str(e.get("nm") or ""))
        if e.get("r") == "text" and "Special Instructions" in nm:
            return str(e.get("v") or "")
    return ""


def deliver_comment(els):
    """The open order's deliver-side comment (LOC Detail > Comments): the right-hand of the two boxes under the
    selected Comments tab - None when that tab isn't up."""
    card = _frame(els, "Order details for")
    if card is None:
        return None
    i = next((k for k, e in enumerate(card) if e.get("r") == "page tab" and e.get("nm") == "Comments"
              and "selected" in (e.get("st") or [])), None)
    if i is None:
        return None
    boxes = []
    for e in card[i + 1:]:
        if e.get("r") == "page tab":
            break
        if e.get("r") == "text" and (e.get("at") or [-1])[0] >= 0:
            boxes.append(e)
    if len(boxes) < 2:
        return None
    return str(max(boxes, key=lambda e: e["at"][0]).get("v") or "")


def services(els):
    """The open order's Service Ids, top row first - the Services tab's first column."""
    card = _frame(els, "Order details for") or []
    i = next((k for k, e in enumerate(card) if e.get("r") == "push button" and e.get("nm") == "Charge Revenue"),
             None)
    if i is None:
        raise Failed("the Services tab did not read as expected")
    texts = [e for e in card[i + 1:] if e.get("r") == "text"][:SERVICE_ROWS]
    return [str(e.get("v") or "").strip().upper() for e in texts if str(e.get("v") or "").strip()]


def summary_line(els, ref):
    """Order Summary's row for one line: {ready_at, deliver_by} - None when it isn't listed."""
    frame = _frame(els, "Order Summary")
    if frame is None:
        return None
    cols = {}
    for e in frame:
        m = re.fullmatch(r"Enter value for : (\w+)", str(e.get("nm") or ""))
        if e.get("r") == "text" and m and m.group(1) in ("EXTERNAL_REF", "EARLY_AVAIL", "LATE_DEL") and e.get("at"):
            cols.setdefault(m.group(1), []).append((e["at"][1], str(e.get("v") or "").strip()))
    down = {k: [v for _, v in sorted(c)] for k, c in cols.items()}
    for n, r in enumerate(down.get("EXTERNAL_REF") or []):
        if r == ref:
            pick = lambda k: (down.get(k) or [""] * (n + 1))[n] if n < len(down.get(k) or []) else ""  # noqa: E731
            return {"ready_at": pick("EARLY_AVAIL"), "deliver_by": pick("LATE_DEL")}
    return None


def _ends(window):
    """("dd/mm/yy HH:MM" start, "dd/mm/yy HH:MM" end) of a recipe window."""
    m = re.fullmatch(r"(\d{2}/\d{2}/\d{2}) (\d{2}:\d{2})-(?:(\d{2}/\d{2}/\d{2}) )?(\d{2}:\d{2})", window or "")
    if not m:
        return "", ""
    return f"{m.group(1)} {m.group(2)}", f"{m.group(3) or m.group(1)} {m.group(4)}"


def _ns(**kw):
    base = dict(order="", collect=None, deliver=None, comments=None, add_service=None, remove_service_row=None,
                veh=None, ballast=False, note="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _open(R, ref):
    card = R._on_screen("os-card", R.CARD_BOX)
    rc, said = _quiet(R.send_batch, "order-update", R.parse_steps(R.order_update_items(_ns(order=ref),
                                                                                       card_open=card)), [ref])
    if rc:
        raise Failed(f"{ref} would not open: {said.strip().splitlines()[0] if said.strip() else rc}")


def _close(R):
    """The open order's own Close, wherever CTMS has scrolled to. A plain click misses it when the page is scrolled and
    lands on the window behind, which hides the order instead of closing it (02/11)."""
    rc, _ = _quiet(R.send_batch, "order-close", R.parse_steps(["anchor", "click 1000,37 after=0.4", "anchor window",
                                                               "click 424,733 react timeout=15"]))
    if rc:
        raise Failed("the order would not close")


def veh_now(R):
    """What the open order's Veh Type box shows: a key of VEH_SHOWS, "" when empty - or None, another vehicle."""
    if R._on_screen("box-veh-empty", VEH_BOX):
        return ""
    for k, (tpl, _) in VEH_SHOWS.items():
        if R._on_screen(tpl, VEH_BOX):
            return k
    return None


def run_note(R, p):
    ref, note = p["lines"][0], p["set"]["note"]
    _open(R, ref)
    si = special_instructions(_elements(R))
    if si is None:
        raise Failed(f"{ref}: its card did not read")
    if si.rstrip().endswith(note.strip()):
        _close(R)
        return f"{ref}: '{note.strip()}' was there already"
    rc, _ = _quiet(R.run_steps, "order-note", R.RUN_STEPS["order-note"](_ns(note=note)))
    if rc or not (special_instructions(_elements(R)) or "").rstrip().endswith(note.strip()):
        raise Failed(f"{ref}: the note did not read back - left open, not saved")
    rc, _ = _quiet(R.order_save_close)
    if rc:
        raise Failed(f"{ref}: the save did not go through - see CTMS")
    _open(R, ref)
    held = (special_instructions(_elements(R)) or "").rstrip().endswith(note.strip())
    _close(R)
    if not held:
        raise Failed(f"{ref}: opened again, the note is not there")
    return f"{ref}: '{note.strip()}' added"


def run_update(R, p):
    s, done = p["set"], []
    want = s.get("services") or {}
    for ref in p["lines"]:
        _open(R, ref)
        now = veh_now(R)
        # typed in already - a Veh Type on it, or a deliver comment: the reply went in before (by hand, or a run), so
        # nothing is typed over it unless he picked "type it in anyway" (his 02/11 "yeah, fix it" - the 01/11 repeats
        # of 7116527/8 would have wiped a second contact from the comment)
        if not s.get("anyway"):
            rc, _ = _quiet(R.send_batch, "loc-comments", R.parse_steps(LOC_COMMENTS))
            said = deliver_comment(_elements(R)) if not rc else None
            if said is None:
                raise Failed(f"{ref}: its LOC Detail comments would not read - left open, nothing typed")
            if now != "" or said.strip():
                _close(R)
                there = [f"Veh Type {VEH_SHOWS[now][1] if now in VEH_SHOWS else 'set'}" if now != "" else "",
                         f"deliver comment '{said.strip()}'" if said.strip() else ""]
                raise Held(f"{ref}: CTMS has it already ({', '.join(x for x in there if x)}) - nothing typed; tick it "
                           "off, or pick 'Type it in anyway' on the item")
        # the vehicle first, before anything is typed: the list is only opened on an empty box - on a filled one it
        # opens at its own value and the scroll lands elsewhere (6055920, 01/11) - and a vehicle already there that
        # isn't the plan's is his, never changed by the run
        veh = s.get("veh")
        if veh:
            if now == veh:
                veh = None
            elif now != "":
                _close(R)
                raise Failed(f"{ref}: its Veh Type is already "
                             + (VEH_SHOWS[now][1] if now else "a vehicle other than the ones the run picks")
                             + f", not {VEH_SHOWS[veh][1]} - left as it is, nothing typed")
        rc, _ = _quiet(R.send_batch, "services-tab",
                       R.parse_steps(["anchor", "anchor window", "click 750,186 react box=20,200,1250,700 timeout=10"]))
        if rc:
            raise Failed(f"{ref}: its Services tab would not open")
        have = services(_elements(R))
        _close(R)
        removes = [i + 1 for i, sid in enumerate(have) if sid in want and not want[sid]]
        adds = [code for code, on in want.items() if on and code not in have]
        if s.get("storage") and "STORAGE" not in have:
            adds.append(f"STORAGE:{s['storage']}")
        a = _ns(order=ref, collect=s.get("collect"), deliver=s.get("deliver"), comments=s.get("comments"),
                add_service=adds or None, remove_service_row=removes or None, veh=veh)
        card = R._on_screen("os-card", R.CARD_BOX)
        rc, said = _quiet(R.send_batch, "order-update", R.parse_steps(R.order_update_items(a, card_open=card)), [ref])
        if rc:
            raise Failed(f"{ref}: the update stopped part way - left open, NOT saved: "
                         f"{said.strip().splitlines()[0] if said.strip() else ''}")
        rc, _ = _quiet(R.order_save_close)
        if rc:
            raise Failed(f"{ref}: the save did not go through - see CTMS")
        got = summary_line(_elements(R), ref)
        c0, _ = _ends(s.get("collect"))
        _, d1 = _ends(s.get("deliver"))
        if got is None:
            raise Failed(f"{ref}: saved, but Order Summary did not list it to check")
        if (c0 and got["ready_at"] != c0) or (d1 and got["deliver_by"] != d1):
            raise Failed(f"{ref}: saved, but CTMS reads Ready At {got['ready_at']} / Deliver By "
                         f"{got['deliver_by']} - not {c0} / {d1}")
        bits = [x for x in (f"collect {s['collect']}" if s.get("collect") else "",
                            f"deliver {s['deliver']}" if s.get("deliver") else "",
                            VEH_SHOWS[veh][1] if veh else (f"{VEH_SHOWS[s['veh']][1]} already" if s.get("veh") else ""),
                            ("+" + "+".join(c.split(":")[0] for c in adds)) if adds else "",
                            f"-{len(removes)} service(s)" if removes else "") if x]
        done.append(f"{ref}: {', '.join(bits)}")
    return "; ".join(done)


def file_emails(p):
    """His rule (30/10): once an order is updated, its email chain is filed away - the site thread's mails still in
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
    the bridge's own look-up does: searches and reads, nothing typed. {"ref|date": what it found}."""
    orders = {f"{p['lookup']['ref']}|{p['lookup']['date']}": dict(p["lookup"], veh=True) for p in plan}
    (result, payload), _ = _quiet(R.ask, "ctms_check", wait_total=LOOK_UP_SECONDS,
                                  orders=[dict(o, key=k) for k, o in orders.items()])
    if not result.get("ok"):
        raise Failed(f"CTMS could not be looked up: {result.get('detail')}")
    return (payload or {}).get("orders") or {}


def run(ids):
    import ctms_run_plan
    import ctms_todo
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
    for p in sorted(plan, key=lambda p: want.index(p["id"])):
        if p["status"] == "done":
            ctms_todo.done(p["id"])
            why = (p.get("explain") or ["CTMS has no line left to update"])[0]
            results.append({"id": p["id"], "ok": True, "said": f"{why} - ticked off" + FILE(p)})
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
            said = run_note(R, p) if p["kind"] == "note" else run_update(R, p)
        except Held as e:                  # CTMS has it - left for him, and the run goes on
            results.append({"id": p["id"], "ok": False, "held": True, "said": str(e)})
            continue
        except Failed as e:
            results.append({"id": p["id"], "ok": False, "said": str(e)})
            break
        except Exception as e:             # the client's own Stop, a lost connection
            results.append({"id": p["id"], "ok": False, "said": f"{type(e).__name__}: {e}"})
            break
        ctms_todo.done(p["id"])
        if p["kind"] == "update":
            said += FILE(p)
        results.append({"id": p["id"], "ok": True, "said": said})
    ok = sum(1 for r in results if r["ok"])
    held = [r["said"] for r in results if r.get("held")]
    waits = [r["said"] for r in results if r.get("waits")]
    left = len(want) - len(results)
    stopped = results and not results[-1]["ok"] and not results[-1].get("held") and not results[-1].get("waits")
    said = (f"{ok} of {len(want)} done in CTMS" + (f"; held, CTMS has it already: {' | '.join(held)}" if held else "")
            + (f"; {' | '.join(waits)}" if waits else "")
            + (f", stopped at: {results[-1]['said']}" if stopped else "") + (f"; {left} not started" if left else ""))
    return {"ok": ok == len(want), "said": said, "results": results}


def main(argv):
    if len(argv) < 3 or argv[1] != "run":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = run(argv[2:])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
