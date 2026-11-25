"""The Network Rail team email when a site asks for another day than we offered. His rule as of 25/11: the day it would
be collected against the stock's availability date (the extract's collection date, never our own moves) - collected
before it, the team is asked first and the order stays put; after it, they are told; on it, it just moves. Made-up
orders, and road runs worked out offline (a far site unless a test says otherwise).

    python -m pytest tests/test_nr_date.py -q
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pytest  # noqa: E402

import ctms_run_plan as P  # noqa: E402
import nr_date as N  # noqa: E402
import same_day  # noqa: E402
import tracker as T  # noqa: E402

OFFERED = "20/11/2026"            # a Friday
FAR = {"miles": 140.0, "seconds": 3 * 3600}       # too far for his 65-mile same-day rule
NEAR = {"miles": 30.0, "seconds": 40 * 60}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Road runs worked out offline: a far site unless a test says otherwise."""
    monkeypatch.setattr(same_day, "road", lambda *a, **k: FAR)


def _rec(order="9100501", date=OFFERED, materials="60x sleepers", avail=None, **kw):
    r = {"id": T._key([order], date), "orders": [order], "kind": "delivery", "delivery_date": date,
         "materials": materials, "site": "Example Yard", "worksite": "Exampleton", "postcode": "EX1 1AA",
         "orig_entryid": "SENT-EID", "reply_at": "2026-11-09 10:00", "sendoff_ready": True, "status": "sent",
         "collections": [{"site": "Example Supplier", "pc": "EX9 9ZZ", "date": avail or date, "from": "08:00",
                          "to": "16:00"}],
         "details": {"date": {"value": "", "confidence": "high", "options": []},
                     "time": {"earliest": "08:00", "latest": "10:00", "confidence": "high"},
                     "offloading": {"value": "HIAB", "confidence": "high", "raw": "yes"},
                     "artic_access": {"value": "yes", "confidence": "high"},
                     "contact": {"name": "sam example", "phone": "07700 900123", "confidence": "high"},
                     "what3words": {"value": "///one.two.three"}}}
    r.update(kw)
    return r


_REAL_PATH = T.PATH


def _tracker(tmp, recs):
    T.PATH = os.path.join(tmp, "tracker.json")
    T.save({"records": recs})


def teardown_function(_f):
    T.PATH = _REAL_PATH          # never leave the real tracker pointed at a temp folder


def test_earlier_later_week_or_neither():
    assert N.classify(OFFERED, "07/11/2026") == "earlier"
    assert N.classify(OFFERED, "19/11/2026") == "earlier"              # one day before is still before
    assert N.classify(OFFERED, "23/11/2026") == "later"                # the Monday after: another week commencing
    assert N.classify(OFFERED, "20/11/2026") is None
    assert N.classify("16/11/2026", "20/11/2026") is None              # later, same week: just a move
    assert N.classify(OFFERED, "next week") is None and N.classify("", "07/11/2026") is None


def test_the_team_comes_from_the_material_and_never_copies_dhl_road():
    assert N.team_for(_rec(materials="279x sleepers"))["name"] == "SCO Sleepers & Troughing"
    assert "SleeperContractManagementTeam@networkrail.co.uk" in N.team_for(_rec(materials="2x bearers"))["to"]
    assert N.team_for(_rec(materials="13x rails"))["to"] == ["SteelMaterials@networkrail.co.uk"]
    assert N.team_for(_rec(materials="80x bagged ballast"))["to"] == ["Track.Aggregates@networkrail.co.uk"]
    assert N.team_for(_rec(materials="1x S&C crossing")) is None        # no team on the list: he is asked
    assert N.team_for(_rec(materials="")) is None
    assert N._addrs("Track.Aggregates@networkrail.co.uk; DHLRoad@networkrail.co.uk") == "Track.Aggregates@networkrail.co.uk"


def test_an_earlier_day_holds_the_order_and_drafts_the_question():
    r = _rec()
    d = {"records": [r]}
    assert N.on_new_date(d, r, "07/11/2026", "the site's reply", reply_eid="REPLY-EID") is False
    assert r["delivery_date"] == OFFERED and r["id"] == T._key(["9100501"], OFFERED)     # NOT moved
    nd = r["nr_date"]
    assert (nd["kind"], nd["offered"], nd["asked"], nd["state"]) == ("earlier", OFFERED, "07/11/2026", "to_send")
    assert nd["reply_eid"] == "REPLY-EID" and "SCOSleepers&Troughing@networkrail.co.uk" in nd["to"]
    assert "allowed" in nd["message"] and "stock" in nd["message"] and "07/11" in nd["message"]
    # his 25/11 rule: what the team is asked about is the collection (the day before), against the availability
    assert (nd["collect"], nd["available"]) == ("06/11/2026", OFFERED)
    assert "06/11" in nd["subject"] and "20/11" in nd["subject"] and "collected on Friday 06/11/2026" in nd["message"]
    assert N.held(r) == OFFERED
    # the same day seen again (a re-read, his confirm) drafts nothing new
    assert N.on_new_date(d, r, "07/11/2026", "your confirm") is False and r["nr_date"]["at"] == nd["at"]


def test_a_later_week_moves_the_order_and_drafts_the_notice():
    r = _rec(materials="13x rails")
    d = {"records": [r]}
    assert N.on_new_date(d, r, "30/11/2026", "the site's reply", reply_eid="REPLY-EID") is True
    assert r["delivery_date"] == "30/11/2026" and r["date_was"] == OFFERED
    nd = r["nr_date"]
    assert nd["kind"] == "later" and nd["state"] == "to_send" and nd["to"] == "SteelMaterials@networkrail.co.uk"
    assert "30/11" in nd["message"] and "20/11" in nd["message"]
    assert nd["collect"] == "27/11/2026" and "later than usual" in nd["subject"]       # collected the Friday before
    assert N.held(r) is None


