"""His 10 + 20 (27/11): bagged ballast going on several vehicles fills each before the next and puts what's left on a
rigid - 30 bags is 20 on an artic and 10 on a rigid, never 15 + 15 on two artics unless he says so - and Book sets
each part of the split to its load and books it on its own trailer. Made-up orders and sites.

    python -m pytest -q tests/test_ballast_loads.py
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ballast_loads as BL  # noqa: E402
import book_run as B  # noqa: E402
import ctms_book as CB  # noqa: E402

A, R = BL.ARTIC, BL.RIGID


# -- the rule
@pytest.mark.parametrize("bags, trailer, carrier, plan", [
    (30, A, "DHL_NOC", [(20, A), (10, R)]),          # his case: 20 + 10, never 15 + 15
    (45, A, "DHL_NOC", [(20, A), (20, A), (5, R)]),
    (35, A, "DHL_NOC", [(20, A), (15, A)]),          # 15 is more than a rigid takes
    (40, A, "DHL_NOC", [(20, A), (20, A)]),
    (30, R, "DHL_NOC", [(10, R), (10, R), (10, R)]),  # a rigid picked: three rigids of 10
    (25, R, "DHL_NOC", [(10, R), (10, R), (5, R)]),
    (30, A, "ABCHAULAGE_DH", [(20, A), (10, R)]),    # any haulier the same
    (15, A, "DHL_NOC", [(15, A)]),                   # one vehicle: nothing to share out
])
def test_each_vehicle_is_filled_before_the_next_and_whats_left_goes_on_a_rigid(bags, trailer, carrier, plan):
    assert BL.loads(bags, trailer, carrier) == plan
    assert sum(q for q, _ in plan) == bags


def test_no_bags_or_a_trailer_the_rule_doesnt_know_plans_nothing():
    assert BL.loads(0, A) is None
    assert BL.loads(30, "NR_60_ART_FL") is None
    assert BL.loads(30, "") is None


def test_the_loads_read_as_he_says_them():
    assert BL.said([(20, A), (10, R)]) == "20 bags on NR_ARTIC_FL and 10 on NR_FLAT_RIG"
    assert BL.said([(10, R)] * 3) == "10 bags on NR_FLAT_RIG, 10 on NR_FLAT_RIG and 10 on NR_FLAT_RIG"
    assert BL.as_job([(20, A)]) == [{"qty": 20, "trailer": A}]


def test_loads_given_must_add_up_to_the_order_and_be_whole_loads_on_a_trailer():
    assert BL.check([{"qty": 10, "trailer": R}] * 3, 30) == [(10, R)] * 3
    with pytest.raises(ValueError, match="add up to 35, not the order's 30"):
        BL.check([{"qty": 20, "trailer": A}, {"qty": 15, "trailer": A}], 30)     # never more in the well than ordered
    with pytest.raises(ValueError, match="whole quantity"):
        BL.check([{"qty": 15.5, "trailer": A}, {"qty": 14.5, "trailer": A}], 30)
    with pytest.raises(ValueError, match="whole quantity"):
        BL.check([{"qty": 30, "trailer": ""}, {"qty": 0, "trailer": R}])
    with pytest.raises(ValueError, match="two vehicles or more"):
        BL.check([{"qty": 30, "trailer": A}], 30)


# -- book_run: the plan worked out before CTMS is touched
BAGS30 = {"orders": ["9100001"], "materials": "30x ballast", "product_codes": ["0057/100500/002"]}


def test_thirty_bags_on_two_artics_go_twenty_and_ten_on_a_rigid():
    job = {"vehicles": 2, "trailer": A, "carrier": "DHL_NOC"}
    said = B.plan_loads(job, BAGS30)
    assert job["loads"] == [{"qty": 20, "trailer": A}, {"qty": 10, "trailer": R}]
    assert "20 bags on NR_ARTIC_FL and 10 on NR_FLAT_RIG" in said


def test_a_rigid_picked_makes_rigids_of_ten():
    job = {"vehicles": 3, "trailer": R, "carrier": "DHL_NOC"}
    B.plan_loads(job, BAGS30)
    assert job["loads"] == [{"qty": 10, "trailer": R}] * 3


def test_his_split_equally_one_vehicle_loose_ballast_and_sleepers_are_left_alone():
    for job, rec in (({"vehicles": 2, "trailer": A, "equal": True}, BAGS30),
                     ({"vehicles": 1, "trailer": A}, BAGS30),
                     ({"vehicles": 2, "trailer": A}, {"materials": "30x ballast", "loose_ballast": True}),
                     ({"vehicles": 2, "trailer": A}, {"materials": "30x ballast", "product_codes": ["0057/100500/001"]}),
                     ({"vehicles": 2, "trailer": A}, {"materials": "120x sleepers"})):
        assert B.plan_loads(job, rec) == "" and "loads" not in job


def test_vehicles_that_dont_fit_the_rule_stop_rather_than_guess():
    with pytest.raises(ValueError, match="fill 2 vehicle"):
        B.plan_loads({"vehicles": 3, "trailer": A, "carrier": "DHL_NOC"}, BAGS30)
    with pytest.raises(ValueError, match="fill 3 vehicle"):
        B.plan_loads({"vehicles": 2, "trailer": R, "carrier": "DHL_NOC"}, BAGS30)


def test_the_forms_own_loads_are_checked_against_the_orders_bags():
    job = {"vehicles": 3, "trailer": R, "loads": [{"qty": 10, "trailer": R}] * 3}
    assert B.plan_loads(job, BAGS30).startswith("Loads as given")
    with pytest.raises(ValueError, match="not the order's 30"):
        B.plan_loads({"vehicles": 2, "loads": [{"qty": 20, "trailer": A}, {"qty": 20, "trailer": R}]}, BAGS30)


class StatusR:
    """The dashboard as book_run asks it: the bridge's version, then Book's answer."""

    def __init__(self, version):
        self.version, self.asked = version, []

    def http(self, method, path):
        return 200, {"state": {"version": self.version}}

    def ask_waiting(self, action, wait_total=90, on_id=None, **args):
        self.asked.append((action, args))
        return ({"ok": True, "detail": "Booked"},
                {"trips": [{"manifest": "MAN-01000001", "status": "ACCEPTED"},
                           {"manifest": "MAN-01000002", "status": "ACCEPTED"}], "seconds": 90})


@pytest.fixture
def pressed(tmp_path, monkeypatch):
    import book_journal as J
    monkeypatch.setattr(J, "PATH", str(tmp_path / "_book_journal.json"))
    monkeypatch.setattr(B, "_lock", lambda: True)
    monkeypatch.setattr(B, "owed_first", lambda orders: [])
    monkeypatch.setattr(B, "record_of", lambda ident: dict(BAGS30, id=ident, postcode="EX1 1AA"))
    monkeypatch.setattr(B, "follow", lambda k, R=None, now=None, only=None: [])
    monkeypatch.setenv("R2_NO_CARD_READ", "1")
    return {"record": "9100001|04/12/2026", "orders": ["9100001"], "date": "04/12/2026", "carrier": "DHL_NOC",
            "haulier": "DHL NOC", "trailer": A, "vehicles": 2}


def test_book_sends_the_loads_to_a_bridge_that_knows_them(pressed):
    desk = StatusR("3")
    out = B.book(pressed, R=desk)
    action, args = desk.asked[0]
    assert action == "ctms_book" and args["loads"] == [{"qty": 20, "trailer": A}, {"qty": 10, "trailer": R}]
    assert args["vehicles"] == 2 and "20 bags on NR_ARTIC_FL and 10 on NR_FLAT_RIG" in out["said"]


def test_an_older_bridge_would_halve_the_line_so_nothing_is_sent_to_it(pressed):
    desk = StatusR("2")
    out = B.book(pressed, R=desk)
    assert desk.asked == [] and out.get("refused") and "Nothing was booked" in out["said"]
    assert "can't set the loads yet" in out["said"]


def test_split_equally_still_goes_to_any_bridge_without_loads(pressed):
    desk = StatusR("2")
    B.book(dict(pressed, equal=True), R=desk)
    assert desk.asked and "loads" not in desk.asked[0][1]


# -- the work PC's Book: split, each part set to its load, each booked on its own trailer
class Stubbed(CB.Booking):
    """Book's own steps, CTMS stood in for: what the split, the cards and the trips are asked."""

    def __init__(self, lines, dry=False):
        super().__init__(run=lambda steps: None, read=lambda *a, **k: [], seen=lambda n, b: False, t={}, dry=dry)
        self._lines, self.log = lines, []

    def start(self):
        pass

    def set_filters(self, region=None, strategy=None):
        pass

    def set_day(self, want):
        pass

    def stage(self, name):
        pass

    def halt(self, where):
        pass

    def look(self, tree=False, asking=False, card=False):
        return []

    def lines(self, orders, date):
        return [{"cust_ref": ref, "deliver": "04/12/26 07:30", "collect": "03/12/26 07:00"} for ref in self._lines]

    def prepare_line(self, ref, want=None):
        self.log.append(("card", ref, want))
        return want is not None

    def split(self, ref, parts, orders=None, date=""):
        self.log.append(("split", ref, parts))
        return [f"{ref}_S{i}" for i in range(1, parts + 1)]

    def trip(self, refs, carrier, trailer, haulage):
        self.log.append(("trip", refs, trailer))
        self.trips.append({"manifest": f"MAN-0100000{len(self.trips) + 1}", "status": "ACCEPTED", "lines": refs})


