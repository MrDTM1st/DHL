"""Holiday handover — the COM side, called by the agent's `handover_start`.

    python handover_cli.py start <days> <cover> <forward01> [notes]

Resolves the cover person from config/team.json, writes the handover state, and
sends the outstanding-work email from the DHL account (never to yourself). The
supervisor's home_tick.py handles auto-forwarding + auto-end while you're away.
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_drafts as bd
import send_order as so
import tracker
from modules import handover, profiles

HANDOVER_PATH = os.path.join(HERE, "_handover.json")
MY_NAME = "Delali Opoku"


def _team():
    try:
        return profiles.load_team(os.path.join(HERE, "config", "team.json"))
    except Exception:
        return {"members": []}


def start(days, cover, forward, notes):
    member = profiles.find_member(_team(), cover)
    if not member:
        print(f"ERROR: no team member matches '{cover}' - add them to config/team.json")
        return 1
    import win32com.client
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    state = handover.start(HANDOVER_PATH, days, member["name"], member["email"], notes, forward)
    records = tracker.load().get("records", [])
    spec = handover.build_handover_email(state, records, sender_name=MY_NAME)
    to, cc, _ = bd.clean_to_cc(spec["to"], spec.get("cc", ""))
    if not to:
        print("ERROR: no valid cover recipient after removing your own address.")
        return 1
    acct = so.dhl_account(ns)
    if acct is None:
        print("ERROR: DHL account not found in Outlook - nothing sent.")
        return 1
    outlook = win32com.client.Dispatch("Outlook.Application")
    m = outlook.CreateItem(0)
    m.To = to
    m.Subject = spec["subject"]
    bd._attach_qr(m)
    m.HTMLBody = bd.html_from_message(spec["message"])
    if not so.bind_account(m, acct):
        print("ERROR: could not bind DHL account - nothing sent.")
        return 1
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    print(f"SENT handover to {member['name']} <{to}>; cover until {state['end']}")
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] != "start":
        print("usage: handover_cli.py start <days> <cover> <forward01> [notes]")
        return
    days = args[1] if len(args) > 1 else "5"
    cover = args[2] if len(args) > 2 else ""
    forward = (args[3] if len(args) > 3 else "1") == "1"
    notes = args[4] if len(args) > 4 else ""
    sys.exit(start(days, cover, forward, notes))


if __name__ == "__main__":
    main()
