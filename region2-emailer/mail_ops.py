"""
The DHL mailbox through Outlook, for a Claude session - run by agent.py on the home PC.

    echo {"action": "search", "args": {...}} | python mail_ops.py

Reads one command as JSON on stdin and prints one line

    MAIL_RESULT {"ok": true|false, "result": {...}}

at the end (agent.py takes the verdict from that line, never from prose).

What it does, all in the DHL account's own mailbox (DHL_SMTP's DeliveryStore,
NOT the profile's default store - see check_sending.py for why that matters):

    folders                                 the mailbox's folders, with counts
    search  {query, folder, days, limit, sender, unread}
                                            newest first; query matches subject,
                                            sender and body
    read    {id, thread}                    one message in full (text body), or
                                            its whole conversation with thread
    draft   {to, cc, bcc, subject, body, reply_to, reply_all, forward}
                                            saved in Drafts, from the DHL account
    send    the same as draft - the cloud then puts it on the dashboard for his
            OK. This script never sends on "send".
    send_draft {id, fingerprint}            ONLY ever queued by the cloud after he
                                            approved on the dashboard: sends the
                                            draft, if it is still exactly what he
                                            saw (same fingerprint)

Nothing here is a background job: it is the user's own request, so it does not
take outlook_gate's background slot (a skipped send is a silent failure).
"""
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timedelta

DHL_SMTP = "delali.opoku@dhl.com"
MAX_LIMIT = 100
MAX_SCAN = 3000
MAX_BODY = 60_000
MAX_THREAD = 25

FOLDER_IDS = {"inbox": 6, "sent": 5, "sent items": 5, "drafts": 16, "deleted": 3,
              "deleted items": 3, "outbox": 4, "junk": 23, "junk email": 23}


class Fail(Exception):
    pass


# ---- pure helpers (tested without Outlook) ----------------------------------

def addr_list(v):
    """'a@x; b@y' / ['a@x', 'b@y'] -> 'a@x; b@y', blanks dropped."""
    if isinstance(v, (list, tuple)):
        parts = [str(x) for x in v]
    else:
        parts = re.split(r"[;,]", str(v or ""))
    return "; ".join(p.strip() for p in parts if p.strip())


def text_to_html(text):
    """Plain text as the start of an HTML body: escaped, line breaks kept."""
    esc = html.escape(str(text or ""))
    paras = esc.replace("\r\n", "\n").split("\n")
    return ('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
            + "<br>\n".join(paras) + "</div>")


def insert_top(existing_html, block):
    """Put `block` at the top of a reply's HTML body, above the quoted message."""
    m = re.search(r"<body[^>]*>", existing_html or "", re.I)
    if not m:
        return block + "<br>" + (existing_html or "")
    i = m.end()
    return existing_html[:i] + block + "<br>" + existing_html[i:]


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def fingerprint(to, cc, bcc, subject, body, attachments=()):
    """What the dashboard showed him. A draft changed after that no longer matches."""
    h = hashlib.sha256()
    for part in (_norm(to), _norm(cc), _norm(bcc), _norm(subject), _norm(body),
                 "|".join(sorted(_norm(a) for a in attachments))):
        h.update(part.encode("utf-8", "replace") + b"\x00")
    return h.hexdigest()


def dasl_like(text):
    q = str(text).replace("'", "''").replace("%", "")
    fields = ("urn:schemas:httpmail:subject", "urn:schemas:httpmail:fromname",
              "urn:schemas:httpmail:fromemail", "urn:schemas:httpmail:textdescription")
    return "@SQL=" + " OR ".join(f'"{f}" LIKE \'%{q}%\'' for f in fields)


def clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


# ---- Outlook -----------------------------------------------------------------

def _outlook():
    import win32com.client
    app = win32com.client.Dispatch("Outlook.Application")
    ns = app.GetNamespace("MAPI")
    acct = None
    for a in ns.Accounts:
        if str(a.SmtpAddress).lower() == DHL_SMTP:
            acct = a
            break
    if acct is None:
        raise Fail(f"The DHL account ({DHL_SMTP}) is not in this Outlook profile.")
    return app, ns, acct, acct.DeliveryStore


def _folder(store, name):
    name = str(name or "Inbox").strip()
    fid = FOLDER_IDS.get(name.lower())
    if fid is not None:
        return store.GetDefaultFolder(fid)
    # a path like "Inbox/Hauliers" or a top-level folder by name
    parts = [p for p in re.split(r"[/\\]", name) if p]
    cur = store.GetRootFolder()
    for i, part in enumerate(parts):
        nxt = None
        if i == 0 and part.lower() in FOLDER_IDS:
            nxt = store.GetDefaultFolder(FOLDER_IDS[part.lower()])
        else:
            for f in cur.Folders:
                if str(f.Name).lower() == part.lower():
                    nxt = f
                    break
        if nxt is None:
            raise Fail(f"No folder called '{name}' in the DHL mailbox (try: folders).")
        cur = nxt
    return cur


