"""
Process an ad hoc that arrived as PLAIN EMAIL TEXT - no form attached.

Most ad hocs come on a form: the Excel Haulage Request Form (process_form),
Network Rail's Word transport request form (process_word_form) or a DTS PDF
(process_dts). Some just arrive typed into the body of a forwarded email -
the two ends, two dates, a cost centre and a line saying what the load is.
Those used to be retyped into a form before they could be processed, which is
the one step where a digit gets dropped.

This module reads that typed block and hands it to the SAME tail every other
ad hoc route uses:

    row -> process_form.to_transform_row -> nr_csv.transform -> write_csv
        -> process_form.save_adhocs   (so the job pins on the dashboard map)

so an email job and a form job produce an identical upload.

Nothing here invents a value. A field the email never states comes out blank
and is reported - the requester's email address (ORD_SUB_REFS 1002) is the
one that is missing most often, because a forwarded job rarely carries it.
No service flag is derived either: see services.py - NIGHT, SATURDAY and
SUN_BANK_HOL go on by hand or not at all.

The block it reads is the shape these emails already arrive in - a label, a
colon, and the value either on the same line or indented under it:

    Collection date: 02/09/2026, window 0900-1200
    Collection address:
      Sperry Rail (International) Ltd
      Donington House
      Riverside Road
      Pride Park
      Derby
      DE24 8HY
      Contact: Steve Elliott - 07909 534173

    Delivery date: 03/09/2026, window 0900-1200
    Delivery address:
      Network Rail - RT&L
      Newhut Road
      Motherwell
      ML1 3ST
      Contacts: Martin Cassidy - 07785 263 371 / David McLaughlin - 07809 377 360
    Delivery notes: Ring the site 30 minutes before arrival for the gate code

    Cost centre: 861232
    Item description: Ultrasonic equipment - X3 Box, 24 Kg total

A date line can give a start with no end ("from 9am", "09:00 onwards"), which
closes the way a form's does. A deadline ("by 12:00") is not a start: the run
says so and leaves the window for the desk. A time is read only off a line that
says nothing else, and any line nothing reads is told.

    python process_email_adhoc.py "<job.txt>" [--raised-by someone@networkrail.co.uk]
"""
import sys, os, re
from datetime import datetime

import nr_csv, outbox, process_form
import process_word_form as pw   # the ad hoc helpers live there - reuse, never re-copy

HERE = os.path.dirname(os.path.abspath(__file__))

# A label owns every line under it until the next label.
LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z /'()&-]{2,40})\s*:\s*(.*)$")
# "Steve Elliott - 07909 534173" / "Martin Cassidy - 07785 263 371"
CONTACT_RE = re.compile(r"^(.+?)\s*-\s*(\+?[\d][\d ()-]{6,})$")
# Labels that belong to the address above them rather than starting a block
# of their own. Nesting is decided by the label, NOT by indentation: the job
# is typed indented and arrives forwarded, and every mail client along the
# way is free to reflow it - the first one that strips the leading spaces
# would otherwise detach both contacts from their addresses and put the
# delivery contact on the upload as the collection one. Whole labels only:
# 'Telford Depot:' and 'Mobile crane on site:' are not a phone number.
PHONE_LABEL_RE = re.compile(r"(?:site )?contact (?:number|no|tel\w*|phone|mobile)"
                            r"|(?:tel(?:ephone)?|phone|mobile|mob)(?: number| no)?")
POSTCODE_LABEL = r"(?:post\s*code|p/\s*code)"
SUB_LABEL_RE = re.compile(r"(?:site )?contacts?(?: name)?|" + PHONE_LABEL_RE.pattern + "|" + POSTCODE_LABEL)
EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# Where an email stops being the job: a block ends here, and the rest is told.
SIGN_OFF_RE = re.compile(r"(?i)^(?:(?:with\s+)?(?:kind(?:est)?|best|warm(?:est)?|many)\s+)?(?:regards|regds|rgds|thanks|thx|wishes)\b"
                         r"|^thank you\b|^cheers\b|^yours\b|^sent from\b|^(?:kr|br|ta|best)\W*$")
# 'Collection notes:' and the like - what the driver has to know at that end.
NOTE_WORDS = ("note", "instruction", "comment", "access")
# Labels that say when or how, never where: a job labelled plain 'Collection:'
# must not have one of these taken for its address.
NOT_ADDRESS = ("date", "day", "time", "window", "contact") + NOTE_WORDS
# Beside a plain 'Collection:' label, these are when and not the site.
NOT_A_SITE_RE = re.compile(r"(?i)asap|a\.s\.a\.p\.?|tbc|tba|today|tomorrow|urgent")

_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_YEARS = f"{datetime.now().year}|{datetime.now().year + 1}"
# '3rd November 2026', 'November 3rd 2026'. Only with this year or next: 'Wed 4th
# Nov, 0900-1200' has no year but a time, and 'Sat 7th Nov 2030' is half past eight.
WORDED_DATE_RE = re.compile(
    r"\b(?:(?P<d1>\d{1,2})(?:st|nd|rd|th)?[\s-]+(?:of\s+)?(?P<m1>" + _MONTH + r")\.?,?[\s-]+(?P<y1>" + _YEARS + r")"
    r"|(?P<m2>" + _MONTH + r")\.?\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y2>" + _YEARS + r"))\b", re.I)
# A time is read only off a line made of nothing but these and the times. Anything
# else on the line - 'ring Robin at 0131 496 0345', 'site closes at 16:00', '12.50
# tonnes', 'closed for lunch 12:00-13:00' - means it is about something else: it
# reads as no time, and the line is told. Blank and told costs a phone call; a
# ring time on the booking as the collection time costs a wasted vehicle.
WHEN_WORDS = frozenset("""window from after at between and to by before until till latest earliest not no earlier later
than prior up on or the of start starts starting started ready available open opens opening finish finishes finishing
close closes closing end ends onward onwards about around approx approximately circa hr hrs hour hours jan january feb
february mar march apr april may jun june jul july aug august sep sept september oct october nov november dec
december""".split())

