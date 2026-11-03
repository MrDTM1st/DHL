"""The home PC's part of the order panel's Book (02/11): what stops a booking first, the DigiHaul row and the checks on it, the site's
email, the carrier codes. Made-up orders and hauliers only.

    python tests/test_book_run.py
"""
import os
import sys
from datetime import datetime

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import book_run as B  # noqa: E402
import carriers  # noqa: E402

NOW = datetime(2026, 11, 2, 15, 0)
TRIP = {"manifest": "MAN-01000001", "cost": "450.00", "revenue": "600", "collect": "06/11/26 07:30", "deliver": "06/11/26 08:30"}


def _sheet(row_top=807, row_bottom=831, filled=(), above=True, picked_head=True, wide=True):
    """The tracker as the work PC pictures it: the cursor's row number highlighted, and whichever yellow cells hold something."""
    im = Image.new("RGB", (1910 if wide else 900, 915), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 358, 64, 831), fill=(245, 245, 245))
    d.rectangle((0, row_top, 64, row_bottom), fill=B.PICKED)
    d.rectangle((B.HEAD_B - 20, B.HEAD_Y - 8, B.HEAD_B + 20, B.HEAD_Y + 8), fill=B.PICKED if picked_head else (245, 245, 245))
    if above:
        d.rectangle((170, row_top - 16, 290, row_top - 6), fill=(0, 0, 0))
    for c in filled:
        xs = B.CELL_B if c == "B" else B.CELLS[c]
        d.rectangle((xs[0] + 20, row_top + 6, xs[0] + 60, row_bottom - 6), fill=(0, 0, 0))
    return im


def test_the_first_empty_row_under_the_last_manifest_reads_as_blank():
    assert B.row_state(_sheet()) == {"blank": True, "above": True}


def test_a_colleagues_half_typed_row_isnt_blank_with_its_manifest_still_empty():
    assert B.row_state(_sheet(filled="CDE"))["blank"] is False


def test_a_row_with_no_manifest_above_it_is_not_where_the_list_ends():
    assert B.row_state(_sheet(above=False))["above"] is False


def test_a_sheet_left_scrolled_sideways_means_no_telling():
    im = _sheet()
    ImageDraw.Draw(im).rectangle((70, B.HEAD_Y - 8, 297, B.HEAD_Y + 8), fill=B.PICKED)     # column C's heading where B's belongs
    assert B.row_state(im) is None


def test_the_cursor_not_plainly_on_column_b_means_no_telling():
    assert B.row_state(_sheet(picked_head=False)) is None
    assert B.row_state(_sheet(wide=False)) is None
    assert B.row_state(Image.new("RGB", (1910, 915), (255, 255, 255))) is None


def test_a_pasted_row_shows_in_every_yellow_cell_but_the_notes():
    assert B.row_filled(_sheet(filled="BCDEG")) is True
    assert B.row_filled(_sheet(filled="BCDE")) is False


def test_the_tracker_row_is_the_yellow_cells_in_their_order_with_notes_blank():
    assert B.row_text(TRIP, "ACME_DH", NOW) == "MAN-01000001\tACME_DH\t450.00\tDelali\t\tN"
    soon = dict(TRIP, collect="03/11/26 08:00")
    assert B.row_text(soon, "ACME_DH", NOW).endswith("\tY")


def test_urgent_is_collecting_today_or_tomorrow_morning():
    assert B.is_urgent("02/11/26 16:00", NOW) is True
    assert B.is_urgent("03/11/26 11:59", NOW) is True
    assert B.is_urgent("03/11/26 12:00", NOW) is False
    assert B.is_urgent("04/11/26 08:00", NOW) is False
    assert B.is_urgent("", NOW) is False


def test_an_update_or_booking_item_on_the_to_do_stops_it_a_note_doesnt():
    items = [{"kind": "note", "orders": ["9100001"], "what": "Add a note"},
             {"kind": "update", "orders": ["9100002"], "what": "Update 9100002"},
             {"kind": "booking", "orders": ["9100003-1-1"], "what": "Add NIGHT before it's booked"}]
    assert B.owed_first(["9100001"], items) == []
    assert [i["what"] for i in B.owed_first(["9100002-1-1"], items)] == ["Update 9100002"]
    assert [i["what"] for i in B.owed_first(["9100003"], items)] == ["Add NIGHT before it's booked"]
    assert B.owed_first(["9100009"], items) == []


