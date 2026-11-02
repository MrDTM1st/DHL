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
    assert p["set"]["services"] == {"HIAB": True, "MOFFETT": False, "REAR STEER": False, "PTS": False}
    assert p["set"]["comments"] == "05/11/26 08:00-12:00 - Sam Example 07700900123 - HIAB required - W3W ///one.two.three"
    assert any(e.startswith("Rear steer left off") for e in p["explain"])


def test_a_reply_ctms_already_has_is_held_for_him_never_typed_over():
    # the look-up saw a Veh Type on the order: the reply went in already (by hand) - held with his two choices (02/11)
    rec = _rec("9100079", "05/11/2026")
    found = _found("9100079", "05/11/2026")
    found["9100079|05/11/2026"]["veh"] = {"9100079-1-1": True}
    p = P.plan([_item("9100079")], [rec], found)[0]
    assert p["status"] == "held" and not p["set"].get("anyway")
    c = [c for c in p["checks"] if c["field"] == "already"][0]
    assert c["options"] == [P.TICK_OFF, P.TYPE_ANYWAY] and "9100079-1-1" in c["why"] and c["quote"] == ""
    # his pick settles it: ticked off with nothing typed, or typed in over what CTMS has
    p = P.plan([_item("9100079", answers={"already": P.TICK_OFF})], [rec], found)[0]
    assert p["status"] == "done" and p["set"] == {} and "ticked it off" in p["explain"][0]
    p = P.plan([_item("9100079", answers={"already": P.TYPE_ANYWAY})], [rec], found)[0]
    assert p["status"] == "ready" and p["set"]["anyway"] is True and p["set"]["deliver"] == "05/11/26 08:00-12:00"
    # no Veh Type seen: nothing to ask
    p = P.plan([_item("9100079")], [rec], _found("9100079", "05/11/2026"))[0]
    assert p["status"] == "ready" and not any(c["field"] == "already" for c in p["checks"])


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
    # a single time the parser read as "08:00 to 08:00" is that one time - never a window into the next day (02/11)
    rec = _rec("9100073", "13/11/2026", time={"earliest": "08:00", "latest": "08:00", "confidence": "high",
                                              "expanded": False})
    p = P.plan([_item("9100073")], [rec], _found("9100073", "13/11/2026"))[0]
    assert p["set"]["deliver"] == "13/11/26 08:00-10:00" and p["set"]["comments"].startswith("13/11/26 08:00 - ")


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


def test_pts_is_only_ever_for_rails():
    for mats in ("10x 1t bags of ballast", "60x sleepers"):
        rec = dict(_rec("9100081", "05/11/2026", pts={"value": "yes", "confidence": "high"}), materials=mats)
        p = P.plan([_item("9100081")], [rec], _found("9100081", "05/11/2026"))[0]
        assert p["set"]["services"]["PTS"] is False and "PTS left off: PTS is only for rails (your rule)" in p["explain"]
        rec = dict(_rec("9100081", "05/11/2026", pts={"value": None}), materials=mats)   # not asked: nothing to doubt
        assert not any(c["field"] == "pts" for c in P.plan([_item("9100081")], [rec],
                                                            _found("9100081", "05/11/2026"))[0]["checks"])
    rec = dict(_rec("9100084", "05/11/2026", pts={"value": "yes", "confidence": "high"}), materials="2x rails")
    assert P.plan([_item("9100084")], [rec], _found("9100084", "05/11/2026"))[0]["set"]["services"]["PTS"] is True
    rec = dict(_rec("9100084", "05/11/2026", pts={"value": None, "raw": ""}), materials="2x rails")
    assert any(c["field"] == "pts" for c in P.plan([_item("9100084")], [rec], _found("9100084", "05/11/2026"))[0]["checks"])