def test_collected_on_the_availability_day_it_just_moves():
    r = _rec(date="16/11/2026")                         # a Monday: available from the 16th
    d = {"records": [r]}
    assert N.on_new_date(d, r, "17/11/2026", "the site's reply") is True      # 08:00 on the 17th: collected the 16th
    assert "nr_date" not in r and r["delivery_date"] == "17/11/2026"


def test_collected_later_in_the_same_week_it_just_moves():
    r = _rec(date="16/11/2026")                         # available Monday 16th
    d = {"records": [r]}
    assert N.on_new_date(d, r, "19/11/2026", "the site's reply") is True      # Thursday 08:00: collected Wednesday
    assert "nr_date" not in r and r["delivery_date"] == "19/11/2026"


def test_no_em_dashes_in_what_is_written():
    for kind, asked in (("earlier", "07/11/2026"), ("later", "30/11/2026")):
        subject, message = N.draft(_rec(), kind, OFFERED, asked)
        assert "—" not in subject + message and "–" not in subject + message


def test_send_then_yes_moves_it():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec()
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply", reply_eid="REPLY-EID")
        _tracker(tmp, d["records"])
        sent = []
        out = N.send(r["id"], {"message": "Hi all — edited"},
                     sender=lambda nd, to, cc, subj, msg: (sent.append((nd["reply_eid"], to, msg)) or True, "sent to " + to))
        assert out["ok"], out
        assert sent[0][0] == "REPLY-EID" and "—" not in sent[0][2]     # the trail is forwarded; no em dash
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "sent" and rec["delivery_date"] == OFFERED
        assert not N.send(r["id"], {}, sender=lambda *a: (True, ""))["ok"]   # never twice
        out = N.answer(r["id"], True)
        assert out["ok"], out
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "allowed" and rec["delivery_date"] == "07/11/2026"
        assert rec["date_moved_by"] == "Network Rail's OK"


def test_no_keeps_the_offered_day_and_the_ctms_update_types_it():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec()
        r["details"]["date"].update(value="07/11/2026", options=["07/11/2026"])
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply")
        r["nr_date"]["state"] = "sent"
        _tracker(tmp, d["records"])
        assert N.answer(r["id"], False)["ok"]
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "not_allowed" and rec["delivery_date"] == OFFERED
        assert rec["details"]["date"]["value"] == OFFERED and rec["details"]["date"]["asked"] == "07/11/2026"


def test_send_needs_someone_in_to():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec(materials="1x S&C crossing")
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply")
        assert r["nr_date"]["to"] == ""
        _tracker(tmp, d["records"])
        out = N.send(r["id"], {}, sender=lambda *a: (True, ""))
        assert not out["ok"] and "Who is the Network Rail team" in out["said"]


def test_the_ctms_run_types_nothing_while_network_rail_is_asked():
    r = _rec()
    r["details"]["date"].update(value="07/11/2026", options=["07/11/2026"])
    N.on_new_date({"records": [r]}, r, "07/11/2026", "the site's reply")
    item = {"id": "t1", "kind": "update", "orders": ["9100501"], "what": "Sam replied - update the order"}
    p = P.plan([item], [r], {})[0]
    assert p["status"] == "yours" and "Waiting on Network Rail" in p["explain"][0]
    # their no: the run goes on the day we offered, not the site's earlier one
    r["nr_date"]["state"] = "not_allowed"
    found = {f"9100501|{OFFERED}": {"lines": [{"ref": "9100501-1-1", "status": "UNSCHEDULED", "deliver_by": "20/11/26 16:01"}]}}
    p = P.plan([item], [r], found)[0]
    assert p["status"] != "yours" and p["set"].get("deliver", "").startswith("20/11/26"), p


def test_dismiss_an_earlier_day_moves_it_without_an_email():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec()
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply")
        _tracker(tmp, d["records"])
        assert N.dismiss(r["id"])["ok"]
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "dismissed" and rec["delivery_date"] == "07/11/2026"


# ---------- the automatic part (his 25/11: "could you also make that automatic?") ----------
from datetime import datetime  # noqa: E402

import ctms_sync as C  # noqa: E402
import ctms_todo as TD  # noqa: E402

NOW = datetime(2026, 11, 4, 10, 0)            # a Wednesday morning, in working hours
TEAM = "SCOSleepers&Troughing@networkrail.co.uk"
SITE = "site.person@example.co.uk"
PERSON = "pat.example@networkrail.co.uk"      # someone on the team, answering for it


def _asked(state="sent", kind="earlier", asked="07/11/2026", **kw):
    """A record whose date change has been drafted (and sent) - made-up order, site and people."""
    r = _rec(to=SITE)
    N.on_new_date({"records": [r]}, r, asked, "the site's reply", reply_eid="REPLY-EID")
    r["nr_date"]["at"] = "2026-11-03 09:00"
    r["nr_date"]["state"] = state
    if state != "to_send":
        r["nr_date"].update(sent_at="2026-11-03 09:30", sent_by="auto")
    r["nr_date"].update(kw)
    return r


def _out(subject, at, to=(TEAM,), conv="CONV-NR", eid="OUT-1"):
    return {"dir": "out", "at": at, "subject": subject, "eid": eid, "conv": conv, "to": list(to), "cc": [],
            "from": "", "from_name": "", "auto": False, "draft": False, "ndr": False, "folder": "/Sent Items"}


def _in(subject, at, frm=PERSON, name="Pat Example", conv="CONV-NR", eid="IN-1", **kw):
    m = {"dir": "in", "at": at, "subject": subject, "eid": eid, "conv": conv, "to": [], "cc": [], "from": frm,
         "from_name": name, "auto": False, "draft": False, "ndr": False, "folder": "/Inbox"}
    m.update(kw)
    return m


def _judge(r, mails, bodies=None, now=NOW):
    bodies = bodies or {}
    return N.judge(r, mails, lambda eid: bodies.get(eid, ""), now)


