"""The background Claude's one tool (assist_tools.py, his 24/11 "Deal with it"): it works on the one email it was given
and stops once he has dealt with it; what may go goes, what needs his yes is held. Made-up people, orders and addresses;
no Outlook, no CTMS and no Claude - each is stood in for.

    python -m pytest tests/test_assist_tools.py
"""
import contextlib
import json
import os
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import assist_tools as T  # noqa: E402
import inbox_assist as A  # noqa: E402

SID = "abc123def456"


def _job(tmp_path, monkeypatch, state="open", job_state="working", **kw):
    for name in ("PATH", "LOG", "SEEN", "PUSH_DUE", "CFG", "WORK_DUE"):
        monkeypatch.setattr(A, name, str(tmp_path / ("x_" + name.lower())))
    monkeypatch.setenv("R2_ASSIST_JOB", SID)
    monkeypatch.delenv("R2_ASSIST_DRY", raising=False)
    monkeypatch.setattr(A, "_outlook_turn", lambda wait=90: contextlib.nullcontext())   # never the live Outlook slot
    it = {"id": SID, "eid": "E1", "state": state, "kind": "needs", "subject": "Delivery 1234567", "from": "Sam Asker",
          "addr": "sam@site.example", "received": "2026-11-24 10:00", "orders": ["1234567"],
          "job": {"state": job_state, "asks": [], "log": [], "did": []}}
    it.update(kw)
    A.save({"mode": "live", "items": {SID: it}})


def _run(capsys, *argv):
    code = T.main(list(argv))
    return code, capsys.readouterr().out


def _it():
    return A.load()["items"][SID]


