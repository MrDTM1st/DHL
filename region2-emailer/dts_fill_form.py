"""
DTS PDF -> filled Haulage Request Form (the real first formatting step).

Takes a DTS "Supplier Collection & Repair" PDF, copies the Haulage Request Form
template, and fills the Transport Request sheet from the PDF. Output lands in
Downloads as "Haulage Request - <ref>.xlsx".

    python dts_fill_form.py "<path to DTS.pdf>" ["<path to template.xlsx>"]
"""
import sys, os, shutil, warnings
from datetime import datetime, timedelta
import dts_convert as dc

warnings.filterwarnings("ignore")

TEMPLATE_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "haulage_request_template.xlsx")


def fill(pdf_path, template):
    data = dc.parse_dts(pdf_path)
    coll, deliv = data["coll"], data["deliv"]
    d2 = datetime.now() + timedelta(days=2)

    import outbox
    out = outbox.path(f"Haulage Request - {data['ref'] or 'DTS'}.xlsx")
    shutil.copyfile(template, out)

    import openpyxl
    wb = openpyxl.load_workbook(out)   # keep formulas
    ws = wb["Transport Request"]

    def put(cell, val):
        if val not in (None, ""):
            ws[cell] = val

    g = lambda d, k: dc.nc(d.get(k, ""))

    # requester (from the form's Raised By block - PDF or xls alike)
    raiser = data.get("raiser", "")
    put("E6", raiser)
    put("E7", data.get("raiser_email", ""))
    put("M6", datetime.now().strftime("%d/%m/%Y"))
    put("K7", "One Way ")
    put("V8", "NRADHOC_NH")   # Account - always this for DTS

    # collection
    put("O9", d2.strftime("%d/%m/%Y"))
    put("N10", dc.to_time(coll.get("start time window", "")))
    put("R10", dc.to_time(coll.get("end time window", ""), True))
    put("D10", g(coll, "address 1"))
    put("D11", g(coll, "address 2"))
    put("D12", g(coll, "collection site"))
    put("D13", g(coll, "address 3"))
    put("D14", g(coll, "post code"))
    put("E15", g(coll, "contact name"))
    put("O15", g(coll, "telephone no"))

    # delivery
    put("O16", d2.strftime("%d/%m/%Y"))
    put("N17", dc.to_time(deliv.get("start time window", "")))
    put("R17", dc.to_time(deliv.get("end time window", ""), True))
    put("D17", g(deliv, "address 1"))
    put("D18", g(deliv, "address 2"))
    put("D19", g(deliv, "delivery site"))
    put("D20", g(deliv, "address 3"))
    put("D21", g(deliv, "post code"))
    put("E22", g(deliv, "contact name"))
    put("O22", g(deliv, "telephone no"))

    # site info / product
    put("K24", "N")            # no offload kit for DTS (no HIAB)
    put("G28", "N"); put("O28", "N"); put("G29", "N")
    put("G31", "Pallets (Larger than van)")
    put("G33", data["pallets"])                       # Quantity = number of pallets
    if data.get("weight_kg"):
        put("G34", f"{data['weight_kg']} kg")         # Approximate Weight = Weight in Kgs
    notes = "Del Notes: " + " ".join(data["del_notes"])
    put("G35", notes)

    # DTS override: the NN reference replaces the auto-generated unique order
    # number - written into RHPC Admin as Customer Order No + Shipment No.
    admin = wb["RHPC Admin - DHL USE ONLY"]
    admin["A3"] = data["ref"]   # Customer Order No
    admin["B3"] = data["ref"]   # Shipment No

    wb.save(out)
    return out, data, raiser


def main():
    pdf = sys.argv[1] if len(sys.argv) > 1 else None
    tpl = sys.argv[2] if len(sys.argv) > 2 else TEMPLATE_DEFAULT
    if not pdf or not os.path.exists(pdf):
        print("Usage: python dts_fill_form.py <DTS.pdf> [template.xlsx]"); return
    out, data, raiser = fill(pdf, tpl)
    print("FILLED FORM :", out)
    print("Reference   :", data["ref"])
    print("Raised by   :", raiser, "|", data.get("raiser_email", ""))
    print("Collection  :", data["coll"].get("collection site"), "|", data["coll"].get("post code"))
    print("Delivery    :", data["deliv"].get("delivery site"), "|", data["deliv"].get("post code"))
    print("Pallets     :", data["pallets"], "| Del notes:", len(data["del_notes"]))


if __name__ == "__main__":
    main()
