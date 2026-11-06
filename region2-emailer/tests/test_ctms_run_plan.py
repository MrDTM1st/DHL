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


RAIL_60FT = "RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED"


def _item(order, kind="update", **extra):
    return dict({"id": f"t{order}", "kind": kind, "orders": [order], "what": "Sam replied - update the order"}, **extra)


def _two_days(**answers):
    rec = _rec("9100090", "18/11/2026")
    rec["details"]["date"] = {"value": "19/11/2026", "flexible": True, "confidence": "high", "raw": "X70 18/11/26 X70 19/11/26",
                              "options": ["18/11/2026", "19/11/2026"]}
    rec["materials"], rec["product_codes"] = "140x rails", [RAIL_60FT]
    return P.plan([_item("9100090", answers=answers)], [rec], _found("9100090", "18/11/2026"))[0]


def test_a_reply_naming_two_days_can_be_picked_as_both():
    p = _two_days()
    c = next(c for c in p["checks"] if c["field"] == "date")
    assert c["options"] == ["18/11/2026", "19/11/2026", "18/11/2026 and 19/11/2026"], c


def test_one_line_staged_over_two_days_runs_from_the_first_to_the_last():
    p = _two_days(date="18/11/2026 and 19/11/2026")                     # Wed and Thu, his 6055858 way
    assert p["status"] == "ready", p["checks"]
    assert p["set"]["deliver"] == "18/11/26 08:00-19/11/26 12:00"
    assert p["set"]["collect"] == "17/11/26 08:00-18/11/26 15:45"       # each the day before, in the yard's hours
    assert p["set"]["comments"].startswith("18/11/26 and 19/11/26 08:00-12:00 - Sam Example 07700900123 - HIAB required")
    assert p["set"]["veh"] == "60ft"


def test_picking_one_of_the_two_days_is_still_one_day():
    p = _two_days(date="19/11/2026")
    assert p["set"]["deliver"] == "19/11/26 08:00-12:00" and p["set"]["collect"] == "18/11/26 08:00-15:45"
    assert p["set"]["comments"].startswith("19/11/26 08:00-12:00")


def test_the_last_loads_collection_keeps_off_the_weekend():
    rec = _rec("9100091", "06/11/2026")
    p = P.plan([_item("9100091", answers={"date": "06/11/2026 and 09/11/2026"})], [rec], _found("9100091", "06/11/2026"))[0]
    assert p["set"]["deliver"] == "06/11/26 08:00-09/11/26 12:00"       # a Friday and the Monday
    assert p["set"]["collect"] == "05/11/26 08:00-06/11/26 15:45"       # Thursday to Friday, not the Sunday


def test_the_sites_instruction_for_the_load_ends_the_comment():
    rec = _rec("9100092", "05/11/2026", comment_extra={"value": "X84 per lorry"})
    p = P.plan([_item("9100092")], [rec], _found("9100092", "05/11/2026"))[0]
    assert p["set"]["comments"].endswith(" - W3W ///one.two.three - X84 per lorry")


def test_a_question_the_email_never_answers_says_so():
    rec = _rec("9100093", "05/11/2026", rear_steer={"value": None, "confidence": "amber", "raw": ""},
               pts={"value": None, "confidence": "amber", "raw": "PTS maybe"})
    rec["materials"], rec["product_codes"] = "10x rails", [RAIL_60FT]
    why = {c["field"]: c["why"] for c in P.plan([_item("9100093")], [rec], _found("9100093", "05/11/2026"))[0]["checks"]}
    assert why == {"rear_steer": "Their email doesn't say", "pts": "Not certain"}, why


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
    p = P.plan([_item("9100079")], [_rec("9100079", "05/11/2026")],
               _found("9100079", "05/11/2026", "SCHEDULED"))[0]
    assert p["status"] == "done"                                        # CTMS has nothing left to update
    p = P.plan([_item("9100080", kind="booking", what="Book with Example at 500")], [], {})[0]
    assert p["status"] == "yours"


def _night(order, what="Add NIGHT + SATURDAY before it's booked (deliver Sat 07/11 23:00)", added="2026-11-03 12:25"):
    return _item(order, kind="other", source="services", what=what, added=added)


def test_night_and_saturday_are_the_runs_to_add_not_his():
    p = P.plan([_night("9100090")], [], _found("9100090", "07/11/2026"))[0]
    assert p["status"] == "ready" and p["lines"] == ["9100090-1-1"] and not p["lookup"]
    assert p["set"] == {"services": {"NIGHT": True, "SATURDAY": True}, "anyway": True}


