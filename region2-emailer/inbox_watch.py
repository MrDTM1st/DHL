"""Emails that need him and are still waiting (11/11) - his managers' note that day: "Work on making sure emails are
checked more regularly so urgent emails and queries are not missed".

Every few minutes (the agent's inbox_watch job, through the Outlook gate) the folders people write to him in are read -
the Inbox, Region 2, Team, DHL, NR, CTMS, ADHOC and DTS, Haulage, and any "Allocated" folder Outlook can see - for
emails from a person that nobody has answered: no reply or forward on it, and nothing sent by him since on the same
conversation, the same subject, or to the same person about the same order. Each one is weighed:

  urgent   one of his managers (named in the home-only _inbox_watch.cfg.json), or words that say it can't wait -
           urgent, ASAP, today, tonight, derailment, emergency, chasing, still waiting, helpdesk...
  high     a materials team or Order Management, a Network Rail query, a haulier answering, a DTS
  normal   anyone else who wrote to him - a colleague, a site the tracker hasn't taken in, a supplier
  low      only copied in, or a round-robin

and goes on the dashboard's "Emails waiting for you" card - and rings the bell once it has waited longer than its
priority allows: 30 working minutes urgent, 60 high, 120 normal. Working minutes are Mon-Fri 08:00-16:30, bank holidays
out, so an email at 16:20 isn't late at 08:05. The day's Region 2 Updates is its own case: urgent, due by its usual
4pm reply.

What the desk already deals with stays off it: a site's reply the tracker has taken in (details, no details, or the
materials team answering an escalation - those have their own bell), an ad hoc form the monitor put on the map, out of
office and delivery notices, meeting replies, his own mail, automatic senders. A phone call answers an email too: he
can mark one dealt with and it stays off.

    python inbox_watch.py scan        read the mailbox, write _inbox_watch.json (the agent pushes it)
    python inbox_watch.py show
    python inbox_watch.py dealt ID    he dealt with it another way

Each command but show ends with one JSON line, {"ok": ..., "said": ...}, for the home agent.
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, time as dtime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_inbox_watch.json")
CFG = os.path.join(HERE, "_inbox_watch.cfg.json")       # home-only: {"managers": ["first last", ...]}

# Where people write to him (paths under the DHL mailbox; "*" = every folder under it)
FOLDERS = (("Inbox",), ("Inbox", "Regions", "Region 2"), ("Inbox", "Regions", "Region 2", "*"),
           ("Inbox", "Team", "*"), ("Inbox", "DHL"), ("Inbox", "NR"), ("Inbox", "CTMS"), ("Inbox", "ADHOC"),
           ("Inbox", "ADHOC", "DTS"), ("Inbox", "ADHOC", "Seasonal"), ("Inbox", "Haulage"), ("Inbox", "Haulage", "*"),
           ("Inbox", "Stoneblowers"), ("Inbox", "Media Sets"))
NOT_THESE = {"completed", "synergy upload", "send out", "send off", "deleted items"}   # done, or files, not people
WAIT = {"urgent": 30, "high": 60, "normal": 120}       # working minutes before the bell
DAYS = {"urgent": 7, "high": 7, "normal": 3, "low": 2}  # how far back each still counts
UPDATE_WAIT = 120                                       # the daily update: reply due by its usual 4pm
WORK_START, WORK_END = dtime(8, 0), dtime(16, 30)
MAX_ITEMS = 40
REPLIED, FORWARDED = (102, 103), (104,)                 # PR_LAST_VERB_EXECUTED
UPDATES = re.compile(r"region\s*2\s*update", re.I)       # the day's Region 2 Updates - his reply is due, filed or not

URGENT_WORDS = re.compile(
    r"\b(?:urgent(?:ly)?|asap|a\.s\.a\.p|today|tonight|this (?:morning|afternoon|evening)|derail\w*|emergency|"
    r"immediately|chas(?:e|ed|ing)|still waiting|helpdesk|help desk|escalat\w*|complain\w*|first thing|"
    r"by \d{1,2}(?::\d\d)?\s?(?:am|pm))\b", re.I)
AUTO_SENDER = re.compile(r"no-?reply|do-?not-?reply|notification|mailer-daemon|postmaster|otmadvisor|service\.portal|"
                         r"microsoft|sharepoint|forms\.office|yammer|newsletter|marketing|survey|calendar", re.I)
SKIP_SUBJECT = re.compile(r"^\s*(?:automatic reply|auto(?:matic)?[- ]?(?:reply|response)|out of (?:the )?office|"
                          r"undeliverable|delivery has failed|delivery status notification|mail delivery|read:|"
                          r"accepted:|declined:|tentative:|recall:|new time proposed)", re.I)
NR_QUERY = re.compile(r"\b(?:quer(?:y|ies)|pod|proof of delivery|complain\w*|not (?:been )?received|missing|"
                      r"where (?:is|are)|delivery query)\b", re.I)
ASKS = re.compile(r"\?|\b(?:can you|could you|can i|please|let me know|need(?:s|ed)?|update|confirm|chase|check|"
                  r"make sure|why|when|what|how|who|where|asap|urgent|today|tomorrow)\b", re.I)
CHANGE = re.compile(r"\b(?:new (?:date|time|day)|change[ds]?|moved|cancel\w*|can'?t|cannot|unable|delay\w*|running late|"
                    r"late|issue|problem|breakdown|broken down|refused|turned away|no access|rejected|not (?:been )?"
                    r"(?:delivered|collected|loaded)|price|quote|rate|£\s?\d)\b", re.I)
DONE = re.compile(r"\b(?:covered|confirmed|booked|delivered|completed|tipped|pod|attached|noted|received|thanks|"
                  r"thank you|all good|no problem)\b", re.I)
MATERIALS_WORDS = ("steel materials", "track aggregates", "sco sleepers", "order management", "ordermanagement",
                   "trackaggregates", "steelmaterials", "scosleepers")
DTS_REF = re.compile(r"\bNN\d{5,}|\bDTS\b", re.I)
ORDER_RE = re.compile(r"(?<![\w/])(?:[5-9]\d{6}|AH\d{1,2}/\d{1,2}/\d{2}[A-Z0-9_]+|NN\d{6,}(?:-\d+)?)(?![\w/])", re.I)
SHARED = ("networkrail.co.uk", "dhl.com", "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "aol.com",
          "yahoo.com", "yahoo.co.uk", "btinternet.com", "icloud.com", "live.co.uk")
LOWER = {"urgent": "high", "high": "normal", "normal": "low", "low": "low"}
RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


# ---------- the rules (no Outlook) ----------
def business_minutes(start, end, holidays=()):
    """Working minutes from start to end: Mon-Fri 08:00-16:30, bank holidays ("YYYY-MM-DD") out."""
    if not start or not end or end <= start:
        return 0
    total, day = 0.0, start.date()
    while day <= end.date():
        if day.weekday() < 5 and day.isoformat() not in holidays:
            a = max(start, datetime.combine(day, WORK_START))
            b = min(end, datetime.combine(day, WORK_END))
            if b > a:
                total += (b - a).total_seconds() / 60
        day += timedelta(days=1)
    return int(total)


def waited_text(minutes):
    """'45 min', '2 h 10 min', '1 day 3 h' - working time, as he'd say it."""
    if minutes < 60:
        return f"{minutes} min"
    days, rest = divmod(minutes, 510)                     # 08:00-16:30 is a working day
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} working day{'s' if days > 1 else ''}" + (f" {hours} h" if hours else "")
    return f"{hours} h" + (f" {mins} min" if mins else "")