def test_their_own_words_without_the_marking_greeting_courtesies_and_signature():
    body = ("OFFICIAL\n\nHi Sam,\n\nThe supplier has confirmed the 07/11/26 will be fine. The sleepers are available."
            " Any issues give me a call.\n\nThanks,\nPat\n________________________________\nFrom: us\nSent: then\n"
            "Please could you confirm whether delivering on 07/11 is allowed?")
    text, thanked = N.said(body)
    assert text == "The supplier has confirmed the 07/11/26 will be fine. The sleepers are available." and thanked
    assert N.said("Hi,\nThanks for the email\nYes that's fine, let me know if you need anything else.\nPat Example")[0] \
        == "Thanks for the email Yes that's fine."
    assert N.said("OFFICIAL\n\nThanks\nPat")[0] == ""                  # a bare thanks
    assert N.said("Fine\nPat")[0] == "Fine" and N.said("Noted\n")[0] == "Noted"   # an answer is never a name


def test_a_yes_has_to_be_a_clear_yes():
    nd = {"kind": "earlier", "offered": OFFERED, "asked": "07/11/2026"}
    for text in ("The supplier has confirmed the 07/11/26 will be fine. The sleepers are available.", "Yes that's fine.",
                 "No problem at all, the stock is ready.", "I don't see any issues with that.", "Fine", "OK",
                 "Saturday is fine.", "The 7th is fine."):
        assert N.verdict(text, nd)[0] == "yes", text
    for text in ("Unfortunately the stock won't be ready until 20/11.", "No, keep it on the 20th please.",
                 "That's not possible, the sleepers aren't in yet.", "No"):
        assert N.verdict(text, nd)[0] == "no", text
    # never a guessed yes: a hedge, a promise to check, a question, a call me, someone else, another day, both, nothing
    for text in ("Should be fine.", "Hopefully that's fine.", "Let me check with the supplier and come back to you.",
                 "Yes, is it the same contact?", "Give me a ring about this one.", "I've copied in the supplier.",
                 "The 9th would work instead.", "Yes fine, but the stock won't be ready.", "Thanks for the email.",
                 "20/11 is fine", "", "Fine if the site can take it early."):
        assert N.verdict(text, nd)[0] == "unclear", text


def test_a_notice_wants_nothing_back_so_only_a_thank_you_is_let_go():
    nd = {"kind": "later", "offered": OFFERED, "asked": "30/11/2026"}
    assert N.verdict("Thanks for letting us know.", nd)[0] == "ack"
    assert N.verdict("Noted.", nd)[0] == "ack" and N.verdict("", nd, thanked=True)[0] == "ack"
    assert N.verdict("Thank you, I'll update our system.", nd)[0] == "ack"
    assert N.verdict("That day doesn't work, it has to go on the 20th.", nd)[0] == "unclear"


def test_to_send_goes_in_working_hours_and_holds_what_it_cannot_send():
    r = _asked(state="to_send")
    assert _judge(r, [])["do"] == "send"
    assert _judge(r, [], now=datetime(2026, 11, 4, 18, 30))["do"] == "wait"         # after 16:30
    assert _judge(r, [], now=datetime(2026, 11, 7, 10, 0))["do"] == "hold"          # the day asked is today
    assert "has gone" in _judge(r, [], now=datetime(2026, 11, 8, 10, 0))["why"]
    nobody = _rec(materials="1x S&C crossing", to=SITE)
    N.on_new_date({"records": [nobody]}, nobody, "07/11/2026", "the site's reply")
    assert "type who it goes to" in _judge(nobody, [])["why"]


def test_a_date_email_he_sent_by_hand_is_never_sent_again():
    r = _asked(state="to_send")
    mine = _out(r["nr_date"]["subject"], datetime(2026, 11, 3, 9, 40))
    got = _judge(r, [mine])
    assert got["do"] == "mark_sent" and got["mail"]["eid"] == "OUT-1"
    # an email to the team about the order but not plainly this one: his to say
    other = _out("RE: 9100501 Exampleton", datetime(2026, 11, 3, 9, 40), eid="OUT-2")
    assert _judge(r, [other], {"OUT-2": "Hi, any news on the contact?"})["do"] == "hold"
    assert _judge(r, [other], {"OUT-2": "Hi, the site wants it on 07/11, ok?"})["do"] == "mark_sent"
    # one sent before it was drafted is something else
    old = _out(r["nr_date"]["subject"], datetime(2026, 11, 2, 9, 0))
    assert _judge(r, [old])["do"] == "send"


def test_network_rails_answer_is_read_off_our_own_thread():
    r = _asked()
    subj = r["nr_date"]["subject"]
    sent = _out(subj, datetime(2026, 11, 3, 9, 30))
    yes = _in("RE: " + subj, datetime(2026, 11, 3, 11, 0))
    got = _judge(r, [sent, yes], {"IN-1": "OFFICIAL\n\nHi,\nYes that's fine, the stock is ready.\nThanks\nPat"})
    assert got["do"] == "yes" and got["mail"]["said"] == "Yes that's fine, the stock is ready."
    # the same subject finds it even when the conversation id doesn't
    got = _judge(r, [sent, dict(yes, conv="OTHER")], {"IN-1": "No, it won't be ready until the 20th."})
    assert got["do"] == "no"
    # unclear: held for him, their words with it
    got = _judge(r, [sent, yes], {"IN-1": "Should be OK, let me check."})
    assert got["do"] == "hold" and "Not a clear yes or no" in got["why"] and got["mail"]["said"]
    # nothing back yet: wait - and once the day asked has gone, his
    assert _judge(r, [sent])["do"] == "wait"
    assert "has gone" in _judge(r, [sent], now=datetime(2026, 11, 8, 9, 0))["why"]


