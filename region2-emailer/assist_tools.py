"""The background Claude's one tool (his 24/11 "Deal with it"). `inbox_assist.py work` starts the Claude Code command
line with Bash held to `python assist_tools.py ...` and nothing else, and R2_ASSIST_JOB naming the one email it deals
with. Every command here works on that email, keeps the job's log for his desk, and stops once he has marked the email
dealt with. What may go without him goes: a reply on the email's own thread, filing it, a CTMS order update. What needs
his yes - money, deletes and cancelling, anyone new to email, any other CTMS change - is HELD (drafted, or written
down) and his desk shows it with Yes / No.

    python assist_tools.py help
    python assist_tools.py email                    the email in full: who, when, its words and the trail
    python assist_tools.py thread                   its whole conversation, oldest first
    python assist_tools.py search TEXT [--days N] [--folder F]
                                                    the mailbox: Inbox, Region 2 Completed and Sent (or --folder F)
    python assist_tools.py read ID                  one message a search found, in full
    python assist_tools.py order REF                what the toolkit knows of an order: tracker, booked, Book's journal
    python assist_tools.py rules [TOPIC]            his rule book: the index, or one topic in full
    python assist_tools.py ctms ROUTE [ARGS...]     CTMS through ctms_routes.py - reads and dry runs only
                                                    (`ctms list` for the routes)
    python assist_tools.py ctms-commit ROUTE [ARGS...]
                                                    an order update you may make: order-update, order-note,
                                                    order-item, order-deltype, order-services. Dry-run it first
    python assist_tools.py reply --text "..."       reply to all on the email's thread (never DHL Road): checked,
                                                    sent, the email filed. A price in it, or a long one: held
    python assist_tools.py draft --to ADDR [--cc ADDR] --subject "..." --text "..."
                                                    a new email: drafted, sent only on his yes
    python assist_tools.py forward --to ADDR --text "..."
                                                    the email forwarded with a note: drafted, sent only on his yes
    python assist_tools.py file [FOLDER]            file the email (Regions/Region 2/Completed unless told)
    python assist_tools.py ask --what "..." [ROUTE ARGS...]
                                                    hold something for his yes: a CTMS change (run with --commit on
                                                    his yes), or with no route something only he can do
    python assist_tools.py say "..."                a line on his desk saying what you're doing

R2_ASSIST_DRY=1 (a trial run): nothing is sent, filed or committed - each is written down as what it would have done.
Exit codes: 0 done, 2 refused.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import inbox_assist as A  # noqa: E402

MAX_REPLY = 1200                                          # a reply longer than this waits for his yes
# money in a reply waits for his yes (his rule: money always asks)
MONEY = re.compile(r"£|\bgbp\b|\bpounds?\b|\bprices?\b|\bpriced\b|\bcosts?\b|\bcharges?\b|\brates?\b|\bquotes?\b"
                   r"|\bquoted\b|\binvoices?\b|\bpayments?\b", re.I)
ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
LIVE = ("open",)                                          # the email still his to deal with: things may go out
WORKING = ("open", "answered")                            # replied to already: CTMS may still be put right
READING = ("open", "answered", "filed")                   # anything that only reads or writes the job down
SKIP_FIELDS = re.compile(r"html|body|entryid|_eid$|^eid$|^orig_", re.I)


class Stop(Exception):
    """Refused: said to Claude, nothing done."""


def _dry():
    return bool(os.environ.get("R2_ASSIST_DRY"))


def _sid():
    sid = str(os.environ.get("R2_ASSIST_JOB") or "")
    if not re.fullmatch(r"[0-9a-f]{12}", sid):
        raise Stop("No job: this tool only works for the background Claude dealing with one of his emails.")
    return sid


def _check(it, states):
    if it is None:
        raise Stop("That email is no longer on his list - stop here.")
    if (it.get("job") or {}).get("state") != "working":
        raise Stop("This job isn't running any more - stop here.")
    if it.get("state") not in states:
        said = {"dealt": "He has marked it dealt with", "gone": "It has left his Inbox (he filed it)",
                "answered": "It's answered already", "filed": "It's filed already"}.get(it.get("state"), "It's closed")
        raise Stop(f"{said} - stop here.")
    return it


def _peek(states=READING):
    """The job's email as the store has it now (a read: no lock)."""
    return _check(A.load()["items"].get(_sid()), states)


