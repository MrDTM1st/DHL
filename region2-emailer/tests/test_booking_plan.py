"""The booking plan (booking_plan) and the CTMS run log (ctms_runlog). His loading rules: fill each vehicle to its
maximum before the next, keep different materials on their own lines, materials mix to fill a vehicle but two types
of rail never share one, a HIAB changes the maximum. Made-up orders only.

    python tests/test_booking_plan.py
"""
import os
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import booking_plan as B  # noqa: E402
import ctms_runlog as L  # noqa: E402


def line(ref, qty, kg, material="Example sleeper", collect="Example Yard", deliver="20/11/2026 08:00"):
    return {"ref": ref, "material": material, "qty": qty, "kg_each": kg, "collect": collect, "deliver": deliver}


def test_each_vehicle_is_filled_before_the_next():
    loads = B.load_plan([line("9000001-1-1", 77, 300), line("9000001-2-1", 800, 312)], limit_kg=26000)
    first = loads[0]
    assert [(ln["ref"], q) for ln, q in first] == [("9000001-1-1", 77), ("9000001-2-1", 9)]
    for v in loads[:-1]:                        # nothing more of the next line would have fitted
        kg = sum(q * ln["kg_each"] for ln, q in v)
        assert kg <= 26000 and kg + 312 > 26000, kg
    assert sum(q for v in loads for _, q in v) == 877                    # every sleeper on a vehicle


def test_a_count_limit_fills_by_count():
    loads = B.load_plan([line("9000001-1-1", 77, 300), line("9000001-2-1", 100, 312)], limit_units=84)
    assert [sum(q for _, q in v) for v in loads] == [84, 84, 9]


def test_different_materials_keep_their_own_lines():
    loads = B.load_plan([line("9000001-1-1", 50, 270, "Type A"), line("9000001-2-1", 50, 280, "Type B")],
                        limit_kg=40000)
    assert len(loads) == 1 and [(ln["material"], q) for ln, q in loads[0]] == [("Type A", 50), ("Type B", 50)]


def test_two_types_of_rail_never_share_a_vehicle():
    loads = B.load_plan([line("9000001-1-1", 30, 650, "RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED"),
                         line("9000001-2-1", 30, 700, "RAIL SHORT, 60E2, 18.288M"),
                         line("9000001-3-1", 40, 300, "Concrete sleeper")], limit_kg=25500)
    # each type on its own vehicle, the sleepers filling up both before one more takes the rest
    assert [[(ln["ref"], q) for ln, q in v] for v in loads] == [
        [("9000001-1-1", 30), ("9000001-3-1", 20)], [("9000001-2-1", 30), ("9000001-3-1", 15)],
        [("9000001-3-1", 5)]]
    same = B.load_plan([line("9000001-1-1", 10, 650, "56E1 rail 18.288M"), line("9000001-2-1", 10, 600, "56E1 rail")],
                       limit_kg=25500)
    assert len(same) == 1                                           # one type shares a vehicle like anything else


def test_what_is_a_rail_and_its_type():
    assert B.rail_type({"material": "RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED"}) == "56E1"
    assert B.rail_type({"material": "RAIL LONG, 60 E2, 36M"}) == "60E2"
    assert B.rail_type({"material": "Rail", "product": "SHORT_RAIL", "rail": "60e1"}) == "60E1"
    for not_a_rail in ("EG47 GR2 guard rail + pad", "SLEEPER COMPOSITE, BASEPLATE FOR INCLINED CEN56 RAIL",
                       "GUARD RAIL SLEEPER", "Rail pads", "G44 CEN60 + pad"):
        assert B.rail_type({"material": not_a_rail}) == "", not_a_rail
    p = B.plan({"job": "Example", "vehicle": {"kind": "artic", "hiab": True},
                "book": {"carrier": "EXAMPLE_DH", "amount": 500},
                "lines": [line("9000001-1-1", 10, 650, "56E1 rail"), line("9000001-2-1", 10, 650, "Rail",)]},
               now=datetime(2026, 11, 1, 9, 0))
    assert len(p["vehicles"]) == 2                                  # an unknown type shares with no other rail
    assert p["questions"] == ["What rail type is 9000001-2-1? Two types never share a vehicle, so it has one of "
                              "its own till I know."]


def test_a_vehicle_carries_one_pick_up_to_one_drop_on_one_day():
    p = B.plan({"job": "Example", "vehicle": {"kind": "artic", "max_kg": 26000},
                "book": {"carrier": "EXAMPLE_DH", "amount": 500},
                "lines": [line("9000001-1-1", 10, 300), line("9000001-2-1", 10, 300, collect="Other Yard"),
                          line("9000001-3-1", 10, 300, deliver="21/11/2026 08:00")]},
               now=datetime(2026, 11, 1, 9, 0))
    assert len(p["vehicles"]) == 3 and not p["questions"]
    assert {v["delivery_type"] for v in p["vehicles"]} == {"STANDARD"}


