"""The Access Bridge reader kept open (03/11): one request a line, one answer a line, a reader that hangs is killed
rather than waited on twice, one that dies is started again, and a combo box's picked row is read. No Java here: a
stand-in reader process, and a stand-in Access Bridge.

    python -m pytest -q tests/test_ctms_jab_kept.py
"""
import io
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_jab as J  # noqa: E402

# a reader that says it is ready, then answers each request with what it was asked - or hangs, or dies
STAND_IN = r'''
import json, sys, time
mode = sys.argv[1]
print(json.dumps({"ok": True, "ready": True}), flush=True)
n = 0
for line in sys.stdin:
    n += 1
    ask = json.loads(line)
    if mode == "hang" and n == 2:
        time.sleep(30)
    if mode == "die" and n == 2:
        sys.exit(1)
    print(json.dumps({"ok": True, "java_windows": 1, "elements": [], "asked": ask, "n": n}), flush=True)
'''


def _reader(mode="ok"):
    return J.Reader([sys.executable, "-c", STAND_IN, mode])


def test_one_reader_answers_read_after_read():
    r = _reader()
    try:
        a = r.read([1, 2], skip=["Planning"], skip_roles=["tree"])
        b = r.read([3])
        assert a["asked"] == {"hwnds": [1, 2], "skip": ["Planning"], "skip_roles": ["tree"]}
        assert (a["n"], b["n"]) == (1, 2)                 # the same process: it counted both
    finally:
        r.stop()


def test_a_reader_that_hangs_is_killed_and_the_next_read_starts_a_new_one():
    r = _reader("hang")
    try:
        r.read([1])
        with pytest.raises(subprocess.TimeoutExpired):
            r.read([1], timeout=1)
        assert r.proc is None
        r.cmd[-1] = "ok"
        assert r.read([1])["n"] == 1                       # a fresh one
    finally:
        r.stop()


def test_a_reader_that_dies_says_so_and_comes_back():
    r = _reader("die")
    try:
        r.read([1])
        with pytest.raises(RuntimeError):
            r.read([1], timeout=5)
        assert r.read([1])["n"] == 1
    finally:
        r.stop()


def test_the_served_reader_answers_each_line_and_ends_with_its_input(monkeypatch):
    class Api:
        pumped = 0

        def pump(self, s):
            Api.pumped += 1
    monkeypatch.setattr(J, "read", lambda hwnds, api=None, skip=(), skip_roles=(): {
        "ok": True, "hwnds": hwnds, "skip": list(skip), "roles": list(skip_roles)})
    out = io.StringIO()
    J.serve(io.StringIO(json.dumps({"hwnds": [5], "skip_roles": ["tree"]}) + "\nnot json\n"), out, api=Api())
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["ready"]
    assert lines[1] == {"ok": True, "hwnds": [5], "skip": [], "roles": ["tree"]}
    assert lines[2]["ok"] is False                         # a bad line is answered, not the end of the reader
    assert Api.pumped >= 1


class FakeBridge:
    """Just enough Access Bridge for a walk: objects are ints, each with its info and children."""

    def __init__(self, tree, picks=None, texts=None):
        self.tree, self.picks, self.texts = tree, picks or {}, texts or {}
        self.released = []
        self.has_selection = True

    def info(self, vm, ac):
        n = self.tree[ac]
        return {"role": n["r"], "name": n.get("nm", ""), "description": "", "states": {"visible", "enabled"},
                "children": len(n.get("kids", [])), "x": 1, "y": 1, "w": n.get("w", 10), "h": 10,
                "text": n["r"] in ("text",), "selection": ac in self.picks}

    def child(self, vm, ac, k):
        return self.tree[ac]["kids"][k]

    def text(self, vm, ac, most):
        return self.texts.get(ac, "")

    def release(self, vm, ac):
        self.released.append(ac)

    def picked(self, vm, ac, inside=None):
        for holder in (ac, inside):
            if holder in self.picks:
                return self.picks[holder]
        return None


def _walk(tree, root=1, **kw):
    out, ctx = [], {"visited": 0, "cut": False, "partial": False, "deadline": 10 ** 12, "focus": None, "skip": (),
                    "skip_roles": kw.get("skip_roles", ())}
    J.walk(kw.get("api") or FakeBridge(tree, kw.get("picks"), kw.get("texts")), 0, root, out, ctx, 1)
    return out


def test_a_drop_downs_picked_row_is_its_value():
    tree = {1: {"r": "internal frame", "nm": "Order details", "kids": [2]},
            2: {"r": "combo box", "nm": "Veh Type", "kids": [3]},
            3: {"r": "list", "nm": "", "w": 0, "kids": []}}
    got = {e["nm"]: e.get("v") for e in _walk(tree, picks={3: "NR_40ft  Artic Flatbed"})}
    assert got["Veh Type"] == "NR_40ft  Artic Flatbed"


def test_an_editable_drop_down_gives_its_words_from_its_text():
    tree = {1: {"r": "combo box", "nm": "Sched", "kids": [2, 3]},
            2: {"r": "text", "nm": "Sched", "kids": []}, 3: {"r": "list", "nm": "", "w": 0, "kids": []}}
    assert _walk(tree, texts={2: "261103"})[0]["v"] == "261103"


def test_a_drop_down_with_nothing_picked_still_reads_as_nothing():
    tree = {1: {"r": "combo box", "nm": "To Plan Reg", "kids": [2]}, 2: {"r": "list", "nm": "", "w": 0, "kids": []}}
    assert "v" not in _walk(tree)[0]


def test_the_manifest_tree_is_left_out_when_only_the_well_is_wanted():
    tree = {1: {"r": "internal frame", "nm": "Planning", "kids": [2, 4]},
            2: {"r": "tree", "nm": "", "kids": [3]}, 3: {"r": "label", "nm": "02/11/26 08:00 MAN-01000001 (ACCEPTED)"},
            4: {"r": "push button", "nm": "Order Filters"}}
    assert any("MAN-" in e["nm"] for e in _walk(tree))
    names = [e["nm"] for e in _walk(tree, skip_roles=("tree",))]
    assert "Order Filters" in names and not any("MAN-" in n for n in names)
