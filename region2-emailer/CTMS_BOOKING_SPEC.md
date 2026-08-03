# CTMS Auto-Booking — Design / Build Spec

**Status:** Spec. Build blocked pending a CTMS screen walkthrough.
**Needs:** Python + Playwright on the **work PC** (that's where the CTMS session lives).

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
| | `product_codes[]`, `materials` | BS extracts have these columns swapped |
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

Run `work_pc\ctms_capture.py`. It is guided: it asks for each screen below in
order, and captures URL, full HTML (including inside frames), every field with
its id / name / label / dropdown options, a PNG, and the network calls.

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

Say **yes** to the network question. It records the requests CTMS makes, and
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

- [ ] Playwright installed on the work PC; dedicated CTMS Chrome profile set up.
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
