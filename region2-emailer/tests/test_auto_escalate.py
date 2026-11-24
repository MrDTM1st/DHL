"""Plain-assert tests for the automatic escalation's decisions - no Outlook.

Run:  python region2-emailer/tests/test_auto_escalate.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import auto_escalate as ae                  # noqa: E402
from modules import chase_rules as cr       # noqa: E402

NOW = datetime(2026, 11, 4, 12, 5)
REC = {"id": "r1", "orders": ["9100001"], "to": "site.person@networkrail.co.uk", "name": "Site Person",
       "worksite": "Somewhere Yard", "postcode": "AA1 1AA", "materials": "21x sleepers", "delivery_date": "10/11/2026",
       "ctms_at": "2026-11-04 09:03", "ctms_veh": False}
OLD = dict(REC, orders=["6999913"])


def dec(action, reason="x"):
    return {"action": action, "reason": reason}


def what(rec=REC, d=None, asked=None, now=NOW):
    return ae.decide(rec, d or dec(cr.SEND), asked, now)[0]


def test_no_reply_is_escalated():
    assert what() == "escalate"
    assert what(d=dec(cr.WAIT)) == "escalate"      # chased yesterday: the chaser waits, this does not


def test_the_ask_and_a_chase_unanswered_is_escalated_and_says_so():
    # his rule 10/11: the chaser waits instead of a second chase; the escalation goes in its place
    d = {"action": cr.WAIT, "reason": "the next contact is the escalation", "evidence": {"escalate": True}}
    assert ae.decide(REC, d, None, NOW) == ("escalate", "no reply to the ask and a chase")
    assert ae.decide(dict(REC, ctms_at=None), d, None, NOW)[0] == "hold"        # CTMS still looked at first


def test_an_out_of_office_is_escalated_but_other_holds_are_his():
    assert what(d=dec(cr.HOLD, "out of office - check their auto-reply")) == "escalate"
    assert what(d=dec(cr.HOLD, "Someone wrote about this order - check")) == "hold"
    assert what(d=dec(cr.HOLD, "they have emailed you since you last asked")) == "hold"
    assert what(d=dec(cr.HOLD, "an email from x could not be read")) == "hold"


def test_a_reply_a_booking_or_a_haulier_ask_stops_it():
    assert what(d=dec(cr.BLOCK, "replied 02/11 09:00")) == "skip"
    assert what(d=dec(cr.STOP, "you have booked it")) == "skip"


def test_a_veh_type_in_ctms_means_the_details_are_in():
    assert what(dict(REC, ctms_veh=True)) == "skip"


def test_ctms_must_have_been_looked_at_today():
    """A cancellation or a phone call leaves nothing in the mailbox - only the look-up sees them."""
    assert what(dict(REC, ctms_at="2026-11-03 17:02")) == "hold"
    assert what(dict(REC, ctms_at=None)) == "hold"
    assert what(dict(REC, ctms_at="")) == "hold"
    assert "CTMS has not been looked at today" in ae.decide(dict(REC, ctms_at=None), dec(cr.SEND), None, NOW)[1]
    # a reply stops it either way: nothing to hold for
    assert what(dict(REC, ctms_at=None), dec(cr.BLOCK, "replied")) == "skip"


def test_a_hold_for_want_of_a_look_up_asks_the_work_pc_for_one_and_never_fails_the_run():
    """11/11: on a busy day no set-time look-up gets its three quiet minutes, so a held escalation asks the dashboard
    to have just its orders looked up at the work PC's next quiet minute - the 20-minute pass then sends it."""
    import json
    import urllib.request
    why = ae.decide(dict(REC, ctms_at=None), dec(cr.SEND), None, NOW)[1]
    assert why.startswith(ae.LOOKED) and "next quiet minute" in why
    keep = (urllib.request.urlopen, ae.HERE)
    folder = tempfile.mkdtemp()
    with open(os.path.join(folder, "cloud.json"), "w", encoding="utf-8") as f:
        json.dump({"url": "https://dash.example/", "agent_key": "k"}, f)
    asked = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        asked.append((req.full_url, json.loads(req.data), req.get_header("X-auth")))
        return Resp()
    try:
        ae.HERE = folder
        urllib.request.urlopen = fake
        assert ae.want_lookup([REC, dict(REC, orders=["9100002", "9100003"], delivery_date="")]) is True
        url, body, key = asked[0]
        assert url == "https://dash.example/api/ctms/check_want" and key == "k"
        assert body["orders"] == [{"ref": "9100001", "date": "10/11/2026"}, {"ref": "9100002", "date": ""},
                                  {"ref": "9100003", "date": ""}]
        assert ae.want_lookup([]) is False and len(asked) == 1                  # nothing to ask about

        def down(req, timeout=0):
            raise OSError("no route")
        urllib.request.urlopen = down
        assert ae.want_lookup([REC]) is False                                   # the dashboard away: no harm done
    finally:
        urllib.request.urlopen, ae.HERE = keep