def test_only_the_team_can_say_yes():
    r = _asked()
    subj = r["nr_date"]["subject"]
    sent = _out(subj, datetime(2026, 11, 3, 9, 30))
    body = {"IN-1": "Yes that's fine."}
    assert _judge(r, [sent, _in("RE: " + subj, datetime(2026, 11, 3, 11, 0), frm=TEAM.lower())], body)["do"] == "yes"
    for frm, who in ((SITE, "The site"), ("someone@supplier.example.com", "Someone outside Network Rail"),
                     ("colleague@dhl.com", "A colleague")):
        got = _judge(r, [sent, _in("RE: " + subj, datetime(2026, 11, 3, 11, 0), frm=frm)], body)
        assert got["do"] == "hold" and got["why"].startswith(who), (frm, got)
    # their yes on another thread (the site's, say) is never taken for the answer: shown to him
    off = _in("RE: 9100501 Exampleton", datetime(2026, 11, 3, 11, 0), conv="SITE-THREAD")
    got = _judge(r, [sent, off], body)
    assert got["do"] == "hold" and "outside the thread" in got["why"]
    # an out-of-office is no answer; a bounce is his
    assert _judge(r, [sent, _in("Automatic reply: " + subj, datetime(2026, 11, 3, 9, 31), auto=True)])["do"] == "wait"
    got = _judge(r, [sent, _in("Undeliverable: " + subj, datetime(2026, 11, 3, 9, 31), frm="postmaster@x.com",
                                ndr=True)])
    assert got["do"] == "hold" and "bounced" in got["why"]


def test_the_newest_answer_counts_and_one_he_waved_through_is_never_held_again():
    r = _asked()
    subj = r["nr_date"]["subject"]
    sent = _out(subj, datetime(2026, 11, 3, 9, 30))
    first = _in("RE: " + subj, datetime(2026, 11, 3, 10, 0), eid="IN-1")
    second = _in("RE: " + subj, datetime(2026, 11, 3, 14, 0), eid="IN-2")
    bodies = {"IN-1": "Let me check with the supplier.", "IN-2": "Yes, that's fine - the supplier is ready."}
    assert _judge(r, [sent, first, second], bodies)["do"] == "yes"
    assert _judge(r, [sent, first, second], dict(bodies, **{"IN-2": "No - it can't go early."}))["do"] == "no"
    yes_then_no = {"IN-1": "Yes that's fine.", "IN-2": "No, sorry, it won't be ready."}
    assert _judge(r, [sent, first, second], yes_then_no)["do"] == "hold"
    assert _judge(r, [sent, first], bodies)["do"] == "hold"
    r["nr_date"]["seen"] = ["IN-1"]
    assert _judge(r, [sent, first], bodies)["do"] == "wait"
    # a yes, then "let me check" that he waved through: still waiting - the older yes isn't taken after all
    r["nr_date"]["seen"] = ["IN-2"]
    later_doubt = {"IN-1": "Yes that's fine.", "IN-2": "Actually let me check with the supplier first."}
    assert _judge(r, [sent, first, second], later_doubt)["do"] == "wait"
    # a bounce or an auto-reply with its own prefix is still on our thread
    assert N._norm_subject("Undeliverable: RE: " + subj) == N._norm_subject(subj)


def test_a_notice_thanked_is_noted_and_anything_more_is_his():
    r = _asked(kind="later", asked="30/11/2026", state="sent")
    subj = r["nr_date"]["subject"]
    sent = _out(subj, datetime(2026, 11, 3, 9, 30))
    reply = _in("RE: " + subj, datetime(2026, 11, 3, 11, 0))
    assert _judge(r, [sent, reply], {"IN-1": "Thanks for letting us know.\nPat"})["do"] == "ack"
    got = _judge(r, [sent, reply], {"IN-1": "That won't work - the possession is on the 20th."})
    assert got["do"] == "hold" and "about the move" in got["why"]
    assert _judge(r, [sent])["do"] == "nothing"


class _Index:
    def __init__(self, mails, bodies):
        self.mails, self.bodies, self.errors, self.refreshed = mails, bodies, [], 0

    def text_of(self, eid):
        return self.bodies.get(eid, "")

    def refresh(self):
        self.refreshed += 1


def _switch(monkeypatch, tmp, how="LIVE"):
    flag = os.path.join(tmp, "auto_chase.enabled")
    if how:
        with open(flag, "w", encoding="utf-8") as f:
            f.write(how + "\n")
    monkeypatch.setattr(N, "CHASE_FLAG", flag)
    monkeypatch.setattr(N, "PAUSE_FLAG", os.path.join(tmp, "nr_date.paused"))
    monkeypatch.setattr(TD, "STORE", os.path.join(tmp, "_ctms_todo.json"))


def test_the_switches(monkeypatch, tmp):
    _switch(monkeypatch, tmp, how="")
    assert N.mode()["mode"] == "off" and "Auto follow-ups" in N.mode()["why"]
    _switch(monkeypatch, tmp, how="SHADOW")
    assert N.mode()["mode"] == "shadow"
    _switch(monkeypatch, tmp, how="LIVE")
    assert N.mode()["mode"] == "live"
    N.set_paused(True)
    assert N.mode()["mode"] == "off" and "paused" in N.mode()["why"]
    N.set_paused(False)
    import toolkit_switch
    monkeypatch.setattr(toolkit_switch, "is_off", lambda: True)
    assert N.mode() == {"mode": "off", "why": "the Toolkit switch is off"}
    out = N.auto(live=True, idx=_Index([], {}), now=NOW)
    assert out["did"] == 0 and out["lines"][0].startswith("SKIP")


