"""An email already in about an order means no ask goes (his 27/11). Two new orders came with their details in Network
Rail threads forwarded to him, naming them in the subject; the build only ever looked at what had been SENT, so it lined
up asks for details that were in, and neither order reached the map. His rule: an email from the site or Network Rail
that names the order means no ask - not in the batch, not from the wait-list later. The order goes on the map instead,
with that email named, to check and put in CTMS, and nothing says it was emailed.

The real build_drafts, with a stand-in served in place of the private config.json it reads at import; Outlook stood in
for; the tracker, wait list, pins and metrics in a temp folder. Made-up orders, names and addresses only.

    python -m pytest -q tests/test_details_in.py
"""
import builtins
import importlib.util
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ctms_notes  # noqa: E402
import metrics  # noqa: E402
import pins  # noqa: E402
import reply_kind  # noqa: E402
import tracker  # noqa: E402
import waitlist  # noqa: E402
from modules import chase_rules  # noqa: E402

STAND_IN_CONFIG = {"active_region": "r2", "regions": {"r2": {"postcode_areas": ["EX"]}},
                   "email_source": {"only_file": "Example_Haulier_Extract", "also_batches": []}}
DAY = (datetime.now() + timedelta(days=9)).strftime("%d/%m/%Y")      # a delivery still to come
C = {"order": 0, "prod": 1, "prod_code": 2, "qty": 3, "date": 4, "dpc": 5, "dcon": 6, "daddr": 7, "dpoint": 8, "instr": 9}
KIM = "Kim Example email: kim.example@site.example"
NOW = datetime.now()
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
TODAY = NOW.strftime("%Y-%m-%d %H:%M")


def row(order, prod, code, qty, contact=KIM, day=DAY):
    return [order + "-1-1", prod, code, qty, day, "EX1 1AA", contact, "Example Yard", "Example Worksite 2609676", ""]


SLEEPER = ("Concrete sleeper G44", "SL44")


def _load_build_drafts():
    cfg = os.path.abspath(os.path.join(ROOT, "config.json"))
    real_open = builtins.open

    def open_(file, *a, **k):
        if isinstance(file, (str, os.PathLike)) and os.path.abspath(file) == cfg:
            return io.StringIO(json.dumps(STAND_IN_CONFIG))
        return real_open(file, *a, **k)
    spec = importlib.util.spec_from_file_location("build_drafts", os.path.join(ROOT, "build_drafts.py"))
    mod = importlib.util.module_from_spec(spec)
    with mock.patch("builtins.open", open_):
        spec.loader.exec_module(mod)
    return mod


LOADED = ("phase2", "send_order", "order_pin", "waitlist_release")


@pytest.fixture
def bd(tmp_path, monkeypatch):
    mod = _load_build_drafts()
    monkeypatch.setitem(sys.modules, "build_drafts", mod)
    monkeypatch.setattr(mod, "HERE", str(tmp_path))
    monkeypatch.setattr(mod, "PENDING_BATCH", str(tmp_path / "_pending_batch.json"))
    monkeypatch.setattr(tracker, "PATH", str(tmp_path / "tracker.json"))
    monkeypatch.setattr(tracker, "DROPS", str(tmp_path / "_booked_drops.json"))
    monkeypatch.setattr(waitlist, "PATH", str(tmp_path / "waitlist.json"))
    monkeypatch.setattr(metrics, "PATH", str(tmp_path / "_metrics.jsonl"))
    monkeypatch.setattr(pins, "PATH", str(tmp_path / "_pins.json"))
    monkeypatch.setattr(mod, "_tracker_lock", lambda wait=30: "LOCK")     # no real mutex in a test
    monkeypatch.setattr(reply_kind, "haulier_of",
                        lambda addr, directory=None: "Example Haulage" if "@haulage.example" in str(addr) else "")
    for name in LOADED:
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield mod
    for name in LOADED:
        sys.modules.pop(name, None)


def group(bd, rows):
    emails, *_ = bd.build_emails_multi([(rows, C, "Example_Haulier_Extract.xlsx")])
    assert len(emails) == 1
    return emails[0]


def mail(subject, sender, when=YESTERDAY, who="Someone", eid="EID-1", folder="Inbox/Regions/Region 2/Completed"):
    return {"subject": subject, "sender": sender, "who": who, "when": when, "entryid": eid, "folder": folder}


def records():
    return tracker.load()["records"]


# ---------- whose email about an order counts ----------
def test_network_rail_a_colleague_and_the_site_count(bd):
    g = {"orders": ["9100001"], "to": "kim.example@site.example"}
    assert bd.mail_counts("lee.example@networkrail.co.uk", g)            # Network Rail's team, or DHL Road on theirs
    assert bd.mail_counts("pat.example@dhl.com", g)                       # a colleague forwarding the thread
    assert bd.mail_counts("kim.example@site.example", g)                  # the site contact
    assert bd.mail_counts("sam.other@site.example", g)                    # someone at the site's own firm


