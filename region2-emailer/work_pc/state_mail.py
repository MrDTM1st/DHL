"""
Move the state between machines through the mailbox they already share.

    HOME PC:  python state_mail.py send           bundle + save a DRAFT
              python state_mail.py send now       bundle + send it
              python state_mail.py send --live    include the live state too

    WORK PC:  python state_mail.py fetch          find it, show what it holds
              python state_mail.py fetch apply    restore it onto this machine

The USB route is closed on the work PC and the code route (git, pip, urllib)
keeps hitting the proxy. Outlook is the one channel that already works on both
machines, because both have delali.opoku@dhl.com in Classic Outlook - that is
the whole premise of the migration. So the bundle travels as an attachment on a
mail from you to you, inside DHL's own mail system: no USB, no personal cloud,
nothing to be approved, and the contact books never leave the tenant.

It carries the same files collect_state carries - the list is imported, not
retyped - and hands the restore to collect_state.restore(), so you get the same
"here is what I am about to replace, type YES" prompt and the same .bak copies.

`send` writes a DRAFT by default and stops. You press send in Outlook. That is
deliberate: nothing here should put mail in your Sent Items on its own.
"""
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta

import collect_state
from engine_preflight import ENGINE

SUBJECT = "DHL-STATE"          # the marker fetch looks for; keep it distinctive
ATTACH = "dhl-state.zip"

# order_index.json is 10.6 MB - bigger than everything else put together - and
# STATE_GROUPS itself calls it "rebuilds itself, slowly". Posting it through a
# mailbox to save the work PC an afternoon of rebuilding is a bad trade against
# attachment limits, so it is out unless you ask for it.
BIG = {"order_index.json"}
WARN_MB = 20


def _zip_bundle(tmp, include_live, include_optional, with_index):
    """collect_state's own backup, zipped."""
    staged = os.path.join(tmp, "state")
    collect_state.backup(staged, include_live, include_optional)
    if not with_index:
        drop = os.path.join(staged, "order_index.json")
        if os.path.exists(drop):
            os.remove(drop)
            print("  (order_index.json left out - it rebuilds itself. "
                  "--with-index to include it)")
    zpath = os.path.join(tmp, ATTACH)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(staged):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, staged))
    return zpath


def _outlook():
    import win32com.client
    return win32com.client.Dispatch("Outlook.Application")


def _me():
    """The address to post to. team.json if it is here, else the constant."""
    try:
        import json
        cfg = os.path.join(ENGINE, "config", "team.json")
        if os.path.exists(cfg):
            return str(json.load(open(cfg, encoding="utf-8")).get("me") or "").strip()
    except Exception:
        pass
    return "delali.opoku@dhl.com"