def _norm_subject(s):
    return re.sub(r"^(?:\s*(?:re|fw|fwd|aw|wg|ext)\s*:\s*)+", "", str(s or ""), flags=re.I).strip().lower()


def orders_in(*texts):
    return sorted({m.upper() for t in texts for m in ORDER_RE.findall(str(t or ""))})


def _domain(addr):
    a = str(addr or "").lower()
    return a.split("@")[-1] if "@" in a else ""


def answered(msg, sent):
    """Has he answered it: a reply or forward on the email itself, or anything he sent since - on the same
    conversation, under the same subject, or to the same person about one of its orders."""
    updates = bool(UPDATES.search(str(msg.get("subject") or "")))
    if msg.get("verb") in (REPLIED if updates else REPLIED + FORWARDED):
        return True
    after = msg["received"]
    if any(t > after for t in sent["conv"].get(msg.get("conv") or "", ())):
        return True
    subj = _norm_subject(msg.get("subject"))
    if subj and len(subj) > 6 and any(t > after for t in sent["subject"].get(subj, ())):
        return True
    if updates:
        return False                  # an email to his manager about one order on the list isn't his reply to it
    addr = str(msg.get("from_addr") or "").lower()
    for o in msg.get("orders") or ():
        if any(t > after for t in sent["order_to"].get((o, addr), ())):
            return True
    return False


