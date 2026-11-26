"""The faster CTMS (his 26/11 "Yes, build it"): CTMS's harmless notices OK'd and the job carries on (the routes, Book,
the Run); an order card's reads skip the windows behind once switched on; and the CTMS job queue - jobs one after
another while CTMS is ready, a stop never tried again by itself, his yes on a held change queued instead of holding
the agent. Made-up orders and manifests only; no CTMS, no bridge, no phone.

    python -m pytest tests/test_ctms_faster.py
"""
import json
import os
import sys
import types
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_queue as Q  # noqa: E402
import ctms_routes as C  # noqa: E402
import ctms_rows  # noqa: E402
import inbox_assist as A  # noqa: E402

NOW = datetime(2026, 11, 26, 9, 0)
NOTICE = "Forms Missed delivery window: Order 11000001 stop 2."


# ---------- the routes: a harmless notice OK'd, the Save pressed again once ----------
def _q(words, buttons=("ok",)):
    return {"window": "Forms", "words": words, "buttons": {b: {"n": i, "at": [10 * i, 10, 5, 5]}
                                                           for i, b in enumerate(buttons, 1)}}


class FakeScreen:
    def __init__(self, q=None, save=True):
        self.q, self.save = q, save

    def question(self):
        return self.q

    def find(self, **kw):
        return [{"n": 99, "at": [500, 500, 40, 20]}] if self.save and kw.get("name") == "Save" else []

    def frame(self, name, contains=True):
        return {"n": 1, "nm": name}


def test_only_a_known_ok_only_notice_counts_as_harmless():
    assert C.harmless(_q(NOTICE)) and C.harmless(_q("FRM-41091: List of values contains no entries."))
    assert not C.harmless(_q(NOTICE, ("ok", "cancel")))                  # a choice: never answered for him
    assert not C.harmless(_q("Do you want to save the changes?"))
    assert not C.harmless(None)


def test_settle_oks_the_notice_and_saves_again_once_never_a_third_time(monkeypatch):
    # after the OK: clean; after the second Save: the notice again; after its OK: clean
    acts, reads = [], [FakeScreen(None), FakeScreen(_q(NOTICE)), FakeScreen(None)]
    monkeypatch.setattr(C, "act", lambda steps, name="route": acts.append(name))
    monkeypatch.setattr(C, "read", lambda wait=150: reads.pop(0))
    C.NOTICES.clear()
    C._RESAVED.clear()
    s, q = C.settle(FakeScreen(_q(NOTICE)), "Planning")
    assert q is None and C.NOTICES == [NOTICE, NOTICE]
    assert acts == ["OK the notice: " + NOTICE[:60], "Planning Save again (the notice stopped the first)",
                    "OK the notice: " + NOTICE[:60]]
    acts.clear()                                                        # the same window again: no third Save
    reads[:] = [FakeScreen(None)]
    C.settle(FakeScreen(_q(NOTICE)), "Planning")
    assert acts == ["OK the notice: " + NOTICE[:60]]
    acts.clear()                                                        # anything else is left up, untouched
    s, q = C.settle(FakeScreen(_q("Do you want to save the changes?", ("yes", "no"))), "Planning")
    assert acts == [] and q["words"].startswith("Do you want")


def test_the_routes_answer_says_what_ctms_said(monkeypatch, capsys):
    C.NOTICES.clear()

    def fake(a):
        C.NOTICES.append(NOTICE)
        return {"said": "done"}
    monkeypatch.setitem(C.ROUTES, "where", (fake, "test"))
    assert C.main(["where"]) == 0
    out = capsys.readouterr().out
    got = json.loads(out.strip().splitlines()[-1][len("ROUTE_RESULT "):])
    assert got["notices"] == [NOTICE] and "OK'd CTMS's notice" in out
    C.NOTICES.clear()


