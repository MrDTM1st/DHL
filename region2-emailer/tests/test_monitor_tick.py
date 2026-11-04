"""The live monitor (monitor_tick): no batch is built under a review he is in, and the extracts and forms it has seen are
remembered in the order they came, the oldest let go first. A stand-in mailbox; made-up ids only.

    python -m pytest -q tests/test_monitor_tick.py
"""
import os
import sys
import time
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


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
    monkeypatch.delitem(sys.modules, "monitor_tick", raising=False)
    import monitor_tick
    for name in ("SEEN", "PHASE2_DUE", "PUSH_DUE"):
        monkeypatch.setattr(monitor_tick, name, str(tmp_path / name))
    monkeypatch.setattr(monitor_tick, "HERE", str(tmp_path))
    yield monitor_tick
    sys.modules.pop("monitor_tick", None)


def test_no_batch_is_built_while_he_is_reviewing_one_and_the_extract_waits_its_turn(M, monkeypatch):
    did = []
    monkeypatch.setattr(M, "run", lambda args: did.append(args) or (0, ""))
    monkeypatch.setattr(M, "report", lambda *a, **k: did.append(a[0]))
    monkeypatch.setattr(M, "_review_open", lambda: True)
    state = {"ext_ids": ["e0", "e1"]}
    M._build(state, [("e1", "Haulier Extract.xlsx")])
    assert did == []                                          # nothing built, nothing said over his review
    assert M._load()["ext_ids"] == ["e0"]                     # unseen again: the next tick finds it
    assert not M._load().get("build_tries")                   # and no try of its three spent
    monkeypatch.setattr(M, "_review_open", lambda: False)     # he has sent it
    M._build(M._load(), [("e1", "Haulier Extract.xlsx")])
    assert did == [["build_drafts.py", "batch"], "done"]
