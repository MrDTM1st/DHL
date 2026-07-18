"""Turn a customer's free-text reply into the STRUCTURED delivery details CTMS
needs - so the booking automation never has to guess.

Everything here is driven by evidence mined from ~1,470 real replies in the
mailbox (see the priors below), plus Delali's own rules:
  * CTMS needs TWO times (earliest + latest). A single time is the NORM (73%),
    so it is expanded by +2 hours.
  * "yes" to offloading means HIAB - that's policy, not a guess.
  * A date range means: consolidate if we can, otherwise take the LATEST date
    ("the further away the safer it is").

Anything the parser is sure about fills silently; anything ambiguous is marked
amber for a one-click confirm on the dashboard, and every confirmation is
remembered in _details_learned.json so the same wording is never guessed twice.
"""
import os, re, json
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LEARNED = os.path.join(HERE, "_details_learned.json")

HIGH, AMBER = "high", "amber"      # confidence: fill silently vs ask to confirm

# Priors from the mined history - used only when the wording is ambiguous.
PRIOR_OFFLOAD = "HIAB"             # 78% of all specified answers
PRIOR_ARTIC = "yes"                # 84% of the split question's answers
PRIOR_PTS = "no"                   # ~90% "no", and it appears on non-rail too

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAYNAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


# ---------------------------------------------------------------- learned store
def _load_learned():
    try:
        return json.load(open(LEARNED, encoding="utf-8"))
    except Exception:
        return {}


def _save_learned(d):
    tmp = LEARNED + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), indent=1, sort_keys=True)
    os.replace(tmp, LEARNED)


def _key(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())[:120]


def learn(field, raw, value):
    """Remember that this exact wording means this value - called when Delali
    confirms or corrects a parsed field, so it's never guessed again."""
    d = _load_learned()
    d.setdefault(field, {})[_key(raw)] = value
    _save_learned(d)
    return value


def recall(field, raw):
    return _load_learned().get(field, {}).get(_key(raw))


# ---------------------------------------------------------------- small helpers
def _clean(s):
    return re.sub(r"\s{2,}", " ", str(s or "").replace("–", "-").replace("—", "-")).strip()


def _lev1(a, b):
    """True if a is within one edit of b - catches haib/hiad/hi ab for 'hiab'.
    Includes an adjacent SWAP, because 'haib' is the commonest typo of all."""
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return True
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(diff) == 1:
            return True
        return (len(diff) == 2 and diff[1] == diff[0] + 1
                and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    lo, hi = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(hi)):
        if hi[:i] + hi[i + 1:] == lo:
            return True
    return False


_DATE_TOKEN = re.compile(r"\b\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}\b")
_ORDINAL_DATE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"(?:\s+(?:19|20)\d{2})?\b", re.I)   # trailing YEAR only - must not eat "2300" (a time)


def _strip_dates(s):
    """Remove date tokens before hunting for times, so 01/03/2026 can't be read
    as 20:26 and '19th feb 2300' keeps only the 2300."""
    s = _DATE_TOKEN.sub(" ", s)
    s = _ORDINAL_DATE.sub(" ", s)
    return s


