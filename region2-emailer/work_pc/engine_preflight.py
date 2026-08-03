"""
Can this machine run the WHOLE toolkit, not just the CTMS tools?

    python engine_preflight.py

start_here.py answers "can we automate CTMS here". This answers the bigger
question: could the engine itself - extracts, sends, replies, tracker, briefs -
move off the home PC and run here instead. It checks the four pip packages,
Outlook and Excel over COM, the ports the supervisor needs, whether the local
state files have been brought across, and whether this machine actually STAYS
AWAKE, because every timed job dies with the session.

READ-ONLY. It opens Outlook and Excel to prove they answer, reads nothing but
folder names, sends nothing and changes nothing. No addresses are printed - the
report is meant to be pasted into a chat, so accounts come out masked.
"""
import os
import socket
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)          # region2-emailer/, one level up
LINES = []


def say(line=""):
    print(line)
    LINES.append(line)


def mask(addr):
    """Never print a full address - this report gets pasted into a chat."""
    addr = str(addr or "")
    if "@" not in addr:
        return addr[:1] + "***" if addr else "(none)"
    user, _, dom = addr.partition("@")
    return f"{user[:1]}***@{dom}"


def section(name):
    say()
    say(name)


def packages():
    section("ENGINE DEPENDENCIES")
    missing = []
    for mod, why in (("win32com.client", "pywin32 - Outlook and Excel over COM"),
                     ("openpyxl", "the .xlsx work"),
                     ("pdfplumber", "DTS PDFs"),
                     ("xlrd", "legacy .xls")):
        try:
            __import__(mod)
            say(f"  [OK]   {mod:16} {why}")
        except Exception:
            missing.append(mod)
            say(f"  [NO]   {mod:16} {why}")
    if missing:
        # Absolute, not "..\requirements.txt" - that hint is only right if you
        # happen to be standing in work_pc\, and the natural place to run this
        # from is the engine folder, where it sent you looking for a file that
        # is already in front of you.
        say(f"         -> pip install -r \"{os.path.join(ENGINE, 'requirements.txt')}\"")
    return not missing


def outlook():
    section("OUTLOOK (required - there is no substitute for this one)")
    try:
        import win32com.client
    except Exception as e:
        say(f"  [NO]   pywin32 not importable: {type(e).__name__}: {e}")
        return False
    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        accounts = list(ns.Accounts)
        say(f"  [OK]   Outlook answered COM - {len(accounts)} account(s):")
        for a in accounts:
            say(f"         - {mask(getattr(a, 'SmtpAddress', ''))}")
        # The engine files briefs into "Region 2 > Send Out". Finding it here is
        # the difference between "Outlook works" and "this is the right mailbox".
        found = []
        for store in ns.Folders:
            try:
                for f in store.Folders:
                    if f.Name.strip().lower() == "region 2":
                        subs = [s.Name for s in f.Folders]
                        found.append(f"{store.Name}: Region 2 ({', '.join(subs) or 'no subfolders'})")
            except Exception:
                continue
        if found:
            for f in found:
                say(f"  [OK]   folder found -> {f}")
        else:
            say("  [--]   no 'Region 2' folder seen - either a different mailbox,")
            say("         or the folders have not been made on this profile yet")
        return True
    except Exception as e:
        say(f"  [NO]   Outlook COM failed: {type(e).__name__}: {e}")
        say("         Is Classic Outlook open and signed in? (New Outlook has no COM)")
        return False


def excel():
    section("EXCEL (wanted - ad hoc forms evaluate their own formulas)")
    try:
        import win32com.client
        xl = win32com.client.Dispatch("Excel.Application")
        try:
            say(f"  [OK]   Excel answered COM - version {xl.Version}")
        finally:
            xl.Quit()
        return True
    except Exception as e:
        say(f"  [--]   Excel COM unavailable: {type(e).__name__}: {e}")
        say("         Not fatal: process_form.py falls back to openpyxl's cached")
        say("         values, which are only as good as the workbook's last save.")
        return False


def ports():
    section("PORTS (the supervisor's single-instance locks)")
    names = {8785: "watchdog", 8786: "supervisor", 8787: "control plane",
             8788: "local agent", 8789: "cloud agent", 8790: "chase run",
             8791: "wait-list release"}
    clash = []
    for p, what in sorted(names.items()):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            s.bind(("127.0.0.1", p))
            say(f"  [OK]   {p} free ({what})")
        except OSError:
            clash.append(p)
            say(f"  [NO]   {p} IN USE ({what}) - something already holds it")
        finally:
            s.close()
    return not clash


