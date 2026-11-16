"""His X on the CTMS to-do (todo_dismiss): an item off the list - and one from a site's reply that wasn't their
details puts the order back to waiting for them, with that email never read as their answer again. Made-up orders
and names only.

    python tests/test_todo_dismiss.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_todo  # noqa: E402
import todo_dismiss as X  # noqa: E402
import tracker  # noqa: E402


class _Files:
    """The tracker and the to-do in a folder of their own."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="todo-x-")
        self.keep = tracker.PATH, ctms_todo.STORE
        tracker.PATH, ctms_todo.STORE = os.path.join(self.tmp, "tracker.json"), os.path.join(self.tmp, "todo.json")
        self.notes = os.path.join(self.tmp, "notes_done.json")
        return self

    def __exit__(self, *a):
        tracker.PATH, ctms_todo.STORE = self.keep
        shutil.rmtree(self.tmp, ignore_errors=True)

    def items(self):
        return [i for i in ctms_todo.listing(tracker.PATH, None, self.notes) if i["kind"] != "note"]


def test_a_reply_that_was_not_the_details_comes_off_and_its_order_waits_for_them_again():
    with _Files() as f:
        rec = {"id": "9100001|20/11/2026", "orders": ["9100001", "9100002"], "kind": "delivery", "status": "sent",
               "to": "sam@example.net", "name": "Sam Example", "emailed_at": "2026-11-11 16:07",
               "reply_at": "2026-11-12 16:03", "sendoff_ready": True, "missing": ["delivery date"],
               "details": {"date": {"value": "21/11/2026"}, "time": {"earliest": "22:00", "latest": "23:00"}}}
        phoned = {"id": "9100003|20/11/2026", "orders": ["9100003"], "kind": "delivery", "status": "sent",
                  "reply_at": "2026-11-12 09:00", "phoned_at": "2026-11-12 09:00", "sendoff_ready": True}
        tracker.save({"records": [rec, phoned]})
        it = ctms_todo.replied(rec, when="2026-11-12 16:03")
        assert sorted(i["source"] for i in f.items()) == ["reply", "services"]          # the update + its Night/Saturday
        out = X.dismiss(it["id"], now="2026-11-16 09:45", notes_done=f.notes)
        assert out["ok"] and out["tracker"] and "waits for its details again" in out["said"], out
        assert "Night / weekend reminder" in out["said"] and f.items() == []
        r, p = tracker.load()["records"]
        assert not {"reply_at", "details", "missing", "sendoff_ready"} & set(r), r
        assert r["replies_after"] == "2026-11-12 16:03" and r["not_the_details"]["at"] == "2026-11-16 09:45"
        assert p["reply_at"] == "2026-11-12 09:00" and p["sendoff_ready"]          # his call's details: his
        assert X.dismiss(it["id"], notes_done=f.notes)["ok"] is False               # off already: nothing changes


def test_any_other_item_only_comes_off_the_list():
    with _Files() as f:
        rec = {"id": "9100010|20/11/2026", "orders": ["9100010"], "kind": "delivery", "status": "sent",
               "reply_at": "2026-11-12 16:03", "sendoff_ready": True, "details": {"date": "21/11/26"}}
        tracker.save({"records": [rec]})
        it = ctms_todo.add("booking", ["9100010"], "Book with Sam's Haulage at 500", when="2026-11-12 17:00")
        out = X.dismiss(it["id"], now="2026-11-16 09:45", notes_done=f.notes)
        assert out["ok"] and not out["tracker"] and "waits for its details" not in out["said"], out
        assert tracker.load()["records"][0]["reply_at"] == "2026-11-12 16:03" and f.items() == []


class _Mail:
    def __init__(self, when):
        self.ReceivedTime = when


def test_the_reply_check_never_takes_that_email_again_but_takes_the_next():
    taken = _Mail(datetime(2026, 11, 12, 16, 3, 40))        # the one the 16:03 check took - in that same minute
    older = _Mail(datetime(2026, 11, 12, 9, 0))
    real = _Mail(datetime(2026, 11, 16, 11, 5))
    rec = {"replies_after": "2026-11-12 16:03"}
    assert X.after_dismissed(rec, [real, taken, older]) == [real]
    assert X.after_dismissed({}, [real, taken]) == [real, taken]               # no X: as ever
    assert X.after_dismissed(rec, [_Mail(None)]) == []                         # no time on it: not risked


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in list(globals().items()) if n.startswith("test_") and callable(fn)]
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
