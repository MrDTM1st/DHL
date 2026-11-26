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


def _sheet(row_top=807, row_bottom=831, filled=(), above=True, picked_head=True, wide=True, size=None, name="B6",
           formula="MAN-01000000"):
    """The tracker as the work PC pictures it: the cursor's row number highlighted, and whichever yellow cells hold something;
    over them the Name Box's text and the formula bar's, each as long as its words."""
    im = Image.new("RGB", size or (1910 if wide else 900, 915), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((B.NAME_AT[0] + 4, 245, B.NAME_AT[0] + 4 + 9 * len(name), 257), fill=(30, 30, 30))
    if formula:
        d.rectangle((305, 245, 305 + 9 * len(formula), 257), fill=(30, 30, 30))
    d.rectangle((0, 358, 64, 831), fill=(245, 245, 245))
    d.rectangle((0, row_top, 64, row_bottom), fill=B.PICKED)
    d.rectangle((B.HEAD_B - 20, B.HEAD_Y - 8, B.HEAD_B + 20, B.HEAD_Y + 8), fill=B.PICKED if picked_head else (245, 245, 245))
    if above:
        d.rectangle((170, row_top - 16, 290, row_top - 6), fill=(0, 0, 0))
    for c in filled:
        xs = B.CELL_B if c == "B" else B.CELLS[c]
        d.rectangle((xs[0] + 20, row_top + 6, xs[0] + 60, row_bottom - 6), fill=(0, 0, 0))
    return im


def test_the_sheet_reads_the_same_in_the_narrower_taller_window():
    big = (1709, 1275)
    assert B.row_state(_sheet(size=big)) == {"blank": True, "above": True}
    assert B.row_state(_sheet(row_top=1100, row_bottom=1124, size=big)) == {"blank": True, "above": True}    # lower down
    assert B.row_state(_sheet(filled="CDE", size=big))["blank"] is False
    assert B.row_filled(_sheet(filled="BCDE", size=big)) is True                                             # G is off it
    assert B.row_filled(_sheet(filled="BCD", size=big)) is False
    assert B.row_state(_sheet(size=(1200, 915))) is None                                                     # too narrow to tell


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


class _Tracker:
    """The work PC as tracker_rows works it: the sheet's picture after each move, the paste, the look after it. typed_in:
    where the typed address goes - "name" (the Name Box), "cell" (24/11: the selected cell) or "nowhere"."""

    def __init__(self, out, fail="", typed_in="name"):
        self.OUT, self.fail, self.pasted, self.typed_in, self.batches = out, fail, [], typed_in, []

    def ask(self, action, **args):
        if action == "paste":
            self.pasted.append(args["text"])
        if action == "use" and args.get("target") == "ctms" and self.fail == "use":
            raise RuntimeError("Could not reach the dashboard")
        return {"ok": True}, {}

    def send_batch(self, name, steps):
        self.batches.append((name, steps))
        if name == "tracker-check" and self.fail == "check":
            raise RuntimeError("Could not reach the dashboard")
        if name == "tracker-escape" and self.fail == "escape":
            return 1
        if name == "tracker-address":
            im = {"name": _sheet(name=B.SHEET_END), "cell": _sheet(formula=B.SHEET_END), "nowhere": _sheet()}[self.typed_in]
        else:
            im = _sheet(filled="BCDEG" if self.pasted else ())
        im.save(os.path.join(self.OUT, "latest.png"))
        return 0

    def save_state(self, payload):
        pass


def test_a_row_pasted_is_counted_even_when_the_look_after_it_fails(tmp_path):
    R = _Tracker(str(tmp_path), fail="check")
    n, why = B.tracker_rows(R, [TRIP], "ACME_DH", NOW)
    assert n == 1 and len(R.pasted) == 1 and "check it by eye" in why
    R = _Tracker(str(tmp_path), fail="use")                  # CTMS's window not brought back after it
    assert B.tracker_rows(R, [TRIP], "ACME_DH", NOW) == (1, "") and len(R.pasted) == 1


class _Walk(_Tracker):
    """The tracker step by step: each move's picture in turn, every batch kept."""

    def __init__(self, out, sheets, **kw):
        super().__init__(out, **kw)
        self.sheets = list(sheets)

    def send_batch(self, name, steps):
        if name != "tracker-row":
            return super().send_batch(name, steps)
        self.batches.append((name, steps))
        self.sheets.pop(0).save(os.path.join(self.OUT, "latest.png"))
        return 0


def test_the_row_is_found_from_column_bs_end_whatever_row_the_view_was_left_on(tmp_path):
    # 23/11: the view opened on the last filled row, the old click + Ctrl+Down ran off to row 1048576 and the row went on
    # by hand. Now: the Name Box to B's last row, Ctrl+Up to the last manifest, Down - no Ctrl+Down at all.
    R = _Walk(str(tmp_path), [_sheet()])
    assert B.tracker_rows(R, [TRIP], "ACME_DH", NOW) == (1, "") and len(R.pasted) == 1
    (n1, box), (n2, address), (n3, row) = R.batches[:3]
    assert n1 == "tracker-name-box" and [s for s in box if s["action"] == "click"] == [{"action": "click", "px": B.NAME_BOX}] * 2
    assert [s["key"] for s in box if s["action"] == "key"] == ["ctrl+a"] and not any(s["action"] == "type" for s in box)
    assert n2 == "tracker-address" and [s.get("text") for s in address if s["action"] != "wait"] == [B.SHEET_END]
    assert n3 == "tracker-row" and [s["key"] for s in row if s["action"] == "key"] == ["enter", "ctrl+up", "down"]


def test_an_address_that_lands_in_a_cell_is_escaped_and_never_entered(tmp_path):
    # 24/11, 09:15: right after Edge switched to the tracker's tab the Name Box click didn't take, and "B1048576" + Enter
    # went into the selected cell - over a colleague's manifest (put back with Ctrl+Z). The formula bar changing gives it
    # away before any Enter: Escape throws the typing away, and nothing more is done.
    for where in ("cell", "nowhere"):
        R = _Walk(str(tmp_path), [_sheet()], typed_in=where)
        n, why = B.tracker_rows(R, [TRIP], "ACME_DH", NOW)
        assert n == 0 and R.pasted == [] and "thrown away with Escape - nothing written" in why
        names = [name for name, _ in R.batches]
        assert names == ["tracker-name-box", "tracker-address", "tracker-escape"]        # no Enter, no tracker-row
        assert R.batches[-1][1][0] == {"action": "key", "key": "escape"}
        assert not any(s.get("key") == "enter" for _, steps in R.batches for s in steps)


def test_an_escape_that_doesnt_go_says_to_look_at_the_tracker_now(tmp_path):
    R = _Walk(str(tmp_path), [_sheet()], typed_in="cell", fail="escape")
    n, why = B.tracker_rows(R, [TRIP], "ACME_DH", NOW)
    assert n == 0 and why.startswith("LOOK AT THE TRACKER NOW") and B.SHEET_END in why


def test_the_name_box_is_told_from_a_cell_by_what_changed_on_the_picture():
    for size in ((1910, 915), (1709, 1275)):
        before = _sheet(size=size)
        assert B.in_name_box(before, _sheet(size=size, name=B.SHEET_END))                    # the Name Box took it
        assert not B.in_name_box(before, _sheet(size=size, formula=B.SHEET_END))             # a cell took it
        assert not B.in_name_box(before, _sheet(size=size, name=B.SHEET_END, formula="x"))   # both: never entered
        assert not B.in_name_box(before, _sheet(size=size))                                   # neither


def test_a_colleagues_half_typed_rows_under_the_last_manifest_are_stepped_over(tmp_path):
    # under the last manifest: two rows a colleague started (no manifest yet), then the empty one - no manifest above it
    R = _Walk(str(tmp_path), [_sheet(filled="CDE"), _sheet(filled="CDE", above=False), _sheet(above=False)])
    assert B.tracker_rows(R, [TRIP], "ACME_DH", NOW) == (1, "") and len(R.pasted) == 1
    assert [n for n, _ in R.batches].count("tracker-row") == 3


def test_an_empty_row_straight_under_no_manifest_is_never_pasted_on(tmp_path):
    R = _Walk(str(tmp_path), [_sheet(above=False)])
    assert B.tracker_rows(R, [TRIP], "ACME_DH", NOW) == (0, "couldn't be sure of the cursor on the tracker")
    assert R.pasted == []


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


def test_a_services_reminder_goes_on_before_the_booking_by_the_run_not_left_to_him(monkeypatch):
    import ctms_run
    night = {"id": "t1", "kind": "other", "source": "services", "orders": ["9100004"],
             "what": "Add NIGHT before it's booked (deliver Thu 12/11 23:00)"}
    hand = {"id": "t2", "kind": "other", "orders": ["9100004"], "what": "Ring the site"}
    assert B.owed_first(["9100004-1-1"], [night, hand]) == [night]          # a hand-written "other" doesn't hold it
    ran = []
    monkeypatch.setattr(ctms_run, "run", lambda ids: ran.append(ids) or {"ok": True, "said": "1 of 1 done in CTMS"})
    ok, said = B.run_owed([night])
    assert ok and ran == [["t1"]] and "went on first" in said
    upd = {"id": "t3", "kind": "update", "orders": ["9100004"], "what": "Update 9100004"}
    ok, said = B.run_owed([upd, night, dict(hand, kind="booking")])
    assert not ok and said.startswith("Ring the site") and "isn't something Book can type" in said


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


def test_a_dts_booking_email_goes_to_whoever_booked_it_in_on_its_form():
    """His 26/11 (a supplier's DTS sent on to us by a colleague): "you just contact these people that has been booked in"
    - the form's raised-by, never whoever forwarded it. An ad hoc keeps its delivery contact first, as before."""
    import types
    ours = "me@example.net"
    fwd = types.SimpleNamespace(SenderEmailAddress="jo.forwarder@example.org", SenderName="Jo Forwarder", Sender=None,
                                Body="Please can you sort this")
    dts = {"kind": "dts", "details": {"contact": {"name": "Ian Site"}}}
    raised = ["orders@supplier.example.com"]
    assert B.oneoff_to(dts, {}, None, raised, ours) == ("orders@supplier.example.com", "")
    assert B.oneoff_to(dts, {}, fwd, raised, ours)[0] == "orders@supplier.example.com"
    assert B.oneoff_to(dts, {"site_to": "chosen@example.com"}, fwd, raised, ours)[0] == "chosen@example.com"
    assert B.oneoff_to(dts, {}, None, [ours, "noreply@example.com"], ours) == ("", "")
    adhoc = {"kind": "adhoc", "details": {"contact": {"name": "Robin Field"}}}
    assert B.oneoff_to(adhoc, {}, None, ["sam.asker@example.net", "robin.field@site.example.com"], ours) == \
        ("robin.field@site.example.com", "Robin")
    assert B.oneoff_to(adhoc, {}, None, ["sam.asker@example.net"], ours) == ("sam.asker@example.net", "")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))


