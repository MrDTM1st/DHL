"""His reply to the day's Region 2 Updates, drafted (daily_update.py, 11/11): their email read the way they write it,
each order's story told from the desk's records and the mail in the order it happened, and nothing claimed that a
record or an email doesn't show - [check] instead. Made-up people, orders and addresses only; no Outlook.

    python -m pytest tests/test_daily_update.py
"""
import json
import os
import sys
import types
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import daily_update as D  # noqa: E402

NOW = datetime(2026, 11, 11, 15, 30)
TEAMS = {"teamsteel@nr.example": "Steel Team", "om@nr.example": "Order Management"}
THEIR_EMAIL = """Hi Pat
See below updates from our catch up
Make sure notes are added to every order
1 Adhoc to plan in with a courier just waiting on price
09/11 – 15/11
9100001 – Contacted site on the 10th – Raise with the Steel Team for alt contact
No Orders Outstanding
16/11 – 22/11
9100002 & 9100003 – Chased site up twice look at raising with the order management team
9100004/9100005 - Orders uploaded 12:49 today contact site
Order 9100006-1-1 – Book with the fleet
AH12/11/26ABC1 – Ad hoc to book
01999991 / 01999992 – Haulier issue raised
Kind Regards
Sam Boss
From: Pat Desk
Sent: 10 November 2026 16:00
Subject: RE: Region 2 Updates 10/11
9100099 – an older line that isn't today's
"""


def mail(when, dir_, kind, refs, frm=("", ""), to=(), subject="9100001 Somewhere", mans=()):
    return {"when": datetime.fromisoformat(when), "dir": dir_, "kind": kind, "refs": list(refs), "subject": subject,
            "from_name": frm[0], "from_addr": frm[1], "to": list(to), "mans": list(mans)}


def src(**kw):
    base = {"tracker": [], "waitlist": [], "todo": [], "journal": [], "adhoc_booked": [], "booked_drops": set(),
            "asks": {}, "teams": TEAMS, "mails": []}
    base.update(kw)
    return base


def line(refs, s):
    return D.status(refs, D.facts(refs, s), NOW)


def test_their_email_is_read_as_they_write_it():
    own = D.own_part(THEIR_EMAIL)
    assert "an older line" not in own and "Sam Boss" not in own
    got = D.parse(own)
    assert [p["kind"] for p in got] == ["point", "point", "week", "order", "week", "order", "order", "order", "order",
                                        "order"]
    assert got[2]["label"] == "09/11 – 15/11"
    assert got[3]["refs"] == ["9100001"] and got[3]["notes"].startswith("Contacted site")
    assert got[5]["refs"] == ["9100002", "9100003"] and got[6]["refs"] == ["9100004", "9100005"]
    assert got[7]["refs"] == ["9100006"]                                   # "Order 9100006-1-1" reads the order
    assert got[8]["refs"] == ["AH12/11/26ABC1"] and got[9]["refs"] == ["MAN-01999991", "MAN-01999992"]
    assert D.refs_in("HA6367441-93 and NN1234567-89") == ["HA6367441-93", "NN1234567-89"]


def test_a_booking_is_told_with_its_manifests_and_a_long_job_in_one_line():
    s = src(journal=[{"key": "9100001@16/11/2026", "trips": [
        {"manifest": "MAN-01999991", "collect": "15/11/26 08:00", "deliver": "16/11/26 10:00", "lines": ["9100001-1-1"]}]}],
        mails=[mail("2026-11-10 17:00", "out", "told", ["9100001"], to=[("Jo Site", "jo@site.example")],
                    mans=["MAN-01999991"])])
    assert line(["9100001"], s) == "Booked, MAN-01999991 (collect 15/11, deliver 16/11) - Jo Site told 10/11."
    many = src(adhoc_booked=[{"ref": "9100002", "man": f"MAN-0199999{i}"} for i in range(5)])
    assert line(["9100002"], many) == "Booked, 5 manifests (MAN-01999990 to MAN-01999994)."