# Times once _clock has written them all as HH:MM.
_T = r"(\d{2}:\d{2})"
# Which of a line's two times is the end: 'by 12:00', 'not after 12:00', 'closes at 16:00', '12:00 latest', '16:00 finish'.
# But 'not before 09:00' and 'not until 09:00' are starts, and '09:00 latest 12:00' has its deadline second.
DEADLINE_RE = re.compile(
    r"\b(?:by|(?<!not )before|(?<!not )until|(?<!not )till|latest|no later(?: than)?|not later(?: than)?"
    r"|(?<!no )(?<!not )earlier than|not after|to|finish\w*|clos(?:e|es|ing)|ends?)\b(?:\s+or)?(?:\s+at)?"
    r"(?:\s+(?:about|around|approx\w*|circa))?\W*" + _T
    + r"|" + _T + r"\s+(?:at the latest|at latest|latest|no later|or (?:before|earlier)|prior|finish\w*"
    r"|clos(?:e|es|ing)|ends?)\b(?!\W*\d{2}:\d{2})", re.I)
# A line's only time is a deadline if any of these is anywhere on it, however it
# is put ('4pm finish', '12:00 or before') - unless it is really a start.
_BY_WORDS = re.compile(r"(?i)\b(?:by|before|until|till|latest|later|earlier|prior|to|not after|finish\w*|clos\w*|ends?)\b")
_FROM_WORDS = re.compile(r"(?i)\b(?:not before|not until|not earlier|no earlier|earliest|onwards?|or later|or after)\b")
# A date a time-word stands in front of or behind is a limit, not the day: 'before 06/11/2026', '06/11/2026 latest'.
# '@' stands for the date, marked by says_more.
DATE_LIMIT_RE = re.compile(r"(?i)\b(?:by|before|after|from|until|till|than|latest|earliest|prior to|up to|end of)\W+"
                           r"(?:(?:the|end of|close(?: of)?)\W+)*"
                           r"(?:(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?\W+)?(?:the\W+)?@"
                           r"|@\W*(?:(?:at (?:the )?)?(?:latest|earliest)|onwards?|or (?:earlier|before|later|after))\b(?!\W*\d)")
_WEEKDAY = r"(?i)\b(mon|tue|wed|thu|fri|sat|sun)(?:s|nes|rs?|ur)?(?:day)?\b"

# A county line is not a town: the upload's region comes from the postcode. An
# explicit list, because the shape of a line says nothing - 'BISHOP AUCKLAND' in
# capitals is a town. A direction in front of any of these counts, spelt out or not.
COUNTIES = frozenset("""bedfordshire|berkshire|buckinghamshire|cambridgeshire|cheshire|cornwall|cumberland|cumbria
|derbyshire|devon|dorset|east riding|east riding of yorkshire|essex|gloucestershire|greater london|greater manchester
|hampshire|herefordshire|hertfordshire|huntingdonshire|isle of wight|kent|lancashire|leicestershire|lincolnshire
|merseyside|middlesex|midlands|norfolk|northamptonshire|northumberland|nottinghamshire|oxfordshire|rutland|shropshire
|somerset|staffordshire|suffolk|surrey|sussex|tyne and wear|warwickshire|westmorland|wiltshire|worcestershire|yorkshire
|aberdeenshire|angus|argyll|argyll and bute|ayrshire|banffshire|berwickshire|caithness|clackmannanshire
|dumfries and galloway|dumfriesshire|dunbartonshire|fife|highland|inverness-shire|kincardineshire|kinross-shire
|kirkcudbrightshire|lanarkshire|lothian|midlothian|moray|nairnshire|orkney|peeblesshire|perth and kinross|perthshire
|renfrewshire|ross-shire|roxburghshire|scottish borders|selkirkshire|shetland|stirlingshire|sutherland|western isles
|wigtownshire|anglesey|isle of anglesey|caernarfonshire|cardiganshire|carmarthenshire|ceredigion|clwyd|denbighshire
|dyfed|flintshire|glamorgan|gwent|gwynedd|merionethshire|monmouthshire|montgomeryshire|pembrokeshire|powys|radnorshire
|vale of glamorgan|lancs|yorks|notts|lincs|staffs|herts|bucks|beds|berks|hants|worcs|warks|wilts|oxon|cambs|glos|gloucs
|northants|leics|derbys|shrops|salop|middx|mddx|mids|cleveland|avon|humberside|teesside|gtr manchester|gtr london
|cheshire east|cheshire west|iow|strathclyde|tayside|grampian|borders|highlands|scottish highlands|rhondda cynon taf|rct
|neath port talbot|blaenau gwent|redcar and cleveland|bath and north east somerset""".replace("\n", "").split("|"))
# Towns as well, so on their own they are the town: only 'County Durham' or
# 'Co. Antrim' means the county.
ALSO_TOWNS = frozenset(("durham", "antrim", "armagh", "down", "fermanagh", "londonderry", "tyrone"))
_DIRECTION = r"^(?:(?:north|south)[ -]?(?:east|west)|north|south|east|west|nth|sth|mid|central|[ns]\.?[ew]|[nsew])(?:\. ?| |/)"
# The word in front of a county when the county is part of the name: 'Crook of Devon', 'Fort Cumberland'.
NAME_GOES_ON = frozenset(("of", "the", "in", "on", "upon", "and", "new", "old", "little", "great", "fort", "port", "mount"))
# '1 High Street' above a county is the street with no town given, not the town.
STREET_RE = re.compile(r"^\d|\b(?:street|st|road|rd|lane|ln|avenue|ave|way|drive|close|crescent|terrace|place|square"
                       r"|approach|row|walk|mews|parade|gardens)\.?$", re.I)
