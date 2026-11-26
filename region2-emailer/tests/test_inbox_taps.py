"""The two tap-savers (inbox_assist.py + assist_tools.py, his 26/11 "Yes, build both"): a site's reply the CTMS to-do
already has leaves his list and is filed once its update is in; emails about the same order are one card, one Dealt
with or one Deal with it for the lot. Made-up people, orders and addresses only; no Outlook and no Claude.

    python -m pytest tests/test_inbox_taps.py
"""
import contextlib
import json
import os
import sys
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import assist_tools as T  # noqa: E402
import inbox_assist as A  # noqa: E402
import inbox_watch as W  # noqa: E402

NOW = datetime(2026, 11, 26, 10, 0)                     # a Thursday morning


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M")


def ctx():
    return {"me": {"me.desk@dhl.example"}, "my_names": ["pat desk"], "managers": ["sam boss"],
            "materials": {"steelmaterials@nr.example"}, "haulier_addrs": {"ops@haul.example"},
            "haulier_domains": {"haul.example"}, "handled": W.taken_in([], [])}


def todo_item(tid="t1", who="Kim Site", orders=("1234567",), added=NOW - timedelta(minutes=50), **kw):
    t = {"id": tid, "kind": "update", "orders": list(orders), "what": f"{who} replied 26/11 - update the order from it",
         "source": "reply", "added": iso(added), "done_at": None}
    t.update(kw)
    return t


def email(sid="e1", kind="needs", who="Kim Site", orders=("1234567-1-1",), received=NOW - timedelta(minutes=55), **kw):
    it = {"id": sid, "eid": "E" + sid, "conv": "C" + sid, "from": who, "addr": who.split()[0].lower() + "@site.example",
          "subject": "RE: delivery " + " ".join(orders), "received": iso(received), "unread": True,
          "orders": list(orders), "state": "open", "kind": kind, "urgency": "today", "ask": who + " sent the details",
          "action": {"type": "ctms", "text": "", "note": "Update CTMS with the details"}}
    it.update(kw)
    return it


# ---------- a site's reply the CTMS to-do has ----------
def test_the_to_do_item_is_the_one_this_very_reply_made():
    it = email()
    assert [t["id"] for t in A.todo_links(it, [todo_item()])] == ["t1"]
    assert A.todo_links(it, [todo_item(who="Lee Other")]) == []                 # someone else's reply
    assert A.todo_links(it, [todo_item(orders=("7654321",))]) == []             # another order
    assert A.todo_links(it, [todo_item(added=NOW - timedelta(hours=3))]) == []  # before the email came
    assert A.todo_links(it, [todo_item(added=NOW + timedelta(days=2))]) == []   # a later reply's, two days on
    assert A.todo_links(it, [todo_item(source="hand")]) == []
    assert A.todo_links(it, [dict(todo_item(), kind="note")]) == []


def test_off_his_list_while_on_the_to_do_filed_once_done_left_alone_after_his_x():
    it = email()
    A.todo_step(it, [todo_item()])
    assert it["kind"] == "todo" and it["was"] == "needs" and it["todo"] == ["t1"]
    A.todo_step(it, [todo_item(done_at=iso(NOW))])
    assert it["kind"] == "file" and it["dest"] == "Regions/Region 2/Completed" and "update is in CTMS" in it["why"]
    it = email()
    A.todo_step(it, [todo_item(done_at=iso(NOW), dismissed=True)])
    assert it["kind"] == "quiet" and "stays in your Inbox" in it["why"]
    # one that asks him something stays his, whatever the to-do has
    it = email(action={"type": "reply", "text": "Hi Kim, yes 09:00 is fine."})
    A.todo_step(it, [todo_item()])
    assert it["kind"] == "needs"
    # the desk's own: taken in at once (a site reply) moves on with its to-do; a bounce never
    it = email(kind="desk", why=A.DESK_TAKEN)
    A.todo_step(it, [todo_item(done_at=iso(NOW))])
    assert it["kind"] == "file"
    it = email(kind="desk", why="a bounce (the bounce escalation deals with it)")
    A.todo_step(it, [todo_item(done_at=iso(NOW))])
    assert it["kind"] == "desk"
    # kept on his list by him, or a job Claude has: never moved
    for kw in ({"listed": True}, {"kept": True}, {"job": {"state": "working"}}):
        it = email(**kw)
        A.todo_step(it, [todo_item()])
        assert it["kind"] == "needs", kw


