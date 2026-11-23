"""
Rail Plan builder (first cut).

Takes the raw CTMS "Short Rail Report" export (.csv) and produces the weekly
rail plan the way the SOP describes:
  * insert a "Leg" column (=1) after Trip Number
  * drop the columns that aren't used
  * drop manual / non-supplier orders (keep only the rail suppliers)
  * group the rows by DELIVERY DAY with a weekday separator row
  * write the master plan, then a plan per supplier-depot
  * on an update: new orders green, cancelled ones red, a vehicle reg new for
    VAS or AMS/RMS orange - against the plan that last went round

    python rail_plan.py "<raw short_rail_rep .csv>"

Supplier-plan grouping is by collection depot (From Post Code) and, where two
suppliers share one, the From Location's prefix - the SOP's table, see plan_for.
"""
import sys, os, csv, re, json, io, codecs
from datetime import datetime, date, timedelta
from openpyxl.styles import PatternFill, Font, Alignment
import outbox

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    RECIP = json.load(open(os.path.join(HERE, "_rail_recipients.json"), encoding="utf-8"))
except Exception:
    RECIP = {}

# A plan as the team names it, and as build() writes it: "Rail Plan wc 02.11 v2 BS.xlsx" (no supplier =
# the master). The version counts the issues of that plan, whatever the day: wc 19.10's BS plan went v1
# (Thu 15/10), v2 (Tue 20/10), v3 (Thu 22/10), and wc 28.09 was on v5 by the Wednesday.
PLAN_FILE = re.compile(r"Rail Plan wc (\d{2}\.\d{2}) v(\d{1,2})((?: [A-Za-z]+){0,4})\.xlsx", re.I)
# The plans that went out by email - agent.py marks these (and never a preview) for the work PC to file
# in the team's Rail Plans folder.
SENT = os.path.join(HERE, "_rail_sent.json")
SENT_DAYS = 7


def plan_file(name):
    """(week commencing 'DD.MM', version, supplier suffix - '' for the master) of a plan's file name, or None."""
    m = PLAN_FILE.fullmatch(str(name or "").strip())
    return (m.group(1), int(m.group(2)), m.group(3).strip()) if m else None

_COMMON = {"haulage", "transport", "transports", "services", "service", "rail", "freight",
           "logistics", "hire", "ltd", "limited", "the", "of", "and", "co", "uk", "group", "sons"}
_HAULIER_ALIAS = {"dhl northern operating centre": "dhl noc", "hhl": "hotspur hire (hhl)"}


def _core(s):
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split()
            if len(t) >= 3 and t not in _COMMON]


def haulier_emails(carriers):
    """Match plan Carrier Names to the haulier contact list. Returns (emails,
    unmatched-carrier-names)."""
    hcfg = RECIP.get("hauliers", {})
    emails, unmatched = [], []
    for car in carriers:
        c = _HAULIER_ALIAS.get(str(car).strip().lower(), str(car).strip().lower())
        addrs = hcfg.get(c)
        if not addrs:
            for key, a in hcfg.items():
                if any(t in key.lower() for t in _core(c)):
                    addrs = a
                    break
        if addrs:
            emails += addrs
        elif "dhl" not in c:
            unmatched.append(car)
    return list(dict.fromkeys(emails)), unmatched

# Colours, matched from the real finished plans:
FILL_HEADER = PatternFill("solid", fgColor="FFFF00")    # header row - yellow
FILL_DAY = PatternFill("solid", fgColor="000000")       # day-separator bar - black
FONT_DAY = Font(bold=True, color="FFFFFF")              # ...with bold white text
FILL_NEW = PatternFill("solid", fgColor="92D050")       # new order (update) - green
FILL_CANCELLED = PatternFill("solid", fgColor="FF0000") # cancelled (update) - red
FILL_REG = PatternFill("solid", fgColor="FFC000")       # vehicle-reg update - orange
CENTER = Alignment(horizontal="center", vertical="center")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# The supplier plans the SOP ("Running the Rail Plan", sent by him 23/11) has go out, by the suffix their files
# carry -> the email chain in _rail_recipients.json, which is also the name the plan goes out under. The
# chains file's own "_plan_to_chain" can add to or override this.
PLAN_CHAIN = {"BS": "British Steel", "VAS": "VAS", "Inf VAS": "Inframat / VAS", "Inf": "Inframat",
              "Arcelor": "Arcelor Mittal", "AMS RMS": "AMS/RMS", "AMS": "AMS SO40"}
