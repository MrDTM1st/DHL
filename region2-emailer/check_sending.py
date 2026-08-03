"""
Why aren't emails going out? Answers it in one command, sends nothing.

    python check_sending.py

Every outbound email in the toolkit - site contacts, haulier cover requests,
chasers, wait-list releases, the rail plan, handover - goes through ONE gate:
send_order.dhl_account(), which walks the Outlook accounts looking for the
address the toolkit sends as. If that lookup returns None, every one of those
paths aborts. That is a single point of failure for all sending, and until now
it announced itself only as a line of text inside a job's output.

This prints what that lookup actually sees. READ-ONLY: it opens Outlook, reads
account names and the last few Sent Items, and stops. It never creates, sends
or modifies anything.
"""
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    print(f"Send check - {datetime.now():%d/%m/%Y %H:%M}\n")
    try:
        import win32com.client
    except Exception as e:
        print(f"[NO] pywin32 missing: {e}")
        return 1
    try:
        import build_drafts as bd
        import send_order as so
    except Exception as e:
        print(f"[NO] could not import the engine: {type(e).__name__}: {e}")
        return 1

    want = so.me_smtp()
    override = " - overridden by 'me' in config/team.json" if want != bd.DHL_SMTP else ""
    print(f"The toolkit sends AS: {want}")
    print(f"  (built-in default: {bd.DHL_SMTP}{override})\n")

    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception as e:
        print(f"[NO] Outlook did not answer COM: {type(e).__name__}: {e}")
        print("     Classic Outlook must be open and signed in (New Outlook has no COM).")
        return 1

    print("ACCOUNTS Outlook reports")
    match = None
    try:
        accts = ns.Accounts
        if not accts.Count:
            print("  [NO] none at all - this Outlook profile has no accounts")
        for i in range(1, accts.Count + 1):
            a = accts.Item(i)
            raw = ""
            try:
                raw = str(a.SmtpAddress or "")
            except Exception as e:
                raw = f"<unreadable: {type(e).__name__}>"
            resolved = so.acct_smtp(a)
            hit = resolved == want
            if hit:
                match = a
            print(f"  [{'OK' if hit else '--'}]  {resolved or '(no address)'}")
            if raw.strip().lower() != resolved:
                # the Exchange case: SmtpAddress is blank or an X.500 DN and the
                # real address only appears after GetExchangeUser()
                print(f"         SmtpAddress reported {raw!r} - resolved via Exchange lookup")
    except Exception as e:
        print(f"  [NO] could not read accounts: {type(e).__name__}: {e}")

    print()
    if match:
        print("VERDICT: the send gate PASSES - dhl_account() finds the account.")
        print("         If mail still isn't going out the cause is downstream;")
        print("         send one order from the dashboard and read the output.")
    else:
        print("VERDICT: the send gate FAILS - dhl_account() returns None, so")
        print("         EVERY send path aborts: site contacts, hauliers, chasers,")
        print("         wait-list releases, rail plan, handover.")
        print()
        print("  Fix: set \"me\" in config/team.json to whichever address above is")
        print("  yours, exactly as Outlook reports it. No code change needed.")

    # Sent Items is the ground truth - the tool's own logs can lie, this can't
    print("\nRECENT SENT ITEMS (ground truth - did anything actually leave?)")
    try:
        sent = ns.GetDefaultFolder(5)          # 5 = olFolderSentMail
        items = sent.Items
        items.Sort("[SentOn]", True)
        cutoff = datetime.now() - timedelta(days=14)
        n = 0
        for i in range(1, min(getattr(items, "Count", 0), 40) + 1):
            it = items.Item(i)
            try:
                when = it.SentOn
                subj = str(it.Subject or "")[:60]
            except Exception:
                continue
            try:
                if when.replace(tzinfo=None) < cutoff:
                    break
            except Exception:
                pass
            n += 1
            if n <= 10:
                print(f"  {when:%d/%m %H:%M}  {subj}")
        print(f"  -> {n} item(s) sent in the last 14 days"
              + ("  ** NOTHING SENT - consistent with the gate failing **" if n == 0 else ""))
    except Exception as e:
        print(f"  (could not read Sent Items: {type(e).__name__}: {e})")

    return 0 if match else 2


if __name__ == "__main__":
    sys.exit(main())
