"""Stand down the hauliers who did not get the job.

A ring-round asks a dozen hauliers to cover one delivery. One of them gets
it and the other eleven are left holding a job that no longer exists. Some
have quoted, some are part way through an abnormal load notification, and
every one of them will chase. Doing it by hand means opening eleven threads
and writing eleven near-identical emails, so in practice it does not get
done and the goodwill goes with it.

haulier_asks already knows exactly who was asked. This works out who came
back, replies inside their own thread where they did, and sends a plain
note where they did not: thanking the ones who took the time, telling the
rest to stop.

Nothing is tracker-enrolled. The tracker chases DELIVERY contacts for
missing details; a haulier told to stand down must never be chased as if
they were the customer - the same reason send_haulier is not logged.

Dry by default. Nothing leaves the mailbox without "send".
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

import build_drafts as bd
import haulier_asks

HERE = os.path.dirname(os.path.abspath(__file__))
NOTES = os.path.join(HERE, "_stand_down_notes.json")

# Mailbox display names that are a department, not a person. Greeting one of
# these by "name" reads as a mailmerge, which is exactly what this is trying
# not to look like.
_ROLES = {"transport", "traffic", "haulage", "accounts", "sales", "info",
          "general haulage", "operations", "office", "planning", "bookings"}


def _first_name(display):
    """A first name to greet, or "" when the sender is a department."""
    d = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", str(display or "")).strip()
    d = re.split(r"\s+-\s+|\s*\|\s*", d)[0].strip()
    if not d or d.lower() in _ROLES or "@" in d:
        return ""
    parts = [p for p in d.split() if p]
    if len(parts) < 2:
        return ""
    first = parts[0]
    if first.lower() in _ROLES or not first[:1].isalpha():
        return ""
    return first


def _domain(addr):
    a = str(addr or "").lower()
    return a.split("@")[-1].strip(" '\"<>") if "@" in a else ""


def sender_of(m):
    try:
        a = m.Sender.GetExchangeUser().PrimarySmtpAddress
    except Exception:
        a = ""
    return str(a or getattr(m, "SenderEmailAddress", "") or "").lower()


def replies(ns, order, asked, days=10):
    """{email_asked: {name, addr, when, entry, body}} for everyone who came back.

    Matched on DOMAIN as well as address: Allelys were asked at heavyhaulage@
    and answered from generalhaulage@, and an exact-address match would have
    filed a company that replied within minutes as silent.
    """
    dhl = bd.dhl_store(ns)
    if dhl is None:
        return {}
    want = str(order).upper().replace(" ", "")
    by_dom = {}
    for a in asked:
        by_dom.setdefault(_domain(a["email"]), a["email"])

    def walk(f):
        yield f
        try:
            for i in range(1, f.Folders.Count + 1):
                yield from walk(f.Folders.Item(i))
        except Exception:
            pass

    cut = datetime.now() - timedelta(days=days)
    out = {}
    for fold in walk(bd.sub(dhl, "Inbox")):
        try:
            its = fold.Items
            its.Sort("[ReceivedTime]", True)
        except Exception:
            continue
        for i in range(1, min(its.Count, 150) + 1):
            try:
                m = its.Item(i)
                when = m.ReceivedTime.replace(tzinfo=None)
            except Exception:
                continue
            if when < cut:
                break
            if want not in str(getattr(m, "Subject", "") or "").upper().replace(" ", ""):
                continue
            addr = sender_of(m)
            key = by_dom.get(_domain(addr))
            if not key:
                continue
            # Earliest reply wins the thread: that is the message they are
            # waiting on an answer to.
            if key in out and out[key]["when"] <= when:
                continue
            body = re.sub(r"\s+", " ", str(getattr(m, "Body", "") or "")).strip()
            out[key] = {"name": str(getattr(m, "SenderName", "") or ""),
                        "addr": addr, "when": when,
                        "entry": m.EntryID, "body": body[:400]}
    return out


def notes(order):
    """Per-haulier greeting/extra line for THIS order.

    The generic wording is deliberately bland because it has to fit everyone.
    Anyone who asked a question or made an offer is owed a sentence that
    answers it, and that sentence cannot be guessed from their text.

    Keyed by ORDER first, then by the address the haulier was asked at. It
    used to be keyed by address alone, and that leaked: the line written for
    Allelys on HO15/9/YO/WS - "please do not progress the abnormal load
    notification" - queued itself to go out again on 7115569, a ballast job
    with no abnormal load anywhere near it. A note belongs to one order and
    is spent once that order is stood down.
    """
    try:
        with open(NOTES, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    if d and all("@" in str(k) for k in d):
        print("  !! _stand_down_notes.json is still address-keyed, so it could "
              "put another order's note in these emails. Ignored - re-file it "
              "under the order it belongs to.")
        return {}
    got = d.get(str(order)) or {}
    return {k.lower(): v for k, v in got.items() if isinstance(v, dict)}


def build(order, asked, got, winner):
    """One message per haulier still owed an answer, winner excluded."""
    extra = notes(order)
    win = str(winner or "").lower()
    out = []
    for a in asked:
        mail = a["email"].lower()
        if win and (win in mail or win in a["name"].lower()):
            continue
        r = got.get(a["email"])
        over = extra.get(mail, {})
        who = over.get("name", _first_name(r["name"]) if r else "")
        hi = "Hi " + who + "," if who else "Hi,"
        note = str(over.get("extra") or "").strip()
        if r:
            lines = [hi, "",
                     "Thanks very much for coming back to me on " + order
                     + ", it is much appreciated."]
            if note:
                lines += ["", note]
            lines += ["",
                      "I have since got this one covered, so there is nothing "
                      "further needed from your side. Sorry for the wasted "
                      "time, and thanks again for the quick response. I will "
                      "keep you in mind for the next one."]
        else:
            lines = [hi, "",
                     "Further to my email earlier about " + order + ", this one "
                     "has now been covered, so please disregard the request."]
            if note:
                lines += ["", note]
            lines += ["", "Apologies if you have already spent time looking at it."]
        out.append({"name": a["name"], "to": (r or {}).get("addr") or a["email"],
                    "replied": bool(r), "entry": (r or {}).get("entry", ""),
                    "message": "\n".join(lines)})
    return out


def _dhl_account(ns):
    for i in range(1, ns.Accounts.Count + 1):
        a = ns.Accounts.Item(i)
        if str(getattr(a, "SmtpAddress", "")).lower() == bd.DHL_SMTP.lower():
            return a
    return None


def send(ns, order, msgs):
    """Reply in their own thread where they wrote in, fresh mail where not."""
    import send_order
    acct = _dhl_account(ns)
    if acct is None:
        print("ABORT: could not find the DHL account - nothing sent.")
        return 0
    n = 0
    for e in msgs:
        try:
            if e["entry"]:
                src = ns.GetItemFromID(e["entry"])
                m = src.Reply()          # keeps their own text quoted underneath
                m.HTMLBody = bd.html_from_message(e["message"]) + m.HTMLBody
            else:
                m = ns.Application.CreateItem(0)
                m.To = e["to"]
                m.Subject = "RE: " + order + " Delivery"
                m.HTMLBody = bd.html_from_message(e["message"])
            bd._attach_qr(m)
            if not send_order.bind_account(m, acct):
                print("   ! could not bind DHL account - NOT sending to " + e["name"])
                continue
            m.Send()
            n += 1
            print("   sent: %-26s %s" % (e["name"], "(reply)" if e["entry"] else "(new)"))
        except Exception as ex:
            print("   !! FAILED %s: %s" % (e["name"], ex))
    print("SEND_RESULT sent=%d" % n)
    return n


def main(argv):
    if len(argv) < 2:
        print("usage: stand_down.py <order> <winner> [send]")
        return 2
    order, winner = argv[0], argv[1]
    go = len(argv) > 2 and argv[2].lower() == "send"
    ns = bd.get_ns()
    asked = haulier_asks.load().get(order) or []
    if not asked:
        print("No record of anyone being asked about " + order + ".")
        return 1
    got = replies(ns, order, asked)
    msgs = build(order, asked, got, winner)
    r = sum(1 for m in msgs if m["replied"])
    print("%s: %d asked, %s booked it, %d to stand down (%d replied, %d did not).\n"
          % (order, len(asked), winner, len(msgs), r, len(msgs) - r))
    for m in msgs:
        print("=" * 68)
        print("TO: %s   [%s]   %s"
              % (m["to"], m["name"],
                 "REPLY in their thread" if m["replied"] else "new mail"))
        print("-" * 68)
        print(m["message"])
        print()
    if not go:
        print("DRY RUN - nothing sent. Re-run with 'send' to send.")
        return 0
    send(ns, order, msgs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