# The SOP: the hauliers give the vehicle reg for what they collect from VAS and AMS/RMS (the port at Goole),
# and once it is in, the line goes round again in orange.
ORANGE_PLANS = {"VAS", "AMS RMS"}
# A manual rail order comes off the plan, whoever supplies it - the SOP's example is an M and seven digits.
MANUAL_REF = re.compile(r"\s*M\d{5,}(?:[_-][A-Za-z0-9]+)*\s*", re.I)
POSTCODE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", re.I)
# The text columns before the dates a comma can spill out of (see mend), the likeliest first.
SPILL_COLS = ("product description", "to location", "carrier name", "booking reference")
REG = re.compile(r"\breg(?:istration)?\b(?:\s*(?:no\.?|number))?\s*[:.#-]?\s*([A-Z0-9]{2,4}\s?[A-Z0-9]{3})\b", re.I)


def vehicle_reg(notes):
    """The vehicle reg in an order's notes ("Vehicle Reg: AB12 CDE" -> "AB12CDE"), or "". A plate has a digit in
    it, so "Reg: pending" is no reg."""
    for m in REG.finditer(str(notes or "")):
        if any(ch.isdigit() for ch in m.group(1)):
            return re.sub(r"\s+", "", m.group(1)).upper()
    return ""


def is_adhoc(order_ref, product_desc, product_code):
    """Manual/adhoc rail orders are excluded from the rail plan. Caught by the
    'ADHOC' product, an AH-style adhoc order reference, or (main rule) a From
    Location that isn't one of the rail suppliers."""
    blob = f"{order_ref} {product_desc} {product_code}".lower()
    if "adhoc" in blob or "ad hoc" in blob:
        return True
    if re.match(r"\s*ah\d", str(order_ref or "").lower()):
        return True
    return False

DROP_COLS = {"del point ref", "product code", "collection date",
             "earliest coll time", "latest coll time", "instructions"}

# From Location prefix -> supplier (rows whose prefix isn't here are MANUAL/other and dropped)
SUPPLIER_PREFIX = [("bri", "British Steel"), ("bs", "British Steel"), ("vas", "VAS"),
                   ("ams", "Arcelor Mittal"), ("inf", "Inframat"), ("wm", "Whitemoor"),
                   ("whit", "Whitemoor")]

def plan_for(from_loc, from_pc):
    """(chain, file-name suffix) of the supplier plan a row goes in, or None: on the master only. By the depot it
    is collected from and, where two suppliers share one, whose stock it is - the SOP's table (23/11):
        British Steel    Bri...         DN16 1BP  Scunthorpe
        VAS              VAS...         DN14 5SS  the port at Goole
        AMS/RMS          AMS...         DN14 5SS
        Arcelor Mittal   AMS...         DN14 5SY
        AMS SO40         AMS...         SO40 4UT  Marchwood
        Inframat / VAS   VAS... Inf...  DN6 0AA   Askern
        Inframat         AMS...         DN6 0AA
    Whitemoor's rows have no plan of their own, and a supplier's row from a depot the table doesn't name is said
    (build's no_plan), not guessed into a plan."""
    pc = re.sub(r"\s+", "", str(from_pc or "")).upper()
    fl = str(from_loc or "").strip().lower()
    if pc.startswith("DN161"):
        sfx = "BS"
    elif pc.startswith("DN60"):
        sfx = "Inf" if fl.startswith("ams") else "Inf VAS"
    elif pc.startswith("SO40"):
        sfx = "AMS"
    elif pc == "DN145SY":
        sfx = "Arcelor"
    elif pc == "DN145SS" and fl.startswith(("ams", "vas")):
        sfx = "AMS RMS" if fl.startswith("ams") else "VAS"
    else:
        return None
    return PLAN_CHAIN[sfx], sfx


def supplier_of(from_loc):
    fl = (from_loc or "").strip().lower()
    for pre, name in SUPPLIER_PREFIX:
        if fl.startswith(pre):
            return name
    return None


def parse_del_date(v):
    v = str(v or "").strip()
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except Exception:
            pass
    return None


def parse_schedule(v):
    """Schedule is YYMMDD (260713 -> 13/07/2026) - the CTMS-intended delivery
    day, and the reliable key for the week + day grouping."""
    m = re.match(r"\s*(\d{2})(\d{2})(\d{2})\s*$", str(v or ""))
    if m:
        try:
            return date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    return None


def week_commencing(dates):
    ds = [d for d in dates if d]
    if not ds:
        return None
    monday = min(ds)
    monday = monday.fromordinal(monday.toordinal() - monday.weekday())  # back to Monday
    return monday


def _cp1252_fallback(err):
    """Decode one stray Windows-1252 byte inside an otherwise UTF-8 file."""
    return err.object[err.start:err.end].decode("cp1252", "replace"), err.end


codecs.register_error("cp1252_fallback", _cp1252_fallback)


