"""Plain-assert tests for how a rail plan is numbered, what an update compares
against, and which plans the work PC files - no Outlook, no dashboard.

Covers what the team would see go wrong: a plan going out under the wrong
version (each issue of a plan is one up from the last that went round,
whoever sent it), an update painting rows green that went round already
(the baseline is the latest issue of every plan, not just the newest email),
and a preview landing in the team's Rail Plans folder as if it had gone out.

Run:  python region2-emailer/tests/test_rail_plan_versions.py
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.modules["metrics"] = types.SimpleNamespace(log=lambda *a, **k: None)    # keep test runs out of the real log

import openpyxl                         # noqa: E402
import rail_plan as R                   # noqa: E402
import agent as A                       # noqa: E402

HDR = ["Schedule", "Trip Number", "Order Reference", "Booking Reference", "Carrier Name", "Product Description",
       "Product Code", "Length", "Quantity", "From Location", "From Post Code", "To Location", "To Post Code",
       "Delivery Date"]


def raw(folder, *rows):
    """A Short Rail Report with these (order, From Location, From Post Code) rows, all delivering Tue 03/11."""
    p = os.path.join(folder, "short_rail_rep.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([HDR] + [["261103", "T1", ref, "B1", "Test Haulage", "Rail", "RAIL", "18.3", "1",
                                          loc, pc, "Test Site", "AB1 2CD", "03-Nov-26"] for ref, loc, pc in rows])
    return p


def went_round(*names):
    """What _plan_mail finds in the mailbox: one email per plan."""
    return [(datetime(2026, 10, 30, 9, 0), None, [(1,) + R.plan_file(n)]) for n in names]


class Att:
    """An attached plan carrying these Order References."""

    def __init__(self, refs):
        self.refs = refs

    def SaveAsFile(self, p):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Schedule", "Order Reference"])
        ws.append(["Monday", None])                     # the black day bar
        for r in self.refs:
            ws.append(["261102", r])
        wb.save(p)


class Mail:
    def __init__(self, *atts):
        self.Attachments = types.SimpleNamespace(Item=lambda j: atts[j - 1], Count=len(atts))


def test_a_plan_name_is_read_the_way_the_team_writes_it():
    assert R.plan_file("Rail Plan wc 19.10 v3 Inf VAS.xlsx") == ("19.10", 3, "Inf VAS")
    assert R.plan_file("Rail Plan wc 19.10 v2.xlsx") == ("19.10", 2, "")
    assert R.plan_file("Rail Plan wc 28.09 v5 BS.xlsx") == ("28.09", 5, "BS")
    for other in ("Rail Plan wc 19.10.xlsx", "Rail Plan wc 19.10 v2 BS.pdf", "Rail Plan wc 19.10 v2 BS (1).xlsx",
                  "BS Ack 04.09.26.xlsx", ""):
        assert R.plan_file(other) is None, other


def test_each_plan_goes_out_one_version_up_from_its_last_issue():
    tmp = tempfile.mkdtemp(prefix="rp-test-")
    keep = R._plan_mail
    try:
        csv_path = raw(tmp, ("T0001", "BRITISH STEEL", "DN16 1BP"), ("T0002", "VAS ASKERN", "DN6 0AA"))
        R._plan_mail = lambda wc: went_round("Rail Plan wc 02.11 v1 BS.xlsx", "Rail Plan wc 02.11 v3 BS.xlsx",
                                             "Rail Plan wc 02.11 v2.xlsx")
        wc, made, _ = R.build(csv_path, out_dir=tmp)
        assert wc.strftime("%d.%m") == "02.11"
        assert sorted(m["name"] for m in made) == ["Rail Plan wc 02.11 v1 Inf VAS.xlsx",   # its first this week
                                                    "Rail Plan wc 02.11 v3.xlsx",
                                                    "Rail Plan wc 02.11 v4 BS.xlsx"], [m["name"] for m in made]
        assert all(os.path.exists(m["path"]) for m in made)
        R._plan_mail = lambda wc: None                  # the mailbox could not be read: v1, and it says so
        wc, made, _ = R.build(csv_path, out_dir=tmp)
        assert {R.plan_file(m["name"])[1] for m in made} == {1}
    finally:
        R._plan_mail = keep
        shutil.rmtree(tmp, ignore_errors=True)


class Folder:
    """An Outlook folder: its mail, its subfolders; kind 0 = mail (1 = a calendar...)."""

    def __init__(self, name, items=(), subs=(), kind=0):
        self.Name, self.DefaultItemType = name, kind
        self.Items = types.SimpleNamespace(Restrict=lambda flt: [i for i in items if "rail plan" in i.Subject.lower()])
        self.Folders = types.SimpleNamespace(Count=len(subs), Item=lambda i: subs[i - 1])


def mail(subject, when, *names):
    return types.SimpleNamespace(Subject=subject, ReceivedTime=when, Attachments=types.SimpleNamespace(
        Count=len(names), Item=lambda j: types.SimpleNamespace(FileName=names[j - 1])))


def test_the_mailbox_look_finds_the_teams_issues_filed_away_from_the_inbox():
    d = datetime
    synergy = Folder("Synergy Upload", [
        mail("RE: Rail Plan wc 02.11 - BS", d(2026, 11, 3, 13, 14), "Rail Plan wc 02.11 v3 BS.xlsx"),
        mail("RE: Rail Plan w/c 02.11", d(2026, 11, 3, 13, 13), "Rail Plan wc 02.11 v2.xlsx", "image001.png"),
        mail("RE: Rail Plan wc 26.10 - BS", d(2026, 10, 28, 9, 0), "Rail Plan wc 26.10 v4 BS.xlsx"),   # last week
        mail("Rail Plan wc 02.11", d(2025, 10, 30, 9, 0), "Rail Plan wc 02.11 v6.xlsx"),               # last year
        mail("Rail Plan wc 02.11 - notes", d(2026, 11, 2, 9, 0), "notes.docx")])
    inbox = Folder("Inbox", [], [Folder("ADHOC", [], [synergy]),
                                 Folder("Rail Plan reminders", [mail("Rail Plan wc 02.11", d(2026, 11, 2, 8, 0),
                                                                     "Rail Plan wc 02.11 v9.xlsx")], kind=1)])
    sent = Folder("Sent Items", [mail("Rail Plan wc 02.11 - British Steel", d(2026, 10, 29, 17, 5),
                                      "Rail Plan wc 02.11 v1 BS.xlsx")])
    store = Folder("delali", [], [inbox, sent])
    keep = sys.modules.get("build_drafts")
    sys.modules["build_drafts"] = types.SimpleNamespace(
        get_ns=lambda: None, dhl_store=lambda ns: store,
        sub=lambda f, name: next((f.Folders.Item(i) for i in range(1, f.Folders.Count + 1)
                                  if f.Folders.Item(i).Name == name), None))
    try:
        found = R._plan_mail(datetime(2026, 11, 2).date())
    finally:
        if keep is None:
            sys.modules.pop("build_drafts")
        else:
            sys.modules["build_drafts"] = keep
    assert [(w.strftime("%d/%m"), [p[1:] for p in plans]) for w, _, plans in found] == [
        ("03/11", [("02.11", 3, "BS")]), ("03/11", [("02.11", 2, "")]), ("29/10", [("02.11", 1, "BS")])], found
    assert found[1][2][0][0] == 1                       # which attachment to save: the plan, not the logo
    assert R.issued(found) == {"bs": 3, "": 2}


def test_an_update_compares_against_the_latest_issue_of_every_plan_not_just_the_newest_email():
    bs3 = Mail(Att(["T0001", "T0004"]))                 # the team's BS-only re-issue: the newest email
    master2 = Mail(Att(["T0001", "T0002", "T0003"]))
    master1 = Mail(Att(["T0001"]))
    found = [(datetime(2026, 11, 3, 13, 14), bs3, [(1, "02.11", 3, "BS")]),
             (datetime(2026, 11, 3, 13, 13), master2, [(1, "02.11", 2, "")]),
             (datetime(2026, 10, 29, 17, 5), master1, [(1, "02.11", 1, "")])]
    assert R.previous_order_refs(None, found) == {"T0001", "T0002", "T0003", "T0004"}
    assert R.previous_order_refs(None, []) is None      # nothing went round: nothing is painted green
    assert R.issued(found) == {"bs": 3, "": 2}


def test_only_a_plan_that_went_out_by_email_is_marked_for_the_shared_folder():
    tmp = tempfile.mkdtemp(prefix="rp-test-")
    box = os.path.join(tmp, "outbox")
    os.makedirs(box)
    keep = R.SENT, A.RAIL_SENT, A.outbox_dir, A._req
    sent = []
    try:
        R.SENT = A.RAIL_SENT = os.path.join(tmp, "_rail_sent.json")
        A.outbox_dir = lambda: box
        A._req = lambda path, data=None, timeout=15: sent.append(data) or {}

        def out(name, data):
            with open(os.path.join(box, name), "wb") as f:
                f.write(data)

        out("Rail Plan wc 02.11 v2 BS.xlsx", b"emailed")
        out("Rail Plan wc 02.11 v2.xlsx", b"previewed")     # built, never sent
        out("NR_heavy_x_31102026093000.csv", b"csv")
        R._mark_sent(os.path.join(box, "Rail Plan wc 02.11 v2 BS.xlsx"), "Rail Plan wc 02.11 v2 BS.xlsx")
        A.push_new_files({})
        assert {d["name"]: d.get("file", False) for d in sent} == {
            "Rail Plan wc 02.11 v2 BS.xlsx": True, "Rail Plan wc 02.11 v2.xlsx": False,
            "NR_heavy_x_31102026093000.csv": False}, sent
        out("Rail Plan wc 02.11 v2 BS.xlsx", b"previewed over it")      # a later preview, same name
        sent.clear()
        A.push_new_files({})
        assert len(sent) == 3 and not any(d.get("file") for d in sent)
        R._mark_sent(os.path.join(box, "Rail Plan wc 02.11 v2.xlsx"), "Rail Plan wc 02.11 v2.xlsx",
                     now=datetime.now() + timedelta(days=8))
        with open(R.SENT, encoding="utf-8") as f:
            assert list(json.load(f)) == ["Rail Plan wc 02.11 v2.xlsx"]    # a week on, the old note is gone
        with open(R.SENT, "w", encoding="utf-8") as f:
            f.write("not json")                         # a broken note never stops a push
        sent.clear()
        A.push_new_files({})
        assert len(sent) == 3 and not any(d.get("file") for d in sent)
    finally:
        R.SENT, A.RAIL_SENT, A.outbox_dir, A._req = keep
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_rail_plan_is_built_from_the_ctms_export_the_upload_or_the_one_last_previewed():
    import base64
    tmp = tempfile.mkdtemp(prefix="rp-test-")
    keep = A.RAIL_RAW, A.RAIL_LAST, A._req
    pulled = []
    try:
        A.RAIL_RAW, A.RAIL_LAST = os.path.join(tmp, "_rail_raw.csv"), os.path.join(tmp, "_rail_last.json")
        A._req = lambda path, data=None, timeout=15: pulled.append(path) or {}
        try:                                            # nothing previewed yet: Build & send with no file says so
            A.rail_plan_input({"source": "last"})
            assert False
        except ValueError as e:
            assert "previewed yet" in str(e)
        try:                                            # no file on the card either
            A.rail_plan_input({"week": "next"})
            assert False
        except ValueError as e:
            assert "No rail-plan CSV received" in str(e)
        exp = {"name": "short_rail_rep_2026-10-31_223746.csv", "data": base64.b64encode(b"Schedule\r\n1\r\n").decode()}
        pulled.clear()
        raw, update, what = A.rail_plan_input({"export": exp, "week": "next"})
        assert pulled == [] and update is True and "short_rail_rep_2026-10-31_223746.csv" in what
        assert open(raw, "rb").read() == b"Schedule\r\n1\r\n"   # the export, never the card's upload slot
        assert A.rail_plan_input({"source": "last", "week": "next"}) == (raw, True, what)   # sent as it was built
        A._req = lambda path, data=None, timeout=15: (pulled.append(path) or
                                                       {"name": "picked.csv", "data": base64.b64encode(b"x").decode()})
        raw, update, what = A.rail_plan_input({"week": "next"})
        assert pulled == ["/api/pull_upload"] and update is False and what == "picked.csv"
        assert A.rail_plan_input({"source": "last"})[1:] == (False, "picked.csv")
        assert A.rail_plan_input({"week": "current"})[1] is True
    finally:
        A.RAIL_RAW, A.RAIL_LAST, A._req = keep
        shutil.rmtree(tmp, ignore_errors=True)


# ---- the Rail plan card's one go (his 16/11: "do it all in one go from one button, which is export from CTMS") ----
def test_the_one_go_holds_back_what_a_look_at_the_preview_would_have_caught():
    from datetime import date
    tmp = tempfile.mkdtemp(prefix="rp-test-")
    keep = R._plan_mail
    try:
        ok_csv = raw(tmp, ("T0001", "BRITISH STEEL", "DN16 1BP"))          # delivering Tue 03/11
        R._plan_mail = lambda wc: []                                       # read: nothing gone round yet
        info = {}
        wc, _, _ = R.build(ok_csv, out_dir=tmp, update=True, info=info)
        assert (info["kept"], info["days"], info["undated"], info["mail_read"], info["new"]) == (
            1, [date(2026, 11, 3)], 0, True, None), info
        assert R.hold_reason(info, wc, date(2026, 11, 2)) == ""
        assert R.hold_reason(info, wc, date(2026, 11, 9)) == "the export runs 03/11 to 03/11, not the week of 09/11"
        R._plan_mail = lambda wc: None                                     # the mailbox could not be read
        info = {}
        wc, _, _ = R.build(ok_csv, out_dir=tmp, update=True, info=info)
        assert "versions could be wrong" in R.hold_reason(info, wc, date(2026, 11, 2))
        R._plan_mail = lambda wc: []
        info = {}
        none_csv = raw(tmp, ("AH12/11/26XX", "BRITISH STEEL", "DN16 1BP"), ("T0009", "SOMEWHERE", "AB1 2CD"))
        wc, _, _ = R.build(none_csv, out_dir=tmp, update=True, info=info)
        assert info["kept"] == 0 and R.hold_reason(info, wc, date(2026, 11, 2)) == "the export has no rail-supplier rows"
    finally:
        R._plan_mail = keep
        shutil.rmtree(tmp, ignore_errors=True)


class _Mail:
    """An Outlook mail being made: what it was given, and the box it lands in once sent."""

    def __init__(self, box):
        self.box, self.To, self.Subject, self.HTMLBody, self.files = box, "", "", "", []
        self.Attachments = types.SimpleNamespace(Add=self.files.append)

    def Send(self):
        self.box.append(self)


def test_the_one_go_sends_each_plan_to_its_chain_and_says_what_went_and_what_did_not():
    from datetime import date
    tmp = tempfile.mkdtemp(prefix="rp-test-")
    box, opened = [], []
    client = types.SimpleNamespace(Dispatch=lambda what: opened.append(what) or types.SimpleNamespace(
        CreateItem=lambda kind: _Mail(box)))
    pkg = types.ModuleType("win32com")
    pkg.client = client
    fakes = {"win32com": pkg, "win32com.client": client,
             "build_drafts": types.SimpleNamespace(get_ns=lambda: None, clean_to_cc=lambda s: (s, "", []),
                                                   _attach_qr=lambda m: None, html_from_message=lambda t: t),
             "send_order": types.SimpleNamespace(dhl_account=lambda ns: "dhl", bind_account=lambda m, a: True)}
    keep = R._plan_mail, R.RECIP, R.SENT, {k: sys.modules.get(k) for k in fakes}
    try:
        sys.modules.update(fakes)
        R.SENT = os.path.join(tmp, "_rail_sent.json")
        R.RECIP = {"chains": {"British Steel": ["bs@example.com"]}, "_plan_to_chain": {"BS": "British Steel"},
                   "dhl_always": ["team@example.com"], "hauliers": {}}
        R._plan_mail = lambda wc: went_round("Rail Plan wc 02.11 v1 BS.xlsx")
        csv_path = raw(tmp, ("T0001", "BRITISH STEEL", "DN16 1BP"))
        res = R.sendoff(csv_path, send=True, update=True, week=date(2026, 11, 2), out_dir=tmp)
        assert res["held"] == "" and not res["failed"], res
        assert [(p["name"], p["rows"], p["to"]) for p in res["sent"]] == [
            ("Rail Plan wc 02.11 v1.xlsx", 1, 1), ("Rail Plan wc 02.11 v2 BS.xlsx", 1, 2)], res["sent"]
        assert [(m.Subject, m.To) for m in box] == [("Rail Plan wc 02.11", "team@example.com"),
                                                     ("Rail Plan wc 02.11 - British Steel",
                                                      "bs@example.com; team@example.com")]
        assert res["unmatched"] == ["Test Haulage"]                        # no address for it: said, not guessed
        with open(R.SENT, encoding="utf-8") as f:
            assert sorted(json.load(f)) == ["Rail Plan wc 02.11 v1.xlsx", "Rail Plan wc 02.11 v2 BS.xlsx"]
        # another week's export: nothing goes out, and Outlook is never opened
        box.clear()
        opened.clear()
        res = R.sendoff(csv_path, send=True, update=True, week=date(2026, 11, 9), out_dir=tmp)
        assert "not the week of 09/11" in res["held"] and not box and not opened and not res["sent"], res
        # a plan Outlook won't send from the DHL account: said, and the others still go
        sys.modules["send_order"] = types.SimpleNamespace(dhl_account=lambda ns: "dhl",
                                                          bind_account=lambda m, a: "British Steel" not in m.Subject)
        res = R.sendoff(csv_path, send=True, update=True, week=date(2026, 11, 2), out_dir=tmp)
        assert [p["name"] for p in res["sent"]] == ["Rail Plan wc 02.11 v1.xlsx"], res
        assert res["failed"] == [{"name": "Rail Plan wc 02.11 v2 BS.xlsx", "why": "the DHL account could not be bound"}]
    finally:
        R._plan_mail, R.RECIP, R.SENT = keep[0], keep[1], keep[2]
        for k, v in keep[3].items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_cards_one_go_sends_only_the_export_it_took_once_that_checked_out():
    import base64
    tmp = tempfile.mkdtemp(prefix="rp-test-")
    exp = {"name": "short_rail_rep_2026-11-16_101500.csv", "data": base64.b64encode(b"Schedule\r\n").decode()}
    export_ok = {"ok": True, "said": "Exported the Short Rail Report ... Export card closed.", "file": exp["name"],
                 "rows": 12, "closed": True, "week": "16/11/2026-22/11/2026"}
    sent = {"wc": "16.11", "send": True, "held": "", "failed": [], "new": ["T0003"], "unmatched": [],
            "sent": [{"name": "Rail Plan wc 16.11 v3.xlsx", "rows": 12, "to": 19, "chain": "MASTER"}]}
    state = {"export": export_ok, "send": sent, "held": exp}
    ran, posts = [], []

    def fake_run(args, timeout=600):
        ran.append(args)
        if args[0] == "ctms_rail_export.py":
            return "a trace line\n" + json.dumps(state["export"])
        return "built\nRAIL_RESULT " + json.dumps(state["send"])

    def fake_req(path, data=None, timeout=15):
        posts.append((path, data))
        return dict(state["held"]) if path == "/api/ctms/rail/file" else {}

    keep = A.run, A._req, A.report, A.snap_outbox, A.push_new_files, A.RAIL_RAW, A.RAIL_LAST
    job = {"action": "ctms_rail", "week": "current", "send": True, "run": 7}

    def go():
        ran.clear()
        posts.clear()
        A.ctms_rail_job(job)
        return [d for p, d in posts if p == "/api/ctms/rail/ran"]

    try:
        A.run, A._req, A.report = fake_run, fake_req, (lambda *a, **k: None)
        A.snap_outbox, A.push_new_files = (lambda: {}), (lambda before: None)
        A.RAIL_RAW, A.RAIL_LAST = os.path.join(tmp, "_rail_raw.csv"), os.path.join(tmp, "_rail_last.json")
        said = go()
        assert ran[0] == ["ctms_rail_export.py", "run", "current"]
        assert ran[1] == ["rail_plan.py", "send", A.RAIL_RAW, "go", "--update", "--week", "2026-11-16"], ran
        assert open(A.RAIL_RAW, "rb").read() == b"Schedule\r\n"              # the very file the export took
        assert said[0]["phase"] == "sending" and said[-1]["ok"] is True and said[-1]["run"] == 7
        assert "Sent Rail Plan wc 16.11 v3 (12 rows, 19 people). 1 new manifest(s) green." in said[-1]["said"]
        state["held"] = dict(exp, name="short_rail_rep_2026-11-16_090000.csv")    # the cloud holds another file
        said = go()
        assert len(ran) == 1 and said[-1]["ok"] is False and "not the export just made" in said[-1]["said"]
        state["held"] = exp
        state["send"] = dict(sent, held="the export has no rail-supplier rows", sent=[])   # rail_plan.py held it
        said = go()
        assert said[-1]["ok"] is False and "Nothing sent - the export has no rail-supplier rows" in said[-1]["said"]
        state["export"] = {"ok": False, "said": "Not exported - stopped at name: x. Nothing was emailed.",
                           "week": "16/11/2026-22/11/2026"}
        said = go()                                                              # the export failed: nothing built
        assert len(ran) == 1 and len(said) == 1 and said[0]["ok"] is False and "Nothing was emailed" in said[0]["said"]
        state["export"] = export_ok
        job["send"] = False                                                      # a page from before: preview only
        said = go()
        assert len(ran) == 1 and len(said) == 1 and said[0]["ok"]
        assert "previewed into Files (nothing sent)" in said[0]["said"]
    finally:
        A.run, A._req, A.report, A.snap_outbox, A.push_new_files, A.RAIL_RAW, A.RAIL_LAST = keep
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