def _change(fn, states=READING):
    """fn(d, item, job) under the store's lock, saved; the desk told."""
    h = A._lock(wait=60)
    try:
        d = A.load()
        it = _check(d["items"].get(_sid()), states)
        out = fn(d, it, it["job"])
        A.save(d)
        return out
    finally:
        A._unlock(h)
        A._touch(A.PUSH_DUE)


def _stamp():
    return datetime.now().strftime("%H:%M")


def _note(job, line, key="log", keep=40):
    job.setdefault(key, []).append(f"{_stamp()} {line}"[:300])
    del job[key][:-keep]


def log(line, did=False):
    def go(d, it, job):
        _note(job, line)
        if did:
            _note(job, line, key="did", keep=20)
    _change(go)


def hold(ask):
    """Something for his yes, written on the job: his desk shows it with Yes / No."""
    def go(d, it, job):
        ask.update(state="open", at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        job.setdefault("asks", []).append(ask)
        _note(job, "held for his yes: " + ask.get("what", ""))
        return len(job["asks"]) - 1
    return _change(go)


def _outlook():
    import mail_ops
    return mail_ops._outlook()


def _show(m, limit):
    names = m.get("attachment_names") or []
    body = str(m.get("body") or m.get("preview") or "").replace("\r\n", "\n")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return "\n".join([
        f"From: {m.get('from')} <{m.get('from_email')}>",
        f"To: {m.get('to') or ''}",
        f"Cc: {m.get('cc') or ''}",
        f"When: {m.get('when')}",
        f"Subject: {m.get('subject')}",
        f"Attachments: {', '.join(names) if names else (m.get('attachments') or 'none')}",
        "",
        body[:limit] + ("\n[... cut short]" if len(body) > limit else ""),
    ])


# ---------- reading ----------
def cmd_email(a):
    it = _peek()
    import mail_ops
    with A._outlook_turn():
        app, ns, acct, store = _outlook()
        m = mail_ops._full(ns.GetItemFromID(it["eid"], store.StoreID))
    log("read the email")
    print(_show(m, 9000))


def cmd_thread(a):
    it = _peek()
    import mail_ops
    with A._outlook_turn():
        app, ns, acct, store = _outlook()
        res = mail_ops.do_read(ns, store, {"id": it["eid"], "thread": True})
    log(f"read the thread ({res.get('count')} emails)")
    room = 16000
    for m in res.get("thread") or []:
        text = _show(m, min(2500, max(300, room)))
        room -= len(text)
        print(text + "\n" + "=" * 60)
        if room <= 0:
            print("[... the rest of the thread cut short]")
            break


def cmd_search(a):
    _peek()
    import mail_ops
    folders = [a.folder] if a.folder else ["Inbox", "Inbox/Regions/Region 2/Completed", "Sent Items"]
    out = []
    with A._outlook_turn():
        app, ns, acct, store = _outlook()
        for f in folders:
            try:
                res = mail_ops.do_search(store, {"folder": f, "query": a.text, "days": a.days, "limit": 10})
            except Exception as e:
                out.append(f"{f}: {e}")
                continue
            for m in res.get("messages") or []:
                out.append(f"{m['when']} | {f} | {m['from']} <{m['from_email']}> | {m['subject']}\n"
                           f"    {str(m.get('preview') or '')[:220]}\n    id {m['id']}")
    log(f"searched the mailbox for {a.text[:60]!r}")
    print("\n".join(out) or "Nothing found.")


def cmd_read(a):
    _peek()
    import mail_ops
    with A._outlook_turn():
        app, ns, acct, store = _outlook()
        m = mail_ops._full(mail_ops._item(ns, store, a.id))
    log(f"read {str(m.get('subject'))[:60]!r}")
    print(_show(m, 6000))


def _record_lines(rec):
    keep = {k: v for k, v in rec.items() if v not in (None, "", [], {}) and not SKIP_FIELDS.search(k)}
    return json.dumps(keep, ensure_ascii=False, indent=1, default=str)[:3000]


def cmd_order(a):
    _peek()
    base = re.sub(r"[-_].*$", "", a.ref.strip())
    if not re.fullmatch(r"[A-Za-z0-9/]{4,30}", base):
        raise Stop("That isn't an order reference.")
    out = []
    records = A._json(os.path.join(HERE, "tracker.json"), {}).get("records") or []
    for r in records:
        if base in {re.sub(r"[-_].*$", "", str(o)) for o in r.get("orders") or ()}:
            out += ["On his tracker:", _record_lines(r)]
    booked = set(map(str, A._json(os.path.join(HERE, "_booked_drops.json"), []) or []))
    out.append("Booked in CTMS (the toolkit's list): " + ("yes" if base in booked or a.ref in booked else "not that it knows"))
    jobs = (A._json(os.path.join(HERE, "_book_journal.json"), {}) or {}).get("jobs") or {}
    for k, e in jobs.items():
        if any(base == re.sub(r"[-_].*$", "", str(o)) for o in e.get("orders") or ()):
            out += [f"Book's journal {k}:", json.dumps({x: e.get(x) for x in (
                "state", "carrier", "haulier", "trailer", "date", "trips", "ctms_said", "updated")},
                ensure_ascii=False, default=str)[:1500]]
    if len(out) == 1:
        out.insert(0, "Not on his tracker or in Book's journal.")
    log(f"looked up {a.ref[:30]}")
    print("\n".join(out))


def rules_dir():
    cfg = A._json(A.CFG, {})
    # Claude Code keeps a project's memory under ~/.claude/projects/<the project folder, : \ / as ->
    project = re.sub(r"[:\\/]", "-", os.path.dirname(HERE))
    return cfg.get("rules_dir") or os.path.join(os.path.expanduser("~"), ".claude", "projects", project, "memory")


def cmd_rules(a):
    _peek()
    folder = rules_dir()
    if not a.topic:
        path = os.path.join(folder, "MEMORY.md")
    elif re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", a.topic):
        path = os.path.join(folder, a.topic + ".md")
    else:
        raise Stop("A topic is one of the names in the index, e.g. booking-checklist.")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        raise Stop(f"No rule book topic {a.topic!r}." if a.topic else "His rule book isn't on this PC.")
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)          # the file's own header, not his rules
    log("read his rules" + (f": {a.topic}" if a.topic else ""))
    print(text[:12000])


