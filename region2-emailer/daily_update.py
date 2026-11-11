"""His reply to the day's Region 2 Updates, drafted for him (11/11).

Every working day after their 1pm call his managers email the notes - each order on the list and what's asked of it -
and he replies by 4-5pm with where each one stands. His words (11/11): "I'm trying my best, but I can't keep up". So
this writes that reply. For each order on the day's list it works out where it really stands from everything the desk
keeps - the tracker (asked, chased, replied, escalated, the materials team's answer), the wait list, the CTMS to-do,
the bookings (the Book journal, the booked ad hocs, the orders taken off as booked), the haulier asks - and the mailbox
itself: what he sent and what came back about it, by hand or not, in the order it happened. Then a reply in his own
style (his 09/10 one: the weeks and the orders in their order, a short line each) goes into Outlook's Drafts as a
Reply All on their email.

It is never sent from here: he reads it, adds what only he knows (a call), and sends it. Anything it cannot show from a
record or an email is marked [check] in yellow - never guessed, as it goes to his manager. Colleagues' emails and the
updates themselves are never taken for a site's reply.

    python daily_update.py preview [--now YYYY-MM-DDTHH:MM]   what it would write today; nothing made
    python daily_update.py draft [--force]                      today's draft, made once (again with --force)
    python daily_update.py due                                  the agent's job: drafts once DRAFT_AT has passed

Each command but preview ends with one JSON line, {"ok": ..., "said": ...}, for the home agent.
"""
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "_daily_update.json")
DRAFT_AT = (15, 30)                 # the draft is made then (or as the email lands, if later) - his reply is due by 4-5pm
DRAFT_UNTIL = 18                    # ...and not after this hour: by then it's the Dashboard's Draft it now
LOOK_BACK = 21                      # days of mail read for each order's story
MAX_EVENTS = 6                      # the last this many steps of an order's story make its line
CHECK = "[check]"
YOURS = "[your update]"

SUBJECT = re.compile(r"region\s*2\s*update", re.I)
WEEK = re.compile(r"^\s*(?:w/?c\s*)?(\d{1,2}/\d{1,2})\s*[–—-]\s*(\d{1,2}/\d{1,2})\s*[–—-]?\s*$", re.I)
# a manifest is written bare in the updates ("01500001"), so an 8-figure 015-019 number reads as one - room to grow
REF = re.compile(r"AH\d{1,2}/\d{1,2}/\d{2}[A-Z0-9_]+|NN\d{6,}(?:-\d+)?|MAN-?0\d{7}\b|[A-Z]{2,4}\d{3,}(?:-\d+)*|"
                 r"\b01[5-9]\d{5}\b|\b[5-9]\d{6}(?:-\d+-\d+)?\b", re.I)
_TOKEN = r"(?:AH\d{1,2}/\d{1,2}/\d{2}[A-Z0-9_]+|(?:MAN-)?[A-Z]{0,4}\d[\w.-]*)"
LEAD = re.compile(r"^\s*(?:orders?\s+)?(?P<refs>" + _TOKEN + r"(?:\s*(?:&|/|,|\+|and)\s*" + _TOKEN + r")*)\s*[–—-]\s*"
                  r"(?P<notes>.*)$", re.I)
GREETING = re.compile(r"^\s*(?:hi|hello|morning|afternoon)\b[^\n]{0,30}$|^\s*(?:see below|below|notes in red|updates? "
                      r"from|as we agreed|as discussed)\b", re.I)
SIGN_OFF = re.compile(r"^\s*(?:kind regards|regards|many thanks|thanks|best)\s*,?\s*$", re.I)
MAN = re.compile(r"\bMAN-?0\d{7}\b", re.I)
ALT_CONTACT = re.compile(r"alternative contact|alt contact|site contact needed|contact needed|new contact", re.I)
CHASED = re.compile(r"can i please get a reply|just following up|following up on|chasing|any update", re.I)
WEBMAIL = ("gmail.com", "googlemail.com", "aol.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.co.uk",
           "btinternet.com", "icloud.com", "live.co.uk", "dhl.com", "networkrail.co.uk")


# ---------- the managers' email ----------
def own_part(body):
    """Their email's own words: above the first quoted header, signature off."""
    text = str(body or "").replace("\r\n", "\n")
    text = re.split(r"\n\s*From:\s", text, maxsplit=1)[0]
    lines = []
    for ln in text.split("\n"):
        if SIGN_OFF.match(ln):
            break
        lines.append(ln.rstrip())
    return "\n".join(lines).strip()


def refs_in(text):
    """The orders (and ad hoc, DTS, manifest refs) a line names, as written: '5000001-1-1' reads 5000001."""
    out = []
    for r in REF.findall(str(text or "")):
        r = _canon(re.sub(r"^([5-9]\d{6})-\d+-\d+$", r"\1", r.upper()))
        if r not in out:
            out.append(r)
    return out


