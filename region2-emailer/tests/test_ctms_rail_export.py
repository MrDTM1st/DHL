"""The rail plan's one-click CTMS export against a stand-in Export card that draws its schedule lists with CTMS's own
digit pictures, where CTMS draws them (the 31/10 pictures): the week is set by reading the lists back, never by
counting keys; nothing is exported until both boxes read as the week; a stop before Export leaves CTMS alone, one
after it closes the export's tab. Made-up file names only.

    python tests/test_ctms_rail_export.py
"""
import base64
import io
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from PIL import Image  # noqa: E402

import ctms_digits as D  # noqa: E402
import ctms_rail_export as X  # noqa: E402

SUNDAY = date(2026, 11, 1)
LAND = date(2026, 5, 15)            # where the thumb's two drags landed the lists (31/10)
JUNK = date(2047, 12, 10)           # the far end of a list: junk schedules decades out


def draw(img, x, y, code):
    cw, ch, pitch, by_cell = D.load()
    cells = {d: raw for raw, d in by_cell.items()}
    for k, c in enumerate(code):
        img.paste(Image.frombytes("RGB", (cw, ch), cells[c]), (x + pitch * k, y))


def blue(img, x, y):
    """A chosen row, its code at x,y: white on blue - nothing the digit pictures match."""
    for yy in range(max(0, y - 7), min(img.height, y + 15)):
        for xx in range(max(0, x - 1), img.width):
            img.putpixel((xx, yy), D.HIGHLIGHT)


class Stop(Exception):
    pass