def test_an_order_cards_reads_skip_the_windows_behind_only_once_switched_on(monkeypatch, tmp_path):
    flag = tmp_path / "fast.on"
    monkeypatch.setattr(C, "FAST_FLAG", str(flag))
    monkeypatch.setattr(C, "PROFILE", {})
    asked = []
    monkeypatch.setattr(C, "connect", lambda: None)
    monkeypatch.setattr(C.R, "ask", lambda action, wait_total=0, **kw: (asked.append(kw) or
                                                                          ({"ok": True}, {"kind": "fields", "elements": []})))
    C.read()
    C.PROFILE.update(C.CARD_SKIP)
    C.read()                                                            # set, but not switched on: a whole read
    flag.write_text("")
    C.read()
    assert asked == [{}, {}, {"skip": ["Planning", "OPOKUD"]}]
    C._WHOLE[0] += 1                                                    # inside a menu: whole, always
    C.read()
    C._WHOLE[0] -= 1
    assert asked[-1] == {}


def test_a_menu_is_always_read_whole(monkeypatch, tmp_path):
    flag = tmp_path / "fast.on"
    flag.write_text("")
    monkeypatch.setattr(C, "FAST_FLAG", str(flag))
    monkeypatch.setattr(C, "PROFILE", dict(C.CARD_SKIP))
    seen = []

    def opened(path, parts, s):
        seen.append((C._skips(), s))
    monkeypatch.setattr(C, "_open_menu", opened)
    monkeypatch.setattr(C, "read", lambda wait=150: "WHOLE READ" if C._WHOLE[0] else "PART READ")
    C.open_menu("C-TMS Modules > Order Management > Orders", s="A PART READ FROM BEFORE")
    assert seen == [({}, "WHOLE READ")] and C._WHOLE[0] == 0


# ---------- the work PC: Book and the Run go past it too ----------
def _notice_els():
    return [{"r": "internal frame", "nm": "Forms", "lv": 0, "at": [20, 151, 428, 163]},
            {"r": "option pane", "nm": NOTICE, "lv": 1, "at": [23, 172, 422, 139]},
            {"r": "push button", "nm": "OK", "lv": 2, "at": [374, 272, 63, 31]},
            {"r": "label", "nm": NOTICE, "lv": 2, "at": [127, 204, 310, 40]}]


def test_the_work_pcs_check_is_the_same():
    assert ctms_rows.harmless(ctms_rows.question(_notice_els()))
    els = _notice_els() + [{"r": "push button", "nm": "Cancel", "lv": 2, "at": [440, 272, 63, 31]}]
    assert not ctms_rows.harmless(ctms_rows.question(els))
    assert not ctms_rows.harmless(None)


def test_book_oks_the_notice_says_it_and_carries_on():
    import test_ctms_book as TB
    ctms = TB.FakeCtms([TB._row("9100001-1-1")])
    real, real_click = ctms.read, ctms.click
    n = [0]

    def read(tree=True, skip=()):
        n[0] += 1
        up = 6 <= n[0] and not getattr(ctms, "okd", False)            # it comes up mid-booking
        return (_notice_els() if up else []) + real(tree, skip)

    def click(s):
        if s.get("screen") == [374 + 31, 272 + 15]:
            ctms.okd = True
        real_click(s)
    ctms.read, ctms.click = read, click
    job = TB._book(ctms)
    assert ctms.okd and job.trips[0]["status"] == "ACCEPTED"
    assert any(x == f'CTMS said "{NOTICE}": OK\'d it and carried on' for x in job.said)


def test_the_runs_save_oks_the_notice_and_saves_once_more():
    import ctms_items as I
    saves, shown = [], [True]

    def run(steps):
        for s in steps:
            if s.get("action") == "click" and tuple(s.get("px") or ()) == I.ORDER_SAVE:
                saves.append(1)
            if s.get("action") == "click" and s.get("screen") == [374 + 31, 272 + 15]:
                shown[0] = False

    def read():
        return _notice_els() if shown[0] and saves else []
    job = I.Items(run, read, lambda name, box: False, {})
    job.close_quietly = lambda: None
    job.save_close("9100001-1-1")
    assert len(saves) == 2 and job.notices == [NOTICE]


