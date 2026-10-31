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
before it is pressed: another CTMS window over it (his Order Filters, 31/10)
would take the click. Without his go-ahead (commit) it is a dry run:
everything up to Import, then the card closed.

Points are pixels of the work PC's own pictures of 29/10 (the window 1910 x
915); the templates were cut from those pictures - CTMS's own words only.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_import_templates.json")


def templates():
    with open(TEMPLATES, encoding="utf-8") as f:
        return json.load(f)


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
        # have landed in Order Filters
        _find(t, "imp-button", (340, 420, 480, 460), 2,
              why="Something is over the Import card's Import button - another CTMS window (Order Filters, say). "
                  "Close or move it, then Upload again."),
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
