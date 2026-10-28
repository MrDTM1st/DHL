# Work-PC setup — CTMS automation

The work PC never needs Claude installed. Once the bridge is running (Step 3)
the loop is live, through the dashboard:

```
Claude (home PC) -> ctms_remote.py -> Haulage Desk -> ctms_bridge.py (work PC) -> CTMS in Edge
        ^                                                                           |
        +------------- a numbered picture of the screen, the words on it -----------+
you -> the dashboard's CTMS page: watch it live, switch "Claude can act" on/off, Stop
```

and new code reaches the work PC by itself: Claude pushes it to GitHub, and the
bridge fetches it, tries it, and restarts on it when asked (see **Updates**).

## Ground rules (non-negotiable)

- **Your CTMS password is never typed into, stored in, or read by any script.**
  You log in yourself in the browser; the tools only drive a session you
  already opened. The bridge will not click or type on a page that shows a
  password box at all.
- Claude can always **look**. It can only **act** (click, type, choose) while
  you have **Claude can act** switched on on the dashboard's CTMS page — it
  switches itself off after the time you pick, and **Stop** cuts it off at
  once. Anything that would book, save, submit, confirm or delete waits for
  your go-ahead in the chat, every time.
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

## Step 3 — the bridge: CTMS on the dashboard, and in Claude's reach

Get the latest code first (`python update_from_github.py apply`, or the ZIP as
in Step 1) — the last time you need to: from here on the bridge updates
itself (see **Updates** below). Then, in the `work_pc` folder:

```
python ctms_bridge.py
```

and leave that window open while you work. The first run asks three things:

1. **The Haulage Desk's address** — press ENTER for the usual one.
2. **The key you log into the Haulage Desk with** — the same one you type in
   the browser. It does not show as you type. The bridge keeps only a key
   *made from* it, which opens the bridge's own channel and nothing else — it
   cannot send email or run the desk.
3. **Whether Claude may act in CTMS** when you switch that on from the
   dashboard. Say **n** and this PC stays look-only whatever the dashboard
   says. Change your mind later with `python ctms_bridge.py --allow-control`
   or `python ctms_bridge.py --observe-only`.

It opens the automation browser if it is not open already (the same separate
window `start_here.py` opens). **Log into CTMS in that window** yourself. Then
open the **CTMS** page on the dashboard — laptop or phone — and you will see
the CTMS tab as it is on this PC, updating every couple of seconds.

Every command it gets is written to `ctms_bridge_log.jsonl` here, and the
window prints each one as it happens, so you can see exactly what it did.

Keep the CTMS window open (it can sit behind other windows) and keep CTMS as
its selected tab — a minimised window cannot be pictured.

## Step 4 — the walkthrough, from the dashboard

On the dashboard's CTMS page:

1. Switch **What CTMS sends** on. It records the requests the CTMS page makes,
   which tells us whether bookings go to an API or a form. Sign-in requests
   and passwords are never recorded.
2. Work through CTMS on this PC as normal. For each screen in the
   **Walkthrough** list, get it on screen and press **Capture**. The most
   important one is **booking-form-filled** — the booking form filled in for a
   real job, *not submitted*.

Each capture is kept here in `work_pc\ctms_capture\` and sent home: the home
PC collects it within a minute. No zipping, no emailing yourself.

The captures include page text and field values (never passwords, never
session tokens), so avoid capturing a screen showing anything you would not
want in your own mailbox.

## Step 5 — working CTMS with Claude (the learner phase)

1. On the dashboard's CTMS page, switch **Claude can act** on (15 min, 1 hour
   or 4 hours). The badge at the top turns amber while it is on.
2. In the chat, tell Claude what to do — "open order 6055515", "put 08:00 in
   earliest", "pick the HIAB rigid". It looks at the screen, does it, and
   sends back what it sees, so you can watch it on the dashboard or on this
   PC's screen as it happens.
3. When it reaches anything that would **book, save, submit, confirm or
   delete**, it stops and asks you. It only goes ahead once you say so.
4. **Stop** on the dashboard switches acting off at once; so does the timer
   running out.

What it will never do, whatever it is told: type into a password box, click or
type on the sign-in page, paste from this PC's clipboard, open a site other
than CTMS, or close/print/save the browser. Every step it takes is kept on the
home PC (picture + what was on screen), which is what the booking automation
gets written from.

## Updates — from the home PC, nothing to do here

After this first setup you should not need to touch the code on this PC again.
The dashboard's **Update** button (on the CTMS page) — or Claude, after it has
pushed a change — tells the bridge to:

1. fetch the code from GitHub (`github.com/MrDTM1st/DHL`, main) — the only
   place code ever comes from; the dashboard can say *when*, not *what*;
2. try it in a scratch folder first — every changed file must compile and the
   bridge must start — and refuse it if not;
3. copy aside the files it replaces (`_update_backups\`), lay the new ones
   down, and restart on them;
4. if the new code dies before it checks in, **put the old files back by
   itself** and carry on. The dashboard says so ("Rolled back: ...").

`python ctms_bridge.py --rollback` puts back what the last update replaced, by
hand. The bridge updates its own folder (`work_pc\`) by default; the whole
toolkit can go the same way when everything moves to this PC.

---

### The older scripts

`ctms_probe.py` and `ctms_attach_test.py` still work standalone and do the
probe and the attach test separately — `start_here.py` just does both, plus
the browser launch, in one go. `ctms_capture.py` is the walkthrough at the
keyboard — the same captures as the dashboard's Capture button, saved here
instead of sent home (zip `ctms_capture\` and email it to yourself, subject
**CTMS walkthrough**). Nothing was removed.
