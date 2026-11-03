"""The booking journal (03/11): a press of Book never books an order twice, finishes what a booking left undone, picks up
an answer the home PC gave up waiting for, and the timer tries Outlook's failed steps again. Made-up orders and hauliers.

    python -m pytest -q tests/test_book_journal.py
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import book_journal as J  # noqa: E402
import book_run as B  # noqa: E402
import book_record  # noqa: E402

DATE = "06/11/2026"
JOB = {"record": "9000001|06/11/2026", "orders": ["9000001"], "date": DATE, "carrier": "ABCHAULAGE_DH",
       "trailer": "NR_ARTIC_FL", "haulier": "ABC Haulage", "vehicles": 1}
TRIP = {"manifest": "MAN-01000001", "status": "ACCEPTED", "cost": "450.00", "revenue": "600",
        "collect": "06/11/26 07:30", "deliver": "06/11/26 08:30"}


@pytest.fixture
def jpath(tmp_path, monkeypatch):
    p = str(tmp_path / "_book_journal.json")
    monkeypatch.setattr(J, "PATH", p)
    return p


# -- the journal on its own
def test_one_job_is_its_orders_and_day_whatever_order_or_spacing_they_come_in():
    assert J.key(["9000002", " 9000001"], DATE) == J.key(["9000001", "9000002"], DATE)
    assert J.key(["9000001"], DATE) != J.key(["9000001"], "07/11/2026")
    assert J.key(["AH30-7-26G5ML"], DATE).startswith("AH30-7-26G5ML@")      # an ad hoc's own dashes are kept


def test_nothing_on_file_books_and_an_accepted_trip_makes_it_booked_with_its_steps(jpath):
    k = J.key(JOB["orders"], DATE)
    assert J.verdict(J.get(k)) == "book"
    J.asking(JOB)
    assert J.verdict(J.get(k)) == "recall"
    e = J.answered(k, True, "Booked", [TRIP], JOB["carrier"])
    assert e["state"] == "booked"
    assert J.left(e) == ["digihaul", "site_email", "filed", "off_map"]      # a _DH carrier's row, not Parcel Pass
    assert J.verdict(e) == "resume"


def test_parcel_pass_is_told_and_our_own_fleet_has_no_digihaul_row():
    assert J.needs("PASS_DH") == ["digihaul", "pass_email", "site_email", "filed", "off_map"]
    assert J.needs("DHL_NOC") == ["site_email", "filed", "off_map"]


def test_a_stop_after_the_first_vehicle_is_still_booked_and_says_what_was_left_short(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    e = J.answered(k, False, "Stopped after 80s: the carrier box", [TRIP, {"manifest": "MAN-01000002", "status": "PLANNED"}],
                   JOB["carrier"])
    assert e["state"] == "booked" and e["short"] == ["MAN-01000002 PLANNED"]
    assert [t["manifest"] for t in J.accepted(e)] == ["MAN-01000001"]


def test_a_manifest_only_planned_is_held_for_him_and_nothing_made_is_clear(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    assert J.answered(k, False, "stopped", [{"manifest": "MAN-01000002", "status": "PLANNED"}])["state"] == "half"
    assert J.verdict(J.get(k)) == "hold"
    J.asking(JOB)
    assert J.answered(k, False, "isn't in the order well", [])["state"] == "clear"
    assert J.verdict(J.get(k)) == "book"


def test_a_failed_outlook_step_comes_round_again_on_the_timer_then_waits_for_him(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    J.answered(k, True, "Booked", [TRIP], JOB["carrier"], now=1000.0)
    J.step(k, "site_email", False, "Outlook busy", now=1000.0)
    assert J.due(now=1000.0 + J.BACKOFF[1] - 1) == [(k, ["filed", "off_map"])]   # the email not yet; the rest straight on
    assert ("site_email" in dict(J.due(now=1000.0 + J.BACKOFF[1]))[k])
    J.step(k, "site_email", False, "busy", now=2000.0)
    J.step(k, "site_email", False, "busy", now=3000.0)
    assert all("site_email" not in st for _, st in J.due(now=10 ** 7))          # three tries: his Retry now
    item = next(i for i in J.open_items() if i["key"] == k)
    assert any(t["step"] == "site_email" and not t["auto"] for t in item["todo"])
    assert "Retry" in item["need"]


def test_the_digihaul_row_is_never_the_timers(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    J.answered(k, True, "Booked", [TRIP], JOB["carrier"], now=1000.0)
    assert all("digihaul" not in st for _, st in J.due(now=10 ** 7))


def test_every_step_done_or_taken_by_hand_finishes_it(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    J.answered(k, True, "Booked", [TRIP], "DHL_NOC")
    J.step(k, "site_email", True, "emailed")
    J.step(k, "filed", True)
    assert J.get(k)["state"] == "booked"
    J.by_hand(k, "off_map")
    assert J.get(k)["state"] == "done" and J.verdict(J.get(k)) == "finished"
    assert not [i for i in J.open_items() if i["key"] == k]


def test_clearing_an_unknown_job_with_nothing_accepted_lets_the_next_press_book(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    J.lost(k, "no record")
    assert J.verdict(J.get(k)) == "hold"
    J.by_hand(k)
    assert J.verdict(J.get(k)) == "book"


def test_an_ask_long_unanswered_is_looked_for_again(jpath):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB, now=1000.0)
    assert J.unanswered(now=1000.0 + 60) == []
    assert J.unanswered(now=1000.0 + J.LOST_AFTER) == [k]


# -- the work PC's own record
def test_the_work_pc_keeps_each_booking_and_hands_back_only_that_commands(tmp_path):
    p = str(tmp_path / "rec.jsonl")
    book_record.keep(41, ["9000001"], DATE, "ABC_DH", False, True, "Booked", [TRIP], path=p)
    book_record.keep(42, ["9000001"], DATE, "ABC_DH", True, True, "Rehearsed", [TRIP], path=p)
    book_record.keep(43, ["9000001"], DATE, "ABC_DH", False, False, "Stopped", [], "box", path=p)
    assert [e["id"] for e in book_record.recall(["9000001"], DATE, path=p)] == [43, 41]     # no rehearsal
    assert [e["id"] for e in book_record.recall(["9000001"], DATE, ask_id=41, path=p)] == [41]
    assert book_record.recall(["9000001"], DATE, ask_id=99, path=p) == []                    # not that press's
    assert book_record.recall(["9000001"], "07/11/2026", path=p) == []


def test_the_work_pc_record_keeps_no_more_than_its_limit(tmp_path, monkeypatch):
    p = str(tmp_path / "rec.jsonl")
    monkeypatch.setattr(book_record, "KEEP", 5)
    for i in range(9):
        book_record.keep(i, ["9000001"], DATE, "X", False, True, "", [], path=p)
    with open(p, encoding="utf-8") as f:
        assert [json.loads(x)["id"] for x in f] == [4, 5, 6, 7, 8]


# -- a press of Book through the journal
class Stop(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


class FakeR:
    """The work PC as book_run asks it: ctms_book's answer, a lost answer, the dashboard and the work PC's record."""

    def __init__(self, answer=None, timeout=False, held=None, record=None):
        self.answer, self.timeout, self.held, self.record = answer, timeout, held, record
        self.asked = []
        self.Stop = Stop

    def ask_waiting(self, action, wait_total=90, on_id=None, **args):
        self.asked.append((action, args))
        if on_id:
            on_id(77)
        if self.timeout:
            raise Stop("No answer from the work PC in time.", 4)
        return self.answer

    def result_of(self, cid):
        return self.held or (None, None)

    def ask(self, action, wait_total=90, **args):
        self.asked.append((action, args))
        if action == "book_recall":
            return {"ok": True, "detail": ""}, {"found": self.record or []}
        return {"ok": True}, {}


@pytest.fixture
def steps(jpath, monkeypatch):
    """Every step after the booking, recorded instead of done."""
    done = []
    monkeypatch.setattr(B, "_lock", lambda: True)
    monkeypatch.setattr(B, "owed_first", lambda orders: [])
    monkeypatch.setattr(B, "record_of", lambda ident: {"orders": ["9000001"], "to": "site@example.com"})
    monkeypatch.setattr(B, "tracker_rows", lambda R, trips, carrier, now=None: (done.append(("row", trips[0]["manifest"])) or 1, ""))
    monkeypatch.setattr(B, "site_email", lambda rec, job, trips: (done.append(("site", trips[0]["manifest"])) or True, "emailed x"))
    monkeypatch.setattr(B, "pass_email", lambda rec, trips, orders: (done.append(("pass",)) or True, "emailed pass"))
    monkeypatch.setattr(B, "file_away", lambda rec: done.append(("filed",)) or 1)
    monkeypatch.setattr(B, "take_off", lambda ident: (done.append(("off",)) or True, ""))
    monkeypatch.setattr(B, "sent_already", lambda *a, **k: False)
    return done


def _answer(trips, ok=True, detail="Booked 9000001 in 50s: MAN-01000001 ACCEPTED"):
    return {"ok": ok, "detail": detail}, {"trips": trips, "seconds": 50}


def test_a_booking_writes_the_row_emails_the_site_files_and_takes_it_off_in_that_order(steps):
    res = B.book(dict(JOB), R=FakeR(_answer([TRIP])))
    assert res["ok"]
    assert steps == [("row", "MAN-01000001"), ("site", "MAN-01000001"), ("filed",), ("off",)]
    assert J.get(J.key(JOB["orders"], DATE))["state"] == "done"


def test_pressing_book_again_on_a_finished_job_books_nothing(steps):
    R = FakeR(_answer([TRIP]))
    B.book(dict(JOB), R=R)
    R.asked.clear()
    steps.clear()
    res = B.book(dict(JOB), R=R)
    assert res["ok"] and "Nothing booked again" in res["said"]
    assert R.asked == [] and steps == []


def test_a_second_press_after_a_failed_email_only_sends_the_email(steps, monkeypatch):
    monkeypatch.setattr(B, "site_email", lambda rec, job, trips: (False, "Outlook busy"))
    R = FakeR(_answer([TRIP]))
    B.book(dict(JOB), R=R)
    assert ("filed",) not in steps                           # the chain stays where the email's retry finds its thread
    monkeypatch.setattr(B, "site_email", lambda rec, job, trips: (steps.append(("site", "again")) or True, "emailed"))
    R.asked.clear()
    steps.clear()
    res = B.book(dict(JOB), R=R)
    assert "Nothing booked again" in res["said"]
    assert R.asked == []                                     # CTMS not asked
    assert steps == [("site", "again"), ("filed",)]          # the row is not pasted twice; the chain filed after


def test_a_retried_email_that_had_gone_already_is_not_sent_twice(steps, monkeypatch):
    monkeypatch.setattr(B, "site_email", lambda rec, job, trips: (False, "the run died after Send"))
    B.book(dict(JOB), R=FakeR(_answer([TRIP])))
    monkeypatch.setattr(B, "sent_already", lambda *a, **k: True)
    monkeypatch.setattr(B, "site_email", lambda rec, job, trips: pytest.fail("sent twice"))
    B.book(dict(JOB), R=FakeR(_answer([TRIP])))
    assert J.get(J.key(JOB["orders"], DATE))["steps"]["site_email"]["ok"]


def test_the_home_pc_giving_up_waiting_books_nothing_twice_and_picks_up_what_was_made(steps):
    R = FakeR(timeout=True)
    res = B.book(dict(JOB), R=R)
    assert not res["ok"] and res.get("pending")
    k = J.key(JOB["orders"], DATE)
    assert J.get(k)["state"] == "asking" and J.get(k)["ask_id"] == 77
    again = B.book(dict(JOB), R=R)                            # pressed again straight away: nothing to be had yet
    assert again.get("pending") and [a for a, _ in R.asked].count("ctms_book") == 1
    R.record = [{"id": 77, "ok": True, "said": "Booked", "trips": [TRIP]}]       # the work PC's own record has it
    res = B.book(dict(JOB), R=R)
    assert res["ok"] and "Already booked in CTMS: MAN-01000001" in res["said"]
    assert [a for a, _ in R.asked].count("ctms_book") == 1
    assert ("site", "MAN-01000001") in steps


def test_a_lost_answer_still_held_by_the_dashboard_is_used(steps):
    R = FakeR(timeout=True)
    B.book(dict(JOB), R=R)
    R.held = _answer([TRIP])
    res = B.book(dict(JOB), R=R)
    assert res["ok"] and res.get("resumed")


def test_the_timer_finds_a_lost_answer_and_sends_what_follows_but_leaves_the_row_to_him(steps, monkeypatch):
    R = FakeR(timeout=True)
    B.book(dict(JOB), R=R)
    k = J.key(JOB["orders"], DATE)
    monkeypatch.setattr(J, "LOST_AFTER", 0)
    R.record = [{"id": 77, "ok": True, "said": "Booked", "trips": [TRIP]}]
    monkeypatch.setattr(B, "_client", lambda: R)
    B.retry()
    e = J.get(k)
    assert e["state"] == "booked"
    assert ("site", "MAN-01000001") in steps and not any(s[0] == "row" for s in steps)
    assert J.left(e) == ["digihaul"]
    assert any("Retry" in i["need"] for i in J.open_items() if i["key"] == k)


def test_a_refused_ask_made_nothing_and_the_next_press_books(steps):
    class Off(FakeR):
        def ask_waiting(self, action, wait_total=90, on_id=None, **args):
            raise Stop("Acting is switched off.", 5)
    res = B.book(dict(JOB), R=Off())
    assert not res["ok"] and "Nothing was booked" in res["said"]
    assert J.verdict(J.get(J.key(JOB["orders"], DATE))) == "book"


def test_a_stop_after_the_first_vehicle_still_tells_the_site_about_it(steps):
    res = B.book(dict(JOB, vehicles=2), R=FakeR(_answer([TRIP, {"manifest": "MAN-01000002", "status": "PLANNED"}],
                                                        ok=False, detail="Stopped after 90s: the carrier box")))
    assert res["ok"] and "Then CTMS stopped" in res["said"]
    assert ("site", "MAN-01000001") in steps


def test_a_rehearsal_never_touches_the_journal(steps, jpath):
    B.book(dict(JOB, dry=True), R=FakeR(_answer([TRIP], detail="Rehearsed")))
    assert not os.path.exists(jpath)


def test_a_trip_with_no_cost_on_file_leaves_the_row_to_him_rather_than_type_it_blank(steps):
    k = J.key(JOB["orders"], DATE)
    J.asking(JOB)
    J.asked(k, 5)
    R = FakeR(held=({"ok": True, "detail": "Booked 9000001 in 50s: MAN-01000009 ACCEPTED"}, None))
    res = B.book(dict(JOB), R=R)                              # the payload had gone: manifests from the words alone
    assert res["ok"] and "cost of MAN-01000009 isn't known" in res["said"]
    assert not any(s[0] == "row" for s in steps)


# -- the dashboard lets the home PC ask the work PC's record, as a look
def test_the_dashboard_passes_a_recall_as_a_look_with_only_its_orders_day_and_command():
    import importlib
    os.environ.setdefault("DASH_KEY", "dash-test-key")
    os.environ.setdefault("AGENT_KEY", "agent-test-key")
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "cloud"))
    S = importlib.import_module("server")
    assert "book_recall" in S.CTMS_READ and "book_recall" not in S.CTMS_DRIVE
    got = S._ctms_args("book_recall", {"orders": ["9000001", "x; rm"], "date": DATE, "ask": 77, "carrier": "EVIL"})
    assert got == {"orders": ["9000001"], "date": DATE, "ask": 77}


def test_the_bridge_answers_a_recall_from_its_record_without_needing_the_switch():
    import ctms_bridge
    assert "book_recall" in ctms_bridge.READ and "book_recall" not in ctms_bridge.DRIVE
