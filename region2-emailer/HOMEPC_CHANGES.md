# Changes to apply on the HOME PC (agent side)

The dashboard (cloud/server.py) was updated on 2026-07-06. The agent code
(`agent.py` / `supervisor.py` and friends) lives only on the home PC — it has
never been committed to this repo — so these matching changes have to be made
there. Open a Claude Code session on the home PC in this folder and point it
at this file, or apply by hand.

## 0. First: get the home PC back online

The dashboard shows "home PC: offline" whenever the agent hasn't contacted the
cloud in the last 15 seconds. While it's offline, every dashboard command
(including "Send email") just sits in the cloud's in-memory queue — nothing
reaches Outlook, so nothing appears in Sent Items or Drafts. Check, in order:

1. Is the PC on and awake? Disable sleep/hibernate:
   `powercfg /change standby-timeout-ac 0` and
   `powercfg /change hibernate-timeout-ac 0`
2. Is `supervisor.py` actually running? (Task Manager → look for the python
   process; consider a Scheduled Task "At log on" so it survives reboots.)
3. Does `region2-emailer/cloud.json` exist, with the CURRENT Railway URL and
   the CURRENT `AGENT_KEY`? A Railway redeploy keeps env vars, but if the URL
   or keys were ever regenerated, cloud.json must be updated to match.
4. Quick test from the home PC:
   `curl https://YOUR-APP-URL/healthz` → should return `{"ok": true, ...}`.
   Then check the agent's log for auth errors (401 = wrong AGENT_KEY).

## 1. CC support on send

The dashboard now sends `email.cc` alongside `to`/`subject`/`message` in the
`order_send_edited` command. In the agent, where the Outlook item is built:

```python
cc = (email.get("cc") or "").strip()
if cc:
    mail.CC = cc          # semicolon-separate multiple addresses
```

Optionally include `"cc": ""` (or a sensible default) in the preview email
dict pushed to `/api/status` so the dashboard's Cc box pre-fills.

## 2. Fast order-number search (the "Outlook finds it in seconds" fix)

Manual Outlook search is fast because it uses the Windows Search content
index. Looping over `folder.Items` in Python and reading each item over COM
is what makes the current search slow. Use `Items.Restrict` with a DASL
`ci_phrasematch` filter — that goes through the same index:

```python
import re

def find_order_items(ns, order, folder_ids=(6, 5)):   # 6 = Inbox, 5 = Sent Items
    """Index-backed Outlook search — same engine as the Outlook search box."""
    order = re.sub(r"\D", "", str(order))              # digits only: no DASL injection
    if not order:
        return []
    hits = []
    for fid in folder_ids:
        items = ns.GetDefaultFolder(fid).Items
        try:
            # content-indexed: returns in well under a second even on huge mailboxes
            flt = ('@SQL=("urn:schemas:httpmail:subject" ci_phrasematch \'%s\' '
                   'OR "urn:schemas:httpmail:textdescription" ci_phrasematch \'%s\')'
                   % (order, order))
            found = items.Restrict(flt)
        except Exception:
            # store not indexed — LIKE scan; slower but still far faster than a Python loop
            flt = ('@SQL=("urn:schemas:httpmail:subject" LIKE \'%%%s%%\' '
                   'OR "urn:schemas:httpmail:textdescription" LIKE \'%%%s%%\')'
                   % (order, order))
            found = items.Restrict(flt)
        # sort the RESTRICTED collection (sorting `items` first is not inherited)
        found.Sort("[ReceivedTime]" if fid == 6 else "[SentOn]", True)
        for i in range(1, found.Count + 1):
            hits.append(found.Item(i))
    return hits
```

Notes:
- `ci_phrasematch` matches whole words — order numbers in subjects/bodies are
  normally standalone tokens, so this behaves like the Outlook search box. If
  an order number can be embedded inside another string (e.g. `PO6054999`),
  the LIKE fallback catches it; you can also run LIKE only when the indexed
  search returns nothing.
- Never fetch `.Body` of every item to search it — that is the slow path.
  `Restrict` filters server-side/against the index first, so you only touch
  the handful of real hits.
- To search the whole mailbox (all folders) like Outlook's "All Mailboxes",
  `Application.AdvancedSearch` with the same DASL filter works asynchronously,
  but per-folder `Restrict` on Inbox + Sent Items is usually all that's needed
  and is much simpler.
- Same trick applies to the DTS-PDF and form lookups if they loop over items.

## 2b. Group several orders into ONE email (order search)

The daily batch build already groups same-recipient orders into one email
(tracker records carry `orders` as a list), but the order-search path builds
an email for exactly the one number typed — so e.g. 7114852 and 7114854 send
separately even though they'd group in the daily build.

The dashboard's "Send order(s)" box now sends space-separated order numbers
in `cmd["order"]` (e.g. `"7114852 7114854"`). In the agent's `order_preview`
/ `order_send_edited` handler:

```python
orders = [o for o in re.split(r"[\s,;/+&]+", str(cmd.get("order", ""))) if o]
```

