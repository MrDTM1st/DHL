"""
The team's DTS sheet, kept up by itself (his 03/11: "one DTS sheet that we have to update every time we get a DTS ... make that
into an automation for whenever we book in a DTS").

Processing a DTS keeps its lines here. Once that order has been booked - however it was: Book, the Booked button, an email
with the manifest, a CTMS look-up, all of which end in the booked list - the next run hands its rows to the work PC, the only
PC that reaches the sheet (work_pc/dts_book.py). A sheet someone has open just means trying again on the next run; a job
that hasn't been booked is never added.

    python dts_sheet.py run                     what's been booked goes on the sheet
    python dts_sheet.py lines DTS_FILE          what a DTS file's rows would be, nothing sent
    python dts_sheet.py add DTS_FILE dd/mm/yyyy that one on the sheet now, with that collection date
"""
import contextlib
import io
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "_dts_lines.json")
PLANNER = "Delali"
CATALOGUE = re.compile(r"\d{3,4}/\d{4,}")
STUCK_HOURS = 2                    # still not on the sheet after this long: he is told, once


def _text(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def from_table(rows):
    """The lines of a DTS's line table, however it was read: [{nn, sub, cat, qty}]. The reference repeats down the table only
    sometimes, so a blank one carries on from the line above."""
    head, at = None, {}
    out, nn = [], ""
    for row in rows:
        cells = [_text(c) for c in row]
        low = [c.lower() for c in cells]
        if head is None:
            cat = next((i for i, c in enumerate(low) if c.startswith(("catologue", "catalogue"))), None)
            if cat is not None:
                find = lambda *w: next((i for i, c in enumerate(low) if any(c.startswith(x) for x in w)), None)  # noqa: E731
                at = {"nn": find("nn/nr", "nr number", "nn number"), "sub": find("sub line"), "cat": cat, "qty": find("total units")}
                head = True
            continue
        cat = cells[at["cat"]] if at["cat"] < len(cells) else ""
        if not CATALOGUE.fullmatch(cat):
            if out:
                break
            continue
        here = cells[at["nn"]] if at["nn"] is not None and at["nn"] < len(cells) else ""
        nn = here or nn
        m = re.search(r"\d+", cells[at["qty"]]) if at["qty"] is not None and at["qty"] < len(cells) else None
        sub = cells[at["sub"]] if at["sub"] is not None and at["sub"] < len(cells) else ""
        out.append({"nn": nn, "sub": sub or "N/A", "cat": cat, "qty": int(m.group(0)) if m else None})
    return out


def lines_of(path):
    """A DTS file's lines, the PDF form or the spreadsheet one."""
    if str(path).lower().endswith((".xls", ".xlsx")):
        import xlrd
        sh = xlrd.open_workbook(path).sheet_by_index(0)
        return from_table([sh.row_values(i) for i in range(sh.nrows)])
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                got = from_table(table)
                if got:
                    return got
    return []


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, STORE)


def remember(path, row):
    """A DTS has been processed: its lines and where they're going, for when it's booked. row: the upload's (nr_csv.dts_row)."""
    ref = str(row.get("Customer Order No") or "").strip()
    d = _load()
    d[ref] = {"lines": lines_of(path), "post": _text(row.get("D Postcode")), "req": _text(row.get("Site Name - Collection")),
              "date": _text(row.get("collection time"))[:10], "at": datetime.now().isoformat(timespec="seconds")}
    _save(d)
    return d[ref]


def rows_for(job):
    """The sheet's rows for one job; [] when a line has no quantity or the job no date, to be looked at rather than guessed."""
    if not job.get("date") or not job.get("lines") or any(ln.get("qty") is None for ln in job["lines"]):
        return []
    return [dict(ln, post=job.get("post") or "", date=job["date"], req=job.get("req") or "", planner=PLANNER) for ln in job["lines"]]


def _on_map():
    try:
        with open(os.path.join(HERE, "_adhocs.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def due(store, on_map, booked, now=None):
    """Which jobs want adding now: booked and off the map, not yet on the sheet. The map's collection date - moved since the DTS
    came in, as often as not - is carried over while the job is on it (changes `store`)."""
    showing = {}
    for rec in on_map:
        for o in rec.get("orders") or []:
            showing[str(o)] = rec
    out = []
    for ref, job in store.items():
        if job.get("done"):
            continue
        rec = showing.get(ref)
        if rec:
            if rec.get("collection_date"):
                job["date"] = rec["collection_date"]
            continue
        if ref in booked:
            out.append(ref)
    return out


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _sheet_path():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f).get("dts_sheet") or ""


def send(R, rows):
    """The rows to the work PC -> (added, why not): added None when it's to be tried again."""
    result, payload = _quiet(R.ask, "dts_add", wait_total=90, folder=_sheet_path(), rows=rows)
    if not result.get("ok"):
        return None, str(result.get("detail") or "no answer")
    return payload or {}, ""


def _tell(R, words):
    try:
        R.http("POST", "/api/status", {"state": "done", "detail": words})
    except Exception:
        pass
    print(words)


def run(now=None):
    import book_run
    import tracker
    now = now or datetime.now()
    store = _load()
    booked = {str(o) for o in tracker.booked_drops()}
    refs = due(store, _on_map(), booked, now)
    if not refs:
        _save(store)
        return 0
    if not _sheet_path():
        print("config.json has no dts_sheet: nothing sent.")
        return 0
    R = book_run._client()
    for ref in refs:
        job = store[ref]
        rows = rows_for(job)
        if not rows:
            if not job.get("told"):
                _tell(R, f"DTS sheet: {ref} is booked, but its lines or collection date couldn't be read. Add it by hand.")
                job["told"] = True
            continue
        job.setdefault("booked_seen", now.isoformat(timespec="seconds"))
        try:
            got, why = send(R, rows)
        except Exception as e:
            got, why = None, str(e)
        if got is None:
            print(f"{ref}: not yet ({why[:200]})")
            hours = (now - datetime.fromisoformat(job["booked_seen"])).total_seconds() / 3600
            if hours >= STUCK_HOURS and not job.get("told"):
                _tell(R, f"DTS sheet: {ref} still isn't on the sheet after {STUCK_HOURS} hours ({why[:120]}). It keeps trying.")
                job["told"] = True
            continue
        job["done"] = now.isoformat(timespec="seconds")
        job["rows"] = got.get("rows")
        _tell(R, f"DTS sheet: {ref} added, row(s) {got.get('rows')} of the {got.get('tab')} tab"
              + (f" ({got.get('skipped')} already there)." if got.get("skipped") else "."))
    _save(store)
    return 0


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) >= 2 and argv[1] == "run":
        import outlook_gate as gate
        if gate.named_lock("dts_sheet", wait=5) is None:
            return 0
        return run()
    if len(argv) == 3 and argv[1] == "lines":
        print(json.dumps(lines_of(argv[2]), indent=1))
        return 0
    if len(argv) == 4 and argv[1] == "add":
        import book_run
        import nr_csv
        row = nr_csv.dts_row(argv[2])
        rows = rows_for({"lines": lines_of(argv[2]), "post": _text(row.get("D Postcode")),
                         "req": _text(row.get("Site Name - Collection")), "date": argv[3]})
        if not rows:
            print("Its lines couldn't be read: nothing sent.")
            return 1
        got, why = send(book_run._client(), rows)
        print(json.dumps(got) if got is not None else f"Not added: {why}")
        return 0 if got is not None else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
