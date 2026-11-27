"""Auto-answers (auto_answer.py + inbox_assist.py, 25/11): an email whose only question Book has answered - booked?
when? who? the ref? - is answered by itself in his own booking words, only after CTMS confirms the manifest, only to
Network Rail and the order's site contacts, only in working hours. Made-up people, orders and manifests only; no
Outlook, no Claude and no CTMS - all three are stood in for.

    python -m pytest tests/test_auto_answer.py
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import auto_answer as aa  # noqa: E402
import inbox_assist as A  # noqa: E402
import inbox_watch as W  # noqa: E402

NOW = datetime(2026, 11, 25, 10, 0)                     # a Wednesday morning
MATERIALS = "a Network Rail materials team"
SITE = "outside (a supplier, site or other company)"


def job(**kw):
    j = {"state": "done", "orders": ["1234567"], "date": "01/12/2026", "carrier": "MADEUP_DH",
         "haulier": "Made Up Haulage",
         "trips": [{"manifest": "MAN-00000001", "status": "ACCEPTED", "collect": "30/11/26 08:00",
                    "deliver": "01/12/26 10:00", "lines": ["1234567-1-1"]}],
         "record_copy": {"details": {"time": {"earliest": "10:00", "latest": "14:00"}}, "to": "kim.site@site.example"},
         "steps": {"site_email": {"ok": True, "said": "emailed kim.site@site.example and lee.other@site.example"}}}
    j.update(kw)
    return j


def ctx():
    return {"me": {"me.desk@dhl.example"}, "my_names": ["pat desk"], "managers": ["sam boss"],
            "materials": {"steelmaterials@nr.example"}, "haulier_addrs": {"ops@haul.example"},
            "haulier_domains": {"haul.example"}, "handled": W.taken_in([], [])}


def confirmed(job, now):
    return True, f"CTMS {now:%d/%m %H:%M}: MAN-00000001 ACCEPTED as booked"


# ---------- which booking ----------
def test_one_booking_covers_the_orders_named_or_it_is_left_for_him():
    jobs = {"a": job()}
    assert aa.find_job(["1234567-1-1"], jobs)[0] == "a"
    assert "names no order" in aa.find_job(["AH01/12/26XYZ"], jobs)[2]
    assert "wasn't booked through Book" in aa.find_job(["7654321"], jobs)[2]
    assert "wasn't booked through Book" in aa.find_job(["1234567", "7654321"], jobs)[2]
    jobs["b"] = job(date="02/12/2026")                      # booked over two days: which one they mean is his
    assert "more than one job" in aa.find_job(["1234567"], jobs)[2]
    jobs = {"a": job(), "c": job(state="half")}             # a booking CTMS hasn't settled
    assert "isn't settled" in aa.find_job(["1234567"], jobs)[2]
    jobs = {"a": job(), "c": job(state="clear")}            # cleared: CTMS booked nothing that time
    assert aa.find_job(["1234567"], jobs)[0] == "a"


def test_only_an_accepted_booking_for_a_later_day_and_not_a_split_one():
    assert aa.check_job(job(), NOW) == ""
    t = dict(job()["trips"][0], status="PLANNED")
    assert "ACCEPTED" in aa.check_job(job(trips=[t]), NOW)
    assert "today or past" in aa.check_job(job(date="25/11/2026"), NOW)
    assert "today or past" in aa.check_job(job(date="24/11/2026"), NOW)
    split = {"details": {}, "collections": [{"site": "Depot A", "date": "30/11/2026"},
                                            {"site": "Depot B", "date": "30/11/2026"}]}
    assert "split" in aa.check_job(job(record_copy=split), NOW)                # several pick-ups
    days = {"details": {"date": {"options": ["01/12/2026", "02/12/2026"]}}}
    assert "split" in aa.check_job(job(record_copy=days), NOW)                 # several days
    choice = {"details": {"date": {"options": ["01/12/2026", "02/12/2026"], "raw": "Would 01/12/26 or 02/12/26 suit?"}}}
    assert aa.check_job(job(record_copy=choice), NOW) == ""                    # a choice of days: one delivery
    rec = {"orders": ["1234567"], "delivery_date": "03/12/2026"}  # the tracker moved it after Book booked it
    assert "the tracker has it on 03/12/2026" in aa.check_job(job(), NOW, [rec])


def test_only_network_rail_and_the_orders_own_site_contacts():
    assert aa.sender_ok(MATERIALS, "steelmaterials@nr.example", job()) == ""
    assert aa.sender_ok(SITE, "Lee.Other@site.example", job()) == ""     # Book's site email went to them
    assert aa.sender_ok(SITE, "kim.site@site.example", job(steps={})) == ""   # the order's own contact
    for who in ("one of his managers", "a haulier", "a DHL colleague", "the DHL Road shared mailbox", SITE):
        assert aa.sender_ok(who, "someone@else.example", job()) != ""


def test_the_answer_is_his_own_booking_email_never_a_price():
    text = aa.answer_text(job(), "Site, Kim")
    assert text == ("Hi Kim,\n\nThis order has been arranged with Made Up Haulage for Tuesday 01/12/2026, delivering "
                    "between 10:00 and 14:00. Here is the ref number MAN-00000001")
    assert aa.text_checks(text, job()) == []
    assert "our own DHL fleet" in aa.answer_text(job(carrier="DHL_NOC"), "Kim Site")
    assert aa.text_checks(text + " £450", job()) == ["a price"]
    assert "MAN-00000002 missing" in aa.text_checks(text, job(trips=job()["trips"] + [
        dict(job()["trips"][0], manifest="MAN-00000002")]))


# ---------- CTMS, read there and then ----------
class _Proc:
    def __init__(self, out):
        self.stdout, self.stderr = out, ""


def _ran(answers):
    calls = []

    def run(args, **kw):
        calls.append(args[2:])
        got = answers.pop(0)
        return _Proc("Selected ...\nROUTE_RESULT " + json.dumps(got))
    return run, calls


def _stops(dl_day="01/12/26", dl_time="10:01"):
    """The Stops tab as trip-read gives it (the shape read 24/11): a start, then the delivery."""
    return [{"Stop": "30/11/26", "Type": "SU", "P Arr": "07:40", "P Dep": "08:20", "Location": "MADE UP DEPOT"},
            {"Stop": "2", "Date": dl_day, "Type": "DL", "P Arr": dl_time, "P Dep": "10:41", "Location": "MADE UP SITE"}]


def test_ctms_must_show_the_manifest_accepted_delivering_when_book_booked_it():
    """26/11 live: Planning's list showed a booked trip at 16:00 - neither its 08:00 collection nor its 23:30 delivery -
    so the check reads the trip's own delivery stop, found by its order line."""
    ok = {"ok": True, "found": "selected", "man": "MAN-00000001", "day": "30/11/26", "time": "16:00",
          "status": "ACCEPTED", "stops": _stops()}
    run, calls = _ran([dict(ok)])
    got = aa.ctms_check(job(), NOW, run=run, lock=lambda: True)
    assert got[0] is True and "MAN-00000001 delivering 01/12 10:01" in got[1]
    assert calls == [["trip-read", "--order", "1234567-1-1", "--tabs", "stops"]]       # never the EFX ref first
    for bad, why in ((dict(ok, status="PLANNED"), "PLANNED in CTMS"),
                     (dict(ok, stops=_stops(dl_time="13:30")), "CTMS delivers at 01/12 13:30, Book booked 01/12 10:00"),
                     (dict(ok, stops=_stops(dl_day="02/12/26")), "CTMS delivers at 02/12 10:01"),
                     (dict(ok, stops=_stops()[:1]), "no delivery stop"),
                     (dict(ok, man="MAN-00000009"), "not MAN-00000001"), ({"ok": True, "found": "list"}, "more than"),
                     ({"ok": False, "said": "Look mum, no hands is off"}, "couldn't be read")):
        run, _ = _ran([bad])
        got = aa.ctms_check(job(), NOW, run=run, lock=lambda: True)
        assert got[0] is False and why in got[1], (bad, got)
    # CTMS plans the arrival a minute or so off the booked window: that's still as booked
    run, _ = _ran([dict(ok, stops=_stops(dl_time="09:31"))])
    assert aa.ctms_check(job(), NOW, run=run, lock=lambda: True)[0] is True
    # a booking running in CTMS: never driven over it
    run, calls = _ran([dict(ok)])
    assert aa.ctms_check(job(), NOW, run=run, lock=lambda: None) == (False, "a booking is running in CTMS")
    assert calls == []
    # no order line in Book's journal to find it by: held
    t = dict(job()["trips"][0], lines=[])
    assert "no order line" in aa.ctms_check(job(trips=[t]), NOW, run=run, lock=lambda: True)[1]


