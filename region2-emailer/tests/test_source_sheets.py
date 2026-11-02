"""Which sheets hold orders to email, and an order typed in by hand picks up every sheet it is on - a British Steel line on
one and an Inframat line on another. Made-up orders and files only.

    python tests/test_source_sheets.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import order_index as I  # noqa: E402
import source_sheets as S  # noqa: E402

PREFIX, MARKERS = "synergy_dhl_haulier_extract", ["bs batch", "bs ack", "bs oits", S.MASTER + "synergy_dhl_haulier_extract"]


def wanted(name, subject=""):
    return S.is_wanted(name, subject, PREFIX, MARKERS)


def test_the_master_sheets_a_batch_comes_as_hold_orders_whatever_the_subject():
    assert wanted("Master - Synergy_DHL_Haulier_Extract_ 261027 - BS.xlsx", "FW: BS Batch - 27/10/2026.")
    assert wanted("Master - Synergy_DHL_Haulier_Extract_ 261109 - INF.xlsx", "FW: Inframat Batch - 09/11/2026.")
    assert wanted("Master - Synergy_DHL_Haulier_Extract_ 261020 - BS V1.xlsx", "")


def test_any_other_master_file_is_still_nothing_even_on_a_bs_thread():
    assert not wanted("Master Template.xlsx", "FW: BS Batch - 27/10/2026.")
    assert not wanted("Master - Rail Plan.xlsx", "FW: BS Batch - 27/10/2026.")


def test_the_extract_and_the_bs_files_are_read_as_before_and_nothing_else():
    assert wanted("Synergy_DHL_Haulier_Extract 22102026.xlsx")
    assert wanted("261105 - BS Ack 28.10.26.xlsx")
    assert wanted("anything.xlsx", "RE: BS OITS this week")
    assert not wanted("Week 45 Courier sheet.xlsx", "Media sets")
    assert not wanted("image001.png", "FW: BS Batch - 27/10/2026.")


class _Att:
    def __init__(self, name):
        self.FileName, self.saved = name, []

    def SaveAsFile(self, path):
        self.saved.append(path)


class _Atts:
    def __init__(self, names):
        self.items = [_Att(n) for n in names]
        self.Count = len(self.items)

    def Item(self, i):
        return self.items[i - 1]


class _Mail:
    def __init__(self, *names):
        self.Attachments = _Atts(names)


class _NS:
    def __init__(self, mails):
        self.mails = mails

    def GetItemFromID(self, e, s):
        return self.mails[e]


def test_an_order_on_several_sheets_comes_back_once_for_each_sheet():
    keep = I.load
    try:
        I.load = lambda: {"orders": {"9100700": [
            {"e": "a", "s": "x", "f": "inf.xlsx"}, {"e": "b", "s": "x", "f": "bs.xlsx"},
            {"e": "c", "s": "x", "f": "bs.xlsx"},          # the same sheet sent again
            {"e": "gone", "s": "x", "f": "old.xlsx"},      # a mail since deleted
            {"e": "d", "s": "x", "f": "moved.xlsx"}]}}     # its attachment no longer on the mail
        ns = _NS({"a": _Mail("image.png", "inf.xlsx"), "b": _Mail("bs.xlsx"), "c": _Mail("bs.xlsx"), "d": _Mail("other.xlsx")})
        got = [fn for _, fn in I.lookup_all(ns, "9100700-1-1", "out.xlsx")]
        assert got == ["inf.xlsx", "bs.xlsx"], got
        assert list(I.lookup_all(ns, "9100799", "out.xlsx")) == []
    finally:
        I.load = keep


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
