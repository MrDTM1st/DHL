"""The map's booked-in check: take a job off once the manifest comes back.

    python adhoc_booked_sweep.py           DRY RUN - what it would remove
    python adhoc_booked_sweep.py apply     remove them

Covers everything the map screen lists: ad hocs, by-hand pins AND tracker
deliveries. It used to read the ad hocs and the pins only, which is 8 of the 21
rows on that list, so "check whether these are booked" could not answer for the
other 13 however long you stared at it - and the answer for a tracker delivery
is in exactly the same place, the manifest number in its own thread.

A job sits on the map until someone presses "Booked - remove from the map".
But the moment it is actually booked is already in the mailbox: the haulier
replies in the thread with a manifest number - "it's for this current run:
260804-man-01567080" - or you reply with one yourself after booking by phone.
MAN *is* the manifest reference, so that number arriving IS the confirmation.

Two rules keep it honest, both learned from real mail in this mailbox:

  * the reference must be in the SUBJECT. Ad hoc threads keep the AH ref in
    the subject line throughout, and matching on the body instead would let
    one thread book a different job that happened to be mentioned in it.

  * the manifest number must be in the text ABOVE the quoted original
    (build_drafts._reply_top). A "gary harbinson reacted to your message"
    notification quotes the whole thread underneath, manifest number and all -
    matching the raw body would have booked AH7/8/26G2CH off the back of a
    thumbs-up.

Removals are remembered in _booked_drops.json, so a later reprocess of the same
form cannot put a booked job back on the map.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_drafts as bd      # noqa: E402
import tracker                 # noqa: E402

ADHOCS = os.path.join(HERE, "_adhocs.json")
LOG = os.path.join(HERE, "_adhoc_booked.json")     # what was removed and why
DAYS = 30
# A backstop, not the window. This was 150, and the loop counted items BEFORE
# checking the date, so whichever limit bit first won: on a live Inbox 150 items
# is a couple of days, not thirty. The jobs that linger on the map are precisely
# the old ones, whose confirmation sits far below item 150 - so the sweep could
# never see the mail that would have cleared them. Outlook does the date filter
# now (find_bookings), and this only stops a runaway folder.
PER_FOLDER = 2000
FOLDERS = ("ADHOC", "Inbox", "Sent Items")


def _load_adhocs():
    try:
        with open(ADHOCS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _load_pins():
    """By-hand pins are jobs too, and they get booked in exactly the same way.

    The sweep only ever read _adhocs.json, so a pinned order stayed on the map
    however long ago it was booked - five of them had built up, every one with a
    MAN reference sitting in Sent Items, the oldest a week past its delivery
    date. Nothing was going to take them off: pins have no 30-minute sweep of
    their own and, until today, no working button either.
    """
    try:
        import pins
        return pins.load()
    except Exception:
        return []


def _load_tracker():
    """Tracker deliveries are on the map list too, and they get booked by phone
    exactly like the rest. Left out, the check answered for 8 rows of 21."""
    try:
        import tracker
        return [r for r in (tracker.load().get("records") or []) if r.get("orders")]
    except Exception:
        return []


def self_booked(rec):
    """The record already says so. order_pin sets booked=True when it proves a
    manifest in Sent Items at pin time, then pins the job map-only so nothing
    chases it - and the sweep used to ignore that flag and re-derive the answer
    from mail that may have scrolled out of the window, so 6055488 sat on the
    map with its own record saying booked."""
    return rec.get("booked") is True


def _folders(ns):
    dhl = bd.dhl_store(ns)
    if dhl is None:
        return []
    out = []
    for name in FOLDERS:
        f = bd.sub(dhl, name)
        if f is not None:
            out.append(f)
    inbox = bd.sub(dhl, "Inbox")
    if inbox is not None:                    # ADHOC is often filed under Inbox
        for i in range(1, inbox.Folders.Count + 1):
            try:
                c = inbox.Folders.Item(i)
                if c.Name.strip().lower() in ("adhoc", "ad hoc", "ad hocs"):
                    out.append(c)
            except Exception:
                continue
    return out


def find_bookings(ns, refs, days=DAYS):
    """{ref: {"man","when","who","subject"}} for every ad hoc now booked in."""
    wanted = {str(r).strip() for r in refs if str(r).strip()}
    if not wanted:
        return {}
    cutoff = datetime.now() - timedelta(days=days)
    booked = {}
    # Outlook does the date filter, in ISO via DASL so it does not depend on the
    # machine's date format. The item cap below is only a runaway guard now.
    flt = ('@SQL="urn:schemas:httpmail:datereceived" >= \''
           + cutoff.strftime("%Y-%m-%d %H:%M") + "'")
    for folder in _folders(ns):
        try:
            items = folder.Items.Restrict(flt)
            items.Sort("[ReceivedTime]", True)
        except Exception:
            try:                                  # a store that refuses the
                items = folder.Items              # restrict still gets swept
                items.Sort("[ReceivedTime]", True)
            except Exception:
                continue
        n = 0
        for it in items:
            n += 1
            if n > PER_FOLDER:
                break
            try:
                when = it.ReceivedTime.replace(tzinfo=None)
                if when < cutoff:
                    break
                subj = str(it.Subject or "")
            except Exception:
                continue
            hits = [r for r in wanted if r in subj]
            if not hits:
                continue
            try:
                body = str(getattr(it, "Body", "") or "")
            except Exception:
                continue
            top = bd._reply_top(body)
            m = bd._MAN_RE.search(top)
            if not (m or any(p in top for p in bd._BOOKED_PHRASES)):
                continue
            man = m.group(0).upper().replace(" ", "-") if m else ""
            for r in hits:
                # keep the EARLIEST confirmation, not whichever we saw last
                prev = booked.get(r)
                if prev and prev["when"] <= when.strftime("%d/%m/%Y %H:%M"):
                    continue
                booked[r] = {
                    "man": man,
                    "when": when.strftime("%d/%m/%Y %H:%M"),
                    "who": str(getattr(it, "SenderName", "") or ""),
                    "folder": folder.Name,
                    "subject": subj[:90],
                }
    return booked


def reason(rec, booked):
    """(ref, why) if this job is booked, else (None, None).

    Two ways of knowing, and the second one used to be thrown away: the mailbox
    says so, or the record itself already says so.
    """
    refs = [str(o).strip() for o in rec.get("orders", []) if str(o).strip()]
    for r in refs:
        if r in booked:
            return r, booked[r]
    if self_booked(rec):
        return (refs[0] if refs else str(rec.get("id", "?"))), {
            "man": "", "when": "", "who": "recorded as booked when it was pinned",
            "folder": "", "subject": ""}
    return None, None


def main():
    apply = "apply" in [a.strip().lower() for a in sys.argv[1:]]
    recs = _load_adhocs()
    pinned = _load_pins()
    tracked = _load_tracker()
    if not recs and not pinned and not tracked:
        print("Nothing on the map.")
        print("SWEEP_RESULT removed=0")
        return 0

    refs = []
    for r in recs + pinned + tracked:
        refs += [str(o).strip() for o in r.get("orders", []) if str(o).strip()]
    print(f"Checking {len(recs)} ad hoc(s), {len(pinned)} pin(s) and "
          f"{len(tracked)} tracker delivery(ies) against the mailbox...\n")

    booked = find_bookings(bd.get_ns(), refs)
    hit = [r for r in recs if reason(r, booked)[0]]
    hit_pins = [r for r in pinned if reason(r, booked)[0]]
    hit_track = [r for r in tracked if reason(r, booked)[0]]
    if not hit and not hit_pins and not hit_track:
        print("  none of them have a manifest yet - nothing to remove.")
        print("SWEEP_RESULT removed=0")
        return 0

    for r in hit + hit_pins + hit_track:
        ref, b = reason(r, booked)
        kind = ("pin" if r in hit_pins
                else "tracker" if r in hit_track
                else r.get("kind", "adhoc"))
        print(f"  {'REMOVE' if apply else 'would remove'}  {ref}  [{kind}]")
        print(f"      {r.get('collection_site','?')} -> {r.get('site','?')}"
              f"  ({r.get('delivery_date','?')})")
        print(f"      manifest {b['man'] or '(booking phrase)'}"
              f" · {b['when'] or 'already on the record'}"
              f" · {b['who'] or '?'} · [{b['folder'] or 'the record itself'}]")

    if not apply:
        print(f"\nDRY RUN - nothing removed. Add 'apply' to take these "
              f"{len(hit) + len(hit_pins) + len(hit_track)} off the map.")
        print("SWEEP_RESULT removed=0")
        return 0

    if hit_pins:
        try:
            import pins
            gone = {r["id"] for r in hit_pins}
            pins.save([p for p in pins.load() if p.get("id") not in gone])
        except Exception as ex:
            print(f"  (could not remove the pins: {ex})")

    # Re-read the ad hocs RIGHT BEFORE writing, and remove only the ids found
    # booked. `recs` was loaded before the mailbox scan, which takes seconds,
    # and writing `recs` back minus the booked ones deleted anything added in
    # between - a form processed during the scan vanished from the map without
    # a word. The cloud agent processes dropped forms while the local agent
    # runs this sweep, so the two genuinely overlap, and once the sweep went
    # from every 30 minutes to every 5 the window stopped being rare.
    booked_ids = {r["id"] for r in hit}
    left = [r for r in _load_adhocs() if r.get("id") not in booked_ids]
    # The temp file carries this process's pid. Two agents run on this PC
    # against the same mailbox - the local one on its 5-minute timer, the cloud
    # one when the map's button is pressed - and with a single fixed ".tmp" the
    # loser of that race raises at os.replace AFTER the pins have already been
    # deleted and BEFORE the removal log is written: a job vanishing with no
    # record of why, which is the thing this script exists to avoid.
    tmp = f"{ADHOCS}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(left, f, indent=1)
    os.replace(tmp, ADHOCS)

    for r in hit_track:                      # tracker deliveries: drop by id
        try:
            import tracker as _tracker
            _tracker.book(r.get("id"))
        except Exception as ex:
            print(f"  (could not drop tracker record {r.get('id')}: {ex})")

    # Remember them, so reprocessing the same form can never put a booked job
    # back on the map - the same guard the tracker's enrol sweeps rely on.
    dropped = []
    for r in hit + hit_pins + hit_track:
        dropped += [str(o).strip() for o in r.get("orders", [])]
    try:
        tracker.remember_drops(dropped)
    except Exception:
        pass

    # Keep a record of what vanished and why: a pin disappearing from the map
    # with no explanation is worse than one that lingers.
    try:
        old = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else []
    except Exception:
        old = []
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for r in hit + hit_pins + hit_track:
        # reason(), not booked[ref] - a record removed on its own booked flag
        # has no mailbox entry, and looking one up raised StopIteration.
        ref, b = reason(r, booked)
        old.insert(0, {"ref": ref, "removed_at": stamp, **b,
                       "site": r.get("site", ""), "csv": r.get("csv", "")})
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(old[:120], f, indent=1)

    n = len(hit) + len(hit_pins) + len(hit_track)
    print(f"\nRemoved {n} from the map ({len(hit)} ad hoc, {len(hit_pins)} pin, "
          f"{len(hit_track)} tracker). {len(left)} ad hoc(s) left.")
    print(f"SWEEP_RESULT removed={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