# ---------- the CTMS job queue ----------
def _queue(monkeypatch, tmp_path):
    monkeypatch.setattr(Q, "PATH", str(tmp_path / "q.json"))
    monkeypatch.setattr(Q, "DUE", str(tmp_path / "q_due"))
    monkeypatch.setattr(Q, "PUSH_DUE", str(tmp_path / "push_due"))


def test_a_job_is_named_routes_never_a_raw_click(monkeypatch, tmp_path):
    _queue(monkeypatch, tmp_path)
    for bad in ([["press", "OK"]], [["menu", "C-TMS Modules"]], [["no-such-route"]], [["trip-price", "x\ny"]], []):
        try:
            Q.add(bad)
            raise AssertionError(f"{bad} was queued")
        except Q.Refused:
            pass
    j = Q.add(Q.split_steps(["trip-price", "MAN-00000001", "440", "--commit", ";;", "trip-resend", "MAN-00000001",
                             "--commit"]), by="Claude", now=NOW)
    assert j["steps"] == [["trip-price", "MAN-00000001", "440", "--commit"], ["trip-resend", "MAN-00000001", "--commit"]]
    assert j["what"] == "trip-price MAN-00000001 440 then trip-resend MAN-00000001" and os.path.exists(Q.DUE)


def test_jobs_run_one_after_another_and_a_stop_ends_its_job_never_tried_again(monkeypatch, tmp_path):
    _queue(monkeypatch, tmp_path)
    a = Q.add([["trip-price", "MAN-00000001", "440", "--commit"], ["trip-resend", "MAN-00000001", "--commit"]],
              what="Price + resend", now=NOW)
    b = Q.add([["order-note", "9100001-1-1", "Emailed DO 26/11", "--commit"]], what="Note", now=NOW)
    ran, rang = [], []

    def step(s):
        ran.append(s[0])
        if s[0] == "trip-resend":
            return {"ok": False, "said": "did not read back as ACCEPTED", "seconds": 40, "notices": [NOTICE]}
        return {"ok": True, "said": f"{s[0]} done", "seconds": 30, "notices": []}
    said = Q.run(step_run=step, is_ready=lambda: (True, ""), ring=lambda t, b: rang.append(t), now=NOW)
    jobs = {j["id"]: j for j in Q.load()["jobs"]}
    assert ran == ["trip-price", "trip-resend", "order-note"] and said == "1 done, 1 stopped"
    assert jobs[a["id"]]["state"] == "stopped" and jobs[a["id"]]["step"] == 1
    assert "trip-resend stopped" in jobs[a["id"]]["said"] and jobs[a["id"]]["notices"] == [NOTICE]
    assert jobs[b["id"]]["state"] == "done" and rang == ["CTMS stopped: Price + resend", "CTMS done: Note"]
    ran.clear()                                                         # nothing runs it again by itself
    assert Q.run(step_run=step, is_ready=lambda: (True, ""), ring=lambda t, b: None) == "nothing ran"
    Q.again(a["id"])                                                    # his Again, after a look: from the resend
    Q.run(step_run=lambda s: ran.append(s[0]) or {"ok": True, "said": "ok", "seconds": 1, "notices": []},
          is_ready=lambda: (True, ""), ring=lambda t, b: None)
    assert ran == ["trip-resend"] and next(j for j in Q.load()["jobs"] if j["id"] == a["id"])["state"] == "done"


def test_nothing_runs_while_ctms_isnt_ready_and_a_waiting_job_can_be_taken_off(monkeypatch, tmp_path):
    _queue(monkeypatch, tmp_path)
    j = Q.add([["order-note", "9100001-1-1", "Emailed DO 26/11", "--commit"]], now=NOW)
    said = Q.run(step_run=lambda s: (_ for _ in ()).throw(AssertionError("ran")),
                 is_ready=lambda: (False, '"Claude can act" is off'), ring=lambda t, b: None, now=NOW)
    p = Q.panel()
    assert "waiting" in said and p["waiting"] == 1 and p["paused"] == '"Claude can act" is off'
    Q.drop(j["id"])
    assert Q.panel()["waiting"] == 0 and Q.load()["jobs"][0]["state"] == "dropped"
    try:
        Q.drop(j["id"])
        raise AssertionError("dropped twice")
    except Q.Refused:
        pass


