"""
Who answered an order's email, and with what (his 02/11). "usually when we escalate, the people from the network rail
team will either give us a screenshot of another email contact or like type in another email contact. Now, it's best
you tell us instead of just saying that Danny's replied" - and Danny's own answer ("is the delivery date still ok for
the 5/11/26") gave nothing to type: "we're going to have to email him back asking for more info". Neither is a reply
to update CTMS from. phase2's reply check uses these; standard library and delivery_details only.
"""
import re

import delivery_details as dd

QUOTE_START = re.compile(r"^\s*(?:From:|-----\s*Original Message|_{8,})", re.M | re.I)
HTML_SIGN_OFF = re.compile(r"(?:kind|best|warm)\s+regards|\bregards\b|many\s+thanks|\bcheers\b", re.I)
HTML_QUOTE = re.compile(r"From:\s*</b>|>\s*From:\s|-----\s*Original Message", re.I)


def materials_team(addr):
    """The materials team an address belongs to (Steel Materials ...) - the people an escalation goes to."""
    try:
        import hauliers
        teams = {str(t["email"]).lower(): t["name"] for t in hauliers.MATERIALS_TEAMS.values()}
    except Exception:
        teams = {}
    return teams.get(str(addr or "").strip().lower(), "")


def own_text(body):
    """Their own words in a reply - above the mail they quote."""
    body = str(body or "")
    m = QUOTE_START.search(body)
    return body[:m.start()] if m else body


def message_part(body):
    """Their own words without their signature: up to the sign-off."""
    return dd.above_sign_off(own_text(body))


def typed_contacts(body, skip=()):
    """The addresses and mobile numbers typed into their message - never the sender's own, ours, or ones we had."""
    t = message_part(body)
    skip = {str(s).strip().lower() for s in skip if s}
    mails = [m.lower() for m in re.findall(r"[\w.'+-]+@[\w-]+(?:\.[\w-]+)+", t)]
    mails = [m for m in dict.fromkeys(mails) if m not in skip and not m.endswith("@dhl.com")]
    phones = [re.sub(r"\D", "", p) for p in re.findall(r"(?<!\d)(?:\+44\s?|0)7\d{3}\s?\d{3}\s?\d{3}(?!\d)", t)]
    phones = ["0" + p[2:] if p.startswith("44") else p for p in phones]
    return mails + [p for p in dict.fromkeys(phones) if p not in skip]


def message_pictures(html):
    """Pictures put in their message - a screenshot of a contact, as the materials team sends - counted above the
    sign-off and the quoted mail, so the logos in signatures don't count."""
    h = str(html or "")
    cut = len(h)
    for pat in (HTML_SIGN_OFF, HTML_QUOTE):
        m = pat.search(h)
        if m:
            cut = min(cut, m.start())
    return len(re.findall(r"<img\b", h[:cut], re.I))


def said_line(body, limit=200):
    """What they wrote, in one line - for telling him."""
    t = re.sub(r"^\s*(?:OFFICIAL|OFFICIAL-SENSITIVE)\s*", "", message_part(body), flags=re.I)
    t = re.sub(r"(?im)^\s*sent from .*$", "", t)
    return re.sub(r"\s+", " ", t).strip()[:limit]


def gave_details(record, body, product_type=None, sender=""):
    """Did their own words give CTMS anything? Our questions answered - or, written out, a time, offloading, access,
    rear steer, PTS, a vehicle, What3Words, a contact with a number, a day other than the one the order has. Read from
    their text only: the quoted mail holds our own questions and dates ("is the delivery date still ok for the 5/11/26"
    read back as 05/11, and "alternative contact needed" from the quoted subject as a contact called "needed"), and a
    signature is nobody's delivery ("you have the wrong person" read as details off the writer's own footer, 02/11)."""
    try:
        if dd.extract_fields(own_text(body)):
            return True
        d = dd.parse_reply(message_part(body), product_type=product_type, sender=sender) or {}
    except Exception:
        return True                                             # never let a parse fault hide a real reply
    val = lambda k: (d.get(k) or {}).get("value")              # noqa: E731
    if any(val(k) for k in ("offloading", "artic_access", "rear_steer", "pts", "vehicle", "what3words")):
        return True
    if (d.get("time") or {}).get("earliest"):
        return True
    c = d.get("contact") or {}
    if c.get("phone") and c.get("source") not in ("sender", "sheet"):
        return True
    day = val("date")
    return bool(day) and day != str(record.get("delivery_date") or "")


def sort_out(record, mails, product_type=None):
    """Which of an order's inbound mails, newest first (each {"addr", "who", "body", ...}), is the site's answer: the
    newest whose own words give the details. The newest from the materials team and the newest with nothing to type are
    handed back to be told as what they are - neither ever hides the answer behind it (his 02/11: a "wrong person,
    my namesake will help" then the namesake's answer). (answer, team, blank), any of them None."""
    own = str(record.get("to") or "").strip().lower()
    team = blank = None
    for m in mails:
        if m.get("addr") != own and materials_team(m.get("addr")):
            team = team or m
        elif gave_details(record, m.get("body"), product_type, m.get("who") or ""):
            return m, team, blank
        else:
            blank = blank or m
    return None, team, blank