def _canon(ref):
    """A ref the one way: a manifest as MAN-0xxxxxxx however it was written (01500001, MAN01500001)."""
    r = str(ref or "").upper()
    m = re.fullmatch(r"(?:MAN-?)?(01[5-9]\d{5})|MAN-?(0\d{7})", r)
    return "MAN-" + (m.group(1) or m.group(2)) if m else r


def _is_man(ref):
    return str(ref).startswith("MAN-")


def parse(text):
    """[{"kind": "week", "label"} | {"kind": "order", "refs", "notes", "line"} | {"kind": "point", "line"}] in their
    order - weeks, the order lines under them, and the other points."""
    out = []
    for raw in str(text or "").split("\n"):
        ln = re.sub(r"\s+", " ", raw).strip()
        if not ln or GREETING.match(ln):
            continue
        w = WEEK.match(ln)
        if w:
            out.append({"kind": "week", "label": f"{w.group(1)} – {w.group(2)}"})
            continue
        m = LEAD.match(ln)
        refs = refs_in(m.group("refs")) if m else []
        if m and refs:
            out.append({"kind": "order", "refs": refs, "notes": m.group("notes").strip(), "line": ln})
        elif re.fullmatch(r"no orders? outstanding\.?", ln, re.I):
            continue
        else:
            out.append({"kind": "point", "line": ln, "refs": refs_in(ln)})
    return out


# ---------- names and dates ----------
def _dt(v):
    if isinstance(v, datetime):
        return v
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y %H:%M"):
        try:
            return datetime.strptime(str(v or "").strip()[:19], f)
        except ValueError:
            continue
    return None


def _d(v):
    t = _dt(v)
    return t.strftime("%d/%m") if t else ""


def _first(name):
    n = re.sub(r"\(.*?\)", "", str(name or "")).strip().strip("'\"")
    if not n or "@" in n:
        return ""
    parts = n.split()
    return parts[0].capitalize() if parts and parts[0][:1].isalpha() else ""


def nice(name, addr="", teams=None):
    """How he'd name someone in the reply: a team as itself, a person by their name as Outlook shows it (company
    aside), or made from their address (john.smith@ is John Smith)."""
    teams = teams or {}
    a = str(addr or "").lower().strip("'\" <>")
    n = re.sub(r"\s*\(.*?\)\s*", " ", str(name or "")).strip().strip("'\"")
    if "@" in n and not a:
        a, n = n.lower(), ""
    if a in teams:
        return teams[a]
    local = a.split("@")[0]
    parts = [p for p in re.split(r"[._-]+", local) if p.isalpha()]
    full = " ".join(p.capitalize() for p in parts[:2])
    if n and "@" not in n:
        # "Ian" on the tracker and ian.smith@ on the email reads Ian Smith
        return full if " " not in n and len(parts) >= 2 and parts[0].lower() == n.lower() else n
    return full or a


def _match(refs, orders):
    have = {str(o).upper() for o in orders or []}
    return bool(have & set(refs))


# ---------- where an order stands ----------
def facts(refs, src):
    """Everything the desk knows about these refs: {record, wait, todo, trips, adhoc, dropped, mails, asks}."""
    rec = next((r for r in src["tracker"] if _match(refs, r.get("orders"))), None)
    wait = next((e for e in src["waitlist"] if _match(refs, e.get("orders"))), None)
    todo = [t for t in src["todo"] if _match(refs, t.get("orders"))]
    trips = []
    for job in src["journal"]:
        lines = {re.sub(r"-\d+-\d+$", "", str(ln)).upper() for t in job.get("trips") or [] for ln in t.get("lines") or []}
        whole = (lines & set(refs) or _match(refs, job.get("orders"))
                 or any(r in str(job.get("key", "")).upper() for r in refs if not _is_man(r)))
        # a manifest on the list is that trip alone
        trips += [t for t in job.get("trips") or [] if t.get("manifest") and (whole or _canon(t["manifest"]) in refs)]
    adhoc = [b for b in src["adhoc_booked"]
             if str(b.get("ref", "")).upper() in refs or (b.get("man") and _canon(b["man"]) in refs)]
    dropped = any(r in src["booked_drops"] for r in refs)
    mails = sorted((m for m in src["mails"] if set(m["refs"]) & set(refs)), key=lambda m: m["when"])
    asks = [a for r in refs for a in src["asks"].get(r, [])]
    return {"record": rec, "wait": wait, "todo": todo, "trips": trips, "adhoc": adhoc, "dropped": dropped,
            "mails": mails, "asks": asks, "teams": src.get("teams") or {},
            "manifests": bool(refs) and all(_is_man(r) for r in refs)}


