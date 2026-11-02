"""An order no email can go to - the sheet's address is mistyped or missing - stays visible until the right one is given,
and is never treated as sent. Made-up orders, people and files only.

    python tests/test_waitlist_address.py
"""
import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import waitlist as W  # noqa: E402

TODAY = date(2026, 11, 2)


def _fresh(*entries):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    W.PATH = path
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": list(entries)}, f)
    return path


def _entry(order, when, to=None, status="waiting"):
    return {"id": f"{order}|{when}", "orders": [order], "to": to, "date": when, "status": status,
            "site": "Test Yard", "postcode": "AB1 2CD", "name": "Sam", "contact_said": "Sam Test email: samtest.co.uk"}


def test_what_counts_as_an_address():
    assert W.has_address("sam.test@example.co.uk")
    assert W.has_address("Sam.O'Test2@example.co.uk")
    assert W.has_address("a@example.co.uk; b@example.co.uk")
    assert not W.has_address(None)
    assert not W.has_address("")
    assert not W.has_address("samtest.co.uk")                # no @
    assert not W.has_address("sam@example")                  # goes nowhere
    assert not W.has_address("sam test@")


def test_only_waiting_entries_with_no_address_show_soonest_first():
    _fresh(_entry("9100001", "20/11/2026"), _entry("9100002", "05/11/2026", to="samtest.co.uk"),
           _entry("9100003", "06/11/2026", to="sam@example.co.uk"), _entry("9100004", "07/11/2026", status="sent"))
    assert [e["orders"][0] for e in W.no_address()] == ["9100002", "9100001"]


def test_a_release_looks_at_them_however_far_off_so_they_can_close():
    _fresh(_entry("9100001", "20/12/2026"), _entry("9100002", "05/11/2026"),
           _entry("9100003", "19/12/2026", to="sam@example.co.uk"), _entry("9100004", "01/11/2026"))
    got = [e["orders"][0] for e in W.due_or_stuck(lead_days=21, today=TODAY)]
    assert got == ["9100002", "9100001"], got                # far off with an address waits; a passed date is overdue's


def test_typing_the_address_clears_it_and_it_goes_when_due():
    _fresh(_entry("9100001", "20/12/2026"))
    assert W.set_address("9100001|20/12/2026", " sam.test@example.co.uk ")
    assert W.no_address() == []
    e = W.load()["entries"][0]
    assert e["to"] == "sam.test@example.co.uk" and e["status"] == "waiting" and e["address_typed_at"]
    assert W.due(lead_days=21, today=TODAY) == []            # still only goes three weeks ahead


def test_a_typed_address_must_be_one_real_address_on_a_waiting_entry():
    _fresh(_entry("9100001", "20/12/2026"), _entry("9100002", "20/12/2026", status="sent"))
    for bad in ("samtest.co.uk", "", None, "a@example.co.uk; b@example.co.uk", "sam@example"):
        assert not W.set_address("9100001|20/12/2026", bad), bad
    assert not W.set_address("9100002|20/12/2026", "sam@example.co.uk")
    assert not W.set_address("nothing", "sam@example.co.uk")
    assert not W.load()["entries"][0]["to"]


def test_the_sheets_own_words_are_kept_on_a_new_entry():
    _fresh()
    assert W.add({"orders": ["9100001"], "to": None, "date": "20/12/2026", "contact_said": "Sam Test email: samtest.co.uk"})
    assert W.no_address()[0]["contact_said"] == "Sam Test email: samtest.co.uk"


def test_a_later_sheet_with_the_address_right_clears_it():
    _fresh()
    W.add({"orders": ["9100001"], "to": None, "date": "20/12/2026"})
    assert not W.add({"orders": ["9100001"], "to": "sam@example.co.uk", "date": "20/12/2026"})
    assert W.no_address() == []
    assert W.load()["entries"][0]["to"] == "sam@example.co.uk"


def test_a_later_sheet_never_overwrites_an_address_or_reopens_a_sent_one():
    _fresh(_entry("9100001", "20/12/2026", to="typed@example.co.uk"), _entry("9100002", "20/12/2026", status="sent"))
    W.add({"orders": ["9100001"], "to": "other@example.co.uk", "date": "20/12/2026"})
    W.add({"orders": ["9100002"], "to": "other@example.co.uk", "date": "20/12/2026"})
    a, b = W.load()["entries"]
    assert a["to"] == "typed@example.co.uk" and not b["to"]


def test_dealt_with_takes_it_off_but_never_one_with_an_address():
    _fresh(_entry("9100001", "20/12/2026"), _entry("9100002", "20/12/2026", to="sam@example.co.uk"))
    assert W.dealt_with("9100001|20/12/2026")
    assert not W.dealt_with("9100002|20/12/2026")
    assert not W.dealt_with("9100001|20/12/2026")            # gone already
    a, b = W.load()["entries"]
    assert a["status"] == "sent" and "dealt with it yourself" in a["note"]
    assert b["status"] == "waiting" and W.no_address() == []


if __name__ == "__main__":
    keep = W.PATH
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        finally:
            if W.PATH != keep and os.path.exists(W.PATH):
                os.remove(W.PATH)
            W.PATH = keep
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