def test_bagged_ballast_weighs_a_tonne_a_bag_whatever_ctms_says():
    rec = dict(_rec("9100085", "05/11/2026"), materials="60x ballast", product_codes=["0057/100500/002"],
               ctms_weight=None)
    p = P.plan([_item("9100085")], [rec], _found("9100085", "05/11/2026"))[0]
    assert p["set"]["veh"] == "artic" and p["set"]["services"]["REAR STEER"] is True, p
    assert "60 bags of ballast at 1 t each - 60,000 kg - an artic HIAB (over 10,000 kg)" in p["explain"]
    rec = dict(rec, materials="8x ballast", ctms_weight=30000)
    assert P.plan([_item("9100085")], [rec], _found("9100085", "05/11/2026"))[0]["set"]["veh"] == "rigid"
    assert P.ballast_bags({"materials": "9x ballast, 7x aggregate"}) == 0         # an aggregate bag isn't known
    assert P.ballast_bags({"materials": "100x loose ballast"}) == 0
    assert P.ballast_bags({"materials": "80x ballast", "product_codes": ["0057/100500/001"]}) == 0   # loose stock
    assert P.ballast_bags({"materials": "10x 1t bags of ballast"}) == 10


def test_without_a_weight_the_vehicle_is_asked_not_assumed():
    rec = dict(_rec("9100082", "05/11/2026"), ctms_weight=None)
    p = P.plan([_item("9100082")], [rec], _found("9100082", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "veh")
    assert p["status"] == "held" and c["options"] == ["rigid", "artic"] and "Weight not read" in c["why"]


def test_a_moffett_job_goes_in_services_on_a_40ft_artic():
    rec = _rec("9100083", "05/11/2026", offloading={"value": "MOFFETT", "confidence": "high", "raw": "yes moffett"},
               rear_steer={"value": "no", "confidence": "high"})
    item = _item("9100083")
    p = P.plan([item], [rec], _found("9100083", "05/11/2026"))[0]
    assert p["status"] == "ready", p["checks"]
    assert p["set"]["services"] == {"HIAB": False, "MOFFETT": True, "REAR STEER": False, "PTS": False}
    assert p["set"]["veh"] == "artic" and any("40ft artic" in e for e in p["explain"])   # not the 5.1t's rigid
    assert "Moffett required" in p["set"]["comments"] and "HIAB required" not in p["set"]["comments"]
    # a site that takes no artics: his pick, the site's own words beside it
    rec = _rec("9100083", "05/11/2026", offloading={"value": "MOFFETT", "confidence": "high", "raw": "yes moffett"},
               artic_access={"value": "no", "confidence": "high", "raw": "no artics, tight access"})
    p = P.plan([item], [rec], _found("9100083", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "veh")
    assert p["status"] == "held" and c["options"] == ["rigid", "artic"] and c["quote"] == "no artics, tight access"
    p = P.plan([dict(item, answers={"veh": "rigid"})], [rec], _found("9100083", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "rigid" and p["set"]["services"]["MOFFETT"] is True


def test_no_site_contact_in_the_reply_means_the_sender_on_the_sheets_name_and_number():
    nobody = {"name": "", "phone": "", "confidence": "amber", "raw": ""}
    rec = dict(_rec("9100084", "05/11/2026", contact=nobody), site_contact="Sam Sheet", site_phone="07700 900555")
    p = P.plan([_item("9100084")], [rec], _found("9100084", "05/11/2026"))[0]
    assert p["status"] == "ready", p["checks"]
    assert "Sam Sheet 07700900555" in p["set"]["comments"]
    assert any("order's contact" in e for e in p["explain"])
    # the sender named (no one else was) but no number: the sheet's number when it is the same person...
    sender = {"name": "Gallimore, Sam", "phone": "", "confidence": "amber", "source": "sender", "raw": ""}
    rec = dict(_rec("9100085", "05/11/2026", contact=sender), site_contact="Sam Gallimore", site_phone="07700 900556")
    p = P.plan([_item("9100085")], [rec], _found("9100085", "05/11/2026"))[0]
    assert p["status"] == "ready" and "07700900556" in p["set"]["comments"], p
    # ...never someone else's number: a colleague who answered is asked for, not given the requester's number
    colleague = dict(sender, name="Jo Colleague")
    rec = dict(_rec("9100086", "05/11/2026", contact=colleague), site_contact="Sam Gallimore", site_phone="07700 900556")
    p = P.plan([_item("9100086")], [rec], _found("9100086", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "contact")
    assert p["status"] == "held" and "No number for Jo Colleague" in c["why"] and c["text"]


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
