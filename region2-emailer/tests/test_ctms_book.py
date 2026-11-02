"""The order panel's Book on the work PC (02/11): a booking run against a pretend CTMS - its well, tree and boxes handed over
the way the Access Bridge hands them, the steps it is told to take moving it on. Made-up orders only.

    python tests/test_ctms_book.py
"""
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_book as B  # noqa: E402
import ctms_orders  # noqa: E402
import ctms_rows  # noqa: E402

NOW = datetime(2026, 11, 2, 12, 0)
X0, Y0 = 443, 604
T = {k: {"rgb": "", "w": 1, "h": 1} for k in (
    "wm-refresh", "wm-apply-trip", "wm-create-trip", "sc-title", "cp-title", "cc-title", "mt-set-status", "st-accepted",
    "al-accepted", "os-split", "split-title", "split-ok", "wn-carrier", "close-ask", "od-vehtype", "os-card", "os-close",
    "os-search")}


def _cell(col, row, value):
    return {"r": "text", "nm": "", "v": value, "lv": 2, "at": [X0 + ctms_rows.OFFSETS[col], Y0 + 23 * row, 80, 23]}


class FakeCtms:
    """What the run sees. `well` is the list as CTMS would sort it; a step list moves it on."""

    def __init__(self, well, carriers=("DHL_NOC",), sched="261102", tree=(), cost="96.18", to="261113", to_stuck=False):
        self.well = list(well)
        self.to = to                    # the well's own To
        self.to_stuck = to_stuck
        self.to_list = None             # the row picked while its list is open
        self.planning_unsaved = False
        self.carriers = list(carriers)
        self.sched = sched
        self.tree = dict(tree)          # manifest: status
        self.page = 0
        self.reversed = False
        self.cost = cost
        self.up = None                  # a box up: carrier / payment / confirm
        self.list = None                # (a drop-down's rows, the box it hangs from)
        self.current = None
        self.menu = None
        self.typed = []
        self.steps = []
        self.reads = 0
        self.next_man = 1000100
        self.applied = {}
        self.trip_lines = {}
        self.selected = None
        self.saved = 0
        self.card = None
        self.summary = False
        self.frames_extra = []
        self.status_line = ""
        self.panel = None

    # -- what the Access Bridge hands over
    def upto(self):
        """The well as its To lets it show."""
        return [r for r in self.well if datetime.strptime(r["deliver"][:8], "%d/%m/%y") <= datetime.strptime(self.to, "%y%m%d")]

    def rows_shown(self):
        rows = list(reversed(self.upto())) if self.reversed else self.upto()
        return rows[self.page * 15:self.page * 15 + 15]

    def read(self):
        self.reads += 1
        els = [{"r": "internal frame", "nm": "Planning", "lv": 0, "at": [20, 130, 1648, 807]},
               {"r": "tree", "nm": "", "lv": 1, "at": [35, 228, 396, 696]},
               {"r": "text", "nm": "Sched", "v": self.sched, "lv": 1, "at": [79, 202, 80, 21]},
               {"r": "push button", "nm": "Save", "lv": 1, "at": [1307, 88, 60, 25], "st": None if self.planning_unsaved else ["disabled"]},
               {"r": "push button", "nm": "Order Filters", "lv": 1, "at": [1557, 544, 95, 23]},
               {"r": "combo box", "nm": "To", "lv": 1, "at": list(TO_BOX)},
               {"r": "list", "nm": "", "lv": 2, "at": [750, 369, 73, 182] if self.to_list else [-1, -1, -1, -1]}]
        if self.to_list:
            els += [{"r": "label", "nm": self.to_list, "lv": 3, "at": [750, 369, 73, 22], "st": ["selected"]}]
        els += [{"r": "push button", "nm": "Cust Ref", "lv": 1, "at": [X0, 560, 100, 25]},
               {"r": "push button", "nm": "Deliver From", "lv": 1, "at": [1127, 560, 66, 25]},
               {"r": "label", "nm": self.status_line or "<OSC>", "lv": 1, "at": [416, 949, 1162, 16]}]
        for n, (man, status) in enumerate(self.tree.items()):
            els.append({"r": "label", "nm": f"Level 0 05/11/26 08:00 {man}  ({status})", "lv": 2, "at": [53, 228 + 23 * n, 284, 23],
                        "st": ["selected"] if man == self.selected else None})
        for i, r in enumerate(self.rows_shown()):
            for col in ("cust_ref", "booking_ref", "deliver", "del_type", "weight", "to_reg"):
                els.append(dict(_cell(col, i, r.get(col, "")), lv=2))
        if self.panel:
            els.insert(0, {"r": "internal frame", "nm": "Planned Orders", "lv": 0, "at": [503, 513, 1006, 332]})
            els.insert(1, {"r": "text", "nm": "Cust Ref", "v": self.panel, "lv": 2, "at": [694, 558, 160, 23]})
        if self.up == "confirm":
            els.insert(0, {"r": "internal frame", "nm": f"Confirm Create Trip Carrier  {self.carrier_picked}\nRevenue         562.62\n"
                                                        f"Cost                {self.cost}\nDo you want to continue?", "lv": 0})
        if self.up in ("carrier", "payment", "confirm"):
            els.append({"r": "internal frame", "nm": B.CARRIER_FRAME, "lv": 0, "at": [437, 130, 1216, 379]})
            for i, c in enumerate(self.carriers):
                els.append({"r": "text", "nm": "", "v": c, "lv": 2, "at": [492, 235 + 23 * i, 113, 23]})
            els.append({"r": "combo box", "nm": "", "lv": 2, "at": [1088, 387, 290, 23]})
            els.append({"r": "combo box", "nm": "", "lv": 2, "at": [853, 463, 254, 29]})
            if self.list:
                for i, name in enumerate(self.list):
                    els.append({"r": "label", "nm": name, "lv": 2, "at": [853, 309 + 22 * i, 239, 22]})
        if self.card:
            els.append({"r": "internal frame", "nm": "Order details for 11000001", "lv": 0, "at": [20, 100, 1200, 600]})
            els.append({"r": "text", "nm": "Customer Ref", "v": self.card, "lv": 2, "at": [594, 200, 150, 24]})
        return els

    def seen(self, name, box):
        return {"sc-title": self.up == "carrier", "cp-title": self.up == "payment", "cc-title": self.up == "confirm"}.get(name, False)

    # -- a step
    def step(self, s):
        self.steps.append(s)
        a = s["action"]
        if a == "find":
            self.find(s)
        elif a == "click":
            self.click(s)
        elif a == "key":
            self.key(s["key"])
        elif a == "type":
            self.typed.append(s["text"])
            if self.list is not None and s["text"][:1] == "D":
                self.list = [c for c in ALT_CARRIERS if c.startswith("D")][:8]

    def run(self, steps):
        for s in steps:
            self.step(s)

    def find(self, s):
        name = s["name"]
        if name == "wm-create-trip":
            assert self.current, "a row made current first"
            self.up = "carrier"
            self.creating = self.current
        elif name == "sc-title" and self.up != "carrier":
            raise RuntimeError("'sc-title' is not on the screen")
        elif name == "cp-title" and self.up != "payment":
            raise RuntimeError("'cp-title' is not on the screen")
        elif name == "cc-title" and self.up != "confirm":
            raise RuntimeError("'cc-title' is not on the screen")
        elif name == "wm-apply-trip":
            self.trip_lines[self.selected].append(self.current)
            self.well = [r for r in self.well if r["cust_ref"] != self.current]
        elif name == "wm-refresh":
            self.page = 0
        elif name == "mt-set-status":
            self.menu = "status"

    def click(self, s):
        px = tuple(s.get("px") or ())
        sc = s.get("screen")
        if sc:
            if s.get("right"):
                return
            if list(sc) == [TO_BOX[0] + TO_BOX[2] - 10, TO_BOX[1] + TO_BOX[3] // 2]:
                self.to_list = None if self.to_list else self.to
                return
            for i, r in enumerate(self.rows_shown()):
                y = Y0 + 23 * i
                if abs(sc[1] - (y + 11)) < 12 and X0 <= sc[0] <= X0 + 100:
                    self.current = r["cust_ref"]
                    if s.get("double"):
                        self.card = r["cust_ref"]
                    return
            if self.up == "carrier" and self.list:
                for i, name in enumerate(self.list):
                    if abs(sc[1] - (309 + 22 * i + 11)) < 12 and sc[0] > 800:
                        (self.__setattr__("trailer_picked", name) if name.startswith("NR_") else self.__setattr__("alt_picked", name))
                        self.list = None
                        return
            if self.up == "carrier":
                for i, c in enumerate(self.carriers):
                    if abs(sc[1] - (235 + 23 * i + 11)) < 12:
                        self.row_picked = c
                        return
            if abs(sc[0] - (1127 + 33)) < 40 and abs(sc[1] - 572) < 14:
                self.reversed = not self.reversed
                self.page = 0
            return
        if px == B.TRAILER_BOX:
            self.list = list(TRAILERS)
        elif px == B.ALT_CARRIER_BOX:
            self.list = ["ACME", "BRAVO"]
        elif px == B.SELECT_CARRIER:
            self.carrier_picked = getattr(self, "alt_picked", None) or getattr(self, "row_picked", "")
            self.up = "payment"
        elif px == B.CREATE_TRIP:
            self.up = "confirm"
        elif px == B.CONFIRM_NO:
            self.up = "carrier"                 # the payment box shuts with it (02/11)
        elif px == B.PAYMENT_CANCEL:
            assert self.up == "payment", "a click on a box that's gone lands on Planning behind it"
            self.up = "carrier"
        elif px == B.CARRIER_EXIT:
            self.up = None
        elif px == B.CONFIRM_YES:
            self.up = None
            man = f"MAN-0{self.next_man}"
            self.next_man += 1
            self.tree[man] = "PLANNED"
            self.selected = man
            self.trip_lines[man] = [self.creating]
            self.well = [r for r in self.well if r["cust_ref"] != self.creating]
            self.status_line = f"Order 11351960 scheduled on trip: {self.sched} / {man}"
        elif px == B.ORDERS_BUTTON:
            self.panel = (self.trip_lines.get(self.selected) or [""])[0]
        elif px == B.PLANNED_CLOSE:
            self.panel = None
        elif px == B.PLANNING_SAVE:
            self.saved += 1
            self.status_line = ""
        elif px == B.FORMS_OK:
            if self.selected and self.tree.get(self.selected) == "PLANNED":
                self.tree[self.selected] = "ACCEPTED"
        elif px == B.ORDER_SAVE:
            self.typed.append("<order saved>")
        elif px == B.ORDER_CLOSE:
            self.card = None

    def key(self, k):
        if self.to_list and k in ("up", "down"):
            d = datetime.strptime(self.to_list, "%y%m%d") + timedelta(days=1 if k == "down" else -1)
            self.to_list = d.strftime("%y%m%d")
        elif self.to_list and k == "enter":
            self.to = self.to if self.to_stuck else self.to_list
            self.to_list = None
            self.page = 0
        elif k == "enter":
            self.sched = self.want_sched if getattr(self, "want_sched", None) else self.sched
        elif k == "pagedown":
            if (self.page + 1) * 15 < len(self.upto()):
                self.page += 1
        elif k == "escape":
            self.list = None


TO_BOX = (758, 523, 80, 23)
TRAILERS = ("NR_BULK_SKIP", "NR_ARTIC_FL", "NR_FLAT_RIG")
ALT_CARRIERS = ("DAWN_HAULAGE", "DELTA_DH", "DOVER FREIGHT")


def _row(ref, deliver="06/11/26 08:30", del_type="STANDARD"):
    return {"cust_ref": ref, "booking_ref": "BK" + ref, "deliver": deliver, "del_type": del_type, "weight": "1000", "to_reg": "PR2"}


def _job(ctms, dry=False, now=NOW):
    # the tree's arrow, the keys and Enter land on the schedule worked out from them
    run = ctms.run

    def steps(batch):
        ups = sum(1 for s in batch if s.get("key") == "up")
        downs = sum(1 for s in batch if s.get("key") == "down")
        if any(s.get("px") == list(B.SCHED_ARROW) for s in batch):
            d = datetime.strptime(ctms.sched, "%y%m%d")
            ctms.want_sched = (d + timedelta(days=ups - downs)).strftime("%y%m%d")
        run(batch)

    return B.Booking(steps, ctms.read, ctms.seen, T, now=now, dry=dry)


def _book(ctms, orders=("9100001",), date="06/11/2026", carrier="DHL_NOC", trailer="NR_ARTIC_FL", haulage=None, vehicles=1, dry=False):
    job = _job(ctms, dry=dry)
    job.book(list(orders), date, carrier, trailer, haulage, vehicles)
    return job


def test_a_plain_booking_goes_from_the_date_to_accepted():
    ctms = FakeCtms([_row("9000001-1-1"), _row("9100001-1-1")])
    job = _book(ctms)
    assert ctms.sched == "261106"                                  # the tree on the delivery day
    assert [t["status"] for t in job.trips] == ["ACCEPTED"] and job.trips[0]["manifest"] == "MAN-01000100"
    assert job.trips[0]["lines"] == ["9100001-1-1"] and job.trips[0]["cost"] == "96.18"
    assert ctms.tree["MAN-01000100"] == "ACCEPTED" and ctms.saved >= 2
    assert ctms.typed == []                                        # NOC: nothing typed, least of all a weight
    assert "9000001-1-1" in [r["cust_ref"] for r in ctms.well]     # the other order left alone


def test_the_row_is_shown_current_by_its_colour_before_its_menu_is_used():
    ctms = FakeCtms([_row("9100001-1-1")])
    _book(ctms)
    colours = [s for s in ctms.steps if s["action"] == "waitfor"]
    assert colours and colours[0]["color"] == B.CURRENT_ROW
    i = ctms.steps.index(colours[0])
    assert ctms.steps[i + 1].get("right") and ctms.steps[i + 2]["name"] == "wm-create-trip"


def test_a_dry_run_says_no_at_the_last_box_and_books_nothing():
    ctms = FakeCtms([_row("9100001-1-1")])
    job = _book(ctms, dry=True)
    assert ctms.tree == {} and ctms.up is None and ctms.saved == 0
    assert job.trips[0]["status"] == "rehearsed" and job.trips[0]["revenue"] == "562.62"
    assert "9100001-1-1" in [r["cust_ref"] for r in ctms.well]


def test_his_price_is_typed_for_a_tier_2_and_read_back_off_the_box():
    ctms = FakeCtms([_row("9100001-1-1")], carriers=("DHL_NOC", "ACME"), cost="450.00")
    job = _book(ctms, carrier="ACME", haulage=450)
    assert ctms.typed == ["450"] and job.trips[0]["cost"] == "450.00"


def test_a_box_under_the_price_typed_stops_with_nothing_booked():
    ctms = FakeCtms([_row("9100001-1-1")], carriers=("ACME",), cost="100.00")
    try:
        _book(ctms, carrier="ACME", haulage=450)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "under the 450" in str(e)
    assert ctms.tree == {} and ctms.up == "confirm"


def test_a_tier_1_with_no_matrix_price_stops_rather_than_booking_it_at_nothing():
    ctms = FakeCtms([_row("9100001-1-1")], carriers=("ACME",), cost="0.00")
    try:
        _book(ctms, carrier="ACME")
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "no matrix price" in str(e)
    assert ctms.tree == {}


def test_a_carrier_off_the_lane_comes_from_the_alternative_list_by_its_first_letter():
    ctms = FakeCtms([_row("9100001-1-1")], cost="478.30")
    job = _book(ctms, carrier="DELTA_DH")
    assert "D" in ctms.typed and job.trips[0]["carrier"] == "DELTA_DH"


def test_a_carrier_nobody_has_stops_with_the_list_closed():
    ctms = FakeCtms([_row("9100001-1-1")])
    try:
        _book(ctms, carrier="NOBODY_DH")
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "NOBODY_DH isn't on CTMS's carrier list" in str(e)
    assert ctms.list is None and ctms.tree == {}


def test_an_order_past_the_first_page_is_found_with_the_deliver_column_pressed_and_put_back_after():
    well = [_row(f"90000{i:02d}-1-1", "05/11/26 08:00") for i in range(40)] + [_row("9100001-1-1")]
    ctms = FakeCtms(well)
    job = _book(ctms)
    assert job.trips[0]["status"] == "ACCEPTED"
    assert job.flipped is True and ctms.reversed is True
    job.tidy()
    assert job.flipped is False and ctms.reversed is False


def test_the_wells_own_to_goes_on_the_delivery_day_so_the_order_is_on_top_and_goes_back_after():
    later = [_row(f"90000{i:02d}-1-1", "12/11/26 08:00") for i in range(200)]     # far past six pages from the 13/11 end
    ctms = FakeCtms([_row("9100001-1-1")] + later)
    job = _book(ctms, dry=True)
    assert ctms.to == "261106" and ctms.sched == "261106"
    assert job.trips and job.to_was == "261113"
    job.tidy()
    assert ctms.to == "261113" and ctms.to_list is None and ctms.reversed is False


def test_a_to_already_on_the_day_has_its_list_shut_and_nothing_pressed():
    ctms = FakeCtms([_row("9100001-1-1")], sched="261106", to="261106")
    job = _book(ctms)
    assert ctms.to == "261106" and ctms.to_list is None and job.trips[0]["status"] == "ACCEPTED"
    assert not any(s.get("key") in ("up", "down") for s in ctms.steps)


def test_a_to_that_wont_move_stops_before_anything_is_booked():
    ctms = FakeCtms([_row("9100001-1-1")], to_stuck=True)
    try:
        _book(ctms)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "wouldn't go to 261106" in str(e) and "Nothing was booked" in str(e)
    assert ctms.tree == {}


def test_a_trip_not_saved_keeps_the_well_as_it_is():
    ctms = FakeCtms([_row("9100001-1-1")])
    job = _job(ctms)
    job.look()
    job.set_day("261106")
    ctms.planning_unsaved = True
    job.tidy()
    assert ctms.to == "261106"


def test_another_days_lines_of_the_order_are_left_for_their_own_booking():
    ctms = FakeCtms([_row("9100001-1-1"), _row("9100001-2-1", "07/11/26 08:30")])
    job = _book(ctms)
    assert job.trips[0]["lines"] == ["9100001-1-1"]
    assert [r["cust_ref"] for r in ctms.well] == ["9100001-2-1"]


def test_ctms_on_another_day_stops_and_says_which():
    ctms = FakeCtms([_row("9100001-1-1", "09/11/26 08:30")])
    try:
        _book(ctms)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "9100001-1-1 on 09/11/2026" in str(e) and "Nothing was booked" in str(e)
    assert ctms.tree == {}


def test_an_order_the_well_hasnt_got_says_what_it_might_be():
    ctms = FakeCtms([_row("9000001-1-1")])
    try:
        _book(ctms)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "isn't in the order well" in str(e) and "filters" in str(e)


def test_several_lines_go_on_one_manifest_by_apply_to_trip():
    ctms = FakeCtms([_row("9100001-1-1"), _row("9100001-2-1"), _row("9100001-3-1")])
    job = _book(ctms)
    assert len(job.trips) == 1 and job.trips[0]["lines"] == ["9100001-1-1", "9100001-2-1", "9100001-3-1"]
    assert ctms.trip_lines["MAN-01000100"] == ["9100001-1-1", "9100001-2-1", "9100001-3-1"]


def test_two_order_numbers_of_one_delivery_share_a_manifest():
    ctms = FakeCtms([_row("9100001-1-1"), _row("9100002-1-1")])
    job = _book(ctms, orders=("9100001", "9100002"))
    assert len(job.trips) == 1 and job.trips[0]["lines"] == ["9100001-1-1", "9100002-1-1"]


def test_lines_already_split_get_a_vehicle_each():
    ctms = FakeCtms([_row("AH5/11/YO_S1"), _row("AH5/11/YO_S2")])
    job = _book(ctms, orders=("AH5/11/YO",), vehicles=2)
    assert [t["lines"] for t in job.trips] == [["AH5/11/YO_S1"], ["AH5/11/YO_S2"]]
    assert all(t["status"] == "ACCEPTED" for t in job.trips) and len(ctms.tree) == 2


def test_lines_that_dont_share_out_over_the_vehicles_stop_rather_than_guess():
    ctms = FakeCtms([_row("9100001-1-1"), _row("9100001-2-1"), _row("9100001-3-1")])
    try:
        _book(ctms, vehicles=2)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "can't split that yet" in str(e)
    assert ctms.tree == {}


def test_a_dry_run_of_a_split_rehearses_a_vehicle_and_splits_nothing():
    ctms = FakeCtms([_row("9100001-1-1")])
    job = _book(ctms, vehicles=2, dry=True)
    assert "would be split into 2" in job.said[0] and not any(s.get("name") == "os-split" for s in ctms.steps)
    assert job.trips[0]["status"] == "rehearsed"


def test_the_delivery_type_only_ever_goes_up_by_his_bands():
    now = datetime(2026, 11, 2, 12, 0)
    assert B.wanted_type("STANDARD", "03/11/26 08:00", now) == "EMERGENCY"     # 20 hours
    assert B.wanted_type("STANDARD", "04/11/26 08:00", now) == "NEXT DAY"      # 44 hours
    assert B.wanted_type("STANDARD", "06/11/26 08:00", now) is None            # 92 hours
    assert B.wanted_type("NEXT DAY", "06/11/26 08:00", now) is None            # as it came, never brought down
    assert B.wanted_type("EMERGE", "03/11/26 08:00", now) is None              # the well cuts it short
    assert B.wanted_type("NEXT DAY", "03/11/26 08:00", now) == "EMERGENCY"
    assert B.wanted_type("STANDARD", "", now) is None


def test_an_urgent_order_is_put_up_on_its_own_card_before_the_trip():
    ctms = FakeCtms([_row("9100001-1-1", "03/11/26 08:00")])
    job = _book(ctms, date="03/11/2026")
    assert "EMERGENCY%" in ctms.typed and ctms.typed.index("EMERGENCY%") < ctms.typed.index("<order saved>")
    assert job.said == ["9100001-1-1 put up to EMERGENCY"] and job.trips[0]["status"] == "ACCEPTED"
    assert ctms.card is None


def test_a_card_that_isnt_the_lines_is_closed_unchanged():
    ctms = FakeCtms([_row("9100001-1-1", "03/11/26 08:00")])
    real = ctms.click

    def wrong_card(s):
        real(s)
        if s.get("double"):
            ctms.card = "9999999-1-1"
    ctms.click = wrong_card
    try:
        _book(ctms, date="03/11/2026")
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "opened 9999999-1-1 for 9100001-1-1" in str(e)
    assert ctms.card is None and "EMERGENCY%" not in ctms.typed and ctms.tree == {}


def test_a_new_manifest_comes_from_the_status_line_or_the_one_new_on_the_tree():
    label = lambda nm, st=None: {"r": "label", "nm": nm, "st": st, "at": [53, 300, 284, 23]}
    assert B.new_manifest([label("Order 1 scheduled on trip: 261105 / MAN-01000036")], {}) == "MAN-01000036"
    tree = [label("Level 0 05/11/26 08:00 MAN-01  (ACCEPTED)"), label("Level 0 05/11/26 08:00 MAN-02  (PLANNED)")]
    assert B.new_manifest(tree, {"MAN-01": {}}) == "MAN-02"
    tree.append(label("Level 0 05/11/26 09:00 MAN-03  (PLANNED)", ["selected"]))
    assert B.new_manifest(tree, {"MAN-01": {}}) == "MAN-03"              # a colleague's turned up: the selected one
    assert B.new_manifest(tree[:1], {"MAN-01": {}}) is None


def test_planned_orders_are_read_off_their_own_window_not_the_well_which_can_still_list_the_line():
    els = [{"r": "internal frame", "nm": "Planned Orders", "lv": 0},
           {"r": "text", "nm": "Cust Ref", "v": "9100002-1-1", "lv": 2, "at": [694, 558, 160, 23]},
           {"r": "text", "nm": "Cust Ref", "v": "", "lv": 2, "at": [694, 581, 160, 23]},
           {"r": "internal frame", "nm": "Planning", "lv": 0},
           {"r": "text", "nm": "", "v": "9100001-1-1", "lv": 2, "at": [443, 583, 100, 23]}]
    assert B.planned_refs(els) == {"9100002-1-1"}


def test_the_confirm_box_comes_as_a_window_with_its_words_in_its_name():
    els = [{"r": "internal frame", "nm": "Confirm Create Trip Carrier  DHL_NOC\nRevenue         1,746.84\nCost                155.58\n"
                                         "Do you want to continue?", "lv": 0}, {"r": "internal frame", "nm": "Planning", "lv": 0}]
    assert B.confirm_box(els) == {"carrier": "DHL_NOC", "revenue": "1746.84", "cost": "155.58"}
    assert B.confirm_box(els[1:]) is None


def test_a_list_row_only_counts_on_the_screen():
    els = [{"r": "internal frame", "nm": B.CARRIER_FRAME, "lv": 0},
           {"r": "label", "nm": "TRANSOL", "lv": 2, "at": [-1, -1, -1, -1]},
           {"r": "label", "nm": "NR_ARTIC_FL", "lv": 2, "at": [1088, 233, 275, 22]}]
    assert B.list_row(els, "TRANSOL") is None
    assert B.list_row(els, "nr_artic_fl")["at"][1] == 233


def test_a_night_delivery_sits_on_the_next_days_schedule():
    assert B.sched_for_delivery("06/11/26 08:30") == "261106"
    assert B.sched_for_delivery("07/11/26 23:30") == "261108"
    assert B.sched_for_delivery("30/11/26 20:00") == "261201"
    assert B.sched_for_delivery("") is None
    assert B.sched_for_day("05/11/2026") == "261105"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
