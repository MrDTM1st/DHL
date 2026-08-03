"""
Work-PC probe - answers "what can this machine actually do?" before any
CTMS automation is written for it.

Standard library only, on purpose: it must run on a bare corporate Python
with nothing installed. It READS the environment and writes a report; it
changes nothing, installs nothing, and never touches credentials.

    python ctms_probe.py

Then email ctms_probe_report.txt to yourself (subject: CTMS probe).
"""
import glob
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime

LINES = []

# Where the browsers live on a corporate Windows build. start_here.py launches
# from this same list - two copies of "where is Edge" is exactly how one of them
# ends up knowing about a path the other doesn't.
BROWSERS = {
    "Edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "Chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}

DEBUG_PORT = 9222


def say(line=""):
    print(line)
    LINES.append(line)


def check(label, fn):
    try:
        result = fn()
        say(f"  [OK]   {label}: {result}")
        return True
    except Exception as e:
        say(f"  [NO]   {label}: {type(e).__name__}: {e}")
        return False


def url_status(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "ctms-probe"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        # the server ANSWERED - the route is open, whatever the status code
        return f"reachable (server answered HTTP {e.code})"


def windows_proxy():
    """Where the corporate proxy actually is, and what pip needs to be told.

    A managed Windows box almost never sets HTTP(S)_PROXY environment
    variables - the proxy lives in the registry, and very often only as a PAC
    URL. The browser reads all of that automatically. pip reads none of it, so
    it tries to reach pypi.org directly and gets "WinError 10061 ... actively
    refused" while the same machine is quite happily browsing GitHub. Reporting
    the env vars alone made that look like "no proxy set", which is the exact
    wrong conclusion.
    """
    if os.name != "nt":
        say("PROXY (Windows only - skipped)")
        say()
        return
    say("PROXY (why pip can fail on a machine whose browser works fine)")
    server = pac = None
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            def val(name):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    return None
            enabled, server, pac = val("ProxyEnable"), val("ProxyServer"), val("AutoConfigURL")
        say(f"  [..]   ProxyEnable: {enabled}")
        say(f"  [..]   ProxyServer: {server or 'not set'}")
        say(f"  [..]   AutoConfigURL (PAC): {pac or 'not set'}")
    except Exception as e:
        say(f"  [--]   could not read the registry: {type(e).__name__}: {e}")
    try:
        out = subprocess.run(["netsh", "winhttp", "show", "proxy"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        for line in out.splitlines():
            if line.strip():
                say(f"  [..]   netsh: {line.strip()}")
    except Exception as e:
        say(f"  [--]   netsh failed: {type(e).__name__}: {e}")

    if server:
        host = str(server).split(";")[0].split("=")[-1]
        say(f"  ==>    try: pip install --proxy http://{host} -r requirements.txt")
    elif pac:
        say("  ==>    PAC-only. pip CANNOT read a PAC file - it needs a real")
        say("         host:port. Open the PAC URL above in the browser and read")
        say("         the PROXY line out of it, or ask IT for the host:port and")
        say("         whether there is an internal package mirror to use instead.")
    else:
        say("  ==>    no proxy configured here. If pip still cannot reach pypi,")
        say("         it is being blocked outright - use the offline wheel route.")
    say()


def find_browser(name):
    """Full path to Edge/Chrome, or None. Shared with start_here.py."""
    return (next((p for p in BROWSERS[name] if os.path.exists(p)), None)
            or shutil.which(name.lower())
            or shutil.which("msedge" if name == "Edge" else "chrome"))


def port_open(port=DEBUG_PORT, timeout=2):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def collect():
    """Run every check and return the report lines.

    Split out of main() so start_here.py can fold the probe into its own
    single-command report instead of shelling out and re-parsing the text.
    """
    LINES.clear()
    say(f"CTMS work-PC probe - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    say(f"machine: {platform.node()} | {platform.platform()}")
    say()

    say("PYTHON")
    say(f"  [OK]   version: {sys.version.split()[0]} at {sys.executable}")
    check("pip", lambda: subprocess.run(
        [sys.executable, "-m", "pip", "--version"], capture_output=True,
        text=True, timeout=60).stdout.strip() or "no output")
    say()

    # The engine's ENTIRE third-party surface, taken from the import graph and
    # not from memory: four pip packages, all pure-wheel on Windows. Worth
    # reporting separately from the automation extras, because these four are
    # the answer to "could the whole toolkit run on this machine".
    say("ENGINE DEPENDENCIES (pip install -r requirements.txt)")
    for mod, why in (("win32com.client", "pywin32 - drives Outlook"),
                     ("openpyxl", "reads/writes .xlsx"),
                     ("pdfplumber", "DTS PDFs"),
                     ("xlrd", "legacy .xls")):
        try:
            __import__(mod)
            say(f"  [OK]   present: {mod:16} ({why})")
        except Exception:
            say(f"  [--]   missing: {mod:16} ({why})")
    say()

    say("AUTOMATION EXTRAS (not needed - the CTMS tools are stdlib only)")
    for mod in ("requests", "playwright", "selenium"):
        try:
            __import__(mod)
            say(f"  [OK]   present: {mod}")
        except Exception:
            say(f"  [--]   missing: {mod} (fine)")
    say()

    say("NETWORK (from this machine)")
    check("Railway control plane", lambda: url_status("https://dhlbutbetter.up.railway.app/"))
    check("pypi.org (pip installs)", lambda: url_status("https://pypi.org/simple/"))
    check("github.com (code downloads)", lambda: url_status("https://github.com/"))
    check("playwright CDN (browser downloads)",
          lambda: url_status("https://playwright.azureedge.net/"))
    proxies = {k: v for k, v in os.environ.items()
               if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")}
    say(f"  [..]   proxy env vars: {proxies or 'none set'}")
    say()
    windows_proxy()

    # Outlook is the one thing that cannot be pip-installed, and process_form.py
    # opens the ad hoc form through Excel itself so the form's own formulas
    # produce the real values (it falls back to openpyxl's cached values, which
    # are only as good as the last save). So: is Office actually on this box?
    say("OFFICE (the only non-Python requirement)")
    for exe, why in (("OUTLOOK.EXE", "required - the engine drives it over COM"),
                     ("EXCEL.EXE", "wanted - ad hoc forms evaluate properly")):
        found = None
        for pat in (r"C:\Program Files\Microsoft Office\root\Office*",
                    r"C:\Program Files (x86)\Microsoft Office\root\Office*",
                    r"C:\Program Files\Microsoft Office\Office*",
                    r"C:\Program Files (x86)\Microsoft Office\Office*"):
            hits = glob.glob(os.path.join(pat, exe))
            if hits:
                found = hits[0]
                break
        say(f"  [{'OK' if found else '--'}]   {exe}: {found or 'not found in the usual places'}  ({why})")
    say()

    say("BROWSERS (for driving YOUR logged-in session - no passwords, ever)")
    for name in BROWSERS:
        found = find_browser(name)
        say(f"  [{'OK' if found else 'NO'}]   {name}: {found or 'not found'}")
    # is a debug session already listening? (harmless port check, no launch)
    if port_open():
        say(f"  [OK]   something already listening on the debug port {DEBUG_PORT}")
    else:
        say(f"  [--]   nothing on debug port {DEBUG_PORT} (expected - nothing launched yet)")
    say()
    return list(LINES)


def main():
    collect()
    say("Next: email ctms_probe_report.txt to yourself, subject 'CTMS probe'.")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ctms_probe_report.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    say(f"report written: {out}")


if __name__ == "__main__":
    main()
