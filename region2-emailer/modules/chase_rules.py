"""Should this contact be chased? - the rules, with no Outlook in sight.

Why this exists. The automatic chaser was switched off because it kept chasing
people who had already replied. Sent Items held 75 chasers from 29/06 to
02/10/2026; 34 of them went to someone who HAD replied - 33 of those replies
were sitting in Inbox/Regions/Region 2/Completed, and the old reply-finder
only ever looked at the top of the Inbox. It also took any email with the
order in the subject as "the reply" (a haulier's quote, our own SEND OUT
draft), chased partial answers and questions back, chased orders after their
delivery date (5033605 five times after it was delivered), and sent several
chasers within three minutes of a reply.

The rule that separates the 34 from the 37 fair chases on that history, with
none wrong either way:

    a REPLY is an inbound email that matches the ORDER (same thread as one of
    our emails about it, or the order number in its subject or own text) AND
    the PERSON (someone we emailed about the order, or someone from the
    contact's own company),

after ignoring our own mail, DHL colleagues and hauliers - except that
anyone we actually asked always counts, whatever their subject line or
address book entry says, and a colleague FORWARDING the contact's answer
counts as the answer. Any reply counts - a full answer, a partial one, a
question back, "I'll come back to you". Once an order+contact has replied it
is never chased automatically again (until Delali re-arms it).

When in doubt it does not chase: an email it cannot read, a stranger writing
about the order, an out-of-office, or the contact writing about something
else are HOLDs for Delali - but holds that expire, so one stray email does
not silence an order for good.

The adapter (chase_guard.py) turns mailbox items into the plain dicts used
here; tests/test_chase_rules.py exercises every rule.

Mail dict:   at (datetime), dir ("in"/"out"), from, from_name, to [..], cc [..],
             subject, conv, eid, folder, auto (bool), ndr (bool), draft (bool)
Record:      a tracker record (orders, to, emailed_at, last_emailed_at, chases,
             delivery_date, reply_at, ...) + to_smtp / conv_ids from the adapter
Decision:    {"action": SEND|WAIT|BLOCK|HOLD|STOP, "reason": str, "evidence": {...}|None}
"""
import re
from datetime import datetime, timedelta, date

SEND, WAIT, BLOCK, HOLD, STOP = "SEND", "WAIT", "BLOCK", "HOLD", "STOP"

MAX_CHASES = 2            # after the first ask: two follow-ups, then it is Delali's call
CHASE_AFTER_BDAYS = 2     # business days since the LAST email to them (ask or chase)
IN_TOUCH_BDAYS = 2        # "they emailed about something else" holds this long, then lapses
OOO_HOLD_BDAYS = 5        # an out-of-office holds this long, then chasing resumes
OOO_LINK_HOURS = 24       # an auto-reply counts only if it answers one of OUR emails
CLOCK_SLACK_MIN = 15      # mail stamped a little after our clock still counts
WORK_START, WORK_END = (8, 0), (16, 30)

ORDER_RE = re.compile(r"(?<!\d)([5-7]\d{6})(?!\d)")
EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# Everyone at Network Rail shares one domain, so "same company" means nothing
# there; webmail domains likewise.
SHARED_DOMAINS = ("networkrail.co.uk", "dhl.com", "gmail.com", "googlemail.com", "outlook.com",
                  "hotmail.com", "hotmail.co.uk", "live.co.uk", "yahoo.com", "yahoo.co.uk",
                  "aol.com", "icloud.com", "btinternet.com", "sky.com")
# "<order> Delivery" is the ring-round subject: replies to it are hauliers.
RING_ROUND_RE = re.compile(r"^(?:(?:re|fw|fwd)\s*:\s*)*(?:[5-7]\d{6}(?:\s*/\s*[5-7]\d{6})*)\s+delivery\b",
                           re.I)
FORWARD_RE = re.compile(r"^\s*(?:(?:re|fw|fwd)\s*:\s*)*(?:fw|fwd)\s*:", re.I)
QUOTE_START = re.compile(r"\s*(From:|Sent:|-----Original|On .* wrote:|_{6,})")

# "This order has been arranged with Lawsons. Here is the ref number MAN-01563625"
# or a reply that just says "booked in". Not "I'll let you know when it's
# booked in" (a promise - it stopped a chase on 5033678), not "so I can get
# this booked in" (an ask), not "has this been booked in?" (a question).
BOOKED_STRONG = re.compile(r"(?i)has been arranged with|\bMAN-?\d{6,}|\b\d{6}-MAN-\d+")
BOOKED_SOFT = re.compile(r"(?i)\bbooked\s+in\b")
NOT_YET = re.compile(r"(?i)\b(when|once|until|till|if|will|let you know|not yet|not been|"
                     r"isn'?t|hasn'?t|haven'?t|can|could|so i|to get|to be|need|able|"
                     r"get (?:this|it|them|these))\b[^.\n]{0,40}$")


