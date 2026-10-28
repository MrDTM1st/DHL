# CTMS Auto-Booking — Design / Build Spec

**Status:** the bridge and the LEARNER PHASE are BUILT (see below): Claude, on
the home PC, sees CTMS on the work PC live and works it while Delali directs it
in the chat; the bridge updates itself from GitHub. Automated booking (Stage 1+)
still waits on learning the screens, which that phase is for.
**Needs:** Python on the **work PC** (that's where the CTMS session lives) -
standard library only. Playwright turned out not to be needed: it drives Edge
over the same DevTools connection the bridge already uses, and installing it on
a locked-down work PC is the part most likely to fail.

Sits on top of the existing toolkit — the job data it books comes from what we
already parse (extracts / tracker). This is the automation that actually *acts*
on CTMS, so the safety model matters more here than anywhere else.

---

## Goal

Book (and update) jobs on CTMS automatically by driving the browser with
Playwright, using the author's own already-logged-in CTMS session (no stored
password). Triggerable from the existing dashboard **and** from a phone via a PWA.

## Where it runs (important)

- Runs on the **WORK PC** — that's where CTMS is logged in. Originally this was
  to be a *second* agent alongside a home-PC engine; the work PC has since been
  proven able to run the whole toolkit (see `WORK_PC_MIGRATION.md`), so booking
  ends up as one more thing the single machine does rather than a split.
- Playwright against the logged-in Chrome, no credentials stored:
  - **Option A (recommended):** persistent context on a dedicated Chrome profile
    that's signed into CTMS — robust and stable for automation.
  - **Option B:** connect over CDP to an already-running Chrome
    (`--remote-debugging-port`) — drives the actual browser you're using.
- It reuses the existing authenticated session; it does not log in or bypass any
  authentication.

## Control flow (phone + web)

```
Phone PWA / dashboard
      → hosted control plane (Railway)
          → work-PC agent polls for the command
              → runs the Playwright booking on CTMS
                  → posts status + confirmation (+ screenshot) back
      ← dashboard / phone shows the result
```

- Same outbound-only agent pattern already in use: nothing connects *into* the
  work PC.
