"""UK postcode helpers - ONE correct implementation, imported everywhere.

There were four copies of "get the outward code" scattered across the toolkit
and three of them were wrong in the same way: they stripped the space and then
let a greedy pattern swallow the first character of the INWARD code.

    "DN3 1ED"  ->  DN31  (Grimsby)      instead of DN3  (Doncaster)   ~40 mi out
    "PE3 6DW"  ->  PE36  (Hunstanton)   instead of PE3  (Peterborough) ~50 mi out
    "CV3 6PH"  ->  CV36  (Shipston)     instead of CV3  (Coventry)     ~30 mi out

That put map pins, distance rankings and quote lanes tens of miles wrong.

The rule that actually holds: a UK inward code is ALWAYS exactly three
characters (digit + two letters). So the outward code is simply everything
except the last three - no pattern matching, no ambiguity, and it works whether
the postcode arrives spaced, unspaced or with stray spaces in the middle.
"""
import re


def compact(pc):
    """Letters and digits only, uppercased: 'le12 9 bs' -> 'LE1299BS'-safe form."""
    return re.sub(r"[^A-Za-z0-9]", "", str(pc or "")).upper()


def norm(pc):
    """Canonical 'OUTWARD INWARD' form, whatever shape it arrived in:
    'BS119DE' / 'le12 9 bs' / 'DN16  1BP ' -> 'BS11 9DE' / 'LE12 9BS' / 'DN16 1BP'.
    Use this as the key for any postcode-keyed cache so the same place can't be
    stored twice under two spellings."""
    s = compact(pc)
    return f"{s[:-3]} {s[-3:]}" if len(s) > 3 else s


def outward(pc):
    """The outward (district) code: 'DN3 1ED' -> 'DN3', 'DN16 1BP' -> 'DN16',
    'EC1A 1BB' -> 'EC1A'. Empty when there isn't enough to be a postcode."""
    s = compact(pc)
    return s[:-3] if len(s) > 3 else ""


def area(pc):
    """The area (letters only): 'DN3 1ED' -> 'DN'. Accepts a postcode or an
    already-extracted outward code."""
    m = re.match(r"[A-Z]+", compact(pc))
    return m.group(0) if m else ""