def send(argv):
    live = "--live" in argv
    with_index = "--with-index" in argv
    # Opt IN, not out - the opposite of collect_state's default, on purpose.
    # The OPTIONAL group holds cloud.json, which is the Railway agent KEY, and
    # the two switches that make the engine act without being asked. Neither
    # belongs in a mail attachment by default, and step 9 wants both switches
    # off on the new machine's first day anyway.
    optional = "--optional" in argv
    really = "now" in argv

    tmp = tempfile.mkdtemp(prefix="dhl-state-mail-")
    try:
        print(f"Bundling{' WITH live state' if live else ' (no live state)'}:\n")
        zpath = _zip_bundle(tmp, live, optional, with_index)
        mb = os.path.getsize(zpath) / (1024 * 1024)
        print(f"\n  bundle: {mb:.1f} MB")
        if mb > WARN_MB:
            print(f"  !! over {WARN_MB} MB - your mail system may refuse it.")
            print("     Drop --with-index, or send in two goes.")

        to = _me()
        stamp = f"{datetime.now():%d/%m/%Y %H:%M}"
        host = os.environ.get("COMPUTERNAME", "?")
        subject = f"{SUBJECT} {stamp} [{host}]{' LIVE' if live else ''}"

        m = _outlook().CreateItem(0)
        m.To = to
        m.Subject = subject
        m.Body = (
            "Toolkit state bundle - machine-readable, do not edit.\n\n"
            f"From: {host}\nTaken: {stamp}\n"
            f"Live state included: {live}\n"
            f"Optional group included: {optional}\n"
            f"order_index.json included: {with_index}\n\n"
            "On the work PC:  python work_pc\\state_mail.py fetch\n"
        )
        m.Attachments.Add(zpath)

        # Bind the DHL account when the engine is importable, so this leaves the
        # right mailbox on a machine with several. Not fatal if it is not.
        try:
            sys.path.insert(0, ENGINE)
            import send_order as so
            import build_drafts as bd
            acct = so.dhl_account(bd.get_ns())
            if acct is not None and not so.bind_account(m, acct):
                print("  (could not bind the DHL account - check the From line)")
        except Exception:
            print("  (engine not importable here - check the From line yourself)")

        if really:
            m.Send()
            print(f"\nSENT to {to}\n  {subject}")
        else:
            m.Save()          # lands in Drafts
            print(f"\nDRAFT saved to {to}\n  {subject}")
            print("\n  Open Outlook and press Send. Or re-run with 'now' to send it:")
            print("    python work_pc\\state_mail.py send now"
                  + (" --live" if live else ""))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_mail(days=30):
    """Newest DHL-STATE mail with an attachment, across every store.

    Deliberately does NOT use build_drafts.dhl_store(): that matches a store by
    DISPLAY NAME against the address, and on a fresh managed profile the store
    is often displayed as "Opoku, Delali" instead - which would make this find
    nothing on exactly the machine it exists to bootstrap. Search them all.
    """
    import win32com.client
    ns = _outlook().GetNamespace("MAPI")
    cutoff = datetime.now() - timedelta(days=days)
    best = None
    for i in range(1, ns.Stores.Count + 1):
        try:
            inbox = ns.Stores.Item(i).GetDefaultFolder(6)      # 6 = Inbox
        except Exception:
            continue
        for folder in [inbox] + [inbox.Folders.Item(j)
                                 for j in range(1, inbox.Folders.Count + 1)]:
            try:
                items = folder.Items
                items.Sort("[ReceivedTime]", True)
                for k in range(1, min(getattr(items, "Count", 0), 200) + 1):
                    it = items.Item(k)
                    try:
                        subj = str(it.Subject or "")
                        when = it.ReceivedTime.replace(tzinfo=None)
                    except Exception:
                        continue
                    if when < cutoff:
                        break
                    if not subj.upper().startswith(SUBJECT):
                        continue
                    if it.Attachments.Count < 1:
                        continue
                    if best is None or when > best[0]:
                        best = (when, subj, it)
            except Exception:
                continue
    return best


def fetch(argv):
    apply = "apply" in argv
    optional = "--optional" in argv       # matches send: opt in, never by default

    found = _find_mail()
    if not found:
        print(f"No '{SUBJECT} ...' mail with an attachment in the last 30 days.")
        print("Send one from the home PC first:  python work_pc\\state_mail.py send")
        return 1
    when, subj, item = found
    print(f"Found: {subj}\n  received {when:%d/%m/%Y %H:%M}")

    tmp = tempfile.mkdtemp(prefix="dhl-state-fetch-")
    try:
        att = None
        for i in range(1, item.Attachments.Count + 1):
            a = item.Attachments.Item(i)
            if str(a.FileName or "").lower().endswith(".zip"):
                att = a
                break
        if att is None:
            print("  that mail has no .zip attachment.")
            return 1
        zpath = os.path.join(tmp, "bundle.zip")
        att.SaveAsFile(zpath)
        staged = os.path.join(tmp, "state")
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            z.extractall(staged)
        print(f"  {len(names)} file(s) in the bundle: {', '.join(sorted(names)[:8])}"
              + (" ..." if len(names) > 8 else ""))

        if not apply:
            print("\nDRY RUN - nothing written. To restore onto this machine:")
            print("  python work_pc\\state_mail.py fetch apply")
            return 0

        # collect_state.restore does the rest: shows what it replaces, makes you
        # type YES, keeps the old copy as <name>.bak, never deletes.
        print()
        collect_state.restore(staged, optional)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    argv = [a.strip().lower() for a in sys.argv[1:]]
    if not argv or argv[0] not in ("send", "fetch"):
        print(__doc__)
        return 2
    return send(argv) if argv[0] == "send" else fetch(argv)


if __name__ == "__main__":
    sys.exit(main())