def weigh(msg, ctx):
    """(priority, why) for an email that may need him, or None when it doesn't: his own, automatic, a notice, or
    something the desk already deals with."""
    name, addr = str(msg.get("from_name") or ""), str(msg.get("from_addr") or "").lower()
    subject, words = str(msg.get("subject") or ""), str(msg.get("words") or "")
    who = f"{name} {addr}".lower()
    if addr in ctx["me"] or any(m in who for m in ctx["my_names"]):
        return None
    if AUTO_SENDER.search(who) or SKIP_SUBJECT.search(subject):
        return None
    if ctx["handled"](msg):
        return None
    to_me = msg.get("to_me", True)
    if UPDATES.search(subject):
        return "urgent", "the day's Region 2 Updates - your reply is due"
    if any(m in who for m in ctx["managers"]):
        # an ask from his manager can't wait; a note that asks nothing ("here's next week's rota") can
        return ("urgent", "your manager") if ASKS.search(f"{subject} {words}") else ("normal", "your manager (FYI)")
    hot = URGENT_WORDS.search(f"{subject} {words}")
    if hot:
        why = f'says "{hot.group(0).lower()}"'
        return ("urgent" if to_me else "high"), why
    dom = _domain(addr)
    haulier = addr in ctx["haulier_addrs"] or (dom and dom not in SHARED and dom in ctx["haulier_domains"])
    if addr in ctx["materials"] or any(w in who for w in MATERIALS_WORDS):
        pri, why = "high", "a materials team / Order Management"
    elif dom == "networkrail.co.uk" and NR_QUERY.search(subject):
        pri, why = "high", "a Network Rail query"
    elif haulier and CHANGE.search(f"{subject} {words}"):
        # a new date or time, a cancellation, a problem, a price: the site or the booking needs him
        pri, why = "high", f'a haulier: "{CHANGE.search(f"{subject} {words}").group(0).lower()}"'
    elif haulier and DONE.search(words):
        pri, why = "low", "a haulier confirming"
    elif haulier:
        pri, why = "normal", "a haulier answering"
    elif msg.get("folder", "").lower().endswith("dts") or DTS_REF.search(subject):
        pri, why = "high", "a DTS"
    elif dom == "dhl.com":
        pri, why = "normal", "a colleague"
    else:
        pri, why = "normal", "wrote to you"
    if not to_me or msg.get("crowd"):
        pri, why = LOWER[pri], why + " (copied in)" if not to_me else why + " (round-robin)"
    return pri, why


def _thread(m):
    """Which conversation an email belongs to: Outlook's own, else its subject without RE:/FW:."""
    return m.get("conv") or "s:" + _norm_subject(m.get("subject"))


def judge(msgs, sent, ctx, now, holidays=(), dealt=()):
    """The conversations waiting for him, most pressing first: [{id, pri, why, alarm, waited, n, ...}]. One line a
    thread - the newest unanswered email shown, the most pressing reason in it, and the wait counted from the first
    one he hasn't answered (how long someone has been waiting)."""
    threads = {}
    for m in msgs:
        if m["id"] in dealt or m["received"] > now:
            continue
        got = weigh(m, ctx)
        if not got:
            continue
        pri, why = got
        if m["received"] < now - timedelta(days=DAYS[pri]) or answered(m, sent):
            continue
        threads.setdefault(_thread(m), []).append((m, pri, why))
    out = []
    for group in threads.values():
        group.sort(key=lambda x: x[0]["received"])
        first, newest = group[0][0], group[-1][0]
        m, pri, why = min(group, key=lambda x: (RANK[x[1]], -x[0]["received"].timestamp()))
        if any(g[2].startswith("the day's Region 2") for g in group):
            pri, why = "urgent", next(g[2] for g in group if g[2].startswith("the day's Region 2"))
        mins = business_minutes(first["received"], now, holidays)
        limit = UPDATE_WAIT if why.startswith("the day's Region 2") else WAIT.get(pri)
        ids = [g[0]["id"] for g in group]
        out.append({"id": newest["id"], "ids": ids, "n": len(group), "pri": pri, "why": why,
                    "from": newest.get("from_name") or newest.get("from_addr"), "addr": newest.get("from_addr"),
                    "subject": str(newest.get("subject") or "")[:160],
                    "received": newest["received"].strftime("%d/%m %H:%M"), "waited": waited_text(mins), "mins": mins,
                    "alarm": bool(limit) and mins >= limit, "unread": any(g[0].get("unread") for g in group),
                    "folder": newest.get("folder"), "orders": sorted({o for g in group for o in g[0].get("orders") or []})[:6],
                    "said": re.sub(r"\s+", " ", str(newest.get("words") or ""))[:220]})
    out.sort(key=lambda x: (not x["alarm"], RANK[x["pri"]], -x["mins"]))
    return out[:MAX_ITEMS]


