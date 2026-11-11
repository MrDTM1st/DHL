"""The Haulier Rejection Form's responses, worked out and sent (11/11).

The rule from the team: the form is filled in whenever NOC or a Tier 1 says no to work offered them, and when a Tier 1
prices off matrix and a cheaper price is found elsewhere - S&C excepted, it goes its own way. His ask (11/11): filled in
by itself, in the background, with the fewest clicks, from the dashboard.

Where a response comes from:
  reply   a Tier 1 on the form answered a ring-round ask (haulier_asks, from Sent Items) with a no: the reason is read
          from their own words, the quoted ask under them left out
  added   the rejection card's "A no by phone or Teams" - NOC's come that way, its asks go by Teams
One response is one job: the hauliers who said no to it for the same reason. Its details - date, collection, postcode,
product, quantity, vehicle - come from the tracker and the wait list where they know the order. A detail worked out
rather than read is UNSURE, and a response with an unsure or missing detail is HELD for him (NOT CERTAIN on the card):
the rest go when he presses Send, or by themselves once he has switched Auto on (the dashboard starts those).

    python rejections.py refresh             replies read (Outlook), responses made or added to
    python rejections.py show
    python rejections.py add '{json}'        a no he was told: orders, hauliers, reason, and whatever he typed
    python rejections.py edit ID '{json}'    his changes from the card
    python rejections.py send ID ['{json}']  filled in and submitted on the work PC - the dashboard's go-ahead first
    python rejections.py drop ID             not needed
    python rejections.py auto on|off

Each command but show ends with one JSON line, {"ok": ..., "said": ...}, for the home agent.
"""
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_rejections.json")
LOCK = os.path.join(HERE, "_rejections.lock.json")      # named so git's _*.json rule keeps it out, like the store

# The form's own words (Haulier Rejection Form 2026, read off the work PC's Edge 11/11) - filled in exactly so
HAULIERS = ("DE O'Reilly", "Hargreaves Services", "Hotspur Hire (HHL)", "JG Vesty", "Lawsons Haulage",
            "Tennant Transport", "V Festa & Sons", "Wm Hamilton & Sons", "DHL NOC")
PRODUCTS = ("Rail", "S&C", "Adhoc - Rail / S&C", "Bagged Ballast", "Loose Ballast", "Sleepers", "Timbers / Bearers",
            "Wheelsets", "Train Bogies", "Container", "Pallets", "Shift Work", "Electrification - Piles / Masts etc.")
VEHICLES = ("Artic Flat", "Artic Hiab", "60ft Flat", "60ft Hiab", "Trombone", "Trombone Hiab", "Artic Moffett",
            "Rigid Flat / Hiab", "Rigid Tipper", "Artic Tipper", "Curtainsider", "Other")
REASONS = ("No Availability - General", "No Availability - Night/Weekend", "No Availability - Vehicle Type",
           "No Availability - Date of Job/Notice", "No Reply", "No Availability - Area",
           "Priced Off-Matrix - booked in as cheapest", "Priced Off-Matrix", "No Availability - Rate",
           "Partial Rejection", "No Availability - PTS", "Rejected - Product/Site Access", "Other")
YES_NO = ("Yes", "No")
OPEN = ("ready", "held", "sending", "failed")
FIELDS = ("orders", "hauliers", "reason", "other", "date", "collection", "postcode", "consolidated", "product",
          "quantity", "vehicle", "vehicle_other", "rear_steer")
ASK_DAYS = 7                  # ring-round asks this recent are looked at - the card's first fill a week's no's
KEEP_DONE = 200               # sent and dropped responses kept, newest
SENDING_FOR = 300             # a send not heard back from in this long is taken as failed (the work PC's answer
                              # waits 150 s at most) - Send can be pressed again; the note says to look at the form

# Other names the haulier directory and people use for the hauliers on the form
_SAME = (("william hamilton", "Wm Hamilton & Sons"), ("wm hamilton", "Wm Hamilton & Sons"),
         ("hargreaves", "Hargreaves Services"), ("hotspur", "Hotspur Hire (HHL)"), ("hhl", "Hotspur Hire (HHL)"),
         ("de o'reilly", "DE O'Reilly"), ("d e o'reilly", "DE O'Reilly"), ("de oreilly", "DE O'Reilly"),
         ("deo", "DE O'Reilly"), ("vesty", "JG Vesty"), ("lawsons", "Lawsons Haulage"),
         ("tennant", "Tennant Transport"), ("festa", "V Festa & Sons"), ("noc", "DHL NOC"), ("dhl fleet", "DHL NOC"))