def test_a_single_drop_closes_the_trip_and_its_wait_counts():
    """26/11 live, a booked rails trip: SU at the supplier 16:00, then CL at the site 17:06 with a 06:24 wait - 23:30, the
    time Book booked. (Made-up names here.)"""
    stops = [{"Stop": "1", "Date": "30/11/26", "Type": "SU", "P Arr": "16:00", "P Dep": "16:40", "Location": "SUPPLIER"},
             {"Stop": "2", "Date": "30/11/26", "Type": "CL", "P Arr": "17:06", "P Dep": "00:10", "Wait": "06:24",
              "Location": "MADE UP SITE"}]
    ok, at = aa.delivery_matches(stops, "30/11/26 23:30")
    assert ok and at == datetime(2026, 11, 30, 23, 30)
    ok, why = aa.delivery_matches(stops, "30/11/26 17:30")          # moved earlier in CTMS: it no longer matches
    assert not ok and "CTMS delivers at 30/11 23:30" in why
    assert aa.delivery_matches(stops[:1], "30/11/26 23:30") == (False, "CTMS shows no delivery stop on the trip")


def test_a_delivery_stop_is_read_even_when_its_number_cell_is_missing():
    stops = [{"Stop": "01/12/26", "Date": None, "Type": "DL", "P Arr": "10:00"}]
    ok, at = aa.delivery_matches(stops, "01/12/26 10:00")
    assert ok and at == datetime(2026, 12, 1, 10, 0)
    assert aa.delivery_matches(stops, "not a time")[0] is False


