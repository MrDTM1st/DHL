"""A DTS whose delivery site can't be reached: ask Network Rail's Supplier Queries team for another contact.

His rule (09/11/2026): "for a DTS, if we can't get in contact with the delivery site, we email the Order Management team
and ask them for alternative contacts." Corrected 10/11/2026: Order Management answered the first one sent
that they only deal with RCOS orders, and a DTS is raised directly in iStore, which is Supplier Queries'
(SupplierQueries@networkrail.co.uk). So a DTS goes to Supplier Queries. A tracked order goes to the materials team that owns the product (the brief's
"Can't reach X?" button, auto_escalate.py, bounce_escalate.py); a DTS has no tracker record and its contact is usually a
name and a phone number off the DTS, so it goes to Order Management instead.

The email is built on the dashboard (the brief's "Ask Order Management" button, which he reads and edits) and sent by
send_order.send_haulier, which hands anything marked what="om_alt_contact" to send() here. send():
  * keeps the trail: it replies to all on a thread Order Management is already on, else forwards the newest mail about
    the DTS (the DTS itself, usually), so the request goes with the whole chain; a new email only when nothing is found;
  * never leaves DHL Road or ourselves on it (book_run.left_off_site), never goes to a haulier's thread.

    python om_contact.py sweep           who we have emailed about each open DTS (Sent Items) -> _om_tries.json
    python om_contact.py show NN...      what a send would do for that DTS, without sending
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
TRIES = os.path.join(HERE, "_om_tries.json")

# Order Management (ordermanagement@networkrail.co.uk) does RCOS orders only - their own answer to the first one, 10/11/2026:
# "Please contact SupplierQueries@networkrail.co.uk ... they deal with orders raised directly in iStore". A DTS is one.
# The names stay (ORDER_MANAGEMENT, OM) so every caller keeps working; only who it is changed.
ORDER_MANAGEMENT = {"name": "Supplier Queries", "email": "supplierqueries@networkrail.co.uk"}
OM = ORDER_MANAGEMENT["email"]
OLD_OM = "ordermanagement@networkrail.co.uk"          # asked before 10/11: still never counted as the site
SCAN_DAYS = 45


# ---------- pure ----------
def subject_for(rec):
    """"NN0000001-1 NWR - SOMEWHERE MDU AB1 2CD - alternative contact needed" - the same ending as every other
    alternative-contact email, so auto_escalate.already_asked and book_run.site_rank know it for what it is."""
    orders = " / ".join(str(o) for o in rec.get("orders") or [])
    site = rec.get("worksite") or rec.get("site") or ""
    return re.sub(r"\s+", " ", f"{orders} {site} {rec.get('postcode') or ''} - alternative contact needed").strip()


def _ours(addr):
    a = str(addr or "").lower()
    return a.endswith("@dhl.com") or "dhlroad" in a or a in (OM, OLD_OM)


def tries_from_sent(mails, not_site=frozenset()):
    """[{to, name, at}] - our sent mails about the DTS that went to someone outside DHL who isn't a haulier or Order
    Management: the site contact emailed. `mails` = [{to: [(name, address)], at: datetime}], oldest first."""
    out = []
    for m in sorted(mails, key=lambda x: x["at"]):
        for name, addr in m.get("to") or []:
            a = str(addr or "").lower()
            if "@" not in a or _ours(a) or a in not_site:
                continue
            out.append({"to": a, "name": str(name or "").strip(), "at": f"{m['at']:%d/%m/%Y %H:%M}"})
    return out


def pick(cands, not_site=frozenset()):
    """(index, "reply" | "forward") of the mail to send on, or (None, None).
    cands = [{people: set of addresses, when: datetime}]. A thread Order Management is already on is answered (reply to
    all); otherwise the newest mail about the DTS is forwarded. Hauliers' threads (the cover requests and their answers)
    are never used: Order Management has no business with a price, and a haulier must never be copied."""
    ok = [(i, c) for i, c in enumerate(cands) if not (set(c.get("people") or ()) & set(not_site))]
    if not ok:
        return None, None
    with_om = [(i, c) for i, c in ok if OM in (c.get("people") or ())]
    pool, how = (with_om, "reply") if with_om else (ok, "forward")
    i, _ = max(pool, key=lambda ic: ic[1]["when"])
    return i, how


# ---------- the mailbox ----------
def _boxes(root):
    """Inbox and every folder under it (ADHOC/DTS, Regions/Region 2/Completed, ...), and Sent Items."""
    import build_drafts as bd
    out = []

    def walk(f, depth):
        out.append(f)
        if depth < 4:
            for i in range(1, f.Folders.Count + 1):
                walk(f.Folders.Item(i), depth + 1)
    inbox = bd.sub(root, "Inbox")
    if inbox is not None:
        walk(inbox, 0)
    sent = bd.sub(root, "Sent Items")
    if sent is not None:
        out.append(sent)
    return out


def _about(box, ref):
    q = str(ref).replace("'", "''")
    try:
        return list(box.Items.Restrict(f"@SQL=(\"urn:schemas:httpmail:subject\" LIKE '%{q}%')"))
    except Exception:
        return []


def find_thread(ns, orders):
    """(mail, "reply" | "forward") to send on, or (None, None)."""
    import book_run
    import build_drafts as bd
    root = bd.dhl_store(ns)
    items, cands = [], []
    for box in _boxes(root):
        for o in orders:
            for it in _about(box, o):
                items.append(it)
                cands.append({"people": book_run._people(it), "when": book_run._when(it)})
    i, how = pick(cands, book_run.haulier_addresses())
    return (items[i], how) if i is not None else (None, None)


def _sent_to(it):
    out = []
    try:
        for i in range(1, it.Recipients.Count + 1):
            r = it.Recipients.Item(i)
            a = str(r.Address or "")
            try:
                u = r.AddressEntry.GetExchangeUser()
                a = (u.PrimarySmtpAddress if u is not None else "") or a
            except Exception:
                pass
            out.append((str(r.Name or ""), a))
    except Exception:
        pass
    return out


def open_dts():
    try:
        with open(os.path.join(HERE, "_adhocs.json"), encoding="utf-8") as f:
            recs = json.load(f)
    except Exception:
        return []
    return [r for r in recs if r.get("kind") == "dts"]


def load():
    try:
        with open(TRIES, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    tmp = TRIES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, TRIES)


def sweep(ns=None):
    """Who we have emailed about each open DTS, from Sent Items (so mails sent by hand count): {ref: {tried: [...],
    asked: <when Order Management was last asked> | ""}}. Read-only on the mailbox."""
    import book_run
    import build_drafts as bd
    ns = ns or bd.get_ns()
    sent = bd.sub(bd.dhl_store(ns), "Sent Items")
    not_site = book_run.haulier_addresses()
    since = datetime.now() - timedelta(days=SCAN_DAYS)
    old = load()
    out = {}
    for rec in open_dts():
        for ref in rec.get("orders") or []:
            mails, asked = [], ""
            for it in _about(sent, ref) if sent is not None else []:
                at = book_run._when(it)
                if at < since:
                    continue
                to = _sent_to(it)
                if any(str(a).lower() == OM for _, a in to):
                    asked = max(asked, f"{at:%Y-%m-%d %H:%M}")
                mails.append({"to": to, "at": at})
            prev = (old.get(ref) or {}).get("asked") or ""
            out[ref] = {"tried": tries_from_sent(mails, not_site), "asked": max(asked, prev)}
    _save(out)
    return out


def _mark_asked(orders):
    d = load()
    now = f"{datetime.now():%Y-%m-%d %H:%M}"
    for o in orders:
        d.setdefault(str(o), {"tried": []})["asked"] = now
    _save(d)


def send(ns, e, really=True):
    """Send the dashboard's reviewed email e = {to, cc, subject, message, orders}. Returns (sent, said)."""
    import book_run
    import build_drafts as bd
    import send_order
    orders = [str(o) for o in e.get("orders") or []]
    to, cc, _removed = bd.clean_to_cc(e.get("to") or OM, e.get("cc") or "")
    message = str(e.get("message") or "").strip()
    if not to or not message:
        return False, "no recipient or no message"
    acct = send_order.dhl_account(ns)
    if acct is None:
        return False, "the DHL account wasn't found"
    src, how = find_thread(ns, orders)
    if src is not None:
        m = src.ReplyAll() if how == "reply" else src.Forward()
        if how == "forward":
            m.To = to
            if cc:
                m.CC = cc
            m.Subject = str(e.get("subject") or "")[:150] or m.Subject
        else:
            have = {a for _, a in book_run._addresses(m)}
            for a in [x.strip() for x in re.split(r"[;,]", f"{to};{cc}") if x.strip()]:
                if a.lower() not in have:
                    m.Recipients.Add(a).Type = 1 if a.lower() in to.lower() else 2
        new, n = re.subn(r"(<body[^>]*>)", lambda mm: mm.group(1) + bd.html_from_message(message), m.HTMLBody,
                         count=1, flags=re.I)
        if n != 1:
            m.Close(1)
            return False, "couldn't find where the email's text starts"
        m.HTMLBody = new
    else:
        m = ns.Application.CreateItem(0)
        m.To = to
        if cc:
            m.CC = cc
        m.Subject = str(e.get("subject") or "")[:150] or "Alternative contact needed"
        m.HTMLBody = bd.html_from_message(message)
    bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        m.Close(1)
        return False, "couldn't set the DHL account on it"
    for i, a in reversed(book_run._addresses(m)):
        if book_run.left_off_site(a, bd.DHL_SMTP.lower()):
            m.Recipients.Remove(i)          # DHL Road and ourselves never stay on (his 03/11)
    got = [a for _, a in book_run._addresses(m)]
    if OM not in got:
        m.Close(1)
        return False, "Supplier Queries isn't on it"
    if set(got) & book_run.haulier_addresses():
        m.Close(1)
        return False, "a haulier is on it"
    way = {"reply": "replied on the thread Supplier Queries is on", "forward": "forwarded with the DTS's email trail",
           None: "a new email (no email about this DTS was found to send it on)"}[how]
    if not really:
        said = f"would send to {got}, subject {m.Subject!r}, {way}"
        m.Close(1)
        return False, said
    if how == "reply":
        m.Display(False)                    # a reply open in the reading pane refuses a plain Send
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    try:
        _mark_asked(orders)
        import metrics
        metrics.log("email_sent", what="om_alt_contact", to=", ".join(got), orders=orders)
    except Exception:
        pass
    return True, f"sent to {', '.join(got)} ({way})"


def main(argv):
    if argv[:1] == ["sweep"]:
        d = sweep()
        print(f"{len(d)} DTS ref(s): " + "; ".join(f"{k}: {len(v['tried'])} emailed"
                                                     + (f", Supplier Queries asked {v['asked']}" if v["asked"] else "")
                                                     for k, v in d.items()))
        return 0
    if argv[:1] == ["show"] and len(argv) > 1:
        import build_drafts as bd
        rec = next((r for r in open_dts() if argv[1] in (r.get("orders") or [])), {"orders": [argv[1]]})
        ok, said = send(bd.get_ns(), {"to": OM, "subject": subject_for(rec), "message": "(test - not sent)",
                                      "orders": rec.get("orders")}, really=False)
        print(said)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
