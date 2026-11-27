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


def _replied(raw, options=("30/11/2026", "01/12/2026")):
    """A made-up order whose site gave these days, as the reply parser keeps them: two dates are always "flexible"."""
    return {"orders": ["9100123"], "details": {"date": {"value": options[-1], "flexible": True, "options": list(options),
                                                        "confidence": "high", "raw": raw},
                                               "time": {"earliest": "08:00", "latest": "16:00"}}}


def test_a_choice_of_days_is_one_delivery_and_the_site_isnt_told_of_another():
    # 27/11: the site asked "30/11 or 01/12?", the whole load went on one manifest for 01/12, and the site email said
    # "The rest is booked for 30/11/2026 separately"
    rec = _replied("Hi, would 30/11/26 or 01/12/26 be ok? Offloading HIAB")
    assert S.days(rec) == [] and S.is_split(rec) is False and S.note(rec, "01/12/2026") == ""
    body = B.words("Robin", "MADEUP_DH", "Made Up Haulage", "01/12/2026",
                   [{"manifest": "MAN-00000001", "deliver": "01/12/26 08:00"}], rec)
    assert "The rest is booked" not in body and "separate" not in body
    assert "Tuesday 01/12/2026, delivering between 08:00 and 16:00. Here is the ref number MAN-00000001" in body


def test_days_that_each_need_a_delivery_are_still_told_as_the_rest():
    rec = _replied("X40 30/11/26 X40 01/12/26")
    assert S.days(rec) == ["30/11/2026", "01/12/2026"] and S.is_split(rec) is True
    assert S.note(rec, "30/11/2026") == "The rest is booked for 01/12/2026 separately."
    body = B.words("Robin", "MADEUP_DH", "Made Up Haulage", "30/11/2026",
                   [{"manifest": "MAN-00000001", "deliver": "30/11/26 08:00"}], rec)
    assert "The rest is booked for 01/12/2026 separately." in body
