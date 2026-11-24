"""Plain-assert tests for windows that run past midnight - no Excel, no Outlook.

A form has one date for a leg and two times, so a 23:30 to 01:00 delivery reached
the upload ending before it began, and a return leg collecting at 23:30 defaulted
to delivering at 00:31 the same date, which fired a query at the requester about
dates they had never given.

Run:  python region2-emailer/tests/test_overnight_windows.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import date_query                       # noqa: E402
import nr_csv                           # noqa: E402
import process_form as PF               # noqa: E402

SAT = dt.datetime(2026, 11, 7)


def at(day, hhmm):
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m))


def form(collect=None, deliver=None, cday=SAT, dday=SAT, ref="AH9/9/99TEST"):
    """An admin row as the form evaluates it: one date for each leg, both times on it."""
    c = collect or (None, None)
    d = deliver or (None, None)
    return {"Customer Order No": ref, "Collection Date": cday, "Delivery Date": dday,
            "collection_time": at(cday, c[0]) if c[0] else None,
            "collection_time_end": at(cday, c[1]) if c[1] else None,
            "delivery_time": at(dday, d[0]) if d[0] else None,
            "delivery_time_end": at(dday, d[1]) if d[1] else None}


def windows(d):
    tr = PF.to_transform_row(d)
    return tr, (tr["collection time"], tr["collection time end"], tr["delivery time"], tr["delivery time end"])


def test_a_night_delivery_closes_on_the_next_day():
    tr, w = windows(form(("22:00", "23:00"), ("23:30", "01:00")))
    assert w == ("07/11/2026 22:00", "07/11/2026 23:00", "07/11/2026 23:30", "08/11/2026 01:00"), w
    assert date_query.backwards([tr]) == []


def test_a_return_leg_with_no_delivery_of_its_own_lands_after_it_collects():
    """The form's own shape: the return's delivery date is Excel's blank and its times are errors."""
    d = form(("23:30", "01:00"), None, dday=dt.time(0, 0))
    d["delivery_time"] = d["delivery_time_end"] = "#VALUE!"
    tr, w = windows(d)
    assert w == ("07/11/2026 23:30", "08/11/2026 01:00", "08/11/2026 00:31", "08/11/2026 02:01"), w
    assert date_query.backwards([tr]) == []


def test_a_default_that_only_crosses_midnight_at_its_end():
    _, w = windows(form(("22:30", "23:45"), None))
    assert w[2:] == ("07/11/2026 23:31", "08/11/2026 00:46"), w


def test_a_default_on_the_legs_own_later_date_keeps_that_date():
    _, w = windows(form(("23:30", "01:00"), None, dday=dt.datetime(2026, 11, 9)))
    assert w[2:] == ("09/11/2026 00:31", "09/11/2026 02:01"), w


def test_a_day_job_is_left_exactly_as_it_was():
    _, w = windows(form(("07:30", "15:00"), None))
    assert w == ("07/11/2026 07:30", "07/11/2026 15:00", "07/11/2026 08:31", "07/11/2026 16:01"), w
    _, w = windows(form(("08:00", "16:00"), ("09:00", "11:00")))
    assert w == ("07/11/2026 08:00", "07/11/2026 16:00", "07/11/2026 09:00", "07/11/2026 11:00"), w


def test_a_window_ending_at_midnight_ends_on_the_next_day():
    _, w = windows(form(("20:00", "21:00"), ("23:00", "00:00")))
    assert w[3] == "08/11/2026 00:00", w


def test_a_blank_closing_time_is_no_close_not_a_window_to_midnight():
    _, w = windows(form(("08:00", "00:00"), ("12:00", "00:00")))
    assert w == ("07/11/2026 08:00", "07/11/2026 16:01", "07/11/2026 12:00", "07/11/2026 14:00"), w
    _, w = windows(form(("09:00", "00:00"), None))         # no delivery either: never 10:01 to 01:01
    assert w == ("07/11/2026 09:00", "07/11/2026 17:01", "07/11/2026 09:01", "07/11/2026 17:01"), w
    _, w = windows(form(("23:00", "00:00"), ("01:00", "00:00"), dday=dt.datetime(2026, 11, 8)))
    assert w == ("07/11/2026 23:00", "08/11/2026 00:00", "08/11/2026 01:00", "08/11/2026 03:00"), w


def test_a_close_at_midnight_is_believed_from_the_evening_on():
    assert not nr_csv.unstated_close("07/11/2026 18:00", "07/11/2026 00:00")
    assert not nr_csv.unstated_close("07/11/2026 23:55", "07/11/2026 00:00")
    assert nr_csv.unstated_close("07/11/2026 17:59", "07/11/2026 00:00")
    assert not nr_csv.unstated_close("07/11/2026 12:00", "08/11/2026 00:00")      # a real next-day date
    assert not nr_csv.unstated_close("07/11/2026 12:00", "07/11/2026 16:00")
    assert not nr_csv.unstated_close("", "")


def test_the_brief_shows_no_close_where_the_form_gave_none():
    _, cw, _, dw = PF._leg_dates(form(("08:00", "00:00"), ("12:00", "00:00")))
    assert cw == {"earliest": "08:00", "latest": ""} and dw == {"earliest": "12:00", "latest": ""}, (cw, dw)
    _, cw, _, dw = PF._leg_dates(form(("22:00", "23:00"), ("23:30", "00:00")))
    assert cw == {"earliest": "22:00", "latest": "23:00"} and dw == {"earliest": "23:30", "latest": "00:00"}, (cw, dw)