def _story(f):
    """The order's steps in the order they happened: [(when, kind, text)], from the mail first, the tracker filling
    in what the mail doesn't show. Colleagues' emails are never steps; nor are ring-rounds to hauliers on an order (the
    asks say those) - but on a manifest the haulier is the story."""
    teams, rec = f["teams"], f["record"] or {}
    was = rec.get("contact_was") or {}
    site = nice(was.get("name") or rec.get("name"), was.get("to") or rec.get("to"), teams) if rec else ""
    steps = []
    for m in f["mails"]:
        k, when = m["kind"], m["when"]
        if k in ("internal", "told") or (k == "haulier_out" and not f.get("manifests")):
            continue
        if m["dir"] == "out":
            # who it went to - the tracker's contact when Outlook didn't say (an email the batch sent)
            who = " and ".join(nice(n, a, teams) for n, a in m["to"][:2]) or site or "the site"
            what = "an alt contact" if re.search(r"altern|alt", m["subject"], re.I) else "a site contact"
            text = {"escalate": f"raised with {who} {when:%d/%m} for {what}",
                    "team_out": f"asked {who} {when:%d/%m}", "chase": f"chased {when:%d/%m}"}.get(k, f"emailed {who} {when:%d/%m}")
        else:
            who = nice(m["from_name"], m["from_addr"], teams)
            text = f"{who} answered {when:%d/%m}" if k == "team_in" else f"{who} replied {when:%d/%m}"
        steps.append((when, k, text))
    kinds = {k for _, k, _ in steps}
    if rec.get("emailed_at") and "ask" not in kinds:
        who = nice(was.get("name") or rec.get("name"), was.get("to") or rec.get("to"), teams)
        steps.append((_dt(rec["emailed_at"]), "ask", f"emailed {who} {_d(rec['emailed_at'])}"))
    if rec.get("chases") and rec.get("last_chased_at") and "chase" not in kinds:
        steps.append((_dt(rec["last_chased_at"]), "chase", f"chased {_d(rec['last_chased_at'])}"))
    if rec.get("escalated_at") and "escalate" not in kinds:
        steps.append((_dt(rec["escalated_at"]), "escalate", f"raised with the materials team {_d(rec['escalated_at'])} "
                                                            "for an alt contact"))
    ans = rec.get("escalation_reply") or {}
    if ans.get("at") and "team_in" not in kinds:
        steps.append((_dt(ans["at"]), "team_in", f"{nice(ans.get('team') or ans.get('from'), ans.get('addr'), teams)} "
                                                 f"answered {_d(ans['at'])}"))
    steps = [s for s in steps if s[0]]
    steps.sort(key=lambda s: s[0])
    # the same step on the trot reads as one ("chased 06/11, 10/11", "asked SCO 10/11, 11/11"); the same step twice
    # is told once
    out, told = [], set()
    for when, k, text in steps:
        base, day = re.sub(r"\d{2}/\d{2}", "#", text), f"{when:%d/%m}"
        if out and out[-1][1] == k and out[-1][3] == base:
            if day not in out[-1][2]:
                out[-1][2] = re.sub(r"^(.*\d{2}/\d{2})", lambda mm: mm.group(1) + ", " + day, out[-1][2], count=1)
            out[-1][0] = when
        elif text not in told:
            out.append([when, k, text, base])
        told.add(text)
    return [(w, k, t) for w, k, t, _base in out]


def _told(steps):
    """The story as a line: the start (the ask and its chases) and the latest steps, "..." between when it's long."""
    texts = [s[2] for s in steps]
    if len(texts) > MAX_EVENTS:
        texts = texts[:2] + ["..."] + texts[-(MAX_EVENTS - 2):]
    return ", ".join(texts).replace(", ..., ", " ... ")


IN_KINDS = ("team_in", "reply", "haulier")


def m_dir_in(step):
    """A step that came in (an answer or a reply) rather than one he sent."""
    return step[1] in IN_KINDS


def _mans(f):
    found = []
    for t in f["trips"]:
        found.append((str(t["manifest"]).upper(), _d(t.get("collect")), _d(t.get("deliver"))))
    for b in f["adhoc"]:
        if b.get("man"):
            found.append((str(b["man"]).upper(), "", ""))
    for m in f["mails"]:
        if m["dir"] == "out" and m["kind"] == "told":
            found += [(x, "", "") for x in m["mans"]]
    seen, out = set(), []
    for man, col, dl in found:
        man = man.replace("MAN0", "MAN-0")
        if man not in seen:
            seen.add(man)
            out.append((man, col, dl))
    return out