def test_the_story_runs_in_order_long_ones_shortened_and_ends_with_where_it_stands():
    rec = {"orders": ["9100001"], "name": "New Person", "to": "new@site.example", "emailed_at": "2026-11-04 09:00",
           "contact_was": {"name": "Jo Site", "to": "jo@site.example"}}
    mails = [mail("2026-11-04 09:00", "out", "ask", ["9100001"], to=[]),                          # the batch's: no To
             mail("2026-11-06 09:00", "out", "chase", ["9100001"], to=[("Jo Site", "jo@site.example")]),
             mail("2026-11-09 09:00", "out", "chase", ["9100001"], to=[("Jo Site", "jo@site.example")]),
             mail("2026-11-10 08:00", "out", "team_out", ["9100001"], to=[("x", "om@nr.example")]),
             mail("2026-11-10 08:30", "out", "haulier_out", ["9100001"], to=[("Ops", "ops@haul.example")]),
             mail("2026-11-10 09:00", "out", "escalate", ["9100001"], to=[("x", "teamsteel@nr.example")],
                  subject="9100001 Somewhere - alternative contact needed"),
             mail("2026-11-10 12:00", "in", "team_in", ["9100001"], frm=("Steel Team", "teamsteel@nr.example")),
             mail("2026-11-10 13:00", "in", "reply", ["9100001"], frm=("Old Contact (Company)", "old@site.example")),
             mail("2026-11-11 09:00", "out", "ask", ["9100001"], to=[("New Person", "new@site.example"),
                                                                       ("Other Person", "other@site.example")]),
             mail("2026-11-11 10:00", "in", "internal", ["9100001"], frm=("Sam Boss", "sam@dhl.com"),
                  subject="RE: Region 2 Updates 11/11")]
    got = line(["9100001"], src(tracker=[rec], mails=mails))
    assert got == ("Emailed Jo Site 04/11, chased 06/11, 09/11 ... raised with Steel Team 10/11 for an alt contact, "
                   "Steel Team answered 10/11, Old Contact replied 10/11, emailed New Person and Other Person 11/11; "
                   "waiting on a reply.")
    assert "Sam Boss" not in got                                          # the update itself is never a reply
    assert "Ops" not in got                                               # an order's ring-round is the asks' story
    six = [m for m in mails if m["kind"] not in ("team_out",)]
    assert "..." not in line(["9100001"], src(tracker=[rec], mails=six))  # six steps are told whole


def test_details_in_a_reply_without_them_and_what_ctms_still_needs():
    rec = {"orders": ["9100001"], "name": "Jo", "to": "jo@site.example", "emailed_at": "2026-11-09 09:00",
           "reply_at": "2026-11-10 11:00", "missing": []}
    s = src(tracker=[rec], todo=[{"orders": ["9100001"], "kind": "update", "done_at": None}])
    assert line(["9100001"], s) == ("Emailed Jo 09/11; details in 10/11 - to book; CTMS update waiting on the Run.")
    part = dict(rec, missing=["delivery date"])
    assert "still need delivery date" in line(["9100001"], src(tracker=[part]))
    ni = {"orders": ["9100001"], "name": "Jo", "to": "jo@site.example", "emailed_at": "2026-11-09 09:00",
          "needs_info": {"at": "2026-11-10 11:00", "from": "Jo Site"}}
    assert line(["9100001"], src(tracker=[ni])).endswith("Jo Site replied 10/11 without the details - to email back.")
    vt = {"orders": ["9100001"], "name": "Jo", "emailed_at": "2026-11-09 09:00", "ctms_veh": True}
    assert "details in (Veh Type in CTMS) - to book" in line(["9100001"], src(tracker=[vt]))


