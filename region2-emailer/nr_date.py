"""
The Network Rail team email when a site asks for a different delivery date than the one we offered - and since 25/11
all of it by itself (his words: "The network rail date changes thing, could you also make that automatic? I don't want
to be manually doing that.").

His rule, as he put it on 25/11: "if sleepers are being collected before the availability date, we have to ask. If it's
after the availability date, then it won't be a problem. We're just notifying them they'll just be collected later than
usual. That's the basic rule of the whole thing." (It was by delivery days, 09/11 - which went wrong once the desk had
moved an order itself: the day the site asked for was judged against our own later day, not the stock's.)
- The AVAILABILITY date is the one the order came down with: the extract's collection date (collections[].date on the
  record). Our own moves never touch it - they change the delivery date only.
- The COLLECTION is worked out from the site's day and time by his collection rules (ctms_run_plan.collection_days):
  near enough with the yard open in time, the same day; a morning delivery, the day before; never at the weekend.
- Collected BEFORE the availability date: the Network Rail team that sent the order down is asked whether that is
  allowed and whether the stock will be ready - and nothing moves, and CTMS gets no collection before it, until they
  say yes. An order went wrong on 09/11 because it was brought forward without anyone confirming the goods were
  ready (the supplier turned the driver away).
- Collected AFTER the availability date, in a later week (week commencing, Monday-based): the team is told it will be
  collected later than usual - no permission, just so nobody chases a collection that didn't happen. Collected ON the
  availability date, or later in its same week: nothing to say, it just moves (his 09/11 rule, kept: "Yes, just a
  move", 25/11).
- Not sure (no firm time from the site and the morning/afternoon decides it, no availability date on the order,
  several pick-ups): drafted and held for him, never sent by itself.

What lives on the tracker record, as r["nr_date"] (the dashboard shows it on the order's panel and its own card):
    kind      "earlier" (collected before availability: ask) | "later" (collected after it: tell)
    offered   the day the order is on (dd/mm/yyyy)   asked   the day the site wants
    collect   the day it would be collected          available   the stock's availability date
    his       set when the desk leaves the email to him ("time", "availability", "asked_before") - never sent by itself
    state     "to_send"  drafted, going by itself in working hours (or by his Send on the dashboard)
              "sent"     gone to Network Rail (for "earlier": waiting for their answer)
              "allowed" / "not_allowed"   their answer (earlier only) - read off their reply, or pressed by him
              "dismissed"  he said no email is needed
    team, to, cc, subject, message      the email, which he can edit before Send
    reply_eid  the site's own email, forwarded underneath so the team sees the whole trail
    sent_by    "auto" (the desk sent it) | "you" (his Send) | "by hand" (found in Sent Items, sent outside the desk)
    answer     the reply the desk went by: {at, from, who, said, eid, verdict}
    answered_by  "auto" | "you"
    held       why the desk stopped and left it to him: {why, at, and the email's from, who, said, eid, subject}
    tell_site  Network Rail said no, and the site still thinks it is the earlier day: his to tell them ("Told them")
    seen       emails he looked at on the card and waved through - never held for again

The automatic part (`auto`: the home agent's timer, and straight after each reply check):
    to_send   goes by itself in working hours (Mon-Fri 08:00-16:30, bank holidays out), the same email his Send sends -
              unless Sent Items shows it went already (then it is marked sent, "by hand"), nobody is known to send it
              to, or the day the site asked for has gone: those are held for him
    sent      Network Rail's reply is read off the whole mailbox: on our email's own thread, from the team (one of the
              addresses it went to, or anyone at Network Rail but the site). A clear yes moves the order, and the CTMS
              to-do then types the new day; a clear no keeps the day we offered. Anything else - a question back,
              "I'll check", a hedge ("should be fine"), another day named, someone else answering, a bounce - is held
              for him with their words. Never a guessed yes.
It follows the Toolkit switch (toolkit.off: nothing at all), the Auto follow-ups switch (auto_chase.enabled - off:
nothing automatic, the card's buttons work as before; SHADOW: it says what it would do and changes nothing) and its own
nr_date.paused. Never copies DHL Road. No em dashes in anything written. The site is never emailed from here - his
rule doesn't say to - so a no stays on the card until he has told them.

    python nr_date.py auto [--dry]           the timer's run (--dry: say what it would do, change nothing)
    python nr_date.py pause | resume         this automation alone off / on again (the card's buttons still work)
    python nr_date.py send <record id> <json file with to/cc/subject/message>
    python nr_date.py answer <record id> yes|no
    python nr_date.py dismiss <record id>
    python nr_date.py seen <record id>       the held email looked at: keep waiting for a clearer one
    python nr_date.py told <record id>       the site has been told Network Rail's no
"""
import copy
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
TEAMS_FILE = os.path.join(HERE, "_nr_teams.json")   # home-only additions (people's own addresses), gitignored
PAUSE_FLAG = os.path.join(HERE, "nr_date.paused")    # this automation alone switched off
CHASE_FLAG = os.path.join(HERE, "auto_chase.enabled")  # the dashboard's Auto follow-ups switch: LIVE / SHADOW / gone

# The team that sends each kind of material down to us, from the real threads in the mailbox. Team mailboxes only
# here (the repo is public); a named person who is always copied goes in _nr_teams.json as {"sleepers": {"add":
# ["..."]}}. S&C and anything else has no team on the list: the email is drafted with nobody in To and the card
# asks him who it goes to, rather than guessing.
TEAMS = {
    "sleepers": {"name": "SCO Sleepers & Troughing",
                 "to": ["SCOSleepers&Troughing@networkrail.co.uk", "SleeperContractManagementTeam@networkrail.co.uk"]},
    "rails": {"name": "Steel Materials", "to": ["SteelMaterials@networkrail.co.uk"]},
    "ballast": {"name": "Track Aggregates", "to": ["Track.Aggregates@networkrail.co.uk"]},
}
KIND_OF = (
    (re.compile(r"sleeper|bearer|trough", re.I), "sleepers"),
    (re.compile(r"\brails?\b", re.I), "rails"),
    (re.compile(r"ballast|aggregate|chipping|granite|stone", re.I), "ballast"),
)
NEVER = re.compile(r"dhlroad@", re.I)      # his rule: never copy DHL Road on these
NR_DOMAIN = "networkrail.co.uk"

OPEN = ("to_send", "sent")                 # still something for him (or Network Rail) to do


def _d(s):
    try:
        return datetime.strptime(str(s or "").strip(), "%d/%m/%Y")
    except ValueError:
        return None


def week_of(day):
    """The Monday of the week a day is in (the week commencing)."""
    return (day - timedelta(days=day.weekday())).date()


def classify(offered, asked):
    """"earlier" when the site asks before the day we offered, "later" when it asks for a day in a later week,
    None otherwise (the same day, a later day in the same week, or either not a date)."""
    o, a = _d(offered), _d(asked)
    if not (o and a):
        return None
    if a < o:
        return "earlier"
    if week_of(a) > week_of(o):
        return "later"
    return None


def _material_kind(r):
    text = " ".join([str(r.get("materials") or "")] + [str(x) for x in r.get("product_types") or []])
    if re.search(r"s&c|switch|crossing", text, re.I):
        return None
    for rx, k in KIND_OF:
        if rx.search(text):
            return k
    return None


