"""The delivery site's contact and phone number, kept for the dashboard's one-tap Call button.

A tracker record only keeps the contact's EMAIL - that is all the emailer needs. But ringing the site is the
other half of chasing, and the number is sitting in the extract the whole time: the contact cell reads
"Sam Example email: sam@example.com phone: 07700 900123" and Ship To Contact Phone usually repeats it. So the
daily run notes each order's contact here (remember), and the agent adds the number to the orders it sends
the dashboard (enrich). Local only: _site_phones.json is gitignored like the rest of the work data.
"""
import datetime
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.join(HERE, "_site_phones.json")
KEEP = 3000          # orders remembered; the oldest drop off first

# A UK number: +44 / 0044 / 0, then 9-10 more digits with spaces, dots, dashes or brackets between.
PHONE_RE = re.compile(r"(?:\+44\s?\(?0?\)?|0044\s?|0)(?:[\s.\-()]*\d){9,10}")


def contact_of(dcon, dphone=""):
    """(name, phone) from the extract's contact cell and its phone column. The phone column wins when it has
    a number; the cell's own "phone:" is the fallback. Either may be blank."""
    field = re.sub(r"\s+", " ", str(dcon or "")).strip()
    name = re.split(r"\s+(?:email|phone|tel)\s*:", field, flags=re.I)[0].strip(" ,-")
    if "@" in name:                     # no name at all - just an address
        name = ""
    m = PHONE_RE.search(str(dphone or "")) or PHONE_RE.search(field)
    phone = re.sub(r"\s+", " ", m.group(0)).strip() if m else ""
    return name, phone


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            book = json.load(f)
        return book if isinstance(book, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(emails, path=None):
    """Note every order's site contact from the day's built emails (each carries site_contact / site_phone).
    Never raises - a phone book is a nicety and must not stop the emails going out."""
    path = path or BOOK
    try:
        book = _load(path)
        today = datetime.date.today().isoformat()
        changed = False
        for e in emails or []:
            phone = str(e.get("site_phone") or "").strip()
            if not phone:
                continue
            for o in e.get("orders") or []:
                k = str(o).strip()
                old = book.get(k) or {}
                if old.get("phone") != phone or old.get("name") != (e.get("site_contact") or ""):
                    book[k] = {"name": e.get("site_contact") or "", "phone": phone, "at": today}
                    changed = True
        if not changed:
            return False
        if len(book) > KEEP:
            for k in sorted(book, key=lambda k: str(book[k].get("at", "")))[:len(book) - KEEP]:
                del book[k]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(book, f)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def same_person(a, b):
    """Whether two names are one person - the same surname and first initial, "Gallimore, Adam" read as Adam
    Gallimore. A lone first name is never enough."""
    def parts(n):
        n = str(n or "").strip()
        if "," in n:
            last, _, first = n.partition(",")
            n = f"{first} {last}"
        w = re.findall(r"[a-z]+", n.lower())
        return (w[0], w[-1]) if len(w) >= 2 else None
    pa, pb = parts(a), parts(b)
    return bool(pa and pb and pa[1] == pb[1] and pa[0][0] == pb[0][0])


def fill_contact(contact, sheet_name, sheet_phone, same=False):
    """His rule (01/11): "if they have updated the order but have not given you a site contact, use them as a site
    contact. You'll find it in the Excel sheet anyway, with their name and phone number." So: nobody named - the
    order's contact from its sheet, name and number; the sender named (the 30/10 rule) but no number - the sheet's
    number, only when the sender IS the sheet's contact (`same`: their address is the one we emailed, or the names
    match). (name, phone, how) - how is "" when nothing came from the sheet."""
    c = contact if isinstance(contact, dict) else {}
    name, phone = str(c.get("name") or "").strip(), str(c.get("phone") or "").strip()
    sheet_name, sheet_phone = str(sheet_name or "").strip(), str(sheet_phone or "").strip()
    if not sheet_phone:
        return name, phone, ""
    if not name and sheet_name:
        return sheet_name, sheet_phone, "sheet"
    if name and not phone and (same or same_person(name, sheet_name)):
        return name, sheet_phone, "sheet phone"
    return name, phone, ""


def fill_reply(rec, item=None, path=None):
    """The rule above on a freshly parsed reply (phase2): the record's contact filled from the order's remembered
    sheet contact. True when it changed anything."""
    det = rec.get("details") if isinstance(rec, dict) else None
    if not isinstance(det, dict):
        return False
    book = _load(path or BOOK)
    sheet = next((book[k] for k in (str(o).split("-")[0].strip() for o in rec.get("orders") or []) if k in book), None)
    if not sheet:
        return False
    sender = ""
    try:
        sender = str(getattr(item, "SenderEmailAddress", "") or "").strip().lower()
    except Exception:
        pass
    same = bool(sender) and sender == str(rec.get("to") or "").strip().lower()
    c = det.get("contact") if isinstance(det.get("contact"), dict) else {}
    name, phone, how = fill_contact(c, sheet.get("name"), sheet.get("phone"), same)
    if not how:
        return False
    det["contact"] = dict(c, name=name, phone=re.sub(r"\D", "", phone), confidence="high", source=how)
    return True


def enrich(tracker_data, path=None):
    """Add site_phone / site_contact to the delivery records that have none, from the remembered extract
    contacts. Collection records are left alone - their orders' numbers belong to the delivery site, not the
    supplier being asked to load. Returns the same dict."""
    book = _load(path or BOOK)
    if not book or not isinstance(tracker_data, dict):
        return tracker_data
    for r in tracker_data.get("records") or []:
        if not isinstance(r, dict) or r.get("kind", "delivery") != "delivery" or r.get("site_phone"):
            continue
        for o in r.get("orders") or []:
            c = book.get(str(o).split("-")[0].strip())
            if c and c.get("phone"):
                r["site_phone"] = c["phone"]
                if c.get("name") and not r.get("site_contact"):
                    r["site_contact"] = c["name"]
                break
    return tracker_data