def test_a_manifest_on_the_list_tells_its_trip_and_the_haulier_side():
    s = src(journal=[{"key": "9100001@16/11/2026", "trips": [
        {"manifest": "MAN-01999991", "collect": "15/11/26 08:00", "deliver": "16/11/26 10:00", "lines": ["9100001-1-1"]},
        {"manifest": "MAN-01999992", "collect": "15/11/26 09:00", "deliver": "16/11/26 11:00", "lines": ["9100001-2-1"]}]}],
        mails=[mail("2026-11-11 09:00", "out", "haulier_out", ["MAN-01999991"], to=[("Ops", "ops@haul.example")]),
               mail("2026-11-11 11:00", "in", "haulier", ["MAN-01999991"], frm=("Ops Desk (Haul Co)", "ops@haul.example"))])
    assert line(["MAN-01999991"], s) == ("Booked, MAN-01999991 (collect 15/11, deliver 16/11); emailed Ops 11/11, "
                                         "Ops Desk replied 11/11; [check] their answer to follow up.")
    assert line(["MAN-01999993"], src()) == D.CHECK + " nothing found on this manifest in the last 3 weeks' mail."
    want = D._want(["MAN-01999991", "9100001"])
    found = {D._canon(h) for h in want.findall("Re: 01999991 and MAN01999991, lines 9100001-1-1 / 19100001x")}
    assert found == {"MAN-01999991", "9100001"}                         # never inside a longer number
    assert D.refs_in("MAN-02000001 and man01500002") == ["MAN-02000001", "MAN-01500002"]


def test_nothing_is_claimed_that_the_records_and_mail_dont_show():
    assert line(["9100009"], src()) == (D.CHECK + " site not emailed yet - nothing sent about it in the last 3 weeks.")
    assert D._sentence([]).startswith(D.CHECK + " nothing found")
    only_team = src(mails=[mail("2026-11-10 14:00", "out", "team_out", ["9100009"], to=[("x", "om@nr.example")])])
    assert line(["9100009"], only_team) == ("Asked Order Management 10/11; waiting on a reply; "
                                            + D.CHECK + " site not emailed yet.")
    waiting = src(waitlist=[{"orders": ["9100009"], "status": "waiting", "date": "15/12/2026"}])
    assert line(["9100009"], waiting).startswith("On the wait list")
    missed = src(waitlist=[{"orders": ["9100009"], "status": "missed", "date": "10/11/2026"}])
    assert D.CHECK in line(["9100009"], missed)
    dropped = src(booked_drops={"9100009"})
    assert line(["9100009"], dropped) == "Taken off the open list as booked in CTMS - " + D.CHECK + " the MAN."


def test_what_each_email_was():
    c = lambda *a: D.classify(*a, TEAMS, {"haul.example", "ops@haul.example"}, ())   # noqa: E731
    assert c("out", "9100001 X - alternative contact needed", "", [("", "teamsteel@nr.example")], "") == "escalate"
    assert c("out", "9100001 X", "", [("", "om@nr.example")], "") == "team_out"
    assert c("out", "9100001 X", "", [("", "planner@haul.example")], "") == "haulier_out"
    assert c("out", "9100001 X", "", [("", "a@dhl.com"), ("", "b@dhl.com")], "") == "internal"
    assert c("out", "9100001 X", "Can I please get a reply to the below?", [("", "jo@site.example")], "") == "chase"
    assert c("out", "9100001 X", "", [("", "jo@site.example")], "") == "ask"
    assert D.classify("out", "9100001 X", "", [("", "jo@site.example")], "", TEAMS, set(), ["MAN-01999991"]) == "told"
    assert c("in", "RE: 9100001 X", "", [], "teamsteel@nr.example") == "team_in"
    assert c("in", "RE: 9100001 X", "", [], "ops@haul.example") == "haulier"
    assert c("in", "RE: 9100001 X", "", [], "boss@dhl.com") == "internal"
    assert c("in", "RE: Region 2 Updates 11/11", "", [], "jo@site.example") == "internal"
    assert c("in", "RE: 9100001 X", "", [], "jo@site.example") == "reply"