def _key(text):
    return " ".join(re.sub(r"[^a-z0-9&' ]+", " ", str(text or "").lower().replace("’", "'")).split())


def form_name(name):
    """The form's name for a haulier, or None when the form doesn't list them (a Tier 2, or AHT)."""
    k = _key(name)
    if not k:
        return None
    for h in HAULIERS:
        if _key(h) == k:
            return h
    for word, h in _SAME:
        if re.search(r"(?:^| )" + re.escape(word) + r"(?: |$)", k):
            return h
    return None


# ---- a reply read: is it a no, and why
_QUOTED = re.compile(r"(?:\bfrom:\s|-{2,}\s*original message|\bsent:\s|\bon\s.{4,80}?\swrote:|\bget outlook for)",
                     re.I)
_NO = re.compile(r"\b(?:no availability|not available|unavailable|unable|can'?t|cannot|can not|won'?t be able|"
                 r"no capacity|fully booked|booked up|no (?:vehicles?|wagons?|trucks?|lorr(?:y|ies)|drivers?)|"
                 r"nothing available|decline|pass on|not for us|have to say no|not this time|no thank|"
                 r"not able|don'?t have|do not have|haven'?t got|have not got|no,? sorry|sorry,? no|no can do|"
                 r"no\b[\w ]{0,30}\b(?:free|spare))\b", re.I)
_PRICE = re.compile(r"(?:£\s?\d|\b\d{3,5}(?:\.\d\d)?\s?(?:\+\s?vat|pounds|gbp)\b)", re.I)
_WHY = (
    ("No Availability - PTS", r"\bpts\b|personal track safety|track (?:badge|safety)"),
    ("No Availability - Night/Weekend", r"\bnights?\b|weekends?|saturday|sunday|\bsat\b|\bsun\b|out of hours|"
                                        r"overnight|bank holiday"),
    ("No Availability - Vehicle Type", r"hiab|moffett?|\bcrane|trailer|trombone|extendable|\b[468]0\s?(?:ft|foot)|"
                                       r"low ?loader|\bartic|\brigid|tipper|curtain ?sider|flat ?bed"),
    ("No Availability - Area", r"\barea\b|too far|not (?:in )?our (?:area|patch|way)|don'?t (?:cover|go)|"
                               r"out of (?:our )?(?:area|range|way)|that far"),
    ("No Availability - Date of Job/Notice", r"short notice|\bnotice\b|that day|those days|tomorrow|\btoday\b|"
                                             r"(?:this|that|next) week|monday|tuesday|wednesday|thursday|friday|"
                                             r"\bdates?\b|\bon the \d"),
    ("No Availability - Rate", r"\brates?\b|\bprice|not worth|\bcost|money|cheap"),
    ("Rejected - Product/Site Access", r"site access|\baccess\b|can'?t get (?:in|on)|"
                                       r"(?:don'?t|do not) (?:carry|move|do|handle) (?:rails?|ballast|sleepers?|that)|"
                                       r"not something we"),
    ("Partial Rejection", r"\bpart(?:ial)?\b|some of|only (?:take|do|carry|manage)|\bhalf\b"),
)


# a helpdesk's wrapping round a reply (a Tier 1's ticket system, 05/11), links, rules - none of it their words
_WRAPPING = (r"-#-#-.*?-#-#-", r"your request #\S+ has been updated\.?(?:\s*you can reply to this email above\.?)?",
             r"<https?://[^>\s]*>?", r"_{4,}", r"\b[\w'\u2019. -]{2,40}\sstaff - \d\d/\d\d/\d{4} \d\d:\d\d")
_SIGN_OFF = re.compile(r"\b(?:kind regards|best regards|warm regards|many thanks|regards|thanks|thank you|cheers|"
                       r"best wishes)\b", re.I)


def own_words(body):
    """A reply's own words: a helpdesk's wrapping taken off, the quoted ask under them and the signature after them
    cut off - so a reason is read from what they wrote, never from a job title or an address in the signature."""
    body = re.sub(r"\s+", " ", str(body or "")).strip()
    for pat in _WRAPPING:
        body = re.sub(pat, " ", body, flags=re.I)
    body = re.sub(r"\s+", " ", body).strip()
    m = _QUOTED.search(body)
    body = (body[:m.start()] if m else body).strip()
    for s in _SIGN_OFF.finditer(body):
        if s.start() >= 15:                    # "Thanks for asking, but..." opens a message, it doesn't sign one off
            body = body[:s.start()]
            break
    return body.strip(" ,;-")