def test_it_works_only_for_the_job_it_was_given(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    monkeypatch.delenv("R2_ASSIST_JOB")
    code, out = _run(capsys, "say", "hello")
    assert code == 2 and "only works for the background Claude" in out
    monkeypatch.setenv("R2_ASSIST_JOB", "../../etc")
    assert _run(capsys, "say", "hello")[0] == 2
    _job(tmp_path, monkeypatch, state="dealt")
    code, out = _run(capsys, "say", "hello")
    assert code == 2 and "He has marked it dealt with - stop here" in out
    _job(tmp_path, monkeypatch, job_state="done")
    code, out = _run(capsys, "reply", "--text", "Hi Sam, yes.")
    assert code == 2 and "isn't running any more" in out
    assert _run(capsys, "nonsense")[0] == 2 and _run(capsys, "help")[0] == 0


def test_say_shows_his_desk_what_it_is_doing(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    assert _run(capsys, "say", "Checking", "CTMS — order 1234567")[0] == 0
    job = _it()["job"]
    assert job["now"] == "Checking CTMS - order 1234567" and job["log"][-1].endswith("Checking CTMS - order 1234567")


def test_money_deletes_and_other_ctms_changes_are_held_for_his_yes(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    code, out = _run(capsys, "ctms-commit", "trip-price", "MAN-1", "--total", "500")
    assert code == 2 and "needs his yes" in out and "ask --what" in out
    code, out = _run(capsys, "ask", "--what", "Set MAN-1 to 500 (the haulier's +40)", "trip-price", "MAN-1", "--total",
                     "500")
    assert code == 0 and "Held for his yes (#0)" in out
    a = _it()["job"]["asks"][0]
    assert a["kind"] == "route" and a["route"] == ["trip-price", "MAN-1", "--total", "500"] and a["state"] == "open"
    assert _run(capsys, "ask", "--what", "Ring the site", )[0] == 0 and _it()["job"]["asks"][1]["kind"] == "todo"
    long = "Please check CTMS for delivery " * 20                          # a long one is cut at a word, with ...
    assert _run(capsys, "ask", "--what", long)[0] == 0
    what = _it()["job"]["asks"][2]["what"]
    assert len(what) <= 200 and what.endswith("…") and long.startswith(what[:-1]) and long[len(what) - 1] == " "
    del_asks = A.load()
    del_asks["items"][SID]["job"]["asks"].pop()
    A.save(del_asks)
    for bad in (["ask", "--what", "x", "press", "Save"], ["ask", "--what", "x", "order-cancel", "1-1-1", "--commit"],
                ["ctms", "order-cancel", "1-1-1", "--commit"], ["ctms", "press", "Save"]):
        assert _run(capsys, *bad)[0] == 2, bad
    assert len(_it()["job"]["asks"]) == 2


def test_ctms_reads_run_without_commit_and_an_order_update_may_commit(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    seen = []

    def run(args, **kw):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='DONE\nROUTE_RESULT {"ok": true, "said": "saved"}',
                                           stderr="")
    monkeypatch.setattr(T.subprocess, "run", run)
    assert _run(capsys, "ctms", "order-read", "1234567-1-1")[0] == 0
    assert seen[-1][-2:] == ["order-read", "1234567-1-1"] and "--commit" not in seen[-1]
    code, out = _run(capsys, "ctms-commit", "order-update", "1234567-1-1", "--deliver-from", "09:00")
    assert code == 0 and seen[-1][-4:] == ["order-update", "1234567-1-1", "--deliver-from", "09:00"][-3:] + ["--commit"]
    assert any("CTMS order-update" in x and "done - saved" in x for x in _it()["job"]["did"])
    monkeypatch.setenv("R2_ASSIST_DRY", "1")                               # a trial run commits nothing
    n = len(seen)
    assert _run(capsys, "ctms-commit", "order-note", "1234567-1-1", "x")[0] == 0 and len(seen) == n
    assert "would commit in CTMS: order-note" in _it()["job"]["did"][-1]


def test_a_reply_goes_on_the_thread_but_one_with_money_in_it_waits(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    import mail_ops
    drafted, sent = [], []
    o = ("app", "ns", types.SimpleNamespace(SmtpAddress="me@example.com"), types.SimpleNamespace(GetRootFolder=lambda: 0))

    def draft(it, body, outlook=None):
        drafted.append(body)
        return o, {"id": "D%d" % len(drafted), "fingerprint": "F"}, ["sam@site.example"], []
    monkeypatch.setattr(A, "reply_draft", draft)
    monkeypatch.setattr(mail_ops, "do_send_draft", lambda ns, acct, store, args: sent.append(args))
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED")
    code, out = _run(capsys, "reply", "--text", "Hi Sam,\\nThe price is £400.\\nKind regards")
    assert code == 0 and "Held for his yes (it mentions money)" in out and sent == []
    a = _it()["job"]["asks"][0]
    assert a["kind"] == "send" and a["thread"] and a["draft"] == {"id": "D1", "fingerprint": "F"}
    assert drafted[0] == "Hi Sam,\nThe price is £400."                  # \\n made a new line; no sign-off
    code, out = _run(capsys, "reply", "--text", "Hi Sam,\nIt's booked for Thursday 09:00.")
    assert code == 0 and "Sent to sam@site.example and filed to Regions/Region 2/Completed" in out
    it = _it()
    assert sent == [{"id": "D2", "fingerprint": "F"}] and it["state"] == "answered" and it["eid"] == "MOVED"
    assert any("replied to sam@site.example" in x for x in it["job"]["did"])
    code, out = _run(capsys, "reply", "--text", "Hi Sam, again")                # answered: nothing more goes
    assert code == 2 and "answered already" in out


def test_his_own_forward_is_never_replied_to_all(monkeypatch, tmp_path, capsys):
    """24/11 trial: the email was his own forward of a site's question - a reply to all would only have reached him."""
    _job(tmp_path, monkeypatch, **{"from": "Pat Desk"})
    monkeypatch.setattr(T, "_my_names", lambda: ["pat desk"])
    monkeypatch.setattr(A, "reply_draft", lambda *a, **k: (_ for _ in ()).throw(AssertionError("drafted")))
    code, out = _run(capsys, "reply", "--text", "Hi Kim, yes.")
    assert code == 2 and "his own email" in out and "draft --to" in out


def test_a_reply_that_fails_its_checks_stays_in_drafts(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    import mail_ops
    monkeypatch.setattr(A, "reply_draft", lambda it, body, outlook=None: (None, {"id": "D", "fingerprint": "F"},
                                                                          ["sam@site.example"], ["0 signatures"]))
    monkeypatch.setattr(mail_ops, "do_send_draft", lambda *a: (_ for _ in ()).throw(AssertionError("sent")))
    code, out = _run(capsys, "reply", "--text", "Hi Sam, yes.")
    assert code == 0 and "NOT SENT" in out and _it()["state"] == "open"


def test_a_new_email_or_a_forward_is_only_drafted_and_dhl_road_never(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    import mail_ops
    made = []
    monkeypatch.setattr(T, "_outlook", lambda: ("app", "ns", "acct", "store"))
    monkeypatch.setattr(mail_ops, "do_draft", lambda app, ns, acct, store, args: made.append(args) or
                        {"id": "N1", "fingerprint": "G"})
    code, out = _run(capsys, "draft", "--to", "jo@haul.example", "--subject", "Collection Friday", "--text",
                     "Hi Jo,\\nCan you collect Friday?")
    assert code == 0 and "held for his yes" in out and made[0]["to"] == "jo@haul.example"
    a = _it()["job"]["asks"][0]
    assert a["kind"] == "send" and "jo@haul.example" in a["what"] and not a.get("thread")
    assert _run(capsys, "forward", "--to", "kim@nr.example", "--text", "FYI")[0] == 0
    assert made[1]["forward"] == "E1" and len(_it()["job"]["asks"]) == 2
    code, out = _run(capsys, "draft", "--to", "DHLRoad@nr.example", "--subject", "x", "--text", "y")
    assert code == 2 and "DHL Road" in out
    assert _run(capsys, "forward", "--to", "no address here")[0] == 2


def test_filing_goes_only_to_his_own_folders(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    monkeypatch.setattr(T, "_outlook", lambda: ("app", "ns", "acct", types.SimpleNamespace(GetRootFolder=lambda: 0)))
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED")
    monkeypatch.setattr(A, "LOG", str(tmp_path / "log.jsonl"))
    assert _run(capsys, "file", "Deleted Items")[0] == 2
    code, out = _run(capsys, "file", "DHL")
    it = _it()
    assert code == 0 and out.strip() == "Filed to DHL." and it["state"] == "filed" and it["filed_to"] == "DHL"
    assert json.loads(open(tmp_path / "log.jsonl").read().splitlines()[0])["by"] == "claude"


def test_his_rule_book_is_read_by_topic_and_nothing_outside_it(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "MEMORY.md").write_text("- [Booking checklist](booking-checklist.md) - every line\n", encoding="utf-8")
    (rules / "booking-checklist.md").write_text("---\nname: x\n---\nWeight first, then the vehicle.\n", encoding="utf-8")
    A.save(dict(A.load()))
    with open(A.CFG, "w", encoding="utf-8") as f:
        json.dump({"rules_dir": str(rules)}, f)
    code, out = _run(capsys, "rules")
    assert code == 0 and "booking-checklist" in out
    code, out = _run(capsys, "rules", "booking-checklist")
    assert code == 0 and out.strip() == "Weight first, then the vehicle."
    for bad in ("../secrets", "MEMORY", "x/../../y"):
        assert _run(capsys, "rules", bad)[0] == 2, bad


def test_what_the_toolkit_knows_of_an_order(monkeypatch, tmp_path, capsys):
    _job(tmp_path, monkeypatch)
    monkeypatch.setattr(T, "HERE", str(tmp_path))
    (tmp_path / "tracker.json").write_text(json.dumps({"records": [
        {"orders": ["1234567-1-1"], "site": "Made Up Depot", "delivery_date": "2026-11-26", "orig_entryid": "SECRET",
         "html": "<p>x</p>"}]}), encoding="utf-8")
    (tmp_path / "_booked_drops.json").write_text(json.dumps(["1234567"]), encoding="utf-8")
    code, out = _run(capsys, "order", "1234567-1-1")
    assert code == 0 and "Made Up Depot" in out and "Booked in CTMS (the toolkit's list): yes" in out
    assert "SECRET" not in out and "<p>" not in out
    assert _run(capsys, "order", "; rm -rf")[0] == 2