def booked_in(text):
    """True for a booking; False for a promise, an ask, a question or a 'not yet'."""
    t = str(text or "")
    if BOOKED_STRONG.search(t):
        return True
    for m in BOOKED_SOFT.finditer(t):
        before = t[max(0, m.start() - 50):m.start()]
        after = t[m.end():m.end() + 25].split("\n", 1)[0]
        if not NOT_YET.search(before) and "?" not in after:
            return True
    return False


# ---------- small helpers ----------
def emails_in(s):
    return [e.lower().strip(".") for e in EMAIL_RE.findall(str(s or ""))]


def domain(addr):
    return str(addr or "").lower().rsplit("@", 1)[-1]


def shared(dom):
    return any(dom == d or dom.endswith("." + d) for d in SHARED_DOMAINS)


def orders_of(rec):
    """The order numbers a record is about (7-digit only - never a product
    code like SLB3007 or a company number in someone's signature)."""
    out = []
    for o in rec.get("orders") or []:
        out += ORDER_RE.findall(str(o))
    return sorted(set(out))


def mentions(text, orders):
    t = str(text or "")
    return any(re.search(r"(?<!\d)" + re.escape(o) + r"(?!\d)", t) for o in orders)


def own_text(body):
    """The part of an email above the quoted original."""
    out = []
    for line in str(body or "").splitlines():
        if QUOTE_START.match(line) and any(x.strip() for x in out):
            break
        out.append(line)
    return "\n".join(out)


def forwarded_from(body):
    """The address on the first quoted 'From:' line of a forward - whose
    message it is. '' if none."""
    for line in str(body or "").splitlines():
        if re.match(r"\s*From:", line):
            got = emails_in(line)
            if got:
                return got[0]
    return ""


def parse_dt(s):
    if isinstance(s, datetime):
        return s
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s).strip(), f)
        except (ValueError, TypeError):
            pass
    return None


def parse_day(s):
    d = parse_dt(s)
    return d.date() if d else None


def is_working_day(d, holidays=()):
    return d.weekday() < 5 and d not in holidays


def business_days_between(start, end, holidays=()):
    """Whole working days from `start` to `end` (start's own day not counted)."""
    if start is None or end is None:
        return 0
    n, d = 0, start.date() if isinstance(start, datetime) else start
    stop = end.date() if isinstance(end, datetime) else end
    while d < stop:
        d += timedelta(days=1)
        if is_working_day(d, holidays):
            n += 1
    return n


def in_working_hours(now, holidays=()):
    return (is_working_day(now.date(), holidays)
            and WORK_START <= (now.hour, now.minute) < WORK_END)


# ---------- who counts ----------
def is_ours(m, ctx):
    """Our own mail: from us, or a draft (SEND OUT briefs are drafts)."""
    frm = str(m.get("from") or "").lower()
    return bool(m.get("draft")) or not frm or frm in ctx.get("me", ())


def is_ignored(m, ctx):
    """Mail that is not the contact replying: us, DHL colleagues, hauliers,
    NR order-desk notices. Only applied to people we did NOT ask."""
    frm = str(m.get("from") or "").lower()
    name = str(m.get("from_name") or "")
    subj = str(m.get("subject") or "")
    if is_ours(m, ctx):
        return "ours"
    if domain(frm) in ctx.get("internal_domains", ("dhl.com",)) or "(DHL" in name \
            or name.strip().lower() in ctx.get("team_names", ()):
        return "DHL colleague"
    if frm in ctx.get("haulier_addresses", ()) or domain(frm) in ctx.get("haulier_domains", ()):
        return "haulier"
    if RING_ROUND_RE.match(subj) or "(#DEO-" in subj:
        return "haulier"
    if re.sub(r"^(?:\s*(?:fw|fwd|re)\s*:\s*)*", "", subj, flags=re.I).lower().startswith(
            "nwr order received"):
        return "order desk"
    return None


def contacts_of(rec, ctx):
    """External addresses we asked about this record. Supplier collection
    records hold Outlook display names ('Anderton Rail') in `to`; the adapter
    adds the resolved addresses of the original email as `to_smtp`."""
    internal = tuple(ctx.get("internal_domains", ("dhl.com",)))
    out = []
    for a in (emails_in(rec.get("to")) + emails_in(rec.get("cc"))
              + [str(x).lower() for x in rec.get("to_smtp") or [] if "@" in str(x)]):
        if a not in ctx.get("me", ()) and domain(a) not in internal and a not in out:
            out.append(a)
    return out


