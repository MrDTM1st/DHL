"""The CTMS to-do run around its items: each one a command to the work PC, ticked off only when it says done; one that goes wrong
doesn't stop the rest unless CTMS couldn't be left clean; email chains filed at the end. What each item does on the work PC is
tests/test_ctms_items.py. Made-up orders only.

    python tests/test_ctms_run.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_run as X  # noqa: E402
import ctms_run_plan  # noqa: E402
import ctms_todo  # noqa: E402


def _note(i, ref="9100001-1-1"):
    return {"id": i, "kind": "note", "orders": [ref[:7]], "status": "ready", "lines": [ref], "set": {"note": " - Emailed DO 28/10"}}


def _update(i, ref="9100002-1-1"):
    return {"id": i, "kind": "update", "orders": [ref[:7]], "status": "ready", "lines": [ref],
            "set": {"deliver": "05/11/26 08:00-12:00"}}


class FakeRemote:
    """ctms_remote as the run uses it: each command answered by what the work PC is scripted to say for that item."""

    def __init__(self, answers=None):
        self.answers, self.items, self.posts, self.looked = dict(answers or {}), [], [], None

    def ask(self, action, wait_total=90, **args):
        if action == "ctms_check":
            self.items.append(("ctms_check", args["orders"]))
            return self.looked
        self.items.append((action, args))
        ref = args["item"]["lines"][0]
        answer = self.answers.get(ref, {"done": True, "clean": True, "said": f"{ref}: done"})
        if isinstance(answer, Exception):
            raise answer
        return {"ok": True, "detail": answer["said"]}, {"kind": "ctms_item", "seconds": 12, **answer}

    def trace(self, *a):
        pass

    def http(self, method, path, body=None):
        self.posts.append((path, json.loads(json.dumps(body))))         # as it left, not as the list is later
        return 200, {}


def _run(plan, fake, ids=None, filed=None, run_id=0):
    ticked = []
    keep = (ctms_run_plan.load, ctms_todo.done, X._client, X.FILE)
    try:
        ctms_run_plan.load = (lambda found=None: plan) if not callable(plan) else plan
        ctms_todo.done = ticked.append
        X._client = lambda: fake
        X.FILE = lambda p: (filed.append(p["id"]) if filed is not None else None) or "; 2 email(s) filed"
        out = X.run(ids or [p["id"] for p in plan], run_id)
    finally:
        ctms_run_plan.load, ctms_todo.done, X._client, X.FILE = keep
    return out, ticked


def test_items_go_one_at_a_time_ticked_off_as_they_are_done():
    fake, filed = FakeRemote(), []
    out, ticked = _run([_note("a"), _update("b")], fake, filed=filed)
    assert out["ok"] and ticked == ["a", "b"] and out["said"].startswith("2 of 2 done in CTMS in ")
    assert [i[0] for i in fake.items] == ["ctms_item", "ctms_item"]
    assert fake.items[0][1]["item"] == {"kind": "note", "lines": ["9100001-1-1"], "set": {"note": " - Emailed DO 28/10"}}
    # the update's chain filed, the note has none - and only with CTMS done
    assert filed == ["b"] and "2 email(s) filed" in out["results"][1]["said"] and "filed" not in out["results"][0]["said"]


def test_the_work_pc_is_told_which_item_is_first_and_last():
    fake = FakeRemote()
    _run([_note("a"), _note("b", "9100003-1-1"), _note("c", "9100004-1-1")], fake)
    assert [(i[1]["first"], i[1]["last"]) for i in fake.items] == [(True, False), (False, False), (False, True)]
    # what isn't typed doesn't count: the held one here sits last, the note is both
    fake = FakeRemote()
    _run([_note("a"), {"id": "h", "kind": "update", "status": "held", "lines": [], "set": {}}], fake)
    assert [(i[1]["first"], i[1]["last"]) for i in fake.items] == [(True, True)]


def test_one_item_going_wrong_doesnt_hold_up_the_rest():
    fake = FakeRemote({"9100001-1-1": {"done": False, "clean": True, "said": "9100001-1-1: the note did not read back"}})
    out, ticked = _run([_note("a"), _note("b", "9100003-1-1")], fake)
    assert ticked == ["b"] and not out["ok"] and [r["ok"] for r in out["results"]] == [False, True]
    assert "1 of 2 done" in out["said"] and "not done: 9100001-1-1: the note did not read back" in out["said"]
    assert "stopped" not in out["said"] and "not started" not in out["said"]


def test_the_run_stops_when_ctms_couldnt_be_left_clean():
    fake = FakeRemote({"9100001-1-1": {"done": False, "clean": False, "said": "9100001-1-1: stuck. CTMS is left as it is"}})
    out, ticked = _run([_note("a"), _note("b", "9100003-1-1")], fake)
    assert ticked == [] and len(fake.items) == 1 and "stopped at: 9100001-1-1: stuck" in out["said"] and "1 not started" in out["said"]


def test_the_run_stops_when_the_work_pc_cant_be_reached():
    fake = FakeRemote({"9100001-1-1": RuntimeError("no answer")})
    out, ticked = _run([_note("a"), _note("b", "9100003-1-1")], fake)
    assert ticked == [] and len(fake.items) == 1 and "stopped at: RuntimeError: no answer" in out["said"]


def test_an_item_ctms_already_has_is_held_and_the_run_goes_on():
    fake = FakeRemote({"9100002-1-1": {"done": False, "held": True, "clean": True, "said": "9100002-1-1: CTMS has it already"}})
    filed = []
    out, ticked = _run([_update("u"), _note("n")], fake, filed=filed)
    assert ticked == ["n"] and out["results"][0]["held"] is True and out["results"][1]["ok"] is True
    assert "1 of 2 done" in out["said"] and "held, CTMS has it already: 9100002-1-1" in out["said"] and filed == []


def test_an_update_with_no_line_left_is_ticked_off_and_its_chain_filed_with_nothing_sent():
    fake, filed = FakeRemote(), []
    done = {"id": "d", "kind": "update", "orders": ["9100005"], "status": "done", "lines": [], "set": {}, "explain": ["Booked"]}
    out, ticked = _run([done], fake, filed=filed)
    assert out["ok"] and ticked == ["d"] and filed == ["d"] and fake.items == [] and out["results"][0]["said"].startswith("Booked - ticked off")


def test_the_page_is_told_how_it_is_going():
    fake = FakeRemote()
    _run([_note("a"), _update("b")], fake, run_id=77)
    paths = {p for p, _ in fake.posts}
    assert paths == {"/api/ctms/todo/progress"}
    assert fake.posts[0][1] == {"run": 77, "on": "9100001-1-1", "results": []}
    assert fake.posts[1][1]["on"] == "9100002-1-1" and [r["id"] for r in fake.posts[1][1]["results"]] == ["a"]
    assert fake.posts[-1][1]["on"] == "the email chains"
    fake = FakeRemote()
    _run([_note("a")], fake)                                            # no run to tell about
    assert fake.posts == []


def test_a_run_looks_up_what_only_ctms_knows_first_then_plans_it_again():
    want = {"id": "t9", "kind": "update", "orders": ["9100400"], "status": "ready", "set": {}, "explain": [],
            "checks": [], "lines": [], "lookup": {"ref": "9100400", "date": "05/11/2026"}}
    plain = _note("n1", "9100401-1-1")
    found = {"9100400|05/11/2026": {"lines": [{"ref": "9100400-1-1", "status": "UNSCHEDULED"}], "weight": {"9100400-1-1": 7000}}}
    typed = dict(want, lookup=None, lines=["9100400-1-1"], set={"deliver": "05/11/26 08:00-10:00", "veh": "rigid"})
    seen = []

    def load(fresh=None):
        seen.append(fresh)
        return [plain, typed] if fresh else [plain, want]
    fake = FakeRemote()
    fake.looked = ({"ok": True}, {"kind": "ctms_check", "orders": found})
    out, ticked = _run(load, fake, ids=["n1", "t9"])
    assert seen == [None, found] and fake.items[0][0] == "ctms_check"
    assert fake.items[0][1] == [{"key": "9100400|05/11/2026", "ref": "9100400", "date": "05/11/2026", "veh": True}]
    assert out["ok"] and ticked == ["n1", "t9"], out                     # looked up, then typed
    # the look-up turns up a doubt: nothing typed, and why is said
    doubtful = dict(want, status="held", lookup=None, checks=[{"field": "already", "why": "CTMS already has it"}])
    fake = FakeRemote()
    fake.looked = ({"ok": True}, {"kind": "ctms_check", "orders": found})
    out, ticked = _run(lambda fresh=None: [doubtful] if fresh else [want], fake, ids=["t9"])
    assert not out["ok"] and "CTMS already has it" in out["said"] and "stopped" not in out["said"], out
    assert [i[0] for i in fake.items] == ["ctms_check"]
    # the look-up refused: those items wait, the rest still go
    fake = FakeRemote()
    fake.looked = ({"ok": False, "detail": "the work PC was busy"}, None)
    out, ticked = _run(lambda fresh=None: [plain, want], fake, ids=["n1", "t9"])
    assert ticked == ["n1"] and "the work PC was busy" in out["said"] and "stopped" not in out["said"], out


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
