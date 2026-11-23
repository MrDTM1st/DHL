"""Every form in one email reaches the map, and forms sharing an order number become ONE order (16/11: one email, two
forms with one number for one lorry - a rails form and a switch half set form - and only the first reached the map).
A stand-in mailbox and made-up orders, sites and numbers only; no Excel, no Outlook.

    python -m pytest -q tests/test_mail_forms.py
"""
import json
import os
import re
import sys
import time
import types
from datetime import datetime as DT

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import nr_csv                     # noqa: E402
import process_form as PF         # noqa: E402

REF = "AH05/01/27EXEX"


def row(ref=REF, site="Example Park", pc="EX2 2BB", prod="Rail", qty="2", road="Park Road", day=DT(2027, 1, 5),
        coll="Example Depot", veh="NR_60_ART_FL"):
    """One RHPC Admin row, shaped as process_form.read_rhpc_rows hands it over."""
    return {
        "Customer Order No": ref, "Shipment No": ref, "Site Name - Collection": coll, "Contact Name": "Sam Example",
        "Order Contact Name": "", "Order Contact No": "", "Address 1": "1 Example Lane", "Address 2": "0",
        "Address 3": "Exampleton", "Postcode": "EX1 1AA", "Telephone No": "07700 900123",
        "Collection Date": day, "collection_time": day.replace(hour=0, minute=1), "collection_time_end": day.replace(hour=5),
        "Delivery Point": site, "D Contact Name": "Sam Example", "D Address 1": road, "D Address 2": "0",
        "D Address 3": "Exampleton", "D Postcode": pc, "D Telephone No": "07700 900123",
        "Delivery Date": day, "delivery_time": day.replace(hour=0, minute=1), "delivery_time_end": day.replace(hour=5),
        "Product / Service Code": prod, "Product / Description": prod, "Product Qty": qty, "Serial Number": "",
        "Delivery Instructions": f"Material {prod} Dimension  Qty {qty} Weight  - 2-", "Raised by": "sam@example.com",
        "Approver": "Sam Example", "Account": "Please select", "Order Type": "C", "HIAB": "Y", "Vehicle Escort": "N",
        "PTS": "Y", "Banksman": "N", "Moffett": "Y", "Log Grab": "N", "Rear Steer": "Y", "Vehicle Type": veh,
        "Cost Centre": "123456//N/A", "Project Code": "", "Task Line": "",
        "Notes for Collection Location Comments": "0", "Notes for Delivery Location Comments": "0", "Est Cost": "",
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The map, the forms kept, the outbox and the CTMS to-do all in a temp folder; no date query staged."""
    import ctms_todo
    import date_query
    import outbox
    import tracker
    import mail_forms
    monkeypatch.setattr(PF, "ADHOCS", str(tmp_path / "_adhocs.json"))
    monkeypatch.setattr(PF, "FORMS_DIR", str(tmp_path / "forms"))
    monkeypatch.setattr(outbox, "OUTBOX", str(tmp_path / "outbox"))
    monkeypatch.setattr(ctms_todo, "STORE", str(tmp_path / "_ctms_todo.json"))
    monkeypatch.setattr(date_query, "raise_query", lambda *a, **k: [])
    monkeypatch.setattr(tracker, "booked_drops", lambda: set())
    return types.SimpleNamespace(MF=mail_forms, tmp=tmp_path)


def form(tmp, name, data=b"form"):
    """A form saved off an email the way monitor_tick saves one: a stamped copy, its email beside it."""
    p = str(tmp / ("20270104090000_" + name))
    with open(p, "wb") as f:
        f.write(data)
    with open(p + ".mail.json", "w", encoding="utf-8") as f:
        json.dump({"from": "Sam Example", "subject": "FW: Haulage Request Forms", "file": name, "entryid": "00AB",
                   "store": "00CD", "conversation": "99", "received": "2027-01-04 09:00"}, f)
    return p


def test_forms_with_one_order_number_become_one_order_with_a_drop_each(env):
    MF, tmp = env.MF, env.tmp
    a, b = form(tmp, "Form rails.xlsx"), form(tmp, "Form switch.xlsx")
    ra = row()
    rb = row(site="Example Station", pc="EX3 3CC", prod="Switches", qty="1", road="Station Road")
    lone = nr_csv.write_csv(nr_csv.transform([PF.to_transform_row(dict(ra))]), str(tmp / "lone.csv"))
    PF.store_adhocs([PF._adhoc_record(dict(ra), "NR_heavy_earlier.csv")])   # an earlier email's first form alone

    res = MF.combine(REF, [(a, [dict(ra)]), (b, [dict(rb)])], stamp=DT(2027, 1, 4, 9, 0, 0))

    assert res == [(True, f"{REF} / {REF}_1 (one order from 2 forms)", "Form rails.xlsx"), (True, "", "Form switch.xlsx")]
    with open(tmp / "outbox" / "NR_heavy_AH05-01-27EXEX_04012027090000.csv", encoding="utf-8", newline="") as f:
        csv = f.read()
    with open(lone, encoding="utf-8", newline="") as f:
        assert csv.startswith(f.read())                     # the first form's order exactly as it comes out alone
    assert [ln.split(",")[1] for ln in csv.splitlines() if ln.startswith("ORDER,")] == [REF, REF + "_1"]
    with open(PF.ADHOCS, encoding="utf-8") as f:
        recs = json.load(f)
    assert len(recs) == 1                                    # the earlier one-form record replaced, not beside it
    rec = recs[0]
    assert rec["orders"] == [REF, REF + "_1"]
    assert rec["csv"] == "NR_heavy_AH05-01-27EXEX_04012027090000.csv"
    assert rec["worksite"] == "Example Park + Example Station" and rec["postcode"] == "EX2 2BB"
    assert [(d["order"], d["pc"], d["address"]) for d in rec["drops"]] == [
        (REF, "EX2 2BB", "Park Road, Exampleton"), (REF + "_1", "EX3 3CC", "Station Road, Exampleton")]
    notes = rec["details"]["notes"]["value"]
    assert f"Drop 2 {REF}_1: 1x Switches to Example Station, Station Road, Exampleton, EX3 3CC." in notes
    assert "Check" not in notes and rec["combined"]["checks"] == []
    assert rec["qty"] == "" and rec["mail"]["file"] == "Form rails.xlsx"
    assert sorted(os.listdir(PF.FORMS_DIR)) == ["Haulage Request Form AH05-01-27EXEX.xlsx",
                                                "Haulage Request Form AH05-01-27EXEX_1.xlsx"]
    assert rec["form_files"] == sorted(os.listdir(PF.FORMS_DIR))


def test_where_the_forms_disagree_the_order_says_so_and_settles_nothing(env):
    MF, tmp = env.MF, env.tmp
    a, b = form(tmp, "Form A.xlsx"), form(tmp, "Form B.xlsx")
    rb = row(site="Example Station", pc="EX3 3CC", day=DT(2027, 1, 6), coll="Sample Yard", veh="NR_40_ART_FL")
    res = MF.combine(REF, [(a, [row()]), (b, [rb])])
    assert res[0][0] is True and res[0][1].endswith("check its Notes: the forms differ")
    with open(PF.ADHOCS, encoding="utf-8") as f:
        rec = json.load(f)[0]
    notes = rec["details"]["notes"]["value"]
    assert "different delivery days (05/01/2027, 06/01/2027)" in notes
    assert "different vehicles (NR_60_ART_FL, NR_40_ART_FL)" in notes
    assert "collect from different places (Example Depot EX1 1AA; Sample Yard EX1 1AA)" in notes
    assert len(rec["collections"]) == 2                     # the haulier needs every pick-up
    assert rec["details"]["vehicle"]["value"] == "NR_60_ART_FL"       # the first form's - not a pick between them
    assert rec["delivery_date"] == "05/01/2027"


def test_a_form_with_a_return_leg_is_never_folded_into_another(env, monkeypatch):
    MF, tmp = env.MF, env.tmp
    a, b = form(tmp, "Form A.xlsx"), form(tmp, "Form B.xlsx")
    ran = []
    monkeypatch.setattr(MF, "alone", lambda p: ran.append(p) or (True, REF, "MAP : job saved"))
    res = MF.combine(REF, [(a, [row(), row(ref=REF + "_R")]), (b, [row(pc="EX3 3CC")])])
    assert ran == [a]                                        # the first goes on as it would alone
    assert res[0] == (True, REF, "Form A.xlsx")
    assert res[1][0] is False and "not combined" in res[1][1] and res[1][2] == "Form B.xlsx"
    assert not os.path.exists(PF.ADHOCS)                     # nothing of the second form on the map to replace it


def test_forms_are_grouped_by_order_number_in_the_emails_order(env):
    rows = {"a": [row("AH1/1/27AAAA")], "b": [row("AH2/1/27BBBB")], "c": [row("AH1/1/27AAAA")], "d": [],
            "e": [row("FS-")]}
    got = env.MF.groups(["a", "b", "c", "d", "e"], read=lambda p: rows[p])
    assert [(ref, [p for p, _ in m]) for ref, m in got] == [
        ("AH1/1/27AAAA", ["a", "c"]), ("AH2/1/27BBBB", ["b"]), ("", ["d"]), ("", ["e"])]


def test_every_form_in_the_email_comes_back_with_what_became_of_it(env, monkeypatch, capsys):
    MF, tmp = env.MF, env.tmp
    a, b, c = form(tmp, "Form a.xlsx"), form(tmp, "Form b.xlsx"), form(tmp, "Form c.xlsx")
    rows = {a: [row("AH1/1/27AAAA")], b: [row("AH2/1/27BBBB")], c: [row("AH1/1/27AAAA", pc="EX3 3CC")]}
    monkeypatch.setattr(MF, "rows_of", lambda p: [dict(r) for r in rows[p]])
    monkeypatch.setattr(MF, "alone", lambda p: (True, "AH2/1/27BBBB", "Order AH2/1/27BBBB | the lone form"))
    assert MF.main([a, b, c]) == 0
    out = capsys.readouterr().out
    assert MF.outcomes(out, ["Form a.xlsx", "Form b.xlsx", "Form c.xlsx"]) == [
        (True, "AH1/1/27AAAA / AH1/1/27AAAA_1 (one order from 2 forms)", "Form a.xlsx"),
        (True, "", "Form c.xlsx"),
        (True, "AH2/1/27BBBB", "Form b.xlsx")]
    assert MF.outcomes("Traceback (most recent call last) ...", ["Form a.xlsx"]) == [
        (False, "the forms did not finish processing", "Form a.xlsx")]


def test_a_record_with_several_orders_takes_the_place_of_one_holding_some_of_them():
    S = frozenset
    assert PF._supersedes(S({"A"}), S({"A"}))                          # the same form again, as ever
    assert not PF._supersedes(S({"A"}), S({"A", "A_1"}))                # one order never swallows a bigger record
    assert PF._supersedes(S({"A", "A_1"}), S({"A"}))
    assert not PF._supersedes(S({"A", "A_1"}), S({"B"}))
    assert not PF._supersedes(S({"A", "A_1"}), S())                     # a record with no orders is nobody's


def test_the_same_form_again_still_replaces_its_own_record(env):
    PF.save_adhocs([row()], "NR_heavy_first.csv")
    PF.save_adhocs([row()], "NR_heavy_again.csv")
    with open(PF.ADHOCS, encoding="utf-8") as f:
        assert [r["csv"] for r in json.load(f)] == ["NR_heavy_again.csv"]


# ---------- the monitor ----------

@pytest.fixture
def M(tmp_path, monkeypatch):
    """monitor_tick with build_drafts (which reads the private config at import), Outlook and the gate stood in for."""
    bd = types.ModuleType("build_drafts")
    bd.is_wanted_extract = lambda fn, subj: "extract" in fn.lower()
    monkeypatch.setitem(sys.modules, "build_drafts", bd)
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda name: types.SimpleNamespace(GetNamespace=lambda kind: object())
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "outlook_gate", types.SimpleNamespace(
        single_instance=lambda name: True, self_destruct=lambda s: None, outlook_hung=lambda: False,
        background_slot=lambda wait: object()))
    try:
        import toolkit_switch
        monkeypatch.setattr(toolkit_switch, "FLAG", str(tmp_path / "toolkit.off"))   # on, whatever this PC says
    except ImportError:
        pass
    monkeypatch.delitem(sys.modules, "monitor_tick", raising=False)
    import monitor_tick
    for name in ("SEEN", "PHASE2_DUE", "PUSH_DUE"):
        monkeypatch.setattr(monitor_tick, name, str(tmp_path / name))
    monkeypatch.setattr(monitor_tick, "HERE", str(tmp_path))
    monkeypatch.setattr(monitor_tick, "AUTO_FORMS", str(tmp_path / "from_mail"))
    monitor_tick._save({"ext_ids": [], "adhoc_ids": [], "inbox_hwm": "", "sent_hwm": "", "last_tree": time.time()})
    yield monitor_tick
    sys.modules.pop("monitor_tick", None)


def _mailbox(M, monkeypatch, mail):
    inbox = object()
    monkeypatch.setattr(M, "_folders", lambda ns: (inbox, None, None))
    monkeypatch.setattr(M, "_scan", lambda folder, limit: iter(mail if folder is inbox else []))


def test_every_form_in_an_email_is_taken_together(M, monkeypatch):
    _mailbox(M, monkeypatch, [("m1", "FW: Haulage Request Forms", "2027-01-04T09:00",
                               ["Form A.xlsx", "Form B.xlsx", "Site plan.pdf"])])
    calls, said = [], []
    monkeypatch.setattr(M, "_auto_adhoc", lambda ns, eid, fns: calls.append((eid, list(fns))) or (
        [(True, "AH1 / AH1_1 (one order from 2 forms)", "Form A.xlsx"), (True, "", "Form B.xlsx")], "Sam Example"))
    monkeypatch.setattr(M, "report", lambda state, detail, *a, **k: said.append(detail))
    M.main()
    assert calls == [("m1", ["Form A.xlsx", "Form B.xlsx"])]          # one call, both forms - not just the first
    assert said == ["New ad hoc on the map: AH1 / AH1_1 (one order from 2 forms) from Sam Example - its brief has "
                    "the Upload button. Not processed: Site plan.pdf - use the DTS / Ad-hoc box."]


def test_an_email_past_what_one_tick_takes_waits_for_the_next(M, monkeypatch):
    _mailbox(M, monkeypatch, [(f"m{i}", "Haulage request", f"2027-01-04T09:0{i}", [f"Form {i}.xlsx"]) for i in range(7)])
    calls = []
    monkeypatch.setattr(M, "_auto_adhoc", lambda ns, eid, fns: calls.append(eid) or ([(True, eid, fns[0])], "Sam"))
    monkeypatch.setattr(M, "report", lambda *a, **k: None)
    M.main()
    assert calls == ["m0", "m1", "m2", "m3", "m4"]
    assert M._load()["adhoc_ids"] == ["m0", "m1", "m2", "m3", "m4"]   # the other two not marked seen, so not lost
    M.main()
    assert calls[5:] == ["m5", "m6"]


class Att:
    def __init__(self, name, data):
        self.FileName, self.data = name, data

    def SaveAsFile(self, path):
        with open(path, "wb") as f:
            f.write(self.data)


def _outlook(atts):
    item = types.SimpleNamespace(
        SenderName="Sam Example", Parent=types.SimpleNamespace(StoreID="S1"), ConversationID="C1",
        Subject="FW: Haulage Request Forms", ReceivedTime=DT(2027, 1, 4, 9, 0),
        Attachments=types.SimpleNamespace(Count=len(atts), Item=lambda i: atts[i - 1]))
    return types.SimpleNamespace(GetItemFromID=lambda eid: item)


def test_two_forms_of_one_name_are_both_saved_and_go_through_together(M, monkeypatch):
    ran = []
    monkeypatch.setattr(M, "run", lambda args: ran.append(args) or (0, (
        "RESULT\tok\tForm.xlsx\tAH1 / AH1_1 (one order from 2 forms)\nRESULT\tok\tForm.xlsx\t\n")))
    ns = _outlook([Att("Form.xlsx", b"one"), Att("Notes.txt", b"x"), Att("Form.xlsx", b"two")])
    results, sender = M._auto_adhoc(ns, "m1", ["Form.xlsx", "Form.xlsx"])
    assert sender == "Sam Example"
    assert ran[0][0] == "mail_forms.py" and len(ran[0]) == 3
    saved = []
    for p in ran[0][1:]:
        with open(p, "rb") as f:
            saved.append(f.read())
        with open(p + ".mail.json", encoding="utf-8") as f:
            assert json.load(f)["file"] == "Form.xlsx"
    assert saved == [b"one", b"two"]                              # by position: the second didn't overwrite the first
    assert results == [(True, "AH1 / AH1_1 (one order from 2 forms)", "Form.xlsx"), (True, "", "Form.xlsx")]
    assert os.path.exists(M.PUSH_DUE)


def test_a_lone_form_goes_through_process_form_as_it_always_did(M, monkeypatch):
    ran = []
    monkeypatch.setattr(M, "run", lambda args: ran.append(args) or (0, (
        "MAP : job saved for the dashboard map (form kept for forwarding).\n"
        "Order AH1 | Example Depot -> Example Park | qty 2 | acct NRADHOC (defaulted)\n")))
    results, sender = M._auto_adhoc(_outlook([Att("Form.xlsx", b"one")]), "m1", "Form.xlsx")
    assert ran[0][0] == "process_form.py" and ran[0][2:] == ["--mail", ran[0][1] + ".mail.json"]
    assert re.fullmatch(r"\d{14}_Form\.xlsx", os.path.basename(ran[0][1]))        # named as before
    assert results == [(True, "AH1", "Form.xlsx")] and sender == "Sam Example"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