def reason_of(words):
    """(the form's reason, sure) for a reply that says no, or None for one that doesn't - a price quoted is a quote,
    not a no. Two reasons named at once: the first in the form's order, marked unsure."""
    w = str(words or "")
    if not _NO.search(w) or _PRICE.search(w):
        return None
    hits = [reason for reason, pat in _WHY if re.search(pat, w, re.I)]
    if not hits:
        return "No Availability - General", True
    return hits[0], len(hits) == 1


# ---- the job's details
def product_of(*texts, adhoc=False):
    """The form's product type from what an order says it carries, or None."""
    t = " ".join(str(x or "") for x in texts).lower()
    if re.search(r"s\s?&\s?c\b|\bs and c\b|switch(?:es)? (?:and|&) crossing|\bturnouts?\b", t):
        found = "S&C"
    elif "ballast" in t:
        found = "Bagged Ballast" if re.search(r"\bbag", t) else "Loose Ballast"
    elif "sleeper" in t:
        found = "Sleepers"
    elif re.search(r"timber|bearer", t):
        found = "Timbers / Bearers"
    elif "wheelset" in t:
        found = "Wheelsets"
    elif "bogie" in t:
        found = "Train Bogies"
    elif "container" in t:
        found = "Container"
    elif "pallet" in t:
        found = "Pallets"
    elif re.search(r"\bpiles?\b|\bmasts?\b|electrification|\bole\b", t):
        found = "Electrification - Piles / Masts etc."
    elif re.search(r"\brails?\b|56e1|60e1|60e2|113a|\bcwr\b", t):
        found = "Rail"
    else:
        return None
    return "Adhoc - Rail / S&C" if adhoc and found in ("Rail", "S&C") else found


def rail_length(*texts):
    """The longest rail length named (metres), or None: 'RAIL SHORT, 56E1, 260 GRADE, 18.288M' reads 18.288."""
    got = [float(x) for x in re.findall(r"\b(\d{1,2}\.\d{1,3})\s?m\b", " ".join(str(t or "") for t in texts).lower())]
    return max(got) if got else None


def vehicle_of(product, offloading=None, length=None, artic_access=None, quantity=None):
    """(the form's vehicle type, sure) worked out the way the desk works it out - rails by length (13.72 m an artic,
    18.3 m a 60ft, longer a trombone), HIAB or Moffett from the site's offloading, no artic access a rigid, ten bags
    of ballast or fewer a rigid - or (None, False)."""
    off = str(offloading or "").upper()
    hiab, moff = off == "HIAB", off == "MOFFETT"
    if str(artic_access or "").lower() == "no":
        return "Rigid Flat / Hiab", True
    if product == "Bagged Ballast":
        n = _number(quantity)
        return ("Rigid Flat / Hiab" if n is not None and n <= 10 else "Artic Hiab"), n is not None
    if product == "Loose Ballast":
        return "Artic Tipper", False
    if product in ("Rail", "Adhoc - Rail / S&C") and length:
        if length > 18.3:
            return ("Trombone Hiab" if hiab else "Trombone"), bool(off)
        if length > 13.72:
            return ("60ft Hiab" if hiab else "60ft Flat"), bool(off)
    if moff:
        return "Artic Moffett", True
    if product and off:
        return ("Artic Hiab" if hiab else "Artic Flat"), off in ("HIAB", "SITE/NONE")
    return None, False


def _number(text):
    m = re.search(r"\d+", str(text or ""))
    return int(m.group()) if m else None