- Look up every order (fast search from section 2 — one Restrict per order,
  or a single combined DASL filter OR-ing the numbers).
- Build ONE email covering all of them, reusing the same grouping/formatting
  the batch build uses for multi-order records.
- If the orders resolve to DIFFERENT recipients, post an error status and
  send nothing — don't guess.
- Nice-to-have: when a single searched order belongs to a same-recipient
  group in today's extract, pull in its siblings automatically (matching
  what the batch build would have produced) and show them in the preview.

Until this is applied, a multi-order search will behave however the current
agent treats an unknown order string — most likely "not found".

## 3. Never fail silently on send

Wrap the actual send and report the result to the cloud status, so the
dashboard shows a red error instead of nothing:

```python
try:
    mail.Send()
    post_status("done", f"Sent to {mail.To}" + (f" (cc {mail.CC})" if mail.CC else ""))
except Exception as e:
    post_status("error", f"Send FAILED — nothing sent: {e}")
    raise
```

## 4. Commit the home-PC code to git (the "unpushed" work)

The engine has never been in the repo — only `cloud/` is. From the home PC:

```
git checkout main && git pull origin main
git add region2-emailer/*.py        # supervisor.py, agent.py, etc.
git status                          # confirm NO xlsx/pdf/config/tracker/cloud.json files are staged
git commit -m "Add home-PC engine (supervisor + agent)"
git push origin main
```

`.gitignore` already excludes work data and `cloud.json` (secrets) — double
check `git status` output before committing anyway.

## 5. Route map on the dashboard (Map tab) — added 2026-07-21

The dashboard now has a **Desk | Map** tab bar. The Map tab draws the latest
Order-upload batch as points and **road-following** routes (collection →
delivery) on a real street map. The agent-side pieces are already in this repo,
so on the home PC just `git pull` and restart the agent — no hand-editing.

What was wired up:

- **`synergy_map.py`** — every mapping run now also writes
  `_synergy_routes.json` (gitignored runtime data): one row per mapped order
  line with `order`, `coll_site`/`coll_pc`, `deliv_site`/`deliv_pc`, `product`,
  `deliv_date`. Written for both a normal upload and the add-sites re-process.
- **`agent.py`** — `push_map()` posts that file to the cloud's new `/api/map`
  after `order_upload` and `add_sites`, and once on startup so a reconnecting
  agent restores the last batch. Mirrors `push_tracker()`/`push_waitlist()`.
- **`cloud/server.py`** — new in-memory `_map` store with `GET`/`POST
  /api/map` (agent-key to push, dash-or-agent to read), plus the tab bar and
  the Leaflet map itself.

How the map gets coordinates (all client-side, in the work browser — nothing
extra runs on the home PC):

- **Leaflet 1.9.4** (map library) + **OpenStreetMap** tiles — the page loads
  these from `unpkg.com` / `tile.openstreetmap.org`. This is the first time the
  dashboard reaches any external host; if the work laptop's network blocks
  them the map won't render (the rest of the dashboard is unaffected).
- **postcodes.io** turns each UK postcode into lat/lon (free, no key, batched).
- **OSRM public server** returns the road route between the two points. It's a
  shared demo server — fine for this volume; for guaranteed capacity later,
  point `roadRoute()` at an OpenRouteService key or a self-hosted OSRM.

Until this reaches the home PC (or before the first upload after it does), the
Map tab simply shows "Run an Order upload… to plot its routes here."

## Phase 2 - reply side (BUILT: phase2.py)

Implemented on the home PC (`phase2.py`, wired into `agent.py`):

- **Reply detection + OOO**: scans the DHL inbox for replies to sent orders;
  a genuine reply sets `reply_at`, an auto-reply/out-of-office sets `ooo_at`
  (flagged amber "Out of office" on the dashboard) instead.
- **Send-off briefs**: on a real reply, drafts the send-off brief into
  `Region 2 > Send Out`, pre-filled from the extract (order/collection/
  delivery/collection-date/materials), with delivery date + offloading read
  from the reply's answers and the full reply quoted; anything unread is
  marked `[CHECK]`.
- **Chasers**: `chase [send]` - 2 business days (weekends + England/Wales bank
  holidays skipped), up to 3 chases, once per business day per order.
- **Agent**: auto-runs `phase2.py check` every 20 min (safe - drafts only).
  Chasers are OPT-IN: create an empty file `auto_chase.enabled` next to the
  scripts to let the agent auto-send them every 3h; otherwise use the
  dashboard's "Run chasers" button. Heartbeat thread keeps "home PC online"
  fresh even during long commands.

## Phase 3 - team features (modules SHIPPED, wiring needed)

Site matching + self-learning, user profiles / never-email-yourself, the
self-updating Outlook watcher, and holiday handover are now in this repo as
complete tested modules (`modules/`, tests in `tests/test_modules.py`).
Follow `INTEGRATE_ON_HOMEPC.md` to wire them into agent.py/supervisor.py.
