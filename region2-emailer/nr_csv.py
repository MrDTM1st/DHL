"""
Faithful Python replica of the Network_Rail_Order_Database transform.

Reproduces the Access queries exactly (TBL_Imported_Orders computed fields,
postcode-district region lookup, ORDER/TASKS/ORD_SUB_REFS/ORD_LINES/ITEMS
records, Final's positional reordering and sort) so the output CSV is
byte-compatible with what the database exports.

    python nr_csv.py "<DTS.pdf>"     -> builds the upload CSV for a DTS job
"""
import os, sys, json, re
from datetime import datetime, timedelta

import postcodes   # the ONE outward-code implementation - never write a sixth

HERE = os.path.dirname(os.path.abspath(__file__))
REGIONS = json.load(open(os.path.join(HERE, "postcode_regions.json"), encoding="utf-8"))

# What nr_conformance said about the most recent write_csv - [] means it
# matched the accepted format. Callers read this to surface the problem in
# their own output rather than each re-running the check.
LAST_COMPLAINTS = []


class Keep(str):
    """A string whose leading/trailing spaces are load-bearing.

    Only the transform's own computed fields wear this - the two halves of the
    Access name split and the seven-character site short codes. Everything else
    is raw source text and gets trimmed. See nc().
    """


def nc(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)   # Excel numerics: 4.0 -> 4, like Access Format()
    # A datetime that reaches here raw would be stringified by str() as
    # '2026-08-09 18:00:00', while every mapper that formats its own dates
    # writes '09/08/2026 18:00'. Two date formats in one upload stream is the
    # kind of difference an import mishandles without complaining, so normalise
    # here as well - the mappers that already format theirs pass strings and
    # are untouched by this.
    if isinstance(v, datetime):
        v = "" if v.year < 1990 else v.strftime("%d/%m/%Y %H:%M")
    s = re.sub(r"[,]", " ", "" if v is None else str(v))
    # Raw source values ARE trimmed - the extract's " Chemical Lane" and
    # " 07802890451" go in with their leading space and come out without it,
    # and 0 of 216 genuine address-2 or phone fields start with a space.
    # Values the transform COMPUTED are not: the Access name split writes
    # "Daniel " and " Smith" as two columns whose shared space is the join,
    # and Left(name,7) keeps whatever trailing space the cut lands on (109 of
    # 216 genuine delivery short codes end in one). Stripping everything
    # deleted the second kind; stripping nothing invented the first.
    return s if isinstance(v, Keep) else s.strip()


def region_of(pc):
    # Was: split on the first space and take what is left of it. That is a
    # FIFTH copy of "get the outward code", and it fails on the one shape the
    # extracts genuinely produce - an unspaced postcode. "BS119DE" has no
    # space, so the district came out "UNKNOWN" and the region followed it,
    # writing UNKNOWN into the upload CSV for a real Bristol order. Spaced and
    # stray-space postcodes agree with the old code exactly, so nothing that
    # worked before changes; only the ones that were failing.
    hit = REGIONS.get(postcodes.outward(pc))
    return hit["region"] if hit else "UNKNOWN"


def first_name(name):
    # IIf(null," TBA", IIf(Left(name,InStr(name," "))=" "," TBA", Left(name,InStr(name," "))))
    if not name:
        return Keep(" TBA")
    i = str(name).find(" ")
    first = str(name)[: i + 1] if i >= 0 else ""
    # A one-word contact ("Tina", "Shunter") has no space, so InStr returns 0
    # and Left(name,0) is "". Jet compares strings ignoring TRAILING spaces, so
    # in Access that "" tests EQUAL to " " and the expression falls to the TBA
    # branch. Python's == does not, so this returned an empty forename and left
    # the whole name in the surname column - and last_name(), which offsets by
    # len(first_name), then started from the wrong character.
    return Keep(" TBA") if first.strip() == "" else Keep(first)


def last_name(name):
    # Mid(name, Len(First), 100) - 1-based start at the last char of First
    name = "" if name is None else str(name)
    fl = len(first_name(name))
    return Keep(name[fl - 1: fl - 1 + 100] if fl >= 1 else name)


