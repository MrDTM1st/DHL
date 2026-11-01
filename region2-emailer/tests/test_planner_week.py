"""His week off the Transport Planners sheet: every cell with his name is a duty that day, partners and notes kept,
his region and Serviceable Materials never listed; the newest version of each week's sheet is found wherever its
mail was filed. Made-up names only.

    python tests/test_planner_week.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import planner_week as W  # noqa: E402

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
ROWS = [
    ["w/c 2nd November", datetime(2026, 10, 2), None, None, None, None],     # the sheet's own dates can be wrong
    [None] + DAYS,
    ["Road 06:30 to 09:00", "Sam", "Sam", "Jo", "Jo", "Jo"],
    ["Road 15:00 to 17:30", "Delali", "Kim", "Jo", "Kim", "Pat"],
    [None],
    ["Regional Planning"] + DAYS + [None, "Kim", 3],                        # a side table beside the days
    ["Region 1 - Flats & HIABS", "Pat", "Pat", "Pat", "Pat", "Pat", None, "Delali", 4],
    ["Region 2 - Flats & HIABS"] + ["Delali"] * 5,
    ["Projects"] + DAYS,
    ["Electrification", "Kim (Emergencies Only)", "Jo", "Jo", "Jo", "Delali (Emergencies Only)"],
    ["S&C", "Sam / Delali", "Sam / Kim", None, None, None],
    ["AD HOC"] + DAYS,
    ["Stoneblower", "Kim", "Delali", "Delali", "Jo", "Kim"],
    ["Media Sets", "Pat", "Pat", "Pat", "Pat", "Pat"],
    ["Reports"] + DAYS,
    ["Rail Plan Update (Current week)", "Jo", "Delali", "Sam", "Kim", "Jo"],
    ["Rail Plan Update (Following week)", None, None, None, "Delali", "Pat"],
    ["Uploads:"] + DAYS,
    ["Serviceable Materials"] + ["Delali"] * 5,
    ["HR"] + DAYS,
    [None, "Sam & Kim Off", "Kim Off", None, None, "Delali / Pat Off"],
    ["On call", "Pat", "Pat", "Pat", "Pat", "Delali"],
]


def _book(path, rows=ROWS):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Main"
    for r in rows:
        ws.append(r)
    wb.create_sheet("Shift Patterns").append(["Delali", "Region 2"])        # other tabs are never read
    wb.save(path)


def test_the_week_and_version_come_from_the_file_name():
    assert W.week_of("Transport Planners wc 02.11.26 v2.xlsx") == (date(2026, 11, 2), 2)
    assert W.week_of("Transport Planners wc 28.09.26 v1.xlsx") == (date(2026, 9, 28), 1)
    assert W.week_of("Transport Planner wc 2.11.2026.xlsx") == (date(2026, 11, 2), 1)
    assert W.week_of("Transport Planners wc 31.02.26 v1.xlsx") is None and W.week_of("Rota.xlsx") is None


def test_every_cell_with_his_name_is_his_duty_and_his_region_never_is():
    got = W.duties(ROWS)
    what = {d: [x["what"] for x in got.get(d.lower(), [])] for d in DAYS}
    assert what == {
        "Monday": ["Road 15:00 to 17:30", "S&C"],
        "Tuesday": ["Stoneblower", "Rail Plan Update (Current week)"],
        "Wednesday": ["Stoneblower"],
        "Thursday": ["Rail Plan Update (Following week)"],
        "Friday": ["Electrification", "Delali / Pat Off", "On call"],
    }, what
    snc = got["monday"][1]
    assert snc["with"] == ["Sam"] and snc["section"] == "Projects"
    assert got["friday"][0]["note"] == "(Emergencies Only)"
    assert got["tuesday"][0]["section"] == "AD HOC"


def test_a_sheet_reads_into_dated_days_monday_to_friday():
    tmp = tempfile.mkdtemp(prefix="planner-test-")
    try:
        path = os.path.join(tmp, "Transport Planners wc 02.11.26 v2.xlsx")
        _book(path)
        wk = W.read(path)
        assert wk["wc"] == "02/11/2026" and wk["version"] == 2
        assert [(d["day"], d["date"]) for d in wk["days"]] == [
            ("Monday", "02/11/2026"), ("Tuesday", "03/11/2026"), ("Wednesday", "04/11/2026"),
            ("Thursday", "05/11/2026"), ("Friday", "06/11/2026")]
        assert "Delali" not in W.say(wk).split("\n", 1)[1].replace("Delali / Pat Off", "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_weeks_already_over_are_left_off_the_card():
    tmp = tempfile.mkdtemp(prefix="planner-test-")
    keep = W.PATH
    W.PATH = os.path.join(tmp, "_planner_week.json")
    try:
        with open(W.PATH, "w", encoding="utf-8") as f:
            json.dump({"at": "x", "weeks": [{"wc": "26/10/2026", "days": []}, {"wc": "02/11/2026", "days": []}]}, f)
        assert [w["wc"] for w in W.load(date(2026, 11, 1))["weeks"]] == ["26/10/2026", "02/11/2026"]   # its Sunday
        assert [w["wc"] for w in W.load(date(2026, 11, 2))["weeks"]] == ["02/11/2026"]
        os.remove(W.PATH)
        assert W.load() == {}
    finally:
        W.PATH = keep
        shutil.rmtree(tmp, ignore_errors=True)


class _Att:
    def __init__(self, name):
        self.FileName = name


class _Atts:
    def __init__(self, names):
        self.items = [_Att(n) for n in names]
        self.Count = len(self.items)

    def Item(self, i):
        return self.items[i - 1]


class _Mail:
    def __init__(self, days_ago, names, sender="Sam Example"):
        self.ReceivedTime = datetime.now() - timedelta(days=days_ago)
        self.Attachments = _Atts(names)
        self.SenderName = sender


class _Items(list):
    def Restrict(self, q):
        assert "Transport Planner" in q
        return self


class _Folder:
    def __init__(self, name, mails=(), subs=()):
        self.Name, self.Items, self.Folders = name, _Items(mails), list(subs)


def _stub_build_drafts(inbox):
    import types
    sys.modules["build_drafts"] = types.SimpleNamespace(dhl_store=lambda ns: "dhl",
                                                        sub=lambda f, name: inbox if name == "Inbox" else None)


def test_newest_picks_the_highest_version_per_week_across_folders():
    inbox = _Folder("Inbox", [_Mail(2, ["Transport Planners wc 02.11.26 v1.xlsx"])], [
        _Folder("Team", [_Mail(1, ["Transport Planners wc 02.11.26 v2.xlsx", "notes.xlsx"], sender="Kim Example")]),
        _Folder("Completed", [_Mail(9, ["Transport Planners wc 26.10.26 v3.xlsx"]),
                              _Mail(40, ["Transport Planners wc 21.09.26 v9.xlsx"])])])         # too old to look at
    keep = sys.modules.get("build_drafts")
    _stub_build_drafts(inbox)
    try:
        got = W.newest(None)
    finally:
        if keep is None:
            sys.modules.pop("build_drafts", None)
        else:
            sys.modules["build_drafts"] = keep
    assert sorted(got) == [date(2026, 10, 26), date(2026, 11, 2)]
    assert got[date(2026, 11, 2)]["version"] == 2 and got[date(2026, 11, 2)]["from"] == "Kim Example"
    assert got[date(2026, 10, 26)]["name"] == "Transport Planners wc 26.10.26 v3.xlsx"


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