def load_raw(path):
    """The raw Short Rail Report, whatever CTMS encoded it as.

    The export is not consistently encoded, and reading it as UTF-8 meant one
    byte could stop the whole plan being built. The 15/09 report (63 orders,
    schedules 260914-260925) died on byte 0x96 at offset 4920 - a Windows-1252
    en dash in a delivery instruction - while the SAME file carried en dashes
    written properly as UTF-8 (e2 80 93) elsewhere. So it is genuinely mixed,
    and neither decoder alone can read it: UTF-8 raises on the 0x96, cp1252
    turns every real UTF-8 dash into "a-euro-quote" mojibake that would then be
    printed on a supplier's plan.

    Decoding as UTF-8 with a per-byte cp1252 fallback is the one reading that
    gets both right, because the error handler only ever sees the bytes UTF-8
    could not explain.
    """
    raw = open(path, "rb").read()
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8):]
    text = raw.decode("utf-8", "cp1252_fallback")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    hdr = [h.strip() for h in rows[0]]
    return hdr, rows[1:]


def mend(row, hdr):
    """(the row with exactly the header's columns, sure) - (None, False) when it can't be told where its extra
    cells belong.

    CTMS does not quote the text it exports (not one quote mark in a whole export), so a comma inside one spills
    the rest of it into the columns after. An order of wc 16.11 came out as "RAIL SHORT, 56E1, 350HT, 9.144M"
    across four cells, its From Location read "9.144M", and the plan dropped it as not a rail supplier: an order
    missing from every plan, nothing said. The extra cells go back into the text column before the dates that
    leaves the From Post Code a postcode and the Delivery Date a date. When those two read right as they are,
    the commas are in the text after the dates, where nothing can be checked: the extra goes into Order Notes
    (so a vehicle reg in it is still read) and sure is False, so the row is said, to look at its contact and
    notes."""
    n, row = len(hdr), list(row)
    if len(row) <= n:
        return row + [""] * (n - len(row)), True
    idx = {h.lower(): i for i, h in enumerate(hdr)}
    fpc, dd = idx.get("from post code"), idx.get("delivery date")

    def ok(cells):
        return ((fpc is None or POSTCODE.fullmatch(str(cells[fpc]).strip()))
                and (dd is None or parse_del_date(cells[dd])))

    def merged(cells, col):
        extra = len(cells) - n
        return cells[:col] + [",".join(cells[col:col + extra + 1])] + cells[col + extra + 1:]

    if not any(str(c).strip() for c in row[n:]) and ok(row[:n]):
        return row[:n], True                            # only commas at the end of the line
    cells = row
    while len(cells) > n:
        for name in SPILL_COLS:
            if name in idx and ok(merged(cells, idx[name])):
                return merged(cells, idx[name]), True
        if str(cells[-1]).strip():
            break
        cells = cells[:-1]                              # a comma at the end of the line as well: one cell fewer
    if ok(row[:n]):
        return merged(row, idx.get("order notes", n - 1)), False
    return None, False


def _fill(cell):
    """A cell's solid fill as RRGGBB, or ''."""
    try:
        f = cell.fill
        v = f.fgColor.rgb if f is not None and f.fill_type == "solid" else ""
        return v[-6:].upper() if isinstance(v, str) and len(v) >= 6 else ""
    except Exception:
        return ""


def _is_red(rgb):
    try:
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    except (ValueError, IndexError, TypeError):
        return False
    return r >= 0xC0 and g <= 0x60 and b <= 0x60


def _weekday(v):
    """0 (Monday) .. 6 from a plan's Schedule or Delivery Date cell, or None."""
    if isinstance(v, (datetime, date)):
        return v.weekday()
    d = parse_schedule(v) or parse_del_date(v)
    return d.weekday() if d else None


def _plan_rows(path):
    """Each order on a finished rail plan .xlsx: [{"ref", "red", "day", "cells": {column, lower case: value}}] -
    "red" if it was coloured red (cancelled) on that issue, "day" the weekday it sits under (its Schedule or
    Delivery Date, else the day bar or Date cell above it). The header, the day bars and blank rows are skipped.
    [] if it can't be read."""
    import openpyxl
    out = []
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return out
    for ws in wb.worksheets:
        hdr, col, day = None, None, None
        for row in ws.iter_rows():
            vals = [c.value for c in row]
            if hdr is None:
                low = [str(v or "").strip().lower() for v in vals]
                if "order reference" in low:
                    hdr, col = low, low.index("order reference")
                continue
            first = str(vals[0] or "").strip().capitalize() if vals else ""
            if first in DAYS:                           # a day bar, or the team's Date cell beside the day's first row
                day = DAYS.index(first)
            ref = str(vals[col] if col < len(vals) and vals[col] is not None else "").strip()
            if not ref:
                continue
            cells = {h: vals[i] for i, h in enumerate(hdr) if h and i < len(vals)}
            d = next((w for w in (_weekday(cells.get("schedule")), _weekday(cells.get("delivery date")))
                      if w is not None), day)
            out.append({"ref": ref, "red": _is_red(_fill(row[col])), "day": d, "cells": cells})
    try:
        wb.close()
    except Exception:
        pass
    return out


