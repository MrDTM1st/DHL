"""CTMS routes (ctms_routes.py, 23/11): the readers every route stands on, fed made-up Access Bridge reads shaped like
the live ones of 23/11 - windows in stacking order, Order Summary's named columns, the tree's labels, the payments
grid with two AMOUNT cells a row, a question inside another window. Made-up orders, manifests and places only; no
CTMS and no bridge.

    python -m pytest tests/test_ctms_routes.py
"""
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_routes as C  # noqa: E402

N = [0]


def el(r, nm="", v=None, at=(0, 0, 10, 10), lv=2, w=1, st=None):
    N[0] += 1
    e = {"n": N[0], "w": w, "lv": lv, "r": r, "nm": nm, "at": list(at)}
    if v is not None:
        e["v"] = v
    if st:
        e["st"] = list(st)
    return e


def screen(*els):
    return C.Screen({"elements": list(els), "windows": [{"w": 1, "title": "MTS"}]})


def test_clean_takes_off_mnemonics_tab_pages_and_required():
    assert C.clean("Orders mnemonic O") == "Orders"
    assert C.clean("C-TMS Modules ALT C") == "C-TMS Modules"
    assert C.clean("Detail tab page Detail tab page Cost Centre") == "Cost Centre"
    assert C.clean("Special \nInstructions Multiline") == "Special Instructions"
    assert C.clean("Status Required") == "Status"


def test_frames_children_and_what_covers_a_button():
    card = el("internal frame", "Order Search", at=(418, 62, 390, 180), lv=1)
    refresh = el("push button", "Refresh", at=(678, 194, 100, 30))
    order = el("internal frame", "Order details for 11111111", at=(0, 59, 1240, 700), lv=1)
    services = el("page tab", "Services", at=(697, 182, 76, 23))      # under the card
    detail = el("page tab", "Detail", at=(5, 182, 76, 23))            # clear of it
    s = screen(card, refresh, order, services, detail)
    assert [C.clean(f["nm"]) for f in s.frames()] == ["Order Search", "Order details for 11111111"]
    assert s.children(card) == [refresh]
    assert s.frame_of(services)["nm"] == "Order details for 11111111"
    assert s.covered(services)["nm"] == "Order Search"
    assert s.covered(detail) is None
    assert s.covered(refresh) is None                                  # the top window covers nothing of its own


def test_a_question_inside_another_window_gives_only_its_own_buttons():
    split = el("internal frame", "Split Order", at=(300, 400, 500, 300), lv=1)
    process = el("push button", "Process", at=(353, 649, 100, 30), lv=2)
    q = el("internal frame", "Orders Information has been entered Do you want to continue to split the order",
           at=(771, 432, 378, 171), lv=2)
    pane = el("option pane", "Information has been entered", at=(774, 457, 372, 143), lv=3)
    ok = el("push button", "OK", at=(956, 561, 91, 31), lv=3)
    cancel = el("push button", "Cancel", at=(1047, 561, 91, 31), lv=3)
    s = screen(split, process, q, pane, ok, cancel)
    got = s.question()
    assert set(got["buttons"]) == {"ok", "cancel"} and got["buttons"]["cancel"] is cancel
    assert "continue to split" in got["words"]


def test_order_summary_rows_line_up_by_column_name_not_pixels():
    f = el("internal frame", "Order Summary", at=(0, 59, 1300, 700), lv=1)
    cells = []
    for i, (ref, status) in enumerate((("1234567-1-1_S2", "SCHEDULED"), ("1234567-1-1_C1", "UNSCHEDULED"))):
        y = 234 + 23 * i
        cells += [el("text", "Enter value for : SCHED_NAME Required", "261125", at=(15, y, 71, 23)),
                  el("text", "Enter value for : EXTERNAL_REF", ref, at=(86, y, 109, 23)),
                  el("text", "Enter value for : STATUS Required", status, at=(195, y, 118, 23)),
                  el("text", "Enter value for : EARLY_AVAIL", "24/11/26 08:00", at=(646, y - 6, 110, 23))]
    cells.append(el("text", "Enter value for : EXTERNAL_REF", "", at=(86, 280, 109, 23)))       # an empty row
    rows = C.summary_rows(screen(f, *cells))
    assert [(r["ref"], r["status"], r["ready"]) for r in rows] == [
        ("1234567-1-1_S2", "SCHEDULED", "24/11/26 08:00"), ("1234567-1-1_C1", "UNSCHEDULED", "24/11/26 08:00")]
    assert rows[0]["cells"]["status"]["v"] == "SCHEDULED"