def _haulier_asked_since(orders, asked, ctx):
    """A haulier from the directory was asked to cover one of these orders
    after our first ask - so the job's details are in hand. Accepts the old
    set-of-orders form too."""
    ho = ctx.get("haulier_orders") or {}
    if isinstance(ho, (set, frozenset, list, tuple)):
        return bool(set(orders) & set(ho))
    for o in orders:
        for t in ho.get(o, []):
            t = parse_dt(t)
            if t and t >= asked:
                return True
    return False


# ---------- the decision ----------
def _frame(rec, mails, ctx, now):
    """Who we asked, when we first asked, and which threads are ours - the
    frame every inbound email is judged against. None if the record cannot
    be judged (no contact / no order number)."""
    orders = orders_of(rec)
    contacts = contacts_of(rec, ctx)
    if not contacts or not orders:
        return None
    # replied once = never auto-chased again, unless Delali re-armed it - and
    # then only mail AFTER the re-arm counts
    rearmed, remembered = None, None
    for o in orders:
        for c in contacts:
            st = (ctx.get("state") or {}).get(f"{o}|{c}")
            if not st:
                continue
            ra = parse_dt(st.get("rearmed_at"))
            if ra:
                rearmed = max(rearmed, ra) if rearmed else ra
            elif st.get("blocked") and remembered is None:
                remembered = st
    if rearmed and remembered and (parse_dt(remembered.get("at")) or now) <= rearmed:
        remembered = None            # a re-arm of a sibling order on the same record covers it

    def about_order(m):
        return mentions(m.get("subject"), orders) or m.get("conv") in _rec_convs(rec)

    def external(addrs):
        return [a for a in addrs if a not in ctx.get("me", ())
                and not is_ignored({"from": a}, ctx)]

    out_all = [m for m in mails if m["dir"] == "out" and m["at"] <= now and about_order(m)]
    # Emails to the people we are chasing: the chase count and the "last
    # emailed" clock.
    ours = [m for m in out_all if set(m.get("to", []) + m.get("cc", [])) & set(contacts)]
    # The window starts at the FIRST ask about these orders to ANY outside
    # person - the record may hold the newest by-hand email, or the extract's
    # contact while someone else was asked first (5033605, 13/08 Ernesta).
    asked = parse_dt(rec.get("emailed_at")) or now
    anchors = [m for m in out_all if external(m.get("to", []) + m.get("cc", []))]
    if anchors:
        asked = min(asked, min(m["at"] for m in anchors))
    if rearmed:
        asked = max(asked, rearmed)
        ours = [m for m in ours if m["at"] >= rearmed]
        anchors = [m for m in anchors if m["at"] >= rearmed]
    on_thread = set(contacts)
    for m in anchors:
        on_thread |= set(external(m.get("to", []) + m.get("cc", [])))
    # When THESE contacts were first asked. Someone else's answer before then is
    # often a redirect - "speak to Simon" (5033840), "send it to Chris"
    # (6055657) - and the new contact still owes a reply: hold, don't block.
    asked_contacts = min([m["at"] for m in ours] + [parse_dt(rec.get("emailed_at")) or now])
    return {"orders": orders, "contacts": contacts, "asked": asked, "ours": ours,
            "asked_contacts": max(asked, asked_contacts) if rearmed else asked_contacts,
            "threads": {m.get("conv") for m in anchors if m.get("conv")} | _rec_convs(rec),
            "on_thread": on_thread, "remembered": remembered,
            "contact_domains": {domain(c) for c in contacts if not shared(domain(c))}}