def status(refs, f, now):
    """One line, his style, of where these orders stand - facts with their dates; [check] where it can't tell."""
    rec, teams = f["record"] or {}, f["teams"]
    bits = []
    mans = _mans(f)
    told = [m for m in f["mails"] if m["dir"] == "out" and m["kind"] == "told"]
    if mans:
        if len(mans) > 3:
            line = f"Booked, {len(mans)} manifests ({mans[0][0]} to {mans[-1][0]})"
        else:
            line = "Booked, " + ", ".join(m + (f" (collect {c}, deliver {d})" if c and d else "") for m, c, d in mans)
        if told:
            line += f" - {nice(*told[-1]['to'][0], teams)} told {told[-1]['when']:%d/%m}" if told[-1]["to"] else ""
        bits.append(line)
    steps = _story(f)
    if f.get("manifests"):
        # a manifest on the list (a haulier issue, say): its booking, then what's been said about it since
        if steps:
            bits.append(_told(steps))
            bits.append(f"{CHECK} their answer to follow up" if m_dir_in(steps[-1]) else "waiting on a reply")
        elif not mans:
            bits.append(f"{CHECK} nothing found on this manifest in the last 3 weeks' mail")
        return _sentence(bits)
    if steps and not mans:
        bits.append(_told(steps))
    # where it stands now
    if not mans:
        last = steps[-1] if steps else None
        missing = rec.get("missing") or []
        ni = rec.get("needs_info") or {}
        if rec.get("ctms_veh") or (rec.get("reply_at") and not missing):
            when = _d(rec.get("reply_at"))
            bits.append(f"details in{(' ' + when) if when else ''}" + (" (Veh Type in CTMS)" if rec.get("ctms_veh") else "")
                        + " - to book")
        elif rec.get("reply_at"):
            bits.append(f"replied {_d(rec['reply_at'])} but still need " + ", ".join(missing))
        elif ni.get("at") and (not last or _dt(ni["at"]) >= last[0]):
            bits.append(f"{nice(ni.get('from'), ni.get('addr'), teams)} replied {_d(ni['at'])} without the details - "
                        "to email back")
        elif last and last[1] in ("ask", "chase", "escalate", "team_out"):
            bits.append("waiting on a reply")
        elif last and m_dir_in(last):
            bits.append(f"{CHECK} their answer to follow up")
        if f["dropped"]:
            bits.append(f"taken off the open list as booked in CTMS - {CHECK} the MAN")
        w = f["wait"] or {}
        site_asked = (any(s[1] in ("ask", "chase") for s in steps) or rec.get("emailed_at")
                      or w.get("status") in ("sent", "waiting"))
        if steps and not site_asked and not f["dropped"]:
            bits.append(f"{CHECK} site not emailed yet")
        if not steps and not rec:
            if w.get("status") == "waiting":
                bits.append(f"On the wait list - the site is emailed 3 weeks before the {w.get('date')} delivery")
            elif w.get("status") == "missed":
                bits.append(f"{CHECK} missed on the wait list - its {w.get('date')} date passed before it went")
            elif w.get("status") == "sent" and w.get("sent_at"):
                bits.append(f"Emailed {_first(w.get('name')) or 'the site'} {_d(w['sent_at'])}")
            elif not f["dropped"]:
                bits.append(f"{CHECK} site not emailed yet - nothing sent about it in the last 3 weeks")
    if f["asks"] and not mans:
        names = sorted({a.get("name") for a in f["asks"] if a.get("name")})
        first = min((_dt(a.get("when")) for a in f["asks"] if _dt(a.get("when"))), default=None)
        bits.append(f"out to {len(names)} haulier{'s' if len(names) != 1 else ''}"
                    + (f" from {first:%d/%m}" if first else "") + (f" ({', '.join(names[:4])})" if names else ""))
    open_todo = [t for t in f["todo"] if not t.get("done_at")]
    done_todo = [t for t in f["todo"] if t.get("done_at") and t.get("kind") == "update"]
    if done_todo:
        bits.append(f"CTMS updated {_d(done_todo[-1]['done_at'])}")
    if open_todo:
        bits.append("CTMS update waiting on the Run")
    return _sentence(bits)


def _sentence(bits):
    if not bits:
        return CHECK + " nothing found to say where this one stands (the desk's records and the last 3 weeks' mail)."
    text = "; ".join(bits)
    text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."