def test_the_answer_kept_on_the_email():
    it = {"orders": ["1234567"], "from": "Steel Materials", "addr": "steelmaterials@nr.example"}
    a = aa.answer(it, MATERIALS, {"a": job()}, [], NOW, check=confirmed)
    assert a["state"] == "ready" and a["text"].startswith("Hi Steel,") and a["mans"] == ["MAN-00000001"]
    assert a["checked_at"] == "2026-11-25 10:00" and a["tries"] == 1
    a = aa.answer(it, MATERIALS, {"a": job()}, [], NOW, check=lambda j, n: (False, "CTMS couldn't be read: closed"))
    assert a["state"] == "unchecked" and a["text"] and "closed" in a["why"]
    a = aa.answer(dict(it, addr="ops@haul.example"), "a haulier", {"a": job()}, [], NOW, check=confirmed)
    assert a["state"] == "held" and not a["text"]


def test_when_it_may_go():
    assert aa.in_hours(NOW) and not aa.in_hours(NOW.replace(hour=6, minute=59)) and not aa.in_hours(NOW.replace(hour=19))
    assert not aa.in_hours(datetime(2026, 11, 28, 10, 0))                       # a Saturday
    assert not aa.in_hours(NOW, {"2026-11-25"})                                 # a bank holiday
    it = {"state": "open", "kind": "needs", "auto": {"state": "ready", "text": "x", "checked_at": "2026-11-25 09:00"}}
    assert aa.due(it, NOW, "live") and not aa.due(it, NOW, "shadow")
    assert not aa.due(it, NOW + timedelta(hours=3), "live")                     # its check has gone stale
    un = {"state": "open", "kind": "needs", "auto": {"state": "unchecked", "tries": 1, "checked_at": "2026-11-25 09:25"}}
    assert aa.recheck_due(un, NOW, "live") and not aa.recheck_due(un, NOW, "shadow")
    assert not aa.recheck_due(un, NOW.replace(hour=9, minute=50), "live")       # tried under half an hour ago
    assert not aa.recheck_due(dict(un, auto=dict(un["auto"], tries=8)), NOW, "live")


def test_who_a_reply_to_all_would_reach():
    c = ctx()
    assert aa.recipient_checks(["kim.site@site.example"], c, "Kim.Site@site.example") == []
    assert "a haulier (ops@haul.example) is on the thread" in aa.recipient_checks(
        ["kim.site@site.example", "ops@haul.example"], c, "kim.site@site.example")
    assert "the sender isn't on the reply" in aa.recipient_checks(["lee@site.example"], c, "kim.site@site.example")
    many = [f"p{n}@site.example" for n in range(13)]
    assert "13 people on it" in aa.recipient_checks(many, c, "p0@site.example")


