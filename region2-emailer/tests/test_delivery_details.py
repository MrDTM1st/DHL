"""What a site's reply says about WHEN (delivery_details): a time after "20th nov" is a time, not the year; a phone
number is never a time; a 12-hour "7:30 - 3:30" is an afternoon, not a 20-hour window; and "no later than 10am" is the
latest, not the earliest. A confidently wrong value goes straight into a booking, so what can't be read is amber.
Made-up people and numbers only.

    python tests/test_delivery_details.py
"""
import contextlib
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import delivery_details as D  # noqa: E402

D.recall = lambda field, raw: None      # what was learned on this PC never decides a test


@contextlib.contextmanager
def _on(day):
    """The parser's clock stood on one day - the year a date takes and what counts as gone both come from it."""
    real = D.datetime

    class Fixed(real):
        @classmethod
        def now(cls, tz=None):
            return cls(day.year, day.month, day.day, 9, 0)
    D.datetime = Fixed
    try:
        yield
    finally:
        D.datetime = real


def test_four_digits_after_an_ordinal_date_are_the_time_not_the_year():
    with _on(date(2026, 11, 4)):
        assert D.find_dates("20th nov 2200") == [date(2026, 11, 20)]
        assert D.find_dates("Tuesday 10th November 0900") == [date(2026, 11, 10)]
        assert D.find_dates("20th nov 2026") == [date(2026, 11, 20)]           # a real year still reads
        assert D.find_dates("3rd jan 2027") == [date(2027, 1, 3)]
        d = D.parse_reply("Date & time of delivery? 20th nov 2200\n")
        assert (d["date"]["value"], d["date"]["confidence"]) == ("20/11/2026", D.HIGH)
        assert (d["time"]["earliest"], d["time"]["latest"]) == ("22:00", "00:00")
        d = D.parse_reply("Date & time of delivery? Tuesday 10th November 0900\n")
        assert d["date"]["value"] == "10/11/2026" and d["time"]["earliest"] == "09:00"


def test_a_phone_number_is_never_a_time():
    with _on(date(2026, 11, 4)):
        for body, window in (("Tuesday 10/11/2026 at 8am is fine. Contact Dave on 0114 234 5678", ("08:00", "10:00")),
                             ("deliver 10/11/2026, 9am. Site contact Sue 0121 496 0000", ("09:00", "11:00"))):
            t = D.parse_reply(body)["time"]
            assert (t["earliest"], t["latest"], t["confidence"]) == window + (D.HIGH,), body
    assert D.find_times("call +44 (0)114 234 5678, deliver 9am") == ["09:00"]
    assert D.find_times("07700-900-123 at 10:00") == ["10:00"]
    assert D.find_times("0114 234 5678 8am") == ["08:00"]                     # a time straight after one
    assert D.find_times("0800 07700 900123") == ["08:00"]                     # a time straight before one
    assert D.find_times("po 0123456789 8am") == ["08:00"]                     # the 8 of 8am is not its last digit
    assert D.find_times("0800 - 1600") == ["08:00", "16:00"]                  # a range is not a phone number
    assert D.find_times("0800 - 1600 07700 900123") == ["08:00", "16:00"]


def test_a_12_hour_end_with_no_pm_is_the_afternoon():
    assert D.parse_time_window("7:30 - 3:30") == ("07:30", "15:30", D.HIGH)
    assert D.parse_time_window("8:00 till 4:00") == ("08:00", "16:00", D.HIGH)
    assert D.parse_time_window("11:00 - 1:00") == ("11:00", "13:00", D.HIGH)
    assert D.parse_time_window("9am - 3:30") == ("09:00", "15:30", D.HIGH)


