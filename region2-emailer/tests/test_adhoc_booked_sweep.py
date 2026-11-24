"""The map's booked-in sweep: a manifest number in an ad hoc's thread takes it off the map - but not a haulier turning
the job down, or naming a manifest they are busy on (AQ's "we already have our pts driver on man 01575454", 02/11).
A stand-in mailbox; made-up refs and people only.

    python tests/test_adhoc_booked_sweep.py
"""
import os
import re
import sys
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# build_drafts reads the private config at import - the sweep only needs these four from it
bd = types.ModuleType("build_drafts")
bd._reply_top = lambda body: body.split("\nFrom:")[0]
bd._MAN_RE = re.compile(r"\bMAN[-\s]?\d{5,}", re.I)
bd._BOOKED_PHRASES = ("this order has been arranged with",)
bd.DHL_SMTP = "planner@example.com"
sys.modules.setdefault("build_drafts", bd)
import adhoc_booked_sweep as S  # noqa: E402


class _Mail:
    def __init__(self, subject, body, sender, hours_ago=1):
        self.Subject, self.Body, self.SenderEmailAddress, self.SenderName = subject, body, sender, sender
        self.ReceivedTime = datetime.now() - timedelta(hours=hours_ago)


class _Items(list):
    def Restrict(self, flt):
        return _Items(self)

    def Sort(self, field, desc):
        self[:] = sorted(self, key=lambda m: m.ReceivedTime, reverse=bool(desc))


class _Folder:
    def __init__(self, name, mails):
        self.Name, self._mails = name, mails

    @property
    def Items(self):
        return _Items(self._mails)


def test_turning_a_job_down_or_naming_another_manifest_is_not_a_booking():
    assert S.declined("Delali, we already have our pts driver on man 01575454 Kind regards Scott")
    assert S.declined("Unfortunately we can't cover this one") and S.declined("That driver is on another job")
    assert not S.declined("it's for this current run: 260804-man-01567080")
    assert not S.declined("Booked on MAN-01575999 for Friday, thanks")


def test_only_a_manifest_that_books_this_job_takes_it_off_the_map():
    keep = S._folders
    inbox = _Folder("Inbox", [
        _Mail("RE: AH9/11/26EXAM Delivery", "Delali, we already have our pts driver on man 01575454\nFrom: us",
              "traffic@haulier.example"),
        _Mail("RE: AH8/11/26EXAM Delivery", "it's for this current run: 260804-man-01567080\nFrom: us",
              "ops@haulier.example")])
    sent = _Folder("Sent Items", [
        _Mail("RE: AH6/11/26EXAM Delivery", "Sorry for the wait - booked on MAN-01575111\nFrom: them",
              "planner@example.com")])
    try:
        S._folders = lambda ns: [inbox, sent]
        got = S.find_bookings(None, ["AH9/11/26EXAM", "AH8/11/26EXAM", "AH6/11/26EXAM"])
        assert "AH9/11/26EXAM" not in got                                  # busy on another manifest: stays
        assert got["AH8/11/26EXAM"]["man"] == "MAN-01567080"               # the haulier confirming this run
        assert got["AH6/11/26EXAM"]["man"] == "MAN-01575111"               # our own word always counts
    finally:
        S._folders = keep


def test_one_mail_about_two_jobs_books_only_the_one_its_manifest_is_for():
    """His 24/11: our reply on a cover request for two jobs gave the first job's manifest, and the sweep took BOTH off the
    map. The manifest now books the job its own words name, else the one Book's journal has on it - never both."""
    keep_f, keep_j = S._folders, S.journal_lines
    both = _Folder("Sent Items", [_Mail("RE: Cover request Thu - 9100001 Here to There + 9100002 There to Here",
                                        "Thanks for covering this. Here's the manifest number: MAN-01900001\nFrom: them",
                                        "planner@example.com")])
    try:
        S._folders = lambda ns: [both]
        S.journal_lines = lambda man: []                       # not Book's: nothing comes off on its say-so
        assert S.find_bookings(None, ["9100001", "9100002"]) == {}
        S.journal_lines = lambda man: ["9100001"] if man == "MAN-01900001" else []
        got = S.find_bookings(None, ["9100001", "9100002"])
        assert set(got) == {"9100001"} and got["9100001"]["man"] == "MAN-01900001", got
        said = _Folder("Sent Items", [_Mail("RE: Cover request - 9100001 + 9100002",
                                            "9100002 is booked on MAN-01900002\nFrom: them", "planner@example.com")])
        S._folders = lambda ns: [said]
        assert set(S.find_bookings(None, ["9100001", "9100002"])) == {"9100002"}     # the one its own words name
    finally:
        S._folders, S.journal_lines = keep_f, keep_j


def test_the_journal_says_which_lines_a_manifest_carries(tmp_path):
    import json
    path = tmp_path / "journal.json"
    path.write_text(json.dumps({"jobs": {"9100001@26/11/2026": {"trips": [
        {"manifest": "MAN-01900001", "lines": ["9100001", "9100001_R"]}]}}}), encoding="utf-8")
    assert S.journal_lines("MAN-01900001", path=str(path)) == ["9100001", "9100001_R"]
    assert S.journal_lines("MAN-01900009", path=str(path)) == []


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