def test_names_read_the_way_he_writes_them():
    assert D.nice("'jo.site@site.example'", "", TEAMS) == "Jo Site"
    assert D.nice("Jo Site (Some Company)", "jo@site.example", TEAMS) == "Jo Site"
    assert D.nice("x", "TeamSteel@nr.example", TEAMS) == "Steel Team"
    assert D.nice("Jo", "jo.site@site.example") == "Jo Site"              # the tracker's first name, made whole
    assert D.nice("Jo", "joanne.site@site.example") == "Jo"               # ...only when the address is plainly theirs
    two = [mail("2026-11-10 09:00", "out", "team_out", ["9100001"], to=[("x", "om@nr.example")]),
           mail("2026-11-11 09:00", "out", "team_out", ["9100001"], to=[("x", "om@nr.example")])]
    assert line(["9100001"], src(mails=two)).startswith("Asked Order Management 10/11, 11/11; waiting on a reply")
    assert D._first("Sam Boss (DHL Supply Chain)") == "Sam"


def test_the_reply_marks_what_he_must_check_and_leaves_room_for_his_words():
    parsed = D.parse(D.own_part(THEIR_EMAIL))
    text, body, summary = D.compose(parsed, src(), NOW, "Hi Sam")
    assert text.splitlines()[0] == "Hi Sam,"
    assert "Make sure notes are added to every order – " + D.YOURS in text
    assert summary == {"orders": 6, "checks": 6, "points": 2}
    assert '<span style="background:#fff2a8">[check]</span>' in body and "<b>09/11 – 15/11</b>" in body
    assert "9100099" not in text                                          # yesterday's lines below the quote


# ---------- Outlook, made up: folders of mail items, as find_update / replied_at walk them ----------
class _List(list):
    @property
    def Count(self):
        return len(self)

    def Item(self, i):
        return self[i - 1]

    def Sort(self, field, desc):
        key = "SentOn" if "SentOn" in field else "ReceivedTime"
        self.sort(key=lambda it: getattr(it, key), reverse=desc)


class _Folder:
    def __init__(self, name, items=(), folders=()):
        self.Name, self.Items, self.Folders = name, _List(items), _List(folders)


class _Mail:
    MessageClass = "IPM.Note"

    def __init__(self, subject, sender, when, body=""):
        self.Subject, self.SenderName, self.ReceivedTime, self.SentOn, self.Body = subject, sender, when, when, body
        self.EntryID = f"{subject}|{sender}|{when:%H%M}"


def _outlook(monkeypatch, folders):
    root = _Folder("root", folders=folders)
    monkeypatch.setitem(sys.modules, "build_drafts", types.SimpleNamespace(dhl_store=lambda ns: root))
    return root


def test_the_managers_list_is_answered_never_a_colleague_s_thanks_on_the_thread(monkeypatch):
    their = _Mail("RE: Region 2 Updates 11/11", "Sam Boss", datetime(2026, 11, 11, 14, 20), THEIR_EMAIL)
    thanks = _Mail("RE: Region 2 Updates 11/11", "Kim Colleague", datetime(2026, 11, 11, 14, 35), "Thanks Sam\nKind Regards")
    old = _Mail("RE: Region 2 Updates 10/11", "Sam Boss", datetime(2026, 11, 10, 14, 20), THEIR_EMAIL)
    _outlook(monkeypatch, [_Folder("Inbox", [thanks, old], [_Folder("Region 2", [their])])])
    assert D.find_update(None, NOW) is their
    _outlook(monkeypatch, [_Folder("Inbox", [old])])
    assert D.find_update(None, NOW) is None                              # yesterday's is never today's


def test_the_1530_draft_isnt_made_when_he_has_replied_already(monkeypatch):
    their = _Mail("RE: Region 2 Updates 11/11", "Sam Boss", datetime(2026, 11, 11, 14, 20), THEIR_EMAIL)
    earlier = _Mail("RE: Region 2 Updates 10/11", "Pat Desk", datetime(2026, 11, 10, 15, 50))
    _outlook(monkeypatch, [_Folder("Inbox", [their]), _Folder("Sent Items", [earlier])])
    assert D.replied_at(None, their) == ""
    mine = _Mail("RE: Region 2 Updates 11/11", "Pat Desk", datetime(2026, 11, 11, 15, 5))
    _outlook(monkeypatch, [_Folder("Inbox", [their]), _Folder("Sent Items", [earlier, mine])])
    assert D.replied_at(None, their) == "15:05"


