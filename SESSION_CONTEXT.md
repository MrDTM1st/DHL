# SESSION_CONTEXT — everything a fresh session needs

> **Purpose.** This file exists so a brand-new session (local or cloud) can pick
> up this project cold and keep working without re-deriving the architecture.
> It documents what the system is, how it fits together, what has been built,
> why the key decisions were made, what recently changed, and what is known to
> be broken or unfinished.
>
> **Written:** 2026-08-03, from `main` @ `8cb2035`.
> **Companion docs:** [`README.md`](README.md) (deploy),
> [`region2-emailer/LOCAL_STATE.md`](region2-emailer/LOCAL_STATE.md) (the data
> that never reaches this repo — read it too),
> [`region2-emailer/cloud/README.md`](region2-emailer/cloud/README.md) (control
> plane), [`region2-emailer/cloud/web/README.md`](region2-emailer/cloud/web/README.md) (UI).

---

## 1. What this is

A personal automation toolkit for a **DHL transport planner** who runs
**Region 2** rail-materials haulage for Network Rail. It takes the daily
"Synergy Haulier Extract", works out which orders are his, emails the right
site contact for each, tracks the replies, parses the answers into the fields
CTMS needs, drafts the haulier brief, and shows the whole operation on a live
map with recommendations for who to ring.

Everything is driven from a **dashboard** ("Haulage Desk") that is reachable
from the work laptop and from a phone (installable PWA), while the actual
Outlook work happens on an always-on **home PC**.

Business context lives in memory notes, not here, but the short version:
prove the toolkit on Region 2 → renegotiate the role → then roll the tool out
to the rest of the team. The `_metrics.jsonl` evidence log exists specifically
to support that case.

**Author / operator:** Delali Opoku (`delali.opoku@dhl.com` for work mail,
`delali.opoku@sullinars.com` for this account). Repo:
`https://github.com/MrDTM1st/DHL`, branch `main`.

---

## 2. Repository layout

```
DHL/
├── Dockerfile                  multi-stage: Node builds the React UI → Python serves it
├── .dockerignore  .gitignore
├── README.md                   Railway deploy + pointer to LOCAL_STATE.md
├── SESSION_CONTEXT.md          ← this file
├── haulier-emailer/            LEGACY stub (README + regions.json). Superseded by
│                               region2-emailer. Kept for the region definition history.
├── outbox/                     generated files (gitignored, local only)
└── region2-emailer/            the whole system
    ├── *.py                    the home-PC engine (Outlook/COM + domain logic)
    ├── modules/                pure-Python, COM-free, unit-tested logic
    ├── tests/test_modules.py   tests for modules/
    ├── work_pc/                the second machine: CTMS automation probes
    ├── config/team.json.example
    ├── cloud.json.example
    ├── postcode_regions.json   11k-line postcode-district → NR region lookup
    ├── *.md                    LOCAL_STATE, CTMS_BOOKING_SPEC, LICENCE_SWITCH_DESIGN,
    │                           HOMEPC_CHANGES, INTEGRATE_ON_HOMEPC
    └── cloud/
        ├── server.py           the hosted control plane (stdlib only, ~1.3k lines)
        ├── Dockerfile  README.md
        └── web/                the React dashboard (Vite → one index.html)
            ├── src/
            └── public/         PWA manifest, service worker, icons
```

### What is deliberately NOT in the repo

The **code is here; the data is not.** Contacts, keys, live order state and
everything the tool has learned are gitignored and live only on the home PC.
`region2-emailer/LOCAL_STATE.md` is the authoritative map of that — read it
before assuming a file exists. Highlights:

| Local-only file | Holds |
|---|---|
| `config.json` | active region, its postcode areas, extract filename rules |
| `config/team.json` | team roster + "me" (never-email-yourself, handover) |
| `cloud.json` | Railway URL + agent key |
| `_hauliers.json` | 55 hauliers + 5 couriers, capabilities, tiers, no-go areas |
| `_synergy_sites.json` | ~121 collection sites + learned additions |
| `_sites.json` | delivery-site name → canonical Synergy site (self-learning) |
| `_details_learned.json` | wording → value corrections confirmed on the dashboard |
| `_quotes.json` | haulier quotes per lane |
| `_metrics.jsonl` | every send/catch/skip since 2026-07-19 — the evidence log |
| `tracker.json`, `waitlist.json`, `order_index.json`, `_adhocs.json`, `_booked_drops.json` | live operational state |
| `auto_chase.enabled`, `auto_recover.enabled` | feature switches (presence = ON) |

---

## 3. Runtime topology

```
work laptop / phone (browser only)      cloud (Railway)                home PC (always on)
┌──────────────────────────┐   HTTPS   ┌──────────────┐   OUTBOUND   ┌────────────────────┐
│ Haulage Desk (React PWA) ├──────────►│  server.py   │◄─────────────┤ agent.py (polls)   │
│ DASH_KEY typed once      │           │ in-memory    │  AGENT_KEY   │ runs the engine    │
└──────────────────────────┘           │ state only   │              │ via Outlook COM    │
                                       └──────────────┘              └────────────────────┘
                                                                     supervisor.py keeps it
                                                                     alive; watchdog keeps
                                                                     the supervisor alive
```

Three hard rules that shape everything:

1. **The home PC only ever connects OUT.** Nothing connects in to it. That is
   why the cloud is a command *queue* the agent polls, not an RPC endpoint.
2. **Outlook is driven through COM**, so this cannot run headless — it needs a
   logged-in Windows session with Classic Outlook open.
3. **The cloud stores nothing on disk.** Commands, status, tracker snapshot,
   panel state and generated files all live in memory. A redeploy wipes them
   (the agent re-pushes within ~60s; files are re-pushed every 30 min).

