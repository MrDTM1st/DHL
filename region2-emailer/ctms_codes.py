"""The product code CTMS wants when a job is BOOKED.

This is not what goes on the Network Rail upload CSV. That distinction is the
whole reason this file exists.

CTMS wants one code per product type, because the extracts describe ballast a
dozen ways - "BALLAST 1 TONNE BAGS", "BALLAST 20MM - Loose", "Ballast",
sometimes only in the service code - and a booking screen cannot take a dozen
spellings of one thing. That requirement is real and unchanged.

What was wrong was where it got applied. The coding was put on the ITEMS row of
the NR upload CSV, and measured against 47 CSVs the original Access database
produced, those codes appear in 0 of 510 genuine ITEMS rows. The real database
sends the NR stock code untouched - 0057/100500/002 is the single commonest
ITEMS value in the whole corpus, on ballast orders - or plain English like
"Spent Ballast". Two of our own ballast orders went out as BAG_BALLAST where
the genuine file for the same supplier, same account, same series carried the
stock code. The upload is Network Rail's system speaking its own language; CTMS
is a different system with a different vocabulary, and translating one into the
other on the way out corrupted the upload.

So the NR upload keeps the stock code, and the code below is what the CTMS
booking path calls instead. That path is specified in CTMS_BOOKING_SPEC.md but
not built yet - it is blocked on the screen walkthrough - so nothing imports
this today. It is here, tested and ready, so the booking work picks it up
rather than re-deriving it from the same wrong place.

LOOSE_BALLAS and LOOSE_STONEB really are twelve characters. They are not
truncations to be tidied up - the same lesson as SUN_BANK_HOL, which CTMS
rejected when it was sent as SUN/BANK_HOL.
"""
import build_drafts as bd   # is_stoneblower / is_loose_ballast live there
                            # already; a second copy is how they drift apart

BAG_BALLAST = "BAG_BALLAST"
LOOSE_BALLAST = "LOOSE_BALLAS"
LOOSE_STONEBLOWER = "LOOSE_STONEB"


def product_code(desc, code=""):
    """The CTMS product code for an order, or None if it has no special one.

    None means "CTMS has no code for this" - sleepers, rails, TG60, media sets
    and everything else book under their own description. Returning None rather
    than a guess keeps the caller honest: it has to decide what to do with an
    unmapped product instead of silently sending it the wrong code.

    Stoneblower is tested FIRST. A stoneblower line can mention ballast and
    would otherwise be coded as one. Loose is not a flavour of bagged either:
    it rides in a tipper and bagged does not, so the two must never collapse
    together.
    """
    blob = (str(desc or "").strip() + " " + str(code or "").strip()).strip()
    if not blob:
        return None
    if bd.is_stoneblower(blob):
        return LOOSE_STONEBLOWER
    if "ballast" in blob.lower():
        return LOOSE_BALLAST if bd.is_loose_ballast(blob) else BAG_BALLAST
    return None