def _extra():
    try:
        with open(TEAMS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def team_for(r):
    """{"key", "name", "to": [...]} for the order's Network Rail team, or None when nobody is known."""
    k = _material_kind(r)
    if not k:
        return None
    t = TEAMS[k]
    to = list(t["to"]) + [a for a in (_extra().get(k) or {}).get("add") or [] if a not in t["to"]]
    return {"key": k, "name": t["name"], "to": [a for a in to if not NEVER.search(a)]}


def _addrs(v):
    parts = v if isinstance(v, (list, tuple)) else re.split(r"[;,]", str(v or ""))
    return "; ".join(p.strip() for p in parts if str(p).strip() and not NEVER.search(str(p)))


def _long(day):
    d = _d(day)
    return d.strftime("%A %d/%m/%Y") if d else str(day or "")


def _short(day):
    d = _d(day)
    return d.strftime("%d/%m") if d else str(day or "")


def _what(r):
    where = ", ".join(x for x in [r.get("worksite") or r.get("site"), r.get("postcode")] if x)
    bits = [str(r.get("materials") or "").strip(), ("to " + where) if where else ""]
    return " ".join(b for b in bits if b)


def draft(r, kind, offered, asked, plan=None):
    """(subject, message) - his plain wording, no em dashes; the signature is added when it is sent. With `plan`
    (collect_plan: the collection day and the stock's availability) it says what his 25/11 rule turns on - when it
    would be collected against when it is available; without one, the delivery days, as before."""
    orders = " / ".join(r.get("orders") or [])
    what = _what(r)
    about = f"order {orders}" + (f" ({what})" if what else "")
    plan = plan or {}
    collect, avail = plan.get("collect"), plan.get("available")
    if collect and avail and kind == "earlier":
        subject = (f"{orders} - collection before the availability date ({_short(collect)}, available "
                   f"{_short(avail)})")
        keep = (f"It stays on {_short(offered)} until I hear back from you." if offered != asked else
                "I will not book it in until I hear back from you.")
        message = "\n".join([
            "Hi all,", "",
            f"The site has come back on {about} asking for delivery on {_long(asked)}. To deliver then it would be "
            f"collected on {_long(collect)}, before the {_long(avail)} it was sent down as available from.", "",
            f"Please could you confirm whether collecting it on {_short(collect)} is allowed, and whether the stock "
            f"will be ready for collection in time? {keep}", "",
            "The site's email is below."])
        return subject, message
    if collect and avail and kind == "later":
        subject = f"{orders} - collected later than usual ({_short(collect)}, available {_short(avail)})"
        message = "\n".join([
            "Hi all,", "",
            f"Just to let you know, the site on {about} has asked for delivery on {_long(asked)}, so it will be "
            f"collected on {_long(collect)}, later than the {_long(avail)} it was sent down as available from. "
            f"Nothing is needed from you - this is so nobody chases a collection on {_short(avail)} that didn't "
            "happen.", "",
            "The site's email is below."])
        return subject, message
    if kind == "earlier":
        subject = f"{orders} - site asking for an earlier delivery ({_short(asked)} instead of {_short(offered)})"
        message = "\n".join([
            "Hi all,", "",
            f"The site has come back on {about} asking for delivery on {_long(asked)}. "
            f"We have it down as available from {_long(offered)}, so this is earlier than the date it was sent "
            "down as.", "",
            f"Please could you confirm whether delivering on {_short(asked)} is allowed, and whether the stock will "
            "be ready for collection in time? I will keep the order on "
            f"{_short(offered)} until I hear back from you.", "",
            "The site's email is below."])
    else:
        subject = f"{orders} - delivery moved to {_short(asked)} (was {_short(offered)})"
        message = "\n".join([
            "Hi all,", "",
            f"Just to let you know, the site on {about} has asked for delivery on {_long(asked)} instead of "
            f"{_long(offered)}, when it was available. The delivery is now planned for {_short(asked)}, so it "
            f"will not be going on {_short(offered)}.", "",
            "The site's email is below."])
    return subject, message


def available(r):
    """(day, why) - the day the stock is available from: the extract's collection date the order came down with
    (collections[].date). Our own moves never touch it, they change the delivery date only. None, with why, when the
    record has none, or pick-ups on different days."""
    days = sorted({str(c.get("date") or "").strip() for c in (r or {}).get("collections") or [] if _d(c.get("date"))},
                  key=_d)
    if not days:
        return None, "no availability date on the order (no collection date came down with it)"
    if len(days) > 1:
        return None, f"pick-ups on different days ({', '.join(_short(x) for x in days)})"
    return days[0], ""


def _start(r):
    """The site's delivery start (HH:MM) off the parsed reply, when it is firm - "" when it isn't."""
    t = ((r or {}).get("details") or {}).get("time")
    if isinstance(t, dict) and t.get("confidence") in ("high", None):
        m = re.match(r"\s*(\d{1,2}):(\d{2})", str(t.get("earliest") or ""))
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def collect_plan(r, day, start=None, run=None):
    """His 25/11 rule on the site's day: when it would be collected against when the stock is available.
        {"verdict": "ask" | "tell" | "fine" | "undecided", "collect", "available", "why", "undecided": reason}
    ask: collected before the availability date. tell: after it, in a later week (week commencing). fine: on it, or
    later in its same week - just a move (his 09/11 rule, kept on his 25/11 "Yes, just a move"). undecided: can't be
    told - no availability date, the collection can't be worked out, or the site's time isn't firm and morning or
    afternoon decides it (a morning delivery goes the day before, an afternoon one may go the same day)."""
    import ctms_run_plan as P
    avail, why = available(r)
    start = _start(r) if start is None else start
    if not avail:
        return {"verdict": "undecided", "collect": "", "available": "", "why": why, "undecided": "availability"}
    days = P.collection_days(r, day, start, run=run)
    if not days:
        return {"verdict": "undecided", "collect": "", "available": avail, "undecided": "availability",
                "why": "the collection day can't be worked out from the record (several pick-ups?)"}
    a = _d(avail)
    after = [(c, how) for c, how in days if _d(c) >= a]
    if not after:
        c, how = days[0]
        return {"verdict": "ask", "collect": c, "available": avail,
                "why": f"collected {_short(c)} ({how}), before the {_short(avail)} it is available from"}
    if len(after) < len(days) and not start:
        c = days[0][0]
        return {"verdict": "undecided", "collect": c, "available": avail, "undecided": "time",
                "why": f"the site's time isn't firm: a morning delivery is collected {_short(c)}, before the "
                       f"{_short(avail)} it is available from - an afternoon one could go {_short(after[0][0])}"}
    c, how = min(after, key=lambda x: _d(x[0]))
    if _d(c) == a:
        return {"verdict": "fine", "collect": c, "available": avail,
                "why": f"collected {_short(c)}, the day it is available from"}
    if week_of(_d(c)) == week_of(a):
        return {"verdict": "fine", "collect": c, "available": avail,
                "why": f"collected {_short(c)}, later than the {_short(avail)} it is available from but the same week "
                       "- just a move"}
    return {"verdict": "tell", "collect": c, "available": avail,
            "why": f"collected {_short(c)} ({how}), later than the {_short(avail)} it is available from"}


def on_new_date(d, r, new, why, reply_eid=None):
    """The one place a site's date (by reply, by his confirm of a parsed date, by phone) lands on a delivery record -
    judged by his 25/11 rule (collect_plan). Collected before the stock's availability: the order stays put and the
    "is this allowed" email is drafted. After it: the order moves and the "collected later than usual" heads-up is
    drafted. On it: it just moves. Not sure: drafted, held for him. Returns True when the order's date changed. `d` is
    the loaded tracker (the caller saves it)."""
    import tracker
    new = str(new or "").strip()
    if not _d(new) or r.get("kind", "delivery") != "delivery":
        return tracker.move_date(d, r, new, why) if _d(new) else False
    offered = str(r.get("delivery_date") or "").strip()
    cur = r.get("nr_date") or {}
    if cur.get("asked") == new and cur.get("kind") == "earlier":
        if cur.get("state") == "allowed":
            return tracker.move_date(d, r, new, why)
        if cur.get("state") in ("sent", "not_allowed") or (cur.get("state") == "to_send" and not cur.get("his")):
            return False        # already asked (or answered) for this very day: nothing new
    plan = collect_plan(r, new)
    his, held_why = "", ""
    if plan["verdict"] == "undecided" and plan.get("undecided") == "availability":
        # no availability date to judge it by: the delivery days, as before 25/11 - and it is his to send or not
        kind = classify(offered, new)
        his, held_why = "availability", plan["why"].capitalize() + " - check it before anything goes to Network Rail"
    elif plan["verdict"] == "undecided":
        kind = "earlier"
        his, held_why = "time", plan["why"].capitalize() + " - ask them, or press No email needed"
    else:
        kind = {"ask": "earlier", "tell": "later", "fine": None}[plan["verdict"]]
    now = tracker._now()
    if cur.get("state") == "to_send" and (cur.get("asked") != new or (kind is None and cur.get("his"))):
        # a draft for another day, or one held on the site's time that turns out not to be needed: never sent now
        cur.update(state="dismissed", superseded_by=new, answered_at=now)
        cur.pop("held", None)
    if cur.get("state") == "sent" and cur.get("asked") != new and kind is None:
        # Network Rail were emailed about another day, and the site's day now needs nothing from them: no answer of
        # theirs moves anything now - he lets them know it's off
        cur.update(state="dismissed", superseded_by=new, answered_at=now,
                   held={"why": f"The site now wants {_short(new)}, which needs nothing from "
                                f"{cur.get('team') or 'Network Rail'} - they were emailed about "
                                f"{_short(cur.get('asked'))}: let them know it's off", "at": now})
    if kind is None:
        return tracker.move_date(d, r, new, why)
    if (cur.get("state") == "to_send" and cur.get("asked") == new and cur.get("kind") == kind
            and cur.get("his", "") == his and (cur.get("collect") or "") == (plan.get("collect") or "")):
        return kind == "later" and tracker.move_date(d, r, new, why)     # the same draft again: nothing new
    if (cur.get("kind") == kind and cur.get("asked") == new and cur.get("offered") == offered
            and cur.get("state") not in ("to_send", "dismissed")):
        return kind == "later" and tracker.move_date(d, r, new, why)
    if cur.get("state") == "sent" and cur.get("asked") != new:
        # Network Rail were emailed about another day already: the new email is his to send, after a word with them
        his = his or "asked_before"
        held_why = held_why or (f"{cur.get('team') or 'Network Rail'} were emailed about {_short(cur.get('asked'))} "
                                f"({str(cur.get('sent_at') or '')[:16]}) - the site now wants {_short(new)}: check "
                                "with them before this goes")
    team = team_for(r)
    subject, message = draft(r, kind, offered, new, plan if not his or his == "time" else None)
    nd = {"kind": kind, "offered": offered, "asked": new, "why": why, "at": tracker._now(),
          "state": "to_send", "team": team["name"] if team else "", "to": _addrs(team["to"]) if team else "",
          "cc": "", "subject": subject, "message": message,
          "reply_eid": str(reply_eid or "") or str(r.get("orig_entryid") or ""),
          "collect": plan.get("collect") or "", "available": plan.get("available") or "", "rule": plan.get("why")}
    if his:
        nd["his"] = his
        nd["held"] = {"why": held_why, "at": now}
    if cur:
        nd["prev"] = {k: cur.get(k) for k in ("kind", "offered", "asked", "state", "at", "sent_at")}
    r["nr_date"] = nd
    try:
        import metrics
        metrics.log("nr_date_" + kind, orders=r.get("orders", []), offered=offered, asked=new,
                    collect=nd["collect"], available=nd["available"])
    except Exception:
        pass
    if kind == "later":
        return tracker.move_date(d, r, new, why)
    return False


def audit(d, now=None):
    """The replied deliveries his 25/11 rule hasn't been put to: the site's day firm on the record and no Network Rail
    email for it - replies parsed before the rule came in, or a draft that waited on the site's time, which is firm
    now. Each is run through on_new_date as if it had just landed. [(record, what it is now)] for the ones that
    change - the caller saves."""
    import ctms_run_plan as P
    import delivery_details as dd
    now = now or datetime.now()
    out = []
    for r in list(d.get("records") or []):
        if r.get("kind", "delivery") != "delivery" or r.get("status") != "sent" or not r.get("reply_at"):
            continue
        # the one day the reply settles on, as the reply check takes it (a choice of days, "flexible" or not sure: his)
        day = P._day(dd.firm_date(r.get("details")))
        if not _d(day) or _d(day).date() < now.date():
            continue
        cur = r.get("nr_date") or {}
        if cur and not (cur.get("state") == "to_send" and cur.get("his") == "time" and cur.get("asked") == day):
            continue                     # the rule was put to it when the site's day landed
        before = json.dumps(cur, sort_keys=True)
        on_new_date(d, r, day, cur.get("why") or "the site's reply (his 25/11 rule)",
                    reply_eid=cur.get("reply_eid") or None)
        nd = r.get("nr_date") or {}
        if json.dumps(nd, sort_keys=True) != before:
            out.append((r, nd))
    return out


def held(r):
    """The day an order is held on while Network Rail is asked about an earlier one - the CTMS run and the map go by
    this. None when nothing is held."""
    nd = (r or {}).get("nr_date") or {}
    if nd.get("kind") == "earlier" and nd.get("state") in OPEN:
        return nd.get("offered") or r.get("delivery_date")
    return None


def moved_to(r):
    """The day a Network Rail date change moved the order to, which CTMS has to follow: a later week's (moved at once),
    or an earlier day they said yes to (or he let go without asking). None when it moved nowhere - still asked, or
    their no."""
    nd = (r or {}).get("nr_date") or {}
    if not _d(nd.get("asked")) or nd.get("superseded_by"):
        return None                        # (an email for a day the site has since changed: it moved nothing)
    if nd.get("kind") == "later" or (nd.get("kind") == "earlier" and nd.get("state") in ("allowed", "dismissed")):
        return nd["asked"]
    return None


def waiting(records):
    """The records with a Network Rail date email still to send, or an earlier date still to be answered."""
    return [r for r in records if ((r.get("nr_date") or {}).get("state") in OPEN)]


# ---------- the switches ----------
def _flag_head(path):
    try:
        raw = open(path, "rb").read(400)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(enc).upper()
        except Exception:
            continue
    return ""


def mode():
    """How the automatic part runs: {"mode": "live" | "shadow" | "off", "why": "..."} - off while the Toolkit switch
    is off, this alone is paused, or the Auto follow-ups switch is off; SHADOW while that switch says so (it decides
    and says what it would do, and changes nothing). LIVE only when the switch's file says LIVE, as the chaser."""
    try:
        import toolkit_switch
        if toolkit_switch.is_off():
            return {"mode": "off", "why": "the Toolkit switch is off"}
    except Exception:
        pass
    if os.path.exists(PAUSE_FLAG):
        return {"mode": "off", "why": "paused on the home PC (nr_date.paused)"}
    if not os.path.exists(CHASE_FLAG):
        return {"mode": "off", "why": "Auto follow-ups are off"}
    head = _flag_head(CHASE_FLAG)
    if "LIVE" in head and "SHADOW" not in head:
        return {"mode": "live", "why": ""}
    return {"mode": "shadow", "why": "Auto follow-ups are in shadow mode: it says what it would do, nothing is sent"}


def set_paused(paused):
    if paused:
        with open(PAUSE_FLAG, "w", encoding="utf-8") as f:
            f.write("Automatic Network Rail date emails paused. `python nr_date.py resume` (or delete this file) "
                    "to start them again. The dashboard's buttons still work.\n")
    else:
        try:
            os.remove(PAUSE_FLAG)
        except FileNotFoundError:
            pass
    return mode()


# ---------- what Network Rail wrote back ----------
_MARKING = re.compile(r"^\s*\[?\s*(?:OFFICIAL|NOT PROTECTIVELY MARKED)(?:[\s-]*SENSITIVE)?\s*\]?\s*:?\s*$", re.I)
_GREETING = re.compile(r"^\s*(?:hi|hello|hey|hiya|dear|morning|good morning|afternoon|good afternoon|evening)"
                       r"(?:\s+[a-z'.-]+){0,3}\s*[,!.:]?\s*$", re.I)
_SIGN_OFF = re.compile(r"^\s*(?:(?:many|kind|best|warm|warmest)\s+)?(?:thanks|thank you|thankyou|cheers|regards|"
                       r"wishes|ta|best|rgds|thx)\b[\s,.!]*(?P<rest>.*?)\s*$", re.I)
_THANKS = re.compile(r"\s*(?:many\s+)?(?:thanks|thank you|thankyou|cheers|ta|thx)\b", re.I)
_TAIL = re.compile(r"^\s*(?:sent from my|get outlook for|from:|sent:|-{2,}|_{4,})", re.I)
# the courtesies round an answer, which are no part of it ("let me know if you need anything else", "any issues give
# me a call") - taken out up to the end of their sentence, so the "if" or the "call" in them doesn't hold a plain yes
_CLOSING = re.compile(r"(?:(?:^|(?<=[.!?,;]\s)|(?<=[,;]))\s*any (?:other |further )?(?:questions|queries|issues|"
                      r"problems)"
                      r"|(?:please\s+)?(?:do\s+)?let (?:me|us) know if you (?:need|have|require|want)"
                      r"|if you (?:need|require|want) (?:anything|any (?:more|further|other)|any(?:thing)? else)"
                      r"|if you have any (?:other |further )?(?:questions|queries|issues|problems|concerns)"
                      r"|(?:please\s+)?(?:feel free|don'?t hesitate) to"
                      r"|hope (?:this|that) helps|have a (?:good|great|nice|lovely))[^.!?]*", re.I)


def _sign_off(line):
    """A line that is only a sign-off: "Thanks", "Many thanks,", "Kind regards", "Thanks, Dan" (a name after it,
    capitalised) - not "Thanks for the email", which is a sentence."""
    m = _SIGN_OFF.match(line)
    if not m or not line.strip():
        return False
    rest = m.group("rest").strip(" ,.!")
    return not rest or (len(rest.split()) <= 3 and all(w[:1].isupper() for w in rest.split()))


def _name_line(line):
    """A line that is just someone's name - one to three capitalised words, no sentence in it, and no answer either
    ("Yes", "Fine" and "No" are capitalised too)."""
    words = line.strip().split()
    if not 1 <= len(words) <= 3 or re.search(r"[,!?:;]|\d", line):
        return False
    if _POS.search(line) or _NEG.search(" " + line.lower()) or _POS_NEGATED.search(line):
        return False
    if all(w.lower().strip(".") in _ACK_WORDS for w in words):
        return False                        # "Noted", "Received": an answer to a notice
    return all(re.fullmatch(r"[A-Z][A-Za-z'.-]*", w) for w in words)


def said(body):
    """Their own words: above the quoted trail, without the OFFICIAL marking, the greeting, the courtesies, the
    sign-off and what follows it. (text, thanked) - thanked: a thanks was there (a bare "Thanks" acknowledges a
    notice)."""
    from modules import chase_rules as cr
    lines, thanked = [], False
    for ln in cr.own_text(body).splitlines():
        if _TAIL.match(ln):
            break
        if _sign_off(ln):
            thanked = thanked or bool(_THANKS.match(ln))
            if lines:
                break                       # the sign-off: their name and signature follow
            continue                        # "Thanks Delali" before anything else: a greeting, really
        if _MARKING.match(ln) or (not lines and _GREETING.match(ln)):
            continue
        if ln.strip():
            lines.append(ln.strip())
    while lines and _name_line(lines[-1]):
        lines.pop()                         # "Sam" under the answer: who wrote it, not what they said
    text = " ".join(_CLOSING.sub("", ln) for ln in lines)          # a line of an email starts a sentence
    text = re.sub(r"\s+([,.!?])", r"\1", re.sub(r"\s+", " ", text))
    text = re.sub(r"[,;]+\s*([.!?])", r"\1", text)
    text = re.sub(r"([.!?])(?:\s*\.)+", r"\1", text)                # what a courtesy taken out leaves behind
    return text.strip(" ,;"), thanked


# a positive put negatively ("no problem"), and a negative wrapped round a positive ("won't be ready"): these go first,
# so the words inside them aren't counted the other way
_POS_NEGATED = re.compile(r"\b(?:no|not an?|without any|zero)\s+(?:problems?|issues?|objections?|concerns?|worries)\b|"
                          r"\bdon'?t see (?:why not|(?:a|an|any) (?:problems?|issues?|reason why not))\b|"
                          r"\bnot a problem\b|\bno reason why not\b", re.I)
_NEG_PHRASE = re.compile(r"\b(?:not|never|no longer|can'?t|cannot|can not|won'?t|will not|wouldn'?t|couldn'?t|"
                         r"isn'?t|aren'?t|wasn'?t|weren'?t|doesn'?t|don'?t|unable to)\s+(?:\w+\s+){0,3}?"
                         r"(?:fine|ok|okay|possible|allowed|permitted|ready|available|able|happen|happening|go|"
                         r"deliver(?:ed)?|collect(?:ed)?|in stock|agree|approve|confirm|accept|do|work|manage)\b|"
                         r"\bunavailable\b|\bimpossible\b|\bnot until\b|\bnot before\b|\bno stock\b", re.I)
_NEG = re.compile(r"(?:^|[.!?;:])\s*no\b|\b(?:can'?t|cannot|can not|won'?t|will not|wouldn'?t|couldn'?t|isn'?t|"
                  r"aren'?t|wasn'?t|weren'?t|doesn'?t|don'?t|unable|unfortunately|afraid not|declined?|"
                  r"reject(?:ed)?|refused?|too (?:early|soon)|keep (?:it|this|them|the order|the delivery|to)|"
                  r"stays? on|remains? on|stick (?:to|with)|leave it (?:on|as))\b", re.I)
_POS = re.compile(r"\b(?:yes|yeah|yep|yup|ok|okay|fine|good to go|go ahead|proceed|approved?|agreed?|allowed|"
                  r"permitted|happy (?:for|with|to)|confirmed|(?:can|happy to|pleased to) confirm|no problem|"
                  r"works (?:for|with) (?:us|me)|that works|in stock|ready|available|can go|can be (?:delivered|"
                  r"collected)|perfect|great|acceptable|absolutely|definitely|sure)\b", re.I)
_HEDGE = re.compile(r"\b(?:should|shouldn'?t|hopefully|probably|possibly|maybe|perhaps|may|might|i think|i believe|"
                    r"i assume|i'?d assume|i guess|i reckon|as far as i (?:know|am aware|can see)|in theory|"
                    r"subject to|provided|providing|as long as|so long as|assuming|if|depends?|depending|unless|"
                    r"tbc|to be confirmed|not sure|unsure|don'?t know|not certain|unclear)\b", re.I)
_LATER = re.compile(r"\b(?:let me|i'?ll|i will|we'?ll|we will|i need to|we need to|need to|going to|i'?m going to)"
                    r"\s+(?:\w+\s+){0,2}?(?:check|confirm|find out|ask|look|chase|speak|come back|get back|revert|"
                    r"double[- ]check|update you|let you know|advise|query)\b|\b(?:come|get) back to you\b|"
                    r"\bchecking\b|\bawaiting\b|\bwaiting (?:on|for)\b|\bwill advise\b|\bfind out\b|\bin touch\b|"
                    r"\bpending\b", re.I)
_ASK = re.compile(r"\?|\b(?:can|could|would) you (?:confirm|check|send|let|tell|advise|call|ring)\b|"
                  r"\bplease (?:confirm|advise|call|ring|phone|send|check)\b", re.I)
_CALL = re.compile(r"\b(?:call|ring|phone) (?:me|us)\b|\bgive (?:me|us) a (?:call|ring|bell)\b|\bspeak to\b|"
                   r"\btalk to\b", re.I)
_PASSED = re.compile(r"\b(?:cc'?d|copied in|copying in|forwarded|forwarding|passed (?:this|it|on)|over to|"
                     r"looping in|looped in|best person)\b", re.I)
_ACK_WORDS = set("""thanks thank you for letting us me know noted received ok okay fine great cheers many that's thats
that is all understood will update updated our records the system acknowledged perfect no problem good much appreciated
info information heads up again kindly lovely brilliant i i'll we we'll we've i've have has been done amended changed
adjusted record recorded this it so and email""".split())
_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                           "dec"))}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _days_named(text):
    """The days their words name: [(day, month or None, weekday name or None)] - "28/11/26", "28/11", "28.11.26",
    "the 28th", "28 November", "Saturday". A time (08.00) or a rail length (13.716) is not a day."""
    t = str(text or "")
    out = []
    for m in re.finditer(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?![\d/])", t):
        dd, mm = int(m.group(1)), int(m.group(2))
        if 1 <= dd <= 31 and 1 <= mm <= 12:
            out.append((dd, mm, None))
    for m in re.finditer(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})(?![\d.])", t):
        dd, mm = int(m.group(1)), int(m.group(2))
        if 1 <= dd <= 31 and 1 <= mm <= 12:
            out.append((dd, mm, None))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                         r"[a-z]*\b", t, re.I):
        out.append((int(m.group(1)), _MONTHS[m.group(2).lower()], None))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)\b(?!\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|"
                         r"nov|dec))", t, re.I):
        out.append((int(m.group(1)), None, None))
    for m in re.finditer(r"\b(" + "|".join(_WEEKDAYS) + r")\b", t, re.I):
        out.append((None, None, m.group(1).lower()))
    return out


