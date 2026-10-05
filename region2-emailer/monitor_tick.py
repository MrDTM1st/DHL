"""Live Outlook monitor - near-real-time watch of the mailbox.

Run every ~60s by the supervisor; outlook_gate keeps it to one copy at a
time and holds it off while Outlook is Not Responding. Watches the Inbox + the
Synergy Upload folder and reacts the moment something relevant lands:
  * a new Haulier Extract / BS batch  -> auto-BUILD today's batch (never sends)
    and flag it ready-to-review on the dashboard,
  * new mail in or out                -> flag _phase2_due so the local agent runs
    the reply/booking check now (at most every 5 min after the last one
    ended), not on its 20-minute cycle,
  * a new ad-hoc Haulage Request / DTS form -> flag it on the dashboard,
  * a bounce on a delivery-details email -> bounce_escalate asks the materials
    team for an alternative contact straight away (the one thing this sends -
    Delali, 05/10/2026: "if something bounces, just immediately escalate it").

Seeds silently on the first run so it never floods on startup. Apart from the
bounce escalation it only builds/notifies. State + watermark live in
_monitor_seen.json.
"""
import os, sys, json, time, subprocess
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_drafts as bd

SEEN = os.path.join(HERE, "_monitor_seen.json")
CLOUD = os.path.join(HERE, "cloud.json")
LOCAL_CP = "http://127.0.0.1:8787"
PHASE2_DUE = os.path.join(HERE, "_phase2_due")   # agent.py runs the reply check
BUILD_TRIES = 3           # an extract whose auto-build keeps failing is given up after this
TICK_MAX_AGE = 25 * 60    # a tick alive this long is stuck on a COM call
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


def run(args):
    """Run a child job -> (returncode, output). Never raises: a child that
    times out or crashes must not take the tick down with it (the tick's state
    is already saved by then). A timeout or launch failure is returncode -1."""
    try:
        p = subprocess.run([sys.executable] + args, cwd=HERE, capture_output=True,
                           text=True, timeout=600)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, f"FAILED {' '.join(args)}: {e}"


def _folders(ns):
    dhl = bd.dhl_store(ns)
    inbox = bd.sub(dhl, "Inbox")
    adhoc = bd.sub(inbox, "ADHOC") if inbox else None
    syn = bd.sub(adhoc, "Synergy Upload") if adhoc else None
    sent = bd.sub(dhl, "Sent Items")
    return inbox, syn, sent


def _scan(folder, limit):
    if folder is None:
        return
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        try:
            items.Sort("[SentOn]", True)
        except Exception:
            pass
    n = 0
    for it in items:
        n += 1
        if n > limit:
            break
        try:
            atts = [str(it.Attachments.Item(j).FileName) for j in range(1, it.Attachments.Count + 1)]
            rt = None
            for attr in ("ReceivedTime", "SentOn", "LastModificationTime"):   # inbox vs sent
                v = getattr(it, attr, None)
                if v is not None and 1990 < getattr(v, "year", 0) < 2100:
                    rt = v
                    break
            if rt is None:
                continue
            riso = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute).isoformat()
            yield (str(it.EntryID), str(it.Subject or ""), riso, atts)
        except Exception:
            continue


TREE_EVERY = 900     # full Inbox-tree BS sweep cadence (seconds)


def _tree_bs(ns, known_ids, days=30, per_folder=60):
    """BS batch/Ack emails ANYWHERE in the Inbox tree. Emails get filed fast -
    by hand or by rules - and on 21/07 two BS Acks landed straight in
    Regions/Region 2/Completed, which nothing watched, so their orders were
    never emailed. This walks every Inbox subfolder on a slow cadence; the
    per-folder cap plus the age break keeps the COM cost sane, and known_ids
    keeps it incremental."""
    out = []
    dhl = bd.dhl_store(ns)
    inbox = bd.sub(dhl, "Inbox")
    if inbox is None:
        return out
    cutoff = datetime.now() - timedelta(days=days)

    def walk(f, depth):
        if f is None or depth > 4:
            return
        try:
            items = f.Items
            items.Sort("[ReceivedTime]", True)
        except Exception:
            items = None
        if items is not None:
            n = 0
            for it in items:
                n += 1
                if n > per_folder:
                    break
                try:
                    rt = it.ReceivedTime
                    if rt is not None and datetime(rt.year, rt.month, rt.day) < cutoff:
                        break                 # newest-first: the rest is older
                except Exception:
                    pass
                try:
                    eid = str(it.EntryID)
                    if eid in known_ids:
                        continue
                    subj = str(it.Subject or "")
                    for j in range(1, it.Attachments.Count + 1):
                        fn = str(it.Attachments.Item(j).FileName)
                        low = fn.lower()
                        if (bd.is_wanted_extract(fn, subj)
                                and any(m in low or m in subj.lower() for m in bd.BS_MARKERS)):
                            out.append((eid, fn))
                            break
                except Exception:
                    continue
        try:
            for i in range(1, f.Folders.Count + 1):
                c = f.Folders.Item(i)
                if depth == 0 and str(c.Name).strip().lower() == "adhoc":
                    continue                  # Synergy Upload has its own fast path
                walk(c, depth + 1)
        except Exception:
            pass

    walk(inbox, 0)
    return out


