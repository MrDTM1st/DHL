"""
His week from the team's Transport Planners sheet - his ask (01/11): "look at the recent transport planner Excel
sheet, and then you tell me the things that I will be doing ... throughout the week ... because I know I forget
pretty often" - for the dashboard's My week card.

The sheet comes by email each week ("Transport Planners wc 02.11.26 v1.xlsx", then v2, v3 ... as replies whenever
it changes), and those mails end up filed all over the Inbox, so the whole Inbox is searched for the newest version
of this week's and next week's sheet. Its first tab has a row per duty (its name in column A) and a column per
weekday, in sections that start with a row of the day names; a cell names whoever has that duty that day, two of
them as "Sam / Jo", a note as "Sam (Emergencies Only)". Every cell with his name is his duty that day - except what
he does every day and doesn't need telling (his words): his region and Serviceable Materials. A row with no name of
its own (the days-off row) shows the cell as it is.

    python planner_week.py refresh       the newest sheets from the mailbox -> _planner_week.json (the agent, hourly)
    python planner_week.py FILE.xlsx     one sheet, read and printed
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_planner_week.json")
ME = "Delali"
SKIP = ("region 2", "serviceable materials")         # every day of his - "you don't need to tell me" (01/11)
SUBJECT = "Transport Planner"
SHEET = re.compile(r"transport planners? wc (\d{1,2})\.(\d{1,2})\.(\d{2}(?:\d{2})?)(?:\s*v(\d+))?.*\.xlsx$", re.I)
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SCAN_DAYS = 21


def week_of(name):
    """(the Monday the sheet is for, its version) from its file name - None when it isn't one."""
    m = SHEET.search(str(name or "").strip())
    if not m:
        return None
    d, mo, y, v = m.groups()
    try:
        return date(int(y) + (2000 if len(y) == 2 else 0), int(mo), int(d)), int(v or 1)
    except ValueError:
        return None


