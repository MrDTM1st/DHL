"""
Work-PC probe - answers "what can this machine actually do?" before any
CTMS automation is written for it.

Standard library only, on purpose: it must run on a bare corporate Python
with nothing installed. It READS the environment and writes a report; it
changes nothing, installs nothing, and never touches credentials.

    python ctms_probe.py

Then email ctms_probe_report.txt to yourself (subject: CTMS probe).
"""
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
    for mod in ("requests", "playwright", "selenium", "win32com.client", "openpyxl"):
        try:
            __import__(mod)
            say(f"  [OK]   module already present: {mod}")
        except Exception:
            say(f"  [--]   module not installed (fine): {mod}")
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
