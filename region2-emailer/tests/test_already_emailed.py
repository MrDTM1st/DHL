"""Plain-assert tests for the "you already emailed it" guard and the wait-list
dry run - both from 26/10/2026, when the 16/10 handover to a colleague (internal,
naming six orders still to be emailed) was read as the planner having emailed all
six, and a dry run of the release closed nine held orders.

It needs the real build_drafts, which reads the private config.json at import:
without it (a plain archive copy, as the deploy gate runs) the file is skipped.

Run:  python region2-emailer/tests/test_already_emailed.py
"""
import os
import sys
from contextlib import contextmanager
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

# A file collected before this one (test_adhoc_booked_sweep) can leave a stand-in
# build_drafts in sys.modules, with no HERE for waitlist_release -> send_order to
# read. It is set aside for the real one, and put back if the real one cannot load.
# Once the real one has loaded it stays: the modules this file loads are bound to it.
_stand_in = sys.modules.get("build_drafts")
if _stand_in is not None and not hasattr(_stand_in, "HERE"):
    del sys.modules["build_drafts"]
else:
    _stand_in = None
try:
    import build_drafts as bd  # noqa: E402
except OSError:
    if os.path.exists(os.path.join(ROOT, "config.json")):
        raise                                   # the config is there: a real failure, not this
    if _stand_in is not None:
        sys.modules["build_drafts"] = _stand_in
    _WHY = "needs the private config.json, which build_drafts reads at import - this copy has none"
    if __name__ != "__main__" and "pytest" in sys.modules:
        import pytest
        pytest.skip(_WHY, allow_module_level=True)
    print("test_already_emailed: skipped - " + _WHY)
    sys.exit(0)
import waitlist  # noqa: E402
import waitlist_release as wr  # noqa: E402

# These cases were written on 26/10/2026: their deliveries (02/11, 10/11, 24/11) still
# to come and their October mail inside the release's look-back. The release code runs
# on that day: for each call, waitlist_release's clock and build_drafts._is_future are
# pinned to it and put back straight after, so no other test file sees a fixed day.
# The system clock is never touched.
DAY = datetime(2026, 10, 26, 12, 0)


class _OnDay(datetime):
    """waitlist_release's datetime, with now() on DAY."""
    @classmethod
    def now(cls, tz=None):
        return cls(DAY.year, DAY.month, DAY.day, DAY.hour, DAY.minute)


def _is_future_on_day(dd):
    """build_drafts._is_future's own rule with DAY as today: unreadable fails open."""
    try:
        return datetime.strptime(str(dd).strip()[:10], "%d/%m/%Y").date() >= DAY.date()
    except Exception:
        return True


@contextmanager
def on_day():
    saved = wr.datetime, bd._is_future
    wr.datetime, bd._is_future = _OnDay, _is_future_on_day
    try:
        yield
    finally:
        wr.datetime, bd._is_future = saved


class User:
    def __init__(self, smtp):
        self.PrimarySmtpAddress = smtp


class Entry:
    def __init__(self, smtp):
        self.smtp = smtp

    def GetExchangeUser(self):
        if self.smtp is None:
            raise RuntimeError("not an Exchange user")
        return User(self.smtp)


class Rcpt:
    def __init__(self, address, smtp=None):
        self.Address = address            # SMTP, or the X500 "/o=..." form
        self.AddressEntry = Entry(smtp)


class Rcpts:
    def __init__(self, rs):
        self.rs = rs
        self.Count = len(rs)

    def Item(self, k):
        return self.rs[k - 1]


class Mail:
    def __init__(self, subject, body, rcpts, when="16/10/2026 17:54"):
        self.Subject, self.Body = subject, body
        self.Recipients = Rcpts(rcpts)
        self.To = "; ".join(r.Address for r in rcpts)
        self.EntryID = subject
        self.SentOn = self.LastModificationTime = datetime.strptime(when, "%d/%m/%Y %H:%M")


class Items(list):
    def Sort(self, *a):
        pass