def test_the_well_is_filtered_on_the_delivery_ends_region():
    # his 09/11: Book puts Order Filters on the order's region before it looks for the order
    import book_run as BR
    assert BR.region_for("LU2 9PW") == "R4" and BR.region_for("DN16 1BP") == "R2" and BR.region_for("") == ""


def test_loose_ballast_and_stoneblowers_are_looked_for_on_strategy_4():
    # his 16/11: loose ballast is on Strategy 4, the same as stoneblowers
    import book_run as BR
    assert BR.strategy_for({"materials": "40x loose ballast"}) == "Strategy 4 - Tippers"
    assert BR.strategy_for({"materials": "ballast", "product_codes": ["0057/100500/001"]}) == "Strategy 4 - Tippers"
    assert BR.strategy_for({"materials": "20x stoneblower stone"}) == "Strategy 4 - Tippers"
    assert BR.strategy_for({"materials": "80x ballast", "product_codes": ["0057/100500/002"]}) == ""   # bags
    assert BR.strategy_for({"materials": "37x rails"}) == "" and BR.strategy_for(None) == ""


def test_with_nobody_on_the_request_to_email_whoever_asked_for_it_is_told():
    """His 24/11 (an RDA order): our own forward of DHL Road's copy, the contact only a name and a phone - the person who
    wrote the request gets the confirmation; never us, DHL Road or a no-reply portal, nor a colleague who only sent it on."""
    import types
    ours = "me@example.net"
    me = types.SimpleNamespace(GetExchangeUser=lambda: types.SimpleNamespace(PrimarySmtpAddress=ours))
    own_forward = types.SimpleNamespace(
        SenderEmailAddress="/o=ExchangeLabs/ou=Exchange/cn=Recipients/cn=me", SenderName="Pat Planner", Sender=me,
        Body=("OFFICIAL\r\nFrom: Sam Asker (Example Co) <sam.asker@example.net> On Behalf Of Transport Projects\r\n"
              "Sent: 24 November 2026 11:52\r\nTo: ZX-DHLRoad <DHLRoad@example.org>\r\nCc: Orders <orders@example.org>\r\n"))
    assert B.requester(own_forward, ours) == ("sam.asker@example.net", "Sam Asker (Example Co)")
    assert B.first_name("Sam Asker (Example Co)") == "Sam"
    sent_on = types.SimpleNamespace(
        SenderEmailAddress="jo.colleague@example.org", SenderName="Jo Colleague", Sender=None,
        Body=("Please can you plan\r\nFrom: Jo Colleague <jo.colleague@example.org> On Behalf Of ZX-DHLRoad\r\n"
              "From: Robin Field <robin.field@example.org>\r\nSent: 16 November 2026 09:58\r\n"
              "To: ZX-DHLRoad <DHLRoad@example.org>\r\n"))
    assert B.requester(sent_on, ours)[0] == "robin.field@example.org"          # who wrote it, not who sent it on
    direct = types.SimpleNamespace(SenderEmailAddress="robin.field@example.org", SenderName="Robin Field", Sender=None,
                                   Body="Hi, can you collect a pallet please")
    assert B.requester(direct, ours) == ("robin.field@example.org", "Robin Field")
    portal = types.SimpleNamespace(SenderEmailAddress="", SenderName="", Sender=None,
                                   Body="From: ZX-DHLRoad <DHLRoad@example.org>\r\nFrom: Portal <noreply@service-now.com>\r\n")
    assert B.requester(portal, ours) == ("", "")