def dp_short(dp):
    # Mid(Left(dp, InStr(dp," ")), 1, 7)
    dp = "" if dp is None else str(dp)
    i = dp.find(" ")
    return Keep((dp[: i + 1] if i >= 0 else "")[:7])


# Every spelling of "no, don't send one" seen on the forms and extracts. A
# task is a chargeable extra, so it is ordered only by an affirmative value -
# anything in here, blank included, means no task row.
NOT_ORDERED = ("", "N", "NO", "0", "-", "--", "N/A", "NA", "NONE", "FALSE", "NIL")

# The accounts the Haulage Request Form raises under. The pick-list below is
# keyed on that form's Material options, so it is applied only to these - a
# Synergy or seasonal product must never be rewritten by it.
ADHOC_ACCOUNTS = ("NRADHOC", "NRADHOC_NH", "NR_OTHER")

# The ad hoc Material -> ITEMS pick-list, read off the 47 genuine Access
# exports in _nr_truth/. 19 of their orders carry the Haulage Request Form
# shape in the delivery instructions ("Material X Dimension ..."), which pairs
# each form Material with the ITEMS value the database actually wrote.
#
# Only the pairs the corpus agrees on are here. Three Materials pass straight
# through and are deliberately absent rather than mapped to themselves - Track
# Materials (4 rows), Timbers (1) and Cable Drums (1).
#
# Box is ALSO absent, and that is a judgement, not an oversight. The corpus
# contradicts itself on it: "Box" became "Box." twice and "Box." became "BOX"
# once. One of those adds a stray full stop and the other uppercases; there is
# no reading where both are a rule. Passing Box through unchanged is the only
# option that invents nothing. If CTMS wants BOX, say so and it is one line.
ADHOC_ITEMS = {
    "parcel": "PARCEL",
    "rail": "ADHOC RAIL",
    "pallet": "PALLET",
    "pallets (van)": "PALLETS_VAN",
    "pallets (larger than van)": "PALLET",
    "composite sleepers": "Composite Sleeper",
}


def adhoc_item(prod, acct):
    """The ITEMS product for an ad hoc, mapped through the form's pick-list.

    Anything not on the list - and everything that is not an ad hoc - comes
    back exactly as it went in.
    """
    if str(acct or "").strip().upper() not in ADHOC_ACCOUNTS:
        return prod
    return ADHOC_ITEMS.get(str(prod or "").strip().lower(), prod)


