"""Plain-assert tests for the rail plan run following the team's SOP ("Running the Rail Plan", his 23/11) - no
Outlook, no dashboard, every order number, place and address made up.

What the team would see go wrong: a supplier's rows in another supplier's plan (or in a plan no supplier gets), a
manual order left on, an order lost because a comma in its description split the line, and an update that doesn't
show what changed the SOP's way - new green, cancelled red, a vehicle reg for VAS or AMS/RMS orange, the last
issue's colours cleared and its red rows left off.

Run:  python region2-emailer/tests/test_rail_plan_sop.py
"""
import base64
import csv
import json
import os
import shutil
import sys
import tempfile
import types
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.modules["metrics"] = types.SimpleNamespace(log=lambda *a, **k: None)    # keep test runs out of the real log

import openpyxl                         # noqa: E402
from openpyxl.styles import PatternFill  # noqa: E402
import rail_plan as R                   # noqa: E402
import agent as A                       # noqa: E402

HDR = ["Schedule", "Trip Number", "Order Reference", "Booking Reference", "Del Point Ref", "Carrier Name",
       "Product Code", "Product Description", "Length", "Quantity", "From Location", "From Post Code", "To Location",
       "To Post Code", "Hiab Required", "Collection Date", "Earliest Coll Time", "Latest Coll Time", "Delivery Date",
       "Earliest Del Time", "Latest Del Time", "Delivery Contact", "Contact Details", "Instructions", "Order Notes"]
WEEK = date(2026, 11, 16)               # Monday; every row below delivers Tue 17/11


def row(ref, loc, pc, notes="", desc="RAIL SHORT 56E1 18.288M"):
    return ["261117", "MAN-T1", ref, "B1", "", "Test Haulage", "0000/000000/0000", desc, "18.288", "1", loc, pc,
            "Test Site", "AB1 2CD", "N", "16-NOV-26", "08:00", "15:00", "17-NOV-26", "08:00", "10:00", "A Person",
            "01000 000000", "", notes]