def test_month_and_year_ends_roll_properly():
    eve = dt.datetime(2026, 12, 31)
    _, w = windows(form(("22:00", "23:00"), ("23:30", "01:00"), cday=eve, dday=eve))
    assert w[3] == "01/01/2027 01:00", w


def test_a_window_that_is_no_night_shift_is_left_for_a_person():
    for start, end in (("14:00", "08:00"), ("14:00", "04:00"), ("12:00", "01:00"), ("17:59", "01:00")):
        d = form(("07:00", "08:00"), (start, end))
        tr, w = windows(d)
        assert w[2:] == (f"07/11/2026 {start}", f"07/11/2026 {end}"), w
        assert any(n.startswith("!!") and "CHECK BY HAND" in n for n in PF.window_notes(d, tr)), w
    _, w = windows(form(("07:00", "08:00"), ("18:00", "04:00")))        # the evening: a night shift
    assert w[3] == "08/11/2026 04:00", w


def test_a_blank_collection_close_never_puts_the_delivery_before_it():
    for start, want in (("10:00", "11:01"), ("12:00", "13:01"), ("17:59", "19:00")):
        tr, w = windows(form((start, "00:00"), None))
        assert w[2] == f"07/11/2026 {want}", w
        assert date_query.backwards([tr]) == [], w
    tr, w = windows(form(("22:00", None), None))
    assert date_query.backwards([tr]) == [], w
    assert nr_csv.dated(w[3]) > nr_csv.dated(w[2]), w


def test_the_run_says_what_it_decided():
    d = form(("23:30", "01:00"), None)
    tr, _ = windows(d)
    notes = PF.window_notes(d, tr)
    assert any("collection window runs past midnight" in n for n in notes), notes
    assert any("the form says delivery 07/11/2026" in n and "goes up as 08/11/2026" in n for n in notes), notes
    d = form(("08:00", "16:00"), ("09:00", "11:00"))
    tr, _ = windows(d)
    assert PF.window_notes(d, tr) == []


def test_a_close_on_the_stroke_of_midnight_owes_nothing_for_the_next_day():
    import ctms_todo
    fri, sat, sun = dt.datetime(2026, 11, 6), dt.datetime(2026, 11, 7), dt.datetime(2026, 11, 8)
    owed = lambda s, e: ctms_todo.services_owed([("deliver", s, e)])
    assert owed(at(fri, "21:00"), at(sat, "00:00")) == ["NIGHT"]
    assert owed(at(sat, "21:00"), at(sun, "00:00")) == ["NIGHT", "SATURDAY"]
    assert owed(at(sat, "23:30"), at(sun, "01:00")) == ["NIGHT", "SATURDAY", "SUNDAY"]    # works into it


def test_a_stated_delivery_before_its_collection_is_still_the_requesters_question():
    tr, w = windows(form(("22:00", "23:00"), ("09:00", "11:00")))
    assert w[2:] == ("07/11/2026 09:00", "07/11/2026 11:00"), w
    assert [p["back_by"] for p in date_query.backwards([tr])] == ["13h 00m"]
    tr, w = windows(form(("08:00", "16:00"), None, dday=dt.datetime(2026, 11, 5)))
    assert w[2][:10] == "05/11/2026", w
    assert len(date_query.backwards([tr])) == 1


def test_an_end_on_a_typed_earlier_date_is_not_touched():
    assert nr_csv.roll_overnight("07/11/2026 23:30", "05/11/2026 01:00") == "05/11/2026 01:00"


def test_no_date_anywhere_stays_blank():
    d = {"Customer Order No": "AH9/9/99TEST", "Collection Date": dt.time(0, 0), "Delivery Date": dt.time(0, 0)}
    _, w = windows(d)
    assert w == ("", "", "", ""), w
    assert nr_csv.roll_overnight("", "") == ""
    assert nr_csv.after_collection("", "", "") == ("", "")


def test_the_other_routes_default_no_longer_ends_before_it_starts():
    assert nr_csv.unconfirmed_window("07/11/2026", ("22:30", "23:45")) == ("07/11/2026 23:31", "08/11/2026 00:46")
    assert nr_csv.unconfirmed_window("07/11/2026", ("07:00", "17:00")) == ("07/11/2026 08:01", "07/11/2026 18:01")
    assert nr_csv.unconfirmed_window("07/11/2026", ("10:00", "23:30")) == ("07/11/2026 11:01", "08/11/2026 00:31")
    assert nr_csv.unconfirmed_window("07/11/2026") == ("07/11/2026 09:01", "07/11/2026 17:01")


def test_the_upload_row_carries_the_rolled_dates():
    d = form(("22:00", "23:00"), ("23:30", "01:00"))
    d.update({"Site Name - Collection": "Yard A", "Delivery Point": "Site B", "Account": "NRADHOC",
              "Postcode": "AA1 1AA", "D Postcode": "BB1 1BB"})
    rows = nr_csv.transform([PF.to_transform_row(d)])
    (_, legs), = nr_csv.order_windows(rows)
    assert legs[1][2] == dt.datetime(2026, 11, 8, 1, 0), legs


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print(f"{len(tests)}/{len(tests)} passed")
