"""
Rail Plan builder (first cut).

Takes the raw CTMS "Short Rail Report" export (.csv) and produces the weekly
rail plan the way the SOP describes:
  * insert a "Leg" column (=1) after Trip Number
  * drop the columns that aren't used
  * drop manual / non-supplier orders (keep only the rail suppliers)
  * group the rows by DELIVERY DAY with a weekday separator row
  * write the master plan, then a plan per supplier-depot

    python rail_plan.py "<raw short_rail_rep .csv>"

Supplier-plan grouping is by collection depot (From Post Code), confirmed from
the real finished plans:
    DN16 1BP (Scunthorpe) -> British Steel
    DN6 0AA  (Askern)     -> Inframat / VAS   (Inf + VAS + the BS172943 code)
    SO40 4UT (Marchwood)  -> Arcelor Mittal
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

# collection depot (From Post Code prefix) -> (plan name, filename suffix)
def plan_for(from_loc, from_pc):
    pc = (from_pc or "").strip().upper().replace(" ", "")
    fl = (from_loc or "").strip().lower()
    if pc.startswith("DN161"):
        return ("British Steel", "BS")
    if pc.startswith("DN60"):
        return ("Inframat / VAS", "Inf VAS")
    if pc.startswith("SO40") or fl.startswith("ams"):
        return ("Arcelor Mittal", "AMS")
    return ("Other", "Other")


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


def _refs_from_plan_xlsx(path):
    """Every Order Reference in a finished rail-plan .xlsx - skips the header,
    the black day-separator rows and blanks (they have no Order Reference)."""
    import openpyxl
    refs = set()
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return refs
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        try:
            hdr = next(rows)
        except StopIteration:
            continue
        col = next((i for i, h in enumerate(hdr or [])
                    if str(h or "").strip().lower() == "order reference"), None)
        if col is None:
            continue
        for row in rows:
            v = row[col] if col < len(row) else None
            if v is not None and str(v).strip():
                refs.add(str(v).strip())
    try:
        wb.close()
    except Exception:
        pass
    return refs


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


def previous_order_refs(wc, found=None):
    """Order References on the latest issue of this week's plans in Outlook - the master and each
    supplier's, every one at its highest version, whoever sent it. A set, or None if no earlier plan
    is found (so a whole fresh plan is never painted green). Only used on a current-week UPDATE.

    Each plan at its own latest, not just the newest email: the team sends a supplier's plan on its own
    ("RE: Rail Plan wc 19.10 - BS"), and comparing against that alone would paint every other
    supplier's rows green."""
    if found is None:
        found = _plan_mail(wc)
    latest = {}                                  # suffix -> (version, item, attachment index)
    for _, it, plans in found or []:             # newest first: a tie on version keeps the newest
        for j, _, v, sfx in plans:
            if sfx.lower() not in latest or v > latest[sfx.lower()][0]:
                latest[sfx.lower()] = (v, it, j)
    if not latest:
        return None
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp(prefix="railprev_")
    refs = set()
    try:
        for n, (_, it, j) in enumerate(latest.values()):
            try:
                p = os.path.join(tmpdir, f"{n}.xlsx")
                it.Attachments.Item(j).SaveAsFile(p)
                refs |= _refs_from_plan_xlsx(p)
            except Exception:
                continue
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return refs or None


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