class FakeCTMS:
    """Just enough of ctms_remote and the Export card. A schedule list opens up from an empty box (at its far end)
    and down from a box on a day (that day chosen, at its top); keys move the chosen day, the view following it."""
    UP_Y = {"start": 341, "end": 374}
    DOWN_Y = {"start": 495, "end": 528}

    def __init__(self, card=False, name=False, start=None, end=None, cc=False, pt=False, land=LAND, drop_every=0,
                 enter_off=0, pt_ups_needed=X.PT_UPS, stale=False):
        self.card, self.name, self.cc, self.pt = card, name, cc, pt
        self.box = {"start": start, "end": end}
        self.open, self.up, self.first, self.sel = None, False, None, None
        self.land, self.drop_every, self.enter_off, self.stale = land, drop_every, enter_off, stale
        self.pt_ups, self.pt_ups_needed, self.keys = 0, pt_ups_needed, 0
        self.asking, self.exported, self.since, self.tabs_closed = False, False, None, 0
        self.log, self.sent = [], []

    # ---- the client's calls ----
    def parse_steps(self, items):
        return list(items)

    def trace(self, *a):
        pass

    def save_state(self, p):
        pass

    def _on_screen(self, name, box, timeout=0.0):
        return self.see(name, box)

    def ask(self, action, wait_total=90, **args):
        self.log.append(action)
        if action == "see":
            return {"ok": True}, {"kind": "window"}
        if action == "export_close":
            self.tabs_closed += 1
            return {"ok": True, "detail": "Closed 1 export tab; CTMS's tab is the one showing again."}, None
        if action == "export_fetch":
            self.since = args.get("since")
            if not self.exported:
                return {"ok": False, "detail": "No CTMS export is open in an Edge tab - press Export in CTMS first."}, None
            made = datetime.now() - (timedelta(days=1) if self.stale else timedelta(seconds=3))
            name = f"short_rail_rep_{made:%Y-%m-%d_%H%M%S}.csv"
            return {"ok": True, "detail": f"Took {name}"}, {"kind": "export", "name": name, "rows": 57}
        assert action == "steps", action
        snaps = []
        self.sent += args["steps"]
        for item in args["steps"]:
            try:
                self.step(item, snaps)
            except Stop as e:
                return {"ok": False, "detail": f"Stopped at {item}: {e}"}, {"kind": "window", "snaps": snaps}
        return {"ok": True, "detail": "Ran"}, {"kind": "window", "snaps": snaps}

    # ---- what CTMS shows ----
    def see(self, name, box):
        if name == X.CARD:
            return self.card
        if name == X.SRR:
            return self.open == "name" if box == X.NAME_LIST else (self.name and self.open != "name")
        if name == X.SR:
            if box == X.PT_LIST:
                return self.open == "pt" and self.pt_ups_needed <= self.pt_ups < self.pt_ups_needed + 8
            return self.pt and self.open is None
        if name == X.ASK:
            return self.asking
        raise AssertionError(f"no such template {name}")

    def render(self, box):
        x0, y0, x1, y1 = (int(float(v)) for v in box.split(","))
        img = Image.new("RGB", (x1 - x0, y1 - y0), (255, 255, 255))
        cover = None
        if self.open in ("start", "end"):
            ys = (self.UP_Y if self.up else self.DOWN_Y)[self.open]
            cover = (ys - 7, ys + 22 * 8 - 7)
            for k in range(8):
                y, day = ys + 22 * k, self.first + timedelta(days=k)
                if y - 7 >= y0 and y + 15 <= y1:
                    (blue(img, X.CODE_X - x0, y - y0) if day == self.sel
                     else draw(img, X.CODE_X - x0, y - y0, D.code_of(day)))
        for key in ("start", "end"):                     # a box shows where no open list covers it
            day, y = self.box[key], X.BOXES[key]["code_y"]
            if day and y0 <= y and y + 14 <= y1 and not (cover and cover[0] <= y < cover[1]) and self.open != "pt":
                draw(img, X.CODE_X - x0, y - y0, D.code_of(day))
        if box == X.CC_BOX and self.cc and self.open is None:
            draw(img, 2, 0, "4242")                         # its one entry - text, whatever it says
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # ---- what a step does ----
    def step(self, item, snaps):
        verb, _, rest = item.partition(" ")
        words = rest.split()
        if verb in ("anchor", "settle"):
            return
        if verb == "snap":
            snaps.append({"name": words[0], "img": self.render(words[1])})
        elif verb == "find":
            box = next(w.split("=", 1)[1] for w in words if w.startswith("box="))
            if not self.see(words[0], box):
                raise Stop(f"'{words[0]}' is not on the screen where it should be")
            if "click" in words:
                if words[0] == X.SRR:
                    self.name, self.open = True, None
                elif words[0] == X.SR:
                    self.pt, self.open = True, None
        elif verb == "click":
            self.click(*(int(float(v)) for v in words[0].split(",")))
        elif verb == "drag":
            self.drag(int(float(words[1].split(",")[1])))
        elif verb == "key":
            self.key(words[0])
        else:
            raise AssertionError(item)

    def click(self, x, y):
        self.log.append(f"click {x},{y}")
        arrows = {tuple(int(v) for v in b["arrow"].split(",")): k for k, b in X.BOXES.items()}
        if (x, y) == (1000, 37):
            self.open = None                             # a click away shuts an open list
        elif (x, y) == (362, 187):
            self.card = True
        elif (x, y) == (649, 286) and self.card:
            self.open = "name"
        elif (x, y) in arrows:
            key = arrows[(x, y)]
            if self.open == key:
                self.open = None
                return
            self.open, self.up = key, self.box[key] is None
            self.first = JUNK if self.up else self.box[key]
            self.sel = None if self.up else self.box[key]
        elif x == 470 and self.open in ("start", "end") and self.up:
            k = (y - 5 - self.UP_Y[self.open]) // 22
            self.box[self.open], self.open = self.first + timedelta(days=k), None
        elif (x, y) == (730, 565):
            self.open = "cc"
        elif (x, y) == (398, 544) and self.open == "cc":
            self.cc, self.open = True, None
        elif (x, y) == (730, 598):
            self.open, self.pt_ups = "pt", 0
        elif (x, y) == (693, 387) and self.card and self.open is None:
            self.exported = True
        elif (x, y) == (693, 417) and self.card:
            if self.box["start"] and self.box["end"]:
                self.card = False
            else:
                self.asking = True
        elif (x, y) == (956, 506) and self.asking:
            self.asking, self.card = False, False

    def drag(self, to_y):
        if self.open in ("start", "end") and self.up:
            end, track_top, grab, land = X.BOXES[self.open]["thumb"]
            if to_y == track_top:
                self.first = date(1964, 1, 1)
            elif to_y == land:
                self.first = self.land

    def key(self, k):
        if k in ("down", "up"):
            self.keys += 1
            if self.drop_every and self.keys % self.drop_every == 0:
                return                                   # CTMS missed this one
            if self.open == "pt" and k == "up":
                self.pt_ups += 1
            elif self.open in ("start", "end") and not self.up:
                self.sel += timedelta(days=1 if k == "down" else -1)
                if self.sel > self.first + timedelta(days=7):
                    self.first = self.sel - timedelta(days=7)
                elif self.sel < self.first:
                    self.first = self.sel
        elif k == "enter" and self.open in ("start", "end") and not self.up:
            self.box[self.open], self.open = self.sel + timedelta(days=self.enter_off), None


