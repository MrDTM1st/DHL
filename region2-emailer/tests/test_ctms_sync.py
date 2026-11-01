"""What CTMS says, put on the map (ctms_sync): a delivery with no line left unscheduled is booked and comes off; one
whose day CTMS no longer has, every open line now on one other day, moves there; a filled Veh Type is ready; an order
CTMS does not know, or open on several other days, is left alone. Made-up order numbers only.

    python tests/test_ctms_sync.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_sync as C  # noqa: E402


def _ln(ref, status, deliver):
    return {"ref": ref, "status": status, "deliver_by": deliver + " 16:01", "schedule": ""}


def test_a_delivery_with_nothing_left_unscheduled_is_booked():
    assert C.judge([_ln("9100040-1-1", "SCHEDULED", "05/11/26")], "05/11/2026") == ("booked", None)
    # its own day's line booked; another day's line still open is another delivery's business
    assert C.judge([_ln("9100040-1-1", "SCHEDULED", "05/11/26"), _ln("9100040-2-1", "UNSCHEDULED", "12/11/26")],
                   "05/11/2026") == ("booked", None)
    assert C.judge([_ln("9100040-1-1", "CANCELLED", "05/11/26")], "05/11/2026") == ("booked", None)
    assert C.judge([_ln("9100040-1-1", "UNSCHEDULED", "05/11/26"), _ln("9100040-2-1", "SCHEDULED", "05/11/26")],
                   "05/11/2026") == ("open", None)


def test_a_delivery_ctms_has_moved_follows_it_but_only_when_there_is_one_day_to_go_to():
    assert C.judge([_ln("9100041-1-1", "UNSCHEDULED", "09/11/26")], "05/11/2026") == ("moved", "09/11/2026")
    assert C.judge([_ln("9100041-1-1", "UNSCHEDULED", "09/11/26"), _ln("9100041-2-1", "UNSCHEDULED", "10/11/26")],
                   "05/11/2026") == (None, None)                # moved - but to which? left alone
    assert C.judge([], "05/11/2026") == (None, None)            # CTMS does not know it


def test_the_plan_takes_off_moves_and_marks_ready_and_leaves_the_rest():
    recs = [{"id": "9100050|05/11/2026", "orders": ["9100050"], "delivery_date": "05/11/2026"},
            {"id": "9100051|05/11/2026", "orders": ["9100051"], "delivery_date": "05/11/2026"},
            {"id": "9100052|06/11/2026", "orders": ["9100052"], "delivery_date": "06/11/2026"},
            {"id": "9100053|06/11/2026", "orders": ["9100053"], "delivery_date": "06/11/2026"},
            {"id": "9100054|07/11/2026", "orders": ["9100054"], "delivery_date": "07/11/2026"},     # not looked up
            {"id": "c|", "orders": ["9100055"], "delivery_date": "", "kind": "collection"}]
    found = {"9100050|05/11/2026": {"lines": [_ln("9100050-1-1", "SCHEDULED", "05/11/26")]},
             "9100051|05/11/2026": {"lines": [_ln("9100051-1-1", "UNSCHEDULED", "08/11/26")]},
             "9100052|06/11/2026": {"lines": [_ln("9100052-1-1", "UNSCHEDULED", "06/11/26")],
                                    "veh": {"9100052-1-1": True}},
             "9100053|06/11/2026": {"lines": []},
             "9100055|": {"lines": [_ln("9100055-1-1", "SCHEDULED", "05/11/26")]},
             "AH01/11/2026/AB-CD|03/11/2026": {"lines": [_ln("AH01/11/2026/AB-CD", "SCHEDULED", "03/11/26")]},
             "AH02/11/2026/EF-GH|04/11/2026": {"lines": [_ln("AH02/11/2026/EF-GH", "UNSCHEDULED", "04/11/26")]}}
    jobs = [{"id": "adhoc|AH01/11/2026/AB-CD|1", "orders": ["AH01/11/2026/AB-CD"], "delivery_date": "03/11/2026"},
            {"id": "adhoc|AH02/11/2026/EF-GH|2", "orders": ["AH02/11/2026/EF-GH"], "delivery_date": "04/11/2026"}]
    p = C.plan(found, recs, jobs)
    assert p["booked"] == ["9100050|05/11/2026"]
    assert p["moved"] == [("9100051|05/11/2026", "08/11/2026")]
    assert p["veh"] == {"9100052|06/11/2026": True}
    assert p["unknown"] == ["9100053"]
    assert p["jobs"] == ["adhoc|AH01/11/2026/AB-CD|1"]             # the booked ad hoc; the open one stays
    assert p["looked"] == ["9100050|05/11/2026", "9100051|05/11/2026", "9100052|06/11/2026", "9100053|06/11/2026"]


def test_the_weight_off_the_cards_is_the_deliverys_lines_added_up():
    recs = [{"id": "9100060|05/11/2026", "orders": ["9100060"], "delivery_date": "05/11/2026"},
            {"id": "9100061|06/11/2026", "orders": ["9100061"], "delivery_date": "06/11/2026"}]
    found = {"9100060|05/11/2026": {"lines": [_ln("9100060-1-1", "UNSCHEDULED", "05/11/26"),
                                              _ln("9100060-2-1", "UNSCHEDULED", "05/11/26")],
                                    "weight": {"9100060-1-1": 1900.0, "9100060-2-1": 3200.5}},
             "9100061|06/11/2026": {"lines": [_ln("9100061-1-1", "UNSCHEDULED", "06/11/26")]}}     # card not read
    p = C.plan(found, recs)
    assert p["weight"] == {"9100060|05/11/2026": {"kg": 5100.5,
                                                   "lines": {"9100060-1-1": 1900.0, "9100060-2-1": 3200.5}}}


def test_a_reply_update_ctms_shows_done_comes_off_the_to_do_list():
    items = [{"id": "t1", "kind": "update", "orders": ["9100080"]},          # Veh Type now filled: done
             {"id": "t2", "kind": "update", "orders": ["9100081"]},          # cancelled in CTMS: nothing to update
             {"id": "t3", "kind": "update", "orders": ["9100082"]},          # still open, Veh Type empty: stays
             {"id": "t4", "kind": "update", "orders": ["9100083"]},          # not looked up: stays
             {"id": "t5", "kind": "note", "orders": ["9100080"]},            # a note is not this rule's
             {"id": "t6", "kind": "update", "orders": ["9100080"], "done_at": "2026-11-01 01:40"}]
    found = {"9100080|": {"lines": [_ln("9100080-1-1", "UNSCHEDULED", "05/11/26")], "veh": {"9100080-1-1": True}},
             "9100081|10/11/2026": {"lines": [_ln("9100081-1-1", "CANCELLED", "10/11/26")]},
             "9100082|": {"lines": [_ln("9100082-1-1", "UNSCHEDULED", "06/11/26")], "veh": {"9100082-1-1": False}}}
    assert C.todo_done(found, items) == ["t1", "t2"]


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
