"""
Media Sets: a week of courier runs -> the Network Rail upload CSV.

    python media_sets.py "Week 19 2026 Courier.xlsx"
    python media_sets.py "Week 19 2026 Courier.xlsx" 19      (force the week number)

The same shape as the Synergy upload, through a different form. The weekly
courier sheet carries 19 columns that line up one-for-one with the Media Sets
Input Sheet's columns B..T, and that form's RHPC Admin sheet is the SAME 47-
column contract the Synergy master sheet and the Haulage Request Form use - so
the finished rows go through nr_csv exactly like every other upload. Nothing
here is a second CSV writer.

Two things come out, both into the outbox:

  * the filled Media Sets Input Sheet - the human record, the thing you would
    have typed by hand, with the audit-check column intact
  * the NR upload CSV - what actually gets uploaded

Like synergy_map.py the CSV is built from values computed HERE, not read back
out of the saved workbook. The form's formulas are reproduced in code so the
output does not depend on Excel being installed, does not need COM, and cannot
blow the agent's 600-second subprocess timeout on a long week.

Sends nothing. Writes only into the outbox.
"""
import os
import re
import shutil
import sys
from datetime import datetime, date, time, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import nr_csv                      # noqa: E402  the ONE csv writer
import outbox                      # noqa: E402

TEMPLATE = os.path.join(HERE, "media_sets_template.xlsx")

# Baked into every row by the form itself (RHPC Admin, columns Y/Z/AF/AG/AP).
PRODUCT_CODE = "MEDIA_SETS"
# nr_csv's ITEMS line takes the DESCRIPTION first and only falls back to the
# code, so both carry MEDIA_SETS - otherwise the CSV would still read
# "Media Sets" however the code was spelled.
PRODUCT_DESC = "MEDIA_SETS"
ACCOUNT = "NRADHOC"
COST_CENTRE = "618294"
CONFIRMATION_EMAILS = ("Sophie.Robinson@networkrail.co.uk; "
                       "David.Whiston@networkrail.co.uk; "
                       "Richard.Wilkinson-Ford@networkrail.co.uk")

# The Input Sheet has 25 numbered rows but RHPC Admin only carries formulas for
# 23 of them (rows 3..25 <- input rows 5..27). Orders 24 and 25 would be typed
# in and then silently never reach the upload. We compute the CSV ourselves so
# OUR output is not capped - but the filled sheet still is, so say so.
SHEET_ROWS = 23

# The courier sheet repeats header names - "Address 1" is both D and L,
# "Postcode" is G and O, "Collection Time Start" is I and Q (the delivery pair
# is mislabelled in the source). Matching by name would mis-map those, so the
# contract is POSITION, and the headers are verified against it instead.
EXPECTED = [
    "site name - collection", "contact name", "order contact no",
    "address 1", "address 2", "address 3", "postcode",
    "collection date", "collection time start", "collection time end",
    "site name - delivery point", "address 1", "address 2", "address 3",
    "postcode", "delivery date", "collection time start", "collection time end",
    "product qty",
]


def _norm(h):
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for f in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v).strip()[:10], f).date()
        except Exception:
            pass
    return None


def _as_time(v):
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, (int, float)):        # Excel serial fraction of a day
        secs = int(round(float(v) % 1 * 86400))
        return (datetime.min + timedelta(seconds=secs)).time()
    for f in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(str(v).strip(), f).time()
        except Exception:
            pass
    return None


def _stamp(d, t):
    """Date + time -> one datetime, the way the form's L3+J5 arithmetic does."""
    if d is None:
        return ""
    return datetime.combine(d, t or time(0, 0))


def week_of(path, sheet_name, override=None):
    """Week number: an explicit argument wins, then the sheet name, then the
    filename. 'Week 19' and 'Week 19 2026 Courier.xlsx' both give 19."""
    if override:
        return str(override).strip()
    for text in (sheet_name or "", os.path.basename(path)):
        m = re.search(r"week\s*(\d{1,2})", str(text), re.I)
        if m:
            return m.group(1)
    return ""