# ---------- in the inbox assistant ----------
def _wire(monkeypatch, tmp_path, mode="live", auto="live", items=None, jobs=None):
    for name in ("PATH", "LOG", "SEEN", "JUDGE_DUE", "PUSH_DUE", "CFG"):
        monkeypatch.setattr(A, name, str(tmp_path / ("x_" + name.lower())))
    jp = tmp_path / "journal.json"
    jp.write_text(json.dumps({"jobs": jobs if jobs is not None else {"1234567@01/12/2026": job()}}))
    monkeypatch.setattr(aa, "JOURNAL", str(jp))
    monkeypatch.setattr(W, "context", lambda *a, **k: ctx())
    A.save({"mode": mode, "auto": auto, "items": items or {}})


def _pending(sid="q1", **kw):
    it = {"id": sid, "eid": "E" + sid, "conv": "C" + sid, "from": "Steel Materials", "addr": "steelmaterials@nr.example",
          "subject": "1234567 delivery", "received": "2026-11-25 09:30", "unread": True, "orders": ["1234567"],
          "state": "open", "kind": "pending", "text": "Hi, is 1234567 booked and when is it coming?", "atts": []}
    it.update(kw)
    return it


def _claude(asks_booking=True, needs=True):
    def ask(system, prompt, cfg):
        assert "booked by Book for 01/12/2026 with Made Up Haulage" in prompt       # Claude sees what Book knows
        assert "asks_booking" in system
        return True, {"needs_you": needs, "urgency": "today", "ask": "Steel Materials ask if 1234567 is booked",
                      "action": {"type": "reply", "text": "Hi,\n\nYes it is booked for Monday."},
                      "asks_booking": asks_booking, "why": "w"}
    return ask


def test_a_booking_question_gets_books_answer_not_claudes(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, items={"q1": _pending()})
    done, said = A.judge(ask=_claude(), now=NOW, check=confirmed)
    it = A.load()["items"]["q1"]
    assert done == 1 and it["kind"] == "needs" and it["auto"]["state"] == "ready"
    assert it["action"]["text"].startswith("Hi Steel,\n\nThis order has been arranged with Made Up Haulage")
    assert "Monday" not in it["action"]["text"]                                 # Claude's words are gone
    # a question that asks more than that keeps Claude's suggestion and nothing goes by itself
    _wire(monkeypatch, tmp_path, items={"q1": _pending()})
    A.judge(ask=_claude(asks_booking=False), now=NOW, check=confirmed)
    it = A.load()["items"]["q1"]
    assert "auto" not in it and it["action"]["text"] == "Hi,\n\nYes it is booked for Monday."
    # auto-answers off: nothing made
    _wire(monkeypatch, tmp_path, auto="off", items={"q1": _pending()})
    A.judge(ask=_claude(), now=NOW, check=confirmed)
    assert "auto" not in A.load()["items"]["q1"]
    # a haulier asking: held, Claude's suggestion kept
    _wire(monkeypatch, tmp_path, items={"q1": _pending(addr="ops@haul.example", **{"from": "Haul Ops"})})
    A.judge(ask=_claude(), now=NOW, check=confirmed)
    it = A.load()["items"]["q1"]
    assert it["auto"]["state"] == "held" and it["action"]["text"] == "Hi,\n\nYes it is booked for Monday."


def _ready(sid="r1", checked="2026-11-25 09:55", received="2026-11-25 09:30", **kw):
    it = {"id": sid, "eid": "E" + sid, "conv": "C" + sid, "from": "Steel Materials",
          "addr": "steelmaterials@nr.example", "subject": "1234567 delivery", "received": received, "unread": True,
          "orders": ["1234567"], "state": "open", "kind": "needs", "urgency": "now", "ask": "booked?",
          "action": {"type": "reply", "text": "Hi Steel,\n\nThis order has been arranged with ...", "note": ""},
          "auto": {"state": "ready", "text": "Hi Steel,\n\nThis order has been arranged with ...",
                   "checked_at": checked, "tries": 1, "said": "CTMS ok"}}
    it.update(kw)
    return it


def _sends(monkeypatch, fail=None):
    sent = []

    def send_reply(d, sid, text=None, now=None, outlook=None, by="him", extra=None):
        if fail:
            raise RuntimeError(fail)
        assert by == "assistant" and extra(["steelmaterials@nr.example"]) == []
        assert extra(["steelmaterials@nr.example", "ops@haul.example"])          # a haulier on it stops it
        sent.append((sid, text))
        d["items"][sid].update(state="answered", sent_at=now.strftime("%Y-%m-%d %H:%M"))
        return "Sent to steelmaterials@nr.example and filed to Regions/Region 2/Completed."
    monkeypatch.setattr(A, "send_reply", send_reply)
    return sent


