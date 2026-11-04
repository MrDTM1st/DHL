"""The team's DTS sheet: rows go on the right tab in the next empty row, nothing else in the workbook changes, nothing goes on
twice, a sheet someone has open just waits, and only a booked job is added. Made-up orders only.

    python tests/test_dts_sheet.py
"""
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import openpyxl  # noqa: E402
import dts_book as D  # noqa: E402
import dts_sheet as S  # noqa: E402

ROW = {"nn": "NN9000001-5/1", "sub": "N/A", "cat": "0086/000001", "qty": 2, "post": "EN1 1AA", "date": "20/11/2026",
       "req": "EXAMPLE SUPPLIER", "planner": "Delali"}


def _book(folder, blanks=3):
    p = os.path.join(folder, "DTS.xlsx")
    wb = openpyxl.Workbook()
    old = wb.active
    old.title = "2025"
    old["A1"] = "kept"
    ws = wb.create_sheet("2026")
    ws.append(["NN No.", "Subline", "Catalogue No.", "Quantity", "Delivery Address", "Collection date", "Requestor", "Planner", "Comments"])
    ws.append(["NN9000000-1", 3, "0057/000001", 10, "EN2 2BB", datetime(2026, 11, 2), "OLD SUPPLIER", "Sam", "a comment"])
    for r in range(3, 3 + blanks):         # the team's formatted empty rows
        ws.cell(row=r, column=6).number_format = "dd/mm/yyyy"
        ws.cell(row=r, column=1).number_format = "@"
    ws["F2"].number_format = "dd/mm/yyyy"
    wb.save(p)
    return p


def _read(p, tab="2026"):
    return [list(r[:9]) for r in openpyxl.load_workbook(p)[tab].iter_rows(values_only=True)]


def test_rows_go_in_the_next_empty_row_with_a_real_date_and_number():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        got = D.add_rows(p, [ROW, dict(ROW, nn="NN9000001-5/2", cat="0086/000002", qty=4)])
        assert got == {"rows": [3, 4], "skipped": 0, "tab": "2026"}
        rows = _read(p)
        assert rows[2][:8] == ["NN9000001-5/1", "N/A", "0086/000001", 2, "EN1 1AA", datetime(2026, 11, 20), "EXAMPLE SUPPLIER", "Delali"]
        assert rows[3][0] == "NN9000001-5/2" and rows[3][3] == 4
        assert rows[1][8] == "a comment"
        assert openpyxl.load_workbook(p)["2026"]["F3"].number_format == "dd/mm/yyyy"


def test_past_the_formatted_rows_it_still_goes_on_and_the_size_follows():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d, blanks=0)
        D.add_rows(p, [dict(ROW, nn=f"NN9000001-5/{i}", cat=f"0086/00000{i}") for i in range(1, 4)])
        ws = openpyxl.load_workbook(p)["2026"]
        assert ws["A5"].value == "NN9000001-5/3" and ws.max_row == 5


def test_nothing_else_in_the_workbook_changes():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        with zipfile.ZipFile(p) as z:
            before = {n: z.read(n) for n in z.namelist()}
            part = D.tab_part(z, 2026)
        D.add_rows(p, [ROW])
        with zipfile.ZipFile(p) as z:
            assert z.namelist() == list(before)
            assert [n for n in before if z.read(n) != before[n]] == [part]
        assert _read(p, "2025")[0][0] == "kept"


def test_a_line_already_there_isnt_added_twice_and_nothing_is_touched_for_none():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        D.add_rows(p, [ROW])
        stamp = os.stat(p).st_mtime_ns
        assert D.add_rows(p, [ROW]) == {"rows": [], "skipped": 1, "tab": "2026"}
        assert os.stat(p).st_mtime_ns == stamp
        got = D.add_rows(p, [ROW, dict(ROW, cat="0086/000009")])
        assert got["rows"] == [4] and got["skipped"] == 1


def test_a_year_with_no_tab_says_so_and_changes_nothing():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        stamp = os.stat(p).st_mtime_ns
        try:
            D.add_rows(p, [dict(ROW, date="02/01/2027")])
            raise AssertionError("it went on")
        except ValueError as e:
            assert "2027" in str(e)
        assert os.stat(p).st_mtime_ns == stamp and os.listdir(d) == ["DTS.xlsx"]


def test_a_sheet_someone_has_open_waits_and_leaves_nothing_behind():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        real = os.replace
        D.BACKUPS, keep = os.path.join(d, "b"), D.BACKUPS

        def refuse(a, b):
            raise PermissionError(13, "in use")

        D.os.replace = refuse
        try:
            D.add_rows(p, [ROW])
            raise AssertionError("it went on")
        except D.Busy as e:
            assert "open" in str(e)
        finally:
            D.os.replace = real
            D.BACKUPS = keep
        assert sorted(os.listdir(d)) == ["DTS.xlsx", "b"] and len(_read(p)) >= 2 and _read(p)[2][0] is None


def test_awkward_text_is_kept_as_written():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        D.add_rows(p, [dict(ROW, req="A & B <Rail> LTD ")])
        assert _read(p)[2][6] == "A & B <Rail> LTD "


