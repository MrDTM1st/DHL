# What lives on the home PC (and isn't in this repo)

The code is here on GitHub. The **data isn't** — contacts, keys, live order
state and everything the tool has learned stay on the home PC and are
gitignored. This file is the map of that: what each local file is, whether
losing it matters, and the rules the code encodes.

> **Nothing in this file is a secret.** Keys, email addresses, phone numbers and
> contact lists are deliberately described, never reproduced. Keep it that way —
> the repo is private today, but this project is intended to be handed over one
> day.

---

## 1. Where things run

| Piece | Runs on | Notes |
|---|---|---|
| `supervisor.py` | home PC | starts/restarts everything below; single instance |
| `control_plane.py` | home PC | local dashboard, `127.0.0.1:8787`, no auth (localhost only) |
| `agent.py` ×2 | home PC | one talks to the local control plane, one to the cloud |
| `cloud/server.py` | Railway | public dashboard; **state is in memory only** |
| `desk_watchdog.pyw` | home PC | restarts the supervisor within ~90s; launched at logon |

Outlook is driven through COM, so this **cannot** run headless — it needs a
logged-in Windows session with Classic Outlook open. All traffic is **outbound**
from the home PC; the cloud never connects inward.

**Single-instance locks (ports):** watchdog 8785, supervisor 8786, control plane
8787, local agent 8788, cloud agent 8789, chase run 8790, wait-list release 8791.

**Timed jobs — all gated to the LOCAL agent only** (`IS_LOCAL` in `agent.py`).
Both agents run on the same PC against the same mailbox, so any timed job that
*sends or writes* must run on exactly one of them, or it fires twice. This
caused real double-sends (every chaser twice, a wait-list email twice). Data
pushes stay on both agents so the cloud dashboard stays fresh.

| Job | Cadence |
|---|---|
| `monitor_tick.py` (live Outlook watch) | ~60s, via supervisor |
| `phase2.py check` (replies, briefs, booked sweep) | 20 min |
| wait-list release (auto-send at ~14 days) | 3h |
| wait-list scan (capture far-ahead orders) | 12h |
| order index refresh | 15 min |
| auto-chasers | 3h — **opt-in** |
| untracked-order recovery | daily — **opt-in** |

---

## 2. Local-only files

### Secrets / configuration — irreplaceable, hand-built
| File | Holds |
|---|---|
| `config.json` | active region, its postcode areas, extract filename rules, collect-first supplier config |
| `config/team.json` | the team roster (names + DHL addresses) and "me", for never-email-yourself and handover |
| `cloud.json` | the Railway URL and the agent key |
| `qr.png` | feedback QR embedded in the signature |
| `synergy_template.xlsx` | the real Synergy Template File — **contains the Supplier Details contact book** |

### Reference data — rebuildable from a source sheet, but not quickly
| File | Holds | Rebuild |
|---|---|---|
| `_hauliers.json` | 55 hauliers + 5 couriers: locations, phones, emails, 40+ capability flags, tiers, CTMS ids | `hauliers.py import <contact list.xlsx>` |
| `_rail_recipients.json` | rail-plan distribution chains + the haulier email map | hand-built from the SOP |
| `_synergy_sites.json` | ~121 collection sites (contact, postcode, loading hours) + learned additions | seeded from Supplier Details, then self-learning |
| `_sites.json` | known delivery site names + learned mappings | self-learning |

### Learned / accumulated — **irreplaceable, back these up**
| File | Holds | Why it matters |
|---|---|---|
| `_details_learned.json` | wording → value corrections you've confirmed | the parser gets smarter only from this |
| `_quotes.json` | haulier quotes per lane | the cost estimates are built from it |
| `_metrics.jsonl` | every send, catch and skip since 2026-07-19 | **this is the evidence for the business case** |
| `_pc_geo.json` | cached postcode coordinates | just a cache, safe to lose |

### Live operational state
| File | Holds |
|---|---|
| `tracker.json` | open orders being chased, with parsed delivery details |
| `waitlist.json` | far-ahead orders held until ~14 days before delivery |
| `order_index.json` | order number → which extract contains it |
| `_monitor_seen.json` | watermarks so the live monitor doesn't re-fire |
| `_last_recover.txt`, `_heartbeat_*.txt` | last-run / liveness stamps |