def test_base_ref():
    assert C.base_ref("1234567-1-1_S12") == "1234567"
    assert C.base_ref("AH24/11/26ABC") == "AH24/11/26ABC"


def test_tree_rows_and_man_numbers():
    a = el("label", "Level 0 18/11/26 10:00 MAN-01000001  (ACCEPTED)", at=(33, 180, 284, 23), st=["selected"])
    b = el("label", "Level 0 22/11/26 23:30 MFR-01000002 0110 (PLANNED)", at=(33, 203, 284, 23))
    rows = C.tree_rows(screen(a, b))
    assert [(r["man"], r["status"], r["selected"]) for r in rows] == [("MAN-01000001", "ACCEPTED", True),
                                                                     ("MFR-01000002", "PLANNED", False)]
    assert C.man_number("MAN-01000001") == "01000001" and C.man_number("OM-MAN-01000001") == "01000001"


def test_minutes_to_a_trips_start():
    row = {"day": "24/11/26", "time": "10:00"}
    assert C._starts_in(row, datetime(2026, 11, 24, 9, 0)) == 60
    assert C._starts_in({"day": "x"}) is None


def test_payments_count_each_line_once_and_take_the_left_amount():
    f = el("internal frame", "Payments for Trip 261129-MAN-01000001", at=(10, 100, 900, 500), lv=1)
    kids = []
    for i, (kind, amt, vat) in enumerate((("ESCORTS", "324.00", "0.00"), ("Trip Haulage", "581.62", "116.32"))):
        y = 300 + 23 * i
        kids += [el("text", "", "12/10/2026", at=(20, y, 80, 23)), el("text", "", kind, at=(120, y, 120, 23)),
                 el("text", "Enter value for : AMOUNT", amt, at=(400, y, 90, 23)),
                 el("text", "Enter value for : VAT_AMOUNT", vat, at=(500, y, 90, 23))]
    kids.append(el("text", "Total", "905.62", at=(400, 480, 90, 23)))
    rows, total = C.payment_lines(screen(f, *kids))
    assert [(r["cells"][1], r["amount"]) for r in rows] == [("ESCORTS", 324.0), ("Trip Haulage", 581.62)]
    assert total == "905.62"


def _payments(*lines):
    f = el("internal frame", "Payments for Trip 261201-MAN-01000002", at=(10, 100, 900, 500), lv=1)
    kids = []
    for i, (kind, amt) in enumerate(lines):
        y = 300 + 23 * i
        kids += [el("text", "", "01/12/2026", at=(20, y, 80, 23)), el("text", "", kind, at=(120, y, 120, 23)),
                 el("text", "", "261201-MAN-01000002" if kind.startswith("Trip") else "SERVICE", at=(250, y, 140, 23)),
                 el("text", "Enter value for : AMOUNT", amt, at=(400, y, 90, 23)),
                 el("text", "Enter value for : VAT_AMOUNT", "0.00", at=(500, y, 90, 23))]
    return C.payment_lines(screen(f, *kids))[0]


def test_a_price_moves_only_the_haulage_line_and_book_names_it_trip_haul_ma():
    # Book's trips (23/11) show their haulage as "Trip Haul Ma", grid and Edit box alike: the route took only
    # "Trip Haulage" and refused one. The services' own lines stay; the haulage makes up the rest of the quote.
    rows = _payments(("HIAB", "50.00"), ("NIGHT", "80.00"), ("Trip Haul Ma", "700.00"))
    line, others, new = C.price_plan(rows, 700)
    assert line["amount"] == 700.0 and others == 130.0 and new == 570.0
    rows = _payments(("ESCORTS", "324.00"), ("Trip Haulage", "581.62"))
    assert C.price_plan(rows, 1000)[2] == 676.0
    for rows, want in ((_payments(("Trip Haul Ma", "1.00"), ("Trip Haulage", "2.00")), 500),   # which one?
                       (_payments(("NIGHT", "80.00")), 500),                                      # none
                       (_payments(("NIGHT", "600.00"), ("Trip Haul Ma", "100.00")), 500)):        # nothing left for it
        try:
            C.price_plan(rows, want)
            raise AssertionError("should refuse")
        except C.Fail:
            pass