class FakeRoot:
    StoreID = "STORE"


def _wire(monkeypatch, tmp_path, msgs, items, todo, mode="live"):
    for name in ("PATH", "LOG", "SEEN", "JUDGE_DUE", "PUSH_DUE", "CFG", "WORK_DUE", "TODO"):
        monkeypatch.setattr(A, name, str(tmp_path / ("x_" + name.lower())))
    (tmp_path / "x_seen").write_text(json.dumps({"ext_ids": []}))
    (tmp_path / "x_todo").write_text(json.dumps({"items": todo}))
    monkeypatch.setitem(sys.modules, "build_drafts", types.SimpleNamespace(
        get_ns=lambda: object(), dhl_store=lambda ns: FakeRoot(), DHL_SMTP="me.desk@dhl.example"))
    monkeypatch.setattr(W, "context", lambda *a, **k: ctx())
    monkeypatch.setattr(W, "collect", lambda ns, now, me: (msgs, {"conv": {}, "subject": {}, "ref": {}}))
    monkeypatch.setattr(W, "load", lambda: {"dealt": {}})
    moved = []

    def move(ns, root, eid, dest):
        moved.append((eid, dest))
        return "NEW-" + eid
    monkeypatch.setattr(A, "_move", move)
    A.save({"mode": mode, "auto": "off", "items": items})
    return moved


def _msg(it):
    return {"id": it["id"], "eid": it["eid"], "conv": it["conv"], "folder": "Inbox", "from_name": it["from"],
            "from_addr": it["addr"], "subject": it["subject"], "received": datetime.strptime(it["received"], "%Y-%m-%d %H:%M"),
            "unread": True, "verb": 0, "words": "", "orders": it["orders"], "to_me": True, "crowd": False}


def test_the_run_moves_it_to_the_to_do_then_files_it_once_the_update_is_in(monkeypatch, tmp_path):
    it = email()
    sid = A.stable_id(_msg(it))
    it = dict(it, id=sid)
    moved = _wire(monkeypatch, tmp_path, [_msg(it)], {sid: it}, [todo_item()])
    d, _ = A.sweep(now=NOW)
    p = A.panel(d, NOW)
    assert d["items"][sid]["kind"] == "todo" and p["needs"] == [] and p["cards"] == 0
    assert p["todo"][0]["id"] == sid and p["todo"][0]["back"] and "Kim Site replied" in p["todo"][0]["what"]
    assert moved == []
    (tmp_path / "x_todo").write_text(json.dumps({"items": [todo_item(done_at=iso(NOW))]}))
    d, n = A.sweep(now=NOW + timedelta(minutes=2))
    assert moved == [("E" + "e1", "Regions/Region 2/Completed")] and n["filed"] == 1
    assert d["items"][sid]["state"] == "filed"
    log = [json.loads(x) for x in open(A.LOG, encoding="utf-8")]
    assert log[-1]["why"].startswith("its update is in CTMS")


def test_keep_on_my_list_puts_it_back_for_good(monkeypatch, tmp_path, capsys):
    it = email()
    sid = A.stable_id(_msg(it))
    it = dict(it, id=sid)
    _wire(monkeypatch, tmp_path, [_msg(it)], {sid: it}, [todo_item()])
    A.sweep(now=NOW)
    assert A.main(["x", "list", sid]) == 0
    assert A.load()["items"][sid]["kind"] == "needs" and A.load()["items"][sid]["listed"]
    d, _ = A.sweep(now=NOW + timedelta(minutes=2))
    assert d["items"][sid]["kind"] == "needs" and [x["id"] for x in A.panel(d, NOW)["needs"]] == [sid]
    assert A.main(["x", "list", sid]) == 1                                    # it isn't on the to-do now


