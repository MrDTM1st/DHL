"""
The CTMS to-do run - the ready items of the plan (ctms_run_plan) typed into CTMS on the work PC one at a time, each
read back before it counts as done (his ask 01/11; the Run button on the dashboard's CTMS page).

  note     the -1-1 line opened and its Special Instructions read: ending with the note already - nothing to type -
           else the note at its end, read back, Save, Close; opened again, it must end with the note
  update   for each open line: opened and its Services read, closed; then the one order-update batch - times, the
           deliver side's comment, services off and on, the Veh Type - Save (the schedule question OK'd) and Close;
           then Order Summary read: Ready At and Deliver By must be what was typed
  done     CTMS has no line left to update - ticked off, nothing typed

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
    rc, _ = _quiet(R.run_steps, "order-close", R.RUN_STEPS["order-close"](_ns()))
    if rc:
        raise Failed("the order would not close")


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
                add_service=adds or None, remove_service_row=removes or None, veh=s.get("veh"))
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
                            s.get("veh") or "",
                            ("+" + "+".join(c.split(":")[0] for c in adds)) if adds else "",
                            f"-{len(removes)} service(s)" if removes else "") if x]
        done.append(f"{ref}: {', '.join(bits)}")
    return "; ".join(done)


def run(ids):
    import ctms_run_plan
    import ctms_todo
    want = [str(i) for i in ids]
    plan = [p for p in ctms_run_plan.load() if p["id"] in want]
    results, R = [], None
    for p in sorted(plan, key=lambda p: want.index(p["id"])):
        if p["status"] == "done":
            ctms_todo.done(p["id"])
            results.append({"id": p["id"], "ok": True, "said": "CTMS has no line left to update - ticked off"})
            continue
        if p["status"] != "ready":
            results.append({"id": p["id"], "ok": False, "said": f"not run - {p['status']}"})
            continue
        try:
            R = R or _client()
            said = run_note(R, p) if p["kind"] == "note" else run_update(R, p)
        except Failed as e:
            results.append({"id": p["id"], "ok": False, "said": str(e)})
            break
        except Exception as e:             # the client's own Stop, a lost connection
            results.append({"id": p["id"], "ok": False, "said": f"{type(e).__name__}: {e}"})
            break
        ctms_todo.done(p["id"])
        results.append({"id": p["id"], "ok": True, "said": said})
    ok = sum(1 for r in results if r["ok"])
    left = len(want) - len(results)
    said = f"{ok} of {len(want)} done in CTMS" + (f", stopped at: {results[-1]['said']}" if results and
                                                  not results[-1]["ok"] else "") + (f"; {left} not started"
                                                                                     if left else "")
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
