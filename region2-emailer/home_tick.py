"""Periodic home-PC maintenance (the COM side of self-update + handover).

Run every ~60s by the supervisor (which is single-instance, so this runs once):
  1. apply any "R2 UPDATE" emails to the site store / team / settings
  2. while a handover is active, forward tracked-order replies to the cover
     person; auto-end on the return date.

Pure-python rules live in modules/; this file is only the Outlook adapter.
"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from modules import site_matching, profiles, handover, self_update

SITES_PATH = os.path.join(HERE, "_sites.json")
HANDOVER_PATH = os.path.join(HERE, "_handover.json")
TEAM_PATH = os.path.join(HERE, "config", "team.json")
SETTINGS_PATH = os.path.join(HERE, "_settings.json")
SEEN_PATH = os.path.join(HERE, "_updates_seen.json")


def _team():
    try:
        return profiles.load_team(TEAM_PATH)
    except Exception:
        return {"members": [], "me": ""}


def _post_local(state, detail):
    """Best-effort toast to the LOCAL control plane (no auth on 127.0.0.1)."""
    try:
        import urllib.request
        body = json.dumps({"state": state, "detail": detail, "output": "", "email": None}).encode()
        req = urllib.request.Request("http://127.0.0.1:8787/api/status", data=body,
                                     headers={"Content-Type": "application/json", "X-Auth": ""},
                                     method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _sender_smtp(it):
    s = getattr(it, "SenderEmailAddress", "") or ""
    if "@" in s:
        return s
    try:                                    # internal Exchange DN -> real SMTP
        return it.Sender.GetExchangeUser().PrimarySmtpAddress or s
    except Exception:
        return s


def check_updates(ns):
    team = _team()
    store = site_matching.SiteStore(SITES_PATH)
    prefix = team.get("update_email", {}).get("subject_prefix", "R2 UPDATE")
    items = ns.GetDefaultFolder(6).Items          # 6 = inbox
    try:
        found = items.Restrict("@SQL=\"urn:schemas:httpmail:subject\" ci_phrasematch '%s'" % prefix)
    except Exception:
        try:
            found = items.Restrict("[Subject] >= '%s' AND [Subject] <= '%sz'" % (prefix, prefix))
        except Exception:
            found = items
    msgs = []
    for i in range(1, min(getattr(found, "Count", 0), 25) + 1):
        try:
            it = found.Item(i)
            msgs.append({"id": it.EntryID, "sender": _sender_smtp(it),
                         "subject": it.Subject or "", "body": it.Body or ""})
        except Exception:
            continue
    applied = self_update.process_messages(msgs, store, TEAM_PATH, SETTINGS_PATH, SEEN_PATH)
    if applied:
        _post_local("done", "Self-update applied: " + "; ".join(applied))
    return applied


def do_handover(ns):
    result = handover.tick(HANDOVER_PATH)
    if result == "ended":
        _post_local("done", "Handover finished - welcome back! Forwarding stopped.")
        return
    if result != "active":
        return
    state = handover.load(HANDOVER_PATH)
    if not state.get("forward"):
        return
    me = _team().get("me", "")
    try:
        recs = json.load(open(os.path.join(HERE, "tracker.json"), encoding="utf-8")).get("records", [])
    except Exception:
        recs = []
    orders = {"".join(ch for ch in str(o) if ch.isdigit())
              for r in recs for o in r.get("orders", [])}
    orders.discard("")
    if not orders:
        return
    inbox = ns.GetDefaultFolder(6).Items
    try:
        inbox.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    incoming = []
    for i in range(1, min(getattr(inbox, "Count", 0), 40) + 1):   # only look at recent inbox
        try:
            it = inbox.Item(i)
            blob = str(it.Subject or "") + " " + str(getattr(it, "Body", "") or "")[:4000]
            if any(o in blob for o in orders):       # a reply about a tracked order
                incoming.append({"id": it.EntryID, "sender": getattr(it, "SenderEmailAddress", "") or ""})
        except Exception:
            continue
    forwarded = []
    for mid in handover.plan_forwards(state, incoming, me=me):
        try:
            fwd = ns.GetItemFromID(mid).Forward()
            fwd.To = state["cover_email"]
            fwd.Send()
            forwarded.append(mid)
        except Exception:
            continue
    if forwarded:
        handover.mark_forwarded(HANDOVER_PATH, forwarded)
        try:
            ns.SendAndReceive(False)
        except Exception:
            pass


def main():
    try:
        import win32com.client
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        return
    try:
        check_updates(ns)
    except Exception:
        pass
    try:
        do_handover(ns)
    except Exception:
        pass


if __name__ == "__main__":
    main()