def test_a_haulier_is_never_taken_for_the_site_on_a_mail_with_the_order_in_its_subject():
    site = "9100001 example yard en1 1aa"
    args = dict(orders=["9100001"], site_topic=site, contact="site@example.net", not_site={"ops@acme-haulage.example"})
    assert B.site_rank("RE: 9100001 Example Yard EN1 1AA", {"site@example.net"}, **args) == 2
    assert B.site_rank("RE: 9100001 Other words", {"site@example.net"}, **args) == 1          # only the contact says so
    assert B.site_rank("9100001 Delivery", {"ops@acme-haulage.example"}, **args) == 0         # a cover request
    assert B.site_rank("9100001 Delivery", {"someone@else.example"}, **args) == 0
    assert B.site_rank("9100001 Yard - alternative contact needed", {"site@example.net"}, **args) == 0
    assert B.site_rank("RE: other words", {"x@y.example"}, orders=["9100001"], site_topic=site, contact="site@example.net",
                       conv="C1", thread_conv="C1") == 2                                      # our first email's own thread


def test_the_site_email_is_his_wording_with_the_window_and_no_price():
    rec = {"details": {"time": {"earliest": "08:00", "latest": "12:00"}}}
    text = B.words("Sam", "ACME_DH", "Acme Haulage", "06/11/2026", [TRIP], rec)
    assert "Hi Sam," in text and "This order has been arranged with Acme Haulage for Friday 06/11/2026" in text
    assert "Thanks. This order" in B.words("Sam", "ACME_DH", "Acme Haulage", "06/11/2026", [TRIP], rec, thanks=True)
    assert "delivering between 08:30 and 12:00" in text and "Here is the ref number MAN-01000001" in text
    assert "450" not in text


def test_our_own_fleet_and_several_lorries_read_as_he_writes_them():
    rec = {"details": {"time": {"earliest": "08:30"}}}
    two = [TRIP, dict(TRIP, manifest="MAN-01000002")]
    text = B.words("", "DHL_NOC", "DHL NOC", "06/11/2026", two, rec)
    assert "Hi there," in text and "our own DHL fleet" in text and "delivering from 08:30" in text
    assert "It will come on two lorries. Here are the ref numbers: MAN-01000001 and MAN-01000002" in text


def test_a_reply_greets_the_name_the_order_has_for_its_contact_never_himself():
    rec = {"to": "christopher.j@example.net", "name": "Chris"}
    assert B.greeting("Christopher J", "Christopher.J@example.net", rec) == "Chris"     # theirs: as he knows them
    assert B.greeting("Delali Opoku", "/O=EXCHANGELABS/CN=X", rec) == "Chris"           # the newest mail is his own
    assert B.greeting("Ray Ellis", "ray@example.net", rec) == "Ray"                     # a colleague answered
    assert B.greeting("Delali Opoku", "/O=EXCHANGELABS/CN=X", {"to": "x@example.net"}) == ""


def test_a_reply_has_to_reach_the_contact():
    assert B.reaches(["sam.smith@example.net", "other@example.net"], "Sam.Smith@example.net")
    assert B.reaches(["sam.smith3@example.net"], "sam.smith@example.net")                 # the order's is a letter out
    assert not B.reaches(["materials.team@example.net"], "sam.smith@example.net")
    assert B.reaches(["anyone@example.net"], "")


def test_ourselves_and_the_dhl_road_mailbox_never_stay_on_a_site_email():
    assert B.left_off_site("me@example.net", "me@example.net")
    assert B.left_off_site("dhlroad@example.net", "me@example.net")
    assert B.left_off_site("zx-dhlroad", "me@example.net")
    assert not B.left_off_site("site@example.net", "me@example.net")


def test_a_forwarded_request_finds_its_contact_in_the_chain_it_quotes():
    chain = ("From: Sam Jones <Sam.Jones@example.net>\r\nTo: Pat Lee ((She,Her)) <Pat.Lee@example.net <mailto:Pat.Lee@example.net> >; "
             "Team <team@example.net>\r\nCc: Christopher Doe <Christopher.Doe@example.net>\r\n")
    assert B.address_in_text(chain, ["chris", "doe"]) == "christopher.doe@example.net"     # he's known by the short name
    assert B.address_in_text(chain, ["pat", "lee"]) == "pat.lee@example.net"
    assert B.address_in_text(chain, ["alex", "doe"]) == ""


