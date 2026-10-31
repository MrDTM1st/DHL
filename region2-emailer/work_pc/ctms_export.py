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

Standard library only, like everything else in work_pc\\.
"""
import os
import re
import ssl
import urllib.error
import urllib.request

import pip_here
import shared_folder

EXPORT_URL = re.compile(r"https://[A-Za-z0-9.-]+(?::\d{1,5})?/[^\s?#]*?/export/([A-Za-z0-9_.-]{1,120}\.csv)", re.I)
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


def take(names, want=""):
    """The newest export open in a tab (or the one called `want`) into Downloads ->
    {"name", "saved_as", "written", "bytes", "rows", "header", "how"}."""
    found = urls(names)
    if want:
        found = [u for u in found if u.rsplit("/", 1)[-1].lower() == str(want).strip().lower()]
    if not found:
        raise RuntimeError("No CTMS export is open in an Edge tab" + (f" called {want}" if want else "")
                           + " - press Export in CTMS first.")
    url = found[0]
    name = url.rsplit("/", 1)[-1]
    data, how = fetch(url)
    saved_as, written = shared_folder.file_one(DOWNLOADS, name, data)
    lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
    return {"name": name, "url": url, "saved_as": saved_as, "written": written, "bytes": len(data),
            "rows": max(0, len(lines) - 1), "header": lines[0][:240] if lines else "", "how": how}
