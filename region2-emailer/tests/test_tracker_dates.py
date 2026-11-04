"""A replied order stays on the tracker - purple on the map - until it is booked, and leaves on its own only once its
delivery date is a week gone; a reply's firm date moves the order to it (one record, not a second beside it).
Made-up order numbers only.

    python tests/test_tracker_dates.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import delivery_details as D  # noqa: E402
import tracker as T  # noqa: E402


def _day(offset):
    return (datetime.now() + timedelta(days=offset)).strftime("%d/%m/%Y")


def _rec(order, date, **kw):
    r = {"id": T._key([order], date), "orders": [order], "delivery_date": date, "chases": 0,
         "reply_at": None, "sendoff_ready": False}
    r.update(kw)
    return r


def test_a_ready_order_stays_until_booked_and_goes_only_a_week_after_its_date():
    ready = dict(reply_at="2026-11-01 09:00", sendoff_ready=True)
    d = {"records": [_rec("9100001", _day(5), **ready),       # due next week: ready to book
                     _rec("9100002", _day(-3), **ready),      # three days gone: still on, booking unseen
                     _rec("9100003", _day(-8), **ready),      # a week gone: stale
                     _rec("9100004", _day(-30)),              # never replied: not this rule's to touch
                     _rec("9100005", "", **ready)]}           # no date: never stale
    assert T.drop_completed(d) == 1
    assert [r["orders"][0] for r in d["records"]] == ["9100001", "9100002", "9100004", "9100005"]
    # finished during the check that is removing: kept, so its parsed reply is saved
    d = {"records": [_rec("9100003", _day(-8), **ready)]}
    assert T.drop_completed(d, keep_ids={d["records"][0]["id"]}) == 0 and len(d["records"]) == 1


def test_a_moved_date_moves_the_record_and_takes_in_the_one_already_there():
    old, new = _day(4), _day(6)
    r = _rec("9100010", old, reply_at="2026-11-01 09:00", chases=1)
    dup = _rec("9100010", new, chases=2)                       # an earlier chase added it on the new day
    other = _rec("9100011", new)
    d = {"records": [r, dup, other]}
    assert T.move_date(d, r, new, "the site's reply") is True
    assert r["delivery_date"] == new and r["id"] == T._key(["9100010"], new)
    assert r["date_was"] == old and r["date_moved_by"] == "the site's reply" and r.get("date_moved_at")
    assert d["records"] == [r, other] and r["chases"] == 2      # one dot on the new day, its history kept
    assert T.move_date(d, r, new) is False                      # already there
    for bad in (None, "", "next Tuesday", "2026-11-09"):
        assert T.move_date(d, r, bad) is False and r["delivery_date"] == new, bad


def test_only_a_firm_date_in_a_reply_moves_the_order():
    def cell(**kw):
        c = {"value": "09/11/2026", "confidence": D.HIGH, "flexible": False, "options": ["09/11/2026"]}
        c.update(kw)
        return {"date": c}
    assert D.firm_date(cell()) == "09/11/2026"
    assert D.firm_date(cell(options=[])) == "09/11/2026"
    assert D.firm_date(cell(confidence=D.AMBER)) is None                       # waits for his confirm
    assert D.firm_date(cell(flexible=True)) is None                            # "any day that week"
    assert D.firm_date(cell(options=["09/11/2026", "10/11/2026"])) is None      # a choice of days
    assert D.firm_date(cell(value=None)) is None
    assert D.firm_date({}) is None and D.firm_date(None) is None


def test_a_real_reply_with_a_new_day_settles_on_it():
    body = (f"Hi,\nDelivery date: {_day(10)}\nDelivery time: 08:00 - 10:00\nHIAB on site for offloading.\n"
            "Contact: Sam Example 07700 900123\n")
    assert D.firm_date(D.parse_reply(body)) == _day(10)
    # a day already gone never moves the order: a footer's date took one to 2003, and the stale sweep took it off (02/11)
    assert D.firm_date(D.parse_reply(f"Hi,\nDelivery date: {_day(-10)}\nDelivery time: 08:00\n")) is None


def test_a_booked_order_stays_remembered_however_many_higher_numbers_are_on_file():
    keep = T.DROPS
    with tempfile.TemporaryDirectory() as tmp:
        T.DROPS = os.path.join(tmp, "_booked_drops.json")
        try:
            T.remember_drops([str(7000000 + i) for i in range(450)])
            T.remember_drops(["5012345"])                       # booked today: sorts first, but it is the newest
            assert "5012345" in T.booked_drops() and len(T.booked_drops()) == 451
            T.remember_drops(["7000001", "5012345"])            # already there: no second copy, no move
            with open(T.DROPS, encoding="utf-8") as f:
                assert json.load(f)[-1] == "5012345"
            T.remember_drops([str(8000000 + i) for i in range(T.DROPS_KEEP - 1)])
            with open(T.DROPS, encoding="utf-8") as f:
                got = json.load(f)
            assert len(got) == T.DROPS_KEEP and got[0] == "5012345"    # the oldest trimmed, not the lowest
            assert "7000449" not in got and not os.path.exists(T.DROPS + ".tmp")
        finally:
            T.DROPS = keep


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
