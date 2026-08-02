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


def main():
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
    candidates = {
        "Edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "Chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
    }
    for name, paths in candidates.items():
        found = next((p for p in paths if os.path.exists(p)), None) \
            or shutil.which(name.lower()) or shutil.which("msedge" if name == "Edge" else "chrome")
        say(f"  [{'OK' if found else 'NO'}]   {name}: {found or 'not found'}")
    # is a debug session already listening? (harmless port check, no launch)
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", 9222))
        say("  [OK]   something already listening on the debug port 9222")
    except Exception:
        say("  [--]   nothing on debug port 9222 (expected - nothing launched yet)")
    finally:
        s.close()
    say()

    say("Next: email ctms_probe_report.txt to yourself, subject 'CTMS probe'.")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ctms_probe_report.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    say(f"report written: {out}")


if __name__ == "__main__":
    main()