# Never the town: a map reference, which rides on the address lines for the driver...
MAP_REF_RE = re.compile(r"^/{3}|\b(?:what\s*3\s*words|w3w|grid\s*ref\w*|ngr)\b", re.I)
# ... and these are not a line of the address at all.
NOT_A_PLACE_RE = re.compile(r"\bsat\s*nav\b|^\+?[\d ()-]{7,}$|^(?:tel(?:ephone)?|phone|mob(?:ile)?|fax)\b.*\d|@", re.I)
# Words beside a postcode that say it is only near, or are just its label.
POSTCODE_WORDS_RE = re.compile(r"(?i)\b(?:nearest|closest|approx\w*|sat\s*nav|post\s*code|pc|p/c)\b")
# Probably not a town, though nothing better was given: the run points it out.
NOT_TOWN_RE = re.compile(r"\b(?:estate|park|yard|depot|compound|sidings?)$|\d|^(?:ring|call|phone|access|please|note)\b", re.I)


# ---------- reading the block ----------
class Blocks(dict):
    """read_blocks' answer. It remembers which labels were asked for, and the
    lines before the first label, so a run can say what nothing read."""
    def __init__(self):
        super().__init__()
        self.read, self.loose, self.far_postcodes = set(), [], set()


def _sub_label(line):
    m = LABEL_RE.match(line)
    return bool(m) and bool(SUB_LABEL_RE.fullmatch(m.group(1).strip().lower()))


def _finished(label, value):
    """Whether a block is complete enough that a blank line ends it: a note with
    words in it, or an address that has reached its postcode or contact."""
    return bool(value) and (label.split()[-1].startswith(NOTE_WORDS)
                            or any(_sub_label(ln) or postcode_on(ln) for ln in value.split("\n")))


def read_blocks(text):
    """{label.lower(): value} where the value keeps the lines under it.

    Labels repeat across a job ("Contact:" appears under both addresses), so
    a sub-label stays part of its parent's block rather than overwriting the
    earlier one - the collection contact is found inside the collection
    address, which is the only place it means anything. A sign-off ends a block,
    as does a blank line once it is _finished: an email's signature has a postcode
    and a mobile of its own, and they are not the delivery address's.
    """
    blocks, cur, gap, parted = Blocks(), None, False, False
    for raw in pw._clean(text).split("\n"):
        line = raw.strip()
        if not line:
            gap = True
            continue
        m = LABEL_RE.match(line)
        sub = _sub_label(line)
        if cur is not None and not m and (SIGN_OFF_RE.match(line) or (gap and _finished(cur, blocks[cur]))):
            cur = None
        was_gap, gap = gap, False
        if m and not (sub and cur):
            cur, parted = m.group(1).strip().lower(), False
            if cur in blocks and cur.split()[-1].startswith(NOTE_WORDS):
                blocks[cur] = (blocks[cur] + "\n" + m.group(2).strip()).strip("\n")     # notes join up
                continue
            # A second drop or load line: one row carries one. The first stays
            # and the second is a block nothing asks for, so the run tells it.
            n = 2
            while cur in blocks:
                cur = f"{m.group(1).strip().lower()} ({n})"
                n += 1
            blocks[cur] = m.group(2).strip()
        elif cur is not None:
            # A postcode below a blank line or a contact could be a signature's, under a
            # sign-off nothing here knows: it is read, and the run points it out.
            parted = parted or (was_gap and bool(blocks[cur])) or any(_sub_label(x) for x in blocks[cur].split("\n"))
            if parted and not sub and postcode_on(line):
                blocks.far_postcodes.add(line)
            blocks[cur] = (blocks[cur] + "\n" + line).strip("\n")
        else:
            blocks.loose.append(line)
    return blocks


def block(blocks, *labels):
    """The first block whose label starts with one of these (so 'Collection
    address' answers to 'collection address' and to 'collection')."""
    for lb in labels:
        for k, v in blocks.items():
            if k.startswith(lb.lower()):
                blocks.read.add(k)
                return v
    return ""


def address_block(blocks, word):
    """A leg's address: 'Collection address', else any other label that starts
    with the word - but never that leg's date or its notes."""
    found = block(blocks, f"{word} address")
    if found:
        return found
    not_where = tuple(f"{word} {w}" for w in NOT_ADDRESS)
    for k, v in blocks.items():
        if k.startswith(word) and not k.startswith(not_where):
            blocks.read.add(k)
            return v
    return ""


def note(blocks, word):
    """A leg's 'Collection notes:' on one line. nr_csv.nc turns a comma in a CSV
    value into a gap, so the commas go here where they read properly."""
    text = block(blocks, *(f"{word} {w}" for w in NOTE_WORDS))
    return re.sub(r"\s*,\s*", " ", " ".join(text.split("\n"))).strip()


# ---------- the pieces ----------
def _hhmm(h, m=0):
    """'09:00', or '' for something no clock shows."""
    return f"{int(h):02d}:{int(m):02d}" if int(h) < 24 and int(m) < 60 else ""