def iso_date(text):
    """'16/11/2026', '16/11/26' or '2026-11-16' -> '2026-11-16', else ''."""
    s = str(text or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _ord(o):
    return str(o or "").replace(" ", "").upper()


def _value(details, key):
    v = (details or {}).get(key) if isinstance(details, dict) else None
    return v.get("value") if isinstance(v, dict) else None


def vehicle_code(code):
    """The form's vehicle type from a vehicle code or words an order carries ('NR_7.5T', 'ARTIC HIAB', '60ft flat'),
    or None."""
    c = str(code or "").upper().replace("_", " ")
    if not c.strip():
        return None
    hiab = "HIAB" in c or "CRANE" in c
    if "TROMBONE" in c or "EXTEND" in c or re.search(r"\b80\s?(?:FT|FOOT|')", c):
        return "Trombone Hiab" if hiab else "Trombone"
    if re.search(r"\b60\s?(?:FT|FOOT|')", c):
        return "60ft Hiab" if hiab else "60ft Flat"
    if "MOFF" in c:
        return "Artic Moffett"
    if "TIPPER" in c:
        return "Rigid Tipper" if "RIGID" in c else "Artic Tipper"
    if "CURTAIN" in c:
        return "Curtainsider"
    if "RIGID" in c or re.search(r"\b(?:3\.5|7\.5|18|26)\s?T(?:ONNE)?\b", c):
        return "Rigid Flat / Hiab"
    if "ARTIC" in c or re.search(r"\b40\s?(?:FT|FOOT|')|\bFLAT\b", c):
        return "Artic Hiab" if hiab else "Artic Flat"
    return None


_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")


def _left_the_map(orders, todo=None, booked=None):
    """What's still known of a job gone from the map: its day from the CTMS to-do's answers (the site's delivery day),
    its postcode from the booked ad hoc's subject line."""
    want = {_ord(o) for o in orders}
    if todo is None:
        todo = _json(os.path.join(HERE, "_ctms_todo.json"), {}).get("items") or []
    if booked is None:
        booked = _json(os.path.join(HERE, "_adhoc_booked.json"), [])
    got = {}
    for it in todo:
        if isinstance(it, dict) and want & {_ord(o) for o in it.get("orders") or []}:
            day = iso_date((it.get("answers") or {}).get("date") if isinstance(it.get("answers"), dict) else "")
            got["date"] = day or got.get("date", "")
    for b in booked:
        if isinstance(b, dict) and _ord(b.get("ref")) in want:
            pcs = _POSTCODE.findall(str(b.get("subject") or "").upper())
            if pcs:
                got["postcode"] = pcs[-1]
    return {k: v for k, v in got.items() if v}


def details(orders, tracker=None, waitlist=None, adhocs=None, pins=None, todo=None, booked=None):
    """What the desk knows of these orders' job - the tracker, the map's ad hocs and pins, the wait list, and for a job
    gone from the map what the CTMS to-do and the booked ad hocs kept:
    {date, collection, postcode, product, quantity, vehicle, rear_steer, sure: {field: bool}} - {} when nothing does.
    The job's date is its delivery day (his word, 11/11)."""
    want = {_ord(o) for o in orders}
    if tracker is None:
        tracker = _json(os.path.join(HERE, "tracker.json"), {}).get("records") or []
    if waitlist is None:
        waitlist = _json(os.path.join(HERE, "waitlist.json"), {}).get("entries") or []
    if adhocs is None:
        adhocs = _json(os.path.join(HERE, "_adhocs.json"), [])
    if pins is None:
        pins = _json(os.path.join(HERE, "_pins.json"), [])
    rows = [(where, r) for where, got in (("tracker", tracker), ("adhoc", adhocs), ("pin", pins),
                                          ("waitlist", waitlist))
            for r in got if isinstance(r, dict) and want & {_ord(o) for o in r.get("orders") or []}]
    if not rows:
        left = _left_the_map(orders, todo, booked)
        return dict(left, sure={k: True for k in left}) if left else {}
    where, r = rows[0]
    d = r.get("details") if isinstance(r.get("details"), dict) else {}
    materials = str(r.get("materials") or "")
    codes = " ".join(str(c) for c in r.get("product_codes") or []) + " " + str(r.get("product") or "")
    adhoc = r.get("kind") == "adhoc" or where == "adhoc" or any(_ord(o).startswith("AH") for o in orders)
    product = product_of(materials, codes, adhoc=adhoc)
    m = re.match(r"\s*(\d+)\s*x\s*(.*)", materials)
    quantity = str(r.get("qty") or "").strip() or (
        f"{m.group(1)} {m.group(2)}" if m and not re.search(r"\d{4}/", m.group(2)) else (m.group(1) if m else ""))
    date = iso_date(_value(d, "date")) or iso_date(r.get("delivery_date")) or iso_date(r.get("date"))
    coded = vehicle_code(_value(d, "vehicle"))            # the vehicle the request asked for, when it names one
    vehicle, v_sure = (coded, True) if coded else vehicle_of(product, _value(d, "offloading"),
                                                             rail_length(codes, materials), _value(d, "artic_access"),
                                                             quantity)
    steer = str(_value(d, "rear_steer") or "").lower()
    collection = ", ".join(x for x in (str(r.get("collection_site") or "").strip(),
                                       str(r.get("collection_pc") or "").strip()) if x)
    return {"date": date, "collection": collection, "postcode": str(r.get("postcode") or "").strip().upper(),
            "product": product or "", "quantity": quantity, "vehicle": vehicle or "",
            "rear_steer": "Yes" if steer == "yes" else "No",
            "sure": {"date": True, "product": bool(product), "vehicle": v_sure, "rear_steer": steer in ("yes", "no")}}


def _fill(rec):
    """Blanks on an open response filled from what the desk knows now - never over anything already there, so his
    changes stay. -> whether anything was filled."""
    known = details(rec["orders"])
    sure = known.get("sure") or {}
    filled = False
    for f in ("date", "collection", "postcode", "product", "quantity", "vehicle"):
        if not rec.get(f) and known.get(f):
            rec[f] = known[f]
            filled = True
            if f in sure and not sure[f] and f not in rec.setdefault("unsure", []):
                rec["unsure"].append(f)
    if filled:
        rec["status"] = _status(rec)
    return filled


# ---- the store
def _json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except Exception:
        return default


def load():
    d = _json(PATH, {})
    d.setdefault("items", [])
    d.setdefault("auto", False)
    return d


def save(d):
    done = [r for r in d["items"] if r.get("status") not in OPEN]
    if len(done) > KEEP_DONE:
        drop = {id(r) for r in done[:-KEEP_DONE]}
        d["items"] = [r for r in d["items"] if id(r) not in drop]
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, PATH)


