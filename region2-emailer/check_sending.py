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


def _sent_folder(ns, match, want):
    """The Sent Items of the mailbox we actually send AS.

    NOT ns.GetDefaultFolder(5). That returns the sent folder of the profile's
    DEFAULT store, which need not be the work account - on this profile the
    default is a personal account idle since 2023. Reading it reported
    "NOTHING SENT" while the DHL mailbox had sent 120 emails in three weeks,
    inventing an outage that was never there. A ground-truth check that can be
    wrong about the ground is worse than no check at all, so resolve the store
    explicitly: the account's own DeliveryStore, then a match on store name.
    """
    if match is not None:
        try:
            return match.DeliveryStore.GetDefaultFolder(5)   # 5 = olFolderSentMail
        except Exception:
            pass
    for i in range(1, ns.Stores.Count + 1):
        try:
            st = ns.Stores.Item(i)
            if str(st.DisplayName or "").strip().lower() == str(want).strip().lower():
                return st.GetDefaultFolder(5)
        except Exception:
            continue
    return None


def _report_sent(ns, match, want, days=14, scan=400):
    """Print what actually left the sending mailbox in the last `days`."""
    print("\nRECENT SENT ITEMS (ground truth - did anything actually leave?)")
    try:
        sent = _sent_folder(ns, match, want)
        if sent is None:
            print(f"  (no mailbox found for {want} - cannot tell what was sent)")
            return
        print(f"  reading: {sent.Store.DisplayName} \\ {sent.Name}")
        items = sent.Items
        items.Sort("[SentOn]", True)
        cutoff = datetime.now() - timedelta(days=days)
        total = getattr(items, "Count", 0)
        n, capped = 0, False
        for i in range(1, min(total, scan) + 1):
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
            if i == scan:
                capped = True          # ran out of scan before running out of days
        if n > 10:
            print(f"  ... and {n - 10} more")
        print(f"  -> {n}{'+' if capped else ''} item(s) sent in the last {days} days"
              + ("  (hit the scan cap - there may be more)" if capped else ""))
        if n == 0:
            print("     ** NOTHING SENT from this mailbox **"
                  + ("  - consistent with the gate failing" if match is None else
                     "  - but the gate PASSES, so the cause is upstream:"
                     " has a batch actually been built and run?"))
    except Exception as e:
        print(f"  (could not read Sent Items: {type(e).__name__}: {e})")


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
    _report_sent(ns, match, want)

    return 0 if match else 2


if __name__ == "__main__":
    sys.exit(main())
