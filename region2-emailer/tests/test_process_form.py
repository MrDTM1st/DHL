"""Plain-assert tests for process_form's Project Shoot Load quantities - no Excel, no Outlook.

A PROJECT SHOOT LOAD form gives every material line its own admin row, each
carrying the line's share of the Total Pallet QTY box. An order's quantity is
the sum over its lines - not the first line's share, which is what a
two-order load of four pallets once uploaded as (0.333 each instead of 2).

Run:  python region2-emailer/tests/test_process_form.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import openpyxl                         # noqa: E402
import process_form as PF               # noqa: E402

A, B = 9100001, 9100002                 # made-up sales orders


def shoot_form(path, box, lines, admin=False):
    """A Project Shoot Load workbook: the Input Sheet (pallet box + materials table),
    the template's Example tab, and - with admin - the admin tab as Excel evaluates it."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Input Sheet"
    ws["A1"] = "PROJECT SHOOT LOAD"
    ws["A28"], ws["D28"], ws["H28"] = "Total Pallet QTY", box, "Total Pallet FP"
    ws["A31"], ws["B31"], ws["Q31"], ws["R31"] = ("Sales Order", "Line Number", "Total Pallet Weight(kg)",
                                                 "Part Pallet Count")
    for i, ref in enumerate(lines):
        ws.cell(row=32 + i, column=1, value=ref)
        ws.cell(row=32 + i, column=2, value=f"{i + 1}.1")
    ws.cell(row=32 + len(lines), column=1, value="Total")
    ex = wb.create_sheet("Example")                      # the template's worked example: never this form's
    ex["A1"] = "PROJECT SHOOT LOAD"
    ex["A28"], ex["D28"] = "Total Pallet QTY", 5
    ex["A31"], ex["Q31"] = "Sales Order", "Part Pallet Count"
    for i, ref in enumerate((11198, 11199)):
        ex.cell(row=32 + i, column=1, value=ref)
    if admin:
        ad = wb.create_sheet("RHPC Admin(do not delete)")
        ad.append(["Customer Order No", "Shipment No", "Product Qty", "Delivery Instructions"])
        ad.append([None, None, None, None])               # the spacer row
        share = (box / len(lines)) if isinstance(box, (int, float)) else 0
        for ref in lines:
            ad.append([ref, "LOAD-1", share, "Total Pallet Weight 541Kg"])
        ad.append(["", "", "", ""])                      # unused lines evaluate to blanks
    wb.save(path)


def rows_for(lines, qty):
    """The admin rows such a form evaluates to - Excel hands numeric refs over as floats."""
    return [{"Customer Order No": float(ref), "Product Qty": qty,
             "Delivery Instructions": "Total Pallet Weight 541Kg"} for ref in lines]


def test_each_order_gets_the_sum_of_its_lines(tmp):
    path = os.path.join(tmp, "two.xlsx")
    lines = [A] * 6 + [B] * 6
    shoot_form(path, 4, lines)
    out = PF.merge_shoot_lines(rows_for(lines, 4 / 12), path)
    assert [(PF._norm_order(d["Customer Order No"]), d["Product Qty"]) for d in out] == [(str(A), 2), (str(B), 2)]
    assert out[0]["Delivery Instructions"] == "Total Pallet Weight 541Kg"      # a bare number adds no words
    one = os.path.join(tmp, "one.xlsx")
    shoot_form(one, 10, [A] * 8)                                                 # one order over eight lines
    assert [d["Product Qty"] for d in PF.merge_shoot_lines(rows_for([A] * 8, 10 / 8), one)] == [10]
    uneven = os.path.join(tmp, "uneven.xlsx")
    shoot_form(uneven, 5, [A] * 7 + [B] * 5)                                     # part pallets stay part pallets
    got = [d["Product Qty"] for d in PF.merge_shoot_lines(rows_for([A] * 7 + [B] * 5, 5 / 12), uneven)]
    assert got == [2.917, 2.083], got


def test_an_empty_box_leaves_the_quantity_blank_and_never_borrows_the_example(tmp):
    path = os.path.join(tmp, "empty.xlsx")
    shoot_form(path, None, [A, B])
    out = PF.merge_shoot_lines(rows_for([A, B], 0), path)
    assert [d["Product Qty"] for d in out] == ["", ""]                           # not the 0 the form computes
    assert PF.shoot_load_qty(path) == (None, "")                                 # nor the Example tab's 5


