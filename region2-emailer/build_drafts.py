"""
Region 2 emailer - Phase 1 draft engine.

Reads config.json, finds a Synergy Haulier Extract (latest from Outlook, or a
path you pass in), applies every agreed rule, and either previews the emails or
creates them as DRAFTS in your DHL Drafts folder. It never sends.

Usage:
    python build_drafts.py preview            # find latest extract, print emails
    python build_drafts.py preview <xlsx>     # preview a specific file
    python build_drafts.py commit             # create drafts in DHL Drafts (latest extract)
    python build_drafts.py commit <xlsx>      # create drafts from a specific file
"""
import sys, os, json, re, html as _html
from collections import defaultdict, OrderedDict
import tracker

DHL_SMTP = "delali.opoku@dhl.com"
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
REGION = CFG["regions"][CFG["active_region"]]
AREAS = set(REGION["postcode_areas"])
SOURCE_PREFIX = CFG["email_source"]["only_file"].lower()

QUESTIONS = """    Date and time of delivery?
    Who will be the contact for delivery?
    Alternative delivery contact?
    Do we need to bring our own offloading? (HIAB or Moffet)
    Can artics access the site?
    Is rear steer required?
    Does the driver need PTS (Only required if within 3m of line)?
    What3Words Location?"""

SIGNATURE = """Kind regards

Delali Opoku

Transport Planner
Manufacturing Logistics
DHL Supply Chain UKI

Contact
07483621949

Out of Hours
03308 577160
07540901630

Excellence. Simply delivered.

Tell us how we did - we would greatly appreciate you taking 5 minutes to send us feedback on your delivery using the link or QR code below:
https://forms.office.com/e/hsiiNzy6B4"""

FORMS_URL = "https://forms.office.com/e/hsiiNzy6B4"
QR_PATH = os.path.join(HERE, "qr.png")

SIGNATURE_HTML = (
    "Kind regards<br><br>"
    "<b>Delali Opoku</b><br><br>"
    "<b>Transport Planner</b><br>Manufacturing Logistics<br>DHL Supply Chain UKI<br><br>"
    "<b>Contact</b><br>07483621949<br><br>"
    "<b>Out of Hours</b><br>03308 577160<br>07540901630<br><br>"
    '<span style="color:#D40511;font-weight:bold;">Excellence. Simply delivered.</span><br><br>'
    "Tell us how we did - we would greatly appreciate you taking 5 minutes to send us feedback "
    "on your delivery using the link or QR code below:<br>"
    f'<a href="{FORMS_URL}">{FORMS_URL}</a><br>'
    '<img src="cid:qrcode" alt="Feedback QR code" width="120" height="120" style="margin-top:8px;border:0;">'
)


def _bodies(name, items, dd):
    ask = "Can you please help with the details below and I can get the delivery arranged for you?"
    if len(items) == 1:
        q, pr = items[0]
        line_t = f"I've got {q}x {pr} available on {dd}. {ask}"
        line_h = f"I've got {q}x {_html.escape(pr)} available on {dd}. {ask}"
    else:
        line_t = (f"I've got the following available on {dd}:\n\n"
                  + "\n".join(f"    {q}x {pr}" for q, pr in items) + f"\n\n{ask}")
        line_h = (f"I've got the following available on {dd}:<br><br>"
                  + "".join(f"&nbsp;&nbsp;&nbsp;&nbsp;{q}x {_html.escape(pr)}<br>" for q, pr in items)
                  + f"<br>{ask}")
    message = f"Hi {name},\n\n{line_t}\n\n{QUESTIONS}"
    text = f"{message}\n\n\n{SIGNATURE}"
    q_html = _html.escape(QUESTIONS).replace("\n", "<br>").replace("    ", "&nbsp;&nbsp;&nbsp;&nbsp;")
    html = ('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1f1f1f;">'
            f"Hi {_html.escape(name)},<br><br>{line_h}<br><br>{q_html}<br><br>{SIGNATURE_HTML}</div>")
    return text, html, message


