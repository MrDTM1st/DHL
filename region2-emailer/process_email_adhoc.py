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

    Cost centre: 861232
    Item description: Ultrasonic equipment - X3 Box, 24 Kg total

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
# delivery contact on the upload as the collection one.
SUB_LABELS = ("contact", "telephone", "phone", "tel", "mobile", "site contact")


# ---------- reading the block ----------
def read_blocks(text):
    """{label.lower(): value} where the value keeps the lines under it.

    Labels repeat across a job ("Contact:" appears under both addresses), so
    a sub-label stays part of its parent's block rather than overwriting the
    earlier one - the collection contact is found inside the collection
    address, which is the only place it means anything.
    """
    blocks, cur = {}, None
    for raw in pw._clean(text).split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = LABEL_RE.match(line)
        sub = bool(m) and m.group(1).strip().lower().startswith(SUB_LABELS)
        if m and not (sub and cur):
            cur = m.group(1).strip().lower()
            blocks[cur] = m.group(2).strip()
        elif cur is not None:
            blocks[cur] = (blocks[cur] + "\n" + line).strip("\n")
    return blocks


def block(blocks, *labels):
    """The first block whose label starts with one of these (so 'Collection
    address' answers to 'collection address' and to 'collection')."""
    for lb in labels:
        for k, v in blocks.items():
            if k.startswith(lb.lower()):
                return v
    return ""


# ---------- the pieces ----------
def window(text):
    """('09:00','12:00') from 'window 0900-1200' or '09:00 - 12:00'.

    A form types a colon into a time; an email just as often writes the window
    as bare four-digit times, which the form parser's pattern does not match.
    Only the text AFTER the word 'window' is rewritten - a bare four-digit run
    earlier on that line is the YEAR of the date sitting beside it, and
    rewriting that turns 02/09/2026 into a 20:26 job. The reading itself is
    still process_word_form's: there is one window parser in this toolkit.
    """
    m = re.search(r"window\s*(.+)$", text or "", re.I | re.M)
    if not m:
        return pw._window(text)
    return pw._window(re.sub(r"\b(\d{2})(\d{2})\b", r"\1:\2", m.group(1)))


def address(cell):
    """(site, addr1, addr2, town, postcode) from a typed address block.

    process_word_form._address cannot read this shape. On the Word form the
    town and the postcode share the last line ('Retford NOTTINGHAMSHIRE DE24
    8HY'); in a typed email the postcode is nearly always on a line of its
    own, which leaves that reader with an empty town and the town folded into
    the street. Here the town is simply the line above the postcode.
    """
    lines = [ln.strip(" ,") for ln in cell.split("\n")]
    lines = [ln for ln in lines
             if ln and ln.lower().strip(". ") not in pw.COUNTRIES
             and not LABEL_RE.match(ln)]        # 'Contact: ...' is not an address line
    if not lines:
        return "", "", "", "", ""
    site, rest = lines[0], lines[1:]
    pc, town = "", ""
    for i in range(len(rest) - 1, -1, -1):
        m = pw.PC_RE.search(rest[i])
        if not m:
            continue
        pc = f"{m.group(1).upper()} {m.group(2).upper()}"
        tail = pw.PC_RE.sub("", rest[i]).strip(" ,")
        rest = rest[:i]
        # postcode alone on its line -> the town is the line above it
        town = tail or (rest.pop() if rest else "")
        break
    else:
        town = rest.pop() if rest else ""
    # 'Retford NOTTINGHAMSHIRE' -> Retford; the county is dropped, the region
    # on the upload comes from the postcode district, never from text
    town = re.sub(r"\s+[A-Z][A-Z\s&']{3,}$", "", town).strip() or town
    parts = [p.strip() for ln in rest for p in ln.split(",") if p.strip()]
    a1 = parts[0] if parts else ""
    a2 = " ".join(parts[1:]) if len(parts) > 1 else ""
    return site, a1, a2, town, pc


def contacts(cell):
    """[(name, phone)] from the 'Contact:' / 'Contacts:' line of an address
    block. Several people on one job are separated by '/' - the first is the
    one the upload carries, the rest are kept for the location comments so a
    driver who cannot raise the first has the second."""
    line = ""
    for ln in cell.split("\n"):
        m = LABEL_RE.match(ln.strip())
        if m and m.group(1).strip().lower().startswith("contact"):
            line = m.group(2).strip()
            break
    out = []
    for part in re.split(r"\s*/\s*(?=[A-Za-z])", line):
        part = part.strip()
        if not part:
            continue
        m = CONTACT_RE.match(part)
        if m:
            out.append((m.group(1).strip(),
                        re.sub(r"[^\d+ ]", "", m.group(2)).strip()))
        else:
            out.append((part, ""))
    return out


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

    cblock = block(blocks, "collection address", "collection")
    dblock = block(blocks, "delivery address", "delivery")
    csite, ca1, ca2, ctown, cpc = address(cblock)
    dsite, da1, da2, dtown, dpc = address(dblock)

    cdate_txt = block(blocks, "collection date")
    ddate_txt = block(blocks, "delivery date")
    cday, dday = pw._first_date(cdate_txt), pw._first_date(ddate_txt)
    cw, dw = window(cdate_txt), window(ddate_txt)

    ccon, dcon = contacts(cblock), contacts(dblock)
    cname, cphone = ccon[0] if ccon else ("", "")
    dname, dphone = dcon[0] if dcon else ("", "")

    desc, qty, weight = item(block(blocks, "item description", "item", "description"))
    cost = block(blocks, "cost centre", "cost centre number", "cost code")
    raised_by = block(blocks, "raised by", "requester email", "requester")

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
    # answer at a gate, so it rides in the location comments.
    notes = ". ".join(f"Also {n} {p}".strip() for n, p in dcon[1:]) or ""
    cnotes = ". ".join(f"Also {n} {p}".strip() for n, p in ccon[1:]) or ""

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
    meta = {"weight": weight, "contacts": ccon + dcon}
    return row, meta


def main():
    path, opts = pw._cli(sys.argv[1:])
    if not path or not os.path.exists(path):
        print("Usage: python process_email_adhoc.py <path to the job text>")
        for k, v in pw.OPTS.items():
            print(f"       --{k:<17} {v}")
        return
    row, meta = parse(path)
    for line in pw.apply_overrides(row, opts):
        print(f"SET : {line}")
    print(f"TEXT: {path}")
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

    # Say which windows the email actually gave and which the toolkit filled
    # in, so nothing on the upload is mistaken for the requester's own words.
    for lbl, key, stated in (("collection", "collection time", row["collection_time"]),
                             ("delivery", "delivery time", row["delivery_time"])):
        if not tr[key]:
            print(f"!! {lbl} has NO DATE in the email - times are BLANK in the CSV.")
        elif stated is None:
            print(f"NOTE {lbl} window not stated - defaulted to 09:00-17:00 in the "
                  f"CSV (correct in CTMS if wrong).")
    if not row["Raised by"]:
        print("!! 1002 (Raised by) is EMPTY - the email states no requester address. "
              "Add it with --raised-by before uploading; CTMS expects it.")
    if not row["D Telephone No"]:
        print("!! Delivery telephone is EMPTY - the upload falls back to the contact "
              "name. Get a number before uploading.")
    print(f"CSV : {out}")


if __name__ == "__main__":
    main()