def test_a_night_not_looked_up_yet_is_looked_up_for_its_delivery_day():
    p = P.plan([_night("9100090")], [], {})[0]
    assert p["status"] == "ready" and p["lookup"] == {"ref": "9100090", "date": "07/11/2026", "cards": False}
    p = P.plan([_night("9100090", "Add NIGHT before it's booked (deliver Sat 02/01 23:00)", "2026-12-20 12:25")], [], {})[0]
    assert p["lookup"]["date"] == "02/01/2027"


def test_a_night_with_no_open_line_stays_his():
    p = P.plan([_night("9100090")], [], _found("9100090", "07/11/2026", "SCHEDULED"))[0]
    assert p["status"] == "yours" and "booked already" in p["explain"][0]


def test_a_night_ctms_showed_nothing_for_is_looked_up_again_by_the_run_not_handed_to_him():
    # his 06/11: "they are not for me to do" - not imported then, or an NN number CTMS holds as the Booking Ref
    p = P.plan([_night("NN4230978-2256")], [], {"NN4230978-2256|07/11/2026": {"lines": []}})[0]
    assert p["status"] == "ready" and p["lookup"] == {"ref": "NN4230978-2256", "date": "07/11/2026", "cards": False}
    assert p["set"] == {"services": {"NIGHT": True, "SATURDAY": True}, "anyway": True}
    assert "looks again first" in p["explain"][0]


def test_a_night_waits_for_an_update_that_needs_an_answer():
    rec = _rec("9100091", "07/11/2026", contact={"confidence": "low"})
    rec.pop("site_contact", None)
    found = _found("9100091", "07/11/2026")
    update, night = P.plan([_item("9100091"), dict(_night("9100091"), id="n1")], [rec], found)
    assert update["status"] == "held" and night["status"] == "held" and "update" in night["checks"][0]["why"]


def test_no_yard_hours_on_the_record_doesnt_hold_the_update():
    rec = dict(_rec("9100095", "05/11/2026"), collections=[{"site": "Example Supplier", "date": "04/11/2026", "from": "", "to": ""}])
    p = P.plan([_item("9100095")], [rec], _found("9100095", "05/11/2026"))[0]
    assert p["status"] == "ready" and "collect" not in p["set"] and p["set"]["deliver"].startswith("05/11/26 08:00")
    assert any("yard hours" in x for x in p["explain"])


def test_pts_is_only_ever_for_rails():
    for mats in ("10x 1t bags of ballast", "60x sleepers"):
        rec = dict(_rec("9100081", "05/11/2026", pts={"value": "yes", "confidence": "high"}), materials=mats)
        p = P.plan([_item("9100081")], [rec], _found("9100081", "05/11/2026"))[0]
        assert p["set"]["services"]["PTS"] is False and "PTS left off: PTS is only for rails (your rule)" in p["explain"]
        rec = dict(_rec("9100081", "05/11/2026", pts={"value": None}), materials=mats)   # not asked: nothing to doubt
        assert not any(c["field"] == "pts" for c in P.plan([_item("9100081")], [rec],
                                                            _found("9100081", "05/11/2026"))[0]["checks"])
    rec = dict(_rec("9100084", "05/11/2026", pts={"value": "yes", "confidence": "high"}), materials="2x rails",
               product_codes=[RAIL_60FT])
    assert P.plan([_item("9100084")], [rec], _found("9100084", "05/11/2026"))[0]["set"]["services"]["PTS"] is True
    rec = dict(_rec("9100084", "05/11/2026", pts={"value": None, "raw": ""}), materials="2x rails",
               product_codes=[RAIL_60FT])
    assert any(c["field"] == "pts" for c in P.plan([_item("9100084")], [rec], _found("9100084", "05/11/2026"))[0]["checks"])
    # a sleeper's stock line can name the rail it is for, and is still a sleeper
    rec = dict(_rec("9100084", "05/11/2026", pts={"value": "yes", "confidence": "high"}), materials="60x GUARD RAIL SLEEPER")
    assert P.plan([_item("9100084")], [rec], _found("9100084", "05/11/2026"))[0]["set"]["services"]["PTS"] is False