def state_files():
    section("LOCAL STATE (not in the repo - it has to be copied across)")
    groups = [
        ("IRREPLACEABLE - copy these or lose them", [
            ("_metrics.jsonl", "the evidence log for the business case"),
            ("_details_learned.json", "every parser correction you've confirmed"),
            ("_quotes.json", "haulier quotes per lane"),
            ("config.json", "region, postcode areas, extract rules"),
            ("config/team.json", "roster + never-email-yourself"),
            ("synergy_template.xlsx", "the Supplier Details contact book"),
            ("_rail_recipients.json", "rail-plan distribution chains"),
        ]),
        ("LIVE STATE - copy at cutover, not before", [
            ("tracker.json", "open orders being chased"),
            ("waitlist.json", "far-ahead orders held back"),
            ("_booked_drops.json", "booked drops, so sweeps can't resurrect them"),
            ("_adhocs.json", "ad hoc map records"),
            ("order_index.json", "order -> extract (rebuilds itself, slowly)"),
        ]),
        ("REBUILDABLE - from a source sheet, but not quickly", [
            ("_hauliers.json", "hauliers.py import <contact list.xlsx>"),
            ("_synergy_sites.json", "seeded from Supplier Details"),
            ("_sites.json", "self-learning delivery sites"),
        ]),
        ("OPTIONAL", [
            ("cloud.json", "Railway URL + agent key (phone access)"),
            ("qr.png", "feedback QR in the signature"),
            ("auto_chase.enabled", "switch: chasers send by themselves"),
            ("auto_recover.enabled", "switch: daily untracked-order sweep"),
        ]),
    ]
    have = missing = 0
    for title, files in groups:
        say(f"  {title}")
        for name, why in files:
            if os.path.exists(os.path.join(ENGINE, name)):
                have += 1
                say(f"    [OK]   {name:24} {why}")
            else:
                missing += 1
                say(f"    [--]   {name:24} {why}")
    say(f"  -> {have} present, {missing} not here yet")
    return have, missing


def power():
    section("STAYING AWAKE (every timed job dies with the session)")
    if os.name != "nt":
        say("  [--]   not Windows - skipped")
        return
    def setting(sub, item, label):
        try:
            out = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", sub, item],
                                 capture_output=True, text=True, timeout=30).stdout
            ac = None
            for line in out.splitlines():
                if "Current AC Power Setting Index" in line:
                    ac = int(line.split(":")[1].strip(), 16)
                    break
            if ac is None:
                say(f"  [--]   {label}: could not read")
            elif ac == 0:
                say(f"  [OK]   {label}: never (plugged in)")
            else:
                say(f"  [NO]   {label}: after {ac // 60} min (plugged in)")
        except Exception as e:
            say(f"  [--]   {label}: {type(e).__name__}: {e}")
    setting("SUB_SLEEP", "STANDBYIDLE", "sleep when idle")
    setting("SUB_SLEEP", "HIBERNATEIDLE", "hibernate when idle")
    setting("SUB_BUTTONS", "LIDACTION", "closing the lid")
    say("         Anything other than 'never' means the 60s monitor, the 20-min")
    say("         reply check, the 3-hourly chasers and the wait-list release")
    say("         all stop until you log back in.")


def autostart():
    section("AUTOSTART (the watchdog has to come back at logon)")
    if os.name != "nt":
        say("  [--]   not Windows - skipped")
        return
    startup = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup")
    if not os.path.isdir(startup):
        say(f"  [NO]   Startup folder not found at {startup}")
        return
    say(f"  [OK]   Startup folder: {startup}")
    try:
        probe = os.path.join(startup, ".dhl_write_test")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        say("  [OK]   it is writable - the watchdog can be put there")
    except Exception as e:
        say(f"  [NO]   not writable ({type(e).__name__}) - policy may be locking it;")
        say("         Task Scheduler at logon is the fallback")
    # desktop.ini is Windows' own folder-metadata file and is in EVERY Startup
    # folder. Matching it on "desk" reported "already there: ['desktop.ini']",
    # which reads as "the watchdog is installed" when nothing is installed.
    existing = [f for f in os.listdir(startup)
                if f.lower() != "desktop.ini"
                and ("desk_watchdog" in f.lower() or "dhl" in f.lower())]
    say(f"  [{'OK' if existing else '--'}]   watchdog already installed: {existing or 'no - nothing yet'}")


def main():
    say(f"Engine preflight - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    say(f"machine: {os.environ.get('COMPUTERNAME') or 'unknown'}")
    say(f"engine folder: {ENGINE}")
    say()
    say("PYTHON")
    say(f"  [OK]   {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 9):
        say("  [NO]   too old - the engine is written against 3.12")

    deps = packages()
    ol = outlook()
    excel()
    free = ports()
    have, missing = state_files()
    power()
    autostart()

    section("VERDICT")
    if ol and deps and free:
        say("  The engine can run on this machine.")
    else:
        say("  Not yet:")
        if not deps:
            say("    - install the missing packages")
        if not ol:
            say("    - Outlook has to answer COM (Classic, signed in)")
        if not free:
            say("    - a port is taken; something may already be running")
    if missing:
        say(f"  {missing} local state file(s) still to copy across - the engine")
        say("  will start without them but it will not know anything yet.")
    say()
    say("  BEFORE STARTING THE ENGINE HERE: stop it on the home PC first.")
    say("  The single-instance locks are all 127.0.0.1 ports and the chase")
    say("  claim is written to the LOCAL tracker.json, so neither one can see")
    say("  another machine. Two PCs on one mailbox = every chaser sent twice.")

    out = os.path.join(HERE, "engine_preflight_report.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\n" + "=" * 62)
    print("COPY EVERYTHING BETWEEN THE MARKERS INTO THE CHAT")
    print("=" * 62)
    print("----- BEGIN ENGINE PREFLIGHT -----")
    print("\n".join(LINES))
    print("----- END ENGINE PREFLIGHT -----")
    print(f"\n(also saved to {out})")


if __name__ == "__main__":
    main()