def test_a_typed_unit_is_kept_in_the_instructions(tmp):
    path = os.path.join(tmp, "box.xlsx")
    shoot_form(path, "1 Box", [A])
    out = PF.merge_shoot_lines(rows_for([A], -2146826273), path)                 # #VALUE! from COM
    assert out[0]["Product Qty"] == 1
    assert out[0]["Delivery Instructions"] == "Total Pallet Weight 541Kg / 1 Box"
    assert PF.shoot_load_qty(path) == (1, "1 Box")


def test_other_forms_and_other_orders_are_left_alone(tmp):
    path = os.path.join(tmp, "plain.xlsx")
    wb = openpyxl.Workbook()
    wb.active["A1"] = "Haulage Request Form"
    wb.save(path)
    rows = [{"Customer Order No": "AH1/1/26TEST", "Product Qty": 3},
            {"Customer Order No": "AH1/1/26TEST_R", "Product Qty": 3}]
    assert PF.merge_shoot_lines([dict(r) for r in rows], path) == rows          # no materials table: as it was
    shoot = os.path.join(tmp, "shoot.xlsx")
    shoot_form(shoot, 4, [A] * 2)
    ret = {"Customer Order No": f"{A}_R", "Product Qty": 1}                      # a return leg is not a line
    out = PF.merge_shoot_lines(rows_for([A] * 2, 2) + [dict(ret)], shoot)
    assert [d["Product Qty"] for d in out] == [4, 1] and out[1] == ret


def test_the_whole_admin_block_is_read_and_folded_into_orders(tmp):
    path = os.path.join(tmp, "admin.xlsx")
    lines = [A] * 6 + [B] * 6                                                    # admin rows 3-14
    shoot_form(path, 4, lines, admin=True)
    keep = sys.modules.get("win32com")
    sys.modules["win32com"] = None                                               # no Excel: the cached values
    try:
        out = PF.read_rhpc_rows(path)
    finally:
        if keep is None:
            sys.modules.pop("win32com", None)
        else:
            sys.modules["win32com"] = keep
    assert [(PF._norm_order(d["Customer Order No"]), d["Product Qty"]) for d in out] == [(str(A), 2), (str(B), 2)]


def request_form(path, typed):
    """A Haulage Request Form whose product box holds `typed`: its upload row looks the box up
    in the form's own drop-down list, as the real template does (V10 is =G31)."""
    wb = openpyxl.Workbook()
    tr = wb.active
    tr.title = "Transport Request"
    tr["G31"], tr["V10"] = typed, "=G31"
    pr = wb.create_sheet("Products")
    pr.append(["Product - Please select", "ITEM_ID"])
    pr.append(["Crane", "CRANE"])
    ad = wb.create_sheet("RHPC Admin - DHL USE ONLY")
    ad.append(["Customer Order No", "Product / Service Code", "Product / Description"])
    ad.append([None, None, None])
    ad.append(["AH01/01/26EXEX", "=IF(A3=\"\",\"\",VLOOKUP('Transport Request'!$V$10,Products!$A:$B,2,FALSE))",
               "=B3"])
    wb.save(path)


def test_a_typed_product_replaces_the_lookups_error(tmp):
    path = os.path.join(tmp, "typed.xlsx")
    request_form(path, "Example crane hire")              # typed, not picked: the form's VLOOKUP is #N/A
    rows = [{"Customer Order No": "AH01/01/26EXEX", "Product / Service Code": -2146826246,
             "Product / Description": "#N/A"}]
    PF.repair_products(rows, path)
    assert rows[0]["Product / Service Code"] == rows[0]["Product / Description"] == "Example crane hire", rows
    request_form(path, None)                               # nothing in the box: blank, never invented
    rows = [{"Customer Order No": "AH01/01/26EXEX", "Product / Description": -2146826246}]
    PF.repair_products(rows, path)
    assert rows[0]["Product / Description"] == ""
    good = [{"Customer Order No": "AH01/01/26EXEX", "Product / Description": "CRANE"}]
    PF.repair_products(good, path)
    assert good[0]["Product / Description"] == "CRANE"     # a looked-up product is left alone


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(tmp)
                print(f"ok    {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
