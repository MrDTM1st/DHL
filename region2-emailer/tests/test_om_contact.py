"""A DTS whose site can't be reached: the Order Management request (om_contact.py) and its dashboard wording
(tests/om_contact.test.mjs, run under Node when it's installed). Made-up refs, sites and people only.

    python -m pytest tests/test_om_contact.py -q
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import om_contact as om  # noqa: E402

T = datetime(2026, 11, 9, 10, 0)
HAULIER = "jobs@haulier.example"


def test_address_is_order_management():
    assert om.OM == "ordermanagement@networkrail.co.uk"
    assert om.ORDER_MANAGEMENT["name"] == "Order Management"


def test_subject_matches_every_other_alt_contact_email():
    s = om.subject_for({"orders": ["NN0000001-1"], "worksite": "NWR - EXAMPLE  MDU", "postcode": "AA1 1AA"})
    assert s == "NN0000001-1 NWR - EXAMPLE MDU AA1 1AA - alternative contact needed"


def test_pick_forwards_the_newest_dts_mail():
    cands = [{"people": {"supplier@example.net", "dhlroad@networkrail.co.uk"}, "when": T},
             {"people": {"me@dhl.com"}, "when": datetime(2026, 11, 8)}]
    assert om.pick(cands, {HAULIER}) == (0, "forward")


def test_pick_answers_a_thread_order_management_is_on():
    cands = [{"people": {"supplier@example.net"}, "when": T},
             {"people": {om.OM, "me@dhl.com"}, "when": datetime(2026, 11, 6)}]
    assert om.pick(cands, {HAULIER}) == (1, "reply")


def test_pick_never_uses_a_hauliers_thread():
    cands = [{"people": {HAULIER, "me@dhl.com"}, "when": T}]
    assert om.pick(cands, {HAULIER}) == (None, None)
    cands.append({"people": {"supplier@example.net"}, "when": datetime(2026, 11, 1)})
    assert om.pick(cands, {HAULIER}) == (1, "forward")


def test_pick_with_nothing_is_a_new_email():
    assert om.pick([], {HAULIER}) == (None, None)


def test_tried_lists_the_site_contact_only():
    mails = [{"to": [("Site Person", "Site@Example.net"), ("Delali", "someone@dhl.com")], "at": T},
             {"to": [("Haulier", HAULIER)], "at": T},
             {"to": [("Order Management", om.OM), ("ZX-DHLRoad", "DHLRoad@networkrail.co.uk")], "at": T},
             {"to": [("Site Person", "site@example.net")], "at": datetime(2026, 11, 6, 9, 5)}]
    got = om.tries_from_sent(mails, {HAULIER})
    assert got == [{"to": "site@example.net", "name": "Site Person", "at": "06/11/2026 09:05"},
                   {"to": "site@example.net", "name": "Site Person", "at": "09/11/2026 10:00"}], got


def test_dashboard_wording():
    node = shutil.which("node")
    if not node:
        print("SKIP  node is not installed")
        return
    r = subprocess.run([node, os.path.join(HERE, "om_contact.test.mjs")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("om_contact: all passed")
