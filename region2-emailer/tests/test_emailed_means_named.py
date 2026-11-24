"""A tracker record says its orders were emailed, and CTMS's "Emailed DO dd/mm" note is written from it, so an order goes
on only when the email that went NAMES it. His cross-check of 24/11: "Some might say I've emailed them, but I haven't
because you haven't" - Sent Items is the proof, and the tracker never claims more than that.

What went wrong: the daily run skips a group (one email per contact + site + day) as already contacted when ANY of its
orders is in Sent Items, or when its contact, postcode and day were emailed under another order number, and the WHOLE
group went on the tracker as emailed at that email's time. An order that joined a delivery after it was asked about went
on at the time of a chase that named only the first order; rails sharing a contact, a site and a day with sleepers went
on at the time of the sleepers' email, which named neither. The recovery sweep and `order_pin ... pin track` did the
same with the siblings an order's lookup brings with it.

The real build_drafts, with a stand-in served in place of the private config.json it reads at import (nothing is
written there); Outlook stood in for; the tracker, pins and metrics in a temp folder. Made-up orders, names and
addresses only.

    python -m pytest -q tests/test_emailed_means_named.py
"""
import builtins
import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timedelta
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ctms_notes  # noqa: E402
import metrics  # noqa: E402
import pins  # noqa: E402
import tracker  # noqa: E402

STAND_IN_CONFIG = {"active_region": "r2", "regions": {"r2": {"postcode_areas": ["EX"]}},
                   "email_source": {"only_file": "Example_Haulier_Extract", "also_batches": []}}
DAY = (datetime.now() + timedelta(days=9)).strftime("%d/%m/%Y")      # a delivery still to come
C = {"order": 0, "prod": 1, "prod_code": 2, "qty": 3, "date": 4, "dpc": 5, "dcon": 6, "daddr": 7, "dpoint": 8, "instr": 9}
KIM = "Kim Example email: kim.example@site.example"


def row(order, prod, code, qty, po="", contact=KIM, day=DAY):
    return [order + "-1-1", prod, code, qty, day, "EX1 1AA", contact, "Example Yard", "Example Worksite 2609676",
            f"QUOTE {po}" if po else ""]


RAIL = ("Flat bottom rail 60E2", "RL60")
SLEEPER = ("Concrete sleeper G44", "SL44")


def _load_build_drafts():
    """build_drafts from its file, reading the stand-in config instead of the private one."""
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


LOADED = ("phase2", "send_order", "order_pin")


@pytest.fixture
def bd(tmp_path, monkeypatch):
    mod = _load_build_drafts()
    monkeypatch.setitem(sys.modules, "build_drafts", mod)
    monkeypatch.setattr(mod, "HERE", str(tmp_path))
    monkeypatch.setattr(tracker, "PATH", str(tmp_path / "tracker.json"))
    monkeypatch.setattr(tracker, "DROPS", str(tmp_path / "_booked_drops.json"))
    monkeypatch.setattr(metrics, "PATH", str(tmp_path / "_metrics.jsonl"))
    monkeypatch.setattr(pins, "PATH", str(tmp_path / "_pins.json"))
    for name in LOADED:                     # imported again below, against this build_drafts
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield mod
    for name in LOADED:
        sys.modules.pop(name, None)


def records():
    return tracker.load()["records"]


def group(bd, rows):
    """The daily run's email group for these extract rows - built the way it builds them."""
    emails, *_ = bd.build_emails_multi([(rows, C, "Example_Haulier_Extract.xlsx")])
    assert len(emails) == 1
    return emails[0]


def sent(when, eid="", to="kim.example@site.example", where="Sent Items"):
    """find_already_emailed's evidence for an order (find_emailed_deliveries' has no entryid)."""
    ev = {"where": where, "when": when, "to": to, "booked": False, "ref": ""}
    if eid:
        ev["entryid"] = eid
    return ev


# ---------- tracker.named ----------
def test_an_order_is_named_only_by_its_whole_number():
    said = "9100001 (PO123) / 9100002-1-1 Example Yard EX1 1AA. Call 019100004 or ref 91000033."
    assert tracker.named(["9100001", "9100002", "9100003", "9100004"], said) == ["9100001", "9100002"]
    assert tracker.named(["9100002", "9100001"], said) == ["9100002", "9100001"]       # kept in the order given
    assert tracker.named(["9100001", ""], said) == ["9100001"]
    assert tracker.named(["9100001"], None) == [] and tracker.named(None, said) == []


