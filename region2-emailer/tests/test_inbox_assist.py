"""The inbox assistant (inbox_assist.py, 23/11): what the fixed rules file and what they leave for Claude, how Claude's
answer is made safe, the card, and the sweep / judge / filing round trip. Made-up people, orders and addresses only;
no Outlook and no Claude - both are stood in for.

    python -m pytest tests/test_inbox_assist.py
"""
import json
import os
import subprocess
import sys
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import inbox_assist as A  # noqa: E402
import inbox_watch as W  # noqa: E402

NOW = datetime(2026, 11, 24, 10, 0)                     # a Tuesday morning


def ctx(records=(), forms=()):
    return {"me": {"me.desk@dhl.example", "pat desk"}, "my_names": ["pat desk"], "managers": ["sam boss"],
            "materials": {"steelmaterials@nr.example"}, "haulier_addrs": {"ops@haul.example"},
            "haulier_domains": {"haul.example"}, "handled": W.taken_in(list(records), forms)}


def msg(**kw):
    mid = kw.pop("id", "m1")
    m = {"id": mid, "eid": "E-" + mid, "conv": "C-" + mid, "folder": "Inbox", "from_name": "Someone",
         "from_addr": "someone@site.example", "subject": "Hello", "received": NOW - timedelta(minutes=30),
         "unread": True, "verb": 0, "words": "", "orders": [], "to_me": True, "crowd": False}
    m.update(kw)
    return m


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M")


# ---------- the fixed rules ----------
def test_teams_notices_and_digests_go_to_dhl():
    c = ctx()
    v = A.rule(msg(from_name="Microsoft Teams", from_addr="noreply@email.teams.microsoft.com",
                   subject="Kim sent you a message"), c)
    assert v == {"kind": "file", "dest": "DHL", "why": "a Teams notice"}
    v = A.rule(msg(from_name="Viva Engage", from_addr="digest@engage.mail.microsoft", subject="Weekly digest"), c)
    assert v["kind"] == "file" and v["dest"] == "DHL"


def test_a_managers_teams_message_is_read_by_claude():
    v = A.rule(msg(from_name="Microsoft Teams", from_addr="noreply@email.teams.microsoft.com",
                   subject="Sam Boss sent you a message"), ctx())
    assert v is None


def test_out_of_office_goes_to_region_2_completed():
    v = A.rule(msg(subject="Automatic reply: order 1234567"), ctx())
    assert v["kind"] == "file" and v["dest"] == "Regions/Region 2/Completed"


def test_a_plain_synergy_forward_is_filed_but_one_that_asks_is_not():
    c = ctx()
    plain = msg(from_name="Kim Colleague", from_addr="kim@dhl.com", subject="FW: Synergy_DHL_Haulier_Extract 23112026",
                words="Please see attached.", atts=["image001.png"])
    v = A.rule(plain, c)
    assert v["kind"] == "file" and v["dest"] == "ADHOC/Synergy Upload"
    asks = msg(from_name="Sam Boss", from_addr="sam.boss@dhl.com", subject="RE: URGENT BS Batch - 24/11/2026",
               words="Can you get these uploaded before 2pm please?")
    assert A.rule(asks, c) is None                        # his manager asks: Claude reads it, never filed by rule


def test_an_extract_the_monitor_has_not_read_stays_for_the_desk():
    m = msg(from_addr="kim@dhl.com", subject="FW: DHL Haulier Extract 24.11.2026", words="",
            atts=["Synergy_DHL_Haulier_Extract.xlsx"])
    assert A.rule(m, ctx(), ext_ids=[])["kind"] == "desk"
    assert A.rule(m, ctx(), ext_ids=[m["eid"]])["kind"] == "file"


def test_dhl_road_sending_one_to_upload_needs_him():
    m = msg(from_name="DHL Road", from_addr="dhlroad@nr.example", subject="Synergy extract",
            words="Please upload", atts=["extract.xlsx"])
    v = A.rule(m, ctx())
    assert v["kind"] == "needs" and v["urgency"] == "today" and v["action"]["type"] == "upload"


def test_bounces_own_mail_and_taken_in_mail_are_left_alone():
    c = ctx()
    assert A.rule(msg(from_name="Mail Delivery System", from_addr="mailer-daemon@x.example",
                      subject="Undeliverable: order 1234567"), c)["kind"] == "desk"
    assert A.rule(msg(from_name="Pat Desk", from_addr="me.desk@dhl.example", subject="note"), c)["kind"] == "desk"
    taken = msg(id="s", from_addr="site@site.example", subject="1234567 delivery", words="Contact Jo on 07000 000000")
    assert A.rule(taken, ctx(records=[{"orig_entryid": "E-s", "orders": ["1234567"]}])) in (None, {"kind": "desk", "why": "the desk has taken it in"})


def test_training_reminders_are_a_to_do_not_noise():
    v = A.rule(msg(from_name="noreply.mytalentworld", from_addr="noreply.mytalentworld@x.example",
                   subject="Friendly reminder: complete your course"), ctx())
    assert v["kind"] == "needs" and v["urgency"] == "week"


def test_an_ordinary_question_goes_to_claude():
    assert A.rule(msg(words="Can you confirm the lorry for Thursday?"), ctx()) is None


# ---------- Claude's answer made safe ----------
def test_verdict_needs_and_file_and_the_manager_guard():
    v = A.verdict({"needs_you": True, "urgency": "now", "ask": "Kim asks for the MAN",
                   "action": {"type": "reply", "text": "Hi Kim — it's MAN-0000001.\nKind regards"}, "why": "a question"})
    assert v["kind"] == "needs" and v["urgency"] == "now" and "—" not in v["action"]["text"]
    v = A.verdict({"needs_you": False, "urgency": "week", "ask": "", "action": {"type": "file"},
                   "file_to": "Somewhere else", "why": "an FYI"})
    assert v["kind"] == "file" and v["dest"] == "Regions/Region 2/Completed"
    v = A.verdict({"needs_you": False, "urgency": "week", "ask": "", "action": {"type": "file"}, "file_to": "DHL",
                   "why": "an FYI"}, from_manager=True)
    assert v["kind"] == "quiet"                           # a manager's email is never filed on Claude's say-so
    v = A.verdict({"needs_you": True, "urgency": "soon", "ask": "x", "action": {"type": "dance"}, "why": ""})
    assert v["urgency"] == "today" and v["action"]["type"] == "other"