def test_an_earlier_ask_for_a_contact_is_not_repeated_and_he_is_told():
    subject = "6999913 Somewhere Yard AA1 1AA - alternative contact needed"
    mine = {"dir": "out", "subject": subject, "at": datetime(2026, 11, 2, 9, 0)}
    assert ae.already_asked(OLD, [dict(mine, subject="6999914 Elsewhere - alternative contact needed"),
                                  dict(mine, dir="in"), dict(mine, subject="6999913 Somewhere Yard AA1 1AA")]) is None
    assert ae.already_asked(OLD, [mine]) is mine
    for s in ("6999913/6999914 Site - alternative contact needed", "6999913-1-1 Site - alternative contact needed",
              "6999913-alternative contact needed", "RE: 6999913 alt contact please"):
        assert ae.already_asked(OLD, [dict(mine, subject=s)]), s
    assert what(OLD, asked=mine) == "asked"


def test_the_email_keeps_the_briefs_wording_and_names_no_price():
    subject, message = ae.compose(REC)
    assert subject == "9100001 Somewhere Yard AA1 1AA - alternative contact needed", subject
    assert "I have been trying to reach Site Person (site.person@networkrail.co.uk) (cc'd) about order 9100001" in message
    assert "21x sleepers to Somewhere Yard, AA1 1AA, delivering 10/11/2026" in message
    assert "not managed to get hold of them after a few attempts" in message
    assert "alternative contact for this order" in message
    assert "—" not in message and "£" not in message and "Kind regards" not in message


def test_two_materials_go_to_both_teams():
    names = lambda m: [t["name"] for t in ae.teams_for(m)]
    assert names("21x sleepers") == ["SCO Sleepers & Troughing"]
    assert names("4x rails") == ["Steel Materials"]
    assert names("15x bags of ballast") == ["Track Aggregates"]
    assert names("37x rails, 516x sleepers") == ["SCO Sleepers & Troughing", "Steel Materials"]
    assert names("3x widgets") == [] and names(None) == []


def test_a_try_that_never_showed_can_go_again_only_after_an_hour():
    at = lambda m: {"at": (NOW - timedelta(minutes=m)).strftime("%d/%m/%Y %H:%M"), "status": "uncertain"}
    assert not ae.retry_ready(at(30), NOW)
    assert ae.retry_ready(at(61), NOW)
    assert ae.retry_ready(dict(at(61), status="sending"), NOW)
    assert not ae.retry_ready(dict(at(600), status="sent"), NOW)
    assert not ae.retry_ready({"at": "soon", "status": "uncertain"}, NOW)
    assert not ae.retry_ready(None, NOW)


def test_he_is_told_once_a_day_per_order():
    state = {}
    ae._tell(state, "r1", "HOLD 6999913: x", NOW)
    ae._tell(state, "r1", "HOLD 6999913: x", NOW + timedelta(hours=3))
    assert len(state["unreported"]) == 1
    ae._tell(state, "r1", "SENT 6999913: escalated to Steel Materials", NOW + timedelta(hours=3))
    assert len(state["unreported"]) == 2
    ae._tell(state, "r1", "SENT 6999913: escalated to Steel Materials", NOW + timedelta(days=1))
    assert len(state["unreported"]) == 3


def test_the_flag_only_sends_when_its_first_word_is_live():
    keep = ae.FLAG
    with tempfile.TemporaryDirectory() as t:
        ae.FLAG = os.path.join(t, "flag")
        try:
            assert ae.mode() == "off"
            for text, want in (("", "shadow"), ("LIVE", "live"), ("live\nnote", "live"), ("SHADOW", "shadow"),
                               ("nonsense", "shadow"), ("not live yet", "shadow"),
                               ("OFF until the delivery rule is proven", "shadow"), ("delivery", "shadow")):
                with open(ae.FLAG, "w") as f:
                    f.write(text)
                assert ae.mode() == want, text
            with open(ae.FLAG, "wb") as f:
                f.write("LIVE\r\n".encode("utf-16"))        # Windows PowerShell's default for "LIVE" > file
            assert ae.mode() == "live"
        finally:
            ae.FLAG = keep


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print(f"{len(tests)}/{len(tests)} passed")
