# Changes to apply on the HOME PC (agent side)

The dashboard (cloud/server.py) was updated on 2026-07-06. The agent code
(`agent.py` / `supervisor.py` and friends) lives only on the home PC — it has
never been committed to this repo — so these matching changes have to be made
there. Open a Claude Code session on the home PC in this folder and point it
at this file, or apply by hand.

## 0. First: get the home PC back online

The dashboard shows "home PC: offline" whenever the agent hasn't contacted the
cloud in the last 15 seconds. While it's offline, every dashboard command
(including "Send email") just sits in the cloud's in-memory queue — nothing
reaches Outlook, so nothing appears in Sent Items or Drafts. Check, in order:

1. Is the PC on and awake? Disable sleep/hibernate:
   `powercfg /change standby-timeout-ac 0` and
   `powercfg /change hibernate-timeout-ac 0`
2. Is `supervisor.py` actually running? (Task Manager → look for the python
   process; consider a Scheduled Task "At log on" so it survives reboots.)
3. Does `region2-emailer/cloud.json` exist, with the CURRENT Railway URL and
   the CURRENT `AGENT_KEY`? A Railway redeploy keeps env vars, but if the URL
   or keys were ever regenerated, cloud.json must be updated to match.
4. Quick test from the home PC:
   `curl https://YOUR-APP-URL/healthz` → should return `{"ok": true, ...}`.
   Then check the agent's log for auth errors (401 = wrong AGENT_KEY).

## 1. CC support on send

The dashboard now sends `email.cc` alongside `to`/`subject`/`message` in the
`order_send_edited` command. In the agent, where the Outlook item is built:

```python
cc = (email.get("cc") or "").strip()
if cc:
    mail.CC = cc          # semicolon-separate multiple addresses
```

Optionally include `"cc": ""` (or a sensible default) in the preview email
dict pushed to `/api/status` so the dashboard's Cc box pre-fills.

## 2. Fast order-number search (the "Outlook finds it in seconds" fix)

Manual Outlook search is fast because it uses the Windows Search content
index. Looping over `folder.Items` in Python and reading each item over COM
is what makes the current search slow. Use `Items.Restrict` with a DASL
`ci_phrasematch` filter — that goes through the same index:

```python
import re

def find_order_items(ns, order, folder_ids=(6, 5)):   # 6 = Inbox, 5 = Sent Items
    """Index-backed Outlook search — same engine as the Outlook search box."""
    order = re.sub(r"\D", "", str(order))              # digits only: no DASL injection
    if not order:
        return []
    hits = []
    for fid in folder_ids:
        items = ns.GetDefaultFolder(fid).Items
        try:
            # content-indexed: returns in well under a second even on huge mailboxes
            flt = ('@SQL=("urn:schemas:httpmail:subject" ci_phrasematch \'%s\' '
                   'OR "urn:schemas:httpmail:textdescription" ci_phrasematch \'%s\')'
                   % (order, order))
            found = items.Restrict(flt)
        except Exception:
            # store not indexed — LIKE scan; slower but still far faster than a Python loop
            flt = ('@SQL=("urn:schemas:httpmail:subject" LIKE \'%%%s%%\' '
                   'OR "urn:schemas:httpmail:textdescription" LIKE \'%%%s%%\')'
                   % (order, order))
            found = items.Restrict(flt)
        # sort the RESTRICTED collection (sorting `items` first is not inherited)
        found.Sort("[ReceivedTime]" if fid == 6 else "[SentOn]", True)
        for i in range(1, found.Count + 1):
            hits.append(found.Item(i))
    return hits
```

Notes:
- `ci_phrasematch` matches whole words — order numbers in subjects/bodies are
  normally standalone tokens, so this behaves like the Outlook search box. If
  an order number can be embedded inside another string (e.g. `PO6054999`),
  the LIKE fallback catches it; you can also run LIKE only when the indexed
  search returns nothing.
- Never fetch `.Body` of every item to search it — that is the slow path.
  `Restrict` filters server-side/against the index first, so you only touch
  the handful of real hits.
- To search the whole mailbox (all folders) like Outlook's "All Mailboxes",
  `Application.AdvancedSearch` with the same DASL filter works asynchronously,
  but per-folder `Restrict` on Inbox + Sent Items is usually all that's needed
  and is much simpler.
- Same trick applies to the DTS-PDF and form lookups if they loop over items.

## 3. Never fail silently on send

Wrap the actual send and report the result to the cloud status, so the
dashboard shows a red error instead of nothing:

```python
try:
    mail.Send()
    post_status("done", f"Sent to {mail.To}" + (f" (cc {mail.CC})" if mail.CC else ""))
except Exception as e:
    post_status("error", f"Send FAILED — nothing sent: {e}")
    raise
```

## 4. Commit the home-PC code to git (the "unpushed" work)

The engine has never been in the repo — only `cloud/` is. From the home PC:

```
git checkout main && git pull origin main
git add region2-emailer/*.py        # supervisor.py, agent.py, etc.
git status                          # confirm NO xlsx/pdf/config/tracker/cloud.json files are staged
git commit -m "Add home-PC engine (supervisor + agent)"
git push origin main
```

`.gitignore` already excludes work data and `cloud.json` (secrets) — double
check `git status` output before committing anyway.
