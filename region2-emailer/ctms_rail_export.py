"""
The rail plan's CTMS export in one go - his "where is the execute rail plan button on the dashboard" (01/11): the
Short Rail Report for a week exported from CTMS by the home PC driving it on the work PC (as ctms_run does), the file
taken from its tab by the bridge, which sends it on - the home PC then builds the plan from it as a PREVIEW in Files,
as it does every export. Sending stays his Build & send. The week: "next" is next Monday to Sunday, "current" this
one - the Rail plan card's choice.

  card      Administration > File Interfaces > Exports - or the Export card already up, taken as it is
  name      the Short Rail Report, picked from its list by its picture, unless the card shows it already
  schedule  Start, then End. A box already on a day starts from it; an empty one's list opens at its far end, so it
            is dragged to about this year, its rows read (ctms_digits) and a day in view clicked. Then the list is
            opened on that day and moved a day a key, and the highlighted row read before Enter
  cost      the Cost Centre list's only entry, unless the box has it - the box must not be empty
  product   SHORT_RAIL, found in its list by its picture - the box must show it
  check     both schedule boxes read back as the week, before Export is pressed
  export    Export; the bridge takes the file from the tab it opened (export-fetch, only a file made since the
            press) and closes the tab; then the card is closed

The first thing not as expected stops it, CTMS left as it is - nothing is ever saved by an export. Only after Export
does a stop tidy up: the export's tab closed (export-close), so CTMS shows again.

    python ctms_rail_export.py run next|current      prints a JSON line at the end: {"ok", "said", ...}
"""
import base64
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import ctms_digits

HERE = os.path.dirname(os.path.abspath(__file__))
# Points on the pictures of the Export card measured 31/10 (1910x915, the menu bar's bottom row at 50); each batch
# starts "anchor window", which moves them to wherever CTMS sits now.
MENU = ["click 230,37 react box=150,45,450,260 quiet=0.2 timeout=5",          # Administration
        "click 231,159 react box=230,140,560,260 quiet=0.2 timeout=5",        # File Interfaces
        "click 362,187 after=0.5"]                                            # Exports
CARD, CARD_BOX = "exp-card", "250,260,360,310"           # its Name label: the card is up
SRR, NAME_BOX, NAME_LIST = "exp-srr", "320,272,480,302", "320,120,560,272"
NAME_ARROW = "649,286"
EXPORT, CLOSE = "693,387", "693,417"
ASK, ASK_BOX, ASK_YES = "close-ask", "900,400,1090,470", "956,506"     # "Close this form?" - Yes
SR, PT_ARROW, PT_LIST, PT_BOX = "exp-short-rail", "730,598", "372,430,640,590", "372,586,640,614"
PT_UPS = 21                     # from the Product Type list's far end SHORT_RAIL is then in view (31/10)
CC_ARROW, CC_ITEM, CC_BOX = "730,565", "398,544", "376,558,540,572"
SNAP_X = 372                    # the left of every snap of a list or box: the codes' first cells sit 5 px in
CODE_X = 377
THUMB_X = 618
# Each schedule box: its list's arrow, where its code sits, the thumb's drags from an empty box (to the top of the
# track, then down to about this year - May 2026 on 31/10, later as days are added), and the band its list can show
# in, opened up from the box (empty) or down from it (on a day).
BOXES = {"start": {"label": "Start Schedule", "arrow": "634,498", "code_y": 493, "thumb": (489, 352, 354, 490),
                   "band": (330, 672)},
         "end": {"label": "End Schedule", "arrow": "634,531", "code_y": 526, "thumb": (522, 385, 387, 523),
                 "band": (363, 705)}}
KEY_PAUSE = 0.1                 # between a list's key presses - the read-back counts what CTMS did, not the keys
KEYS_A_BATCH = 100
SETTLE = "settle quiet=0.8 timeout=20"
FETCH_SLACK = 600               # seconds the export file's name may be behind the press (CTMS's clock)


class Failed(Exception):
    pass


def week_of(which, today=None):
    """(Monday, Sunday) of the week asked for: "current" the one today is in, "next" the one after."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7 if which == "next" else 0)
    return monday, monday + timedelta(days=6)


def pick(rows, want):
    """The row to click in a list read off its picture: the last day on or before `want` (the fewest keys down),
    else the first after it."""
    before = [r for r in rows if r[1] <= want]
    return before[-1] if before else rows[0]


def presses(n):
    """The keys that move a list n days: [[step, ...], ...] a batch each - [[]] for none."""
    keys = [f"key {'down' if n > 0 else 'up'} after={KEY_PAUSE:g}"] * abs(n)
    return [keys[i:i + KEYS_A_BATCH] for i in range(0, len(keys), KEYS_A_BATCH)] or [[]]


def ink(img):
    """Dark pixels in a picture of a box - its text. The box's own frame is lighter than this."""
    return sum(1 for y in range(img.height) for x in range(img.width) if max(img.getpixel((x, y))[:3]) < 128)


