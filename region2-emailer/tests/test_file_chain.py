"""Filing an order's email chain once its CTMS update is done: only the site thread's mails in the Inbox's top level,
only with the order number in the subject, into Region 2 > Completed - never another order's mail, never a
sub-folder's. A made-up mailbox only.

    python tests/test_file_chain.py
"""
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import file_chain as F  # noqa: E402


class Mail:
    def __init__(self, subject, conv="", sender="Sam Example", days_ago=1):
        self.Subject, self.ConversationID, self.SenderName = subject, conv, sender
        self.ConversationTopic = F.topic(subject)
        self.ReceivedTime = datetime.now() - timedelta(days=days_ago)
        self.moved_to = None

    def Move(self, dest):
        self.moved_to = dest.Name
        return self


class Items(list):
    def Sort(self, key, desc):
        self.sort(key=lambda m: m.ReceivedTime, reverse=desc)


class Folder:
    def __init__(self, name, mails=(), subs=()):
        self.Name, self.Items, self.subs = name, Items(mails), list(subs)

    @property
    def Folders(self):
        subs = self.subs

        class _F:
            Count = len(subs)

            def Item(self, i):
                return subs[i - 1]
        return _F()


class NS:
    def __init__(self, first=None):
        self.first = first

    def GetItemFromID(self, eid):
        if self.first is None:
            raise LookupError(eid)
        return self.first


def _mailbox(inbox_mails, completed=None, region2=()):
    completed = completed or Folder("Completed")
    tree = Folder("root", subs=[Folder("Inbox", inbox_mails, subs=[
        Folder("Regions", subs=[Folder("Region 2", region2, subs=[completed])])])])
    return tree, completed


def test_the_site_thread_is_filed_whoever_replied_and_nothing_else_is():
    first = Mail("9100090 Walsall - Example Yard WS10 0AA", conv="C1")
    thread = [Mail("RE: 9100090 Walsall - Example Yard WS10 0AA", conv="C1", sender="Sam Example"),
              Mail("Re: 9100090 Walsall - Example Yard WS10 0AA", conv="C1", sender="A Colleague"),
              Mail("RE: RE: 9100090 Walsall - Example Yard WS10 0AA", conv="C1", days_ago=3)]
    others = [Mail("RE: 9100091 Somewhere - Another Site", conv="C2"),               # another order
              Mail("RE: 9100090 haulier quote", conv="C3", sender="Example Haulage"),  # the order, not the thread
              Mail("RE: 9100090 Walsall - Example Yard WS10 0AA", conv="C1", days_ago=90)]   # too old to look at
    root, completed = _mailbox(thread + others)
    done = F.file_chain(NS(first), {"orders": ["9100090"], "orig_entryid": "E1"}, root=root)
    assert len(done) == 3 and all(m.moved_to == "Completed" for m in thread)
    assert all(m.moved_to is None for m in others)


def test_without_the_first_email_our_own_subject_decides():
    mine = Mail("RE: 9100092 Lowestoft - Example Station NR32 2AA", conv="X")
    other = Mail("FW: Cancellation 9100092", conv="Y")                  # names the order, not our subject
    root, _ = _mailbox([mine, other])
    done = F.file_chain(NS(None), {"orders": ["9100092"], "orig_entryid": "gone"}, root=root)
    assert [d[2] for d in done] == ["RE: 9100092 Lowestoft - Example Station NR32 2AA"]
    assert other.moved_to is None


def test_a_dry_run_moves_nothing_and_a_missing_folder_moves_nothing():
    m = Mail("RE: 9100093 Example - Site", conv="C9")
    root, _ = _mailbox([m])
    assert len(F.file_chain(NS(None), {"orders": ["9100093"]}, root=root, move=False)) == 1
    assert m.moved_to is None
    bare = Folder("root", subs=[Folder("Inbox", [m])])
    try:
        F.file_chain(NS(None), {"orders": ["9100093"]}, root=bare)
        assert False, "should have refused"
    except RuntimeError as e:
        assert "nothing filed" in str(e)
    assert m.moved_to is None


def test_mail_in_a_sub_folder_is_never_touched():
    in_region2 = Mail("RE: 9100094 Example - Site", conv="C4")
    root, _ = _mailbox([], region2=[in_region2])
    assert F.file_chain(NS(None), {"orders": ["9100094"]}, root=root) == [] and in_region2.moved_to is None


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