class Folder:
    def __init__(self, mails):
        self.Items = Items(mails)


SAM_X500 = Rcpt("/o=ExchangeLabs/ou=Exchange/cn=Recipients/cn=sam", "sam.clerk@dhl.com")
JO = Rcpt("jo.colleague@dhl.com")
SITE = Rcpt("robin.field@networkrail.co.uk")

# --- _internal_only --------------------------------------------------------
assert bd._internal_only(Mail("h", "", [SAM_X500, JO]))
assert not bd._internal_only(Mail("h", "", [SAM_X500, SITE]))
assert not bd._internal_only(Mail("h", "", []))                      # unreadable -> contact
assert not bd._internal_only(Mail("h", "", [Rcpt("/o=x/cn=list", None)]))   # DL -> contact
assert not bd._internal_only(Mail("h", "", [Rcpt("someone@dhl.com.evil.co")]))


def found_in(sent, orders):
    real = bd.dhl_store, bd.sub
    bd.dhl_store = lambda ns: None
    bd.sub = lambda root, name: Folder(sent) if name == "Sent Items" else Folder([])
    try:
        return bd.find_already_emailed(None, orders)
    finally:
        bd.dhl_store, bd.sub = real


HANDOVER = Mail("Region 2 handover - away Mon 19/10 to Fri 23/10, back Mon 26/10",
                "SITE STILL TO BE CONTACTED\n - 9100320, Trackwork Doncaster to Tuxford\n"
                " - 9100305, British Steel to Haxey", [SAM_X500], )
TO_SITE = Mail("9100305 Haxey CCTV Level Crossing DN9 2NL", "Hi Robin, I've got 4x rails",
               [SITE], when="15/10/2026 09:00")
BOOKED_INTERNAL = Mail("RE: 9100320", "This order has been arranged with NOC. MAN-01905111",
                       [JO], when="14/10/2026 10:00")

# the handover alone is not contact with either site
assert found_in([HANDOVER], {"9100320", "9100305"}) == {}
# a real email to the site still counts, even behind the newer handover
got = found_in([HANDOVER, TO_SITE], {"9100305"})
assert set(got) == {"9100305"} and got["9100305"]["when"] == "15/10/2026 09:00", got
# a booking stays a booking whoever it went to
got = found_in([BOOKED_INTERNAL], {"9100320"})
assert got["9100320"]["booked"] and got["9100320"]["ref"] == "MAN-01905111", got

# --- colleagues' emails, seen from anywhere in the mailbox -----------------
# Built through the REAL MailIndex._add from fake Outlook items: the index
# keeps recipients only for the planner's own sent mail, which a hand-made index
# hid the first time (a colleague's copy to the planner came out with no recipients).
import chase_guard  # noqa: E402

REAL_INDEX = chase_guard.MailIndex
AT = datetime(2026, 10, 23, 14, 50)


class R:
    def __init__(self, address, typ=1):
        self.Address, self.Type = address, typ


class Item:
    Class, MessageClass, Sent, ConversationID = 43, "IPM.Note", True, "c"

    def __init__(self, eid, frm, to, subject, body="", at=AT, cc=(), sent=True):
        self.EntryID, self.SenderEmailAddress, self.SenderName = eid, frm, frm
        self.Subject, self.Body, self.Sent = subject, body, sent
        self.ReceivedTime = self.SentOn = self.CreationTime = at
        self.Recipients = Rcpts([R(a) for a in to] + [R(a, 2) for a in cc])


class NS:
    items = {}

    def GetItemFromID(self, eid, store=None):
        return NS.items[eid]


def index_of(inbound, outbound=(), errors=()):
    NS.items = {i.EntryID: i for i in list(inbound) + list(outbound)}

    def make(ns, since):
        idx = object.__new__(REAL_INDEX)
        idx.ns, idx.store_id = ns, "s"
        idx.mails, idx._seen, idx._text = [], set(), {}
        idx.errors, idx.item_errors, idx.started_at = list(errors), [], datetime.now()
        for i in inbound:
            idx._add(i, "in", "/Inbox/Regions/Region 2", since)
        for i in outbound:
            idx._add(i, "out", "/Sent Items", since)
        return idx
    return make