def _client():
    import ctms_run
    return ctms_run._client()


def _image(snap):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(snap.get("img") or ""))).convert("RGB")


def _steps(R, name, items):
    """One batch on the work PC, anchored to where CTMS sits -> {snap name: picture}; Failed where it stopped."""
    steps = R.parse_steps(["anchor", "anchor window"] + list(items))
    result, payload = R.ask("steps", wait_total=90 + 2 * len(steps), steps=steps)
    R.trace(f"rail-{name}", {"steps": len(steps)}, result, payload)
    if payload and payload.get("kind") == "window":
        R.save_state(payload)
    if not result.get("ok"):
        raise Failed(f"{name}: {result.get('detail')}")
    return {s.get("name"): _image(s) for s in (payload or {}).get("snaps") or []}


def _band(b):
    top, bottom = b["band"]
    return top, f"{SNAP_X},{top},{SNAP_X + 60},{bottom}"


def set_schedule(R, key, want):
    """One schedule box on `want`, read back off its list before Enter. Says what it did."""
    b = BOXES[key]
    top, band = _band(b)
    y = b["code_y"]
    shot = _steps(R, f"{key}-box", [f"snap box {SNAP_X},{y - 3},600,{y + 17}"])["box"]
    have = ctms_digits.read_box(shot, CODE_X - SNAP_X, 3)
    if have is None and ink(shot) > 20:
        raise Failed(f"the {b['label']} box shows something that doesn't read as a day - left as it is")
    how = f"from {have:%d/%m/%Y}, the day it was on" if have else ""
    if have is None:
        end, track_top, grab, land = b["thumb"]
        shot = _steps(R, f"{key}-find", [f"click {b['arrow']} after=1.0",
                                         f"drag {THUMB_X},{end} {THUMB_X},{track_top} after=0.8",
                                         f"drag {THUMB_X},{grab} {THUMB_X},{land} after=1.0",
                                         SETTLE, f"snap list {band}"])["list"]
        rows, _ = ctms_digits.read_list(shot, CODE_X - SNAP_X, want)
        if not rows:
            raise Failed(f"the {b['label']} list did not read as days near {want:%d/%m/%Y} - left open")
        row_y, have = pick(rows, want)
        _steps(R, f"{key}-pick", [f"click 470,{top + row_y + 5} after=1.2"])
        how = f"from {have:%d/%m/%Y}, clicked in its list"
    opened, sel = False, have
    for _ in range(4):
        chunks = presses((want - sel).days)
        for i, chunk in enumerate(chunks):
            items = ([] if opened else [f"click {b['arrow']} after=1.2"]) + chunk
            opened = True
            if i == len(chunks) - 1:
                items += [SETTLE, f"snap list {band}"]
            shots = _steps(R, f"{key}-keys", items)
        _, chosen = ctms_digits.read_list(shots["list"], CODE_X - SNAP_X, want)
        if chosen is None:
            raise Failed(f"the {b['label']} list's chosen day could not be read - left open, nothing set")
        sel = chosen[1]
        if sel == want:
            break
    else:
        raise Failed(f"the {b['label']} list would not come to {want:%d/%m/%Y} - it is on {sel:%d/%m/%Y}, left open")
    _steps(R, f"{key}-set", ["key enter after=1.2"])
    return f"{b['label']} {want:%d/%m/%Y} ({how})"


def set_product(R):
    if R._on_screen(SR, PT_BOX):
        return
    _steps(R, "product", [f"click {PT_ARROW} after=1.0"] + presses(-PT_UPS)[0] + [SETTLE])
    for more in (6, 6, None):
        if R._on_screen(SR, PT_LIST):
            break
        if more is None:
            raise Failed("SHORT_RAIL is not in view in the Product Type list where it was (31/10) - left open")
        _steps(R, "product", presses(-more)[0] + [SETTLE])
    _steps(R, "product", [f"find {SR} click box={PT_LIST} after=1.2", f"find {SR} box={PT_BOX} timeout=4"])


def close_card(R):
    """The Export card's Close - "Close this form?" answered Yes when it asks (it does with a box empty). Says
    whether it went."""
    _steps(R, "close", ["click 1000,37 after=0.4", f"click {CLOSE} after=1.5"])   # a first click only focuses Java
    if R._on_screen(ASK, ASK_BOX, timeout=1.0):
        _steps(R, "close", [f"click {ASK_YES} after=1.5"])
    return not R._on_screen(CARD, CARD_BOX)


