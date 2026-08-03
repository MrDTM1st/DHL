# Work-PC setup — CTMS automation

The work PC never needs Claude installed. The build loop is:

```
home PC (Claude writes code) -> GitHub -> work PC (download & run)
work PC (reports, screen captures) -> paste into the chat, or email to
                                      yourself -> home Outlook (Claude reads)
```

## Ground rules (non-negotiable)

- **Your CTMS password is never typed into, stored in, or read by any script.**
  You log in yourself in the browser; the tools only drive a session you
  already opened.
- Stage 0 is **read-only** — looking things up, never changing them. Booking
  writes come later, in stages, each one signed off by you first.
- Keep your manager/IT in the loop about what runs on this machine.

## Step 1 — get the code (no git needed)

1. In the browser: `github.com/MrDTM1st/DHL` → green **Code** button →
   **Download ZIP**.
2. Extract somewhere sensible, e.g. `Documents\DHL-tools`.
3. Updates later = download the ZIP again and replace the folder
   (or `git clone` / `git pull` if git is allowed here — even better).

## Step 2 — one command

Open Command Prompt in the extracted `region2-emailer\work_pc` folder and run:

```
python start_here.py
```

That is the whole setup. Using nothing but Python itself — no installs — it:

- checks Python, `pip`, and whether pypi.org / GitHub / the Railway control
  plane are reachable from this machine
- finds Edge (or Chrome) and **launches it for you** on a debug port, with its
  own separate profile. You do **not** need to close the Edge you are working
  in, and you do not need to paste a long command line
- proves the automation can attach to that browser — the no-password approach
- writes `ctms_workpc_report.txt` **and** prints the report between two
  markers at the end

**Then:** select everything between `----- BEGIN CTMS WORK-PC REPORT -----`
and `----- END ... -----`, copy it, and paste it into the chat. (Or email
`ctms_workpc_report.txt` to yourself, subject **CTMS probe**, if that is
easier — the home toolkit picks it up from there.)

A fresh browser window will have opened. **Log into CTMS in that window**, as
normal, and leave it open.

> If the report says the debug port never opened, that is usually group policy
> switching remote debugging off on a managed build. Send the report anyway —
> the next step gets rewritten around what this machine does allow.

## Step 3 — the CTMS walkthrough

With CTMS logged in in that window, run:

```
python ctms_capture.py
```

Then just **use CTMS normally** — search an order, open it, start a booking.
Give each screen a name when it asks, and it snapshots the current tab:

- the URL and title
- the full HTML, **including inside frames** (enterprise screens keep the real
  form in one, and a snapshot that stops at the frame boundary is empty)
- every input / select / button, with id, name, label, placeholder and
  **dropdown options** — this is exactly what selectors get written from
- a **PNG screenshot**, so the field list is readable later

Cover at least: the login landing, order search, an order open on screen, and
the booking form. Snapshots land in `work_pc\ctms_capture\`.

Zip that folder and email it to yourself, subject **CTMS walkthrough**.

It is **read-only** — it takes pictures, it never clicks, types or submits.
The capture does include page text and field values, so avoid capturing a
screen showing anything you would not want in your own mailbox.

---

### The older scripts

`ctms_probe.py` and `ctms_attach_test.py` still work standalone and do the
probe and the attach test separately — `start_here.py` just does both, plus
the browser launch, in one go. Nothing was removed.