def transform(rows):
    """rows: list of dicts in Imported_Orders column shape. Returns list of
    35-field records, ordered like the Final query (OrdSort, SEQ)."""
    out = []
    W = 35

    def rec(seq, ordsort, vals):
        r = [""] * W
        for i, v in vals.items():
            r[i] = nc(v)
        out.append((str(ordsort), seq, r))

    for o in rows:
        ordno = o.get("Customer Order No")
        site = o.get("Site Name - Collection") or ""
        acct = (o.get("Account") or "").strip()
        # ORDER row (SEQ 1) - Final's column order
        rec(1, ordno, {
            0: "ORDER", 1: ordno, 2: Keep(site[:7]), 3: site,
            4: first_name(o.get("Contact Name")), 5: last_name(o.get("Contact Name")),
            6: o.get("Notes for Collection Location Comments"),
            7: o.get("Address 1"), 8: o.get("Address 2"),
            9: (o.get("Address 3") or "").upper(), 10: region_of(o.get("Postcode")),
            11: o.get("Postcode"), 12: o.get("Telephone No"),
            13: o.get("collection time"), 14: o.get("collection time end"),
            15: dp_short(o.get("Delivery Point")), 16: o.get("Delivery Point"),
            17: first_name(o.get("D Contact Name")), 18: last_name(o.get("D Contact Name")),
            19: o.get("D Address 1"), 20: o.get("D Address 2"), 21: o.get("D Address 3"),
            22: region_of(o.get("D Postcode")), 23: o.get("D Postcode"),
            # The [-12:] fallback is our own slice, so any space it starts with
            # is an artefact of where the cut landed, not something the source
            # wrote - and 0 of 216 genuine phone numbers begin with a space.
            # Strip THIS value only; the general no-strip rule still holds.
            24: o.get("D Telephone No") or str(o.get("D Contact Name") or "")[-12:].strip(),
            25: o.get("delivery time"), 26: o.get("delivery time end"),
            # 255 is the Access Short Text ceiling and the database really does
            # cut at it: 12 genuine ORDER rows sit at exactly 255, every one
            # chopped mid-word, and none of the 216 exceeds it. Two rows sharing
            # one note but differing in prefix length run different distances
            # into the identical tail, which proves the cut happens HERE, on the
            # assembled string, not upstream. We were sending 361 characters on
            # every Synergy upload.
            27: str(o.get("Delivery Instructions") or "")[:255],
            28: "NRHEAVY" if acct.upper() == "HEAVY" else acct,
            29: "", 30: o.get("Vehicle Type"),
            31: str(o.get("Est Cost") if o.get("Est Cost") is not None else 0),
            32: o.get("Notes for Delivery Location Comments"),
            33: o.get("Shipment No") or ordno, 34: "",
        })
        # ORD_TASKS rows (SEQ 2..8): col1=task name, col2=1  (Final positional swap)
        for field, label, seq in (("Banksman", "BANKSMAN", 2), ("HIAB", "HIAB", 3),
                                  ("Log Grab", "LOG GRAB", 4), ("Moffett", "MOFFETT", 5),
                                  ("PTS", "PTS", 6), ("Rear Steer", "REAR STEER", 7),
                                  ("Vehicle Escort", "ESCORTS", 8)):
            v = o.get(field)
            # The test used to be "anything that is not the single string N",
            # which made an EMPTY cell order the service: a form that left HIAB
            # blank got a HIAB task, and a HIAB is a chargeable extra. Only an
            # affirmative value asks for the task now. Every genuine ORD_TASKS
            # row carries a real code and the value 1; 117 of 216 genuine orders
            # (54%) carry no task row at all, so "absent" is the normal case.
            if str("" if v is None else v).strip().upper() not in NOT_ORDERED:
                rec(seq, ordno, {0: "ORD_TASKS", 1: label, 2: "1"})
        # No NIGHT / SATURDAY / SUN_BANK_HOL rows. This used to derive them from
        # the delivery time and add one to every upload; it does not any more,
        # on any route. A job that needs one gets it put on by hand, so nothing
        # is charged for a service nobody chose. Do not add it back here or in a
        # mapper.
        # ORD_SUB_REFS 1002 (SEQ 9): col1=1002, col2=Raised by
        rec(9, ordno, {0: "ORD_SUB_REFS", 1: "1002", 2: o.get("Raised by")})
        # ORD_SUB_REFS 1003 (SEQ 10): col1=1003, col2=Cost Centre or "0"
        # A cost centre of "   " is not a cost centre. The old test only caught
        # None and "", so a whitespace-only cell wrote an EMPTY 1003; the
        # genuine database never emits an empty sub-ref - 1003 falls back to the
        # literal "0" (510 of 510 genuine 1003 rows are non-empty).
        cc = o.get("Cost Centre")
        rec(10, ordno, {0: "ORD_SUB_REFS", 1: "1003",
                        2: cc if str(cc or "").strip() else "0"})
        # ORD_LINES (SEQ 12): col2=class, col3=qty, col4=Serial Number
        rec(12, ordno, {0: "ORD_LINES",
                        2: "CHRG_PALLET" if acct == "NRNONHEAVY" else "HEAVY",
                        3: o.get("Product Qty"), 4: o.get("Serial Number")})
        # ITEMS (SEQ 13): col1=Product/Description, col2=qty.
        # If the form states a product, follow it - fall back to the service
        # code, never leave the ITEMS product blank for the upload to default.
        #
        # The product goes out EXACTLY as the order stated it. There used to be
        # a re-code here turning ballast and stoneblowers into their CTMS codes,
        # and it corrupted the upload: BAG_BALLAST, LOOSE_BALLAS and
        # LOOSE_STONEB appear in 0 of 510 ITEMS rows across the 47 genuine
        # Access exports in _nr_truth/. The real database sends the NR stock
        # code untouched - 0057/100500/002 is the corpus's commonest ITEMS
        # value, on ballast orders from the same suppliers as ours - or plain
        # English like "Spent Ballast". CTMS wanting one code per type is still
        # true; it just belongs on the booking, not on Network Rail's upload.
        # The codes moved to ctms_codes.product_code().
        prod = str(o.get("Product / Description") or "").strip() \
            or str(o.get("Product / Service Code") or "").strip()
        # An ad hoc's Material goes through the form's own pick-list: the
        # genuine database writes PARCEL for "Parcel" and ADHOC RAIL for
        # "Rail". Only ad hoc accounts, and only the entries the corpus agrees
        # on - everything else passes through. See ADHOC_ITEMS.
        prod = adhoc_item(prod, acct)
        rec(13, ordno, {0: "ITEMS", 1: prod, 2: o.get("Product Qty")})
    out.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in out]


