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
POLL_SECONDS = 2
HEARTBEAT_SECONDS = 5


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
    while True:
        try:
            _req("/api/heartbeat", timeout=8)
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
    last_push = time.time()
    last_index = time.time()
    last_check = 0            # reply check runs soon after start, then every 20 min
    last_chase = time.time()  # auto-chase (opt-in) only after the first interval
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
        except Exception as e:
            report("error", str(e))
        if action or time.time() - last_push > 60:
            push_tracker()
            push_waitlist()
            last_push = time.time()
        if time.time() - last_waitscan > 43200:   # every 12h: capture far-ahead orders onto the wait list (no drafts, no sends)
            try:
                subprocess.Popen([sys.executable, "build_drafts.py", "waitscan"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_waitscan = time.time()
        if time.time() - last_release > 10800:    # every 3h: auto-SEND any wait-list order now within its window
            out = run(["waitlist_release.py", "send"])
            push_waitlist()
            low = out.lower()
            if any(k in low for k in ("sent:", "missed", "failed")):
                report("error" if ("missed" in low or "failed" in low) else "done",
                       "Wait-list auto-send ran.", tail(out, 14))
            last_release = time.time()
        if time.time() - last_index > 900:      # keep the order index fresh
            try:
                subprocess.Popen([sys.executable, os.path.join(HERE, "order_index.py")],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_index = time.time()
        if time.time() - last_check > 1200:     # Phase 2: replies + OOO + send-off drafts, every 20 min
            try:                                 # background so it never blocks command handling
                subprocess.Popen([sys.executable, "phase2.py", "check"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_check = time.time()
        # Auto-chasers are OPT-IN: only run when auto_chase.enabled exists.
        if (os.path.exists(os.path.join(HERE, "auto_chase.enabled"))
                and time.time() - last_chase > 10800):     # every 3h
            try:
                subprocess.Popen([sys.executable, "phase2.py", "chase", "send"],
                                 cwd=HERE, creationflags=0x08000000)
            except Exception:
                pass
            last_chase = time.time()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