def _is_day(named, day):
    dd, mm, wd = named
    if day is None:
        return False
    if wd:
        return _WEEKDAYS[day.weekday()] == wd
    return dd == day.day and (mm is None or mm == day.month)


def verdict(text, nd, thanked=False):
    """What their words say about the date change: ("yes" | "no" | "ack" | "unclear", why). An earlier day needs a
    clear yes or a clear no; a later week's notice needs nothing back, so a plain thanks is an "ack" and anything more
    is for him to read. Never a yes when in doubt: a question, a hedge, a promise to check, a call me, someone else
    brought in, both a yes and a no, or a day named that isn't one of the two - all "unclear"."""
    t = str(text or "").strip()
    if nd.get("kind") == "later":
        words = re.findall(r"[a-z']+", t.lower())
        if (not t and thanked) or (words and all(w in _ACK_WORDS for w in words)):
            return "ack", "a thank-you"
        return "unclear", "they wrote back about the move" if t else "nothing written above the trail"
    if not t:
        return "unclear", "nothing written above the trail"
    low = " " + t.lower() + " "
    low = _POS_NEGATED.sub(" (+) ", low)
    low = _NEG_PHRASE.sub(" (-) ", low)
    for rx, why in ((_ASK, "a question back"), (_LATER, "they are still finding out"), (_CALL, "they want a call"),
                    (_PASSED, "someone else is brought in"), (_HEDGE, "not a firm answer")):
        m = rx.search(low)
        if m:
            return "unclear", f"{why} (\"{m.group(0).strip()}\")"
    asked, offered = _d(nd.get("asked")), _d(nd.get("offered"))
    days = _days_named(t)
    other = [x for x in days if not (_is_day(x, asked) or _is_day(x, offered))]
    if other:
        return "unclear", "they name another day"
    pos = low.count("(+)") + len(_POS.findall(low))
    neg = low.count("(-)") + len(_NEG.findall(low))
    if pos and neg:
        return "unclear", "both a yes and a no in it"
    if pos:
        if any(_is_day(x, offered) for x in days) and not any(_is_day(x, asked) for x in days):
            return "unclear", f"a yes, but to {_short(nd.get('offered'))} - the day we offered, not the one asked"
        return "yes", "a clear yes"
    if neg:
        return "no", "a clear no"
    return "unclear", "no yes or no in it"