def test_the_automatic_run_sends_reads_the_answer_and_moves_the_order(monkeypatch, tmp):
    _switch(monkeypatch, tmp)
    ask = _asked(state="to_send")                                 # 9100501, sleepers: to send
    yes = _asked(state="sent")                                    # the same, sent and answered
    yes["orders"], yes["id"] = ["9100502"], T._key(["9100502"], OFFERED)
    yes["nr_date"]["subject"] = "9100502 - site asking for an earlier delivery (07/11 instead of 20/11)"
    _tracker(tmp, [ask, yes])
    TD.replied(yes, when="2026-11-03 08:00", who="Sam")          # the reply's update, held till their answer
    subj = yes["nr_date"]["subject"]
    idx = _Index([_out(subj, datetime(2026, 11, 3, 9, 30)), _in("RE: " + subj, datetime(2026, 11, 3, 11, 0))],
                 {"IN-1": "Hi,\nThe supplier has confirmed the 07/11 will be fine.\nThanks\nPat"})
    sent = []
    out = N.auto(live=True, idx=idx, now=NOW,
                 sender=lambda nd, to, cc, subj, msg: (sent.append((nd["reply_eid"], to, subj)) or True, "sent to " + to))
    assert out["ok"] and out["did"] == 2, out
    assert sent == [("REPLY-EID", ask["nr_date"]["to"], ask["nr_date"]["subject"])] and idx.refreshed == 1
    recs = {r["orders"][0]: r for r in T.load()["records"]}
    a, y = recs["9100501"]["nr_date"], recs["9100502"]
    assert a["state"] == "sent" and a["sent_by"] == "auto"
    assert y["delivery_date"] == "07/11/2026" and y["date_moved_by"] == "Network Rail's OK"
    nd = y["nr_date"]
    assert nd["state"] == "allowed" and nd["answered_by"] == "auto" and nd["answer"]["verdict"] == "yes"
    assert "07/11 will be fine" in nd["answer"]["said"] and not N.held(y)
    # the CTMS to-do: the reply's own update, no longer held, types the new day
    plan = P.plan(TD.listing(tracker_path=T.PATH), T.load()["records"], {})
    upd = [p for p in plan if p["kind"] == "update" and "9100502" in p["orders"]][0]
    assert upd["status"] != "yours" and not upd.get("nr_held")
    # run again: nothing new
    assert N.auto(live=True, idx=idx, now=NOW, sender=lambda *a: (True, ""))["did"] == 0


def test_their_no_keeps_the_day_and_leaves_the_site_to_him(monkeypatch, tmp):
    _switch(monkeypatch, tmp)
    r = _asked(asked="07/11/2026")                                # 07/11/2026 is a Saturday
    r["details"]["date"].update(value="07/11/2026")
    _tracker(tmp, [r])
    TD.replied(r, when="2026-11-03 08:00", who="Sam")
    assert [i for i in TD.load()["items"] if i.get("source") == "services"]       # SATURDAY, for the day asked
    subj = r["nr_date"]["subject"]
    idx = _Index([_out(subj, datetime(2026, 11, 3, 9, 30)), _in("RE: " + subj, datetime(2026, 11, 3, 11, 0))],
                 {"IN-1": "No, the sleepers won't be ready until the 20th."})
    out = N.auto(live=True, idx=idx, now=NOW)
    assert out["did"] == 1 and out["lines"][0].startswith("NO"), out
    rec = T.load()["records"][0]
    assert rec["delivery_date"] == OFFERED and rec["nr_date"]["state"] == "not_allowed"
    assert rec["nr_date"]["tell_site"] and rec["details"]["date"]["value"] == OFFERED
    assert not [i for i in TD.load()["items"] if i.get("source") == "services" and not i.get("done_at")]
    assert N.told(rec["id"])["ok"] and not T.load()["records"][0]["nr_date"]["tell_site"]


def test_held_for_him_once_and_his_seen_lets_it_go(monkeypatch, tmp):
    _switch(monkeypatch, tmp)
    r = _asked()
    _tracker(tmp, [r])
    subj = r["nr_date"]["subject"]
    idx = _Index([_out(subj, datetime(2026, 11, 3, 9, 30)), _in("RE: " + subj, datetime(2026, 11, 3, 11, 0))],
                 {"IN-1": "I'll check with the supplier and come back to you."})
    out = N.auto(live=True, idx=idx, now=NOW)
    assert out["did"] == 1 and out["lines"][0].startswith("HOLD")
    held = T.load()["records"][0]["nr_date"]["held"]
    assert held["eid"] == "IN-1" and "come back to you" in held["said"]
    assert N.auto(live=True, idx=idx, now=NOW)["did"] == 0             # the same hold isn't said again
    assert N.seen(r["id"])["ok"]
    nd = T.load()["records"][0]["nr_date"]
    assert "held" not in nd and nd["seen"] == ["IN-1"] and nd["state"] == "sent"
    assert N.auto(live=True, idx=idx, now=NOW)["did"] == 0


def test_shadow_says_what_it_would_do_and_changes_nothing(monkeypatch, tmp):
    _switch(monkeypatch, tmp, how="SHADOW")
    r = _asked(state="to_send")
    _tracker(tmp, [r])
    before = json.dumps(T.load())
    out = N.auto(live=True, idx=_Index([], {}), now=NOW, sender=lambda *a: (_ for _ in ()).throw(AssertionError))
    assert out["mode"] == "shadow" and out["lines"][0].startswith("WOULD SEND") and out["did"] == 0
    assert json.dumps(T.load()) == before


def test_a_mailbox_it_cannot_read_sends_and_decides_nothing(monkeypatch, tmp):
    _switch(monkeypatch, tmp)
    r = _asked(state="to_send")
    _tracker(tmp, [r])

    class Broken(_Index):
        def refresh(self):
            raise RuntimeError("folder will not open")

    class Quiet(_Index):
        def refresh(self):
            self.errors.append("/Inbox/Region 2: cannot open folder")     # the index records it, doesn't raise
    for idx in (Broken([], {}), Quiet([], {})):
        out = N.auto(live=True, idx=idx, now=NOW, sender=lambda *a: (_ for _ in ()).throw(AssertionError))
        # a safe stop, not a failure: nothing went or was decided, and the next run looks again
        assert out["ok"] and out["did"] == 0 and out["lines"][0].startswith("ABORT"), out
        assert T.load()["records"][0]["nr_date"]["state"] == "to_send"


