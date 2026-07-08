"""
DTS PDF -> NR upload CSV.

Reads a DTS "Supplier Collection & Repair Agent Order Form" PDF and writes the
NR upload CSV (ORDER / ORD_SUB_REFS / ORD_LINES / ITEMS records), applying the
DTS rules: order-type NRADHOC_NH, no HIAB, blank vehicle, reference = order no,
site short-code = first address line, times 9AM->09:00 / NOON->12:00,
dates = today+2, quantity = pallet count, 1002/1003 blank, and NO commas.

    python dts_convert.py "<path to DTS.pdf>"
"""
import sys, os, re
from datetime import datetime, timedelta
import pdfplumber

ORDER_TYPE = "NRADHOC_NH"
LOAD_CLASS = "NRADHOC_NH"


def nc(v):
    """No commas; collapse whitespace."""
    return re.sub(r"\s+", " ", str(v or "").replace(",", " ")).strip()


def addr(v):
    """Address/site/contact fields: no commas AND no hyphens."""
    return re.sub(r"\s+", " ", str(v or "").replace(",", " ").replace("-", " ")).strip()


def to_time(s, is_end=False):
    # working example uses HH:MM (no seconds) - match it exactly
    default = "14:00" if is_end else "09:00"
    s = (s or "").strip().upper()
    if not s:
        return default
    if "NOON" in s:
        return "12:00"
    if "MIDNIGHT" in s:
        return "00:00"
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", s)
    if m:
        h = int(m.group(1)); mnt = m.group(2) or "00"; ap = m.group(3)
        if ap == "PM" and h < 12:
            h += 12
        if ap == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mnt}"
    return default


def parse_block(block):
    d = {}
    for line in block.splitlines():
        m = re.match(r"<([^>]+)>\s*(.*)", line.strip())
        if m:
            d[m.group(1).strip().lower()] = m.group(2).strip()
    return d


def parse_pdf(path):
    with pdfplumber.open(path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        tables = []
        for p in pdf.pages:
            tables.extend(p.extract_tables() or [])
    ref = ""
    fn = os.path.basename(path)
    m = re.search(r"([A-Z]{2}\d{5,}-\d+)", fn) or re.search(r"([A-Z]{2}\d{5,}-\d+)", text)
    if m:
        ref = m.group(1)
    raiser_email = ""
    em = re.search(r"Email Address:\s*([\w.\-+]+@[\w.\-]+)", text)
    if em:
        raiser_email = em.group(1)
    pallets = 0
    pm = re.search(r"Total Pallets/Parcels:\s*(.+)", text)
    if pm:
        pallets = sum(int(x) for x in re.findall(r"(\d+)\s*@", pm.group(1))) or 0
    del_notes = re.findall(r"\b\d{3,4}/\d{5,6}\b", text)
    ci = text.find("<Collection Site>")
    di = text.find("<Delivery Site>")
    coll = parse_block(text[ci:di]) if ci >= 0 else {}
    deliv = parse_block(text[di:]) if di >= 0 else {}
    m = re.search(r"Raised By:\s*(.+?)\s*Date:", text)
    raiser = m.group(1).strip() if m else ""
    weight_kg = _weight_from_tables(tables)
    return dict(ref=ref, pallets=pallets, weight_kg=weight_kg, del_notes=del_notes,
                coll=coll, deliv=deliv, raiser_email=raiser_email, raiser=raiser)


def _weight_from_tables(tables):
    """Sum the 'Weight in Kgs' column of the DTS line-items table (the PDF puts
    the shipment total in that column, e.g. 3061). Returns 0 if not found."""
    for tbl in tables:
        for hi, row in enumerate(tbl):
            cells = [str(c or "").strip().lower() for c in row]
            widx = next((i for i, c in enumerate(cells) if "weight in kg" in c), None)
            if widx is None:
                continue
            total = 0.0
            for row2 in tbl[hi + 1:]:
                if widx < len(row2):
                    m = re.search(r"(\d+(?:\.\d+)?)", str(row2[widx] or ""))
                    if m:
                        total += float(m.group(1))
            return int(total) if float(total).is_integer() else round(total, 1)
    return 0


def _xl_time(v):
    """Excel time fraction -> 'HH:MM', else None."""
    if isinstance(v, float) and 0 <= v < 1:
        mins = int(round(v * 24 * 60))
        return f"{mins // 60:02d}:{mins % 60:02d}"
    return None


def parse_xls(path):
    """The spreadsheet flavour of the DTS form (Network_Rail_DTS_*.xls)."""
    import xlrd
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)

    def dmy(v):
        if isinstance(v, float) and v > 1:
            try:
                return xlrd.xldate.xldate_as_datetime(v, wb.datemode).strftime("%d/%m/%Y")
            except Exception:
                return ""
        m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", str(v or ""))
        return m.group(1) if m else ""

    ref = ""
    raiser = raiser_email = ""
    pallets_raw = ""
    del_notes, line_qtys = [], []
    coll, deliv = {}, {}
    cur = None
    for r in range(sh.nrows):
        label = str(sh.cell_value(r, 1)).strip() if sh.ncols > 1 else ""
        val5 = sh.cell_value(r, 5) if sh.ncols > 5 else ""
        low = label.lower()
        if low.startswith("raised by"):
            raiser = str(val5).strip()
        elif low.startswith("email address"):
            raiser_email = str(val5).strip()
        elif low.startswith("total pallets"):
            pallets_raw = str(val5).strip()
            v15 = str(sh.cell_value(r, 15)).strip() if sh.ncols > 15 else ""
            if re.match(r"[A-Z]{2}\d{5,}", v15):
                ref = v15
        elif low == "collection site":
            cur = coll
        elif low == "delivery point":
            cur = deliv
        elif label.startswith("<") and cur is not None:
            tag = label.strip("<>*").strip().lower().replace(">", "")
            if tag in ("start time window", "end time window"):
                t = _xl_time(val5)
                cur[tag] = t if t else str(val5).strip()
            elif tag in ("collection date", "delivery date"):
                cur["date"] = dmy(val5)
                cur[tag] = str(val5).strip()
            else:
                cur[tag] = str(val5).strip()
        # line items: NN ref in col1, catalogue no in col5
        if re.match(r"[A-Z]{2}\d{5,}", label) and str(val5).strip():
            m = re.match(r"\d{3,4}/\d{4,}", str(val5).strip())
            if m:
                del_notes.append(m.group(0))
            if not ref:
                ref = label.split("/")[0]
            q = sh.cell_value(r, 16) if sh.ncols > 16 else None
            try:
                line_qtys.append(int(float(q)))
            except Exception:
                pass
    fn = os.path.basename(path)
    if not ref:
        m = re.search(r"([A-Z]{2}\d{5,}-\d+)", fn)
        ref = m.group(1) if m else ""
    m = re.match(r"\s*(\d+)", pallets_raw)
    pallets = int(m.group(1)) if m else (sum(line_qtys) or 1)
    weight_kg = _weight_from_sheet(sh)
    return dict(ref=ref, pallets=pallets, weight_kg=weight_kg, del_notes=del_notes,
                coll=coll, deliv=deliv, raiser_email=raiser_email, raiser=raiser)