def _clock(text):
    """A line's times all written HH:MM, with the date itself taken out.

    The date goes first because a time can be read out of it: 03.11.2026 holds
    an '03.11', and the year of 3 November 2026 is a 20:26. Four bare digits are a
    time only where a time is being said - after 'window' or 'from', in a range,
    alone on the line. '2.30' or '1:30-3:30pm' could be either end of the day, and
    '12.11' a date as easily as a time, so those become a word no line can be read
    with: nothing is guessed, and the line is told.
    """
    def four(m):
        return m.group(1) + (_hhmm(m.group(2), m.group(3)) or m.group(2) + m.group(3))

    def meridiem(m):
        h, mins, half = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if not 1 <= h <= 12:                # '17:00pm' says the same twice; '13pm' says nothing
            return _hhmm(h, mins) if m.group(2) else m.group(0)
        return _hhmm(h % 12 + (12 if half == "p" else 0), mins) or m.group(0)

    def pm_on_the_end(m):
        # '10:00-11:30pm': the start is morning only by a 13-hour window, and could be 22:00
        h2, m2 = int(m.group(4)) % 12 + 12, int(m.group(5) or 0)
        return ("unclear" + m.group(3) + m.group(0)[len(m.group(1)) + len(m.group(2)) + 1 + len(m.group(3)):]
                if int(m.group(1)) * 60 + int(m.group(2)) + 720 < h2 * 60 + m2 else m.group(0))

    def written(m):
        h, sep, mins = m.group(1), m.group(2), int(m.group(3))
        if (len(h) == 1 and 1 <= int(h) <= 6) or (sep == "." and mins % 5):
            return "unclear"
        return _hhmm(h, mins) or m.group(0)

    t = pw.DATE_RE.sub(lambda m: " " if pw._real_date(m) else m.group(0), pw._clean(text)).replace("&", " and ")
    t = WORDED_DATE_RE.sub(" ", t)
    t = re.sub(r"\b(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?\b\.?", " ", t, flags=re.I)
    t = re.sub(r"\b(?:12\s*)?(?:noon|midday)\b", "12:00", t, flags=re.I)
    t = re.sub(r"\b(\d{1,2}:\d{2}):\d{2}\b", r"\1", t)
    t = re.sub(r"(?i)(?<![\d:.])(1[01]|[7-9])[:.](\d{2})(\s*(?:-|~|to|and|until|till)\s*)(\d{1,2})(?:[:.](\d{2}))?\s*p\.?m\b",
               pm_on_the_end, t)
    t = re.sub(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\b\.?", meridiem, t, flags=re.I)
    t = re.sub(r"(?i)(\d{1,2}[:.]\d{2})\s*(?:hrs?|hours?)\b", r"\1", t)
    t = re.sub(r"\b(\d{1,2})([:.])(\d{2})\b", written, t)
    t = re.sub(r"(?i)()\b(\d{2})(\d{2})\s*(?:hrs?|hours?)\b", four, t)
    # four digits: where a word says a time is coming; first in a range; second in one; before 'onwards'
    t = re.sub(r"(?i)(\b(?:window|from|after|at|between|by|before|until|till|than|latest|earliest|start\w*|ready"
               r"|available|open\w*|finish\w*|clos\w*|ends?)\W*?)(\d{2})(\d{2})\b", four, t)
    t = re.sub(r"()\b(\d{2})(\d{2})\b(?=\s*(?:-|to|and|until|till)\s*\d{2}:?\d{2}\b)", four, t)
    t = re.sub(r"(\d{2}:\d{2}\s*(?:-|~|to|and|until|till)\s*)(\d{2})(\d{2})\b", four, t)
    t = re.sub(r"(?i)()\b(\d{2})(\d{2})\b(?=\s*(?:onwards?|start|latest|at the latest)\b)", four, t)
    return re.sub(r"^(\W*)(\d{2})(\d{2})\W*$", four, t)


def _when_only(line):
    """Whether a line _clock has been over says nothing but when: see WHEN_WORDS."""
    if re.search(r"(?i)\bclos\w*(?:\s+at)?\W*" + _T + r"\s*(?:-|~|to)", line):     # 'close 12:00-13:00' is a closure
        return False
    t = re.sub(_T, " ", line.lower())
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)\b", " ", t)
    return (not re.search(r"[<>]|\b(?:not|no)\b(?!\s+(?:before|after|until|earlier|later)\b)", t)
            and set(re.findall(r"[a-z]+|\d+", t)) <= WHEN_WORDS)


def _when_lines(text):
    """The lines of a block a time can be read from: nothing but when, with a time on."""
    return [t for t in (_clock(ln) for ln in (text or "").split("\n")) if re.search(_T, t) and _when_only(t)]


def _only_by(t):
    """Whether a line's only time is a deadline."""
    return bool(_BY_WORDS.search(t)) and not _FROM_WORDS.search(t)


def _days(line):
    return ([m.group(0) for m in pw.DATE_RE.finditer(line) if pw._real_date(m)]
            + [m.group(0) for m in WORDED_DATE_RE.finditer(line)])


def says_more(text):
    """The lines of a date block saying more than what went on the upload, as typed:
    anything besides a date and a time, a time that was not used, a second date, or
    a date that is a limit ('before 06/11/2026' goes up on the 6th, so it is told)."""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    used = set(window(text)) | {deadline(text)}
    two_days = len({first_date(d) for ln in lines for d in _days(ln)}) > 1
    day = first_date(text)
    out = []
    for ln in lines:
        marked = ln
        for d in _days(ln):
            marked = marked.replace(d, "@")
        if (not _when_only(_clock(ln)) or set(re.findall(_T, _clock(ln))) - used
                or ("@" in marked and (two_days or DATE_LIMIT_RE.search(marked)))
                or re.search(r"(?i)\b\d{1,2}(?:st|nd|rd|th)\b", marked)        # a day that is not the date read
                or (day and {w.lower() for w in re.findall(_WEEKDAY, ln)} - {f"{day:%a}".lower()})):
            out.append(ln)
    return out


def window(text):
    """(start, end) from a date line, '' for what it does not give.

    '09:00-12:00', 'window 0900-1200' and '9am to 5pm' give both, as does a start
    with a deadline ('from 09:00, by 12:00'). 'from 9am', '09:00 onwards' or a time
    on its own give the start: the end stays blank, for to_transform_row to close
    the way it closes a form's. A deadline alone gives nothing - see deadline().

    Only a line of nothing but time wording is read, and only if it is the one
    such line: two lines of times compete. The exception is a range straight
    after the word 'window', which says what it is whatever else the line holds.
    A range is still read by process_word_form: there is one range parser in this
    toolkit. Something no clock shows gives nothing rather than a crash in _at.
    """
    lines = (text or "").split("\n")
    start, end = "", ""
    for ln in lines:
        m = re.search(r"(?i)\bwindow\W*" + _T + r"\s*(?:-|~|to)\s*" + _T, _clock(ln))
        if m:
            start, end = m.group(1), m.group(2)
            break
    else:
        said = _when_lines(text)
        if len(said) == 1:
            start, end = _read_when(said[0])
    return (start, end) if start != end and all(_hhmm(*v.split(":")) for v in (start, end) if v) else ("", "")


