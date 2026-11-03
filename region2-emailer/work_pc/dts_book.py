"""
The team's DTS sheet: rows added to its year's tab, nothing else in the workbook touched.

The workbook is on the team's share, and people have it open. So:
  - only that tab's own part of the file changes: each new row's cells, in the sheet's next empty row, in the formatting
    that row already has. Every other part is copied across byte for byte, and checked afterwards to be the same
  - a line already on the tab (the same reference and catalogue number) isn't added twice
  - the new file goes in by one rename, which Windows refuses while anyone has the workbook open: that's Busy, nothing is
    changed, and the home PC tries again later. So is the file having changed while this was working on it. The ~$ lock
    file isn't looked at: one can be left behind for years
  - the last few versions are kept beside this file

Standard library only, like everything else in work_pc\\.
"""
import copy
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUPS = os.path.join(HERE, "dts_backups")
KEEP = 10
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
ROW = re.compile(r"<row\b([^>]*?)(?:/>|>(.*?)</row>)", re.S)
CELL = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
COLUMNS = "ABCDEFGH"               # NN No., Subline, Catalogue No., Quantity, Delivery Address, Collection date, Requestor, Planner


class Busy(RuntimeError):
    """Someone has the workbook open, or it changed: nothing was done, try later."""


def _attr(text, name):
    m = re.search(r'\b' + name + r'="([^"]*)"', text)
    return m.group(1) if m else ""


def _shared(z):
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(MAIN + "t")) for si in root.findall(MAIN + "si")]


def tab_part(z, year):
    """The file inside the workbook holding the year's tab; a Stop-worthy ValueError when there's no such tab."""
    book = z.read("xl/workbook.xml").decode("utf-8")
    sheet = next((s for s in re.findall(r"<sheet\b[^>]*>", book) if _attr(s, "name") == str(year)), None)
    if sheet is None:
        raise ValueError(f"The DTS sheet has no {year} tab.")
    rid = re.search(r'r:id="([^"]+)"', sheet).group(1)
    for rel in re.findall(r"<Relationship\b[^>]*>", z.read("xl/_rels/workbook.xml.rels").decode("utf-8")):
        if _attr(rel, "Id") == rid:
            target = _attr(rel, "Target").lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    raise ValueError(f"The DTS sheet's {year} tab couldn't be found in the file.")


def _cells(body):
    """{column: (attrs, inside)} of a row's XML."""
    out = {}
    for attrs, inside in CELL.findall(body or ""):
        col = re.match(r"[A-Z]+", _attr(attrs, "r"))
        if col:
            out[col.group(0)] = (attrs, inside or "")
    return out


def _value(cell, shared):
    attrs, inside = cell
    kind = _attr(attrs, "t")
    if kind == "inlineStr":
        return "".join(re.findall(r"<t\b[^>]*>(.*?)</t>", inside, re.S))
    m = re.search(r"<v>(.*?)</v>", inside, re.S)
    if not m:
        return ""
    if kind == "s":
        i = int(m.group(1))
        return shared[i] if i < len(shared) else ""
    return m.group(1)


def _key(nn, cat):
    return (re.sub(r"\s+", "", str(nn)).upper(), re.sub(r"\s+", "", str(cat)).upper())


def read_rows(xml, shared):
    """[(row number, {column: value})] of what the tab holds."""
    out = []
    for attrs, body in ROW.findall(xml):
        cells = _cells(body)
        out.append((int(_attr(attrs, "r")), {c: _value(v, shared) for c, v in cells.items()}))
    return out


def _serial(day):
    return (datetime.strptime(day, "%d/%m/%Y") - datetime(1899, 12, 30)).days