def test_parcel_pass_gets_the_manifest_and_the_job_and_is_never_asked_for_an_eta():
    rec = {"site": "Example Depot", "postcode": "EN1 1AA", "collection_site": "Example Store", "collection_pc": "EN2 2BB",
           "details": {"time": {"latest": "14:00"}, "collection_time": {"latest": "08:30"},
                       "contact": {"name": "Sam Jones", "phone": "07700 900000"}}}
    trip = dict(TRIP, collect="06/11/26 07:30", deliver="07/11/26 13:00")
    text = B.pass_words("Pat", [trip], rec)
    assert "Hi Pat," in text and "Here's the manifest number: MAN-01000001" in text
    assert "Collection: Friday 06/11/2026 between 07:30 and 08:30, Example Store EN2 2BB" in text
    assert "Delivery: Saturday 07/11/2026 between 13:00 and 14:00, Example Depot EN1 1AA" in text
    assert "Site contact: Sam Jones 07700 900000" in text
    assert "ETA" not in text


def test_the_checks_on_parcel_pass_s_email_before_it_goes():
    good = ["nr@passlogistics.co.uk"]
    assert B.pass_checks("Here's the manifest number: MAN-01000001", [TRIP], good) == []
    assert B.pass_checks("MAN-01000001", [TRIP], ["site@example.net"])
    assert B.pass_checks("nothing", [TRIP], good)
    assert B.pass_checks("MAN-01000001 send me the ETA", [TRIP], good)
    assert B.pass_greeting("Pat Smith") == "Pat" and B.pass_greeting("NR") == ""


def test_who_is_greeted():
    assert B.first_name("Blake, Steven") == "Steven"
    assert B.first_name("Steven Blake") == "Steven"
    assert B.first_name("") == ""
    assert B.first_name("07700 900000") == ""


def test_the_checks_on_a_site_email_before_it_goes():
    ok = "Hi Sam, Here is the ref number MAN-01000001"
    assert B.checks(ok, [TRIP], ["site@example.net"], {"ops@acme-haulage.example"}) == []
    assert "nobody to send it to" in B.checks(ok, [TRIP], [], set())
    assert "a haulier is on it" in B.checks(ok, [TRIP], ["ops@acme-haulage.example"], {"ops@acme-haulage.example"})
    assert any("missing" in x for x in B.checks("Hi Sam", [TRIP], ["a@b.example"], set()))
    assert "a price slipped in" in B.checks(ok + " £450", [TRIP], ["a@b.example"], set())


def test_a_haulier_is_booked_under_its_digihaul_code_where_ctms_has_one():
    codes = ["ACME", "ACME_DH", "BRAVO", "CHARLIE_T_DH", "DELTA", "DELTA_HAUL_DH", "ECHO"]
    assert carriers.match("ACME", codes) == "ACME_DH"
    assert carriers.match("C_HARLIE_T", codes) == "CHARLIE_T_DH"          # however the list punctuates it
    assert carriers.match("BRAVO", codes) == "BRAVO"                      # no DigiHaul one
    assert carriers.match("DELTA_HAUL", codes) == "DELTA_HAUL_DH"
    assert carriers.match("ECHO", codes) == "ECHO"
    assert carriers.match("", codes) == "" and carriers.match("NOBODY", codes) == ""


def test_his_map_comes_first_then_the_match_then_what_the_contact_list_has():
    data = {"codes": ["ACME_DH"], "book": {"Foxtrot Ltd": "FOX_DH"}}
    assert carriers.book_code({"name": "Foxtrot Ltd", "ctms": "FOXTROT"}, data) == "FOX_DH"
    assert carriers.book_code({"name": "Acme Haulage", "ctms": "ACME"}, data) == "ACME_DH"
    assert carriers.book_code({"name": "Golf", "ctms": "GOLF"}, data) == "GOLF"
    assert carriers.book_code({"name": "Hotel"}, data) == ""


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
