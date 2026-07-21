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

- Runs on the **WORK PC** — that's where CTMS is logged in. The rest of the
  toolkit stays on the home PC; this is a **second agent**, on the work PC.
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

## Data → CTMS field mapping (capture during the walkthrough)

| CTMS field | Source (extract / tracker / derived) | Formatting / notes |
|---|---|---|
| _(to fill in)_ | | |

## What I need from the CTMS walkthrough

1. The exact booking journey: URL, each screen, each field, the order of steps,
   the buttons.
2. For each field: where its value comes from (extract / tracker / derived) and
   any formatting rules.
3. How CTMS confirms a booking (confirmation number / screen) so we capture proof.
4. The **update an existing job** flow, if it differs from a new booking.
5. Edge cases: validation errors, duplicate warnings, required-but-sometimes-blank
   fields, multi-line jobs, etc.
6. How the bot should decide **which** jobs to book (from the tracker? a dashboard
   selection? a whole day / week?).

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
