"""Updated over the phone: the call's answers are checked, land on the order the way a reply does (each certain, over
an earlier email's), move its date, and put its update on the CTMS to-do in place of any older one. Made-up orders,
names and Ofcom drama-range numbers only.

    python tests/test_phone_update.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_todo  # noqa: E402
import phone_update as P  # noqa: E402
import tracker  # noqa: E402

FORM = {"date": "13/11/2026", "from": "08:00", "to": "", "offloading": "HIAB", "artic_access": "yes",
        "rear_steer": "no", "pts": "", "vehicle": "", "contact_name": "Sam Example", "contact_phone": "07700 900123",
        "what3words": "one.two.three", "notes": "ring 30 mins before"}


def test_the_answers_become_certain_details_and_pts_is_only_asked_on_rails():
    got, problems = P.details_from(FORM, rails=False)
    assert problems == [] and "pts" not in got
    assert got["date"] == {"value": "13/11/2026", "confidence": "high", "raw": P.RAW, "flexible": False,
                           "options": ["13/11/2026"]}
    assert got["time"]["earliest"] == "08:00" and got["time"]["latest"] is None      # the run adds his +2h
    assert got["contact"]["phone"] == "07700900123" and got["what3words"]["value"] == "///one.two.three"
    assert got["vehicle"]["value"] is None                                           # go by the weight
    _, problems = P.details_from(FORM, rails=True)
    assert problems == ["pts"]                                                       # a rail order must say
    got, _ = P.details_from(dict(FORM, pts="yes", vehicle="artic", to="22:00"), rails=True)
    assert got["pts"]["value"] == "yes" and got["vehicle"]["value"] == "artic" and got["time"]["latest"] == "22:00"


def test_what_the_run_would_ask_is_settled_on_the_form():
    import ctms_run_plan as plan
    rec = {"collections": [{"site": "Yard"}]}
    assert P.run_answers(FORM, rec, "08:00") == ({}, [])                              # a morning delivery: the day before
    assert P.run_answers(FORM, rec, "14:00") == ({}, ["collect"])                     # an afternoon one has no rule
    assert P.run_answers(FORM, {"collections": []}, "14:00") == ({}, [])              # no single pick-up: by hand as ever
    got, _ = P.run_answers(dict(FORM, collect="the same day", already=plan.TYPE_ANYWAY, vehicle="artic"), rec, "14:00")
    assert got == {"collect": "the same day", "already": plan.TYPE_ANYWAY, "veh": "artic"}
    assert P.run_answers(dict(FORM, collect="whenever"), rec, "08:00")[1] == ["collect"]


def test_the_forms_answers_are_kept_on_the_to_do_item():
    folder = tempfile.mkdtemp()
    try:
        rec = {"orders": ["9100001"], "details": {}, "site": "Yard", "to": "sam@example.net"}
        it = ctms_todo.phoned(rec, path=os.path.join(folder, "todo.json"), when="2026-11-03 10:00",
                              answers={"collect": "the same day", "veh": "artic"})
        assert it["answers"] == {"collect": "the same day", "veh": "artic"}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_anything_not_picked_or_not_right_is_named_and_nothing_saved():
    _, problems = P.details_from(dict(FORM, date="31/11/2026", offloading="CRANE", contact_phone="123",
                                      what3words="not w3w"), rails=False)
    assert problems == ["date", "offloading", "contact_phone", "what3words"], problems
    _, problems = P.details_from(dict(FORM, **{"from": "23:00", "to": "02:00"}), rails=False)
    assert problems == []                                                            # a night job: past midnight
    _, problems = P.details_from(dict(FORM, **{"from": "08:00", "to": "08:00"}), rails=False)
    assert problems == ["to"]


def test_saving_lands_on_the_order_moves_its_date_and_replaces_the_open_ctms_update():
    tmp = tempfile.mkdtemp(prefix="phone-test-")
    keep = tracker.PATH, ctms_todo.STORE
    tracker.PATH, ctms_todo.STORE = os.path.join(tmp, "tracker.json"), os.path.join(tmp, "todo.json")
    try:
        rec = {"id": "9100090|10/11/2026", "orders": ["9100090"], "kind": "delivery", "status": "sent",
               "delivery_date": "10/11/2026", "materials": "60x ballast", "name": "Sam",
               "reply_at": "2026-11-01 09:00",
               "details": {"vehicle": {"value": "NR_ARTIC_FL", "confidence": "high"},
                           "notes": {"value": "gate code 1234", "confidence": "high"}}}
        tracker.save({"records": [rec]})
        old = ctms_todo.replied(rec)                                     # the email's update, still open
        out = P.apply("9100090|10/11/2026", FORM, now="2026-11-02 10:15")
        assert out["ok"] and "moved to 13/11/2026" in out["said"], out
        r = tracker.load()["records"][0]
        assert r["id"] == "9100090|13/11/2026" and r["delivery_date"] == "13/11/2026" and r["date_was"] == "10/11/2026"
        assert r["phoned_at"] == "2026-11-02 10:15" and r["reply_at"] == "2026-11-01 09:00" and r["sendoff_ready"]
        assert r["details"]["offloading"]["value"] == "HIAB" and r["details"]["vehicle"]["value"] is None
        assert r["details"]["notes"]["value"] == "ring 30 mins before"
        assert r["missing"] == []
        items = ctms_todo.load()["items"]
        was = next(i for i in items if i["id"] == old["id"])
        assert was["done_at"] and was["superseded"] == "phone"
        new = [i for i in items if not i.get("done_at")]
        assert [i["what"] for i in new] == ["Updated over the phone 02/11 - update the order from it"], new
        assert new[0]["source"] == "phone" and new[0]["details"]["details"]["contact"]["name"] == "Sam Example"
        assert P.apply("9199999|01/01/2026", FORM)["ok"] is False                # not on the tracker
        out = P.apply("9100090|13/11/2026", dict(FORM, artic_access=""))
        assert not out["ok"] and "artic access" in out["said"]
    finally:
        tracker.PATH, ctms_todo.STORE = keep
        shutil.rmtree(tmp, ignore_errors=True)


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