def _run(fake, which="next"):
    keep = X._client
    X._client = lambda: fake
    try:
        return X.run(which, today=SUNDAY)
    finally:
        X._client = keep


# ---- the digit reader ----
def test_a_list_reads_as_its_run_of_days_and_the_blue_row_gets_the_day_its_place_puts_on_it():
    img = Image.new("RGB", (60, 342), (255, 255, 255))
    first = date(2026, 10, 26)
    for k in range(8):
        y = 165 + 22 * k
        if k == 7:
            blue(img, 5, y)
        else:
            draw(img, 5, y, D.code_of(first + timedelta(days=k)))
    draw(img, 5, 31 + 3, D.code_of(date(2026, 11, 2)))      # a box showing beside the list, off its grid
    rows, chosen = D.read_list(img, 5, date(2026, 11, 2))
    assert [d for _, d in rows] == [first + timedelta(days=k) for k in range(7)]
    assert chosen == (165 + 22 * 7, date(2026, 11, 2))
    assert D.read_box(img, 5, 34) == date(2026, 11, 2)


def test_junk_rows_far_off_and_a_lone_row_are_never_trusted():
    img = Image.new("RGB", (60, 200), (255, 255, 255))
    for k in range(6):
        draw(img, 5, 10 + 22 * k, D.code_of(JUNK + timedelta(days=k)))
    assert D.read_list(img, 5, date(2026, 11, 2)) == ([], None)
    one = Image.new("RGB", (60, 40), (255, 255, 255))
    draw(one, 5, 10, "261102")
    assert D.read_list(one, 5, date(2026, 11, 2)) == ([], None)
    assert D.read_box(Image.new("RGB", (60, 40), (255, 255, 255)), 5, 10) is None


# ---- the week, and the small rules ----
def test_the_week_is_monday_to_sunday_and_a_sunday_belongs_to_the_week_it_ends():
    assert X.week_of("next", SUNDAY) == (date(2026, 11, 2), date(2026, 11, 8))
    assert X.week_of("current", SUNDAY) == (date(2026, 10, 26), date(2026, 11, 1))
    assert X.week_of("current", date(2026, 11, 2)) == (date(2026, 11, 2), date(2026, 11, 8))


def test_keys_go_a_hundred_a_batch_and_the_row_clicked_needs_the_fewest():
    assert [len(c) for c in X.presses(166)] == [100, 66] and X.presses(0) == [[]]
    assert X.presses(-3) == [["key up after=0.1"] * 3]
    rows = [(0, date(2026, 5, 15)), (22, date(2026, 5, 16))]
    assert X.pick(rows, date(2026, 11, 2)) == (22, date(2026, 5, 16))
    assert X.pick(rows, date(2026, 5, 1)) == (0, date(2026, 5, 15))       # all after: the first, then keys up