def test_a_dts_tables_lines_are_read_from_either_form():
    xls = [["", "NN/NR Number*", "Line No*", "Sub Line No", "Catologue No*", "Item", "Weight", "Pallets", "Total units*"],
           ["", "NN9000001-5/1", "", "", "0086/000001", "BOOM", "495KG", "2", 2.0],
           [" ", "NN9000001-5/2", "", "", "0086/000002", "BOOM", "469KG", "2", 2.0],
           ["Account", "", "", "", "", "", "", "", ""]]
    assert S.from_table(xls) == [{"nn": "NN9000001-5/1", "sub": "N/A", "cat": "0086/000001", "qty": 2},
                                 {"nn": "NN9000001-5/2", "sub": "N/A", "cat": "0086/000002", "qty": 2}]
    pdf = [["NR Number", "Line No", "Sub Line No", "Supplier Del Note Number", "Catologue No", "Weight in Kgs", "No of Pallets", "Total units"],
           ["NN9000002-1", "88", "4", "111", "0057/000001", None, None, "2"],
           [None, "89", "1", None, "0057/000002", None, None, "12"]]
    assert S.from_table(pdf) == [{"nn": "NN9000002-1", "sub": "4", "cat": "0057/000001", "qty": 2},
                                 {"nn": "NN9000002-1", "sub": "1", "cat": "0057/000002", "qty": 12}]


def test_only_a_booked_job_off_the_map_is_due_and_the_maps_date_carries_over():
    store = {"NN1": {"date": "01/11/2026"}, "NN2": {"date": "01/11/2026"}, "NN3": {"date": "01/11/2026"}, "NN4": {"done": "x"}}
    on_map = [{"orders": ["NN1"], "collection_date": "09/11/2026"}]
    assert S.due(store, on_map, {"NN1", "NN3", "NN4"}) == ["NN3"]           # NN2 isn't booked, NN1 is still showing
    assert store["NN1"]["date"] == "09/11/2026"


def test_a_job_with_something_unread_is_held_not_guessed():
    job = {"lines": [{"nn": "NN1", "sub": "N/A", "cat": "0086/1", "qty": None}], "date": "01/11/2026"}
    assert S.rows_for(job) == []
    assert S.rows_for(dict(job, lines=[])) == []
    assert S.rows_for({"lines": [{"nn": "NN1", "sub": "N/A", "cat": "0086/1", "qty": 1}], "date": ""}) == []
    assert S.rows_for({"lines": [{"nn": "NN1", "sub": "N/A", "cat": "0086/1", "qty": 1}], "date": "01/11/2026", "post": "EN1", "req": "X"})[0]["planner"] == S.PLANNER


def test_a_lines_collection_date_changes_and_nothing_else_does():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        D.add_rows(p, [ROW, dict(ROW, nn="NN9000001-5/2", cat="0086/000002", qty=4)])
        before = _read(p)
        with zipfile.ZipFile(p) as z:
            parts = {n: z.read(n) for n in z.namelist()}
            part = D.tab_part(z, 2026)
        got = D.set_date(p, "NN9000001-5/1", "0086/000001", "24/11/2026")
        assert got == {"row": 3, "tab": "2026", "was": "20/11/2026", "date": "24/11/2026"}
        after = _read(p)
        assert after[2][5] == datetime(2026, 11, 24)
        after[2][5] = before[2][5]
        assert after == before
        assert openpyxl.load_workbook(p)["2026"]["F3"].number_format == "dd/mm/yyyy"
        with zipfile.ZipFile(p) as z:
            assert [n for n in parts if z.read(n) != parts[n]] == [part]


def test_a_date_already_right_or_a_line_not_there_changes_nothing():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        D.add_rows(p, [ROW])
        stamp = os.stat(p).st_mtime_ns
        assert D.set_date(p, " nn9000001-5/1", "0086/000001", "20/11/2026")["was"] == "20/11/2026"
        for nn, cat in (("NN9000001-5/9", "0086/000001"), ("NN9000001-5/1", "0086/000009")):
            try:
                D.set_date(p, nn, cat, "24/11/2026")
                raise AssertionError("it changed")
            except ValueError as e:
                assert "isn't on" in str(e)
        assert os.stat(p).st_mtime_ns == stamp


def test_a_line_on_the_tab_twice_is_asked_about_not_guessed():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        D.add_rows(p, [ROW])
        wb = openpyxl.load_workbook(p)
        wb["2026"].append(["NN9000001-5/1", "N/A", "0086/000001", 1, "EN1 1AA", datetime(2026, 11, 21), "X", "Sam"])
        wb.save(p)
        try:
            D.set_date(p, "NN9000001-5/1", "0086/000001", "24/11/2026")
            raise AssertionError("it changed")
        except ValueError as e:
            assert "2 times" in str(e)


def test_a_date_change_on_a_sheet_someone_has_open_waits():
    with tempfile.TemporaryDirectory() as d:
        p = _book(d)
        D.add_rows(p, [ROW])
        real = os.replace
        D.BACKUPS, keep = os.path.join(d, "b"), D.BACKUPS

        def refuse(a, b):
            raise PermissionError(13, "in use")

        D.os.replace = refuse
        try:
            D.set_date(p, "NN9000001-5/1", "0086/000001", "24/11/2026")
            raise AssertionError("it changed")
        except D.Busy as e:
            assert "open" in str(e)
        finally:
            D.os.replace = real
            D.BACKUPS = keep
        assert _read(p)[2][5] == datetime(2026, 11, 20) and sorted(os.listdir(d)) == ["DTS.xlsx", "b"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
