"""The weight on each order of an NR upload CSV - set in CTMS straight after the import.

CTMS's NRHEAVY_Order_Import reads no weight at all. Its field map (C-TMS Modules >
Maintenance > Imports) takes ITEM_ID and ITEM_QTY from an ITEMS row and LINE_PRODUCT,
LINE_DU_TYPE, LINE_QTY and LENGTH from an ORD_LINES row - nothing else - so an imported
order arrives at its quantity, not its weight: a 12 kg box came in as weight 1 (29/10).
The weight has to be typed in afterwards, and this says what to type.

The weight we do know rides as text in the order's Delivery Instructions - the forms
write "Weight - 12kg-", repair_weights adds "/ Weight 32 kg", and a DTS upload leads
with "Weight - 3061kg-" - so it is read back out of the CSV itself. Whatever made the
upload, the run sets what the upload says.

It never guesses. No unit, a weight "each", a range, or a tonnage that is really a
vehicle ("7.5ton vehicle") gives no weight, with the reason, and that order is left for
Delali to set by hand. A wrong weight costs more than a missing one: a haulier prices
off it and a vehicle is picked for it.

    python upload_weights.py NR_heavy_....csv      each order's ref and the weight to set
"""
import re
import sys

_QUALIFIER = r"(?:(?:approx\w*|circa|about|around|roughly|ca)\.?\s*)?"
# Commas never reach the CSV (nr_csv._csv_safe turns them into spaces), so "1,200kg"
# arrives as "1 200kg" - a group of exactly three digits after a space is thousands.
_NUMBER = r"(\d{1,3}(?:[ ,]\d{3})+|\d+)(\.\d+)?"
_WEIGHT = re.compile(r"\bweights?\b\W{0,6}?" + _QUALIFIER + _NUMBER +
                     r"\s*(kilograms?|kilos?|kgs?|tonnes?|tons?|t)?(?![a-z0-9])", re.I)
_VEHICLE = re.compile(r"\s*-?\s*(?:vehicle|veh\b|truck|lorry|rigid|artic|van\b|wagon)", re.I)
_EACH = re.compile(r"\s*(?:each|per\b|a\s+piece|/\s*(?:item|unit|pallet|box|bag|drum))", re.I)
MAX_KG = 44000          # the heaviest legal UK lorry - anything over it is a typo, not a load


def kg(text):
    """(kilograms, why) from an order's Delivery Instructions; kilograms is None when
    the text does not say one weight plainly, and why says what it said instead."""
    text = str(text or "")
    m = _WEIGHT.search(text)
    if not m:
        return None, "no weight in the instructions"
    said = text[m.start():m.end() + 14].strip()
    number = float(re.sub(r"[ ,]", "", m.group(1)) + (m.group(2) or ""))
    unit = (m.group(3) or "").lower()
    rest = text[m.end():]
    if not unit:
        return None, f"no unit on the weight ({said!r})"
    if _VEHICLE.match(rest):
        return None, f"that is a vehicle size, not a weight ({said!r})"
    if _EACH.match(rest):
        return None, f"a weight each, not the load's ({said!r})"
    value = number * 1000 if unit.startswith("t") else number
    if not 0 < value <= MAX_KG:
        return None, f"{value:g} kg cannot be one load ({said!r})"
    return (int(value) if float(value).is_integer() else round(value, 1)), said


def orders(path):
    """[(ref, kilograms, why)] for every ORDER row of an upload CSV, in file order.

    The file is nr_csv.write_csv's: cp1252, a plain ",".join with no quoting (values never
    hold a comma), ORDER rows' column 2 the ref and column 28 the Delivery Instructions."""
    with open(path, encoding="cp1252", errors="replace", newline="") as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        cells = line.split(",")
        if cells[0] == "ORDER" and len(cells) > 27:
            out.append((cells[1].strip(), *kg(cells[27])))
    # One weight copied onto several orders of a file may be each order's or the whole
    # consignment's ("Weight 126Kg" on both orders of one file, 28/10) - the text cannot
    # say which, and setting it on each would double it. None of them is set.
    shared = {}
    for ref, weight, why in out:
        if weight is not None:
            shared.setdefault((weight, why), []).append(ref)
    return [(ref, None, f"the same weight is on {len(shared[(weight, why)])} orders in this file - "
                        f"each, or between them? ({why!r})")
            if weight is not None and len(shared[(weight, why)]) > 1 else (ref, weight, why)
            for ref, weight, why in out]


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    for ref, weight, why in orders(argv[0]):
        print(f"{ref}  {weight} kg  - from {why!r}" if weight is not None
              else f"{ref}  NO WEIGHT - set it by hand: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