### Processes on the home PC

| Piece | What it does |
|---|---|
| `desk_watchdog.pyw` | every ~90s, restarts the supervisor if it died. In Startup folder. Holds port 8785. |
| `supervisor.py` | starts/restarts the control plane + both agents; fires `home_tick.py` and `monitor_tick.py` every 60s. Holds 8786. |
| `control_plane.py` | the **local** dashboard on `127.0.0.1:8787`, no auth (localhost only). The older inline-HTML UI. |
| `agent.py` ×2 | one polls the local control plane (8788), one polls the cloud (8789). Same PC, same Outlook. |
| `desk.pyw` | one-click launcher; `pythonw desk.pyw open` also opens the dashboard. |

**Single-instance ports:** watchdog 8785, supervisor 8786, control plane 8787,
local agent 8788, cloud agent 8789, chase run 8790, wait-list release 8791.

### The `IS_LOCAL` rule (important — it caused real double-sends)

Both agents run on the same PC against the same mailbox. **Any timed job that
SENDS or WRITES must run on exactly one of them** — the local one — or it fires
twice. This already caused a colleague to receive every chaser twice and a
wait-list email twice. In `agent.py`, `IS_LOCAL = BASE.startswith("http://127.0.0.1")`
gates all timed jobs. Data *pushes* (tracker/waitlist/panel/files) run on both,
so both control planes stay fresh.

### Timed jobs (all gated to the local agent)

| Job | Cadence |
|---|---|
| `monitor_tick.py` — live Outlook watch | ~60s, via supervisor |
| `phase2.py check` — replies, briefs, booked sweep | 20 min |
| wait-list release (auto-send at ~14 days) | 3h |
| wait-list scan (capture far-ahead orders) | 12h |
| order index refresh | 15 min |
| auto-chasers | 3h — **opt-in** (`auto_chase.enabled`) |
| untracked-order recovery | daily — **opt-in** (`auto_recover.enabled`) |

Both auto jobs are opt-in on purpose: they act without asking. `auto_chase` is
currently **OFF** (there's an `auto_chase.disabled.bak` sitting untracked in the
working tree); `auto_recover.enabled` is **ON**.

---

## 4. Backend — the cloud control plane (`region2-emailer/cloud/server.py`)

Python **stdlib only** (`http.server` + `ThreadingHTTPServer`). ~1.3k lines,
about 1000 of which are the *legacy inline HTML page* kept as a fallback UI.

### Auth

- `DASH_KEY` — typed by the human in the browser, sent as the `X-Auth` header,
  stored in `localStorage` only.
- `AGENT_KEY` — used by the home PC agent.
- Both are **required env vars**; the server refuses to start without them.
- `_is_agent()` refreshes `_agent_seen` as a side effect — that's how "home PC
  online" works (any agent-authenticated request counts; the agent also pings
  `/api/heartbeat` every 5s). Online = seen within 30s.

### In-memory state

`_queue` (commands), `_status` (state machine), `_tracker`, `_waitlist`,
`_panel`, `_upload` (one pending browser→agent file), `_files` (max 12
agent-produced files), `_dropped` (expired commands, max 8).

### REST API

| Method + path | Auth | Purpose |
|---|---|---|
| `GET /` | none | serves the built React `index.html`; falls back to the inline `PAGE` |
| `GET /manifest.webmanifest`, `/sw.js`, `/icon-*.png`, `/apple-touch-icon.png` | none | PWA assets, `Cache-Control: no-cache` |
| `GET /healthz` | none | host health check |
| `GET /api/status` | dash or agent | state machine + `agent_online`, `queued`, `queue_ttl`, `dropped`, **`panel`** |
| `GET /api/next` | agent | pops the next queued command |
| `GET /api/tracker` | dash or agent | last tracker snapshot the agent pushed |
| `GET /api/waitlist` | dash or agent | wait-list snapshot |
| `GET /api/files` | dash or agent | list of generated files (name/size/at) |
| `GET /api/file?name=` | dash | base64 body of one file |
| `GET /api/pull_upload` | agent | collects the file the browser uploaded |
| `GET /api/heartbeat` | agent | liveness ping |
| `POST /api/command` | dash | enqueue `{action, order, email, sel, mode, week, sites, data}` |
| `POST /api/status` | agent | agent reports state/detail/output/email |
| `POST /api/dropped_clear` | dash | dismiss the expired-command notice |
| `POST /api/tracker`, `/api/waitlist`, `/api/panel` | agent | data pushes |
| `POST /api/upload` | dash | browser→agent file handoff |
| `POST /api/files` | agent | agent uploads an outbox file |

### The command TTL / "NOT sent" guarantee

A queued command expires only when **both** it is older than `QUEUE_TTL`
(default 600s) **and** the agent has been away at least that long. This is
deliberate:

- an online-but-busy home PC keeps its whole backlog — nothing is dropped
  while the agent is checking in;
