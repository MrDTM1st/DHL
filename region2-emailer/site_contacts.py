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
