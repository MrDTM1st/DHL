"""
His X on the CTMS page's to-do list (16/11): an order's reply that "isn't actually an email for details, but you don't
know that. I do. So I want to take it off the list. It happens sometimes ... And then when the actual one comes up,
then you have all the details."

  any item          off the list, never typed into CTMS - a note counts as written, so it never comes back
  a site's reply    that email wasn't their details: the order goes back to waiting for them. The reply check then
                    takes only mail that came in after the one it took (replies_after on the tracker record), so the
                    real answer goes on the list with its details when it comes, and that email never again. The
                    Night / Saturday / Sunday reminder the same reply left goes too. The chaser and the escalations
                    judge by the mailbox, where that email still reads as an answer - nothing is chased or escalated
                    because of the X.

The tracker is only edited under its lock, as phone_update does.

    python todo_dismiss.py ID         prints {"ok", "said", "tracker"} last
"""
import json
import sys
from datetime import datetime, timedelta

import ctms_todo
import tracker

LOCK_WAIT = 30
STAMP = "%Y-%m-%d %H:%M"


def after_dismissed(record, found):
    """The mail a reply check may take for an order. After his X said the email it took wasn't the site's details,
    only what came in after that one counts: the real answer is picked up when it comes, and the same email never
    again. The mark is to the minute, so the whole of that minute is behind it."""
    try:
        after = datetime.strptime(str(record.get("replies_after") or "")[:16], STAMP) + timedelta(seconds=59)
    except ValueError:
        return found

    def received(it):
        try:
            return datetime.fromtimestamp(it.ReceivedTime.timestamp())
        except Exception:
            return None
    return [it for it in found if (received(it) or after) > after]


def reopen(item, d, now):
    """The tracker records a reply's to-do item came from, back to waiting for the site's details -> [records]. One
    whose details came from his call is left alone: those are his."""
    orders = set(ctms_todo._bases(item.get("orders")))
    hit = [r for r in d.get("records") or [] if r.get("kind", "delivery") == "delivery" and r.get("reply_at")
           and not r.get("phoned_at") and orders & set(ctms_todo._bases(r.get("orders")))]
    for r in hit:
        r["replies_after"] = max(str(r.get("replies_after") or ""), str(r["reply_at"]))
        r["not_the_details"] = {"at": now, "reply_at": r["reply_at"], "what": item.get("what") or ""}
        for k in ("reply_at", "details", "missing", "details_note", "sendoff_ready"):
            r.pop(k, None)
    return hit


def dismiss(item_id, now=None, store=None, notes_done=None):
    """The item off the list (ctms_todo.dismiss) and, for one from a site's reply, its order waiting for the details
    again. The caller holds the tracker's lock. -> {"ok", "said", "tracker": whether the tracker changed}"""
    now = now or tracker._now()
    item = next((i for i in ctms_todo.listing(tracker.PATH, store, notes_done) if i["id"] == item_id), None)
    if item is None:
        return {"ok": False, "said": "That to-do item is no longer on the list - nothing changed.", "tracker": False}
    reopened = []
    if item["kind"] == "update" and item.get("source") == "reply":
        d = tracker.load()
        reopened = reopen(item, d, now)
        if reopened:
            tracker.save(d)
    gone = ctms_todo.dismiss(item_id, path=store, tracker_path=tracker.PATH, notes_done=notes_done, when=now)
    said = (f"{' / '.join(item.get('orders') or [])}: \"{item.get('what')}\" is off the CTMS to-do list - nothing is "
            "typed into CTMS for it")
    if len(gone) > 1:
        said += ", nor for the Night / weekend reminder the same reply left"
    if reopened:
        said += (". The order waits for its details again: that email won't be read as their answer again, and the "
                 "next one from the site goes on the list with its details")
    return {"ok": True, "said": said + ".", "tracker": bool(reopened)}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    import outlook_gate as gate
    if gate.named_lock("phase2_tracker", wait=LOCK_WAIT) is None:      # a reply check or chase holds the tracker
        out = {"ok": False, "said": "Not taken off - the reply check is updating the tracker; press the X again in a "
                                   "minute.", "tracker": False}
    else:
        out = dismiss(argv[1])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