def test_a_failed_send_is_said_and_tried_again(monkeypatch, tmp):
    _switch(monkeypatch, tmp)
    r = _asked(state="to_send")
    _tracker(tmp, [r])
    out = N.auto(live=True, idx=_Index([], {}), now=NOW, sender=lambda *a: (False, "Outlook said no"))
    assert not out["ok"] and out["lines"][0].startswith("FAIL")
    nd = T.load()["records"][0]["nr_date"]
    assert nd["state"] == "to_send" and nd["send_failed"]["said"] == "Outlook said no"


# ---------- what CTMS has to follow ----------
def _ln(ref, status, deliver):
    return {"ref": ref, "status": status, "deliver_by": deliver + " 16:01", "schedule": ""}


def test_a_yes_with_no_update_left_open_puts_one_on_the_to_do(monkeypatch, tmp):
    _switch(monkeypatch, tmp)
    r = _asked()
    r["details"]["date"]["value"] = "07/11/2026"
    it = TD.nr_moved(r, "07/11/2026", when="2026-11-03 11:00")
    assert it["source"] == "nr_date" and "07/11" in it["what"]
    assert it["details"]["details"]["date"]["value"] == "07/11/2026"
    assert TD.nr_moved(r, "07/11/2026")["id"] == it["id"]               # never twice


def test_while_network_rail_is_asked_the_earlier_days_services_wait():
    r = _asked(asked="07/11/2026")                         # a Saturday: SATURDAY would be owed
    items = [{"id": "u1", "kind": "update", "orders": ["9100501"], "what": "Sam replied"},
             {"id": "s1", "kind": "other", "orders": ["9100501"], "source": "services",
              "what": "Add SATURDAY before it's booked (deliver Sat 07/11 08:00)", "added": "2026-11-03 08:00"}]
    plan = {p["id"]: p for p in P.plan(items, [r], {})}
    assert plan["u1"]["status"] == "yours" and plan["s1"]["status"] == "held"
    assert "Network Rail" in plan["s1"]["checks"][0]["why"]


def test_a_moved_order_ctms_has_an_old_update_on_is_typed_over_not_asked_about():
    r = _asked(state="allowed", asked="07/11/2026")
    r["delivery_date"] = "07/11/2026"
    r["details"]["date"].update(value="07/11/2026")
    item = {"id": "u1", "kind": "update", "orders": ["9100501"], "what": "Sam replied"}
    found = {f"9100501|{OFFERED}": {"lines": [_ln("9100501-1-1", "UNSCHEDULED", "20/11/26")],
                                     "veh": {"9100501-1-1": True}}}
    p = P.plan([item], [r], found)[0]
    assert p["set"].get("anyway") is True and not [c for c in p["checks"] if c["field"] == "already"], p
    assert p["set"]["deliver"].startswith("07/11/26") and any("20/11" in x for x in p["explain"])
    # once CTMS has the new day, a Veh Type means what it always meant
    found = {f"9100501|{OFFERED}": {"lines": [_ln("9100501-1-1", "UNSCHEDULED", "07/11/26")],
                                     "veh": {"9100501-1-1": True}}}
    p = P.plan([item], [r], found)[0]
    assert not p["set"].get("anyway") and [c for c in p["checks"] if c["field"] == "already"]


def test_the_look_up_never_undoes_a_network_rail_move_or_ticks_off_what_waits_for_one():
    moved = _asked(state="allowed", asked="07/11/2026")
    moved["delivery_date"], moved["id"] = "07/11/2026", T._key(["9100501"], "07/11/2026")
    lines = [_ln("9100501-1-1", "UNSCHEDULED", "20/11/26")]
    found = {"9100501|07/11/2026": {"lines": lines, "veh": {"9100501-1-1": True}}}
    assert C.nr_owed(moved, lines) == "07/11/2026"
    assert C.plan(found, [moved])["moved"] == []               # CTMS's old day isn't news: the to-do types the new
    item = {"id": "u1", "kind": "update", "orders": ["9100501"]}
    assert C.todo_done(found, [item], [moved]) == []
    assert C.todo_done(found, [item]) == ["u1"]                # without the tracker: as it always was
    held = _asked(state="sent")
    found = {f"9100501|{OFFERED}": {"lines": [_ln("9100501-1-1", "UNSCHEDULED", "20/11/26")],
                                     "veh": {"9100501-1-1": True}}}
    assert C.todo_done(found, [item], [held]) == []
    # booked meanwhile (no line open): done whatever - nothing is ever typed onto a booked line
    found = {"9100501|07/11/2026": {"lines": [_ln("9100501-1-1", "SCHEDULED", "20/11/26")]}}
    assert C.todo_done(found, [item], [moved]) == ["u1"]
    # CTMS on the new day: the move is in
    lines = [_ln("9100501-1-1", "UNSCHEDULED", "07/11/26")]
    assert C.nr_owed(moved, lines) is None


# ---------- his 25/11 rule: the collection against the availability date ----------
MON = "30/11/2026"                      # a Monday: the stock is available from it


def _site(r, day, time="08:00", sure="high"):
    """The site's reply on the record: its day, and its time (sure: how sure the parser was of it)."""
    r["details"]["date"].update(value=day, options=[day], confidence="high")
    r["details"]["time"] = {"earliest": time, "latest": "", "confidence": sure}
    return r


