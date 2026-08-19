"""
Process a WORD "Transport Request Form" (.doc/.docx) as an ad hoc.

The Excel Haulage Request Form has an RHPC Admin row that process_form.py
reads straight off. Network Rail's own Word transport request form has no
such row - it is a two-column label/value table typed by the requester - so
this module reads that table, maps it into the same form-row shape, and hands
it to the SAME tail every other ad hoc route uses:

    row -> process_form.to_transform_row -> nr_csv.transform -> write_csv
        -> process_form.save_adhocs   (so the job pins on the dashboard map)

Nothing here invents a date. A field the requester left blank comes out blank
and is reported, exactly as on the Excel path.

    python process_word_form.py "<path to Transport request form.doc>"
"""
import sys, os, re
from datetime import datetime

import nr_csv, outbox, postcodes, process_form

HERE = os.path.dirname(os.path.abspath(__file__))

# The form's own address block ends on a country line - it is not an address
# line and must not be mistaken for the town.
COUNTRIES = {"england", "scotland", "wales", "uk", "united kingdom", "gb"}
PC_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*(?:[-‐-―~]|to)\s*(\d{1,2})[:.](\d{2})")
DATE_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")


# ---------- reading the document ----------
def read_cells(path):
    """Every table cell of the form as text, paragraph marks kept as newlines.

    Word is the only thing on this machine that can open a 97-2003 .doc, so it
    does the reading - invisible, read-only, never touching the file.
    """
    import win32com.client
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    cells = []
    try:
        doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True,
                                  ConfirmConversions=False, AddToRecentFiles=False)
        try:
            for ti in range(1, doc.Tables.Count + 1):
                t = doc.Tables(ti)
                for r in range(1, t.Rows.Count + 1):
                    for c in range(1, t.Columns.Count + 1):
                        try:
                            txt = t.Cell(r, c).Range.Text
                        except Exception:
                            continue    # merged cell - already read on its own row
                        txt = txt.replace("\x07", "").replace("\r", "\n")
                        cells.append(_clean(txt))
        finally:
            doc.Close(False)
    finally:
        word.Quit()
    return cells


def _clean(s):
    """Tidy one cell: Word's smart punctuation and non-breaking spaces become
    plain ASCII, runs of blank lines collapse, trailing space goes."""
    s = (str(s or "").replace(" ", " ").replace("’", "'")
         .replace("‘", "'").replace("“", '"').replace("”", '"'))
    s = re.sub(r"[‐-―]", "-", s)          # en/em dashes -> hyphen
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines).strip("\n ")


# ---------- pulling values out ----------
def _cell_with(cells, *labels):
    """The first cell whose text contains one of these labels."""
    for c in cells:
        low = c.lower()
        for lb in labels:
            if lb.lower() in low:
                return c
    return ""


def _after(cell, *labels):
    """What the requester typed after a label, to the end of that line.

    Labels on this form end in ':' or '-' ("Delivery Site Contact Name-"), and
    some carry a bracketed instruction ("Other (please state):") - all of which
    the requester types straight past, so the split is on the punctuation.
    """
    for lb in labels:
        m = re.search(re.escape(lb) + r"\s*(?:\([^)]*\))?\s*[:\-]\s*", cell, re.I)
        if m:
            return cell[m.end():].split("\n")[0].strip(" -–")
    return ""