# ---------- what the desk already deals with ----------
def _dt(v):
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(str(v or "").strip()[:19], f)
        except ValueError:
            continue
    return None


def taken_in(records, adhoc_ids=()):
    """handled(msg): this is the very reply the tracker took in - the site's details, a reply without them, or the
    materials team answering an escalation, each with its own bell - or a form the monitor put on the map. The
    tracker notes the reply a few minutes after it lands, so it is the email received up to half an hour before
    that note, about one of its orders, from outside DHL: a colleague's email about the same order still counts."""
    marks = []
    for r in records or []:
        orders = {str(o).upper() for o in r.get("orders") or []}
        for t in [_dt(r.get("reply_at"))] + [_dt((r.get(k) or {}).get("at")) for k in ("needs_info", "escalation_reply")]:
            if orders and t:
                marks.append((orders, t))
    forms = set(adhoc_ids or ())

    def handled(msg):
        if msg.get("eid") in forms:
            return True
        if _domain(msg.get("from_addr")) == "dhl.com":
            return False
        mine, at = set(msg.get("orders") or ()), msg["received"]
        return any(mine & orders and at - timedelta(minutes=2) <= t <= at + timedelta(minutes=30)
                   for orders, t in marks)
    return handled


# ---------- the store ----------
def _json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except Exception:
        return default


def load():
    d = _json(PATH, {})
    d.setdefault("items", [])
    d.setdefault("dealt", {})
    return d


def save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
    os.replace(tmp, PATH)


def panel(d=None):
    """The dashboard's card: what's waiting (the alarms first), how many low ones were left off, when it looked."""
    d = d or load()
    items = d.get("items") or []
    shown = [i for i in items if i.get("pri") != "low"]
    return {"at": d.get("at", ""), "items": shown[:30], "low": len(items) - len(shown),
            "alarms": sum(1 for i in shown if i.get("alarm")), "seconds": d.get("seconds")}


# ---------- reading Outlook ----------
def _id(eid):
    return hashlib.sha1(str(eid).encode()).hexdigest()[:12]


def _addr(it):
    a = str(getattr(it, "SenderEmailAddress", "") or "")
    if a.startswith("/") or "@" not in a:
        try:
            a = str(it.Sender.GetExchangeUser().PrimarySmtpAddress or a)
        except Exception:
            pass
    return a.lower()


def _subfolders(f, path):
    """The folders a FOLDERS path names: "*" every folder under the one before it."""
    for part in path[1:]:
        if f is None:
            return []
        if part == "*":
            return [f.Folders.Item(j) for j in range(1, f.Folders.Count + 1)
                    if str(f.Folders.Item(j).Name).strip().lower() not in NOT_THESE]
        f = next((f.Folders.Item(j) for j in range(1, f.Folders.Count + 1)
                  if str(f.Folders.Item(j).Name).strip().lower() == part.lower()), None)
    return [f] if f is not None else []


def _allocated(ns):
    """Any folder called Allocated that Outlook can see - the DHL Road shared mailbox's, once it's added."""
    out = []

    def walk(f, depth):
        try:
            if "allocat" in str(f.Name).lower():
                out.append(f)
            if depth < 4:
                for j in range(1, f.Folders.Count + 1):
                    walk(f.Folders.Item(j), depth + 1)
        except Exception:
            pass
    for k in range(1, ns.Stores.Count + 1):
        try:
            walk(ns.Stores.Item(k).GetRootFolder(), 0)
        except Exception:
            pass
    return out