def _refs_from_plan_xlsx(path):
    """Every Order Reference in a finished rail-plan .xlsx."""
    return {r["ref"] for r in _plan_rows(path)}


def _plan_mail(wc):
    """Every email in the DHL mailbox with one of this week's plans attached, newest first:
    [(when, item, [(attachment index, wc, version, suffix)])] - or None if the mailbox could not be read.

    Sent Items and the whole Inbox tree. The team's own issues are filed into Inbox > ADHOC > Synergy
    Upload, never left in the Inbox, so the old look at the Inbox and Sent Items alone found only the
    plans sent from here - an update then compared against a plan days out of date."""
    if wc is None:
        return None
    wcs = wc.strftime("%d.%m")
    since = datetime.combine(wc, datetime.min.time()) - timedelta(days=21)   # the names carry no year
    try:
        import build_drafts as bd
        dhl = bd.dhl_store(bd.get_ns())
        roots = [f for f in (bd.sub(dhl, "Sent Items"), bd.sub(dhl, "Inbox")) if f]
    except Exception:
        return None
    if not roots:
        return None
    flt = "@SQL=(\"urn:schemas:httpmail:subject\" LIKE '%rail plan%')"
    found = []

    def look(folder, depth):
        try:
            if depth and int(folder.DefaultItemType) != 0:
                return                          # a calendar, contacts... - not mail
            items = folder.Items.Restrict(flt)
        except Exception:
            items = []
        for it in items:
            try:
                rt = next((v for v in (getattr(it, a, None) for a in ("ReceivedTime", "SentOn"))
                           if v is not None and 1990 < getattr(v, "year", 0) < 2100), None)
                if rt is None:
                    continue
                when = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute, rt.second)
                if when < since:
                    continue
                atts = it.Attachments
                plans = [(j,) + p for j in range(1, atts.Count + 1)
                         for p in [plan_file(atts.Item(j).FileName)] if p and p[0] == wcs]
                if plans:
                    found.append((when, it, plans))
            except Exception:
                continue
        if depth < 8:
            try:
                for i in range(1, folder.Folders.Count + 1):
                    look(folder.Folders.Item(i), depth + 1)
            except Exception:
                pass

    for r in roots:
        look(r, 0)
    found.sort(key=lambda x: x[0], reverse=True)
    return found


def issued(found):
    """{suffix, lower case ('' = the master): the highest version of that plan already gone round}."""
    top = {}
    for _, _, plans in found or []:
        for _, _, v, sfx in plans:
            top[sfx.lower()] = max(top.get(sfx.lower(), 0), v)
    return top


def previous_plans(found):
    """The latest issue of each of this week's plans in the mailbox, as it went round: {suffix, lower case ('' =
    the master): its rows (see _plan_rows)} - every plan at its own highest version, whoever sent it. {} when
    none went round."""
    latest = {}                                  # suffix -> (version, item, attachment index)
    for _, it, plans in found or []:             # newest first: a tie on version keeps the newest
        for j, _, v, sfx in plans:
            if sfx.lower() not in latest or v > latest[sfx.lower()][0]:
                latest[sfx.lower()] = (v, it, j)
    if not latest:
        return {}
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp(prefix="railprev_")
    out = {}
    try:
        for n, (sfx, (_, it, j)) in enumerate(latest.items()):
            try:
                p = os.path.join(tmpdir, f"{n}.xlsx")
                it.Attachments.Item(j).SaveAsFile(p)
                out[sfx] = _plan_rows(p)
            except Exception:
                continue
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out


def _on_plan(prev):
    """The orders still on the plans that went round: a row they coloured red had been cancelled."""
    return {r["ref"] for rows in (prev or {}).values() for r in rows if not r["red"]}


def previous_order_refs(wc, found=None):
    """Order References on the latest issue of this week's plans in Outlook - the master and each
    supplier's, every one at its highest version, whoever sent it - leaving out the ones those issues had
    in red (cancelled). A set, or None if no earlier plan is found (so a whole fresh plan is never painted
    green). Only used on a current-week UPDATE.

    Each plan at its own latest, not just the newest email: the team sends a supplier's plan on its own
    ("RE: Rail Plan wc 19.10 - BS"), and comparing against that alone would paint every other
    supplier's rows green."""
    if found is None:
        found = _plan_mail(wc)
    return _on_plan(previous_plans(found)) or None