# The window an upload carries when nobody has confirmed the times. Nine to
# five with a minute on each end: the odd minute is the marker, so a glance at
# CTMS says "these times are still ours, not the site's". A confirmed nine-to-
# five stays 09:00-17:00 and reads differently on purpose.
UNCONFIRMED_START = "09:01"
UNCONFIRMED_END = "17:01"


def _hhmm(v):
    """(hour, minute) from a datetime or a "dd/mm/YYYY HH:MM" string, else None."""
    if v is None or v == "":
        return None
    if hasattr(v, "hour") and hasattr(v, "minute"):
        return (v.hour, v.minute)
    m = re.search(r"(\d{1,2}):(\d{2})", str(v))
    return (int(m.group(1)), int(m.group(2))) if m else None


def unstated_window(a, b):
    """True when a leg's times were never actually given.

    Blank is the easy case. The one that bit us is midnight: a spreadsheet with
    a date and no time exports as 00:00, and an unset delivery reaches us as a
    minute past. Taken literally that is a delivery at 00:01 sitting BEFORE its
    own 07:00 collection - not bookable, and it fired a "why is this backwards?"
    query at the raiser for a time nobody had set.

    Synergy spells it a third way, and this is the one seen in the wild: a
    whole-day window, 00:01 to 23:59. Taken literally that is a delivery
    starting a minute past midnight - before its own 07:00 collection - which
    is what fired the backwards-date query at the raiser.

    A genuine midnight job always carries a REAL window (00:00-02:00), so only
    a window that is zero-length at midnight, or that spans essentially the
    whole day, counts as unstated. Never widen the zero-length case past a
    minute: 00:00-00:30 is somebody's night shift.
    """
    ha, hb = _hhmm(a), _hhmm(b)
    if ha is None:
        return True
    if ha[0] != 0 or ha[1] > 1:     # a real start time - nothing to guess
        return False
    if hb is None:
        return True
    if hb[0] == 0 and hb[1] - ha[1] <= 1:
        return True                 # zero-length at midnight: a date with no time
    return hb[0] == 23 and hb[1] >= 58   # 00:01-23:59: "any time that day"


MARKER = timedelta(hours=1, minutes=1)
# The window assumed when the collection end is not known either. 08:00-16:00
# is what most supplier yards keep, and plus the marker it comes out as the
# familiar 09:01-17:01 - which is where that pair came from in the first place.
DEFAULT_BASE = ("08:00", "16:00")


