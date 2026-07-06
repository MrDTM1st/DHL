"""
Phase 2 - the reply side of the Region 2 emailer.

For every order the tool has emailed (tracker status 'sent'):
  * find the customer's reply in the DHL inbox
  * if it's an out-of-office / auto-reply -> FLAG it (your cue to chase someone
    else), do NOT count it as a real reply
  * if it's a genuine reply -> mark replied AND draft the send-off brief into
    Region 2 > Send Out, pre-filled from the extract with the reply quoted and
    the from-their-reply fields marked [CHECK] so nothing is ever guessed.

Plus 2-business-day chasers (weekends + England/Wales bank holidays skipped).
Sending chasers is opt-in: preview by default; only sends when told to.

    python phase2.py check          # replies + OOO flags + send-off drafts (no customer email sent)
    python phase2.py chase          # preview who is due a chase (sends nothing)
    python phase2.py chase send     # actually send the chasers
"""
import os, re, sys
from datetime import datetime, date, timedelta
import win32com.client
import build_drafts as bd
import order_index
import send_order
import tracker

DHL_SMTP = "delali.opoku@dhl.com"
CHASE_AFTER_BDAYS = 2
MAX_CHASES = 3

# England & Wales bank holidays (2026-2027). Extend as needed.
BANK_HOLIDAYS = {
    "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25",
    "2026-08-31", "2026-12-25", "2026-12-28",
    "2027-01-01", "2027-03-26", "2027-03-29", "2027-05-03", "2027-05-31",
    "2027-08-30", "2027-12-27", "2027-12-28",
}


# ---------- dates ----------
def is_working_day(d):
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in BANK_HOLIDAYS


def _parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s), fmt)
        except Exception:
            pass
    return None


def business_days_since(dstr):
    dt = _parse_dt(dstr)
    if not dt:
        return 0
    cur, today, n = dt.date(), date.today(), 0
    while cur < today:
        cur += timedelta(days=1)
        if is_working_day(cur):
            n += 1
    return n


# ---------- outlook helpers ----------
def _dhl(ns):
    for i in range(1, ns.Folders.Count + 1):
        if ns.Folders.Item(i).Name.lower() == DHL_SMTP:
            return ns.Folders.Item(i)


def _sub(f, name):
    if f is None:
        return None
    for i in range(1, f.Folders.Count + 1):
        c = f.Folders.Item(i)
        if c.Name.strip().lower() == name.strip().lower():
            return c


def _sendout_folder(ns, create=True):
    dhl = _dhl(ns)
    region2 = _sub(_sub(_sub(dhl, "Inbox"), "Regions"), "Region 2")
    if region2 is None:
        return None
    folder = _sub(region2, "Send out") or _sub(region2, "Send Out")
    if folder is None and create:
        try:
            folder = region2.Folders.Add("Send Out")
        except Exception:
            folder = None
    return folder


def _rt_naive(rt):
    try:
        return datetime.fromtimestamp(rt.timestamp())
    except Exception:
        return None


AUTO_SUBJECT = ("out of office", "automatic reply", "auto-reply", "autoreply",
                "auto reply", "on annual leave", "annual leave", "on holiday",
                "away from the office", "on leave", "out of the office")


def is_auto_reply(item):
    subj = str(getattr(item, "Subject", "") or "").lower()
    if any(k in subj for k in AUTO_SUBJECT):
        return True
    try:
        hdr = item.PropertyAccessor.GetProperty(
            "http://schemas.microsoft.com/mapi/proptag/0x007D001F") or ""
        h = hdr.lower()
        if ("auto-submitted: auto-replied" in h or "auto-submitted:auto-replied" in h
                or "x-autoreply" in h or "x-autorespond" in h
                or "precedence: auto_reply" in h):
            return True
    except Exception:
        pass
    return False