def main():
    # The supervisor fires this every 60s whether or not the last one finished.
    # Without these guards ticks piled up (ten at once on 02/10/2026), each one
    # starting its own build / reply check, and Outlook froze and stopped
    # syncing. One tick at a time; none while Outlook is Not Responding; and
    # the tick plus the batch build it may start counts as the ONE background
    # Outlook job (agent.py's timer jobs take turns with it through the slot).
    import outlook_gate as gate
    if not gate.single_instance("monitor_tick"):
        return
    gate.self_destruct(TICK_MAX_AGE)      # stuck on a COM call -> kill this tick and its build
    if gate.outlook_hung():
        return
    # 45s, longer than the agent's jobs queue (30s), so the live monitor gets
    # its turn between them instead of going blind behind a queue of waiters.
    if gate.background_slot(wait=45) is None:
        return
    try:
        import win32com.client
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        return
    inbox, syn, sent = _folders(ns)
    state = _load()
    seed = state is None
    if seed:
        state = {"ext_ids": [], "adhoc_ids": [], "inbox_hwm": "", "sent_hwm": ""}
    ext_ids = set(state.get("ext_ids", []))
    adhoc_ids = set(state.get("adhoc_ids", []))
    inbox_hwm = state.get("inbox_hwm", "")
    sent_hwm = state.get("sent_hwm", "")

    new_extracts, new_adhocs, new_mail = [], [], False      # new_extracts: (entry id, file)
    new_inbox_hwm, new_sent_hwm = inbox_hwm, sent_hwm
    for folder in (inbox, syn):
        for eid, subj, riso, atts in _scan(folder, 80):
            if folder is inbox:
                # the Inbox's new-mail watermark, from the same pass (this used
                # to be a second scan of the newest 40 - the same items again)
                if riso > new_inbox_hwm:
                    new_inbox_hwm = riso
                if inbox_hwm and riso > inbox_hwm:
                    new_mail = True
            for fn in atts:
                low = fn.lower()
                if bd.is_wanted_extract(fn, subj):
                    if eid not in ext_ids:
                        ext_ids.add(eid)
                        new_extracts.append((eid, fn))
                elif (low.endswith((".xlsx", ".xlsm", ".pdf"))
                      and any(h in low or h in subj.lower() for h in FORM_HINTS)
                      and eid not in adhoc_ids):
                    adhoc_ids.add(eid)
                    new_adhocs.append(fn)
    # slow full-tree sweep for BS files filed outside the watched folders
    if time.time() - state.get("last_tree", 0) > TREE_EVERY:
        try:
            for eid, fn in _tree_bs(ns, ext_ids):
                ext_ids.add(eid)
                new_extracts.append((eid, fn))
        except Exception:
            pass
        state["last_tree"] = time.time()
    # ALSO watch Sent Items: when YOU send a "booked in" message, phase2 check's
    # booked-sweep runs live and drops that order from the tracker (never chased).
    for eid, subj, riso, atts in _scan(sent, 40):
        if riso > new_sent_hwm:
            new_sent_hwm = riso
        if sent_hwm and riso > sent_hwm:
            new_mail = True

    # Save what this tick has SEEN before doing anything slow. The state used to
    # be saved only after the build / reply check below (minutes each), so any
    # tick that overlapped read the old state, saw the same "new" extract and
    # the same "new" mail, and started the same heavy job again.
    state["ext_ids"] = list(ext_ids)[-500:]
    state["adhoc_ids"] = list(adhoc_ids)[-500:]
    state["inbox_hwm"] = new_inbox_hwm
    state["sent_hwm"] = new_sent_hwm
    _save(state)

    if seed:
        return
    if new_mail:
        # New mail in or out: ask the local agent for a reply check. It used to
        # run right here under a 600s limit - but a check can take 13 minutes,
        # so it was killed before saving, and it kept the live monitor off the
        # slot for the whole time. The agent runs it under the gate with a
        # proper budget, and never sooner than 5 minutes after the last one.
        try:
            open(PHASE2_DUE, "w").close()
        except OSError:
            pass
        # A bounce is new mail too. Escalate it while the contact's silence still
        # costs something - 7115888's bounce sat unnoticed for three days.
        if os.path.exists(os.path.join(HERE, "bounce_escalate.enabled")):
            _bounces(ns)
    if new_extracts:
        _build(state, new_extracts)
    if new_adhocs:
        report("done", "New ad-hoc form arrived: " + ", ".join(new_adhocs[:3])
               + " - process it from the DTS / Ad-hoc box.")


