"""The toolkit's own on/off switch: the Toolkit switch on the Dashboard (asked for 21/11: "a button that turns on and
off the whole toolkit on the dashboard, just because we're now having issues with Outlook even opening on the home
PC").

Off is a FILE, toolkit.off next to this one, as auto_chase.enabled is for the chasers. All the toolkit's Outlook work
on the home PC is done by processes of their own, and each looks at the file when it starts, so a flip takes effect at
once with nothing restarted, and lasts through a restart of the agents, the supervisor or the whole PC.

While it is off:
  - the supervisor starts no live monitor or home tick (and one started anyway goes away at once)
  - the local agent starts none of its timer jobs (and outlook_gate refuses one started anyway)
  - both agents turn down every dashboard command but the switch itself and Update the home PC, and the work-mail
    channel's asks
  - the cloud dashboard refuses the buttons that start work, and starts nothing by itself (set-time CTMS look-ups,
    escalation look-ups, the rejection card's Auto)
What is still running when it goes off finishes by itself; the panel says what that is. Both agents stay connected,
so the dashboard can turn it back on, and keep its lists up to date from their files - reading files, not Outlook.

    python toolkit_switch.py            # how it is
    python toolkit_switch.py off|on     # flip it here (the dashboard's switch does the same)
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(HERE, "toolkit.off")

OFF_SAID = ("The toolkit is switched off, so the home PC is leaving Outlook alone - turn it on with the Toolkit "
            "switch on the Dashboard first.")
# what the agents still do from the dashboard while it is off: the switch, and the home PC's code update (git only)
ALWAYS = ("set_toolkit", "home_update")

# the local agent's timer jobs, as the dashboard says them while they finish
LABELS = {
    "waitlist_release": "the wait-list send", "chase": "the chasers", "book_retry": "the booking follow-ups",
    "adhoc_sweep": "the ad hoc sweep", "phase2_check": "the reply check", "haulier_asks": "who's been asked",
    "rejections": "the rejection replies", "inbox_watch": "the inbox watch", "daily_update": "the Updates reply",
    "om_tries": "the Order Management look", "dts_sheet": "the DTS sheet", "order_index": "the order index",
    "waitscan": "the wait-list scan", "recover": "the recover sweep", "planner_week": "the planner sheet",
}
# the supervisor's minute ticks: (said as, outlook_gate's single-instance name)
TICKS = (("the live monitor", "monitor_tick"), ("the home tick", "home_tick"))


def is_off():
    """True while the switch is off. Never raises: a switch that can't be read is on, as it always was."""
    try:
        return os.path.exists(FLAG)
    except Exception:
        return False


def since():
    """When it was switched off ("21/11 18:40"), or ""."""
    try:
        with open(FLAG, encoding="utf-8") as f:
            return str(json.load(f).get("since") or "")[:20]
    except Exception:
        return ""


def switch(on, by="the dashboard", now=None):
    """Turn it on (the file goes) or off (the file is written - kept as it is if it is off already, so "since" stays
    the first time). -> True when it is now on."""
    if on:
        try:
            os.remove(FLAG)
        except FileNotFoundError:
            pass
    elif not is_off():
        note = {"since": time.strftime("%d/%m %H:%M", time.localtime(now)), "by": str(by)[:60],
                "note": "The toolkit is switched OFF: nothing on this PC uses Outlook. Turn it back on with the "
                        "Toolkit switch on the dashboard (or delete this file)."}
        tmp = FLAG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(note, f, indent=1)
        os.replace(tmp, FLAG)
    return not is_off()


def _held(name):
    """True when a live process holds the named lock - outlook_gate's single-instance mutexes, which Windows frees the
    moment their process dies, so a crash or a kill can never leave one looking busy."""
    try:
        import win32event
        h = win32event.OpenMutex(0x00100000, False, name)        # SYNCHRONIZE: only to see that it is there
    except Exception:
        return False
    try:
        h.Close()
    except Exception:
        pass
    return True


def busy(jobs=()):
    """What of the toolkit's Outlook work is still going: each of `jobs` - (timer job key, its args), as agent.py's
    _bg_jobs gives them - and the supervisor's ticks, whose single-instance lock a live process still holds."""
    import outlook_gate
    locks = [(LABELS.get(key, str(key).replace("_", " ")), "Local\\R2_single_" + outlook_gate.job_lock(args))
             for key, args in jobs]
    locks += [(said, "Local\\R2_single_" + name) for said, name in TICKS]
    out = []
    for said, name in locks:
        if said not in out and _held(name):
            out.append(said)
    return out


def outlook():
    """How Outlook is on this PC, for the dashboard while the toolkit is off: "open", "not responding", "running with
    no window" (started but showing nothing - how it was on 21/11) or "not running". "" when it can't be told."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("rctrl_renwnd32", None)      # Outlook's main window
        if hwnd:
            return "not responding" if user32.IsHungAppWindow(hwnd) else "open"
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True, timeout=10, creationflags=0x08000000)
    except Exception:
        return ""
    return "running with no window" if "outlook.exe" in (r.stdout or "").lower() else "not running"


def state(jobs=(), extra=()):
    """For the dashboard's panel: {"on": True}, or while it is off {"on": False, "since", "busy", "outlook"} - `extra`
    is work the asking agent knows it is doing itself (a work-mail ask)."""
    if not is_off():
        return {"on": True}
    try:
        going = busy(jobs)
    except Exception:
        going = []
    return {"on": False, "since": since(), "busy": [str(e) for e in extra if e] + going, "outlook": outlook()}


if __name__ == "__main__":
    if sys.argv[1:2] in (["on"], ["off"]):
        switch(sys.argv[1] == "on", by="this PC")
    s = state()
    print("Toolkit " + ("ON" if s["on"] else f"OFF since {s['since']} - Outlook: {s['outlook'] or 'unknown'}"
                        + (f"; still finishing: {', '.join(s['busy'])}" if s["busy"] else "")))