# ---------- one card per order ----------
def _card_items():
    return {
        "a": email("a", who="Gus Ops", orders=("7777777", "RD100001"), urgency="now", received=NOW - timedelta(hours=3)),
        "b": email("b", who="Rae Site", orders=("RD100001",), urgency="now", received=NOW - timedelta(hours=1)),
        "c": email("c", who="Eli Ops", orders=("7777777-1-1",), urgency="today", received=NOW - timedelta(minutes=30)),
        "x": email("x", who="Big Batch", orders=("7777777", "1111111", "2222222"), urgency="week"),
        "y": email("y", who="Lone Ask", orders=(), urgency="today"),
    }


def test_emails_about_the_same_order_are_one_card():
    d = {"mode": "live", "items": _card_items()}
    p = A.panel(d, NOW)
    leads = [x for x in p["needs"] if x["lead"]]
    assert p["cards"] == 3 == len(leads) and len(p["needs"]) == 5
    card = next(x for x in leads if x["group_n"] == 3)
    assert card["id"] == "b"                                  # the most urgent, then the newest
    assert sorted(o["id"] for o in card["others"]) == ["a", "c"] and card["about"] == "RD100001 / 7777777"
    assert {x["id"]: x.get("group") for x in p["needs"] if not x["lead"]} == {"a": "b", "c": "b"}
    assert card["waited"] == W.waited_text(max(x["mins"] for x in p["needs"] if x["id"] in "abc"))
    assert next(x for x in leads if x["id"] == "x")["group_n"] == 1   # a batch naming three orders stands alone
    assert p["now"] == 1 and sorted(A.group_members(d, "b", NOW)) == ["a", "c"]
    assert A.group_members(d, "a", NOW) == []                 # not a card's lead


def test_dealt_with_on_a_card_takes_them_all_off(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [], _card_items(), [])
    assert A.main(["x", "dealt", "b", "--group"]) == 0
    d = A.load()
    assert [s for s in "abcxy" if d["items"][s]["state"] == "dealt"] == ["a", "b", "c"]
    assert A.main(["x", "dealt", "x"]) == 0 and A.load()["items"]["y"]["state"] == "open"


def test_deal_with_it_on_a_card_gives_claude_the_lot_and_they_go_with_the_job(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [], _card_items(), [])
    d = A.load()

    def ringing(d):
        return {x[0]["id"] for x in A._alerts_due(d, NOW)}
    assert {"a", "b"} <= ringing(d)                           # "now" emails ring...
    said = A.deal(d, "b", note="", now=NOW, group=True)
    assert "all 3 emails" in said and sorted(d["items"]["b"]["job"]["group"]) == ["a", "c"]
    assert d["items"]["a"]["job_of"] == "b" and d["items"]["c"]["job_of"] == "b" and os.path.exists(A.WORK_DUE)
    assert not ringing(d) & {"a", "b", "c"}                   # ...not while Claude has the card
    A.save(d)
    briefs = []

    def ask(brief, sid, system, cfg):
        briefs.append(brief)
        return True, {"status": "done", "summary": "Answered all three about the order."}
    monkeypatch.setattr(A, "ring", lambda alerts, push=None: 0)
    assert A.work(ask=ask, now=NOW)[0] == "b"
    assert "--email a:" in briefs[0] and "--email c:" in briefs[0] and "ITS own thread" in briefs[0]
    d = A.load()
    assert [d["items"][s]["state"] for s in "abc"] == ["dealt", "dealt", "dealt"] and "job_of" not in d["items"]["a"]
    # a job that fails puts the others back as they were
    _wire(monkeypatch, tmp_path, [], _card_items(), [])
    d = A.load()
    A.deal(d, "b", now=NOW, group=True)
    A.save(d)
    A.work(ask=lambda *a: (False, "Not logged in"), now=NOW)
    d = A.load()
    assert d["items"]["b"]["job"]["state"] == "failed" and d["items"]["a"]["state"] == "open"
    assert "job_of" not in d["items"]["a"] and "a" in {x[0]["id"] for x in A._alerts_due(d, NOW)}


