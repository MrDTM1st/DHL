"""Book's line checks (03/11, work_pc/ctms_lines.py), Order Summary's "up to", and the home PC's side: which quantity
the desk knows, and the CTMS to-do's update run before a booking instead of refusing it. Screens built with the names
and places read live on 03/11. Made-up orders only.

    python -m pytest -q tests/test_ctms_lines.py
"""
import os
import sys
from datetime import datetime

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_lines as L  # noqa: E402
import ctms_orders  # noqa: E402
import book_run  # noqa: E402


def _card(tab="Detail", grid=(), items=()):
    els = [{"r": "internal frame", "nm": "Order details for 11000001", "lv": 0, "at": [20, 151, 1239, 702]},
           {"r": "page tab", "nm": "Detail", "lv": 1, "at": [25, 274, 76, 23], "st": ["selected"] if tab == "Detail" else None},
           {"r": "page tab", "nm": "Order Items", "lv": 1, "at": [98, 274, 86, 23],
            "st": ["selected"] if tab == "Order Items" else None}]
    for i, (prod, qty) in enumerate(grid):
        els += [{"r": "text", "nm": "Product Type", "v": prod, "lv": 2, "at": [30, 567 + 23 * i, 121, 23]},
                {"r": "text", "nm": "Qty", "v": f"   {qty:.3f}", "lv": 2, "at": [261, 567 + 23 * i, 92, 23]},
                {"r": "text", "nm": "Weight", "v": "  1,000.00", "lv": 2, "at": [353, 567 + 23 * i, 85, 23]},
                {"r": "text", "nm": "Weight", "v": "", "lv": 2, "at": [990, 567 + 23 * i, 70, 23]}]
    els.append({"r": "text", "nm": "Product Type", "v": "", "lv": 2, "at": [30, 660, 121, 23], "st": ["read-only"]})
    for i, (ident, ordered) in enumerate(items):
        els += [{"r": "text", "nm": "Order Items tab page Identifier Required" if i == 0 else "Identifier Required",
                 "v": ident, "lv": 2, "at": [55, 343 + 24 * i, 80, 24]},
                {"r": "text", "nm": "Product", "v": ident, "lv": 2, "at": [135, 343 + 24 * i, 80, 24]},
                {"r": "text", "nm": "Ordered", "v": f"      {ordered:g}", "lv": 2, "at": [676, 343 + 24 * i, 70, 24]}]
    return els


def test_the_detail_grid_is_read_only_off_the_detail_tab():
    rows = L.detail(_card("Detail", grid=[("WHEELSETS", 16)]))
    assert [(r["product"], r["qty"], r["weight"]) for r in rows] == [("WHEELSETS", 16.0, 1000.0)]
    assert L.detail(_card("Order Items", grid=[("WHEELSETS", 16)])) is None


def test_order_items_are_read_by_their_names_whatever_tab_page_prefix_they_carry():
    its = L.items(_card("Order Items", items=[("WHEELSETS", 10), ("WHEELSET_AXLE", 6)]))
    assert [(i["identifier"], i["ordered"]) for i in its] == [("WHEELSETS", 10.0), ("WHEELSET_AXLE", 6.0)]


def _plan(grid, items, want=None):
    return L.plan("9100001-1-1", [{"product": p, "qty": q} for p, q in grid],
                  [{"identifier": i, "ordered": o} for i, o in items], want)


def test_all_right_means_nothing_to_change():
    assert _plan([("S&C", 1)], [("S&C", 1)], 1) == {"items": [], "qty": None, "said": []}
    assert _plan([("S&C", 1)], [("s&c", 1)]) == {"items": [], "qty": None, "said": []}


def test_an_item_off_the_detail_tabs_product_is_put_to_it():
    got = _plan([("WHEELSETS", 16)], [("S&C", 16)])
    assert got["items"] == [(0, "WHEELSETS", None)] and got["qty"] is None


def test_the_orders_quantity_puts_both_places_right():
    got = _plan([("S&C", 15)], [("S&C", 14)], 16)
    assert got["items"] == [(0, None, 16)] and got["qty"] == 16


def test_what_the_desk_cant_settle_is_asked_never_guessed():
    with pytest.raises(L.Doubt, match="which is right"):
        _plan([("S&C", 16)], [("S&C", 15)])                       # no order figure, the two disagree
    with pytest.raises(L.Doubt, match="which should it be"):
        _plan([("S&C", 1), ("RAILS", 1)], [("SLEEPERS", 2)])       # two products: which one?
    with pytest.raises(L.Doubt, match="which goes where"):
        _plan([("S&C", 10)], [("S&C", 6), ("S&C", 6)], 16)         # two items to share a different total
    with pytest.raises(L.Doubt, match="no Product Type"):
        _plan([], [("S&C", 1)])
    with pytest.raises(L.Doubt, match="no item"):
        _plan([("S&C", 1)], [])


