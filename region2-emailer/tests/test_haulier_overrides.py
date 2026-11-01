"""The overrides a contact-sheet re-import can't wipe: caps_add adds a capability the sheet leaves out and keeps the
sheet's own list, caps replaces it outright, and every other key just sets. Made-up hauliers only.

    python tests/test_haulier_overrides.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import hauliers  # noqa: E402

hauliers._OVERRIDES = {"adder co": {"caps_add": ["Rear Steer", "Moffett"]},
                       "swapper co": {"caps": ["Log Grab"]},
                       "patch co": {"only_areas": ["SE"], "only_scope": "delivery"}}


def _load(*hs):
    return {h["name"]: h for h in hauliers._apply_overrides({"hauliers": [dict(h) for h in hs]})["hauliers"]}


def test_caps_add_keeps_the_sheet_list_and_adds_once():
    got = _load({"name": "Adder Co Ltd", "caps": ["Artic Hiab", "Moffett"]})
    assert got["Adder Co Ltd"]["caps"] == ["Artic Hiab", "Moffett", "Rear Steer"]
    assert "caps_add" not in got["Adder Co Ltd"]


def test_caps_add_still_works_with_no_caps_on_the_sheet():
    assert _load({"name": "Adder Co"})["Adder Co"]["caps"] == ["Rear Steer", "Moffett"]


def test_caps_replaces_and_other_keys_set():
    got = _load({"name": "Swapper Co", "caps": ["Artic Hiab"]}, {"name": "Patch Co", "caps": ["Bags"]},
                {"name": "Untouched Co", "caps": ["Bags"]})
    assert got["Swapper Co"]["caps"] == ["Log Grab"]
    assert got["Patch Co"]["only_areas"] == ["SE"] and got["Patch Co"]["caps"] == ["Bags"]
    assert got["Untouched Co"] == {"name": "Untouched Co", "caps": ["Bags"]}


def test_the_override_list_is_not_changed_by_applying_it():
    _load({"name": "Adder Co", "caps": []})
    assert hauliers._OVERRIDES["adder co"] == {"caps_add": ["Rear Steer", "Moffett"]}


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