def test_a_window_that_ends_before_it_starts_is_asked_unless_it_is_a_night_shift():
    assert D.parse_time_window("Thursday 12.11 8am") == ("12:11", "08:00", D.AMBER)
    assert D.parse_time_window("06:00 - 00:00")[2] == D.AMBER                  # 00:00 is 24-hour - never moved
    assert D.parse_time_window("2pm - 4:00")[2] == D.AMBER
    assert D.parse_time_window("09:00 - 09:00")[2] == D.AMBER
    assert D.parse_time_window("22:00 - 04:00") == ("22:00", "04:00", D.HIGH)
    assert D.parse_time_window("21:00-05:00") == ("21:00", "05:00", D.HIGH)
    assert D.parse_time_window("between 22:00 and 06:00") == ("22:00", "06:00", D.HIGH)


def test_no_later_than_is_the_latest_and_the_two_hours_go_in_front():
    for t in ("no later than 10am", "not later than 10am", "before 10am", "by 10:00", "until 10am", "till 10:00",
              "latest 10am", "latest: 10am", "10am latest", "10:00 at the latest"):
        assert D.parse_time_window(t) == ("08:00", "10:00", D.HIGH), t
    for t in ("after 10am", "from 10am", "10am", "10am earliest"):
        assert D.parse_time_window(t) == ("10:00", "12:00", D.HIGH), t
    assert D.parse_time_window("before 1am") == ("23:00", "01:00", D.HIGH)
    # the "by" of a date is not the time's: "by 20/11/2026 8am" is still 8am onwards
    assert D.parse_time_window("deliver by 20/11/2026 8am") == ("08:00", "10:00", D.HIGH)
    with _on(date(2026, 11, 4)):
        t = D.parse_reply("Date & time of delivery? 13/11/2026 no later than 10am\n")["time"]
        assert (t["earliest"], t["latest"], t["expanded"]) == ("08:00", "10:00", True)


def test_ordinary_answers_read_as_they_always_have():
    for t, want in (("08:00-16:00", ("08:00", "16:00")), ("8am", ("08:00", "10:00")),
                    ("between 9 and 11am", ("09:00", "11:00")), ("22:00hrs", ("22:00", "00:00")),
                    ("9:30am - 2:30pm", ("09:30", "14:30")), ("19th feb 2300", ("23:00", "01:00")),
                    ("Monday 10/11/2026 0900", ("09:00", "11:00")), ("0800 - 1600", ("08:00", "16:00")),
                    ("7:00 AM - 3:00 PM", ("07:00", "15:00")), ("23:00 - 01:00", ("23:00", "01:00"))):
        assert D.parse_time_window(t) == want + (D.HIGH,), t
    assert D.parse_time_window("0800-1600") == (None, None, D.AMBER)
    assert D.parse_time_window("18.288m rail") == (None, None, D.AMBER)


def test_a_bare_starting_hour_is_the_start_of_the_window_not_lost():
    for said, want in (("between 9 and 11am", ("09:00", "11:00")), ("9-11am", ("09:00", "11:00")),
                       ("Delivery time: 9 - 11am", ("09:00", "11:00")), ("8 to 4pm", ("08:00", "16:00")),
                       ("1 to 4pm", ("13:00", "16:00")), ("10 to 12pm", ("10:00", "12:00")),
                       ("11-1pm", ("11:00", "13:00")), ("from 7 till 3pm", ("07:00", "15:00"))):
        lo, hi, conf = D.parse_time_window(said)
        assert (lo, hi, conf) == (want[0], want[1], D.HIGH), (said, lo, hi, conf)
    # what it was before stays: a time with its own am/pm, and a lone "until" time is still the latest
    assert D.parse_time_window("9am-11am") == ("09:00", "11:00", D.HIGH)
    assert D.parse_time_window("until 3pm") == ("13:00", "15:00", D.HIGH)
    assert D.parse_time_window("between 8 and 10") == (None, None, D.AMBER)      # no clock time in it at all
    assert D.parse_time_window("Gate 3 - 9am") == ("09:00", "11:00", D.HIGH)    # a place's number is no start
    assert D.parse_time_window("Unit 4 to 8am") == ("08:00", "10:00", D.HIGH)


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