def export(folder, rows, lines=()):
    """A Short Rail Report: these rows, then any lines written as they are (CTMS doesn't quote its text)."""
    p = os.path.join(folder, "short_rail_rep.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([HDR] + list(rows))
        for line in lines:
            f.write(line + "\r\n")
    return p


class PlanAtt:
    """An emailed plan: (order, From Location, From Post Code, order notes, red?) rows under a Tuesday bar."""

    def __init__(self, rows):
        self.rows = rows

    def SaveAsFile(self, p):
        wb = openpyxl.Workbook()
        ws = wb.active
        hdr = ["Schedule", "Trip Number", "Leg", "Order Reference", "Carrier Name", "From Location", "From Post Code",
               "Delivery Date", "Order Notes"]
        ws.append(hdr)
        ws.append(["Tuesday"] + [""] * (len(hdr) - 1))
        for ref, loc, pc, notes, red in self.rows:
            ws.append(["261117", "MAN-T1", 1, ref, "Old Haulage", loc, pc, "17-Nov-26", notes])
            if red:
                for c in ws[ws.max_row]:
                    c.fill = PatternFill("solid", fgColor="FF0000")
        wb.save(p)


def went_round(**plans):
    """What _plan_mail finds: one email per plan, named suffix=... ('master' = no suffix), all v1."""
    found = []
    for sfx, rows in plans.items():
        name = "Rail Plan wc 16.11 v1" + ("" if sfx == "master" else " " + sfx.replace("_", " ")) + ".xlsx"
        att = PlanAtt(rows)
        mail = types.SimpleNamespace(Attachments=types.SimpleNamespace(Item=lambda j, a=att: a, Count=1))
        found.append((datetime(2026, 11, 16, 9, 0), mail, [(1,) + R.plan_file(name)]))
    return found


def fills(path):
    """{order: its row's colour ('' plain)} on a built plan, in the order the rows sit."""
    ws = openpyxl.load_workbook(path).active
    col = [c.value for c in ws[1]].index("Order Reference")
    return {str(r[col].value): R._fill(r[col]) for r in ws.iter_rows(min_row=2) if r[col].value}


def made_by_suffix(made):
    return {m["suffix"]: m for m in made}


def with_mail(found, fn):
    keep = R._plan_mail
    R._plan_mail = lambda wc: found
    try:
        return fn()
    finally:
        R._plan_mail = keep


def test_each_supplier_plan_takes_the_rows_the_sop_table_gives_it():
    want = {("Bri00001", "DN16 1BP"): "BS", ("VAS00001", "DN14 5SS"): "VAS", ("AMS00001", "DN14 5SS"): "AMS RMS",
            ("AMS00002", "DN14 5SY"): "Arcelor", ("AMS00003", "SO40 4UT"): "AMS", ("VAS00002", "DN6 0AA"): "Inf VAS",
            ("Inf00001", "DN6 0AA"): "Inf VAS", ("AMS4/0000001", "DN6 0AA"): "Inf"}
    for (loc, pc), sfx in want.items():
        assert R.plan_for(loc, pc) == (R.PLAN_CHAIN[sfx], sfx), (loc, pc, R.plan_for(loc, pc))
    assert R.plan_for("WM00001", "PE15 0AA") is None                # Whitemoor: the master only
    assert R.plan_for("VAS00003", "AB1 2CD") is None                # a depot the table doesn't name
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    try:
        rows = [row("T%04d" % n, loc, pc) for n, (loc, pc) in enumerate(want, 1)]
        rows += [row("T0100", "WM00001", "PE15 0AA"), row("T0101", "VAS00003", "AB1 2CD")]
        info = {}
        wc, made, _ = with_mail([], lambda: R.build(export(tmp, rows), out_dir=tmp, update=True, info=info))
        by = made_by_suffix(made)
        assert sorted(by) == ["", "AMS", "AMS RMS", "Arcelor", "BS", "Inf", "Inf VAS", "VAS"], sorted(by)
        assert by[""]["count"] == 10 and by["Inf VAS"]["count"] == 2 and by["VAS"]["count"] == 1
        assert by["AMS"]["chain"] == "AMS SO40" and by["Arcelor"]["chain"] == "Arcelor Mittal"
        assert info["no_plan"] == ["T0101 (from VAS00003 AB1 2CD)"], info["no_plan"]   # said, not guessed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_manual_order_comes_off_the_plan_and_a_suppliers_lettered_one_stays():
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    try:
        rows = [row("M1234567", "Bri00001", "DN16 1BP"), row("M1234567_S1", "Bri00001", "DN16 1BP"),
                row("MX56E1_S1", "AMS00003", "SO40 4UT"), row("T0001", "Bri00001", "DN16 1BP")]
        info = {}
        _, made, _ = with_mail([], lambda: R.build(export(tmp, rows), out_dir=tmp, update=True, info=info))
        assert set(fills(made_by_suffix(made)[""]["path"])) == {"MX56E1_S1", "T0001"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_comma_in_a_description_no_longer_loses_the_order():
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    try:
        spilt = ",".join(row("T0002", "VAS00002", "DN6 0AA", desc="RAIL SHORT, 56E1, 350HT, 9.144M"))
        fixed, sure = R.mend(next(csv.reader([spilt])), HDR)
        assert sure and fixed == row("T0002", "VAS00002", "DN6 0AA", desc="RAIL SHORT, 56E1, 350HT, 9.144M")
        assert R.mend(next(csv.reader([spilt + ","])), HDR) == (fixed, True)    # a comma at the end of the line too
        plain = row("T0004", "Bri00001", "DN16 1BP")
        assert R.mend(plain + ["", ""], HDR) == (plain, True)                     # commas at the end only
        # commas in the text after the dates: the row is kept, its notes keep the reg, and it is said
        late = row("T0005", "Bri00001", "DN16 1BP", notes="Vehicle Reg: AB12 CDE, call first")
        fixed, sure = R.mend(next(csv.reader([",".join(late)])), HDR)
        assert not sure and fixed == late
        info = {}
        _, made, _ = with_mail([], lambda: R.build(export(tmp, [row("T0001", "Bri00001", "DN16 1BP")], [spilt]),
                                                   out_dir=tmp, update=True, info=info))
        by = made_by_suffix(made)
        assert "T0002" in fills(by["Inf VAS"]["path"]) and info["unreadable"] == []
        ws = openpyxl.load_workbook(by["Inf VAS"]["path"]).active
        hdr = [c.value for c in ws[1]]
        got = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[hdr.index("Order Reference")] == "T0002"][0]
        assert got[hdr.index("Product Description")] == "RAIL SHORT, 56E1, 350HT, 9.144M"
        assert got[hdr.index("From Location")] == "VAS00002"
        # commas in two columns at once: where they belong can't be told - the send-off holds, nothing guessed
        bad = row("T0003", "Bri00001", "DN16 1BP", desc="RAIL, SHORT")
        bad[12] = "Test, Site"
        info = {}
        wc, _, _ = with_mail([], lambda: R.build(export(tmp, [row("T0001", "Bri00001", "DN16 1BP")], [",".join(bad)]),
                                                 out_dir=tmp, update=True, info=info))
        assert info["unreadable"] == ["T0003"]
        assert R.hold_reason(info, wc, WEEK) == "1 row(s) of the export could not be read (T0003)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_update_shows_new_green_cancelled_red_and_a_new_vehicle_reg_orange():
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    bs, vas = ("Bri00001", "DN16 1BP"), ("VAS00001", "DN14 5SS")
    try:
        found = went_round(
            master=[("T0001",) + bs + ("", False), ("T0002",) + vas + ("", False), ("T0003",) + bs + ("", False),
                    ("T0004",) + bs + ("", True), ("T0006",) + bs + ("", True)],
            BS=[("T0001",) + bs + ("", False), ("T0003",) + bs + ("", False), ("T0004",) + bs + ("", True)],
            VAS=[("T0002",) + vas + ("", False)])
        rows = [row("T0001", *bs), row("T0002", *vas, notes="Vehicle Reg: AB12 CDE"), row("T0005", *bs),
                row("T0006", *bs)]           # T0003 cancelled since; T0004 was red already; T0006 back on
        info = {}
        _, made, _ = with_mail(found, lambda: R.build(export(tmp, rows), out_dir=tmp, update=True, info=info))
        by = made_by_suffix(made)
        assert [m["name"] for m in made] == ["Rail Plan wc 16.11 v2.xlsx", "Rail Plan wc 16.11 v2 BS.xlsx",
                                             "Rail Plan wc 16.11 v2 VAS.xlsx"], [m["name"] for m in made]
        G, RED, O = "92D050", "FF0000", "FFC000"
        assert fills(by[""]["path"]) == {"T0001": "", "T0002": O, "T0003": RED, "T0005": G, "T0006": G}
        assert fills(by["BS"]["path"]) == {"T0001": "", "T0003": RED, "T0005": G, "T0006": G}
        assert fills(by["VAS"]["path"]) == {"T0002": O}
        assert (info["new"], info["cancelled"], info["regs"]) == (["T0005", "T0006"], ["T0003"], ["T0002"])
        assert "Old Haulage" in by["BS"]["carriers"]                    # the cancelled job's haulier is told
        # the same reg again next time: plain; a reg on a BS order is not the SOP's orange
        found = went_round(master=[("T0001",) + bs + ("", False), ("T0002",) + vas + ("Vehicle Reg: AB12 CDE", False)],
                           VAS=[("T0002",) + vas + ("Vehicle Reg: AB12 CDE", False)])
        rows = [row("T0001", *bs, notes="reg AB12CDE"), row("T0002", *vas, notes="Vehicle Reg: AB12 CDE")]
        _, made, _ = with_mail(found, lambda: R.build(export(tmp, rows), out_dir=tmp, update=True))
        assert fills(made_by_suffix(made)[""]["path"]) == {"T0001": "", "T0002": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_supplier_whose_every_order_is_cancelled_still_gets_its_plan_in_red():
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    try:
        found = went_round(master=[("T0001", "Bri00001", "DN16 1BP", "", False), ("T0002", "AMS00001", "DN14 5SS", "", False)],
                           AMS_RMS=[("T0002", "AMS00001", "DN14 5SS", "", False)])
        _, made, _ = with_mail(found, lambda: R.build(export(tmp, [row("T0001", "Bri00001", "DN16 1BP")]),
                                                      out_dir=tmp, update=True))
        by = made_by_suffix(made)
        assert by["AMS RMS"]["name"] == "Rail Plan wc 16.11 v2 AMS RMS.xlsx" and by["AMS RMS"]["count"] == 0
        assert fills(by["AMS RMS"]["path"]) == {"T0002": "FF0000"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_vehicle_regs_are_read_from_the_order_notes():
    assert R.vehicle_reg("Vehicle Reg: AB12 CDE") == "AB12CDE"
    assert R.vehicle_reg("reg no Z123 XYZ, call ahead") == "Z123XYZ"
    assert R.vehicle_reg("Registration - AB12CDE") == "AB12CDE"
    for none in ("", None, "Regards, the site", "Region 2 order", "Collect 6 x 60ft rails", "Vehicle Reg: pending",
                 "Reg: TBC"):
        assert R.vehicle_reg(none) == "", none


class _Mail:
    def __init__(self, box):
        self.box, self.To, self.Subject, self.HTMLBody = box, "", "", ""
        self.Attachments = types.SimpleNamespace(Add=lambda p: None)

    def Send(self):
        self.box.append(self)


def test_a_supplier_plan_with_no_email_list_is_not_sent_to_the_rest_alone():
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    box = []
    client = types.SimpleNamespace(Dispatch=lambda what: types.SimpleNamespace(CreateItem=lambda kind: _Mail(box)))
    pkg = types.ModuleType("win32com")
    pkg.client = client
    fakes = {"win32com": pkg, "win32com.client": client,
             "build_drafts": types.SimpleNamespace(get_ns=lambda: None, clean_to_cc=lambda s: (s, "", []),
                                                   _attach_qr=lambda m: None, html_from_message=lambda t: t),
             "send_order": types.SimpleNamespace(dhl_account=lambda ns: "dhl", bind_account=lambda m, a: True)}
    keep = R.RECIP, R.SENT, {k: sys.modules.get(k) for k in fakes}
    try:
        sys.modules.update(fakes)
        R.SENT = os.path.join(tmp, "_rail_sent.json")
        R.RECIP = {"chains": {"British Steel": ["bs@example.com"]}, "dhl_always": ["team@example.com"], "hauliers": {}}
        rows = [row("T0001", "Bri00001", "DN16 1BP"), row("T0002", "VAS00001", "DN14 5SS")]
        res = with_mail([], lambda: R.sendoff(export(tmp, rows), send=True, update=True, week=WEEK, out_dir=tmp))
        assert [p["name"] for p in res["sent"]] == ["Rail Plan wc 16.11 v1.xlsx", "Rail Plan wc 16.11 v1 BS.xlsx"]
        assert res["failed"] == [{"name": "Rail Plan wc 16.11 v1 VAS.xlsx", "why": "no email list for VAS"}]
        assert [m.Subject for m in box] == ["Rail Plan wc 16.11", "Rail Plan wc 16.11 - British Steel"]
    finally:
        R.RECIP, R.SENT = keep[0], keep[1]
        for k, v in keep[2].items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_cards_message_says_what_went_red_and_orange_and_what_no_supplier_got():
    tmp = tempfile.mkdtemp(prefix="rp-sop-")
    name = "short_rail_rep_2026-11-16_101500.csv"
    result = {"wc": "16.11", "send": True, "held": "", "failed": [], "new": ["T0005"], "cancelled": ["T0003"],
              "regs": ["T0002"], "no_plan": ["T0101 (from VAS00003 AB1 2CD)"], "check": ["T0007"], "unmatched": [],
              "sent": [{"name": "Rail Plan wc 16.11 v2.xlsx", "rows": 4, "to": 9, "chain": "MASTER"}]}
    keep = A._req, A.run, A.snap_outbox, A.push_new_files, A.RAIL_RAW, A.RAIL_LAST
    try:
        A._req = lambda path, data=None, timeout=15: {"name": name, "data": base64.b64encode(b"Schedule\r\n").decode()}
        A.run = lambda args, timeout=600: "built\nRAIL_RESULT " + json.dumps(result)
        A.snap_outbox, A.push_new_files = (lambda: {}), (lambda before: None)
        A.RAIL_RAW, A.RAIL_LAST = os.path.join(tmp, "_rail_raw.csv"), os.path.join(tmp, "_rail_last.json")
        ok, said, _ = A.rail_send_export(7, {"file": name, "week": "16/11/2026-22/11/2026"})
        assert ok, said
        assert ("Sent Rail Plan wc 16.11 v2 (4 rows, 9 people). 1 new manifest(s) green. 1 cancelled (red): T0003. "
                "1 vehicle reg update(s) orange. On the master only, its depot in no supplier's plan: "
                "T0101 (from VAS00003 AB1 2CD). Commas split the text of T0007 - check its contact and notes on the "
                "plan.") == said, said
    finally:
        A._req, A.run, A.snap_outbox, A.push_new_files, A.RAIL_RAW, A.RAIL_LAST = keep
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
