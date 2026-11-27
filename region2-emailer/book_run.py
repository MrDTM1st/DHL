"""
The order panel's Book, the home PC's part (his design 02/11: "book with who?", the price if it's a tier 2, "and then you
just book it in"). Every click in CTMS happens on the WORK PC (work_pc/ctms_book.py, one command to its bridge). What
follows from here:

  1. first: anything on the CTMS to-do that has to go on before the booking stops it - "if you do it after we book it,
     we'd have to then unbook it and then put it back on"
  2. the booking itself, on the work PC
  3. a *_DH carrier's row on the DigiHaul Job Tracker: next empty row, yellow cells only (his 02/11: "if the haulier is with
     DH, the manifest number and stuff has to go on that Excel sheet"), each row looked at first - a colleague's can be
     half typed, with the manifest still empty
  4. the site's email: the manifest and the delivery's start and end times (his rule, every booking) - Reply All on the
     order's site thread, an ad hoc's request forwarded so its sheet stays attached, never a price. Nothing to the other
     hauliers or NOC: "We just let the delivery site know. The hauliers already know." Parcel Pass is the one that hears:
     the manifest and the job on its own quote's thread, and no asking for an ETA (his 03/11)
  5. the order off the map, its chain filed

A stop at any point says what was done so far. Past the booking nothing undoes it: what couldn't be done is said, for him
to do by hand. Stop pressed on the dashboard during the booking (16/11) ends it before its next trip: what CTMS made is
kept, but nothing follows it by itself - no row, no email, still on the map - and the rest isn't booked till CTMS has
been looked at and the job cleared on the Bookings card.

    python book_run.py run '{"record": "...", "orders": ["..."], "date": "dd/mm/yyyy", "carrier": "...", "trailer": "...",
                             "haulier": "...", "haulage": 450, "vehicles": 1, "dry": false}'
    python book_run.py batch '[{job}, ...]' [--run N]   Book approved: each in turn, stopping where CTMS needs a look
    python book_run.py retry             the timer: lost answers looked for, Outlook's failed steps tried again
    python book_run.py clear KEY [STEP]  his Done by hand / Clear

Every press goes through the booking journal (book_journal.py) first: an order it has booked is never booked again - a
press finishes what is left instead - and an answer the home PC gave up waiting for is asked for again by its id.

Prints what it does and, last, one line of JSON for the agent: {"ok", "said", "trips", "seconds", ...}.
"""
import contextlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1f1f1f;"
PLANNER = "Delali"
NOC = "DHL_NOC"
BLOCKS = ("update", "booking")     # what has to go on before a booking; a note can follow it

# The DigiHaul tracker as the work PC shows it, on the picture (1910 x 915 since 02/11, 1709 x 1275 at times): the
# highlighted row number says which row the cursor is on, and the column headings above the rows where each column is -
# found on every picture, never kept from an earlier one. Column A's width changes under us (24/11 and 27/11: 65 px, then
# 16 px a booking later), and every column with it: B to G read where they had once sat took in the black borders between
# the cells, and every empty row read as written in ("no empty row where one should be").
GUTTER_X = 8
ROW_TOP, ROW_END = 358, 832
PICKED = (202, 234, 216)           # a highlighted row number or column heading
PARTING = ((224, 224, 224), (160, 216, 185))   # the 1-px line between two column headings; green-grey edging a highlighted one
PARTING_YS = (286, 303)            # the heading strip above and under its letters (they run across 289-300)
UNDERLINE_Y = 306                  # the strip's foot, clear of the Name Box's tooltip: the cursor's column(s) underlined dark green
INSET = 6                          # a cell's border, and the cursor's green frame on it, stay outside what is read in it
A_SHOWS = 10                       # column A's cell, plain white on the cursor's row between the row numbers and B: 16 px
                                   # at its narrowest (27/11). A view scrolled sideways shows no A (03/11: C first, after
                                   # a 4-px sliver)
B_LEFT_MAX = 230                   # column B starts after the row numbers and column A...
B_WIDE = (100, 400)                # ...and is a manifest's width: never A's, nor F's or G's
G_MIDDLE = 280                     # G's Y or N, in the middle of the column, is this far in from its left
SCROLLBAR, SHEET_FOOT = 20, 83     # what the page keeps on its right and under the rows, whatever the window's size (03-04/11)
NAME_BOX = [80, 250]               # Excel's Name Box, over column A's heading (seen 23/11)
SHEET_END = "B1048576"             # column B's last row: Ctrl+Up from it stops on the last manifest, wherever the view was
# What the keys typed for the Name Box changed, on the pictures before and after (the same at 1910 x 915 and 1709 x 1275):
# the Name Box's own text, and the formula bar with its X, tick and fx - which change only when a CELL is being typed in
NAME_AT = (12, 240, 140, 262)
FORMULA_AT = (180, 240, 900, 262)
CHANGED = 12                       # pixels that differ: that part of the picture changed
PASS_CARRIER = "PASS_DH"
PASS_DOMAIN = "passlogistics"


class Stop(RuntimeError):
    """Not as expected: the words are what he is told."""


def _client():
    import ctms_remote as R
    R.OUT = os.path.join(HERE, "ctms_remote")
    R.STATE = os.path.join(R.OUT, "state.json")
    R.BASE, R.KEY = R._desk()
    return R


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **k)


# -- what the order is
def record_of(ident):
    """The panel's record, wherever it lives: {} when it has gone."""
    try:
        import tracker
        got = next((r for r in tracker.load().get("records", []) if r.get("id") == ident), None)
        if got:
            return got
    except Exception:
        pass
    try:
        with open(os.path.join(HERE, "_adhocs.json"), encoding="utf-8") as f:
            got = next((r for r in json.load(f) if r.get("id") == ident), None)
        if got:
            return got
    except Exception:
        pass
    try:
        import pins
        return next((p for p in pins.load() if p.get("id") == ident), None) or {}
    except Exception:
        return {}


def region_for(postcode):
    """The NR region of a delivery postcode ("R4"), "" when it isn't known."""
    try:
        import nr_regions
        return nr_regions.region_of(postcode or "") if postcode else ""
    except Exception:
        return ""


TIPPERS = "Strategy 4 - Tippers"     # the well's Business Type for loose ballast and stoneblowers (his 16/11)


ADHOC_PROJECTS = "Strategy 6 - Ad-Hoc/Projects"


def _upload_rows(rec):
    """The order's own rows in its upload CSV - its ORDER row and those under it - [] when there's no upload on file."""
    try:
        import csv
        import outbox
        with open(outbox.path(rec["csv"]), encoding="utf-8", newline="") as f:
            rows = [r for r in csv.reader(f) if r]
    except Exception:
        return []
    want = {str(o) for o in (rec.get("orders") or [])}
    out, mine = [], False
    for r in rows:
        if r[0] == "ORDER":
            mine = len(r) > 1 and (not want or r[1] in want)
        if mine:
            out.append(r)
    return out


def upload_account(rec):
    """The CTMS account its upload put the order on (NRADHOC, NRADHOC_NS ...): "" without one."""
    row = next((r for r in _upload_rows(rec or {}) if r[0] == "ORDER"), [])
    return str(row[28]).strip() if len(row) > 28 else ""


def raised_by(rec):
    """The addresses its upload names as raising it (sub-ref 1002: the requester, often the site contact too)."""
    out = []
    for r in _upload_rows(rec or {}):
        if r[0] == "ORD_SUB_REFS" and len(r) > 2 and str(r[1]).strip() == "1002":
            out += [a.strip().lower() for a in re.split(r"[;,]", r[2]) if "@" in a]
    return out


def contact_in(addresses, name):
    """The address among these that goes by the contact's name - every word of it in the address - "" when none does."""
    words_ = [w.lower().replace("'", "") for w in re.findall(r"[A-Za-z'-]{2,}", str(name or ""))]
    if not words_:
        return ""
    return next((a.lower() for a in addresses if all(w in a.lower().split("@")[0] for w in words_)), "")


def order_strategy(ref, run=None):
    """The order's Business Type off its card in CTMS - the routes' order-read, about half a minute - "" when it can't
    be read. A bare order number opens its first line."""
    import subprocess
    run = run or subprocess.run

    def read(r):
        try:
            p = run([sys.executable, os.path.join(HERE, "ctms_routes.py"), "order-read", str(r)], capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=240, cwd=HERE)
            out = str(p.stdout or "")
        except Exception:
            return "", ""
        line = next((ln for ln in out.splitlines() if ln.startswith("ROUTE_RESULT ")), "")
        try:
            d = json.loads(line[len("ROUTE_RESULT "):]) if line else {}
        except ValueError:
            d = {}
        bt = str(((d.get("order") or {}).get("business_type")) or "").strip()
        return (bt if bt.startswith("Strategy") else ""), out

    bt, out = read(ref)
    if not bt:
        m = re.search(r"lines found: ([^)\r\n]+)\)", out)
        first = m.group(1).split(",")[0].strip() if m else ""
        if first and first not in ("none", str(ref)):
            bt, _ = read(first)
    return bt


def strategy_for(rec):
    """The well's strategy for an order when it can be told: loose ballast and stoneblower stone are on Strategy 4, the
    tippers (his 16/11); an ad hoc over 4 tonnes - its upload on NRADHOC_NS - imports on Strategy 6 (seen 24/11, when
    the well's Business Type left on another strategy by an earlier booking hid one). "" when it isn't known - the well
    is then filtered on the region alone."""
    try:
        import ctms_run_plan
        if ctms_run_plan.tipped(rec or {}):
            return TIPPERS
    except Exception:
        pass
    return ADHOC_PROJECTS if upload_account(rec or {}) == "NRADHOC_NS" else ""