# ---------------------------------------------------------------- times
_TIME_PATS = [
    re.compile(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\s*(am|pm)?\b", re.I),   # 22:00, 23.30
    re.compile(r"\b(\d{1,2})\s*(am|pm)\b", re.I),                      # 10am, 12am
    re.compile(r"(?<![\d/\-.])(\d{4})(?:\s*hrs)?(?![\d/\-])", re.I),   # 2200, 0400
]


def _to_hm(h, m, ap):
    h, m = int(h), int(m or 0)
    if ap:
        ap = ap.lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    if h > 23 or m > 59:
        return None
    return f"{h:02d}:{m:02d}"


def find_times(text):
    """Every time in the text, in order. Dates are stripped first, and matches
    may not OVERLAP - otherwise "10:00am" reads as both 10:00 and 00am(=12:00)
    and a single time looks like a range."""
    s = _strip_dates(_clean(text).lower())
    spans, hits = [], []
    for i, pat in enumerate(_TIME_PATS):          # colon form first - it wins ties
        for m in pat.finditer(s):
            if any(m.start() < b and m.end() > a for a, b in spans):
                continue
            if i == 0:
                t = _to_hm(m.group(1), m.group(2), m.group(3))
            elif i == 1:
                t = _to_hm(m.group(1), 0, m.group(2))
            else:
                v = m.group(1)
                t = _to_hm(v[:2], v[2:], None)
            if t:
                spans.append((m.start(), m.end()))
                hits.append((m.start(), t))
    return [t for _, t in sorted(hits)]


def plus_hours(t, hours=2):
    h, m = map(int, t.split(":"))
    return f"{(h + hours) % 24:02d}:{m:02d}"     # wraps past midnight (23:00 -> 01:00)


def parse_time_window(text):
    """-> (earliest, latest, confidence). CTMS needs both; a single time is the
    common case (73%) and is expanded by +2 hours per Delali's rule."""
    ts = find_times(text)
    if not ts:
        return None, None, AMBER
    if len(ts) >= 2:
        return ts[0], ts[1], HIGH
    return ts[0], plus_hours(ts[0], 2), HIGH


# ---------------------------------------------------------------- dates
def find_dates(text, default_year=None):
    """Every date in the text as date objects (dd/mm first - UK)."""
    s = _clean(text).lower()
    year0 = default_year or datetime.now().year
    out = []
    for m in _DATE_TOKEN.finditer(s):
        parts = re.split(r"[/.-]", m.group(0).replace(" ", ""))
        try:
            d, mo = int(parts[0]), int(parts[1])
            y = int(parts[2]) if len(parts) > 2 else year0
            if y < 100:
                y += 2000
            out.append(datetime(y, mo, d).date())
        except Exception:
            continue
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?\s*(\d{4})?\b", s):
        mo = MONTHS.get(m.group(2)[:3])
        if not mo:
            continue
        try:
            out.append(datetime(int(m.group(3) or year0), mo, int(m.group(1))).date())
        except Exception:
            continue
    return sorted(set(out))


def pick_date(dates, consolidatable=None):
    """Delali's rule for a range/options: consolidate if we can, otherwise take
    the LATEST ('the further away the safer it is')."""
    if not dates:
        return None, AMBER
    if len(dates) == 1:
        return dates[0], HIGH
    for d in dates:                       # prefer a day we can share a vehicle on
        if consolidatable and d in consolidatable:
            return d, HIGH
    return max(dates), HIGH


def parse_date(text, consolidatable=None):
    """-> (date, flexible, options, confidence)."""
    ds = find_dates(text)
    s = _clean(text).lower()
    vague = bool(re.search(r"flexible|any\s*day|any\s*date|asap|whenever|tbc", s))
    dayrange = bool(re.search(r"(%s)\w*\s*(?:-|to|till|until)\s*(%s)" %
                              ("|".join(d[:3] for d in DAYNAMES), "|".join(d[:3] for d in DAYNAMES)), s))
    if not ds:
        # e.g. "asap - monday to friday": flexible but no concrete date to take
        return None, (vague or dayrange), [], AMBER
    d, conf = pick_date(ds, consolidatable)
    flexible = vague or dayrange or len(ds) > 1
    return d, flexible, ds, (conf if not vague else AMBER)


# ---------------------------------------------------------------- offloading
def parse_offloading(text, product_type=None):
    """-> (value, confidence). 'yes' means HIAB - Delali's policy, so it's HIGH
    confidence, not a guess. Handles haib/hiad/hi ab/moffet/moffatt spellings."""
    raw = _clean(text)
    hit = recall("offloading", raw)
    if hit:
        return hit, HIGH
    # the templates embed their own prompt ("hiab/moffett?") - if anything follows
    # the last "?", that's the actual answer, not the menu we offered them
    if "?" in raw and raw.rsplit("?", 1)[-1].strip():
        raw = raw.rsplit("?", 1)[-1].strip()
    s = raw.lower()
    flat = re.sub(r"[^a-z]", "", s)
    moff = "moff" in flat
    hiab = "hiab" in flat or any(_lev1(t, "hiab") for t in re.findall(r"[a-z]{3,5}", flat))
    # explicit "no" / site handles it - check before the keywords so "no hiab" reads right
    if re.match(r"^\s*(no\b|none\b|not required|nil\b)", s) or "telehandler" in s or "site offload" in s:
        return "SITE/NONE", HIGH
    if moff and hiab:
        return "BOTH", AMBER                       # they named both - ask which
    if moff:
        return "MOFFETT", HIGH
    if hiab:
        return "HIAB", HIGH
    if re.match(r"^\s*(yes|y\b|yeah|yep|please|required|req\b)", s):
        # bare yes -> HIAB by policy; sleepers lean Moffett in the history
        if product_type == "sleepers":
            return "MOFFETT", AMBER
        return "HIAB", HIGH
    return None, AMBER


# ---------------------------------------------------------------- site access
_YES = re.compile(r"\b(yes|y|yep|yeah|can|will fit|suitable|fine|ok)\b")
_NO = re.compile(r"\b(no|n|not|cannot|can't|cant|unable)\b")


def _yesno(clause):
    if _NO.search(clause) and not re.search(r"no\s*(?:need|rear)", clause):
        return "no"
    if _YES.search(clause):
        return "yes"
    if _NO.search(clause):
        return "no"
    return None


def parse_access(text):
    """The team template merges 'can an artic fit / does it need rear steer' into
    ONE line, which is the single biggest source of mush ('yes/yes',
    'arctic yes, rear steer no'). Split it back into two fields.
    -> (artic, rear_steer, vehicle, confidence)"""
    raw = _clean(text)
    hit = recall("access", raw)
    if hit:
        return hit.get("artic"), hit.get("rear"), hit.get("vehicle"), HIGH
    s = raw.lower()
    vehicle = None
    mv = re.search(r"\b(rigid|18\s*t|7\.5\s*t|flat\s*bed|small\s*artic)", s)
    if mv:
        vehicle = mv.group(1).replace(" ", "")
    clauses = [c for c in re.split(r"[,./;]|\band\b", s) if c.strip()]
    artic = rear = None
    for c in clauses:
        if "rear" in c:
            rear = _yesno(c) or "yes"          # "rear steer" alone means it's needed
        elif re.search(r"artic|arctic|lorr|vehicle|access", c):
            artic = _yesno(c)
    # "yes/yes" - no keywords at all: the template asks artic first, rear second
    if artic is None and rear is None and len(clauses) == 2:
        a, r = _yesno(clauses[0]), _yesno(clauses[1])
        if a and r:
            artic, rear = a, r
    if artic is None:
        artic = _yesno(s)
    if artic is None and vehicle:
        artic = "no"                            # "small rigids req" implies no artic
    if re.search(r"\bno\b.*\b(artic|arctic)\b|\b(artic|arctic)\b.*\bno\b", s) and vehicle:
        artic = "no"
    conf = HIGH if (artic and rear) else AMBER
    return artic, rear, vehicle, conf


# ---------------------------------------------------------------- pts / w3w
def parse_pts(text, whole_reply=""):
    """PTS shows up on non-rail loads too and leaks into other fields
    ('moffet (no pts this time)'), so scan the whole reply as a fallback."""
    for src in (text, whole_reply):
        s = _clean(src).lower()
        if not s:
            continue
        if re.search(r"\bno\s*pts|pts\s*not\s*(?:required|needed)|^\s*no\b", s):
            return "no", HIGH
        if re.search(r"\bpts\b", s):
            if re.search(r"pts\s*(?:is\s*)?(?:required|needed)|require\s*pts|\byes\b", s):
                return "yes", HIGH
            return "yes", AMBER
        if re.match(r"^\s*(yes)\b", s):
            return "yes", HIGH
    # NEVER default this. PTS is a safety certification - ~90% of answers are
    # "no", but assuming it could send a driver to a live-track site uncertified.
    # Unstated means unknown, and gets chased on rail orders (see missing()).
    return None, AMBER


_W3W = re.compile(r"(?:///|w3w\.co/)?\b([a-z]{3,})[.,]\s*([a-z]{3,})[.,]\s*([a-z]{3,})\b", re.I)


def parse_w3w(text):
    """-> (///a.b.c, confidence). Handles ///words, comma-separated, and
    w3w.co URLs; an address-only answer returns None so we can chase it."""
    s = _clean(text)
    m = re.search(r"w3w\.co/([a-z]+)\.([a-z]+)\.([a-z]+)", s, re.I)
    if not m:
        m = _W3W.search(s)
    if m:
        return "///" + ".".join(g.lower() for g in m.groups()), HIGH
    return None, AMBER


_PHONE = re.compile(r"(?:\+44|0)\s*\d[\d\s]{8,14}")


def parse_contact(text):
    s = _clean(text)
    ph = _PHONE.search(s)
    phone = re.sub(r"\s+", "", ph.group(0)) if ph else None
    name = _clean(s[:ph.start()] if ph else s).strip(" -,:")
    return (name or None), phone, (HIGH if (name and phone) else AMBER)


# ---------------------------------------------------------------- the templates
FIELD_PATTERNS = [
    ("date",     r"delivery dates?\s*:"),
    ("time",     r"delivery times?\s*:"),
    ("access",   r"site access\s*:"),
    ("offload",  r"offloading\s*:"),
    ("notes",    r"additional information\s*/?\s*driver requirm?e?ments?\s*:"),
    ("w3w",      r"confirm delivery address[^:\n]*:"),
    ("datetime", r"date\s*(?:&|and)\s*time of delivery\?"),
    ("contact",  r"who will be the contact for (?:the )?delivery\?"),
    ("altcontact", r"alternative (?:delivery )?contacts?\??\s*:?"),
    ("offload",  r"do we need to bring our own offloading\?(?:\s*hiab or moff?ett?\?)?"),
    ("artic",    r"can artic'?s?\s*access (?:the )?site\?"),
    ("rear",     r"is rear steer required\?"),
    ("pts",      r"does the driver (?:require|need) pts[^?\n]*\?"),
    ("w3w",      r"what3words location\?"),
]
_PROMPT_STRIP = [r"^\([^)]*\)\s*", r"^hiab\s*(?:/|or)\s*moff\w*\s*\??\s*",
                 r"^\(?can an? art?ic[^?]*\?\s*"]   # moff\w* covers moffett/moffatt/moffit


def extract_fields(body):
    """Pull the labelled values out of either template format."""
    out = {}
    low = str(body or "").lower()
    for key, pat in FIELD_PATTERNS:
        for m in re.finditer(pat, low, re.I):
            line = low[m.end():].split("\n", 1)[0].strip(" \t:-")
            for p in _PROMPT_STRIP:
                line = re.sub(p, "", line, flags=re.I).strip()
            line = _clean(line).strip(" \t:-")
            if line and len(line) < 200 and key not in out:
                out[key] = line
    return out


def parse_reply(body, product_type=None, consolidatable=None):
    """Free-text reply -> the structured details CTMS needs, each with a
    confidence. AMBER fields are the ones to put in front of Delali."""
    f = extract_fields(body)
    whole = str(body or "")
    d = {}

    dtxt = f.get("date") or f.get("datetime") or ""
    date, flexible, options, dconf = parse_date(dtxt, consolidatable)
    d["date"] = {"value": date.strftime("%d/%m/%Y") if date else None,
                 "flexible": flexible, "options": [x.strftime("%d/%m/%Y") for x in options],
                 "confidence": dconf, "raw": dtxt}

    ttxt = f.get("time") or f.get("datetime") or ""
    lo, hi, tconf = parse_time_window(ttxt)
    d["time"] = {"earliest": lo, "latest": hi, "confidence": tconf, "raw": ttxt,
                 "expanded": bool(lo and hi and len(find_times(ttxt)) == 1)}

    otxt = f.get("offload", "")
    ov, oconf = parse_offloading(otxt, product_type)
    d["offloading"] = {"value": ov, "confidence": oconf, "raw": otxt}

    if "access" in f:
        a, r, veh, aconf = parse_access(f["access"])
    else:
        a = _yesno(f.get("artic", "")) if f.get("artic") else None
        r = _yesno(f.get("rear", "")) if f.get("rear") else None
        veh = None
        mv = re.search(r"\b(rigid|18\s*t|7\.5\s*t)", f.get("artic", ""), re.I)
        if mv:
            veh = mv.group(1)
        aconf = HIGH if (a and r) else AMBER
    d["artic_access"] = {"value": a, "confidence": HIGH if a else AMBER, "raw": f.get("access") or f.get("artic", "")}
    d["rear_steer"] = {"value": r, "confidence": HIGH if r else AMBER, "raw": f.get("access") or f.get("rear", "")}
    d["vehicle"] = {"value": veh, "confidence": HIGH if veh else AMBER, "raw": f.get("access", "")}

    pv, pconf = parse_pts(f.get("pts", ""), whole)
    d["pts"] = {"value": pv, "confidence": pconf, "raw": f.get("pts", "")}

    wv, wconf = parse_w3w(f.get("w3w", ""))
    d["what3words"] = {"value": wv, "confidence": wconf, "raw": f.get("w3w", "")}

    cn, cp, cconf = parse_contact(f.get("contact") or f.get("altcontact") or "")
    d["contact"] = {"name": cn, "phone": cp, "confidence": cconf,
                    "raw": f.get("contact") or f.get("altcontact") or ""}

    d["notes"] = {"value": f.get("notes") or None, "confidence": HIGH, "raw": f.get("notes", "")}
    return d


# fields that must be filled before an order can actually be booked on CTMS
REQUIRED = ("date", "time", "offloading", "artic_access", "what3words", "contact")
LABELS = {"date": "delivery date", "time": "delivery time", "offloading": "offloading (HIAB/Moffett)",
          "artic_access": "artic access", "rear_steer": "rear steer", "what3words": "What3Words",
          "contact": "site contact", "pts": "PTS", "vehicle": "vehicle size"}


def missing(details, product_type=None):
    """What's still needed - so the chaser asks for exactly these, instead of
    'can I get a reply?'. PTS is only chased on RAIL orders (Delali's rule),
    but it is never assumed on any order."""
    need = list(REQUIRED) + (["pts"] if product_type == "rails" else [])
    out = []
    for k in need:
        v = details.get(k) or {}
        got = v.get("value") or v.get("earliest") or v.get("name")
        if not got:
            out.append(LABELS.get(k, k))
    return out


def amber(details):
    """Fields parsed but not certain - these are the one-click confirms whose
    answers get fed back through learn()."""
    return [LABELS.get(k, k) for k, v in details.items()
            if isinstance(v, dict) and v.get("confidence") == AMBER
            and (v.get("value") or v.get("earliest") or v.get("name"))]
