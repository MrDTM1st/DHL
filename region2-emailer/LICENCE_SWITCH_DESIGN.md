# Server Link — Licence Switch + Auto-Update — Design Note

**Status:** Design only. NOT implemented, NOT wired into the toolkit yet.
Parked here on purpose so the thinking isn't lost while we focus on other work.

---

## Purpose

Give the author a clean way to (a) prove ownership of the toolkit, (b) switch it
off if a licence lapses, and (c) push updates (bug fixes and new features) from a
server so machines pull the latest without a manual reinstall — all over the same
server link. A normal software licensing + update control, the same way
commercial software behaves.

## Hard principle: DISABLE, never destroy

This switch **stops the app from running**. It does **not** delete, corrupt,
encrypt, brick, or otherwise damage anything on the machine.

- No file deletion.
- No touching of company data or the OS.
- No "logic bomb" / self-destruct behaviour of any kind.

Reason this is written down loudly: a switch that *disables* is a defensible
licensing mechanism. A switch that *destroys* is a criminal matter (in the UK,
Computer Misuse Act — unauthorised impairment of a computer) and would misfire on
any server outage. We are deliberately building the safe one. If anyone reading
this later is tempted to make it destructive: don't. It converts an IP dispute
into a prosecution and takes out the very proof needed to justify wider rollout.

---

## How it works (flow)

1. On boot, before doing any work, the app calls a small **licence endpoint**
   (a server the author controls) and sends its machine ID.
2. The endpoint replies with a **signed** status token, e.g.
   `{ status: active | inactive, expires: <date>, grace_days: 14, machine: <id> }`.
3. The app **verifies the signature** against a public key baked into the build
   (server holds the private key). This stops anyone forging an "active" reply or
   editing a local config to flip the switch themselves.
4. Decision:
   - `active` and not expired  → run normally.
   - `inactive`, or past `expires` → show a message and exit cleanly.

## Fail-open vs fail-closed — use a grace period

The toolkit runs operational work, so "can't reach server ⇒ refuse to run" is too
brittle (a dropped connection would lock everyone out). Use a **cached grace
window** instead:

- The app stores the last **valid signed token**.
- If the server is unreachable, it keeps running while the cached token is still
  inside its grace window (e.g. 14 days since the last good check).
- Only a definite `inactive` from the server, or a fully-lapsed grace window,
  disables it.

Net effect: brief outages are invisible; a deliberate switch-off, or a long
absence, disables — without ever depending on the server being up 24/7.

## When the door is closed

- App shows a plain message: *"Licence inactive — please contact <author>."*
- App exits. Nothing is changed on disk. Re-enabling is instant: flip the server
  back to `active`, next boot runs again.

---

## Components to build (later)

1. **Licence endpoint** — tiny web service the author controls. State per machine:
   active/inactive + expiry. Signs each response.
2. **Client check module** — one function called at startup: fetch, verify
   signature, apply grace-period logic, allow/deny.
3. **Signed tokens** — public key embedded in the build; private key only on the
   server. Prevents local spoofing.
4. **Machine binding (optional)** — token tied to a machine ID so a token copied
   to another PC doesn't authorise it.
5. **Graceful exit** — clear message, clean shutdown, nothing destructive.

## Honest limits

- The check is **client-side**, so a determined person could patch it out. Raise
  the bar by shipping the toolkit **compiled (Nuitka)** or **obfuscated
  (PyArmor)** rather than as plain `.py`. Not bulletproof — nothing client-side
  is — but enough to stop casual bypass.
- PyArmor can also enforce an **expiry date** in the code itself, as a second,
  offline layer alongside the phone-home check.

## What this deliberately does NOT do

- ❌ Delete or modify files
- ❌ Damage the machine or company data
- ❌ Trigger anything on network failure (grace period covers that)
- ✅ Only ever: allow the app to run, or stop it from running

---

## Auto-Update (same server)

Bug fixes and new features are served from the same server: each machine checks
its version on boot and pulls the latest when there's a newer one.

**Not the same as `self_update.py`.** That existing module applies *data/config*
updates (site store, team, settings) from "R2 UPDATE" emails. This is a separate
thing — it updates the *code itself*. Keep them clearly named and separate.

### How it works
1. On boot, the licence call (or a second endpoint) also returns an **update
   manifest**: `{ latest_version, url, sha256, signature, mandatory? }`.
2. Client compares `latest_version` to its own. If newer: download to a staging
   folder, verify checksum **and signature**, then apply and restart.

### Safety rails (these are not optional)
- **Sign every update.** Same key approach as the licence token — the client only
  applies an update whose signature verifies. This is the single most important
  rule: without it, anyone who compromises the server or the domain can run code
  on every machine. Signature check first, always.
- **Atomic swap + rollback.** Stage the full download, verify, then switch over —
  so a half-downloaded update can't leave a broken install. Keep the last
  known-good version; if the new one fails a startup self-check, revert to it
  automatically.
- **Staged rollout.** Update your own machine (or one canary PC) first, confirm
  it's healthy, then release to the rest. Never push to everyone at once.
- **Never mid-operation.** Apply on boot / when idle, not while a batch is
  running.
- **Version log / changelog.** Track what version is on each machine and what
  each release changed.

### Governance note (same theme as the switch)
An auto-update channel means you can run new code on company machines remotely.
That's powerful and normal for software — but on company kit it's exactly the kind
of thing IT will (reasonably) care about. Keep updates **signed, logged, and
reviewable**, and ideally have the mechanism be **known/agreed** rather than
silent. That protects you too: "signed, logged, staged updates" is defensible;
"one person can silently push arbitrary code to all PCs" is what gets flagged.

### Open decisions
- Mandatory vs optional updates? Auto-apply vs prompt-to-update?
- Which machine is the canary?
- Same endpoint as the licence check, or a separate one?

## The real protection is paper, not code

The switch is a convenience, not the safeguard. The thing that actually protects
ownership — especially if the author ever leaves — is a **written agreement**:
"author owns the toolkit; company licenses it." Do this alongside, and ideally
make the company aware the licence check exists, so the off-switch is transparent
rather than a surprise. A known, disable-only licence control on agreed IP is
completely normal; a secret one on business-critical software is the part that
causes trouble.

## Open decisions for later

- Grace window length (7 / 14 / 30 days?).
- Machine binding on or off?
- Where the endpoint is hosted, and how the author flips a machine on/off.
- Packaging choice for anti-bypass: Nuitka vs PyArmor (vs both).
- Whether the company is told about the check (recommended: yes).