def _read_when(t):
    """(start, end) off one line of nothing but when."""
    t = re.sub(r"(?i)\bbetween\s+(\d{2}:\d{2})\s+and\b", r"\1 -", t)
    t = re.sub(r"(?i)(\d{2}:\d{2})\s+(?:until|till)\b(?=\W*\d{2}:\d{2})", r"\1 -", t)
    times = re.findall(_T, t)
    if re.search(_T + r"\W*or\s+(?:(?:before|after|by|from|until|till|at)\s+)?" + _T, t):      # a choice, not a window
        return "", ""
    if len(times) == 2 and pw.TIME_RE.search(t):
        return pw._window(t)
    if len(times) == 1:
        return ("", "") if _only_by(t) else (times[0], "")
    d = DEADLINE_RE.search(t)
    if len(times) == 2 and d:
        rest = t[:d.start()] + " " + t[d.end():]
        start = re.findall(_T, rest)
        # '19:00 finish, 07:00 start' has its end first; a time with a start word beside it is no end
        if (len(start) == 1 and not DEADLINE_RE.search(rest)
                and not re.search((d.group(1) or d.group(2)) + r"\s+(?:start\w*|earliest|open\w*|onwards?)\b", t)):
            return start[0], d.group(1) or d.group(2)
    return "", ""


def deadline(text):
    """The '12:00' of a line that says 'by 12:00' and gives no window, else ''.
    It is not a start, so it cannot go on the upload as one, and the run says so."""
    said = _when_lines(text)
    if window(text)[0] or len(said) != 1 or len(re.findall(_T, said[0])) != 1 or not _only_by(said[0]):
        return ""
    return re.findall(_T, said[0])[0]


def first_date(text):
    """The first real date in the text, written either way. A worded one needs its
    year: 'Wed 4th Nov' stays blank and is told, a year is not ours to guess."""
    day = pw._first_date(text)
    m = None if day else WORDED_DATE_RE.search(text or "")
    if not m:
        return day
    try:
        return datetime.strptime(f"{m.group('d1') or m.group('d2')} {(m.group('m1') or m.group('m2'))[:3]} "
                                 f"{m.group('y1') or m.group('y2')}", "%d %b %Y")
    except ValueError:
        return None


def date_doubts(text, day):
    """What a leg's own words say against its date. The date stays as typed, for the
    desk to look at: a weekday beside it is the only cross-check on the digits."""
    if not day:
        return []
    out = [f"{day:%d/%m/%Y} is in the past"] if day.date() < datetime.now().date() else []
    m = re.search(_WEEKDAY, text or "")
    if m and m.group(1).lower() != f"{day:%a}".lower():
        out.append(f"{day:%d/%m/%Y} is a {day:%A}, the email says {m.group(0)}")
    return out


def when_on_label(cell):
    """('03/11/2026 from 9am', the rest) for a 'Collection:' heading with the when
    beside it and the where under it: a line of nothing but when is not the site."""
    first, _, rest = (cell or "").partition("\n")
    t = _clock(first)
    when = rest and (NOT_A_SITE_RE.fullmatch(first) or (_when_only(t) and (t != first or re.search(r"\d", t))))
    return (first, rest) if first_date(first) or when else ("", cell)


def is_county(line):
    """Whether a whole address line is a county: see COUNTIES."""
    key = re.sub(r"\s+", " ", re.sub(r"\s*&\s*", " and ", (line or "").lower())).strip(" .,")
    named = re.match(r"(?:co\. ?|co |county )(.+)", key)
    if named and named.group(1) in ALSO_TOWNS:
        return True
    key = named.group(1) if named else key
    return key in COUNTIES or re.sub(_DIRECTION, "", key) in (COUNTIES | pw.COUNTRIES)


def without_county(town):
    """'Retford NOTTINGHAMSHIRE' -> the town. A town that is nothing but a county
    stays, there being nothing better to put there, and so does a name the county
    is part of ('Crook of Devon'), or a country with no comma ('New England')."""
    if is_county(town):
        return town
    words = town.split()
    for n in range(min(5, len(words) - 1), 0, -1):
        tail, left = " ".join(words[-n:]), words[:-n]
        if (is_county(tail) and tail.lower() not in pw.COUNTRIES and left[-1].lower() not in NAME_GOES_ON
                and re.search(r"[A-Za-z]{3}", " ".join(left))):
            return " ".join(left).strip(" -/")
    return town


def postcode_on(line):
    """The postcode on an address line, or None. 'M1 2nd exit' and 'Unit B4 1st Floor'
    have the shape, but are a road or a unit and an ordinal with more words after
    it: a real one ends its line ('ML1 3ST' is real). 'A1 5km' and 'M1 8am' cannot
    be: no inward code has a C, I, K, M, O or V. Of two on a line, the last."""
    found = None
    for m in pw.PC_RE.finditer(line):
        if (re.fullmatch(r"\d[ABD-HJLNP-UW-Z]{2}", m.group(2), re.I)
                and (not re.fullmatch(r"\d(?:st|nd|rd|th)", m.group(2), re.I) or not line[m.end():].strip(" ,."))):
            found = m
    return found


