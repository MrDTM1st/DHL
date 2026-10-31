"""
An upload CSV into CTMS in one go - the map's Upload button (31/10).

His ask: "in the map, instead of it saying download CSV, you just have an upload
button". So the bridge runs the whole import learned with him on 29/10 as one
job (ctms_bridge's import_csv):

  1. the CSV from the dashboard into Downloads - only ever adding
  2. Administration > File Interfaces > Imports; File Type NRHEAVY_Order_Import
     (the second line of its list)
  3. Input file: the CSV's whole path, typed - Browse opens a window outside
     CTMS
  4. Import, and CTMS's two questions answered Yes - each only once its own
     words are on the screen: "File must be on Server for import ... transfer
     the file?", then "Import file now?"
  5. the result kept as a picture: "N Lines processed successfully. 0 Lines
     failed processing. 0 Lines of invalid data encountered." - clean is both
     noughts showing
  6. OK, and the Import card's Close

Each step waits for CTMS to answer, and the run stops - touching nothing more -
at anything not on the screen where it should be. Stopped before Import, it
closes the card it opened (its Close seen first). The Import button is seen
before it is pressed: another CTMS window over it would take the click. His
Order Filters panel sat right over it on 31/10, so that one is closed by its
own X before the card opens - his word: "If you see it there, close it" -
and left alone when it is parked out of the way. Without his go-ahead
(commit) it is a dry run: everything up to Import, then the card closed.

Points are pixels of the work PC's own pictures of 29/10 (the window 1910 x
915); the templates were cut from those pictures - CTMS's own words only -
and Order Filters' from those of 31/10.
"""
import base64
import json
import os

import ctms_fast

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_import_templates.json")

# Order Filters is in the way when any of it is over the Import card (about 15-1105 x 55-815) or CTMS's questions
# (790-1180 x 370-545). Found by its title's "der Filters" - top left 23,398 in its usual spot, bottom left - the
# panel reaches 36 px left of that (its icon and "Or") and about 450 px down: a title left of 1220 and above 820
# is in the way.
IN_THE_WAY = (1220, 820)
# its X: as drawn with the panel behind, in front, and in front with the pointer resting on it (a box round it)
OF_XS = ("of-x", "of-x-on", "of-x-on-hot")


def templates():
    with open(TEMPLATES, encoding="utf-8") as f:
        return json.load(f)


def _tpl(t, name):
    tp = t[name]
    return ctms_fast.rgb_to_bgra(base64.b64decode(tp["rgb"]), tp["w"], tp["h"]), tp["w"], tp["h"]


def order_filters(bgra, w, h, t):
    """Where Order Filters' title is on the picture, in either look (the panel in front or not) - None when the
    panel is not open."""
    for look in ("of-title", "of-title-on"):
        tpl, tw, th = _tpl(t, look)
        hit = ctms_fast.find(bgra, w, h, (0, 0, w, h), tpl, tw, th)
        if hit:
            return hit
    return None


def order_filters_x(bgra, w, h, t, off=(0, 0)):
    """The middle of Order Filters' X on the picture when the panel is open in the way of the Import card; None when
    it is not open, or parked out of the way. Its X is looked for only along its title's row - CTMS's other windows
    have the very same X."""
    hit = order_filters(bgra, w, h, t)
    if not hit or hit[0] >= IN_THE_WAY[0] + off[0] or hit[1] >= IN_THE_WAY[1] + off[1]:
        return None
    for name in OF_XS:
        xt, xw, xh = _tpl(t, name)
        at = ctms_fast.find(bgra, w, h, (hit[0], hit[1] - 6, hit[0] + 600, hit[1] + 20), xt, xw, xh)
        if at:
            return at[0] + xw // 2, at[1] + xh // 2
    raise RuntimeError("Order Filters is over the Import card, but its X is not where it should be - close it "
                       "yourself, then Upload again.")


def _find(t, name, box, timeout, why=""):
    tp = t[name]
    step = {"action": "find", "name": name, "box": list(box), "tpl": tp["rgb"], "tw": tp["w"], "th": tp["h"],
            "timeout": timeout}
    if why:
        step["why"] = why                       # said instead of "not on the screen", should it not be found
    return step


def _click(x, y, **extra):
    return dict({"action": "click", "px": [x, y]}, **extra)


def open_and_type(path, t):
    """Up to the moment before Import: the card open, NRHEAVY_Order_Import chosen, the path typed."""
    return [
        {"action": "anchor"},
        _click(1000, 37, after=0.4),                    # a first click only gives CTMS's Java the focus
        _click(230, 37, react=True, box=[180, 45, 420, 200], quiet=0.2, timeout=5),     # Administration
        _click(231, 159, react=True, box=[330, 150, 430, 200], quiet=0.2, timeout=5),   # File Interfaces
        _click(362, 163, after=0.3),                                                     # Imports
        _find(t, "imp-card", (40, 205, 150, 245), 25),              # the Import card is up: its File Type
        _click(575, 226, react=True, box=[130, 235, 600, 420], quiet=0.2, timeout=5),   # File Type's list
        _click(217, 251, after=0.8),                                # NRHEAVY_Order_Import, its second line
        _click(357, 267, after=0.3),                                # Input file - File Type loses the focus,
        _find(t, "imp-nrheavy", (125, 210, 590, 245), 5),           # so its white box shows NRHEAVY plainly
        {"action": "key", "key": "home", "after": 0.05},
        {"action": "key", "key": "shift+end", "after": 0.05},       # all of the default c:\temp path
        {"action": "type", "text": path, "after": 0.3},
        {"action": "snap", "name": "path", "box": [55, 255, 680, 282]},
        # the Import button itself in view: on 31/10 his Order Filters panel sat over it, and a click there would
        # have landed in Order Filters - that one is closed first now, but any other CTMS window would do the same
        _find(t, "imp-button", (340, 420, 480, 460), 2,
              why="Something is over the Import card's Import button - another CTMS window. Close or move it, "
                  "then Upload again."),
    ]


def import_and_answer(t):
    """Import, CTMS's two questions, and its answer - kept as the "result" snap."""
    return [
        _click(405, 438, after=0.3),                                # Import
        _find(t, "imp-ask-server", (790, 395, 1180, 450), 30),      # "File must be on Server for import ..."
        _click(1069, 519, after=0.5),                               # Yes
        _find(t, "imp-ask-now", (880, 400, 1100, 470), 30),         # "Import file now?"
        _click(953, 505, after=0.5),                                # Yes
        _find(t, "imp-done", (850, 395, 1150, 445), 180),           # "N Lines processed successfully."
        {"action": "snap", "name": "result", "box": [815, 370, 1125, 545]},
    ]


def clean_checks(t):
    """The result's two noughts: each step fails when its line says anything else."""
    return [_find(t, "imp-failed-0", (850, 420, 1080, 465), 0), _find(t, "imp-invalid-0", (850, 440, 1140, 485), 0)]


def finish(t):
    return [_click(1074, 519, after=0.8)] + close_card(t)          # OK on CTMS's answer, then the card closed


def close_card(t):
    """The Import card's Close - pressed only once its own label is seen there (31/10: a stopped run closes the
    card it opened, so nothing is left over his work - and never clicks blind if the card is not up)."""
    return [_find(t, "imp-close", (980, 120, 1090, 160), 3), _click(1030, 139, after=1.2)]