# ---- the run ----
def test_from_a_closed_card_the_week_is_set_by_reading_the_lists_and_only_then_exported():
    fake = FakeCTMS()
    out = _run(fake)
    assert out["ok"], out
    assert fake.box == {"start": date(2026, 11, 2), "end": date(2026, 11, 8)} and fake.cc and fake.pt and fake.name
    assert fake.exported and not fake.card and fake.tabs_closed == 0
    assert out["week"] == "02/11/2026-08/11/2026" and out["rows"] == 57 and out["file"].startswith("short_rail_rep_")
    assert fake.since and fake.since < datetime.now().strftime("%Y-%m-%d_%H%M%S")    # only a file made since
    assert "Start Schedule 02/11/2026 (from 22/05/2026, clicked in its list)" in out["said"], out["said"]
    assert "nothing sent" in out["said"] and "Export card closed" in out["said"]


def test_keys_ctms_missed_are_made_up_from_what_the_list_shows():
    fake = FakeCTMS(drop_every=10)
    out = _run(fake)
    assert out["ok"], out
    assert fake.box == {"start": date(2026, 11, 2), "end": date(2026, 11, 8)}


def test_a_card_left_open_on_a_day_starts_from_it_without_dragging():
    fake = FakeCTMS(card=True, name=True, start=date(2026, 10, 26), cc=True)
    out = _run(fake)
    assert out["ok"], out
    assert "Start Schedule 02/11/2026 (from 26/10/2026, the day it was on)" in out["said"]
    assert fake.log.count("click 362,187") == 0                     # the card was up: no menu
    assert fake.box["start"] == date(2026, 11, 2)


def test_the_current_week_too():
    fake = FakeCTMS()
    out = _run(fake, "current")
    assert out["ok"] and fake.box == {"start": date(2026, 10, 26), "end": date(2026, 11, 1)}


def test_a_list_that_does_not_read_stops_it_before_export_and_ctms_is_left_alone():
    fake = FakeCTMS(land=JUNK)
    out = _run(fake)
    assert not out["ok"] and "did not read as days near 02/11/2026" in out["said"], out
    assert not fake.exported and fake.tabs_closed == 0 and "export_fetch" not in fake.log
    assert "Nothing was emailed" in out["said"]


def test_boxes_that_do_not_read_back_as_the_week_are_never_exported():
    fake = FakeCTMS(enter_off=1)
    out = _run(fake)
    assert not out["ok"] and "before Export, the schedule boxes read 03/11/2026 to 09/11/2026" in out["said"], out
    assert not fake.exported


def test_short_rail_further_up_its_list_is_found_with_more_keys():
    fake = FakeCTMS(pt_ups_needed=X.PT_UPS + 6)
    assert _run(fake)["ok"] and fake.pt
    fake = FakeCTMS(pt_ups_needed=X.PT_UPS + 40)
    out = _run(fake)
    assert not out["ok"] and "SHORT_RAIL is not in view" in out["said"] and not fake.exported


def test_a_file_that_is_not_this_export_stops_it_and_its_tab_is_closed():
    fake = FakeCTMS(stale=True)
    out = _run(fake)
    assert not out["ok"] and "is not the export just made" in out["said"], out
    assert fake.tabs_closed == 1 and "After Export:" in out["said"]


def test_every_step_it_sends_is_one_the_real_client_takes():
    import ctms_remote as R
    fake = FakeCTMS(pt_ups_needed=X.PT_UPS + 6)
    assert _run(fake)["ok"]
    keep = R.load_state
    R.load_state = lambda: {"kind": "window", "img_w": 1910, "img_h": 915}
    try:
        steps = R.parse_steps(fake.sent)
    finally:
        R.load_state = keep
    assert len(steps) == len(fake.sent) and {s["action"] for s in steps} >= {"anchor", "click", "drag", "key", "find",
                                                                          "snap", "settle"}
    assert all(s.get("box") for s in steps if s["action"] in ("find", "snap"))


def test_close_answers_yes_when_ctms_asks():
    fake = FakeCTMS(card=True)
    assert X.close_card(fake) is True and not fake.card and "click 956,506" in fake.log


def test_which_week_must_be_next_or_current():
    assert X.run("last")["ok"] is False


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