def _proc(out, code=0):
    return subprocess.CompletedProcess([], code, stdout=out, stderr="")


def test_ask_claude_reads_the_command_lines_answer(tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_text("")
    cfg = {"claude": str(exe)}
    seen = {}

    def run(args, **kw):
        seen["args"], seen["input"], seen["env"] = args, kw.get("input"), kw.get("env")
        return _proc(json.dumps({"type": "result", "is_error": False, "result": "",
                                 "structured_output": {"needs_you": True, "urgency": "today", "ask": "a",
                                                       "action": {"type": "reply"}, "why": "b"}}))
    ok, got = A.ask_claude("SYSTEM", "PROMPT", cfg, run=run)
    assert ok and got["ask"] == "a"
    assert seen["input"] == "PROMPT" and "--tools" in seen["args"] and "--json-schema" in seen["args"]
    assert not any(k.startswith("CLAUDE_CODE_") for k in seen["env"])
    ok, said = A.ask_claude("S", "P", cfg, run=lambda a, **k: _proc(json.dumps(
        {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"})))
    assert not ok and "Not logged in" in said
    ok, said = A.ask_claude("S", "P", cfg, run=lambda a, **k: _proc("garbage"))
    assert not ok
    ok, said = A.ask_claude("S", "P", {"claude": str(tmp_path / "missing.exe")})
    assert not ok and "isn't installed" in said


def test_the_prompt_says_who_the_sender_is_and_what_the_tracker_knows():
    records = [{"orders": ["1234567"], "site": "Made Up Depot", "delivery_date": "2026-11-26", "reply_at": "x",
                "missing": ["contact"], "chases": 1}]
    it = {"from": "Sam Boss", "addr": "sam.boss@dhl.com", "subject": "1234567", "received": "2026-11-24 09:00",
          "orders": ["1234567", "7654321"], "text": "Where is this?", "atts": []}
    p = A.prompt_for(it, ctx(), records, booked={"7654321"})
    assert "one of his managers" in p and "Made Up Depot" in p and "still missing: contact" in p
    assert "7654321 - booked in CTMS" in p
    s = A.system_prompt(ctx(), {"rules": ["Made-up extra rule."]})
    assert "Pat" in s and "Sam Boss" in s and "Made-up extra rule." in s and "ADHOC/Synergy Upload" in s


# ---------- the card ----------
def _item(sid, **kw):
    it = {"id": sid, "eid": "E" + sid, "from": "Kim", "addr": "kim@x.example", "subject": "s" + sid,
          "received": iso(NOW - timedelta(minutes=90)), "unread": True, "orders": [], "state": "open"}
    it.update(kw)
    return it


def test_panel_orders_by_urgency_and_rings_now_at_once():
    d = {"mode": "shadow", "items": {
        "a": _item("a", kind="needs", urgency="week", ask="week one", action={"type": "reply"}),
        "b": _item("b", kind="needs", urgency="now", ask="now one", action={"type": "ctms"},
                   received=iso(NOW - timedelta(minutes=1))),
        "c": _item("c", kind="pending", words=["high", "a materials team"]),
        "d": _item("d", kind="pending", words=None),
        "e": _item("e", kind="file", dest="DHL", why="a Teams notice"),
        "f": _item("f", kind="file", dest="DHL", why="kept", kept=True),
        "g": _item("g", kind="needs", urgency="today", state="answered"),
    }}
    p = A.panel(d, NOW)
    assert [x["id"] for x in p["needs"]] == ["b", "c", "a"]
    assert p["needs"][0]["alarm"] is True                     # now: straight away
    assert p["needs"][1]["by"] == "words" and p["needs"][1]["urgency"] == "today"
    assert [x["id"] for x in p["would_file"]] == ["e"]
    assert p["pending"] == 2 and p["now"] == 1


# ---------- sweep, judge, filing ----------
class FakeRoot:
    StoreID = "STORE"


def _wire(monkeypatch, tmp_path, msgs, sent=None, ext_ids=()):
    for name in ("PATH", "LOG", "SEEN", "JUDGE_DUE", "PUSH_DUE", "CFG"):
        monkeypatch.setattr(A, name, str(tmp_path / ("x_" + name.lower())))
    (tmp_path / "x_seen").write_text(json.dumps({"ext_ids": list(ext_ids)}))
    # build_drafts needs the home-only config.json: a stand-in with just what the sweep uses
    monkeypatch.setitem(sys.modules, "build_drafts", types.SimpleNamespace(
        get_ns=lambda: object(), dhl_store=lambda ns: FakeRoot(), DHL_SMTP="me.desk@dhl.example"))
    monkeypatch.setattr(W, "context", lambda *a, **k: ctx())
    monkeypatch.setattr(W, "collect", lambda ns, now, me: (msgs, sent or {"conv": {}, "subject": {}, "ref": {}}))
    monkeypatch.setattr(A, "_details", lambda ns, sid, eid: {"to": "Pat Desk", "cc": "", "text": "full text",
                                                             "trail": "", "atts": []})
    monkeypatch.setattr(A, "_attachments", lambda ns, sid, eid: [])
    moved = []

    def move(ns, root, eid, dest):
        moved.append((eid, dest))
        return "NEW-" + eid
    monkeypatch.setattr(A, "_move", move)
    return moved


def test_sweep_sorts_new_mail_and_shadow_moves_nothing(monkeypatch, tmp_path):
    msgs = [msg(id="t", from_name="Microsoft Teams", from_addr="noreply@email.teams.microsoft.com",
                subject="Kim sent you a message"),
            msg(id="q", from_addr="kim@site.example", subject="Delivery Thursday", words="Can you confirm the time?")]
    moved = _wire(monkeypatch, tmp_path, msgs)
    d, n = A.sweep(now=NOW)
    kinds = sorted((it["subject"], it["kind"]) for it in d["items"].values())
    assert kinds == [("Delivery Thursday", "pending"), ("Kim sent you a message", "file")]
    assert n["queued"] == 1 and moved == [] and os.path.exists(A.JUDGE_DUE)
    pend = next(it for it in d["items"].values() if it["kind"] == "pending")
    assert pend["text"] == "full text" and pend["words"][0] == "normal"


def test_live_mode_files_logs_and_keeps_the_monitor_s_read_list(monkeypatch, tmp_path):
    ext = msg(id="x", from_addr="kim@dhl.com", subject="FW: Synergy_DHL_Haulier_Extract 24112026", words="",
              atts=["Synergy_DHL_Haulier_Extract.xlsx"])
    moved = _wire(monkeypatch, tmp_path, [ext], ext_ids=[ext["eid"]])
    monkeypatch.setattr(A, "_attachments", lambda ns, sid, eid: ["Synergy_DHL_Haulier_Extract.xlsx"])
    A.save({"mode": "live", "items": {}})
    d, n = A.sweep(now=NOW)
    assert moved == [("E-x", "ADHOC/Synergy Upload")] and n["filed"] == 1
    it = next(iter(d["items"].values()))
    assert it["state"] == "filed" and it["eid"] == "NEW-E-x"
    log = [json.loads(x) for x in open(A.LOG, encoding="utf-8")]
    assert log[0]["to"] == "ADHOC/Synergy Upload" and log[0]["new_eid"] == "NEW-E-x"
    assert "NEW-E-x" in json.load(open(A.SEEN))["ext_ids"]   # the monitor won't read it again as a new extract
    p = A.panel(A.load(), NOW)
    assert p["filed"] and p["filed"][0]["filed_to"] == "ADHOC/Synergy Upload"


def test_an_answered_email_leaves_the_list_and_is_filed_like_the_rest(monkeypatch, tmp_path):
    q = msg(id="q", subject="Delivery Thursday", words="Can you confirm the time?", orders=["1234567"])
    _wire(monkeypatch, tmp_path, [q])
    A.sweep(now=NOW)
    # he emailed someone about the same order: off the list, but not filed on that alone
    monkeypatch.setattr(W, "collect", lambda ns, now, me: ([q], {"conv": {}, "subject": {}, "ref": {"1234567": [NOW]}}))
    d, _ = A.sweep(now=NOW + timedelta(minutes=5))
    assert next(iter(d["items"].values()))["state"] == "answered"
    # he replied on the thread itself: filed to Region 2 Completed (live) / listed (shadow)
    r = msg(id="r", subject="Collection Friday", words="Can you confirm?", received=NOW - timedelta(minutes=10))
    monkeypatch.setattr(W, "collect", lambda ns, now, me: ([r], {"conv": {}, "subject": {}, "ref": {}}))
    A.sweep(now=NOW)
    monkeypatch.setattr(W, "collect", lambda ns, now, me: ([r], {"conv": {"C-r": [NOW]}, "subject": {}, "ref": {}}))
    d, _ = A.sweep(now=NOW + timedelta(minutes=5))
    it = next(i for i in d["items"].values() if i["subject"] == "Collection Friday")
    assert it["kind"] == "file" and it["dest"] == "Regions/Region 2/Completed" and "text" not in it
    assert [x["subject"] for x in A.panel(d, NOW)["would_file"]] == ["Collection Friday"]


def test_a_managers_or_urgent_synergy_email_is_never_filed_by_rule():
    m = msg(from_name="Sam Boss", from_addr="sam.boss@dhl.com", subject="RE: URGENT BS Batch - 24/11/2026", words="")
    assert A.rule(m, ctx()) is None
    m = msg(from_addr="kim@dhl.com", subject="RE: Inframat Batch - urgent", words="")
    assert A.rule(m, ctx()) is None


def test_mail_from_his_other_account_is_read_by_claude():
    assert A.rule(msg(from_name="Pat Desk", from_addr="pat.desk@nr.example", subject="FW: do this"), ctx()) is None
    assert A.rule(msg(from_name="Pat", from_addr="me.desk@dhl.example", subject="x"), ctx())["kind"] == "desk"


def test_dealt_with_on_the_old_card_counts(monkeypatch, tmp_path):
    q = msg(id="q", subject="Old ask", words="Can you?")
    _wire(monkeypatch, tmp_path, [q])
    monkeypatch.setattr(W, "load", lambda: {"dealt": {W._id(q["eid"]): "2026-11-23"}})
    d, n = A.sweep(now=NOW)
    it = next(iter(d["items"].values()))
    assert it["state"] == "dealt" and n["queued"] == 0


def test_judge_stores_claudes_verdicts_and_stops_on_a_sign_in_problem(monkeypatch, tmp_path):
    msgs = [msg(id="q1", subject="One", words="Can you?", received=NOW - timedelta(minutes=20)),
            msg(id="q2", subject="Two", words="Could you?", received=NOW - timedelta(minutes=10))]
    _wire(monkeypatch, tmp_path, msgs)
    A.sweep(now=NOW)

    def ask(system, prompt, cfg):
        return True, {"needs_you": "Two" in prompt, "urgency": "now", "ask": "Kim asks", "action": {"type": "reply"},
                      "file_to": "DHL", "why": "w"}
    done, said = A.judge(ask=ask, now=NOW)
    d = A.load()
    by_subject = {it["subject"]: it for it in d["items"].values()}
    assert done == 2 and said == ""
    assert by_subject["Two"]["kind"] == "needs" and by_subject["One"]["kind"] == "file"
    assert "text" not in by_subject["Two"] and d["claude"]["ok"] is True
    # a fresh email while he isn't signed in: it waits, the card says why
    msgs.append(msg(id="q3", subject="Three", words="Would you?"))
    A.sweep(now=NOW)
    done, said = A.judge(ask=lambda s, p, c: (False, "Not logged in"), now=NOW)
    d = A.load()
    assert done == 0 and "Not logged in" in said and d["claude"]["ok"] is False
    assert next(it for it in d["items"].values() if it["subject"] == "Three")["kind"] == "pending"


def test_a_save_waits_while_windows_holds_the_file(monkeypatch, tmp_path):
    path = str(tmp_path / "x.json")
    real, tries = os.replace, []

    def busy(src, dst):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)
    monkeypatch.setattr(A.os, "replace", busy)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    A._write(path, {"a": 1})
    assert json.load(open(path)) == {"a": 1} and len(tries) == 3
    monkeypatch.setattr(A.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "denied")))
    A._write(path, {"a": 2})                                 # never freed: written in place instead
    assert json.load(open(path)) == {"a": 2} and not os.path.exists(path + ".tmp")
    assert A._json(str(tmp_path / "none.json"), "default") == "default"


def test_keep_and_dealt_commands(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, [])
    A.save({"mode": "shadow", "items": {"a": _item("a", kind="file", dest="DHL"), "b": _item("b", kind="needs")}})
    assert A.main(["x", "keep", "a"]) == 0
    assert A.main(["x", "dealt", "b"]) == 0
    d = A.load()
    assert d["items"]["a"]["kept"] and d["items"]["a"]["kind"] == "quiet" and d["items"]["b"]["state"] == "dealt"
    assert A.main(["x", "mode", "live"]) == 0 and A.load()["mode"] == "live"
    assert A.main(["x", "mode", "loud"]) == 1


# ---------- one tap: Send (his 24/11 "Alerts + one-tap replies") ----------
def test_a_reply_loses_the_sign_off_outlook_will_add_and_never_has_an_em_dash():
    assert A.clean_reply("Hi Sam,\n\nYes, Monday works.\n\nKind regards") == "Hi Sam,\n\nYes, Monday works."
    assert A.clean_reply("Hi Sam,\nYes.\nKind regards,\nPat\n\n") == "Hi Sam,\nYes."
    assert A.clean_reply("Hi Sam,\nThanks for the update — all good.") == "Hi Sam,\nThanks for the update - all good."
    assert A.clean_reply("Hi Sam,\nIt's booked.") == "Hi Sam,\nIt's booked."
    assert A.clean_reply("   ") == "" and A.clean_reply(None) == ""


def test_the_checks_before_a_one_tap_reply_goes():
    ours = "me@example.com"
    good = "Hi Sam,\nYes.\nKind regards\nPat Planner\nOut of Hours\n0000\n"
    assert A.reply_checks(good, ["sam@example.net"], ours) == []
    assert "nobody to send it to" in A.reply_checks(good, [], ours)
    assert "DHL Road is on it" in A.reply_checks(good, ["dhlroad@example.org"], ours)
    assert "you are on it" in A.reply_checks(good, [ours], ours)
    assert any("signatures" in b for b in A.reply_checks("Hi Sam,\nYes.\n", ["sam@example.net"], ours))
    assert any("signatures" in b for b in A.reply_checks(good + good, ["sam@example.net"], ours))
    assert "an em dash crept in" in A.reply_checks(good.replace("Yes.", "Yes — fine."), ["sam@example.net"], ours)


class _Rcpt:
    def __init__(self, a):
        self.Address, self.AddressEntry = a, None


class _Rcpts:
    def __init__(self, addrs):
        self.l = [_Rcpt(a) for a in addrs]

    @property
    def Count(self):
        return len(self.l)

    def Item(self, i):
        return self.l[i - 1]

    def Remove(self, i):
        del self.l[i - 1]


class _Atts:
    Count = 0


class _Reply:
    Class, Sent, CC, BCC, Subject = 43, False, "", "", "RE: Monday"

    def __init__(self, addrs, html):
        self.Recipients, self.HTMLBody, self.EntryID, self.Attachments = _Rcpts(addrs), html, "NEW1", _Atts()
        self.sent = False

    @property
    def To(self):
        return "; ".join(r.Address for r in self.Recipients.l)

    @property
    def Body(self):
        import re as _re
        return _re.sub(r"<[^>]+>", "\n", self.HTMLBody)

    def Save(self):
        pass

    def Send(self):
        self.sent = True


def _outlook_with(reply):
    src = types.SimpleNamespace(ReplyAll=lambda: reply)
    items = {"E1": src, "NEW1": reply}
    ns = types.SimpleNamespace(GetItemFromID=lambda eid, store_id=None: items[eid])
    store = types.SimpleNamespace(StoreID="S1", GetRootFolder=lambda: None)
    return None, ns, types.SimpleNamespace(SmtpAddress="me@example.com"), store


SIGNED = ("<html><body><div>Kind regards<br>Pat Planner<br>Out of Hours<br>0000</div>"
          "<div>From: Sam Asker &lt;sam@example.net&gt;</div><div>Can we do Monday?</div></body></html>")


def _one(text="Hi Sam,\n\nYes, Monday works.\n\nKind regards"):
    return {"items": {"x1": {"id": "x1", "eid": "E1", "state": "open", "subject": "Monday", "from": "Sam Asker",
                             "received": "2026-11-24 10:00", "action": {"type": "reply", "text": text}}}}


def test_one_tap_sends_to_all_but_us_and_dhl_road_then_files_it(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(A, "SEEN", str(tmp_path / "seen.json"))
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED1")
    reply = _Reply(["sam@example.net", "me@example.com", "dhlroad@example.org", "jo@example.net"], SIGNED)
    d = _one()
    said = A.send_reply(d, "x1", outlook=_outlook_with(reply))
    assert reply.sent and [r.Address for r in reply.Recipients.l] == ["sam@example.net", "jo@example.net"]
    assert "Yes, Monday works." in reply.HTMLBody and reply.Body.count("Kind regards") == 1      # Outlook's, once
    it = d["items"]["x1"]
    assert it["state"] == "answered" and it["eid"] == "MOVED1" and it["sent_to"] == ["sam@example.net", "jo@example.net"]
    assert "Sent to sam@example.net, jo@example.net and filed to Regions/Region 2/Completed" in said
    assert "inbox_assist_sent" in open(tmp_path / "log.jsonl", encoding="utf-8").read()


def test_his_edit_goes_instead_and_a_failed_check_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(A, "SEEN", str(tmp_path / "seen.json"))
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED1")
    reply = _Reply(["sam@example.net"], SIGNED)
    A.send_reply(_one(), "x1", text="Hi Sam,\nTuesday instead, sorry.\nThanks", outlook=_outlook_with(reply))
    assert "Tuesday instead, sorry." in reply.HTMLBody and "Monday works" not in reply.HTMLBody and reply.sent
    unsigned = _Reply(["sam@example.net"], SIGNED.replace("Out of Hours", "Mobile"))
    d = _one()
    try:
        A.send_reply(d, "x1", outlook=_outlook_with(unsigned))
        raise AssertionError("it should not have been sent")
    except RuntimeError as e:
        assert "not sent, it's in Drafts" in str(e) and "0 signatures" in str(e)
    assert not unsigned.sent and d["items"]["x1"]["state"] == "open"
    gone = _one()
    gone["items"]["x1"]["state"] = "dealt"
    try:
        A.send_reply(gone, "x1", outlook=_outlook_with(_Reply(["sam@example.net"], SIGNED)))
        raise AssertionError("a dealt-with email should not be answered")
    except RuntimeError as e:
        assert "isn't on the list" in str(e)


def test_the_card_marks_a_reply_it_can_send():
    d = {"mode": "shadow", "items": {"x1": dict(_one()["items"]["x1"], kind="needs", urgency="today", ask="Monday?",
                                                  cc="Jo Example", received="2026-11-24 10:00:00"),
                                     "x2": dict(_one("")["items"]["x1"], id="x2", kind="needs", urgency="today",
                                                ask="Call them", received="2026-11-24 10:00:00")}}
    p = A.panel(d, now=datetime(2026, 11, 24, 11, 0))
    by = {x["id"]: x for x in p["needs"]}
    assert by["x1"]["sendable"] and by["x1"]["cc"] == "Jo Example" and not by["x2"]["sendable"]


# ---------- phone alerts (his 24/11) ----------
class _Push:
    def __init__(self, subs=1):
        self.subs, self.sent = subs, []

    def count(self):
        return self.subs

    def notify(self, title, body, url="/", tag=None):
        self.sent.append((title, body, tag))
        return {"sent": self.subs, "dropped": 0, "error": None}


def _items_for_alerts():
    return {"mode": "shadow", "items": {
        "n1": {"id": "n1", "state": "open", "kind": "needs", "urgency": "now", "from": "Sam Asker",
               "ask": "Sam asks if the driver can wait", "received": "2026-11-24 10:55:00"},
        "t1": {"id": "t1", "state": "open", "kind": "needs", "urgency": "today", "from": "Jo Example",
               "ask": "Jo asks for a time", "received": "2026-11-24 10:50:00"},
        "w1": {"id": "w1", "state": "open", "kind": "pending", "words": ["urgent", "says urgent"], "from": "Robin Field",
               "subject": "URGENT: gate locked", "received": "2026-11-24 10:58:00"},
        "f1": {"id": "f1", "state": "open", "kind": "file", "from": "Teams", "subject": "x", "received": "2026-11-24 10:00:00"},
        "d1": {"id": "d1", "state": "dealt", "kind": "needs", "urgency": "now", "from": "Pat", "ask": "y",
               "received": "2026-11-24 10:00:00"}}}


def test_a_now_email_rings_his_phone_once_and_today_waits_for_its_bell():
    push, d, now = _Push(), _items_for_alerts(), datetime(2026, 11, 24, 11, 0)
    alerts = A.alert_phone(d, now, push=push)
    assert sorted(t for _, _, t in alerts) == ["assist-n1", "assist-w1"]                # now, and the urgent words
    assert alerts[0][0].startswith("Needs you now: ") and d["items"]["n1"]["alerted"] and "alerted" not in d["items"]["t1"]
    assert A.ring(alerts, push=push) == 2 and len(push.sent) == 2
    assert A.alert_phone(d, now, push=push) == []                                     # each rings once
    later = A.alert_phone(d, datetime(2026, 11, 24, 12, 0), push=push)                 # today's bell: 60 working mins
    assert [t for _, _, t in later] == ["assist-t1"] and later[0][0].startswith("Still waiting: ")


def test_no_alert_while_off_or_with_no_phone_signed_up_and_nothing_marked():
    d = _items_for_alerts()
    assert A.alert_phone(d, datetime(2026, 11, 24, 11, 0), push=_Push(subs=0)) == []
    assert not any(it.get("alerted") for it in d["items"].values())
    d["mode"] = "off"
    assert A.alert_phone(d, datetime(2026, 11, 24, 11, 0), push=_Push()) == []
    assert A.ring([("t", "b", "x")], push=types.SimpleNamespace(notify=lambda *a: 1 / 0)) == 0      # never raises


# ---------- Deal with it (his 24/11: "one button that just says either dealt with or deal with it") ----------
class _PushUrl(_Push):
    def notify(self, title, body, url="/", tag=None):
        self.sent.append((title, body, tag, url))
        return {"sent": 1, "dropped": 0, "error": None}


def test_a_tap_on_an_alert_opens_the_desk_on_that_email():
    assert A.deep_link("assist-abc123def456") == "/?assist=abc123def456"
    assert A.deep_link("something-else") == "/" and A.deep_link(None) == "/" and A.deep_link("assist-") == "/"
    push = _PushUrl()
    assert A.ring([("Needs you now: Sam", "Sam asks", "assist-abc123def456")], push=push) == 1
    assert push.sent[0][3] == "/?assist=abc123def456"


def _dealable(tmp_path, monkeypatch, **items):
    for name in ("PATH", "LOG", "SEEN", "JUDGE_DUE", "PUSH_DUE", "CFG", "WORK_DUE"):
        monkeypatch.setattr(A, name, str(tmp_path / ("x_" + name.lower())))
    d = {"mode": "live", "items": {sid: dict({"id": sid, "eid": "E1", "state": "open", "subject": "Monday",
                                              "from": "Sam Asker", "addr": "sam@example.net", "orders": ["1234567"],
                                              "received": "2026-11-24 10:00"}, **kw) for sid, kw in items.items()}}
    A.save(d)
    return d


def test_deal_with_it_sends_a_ready_reply_files_noise_and_gives_claude_the_rest(monkeypatch, tmp_path):
    d = _dealable(tmp_path, monkeypatch,
                  r1={"kind": "needs", "urgency": "now", "action": {"type": "reply", "text": "Hi Sam,\nYes, Monday.\nThanks"}},
                  f1={"kind": "file", "dest": "DHL"},
                  c1={"kind": "needs", "urgency": "today", "action": {"type": "ctms", "note": "move it to Tuesday"}},
                  p1={"kind": "pending", "words": ["high", "x"]})
    assert A.deal_plan(d["items"]["r1"])["kind"] == "send" and A.deal_plan(d["items"]["f1"])["kind"] == "file"
    assert A.deal_plan(d["items"]["c1"])["kind"] == "claude" and A.deal_plan(d["items"]["p1"])["kind"] == "claude"
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED-" + dest)
    reply = _Reply(["sam@example.net", "me@example.com"], SIGNED)
    said = A.deal(d, "r1", outlook=_outlook_with(reply))
    assert reply.sent and "Sent to sam@example.net" in said and d["items"]["r1"]["state"] == "answered"
    said = A.deal(d, "f1", outlook=_outlook_with(_Reply([], SIGNED)))
    assert said == "Filed to DHL." and d["items"]["f1"]["state"] == "filed"
    said = A.deal(d, "c1", now=NOW)
    job = d["items"]["c1"]["job"]
    assert "Claude is on it" in said and job["state"] == "queued" and os.path.exists(A.WORK_DUE)
    assert A.deal(d, "c1") == "Claude is on it already."
    try:
        A.deal(d, "r1")
        raise AssertionError("an answered email is not dealt with twice")
    except RuntimeError as e:
        assert "isn't on the list" in str(e)


def test_a_note_or_his_own_words_go_to_claude_with_the_job(monkeypatch, tmp_path):
    d = _dealable(tmp_path, monkeypatch,
                  r1={"kind": "needs", "urgency": "now", "action": {"type": "reply", "text": "Hi Sam,\nYes.\nThanks"}})
    said = A.deal(d, "r1", text="Hi Sam,\nTuesday instead.\nKind regards", note="check CTMS first", now=NOW)
    job = d["items"]["r1"]["job"]
    assert "Claude is on it" in said and job["note"] == "check CTMS first" and job["reply"] == "Hi Sam,\nTuesday instead."
    brief = A.work_brief(d["items"]["r1"], ctx(), [], set())
    assert "His note to you - do this: check CTMS first" in brief and "Tuesday instead." in brief
    assert "1234567 - not on his tracker" in brief and "assist_tools.py email" in brief


def test_the_background_claude_is_held_to_the_toolkit_alone(tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_text("")
    seen = {}

    def run(args, **kw):
        seen.update(args=args, **kw)
        return _proc(json.dumps({"type": "result", "is_error": False,
                                 "structured_output": {"status": "done", "summary": "Told Sam."}}))
    ok, got = A.ask_worker("BRIEF", "abc123def456", "RULES", {"claude": str(exe)}, run=run)
    a = seen["args"]
    assert ok and got["summary"] == "Told Sam."
    assert a[a.index("--tools") + 1] == "Bash" and a[a.index("--allowedTools") + 1] == "Bash(python assist_tools.py:*)"
    assert a[a.index("--permission-mode") + 1] == "dontAsk" and a[a.index("--setting-sources") + 1] == "user"
    assert "--strict-mcp-config" in a and a[a.index("--append-system-prompt") + 1] == "RULES"
    assert seen["env"]["R2_ASSIST_JOB"] == "abc123def456" and seen["cwd"] == A.HERE and seen["input"] == "BRIEF"
    assert not any(k.startswith(("CLAUDE_CODE_", "ANTHROPIC_")) for k in seen["env"])
    r = A.work_rules(ctx(), {"rules": ["Made-up rule."]})
    assert "Pat" in r and "order-update" in r and "Made-up rule." in r and "money" in r


def test_the_worker_takes_the_job_and_his_phone_hears_how_it_went(monkeypatch, tmp_path):
    _dealable(tmp_path, monkeypatch,
              a1={"kind": "needs", "urgency": "now", "ask": "Sam asks if it's booked", "action": {"type": "other"},
                  "job": {"state": "queued", "asked_at": "2026-11-24 10:05", "note": "", "asks": [], "log": []}},
              b1={"kind": "needs", "urgency": "today", "ask": "Jo wants a price", "action": {"type": "other"},
                  "job": {"state": "queued", "asked_at": "2026-11-24 10:06", "note": "", "asks": [], "log": []}})
    monkeypatch.setattr(W, "context", lambda *a, **k: ctx())
    rang = []
    monkeypatch.setattr(A, "ring", lambda alerts, push=None: rang.extend(alerts) or len(alerts))

    def ask(brief, sid, system, cfg):
        assert A.load()["items"][sid]["job"]["state"] == "working"          # the desk shows it working
        if sid == "b1":                                                     # it held something for his yes
            dd = A.load()
            dd["items"]["b1"]["job"]["asks"].append({"kind": "todo", "what": "Agree Jo's price", "state": "open"})
            A.save(dd)
        return True, {"status": "done", "summary": "Checked CTMS — it's booked; told Sam."}
    assert A.work(ask=ask, now=NOW)[0] == "a1"                              # the oldest first
    it = A.load()["items"]["a1"]
    assert it["job"]["state"] == "done" and it["state"] == "dealt" and it["dealt_by"] == "claude"
    assert it["job"]["summary"] == "Checked CTMS - it's booked; told Sam."   # never an em dash
    assert rang[-1] == ("Done: Sam Asker", "Checked CTMS - it's booked; told Sam.", "assist-a1")
    assert os.path.exists(A.WORK_DUE)                                       # b1 still queued: go again
    assert A.work(ask=ask, now=NOW)[0] == "b1"
    it = A.load()["items"]["b1"]
    assert it["job"]["state"] == "needs_you" and it["state"] == "open"
    assert rang[-1][0] == "Needs your yes: Sam Asker" and rang[-1][1] == "Agree Jo's price"
    assert A.work(ask=ask, now=NOW) == (None, "nothing queued")
    d = A.load()                                                            # it couldn't: said on the card and phone
    d["items"]["a1"].update(state="open", job={"state": "queued", "asked_at": "2026-11-24 11:00", "asks": []})
    A.save(d)
    A.work(ask=lambda *a: (False, "Not logged in"), now=NOW)
    job = A.load()["items"]["a1"]["job"]
    assert job["state"] == "failed" and job["said"] == "Not logged in" and rang[-1][0] == "Couldn't finish: Sam Asker"


def test_a_job_that_crashes_or_is_lost_never_hides_its_email(monkeypatch, tmp_path):
    d = _dealable(tmp_path, monkeypatch,
                  s1={"kind": "needs", "urgency": "now", "ask": "Stuck one", "received": iso(NOW - timedelta(minutes=50)),
                      "job": {"state": "working", "started": iso(NOW - timedelta(minutes=30)), "asks": []}},
                  w1={"kind": "needs", "urgency": "now", "ask": "Still going", "received": iso(NOW - timedelta(minutes=50)),
                      "job": {"state": "working", "started": iso(NOW - timedelta(minutes=5)), "asks": []}})
    assert A._unstick(d, NOW) == 1                                          # the home PC lost it: back on his list
    assert d["items"]["s1"]["job"]["state"] == "failed" and "stopped without finishing" in d["items"]["s1"]["job"]["said"]
    assert d["items"]["w1"]["job"]["state"] == "working"                    # one still within its time is left
    assert [it["id"] for it, _ in A._alerts_due(d, NOW)] == ["s1"]          # and its bell is back
    monkeypatch.setattr(W, "context", lambda *a, **k: ctx())
    monkeypatch.setattr(A, "ring", lambda alerts, push=None: len(alerts))
    d = A.load()
    d["items"]["s1"]["job"] = {"state": "queued", "asked_at": iso(NOW), "asks": []}
    A.save(d)
    A.work(ask=lambda *a: 1 / 0, now=NOW)                                   # the worker itself broke
    job = A.load()["items"]["s1"]["job"]
    assert job["state"] == "failed" and "ZeroDivisionError" in job["said"]


def test_a_job_that_needs_him_but_held_nothing_still_asks_him(monkeypatch, tmp_path):
    _dealable(tmp_path, monkeypatch, n1={"kind": "needs", "urgency": "now", "ask": "x", "action": {"type": "other"},
                                         "job": {"state": "queued", "asked_at": iso(NOW), "asks": []}})
    monkeypatch.setattr(W, "context", lambda *a, **k: ctx())
    monkeypatch.setattr(A, "ring", lambda alerts, push=None: len(alerts))
    A.work(ask=lambda *a: (True, {"status": "needs_you", "summary": "Only you can ring the site about the gate."}), now=NOW)
    job = A.load()["items"]["n1"]["job"]
    assert job["state"] == "needs_you" and job["asks"] == [
        {"kind": "todo", "state": "open", "at": iso(NOW), "what": "Only you can ring the site about the gate."}]


class _Ran:
    def __init__(self, out):
        self.out, self.args = out, None

    def __call__(self, args, **kw):
        self.args = args
        return _proc(self.out)


def test_his_yes_sends_a_held_email_runs_a_held_ctms_change_and_no_leaves_it(monkeypatch, tmp_path):
    asks = [{"kind": "send", "thread": True, "what": "Send this reply to sam@example.net", "to": "sam@example.net",
             "draft": {"id": "D1", "fingerprint": "F1"}, "state": "open"},
            {"kind": "route", "what": "Set MAN-1's total to 500", "route": ["trip-price", "MAN-1", "--total", "500"],
             "state": "open"},
            {"kind": "todo", "what": "Ring the site", "state": "open"}]
    d = _dealable(tmp_path, monkeypatch, a1={"kind": "needs", "urgency": "now", "action": {"type": "other"},
                                              "job": {"state": "needs_you", "asks": asks}})
    import mail_ops
    sent = []
    monkeypatch.setattr(mail_ops, "do_send_draft", lambda ns, acct, store, args: sent.append(args) or {"said": "sent"})
    monkeypatch.setattr(A, "_move", lambda ns, root, eid, dest: "MOVED-1")
    o = _outlook_with(_Reply([], SIGNED))
    a = A.yes_begin(d, "a1", 0)
    assert d["items"]["a1"]["job"]["asks"][0]["state"] == "running"
    ok, said = A.yes_do(a, outlook=o)
    said = A.yes_end(d, "a1", 0, ok, said, outlook=o)
    assert ok and sent == [{"id": "D1", "fingerprint": "F1"}] and "filed to Regions/Region 2/Completed" in said
    assert d["items"]["a1"]["state"] == "answered"
    a = A.yes_begin(d, "a1", 1)                                             # CTMS closed: it waits for his yes again
    ok, said = A.yes_do(a, run=_Ran('STOPPED: CTMS isn\'t open\nROUTE_RESULT {"ok": false, "said": "CTMS isn\'t open"}'))
    A.yes_end(d, "a1", 1, ok, said)
    assert d["items"]["a1"]["job"]["asks"][1]["state"] == "open" and d["items"]["a1"]["job"]["asks"][1]["said"] == "CTMS isn't open"
    ran = _Ran('DONE trip-price in 9s\nROUTE_RESULT {"ok": true, "said": "total 500.00"}')
    a = A.yes_begin(d, "a1", 1)
    ok, said = A.yes_do(a, run=ran)
    assert ok and said == "total 500.00" and ran.args[-5:] == ["trip-price", "MAN-1", "--total", "500", "--commit"]
    A.yes_end(d, "a1", 1, ok, said)
    assert A.no(d, "a1", 2) == "Left undone."
    job = d["items"]["a1"]["job"]
    assert [x["state"] for x in job["asks"]] == ["done", "done", "declined"] and job["state"] == "done"
    try:
        A.yes_begin(d, "a1", 0)
        raise AssertionError("a yes counts once")
    except RuntimeError as e:
        assert "done already" in str(e)


def test_a_held_route_is_never_a_raw_click_or_a_commit_smuggled_in():
    assert A.held_route(["order-cancel", "1234567-1-1"]) == ["order-cancel", "1234567-1-1"]
    for bad in (["press", "Save"], ["menu", "x"], ["trip-price", "MAN-1", "--commit"], [], ["rm -rf", "x"],
                ["order-note", "1234567-1-1", "a\nb"]):
        try:
            A.held_route(bad)
            raise AssertionError(f"{bad} should be refused")
        except RuntimeError:
            pass
    ok, said = A._route_result('STOPPED: CTMS isn\'t open\nROUTE_RESULT {"ok": false, "said": "CTMS isn\'t open"}')
    assert not ok and said == "CTMS isn't open"
    assert A._route_result("garbage\nlast words") == (False, "last words")


def test_the_card_says_what_deal_with_it_will_do_and_shows_the_job():
    d = {"mode": "live", "items": {
        "r1": _item("r1", kind="needs", urgency="now", ask="Sam asks", action={"type": "reply", "text": "Hi Sam,\nYes."}),
        "c1": _item("c1", kind="needs", urgency="now", ask="Move it", action={"type": "ctms"},
                    job={"state": "working", "asked_at": iso(NOW), "now": "Reading CTMS", "asks": [], "log": ["10:00 x"]}),
        "h1": _item("h1", kind="needs", urgency="today", ask="Price?", action={"type": "other"},
                    job={"state": "needs_you", "asked_at": iso(NOW), "asks": [
                        {"kind": "route", "what": "Set the total", "route": ["trip-price", "MAN-1"], "state": "open"}]}),
        "d1": _item("d1", kind="needs", urgency="now", ask="Done one", state="dealt",
                    job={"state": "done", "asked_at": iso(NOW), "summary": "Told Sam it's booked.", "asks": []}),
        "o1": _item("o1", kind="needs", urgency="now", ask="Old", state="dealt",
                    job={"state": "done", "asked_at": "2026-11-20 09:00", "summary": "x", "asks": []})}}
    p = A.panel(d, NOW)
    by = {x["id"]: x for x in p["needs"]}
    assert by["r1"]["deal"]["kind"] == "send" and by["c1"]["deal"]["kind"] == "claude"
    assert by["c1"]["job"]["now"] == "Reading CTMS" and not by["c1"]["alarm"] and by["r1"]["alarm"]
    assert by["h1"]["job"]["asks"][0]["route"] == "trip-price MAN-1" and by["h1"]["job"]["asks"][0]["n"] == 0
    assert [j["id"] for j in p["jobs"]] == ["d1"] and p["jobs"][0]["job"]["summary"] == "Told Sam it's booked."
    assert [it["id"] for it, _ in A._alerts_due(d, NOW)] == ["r1"]          # Claude's jobs ring when they end


def test_dealt_with_drops_what_claude_held(monkeypatch, tmp_path):
    _dealable(tmp_path, monkeypatch,
              h1={"kind": "needs", "urgency": "today", "job": {"state": "needs_you", "asks": [
                  {"kind": "send", "what": "Send it", "state": "open"}, {"kind": "todo", "what": "x", "state": "done"}]}},
              q1={"kind": "needs", "urgency": "today", "job": {"state": "queued", "asks": []}})
    assert A.main(["x", "dealt", "h1"]) == 0 and A.main(["x", "dealt", "q1"]) == 0
    d = A.load()
    assert [a["state"] for a in d["items"]["h1"]["job"]["asks"]] == ["declined", "done"]
    assert d["items"]["h1"]["job"]["state"] == "done" and d["items"]["q1"]["job"]["state"] == "dropped"
    assert A.work(ask=lambda *a: (True, {}), now=NOW) == (None, "nothing queued")   # a dropped job never runs
