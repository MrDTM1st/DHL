"""What a site's answer to "Do we need to bring our own offloading? (HIAB or Moffet)" means: a bare yes is a HIAB
whatever the load (his rule 01/11) - a Moffett only when they say Moffett - and no is the site's own.

    python tests/test_offloading.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import delivery_details as dd  # noqa: E402

dd.recall = lambda field, raw: None      # what was learned on this PC never decides a test


def test_a_bare_yes_is_a_hiab_whatever_the_load():
    for kind in (None, "sleepers", "ballast", "rails"):
        assert dd.parse_offloading("yes", kind) == ("HIAB", dd.HIGH), kind
        assert dd.parse_offloading("Do we need to bring our own offloading? (HIAB or Moffet) yes", kind) == \
            ("HIAB", dd.HIGH), kind


def test_a_moffett_only_when_they_say_moffett():
    assert dd.parse_offloading("(HIAB or Moffet) yes moffet please", "sleepers") == ("MOFFETT", dd.HIGH)
    assert dd.parse_offloading("Moffatt required") == ("MOFFETT", dd.HIGH)
    assert dd.parse_offloading("hiab please") == ("HIAB", dd.HIGH)


def test_no_is_the_sites_own_and_both_is_asked():
    assert dd.parse_offloading("No - loose ballast being tipped") == ("SITE/NONE", dd.HIGH)
    assert dd.parse_offloading("we would need a hiab and a moffett") == ("BOTH", dd.AMBER)   # asked, not picked
    assert dd.parse_offloading("(HIAB or Moffet)") == (None, dd.AMBER)          # only our own menu - no answer


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
