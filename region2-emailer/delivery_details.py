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
    as 20:26 and '19th feb 2300' keeps only the 2300. What is cut leaves a ';'
    rather than a bare space, so the 'by' of 'by 20/11/2026 8am' is not later
    read as 'by 8am'."""
    s = _DATE_TOKEN.sub(" ; ", s)
    s = _ORDINAL_DATE.sub(" ; ", s)
    return s


# A UK phone number - 0 or +44 (and a "(0)") then 9-10 more digits, single
# spaces or hyphens between them - is cut before hunting for times, the way
# dates are: "Contact Dave on 0114 234 5678" read the 0114 as 01:14. It must
# take a whole run of digit groups, so a 4-digit time that runs into a number
# ("0800 07700 900123") stays a time; a group that IS a time ("8am", "10:00",
# "0800hrs") is never part of one; and 0800-1600 is far too short to be one.
_NOT_A_TIME = r"(?!\d+\s*(?:am|pm|hrs?)\b|\d+[:.]\d)\d"
_PHONE_NUM = re.compile(r"(?<!\d)(?<!\d[:.])(?:\+44\s?(?:\(0\)\s?)?|0)(?:\d|[\s-]" + _NOT_A_TIME + r"){9,10}"
                        r"(?!\d|[:.]\d|[\s-]" + _NOT_A_TIME + ")")


# ---------------------------------------------------------------- times
_TIME_PATS = [
    # 22:00, 23.30, and 22:30hrs. The trailing \b used to sit between "0" and
    # "h", which are both word characters, so "22:30hrs" matched nothing at all
    # and the time was lost - while pattern 3 below already honoured an "hrs"
    # suffix on the bare form. The two guards replace what \b was really doing:
    # (?!\.?\d) keeps rail dimensions out (18.288m, 22.710m read as 18:28,
    # 22:71 without it) and (?![a-z]) keeps other unit letters out.
    re.compile(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\s*(am|pm)?(?:\s*(?:hrs?|hours))?"
               r"(?!\.?\d)(?![a-z])", re.I),
    re.compile(r"\b(\d{1,2})\s*(am|pm)\b", re.I),                      # 10am, 12am
    # 2200, 0400 - but not part of a word: an order's "RD1234" or "2000kg" is no time
    re.compile(r"(?<![\d/\-.a-z])(\d{4})(?:\s*hrs)?(?![\d/\-a-z])", re.I),
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


def _time_hits(text):
    """(text searched, [(start, end, "HH:MM", am/pm as typed or None)]) - the
    times find_times returns, with where each sat and whether it said am/pm."""
    s = _PHONE_NUM.sub(" ; ", _strip_dates(_clean(text).lower()))
    spans, hits = [], []
    for i, pat in enumerate(_TIME_PATS):          # colon form first - it wins ties
        for m in pat.finditer(s):
            if any(m.start() < b and m.end() > a for a, b in spans):
                continue
            if i == 0:
                ap = m.group(3)
                t = _to_hm(m.group(1), m.group(2), ap)
            elif i == 1:
                ap = m.group(2)
                t = _to_hm(m.group(1), 0, ap)
            else:
                v, ap = m.group(1), None
                t = _to_hm(v[:2], v[2:], None)
            if t:
                spans.append((m.start(), m.end()))
                hits.append((m.start(), m.end(), t, ap))
    return s, sorted(hits, key=lambda h: h[0])


def find_times(text):
    """Every time in the text, in order. Dates and phone numbers are stripped
    first, and matches may not OVERLAP - otherwise "10:00am" reads as both
    10:00 and 00am(=12:00) and a single time looks like a range."""
    return [t for _, _, t, _ in _time_hits(text)[1]]


def plus_hours(t, hours=2):
    h, m = map(int, t.split(":"))
    return f"{(h + hours) % 24:02d}:{m:02d}"     # wraps past midnight (23:00 -> 01:00)


# A lone time that is the LATEST they can take it - "no later than 10am",
# "before 10am", "by 10:00", "10am latest", "10:00 at the latest". "after" and
# "from" are not here: those are the earliest, which is how a lone time reads.
_LATEST_BEFORE = re.compile(r"(?:\b(?:no|not)\s+later\s+than|\b(?:before|by|until|till|latest))\s*:?\s*$")
_LATEST_AFTER = re.compile(r"\s*(?:at\s+the\s+)?latest\b")


def parse_time_window(text):
    """-> (earliest, latest, confidence). CTMS needs both; a single time is the
    common case (73%) and is expanded by +2 hours per Delali's rule."""
    s, hits = _time_hits(text)
    if not hits:
        return None, None, AMBER
    if len(hits) >= 2:
        lo, hi, hi_ap = hits[0][2], hits[1][2], hits[1][3]
        # "7:30 - 3:30", "8:00 till 4:00": a 12-hour end with no pm on it. Taken
        # as written that is a 20-hour window into the next day. A morning start
        # and an end before it with no am/pm: the end is pm. 00:xx is a 24-hour
        # time, never a 12-hour one, so it is not moved.
        if not hi_ap and "01:00" <= hi < lo < "12:00":
            hi = plus_hours(hi, 12)
        # Still ending at or before it starts, and not a night shift (22:00-04:00):
        # it is not a window we can read - "Thursday 12.11 8am" is 12:11-08:00.
        return lo, hi, (AMBER if hi <= lo and lo < "18:00" else HIGH)
    start, end, t, _ = hits[0]
    if _LATEST_BEFORE.search(s[:start]) or _LATEST_AFTER.match(s[end:]):
        # the latest, not the earliest - Delali's 2 hours go in front of it
        return plus_hours(t, -2), t, HIGH
    return t, plus_hours(t, 2), HIGH


