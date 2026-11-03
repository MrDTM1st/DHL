"""The well's filters (03/11, work_pc/ctms_filters.py and Booking's use of them): what's set is read by name or by where
it sits, cleared the way a clean well has it, and put back as he had it, each read back - a drop-down moved by its keys
(a click on an open list's row can pick nothing). The panels' places as read live on 03/11. Made-up values only.

    python -m pytest -q tests/test_ctms_filters.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_book as B  # noqa: E402
import ctms_filters as F  # noqa: E402

PANEL_AT, ADV_AT = [30, 491, 426, 456], [378, 284, 523, 574]
BUSINESS = ["", "Strategy 1 - Flats & Hiabs", "Strategy 2 - Bulk", "Strategy 3 - Rails"]
DELIVERY = ["All", "STANDARD", "NEXT DAY", "EMERGENCY"]


class Filters:
    """Planning with Order Filters and Advanced Order Filters: drop-downs that only move by their keys."""

    def __init__(self, business="", delivery="All", show_all=True, weight="", stuck=()):
        self.vals = {"Business Type": business, "Delivery Type": delivery, "Show All Orders": show_all, "Weight": weight}
        self.lists = {"Business Type": BUSINESS, "Delivery Type": DELIVERY}
        self.panel = self.adv = False
        self.open_list = None             # (name, index picked while open)
        self.stuck = set(stuck)           # boxes CTMS won't change
        self.focus = None
        self.applied = []

    def _boxes(self):
        return {"Delivery Type": ("combo box", [506, 319, 225, 27], ADV_AT, "Delivery Type"),
                "Business Type": ("combo box", [506, 571, 225, 28], ADV_AT, ""),
                "Show All Orders": ("check box", [444, 677, 120, 24], ADV_AT, "Show All Orders"),
                "Weight": ("text", [146, 736, 77, 27], PANEL_AT, "Weight")}

    def read(self, tree=True, skip=()):
        els = [{"r": "internal frame", "nm": "Planning", "lv": 0, "at": [20, 151, 1648, 807]},
               {"r": "push button", "nm": "Order Filters", "lv": 1, "at": [1557, 544, 95, 23]}]
        for win, up, at, btns in ((F.PANEL, self.panel, PANEL_AT, [("Refresh", [58, 914, 118, 24]),
                                                                   ("Advanced Filters", [303, 914, 118, 24])]),
                                  (F.ADVANCED, self.adv, ADV_AT, [("Search", [423, 777, 100, 30]), ("Close", [524, 777, 100, 30])])):
            if not up:
                continue
            els.append({"r": "internal frame", "nm": win, "lv": 0, "at": at})
            for n, (role, bat, wat, nm) in self._boxes().items():
                if wat is not at:
                    continue
                e = {"r": role, "nm": nm, "lv": 1, "at": bat}
                v = self.vals[n]
                if role == "check box":
                    e["st"] = ["checked"] if v else None
                elif v:
                    e["v"] = v
                els.append(e)
                if self.open_list and self.open_list[0] == n:
                    els += [{"r": "label", "nm": row, "lv": 2, "at": [bat[0], bat[1] + 23 * (k + 1), 200, 22],
                             "st": ["selected"] if k == self.open_list[1] else None} for k, row in enumerate(self.lists[n])]
            els += [{"r": "push button", "nm": b, "lv": 1, "at": bat} for b, bat in btns]
        return els

    def run(self, steps):
        for s in steps:
            a = s["action"]
            if a == "click":
                self.click(s.get("screen"))
            elif a == "key":
                self.key(s["key"])
            elif a == "type" and self.focus:
                self.vals[self.focus] = s["text"]

    def click(self, sc):
        if not sc:
            return
        if abs(sc[0] - 1604) < 50 and abs(sc[1] - 555) < 12:
            self.panel = True
            return
        if self.panel and [PANEL_AT[0] + PANEL_AT[2] - 13, PANEL_AT[1] + 11] == list(sc):
            self.panel = False
            return
        for b, bat in (("Advanced Filters", [303, 914, 118, 24]), ("Refresh", [58, 914, 118, 24]),
                       ("Search", [423, 777, 100, 30]), ("Close", [524, 777, 100, 30])):
            if bat[0] <= sc[0] <= bat[0] + bat[2] and bat[1] <= sc[1] <= bat[1] + bat[3]:
                if b == "Advanced Filters":
                    self.adv = True
                elif b == "Close":
                    self.adv = False
                else:
                    self.applied.append(b)
                return
        for n, (role, bat, _w, _nm) in self._boxes().items():
            if bat[0] <= sc[0] <= bat[0] + bat[2] and bat[1] <= sc[1] <= bat[1] + bat[3]:
                if role == "check box" and n not in self.stuck:
                    self.vals[n] = not self.vals[n]
                elif role == "combo box":
                    self.open_list = (n, self.lists[n].index(self.vals[n])) if not self.open_list else None
                else:
                    self.focus = n
                return

    def key(self, k):
        if self.open_list:
            n, i = self.open_list
            if k in ("down", "up"):
                self.open_list = (n, max(0, min(len(self.lists[n]) - 1, i + (1 if k == "down" else -1))))
            elif k == "enter":
                if n not in self.stuck:
                    self.vals[n] = self.lists[n][i]
                self.open_list = None
            elif k == "escape":
                self.open_list = None


def _job(f):
    return B.Booking(f.run, f.read, lambda name, box: False, {})


def test_unnamed_boxes_are_known_by_where_they_sit():
    f = Filters(business="Strategy 2 - Bulk")
    f.panel = f.adv = True
    vals = F.values(f.read(), F.ADVANCED)
    assert vals == {"Delivery Type": "All", "Business Type": "Strategy 2 - Bulk", "Show All Orders": True}
    assert F.set_ones(vals) == {"Business Type": "Strategy 2 - Bulk"}


def test_a_clean_well_has_nothing_set():
    f = Filters()
    f.panel = f.adv = True
    assert F.set_ones(F.values(f.read(), F.ADVANCED)) == {} and F.set_ones(F.values(f.read(), F.PANEL)) == {}


def test_an_open_list_is_moved_by_its_keys_never_a_click_on_its_row():
    rows = [("", False), ("A", True), ("B", False), ("C", False)]
    assert F.moves(rows, "C") == ["down", "down"] and F.moves(rows, "") == ["up"] and F.moves(rows, "A") == []
    assert F.moves(rows, "Z") is None and F.moves([("A", False)], "A") is None


def test_his_filters_are_cleared_to_find_the_order_and_put_back_after():
    f = Filters(business="Strategy 2 - Bulk", delivery="NEXT DAY", show_all=False, weight="5000")
    job = _job(f)
    job.look()
    assert job.clear_filters() is True
    assert f.vals == {"Business Type": "", "Delivery Type": "All", "Show All Orders": True, "Weight": ""}
    assert "Search" in f.applied and "Refresh" in f.applied and not f.panel and not f.adv
    job.restore_filters()
    assert f.vals == {"Business Type": "Strategy 2 - Bulk", "Delivery Type": "NEXT DAY", "Show All Orders": False,
                      "Weight": "5000"}
    assert job.said[-1] == "the well's filters put back as they were" and not f.panel and not f.adv


def test_no_filter_on_means_nothing_touched():
    f = Filters()
    job = _job(f)
    job.look()
    assert job.clear_filters() is False and job.filters_was == {} and not f.panel and not f.adv


def test_a_filter_that_wont_go_back_is_said_for_him_to_put_back():
    f = Filters(business="Strategy 2 - Bulk")
    job = _job(f)
    job.look()
    job.clear_filters()
    f.stuck.add("Business Type")
    job.restore_filters()
    assert job.said[-1] == "PUT BACK BY HAND on the well's filters: Business Type 'Strategy 2 - Bulk'"


def test_a_rehearsal_says_which_filters_it_would_clear_and_clears_none():
    f = Filters(business="Strategy 2 - Bulk")
    job = _job(f)
    job.dry = True
    job.look()
    assert job.clear_filters() is False and f.vals["Business Type"] == "Strategy 2 - Bulk"
    assert "would be cleared and put back: Business Type 'Strategy 2 - Bulk'" in job.said[-1]