def address(cell, told=None):
    """(site, addr1, addr2, town, postcode) from a typed address block.

    process_word_form._address cannot read this shape. On the Word form the
    town and the postcode share the last line ('Retford NOTTINGHAMSHIRE DE24
    8HY'); in a typed email the postcode is nearly always on a line of its
    own, which leaves that reader with an empty town and the town folded into
    the street. Here the town is the last place above the postcode, once the
    county is off it. Lines that are not the address go on `told`.
    """
    told = [] if told is None else told
    lines = [re.sub(rf"(?i)^{POSTCODE_LABEL}\W*", "", ln.strip(" ,")) for ln in cell.split("\n")]
    lines = [ln for ln in lines
             if ln and ln.lower().strip(". ") not in pw.COUNTRIES
             and not _sub_label(ln)]            # 'Contact: ...' is not an address line
    if len(lines) == 1:                         # 'Collection address: DAC Limited, Union Mill, Sabden, BB7 9ED'
        lines = [p.strip() for p in re.sub(r"^(\d+[A-Za-z]?),\s*", r"\1 ", lines[0]).split(",") if p.strip()]
    if not lines:
        return "", "", "", "", ""
    site, rest = lines[0], lines[1:]
    refs = [ln for ln in rest if MAP_REF_RE.search(ln) and not postcode_on(ln)]
    told.extend(ln for ln in rest if NOT_A_PLACE_RE.search(ln) and not postcode_on(ln))
    rest = [ln for ln in rest if ln not in refs and (postcode_on(ln) or not NOT_A_PLACE_RE.search(ln))]
    pc = ""
    hits = [i for i, ln in enumerate(rest) if postcode_on(ln)]
    if hits:
        # alone on its line beats one in a sentence; the first beats a 'Sat nav' below it
        alone = [i for i in hits if not pw.PC_RE.sub("", rest[i]).strip(" ,.")]
        i = (alone or hits)[0]
        m = postcode_on(rest[i])
        pc = f"{m.group(1).upper()} {m.group(2).upper()}"
        # Beside it: the town in front, or a county behind. Punctuation goes, and a
        # line holding anything else ('Nearest postcode ...') is told.
        before, after = (x.strip(" ,.;:-()") for x in (rest[i][:m.start()], rest[i][m.end():]))
        keep = [x for x, ok in ((before, True), (after, is_county(after)))
                if ok and re.search("[A-Za-z]", x) and not POSTCODE_WORDS_RE.search(x)]
        if len(keep) < len([x for x in (before, after) if x]):
            told.append(rest[i])
        told.extend(rest[j] for j in hits if j < i)
        told.extend(ln for ln in rest[i + 1:] if not is_county(ln))
        rest = [ln for j, ln in enumerate(rest[:i]) if j not in hits] + keep
    # commas first, a bare house number staying with its street ('12, High Street')
    parts = [p.strip() for ln in rest for p in re.sub(r"^(\d+[A-Za-z]?),\s*", r"\1 ", ln).split(",") if p.strip()]
    # The county is dropped, the region on the upload comes from the postcode
    # district, never from text.
    while len(parts) > 1 and is_county(parts[-1]) and not STREET_RE.search(parts[-2]):
        parts.pop()
    town = without_county(parts.pop()) if parts else ""
    parts += refs
    # 0 of the 223 uploads on file left line 1 blank, so the town fills it when the
    # block gives nothing else ('Pullmans Place / Staines / TW18 4LD'). A county is
    # not a place to send a lorry: that stays blank, and the run says so.
    a1 = parts[0] if parts else ("" if is_county(town) else town)
    a2 = " ".join(parts[1:])
    return site, a1, a2, town, pc


def contacts(cell):
    """[(name, phone)] from the 'Contact:' / 'Contacts:' lines of an address
    block. Several people on one job are separated by '/' - the first is the
    one the upload carries, the rest are kept for the location comments so a
    driver who cannot raise the first has the second. A number on a line of its
    own ('Tel: ...') goes with the first person, if they have none, and any more
    numbers are kept the same way."""
    said, phones = [], []
    for ln in cell.split("\n"):
        m = LABEL_RE.match(ln.strip())
        label = m.group(1).strip().lower() if m else ""
        if PHONE_LABEL_RE.fullmatch(label):
            phones.append(re.sub(r"[^\d+ ]", "", m.group(2)).strip())
        elif label and SUB_LABEL_RE.fullmatch(label) and not re.fullmatch(POSTCODE_LABEL, label):
            said.append(m.group(2).strip())
    out = []
    for part in re.split(r"\s*/\s*(?=[A-Za-z])", " / ".join(said)):
        part = part.strip()
        if not part:
            continue
        m = CONTACT_RE.match(part)
        if m:
            out.append((m.group(1).strip(),
                        re.sub(r"[^\d+ ]", "", m.group(2)).strip()))
        else:
            out.append((part, ""))
    phones = [p for p in phones if p]
    if phones and not (out and out[0][1]):
        out[0:1] = [(out[0][0] if out else "", phones.pop(0))]
    return out + [("", p) for p in phones if p not in [x[1] for x in out]]


def item(text):
    """(description, qty, weight) from 'Ultrasonic equipment - X3 Box, 24 Kg
    total'. The quantity is the multiplier ('X3', '3 x'); the weight is
    whatever states a unit. Anything that will not read stays blank - the
    description then carries the requester's own words unaltered."""
    t = (text or "").strip()
    wm = re.search(r"([\d.]+\s*(?:kgs?|tonnes?|te?\b).*)$", t, re.I)
    weight = wm.group(1).strip(" ,.") if wm else ""
    qm = re.search(r"\bx\s*(\d{1,4})\b", t, re.I) or re.search(r"\b(\d{1,4})\s*x\b", t, re.I)
    qty = qm.group(1) if qm else ""
    desc = re.split(r"\s*[-,]\s*", t)[0].strip() if t else ""
    return desc, qty, weight