- `/api/next` passes the **pre-request** `agent_seen`, because merely
  authenticating that request already refreshed the clock and would otherwise
  let a reconnecting agent revive arbitrarily stale commands (imagine a "send
  the batch" from three hours ago firing on reconnect);
- expired commands land in `_dropped` and the dashboard shows a red
  "⚠ NOT sent/run" notice that stays until dismissed.

### The `panel` channel

`POST /api/panel` (agent key) holds *persistent* dashboard state, separate from
`/api/status` so job chatter can never wipe it. It is returned inside
`GET /api/status` as `panel` and carries:

```
decisions[]   delivery-site decisions awaiting a human pick
sites[]       all known Synergy site names (drop-down fallback)
handover{}    holiday-cover state
team[]        {name, email}
hauliers[]    the slimmed haulier directory (see §7)
auto_chase    bool — the dashboard switch
adhocs[]      recently processed ad hoc jobs (map records)
mat_teams{}   materials-team escalation contacts
```

---

## 5. Backend — the home-PC engine

Every file below lives in `region2-emailer/`. Anything importing
`win32com.client` needs Outlook; anything in `modules/` deliberately does not.

### Phase 1 — build and send the outreach

| File | What it does |
|---|---|
| `build_drafts.py` (1.3k lines) | **The core.** Finds the Synergy Haulier Extract in Outlook (or a path), applies every domain rule, groups into one email per contact+site+date, previews or writes Drafts. Never sends. Also `week next\|after` and `waitscan`. |
| `send_order.py` | Manual order send: search Outlook for the extract containing an order, build + preview the email, `send`/`sendbatch`/`sendjson`/`sendhaulier`. A pasted order is a deliberate pick, so region/supplier-rails filters are **not** applied. |
| `order_index.py` | order number → which attachment contains it. Incremental (only reads mail newer than the last scan) so "send one order" is instant. |
| `waitlist.py` / `waitlist_release.py` | Far-ahead orders are held, then auto-sent ~14 days before delivery. `release` re-checks at send time that it wasn't already handled; anything whose date passed while waiting is marked **MISSED** and shouted about. |
| `tracker.py` | The live order store. `log()`, `book()`, `drop_completed()`, plus `_booked_drops.json` memory so enrol sweeps can never resurrect an order you booked. |

### Phase 2 — the reply side

| File | What it does |
|---|---|
| `phase2.py` (887 lines) | For every emailed order: find the reply, distinguish out-of-office from a genuine reply, parse the details, draft the send-off brief into `Region 2 > Send Out`, run the booked sweep, and (opt-in) send 2-business-day chasers. `check` / `chase [send]` / `learn` / `recover`. |
| `delivery_details.py` | Turns free text into the structured fields CTMS needs. Evidence-driven (mined from ~1,470 real replies). Confident values fill silently; ambiguous ones go **amber** for a one-click confirm, and every confirmation is remembered in `_details_learned.json`. |
| `monitor_tick.py` | Live Outlook watch, ~60s. New extract → auto-build today's batch (never sends) and flag it; new inbox mail → run the reply check so bookings show within a minute; new ad hoc/DTS form → flag it. Seeds silently on first run. |

### Ad hoc / DTS / uploads

| File | What it does |
|---|---|
| `process_form.py` | A filled Haulage Request Form → NR upload CSV. Reads the form's "RHPC Admin – DHL USE ONLY" row **via Excel itself** so the form's own formulas produce the real values. Also writes the map record into `_adhocs.json` and keeps a copy of the form for forwarding. |
| `process_dts.py`, `dts_convert.py`, `dts_fill_form.py` | DTS PDF → filled Haulage Request Form **and** the NR upload CSV. |
| `nr_csv.py` | Faithful Python replica of the Network_Rail_Order_Database Access transform — ORDER / TASKS / ORD_SUB_REFS / ORD_LINES / ITEMS records, positional reordering and sort, byte-compatible output. |
| `synergy_map.py` | Raw Synergy extract → enriched rows → NR upload CSV, replicating the Synergy Template File (Supplier Details lookups by collection site name). Unknown sites are reported as UNMATCHED and the dashboard pops up to learn them. |
| `rail_plan.py` | CTMS "Short Rail Report" CSV → the weekly rail plan per the SOP: Leg column, dropped columns, grouped by delivery day, a master plan plus one per supplier depot (Scunthorpe → British Steel, Askern → Inframat/VAS, Marchwood → ArcelorMittal). Current-week mode greens the new manifests. |
| `outbox.py` | Everything generated lands in `~/Documents/DHL/outbox` and self-purges at 48h. |

### Support

| File | What it does |
|---|---|
| `hauliers.py` | The haulier directory. Imports the "Haulier Contact List – Planner Version" workbook into `_hauliers.json`, answers "who should I ring for this job", and holds `MATERIALS_TEAMS`. |
| `postcodes.py` | **The one correct UK postcode implementation.** See §6 — this fixed pins that were up to 41 miles out. |
| `quotes.py` | Haulier quote memory per lane, with district→district / area→area / reverse-lane / same-delivery-area matching, most specific first. Every estimate names the quotes it came from. |
| `metrics.py` | The evidence log (`_metrics.jsonl`). Design rule: **metrics must never break the tool** — `log()` swallows every error. |
| `home_tick.py` | The COM adapter for self-update ("R2 UPDATE" emails) + holiday-handover forwarding. |
| `handover_cli.py` | The COM side of `handover_start`. |
| `modules/` | Pure-Python, COM-free, tested: `site_matching` (self-learning fuzzy site store, 0.92 auto-accept), `profiles` (team + never-email-yourself), `handover`, `self_update`. |
| `work_pc/` | `ctms_probe.py` (stdlib-only capability report), `ctms_attach_test.py` (proves attaching to a browser *he* logged into), `ctms_capture.py` (hand-rolled CDP client that snapshots CTMS screens, fields, and dropdown options). All read-only. |

### Agent command vocabulary

These are the `action` values `POST /api/command` accepts and `agent.py`
handles. **When adding a UI button, this is the contract to extend:**

```
preview  commit  extract_preview{week}  extract_send{sel}  week_drafts{week}
order_preview{order}  order_send{order}  order_send_edited{order,email}
dts{order}  form{order}  form_upload  order_upload  add_sites{sites}
rail_plan{mode,week}  tracker_refresh  learn_detail{id,field,value}
run_chasers  set_auto_chase{on}  booked_call{order}  adhoc_booked{order}
haulier_email{email}  waitlist_release  waitlist_scan
site_decision{data}  handover_start{data}  handover_stop
```

---

## 6. The domain rules the code encodes

These are decisions that are **not** obvious from reading the code, and getting
one wrong sends a real email to a real customer. Treat them as invariants.

**Region & scope**
- Region 2 = a fixed set of English postcode areas, matched on the **delivery**
  postcode (`B, CB, CO, CV, DE, DN, DY, HR, IP, LE, LL, LN, NG, NN, NR, PE, S,
  ST, SY, TF, WR, WS, WV` per the legacy `haulier-emailer/regions.json`; the
  live list is in the gitignored `config.json`).
- **Off-limits, never emailed:** supplier rails (order number starts with a
  letter) and stoneblowers (STONEBLOWER in the product code). They are booked
  separately.
- **BS / British Steel batch files ARE real Region 2 work** and must be
  processed like the normal extract. Their product columns are **swapped**
  versus the Synergy extract, so the readable wording is chosen by *content*,
  not column position.

**Emails**
- One email per contact + site + delivery date. Subject carries the orders, the
  worksite and the postcode.
- Far-ahead orders wait and auto-send ~14 days before delivery. Nothing is
  forgotten, nothing is emailed twice.
- Chasers: 2 business days (weekends + England/Wales bank holidays skipped),
  max 3, never twice in a day, and **never** for an order already booked.

**Bookings**
- A booking is *your own sent email* containing "this order has been arranged
  with …" or a **MAN reference**. It counts whether sent fresh or as a reply.
- A booking covers the **whole vehicle**: it clears every tracked order sharing
  that contact + postcode + date, not just the order it names.
- Booked drops are **remembered** (`_booked_drops.json`) so the enrol sweeps
  can't resurrect them next tick.

**Delivery details (parsed from replies)**
- CTMS needs **two** times; a single time is expanded by **+2 hours** (73% of
  real replies give one time).
- **"Yes" to offloading means HIAB** — policy, not a guess.
- A date range means: consolidate if possible, otherwise take the **latest**
  date ("the further away the safer it is").
- **PTS is never assumed** — it's a safety certification, so unstated means
  unknown, and it's only chased on rail orders.
- Ad hoc forms with no time window get **09:00–17:00** in the CSV (anchored on
  that leg's own date) — but the brief shows the window **blank** rather than
  claiming a time the requester never gave. A form with no date stays blank; a
  date is never invented.

**Hauliers**
- Order of approach: **DHL NOC (our own fleet) → Tier 1 → Tier 2.** Distance
  only breaks ties *within* a band.
- Tier is encoded as the **cell colour** in the contact list, not text. Two
  hauliers are marked **Do Not Use** and are filtered out everywhere — they are
  never even published to the dashboard.
- **Coverage is a hard filter, like capability.** `no_go_scope` says which end
  it applies to: HHL happily *collects* from the north but won't *deliver*
  there, so their scope is `delivery`. A multi-collection job needs the haulier
  at every pick-up, so one no-go collection rules them out.
- **DHL NOC avoids night and weekend work.** A night (window starting
  20:00–05:59) or weekend job tags them and drops them below the externals.
- Distances are **straight-line from postcode centroids** — good for "who's
  nearest", not drive time. Drive time comes from OSRM (§8).

**The postcode bug that must never come back**
There were four copies of "get the outward code" and three were wrong the same
way: they stripped the space, then a greedy pattern swallowed the first
character of the *inward* code.

```
"DN3 1ED" → DN31 (Grimsby)     instead of DN3 (Doncaster)    ~40 mi out
"PE3 6DW" → PE36 (Hunstanton)  instead of PE3 (Peterborough)  ~50 mi out
"CV3 6PH" → CV36 (Shipston)    instead of CV3 (Coventry)      ~30 mi out
```

The rule that actually holds: **a UK inward code is always exactly three
characters**, so the outward code is everything except the last three. No
pattern matching. `postcodes.py` (Python) and `pcNorm`/`outcodeOf` in
`src/lib/geo.js` (browser) are the two implementations — keep them mirrored,
and don't add a third.

---

## 7. Data shapes

### Tracker record (`tracker.json` → `GET /api/tracker`)

```js
{
  id: "6055263-6055264|12/08/2026",   // orders joined + delivery date
  orders: ["6055263"], to, name, product_codes: [], materials,
  site, worksite, postcode,
  collection_site, collection_pc,
  collections: [{site, pc}],          // a job can load at SEVERAL sites
  delivery_date: "12/08/2026",        // dd/mm/yyyy everywhere
  source, kind: "delivery"|"collection", orig_entryid,
  emailed_at, last_emailed_at, status, chases,
  reply_at, ooo_at, sendoff_ready,
  details: { date, time{earliest,latest}, offloading{value,confidence},
             artic_access, rear_steer, vehicle, pts, what3words,
             contact{name,phone}, collection_time },
  missing: [], loose_ballast
}
```

Every `details` field carries `confidence: "high" | "amber"`. Amber renders a
✓/✎ pair in the tracker that fires `learn_detail`.

### Ad hoc record (`_adhocs.json` → `panel.adhocs`)

Same shape plus `kind: "adhoc"`, `qty`, `product`, `weight`, `collection_date`,
`csv` (the generated filename), `form_file` (the kept form, forwarded on cover
requests), `processed_at`, and optionally `return_leg{order, collection_date,
collection_time, delivery_date, time, to_site, to_pc}`. Capped at the newest 8.

**Ad hocs are never in the tracker** — they aren't emailed orders. They appear
on the map only, via `panel.adhocs`, and `App.jsx` merges them:
`mapRecords = records.concat(adhocs)`.

### Slim haulier (`panel.hauliers`)

```js
{ name, loc, pc, tier, phone, email,
  fleet,            // DHL NOC — approached first
  no_go: [],        // postcode areas they don't cover
  no_go_scope,      // 'both' | 'collection' | 'delivery'
  avoid_nw,         // avoids night/weekend work
  caps: [],         // capability strings; the match happens in the browser
  parcel }          // booking services (Parcel Pass): contact only, never ranked
```

---

## 8. Frontend — the React dashboard

`region2-emailer/cloud/web/`. React 18 + Vite + `vite-plugin-singlefile` +
Leaflet/react-leaflet. **No backend endpoints were added for the UI** — it
talks to the exact same REST API the old inline page used, so the agent and the
deployment model are unchanged.

```
src/
  main.jsx              entry
  App.jsx               auth gate, polling, nav, notifications, toasts, all wiring
  api.js                X-Auth fetch client; AuthError → login screen
  hooks.js              usePoll → useStatus (1.5s) / useTracker (6s) / useClock
  theme.css             the DHL design system (~500 lines)
  icons.jsx             inline SVG icon set
  lib/orders.js         ALL domain logic in the browser (urgency, pipeline, needs,
                        vehicle codes, Parcel Pass, haulier ranking, ETA maths)
  lib/geo.js            postcodes.io geocoding + OSRM routing, both localStorage-cached
  components/           TopNav, Toasts, Drawer, NotifPop, OrdersPanel, FlowPanels, Login
  pages/                Dashboard, MapPage, TrackerPage, Notifications
```

### Pages

- **Dashboard** — metric tiles (tracked / urgent / awaiting / ready), the
  transient `FlowPanels` review steps, a grid of command cards (today's extract,
  upcoming weeks, send order(s), process DTS, **ad hoc form drop zone**, rail
  plan, **order upload drop zone**), and a right rail: status card (with the
  dropped-command warning), "Next out the door", **Files card**, Holiday cover.
- **Map** — the operational picture. See §9.
- **Tracker** — the pipeline (Drafted → Emailed → Reply → Sent off) as coloured
  segments, filter chips, search, the parsed-detail chips with the amber
  confirm/fix, "View brief", "Booked via call", and the **Auto follow-ups
  switch** (currently OFF).
- **Notifications** — derived client-side from orders inside the ≤3-day window.

### FlowPanels — the agent-driven review steps

Driven by `status.state`, so the UI mirrors the agent's state machine exactly:

| state | panel |
|---|---|
| `preview_ready` | single-order **Review & send** editor (To/Cc/Subject/Message) |
| `batch_ready` | today's batch — tick which to send |
| `sites_needed` | unknown collection sites — fill in details, re-process |
| `panel.decisions` non-empty | delivery-site decisions (persistent, not a state) |

Every send confirms first, and when the home PC is offline the confirm text
changes to explain that the command will be discarded after the TTL.

### The order brief (`Drawer.jsx`)

Opens **beside** the map, never over a dimmed one — the whole point is reading
the job while looking at where it is. It shows the job facts, the run distance
and drive time, the parsed details, a **"This job needs"** chip row, the Parcel
Pass verdict for ad hocs, and the **full list of hauliers that fit** (fleet →
tier 1 → tier 2, closest first within each band). Tapping a haulier re-times the
job from their base and redraws their approach leg on the map. Each row has Call
and Email; Email opens an inline compose prefilled with the cover-request
wording taken from real Sent Items — anything unknown stays a **blank line**
rather than an invented value.

Also in the brief: the **materials-team escalation** ("Can't reach *X*? Ask
Steel Materials / Track Aggregates / SCO Sleepers & Troughing for another
contact"), which offers all three teams when the product doesn't map to one; the
ad hoc's **upload CSV with a Download button**; and **"Booked — remove from the
map"** for ad hocs / "Mark booked over the phone" for tracked orders.

### Design system

DHL red `#D40511` + yellow `#FFCC00` on a warm off-white; Archivo / JetBrains
Mono; `--radius:14px`; a three-tier shadow scale. Yellow top bar, red accents,
`--depot` near-black and `--go` green for the map.

---

## 9. The map subsystem (read this before touching `MapPage.jsx`)

**Stack:** Leaflet + react-leaflet, **OpenStreetMap raster tiles**,
**postcodes.io** for geocoding, **OSRM public demo server** for road routes.
All three are unauthenticated public services — everything degrades gracefully.

### Geocoding (`lib/geo.js`)

- Records carry **postcodes, not coordinates**, so everything is geocoded in the
  browser and cached in `localStorage` under `r2geo`.
- Batched 90 at a time against `POST https://api.postcodes.io/postcodes`.
- **Outcode-centroid fallback** for terminated industrial postcodes (British
  Steel's `DN16 1BP` no longer resolves). **Any new geocoding path needs this
  same fallback** or those sites silently vanish from the map.
- The three fixed **collection depots** (British Steel Scunthorpe, Inframat/VAS
  Askern, ArcelorMittal Marchwood) carry hard-coded real centroids and are
  **seeded into the cache after** the persisted cache loads, so the precise
  coordinate always wins over a stale/coarser cached one. Otherwise the depot
  *pin* renders at the precise point while a *route* to it snaps to the outcode
  centroid ~2 km away, and the route visibly misses its own pin.
- `pcNorm` canonicalises to `'OUTWARD INWARD'`. Extracts arrive spaced
  (`"LE10 1BJ  "`), unspaced (`"BS119DE"`) and with stray middle spaces
  (`"LE12 9 BS"`); without canonicalising, one place lands in the cache under
  several keys and a lookup from one spelling misses a pin geocoded under
  another. `orders.js` **re-exports** `pcNorm` from `geo.js` rather than
  defining its own — two copies is exactly how cache keys drift apart.

### Routing

`routeBetween(a, b)` hits OSRM `driving` with `overview=full&geometries=geojson`
and returns `{line, meters, seconds, road}` — geometry *and* drive time in one
request, because an ETA is made of exactly those. Cached in `localStorage` under
`r2routes2` (the key is **versioned**: v1 entries were a bare coordinate array,
so an old browser reading `.line` off an array would break). A failure falls
back to a straight line marked `road: false`, and the UI says "straight-line
estimate" rather than pretending.

### Focus mode

With a brief open the map becomes Google-directions: **only** that job is shown
— **A** (collection), **B** (delivery), the blue route, and the active haulier
with their dashed-green approach leg. Everything else — other orders, depots,
other haulier bases — is hidden. Extra pick-ups on a multi-collection job become
**A2 / A3** pins; the drawn route runs from the *first* collection (a multi-stop
route isn't invented for the ETA). Closing the brief is a deliberate re-frame
back to the overview.

### Camera behaviour — four separate bugs are encoded here

1. **`FitBounds` frames once and then never on its own.** It used to re-fit
   whenever the *number* of plotted points changed — which happens as postcodes
   geocode in one by one, on every tracker poll, and on every layer toggle. The
   map kept yanking itself back under the user, which reads exactly like "the
   pins won't stay put". Re-framing is now only ever deliberate: the initial
   fit, the **Fit all** button, or selecting an order.
2. **`FlyToRoute` is keyed on the ORDER, not the geometry.** Keying on geometry
   meant flying twice per click: once to the straight-line placeholder, then
   again when OSRM's road route arrived a second later.
3. **`FlyToPoint` / `FlyToRoute` are wrapped in `map.whenReady()` + try/catch**
   with `setView`/`fitBounds` fallbacks. Flying before the map has laid out
   (opening "View brief" from the tracker mounts the map with a selection
   already set) **threw and blanked the entire app** for any order with no
   collection on record.
4. **`ResizeOnBrief` calls `map.invalidateSize()`** 260 ms after the brief
   opens. Leaflet caches the container size; without this the projection keeps
   using the old width and every pin and tile sits offset.

### Layout / z-index

- `.mapwrap` sets `position:absolute; inset:0; z-index:1`, which gives it **its
  own stacking context** so Leaflet's internal panes and controls (which carry
  z-index up to 1000) stay *inside* the map instead of leaking above the drawer,
  notification popover and toasts.
- Overlays inside the map (`.legend`, `.layertoggle`, `.maploading`,
  `.mapwrap .uploadpanel`) use `z-index:1010` — that only has to beat Leaflet's
  1000 *within* that context, not the rest of the app.
- `.pin-icon` needed an explicit rule at the same specificity as
  `.leaflet-marker-icon` but loading **after** it — without it the pins sat in
  document flow instead of on the map (the one-CSS-line commit `4807d3f`).
- Attribution and zoom controls are both bottom-**left** so the required OSM
  attribution never collides with the legend (bottom-right).
- With a brief open, the map narrows to `calc(100% - min(480px,100%))` and the
  legend/layer panel shift left by the drawer width.

---

## 10. The ad hoc flow, end to end

This is the most recently-worked path and the one most likely to be extended.

1. **Drop a filled Haulage Request Form** (`.xlsx`/`.xlsm`) onto the *Ad hoc
   form* card on the Dashboard — or click it to pick a file. `AdhocFormCard`
   handles `onDragOver` / `onDragLeave` / `onDrop` and highlights the drop zone.
   (The card used to ask you to type a reference so the agent could go *search
   Outlook* for the form; drag-and-drop replaced that in `e771c0e`. `UploadCard`
   for the Synergy order upload works identically.)
2. `onUpload` → base64 → `POST /api/upload`, then `POST /api/command
   {action:'form_upload'}`.
3. The agent pulls the file from `/api/pull_upload`, writes it locally, and runs
   `process_form.py`.
4. `process_form.py` reads the form through **Excel itself** (so the form's own
   formulas produce genuine values), writes the **NR upload CSV** to the outbox
   with the order ref in the filename (`NR_heavy_AH30-7-26G5ML_<stamp>.csv`),
   keeps a copy of the form for forwarding, and appends the **map record** to
   `_adhocs.json`.
5. The agent `push_new_files()` (CSV appears in the **Files card**) and
   `push_panel()` (record appears in `panel.adhocs`).
6. **`App.jsx` auto-jumps to the map.** The first panel it sees is the baseline
   — old ad hocs must not hijack the screen on page load — so anything appearing
   *after* that is a form you just uploaded: toast, select it, switch to the map,
   brief open.
7. The brief shows the **Parcel Pass verdict**: a small load (transit / 7.5t /
   18t, no lifting kit, no PTS, no rear steer) is a **Parcel Pass** job with Call
   and Email buttons; anything needing a HIAB, Moffett, PTS, rear steer or a
   bigger vehicle is *"NOT ONE FOR PARCEL PASS"* with the reasons, and the
   haulier ring-round below.
8. When it's booked, **"Booked — remove from the map"** → `adhoc_booked` → the
   agent drops it from `_adhocs.json`, re-pushes the panel, and the pin is gone
   on the next poll. (Ad hocs aren't tracker records, so "Mark booked over the
   phone" never applied to them — that's why this button exists.)

Known ad hoc gotchas already handled: Excel's 1899/1900 epoch and `time(0,0)`
mean *"not set"* and must read as empty everywhere; collection and delivery
dates are separate columns and can differ; quantities may be **text**
("X1 DRUM", "12 x pallets"); a row-4 that repeats row 3 with `_R` is the
**return leg** of the same order (one merged record, not two half-jobs); an
identical-ref duplicate row would book the order twice and is dropped with a
note; and Excel floats (`1770679.0`) normalise to integers.

---

## 11. Recent changes (newest first)

The last ~30 commits, grouped. Each entry is *why*, not just *what* — the "why"
is usually a real incident.

**Work-PC / CTMS bridge (8cb2035, 5049e8a)**
Python landed on the work PC. Build loop: Claude writes on the home PC → GitHub
→ work PC downloads the ZIP and runs it; anything the work PC needs to send back
travels by email-to-self into home Outlook. `ctms_probe.py` (stdlib only, no
installs, no credentials) reports Python/pip/network/browser capability;
`ctms_attach_test.py` proves automation can attach to a browser *he* logged into
(Edge `--remote-debugging-port` + separate profile) so no password is ever
stored; `ctms_capture.py` is a hand-rolled CDP websocket client that snapshots
each CTMS screen — URL, title, full HTML, and every input/select/button with id,
name, label, placeholder and dropdown **options**, which is what selectors get
written from. Stage 0 stays read-only. **Blocked on:** his probe report and the
CTMS screen walkthrough.

**Ad hoc accuracy (4d6b9f0, 21a3e0d, f18f6c4)**
9–5 default for missing time windows; Excel float refs normalised; duplicate
rows dropped (caught live on order 1770679, where row 4 duplicated row 3 exactly
and would have booked the job twice). The brief now carries its own upload CSV
with a Download button, and CSV filenames carry the order ref so the Files card
reads as jobs rather than timestamps. Real collection vs delivery dates, text
quantities, and return legs merged into one record.

**Escalation + the blank-app crash (bc56c0e, 6ed8c86, 4ef7467)**
"I need an escalation button" — he had one, but only when materials matched
rails/ballast/sleepers, and the very order he needed it for had blank materials
and got no button. Unknown materials now offer all three teams. Worse: opening
*that* brief crashed the whole app to a blank page, because `FlyToPoint` threw
when flying before the map had laid out. Both fixed.

**Booked button for ad hocs (5348b73)** — "I have no way of removing it."

**Tracker completeness (bdd4b95)**
"You don't have all of the orders on the tracker." Reconciling the last 1200
Sent Items found 111 emailed-but-untracked orders. Two defects: the daily
recovery sweep rebuilt at most 8 orders/day but wrote its 20h throttle stamp
regardless, so a backlog never drained (cap raised 8 → 24); and one order was
too old for any extract so the rebuild path skipped it forever. Plus the churn
fix: booked drops are now remembered so the enrol sweeps stop resurrecting them.

**CTMS vehicle codes (3329d2a)**
"NR_ART_40_CT means artic curtain." The codes compose, so `vehicleInfo()`
decodes any of them, and the stated vehicle became a **hard need** in the
haulier match. HIAB on a tonnage-coded vehicle is a *rigid* hiab, not an artic
one.

**Haulier send safety (6e3708b)**
A cover request that **sent fine** was reported as failed — `metrics.log()`
passed `kind` twice, the TypeError after `m.Send()` ate the success line, and the
agent's "sent to" sniff reported an error for an email already in Sent Items.
That error message is one hopeful retry away from double-emailing a haulier.
Everything after `m.Send()` now sits in a try/except.

**Map work (92afe60, bc66229, 4ea77b0, 4807d3f, 76bf72c, 1377a5d, 4f727f2, bed8834, 027c025, f967ba1)**
Swapped an animated d3-geo SVG for a real Leaflet/OSM map; recalibrated depot
coordinates to real postcode centroids; stopped Leaflet's UI overlapping the
rest of the dashboard; fixed outward-code extraction (**pins were up to 41 miles
out**); stopped the view re-framing itself; fixed pins sitting in document flow;
added drive-time ETAs re-timed per haulier; then focus mode.

**Ad hoc drag-and-drop (e771c0e, 7831d8a, 40f0bde, 530ae4c)**
A drag-and-drop ad hoc queue was added, then file upload, then the ad hoc card's
Outlook search was replaced with drag-and-drop — and the separate queue page was
removed once the card did the job.

**React redesign (6b66c11)** — the whole UI, wired to the same API.

**Documentation (662fb6b, a5bd1f0)** — `LOCAL_STATE.md`, plus the CTMS booking
and licence-switch design docs.

---

## 12. Build & deploy

**Local UI dev**
```bash
cd region2-emailer/cloud/web
npm install
npm run dev          # Vite dev server; proxy /api to a running server.py
npm run build        # -> dist/index.html, ONE self-contained file
```

`vite-plugin-singlefile` inlines all JS/CSS so the Python server never has to
serve hashed asset chunks. `server.py` looks for the build at `$WEB_INDEX`, then
`./web_index.html`, then `./web/dist/index.html`, and falls back to its own
inline `PAGE` if none exists.

**Container** — the root `Dockerfile` is multi-stage: `node:22-slim` runs
`npm ci && npm run build`, then `python:3.12-slim` copies `server.py`,
`dist/index.html → web_index.html`, and the whole `dist/ → web_dist/` (for the
PWA assets). `PORT=8080`.

**Railway** — connect the repo, set `DASH_KEY` and `AGENT_KEY` (long random
strings), deploy, note the URL, then on the home PC write `cloud.json` from
`cloud.json.example`. The supervisor picks it up within ~20s.
Current deployment: `https://dhlbutbetter.up.railway.app` (in `desk.pyw`).

**PWA** — `manifest.webmanifest` + `sw.js` make it installable on a phone. The
service worker is **network-first for the app shell** (a deploy must land on
next open, never be pinned by a cache) with a cached fallback for offline, and
it **never touches `/api/*`** — stale tracker state presented as current would be
worse than an error.

**Home PC deps:** Python 3.12, `pywin32`, `openpyxl`, `pdfplumber` (DTS PDFs),
and Classic Outlook signed in.

---

## 13. Known issues & landmines

1. **Railway can serve more than one instance.** The cloud server keeps state in
   memory, so a second replica answers with an empty dashboard (no tracker,
   agent shown offline) depending on which one a request lands on. It **must**
   run as exactly one replica.
2. **Distances are straight-line** from postcode centroids in the ranking;
   drive time only exists where OSRM answered. Terminated industrial postcodes
   don't geocode and fall back to the outcode centroid — any new geocoding path
   needs the same fallback.
3. **The dashboard is a personal prototype.** The cloud instance holds order and
   contact data behind a single shared key. Moving it onto sanctioned
   infrastructure is a prerequisite for any team rollout.
4. **OSRM and postcodes.io are public, unauthenticated, rate-limited demo
   services.** Failures are expected and handled (straight-line fallback,
   fewer pins) — but a heavy day of geocoding can hit limits, and the caches are
   per-browser.
5. **The cloud loses `_files` and `_panel` on every redeploy.** The agent
   re-pushes files at startup and every 30 min, and the panel every 30s — but
   there's a window where the Files card looks empty while the CSVs still exist
   in the outbox. The outbox itself purges at 48h, so a Download can legitimately
   fail with "aged out".
6. **Two agents, one mailbox.** Anything new that sends or writes on a timer
   must be gated behind `IS_LOCAL`. This is the single easiest way to reintroduce
   double-sends.
7. **`server.py` still carries ~1000 lines of legacy inline HTML** (the old
   dashboard) as a fallback. It is *not* kept in sync with the React app — don't
   fix a bug there and assume it's fixed in the UI people actually use.
8. **Never define a second postcode normaliser or geocode cache key.** See §6.
9. Untracked local scratch currently in the working tree:
   `region2-emailer/_index_scan.url`, `_search.url` (SharePoint shortcuts) and
   `auto_chase.disabled.bak`. These are local artifacts, not part of the repo,
   and `.gitignore` doesn't cover `_*.url` — don't commit them by accident.

---

## 14. Open threads / roadmap

| Thread | State |
|---|---|
| **CTMS auto-booking** | Spec written (`CTMS_BOOKING_SPEC.md`), probes committed. Blocked on the work-PC probe report + a CTMS screen walkthrough before selectors can be written. Staged safety model: assist → supervised auto → full auto, always with dry-run, screenshots, a stop button and an idempotency check. |
| **Supplier collect-first** | Two-stage supplier→delivery draft flow for Anderton / BCM / Trough Tec. Needs an HS number from an upload sheet — pending. |
| **Consolidation** | Spot same-day deliveries to the same/nearby postcode area so two jobs share one vehicle. Advisory suggestion in the extract output. |
| **Quote comparison** | `quotes.py` works; entry is manual. The haulier layer and contact recommendations are live on the map. Once quote history is deep enough, *cheapest* supersedes *distance* in the ranking tie-break. |
| **Licence switch + auto-update** | Design only (`LICENCE_SWITCH_DESIGN.md`). Hard principle written down loudly: **disable, never destroy.** Signed tokens, 14-day grace window, signed+staged code updates. Not implemented. |
| **Team rollout** | Gated on moving off the personal Railway instance and on the role renegotiation happening *first*. |

---

## 15. Working conventions

- **Commit messages** read like an incident note: a one-line subject that says
  the outcome, then a body explaining what the user actually said, what broke,
  and what changed. Look at `git log` for the house style — matching it matters
  here, because these messages are the project's real changelog.
- **Comments explain the incident, not the syntax.** Most of the odd-looking
  code in this repo is odd because of a specific real-world failure; the comment
  above it is usually the only record of that failure. Preserve them.
- **Nothing sends without a human confirm** unless it's an explicitly opt-in
  timed job. Preview/draft first is the default across the whole toolkit.
- **Never invent a value.** Blank lines, "—", and "still needed:" are correct
  outputs. A guessed date or time reaches a real haulier.
- **The repo is private today but is intended to be handed over one day** — so
  keys, addresses and contact lists are described in docs, never reproduced.
- Branches: `main` is live. `dhl-haulage-desk-redesign` and
  `claude/python-work-pc-justification-1a5891` are older/parallel lines.

---

## 16. Quick reference

```bash
# home PC
python supervisor.py                     # starts everything
pythonw desk.pyw open                    # launcher + open the dashboard
python build_drafts.py batch             # today's extract → pending batch
python build_drafts.py week next         # a whole delivery week
python phase2.py check                   # replies, briefs, booked sweep
python phase2.py chase send              # send the 2-business-day chasers
python waitlist_release.py               # DRY RUN; add `send` to actually send
python process_form.py "<form.xlsx>"     # ad hoc → NR upload CSV + map record
python synergy_map.py "<extract.xlsx>"   # order upload → NR CSV
python rail_plan.py "<short_rail.csv>"   # weekly rail plan
python hauliers.py import "<list.xlsx>"  # rebuild the haulier directory
python metrics.py                        # the evidence summary
python tests/test_modules.py             # modules/ tests

# UI
cd region2-emailer/cloud/web && npm run dev     # or: npm run build

# cloud
DASH_KEY=… AGENT_KEY=… PORT=8080 python server.py
```

**If you're picking this up cold:** read `region2-emailer/LOCAL_STATE.md` next —
it tells you which local files exist, which are irreplaceable, and how to
restore on a new machine. Then skim `git log` for the last ten commits; the
bodies carry the operational history this file summarises.