def test_collected_before_the_availability_date_is_asked_after_it_told_on_it_it_just_moves(monkeypatch):
    def plan(day, time="08:00", sure="high", road=FAR):
        monkeypatch.setattr(same_day, "road", lambda *a, **k: road)
        r = _site(_rec(date=MON), day, time, sure)
        return N.collect_plan(r, day)
    got = plan(MON)                                      # 08:00 Monday, a far site: the day before, so the Friday
    assert (got["verdict"], got["collect"]) == ("ask", "27/11/2026") and "before the 30/11" in got["why"]
    assert plan(MON, "09:30", road=NEAR)["verdict"] == "fine"   # near, the yard open in time: collected that day
    assert plan(MON, road=NEAR)["verdict"] == "ask"      # ...but not for 08:00: the yard opens 08:00, 40 min away
    assert plan("01/12/2026")["verdict"] == "fine"       # Tuesday 08:00: collected the Monday it's available
    # later in the same week is just a move (his 09/11 rule, kept 25/11: "Yes, just a move")
    got = plan("04/12/2026")                             # Friday 08:00: collected Thursday 03/12, same week
    assert (got["verdict"], got["collect"]) == ("fine", "03/12/2026") and "same week" in got["why"]
    got = plan("08/12/2026")                             # Tuesday 08:00 the week after: collected Monday 07/12
    assert (got["verdict"], got["collect"]) == ("tell", "07/12/2026") and "later than the 30/11" in got["why"]
    assert plan(MON, "14:00")["verdict"] == "fine"       # an afternoon delivery can be collected that morning
    assert plan(MON, "", sure="low")["undecided"] == "time"        # morning or afternoon decides it, not firm
    assert plan("09/12/2026", "", sure="low")["verdict"] == "tell"  # ...unless both days are a later week anyway
    assert plan("02/12/2026", "", sure="low")["verdict"] == "fine"  # ...or both the same week, on or after it
    nothing = _site(_rec(date=MON), MON)
    nothing["collections"] = []
    assert N.collect_plan(nothing, MON)["undecided"] == "availability"


def test_our_own_moves_never_change_the_availability_date():
    # moved by us 30/11 -> 04/12 (in CTMS, at his request); the site then confirms the 30th, 08:00, a far site
    r = _site(_rec(date="04/12/2026", avail=MON, date_was=MON, date_moved_by="CTMS"), MON)
    d = {"records": [r]}
    assert N.on_new_date(d, r, MON, "the site's reply") is False        # asked first: collected Friday 27/11
    nd = r["nr_date"]
    assert (nd["kind"], nd["collect"], nd["available"], nd["offered"]) == ("earlier", "27/11/2026", MON, "04/12/2026")
    assert "collection before the availability date" in nd["subject"] and "earlier delivery" not in nd["subject"]
    # a holding move of ours (available 20/11, moved by us to 16/12), and the site asks for Saturday 28/11 midday:
    # collected the Friday, after its availability - a heads-up, not a question
    r = _site(_rec(date="16/12/2026", avail="20/11/2026", materials="13x rails"), "28/11/2026", "12:00")
    d = {"records": [r]}
    assert N.on_new_date(d, r, "28/11/2026", "the site's reply") is True
    assert r["nr_date"]["kind"] == "later" and r["nr_date"]["collect"] == "27/11/2026"


def test_what_the_rule_cant_settle_is_drafted_and_held_never_sent():
    r = _site(_rec(date=MON), MON, "", sure="low")
    d = {"records": [r]}
    N.on_new_date(d, r, MON, "the site's reply")
    nd = r["nr_date"]
    assert nd["his"] == "time" and nd["state"] == "to_send" and "time isn't firm" in nd["held"]["why"]
    assert _judge(r, [])["do"] == "hold"
    # his firm time later (the audit puts it to the rule again): 14:00 - collected the Monday, nothing needed
    r["details"]["time"] = {"earliest": "14:00", "latest": "16:00", "confidence": "high"}
    assert N.audit(d, now=NOW) and r["nr_date"]["state"] == "dismissed" and r["nr_date"]["superseded_by"] == MON
    # no availability date at all: judged by the delivery days as before 25/11, and his to send or not
    r = _site(_rec(date=OFFERED), "07/11/2026")
    r["collections"] = []
    N.on_new_date({"records": [r]}, r, "07/11/2026", "the site's reply")
    assert r["nr_date"]["his"] == "availability" and r["nr_date"]["kind"] == "earlier"


def test_the_audit_puts_replies_from_before_the_rule_to_it():
    old = _site(_rec(order="9100801", date=MON), MON)                 # replied before 25/11: 08:00 Monday, far
    fine = _site(_rec(order="9100802", date="01/12/2026", avail=MON), "01/12/2026")
    done = _site(_rec(order="9100803", date=MON), MON)
    done["nr_date"] = {"kind": "earlier", "asked": MON, "offered": MON, "state": "sent"}
    d = {"records": [old, fine, done]}
    changed = N.audit(d, now=NOW)
    assert [r["orders"] for r, _ in changed] == [["9100801"]]
    nd = old["nr_date"]
    assert (nd["kind"], nd["state"], nd["collect"]) == ("earlier", "to_send", "27/11/2026") and not nd.get("his")
    assert "will not book it in until I hear back" in nd["message"]      # the site kept its own day
    assert "nr_date" not in fine and done["nr_date"]["state"] == "sent"
    assert N.audit(d, now=NOW) == []                                   # nothing new the second time
    # a reply that gives no one firm day (a choice of days) is his to confirm first - the audit leaves it
    choice = _site(_rec(order="9100804", date=MON), MON)
    choice["details"]["date"]["options"] = [MON, "01/12/2026"]
    assert N.audit({"records": [choice]}, now=NOW) == [] and "nr_date" not in choice


def test_a_draft_for_another_day_never_goes_and_a_sent_one_stops_counting():
    r = _site(_rec(), "07/11/2026")
    d = {"records": [r]}
    N.on_new_date(d, r, "07/11/2026", "the site's reply")              # an ask, still to send
    N.on_new_date(d, r, "21/11/2026", "your confirm")                  # then Saturday 21st: collected Fri 20/11
    old = r["nr_date"]
    assert old["state"] == "dismissed" and old["superseded_by"] == "21/11/2026" and r["delivery_date"] == "21/11/2026"
    # an ask that had gone: no answer of theirs moves anything now, and he's told to let them know it's off
    r = _site(_rec(), "07/11/2026")
    d = {"records": [r]}
    N.on_new_date(d, r, "07/11/2026", "the site's reply")
    r["nr_date"].update(state="sent", sent_at="2026-11-03 09:30")
    N.on_new_date(d, r, "21/11/2026", "your confirm")
    nd = r["nr_date"]
    assert nd["state"] == "dismissed" and "let them know it's off" in nd["held"]["why"]
    assert N.moved_to(r) is None and _judge(r, [])["do"] == "nothing"


