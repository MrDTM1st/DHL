"""
Work PC, one command. Run this and nothing else:

    python start_here.py

It does the whole Stage 0 setup in one go:

  1. probes the machine (Python, pip, network, browsers) - installs nothing
  2. LAUNCHES the debug browser for you, on its own profile, so you never have
     to paste that long msedge.exe command line again
  3. proves the automation can attach to it
  4. writes ONE report and prints it between two markers so you can select it,
     copy it, and paste it straight into the chat

Standard library only, READ-ONLY, and your CTMS password is never typed into,
stored in, or read by any of this. You log in yourself in the window it opens;
the tools only ever drive a session you already opened.
"""
import json
import os
import subprocess
import tempfile
import time
import urllib.request

import ctms_probe
from ctms_probe import DEBUG_PORT, find_browser, port_open, say

# Its own profile directory, deliberately NOT your normal one. Two reasons:
# a browser started with a --user-data-dir that is already in use just hands
# the arguments to the running instance and exits, so the debug port never
# opens; and keeping it separate means you do not have to close the Edge you
# are actually working in - the first version of this asked him to close every
# window and lose his tabs, which is a real cost on a work machine.
PROFILE = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
                       "ctms-automation-profile")
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "ctms_workpc_report.txt")


def launch(exe):
    args = [
        exe,
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    # Detached, so closing this Command Prompt does not take the browser with
    # it - the walkthrough happens in that window long after this script exits.
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    subprocess.Popen(args, close_fds=True, **kwargs)


def wait_for_port(seconds=25):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(timeout=1):
            return True
        time.sleep(1)
    return False


def attach_report():
    """What can the automation see? Also the proof that no password is needed."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=5) as r:
            v = json.load(r)
        say(f"  [OK]   attached to: {v.get('Browser')} (CDP {v.get('Protocol-Version')})")
        with urllib.request.urlopen(
                f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=5) as r:
            tabs = json.load(r)
        pages = [t for t in tabs if t.get("type") == "page"]
        say(f"  [OK]   {len(pages)} tab(s) visible to the automation:")
        for t in pages:
            say(f"         - {t.get('title', '?')[:60]} | {t.get('url', '?')[:80]}")
        return True
    except Exception as e:
        say(f"  [NO]   could not attach: {type(e).__name__}: {e}")
        return False


def main():
    print(__doc__)
    ctms_probe.collect()

    say("DEBUG BROWSER")
    launched = False
    if port_open():
        say(f"  [OK]   port {DEBUG_PORT} already open - attaching to what is there")
    else:
        exe = find_browser("Edge") or find_browser("Chrome")
        if not exe:
            say("  [NO]   no Edge or Chrome found - nothing to launch")
        else:
            say(f"  [..]   launching: {exe}")
            say(f"  [..]   profile:   {PROFILE}")
            try:
                launch(exe)
            except Exception as e:
                say(f"  [NO]   launch failed: {type(e).__name__}: {e}")
            if wait_for_port():
                launched = True
                say(f"  [OK]   debug port {DEBUG_PORT} is open")
            else:
                say(f"  [NO]   port {DEBUG_PORT} never opened after 25s.")
                # The likely cause on a managed machine, worth naming outright
                # so the report answers it rather than prompting another round
                # trip: Edge policy can switch remote debugging off entirely.
                say("         Most likely: group policy has remote debugging")
                say("         disabled on this build (RemoteDebuggingAllowed),")
                say("         or the browser was blocked from starting.")
    ok = attach_report()
    say()

    if ok:
        # Say which window, accurately. On a re-run the port is already open and
        # nothing new appeared - telling him to use "the window that just
        # opened" would have him hunting for a window that was never there.
        where = ("the browser window that just opened" if launched
                 else f"the browser already on port {DEBUG_PORT}")
        say(f"VERDICT: attach works. Log into CTMS in {where},")
        say("         then run:  python ctms_capture.py")
    else:
        say("VERDICT: no debug session. Send this report as-is - the capture step")
        say("         gets rewritten around whatever this machine does allow.")
    say()

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(ctms_probe.LINES) + "\n")

    print("\n" + "=" * 62)
    print("COPY EVERYTHING BETWEEN THE MARKERS INTO THE CHAT")
    print("=" * 62)
    print("----- BEGIN CTMS WORK-PC REPORT -----")
    print("\n".join(ctms_probe.LINES))
    print("----- END CTMS WORK-PC REPORT -----")
    print(f"\n(also saved to {REPORT} - or email it to yourself,"
          f" subject 'CTMS probe', if that is easier)")


if __name__ == "__main__":
    main()