LOADS = [{"qty": 20, "trailer": A}, {"qty": 10, "trailer": R}]


def test_the_line_is_split_each_part_set_going_down_first_and_booked_on_its_own_trailer():
    job = Stubbed(["9100001-1-1"])
    job.book(["9100001"], "04/12/2026", "DHL_NOC", A, None, 2, loads=LOADS)
    assert job.log == [("card", "9100001-1-1", None),                 # the line checked as it is
                       ("split", "9100001-1-1", 2),
                       ("card", "9100001-1-1_S2", 10.0),              # 15 -> 10 first: never more than the order
                       ("card", "9100001-1-1_S1", 20.0),              # then 15 -> 20
                       ("trip", ["9100001-1-1_S1"], A),
                       ("trip", ["9100001-1-1_S2"], R)]
    assert any("set to their loads" in s for s in job.said)


def test_three_rigids_of_ten_are_three_parts_each_on_a_rigid():
    job = Stubbed(["9100001-1-1"])
    job.book(["9100001"], "04/12/2026", "DHL_NOC", R, None, 3, loads=[{"qty": 10, "trailer": R}] * 3)
    assert [x for x in job.log if x[0] == "trip"] == [("trip", [f"9100001-1-1_S{i}"], R) for i in (1, 2, 3)]