def test_the_journal_keeps_the_record_so_what_follows_a_booking_still_knows_the_request(tmp_path):
    """An ad hoc leaves the map once booked: the journal's own copy of the record is what the site email reads then."""
    import book_journal as J
    path = str(tmp_path / "journal.json")
    rec = {"id": "adhoc|9100001|1", "kind": "adhoc", "mail": {"entryid": "E1"}, "details": {"contact": {"name": "Sam"}}}
    e = J.asking({"orders": ["9100001"], "date": "26/11/2026", "carrier": "PASS_DH", "record": rec["id"],
                  "record_copy": rec}, path=path)
    assert J.get(e["key"], path=path)["record_copy"] == rec


def test_an_ad_hoc_over_four_tonnes_is_on_strategy_6_and_its_upload_names_who_raised_it(tmp_path, monkeypatch):
    """His 24/11: an ad hoc the well's Business Type (left on another strategy) hid, and a site email with no request
    email on the job. Its upload says both: NRADHOC_NS imports on Strategy 6, and sub-ref 1002 names who raised it."""
    import outbox
    order = ["ORDER", "AH1/1/26EXEX", "Exa", "Example Yard"] + [""] * 24 + ["NRADHOC_NS", "", "", "0", "Material x"]
    rows = [order, ["ORD_SUB_REFS", "1002", "sam.asker@example.net;Robin.Field@site.example.com"],
            ["ORD_SUB_REFS", "1003", "100001"], ["ORDER", "AH2/1/26EXEX", "Other"] + [""] * 25 + ["NRADHOC"],
            ["ORD_SUB_REFS", "1002", "someone.else@example.net"]]
    (tmp_path / "up.csv").write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(outbox, "path", lambda name: str(tmp_path / name))
    rec = {"orders": ["AH1/1/26EXEX"], "csv": "up.csv"}
    assert B.upload_account(rec) == "NRADHOC_NS" and B.strategy_for(rec) == "Strategy 6 - Ad-Hoc/Projects"
    assert B.raised_by(rec) == ["sam.asker@example.net", "robin.field@site.example.com"]     # its own rows only
    assert B.contact_in(B.raised_by(rec), "Robin Field") == "robin.field@site.example.com"
    assert B.contact_in(B.raised_by(rec), "Jo Colleague") == ""
    other = {"orders": ["AH2/1/26EXEX"], "csv": "up.csv"}
    assert B.strategy_for(other) == "" and B.raised_by(other) == ["someone.else@example.net"]
    assert B.strategy_for({"orders": ["X"], "csv": "missing.csv"}) == "" and B.raised_by({}) == []


def test_an_order_whose_strategy_the_toolkit_cant_tell_has_it_read_off_its_card():
    """His 24/11 "the book button has a gap with not checking the strategy types": the card's Business Type, read by
    the routes' order-read; a bare order number opens its first line; nothing readable is ""."""
    import json as _json
    import types
    said = []

    def run(args, **kw):
        ref = args[-1]
        said.append(ref)
        if ref == "9100001":
            out = 'no line 9100001 in Order Summary (lines found: 9100001-1-1, 9100001-2-1)\nROUTE_RESULT {"ok": false}'
        elif ref in ("9100001-1-1", "AH1/12/26EXEX"):
            out = "ROUTE_RESULT " + _json.dumps({"order": {"business_type": "Strategy 10 - Non NR"}, "ok": True})
        else:
            out = "it fell over"
        return types.SimpleNamespace(stdout=out, returncode=0)

    assert B.order_strategy("AH1/12/26EXEX", run=run) == "Strategy 10 - Non NR" and said == ["AH1/12/26EXEX"]
    said.clear()
    assert B.order_strategy("9100001", run=run) == "Strategy 10 - Non NR" and said == ["9100001", "9100001-1-1"]
    assert B.order_strategy("9100009", run=run) == ""
