"""Plain-assert tests for the chaser's reply rules - no Outlook needed.

Every case is a real chaser from Sent Items (29/06-02/10/2026), labelled by
hand: did a reply already exist when it went out? The idx numbers refer to
that audit.

Run:  python region2-emailer/tests/test_chase_rules.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules import chase_rules as cr  # noqa: E402

ME = {"delali.opoku@dhl.com", "delali.opoku@networkrail.co.uk"}
CTX = {"me": ME, "internal_domains": ("dhl.com",), "team_names": {"zoe mccutcheon"},
       "haulier_addresses": {"kevin@gundeltransport.com"}, "haulier_domains": {"gundeltransport.com",
                                                                               "blakes-slv.co.uk"},
       "haulier_orders": set(), "state": {}, "holidays": ()}


def T(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def out(at, to, subject, conv="", cc=(), eid=None):
    return {"at": T(at), "dir": "out", "from": "delali.opoku@dhl.com", "from_name": "Delali",
            "to": [to] if isinstance(to, str) else list(to), "cc": list(cc), "subject": subject,
            "conv": conv, "eid": eid or f"o-{at}", "folder": "/Sent Items", "auto": False, "ndr": False}


def inn(at, frm, subject, conv="", name="", folder="/Inbox/Regions/Region 2/Completed", auto=False,
        ndr=False, eid=None):
    return {"at": T(at), "dir": "in", "from": frm, "from_name": name, "to": [], "cc": [],
            "subject": subject, "conv": conv, "eid": eid or f"i-{at}-{frm}", "folder": folder,
            "auto": auto, "ndr": ndr}


def rec(orders, to, emailed, delivery="31/12/2026", chases=0, **kw):
    r = {"orders": orders, "to": to, "emailed_at": emailed, "last_emailed_at": emailed,
         "chases": chases, "delivery_date": delivery, "status": "sent"}
    r.update(kw)
    return r


def run(r, mails, now, texts=None, ctx=None):
    texts = texts or {}
    return cr.assess(r, mails, dict(CTX, **(ctx or {})), lambda eid: texts.get(eid, ""), T(now))


def test_reply_filed_in_completed_on_another_thread_blocks():
    # idx 6 - 5033351 / Andrew Gilliver: full answer 06/07 under "Re: 5033351",
    # filed in Completed, different ConversationID from the chaser.
    r = rec(["5033351"], "andrew.gilliver@networkrail.co.uk", "2026-07-03 09:00")
    mails = [out("2026-07-03 09:00", "andrew.gilliver@networkrail.co.uk", "5033351 Doncaster Woodyard", "A"),
             inn("2026-07-06 10:34", "andrew.gilliver@networkrail.co.uk",
                 "Re: 5033351 Doncaster Woodyard", "B")]
    d = run(r, mails, "2026-07-08 17:15")
    assert d["action"] == cr.BLOCK, d
    assert "Completed" in d["evidence"]["folder"]


def test_reply_about_a_sibling_order_holds_never_blocks():
    # idx 7 - 6054932/3: he only wrote about 5033351 (same site), so not a reply
    # to these - but he IS in touch, so hold for Delali rather than chase blind.
    r = rec(["6054932", "6054933"], "andrew.gilliver@networkrail.co.uk", "2026-07-03 09:05")
    mails = [out("2026-07-03 09:05", "andrew.gilliver@networkrail.co.uk", "6054932 / 6054933 Doncaster", "C"),
             inn("2026-07-06 10:34", "andrew.gilliver@networkrail.co.uk",
                 "Re: 5033351 Doncaster Woodyard", "B")]
    assert run(r, mails, "2026-07-07 10:00")["action"] == cr.HOLD       # he wrote yesterday: hold
    d = run(r, mails, "2026-07-08 17:15")                               # 2 business days on: lapsed
    assert d["action"] == cr.SEND, d                                    # never BLOCK


def test_no_reply_at_all_sends():
    # idx 9 - 5032847 / David Lloyd: nothing came back.
    r = rec(["5032847"], "david.lloyd3@networkrail.co.uk", "2026-07-06 10:00")
    mails = [out("2026-07-06 10:00", "david.lloyd3@networkrail.co.uk", "5032847 Site", "D")]
    d = run(r, mails, "2026-07-09 10:45")
    assert d["action"] == cr.SEND, d


def test_colleague_on_the_thread_answering_blocks():
    # idx 60 - 6055570: Greg answered for Richard. Greg was copied on the ask.
    r = rec(["6055570"], "richard.chappelow@networkrail.co.uk", "2026-09-01 09:00")
    mails = [out("2026-09-01 09:00", "richard.chappelow@networkrail.co.uk", "6055570 Site", "E",
                 cc=["greg.smith@networkrail.co.uk"]),
             inn("2026-09-02 08:00", "greg.smith@networkrail.co.uk", "RE: 6055570 Site", "E")]
    d = run(r, mails, "2026-09-04 10:00")
    assert d["action"] == cr.BLOCK, d


def test_stranger_writing_about_the_order_holds():
    # Someone never emailed (not on the thread, shared NR domain) writes with
    # the order in the subject: not proof, but never chase blind.
    r = rec(["6055570"], "richard.chappelow@networkrail.co.uk", "2026-09-01 09:00")
    mails = [out("2026-09-01 09:00", "richard.chappelow@networkrail.co.uk", "6055570 Site", "E"),
             inn("2026-09-02 08:00", "someone.else@networkrail.co.uk", "RE: 6055570 Site", "Z")]
    d = run(r, mails, "2026-09-04 10:00")
    assert d["action"] == cr.HOLD, d


def test_out_of_office_is_not_a_reply_but_the_later_answer_is():
    # idx 38 - 6055351 / Ian Langham: OOO 31/07, real reply 03/08 06:38.
    r = rec(["6055351"], "ian.langham@networkrail.co.uk", "2026-07-29 09:00")
    m = [out("2026-07-29 09:00", "ian.langham@networkrail.co.uk", "6055351 Site", "F"),
         inn("2026-07-31 09:00", "ian.langham@networkrail.co.uk", "Automatic reply: 6055351 Site", "F",
             auto=True)]
    assert run(r, m, "2026-08-02 10:00")["action"] == cr.HOLD          # OOO alone: hold
    m.append(inn("2026-08-03 06:38", "ian.langham@networkrail.co.uk", "RE: 6055351 Site", "F"))
    assert run(r, m, "2026-08-03 10:53")["action"] == cr.BLOCK


def test_internal_forwards_and_our_drafts_are_not_replies():
    # idx 37 - ignore DHL forwards, our own SEND OUT drafts (blank sender),
    # and the order desk; nothing else came back -> chase is fair.
    r = rec(["6055351"], "ian.langham@networkrail.co.uk", "2026-07-20 09:00")
    mails = [out("2026-07-20 09:00", "ian.langham@networkrail.co.uk", "6055351 Site", "G"),
             inn("2026-07-21 09:00", "zoe.mccutcheon@dhl.com", "FW: 6055351 Site", "G",
                 name="Zoe McCutcheon (DHL Supply Chain)"),
             inn("2026-07-21 09:10", "", "SEND OUT: 6055351 Site", "", folder="/Inbox/Regions/Region 2/Send Out"),
             inn("2026-07-21 09:20", "orders@networkrail.co.uk", "NWR Order Received 6055351", "")]
    d = run(r, mails, "2026-07-24 10:00")
    assert d["action"] == cr.SEND, d


def test_haulier_quote_is_not_the_site_replying_and_ring_round_stops_it():
    # idx 64 - 5033942: Gundel's quote is not the site answering. A ring-round
    # already went out for the order, so details are in hand: STOP.
    r = rec(["5033942"], "michael.evans@networkrail.co.uk", "2026-09-07 09:00", delivery="20/09/2026")
    mails = [out("2026-09-07 09:00", "michael.evans@networkrail.co.uk", "5033942 Site", "H"),
             inn("2026-09-09 09:00", "kevin@gundeltransport.com", "RE: 5033942 Delivery", "R")]
    d = run(r, mails, "2026-09-10 10:00")
    assert d["action"] == cr.SEND, d                       # the quote alone changes nothing
    d = run(r, mails, "2026-09-10 10:00", ctx={"haulier_orders": {"5033942"}})
    assert d["action"] == cr.STOP, d


def test_question_back_minutes_before_blocks():
    # idx 52 - 6055400/02 / Ernesta: question back 2.6 minutes before. The
    # company number SC156416 in her signature is not an order.
    r = rec(["6055400", "6055402"], "ernesta.ziogelyte@voestalpine.com", "2026-09-10 09:00")
    mails = [out("2026-09-10 09:00", "ernesta.ziogelyte@voestalpine.com", "6055400 / 6055402 VAE", "J"),
             inn("2026-09-14 11:57", "ernesta.ziogelyte@voestalpine.com", "RE: 6055400 / 6055402 VAE", "J")]
    d = run(r, mails, "2026-09-14 12:00")
    assert d["action"] == cr.BLOCK, d


def test_reply_from_same_supplier_company_blocks():
    # idx 3 - anderton.rail answered; the chaser was to anderton.transport.
    r = rec(["6055183"], "anderton.transport@ibstock.co.uk", "2026-06-26 09:00")
    mails = [out("2026-06-26 09:00", "anderton.transport@ibstock.co.uk", "6055183 Collection Details", "K"),
             inn("2026-06-29 15:49", "anderton.rail@ibstock.co.uk", "RE: 6055183 Collection Details", "K")]
    d = run(r, mails, "2026-06-29 16:11")
    assert d["action"] == cr.BLOCK, d


def test_order_only_in_their_text_blocks():
    r = rec(["7116026"], "christopher.jeary@networkrail.co.uk", "2026-10-01 09:00")
    mails = [out("2026-10-01 09:00", "christopher.jeary@networkrail.co.uk", "7116026 Norwich", "L"),
             inn("2026-10-02 13:22", "christopher.jeary@networkrail.co.uk", "Norwich delivery", "M",
                 eid="x1")]
    texts = {"x1": "Hi, for 7116026 rear steer is just preferred.\n\nFrom: Delali\n..."}
    assert run(r, mails, "2026-10-06 10:00", texts)["action"] == cr.BLOCK
    # ...but the number only in the QUOTED part is not their text
    texts = {"x1": "Hi, see you Monday.\n\nFrom: Delali\nSubject: 7116026"}
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] == cr.HOLD   # in touch, not a reply
    assert run(r, mails, "2026-10-06 10:00", texts)["action"] == cr.SEND   # ...and the hold lapses


def test_delivery_date_reached_stops():
    # idx 34 - 5033605 was delivered on 03/07 and chased five more times.
    r = rec(["5033605"], "kyle.broughton@networkrail.co.uk", "2026-06-25 09:00", delivery="03/07/2026")
    mails = [out("2026-06-25 09:00", "kyle.broughton@networkrail.co.uk", "5033605 Site", "N")]
    assert run(r, mails, "2026-07-10 10:00")["action"] == cr.STOP
    assert run(r, mails, "2026-07-03 10:00")["action"] == cr.STOP       # on the day too


def test_reply_to_an_earlier_ask_survives_re_enrolment():
    # idx 34 again: the record was re-enrolled later, but the reply came to the
    # FIRST ask - which is in Sent Items - so it still counts.
    r = rec(["5033605"], "kyle.broughton@networkrail.co.uk", "2026-07-17 12:00", delivery="31/07/2026")
    mails = [out("2026-06-25 09:00", "kyle.broughton@networkrail.co.uk", "5033605 Site", "N"),
             inn("2026-06-26 09:00", "kyle.broughton@networkrail.co.uk", "RE: 5033605 Site", "N")]
    assert run(r, mails, "2026-07-21 07:36")["action"] == cr.BLOCK


def test_booked_in_by_you_stops():
    r = rec(["7116137"], "dave.robinson@networkrail.co.uk", "2026-09-28 09:00")
    mails = [out("2026-09-28 09:00", "dave.robinson@networkrail.co.uk", "7116137 Doncaster", "P"),
             out("2026-10-01 09:00", "dave.robinson@networkrail.co.uk", "RE: 7116137 Doncaster", "P", eid="b1")]
    texts = {"b1": "Hi Dave, this is booked in for Monday. MAN-01572653"}
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] == cr.STOP


def test_bounced_ask_stops():
    r = rec(["7115311"], "martyn.singleton@netoworkrail.co.uk", "2026-08-06 09:00")
    mails = [out("2026-08-06 09:00", "martyn.singleton@netoworkrail.co.uk", "7115311 Site", "Q"),
             inn("2026-08-06 09:01", "postmaster@dhl.com", "Undeliverable: 7115311 Site", "", ndr=True,
                 eid="ndr1")]
    texts = {"ndr1": "Delivery has failed to these recipients: martyn.singleton@netoworkrail.co.uk"}
    assert run(r, mails, "2026-08-10 10:00", texts)["action"] == cr.STOP
    # a bounce of some other address is not "your ask bounced"
    texts = {"ndr1": "Delivery has failed to these recipients: someone.else@example.com"}
    assert run(r, mails, "2026-08-10 10:00", texts)["action"] == cr.SEND


def test_timing_two_business_days_since_the_last_email_and_a_cap():
    r = rec(["5032847"], "david.lloyd3@networkrail.co.uk", "2026-07-09 10:00")    # a Thursday
    mails = [out("2026-07-09 10:00", "david.lloyd3@networkrail.co.uk", "5032847 Site", "D")]
    assert run(r, mails, "2026-07-10 10:00")["action"] == cr.WAIT      # Fri: 1 business day
    assert run(r, mails, "2026-07-12 10:00")["action"] == cr.WAIT      # Sun: still 1
    assert run(r, mails, "2026-07-13 10:00")["action"] == cr.SEND      # Mon: 2
    # a chase on Monday resets the clock - never chased on consecutive days
    mails.append(out("2026-07-13 10:00", "david.lloyd3@networkrail.co.uk", "5032847 Site", "D2"))
    assert run(r, mails, "2026-07-14 10:00")["action"] == cr.WAIT
    assert run(r, mails, "2026-07-15 10:00")["action"] == cr.SEND      # chase #2
    mails.append(out("2026-07-15 10:00", "david.lloyd3@networkrail.co.uk", "5032847 Site", "D3"))
    assert run(r, mails, "2026-07-20 10:00")["action"] == cr.STOP      # two chases: over to Delali


def test_remembered_reply_blocks_a_duplicate_record_and_rearm_reopens():
    st = {"5033605|kyle.broughton@networkrail.co.uk": {"blocked": True, "why": "replied 19/07"}}
    r = rec(["5033605"], "kyle.broughton@networkrail.co.uk", "2026-07-17 12:00")
    assert run(r, [], "2026-07-21 10:00", ctx={"state": st})["action"] == cr.BLOCK
    st["5033605|kyle.broughton@networkrail.co.uk"]["rearmed_at"] = "2026-07-21 10:00"
    mails = [inn("2026-07-19 20:13", "kyle.broughton@networkrail.co.uk", "RE: 5033605 Site", "N")]
    # the old reply is before the re-arm, so it no longer blocks; the clock restarts
    d = run(r, mails, "2026-07-22 10:00", ctx={"state": st})
    assert d["action"] == cr.WAIT, d
    assert run(r, mails, "2026-07-23 10:00", ctx={"state": st})["action"] == cr.SEND


def test_no_external_contact_stops():
    # idx 22/24 - "chased" Delali himself
    r = rec(["5033540"], "Delali Opoku (DHL Supply Chain) <delali.opoku@dhl.com>", "2026-07-10 09:00")
    assert run(r, [], "2026-07-17 12:37")["action"] == cr.STOP


def test_one_chaser_per_contact_per_run():
    a = rec(["5033351"], "andrew.gilliver@networkrail.co.uk", "2026-07-03 09:00", delivery="14/07/2026")
    b = rec(["6054932"], "andrew.gilliver@networkrail.co.uk", "2026-07-03 09:00", delivery="20/07/2026")
    c = rec(["5032847"], "david.lloyd3@networkrail.co.uk", "2026-07-03 09:00", delivery="25/07/2026")
    decs = [(r, {"action": cr.SEND, "reason": "", "evidence": None}) for r in (b, a, c)]
    picked = cr.one_per_contact(decs)
    assert [p[0]["orders"] for p in picked] == [["5033351"], ["5032847"]]   # soonest delivery first
    assert decs[0][1]["action"] == cr.WAIT                                    # b waits


def test_working_hours():
    assert cr.in_working_hours(T("2026-10-05 08:00"))           # Monday 08:00
    assert not cr.in_working_hours(T("2026-10-05 16:30"))
    assert not cr.in_working_hours(T("2026-10-04 10:00"))       # Sunday


def test_reply_mails_for_the_reply_check_and_earliest_across_months():
    # The reply check uses the same rules; a haulier quote is never "the reply".
    r = rec(["6055404"], "gareth.baxter@voestalpine.com", "2026-09-15 09:00")
    mails = [out("2026-09-15 09:00", "gareth.baxter@voestalpine.com", "6055404 VAE", "S"),
             inn("2026-09-16 09:00", "kevin@gundeltransport.com", "RE: 6055404 Delivery", "R"),
             inn("2026-10-01 08:00", "ernesta.ziogelyte@voestalpine.com", "RE: 6055404 VAE", "S"),
             inn("2026-09-30 10:00", "ernesta.ziogelyte@voestalpine.com", "RE: 6055404 VAE", "S")]
    replies, ooo = cr.reply_mails(r, mails, CTX, lambda e: "", T("2026-10-02 10:00"))
    assert [m["at"] for m in replies] == [T("2026-09-30 10:00"), T("2026-10-01 08:00")], replies
    d = run(r, mails, "2026-10-02 10:00")
    assert d["action"] == cr.BLOCK and d["evidence"]["ts"] == "2026-09-30 10:00", d   # 30/09, not 01/10


def test_booked_wording():
    assert cr.booked_in("Hi,\n\nThis order has been arranged with Lawsons. Here is the ref number MAN-01563625")
    assert cr.booked_in("booked in")
    assert cr.booked_in("All booked in for Monday, thanks")
    assert not cr.booked_in("No, I've already got what I need, I'll let you know when its booked in.")
    assert not cr.booked_in("Has this been booked in?")
    assert not cr.booked_in("It's not been booked in yet")


def test_colleague_forwarding_the_contacts_answer_blocks():
    # a reply that reached Delali only as a forward (NR alias / colleague)
    r = rec(["7116043"], "nicholas.holloway@networkrail.co.uk", "2026-09-30 09:12")
    mails = [out("2026-09-30 09:12", "nicholas.holloway@networkrail.co.uk", "7116043 Bordesley", "U"),
             inn("2026-10-01 10:00", "elizabeth.lagoudaki@dhl.com", "FW: RE: 7116043 Bordesley", "U",
                 name="Elizabeth Lagoudaki (DHL Supply Chain)", eid="f1")]
    texts = {"f1": "FYI\n\nFrom: Nicholas Holloway <nicholas.holloway@networkrail.co.uk>\nSent: ...\n"
                   "Tuesday 08:00, HIAB please"}
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] == cr.BLOCK
    # from Delali's own NR alias too
    mails[1] = inn("2026-10-01 10:00", "delali.opoku@networkrail.co.uk", "FW: RE: 7116043 Bordesley", "U",
                   eid="f1")
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] == cr.BLOCK


def test_the_contacts_own_reply_counts_whatever_the_subject_or_address_book_says():
    # a site contact titling their mail like a ring-round, or listed as a haulier
    r = rec(["7116043"], "nicholas.holloway@networkrail.co.uk", "2026-09-30 09:12")
    mails = [out("2026-09-30 09:12", "nicholas.holloway@networkrail.co.uk", "7116043 Bordesley", "U"),
             inn("2026-10-01 10:00", "nicholas.holloway@networkrail.co.uk", "7116043 Delivery", "V")]
    assert run(r, mails, "2026-10-05 10:00")["action"] == cr.BLOCK
    ctx = {"haulier_addresses": {"nicholas.holloway@networkrail.co.uk"}}
    mails[1]["subject"] = "RE: 7116043 Bordesley"
    assert run(r, mails, "2026-10-05 10:00", ctx=ctx)["action"] == cr.BLOCK


def test_an_email_that_cannot_be_read_holds():
    r = rec(["7116043"], "nicholas.holloway@networkrail.co.uk", "2026-09-30 09:12")
    mails = [out("2026-09-30 09:12", "nicholas.holloway@networkrail.co.uk", "7116043 Bordesley", "U"),
             inn("2026-10-01 10:00", "nicholas.holloway@networkrail.co.uk", "Bordesley", "W", eid="u1")]
    d = cr.assess(r, mails, CTX, lambda eid: None, T("2026-10-05 10:00"))
    assert d["action"] == cr.HOLD and "could not be read" in d["reason"], d


def test_out_of_office_hold_lapses_and_unrelated_auto_replies_do_not_count():
    r = rec(["6055351"], "ian.langham@networkrail.co.uk", "2026-07-29 09:00")
    m = [out("2026-07-29 09:00", "ian.langham@networkrail.co.uk", "6055351 Site", "F"),
         inn("2026-07-29 09:01", "ian.langham@networkrail.co.uk", "Automatic reply: 6055351 Site", "F",
             auto=True)]
    assert run(r, m, "2026-07-31 10:00")["action"] == cr.HOLD
    assert run(r, m, "2026-08-10 10:00")["action"] == cr.SEND          # 5+ business days: resume
    # an auto-reply to some other email of his, days later, is not about this ask
    m[1] = inn("2026-07-31 15:00", "ian.langham@networkrail.co.uk", "Automatic reply: Rota", "X", auto=True)
    assert run(r, m, "2026-08-03 10:00")["action"] == cr.SEND


def test_booked_needs_to_be_this_order_and_a_booking():
    r = rec(["7116137"], "dave.robinson@networkrail.co.uk", "2026-09-28 09:00")
    mails = [out("2026-09-28 09:00", "dave.robinson@networkrail.co.uk", "7116137 Doncaster", "P"),
             out("2026-09-29 09:00", "dave.robinson@networkrail.co.uk", "RE: 7116137 / 7116138 Doncaster",
                 "P", eid="b1")]
    texts = {"b1": "Hi Dave, can you send the window so I can get this booked in?"}
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] != cr.STOP
    texts = {"b1": "Hi Dave, 7116138 is with NOC MAN-01572653, still need yours"}
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] != cr.STOP
    texts = {"b1": "Hi Dave, 7116137 is booked in for Monday."}
    assert run(r, mails, "2026-10-05 10:00", texts)["action"] == cr.STOP


def test_haulier_asked_before_our_ask_does_not_stop():
    r = rec(["5033942"], "michael.evans@networkrail.co.uk", "2026-09-07 09:00", delivery="20/09/2026")
    mails = [out("2026-09-07 09:00", "michael.evans@networkrail.co.uk", "5033942 Site", "H")]
    early = {"haulier_orders": {"5033942": ["01/09/2026 09:00"]}}
    later = {"haulier_orders": {"5033942": ["08/09/2026 09:00"]}}
    assert run(r, mails, "2026-09-10 10:00", ctx=early)["action"] == cr.SEND
    assert run(r, mails, "2026-09-10 10:00", ctx=later)["action"] == cr.STOP


def test_reply_on_the_tracker_blocks_and_collection_names_resolve():
    r = rec(["5032847"], "david.lloyd3@networkrail.co.uk", "2026-07-06 10:00", reply_at="2026-05-01 09:00")
    assert run(r, [], "2026-07-09 10:00")["action"] == cr.BLOCK
    # a supplier collection record: To holds display names; the adapter adds addresses
    c = rec(["6055183"], "Anderton Rail; Anderton Transport", "2026-06-26 09:00", kind="collection")
    assert run(c, [], "2026-06-30 10:00")["action"] == cr.STOP          # nobody to chase without them
    c["to_smtp"] = ["anderton.rail@ibstock.co.uk"]
    mails = [out("2026-06-26 09:00", "anderton.rail@ibstock.co.uk", "6055183 Collection Details", "K"),
             inn("2026-06-29 15:49", "anderton.rail@ibstock.co.uk", "RE: 6055183 Collection Details", "K")]
    assert run(c, mails, "2026-06-30 10:00")["action"] == cr.BLOCK


def test_window_starts_at_the_first_ask_to_anyone():
    # the record holds Richard (the extract contact) and the NEWEST email; Greg
    # was asked first by hand and answered - that is the reply
    r = rec(["6055570"], "richard.chappelow@networkrail.co.uk", "2026-09-03 09:00")
    mails = [out("2026-09-01 09:00", "greg.smith@networkrail.co.uk", "6055570 Site", "E"),
             inn("2026-09-02 08:00", "greg.smith@networkrail.co.uk", "RE: 6055570 Site", "E"),
             out("2026-09-03 09:00", "richard.chappelow@networkrail.co.uk", "6055570 Site", "E2")]
    # Greg answered before Richard was even asked - it may be the answer, or
    # a "speak to Richard" redirect (5033840, 6055657): never chase blind, hold
    assert run(r, mails, "2026-09-07 10:00")["action"] == cr.HOLD
    # Richard's own reply to the earlier thread still blocks
    mails.append(inn("2026-09-04 08:00", "richard.chappelow@networkrail.co.uk", "RE: 6055570 Site", "E2"))
    assert run(r, mails, "2026-09-07 10:00")["action"] == cr.BLOCK


def test_one_per_contact_any_shared_address():
    a = rec(["5033351"], "andrew.gilliver@networkrail.co.uk", "2026-07-03 09:00", delivery="14/07/2026")
    b = rec(["6054932"], "andrew.gilliver@networkrail.co.uk; site.box@networkrail.co.uk", "2026-07-03 09:00",
            delivery="20/07/2026")
    decs = [(r, {"action": cr.SEND, "reason": "", "evidence": None}) for r in (a, b)]
    assert len(cr.one_per_contact(decs, CTX)) == 1


def test_rearming_one_order_of_a_shared_record_reopens_it():
    st = {"6055400|e@voestalpine.com": {"blocked": True, "why": "replied", "at": "2026-09-01 09:00"},
          "6055402|e@voestalpine.com": {"rearmed_at": "2026-09-10 09:00"}}
    r = rec(["6055400", "6055402"], "e@voestalpine.com", "2026-08-25 09:00")
    d = run(r, [], "2026-09-11 10:00", ctx={"state": st})
    assert d["action"] != cr.BLOCK, d


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
