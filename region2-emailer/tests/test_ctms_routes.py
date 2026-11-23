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


def test_notes_and_comments_are_never_sent_without_commit(capsys):
    got = C.run_item({"kind": "note", "lines": ["1234567-1-1"], "set": {"note": " - Emailed DO 24/11"}}, commit=False)
    assert got["done"] is False and "not sent" in got["said"]
    got = C.run_item({"kind": "update", "lines": ["1234567-1-1"], "set": {"comments": "Jo 07000 000000"}}, commit=False)
    assert got["done"] is False
    assert "NOT SENT" in capsys.readouterr().out


def test_every_route_has_its_arguments():
    for name in C.ROUTES:
        assert C._args(name).prog.endswith(name)
    assert C.main(["list"]) == 0