SITE_ADDR = "chris.track@networkrail.co.uk"
ME = bd.DHL_SMTP                        # the desk's own address
held = {"id": "9100320|02/11/2026", "orders": ["9100320"], "to": SITE_ADDR,
        "added_at": "2026-10-07 21:03", "date": "02/11/2026"}
saved_idx, saved_fresh, saved_load = chase_guard.MailIndex, chase_guard.mailbox_fresh, waitlist.load
chase_guard.mailbox_fresh = lambda ns, idx, now=None: (True, "")
waitlist.load = lambda: {"entries": [held]}


def check(inbound=(), outbound=(), entry=held, errors=()):
    chase_guard.MailIndex = index_of(inbound, outbound, errors)
    with on_day():
        return wr._contact_check(NS(), [entry]).get(entry["id"])


try:
    # a colleague to the site, the planner copied - the 23/10 case, as Outlook files it
    v = check([Item("a", "jo.colleague@dhl.com", [SITE_ADDR], "9100320 - NG22 0NR - TUXFORD",
                    cc=[ME])])
    assert v and v[0] == "contacted" and "jo.colleague@dhl.com" in v[1], v
    # order only in the body
    v = check([Item("b", "jo.colleague@dhl.com", [SITE_ADDR], "Tuxford timbers",
                    body="Hi Chris, 9100320 - 7x timbers wc 02/11")])
    assert v and v[0] == "contacted", v
    # the planner's own email to the site from Sent Items
    v = check(outbound=[Item("o", ME, [SITE_ADDR], "9100320 Tuxford")])
    assert v and v[0] == "contacted", v
    # the site asking about it is not an ask from us - hold, don't close
    v = check([Item("s", SITE_ADDR, [ME], "Any news on 9100320?")])
    assert v and v[0] == "hold", v
    # another order, a draft, before the hold, the handover, a haulier: nothing
    assert check([Item("c", SITE_ADDR, [ME], "9100325"),
                  Item("d", "jo.colleague@dhl.com", [SITE_ADDR], "9100320", sent=False),
                  Item("e", "jo.colleague@dhl.com", [SITE_ADDR], "9100320", at=datetime(2026, 10, 1)),
                  Item("f", "jo.colleague@dhl.com", [ME], "FW: 9100320"),
                  Item("h", "traffic@haulier-one.co.uk", [ME], "RE: 9100320")],
                 outbound=[Item("g", ME, ["sam.clerk@dhl.com"], "Region 2 handover",
                                body="SITE STILL TO BE CONTACTED - 9100320")]) is None
    # two orders, only one emailed - hold for the rest
    two = dict(held, id="9100330-9100335|10/11/2026", orders=["9100330", "9100335"])
    v = check([Item("p", "jo.colleague@dhl.com", [SITE_ADDR], "9100330 Colas")], entry=two)
    assert v and v[0] == "hold" and "9100330" in v[1], v
    # an unreadable colleague email that might be it - hold, try again
    NS_bad = Item("u", "jo.colleague@dhl.com", [SITE_ADDR], "9100320 Tuxford")
    chase_guard.MailIndex = index_of([NS_bad])
    NS.items.pop("u")
    with on_day():
        v = wr._contact_check(NS(), [held]).get(held["id"])
    assert v and v[0] == "hold", v
    # contact made under an older entry for the same order still counts
    older = dict(held, id="9100320|old", added_at="2026-10-01 09:00", status="sent")
    waitlist.load = lambda: {"entries": [older, dict(held, added_at="2026-10-25 09:00")]}
    v = check([Item("k", "jo.colleague@dhl.com", [SITE_ADDR], "9100320", at=datetime(2026, 10, 20))],
              entry=dict(held, added_at="2026-10-25 09:00"))
    assert v and v[0] == "contacted", v
    waitlist.load = lambda: {"entries": [held]}
    # a mailbox that can't be read fully raises, so a send run stops
    try:
        check(errors=["/Inbox/Regions: cannot open"])
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
finally:
    chase_guard.MailIndex, chase_guard.mailbox_fresh, waitlist.load = saved_idx, saved_fresh, saved_load

