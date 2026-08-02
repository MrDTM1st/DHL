"""
Proves the automation can ATTACH to a browser you logged into yourself -
the no-credentials approach. Standard library only; installs nothing.

1. Close Edge completely, then start it with a debug port (paste into
   Command Prompt - one line):

   "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\\ctms-automation-profile"

   (A fresh window opens with its own profile - log into CTMS in it
   yourself, as normal. Your password never touches any script.)

2. With that window open, run:   python ctms_attach_test.py

It lists the open tabs it can see and writes ctms_attach_report.txt -
email that to yourself (subject: CTMS probe) with the probe report.
"""
import json
import os
import urllib.request
from datetime import datetime

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctms_attach_report.txt")


def main():
    lines = [f"CTMS attach test - {datetime.now().strftime('%d/%m/%Y %H:%M')}"]
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as r:
            v = json.load(r)
        lines.append(f"[OK] debug browser found: {v.get('Browser')} (CDP {v.get('Protocol-Version')})")
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
            tabs = json.load(r)
        pages = [t for t in tabs if t.get("type") == "page"]
        lines.append(f"[OK] {len(pages)} tab(s) visible to the automation:")
        for t in pages:
            lines.append(f"     - {t.get('title', '?')[:60]} | {t.get('url', '?')[:80]}")
        lines.append("")
        lines.append("ATTACH WORKS. Log into CTMS in that window (if you haven't), then this")
        lines.append("machine can drive it - no password ever stored.")
    except Exception as e:
        lines.append(f"[NO] could not reach the debug port: {type(e).__name__}: {e}")
        lines.append("     Is the Edge window from step 1 open? Was Edge FULLY closed first?")
    print("\n".join(lines))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nreport written: {OUT}")


if __name__ == "__main__":
    main()