def _when(t):
    try:
        return datetime(t.year, t.month, t.day, t.hour, t.minute, t.second).isoformat(timespec="minutes")
    except Exception:
        return ""


def _sender(it):
    try:
        if it.SenderEmailType == "EX":
            ex = it.Sender.GetExchangeUser()
            if ex is not None:
                return str(ex.PrimarySmtpAddress)
    except Exception:
        pass
    try:
        return str(it.SenderEmailAddress or "")
    except Exception:
        return ""


def _attachments(it):
    out = []
    try:
        for i in range(1, it.Attachments.Count + 1):
            out.append(str(it.Attachments.Item(i).FileName))
    except Exception:
        pass
    return out


def _summary(it, folder_name=""):
    body = ""
    try:
        body = str(it.Body or "")
    except Exception:
        pass
    when = getattr(it, "ReceivedTime", None) or getattr(it, "SentOn", None)
    return {
        "id": str(it.EntryID),
        "folder": folder_name,
        "when": _when(when) if when else "",
        "from": str(getattr(it, "SenderName", "") or ""),
        "from_email": _sender(it),
        "to": str(getattr(it, "To", "") or ""),
        "subject": str(getattr(it, "Subject", "") or ""),
        "preview": re.sub(r"\s+", " ", body)[:240],
        "unread": bool(getattr(it, "UnRead", False)),
        "attachments": len(_attachments(it)),
    }


def _full(it):
    s = _summary(it)
    try:
        body = str(it.Body or "")
    except Exception:
        body = ""
    s.update(cc=str(getattr(it, "CC", "") or ""), body=body[:MAX_BODY], truncated=len(body) > MAX_BODY,
             attachment_names=_attachments(it))
    try:
        s["conversation"] = str(it.ConversationTopic or "")
    except Exception:
        pass
    s.pop("preview", None)
    return s


def do_folders(store, args):
    out = []

    def walk(f, path, depth):
        try:
            out.append({"path": path, "items": int(f.Items.Count), "unread": int(f.UnReadItemCount)})
        except Exception:
            out.append({"path": path})
        if depth < 3:
            for sub in f.Folders:
                walk(sub, path + "/" + str(sub.Name), depth + 1)
    root = store.GetRootFolder()
    for f in root.Folders:
        walk(f, str(f.Name), 1)
    return {"folders": out[:400]}


def do_search(store, args):
    folder = _folder(store, args.get("folder") or "Inbox")
    days = clamp(args.get("days"), 1, 365, 14)
    limit = clamp(args.get("limit"), 1, MAX_LIMIT, 20)
    since = datetime.now() - timedelta(days=days)
    query = str(args.get("query") or "").strip()
    sender = str(args.get("sender") or "").strip().lower()
    unread = bool(args.get("unread"))
    items = folder.Items
    if query:
        items = items.Restrict(dasl_like(query))
    date_field = "[SentOn]" if folder.DefaultItemType == 0 and str(folder.Name).lower().startswith("sent") else "[ReceivedTime]"
    try:
        items.Sort(date_field, True)
    except Exception:
        pass
    found, scanned = [], 0
    it = items.GetFirst()
    while it is not None and scanned < MAX_SCAN and len(found) < limit:
        scanned += 1
        try:
            if getattr(it, "Class", 0) == 43:        # 43 = MailItem
                t = getattr(it, "ReceivedTime", None) or getattr(it, "SentOn", None)
                if t is not None and datetime(t.year, t.month, t.day, t.hour, t.minute) < since:
                    break                            # sorted newest first: the rest are older
                if unread and not it.UnRead:
                    pass
                elif sender and sender not in (str(it.SenderName or "").lower() + " " + _sender(it).lower()):
                    pass
                else:
                    found.append(_summary(it, str(folder.Name)))
        except Exception:
            pass
        it = items.GetNext()
    return {"folder": str(folder.FolderPath), "days": days, "count": len(found), "messages": found,
            "more": len(found) >= limit}


def _item(ns, store, entry_id):
    if not entry_id:
        raise Fail("Which message? Give its id (from search).")
    try:
        return ns.GetItemFromID(str(entry_id), store.StoreID)
    except Exception:
        raise Fail("No message with that id in the DHL mailbox (moved or deleted?).")


