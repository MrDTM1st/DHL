"""
Order index: order number -> which email attachment contains it.

Makes "Send one order" instant (like Outlook's own search) instead of
re-scanning every attachment. The index is built incrementally: each refresh
only reads mail newer than the last scan, so after the first build a refresh
takes seconds. State lives in order_index.json next to this file.

    python order_index.py            # refresh (first run = full build)
"""
import os, json, sys
import win32com.client

HERE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(HERE, "order_index.json")
DHL_SMTP = "delali.opoku@dhl.com"
SKIP_FOLDERS = {"contacts", "calendar", "tasks", "notes", "journal", "files",
                "conversation history", "rss feeds", "search folders", "outbox"}
MAX_LOCS = 3          # newest N locations kept per order token


def load():
    try:
        return json.load(open(IDX, encoding="utf-8"))
    except Exception:
        return {"folders": {}, "orders": {}}


def save(d):
    tmp = IDX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, IDX)     # atomic - a concurrent lookup never sees a partial file


def tokens_in_xlsx(path):
    """Only the values in 'Customer Order No' columns - real order refs,
    nothing else. Keeps the index tiny and exact."""
    out = set()
    try:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            hdr = next(rows, ())
            col = None
            for i, h in enumerate(hdr):
                if h is not None and str(h).strip().lower() == "customer order no":
                    col = i
                    break
            if col is None:
                continue
            for r in rows:
                if col < len(r) and r[col] not in (None, ""):
                    v = str(r[col]).strip().upper()
                    out.add(v)
                    out.add(v.split("-")[0])
        wb.close()
    except Exception:
        pass
    return out


def _ts(item):
    try:
        return float(item.ReceivedTime.timestamp())
    except Exception:
        return 0.0


def refresh(max_items_per_folder=2000):
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    dhl = None
    for i in range(1, ns.Folders.Count + 1):
        if ns.Folders.Item(i).Name.lower() == DHL_SMTP:
            dhl = ns.Folders.Item(i)
            break
    if dhl is None:
        print("DHL store not found"); return
    d = load()
    tmp = os.path.join(HERE, "_index_scan.xlsx")
    scanned = added = 0

    def note(token, loc):
        locs = d["orders"].setdefault(token, [])
        if any(l["e"] == loc["e"] and l["f"] == loc["f"] for l in locs):
            return
        locs.insert(0, loc)
        del locs[MAX_LOCS:]

    def walk(folder, path):
        nonlocal scanned, added
        name = folder.Name.strip().lower()
        if name in SKIP_FOLDERS:
            return
        fid = f"{path}/{folder.Name}"
        last = d["folders"].get(fid, 0.0)
        newest = last
        try:
            items = folder.Items
            items.Sort("[ReceivedTime]", True)
        except Exception:
            items = None
        if items is not None:
            n = 0
            for it in items:
                n += 1
                if n > max_items_per_folder:
                    break
                ts = _ts(it)
                if ts and ts <= last:
                    break                       # everything older is already indexed
                newest = max(newest, ts)
                try:
                    store_id = folder.StoreID
                    for j in range(1, it.Attachments.Count + 1):
                        att = it.Attachments.Item(j)
                        fn = str(att.FileName)
                        if not fn.lower().endswith((".xlsx", ".xlsm")):
                            continue
                        att.SaveAsFile(tmp)
                        scanned += 1
                        loc = {"e": it.EntryID, "s": store_id, "f": fn, "r": ts}
                        for tok in tokens_in_xlsx(tmp):
                            note(tok, loc)
                            added += 1
                except Exception:
                    continue
        if newest > last:
            d["folders"][fid] = newest
            save(d)                              # progressive save per folder
        try:
            for i in range(1, folder.Folders.Count + 1):
                walk(folder.Folders.Item(i), fid)
        except Exception:
            pass

    walk(dhl, "")
    save(d)
    print(f"index refresh: scanned {scanned} attachment(s), {len(d['orders'])} tokens known")


def lookup(ns, order, out_path):
    """Instant lookup: returns (path, filename) or (None, None)."""
    d = load()
    base = str(order).split("-")[0].upper()
    for key in (base, str(order).upper()):
        for loc in d["orders"].get(key, []):
            try:
                it = ns.GetItemFromID(loc["e"], loc["s"])
                for j in range(1, it.Attachments.Count + 1):
                    att = it.Attachments.Item(j)
                    if str(att.FileName) == loc["f"]:
                        att.SaveAsFile(out_path)
                        return out_path, loc["f"]
            except Exception:
                continue
    return None, None


if __name__ == "__main__":
    refresh()