### Feature switches (presence of the file = ON)
| File | Effect |
|---|---|
| `auto_chase.enabled` | chasers send automatically every 3h |
| `auto_recover.enabled` | daily sweep re-enrols emailed-but-untracked orders |

Delete the file to turn the behaviour off. Both are deliberately opt-in because
they act without asking.

### Scratch — safe to delete any time
`_*.xlsx`, `_*.csv`, `_*.xls*`, `_search.xlsx`, `_brief.xlsx`, `_syn_up_*.xlsx`,
`__pycache__/`, `*.log`. These are working copies of attachments pulled from
Outlook. `outbox/` holds generated files (rail plans, upload sheets, NR CSVs)
and is also local-only.

---

## 3. Rules the code encodes

Domain decisions that aren't obvious from reading the code:

**Region & scope**
- Region 2 = a fixed set of English postcode areas, matched on the **delivery**
  postcode.
- **Supplier rails** (order number starts with a letter) and **stoneblowers**
  (STONEBLOWER in the product) are booked separately — never emailed.
- **BS batch files** are real Region 2 work and must be processed like the
  normal extract. Their product columns are **swapped** versus the Synergy
  extract, so the readable wording is chosen by *content*, not column position.

**Emails**
- One email per contact + site + delivery date; subject carries the orders, the
  worksite and the postcode.
- Far-ahead orders wait and auto-send ~14 days before delivery — nothing is
  forgotten, nothing is emailed twice.
- Chasers: 2 business days, max 3, never twice in a day, and **never** for an
  order already booked.

**Bookings**
- A booking is your own sent email containing *"this order has been arranged
  with …"* or a **MAN reference**. It counts whether you sent it as a fresh
  email or a reply.
- A booking covers the **whole vehicle**: it clears every tracked order sharing
  that contact + postcode + date, not just the order it names.

**Delivery details (from replies)**
- CTMS needs two times; a single time is expanded by **+2 hours**.
- "Yes" to offloading means **HIAB**.
- A date range means: consolidate if possible, otherwise take the **latest**
  date.
- **PTS is never assumed** — it's a safety certification, so unstated means
  unknown, and it's only chased on rail orders.

**Hauliers**
- Order of approach: **DHL NOC (our own fleet) → Tier 1 → Tier 2.** Distance
  only breaks ties *within* a band.
- Tier is encoded as the **cell colour** in the contact list, not text — and two
  hauliers are marked **Do Not Use**; they are filtered out everywhere and never
  published to the dashboard.

---

## 4. Restoring on a new machine

1. Clone the repo, install Python 3.12 + `pywin32`, `openpyxl`.
2. Restore the local files above (they are **not** in the repo — copy them from
   a backup or rebuild the reference ones from their source sheets).
3. Set the Railway environment variables (`DASH_KEY`, `AGENT_KEY`) — the cloud
   server refuses to start without them.
4. Start `supervisor.py`; add the watchdog to the Startup folder for logon.

**Back up, at minimum:** `config.json`, `config/team.json`, `cloud.json`,
`_synergy_sites.json`, `_rail_recipients.json`, `_details_learned.json`,
`_quotes.json`, `_metrics.jsonl`, `tracker.json`, `waitlist.json`.

---

## 5. Known issues

- **Railway can serve more than one instance.** The cloud server keeps state in
  memory, so a second instance answers with an empty dashboard (no tracker,
  agent shown offline) depending on which one a request lands on. It must run as
  exactly **one** replica.
- Distances are straight-line from postcode centroids — good for "who's
  nearest", not drive time. Terminated industrial postcodes (e.g. the British
  Steel depot) don't geocode and fall back to the outcode centroid; **any new
  geocoding path needs that same fallback.**
- The dashboard is a personal prototype: the cloud instance holds order and
  contact data and is protected by a single shared key. Moving it onto
  sanctioned infrastructure is a prerequisite for any team rollout.
