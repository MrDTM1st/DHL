"""Times off the forms and sheets onto the upload: a DTS "2.30PM" or "0930" is the time it says, a Synergy site saved
as "07:00" still fills ORDER 13/14, a Media Sets row with no times gets the same default window as every other route
(and its own audit check actually runs), and a Word form's "Open Hours: 00:00 - 24:00" does not crash. Made-up sites.

    python tests/test_form_times.py
"""
import builtins
import io
import os
import sys
from datetime import datetime, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dts_convert as DC  # noqa: E402
import media_sets as M  # noqa: E402
import process_word_form as PW  # noqa: E402


def _synergy_map():
    """synergy_map reads its site store at import - a store this PC may not have. An empty one is all _hours needs."""
    if "synergy_map" in sys.modules:
        return sys.modules["synergy_map"]
    real = builtins.open
    builtins.open = lambda p, *a, **k: (io.StringIO("{}") if str(p).endswith("_synergy_sites.json")
                                         else real(p, *a, **k))
    try:
        import synergy_map
    finally:
        builtins.open = real
    return synergy_map


def test_a_dts_time_reads_with_a_dot_or_no_separator_at_all():
    for raw, want in (("2.30PM", "14:30"), ("9.30AM", "09:30"), ("0930", "09:30"), ("1530", "15:30"),
                      ("930", "09:30"), ("9AM", "09:00"), ("12PM", "12:00"), ("12AM", "00:00"), ("NOON", "12:00"),
                      ("09:00", "09:00"), ("14:00", "14:00"), ("9:30 am", "09:30")):
        assert DC.to_time(raw) == want, raw
    # never a time that is no time - the default instead
    for raw in ("", "25:00", "9:75", "TBC"):
        assert (DC.to_time(raw), DC.to_time(raw, True)) == ("09:00", "14:00"), raw


def test_a_synergy_site_saved_without_seconds_still_has_hours():
    S = _synergy_map()
    assert S._hours("07:00") == S._hours("07:00:00") == S._hours("7:00:00")
    assert S._hours("17:00").total_seconds() == 17 * 3600
    assert S._hours("") is None and S._hours(None) is None and S._hours("7") is None


def _row(cdate, cstart, cend, ddate, dstart, dend):
    return ["Example Depot", "Sam Example", "01000 000000", "1 Example Road", "", "", "DN16 1BP",
            cdate, cstart, cend, "Example Siding", "2 Example Road", "", "", "DE24 8AD", ddate, dstart, dend, 1]


def test_a_media_sets_row_with_no_times_gets_the_default_window_not_midnight():
    o, _ = M.to_orders([_row(datetime(2026, 11, 10), None, None, datetime(2026, 11, 11), "", "junk")], 19)
    o = o[0]
    assert (o["collection time"], o["collection time end"]) == ("10/11/2026 09:01", "10/11/2026 17:01")
    # the delivery defaults off this row's own collection window, +1h01m, as every other route does
    assert (o["delivery time"], o["delivery time end"]) == ("11/11/2026 10:02", "11/11/2026 18:02")
    # a start with no end closes after it, never on a 00:00 before it
    o, _ = M.to_orders([_row(datetime(2026, 11, 10), time(7, 0), None, datetime(2026, 11, 11), time(9, 0), None)], 19)
    o = o[0]
    assert (o["collection time"], o["collection time end"]) == ("10/11/2026 07:00", "10/11/2026 15:01")
    assert (o["delivery time"], o["delivery time end"]) == ("11/11/2026 09:00", "11/11/2026 11:00")
    # stated times go up exactly as stated
    o, problems = M.to_orders([_row(datetime(2026, 11, 10), time(7, 0), time(15, 0),
                                    datetime(2026, 11, 11), time(8, 0), time(16, 0))], 19)
    assert (o[0]["collection time"], o[0]["delivery time end"]) == ("10/11/2026 07:00", "11/11/2026 16:00")
    assert problems == []


def test_the_media_sets_audit_check_flags_a_collection_after_its_delivery():
    _, problems = M.to_orders([_row(datetime(2026, 11, 12), time(7, 0), time(15, 0),
                                    datetime(2026, 11, 11), time(8, 0), time(16, 0))], 19)
    assert len(problems) == 1 and "12/11 07:00 is AFTER delivery 11/11 08:00" in problems[0]


def test_open_all_day_on_a_word_form_ends_at_23_59():
    day = datetime(2026, 11, 10)
    assert PW._window("Open Hours: 00:00 - 24:00") == ("00:00", "24:00")
    assert PW._at(day, "24:00") == datetime(2026, 11, 10, 23, 59)
    assert PW._at(day, "16:00") == datetime(2026, 11, 10, 16, 0)


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