@contextmanager
def locked(wait=30.0):
    """The store to itself while it is read, changed and written back - the background refresh and a dashboard
    Send never write over each other. A lock left by a process that died is taken after a minute."""
    end = time.time() + wait
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCK) > 60:
                    os.remove(LOCK)
                    continue
            except OSError:
                pass
            if time.time() > end:
                raise RuntimeError("The rejection list is busy - try again in a moment.")
            time.sleep(0.2)
    try:
        yield
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


def gaps(rec):
    """What stops a response going, in words: [] when it can go."""
    out = []
    if not rec.get("hauliers") or any(h not in HAULIERS for h in rec["hauliers"]):
        out.append("the haulier")
    if not iso_date(rec.get("date")):
        out.append("the date of the job")
    # every question on the form is required - these three too, though the page's screen-reader names don't say so
    # (the red asterisks on the work PC's form, 11/11)
    for f, words in (("collection", "the collection site"), ("postcode", "the postcode"), ("quantity", "the quantity")):
        if not str(rec.get(f) or "").strip():
            out.append(words)
    if rec.get("consolidated") not in YES_NO:
        out.append("consolidated or not")
    if rec.get("product") not in PRODUCTS:
        out.append("the product")
    elif rec["product"] == "S&C":
        out.append("S&C goes its own way, not on this form")
    if rec.get("vehicle") not in VEHICLES or (rec["vehicle"] == "Other" and not rec.get("vehicle_other")):
        out.append("the vehicle")
    if rec.get("rear_steer") not in YES_NO:
        out.append("rear-steer or not")
    if rec.get("reason") not in REASONS or (rec["reason"] == "Other" and not rec.get("other")):
        out.append("the reason")
    names = {"date": "the date of the job", "product": "the product", "vehicle": "the vehicle",
             "rear_steer": "rear-steer", "reason": "the reason", "quantity": "the quantity",
             "collection": "the collection site", "postcode": "the postcode"}
    out += [f"{names.get(f, f)} (NOT CERTAIN)" for f in rec.get("unsure") or [] if names.get(f, f) not in out]
    return out


def _status(rec):
    return "held" if gaps(rec) else "ready"


def _id(orders, reason, date, hauliers):
    raw = "|".join(sorted(_ord(o) for o in orders)) + f"|{reason}|{date}|{'/'.join(sorted(hauliers))}|{time.time()}"
    return "r" + hashlib.sha1(raw.encode()).hexdigest()[:10]


def make(orders, hauliers, reason, said="", source="added", given=None, tracker=None, waitlist=None, now=None):
    """A response for this job: what he gave, the rest from what the desk knows of the orders (details), the
    worked-out parts marked unsure."""
    given = {k: v for k, v in (given or {}).items() if k in FIELDS and v not in (None, "")}
    orders = [str(o).strip() for o in orders if str(o).strip()]
    known = details(orders, tracker, waitlist)
    sure = known.get("sure") or {}
    rec = {"orders": orders, "hauliers": sorted({h for h in (form_name(x) for x in hauliers) if h},
                                                key=HAULIERS.index),
           "reason": reason, "other": "", "consolidated": "No", "vehicle_other": "", "said": str(said or "")[:300],
           "source": source, "made": (now or datetime.now()).strftime("%d/%m/%Y %H:%M"), "unsure": []}
    for f in ("date", "collection", "postcode", "product", "quantity", "vehicle", "rear_steer"):
        rec[f] = known.get(f, "") or ("No" if f == "rear_steer" else "")
        if f in sure and not sure[f] and rec[f]:
            rec["unsure"].append(f)
    if not known:
        rec["unsure"] = []                        # nothing worked out: what's missing shows as missing
    _apply(rec, given)
    rec["id"] = _id(orders, reason, rec["date"], rec["hauliers"])
    rec["status"] = _status(rec)
    return rec


