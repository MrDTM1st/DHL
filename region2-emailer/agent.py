"""
Home agent for the Region 2 emailer.

Runs on your always-on home PC. Polls the control plane for commands, runs the
engine locally, and posts the result back. Only ever makes OUTBOUND requests to
the control plane - nothing connects in to this PC.

    python agent.py                 # points at the local control plane
    python agent.py https://your-hosted-url   # points at the deployed one
"""
import sys, time, json, subprocess, os, threading, socket
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8787"
KEY = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("R2_AGENT_KEY", "")
# Two agents run side by side (local CP + cloud CP) on the SAME PC/Outlook.
# Timed jobs that SEND or WRITE must run on only one of them - the local one -
# or everything fires twice (Darren got the same wait-list email twice, Paul
# got every chaser twice). Command handling and data pushes stay on both.
IS_LOCAL = BASE.startswith("http://127.0.0.1")
POLL_SECONDS = 2
HEARTBEAT_SECONDS = 5

sys.path.insert(0, HERE)   # local modules importable no matter the cwd
from modules import site_matching, profiles, handover   # pure-python, no COM
CONFIG_DIR = os.path.join(HERE, "config")
HANDOVER_PATH = os.path.join(HERE, "_handover.json")


def site_store():
    """Fresh store each call so we never race the upload subprocess's writes."""
    return site_matching.SiteStore(os.path.join(HERE, "_sites.json"))


def team_config():
    try:
        return profiles.load_team(os.path.join(CONFIG_DIR, "team.json"))
    except Exception:
        return {"members": [], "me": ""}


def _req(path, data=None, timeout=15):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json", "X-Auth": KEY},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def heartbeat():
    """Keep the cloud's 'home PC online' fresh even while the main loop is
    blocked running a long command (a deep search can take minutes). Any
    agent-authenticated request refreshes the server's last-seen clock, so a
    steady background ping means the pill never flickers offline while we're
    alive - it only goes offline if this whole process actually stops."""
    tag = "cloud" if BASE.lower().startswith("https") else "local"
    hbfile = os.path.join(HERE, f"_heartbeat_{tag}.txt")
    while True:
        try:
            _req("/api/heartbeat", timeout=8)
            try:
                with open(hbfile, "w") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} ok {BASE}\n")
            except Exception:
                pass
        except Exception as e:
            try:
                with open(hbfile, "w") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} FAIL {type(e).__name__}: {e}\n")
            except Exception:
                pass
        time.sleep(HEARTBEAT_SECONDS)


def push_tracker():
    try:
        with open(os.path.join(HERE, "tracker.json"), encoding="utf-8") as f:
            _req("/api/tracker", json.load(f))
    except Exception:
        pass


def push_waitlist():
    try:
        with open(os.path.join(HERE, "waitlist.json"), encoding="utf-8") as f:
            _req("/api/waitlist", json.load(f))
    except Exception:
        pass


def outbox_dir():
    return os.path.join(os.path.expanduser("~"), "Documents", "DHL", "outbox")


def snap_outbox():
    try:
        d = outbox_dir()
        return {n: os.path.getmtime(os.path.join(d, n)) for n in os.listdir(d)}
    except Exception:
        return {}


def push_new_files(before):
    """Upload outbox files created/changed since `before` to the control
    plane, so they can be downloaded from the dashboard at work."""
    import base64
    d = outbox_dir()
    for n, m in snap_outbox().items():
        if n in before and m <= before.get(n, 0):
            continue
        p = os.path.join(d, n)
        try:
            size = os.path.getsize(p)
            if size > 8_000_000:
                continue
            with open(p, "rb") as f:
                _req("/api/files", {"name": n, "size": size,
                                    "data": base64.b64encode(f.read()).decode()})
        except Exception:
            pass


def report(state, detail, output="", email=None):
    try:
        _req("/api/status", {"state": state, "detail": detail, "output": output,
                             "email": email})
    except Exception:
        pass


def _slim_hauliers():
    """Just enough for the map's haulier layer. DO-NOT-USE hauliers are never
    published - they must not show up as an option anywhere."""
    try:
        import hauliers
        out = []
        for h in hauliers.load().get("hauliers", []):
            if h.get("do_not_use") or not h.get("postcode"):
                continue
            out.append({"name": h["name"], "loc": h.get("location", ""),
                        "pc": h.get("postcode", ""), "tier": h.get("tier", ""),
                        "phone": (h.get("phone") or "")[:40]})
        return out
    except Exception:
        return []


def push_panel():
    """Persistent dashboard panel: site decisions, known sites, handover, team,
    hauliers. Separate from /api/status so job chatter never wipes it."""
    try:
        ss = site_store()
        team = team_config()
        _req("/api/panel", {
            "decisions": ss.pending(),
            "sites": ss.sites(),
            "handover": handover.panel_state(handover.load(HANDOVER_PATH)),
            "team": [{"name": m.get("name", ""), "email": m.get("email", "")}
                     for m in team.get("members", [])],
            "hauliers": _slim_hauliers(),
        })
    except Exception:
        pass