def export(R, which, today=None, state=None):
    """The week's Short Rail Report exported and sent on for the preview -> what was done. Failed says where it
    stopped; state["exported"] is True from Export's press until its file is in hand."""
    state = {} if state is None else state
    monday, sunday = week_of(which, today)
    result, payload = R.ask("see", marks=False)          # the latest picture is a window's: points aim on it
    if not result.get("ok") or (payload or {}).get("kind") != "window":
        raise Failed(f"CTMS's window could not be seen: {result.get('detail')}")
    R.save_state(payload)
    _steps(R, "focus", ["click 1000,37 after=0.4"])     # a first click only gives Java the focus; shuts a list
    if not R._on_screen(CARD, CARD_BOX):
        _steps(R, "open", MENU + [f"find {CARD} box={CARD_BOX} timeout=15"])
    if not R._on_screen(SRR, NAME_BOX):
        _steps(R, "name", [f"click {NAME_ARROW} after=1.0", f"find {SRR} click box={NAME_LIST} timeout=4 after=2.0",
                           f"find {SRR} box={NAME_BOX} timeout=5"])
    said = [set_schedule(R, "start", monday), set_schedule(R, "end", sunday)]
    shot = _steps(R, "cost", [f"snap cc {CC_BOX}"])["cc"]
    if ink(shot) <= 20:
        shot = _steps(R, "cost", [f"click {CC_ARROW} after=1.0", f"click {CC_ITEM} after=1.2", f"snap cc {CC_BOX}"])["cc"]
        if ink(shot) <= 20:
            raise Failed("the Cost Centre box is still empty after its list's entry was clicked")
    set_product(R)
    shots = _steps(R, "check", [f"find {SRR} box={NAME_BOX}", f"find {SR} box={PT_BOX}",
                                f"snap start {SNAP_X},{BOXES['start']['code_y'] - 3},600,{BOXES['start']['code_y'] + 17}",
                                f"snap end {SNAP_X},{BOXES['end']['code_y'] - 3},600,{BOXES['end']['code_y'] + 17}",
                                f"snap cc {CC_BOX}"])
    got = (ctms_digits.read_box(shots["start"], CODE_X - SNAP_X, 3), ctms_digits.read_box(shots["end"], CODE_X - SNAP_X, 3))
    if got != (monday, sunday):
        seen = " to ".join(f"{d:%d/%m/%Y}" if d else "nothing readable" for d in got)
        raise Failed(f"before Export, the schedule boxes read {seen} - not {monday:%d/%m/%Y} to {sunday:%d/%m/%Y}")
    if ink(shots["cc"]) <= 20:
        raise Failed("before Export, the Cost Centre box is empty")
    pressed = datetime.now()
    state["exported"] = True
    _steps(R, "export", [f"click {EXPORT} after=2.0"])
    since = (pressed - timedelta(seconds=FETCH_SLACK)).strftime("%Y-%m-%d_%H%M%S")
    result, payload = R.ask("export_fetch", wait_total=180, since=since)
    R.trace("rail-export-fetch", {"since": since}, result, payload)
    if not result.get("ok"):
        raise Failed(f"the export's file: {result.get('detail')}")
    name, rows = str((payload or {}).get("name") or ""), (payload or {}).get("rows")
    stamp = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{6})", name)
    made = datetime.strptime("".join(stamp.groups()), "%Y-%m-%d%H%M%S") if stamp else None
    if not (name.startswith("short_rail_rep_") and made and abs((made - pressed).total_seconds()) <= FETCH_SLACK):
        raise Failed(f"the file the bridge took ({name or 'no name'}) is not the export just made")
    state["exported"] = False            # the file is in hand and its tab closed: nothing left to tidy
    try:
        closed = close_card(R)
    except Exception:
        closed = False
    return {"week": f"{monday:%d/%m/%Y}-{sunday:%d/%m/%Y}", "file": name, "rows": rows,
            "said": (f"Exported the Short Rail Report for {monday:%d/%m} to {sunday:%d/%m} from CTMS - {name}, "
                     f"{rows} row(s); its plan is being previewed into Files (nothing sent). "
                     + "; ".join(said) + ". " + ("Export card closed." if closed else
                                                 "The Export card did not close - close it yourself."))}


def run(which, today=None):
    if which not in ("next", "current"):
        return {"ok": False, "said": f"which week - next or current, not '{which}'"}
    monday, sunday = week_of(which, today)
    out = {"week": f"{monday:%d/%m/%Y}-{sunday:%d/%m/%Y}"}
    R, state = None, {"exported": False}
    try:
        R = _client()
        out.update(export(R, which, today, state), ok=True)
        return out
    except Exception as e:                 # Failed, the client's own Stop, a lost connection
        why = str(e) if isinstance(e, Failed) else f"{type(e).__name__}: {e}"
        tidy = ""
        if R is not None and state["exported"]:
            try:
                result, _ = R.ask("export_close", wait_total=120)
                tidy = f" After Export: {result.get('detail')}"
            except Exception as e2:
                tidy = f" After Export, its tab could not be closed ({e2}) - close it yourself."
        out.update(ok=False, said=f"Not exported - stopped at {why}.{tidy} Nothing was emailed.")
        return out


def main(argv):
    if len(argv) != 3 or argv[1] != "run":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = run(argv[2])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
