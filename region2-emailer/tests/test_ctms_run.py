"""The CTMS to-do run against a stand-in CTMS: a note typed only when it isn't there and kept only when it reads back,
services worked out from what the order has, the times read back after the save - and the first thing not as
expected stops the run with nothing after it touched. Made-up orders only.

    python tests/test_ctms_run.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_run as X  # noqa: E402


def _card(si="", services=()):
    els = [{"r": "internal frame", "nm": "Order details for 11300001", "lv": 1},
           {"r": "text", "nm": "Special \nInstructions Multiline", "v": si, "lv": 3},
           {"r": "push button", "nm": "Charge Revenue", "lv": 3}]
    rows = list(services) + [""] * (X.SERVICE_ROWS - len(services))
    els += [{"r": "text", "nm": "", "v": v, "lv": 3} for v in rows]
    els += [{"r": "text", "nm": "", "v": "USE OF HIAB", "lv": 3}]          # the names column - never read as ids
    return els


def _loc(comment=""):
    """The order card on LOC Detail > Comments: the collect side's box, then the deliver side's to its right."""
    return [{"r": "internal frame", "nm": "Order details for 11300001", "lv": 1},
            {"r": "page tab", "nm": "Contact", "lv": 2, "at": [51, 729, 91, 26]},
            {"r": "page tab", "nm": "Comments", "lv": 2, "st": ["selected"], "at": [139, 729, 91, 26]},
            {"r": "text", "nm": "Comments tab page null", "v": "Please contact supplier", "lv": 3,
             "at": [66, 765, 416, 23]},
            {"r": "text", "nm": "", "v": comment, "lv": 3, "at": [602, 765, 417, 23]},
            {"r": "push button", "nm": "Edit", "lv": 3, "at": [492, 755, 100, 30]},
            {"r": "page tab", "nm": "Detail", "lv": 2, "at": [25, 274, 76, 23]}]


def _summary(ref, ready, deliver):
    return [{"r": "internal frame", "nm": "Order Summary", "lv": 1},
            {"r": "text", "nm": "Enter value for : EXTERNAL_REF", "v": ref, "lv": 3, "at": [0, 100]},
            {"r": "text", "nm": "Enter value for : EARLY_AVAIL", "v": ready, "lv": 3, "at": [0, 100]},
            {"r": "text", "nm": "Enter value for : LATE_DEL", "v": deliver, "lv": 3, "at": [0, 100]}]


class FakeCTMS:
    """Just enough of ctms_remote: each call recorded, each read answered from `reads`; `veh` is what the order's
    Veh Type box shows - "rigid", "artic", "" (empty) or "other"."""
    CARD_BOX = "430,50,830,270"

    def __init__(self, reads, veh=""):
        self.reads, self.calls, self.veh = list(reads), [], veh
        self.RUN_STEPS = {"order-close": lambda a: [("click", {})],
                          "order-note": lambda a: [("type", {"text": a.note})]}

    def _on_screen(self, name, box, timeout=0.0):
        return {"box-veh-rigid": self.veh == "rigid", "box-veh-artic": self.veh == "artic",
                "box-veh-empty": self.veh == ""}.get(name, False)

    def order_update_items(self, a, card_open=False):
        return [("update", {k: v for k, v in vars(a).items() if v})]

    def parse_steps(self, items):
        return items

    def send_batch(self, name, batch, refs=None):
        self.calls.append((name, batch))
        return 0

    def run_steps(self, name, steps):
        self.calls.append((name, steps))
        return 0

    def order_save_close(self):
        self.calls.append(("save-close", None))
        return 0

    def ask(self, action, wait_total=90, **args):
        return {"ok": True}, {"kind": "fields", "elements": self.reads.pop(0)}


def test_the_parsers_read_only_the_order_card_and_the_summary_row():
    assert X.special_instructions(_card("BPA - Emailed DO 28/10")) == "BPA - Emailed DO 28/10"
    assert X.special_instructions([{"r": "internal frame", "nm": "Planning", "lv": 1}]) is None
    assert X.services(_card(services=["HIAB", "REAR STEER"])) == ["HIAB", "REAR STEER"]
    assert X.summary_line(_summary("9100090-1-1", "04/11/26 08:00", "05/11/26 12:00"), "9100090-1-1") == \
        {"ready_at": "04/11/26 08:00", "deliver_by": "05/11/26 12:00"}
    assert X.summary_line(_summary("9100090-1-1", "x", "y"), "9100091-1-1") is None


def test_a_note_is_typed_only_when_missing_and_counts_only_once_it_reads_back():
    note = {"lines": ["9100092-1-1"], "set": {"note": " - Emailed DO 28/10"}}
    R = FakeCTMS([_card("BPA ref - Emailed DO 28/10")])
    assert "there already" in X.run_note(R, note)
    assert not any(n == "order-note" for n, _ in R.calls)               # nothing typed
    R = FakeCTMS([_card("BPA ref"), _card("BPA ref - Emailed DO 28/10"), _card("BPA ref - Emailed DO 28/10")])
    assert "added" in X.run_note(R, note) and ("save-close", None) in R.calls
    R = FakeCTMS([_card("BPA ref"), _card("BPA ref")])                   # typed, but it doesn't read back
    try:
        X.run_note(R, note)
        assert False, "should have stopped"
    except X.Failed as e:
        assert "not saved" in str(e)
    assert ("save-close", None) not in R.calls                          # never saved


def test_an_update_takes_off_and_puts_on_only_what_the_order_lacks_and_reads_the_times_back():
    p = {"lines": ["9100093-1-1"], "set": {
        "deliver": "05/11/26 08:00-12:00", "collect": "04/11/26 08:00-15:45", "comments": "05/11/26 08:00 - Sam",
        "veh": "rigid", "services": {"HIAB": True, "REAR STEER": False, "PTS": False}}}
    R = FakeCTMS([_loc(""), _card(services=["REAR STEER", "PTS", "HIAB"]),
                  _summary("9100093-1-1", "04/11/26 08:00", "05/11/26 12:00")])
    said = X.run_update(R, p)
    upd = [b for n, b in R.calls if n == "order-update" and b[0][1].get("deliver")][0][0][1]
    assert upd["remove_service_row"] == [1, 2] and "add_service" not in upd        # HIAB there already
    assert upd["veh"] == "rigid" and upd["comments"] == "05/11/26 08:00 - Sam"          # an empty box: picked
    assert "9100093-1-1" in said
    # the times CTMS shows after the save are not what was typed: stop
    R = FakeCTMS([_loc(""), _card(services=[]), _summary("9100093-1-1", "04/11/26 09:00", "05/11/26 12:00")])
    try:
        X.run_update(R, p)
        assert False, "should have stopped"
    except X.Failed as e:
        assert "Ready At 04/11/26 09:00" in str(e)


def test_a_run_stops_at_the_first_failure_and_ticks_off_only_what_was_done():
    import ctms_run_plan
    import ctms_todo
    ticked, filed, keep = [], [], (ctms_run_plan.load, ctms_todo.done, X._client, X.FILE)
    plan = [{"id": "a", "kind": "update", "status": "done", "lines": [], "set": {}},
            {"id": "b", "kind": "note", "status": "ready", "lines": ["9100094-1-1"],
             "set": {"note": " - Emailed DO 28/10"}},
            {"id": "c", "kind": "note", "status": "ready", "lines": ["9100095-1-1"],
             "set": {"note": " - Emailed DO 28/10"}},
            {"id": "d", "kind": "update", "status": "held", "lines": [], "set": {}}]
    try:
        ctms_run_plan.load = lambda: plan
        ctms_todo.done = lambda i: ticked.append(i)
        X._client = lambda: FakeCTMS([_card("x"), _card("x")])           # b: typed, never reads back
        X.FILE = lambda p: filed.append(p["id"]) or "; 2 email(s) filed to Region 2 > Completed"
        out = X.run(["a", "b", "c", "d"])
        assert ticked == ["a"] and out["ok"] is False
        assert [r["id"] for r in out["results"]] == ["a", "b"] and "2 not started" in out["said"], out
        # the update CTMS shows done files its email chain; a note, or an item that failed, files nothing
        assert filed == ["a"] and "2 email(s) filed" in out["results"][0]["said"]
    finally:
        ctms_run_plan.load, ctms_todo.done, X._client, X.FILE = keep


def test_an_update_ctms_already_has_is_held_untouched_and_the_run_goes_on():
    p = {"lines": ["9100098-1-1"], "set": {
        "deliver": "05/11/26 08:00-12:00", "comments": "05/11/26 08:00 - Sam", "veh": "artic",
        "services": {"HIAB": True, "MOFFETT": False, "REAR STEER": True, "PTS": False}}}
    # a Veh Type on it, or a deliver comment typed: held with what CTMS has, nothing typed, nothing saved (02/11)
    for veh, comment, words in (("artic", "", "Veh Type NR_40ft Artic Flatbed"),
                                ("", "05/11/26 08:00 - Sam / Jo 07700900124", "deliver comment '05/11/26 08:00 - Sam / Jo")):
        R = FakeCTMS([_loc(comment)], veh=veh)
        try:
            X.run_update(R, p)
            assert False, "should have been held"
        except X.Held as e:
            assert words in str(e) and "nothing typed" in str(e), str(e)
        assert not any(n == "order-update" and b[0][1].get("deliver") for n, b in R.calls if b)
        assert ("save-close", None) not in R.calls
    # in a run, a held item stays on the list and the next one still runs
    import ctms_run_plan
    import ctms_todo
    ticked, keep = [], (ctms_run_plan.load, ctms_todo.done, X._client, X.FILE)
    plan = [{"id": "u", "kind": "update", "status": "ready", "lines": ["9100098-1-1"], "set": p["set"]},
            {"id": "n", "kind": "note", "status": "ready", "lines": ["9100099-1-1"],
             "set": {"note": " - Emailed DO 28/10"}}]
    try:
        ctms_run_plan.load = lambda: plan
        ctms_todo.done = lambda i: ticked.append(i)
        X._client = lambda: FakeCTMS([_loc(""), _card("x"), _card("x - Emailed DO 28/10"),
                                      _card("x - Emailed DO 28/10")], veh="artic")
        X.FILE = lambda p: ""
        out = X.run(["u", "n"])
        assert ticked == ["n"] and out["results"][0]["held"] is True and out["results"][1]["ok"] is True, out
        assert out["said"].startswith("1 of 2 done in CTMS; held, CTMS has it already: 9100098-1-1"), out["said"]
    finally:
        ctms_run_plan.load, ctms_todo.done, X._client, X.FILE = keep


def test_a_vehicle_already_there_is_never_picked_again_and_another_one_stops_it_before_any_typing():
    # his "Type it in anyway" on an order CTMS has a Veh Type on: the old care for the vehicle still holds
    p = {"lines": ["9100096-1-1"], "set": {
        "deliver": "05/11/26 08:00-12:00", "comments": "05/11/26 08:00 - Sam", "veh": "rigid", "anyway": True,
        "services": {"HIAB": True, "MOFFETT": False, "REAR STEER": False, "PTS": False}}}
    # already the 40ft rigid: everything else typed, the vehicle list never opened
    R = FakeCTMS([_card(services=["HIAB"]), _summary("9100096-1-1", "", "05/11/26 12:00")], veh="rigid")
    said = X.run_update(R, p)
    upd = [b for n, b in R.calls if n == "order-update" and b[0][1].get("deliver")][0][0][1]
    assert "veh" not in upd and "NR_Rigid (Up to 40ft) already" in said, said
    # set to the artic, or to a vehicle it doesn't know: left as it is, nothing typed, nothing saved
    for shows, words in (("artic", "NR_40ft Artic Flatbed"), ("other", "a vehicle other than")):
        R = FakeCTMS([], veh=shows)
        try:
            X.run_update(R, p)
            assert False, "should have stopped"
        except X.Failed as e:
            assert words in str(e) and "nothing typed" in str(e), str(e)
        assert not any(n == "order-update" and b[0][1].get("deliver") for n, b in R.calls if b)
        assert ("save-close", None) not in R.calls


def test_a_moffett_goes_in_services_like_a_hiab():
    p = {"lines": ["9100097-1-1"], "set": {
        "deliver": "05/11/26 08:00-12:00", "veh": "artic",
        "services": {"HIAB": False, "MOFFETT": True, "REAR STEER": False, "PTS": False}}}
    R = FakeCTMS([_loc(""), _card(services=["HIAB"]), _summary("9100097-1-1", "", "05/11/26 12:00")])
    X.run_update(R, p)
    upd = [b for n, b in R.calls if n == "order-update" and b[0][1].get("deliver")][0][0][1]
    assert upd["add_service"] == ["MOFFETT"] and upd["remove_service_row"] == [1]   # HIAB off, MOFFETT on
    assert upd["veh"] == "artic"


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
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
