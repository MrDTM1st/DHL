"""Who `hauliers.py find` suggests for a job, by where the job is: a haulier
with no-go areas is never sent there, and one who works only one patch is only
sent inside it. Made-up hauliers only - no geocoding, no quote history.

    python tests/test_haulier_coverage.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import hauliers  # noqa: E402

CAPS = ["Artic Hiab", "Bags"]
POOL = [
    {"name": "Anywhere Co", "tier": "tier1", "caps": CAPS, "postcode": ""},
    {"name": "Patch Co", "tier": "tier1", "caps": CAPS, "postcode": "",
     "only_areas": ["SE", "CB", "PE15"], "only_scope": "delivery"},
    {"name": "Both Ends Co", "tier": "tier1", "caps": CAPS, "postcode": "",
     "only_areas": ["SE", "DN"]},
    {"name": "Not North Co", "tier": "tier2", "caps": CAPS, "postcode": "",
     "no_go_areas": ["DN", "YO"], "no_go_scope": "delivery"},
]
hauliers.load = lambda: {"hauliers": [dict(h) for h in POOL], "couriers": []}
hauliers.geocode = lambda pcs: {}


def names(frm, to):
    return [h["name"] for h in hauliers.recommend(frm, ["artic hiab"], to)[0]]


def test_a_patch_haulier_is_only_sent_inside_their_patch():
    assert "Patch Co" in names("DN16 1AA", "SE18 6AA")
    assert "Patch Co" in names("DN16 1AA", "CB7 4AA")       # a whole area
    assert "Patch Co" in names("DN16 1AA", "PE15 8AA")      # one district of a big area...
    assert "Patch Co" not in names("DN16 1AA", "PE25 1AA")  # ...and not the rest of it
    assert "Patch Co" not in names("DN16 1AA", "NG10 5AA")


def test_a_bare_district_still_counts():
    assert "Patch Co" in names("DN16", "PE15")
    assert "Patch Co" not in names("DN16", "PE25")


def test_the_scope_says_which_end():
    assert "Both Ends Co" in names("DN16 1AA", "SE18 6AA")
    assert "Both Ends Co" not in names("NG10 1AA", "SE18 6AA")   # pick-up outside the patch
    assert "Not North Co" in names("DN16 1AA", "SE18 6AA")       # collecting up north is fine
    assert "Not North Co" not in names("SE18 1AA", "DN16 6AA")   # delivering there is not


def test_an_unknown_postcode_rules_nobody_out():
    assert set(names("", "")) == {h["name"] for h in POOL}


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