def owed_first(orders, listing=None):
    """What the CTMS to-do has for these orders that has to go on before the booking."""
    import ctms_todo
    items = ctms_todo.listing() if listing is None else listing
    want = set(ctms_todo._bases(orders))
    return [i for i in items if (i.get("kind") in BLOCKS or _services(i))
            and want & set(ctms_todo._bases(i.get("orders") or []))]


def _services(item):
    """A Night / Saturday / Sunday the order needs ("Add NIGHT before it's booked"): the desk's to put on before it
    books, not his (his 06/11) - the to-do's Run adds it, as it does an update."""
    return item.get("source") == "services"


def run_owed(items):
    """The CTMS to-do's items that have to go on before this booking, run the way the to-do's Run runs them (ctms_run):
    (all done, in words). Anything it can't type - a hand-written item, a doubt only he can settle - stays undone, and
    the booking with it."""
    import ctms_run
    runnable = [i for i in items if i.get("kind") == "update" or _services(i)]
    if len(runnable) < len(items):
        other = next(i for i in items if i not in runnable)
        return False, (f"{other['what']}: that's on the CTMS to-do and has to go on before the booking, and it isn't "
                       "something Book can type. Do it, or tick it off.")
    try:
        res = _quiet(ctms_run.run, [i["id"] for i in runnable])
    except Exception as e:
        return False, f"What the CTMS to-do has for these orders couldn't be run first ({e})."
    if not res.get("ok"):
        return False, f"What the CTMS to-do has for these orders has to go on first, and it didn't all go: {res.get('said')}."
    return True, f"What the CTMS to-do had for these orders went on first: {res.get('said')}."


_QTY = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*x\b", re.I)


def quantities(rec):
    """{order: quantity} where the desk knows the order's quantity for certain, for Book's line check (his 03/11: the
    quantity must be the order's). An ad hoc's form says it; a tracked order only when it is one order of one product
    ("27x sleepers") - several products or orders on one record can't be shared out to CTMS's lines without guessing."""
    orders = [str(o) for o in rec.get("orders") or []]
    if len(orders) != 1:
        return {}
    if rec.get("kind") in ("adhoc", "dts"):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", str(rec.get("qty") or ""))
        return {orders[0]: float(m.group(1))} if m else {}
    parts = [p for p in str(rec.get("materials") or "").split(",") if p.strip()]
    if len(parts) != 1 or len(rec.get("product_codes") or []) > 1:
        return {}
    m = _QTY.match(parts[0])
    return {orders[0]: float(m.group(1))} if m else {}


LOADS_FROM = 3      # the work PC bridge's version whose Book sets each part of a split to its load (27/11)


def plan_loads(job, rec):
    """His 10 + 20 (27/11): bagged ballast going on more than one vehicle is shared out the ballast_loads way - each
    vehicle full before the next, what's left on a rigid when it is 10 bags or fewer - never halved ("You don't ever
    split it down into 15s to put on 2 Arctics because you're just wasting space. Unless I explicitly say so").
    Loads the job brings (the Book form's) are checked against the order's bags instead, and "equal": true is his
    say-so for halving it. Sets job["loads"] and job["vehicles"]. -> the plan in words ("" when there's none), or
    ValueError saying why it can't be booked as asked."""
    import ballast_loads as BL
    import ctms_run_plan
    n = int(job.get("vehicles") or 1)
    # a record flagged loose (the map's own flag) is tipped whatever its words say - never bags
    bags = None if (rec or {}).get("loose_ballast") else (ctms_run_plan.ballast_bags(rec or {}) or None)
    if job.get("loads"):
        plan = BL.check(job["loads"], bags)
        if n not in (1, len(plan)):
            raise ValueError(f"{len(plan)} loads ({BL.said(plan)}) for {n} vehicles")
        job["loads"], job["vehicles"] = BL.as_job(plan), len(plan)
        return "Loads as given: " + BL.said(plan)
    if job.get("equal") or n < 2 or not bags:
        return ""
    plan = BL.loads(bags, job.get("trailer"), job.get("carrier"))
    if plan is None:
        return ""                          # a trailer the rule doesn't know: split as asked
    if len(plan) != n:
        raise ValueError(f"{bags} bags on {job.get('trailer')} fill {len(plan)} vehicle(s), each full before the next "
                         f"({BL.said(plan)}), not {n}: book {len(plan)}, pick the other trailer, or tick Split equally")
    job["loads"] = BL.as_job(plan)
    return f"Loads: {BL.said(plan)}, each vehicle full before the next (his 10 + 20)"


def bridge_takes_loads(R):
    """Whether the work PC's bridge is on a version whose Book sets each part's load. An older one would drop the
    loads and halve the line, so they're never sent to it."""
    try:
        code, st = R.http("GET", "/api/ctms/status")
        v = str(((st or {}).get("state") or {}).get("version") or "").strip()
        return code == 200 and v.isdigit() and int(v) >= LOADS_FROM
    except Exception:
        return False


