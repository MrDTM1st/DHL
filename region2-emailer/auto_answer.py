"""Auto-answers (his 25/11 pick, "Auto-answers"). On his day off the Emails page held 24 emails, and a tap of Deal with
it on each takes too long: "make it answer like obvious questions that it already knows". Some emails ask only what
Book already knows - is the order booked, when is it coming, who is bringing it, what's the ref - and those the inbox
assistant answers by itself. Only those, and only when all of this holds:

  - Claude, reading the email (inbox_assist judge), says that is ALL it asks (asks_booking): nothing to change, no
    problem, no price, nothing about a collection;
  - every order it names is a seven-digit order Book booked, all of them in one job, every manifest ACCEPTED, for a
    day after today (on the day, where a lorry is is his to answer), and not split over pick-ups or days;
  - it's from Network Rail (a site, a requester, a materials team) or one of the order's own site contacts - never a
    manager, DHL Road, a DHL colleague, a haulier or a supplier;
  - CTMS, read there and then (trip-read by its order line, the Stops tab only - reads only), still shows each
    manifest ACCEPTED, delivering on the day Book booked and within the hour of its time (CTMS plans the arrival a
    minute or so off the booked window: 22:31 for a 22:30 booking, seen 24/11).

The words are never Claude's: they are his own booking email (book_run.words, "This order has been arranged with ...
for <day>, delivering between ... Here is the ref number MAN-..."), filled from Book's journal. Never a price.

    off      nothing of this
    shadow   (how it starts) the email's card carries the answer it would send and says why; nothing goes by itself
    live     it goes: reply to all on the email's own thread (never DHL Road, never a haulier), in working hours
             (07:00-19:00 on weekdays that aren't bank holidays), at most 5 a run and 40 a day; filed to Region 2 >
             Completed like every email he answers, and listed on the Emails page as "Answered for you"

What can't be checked waits for him: CTMS not open, Look mum off, a booking running - the answer stays on the card for
his one tap, and in live mode CTMS is tried again every half hour (8 tries). A check over three hours old is done again
before anything goes.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(HERE, "_book_journal.json")
ROUTES = os.path.join(HERE, "ctms_routes.py")

MODES = ("off", "shadow", "live")
BOOKED = ("booked", "done")                               # Book's journal: in CTMS, the manifests ACCEPTED
UNSURE = ("asking", "half", "unknown", "stopped")         # a booking CTMS hasn't settled: never answered from
ROLES = ("Network Rail (a site, requester or colleague)", "a Network Rail materials team")   # inbox_assist.role's words
HOURS = (7, 19)                                           # when an answer may go, on a working weekday
FRESH = timedelta(hours=3)                                # a CTMS check older than this is done again first
RETRY = timedelta(minutes=30)                             # CTMS couldn't be read: tried again after this (live only)
TRIES = 8
PER_RUN = 5
PER_DAY = 40
MAX_PEOPLE = 12                                           # a reply to all that would go wider than this is his
CHECK_WAIT = 180                                          # seconds for one CTMS read
DRIFT = timedelta(minutes=60)                             # CTMS's planned arrival against Book's booked time
# The stops a delivery can be (read live 24/11 and 26/11): DL a drop; CL the stop that closes the trip - on a single
# drop it IS the site (a rails trip, 26/11: SU at the supplier 16:00, CL at the site 17:06 with a 06:24 wait = 23:30,
# the time Book booked)
DROP_TYPES = ("DL", "CL")
STAMP = "%Y-%m-%d %H:%M"
ORDER = re.compile(r"\d{7}")
MAN = re.compile(r"MAN-\d{8}")
ADDR = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def _base(o):
    return re.sub(r"-.*$", "", re.sub(r"\s+", "", str(o or ""))).upper()


def _orders_of(job):
    return {_base(x) for x in (job or {}).get("orders") or ()}


def _age(stamp, now):
    try:
        return now - datetime.strptime(str(stamp or "")[:16], STAMP)
    except ValueError:
        return timedelta(days=999)


def load_journal(path=None):
    """Book's journal (book_journal.py): {key: job}. {} when there's none."""
    try:
        with open(path or JOURNAL, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    jobs = d.get("jobs") if isinstance(d, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def in_hours(now, holidays=()):
    """A working weekday (not a bank holiday), 07:00-19:00."""
    return (now.weekday() < 5 and now.strftime("%Y-%m-%d") not in {str(h) for h in holidays or ()}
            and HOURS[0] <= now.hour < HOURS[1])


# ---------- what Book knows ----------
def book_line(order, jobs):
    """What Book's journal has on one order, in a line for Claude's reading of the email; "" when nothing."""
    import book_run
    b = _base(order)
    bits = []
    for e in jobs.values():
        if b not in _orders_of(e):
            continue
        if e.get("state") in BOOKED:
            who = "our own DHL fleet" if e.get("carrier") == book_run.NOC else (e.get("haulier") or e.get("carrier") or "?")
            trips = [t for t in e.get("trips") or [] if t.get("manifest")][:3]
            bits.append(f"booked by Book for {e.get('date')} with {who}: " + "; ".join(
                f"{t['manifest']} {t.get('status') or '?'}, collect {t.get('collect') or '?'}, "
                f"deliver {t.get('deliver') or '?'}" for t in trips))
        elif e.get("state") in UNSURE:
            bits.append(f"a booking for {e.get('date')} that Book hasn't settled ({e.get('state')})")
    return "; ".join(bits[:3])


def find_job(orders, jobs):
    """-> (key, job, "") when one job Book booked covers every order the email names; (None, None, why not)."""
    named = sorted({_base(o) for o in orders or () if ORDER.fullmatch(_base(o))})
    if not named:
        return None, None, "it names no order number"
    keys = set()
    for o in named:
        mine = {k: e for k, e in jobs.items() if o in _orders_of(e)}
        if any(e.get("state") in UNSURE for e in mine.values()):
            return None, None, f"a booking of {o} isn't settled in Book"
        booked = [k for k, e in mine.items() if e.get("state") in BOOKED]
        if not booked:
            return None, None, f"{o} wasn't booked through Book"
        keys.update(booked)
    if len(keys) != 1:
        days = ", ".join(sorted(str(jobs[k].get("date") or "?") for k in keys))
        return None, None, f"booked as more than one job ({days})"
    k = keys.pop()
    return k, jobs[k], ""


def check_job(job, now, records=()):
    """Why the job can't be answered from as it stands, or ""."""
    trips = job.get("trips") or []
    if not trips or any(t.get("status") != "ACCEPTED" or not MAN.fullmatch(str(t.get("manifest") or ""))
                        for t in trips):
        return "not every manifest is ACCEPTED in Book's journal"
    try:
        day = datetime.strptime(str(job.get("date") or ""), "%d/%m/%Y").date()
    except ValueError:
        return "Book's journal has no delivery day for it"
    if day <= now.date():
        return "the delivery is today or past: where it is is yours to answer"
    for t in trips:
        for f in ("collect", "deliver"):
            try:
                datetime.strptime(str(t.get(f) or "")[:14], "%d/%m/%y %H:%M")
            except ValueError:
                return f"{t['manifest']} has no {f} time in Book's journal"
    try:
        import pickup_split
        if pickup_split.note(job.get("record_copy") or {}, job.get("date")):
            return "a split order (several pick-ups or days)"
    except Exception:
        return "couldn't tell whether it's a split order"
    mine = _orders_of(job)
    for r in records or ():
        if mine & {_base(x) for x in r.get("orders") or ()}:
            dd = str(r.get("delivery_date") or "")
            if dd and dd != job.get("date"):
                return f"the tracker has it on {dd}, Book booked {job.get('date')}"
    return ""