def _first_date(text):
    """dd/mm/yyyy from anywhere in the text, as a date - or None. Two-digit
    years are this century; the forms are never historic."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime(y, mth, d)
    except ValueError:
        return None


def _window(text):
    """('08:00','16:00') from an 'Open Hours: 08:00 - 16:00' line, else ('','')."""
    m = TIME_RE.search(text or "")
    if not m:
        return "", ""
    return f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}"


def _at(day, hhmm):
    """A form date + 'HH:MM' as a datetime, so the record carries the same
    shape the Excel path produces. No date -> nothing; a time is never
    attached to a day that was not given."""
    if not day or not hhmm:
        return None
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m))


def _address(cell, label):
    """Split an address block into (site, addr1, addr2, town, postcode).

    Line 1 is the site name, the last real line carries town/county/postcode,
    and whatever sits between is the street - comma-separated on one line as
    often as it is on two, so it is flattened either way.
    """
    lines = [ln.strip(" ,") for ln in cell.split("\n")]
    if lines:
        lines[0] = _after(lines[0], label) or lines[0]
    lines = [ln for ln in lines if ln and ln.lower().strip(". ") not in COUNTRIES]
    if not lines:
        return "", "", "", "", ""
    site, rest = lines[0], lines[1:]
    pc = ""
    for i in range(len(rest) - 1, -1, -1):
        m = PC_RE.search(rest[i])
        if m:
            pc = f"{m.group(1).upper()} {m.group(2).upper()}"
            # what is left of that line is town (+ county in capitals)
            tail = PC_RE.sub("", rest[i]).strip(" ,")
            rest = rest[:i]
            break
    else:
        tail = rest.pop() if rest else ""
    # "Retford NOTTINGHAMSHIRE" -> town Retford; the county is dropped, the
    # region on the upload comes from the postcode district, never from text
    town = re.sub(r"\s+[A-Z][A-Z\s&']{3,}$", "", tail).strip() or tail
    parts = [p.strip() for ln in rest for p in ln.split(",") if p.strip()]
    a1 = parts[0] if parts else ""
    a2 = " ".join(parts[1:]) if len(parts) > 1 else ""
    return site, a1, a2, town, pc


def _items(cells):
    """The item grid - laid out as plain paragraphs inside one cell, not a real
    table, so it is read by shape: a works-order reference, a description, and
    a quantity. Returns (w_order, description, qty, weight, dims)."""
    cell = _cell_with(cells, "Description of Item")
    body = re.split(r"description of item\s*:?", cell, flags=re.I)[-1]
    # drop the column headings before looking at what was typed under them
    for h in ("ITEM", "W / ORDER", "W/ORDER", "DESCRIPTION", "QUANTITY",
              "WEIGHT", "DIMS"):
        body = re.sub(r"^\s*" + re.escape(h) + r"\s*$", "", body,
                      flags=re.I | re.M)
    toks = [t.strip() for t in body.split("\n") if t.strip()]
    w_order = next((t for t in toks if re.fullmatch(r"[\d/\\.-]{4,}", t)), "")
    qty = next((t for t in reversed(toks)
                if re.fullmatch(r"\d{1,5}", t) and t != w_order), "")
    desc = next((t for t in toks
                 if t not in (w_order, qty) and re.search(r"[A-Za-z]{3}", t)), "")
    weight = _after(_cell_with(cells, "Total Approximate Weight"),
                    "Total Approximate Weight")
    dims = _after(_cell_with(cells, "Total Dims"), "Total Dims")
    return w_order, desc, qty, re.sub(r"^-?\s*approx\s*", "", weight, flags=re.I), dims


def _yes(v):
    """Y/N for a task flag. A blank or a dash is the requester saying no."""
    return "Y" if re.match(r"\s*(y|yes|true|1)\b", str(v or ""), re.I) else "N"


# ---------- the reference ----------
def ah_ref(collection_day, coll_pc, del_pc):
    """AH<d/m/yy><collection><delivery> - the desk's ad hoc reference, e.g.
    AH19/8/26NESY. The two-character halves are the postcode districts cut to
    two ('NE7'->NE, 'M40'->M4), matching every ref already in the outbox."""
    day = collection_day or datetime.now()
    half = lambda pc: postcodes.outward(pc)[:2].upper()
    return f"AH{day.day}/{day.month}/{day.strftime('%y')}{half(coll_pc)}{half(del_pc)}"


# ---------- form -> the shape every ad hoc route already speaks ----------
def parse(path):
    cells = read_cells(path)
    head = _cell_with(cells, "Requester")
    raised_on = _first_date(re.split(r"date\s*:", head, flags=re.I)[-1]) \
        or _first_date(head)
    requester = re.split(r"\s{2,}|\s+date\s*:", _after(head, "Requester"),
                         flags=re.I)[0].strip()

    csite, ca1, ca2, ctown, cpc = _address(
        _cell_with(cells, "Collection address"), "Collection address")
    dsite, da1, da2, dtown, dpc = _address(
        _cell_with(cells, "Delivery Address"), "Delivery Address")

    coll_cell = _cell_with(cells, "Date Available for Collection")
    del_cell = _cell_with(cells, "Delivery Date")
    cday = _first_date(coll_cell)
    dday = _first_date(re.split(r"open hours", del_cell, flags=re.I)[0])
    cw = _window(coll_cell)
    dw = _window(del_cell)

    # the two contact rows: name on the left, its own phone in the cell beside it
    def contact(label):
        for i, c in enumerate(cells):
            if label.lower() in c.lower():
                name = _after(c, label)
                phone = ""
                for nxt in cells[i + 1:i + 2]:
                    if "telephone" in nxt.lower():
                        phone = _after(nxt, "Telephone Number", "Telephone No",
                                       "Telephone")
                return name, re.sub(r"[^\d+ ]", "", phone).strip()
        return "", ""

    cname, cphone = contact("Collection Site Contact Name")
    dname, dphone = contact("Delivery Site Contact Name")

    w_order, desc, qty, weight, dims = _items(cells)
    cost = _after(_cell_with(cells, "Cost Centre Number"), "Cost Centre Number")
    trans = _after(_cell_with(cells, "Trans No"), "Trans No").strip(" -")
    # "Hiab required?" is a question cell; the answer is typed either after the
    # question mark or in the narrow cell beside it. A dash or a blank is "no".
    hiab = "N"
    for i, c in enumerate(cells):
        if "hiab required" in c.lower():
            answer = c.split("?", 1)[-1].strip()
            if not answer and i + 1 < len(cells):
                answer = cells[i + 1].strip()
            hiab = _yes(answer)
            break
    driver_loads = _after(_cell_with(cells, "Will Driver be required"),
                          "Will Driver be required to load or unload materials")
    extra = _after(_cell_with(cells, "Additional Useful Information"),
                   "Additional Useful Information")
    trip = _after(_cell_with(cells, "Return trip"), "Return trip or one- way only",
                  "Return trip or one-way only", "Return trip")

    ref = ah_ref(cday or dday, cpc, dpc)

    # Delivery Instructions carry the material line the desk expects; the
    # weight/dims tail is what the map record lifts back out for the brief.
    instr = " ".join(p for p in (
        f"Material {desc}" if desc else "",
        f"Dimension {dims}" if dims else "",
        f"Qty {qty}" if qty else "",
        f"Weight - {weight}" if weight else "",
    ) if p)
    notes = ". ".join(p for p in (
        f"W/Order {w_order}" if w_order else "",
        "Driver required to load and unload" if _yes(driver_loads) == "Y" else "",
        extra,
    ) if p)

    row = {
        "Customer Order No": ref, "Shipment No": trans or ref,
        # collection end
        "Site Name - Collection": csite, "Contact Name": cname,
        "Address 1": ca1, "Address 2": ca2, "Address 3": ctown,
        "Postcode": cpc, "Telephone No": cphone,
        "Collection Date": cday,
        "collection_time": _at(cday, cw[0]), "collection_time_end": _at(cday, cw[1]),
        # delivery end
        "Delivery Point": dsite, "D Contact Name": dname,
        "D Address 1": da1, "D Address 2": da2, "D Address 3": dtown,
        "D Postcode": dpc, "D Telephone No": dphone,
        "Delivery Date": dday,
        "delivery_time": _at(dday, dw[0]), "delivery_time_end": _at(dday, dw[1]),
        # load
        "Product / Description": desc, "Product Qty": qty, "Serial Number": "",
        "Delivery Instructions": instr,
        "Notes for Collection Location Comments": "",
        "Notes for Delivery Location Comments": notes,
        # admin - an ad hoc is NRADHOC; the cost number rides on 1003, the
        # requester's email on 1002 (blank when the form never states one)
        "Account": process_form.ADHOC_ACCOUNT, "Cost Centre": cost,
        "Raised by": "", "Est Cost": 0, "Vehicle Type": "",
        # tasks - the Word form only ever asks about a HIAB
        "HIAB": hiab, "Moffett": "N", "PTS": "N", "Banksman": "N",
        "Log Grab": "N", "Rear Steer": "N", "Vehicle Escort": "N",
    }
    meta = {"requester": requester, "raised_on": raised_on, "trip": trip,
            "w_order": w_order, "driver_loads": driver_loads, "trans": trans,
            "weight": weight, "dims": dims, "extra": extra}
    return row, meta


# ---------- what the template has no box for ----------
# Three things CTMS wants are simply not askable on this form: it has no
# requester-email field at all, "Date Available for Collection" is routinely
# left on open hours, and the delivery telephone line is as often blank as
# filled. They come from the desk instead - stated on the command line, echoed
# back in the run so nothing on the upload is mistaken for the requester's own
# words, and never guessed at.
OPTS = {
    "collection": 'collection date and window, e.g. "20/08/2026 07:00-15:00"',
    "delivery": 'delivery date and window, e.g. "20/08/2026 08:00-16:00"',
    "raised-by": "requester's email - ORD_SUB_REFS 1002",
    "collection-phone": "collection site telephone",
    "delivery-phone": "delivery site telephone",
}


def _cli(argv):
    """(path, {option: value}) from the command line."""
    path, opts, i = "", {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            opts[a[2:].lower()] = argv[i + 1].strip() if i + 1 < len(argv) else ""
            i += 2
        else:
            path = path or a.strip()
            i += 1
    return path, opts


def apply_overrides(row, opts):
    """Merge the desk-supplied fields into a parsed row. Returns what changed,
    so the run can say it out loud.

    The reference is rebuilt afterwards because it encodes the COLLECTION day -
    supplying that day is exactly the case where the parsed ref was standing on
    the delivery date as a fallback.
    """
    used = []
    for flag, dkey, tkey, ekey in (
            ("collection", "Collection Date", "collection_time", "collection_time_end"),
            ("delivery", "Delivery Date", "delivery_time", "delivery_time_end")):
        v = opts.get(flag)
        if not v:
            continue
        day = _first_date(v) or row[dkey]
        if not day:
            print(f"!! --{flag} {v!r} has no readable date - ignored.")
            continue
        start, end = _window(v)
        row[dkey] = day
        row[tkey] = _at(day, start) if start else None
        row[ekey] = _at(day, end) if end else None
        used.append(f"{flag} {day:%d/%m/%Y} "
                    f"{start + '-' + end if start and end else '(no window given)'}")
    for flag, key, label in (("raised-by", "Raised by", "1002 raised by"),
                             ("collection-phone", "Telephone No", "collection phone"),
                             ("delivery-phone", "D Telephone No", "delivery phone")):
        if opts.get(flag):
            row[key] = opts[flag]
            used.append(f"{label} {opts[flag]}")
    # 1002 is a semicolon-separated LIST. Every upload that has ever been
    # accepted carries the separator - two addresses joined by it, or a lone
    # address terminated by it ("NRFleetspares@dhl.com;") - and the one CTMS
    # rejection traced to this field was a 1002 that did not. A single bare
    # address is the shape that has never been seen to work, so terminate it.
    rb = str(row.get("Raised by") or "").strip()
    if rb and ";" not in rb:
        row["Raised by"] = rb + ";"
    if used:
        ref = ah_ref(row["Collection Date"] or row["Delivery Date"],
                     row["Postcode"], row["D Postcode"])
        if row["Shipment No"] == row["Customer Order No"]:
            row["Shipment No"] = ref      # no Trans No on the form - it mirrors the ref
        row["Customer Order No"] = ref
    return used


def main():
    path, opts = _cli(sys.argv[1:])
    if not path or not os.path.exists(path):
        print("Usage: python process_word_form.py <path to Transport request form.doc>")
        for k, v in OPTS.items():
            print(f"       --{k:<17} {v}")
        return
    row, meta = parse(path)
    for line in apply_overrides(row, opts):
        print(f"SET : {line}")
    print(f"FORM: {path}")
    print(f"Raised by : {meta['requester'] or '(not stated)'}"
          f"{'  on ' + meta['raised_on'].strftime('%d/%m/%Y') if meta['raised_on'] else ''}"
          f"  |  {meta['trip'] or 'trip type not stated'}")
    print(f"Reference : {row['Customer Order No']}")
    print(f"Collection: {row['Site Name - Collection']} {row['Postcode']} "
          f"({row['Contact Name'] or 'no contact'} {row['Telephone No']})")
    print(f"Delivery  : {row['Delivery Point']} {row['D Postcode']} "
          f"({row['D Contact Name'] or 'no contact'} {row['D Telephone No']})")
    print(f"Load      : {row['Product Qty'] or '?'} x {row['Product / Description'] or '?'}"
          f"  |  HIAB {row['HIAB']}  |  cost centre {row['Cost Centre'] or '(none)'}")

    if process_form._ref_incomplete(row["Customer Order No"]):
        print("!! Could not build a usable reference - both postcodes must read. "
              "Nothing written.")
        return

    tr = process_form.to_transform_row(row)
    records = nr_csv.transform([tr])

    # Detection only. A backwards window here is usually the FORM's missing
    # collection date being defaulted, not the requester making a mistake, so
    # this route says so rather than staging a query email at them.
    import date_query
    for p in date_query.backwards([tr]):
        print(f"!! DELIVERY BEFORE COLLECTION  {p['ref']}: collect {p['collection']} "
              f"deliver {p['delivery']} ({p['back_by']} earlier) - fix the "
              f"collection day before uploading.")

    ref = re.sub(r"[^A-Za-z0-9]+", "-", row["Customer Order No"]).strip("-")[:24]
    name = f"NR_heavy_{ref}_{datetime.now():%d%m%Y%H%M%S}.csv"
    out = nr_csv.write_csv(records, outbox.path(name))

    try:
        if process_form.save_adhocs([row], name, form_path=path):
            print("MAP : job saved for the dashboard map (form kept for forwarding).")
        else:
            print("MAP : NOT on the map - refused, see the SKIP line(s) above.")
    except Exception as ex:      # the map extra must never cost the CSV
        print(f"(map record not saved: {ex})")

    # Say which windows the form actually gave and which the toolkit filled in,
    # so nothing on the upload is mistaken for the requester's own instruction.
    for lbl, key, stated in (("collection", "collection time", row["collection_time"]),
                             ("delivery", "delivery time", row["delivery_time"])):
        if not tr[key]:
            print(f"!! {lbl} has NO DATE on the form - times are BLANK in the CSV.")
        elif stated is None:
            print(f"NOTE {lbl} window not stated on the form - defaulted to "
                  f"09:00-17:00 in the CSV (correct in CTMS if wrong).")
    if not row["Raised by"]:
        print("!! 1002 (Raised by) is EMPTY - the Word form has no requester email. "
              "Add it before uploading; CTMS expects it.")
    if not row["D Telephone No"]:
        print("!! Delivery telephone is EMPTY on the form - the upload falls back "
              "to the contact name. Get a number before uploading.")
    print(f"CSV : {out}")


if __name__ == "__main__":
    main()