def test_one_email_on_its_own_is_dealt_with_as_before(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [], {"y": email("y", who="Lone Ask", orders=())}, [])
    d = A.load()
    said = A.deal(d, "y", now=NOW, group=True)                 # no card around it: its own job, no group
    assert "Claude is on it" in said and not d["items"]["y"]["job"].get("group")


# ---------- the tool, on another email of the card ----------
def _job(tmp_path, monkeypatch):
    for name in ("PATH", "LOG", "SEEN", "PUSH_DUE", "CFG", "WORK_DUE"):
        monkeypatch.setattr(A, name, str(tmp_path / ("x_" + name.lower())))
    monkeypatch.setenv("R2_ASSIST_JOB", "aaaaaaaaaaaa")
    monkeypatch.delenv("R2_ASSIST_DRY", raising=False)
    monkeypatch.setattr(A, "_outlook_turn", lambda wait=90: contextlib.nullcontext())
    lead = email("aaaaaaaaaaaa", who="Rae Site", orders=("RD100001",),
                 job={"state": "working", "group": ["bbbbbbbbbbbb"], "asks": [], "log": [], "did": []})
    other = email("bbbbbbbbbbbb", who="Gus Ops", orders=("7777777", "RD100001"), job_of="aaaaaaaaaaaa")
    stranger = email("cccccccccccc", who="Not Card", orders=("5555555",))
    A.save({"mode": "live", "items": {x["id"]: x for x in (lead, other, stranger)}})


def test_the_tool_works_on_another_email_of_the_card_and_no_other(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    import mail_ops
    o = ("app", "ns", types.SimpleNamespace(SmtpAddress="me@example.com"), types.SimpleNamespace(GetRootFolder=lambda: 0))
    replied_on = []

    def draft(it, body, outlook=None):
        replied_on.append(it["id"])
        return o, {"id": "D%d" % len(replied_on), "fingerprint": "F"}, [it["addr"]], []
    monkeypatch.setattr(A, "reply_draft", draft)
    monkeypatch.setattr(mail_ops, "do_send_draft", lambda ns, acct, store, args: None)
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED-" + eid)
    assert T.main(["--email", "cccccccccccc", "reply", "--text", "Hi"]) == 2
    assert "isn't on this job's card" in capsys.readouterr().out
    assert T.main(["--email", "not-an-id", "say", "x"]) == 2
    assert T.main(["--email", "bbbbbbbbbbbb", "reply", "--text", "Hi Gus,\nIt's booked for Monday."]) == 0
    d = A.load()
    assert replied_on == ["bbbbbbbbbbbb"] and d["items"]["bbbbbbbbbbbb"]["state"] == "answered"
    assert d["items"]["aaaaaaaaaaaa"]["state"] == "open"                      # the job's own email untouched
    assert any("replied to gus@site.example" in x for x in d["items"]["aaaaaaaaaaaa"]["job"]["did"])
    # a reply with money in it on the other email is held - and his yes files THAT email
    assert T.main(["--email", "bbbbbbbbbbbb", "reply", "--text", "Hi Gus, the price is £400."]) == 2  # answered now
    d = A.load()
    d["items"]["bbbbbbbbbbbb"]["state"] = "open"
    A.save(d)
    assert T.main(["--email", "bbbbbbbbbbbb", "reply", "--text", "Hi Gus, the price is £400."]) == 0
    a = A.load()["items"]["aaaaaaaaaaaa"]["job"]["asks"][0]
    assert a["email"] == "bbbbbbbbbbbb" and a["thread"]
    d = A.load()
    a["state"] = "running"
    d["items"]["aaaaaaaaaaaa"]["job"]["asks"][0] = a
    monkeypatch.setattr(A, "file_answered", lambda o, d, sid, now, by="him", kind="": " and filed " + sid)
    said = A.yes_end(d, "aaaaaaaaaaaa", 0, True, "Sent.", now=NOW, outlook=o)
    assert said.endswith("filed bbbbbbbbbbbb") and d["items"]["bbbbbbbbbbbb"]["state"] == "answered"
    assert d["items"]["aaaaaaaaaaaa"]["state"] == "open"
