"""Plain-assert tests for ad hocs typed into an email - no Excel, no Outlook.

AH3/11/26EHBB (02/11/2026, a courier box, Edinburgh to Sabden) had to be finished by hand: "from 9am" was not read, the
"call me before you pick up" had nowhere to go, and the county on its own line went on the upload as the town.

Run:  python region2-emailer/tests/test_email_adhoc.py
"""
import os
import re
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import nr_csv                           # noqa: E402
import process_email_adhoc as PE        # noqa: E402
import process_form as PF               # noqa: E402
import process_word_form as PW          # noqa: E402

Y = datetime.now().year
COURIER = """Collection date: 03/11/2026, from 9am
Collection address:
  Network Rail Telecom
  Edinburgh Waverley Station
  Edinburgh
  EH1 1BB
  Contact: Robin Field - 07700900790
Collection notes: Courier must call Robin before picking up, to arrange access through the secure station entrance

Delivery date: 04/11/2026
Delivery address:
  DAC Limited
  Union Mill
  Watt Street
  Sabden
  Lancashire
  BB7 9ED
  Contact: Chris De Clerk - 07700 900838 / Sue Other - 07700 900123

Cost centre: 100001
Raised by: Robin.Field@networkrail.co.uk
Item description: Telephone spares - X1 Box, 10 Kg approx
"""


