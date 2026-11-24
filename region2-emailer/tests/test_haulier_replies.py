"""Plain-assert tests for filing hauliers' "no" replies - every case is a real
reply to a ring-round on 02/10/2026.

Run:  python region2-emailer/tests/test_haulier_replies.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.haulier_replies import classify  # noqa: E402

SIG = "\n\nKind regards\nLee\nHaulier One\nLIMIT OF LIABILITY £100 PER TONNE"
QUOTED = "\n\nFrom: Pat Planner\nSent: 02 October 2026\nWould you be able to cover the job below"

DECLINES = [
    "No sorry",
    "Nothing for this one",
    "Pat, Unfortunately nothing for this one",
    "Hi Pat, I am ever so sorry but we are struggling to cover this one,",
    "Pat This is out of my area",
    "Hi Pat, I'm sorry we cannot cover this as we are fully booked",
    "Hi Pat Sorry we can't. We don't have drivers with driving time left",
    "Sorry cannot cover this",
    "Cant cover this one",
    "Apologies, not at such short notice",
    "Hello We would struggle today ☹",
    "Hi Pat, Apologies, same with this one, we cannot cover it",
    "Hi Pat, Agin cannot cover, sorry",
    "Sorry we cannot help. Sent from my iPhone",
    "Pat I have nothing in Scunthorpe today to collect",
]
OTHERS = [
    "Hi Pat Think we will be able to do 1 if that would help",           # partial offer
    "Hi there sorry this would be Tuesday load and delivery for me",     # counter-offer
    "Sorry couldnt free one up for monday, if any other day will work let me know",
    "Pat, Any news on this one?",                                        # a chase
    "Hello What time is this job delivering?",                           # a question
    "Hiya, I think this is new rail? We only have a log grab hiab for scrap",
    "Apologies, my hiab is an artic hiab and hes already booked up",     # tells us what they have
    "Your request #4411 has been received",                              # ticket auto-ack
    "Automatic reply: I am out of the office until Monday",
    # a no that carries what the planner needs to know (9100355, 05/10)
    "Apologies, we cannot collect from Boroubridge.\nWe usually collect this order from Land Recovery.\n"
    "If the collection point changes, give us a call and we may be able to cover",
    "Good afternoon,\nYes we can cover these loads on 8 wheel Rigid Tippers.",   # a yes without a price
]
QUOTES = [
    "Hi yes our quote for this would be £850.00",
    "Hi Pat, We can cover this for £850, please let me know if you need me to book it in, thanks.",
    "This one I can do £950",
]


def test_plain_no_is_a_decline():
    for t in DECLINES:
        assert classify(t + SIG + QUOTED) == "decline", t


def test_anything_else_stays_in_the_inbox():
    for t in OTHERS:
        assert classify(t + SIG + QUOTED) == "other", t


def test_a_price_is_a_quote_but_a_liability_limit_is_not():
    for t in QUOTES:
        assert classify(t + SIG + QUOTED) == "quote", t
    assert classify("Sorry cannot cover this" + SIG) == "decline"     # the £100 PER TONNE is no price


def test_a_no_quoted_below_does_not_count():
    # their own words are "yes, £900"; an earlier "no" sits in the quoted thread
    assert classify("Yes we can do £900" + QUOTED + "\nNo sorry") == "quote"
    assert classify("" + QUOTED) == "other"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
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