def run(args):
    proc = subprocess.run([sys.executable] + args, cwd=HERE,
                          capture_output=True, text=True, timeout=600)
    return (proc.stdout or "") + (proc.stderr or "")


def tail(out, n=8):
    return "\n".join(out.strip().splitlines()[-n:])


def single_instance():
    """Refuse to run a second agent for the same target. If the supervisor is
    restarted while an old agent is still alive, the fresh copy would otherwise
    double-poll and double-send. Local and cloud agents use different ports so
    both legitimately run. Returns the held socket (keep the reference alive)."""
    port = 8789 if BASE.lower().startswith("https") else 8788
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        print("Another agent for this target is already running - exiting.")
        sys.exit(0)
    return s


def main():
    _lock = single_instance()   # noqa: F841 - held for process lifetime
    print(f"Agent polling {BASE} every {POLL_SECONDS}s. Ctrl+C to stop.")
    threading.Thread(target=heartbeat, daemon=True).start()
    report("idle", "Agent connected.")
    push_tracker()
    push_waitlist()
    push_panel()
    last_push = time.time()
    last_panel = time.time()
    last_index = time.time()
    last_check = 0            # reply check runs soon after start, then every 20 min
    last_chase = time.time()  # auto-chase (opt-in) only after the first interval
    last_recover = 0.0        # daily untracked-order recovery (runs on first tick)
    last_waitscan = 0         # capture far-ahead orders onto the wait list (soon, then every 12h)
    last_release = 0          # auto-send due wait-list emails (soon after start, then every 3h)
    while True:
        try:
            cmd = _req("/api/next")
        except Exception:
            time.sleep(POLL_SECONDS)
            continue
        action = cmd.get("action") if cmd else None
        order = (cmd.get("order") or "").strip() if cmd else ""
        try:
            if action in ("preview", "commit"):
                report("running", f"Running {action}…")
                out = run(["build_drafts.py", action])
                report("done", f"{action} finished.", tail(out))
            elif action == "extract_preview":
                wk = (cmd.get("week") or "").strip().lower()
                if wk in ("next", "after"):
                    label = "week after" if wk == "after" else "next week"
                    report("running", f"Building the {label} batch…")
                    out = run(["build_drafts.py", "week", wk])
                else:
                    report("running", "Building today's extract batch…")
                    out = run(["build_drafts.py", "batch"])
                batch = None
                try:
                    pend = os.path.join(HERE, "_pending_batch.json")
                    if os.path.exists(pend):
                        batch = json.load(open(pend, encoding="utf-8"))
                except Exception:
                    batch = None
                if batch:
                    report("batch_ready",
                           f"Batch ready — {len(batch)} email(s) to review, then send.",
                           tail(out, 30), email=batch)
                else:
                    report("done", "Nothing to send — no Region 2 emails in today's extract.",
                           tail(out, 30))
            elif action == "week_drafts":
                wk = (cmd.get("week") or "next").strip().lower()
                wk = wk if wk in ("next", "after") else "next"
                label = "week after" if wk == "after" else "next week"
                report("running", f"Building {label} drafts…")
                out = run(["build_drafts.py", "week", wk, "commit"])
                report("done", f"{label} drafts created in your DHL Drafts folder.", tail(out, 20))
            elif action == "extract_send":
                sel = (cmd.get("sel") or "all").strip() or "all"
                report("running", "Sending today's extract batch…")
                out = run(["send_order.py", "sendbatch", sel])
                push_tracker()
                try:
                    os.remove(os.path.join(HERE, "_pending_batch.json"))
                except Exception:
                    pass
                report("done", "Batch sent from your DHL account.", tail(out, 12))
            elif action == "learn_detail":
                # one-click confirm/correct of a parsed delivery detail - the
                # wording is remembered so it's never guessed again
                rid = str(cmd.get("id") or "")
                fld = str(cmd.get("field") or "")
                val = str(cmd.get("value") or "")
                out = run(["phase2.py", "learn", rid, fld, val])
                push_tracker()
                report("done", f"Noted — {fld} = {val}. I'll remember that wording.", tail(out, 6))
            elif action == "rail_plan":
                mode = (cmd.get("mode") or "preview").lower()
                week = (cmd.get("week") or "next").strip().lower()
                report("running", f"Rail plan — {mode}"
                       + (" (current-week update)" if week == "current" else "") + "…")
                up = None
                try:
                    up = _req("/api/pull_upload")
                except Exception:
                    up = None
                if not up or not up.get("data"):
                    report("error", "No rail-plan CSV received — pick the file and try again.")
                else:
                    import base64
                    raw = os.path.join(HERE, "_rail_raw.csv")
                    with open(raw, "wb") as f:
                        f.write(base64.b64decode(up["data"]))
                    before = snap_outbox()
                    args = (["rail_plan.py", "send", raw]
                            + (["go"] if mode == "send" else [])
                            + (["--update"] if week == "current" else []))
                    out = run(args)
                    push_new_files(before)
                    verb = "sent" if mode == "send" else "previewed (nothing sent)"
                    extra = " New manifests are highlighted green." if week == "current" else ""
                    report("done", f"Rail plan {verb} — plans are in Files below.{extra}", tail(out, 34))
            elif action == "order_upload":
                report("running", "Processing order upload…")
                up = None
                try:
                    up = _req("/api/pull_upload")
                except Exception:
                    up = None
                if not up or not up.get("data"):
                    report("error", "No file received — pick the Synergy extract and try again.")
                else:
                    import base64
                    raw = os.path.join(HERE, "_synergy_raw.xlsx")
                    with open(raw, "wb") as f:
                        f.write(base64.b64decode(up["data"]))
                    before = snap_outbox()
                    out = run(["synergy_map.py", raw])
                    push_new_files(before)
                    try:
                        unmatched = json.load(open(os.path.join(HERE, "_synergy_unmatched.json"), encoding="utf-8"))
                    except Exception:
                        unmatched = []
                    if unmatched:
                        report("sites_needed", f"{len(unmatched)} unknown collection site(s) — add their details to finish.",
                               tail(out, 20), email=unmatched)
                    else:
                        report("done", "Order upload processed — NR upload CSV is in Files.", tail(out, 20))
                    push_panel()   # surface any delivery-site decisions the mapping raised
            elif action == "add_sites":
                report("running", "Learning new sites & re-processing…")
                sites = cmd.get("sites") or {}
                try:
                    json.dump(sites, open(os.path.join(HERE, "_synergy_newsites.json"), "w", encoding="utf-8"))
                except Exception:
                    pass
                run(["synergy_map.py", "addsites"])
                raw = os.path.join(HERE, "_synergy_raw.xlsx")
                before = snap_outbox()
                out = run(["synergy_map.py", raw]) if os.path.exists(raw) else ""
                push_new_files(before)
                try:
                    unmatched = json.load(open(os.path.join(HERE, "_synergy_unmatched.json"), encoding="utf-8"))
                except Exception:
                    unmatched = []
                if unmatched:
                    report("sites_needed", f"Still {len(unmatched)} unknown site(s) — add the rest.",
                           tail(out, 20), email=unmatched)
                else:
                    report("done", f"Learned {len(sites)} site(s) — order upload re-processed, CSV in Files.", tail(out, 20))
            elif action == "order_preview" and order:
                report("running", f"Finding order {order}…")
                out = run(["send_order.py", order])
                email = None
                try:
                    pend = os.path.join(HERE, "_pending_email.json")
                    if "preview only" in out and os.path.exists(pend):
                        email = json.load(open(pend, encoding="utf-8"))
                except Exception:
                    email = None
                if email:
                    report("preview_ready",
                           f"Preview ready for {order} — edit below if needed, then Send.",
                           out[:4000], email=email)
                else:
                    report("done", f"No email built for {order}.", tail(out, 10))
            elif action == "order_send" and order:
                report("running", f"Sending order {order}…")
                out = run(["send_order.py", order, "send"])
                report("done", f"Order {order} sent.", tail(out))
            elif action == "order_send_edited":
                report("running", "Sending (with your edits)…")
                try:
                    pend = os.path.join(HERE, "_pending_email.json")
                    emails = json.load(open(pend, encoding="utf-8"))
                    edits = cmd.get("email") or {}
                    if emails and edits:
                        emails[0]["to"] = edits.get("to", emails[0]["to"])
                        emails[0]["cc"] = edits.get("cc", emails[0].get("cc", ""))
                        emails[0]["subject"] = edits.get("subject", emails[0]["subject"])
                        emails[0]["message"] = edits.get("message", emails[0]["message"])
                        json.dump(emails, open(pend, "w", encoding="utf-8"), indent=1)
                    out = run(["send_order.py", "sendjson"])
                    report("done", "Email sent (with your edits).", tail(out))
                except Exception as e:
                    report("error", f"Edited send failed: {e}")
            elif action == "dts" and order:
                report("running", f"Processing DTS {order}…")
                before = snap_outbox()
                out = run(["process_dts.py", order])
                push_new_files(before)
                report("done", f"DTS {order} processed - files below and in the outbox.", tail(out, 10))
            elif action == "form" and order:
                report("running", f"Processing filled form ({order})…")
                before = snap_outbox()
                out = run(["process_form.py", order])
                push_new_files(before)
                if "Nothing written" in out or "INCOMPLETE ORDER" in out or "NOT FOUND" in out:
                    report("error", "Form NOT processed - see below (likely a missing order number).", tail(out, 10))
                else:
                    report("done", "Form processed - upload CSV below and in the outbox.", tail(out, 10))
            elif action == "tracker_refresh":
                report("running", "Checking replies & building send-off drafts…")
                out = run(["phase2.py", "check"])
                report("done", "Replies checked - tracker updated, briefs drafted.", tail(out, 6))
            elif action == "booked_call" and order:
                report("running", "Marking booked via call…")
                out = run(["tracker.py", "book", order])
                push_tracker()
                report("done", "Booked via call - removed from the tracker.", tail(out, 4))
            elif action == "run_chasers":
                report("running", "Running chasers (2-business-day follow-ups)…")
                out = run(["phase2.py", "chase", "send"])
                report("done", "Chasers run.", tail(out, 10))
            elif action == "waitlist_release":
                report("running", "Releasing any due wait-list emails…")
                out = run(["waitlist_release.py", "send"])
                push_waitlist()
                low = out.lower()
                state = "error" if ("missed" in low or "failed" in low) else "done"
                report(state, "Wait-list release run.", tail(out, 14))
            elif action == "waitlist_scan":
                report("running", "Scanning for far-ahead orders to hold…")
                out = run(["build_drafts.py", "waitscan"])
                push_waitlist()
                report("done", "Wait-list scan done.", tail(out, 10))
            elif action == "site_decision":
                d = cmd.get("data") or {}
                site_store().resolve(d.get("raw", ""), d.get("site", ""))
                push_panel()
                report("done", f"Site saved: {d.get('raw')} -> {d.get('site')} (remembered).")
            elif action == "handover_start":
                d = cmd.get("data") or {}
                report("running", "Setting up handover…")
                out = run(["handover_cli.py", "start", str(d.get("days", 5)),
                           str(d.get("cover", "")), "1" if d.get("forward", True) else "0",
                           str(d.get("notes", ""))])
                push_panel()
                report("done" if "SENT handover" in out else "error", tail(out, 5))
            elif action == "handover_stop":
                handover.end(HANDOVER_PATH)
                push_panel()
                report("done", "Handover ended — you're back in charge.")
        except Exception as e:
            report("error", str(e))
        if action or time.time() - last_push > 60:
            push_tracker()
            push_waitlist()
            last_push = time.time()
        if action or time.time() - last_panel > 30:
            push_panel()   # keep decisions / handover / team fresh on the dashboard
            last_panel = time.time()
        if IS_LOCAL and time.time() - last_waitscan > 43200:   # every 12h: capture far-ahead orders onto the wait list (no drafts, no sends)
            try:
                subprocess.Popen([sys.executable, "build_drafts.py", "waitscan"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_waitscan = time.time()
        if IS_LOCAL and time.time() - last_release > 10800:   # every 3h: auto-SEND any wait-list order now within its window
            out = run(["waitlist_release.py", "send"])
            push_waitlist()
            low = out.lower()
            if any(k in low for k in ("sent:", "missed", "failed")):
                report("error" if ("missed" in low or "failed" in low) else "done",
                       "Wait-list auto-send ran.", tail(out, 14))
            last_release = time.time()
        if IS_LOCAL and time.time() - last_index > 900:      # keep the order index fresh
            try:
                subprocess.Popen([sys.executable, os.path.join(HERE, "order_index.py")],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_index = time.time()
        if IS_LOCAL and time.time() - last_check > 1200:     # Phase 2: replies + OOO + send-off drafts, every 20 min
            try:                                 # background so it never blocks command handling
                subprocess.Popen([sys.executable, "phase2.py", "check"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_check = time.time()
        # Auto-chasers are OPT-IN: only run when auto_chase.enabled exists.
        # ONLY the local agent chases (phase2 also holds a lock, but don't even
        # start the second one).
        if (IS_LOCAL
                and os.path.exists(os.path.join(HERE, "auto_chase.enabled"))
                and time.time() - last_chase > 10800):     # every 3h
            try:
                subprocess.Popen([sys.executable, "phase2.py", "chase", "send"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_chase = time.time()
        # Daily safety net: re-enrol anything emailed but missing from the
        # tracker (wait-list sends, orders emailed by hand). Slow, so it runs
        # detached on the local agent only and never blocks a check.
        # OPT-IN via auto_recover.enabled until it's proven on real data - it
        # writes to the tracker, and a bad enrolment means chasing the wrong
        # person. Run `phase2.py recover` by hand to try it first.
        if (IS_LOCAL
                and os.path.exists(os.path.join(HERE, "auto_recover.enabled"))
                and time.time() - last_recover > 86400):
            try:
                subprocess.Popen([sys.executable, "phase2.py", "recover"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_recover = time.time()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
