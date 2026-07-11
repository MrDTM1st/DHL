# Integration brief — wire the new modules into the home-PC agent

**Audience: the Claude Code session running on the home PC** (or a human
applying by hand). Everything below ships in `region2-emailer/modules/` as
complete, tested, pure-Python code — no Outlook imports. Your job is the
last mile: small COM adapters and hooking module calls into `agent.py` /
`supervisor.py`. Do NOT touch the already-built rail plan, supplier
exception workflow, order upload, phase2 reply-side, or waitlist logic
except where a hook is explicitly named below.

Run the module tests first — they must pass on the home PC too:

    python region2-emailer/tests/test_modules.py

## 0. One-time setup

1. `copy region2-emailer\config\team.json.example region2-emailer\config\team.json`
   and fill in the real `me` address and team members (file is gitignored).
2. Data files the modules write (all gitignored automatically):
   `_sites.json`, `_handover.json`, `_updates_seen.json`, `_settings.json`
   — all under `region2-emailer/`.

## 1. The panel — how the new features talk to the dashboard

The cloud has a new persistent channel: `POST /api/panel` (agent key).
Unlike `/api/status` it is NOT overwritten by job chatter — push it after
anything changes a decision/handover/team state. Shape:

```python
def push_panel():
    payload = {
        "decisions": site_store.pending(),         # [{raw, context, options}]
        "sites": site_store.sites(),               # full drop-down fallback
        "handover": handover.panel_state(handover.load(HANDOVER_PATH)),
        "team": [{"name": m["name"], "email": m["email"]}
                 for m in team.get("members", [])],
    }
    post_json(cloud_url + "/api/panel", payload, agent_key)   # reuse existing helper
```

Call `push_panel()` at agent startup and after every mutation below. The
dashboard shows: a "Delivery site decisions" card whenever `decisions` is
non-empty, and the holiday card state. Commands from those cards arrive via
`/api/next` with a new `data` field (dict) alongside the usual keys.

## 2. Delivery site matching + self-learning (modules/site_matching.py)

```python
from modules import site_matching
site_store = site_matching.SiteStore(os.path.join(BASE, "_sites.json"))
```

- **Seed once at startup** (idempotent): collect every Synergy site name the
  system already knows — from the delivery-site column of historical upload
  CSVs in the outbox/recent folders and/or the sites the order-upload flow
  already uses — and `site_store.add_sites(names)`.
- **Hook into the order-upload / extract flows**: wherever a raw delivery
  site from an upload row is used today, first try
  `site = site_store.request_decision(raw, context=f"order {order_no}")`.
  - If a site comes back, use it (exact/learned/fuzzy — all safe).
  - If `None`, the row is held: skip it in this build, post a status like
    `f"{n} site(s) need a decision on the dashboard"`, and `push_panel()`.
    The user picks on the dashboard, which sends the command below; then
    they simply re-run the upload — held rows now resolve automatically.
- **Handle the command** in the agent's dispatch:

```python
elif action == "site_decision":
    d = cmd.get("data") or {}
    site_store.resolve(d.get("raw", ""), d.get("site", ""))
    push_panel()
    post_status("done", f"Site saved: {d.get('raw')} -> {d.get('site')} (remembered)")
```

Note: this is SEPARATE from the existing `sites_needed`/`add_sites` flow
(which captures contact details for unknown collection sites) — leave that
flow exactly as it is.

## 3. Profiles + never-email-yourself (modules/profiles.py)

```python
from modules import profiles
team = profiles.load_team(os.path.join(BASE, "config", "team.json"))
ME = team.get("me", "")
```

In the ONE place outgoing mail gets built (the shared send helper), just
before assigning To/Cc:

```python
to, cc, removed = profiles.clean_recipients(to, cc, me=ME)
if removed:
    log(f"self-address removed from recipients: {removed}")
if not to:
    post_status("error", "No recipients left after removing your own address — nothing sent.")
    return
```

`profiles.find_member(team, ...)` resolves the handover cover (below);
`split_internal_external` is available for any internal-vs-external routing.

## 4. Self-updating from Outlook (modules/self_update.py)

In the supervisor's periodic loop (it already ticks frequently; run this
part every ~60s):