# ---------- the mailbox ----------
def _norm_subject(s):
    s = str(s or "")
    while True:
        t = re.sub(r"^\s*(?:(?:re|fw|fwd|aw|wg|undeliverable|automatic reply|auto[- ]?reply|out of office(?: reply)?)"
                   r"\s*:|\[[^\]]{0,40}\]|\((?:external|official)\))\s*", "", s, flags=re.I)
        if t == s:
            break
        s = t
    return re.sub(r"\s+", " ", s).strip().lower()


def _team_addrs(nd):
    return {a.strip().lower() for a in re.split(r"[;,]", f"{nd.get('to') or ''};{nd.get('cc') or ''}") if "@" in a}


def _site_addrs(r):
    from modules import chase_rules as cr
    return set(cr.emails_in(r.get("to"))) | set(cr.emails_in(r.get("cc")))


def _dt(s):
    from modules import chase_rules as cr
    return cr.parse_dt(s)


def _who(m, team, site, me=()):
    """Whose email this is, for a Network Rail date change: "team" (one of the addresses it went to, or anyone at
    Network Rail but the site), "site", "us", "colleague" (DHL) or "other" (a supplier, a haulier ...)."""
    from modules import chase_rules as cr
    frm = str(m.get("from") or "").lower()
    if m.get("dir") == "out" or not frm or frm in me:
        return "us"
    if frm in team:
        return "team"
    if frm in site:
        return "site"
    dom = cr.domain(frm)
    if dom == NR_DOMAIN or dom.endswith("." + NR_DOMAIN):
        return "team"
    if dom == "dhl.com" or dom.endswith(".dhl.com"):
        return "colleague"
    return "other"