def test_bagged_ballast_weighs_a_tonne_a_bag_whatever_ctms_says():
    rec = dict(_rec("9100085", "05/11/2026"), materials="60x ballast", product_codes=["0057/100500/002"],
               ctms_weight=None)
    p = P.plan([_item("9100085")], [rec], _found("9100085", "05/11/2026"))[0]
    assert p["set"]["veh"] == "artic" and p["set"]["services"]["REAR STEER"] is True, p
    assert "60 bags of ballast at 1 t each - 60,000 kg - an artic (over 10,000 kg)" in p["explain"]
    rec = dict(rec, materials="8x ballast", ctms_weight=30000)
    assert P.plan([_item("9100085")], [rec], _found("9100085", "05/11/2026"))[0]["set"]["veh"] == "rigid"
    assert P.ballast_bags({"materials": "9x ballast, 7x aggregate"}) == 0         # an aggregate bag isn't known
    assert P.ballast_bags({"materials": "100x loose ballast"}) == 0
    assert P.ballast_bags({"materials": "80x ballast", "product_codes": ["0057/100500/001"]}) == 0   # loose stock
    assert P.ballast_bags({"materials": "10x 1t bags of ballast"}) == 10


def test_the_vehicle_is_whatever_fits_the_weight_with_or_without_a_hiab():
    # his 02/11: "sleepers weigh 7 tons, you put it under a rigid" - and nobody is asked
    none = {"value": "SITE/NONE", "confidence": "high", "raw": "no"}
    for kg, veh in ((7000, "rigid"), (10000, "rigid"), (10001, "artic"), (40000, "artic")):
        rec = dict(_rec("9100082", "05/11/2026", offloading=none), ctms_weight=kg)
        p = P.plan([_item("9100082")], [rec], _found("9100082", "05/11/2026"))[0]
        assert p["status"] == "ready" and p["set"]["veh"] == veh and not p["lookup"], (kg, p)
    # the weight the last look-up read counts, whichever key it read it under
    found = _found("9100082", "05/11/2026")
    found["9100082|"] = {"lines": [], "veh": {"9100082-1-1": False}, "weight": {"9100082-1-1": 12500.0}}
    p = P.plan([_item("9100082")], [dict(_rec("9100082", "05/11/2026"), ctms_weight=None)], found)[0]
    assert p["set"]["veh"] == "artic" and any("12,500 kg in CTMS" in e for e in p["explain"])


def test_a_reply_covering_two_orders_does_both_orders_lines():
    # one reply for two orders: all of both, not the first's alone and the item ticked off (02/11)
    line = lambda ref, day: {"ref": ref, "status": "UNSCHEDULED", "deliver_by": f"{day}/11/26 16:00"}  # noqa: E731
    rec = dict(_rec("9100083", "05/11/2026"), orders=["9100083", "9100084"], ctms_weight=2000)
    it = dict(_item("9100083"), orders=["9100083", "9100084"])
    found = {"9100083|05/11/2026": {"lines": [line("9100083-1-1", "05"), line("9100083-2-1", "05")]},
             "9100084|05/11/2026": {"lines": [line("9100084-1-1", "13")]}}      # CTMS still has this one on another day
    p = P.plan([it], [rec], found)[0]
    assert p["lines"] == ["9100083-1-1", "9100083-2-1", "9100084-1-1"] and p["lookup"] is None
    # one of them not looked up yet: both read when Run's pressed
    p = P.plan([it], [rec], {"9100083|05/11/2026": found["9100083|05/11/2026"]})[0]
    assert p["lookup"] == {"ref": "9100083", "date": "05/11/2026", "cards": False, "also": ["9100084"]}
    # a Veh Type on the second counts too
    found["9100084|05/11/2026"]["veh"] = {"9100084-1-1": True}
    p = P.plan([it], [rec], found)[0]
    assert p["status"] == "held" and any("9100084-1-1" in c.get("why", "") for c in p["checks"])