def _inbound(fr, mails, ctx, text_of, now):
    """Sort every inbound email since the ask into replies / out-of-office /
    in-touch-about-something-else / someone-else-wrote / unreadable / bounces.

    text_of(eid) returns the email's text, or None when it could not be read -
    an unreadable email that might be the reply is a HOLD, never a 'no'."""
    orders, contacts = fr["orders"], fr["contacts"]
    hol = ctx.get("holidays", ())
    upper = now + timedelta(minutes=ctx.get("clock_slack_min", CLOCK_SLACK_MIN))
    last_out = max([fr["asked"]] + [m["at"] for m in fr["ours"]])
    out = {k: [] for k in ("replies", "ooo", "in_touch", "others", "unreadable", "bounced")}

    def text(m):
        t = text_of(m["eid"])
        if t is None:
            out["unreadable"].append((m, ["could not read this email"]))
        return t

    for m in mails:
        if m["dir"] != "in" or not (fr["asked"] < m["at"] <= upper):
            continue
        on_thr = bool(m.get("conv")) and m["conv"] in fr["threads"]
        in_subj = mentions(m.get("subject"), orders)
        if m.get("ndr"):
            # only a real non-delivery report, and only for someone we asked
            if in_subj or on_thr:
                t = text(m) or ""
                if any(c in (str(m.get("subject", "")) + " " + t).lower() for c in contacts):
                    out["bounced"].append((m, ["bounce"]))
            continue
        if m.get("draft"):
            continue                       # our own drafts (SEND OUT briefs) - never a reply
        frm = m["from"]
        asked_them = frm in fr["on_thread"]
        person = asked_them or (domain(frm) in fr["contact_domains"])
        if not asked_them:
            ign = is_ignored(m, ctx)
            if ign:
                # A colleague (or Delali's NR alias) forwarding the contact's
                # own message about this order IS the reply arriving.
                if (ign in ("DHL colleague", "ours") and FORWARD_RE.match(str(m.get("subject", "")))
                        and (on_thr or in_subj)):
                    t = text(m)
                    if t is not None:
                        src = forwarded_from(t)
                        if src and (src in fr["on_thread"] or domain(src) in fr["contact_domains"]):
                            out["replies"].append((m, ["forwarded by a colleague"]))
                        # anything else a colleague forwards (order-desk mail,
                        # an NR notice) is not the contact - ignored, as before
                continue
        if not person:
            # Someone we never emailed, writing on our thread or with the order
            # in the subject - a colleague covering, say. Not proof the contact
            # answered, but never a reason to chase blind: hold for Delali.
            if not m.get("auto") and (on_thr or in_subj):
                out["others"].append((m, ["someone else wrote about this order"]))
            continue
        why = []
        if on_thr:
            why.append("same thread")
        if in_subj:
            why.append("order in subject")
        if not why:
            t = text(m)
            if t is None:
                continue                                  # already held as unreadable
            if mentions(own_text(t), orders):
                why.append("order in their text")
        if m.get("auto"):
            answers_us = any(timedelta(0) <= m["at"] - o["at"] <= timedelta(hours=OOO_LINK_HOURS)
                             for o in fr["ours"])
            if (why or (frm in contacts and answers_us)) \
                    and business_days_between(m["at"], now, hol) <= OOO_HOLD_BDAYS:
                out["ooo"].append((m, why or ["out of office"]))
            continue
        if why:
            if (frm not in contacts and domain(frm) not in fr["contact_domains"]
                    and m["at"] <= fr["asked_contacts"]):
                out["others"].append((m, why + [f"before you asked {', '.join(contacts)}"]))
            else:
                out["replies"].append((m, why))
        elif (frm in contacts or asked_them) and m["at"] > last_out \
                and business_days_between(m["at"], now, hol) < IN_TOUCH_BDAYS:
            out["in_touch"].append((m, ["emailed you since, about something else"]))
    for k in out:
        out[k].sort(key=lambda x: x[0]["at"])
    return out


def reply_mails(rec, mails, ctx, text_of, now):
    """(replies, out_of_office) for a record, oldest first, as mail dicts -
    for the reply check that parses the answer and drafts the send-off brief.
    The same rules as the chaser, so the two can never disagree about whether
    someone has replied. None if the rules cannot judge the record (the caller
    falls back to the old search)."""
    fr = _frame(rec, mails, ctx, now)
    if fr is None:
        return None
    ib = _inbound(fr, mails, ctx, text_of, now)
    return [m for m, _ in ib["replies"]], [m for m, _ in ib["ooo"]]


