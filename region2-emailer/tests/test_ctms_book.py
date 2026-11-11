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
YES_AT, NO_AT, OK_AT = [980, 560, 40, 20], [1040, 560, 40, 20], [1000, 480, 40, 20]     # nowhere the old fixed points were
T = {k: {"rgb": "", "w": 1, "h": 1} for k in (
    "wm-refresh", "wm-apply-trip", "wm-create-trip", "sc-title", "cp-title", "cc-title", "mt-set-status", "st-accepted",
    "al-accepted", "os-split", "split-title", "split-ok", "close-ask", "od-vehtype", "os-card", "os-close",
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
        self.selection = []
        self.honours_selecting = True   # False: CTMS's Create New Trip takes the current row alone
        self.rows_a_page = 15
        self.panel_stuck = False
        self.carrier_behind = False
        self.alert = ""
        # each line's card as the Access Bridge reads it live (03/11): the Detail grid and Order Items
        self.line_info = {}             # ref: {"product", "qty", "items": [{"id", "ordered"}]}
        self.catalog = [("S&C", "S&C"), ("WHEELSETS", "Wheelsets"), ("WHEELSET_AXLE", "Wheelset axle")]
        self.card_tab, self.card_dirty, self.card_row = "Detail", False, 0
        self.item_win = None            # {"row", "id", "ordered"} while the item window is up
        self.weights = []               # each item Save's Weight box, as it was saved
        self.lov = None                 # Ctrl+L's choices while its list is up
        self.focus = None
        self.saves = []                 # what each save put on: ("item", ref, id, ordered) / ("card", ref, qty)
        self.list_of = None             # which drop-down the open list hangs from: trailer / alt
        self.shift = (0, 0)             # how far the carrier screen and payment box sit from these places
        self.types = None               # the Delivery Types list while it's up: {"find": typed, "rows": listed}
        self.type_list = list(TYPE_CODES)   # its rows as CTMS sorts them
        self.type_set = None            # the code its OK put on the card
        self.split_up = False           # the Split window
        self.split_names = ("Process", "Exit")
        self.split_typed = ""
        self.split_done = False

    # -- what the Access Bridge hands over
    def upto(self):
        """The well as its To lets it show."""
        return [r for r in self.well if datetime.strptime(r["deliver"][:8], "%d/%m/%y") <= datetime.strptime(self.to, "%y%m%d")]

    def rows_shown(self):
        rows = list(reversed(self.upto())) if self.reversed else self.upto()
        return rows[self.page * self.rows_a_page:self.page * self.rows_a_page + self.rows_a_page]

    def read(self, tree=True, skip=()):
        """As the Access Bridge hands it over: without tree, the manifest tree's own box but none of its rows."""
        self.reads += 1
        return self._els(tree, skip)

    def _els(self, tree=True, skip=()):
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
        for n, (man, status) in enumerate(self.tree.items() if tree else ()):
            els.append({"r": "label", "nm": f"Level 0 05/11/26 08:00 {man}  ({status})", "lv": 2, "at": [53, 228 + 23 * n, 284, 23],
                        "st": ["selected"] if man == self.selected else None})
        for i, r in enumerate(self.rows_shown()):
            for col in ("cust_ref", "booking_ref", "deliver", "del_type", "weight", "to_reg"):
                els.append(dict(_cell(col, i, r.get(col, "")), lv=2))
        if "Planning" in skip:                  # a card's read: Planning named, nothing inside it
            els = els[:1]
        if self.panel:
            els.insert(0, {"r": "internal frame", "nm": "Planned Orders", "lv": 0, "at": [503, 513, 1006, 332]})
            for i, ref in enumerate(self.panel):
                els.insert(1, {"r": "text", "nm": "Cust Ref", "v": ref, "lv": 2, "at": [694, 558 + 23 * i, 160, 23]})
        if self.up == "confirm":
            els[0:0] = [{"r": "internal frame", "nm": f"Confirm Create Trip Carrier  {self.carrier_picked}\nRevenue         562.62\n"
                                                      f"Cost                {self.cost}\nDo you want to continue?", "lv": 0},
                        {"r": "option pane", "nm": "Do you want to continue?", "lv": 1, "at": [900, 500, 300, 120]},
                        {"r": "push button", "nm": "Yes ALT Y", "lv": 2, "at": YES_AT},
                        {"r": "push button", "nm": "No ALT N", "lv": 2, "at": NO_AT}]
        if self.alert:
            els[0:0] = [{"r": "internal frame", "nm": "Forms", "lv": 0},
                        {"r": "option pane", "nm": self.alert, "lv": 1, "at": [900, 440, 300, 100]},
                        {"r": "push button", "nm": "OK ALT O", "lv": 2, "at": OK_AT}]
        if self.up in ("carrier", "payment", "confirm"):
            dx, dy = self.shift
            els.append({"r": "internal frame", "nm": B.CARRIER_FRAME, "lv": 0, "at": [437 + dx, 130 + dy, 1216, 379]})
            for i, c in enumerate(self.carriers):
                els.append({"r": "text", "nm": "", "v": c, "lv": 2, "at": [492 + dx, 235 + dy + 23 * i, 113, 23]})
            for which, (x, y, w, h) in (("trailer", TRAILER_AT), ("alt", ALT_AT)):
                els.append({"r": "combo box", "nm": "", "lv": 2, "at": [x + dx, y + dy, w, h]})   # no names of their own
                shown = self.list is not None and self.list_of == which
                els.append({"r": "list", "nm": "", "lv": 3,
                            "at": [LIST_X + dx, LIST_Y + dy, LIST_W, 22 * len(self.list)] if shown else [-1, -1, -1, -1]})
            if self.list:
                for i, name in enumerate(self.list):
                    els.append({"r": "label", "nm": name, "lv": 2, "at": [LIST_X + dx, LIST_Y + dy + 22 * i, LIST_W, 22]})
            on = None if self.up == "carrier" else ["disabled"]
            els += [{"r": "push button", "nm": name, "lv": 2, "at": [x + dx, y + dy, w, h], "st": on}
                    for name, (x, y, w, h) in (("Select Carrier", SELECT_AT), ("Exit", EXIT_AT))]
        if self.up == "payment":
            dx, dy = self.shift
            els[0:0] = [{"r": "internal frame", "nm": B.PAYMENT_FRAME, "lv": 0, "at": [560 + dx, 600 + dy, 420, 200]}] + [
                {"r": "push button", "nm": name, "lv": 1, "at": [x + dx, y + dy, w, h]}
                for name, (x, y, w, h) in (("Create Trip", CREATE_AT), ("Cancel", CANCEL_AT))]
        if self.split_up:
            els[0:0] = [{"r": "internal frame", "nm": "Split Orders", "lv": 0, "at": [500, 400, 500, 300]},
                        {"r": "text", "nm": "Number of splits", "v": self.split_typed, "lv": 1, "at": [620, 440, 60, 23]}] + [
                {"r": "push button", "nm": name, "lv": 1, "at": at}
                for name, at in zip(self.split_names, ([560, 620, 100, 30], [800, 620, 100, 30]))]
        if self.card:
            els += self.card_els()
        if self.carrier_behind:     # last: CTMS reads its windows front first, so a new carrier window comes before this one
            els += [{"r": "internal frame", "nm": B.CARRIER_FRAME, "lv": 0, "at": [437, 130, 1216, 379]}] + [
                {"r": "push button", "nm": name, "lv": 2, "at": list(at), "st": ["disabled"]}   # behind Planning (11/11)
                for name, at in (("Select Carrier", SELECT_AT), ("Exit", EXIT_AT))]
        return els

    def info(self, ref):
        return self.line_info.setdefault(ref, {"product": "S&C", "qty": 1, "items": [{"id": "S&C", "ordered": 1}]})

    def card_els(self):
        """The open card, its names and places as read live on 03/11."""
        li = self.info(self.card)
        els = [{"r": "internal frame", "nm": "Order details for 11000001", "lv": 0, "at": [20, 151, 1239, 702]},
               {"r": "text", "nm": "Customer Ref", "v": self.card, "lv": 2, "at": [596, 243, 159, 26]}]
        for name, at in (("Detail", [25, 274, 76, 23]), ("Order Items", [98, 274, 86, 23]), ("Add Detail", [254, 274, 78, 23])):
            els.append({"r": "page tab", "nm": name, "lv": 2, "at": at, "st": ["selected"] if self.card_tab == name else None})
        if self.card_tab == "Detail":
            els += [{"r": "text", "nm": "Product Type", "v": li["product"], "lv": 3, "at": [30, 567, 121, 23]},
                    {"r": "text", "nm": "Qty", "v": f"   {(self.pending_qty if self.card_dirty else li['qty']):.3f}", "lv": 3,
                     "at": [261, 567, 92, 23]},
                    {"r": "text", "nm": "Product Type", "v": "", "lv": 3, "at": [30, 590, 121, 23], "st": ["read-only"]}]
        if self.card_tab == "Order Items":
            for i, it in enumerate(li["items"]):
                els += [{"r": "text", "nm": "Order Items tab page Identifier Required" if i == 0 else "Identifier Required",
                         "v": it["id"], "lv": 3, "at": [55, 343 + 24 * i, 80, 24], "st": ["read-only"]},
                        {"r": "text", "nm": "Ordered", "v": f"      {it['ordered']:g}", "lv": 3, "at": [676, 343 + 24 * i, 70, 24]}]
            els.append({"r": "push button", "nm": "Edit/Delete", "lv": 3, "at": [150, 612, 110, 26]})
        front = []
        if self.item_win:
            front += [{"r": "internal frame", "nm": "Create,Edit or Delete Order Item", "lv": 0, "at": [18, 151, 826, 486]},
                      {"r": "text", "nm": "Identifier Required", "v": self.item_win["id"], "lv": 1, "at": [133, 323, 357, 23]},
                      {"r": "text", "nm": "Ordered", "v": f"      {self.item_win['ordered']:g}", "lv": 1, "at": [133, 459, 110, 24]},
                      {"r": "text", "nm": "Delivered", "v": self.item_win.get("delivered", "       0"), "lv": 1,
                       "at": [500, 459, 110, 24]},
                      {"r": "text", "nm": "Weight", "v": self.item_win.get("weight", "34,970.00"), "lv": 1,
                       "at": [133, 493, 110, 23]},
                      {"r": "push button", "nm": "Save", "lv": 1, "at": [138, 584, 100, 30]},
                      {"r": "push button", "nm": "Exit", "lv": 1, "at": [618, 584, 100, 30]}]
        if self.lov is not None:
            front += [{"r": "internal frame", "nm": "Product Items", "lv": 0, "at": [133, 346, 456, 456]}]
            front += [{"r": "label", "nm": f"Item_Id:{a}\tItem_Description:{b}", "lv": 2, "at": [-1, -1, -1, -1],
                       "st": ["selected"] if k == 0 else None} for k, (a, b) in enumerate(self.lov)]
            front += [{"r": "push button", "nm": "OK ALT O", "lv": 1, "at": [363, 763, 61, 31]},
                      {"r": "push button", "nm": "Cancel ALT C", "lv": 1, "at": [429, 763, 61, 31]}]
        if self.types is not None:          # mid-window: where it sits depends on CTMS's window (10-11/11)
            front += [{"r": "internal frame", "nm": B.TYPES_FRAME, "lv": 0, "at": [700, 420, 420, 500], "types": True},
                      {"r": "text", "nm": "Find", "v": self.types["find"], "lv": 1, "at": [760, 470, 350, 22], "types": True}]
            front += [{"r": "label", "nm": f"Delivery_Type:{v}", "lv": 2, "at": [-1, -1, -1, -1],
                       "st": ["selected"] if k == 0 else None} for k, v in enumerate(self.types["rows"])]
            front += [{"r": "push button", "nm": name, "lv": 1, "at": [x, 880, 61, 31], "types": True}
                      for name, x in (("Find ALT F", 760), ("OK ALT O", 830), ("Cancel ALT C", 900))]
        return front + els

    def card_click(self, sc):
        """A click where the Access Bridge places something on the open card: True when it landed on one."""
        under = [e for e in self.card_els() if e["r"] != "internal frame" and len(e.get("at") or []) == 4 and e["at"][2] > 0
                 and e["at"][0] <= sc[0] <= e["at"][0] + e["at"][2] and e["at"][1] <= sc[1] <= e["at"][1] + e["at"][3]]
        if not under:
            return False
        hit = min(under, key=lambda e: e["at"][2] * e["at"][3])
        nm, li = hit["nm"], self.info(self.card)
        if hit.get("types"):
            self.types_click(hit)
            return True
        if hit["r"] == "page tab":
            self.card_tab = nm
        elif nm.endswith("Identifier Required") and not self.item_win:
            self.card_row = (hit["at"][1] - 343) // 24
        elif nm == "Edit/Delete":
            it = li["items"][self.card_row]
            self.item_win = {"row": self.card_row, "id": it["id"], "ordered": it["ordered"]}
        elif nm == "Identifier Required":
            self.focus = "id"
        elif nm == "Ordered" and self.item_win:
            self.focus = "ordered"
        elif nm in ("Weight", "Delivered") and self.item_win:
            self.focus = nm.lower()
        elif nm == "Qty":
            self.focus = "qty"
        elif nm == "OK ALT O":
            self.item_win["id"] = self.lov[0][0]
            self.lov = None
        elif nm == "Cancel ALT C":
            self.lov = None
        elif nm == "Save" and self.item_win:
            li["items"][self.item_win["row"]] = {"id": self.item_win["id"], "ordered": self.item_win["ordered"]}
            self.saves.append(("item", self.card, self.item_win["id"], self.item_win["ordered"]))
            self.weights.append(self.item_win.get("weight", "34,970.00"))
        elif nm == "Exit":
            self.item_win, self.focus = None, None
        return True

    def types_click(self, hit):
        """The Delivery Types list: its Find box, Find (any case, as Forms' Find), OK, Cancel."""
        name = hit["nm"].split(" ALT ")[0]
        if hit["r"] == "text":
            self.focus = "types"
        elif name == "Find":
            want = self.types["find"].rstrip("%").upper()
            self.types["rows"] = [v for v in self.type_list if v.upper().startswith(want)]
        elif name == "OK":
            self.type_set = self.types["rows"][0]
            self.types, self.focus = None, None
        elif name == "Cancel":
            self.types, self.focus = None, None

    def list_click(self, sc):
        """A click on the open drop-down: its scroll arrow does nothing here, a row is picked. True when it was on it."""
        dx, dy = self.shift
        if not (LIST_X + dx <= sc[0] <= LIST_X + dx + LIST_W and LIST_Y + dy <= sc[1] < LIST_Y + dy + 22 * len(self.list)):
            return False
        if sc[0] >= LIST_X + dx + LIST_W - 20:
            return True                                   # its own scroll arrow
        name = self.list[(sc[1] - LIST_Y - dy) // 22]
        setattr(self, "trailer_picked" if name.startswith("NR_") else "alt_picked", name)
        self.list, self.list_of = None, None
        return True

    def named_click(self, sc):
        """A click on the carrier screen, the payment box or the Split window, worked by what is under it as read."""
        frame, hit = "", None
        for e in self._els(tree=False):
            if e["r"] == "internal frame":
                frame = e["nm"]
                continue
            at = e.get("at") or []
            if (e["r"] in ("push button", "combo box", "text") and len(at) == 4 and at[2] > 0
                    and at[0] <= sc[0] <= at[0] + at[2] and at[1] <= sc[1] <= at[1] + at[3]
                    and frame.startswith((B.CARRIER_FRAME, B.PAYMENT_FRAME, "Split"))):
                if hit is None or at[2] * at[3] < hit[1]["at"][2] * hit[1]["at"][3]:
                    hit = (frame, e)
        if hit is None:
            return False
        frame, e = hit
        name = e["nm"]
        if "disabled" in (e.get("st") or []):
            return True                                   # a window behind something: the click does nothing
        if frame.startswith(B.CARRIER_FRAME):
            if e["r"] == "combo box":
                self.list_of = "trailer" if e["at"][2] == TRAILER_AT[2] else "alt"
                self.list = list(TRAILERS) if self.list_of == "trailer" else ["ACME", "BRAVO"]
            elif e["r"] == "text":
                self.row_picked = e["v"]
            elif name == "Select Carrier":
                self.carrier_picked = getattr(self, "alt_picked", None) or getattr(self, "row_picked", "")
                self.up = "payment"
            elif name == "Exit":
                self.up = None
        elif frame.startswith(B.PAYMENT_FRAME):
            if name == "Create Trip":
                self.up = "confirm"
            elif name == "Cancel":
                self.up = "carrier"
        elif e["r"] == "text":
            self.focus = "split"
        elif name == self.split_names[0]:
            self.alert, self.split_done = "Split done", True
        elif name == self.split_names[1]:
            self.split_up = False
        return True

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
            if self.card and self.focus == "id" and self.item_win:
                self.item_win["id"] = s["text"]
            elif self.card and self.focus == "ordered" and self.item_win:
                self.item_win["ordered"] = float(s["text"])
            elif self.card and self.focus == "qty":
                self.pending_qty, self.card_dirty = float(s["text"]), True
            elif self.types is not None and self.focus == "types":
                self.types["find"] = s["text"]
            elif self.split_up and self.focus == "split":
                self.split_typed = s["text"]
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
            self.creating = list(self.selection) if self.honours_selecting and self.selection else [self.current]
        elif name == "sc-title" and self.up != "carrier":
            raise RuntimeError("'sc-title' is not on the screen")
        elif name == "cp-title" and self.up != "payment":
            raise RuntimeError("'cp-title' is not on the screen")
        elif name == "cc-title" and self.up != "confirm":
            raise RuntimeError("'cc-title' is not on the screen")
        elif name == "wm-apply-trip":
            self.trip_lines[self.selected].append(self.current)
            self.well = [r for r in self.well if r["cust_ref"] != self.current]
        elif name == "st-accepted":
            self.alert = "Manifest accepted"
        elif name == "wm-refresh":
            self.page = 0
        elif name == "mt-set-status":
            self.menu = "status"
        elif name == "os-split":
            self.split_up = True

    def click(self, s):
        px = tuple(s.get("px") or ())
        sc = s.get("screen")
        if px == NEW_ORDER:                     # what used to be pressed for Planned Orders' close, it sitting elsewhere
            self.card = "NEW"
        if sc:
            if s.get("right"):
                return
            if self.up == "confirm" and list(sc) == [YES_AT[0] + 20, YES_AT[1] + 10]:
                self.confirm_yes()
                return
            if self.up == "confirm" and list(sc) == [NO_AT[0] + 20, NO_AT[1] + 10]:
                self.up = "carrier"             # the payment box shuts with it (02/11)
                return
            if self.alert and list(sc) == [OK_AT[0] + 20, OK_AT[1] + 10]:
                if self.alert == "Manifest accepted" and self.selected and self.tree.get(self.selected) == "PLANNED":
                    self.tree[self.selected] = "ACCEPTED"
                self.alert = ""
                return
            if self.card and self.card_click(sc):
                return
            if self.up == "carrier" and self.list and self.list_click(sc):
                return
            if self.named_click(sc):
                return
            if self.panel and not self.panel_stuck and list(sc) == [503 + 1006 - B.PLANNED_X, 513 + B.PLANNED_Y]:
                self.panel = None
                return
            if list(sc) == [TO_BOX[0] + TO_BOX[2] - 10, TO_BOX[1] + TO_BOX[3] // 2]:
                self.to_list = None if self.to_list else self.to
                return
            for i, r in enumerate(self.rows_shown()):
                y = Y0 + 23 * i
                if abs(sc[1] - (y + 11)) < 12 and X0 <= sc[0] <= X0 + 100:
                    self.click_row(r["cust_ref"], s.get("hold") or [])
                    if s.get("double"):
                        self.card = r["cust_ref"]
                    return
            if abs(sc[0] - (1127 + 33)) < 40 and abs(sc[1] - 572) < 14:
                self.reversed = not self.reversed
                self.page = 0
            return
        if px == B.TYPE_LIST and self.card and self.card_tab == "Add Detail":
            self.types = {"find": "%", "rows": list(self.type_list)}
        elif px == B.ORDERS_BUTTON:
            self.panel = list(self.trip_lines.get(self.selected) or [""])
        elif px == B.PLANNING_SAVE:
            self.saved += 1
            self.status_line = ""
        elif px == B.ORDER_SAVE:
            self.typed.append("<order saved>")
            if self.card_dirty:
                self.info(self.card)["qty"] = self.pending_qty
                self.saves.append(("card", self.card, self.pending_qty))
            self.card_dirty = False
        elif px == B.ORDER_CLOSE:
            self.card, self.card_tab, self.item_win, self.lov, self.focus = None, "Detail", None, None, None
            self.card_dirty = False

    def confirm_yes(self):
        self.up = None
        man = f"MAN-0{self.next_man}"
        self.next_man += 1
        self.tree[man] = "PLANNED"
        self.selected = man
        self.trip_lines[man] = list(self.creating)
        self.well = [r for r in self.well if r["cust_ref"] not in self.creating]
        self.selection = []
        self.status_line = f"Order 11351960 scheduled on trip: {self.sched} / {man}"

    def click_row(self, ref, hold):
        shown = [r["cust_ref"] for r in self.rows_shown()]
        if "shift" in hold:
            a, b = sorted((shown.index(self.current), shown.index(ref)))
            self.selection = shown[a:b + 1]
        elif "ctrl" in hold:
            self.selection = self.selection + [ref]
        else:
            self.selection = [ref]
        self.current = ref

    def key(self, k):
        if k == "delete" and self.item_win and self.focus in ("weight", "delivered"):
            self.item_win[self.focus] = ""
            return
        if k == "ctrl+l" and self.card and self.item_win and self.focus == "id":
            self.lov = [c for c in self.catalog if c[0].upper().startswith(self.item_win["id"].upper())]
            return
        if self.to_list and k in ("up", "down"):
            d = datetime.strptime(self.to_list, "%y%m%d") + timedelta(days=1 if k == "down" else -1)
            self.to_list = d.strftime("%y%m%d")
        elif self.to_list and k == "enter":
            self.to = self.to if self.to_stuck else self.to_list
            self.to_list = None
            self.page = 0
        elif k == "enter":
            self.sched = self.want_sched if getattr(self, "want_sched", None) else self.sched
        elif k == "pageup":
            self.page = max(0, self.page - 1)
        elif k == "pagedown":
            if (self.page + 1) * 15 < len(self.upto()):
                self.page += 1
        elif k == "escape":
            self.list = None


TO_BOX = (758, 523, 80, 23)
TRAILERS = ("NR_BULK_SKIP", "NR_ARTIC_FL", "NR_FLAT_RIG")
TYPE_CODES = ("EMERGENCY", "Emergency", "NEXT DAY", "STANDARD")      # as CTMS sorts the Delivery Types list
TRAILER_AT, ALT_AT = (1088, 387, 290, 23), (853, 463, 254, 29)        # the carrier screen's drop-downs, as first read
LIST_X, LIST_Y, LIST_W = 853, 309, 239                                # where an opened one's list sits
SELECT_AT, EXIT_AT = (700, 470, 129, 31), (834, 470, 120, 31)         # nowhere the old fixed points were
CREATE_AT, CANCEL_AT = (600, 700, 146, 30), (600, 731, 146, 30)
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


NEW_ORDER = (1493, 447)


def test_closing_planned_orders_uses_where_it_really_sits_never_the_new_order_button():
    ctms = FakeCtms([_row("9100001-1-1"), _row("9100001-2-1")])
    job = _book(ctms)
    assert job.trips[0]["status"] == "ACCEPTED" and ctms.card is None and ctms.panel is None
    assert not [s for s in ctms.steps if tuple(s.get("px") or ()) == NEW_ORDER]


def test_a_panel_that_wont_close_stops_before_accepted():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.panel_stuck = True
    try:
        _book(ctms)
        raise AssertionError("it went on")
    except B.Stop as e:
        assert "wouldn't close" in str(e)
    assert ctms.tree["MAN-01000100"] == "PLANNED"


def test_a_carrier_window_left_behind_is_left_there_and_the_window_menu_never_opened():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.carrier_behind = True
    job = _book(ctms)
    assert job.trips[0]["status"] == "ACCEPTED"
    assert not [s for s in ctms.steps if s.get("name") == "wn-carrier" or s.get("px") == [386, 37]]
    assert ctms.carrier_behind


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


def test_a_sort_ctms_already_put_back_isnt_turned_round_again():
    ctms = FakeCtms([_row("9000200-1-1", "03/11/26 08:00")] + [_row(f"90000{i:02d}-1-1", "05/11/26 08:00") for i in range(40)] + [_row("9100001-1-1")])
    job = _book(ctms, dry=True)
    assert job.flipped is True
    ctms.reversed = False                # the carrier screen did it
    job.tidy()
    assert ctms.reversed is False and job.flipped is False


def test_the_hunt_stops_at_a_page_already_before_the_day():
    ctms = FakeCtms([_row(f"90000{i:03d}-1-1", "03/11/26 08:00") for i in range(200)])
    try:
        _book(ctms)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "isn't in CTMS for 06/11/2026 at all" in str(e)        # Order Summary asked once the hunt gave up
    assert sum(1 for s in ctms.steps if s.get("key") == "pagedown") < 15


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


def _missing(summary, filters=None, clears=True):
    """An order the well won't show: Order Summary's lines for it, and the well's filters as he has them."""
    ctms = FakeCtms([_row("9000001-1-1")])
    job = _job(ctms)
    job.summary_lines = lambda orders: [dict(r) for r in summary]
    asked = []

    def clear():
        asked.append("cleared")
        if filters and clears:
            ctms.well.append(_row("9100001-1-1"))                     # the filter off, the line shows
            job.filters_was = {"Advanced Order Filters": dict(filters)}
            return True
        return False
    job.clear_filters = clear
    return ctms, job, asked


def _summary(status, day="06/11/26 08:30"):
    return [{"ref": "9100001-1-1", "status": status, "deliver_by": day, "schedule": "261106"}]


def test_an_order_order_summary_hasnt_got_says_its_not_in_ctms_yet():
    ctms, job, asked = _missing([])
    try:
        job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "isn't in CTMS for 06/11/2026 at all" in str(e) and asked == []


def test_an_order_already_scheduled_says_its_booked_and_touches_no_filter():
    ctms, job, asked = _missing(_summary("SCHEDULED"))
    try:
        job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "booked in already on 06/11/2026 (CTMS: SCHEDULED)" in str(e) and asked == []


def test_an_unscheduled_order_the_well_hides_has_its_filters_cleared_and_is_booked():
    ctms, job, asked = _missing(_summary("UNSCHEDULED"), filters={"Business Type": "Strategy 2"})
    job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1)
    assert asked == ["cleared"] and job.trips[0]["status"] == "ACCEPTED"


def test_an_unscheduled_order_with_no_filter_on_says_so():
    ctms, job, asked = _missing(_summary("UNSCHEDULED"))
    try:
        job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "won't show it even with its filters as a clean well has them" in str(e) and asked == ["cleared"]


def _lines(n, order="9100001"):
    return [f"{order}-{i}-1" for i in range(1, n + 1)]


def test_seven_lines_side_by_side_go_on_one_manifest_selected_in_one_go():
    ctms = FakeCtms([_row(r) for r in _lines(7)])
    job = _book(ctms)
    assert ctms.trip_lines["MAN-01000100"] == _lines(7)
    assert job.trips[0]["lines"] == _lines(7) and job.trips[0]["took"] == 7 and job.trips[0]["status"] == "ACCEPTED"
    held = [s for s in ctms.steps if s.get("hold")]
    assert [s["hold"] for s in held] == [["shift"]]               # first row clicked, Shift-click on the last
    menu = next(i for i, s in enumerate(ctms.steps) if s.get("name") == "wm-create-trip")
    plain = [i for i, s in enumerate(ctms.steps) if s["action"] == "click" and s.get("screen") and not s.get("hold") and not s.get("right")]
    assert not [i for i in plain if ctms.steps.index(held[0]) < i < menu]     # nothing plain after, to lose the selection
    assert not any(s.get("name") == "wm-apply-trip" for s in ctms.steps)


def test_other_orders_between_the_lines_are_ctrl_clicked_round():
    well = [_row("9100001-1-1"), _row("9100002-1-1"), _row("9100001-2-1"), _row("9100001-3-1")]
    ctms = FakeCtms(well)
    _book(ctms)
    assert ctms.trip_lines["MAN-01000100"] == _lines(3)
    assert [s["hold"] for s in ctms.steps if s.get("hold")] == [["ctrl"], ["ctrl"]]
    assert [r["cust_ref"] for r in ctms.well] == ["9100002-1-1"]


def test_lines_ctms_wouldnt_take_from_the_selection_go_on_by_apply_to_trip():
    ctms = FakeCtms([_row(r) for r in _lines(3)])
    ctms.honours_selecting = False
    job = _book(ctms)
    assert sorted(ctms.trip_lines["MAN-01000100"]) == _lines(3)
    assert sum(1 for s in ctms.steps if s.get("name") == "wm-apply-trip") == 2
    assert job.trips[0]["took"] == 1 and job.trips[0]["status"] == "ACCEPTED"


def test_lines_a_page_apart_are_picked_up_by_apply_to_trip():
    well = [_row(f"9100009-{i}-1") for i in range(1, 15)] + [_row("9100001-1-1"), _row("9100001-2-1")]
    ctms = FakeCtms(well)
    job = _book(ctms)
    assert ctms.trip_lines["MAN-01000100"] == _lines(2) and job.trips[0]["status"] == "ACCEPTED"
    assert not [s for s in ctms.steps if s.get("hold")]


def test_a_line_that_isnt_ours_on_the_manifest_stops_it_before_accepted():
    ctms = FakeCtms([_row(r) for r in _lines(2)] + [_row("9100002-1-1")])
    real = ctms.click

    def stray(s):
        real(s)
        if s.get("screen") == [YES_AT[0] + 20, YES_AT[1] + 10]:
            ctms.trip_lines[ctms.selected].append("9100002-1-1")

    ctms.click = stray
    job = _job(ctms)
    try:
        job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1)
        raise AssertionError("it went on")
    except B.Stop as e:
        assert "9100002-1-1" in str(e) and "still PLANNED" in str(e)
    assert ctms.tree["MAN-01000100"] == "PLANNED"


def test_a_dry_run_selects_them_all_and_says_no():
    ctms = FakeCtms([_row(r) for r in _lines(7)])
    job = _book(ctms, dry=True)
    assert job.trips[0]["picked"] == 7 and job.trips[0]["status"] == "rehearsed"
    assert not ctms.tree and len(ctms.well) == 7


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
    assert ctms.card is None and ctms.type_set == "EMERGENCY" and ctms.types is None   # picked off the list by name


def test_a_delivery_types_list_whose_top_row_isnt_the_code_is_cancelled_and_the_card_left_unsaved():
    ctms = FakeCtms([_row("9100001-1-1", "03/11/26 08:00")])
    ctms.type_list = ["Emergency", "EMERGENCY", "NEXT DAY", "STANDARD"]    # the look-alike on top
    try:
        _book(ctms, date="03/11/2026")
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "gave Emergency for EMERGENCY" in str(e) and "left unsaved" in str(e)
    assert ctms.types is None and ctms.type_set is None and ctms.card is None
    assert "<order saved>" not in ctms.typed and ctms.tree == {}


def test_the_carrier_screen_and_payment_box_are_worked_where_ctms_puts_them_by_their_names():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.shift = (-300, 260)                       # CTMS's window another size: both boxes somewhere else (his 11/11)
    job = _book(ctms, carrier="DELTA_DH")
    assert job.trips[0]["status"] == "ACCEPTED" and job.trips[0]["carrier"] == "DELTA_DH"
    assert ctms.trailer_picked == "NR_ARTIC_FL"
    pressed = [s["screen"] for s in ctms.steps if s.get("action") == "click" and s.get("screen")]
    assert [SELECT_AT[0] - 300 + 64, SELECT_AT[1] + 260 + 15] in pressed      # Select Carrier, where it was read
    assert [CREATE_AT[0] - 300 + 73, CREATE_AT[1] + 260 + 15] in pressed      # and the payment box's Create Trip


def test_a_dry_run_backs_out_of_the_boxes_by_their_names_wherever_they_sit():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.shift = (-300, 260)
    job = _book(ctms, dry=True)
    assert job.trips[0]["status"] == "rehearsed" and ctms.up is None and ctms.tree == {}


def test_the_split_window_is_worked_by_its_names_wherever_it_opens():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.split_up = True                           # Order Summary's Split Orders pressed
    _job(ctms).split_into("9100001-1-1", 2)
    assert ctms.split_typed == "2" and ctms.split_done and not ctms.split_up and not ctms.alert


def test_a_split_window_without_its_named_buttons_stops_saying_what_it_has():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.split_up, ctms.split_names = True, ("Go", "Close")
    try:
        _job(ctms).split_into("9100001-1-1", 2)
        raise AssertionError("should have stopped")
    except B.Stop as e:
        assert "its buttons: Go, Close" in str(e) and "nothing was split" in str(e)
    assert not ctms.split_done and ctms.split_typed == ""


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


# -- his line checks before the trip (03/11): Order Items' product the Detail tab's, the quantity the order's
def test_an_item_on_the_wrong_product_is_put_right_through_ctrl_l_taking_the_top_choice():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.line_info["9100001-1-1"] = {"product": "WHEELSETS", "qty": 16, "items": [{"id": "S&C", "ordered": 16}]}
    job = _book(ctms)
    assert ctms.saves == [("item", "9100001-1-1", "WHEELSETS", 16)]        # the top of WHEELSETS / WHEELSET_AXLE
    assert "<order saved>" in ctms.typed and job.trips[0]["status"] == "ACCEPTED"
    assert "9100001-1-1: item S&C put right to WHEELSETS" in job.said


def test_a_quantity_not_the_orders_is_put_right_in_both_places():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.line_info["9100001-1-1"] = {"product": "S&C", "qty": 15, "items": [{"id": "S&C", "ordered": 14}]}
    job = _job(ctms)
    job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1, qty={"9100001": 16})
    assert ("item", "9100001-1-1", "S&C", 16.0) in ctms.saves and ("card", "9100001-1-1", 16.0) in ctms.saves
    assert ctms.weights == [""]         # cleared, so CTMS works it out from the new quantity (his rule, 03/11)
    assert ctms.line_info["9100001-1-1"]["qty"] == 16 and job.trips[0]["status"] == "ACCEPTED"


def test_a_line_already_right_is_closed_unsaved_and_booked():
    ctms = FakeCtms([_row("9100001-1-1")])
    job = _job(ctms)
    job.book(["9100001"], "06/11/2026", "DHL_NOC", "NR_ARTIC_FL", None, 1, qty={"9100001": 1})
    assert ctms.saves == [] and "<order saved>" not in ctms.typed and job.trips[0]["status"] == "ACCEPTED"


def test_quantities_that_disagree_with_no_order_figure_stop_and_ask_before_anything_is_typed():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.line_info["9100001-1-1"] = {"product": "S&C", "qty": 16, "items": [{"id": "S&C", "ordered": 15}]}
    try:
        _book(ctms)
        raise AssertionError("it went on")
    except B.Stop as e:
        assert "Detail tab says 16 and Order Items says 15" in str(e) and "Nothing was booked" in str(e)
    assert ctms.saves == [] and ctms.tree == {} and ctms.card is None


def test_a_product_ctrl_l_cant_find_stops_with_nothing_saved():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.line_info["9100001-1-1"] = {"product": "RAILS", "qty": 1, "items": [{"id": "S&C", "ordered": 1}]}
    try:
        _book(ctms)
        raise AssertionError("it went on")
    except B.Stop as e:
        assert "no product item for RAILS" in str(e)
    assert ctms.saves == [] and ctms.tree == {}


def test_a_rehearsal_says_what_it_would_put_right_and_types_nothing_on_the_line():
    ctms = FakeCtms([_row("9100001-1-1")])
    ctms.line_info["9100001-1-1"] = {"product": "WHEELSETS", "qty": 16, "items": [{"id": "S&C", "ordered": 16}]}
    job = _book(ctms, dry=True)
    assert ctms.saves == [] and "<order saved>" not in ctms.typed
    assert "9100001-1-1: item S&C would be put right to WHEELSETS" in job.said


def test_a_question_nobody_asked_is_answered_ok_and_stops_the_booking():
    ctms = FakeCtms([_row("9100001-1-1")])
    real = ctms.read

    def alert(tree=True, skip=()):
        els = real(tree, skip)
        if ctms.reads > 2 and not getattr(ctms, "alert_gone", False):       # partway through: not one from before
            els = [{"r": "internal frame", "nm": "A schedule must be selected.", "lv": 0, "at": [790, 470, 310, 160]},
                   {"r": "option pane", "nm": "", "lv": 1, "at": [790, 490, 310, 140]},
                   {"r": "push button", "nm": "OK", "lv": 2, "at": [1025, 592, 62, 30]}] + els
        return els
    ctms.read = alert
    real_click = ctms.click

    def click(s):
        if s.get("screen") == [1056, 607]:
            ctms.alert_gone = True
        real_click(s)
    ctms.click = click
    try:
        _book(ctms)
        raise AssertionError("it went on")
    except B.Stop as e:
        assert '"A schedule must be selected."' in str(e) and "answered OK" in str(e)
    assert ctms.alert_gone and ctms.tree == {}


def test_each_line_of_a_several_line_order_is_checked_and_only_the_wrong_one_saved():
    ctms = FakeCtms([_row("9100001-1-1"), _row("9100001-2-1")])
    ctms.line_info["9100001-2-1"] = {"product": "WHEELSETS", "qty": 2, "items": [{"id": "WHEELSET_AXLE", "ordered": 2}]}
    job = _book(ctms)
    assert ctms.saves == [("item", "9100001-2-1", "WHEELSETS", 2)]
    assert job.trips[0]["status"] == "ACCEPTED" and sorted(job.trips[0]["lines"]) == ["9100001-1-1", "9100001-2-1"]


def test_the_orders_quantity_goes_to_its_line_only_when_it_has_just_one():
    assert B.line_wants(["9100001-1-1"], ["9100001"], {"9100001": 16}) == {"9100001-1-1": 16.0}
    assert B.line_wants(["9100001-1-1", "9100001-2-1"], ["9100001"], {"9100001": 16}) == {}
    assert B.line_wants(["FS-1-TNNG"], ["FS-1-TNNG"], {"FS-1-TNNG": 16}) == {"FS-1-TNNG": 16.0}


def _forms_notice(words):
    """A Forms notice the way it really comes (live 03/11): a window called "Forms", its words in the pane and a label."""
    return [{"r": "internal frame", "nm": "Forms", "lv": 0, "at": [20, 151, 428, 163]},
            {"r": "option pane", "nm": words, "lv": 1, "at": [23, 172, 422, 139]},
            {"r": "push button", "nm": "OK", "lv": 2, "at": [374, 272, 63, 31], "st": ["focused"]},
            {"r": "label", "nm": words, "lv": 2, "at": [127, 204, 310, 40]}]


def test_a_notice_already_up_before_the_booking_is_okd_said_and_gone_past():
    ctms = FakeCtms([_row("9100001-1-1")])
    real, real_click = ctms.read, ctms.click

    def read(tree=True, skip=()):
        notice = [] if getattr(ctms, "okd", False) else _forms_notice("FRM-92220: access to system clipboard denied")
        return notice + real(tree, skip)

    def click(s):
        if s.get("screen") == [374 + 31, 272 + 15]:
            ctms.okd = True
        real_click(s)
    ctms.read, ctms.click = read, click
    job = _book(ctms)
    assert ctms.okd and job.trips[0]["status"] == "ACCEPTED"
    assert job.said[0] == 'CTMS had "FRM-92220: access to system clipboard denied" up from before: OK\'d it'


def test_a_forms_questions_words_come_from_its_pane_when_its_window_is_just_forms():
    import ctms_rows
    assert ctms_rows.question(_forms_notice("FRM-1: no"))[0] == "FRM-1: no"
    framed = [{"r": "internal frame", "nm": "Change schedule to: 261106?", "lv": 0},
              {"r": "option pane", "nm": "", "lv": 1}, {"r": "push button", "nm": "OK", "lv": 2, "at": [1, 1, 5, 5]}]
    assert ctms_rows.question(framed)[0] == "Change schedule to: 261106?"