def read_courier(path):
    """(rows, sheet_name) - the 19 columns, positionally, headers verified."""
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    hdr = [_norm(ws.cell(row=1, column=c).value) for c in range(1, 20)]
    if hdr != EXPECTED:
        wb.close()
        diff = [f"col {chr(64 + i + 1)}: expected {EXPECTED[i]!r}, found {hdr[i]!r}"
                for i in range(min(len(hdr), len(EXPECTED))) if hdr[i] != EXPECTED[i]]
        raise SystemExit("The courier sheet's columns are not what Media Sets expects.\n  "
                         + "\n  ".join(diff or ["column count differs"])
                         + "\nNothing written - the columns repeat names, so guessing "
                           "which is which would silently swap collection and delivery.")
    rows = []
    for r in range(2, ws.max_row + 1):
        vals = [ws.cell(row=r, column=c).value for c in range(1, 20)]
        if all(v in (None, "") for v in vals):
            continue
        if not str(vals[0] or "").strip():        # no collection site = not a job
            continue
        rows.append(vals)
    name = ws.title
    wb.close()
    return rows, name


def to_orders(rows, week):
    """The 47-column dicts, reproducing the form's RHPC Admin formulas."""
    out, problems = [], []
    for i, v in enumerate(rows, start=1):
        (csite, contact, phone, a1, a2, a3, pc, cdate, cstart, cend,
         dsite, d1, d2, d3, dpc, ddate, dstart, dend, qty) = v

        cd, dd = _as_date(cdate), _as_date(ddate)
        ct = _stamp(cd, _as_time(cstart))
        cte = _stamp(cd, _as_time(cend))
        dt = _stamp(dd, _as_time(dstart))
        dte = _stamp(dd, _as_time(dend))

        # The form's own audit check: collection must not be after delivery.
        if isinstance(ct, datetime) and isinstance(dt, datetime) and ct > dt:
            problems.append(f"row {i} ({csite} -> {dsite}): collection "
                            f"{ct:%d/%m %H:%M} is AFTER delivery {dt:%d/%m %H:%M}")

        # "MS"&week&"/"&n&"/"&DAY&"/"&MONTH&"/"&YEAR&"/"&LEFT(postcode,2)
        ref = ""
        if cd:
            ref = (f"MS{week}/{i}/{cd.day}/{cd.month}/{cd.year}/"
                   f"{str(pc or '').strip()[:2].upper()}")

        out.append({
            "Customer Order No": ref, "Shipment No": ref,
            "Site Name - Collection": csite,
            "Contact Name": contact, "Order Contact Name": contact,
            "Order Contact No": phone, "Telephone No": phone,
            "Address 1": a1, "Address 2": a2, "Address 3": a3, "Postcode": pc,
            "Collection Date": cd,
            "collection time": ct, "collection time end": cte,
            "Delivery Point": dsite, "D Contact Name": contact,
            "D Address 1": d1, "D Address 2": d2, "D Address 3": d3,
            "D Postcode": dpc, "D Telephone No": phone,
            "Delivery Date": dd,
            "delivery time": dt, "delivery time end": dte,
            "Product / Service Code": PRODUCT_CODE,
            "Product / Description": PRODUCT_DESC,
            "Product Qty": qty,
            "Raised by": CONFIRMATION_EMAILS,
            "Account": ACCOUNT, "Order Type": "C",
            "Vehicle Escort": "N", "PTS": "N", "Banksman": "N", "Log Grab": "N",
            "Cost Centre": COST_CENTRE,
        })
    return out, problems


def fill_sheet(rows, week, out_path):
    """A copy of the real Input Sheet with this week's rows typed in."""
    if not os.path.exists(TEMPLATE):
        print(f"  (no {os.path.basename(TEMPLATE)} here - skipping the filled sheet)")
        return None
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    shutil.copyfile(TEMPLATE, out_path)
    wb = openpyxl.load_workbook(out_path)          # keep the formulas
    ws = wb["Input Sheet"]
    if week:
        ws["C1"] = int(week) if str(week).isdigit() else week
    for n, v in enumerate(rows[:SHEET_ROWS]):
        r = 5 + n
        for c, val in enumerate(v):                # data A..S -> sheet B..T
            ws.cell(row=r, column=2 + c).value = val
    wb.save(out_path)
    wb.close()
    return out_path


