"""
Manual order send.

Give it an order number; it searches your Outlook (Synergy Upload + Inbox) for
the Haulier Extract that contains it, builds the email(s) for that order using
the SAME grouping (one per contact+site+date), and previews them. A pasted order
is a deliberate pick, so the region + supplier-rails filters are NOT applied here.

    python send_order.py 6054999          # find + preview (never sends)
    python send_order.py 6054999 send     # actually send (only after you've okayed the preview)
"""
import sys, os, re, zipfile
from collections import OrderedDict
import win32com.client
import build_drafts as bd
import tracker


def extract_contains(path, order):
    """Fast check: is this order number's text inside the xlsx?"""
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith(".xml") and ("sharedstrings" in name.lower() or "sheet" in name.lower()):
                    if order.encode() in z.read(name):
                        return True
    except Exception:
        return False
    return False


def find_extract(ns, order, limit=None):
    # A pasted order is a deliberate pick: search EVERY spreadsheet attachment
    # in EVERY folder, whole history, newest first. Inbox tree first (that is
    # where extracts live), then the rest of the mailbox.
    dhl = bd.dhl_store(ns)
    tmp = os.path.join(bd.HERE, "_search.xlsx")
    base = str(order).split("-")[0]

    def walk(folder):
        try:
            items = folder.Items
        except Exception:
            items = None
        if items is not None:
            try:
                items.Sort("[ReceivedTime]", True)
            except Exception:
                pass
            n = 0
            for it in items:
                n += 1
                if limit and n > limit:
                    break
                try:
                    for j in range(1, it.Attachments.Count + 1):
                        att = it.Attachments.Item(j)
                        fn = str(att.FileName)
                        if not fn.lower().endswith((".xlsx", ".xlsm")):
                            continue
                        att.SaveAsFile(tmp)
                        if extract_contains(tmp, base):
                            return fn
                except Exception:
                    continue
        try:
            for i in range(1, folder.Folders.Count + 1):
                hit = walk(folder.Folders.Item(i))
                if hit:
                    return hit
        except Exception:
            pass
        return None

    inbox = bd.sub(dhl, "Inbox")
    fn = walk(inbox) if inbox is not None else None
    if not fn:
        for i in range(1, dhl.Folders.Count + 1):
            f = dhl.Folders.Item(i)
            if f.Name.strip().lower() == "inbox":
                continue
            fn = walk(f)
            if fn:
                break
    return (tmp, fn) if fn else (None, None)


CODE_PAT = re.compile(r"^\d{3,4}/\d{3,}")


def pick_product(r, C):
    """Readable text and short code, whichever columns they sit in.
    Haulier extracts keep text in 'Product / Service Code'; BS/Master batches
    swap the two columns."""
    a = bd.clean(r[C["prod"]]) if C["prod"] is not None else ""
    b = bd.clean(r[C["prod_code"]]) if C["prod_code"] is not None else ""
    if CODE_PAT.match(a) and b and not CODE_PAT.match(b):
        return b, a   # swapped layout: text was in Description
    return a, b


def build_for_order(path, order, source=""):
    rows, C = bd.load_rows(path)
    target = order.split("-")[0]
    mine = [r for r in rows if r[C["order"]] and bd.base_order(r[C["order"]]) == target]
    groups = OrderedDict()
    for r in mine:
        key = (bd.email_of(r[C["dcon"]]), bd.clean(r[C["dpc"]]), bd.fdate(r[C["date"]]))
        groups.setdefault(key, []).append(r)
    emails = []
    for (em, dpc, dd), rs in groups.items():
        r0 = rs[0]
        orders = sorted(set(bd.base_order(r[C["order"]]) for r in rs))
        subject = f"{' / '.join(orders)} {bd.clean(r0[C['daddr']])} {dpc}"
        picked = [pick_product(r, C) for r in rs]
        items = [(r[C["qty"]], p[0]) for r, p in zip(rs, picked)]
        nm = bd.firstname(r0[C['dcon']])
        text, html, message = bd._bodies(nm, items, dd)
        pcodes = sorted({p[1] for p in picked if p[1]})
        emails.append(dict(to=em, cc="", name=nm, subject=subject, body=text, html=html,
                           message=message, items=len(items), date=dd, area=bd.area(dpc),
                           orders=orders, product_codes=pcodes,
                           materials=bd.product_summary(items),
                           site=bd.clean(r0[C['daddr']]), postcode=dpc, source=source))
    return emails


