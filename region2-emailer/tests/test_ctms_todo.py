"""What CTMS still owes (ctms_todo): the tracker's Emailed/Chased notes plus what is remembered - escalations,
replies to update from, bookings - listed together, each done once. Made-up orders and names only.

    python tests/test_ctms_todo.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_todo as T  # noqa: E402


def _paths():
    d = tempfile.mkdtemp()
    return os.path.join(d, "todo.json"), os.path.join(d, "tracker.json"), os.path.join(d, "notes_done.json")


def test_an_escalation_leaves_an_escalated_note_per_order_and_never_twice():
    store, _, _ = _paths()
    a = T.escalated(["1234567", "7654321-1-1"], when="2026-10-30 19:40", path=store)
    assert [i["note"] for i in a] == [" - Escalated DO 30/10"] * 2
    assert [i["ref"] for i in a] == ["1234567-1-1", "7654321-1-1"]
    again = T.escalated(["1234567"], when="2026-10-30 19:45", path=store)
    assert again[0]["id"] == a[0]["id"] and len(T.load(store)["items"]) == 2


def test_a_reply_becomes_an_order_to_update_with_its_answers():
    store, _, _ = _paths()
    rec = {"orders": ["1234567"], "name": "Sam Example", "reply_at": "2026-10-30 13:23", "kind": "delivery",
           "details": {"date": "13/11/26", "time": "08:00"}, "missing": []}
    it = T.replied(rec, path=store)
    assert it["kind"] == "update" and "Sam Example replied 30/10" in it["what"]
    assert it["details"]["details"]["time"] == "08:00"
    assert T.replied(dict(rec, kind="collection"), path=store) is None      # a supplier's collection reply


def test_the_list_holds_the_trackers_notes_and_the_remembered_rest_and_done_takes_them_off():
    store, tracker, notes_done = _paths()
    with open(tracker, "w", encoding="utf-8") as f:
        json.dump({"records": [{"orders": ["1111111"], "status": "sent", "kind": "delivery",
                                "emailed_at": "2026-10-28 15:06", "chases": 1,
                                "last_chased_at": "2026-10-30 09:00"}]}, f)
    T.add("booking", ["2222222"], "Book with Sam's Haulage at 500", path=store, when="2026-10-30 19:00")
    T.escalated(["3333333"], when="2026-10-30 19:40", path=store)
    items = T.listing(tracker, store, notes_done)
    whats = [(i["kind"], i["orders"][0], i.get("note") or "") for i in items]
    assert ("note", "1111111", " - Emailed DO 28/10") in whats and ("note", "1111111", " - Chased DO 30/10") in whats
    assert ("booking", "2222222", "") in whats and ("note", "3333333", " - Escalated DO 30/10") in whats
    assert [i["added"] for i in items] == sorted(i["added"] for i in items)          # oldest first
    chased = next(i for i in items if i.get("note") == " - Chased DO 30/10")
    assert T.done(chased["id"], store, tracker, notes_done)                             # a tracker note
    esc = next(i for i in items if i["orders"] == ["3333333"])
    assert T.done(esc["id"], store, tracker, notes_done)                                # a remembered note
    left = [(i["orders"][0], i.get("note") or "") for i in T.listing(tracker, store, notes_done)]
    assert ("1111111", " - Chased DO 30/10") not in left and ("3333333", " - Escalated DO 30/10") not in left
    assert ("1111111", " - Emailed DO 28/10") in left and ("2222222", "") in left
    assert T.done("t00000000", store, tracker, notes_done) is None


def test_a_note_the_run_wrote_by_itself_drops_off_the_list():
    store, tracker, notes_done = _paths()
    T.escalated(["4444444"], when="2026-10-30 19:40", path=store)
    import ctms_notes
    ctms_notes.mark_done("4444444-1-1", " - Escalated DO 30/10", notes_done)
    assert T.listing(tracker, store, notes_done) == []


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
