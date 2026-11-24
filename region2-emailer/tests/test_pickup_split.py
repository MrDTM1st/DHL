import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickup_split as S  # noqa: E402
import book_run as B  # noqa: E402

REC = {"collections": [{"site": "TML-Trackwork NSC-", "pc": "DN4", "date": "10/11/2026"},
                       {"site": "SOM-Cemex NDS-", "pc": "DE5", "date": "10/11/2026"}],
       "details": {"date": {"options": ["13/11/2026", "11/11/2026"]}}}


def test_one_pickup_one_day_says_nothing():
    assert S.note({"collections": [{"site": "A", "date": "10/11/2026"}]}) == ""


def test_several_pickups_and_days_are_told_and_the_other_day_named():
    n = S.note(REC, "11/11/2026")
    assert "2 separate pick-ups (TML-Trackwork NSC on 10/11/2026; SOM-Cemex NDS on 10/11/2026)" in n
    assert "booked for 13/11/2026 separately" in n
    assert S.days(REC) == ["11/11/2026", "13/11/2026"]


def test_the_site_email_carries_it():
    rec = dict(REC, details=dict(REC["details"], time={"earliest": "07:00", "latest": "12:00"}))
    body = B.words("Robin", "DH_X", "X", "11/11/2026", [{"manifest": "MAN-1", "deliver": "11/11/2026 07:00"}], rec)
    assert "separate pick-ups" in body
