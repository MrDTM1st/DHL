# Work-PC setup — CTMS automation

The work PC never needs Claude installed. The build loop is:

```
home PC (Claude writes code) -> GitHub -> work PC (download & run)
work PC (reports, screen captures) -> email to yourself -> home Outlook (Claude reads)
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

## Step 2 — run the probe

Open Command Prompt in the extracted `region2-emailer\work_pc` folder and run:

```
python ctms_probe.py
```

It checks (using nothing but Python itself — no installs needed):

- Python version and where it is
- whether `pip` works, and whether pypi.org is reachable (for installing
  Playwright later)
- whether the Railway control plane is reachable (the dashboard link-up)
- whether Edge/Chrome exist and whether a debug session can be attached
  (how the automation will drive YOUR logged-in browser — no passwords)
- proxy settings that installs might need

It writes **`ctms_probe_report.txt`** next to itself.

## Step 3 — send the report home

Email `ctms_probe_report.txt` to yourself (delali.opoku@dhl.com) with the
subject **CTMS probe**. The home toolkit picks it up from there and the next
build step gets written against what your work PC can actually do.

## Step 4 — the CTMS walkthrough (when ready)

For each main CTMS screen (login landing, order search, an order open on
screen, the booking form):

1. Open the screen in the browser.
2. `Ctrl+S` → save as **"Webpage, Complete"** into one folder.
3. Also take a screenshot of each (Win+Shift+S) if easy.

Email the lot to yourself, subject **CTMS walkthrough**. The saved HTML is
what the automation's selectors get written from — the more screens, the
fewer guesses.
