"""Fast steps in CTMS's own window: where its screen sits now, and waiting on the screen instead of the clock.

A batch of steps used to run on fixed sleeps (0.4 s after every click, plus waits padded in to be safe) at fixed
places on the picture - so a page scrolled 21 px (30/10) sent the Orders menu clicks into Planning's Find box, and a
booking took about thirty round trips with Claude reading a picture between each. These are the pieces a batch needs
to run a whole job on the work PC by itself:

  anchor         where CTMS's menu bar is now, against the pictures the recipes were measured on - every point
                 after it in the batch moves by the difference
  react          a click or key that waits for CTMS to answer: a watched box changes, then the screen holds still
  waitfor/check  a pixel's colour, waited for or required, so a recipe knows the window it expects is up
  snap           a small picture of part of the screen kept for the answer - a checkpoint without a picture per step

Pure functions over BGRA pixels - the bridge does the capturing and clicking. Standard library only, like the rest
of the bridge (nothing gets installed on the work PC).
"""

MENU_GREY = (102, 102, 102)
CANON_MENU_BOTTOM = 50      # the menu bar's last row on the pictures every recipe was measured on (29-30/10)
CANON_MENU_LEFT = 15        # and its first column
BLOCK_W, BLOCK_H = 40, 20   # the screen is compared in blocks this size
QUIET_BLOCKS = 2            # a blinking caret changes a block or two - more than that is CTMS answering


def rgb_at(bgra, w, x, y):
    """(r, g, b) of one pixel of a BGRA picture w pixels wide."""
    i = (int(y) * w + int(x)) * 4
    return bgra[i + 2], bgra[i + 1], bgra[i]


def near(c, want, tol):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(c, want))


def parse_color(text):
    """(r, g, b) from '#RRGGBB'."""
    s = str(text or "").strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"'{text}' is not a colour - write it #RRGGBB.")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def hex_color(c):
    return "#%02X%02X%02X" % tuple(c)


def anchor(bgra, w, h):
    """(dx, dy): how far CTMS's screen sits from where the recipes were measured, read off the bottom edge and
    left end of its grey menu bar - or None when the bar is not on the picture (the page scrolled past it, or
    something drawn over it). Only the bottom edge is used: scrolled down, the bar's top goes off the picture."""
    for x in (600, 900, 300, 1200):
        if x >= w:
            continue
        run, bottom = 0, None
        for y in range(min(h, 200)):
            if near(rgb_at(bgra, w, x, y), MENU_GREY, 6):
                run += 1
            elif run >= 5:
                bottom = y - 1
                break
            else:
                run = 0
        if bottom is None:
            continue
        row = max(0, bottom - 3)
        left = next((c for c in range(min(w, 400)) if near(rgb_at(bgra, w, c, row), MENU_GREY, 6)), None)
        if left is not None:
            return left - CANON_MENU_LEFT, bottom - CANON_MENU_BOTTOM
    return None


TITLE_TEALS = ((54, 76, 76), (120, 186, 186))   # a window's title bar in CTMS, active and not
CANON_TITLE_GAP = 25        # its last row, counted from the menu bar's last row, when CTMS's own area is not scrolled


def window_offset(bgra, w, h, menu_bottom):
    """How far CTMS's own window area has scrolled - its windows move together inside it, the menu bar does not
    (30/10: the area scrolled 8 px while the page did not, and the Services tab click missed). Read off the last
    title-bar row under the menu bar - the title bar ends where the window's red band or grey border starts (a
    button's teal edge further down is not it, 30/10); 0 when no title bar shows there."""
    x = 600 if w > 600 else w // 2
    last = None
    for y in range(max(0, menu_bottom + 1), min(h, menu_bottom + 45)):
        c = rgb_at(bgra, w, x, y)
        if any(near(c, t, 8) for t in TITLE_TEALS):
            last = y
        elif last is not None and (near(c, (202, 2, 2), 30) or near(c, (225, 225, 225), 4)):
            break
    return 0 if last is None else (last - menu_bottom) - CANON_TITLE_GAP


def _opaque(data):
    """The same pixels with every alpha byte 255: a picture straight from the window and one read off a PNG can
    disagree on alpha, never on colour."""
    b = bytearray(data)
    b[3::4] = b"\xff" * (len(b) // 4)
    return bytes(b)


def rgb_to_bgra(rgb, w, h):
    """BGRA bytes from RGB bytes (the way a template travels: three bytes a pixel)."""
    if len(rgb) != w * h * 3:
        raise ValueError("The picture's size does not match its pixels.")
    out = bytearray(w * h * 4)
    out[0::4], out[1::4], out[2::4] = rgb[2::3], rgb[1::3], rgb[0::3]
    out[3::4] = b"\xff" * (w * h)
    return bytes(out)


def find(bgra, w, h, box, tpl, tw, th):
    """Where an exact small picture (tpl: BGRA, tw x th) sits inside box (x0, y0, x1, y1) of the window's picture -
    the top left of the first match, or None. CTMS draws its words in one font, so a list item or a label looks
    the same pixel for pixel every time it is drawn on the same background: an exact match is a reliable 'find
    this text'. The search runs on the template's busiest row, so a blank first row does not match everywhere."""
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 - x0 < tw or y1 - y0 < th or len(tpl) != tw * th * 4:
        return None
    tpl = _opaque(tpl)
    rows = [tpl[r * tw * 4:(r + 1) * tw * 4] for r in range(th)]
    k = max(range(th), key=lambda r: len({rows[r][i:i + 4] for i in range(0, tw * 4, 4)}))
    stride = w * 4
    region = [_opaque(bgra[y * stride + x0 * 4:y * stride + x1 * 4]) for y in range(y0, y1)]
    for ry in range(k, (y1 - y0) - (th - 1 - k)):
        line, start = region[ry], 0
        while True:
            i = line.find(rows[k], start)
            if i < 0:
                break
            top = ry - k
            if i % 4 == 0 and all(region[top + r][i:i + tw * 4] == rows[r] for r in range(th)):
                return x0 + i // 4, y0 + top
            start = i + 1
    return None


def changed(a, b, w, h, box=None):
    """How many BLOCK_W x BLOCK_H blocks differ between two pictures of the same size, inside box
    (x0, y0, x1, y1) - the whole picture when box is None. Rows that match are skipped whole, so a screen
    that barely moved costs next to nothing to compare."""
    if len(a) != len(b):
        return 10 ** 6
    x0, y0, x1, y1 = box or (0, 0, w, h)
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
    if x1 <= x0 or y1 <= y0:
        return 0
    ma, mb, stride = memoryview(a), memoryview(b), w * 4
    blocks = set()
    for y in range(y0, y1):
        s, e = y * stride + x0 * 4, y * stride + x1 * 4
        if ma[s:e] == mb[s:e]:
            continue
        for bx in range(x0, x1, BLOCK_W):
            bs, be = y * stride + bx * 4, y * stride + min(x1, bx + BLOCK_W) * 4
            if ma[bs:be] != mb[bs:be]:
                blocks.add(((y - y0) // BLOCK_H, (bx - x0) // BLOCK_W))
    return len(blocks)


def shift_box(box, off):
    """A box measured on the recipes' pictures, moved to where CTMS sits now."""
    dx, dy = off
    return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
