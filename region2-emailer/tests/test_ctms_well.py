"""The order well read as text (02/11): Planning's grid handed over by the Access Bridge as nameless cells with their
places on the screen - the order number column found by what it holds, the rest by where they sit from it, rows by
height. Made-up orders only.

    python tests/test_ctms_well.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_well as W  # noqa: E402

X0, Y0 = 443, 604                  # where the Cust Ref column's first cell sat on 02/11


def _cell(col, row, value, w=100):
    return {"r": "text", "nm": "", "v": value, "lv": 2, "st": ["read-only"],
            "at": [X0 + W.OFFSETS[col], Y0 + 23 * row, w, 23]}


def _planning(rows_, blank=3):
    els = [{"r": "internal frame", "nm": "Planning", "lv": 0},
           {"r": "text", "nm": "TZ Abbr", "v": "", "lv": 2, "at": [940, 300, 50, 23]},       # the stops grid: named
           {"r": "push button", "nm": "Order Filters", "lv": 1, "at": [1557, 544, 95, 23]}]
    els += [{"r": "text", "nm": "", "v": "", "lv": 2, "at": [400, Y0 + 23 * i, 30, 23]} for i in range(15)]
    # column by column, as CTMS hands them over - and not in the order they show
    for col in ("cust_ref", "from_loc", "to_loc", "booking_ref", "from_post", "to_post", "collect", "deliver",
                "weight"):
        els += [_cell(col, i, r.get(col, "")) for i, r in enumerate(rows_)]
        els += [_cell(col, len(rows_) + i, "") for i in range(blank)]
    return els


ROWS = [{"cust_ref": "SC9100001", "booking_ref": "VAE/SC9100001", "from_loc": "Example Rail", "from_post": "DN1 1AA",
         "to_loc": "Exampletown Yard", "to_post": "YO1 1AA", "collect": "01/11/26", "deliver": "02/11/26",
         "weight": "2000"},
        {"cust_ref": "9100002-1-1", "booking_ref": "HA9100002-306-1", "from_loc": "Example Quarry",
         "from_post": "BA1 1AA", "to_loc": "London 1052327", "to_post": "E1 1AA", "collect": "02/11/26",
         "deliver": "02/11/26", "weight": "10000"}]


def test_the_rows_on_screen_come_back_by_order_number_with_every_column_named():
    got = W.rows(_planning(ROWS))
    assert [r["cust_ref"] for r in got] == ["SC9100001", "9100002-1-1"]
    assert got[1]["booking_ref"] == "HA9100002-306-1" and got[1]["to_post"] == "E1 1AA"
    assert got[1]["deliver"] == "02/11/26" and got[1]["weight"] == "10000" and got[0]["from_loc"] == "Example Rail"
    assert got[0]["cell"] == [X0, Y0, 100, 23]                          # where its order number sits


def test_an_order_is_found_by_its_number_and_aimed_at_the_middle_of_it():
    got = W.rows(_planning(ROWS))
    row = W.find(got, "9100002-1-1")
    assert row and W.point(row) == [X0 + 50, Y0 + 23 + 11]
    assert W.find(got, "9100002-1-1 ".upper()) is row and W.find(got, "9100003-1-1") is None


def test_no_planning_or_no_order_numbers_means_no_rows_never_a_guess():
    assert W.rows([{"r": "internal frame", "nm": "Order Summary", "lv": 0}]) == []
    assert W.rows(_planning([])) == []


def test_a_further_page_adds_only_the_orders_not_seen():
    seen = W.rows(_planning(ROWS))
    page = W.rows(_planning([ROWS[1], dict(ROWS[0], cust_ref="SC9100009")]))
    assert W.merge(seen, page) == 1 and [r["cust_ref"] for r in seen] == ["SC9100001", "9100002-1-1", "SC9100009"]
    assert W.merge(seen, page) == 0


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
