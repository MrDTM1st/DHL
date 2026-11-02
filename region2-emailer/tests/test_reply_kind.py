"""Who answered an order's email, and with what (his 02/11): the materials team answering an escalation is told as
theirs - a contact typed in, or a screenshot of one - never as the site's reply, and a reply with nothing to type
("is the delivery date still ok?") is not an update for CTMS. Made-up people and orders only.

    python tests/test_reply_kind.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import reply_kind as K  # noqa: E402

QUOTED = ("\r\nFrom: Delali Opoku (DHL Supply Chain) <delali.opoku@dhl.com>\r\nSent: 30 October 2026 19:41\r\n"
          "Subject: 9100200 Exampletown EX1 1AA - alternative contact needed\r\n\r\nHi,\r\n\r\nCould you point me to an "
          "alternative contact for this order?\r\n\r\nKind regards\r\n\r\nDelali Opoku\r\n07700 900999\r\n")
TEAM_SIGNATURE = "Kind regards,\r\n\r\nSam Clerk\r\n\r\nContracts Assistant\r\n\r\nM 0770 090 0555\r\n\r\n"


def test_the_materials_teams_addresses_are_known_whatever_their_case():
    assert K.materials_team("SteelMaterials@networkrail.co.uk") == "Steel Materials"
    assert K.materials_team("steelmaterials@NETWORKRAIL.co.uk") == "Steel Materials"
    assert K.materials_team("track.aggregates@networkrail.co.uk") == "Track Aggregates"
    assert K.materials_team("sam.site@example.com") == "" and K.materials_team("") == ""


def test_a_contact_typed_into_their_message_is_picked_out_but_never_theirs_ours_or_the_one_we_had():
    body = ("OFFICIAL\r\n\r\nHi Delali,\r\n\r\nPlease try Jo Planner jo.planner@example.com or 07700 900123, "
            "or the site at sam.site@example.com.\r\n\r\n" + TEAM_SIGNATURE + QUOTED)
    got = K.typed_contacts(body, skip=("steelmaterials@networkrail.co.uk", "sam.site@example.com"))
    assert got == ["jo.planner@example.com", "07700900123"], got     # not the signature's number, nor ours quoted
    assert K.typed_contacts("Please see below -\r\n\r\n" + TEAM_SIGNATURE + QUOTED) == []


def test_a_screenshot_in_their_message_counts_but_the_logos_in_signatures_do_not():
    html = ('<p>Hi Delali,</p><p>Please see below &ndash;</p><p><img src="cid:image001.png"></p>'
            '<p>Kind regards,</p><p>Sam Clerk</p><img src="cid:image002.png">'
            '<div><b>From:</b> Delali Opoku</div><img src="cid:image003.png">')
    assert K.message_pictures(html) == 1
    assert K.message_pictures('<p>Thanks, see the contact above.</p><p>Kind regards</p><img src="cid:logo.png">') == 0


def test_what_they_wrote_comes_back_in_one_line_without_their_signature_or_the_quote():
    body = ("OFFICIAL\r\n\r\nMorning \r\n\r\nI've been away is the delivery date still ok for the 5/11/26\r\n\r\n"
            "Sent from Outlook for iOS <https://aka.ms/o0ukef>\r\n________________________________\r\n" + QUOTED)
    assert K.said_line(body) == "Morning I've been away is the delivery date still ok for the 5/11/26"


def test_a_reply_that_only_asks_about_our_date_gives_nothing_to_type():
    rec = {"delivery_date": "05/11/2026", "materials": "1x rails"}
    asks = ("OFFICIAL\r\n\r\nMorning\r\n\r\nI've been away is the delivery date still ok for the 5/11/26\r\n\r\n"
            "________________________________\r\n" + QUOTED)
    assert K.gave_details(rec, asks, "rails", "Sam Site") is False     # our own date asked back, "needed" quoted
    # a different day is news, and so is anything about the delivery itself
    assert K.gave_details(rec, "Can we make it 06/11/26 please" + QUOTED, "rails", "Sam Site") is True
    assert K.gave_details(rec, "Yes 5/11 is fine, we will need a HIAB and artics can get in" + QUOTED, "rails",
                          "Sam Site") is True
    assert K.gave_details(rec, "Deliver between 08:00 and 12:00 please" + QUOTED, "rails", "Sam Site") is True


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