def _ours(nd, mails):
    """Our own email(s) to the team for this date change, in the index: the same subject, sent since it was drafted."""
    since = _dt(nd.get("at")) or datetime.min
    subj = _norm_subject(nd.get("subject"))
    return [m for m in mails if m.get("dir") == "out" and _norm_subject(m.get("subject")) == subj
            and m.get("at") and m["at"] >= since - timedelta(minutes=10)]


def sent_already(r, mails, text_of):
    """(mail, sure) when Sent Items shows the date email went outside the desk - to the team, about the order, since
    it was drafted: sure when it has our subject or names the day asked; not sure when it only names the order (it
    may be about something else). (None, False) when nothing went."""
    from modules import chase_rules as cr
    nd = r.get("nr_date") or {}
    team = _team_addrs(nd)
    since = (_dt(nd.get("at")) or datetime.min) - timedelta(minutes=10)
    orders = cr.orders_of(r) or [str(o) for o in r.get("orders") or []]
    subj = _norm_subject(nd.get("subject"))
    maybe = None
    for m in sorted((m for m in mails if m.get("dir") == "out" and m.get("at") and m["at"] >= since),
                    key=lambda m: m["at"]):
        if not {str(a).strip().lower() for a in list(m.get("to") or []) + list(m.get("cc") or [])} & team:
            continue
        if _norm_subject(m.get("subject")) == subj:
            return m, True
        if cr.mentions(m.get("subject"), orders):
            body = text_of(m["eid"]) if text_of else None
            words = f"{m.get('subject') or ''} {cr.own_text(body or '')}"
            asked = _d(nd.get("asked"))
            if asked and any(_is_day(x, asked) for x in _days_named(words)):
                return m, True
            maybe = maybe or m
    return maybe, False


def _quote(text, n=220):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[:n - 3].rstrip() + "..."


def _mail_said(m, text_of, who):
    body = text_of(m["eid"]) if text_of else None
    words, thanked = said(body or "")
    return {"at": m["at"].strftime("%Y-%m-%d %H:%M"), "from": m.get("from") or "", "who": m.get("from_name") or "",
            "said": _quote(words), "eid": m.get("eid") or "", "subject": str(m.get("subject") or "")[:120],
            "whose": who, "_text": words, "_thanked": thanked, "_read": body is not None}