def do_read(ns, store, args):
    it = _item(ns, store, args.get("id"))
    if not args.get("thread"):
        return {"message": _full(it)}
    msgs = []
    try:
        conv = it.GetConversation()
        if conv is not None:
            def walk(items):
                for i in range(1, items.Count + 1):
                    x = items.Item(i)
                    if getattr(x, "Class", 0) == 43 and len(msgs) < MAX_THREAD:
                        msgs.append(_full(x))
                    walk(conv.GetChildren(x))
            walk(conv.GetRootItems())
    except Exception:
        msgs = []
    if not msgs:
        msgs = [_full(it)]
    msgs.sort(key=lambda m: m.get("when", ""))
    return {"thread": msgs, "count": len(msgs)}


def _use_account(m, acct):
    try:
        m._oleobj_.Invoke(64209, 0, 8, 0, acct)     # SendUsingAccount, reliably
    except Exception:
        try:
            m.SendUsingAccount = acct
        except Exception:
            pass


def _describe(m, why=""):
    att = _attachments(m)
    body = str(m.Body or "")
    return {"id": str(m.EntryID), "to": str(m.To or ""), "cc": str(m.CC or ""), "bcc": str(m.BCC or ""),
            "subject": str(m.Subject or ""), "body": body[:MAX_BODY], "attachments": att,
            "fingerprint": fingerprint(m.To, m.CC, m.BCC, m.Subject, body, att), "why": why}


def do_draft(app, ns, acct, store, args):
    to, cc, bcc = addr_list(args.get("to")), addr_list(args.get("cc")), addr_list(args.get("bcc"))
    body = str(args.get("body") or "")
    subject = args.get("subject")
    reply_to, fwd = args.get("reply_to"), args.get("forward")
    if reply_to and fwd:
        raise Fail("A draft is a reply or a forward, not both.")
    if reply_to or fwd:
        orig = _item(ns, store, reply_to or fwd)
        m = orig.Forward() if fwd else (orig.ReplyAll() if args.get("reply_all") else orig.Reply())
        if to:
            m.To = to if fwd or args.get("replace_to") else addr_list([m.To, to])
        if cc:
            m.CC = addr_list([m.CC, cc])
        if bcc:
            m.BCC = bcc
        if subject:
            m.Subject = str(subject)
        m.HTMLBody = insert_top(m.HTMLBody, text_to_html(body))
    else:
        if not to:
            raise Fail("A new email needs a 'to'.")
        if not subject:
            raise Fail("A new email needs a subject.")
        m = app.CreateItem(0)
        m.To, m.CC, m.BCC, m.Subject = to, cc, bcc, str(subject)
        m.HTMLBody = text_to_html(body)
    if not str(m.To or "").strip():
        raise Fail("The draft has nobody in 'to'.")
    _use_account(m, acct)
    m.Save()
    drafts = store.GetDefaultFolder(16)
    try:
        if str(m.Parent.EntryID) != str(drafts.EntryID):
            m = m.Move(drafts)
    except Exception:
        pass
    m = ns.GetItemFromID(str(m.EntryID), store.StoreID)    # read it back as saved
    out = _describe(m, str(args.get("why") or ""))
    out["reply_to"] = str(reply_to or fwd or "")
    return out


def do_send_draft(ns, acct, store, args):
    m = _item(ns, store, args.get("id"))
    if getattr(m, "Class", 0) != 43 or getattr(m, "Sent", False):
        raise Fail("That is not an unsent draft any more - nothing sent.")
    now = _describe(m)
    if not args.get("fingerprint") or now["fingerprint"] != args.get("fingerprint"):
        raise Fail("The draft changed after you approved it - nothing sent. It is still in Drafts.")
    _use_account(m, acct)
    m.Send()
    # nothing after Send() may touch the item (24/07): the verdict is the call returning
    return {"said": f"sent to {now['to']}", "to": now["to"], "subject": now["subject"]}


def run(cmd):
    action = cmd.get("action")
    args = cmd.get("args") if isinstance(cmd.get("args"), dict) else {}
    app, ns, acct, store = _outlook()
    if action == "folders":
        return do_folders(store, args)
    if action == "search":
        return do_search(store, args)
    if action == "read":
        return do_read(ns, store, args)
    if action in ("draft", "send"):
        return do_draft(app, ns, acct, store, args)
    if action == "send_draft":
        return do_send_draft(ns, acct, store, args)
    raise Fail(f"Unknown mail action '{action}'.")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        cmd = json.loads(sys.stdin.read() or "{}")
        res, ok = run(cmd), True
    except Fail as e:
        res, ok = {"error": str(e)}, False
    except Exception as e:
        res, ok = {"error": f"Outlook: {type(e).__name__}: {e}"}, False
    print("MAIL_RESULT " + json.dumps({"ok": ok, "result": res}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
