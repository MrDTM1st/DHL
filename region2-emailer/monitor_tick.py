"""Live Outlook monitor - near-real-time watch of the mailbox.

Run every ~60s by the supervisor (single instance). Watches the Inbox + the
Synergy Upload folder and reacts the moment something relevant lands:
  * a new Haulier Extract / BS batch  -> auto-BUILD today's batch (never sends)
    and flag it ready-to-review on the dashboard,
  * new inbox mail                    -> run the reply/booking check so bookings
    show within a minute, not the 20-minute cycle,
  * a new ad-hoc Haulage Request / DTS form -> flag it on the dashboard.

Seeds silently on the first run so it never floods on startup. Nothing is ever
sent - it only builds/notifies. State + watermark live in _monitor_seen.json.
"""
import os, sys, json, time, subprocess
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_drafts as bd

SEEN = os.path.join(HERE, "_monitor_seen.json")
CLOUD = os.path.join(HERE, "cloud.json")
LOCAL_CP = "http://127.0.0.1:8787"
PHASE2_THROTTLE = 180     # seconds between reply-checks even if mail keeps arriving
FORM_HINTS = ("haulage request", "transport request", "request form", "dts")


def _load():
    try:
        return json.load(open(SEEN, encoding="utf-8"))
    except Exception:
        return None


def _save(d):
    tmp = SEEN + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, SEEN)


def _cps():
    """Control planes to report to: the local one (no key) + the cloud one."""
    out = [(LOCAL_CP, "")]
    try:
        c = json.load(open(CLOUD, encoding="utf-8"))
        if c.get("url") and c.get("agent_key"):
            out.append((c["url"].rstrip("/"), c["agent_key"]))
    except Exception:
        pass
    return out


def _post(path, payload):
    import urllib.request
    for url, key in _cps():
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(url + path, data=body,
                    headers={"Content-Type": "application/json", "X-Auth": key}, method="POST")
            urllib.request.urlopen(req, timeout=8)
        except Exception:
            pass


def report(state, detail, output="", email=None):
    _post("/api/status", {"state": state, "detail": detail, "output": output, "email": email})


def push_tracker():
    try:
        _post("/api/tracker", json.load(open(os.path.join(HERE, "tracker.json"), encoding="utf-8")))
    except Exception:
        pass


def run(args):
    p = subprocess.run([sys.executable] + args, cwd=HERE, capture_output=True, text=True, timeout=600)
    return (p.stdout or "") + (p.stderr or "")


def _folders(ns):
    dhl = bd.dhl_store(ns)
    inbox = bd.sub(dhl, "Inbox")
    adhoc = bd.sub(inbox, "ADHOC") if inbox else None
    syn = bd.sub(adhoc, "Synergy Upload") if adhoc else None
    return inbox, syn


def _scan(folder, limit):
    if folder is None:
        return
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    n = 0
    for it in items:
        n += 1
        if n > limit:
            break
        try:
            atts = [str(it.Attachments.Item(j).FileName) for j in range(1, it.Attachments.Count + 1)]
            rt = it.ReceivedTime
            riso = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute).isoformat()
            yield (str(it.EntryID), str(it.Subject or ""), riso, atts)
        except Exception:
            continue


def main():
    try:
        import win32com.client
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        return
    inbox, syn = _folders(ns)
    state = _load()
    seed = state is None
    if seed:
        state = {"ext_ids": [], "adhoc_ids": [], "inbox_hwm": "", "last_phase2": 0}
    ext_ids = set(state.get("ext_ids", []))
    adhoc_ids = set(state.get("adhoc_ids", []))
    hwm = state.get("inbox_hwm", "")

    new_extracts, new_adhocs, new_mail = [], [], False
    new_hwm = hwm
    for folder in (inbox, syn):
        for eid, subj, riso, atts in _scan(folder, 80):
            for fn in atts:
                low = fn.lower()
                if bd.is_wanted_extract(fn, subj):
                    if eid not in ext_ids:
                        ext_ids.add(eid)
                        new_extracts.append(fn)
                elif (low.endswith((".xlsx", ".xlsm", ".pdf"))
                      and any(h in low or h in subj.lower() for h in FORM_HINTS)
                      and eid not in adhoc_ids):
                    adhoc_ids.add(eid)
                    new_adhocs.append(fn)
    for eid, subj, riso, atts in _scan(inbox, 40):
        if riso > new_hwm:
            new_hwm = riso
        if hwm and riso > hwm:
            new_mail = True

    if not seed:
        if new_extracts:
            run(["build_drafts.py", "batch"])
            try:
                batch = json.load(open(os.path.join(HERE, "_pending_batch.json"), encoding="utf-8"))
            except Exception:
                batch = []
            names = ", ".join(new_extracts[:2])
            if batch:
                loose = [e for e in batch if e.get("loose_ballast")]
                pri = ("PRIORITY - LOOSE BALLAST: "
                       + "; ".join(" / ".join(e.get("orders", [])) for e in loose[:3]) + ". ") if loose else ""
                report("batch_ready", pri + f"New extract arrived ({names}) - batch built, "
                       f"{len(batch)} email(s) to review, then send.", "", batch)
            else:
                report("done", f"New extract arrived ({names}) - nothing new to email.")
        now = time.time()
        if new_mail and now - state.get("last_phase2", 0) > PHASE2_THROTTLE:
            run(["phase2.py", "check"])
            push_tracker()
            state["last_phase2"] = now
        if new_adhocs:
            report("done", "New ad-hoc form arrived: " + ", ".join(new_adhocs[:3])
                   + " - process it from the DTS / Ad-hoc box.")

    state["ext_ids"] = list(ext_ids)[-500:]
    state["adhoc_ids"] = list(adhoc_ids)[-500:]
    state["inbox_hwm"] = new_hwm
    _save(state)


if __name__ == "__main__":
    main()
