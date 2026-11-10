"""Order Search on CTMS as its own app (10/11/2026): the card's boxes and buttons found by their Access Bridge names and
clicked where it places them, wherever the card opens, and Order Summary's "Required" columns read. Made-up orders only.

    python -m pytest tests/test_ctms_orders_card.py -q
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_orders as CO  # noqa: E402


class Templates(dict):
    def __missing__(self, name):
        return {"rgb": "", "w": 1, "h": 1}


NAMES = {"SCHED_NAME": "Enter value for : SCHED_NAME Required", "EXTERNAL_REF": "Enter value for : EXTERNAL_REF",
         "STATUS": "Enter value for : STATUS Required", "DELIVERY_TYPE_ID": "Enter value for : DELIVERY_TYPE_ID",
         "EARLY_AVAIL": "Enter value for : EARLY_AVAIL", "LATE_DEL": "Enter value for : LATE_DEL"}
LEFT = {"SCHED_NAME": 30, "EXTERNAL_REF": 110, "STATUS": 240, "DELIVERY_TYPE_ID": 330, "EARLY_AVAIL": 420,
        "LATE_DEL": 560}


def _row(ref, status, sched="261112"):
    return {"SCHED_NAME": sched, "EXTERNAL_REF": ref, "STATUS": status, "DELIVERY_TYPE_ID": "STANDARD",
            "EARLY_AVAIL": "11/11/26 08:00", "LATE_DEL": "12/11/26 16:00"}


def _app_read(left=1480, rows=(), card=True):
    """A read as the app hands it over: Order Summary with its required columns named '... Required', and the compact
    Search card (a planner's own saved layout) with its left edge at `left` on the screen."""
    els = [{"r": "internal frame", "nm": "Planning", "lv": 1},
           {"r": "internal frame", "nm": "Order Summary", "lv": 1}]
    for item, nm in NAMES.items():
        for i in reversed(range(5)):                       # bottom row first: order is by place, not by read
            els.append({"r": "text", "nm": nm, "lv": 2, "v": rows[i][item] if i < len(rows) else "",
                        "at": [LEFT[item], 250 + 23 * i, 80, 23]})
    if card:
        els += [{"r": "internal frame", "nm": "Order Search", "lv": 1, "at": [left, 120, 420, 160]},
                {"r": "combo box", "nm": "Layout", "lv": 2, "v": "1: Planner", "at": [left + 80, 150, 200, 22]},
                {"r": "text", "nm": "Enter a Customer Ref to search for", "lv": 2, "at": [left + 120, 180, 160, 22]},
                {"r": "text", "nm": "Enter a Booking Ref to search for", "lv": 2, "at": [left + 120, 205, 160, 22]},
                {"r": "text", "nm": "Enter a Trip Id to search for", "lv": 2, "at": [left + 120, 230, 160, 22]},
                {"r": "push button", "nm": "Close", "lv": 2, "at": [left + 100, 255, 70, 24]},
                {"r": "push button", "nm": "Clear", "lv": 2, "at": [left + 180, 255, 70, 24]},
                {"r": "push button", "nm": "Refresh", "lv": 2, "at": [left + 260, 255, 70, 24]}]
    return {"elements": els}


def test_the_apps_required_columns_are_read_so_an_open_line_shows_unscheduled():
    got = CO.lines(_app_read(rows=[_row("9100040-1-1", "UNSCHEDULED"), _row("9100040-2-1", "SCHEDULED")]))
    assert [(r["ref"], r["status"], r["schedule"]) for r in got] == [
        ("9100040-1-1", "UNSCHEDULED", "261112"), ("9100040-2-1", "SCHEDULED", "261112")]
    assert CO.line_for(got, "12/11/2026")["ref"] == "9100040-1-1"        # blank before: no line was ever open


def test_the_card_is_found_by_its_names_wherever_it_opens():
    for left in (480, 1480):                                            # the middle, or over on the right
        p = CO.card_parts(_app_read(left=left))
        assert set(p) == {"customer", "booking", "close", "clear", "refresh"}
        assert CO.card_up(_app_read(left=left)) and CO._mid(p["customer"]) == [left + 200, 191]
    assert CO.card_parts(_app_read(card=False)) is None and not CO.card_up(_app_read(card=False))
    hidden = _app_read()
    for e in hidden["elements"]:
        if e["lv"] == 2 and "Enter value" not in e["nm"]:
            e["at"] = [-1, -1, -1, -1]                                   # listed, placed nowhere: not on the screen
    assert CO.card_parts(hidden) == {} and not CO.card_up(hidden)
    assert not CO.card_up({"elements": [{"r": "internal frame", "nm": "Order Search", "lv": 1}]})   # nothing of it read


def test_a_search_clicks_the_cards_own_boxes_and_buttons_where_the_access_bridge_places_them():
    read = _app_read(left=1480)
    steps = CO.search_at(read, "9100040%")
    assert [s["screen"] for s in steps if s["action"] == "click"] == [[1695, 267], [1680, 191], [1775, 267]]
    assert [s["text"] for s in steps if s["action"] == "type"] == ["9100040%"]        # Clear, Customer Ref, Refresh
    assert steps[-1]["react"] is True and steps[-1]["box"] == CO.FIRST_ROW_BOX and steps[-1]["timeout"] == 15
    assert not any(s["action"] == "anchor" for s in steps)     # the batch's anchor, taken before the card opened, holds
    assert [s["screen"] for s in CO.search_at(read, "NN1%", booking=True) if s["action"] == "click"][1] == [1680, 216]
    # no card in the read (an older one, or Edge's) or none of its boxes showing: the stored points, as ever
    assert CO.search_at({"elements": []}, "9100040%") == CO.search("9100040%")
    assert CO.search_at(_app_read(card=False), "NN1%", booking=True) == CO.search("NN1%", booking=True)
    shut = _app_read()
    shut["elements"] = [e for e in shut["elements"] if "search for" not in str(e.get("nm"))]
    assert CO.search_at(shut, "9100040%") == CO.search("9100040%")


def test_a_line_opens_on_its_own_status_cell_once_the_card_is_shut():
    t = Templates()
    read = _app_read(left=1480, rows=[_row("9100040-1-1", "UNSCHEDULED")])
    steps = CO.open_line_at(read, t)
    assert steps[0] == {"action": "click", "screen": [1615, 267], "after": 0.5}       # the card's own Close first
    assert steps[1]["double"] is True and steps[1]["screen"] == [280, 261] and steps[1]["react"] is True   # top line
    assert steps[2] == {"action": "anchor", "window": True} and steps[3]["name"] == "od-vehtype"
    # Status not read: its stored point, after the card's own Close when that is read
    no_status = {"elements": [e for e in read["elements"] if "STATUS" not in str(e.get("nm"))]}
    assert CO.open_line_at(no_status, t) == [steps[0]] + CO.open_line(t)[1:]
    assert CO.open_line_at({"elements": []}, t) == CO.open_line(t)
    assert CO.card_close_at({"elements": []}) == [{"action": "click", "px": [509, 226], "after": 0.5}]


def test_closing_a_line_can_leave_the_card_to_whoever_reads_it():
    t = Templates()
    assert CO.close_line(t)[-1]["name"] == "os-card"
    assert CO.close_line(t, then_card=False) == CO.close_line(t)[:3]
    assert "os-card" not in [s.get("name") for s in CO.close_line(t, then_card=False)]