def test_ctrl_ls_list_is_read_top_first():
    els = [{"r": "internal frame", "nm": "Product Items", "lv": 1, "at": [133, 346, 456, 456]},
           {"r": "text", "nm": "Find", "v": "WHEEL%", "lv": 2, "at": [169, 396, 412, 26]},
           {"r": "label", "nm": "Item_Id:WHEELSETS\tItem_Description:Wheelsets", "lv": 3, "at": [-1, -1, -1, -1],
            "st": ["focused", "selected"]},
           {"r": "label", "nm": "Item_Id:WHEELSET_AXLE\tItem_Description:Axle", "lv": 3, "at": [-1, -1, -1, -1]},
           {"r": "push button", "nm": "OK ALT O", "lv": 2, "at": [363, 763, 61, 31]}]
    assert L.choices(els) == [("WHEELSETS", "Wheelsets"), ("WHEELSET_AXLE", "Axle")]
    assert L.button(els, L.LIST_WINDOW, "OK")["at"] == [363, 763, 61, 31]
    assert L.choices([]) is None


# -- Order Summary's "up to"
UPTO = {"r": "text", "nm": "up to", "v": "04/11/26", "lv": 2, "at": [216, 251, 67, 27]}


def test_up_to_on_tomorrow_is_put_well_ahead_by_its_own_place():
    steps = ctms_orders.upto([UPTO], now=datetime(2026, 11, 3, 18, 0))
    assert steps[0] == {"action": "click", "screen": [249, 264], "after": 0.15}
    assert steps[-1]["text"] == "03/03/27"                          # 120 days on


def test_up_to_far_enough_ahead_or_not_there_is_left_alone():
    assert ctms_orders.upto([dict(UPTO, v="30/03/27")], now=datetime(2026, 11, 3)) == []
    assert ctms_orders.upto([], now=datetime(2026, 11, 3)) == []
    assert ctms_orders.upto({"elements": [dict(UPTO, at=[-1, -1, -1, -1])]}, now=datetime(2026, 11, 3)) == []


# -- the home PC: the order's quantity, and the to-do first
def test_the_desk_knows_an_ad_hocs_quantity_and_a_one_product_orders():
    assert book_run.quantities({"kind": "adhoc", "orders": ["AH1-2-3"], "qty": "16"}) == {"AH1-2-3": 16.0}
    assert book_run.quantities({"orders": ["6055913"], "materials": "27x sleepers", "product_codes": ["0057/1"]}) == \
        {"6055913": 27.0}


def test_the_desk_doesnt_guess_a_quantity_it_cant_share_out():
    assert book_run.quantities({"kind": "adhoc", "orders": ["AH1"], "qty": "X1 DRUM"}) == {}
    assert book_run.quantities({"orders": ["7116791"], "materials": "20x ballast, 7x aggregate"}) == {}
    assert book_run.quantities({"orders": ["6055854", "6055859"], "materials": "622x sleepers"}) == {}
    assert book_run.quantities({"orders": ["5034161"], "materials": "37x rails", "product_codes": ["a", "b"]}) == {}


def test_the_to_dos_update_runs_first_and_a_hand_item_still_stops_it(monkeypatch):
    import ctms_run
    ran = []
    monkeypatch.setattr(ctms_run, "run", lambda ids, run_id=0: ran.append(ids) or {"ok": True, "said": "1 of 1 done"})
    ok, how = book_run.run_owed([{"id": "u1", "kind": "update", "what": "Update 9100001"}])
    assert ok and ran == [["u1"]] and "went on first" in how
    ok, how = book_run.run_owed([{"id": "b1", "kind": "booking", "what": "Book with NOC"}])
    assert not ok and "isn't something Book can type" in how
    monkeypatch.setattr(ctms_run, "run", lambda ids, run_id=0: {"ok": False, "said": "0 of 1 done; held, CTMS has it"})
    ok, how = book_run.run_owed([{"id": "u1", "kind": "update", "what": "Update 9100001"}])
    assert not ok and "didn't all go" in how


def test_a_tab_pages_prefix_said_over_and_over_is_still_the_same_field():
    # live 03/11: each visit to Order Items put "Order Items tab page " on its first Identifier once more
    els = _card("Order Items", items=[("WHEELSETS", 8)])
    els[3]["nm"] = "Order Items tab page Order Items tab page Order Items tab page Identifier Required"
    assert [(i["identifier"], i["ordered"]) for i in L.items(els)] == [("WHEELSETS", 8.0)]


def test_an_item_by_catalogue_number_whose_own_product_is_the_details_is_left_alone():
    rows = [{"product": "LOOSE_BALLAS", "qty": 28.0, "weight": None, "qty_box": None}]
    its = [{"identifier": "0057/100500/001", "product": "LOOSE_BALLAST", "ordered": 28.0, "cell": None}]
    assert L.plan("9100001-1-1_S1", rows, its) == {"items": [], "qty": None, "said": []}
    its[0]["product"] = "SLEEPERS"
    assert L.plan("9100001-1-1_S1", rows, its)["items"] == [(0, "LOOSE_BALLAS", None)]
