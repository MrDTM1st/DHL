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
import os
import sys
from datetime import datetime, timedelta

import build_drafts as bd
import metrics
import send_order as so
import tracker, waitlist

# The agent runs `waitlist_release.py send` every 3 hours with no switch of its
# own, so this file is the off switch: while it exists nothing is sent. A dry
# run still shows what is due. Delete it to resume.
PAUSE_FLAG = os.path.join(bd.HERE, "waitlist_release.paused")


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
                collections=e.get("collections"),
                po=e.get("po"))
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


def _held_since(e):
    try:
        return datetime.strptime(e.get("added_at") or "", "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.now() - timedelta(days=60)


def _window(e, every):
    """Since when to look for contact about this delivery: the earliest hold of
    ANY entry (waiting or closed) for the same date sharing an order with it,
    because a re-extract starts a new entry with a fresh added_at while the
    contact went to the old one. Capped like the chaser's lookback."""
    import chase_guard as guard
    ords = set(e.get("orders", []))
    starts = [_held_since(x) for x in every
              if ords & set(x.get("orders", [])) and x.get("date") == e.get("date")] or [_held_since(e)]
    floor = datetime.now() - timedelta(days=guard.MAX_LOOKBACK_DAYS)
    return max(min(starts) - timedelta(days=1), floor)


def _internal_domains():
    import json
    import chase_guard as guard
    try:
        return tuple(json.load(open(guard.TEAM, encoding="utf-8")).get("internal_domains")
                     or ("dhl.com",))
    except Exception:
        return ("dhl.com",)


def _contact_check(ns, entries):
    """{entry id: ("contacted", why) | ("hold", why)} for due entries the mailbox
    says should not just be sent. Sent Items alone misses colleagues: on 23/10
    a colleague emailed seven held sites from their own mailbox, copying the
    planner, and the release would have asked all seven again.

    contacted - the planner or a colleague emailed the held contact naming EVERY
                order on the entry (closed, not sent).
    hold      - only some orders were covered, the site itself wrote about it,
                or an email that might settle it could not be read (not sent,
                not closed - looked at again next run, and reported).
    Raises if the mailbox can't be read fully or isn't syncing, so a send run
    stops rather than guess."""
    import chase_guard as guard
    from modules import chase_rules as cr
    if not entries:
        return {}
    every = waitlist.load().get("entries", [])
    wins = {e["id"]: _window(e, every) for e in entries}
    idx = guard.MailIndex(ns, min(wins.values()))
    if idx.errors:
        raise RuntimeError("; ".join(idx.errors[:3]))
    if len(idx.item_errors) > 5:
        raise RuntimeError(f"{len(idx.item_errors)} emails could not be read")
    # the "no new mail for 3h" test only means something in working hours;
    # the release also runs in the evening, when a quiet inbox is normal
    now = datetime.now()
    ok, why = guard.mailbox_fresh(ns, idx, now if cr.in_working_hours(now) else now.replace(hour=0))
    if not ok:
        raise RuntimeError(why)
    internal = _internal_domains()
    me = guard._me()

    def ours(addr):
        dom = cr.domain(addr)
        return addr in me or any(dom == d or dom.endswith("." + d) for d in internal)

    mails = sorted((m for m in idx.mails if not m.get("draft") and not m.get("ndr")),
                   key=lambda m: m["at"])
    rcpt = {}

    def to_contact(m, who):
        """Was this mail addressed to the contact? The index has recipients only
        for the planner's own mail; for a colleague's, copying him, read them. Site
        addresses are plain SMTP; an "/o=..." one is looked up only when no
        plain address matched. None = could not be read."""
        if m["dir"] == "out":
            return bool(who & (set(m["to"]) | set(m["cc"])))
        if m["eid"] not in rcpt:
            try:
                rs = ns.GetItemFromID(m["eid"], idx.store_id).Recipients
                got, x500 = set(), []
                for k in range(1, rs.Count + 1):
                    r = rs.Item(k)
                    a = str(r.Address or "").lower().strip()
                    if a.startswith("/"):
                        x500.append(r)
                    else:
                        got.add(a)
                if not who & got:
                    for r in x500:
                        try:
                            got.add(str(r.AddressEntry.GetExchangeUser().PrimarySmtpAddress).lower())
                        except Exception:
                            pass            # a list or a contact card - never the held site
                rcpt[m["eid"]] = got
            except Exception:
                rcpt[m["eid"]] = None
        got = rcpt[m["eid"]]
        return None if got is None else bool(who & got)

    def say(m):
        return f"{m['at']:%d/%m/%Y %H:%M} by {m['from']}: {m['subject'][:60]}"

    out = {}
    for e in entries:
        who = set(cr.emails_in(e.get("to")))
        ords = [str(o).strip() for o in e.get("orders", []) if str(o).strip()]
        if not who or not ords:
            continue
        covered, ev, site, unread = set(), None, None, []
        for m in mails:
            if m["at"] < wins[e["id"]]:
                continue
            if m["from"] in who:                         # the site writing in
                if cr.mentions(m["subject"] + " " + (idx.text_of(m["eid"]) or ""), ords):
                    site = site or m
                continue
            if not (m["dir"] == "out" or ours(m["from"])):
                continue
            # addressed to the contact first: an unreadable email to someone
            # else must not hold every entry
            hit = to_contact(m, who)
            if hit is False:
                continue
            body = idx.text_of(m["eid"])
            if body is None or hit is None:
                if body is None or cr.mentions(m["subject"] + " " + body, ords):
                    unread.append(m)
                continue
            # what was typed, not the quoted thread: "I'll be in touch nearer
            # the time" under the site's own list of orders is not the ask
            named = {o for o in ords if cr.mentions(m["subject"], [o])
                     or cr.mentions(cr.own_text(body), [o])}
            if named:
                covered |= named
                ev = ev or m
        if covered >= set(ords):
            out[e["id"]] = ("contacted", "already emailed " + say(ev))
        elif covered:
            out[e["id"]] = ("hold", f"only {', '.join(sorted(covered))} emailed, "
                                    f"{say(ev)} - check the rest")
        elif site:
            out[e["id"]] = ("hold", "the site wrote about it " + say(site) + " - check before asking")
        elif unread:
            out[e["id"]] = ("hold", f"could not read {say(unread[0])}"
                                    + (f" (+{len(unread) - 1} more)" if len(unread) > 1 else "")
                                    + " - it may cover this; trying again next run")
    return out


def _overlapping(due, waiting):
    """{entry id: [other ids]} - the same delivery on the list more than once.
    The order set grows between extracts (orders A-B, then A-B-C, then A-C,
    all to the same site contact for 10/11), and sending each would ask the
    site three times."""
    out = {}
    for a in due:
        others = [b["id"] for b in waiting
                  if b["id"] != a["id"] and b.get("date") == a.get("date")
                  and set(a.get("orders", [])) & set(b.get("orders", []))]
        if others:
            out[a["id"]] = others
    return out


def _tracked_dates():
    """order -> the delivery dates the tracker has it emailed for."""
    out = {}
    for r in tracker.load().get("records", []):
        for o in r.get("orders", []):
            out.setdefault(str(o).strip(), set()).add(str(r.get("delivery_date") or "").strip())
    return out


def _timer_run():
    """Run by the agent's 3-hourly timer, not a press of Send on the dashboard: the timer runs every background job
    with R2_PHASE2_WAIT=0."""
    return os.environ.get("R2_PHASE2_WAIT") == "0"


def _working_hours(now=None):
    """Mon-Fri 08:00-16:30, bank holidays out - the hours the chasers keep, too."""
    from modules import chase_rules as cr
    from services import BANK_HOLIDAYS
    hol = {datetime.strptime(h, "%Y-%m-%d").date() for h in BANK_HOLIDAYS}
    return cr.in_working_hours(now or datetime.now(), hol)


def release(send=False):
    report = {"sent": [], "skipped": [], "held": [], "missed": [], "failed": [], "no_address": []}
    if send and _timer_run() and not _working_hours():
        # the lead time went from 2 weeks to 3 on a Sunday night (01/11): the timer must not mail a whole new
        # week's sites at 3am - due entries go on its first run in working hours; Send on the dashboard still sends
        print("release: outside working hours - due entries wait for the first run on a working day after 08:00.")
        return report
    if send and not _release_lock():
        print("release: another wait-list release is already running - skipping.")
        return report
    ns = bd.get_ns()
    due = waitlist.due_or_stuck()
    over = waitlist.overdue()

    # A dry run only reports. It used to close entries as it went, so a look
    # on 26/10 marked nine held orders "sent" with nothing sent.
    def mark(entry_id, status, note):
        if send:
            waitlist.mark(entry_id, status, note=note)

    def label_of(e):
        return f"{' / '.join(e['orders'])} | {e['site']} {e['postcode']} | {e['date']}"

    # re-check guards against the LIVE mailbox at send time
    done = bd._already_done_orders()
    dates = _tracked_dates()
    all_orders = {str(o).strip() for e in due for o in e.get("orders", [])}
    already = bd.find_already_emailed(ns, all_orders)
    overlap = _overlapping(due, waitlist.waiting())
    every = waitlist.load().get("entries", [])

    def other_dates(e):
        """Other delivery dates these orders are on (wait list, any status, or
        tracker). Evidence found for one date must not close another: an order
        held for 10/11 and 24/11 would have had 24/11 closed unsent by 10/11's
        ask or booking (another order went that way on 02/10)."""
        ords = set(e.get("orders", []))
        ds = {x.get("date") for x in every if ords & set(x.get("orders", []))}
        ds |= {d for o in ords for d in dates.get(o, ())}
        return sorted(d for d in ds if d and d != e.get("date"))

    todo, mine = [], {}
    for e in due:
        ords = [str(o).strip() for o in e.get("orders", [])]
        label = label_of(e)
        also = other_dates(e)
        if ords and all(o in done for o in ords):
            if all(e["date"] in dates.get(o, ()) for o in ords):
                mark(e["id"], "sent", "already handled by tool before release")
                report["skipped"].append(label + "  (already done by tool)")
            else:
                # an order on the list for 10/11 and 24/11: once 10/11 went,
                # this closed 24/11 unsent
                other = sorted({d for o in ords for d in dates.get(o, ())} - {e["date"]})
                report["held"].append(label + f"  (the tool emailed it for {', '.join(other)} - "
                                              "a second delivery, or moved? check)")
            continue
        if ords and all(o in already for o in ords):
            seen = {o: already[o] for o in ords if o in already}
            ev = next((v for v in seen.values() if v.get("booked")), next(iter(seen.values())))
            if ev.get("booked") and not also:   # your in-thread reply - booked in
                refstr = f" {ev['ref']}" if ev.get("ref") else ""
                mark(e["id"], "sent", f"you replied (booked in{refstr}) {ev['when']}")
                report["skipped"].append(label + f"  (you replied {ev['when']} - booked in{refstr})")
                continue
            # Anything else in Sent/Drafts naming the orders - to a haulier, a
            # supplier, someone other than the held contact, or a draft - no
            # longer closes the entry. The whole-mailbox check below closes it
            # if the held contact was emailed; if not, it is held for a look.
            mine[e["id"]] = ev
        if not bd._is_future(e["date"]):
            mark(e["id"], "missed", "delivery date passed before release")
            report["missed"].append(label)
            continue
        if not waitlist.has_address(e.get("to")):       # shown on the dashboard until the right address is given
            report["no_address"].append(label)
            continue
        if e["id"] in overlap:
            report["held"].append(label + f"  (also on the wait list as {', '.join(overlap[e['id']])}"
                                          " - close the ones that are out of date)")
            continue
        todo.append(e)

    # the whole mailbox, only for what is still going to send
    try:
        checked = _contact_check(ns, todo)
    except Exception as ex:
        for e in todo:
            report["failed"].append(label_of(e) + "  (not sent - could not check the whole "
                                                  f"mailbox for colleagues' emails: {ex})")
        todo, checked = [], {}

    outlook = acct = None
    if send and todo:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        acct = so.dhl_account(ns)
        if acct is None:
            for e in todo:
                report["failed"].append(label_of(e) + "  (DHL account not found - not sent)")
            todo = []

    sent_orders = set()
    for e in todo:
        label = label_of(e)
        verdict = checked.get(e["id"])
        also = other_dates(e)
        if verdict and verdict[0] == "contacted" and not also:
            mark(e["id"], "sent", verdict[1])
            report["skipped"].append(label + f"  ({verdict[1]})")
            continue
        if verdict and verdict[0] == "contacted":
            report["held"].append(label + f"  ({verdict[1]} - but it is also on the list for "
                                          f"{', '.join(also)}: is that email for this delivery? check)")
            continue
        if verdict:
            report["held"].append(label + f"  ({verdict[1]})")
            continue
        if e["id"] in mine:
            ev = mine[e["id"]]
            report["held"].append(label + f"  (you emailed {ev.get('to') or 'someone'} about it, "
                                          f"{ev['where']} {ev['when']} - not {e.get('to')}; "
                                          "send or close?)")
            continue
        if sent_orders & set(e.get("orders", [])):
            report["held"].append(label + "  (its orders were just emailed for another date - check)")
            continue
        if not send:
            report["sent"].append(label + "  (DRY RUN - would send)")
            continue
        try:
            ok, why = _send_one(outlook, acct, e)
            if ok:
                waitlist.mark(e["id"], "sent")
                report["sent"].append(label)
                sent_orders |= set(e.get("orders", []))
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
        mark(e["id"], "missed", "was still waiting after delivery date")
        report["missed"].append(label_of(e))

    return report


def main():
    send = len(sys.argv) > 1 and sys.argv[1].lower() == "send"
    if send and os.path.exists(PAUSE_FLAG):
        print("Wait-list release - PAUSED (waitlist_release.paused). Nothing sent.")
        return
    r = release(send=send)
    mode = "SENDING" if send else "DRY RUN (pass 'send' to actually send)"
    print(f"Wait-list release - {mode} | lead {waitlist.LEAD_DAYS}d\n")
    for k, head in (("sent", "SENT" if send else "WOULD SEND"),
                    ("skipped", "SKIPPED (already handled)"),
                    ("held", "HELD - not sent, failed a safety check (needs you)"),
                    ("failed", "FAILED - NEEDS ATTENTION"),
                    ("no_address", "NO ADDRESS TO EMAIL - on the dashboard until it is given"),
                    ("missed", "!! MISSED - delivery date passed while waiting (ACTION NEEDED)")):
        if r.get(k):
            print(f"{head}:")
            for line in r[k]:
                print("   " + line)
            print()
    if not any(r.values()):
        print("Nothing due. Wait list is clear.")


if __name__ == "__main__":
    main()