- Requires the work PC on + the work-PC agent running for remote control (same
  trade-off as today's home-PC desk).

### What is built - the Stage 0 bridge

`work_pc/ctms_bridge.py` on the work PC, the **CTMS** page on the dashboard,
and a channel of their own on the control plane (`/api/ctms/*` in
`cloud/server.py`). Standard library only, like the rest of `work_pc/`.

- **Its own channel and key.** Not more actions on the home agent's queue: the
  work PC can never pull an Outlook command, and the home agent never sees a
  CTMS one. The bridge's key is derived from `DASH_KEY` (HMAC, `ctms-bridge-v1`),
  so nothing new is set on Railway; the work PC stores only the derived key,
  which opens the bridge's endpoints and nothing else.
- **Observe commands for the dashboard** - `look` (a picture now), `capture`
  (one walkthrough screen), `net` (record what CTMS sends, on/off). (Stage 0
  had nothing else; the learner phase below added acting, behind a switch.)
- **Live view.** While the CTMS page is open on screen, the bridge sends a
  scaled JPEG of the CTMS tab every ~1.5s (an unchanged screen costs a few
  bytes). Nothing streams when nobody is looking.
- **The walkthrough comes home by itself.** Each capture is zipped (fields with
  dropdown options, page HTML, page text, PNG, network log), kept on the work
  PC in `work_pc\ctms_capture\`, sent to the cloud, and collected by the home
  PC's cloud agent into the same folder there, unpacked.
- **Nothing secret leaves.** Password boxes are blanked, a sign-in request's
  body is never recorded, and session ids / tokens are stripped from every
  address, form action, link, request body and the page HTML. Tested in
  `tests/test_ctms_bridge.py`.
- **Commands expire in 60s, online or not.** "Capture this screen" run late
  would capture the wrong screen under the right name.
- **Stop** cancels anything queued and switches recording off. Every command
  and result is logged on the work PC in `work_pc\ctms_bridge_log.jsonl`.
- **Single instance:** port 8792 (the toolkit's locks run 8785-8791).

### What is built - the learner phase (Claude drives, Delali directs)

Delali asked for "a live connection between the work PC and the home PC" so
Claude can see CTMS, ask what to do, and do it - learning CTMS before any of it
is automated. Three parts:

- **`work_pc/ctms_drive.py`** - what the bridge does in the CTMS tab. `see`
  returns a picture with every clickable thing numbered on it (frames and
  shadow roots included), the numbered list (role, label, value, options,
  frame) and the page text. `click` / `type` / `key` / `select` / `scroll` /
  `hover` act on a number (or `click --at x,y` on the picture);
  `goto` / `back` / `forward` / `reload` / `dialog` / `wait` / `tab(s)` round
  it out. Every action answers with a fresh `see`, so the result is seen, not
  assumed. Built on the stdlib CDP client: real mouse and key events
  (keyup-driven lookups fire), settle-waits for page loads and data calls,
  confirm()/alert() boxes reported the moment they open.
- **`ctms_remote.py`** (home PC) - how Claude uses it: `python ctms_remote.py
  see`, `click 12`, `type 7 "HS6366072" --enter`, ... Reads `cloud.json`
  (url + agent_key). Keeps `ctms_remote/latest.jpg` and a step-by-step trace in
  `ctms_remote/trace/<day>/` (picture + screen + command + result) - the record
  Stage 1 selectors get written from.
- **The relay** - the bridge's check-in is held open (`wait`, up to 20s) until
  there is work, and Claude's wait for an answer is held open until it lands
  (`GET /api/ctms/result?id=&wait=`), so a command and its result are one round
  trip of a second or two, with no hard polling.

Who may do what (server-enforced, and the bridge checks again on its side):

| | dashboard (`DASH_KEY`) | home PC / Claude (`AGENT_KEY`) | bridge (derived key) |
|---|---|---|---|
| look: `see`, `wait`, `tabs`, `look`, `capture`, `net` | yes | yes | - |
| act: `click`, `type`, `key`, `select`, `scroll`, `hover`, `goto`, `back`, `forward`, `reload`, `dialog`, `tab` | only while armed | only while armed | - |
| switch **Claude can act** on/off (`/api/ctms/control`, 5-480 min) | **yes** | no | no |
| Stop (cancels the queue, disarms) | yes | no | no |
| `update` | yes | yes | - |
| check in, answer, upload pictures/captures | - | - | yes |

The rails, in code (`ctms_drive.py`), not good intentions:

- **Two locks to act:** the work PC must allow it (`allow_control`, asked at
  setup; `--allow-control` / `--observe-only`) AND the dashboard switch must be
  on. It runs out by itself; Stop and switching off cancel anything queued.
- **Sign-in page:** a visible password box anywhere (frames included) means
  nothing is clicked or typed on that page. Password boxes are never typed
  into. Clipboard paste and browser-level keys (close, print, DevTools...) are
  refused.
- **Commit guard:** a button/link/key/dropdown/dialog answer that would book,
  save, submit, confirm, send, delete (or cancel an order/booking/job) is
  refused unless the command carries `commit` - which Claude only sends after
  Delali says go in the chat. Judged on the label, on ids/names/onclick split
  out of camelCase, and on the form's action; a submit button with no label
  counts as risky, and so does a click into a frame the bridge cannot read.
  Reload/back onto a form-submit page and `goto` an address that looks like an
  action need it too.
- **Stale numbers:** a number only works against the picture it came from; if
  the page navigated or redrew, the action is refused ("look again").
- **goto** stays on the CTMS host.

**One-click setup** ("Set up this PC" on the CTMS page, asked for so the work
PC needs no Command Prompt at all): `GET /api/ctms/setup` (dashboard key only)
fills `cloud/ctms_setup.py` with this dashboard's address, the bridge key and
his two choices, and puts `@python -x "%~f0" %* & pause & goto :eof` in front -
Windows runs that line on a double-click, `python -x` skips it. The setup gets
the code (PAC proxy -> PowerShell -> a DHL-main.zip in Downloads), installs into
`%USERPROFILE%\CTMS-bridge`, writes the config, checks `POST /api/ctms/hello`,
writes/removes the Startup-folder entry (`ctms_bridge.py --autostart on|off`),
closes any running bridge and starts the new one in its own console (not via
`start` from a shell: an inherited handle kept the setup window from closing).
The bridge remembers CTMS's app root (`ctms_url`) and opens the automation
browser on it. A web page cannot start programs on the PC, so this is the one
double-click; everything after it is buttons.

**Remote updates** (`work_pc/ctms_update.py`): `update` (dashboard button or
`ctms_remote.py update [--branch B] [--all]`) makes the bridge download the
branch's ZIP from GitHub - code never comes from the dashboard - compile every
changed file and import the bridge's modules in a scratch folder, back up what
it replaces (`_update_backups\`, flat numbered files: deep paths hit Windows'
260-character limit), lay the new files down and exit 75. `ctms_bridge.py` now
runs as a small **supervisor** plus the bridge as its child: exit 75 restarts
on the new code; a child that dies before its first check-in after an update is
rolled back automatically (`_update_rolled_back.json`, shown on the dashboard);
anything else restarts up to three times in ten minutes. Verified end to end on
the home PC: good update, update that does not compile (refused), update that
crashes on start (rolled back by itself).

## Safety model — human-in-the-loop, staged

Consistent with the toolkit's existing "draft/preview, you approve" philosophy.
Booking is the one action that touches the outside world, so it earns the extra
care.

- **Stage 1 — Assist:** the bot fills the CTMS booking form and **stops at the
  final submit**. It shows a preview (and/or a screenshot) on the dashboard/phone;
  a human taps **Confirm** to submit.
- **Stage 2 — Supervised auto:** the bot submits, but **one job at a time**, with
  a visible log and an easy stop. Anything unusual — unexpected screen, validation
  error, ambiguous match — **pauses for a human** instead of guessing.
- **Stage 3 — Full auto:** batch booking, only after Stages 1–2 have proven it on
  real jobs. Always with a stop button and a full audit log.
- **Always on:** a **dry-run** mode; a **screenshot of every booking** as an audit
  trail; a hard **stop** button; and an **idempotency check** against the tracker
  so the same job is never booked twice.

## Data → CTMS field mapping

The **source** column is settled — this is everything the toolkit already holds
by the time an order is ready to book, taken from `tracker.py`,
`delivery_details.py` and `hauliers.py`. Only the left column is unknown, and
the walkthrough fills it in.

| CTMS field | Source we already have | Formatting / notes |
|---|---|---|
| _(walkthrough)_ | `orders[]` | order number(s); a vehicle can carry several |
| | `delivery_date` | `dd/mm/yyyy` everywhere |
| | `site` / `worksite`, `postcode` | delivery end |
| | `collection_site`, `collection_pc`, `collections[]` | a job can load at several sites |
| | `product_codes[]`, `materials` | BS extracts have these columns swapped. Pass them through **`ctms_codes.product_code()`** — CTMS wants one code per type (`BAG_BALLAST`, `LOOSE_BALLAS`, `LOOSE_STONEB`) where the extracts spell ballast a dozen ways. `None` back means CTMS has no special code and the product books under its own description. **This is the only place that mapping belongs** — it was briefly applied to the NR upload's ITEMS row instead, where it corrupted the file: those codes appear in 0 of 510 ITEMS rows across the 47 genuine Access exports, which send the NR stock code (`0057/100500/002`) untouched |
| | `details.date.value` | the date confirmed in the reply, if it moved |
| | `details.time.earliest` / `.latest` | **CTMS needs two.** A single time is expanded by +2h (73% of replies give one) |
| | `details.offloading.value` | **"Yes" means HIAB** — policy, not inference |
| | `details.artic_access.value` | |
| | `details.rear_steer.value` | |
| | `details.vehicle.value` | already a CTMS code — `NR_ART_40_CT` etc; `vehicleInfo()` decodes them |
| | `details.pts.value` | never assumed; unstated = unknown, chased on rails only |
| | `details.what3words.value` | |
| | `details.contact.name` / `.phone` | site contact on the day |
| | `details.collection_time` | |
| | `details.notes.value` | |
| | `loose_ballast` | |
| | haulier `ctms` id | **already mapped** — `hauliers.py` imports a "CTMS Names" sheet into `_hauliers.json`, so haulier → CTMS name is a lookup, not a guess |

Every `details` field also carries `confidence: "high" | "amber"`. **Amber must
never be auto-submitted** — that is precisely the flag saying a human has not
confirmed this value. `details.missing[]` lists what is still unknown;
non-empty means the job is not bookable yet.

## What I still need — the walkthrough

With the bridge running, open the **CTMS** page on the dashboard: it lists the
screens below with a Capture button each, and ticks them off as they arrive.
Bring each screen up in CTMS on the work PC and press Capture. Each one records
URL, full HTML (including inside frames), every field with its id / name /
label / dropdown options, a PNG, and - with recording on - the network calls.
(`work_pc\ctms_capture.py` still does the same at the keyboard, as a fallback.)

| Screen | Why |
|---|---|
| home | where the journey starts |
| order-search (empty) | the search field selectors |
| search-results | how a result is identified and opened |
| order-open | which of our fields CTMS already knows vs which we supply |
| booking-form-empty | the field list, required markers, dropdown options |
| **booking-form-filled** | **the most important one.** Filled for a real job, *not submitted* — it shows what a correct value looks like in each field |
| confirmation | how CTMS confirms, so we can capture proof + the reference |
| booked-job | the update-an-existing-job flow, if it differs |
| validation-error | how failures present, so the bot can stop rather than guess |

Switch **What CTMS sends** on first. It records the requests CTMS makes, and
answers the one architectural question in this whole build:

- **CTMS posts the booking to a JSON API** → drive that API. Stable, fast,
  survives UI changes, and the response gives us the confirmation reference
  directly. This is much the better outcome.
- **CTMS submits a classic form postback** → drive the DOM with selectors.
  Workable, but brittle, and every CTMS release can break it.

Still open after the walkthrough, and a decision rather than a discovery: how
the bot chooses **which** jobs to book — everything the tracker marks ready, a
dashboard selection, or a day/week at a time.

## PWA (phone control)

- Add a **web app manifest + service worker** to the existing dashboard so it's
  installable on the phone home screen and behaves like an app.
- The phone triggers the same commands the dashboard does (book job X / today's
  batch) and sees status + confirmations.
- **Auth:** keep it behind the existing dashboard key (`DASH_KEY`) + HTTPS. Never
  put job data or keys in URLs/query strings.

## Rollout checklist

- [x] Bridge: work PC ↔ dashboard, observe only, its own key and channel.
- [ ] Walkthrough captured from the dashboard (all nine screens, recording on).
- [ ] Read-only lookups (booked? MAN ref? which orders share a vehicle) from the captures.
- [ ] Booking script built from the walkthrough; **dry-run** first.
- [ ] Stage 1 (assist) on a handful of real jobs.
- [ ] Audit log + stop button verified.
- [ ] Graduate stages only after clean runs.

## Governance note

This automates the author's own authorised CTMS access — normal RPA. Two things
keep it low-risk: (1) keep a **human confirm** in the loop until it's proven —
that's the guard against fast, repeated mistakes; and (2) be mindful CTMS may
carry its own usage terms. A preview/confirm model driving your own logged-in
session is the sensible, low-blast-radius way to run it.