# ---------- the reply ----------
def compose(parsed, src, now, greet="Hi"):
    """(plain text, HTML, summary) of the reply."""
    lines, html_lines, done, checks = [f"{greet},"], [f"<p>{html.escape(greet)},</p>"], 0, 0
    points = [p for p in parsed if p["kind"] == "point"]
    if points:
        html_lines.append("<p>")
        for p in points:
            lines.append(f"{p['line']} – {YOURS}")
            html_lines.append(f"{html.escape(p['line'])} – {_hl(YOURS)}<br>")
        html_lines.append("</p>")
    block = []
    for p in parsed:
        if p["kind"] == "week":
            if block:
                html_lines.append("<p>" + "".join(block) + "</p>")
                block = []
            lines.append(p["label"])
            block.append(f"<b>{html.escape(p['label'])}</b><br>")
        elif p["kind"] == "order":
            st = status(p["refs"], facts(p["refs"], src), now)
            label = " / ".join(r[4:] if r.startswith("MAN-") else r for r in p["refs"])
            lines.append(f"{label} – {st}")
            block.append(f"{html.escape(label)} – {_marked(st)}<br>")
            done += 1
            checks += CHECK in st
    if block:
        html_lines.append("<p>" + "".join(block) + "</p>")
    return "\n".join(lines), "".join(html_lines), {"orders": done, "checks": checks, "points": len(points)}


def _hl(text):
    return f'<span style="background:#fff2a8">{html.escape(text)}</span>'


def _marked(text):
    return html.escape(text).replace(html.escape(CHECK), _hl(CHECK))


# ---------- the desk's records ----------
def _json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except Exception:
        return default


def directory():
    """(teams {address: name}, haulier addresses and domains) - who's who in the mail."""
    teams = {"ordermanagement@networkrail.co.uk": "Order Management"}
    hauliers = set()
    try:
        import hauliers as H
        teams.update({t["email"].lower(): t["name"] for t in H.MATERIALS_TEAMS.values()})
        for g in ("hauliers", "couriers"):
            for h in H.load().get(g, []) or []:
                for e in h.get("emails") or []:
                    e = str(e).lower().strip()
                    hauliers.add(e)
                    if e.split("@")[-1] not in WEBMAIL:
                        hauliers.add(e.split("@")[-1])
    except Exception:
        pass
    return teams, hauliers


def records():
    """The desk's own records, as facts() takes them (mails filled in from Outlook)."""
    j = _json(os.path.join(HERE, "_book_journal.json"), {}).get("jobs") or {}
    teams, _hauliers = directory()
    return {"tracker": _json(os.path.join(HERE, "tracker.json"), {}).get("records") or [],
            "waitlist": _json(os.path.join(HERE, "waitlist.json"), {}).get("entries") or [],
            "todo": _json(os.path.join(HERE, "_ctms_todo.json"), {}).get("items") or [],
            "journal": list(j.values()) if isinstance(j, dict) else [],
            "adhoc_booked": _json(os.path.join(HERE, "_adhoc_booked.json"), []),
            "booked_drops": {str(x).upper() for x in _json(os.path.join(HERE, "_booked_drops.json"), [])},
            "asks": {str(k).upper(): v for k, v in _json(os.path.join(HERE, "_haulier_asks.json"), {}).items()},
            "teams": teams, "mails": []}


def classify(dir_, subject, words, to, from_addr, teams, hauliers, mans):
    """What an email about an order was, as the reply tells it: out - ask, chase, escalate, team_out, haulier_out, told,
    internal; in - reply, team_in, haulier, internal. The updates themselves and colleagues are internal."""
    def haulier(a):
        return a in hauliers or a.split("@")[-1] in hauliers
    if SUBJECT.search(subject):
        return "internal"
    if dir_ == "out":
        addrs = [a for _n, a in to]
        if ALT_CONTACT.search(subject) and any(a in teams for a in addrs):
            return "escalate"
        if any(a in teams for a in addrs):
            return "team_out"
        if any(haulier(a) for a in addrs):
            return "haulier_out"
        if addrs and all(a.endswith("@dhl.com") for a in addrs):
            return "internal"
        if mans:
            return "told"
        if CHASED.search(words):
            return "chase"
        return "ask"
    if from_addr in teams:
        return "team_in"
    if haulier(from_addr):
        return "haulier"
    if from_addr.endswith("@dhl.com"):
        return "internal"
    return "reply"


def _want(refs):
    """These refs as people write them in an email, whole - a manifest with or without its MAN-; 5000001 in
    5000001-1-1 or 5000001/5000002, never inside a longer number."""
    alts = [r"(?:MAN-?)?" + r[4:] if _is_man(r) else re.escape(r) for r in sorted(set(refs), key=len, reverse=True)]
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.I) if alts else None


