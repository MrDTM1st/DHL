"""
CTMS notes owed - the contact trail that goes into CTMS after the toolkit emails a site.

Every site email the toolkit sends (tracker status 'sent') owes CTMS a note at the END of
the order's Special Instructions - on its -1-1 line only, his rule (29/10):

    " - Emailed DO 28/10"    the first email, dated the day it went
    " - Chased DO 30/10"     a chase, dated the day it went

This works out which notes are owed - from the tracker, less the ones already written
(ctms_notes_done.json, gitignored) - for the CTMS run to work through, and records each one
the run has saved. The run checks Special Instructions before adding anything, so a note
he wrote by hand is never doubled.

    python ctms_notes.py                    the notes owed, oldest first
    python ctms_notes.py done REF "NOTE"    mark one written (the run does this after each save)
    python ctms_notes.py skip REF "NOTE" WHY  it is not owed after all (order already scheduled/booked)

Reads the tracker; never writes it.
"""
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DONE = os.path.join(HERE, "ctms_notes_done.json")
INITIALS = "DO"


def _ddmm(when):
    """'2026-10-28' or '2026-10-28 14:05' -> '28/10'; '' if it is not a date."""
    try:
        return datetime.strptime(str(when or "")[:10], "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return ""


def first_line(order):
    """The CTMS line a note goes on - the order's -1-1, never every line: '1234567' -> '1234567-1-1'."""
    return str(order).split("-")[0].strip() + "-1-1"


def owed(records, done=(), initials=INITIALS):
    """[{ref, order, note, kind, date}] still to write, oldest first - one per order per contact."""
    written = {(d.get("ref"), d.get("note")) for d in done}
    out, seen = [], set()
    for r in records:
        if r.get("status") != "sent" or r.get("kind", "delivery") != "delivery":
            continue                    # drafts have not gone; collection requests are not site emails
        contacts = []
        if _ddmm(r.get("emailed_at")):
            contacts.append(("emailed", str(r["emailed_at"])[:10], f" - Emailed {initials} {_ddmm(r['emailed_at'])}"))
        chased = r.get("last_chased_at") or r.get("last_emailed_at")
        if r.get("chases") and _ddmm(chased):
            contacts.append(("chased", str(chased)[:10], f" - Chased {initials} {_ddmm(chased)}"))
        orders = dict.fromkeys(str(o).split("-")[0].strip() for o in r.get("orders") or [] if str(o).strip())
        for order in orders:
            ref = first_line(order)
            for kind, day, note in contacts:
                if (ref, note) in written or (ref, note) in seen:
                    continue
                seen.add((ref, note))
                out.append({"ref": ref, "order": order, "note": note, "kind": kind, "date": day})
    out.sort(key=lambda n: (n["date"], n["ref"], n["kind"] != "emailed"))
    return out


def load_done(path=None):
    try:
        with open(path or DONE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _remember(ref, note, path, extra):
    """Take a note off the owed list - written, or skipped. Matched by (ref, note)."""
    path = path or DONE
    done = load_done(path)
    if not any(d.get("ref") == ref and d.get("note") == note for d in done):
        done.append(dict(ref=ref, note=note, at=datetime.now().isoformat(timespec="seconds"), **extra))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(done[-2000:], f, indent=1)
        os.replace(tmp, path)
    return done


def mark_done(ref, note, path=None):
    """Record a note as written in CTMS - the run calls this after each save."""
    return _remember(ref, note, path, {})


def mark_skip(ref, note, why="", path=None):
    """Take a note off the owed list without writing it - the order is already
    scheduled on a trip (booked and dealt with), so the note is not owed."""
    return _remember(ref, note, path, {"skipped": why or "already scheduled"})


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="ctms_notes.py", description="CTMS notes owed after site emails.")
    ap.add_argument("--tracker", help="the tracker file to read (default: the toolkit's own)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("done", help="mark a note written in CTMS")
    p.add_argument("ref")
    p.add_argument("note")
    p = sub.add_parser("skip", help="the note is not owed (order already scheduled/booked)")
    p.add_argument("ref")
    p.add_argument("note")
    p.add_argument("why", nargs="?", default="already scheduled")
    a = ap.parse_args(argv)
    if a.cmd == "done":
        mark_done(a.ref, a.note)
        print(f"Marked written: {a.ref} '{a.note}'")
        return 0
    if a.cmd == "skip":
        mark_skip(a.ref, a.note, a.why)
        print(f"Skipped (not owed): {a.ref} '{a.note}' - {a.why}")
        return 0
    if a.tracker:
        with open(a.tracker, encoding="utf-8") as f:
            records = json.load(f).get("records", [])
    else:
        import tracker
        records = tracker.load().get("records", [])
    notes = owed(records, load_done())
    if not notes:
        print("No CTMS notes owed - every emailed order has its note.")
        return 0
    print(f"{len(notes)} CTMS note(s) owed - each at the END of Special Instructions, on the -1-1 line:")
    for n in notes:
        print(f"  {n['ref']:14} '{n['note']}'   ({n['kind']} {n['date']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