def answers(r, mails, text_of, me=()):
    """Everything that came back on our date email's own thread since it went, oldest first, each with whose it is
    and their words - and the team's emails about the order outside that thread (maybe their answer, sent fresh)."""
    from modules import chase_rules as cr
    nd = r.get("nr_date") or {}
    sent = _dt(nd.get("sent_at")) or _dt(nd.get("at")) or datetime.min
    team, site = _team_addrs(nd), _site_addrs(r)
    convs = {m.get("conv") for m in _ours(nd, mails) if m.get("conv")}
    subj = _norm_subject(nd.get("subject"))
    orders = cr.orders_of(r) or [str(o) for o in r.get("orders") or []]
    on, off = [], []
    for m in sorted((m for m in mails if m.get("dir") == "in" and not m.get("draft") and m.get("at")
                     and m["at"] > sent), key=lambda m: m["at"]):
        thread = (m.get("conv") and m["conv"] in convs) or _norm_subject(m.get("subject")) == subj
        who = _who(m, team, site, me)
        if who == "us":
            continue
        if thread:
            on.append((m, who))
        elif who == "team" and cr.mentions(m.get("subject"), orders) and not m.get("auto") and not m.get("ndr"):
            off.append((m, who))
    return on, off


def judge(r, mails, text_of, now, me=(), holidays=()):
    """What to do about one record's Network Rail date change, from the mailbox - pure, so it can be tried on anything:
        {"do": "send" | "mark_sent" | "wait" | "yes" | "no" | "ack" | "hold" | "nothing", "why", "mail": {...}}
    "wait" is a send held back to working hours, or an ask with no answer yet. Nothing here sends or changes a thing."""
    from modules import chase_rules as cr
    nd = r.get("nr_date") or {}
    state, kind = nd.get("state"), nd.get("kind")
    asked = _d(nd.get("asked"))
    seen = set(nd.get("seen") or [])
    if state == "to_send":
        if nd.get("his"):                  # the rule couldn't settle it (the site's time, no availability date...)
            return {"do": "hold", "why": (nd.get("held") or {}).get("why") or "Left to you"}
        if not str(nd.get("to") or "").strip():
            return {"do": "hold", "why": "No Network Rail team is known for this material - type who it goes to, "
                                         "and press Send"}
        if asked and asked.date() < now.date():
            return {"do": "hold", "why": f"The day the site asked for ({_short(nd['asked'])}) has gone - nothing sent"}
        if kind == "earlier" and asked and asked.date() == now.date():
            return {"do": "hold", "why": "The site asked for today - too late to ask Network Rail, nothing sent"}
        m, sure = sent_already(r, mails, text_of)
        if m is not None and sure:
            return {"do": "mark_sent", "why": f"Sent Items has it already ({m['at']:%d/%m %H:%M}) - not sent again",
                    "mail": {"at": m["at"].strftime("%Y-%m-%d %H:%M"), "eid": m.get("eid") or "",
                             "subject": str(m.get("subject") or "")[:120]}}
        if m is not None:
            return {"do": "hold", "why": f"You emailed {nd.get('team') or 'them'} about the order at "
                                         f"{m['at']:%d/%m %H:%M} (\"{_quote(m.get('subject'), 80)}\") - was that "
                                         "this? Send it, or No email needed"}
        if not cr.in_working_hours(now, holidays):
            return {"do": "wait", "why": "goes by itself in working hours (Mon-Fri 08:00-16:30)"}
        return {"do": "send", "why": "the site's reply asks for it"}
    if state != "sent":
        return {"do": "nothing", "why": ""}
    on, off = answers(r, mails, text_of, me)
    # one he waved through ("Keep waiting") stands for its time: nothing older than it is taken for their answer
    waved = max((m["at"] for m, who in on if m.get("eid") in seen), default=None)
    picked = []
    for m, who in on:
        if waved is not None and m["at"] <= waved and m.get("eid") not in seen:
            continue
        if m.get("ndr"):
            if m.get("eid") not in seen:
                return {"do": "hold", "why": "Your email to Network Rail bounced - check the address",
                        "mail": _mail_said(m, text_of, who)}
            continue
        if m.get("auto"):
            continue                       # an out-of-office: still waiting for the answer
        got = _mail_said(m, text_of, who)
        if not got["_read"]:
            return {"do": "hold", "why": "Their reply couldn't be read - read it in Outlook", "mail": got}
        if m.get("eid") in seen:
            continue                       # he looked at this one and said keep waiting
        if who != "team":
            name = {"site": "The site", "colleague": "A colleague", "other": "Someone outside Network Rail"}.get(
                who, "Someone")
            return {"do": "hold", "why": f"{name} answered on the Network Rail thread, not the team - read it",
                    "mail": got}
        picked.append(got)
    if kind == "later":
        for got in picked:
            v, why = verdict(got["_text"], nd, got["_thanked"])
            if v != "ack":
                return {"do": "hold", "why": f"{nd.get('team') or 'Network Rail'} wrote back about the move - read "
                                             "it", "mail": got}
        if picked and not nd.get("answer"):
            return {"do": "ack", "why": "they said thanks", "mail": picked[-1]}
        return {"do": "nothing", "why": ""}
    if picked:
        verdicts = [(got, verdict(got["_text"], nd)) for got in picked]
        newest, (v, why) = verdicts[-1]
        clear = {x[1][0] for x in verdicts if x[1][0] in ("yes", "no")}
        if v == "unclear":
            return {"do": "hold", "why": f"Not a clear yes or no: {why}", "mail": newest}
        if len(clear) > 1:
            return {"do": "hold", "why": "A yes and a no in their replies - read them", "mail": newest}
        return {"do": v, "why": why, "mail": newest}
    for m, who in off:
        if m.get("eid") not in seen:
            got = _mail_said(m, text_of, who)
            return {"do": "hold", "why": f"{nd.get('team') or 'Network Rail'} wrote about the order outside the "
                                         "thread - is it their answer?", "mail": got}
    if kind == "earlier" and asked and asked.date() < now.date():
        return {"do": "hold", "why": f"No answer, and {_short(nd['asked'])} has gone - it stays on "
                                     f"{_short(nd.get('offered'))}: press They said no, and tell the site"}
    return {"do": "wait", "why": "waiting for their answer"}


# ---------- the dashboard's buttons (agent action "nr_date") and the automatic part's changes ----------
def _find(d, rid):
    for r in d["records"]:
        if r.get("id") == rid:
            return r
    return None


def _forward_send(nd, to, cc, subject, message):
    """Forward the site's email (the whole trail underneath) to the team, from the DHL account. Falls back to a new
    email when the site's email is gone. Returns (ok, said)."""
    import win32com.client
    import build_drafts as bd
    import send_order
    from mail_ops import insert_top
    ns = bd.get_ns()
    acct = send_order.dhl_account(ns)
    if acct is None:
        return False, "The DHL account was not found in Outlook - nothing sent."
    m = None
    if nd.get("reply_eid"):
        try:
            store = bd.dhl_store(ns)
            src = ns.GetItemFromID(nd["reply_eid"], store.StoreID)
            m = src.Forward()
            m.HTMLBody = insert_top(m.HTMLBody, bd.html_from_message(message))
        except Exception:
            m = None
    if m is None:
        m = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
        m.HTMLBody = bd.html_from_message(message)
    to, cc, _ = bd.clean_to_cc(to, cc)
    m.To = to
    m.CC = cc or ""
    m.Subject = subject
    bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        return False, "Could not send from the DHL account - nothing sent."
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    return True, f"sent to {to}"


def _go(r, nd, edits, sender, by):
    """The email goes: the (edited) one, the same checks whoever sends it. (ok, said)."""
    import tracker
    edits = edits or {}
    to = _addrs(edits.get("to", nd.get("to")))
    cc = _addrs(edits.get("cc", nd.get("cc")))
    subject = str(edits.get("subject") or nd.get("subject") or "").strip()
    message = str(edits.get("message") or nd.get("message") or "").replace("—", "-").replace("–", "-")
    if not to:
        return False, "Who is the Network Rail team for this order? Type their address in To."
    ok, said_ = (sender or _forward_send)(nd, to, cc, subject, message)
    if not ok:
        return False, said_
    nd.update(state="sent", sent_at=tracker._now(), to=to, cc=cc, subject=subject, message=message, sent_by=by)
    nd.pop("held", None)
    nd.pop("send_failed", None)
    return True, said_