def collect(ns, now, me):
    """(the emails to weigh, what he has sent) from Outlook."""
    import build_drafts as bd
    from rejections import own_words
    root = bd.dhl_store(ns)
    if root is None:
        raise RuntimeError("the DHL mailbox isn't open in Outlook")
    inbox = next((root.Folders.Item(j) for j in range(1, root.Folders.Count + 1)
                  if str(root.Folders.Item(j).Name) == "Inbox"), None)
    folders, seen = [], set()
    for path in FOLDERS:
        for f in _subfolders(inbox, path) if inbox is not None else []:
            if f.EntryID not in seen:
                seen.add(f.EntryID)
                folders.append(f)
    for f in _allocated(ns):
        if f.EntryID not in seen:
            seen.add(f.EntryID)
            folders.append(f)
    # the day's Region 2 Updates needs his reply wherever it was filed - Completed included, for that email only
    filed = set()
    for f in _subfolders(inbox, ("Inbox", "Regions", "Region 2", "Completed")) if inbox is not None else []:
        if f.EntryID not in seen:
            seen.add(f.EntryID)
            filed.add(str(f.EntryID))
            folders.append(f)
    cut = now - timedelta(days=max(DAYS.values()))
    msgs = []
    verb = "http://schemas.microsoft.com/mapi/proptag/0x10810003"
    for f in folders:
        label = str(f.FolderPath).split("\\", 3)[-1] if "\\" in str(f.FolderPath) else str(f.Name)
        try:
            items = f.Items
            items.Sort("[ReceivedTime]", True)
        except Exception:
            continue
        only_updates = str(f.EntryID) in filed
        for i in range(1, min(items.Count, 400) + 1):
            try:
                it = items.Item(i)
                when = it.ReceivedTime.replace(tzinfo=None)
            except Exception:
                continue
            if when < cut or (only_updates and when.date() < now.date()):
                break
            try:
                if not str(it.MessageClass).startswith("IPM.Note"):
                    continue
                if only_updates and not UPDATES.search(str(getattr(it, "Subject", "") or "")):
                    continue
                try:
                    v = it.PropertyAccessor.GetProperty(verb)
                except Exception:
                    v = 0
                to = str(getattr(it, "To", "") or "")
                cc = str(getattr(it, "CC", "") or "")
                body = str(getattr(it, "Body", "") or "")[:4000]
                subject = str(getattr(it, "Subject", "") or "")
                words = own_words(body)
                n_to = len([x for x in re.split(r"[;,]", to) if x.strip()]) + len([x for x in re.split(r"[;,]", cc) if x.strip()])
                msgs.append({"id": _id(it.EntryID), "eid": str(it.EntryID), "conv": str(getattr(it, "ConversationID", "") or ""),
                             "folder": label, "from_name": str(getattr(it, "SenderName", "") or ""), "from_addr": _addr(it),
                             "subject": subject, "received": when, "unread": bool(getattr(it, "UnRead", False)), "verb": v,
                             "words": words[:600], "orders": orders_in(subject, words[:1500]),
                             "to_me": _mentions_me(to, me), "crowd": n_to > 12})
            except Exception:
                continue
    sent = {"conv": {}, "subject": {}, "order_to": {}}
    sf = next((root.Folders.Item(j) for j in range(1, root.Folders.Count + 1)
               if str(root.Folders.Item(j).Name) == "Sent Items"), None)
    if sf is not None:
        items = sf.Items
        items.Sort("[SentOn]", True)
        for i in range(1, min(items.Count, 600) + 1):
            try:
                it = items.Item(i)
                when = it.SentOn.replace(tzinfo=None)
            except Exception:
                continue
            if when < cut:
                break
            try:
                subject = str(getattr(it, "Subject", "") or "")
                sent["conv"].setdefault(str(getattr(it, "ConversationID", "") or ""), []).append(when)
                sent["subject"].setdefault(_norm_subject(subject), []).append(when)
                orders = orders_in(subject, str(getattr(it, "Body", "") or "")[:1500])
                recips = []
                for k in range(1, it.Recipients.Count + 1):
                    r = it.Recipients.Item(k)
                    a = str(getattr(r, "Address", "") or "")
                    if "@" not in a:
                        try:
                            a = str(r.AddressEntry.GetExchangeUser().PrimarySmtpAddress or a)
                        except Exception:
                            pass
                    recips.append(a.lower())
                for o in orders:
                    for a in recips:
                        sent["order_to"].setdefault((o, a), []).append(when)
            except Exception:
                continue
    return msgs, sent


