"""
Send the backlog: emails the tool PREPARED but never actually sent.

    python resend_backlog.py            DRY RUN - lists what would go, sends nothing
    python resend_backlog.py send       actually sends
    python resend_backlog.py send 10    ...at most 10 (default cap is 25)

When the send gate failed, build_drafts.py had already done its half of the
job: each email was written, bound to the account, saved into Outlook Drafts,
and logged to the tracker as status="drafted". Only the send was lost. So the
backlog is not something to rebuild from the extract - it is sitting in the
Drafts folder, already reviewed, and this sends exactly what was prepared.

Three things it will NOT do, each for a reason:

  * anything already in SENT ITEMS is skipped. You may have sent it by hand
    while the tool was failing, and Sent Items is the only source that knows.
  * anything whose DELIVERY DATE HAS PASSED is never sent - it is reported as
    MISSED instead. Emailing a site to arrange a delivery that already
    happened is worse than not emailing at all. Same rule waitlist_release.py
    has always used.
  * it stops at a cap. A backlog that has built up quietly can be large, and
    a hundred emails leaving at once is its own incident.

Dry run is the default. Nothing leaves without `send` typed explicitly.
"""
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_drafts as bd      # noqa: E402
import metrics                 # noqa: E402
import send_order as so        # noqa: E402
import tracker                 # noqa: E402

DEFAULT_CAP = 25


def _past(dd):
    """True if this delivery date has already gone by."""
    try:
        return datetime.strptime(str(dd).strip()[:10], "%d/%m/%Y").date() < datetime.now().date()
    except Exception:
        return False          # unparseable: not our call to make, let it through


def outstanding():
    """Tracker records the tool prepared but never emailed."""
    d = tracker.load()
    out = []
    for r in d.get("records", []):
        if r.get("emailed_at"):
            continue                       # it went out
        if str(r.get("status") or "").lower() not in ("drafted", ""):
            continue
        if not (r.get("orders") and r.get("to")):
            continue
        out.append(r)
    return out


def main():
    argv = [a.strip().lower() for a in sys.argv[1:]]
    do_send = "send" in argv
    cap = next((int(a) for a in argv if a.isdigit()), DEFAULT_CAP)

    recs = outstanding()
    if not recs:
        print("Nothing outstanding - every tracked order has an emailed_at.")
        print("SEND_RESULT sent=0")
        return 0
    print(f"{len(recs)} order group(s) prepared but never emailed.\n")

    ns = bd.get_ns()

    # Check the gate ONCE, up front. If it is still broken there is no point
    # walking the whole backlog to fail on every single one - and a run that
    # fails 40 times in a row is how you end up unsure what actually happened.
    acct = so.dhl_account(ns)
    if acct is None:
        print("\nABORT: the send gate is still failing - fix that first "
              "(python check_sending.py). Nothing attempted.")
        print("SEND_RESULT sent=0")
        return 2

    all_orders = sorted({o for r in recs for o in r.get("orders", [])})
    print(f"Checking {len(all_orders)} order(s) against Sent Items and Drafts...")
    already = bd.find_already_emailed(ns, all_orders, limit=1500)

    todo, skipped, missed, nodraft = [], [], [], []
    for r in recs:
        label = f"{' / '.join(r.get('orders', []))} -> {r.get('to')} ({r.get('delivery_date')})"
        hits = [already.get(o) for o in r.get("orders", []) if already.get(o)]
        if any(h["where"] == "Sent Items" for h in hits):
            when = next(h["when"] for h in hits if h["where"] == "Sent Items")
            skipped.append(f"{label}  - already in Sent Items {when}")
            continue
        if _past(r.get("delivery_date")):
            missed.append(label)
            continue
        draft = next((h for h in hits if h["where"] == "Drafts" and h.get("entryid")), None)
        if not draft:
            nodraft.append(label)
            continue
        todo.append((r, draft["entryid"], label))

    for line in skipped:
        print(f"  SKIP    {line}")
    for line in nodraft:
        print(f"  NO DRAFT {line}  - nothing prepared to send; rebuild it with build_drafts.py")
    for line in missed:
        print(f"  !! MISSED {line}  - delivery date has PASSED, not sending. Handle by hand.")

    if len(todo) > cap:
        print(f"\n  ({len(todo)} ready, capped at {cap} this run - re-run for the rest)")
        todo = todo[:cap]

    print(f"\n{len(todo)} to send:")
    for _, _, label in todo:
        print(f"  {'SEND' if do_send else 'would send'}  {label}")

    if not do_send:
        print(f"\nDRY RUN - nothing sent. Add 'send' to actually send these {len(todo)}.")
        print("SEND_RESULT sent=0")
        return 0

    sent = 0
    for r, eid, label in todo:
        try:
            m = ns.GetItemFromID(eid)
            if not so.bind_account(m, acct):
                print(f"  ! could not bind account, NOT sent: {label}")
                continue
            m.Send()
            # Past this point the email is GONE. Nothing here may turn a real
            # send into a reported failure - the 24/07 rule.
            sent += 1
            try:
                tracker.log(orders=r.get("orders", []), to=r.get("to"),
                            name=r.get("name", ""), product_codes=r.get("product_codes", []),
                            materials=r.get("materials", ""), site=r.get("site", ""),
                            postcode=r.get("postcode", ""), delivery_date=r.get("delivery_date"),
                            source=r.get("source", ""), status="sent",
                            worksite=r.get("worksite", ""),
                            collection_site=r.get("collection_site", ""),
                            collection_pc=r.get("collection_pc", ""),
                            collections=r.get("collections"))
                metrics.log("email_sent", orders=r.get("orders", []), to=r.get("to"),
                            what="backlog_resend")
            except Exception as ex:
                print(f"    (sent, but bookkeeping hiccup: {ex})")
            print(f"  SENT  {label}")
        except Exception as ex:
            print(f"  ! FAILED {label}: {type(ex).__name__}: {ex}")
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass

    print(f"\nSent {sent} of {len(todo)}.")
    if missed:
        print(f"!! {len(missed)} order(s) MISSED their delivery date and were NOT "
              f"sent - these need handling by hand.")
    print(f"SEND_RESULT sent={sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
