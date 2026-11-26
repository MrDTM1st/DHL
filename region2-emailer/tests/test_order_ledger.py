"""order_ledger: what the toolkit did to an order's lines, for him to answer with (his 26/11), and the copies Book may book."""
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import order_ledger as L  # noqa: E402


def test_an_orders_number_is_read_off_any_of_its_lines():
    assert L.order_of("9100001-1-1_C1") == "9100001" and L.order_of("9100001") == "9100001"
    assert L.order_of("AH1/1/26EXEX") == "AH1/1/26EXEX" and L.order_of("AH1/1/26EXEX_RB") == "AH1/1/26EXEX"
    assert L.ADDED.search("9100001-1-1_C1") and L.ADDED.search("9100001-1-1_RB")
    assert not L.ADDED.search("9100001-1-1_S12")


def test_what_was_done_is_kept_and_told_in_plain_words(tmp_path):
    p = str(tmp_path / "l.jsonl")
    now = datetime(2026, 11, 26, 14, 0)
    L.log("split", "9100001-1-1_S2", "into 4 equal parts: 9100001-1-1_S16, 9100001-1-1_S17", path=p, now=now,
          new=["9100001-1-1_S16", "9100001-1-1_S17"])
    L.log("cancel", "9100001-1-1_C1", "UNSCHEDULED -> CANCELLED", path=p, now=now)
    L.log("cancel", "9100002-1-1", "UNSCHEDULED -> CANCELLED", path=p, now=now)
    assert [e["action"] for e in L.events("9100001", path=p)] == ["split", "cancel"]
    text = "\n".join(L.history("9100001-1-1", path=p))
    assert "9100001-1-1_C1: cancelled - UNSCHEDULED -> CANCELLED" in text and "9100002" not in text
    assert "nothing kept" in L.history("9100009", path=p)[1]


def test_book_may_book_only_the_copies_made_here_or_cleared_by_him(tmp_path):
    p = str(tmp_path / "l.jsonl")
    L.log("copy", "9100001-1-1_S3", "plan", path=p, new=["9100001-1-1_C1"], replaces="9100001-1-1_S3")
    L.log("allow", "9100001-1-1_C2", "cleared for Book by hand", path=p, why="site wants one more")
    L.log("copy", "9100002-1-1", "plan", path=p, new=["9100002-1-1_C1"])
    assert L.known_lines(["9100001"], path=p) == ["9100001-1-1_C1", "9100001-1-1_C2"]
    assert L.known_lines([], path=p) == []


def test_a_non_conformance_and_an_original_quantity_are_remembered(tmp_path):
    p = str(tmp_path / "l.jsonl")
    assert not L.non_conformed("9100001-1-1_S3", path=p) and L.original("9100001", path=p) is None
    L.log("nc", "9100001-1-1_S3", "SUPP: not ready", path=p)
    L.remember_original("9100001", 1150, path=p)
    assert L.non_conformed("9100001-1-1_s3", path=p) and L.original("9100001-1-1_S3", path=p) == 1150