def _weight_from_sheet(sh):
    """Sum the 'Weight in Kgs' column across the DTS line-item rows (e.g. '119KG'
    -> 119). Returns 0 if the column isn't present."""
    wcol = hdr = None
    for r in range(sh.nrows):
        for c in range(sh.ncols):
            if "weight in kg" in str(sh.cell_value(r, c)).strip().lower():
                wcol, hdr = c, r
                break
        if wcol is not None:
            break
    if wcol is None:
        return 0
    total = 0.0
    for r in range(hdr + 1, sh.nrows):
        m = re.search(r"(\d+(?:\.\d+)?)", str(sh.cell_value(r, wcol)))
        if m:
            total += float(m.group(1))
    return int(total) if float(total).is_integer() else round(total, 1)


def parse_dts(path):
    """Either flavour of DTS: PDF form or the .xls spreadsheet form."""
    if str(path).lower().endswith((".xls", ".xlsx")):
        return parse_xls(path)
    return parse_pdf(path)


def build_rows(data):
    coll, deliv, ref = data["coll"], data["deliv"], data["ref"]
    pallets = str(data["pallets"] or "")
    d2 = (datetime.now() + timedelta(days=2)).strftime("%d/%m/%Y")

    def g(d, k):
        return nc(d.get(k, ""))

    def dt(d, k, is_end=False):
        return f"{d2} {to_time(d.get(k, ''), is_end)}"

    materials = nc("Del Notes " + " ".join(data["del_notes"]) + f" - {pallets} pallets")

    order = [
        "ORDER", nc(ref),
        addr(coll.get("address 1")),   # collection short-code = first address line
        addr(coll.get("collection site")),
        addr(coll.get("contact name")), "",   # contact col 1, contact col 2 (blank)
        "",                            # notes (blank)
        addr(coll.get("address 1")), addr(coll.get("address 2")), addr(coll.get("address 3")),
        addr(coll.get("address 3")),   # town  [assumption: repeat addr3]
        g(coll, "post code"), g(coll, "telephone no"),
        dt(coll, "start time window"), dt(coll, "end time window", True),
        addr(deliv.get("address 1")),  # delivery short-code
        addr(deliv.get("delivery site")),
        addr(deliv.get("contact name")), "",  # contact col 1, contact col 2 (blank)
        addr(deliv.get("address 1")), addr(deliv.get("address 2")), addr(deliv.get("address 3")),
        addr(deliv.get("address 3")),  # town  [assumption]
        g(deliv, "post code"), g(deliv, "telephone no"),
        dt(deliv, "start time window"), dt(deliv, "end time window", True),
        materials,                     # materials  [assumption]
        ORDER_TYPE, "", "",            # order-type, blank, vehicle(blank)
        "0", "0", nc(ref), "",
    ]
    rows = [
        order,
        ["ORD_TASKS", "", ""],                   # kept but blank (no HIAB for DTS)
        ["ORD_SUB_REFS", "1002", nc(data.get("raiser_email", ""))],
        ["ORD_SUB_REFS", "1003", ""],
        ["ORD_LINES", "", LOAD_CLASS, pallets],
        ["ITEMS", "PALLETS", pallets],
    ]
    width = len(order)
    return [r + [""] * (width - len(r)) for r in rows]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not os.path.exists(path):
        print("Usage: python dts_convert.py <DTS.pdf>"); return
    data = parse_pdf(path)
    rows = build_rows(data)
    out = os.path.join(os.path.dirname(os.path.abspath(path)),
                       f"NR_NH_{datetime.now().strftime('%d%m%Y%H%M%S')}.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write(",".join(r) + "\n")
    print("Reference   :", data["ref"])
    print("Pallets     :", data["pallets"])
    print("Del notes   :", data["del_notes"])
    print("Written CSV :", out, "\n")
    for r in rows:
        print(r[0].ljust(13), "|", ",".join(x for x in r if x != "")[:120])


if __name__ == "__main__":
    main()
