"""
CTMS's schedule codes read off its picture - for the Short Rail Report export's Start and End Schedule lists, which
nothing else can read: the Access Bridge drowns in their tens of thousands of entries (one a day back to 1963), and
the list jumps to its top when typed into.

CTMS draws a code like 261102 in fixed 8-pixel cells, and every copy of a digit is the same pixels wherever it is
drawn (checked 01/11 on seven rows: 0-9 identical in every row and cell), so each cell is matched exactly against
the ten digits in ctms_digits.json. A code carries no century - the junk rows at the far end of the list (2147,
2303 ...) read as 47xxxx, 03xxxx - so a code is only trusted inside a run of rows that read as consecutive days.

The schedule boxes draw their day the same way (white behind it), so a box reads back once its list is shut. The
list's chosen row is white on blue and reads as nothing - its day is the one its place among the others puts on it.
"""
import base64
import json
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "ctms_digits.json")
HIGHLIGHT = (0, 0, 255)            # the chosen row's ground, from a pixel left of its code to the list's edge (31/10)
_CACHE = {}


def load():
    """(cell width, cell height, pitch, {raw RGB cell bytes: digit})."""
    if "t" not in _CACHE:
        with open(TEMPLATES, encoding="utf-8") as f:
            t = json.load(f)
        cw, ch = t["cell"]
        _CACHE["t"] = (cw, ch, t["pitch"], {base64.b64decode(v): d for d, v in t["digits"].items()})
    return _CACHE["t"]


def _cell(px, x0, y0, cw, ch):
    return bytes(v for j in range(ch) for i in range(cw) for v in px[x0 + i, y0 + j][:3])


def read_code(img, x, y, n=6):
    """The n cells from x,y read as digits - '?' for a cell that is not one. img: a PIL RGB image."""
    cw, ch, pitch, by_cell = load()
    px = img.load()
    return "".join(by_cell.get(_cell(px, x + pitch * k, y, cw, ch), "?") for k in range(n))


def code_date(code):
    """The day a 6-digit code names, in this century - None when it isn't one."""
    if len(code) != 6 or not code.isdigit():
        return None
    try:
        return date(2000 + int(code[:2]), int(code[2:4]), int(code[4:]))
    except ValueError:
        return None


def code_of(day):
    return f"{day:%y%m%d}"


def read_rows(img, x, y0, row_pitch, rows):
    """Every row's code, top first."""
    return [read_code(img, x, y0 + row_pitch * r) for r in range(rows)]


def day_run(codes, near, slack=400):
    """The rows that read as consecutive days within `slack` days of `near` - [(row index, day)] - or [] when no two
    rows do. Junk rows never pass: they are years apart, not a day."""
    days = [code_date(c) for c in codes]
    best, cur = [], []
    for i, d in enumerate(days):
        ok = d is not None and abs((d - near).days) <= slack
        if ok and cur and d == cur[-1][1] + timedelta(days=1):
            cur.append((i, d))
        elif ok:
            cur = [(i, d)]
        else:
            cur = []
        if len(cur) > len(best):
            best = list(cur)
    return best if len(best) >= 2 else []


def read_box(img, x, y):
    """The day a schedule box shows, its code's first cell at x,y - None when it shows none (or the box is open)."""
    return code_date(read_code(img, x, y))


def _scan(img, x, near, slack):
    """[(y, day)] for every height in the picture where a whole code near `near` starts at x."""
    cw, ch, pitch, by_cell = load()
    px = img.load()
    out = []
    for y in range(0, img.height - ch + 1):
        if _cell(px, x, y, cw, ch) not in by_cell:          # the first cell decides most heights
            continue
        d = code_date(read_code(img, x, y))
        if d is not None and abs((d - near).days) <= slack:
            out.append((y, d))
    return out


def _chosen(img, x, y):
    px = img.load()
    return all(0 <= yy < img.height and px[x - 1, yy][:3] == HIGHLIGHT for yy in (y - 4, y + 12))


def read_list(img, x, near, pitch=22, slack=400):
    """An open schedule list, from a picture of it (the codes' first cells at x) -> (rows, chosen).

    rows: [(y, day)] the rows that read as consecutive days within `slack` days of `near`, top first - the most on
    one row grid, so a box showing its day beside the list (off the grid) and junk rows (years away) never count;
    [] when fewer than two rows do. chosen: (y, day) of the one highlighted row on that grid, its day the one its
    place among the rows puts on it - None when no row (or more than one) is highlighted."""
    hits = _scan(img, x, near, slack)
    rows = []
    for y0, d0 in hits:
        run = [(y, d) for y, d in hits if (y - y0) % pitch == 0 and (d - d0).days == (y - y0) // pitch]
        if len(run) > len(rows):
            rows = run
    if len(rows) < 2:
        return [], None
    y0, d0 = rows[0]
    lit = [(y, d0 + timedelta(days=(y - y0) // pitch)) for y in range(y0 % pitch, img.height, pitch)
           if _chosen(img, x, y)]
    return rows, (lit[0] if len(lit) == 1 else None)