def test_ctms_never_collects_before_the_availability_date_without_their_yes():
    item = {"id": "u1", "kind": "update", "orders": ["9100501"], "what": "Sam replied"}
    r = _site(_rec(date=MON), MON)                                     # 08:00 Monday, far: collected Fri 27/11
    p = P.plan([item], [r], {})[0]
    assert p["status"] == "held" and "collect" not in p["set"]
    assert any(c["field"] == "nr_collect" and "before the 30/11" in c["why"] for c in p["checks"])
    r["nr_date"] = {"kind": "earlier", "asked": MON, "offered": MON, "state": "allowed"}       # their yes
    p = P.plan([item], [r], {})[0]
    assert p["set"]["collect"].startswith("27/11/26") and not [c for c in p["checks"] if c["field"] == "nr_collect"]
    assert any("Network Rail said yes" in x for x in p["explain"])
    # an afternoon delivery on the availability day: collected that morning, never the Friday - and no question
    r = _site(_rec(date=MON), MON, "14:00")
    p = P.plan([item], [r], {})[0]
    assert p["set"]["collect"].startswith("30/11/26") and not [c for c in p["checks"] if c["field"] == "collect"]
    # an afternoon delivery the day before it's available: either day is too early - no pick asked, just their yes
    r = _site(_rec(date="27/11/2026", avail=MON), "27/11/2026", "14:00")
    p = P.plan([item], [r], {})[0]
    fields = [c["field"] for c in p["checks"]]
    assert "nr_collect" in fields and "collect" not in fields and "collect" not in p["set"]


# ---------- the home agent ----------
def test_the_agent_runs_it_on_a_timer_and_straight_after_a_reply_check(monkeypatch, tmp):
    import agent
    monkeypatch.setattr(agent, "BG_TIMERS", os.path.join(tmp, "timers.json"))
    jobs = {k: (args, every, enabled) for k, args, every, _t, enabled in agent._bg_jobs()}
    assert jobs["nr_date"][:2] == (["nr_date.py", "auto"], agent.NR_DATE_EVERY) and "nr_date" in agent.SEND_JOBS
    monkeypatch.setattr(agent, "_nr_auto", lambda: {"mode": "off", "why": "Auto follow-ups are off"})
    assert jobs["nr_date"][2]() is False                   # off: never started
    monkeypatch.setattr(agent, "_nr_auto", lambda: {"mode": "shadow", "why": ""})
    assert jobs["nr_date"][2]() is True
    pushed, said = [], []
    monkeypatch.setattr(agent, "push_tracker", lambda: pushed.append("tracker"))
    monkeypatch.setattr(agent, "push_panel", lambda: pushed.append("panel"))
    monkeypatch.setattr(agent, "report", lambda state, detail, *a, **k: said.append((state, detail)))
    monkeypatch.setattr(agent, "_review_pending", lambda: False)
    bg = agent.BackgroundJobs()
    monkeypatch.setattr(bg, "_output", lambda key, offset=0: "")
    now = 1_800_000_000.0
    bg.last["nr_date"] = now - 400
    bg._done("phase2_check", 0, now - 60, 0, now)          # new mail read: it looks next
    assert bg._due("nr_date", agent.NR_DATE_EVERY, now)
    bg.last["nr_date"] = now - 100
    bg._done("phase2_check", 0, now - 60, 0, now)          # ...but not again within a few minutes of its last
    assert not bg._due("nr_date", agent.NR_DATE_EVERY, now)
    out = ("SENT   9100501: SCO Sleepers & Troughing asked about 07/11 (sent to x)\n"
           "YES    9100502: Pat Example said yes (a clear yes) - moved to 07/11\n"
           'NR_RESULT {"ok": true, "did": 2, "mode": "live"}\n')
    monkeypatch.setattr(bg, "_output", lambda key, offset=0: out)
    bg._done("nr_date", 0, now - 30, 0, now)
    assert said[-1] == ("done", "Network Rail date emails: sent 9100501, yes 9100502.") and "panel" in pushed
    # never said over a review waiting on him (a batch to send, say): the card has it
    monkeypatch.setattr(agent, "_review_pending", lambda: True)
    n = len(said)
    bg._done("nr_date", 0, now - 30, 0, now)
    assert len(said) == n
    monkeypatch.setattr(agent, "_review_pending", lambda: False)
    # shadow: what it would do, said once
    out = 'WOULD SEND      9100501 (earlier 20/11/2026 -> 07/11/2026): the site\'s reply asks for it\nNR_RESULT {"ok": true, "did": 0, "mode": "shadow"}\n'
    monkeypatch.setattr(bg, "_output", lambda key, offset=0: out)
    n = len(said)
    bg._done("nr_date", 0, now - 30, 0, now)
    bg._done("nr_date", 0, now - 30, 0, now)
    assert len(said) == n + 1 and "shadow" in said[-1][1]
    # a run that fell over is said, and tried again soon
    bg._done("nr_date", 1, now - 30, 0, now)
    assert said[-1][0] == "error" and said[-1][1].startswith("The Network Rail date emails did not finish")
    assert bg.retry_at["nr_date"] == now + agent.BG_FAIL_RETRY
    # a mailbox it couldn't read: a safe stop, said once a day rather than every run
    monkeypatch.setattr(agent, "_said_today", {})
    out = ("ABORT  part of the mailbox couldn't be read, so an answer could be missed - nothing sent or decided: x\n"
           'NR_RESULT {"ok": true, "did": 0, "mode": "live"}\n')
    monkeypatch.setattr(bg, "_output", lambda key, offset=0: out)
    n = len(said)
    bg._done("nr_date", 0, now - 30, 0, now)
    bg._done("nr_date", 0, now - 30, 0, now)
    assert len(said) == n + 1 and said[-1][0] == "error" and "part of the mailbox" in said[-1][1]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_") and f.__code__.co_argcount == 0:
            f()
    print("ok")