def _apply(rec, given):
    """His words over the worked-out ones: each field he gave is taken as sure."""
    for f, v in given.items():
        if f == "orders":
            v = [str(o).strip() for o in (v if isinstance(v, list) else re.split(r"[\s,;/&+]+", str(v))) if str(o).strip()]
        elif f == "hauliers":
            v = sorted({h for h in (form_name(x) for x in (v if isinstance(v, list) else [v])) if h},
                       key=HAULIERS.index)
        elif f == "date":
            v = iso_date(v) or ""
        else:
            v = str(v).strip()[:200]
        rec[f] = v
        if f in rec.get("unsure", []):
            rec["unsure"].remove(f)


def _same_job(a, b):
    return ({_ord(o) for o in a["orders"]} == {_ord(o) for o in b["orders"]} and a["reason"] == b["reason"]
            and a.get("date") == b.get("date"))


def add(d, rec):
    """Into the store: onto an open response for the same job and reason (another haulier ticked), else as its own.
    A haulier already in a sent or dropped response for it is not put in again. -> the response it went into, or
    None when there was nothing new."""
    for old in d["items"]:
        if _same_job(old, rec) and set(rec["hauliers"]) <= set(old["hauliers"]):
            return None                           # known already - open, sent or dropped
    for old in d["items"]:
        if _same_job(old, rec) and old.get("status") in ("ready", "held", "failed"):
            old["hauliers"] = sorted(set(old["hauliers"]) | set(rec["hauliers"]), key=HAULIERS.index)
            if rec.get("said") and rec["said"] not in old.get("said", ""):
                old["said"] = (old.get("said", "") + " | " + rec["said"]).strip(" |")[:600]
            old["status"] = _status(old)
            return old
    d["items"].append(rec)
    return rec


def find(d, rid):
    return next((r for r in d["items"] if r.get("id") == rid), None)


def answers(rec):
    """The form's answers for a response, as the work PC fills them in (ctms_form). Raises ValueError with what's
    missing when it can't go."""
    left = [g for g in gaps(rec) if "NOT CERTAIN" not in g]
    if left:
        raise ValueError("Not sent - it needs " + ", ".join(left) + ".")
    day = datetime.strptime(iso_date(rec["date"]), "%Y-%m-%d")
    out = [{"q": "Haulier Name", "tick": list(rec["hauliers"])},
           {"q": "Date of Job", "text": f"{day.month}/{day.day}/{day.year}"},          # the form's M/d/yyyy
           {"q": "Collection Site", "text": rec["collection"]},
           {"q": "Delivery Postcode", "text": rec["postcode"]},
           {"q": "Consolidated Delivery", "pick": rec["consolidated"]},
           {"q": "Product Type", "pick": rec["product"]},
           {"q": "Quantity", "text": rec["quantity"]}]
    out.append(dict({"q": "Vehicle Type", "pick": rec["vehicle"]},
                    **({"other": rec["vehicle_other"]} if rec["vehicle"] == "Other" else {})))
    out.append({"q": "Rear-Steer", "pick": rec["rear_steer"]})
    out.append(dict({"q": "Rejection Reason", "pick": rec["reason"]},
                    **({"other": rec["other"]} if rec["reason"] == "Other" else {})))
    return out


def _shown(rec):
    """Its status as the card shows it: a send never heard back from is a failed one."""
    if rec.get("status") == "sending" and time.time() - float(rec.get("sending_ts") or 0) >= SENDING_FOR:
        return "failed"
    return rec.get("status")


def panel(d=None):
    """The rejection card: what's open (with what stops each one going), the last few sent, and the Auto switch."""
    d = d or load()
    keep = FIELDS + ("id", "status", "said", "source", "made", "unsure", "note", "sent_at")
    open_ = [dict({k: r.get(k) for k in keep}, status=_shown(r), gaps=gaps(r))
             for r in d["items"] if r.get("status") in OPEN]
    sent = [{k: r.get(k) for k in ("id", "orders", "hauliers", "reason", "sent_at")}
            for r in d["items"] if r.get("status") == "sent"][-5:]
    return {"open": open_[-40:], "sent": sent, "auto": bool(d.get("auto"))}