def send(rid, edits, sender=None):
    """His Send: the (edited) email goes, and the record says so. sender(nd, to, cc, subject, message) -> (ok,
    said) is the Outlook part (tests pass a stand-in)."""
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd:
        return {"ok": False, "said": "That order has no Network Rail email waiting - nothing sent."}
    if nd.get("state") != "to_send":
        return {"ok": False, "said": f"Already {nd.get('state', '').replace('_', ' ')} - nothing sent."}
    ok, said_ = _go(r, nd, edits, sender, "you")
    if not ok:
        return {"ok": False, "said": said_}
    tracker.save(d)
    orders = " / ".join(r.get("orders") or [])
    return {"ok": True, "said": f"{orders}: Network Rail emailed ({said_})"
            + (f" - the order stays on {_short(nd['offered'])} until they say yes." if nd["kind"] == "earlier" else ".")}


def _todo_after(r, nd, yes):
    """The CTMS to-do after their answer: a yes needs the order's update open (the site's reply left one; it now types
    the new day) - one is added if none is; a no takes off the Night / Saturday / Sunday the earlier day needed and
    puts on what the offered day needs. Never fails the answer itself: it says what went wrong instead."""
    try:
        import ctms_todo
        if yes:
            it = ctms_todo.nr_moved(r, nd["asked"])
            return f"CTMS to-do: {it['what']}" if it else ""
        ctms_todo.nr_kept(r, nd["asked"], nd["offered"])
        return ""
    except Exception as e:
        return f"(the CTMS to-do couldn't be updated: {e})"


def decide(d, r, yes, by, mail=None):
    """Network Rail's answer to an earlier day lands - read off their reply (by "auto") or pressed by him ("you").
    Yes: the order moves to the site's day, and the CTMS to-do types it. No: it stays on the day we offered (the
    parsed reply's date is set back to it, so the CTMS update types that day), and the site is his to tell."""
    import tracker
    nd = r["nr_date"]
    nd.update(answered_at=tracker._now(), answered_by=by)
    nd.pop("held", None)
    if mail:
        nd["answer"] = {k: v for k, v in mail.items() if not k.startswith("_")}
        nd["answer"]["verdict"] = "yes" if yes else "no"
    if yes:
        nd["state"] = "allowed"
        moved = tracker.move_date(d, r, nd["asked"], "Network Rail's OK")
        note = _todo_after(r, nd, True)
        return moved, note
    nd["state"] = "not_allowed"
    nd["tell_site"] = True
    cell = (r.get("details") or {}).get("date")
    if isinstance(cell, dict):
        cell["asked"] = cell.get("value")
        cell["value"] = nd["offered"]
    note = _todo_after(r, nd, False)
    return False, note


def answer(rid, yes):
    """Network Rail's answer to an earlier date, as he presses it. Yes: the order moves to the site's day. No: it
    stays on the day we offered, and the CTMS update types that day (the parsed reply's date is set back to it)."""
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd or nd.get("kind") != "earlier" or nd.get("state") not in OPEN:
        return {"ok": False, "said": "That order has no earlier date waiting on Network Rail."}
    orders = " / ".join(r.get("orders") or [])
    moved, note = decide(d, r, yes, "you")
    tracker.save(d)
    if yes:
        return {"ok": True, "said": f"{orders}: allowed - " + (f"moved to {_short(nd['asked'])}." if moved
                                                               else f"it is on {_short(nd['asked'])}.")
                + (f" {note}" if note else "")}
    return {"ok": True, "said": f"{orders}: not allowed - it stays on {_short(nd['offered'])}. Let the site know."
            + (f" {note}" if note else "")}


def dismiss(rid):
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd or nd.get("state") != "to_send":
        return {"ok": False, "said": "Nothing to dismiss on that order."}
    nd.update(state="dismissed", answered_at=tracker._now())
    nd.pop("held", None)
    if nd.get("kind") == "earlier":       # no email, so no hold: the site's day stands as any other reply's
        tracker.move_date(d, r, nd["asked"], "the site's reply")
    tracker.save(d)
    return {"ok": True, "said": f"{' / '.join(r.get('orders') or [])}: no Network Rail email."}


def seen(rid):
    """His "Keep waiting" / "Seen" on a held email: it is waved through and never held for again - an ask goes on
    waiting for their answer, a notice is done with."""
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    h = (nd or {}).get("held") or {}
    if not nd or not h:
        return {"ok": False, "said": "Nothing held on that order."}
    if h.get("eid"):
        nd["seen"] = sorted(set(nd.get("seen") or []) | {h["eid"]})
    nd.pop("held", None)
    nd["seen_at"] = tracker._now()
    tracker.save(d)
    return {"ok": True, "said": f"{' / '.join(r.get('orders') or [])}: seen"
            + (" - still waiting for Network Rail's answer." if nd.get("state") == "sent" and nd.get("kind") == "earlier"
               else ".")}


def told(rid):
    """His "Told them": the site knows Network Rail said no, so the card lets it go."""
    import tracker
    d = tracker.load()
    r = _find(d, rid)
    nd = (r or {}).get("nr_date")
    if not nd or not nd.get("tell_site"):
        return {"ok": False, "said": "Nothing to tell the site on that order."}
    nd["tell_site"] = False
    nd["told_site_at"] = tracker._now()
    tracker.save(d)
    return {"ok": True, "said": f"{' / '.join(r.get('orders') or [])}: the site knows it stays on "
                                f"{_short(nd.get('offered'))}."}


def _hold(nd, why, mail, now):
    """Held for him - kept as it was when nothing about it changed, so the card doesn't flicker run to run."""
    h = {"why": why, "at": now.strftime("%Y-%m-%d %H:%M")}
    if mail:
        h.update({k: v for k, v in mail.items() if not k.startswith("_")})
    old = nd.get("held") or {}
    if old.get("why") == h["why"] and old.get("eid", "") == h.get("eid", ""):
        return False
    nd["held"] = h
    return True


def apply(d, r, j, sender=None, now=None):
    """One record's judgement carried out on the loaded tracker (the caller saves it). Returns the line to report, or
    "" when nothing changed."""
    import tracker
    now = now or datetime.now()
    nd = r["nr_date"]
    orders = " / ".join(r.get("orders") or [])
    team = nd.get("team") or "Network Rail"
    do = j["do"]
    if do == "send":
        ok, said_ = _go(r, nd, {}, sender, "auto")
        if not ok:
            nd["send_failed"] = {"at": now.strftime("%Y-%m-%d %H:%M"), "said": said_}
            return f"FAIL   {orders}: {said_}"
        return (f"SENT   {orders}: {team} " + ("asked about " if nd["kind"] == "earlier" else "told about ")
                + f"{_short(nd['asked'])} ({said_})")
    if do == "mark_sent":
        mail = j.get("mail") or {}
        nd.update(state="sent", sent_at=mail.get("at") or tracker._now(), sent_by="by hand",
                  sent_eid=mail.get("eid") or "")
        nd.pop("held", None)
        return f"SEEN   {orders}: {j['why']}"
    if do in ("yes", "no"):
        moved, note = decide(d, r, do == "yes", "auto", j.get("mail"))
        who = (j.get("mail") or {}).get("who") or team
        if do == "yes":
            return (f"YES    {orders}: {who} said yes ({j['why']}) - moved to {_short(nd['asked'])}"
                    + (f"; {note}" if note else ""))
        return (f"NO     {orders}: {who} said no - it stays on {_short(nd['offered'])}; the site is yours to tell"
                + (f" {note}" if note else ""))
    if do == "ack":
        mail = {k: v for k, v in (j.get("mail") or {}).items() if not k.startswith("_")}
        nd["answer"] = dict(mail, verdict="ack")
        return f"THANKS {orders}: {mail.get('who') or team} said thanks for the notice"
    if do == "hold":
        if _hold(nd, j["why"], j.get("mail"), now):
            return f"HOLD   {orders}: {j['why']}"
        return ""
    if do == "wait" and nd.get("held") and nd.get("state") == "sent":
        nd.pop("held", None)               # what was held is gone (read in Outlook, filed): just waiting again
        return f"WAIT   {orders}: {j['why']}"
    return ""


