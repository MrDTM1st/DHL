"""
Process an already-filled Haulage Request Form (the usual ad hoc).

Reads the form's own "RHPC Admin - DHL USE ONLY" row - via Excel itself, so
the form's formulas produce the genuine values - and runs it through the
replicated database logic to build the NR upload CSV in the outbox.

    python process_form.py "<path to filled form.xlsx>"
    python process_form.py <reference or filename fragment>   # searches email
    python process_form.py latest                             # newest form in email
"""
import sys, os, re, json
from datetime import datetime
import nr_csv, outbox

HERE = os.path.dirname(os.path.abspath(__file__))
DHL_SMTP = "delali.opoku@dhl.com"
FORM_HINTS = ("haulage request", "transport request", "request form")


def find_form(query):
    import win32com.client
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    dhl = None
    for i in range(1, ns.Folders.Count + 1):
        if ns.Folders.Item(i).Name.lower() == DHL_SMTP:
            dhl = ns.Folders.Item(i)
            break

    def sub(f, name):
        if f is None:
            return None
        for i in range(1, f.Folders.Count + 1):
            c = f.Folders.Item(i)
            if c.Name.strip().lower() == name.strip().lower():
                return c

    inbox = sub(dhl, "Inbox")
    q = (query or "").lower()
    latest = q in ("", "latest")
    out = os.path.join(HERE, "_form.xlsx")
    for folder in (inbox, sub(sub(inbox, "ADHOC"), "DTS")):
        if folder is None:
            continue
        items = folder.Items
        try:
            items.Sort("[ReceivedTime]", True)
        except Exception:
            pass
        for it in items:   # full history, newest first
            try:
                subj = str(it.Subject or "").lower()
                for j in range(1, it.Attachments.Count + 1):
                    att = it.Attachments.Item(j)
                    fn = str(att.FileName)
                    if not fn.lower().endswith((".xlsx", ".xlsm")):
                        continue
                    fl = fn.lower()
                    hit = (any(h in fl or h in subj for h in FORM_HINTS)
                           if latest else (q in fl or q in subj))
                    if hit:
                        att.SaveAsFile(out)
                        return out, fn, folder.Name
            except Exception:
                continue
    return None, None, None


# The first two headers of the 47-column contract. The admin sheet is found
# by NAME first, because every form in the corpus calls it "RHPC Admin"
# something and that stays the fast path - then by this header, because the
# name is not dependable. The Heavy Material Order Request Form puts the same
# 47 columns on a tab called "DHL Upload"; the name test returned None, that
# None was handed to Excel as a sheet index, and the run died on the first
# form of a template nobody had seen before. A header cannot be renamed
# without breaking the upload itself, so it is the safer thing to match.
_ADMIN_HEAD = ("customer order no", "shipment no")
# How far down the admin tab is read. The block ends at its first blank row,
# so this only has to clear the longest: a Project Shoot Load's row per line.
_ADMIN_ROWS = 60


def _pick_admin_sheet(names, row1_of):
    """The name of the tab holding the RHPC admin row, or None."""
    for n in names:
        if str(n).strip().lower().startswith("rhpc admin"):
            return n
    for n in names:
        try:
            got = [str(v).strip().lower() for v in (row1_of(n) or [])[:2]
                   if v is not None]
        except Exception:
            continue
        if tuple(got) == _ADMIN_HEAD:
            return n
    return None