def _mark_sent(path, name, now=None):
    """Note that a plan went out by email, these very bytes - agent.py then marks it for the work PC to
    file in the team's Rail Plans folder. Kept a week."""
    import hashlib
    now = now or datetime.now()
    try:
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        try:
            with open(SENT, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            rec = {}
        cutoff = (now - timedelta(days=SENT_DAYS)).isoformat(timespec="seconds")
        rec = {n: r for n, r in (rec.items() if isinstance(rec, dict) else [])
               if isinstance(r, dict) and str(r.get("at") or "") >= cutoff}
        rec[name] = {"sha256": sha, "at": now.isoformat(timespec="seconds")}
        tmp = SENT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
        os.replace(tmp, SENT)
    except Exception as e:
        print(f"   (not noted for the shared folder: {e})")


def build(path, out_dir=None, update=False, info=None):
    """The plans from a raw Short Rail Report -> (week commencing, [plan made], [mis-dated row]). `info`, a dict,
    is filled with what a send-off checks before anything goes out (hold_reason): the rows kept, their days, whether
    this week's earlier issues could be read from the mailbox, the rows that could not be read - and what an update
    coloured (the new manifests green, the cancelled red, a new vehicle reg orange) and which rows are on the master
    only, their depot in no supplier's plan."""
    hdr, data = load_raw(path)
    idx = {h.lower(): i for i, h in enumerate(hdr)}
    fl_i, fpc_i, dd_i, sch_i = idx["from location"], idx["from post code"], idx["delivery date"], idx["schedule"]
    car_i, notes_i = idx.get("carrier name"), idx.get("order notes")

    # kept columns = original order, minus DROP_COLS, with Leg inserted after Trip Number
    keep_cols = [i for i, h in enumerate(hdr) if h.lower() not in DROP_COLS]
    out_hdr = []
    for i in keep_cols:
        out_hdr.append(hdr[i])
        if hdr[i].lower() == "trip number":
            out_hdr.append("Leg")

    def shape(row, sch=None):
        out = []
        for i in keep_cols:
            v = row[i] if i < len(row) else ""
            # correct a mis-planned delivery date to the day it's categorised under
            if sch is not None and i == dd_i and parse_del_date(v) != sch:
                v = sch.strftime("%d-%b-%y")
            out.append(v)
            if hdr[i].lower() == "trip number":
                out.append("1")
        return out

    ordref_i = idx["order reference"]
    pdesc_i, pcode_i = idx.get("product description"), idx.get("product code")
    kept, dropped, mism, unreadable, mended, check = [], [], [], [], [], []
    in_export = set()            # every order the export has, kept or not: one gone from it is no longer planned
    for n, r in enumerate(data, start=2):
        if not any(str(c).strip() for c in r):
            continue
        oref = str(r[ordref_i] if ordref_i < len(r) else "").strip()
        if oref:
            in_export.add(oref)
        fixed, sure = mend(r, hdr)
        if fixed is None:
            if is_adhoc(oref, "", "") or MANUAL_REF.fullmatch(oref):
                dropped.append((oref, "adhoc" if is_adhoc(oref, "", "") else "manual order"))
            else:
                unreadable.append(oref or f"line {n}")
            continue
        if len(r) > len(hdr) and any(str(c).strip() for c in r[len(hdr):]):
            (mended if sure else check).append(oref)
        r = fixed
        pdesc = r[pdesc_i] if pdesc_i is not None else ""
        pcode = r[pcode_i] if pcode_i is not None else ""
        if is_adhoc(oref, pdesc, pcode):
            dropped.append((oref, "adhoc"))
            continue
        if MANUAL_REF.fullmatch(oref):
            dropped.append((oref, "manual order"))
            continue
        sup = supplier_of(r[fl_i])
        if sup is None:
            dropped.append((oref, f"not a rail supplier (From {r[fl_i]})"))
            continue
        sch = parse_schedule(r[sch_i])   # intended delivery day (reliable)
        dd = parse_del_date(r[dd_i])     # stated delivery date (check against sch)
        kept.append((r, sup, sch, dd, plan_for(r[fl_i], r[fpc_i])))

    wc = week_commencing([k[2] for k in kept])
    # flag rows whose stated delivery date doesn't match the scheduled day (CTMS mis-plan)
    for r, _, sch, dd, _ in kept:
        if sch and (dd is None or dd != sch):
            mism.append((r[ordref_i], r[sch_i], r[dd_i]))

    # What has gone round for this week already (sent from here or by the team): each plan is named one version
    # up from its last issue, and an UPDATE (current-week) colours what changed since then, the SOP's way - new
    # orders green, cancelled ones red, a vehicle reg new for VAS or AMS/RMS orange. Nothing carries over from the
    # last issue's colours: its green and orange go plain, and its red rows are left off.
    found = _plan_mail(wc)
    top = issued(found)
    prev = previous_plans(found) if update else {}
    prev_refs = (_on_plan(prev) or None) if update else None
    coloured = {"new": set(), "cancelled": set(), "regs": set()}

    def reg_before(ref, sfx):
        """The vehicle reg the plans that went round gave this order - its own plan's issue first."""
        for key in [sfx.lower()] + [k for k in prev if k != sfx.lower()]:
            for pr in prev.get(key, []):
                if pr["ref"] == ref and not pr["red"]:
                    return vehicle_reg(pr["cells"].get("order notes"))
        return ""

    def colour(r, plan):
        if not prev_refs:
            return None
        ref = str(r[ordref_i]).strip()
        if ref and ref not in prev_refs:                 # new manifest since the last issue
            coloured["new"].add(ref)
            return FILL_NEW
        if plan and plan[1] in ORANGE_PLANS and notes_i is not None:
            now = vehicle_reg(r[notes_i])
            if now and now != reg_before(ref, plan[1]):  # the haulier's reg is in (or changed) since
                coloured["regs"].add(ref)
                return FILL_REG
        return None

    def cancelled(sfx, have):
        """This plan's orders on its last issue that the export no longer has: (day, cells, carrier) each, to go
        back on in red - once, as a row already red on that issue is left off."""
        out = []
        for pr in prev.get(sfx.lower(), []) if prev_refs else []:
            if pr["red"] or pr["ref"] in in_export or pr["ref"] in have:
                continue
            have.add(pr["ref"])
            coloured["cancelled"].add(pr["ref"])
            cells = []
            for h in out_hdr:
                v = "1" if h == "Leg" else pr["cells"].get(h.lower())
                v = v.strftime("%d-%b-%y") if isinstance(v, (datetime, date)) else ("" if v is None else v)
                cells.append(v)
            out.append((pr["day"] if pr["day"] is not None else 99, cells,
                        str(pr["cells"].get("carrier name") or "").strip()))
        return out

    def write_plan(rows, suffix):
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active
        ws.title = f"wc {wc.strftime('%d.%m')}" if wc else "Rail Plan"
        ws.append(out_hdr)
        for cell in ws[1]:                       # header row - yellow
            cell.fill = FILL_HEADER
        # group by delivery-day weekday, in Mon..Sun order; unknown/mismatch last
        by_day, carriers, have = {}, set(), set()
        for r, sup, sch, dd, plan in rows:
            by_day.setdefault(sch.weekday() if sch else 99, []).append((shape(r, sch), colour(r, plan)))
            have.add(str(r[ordref_i]).strip())
            if car_i is not None and str(r[car_i] or "").strip():
                carriers.add(str(r[car_i]).strip())
        for k, cells, car in cancelled(suffix, have):
            by_day.setdefault(k, []).append((cells, FILL_CANCELLED))
            if car:
                carriers.add(car)                # the haulier is told its job is off
        for k in sorted(by_day):
            ws.append([DAYS[k] if k < 7 else "CHECK - date mismatch"] + [""] * (len(out_hdr) - 1))
            for cell in ws[ws.max_row]:          # day-separator bar - black w/ bold white text
                cell.fill = FILL_DAY
                cell.font = FONT_DAY
            for cells, fill in by_day[k]:
                ws.append(cells)
                if fill is not None:
                    for cell in ws[ws.max_row]:
                        cell.fill = fill
        # centre every cell, and size each column to its content
        for row in ws.iter_rows():
            for c in row:
                c.alignment = CENTER
        for col in ws.columns:
            mx = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max(mx + 2, 10), 55)
        wcs = wc.strftime("%d.%m") if wc else "TBC"
        name = (f"Rail Plan wc {wcs} v{top.get(suffix.lower(), 0) + 1}"
                + (f" {suffix}" if suffix else "") + ".xlsx")
        p = os.path.join(out_dir, name) if out_dir else outbox.path(name)
        wb.save(p)
        return p, name, len(rows), carriers

    # master = all kept
    mpath, mfile, mcount, mcarr = write_plan(kept, "")
    # per supplier-plan
    plans, no_plan = {}, []
    for k in kept:
        if k[4] is None:
            if k[1] != "Whitemoor":                 # Whitemoor has no plan of its own; any other is said
                no_plan.append(f"{str(k[0][ordref_i]).strip()} (from {k[0][fl_i]} {k[0][fpc_i]})")
            continue
        plans.setdefault(k[4], []).append(k)
    # a supplier whose every order this week is now cancelled still gets its plan, all red
    known = {s.lower(): (c, s) for s, c in PLAN_CHAIN.items()}
    for sfx in prev if prev_refs else []:
        if sfx in known and known[sfx] not in plans and any(
                not pr["red"] and pr["ref"] not in in_export for pr in prev[sfx]):
            plans[known[sfx]] = []
    made = [{"path": mpath, "name": mfile, "count": mcount, "chain": None, "suffix": "", "carriers": mcarr}]
    for (pn, sfx), rows in plans.items():
        p, f, c, carr = write_plan(rows, sfx)
        made.append({"path": p, "name": f, "count": c, "chain": pn, "suffix": sfx, "carriers": carr})

    print(f"Week commencing: {wc}  |  kept {len(kept)} rows, dropped {len(dropped)} manual/non-supplier")
    if found is None and wc:
        print("  ! Could not read the mailbox for this week's earlier issues - every plan is named v1.")
    if update:
        wcs = wc.strftime("%d.%m") if wc else "TBC"
        if prev_refs is None:
            print(f"  UPDATE: no previous rail plan found in Outlook for wc {wcs} - nothing coloured.")
        else:
            for what, key in (("new manifest(s) highlighted green", "new"), ("cancelled, back on in red", "cancelled"),
                              ("vehicle reg update(s) in orange", "regs")):
                got = sorted(coloured[key])
                print(f"  UPDATE: {len(got)} {what}" + ((": " + ", ".join(got)) if got else "."))
    if mended:
        print("  MENDED (a comma in a text column had spilled it across the columns): " + ", ".join(mended))
    if check:
        print("  !! CHECK the contact and notes of (commas in the text after the dates): " + ", ".join(check))
    if unreadable:
        print("  !! COULD NOT READ (where its extra cells belong can't be told): " + ", ".join(unreadable))
    if no_plan:
        print("  ON THE MASTER ONLY (its depot is in no supplier's plan): " + "; ".join(no_plan))
    if dropped:
        print("  EXCLUDED (adhoc / manual / not a rail supplier):")
        for o, reason in dropped:
            print(f"     {o}  ({reason})")
    if mism:
        print(f"  ~ {len(mism)} row(s) had a wrong delivery date - corrected to the scheduled day:")
        for o, sch, dd in mism:
            print(f"     {o}  was {dd}  ->  {sch}")
    print("  FILES:")
    for m in made:
        print(f"     {m['count']:3} rows  {(m['chain'] or 'MASTER'):16}  {m['name']}")
    try:
        import metrics
        metrics.log("rail_plan_built", files=len(made), rows=len(kept), update=update)
        if mism:
            metrics.log("date_corrected", n=len(mism))   # CTMS mis-planned dates fixed
    except Exception:
        pass
    if info is not None:
        refs = {str(k[0][ordref_i]).strip() for k in kept if str(k[0][ordref_i]).strip()}
        info.update(kept=len(kept), days=sorted({k[2] for k in kept if k[2]}),
                    undated=sum(1 for k in kept if not k[2]), mail_read=found is not None,
                    new=sorted(refs - prev_refs) if update and prev_refs is not None else None,
                    cancelled=sorted(coloured["cancelled"]), regs=sorted(coloured["regs"]),
                    no_plan=no_plan, unreadable=unreadable, check=check)
    return wc, made, mism


