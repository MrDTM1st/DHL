# Moving the whole toolkit onto the work PC

**Goal:** everything — engine, dashboard, agents, CTMS automation — runs on the
work PC, and the home PC is no longer in the loop.

**Status:** runbook. Nothing here has been executed yet.

This is feasible. The engine needs Classic Outlook, four pip packages and
nothing else (see [`requirements.txt`](requirements.txt)) — no external
binaries, no hardcoded paths. But two things decide whether it *works*, and
neither is a dependency problem. Read §1 before doing anything.

---

## 1. The two things that actually decide this

### 1.1 Two machines on one mailbox will double-send. There is no guard.

This is the one that can hurt a real customer, so it comes first.

Every single-instance lock in the codebase binds `127.0.0.1` — watchdog 8785,
supervisor 8786, control plane 8787, agents 8788/8789, chase run 8790,
wait-list release 8791. They are **same-machine locks only**. And the "already
chased today" claim is written to the **local** `tracker.json`:

```python
# phase2.py — claim_chase()
if r.get("last_chased_at") == today:
    return False                 # already claimed by another run
```

Two PCs means two `tracker.json` files. Each claims independently, each sends.
`IS_LOCAL` does not help — it was designed to separate two agents on **one**
PC, and both machines would consider themselves local.

The toolkit has already caused this exact incident once (every chaser sent
twice, a wait-list email twice) and the whole `IS_LOCAL` design exists because
of it. A cross-machine version of it would be worse, because nothing in the
code can currently detect it.

**So the cutover is hard, not gradual.** The home PC engine stops *before* the
work PC engine starts. There is no overlap period, no "run both for a week and
see". §4 is written around that.

One softer spot: the wait-list release is safer than the chasers, because it
re-checks Outlook Sent Items (`find_already_emailed`) before sending, and Sent
Items is mailbox-level, so it *is* shared between machines. It would mostly
catch a duplicate. "Mostly" is not a safety model — do the hard cutover anyway.

### 1.2 A laptop that sleeps is not an always-on machine

The timed jobs assume a PC that never stops:

| Job | Cadence | What a sleeping machine costs |
|---|---|---|
| `monitor_tick.py` | 60s | new extracts and replies aren't noticed until you're back |
| `phase2.py check` | 20 min | bookings don't appear on the tracker |
| order index refresh | 15 min | "send one order" gets slow, not broken |
| wait-list release | 3h | **an order due to auto-send can miss its window** |
| wait-list scan | 12h | far-ahead orders aren't captured |
| auto-chasers | 3h (opt-in) | chasers slip a day |
| untracked-order recovery | daily (opt-in) | backlog drains slower |

Most of that is *delay*, and delay is survivable. The wait-list release is the
one with teeth: it exists to auto-send ~14 days before delivery, and
`waitlist_release.py` marks anything whose date passed while waiting as
**MISSED**. A laptop that is off every evening and weekend will eventually
produce a MISSED that a home PC would not have.

`engine_preflight.py` reads the actual power settings on the machine and tells
you what they are. If the answer is "sleeps after 30 minutes", the options are:

- set sleep and hibernate to **never on AC**, and lid-close to **do nothing**,
  and leave it docked and plugged in overnight (needs to be allowed by policy);
- or accept the delays, and move only the wait-list release to something
  always-on (that would be the cloud — it is the only always-on piece we have);
- or keep the home PC purely as the timer and run everything else here, which
  is not "everything on the work PC" and re-opens §1.1.

**This is the decision the migration hangs on.** Everything else is logistics.

---

## 2. What has to move

Code comes from GitHub. Data does not — it is gitignored and lives only on the
home PC. `engine_preflight.py` lists exactly what is present and what is not.

| Group | Files | How |
|---|---|---|
| **Irreplaceable** | `_metrics.jsonl`, `_details_learned.json`, `_quotes.json`, `config.json`, `config/team.json`, `synergy_template.xlsx`, `_rail_recipients.json` | copy by hand; back up first |
| **Live state** | `tracker.json`, `waitlist.json`, `_booked_drops.json`, `_adhocs.json`, `order_index.json` | copy **at cutover**, not before — they change hourly |
| **Rebuildable** | `_hauliers.json`, `_synergy_sites.json`, `_sites.json` | copy, or rebuild from the source sheets |
| **Optional** | `cloud.json`, `qr.png`, `auto_chase.enabled`, `auto_recover.enabled` | copy if you want the same behaviour |

`_metrics.jsonl` is the evidence log for the business case — it goes back to
2026-07-19 and cannot be reconstructed. Back it up somewhere that is not either
PC before you start.

**Do not put any of these in the repo.** They are gitignored on purpose.
Move them on a USB stick or through a sanctioned corporate channel — and note
that `config/team.json` and `synergy_template.xlsx` carry colleague and
supplier contact details, so that channel choice is a real one, not a
formality.

---

## 3. What changes in the topology

Almost nothing, which is the good news:

```
BEFORE                                  AFTER
home PC: engine + 2 agents              work PC: engine + 2 agents + CTMS tools
work PC: CTMS probes only               home PC: nothing
Railway: control plane                  Railway: control plane (unchanged)
```

- `supervisor.py`, `agent.py`, `control_plane.py`, the watchdog and every port
  work identically — they were never home-PC-specific, only Windows-specific.
- `IS_LOCAL` keeps working and keeps being necessary: two agents (local + cloud)
  on one PC is exactly the case it was written for.
- The Railway control plane does not change at all. Keep it if you want phone
  access; drop `cloud.json` if you don't, and use `127.0.0.1:8787`.