PENDING = os.path.join(bd.HERE, "_pending_email.json")


def save_pending(emails):
    import json
    slim = [{k: e.get(k) for k in ("to", "cc", "name", "subject", "message", "date", "area",
                                   "orders", "product_codes", "materials", "site",
                                   "postcode", "source")} for e in emails]
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump(slim, f, indent=1, default=str)


def send_pending(ns):
    """Send whatever is in _pending_email.json (possibly edited): the HTML is
    rebuilt from the message text, signature and QR appended untouched."""
    import json
    emails = json.load(open(PENDING, encoding="utf-8"))
    for e in emails:
        e["html"] = bd.html_from_message(e.get("message", ""))
        e["body"] = e.get("message", "") + "\n\n\n" + bd.SIGNATURE
    return send_emails(ns, emails)


def dhl_account(ns):
    accts = ns.Accounts
    for i in range(1, accts.Count + 1):
        a = accts.Item(i)
        if str(a.SmtpAddress).strip().lower() == bd.DHL_SMTP:
            return a
    return None


def bind_account(mail, acct):
    """Set SendUsingAccount reliably. Plain assignment is silently ignored by
    some pywin32 versions (the 5033351 misfire), so use the raw property-put
    and then VERIFY the account actually took."""
    try:
        mail._oleobj_.Invoke(64209, 0, 8, 0, acct)   # DISPID for SendUsingAccount
    except Exception:
        try:
            mail.SendUsingAccount = acct
        except Exception:
            pass
    try:
        return str(mail.SendUsingAccount.SmtpAddress).strip().lower() == bd.DHL_SMTP
    except Exception:
        return False


def send_emails(ns, emails):
    outlook = win32com.client.Dispatch("Outlook.Application")
    acct = dhl_account(ns)
    if acct is None:
        print("ABORT: DHL account not found in Outlook - nothing sent.")
        return 0
    sent = 0
    for e in emails:
        if not e["to"]:
            print(f"   ! no recipient, skipped: {e['subject']}")
            continue
        m = outlook.CreateItem(0)
        m.To = e["to"]
        if e.get("cc"):
            m.CC = e["cc"]
        m.Subject = e["subject"]
        bd._attach_qr(m)
        m.HTMLBody = e.get("html") or e["body"]
        if not bind_account(m, acct):
            print(f"   ! could not bind DHL account - NOT sending: {e['subject']}")
            continue
        m.Send()
        tracker.log(orders=e.get("orders", []), to=e["to"], name=e.get("name", ""),
                    product_codes=e.get("product_codes", []), materials=e.get("materials", ""),
                    site=e.get("site", ""), postcode=e.get("postcode", ""), delivery_date=e["date"],
                    source=e.get("source", ""), status="sent")
        sent += 1
    if sent:
        try:
            ns.SendAndReceive(False)   # flush the outbox immediately
        except Exception:
            pass
    return sent


def main():
    if len(sys.argv) < 2:
        print("Usage: python send_order.py <order#> [send]  |  python send_order.py sendjson")
        return
    order = sys.argv[1].strip()
    mode = sys.argv[2] if len(sys.argv) > 2 else "preview"
    ns = bd.get_ns()
    if order == "sendjson":
        n = send_pending(ns)
        print(f"Sent {n} email(s) from your DHL account (edited version).")
        return
    import order_index
    path, fn = order_index.lookup(ns, order, os.path.join(bd.HERE, "_search.xlsx"))
    if path:
        print(f"Found instantly via index: {fn}\n")
    else:
        print(f"Not in index - deep-searching your Outlook for {order}...")
        path, fn = find_extract(ns, order)
        if not path:
            print("Not found anywhere in the mailbox. (Check the order reference.)")
            return
        print(f"Found in: {fn}\n")
    emails = build_for_order(path, order, source=fn)
    if not emails:
        print("Extract matched but no rows for that exact order number.")
        return
    for e in emails:
        print("=" * 70)
        print(f"To:      {e['to']}\nSubject: {e['subject']}   [area {e['area']}]")
        print("-" * 70)
        print(e["body"])
        print()
    if mode == "send":
        print("Sending...")
        n = send_emails(ns, emails)
        print(f"Sent {n} email(s) from your DHL account.")
    else:
        save_pending(emails)
        print(f"(preview only - {len(emails)} email(s) ready. Nothing sent.)")


if __name__ == "__main__":
    main()