```python
from modules import self_update

def check_update_emails(ns):
    # cheap indexed pull of recent inbox items with the R2 UPDATE prefix
    items = ns.GetDefaultFolder(6).Items
    flt = "@SQL=\"urn:schemas:httpmail:subject\" ci_phrasematch 'R2 UPDATE'"
    try:
        found = items.Restrict(flt)
    except Exception:
        found = items.Restrict("[Subject] >= 'R2 UPDATE' AND [Subject] <= 'R2 UPDATEz'")
    msgs = []
    for i in range(1, min(found.Count, 25) + 1):
        it = found.Item(i)
        msgs.append({"id": it.EntryID,
                     "sender": getattr(it, "SenderEmailAddress", "") or "",
                     "subject": it.Subject or "", "body": it.Body or ""})
    applied = self_update.process_messages(
        msgs, site_store,
        team_path=os.path.join(BASE, "config", "team.json"),
        settings_path=os.path.join(BASE, "_settings.json"),
        seen_path=os.path.join(BASE, "_updates_seen.json"))
    if applied:
        push_panel()
        post_status("done", "Self-update applied: " + "; ".join(applied))
```

Exchange note: `SenderEmailAddress` for internal senders may be an
`/O=EXCHANGE...` DN rather than SMTP. If team senders aren't recognised, use
`it.Sender.GetExchangeUser().PrimarySmtpAddress` (guarded in try/except)
and fall back to `SenderEmailAddress`.

## 5. Holiday handover (modules/handover.py)

```python
from modules import handover
HANDOVER_PATH = os.path.join(BASE, "_handover.json")
```

**Commands** in the agent dispatch:

```python
elif action == "handover_start":
    d = cmd.get("data") or {}
    member = profiles.find_member(team, d.get("cover", ""))
    if not member:
        post_status("error", f"No team member matches '{d.get('cover')}' — check config/team.json")
    else:
        state = handover.start(HANDOVER_PATH, d.get("days", 5), member["name"],
                               member["email"], d.get("notes", ""), bool(d.get("forward", True)))
        spec = handover.build_handover_email(state, tracker_records(), sender_name=MY_NAME)
        send_email(spec["to"], spec["subject"], spec["message"])   # existing helper;
        # attach relevant outbox files for outstanding orders if easy to gather
        push_panel()
        post_status("done", f"Handover sent to {member['name']}; cover until {state['end']}")

elif action == "handover_stop":
    handover.end(HANDOVER_PATH)
    push_panel()
    post_status("done", "Handover ended — you're back in charge.")
```

**Supervisor tick** (same ~60s slot as self-update):

```python
result = handover.tick(HANDOVER_PATH)
if result == "ended":
    push_panel()
    post_status("done", "Handover finished — welcome back! Forwarding stopped.")
elif result == "active":
    state = handover.load(HANDOVER_PATH)
    incoming = [...]   # NEW unseen inbox messages since last tick as
                       # [{"id": EntryID, "sender": smtp}] — reuse/borrow the
                       # phase2 reply-scan so this stays one cheap pass
    for mid in handover.plan_forwards(state, incoming, me=ME):
        item = ns.GetItemFromID(mid)
        fwd = item.Forward()
        fwd.To = state["cover_email"]
        fwd.Send()
    handover.mark_forwarded(HANDOVER_PATH, [...ids actually forwarded...])
```

Keep forwarding scoped if preferred: only messages whose subject/body hits a
tracked order (phase2 already computes this) — that matches "incoming
replies" from the design notes and avoids forwarding unrelated mail.

## 6. After wiring

1. `python region2-emailer/tests/test_modules.py` — still green.
2. Restart the supervisor; dashboard header goes ONLINE.
3. End-to-end checks:
   - Upload an extract containing a misspelled delivery site → decision card
     appears → pick site → re-run → row resolves; next time no question.
   - Send any order email with your own address in Cc → it's stripped.
   - Email yourself `R2 UPDATE` / `site: TEST X => <real site>` → within a
     minute status shows "Self-update applied".
   - Start a 1-day handover to a teammate → they get the outstanding-work
     email; card shows active; "End handover now" stops it.
4. Commit and push the wiring (never commit team.json / _*.json data files).
