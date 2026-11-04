"""One item of the CTMS to-do on the work PC (02/11): a pretend order card, its boxes handed over the way the Access Bridge hands them,
the steps it is told to take moving it on. A note goes in only with the cursor in the right box and everything else unchanged; an
update reads what's there first; a stop backs out without saving. Made-up orders only.

    python tests/test_ctms_items.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_items as I  # noqa: E402

SI_AT = [152, 700, 1066, 66]
COST_AT = [156, 281, 117, 23]


class Templates(dict):
    def __missing__(self, name):
        return {"rgb": "", "w": 1, "h": 1}


class FakeOrder:
    """The screen: an order card over Order Summary. `lands_in` is where a click on Special Instructions really puts the cursor."""

    def __init__(self, ref="9100001-1-1", si="BPA ref", veh="", comment="", have=(), lands_in="si", save_works=True, ready="", deliver_by=""):
        self.ref, self.si, self.veh, self.comment, self.have = ref, si, veh, comment, list(have)
        self.lands_in, self.save_works = lands_in, save_works
        self.ready, self.deliver_by = ready, deliver_by
        self.cost = "NRCC"
        self.open_card = False
        self.tab = "detail"
        self.cursor = "cost"
        self.asked = ""
        self.saved = 0
        self.steps = []
        self.typed = []
        self.asks_on_save = self.asks_on_close = ""
        self.takes = {"N": "NIGHT", "SAT": "SATURDAY", "SUN": "SUNDAY"}
        self.dirty = False
        self.opens_as = None
        self.missing = set()
        self.found = True
        self.discarded = 0
        self.once_saved = None          # (ready, deliver_by) Order Summary shows after the save

    # -- what the Access Bridge hands over
    def read(self):
        els = []
        if self.open_card:
            els += [{"r": "internal frame", "nm": "Order details for 11000001", "lv": 0},
                    {"r": "text", "nm": "Customer Ref", "v": self.opens_as or self.ref, "lv": 3, "at": [594, 200, 150, 24]},
                    {"r": "text", "nm": "Detail tab page Cost Centre", "v": self.cost, "lv": 3, "at": COST_AT,
                     "st": ["focused"] if self.cursor == "cost" else None},
                    {"r": "text", "nm": "Special \nInstructions Multiline", "v": self.si, "lv": 3, "at": SI_AT,
                     "st": ["focused"] if self.cursor == "si" else None}]
            if self.tab == "loc":
                els += [{"r": "page tab", "nm": "Comments", "lv": 2, "st": ["selected"], "at": [139, 729, 91, 26]},
                        {"r": "text", "nm": "Comments tab page null", "v": "Please contact supplier", "lv": 3, "at": [66, 765, 416, 23]},
                        {"r": "text", "nm": "", "v": self.comment, "lv": 3, "at": [602, 765, 417, 23]},
                        {"r": "page tab", "nm": "Detail", "lv": 2, "at": [25, 274, 76, 23]}]
            if self.tab == "services":
                rows = self.have + [""] * (I.SERVICE_ROWS - len(self.have))
                els += [{"r": "push button", "nm": "Charge Revenue", "lv": 3}]
                els += [{"r": "text", "nm": "", "v": v, "lv": 3, "at": [100, 400, 50, 20]} for v in rows]
        if self.asked:                  # as CTMS hands it over (02/11): a window inside the one that asked
            els += [{"r": "internal frame", "nm": f"Orders {self.asked}", "lv": 1},
                    {"r": "option pane", "nm": self.asked, "lv": 2, "at": [771, 473, 357, 135]},
                    {"r": "push button", "nm": "OK ALT O", "lv": 3, "at": [938, 569, 91, 31]},
                    {"r": "push button", "nm": "Cancel ALT C", "lv": 3, "at": [1029, 569, 91, 31]},
                    {"r": "label", "nm": self.asked, "lv": 3, "at": [871, 505, 249, 60]}]
        els += [{"r": "internal frame", "nm": "Order Summary", "lv": 0},
                {"r": "text", "nm": "Enter value for : EXTERNAL_REF", "v": self.ref, "lv": 3, "at": [0, 100]},
                {"r": "text", "nm": "Enter value for : EARLY_AVAIL", "v": self.ready, "lv": 3, "at": [0, 100]},
                {"r": "text", "nm": "Enter value for : LATE_DEL", "v": self.deliver_by, "lv": 3, "at": [0, 100]},
                {"r": "internal frame", "nm": "Planning", "lv": 0}]
        return els

    def seen(self, name, box):
        if name == "box-veh-empty":
            return self.veh == ""
        if name.startswith("box-veh-"):
            return self.veh == name[len("box-veh-"):]
        if name == "os-card":
            return True
        return False

    # -- a step
    def run(self, steps):
        for s in steps:
            self.steps.append(s)
            a = s["action"]
            if a == "find":
                self.find(s)
            elif a == "click":
                self.click(s)
            elif a == "type":
                self.typed.append(s["text"])
                if self.tab == "services" and s["text"] in self.takes:
                    self.have = list(self.have) + [self.takes[s["text"]]]
                if self.open_card and self.cursor == "si" and self.tab == "detail":
                    self.si += s["text"]
                    self.dirty = True
                elif self.open_card and self.cursor == "cost" and self.tab == "detail":
                    self.cost += s["text"]
                    self.dirty = True

    def find(self, s):
        name = s["name"]
        if name in self.missing:
            raise RuntimeError(f"'{name}' is not on the screen")
        if name == "od-vehtype":
            self.open_card = True
            self.tab = "detail"
            self.cursor = "cost"
        if name == "od-discard" and not self.asked:
            raise RuntimeError("'od-discard' is not on the screen")
        if name == "schedule-ask":
            raise RuntimeError("'schedule-ask' is not on the screen")

    def click(self, s):
        px, sc = tuple(s.get("px") or ()), s.get("screen")
        if sc:
            if self.asked:
                if sc[0] < 1029:                # OK
                    if "discard" in self.asked:
                        self.discarded += 1
                        self.open_card, self.dirty = False, False
                self.asked = ""
                return
            if SI_AT[0] <= sc[0] <= SI_AT[0] + SI_AT[2] and SI_AT[1] <= sc[1] <= SI_AT[1] + SI_AT[3]:
                self.cursor = self.lands_in
            return
        if s.get("react") and px == (742, 226) and not self.found:
            raise RuntimeError("CTMS did not answer")
        if px == I.TAB_DETAIL:
            self.tab = "detail"
        elif px == I.TAB_LOC:
            self.tab = "loc"
        elif px == I.TAB_SERVICES:
            self.tab = "services"
        elif px == I.LOC_BOX_SAVE:
            self.dirty = True
        elif px == I.SERVICE_NEW or px == I.SERVICE_DELETE:
            self.dirty = True
        elif px == I.ORDER_SAVE:
            if self.save_works:
                self.saved += 1
                self.dirty = False
                self.asked = self.asks_on_save
                if self.once_saved:
                    self.ready, self.deliver_by = self.once_saved
        elif px == I.ORDER_CLOSE:
            if self.asks_on_close:
                self.asked, self.asks_on_close = self.asks_on_close, ""
            if "schedule" in self.asked:
                raise RuntimeError("CTMS did not answer")
            if self.dirty:
                self.asked = "Do you want to discard your changes?"
            else:
                self.open_card = False

    def clicks(self, *points):
        return [tuple(s["px"]) for s in self.steps if s["action"] == "click" and tuple(s.get("px") or ()) in points]


def _items(order):
    return I.Items(order.run, order.read, order.seen, Templates())


NOTE = " - Emailed DO 28/10"


def test_a_note_goes_in_at_the_end_of_special_instructions_and_is_saved():
    o = FakeOrder()
    said = _items(o).note(o.ref, NOTE)
    assert o.si == "BPA ref" + NOTE and o.saved == 1 and not o.open_card and "added" in said
    # aimed where the Access Bridge places the box, whatever the page's scroll, not at a point on a picture
    aim = [s for s in o.steps if s["action"] == "click" and s.get("screen")][0]["screen"]
    assert SI_AT[0] < aim[0] < SI_AT[0] + SI_AT[2] and SI_AT[1] < aim[1] < SI_AT[1] + SI_AT[3]
    keys = [s["key"] for s in o.steps if s["action"] == "key"]
    assert "ctrl+end" in keys


def test_a_note_already_there_is_not_typed_again():
    o = FakeOrder(si="BPA ref" + NOTE + "  ")
    said = _items(o).note(o.ref, NOTE)
    assert "there already" in said and o.typed.count(NOTE) == 0 and o.saved == 0 and not o.open_card


def test_the_note_that_landed_in_cost_centre_cant_happen_nothing_is_typed_without_the_cursor_in_the_box():
    o = FakeOrder(lands_in="cost")
    job = _items(o)
    try:
        job.refs = [o.ref]
        job.note(o.ref, NOTE)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "nothing was typed" in str(e)
    assert o.cost == "NRCC" and NOTE not in o.typed and o.saved == 0
    assert job.clear_up() is True and not o.open_card                   # closed, nothing to discard


def test_a_note_that_doesnt_read_back_or_touches_another_box_is_never_saved():
    o = FakeOrder()
    real = o.run

    def typed_elsewhere(steps):
        real(steps)
        if any(s["action"] == "type" and s["text"] == NOTE for s in steps):      # it reads as if the box took it, and the other changed too
            o.cost = "NRCC junk"
    o.run = typed_elsewhere
    job = _items(o)
    job.refs = [o.ref]
    try:
        job.note(o.ref, NOTE)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "not saved" in str(e)
    assert o.saved == 0
    assert job.clear_up() is True and o.discarded == 1 and not o.open_card


def test_a_save_that_doesnt_take_is_said_and_backed_out_of():
    o = FakeOrder(save_works=False)
    job = _items(o)
    job.refs = [o.ref]
    try:
        job.note(o.ref, NOTE)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "did not go through" in str(e)
    assert job.clear_up() is True and o.discarded == 1


def test_clearing_up_never_discards_a_card_thats_not_this_items():
    o = FakeOrder()
    o.open_card, o.dirty, o.asked = True, True, "Do you want to discard your changes?"
    job = _items(o)
    job.refs = ["9999999-1-1"]
    assert job.clear_up() is False and o.discarded == 0 and o.open_card


def test_a_run_wont_start_on_top_of_an_order_someone_has_changed():
    o = FakeOrder()
    o.open_card, o.dirty = True, True
    job = _items(o)
    try:
        job.begin()
        raise AssertionError("should have stopped")
    except I.Busy as e:
        assert "changes not saved" in str(e)
    assert o.discarded == 0 and o.open_card and not o.asked             # its Cancel pressed, the order still up


def test_an_order_with_nothing_changed_is_closed_out_of_the_way_to_start():
    o = FakeOrder()
    o.open_card = True
    _items(o).begin()
    assert not o.open_card and o.discarded == 0


def test_a_line_ctms_cant_find_stops_that_item():
    o = FakeOrder()
    o.found = False
    try:
        _items(o).note(o.ref, NOTE)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "found nothing" in str(e)
    assert NOTE not in o.typed


def test_the_wrong_card_is_never_typed_on():
    o = FakeOrder()
    o.opens_as = "9999999-1-1"
    try:
        _items(o).note(o.ref, NOTE)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "reads 9999999-1-1" in str(e)
    assert NOTE not in o.typed


SET = {"collect": "04/11/26 08:00-15:45", "deliver": "05/11/26 08:00-12:00", "comments": "05/11/26 08:00 - Sam", "veh": "rigid",
       "services": {"HIAB": True, "REAR STEER": False, "PTS": False}}


def _updated(have=("REAR STEER", "PTS", "HIAB"), **kw):
    return FakeOrder(ready="04/11/26 08:00", deliver_by="05/11/26 12:00", have=have, **kw)


def test_an_update_types_what_it_should_and_reads_the_times_back_from_order_summary():
    o = _updated()
    said = _items(o).update(o.ref, SET)
    assert o.saved == 1 and not o.open_card
    assert o.typed[:0] == [] and [t for t in o.typed if ":" in t or "/" in t][:4] == ["04/11/26", "08:00", "04/11/26", "15:45"]
    assert "05/11/26 08:00 - Sam" in o.typed
    assert "collect 04/11/26 08:00-15:45" in said and "NR_Rigid (Up to 40ft)" in said and "-2 service(s)" in said
    # bottom rows off first, rows moving up
    rows = [s["px"][1] for s in o.steps if s["action"] == "click" and s.get("px") and s["px"][0] == I.SERVICE_ROW_X]
    assert rows == [I.SERVICE_ROW_Y + 23, I.SERVICE_ROW_Y]


ONLY_NIGHT = {"services": {"NIGHT": True, "SATURDAY": True}, "anyway": True}


def test_night_and_saturday_alone_go_on_by_his_short_codes_and_nothing_else_is_typed():
    o = _updated(have=[])
    said = _items(o).update(o.ref, ONLY_NIGHT)
    assert o.saved == 1 and not o.open_card and said.endswith("+NIGHT+SATURDAY")
    assert [t for t in o.typed if t not in (1, "1", o.ref)] == ["N", "SAT"]


def test_a_night_on_it_already_is_left_with_nothing_saved():
    o = _updated(have=["NIGHT", "SATURDAY"])
    said = _items(o).update(o.ref, ONLY_NIGHT)
    assert o.saved == 0 and o.typed == [o.ref] and "already" in said


def test_a_night_that_doesnt_read_back_is_not_saved():
    o = _updated(have=[])
    o.takes = {}
    try:
        _items(o).update(o.ref, ONLY_NIGHT)
        raise AssertionError("it went on")
    except I.Stop as e:
        assert "did not read back" in str(e)
    assert o.saved == 0


SCHEDULE = "Change schedule to: 261110?"


def test_the_schedule_question_is_pressed_ok_wherever_it_shows():
    o = _updated()
    o.asks_on_save = SCHEDULE
    _items(o).update(o.ref, SET)
    assert o.saved == 1 and not o.asked and not o.open_card


def test_a_schedule_question_that_comes_up_late_is_pressed_ok_too():
    o = _updated()
    o.asks_on_close = SCHEDULE
    _items(o).update(o.ref, SET)
    assert o.saved == 1 and not o.asked and not o.open_card


def test_a_service_missing_goes_on_and_one_there_is_left():
    o = _updated(have=["PTS"])
    s = dict(SET, services={"HIAB": True, "PTS": True, "MOFFETT": False})
    _items(o).update(o.ref, s)
    assert "HIAB" in o.typed and "PTS" not in o.typed and "MOFFETT" not in o.typed


def test_the_veh_type_is_only_picked_on_an_empty_box():
    o = _updated()
    _items(o).update(o.ref, SET)
    assert any(s.get("name") == "veh-rigid-40ft" for s in o.steps)
    o = _updated(veh="rigid", comment="")
    s = dict(SET, anyway=True)
    said = _items(o).update(o.ref, s)
    assert not any(st.get("name") == "veh-rigid-40ft" for st in o.steps) and "NR_Rigid (Up to 40ft) already" in said


def test_another_vehicle_on_it_stops_before_anything_is_typed():
    for veh, words in (("artic", "NR_40ft Artic Flatbed"), ("other", "a vehicle other than")):
        o = _updated(veh=veh)
        try:
            _items(o).update(o.ref, dict(SET, anyway=True))
            raise AssertionError("should have stopped")
        except I.Stop as e:
            assert words in str(e) and "nothing typed" in str(e)
        assert o.typed.count("05/11/26 08:00 - Sam") == 0 and o.saved == 0


def test_an_update_ctms_already_has_is_held_with_nothing_typed():
    for veh, comment, words in (("artic", "", "Veh Type NR_40ft Artic Flatbed"), ("", "05/11/26 08:00 - Sam / Jo 07700900124", "deliver comment")):
        o = _updated(veh=veh, comment=comment)
        try:
            _items(o).update(o.ref, SET)
            raise AssertionError("should have been held")
        except I.Held as e:
            assert words in str(e) and "nothing typed" in str(e)
        assert o.saved == 0 and not o.open_card and "05/11/26 08:00 - Sam" not in o.typed


def test_this_very_update_already_in_counts_as_done():
    # a run stopped part way through an order's lines, then run again: the lines that went in aren't a doubt
    o = _updated(comment="05/11/26 08:00 - Sam ", veh="rigid")
    said = _items(o).update(o.ref, SET)
    assert "has this update already" in said and o.saved == 0 and o.typed.count("05/11/26 08:00 - Sam") == 0


DELIVER_ONLY = {"deliver": "18/11/26 09:00-11:00", "comments": "18/11/26 09:00 - Sam", "veh": "rigid",
                "services": {"HIAB": True, "REAR STEER": False, "PTS": False}}


def test_a_collection_left_after_the_new_delivery_moves_to_the_day_before():
    o = FakeOrder(ready="19/11/26 08:00", deliver_by="19/11/26 16:46", have=("HIAB",))   # a Wednesday's delivery
    o.once_saved = ("17/11/26 08:00", "18/11/26 11:00")
    said = _items(o).update(o.ref, DELIVER_ONLY)
    dated = [t for t in o.typed if "/" in t]
    assert dated[:2] == ["17/11/26", "17/11/26"] and dated[2] == "18/11/26"     # its dates first, and only its dates
    assert "08:00" not in o.typed
    assert "collection moved to 17/11/26 (it was 19/11/26 08:00" in said


def test_a_monday_delivery_pulled_forward_collects_friday_with_storage():
    s = dict(DELIVER_ONLY, deliver="16/11/26 09:00-11:00", comments="16/11/26 09:00 - Sam")
    o = FakeOrder(ready="17/11/26 08:00", deliver_by="17/11/26 16:00", have=("HIAB",))
    o.once_saved = ("13/11/26 08:00", "16/11/26 11:00")
    _items(o).update(o.ref, s)
    assert "13/11/26" in o.typed and "STORAGE" in o.typed and "2" in [str(t) for t in o.typed]


def test_a_collection_that_cant_move_by_the_rule_stops_with_nothing_typed():
    s = dict(DELIVER_ONLY, deliver="15/11/26 09:00-11:00")               # a Sunday's: the day before is a Saturday
    o = FakeOrder(ready="16/11/26 08:00", deliver_by="16/11/26 16:00", have=("HIAB",))
    try:
        _items(o).update(o.ref, s)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "Saturday" in str(e)
    assert o.typed == [o.ref]                                            # only its search


def test_a_morning_delivery_isnt_collected_that_same_morning():
    o = FakeOrder(ready="18/11/26 08:00", deliver_by="18/11/26 16:46", have=("HIAB",))
    o.once_saved = ("17/11/26 08:00", "18/11/26 11:00")
    said = _items(o).update(o.ref, DELIVER_ONLY)
    assert "collection moved to 17/11/26 (it was 18/11/26 08:00)" in said


def test_an_afternoon_delivery_can_be_collected_that_morning():
    s = dict(DELIVER_ONLY, deliver="18/11/26 13:00-15:00", comments="18/11/26 13:00 - Sam")
    o = FakeOrder(ready="18/11/26 08:00", deliver_by="18/11/26 16:46", have=("HIAB",))
    o.once_saved = ("18/11/26 08:00", "18/11/26 15:00")
    assert "collection moved" not in _items(o).update(o.ref, s)


def test_a_collection_already_before_the_delivery_is_left_alone():
    o = FakeOrder(ready="17/11/26 08:00", deliver_by="19/11/26 16:46", have=("HIAB",))
    o.once_saved = ("17/11/26 08:00", "18/11/26 11:00")
    said = _items(o).update(o.ref, DELIVER_ONLY)
    assert [t for t in o.typed if "/" in t][0] == "18/11/26" and "collection moved" not in said


def test_a_plan_with_the_collection_after_the_delivery_types_nothing():
    o = FakeOrder(ready="17/11/26 08:00", deliver_by="19/11/26 16:46", have=("HIAB",))
    try:
        _items(o).update(o.ref, dict(DELIVER_ONLY, collect="19/11/26 08:00-16:00"))
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "isn't before the delivery" in str(e)
    assert o.typed == [o.ref]


def test_going_later_types_the_delivery_first():
    o = _updated()
    o.ready, o.deliver_by = "01/11/26 08:00", "02/11/26 12:00"
    o.once_saved = ("04/11/26 08:00", "05/11/26 12:00")
    _items(o).update(o.ref, SET)
    assert [t for t in o.typed if "/" in t][0] == "05/11/26"


def test_the_deliver_comment_reads_on_a_monitor_left_of_and_above_the_main_one():
    els = [{"r": "internal frame", "nm": "Order details for 11000001", "lv": 0, "at": [-768, -1289, 1200, 600]},
           {"r": "page tab", "nm": "Comments", "lv": 2, "st": ["selected"], "at": [-650, -700, 91, 26]},
           {"r": "text", "nm": "Comments tab page null", "v": "Please contact supplier", "lv": 3, "at": [-720, -660, 416, 23]},
           {"r": "text", "nm": "", "v": "05/11/26 08:00 - Sam", "lv": 3, "at": [-180, -660, 417, 23]},
           {"r": "text", "nm": "", "v": "hidden", "lv": 3, "at": [-1, -1, -1, -1]}]
    assert I.deliver_comment(els) == "05/11/26 08:00 - Sam"


def test_the_same_comment_with_the_dates_not_kept_is_typed_again_not_ticked():
    o = FakeOrder(ready="17/11/26 08:00", deliver_by="19/11/26 16:46", have=("HIAB",), comment="18/11/26 09:00 - Sam", veh="rigid")
    o.once_saved = ("17/11/26 08:00", "18/11/26 11:00")
    said = _items(o).update(o.ref, DELIVER_ONLY)
    assert "has this update already" not in said and o.saved == 1 and "18/11/26" in o.typed


def test_times_that_dont_read_back_are_said():
    o = FakeOrder(ready="04/11/26 09:00", deliver_by="05/11/26 12:00", have=())
    try:
        _items(o).update(o.ref, SET)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "Ready At 04/11/26 09:00" in str(e)


def test_his_rules_stop_what_shouldnt_be_typed():
    for s, words in ((dict(SET, comments="08:00, Sam"), "No commas"),
                     (dict(SET, services={"REAR STEER": True}), "rigid never needs rear steer"),
                     (dict(SET, collect="05/11/26 07:00-15:00", services={}, storage=2), "Storage")):
        o = _updated(have=())
        try:
            _items(o).update(o.ref, s)
            raise AssertionError("should have stopped")
        except I.Stop as e:
            assert words in str(e) and "Nothing was typed" in str(e)
        assert o.saved == 0


def test_a_step_failing_part_way_keeps_nothing():
    o = _updated()
    o.missing.add("veh-rigid-40ft")
    job = _items(o)
    job.refs = [o.ref]
    try:
        job.update(o.ref, SET)
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert "part way" in str(e) and "nothing of this line was saved" in str(e)
    assert o.saved == 0


def test_a_rehearsal_types_a_line_and_throws_it_away():
    o = _updated()
    job = _items(o)
    said = job.do({"kind": "update", "lines": [o.ref, "9100001-2-1"], "set": SET}, dry=True)
    assert "rehearsed" in said and o.saved == 0 and o.discarded == 1 and not o.open_card
    assert "04/11/26" in o.typed and "05/11/26 08:00 - Sam" not in o.typed        # the comment's box saves by itself


def test_an_item_does_each_of_its_lines():
    o = _updated()
    job = _items(o)
    refs = []

    def one(ref, s):
        refs.append(ref)
        return f"{ref}: done"
    job.update = one
    said = job.do({"kind": "update", "lines": ["9100001-1-1", "9100001-2-1"], "set": SET})
    assert refs == ["9100001-1-1", "9100001-2-1"] and said == "9100001-1-1: done; 9100001-2-1: done"
    assert job.refs == ["9100001-1-1", "9100001-2-1"]


def test_a_line_that_stops_after_one_was_saved_says_which_was_saved_and_which_wasnt():
    job = _items(_updated())
    lines = ["9100001-1-1", "9100001-2-1", "9100001-3-1"]
    for stop in (I.Stop("9100001-2-1: the update stopped part way (x), so nothing of this line was saved."),
                 I.Held("9100001-2-1: CTMS has it already (Veh Type set) - nothing typed"),
                 RuntimeError("CTMS did not answer within 15s")):
        def one(ref, s):
            if ref == lines[1]:
                raise stop
            return f"{ref}: deliver 05/11/26 08:00-12:00"
        job.update = one
        try:
            job.do({"kind": "update", "lines": lines, "set": SET})
            raise AssertionError("should have stopped")
        except (I.Stop, I.Held) as e:
            assert type(e) is (type(stop) if isinstance(stop, (I.Stop, I.Held)) else I.Stop)
            assert str(e).startswith("Saved first: 9100001-1-1: deliver 05/11/26 08:00-12:00. Then 9100001-2-1 was not: "), e
            assert str(stop) in str(e) and str(e).endswith("Not tried: 9100001-3-1."), e
    # the first line stopping: as it always was, nothing saved to tell of
    def first(ref, s):
        raise I.Stop(f"{ref}: its card wouldn't open.")
    job.update = first
    try:
        job.do({"kind": "update", "lines": lines, "set": SET})
        raise AssertionError("should have stopped")
    except I.Stop as e:
        assert str(e) == "9100001-1-1: its card wouldn't open."


def test_the_parsers():
    assert I.window_parts("05/11/26 8:00-12:00") == ("05/11/26", "08:00", "05/11/26", "12:00")
    assert I.window_parts("05/11/26 22:00-06/11/26 06:00") == ("05/11/26", "22:00", "06/11/26", "06:00")
    assert I.ends("05/11/26 08:00-12:00") == ("05/11/26 08:00", "05/11/26 12:00") and I.ends(None) == ("", "")
    o = FakeOrder(ready="a", deliver_by="b")
    assert I.summary_line(o.read(), o.ref) == {"ready_at": "a", "deliver_by": "b"} and I.summary_line(o.read(), "x") is None
    assert I.question(o.read()) is None
    o.open_card, o.asked = True, "Do you want to discard your changes?"
    words, buttons = I.question(o.read())
    assert words == "Orders Do you want to discard your changes?" and sorted(buttons) == ["cancel", "ok"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