# ---------------------------------------------------------------- dates
def _today():
    return datetime.now().date()


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
    # the year is 19xx/20xx only, as in _ORDINAL_DATE - any 4 digits made "20th nov 2200" the year 2200 and
    # "10th November 0900" the year 900, when those digits are the delivery TIME
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?\s*((?:19|20)\d{2})?\b", s):
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
    """-> (date, flexible, options, confidence). A day already gone is no delivery they are asking for: a footer's "20
    years' service from 11 August 2003" moved an order to 2003, and the stale sweep then took it off the tracker (02/11)."""
    ds = [x for x in find_dates(text) if x >= _today()]
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
_NEGATED = re.compile(r"\b(?:not|no|don[’']?t|doesn[’']?t|won[’']?t|isn[’']?t|aren[’']?t)\s+(?:[a-z]+\s+){0,2}?"
                      r"(?:need|needed|require|required|necessary)\b|\bno\s+need\b")
_OTHER_FIELD = re.compile(r"\bpts\b|rear\s*steer|\bar(?:c)?tics?\b")


def _named(s):
    """(moffett named, hiab named) - haib/hiad/hi ab count as hiab."""
    flat = re.sub(r"[^a-z]", "", s)
    return "moff" in flat, "hiab" in flat or any(_lev1(t, "hiab") for t in re.findall(r"[a-z]{3,5}", flat))


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
    # Delete OUR OWN menu before any keyword test. The split above only helps
    # when the menu precedes the last "?", and in the template it does not - the
    # line reads "...offloading? (HIAB or Moffet) yes moffet please", so the
    # menu survives and both keywords are found. That did not merely invent a
    # value where the contact left the line blank: it OVERRODE real answers.
    # "(HIAB or Moffet) yes moffet please" came back BOTH instead of MOFFETT,
    # and "(HIAB or Moffet) No - Loose ballast being Tipped" came back BOTH
    # instead of SITE/NONE, on a load that is tipped and needs neither.
    s = re.sub(r"[\(\[]?\s*hiab\s*(?:/|or|,|&|and)\s*moff\w*\s*[\)\]]?\s*\??", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not re.search(r"[a-z0-9]", s):
        return None, AMBER          # nothing but our own menu - they never answered
    moff, hiab = _named(s)
    # explicit "no" / site handles it - check before the keywords so "no hiab" reads right
    if re.match(r"^\s*(no\b|none\b|not required|nil\b)", s) or "telehandler" in s or "site offload" in s:
        return "SITE/NONE", HIGH
    # A negation further in - "HIAB not required", "We don't need a hiab", "Moffett not needed - forklift on
    # site" - names the kit they do NOT want, and the keyword tests below read it as the answer. Never confident:
    # SITE/NONE to confirm when every keyword they named is ruled out, nothing when it is mixed ("hiab, no
    # moffett needed"). A clause about PTS, rear steer or the artic is not about offloading and is skipped.
    neg = [_named(c) for c in re.split(r"[,;.!?()/]|\s-+|-+\s|\b(?:and|but)\b", s)
           if _NEGATED.search(c) and (any(_named(c)) or not _OTHER_FIELD.search(c))]
    if neg:
        if (moff or hiab) and (not moff or any(m for m, _ in neg)) and (not hiab or any(h for _, h in neg)):
            return "SITE/NONE", AMBER
        return None, AMBER
    if moff and hiab:
        return "BOTH", AMBER                       # they named both - ask which
    if moff:
        return "MOFFETT", HIGH
    if hiab:
        return "HIAB", HIGH
    if re.match(r"^\s*(yes|y\b|yeah|yep|please|required|req\b)", s):
        # bare yes -> HIAB, whatever the load: "if someone says, do we need to bring our own offloading? And then
        # they say yes, you always default to a HIAB. Not a Moffett. Unless they explicitly say so" - Delali,
        # 01/11/2026. Sleepers used to lean Moffett here from the history - a guess that sent a sleeper job to
        # Moffett firms only.
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
    # First, the answer typed against OUR question, wherever it sits in the
    # thread. Anchoring on the question is the only reliable read: a reply
    # answers eight of them, and a bare "yes" belonging to one of the others is
    # not about PTS. Measured over 95 replies that answered explicitly, the
    # whole-reply fallback got 7 wrong, every one a "no" read as "yes" because
    # the \byes\b below matched the artic-access or rear-steer answer above it.
    anchored = re.search(r"(?:needs?|requires?)\s*pts[^?\n]*\??[ \t]*([^\n]{0,40})",
                         _clean(whole_reply or text).lower())
    if anchored:
        stated = anchored.group(1).strip(" \t:.-")
        if re.match(r"^(no\b|n/a\b|n\b|not\b|none\b)", stated):
            return "no", HIGH
        if re.match(r"^(yes\b|y\b)", stated):
            return "yes", HIGH

    for i, src in enumerate((text, whole_reply)):
        s = _clean(src).lower()
        if not s:
            continue
        if re.search(r"\bno\s*pts|pts\s*not\s*(?:required|needed)|^\s*no\b", s):
            return "no", HIGH
        if re.search(r"\bpts\b", s):
            # a loose "yes" counts only in the PTS field's OWN text, never in
            # the whole reply - that is where those seven wrong answers came from
            loose = r"|\byes\b" if i == 0 else ""
            if re.search(r"pts\s*(?:is\s*)?(?:required|needed)|require\s*pts" + loose, s):
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
_PHONE_LABEL = r"(?:m|t|p|w|tel|telephone|mob|mobile|phone|cell|direct|dd|office|number|no|num)\.?"
_MOBILE = re.compile(r"^(?:\+44|0)7")
_FROM_LINE = re.compile(r"^\s*from:\s*(.+?)\s*(?:<[^>\n]*>)?\s*$", re.I | re.M)   # a quoted mail's From:
# leading words that aren't part of a name: "contact delivery will be darren..."
_FILLER = re.compile(
    r"^\W*(?:the|a|our|site|delivery|for|on|is|are|will\s+be|contacts?|person|name|"
    r"alternative|alt|please|to|of)\b\W*", re.I)


def _strip_filler(s):
    prev = None
    while s and s != prev:
        prev = s
        s = _FILLER.sub("", s).strip()
    return s


def parse_contact(text):
    s = _clean(text)
    ph = _PHONE.search(s)
    phone = re.sub(r"\s+", "", ph.group(0)) if ph else None
    name = _strip_filler(_clean(s[:ph.start()] if ph else s).strip(" -,:"))
    # "M 07700 900123" or "Sam | Mob: 07..." - a footer's label in front of its number is not a name
    name = re.sub(r"(?:^|[\s|/]+)" + _PHONE_LABEL + r"\s*:?\s*$", "", name, flags=re.I).strip(" -,:|/")
    return (name or None), phone, (HIGH if (name and phone) else AMBER)


def sender_name(sender):
    """Outlook's display name as the person's name: 'Example, Sam' -> 'Sam Example', '(Company)' dropped,
    an address's own part ('sam.example@...') -> 'Sam Example'."""
    s = re.sub(r"\([^)]*\)", "", str(sender or "")).strip(" '\"")
    if "@" in s:
        s = re.sub(r"[._]+", " ", s.split("@", 1)[0]).title()
    elif "," in s:
        last, first = (p.strip() for p in s.split(",", 1))
        s = f"{first} {last}"
    return " ".join(s.split()) or None


def sender_phone(body, sender):
    """The sender's own number: from what they wrote and their footer first (a mobile over a landline), else
    from an earlier mail of theirs quoted further down. Never a number from anyone else's mail in the thread -
    our own signature is quoted in every reply."""
    s = str(body or "")
    toks = (sender_name(sender) or "").lower().split()
    parts = [_top(s)]
    for m in _FROM_LINE.finditer(s):
        if toks and all(t in m.group(1).lower() for t in toks):      # their own earlier mail
            nxt = _FROM_LINE.search(s, m.end())
            parts.append(s[m.end():nxt.start() if nxt else len(s)])
    for part in parts:
        phones = [re.sub(r"\s+", "", p.group(0)) for p in _PHONE.finditer(part)]
        if phones:
            return next((p for p in phones if _MOBILE.match(p)), phones[0])
    return None


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


_QUOTE_MARKERS = ("-----original message-----", "\nfrom:", "\nsent:", "________",
                  " wrote:", "on behalf of")


# A sign-off on a line of its own, at most a name after it: "Thanks," "Kind regards" "Regards Sam". "Thanks for that,
# deliver on the 12th" carries on, and so does a "Thanks Sam" with nothing typed above it - that's a greeting.
SIGN_OFF = re.compile(r"^[ \t]*(?:(?:kind|best|warm|many)\s+(?:regards|thanks)|regards|thanks|thank\s+you|cheers)\b"
                      r"[ \t,.!-]*(?:\w+[ \t,.!]*)?\r?$", re.M | re.I)


def above_sign_off(text):
    """What they typed above their sign-off - a signature's dates and numbers are nobody's delivery."""
    t = str(text or "")
    for m in SIGN_OFF.finditer(t):
        if re.sub(r"\bOFFICIAL(?:-SENSITIVE)?\b", "", t[:m.start()]).strip():
            return t[:m.start()]
    return t


def _top(body):
    """Just the text they typed, above any quoted original."""
    s = str(body or "")
    low, cut = s.lower(), len(s)
    for mk in _QUOTE_MARKERS:
        i = low.find(mk)
        if 0 <= i < cut:
            cut = i
    return s[:cut]


def _prose(body):
    """Plenty of people ignore the template and just write it out ("hiab will be
    required / arctics can access site / no pts required"). Find each field in
    the prose so those replies aren't a total miss."""
    t = _top(body)
    out = {}
    for line in re.split(r"[\n;]", t):
        l = line.strip()
        low = l.lower()
        if not low:
            continue
        if "offload" in low or "hiab" in low or "moff" in low:
            out.setdefault("offload", l)
        if re.search(r"ar[c]?tic", low):
            out.setdefault("artic", l)
        if "rear steer" in low:
            out.setdefault("rear", l)
        if re.search(r"\bpts\b", low):
            out.setdefault("pts", l)
        # "what three words" and "what 3 words" contain none of the three
        # literals this used to test, so those lines were never handed to
        # parse_w3w at all - it only ever saw them when the writer also typed
        # ///. parse_w3w itself reads them fine.
        if re.search(r"what\s*(?:3|three)\s*words?|\bw\s*3\s*w\b|///", low):
            out.setdefault("w3w", l)
        if _PHONE.search(l):
            key = "altcontact" if re.search(r"alternat|\balt\b|second|backup", low) else "contact"
            out.setdefault(key, l)
    out.setdefault("datetime", above_sign_off(t))     # dates/times hunted across what they typed, not their footer
    return out


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


def parse_reply(body, product_type=None, consolidatable=None, sender=None):
    """Free-text reply -> the structured details CTMS needs, each with a
    confidence. AMBER fields are the ones to put in front of Delali.
    sender is the reply's From name - the contact when the reply names nobody."""
    labelled = extract_fields(body)
    prose = _prose(body)
    f = {k: (labelled.get(k) or prose.get(k) or "")            # template wins, prose fills gaps
         for k in set(labelled) | set(prose)}
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
        rtxt = f.get("rear", "")
        # "rear steer required" has no yes/no in it - naming it at all means needed
        r = (_yesno(rtxt) or ("yes" if "rear steer" in rtxt.lower() else None)) if rtxt else None
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
    if not cn and sender_name(sender):
        # Nobody named: the contact is whoever sent the reply, on the number in their footer - or anywhere
        # else in their mail (Delali's rule, 30/10)
        cp = cp or sender_phone(body, sender)
        d["contact"].update(name=sender_name(sender), phone=cp, confidence=HIGH if cp else AMBER, source="sender")

    if f.get("contact") and f.get("altcontact"):      # "contact name(s) with phone numbers" go in the comment (his 30/10)
        an, ap, _ = parse_contact(f["altcontact"])
        if ap and ap != d["contact"].get("phone"):
            d["alt_contact"] = {"name": an, "phone": ap, "confidence": HIGH, "raw": f["altcontact"]}

    d["notes"] = {"value": f.get("notes") or None, "confidence": HIGH, "raw": f.get("notes", "")}
    return d


# fields that must be filled before an order can actually be booked on CTMS
REQUIRED = ("date", "time", "offloading", "artic_access", "what3words", "contact")
LABELS = {"date": "delivery date", "time": "delivery time", "offloading": "offloading (HIAB/Moffett)",
          "artic_access": "artic access", "rear_steer": "rear steer", "what3words": "What3Words",
          "contact": "site contact", "pts": "PTS", "vehicle": "vehicle size"}


def missing(details, product_type=None):
    """What's still needed - so the chaser asks for exactly these, instead of
    'can I get a reply?'. PTS is only chased on RAIL orders (S&C with them) -
    "PTS is only for Rails" (Delali's rule) - but it is never assumed on any order."""
    need = list(REQUIRED) + (["pts"] if product_type in ("rails", "S&C") else [])
    out = []
    for k in need:
        v = details.get(k) or {}
        got = v.get("value") or v.get("earliest") or v.get("name")
        if not got:
            out.append(LABELS.get(k, k))
    return out


def firm_date(details):
    """The one delivery date a reply settles on (dd/mm/yyyy), or None - an amber date, a "flexible" one or a choice
    of days is not firm, and waits for Delali's confirm."""
    cell = (details or {}).get("date") or {}
    if (cell.get("value") and cell.get("confidence") == HIGH and not cell.get("flexible")
            and len(cell.get("options") or []) <= 1):
        return cell["value"]
    return None


def amber(details):
    """Fields parsed but not certain - these are the one-click confirms whose
    answers get fed back through learn()."""
    return [LABELS.get(k, k) for k, v in details.items()
            if isinstance(v, dict) and v.get("confidence") == AMBER
            and (v.get("value") or v.get("earliest") or v.get("name"))]
