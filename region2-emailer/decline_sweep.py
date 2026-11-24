"""File hauliers' "no" replies out of the Inbox into Region 2 > Completed.

    python decline_sweep.py          DRY RUN - list what would be filed
    python decline_sweep.py apply    file them

A ring-round asks 5-10 hauliers per job and most say no; on 05/10/2026 the planner
asked for the no's to go straight to Inbox/Regions/Region 2/Completed "so it
doesn't absolutely clutter my inbox". Filed, never deleted - Completed is where
he files finished mail, and the quote board and the chaser both read it.

Only the top level of the Inbox is swept, and an email is filed only when ALL
of these hold:
  * it is from a haulier in the directory (address, or the haulier's own domain)
  * its subject names an order we have asked hauliers to cover (_haulier_asks.json)
  * modules/haulier_replies.classify() calls it a clean no - no price, no
    question, no "could do Tuesday instead", nothing we are unsure of.
Anything else stays where the planner will see it.
"""
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from modules import haulier_replies as hr          # noqa: E402
from modules import chase_rules as cr              # noqa: E402

DAYS = 7


def _haulier_who(ctx_addr, ctx_dom, addr):
    a = str(addr or "").lower()
    return a in ctx_addr or (cr.domain(a) in ctx_dom and "@" in a)


def main():
    apply = "apply" in [a.lower() for a in sys.argv[1:]]
    import build_drafts as bd
    import haulier_asks
    import chase_guard as g
    asked = {str(k).strip() for k, v in haulier_asks.load().items() if v}
    if not asked:
        print("No ring-round asks on record - nothing to sweep.")
        print("SWEEP_RESULT filed=0")
        return 0
    ctx = g.context(state={})
    h_addr, h_dom = ctx["haulier_addresses"], ctx["haulier_domains"]
    ns = bd.get_ns()
    root = bd.dhl_store(ns)
    inbox = bd.sub(root, "Inbox") if root is not None else None
    regions = bd.sub(inbox, "Regions") if inbox is not None else None
    region2 = bd.sub(regions, "Region 2") if regions is not None else None
    done = bd.sub(region2, "Completed") if region2 is not None else None
    if inbox is None or done is None:
        print("Inbox or Inbox/Regions/Region 2/Completed not found - nothing filed.")
        print("SWEEP_RESULT filed=0")
        return 1
    since = datetime.now() - timedelta(days=DAYS)
    items = inbox.Items.Restrict(f"[ReceivedTime] >= '{g._outlook_date(since)}'")
    picked = []
    for it in items:
        try:
            if int(getattr(it, "Class", 0)) != 43:
                continue
            subj = str(it.Subject or "")
            orders = [o for o in asked if o and o in subj]
            if not orders:
                continue
            sender = g._smtp_of_sender(it)
            if not _haulier_who(h_addr, h_dom, sender):
                continue
            verdict = hr.classify(str(it.Body or ""))
            if verdict != "decline":
                continue
            picked.append((it, sender, subj, hr.own_text(str(it.Body or ""))[:80]))
        except Exception:
            continue
    filed = 0
    for it, sender, subj, said in picked:
        line = f"  {'FILED' if apply else 'would file'}  {sender:<38} {subj[:55]:<55} \"{said}\""
        if apply:
            try:
                it.Move(done)          # never touch the item after Move
                filed += 1
            except Exception as e:
                line = f"  FAILED  {sender} {subj[:55]}: {e}"
        print(re.sub(r"\s+\n", "\n", line))
    n = filed if apply else len(picked)
    print(f"\n{n} haulier 'no' repl{'y' if n == 1 else 'ies'} "
          f"{'filed to Region 2 > Completed' if apply else 'would be filed (dry run)'}.")
    print(f"SWEEP_RESULT filed={filed if apply else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
