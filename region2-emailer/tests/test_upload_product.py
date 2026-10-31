"""The product type on the upload's ORD_LINES line - the column CTMS's import reads as the order line's product.
Left empty, an order arrives INVALID unless CTMS's own item list happens to know the ITEMS word, and a planner has
to set the product by hand. The Haulage Request Form's own drop-down decides what an ad hoc is. Made-up orders and
sites only.

    python tests/test_upload_product.py
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import nr_csv as N  # noqa: E402


def order(material, account="NRADHOC", code="", serial="", ref="AH01/01/26EXEX"):
    return {"Customer Order No": ref, "Site Name - Collection": "Example Depot", "Contact Name": "Sam Example",
            "Postcode": "EX1 1AA", "Delivery Point": "Example Siding", "D Contact Name": "Jo Example",
            "D Postcode": "EX2 2BB", "Product / Description": material, "Product / Service Code": code,
            "Product Qty": 2, "Serial Number": serial, "Raised by": "planner@example.com", "Account": account}


def lines(o):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        recs = N.transform([o])
    by = {r[0]: r for r in recs}
    return by["ORD_LINES"], by["ITEMS"], out.getvalue()


def test_every_form_option_uploads_its_item_and_product_type():
    for option, item, ptype in N.FORM_PRODUCTS:
        ord_line, items, _ = lines(order(option))
        assert ord_line[1] == ptype, f"{option}: product {ord_line[1]!r}, wanted {ptype!r}"
        assert items[1] == item.strip(), f"{option}: item {items[1]!r}, wanted {item!r}"
        assert ptype in N.PRODUCT_TYPES, f"{option}: {ptype!r} is not a CTMS code we know"
        assert N.placed_product(item) == ptype, f"{option}: its item {item!r} reads as {N.placed_product(item)!r}"


def test_the_requesters_own_words():
    for material, code in (("Half set switches", "S&C"), ("Crossing nose", "S&C"), ("Train jack", "MACHINERY"),
                           ("water jetter", "MACHINERY"), ("2x crane", "CRANE"), ("X1 DRUM", "CABLE_DRUMS"),
                           ("72x bagged ballast", "BAG_BALLAST"), ("BALLAST 20MM - Loose", "LOOSE_BALLAS"),
                           ("21x stone-blower", "LOOSE_STONEB"), ("hardwood sleepers", "HARD_SLEEPER"),
                           ("Concrete troughing", "CONC_TROUGH"), ("Rail clips", "RAIL_COMP"), ("Pallet", "PALLETS"),
                           ("Pallet_NDC", "PRO_SH_NDS"), ("WHEELSETS", "WHEELSETS"), ("wheel sets", "WHEELSETS")):
        got = lines(order(material))[0][1]
        assert got == code, f"{material}: {got!r}, wanted {code!r}"


def test_his_own_calls():
    for material, code in (("Serviceable sleepers", "SERVICE_MAT"), ("20x servicable concrete sleepers", "SERVICE_MAT"),
                           ("Non-serviceable sleepers", "NON_SERV_MAT"), ("Supplier collection", "SUPPLIER_COL"),
                           ("Supplier collect - 4 pallets", "SUPPLIER_COL"), ("Timbers", "HARD_BEARERS")):
        got = N.placed_product(material)
        assert got == code, f"{material}: {got!r}, wanted {code!r}"


def test_what_nothing_places_goes_up_as_parcel_and_says_so():
    ord_line, _, said = lines(order("Signal Head"))
    assert ord_line[1] == "PARCEL"
    assert "AH01/01/26EXEX (Signal Head)" in said and "PARCEL" in said
    assert "NOTE" not in lines(order("Parcel"))[2]          # a real parcel is not a fallback


def test_the_items_line_follows_the_form():
    assert lines(order("Box"))[1][1] == "Box."              # what the form's own upload row sends
    assert lines(order("Watter Jetter Module"))[1][1] == "Water Jetter Modules"
    assert lines(order("Pallet"))[1][1] == "PALLET"         # the old database's word, which CTMS's item list knows
    assert lines(order("Signal Head"))[1][1] == "Signal Head"
    assert lines(order("Box", account="HEAVY"))[1][1] == "Box"   # never rewritten off an ad hoc account


def test_a_product_type_already_goes_in_as_itself():
    assert lines(order("SUPPLIER_COL", account="NRADHOC_NH"))[0][1] == "SUPPLIER_COL"     # a DTS
    assert lines(order("Media Sets", code="MEDIA_SETS"))[0][1] == "MEDIA_SETS"           # a media set


def test_synergy_and_seasonal_leave_it_to_ctms():
    # the NR stock number: CTMS's item list places it, and a guess on top could only disagree
    assert lines(order("0000/000000/000", account="HEAVY", code="BALLAST 1 TONNE BAGS"))[0][1] == ""
    assert lines(order("TG60", account="Heavy", code="TG60"))[0][1] == ""


def test_only_a_real_length_goes_in():
    assert lines(order("Rail", serial="18.288"))[0][4] == "18.288"
    for junk in ("St", "00", "0", ""):
        assert lines(order("Pallet", serial=junk))[0][4] == "", junk


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
