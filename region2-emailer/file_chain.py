"""
An order's email chain filed away once its CTMS update is done - his rule (30/10): "once you've updated an order,
just file away that email chain again ... we're just trying to make sure that the only relevant things in my inbox
are in my inbox."

Every mail of the site thread still in the DHL Inbox's TOP level goes to Inbox > Regions > Region 2 > Completed,
where he files finished threads. The thread is the conversation of the first email sent to the site (the tracker's
orig_entryid) - every reply in it, whoever sent it (a site colleague answering for the contact counts) - else, with
no first email to go by, the mails whose subject is our site email's, which starts with the order number. Either
way the order number must be in the subject. Never Sent Items, never a sub-folder, never deleted.

    python file_chain.py ORDER          a dry run: what would be filed
    python file_chain.py ORDER --move   files them
"""
import re
import sys
from datetime import datetime, timedelta

DEST = ("Inbox", "Regions", "Region 2", "Completed")
DAYS = 60                          # how far back the Inbox is read


def _sub(folder, name):
    for i in range(1, folder.Folders.Count + 1):
        f = folder.Folders.Item(i)
        if str(f.Name).lower() == name.lower():
            return f
    return None


def folder(root, path):
    f = root
    for name in path:
        f = _sub(f, name) if f is not None else None
    return f


def topic(subject):
    """A subject without its RE: / FW: prefixes, lower case - how the thread reads in every mail of it."""
    s = re.sub(r"^(?:\s*(?:re|fw|fwd)\s*:\s*)+", "", str(subject or ""), flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


def chain(inbox, order, conv_id="", thread="", now=None):
    """The top-level Inbox mails of an order's thread, newest first: (item, when, sender, subject)."""
    order = str(order).strip()
    since = (now or datetime.now()) - timedelta(days=DAYS)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    out = []
    for it in items:
        try:
            t = it.ReceivedTime
        except AttributeError:          # receipts and meeting notices carry no received time
            continue
        when = datetime(t.year, t.month, t.day, t.hour, t.minute)
        if when < since:
            break
        subj = str(getattr(it, "Subject", "") or "")
        if order not in subj:
            continue
        same = bool(conv_id) and str(getattr(it, "ConversationID", "") or "") == conv_id
        if same or (thread and topic(subj) == thread) or (not conv_id and not thread
                                                           and topic(subj).startswith(order + " ")):
            out.append((it, when, str(getattr(it, "SenderName", "") or ""), subj))
    return out


def file_chain(ns, rec, root=None, move=True):
    """File one tracker record's chain: [(when, sender, subject)] moved (or that would be, move=False). Raises
    when the Completed folder can't be found - nothing is moved then."""
    if root is None:
        import tracker
        root = tracker._dhl(ns)
    inbox, dest = folder(root, ("Inbox",)), folder(root, DEST)
    if inbox is None or dest is None:
        raise RuntimeError("Inbox > Regions > Region 2 > Completed isn't in the DHL mailbox - nothing filed")
    conv_id = thread = ""
    if rec.get("orig_entryid"):
        try:
            first = ns.GetItemFromID(rec["orig_entryid"])
            conv_id = str(getattr(first, "ConversationID", "") or "")
            thread = topic(getattr(first, "ConversationTopic", "") or getattr(first, "Subject", ""))
        except Exception:
            pass                        # moved or gone: the subject rule below decides
    done = []
    for o in rec.get("orders") or []:
        for it, when, who, subj in chain(inbox, o, conv_id, thread):
            if move:
                it.Move(dest)
            done.append((when, who, subj))
    return done


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-2].strip())
        return 2
    import json
    import os
    import build_drafts as bd
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "tracker.json"), encoding="utf-8") as f:
        recs = [r for r in json.load(f).get("records") or [] if argv[1] in (r.get("orders") or [])]
    rec = recs[0] if recs else {"orders": [argv[1]]}
    done = file_chain(bd.get_ns(), rec, move="--move" in argv)
    for when, who, subj in done:
        print(f"{when:%d/%m %H:%M} | {who} | {subj}")
    print(("Filed " if "--move" in argv else "Would file ") + f"{len(done)} to Region 2 > Completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
