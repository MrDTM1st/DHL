"""
The file a CTMS export opens, taken straight from where CTMS put it (31/10).

A CTMS export (Administration > File Interfaces > Exports) opens its file in a
new Edge tab, and the Internet Explorer engine CTMS runs in asks there whether
to open or save it - a pop-up drawn inside that tab, which the bridge cannot
see, and the file goes bad if it waits ("save it as quickly as possible"). The
tab's name is the file's address on CTMS's own server, so the bridge reads the
name (ctms_tabs, through Windows UI Automation) and takes the file from there
itself, at once, into Downloads.

  - only an address CTMS's export opened: the name of a tab open in Edge right
    now that is an https address of a .csv in an /export/ folder - nothing the
    home PC or the dashboard sends is ever fetched
  - straight to CTMS's server first (it is on DHL's own network), then through
    the proxy, trusting this PC's own roots either way
  - a web page coming back instead of the file (a sign-in page) is said, never
    saved as the CSV
  - into Downloads, only ever adding: the same file already there is left
    alone, another of its name keeps its place and this goes in as "name (2)"
  - then that tab is closed, by its own close button, and CTMS's tab brought
    back: left open, CTMS's window shows its blank page and the bridge cannot
    see CTMS ("you need to remove this tab off of Edge", 31/10)
  - a Short Rail Report goes on to the home PC, which builds the rail plan
    from it as a PREVIEW - sending stays his Build & send

Since CTMS runs as its own program (10/11), an export opens in Edge proper,
not its Internet Explorer mode, and Edge - no "ask me" on downloads - saves
the file into Downloads by itself at once: no tab is left to read (18/11: the
rail plan's export was saved there and the bridge, looking only at tabs, said
there was none). So with no export open in a tab, the newest export file in
Downloads is taken instead: a .csv named as CTMS names its exports (what it
is, then when it was made), made since Export was pressed - or, asked
without that, saved in the last half hour.

Standard library only, like everything else in work_pc\\.
"""
import os
import re
import ssl
import time
import urllib.error
import urllib.request

import pip_here
import shared_folder

EXPORT_URL = re.compile(r"https://[A-Za-z0-9.-]+(?::\d{1,5})?/[^\s?#]*?/export/([A-Za-z0-9_.-]{1,120}\.csv)", re.I)
# The Short Rail Report - the export the rail plan is built from: sent on to the home PC for a preview.
RAIL_EXPORT = re.compile(r"short_rail_rep_[0-9_-]{1,40}\.csv")
MAX_BYTES = 20_000_000
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")


def is_export(name):
    return bool(EXPORT_URL.search(name or ""))


def urls(names):
    """The export addresses among tab names (Edge's title says the selected one's), newest file first."""
    out = []
    for n in names:
        m = EXPORT_URL.search(n or "")
        if m and m.group(0) not in out:
            out.append(m.group(0))
    return sorted(out, key=lambda u: u.rsplit("/", 1)[-1].lower(), reverse=True)   # its name carries the time


def _openers():
    bundle = pip_here.write_bundle()
    ctx = ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()
    yield "straight from CTMS's server", urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
    proxy = pip_here.proxy_from_pac()
    if proxy:
        yield "through the proxy", urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": f"http://{proxy}", "https": f"http://{proxy}"}),
            urllib.request.HTTPSHandler(context=ctx))


def fetch(url):
    """(the file's bytes, how they came). RuntimeError saying why, for each way tried, if they did not."""
    why = []
    for how, opener in _openers():
        try:
            with opener.open(url, timeout=60) as r:
                data = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            why.append(f"{how}: HTTP {e.code}")
            continue
        except Exception as e:
            why.append(f"{how}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if len(data) > MAX_BYTES:
            raise RuntimeError("What came back is far too big to be an export.")
        head = data[:4096].lstrip().lower()
        if head.startswith((b"<!doctype", b"<html")) or b"<html" in head:
            why.append(f"{how}: a web page came back, not the file - a sign-in page, most likely")
            continue
        if not data.strip():
            why.append(f"{how}: the file came back empty")
            continue
        return data, how
    raise RuntimeError("Could not take the file from CTMS's server - " + "; ".join(why) + ".")


STAMP = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{6})\.csv$")     # the time CTMS made the file, in its name
# An export file as Edge saves it into Downloads: CTMS's own name (what it is, then the time it was made) - and a
# second copy of one already there gets " (1)" from Edge, " (2)" from file_one.
SAVED = re.compile(r"([A-Za-z0-9_.-]{1,120}?_(\d{4}-\d{2}-\d{2}_\d{6}))(?: \(\d{1,3}\))?\.csv", re.I)
RECENT = 1800       # seconds: asked without `since`, a file in Downloads counts only if it was saved this recently


def _rows(data):
    lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
    return max(0, len(lines) - 1), lines[0][:240] if lines else ""


def saved(want="", since="", now=None):
    """The newest export Edge saved into Downloads by itself (CTMS as its own program, 18/11) -> the dict take() gives
    ("url" empty: there is no tab), or None. Only a .csv named as CTMS names its exports; `want` its name; `since`
    one CTMS made then or later; without `since`, one saved in the last RECENT seconds. A web page saved under such a
    name is passed over, never taken as the file."""
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(DOWNLOADS))
    except OSError:
        return None
    found = []
    for e in entries:
        m = SAVED.fullmatch(e.name)
        if not m or not e.is_file():
            continue
        name, stamp = m.group(1) + ".csv", m.group(2)
        if want and name.lower() != str(want).strip().lower():
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        if (since and stamp < since) or (not since and st.st_mtime < now - RECENT) or not 0 < st.st_size <= MAX_BYTES:
            continue
        found.append((stamp, st.st_mtime, name, e.name, e.path))
    for stamp, _, name, saved_as, path in sorted(found, reverse=True):
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_BYTES + 1)
        except OSError:
            continue
        head = data[:4096].lstrip().lower()
        if not data.strip() or head.startswith((b"<!doctype", b"<html")) or b"<html" in head:
            continue
        rows, header = _rows(data)
        return {"name": name, "url": "", "saved_as": saved_as, "written": False, "bytes": len(data), "rows": rows,
                "header": header, "how": "from Downloads, where Edge saved it", "data": data}
    return None


def take(names, want="", since=""):
    """The newest export open in a tab (or the one called `want`) into Downloads ->
    {"name", "url", "saved_as", "written", "bytes", "rows", "header", "how", "data"}. `since` ("YYYY-MM-DD_HHMMSS"):
    only a file CTMS made then or later - the one-click rail export's own, never an older tab left open. With no
    such tab, the export Edge saved into Downloads by itself (saved), "url" empty."""
    found = urls(names)
    if want:
        found = [u for u in found if u.rsplit("/", 1)[-1].lower() == str(want).strip().lower()]
    if since:
        found = [u for u in found if (STAMP.search(u) or [None, ""])[1] >= since]
    if not found:
        got = saved(want, since)
        if got:
            return got
        raise RuntimeError("No CTMS export is open in an Edge tab or saved in Downloads"
                           + (f" called {want}" if want else "")
                           + (" made since Export was pressed" if since else " in the last half hour")
                           + " - press Export in CTMS first.")
    url = found[0]
    name = url.rsplit("/", 1)[-1]
    data, how = fetch(url)
    saved_as, written = shared_folder.file_one(DOWNLOADS, name, data)
    rows, header = _rows(data)
    return {"name": name, "url": url, "saved_as": saved_as, "written": written, "bytes": len(data),
            "rows": rows, "header": header, "how": how, "data": data}