def main():
    args = [a for a in sys.argv[1:]]
    if not args or not os.path.exists(args[0]):
        print(__doc__)
        print("MEDIA_RESULT orders=0")
        return 2
    src = args[0]
    override = args[1] if len(args) > 1 else None

    rows, sheet_name = read_courier(src)
    week = week_of(src, sheet_name, override)
    print(f"Media Sets - week {week or '?'} - {len(rows)} courier run(s) "
          f"from {os.path.basename(src)}\n")
    if not rows:
        print("Nothing to do - no rows with a collection site.")
        print("MEDIA_RESULT orders=0")
        return 0
    if not week:
        print("  !! no week number in the sheet name or filename - the order")
        print("     references will read 'MS//...'. Pass one: media_sets.py <file> 19")

    orders, problems = to_orders(rows, week)

    import services
    for o in orders:
        svc = services.for_delivery(o.get("delivery time"))
        print(f"  {o['Customer Order No'] or '(no ref)':26} "
              f"{str(o['Site Name - Collection'])[:26]:26} {str(o['Postcode'] or ''):9}"
              f" -> {str(o['Delivery Point'])[:12]:12} {str(o['D Postcode']):9}"
              f" {('  ' + ', '.join(svc)) if svc else ''}")

    # An unrecognised outward code ships as the literal 'UNKNOWN' rather than
    # failing, so count them here instead of letting them through unremarked.
    unknown = [o for o in orders if nr_csv.region_of(o.get("Postcode")) == "UNKNOWN"
               or nr_csv.region_of(o.get("D Postcode")) == "UNKNOWN"]
    if unknown:
        print(f"\n  !! {len(unknown)} row(s) have a postcode with no region - they will "
              f"upload as UNKNOWN:")
        for o in unknown[:8]:
            print(f"       {o['Customer Order No']}  {o['Postcode']} -> {o['D Postcode']}")
    # Dates that run backwards are a question for whoever raised the sheet, not
    # something to guess at here - so the email that asks is staged for review
    # rather than the run quietly carrying on.
    import date_query
    backwards = date_query.raise_query(
        orders, CONFIRMATION_EMAILS, f"Media sets week {week or '?'}")
    if backwards:
        print(f"\n  !! {len(backwards)} DELIVERY BEFORE COLLECTION - not bookable as they stand:")
        for p in backwards:
            print(f"       {p['ref']}  collect {p['collection']}  "
                  f"deliver {p['delivery']}  ({p['back_by']} earlier)")
        print("     An email asking them to confirm is ready for Review & send.")
    if problems and not backwards:
        print(f"\n  !! {len(problems)} DATE ERROR(S) - the form would flag these:")
        for p in problems:
            print(f"       {p}")
    if len(rows) > SHEET_ROWS:
        print(f"\n  !! {len(rows)} rows but the Input Sheet's RHPC Admin only carries "
              f"{SHEET_ROWS} - the filled sheet shows the first {SHEET_ROWS}. "
              f"The CSV below has all {len(rows)}.")

    stamp = datetime.now().strftime("%d%m%Y%H%M%S")
    sheet_out = fill_sheet(rows, week, outbox.path(f"Media Sets Week {week or 'x'} {stamp}.xlsx"))
    csv_out = outbox.path(f"NR_media_sets_wk{week or 'x'}_{stamp}.csv")
    nr_csv.write_csv(nr_csv.transform(orders), csv_out)

    print()
    if sheet_out:
        print(f"  SHEET: {sheet_out}")
    print(f"  CSV  : {csv_out}")
    try:
        import metrics
        metrics.log("media_sets_built", orders=[o["Customer Order No"] for o in orders],
                    what=f"week {week}")
    except Exception:
        pass
    print(f"MEDIA_RESULT orders={len(orders)} backwards={len(backwards)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