def test_live_answers_go_in_working_hours_capped_and_shadow_sends_nothing(monkeypatch, tmp_path):
    items = {f"r{n}": _ready(f"r{n}", received=f"2026-11-25 09:{10 + n}") for n in range(7)}
    _wire(monkeypatch, tmp_path, items=items)
    sent = _sends(monkeypatch)
    d = A.load()
    assert A._auto_send(d, NOW, ctx()) == aa.PER_RUN and [s for s, _ in sent] == ["r0", "r1", "r2", "r3", "r4"]
    assert d["items"]["r0"]["auto"]["state"] == "sent" and d["items"]["r6"]["auto"]["state"] == "ready"
    assert A.panel(d, NOW)["auto"]["sent"][0]["text"].startswith("Hi Steel")
    # shadow, out of hours: nothing
    for mode, now in (("shadow", NOW), ("live", NOW.replace(hour=20))):
        _wire(monkeypatch, tmp_path, auto=mode, items={"r1": _ready()})
        sent = _sends(monkeypatch)
        d = A.load()
        assert A._auto_send(d, now, ctx()) == 0 and sent == [] and d["items"]["r1"]["auto"]["state"] == "ready"


def test_a_stale_check_is_done_again_and_a_failed_send_stays_his(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, items={"r1": _ready(checked="2026-11-25 06:30")})
    sent = _sends(monkeypatch)
    d = A.load()
    assert A._auto_send(d, NOW, ctx()) == 0 and sent == []
    assert d["items"]["r1"]["auto"]["state"] == "unchecked" and aa.recheck_due(d["items"]["r1"], NOW, "live")
    _wire(monkeypatch, tmp_path, items={"r1": _ready()})
    _sends(monkeypatch, fail="not sent, it's in Drafts: DHL Road is on it")
    d = A.load()
    assert A._auto_send(d, NOW, ctx()) == 0
    it = d["items"]["r1"]
    assert it["auto"]["state"] == "failed" and "DHL Road" in it["auto"]["why"] and it["action"]["text"]
    assert [x[0]["id"] for x in A._alerts_due(d, NOW)] == ["r1"]              # it rings: it's his now


def test_an_answer_about_to_go_never_rings_his_phone(monkeypatch, tmp_path):
    d = {"mode": "live", "auto": "live", "items": {"r1": _ready()}}
    assert A._alerts_due(d, NOW) == []
    d["auto"] = "shadow"                                                      # in shadow it's his: it rings
    assert [x[0]["id"] for x in A._alerts_due(d, NOW)] == ["r1"]


def test_the_judge_tries_ctms_again_for_one_it_couldnt_confirm(monkeypatch, tmp_path):
    un = _ready(auto={"state": "unchecked", "text": "old", "checked_at": "2026-11-25 09:00", "tries": 2,
                      "why": "CTMS couldn't be read"})
    _wire(monkeypatch, tmp_path, items={"r1": un})
    done, said = A.judge(ask=lambda *a: (_ for _ in ()).throw(AssertionError("no Claude for a recheck")), now=NOW,
                         check=confirmed)
    it = A.load()["items"]["r1"]
    assert it["auto"]["state"] == "ready" and it["auto"]["tries"] == 3 and it["auto"]["text"].startswith("Hi Steel")
    assert it["action"]["text"] == it["auto"]["text"]
    # the booking went away from Book's journal meanwhile: held, the old words off the card
    un["auto"]["checked_at"] = "2026-11-25 09:00"
    _wire(monkeypatch, tmp_path, items={"r1": un}, jobs={})
    A.judge(ask=lambda *a: (True, {}), now=NOW, check=confirmed)
    it = A.load()["items"]["r1"]
    assert it["auto"]["state"] == "held" and it["action"]["text"] == ""


def test_the_switch_and_the_card(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, auto="shadow", items={"r1": _ready()})
    assert A.main(["x", "auto", "live"]) == 0 and A.load()["auto"] == "live"
    assert A.main(["x", "auto", "sometimes"]) == 1
    p = A.panel(A.load(), NOW)
    assert p["auto"]["mode"] == "live" and p["auto"]["ready"] == 1 and p["needs"][0]["auto"]["state"] == "ready"
    fresh = tmp_path / "fresh.json"
    monkeypatch.setattr(A, "PATH", str(fresh))
    assert A.load()["auto"] == "shadow"                                       # how it starts