def test_the_carriers_payments_is_found_by_its_place_when_its_name_is_cut_off():
    # Planning's Finance tab late on 23/11: the carrier's Payments named "Finance tab page" over and over, cut off before
    # "Payments" - the old pick by name found only the revenue's and opened Order Revenue
    t = el("page tab", "Finance", at=(810, 132, 81, 23), lv=2, st=["selected"])
    cut = "Finance tab page " * 11 + "Finance tab p"
    kids = [el("push button", "Adjustment", at=(678, 171, 100, 30), lv=3),
            el("push button", cut, at=(678, 215, 100, 30), lv=3),
            el("text", "Enter value for : TRIP_STATUS", "750.00", at=(563, 215, 102, 23), lv=3),
            el("text", "Trip Revenue", "600.00", at=(928, 215, 113, 23), lv=3),
            el("push button", "Finance tab page Payments", at=(1065, 215, 113, 30), lv=3),
            el("push button", "Calc Costs", at=(1065, 245, 113, 30), lv=3)]
    s = screen(t, *kids)
    assert C.carrier_payments(s, t) is kids[1]
    kids[1]["nm"] = "Finance tab page Payments"                             # early in the day: both read Payments
    assert C.carrier_payments(screen(t, *kids), t) is kids[1]
    assert C.cut_short("Finance tab p", "Finance") and not C.cut_short("Calc Costs", "Finance")
    no_rev = [k for k in kids if k["nm"] != "Trip Revenue"]
    no_rev[1]["nm"] = cut                                                   # no revenue figure and one cut name: no guess
    assert C.carrier_payments(screen(t, *no_rev), t) is None


def test_an_item_box_plan_creates_what_an_ad_hoc_upload_left_out():
    # Create's box as it opened on 23/11: nothing but the Oms Ref and "Please Select" (blank boxes aren't read)
    fresh = {"Oms Ref": "11111111", "Identifier": "Please Select"}
    assert C.item_plan(fresh, "PARCEL", 2.0, 1200.0) == [("Product", "PARCEL"), ("Identifier", "Ctrl+L"),
                                                         ("Ordered", "2"), ("Weight", "1200")]
    right = {"Product": "Cable Drums", "Identifier": "Cable Drums", "Ordered": "2", "Weight": "1,200.00"}
    assert C.item_plan(right, "CABLE_DRUMS") == []                        # the drop-down's name, the Detail's code
    typed_text = {"Identifier": "2 x Cable drums", "Ordered": "2", "Delivered": "0"}
    assert C.item_plan(typed_text, "CABLE_DRUMS", None, 1200) == [("Product", "CABLE DRUMS"), ("Identifier", "Ctrl+L"),
                                                                   ("Delivered", ""), ("Weight", "1200")]
    assert C.item_plan(right, "CABLE_DRUMS", ident=True) == [("Identifier", "Ctrl+L")]
    try:
        C.item_plan(fresh, "PARCEL", 2.0)                                   # no weight anywhere: never guessed
        raise AssertionError("should refuse")
    except C.Fail as e:
        assert "--weight" in str(e)
    assert C.product_name("STEE_SLEEPER") != C.product_name("STEEL SLEEPERS")    # a name that differs needs --product


def test_ctrl_l_lists_its_rows_as_labels_top_first():
    box = el("internal frame", "Product Items", at=(113, 254, 456, 456), lv=1)
    kids = [el("text", "Find", "BOX%", at=(149, 304, 412, 26), lv=2), el("list", "", at=(123, 342, 436, 303), lv=2),
            el("label", "Item_Id:Box.\tItem_Description:BOX", at=(-1, -1, -1, -1), lv=3, st=["selected"]),
            el("label", "Item_Id:BOX2\tItem_Description:Box two", at=(-1, -1, -1, -1), lv=3),
            el("push button", "OK", at=(343, 671, 61, 31), lv=2)]
    assert C.product_items(screen(box, *kids)) == [("Box.", "BOX"), ("BOX2", "Box two")]


def test_named_and_header_grids():
    tab = el("page tab", "Services", at=(697, 182, 76, 23), lv=2)
    heads = [el("push button", n, at=(x, 268, w, 23), lv=3) for n, x, w in (("Service Id", 83, 152), ("Name", 235, 270),
                                                                         ("Qty", 503, 117))]
    cells = [el("text", "null", "HIAB", at=(83, 291, 152, 24), lv=3), el("text", "", "USE OF HIAB", at=(235, 291, 270, 24), lv=3),
             el("text", "", "1", at=(505, 291, 115, 24), lv=3)]
    s = screen(tab, *heads, *cells)
    assert C.header_grid(s, tab, ("Service Id", "Name", "Qty")) == [{"Service Id": "HIAB", "Name": "USE OF HIAB",
                                                                    "Qty": "1"}]
    t2 = el("page tab", "Trip Detail", lv=2)
    named = [el("text", "Trip ID", "MAN-01000001", at=(110, 233, 121, 23), lv=3),
             el("text", "Carrier ID", "HAUL_DH", at=(231, 233, 115, 23), lv=3),
             el("text", "Trip ID", "", at=(110, 256, 121, 23), lv=3)]
    s = screen(t2, *named)
    assert C.named_grid(s, t2, ("Trip ID", "Carrier ID")) == [{"Trip ID": "MAN-01000001", "Carrier ID": "HAUL_DH"}]


