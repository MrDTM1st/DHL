"""
Process an already-filled Haulage Request Form (the usual ad hoc).

Reads the form's own "RHPC Admin - DHL USE ONLY" row - via Excel itself, so
the form's formulas produce the genuine values - and runs it through the
replicated database logic to build the NR upload CSV in the outbox.

    python process_form.py "<path to filled form.xlsx>"
    python process_form.py <reference or filename fragment>   # searches email
    python process_form.py latest                             # newest form in email
"""
import sys, os, re
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
            target = next((n for n in names if n.strip().lower().startswith("rhpc admin")), None)
            sh = wb.Worksheets(target)
            rows = sh.Range(sh.Cells(1, 1), sh.Cells(4, 60)).Value
        finally:
            wb.Close(False)
            xl.Quit()
    except Exception:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wbo = openpyxl.load_workbook(path, data_only=True)
        target = next((n for n in wbo.sheetnames if n.strip().lower().startswith("rhpc admin")), None)
        sho = wbo[target]
        rows = [[c.value for c in r] for r in sho.iter_rows(min_row=1, max_row=4, max_col=60)]
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for r in rows[2:4]:   # data rows 3 and 4 (4 = return leg, if present)
        d = {headers[i]: r[i] for i in range(len(headers)) if headers[i]}
        if d.get("Customer Order No") not in (None, ""):
            out.append(d)
    return out


def fmt_dt(v):
    if v is None or v == "":
        return ""
    try:
        return v.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(v)


ADHOC_ACCOUNT = "NRADHOC"   # default when the form leaves the account unset
UNSET_ACCOUNTS = {"", "please select", "select", "none"}


def _norm_order(ref):
    """Normalise an order number for the upload: spaces are not allowed, so a
    reference like 'FS-PLC CARDS' becomes 'FS-PLC-CARDS'. Collapses runs of
    whitespace/hyphens to a single hyphen and trims the ends."""
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


def to_transform_row(d):
    r = dict(d)
    r["collection time"] = fmt_dt(d.get("collection_time"))
    r["collection time end"] = fmt_dt(d.get("collection_time_end"))
    r["delivery time"] = fmt_dt(d.get("delivery_time"))
    r["delivery time end"] = fmt_dt(d.get("delivery_time_end"))
    r["Account"] = account_for(d)   # preset account wins; else NRADHOC
    return r


def main():
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else "latest"
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
    records = nr_csv.transform([to_transform_row(d) for d in rows])
    name = "NR_heavy_" + datetime.now().strftime("%d%m%Y%H%M%S") + ".csv"
    out = nr_csv.write_csv(records, outbox.path(name))
    for d in rows:
        preset = str(d.get('Account') or '').strip().lower() not in UNSET_ACCOUNTS
        print(f"Order {d.get('Customer Order No')} | {d.get('Site Name - Collection')} "
              f"-> {d.get('Delivery Point')} | qty {d.get('Product Qty')} | "
              f"acct {account_for(d)}{' (preset)' if preset else ' (defaulted)'}")
    print(f"CSV : {out}")


if __name__ == "__main__":
    main()