def job(text):
    with tempfile.TemporaryDirectory() as t:
        path = os.path.join(t, "job.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return PE.parse(path)


def test_a_range_still_reads_as_it_did():
    for text, want in (("02/09/2026, window 0900-1200", ("09:00", "12:00")),
                       ("window 2300-2359", ("23:00", "23:59")),
                       ("18/10/2026, window 0000-0600", ("00:00", "06:00")),
                       ("Open 08:00 - 16:00", ("08:00", "16:00")),
                       ("08.00 to 16.00", ("08:00", "16:00")),
                       ("9:30-11:00", ("09:30", "11:00")),
                       ("03/11/2026 0900-1700", ("09:00", "17:00")),
                       ("03/11/2026", ("", "")), ("", ("", "")), (None, ("", ""))):
        assert PE.window(text) == want, (text, PE.window(text))


def test_a_start_with_no_end_is_kept():
    for text, want in (("03/11/2026, from 09:00", "09:00"), ("03/11/2026, from 9am", "09:00"),
                       ("from 9.30am", "09:30"), ("from 9:30 a.m.", "09:30"), ("from 0900", "09:00"),
                       ("from 0900hrs", "09:00"), ("from 09:00hrs", "09:00"), ("9am onwards", "09:00"),
                       ("09:00 onwards", "09:00"), ("0900 onwards", "09:00"), ("after 13:00", "13:00"),
                       ("at 2pm", "14:00"), ("not before 09:00", "09:00"), ("no earlier than 9am", "09:00"),
                       ("ready from 9am", "09:00"), ("available from approx 08:30", "08:30"),
                       ("Tuesday 03/11/2026 09:00", "09:00"), ("03/11/2026 0900", "09:00"), ("03/11/2026\n09:00", "09:00"),
                       ("from noon", "12:00"), ("from 12pm", "12:00"), ("from 12am", "00:00"), ("from 12 midday", "12:00")):
        assert PE.window(text) == (want, ""), (text, PE.window(text))


def test_a_deadline_is_not_a_start():
    for text in ("03/11/2026, by 12:00", "by 12pm", "by midday", "before 12:00", "no later than 12:00", "not after 12:00",
                 "until 12:00", "12:00 latest", "12:00 at the latest", "latest 1200", "by 1200", "on or before 12:00"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
        assert PE.deadline(text) == "12:00", (text, PE.deadline(text))
    for text in ("from 09:00", "09:00-12:00", "03/11/2026", "not before 12:00"):
        assert PE.deadline(text) == "", text


def test_a_start_with_its_end_or_deadline_is_a_window():
    for text in ("from 9am to 5pm", "9am-5pm", "9am - 5pm", "between 09:00 and 17:00", "between 9am and 5pm",
                 "from 09:00 until 17:00", "from 09:00, by 17:00", "from 9am, no later than 5pm",
                 "between 0900 and 1700", "0900 to 1700"):
        assert PE.window(text) == ("09:00", "17:00"), (text, PE.window(text))


def test_nothing_is_read_out_of_a_date_or_a_guess():
    for text in ("03.11.2026", "3.11.26", "02/09/2026", "2 September 2026", "from 2 September 2026", "3-Nov-2026",
                 "from 9", "from 9 to 5", "morning", "AM", "tbc", "13pm", "from 13pm"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
    assert PE.window("03.11.2026 from 09.30") == ("09:30", "")
    assert PE.window(f"2 September {Y}, from 0900") == ("09:00", "")


def test_a_time_no_clock_shows_reads_as_nothing_not_a_crash():
    for text in ("25:00-26:00", "from 25:00", "window 2500-2600", "09:75 onwards", "from 09:00 by 25:00"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))


def test_a_county_line_is_not_the_town():
    addr = lambda *lines: PE.address("\n".join(lines))
    assert addr("DAC Limited", "Union Mill", "Watt Street", "Sabden", "Lancashire", "BB7 9ED") == (
        "DAC Limited", "Union Mill", "Watt Street", "Sabden", "BB7 9ED")
    for county in ("Lancashire", "LANCASHIRE", "Lancs", "West Yorkshire", "North Yorks", "East Sussex", "Tyne & Wear",
                   "Tyne and Wear", "County Durham", "Co. Durham", "Co Antrim", "Greater Manchester", "South Wales"):
        assert addr("Site", "1 High Street", "Sometown", county, "BB7 9ED") == (
            "Site", "1 High Street", "", "Sometown", "BB7 9ED"), county
    assert addr("Site", "Sabden", "Lancashire", "BB7 9ED") == ("Site", "Sabden", "", "Sabden", "BB7 9ED")
    # a street above the county: no town was given, and the street stays the street
    for street in ("1 High Street", "Watt Street", "Moor Lane", "Mitre Way", "Station Rd", "Watt St."):
        assert addr("Site", street, "West Yorkshire", "BD1 1AA") == ("Site", street, "", "West Yorkshire", "BD1 1AA"), street
    assert addr("Site", "Union Mill", "Watt Street", "Lancashire", "BB7 9ED") == (
        "Site", "Union Mill", "Watt Street", "Lancashire", "BB7 9ED")


def test_a_town_stays_the_town():
    addr = lambda *lines: PE.address("\n".join(lines))
    # the docstring's and real jobs' shapes
    assert addr("Network Rail Telecom", "Edinburgh Waverley Station", "Edinburgh", "EH1 1BB") == (
        "Network Rail Telecom", "Edinburgh Waverley Station", "", "Edinburgh", "EH1 1BB")
    assert addr("Sperry Rail (International) Ltd", "Donington House", "Riverside Road", "Pride Park", "Derby", "DE24 8HY") == (
        "Sperry Rail (International) Ltd", "Donington House", "Riverside Road Pride Park", "Derby", "DE24 8HY")
    # line 1 is never blank: 0 of the 223 uploads on file left it so
    assert addr("Pullmans Place", "Staines", "TW18 4LD") == ("Pullmans Place", "Staines", "", "Staines", "TW18 4LD")
    assert addr("Network Rail - Chathill LC", "Chathill", "Northumberland", "NE67 5DE") == (
        "Network Rail - Chathill LC", "Chathill", "", "Chathill", "NE67 5DE")
    # also towns: only "County Durham" or "Co. Antrim" means the county
    for town in ("Durham", "Antrim", "Armagh", "Londonderry"):
        assert addr("Site", "1 High Street", town, "DH1 1AA")[3] == town, town
    # capitals say nothing: these lost a word to the old guess
    for town in ("BISHOP AUCKLAND", "MILTON KEYNES", "NEWCASTLE UPON TYNE", "BURTON ON TRENT"):
        assert addr("Site", "1 High Street", town, "DL14 7AA")[3] == town, town
    # named after a county, not one
    assert addr("Site", "Lancashire Road", "Sometown", "BB7 9ED")[1] == "Lancashire Road"
    assert addr("Site", "1 High Street", "Kent Town", "BB7 9ED")[3] == "Kent Town"
    # nothing better for the town field: it stays
    assert addr("Site", "Lancashire", "BB7 9ED")[3] == "Lancashire"


def test_a_county_on_the_towns_line_comes_off():
    addr = lambda *lines: PE.address("\n".join(lines))
    assert addr("Site", "1 High Street", "Retford NOTTINGHAMSHIRE DN22 6AA")[3] == "Retford"
    assert addr("Site", "1 High Street", "Sabden, Lancashire", "BB7 9ED")[3] == "Sabden"
    assert addr("Site", "1 High Street", "Bradford West Yorkshire", "BD1 1AA")[3] == "Bradford"
    assert addr("Site", "1 High Street", "Bishop Auckland, Co. Durham", "DL14 7AA")[3] == "Bishop Auckland"
    assert addr("Site", "1 High Street", "Sabden, Lancs BB7 9ED")[3] == "Sabden"
    assert addr("Site", "1 High Street", "Bradford, West Yorkshire", "BD1 1AA")[3] == "Bradford"


def test_a_note_rides_on_the_upload():
    row, _ = job(COURIER)
    assert row["Notes for Collection Location Comments"] == (
        "Courier must call Robin before picking up to arrange access through the secure station entrance"), row
    assert row["Notes for Delivery Location Comments"] == "Also Sue Other 07700 900123", row
    tr = PF.to_transform_row(row)
    order = next(r for r in nr_csv.transform([tr]) if r[0] == "ORDER")
    assert order[6] == row["Notes for Collection Location Comments"], order[6]
    assert order[32] == "Also Sue Other 07700 900123", order[32]
    assert len(order) == 35 and not any("," in str(v) for v in order), order


def test_a_note_goes_in_front_of_the_second_contact_and_can_run_over_lines():
    row, _ = job(COURIER.replace("Cost centre:", "Delivery instructions:\n  Ring Chris first,\n  gate 3 only\nCost centre:"))
    assert row["Notes for Delivery Location Comments"] == "Ring Chris first gate 3 only. Also Sue Other 07700 900123", row


def test_notes_and_dates_are_never_taken_for_the_address():
    text = """Collection notes: Ring first
Collection date: 03/11/2026
Collection window: 09:00-12:00
Collection:
  Network Rail Telecom
  Edinburgh Waverley Station
  Edinburgh
  EH1 1BB
  Contact: Robin Field - 07700900790
Delivery time: from 14:00
Delivery date: 04/11/2026
Delivery comments: Gate 3
Delivery:
  DAC Limited
  Union Mill
  Sabden
  BB7 9ED
  Contact: Chris De Clerk - 07700900838
"""
    row, meta = job(text)
    assert row["Site Name - Collection"] == "Network Rail Telecom" and row["Postcode"] == "EH1 1BB", row
    assert row["Delivery Point"] == "DAC Limited" and row["D Postcode"] == "BB7 9ED", row
    assert row["Notes for Collection Location Comments"] == "Ring first", row
    assert row["Notes for Delivery Location Comments"] == "Gate 3", row
    assert (row["collection_time"].hour, row["collection_time_end"].hour) == (9, 12), row
    assert row["delivery_time"].hour == 14 and row["delivery_time_end"] is None, row
    assert meta["unread"] == [], meta


def test_the_upload_gets_the_windows_it_should():
    row, meta = job(COURIER)
    assert row["Customer Order No"] == "AH3/11/26EHBB", row
    assert row["D Address 1"] == "Union Mill" and row["D Address 2"] == "Watt Street" and row["D Address 3"] == "Sabden", row
    tr = PF.to_transform_row(row)
    assert (tr["collection time"], tr["collection time end"]) == ("03/11/2026 09:00", "03/11/2026 17:01"), tr
    assert (tr["delivery time"], tr["delivery time end"]) == ("04/11/2026 09:01", "04/11/2026 17:01"), tr
    said = PE.windows_said(row, tr, meta)
    assert any("collection start stated, no end - 03/11/2026 09:00 to 03/11/2026 17:01" in s for s in said), said
    assert any("delivery window not stated - 04/11/2026 09:01 to 04/11/2026 17:01" in s for s in said), said
    # a delivery start closes two hours on, his rule for any slot
    row, meta = job(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026 at 14:00"))
    tr = PF.to_transform_row(row)
    assert (tr["delivery time"], tr["delivery time end"]) == ("04/11/2026 14:00", "04/11/2026 16:00"), tr


def test_a_deadline_is_told_not_dropped():
    row, meta = job(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026, by 12:00"))
    assert row["delivery_time"] is None and meta["deadlines"]["delivery"] == "12:00", meta
    said = PE.windows_said(row, PF.to_transform_row(row), meta)
    assert any(s.startswith("!! delivery must be done by 12:00") for s in said), said


def test_an_address_with_no_line_is_told():
    row, meta = job(COURIER.replace("  Union Mill\n  Watt Street\n  Sabden\n  Lancashire\n", ""))
    assert row["D Address 1"] == "" and row["D Postcode"] == "BB7 9ED", row
    said = PE.windows_said(row, PF.to_transform_row(row), meta)
    assert any(s.startswith("!! delivery has no address line") for s in said), said


def test_a_line_nothing_reads_is_told():
    row, meta = job("Please see below\n" + COURIER + "Before collection: ring Robin\nAccess: gate 3\n")
    assert meta["unread"] == ["Please see below", "before collection: ring Robin", "access: gate 3"], meta
    said = PE.windows_said(row, PF.to_transform_row(row), meta)
    assert any("Not read" in s and "ring Robin" in s for s in said), said
    assert job(COURIER)[1]["unread"] == []


def test_the_desks_flags_read_a_start_too():
    row, meta = job(COURIER)
    used = PW.apply_overrides(row, {"delivery": "05/11/2026 from 10am"}, read_window=PE.window)
    assert used == ["delivery 05/11/2026 from 10:00"], used
    assert row["delivery_time"].hour == 10 and row["delivery_time_end"] is None, row
    # the Word form's route, and a lone 1002, are as they were
    row, _ = job(COURIER)
    assert PW.apply_overrides(row, {"delivery": "05/11/2026 from 10am"}) == ["delivery 05/11/2026 (no window given)"]
    assert row["Raised by"] == "Robin.Field@networkrail.co.uk;", row


def said(text):
    """What the run tells about a job."""
    row, meta = job(text)
    return row, PF.to_transform_row(row), PE.windows_said(row, PF.to_transform_row(row), meta)


def test_a_dotted_range_is_not_a_date():
    for text, want in (("03/11/2026, 08.00-16.00", ("08:00", "16:00")), ("window 08.00-16.00", ("08:00", "16:00")),
                       ("09:00-12.00", ("09:00", "12:00")), ("09.30-12.30", ("09:30", "12:30"))):
        assert PE.window(text) == want, (text, PE.window(text))
    assert PW._first_date("08.00-16.00 on 04/11/2026").strftime("%d/%m/%Y") == "04/11/2026"
    assert PW._first_date("08.10-16.30 on 04/11/2026").strftime("%d/%m/%Y") == "04/11/2026"


def test_window_anchors_the_range_whatever_else_the_line_holds():
    for text, want in (("03/11/2026 closed 12:00-13:00, window 0900-1700", ("09:00", "17:00")),
                       ("03/11/2026, gate 08:00-17:00, window 0900-1200", ("09:00", "12:00"))):
        assert PE.window(text) == want, (text, PE.window(text))


def test_a_line_about_something_else_gives_no_time_and_is_told():
    for text in ("ring at 08:00, collect from 10:00", "booking in at 08:00, deliver at 10:00",
                 "ready from 8am, must be delivered by 4pm", "ring Robin at 0131 496 0345", "call site at 0800 123 4567",
                 "from 9am, up to 12.50 tonnes", "rails at 12.20 m", "load at 1500 kg", "CW1 8PM - 06:00",
                 "site closes at 16:00", "no deliveries after 15:00", "no deliveries before 09:00", "do not arrive after 15:00",
                 "closed for lunch 12:00-13:00", "Open 08.00-16.00, ring at 07:30", "not at 12:00", "<12:00", "PO 1234 - 09:00"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
        assert PE.deadline(text) == "", (text, PE.deadline(text))
        assert PE.says_more(text) == [text], (text, PE.says_more(text))
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026\n  Site closes at 16:00"))
    assert row["delivery_time"] is None and any("Site closes at 16:00" in x for x in out), out


def test_a_second_line_of_times_competes_unless_it_is_about_something_else():
    assert PE.window("04/11/2026 from 09:00\nSite closes at 16:00") == ("09:00", "")
    assert PE.window("from 09:00\nfrom 13:00") == ("", "")
    assert PE.window("from 09:00 or from 13:00") == ("", "")
    assert PE.window("by 09:00 or by 12:00") == ("", "")


def test_a_year_is_not_a_time():
    for text, want in ((f"3rd November {Y} - 09:00 to 12:00", ("09:00", "12:00")), (f"2 September {Y} - 09:00", ("09:00", "")),
                       (f"3 Nov {Y} - 0900", ("09:00", "")), (f"November 3rd {Y} - 09:00", ("09:00", ""))):
        assert PE.window(text) == want, (text, PE.window(text))


def test_closing_words_are_a_deadline_or_an_end():
    for text in ("closes at 16:00", "close 16:00", "at 16:00 latest", "finish 16:00", "ends at 16:00", "to 16:00"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
        assert PE.deadline(text) == "16:00", (text, PE.deadline(text))
    for text in ("from 09:00 latest 12:00", "earliest 0900 latest 1200", "start 09:00 finish 12:00", "09:00 till 12:00",
                 "after 09:00 before 12:00", "not before 09:00, not after 12:00"):
        assert PE.window(text) == ("09:00", "12:00"), (text, PE.window(text))
        assert PE.deadline(text) == "", (text, PE.deadline(text))
    assert PE.window("not until 09:00") == ("09:00", "") and PE.deadline("not until 09:00") == ""


def test_either_end_of_the_day_is_not_guessed():
    for text in ("1:30-3:30pm", "2.00 - 4.00 pm", "at 2.30", "from 1.30", "after 3:30", "1:00-3:00", "from 2.11", "from 12.11",
                 "from 09:00 - 12", "from 9am to 5"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
        assert PE.says_more(text) == [text], (text, PE.says_more(text))
    for text, want in (("09:00:00 - 12:00:00", ("09:00", "12:00")), ("9:00-5:00pm", ("09:00", "17:00")),
                       ("11:30-1:30pm", ("11:30", "13:30")), ("from 8:30", ("08:30", "")), ("from 02:30", ("02:30", ""))):
        assert PE.window(text) == want, (text, PE.window(text))


def test_a_typed_midnight_is_told_when_the_upload_replaces_it():
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026, at 00:00"))
    assert any(x.startswith("!! delivery said 00:00") for x in out), out
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026, window 0000-0600"))
    assert (tr["delivery time"], tr["delivery time end"]) == ("04/11/2026 00:00", "04/11/2026 06:00"), tr
    assert not any("said" in x for x in out), out


def test_a_date_that_will_not_read_is_told_not_borrowed_in_silence():
    for typed in ("Sat 7th Nov 23:00", "03/11, window 0900-1200", "Tuesday 3rd"):
        row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am", f"Collection date: {typed}"))
        assert row["Collection Date"] is None, typed
        assert any(x.startswith("!! collection date could not be read") and "other leg's date" in x for x in out), out
    row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am", f"Collection date: 3 November {Y}, from 9am"))
    assert row["Customer Order No"] == f"AH3/11/{Y % 100}EHBB" and tr["collection time"] == f"03/11/{Y} 09:00", tr
    assert PE.first_date("Wed 4th Nov, 0900-1200") is None
    row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am\n", "").replace("Delivery date: 04/11/2026\n", ""))
    assert any("No date read on either leg" in x for x in out), out


def test_a_date_on_a_plain_label_is_not_the_site():
    row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am\nCollection address:",
                                        "Collection: 03/11/2026 from 9am"))
    assert row["Site Name - Collection"] == "Network Rail Telecom", row
    assert tr["collection time"] == "03/11/2026 09:00" and row["Customer Order No"] == "AH3/11/26EHBB", tr
    row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am\n", "")
                        .replace("Collection notes:", "Collection window: 03/11/2026 09:00-12:00\nCollection notes:"))
    assert (tr["collection time"], tr["collection time end"]) == ("03/11/2026 09:00", "03/11/2026 12:00"), tr


def test_counties_with_a_direction_leave_no_stray_letter():
    addr = lambda *lines: PE.address("\n".join(lines))
    for town, county, pc in (("Doncaster", "S Yorks", "DN5 9TH"), ("Leeds", "W. Yorks", "LS9 0DX"), ("Rhyl", "N Wales", "LL18 1AA"),
                             ("Grimsby", "North East Lincolnshire", "DN31 1AA"), ("Birmingham", "W Midlands", "B1 1AA"),
                             ("Hayes", "Middx", "UB3 1AA")):
        assert addr("Site", "1 High Road", town, county, pc) == ("Site", "1 High Road", "", town, pc), county
        assert addr("Site", "1 High Road", f"{town} {county}", pc)[3] == town, county


def test_a_place_named_for_a_county_keeps_its_name():
    addr = lambda *lines: PE.address("\n".join(lines))
    for town in ("New England", "Crook of Devon", "Little Scotland", "Little England", "Fort Cumberland", "Kingdom of Fife"):
        assert addr("Site", "1 High Road", town, "PE1 2PN")[3] == town, town
    assert addr("Site", "1 High Road", "Sabden, England", "BB7 9ED")[3] == "Sabden"


def test_a_postcode_shape_is_not_the_postcode():
    addr = lambda *lines: PE.address("\n".join(lines))
    told = []
    assert PE.address("\n".join(("Network Rail", "Wakefield Road", "Wakefield", "WF1 1AA", "Leave M1 2nd exit after J39")), told) == (
        "Network Rail", "Wakefield Road", "", "Wakefield", "WF1 1AA")
    assert told == ["Leave M1 2nd exit after J39"], told
    told = []
    assert PE.address("\n".join(("Site", "1 High Road", "Derby", "DE24 8HY", "Sat nav DE24 9ZZ")), told)[3:] == ("Derby", "DE24 8HY")
    assert told == ["Sat nav DE24 9ZZ"], told
    assert addr("Site", "Union Mill", "Unit B4 1st Floor, Sabden BB7 9ED")[3:] == ("Sabden", "BB7 9ED")
    assert addr("Site", "1 High Road", "Motherwell", "ML1 3ST")[3:] == ("Motherwell", "ML1 3ST")
    assert addr("Site", "1 High Road", "Motherwell ML1 3ST")[3:] == ("Motherwell", "ML1 3ST")


def test_the_county_comes_off_however_the_last_line_is_typed():
    addr = lambda *lines: PE.address("\n".join(lines))
    for lines in (("Site", "1 High Road", "Sabden", "Lancashire BB7 9ED"), ("Site", "1 High Road", "Sabden", "BB7 9ED, Lancashire"),
                  ("Site", "1 High Road", "Sabden", "BB7 9ED", "Lancashire"), ("Site", "1 High Road", "Sabden", "Postcode: BB7 9ED"),
                  ("Site", "1 High Road", "Sabden", "Post code BB7 9ED")):
        assert addr(*lines) == ("Site", "1 High Road", "", "Sabden", "BB7 9ED"), lines
    row, _ = job(COURIER.replace("  BB7 9ED\n", "  Postcode: BB7 9ED\n"))
    assert row["D Postcode"] == "BB7 9ED" and row["D Contact Name"] == "Chris De Clerk", row


def test_commas_split_before_the_town_is_chosen():
    addr = lambda *lines: PE.address("\n".join(lines))
    assert addr("Site", "Watt Street, Sabden", "Lancashire", "BB7 9ED") == ("Site", "Watt Street", "", "Sabden", "BB7 9ED")
    assert addr("Site", "Bideford Road, Newport", "NP20 3BG") == ("Site", "Bideford Road", "", "Newport", "NP20 3BG")
    assert addr("Site", "12, High Street", "Sabden", "BB7 9ED") == ("Site", "12 High Street", "", "Sabden", "BB7 9ED")
    assert addr("DAC Limited, Union Mill, Sabden, BB7 9ED") == ("DAC Limited", "Union Mill", "", "Sabden", "BB7 9ED")


def test_line_one_is_only_filled_from_a_place():
    addr = lambda *lines: PE.address("\n".join(lines))
    assert addr("DAC Limited", "Lancashire", "BB7 9ED") == ("DAC Limited", "", "", "Lancashire", "BB7 9ED")
    row, tr, out = said(COURIER.replace("  Union Mill\n  Watt Street\n  Sabden\n  Lancashire\n", "  Sabden\n"))
    assert row["D Address 1"] == row["D Address 3"] == "Sabden", row
    assert any(x.startswith("NOTE delivery gave one address line") for x in out), out
    assert addr("Site", "Union Mill", "Station Approach", "Lancashire", "BB7 9ED") == (
        "Site", "Union Mill", "Station Approach", "Lancashire", "BB7 9ED")


def test_map_references_ride_and_are_never_the_town():
    addr = lambda *lines: PE.address("\n".join(lines))
    assert addr("Site", "Union Mill", "Sabden", "W3W///filled.count.soap", "BB7 9ED") == (
        "Site", "Union Mill", "W3W///filled.count.soap", "Sabden", "BB7 9ED")
    assert addr("Site", "Union Mill", "Sabden", "///filled.count.soap", "BB7 9ED")[3] == "Sabden"
    told = []
    assert PE.address("\n".join(("Site", "Union Mill", "Sabden", "07700 900173", "BB7 9ED")), told)[3] == "Sabden"
    assert told == ["07700 900173"], told


def test_a_repeated_label_keeps_the_first_and_tells_the_second():
    row, meta = job(COURIER + "Item description: Half set switches - X2, 5.6 tonnes total\nCost centre: 999999\n")
    assert row["Cost Centre"] == "100001" and row["Product / Description"] == "Telephone spares", row
    assert any("item description (2): Half set switches" in x for x in meta["unread"]), meta
    assert any("cost centre (2): 999999" in x for x in meta["unread"]), meta
    row, meta = job(COURIER + "Delivery date: 05/11/2026\nDelivery address:\n  Other Ltd\n  1 High Road\n  Leeds\n  LS9 0DX\n")
    assert row["D Postcode"] == "BB7 9ED" and row["Delivery Date"].day == 4, row
    assert any("delivery address (2): Other Ltd" in x for x in meta["unread"]), meta
    row, _ = job(COURIER + "Collection notes: Gate 3 only\n")
    assert row["Notes for Collection Location Comments"].endswith("entrance Gate 3 only"), row


def test_what_runs_on_under_a_value_is_told_not_glued_on():
    row, meta = job(COURIER.replace("Raised by: Robin.Field@networkrail.co.uk",
                                    "Raised by: Robin.Field@networkrail.co.uk\nKind regards\nRobin Field"))
    assert row["Raised by"] == "Robin.Field@networkrail.co.uk", row
    assert "Kind regards" in meta["unread"] and "Robin Field" in meta["unread"], meta
    row, meta = job(COURIER.replace("10 Kg approx", "5.6 tonnes total\nHIAB will be required"))
    assert "HIAB will be required" in meta["unread"] and row["HIAB"] == "N", (row, meta)
    assert "Weight - 5.6 tonnes total" in row["Delivery Instructions"], row
    row, meta = job(COURIER.replace("Raised by: Robin.Field@networkrail.co.uk", "Raised by: Robin Field"))
    assert row["Raised by"] == "" and "raised by: Robin Field" in meta["unread"], (row, meta)


def test_only_whole_labels_belong_to_the_address():
    blocks = PE.read_blocks("Delivery address:\n  Site\n  Telephone: 01234 567890\n  Telford Depot: gate 2\n  Mobile crane on site: yes\n")
    assert blocks["delivery address"] == "Site\nTelephone: 01234 567890", dict(blocks)
    assert "telford depot" in blocks and "mobile crane on site" in blocks, dict(blocks)
    for lines in (("Contact: Robin Field", "Tel: 07700 900790"), ("Contact: Robin Field", "Mobile: 07700 900790"),
                  ("Contact name: Robin Field", "Contact number: 07700 900790")):
        assert PE.contacts("\n".join(lines)) == [("Robin Field", "07700 900790")], lines
    assert PE.contacts("Contact: A Person - 07700 900123\nContact: B Person - 07700 900124") == [
        ("A Person", "07700 900123"), ("B Person", "07700 900124")]


def test_a_closing_word_after_the_time_is_not_a_start():
    for text in ("4pm finish", "16:00 close", "17:00 end", "12:00 or before", "12:00 no later", "no later 12:00",
                 "earlier than 12:00", "before or at 12:00", "16:00 finish", "4pm close", "12:00 or earlier"):
        t = PE._clock(text)
        assert PE.window(text) == ("", ""), (text, PE.window(text))
        assert PE.deadline(text) == re.findall(r"\d\d:\d\d", t)[0], (text, PE.deadline(text))
    for text in ("no earlier than 9am", "not before 09:00", "12:00 or later", "9am start", "09:00 or after", "earliest 09:00"):
        assert PE.window(text)[0] and not PE.window(text)[1] and not PE.deadline(text), (text, PE.window(text))
    assert PE.window("08:00 start, 16:00 finish") == ("08:00", "16:00")
    assert PE.window("close 12:00-13:00") == ("", "") and PE.says_more("close 12:00-13:00") == ["close 12:00-13:00"]


def test_pm_on_the_end_of_a_range_alone_is_not_guessed():
    for text in ("10:00-11:30pm", "window 7:00-9:00pm", "8:00-10:00pm", "9.00-11.00pm", "from 7:00 to 9:00pm", "between 8:00 and 10:00pm"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
        assert PE.says_more(text) == [text], (text, PE.says_more(text))
    for text, want in (("9:00-5:00pm", ("09:00", "17:00")), ("8:00-4:30pm", ("08:00", "16:30")), ("7:00-7:00pm", ("07:00", "19:00")),
                       ("8pm-10pm", ("20:00", "22:00")), ("08:00-10pm", ("08:00", "22:00")), ("20:00-22:00", ("20:00", "22:00")),
                       ("10:00am-11:30pm", ("10:00", "23:30"))):
        assert PE.window(text) == want, (text, PE.window(text))


def test_a_second_date_or_a_limit_on_a_date_is_told():
    for typed in ("before 06/11/2026", "after 06/11/2026", "by 06/11/2026", "no later than 06/11/2026", "06/11/2026 latest",
                  "04/11/2026 or 05/11/2026", "from 04/11/2026 to 06/11/2026", "04/11/2026 - 06/11/2026"):
        row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", f"Delivery date: {typed}"))
        assert row["Delivery Date"] is not None, typed
        assert any("Not read" in x and typed in x for x in out), (typed, out)
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026\n  05/11/2026"))
    assert any("Not read" in x and "05/11/2026" in x for x in out), out
    for quiet in ("on 04/11/2026", "Wed 04/11/2026", "04/11/2026 by 12:00", "04/11/2026 latest 12:00"):
        assert PE.says_more(quiet) == [], quiet
    assert PE.window("03/11/2026 09:00 to 04/11/2026 16:00") and PE.says_more("03/11/2026 09:00 to 04/11/2026 16:00")


def test_a_rival_time_is_told_and_ampersand_reads_as_and():
    assert PE.window("04/11/2026, between 09:00 & 12:00") == ("09:00", "12:00")
    assert PE.says_more("04/11/2026, between 09:00 & 12:00") == []
    for typed in ("04/11/2026, window 0900-1200 or 1300-1500", "04/11/2026 window 0900-1200 by 11:00", "04/11/2026, 09:00 or 14:00",
                  "04/11/2026, 08:00-12:00 and 13:00-16:00"):
        assert PE.says_more(typed) == [typed], (typed, PE.says_more(typed))
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026, 09:00 or 14:00"))
    assert any(x.startswith("NOTE delivery window not read") for x in out), out
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026 window 0900-1200\nDelivery time: 14:00"))
    assert (tr["delivery time"], tr["delivery time end"]) == ("04/11/2026 09:00", "04/11/2026 12:00"), tr
    assert any("Not read" in x and "14:00" in x for x in out), out


def test_a_year_that_is_a_time_or_a_dropped_digit_is_not_a_date():
    for typed in ("Sat 7th Nov 2030", "Sat 7th Nov 2000", "04/11/202", "04/11/1926"):
        assert PE.first_date(typed) is None, typed
        row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", f"Delivery date: {typed}"))
        assert row["Delivery Date"] is None and any("date could not be read" in x for x in out), (typed, out)
    row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am", "Collection date: 03/11/202"))     # used to crash
    assert row["Collection Date"] is None and any("collection date could not be read" in x for x in out), out


def test_the_other_legs_time_does_not_land_on_this_leg():
    row, tr, out = said(COURIER.replace("Collection date: 03/11/2026, from 9am", "Collection date: 03/11/2026 for delivery on 04/11/2026 at 14:00"))
    assert row["collection_time"] is None and any("Not read" in x and "at 14:00" in x for x in out), out
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026, ready for collection from 07:00"))
    assert row["delivery_time"] is None and any("Not read" in x and "07:00" in x for x in out), out
    row, _ = job(COURIER.replace("Collection date: 03/11/2026, from 9am", "Collection date: 03/11/2026, ready for collection from 9am"))
    assert row["collection_time"].hour == 9, row
    row, _ = job(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: 04/11/2026, for delivery at 14:00"))
    assert row["delivery_time"].hour == 14, row


def test_a_date_against_its_own_words_is_told():
    assert PE.date_doubts("Tuesday 04/11/2026", datetime(2026, 11, 4)) [-1:] == ["04/11/2026 is a Wednesday, the email says Tuesday"]
    assert any("is in the past" in x for x in PE.date_doubts("03/11/25", datetime(2025, 11, 3)))
    assert not [x for x in PE.date_doubts("Wednesday 04/11/2026", datetime(2026, 11, 4)) if "the email says" in x]
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", "Delivery date: Tuesday 04/11/2026"))
    assert any(x.startswith("!! delivery date: 04/11/2026 is a Wednesday") for x in out), out


SIGNATURE = """
Kind regards

Robin Field
Network Rail
The Quadrant
Elder Gate
Milton Keynes
MK9 1EN
Mobile: 07700 900790
"""


def test_a_signature_is_not_the_address():
    last = """Cost centre: 100001
Item description: Box - X1, 10 Kg
Collection date: 03/11/2026
Collection address:
  Site
  1 High Road
  Edinburgh
  EH1 1BB
  Contact: Robin Field - 07700900790
Delivery date: 04/11/2026
Delivery address:
  DAC Limited
  Union Mill
  Sabden, Lancashire BB7 9ED
  Contact: Chris De Clerk
"""
    row, meta = job(last + SIGNATURE)
    assert row["D Postcode"] == "BB7 9ED" and row["D Address 3"] == "Sabden", row
    assert row["Customer Order No"] == "AH3/11/26EHBB", row
    assert row["D Telephone No"] == "", row                     # not the requester's own mobile
    assert "MK9 1EN" in meta["unread"] and "Kind regards" in meta["unread"], meta
    # no postcode in the address: blank, not the signature's, so the run refuses
    row, meta = job(last.replace("Sabden, Lancashire BB7 9ED", "Sabden") + SIGNATURE)
    assert row["D Postcode"] == "", row
    # a double-spaced address still reads to its end
    row, _ = job(COURIER.replace("  Union Mill\n", "\n  Union Mill\n\n").replace("  Sabden\n", "  Sabden\n\n"))
    assert row["D Postcode"] == "BB7 9ED" and row["D Address 1"] == "Union Mill", row
    # and a note
    row, meta = job(COURIER + "Delivery notes: Ring Chris first\n\nMany thanks\nRobin\n")
    assert row["Notes for Delivery Location Comments"].startswith("Ring Chris first."), row
    assert "Many thanks" in meta["unread"], meta


def test_what_sits_beside_the_postcode_is_not_the_town():
    addr = lambda line: PE.address("\n".join(("Site", "Bideford Road", "Newport", line)))
    for line in ("NP20 3BG.", "(NP20 3BG)", "NP20 3BG - 01633 123456", "Sat Nav NP20 3BG", "PC: NP20 3BG", "Nearest postcode NP20 3BG", "NP20 3BG (nearest)"):
        assert addr(line) == ("Site", "Bideford Road", "", "Newport", "NP20 3BG"), (line, addr(line))
    told = []
    PE.address("\n".join(("Site", "Chathill", "Nearest postcode NE67 5DE")), told)
    assert told == ["Nearest postcode NE67 5DE"], told
    assert PE.address("Site\nBideford Road\nNewport - NP20 3BG")[3] == "Newport"
    assert PE.address("Site\nBideford Road\nNewport NP20 3BG.")[3] == "Newport"
    # the last of two on a line, and one above is told
    told = []
    assert PE.address("Site\nBideford Road\nNewport\nSat nav NP20 9ZZ\nNP20 3BG", told)[4] == "NP20 3BG"
    assert told == ["Sat nav NP20 9ZZ"], told


def test_a_road_and_a_distance_is_not_a_postcode():
    assert PE.address("Network Rail - Chathill LC\nChathill\nOff A1 5km north of Alnwick")[4] == ""
    assert PE.address("Site\nOff M1 8am-4pm\nLeeds\nLS9 0DX")[3:] == ("Leeds", "LS9 0DX")
    assert PE.address("Site\nGate A1 5pm close\nGateshead NE11 0JY")[3:] == ("Gateshead", "NE11 0JY")
    row, tr, out = said(COURIER.replace("  BB7 9ED\n", "  N1C 4AH\n"))
    assert any(x.startswith("!! delivery postcode N1C 4AH is not in the region list") for x in out), out


def test_more_county_spellings():
    addr = lambda *lines: PE.address("\n".join(lines))
    for town, county in (("Middlesbrough", "Cleveland"), ("Scunthorpe", "South Humberside"), ("Bristol", "Avon"), ("Manchester", "Gtr Manchester"),
                         ("Leeds", "W.Yorks"), ("Newcastle", "Tyne&Wear"), ("Ferryhill", "Co.Durham"), ("Cheadle Hulme", "Cheshire East"),
                         ("Abercynon", "Rhondda Cynon Taf"), ("Inverness", "Highlands"), ("Thirsk", "Nth Yorkshire"), ("Ebbw Vale", "Blaenau Gwent")):
        assert addr("Site", "1 High Road", town, county, "LS9 0DX")[3] == town, county
    for town in ("Stratford upon Avon", "Bradford on Avon", "Redcar and Cleveland"):
        assert addr("Site", "1 High Road", town, "LS9 0DX")[3] == town, town


def test_a_town_that_is_probably_not_one_is_pointed_out():
    for block_lines in ("  Unit 5\n  Pantglas Industrial Estate\n", "  Gate 3\n  Tyne Yard\n", "  Union Mill\n  Lancashire Way\n"):
        row, tr, out = said(COURIER.replace("  Union Mill\n  Watt Street\n  Sabden\n  Lancashire\n", block_lines))
        assert any(x.startswith("NOTE delivery gave one address line or no town") for x in out), (block_lines, out)
    row, tr, out = said(COURIER)
    assert not any("no town" in x for x in out), out
    told = []
    assert PE.address("Site\nUnion Mill\nSabden\nTel 01633 123456\nRobin@networkrail.co.uk\nBB7 9ED", told)[3] == "Sabden"
    assert told == ["Tel 01633 123456", "Robin@networkrail.co.uk"], told


def test_no_line_is_lost():
    assert PE.contacts("Contact: Jo Colleague - 07700 900 257\nTel: 01633 123456") == [("Jo Colleague", "07700 900 257"), ("", "01633 123456")]
    assert PE.contacts("Contact: Jo Colleague\nTel: 01633 123456\nMobile: 07700 900 257") == [("Jo Colleague", "01633 123456"), ("", "07700 900 257")]
    row, _ = job(COURIER.replace("  Contact: Chris De Clerk - 07700 900838 / Sue Other - 07700 900123",
                                 "  Contact: Chris De Clerk - 07700 900838\n  Tel: 01633 123456"))
    assert row["Notes for Delivery Location Comments"] == "Also 01633 123456", row
    assert PE.address("Network Rail: Ebbw Junction Depot\nBideford Road\nNewport\nNP20 3BG") == (
        "Network Rail: Ebbw Junction Depot", "Bideford Road", "", "Newport", "NP20 3BG")
    assert PE.address("12, High Street, Sabden, BB7 9ED")[0] == "12 High Street"


def test_a_when_on_a_plain_label_is_told_not_the_site():
    head = "Collection date: 03/11/2026, from 9am\nCollection address:"
    row, tr, out = said(COURIER.replace(head, "Collection: Tues 3rd Nov from 9am"))
    assert row["Site Name - Collection"] == "Network Rail Telecom", row
    assert any(x.startswith("!! collection date could not be read: Tues 3rd Nov from 9am") for x in out), out
    row, tr, out = said(COURIER.replace(head, "Collection date: 03/11/2026\nCollection: from 9am"))
    assert row["Site Name - Collection"] == "Network Rail Telecom" and tr["collection time"] == "03/11/2026 09:00", row
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026\nDelivery address:", "Delivery date: 04/11/2026\nDelivery: ASAP"))
    assert row["Delivery Point"] == "DAC Limited" and any("Not read" in x and "ASAP" in x for x in out), (row, out)
    row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026\nDelivery address:", "Delivery date: 04/11/2026\nDelivery: 04/11/2026, by 12:00"))
    assert any(x.startswith("!! delivery must be done by 12:00") for x in out), out
    # names that only look like it stay the site
    for name in ("DAC Limited", "March", "The Close"):
        assert PE.when_on_label(f"{name}\nUnion Mill") == ("", f"{name}\nUnion Mill"), name


def test_the_desks_flags_read_a_worded_date_and_refuse_a_bad_one():
    flags = lambda v: (lambda r: (PW.apply_overrides(r, {"delivery": v}, read_window=PE.window, read_date=PE.first_date), r))(job(COURIER)[0])
    used, row = flags(f"5 November {Y} from 10am")
    assert row["Delivery Date"] == datetime(Y, 11, 5) and row["delivery_time"].hour == 10, row
    used, row = flags("from 10am")                              # a time on its own keeps the job's date
    assert row["Delivery Date"].day == 4 and row["delivery_time"].hour == 10, row
    for bad in ("Tues 5th Nov from 10am", "5 Nov", "tbc", "04/11/202 from 10am"):
        used, row = flags(bad)
        assert used == [] and row["Delivery Date"].day == 4, (bad, used, row)


def test_an_unknown_sign_off_cannot_lend_its_postcode_in_silence():
    last = """Collection date: 03/11/2026
Collection address:
  Site
  1 High Road
  Edinburgh
  EH1 1BB
  Contact: Robin Field - 07700900790
Delivery date: 04/11/2026
Delivery address:
  DAC Limited
  Union Mill
  Sabden
  Contact: Chris De Clerk
"""
    tail = "{}\nRobin Field\nNetwork Rail\nMilton Keynes\nMK9 1EN\n"
    for off in ("Rgds", "Kindest regards", "With kind regards", "Regds", "KR", "BR", "Best", "Thx", "Ta"):
        row, _ = job(last + "\n" + tail.format(off))
        assert row["D Postcode"] == "", (off, row)              # blank, so the run refuses
    for off in ("All the best", "Speak soon"):
        row, _ = job(last + "\n" + tail.format(off))            # a blank line under the contact ends the address
        assert row["D Postcode"] == "", (off, row)
        row, tr, out = said(last + tail.format(off))            # no blank line, no sign-off it knows: read, and pointed out
        assert row["D Postcode"] == "MK9 1EN" and any(x.startswith("!! delivery postcode MK9 1EN sits below") for x in out), out
    row, tr, out = said(COURIER)
    assert not any("sits below" in x for x in out), out


def test_another_day_in_ordinals_or_by_name_is_told():
    for typed in ("4th to 6th November 2026", "4th Nov - 6th Nov 2026", "between 4th and 6th November 2026", "04/11/2026 or 5th November",
                  "04/11/2026 or the 5th", "4th or 5th November 2026, 0900-1200"):
        row, tr, out = said(COURIER.replace("Delivery date: 04/11/2026", f"Delivery date: {typed}"))
        assert any("Not read" in x and typed in x for x in out), (typed, out)
    assert PE.says_more("03/11/2026 09:00 to 16:00 on the 4th")
    # a window ending on another named day: told, the planner corrects the close
    assert PE.says_more("Sat 07/11/2026 23:00 to Mon 05:00") == ["Sat 07/11/2026 23:00 to Mon 05:00"]
    assert PE.says_more("Sat 07/11/2026 06:00 - Sun 18:00") == ["Sat 07/11/2026 06:00 - Sun 18:00"]
    assert PE.says_more("Sat 07/11/2026 06:00-14:00") == [] and PE.says_more("Tues 03/11/2026") == []


def test_a_date_limit_however_it_is_put_is_told():
    for typed in ("before the 6th November 2026", "by the 6th November 2026", "no later than the 6th November 2026", "06/11/2026 or earlier",
                  "06/11/2026 or before", "06/11/2026 or later", "06/11/2026 or after", "by end of 06/11/2026", "before close 06/11/2026",
                  "end of 06/11/2026", "by close 06/11/2026", "before Friday the 06/11/2026", "06/11/2026 at the earliest"):
        assert PE.says_more(typed) == [typed], typed
    for quiet in ("on 04/11/2026", "04/11/2026 by 12:00", "04/11/2026 latest 12:00"):
        assert PE.says_more(quiet) == [], quiet


def test_two_limits_are_not_paired_backwards():
    for text in ("before 07:00 or after 19:00", "after 19:00 or before 07:00", "19:00 finish, 07:00 start", "19:00 latest, 07:00 earliest",
                 "18:00 close, 06:00 open", "by 12:00 or 13:00", "7:00-7:00", "7am-7am", "window 0900-0900", "16:00 finish, 08:00 start"):
        assert PE.window(text) == ("", ""), (text, PE.window(text))
    assert PE.says_more("before 07:00 or after 19:00") == ["before 07:00 or after 19:00"]
    assert PE.window("09:00 or later, 12:00 latest") == ("09:00", "12:00")
    assert PE.window("after 19:00, before 07:00") == ("19:00", "07:00")     # a night
    assert PE.window("07:00 start, 19:00 finish") == ("07:00", "19:00")


def test_the_county_list_is_clean():
    assert not any(c != c.strip().lower() or "\n" in c or not c for c in PE.COUNTIES)
    assert {"lancashire", "yorkshire", "fife", "powys", "isle of wight"} <= PE.COUNTIES
    assert not PE.ALSO_TOWNS & PE.COUNTIES


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print(f"{len(tests)}/{len(tests)} passed")