def test_the_card_before_and_after_the_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setitem(sys.modules, "inbox_watch", types.SimpleNamespace(panel=lambda: {"items": [
        {"why": "a haulier", "received": "11/11 14:00", "from": "Ops"},
        {"why": "the day's Region 2 Updates - your reply is due", "received": "11/11 14:20", "from": "Sam Boss"}]}))
    assert D.panel(NOW) == {"due": "15:30", "arrived": "14:20", "by": "Sam Boss"}
    assert D.panel(datetime(2026, 11, 11, 18, 30))["late"] is True           # 15:30 came and went: Draft it now
    assert D.panel(datetime(2026, 11, 12, 9, 0)) == {"due": "15:30"}         # yesterday's email isn't today's
    D._save_state({"day": "2026-11-11", "draft_at": "15:30", "for": "11/11 14:20", "from": "Sam Boss",
                   "summary": {"orders": 6}, "text": "Hi Sam,", "entry": "x", "saved": "y"})
    got = D.panel(NOW)
    assert got["draft_at"] == "15:30" and got["summary"] == {"orders": 6} and "entry" not in got


def test_the_agent_s_job_does_nothing_out_of_hours_or_twice_and_never_opens_outlook_for_it(monkeypatch, tmp_path,
                                                                                            capsys):
    monkeypatch.setattr(D, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setitem(sys.modules, "build_drafts", None)               # importing it here would fail the test
    said = lambda: json.loads(capsys.readouterr().out.strip().splitlines()[-1])["said"]   # noqa: E731
    assert D.main(["daily_update.py", "due", "--now", "2026-11-11T14:00"]) == 0 and said().startswith("Not time")
    assert D.main(["daily_update.py", "due", "--now", "2026-11-14T15:45"]) == 0 and said().startswith("Not time")
    assert D.main(["daily_update.py", "due", "--now", "2026-11-11T18:10"]) == 0 and said().startswith("Not time")
    D._save_state({"day": "2026-11-11", "replied": "15:05"})
    assert D.main(["daily_update.py", "due", "--now", "2026-11-11T15:40"]) == 0 and "already" in said()


def test_drafting_again_knows_a_draft_he_has_written_in():
    body = "Hi Sam,\r\n9100001 – Emailed Jo Site 04/11; waiting on a reply.\r\n\r\nKind regards\r\nPat\r\nFrom: Sam Boss\r\n..."
    top = D._top(types.SimpleNamespace(Body=body))
    assert top and D._top(types.SimpleNamespace(Body=body.replace("\r\n\r\n", "\r\n \r\n"))) == top   # spacing aside
    for his in (body.replace("a reply.", "a reply. Rang them, booked for Friday."),       # after the last line
                body.replace("Hi Sam,", "Hi Sam, all sorted bar one."),                    # at the top
                body.replace("Kind regards", "Call me if needed.\r\nKind regards")):       # above his signature
        assert D._top(types.SimpleNamespace(Body=his)) != top
    assert D._top(types.SimpleNamespace(Body=body.replace("From: Sam Boss", "From: Sam Boss (edited quote)"))) == top
    assert D._top(types.SimpleNamespace(Body="")) == ""


def test_the_1530_draft_isnt_made_once_their_email_is_filed(monkeypatch, tmp_path):
    # his rule, 11/11: filed into a folder = dealt with
    monkeypatch.setattr(D, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setitem(sys.modules, "send_order", types.SimpleNamespace())
    their = _Mail("RE: Region 2 Updates 11/11", "Sam Boss", datetime(2026, 11, 11, 14, 20), THEIR_EMAIL)
    done = _Folder("Completed", [their])
    their.Parent = done
    _outlook(monkeypatch, [_Folder("Inbox", [], [_Folder("Regions", [], [_Folder("Region 2", [], [done])])])])
    got = D.make_draft(None, NOW, auto=True)
    assert got["dealt"] == "Completed" and "no draft needed" in got["said"]
    assert D.panel(NOW)["dealt"] == "Completed" and not D.panel(NOW).get("draft_at")
    assert D._folder_of(types.SimpleNamespace(Parent=types.SimpleNamespace(Name="Inbox"))) == "Inbox"