# ---------- email text -> the shape every ad hoc route already speaks ----------
def parse(path):
    with open(path, encoding="utf-8-sig") as f:
        blocks = read_blocks(f.read())
    told = []

    def one_line(*labels):
        """A value that is one line. Whatever runs on under it is told, not glued on:
        an email's sign-off under 'Raised by', 'HIAB will be required' under the item."""
        first, *more = block(blocks, *labels).split("\n")
        told.extend(more)
        return first.strip()

    cwhen, cblock = when_on_label(address_block(blocks, "collection"))
    dwhen, dblock = when_on_label(address_block(blocks, "delivery"))
    csite, ca1, ca2, ctown, cpc = address(cblock, told)
    dsite, da1, da2, dtown, dpc = address(dblock, told)

    cdate_txt = "\n".join(x for x in (block(blocks, "collection date"), cwhen,
                                      block(blocks, "collection time", "collection window")) if x)
    ddate_txt = "\n".join(x for x in (block(blocks, "delivery date"), dwhen,
                                      block(blocks, "delivery time", "delivery window")) if x)
    cday, dday = first_date(cdate_txt), first_date(ddate_txt)
    # 'for collection' is said of its own leg. On the other leg's line it stays in,
    # the line reads as about something else, and that leg's time cannot land here.
    cwhen_txt = re.sub(r"(?i)\bfor collection\b", " ", cdate_txt)
    dwhen_txt = re.sub(r"(?i)\bfor delivery\b", " ", ddate_txt)
    cw, dw = window(cwhen_txt), window(dwhen_txt)
    told.extend(f"collection date: {ln}" for ln in says_more(cwhen_txt))
    told.extend(f"delivery date: {ln}" for ln in says_more(dwhen_txt))

    ccon, dcon = contacts(cblock), contacts(dblock)
    cname, cphone = ccon[0] if ccon else ("", "")
    dname, dphone = dcon[0] if dcon else ("", "")

    desc, qty, weight = item(one_line("item description", "item", "description"))
    cost = one_line("cost centre", "cost centre number", "cost code")
    raised_txt = one_line("raised by", "requester email", "requester")
    raised_by = ";".join(EMAIL_RE.findall(raised_txt))
    if raised_txt and not raised_by:
        told.append(f"raised by: {raised_txt}")

    ref = pw.ah_ref(cday or dday, cpc, dpc)

    # Delivery Instructions carry the material line the desk expects; the
    # weight tail is what the map record lifts back out for the brief.
    instr = " ".join(p for p in (
        f"Material {desc}" if desc else "",
        f"Qty {qty}" if qty else "",
        f"Weight - {weight}" if weight else "",
    ) if p)
    # The people the upload has no column for. A second delivery contact is
    # not decoration - it is who the driver rings when the first does not
    # answer at a gate, so it rides in the location comments, behind whatever
    # the job says the driver has to know at that end.
    notes = ". ".join(x for x in [note(blocks, "delivery")] + [" ".join(f"Also {n} {p}".split()) for n, p in dcon[1:]] if x)
    cnotes = ". ".join(x for x in [note(blocks, "collection")] + [" ".join(f"Also {n} {p}".split()) for n, p in ccon[1:]] if x)

    row = {
        "Customer Order No": ref, "Shipment No": ref,
        # collection end
        "Site Name - Collection": csite, "Contact Name": cname,
        "Address 1": ca1, "Address 2": ca2, "Address 3": ctown,
        "Postcode": cpc, "Telephone No": cphone,
        "Collection Date": cday,
        "collection_time": pw._at(cday, cw[0]), "collection_time_end": pw._at(cday, cw[1]),
        # delivery end
        "Delivery Point": dsite, "D Contact Name": dname,
        "D Address 1": da1, "D Address 2": da2, "D Address 3": dtown,
        "D Postcode": dpc, "D Telephone No": dphone,
        "Delivery Date": dday,
        "delivery_time": pw._at(dday, dw[0]), "delivery_time_end": pw._at(dday, dw[1]),
        # load
        "Product / Description": desc, "Product Qty": qty, "Serial Number": "",
        "Delivery Instructions": instr,
        "Notes for Collection Location Comments": cnotes,
        "Notes for Delivery Location Comments": notes,
        # admin - an ad hoc is NRADHOC; the cost number rides on 1003, the
        # requester's email on 1002 (blank when the email never states one)
        "Account": process_form.ADHOC_ACCOUNT, "Cost Centre": cost,
        "Raised by": raised_by, "Est Cost": 0, "Vehicle Type": "",
        # A typed email states a lifting requirement in words or not at all.
        # Nothing is inferred from the weight: a task flag is a charge, and
        # deciding a job needs a HIAB is the desk's call, not the parser's.
        "HIAB": "N", "Moffett": "N", "PTS": "N", "Banksman": "N",
        "Log Grab": "N", "Rear Steer": "N", "Vehicle Escort": "N",
    }
    meta = {"weight": weight, "contacts": ccon + dcon,
            "dates": {"collection": cdate_txt, "delivery": ddate_txt},
            "deadlines": {"collection": deadline(cwhen_txt), "delivery": deadline(dwhen_txt)},
            "far_postcodes": [pc for pc, cell in ((cpc, cblock), (dpc, dblock))
                              if pc and blocks.far_postcodes & set(cell.split("\n"))],
            "unread": blocks.loose + told
            + [f"{k}: {v}".replace("\n", " / ") for k, v in blocks.items() if k not in blocks.read]}
    return row, meta