def site_people(job):
    """The order's site contacts as Book knew them: the record's contact and whoever its site email went to."""
    said = str(((job.get("steps") or {}).get("site_email") or {}).get("said") or "")
    to = str((job.get("record_copy") or {}).get("to") or "")
    return {a.lower() for a in ADDR.findall(to + " " + said)}


def sender_ok(role, addr, job):
    """Why this sender doesn't get an answer by itself, or ""."""
    if role in ROLES or str(addr or "").lower() in site_people(job):
        return ""
    return f"it's from {role}: only Network Rail and the order's site contacts are answered by themselves"


def answer_text(job, sender):
    """His own booking email (book_run.words), as plain text: Outlook adds his signature."""
    import book_run
    html = book_run.words(book_run.first_name(sender), job.get("carrier") or "", job.get("haulier") or "", job["date"],
                          job["trips"], job.get("record_copy") or {})
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"<br\s*/?>", "\n", html)).strip()


def text_checks(text, job):
    bad = [f"{t['manifest']} missing" for t in job["trips"] if t["manifest"] not in text]
    if "£" in text:
        bad.append("a price")
    if "—" in text or "–" in text:
        bad.append("an em dash")
    if "<" in text or ">" in text:
        bad.append("markup left in")
    if len(text) > 900:
        bad.append("too long")
    return bad