# ---------- the daily run's by-hand enrolment ----------
def test_an_order_that_joined_an_asked_delivery_goes_on_alone_with_its_own_lines(bd):
    # 9100001 was asked about and chased; 9100002 joined the same contact, site and day afterwards. The chase is the
    # newest mail naming 9100001 - and the only one naming either. 9100002 had never been named.
    e = group(bd, [row("9100001", *RAIL, 10, po="PO123456"), row("9100002", *SLEEPER, 40, po="PO654321")])
    e["_seen"] = {"9100001": sent("17/11/2026 10:57", "EID-CHASE")}
    assert bd.enrol_by_hand([e]) == 1
    [r] = records()
    assert r["id"] == f"9100001|{DAY}" and r["orders"] == ["9100001"]
    assert r["emailed_at"] == "2026-11-17 10:57" and r["orig_entryid"] == "EID-CHASE" and r["status"] == "sent"
    assert r["materials"] == "10x rails" and r["product_codes"] == ["RL60"] and r["po"] == {"9100001": "PO123456"}
    assert e["_unnamed"] == ["9100002"]
    # CTMS is owed "Emailed DO 17/11" on the order the email named, and nothing on the one it did not
    assert [(n["ref"], n["note"]) for n in ctms_notes.owed(records())] == [("9100001-1-1", " - Emailed DO 17/11")]


def test_a_delivery_matched_only_by_contact_postcode_and_day_puts_nothing_on(bd):
    # rails to the same contact, postcode and day as a sleepers email that named only the sleepers
    e = group(bd, [row("9100003", *RAIL, 12), row("9100004", *RAIL, 6)])
    e["_seen"] = {"_delivery": sent("18/11/2026 10:58")}
    assert bd.enrol_by_hand([e]) == 0
    assert records() == [] and ctms_notes.owed(records()) == []
    assert e["_unnamed"] == ["9100003", "9100004"]


def test_orders_an_email_named_go_on_as_before_each_dated_from_its_own_email(bd):
    both = group(bd, [row("9100005", *RAIL, 10), row("9100006", *SLEEPER, 40)])
    both["_seen"] = {o: sent("10/11/2026 09:15", "EID-ONE") for o in ("9100005", "9100006")}
    apart = group(bd, [row("9100007", *RAIL, 10, contact="Sam Example email: sam.example@site.example"),
                       row("9100008", *SLEEPER, 40, contact="Sam Example email: sam.example@site.example")])
    apart["_seen"] = {"9100007": sent("11/11/2026 14:02", "EID-A"), "9100008": sent("12/11/2026 08:30", "EID-B")}
    drafted = group(bd, [row("9100009", *RAIL, 4, contact="Jo Example email: jo.example@site.example")])
    drafted["_seen"] = {"9100009": sent("13/11/2026 16:00", "EID-D", where="Drafts")}
    assert bd.enrol_by_hand([both, apart, drafted]) == 3
    got = {r["id"]: r for r in records()}
    assert set(got) == {f"9100005-9100006|{DAY}", f"9100007|{DAY}", f"9100008|{DAY}"}
    one = got[f"9100005-9100006|{DAY}"]                                          # one email, one record, as before
    assert one["emailed_at"] == "2026-11-10 09:15" and one["materials"] == "10x rails, 40x sleepers"
    assert got[f"9100007|{DAY}"]["emailed_at"] == "2026-11-11 14:02"           # two emails: each from its own
    assert got[f"9100008|{DAY}"]["emailed_at"] == "2026-11-12 08:30"
    assert got[f"9100008|{DAY}"]["materials"] == "40x sleepers"
    assert both["_unnamed"] == [] and apart["_unnamed"] == [] and drafted["_unnamed"] == ["9100009"]   # not sent yet
    assert bd.enrol_by_hand([both, apart]) == 0 and len(records()) == 3          # never twice


# ---------- the recovery sweep (phase2 recover) ----------
class Mail:
    def __init__(self, subject, when, eid, to="kim.example@site.example"):
        self.Subject, self.To, self.EntryID = subject, to, eid
        self.Body = "Hi Kim,\n\nI've got 10x rail available. Can you please help with the details below and " \
                    "I can get the delivery arranged for you?"
        self.SentOn = datetime.strptime(when, "%d/%m/%Y %H:%M")