chase_guard.mailbox_fresh = lambda ns, idx, now=None: (True, "")
waitlist.load = lambda: {"entries": [held]}
try:
    # a reply that only QUOTES the order is not the ask
    v = check(outbound=[Item("q", ME, [SITE_ADDR], "RE: upcoming deliveries",
                             body="Thanks, I'll be in touch nearer the time.\nFrom: Chris Track\n"
                                  "Sent: 21 October 2026\ncoming up: 9100320 on 02/11")])
    assert v is None, v
    # an unreadable email to someone else holds nothing
    chase_guard.MailIndex = index_of([], [Item("z", ME, ["traffic@haulier-one.co.uk"],
                                               "Lunch")])
    NS.items.pop("z")
    with on_day():
        assert wr._contact_check(NS(), [held]) == {}
    # a site address picked from the address book comes through as /o=...
    x5 = Item("x", "jo.colleague@dhl.com", [], "9100320 Tuxford")
    gal = R("/o=ExchangeLabs/ou=Exchange/cn=Recipients/cn=ctrack")
    gal.AddressEntry = Entry(SITE_ADDR)
    x5.Recipients = Rcpts([gal])
    v = check([x5])
    assert v and v[0] == "contacted", v
finally:
    chase_guard.MailIndex, chase_guard.mailbox_fresh, waitlist.load = saved_idx, saved_fresh, saved_load

# --- the same delivery on the list three times -----------------------------
A = {"id": "9100330-9100333|10/11/2026", "orders": ["9100330", "9100333"], "date": "10/11/2026"}
B = {"id": "9100330-9100333-9100335|10/11/2026", "orders": ["9100330", "9100333", "9100335"], "date": "10/11/2026"}
C = {"id": "9100330-9100335|10/11/2026", "orders": ["9100330", "9100335"], "date": "10/11/2026"}
D = {"id": "9100332|10/11/2026", "orders": ["9100332"], "date": "10/11/2026"}
E = {"id": "9100332|24/11/2026", "orders": ["9100332"], "date": "24/11/2026"}   # a second delivery
ov = wr._overlapping([A, B, C, D, E], [A, B, C, D, E])
assert set(ov) == {A["id"], B["id"], C["id"]} and set(ov[A["id"]]) == {B["id"], C["id"]}, ov

# --- release(): what closes, what holds, what sends -----------------------
def run_release(due, waiting=None, every=None, done=(), tracked=None, already=None, checked=None):
    marks = []
    saved = (waitlist.due, waitlist.overdue, waitlist.mark, waitlist.waiting, waitlist.load,
             bd.get_ns, bd._already_done_orders, bd.find_already_emailed, wr._contact_check,
             wr._tracked_dates)
    # as the real ones are called: due(lead_days, today), waiting(d), overdue(today)
    waitlist.due = lambda *a, **k: list(due)
    waitlist.waiting = lambda *a, **k: list(waiting if waiting is not None else due)
    waitlist.load = lambda: {"entries": list(every if every is not None else due)}
    waitlist.overdue = lambda *a, **k: [e for e in due if e["date"].endswith("2020")]
    waitlist.mark = lambda *a, **k: marks.append(a)
    bd.get_ns = lambda: None
    bd._already_done_orders = lambda: set(done)
    bd.find_already_emailed = lambda ns, o: dict(already or {})
    wr._contact_check = lambda ns, todo: dict(checked or {})
    wr._tracked_dates = lambda: dict(tracked or {})
    try:
        with on_day():
            return wr.release(send=False), marks
    finally:
        (waitlist.due, waitlist.overdue, waitlist.mark, waitlist.waiting, waitlist.load,
         bd.get_ns, bd._already_done_orders, bd.find_already_emailed, wr._contact_check,
         wr._tracked_dates) = saved