def _new_cell(col, n, style, value):
    s = f' s="{style}"' if style else ""
    if col == "F":
        return f'<c r="F{n}"{s}><v>{_serial(value)}</v></c>'
    if value in ("", None):
        return f'<c r="{col}{n}"{s}/>'
    if isinstance(value, (int, float)) or re.fullmatch(r"\d+(\.\d+)?", str(value)):
        return f'<c r="{col}{n}"{s}><v>{value}</v></c>'
    return f'<c r="{col}{n}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _col_no(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def add_to_xml(xml, rows, shared):
    """The tab's XML with these rows added -> (new XML, [(row number, the row)], how many were there already)."""
    held = read_rows(xml, shared)
    filled = [n for n, v in held if str(v.get("A") or "").strip() or str(v.get("C") or "").strip()]
    last = max(filled or [1])
    have = {_key(v.get("A", ""), v.get("C", "")) for _, v in held}
    used, skipped, n = [], 0, last
    styles = {c: _attr(a, "s") for c, (a, _) in _cells(next((m.group(2) for m in ROW.finditer(xml)
                                                            if int(_attr(m.group(1), "r")) == last), "")).items()}
    for row in rows:
        if _key(row["nn"], row["cat"]) in have:
            skipped += 1
            continue
        have.add(_key(row["nn"], row["cat"]))
        n += 1
        values = dict(zip(COLUMNS, (row["nn"], row.get("sub") or "N/A", row["cat"], row["qty"], row["post"], row["date"],
                                    row["req"], row["planner"])))
        m = next((m for m in ROW.finditer(xml) if int(_attr(m.group(1), "r")) == n), None)
        old = _cells(m.group(2)) if m else {}
        built = {}
        for col, (attrs, inside) in old.items():
            if col not in values:
                built[col] = f"<c{attrs}>{inside}</c>" if inside else f"<c{attrs}/>"
        for col, value in values.items():
            style = _attr(old[col][0], "s") if col in old else styles.get(col, "")
            built[col] = _new_cell(col, n, style, value)
        cells = "".join(built[c] for c in sorted(built, key=_col_no))
        if m:
            xml = xml[:m.start()] + f"<row{m.group(1)}>{cells}</row>" + xml[m.end():]
        else:
            xml = xml.replace("</sheetData>", f'<row r="{n}">{cells}</row></sheetData>', 1)
            if _dim_end(xml) < n:
                xml = re.sub(r'(<dimension ref="[A-Z]+\d+:[A-Z]+)\d+("/>)', lambda d: f"{d.group(1)}{n}{d.group(2)}", xml, count=1)
        used.append((n, row))
    return xml, used, skipped


def _dim_end(xml):
    m = re.search(r'<dimension ref="[A-Z]+\d+:[A-Z]+(\d+)"/>', xml)
    return int(m.group(1)) if m else 0


def add_rows(path, rows):
    """Add these to the year's tab of the workbook at `path` -> {"rows": row numbers, "skipped", "tab"}. Each row: nn, sub, cat,
    qty, post, date (dd/mm/yyyy), req, planner. Raises Busy when it couldn't be done now."""
    if not rows:
        return {"rows": [], "skipped": 0, "tab": ""}
    years = {datetime.strptime(r["date"], "%d/%m/%Y").year for r in rows}
    if len(years) != 1:
        raise ValueError("Those rows run across two years' tabs.")
    year = years.pop()
    before = os.stat(path).st_mtime_ns
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except PermissionError as e:
        raise Busy("the DTS sheet can't be read just now") from e
    temp = path + f".{os.getpid()}.tmp"
    try:
        with zipfile.ZipFile(path) as z:
            part = tab_part(z, year)
            shared = _shared(z)
            xml = z.read(part).decode("utf-8")
            new, used, skipped = add_to_xml(xml, rows, shared)
            if not used:
                return {"rows": [], "skipped": skipped, "tab": str(year)}
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as out:
                for info in z.infolist():
                    data = new.encode("utf-8") if info.filename == part else z.read(info.filename)
                    out.writestr(copy.copy(info), data, compress_type=zipfile.ZIP_DEFLATED)   # a copy: writing moves its offset
            with zipfile.ZipFile(temp) as check:
                for info in z.infolist():
                    if info.filename != part and check.read(info.filename) != z.read(info.filename):
                        raise ValueError(f"{info.filename} came out different - nothing was changed.")
                got = dict(read_rows(check.read(part).decode("utf-8"), shared))
        for n, row in used:
            if _key(got[n].get("A", ""), got[n].get("C", "")) != _key(row["nn"], row["cat"]):
                raise ValueError(f"Row {n} didn't read back as {row['nn']} - nothing was changed.")
        if os.stat(path).st_mtime_ns != before:
            raise Busy("the DTS sheet changed while this was working on it")
        _backup(raw)
        try:
            os.replace(temp, path)
        except PermissionError as e:
            raise Busy("someone has the DTS sheet open") from e
        return {"rows": [n for n, _ in used], "skipped": skipped, "tab": str(year)}
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def _backup(raw):
    os.makedirs(BACKUPS, exist_ok=True)
    with open(os.path.join(BACKUPS, f"DTS-{datetime.now():%Y%m%d%H%M%S}.xlsx"), "wb") as f:
        f.write(raw)
    for old in sorted(os.listdir(BACKUPS))[:-KEEP]:
        try:
            os.remove(os.path.join(BACKUPS, old))
        except OSError:
            pass