def test_trip_detail_read_by_place_under_owning_depot():
    t = el("page tab", "Trip Detail", at=(426, 132, 86, 23), lv=2)
    x = 531
    kids = [el("text", "Owning Depot", "NR_Z9", at=(x, 165, 170, 23), lv=3)]
    for v, y in (("NRCC", 188), ("M0000001", 215), ("ACCEPTED", 273), ("HAUL_DH", 303)):
        kids.append(el("text", "Enter value for : TRIP_STATUS", v, at=(x, y, 170, 23), lv=3))
    kids.append(el("text", "Enter value for : Delivery Type", "STANDARD", at=(1210, 215, 168, 23), lv=3))
    d = C.read_trip_detail(screen(t, *kids), t)
    assert d == {"Owning Depot": "NR_Z9", "Cost Centre": "NRCC", "Trip Ref": "M0000001", "Status": "ACCEPTED",
                 "Carrier": "HAUL_DH", "Delivery Type": "STANDARD"}


def test_the_order_window_reads_back_plainly():
    f = el("internal frame", "Order details for 11111111", at=(0, 59, 1240, 700), lv=1)
    kids = [el("text", "Status Required", "UNSCHEDULED"), el("text", "Oms Ref", "11111111"),
            el("text", "Customer Ref", "1234567-1-1"), el("check box", "Booked In", st=["checked"]),
            el("text", "Collect From", "Abc11111", lv=3), el("text", "", "Made Up Depot", lv=3),
            el("text", "Collect Times", "24/11/26", lv=3), el("text", "", "08:00", lv=3),
            el("text", "to", "24/11/26", lv=3), el("text", "", "16:00", lv=3),
            el("text", "Product Type", "SHORT_RAIL", at=(10, 475, 121, 23), lv=3),
            el("text", "Qty", "   10.000", at=(241, 475, 92, 23), lv=3),
            el("text", "Weight", "  10,000.00", at=(333, 475, 85, 23), lv=3),
            el("text", "", "Strategy 1 - Flats & Hiabs", lv=3),
            el("text", "Special \nInstructions Multiline", "Made up note - Emailed DO 01/11", lv=3)]
    d = C.read_detail(screen(f, *kids), f)
    assert d["status"] == "UNSCHEDULED" and d["oms"] == "11111111" and d["booked_in"]
    assert d["collect_from"] == {"code": "Abc11111", "name": "Made Up Depot"}
    assert d["collect"] == "24/11/26 08:00 - 24/11/26 16:00"
    assert d["items"][0]["Product Type"] == "SHORT_RAIL" and d["items"][0]["Qty"] == "10.000"
    assert d["business_type"].startswith("Strategy 1") and d["special_instructions"].endswith("DO 01/11")


def test_nc_rows_find_the_first_empty_row():
    box = el("internal frame", "Non conformance", at=(0, 100, 1100, 300), lv=1)
    kids = [el("combo box", "", "Supplier Issue", at=(20, 171, 308, 25), lv=2),
            el("combo box", "", "Load", at=(328, 171, 100, 25), lv=2),
            el("text", "", "old comment", at=(428, 171, 400, 25), lv=2),
            el("combo box", "", "", at=(20, 196, 308, 25), lv=2),
            el("combo box", "", "", at=(328, 196, 100, 25), lv=2),
            el("text", "", "", at=(428, 196, 400, 25), lv=2)]
    rows = C.nc_rows(screen(box, *kids))
    assert [(r["reason"], r["activity"], r["comment"]) for r in rows] == [("Supplier Issue", "Load", "old comment"),
                                                                        ("", "", "")]


def test_a_delivery_comment_is_never_sent_without_commit(capsys):
    # its box saves by itself, so there is no dry run for it (a note's dry run is honoured since main 88c132c)
    got = C.run_item({"kind": "update", "lines": ["1234567-1-1"], "set": {"comments": "Jo 07000 000000"}}, commit=False)
    assert got["done"] is False and "not sent" in got["said"]
    assert "NOT SENT" in capsys.readouterr().out