def _mentions_me(to, me):
    """Is he on the To line (not only copied in)? Display names count - Outlook often shows only those."""
    t = str(to or "").lower()
    return not t.strip() or any(m in t for m in me)


def context(records=None, adhoc_ids=None):
    """Who is who: his managers (the home-only config), the materials teams, the hauliers - and what the desk deals
    with already."""
    import build_drafts as bd
    cfg = _json(CFG, {})
    me = {bd.DHL_SMTP.lower()}
    names = ([str(n).lower() for n in cfg.get("my_names", [])]
             or [bd.DHL_SMTP.split("@")[0].replace(".", " ").lower()])
    materials = set()
    hauler_addrs, hauler_domains = set(), set()
    try:
        import hauliers
        materials = {t["email"].lower() for t in hauliers.MATERIALS_TEAMS.values()}
        d = hauliers.load()
        for g in ("hauliers", "couriers"):
            for h in d.get(g, []) or []:
                for e in h.get("emails") or []:
                    e = str(e).strip().lower()
                    hauler_addrs.add(e)
                    if _domain(e) and _domain(e) not in SHARED:
                        hauler_domains.add(_domain(e))
    except Exception:
        pass
    if records is None:
        records = _json(os.path.join(HERE, "tracker.json"), {}).get("records") or []
    if adhoc_ids is None:
        adhoc_ids = _json(os.path.join(HERE, "_monitor_seen.json"), {}).get("adhoc_ids") or []
    return {"me": me | {n for n in names}, "my_names": names,
            "managers": [str(n).lower() for n in cfg.get("managers", [])], "materials": materials,
            "haulier_addrs": hauler_addrs, "haulier_domains": hauler_domains,
            "handled": taken_in(records, adhoc_ids)}


def scan(ns=None, now=None):
    """Read the mailbox and write what's waiting. -> the panel."""
    import build_drafts as bd
    try:
        from services import BANK_HOLIDAYS as holidays
    except Exception:
        holidays = set()
    t0 = time.time()
    now = now or datetime.now()
    ns = ns or bd.get_ns()
    ctx = context()
    msgs, sent = collect(ns, now, ctx["me"])
    d = load()
    keep = {k: v for k, v in d["dealt"].items() if v >= (now - timedelta(days=10)).strftime("%Y-%m-%d")}
    d.update(items=judge(msgs, sent, ctx, now, holidays, set(keep)), dealt=keep,
             at=now.strftime("%d/%m %H:%M"), seconds=round(time.time() - t0, 1), read=len(msgs))
    save(d)
    return panel(d)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "show":
        for i in load()["items"]:
            print(f"{i['pri']:7} {'BELL' if i['alarm'] else '    '} {i['waited']:>14} | {i['from'][:28]:28} | "
                  f"{i['subject'][:60]} | {i['why']} | {i['folder']}")
        return 0
    if cmd == "scan":
        try:
            p = scan()
        except Exception as e:
            print(json.dumps({"ok": False, "said": f"The inbox couldn't be read ({type(e).__name__}: {e})."}))
            return 1
        print(json.dumps({"ok": True, "said": f"{len(p['items'])} email(s) waiting, {p['alarms']} past their time."}))
        return 0
    if cmd == "dealt":
        iid = argv[2] if len(argv) > 2 else ""
        d = load()
        item = next((i for i in d["items"] if i["id"] == iid), None)
        if item is None:
            print(json.dumps({"ok": False, "said": "That email isn't on the list any more."}))
            return 1
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        for x in item.get("ids") or [iid]:             # the whole thread as it stood - a new email in it comes back
            d["dealt"][x] = stamp
        d["items"] = [i for i in d["items"] if i["id"] != iid]
        save(d)
        print(json.dumps({"ok": True, "said": "Taken off - dealt with."}))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))