def read_mail(ns, refs, now):
    """[{when, dir, kind, refs, subject, from_name, from_addr, to: [(name, address)], mans}] - every email of the last
    LOOK_BACK days whose subject or own words name one of the refs, in the DHL mailbox (Completed folders too)."""
    import build_drafts as bd
    from rejections import own_words
    root = bd.dhl_store(ns)
    me = bd.DHL_SMTP.lower()
    teams, hauliers = directory()
    want = _want(refs)
    cut = now - timedelta(days=LOOK_BACK)
    out, seen = [], set()
    skip = {"deleted items", "synergy upload", "junk email", "outbox", "drafts", "media sets"}

    def addr_of(entry, fallback):
        a = str(fallback or "")
        if "@" not in a:
            try:
                a = str(entry.GetExchangeUser().PrimarySmtpAddress or a)
            except Exception:
                pass
        return a.lower().strip("'\" ")

    def walk(f, depth=0):
        if str(f.Name).strip().lower() in skip:
            return
        try:
            items = f.Items
            items.Sort("[ReceivedTime]", True)
            for i in range(1, min(items.Count, 1500) + 1):
                it = items.Item(i)
                try:
                    when = it.ReceivedTime.replace(tzinfo=None)
                except Exception:
                    continue
                if when < cut:
                    break
                if when > now:
                    continue
                try:
                    if not str(it.MessageClass).startswith("IPM.Note"):
                        continue
                    subject = str(getattr(it, "Subject", "") or "")
                    body = str(getattr(it, "Body", "") or "")[:5000]
                    words = own_words(body)
                    hit = sorted({_canon(h) for h in want.findall(subject + " " + words)}) if want else []
                    if not hit:
                        continue
                    key = (str(getattr(it, "ConversationID", "")), when.strftime("%Y%m%d%H%M"), subject[:40])
                    if key in seen:
                        continue
                    seen.add(key)
                    sender = addr_of(it.Sender, getattr(it, "SenderEmailAddress", "")) if getattr(it, "Sender", None) \
                        else str(getattr(it, "SenderEmailAddress", "") or "").lower()
                    dir_ = "out" if sender == me or "opoku" in str(getattr(it, "SenderName", "")).lower() else "in"
                    to = []
                    if dir_ == "out":
                        for k in range(1, it.Recipients.Count + 1):
                            r = it.Recipients.Item(k)
                            if r.Type == 1:
                                to.append((str(getattr(r, "Name", "") or ""), addr_of(r.AddressEntry, getattr(r, "Address", ""))))
                    mans = sorted({x.upper().replace("MAN0", "MAN-0") for x in MAN.findall(words)})
                    out.append({"when": when, "dir": dir_, "refs": hit, "subject": subject[:160],
                                "kind": classify(dir_, subject, words, to, sender, teams, hauliers, mans),
                                "from_name": str(getattr(it, "SenderName", "") or ""), "from_addr": sender,
                                "to": to, "mans": mans})
                except Exception:
                    continue
        except Exception:
            pass
        if depth < 5:
            try:
                for j in range(1, f.Folders.Count + 1):
                    walk(f.Folders.Item(j), depth + 1)
            except Exception:
                pass
    for j in range(1, root.Folders.Count + 1):
        walk(root.Folders.Item(j))
    return out


def find_update(ns, now):
    """Today's Region 2 Updates from his managers: the newest with the order list in its own words - a colleague's
    reply-all on the thread ("thanks") is never the one answered. -> the Outlook item, or None."""
    import build_drafts as bd
    root = bd.dhl_store(ns)
    found = []

    def walk(f, depth=0):
        if str(f.Name).strip().lower() in ("deleted items", "sent items", "outbox", "drafts"):
            return
        try:
            items = f.Items
            items.Sort("[ReceivedTime]", True)
            for i in range(1, min(items.Count, 300) + 1):
                it = items.Item(i)
                try:
                    when = it.ReceivedTime.replace(tzinfo=None)
                except Exception:
                    continue
                if when.date() < now.date():
                    break
                if when > now:
                    continue
                if (SUBJECT.search(str(getattr(it, "Subject", "") or ""))
                        and "opoku" not in str(getattr(it, "SenderName", "")).lower()):
                    found.append((when, it))
        except Exception:
            pass
        if depth < 5:
            try:
                for j in range(1, f.Folders.Count + 1):
                    walk(f.Folders.Item(j), depth + 1)
            except Exception:
                pass
    for j in range(1, root.Folders.Count + 1):
        walk(root.Folders.Item(j))
    found.sort(key=lambda x: x[0], reverse=True)
    for _when, it in found:
        try:
            if any(p["kind"] in ("order", "week") for p in parse(own_part(str(it.Body or "")))):
                return it
        except Exception:
            continue
    return found[0][1] if found else None


def replied_at(ns, item):
    """When he has answered their email already (his Sent Items, after it came in) -> "HH:MM", or ""."""
    import build_drafts as bd
    try:
        root = bd.dhl_store(ns)
        after = item.ReceivedTime.replace(tzinfo=None)
        for j in range(1, root.Folders.Count + 1):
            f = root.Folders.Item(j)
            if str(f.Name).strip().lower() != "sent items":
                continue
            items = f.Items
            items.Sort("[SentOn]", True)
            for i in range(1, min(items.Count, 200) + 1):
                it = items.Item(i)
                when = it.SentOn.replace(tzinfo=None)
                if when < after:
                    break
                if SUBJECT.search(str(getattr(it, "Subject", "") or "")):
                    return when.strftime("%H:%M")
    except Exception:
        return ""
    return ""