def recipients_for(m):
    """To-list for one plan file: its supplier chain (PLAN_CHAIN, or the chains file's _plan_to_chain) +
    always the DHL colleagues + the hauliers actually on that plan -> (to, unmatched carriers, missing):
    `missing` names the chain of a supplier plan the chains file has no addresses for - such a plan must not
    go to the DHL colleagues and hauliers alone, as if the supplier had it."""
    chain_key = {**PLAN_CHAIN, **(RECIP.get("_plan_to_chain") or {})}.get(m["suffix"]) if m["suffix"] else None
    chain = list(RECIP.get("chains", {}).get(chain_key, [])) if chain_key else []
    to = chain + RECIP.get("dhl_always", [])
    hem, unmatched = haulier_emails(m["carriers"])
    to += hem
    missing = (chain_key or m["suffix"]) if m["suffix"] and not chain else ""
    return list(dict.fromkeys(x for x in to if x)), unmatched, missing


def hold_reason(info, wc, week=None):
    """Why plans built from this export must not go out by themselves - '' when they may. The Rail plan card's
    one go sends with no preview (his 16/11), so what a look at the preview used to catch is checked here: no rows
    to send, another week's rows, a row with no day, a row that could not be read (an order no plan would show), or
    this week's earlier issues unreadable (every plan would go out as v1, whatever has gone round)."""
    if not info.get("kept"):
        return "the export has no rail-supplier rows"
    if info.get("unreadable"):
        bad = info["unreadable"]
        return f"{len(bad)} row(s) of the export could not be read ({', '.join(str(b) for b in bad[:4])})"
    if info.get("undated"):
        return f"{info['undated']} row(s) have no schedule day"
    days = info.get("days") or []
    if week is not None and (wc != week or not days or days[-1] > week + timedelta(days=6)):
        return (f"the export runs {days[0]:%d/%m} to {days[-1]:%d/%m}, not the week of {week:%d/%m}" if days
                else f"the export is not for the week of {week:%d/%m}")
    if not info.get("mail_read"):
        return "the mailbox could not be read for this week's earlier issues, so the versions could be wrong"
    return ""