def read_rhpc_rows(path):
    """Open the form in Excel (invisible) so its formulas evaluate, and read
    the RHPC Admin rows. Falls back to cached values if Excel is unavailable."""
    rows = None
    try:
        import win32com.client
        xl = win32com.client.Dispatch("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(os.path.abspath(path), ReadOnly=True, UpdateLinks=0)
        try:
            names = [s.Name for s in wb.Worksheets]
            target = _pick_admin_sheet(
                names, lambda n: wb.Worksheets(n).Range("A1:B1").Value[0])
            if target is None:
                raise ValueError("no admin sheet by name or header")
            sh = wb.Worksheets(target)
            rows = sh.Range(sh.Cells(1, 1), sh.Cells(_ADMIN_ROWS, 60)).Value
        finally:
            wb.Close(False)
            xl.Quit()
    except Exception:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wbo = openpyxl.load_workbook(path, data_only=True)
        target = _pick_admin_sheet(
            wbo.sheetnames,
            lambda n: [c.value for c in next(
                wbo[n].iter_rows(min_row=1, max_row=1, max_col=2))])
        if target is None:
            raise ValueError(
                "No admin sheet in %s: no tab is named 'RHPC Admin*' and none "
                "carries the 47-column header row." % os.path.basename(path))
        sho = wbo[target]
        rows = [[c.value for c in r] for r in sho.iter_rows(min_row=1, max_row=_ADMIN_ROWS, max_col=60)]
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    # The RHPC Admin templates put a spacer on row 2 and the data from row 3
    # (row 4 being the return leg). Newer single-sheet exports put the data
    # straight under the header, some carry more than two rows, and a PROJECT
    # SHOOT LOAD form has a row per material LINE - twelve on a two-order load -
    # so a fixed two-row slice dropped rows without a word. The block is read
    # from row 2 down to its first blank row, which also keeps a stray error
    # cell below a gap out of the upload; merge_shoot_lines then folds a shoot
    # load's lines into one record per order. Rows are NOT filtered by order
    # number here: a "_R" return leg has its own ref and must stay, and main()
    # drops exact-duplicate refs.
    for r in rows[1:]:
        d = {headers[i]: r[i] for i in range(len(headers)) if headers[i]}
        if d.get("Customer Order No") in (None, ""):
            if out:
                break          # end of the block
            continue           # the RHPC templates' spacer row
        out.append(d)
    out = merge_shoot_lines(out, path)
    repair_quantities(out, path)
    repair_products(out, path)
    repair_weights(out, path)
    repair_times(out, path)
    repair_postcodes(out)
    repair_phones(out)
    return out


# Excel's error values, in BOTH shapes this pipeline meets them. openpyxl
# (data_only) hands back the text "#VALUE!"; Excel COM hands back the raw
# CVErr code, a large negative int. read_rhpc_rows prefers COM, so the code
# is what actually reached the upload.
_XL_ERR_TEXT = ("#VALUE!", "#REF!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#DIV/0!")
_XL_ERR_LO, _XL_ERR_HI = -2146826300, -2146826200


def is_excel_error(v):
    """True for a cell that holds an Excel error rather than a value.

    A PROJECT SHOOT LOAD sheet computes Product Qty arithmetically from its
    "Total Pallet QTY" box, and requesters fill that in as text - "1 Box".
    Arithmetic on text is #VALUE!, which COM reports as -2146826273, and that
    went through every check untouched: it is an int, it is not blank, so an
    upload went out with a quantity of minus two billion. The corpus shows
    the other face of the same fault, quantities written as 0 or left empty.
    """
    if isinstance(v, bool):
        return False
    if isinstance(v, int) and _XL_ERR_LO <= v <= _XL_ERR_HI:
        return True
    return str(v).strip().upper() in _XL_ERR_TEXT


def _leading_number(v):
    """The count at the front of a free-text quantity: "1 Box" -> 1."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(v or ""))
    if not m:
        return None
    n = float(m.group(1))
    return int(n) if n == int(n) else n


def _pallet_box(ws):
    """(count, text) typed in this sheet's "Total Pallet QTY" box, or (None, "")
    when it has none - left empty, the next thing along is the "Total Pallet FP"
    label, which has no number."""
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 80)):
        for i, cell in enumerate(row):
            if not re.search(r"total\s*pallet\s*qty", str(cell.value or ""), re.I):
                continue
            for nxt in row[i + 1:]:
                if nxt.value in (None, ""):
                    continue
                n = _leading_number(nxt.value)
                return (n, str(nxt.value).strip()) if n is not None else (None, "")
    return None, ""


def shoot_load_qty(path):
    """(count, unit_text) recovered from the input sheet, or (None, "").

    Read straight off the "Total Pallet QTY" box the requester typed into,
    which is the only place the real figure survives - the RHPC tab holds
    the result of arithmetic on it, and that arithmetic is what failed. The
    template's "Example" tab has a box of its own, filled with 5: an empty
    box on the real sheet must not borrow it.
    """
    try:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return None, ""
    for ws in wb.worksheets:
        if ws.max_row > 200 or ws.title.strip().lower() == "example":
            continue                      # address/reference tabs, the worked example
        n, text = _pallet_box(ws)
        if n is not None:
            return n, text
    return None, ""


def _note_unit(d, unit):
    """Keep the words of a typed quantity ("1 Box") in the instructions.

    "1 Box" only ever existed to be multiplied, so the words are lost once the
    number is taken. Against a Pallet_NDC line a bare 1 reads as a pallet; a
    10kg box is a different vehicle.
    """
    if unit and re.search(r"[a-z]", unit, re.I):
        instr = str(d.get("Delivery Instructions") or "").strip()
        if unit.lower() not in instr.lower():
            d["Delivery Instructions"] = (instr + " / " + unit).strip(" /")


def shoot_load_lines(path, refs):
    """A PROJECT SHOOT LOAD form's materials table, if this is one:
    ({sales order: its number of lines}, pallets, pallets_text) - else None.

    That form gives every material line its own RHPC row, and each row's
    Product Qty is the line's "Part Pallet Count": the Total Pallet QTY box
    shared evenly over ALL the lines (=$D$28/COUNT(...)). So an order's
    quantity is the sum over its own lines, and every line together is the
    box. Only a table holding this form's orders counts - the template's
    "Example" tab carries the same table with made-up ones.
    """
    try:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return None
    want = {_norm_order(r) for r in refs}
    for ws in wb.worksheets:
        if ws.max_row > 200:
            continue                      # address/reference tabs
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 80)):
            heads = {str(c.value or "").strip().lower(): c.column for c in row}
            if "sales order" not in heads or "part pallet count" not in heads:
                continue
            lines = {}
            for r in range(row[0].row + 1, ws.max_row + 1):
                ref = _norm_order(ws.cell(row=r, column=heads["sales order"]).value)
                if not ref or ref.lower() == "total":
                    break
                lines[ref] = lines.get(ref, 0) + 1
            if want & set(lines):
                n, text = _pallet_box(ws)
                return lines, n, text
            break                         # this tab's table holds other orders
    return None


def merge_shoot_lines(rows, path):
    """One record per order on a PROJECT SHOOT LOAD form, carrying its share of the pallets.

    Each of the form's RHPC rows is one material line. Taken as they came,
    an order's second and later lines were dropped as duplicate rows and the
    order went out with ONE line's share: a two-order load of four pallets
    over twelve lines uploaded as 0.333 of a pallet per order instead of 2.
    The first row of each order is kept and given the order's share; the
    rest are its other lines. With the box left empty there is nothing to
    share, and the quantity is left BLANK - visibly missing - rather than
    the 0 the form computes from it.
    """
    found = shoot_load_lines(path, [d.get("Customer Order No") for d in rows])
    if not found:
        return rows
    lines, pallets, text = found
    every = sum(lines.values())
    out, kept = [], set()
    for d in rows:
        ref = _norm_order(d.get("Customer Order No"))
        if ref not in lines:
            out.append(d)                 # not one of the table's orders - as it was
            continue
        if ref in kept:
            continue                      # another of this order's lines: in its share
        kept.add(ref)
        out.append(d)
        if pallets is None:
            d["Product Qty"] = ""
            print(f"!! {ref}: the Project Shoot Load form's Total Pallet QTY box is empty, so "
                  f"it gives no quantity - left BLANK, fill it in by hand.")
            continue
        share = round(pallets * lines[ref] / every, 3)
        d["Product Qty"] = int(share) if share == int(share) else share
        _note_unit(d, text)
        print(f"   {ref}: {lines[ref]} of the {every} material line(s) on the Project Shoot "
              f"Load form - quantity {d['Product Qty']}, its share of Total Pallet QTY {text!r}.")
    return out


def repair_quantities(rows, path):
    """Replace an error-valued Product Qty with the figure the requester gave.

    Never invents one: if the input sheet cannot be read the quantity is left
    BLANK, which is visibly missing, rather than a number nobody wrote.
    """
    for d in rows:
        q = d.get("Product Qty")
        if not is_excel_error(q):
            continue
        n, unit = shoot_load_qty(path)
        ref = str(d.get("Customer Order No") or "").strip()
        if n is None:
            d["Product Qty"] = ""
            print(f"!! {ref}: Product Qty is an Excel error ({q}) and the input "
                  f"sheet has no readable quantity - left BLANK, fill it by hand.")
            continue
        d["Product Qty"] = n
        _note_unit(d, unit)
        print(f"   {ref}: Product Qty was an Excel error ({q}); recovered "
              f"{n!r} from the input sheet ({unit!r}).")


_TIME_TXT = re.compile(r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$")
_CELL_REF = re.compile(r"(?:'([^']+)'|([A-Za-z0-9_ ]+))?!?\$?([A-Z]{1,3})\$?(\d{1,5})")
_LOOKUP_ARG = re.compile(r"VLOOKUP\(\s*([^,]+),", re.I)
_PRODUCT_COLS = ("Product / Service Code", "Product / Description")


def typed_product(path):
    """What the requester put in the form's product box, or "".

    The admin tab's product is a VLOOKUP of that box in the form's own
    drop-down list; this follows the formula back to the box - through a
    plain "=G31" if there is one - rather than guessing where it sits. A form
    has the one box, and its rows' formulas all point at it, so the first one
    found will do: the order numbers beside them may not be readable at all
    when Excel has not saved its own results into the file.
    """
    sheet, _, cols = _admin_cell_map(path)
    col = next((cols[c] for c in _PRODUCT_COLS if c in cols), None)
    if not (sheet and col):
        return ""
    try:
        import openpyxl
        import warnings
        warnings.filterwarnings("ignore")
        wf = openpyxl.load_workbook(path, data_only=False)
        wv = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return ""
    try:
        m = None
        for row in range(2, _ADMIN_ROWS + 1):
            m = _LOOKUP_ARG.search(str(wf[sheet].cell(row=row, column=col).value or ""))
            if m:
                break
        name = sheet
        for _ in range(4):                        # the box, or a short chain of =A1 hops to it
            hit = _CELL_REF.search(m.group(1)) if m else None
            if not hit:
                return ""
            q, bare, c, r = hit.groups()
            name = (q or bare or name).strip()
            if name not in wf.sheetnames:
                return ""
            f = wf[name]["%s%s" % (c, r)].value
            if isinstance(f, str) and f.startswith("="):
                m = re.match(r"=\s*(.+)$", f)
                continue
            v = wv[name]["%s%s" % (c, r)].value
            return "" if v in (None, "") or is_excel_error(v) else str(v).strip()
        return ""
    finally:
        wf.close()
        wv.close()


def repair_products(rows, path):
    """Replace an error-valued product with what the requester typed.

    The admin tab looks the product box up in the form's own drop-down list,
    so a product typed in rather than picked finds no row and comes back #N/A
    - "RHTT Sandite module" on AH29/10/26YOIP - and Excel's error code went
    out as the item. The words they typed are what they asked for, and nr_csv
    reads a CTMS product type from them. Never invents one: with nothing in
    the box either, the product is left BLANK, which is visibly missing.
    """
    for d in rows:
        bad = [k for k in _PRODUCT_COLS if is_excel_error(d.get(k))]
        if not bad:
            continue
        ref = str(d.get("Customer Order No") or "").strip()
        typed = typed_product(path)
        for k in bad:
            d[k] = typed
        if typed:
            print(f"   {ref}: the product was an Excel error - the form's product box says {typed!r}, used that.")
        else:
            print(f"!! {ref}: the product is an Excel error and the form's product box is empty "
                  f"- left BLANK, fill it in by hand.")


def _as_clock(v):
    """(hour, minute) if the cell holds a time Excel could not add to a date."""
    import datetime as _dt
    if isinstance(v, _dt.time):
        return v.hour, v.minute
    if isinstance(v, _dt.datetime):
        return None                      # a real date, not a loose clock time
    m = _TIME_TXT.match(str(v or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if 0 <= h <= 23 and 0 <= mi <= 59 else None


def formula_time(path, sheet, rownum, want_col):
    """The clock time the form's own formula was reaching for, or None.

    A time cell on the admin tab is never typed - it is the leg's date plus a
    time taken off the human sheet, and this template stores those times as
    TEXT with a leading space (" 08:00", straight out of its depot Lookup
    tab). Date + text is #VALUE!, so the cell errors on every form built from
    this template, not only the one that exposed it.

    Rather than guess where the time lives, which differs per template, this
    follows the reference the broken formula already points at. The form says
    where its own times come from; the only thing it got wrong was the adding.
    """
    try:
        import openpyxl
        import warnings
        warnings.filterwarnings("ignore")
        wf = openpyxl.load_workbook(path, data_only=False)
        wv = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return None
    try:
        f = str(wf[sheet].cell(row=rownum, column=want_col).value or "")
        if not f.startswith("="):
            return None
        for q, bare, col, row in _CELL_REF.findall(f):
            name = (q or bare or sheet).strip()
            if name not in wv.sheetnames:
                continue
            try:
                cell = wv[name]["%s%s" % (col, row)]
            except Exception:
                continue
            hit = _as_clock(cell.value)
            if hit:
                return hit
        return None
    finally:
        wf.close()
        wv.close()


def _admin_cell_map(path):
    """(sheet name, {order ref: row}, {header: column}) for the admin tab."""
    try:
        import openpyxl
        import warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return None, {}, {}
    try:
        sheet = _pick_admin_sheet(
            wb.sheetnames,
            lambda n: [c.value for c in next(
                wb[n].iter_rows(min_row=1, max_row=1, max_col=2))])
        if sheet is None:
            return None, {}, {}
        ws = wb[sheet]
        cols = {}
        for c in range(1, min(ws.max_column, 60) + 1):
            h = str(ws.cell(row=1, column=c).value or "").strip()
            if h:
                cols.setdefault(h, c)
        rownum = {}
        for r in range(2, min(ws.max_row, 10) + 1):
            ref = _norm_order(ws.cell(row=r, column=1).value)
            if ref:
                rownum.setdefault(ref, r)
        return sheet, rownum, cols
    finally:
        wb.close()


def repair_times(rows, path):
    """Rebuild an error-valued time cell from the date and the form's own cell.

    Never invents a window: a time that cannot be recovered is left BLANK, and
    to_transform_row then applies the usual unconfirmed 09:01-17:01, which is
    visibly ours rather than a number nobody wrote.
    """
    import datetime as _dt
    legs = (("collection_time", "Collection Date"),
            ("collection_time_end", "Collection Date"),
            ("delivery_time", "Delivery Date"),
            ("delivery_time_end", "Delivery Date"))
    sheet, rowmap, cols = None, {}, {}
    looked = False
    for d in rows:
        ref = str(d.get("Customer Order No") or "").strip()
        for field, datekey in legs:
            bad = d.get(field)
            if not is_excel_error(bad):
                continue
            if not looked:
                sheet, rowmap, cols = _admin_cell_map(path)
                looked = True
            r = rowmap.get(_norm_order(ref))
            got = (formula_time(path, sheet, r, cols[field])
                   if sheet and r and field in cols else None)
            if not got:
                d[field] = ""
                print("!! %s: %s is an Excel error (%r) and the form has no "
                      "readable time behind it - left BLANK, the unconfirmed "
                      "window will be used." % (ref, field, bad))
                continue
            base = d.get(datekey)
            if not isinstance(base, _dt.datetime):
                ds, _ = _dt_parts(base)
                base = _dt.datetime.strptime(ds, "%d/%m/%Y") if ds else None
            if base is None:
                d[field] = ""
                print("!! %s: %s recovered %02d:%02d but the leg has no date - "
                      "left BLANK." % (ref, field, got[0], got[1]))
                continue
            d[field] = base.replace(hour=got[0], minute=got[1])
            print("   %s: %s was an Excel error; recovered %02d:%02d from the "
                  "form's own cell." % (ref, field, got[0], got[1]))


_PC_RE = re.compile(r"^([A-Z]{1,2}\d[\dA-Z]?)\s*(\d[A-Z]{2})$")


def repair_phones(rows):
    """Put back the leading zero Excel drops when a phone is typed as a number.

    A requester who types 07700900263 into an unformatted cell leaves Excel
    holding the number 7700900263, and the zero is gone before this code ever
    sees it. Twelve records in the reference corpus are already 10 digits
    starting with 7, so this has been going out for a while: the haulier gets
    a number that will not dial, and rings nobody at the delivery site.

    Deliberately narrow. A UK number is 10 or 11 digits WITH its zero, so a
    bare 10-digit value is one short and the missing digit can only be the
    zero. Anything else is left exactly as typed.
    """
    for d in rows:
        ref = str(d.get("Customer Order No") or "").strip()
        for field in ("Telephone No", "D Telephone No", "Order Contact No"):
            v = d.get(field)
            if v in (None, ""):
                continue
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            t = str(v).strip()
            if not t.isdigit() or len(t) != 10 or t.startswith("0"):
                d[field] = t
                continue
            d[field] = "0" + t
            print("   %s: %s %r is 10 digits - read as %r (Excel stripped the "
                  "leading zero)." % (ref, field, t, d[field]))


def repair_postcodes(rows):
    """Fix a letter O typed for the zero in a postcode's inward half.

    The inward half is ALWAYS digit-letter-letter, so an O in first position
    cannot be a letter - "WS10 OLH" is Bescot Yard's WS10 0LH. Left alone it
    reaches the haulier as the delivery address and is not a real postcode,
    so a sat-nav drops the driver wherever the outward code lands.
    """
    for d in rows:
        ref = str(d.get("Customer Order No") or "").strip()
        for field in ("Postcode", "D Postcode"):
            raw = str(d.get(field) or "").strip().upper()
            if not raw or _PC_RE.match(raw):
                continue
            fixed = re.sub(r"O(?=[A-Z]{2}$)", "0", raw)
            m = _PC_RE.match(fixed)
            if m:
                d[field] = "%s %s" % (m.group(1), m.group(2))
                print("   %s: %s %r is not a postcode - read as %r (a letter O "
                      "cannot start an inward code)."
                      % (ref, field, raw, d[field]))
            else:
                print("!! %s: %s %r is not a valid postcode - CHECK BY HAND "
                      "before this goes to a haulier." % (ref, field, raw))


def fmt_dt(v):
    """Excel encodes 'no date' as the 1899/1900 epoch (a bare time cell reads
    as time(0,0), COM gives 1899-12-30) - those are placeholders for a date
    the requester hasn't set (e.g. a TBC return leg), NOT real dates. They
    must come out EMPTY, never '30/12/1899 00:00' in the upload."""
    import datetime as _dt
    if v is None or v == "":
        return ""
    # An error cell has no time in it. Left to the fallthrough below it came
    # out as the text "#VALUE!" (or "-2146826273" under COM) and landed in a
    # time column of the upload, where nothing downstream reads it as absent.
    # Blank is what the window defaults in to_transform_row are waiting for.
    if is_excel_error(v):
        return ""
    if isinstance(v, _dt.datetime):
        return "" if v.year < 1990 else v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, _dt.time):
        return ""   # a bare time has no date - can't make an upload window
    try:
        return v.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(v)


ADHOC_ACCOUNT = "NRADHOC"   # default when the form leaves the account unset
UNSET_ACCOUNTS = {"", "please select", "select", "none"}


def _norm_order(ref):
    """Normalise an order number for the upload: spaces are not allowed, so a
    reference like 'FS-PLC CARDS' becomes 'FS-PLC-CARDS'. Collapses runs of
    whitespace/hyphens to a single hyphen and trims the ends. Excel hands
    numeric refs over as floats - 1770679.0 must upload as 1770679."""
    if isinstance(ref, float) and ref.is_integer():
        ref = int(ref)
    r = str(ref or "").strip()
    r = re.sub(r"\s+", "-", r)
    r = re.sub(r"-{2,}", "-", r).strip("-")
    return r


def _ref_incomplete(ref):
    """True only if the order number is missing or truncated - blank, or ending
    on a separator (e.g. a blank Collection Ref leaves a bare 'FS-'). A valid
    letters-only reference such as 'FS-PLC-CARDS' is NOT incomplete."""
    r = str(ref or "").strip()
    return (not r) or r[-1] in "-/ " or r.upper() in ("FS", "FS-")


def account_for(d):
    """Keep a preset account; only default to NRADHOC when the form left it
    on 'Please select' / blank."""
    acct = str(d.get("Account") or "").strip()
    return acct if acct.lower() not in UNSET_ACCOUNTS else ADHOC_ACCOUNT


def _dateonly_window(a, b):
    """True for Excel's 'date picked, NO time': a zero-length midnight window
    (start == end == 00:00 on the same day, or no end at all). A real
    midnight job always has a non-zero window (e.g. 00:00-02:00)."""
    import datetime as _dt
    mid = lambda v: (isinstance(v, _dt.datetime) and v.year >= 1990
                     and (v.hour, v.minute) == (0, 0))
    # A leg whose START is gone and whose END is a bare midnight is just as
    # unstated as a midnight-to-midnight pair. That is what a blank closing
    # time looks like once the opening time has been discarded as an error,
    # and the map record read "latest 00:00" - a delivery deadline nobody set,
    # sitting next to a CSV that had correctly used the unconfirmed window.
    if a in (None, "") and mid(b):
        return True
    return mid(a) and (b in (None, "") or (mid(b) and b == a))


def to_transform_row(d):
    r = dict(d)
    r["collection time"] = fmt_dt(d.get("collection_time"))
    r["collection time end"] = fmt_dt(d.get("collection_time_end"))
    r["delivery time"] = fmt_dt(d.get("delivery_time"))
    r["delivery time end"] = fmt_dt(d.get("delivery_time_end"))
    # a date-only window (midnight-to-midnight) means the requester never set
    # a time - blank it so the 09:00-17:00 default below takes over
    if nr_csv.unstated_window(d.get("collection_time"), d.get("collection_time_end")):
        r["collection time"] = r["collection time end"] = ""
    if nr_csv.unstated_window(d.get("delivery_time"), d.get("delivery_time_end")):
        r["delivery time"] = r["delivery time end"] = ""
    # A close left blank is no close, whatever midnight it reads as. See
    # nr_csv.unstated_close. The rules for a start with no end take it from there.
    for k in ("collection time", "delivery time"):
        if nr_csv.unstated_close(r[k], r[k + " end"]):
            r[k + " end"] = ""
    # One date on the form and two times, so a night window closes on the next
    # day. See nr_csv.roll_overnight.
    r["collection time end"] = nr_csv.roll_overnight(r["collection time"], r["collection time end"])
    r["delivery time end"] = nr_csv.roll_overnight(r["delivery time"], r["delivery time end"])
    # Delali (24/07): "if you ever get one where there is no delivery time,
    # just put nine to five so when I upload it the system recognizes it."
    # Only the WINDOW is invented - the date comes from the leg's own date
    # column (the other end's date as a last resort) and a form with no date
    # at all still comes out blank; a date is never made up.
    def _date_of(*keys):
        for k in keys:
            ds, _ = _dt_parts(d.get(k))
            if ds:
                return ds
        return ""
    # 09:01-17:01, not 09:00-17:00: the odd minute is how CTMS shows at a glance
    # that these times are still ours and nobody has confirmed them.
    if not r["collection time"]:
        base = _date_of("Collection Date", "collection_time", "Delivery Date", "delivery_time")
        if base:
            r["collection time"], r["collection time end"] = nr_csv.unconfirmed_window(base)
    if not r["delivery time"]:
        base = _date_of("Delivery Date", "delivery_time", "Collection Date", "collection_time")
        if base:
            # Default the delivery off THIS job's collection window (+1h01m),
            # which is what the real database does - not off a fixed pair.
            ct, cte = r["collection time"], r["collection time end"]
            r["delivery time"], r["delivery time end"] = nr_csv.unconfirmed_window(base, (ct, cte))
            # With no collection end the default is the fixed pair, which can land
            # before a collection that starts after 09:01. Those times are ours, so
            # work them from the collection instead of asking the requester why.
            if ct and not cte and nr_csv.dated(r["delivery time"]) and nr_csv.dated(ct) and nr_csv.dated(
                    r["delivery time"]) < nr_csv.dated(ct):
                r["delivery time"], r["delivery time end"] = nr_csv.unconfirmed_window(
                    base, (ct, nr_csv.close_window(ct)))
            r["delivery time"], r["delivery time end"] = nr_csv.after_collection(
                r["delivery time"], r["delivery time end"], ct)
    # A window with a start but no end used to be closed at the fixed 17:01,
    # which put the delivery marker on collection windows and turned a 22:00
    # start into an end earlier than itself. See nr_csv.close_window.
    #
    # The two legs are closed differently on purpose. A collection start with
    # no end is opening hours, so it gets a working day. A DELIVERY start with
    # no end is a slot the site named, so it gets +2h - the same rule
    # delivery_details already applies to the identical answer when it arrives
    # by email. See nr_csv.slot_window_end.
    if r["collection time"] and not r["collection time end"]:
        r["collection time end"] = nr_csv.close_window(r["collection time"])
    if r["delivery time"] and not r["delivery time end"]:
        r["delivery time end"] = nr_csv.slot_window_end(r["delivery time"])
    r["Account"] = account_for(d)   # preset account wins; else NRADHOC
    return r


def window_notes(d, tr):
    """What the toolkit decided about a leg's dates, for the run's output: every route that builds an upload
    prints these. The date a night window closes on is ours, so it says so. One still ending before it starts
    was not a night shift, and needs a person."""
    out = []
    ref = d.get("Customer Order No")
    for lbl, k in (("collection", "collection time"), ("delivery", "delivery time")):
        s, e = nr_csv.dated(tr.get(k)), nr_csv.dated(tr.get(k + " end"))
        if s and e and e < s:
            out.append(f"!! {ref}: {lbl} window ends before it starts ({tr[k]} to {tr[k + ' end']}) "
                       "- CHECK BY HAND before uploading.")
        elif s and e and e.date() > s.date():
            out.append(f"NOTE {ref}: {lbl} window runs past midnight - closes {tr[k + ' end']} in the CSV.")
    day, _ = _dt_parts(d.get("Delivery Date"))
    s = nr_csv.dated(tr.get("delivery time"))
    if day and s and s.strftime("%d/%m/%Y") != day:
        out.append(f"NOTE {ref}: the form says delivery {day}, but with no time and a collection that runs "
                   f"into the night it goes up as {s:%d/%m/%Y} - the map still shows {day}.")
    return out


# ---------- dashboard map record ----------
# Each processed ad hoc is also saved as a record shaped like a tracker
# record, so the dashboard's brief, haulier ranking and map focus mode all
# work on it unchanged. The agent publishes these on the panel.
ADHOCS = os.path.join(HERE, "_adhocs.json")
FORMS_DIR = os.path.join(HERE, "_adhoc_forms")   # kept to forward with cover requests


def _flag(d, k):
    return str(d.get(k) or "N").strip().upper() not in ("N", "")


def _dt_parts(v):
    """(date_str, time_str) from an Excel cell that may hold a datetime, a
    bare time, or nothing. The 1899/1900 epoch and time(0,0) are Excel's
    'not set' placeholders (a TBC return leg) - they read as EMPTY."""
    import datetime as _dt
    if isinstance(v, _dt.datetime):
        if v.year < 1990:
            return "", (v.strftime("%H:%M") if (v.hour or v.minute) else "")
        return v.strftime("%d/%m/%Y"), v.strftime("%H:%M")
    if isinstance(v, _dt.time):
        return "", (v.strftime("%H:%M") if (v.hour or v.minute) else "")
    # Already-formatted strings, which is what the transform shape carries
    # (nr_csv.dts_row builds 'dd/mm/yyyy HH:MM'). These used to fall through to
    # ("", "") - so a DTS pinned on the map with no dates on it at all.
    for f in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
              "%Y-%m-%d %H:%M"):
        try:
            p = _dt.datetime.strptime(str(v).strip(), f)
        except Exception:
            continue
        if p.year < 1990:
            return "", (p.strftime("%H:%M") if (p.hour or p.minute) else "")
        return p.strftime("%d/%m/%Y"), p.strftime("%H:%M")
    return "", ""


def _covers(qty, prod):
    """True when the qty text already says what the product is ('12 x pallets'
    covers 'PALLET'), so the materials line doesn't need the product repeated.
    Compared on stemmed words: 'Cable Drums' is NOT covered by 'X1 DRUM'
    (the 'cable' is information) so that pair combines."""
    words = {w.rstrip("s") for w in re.findall(r"[a-z]+", qty.lower())}
    pw = [w.rstrip("s") for w in re.findall(r"[a-z]+", prod.lower())]
    return bool(pw) and all(w in words for w in pw)


def _leg_dates(d):
    """(collection_date, coll window, delivery_date, del window) for one row.
    The form has dedicated DATE columns, and collection/delivery can differ
    (collect Thu, deliver Sat) - never derive one date from the other. A
    date-only window (midnight-to-midnight) shows BLANK on the brief - the
    CSV gets the 9-5 default, but the brief never claims a time the
    requester didn't give."""
    # Two shapes reach this. The FORM shape has separate date columns and
    # underscore time keys; the TRANSFORM shape (nr_csv.dts_row, and anything
    # already through to_transform_row) has only the space-form keys, with the
    # date baked into them. Accept either, or a DTS pins on the map with no
    # dates at all.
    ctk = d.get("collection_time", d.get("collection time"))
    ctke = d.get("collection_time_end", d.get("collection time end"))
    dtk = d.get("delivery_time", d.get("delivery time"))
    dtke = d.get("delivery_time_end", d.get("delivery time end"))

    cdate, _ = _dt_parts(d.get("Collection Date"))
    cd2, ct1 = _dt_parts(ctk)
    _, ct2 = _dt_parts(ctke)
    ddate, _ = _dt_parts(d.get("Delivery Date"))
    dd2, dt1 = _dt_parts(dtk)
    _, dt2 = _dt_parts(dtke)
    if _dateonly_window(ctk, ctke):
        ct1 = ct2 = ""
    if _dateonly_window(dtk, dtke):
        dt1 = dt2 = ""
    # the same blank close the CSV leaves out: a haulier must not read "12:00 - 00:00"
    if nr_csv.unstated_close(ctk, ctke):
        ct2 = ""
    if nr_csv.unstated_close(dtk, dtke):
        dt2 = ""
    return (cdate or cd2, {"earliest": ct1, "latest": ct2},
            ddate or dd2, {"earliest": dt1, "latest": dt2})


def _pair_return(rows):
    """The form's row 4 is the RETURN leg of row 3's order (same ref + '_R').
    One order, one email, one map record - so legs are paired, not split."""
    if len(rows) == 2:
        a = str(rows[0].get("Customer Order No") or "").strip()
        b = str(rows[1].get("Customer Order No") or "").strip()
        if a and b == a + "_R":
            return [(rows[0], rows[1])]
    return [(r, None) for r in rows]


def _adhoc_record(d, csv_name, ret=None, form_file="", kind="adhoc", mail=None):
    s = lambda k: str(d.get(k) or "").strip()

    cdate, cwin, ddate, dwin = _leg_dates(d)

    qty = d.get("Product Qty")
    if isinstance(qty, float) and qty.is_integer():
        qty = int(qty)
    qty = str(qty if qty is not None else "").strip()
    prod = s("Product / Description") or s("Product / Service Code")
    # quantities are allowed to be TEXT on these forms ("X1 DRUM",
    # "12 x pallets") - a plain number becomes an "Nx" multiplier, text that
    # already names the product stands alone, otherwise both are kept
    if re.fullmatch(r"\d{1,5}", qty):
        mats = qty + "x " + prod
    elif qty and prod and not _covers(qty, prod):
        mats = prod + " — " + qty
    else:
        mats = qty or prod
    # the weight/dimensions ride inside Delivery Instructions
    # ("... Qty X1 DRUM Weight - 400KG-DRUM W= 580MM X H 1000MM")
    wm = re.search(r"[Ww]eight\s*-?\s*(.+)", s("Delivery Instructions"))
    weight = wm.group(1).strip(" -") if wm else ""

    off = "HIAB" if _flag(d, "HIAB") else ("MOFFETT" if _flag(d, "Moffett") else "")
    rec = {
        "id": kind + "|" + s("Customer Order No") + "|" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "kind": kind,
        "orders": [s("Customer Order No")],
        "site": s("Delivery Point"), "worksite": s("Delivery Point"),
        "postcode": s("D Postcode"),
        "collection_site": s("Site Name - Collection"), "collection_pc": s("Postcode"),
        "collections": [{"site": s("Site Name - Collection"), "pc": s("Postcode")}],
        "materials": mats,
        "qty": qty, "product": prod, "weight": weight,
        "delivery_date": ddate,
        "collection_date": cdate,
        "form_file": form_file,
        "details": {
            "time": dwin,
            "collection_time": cwin,
            "vehicle": {"value": s("Vehicle Type")},
            "offloading": {"value": off},
            "pts": {"value": "yes" if _flag(d, "PTS") else ""},
            "rear_steer": {"value": "yes" if _flag(d, "Rear Steer") else ""},
            "contact": {"name": s("D Contact Name"), "phone": s("D Telephone No")},
        },
        "csv": os.path.basename(csv_name),
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if mail:
        # the email the form came in (monitor_tick put it on the map by itself) - who sent it, and where to find it
        # again to forward it on the same chain once it is booked
        rec["mail"] = {k: str(mail.get(k) or "")[:300] for k in
                       ("from", "subject", "received", "file", "entryid", "store", "conversation")}
    if ret is not None:
        r2 = lambda k: str(ret.get(k) or "").strip()
        rcd, rcwin, rdd, rdwin = _leg_dates(ret)
        rec["return_leg"] = {
            "order": r2("Customer Order No"),
            "collection_date": rcd, "collection_time": rcwin,
            "delivery_date": rdd, "time": rdwin,
            "to_site": r2("Delivery Point"), "to_pc": r2("D Postcode"),
        }
    return rec


def save_adhocs(rows, csv_name, form_path="", keep=8, kind="adhoc", mail=None):
    """Newest first, capped - the map only ever needs the recent handful.
    Keeps a copy of the filled form so the cover-request email can forward it."""
    form_file = ""
    if form_path and os.path.exists(form_path) and rows:
        import shutil
        os.makedirs(FORMS_DIR, exist_ok=True)
        ref = re.sub(r"[^A-Za-z0-9._-]", "-", str(rows[0].get("Customer Order No") or "form"))
        form_file = "Haulage Request Form " + ref + os.path.splitext(form_path)[1]
        shutil.copyfile(form_path, os.path.join(FORMS_DIR, form_file))
    recs = [_adhoc_record(d, csv_name, ret=ret, form_file=form_file, kind=kind, mail=mail)
            for d, ret in _pair_return(rows)]
    return store_adhocs(recs, keep=keep)


def _supersedes(new, old):
    """A record being saved takes the place of an old one with the same order numbers. One that carries SEVERAL orders
    (one lorry's drops, see mail_forms.py) also takes the place of an old one holding only some of them: on 16/11 the
    first form of a two-form email sat on the map by itself, and the combined order had to replace it, not sit beside
    it. A record with one order never swallows a bigger one."""
    return bool(old) and (old == new or (len(new) > 1 and old < new))


def store_adhocs(recs, keep=8):
    """Put these map records on the map: booked-off jobs refused, same orders replaced, newest first, capped."""
    # An unreadable store must NOT become an empty one. This used to be
    # `except: old = []`, so a single failed read replaced the whole map with
    # just the job being processed - it silently binned five live records
    # twice in one day. Keep the bad file so it can be looked at, and never
    # start from empty while a non-empty file is sitting there.
    old = []
    if os.path.exists(ADHOCS):
        try:
            with open(ADHOCS, encoding="utf-8") as f:
                old = json.load(f)
            if not isinstance(old, list):
                raise ValueError("not a list")
        except Exception as ex:
            keep_name = ADHOCS + ".unreadable"
            try:
                os.replace(ADHOCS, keep_name)
                print(f"  !! _adhocs.json unreadable ({type(ex).__name__}) - kept as "
                      f"{os.path.basename(keep_name)}; the map starts from this job only")
            except Exception:
                pass
            old = []
    # A job you have already booked off must not come back just because the form
    # was reprocessed. _booked_drops.json guarded the TRACKER only; nothing on
    # this path ever read it, so the same order was booked off three times in
    # fifteen minutes on 10/08 and a booked DTS reappeared twice.
    try:
        import tracker
        drops = tracker.booked_drops()
        kept = []
        for r in recs:
            if {str(o).strip() for o in r.get("orders", [])} & drops:
                print(f"SKIP: {'/'.join(r.get('orders', []))} is already booked in "
                      f"- not putting it back on the map")
            else:
                kept.append(r)
        recs = kept
    except Exception:
        pass
    # Same order reprocessed - replace its previous record rather than stacking
    # duplicate pins. Keyed on the ORDER NUMBERS, not the id: the id carries a
    # timestamp, so it is different on every run and never matched anything.
    # Reprocessing one form five times left five pins on the same spot, and the
    # stale ones kept whatever dates the form had at the time.
    fresh = [frozenset(str(o).strip() for o in r.get("orders", [])) for r in recs]
    old = [r for r in old
           if not any(_supersedes(f, frozenset(str(o).strip() for o in r.get("orders", []))) for f in fresh)]
    tmp = ADHOCS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump((recs + old)[:keep], f, indent=1)
    os.replace(tmp, ADHOCS)        # atomic: a concurrent reader never sees a partial file
    return len(recs)


def outcome(out):
    """What a run of this script said about a form -> (on the map?, its order or why not) - for monitor_tick, which
    puts forms off the mail straight on the map."""
    if "MAP : job saved" in out:
        m = re.search(r"^Order (\S+)", out, re.M)
        return True, m.group(1) if m else ""
    why = next((ln.strip(" !") for ln in out.splitlines()
                if ln.startswith(("!!", "Nothing written", "MAP : NOT", "SKIP:", "No data", "NOT FOUND"))), "")
    return False, why or "the form did not finish processing"


def main():
    args = sys.argv[1:]
    mail = None
    if "--mail" in args:            # monitor_tick: the email the form came in, as a small JSON file
        i = args.index("--mail")
        try:
            with open(args[i + 1], encoding="utf-8") as f:
                mail = json.load(f)
        except (IndexError, OSError, ValueError):
            mail = None
        del args[i:i + 2]
    arg = args[0].strip() if args else "latest"
    if os.path.exists(arg):
        path, src = arg, "local file"
    else:
        print(f"Searching your mailbox for a filled form ({arg}, full history)...")
        path, fn, where = find_form(arg)
        if not path:
            print(f"NOT FOUND: no form matching '{arg}'.")
            return
        src = f"email attachment '{fn}' (folder: {where})"
    print(f"FORM: {src}")

    rows = read_rhpc_rows(path)
    if not rows:
        print("No data in the form's RHPC Admin row - is it actually filled in?")
        return

    # Order numbers can't contain spaces in the upload - hyphenate them (e.g.
    # 'FS-PLC CARDS' -> 'FS-PLC-CARDS') on both the order and shipment refs.
    for d in rows:
        d["Customer Order No"] = _norm_order(d.get("Customer Order No"))
        if str(d.get("Shipment No") or "").strip():
            d["Shipment No"] = _norm_order(d.get("Shipment No"))

    # a row 4 with the SAME ref as row 3 (no _R suffix) is a form-filling
    # duplicate, not a return leg - keeping it would book the order TWICE
    seen_refs, uniq = set(), []
    for d in rows:
        refn = str(d.get("Customer Order No"))
        if refn in seen_refs:
            print(f"NOTE {refn}: duplicate row on the form (same ref, not a return leg) - ignored.")
            continue
        seen_refs.add(refn)
        uniq.append(d)
    rows = uniq

    # Guard: a truncated order number (e.g. 'FS-' when the Collection Ref was
    # left blank) would be rejected by the upload. Refuse rather than produce a
    # dead file, and say exactly what to fix.
    good, bad = [], []
    for d in rows:
        (bad if _ref_incomplete(d.get("Customer Order No")) else good).append(d)
    for d in bad:
        print(f"!! INCOMPLETE ORDER NUMBER {str(d.get('Customer Order No')).strip()!r} - the form's "
              f"order-number field (e.g. Collection Ref) is blank. Fill it in and re-run; nothing written for this one.")
    if not good:
        print("Nothing written - no usable order number on the form.")
        return
    rows = good
    transformed = [to_transform_row(d) for d in rows]
    records = nr_csv.transform(transformed)

    # A delivery timed before its own collection is not bookable, and which end
    # is wrong is the requester's call, not ours. Checked on the TRANSFORMED
    # rows because that is where the date and time are finally combined - the
    # raw form columns keep them apart.
    import date_query
    backwards = date_query.raise_query(
        transformed,
        str(rows[0].get("Raised by") or "").split(";")[0].strip(),
        f"Ad hoc {rows[0].get('Customer Order No') or 'form'}")
    if backwards:
        print(f"!! {len(backwards)} DELIVERY BEFORE COLLECTION - not bookable as they stand:")
        for p in backwards:
            print(f"     {p['ref']}  collect {p['collection']}  "
                  f"deliver {p['delivery']}  ({p['back_by']} earlier)")
        print("   An email asking them to confirm is ready for Review & send.")
    print(f"BACKWARDS_DATES {len(backwards)}")
    # the order ref rides in the FILENAME - a Files card full of bare
    # timestamps gives no clue which CSV belongs to which job
    ref = re.sub(r"[^A-Za-z0-9]+", "-", str(rows[0].get("Customer Order No") or "")).strip("-")[:24]
    name = ("NR_heavy_" + (ref + "_" if ref else "")
            + datetime.now().strftime("%d%m%Y%H%M%S") + ".csv")
    out = nr_csv.write_csv(records, outbox.path(name))
    try:
        # Say what actually happened. save_adhocs can skip every record - a job
        # already booked off is refused, by design - and this printed "job
        # saved" regardless, so an upload that reached the map and one that was
        # silently refused produced identical output. AH19/8/26NESY was chased
        # for a quarter of an hour on the strength of that line.
        n_mapped = save_adhocs(rows, name, form_path=path, mail=mail)
        if n_mapped:
            print("MAP : job saved for the dashboard map (form kept for forwarding).")
        else:
            print("MAP : NOT on the map - every job in this form was refused, "
                  "see the SKIP line(s) above.")
    except Exception as ex:   # the map extra must never cost the CSV
        print(f"(map record not saved: {ex})")
    for d in rows:
        preset = str(d.get('Account') or '').strip().lower() not in UNSET_ACCOUNTS
        print(f"Order {d.get('Customer Order No')} | {d.get('Site Name - Collection')} "
              f"-> {d.get('Delivery Point')} | qty {d.get('Product Qty')} | "
              f"acct {account_for(d)}{' (preset)' if preset else ' (defaulted)'}")
        tr = to_transform_row(d)
        defaulted = []
        for lbl, rs, re_, k in (("collection", "collection_time", "collection_time_end", "collection time"),
                                ("delivery", "delivery_time", "delivery_time_end", "delivery time")):
            had_time = bool(fmt_dt(d.get(rs))) and not _dateonly_window(d.get(rs), d.get(re_))
            if not had_time and tr[k]:
                defaulted.append(lbl)
        missing = [lbl for lbl, k in (("collection", "collection time"),
                                      ("delivery", "delivery time")) if not tr[k]]
        if defaulted:
            print(f"NOTE {d.get('Customer Order No')}: {' & '.join(defaulted)} time not set on the "
                  f"form - defaulted to 09:00-17:00 in the CSV (correct in CTMS if wrong).")
        for line in window_notes(d, tr):
            print(line)
        if missing:
            print(f"!! {d.get('Customer Order No')}: {' & '.join(missing)} has NO DATE on the form "
                  f"at all - times are BLANK in the CSV; fill in before uploading.")
    print(f"CSV : {out}")


_WEIGHT_LABEL = re.compile(r"(approximate|total\s*pallet|gross)\s*weight", re.I)


def sheet_weight(path):
    """The weight the requester actually typed, or "".

    Looks RIGHT of the label first (a row label, "Approximate Weight: | 32 kg")
    then DOWN (a column header over a materials table). A candidate has to
    contain a digit, which is what stops the Project Shoot sheets reading
    their neighbouring "Part Pallet Count" header as a weight.
    """
    try:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return ""

    def usable(v):
        return v not in (None, "") and re.search(r"\d", str(v))             and not is_excel_error(v)

    for ws in wb.worksheets:
        if ws.max_row > 200:
            continue                       # address/reference tabs
        top = min(ws.max_row, 80)
        for row in ws.iter_rows(min_row=1, max_row=top):
            for cell in row:
                if not _WEIGHT_LABEL.search(str(cell.value or "")):
                    continue
                for nxt in row[cell.column:]:          # rest of the row
                    if usable(nxt.value):
                        return str(nxt.value).strip()
                for r in range(cell.row + 1, top + 1):  # down the column
                    v = ws.cell(row=r, column=cell.column).value
                    if usable(v):
                        return str(v).strip()
    return ""


def repair_weights(rows, path):
    """Make sure a stated weight actually reaches the upload.

    There is NO weight column in the NRADHOC format. The five record types
    carry no slot for one, and across the 47 genuine Access exports in
    _nr_truth/ (2685 rows) not one populates a weight field - the only
    numeric-looking extra, ORD_LINES col4, holds 18.288 and 13.716, which are
    60ft and 45ft in metres: rail lengths in Serial Number, not weights.
    Every genuine file that states a weight states it as text inside Delivery
    Instructions, so that is the only correct destination.

    The forms concatenate it there themselves, so this is a backstop and
    usually a no-op: it only fires when the instructions mention no weight at
    all. It stays because a haulier prices off that number, and the one place
    the weight HAS been lost was code that rebuilt the instructions from
    scratch (see adhoc_multidrop.legs) rather than a form that failed to
    state it.
    """
    for d in rows:
        instr = str(d.get("Delivery Instructions") or "")
        if re.search(r"weight", instr, re.I):
            continue                       # the form already carried it
        w = sheet_weight(path)
        if not w:
            continue                       # nobody stated one - invent nothing
        d["Delivery Instructions"] = (instr.strip() + " / Weight " + w).strip(" /")
        ref = str(d.get("Customer Order No") or "").strip()
        print(f"   {ref}: weight {w!r} was on the form but missing from the "
              f"upload - added to Delivery Instructions.")


if __name__ == "__main__":
    main()