REVIEW_STATES = ("preview_ready", "batch_ready", "sites_needed", "found")


def _review_open():
    """True if EITHER dashboard is showing something waiting on Delali (or we
    cannot tell) - a monitor notice must never wipe a review he is in."""
    import urllib.request
    for url, key in _cps():
        try:
            req = urllib.request.Request(url + "/api/status", headers={"X-Auth": key})
            st = json.loads(urllib.request.urlopen(req, timeout=8).read() or b"{}")
            if st.get("state") in REVIEW_STATES:
                return True
        except Exception:
            if key:                      # the cloud one matters; the local CP may simply be down
                return True
    return False


def _bounces(ns):
    """Escalate new bounces, then post what is waiting - one combined notice,
    and only when no review is open (notices keep in the state file till then)."""
    try:
        import bounce_escalate
        bounce_escalate.run(ns, send=True)
    except Exception as e:
        try:
            st = bounce_escalate._load() or {}
            bounce_escalate._note(st, f"Bounce check failed: {e}")
            bounce_escalate._save(st)
        except Exception:
            pass
    try:
        import bounce_escalate
        lines = bounce_escalate.take_unreported(clear=False)
        if lines and not _review_open():
            report("done", f"{len(lines)} bounce update(s) - {lines[-1][12:150]}", "\n".join(lines))
            bounce_escalate.take_unreported(clear=True)
    except Exception:
        pass


def _build(state, new_extracts):
    """Auto-build the batch for newly arrived extracts, and only ever announce
    a batch THIS build wrote. If the build fails, put the extracts back as
    unseen so the next tick tries again (up to BUILD_TRIES times) - they are
    already saved as seen, and a one-off error line is easily overwritten."""
    batch_path = os.path.join(HERE, "_pending_batch.json")
    names = ", ".join(fn for _eid, fn in new_extracts[:2])

    def mtime():
        try:
            return os.path.getmtime(batch_path)
        except OSError:
            return None

    before = mtime()
    rc, out = run(["build_drafts.py", "batch"])
    tries = state.setdefault("build_tries", {})
    if rc != 0:
        retry = []
        for eid, _fn in new_extracts:
            tries[eid] = tries.get(eid, 0) + 1
            if tries[eid] < BUILD_TRIES:
                retry.append(eid)
        if retry:
            state["ext_ids"] = [e for e in state.get("ext_ids", []) if e not in retry]
        _save(state)
        report("error", f"New extract arrived ({names}) but the automatic batch build did not "
               + ("finish - trying again in a minute." if retry
                  else f"finish after {BUILD_TRIES} tries - press Build to run it."),
               out[-400:])
        return
    for eid, _fn in new_extracts:
        tries.pop(eid, None)
    _save(state)
    batch = []
    if mtime() != before:                 # this build wrote it - not a stale one
        try:
            batch = json.load(open(batch_path, encoding="utf-8"))
        except Exception:
            batch = []
    if batch:
        loose = [e for e in batch if e.get("loose_ballast")]
        pri = ("PRIORITY - LOOSE BALLAST: "
               + "; ".join(" / ".join(e.get("orders", [])) for e in loose[:3]) + ". ") if loose else ""
        report("batch_ready", pri + f"New extract arrived ({names}) - batch built, "
               f"{len(batch)} email(s) to review, then send.", "", batch)
    else:
        report("done", f"New extract arrived ({names}) - nothing new to email.")


if __name__ == "__main__":
    main()