# ---------- CTMS, read there and then ----------
def _route(args, run=subprocess.run):
    """One CTMS route (reads only) -> its ROUTE_RESULT; {"ok": False, "said": why} when there's none."""
    try:
        p = run([sys.executable, ROUTES] + list(args), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=CHECK_WAIT, cwd=HERE, creationflags=0x08000000 if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "said": "CTMS took too long to answer"}
    except OSError as e:
        return {"ok": False, "said": f"the CTMS route couldn't start ({e})"}
    for line in reversed(str(p.stdout or "").splitlines()):
        if line.startswith("ROUTE_RESULT "):
            try:
                got = json.loads(line[len("ROUTE_RESULT "):])
                return got if isinstance(got, dict) else {"ok": False, "said": "an answer in the wrong form"}
            except ValueError:
                break
    tail = (str(p.stderr or "") + "\n" + str(p.stdout or "")).strip().splitlines()
    return {"ok": False, "said": (tail[-1] if tail else "no answer")[:160]}


def _num(man):
    m = re.search(r"\d{8}", str(man or ""))
    return m.group(0) if m else ""


def _booking_lock():
    """Book's own lock (one booking at a time): the check never drives CTMS while a booking runs. -> a handle, True
    without pywin32, or None while a booking holds it."""
    try:
        import outlook_gate
        return outlook_gate.named_lock("book_run", wait=0)
    except Exception:
        return True


def _let_go(h):
    if h not in (None, True):
        try:
            import outlook_gate
            outlook_gate.release(h)
        except Exception:
            pass


def _stop_at(st):
    """When a Stops row's work starts: its planned arrival plus any Wait (a lorry early for its window waits there),
    as a datetime, or None. The first row's number cell can be missing, so its date lands in Stop (seen 24/11)."""
    day = str(st.get("Date") or "").strip()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{2}", day):
        day = str(st.get("Stop") or "").strip()
    try:
        at = datetime.strptime(f"{day} {str(st.get('P Arr') or '').strip()}", "%d/%m/%y %H:%M")
    except ValueError:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(st.get("Wait") or "").strip())
    return at + timedelta(hours=int(m.group(1)), minutes=int(m.group(2))) if m else at