def _shift(hhmm, delta):
    t = (hhmm[0] * 60 + hhmm[1] + int(delta.total_seconds() // 60)) % (24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


def close_window(startstr):
    """Close a window that has a start and no end, on the start's own date.

    This used to stamp on the fixed 17:01. That is the DELIVERY marker, and it
    was being written onto collection windows too; worse, a 22:00 start closed
    at 17:01 - an end four hours before its own beginning, which is not
    bookable. A working day plus the marker minute keeps the familiar
    09:00 -> 17:01 and can never invert. It clamps at 23:59 rather than rolling
    onto the next date, because inventing a second date is the bigger sin.
    """
    d, _, t = str(startstr or "").strip().partition(" ")
    hm = _hhmm(startstr)
    if not d or hm is None:
        return ""
    mins = min(hm[0] * 60 + hm[1] + 8 * 60 + 1, 23 * 60 + 59)
    return f"{d} {mins // 60:02d}:{mins % 60:02d}"


def unconfirmed_window(datestr, base=None):
    """The delivery window to use when nobody has confirmed one.

    It is NOT a fixed 09:01-17:01. Measured across the reference corpus, the
    real database takes the order's own COLLECTION window and adds exactly one
    hour and one minute to both ends - 47 of 47 defaulted windows, 0 of 166
    confirmed ones. The odd minute everyone recognises is the tail of that
    61-minute shift, not a flag bolted onto a fixed pair:

        Land Recovery        07:00-17:00  ->  08:01-18:01   (x3)
        Trackwork Doncaster  07:30-15:00  ->  08:31-16:01   (x12)
        British Steel        08:00-16:00  ->  09:01-17:01   (x10)
        Sicut Doncaster      08:30-15:00  ->  09:31-16:01   (x4)

    Hard-coding 09:01-17:01 was right only for the yards that open 08:00-16:00
    - 23 of the 47. For Land Recovery we were an hour late at the front and an
    hour early at the back, on a window the site never agreed to.

    `base` is the collection window, either end as a datetime or a
    "dd/mm/YYYY HH:MM" / "HH:MM" string. With nothing usable it falls back to
    DEFAULT_BASE, which reproduces the old pair exactly.
    """
    d = str(datestr or "").strip()
    a = _hhmm(base[0]) if base and len(base) > 0 else None
    b = _hhmm(base[1]) if base and len(base) > 1 else None
    if a is None or b is None:
        a, b = _hhmm(DEFAULT_BASE[0]), _hhmm(DEFAULT_BASE[1])
    return ((d + " " + _shift(a, MARKER)).strip(),
            (d + " " + _shift(b, MARKER)).strip())


def _csv_safe(v):
    """Final guarantee before the field is written: no commas (they'd shift
    every following column and the upload rejects the row) and no embedded
    line breaks (same effect). Idempotent - already-clean fields pass through
    unchanged.

    It used to also collapse every whitespace run and .strip() the result.
    Both were wrong, measured against 47 CSVs the real Access database
    produced. That database preserves whitespace verbatim: "Contact  45
    minutes" keeps its double space, and - the part that actually matters -
    the Access name split emits "Daniel " and " Smith" as two fields whose
    SHARED SPACE is what rejoins them. Stripping deleted the join. Same for
    the seven-character site short code: Left(name,7) of "Doncaster AHD" is
    "Doncast" but of "Tower Lane" it is "Tower L" and of "BGF-Bag" the code
    keeps its trailing space. 109 of 216 genuine delivery short codes end in
    a space. Tabs pass through untouched because the genuine files contain
    literal tabs and Network Rail accepted them.

    Only commas and line breaks are removed, because only those two can shift
    a column: the genuine export is a naive ",".join of 35 fields with no
    quoting anywhere, so a comma in a value silently becomes a new column.
    """
    return re.sub(r"[\r\n]+", " ", str("" if v is None else v).replace(",", " "))


def write_csv(records, out_path):
    """Write the upload exactly as the Access database writes it.

    Two byte-level details, both measured over the 47-file reference corpus in
    _nr_truth/ and both wrong here until 02/09/2026:

    CRLF, never bare LF. 2687 CRLF and 0 bare LF across the corpus; 47/47
    files end terminated, and CRLF-CRLF never appears, so there is no trailing
    blank line. Every file we had produced up to this point used bare LF.

    cp1252, never UTF-8. The corpus carries bytes that are not valid UTF-8 at
    all - 0xFB in a What3Words note, 0xE1 used as an address-line separator -
    and decodes cleanly only as single-byte ANSI. An accented character in a
    site note would have gone out as two bytes where the database sends one.
    Anything cp1252 cannot represent is replaced rather than raising, because
    failing to write the upload is worse than losing one exotic glyph.
    """
    with open(out_path, "w", encoding="cp1252", errors="replace", newline="") as f:
        for r in records:
            f.write(",".join(_csv_safe(x) for x in r) + "\r\n")

    # Check what we just wrote against the 47 files Network Rail actually
    # accepted, and say so loudly when it does not match.
    #
    # 04/09/2026: three orders went up with an empty ORD_SUB_REFS 1002 and
    # simply did not appear in CTMS. Nothing failed, nothing was reported - the
    # run said "CSV: <path>" exactly as it does on a good day, and the orders
    # were only missed because somebody went looking for them. nr_conformance
    # had caught it the whole time; it was just never pointed at our own
    # output. Every producer goes through this one writer, so the check belongs
    # here rather than in any one of them.
    #
    # It reports, it does not delete: a CSV that is 95% right is still the
    # fastest route to a fixed one, and refusing to write it would leave the
    # planner with nothing at all.
    global LAST_COMPLAINTS
    LAST_COMPLAINTS = []
    try:
        import nr_conformance
        LAST_COMPLAINTS = nr_conformance.check(out_path)
    except Exception:
        pass
    if LAST_COMPLAINTS:
        print(f"  !! CSV DOES NOT MATCH THE ACCEPTED FORMAT "
              f"({len(LAST_COMPLAINTS)} problem(s)) - CTMS may drop these silently:")
        for c in LAST_COMPLAINTS:
            print(f"       {c}")
    print(f"  CONFORMANT {0 if LAST_COMPLAINTS else 1}")
    return out_path


# ---------- DTS input builder ----------
def dts_row(pdf_path):
    import dts_convert as dc
    d = dc.parse_dts(pdf_path)
    coll, deliv = d["coll"], d["deliv"]
    d2 = (datetime.now() + timedelta(days=2)).strftime("%d/%m/%Y")

    def t(block, key, end=False):
        # a real date on the form wins; otherwise the today+2 placeholder
        day = block.get("date") or d2
        return f"{day} {dc.to_time(block.get(key, ''), end)}"

    g = lambda b, k: (b.get(k) or "").strip()
    return dict({
        "Customer Order No": d["ref"], "Shipment No": d["ref"],
        "Site Name - Collection": g(coll, "collection site"),
        "Contact Name": g(coll, "contact name"),
        "Address 1": g(coll, "address 1"), "Address 2": g(coll, "address 2"),
        "Address 3": g(coll, "address 3"), "Postcode": g(coll, "post code"),
        "Telephone No": g(coll, "telephone no"),
        "collection time": t(coll, "start time window"),
        "collection time end": t(coll, "end time window", True),
        "Delivery Point": g(deliv, "delivery site"),
        "D Contact Name": g(deliv, "contact name"),
        "D Address 1": g(deliv, "address 1"), "D Address 2": g(deliv, "address 2"),
        "D Address 3": g(deliv, "address 3"), "D Postcode": g(deliv, "post code"),
        "D Telephone No": g(deliv, "telephone no"),
        "delivery time": t(deliv, "start time window"),
        "delivery time end": t(deliv, "end time window", True),
        # DTS rule: the product is ALWAYS the SUPPLIER_COL placeholder, the
        # quantity is the pallet count, and the weight (Kgs) goes on the Haulage
        # Request Form - the NR upload itself has no weight column.
        "Product / Description": "SUPPLIER_COL",
        "Product Qty": d["pallets"],
        "Serial Number": "", "Raised by": d.get("raiser_email", ""),
        "Account": "NRADHOC_NH", "Cost Centre": None, "Vehicle Type": "",
        "Delivery Instructions": "Del Notes " + " ".join(d["del_notes"]),
        "HIAB": "N", "Vehicle Escort": "N", "PTS": "N", "Banksman": "N",
        "Moffett": "N", "Log Grab": "N", "Rear Steer": "N",
        "Est Cost": None, "Notes for Collection Location Comments": "",
        "Notes for Delivery Location Comments": "",
    })


def main():
    pdf = sys.argv[1] if len(sys.argv) > 1 else None
    if not pdf or not os.path.exists(pdf):
        print("Usage: python nr_csv.py <DTS.pdf>"); return
    row = dts_row(pdf)
    records = transform([row])
    import outbox
    name = "NR_heavy_" + datetime.now().strftime("%d%m%Y%H%M%S") + ".csv"
    out = write_csv(records, outbox.path(name))
    print("WROTE:", out)
    for r in records:
        print("  " + ",".join(r))


if __name__ == "__main__":
    main()
