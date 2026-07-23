"""
Wait-list release - the auto-send half of the wait list.

Runs daily on the home PC (the agent calls it). For every wait-listed order now
within the lead window it SENDS the held email from the DHL account - but only
after re-checking, at send time, that:
  * the order hasn't already been drafted/sent by the tool (tracker), and
  * you haven't emailed the contact yourself in the meantime (Sent/Drafts), and
  * the delivery date hasn't slipped into the past.
Anything already handled is quietly closed off; anything whose date passed while
waiting is marked MISSED and reported loudly so it can never be silently dropped.

    python waitlist_release.py          # DRY RUN - show what would send
    python waitlist_release.py send     # actually send due entries
"""
import sys
import build_drafts as bd
import metrics
import send_order as so
import tracker, waitlist


def _send_one(outlook, acct, e):
    to, cc, removed = bd.clean_to_cc(e.get("to", ""), e.get("cc", ""))
    if not to:
        return False, "no recipient after removing your own address"
    m = outlook.CreateItem(0)
    m.To = to
    if cc:
        m.CC = cc
    m.Subject = e["subject"]
    bd._attach_qr(m)
    m.HTMLBody = e.get("html") or e.get("body") or ""
    if not so.bind_account(m, acct):
        return False, "could not bind DHL account"
    m.Send()
    tracker.log(orders=e.get("orders", []), to=e["to"], name=e.get("name", ""),
                product_codes=e.get("product_codes", []), materials=e.get("materials", ""),
                site=e.get("site", ""), postcode=e.get("postcode", ""),
                delivery_date=e["date"], source=e.get("source", ""), status="sent",
                worksite=e.get("worksite", ""),
                collection_site=e.get("collection_site", ""),
                collection_pc=e.get("collection_pc", ""),
                collections=e.get("collections"))
    metrics.log("waitlist_released", orders=e.get("orders", []), to=e["to"])
    return True, "sent"


_LOCK_SOCK = None


def _release_lock():
    """Only ONE sending release at a time. The 3h timer (local agent) and a
    dashboard-clicked release (either agent) used to overlap and the same
    wait-list email went out twice (5033651 -> Darren, 17/07 09:19 x2)."""
    global _LOCK_SOCK
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8791))
    except OSError:
        return False
    _LOCK_SOCK = s
    return True


def release(send=False):
    if send and not _release_lock():
        print("release: another wait-list release is already running - skipping.")
        return {"sent": [], "skipped": [], "missed": [], "failed": []}
    ns = bd.get_ns()
    due = waitlist.due()
    over = waitlist.overdue()
    report = {"sent": [], "skipped": [], "missed": [], "failed": []}

    # re-check guards against the LIVE mailbox at send time
    done = bd._already_done_orders()
    all_orders = {str(o).strip() for e in due for o in e.get("orders", [])}
    already = bd.find_already_emailed(ns, all_orders)

    outlook = acct = None
    if send and due:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        acct = so.dhl_account(ns)
        if acct is None:
            print("ABORT: DHL account not found - nothing sent.")
            return report

    for e in due:
        ords = [str(o).strip() for o in e.get("orders", [])]
        label = f"{' / '.join(ords)} | {e['site']} {e['postcode']} | {e['date']}"
        if ords and all(o in done for o in ords):
            waitlist.mark(e["id"], "sent", note="already handled by tool before release")
            report["skipped"].append(label + "  (already done by tool)")
            continue
        if ords and all(o in already for o in ords):
            seen = {o: already[o] for o in ords if o in already}
            ev = next((v for v in seen.values() if v.get("booked")), next(iter(seen.values())))
            if ev.get("booked"):   # your in-thread reply - booked in
                refstr = f" {ev['ref']}" if ev.get("ref") else ""
                waitlist.mark(e["id"], "sent", note=f"you replied (booked in{refstr}) {ev['when']}")
                report["skipped"].append(label + f"  (you replied {ev['when']} - booked in{refstr})")
            else:
                waitlist.mark(e["id"], "sent", note=f"you emailed manually {ev['where']} {ev['when']}")
                report["skipped"].append(label + f"  (you emailed it {ev['where']} {ev['when']})")
            continue
        if not bd._is_future(e["date"]):
            waitlist.mark(e["id"], "missed", note="delivery date passed before release")
            report["missed"].append(label)
            continue
        if not send:
            report["sent"].append(label + "  (DRY RUN - would send)")
            continue
        try:
            ok, why = _send_one(outlook, acct, e)
            if ok:
                waitlist.mark(e["id"], "sent")
                report["sent"].append(label)
            else:
                report["failed"].append(label + f"  ({why})")
        except Exception as ex:
            report["failed"].append(label + f"  ({ex})")

    if send and report["sent"]:
        try:
            ns.SendAndReceive(False)
        except Exception:
            pass

    # overdue = a reliability failure: never send a past-date email, but SHOUT.
    for e in over:
        waitlist.mark(e["id"], "missed", note="was still waiting after delivery date")
        report["missed"].append(f"{' / '.join(e['orders'])} | {e['site']} {e['postcode']} | {e['date']}")

    return report


def main():
    send = len(sys.argv) > 1 and sys.argv[1].lower() == "send"
    r = release(send=send)
    mode = "SENDING" if send else "DRY RUN (pass 'send' to actually send)"
    print(f"Wait-list release - {mode} | lead {waitlist.LEAD_DAYS}d\n")
    for k, head in (("sent", "SENT" if send else "WOULD SEND"),
                    ("skipped", "SKIPPED (already handled)"),
                    ("failed", "FAILED - NEEDS ATTENTION"),
                    ("missed", "!! MISSED - delivery date passed while waiting (ACTION NEEDED)")):
        if r[k]:
            print(f"{head}:")
            for line in r[k]:
                print("   " + line)
            print()
    if not any(r.values()):
        print("Nothing due. Wait list is clear.")


if __name__ == "__main__":
    main()