def delivery_matches(stops, deliver):
    """(True, the delivery stop's time) when one of the trip's delivery stops (DROP_TYPES) - its arrival plus its wait -
    is within DRIFT of the time Book booked; (False, what CTMS has)."""
    try:
        want = datetime.strptime(str(deliver or "")[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return False, "Book's journal has no delivery time for it"
    drops = [_stop_at(s) for s in stops or () if str(s.get("Type") or "").strip().upper() in DROP_TYPES]
    if not drops:
        return False, "CTMS shows no delivery stop on the trip"
    near = [at for at in drops if at is not None and abs(at - want) <= DRIFT]
    if near:
        return True, near[0]
    got = ", ".join(f"{at:%d/%m %H:%M}" for at in drops if at is not None) or "no time"
    return False, f"CTMS delivers at {got}, Book booked {want:%d/%m %H:%M}"


def ctms_check(job, now, run=subprocess.run, lock=_booking_lock):
    """Each manifest found in Planning by its order line (trip-read --order LINE --tabs stops, reads only - by line,
    because a trip can have no EFX ref to find it by: 26/11's 52 seconds for nothing): the trip CTMS selects is that
    manifest, ACCEPTED, and one of its delivery stops is on the day Book booked, within the hour of its time.
    -> (True, what was seen) or (False, why not)."""
    try:
        import outlook_gate
        if outlook_gate._toolkit_off():
            return False, "the toolkit is switched off"
    except Exception:
        pass
    h = lock()
    if h is None:
        return False, "a booking is running in CTMS"
    try:
        seen = []
        for t in job["trips"]:
            man = t["manifest"]
            line = next((str(x) for x in t.get("lines") or () if str(x).strip()), "")
            if not line:
                return False, f"Book's journal has no order line to find {man} by"
            got = _route(["trip-read", "--order", line, "--tabs", "stops"], run)
            if not got.get("ok"):
                return False, "CTMS couldn't be read: " + str(got.get("said") or "no answer")[:140]
            if got.get("found") != "selected":
                return False, f"CTMS lists more than one trip for {line}"
            if _num(got.get("man")) != _num(man):
                return False, f"CTMS has {got.get('man')} for {line}, not {man}"
            if str(got.get("status") or "").upper() != "ACCEPTED":
                return False, f"{man} is {got.get('status') or 'not known'} in CTMS, not ACCEPTED"
            ok, at = delivery_matches(got.get("stops"), t.get("deliver"))
            if not ok:
                return False, f"{man}: {at}"
            seen.append(f"{man} delivering {at:%d/%m %H:%M}")
        return True, f"CTMS {now:%d/%m %H:%M}: {', '.join(seen)}, ACCEPTED as booked"
    finally:
        _let_go(h)


# ---------- the answer kept on the email ----------
def answer(it, role, jobs, records, now, check=None, tries=0):
    """One booking question -> what is kept on the email (it["auto"]):
         state  ready (checked in CTMS: it may go), unchecked (CTMS couldn't confirm it: his one tap, or tried again),
                held (not one to answer by itself: why says why), later sent / failed
         text   the answer (ready / unchecked), why, job, mans, checked_at, tries, said"""
    a = {"at": now.strftime(STAMP), "state": "held", "why": "", "text": "", "job": "", "mans": [], "checked_at": "",
         "tries": int(tries or 0), "said": ""}
    k, job, why = find_job(it.get("orders"), jobs)
    if job is None:
        return dict(a, why=why)
    why = check_job(job, now, records) or sender_ok(role, it.get("addr"), job)
    if why:
        return dict(a, why=why, job=k)
    text = answer_text(job, it.get("from"))
    bad = text_checks(text, job)
    if bad:
        return dict(a, why="the answer failed its checks: " + "; ".join(bad), job=k)
    a.update(text=text, job=k, mans=[t["manifest"] for t in job["trips"]])
    ok, said = (check or ctms_check)(job, now)
    a.update(checked_at=now.strftime(STAMP), tries=a["tries"] + 1, said=str(said)[:200])
    a.update(state="ready", why="") if ok else a.update(state="unchecked", why=str(said)[:200])
    return a


def note(a, mode):
    """The line under the email on his card."""
    st = (a or {}).get("state")
    if st == "ready":
        return ("Sending it myself: " if mode == "live" else "I'd send this myself (shadow): ") + str(a.get("said") or "")
    if st == "unchecked":
        return "From Book, but not sent by itself: " + str(a.get("why") or "")
    if st == "failed":
        return "Couldn't send it myself: " + str(a.get("why") or "")
    return ""


def stale(a, now):
    return _age((a or {}).get("checked_at"), now) >= FRESH


def due(it, now, mode, holidays=()):
    """This email's answer goes now."""
    a = it.get("auto") or {}
    return (mode == "live" and it.get("state") == "open" and it.get("kind") == "needs" and a.get("state") == "ready"
            and bool(a.get("text")) and in_hours(now, holidays) and not stale(a, now))


def recheck_due(it, now, mode, holidays=()):
    """CTMS couldn't confirm it (or the check went stale): try again, half-hourly in working hours, live only."""
    a = it.get("auto") or {}
    return (mode == "live" and it.get("state") == "open" and it.get("kind") == "needs"
            and a.get("state") == "unchecked" and int(a.get("tries") or 0) < TRIES
            and _age(a.get("checked_at"), now) >= RETRY and in_hours(now, holidays))


def recipient_checks(people, ctx, sender=""):
    """Who a reply to all would reach, checked before an answer goes by itself - [] when it may."""
    import inbox_watch as iw
    bad = []
    hauls, doms = set(ctx.get("haulier_addrs") or ()), set(ctx.get("haulier_domains") or ())
    for p in people:
        dom = p.rsplit("@", 1)[-1]
        if p in hauls or (dom in doms and dom not in iw.SHARED):
            bad.append(f"a haulier ({p}) is on the thread")
    if len(people) > MAX_PEOPLE:
        bad.append(f"{len(people)} people on it")
    if sender and str(sender).lower() not in people:
        bad.append("the sender isn't on the reply")
    return bad