def html_from_message(message):
    """Rebuild the branded HTML email from an (edited) plain-text message.
    The signature block - bolds, red strapline, QR - is appended untouched."""
    body = _html.escape(message).replace("\n", "<br>").replace("    ", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return ('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1f1f1f;">'
            f"{body}<br><br>{SIGNATURE_HTML}</div>")


def _attach_qr(mail):
    if not os.path.exists(QR_PATH):
        return
    try:
        att = mail.Attachments.Add(QR_PATH)
        pa = att.PropertyAccessor
        pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", "qrcode")   # content-id
        pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x7FFE000B", True)        # hide from attach list
    except Exception:
        pass

# ---------- helpers ----------
def clean(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()

def area(pc):
    m = re.match(r"\s*([A-Za-z]{1,2})", str(pc or ""))
    return m.group(1).upper() if m else "?"

def email_of(s):
    m = re.search(r"[\w.\-+]+@[\w.\-]+", str(s or ""))
    return m.group(0) if m else None

def firstname(s):
    nm = re.split(r"\s+email:", str(s or ""))[0].strip()
    return nm.split()[0].capitalize() if nm else ""

def base_order(o):
    return str(o).split("-")[0]

def fdate(d):
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d or "")

def is_supplier_rail(order):
    return str(order or "")[:1].isalpha()   # order number starts with a letter

def product_type(desc):
    d = (desc or "").upper()
    for key, label in (("SLEEPER", "sleepers"), ("BALLAST", "ballast"), ("RAIL", "rails"),
                       ("SWITCH", "S&C"), ("CROSSING", "S&C"), ("PAD", "pads")):
        if key in d:
            return label
    w = (desc or "").split()
    return w[0].lower() if w else "items"

def _qty(q):
    try:
        return int(float(q))
    except Exception:
        return 0

def product_summary(items):
    """items = list of (qty, description) -> readable string like '51x sleepers, 40x ballast'."""
    agg = OrderedDict()
    for qty, desc in items:
        t = product_type(desc)
        agg[t] = agg.get(t, 0) + _qty(qty)
    return ", ".join(f"{q}x {t}" for t, q in agg.items())

# ---------- outlook ----------
def get_ns():
    import win32com.client
    return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")

def dhl_store(ns):
    for i in range(1, ns.Folders.Count + 1):
        f = ns.Folders.Item(i)
        if f.Name.lower() == DHL_SMTP:
            return f
    return None

def sub(folder, name):
    for i in range(1, folder.Folders.Count + 1):
        c = folder.Folders.Item(i)
        if c.Name.strip().lower() == name.strip().lower():
            return c
    return None

def find_inbox_extracts(ns, limit=300):
    """ALL Haulier Extracts sitting in the Inbox root (not filed subfolders) -
    unprocessed extracts live in the Inbox; there can be several per day.
    Returns [(path, filename)] newest first."""
    dhl = dhl_store(ns)
    inbox = sub(dhl, "Inbox")
    if inbox is None:
        return []
    items = inbox.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    found, seen, n = [], set(), 0
    for it in items:
        n += 1
        if n > limit:
            break
        try:
            for j in range(1, it.Attachments.Count + 1):
                att = it.Attachments.Item(j)
                fn = str(att.FileName)
                low = fn.lower()
                if low.startswith(SOURCE_PREFIX) and not low.startswith("master") and fn not in seen:
                    seen.add(fn)
                    path = os.path.join(HERE, f"_inbox_extract_{len(found)}.xlsx")
                    att.SaveAsFile(path)
                    found.append((path, fn))
        except Exception:
            pass
    return found

# ---------- core ----------
def load_rows(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    def ci(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None
    C = dict(
        order=ci("customer order no"), dpc=ci("d postcode"), dcon=ci("d contact name"),
        prod=ci("product / service code"), prod_code=ci("product / description"),
        qty=ci("product qty"), date=ci("delivery date"),
        daddr=ci("d address1", "d address 1"),
    )
    return rows[1:], C

def build_emails(rows, C, source=""):
    """Single-file convenience wrapper around build_emails_multi."""
    return build_emails_multi([(rows, C, source)])


def build_emails_multi(files):
    """files = [(rows, C, source)]. Combines ALL extracts, de-duplicates
    identical rows appearing in more than one file (an 'additional' extract
    repeating an order must not double quantities), then groups by
    contact+site+date as usual."""
    groups = OrderedDict()
    skipped_rails = 0
    skipped_region = set()
    seen_rows = set()
    for rows, C, source in files:
        for r in rows:
            order = r[C["order"]]
            if order is None:
                continue
            dup = (str(order), clean(r[C["prod"]]), str(r[C["qty"]]),
                   fdate(r[C["date"]]), clean(r[C["dpc"]]))
            if dup in seen_rows:
                continue
            seen_rows.add(dup)
            if is_supplier_rail(order):
                skipped_rails += 1
                continue
            key = (email_of(r[C["dcon"]]), clean(r[C["dpc"]]), fdate(r[C["date"]]))
            groups.setdefault(key, []).append((r, C, source))
    emails = []
    for (em, dpc, dd), bundle in groups.items():
        if area(dpc) not in AREAS:
            skipped_region.add((dpc, dd))
            continue
        r0, C0, _ = bundle[0]
        orders = sorted(set(base_order(r[C["order"]]) for r, C, _ in bundle))
        subject = f"{' / '.join(orders)} {clean(r0[C0['daddr']])} {dpc}"
        items = [(r[C["qty"]], clean(r[C["prod"]])) for r, C, _ in bundle]
        nm = firstname(r0[C0['dcon']])
        text, html, message = _bodies(nm, items, dd)
        pcodes = sorted({clean(r[C['prod_code']]) for r, C, _ in bundle
                         if C['prod_code'] is not None and r[C['prod_code']]})
        sources = " + ".join(sorted({s for _, _, s in bundle if s}))
        emails.append(dict(to=em, name=nm, subject=subject, body=text, html=html,
                           items=len(items), date=dd, orders=orders, product_codes=pcodes,
                           materials=product_summary(items), site=clean(r0[C0['daddr']]),
                           postcode=dpc, source=sources))
    return emails, skipped_rails, len(skipped_region)

def create_drafts(ns, emails):
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    acct = None
    for a in ns.Accounts:
        if str(a.SmtpAddress).lower() == DHL_SMTP:
            acct = a
            break
    drafts = acct.DeliveryStore.GetDefaultFolder(16) if acct else None  # 16 = Drafts
    made = 0
    for e in emails:
        if not e["to"]:
            print(f"   ! skipped (no recipient found): {e['subject']}")
            continue
        m = outlook.CreateItem(0)  # 0 = MailItem
        m.To = e["to"]
        m.Subject = e["subject"]
        _attach_qr(m)
        m.HTMLBody = e.get("html") or e["body"]
        try:
            m._oleobj_.Invoke(64209, 0, 8, 0, acct)   # SendUsingAccount, reliably
        except Exception:
            try:
                m.SendUsingAccount = acct
            except Exception:
                pass
        m.Save()
        if drafts is not None:
            m.Move(drafts)
        tracker.log(orders=e.get("orders", []), to=e["to"], name=e.get("name", ""),
                    product_codes=e.get("product_codes", []), materials=e.get("materials", ""),
                    site=e.get("site", ""), postcode=e.get("postcode", ""), delivery_date=e["date"],
                    source=e.get("source", ""), status="drafted")
        made += 1
    return made

# ---------- entry ----------
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    path = sys.argv[2] if len(sys.argv) > 2 else None
    ns = None
    if path is None:
        ns = get_ns()
        extracts = find_inbox_extracts(ns)
        if not extracts:
            print("No Haulier Extracts in the Inbox."); return
        print(f"Found {len(extracts)} Haulier Extract(s) in the Inbox:")
        for _, fn in extracts:
            print(f"  - {fn}")
        print()
        files = []
        for p, fn in extracts:
            rows, C = load_rows(p)
            files.append((rows, C, fn))
    else:
        print(f"Using file: {path}\n")
        rows, C = load_rows(path)
        files = [(rows, C, os.path.basename(path))]

    total_rows = sum(len(rows) for rows, _, _ in files)
    emails, rails, region = build_emails_multi(files)
    print(f"Rows: {total_rows} | Region 2 emails: {len(emails)} | "
          f"supplier-rails skipped: {rails} | out-of-region groups skipped: {region}\n")
    for e in emails:
        print(f"  TO {e['to'] or '(none)':36} | {e['subject']} | {e['items']} item(s) {e['date']}")

    if mode == "commit":
        if ns is None:
            ns = get_ns()
        print("\nCreating drafts in DHL Drafts...")
        n = create_drafts(ns, emails)
        print(f"Done - {n} draft(s) created. Nothing sent.")
    else:
        print("\n(preview only - no drafts created. Run with 'commit' to create them.)")

if __name__ == "__main__":
    main()
