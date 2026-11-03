"""
The DHL work mailbox (Outlook on the home PC), from a Claude session.

    python outlook_remote.py status                       channel on? home PC answering? sends waiting
    python outlook_remote.py folders
    python outlook_remote.py search "MAN-1234" [--folder Inbox] [--days 14] [--limit 20]
                                                [--from someone] [--unread]
    python outlook_remote.py read ID [--thread]           one message in full, or its whole conversation
    python outlook_remote.py draft --to a@x --subject S --body "..." [--cc] [--bcc]
                                                [--reply-to ID [--reply-all]] [--forward ID]
                                                [--body-file F]
                                                saved in Outlook Drafts - nothing goes out
    python outlook_remote.py send  (same options as draft) [--why "one line for Delali"] [--wait 120]
                                                drafts it AND asks for Delali's OK on the dashboard;
                                                it goes only when he presses Send there
    python outlook_remote.py pending                      the sends waiting for (or past) his OK

IDs are the "id" from search / read. Address and key: desk_client.py (cloud.json
on the home PC; CTMS_DESK_URL/KEY or the Railway CLI in a cloud session).

Exit codes: 0 done, 2 refused or failed, 3 waiting for his OK (send), 4 the
home PC did not answer, 5 the channel is switched off, 1 anything else.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desk_client  # noqa: E402

BASE, KEY = "", ""


class Stop(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def http(method, path, body=None, timeout=40):
    host = (urlsplit(BASE).hostname or "").lower()
    handlers = [urllib.request.ProxyHandler({})] if host in ("127.0.0.1", "localhost") else []
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Auth": KEY, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Stop(f"Could not reach the dashboard at {BASE}: {getattr(e, 'reason', e)}", 4)


def _check(code, body):
    if code == 401:
        raise Stop("The dashboard did not accept the home PC's key.")
    if code == 404 and body.get("error") == "not found":
        raise Stop("This dashboard has no mail channel yet - it needs redeploying.")
    if code == 409:
        raise Stop(body.get("error") or "The mail channel is switched off on the dashboard.", 5)
    if code != 200:
        raise Stop(body.get("error") or f"The dashboard answered HTTP {code}.")
    return body


def ask(action, args, patience=150):
    """Queue a mail command and wait for the home PC's answer."""
    body = _check(*http("POST", "/api/mail/command", {"action": action, "args": args}))
    cid = body["id"]
    if not body.get("home_pc"):
        print("(the home PC has not checked in for mail lately - waiting anyway)", file=sys.stderr)
    end = time.time() + patience
    while time.time() < end:
        code, r = http("GET", f"/api/mail/result?id={cid}&wait=20", timeout=35)
        r = _check(code, r)
        if r.get("done"):
            if not r.get("ok"):
                raise Stop((r.get("result") or {}).get("error") or "The home PC said no.", 2)
            return r.get("result") or {}
    raise Stop(f"No answer from the home PC within {patience}s (command {cid}).", 4)


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _draft_args(a):
    body = a.body or ""
    if a.body_file:
        with open(a.body_file, encoding="utf-8") as f:
            body = f.read()
    args = {"to": a.to or "", "cc": a.cc or "", "bcc": a.bcc or "", "subject": a.subject or "",
            "body": body}
    if a.reply_to:
        args["reply_to"] = a.reply_to
        args["reply_all"] = bool(a.reply_all)
    if a.forward:
        args["forward"] = a.forward
    if getattr(a, "why", None):
        args["why"] = a.why
    return args


def cmd_status(_a):
    s = _check(*http("GET", "/api/mail/status"))
    print(f"mail channel: {'on' if s.get('on') else 'OFF (switched off on the dashboard)'}")
    ago = s.get("seen_ago")
    print(f"home PC: {'answering' if s.get('home_pc') else 'not answering'}"
          + (f" (last asked {ago}s ago)" if ago is not None else " (never seen since the last deploy)"))
    for p in s.get("pending") or []:
        print(f"  #{p['id']} {p['state']:8} {p.get('at', '')}  to {p.get('to', '')}: {p.get('subject', '')}"
              + (f"  - {p['said']}" if p.get("said") else ""))
    return 0


def cmd_pending(_a):
    out(_check(*http("GET", "/api/mail/pending")))
    return 0


def cmd_send(a):
    r = ask("send", _draft_args(a))
    pid = r.get("approval")
    print(f"Drafted in Outlook and waiting for Delali's OK on the dashboard (approval #{pid}):")
    print(f"  to {r.get('to')}" + (f"  cc {r['cc']}" if r.get("cc") else "") + f"\n  subject: {r.get('subject')}")
    if not pid or not a.wait:
        return 3
    end = time.time() + a.wait
    while time.time() < end:
        s = _check(*http("GET", "/api/mail/pending"))
        p = next((x for x in s.get("pending") or [] if x["id"] == pid), None)
        if p and p["state"] in ("sent", "refused", "failed", "expired"):
            print(f"{p['state']}" + (f": {p['said']}" if p.get("said") else ""))
            return 0 if p["state"] == "sent" else 2
        time.sleep(5)
    print("Still waiting for his OK.")
    return 3


def run(a):
    if a.cmd == "status":
        return cmd_status(a)
    if a.cmd == "pending":
        return cmd_pending(a)
    if a.cmd == "folders":
        out(ask("folders", {}))
        return 0
    if a.cmd == "search":
        out(ask("search", {"query": a.query or "", "folder": a.folder, "days": a.days, "limit": a.limit,
                           "sender": a.sender or "", "unread": a.unread}))
        return 0
    if a.cmd == "read":
        out(ask("read", {"id": a.id, "thread": a.thread}))
        return 0
    if a.cmd == "draft":
        r = ask("draft", _draft_args(a))
        r.pop("fingerprint", None)
        out(r)
        return 0
    if a.cmd == "send":
        return cmd_send(a)
    raise Stop(f"unknown command {a.cmd}")


def main(argv=None):
    global BASE, KEY
    ap = argparse.ArgumentParser(description="The DHL mailbox through the home PC's Outlook.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("pending")
    sub.add_parser("folders")
    p = sub.add_parser("search")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--folder", default="Inbox")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--from", dest="sender")
    p.add_argument("--unread", action="store_true")
    p = sub.add_parser("read")
    p.add_argument("id")
    p.add_argument("--thread", action="store_true")
    for name in ("draft", "send"):
        p = sub.add_parser(name)
        p.add_argument("--to")
        p.add_argument("--cc")
        p.add_argument("--bcc")
        p.add_argument("--subject")
        p.add_argument("--body")
        p.add_argument("--body-file")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--reply-to")
        g.add_argument("--forward")
        p.add_argument("--reply-all", action="store_true")
        if name == "send":
            p.add_argument("--why", help="one line shown to Delali with the approval")
            p.add_argument("--wait", type=int, default=0, help="seconds to wait for his decision")
    a = ap.parse_args(argv)
    try:
        BASE, KEY = desk_client.desk()
        return run(a)
    except desk_client.NoDesk as e:
        print(str(e))
        return 1
    except Stop as e:
        print(str(e))
        return e.code


if __name__ == "__main__":
    sys.exit(main())
