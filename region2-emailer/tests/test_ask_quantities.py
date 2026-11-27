"""The count an ask states is CTMS's (his 27/11: NOC was told 6 rails for a delivery CTMS holds 4 for - the 6 was the
extract's). Made-up orders.

    python -m pytest -q tests/test_ask_quantities.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask_quantities as Q  # noqa: E402

SHORT = "RAIL SHORT, 56E1, 260 GRADE, 13.716M, UNDRILLED"
LONG = "RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED"


def test_rails_of_one_length_are_counted_from_ctmss_weight():
    rec = {"materials": "4x rails", "product_codes": [SHORT], "ctms_weight": 1543.6}       # 2 x 13.716 m of 56E1
    c = Q.ctms_count(rec)
    assert c["count"] == 2 and c["said"] == "CTMS weighs them 1,544 kg: 2 rails, not the 4 the extract says"
    assert Q.ask_line(rec) == ("2x rails", "CTMS's weight")
    assert Q.ctms_count(dict(rec, materials="2x rails")) is None                            # they agree


def test_rails_of_two_lengths_are_checked_by_whether_the_weight_fits():
    rec = {"materials": "6x rails", "product_codes": [LONG, SHORT], "ctms_weight": 3601.7}  # 2 long + 2 short in CTMS
    c = Q.ctms_count(rec)
    assert c["count"] is None and "which isn't 6 rails" in c["said"]
    line, source = Q.ask_line(rec)
    assert line == "6x rails" and source.startswith("the extract - CHECK the count in CTMS before you ask")
    assert Q.ctms_count(dict(rec, materials="4x rails")) is None                            # 4 fits that weight


def test_bagged_ballast_is_a_tonne_a_bag_and_loose_isnt_counted():
    assert Q.ctms_count({"materials": "30x ballast", "ctms_weight": 30000.0}) is None
    c = Q.ctms_count({"materials": "30x ballast", "ctms_weight": 20000.0})
    assert c["count"] == 20 and c["what"] == "ballast"
    assert Q.ctms_count({"materials": "30x ballast", "ctms_weight": 20000.0, "loose_ballast": True}) is None
    assert Q.ctms_count({"materials": "30x ballast", "product_codes": ["0057/100500/001"], "ctms_weight": 1.0}) is None


def test_nothing_is_said_without_ctms_or_where_a_weight_cant_tell():
    assert Q.ctms_count({"materials": "4x rails", "product_codes": [SHORT]}) is None        # not looked up yet
    assert Q.ask_line({"materials": "4x rails"}) == ("4x rails", "the extract (CTMS not looked at yet)")
    assert Q.ctms_count({"materials": "40x sleepers", "ctms_weight": 9000.0}) is None
    assert Q.ctms_count({"materials": "10x rails, 40x sleepers", "ctms_weight": 9000.0}) is None
    assert Q.ctms_count({"materials": "4x rails", "product_codes": ["RAIL SHORT, 13.716M"], "ctms_weight": 99.0}) is None