def build(ns, now, item=None):
    """(the managers' email, parsed lines, plain text, HTML, summary) for today - or None when none came yet."""
    item = item or find_update(ns, now)
    if item is None:
        return None
    parsed = parse(own_part(str(item.Body or "")))
    refs = sorted({r for p in parsed for r in p.get("refs") or []})
    src = records()
    src["mails"] = read_mail(ns, refs, now) if refs else []
    greet = ("Hi " + _first(item.SenderName)).strip()
    text, body, summary = compose(parsed, src, now, greet)
    return item, parsed, text, body, summary


# ---------- the draft ----------
def _state():
    return _json(STATE, {})


def _save_state(d):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
    os.replace(tmp, STATE)


def make_draft(ns, now, force=False, auto=False):
    """Today's reply as a draft Reply All on their email - saved in Drafts, never sent. The 15:30 one (auto) isn't
    made when he has replied already, or has filed their email out of the Inbox (dealt with - his rule, 11/11).
    -> {"ok", "said", ...}"""
    import build_drafts as bd
    import send_order as so
    item = find_update(ns, now)
    if item is None:
        return {"ok": False, "said": "Today's Region 2 Updates hasn't come in yet - nothing to reply to."}
    key = hashlib.sha1(str(item.EntryID).encode()).hexdigest()[:12]
    st = _state()
    if st.get("key") == key and st.get("draft_at") and not force:
        return {"ok": True, "said": f"Today's reply was drafted already at {st['draft_at']} - it's in Drafts.",
                "already": True}
    if auto:
        where = _folder_of(item)
        if where and where.lower() != "inbox":
            _save_state({"key": key, "day": now.strftime("%Y-%m-%d"), "dealt": where, "from": str(item.SenderName),
                         "for": item.ReceivedTime.strftime("%d/%m %H:%M")})
            return {"ok": True, "said": f"Today's Region 2 Updates is filed in {where} - dealt with, no draft needed.",
                    "dealt": where}
        at = replied_at(ns, item)
        if at:
            _save_state({"key": key, "day": now.strftime("%Y-%m-%d"), "replied": at, "from": str(item.SenderName),
                         "for": item.ReceivedTime.strftime("%d/%m %H:%M")})
            return {"ok": True, "said": f"You replied to today's Region 2 Updates at {at} - no draft needed.",
                    "replied": at}
    _item, parsed, text, body, summary = build(ns, now, item)
    store = bd.dhl_store(ns).StoreID
    earlier = _earlier_draft(ns, store, st) if st.get("day") == now.strftime("%Y-%m-%d") else ""
    m = item.ReplyAll()
    acct = so.dhl_account(ns)
    if acct is not None:
        so.bind_account(m, acct)
    me = bd.DHL_SMTP.lower()
    for i in range(m.Recipients.Count, 0, -1):
        r = m.Recipients.Item(i)
        try:
            a = str(r.AddressEntry.GetExchangeUser().PrimarySmtpAddress or r.Address or "")
        except Exception:
            a = str(r.Address or "")
        if a.lower() == me:
            m.Recipients.Remove(i)
    with _PicturePrompt():
        m.Display(False)                               # his signature goes in, as on any reply he writes
        font = "font-family:Calibri,Arial,sans-serif;font-size:11pt"
        new, n = re.subn(r"(<body[^>]*>)", lambda mm: mm.group(1) + f'<div style="{font}">{body}</div>',
                         m.HTMLBody, count=1, flags=re.I)
        m.HTMLBody = new if n == 1 else f'<div style="{font}">{body}</div>' + m.HTMLBody
        m.Save()
        entry, top = str(m.EntryID), _top(m)
        m.Close(0)                                     # olSave - it stays in Drafts, nothing sent
    st = {"key": key, "for": item.ReceivedTime.strftime("%d/%m %H:%M"), "from": str(item.SenderName),
          "draft_at": now.strftime("%H:%M"), "summary": summary, "text": text[:6000], "day": now.strftime("%Y-%m-%d"),
          "entry": entry, "saved": _modified(ns, entry, store), "top": top}
    _save_state(st)
    first = _first(item.SenderName)
    return {"ok": True, "said": (f"Your reply to {first + chr(39) + 's' if first else 'the'} Region 2 Updates is in Drafts: "
                                 f"{summary['orders']} order(s), {summary['checks']} to check" + earlier + "."),
            "summary": summary}