def _index(ns, records):
    """The whole mailbox since the oldest open date change was drafted (less a day), as the chaser reads it."""
    import chase_guard as guard
    starts = [x for x in ((_dt((r.get("nr_date") or {}).get("at"))) for r in records) if x]
    since = (min(starts) if starts else datetime.now()) - timedelta(days=1)
    since = max(since, datetime.now() - timedelta(days=guard.MAX_LOOKBACK_DAYS))
    return guard.MailIndex(ns, since)


def _stopped(d, live, did, lines, why, mode_):
    """A run that stopped at the mailbox: what the rule drafted before it (no Outlook in that) is kept all the same."""
    import tracker
    if live and did:
        tracker.save(d)
    return {"ok": True, "lines": lines + [why], "did": did, "mode": mode_}


def auto(live=True, ns=None, idx=None, sender=None, now=None):
    """The timer's run. Every open Network Rail date change judged against the whole mailbox; with live, what that
    says is done and saved - else it only says what it would do. Fails closed: a mailbox it can't read completely,
    or one that has stopped syncing, sends and decides nothing. Returns {"ok", "lines", "did", "mode"}."""
    import tracker
    from modules import chase_rules as cr
    now = now or datetime.now()
    m = mode()
    if live and m["mode"] == "off":
        return {"ok": True, "lines": [f"SKIP   automatic Network Rail emails: {m['why']}"], "did": 0,
                "mode": m["mode"]}
    if m["mode"] == "shadow":
        live = False                       # shadow: what it would do, said and nothing more
    d = tracker.load()
    # his 25/11 rule put to the replies it hasn't been put to yet (parsed before it came in, or a draft that waited on
    # the site's time): what it drafts goes on below like any other. Shadow and a dry run work on a copy - said only
    if not live:
        d = copy.deepcopy(d)
    lines, did = [], 0
    for r, nd in audit(d, now):
        orders = " / ".join(r.get("orders") or [])
        what = ("ask" if nd.get("kind") == "earlier" else "heads-up") if nd.get("state") == "to_send" else "none needed"
        lines.append(f"{'DRAFT ' if live else 'WOULD DRAFT'} {orders}: {what} - {nd.get('rule') or nd.get('why')}"
                     + (f" (held for you: {(nd.get('held') or {}).get('why')})" if nd.get("his") else ""))
        did += 1 if live else 0
    recs = [r for r in d["records"] if (r.get("nr_date") or {}).get("state") in OPEN]
    if not recs:
        if live and did:
            tracker.save(d)
        return {"ok": True, "lines": lines, "did": did, "mode": m["mode"]}
    try:
        from services import BANK_HOLIDAYS
        hol = {datetime.strptime(h, "%Y-%m-%d").date() for h in BANK_HOLIDAYS}
    except Exception:
        hol = set()
    if idx is None:
        import build_drafts as bd
        import chase_guard as guard
        ns = ns or bd.get_ns()
        try:
            idx = _index(ns, recs)
        except Exception as e:
            return _stopped(d, live, did, lines, f"ABORT  the mailbox couldn't be read - nothing sent or decided ({e})",
                            m["mode"])
        if idx.errors:
            return _stopped(d, live, did, lines, "ABORT  part of the mailbox couldn't be read, so an answer could be "
                            "missed - nothing sent or decided: " + "; ".join(idx.errors[:3]), m["mode"])
        ok, why = guard.mailbox_fresh(ns, idx, now if cr.in_working_hours(now, hol) else now.replace(hour=0))
        if not ok:
            return _stopped(d, live, did, lines, f"ABORT  {why} - nothing sent or decided", m["mode"])
    me = set()
    try:
        import chase_guard as guard
        me = set(guard._me())
    except Exception:
        pass
    refreshed = False
    for r in recs:
        j = judge(r, idx.mails, idx.text_of, now, me, hol)
        orders = " / ".join(r.get("orders") or [])
        if j["do"] in ("nothing",):
            continue
        if not live:
            would = {"send": "WOULD SEND", "mark_sent": "WOULD MARK SENT", "yes": "WOULD SAY YES",
                     "no": "WOULD SAY NO", "ack": "WOULD NOTE THANKS", "hold": "WOULD HOLD", "wait": "WAIT"}[j["do"]]
            extra = ""
            mail = j.get("mail") or {}
            if mail.get("said"):
                extra = f" | {mail.get('who') or mail.get('from')} {mail.get('at')}: \"{mail['said']}\""
            lines.append(f"{would:<15} {orders} ({r['nr_date']['kind']} {r['nr_date'].get('offered')} -> "
                         f"{r['nr_date'].get('asked')}): {j['why']}{extra}")
            continue
        if j["do"] == "send" and not refreshed and hasattr(idx, "refresh"):
            # the last look before anything goes: mail that landed since the folders were read (a folder that won't
            # open now is recorded, not raised - as the chaser, that stops the sends too)
            try:
                n_err = len(getattr(idx, "errors", None) or [])
                idx.refresh()
                if len(getattr(idx, "errors", None) or []) > n_err:
                    raise RuntimeError("; ".join(idx.errors[n_err:n_err + 2]))
            except Exception as e:
                lines.append(f"ABORT  the last look at the mailbox failed - nothing more sent ({e})")
                break
            refreshed = True
            j = judge(r, idx.mails, idx.text_of, now, me, hol)
        if j["do"] == "send" and mode()["mode"] != "live":
            lines.append("STOP   automatic Network Rail emails were switched off mid-run - nothing more sent")
            break
        said_ = apply(d, r, j, sender=sender, now=now)
        if said_:
            lines.append(said_)
            did += 1
    if live and did:
        tracker.save(d)
    # ok: nothing failed half way. An ABORT stopped before anything was sent or decided - safe, said by the agent once
    # a day; a FAIL is an email that wouldn't go, tried again in a few minutes
    return {"ok": not any(x.startswith("FAIL") for x in lines), "lines": lines, "did": did, "mode": m["mode"]}


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmds = ("send", "answer", "dismiss", "seen", "told")
    if len(argv) >= 2 and argv[1] in ("pause", "resume"):
        print(json.dumps(set_paused(argv[1] == "pause")))
        return 0
    if len(argv) >= 2 and argv[1] == "auto":
        dry = "--dry" in argv[2:]
        import outlook_gate as gate
        if not dry:
            try:
                wait = float(os.environ.get("R2_PHASE2_WAIT", "30"))
            except ValueError:
                wait = 30.0
            if gate.named_lock("phase2_tracker", wait=wait) is None:     # a reply check or chase holds the tracker
                print("SKIP   the reply check is updating the tracker - next time")
                return gate.SKIPPED
        out = auto(live=not dry)
        print("\n".join(out["lines"]) if out["lines"] else "nothing to do")
        print("NR_RESULT " + json.dumps({k: out[k] for k in ("ok", "did", "mode")}))
        return 0 if out["ok"] else 1
    if len(argv) < 3 or argv[1] not in cmds:
        print("usage: nr_date.py auto [--dry] | pause | resume | send <id> <json> | answer <id> yes|no | dismiss <id> "
              "| seen <id> | told <id>")
        return 2
    import outlook_gate as gate
    if gate.named_lock("phase2_tracker", wait=30) is None:      # a reply check or chase holds the tracker
        out = {"ok": False, "said": "Not done - the reply check is updating the tracker; press it again in a minute."}
    elif argv[1] == "send":
        edits = {}
        if len(argv) > 3:
            with open(argv[3], encoding="utf-8") as f:
                edits = json.load(f)
        out = send(argv[2], edits if isinstance(edits, dict) else {})
    elif argv[1] == "answer":
        out = answer(argv[2], len(argv) > 3 and argv[3].lower() in ("yes", "y", "allowed", "1", "true"))
    elif argv[1] == "seen":
        out = seen(argv[2])
    elif argv[1] == "told":
        out = told(argv[2])
    else:
        out = dismiss(argv[2])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
