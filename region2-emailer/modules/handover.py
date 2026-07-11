"""Holiday / send-off handover.

start() writes the state file and builds the batch handover email spec from
the tracker; the agent sends it with its existing machinery. plan_forwards()
picks which new incoming messages to forward while away. tick() runs once a
minute from the supervisor and deactivates automatically on the return date.

State file is JSON (underscore name like _handover.json keeps it out of git).
"""
import json
import os
from datetime import date, timedelta


def _save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return state


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": False}


def start(path, days, cover_name, cover_email, notes="", forward=True, today=None):
    start_d = date.fromisoformat(str(today)) if today else date.today()
    days = max(1, min(int(days), 365))
    state = {
        "active": True,
        "start": start_d.isoformat(),
        # return date: cover (and forwarding) run while today < end
        "end": (start_d + timedelta(days=days)).isoformat(),
        "cover_name": str(cover_name),
        "cover_email": str(cover_email),
        "notes": str(notes or ""),
        "forward": bool(forward),
        "forwarded_ids": [],
    }
    return _save(path, state)


def end(path):
    state = load(path)
    state["active"] = False
    return _save(path, state)


def is_active(state, today=None):
    if not state.get("active"):
        return False
    today = str(today or date.today().isoformat())
    return today < state.get("end", "")      # ISO strings compare correctly


def tick(path, today=None):
    """Call once a minute. Returns 'ended' the first tick after the return
    date, 'active' while away, else 'off'."""
    state = load(path)
    if state.get("active") and not is_active(state, today):
        state["active"] = False
        _save(path, state)
        return "ended"
    return "active" if state.get("active") else "off"


def outstanding(tracker_records):
    """Unfinished work: not emailed yet, awaiting a reply, or send-off not done."""
    return [r for r in tracker_records or []
            if not r.get("reply_at") or not r.get("sendoff_ready")]


def build_handover_email(state, tracker_records, sender_name=""):
    rows = outstanding(tracker_records)
    first = (state.get("cover_name", "").split(" ") or [""])[0]
    lines = [
        f"Hi {first or 'there'},",
        "",
        f"I'm away until {state.get('end', '')} — please cover the following Region 2 work:",
        "",
    ]
    if rows:
        for r in rows:
            orders = " / ".join(r.get("orders", [])) or "?"
            bits = []
            if not r.get("emailed_at"):
                bits.append("email not sent yet")
            elif not r.get("reply_at"):
                chase = f" (chased x{r['chases']})" if r.get("chases") else ""
                bits.append(f"awaiting reply from {r.get('to', '')}{chase}")
            if not r.get("sendoff_ready"):
                bits.append("send-off not done")
            mat = f" — {r['materials']}" if r.get("materials") else ""
            lines.append(f"  - {orders}{mat}: {', '.join(bits) or 'in progress'}")
    else:
        lines.append("  - Nothing outstanding right now — new work will be forwarded.")
    if state.get("notes"):
        lines += ["", "Notes:", state["notes"]]
    if state.get("forward"):
        lines += ["", "Replies to my tracked orders will be auto-forwarded to you while I'm away."]
    lines += ["", "Thanks!", sender_name]
    return {"to": state.get("cover_email", ""), "cc": "",
            "subject": f"Handover — Region 2 cover until {state.get('end', '')}",
            "message": "\n".join(lines)}


def plan_forwards(state, incoming, me="", today=None):
    """incoming: [{"id","sender"}] new inbox messages. Returns ids to forward.

    Never forwards mail from the cover person or from yourself, and never
    forwards the same message twice.
    """
    if not is_active(state, today) or not state.get("forward"):
        return []
    done = set(state.get("forwarded_ids", []))
    cover = state.get("cover_email", "").lower()
    me = str(me or "").lower()
    out = []
    for m in incoming or []:
        mid = str(m.get("id", ""))
        snd = str(m.get("sender", "")).lower()
        if mid and mid not in done and snd and snd not in (cover, me):
            out.append(mid)
    return out


def mark_forwarded(path, ids):
    state = load(path)
    known = set(state.get("forwarded_ids", []))
    known.update(str(i) for i in ids)
    state["forwarded_ids"] = sorted(known)[-1000:]
    return _save(path, state)


def panel_state(state):
    """The bit of state the dashboard shows (no forwarded-id noise)."""
    return {k: state.get(k) for k in
            ("active", "start", "end", "cover_name", "cover_email", "forward")}
