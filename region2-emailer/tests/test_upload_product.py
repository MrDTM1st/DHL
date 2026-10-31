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


def order(material, account="NRADHOC", code="", serial="", ref="AH01/01/26EXEX", **more):
    return dict({"Customer Order No": ref, "Site Name - Collection": "Example Depot", "Contact Name": "Sam Example",
                 "Postcode": "EX1 1AA", "Delivery Point": "Example Siding", "D Contact Name": "Jo Example",
                 "D Postcode": "EX2 2BB", "Product / Description": material, "Product / Service Code": code,
                 "Product Qty": 2, "Serial Number": serial, "Raised by": "planner@example.com",
                 "Account": account}, **more)


def lines(o):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        recs = N.transform([o])
    by = {r[0]: r for r in recs}
    return by["ORD_LINES"], by["ITEMS"], out.getvalue()


def upload(o):
    """(the ORDER row, the task names, what was printed)."""
    with contextlib.redirect_stdout(io.StringIO()) as out:
        recs = N.transform([o])
    return next(r for r in recs if r[0] == "ORDER"), [r[1] for r in recs if r[0] == "ORD_TASKS"], out.getvalue()


def test_postcodes_go_up_with_their_space():
    row, _, _ = upload(order("Pallet", Postcode="OL113AU", **{"D Postcode": "le27st"}))
    assert (row[11], row[23]) == ("OL11 3AU", "LE2 7ST"), row
    assert upload(order("Pallet", Postcode="TBC"))[0][11] == "TBC"          # not a postcode: as it came


def test_the_account_follows_his_rules():
    acct = lambda **kw: upload(order(kw.pop("material", "Pallet"), **kw))[0][28]
    assert acct(**{"Cost Centre": "GBMD30.10000.100000.100"}) == "NR_OTHER"   # a DHL cost centre
    assert acct(material="Shift Work") == "NRADHOC_NS"
    assert acct(**{"Delivery Instructions": "Material Container Weight - 10000kg"}) == "NRADHOC_NS"
    assert acct(**{"Delivery Instructions": "Material Pallet Weight - 3000kg"}) == "NRADHOC"
    assert acct(account="NRADHOC_NH", **{"Delivery Instructions": "Weight - 6000kg"}) == "NRADHOC_NH"
    assert acct(account="HEAVY", code="X", **{"Cost Centre": "GBMD30"}) == "NRHEAVY"   # never off an ad hoc's
    assert "account NRADHOC -> NRADHOC_NS, shift work" in upload(order("Shift Work"))[2]
    assert lines(order("Box", account="NRADHOC_NS"))[0][1] == "BOX"           # every form account is an ad hoc


def test_services_fit_the_vehicle():
    tasks = lambda m="Pallet", **kw: upload(order(m, **kw))[1]
    assert "HIAB" not in tasks(HIAB="Y", **{"Vehicle Type": "NR_R_TIP26_8"})
    assert "HIAB" not in tasks("Loose ballast", HIAB="Y")                       # tipped, vehicle not named yet
    assert "HIAB" in tasks(HIAB="Y", **{"Vehicle Type": "NR_ARTIC_FL"})
    assert "MOFFETT" not in tasks(Moffett="Y", **{"Vehicle Type": "NR_CS_MOF"})
    assert "ESCORTS" not in tasks("Rail", **{"Vehicle Escort": "Y", "Vehicle Type": "NR_60_ART_FL"})
    assert "ESCORTS" in tasks("Rail", **{"Vehicle Type": "NR_TROM_80ft"})
    assert "ESCORTS" in tasks("Rail", **{"Vehicle Escort": "Y"})                  # no vehicle yet: as asked
    said = upload(order("Rail", **{"Vehicle Escort": "Y", "Vehicle Type": "NR_60_ART_FL"}))[2]
    assert "ESCORTS off - only a trombone has one, not NR_60_ART_FL" in said


def test_the_upload_finds_its_night_and_weekend_legs():
    recs = N.transform([order("Pallet", **{"collection time": "06/11/2026 21:00",
                                            "collection time end": "06/11/2026 22:00",
                                            "delivery time": "07/11/2026 08:00",
                                            "delivery time end": "07/11/2026 12:00"})])
    (ref, legs), = N.order_windows(recs)
    assert ref == "AH01/01/26EXEX" and [leg for leg, _, _ in legs] == ["collect", "deliver"]
    import ctms_todo
    assert ctms_todo.services_owed(legs) == ["NIGHT", "SATURDAY"]


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
                           ("27x sleepers", "CONC_SLEEPER"), ("Sleeper", "CONC_SLEEPER"),
                           ("timber sleepers", "HARD_BEARERS"), ("wooden sleepers", "HARD_BEARERS"),
                           ("Timber", "HARD_BEARERS"),
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
