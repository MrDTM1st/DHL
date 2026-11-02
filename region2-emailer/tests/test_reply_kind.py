"""Who answered an order's email, and with what (his 02/11): the materials team answering an escalation is told as
theirs - a contact typed in, or a screenshot of one - never as the site's reply, and a reply with nothing to type
("is the delivery date still ok?") is not an update for CTMS. Made-up people and orders only.

    python tests/test_reply_kind.py
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import reply_kind as K  # noqa: E402
import delivery_details as D  # noqa: E402

D._today = lambda: date(2026, 11, 2)                 # the day these made-up replies are written

QUOTED = ("\r\nFrom: Delali Opoku (DHL Supply Chain) <delali.opoku@dhl.com>\r\nSent: 30 October 2026 19:41\r\n"
          "Subject: 9100200 Exampletown EX1 1AA - alternative contact needed\r\n\r\nHi,\r\n\r\nCould you point me to an "
          "alternative contact for this order?\r\n\r\nKind regards\r\n\r\nDelali Opoku\r\n07700 900999\r\n")
TEAM_SIGNATURE = "Kind regards,\r\n\r\nSam Clerk\r\n\r\nContracts Assistant\r\n\r\nM 0770 090 0555\r\n\r\n"
# someone we emailed by mistake, with a footer that has a phone number and a date in it
WRONG_PERSON = ("OFFICIAL\r\n\r\n\r\n\r\nGood morning Delali\r\n\r\n \r\n\r\nI'm afraid you have the wrong person; my "
                "namesake, cc above, will be able to help you.\r\n\r\n \r\n\r\nBest regards\r\n\r\n \r\n\r\nSam.\r\n\r\n"
                " \r\n\r\nSam Example CEng\r\n\r\nSenior Engineer\r\n\r\nTelephone 07700 900444\r\n\r\n \r\n\r\nPlease "
                "note that I do not work any Fridays.\r\n\r\n \r\n\r\n20 years' railway service from 11 August 2003.\r\n\r\n"
                + QUOTED)
ANSWERS = ("OFFICIAL\r\n\r\n    Date and time of delivery? 08:00 18/11/26\r\n    Who will be the contact for delivery? "
           "Jo Site 07700 900111\r\n    Alternative delivery contact? S Example 07700 900222\r\n    Do we need to bring our "
           "own offloading? (HIAB or Moffet) - HIAB req\r\n    Can artics access the site? no\r\n    Is rear steer "
           "required? yes\r\n    Does the driver need PTS (Only required if within 3m of line)? yes\r\n    What3Words "
           "Location? ///one.two.three\r\n\r\n \r\n\r\nSam Example\r\n\r\nSection Supervisor\r\n\r\n07700 900222\r\n" + QUOTED)


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


def test_a_wrong_person_reply_gives_nothing_to_type_whatever_its_footer_says():
    rec = {"delivery_date": "16/11/2026", "materials": "2x rails"}
    assert K.gave_details(rec, WRONG_PERSON, "rails", "Sam Example") is False
    assert K.said_line(WRONG_PERSON) == ("Good morning Delali I'm afraid you have the wrong person; my namesake, cc "
                                         "above, will be able to help you.")
    # our questions answered count wherever they signed off
    assert K.gave_details(rec, "Hi,\r\nThanks\r\nCan artics access the site? no\r\n" + QUOTED, "rails", "Sam") is True


def test_a_footers_date_is_no_delivery_date_and_a_day_gone_is_not_firm():
    for body in (WRONG_PERSON, "Please see my footer.\r\nSam Example\r\nIn post since 11 August 2003\r\n" + QUOTED):
        d = D.parse_reply(body, product_type="rails", sender="Sam Example")
        assert d["date"]["value"] is None and D.firm_date(d) is None, d["date"]
    # a day already gone, even typed in the answer, is never taken as the delivery: it comes to him with their words
    d = D.parse_reply("Date and time of delivery? 28/10/26 08:00\r\n" + QUOTED)
    assert d["date"]["value"] is None and D.firm_date(d) is None and d["date"]["raw"].startswith("28/10/26")
    # a gone day beside the real one doesn't make it "a choice of days"
    d = D.parse_reply("I was off on 28/10/26. Please deliver on 18/11/26 at 08:00.\r\n" + QUOTED)
    assert D.firm_date(d) == "18/11/2026", d["date"]


def test_a_sign_off_ends_the_message_but_a_greeting_or_a_thanks_with_more_to_say_does_not():
    assert D.above_sign_off("Deliver 18/11\r\nKind regards,\r\nSam 01/02/2030") == "Deliver 18/11\r\n"
    assert D.above_sign_off("Deliver 18/11\nThanks\nSam") == "Deliver 18/11\n"
    assert D.above_sign_off("Deliver 18/11\nRegards Sam\n01/02/2030") == "Deliver 18/11\n"
    assert D.above_sign_off("Thanks Delali\n\nDeliver 18/11\nCheers") == "Thanks Delali\n\nDeliver 18/11\n"
    assert D.above_sign_off("OFFICIAL\n\nThanks\nDeliver 18/11") == "OFFICIAL\n\nThanks\nDeliver 18/11"
    text = "Thanks for that, please deliver on 18/11/26\nSam"
    assert D.above_sign_off(text) == text


def test_the_alternative_contact_is_read_beside_the_contact():
    d = D.parse_reply(ANSWERS, product_type="rails", sender="Sam Example")
    assert (d["contact"]["name"], d["contact"]["phone"]) == ("jo site", "07700900111"), d["contact"]
    assert (d["alt_contact"]["name"], d["alt_contact"]["phone"]) == ("s example", "07700900222"), d.get("alt_contact")
    assert d["date"]["value"] == "18/11/2026" and d["artic_access"]["value"] == "no" and D.missing(d, "rails") == []
    # none given, or only the one contact named under that heading: nothing to add
    assert "alt_contact" not in D.parse_reply("Who will be the contact for delivery? Jo 07700 900111\r\n"
                                              "Alternative delivery contact? N/A\r\n" + QUOTED)
    d = D.parse_reply("Alternative delivery contact? Jo 07700 900111\r\n" + QUOTED)
    assert "alt_contact" not in d and d["contact"]["phone"] == "07700900111"


def test_the_newest_mail_with_the_details_is_the_answer_whatever_came_after_it():
    rec = {"to": "sam.example@example.com", "delivery_date": "16/11/2026", "materials": "2x rails"}
    wrong = {"addr": "sam.example@example.com", "who": "Sam Example", "body": WRONG_PERSON, "eid": "e1"}
    real = {"addr": "sam.example3@example.com", "who": "Sam Example", "body": ANSWERS, "eid": "e2"}
    later = {"addr": "jo.site@example.com", "who": "Jo Site", "body": "Thanks all\r\n" + QUOTED, "eid": "e3"}
    team = {"addr": "steelmaterials@networkrail.co.uk", "who": "Sam Clerk", "eid": "e4",
            "body": "Please try Jo\r\n" + TEAM_SIGNATURE + QUOTED}
    assert K.sort_out(rec, [wrong], "rails") == (None, None, wrong)     # nothing yet: told as "no details"
    assert K.sort_out(rec, [real, wrong], "rails") == (real, None, None)
    assert K.sort_out(rec, [later, real, wrong], "rails") == (real, None, later)     # never hidden by a later "thanks"
    assert K.sort_out(rec, [team, wrong], "rails") == (None, team, wrong)
    assert K.sort_out(rec, [team, real], "rails") == (real, team, None)
    # the team's address being the order's own contact: their reply is the site's
    assert K.sort_out(dict(rec, to=team["addr"]), [team], "rails")[1] is None


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
