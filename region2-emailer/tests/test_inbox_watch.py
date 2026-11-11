"""Emails waiting for him (inbox_watch.py, 11/11): who counts as urgent, what counts as answered, what the desk already
deals with, and when the bell rings - in working minutes. Made-up people, orders and addresses only; no Outlook.

    python -m pytest tests/test_inbox_watch.py
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import inbox_watch as W  # noqa: E402

NOW = datetime(2026, 11, 11, 15, 0)                      # a Wednesday afternoon
HOLS = {"2026-12-25"}


def ctx(records=(), forms=()):
    return {"me": {"me.desk@dhl.example", "pat desk"}, "my_names": ["pat desk"], "managers": ["sam boss", "lee chief"],
            "materials": {"steelmaterials@nr.example"}, "haulier_addrs": {"ops@haul.example", "fleet@aol.com"},
            "haulier_domains": {"haul.example"}, "handled": W.taken_in(list(records), forms)}


def msg(**kw):
    mid = kw.pop("id", "m1")
    m = {"id": mid, "eid": "E-" + mid, "conv": "C-" + mid, "folder": "Inbox", "from_name": "Someone",
         "from_addr": "someone@site.example", "subject": "A question", "received": NOW - timedelta(hours=1),
         "unread": True, "verb": 0, "words": "Can you let me know?", "orders": [], "to_me": True, "crowd": False}
    m.update(kw)
    return m


NOBODY_SENT = {"conv": {}, "subject": {}, "ref": {}}


def test_working_minutes_skip_nights_weekends_and_bank_holidays():
    fri = datetime(2026, 11, 13, 16, 0)
    assert W.business_minutes(fri, datetime(2026, 11, 16, 8, 30)) == 60              # 30 Fri + 30 Mon
    assert W.business_minutes(datetime(2026, 11, 11, 18, 0), datetime(2026, 11, 12, 8, 10)) == 10
    assert W.business_minutes(datetime(2026, 12, 24, 16, 0), datetime(2026, 12, 28, 8, 0), HOLS) == 30
    assert W.business_minutes(NOW, NOW - timedelta(hours=1)) == 0
    assert W.waited_text(45) == "45 min" and W.waited_text(130) == "2 h 10 min"
    assert W.waited_text(510 + 120) == "1 working day 2 h" and W.waited_text(1020) == "2 working days"


def test_who_it_is_from_decides_how_soon_it_matters():
    c = ctx()
    assert W.weigh(msg(from_name="Sam Boss (Company)", from_addr="sam.boss@dhl.com"), c) == (
        "urgent", "your manager asks")
    assert W.weigh(msg(subject="RE: Region 2 Updates 11/11", from_name="Sam Boss"), c)[1].startswith("the day's Region 2")
    assert W.weigh(msg(words="We need this delivered today please"), c) == ("urgent", 'says "today"')
    assert W.weigh(msg(words="Still waiting on this", to_me=False), c)[0] == "high"     # copied in: one step down
    assert W.weigh(msg(from_name="Steel Materials", from_addr="steelmaterials@nr.example"), c)[0] == "high"
    assert W.weigh(msg(from_name="Order Management", from_addr="om@nr.example"), c)[0] == "high"
    assert W.weigh(msg(from_addr="a.person@networkrail.co.uk", subject="Delivery Query for: 9100001"), c) == (
        "high", "a Network Rail query")
    assert W.weigh(msg(from_addr="planner@haul.example"), c) == ("normal", "a haulier asking")
    assert W.weigh(msg(from_addr="planner@haul.example", words="New date for this one is Friday"), c) == (
        "high", 'a haulier: "new date"')                         # a change needs passing on, asked or not
    assert W.weigh(msg(from_addr="fleet@aol.com"), c)[0] == "normal"                    # a haulier on webmail, by address
    assert W.weigh(msg(from_addr="someone@aol.com"), c) == ("normal", "asks you")      # ... not everyone on it
    assert W.weigh(msg(folder="Inbox\\ADHOC\\DTS"), c) == ("high", "a DTS")
    assert W.weigh(msg(from_addr="colleague@dhl.com"), c) == ("normal", "a colleague asking")
    assert W.weigh(msg(), c) == ("normal", "asks you")
    assert W.weigh(msg(to_me=False), c) == ("low", "asks you (copied in)")
    assert W.weigh(msg(crowd=True), c) == ("low", "asks you (round-robin)")
    # nothing for him: his own, automatic, a notice
    assert W.weigh(msg(from_addr="me.desk@dhl.example"), c) is None
    assert W.weigh(msg(from_name="Pat Desk (Company)"), c) is None
    assert W.weigh(msg(from_addr="noreply@system.example"), c) is None
    assert W.weigh(msg(subject="Automatic reply: A question"), c) is None
    assert W.weigh(msg(subject="Undeliverable: A question"), c) is None
    assert W.weigh(msg(subject="Accepted: Catch up"), c) is None


def test_what_asks_him_nothing_needs_no_reply():
    # his 11/11: "some of the things you flagged don't even need a reply"
    c = ctx()
    boss = dict(from_name="Sam Boss", from_addr="sam.boss@dhl.com")
    assert W.weigh(msg(words="Hi All See attached updated planner for today", **boss), c) is None
    assert W.weigh(msg(words="Next week's rota is attached.", **boss), c) is None
    assert W.weigh(msg(words="Thank you."), c) is None
    assert W.weigh(msg(words="Please see attached. Please find the POD attached."), c) is None
    assert W.weigh(msg(subject="RE: Derailment confirmations", words="Hello 9100001 - Delivered on the 28th"), c) is None
    assert W.weigh(msg(from_addr="planner@haul.example", words="Now covered, thanks"), c) is None
    # ...nor does a note to someone else on the thread
    assert W.weigh(msg(words="Hi Lee Yes the sleepers are being delivered tomorrow for you", **boss), c) is None
    assert W.weigh(msg(words="OFFICIAL\nHi Jo, Sorry for the delay. How can I help with the delivery?"), c) is None
    # but a question or a request to him, or to everyone, does
    assert W.weigh(msg(words="Hi Pat, can you get the haulier to send the first page?", **boss), c) == (
        "urgent", "your manager asks")
    assert W.weigh(msg(words="Hi all, could someone cover this on Friday?"), c) is not None
    assert W.weigh(msg(words="Hi Jo and Pat, when can this be delivered"), c) is not None
    assert W.weigh(msg(words="Morning, any update on this one"), c) is not None
    assert W.weigh(msg(words="Hi, Can you confirm the time?"), c) is not None
    assert W.weigh(msg(words="Dear Sir/Madam, could you advise on the delivery?"), c) is not None
    assert W.weigh(msg(words="Please book this in for Tuesday"), c) is not None
    assert W.weigh(msg(subject="Delivery tomorrow?", words="Sent from my phone"), c) is not None


def test_only_the_inbox_is_read_filed_is_dealt_with():
    assert W.FOLDERS == (("Inbox",),)                     # his rule: filed into a folder = dealt with


def test_answered_means_a_reply_a_forward_or_anything_he_sent_since_on_it():
    m = msg(orders=["9100001"])
    assert W.answered(dict(m, verb=102), NOBODY_SENT) and W.answered(dict(m, verb=104), NOBODY_SENT)
    later, earlier = m["received"] + timedelta(minutes=5), m["received"] - timedelta(minutes=5)
    assert W.answered(m, {"conv": {"C-m1": [later]}, "subject": {}, "ref": {}})
    assert not W.answered(m, {"conv": {"C-m1": [earlier]}, "subject": {}, "ref": {}})      # before it came
    assert W.answered(m, {"conv": {}, "subject": {"a question": [later]}, "ref": {}})       # RE:/FW: aside
    # acted on: anything he sent since naming its order - to anyone (the haulier, for his manager's ask)
    assert W.answered(m, {"conv": {}, "subject": {}, "ref": {"9100001": [later]}})
    assert not W.answered(m, {"conv": {}, "subject": {}, "ref": {"9100001": [earlier]}})
    assert not W.answered(m, {"conv": {}, "subject": {}, "ref": {"9100002": [later]}})
    assert W._norm_subject("RE: FW: EXT: A question") == "a question"
    # the day's updates: only his reply answers them - not a forward, nor an email to his manager about one listed order
    up = msg(subject="RE: Region 2 Updates 11/11", from_addr="sam.boss@dhl.example", orders=["9100001"])
    assert not W.answered(dict(up, verb=104), NOBODY_SENT) and W.answered(dict(up, verb=102), NOBODY_SENT)
    assert not W.answered(up, {"conv": {}, "subject": {}, "ref": {"9100001": [later]}})
    assert W.answered(up, {"conv": {"C-m1": [later]}, "subject": {}, "ref": {}})


def test_what_the_tracker_took_in_and_forms_on_the_map_stay_off_but_a_colleague_s_email_does_not():
    rec = {"orders": ["9100001"], "to": "site@site.example", "reply_at": "2026-11-11 13:03",
           "needs_info": {"at": "2026-11-10 09:00"}}
    c = ctx([rec], forms=["FORM-EID"])
    took = msg(orders=["9100001"], received=datetime(2026, 11, 11, 13, 0))               # the reply it noted at 13:03
    assert W.weigh(took, c) is None
    assert W.weigh(msg(orders=["9100001"], received=datetime(2026, 11, 11, 9, 0)), c) is not None  # a different email
    assert W.weigh(dict(took, from_addr="boss@dhl.com"), c) is not None                   # a colleague about it
    assert W.weigh(dict(msg(id="form", folder="Inbox\\ADHOC"), eid="FORM-EID"), c) is None


def test_the_list_puts_what_is_past_its_time_first_and_rings_by_priority():
    c = ctx()
    msgs = [msg(id="old-normal", received=NOW - timedelta(hours=3)),                       # 180 min: past 120
            msg(id="new-normal", received=NOW - timedelta(minutes=50)),
            msg(id="boss", from_name="Sam Boss", received=NOW - timedelta(minutes=40)),    # 40 min: past 30
            msg(id="haulier", from_addr="ops@haul.example", received=NOW - timedelta(minutes=50)),   # not yet 60
            msg(id="update", from_name="Lee Chief", subject="RE: Region 2 Updates 11/11",
                received=NOW - timedelta(minutes=90)),                                        # its own 120
            msg(id="answered", verb=103),
            msg(id="stale", received=NOW - timedelta(days=4)),                                 # normal: 3 days back
            msg(id="cc", to_me=False, received=NOW - timedelta(hours=5)),
            msg(id="dealt", received=NOW - timedelta(hours=5))]
    out = W.judge(msgs, NOBODY_SENT, c, NOW, HOLS, dealt={"dealt"})
    assert [(i["id"], i["alarm"]) for i in out] == [
        ("boss", True), ("old-normal", True), ("update", False), ("new-normal", False), ("haulier", False),
        ("cc", False)]
    boss = out[0]
    assert boss["pri"] == "urgent" and boss["waited"] == "40 min" and boss["received"] == "11/11 14:20"
    p = W.panel({"items": out, "at": "11/11 15:00"})
    assert [i["id"] for i in p["items"]] == ["boss", "old-normal", "update", "new-normal", "haulier"]
    assert p["low"] == 1 and p["alarms"] == 2


def test_dealt_with_takes_it_off_and_keeps_it_off():
    folder = tempfile.mkdtemp()
    keep = W.PATH
    W.PATH = os.path.join(folder, "_inbox_watch.json")
    try:
        W.save({"items": [{"id": "abc", "ids": ["abc", "abd"], "pri": "urgent", "alarm": True}], "dealt": {}})

        def run(*argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = W.main(["inbox_watch.py", *argv])
            return code, json.loads(buf.getvalue().strip().splitlines()[-1])
        assert run("dealt", "abc") == (0, {"ok": True, "said": "Taken off - dealt with."})
        d = W.load()
        assert d["items"] == [] and {"abc", "abd"} <= set(d["dealt"])                  # the whole thread
        assert run("dealt", "abc")[0] == 1                                                     # gone already
        out = W.judge([msg(id="abc")], NOBODY_SENT, ctx(), NOW, dealt=set(d["dealt"]))
        assert out == []
    finally:
        W.PATH = keep


def test_order_numbers_ad_hoc_and_dts_refs_are_picked_out():
    assert W.orders_in("RE: 9100001 / 9100002 Somewhere", "AH12/11/26ABC1 and NN1234567-89, not 91000011") == [
        "9100001", "9100002", "AH12/11/26ABC1", "NN1234567-89"]
    # manifests and NR requests too, however they're written - what a POD ask and the email to the haulier share
    assert W.orders_in("FW: order tomorrow RD100001/9100003", "manifest 261017-MAN-01500001 and MAN01500002") == [
        "9100003", "MAN-01500001", "MAN-01500002", "RD100001"]


def test_one_line_a_thread_its_most_pressing_reason_waiting_since_the_first_unanswered():
    c = ctx()
    thread = [msg(id="t1", received=NOW - timedelta(hours=3)),
              msg(id="t2", words="Chasing this please", received=NOW - timedelta(hours=1)),
              msg(id="t3", words="Any news?", received=NOW - timedelta(minutes=20))]
    for m in thread:
        m["conv"] = "THREAD"
    other = msg(id="o1", received=NOW - timedelta(minutes=10))
    out = W.judge(thread + [other], NOBODY_SENT, c, NOW)
    first = out[0]
    assert (first["id"], first["n"], first["pri"], first["why"], first["mins"]) == (
        "t3", 3, "urgent", 'says "chasing"', 180)
    assert first["ids"] == ["t1", "t2", "t3"] and first["alarm"] and first["received"] == "11/11 14:40"
    assert [i["id"] for i in out] == ["t3", "o1"]
    # answered in the thread since: only what came after his reply still counts
    sent = {"conv": {"THREAD": [NOW - timedelta(minutes=30)]}, "subject": {}, "ref": {}}
    out = W.judge(thread, sent, c, NOW)
    assert [(i["id"], i["n"]) for i in out] == [("t3", 1)]