# ---------- CTMS ----------
def _route(route):
    route = [str(x) for x in route or ()]
    if not route:
        raise Stop("Which route? `python assist_tools.py ctms list` lists them.")
    if route[0] in A.CTMS_NEVER:
        raise Stop("Raw clicks aren't yours to make - use a named route.")
    if "--commit" in route:
        raise Stop("Not with --commit here: ctms-commit for an order update, or ask for anything else.")
    return route


def _run_route(route, commit):
    try:
        import outlook_gate
        if outlook_gate._toolkit_off():
            raise Stop("The toolkit is switched off - nothing runs.")
    except ImportError:
        pass
    p = subprocess.run([sys.executable, os.path.join(HERE, "ctms_routes.py")] + route + (["--commit"] if commit else []),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, cwd=HERE,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    return str(p.stdout or "") + (("\n" + str(p.stderr)) if p.stderr else "")


def cmd_ctms(a):
    _peek()
    route = _route([a.route] + a.args)
    log("CTMS " + " ".join(route)[:120])
    out = _run_route(route, commit=False)
    lines = out.strip().splitlines()
    print("\n".join(lines[-150:]))


def cmd_ctms_commit(a):
    _peek(WORKING)
    route = _route([a.route] + a.args)
    if route[0] not in A.CTMS_MAY_COMMIT:
        raise Stop(f"{route[0]} with --commit needs his yes: `python assist_tools.py ask --what \"...\" "
                   f"{' '.join(route)}`.")
    if _dry():
        log("would commit in CTMS: " + " ".join(route)[:160], did=True)
        print("Trial run: not committed (it would have run with --commit).")
        return
    log("CTMS commit " + " ".join(route)[:120])
    out = _run_route(route, commit=True)
    ok, said = A._route_result(out)
    log(f"CTMS {route[0]} {' '.join(route[1:])[:60]}: " + ("done" if ok else "stopped") + f" - {said[:120]}", did=True)
    print("\n".join(out.strip().splitlines()[-80:]))


# ---------- what goes out ----------
def _words(text):
    """What Claude typed for an email: a literal backslash-n (a shell's way of writing a new line) becomes one; never
    an em dash."""
    return A.EM_DASH.sub(" - ", str(text or "").replace("\\n", "\n")).strip()


def _people(text):
    got = [x.lower() for x in ADDRESS.findall(str(text or ""))]
    if not got:
        raise Stop("Give an email address.")
    if any("dhlroad" in x for x in got):
        raise Stop("DHL Road is never written to from here.")
    return got


def _my_names():
    """His own names, as the inbox watch knows them (the home-only config), else from the DHL address."""
    try:
        import inbox_watch as iw
        import mail_ops
        names = [str(n).lower() for n in (iw._json(iw.CFG, {}) or {}).get("my_names", []) if n]
        return names or [mail_ops.DHL_SMTP.split("@")[0].replace(".", " ").lower()]
    except Exception:
        return []


def cmd_reply(a):
    it = _peek(LIVE)
    if any(n and n in str(it.get("from") or "").lower() for n in _my_names()):
        # 24/11 trial: his own forward of a site's question - a reply-all would only have gone back to him
        raise Stop("It's his own email (a forward, or a note to himself): a reply to all would only reach him. Write "
                   "to the person it's about with `draft --to ...` - it waits for his yes.")
    body = A.clean_reply(_words(a.text))
    if not body:
        raise Stop("There's no reply text.")
    why_hold = ("it mentions money" if MONEY.search(body) else
                "it's longer than a reply should be" if len(body) > MAX_REPLY else "")
    if _dry():
        log(("would hold for his yes" if why_hold else "would reply to all") + ": " + body.replace("\n", " ")[:160],
            did=True)
        print("Trial run: not sent." + (f" (It would be held: {why_hold}.)" if why_hold else ""))
        return
    import mail_ops
    with A._outlook_turn():
        o, d0, people, bad = A.reply_draft(it, body)
        if bad:
            log("a reply left in his Drafts, not sent: " + "; ".join(bad), did=True)
            print("NOT SENT - it's in his Drafts: " + "; ".join(bad))
            return
        if why_hold:
            n = hold({"kind": "send", "thread": True, "what": f"Send this reply to {', '.join(people)}",
                      "to": ", ".join(people), "text": body, "draft": {"id": d0["id"], "fingerprint": d0["fingerprint"]}})
            print(f"Held for his yes ({why_hold}): it's in his Drafts, and his desk asks him (#{n}).")
            return
        mail_ops.do_send_draft(o[1], o[2], o[3], {"id": d0["id"], "fingerprint": d0["fingerprint"]})

        def sent(d, it2, job):
            now = datetime.now()
            filed = A.file_answered(o, d, it2["id"], now, by="claude", kind="inbox_assist_sent")
            it2.update(state="answered", sent_at=now.strftime("%Y-%m-%d %H:%M"), sent_to=people,
                       sent_text=body[:1500])
            _note(job, f"replied to {', '.join(people)}{filed}: " + body.replace("\n", " ")[:140])
            _note(job, f"replied to {', '.join(people)}: " + body.replace("\n", " ")[:140], key="did", keep=20)
            return filed
        filed = _change(sent, states=LIVE)
    print(f"Sent to {', '.join(people)}{filed}.")


def _new_draft(args, what, extra):
    import mail_ops
    with A._outlook_turn():
        app, ns, acct, store = _outlook()
        d0 = mail_ops.do_draft(app, ns, acct, store, args)
    n = hold(dict({"kind": "send", "what": what, "draft": {"id": d0["id"], "fingerprint": d0["fingerprint"]}}, **extra))
    print(f"Drafted, and held for his yes (#{n}) - it goes only when he says.")


def cmd_draft(a):
    _peek(WORKING)
    to, cc = _people(a.to), (_people(a.cc) if a.cc else [])
    body = _words(a.text)
    if not body or not a.subject:
        raise Stop("A new email needs a subject and words.")
    try:
        import build_drafts
        body += "\n\n" + build_drafts.SIGNATURE.strip()           # a new email gets no signature from Outlook
    except Exception:
        pass
    if _dry():
        log(f"would draft a new email to {', '.join(to)}: {a.subject[:80]}", did=True)
        print("Trial run: not drafted.")
        return
    _new_draft({"to": "; ".join(to), "cc": "; ".join(cc), "subject": a.subject[:200], "body": body},
               f"Send a new email to {', '.join(to + cc)}: {a.subject[:100]}",
               {"to": ", ".join(to + cc), "text": body[:1500]})


def cmd_forward(a):
    it = _peek(WORKING)
    to = _people(a.to)
    body = _words(a.text)
    if _dry():
        log(f"would forward it to {', '.join(to)}", did=True)
        print("Trial run: not drafted.")
        return
    _new_draft({"forward": it["eid"], "to": "; ".join(to), "body": body},
               f"Forward {it.get('subject', 'it')[:80]!r} to {', '.join(to)}", {"to": ", ".join(to), "text": body[:1500]})


def cmd_file(a):
    _peek(LIVE)
    dest = a.folder or A.FOLDERS[0]
    if dest not in A.FOLDERS:
        raise Stop("It's filed to one of: " + ", ".join(A.FOLDERS))
    if _dry():
        log(f"would file it to {dest}", did=True)
        print("Trial run: not filed.")
        return
    with A._outlook_turn():
        app, ns, acct, store = _outlook()

        def go(d, it, job):
            it["dest"] = dest
            A.file_one(ns, store.GetRootFolder(), d, it["id"], datetime.now(), by="claude")
            _note(job, f"filed it to {dest}")
            _note(job, f"filed it to {dest}", key="did", keep=20)
        _change(go, states=LIVE)
    print(f"Filed to {dest}.")


def _short(text, n):
    """Cut at a word, with an ellipsis, when it's longer than n."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= n:
        return text
    cut = text[:n - 1]
    return (cut[:cut.rfind(" ")] if " " in cut[n // 2:] else cut).rstrip(" ,;:-") + "…"


def cmd_ask(a):
    _peek()
    what = _short(A.EM_DASH.sub(" - ", str(a.what or "")), 200)
    if not what:
        raise Stop("Say what it is, in plain words, with --what.")
    if a.route:
        try:
            route = A.held_route(a.route)
        except RuntimeError as e:
            raise Stop(str(e))
        n = hold({"kind": "route", "what": what, "route": route})
        print(f"Held for his yes (#{n}): on Yes it runs `ctms_routes.py {' '.join(route)} --commit`.")
    else:
        n = hold({"kind": "todo", "what": what})
        print(f"On his desk (#{n}) as a thing for him to do.")


def cmd_say(a):
    text = A.EM_DASH.sub(" - ", " ".join(a.text)).strip()[:160]

    def go(d, it, job):
        job["now"] = text
        _note(job, text)
    _change(go)
    print("Shown on his desk.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="assist_tools.py", add_help=False)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("help")
    sub.add_parser("email")
    sub.add_parser("thread")
    s = sub.add_parser("search")
    s.add_argument("text")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--folder")
    s = sub.add_parser("read")
    s.add_argument("id")
    s = sub.add_parser("order")
    s.add_argument("ref")
    s = sub.add_parser("rules")
    s.add_argument("topic", nargs="?")
    for name in ("ctms", "ctms-commit"):
        s = sub.add_parser(name)
        s.add_argument("route")
        s.add_argument("args", nargs=argparse.REMAINDER)
    s = sub.add_parser("reply")
    s.add_argument("--text", required=True)
    s = sub.add_parser("draft")
    s.add_argument("--to", required=True)
    s.add_argument("--cc")
    s.add_argument("--subject", required=True)
    s.add_argument("--text", required=True)
    s = sub.add_parser("forward")
    s.add_argument("--to", required=True)
    s.add_argument("--text", default="")
    s = sub.add_parser("file")
    s.add_argument("folder", nargs="?")
    s = sub.add_parser("ask")
    s.add_argument("--what", required=True)
    s.add_argument("route", nargs=argparse.REMAINDER)
    s = sub.add_parser("say")
    s.add_argument("text", nargs="+")
    try:
        a = p.parse_args(argv)
    except SystemExit:
        print("That isn't a command it knows. `python assist_tools.py help` lists them.")
        return 2
    if a.cmd in (None, "help"):
        print(__doc__)
        return 0
    try:
        {"email": cmd_email, "thread": cmd_thread, "search": cmd_search, "read": cmd_read, "order": cmd_order,
         "rules": cmd_rules, "ctms": cmd_ctms, "ctms-commit": cmd_ctms_commit, "reply": cmd_reply, "draft": cmd_draft,
         "forward": cmd_forward, "file": cmd_file, "ask": cmd_ask, "say": cmd_say}[a.cmd](a)
    except Stop as e:
        print("REFUSED: " + str(e))
        return 2
    except subprocess.TimeoutExpired:
        print("STOPPED: CTMS took too long - look before trying again.")
        return 2
    except Exception as e:                                # Outlook busy, CTMS away...: said, never a traceback
        print(f"FAILED: {type(e).__name__}: {str(e)[:300]}")
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
