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

HERE = os.path.dirname(os.path.abspath(__file__))
REGIONS = json.load(open(os.path.join(HERE, "postcode_regions.json"), encoding="utf-8"))


def nc(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)   # Excel numerics: 4.0 -> 4, like Access Format()
    return re.sub(r"[,]", " ", "" if v is None else str(v)).strip()


def region_of(pc):
    pc = ("" if pc is None else str(pc)).strip().upper()
    i = pc.find(" ")
    district = pc[:i] if i > 0 else "UNKNOWN"
    hit = REGIONS.get(district)
    return hit["region"] if hit else "UNKNOWN"


def first_name(name):
    # IIf(null," TBA", IIf(Left(name,InStr(name," "))=" "," TBA", Left(name,InStr(name," "))))
    if not name:
        return " TBA"
    i = str(name).find(" ")
    first = str(name)[: i + 1] if i >= 0 else ""
    return " TBA" if first == " " else first


def last_name(name):
    # Mid(name, Len(First), 100) - 1-based start at the last char of First
    name = "" if name is None else str(name)
    fl = len(first_name(name))
    return name[fl - 1: fl - 1 + 100] if fl >= 1 else name


def dp_short(dp):
    # Mid(Left(dp, InStr(dp," ")), 1, 7)
    dp = "" if dp is None else str(dp)
    i = dp.find(" ")
    return (dp[: i + 1] if i >= 0 else "")[:7]


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
            0: "ORDER", 1: ordno, 2: site[:7], 3: site,
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
            24: o.get("D Telephone No") or str(o.get("D Contact Name") or "")[-12:],
            25: o.get("delivery time"), 26: o.get("delivery time end"),
            27: o.get("Delivery Instructions"),
            28: "NRHEAVY" if acct == "HEAVY" else acct,
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
            if v is not None and str(v).strip().upper() != "N":
                rec(seq, ordno, {0: "ORD_TASKS", 1: label, 2: "1"})
        # ORD_SUB_REFS 1002 (SEQ 9): col1=1002, col2=Raised by
        rec(9, ordno, {0: "ORD_SUB_REFS", 1: "1002", 2: o.get("Raised by")})
        # ORD_SUB_REFS 1003 (SEQ 10): col1=1003, col2=Cost Centre or "0"
        cc = o.get("Cost Centre")
        rec(10, ordno, {0: "ORD_SUB_REFS", 1: "1003", 2: cc if cc not in (None, "") else "0"})
        # ORD_LINES (SEQ 12): col2=class, col3=qty, col4=Serial Number
        rec(12, ordno, {0: "ORD_LINES",
                        2: "CHRG_PALLET" if acct == "NRNONHEAVY" else "HEAVY",
                        3: o.get("Product Qty"), 4: o.get("Serial Number")})
        # ITEMS (SEQ 13): col1=Product/Description, col2=qty.
        # If the form states a product, follow it - fall back to the service
        # code, never leave the ITEMS product blank for the upload to default.
        prod = str(o.get("Product / Description") or "").strip() \
            or str(o.get("Product / Service Code") or "").strip()
        rec(13, ordno, {0: "ITEMS", 1: prod, 2: o.get("Product Qty")})
    out.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in out]


def _csv_safe(v):
    """Final guarantee before the field is written: no commas (they'd shift
    every following column and the upload rejects the row) and no embedded
    line breaks/tabs (same effect). Idempotent - already-clean fields pass
    through unchanged."""
    return re.sub(r"\s+", " ", str("" if v is None else v).replace(",", " ")).strip()


def write_csv(records, out_path):
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        for r in records:
            f.write(",".join(_csv_safe(x) for x in r) + "\n")
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
        # A DTS carries no product line, so it falls back to the SUPPLIER_COL
        # placeholder (the NR database shows this as its default item). But if
        # the parser ever finds a stated product, follow that instead.
        "Product / Description": (str(d.get("product") or "").strip() or "SUPPLIER_COL"),
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
