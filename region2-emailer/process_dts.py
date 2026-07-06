"""
Process a DTS end to end.

Give it an NN reference (searches your ENTIRE mailbox for the DTS PDF - Inbox
and ADHOC/DTS, newest first, no age limit) or a direct path to a DTS PDF.
Produces BOTH outputs in Downloads:
  1. the filled Haulage Request Form (paper trail)
  2. the NR upload CSV (via the replicated database logic)

    python process_dts.py NN5139446-260
    python process_dts.py "C:\\path\\to\\DTS.pdf"
"""
import sys, os
from datetime import datetime
import dts_fill_form, nr_csv

HERE = os.path.dirname(os.path.abspath(__file__))
DHL_SMTP = "delali.opoku@dhl.com"


def find_dts_pdf(ref):
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
    dts_folder = sub(sub(inbox, "ADHOC"), "DTS")
    refu = ref.upper()
    out = os.path.join(HERE, "_dts.pdf")
    for folder in (inbox, dts_folder):
        if folder is None:
            continue
        items = folder.Items
        try:
            items.Sort("[ReceivedTime]", True)
        except Exception:
            pass
        for it in items:   # no limit - whole history, newest first
            try:
                subj = str(it.Subject or "").upper()
                for j in range(1, it.Attachments.Count + 1):
                    att = it.Attachments.Item(j)
                    fn = str(att.FileName)
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in (".pdf", ".xls", ".xlsx"):
                        continue
                    if refu in fn.upper() or (refu in subj and "dts" in fn.lower()):
                        dst = os.path.join(HERE, "_dts" + ext)
                        att.SaveAsFile(dst)
                        return dst, fn, folder.Name
            except Exception:
                continue
    return None, None, None


def main():
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not arg:
        print("Usage: python process_dts.py <NN reference | path-to-pdf>")
        return
    if os.path.exists(arg):
        pdf, src = arg, "local file"
    else:
        print(f"Searching your mailbox for DTS {arg} (full history)...")
        pdf, fn, where = find_dts_pdf(arg)
        if not pdf:
            print(f"NOT FOUND: no PDF matching '{arg}' in Inbox or ADHOC/DTS.")
            return
        src = f"email attachment '{fn}' (folder: {where})"
    print(f"DTS PDF: {src}")

    form_path, data, raiser = dts_fill_form.fill(pdf, dts_fill_form.TEMPLATE_DEFAULT)
    row = nr_csv.dts_row(pdf)
    records = nr_csv.transform([row])
    import outbox
    csv_name = "NR_heavy_" + datetime.now().strftime("%d%m%Y%H%M%S") + ".csv"
    csv_path = nr_csv.write_csv(records, outbox.path(csv_name))
    print(f"Reference : {data['ref']}  |  raised by {raiser}")
    print(f"Collection: {data['coll'].get('collection site')} {data['coll'].get('post code')}")
    print(f"Delivery  : {data['deliv'].get('delivery site')} {data['deliv'].get('post code')}")
    print(f"Pallets   : {data['pallets']}  |  del notes: {len(data['del_notes'])}")
    print(f"FORM : {form_path}")
    print(f"CSV  : {csv_path}")


if __name__ == "__main__":
    main()