def sendoff(path, send=False, update=False, week=None, out_dir=None):
    """Build the plans then draft/send one email per plan to its recipients.
    Plans are written to the outbox so they're downloadable from the dashboard.
    update=True (current-week) greens the new manifests vs the previous plan. week (its Monday): the week the
    plans must be for - nothing goes out when they are not, or when hold_reason finds another reason. -> what
    happened: {wc, send, held, sent: [{name, rows, to, chain}], failed: [{name, why}], new, cancelled, regs,
    no_plan, check, unmatched}."""
    info = {}
    wc, made, mism = build(path, out_dir=out_dir, update=update, info=info)
    wcs = wc.strftime("%d.%m") if wc else "TBC"
    result = {"wc": wcs, "send": bool(send), "held": "", "sent": [], "failed": [], "new": info.get("new"),
              "cancelled": info.get("cancelled") or [], "regs": info.get("regs") or [],
              "no_plan": info.get("no_plan") or [], "check": info.get("check") or [], "unmatched": []}
    held = hold_reason(info, wc, week) if send else ""
    outlook = acct = ns = None
    if send and not held:
        try:
            import win32com.client, build_drafts as bd, send_order as so
            ns = bd.get_ns(); acct = so.dhl_account(ns)
            outlook = win32com.client.Dispatch("Outlook.Application")
        except Exception as e:
            held = f"Outlook could not be opened ({str(e)[:120]})"
    if held:
        result["held"], send = held, False
    print(f"\n=== RAIL PLAN SEND-OFF wc {wcs}  ({'SENDING' if send else 'PREVIEW - nothing sent'}) ===")
    if held:
        print(f"   NOT SENT - {held}.")
    for m in made:
        to, unmatched, missing = recipients_for(m)
        result["unmatched"] += [u for u in unmatched if u not in result["unmatched"]]
        label = m["chain"] or "MASTER"
        subj = f"Rail Plan wc {wcs}" + (f" - {m['chain']}" if m["chain"] else "")
        print(f"\n[{label}]  attach: {m['name']}  ->  {len(to)} recipients")
        print("   TO: " + "; ".join(to))
        if unmatched:
            print("   !! carrier(s) not matched to a haulier email: " + ", ".join(unmatched))
        if missing:
            print(f"   !! no email list for {missing} in _rail_recipients.json - this plan can't go to them")
        if send:
            import build_drafts as bd, send_order as so
            if missing:
                print("   NOT SENT - no email list for " + missing)
                result["failed"].append({"name": m["name"], "why": f"no email list for {missing}"})
                continue
            if not to:
                print("   NOT SENT - nobody to send it to")
                result["failed"].append({"name": m["name"], "why": "nobody to send it to"})
                continue
            try:
                mail = outlook.CreateItem(0)
                to_str, _cc, _rm = bd.clean_to_cc("; ".join(to))
                mail.To = to_str
                mail.Subject = subj
                message = (f"Hi all,\n\nPlease find attached the rail plan for week commencing "
                           f"{wc.strftime('%d/%m/%Y')}"
                           + (f" - {m['chain']}." if m["chain"] else ".")
                           + "\n\nMany thanks.")
                bd._attach_qr(mail)                          # inline QR for the signature
                mail.HTMLBody = bd.html_from_message(message)  # message + your signature
                mail.Attachments.Add(m["path"])
                if not so.bind_account(mail, acct):
                    print("   ABORT: could not bind DHL account - NOT sent")
                    result["failed"].append({"name": m["name"], "why": "the DHL account could not be bound"})
                    continue
                mail.Send()
            except Exception as e:
                print(f"   NOT SENT - Outlook: {e}")
                result["failed"].append({"name": m["name"], "why": f"Outlook: {str(e)[:120]}"})
                continue
            print("   SENT")
            result["sent"].append({"name": m["name"], "rows": m["count"], "to": len(to), "chain": label})
            _mark_sent(m["path"], m["name"])         # gone out: the work PC files it in the Rail Plans folder
    if send and ns is not None:
        try:
            ns.SendAndReceive(False)
        except Exception:
            pass
    return result


if __name__ == "__main__":
    a = sys.argv[1:]
    update = "--update" in a                      # current-week update: green the new manifests
    a = [x for x in a if x != "--update"]
    week = None                                   # --week YYYY-MM-DD: the Monday the plans must be for
    if "--week" in a:
        i = a.index("--week")
        try:
            week = datetime.strptime(a[i + 1], "%Y-%m-%d").date()
        except (IndexError, ValueError):
            print("--week wants that week's Monday as YYYY-MM-DD"); sys.exit(1)
        del a[i:i + 2]
    if a and a[0] == "send":
        if len(a) < 2 or not os.path.exists(a[1]):
            print("Usage: python rail_plan.py send <raw csv> [go] [--update] [--week YYYY-MM-DD]"); sys.exit(1)
        res = sendoff(a[1], send=(len(a) > 2 and a[2].lower() == "go"), update=update, week=week)
        print("RAIL_RESULT " + json.dumps(res))       # what agent.py reads back (the card's one go)
    elif a and os.path.exists(a[0]):
        build(a[0], update=update)
    else:
        print("Usage: python rail_plan.py <raw csv> [--update]   |   "
              "python rail_plan.py send <raw csv> [go] [--update] [--week YYYY-MM-DD]")