# ---- replies, from the mailbox
def _when(text):
    try:
        return datetime.strptime(str(text or "")[:16], "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def asked_jobs(asks, now=None):
    """{(form haulier, address, when asked): [orders]} - the ring-round asks to hauliers on the form, recent ones,
    orders asked in one email kept together as one job."""
    cut = (now or datetime.now()) - timedelta(days=ASK_DAYS)
    jobs = {}
    for order, rows in (asks or {}).items():
        for a in rows or []:
            h = form_name(a.get("name"))
            when = _when(a.get("when"))
            if h and when and when >= cut and a.get("email"):
                jobs.setdefault((h, str(a["email"]).lower(), a["when"]), []).append(order)
    return jobs


def _replies(ns, jobs, days=ASK_DAYS + 2):
    """{job: [{"when", "body"}]} - every reply in the DHL mailbox's Inbox (and its folders) from the address's company
    whose subject names one of the job's orders. One pass through the mailbox for all of them."""
    import build_drafts as bd
    import stand_down
    dhl = bd.dhl_store(ns)
    if dhl is None:
        return {}
    by_order = {}
    for job, orders in jobs.items():
        for o in orders:
            by_order.setdefault(_ord(o), []).append(job)
    if not by_order:
        return {}
    pat = re.compile("|".join(re.escape(o) for o in sorted(by_order, key=len, reverse=True)))
    cut = datetime.now() - timedelta(days=days)
    out = {}

    def walk(f):
        yield f
        try:
            for i in range(1, f.Folders.Count + 1):
                yield from walk(f.Folders.Item(i))
        except Exception:
            pass

    for fold in walk(bd.sub(dhl, "Inbox")):
        try:
            its = fold.Items
            its.Sort("[ReceivedTime]", True)
        except Exception:
            continue
        for i in range(1, min(its.Count, 400) + 1):
            try:
                m = its.Item(i)
                when = m.ReceivedTime.replace(tzinfo=None)
            except Exception:
                continue
            if when < cut:
                break
            subject = str(getattr(m, "Subject", "") or "").upper().replace(" ", "")
            hits = set(pat.findall(subject))
            if not hits:
                continue
            dom = stand_down._domain(stand_down.sender_of(m))
            for o in hits:
                for job in by_order[o]:
                    if dom and dom == stand_down._domain(job[1]) and when >= (_when(job[2]) or cut):
                        out.setdefault(job, []).append({"when": when, "body": str(getattr(m, "Body", "") or "")[:3000]})
    return out


def refresh(ns=None, asks=None, replies=None, now=None):
    """Responses made from the replies: the newest reply that says yes or no decides - a no with its reason makes a
    response (or ticks the haulier on one for the same job). Blanks on the open ones are filled first, from whatever
    the desk has learnt of their jobs since. -> how many were made or added to."""
    if asks is None:
        import haulier_asks
        asks = haulier_asks.load()
    jobs = asked_jobs(asks, now)
    got = (replies(jobs) if replies else _replies(ns, jobs)) if jobs else {}
    n = 0
    with locked():
        d = load()
        for rec in d["items"]:                    # details that have turned up since: blanks filled, his words kept
            if rec.get("status") in ("ready", "held", "failed"):
                _fill(rec)
        for job, orders in jobs.items():
            verdict = None
            for msg in sorted(got.get(job) or [], key=lambda x: x["when"]):
                words = own_words(msg["body"])
                why = reason_of(words)
                if why:
                    verdict = (why, words)
                elif _PRICE.search(words) or re.search(r"\b(?:yes|can do|we can do|happy to)\b", words, re.I):
                    verdict = None                # came back with a price or a yes after all
            if not verdict:
                continue
            (reason, sure), words = verdict
            rec = make(orders, [job[0]], reason, said=words[:200], source="reply", now=now)
            if rec.get("product") == "S&C":
                continue                          # S&C goes its own way
            if not sure:
                rec["unsure"].append("reason")
                rec["status"] = _status(rec)
            if add(d, rec):
                n += 1
        save(d)
    return n


# ---- sent on the work PC
def _bridge_ask(action, **args):
    import ctms_remote as R
    R.BASE, R.KEY = R._desk()
    return R.ask(action, wait_total=150, **args)


def send(rid, edits=None, ask=None):
    """The response filled in and submitted on the work PC (the dashboard switched Look mum, no hands on for it).
    {"ok", "said"} - sent only when the form said it took it."""
    with locked():
        d = load()
        rec = find(d, rid)
        if rec is None:
            return {"ok": False, "said": "That response is no longer on the list."}
        if rec.get("status") == "sent":
            return {"ok": True, "said": f"Sent already, at {rec.get('sent_at')}."}
        if rec.get("status") == "sending" and time.time() - float(rec.get("sending_ts") or 0) < SENDING_FOR:
            return {"ok": False, "said": "That one is being sent already."}
        if edits:
            _apply(rec, {k: v for k, v in edits.items() if k in FIELDS})
        rec["unsure"] = []                        # his press of Send is his word on what he saw
        try:
            filled = answers(rec)
        except ValueError as e:
            rec["status"] = _status(rec)
            save(d)
            return {"ok": False, "said": str(e)}
        rec.update(status="sending", sending_ts=time.time())
        save(d)
    try:
        result, payload = (ask or _bridge_ask)("form_fill", answers=filled, submit=True)
    except Exception as e:                        # the dashboard or the work PC away
        result, payload = {"ok": False, "detail": f"The work PC couldn't be asked ({e})."}, {}
    ok = bool(result.get("ok")) and bool((payload or {}).get("submitted"))
    said = str(result.get("detail") or "")[:300]
    with locked():
        d = load()
        rec = find(d, rid)
        if rec is not None:
            rec["note"] = said
            if ok:
                rec.update(status="sent", sent_at=datetime.now().strftime("%d/%m/%Y %H:%M"))
            else:
                rec["status"] = "failed"
            save(d)
    names = " / ".join(rec["hauliers"]) if rec else ""
    return {"ok": ok, "said": (f"Rejection form sent: {names}, {' / '.join(rec['orders'])}." if ok and rec else
                               "Rejection form not sent: " + (said or "no answer from the work PC."))}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "show":
        for r in load()["items"]:
            print(f"{r.get('id')}  {r.get('status'):8} {' / '.join(r.get('orders') or [])}  "
                  f"{', '.join(r.get('hauliers') or [])}  {r.get('reason')}  {gaps(r) or ''}")
        return 0
    if cmd == "refresh":
        try:
            import win32com.client
            ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        except Exception as e:
            print(json.dumps({"ok": False, "said": f"Outlook couldn't be reached ({e})."}))
            return 1
        n = refresh(ns)
        print(json.dumps({"ok": True, "said": f"{n} rejection(s) found in replies." if n else "No new rejections."}))
        return 0
    if cmd == "add":
        data = json.loads(argv[2]) if len(argv) > 2 else {}
        orders = data.get("orders") or []
        orders = orders if isinstance(orders, list) else re.split(r"[\s,;/&+]+", str(orders))
        hauliers = data.get("hauliers") or []
        reason = str(data.get("reason") or "")
        if not [o for o in orders if str(o).strip()] or not hauliers or reason not in REASONS:
            print(json.dumps({"ok": False, "said": "A no needs the order, who said it and why."}))
            return 1
        rec = make(orders, hauliers if isinstance(hauliers, list) else [hauliers], reason, said=data.get("said") or "",
                   source="added", given={k: v for k, v in data.items() if k not in ("orders", "hauliers", "reason")})
        if rec["product"] == "S&C":
            print(json.dumps({"ok": False, "said": "S&C goes its own way - not on this form."}))
            return 1
        with locked():
            d = load()
            got = add(d, rec)
            save(d)
        print(json.dumps({"ok": True, "said": ("On the rejection card: " + " / ".join(rec["orders"]) +
                                               (" - ready to send." if got and got["status"] == "ready" else
                                                " - it needs a look before it goes.")) if got else
                          "That no is on the card already."}))
        return 0
    if cmd in ("edit", "drop", "send"):
        rid = argv[2] if len(argv) > 2 else ""
        edits = json.loads(argv[3]) if len(argv) > 3 else {}
        if cmd == "send":
            out = send(rid, edits if isinstance(edits, dict) else {})
            print(json.dumps(out))
            return 0 if out["ok"] else 1
        with locked():
            d = load()
            rec = find(d, rid)
            if rec is None or rec.get("status") in ("sent", "sending"):
                print(json.dumps({"ok": False, "said": "That response can't be changed now."}))
                return 1
            if cmd == "drop":
                rec["status"] = "dropped"
            else:
                _apply(rec, {k: v for k, v in (edits or {}).items() if k in FIELDS})
                rec["status"] = _status(rec)
            save(d)
        print(json.dumps({"ok": True, "said": "Taken off the rejection card." if cmd == "drop" else
                          ("Changed - ready to send." if rec["status"] == "ready" else "Changed.")}))
        return 0
    if cmd == "auto":
        on = len(argv) > 2 and argv[2] == "on"
        with locked():
            d = load()
            d["auto"] = on
            save(d)
        print(json.dumps({"ok": True, "said": "Rejection forms: complete ones now go by themselves." if on else
                          "Rejection forms: each one waits for your Send."}))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
