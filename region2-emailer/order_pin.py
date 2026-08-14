"""Search an order and put it on the map. Sends nothing, ever.

    python order_pin.py 5033691              SEARCH - what is this order? writes nothing
    python order_pin.py 5033691 pin          pin it on the map
    python order_pin.py 5033691 pin track    pin it AND track it (so it gets chased)

Why this exists: when you email a site yourself, the toolkit never sees it, so
the order is not on the map and not in the tracker. The existing "send one
order" flow would build the email and send it - which is exactly what you do
not want when you have already written to them by hand. This is that flow with
the sending cut off: the same lookup, the same extract row, the same details,
stopping at the map.

`pin` alone is map-only: you see it, nothing chases it.
`pin track` also enrols it in the tracker, so it is chased for delivery details
like any other order - dated from when YOU actually emailed them, which is read
out of Sent Items rather than assumed to be now.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_drafts as bd      # noqa: E402
import pins                    # noqa: E402
import send_order as so        # noqa: E402
import tracker                 # noqa: E402


def _tracked(orders):
    """The tracker record id already covering any of these orders, or ''."""
    want = {str(o).strip() for o in orders}
    for r in tracker.load().get("records", []):
        if want & {str(o).strip() for o in r.get("orders", [])}:
            return r.get("id", "?")
    return ""


def _fmt(e):
    coll = e.get("collections") or []
    where = ", ".join(f"{c.get('site','?')} {c.get('pc','')}".strip() for c in coll) or "-"
    return (f"  order(s)   : {' / '.join(e.get('orders', []))}\n"
            f"  site       : {e.get('site','?')}  {e.get('postcode','')}\n"
            f"  delivery   : {e.get('date','?')}\n"
            f"  materials  : {e.get('materials','?')}\n"
            f"  collection : {where}\n"
            f"  contact    : {e.get('name','')} <{e.get('to','')}>\n"
            f"  from       : {e.get('source','?')}")


def main():
    argv = [a.strip() for a in sys.argv[1:]]
    if not argv:
        print(__doc__)
        return 2
    order = argv[0]
    do_pin = any(a.lower() == "pin" for a in argv[1:])
    do_track = any(a.lower() == "track" for a in argv[1:])

    ns = bd.get_ns()
    collected, tokens, not_found = so.resolve_orders(ns, order)
    if not collected:
        # Deliberately no fallback hunt through Sent Items or the wait list: if
        # it is not in the extracts, say so plainly rather than half-inventing
        # an order from an email subject.
        #
        # But only say it when it has actually been proved. The whole-mailbox
        # scan is capped now, and a scan that ran out of time has proved
        # nothing - reporting that as "not in any extract" would be the same
        # false negative that sent 7115288 missing, just with a new cause.
        scan = so.LAST_SCAN
        miss = " ".join(not_found) or order
        if scan.get("cut_short"):
            print(f"NOT FINISHED: searched {scan['files']} spreadsheet(s) in "
                  f"{scan['seconds']}s without finding {miss}, and stopped there "
                  f"so the desk was not blocked any longer.")
            print("This does NOT mean the order is missing - the search was cut "
                  "short. Run it again to carry on, or check the order number.")
        else:
            print(f"NOT FOUND: {miss} is not in the order index or any extract "
                  f"in your mailbox"
                  + (f" ({scan['files']} spreadsheet(s) searched)."
                     if scan.get("files") else "."))
        print("Nothing pinned.")
        print("PIN_RESULT pinned=0")
        return 1

    emails = so.build_from_collected(collected)
    if not emails:
        print(f"NOT FOUND: {order} matched a file but no usable row. Nothing pinned.")
        print("PIN_RESULT pinned=0")
        return 1
    if len(emails) > 1:
        print(f"note: {order} resolves to {len(emails)} groups (different "
              f"recipients/sites) - pinning all of them.")

    # Did you actually email it? Sent Items is the only place that knows, and it
    # gives the real send time, so a tracked pin is chased from when YOU wrote
    # to them rather than from now.
    all_orders = sorted({o for e in emails for o in e.get("orders", [])})
    try:
        already = bd.find_already_emailed(ns, all_orders, limit=800)
    except Exception as ex:
        already = {}
        print(f"  (could not read Sent Items: {type(ex).__name__} - carrying on)")

    pinned = tracked = 0
    for e in emails:
        print("=" * 66)
        print(_fmt(e))
        hits = [already.get(o) for o in e.get("orders", []) if already.get(o)]
        sent = next((h for h in hits if h.get("where") == "Sent Items"), None)
        if sent:
            print(f"  emailed    : YES - {sent.get('where')} {sent.get('when')}"
                  + (f" (booked in{' ' + sent['ref'] if sent.get('ref') else ''})"
                     if sent.get("booked") else ""))
        else:
            print("  emailed    : no trace in Sent Items - are you sure you sent it?")

        # Already tracked? Then it is ALREADY on the map - the map plots tracker
        # records too. Pinning it as well would show one delivery as two pins in
        # the same place, which is worse than not pinning it at all.
        tracked_already = _tracked(e.get("orders", []))
        if tracked_already:
            print(f"  tracked    : ALREADY on the tracker as {tracked_already}"
                  " - it is on the map already, not pinning again.")
            continue

        # Booked in already? Then tracking it would hand a finished order back to
        # the chasers - the exact churn _booked_drops.json exists to stop. The
        # pin is still fine and often wanted (you still want to see the drop on
        # the map), so pin it and drop the tracking.
        booked = bool(sent and sent.get("booked"))
        if booked and do_track:
            print("  !! already BOOKED IN - pinning, but NOT tracking it:"
                  " a booked order must not go back to the chasers.")

        if not do_pin:
            continue

        rec = {
            "id": pins.make_id(e.get("orders", []), e.get("date")),
            "kind": "pinned",
            "orders": e.get("orders", []),
            "to": e.get("to", ""),
            "name": e.get("name", ""),
            "site": e.get("site", ""),
            "worksite": e.get("worksite", ""),
            "postcode": e.get("postcode", ""),
            "delivery_date": e.get("date", ""),
            "materials": e.get("materials", ""),
            "product_codes": e.get("product_codes", []),
            "collections": e.get("collections") or [],
            "collection_site": e.get("collection_site", ""),
            "collection_pc": e.get("collection_pc", ""),
            "source": e.get("source", ""),
            "emailed_at": (sent or {}).get("when", ""),
            "booked": booked,
            "tracked": bool(do_track and not booked),
            "pinned_at": tracker._now(),
        }
        pins.add(rec)
        pinned += 1
        print("  -> PINNED on the map"
              + (" and tracked" if (do_track and not booked) else " (map only)"))

        if do_track and not booked:
            tracked += 1
            # only_if_new: never bump the chase count of an order already tracked.
            tracker.log(orders=e.get("orders", []), to=e.get("to", ""),
                        name=e.get("name", ""), product_codes=e.get("product_codes", []),
                        materials=e.get("materials", ""), site=e.get("site", ""),
                        postcode=e.get("postcode", ""), delivery_date=e.get("date"),
                        source="by hand", status="sent",
                        emailed_at=(sent or {}).get("when") or None,
                        only_if_new=True,
                        worksite=e.get("worksite", ""),
                        collection_site=e.get("collection_site", ""),
                        collection_pc=e.get("collection_pc", ""),
                        collections=e.get("collections"))

    if not do_pin:
        print("\nSEARCH ONLY - nothing written. To put it on the map:")
        print(f"  python order_pin.py {order} pin          (map only)")
        print(f"  python order_pin.py {order} pin track    (map + chased)")
        print("PIN_RESULT pinned=0")
        return 0

    # Say what actually happened, not what was asked for: `track` can be
    # refused per order (already booked in), and a summary that claims it
    # tracked something it deliberately skipped is how you stop trusting the
    # output at all.
    note = ""
    if do_track:
        note = (f" Tracked {tracked}." if tracked
                else " Tracked none - see above.")
    print(f"\nPinned {pinned}.{note}")
    print(f"PIN_RESULT pinned={pinned} tracked={tracked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