def test_what_only_ctms_knows_is_read_when_run_is_pressed_never_asked():
    rec = dict(_rec("9100082", "05/11/2026"), ctms_weight=None)
    # never looked up: ready all the same, nothing to answer - the run looks it up first
    p = P.plan([_item("9100082")], [rec], {})[0]
    assert p["status"] == "ready" and p["checks"] == [] and p["lines"] == [] and "veh" not in p["set"], p
    assert p["lookup"] == {"ref": "9100082", "date": "05/11/2026", "cards": True}
    assert any(e.startswith("Read from CTMS when you press Run") for e in p["explain"])
    # its lines known, the card not opened: the weight is still to read
    p = P.plan([_item("9100082")], [rec], _found("9100082", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["lookup"] and any(e.endswith("which picks the vehicle") for e in p["explain"]), p
    # looked up, the card opened, and CTMS shows no weight: only now can nothing say
    found = _found("9100082", "05/11/2026")
    found["9100082|05/11/2026"]["veh"] = {"9100082-1-1": False}
    p = P.plan([_item("9100082")], [rec], found)[0]
    c = next(c for c in p["checks"] if c["field"] == "veh")
    assert p["status"] == "held" and c["options"] == ["rigid", "artic"] and "no weight" in c["why"] and not p["lookup"]
    # a plan with everything needs no look-up
    p = P.plan([_item("9100082")], [dict(rec, ctms_weight=5000)], _found("9100082", "05/11/2026"))[0]
    assert not p["lookup"]


def test_rails_go_by_their_length_not_their_weight():
    # one 60ft rail weighs a tonne: by its weight a rigid, which can't carry it
    rec = dict(_rec("9100090", "05/11/2026"), materials="1x rails", product_codes=[RAIL_60FT], ctms_weight=1030)
    p = P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "60ft", p
    assert p["set"]["services"]["REAR STEER"] is True and "Rear steer required" in p["set"]["comments"]
    assert any("18.288 m rails - a 60ft artic" in e for e in p["explain"])
    # the length decides it: no weight needed, no look-up for one
    rec = dict(rec, ctms_weight=None)
    assert P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]["set"]["veh"] == "60ft"
    # no longer than a normal trailer: a 40ft artic; no longer than a rigid: by the weight, as anything else
    rec = dict(rec, product_codes=["RAIL SHORT, 56E1, 13.5M"])
    assert P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]["set"]["veh"] == "artic"
    rec = dict(rec, product_codes=["RAIL SHORT, 56E1, 9.144M"], ctms_weight=2000)
    assert P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]["set"]["veh"] == "rigid"
    # over 18.3 m: the 80ft artic, with its escort
    rec = dict(rec, product_codes=["RAIL LONG, 56E1, 36.576M"])
    p = P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "80ft" and p["set"]["services"]["ESCORTS"] is True, p
    assert p["set"]["services"]["REAR STEER"] is True
    # 60ft rails need none, and an escort already on an order is never taken off
    rec = dict(rec, product_codes=[RAIL_60FT])
    assert "ESCORTS" not in P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]["set"]["services"]
    # rails nobody says the length of can't be worked out
    rec = dict(rec, product_codes=[], ctms_weight=2000)
    p = P.plan([_item("9100090")], [rec], _found("9100090", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "veh")
    assert p["status"] == "held" and c["options"] == ["rigid", "artic", "60ft", "80ft"], p


def test_a_site_ruling_out_the_only_thing_that_fits_is_the_one_question_with_their_words():
    # no artics, rear steer yes, 60ft rails: nothing else carries them - his to settle, never a silent guess
    rec = dict(_rec("9100091", "05/11/2026", artic_access={"value": "no", "confidence": "high", "raw": "no"}),
               materials="2x rails", product_codes=[RAIL_60FT])
    item = _item("9100091")
    p = P.plan([item], [rec], _found("9100091", "05/11/2026"))[0]
    assert p["status"] == "held" and [c["field"] for c in p["checks"]] == ["veh"], p["checks"]
    c = p["checks"][0]
    assert c["quote"] == "no" and c["options"] == ["60ft"] and "18.288 m rails only fit a 60ft artic" in c["why"]
    assert "rear steer" in c["why"]
    p = P.plan([dict(item, answers={"veh": "60ft"})], [rec], _found("9100091", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "60ft" and p["set"]["services"]["REAR STEER"] is True
    assert "Rear steer required" in p["set"]["comments"]


def test_no_artics_means_rigids_and_the_booking_splits_what_one_cant_take():
    rec = dict(_rec("9100092", "05/11/2026", artic_access={"value": "no", "confidence": "high", "raw": "no"}),
               ctms_weight=15000)
    p = P.plan([_item("9100092")], [rec], _found("9100092", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "rigid", p
    assert any("15,000 kg in CTMS is over one rigid's 10,000 kg" in e for e in p["explain"])
    assert p["set"]["services"]["REAR STEER"] is False
    # the site named one: theirs
    rec = dict(_rec("9100092", "05/11/2026", vehicle={"value": "rigid", "confidence": "high"}), ctms_weight=15000)
    assert P.plan([_item("9100092")], [rec], _found("9100092", "05/11/2026"))[0]["set"]["veh"] == "rigid"


def test_a_rigid_is_never_asked_about_rear_steer():
    rec = dict(_rec("9100093", "05/11/2026", rear_steer={"value": None, "confidence": "amber", "raw": "tbc"}),
               ctms_weight=5000)
    p = P.plan([_item("9100093")], [rec], _found("9100093", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["services"]["REAR STEER"] is False, p
    rec = dict(rec, ctms_weight=15000)                                  # an artic: still asked
    p = P.plan([_item("9100093")], [rec], _found("9100093", "05/11/2026"))[0]
    assert p["status"] == "held" and any(c["field"] == "rear_steer" for c in p["checks"])


def test_loose_ballast_goes_on_the_rigid_tipper():
    rec = dict(_rec("9100094", "05/11/2026"), materials="80x loose ballast")
    p = P.plan([_item("9100094")], [rec], _found("9100094", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "tipper" and not p["set"]["services"]["HIAB"]
    assert not [c for c in p["checks"] if c["field"] == "veh_tipper"]


def test_a_stoneblower_goes_on_the_rigid_tipper_and_is_asked_nothing_about_lifting():
    for stone in ({"materials": "20x stoneblower ballast"}, {"materials": "20x ballast", "product_codes": ["STONEBLOWER, 20T"]}):
        rec = dict(_rec("9100096", "05/11/2026", offloading={"value": None, "confidence": "amber", "raw": ""},
                        rear_steer={"value": None, "confidence": "amber", "raw": ""}), **stone)
        p = P.plan([_item("9100096")], [rec], _found("9100096", "05/11/2026"))[0]
        assert p["status"] == "ready" and p["set"]["veh"] == "tipper", p
        assert p["set"]["services"] == {"HIAB": False, "MOFFETT": False, "REAR STEER": False, "PTS": False}
        assert "HIAB" not in p["set"]["comments"]
    # a HIAB the site asked for still never goes on a tipper
    rec = dict(_rec("9100096", "05/11/2026"), materials="20x stoneblower ballast")
    p = P.plan([_item("9100096")], [rec], _found("9100096", "05/11/2026"))[0]
    assert p["set"]["services"]["HIAB"] is False and "HIAB" not in p["set"]["comments"], p


def test_the_alternative_contact_goes_in_the_comment_as_he_types_it():
    alt = {"name": "jo backup", "phone": "07700 900777", "confidence": "high"}
    rec = _rec("9100095", "05/11/2026", alt_contact=alt)
    p = P.plan([_item("9100095")], [rec], _found("9100095", "05/11/2026"))[0]
    assert " - Sam Example 07700900123 / Jo Backup 07700900777 - HIAB required" in p["set"]["comments"], p


def test_a_moffett_job_goes_in_services_on_a_40ft_artic():
    rec = _rec("9100083", "05/11/2026", offloading={"value": "MOFFETT", "confidence": "high", "raw": "yes moffett"},
               rear_steer={"value": "no", "confidence": "high"})
    item = _item("9100083")
    p = P.plan([item], [rec], _found("9100083", "05/11/2026"))[0]
    assert p["status"] == "ready", p["checks"]
    assert p["set"]["services"] == {"HIAB": False, "MOFFETT": True, "REAR STEER": False, "PTS": False}
    assert p["set"]["veh"] == "artic" and any("40ft artic" in e for e in p["explain"])   # not the 5.1t's rigid
    assert "Moffett required" in p["set"]["comments"] and "HIAB required" not in p["set"]["comments"]
    # "the Moffetts only go on artics, so you don't put it on a rigid" (his 02/11): a site that takes no artics is his to
    # settle, the site's own words beside it - and however light the load is
    rec = dict(_rec("9100083", "05/11/2026", offloading={"value": "MOFFETT", "confidence": "high", "raw": "yes moffett"},
                    artic_access={"value": "no", "confidence": "high", "raw": "no artics, tight access"}), ctms_weight=2000)
    p = P.plan([item], [rec], _found("9100083", "05/11/2026"))[0]
    c = next(c for c in p["checks"] if c["field"] == "veh")
    assert p["status"] == "held" and c["options"] == ["artic"] and c["quote"] == "no artics, tight access", p
    assert p["set"].get("veh") != "rigid"
    p = P.plan([dict(item, answers={"veh": "artic"})], [rec], _found("9100083", "05/11/2026"))[0]
    assert p["status"] == "ready" and p["set"]["veh"] == "artic" and p["set"]["services"]["MOFFETT"] is True
    # short rails with a Moffett: an artic too, never by the weight
    rec = dict(_rec("9100083", "05/11/2026", offloading={"value": "MOFFETT", "confidence": "high", "raw": "moffett"}),
               materials="1x rails", product_codes=["RAIL SHORT, 56E1, 9.144M"], ctms_weight=600)
    assert P.plan([item], [rec], _found("9100083", "05/11/2026"))[0]["set"]["veh"] == "artic"


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
