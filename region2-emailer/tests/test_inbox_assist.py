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