def ent(orders, date="02/11/2026", **kw):
    return dict({"id": "-".join(orders) + "|" + date, "orders": list(orders), "site": "S",
                 "postcode": "NG22 0NR", "date": date, "to": "x@networkrail.co.uk"}, **kw)


CONTACTED = ("contacted", "already emailed 23/10/2026 14:50 by jo.colleague@dhl.com: 7")
# a dry run reports and never marks; overlap and past dates as before
r, marks = run_release([ent(["1"], "01/01/2020"), ent(["9", "10"]), ent(["9"]), ent(["7"])],
                       checked={"7|02/11/2026": CONTACTED})
assert marks == [] and r["missed"] and len(r["held"]) == 2 and len(r["skipped"]) == 1 and not r["sent"], r
assert "jo.colleague@dhl.com" in r["skipped"][0], r
# a booked-in reply closes it
r, _ = run_release([ent(["5"])], already={"5": {"where": "Sent Items", "when": "w", "to": "t",
                                                "booked": True, "ref": "MAN-01"}})
assert r["skipped"] and "booked in MAN-01" in r["skipped"][0], r
# any other Sent hit (a haulier ring-round, a draft, someone else) holds - never closes
r, _ = run_release([ent(["6"])], already={"6": {"where": "Sent Items", "when": "24/10/2026 09:00",
                                                "to": "traffic@haulier-one.co.uk", "booked": False}})
assert r["held"] and "traffic@haulier-one.co.uk" in r["held"][0] and not r["skipped"], r
# ...unless the whole-mailbox check shows the held contact was emailed
r, _ = run_release([ent(["6"])], already={"6": {"where": "Sent Items", "when": "w", "to": "t", "booked": False}},
                   checked={"6|02/11/2026": CONTACTED})
assert r["skipped"] and not r["held"], r
# 9100332 on the list for 10/11 and 24/11: 10/11's email or booking must not close 24/11
e10, e24 = ent(["9100332"], "10/11/2026", status="sent"), ent(["9100332"], "24/11/2026")
r, _ = run_release([e24], waiting=[e24], every=[e10, e24], checked={e24["id"]: CONTACTED})
assert r["held"] and "10/11/2026" in r["held"][0] and not r["skipped"], r
r, _ = run_release([e24], waiting=[e24], every=[e10, e24],
                   already={"9100332": {"where": "Sent Items", "when": "w", "to": "t", "booked": True, "ref": "M"}})
assert r["held"] and not r["skipped"], r
r, _ = run_release([e24], waiting=[e24], every=[e10, e24], done={"9100332"},
                   tracked={"9100332": {"10/11/2026"}})
assert r["held"] and "10/11/2026" in r["held"][0], r
# nothing found anywhere - it sends
r, _ = run_release([ent(["8"])])
assert r["sent"] and not r["held"], r

# --- the agent reports held and closed runs ---------------------------------
import io as _io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402


def agent_reports(report):
    buf = _io.StringIO()
    real, argv = wr.release, sys.argv
    wr.release = lambda send=False: report
    try:
        with redirect_stdout(buf):
            sys.argv = ["waitlist_release.py"]
            wr.main()
    finally:
        wr.release, sys.argv = real, argv
    low = buf.getvalue().lower()
    src = open(os.path.join(os.path.dirname(__file__), "..", "agent.py"), encoding="utf-8").read()
    keys = src.split('key == "waitlist_release":', 1)[1].split("report(", 1)[0]
    import re as _re
    words = _re.findall(r'"([^"]+)"', keys)
    return any(k in low for k in words if k not in ("waitlist_release",))


empty = {"sent": [], "skipped": [], "held": [], "missed": [], "failed": []}
assert agent_reports(dict(empty, held=["x | y | z  (why)"]))
assert agent_reports(dict(empty, skipped=["x | y | z  (why)"]))

print("test_already_emailed: all passed")