def test_ready_needs_the_work_pc_claude_can_act_ctms_open_and_nothing_running(monkeypatch):
    import ctms_remote as R
    monkeypatch.setattr(R, "BASE", "x")
    monkeypatch.setattr(Q, "_lock", lambda name, wait: True)
    base = {"online": True, "state": {"window": {"found": True}}, "control": {"armed": True, "left": 1200}}
    cases = [({}, True), ({"online": False}, "offline"), ({"control": {"armed": False}}, "is off"),
             ({"control": {"armed": True, "left": 60}}, "run out"), ({"state": {"window": {}}}, "isn't open"),
             ({"running": {"action": "book"}}, "busy (book)")]
    for change, want in cases:
        st = dict(base, **change)
        monkeypatch.setattr(R, "http", lambda method, path, st=st: (200, st))
        ok, why = Q.ready()
        assert (ok is True) if want is True else (not ok and want in why), (change, ok, why)
    monkeypatch.setattr(Q, "_lock", lambda name, wait: None)            # a booking holds Book's lock
    assert Q.ready() == (False, "a booking is running")


def test_his_yes_on_a_held_ctms_change_goes_to_the_queue_and_the_job_hears_how_it_went(monkeypatch, tmp_path):
    _queue(monkeypatch, tmp_path)
    for name in ("PATH", "LOG", "SEEN", "PUSH_DUE", "CFG", "WORK_DUE", "JUDGE_DUE"):
        monkeypatch.setattr(A, name, str(tmp_path / ("a_" + name.lower())))
    sid = "abc123def456"
    A.save({"mode": "live", "items": {sid: {
        "id": sid, "state": "open", "kind": "needs", "from": "Kim", "subject": "x", "received": "2026-11-26 08:00",
        "job": {"state": "needs_you", "asks": [{"kind": "route", "state": "open", "what": "Set MAN-00000001 to 440",
                                                "route": ["trip-price", "MAN-00000001", "440"]}]}}}})
    assert A.main(["x", "yes", sid, "0"]) == 0
    it = A.load()["items"][sid]
    a = it["job"]["asks"][0]
    assert a["state"] == "queued" and a["queue"] and it["job"]["state"] == "needs_you"     # not settled yet
    job = Q.load()["jobs"][0]
    assert job["steps"] == [["trip-price", "MAN-00000001", "440", "--commit"]] and job["assist"] == {"sid": sid, "n": 0}
    Q.run(step_run=lambda s: {"ok": True, "said": "MAN-00000001 total 440.00", "seconds": 30, "notices": []},
          is_ready=lambda: (True, ""), ring=lambda t, b: None)
    it = A.load()["items"][sid]
    assert it["job"]["asks"][0]["state"] == "done" and it["job"]["state"] == "done" and it["state"] == "dealt"


def test_trip_read_reads_only_the_tabs_asked_for(monkeypatch, capsys):
    monkeypatch.setattr(C, "r_trip_find", lambda a: {"found": "selected", "man": "MAN-00000001", "day": "30/11/26",
                                                       "time": "16:00", "status": "ACCEPTED"})
    asked = []
    monkeypatch.setattr(C, "trip_tabs", lambda words: asked.append(list(words)) or {
        "stops": [{"Stop": "2", "Date": "01/12/26", "Type": "DL", "P Arr": "10:01"}]})
    a = C._args("trip-read").parse_args(["--order", "9100001-1-1", "--tabs", "stops"])
    got = C.r_trip_read(a)
    assert asked == [["stops"]] and got["stops"][0]["Type"] == "DL" and "stop 2 DL" in capsys.readouterr().out
    try:
        C.r_trip_read(C._args("trip-read").parse_args(["--order", "9100001-1-1", "--tabs", "money"]))
        raise AssertionError("a tab that isn't there was read")
    except C.Fail:
        pass