def build(path, out_dir=None, update=False):
    hdr, data = load_raw(path)
    idx = {h.lower(): i for i, h in enumerate(hdr)}
    fl_i, fpc_i, dd_i, sch_i = idx["from location"], idx["from post code"], idx["delivery date"], idx["schedule"]
    car_i = idx.get("carrier name")

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
    kept, dropped, mism = [], [], []
    for r in data:
        if not any(c.strip() for c in r):
            continue
        oref = r[ordref_i] if ordref_i < len(r) else ""
        pdesc = r[pdesc_i] if pdesc_i is not None and pdesc_i < len(r) else ""
        pcode = r[pcode_i] if pcode_i is not None and pcode_i < len(r) else ""
        sup = supplier_of(r[fl_i])
        if is_adhoc(oref, pdesc, pcode):
            dropped.append((oref, "adhoc"))
            continue
        if sup is None:
            dropped.append((oref, f"not a rail supplier (From {r[fl_i]})"))
            continue
        sch = parse_schedule(r[sch_i])   # intended delivery day (reliable)
        dd = parse_del_date(r[dd_i])     # stated delivery date (check against sch)
        kept.append((r, sup, sch, dd))

    wc = week_commencing([sch for _, _, sch, _ in kept])
    # flag rows whose stated delivery date doesn't match the scheduled day (CTMS mis-plan)
    for r, sup, sch, dd in kept:
        if sch and (dd is None or dd != sch):
            mism.append((r[idx["order reference"]], r[sch_i], r[dd_i]))

    # What has gone round for this week already (sent from here or by the team):
    # each plan is named one version up from its last issue, and an UPDATE
    # (current-week) highlights the manifests that are NEW since then green.
    found = _plan_mail(wc)
    top = issued(found)
    prev_refs = previous_order_refs(wc, found) if update else None

    DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def write_plan(rows, suffix):
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active
        ws.title = f"wc {wc.strftime('%d.%m')}" if wc else "Rail Plan"
        ws.append(out_hdr)
        for cell in ws[1]:                       # header row - yellow
            cell.fill = FILL_HEADER
        # group by delivery-day weekday, in Mon..Sun order; unknown/mismatch last
        by_day, carriers = {}, set()
        for r, sup, sch, dd in rows:
            k = sch.weekday() if sch else 99
            by_day.setdefault(k, []).append((r, sch))
            if car_i is not None and car_i < len(r) and str(r[car_i] or "").strip():
                carriers.add(str(r[car_i]).strip())
        for k in sorted(by_day):
            ws.append([DAYS[k] if k < 7 else "CHECK - date mismatch"] + [""] * (len(out_hdr) - 1))
            for cell in ws[ws.max_row]:          # day-separator bar - black w/ bold white text
                cell.fill = FILL_DAY
                cell.font = FONT_DAY
            for r, sch in by_day[k]:
                ws.append(shape(r, sch))
                # new manifest since the previous plan -> highlight the row green
                if update and prev_refs:
                    ref = str(r[ordref_i]).strip() if ordref_i < len(r) else ""
                    if ref and ref not in prev_refs:
                        for cell in ws[ws.max_row]:
                            cell.fill = FILL_NEW
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
        return p, name, sum(len(v) for v in by_day.values()), carriers

    # master = all kept
    mpath, mfile, mcount, mcarr = write_plan(kept, "")
    # per supplier-plan
    plans = {}
    for r, sup, sch, dd in kept:
        pn, sfx = plan_for(r[fl_i], r[fpc_i])
        plans.setdefault((pn, sfx), []).append((r, sup, sch, dd))
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
            print(f"  UPDATE: no previous rail plan found in Outlook for wc {wcs} - nothing highlighted green.")
        else:
            cur = {str(r[ordref_i]).strip() for r, _, _, _ in kept if ordref_i < len(r) and str(r[ordref_i]).strip()}
            newr = sorted(cur - prev_refs)
            print(f"  UPDATE: {len(newr)} new manifest(s) highlighted green"
                  + ((": " + ", ".join(newr)) if newr else " (none new)."))
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
    return wc, made, mism


def recipients_for(m):
    """To-list for one plan file: its supplier chain (per plan_to_chain) +
    always the DHL colleagues + the hauliers actually on that plan."""
    chain_key = RECIP.get("_plan_to_chain", {}).get(m["suffix"])
    to = list(RECIP.get("chains", {}).get(chain_key, [])) if chain_key else []
    to += RECIP.get("dhl_always", [])
    hem, unmatched = haulier_emails(m["carriers"])
    to += hem
    return list(dict.fromkeys(x for x in to if x)), unmatched


def sendoff(path, send=False, update=False):
    """Build the plans then draft/send one email per plan to its recipients.
    Plans are written to the outbox so they're downloadable from the dashboard.
    update=True (current-week) greens the new manifests vs the previous plan."""
    wc, made, mism = build(path, update=update)
    wcs = wc.strftime("%d.%m") if wc else "TBC"
    outlook = acct = ns = None
    if send:
        import win32com.client, build_drafts as bd, send_order as so
        ns = bd.get_ns(); acct = so.dhl_account(ns)
        outlook = win32com.client.Dispatch("Outlook.Application")
    print(f"\n=== RAIL PLAN SEND-OFF wc {wcs}  ({'SENDING' if send else 'PREVIEW - nothing sent'}) ===")
    for m in made:
        to, unmatched = recipients_for(m)
        label = m["chain"] or "MASTER"
        subj = f"Rail Plan wc {wcs}" + (f" - {m['chain']}" if m["chain"] else "")
        print(f"\n[{label}]  attach: {m['name']}  ->  {len(to)} recipients")
        print("   TO: " + "; ".join(to))
        if unmatched:
            print("   !! carrier(s) not matched to a haulier email: " + ", ".join(unmatched))
        if send:
            import build_drafts as bd, send_order as so
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
                print("   ABORT: could not bind DHL account - NOT sent"); continue
            mail.Send()
            print("   SENT")
            _mark_sent(m["path"], m["name"])         # gone out: the work PC files it in the Rail Plans folder
    if send and ns is not None:
        try:
            ns.SendAndReceive(False)
        except Exception:
            pass


if __name__ == "__main__":
    a = sys.argv[1:]
    update = "--update" in a                      # current-week update: green the new manifests
    a = [x for x in a if x != "--update"]
    if a and a[0] == "send":
        if len(a) < 2 or not os.path.exists(a[1]):
            print("Usage: python rail_plan.py send <raw csv> [go] [--update]"); sys.exit(1)
        sendoff(a[1], send=(len(a) > 2 and a[2].lower() == "go"), update=update)
    elif a and os.path.exists(a[0]):
        build(a[0], update=update)
    else:
        print("Usage: python rail_plan.py <raw csv> [--update]   |   "
              "python rail_plan.py send <raw csv> [go] [--update]")