def windows_said(row, tr, meta):
    """Which windows the email actually gave and which the toolkit filled in, so
    nothing on the upload is mistaken for the requester's own words - and what
    the job says that nothing on the upload carries."""
    hm = lambda t: f"{t:%H:%M}" if t else ""
    out = []
    for lbl, key, day, start, end in (
            ("collection", "collection time", row["Collection Date"], row["collection_time"], row["collection_time_end"]),
            ("delivery", "delivery time", row["Delivery Date"], row["delivery_time"], row["delivery_time_end"])):
        csv = f"{tr[key]} to {tr[key + ' end']}"
        typed = meta["dates"].get(lbl, "").split("\n")[0]
        how = f"date could not be read: {typed}" if typed else "has NO DATE in the email"
        if not tr[key]:
            out.append(f"!! {lbl} {how} - times are BLANK in the CSV.")
        elif not day:
            out.append(f"!! {lbl} {how} - {csv} in the CSV is the other leg's date and the default "
                       "window. Set it in CTMS before booking.")
        elif (start and tr[key][-5:] != hm(start)) or (end and tr[key + " end"][-5:] != hm(end)):
            out.append(f"!! {lbl} said {hm(start)}{' to ' + hm(end) if end else ''}, but {csv} is in the CSV: "
                       "a midnight reads as a blank form cell. Set it in CTMS before booking.")
        elif start is None:
            why = "not read" if any(x.startswith(f"{lbl} date: ") for x in meta["unread"]) else "not stated"
            out.append(f"NOTE {lbl} window {why} - {csv} in the CSV is the default "
                       "(correct in CTMS if wrong).")
        elif end is None:
            out.append(f"NOTE {lbl} start stated, no end - {csv} in the CSV, the close is the default "
                       "(correct in CTMS if wrong).")
        if meta["deadlines"].get(lbl):
            out.append(f"!! {lbl} must be done by {meta['deadlines'][lbl]} - a deadline, not a start, so that "
                       "window does not honour it. Set it in CTMS before booking.")
        out += [f"!! {lbl} date: {x} - check it before uploading." for x in date_doubts(meta["dates"].get(lbl), day)]
    if not row["Collection Date"] and not row["Delivery Date"]:
        out.append(f"!! No date read on either leg - {row['Customer Order No']} carries today's date.")
    for lbl, pc in (("collection", row["Postcode"]), ("delivery", row["D Postcode"])):
        if pc in meta.get("far_postcodes", ()):
            out.append(f"!! {lbl} postcode {pc} sits below a blank line or a contact in the address, so it may be a "
                       "signature's and not the site's. Check it before uploading.")
        if pc and nr_csv.region_of(pc) == "UNKNOWN":
            out.append(f"!! {lbl} postcode {pc} is not in the region list, so the upload's region is UNKNOWN. "
                       "Check the postcode before uploading.")
    for lbl, key, town in (("collection", "Address 1", "Address 3"), ("delivery", "D Address 1", "D Address 3")):
        if not row[key]:
            out.append(f"!! {lbl} has no address line - every upload on file has one. Add it before uploading.")
        elif row[town] and (row[key] == row[town] or STREET_RE.search(row[town]) or is_county(row[town])
                            or NOT_TOWN_RE.search(row[town])):
            out.append(f"NOTE {lbl} gave one address line or no town: '{row[town]}' is on the upload as the town"
                       f"{' and as line 1' if row[key] == row[town] else ''}. Check it before uploading.")
    out += [f"!! Not read, nothing on the upload carries it: {line}" for line in meta["unread"]]
    return out


def main():
    path, opts = pw._cli(sys.argv[1:])
    if not path or not os.path.exists(path):
        print("Usage: python process_email_adhoc.py <path to the job text>")
        for k, v in pw.OPTS.items():
            print(f"       --{k:<17} {v}")
        return
    row, meta = parse(path)
    used = pw.apply_overrides(row, opts, read_window=window, read_date=first_date)
    for line in used:
        print(f"SET : {line}")
    for leg in ("collection", "delivery"):
        if any(u.startswith(f"{leg} ") for u in used):
            meta["deadlines"][leg] = deadline(opts[leg])
            meta["dates"][leg] = opts[leg]
    print(f"TEXT: {path}")
    print(f"Reference : {row['Customer Order No']}")
    print(f"Collection: {row['Site Name - Collection']} {row['Postcode']} "
          f"({row['Contact Name'] or 'no contact'} {row['Telephone No']})")
    print(f"Delivery  : {row['Delivery Point']} {row['D Postcode']} "
          f"({row['D Contact Name'] or 'no contact'} {row['D Telephone No']})")
    print(f"Load      : {row['Product Qty'] or '?'} x {row['Product / Description'] or '?'}"
          f"  |  HIAB {row['HIAB']}  |  cost centre {row['Cost Centre'] or '(none)'}")

    # A half reference ('AH3/11/26EH') does not end on a separator, so
    # _ref_incomplete alone passes it, and a missing postcode is a blank region.
    if process_form._ref_incomplete(row["Customer Order No"]) or not (row["Postcode"] and row["D Postcode"]):
        print("!! Could not build a usable reference - both postcodes must read. "
              "Nothing written.")
        for line in meta["unread"]:
            print(f"!! Not read, nothing on the upload carries it: {line}")
        return

    tr = process_form.to_transform_row(row)
    records = nr_csv.transform([tr])
    for line in process_form.window_notes(row, tr):
        print(line)

    # Detection only. A backwards window on this route is usually a date typed
    # into the wrong line of the email, so it is said out loud rather than
    # staged as a query email at whoever forwarded it.
    import date_query
    for p in date_query.backwards([tr]):
        print(f"!! DELIVERY BEFORE COLLECTION  {p['ref']}: collect {p['collection']} "
              f"deliver {p['delivery']} ({p['back_by']} earlier) - fix the dates "
              f"before uploading.")

    ref = re.sub(r"[^A-Za-z0-9]+", "-", row["Customer Order No"]).strip("-")[:24]
    name = f"NR_heavy_{ref}_{datetime.now():%d%m%Y%H%M%S}.csv"
    out = nr_csv.write_csv(records, outbox.path(name))

    try:
        if process_form.save_adhocs([row], name, form_path=path):
            print("MAP : job saved for the dashboard map (job text kept for forwarding).")
        else:
            print("MAP : NOT on the map - refused, see the SKIP line(s) above.")
    except Exception as ex:      # the map extra must never cost the CSV
        print(f"(map record not saved: {ex})")

    for line in windows_said(row, tr, meta):
        print(line)
    if not row["Raised by"]:
        print("!! 1002 (Raised by) is EMPTY - the email states no requester address. "
              "Add it with --raised-by before uploading; CTMS expects it.")
    if not row["Telephone No"]:
        print("!! Collection telephone is EMPTY - CTMS expects it. Get a number before uploading.")
    if not row["D Telephone No"]:
        print("!! Delivery telephone is EMPTY - the upload falls back to the contact "
              "name. Get a number before uploading.")
    print(f"CSV : {out}")


if __name__ == "__main__":
    main()