def find_reply(ns, record):
    """The customer's reply for this order: an inbox item received after we
    emailed, whose subject carries one of the order numbers."""
    inbox = _sub(_dhl(ns), "Inbox")
    if inbox is None:
        return None
    emailed = _parse_dt(record.get("emailed_at"))
    to = (record.get("to") or "").strip().lower()
    for order in record.get("orders", []):
        digits = re.sub(r"\D", "", str(order))
        if not digits:
            continue
        try:
            flt = ("@SQL=(\"urn:schemas:httpmail:subject\" LIKE '%" + digits + "%')")
            found = inbox.Items.Restrict(flt)
            found.Sort("[ReceivedTime]", True)
        except Exception:
            found = inbox.Items
        for it in found:
            try:
                rt = _rt_naive(it.ReceivedTime)
                if emailed and rt and rt <= emailed:
                    continue
                sender = str(getattr(it, "SenderEmailAddress", "") or "").lower()
                subj_digits = re.sub(r"\D", "", str(it.Subject or ""))
                if (to and to in sender) or (digits in subj_digits):
                    return it
            except Exception:
                continue
    return None


# ---------- send-off brief ----------
def _load_full(path):
    import openpyxl, warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip().lower() if h is not None else "" for h in rows[0]]

    def ci(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None
    C = dict(order=ci("customer order no"),
             caddr=ci("address1", "address 1"), cpc=ci("postcode"),
             cdate=ci("collection date"),
             daddr=ci("d address1", "d address 1"), dpc=ci("d postcode"),
             ddate=ci("delivery date"),
             prod=ci("product / service code"), prodc=ci("product / description"),
             qty=ci("product qty"))
    return rows[1:], C


def _answer(body, *fragments):
    """Pull the customer's answer that follows one of our questions on the same
    line, e.g. 'Do we need to bring our own offloading? HIAB required' -> the
    text after the '?'. Reading the answer (not the whole body) avoids matching
    keywords that live in the question itself."""
    for line in str(body or "").splitlines():
        low = line.lower()
        if any(fr in low for fr in fragments) and "?" in line:
            ans = line.split("?", 1)[1]
            ans = re.sub(r"^\s*\([^)]*\)\s*", "", ans).strip(" \t-:>")  # drop a trailing bit of the question
            if ans:
                return ans
    return None


def build_brief(ns, record, reply_item):
    order = record["orders"][0]
    tmp = os.path.join(bd.HERE, "_brief.xlsx")
    path, fn = order_index.lookup(ns, order, tmp)
    if not path:
        path, fn = send_order.find_extract(ns, order)
    coll = deliv = cdate = ""
    mats = record.get("materials", "")
    if path:
        try:
            rows, C = _load_full(path)
            target = order.split("-")[0]
            grp = [r for r in rows if r[C["order"]] and bd.base_order(r[C["order"]]) == target]
            if grp:
                r0 = grp[0]
                coll = f"{bd.clean(r0[C['caddr']])}, {bd.clean(r0[C['cpc']])}" if C['caddr'] is not None else ""
                deliv = f"{bd.clean(r0[C['daddr']])}, {bd.clean(r0[C['dpc']])}" if C['daddr'] is not None else ""
                cdate = bd.fdate(r0[C['cdate']]) if C['cdate'] is not None else ""
        except Exception:
            pass
    if not deliv:
        deliv = f"{record.get('site', '')}, {record.get('postcode', '')}"

    try:
        reply_body = str(reply_item.Body or "")
    except Exception:
        reply_body = ""
    d_ans = _answer(reply_body, "date and time of delivery", "delivery date")
    o_ans = _answer(reply_body, "own offloading", "hiab or moffet", "offloading")
    deliv_dt = d_ans if d_ans else "[CHECK - from their reply below]"
    offload = o_ans if o_ans else "[CHECK - from their reply below]"

    brief = (
        f"Order: {' / '.join(record['orders'])}\n"
        f"Collection: {coll}\n"
        f"Delivery: {deliv}\n"
        f"Collection date/time: {cdate}\n"
        f"Delivery date/time: {deliv_dt}\n"
        f"Materials: {mats}\n"
        f"Vehicle: (leave with me)\n"
        f"Offloading: {offload}\n"
        f"\n--- their reply {'-' * 40}\n{reply_body[:3000]}\n"
    )

    outlook = win32com.client.Dispatch("Outlook.Application")
    m = outlook.CreateItem(0)
    m.Subject = "SEND OUT: " + " / ".join(record["orders"]) + " " + record.get("site", "")
    m.Body = brief
    acct = send_order.dhl_account(ns)
    if acct is not None:
        send_order.bind_account(m, acct)
    m.Save()
    folder = _sendout_folder(ns)
    if folder is not None:
        m.Move(folder)
    return True


# ---------- main passes ----------
def check(ns=None):
    ns = ns or bd.get_ns()
    d = tracker.load()
    replies = ooo = briefs = 0
    for r in d["records"]:
        if r.get("status") != "sent":
            continue
        if r.get("reply_at") or r.get("ooo_at"):
            continue
        item = find_reply(ns, r)
        if not item:
            continue
        if is_auto_reply(item):
            r["ooo_at"] = tracker._now()
            ooo += 1
        else:
            r["reply_at"] = tracker._now()
            replies += 1
            try:
                if build_brief(ns, r, item):
                    r["sendoff_ready"] = True
                    briefs += 1
            except Exception as e:
                r["sendoff_note"] = str(e)[:140]
    tracker.save(d)
    print(f"check: {replies} new repl(y/ies), {ooo} out-of-office flagged, {briefs} send-off draft(s) created.")
    return replies, ooo, briefs


def _due_for_chase(r):
    if r.get("status") != "sent":
        return False
    if r.get("reply_at") or r.get("ooo_at"):
        return False
    if r.get("chases", 0) >= MAX_CHASES:
        return False
    if business_days_since(r.get("emailed_at")) < CHASE_AFTER_BDAYS:
        return False
    if r.get("last_chased_at") == date.today().isoformat():
        return False
    return True


def _send_chase(ns, record):
    collected, tokens, nf = send_order.resolve_orders(ns, " ".join(record["orders"]))
    if not collected:
        return False
    emails = send_order.build_from_collected(collected)
    if not emails:
        return False
    e = emails[0]
    original = e["message"].split("\n\n", 1)[-1]
    e["message"] = f"Hi {e['name']},\n\nCan I please get a reply to the below?\n\n{original}"
    e["html"] = bd.html_from_message(e["message"])
    e["cc"] = ""
    return send_order.send_emails(ns, [e]) > 0   # send_emails -> tracker.log bumps chases


def run_chasers(ns=None, send=False):
    ns = ns or bd.get_ns()
    d = tracker.load()
    due = [r for r in d["records"] if _due_for_chase(r)]
    out = []
    chased_ids = []
    for r in due:
        bd_n = business_days_since(r.get("emailed_at"))
        if not send:
            out.append(f"  DUE  {' / '.join(r['orders'])} -> {r['to']} "
                       f"(bday {bd_n}, would be chase #{r.get('chases', 0) + 1})")
            continue
        ok = _send_chase(ns, r)
        out.append(f"  {'SENT' if ok else 'FAIL'} {' / '.join(r['orders'])} -> {r['to']}")
        if ok:
            chased_ids.append(r["id"])
    if send and chased_ids:
        d2 = tracker.load()
        for r in d2["records"]:
            if r["id"] in chased_ids:
                r["last_chased_at"] = date.today().isoformat()
        tracker.save(d2)
    verb = "sent" if send else "due"
    print(f"chasers: {len(chased_ids) if send else len(due)} {verb}.")
    print("\n".join(out) if out else "  (none)")
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    ns = bd.get_ns()
    if cmd == "check":
        check(ns)
    elif cmd == "chase":
        run_chasers(ns, send=(len(sys.argv) > 2 and sys.argv[2] == "send"))
    elif cmd == "all":
        check(ns)
        run_chasers(ns, send=False)
    else:
        print("usage: phase2.py check | chase [send] | all")


if __name__ == "__main__":
    main()