def assess(rec, mails, ctx, text_of, now):
    """Decide what to do about one tracker record.

    mails    every indexed mail (in and out) - only those up to `now` count
    ctx      me, internal_domains, team_names, haulier_addresses,
             haulier_domains, haulier_orders, state, holidays
    text_of  eid -> the email's text, or None if it could not be read
             (fetched lazily; only asked for when the cheaper signals cannot decide)
    """
    if rec.get("reply_at"):
        # the reply check already found and parsed their reply - perhaps one
        # older than the mailbox window the chaser reads
        return _d(BLOCK, f"replied (on the tracker since {rec['reply_at']})")
    if not contacts_of(rec, ctx):
        return _d(STOP, "no external contact on this order - nobody to chase")
    fr = _frame(rec, mails, ctx, now)
    if fr is None:
        return _d(HOLD, "no order number on the record - cannot check for a reply safely")
    if fr["remembered"]:
        st = fr["remembered"]
        return _d(BLOCK, f"replied earlier ({st.get('why', 'reply on record')})", st.get("evidence"))

    # Stop: the job no longer needs details from them.
    deliv = parse_day(rec.get("delivery_date"))
    if deliv and deliv <= now.date():
        return _d(STOP, f"delivery date {deliv:%d/%m/%Y} has been reached")
    if _haulier_asked_since(fr["orders"], fr["asked"], ctx):
        return _d(STOP, "a haulier has already been asked to cover it - details are in hand")
    for m in fr["ours"]:
        if m["at"] < fr["asked"]:
            continue
        # your own words only, and about THIS order - a quoted "booked in" or
        # another order's MAN ref further down the thread is not you booking it
        t = text_of(m["eid"])
        mine = own_text(t)
        subject_orders = set(ORDER_RE.findall(str(m.get("subject", ""))))
        if booked_in(mine) and (mentions(mine, fr["orders"]) or subject_orders <= set(fr["orders"])):
            return _d(STOP, "you have booked it (booking email in Sent Items)", _ev(m, ["booked"]))

    ib = _inbound(fr, mails, ctx, text_of, now)
    if ib["replies"]:
        m, why = ib["replies"][0]
        return _d(BLOCK, f"replied {m['at']:%d/%m %H:%M} ({', '.join(why)}) - {m['from']}", _ev(m, why))
    if ib["bounced"]:
        m, why = ib["bounced"][0]
        return _d(STOP, "your ask bounced - the address needs checking", _ev(m, why))
    if ib["unreadable"]:
        m, why = ib["unreadable"][0]
        return _d(HOLD, f"an email from {m['from'] or 'someone'} could not be read - check it "
                        "before chasing", _ev(m, why))
    if ib["others"]:
        m, why = ib["others"][0]
        return _d(HOLD, f"{m['from']} wrote about this order - check whether it answers it", _ev(m, why))
    if ib["ooo"]:
        m, why = ib["ooo"][-1]
        return _d(HOLD, "out of office - check their auto-reply for a return date or cover contact "
                        f"(chasing resumes after {OOO_HOLD_BDAYS} business days)", _ev(m, why))
    if ib["in_touch"]:
        m, why = ib["in_touch"][-1]
        return _d(HOLD, "they have emailed you since you last asked (about something else?) - "
                        f"check before chasing (lapses after {IN_TOUCH_BDAYS} business days)",
                  _ev(m, why))

    ours = fr["ours"]
    chased = max(int(rec.get("chases") or 0), max(0, len(ours) - 1))
    if chased >= MAX_CHASES:
        return _d(STOP, f"already chased {chased} time(s) - over to you")
    last = max([fr["asked"]] + [m["at"] for m in ours]
               + [x for x in (parse_dt(rec.get("last_emailed_at")),
                              parse_dt(rec.get("last_chased_at"))) if x])
    bdays = business_days_between(last, now, ctx.get("holidays", ()))
    if bdays < CHASE_AFTER_BDAYS:
        return _d(WAIT, f"last emailed {last:%d/%m %H:%M} - {bdays} business day(s) ago")
    return _d(SEND, f"no reply since {fr['asked']:%d/%m %H:%M} ({bdays} business days) - "
                    f"chase #{chased + 1}")


def _rec_convs(rec):
    return {c for c in (rec.get("conv_ids") or []) if c}


def _ev(m, why):
    return {"at": m["at"].strftime("%d/%m %H:%M"), "ts": m["at"].strftime("%Y-%m-%d %H:%M"),
            "from": m.get("from", ""),
            "subject": str(m.get("subject", ""))[:90], "folder": m.get("folder", ""),
            "why": list(why), "eid": m.get("eid", "")}


def _d(action, reason, evidence=None):
    return {"action": action, "reason": reason, "evidence": evidence}


def one_per_contact(decisions, ctx=None):
    """Of the records due a chase, send only ONE email per contact per run -
    the soonest delivery first. The rest wait for the next run. Andrew
    Gilliver got two chasers in the same second, one of them about an order
    he had already answered. Any shared address counts as the same contact."""
    ctx = ctx or {}
    picked, seen = [], set()
    for rec, dec in sorted(decisions, key=lambda x: (parse_day(x[0].get("delivery_date"))
                                                     or date.max)):
        if dec["action"] != SEND:
            continue
        addrs = set(contacts_of(rec, ctx)) or set(emails_in(rec.get("to")))
        if addrs & seen:
            dec["action"], dec["reason"] = WAIT, "one chaser per contact per run - next run"
            continue
        seen |= addrs
        picked.append((rec, dec))
    return picked
