"""What the CTMS to-do run would type, by his rules - and every doubt held with the site's own words and the choices
for a drop-down, never guessed. Made-up orders only.

    python tests/test_ctms_run_plan.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_run_plan as P  # noqa: E402


def _rec(order, date, **details):
    base = {"date": {"value": date, "confidence": "high", "options": [date]},
            "time": {"earliest": "08:00", "latest": "12:00", "confidence": "high"},
            "offloading": {"value": "HIAB", "confidence": "high", "raw": "yes"},
            "artic_access": {"value": "yes", "confidence": "high"},
            "rear_steer": {"value": "yes", "confidence": "high", "raw": "yes"},
            "pts": {"value": "no", "confidence": "high"},
            "contact": {"name": "sam example", "phone": "07700 900123", "confidence": "high"},
            "what3words": {"value": "///one.two.three"}}
    base.update(details)
    return {"id": f"{order}|{date}", "orders": [order], "kind": "delivery", "delivery_date": date,
            "materials": "60x sleepers", "ctms_weight": 5100,
            "collections": [{"site": "Example Supplier", "pc": "TS2 1AA", "from": "08:00", "to": "15:45"}],
            "details": base}


def _found(order, date, status="UNSCHEDULED"):
    dd = date[:6] + date[8:]
    return {f"{order}|{date}": {"lines": [{"ref": f"{order}-1-1", "status": status, "deliver_by": f"{dd} 16:01"}]}}


def _item(order, kind="update", **extra):
    return dict({"id": f"t{order}", "kind": kind, "orders": [order], "what": "Sam replied - update the order"}, **extra)


def test_a_note_is_always_ready():
    p = P.plan([{"id": "n1", "kind": "note", "orders": ["9100070"], "ref": "9100070-1-1", "note": " - Emailed DO 28/10",
                 "what": "Add 'Emailed DO 28/10'"}], [], {})
    assert p[0]["status"] == "ready" and p[0]["set"] == {"note": " - Emailed DO 28/10"} and p[0]["lines"] == ["9100070-1-1"]


def test_a_clear_reply_is_ready_with_his_rules_applied():
    rec = _rec("9100071", "05/11/2026")                                 # a Thursday, 08:00-12:00, 5.1 t, HIAB
    p = P.plan([_item("9100071")], [rec], _found("9100071", "05/11/2026"))[0]
    assert p["status"] == "ready", p["checks"]
    assert p["lines"] == ["9100071-1-1"]
    assert p["set"]["deliver"] == "05/11/26 08:00-12:00"
    assert p["set"]["collect"] == "04/11/26 08:00-15:45"                # the day before, in the yard's hours
    assert p["set"]["veh"] == "rigid"                                   # 5,100 kg on a HIAB
    assert p["set"]["services"] == {"HIAB": True, "REAR STEER": False, "PTS": False}
    assert p["set"]["comments"] == "05/11/26 08:00-12:00 - Sam Example 07700900123 - HIAB required - W3W ///one.two.three"
    assert any(e.startswith("Rear steer left off") for e in p["explain"])


def test_a_heavy_hiab_load_is_an_artic_and_keeps_its_rear_steer():
    rec = dict(_rec("9100072", "05/11/2026"), ctms_weight=15000)
    p = P.plan([_item("9100072")], [rec], _found("9100072", "05/11/2026"))[0]
    assert p["set"]["veh"] == "artic" and p["set"]["services"]["REAR STEER"] is True
    assert "Rear steer required" in p["set"]["comments"]


def test_a_single_time_gets_two_hours_and_the_comment_keeps_their_time():
    rec = _rec("9100073", "05/11/2026", time={"earliest": "09:00", "latest": "11:00", "confidence": "high",
                                              "expanded": True})
    p = P.plan([_item("9100073")], [rec], _found("9100073", "05/11/2026"))[0]
    assert p["set"]["deliver"] == "05/11/26 09:00-11:00" and p["set"]["comments"].startswith("05/11/26 09:00 - ")
    rec = _rec("9100073", "05/11/2026", time={"earliest": "09:00", "confidence": "high"})
    p = P.plan([_item("9100073")], [rec], _found("9100073", "05/11/2026"))[0]
    assert p["set"]["deliver"] == "05/11/26 09:00-11:00" and any("+2h" in e for e in p["explain"])


def test_a_monday_delivery_collects_on_friday_with_storage_x2():
    rec = _rec("9100074", "09/11/2026")                                 # a Monday
    p = P.plan([_item("9100074")], [rec], _found("9100074", "09/11/2026"))[0]
    assert p["set"]["collect"] == "06/11/26 08:00-15:45" and p["set"]["storage"] == 2, p


def test_an_uncertain_answer_is_held_with_their_words_and_choices_then_settled_by_his_pick():
    rec = _rec("9100075", "05/11/2026", offloading={"value": "MOFFETT", "confidence": "amber", "raw": "yes we need it"})
    item = _item("9100075")
    p = P.plan([item], [rec], _found("9100075", "05/11/2026"))[0]
    assert p["status"] == "held"
    c = next(c for c in p["checks"] if c["field"] == "offloading")
    assert c["quote"] == "yes we need it" and c["options"] == ["HIAB", "MOFFETT", "SITE/NONE"]
    assert "veh" not in p["set"] and "services" not in p["set"]         # nothing decided on a guess
    p = P.plan([dict(item, answers={"offloading": "HIAB"})], [rec], _found("9100075", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["services"]["HIAB"] is True


def test_an_afternoon_delivery_asks_which_day_to_collect():
    rec = _rec("9100076", "05/11/2026", time={"earliest": "13:00", "latest": "15:00", "confidence": "high"})
    item = _item("9100076")
    p = P.plan([item], [rec], _found("9100076", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "collect")
    assert p["status"] == "held" and c["options"] == ["the day before", "the same day"]
    p = P.plan([dict(item, answers={"collect": "the same day"})], [rec], _found("9100076", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["collect"] == "05/11/26 08:00-15:45"


def test_what_cannot_be_typed_safely_is_left_for_him():
    two = dict(_rec("9100077", "05/11/2026"), collections=[{"pc": "A"}, {"pc": "B"}])
    p = P.plan([_item("9100077")], [two], _found("9100077", "05/11/2026"))[0]
    assert p["status"] == "held" and any(c["field"] == "collect" and "2 pick-ups" in c["why"] for c in p["checks"])
    p = P.plan([_item("9100078")], [_rec("9100078", "05/11/2026")], {})[0]   # never looked up in CTMS
    assert p["status"] == "held" and any(c["field"] == "lines" for c in p["checks"])
    p = P.plan([_item("9100079")], [_rec("9100079", "05/11/2026")],
               _found("9100079", "05/11/2026", "SCHEDULED"))[0]
    assert p["status"] == "done"                                        # CTMS has nothing left to update
    p = P.plan([_item("9100080", kind="booking", what="Book with Example at 500")], [], {})[0]
    assert p["status"] == "yours"


def test_ballast_never_gets_pts():
    rec = dict(_rec("9100081", "05/11/2026", pts={"value": "yes", "confidence": "high"}), materials="10x 1t bags of ballast")
    p = P.plan([_item("9100081")], [rec], _found("9100081", "05/11/2026"))[0]
    assert p["set"]["services"]["PTS"] is False and any("ballast" in e for e in p["explain"])


def test_without_a_weight_the_vehicle_is_asked_not_assumed():
    rec = dict(_rec("9100082", "05/11/2026"), ctms_weight=None)
    p = P.plan([_item("9100082")], [rec], _found("9100082", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "veh")
    assert p["status"] == "held" and c["options"] == ["rigid", "artic"] and "Weight not read" in c["why"]


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
