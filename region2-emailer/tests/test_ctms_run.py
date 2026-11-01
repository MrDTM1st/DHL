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


def _summary(ref, ready, deliver):
    return [{"r": "internal frame", "nm": "Order Summary", "lv": 1},
            {"r": "text", "nm": "Enter value for : EXTERNAL_REF", "v": ref, "lv": 3, "at": [0, 100]},
            {"r": "text", "nm": "Enter value for : EARLY_AVAIL", "v": ready, "lv": 3, "at": [0, 100]},
            {"r": "text", "nm": "Enter value for : LATE_DEL", "v": deliver, "lv": 3, "at": [0, 100]}]


class FakeCTMS:
    """Just enough of ctms_remote: each call recorded, each read answered from `reads`."""
    CARD_BOX = "430,50,830,270"

    def __init__(self, reads):
        self.reads, self.calls = list(reads), []
        self.RUN_STEPS = {"order-close": lambda a: [("click", {})],
                          "order-note": lambda a: [("type", {"text": a.note})]}

    def _on_screen(self, name, box, timeout=0.0):
        return False

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
    R = FakeCTMS([_card(services=["REAR STEER", "PTS", "HIAB"]),
                  _summary("9100093-1-1", "04/11/26 08:00", "05/11/26 12:00")])
    said = X.run_update(R, p)
    upd = [b for n, b in R.calls if n == "order-update" and b[0][1].get("deliver")][0][0][1]
    assert upd["remove_service_row"] == [1, 2] and "add_service" not in upd        # HIAB there already
    assert upd["veh"] == "rigid" and upd["comments"] == "05/11/26 08:00 - Sam"
    assert "9100093-1-1" in said
    # the times CTMS shows after the save are not what was typed: stop
    R = FakeCTMS([_card(services=[]), _summary("9100093-1-1", "04/11/26 09:00", "05/11/26 12:00")])
    try:
        X.run_update(R, p)
        assert False, "should have stopped"
    except X.Failed as e:
        assert "Ready At 04/11/26 09:00" in str(e)


def test_a_run_stops_at_the_first_failure_and_ticks_off_only_what_was_done():
    import ctms_run_plan
    import ctms_todo
    ticked, keep = [], (ctms_run_plan.load, ctms_todo.done, X._client)
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
        out = X.run(["a", "b", "c", "d"])
        assert ticked == ["a"] and out["ok"] is False
        assert [r["id"] for r in out["results"]] == ["a", "b"] and "2 not started" in out["said"], out
    finally:
        ctms_run_plan.load, ctms_todo.done, X._client = keep


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
