"""The site contact from a reply (delivery_details): a named contact wins; when nobody is named, the person who
sent the reply is the contact, on the number in their footer - or anywhere in their own mail, never in ours.
Made-up names and Ofcom drama-range numbers only.

    python tests/test_reply_contact.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import delivery_details as D  # noqa: E402

OURS = """From: Planner (Example Logistics) <planner@example.com>
Sent: 30 October 2026 00:10
To: Sam Example <sam.example@example.com>
Subject: 1234567 Example Depot
Hi Sam,
Can you please help with the details below and I can get the delivery arranged for you?
    Date and time of delivery?
    Who will be the contact for delivery?
Kind regards
Planner
Contact
01632 960999
"""

FOOTER_ONLY = """OFFICIAL
Planner,
No Hiab required
Please deliver between 0800 to 1200 on 20/11/2026.
HGV ok.
Regards,
Sam
Sam Example
Operations Manager
Example Depot | Example Road | Exampletown | EX1 2AB
M 07700 900123 | E sam.example@example.com
W example.com
""" + OURS


def test_nobody_named_means_the_sender_on_the_number_in_their_footer():
    c = D.parse_reply(FOOTER_ONLY, sender="Sam Example")["contact"]
    assert (c["name"], c["phone"], c["confidence"], c.get("source")) == \
        ("Sam Example", "07700900123", D.HIGH, "sender")


def test_a_footer_label_is_never_a_name():
    c = D.parse_reply(FOOTER_ONLY)["contact"]                 # no sender known: the number, but no name
    assert (c["name"], c["phone"], c["confidence"]) == (None, "07700900123", D.AMBER)
    assert D.parse_contact("Sam Example | Mob: 07700 900123")[:2] == ("Sam Example", "07700900123")
    assert D.parse_contact("Tel: 01632 960123")[0] is None


def test_a_named_contact_wins_over_the_sender():
    body = "Hi,\nContact for delivery: Darren 07700 900456\nThanks\nSam Example\nM 07700 900123\n" + OURS
    c = D.parse_reply(body, sender="Sam Example")["contact"]
    assert (c["name"], c["phone"], c.get("source")) == ("Darren", "07700900456", None)


def test_the_number_can_come_from_their_own_earlier_mail_but_never_from_ours():
    earlier = ("From: Sam Example <sam.example@example.com>\nSent: 30 October 2026 05:26\n"
               "Subject: RE: 1234567 Example Depot\nWhich job is this for?\nSam Example\nMob: 07700 900789\n")
    body = "Hi,\nDeliver 20/11/2026 between 08:00 and 12:00.\nThanks\nSam\n" + earlier + OURS
    c = D.parse_reply(body, sender="Example, Sam")["contact"]
    assert (c["name"], c["phone"], c["confidence"]) == ("Sam Example", "07700900789", D.HIGH)
    c = D.parse_reply("Hi,\nDeliver 20/11/2026 at 08:00.\nThanks\nSam\n" + OURS, sender="Sam Example")["contact"]
    assert (c["name"], c["phone"], c["confidence"]) == ("Sam Example", None, D.AMBER)
    assert "site contact" not in D.missing(D.parse_reply("Hi,\nThanks\n" + OURS, sender="Sam Example"))


def test_the_senders_name_reads_like_a_name():
    assert D.sender_name("Example, Sam") == "Sam Example"
    assert D.sender_name("Sam Example (Example Co)") == "Sam Example"
    assert D.sender_name("sam.example@example.com") == "Sam Example"
    assert D.sender_name("") is None


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
