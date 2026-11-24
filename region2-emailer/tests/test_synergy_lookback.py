"""The batch and the wait-list scan read the normal extracts filed in Synergy Upload back over the wait list's whole
lead (his 24/11 "you missed this"): an order whose extract came while he was away sat in batches nobody sent, the
extract was filed, and at a 3-day look-back the order was in no batch and on no list four days on.

build_drafts reads the private config at import, so this reads its source.

    python tests/test_synergy_lookback.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(os.path.dirname(HERE), "build_drafts.py"), encoding="utf-8").read()


def test_synergy_upload_is_read_back_over_the_wait_lists_whole_lead():
    assert "SYNERGY_UPLOAD_DAYS = waitlist.LEAD_DAYS" in SRC
    calls = [ln for ln in SRC.splitlines() if "find_synergy_upload(" in ln and not ln.lstrip().startswith("def ")]
    assert calls and all("days=SYNERGY_UPLOAD_DAYS" in ln for ln in calls), calls


if __name__ == "__main__":
    test_synergy_upload_is_read_back_over_the_wait_lists_whole_lead()
    print("ok")
    sys.exit(0)