def is_urgent(collect, now):
    """The tracker's Urgent: "If Collecting Today/Tomorrow Morning". collect as the well shows it, dd/mm/yy HH:MM."""
    try:
        when = datetime.strptime(str(collect or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return False
    return when.date() <= now.date() or (when.date() == (now + timedelta(days=1)).date() and when.hour < 12)


# -- the DigiHaul row
def _near(c, want, tol=12):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(c, want))


def picked_row(im):
    """(top, bottom) of the row whose number is highlighted, or None."""
    ys = [y for y in range(ROW_TOP, max(ROW_END, im.size[1] - SHEET_FOOT)) if _near(im.getpixel((GUTTER_X, y)), PICKED)]
    return (ys[0], ys[-1]) if ys else None


def _dark(im, xs, ys):
    return sum(1 for y in range(*ys) for x in range(*xs) if sum(im.getpixel((x, y))[:3]) < 240)


def _underline(c):
    """The dark green under the cursor's column heading - a shade darker where the Name Box's tooltip shadows it."""
    r, g, b = c[:3]
    return r < 100 and g - r > 40 and g - b > 30


def _parting(im, x):
    """Whether one of the 1-px lines between two column headings is at x: on the strip above its letters and under them,
    with the strip's own shade either side - not the edge of a shadow or a letter."""
    return all(any(_near(im.getpixel((x, y)), p) for p in PARTING)
               and not any(_near(im.getpixel((x + d, y)), p) for p in PARTING for d in (-2, 2)) for y in PARTING_YS)


def yellow_columns(im, row, one=True):
    """Where B to G are on the picture, from the column headings: {"B": (left, right), ... "G": (left, right or the
    window's edge)}. B is the column the cursor's heading is underlined in - where the underline starts - and each one
    after it runs to the next line between two headings. It must have column A's cell to its left on the cursor's row
    (row: its (top, bottom)) - never a view scrolled sideways, where the first column shown can be any. one: the cursor
    is on one cell - only B underlined, at a place and width B can have (the Name Box can't be read). None when any of
    that, or B to F and the start of G, can't be told."""
    edge = im.size[0] - SCROLLBAR
    left = next((x for x in range(GUTTER_X, edge) if _underline(im.getpixel((x, UNDERLINE_Y)))), None)
    if left is None:
        return None
    end = left
    while end + 1 < edge and _underline(im.getpixel((end + 1, UNDERLINE_Y))):
        end += 1
    lines = [x for x in range(left + 5, edge) if _parting(im, x)][:6]
    if len(lines) < 5:                 # B|C, C|D, D|E, E|F and F|G: the yellow cells up to G have to show
        return None
    spans = dict(zip("BCDEFG", zip([left] + lines, lines + [edge])))
    b0, b1 = spans["B"]
    y, a = (row[0] + row[1]) // 2, 0
    while b0 - 1 - a > GUTTER_X and min(im.getpixel((b0 - 1 - a, y))[:3]) >= 250:
        a += 1                         # A's cell, from the cursor's frame back towards the row numbers
    if a < A_SHOWS:
        return None
    if one and (abs(end - b1) > 3 or b0 > B_LEFT_MAX or not B_WIDE[0] <= b1 - b0 <= B_WIDE[1]):
        return None
    return spans


def _inside(span):
    """What is read of a cell: its span short of its own borders and the cursor's frame."""
    return span[0] + INSET, span[1] - INSET


def row_state(im):
    """Where the tracker's cursor is on a picture: None when it can't be told it is on one cell of column B; else
    {"blank": the row's yellow cells are empty, "above": the row above has a manifest}. Anything dark inside a cell
    counts as writing, so a colleague's half-typed row never reads as blank (nor does a row a dark avatar of theirs
    covers: it is stepped over, like their writing)."""
    row = picked_row(im)
    spans = yellow_columns(im, row) if row else None
    if not spans or row[1] - row[0] < 8:
        return None
    top, bottom = row
    band = (top + 4, bottom - 3)
    return {"blank": not any(_dark(im, _inside(xs), band) for xs in spans.values()),
            "above": bool(_dark(im, _inside(spans["B"]), (top - 20, top - 4)))}


def row_filled(im):
    """Whether the row just pasted shows in every yellow cell that should have something (F, Notes, stays blank). The
    paste leaves the cursor on the whole row, B to G."""
    row = picked_row(im)
    spans = yellow_columns(im, row, one=False) if row else None
    if not spans:
        return False
    band = (row[0] + 4, row[1] - 3)
    shown = "BCDEG" if spans["G"][0] + G_MIDDLE <= im.size[0] - SCROLLBAR else "BCDE"   # G's middle is off a narrower window
    return all(_dark(im, _inside(spans[c]), band) for c in shown)


def _changed(a, b, box):
    """How many pixels inside box differ markedly between two pictures."""
    x0, y0, x1, y1 = box
    pa, pb = a.load(), b.load()
    return sum(1 for y in range(y0, min(y1, a.size[1], b.size[1])) for x in range(x0, min(x1, a.size[0], b.size[0]))
               if sum(abs(int(p) - int(q)) for p, q in zip(pa[x, y][:3], pb[x, y][:3])) > 60)


def in_name_box(before, after):
    """Whether the keys just typed went into the Name Box: its text changed and the formula bar didn't. The formula bar
    changing is a cell being typed in - 24/11, 09:15: right after Edge switched to the tracker's tab the Name Box click
    didn't take, and "B1048576" went into the selected cell, over a colleague's manifest."""
    return _changed(before, after, NAME_AT) >= CHANGED and _changed(before, after, FORMULA_AT) < CHANGED


def row_text(trip, carrier, now):
    """B manifest, C the carrier code, D the cost, E the planner, F left blank, G Urgent. The cost is what CTMS charges
    once the trip is accepted, read back off its Payments, when the work PC could read it - not the Create Trip box's
    figure, which leaves out what CTMS adds (his 27/11: a third of the real charge went on the tracker that way)."""
    return "\t".join([trip["manifest"], carrier, str(trip.get("total") or trip.get("cost") or ""), PLANNER, "",
                      "Y" if is_urgent(trip.get("collect"), now) else "N"])


# -- the cost, checked once the trip is accepted (his 27/11)
LIFT = ("HIAB", "MOFF")         # a payment line for lifting gear: CTMS's HIAB, or the Moffett service


def _money(v):
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def lifting_needed(rec):
    """The lifting gear the job's details ask for: "HIAB", "MOFFETT", "BOTH" (either), or "" when none is said."""
    off = str((((rec or {}).get("details") or {}).get("offloading") or {}).get("value") or "").strip().upper()
    return off if off in ("HIAB", "MOFFETT", "BOTH") else ""


def _gear(lift):
    return {"HIAB": "HIAB", "MOFFETT": "Moffett"}.get(lift, "HIAB or Moffett")


def cost_check(rec, job, trips):
    """(ok, words): each accepted trip's charges - as CTMS has them once it is accepted, read back by the work PC -
    checked against the job. His 27/11, "double check the costs at the end of you accepting something": an artic HIAB
    job went on as an artic flat with no HIAB on the order, CTMS charged a third of the real price, and the DigiHaul
    row carried that to the haulier, who asked why.
      * a quote typed: the charges come to it
      * the job needs lifting gear (offloading HIAB, a Moffett, or either): a HIAB or Moffett charge is on it - without
        one CTMS has priced the trip as if none were wanted
      * charges that couldn't be read back fail it only when there is something above to check them against
    The words give each trip's charges either way, so the figure is in front of him."""
    quote = _money(job.get("haulage"))
    quote = quote if quote and quote > 0 else None
    lift = lifting_needed(rec)
    wrong, told = [], []
    for t in trips or []:
        man = t.get("manifest") or "?"
        charges = t.get("charges") or []
        total = _money(t.get("total"))
        if not charges:
            if quote is not None or lift:
                wrong.append(f"{man}'s charges weren't read back from CTMS (its Create Trip box said {t.get('cost') or '?'})"
                             + (f": check they come to the {quote:g} quote" if quote is not None else "")
                             + (" and" if quote is not None and lift else ":" if lift else "")
                             + (f" check a {_gear(lift)} charge is on it" if lift else "") + " - its Payments in CTMS")
            else:
                told.append(f"{man} {t.get('cost') or '?'} (its Create Trip box's figure - not read back)")
            continue
        lines = ", ".join(f"{c.get('kind')} {c.get('amount') or '?'}" for c in charges)
        kinds = " ".join(str(c.get("kind") or "").upper() for c in charges)
        if total is None:
            wrong.append(f"{man}: a charge line couldn't be read ({lines}) - look at its Payments in CTMS")
            continue
        if quote is not None and abs(total - quote) > 0.005:
            wrong.append(f"{man}'s charges come to {total:.2f} ({lines}), not the {quote:g} quote")
        if lift and not any(g in kinds for g in LIFT):
            wrong.append(f"{man} has no {_gear(lift)} charge ({lines}), yet the job needs one (offloading {lift}): CTMS "
                         "has priced it without - put the service on the order, then send the manifest again (Planned, "
                         "then Accepted)")
        told.append(f"{man} {total:.2f} ({lines})" + ("" if quote is not None else ", CTMS's own price"))
    if wrong:
        return False, "; ".join(wrong)
    return True, "; ".join(told)


def tracker_rows(R, trips, carrier, now=None, look_only=False):
    """Each manifest on the DigiHaul tracker, a row at a time. Returns (rows written, why it stopped or "").
    look_only: gets to the row and says what it found there, nothing pasted."""
    from PIL import Image
    now = now or datetime.now()
    result, _ = _quiet(R.ask, "use", target="page")
    if not result.get("ok"):
        return 0, f"the tracker's tab wouldn't come up ({result.get('detail')})"
    done, why = 0, ""
    latest = os.path.join(R.OUT, "latest.png")
    try:
        for trip in trips:
            # The Name Box to column B's last row, Ctrl+Up to the last manifest, Down: wherever the sheet was left. A click
            # into the view and Ctrl+Down ran off to row 1048576 when the clicked row was the last one filled (23/11).
            # The Name Box clicked twice - after Edge switches tabs the first click only gives the page the keys - and
            # the address typed, NOT entered, until the pictures before and after show it went into the Name Box. In a
            # cell (24/11: over a colleague's manifest) it is thrown away with Escape, and nothing more is done.
            if _quiet(R.send_batch, "tracker-name-box", [{"action": "click", "px": NAME_BOX}, {"action": "wait", "seconds": 0.6},
                                                         {"action": "click", "px": NAME_BOX}, {"action": "wait", "seconds": 0.4},
                                                         {"action": "key", "key": "ctrl+a"}, {"action": "wait", "seconds": 0.3}]):
                return done, "the tracker didn't take the clicks"
            before = Image.open(latest).convert("RGB")
            typed = _quiet(R.send_batch, "tracker-address", [{"action": "type", "text": SHEET_END},
                                                             {"action": "wait", "seconds": 0.5}])
            if typed or not in_name_box(before, Image.open(latest).convert("RGB")):
                if _quiet(R.send_batch, "tracker-escape", [{"action": "key", "key": "escape"}, {"action": "wait", "seconds": 0.5}]):
                    return done, (f"LOOK AT THE TRACKER NOW: the Name Box didn't have the keys, and the Escape that throws "
                                  f"\"{SHEET_END}\" away didn't go either - it may be sitting in a cell, not yet entered")
                return done, ("the Name Box didn't have the keys, so what was typed was thrown away with Escape - nothing "
                              "written on the tracker")
            steps = [{"action": "key", "key": "enter"}, {"action": "wait", "seconds": 0.9},
                     {"action": "key", "key": "ctrl+up"}, {"action": "wait", "seconds": 0.9},
                     {"action": "key", "key": "down"}, {"action": "wait", "seconds": 0.9}]
            past = False                   # stepped over a colleague's half-typed row: no manifest above is then expected
            for _ in range(4):
                if _quiet(R.send_batch, "tracker-row", steps):
                    return done, "the tracker didn't take the keys"
                state = row_state(Image.open(latest).convert("RGB"))
                if state is None or not (state["above"] or past):
                    return done, "couldn't be sure of the cursor on the tracker"
                if state["blank"]:
                    break
                past = True
                steps = [{"action": "key", "key": "down"}, {"action": "wait", "seconds": 0.7}]   # half typed by a colleague
            else:
                return done, "no empty row where one should be"
            if look_only:
                return done, f"would paste here: {row_text(trip, carrier, now)!r}"
            result, _ = _quiet(R.ask, "paste", text=row_text(trip, carrier, now))
            if not result.get("ok"):
                return done, f"the paste was refused ({result.get('detail')})"
            done += 1
            try:
                if _quiet(R.send_batch, "tracker-check", [{"action": "wait", "seconds": 1.0}]):
                    return done, "couldn't look at the row after the paste"
                filled = row_filled(Image.open(latest).convert("RGB"))
            except Exception as x:
                # the paste went: it stays counted, so a retry never pastes it again - only the look after it failed
                return done, f"couldn't look at {trip['manifest']}'s row after the paste ({str(x)[:80]}): check it by eye"
            if not filled:
                why = f"{trip['manifest']}'s row didn't read back as filled: look at it"
                break
    finally:
        try:
            (_, payload) = _quiet(R.ask, "use", target="ctms")
        except Exception:
            payload = None                 # what was pasted stays counted; the bridge books nothing on the tracker's tab
        if payload and payload.get("kind") == "window":
            R.save_state(payload)          # the page's picture was the last on file: what's next aims at CTMS
    return done, why


# -- the site's email
def first_name(name):
    """The name to greet: "Blake, Steven" or "Steven Blake" -> Steven."""
    name = str(name or "").strip()
    if "," in name:
        name = name.split(",", 1)[1].strip()
    word = (name.split() or [""])[0]
    return word if re.fullmatch(r"[A-Za-z][A-Za-z'-]+", word) else ""


def and_list(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


LORRIES = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def greeting(sender, sender_address, rec):
    """Who a reply greets: the name the order has for its contact, when the mail is theirs or ours; else whoever wrote it."""
    who = first_name(sender)
    if not who or who == PLANNER or str(sender_address or "").lower() == str(rec.get("to") or "").lower():
        return first_name(rec.get("name")) or ("" if who == PLANNER else who)
    return who


def words(greet, carrier, haulier, date, trips, rec, thanks=False):
    """His own wording (30/10): "Thanks. This order has been arranged with ... for <day>, delivering between ... and ....
    Here is the ref number MAN-...". The start is CTMS's, the end the site's window. Never a price."""
    day = datetime.strptime(date, "%d/%m/%Y").strftime("%A %d/%m/%Y")
    t = (rec.get("details") or {}).get("time") or {}
    start = str(trips[0].get("deliver") or "").strip()[9:14] or str(t.get("earliest") or "")
    end = str(t.get("latest") or "")
    when = f"delivering between {start} and {end}" if start and end > start else f"delivering from {start}" if start else ""
    who = "our own DHL fleet" if carrier == NOC else (haulier or carrier)
    mans = [x["manifest"] for x in trips]
    n = len(mans)
    last = f"Here is the ref number {mans[0]}" if n == 1 else (
        f"It will come on {LORRIES.get(n, n)} lorries. Here are the ref numbers: {and_list(mans)}")
    import pickup_split
    split = pickup_split.note(rec, date)          # several pick-ups / days: the site is told (his rule 02/11)
    return (f"Hi {greet or 'there'},<br><br>{'Thanks. ' if thanks else ''}This order has been arranged with {who} for {day}"
            + (f", {when}" if when else "") + f". {last}<br><br>" + (f"{split}<br><br>" if split else ""))


def _addresses(mail):
    mail.Recipients.ResolveAll()
    out = []
    for i in range(1, mail.Recipients.Count + 1):
        r = mail.Recipients.Item(i)
        a = ""
        try:
            u = r.AddressEntry.GetExchangeUser()
            a = u.PrimarySmtpAddress if u is not None else ""
        except Exception:
            pass
        out.append((i, (a or str(r.Address or "") or str(r.Name or "")).lower()))
    return out


def haulier_addresses():
    """Every address the haulier list has: a site email never goes to one."""
    try:
        import hauliers
        d = hauliers.load()
        return {str(a).lower() for h in d.get("hauliers", []) + d.get("services", []) for a in h.get("emails") or []}
    except Exception:
        return set()


def _when(item):
    for attr in ("ReceivedTime", "SentOn"):
        try:
            t = getattr(item, attr)
            return datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
        except Exception:
            pass
    return datetime(2000, 1, 1)


def _people(item):
    """The addresses on a mail, lower case: its sender's and each recipient's."""
    got = set()
    try:
        got.add(str(item.SenderEmailAddress or "").lower())
    except Exception:
        pass
    try:
        for i in range(1, item.Recipients.Count + 1):
            r = item.Recipients.Item(i)
            got.add(str(r.Address or "").lower())
            try:
                u = r.AddressEntry.GetExchangeUser()
                if u is not None:
                    got.add(str(u.PrimarySmtpAddress or "").lower())
            except Exception:
                pass
    except Exception:
        pass
    return got


def site_rank(subject, people, orders, site_topic, contact, conv=None, thread_conv=None, not_site=frozenset()):
    """How surely a mail with an order number in its subject is on the site's thread: 2 our site email's own thread, 1 the
    contact is on it and it opens with the order, 0 not at all - a haulier's cover request ("<order> Delivery") and the
    materials team's "alternative contact" chain start with the order number too."""
    import file_chain
    topic = file_chain.topic(subject)
    if people & not_site or "alternative contact" in topic:
        return 0
    if (thread_conv and conv == thread_conv) or (site_topic and topic == site_topic):
        return 2
    return 1 if contact and contact in people and any(topic.startswith(str(o).lower()) for o in orders) else 0


def site_thread(ns, rec):
    """(the newest mail of the order's site thread, how sure) - the Inbox, where he files them, or Sent Items - or (None, 0).
    Our own thread when there is one; a mail that only has the contact on it, when there isn't."""
    import build_drafts as bd
    import file_chain
    root = bd.dhl_store(ns)
    boxes = [bd.sub(root, "Inbox"), file_chain.folder(root, file_chain.DEST), bd.sub(root, "Sent Items")]
    orders = [str(o) for o in rec.get("orders") or []]
    site_topic = file_chain.topic(bd.subject_for(orders, rec.get("worksite") or "", rec.get("site") or "",
                                                 rec.get("postcode") or "", rec.get("po") or {}))
    contact = str(rec.get("to") or "").lower()
    thread_conv = ""
    if rec.get("orig_entryid"):
        try:
            thread_conv = str(ns.GetItemFromID(rec["orig_entryid"]).ConversationID or "")
        except Exception:
            pass
    not_site = haulier_addresses()
    best, how = None, 0
    for box in boxes:
        if box is None:
            continue
        for o in orders:
            for it in box.Items.Restrict('@SQL=("urn:schemas:httpmail:subject" LIKE \'%' + o.replace("'", "''") + '%\')'):
                subj = str(getattr(it, "Subject", "") or "")
                rank = site_rank(subj, _people(it), orders, site_topic, contact,
                                 str(getattr(it, "ConversationID", "") or ""), thread_conv, not_site)
                if rank and (rank, _when(it)) > (how, _when(best) if best is not None else datetime(2000, 1, 1)):
                    best, how = it, rank
    return best, how


def reaches(addresses, contact):
    """Whether a reply gets to the order's contact - the address on the order can be a letter out of the real one's."""
    who = str(contact or "").lower().split("@")[0]
    return any(str(a).lower().split("@")[0].startswith(who) for a in addresses) if who else True


def address_in_text(text, words_):
    """The address of whoever goes by these words in a mail's text: "Name <address>", the way a quoted chain has its people."""
    for who, a in re.findall(r"([^<>;:\r\n]*)<([\w.'+-]+@[\w-]+(?:\.[\w-]+)+)", str(text or "")):
        if all(w in f"{who} {a}".lower() for w in words_):
            return a.lower()
    return ""


def adhoc_address(src, name):
    """The delivery contact's address on an ad hoc's request - the form gives a name and a phone number, so only someone
    on the mail itself can be emailed: one of its recipients, or on a colleague's forward, someone in the chain it quotes.
    "" when nobody on it goes by that name."""
    words_ = [w.lower() for w in re.findall(r"[A-Za-z'-]{2,}", str(name or ""))]
    if not words_:
        return ""
    for i in range(1, src.Recipients.Count + 1):
        r = src.Recipients.Item(i)
        a = str(r.Address or "")
        try:
            u = r.AddressEntry.GetExchangeUser()
            a = (u.PrimarySmtpAddress if u is not None else "") or a
        except Exception:
            pass
        said = f"{r.Name} {a}".lower()
        if "@" in a and all(w in said for w in words_):
            return a.lower()
    return address_in_text(src.Body, words_)


def oneoff_to(rec, job, src, raised, ours):
    """Who an ad hoc's or a DTS's booking email goes to, and the name it greets: (address, name).
    A DTS: the people who booked it in, on its form - its upload's raised-by (his 26/11: "you just contact these people
    that has been booked in", naming the supplier's own address) - never whoever sent it on to us. An ad hoc: the delivery
    contact on the request or its upload, else whoever asked for it (his 24/11), else who raised it."""
    contact = ((rec.get("details") or {}).get("contact") or {}).get("name") or ""
    usable = [a for a in raised if not left_off_site(a, ours) and not _NOBODY.search(a)]
    if job.get("site_to"):
        return job["site_to"], first_name(contact)
    if rec.get("kind") == "dts" and usable:
        return usable[0], ""
    to = (adhoc_address(src, contact) if src is not None else "") or contact_in(raised, contact)
    greet = first_name(contact)
    if not to and src is not None:      # nobody on the request to email: whoever asked for it is told (his 24/11)
        to, who = requester(src, ours)
        greet = first_name(who)
    if not to:                          # no request email kept on the job: who raised it, as its upload says
        to, greet = (usable[0] if usable else ""), ""
    return to, greet


def left_off_site(address, ours):
    """Who never stays on a site email: ourselves, and the DHL Road mailbox (his 03/11), whatever the chain had on it."""
    return address == ours or "dhlroad" in address


_NOBODY = re.compile(r"no-?reply|donotreply|service-now|mailer-daemon|postmaster", re.I)


def requester(src, ours):
    """Who asked for the job, when its request names nobody we can email (his 24/11, an RDA order: "code that in too"):
    the person who first wrote it - the deepest "From:" in the chain the mail quotes, so not a colleague who only sent it
    on, nor our own forward of DHL Road's copy - else the mail's own sender. Never ourselves, DHL Road or a no-reply
    portal. (address, name) - ("", "") when there's nobody."""
    def person(a):
        a = str(a or "").strip().lower()
        return "@" in a and not left_off_site(a, ours) and not _NOBODY.search(a)

    quoted = re.findall(r"From:\s*([^<>\r\n]*?)\s*<([\w.'+-]+@[\w-]+(?:\.[\w-]+)+)", str(getattr(src, "Body", "") or ""))
    for who, a in reversed(quoted):
        if person(a):
            return a.lower(), who.strip()
    sender = str(getattr(src, "SenderEmailAddress", "") or "")
    try:
        u = src.Sender.GetExchangeUser()
        sender = (u.PrimarySmtpAddress if u is not None else "") or sender
    except Exception:
        pass
    if person(sender):
        return sender.lower(), str(getattr(src, "SenderName", "") or "")
    return "", ""


def checks(top, trips, got, mine):
    """What must be true of a site email before it goes: the words, the recipients. [] when it may."""
    bad = []
    if not got:
        bad.append("nobody to send it to")
    if any(a in mine for a in got):
        bad.append("a haulier is on it")
    for x in trips:
        if x["manifest"] not in top:
            bad.append(f"{x['manifest']} missing")
    if "£" in top:
        bad.append("a price slipped in")
    if "—" in top:
        bad.append("an em dash crept in")
    return bad


def site_email(rec, job, trips, send=True):
    """The site told. Returns (sent, what was done, in words): it never raises for want of a thread - he is told.
    send False: built, checked and thrown away, the words said back."""
    import build_drafts as bd
    import send_order
    ns = bd.get_ns()
    acct = next((ns.Accounts.Item(i) for i in range(1, ns.Accounts.Count + 1)
                 if str(getattr(ns.Accounts.Item(i), "SmtpAddress", "")).lower() == bd.DHL_SMTP.lower()), None)
    if acct is None:
        return False, "the DHL account wasn't found"
    carrier, haulier, date = job["carrier"], job.get("haulier") or "", job["date"]
    oneoff = rec.get("kind") in ("adhoc", "dts")
    thanks = False
    if oneoff:
        entry = (rec.get("mail") or {}).get("entryid")
        src = ns.GetItemFromID(entry) if entry else None
        contact = ((rec.get("details") or {}).get("contact") or {}).get("name") or ""
        to, greet = oneoff_to(rec, job, src, raised_by(rec), bd.DHL_SMTP.lower())
        if not to:
            return False, (f"no address for {contact or 'the delivery contact'} on the request or its upload, and "
                           "nobody who asked")
        if src is not None:
            m = src.Forward()
        else:                            # a new email of its own, as for a tracker order with no thread
            m = ns.Application.CreateItem(0)
            m.Subject = bd.subject_for(rec.get("orders") or [], rec.get("worksite") or "", rec.get("site") or "",
                                       rec.get("postcode") or "", rec.get("po") or {})
        m.To = to
    else:
        src, _ = site_thread(ns, rec)
        if src is not None:
            m = src.ReplyAll()
            if rec.get("to") and not reaches([a for _, a in _addresses(m)], rec["to"]):
                m.Close(1)               # its last word was someone else's - a materials team's - and wouldn't reach the site
                src = None
        if src is None:
            if not rec.get("to"):
                return False, "no site thread and no contact"
            m = ns.Application.CreateItem(0)
            m.To = rec["to"]
            m.Subject = bd.subject_for(rec.get("orders") or [], rec.get("worksite") or "", rec.get("site") or "",
                                       rec.get("postcode") or "", rec.get("po") or {})
            greet = first_name(rec.get("name"))
        else:
            sender = str(getattr(src, "SenderName", "") or "")
            greet = greeting(sender, getattr(src, "SenderEmailAddress", ""), rec)
            thanks = first_name(sender) != PLANNER
    body = words(greet, carrier, haulier, date, trips, rec, thanks)
    if src is not None:
        new, n = re.subn(r"(<body[^>]*>)", lambda mm: mm.group(1) + f'<div style="{FONT}">{body}</div>', m.HTMLBody,
                         count=1, flags=re.I)
        if n != 1:
            return False, "couldn't find where its text starts"
        m.HTMLBody = new
    else:
        m.HTMLBody = bd.html_from_message(body.replace("<br>", "\n").strip())
        bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        return False, "couldn't set the DHL account on it"
    for i, a in reversed(_addresses(m)):
        if left_off_site(a, bd.DHL_SMTP.lower()):
            m.Recipients.Remove(i)       # his own reply-all
    got = [a for _, a in _addresses(m)]
    top = re.split(r"\n\s*(?:From:|-#-#-|________________)", str(m.Body or ""))[0]
    bad = checks(top, trips, got, haulier_addresses())
    if bad and send:
        return False, "; ".join(bad)
    if not send:
        said = f"to {got} subject {m.Subject!r} problems {bad}: {re.sub(r'(\r?\n)+', ' / ', top).strip()[:500]}"
        m.Close(1)                       # thrown away
        return False, said
    m.Display(False)                     # a reply open in the reading pane refuses a plain Send
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    return True, "emailed " + and_list(got)


def _between(stamp, latest):
    """"Tuesday 03/11/2026 between 12:00 and 13:00" from the well's dd/mm/yy HH:MM and the window's end; "" with no stamp."""
    try:
        when = datetime.strptime(str(stamp or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return ""
    start, day = when.strftime("%H:%M"), when.strftime("%A %d/%m/%Y")
    return f"{day} between {start} and {latest}" if str(latest or "") > start else f"{day} from {start}"


def collection_contact(rec):
    """The name and number on the collection end of the order's upload, which the record doesn't keep; "" without one."""
    try:
        import csv
        import outbox
        with open(outbox.path(rec["csv"]), encoding="utf-8", newline="") as f:
            row = next(r for r in csv.reader(f) if r and r[0] == "ORDER")
        return re.sub(r"\s+", " ", f"{row[4]} {row[5]} {row[12]}").strip()
    except Exception:
        return ""


def pass_words(greet, trips, rec):
    """What Parcel Pass is told when the job comes to them: the manifest and the job. Never asked for an ETA (his 03/11)."""
    d = rec.get("details") or {}
    mans = [x["manifest"] for x in trips]
    number = f"Here's the manifest number: {mans[0]}" if len(mans) == 1 else f"Here are the manifest numbers: {and_list(mans)}"
    lines = [f"Hi {greet or 'there'},", "", f"Thanks for covering this, sending it over now. {number}", ""]
    collect = _between(trips[0].get("collect"), (d.get("collection_time") or {}).get("latest"))
    deliver = _between(trips[0].get("deliver"), (d.get("time") or {}).get("latest"))
    frm = " ".join(str(rec.get(k) or "") for k in ("collection_site", "collection_pc")).strip()
    to = " ".join(str(rec.get(k) or "") for k in ("site", "postcode")).strip()
    if collect:
        lines.append(f"Collection: {collect}" + (f", {frm}" if frm else ""))
    if deliver:
        lines.append(f"Delivery: {deliver}" + (f", {to}" if to else ""))
    who = collection_contact(rec)
    if who:
        lines.append(f"Collection contact: {who}")
    contact = d.get("contact") or {}
    site = " ".join(str(contact.get(k) or "") for k in ("name", "phone")).strip()
    if site:
        lines.append(f"Site contact: {site}")
    return "<br>".join(lines) + "<br><br>"


def pass_greeting(sender):
    who = first_name(sender)
    return "" if who.isupper() else who          # the shared mailbox's name, NR, isn't anyone's


def pass_thread(ns, orders):
    """The newest mail from Parcel Pass on this order (their quote), in the Inbox or filed: None when there isn't one."""
    import build_drafts as bd
    import file_chain
    root = bd.dhl_store(ns)
    best = None
    for box in (bd.sub(root, "Inbox"), file_chain.folder(root, file_chain.DEST)):
        if box is None:
            continue
        for o in orders:
            for it in box.Items.Restrict('@SQL=("urn:schemas:httpmail:subject" LIKE \'%' + str(o).replace("'", "''") + '%\')'):
                if PASS_DOMAIN in str(getattr(it, "SenderEmailAddress", "") or "").lower() and (best is None or _when(it) > _when(best)):
                    best = it
    return best


def pass_checks(top, trips, got):
    bad = []
    if not got or not all(PASS_DOMAIN in a for a in got):
        bad.append("it isn't going to Parcel Pass alone")
    for x in trips:
        if x["manifest"] not in top:
            bad.append(f"{x['manifest']} missing")
    if re.search(r"\bETA\b", top):
        bad.append("it asks for an ETA")
    if "—" in top:
        bad.append("an em dash crept in")
    return bad


def pass_email(rec, trips, orders, send=True):
    """Parcel Pass told it's coming to them, on their own quote's thread: (sent, what was done, in words)."""
    import build_drafts as bd
    import hauliers
    import send_order
    ns = bd.get_ns()
    acct = next((ns.Accounts.Item(i) for i in range(1, ns.Accounts.Count + 1)
                 if str(getattr(ns.Accounts.Item(i), "SmtpAddress", "")).lower() == bd.DHL_SMTP.lower()), None)
    if acct is None:
        return False, "the DHL account wasn't found"
    src = pass_thread(ns, orders)
    if src is not None:
        m = src.Reply()
        body = pass_words(pass_greeting(getattr(src, "SenderName", "")), trips, rec)
        new, n = re.subn(r"(<body[^>]*>)", lambda mm: mm.group(1) + f'<div style="{FONT}">{body}</div>', m.HTMLBody,
                         count=1, flags=re.I)
        if n != 1:
            return False, "couldn't find where its text starts"
        m.HTMLBody = new
    else:
        service = next((s for s in hauliers.load().get("services", []) if PASS_DOMAIN in " ".join(s.get("emails") or []).lower()), None)
        if service is None:
            return False, "no Parcel Pass address on the list"
        m = ns.Application.CreateItem(0)
        m.To = service["emails"][0]
        m.Subject = f"{' / '.join(orders)} Delivery"
        m.HTMLBody = bd.html_from_message(pass_words("", trips, rec).replace("<br>", "\n").strip())
        bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        return False, "couldn't set the DHL account on it"
    got = [a for _, a in _addresses(m)]
    top = re.split(r"\n\s*(?:From:|-#-#-|________________)", str(m.Body or ""))[0]
    bad = pass_checks(top, trips, got)
    if bad and send:
        return False, "; ".join(bad)
    if not send:
        said = f"to {got} subject {m.Subject!r} problems {bad}: {re.sub(r'(\r?\n)+', ' / ', top).strip()[:500]}"
        m.Close(1)                       # thrown away
        return False, said
    m.Display(False)                     # a reply open in the reading pane refuses a plain Send
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    return True, "emailed " + and_list(got)


def file_away(rec):
    """The job's mail filed in Region 2 > Completed: (how many, or the reason it couldn't)."""
    import build_drafts as bd
    import file_chain
    ns = bd.get_ns()
    if rec.get("kind") in ("adhoc", "dts"):
        entry = (rec.get("mail") or {}).get("entryid")
        if not entry:
            return 0
        dest = file_chain.folder(bd.dhl_store(ns), file_chain.DEST)
        ns.GetItemFromID(entry).Move(dest)
        return 1
    return len(file_chain.file_chain(ns, rec))


def take_off(ident):
    """Off the map, the way its Booked button does it."""
    import agent
    with open(os.path.join(HERE, "cloud.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    agent.BASE, agent.KEY = cfg["url"], cfg["agent_key"]
    return agent._book_off(ident)


# -- a step done once only
SENT_LOOK = 300                  # Sent Items looked through for an email already gone, newest first
SENT_DAYS = 3


def sent_already(manifests, to_has="", to_not=""):
    """Whether an email naming every one of these manifests has gone from the DHL account in the last few days - to an
    address with to_has in it, or with no to_not in any. A retry looks first: the Send can go through and the run still
    die before the journal hears of it, and a second "it's booked" email to a site is the one mistake here that reads as
    a muddle to the customer."""
    import build_drafts as bd
    want = [m for m in manifests if m]
    if not want:
        return False
    folder = bd.sub(bd.dhl_store(bd.get_ns()), "Sent Items")
    if folder is None:
        return False
    items = folder.Items
    items.Sort("[SentOn]", True)
    since = datetime.now() - timedelta(days=SENT_DAYS)
    for n, it in enumerate(items):
        if n >= SENT_LOOK:
            break
        try:
            if datetime(*it.SentOn.timetuple()[:6]) < since:
                break
            body = str(getattr(it, "Body", "") or "")[:4000]
            if not all(m in body for m in want):
                continue
            to = " ".join(a for _, a in _addresses(it)).lower()       # only for a mail that names them: it's slow
        except Exception:
            continue
        if (not to_has or to_has in to) and not (to_not and to_not in to):
            return True
    return False


def _step(k, name, fn, auto=False):
    """One step run and written down: (ok, words). An exception is a step not done, never a run ended."""
    import book_journal as J
    try:
        ok, said = fn()
    except Exception as e:
        ok, said = False, str(e)[:160]
    J.step(k, name, ok, said, auto=auto)
    return ok, said


def follow(k, R=None, now=None, auto=False, only=None):
    """What follows a booking, each step the journal hasn't got as done - the steps, then, a press of Book, a Retry and the
    timer all share. auto: the timer, which leaves the DigiHaul row to his Retry (it needs Look mum, no hands on). only:
    these steps alone. Returns the words, step by step."""
    import book_journal as J
    now = now or datetime.now()
    e = J.get(k) or {}
    made = J.accepted(e)
    mans = [t["manifest"] for t in made]
    if not mans:
        return []                            # nothing ACCEPTED: nothing follows
    carrier = str(e.get("carrier") or "")
    job = {x: e.get(x) for x in J.JOB_KEYS if e.get(x) not in (None, "")}
    orders = [str(o) for o in e.get("orders") or []]
    rec = record_of(e.get("record")) or e.get("record_copy") or {"orders": orders}
    said = []
    for name in J.left(e):
        if only and name not in only:
            continue
        if auto and name not in J.AUTO:
            continue
        steps = (J.get(k) or {}).get("steps") or {}
        tried = int((steps.get(name) or {}).get("tries") or 0)
        started = bool((steps.get(name) or {}).get("started"))     # begun by a run that may have died after the Send
        if name == "cost":
            ok, how = _step(k, name, lambda: cost_check(rec, job, made), auto)
            said.append(f"Cost checked: {how}." if ok else
                        f"COST CHECK FAILED: {how}. Nothing carries that price on: once CTMS has it right, press Done on "
                        "the cost check and type the DigiHaul row by hand with the right price.")
            continue
        if name == "digihaul":
            have = set((steps.get("digihaul") or {}).get("written") or [])
            todo = [t for t in made if t["manifest"] not in have]
            if "cost" in steps and not (steps.get("cost") or {}).get("ok"):
                # the cost check didn't pass (his 27/11): the haulier reads the tracker, so CTMS's figure isn't written -
                # not even once the check is Done by hand, the price having been put right in CTMS since it was read
                J.step(k, name, False, "held: the cost check didn't pass - typed by hand with the right price")
                said.append("DigiHaul NOT written: the cost check didn't pass, so CTMS's figure isn't put in front of "
                            "the haulier. By hand, with the right price: "
                            + " | ".join(row_text(t, carrier, now).replace("\t", ", ") for t in todo) + ".")
                continue
            nocost = [t["manifest"] for t in todo if t.get("total") in (None, "") and t.get("cost") in (None, "")]
            if nocost:
                J.step(k, name, False, f"the cost of {and_list(nocost)} isn't known here: type the row by hand")
                said.append(f"DigiHaul NOT written: the cost of {and_list(nocost)} isn't known here. By hand: "
                            + " | ".join(row_text(t, carrier, now).replace("\t", ", ") for t in todo) + ".")
                continue
            R = R or _client()
            rows, why = 0, ""
            for t in todo:                       # one at a time, each kept as it goes on: a retry never pastes it twice
                try:
                    n, why = tracker_rows(R, [t], carrier, now)
                except Exception as x:
                    n, why = 0, str(x)[:160]
                if n:
                    J.written(k, t["manifest"])
                    rows += 1
                if why or not n:
                    why = why or "the row didn't go on"
                    break
            left_ = [t for t in todo if t["manifest"] not in set(((J.get(k) or {}).get("steps") or {})
                                                                  .get("digihaul", {}).get("written") or [])]
            # a row put on by hand after a try that stopped is still "left" here: a Retry would paste it twice (26/11)
            look = (f" Before a Retry, look at the tracker: if {and_list([t['manifest'] for t in left_])} is on it "
                    "already, press Done by hand instead." if left_ else "")
            J.step(k, name, not left_, why + look if left_ else why)
            said.append(f"DigiHaul: {rows} row(s) written" + (f", but {why}." if why else ".") if not left_ else
                        f"DigiHaul: {rows} of {len(todo)} row(s) written, {why}. Retry, or by hand: "
                        + " | ".join(row_text(t, carrier, now).replace("\t", ", ") for t in left_) + "." + look)
        elif name == "pass_email":
            def go():
                if (tried or started) and sent_already(mans, to_has=PASS_DOMAIN):
                    return True, "it had gone already"
                J.begin(k, name)
                return pass_email(rec, made, orders)
            ok, how = _step(k, name, go, auto)
            said.append(f"Parcel Pass: {how}." if ok else f"Parcel Pass email NOT sent ({how}): "
                        + ("I'll try again in a few minutes." if _auto_left(k, name) else f"tell them {and_list(mans)} by hand, or Retry."))
        elif name == "site_email":
            def go():
                if (tried or started) and sent_already(mans, to_not=PASS_DOMAIN):
                    return True, "it had gone already"
                J.begin(k, name)
                return site_email(rec, job, made)
            ok, how = _step(k, name, go, auto)
            said.append(f"Site: {how}." if ok else f"Site email NOT sent ({how}): "
                        + ("I'll try again in a few minutes." if _auto_left(k, name) else f"tell them {and_list(mans)} by hand, or Retry."))
        elif name == "filed":
            if "site_email" in J.left(J.get(k) or {}):
                continue                         # the chain stays where the site email's retry can find its thread
            ok, how = _step(k, name, lambda: (True, f"{file_away(rec)} filed"), auto)
            if ok:
                said.append("Chain filed.")
        elif name == "off_map":
            def go():
                removed, _ = take_off(e.get("record"))
                return True, "off the map" if removed else "it had gone under another id"
            ok, how = _step(k, name, go, auto)
            said.append("Off the map." if ok and how == "off the map" else
                        f"Still on the map: {how}." if ok else f"Still on the map ({how}).")
    return said


def _auto_left(k, name):
    import book_journal as J
    s = ((J.get(k) or {}).get("steps") or {}).get(name) or {}
    return name in J.AUTO and s.get("next_at") is not None and not s.get("ok")


# -- what came of an ask nobody heard the answer to
def _parsed_trips(text):
    """Manifests and their status out of the bridge's words ("Booked 1 in 52s: MAN-01000001 ACCEPTED, ..."), when the
    picture-laden payload has gone: no cost, so the DigiHaul row waits for him."""
    return [{"manifest": m, "status": st} for m, st in re.findall(r"(MAN-\d+)\s+([A-Z]+)", str(text or ""))]


def _by_you(text):
    """Whether the bridge's words say Stop on the dashboard ended the booking ("Stopped by you after 1 of 4 trips: ...")."""
    return str(text or "").startswith("Stopped by you")


def recall(k, R=None):
    """An ask whose answer the home PC never had, looked for again: the dashboard by its command id, then the work PC's
    own record of what its Book made. Either answer goes into the journal as if it had come at the time. Nothing in CTMS
    is touched. Returns the journal's entry."""
    import book_journal as J
    e = J.get(k) or {}
    cid = e.get("ask_id")
    if not cid:
        # no number came back: the dashboard may still have queued it (the POST's answer lost on the way) and the work PC
        # booked it, so it is never taken for nothing made - after a while it is his to look at in CTMS
        if time.time() - float(e.get("asked_at") or 0) > J.LOST_AFTER:
            return J.lost(k, "the dashboard never said it had the command - it may have reached the work PC")
        return J.get(k)
    R = R or _client()
    try:
        result, payload = R.result_of(cid)
    except Exception:
        result, payload = None, None
    if result is not None and (payload or {}).get("trips") is not None:
        return J.answered(k, result.get("ok"), result.get("detail"), payload["trips"], e.get("carrier"),
                          pressed=bool(payload.get("stop_pressed")) or _by_you(result.get("detail")))
    try:
        got, back = _quiet(R.ask, "book_recall", wait_total=45, orders=e.get("orders"), date=e.get("date"), ask=cid)
    except Exception:
        got, back = {}, None
    found = ((back or {}).get("found") or []) if got.get("ok") else None
    if found:
        f = found[0]
        return J.answered(k, f.get("ok"), f.get("said"), f.get("trips"), e.get("carrier"),
                          pressed=bool(f.get("pressed")) or _by_you(f.get("said")))
    if result is not None:
        trips = _parsed_trips(result.get("detail"))
        return J.answered(k, result.get("ok"), result.get("detail"), trips, e.get("carrier"),
                          pressed=_by_you(result.get("detail")))
    if found is not None and time.time() - float(e.get("asked_at") or 0) > J.LOST_AFTER:
        # the work PC answered and has nothing for that command: it never ran it, or died before it was done
        return J.lost(k, "the work PC has no record of booking it - it may have stopped part way")
    return J.get(k)


# -- the whole of it
LOCK_WAIT = 20


def _lock():
    """One booking run on the home PC at a time - a press of Book, a Retry, the timer: the journal is read and written by
    each, and two at once could each think a step undone."""
    try:
        import outlook_gate
        return outlook_gate.named_lock("book_run", wait=LOCK_WAIT)
    except Exception:
        return True


def book(job, R=None, now=None):
    """One press of Book: the answer the agent passes on. The journal decides first whether CTMS is asked at all."""
    import book_journal as J
    t0 = time.time()
    now = now or datetime.now()
    orders = [str(o) for o in job.get("orders") or []]
    out = {"ok": False, "said": "", "trips": [], "seconds": None}
    dry = bool(job.get("dry"))
    k = J.key(orders, job.get("date"))
    if not dry:
        if _lock() is None:
            out["said"] = "Another booking is still finishing on the home PC: press it again in a minute. Nothing was booked."
            return out
        e = J.get(k)
        if J.verdict(e) == "recall":
            e = recall(k, R)
        v = J.verdict(e)
        mans = and_list([t["manifest"] for t in J.accepted(e)]) if J.accepted(e) else ""
        if v == "recall":
            out["said"] = ("The last press of Book for this order is still waiting for the work PC's answer, so it isn't "
                           "booked again. Give it a few minutes: what it made is picked up by itself. If CTMS shows "
                           "nothing for it, Clear it on the Bookings card and press Book again.")
            out["pending"] = True
            return out
        if v == "hold":
            out["said"] = ("Not booked again: " + (f"you pressed Stop on it after {mans or 'nothing'} ACCEPTED, so the rest "
                                                  "isn't booked and nothing has followed it"
                                                  if e.get("state") == "stopped" else
                                                  f"{', '.join(e.get('short') or [])} was left short of ACCEPTED in CTMS"
                                                  if e.get("state") == "half" else
                                                  "the last press never said what it made")
                           + ". Look in CTMS, then Clear it on the Bookings card (or finish it there) and press Book again.")
            out["held"] = True
            return out
        if v == "finished":
            out.update(ok=True, said=f"Already booked: {mans}, and everything after it is done. Nothing booked again.",
                       trips=J.accepted(e))
            return out
        if v == "resume":
            said = [f"Already booked in CTMS: {mans}. Nothing booked again; finishing what was left."]
            said += follow(k, R, now)
            e = J.get(k)
            out.update(ok=True, said=" ".join(said), trips=J.accepted(e), resumed=True, total=round(time.time() - t0, 1))
            return out
    try:                               # his 10 + 20 (27/11): worked out before anything in CTMS is touched
        planned = plan_loads(job, record_of(job.get("record")) or job.get("record_copy") or {})
    except ValueError as x:
        out["said"] = f"{x}. Nothing was booked."
        out["refused"] = True
        return out
    if job.get("loads"):
        R = R or _client()
        if not bridge_takes_loads(R):
            out["said"] = (f"The work PC's Book can't set the loads yet ({planned}): its bridge needs the update that "
                           "brings them, or it would halve the line. Book the parts on their own, or tick Split "
                           "equally. Nothing was booked.")
            out["refused"] = True
            return out
    first = owed_first(orders)
    before = [planned + "."] if planned else []
    if first and not dry:
        # his 03/11: what's missing on a line is dealt with, not gone past - the to-do's update (times, the delivery
        # comment, services, the Veh Type) is typed in first, by the same run the to-do's Run button uses
        went, how = run_owed(first)
        if not went:
            out["said"] = f"{how} Nothing was booked."
            return out
        before.append(how)
    R = R or _client()
    args = {k_: job[k_] for k_ in ("orders", "date", "carrier", "trailer", "vehicles", "dry") if job.get(k_) not in (None, "")}
    if job.get("haulage") not in (None, ""):
        args["haulage"] = float(job["haulage"])
    if job.get("loads"):
        args["loads"] = job["loads"]
    rec = record_of(job.get("record")) or job.get("record_copy") or {}     # a record already off the map, carried
    try:                               # the copies the ledger knows of: Book books no other (his 26/11)
        import order_ledger
        known = order_ledger.known_lines(orders)
    except Exception:
        known = []
    if known:
        args["known"] = known
    qty = quantities(rec)
    if qty:
        args["qty"] = qty
    # his 09/11: the well's Order Filters on the order's region (the delivery end) - and its strategy when known - first
    region = job.get("region") or region_for(rec.get("postcode"))
    if region:
        args["region"] = region
    strategy = job.get("strategy") or strategy_for(rec)
    if not strategy and not dry and orders and not os.environ.get("R2_NO_CARD_READ"):
        # his 24/11 "the book button has a gap with not checking the strategy types": a Business Type an earlier booking
        # left on hid three orders in one afternoon. When the toolkit can't tell the order's own, its card says it.
        # (The tests set R2_NO_CARD_READ: their stand-in CTMS must never become the real one through this read.)
        strategy = order_strategy(orders[0])
        if strategy:
            before.append(f"Its Business Type read off its card in CTMS ({strategy}), so another's can't hide it.")
    if strategy:
        args["strategy"] = strategy
    wait = min(780, 150 + 90 * int(job.get("vehicles") or 1) + 30 * max(1, len(orders))
               + 60 * len(job.get("loads") or []))          # each part's card set to its load
    numbered = []
    if not dry:
        if rec.get("id") and not job.get("record_copy"):
            # the record as it is now, on the journal: an ad hoc leaves the map once booked (or the map's cap pushes it
            # off), and what follows - the site email above all - must still know its request and contact (his 24/11:
            # an RDA order went "no site thread and no contact" because its record had gone)
            job["record_copy"] = rec
        J.asking(job)

        def on_id(cid):
            numbered.append(cid)             # the work PC has it from here: only its answer says what was made
            J.asked(k, cid)
        args["on_id"] = on_id
    try:
        result, payload = _quiet(R.ask_waiting, "ctms_book", wait_total=wait, **args)
    except Exception as x:
        if dry:
            raise
        if getattr(x, "code", None) == 4 or numbered:
            # a dashboard error once the command was numbered is not CTMS's answer: what it made is looked for again
            out["said"] = (("The work PC didn't answer in time" if getattr(x, "code", None) == 4 else
                            f"{x} The work PC's answer couldn't be had") + ": it may still be booking. Don't book it by "
                           "hand: press Book again in a few minutes and I'll pick up what it made rather than book it twice.")
            out["pending"] = True
            return out
        J.answered(k, False, str(x), [], job.get("carrier"))        # refused before the work PC had it: nothing made
        out["said"] = f"{x} Nothing was booked."
        out["refused"] = True
        return out
    payload = payload or {}
    trips = payload.get("trips") or []
    out.update(trips=[{k_: t.get(k_) for k_ in ("manifest", "status", "revenue", "cost", "total")} for t in trips],
               seconds=payload.get("seconds"), stages=payload.get("stages"), ctms=result.get("detail"))
    if dry:
        out.update(ok=bool(result.get("ok")), said=str(result.get("detail") or "The work PC didn't answer."))
        return out
    pressed = bool(payload.get("stop_pressed"))
    e = J.answered(k, result.get("ok"), result.get("detail"), trips, job.get("carrier"), pressed=pressed)
    made = J.accepted(e)
    if pressed:
        # Stop pressed (16/11): what CTMS made is kept, and nothing more is done by itself - no row, no email, still on
        # the map - and nothing books the rest: the Bookings card holds it till CTMS has been looked at
        out["stopped"] = True
        out["said"] = str(result.get("detail") or "Stopped by you.") + (
            " Nothing has followed it: no DigiHaul row, no site email, and it stays on the map. Look in CTMS, then "
            "Clear it on the Bookings card." if made else "")
        return out
    if not made:
        out["said"] = str(result.get("detail") or "The work PC didn't answer.")
        return out
    said = before + [f"{and_list([t['manifest'] for t in made])} ACCEPTED with {job['carrier']} in "
                     f"{payload.get('seconds')} seconds"
                     + (f" (cost {made[0].get('total') or made[0].get('cost')}, revenue {made[0].get('revenue')})"
                        if len(made) == 1 else "") + "."]
    fixed = [n for n in payload.get("notes") or []
             if "put right" in n or "put up to" in n or "PUT BACK BY HAND" in n or "split into" in n
             or "set to their loads" in n]
    if fixed:
        said.append("On the lines first: " + "; ".join(fixed) + ".")
    priced = [str(n) for n in payload.get("priced") or []]    # a quote is the TOTAL: the haulier's own lines came off it
    if priced:
        said.append("Price: " + "; ".join(priced) + ".")
    by_hand = [str(n) for n in payload.get("notes") or []
               if str(n).startswith(("CLOSE BY HAND", "CHECK BY HAND", "CHECK THE COST BY HAND"))]
    if by_hand and result.get("ok"):                          # a stop's own words carry them already
        said.append("; ".join(by_hand) + ".")
    if not result.get("ok"):
        said.append(f"Then CTMS stopped: {result.get('detail')} What was ACCEPTED is followed up below.")
    for t in made:
        if len(t.get("lines") or []) > 1:
            said.append(f"{t['manifest']} has {len(t['lines'])} lines: {t.get('took', 1)} went on from selecting them in one go"
                        + (f", the other {len(t['lines']) - t.get('took', 1)} by Apply to Trip." if t.get("took", 1) < len(t["lines"]) else "."))
    said += follow(k, R, now)
    import pickup_split
    split_rec = record_of(job.get("record")) or {"orders": orders}
    if pickup_split.is_split(split_rec):     # the order is split by day: this day's own comment goes on what was made
        said.append("Split order: " + (pickup_split.note(split_rec, job["date"]) or "one day") + " By hand: change the comment "
                    f"on the order made for {job['date']} to read that day only ({pickup_split.short(job['date'])}).")
    e = J.get(k) or {}
    out.update(ok=True, said=" ".join(said), email=bool(((e.get("steps") or {}).get("site_email") or {}).get("ok")),
               total=round(time.time() - t0, 1))
    if "pass_email" in (e.get("steps") or {}):
        out["pass_email"] = bool(e["steps"]["pass_email"].get("ok"))
    return out


# -- Book approved: his ticked list, one after another
def not_ready(rec):
    """Why an order isn't strictly ready to book, in words - "" when it is (his rule 03/11: nothing missing, nothing
    amber, the site has answered). Checked here again whatever the dashboard showed: the tracker may have moved since."""
    if not rec or not rec.get("orders"):
        return "it's no longer on the map or the tracker"
    kind = rec.get("kind")
    if kind in ("adhoc", "dts"):
        return ""                                    # its details came on the form
    if kind in ("pinned", "collection"):
        return "it isn't a delivery the desk books"
    answered = rec.get("phoned_at") or rec.get("ctms_veh")
    if rec.get("details_in") and not answered:
        # an email came in about it before anyone asked (his 27/11): the details are in that email, not in CTMS yet -
        # Veh Type filled in CTMS (or a call's form) says they are
        m = rec["details_in"]
        return (f"an email came in about it ({m.get('who') or m.get('sender') or 'someone'} {m.get('when') or ''}): "
                "check it and put the details in CTMS first")
    if not (answered or rec.get("reply_at")):
        return "the site hasn't replied"
    if not answered and rec.get("missing"):
        return "still missing: " + ", ".join(str(m) for m in rec["missing"])
    amber = [k for k, v in (rec.get("details") or {}).items() if isinstance(v, dict) and v.get("confidence") == "amber"]
    if amber:
        return "not confirmed yet: " + ", ".join(sorted(amber))
    return ""


def go_on(res):
    """Whether the next booking of the batch may start: only after one that booked, or one that stopped before touching
    anything ("Nothing was booked"). A refusal (Stop pressed, acting off), Stop pressed during a booking, an answer still
    to come, a half-made trip or a stop part way leaves CTMS for him to look at first."""
    if res.get("refused") or res.get("pending") or res.get("held") or res.get("stopped"):
        return False
    if res.get("ok"):
        return True
    return "Nothing was booked" in str(res.get("said") or "") or bool(res.get("skipped"))


def _progress(R, run_id, i, state, said="", manifests=()):
    if run_id in (None, ""):
        return
    try:
        R.http("POST", "/api/ctms/book/progress", {"run": run_id, "i": i, "state": state, "said": str(said)[:500],
                                                   "manifests": list(manifests)})
    except Exception:
        pass                             # the page told is never worth a booking


def batch(jobs, run_id=None, R=None, now=None):
    """Each approved job booked in turn, through book() and so the journal: one already booked is finished, not booked
    again. Stops at the first that leaves CTMS needing a look. Returns {ok, said, results}."""
    R = R or _client()
    t0 = time.time()
    results = []
    stopped, by_you = "", False
    for i, job in enumerate(jobs):
        named = " / ".join(str(o) for o in job.get("orders") or [])
        _progress(R, run_id, i, "running")
        why = not_ready(record_of(job.get("record")))
        if why:
            res = {"ok": False, "skipped": True, "said": f"Not booked: {why}. Nothing was booked.", "trips": []}
        else:
            try:
                res = book(dict(job), R=R, now=now)
            except Exception as e:
                res = {"ok": False, "said": f"The booking failed before it finished: {e}. Look at CTMS.", "trips": []}
        mans = [t.get("manifest") for t in res.get("trips") or [] if t.get("manifest") and t.get("status") == "ACCEPTED"]
        state = "booked" if res.get("ok") else "skipped" if res.get("skipped") else "not booked"
        _progress(R, run_id, i, state, res.get("said"), mans)
        results.append({"orders": job.get("orders"), "ok": bool(res.get("ok")), "state": state, "said": res.get("said"),
                        "manifests": mans})
        if not go_on(res):
            stopped, by_you = named, bool(res.get("stopped"))
            break
    booked = sum(1 for r in results if r["ok"])
    said = f"{booked} of {len(jobs)} booked"
    if stopped:
        said += ((f"; you pressed Stop during {stopped}" if by_you else f"; stopped at {stopped} so CTMS can be looked at")
                 + (f", {len(jobs) - len(results)} not started" if len(jobs) > len(results) else ""))
    skipped = [r for r in results if r["state"] != "booked"]
    if skipped:
        said += ". " + " ".join(f"{' / '.join(r['orders'] or [])}: {r['said']}" for r in skipped)
    return {"ok": bool(booked) and not stopped, "said": said, "results": results,
            "trips": [{"manifest": m, "status": "ACCEPTED"} for r in results for m in r["manifests"]],
            "seconds": round(time.time() - t0, 1)}


def retry(now=None):
    """The home PC's timer (agent.py, every few minutes): answers never heard looked for again, and Outlook's steps that
    failed tried again on their own clock. Nothing is asked of CTMS but the work PC's own record."""
    import book_journal as J
    if _lock() is None:
        return {"ok": True, "said": "a booking is running: next time", "did": []}
    did = []
    for k in J.unanswered():
        e = recall(k)
        did.append(f"{k}: {(e or {}).get('state')}")
    for k, steps in J.due():
        words = follow(k, now=now, auto=True, only=steps)
        did.append(f"{k}: " + " ".join(words))
    return {"ok": True, "said": f"{len(did)} booking(s) looked at", "did": did}


def clear(k, step=None):
    """His Done by hand / Clear on the Bookings card."""
    import book_journal as J
    e = J.by_hand(k, step)
    return {"ok": e is not None, "said": "cleared" if e is not None else "that booking is no longer on file",
            "state": (e or {}).get("state")}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if argv[:1] == ["retry"]:
        res = retry()
        print(res["said"])
        for d in res["did"]:
            print("  " + d)
        print(json.dumps(res, default=str))
        return 0
    if argv[:1] == ["batch"] and len(argv) >= 2:
        run_id = None
        if "--run" in argv:
            try:
                run_id = int(argv[argv.index("--run") + 1])
            except (IndexError, ValueError):
                run_id = None
        try:
            res = batch(json.loads(argv[1]), run_id)
        except Exception as e:
            res = {"ok": False, "said": f"The batch failed before it finished: {e}. Look at CTMS.", "results": [],
                   "trips": []}
        print(res["said"])
        print(json.dumps(res, default=str))
        return 0 if res["ok"] else 1
    if argv[:1] == ["clear"] and len(argv) >= 2:
        res = clear(argv[1], argv[2] if len(argv) > 2 else None)
        print(json.dumps(res, default=str))
        return 0 if res["ok"] else 1
    if len(argv) < 2 or argv[0] != "run":
        print(__doc__)
        return 2
    try:
        res = book(json.loads(argv[1]))
    except Exception as e:
        res = {"ok": False, "said": f"The booking run failed before it finished: {e}. Look at CTMS before pressing it again.",
               "trips": []}
    print(res["said"])
    print(json.dumps(res, default=str))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