def test_a_haulier_a_supplier_himself_and_nobody_do_not(bd):
    g = {"orders": ["9100001"], "to": "kim.example@gmail.com"}
    assert not bd.mail_counts("desk@haulage.example", g)                  # a quote: hauliers don't update orders
    assert not bd.mail_counts("sales@supplier.example", g)                # the supplier, about availability
    assert not bd.mail_counts(bd.DHL_SMTP, g)                             # his own, copied to himself
    assert not bd.mail_counts("no-reply@networkrail.co.uk", g)
    assert not bd.mail_counts("someone.else@gmail.com", g)                # a shared mail service: the address only
    assert bd.mail_counts("kim.example@gmail.com", g)
    assert not bd.mail_counts("", g) and not bd.mail_counts("Lee Example", g)


def test_the_orders_own_thread_counts_but_not_a_list_a_bounce_or_a_haulier_thread(bd):
    gs = [{"orders": ["9100001"], "to": "kim.example@site.example"}, {"orders": ["9100005"], "to": ""}]
    got = bd.details_from_mails([
        mail("FW: RD100001 9100009 NEW RD100002 9100001", "lee.example@networkrail.co.uk", eid="E-FWD"),
        mail("Region 2 updates 9100001 9100002 9100003 9100004", "boss.example@dhl.com", eid="E-LIST"),
        mail("Undeliverable: 9100005 Example Yard", "pat.example@dhl.com", eid="E-NDR"),
        mail("Automatic reply: 9100005 Example Yard", "pat.example@dhl.com", eid="E-OOO"),
        mail("RE: 9100005 Delivery", "lee.example@networkrail.co.uk", eid="E-HAUL"),
        mail("RE: 9100005 / 9100006 Delivery", "lee.example@networkrail.co.uk", eid="E-HAUL2"),
        mail("RE: 91000051 Example", "lee.example@networkrail.co.uk", eid="E-LONGER"),   # not the order: a longer number
    ], gs)
    assert {o: m["entryid"] for o, m in got.items()} == {"9100001": "E-FWD"}


def test_the_newest_counting_email_is_the_one_kept(bd):
    gs = [{"orders": ["9100001"], "to": ""}]
    got = bd.details_from_mails([
        mail("URGENT ORDER RD1 9100001", "lee.example@networkrail.co.uk", when="2026-11-26 14:48", eid="OLD"),
        mail("FW: EXT: URGENT ORDER RD1 9100001", "max.example@networkrail.co.uk", when="2026-11-27 06:39", eid="NEW"),
        mail("RE: URGENT ORDER RD1 9100001", "sales@supplier.example", when="2026-11-27 08:00", eid="SUPPLIER"),
    ], gs)
    assert got["9100001"]["entryid"] == "NEW"


# ---------- the Outlook search ----------
class Item:
    def __init__(self, subject, sender, when, eid, cls=43):
        self.Subject, self.SenderEmailAddress, self.SenderName = subject, sender, "Someone"
        self.ReceivedTime, self.EntryID, self.Class = when, eid, cls


class Items(list):
    def __init__(self, items, asked):
        super().__init__(items)
        self.asked = asked

    def Restrict(self, flt):
        self.asked.append(flt)
        want = re.findall(r"LIKE '%([0-9]+)%'", flt)
        return [it for it in self if any(o in it.Subject for o in want)]


class Folders(list):
    @property
    def Count(self):
        return len(self)

    def Item(self, i):
        return self[i - 1]


class Folder:
    def __init__(self, name, items=(), subs=(), kind=0, asked=None):
        self.Name, self.DefaultItemType = name, kind
        self.Items = Items(items, asked if asked is not None else [])
        self.Folders = Folders(subs)