def test_without_loads_a_split_is_still_equal_and_all_on_the_one_trailer():
    job = Stubbed(["9100001-1-1"])
    job.book(["9100001"], "04/12/2026", "DHL_NOC", A, None, 2)
    assert [x for x in job.log if x[0] == "card"] == [("card", "9100001-1-1", None)]
    assert [x[2] for x in job.log if x[0] == "trip"] == [A, A]


def test_a_dry_run_says_the_loads_and_rehearses_the_first():
    job = Stubbed(["9100001-1-1"], dry=True)
    job.book(["9100001"], "04/12/2026", "DHL_NOC", A, None, 2, loads=LOADS)
    assert "the parts set to 20 on NR_ARTIC_FL, 10 on NR_FLAT_RIG" in job.said[0]
    assert [x for x in job.log if x[0] == "split"] == [] and job.log[-1] == ("trip", ["9100001-1-1"], A)


def test_loads_for_an_order_already_on_several_lines_stop_before_anything_is_touched():
    job = Stubbed(["9100001-1-1_S1", "9100001-1-1_S2"])
    with pytest.raises(CB.Stop, match="Nothing was booked"):
        job.book(["9100001"], "04/12/2026", "DHL_NOC", A, None, 2, loads=LOADS)
    assert job.log == []


@pytest.mark.parametrize("loads, vehicles", [
    (LOADS, 3),                                                       # not one a vehicle
    ([{"qty": 30, "trailer": A}], 1),                                 # one load is no split
    ([{"qty": 20, "trailer": A}, {"qty": 0, "trailer": R}], 2),
    ([{"qty": 20.5, "trailer": A}, {"qty": 9.5, "trailer": R}], 2),
    ([{"qty": 20, "trailer": A}, {"qty": 10}], 2),
])
def test_wrong_loads_stop_before_ctms_is_touched(loads, vehicles):
    job = Stubbed(["9100001-1-1"])
    with pytest.raises(CB.Stop, match="Nothing was booked"):
        job.book(["9100001"], "04/12/2026", "DHL_NOC", A, None, vehicles, loads=loads)
    assert job.log == []