- The CTMS work stops being a "second agent on a second machine" and becomes
  just another thing this machine does. `CTMS_BOOKING_SPEC.md` §"Where it runs"
  should be updated once this lands — it currently says the rest of the toolkit
  stays on the home PC.

---

## 4. The cutover

Steps 1–5 are safe to do while the home PC carries on working. Step 6 is the
point of no overlap.

1. **Back up** the irreplaceable files from the home PC to somewhere that is
   neither PC.
2. On the work PC: get the code (`git clone`, or Download ZIP), then
   `pip install -r requirements.txt`. If pip cannot reach pypi.org, see §4.1.
3. `python work_pc\engine_preflight.py` — expect green Python/packages/Outlook/
   ports, and read what it says about sleep settings.
4. Copy the **irreplaceable** and **rebuildable** files across. Re-run the
   preflight; the state list should now be mostly present.
5. **Dry-run everything that does not send.** These are all read-only or
   draft-only:
   ```
   python build_drafts.py            (preview only - never sends)
   python phase2.py check            (drafts briefs, sends nothing)
   python waitlist_release.py        (DRY RUN unless you add `send`)
   python metrics.py                 (the evidence summary)
   python tests/test_modules.py      (the modules/ tests)
   ```
   Compare the output against the home PC's. Same orders, same counts.
6. **Cutover.** On the home PC, in this order:
   - close the dashboard,
   - kill the watchdog (port 8785) and the supervisor (8786) — the watchdog
     first, or it will restart the supervisor within 90 seconds,
   - remove the watchdog from the Startup folder so a logon can't revive it,
   - confirm no `python.exe`/`pythonw.exe` running `supervisor.py` remains.
7. Copy the **live state** files across now that nothing is writing to them.
8. On the work PC: `python supervisor.py`, then put the watchdog in the Startup
   folder.
9. Watch for one full working day with **both opt-in switches off** — no
   `auto_chase.enabled`, no `auto_recover.enabled`. Those are the two jobs that
   act without asking; leave them off until a day has gone cleanly, then turn
   them back on one at a time.

---

### 4.1 When pip cannot reach pypi.org

`WinError 10061 ... actively refused` on a machine whose browser downloads from
GitHub fine is the signature of a corporate proxy: the browser reads the
system proxy (and PAC file) automatically, pip reads neither.

`work_pc\ctms_probe.py` reports the registry proxy settings, the PAC URL and
`netsh winhttp show proxy`, and prints the `pip --proxy` line to try. Three
outcomes:

1. **A real `host:port`** — `pip install --proxy http://host:port -r requirements.txt`.
   Make it permanent in `%APPDATA%\pip\pip.ini`.
2. **A PAC URL only** — pip cannot read a PAC file. Open the PAC URL in the
   browser, read the `PROXY host:port` out of it, and use that. This is also
   the moment to ask IT whether there is an **internal package mirror**
   (Artifactory / Nexus), which is what they will prefer you use anyway:
   `pip install --index-url https://<mirror>/simple -r requirements.txt`.
3. **Blocked outright** — use the offline route below.

**The offline route — wheels on a USB stick.** This works regardless of policy,
and costs nothing extra, because *you have to visit the home PC anyway* for the
state files in §2 and the cutover in step 6. Do both in one trip.

On the **home PC** (which already has all four packages and working internet):

```
cd region2-emailer
pip download -r requirements.txt -d wheels --only-binary :all: ^
    --platform win_amd64 --python-version 312
```

Copy the `wheels` folder onto the same USB stick as the state files. Then on the
**work PC**:

```
pip install --no-index --find-links=wheels -r requirements.txt
```

`--platform`/`--python-version` matter: without them pip downloads wheels for
the machine it is standing on. Both PCs are Windows on Python 3.12 here, so the
values above are right — but check the work PC's version (the preflight prints
it) if that ever stops being true.

If USB storage is blocked by policy, the same wheels can travel as an email
attachment to yourself — they are ordinary files, though `pywin32` is ~10 MB
and some filters dislike archives.

---

## 5. Risks specific to a corporate machine

None of these are blockers, but finding them at step 8 instead of step 3 costs
a day.

- **Classic Outlook, not New Outlook.** New Outlook has no COM interface at all.
  If IT migrates the machine to New Outlook, the engine stops dead. This is a
  bigger risk on a managed work PC than on a home one, and it is worth knowing
  the rollout plan before committing.
- **Outlook's programmatic-access guard** can throw a "a program is trying to
  send mail on your behalf" prompt, which stalls an unattended send. It is
  normally suppressed when a registered antivirus is present, which a corporate
  build will have — but confirm it at step 5.
- **EDR / antivirus** may take an interest in a Python process driving Outlook
  and opening localhost listeners. Worth clearing with IT *before* it gets
  quarantined mid-day.
- **Startup folder policy.** The preflight checks whether it is writable. If it
  is locked down, Task Scheduler at logon is the fallback.
- **Governance.** A read-only CTMS probe is one conversation. The full toolkit —
  contact lists, order state, an agent polling a personal Railway instance from
  a corporate machine — is a different and much bigger one.
  `SESSION_CONTEXT.md` §13 already flags moving off the personal Railway
  instance as a prerequisite for team rollout; running it *from* a work machine
  brings that forward. Have that conversation before step 6, not after.

---

## 6. Rollback

Keep the home PC intact — do not delete anything — until the work PC has run
clean for a week. Rolling back is: stop the work PC supervisor and watchdog,
copy the live state files back, restart the home PC supervisor. The same hard
rule applies in reverse, for the same reason: **only one machine runs the
engine at a time.**