def test_window_ends_and_delivery_type_rows():
    assert C.window_ends("10/02/27 08:00 - 16:00", "x") == (("10/02/27", "08:00"), ("10/02/27", "16:00"))
    assert C.window_ends("10/02/27 22:00 - 11/02/27 6:00", "x") == (("10/02/27", "22:00"), ("11/02/27", "06:00"))
    try:
        C.window_ends("tomorrow", "--deliver")
        raise AssertionError("should refuse")
    except C.Fail:
        pass
    win = el("internal frame", "Delivery Types", at=(760, 328, 423, 506), lv=1)
    rows = [el("label", "Delivery Type:NEXT DAY\tDescription:Next day", lv=2),
            el("label", "Delivery Type:Next Day\tDescription:old", lv=2)]
    assert C.type_rows(screen(win, *rows)) == ["NEXT DAY", "Next Day"]


def test_service_rules():
    rails = {"items": [{"Product Type": "SHORT_RAIL"}], "veh_type": "NR_40ft Artic Flatbed"}
    ballast = {"items": [{"Product Type": "LOOSE_BALLAST"}], "veh_type": "NR_Rigid (Up to 40ft)"}
    C.service_rails(["PTS", "REAR STEER"], rails)                         # fine on rails and an artic
    for adds, d in ((["PTS"], ballast), (["REAR STEER"], ballast)):
        try:
            C.service_rails(adds, d)
            raise AssertionError("should refuse")
        except C.Fail:
            pass


def test_every_route_has_its_arguments():
    for name in C.ROUTES:
        assert C._args(name).prog.endswith(name)
    assert C.main(["list"]) == 0


def _never(*a, **k):
    raise AssertionError("CTMS was touched")


def test_a_ref_on_two_lines_picks_the_live_one_never_the_cancelled_one():
    # 26/11: a line's cancelled twin was listed first in Order Summary, and it was the one updated
    rows = [{"ref": "9100001-1-1", "status": "CANCELLED"}, {"ref": "9100001-1-1", "status": "UNSCHEDULED"},
            {"ref": "9100001-2-1", "status": "UNSCHEDULED"}]
    assert C.pick_line(rows, "9100001-1-1") is rows[1]
    assert C.pick_line(rows, "9100001-1-1", gone=True) is rows[0]          # a restore wants the cancelled one
    assert C.pick_line(rows[:1], "9100001-1-1") is rows[0]                 # only a cancelled one: open_order refuses it
    assert C.pick_line(rows, "9100009-1-1") is None


def test_no_route_opens_a_cancelled_or_aborted_line(monkeypatch):
    monkeypatch.setattr(C, "act", _never)
    for status in ("CANCELLED", "ABORTED"):
        monkeypatch.setattr(C, "order_search", lambda ref, s=None, st=status: ([{"ref": ref, "status": st, "cells": {}}], None))
        try:
            C.open_order("9100001-1-1", modify_scheduled=True)
            raise AssertionError("opened")
        except C.Fail as e:
            assert "left alone, nothing opened" in str(e) and status in str(e)


def test_no_price_charge_or_percentage_goes_into_ctms():
    # his 26/11: "we don't do 75% cancellations ... we don't mention the price" (a 23/11 comment carried both)
    for bad in ("Haulier charge 75% = £123.45 per load", "charge 75 % agreed", "cost 500 GBP", "500 pounds", "ten per cent"):
        try:
            C.no_price(bad, "a non-conformance comment")
            raise AssertionError(bad)
        except C.Fail as e:
            assert "no prices" in str(e)
    for fine in ("Site postponed to 10/02/2027 (access issues - J Bloggs 20/11). Re-ordered for 10/02/2027.",
                 "30/11/26 12:00-14:00 - Sam 07700900000 - HIAB required - W3W ///index.home.raft",
                 "Cancelled 23/11: site postponed (J Bloggs)", "No cancellation charges"):
        C.no_price(fine, "a comment")


def test_the_comment_routes_refuse_a_price_before_ctms_is_touched(monkeypatch):
    import argparse
    monkeypatch.setattr(C, "run_item", _never)
    monkeypatch.setattr(C, "close_orders", _never)
    update = argparse.Namespace(refs=["9100001-1-1"], collect=None, deliver=None, comments="Haulier charge 75% per load",
                                veh=None, service=None, no_service=None, storage=None, anyway=False, same_day=False,
                                commit=True)
    note = argparse.Namespace(ref="9100001-1-1", note="Cancelled 23/11 - charge £123.45", modify=False, commit=True)
    nc = argparse.Namespace(ref="9100001-1-1", comment="Site postponed. Haulier charge 75% = £123.45 per load",
                            reason="SUPP", activity="Load", modify=False, commit=True)
    for fn, a in ((C.r_order_update, update), (C.r_order_note, note), (C.r_order_nc, nc)):
        try:
            fn(a)
            raise AssertionError(fn.__name__)
        except C.Fail as e:
            assert "no prices" in str(e)