def test_the_search_asks_outlook_only_for_the_orders_and_walks_every_folder(bd, monkeypatch):
    asked = []
    old = NOW - timedelta(days=bd.DETAILS_DAYS + 2)
    done = Folder("Completed", [Item("Fw: URGENT ORDER RD1 9100001", "lee.example@networkrail.co.uk",
                                     NOW - timedelta(hours=3), "E-1")], asked=asked)
    region = Folder("Region 2", subs=[done], asked=asked)
    cal = Folder("Calendar", [Item("9100002 site visit", "lee.example@networkrail.co.uk", NOW, "E-CAL")], kind=1,
                 asked=asked)
    inbox = Folder("Inbox", [
        Item("RE: 9100002 Example Yard", "kim.example@site.example", old, "E-OLD"),              # older than the window
        Item("Read: 9100002 Example Yard", "kim.example@site.example", NOW, "E-RCPT", cls=46),  # a receipt, not mail
        Item("RE: 9100003 Example Yard", "kim.example@site.example", NOW - timedelta(hours=1), "E-3"),
    ], subs=[region, cal], asked=asked)
    monkeypatch.setattr(bd, "dhl_store", lambda ns: "store")
    monkeypatch.setattr(bd, "sub", lambda parent, name: inbox if (parent, name) == ("store", "Inbox") else None)
    import chase_guard
    monkeypatch.setattr(chase_guard, "_smtp_of_sender", lambda it: it.SenderEmailAddress.lower())
    monkeypatch.setattr(bd, "DETAILS_CHUNK", 2)
    gs = [{"orders": ["9100001", "9100002"], "to": "kim.example@site.example"},
          {"orders": ["9100003"], "to": "kim.example@site.example"}]
    got = bd.find_details_in(None, gs)
    assert {o: (m["entryid"], m["folder"]) for o, m in got.items()} == {
        "9100001": ("E-1", "Inbox/Region 2/Completed"),
        "9100003": ("E-3", "Inbox")}
    # two filters a folder (2 orders, then 1), for the Inbox and its two mail folders - never the calendar
    assert len(asked) == 6 and all(f.startswith("@SQL=") for f in asked)
    assert "9100001" in asked[0] and "9100002" in asked[0] and "9100003" in asked[1]


def test_no_inbox_is_an_error_not_an_empty_answer(bd, monkeypatch):
    monkeypatch.setattr(bd, "dhl_store", lambda ns: None)
    monkeypatch.setattr(bd, "sub", lambda parent, name: None)
    with pytest.raises(RuntimeError):
        bd.find_details_in(None, [{"orders": ["9100001"], "to": ""}])
    assert bd.find_details_in(None, []) == {}


# ---------- onto the map, never as emailed ----------
def test_the_whole_delivery_goes_on_the_map_and_nothing_says_it_was_emailed(bd):
    e = group(bd, [row("9100001", *SLEEPER, 40), row("9100002", *SLEEPER, 20)])
    e["_details"] = {"9100001": mail("FW: RD1 9100001", "lee.example@networkrail.co.uk", who="Lee Example")}
    assert bd.enrol_details_in([e]) == (1, True)
    [r] = records()
    assert r["orders"] == ["9100001", "9100002"] and r["delivery_date"] == DAY
    assert r["status"] == tracker.DETAILS_IN and r["emailed_at"] is None and r["last_emailed_at"] is None
    assert r["reply_at"] == YESTERDAY and r["sendoff_ready"] and r["source"] == "details already in"
    assert r["details_in"]["subject"] == "FW: RD1 9100001" and r["details_in"]["who"] == "Lee Example"
    assert r["details_in"]["named"] == ["9100001"]                       # the map says to check 9100002 is covered
    assert ctms_notes.owed(records()) == []                              # no "Emailed DO" note for CTMS
    assert not chase_rules.escalate_due(r, NOW)                          # never escalated for want of a reply
    assert bd._already_done_orders() == {"9100001", "9100002"}           # the next build asks neither
    assert bd.enrol_details_in([e]) == (0, True)                         # put on once


def test_a_booked_order_never_comes_back_and_a_busy_tracker_puts_nothing_on(bd, monkeypatch):
    e = group(bd, [row("9100001", *SLEEPER, 40)])
    e["_details"] = {"9100001": mail("FW: RD1 9100001", "lee.example@networkrail.co.uk")}
    tracker.remember_drops(["9100001"])
    assert bd.enrol_details_in([e]) == (0, True) and records() == []
    monkeypatch.setattr(bd, "_tracker_lock", lambda wait=30: None)
    tracker.remember_drops([])
    with open(tracker.DROPS, "w", encoding="utf-8") as f:
        json.dump([], f)
    assert bd.enrol_details_in([e]) == (0, False) and records() == []


def test_book_waits_for_ctms_to_have_the_details(bd):
    import book_run
    rec = {"orders": ["9100001"], "kind": "delivery", "reply_at": YESTERDAY,
           "details_in": {"who": "Lee Example", "when": YESTERDAY, "subject": "FW: RD1 9100001"}}
    assert "put the details in CTMS first" in book_run.not_ready(rec)
    assert book_run.not_ready(dict(rec, ctms_veh=True)) == ""             # Veh Type filled: they are in CTMS now
    assert book_run.not_ready(dict(rec, phoned_at=TODAY)) == ""