class _PicturePrompt:
    """Outlook's "Automatic Picture Download" prompt (pictures in the email replied to) answered No while the draft is
    made - at 15:30 nobody is there to click it, and the draft would hang on it (it stopped sends here on 11/11)."""

    def __enter__(self):
        import threading
        self.stop = threading.Event()
        threading.Thread(target=self._watch, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.stop.wait(0.5)
        self.stop.set()
        return False

    def _watch(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        except Exception:
            return                                     # not Windows: nothing to answer
        while not self.stop.is_set():
            found = []

            def seen(h, _l):
                buf = ctypes.create_unicode_buffer(200)
                user32.GetWindowTextW(h, buf, 200)
                if buf.value == "Automatic Picture Download" and user32.IsWindowVisible(h):
                    found.append(h)
                return True
            user32.EnumWindows(proc(seen), 0)
            for h in found:
                no = user32.GetDlgItem(h, 7)           # IDNO
                if no:
                    user32.PostMessageW(no, 0x00F5, 0, 0)   # BM_CLICK
            self.stop.wait(0.5)


def _top(item):
    """A fingerprint of everything above the quoted email (whitespace aside) - any word of his changes it."""
    try:
        t = re.sub(r"\s+", " ", str(item.Body or "").split("\nFrom:", 1)[0]).strip()
        return hashlib.sha1(t.encode("utf-8")).hexdigest()[:16] if t else ""
    except Exception:
        return ""


def _folder_of(item):
    try:
        return str(item.Parent.Name).strip()
    except Exception:
        return ""


def _modified(ns, entry, store):
    try:
        return ns.GetItemFromID(entry, store).LastModificationTime.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _earlier_draft(ns, store, st):
    """Drafting it again: the earlier draft goes to Deleted Items if it's untouched; one he has written in, or sent,
    is left alone. -> what to tell him."""
    if not st.get("entry"):
        return ""
    try:
        old = ns.GetItemFromID(st["entry"], store)
        if str(old.Parent.Name).strip().lower() != "drafts" or old.Sent:
            return ""
        if ((st.get("saved") and _modified(ns, st["entry"], store) == st["saved"])
                or (st.get("top") and _top(old) == st["top"])):
            old.Delete()
            return " (the earlier draft is in Deleted Items)"
        return " - the earlier one may have your changes in it, so it's still in Drafts too"
    except Exception:
        return ""


def panel(now=None):
    """The Dashboard's card: today's draft - or, before it's made, when their email came in (from the inbox watch)."""
    now = now or datetime.now()
    st = _state()
    due = "%02d:%02d" % DRAFT_AT
    if st.get("day") == now.strftime("%Y-%m-%d"):
        return dict({k: st.get(k) for k in ("for", "from", "draft_at", "summary", "text", "replied", "dealt")},
                    due=due)
    out = {"due": due}
    try:
        import inbox_watch
        for i in inbox_watch.panel().get("items") or []:
            if str(i.get("why", "")).startswith("the day's Region 2") and str(i.get("received", "")).startswith(
                    now.strftime("%d/%m")):
                out.update(arrived=str(i["received"])[-5:], by=i.get("from"))
                if now.hour >= DRAFT_UNTIL:
                    out["late"] = True        # the 15:30 draft didn't happen and won't now
                break
    except Exception:
        pass
    return out


def main(argv):
    args = argv[1:]
    cmd = args[0] if args else "preview"
    now = datetime.now()
    if "--now" in args:
        now = datetime.fromisoformat(args[args.index("--now") + 1])
    if cmd == "preview":
        import build_drafts as bd
        got = build(bd.get_ns(), now)
        if got is None:
            print("No Region 2 Updates today yet.")
            return 0
        item, _parsed, text, _body, summary = got
        print(f"Their email: {item.SenderName}, {item.ReceivedTime:%d/%m %H:%M} - {item.Subject}")
        print(f"{summary['orders']} order line(s), {summary['checks']} to check\n")
        print(text)
        return 0
    if cmd in ("draft", "due"):
        if cmd == "due":
            if now.weekday() >= 5 or (now.hour, now.minute) < DRAFT_AT or now.hour >= DRAFT_UNTIL:
                print(json.dumps({"ok": True, "said": "Not time for the update reply."}))
                return 0
            if _state().get("day") == now.strftime("%Y-%m-%d"):
                print(json.dumps({"ok": True, "said": "Today's reply is drafted (or sent) already."}))
                return 0
        try:
            import build_drafts as bd
            out = make_draft(bd.get_ns(), now, force="--force" in args, auto=cmd == "due")
        except Exception as e:
            out = {"ok": False, "said": f"The reply couldn't be drafted ({type(e).__name__}: {e})."}
        print(json.dumps(out, default=str))
        return 0 if out["ok"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))