class Items(list):
    def Sort(self, *a):
        pass


def test_recovery_rebuilds_only_the_orders_a_sent_subject_named(bd, monkeypatch):
    import phase2
    folder = type("Folder", (), {"Items": Items([
        Mail("7900013 Example Worksite - Example Yard EX1 1AA", "12/11/2026 08:30", "EID-B"),   # newest first
        Mail("7900011 Example Worksite - Example Yard EX1 1AA", "11/11/2026 14:02", "EID-A")])})
    monkeypatch.setattr(bd, "dhl_store", lambda ns: "dhl")
    monkeypatch.setattr(bd, "sub", lambda parent, name: folder if name == "Sent Items" else None)
    monkeypatch.setattr(bd, "find_already_emailed", lambda ns, orders, limit=0: {})        # nothing booked
    asked = []

    def resolve(ns, typed):
        # as the real lookup does: each order's lines and its siblings' - every line to the same contact, site, day
        asked.append(typed)
        lines = [row("7900011", *RAIL, 10), row("7900012", *SLEEPER, 40), row("7900013", *RAIL, 6)]
        return [(r, C, "Example_Haulier_Extract.xlsx") for r in lines], typed.split(), []
    monkeypatch.setattr(phase2.send_order, "resolve_orders", resolve)
    assert phase2.enrol_untracked(None) == 2
    assert asked == ["7900011 7900013"]
    got = {r["id"]: r for r in records()}
    assert set(got) == {f"7900011|{DAY}", f"7900013|{DAY}"}                     # 7900012: no email named it
    assert got[f"7900011|{DAY}"]["emailed_at"] == "2026-11-11 14:02" and got[f"7900011|{DAY}"]["orig_entryid"] == "EID-A"
    assert got[f"7900013|{DAY}"]["emailed_at"] == "2026-11-12 08:30" and got[f"7900013|{DAY}"]["orig_entryid"] == "EID-B"
    assert got[f"7900011|{DAY}"]["materials"] == "10x rails" and got[f"7900011|{DAY}"]["source"] == "sent (recovered)"


# ---------- order_pin ... pin track ----------
def _pin(bd, monkeypatch, capsys, already):
    import order_pin
    monkeypatch.setattr(bd, "get_ns", lambda: None)
    monkeypatch.setattr(bd, "find_already_emailed", lambda ns, orders, limit=0: dict(already))
    lines = [row("9100021", *RAIL, 10, po="PO111111"), row("9100022", *SLEEPER, 40)]
    monkeypatch.setattr(order_pin.so, "resolve_orders",
                        lambda ns, typed: ([(r, C, "Example_Haulier_Extract.xlsx") for r in lines], [typed], []))
    monkeypatch.setattr(sys, "argv", ["order_pin.py", "9100021", "pin", "track"])
    assert order_pin.main() == 0
    return capsys.readouterr().out


def test_pin_track_tracks_only_the_orders_a_sent_email_names(bd, monkeypatch, capsys):
    out = _pin(bd, monkeypatch, capsys, {"9100021": sent("14/11/2026 11:20", "EID-P")})
    [r] = records()
    assert r["orders"] == ["9100021"] and r["source"] == "by hand" and r["status"] == "sent"
    assert r["emailed_at"] == "2026-11-14 11:20" and r["orig_entryid"] == "EID-P"     # the tracker's own form
    assert r["materials"] == "10x rails" and r["po"] == {"9100021": "PO111111"}
    assert "NOT tracking 9100022" in out and "PIN_RESULT pinned=1 tracked=1" in out
    assert [(n["ref"], n["note"]) for n in ctms_notes.owed(records())] == [("9100021-1-1", " - Emailed DO 14/11")]


def test_pin_track_with_no_trace_in_sent_items_pins_and_tracks_nothing(bd, monkeypatch, capsys):
    out = _pin(bd, monkeypatch, capsys, {})
    assert records() == []
    assert "NOT tracking 9100021 / 9100022" in out and "PIN_RESULT pinned=1 tracked=0" in out
    assert [p["tracked"] for p in pins.load()] == [False]