def _text(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def _day_columns(row):
    """{column index: weekday} when a row is a row of day names (a section's head), else {}."""
    cols = {i: _text(v).lower() for i, v in enumerate(row) if _text(v).lower() in DAYS}
    return cols if len(cols) >= 3 else {}


def _mine(cell, me):
    """(is it his, the note on his name, who else) for one cell: "Sam / Delali", "Delali (Emergencies Only)"."""
    parts = [p.strip() for p in re.split(r"\s*(?:/|&|,|\+|\band\b)\s*", cell) if p.strip()]
    mine, note, others = False, "", []
    for p in parts:
        m = re.match(r"([A-Za-z'-]+)\s*(.*)$", p)
        if not m:
            continue
        if m.group(1).lower() == me.lower():
            mine, note = True, m.group(2).strip()
        else:
            others.append(m.group(1))
    return mine, note, others


def duties(rows, me=ME, skip=SKIP):
    """His duties from the sheet's rows (lists of cell values, column A first) -> {weekday: [{what, section, note,
    with}]} in the sheet's order."""
    out, cols, section = {}, {}, ""
    for row in rows:
        head = _day_columns(row)
        if head:
            cols, section = head, _text(row[0]).rstrip(":").strip() if row else ""
            continue
        if not cols:
            continue
        label = _text(row[0]) if row else ""
        if label and any(s in label.lower() for s in skip):
            continue
        for i, day in cols.items():
            cell = _text(row[i]) if i < len(row) else ""
            if not cell:
                continue
            mine, note, others = _mine(cell, me)
            if not mine:
                continue
            out.setdefault(day, []).append({"what": label or cell, "section": section,
                                            "note": note if label else "", "with": others if label else []})
    return out


def read(path, me=ME, skip=SKIP, week=None):
    """One sheet -> {"wc": dd/mm/yyyy, "version", "days": [{"day", "date", "duties"}]} Monday to Friday (a weekend
    day only when he has something on it). week: (its Monday, version) when the file's own name no longer says."""
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Main"] if "Main" in wb.sheetnames else wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    wk = week or week_of(os.path.basename(path))
    monday = wk[0] if wk else None
    got = duties(rows, me, skip)
    days = []
    for k, day in enumerate(DAYS):
        if k >= 5 and not got.get(day):
            continue
        when = monday + timedelta(days=k) if monday else None
        days.append({"day": day.title(), "date": when.strftime("%d/%m/%Y") if when else "",
                     "duties": got.get(day, [])})
    return {"wc": monday.strftime("%d/%m/%Y") if monday else "", "version": wk[1] if wk else 0, "days": days}


def newest(ns, days=SCAN_DAYS):
    """{Monday: {"version", "received", "from", "att"}} - the newest version of each week's sheet anywhere in the
    Inbox, from mails of the last `days` days."""
    import build_drafts as bd
    inbox = bd.sub(bd.dhl_store(ns), "Inbox")
    cutoff = datetime.now() - timedelta(days=days)
    found = {}

    def walk(folder, depth):
        try:
            items = folder.Items.Restrict(f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{SUBJECT}%'")
        except Exception:
            items = []
        for it in items:
            try:
                got = it.ReceivedTime.replace(tzinfo=None)
                if got < cutoff:
                    continue
                atts = [it.Attachments.Item(i + 1) for i in range(it.Attachments.Count)]
            except Exception:
                continue
            for a in atts:
                wk = week_of(a.FileName)
                if not wk:
                    continue
                best = found.get(wk[0])
                if best is None or (wk[1], got) > (best["version"], best["received"]):
                    found[wk[0]] = {"version": wk[1], "received": got, "att": a, "name": a.FileName,
                                    "from": str(getattr(it, "SenderName", "") or "")}
        if depth < 5:
            try:
                for sub in folder.Folders:
                    walk(sub, depth + 1)
            except Exception:
                pass

    if inbox is not None:
        walk(inbox, 1)
    return found


def refresh(ns, today=None):
    """This week's and next week's newest sheets, read -> what _planner_week.json now holds."""
    today = today or date.today()
    this = today - timedelta(days=today.weekday())
    found = newest(ns)
    weeks = []
    for monday in (this, this + timedelta(days=7)):
        f = found.get(monday)
        if not f:
            continue
        path = os.path.join(HERE, f"_planner_wc_{monday:%Y-%m-%d}.xlsx")
        f["att"].SaveAsFile(path)
        wk = read(path, week=(monday, f["version"]))
        wk.update(file=f["name"], sender=f["from"], received=f["received"].strftime("%d/%m %H:%M"))
        weeks.append(wk)
    out = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "weeks": weeks}
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    os.replace(tmp, PATH)
    return out


def load(today=None):
    """What the dashboard shows: the weeks read last, any already over left out."""
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    today = today or date.today()
    keep = []
    for w in d.get("weeks") or []:
        try:
            if datetime.strptime(w["wc"], "%d/%m/%Y").date() + timedelta(days=6) >= today:
                keep.append(w)
        except (KeyError, ValueError):
            continue
    return dict(d, weeks=keep)


def say(week):
    lines = [f"w/c {week['wc']} ({week.get('file') or 'v' + str(week.get('version'))})"]
    for d in week["days"]:
        bits = [x["what"] + (f" ({x['note']})" if x["note"] else "") + (f" with {', '.join(x['with'])}"
                                                                        if x["with"] else "") for x in d["duties"]]
        lines.append(f"  {d['day'][:3]} {d['date'][:5]}  " + ("; ".join(bits) if bits else "-"))
    return "\n".join(lines)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) == 2 and argv[1] == "refresh":
        import build_drafts as bd
        out = refresh(bd.get_ns())
        print("\n".join(say(w) for w in out["weeks"]) or "No Transport Planners sheet for this week or next found.")
        return 0
    if len(argv) == 2 and argv[1].lower().endswith(".xlsx"):
        print(say(read(argv[1])))
        return 0
    print(__doc__.strip().splitlines()[-2].strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