# ---------- the daily run ----------
def _daily_run(bd, monkeypatch, capsys, rows, found, mode="batch"):
    monkeypatch.setattr(sys, "argv", ["build_drafts.py", mode])
    monkeypatch.setattr(bd, "get_ns", lambda: None)
    monkeypatch.setattr(bd, "find_inbox_extracts", lambda ns: [("x.xlsx", "Example_Haulier_Extract.xlsx")])
    monkeypatch.setattr(bd, "find_synergy_upload", lambda ns, **k: [])
    monkeypatch.setattr(bd, "find_bs_tree", lambda ns, **k: [])
    monkeypatch.setattr(bd, "load_rows", lambda p: (rows, C))
    monkeypatch.setattr(bd.site_contacts, "remember", lambda emails: None)
    monkeypatch.setattr(bd, "find_already_emailed", lambda ns, orders, limit=0: {})
    monkeypatch.setattr(bd, "find_emailed_deliveries", lambda ns, groups, limit=0: {})
    monkeypatch.setattr(bd, "find_collection_sent", lambda ns, orders: set())
    monkeypatch.setattr(bd, "find_details_in", found)
    bd.main()
    out = capsys.readouterr().out
    if mode != "batch":
        return out, None                     # only a batch run writes the dashboard's batch
    with open(bd.PENDING_BATCH, encoding="utf-8") as f:
        batch = json.load(f)
    return out, batch


def test_an_order_with_an_email_in_is_not_asked_and_goes_on_the_map(bd, monkeypatch, capsys):
    rows = [row("9100001", *SLEEPER, 40),
            row("9100003", *SLEEPER, 10, contact="Max Example email: max.example@other.example")]
    lee = mail("FW: URGENT ORDER RD1 9100001", "lee.example@networkrail.co.uk", who="Lee Example")
    out, batch = _daily_run(bd, monkeypatch, capsys, rows, lambda ns, groups: {"9100001": lee})
    assert [b["orders"] for b in batch] == [["9100003"]]                 # only the other one is asked
    assert "EMAIL IS ALREADY IN" in out and "FW: URGENT ORDER RD1 9100001" in out and "email already in: 1" in out
    [r] = records()
    assert r["orders"] == ["9100001"] and r["status"] == tracker.DETAILS_IN


def test_a_far_ahead_order_with_an_email_in_is_not_wait_listed_either(bd, monkeypatch, capsys):
    far = (datetime.now() + timedelta(days=60)).strftime("%d/%m/%Y")
    lee = mail("FW: RD1 9100001", "lee.example@networkrail.co.uk")
    _daily_run(bd, monkeypatch, capsys, [row("9100001", *SLEEPER, 40, day=far)],
               lambda ns, groups: {"9100001": lee}, mode="waitscan")
    assert waitlist.load()["entries"] == []
    assert [r["delivery_date"] for r in records()] == [far]


def test_when_the_mail_check_fails_the_batch_still_builds_and_says_so(bd, monkeypatch, capsys):
    def broken(ns, groups):
        raise RuntimeError("Outlook said no")
    out, batch = _daily_run(bd, monkeypatch, capsys, [row("9100001", *SLEEPER, 40)], broken)
    assert [b["orders"] for b in batch] == [["9100001"]]
    assert "received-mail check could not run" in out and "Check before you Send" in out
    assert records() == []


# ---------- the wait list's release ----------
def test_the_release_takes_an_entry_with_an_email_in_off_the_send_list(bd):
    import waitlist_release as wr
    a = {"id": "9100001|" + DAY, "orders": ["9100001"], "date": DAY, "to": "kim.example@site.example"}
    b = {"id": "9100002|" + DAY, "orders": ["9100002"], "date": DAY, "to": "kim.example@site.example"}
    c = {"id": "9100003|" + DAY, "orders": ["9100003"], "date": DAY, "to": "kim.example@site.example"}
    lee = mail("FW: RD1 9100001", "lee.example@networkrail.co.uk")
    max_ = mail("FW: RD2 9100003", "max.example@networkrail.co.uk")
    keep, closing, holding = wr.mail_in_split([a, b, c], {"9100001": lee, "9100003": max_},
                                              lambda e: ["01/01/2030"] if e is c else [])
    assert keep == [b] and closing == [(a, lee)] and holding == [(c, max_)]   # on other days too: held, not closed


def test_closing_puts_it_on_the_map_and_off_the_wait_list(bd):
    import waitlist_release as wr
    e = group(bd, [row("9100001", *SLEEPER, 40)])
    e["date"] = DAY
    assert waitlist.add(e)
    [w] = waitlist.load()["entries"]
    wr.close_mail_in(w, mail("FW: RD1 9100001", "lee.example@networkrail.co.uk", who="Lee Example"))
    [w] = waitlist.load()["entries"]
    assert w["status"] == "closed" and "an email came in about it" in w["note"] and waitlist.due() == []
    [r] = records()
    assert r["status"] == tracker.DETAILS_IN and r["emailed_at"] is None and r["details_in"]["named"] == ["9100001"]