def test_a_hiab_changes_the_maximum_and_an_unknown_one_is_asked():
    assert (B.max_kg("artic", "hiab"), B.max_kg("artic", "")) == (20280, 25500)
    heavy = B.plan({"job": "Example", "vehicle": {"kind": "artic", "hiab": False, "max_units": 84},
                    "lines": [line("9000001-1-1", 100, 312)]})
    assert [v["units"] for v in heavy["vehicles"]] == [81, 19]      # 84 would be 26,208 kg - the weight caps it
    p = B.plan({"job": "Example", "vehicle": {"kind": "rigid", "hiab": False, "max_units": 84},
                "lines": [line("9000001-1-1", 100, 300)]})
    assert p["questions"][0] == "What's the most a rigid without a HIAB carries?"
    assert [v["units"] for v in p["vehicles"]] == [84, 16]          # still planned by the count meanwhile
    assert any("haulier" in q for q in p["questions"]) and any("amount" in q for q in p["questions"])


CONTACT_LIST = {"hauliers": [
    {"name": "Example Hiab Haulage", "ctms": "EX_HIAB", "caps": ["Artic Hiab"], "tier": "tier1"},
    {"name": "Example Moffett Haulage", "ctms": "EX_MOFF", "caps": ["Artic Flat", "Moffett"], "tier": "tier2"},
    {"name": "Example Fleet Moffett", "ctms": "EX_FLEET", "caps": ["Moffett"], "tier": "tier1"},
    {"name": "Example Red Haulage", "ctms": "EX_RED", "caps": ["Moffett"], "tier": "do_not_use", "do_not_use": True}]}


def test_a_moffett_job_goes_only_to_a_haulier_with_a_moffett():
    job = {"job": "Example", "vehicle": {"kind": "artic", "moffett": True, "max_units": 84},
           "book": {"amount": 500}, "lines": [line("9000001-1-1", 100, 300)]}
    p = B.plan(job, directory=CONTACT_LIST)
    assert p["questions"] == ["What's the most an artic with a Moffett carries?",       # never guessed
                              "Which haulier - it needs a Moffett: Example Fleet Moffett, Example Moffett Haulage?"]
    assert [v["units"] for v in p["vehicles"]] == [84, 16]
    job["book"]["carrier"] = "EX_HIAB_DH"
    assert p["questions"][0] in B.plan(job, directory=CONTACT_LIST)["questions"]
    assert B.plan(job, directory=CONTACT_LIST)["questions"][1].startswith("EX_HIAB_DH has no Moffett")
    job["book"]["carrier"] = "EXMOFF_DH"                    # the _DH code CTMS books, spelt its own way
    assert B.plan(job, directory=CONTACT_LIST)["questions"] == ["What's the most an artic with a Moffett carries?"]


def test_the_delivery_type_follows_booking_to_delivery():
    now = datetime(2026, 11, 1, 9, 0)
    assert B.delivery_type(now, datetime(2026, 11, 2, 8, 0)) == "EMERGENCY"
    assert B.delivery_type(now, datetime(2026, 11, 3, 9, 0)) == "NEXT DAY"
    assert B.delivery_type(now, datetime(2026, 11, 5, 9, 0)) == "STANDARD"


def test_a_load_too_heavy_for_any_vehicle_is_refused():
    try:
        B.load_plan([line("9000001-1-1", 1, 30000)], limit_kg=26000)
        assert False
    except ValueError as e:
        assert "more than a vehicle carries" in str(e)


def test_the_run_log_keeps_the_clean_streak_and_where_runs_stopped():
    path = os.path.join(tempfile.mkdtemp(), "runs.jsonl")
    L.record("order-update", ["9000001-1-1"], True, "Ran 54 step(s)", path=path)
    L.record("order-update", ["9000002-1-1"], False,
             "Stopped at step 5 of 6 (click): CTMS did not answer within 10s", path=path)
    L.record("order-update", ["9000003-1-1"], True, "Ran 54 step(s)", path=path)
    L.record("order-update", ["9000004-1-1"], True, "Ran 54 step(s)", path=path)
    s = L.summary(path)["order-update"]
    assert (s["runs"], s["clean"], s["streak"]) == (4, 3, 2)
    assert s["stopped"] == {"5/6 click": 1} and s["last_stop"]["refs"] == ["9000002-1-1"]


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
