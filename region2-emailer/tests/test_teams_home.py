"""teams_home: what Teams' UI Automation names say - the chat list, the open chat's messages - and the guards on a send.
Names here are made up; the shapes are the ones the home PC's Teams gave on 26/11."""
import pytest

import teams_home as H

TEXT, GROUP = H.TEXT, H.GROUP


# ---------- the chat list

@pytest.mark.parametrize("name, want", [
    ("Chat Pat Jones (Example Ltd) Away",
     {"title": "Pat Jones (Example Ltd)", "kind": "Chat", "unread": False, "status": "Away", "flags": []}),
    ("Unread message Group chat Example Ops - Planning Has external participants",
     {"title": "Example Ops - Planning", "kind": "Group chat", "unread": True, "status": "",
      "flags": ["Has external participants"]}),
    ("Group chat Team Room", {"title": "Team Room", "kind": "Group chat", "unread": False, "status": "", "flags": []}),
    ("Unread message Chat Sam Lee (Example Ltd) Offline",
     {"title": "Sam Lee (Example Ltd)", "kind": "Chat", "unread": True, "status": "Offline", "flags": []}),
    ("Meeting chat Weekly Catch Up",
     {"title": "Weekly Catch Up", "kind": "Meeting chat", "unread": False, "status": "", "flags": []}),
    ("Chat Kim Park (Example Ltd) Has pinned messages Away",
     {"title": "Kim Park (Example Ltd)", "kind": "Chat", "unread": False, "status": "Away",
      "flags": ["Has pinned messages"]}),
    ("Chat Me Myself (Example Ltd) (You)",
     {"title": "Me Myself (Example Ltd)", "kind": "Chat", "unread": False, "status": "(You)", "flags": []}),
    ("Chat Ann Out (Example Ltd) Out of office",
     {"title": "Ann Out (Example Ltd)", "kind": "Chat", "unread": False, "status": "Out of office", "flags": []}),
])
def test_parse_chat(name, want):
    assert H.parse_chat(name) == want


@pytest.mark.parametrize("name", ["Mentions", "Drafts", "See more", "Chats", "Teams and channels Unread Team Users",
                                  "Community All Company", "Chat"])
def test_parse_chat_leaves_out_what_isnt_a_chat(name):
    assert H.parse_chat(name) is None


CHATS = [H.parse_chat(n) for n in ("Chat Pat Jones (Example Ltd) Away", "Chat Pat Smith (Example Ltd) Away",
                                   "Group chat Example Ops - Planning", "Chat Sam Lee (Example Ltd) Offline")]


def test_pick_chat_whole_title_then_start_then_contains():
    assert H.pick_chat(CHATS, "sam lee (example ltd)")["title"] == "Sam Lee (Example Ltd)"
    assert H.pick_chat(CHATS, "Example Ops")["title"] == "Example Ops - Planning"
    assert H.pick_chat(CHATS, "jones")["title"] == "Pat Jones (Example Ltd)"


def test_pick_chat_two_matches_asks_which():
    with pytest.raises(H.Stop, match="2 chats match"):
        H.pick_chat(CHATS, "pat")


def test_pick_chat_none_names_the_list():
    with pytest.raises(H.Stop, match="No chat"):
        H.pick_chat(CHATS, "nobody here")


# ---------- an open chat's messages

def _message(text, who, when="Today at 09:15.", reacts=""):
    """The four elements Teams gives one message: its short text, the sender, the time, and the message group."""
    short = text if len(text) < 40 else text[:40] + "..."
    return [(TEXT, f"{short} by {who}"), (TEXT, who), (TEXT, when),
            (GROUP, f"{text} {who}" + (f" {reacts}" if reacts else "") + f" {when}")]


PAT, ME = "Pat Jones (Example Ltd)", "Me Myself (Example Ltd)"


def test_parse_messages_reads_sender_time_and_whole_text():
    items = (_message("we can do Tue 08/12 for you", PAT, "Today at 16:18.")
             + _message("thanks, that's great", ME, "Today at 16:20.", "1 Like reaction."))
    got = H.parse_messages(items, ME)
    assert got == [
        {"sender": PAT, "when": "Today at 16:18", "text": "we can do Tue 08/12 for you", "reactions": ""},
        {"sender": ME, "when": "Today at 16:20", "text": "thanks, that's great", "reactions": "1 Like reaction"},
    ]


def test_parse_messages_a_long_message_keeps_all_its_text():
    long = "Order 1234567, 13 rails (10 x 18.288m, 3 x 13.716m), deliver any time before 15:00. Would you be able?"
    got = H.parse_messages(_message(long, PAT), ME)
    assert got[0]["text"] == long


def test_parse_messages_drops_his_own_newest_receipt_only():
    items = _message("Sent hello there", ME) + _message("Sent the rails over yesterday", PAT)
    got = H.parse_messages(items, ME)
    assert got[0]["text"] == "hello there"                       # his: Teams' "Sent" before the newest
    assert got[1]["text"] == "Sent the rails over yesterday"      # someone else's words are left alone


def test_parse_messages_text_saying_by_doesnt_make_a_sender():
    items = _message("delivered by Monday please", PAT)
    got = H.parse_messages(items, ME)
    assert [m["sender"] for m in got] == [PAT]
    assert got[0]["text"] == "delivered by Monday please"


def test_parse_messages_leaves_out_a_deleted_message_and_other_groups():
    items = ([(TEXT, f"This message has been deleted. by {ME}"), (GROUP, "This message has been deleted.")]
             + [(GROUP, "Message List"), (TEXT, "Last read")]
             + _message("still on for tomorrow?", PAT, "Yesterday at 17:09."))
    got = H.parse_messages(items, ME)
    assert got == [{"sender": PAT, "when": "Yesterday at 17:09", "text": "still on for tomorrow?", "reactions": ""}]


def test_parse_messages_with_a_date_for_a_time():
    got = H.parse_messages(_message("older one", PAT, "23/11/2026 18:53."), ME)
    assert got[0]["when"] == "23/11/2026 18:53"


def test_senders_must_also_stand_alone():
    items = [(TEXT, "this is going by road"), (TEXT, "x by Pat Jones (Example Ltd)"), (TEXT, PAT)]
    assert H.senders_in(items) == [PAT]


# ---------- guards on a send

def test_check_text_refuses_dashes_blank_and_a_book():
    assert H.check_text("  plain text, fine. ") == "plain text, fine."
    for bad in ("", "   ", "an em — dash", "an en – dash", "x" * 4001):
        with pytest.raises(H.Stop):
            H.check_text(bad)


@pytest.mark.parametrize("window, chat, want", [
    ("Chat | Pat Jones (Example Ltd) | Microsoft Teams", "Pat Jones (Example Ltd)", True),
    ("Chat | Me Myself (Example Ltd) (You) | Microsoft Teams", "Me Myself (Example Ltd)", True),
    ("Chat | Pat Jones (Example Ltd) | Microsoft Teams", "Pat Jo", False),
    ("Chat | Pat Smith (Example Ltd) | Microsoft Teams", "Pat Jones (Example Ltd)", False),
    ("Microsoft Teams", "Pat Jones (Example Ltd)", False),
])
def test_title_is(window, chat, want):
    assert H.title_is(window, chat) is want


def test_person_of_drops_the_company():
    assert H.person_of("Pat Jones (Example Ltd)") == "Pat Jones"
    assert H.person_of("Example Ops - Planning") == "Example Ops - Planning"


def test_email_for_tries_the_title_then_the_bare_name():
    asked = []

    def resolve(name):
        asked.append(name)
        return "pat.jones@example.com" if name == "Pat Jones" else ""
    assert H.email_for("Pat Jones (Example Ltd)", resolve) == "pat.jones@example.com"
    assert asked == ["Pat Jones (Example Ltd)", "Pat Jones"]
    assert H.email_for("Nobody (Example Ltd)", lambda n: "") == ""


def test_send_refuses_a_group_chat_before_anything_is_opened(monkeypatch):
    monkeypatch.setattr(H, "main_window", lambda: (1, "Chat | x | Microsoft Teams"))

    class FakeUia:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(H, "_Uia", FakeUia)
    monkeypatch.setattr(H, "_chat_entries", lambda s, h: [(None, c) for c in CHATS])
    monkeypatch.setattr(H, "_teams", lambda: (None, type("T", (), {"Stop": Exception})))
    with pytest.raises(H.Stop, match="group chat"):
        H.send("example ops", "hello", dry=True)


def test_send_refuses_a_dash_before_teams_is_touched(monkeypatch):
    monkeypatch.setattr(H, "main_window", lambda: pytest.fail("Teams was looked at"))
    monkeypatch.setattr(H, "_teams", lambda: (None, None))
    with pytest.raises(H.Stop, match="dash"):
        H.send("pat", "a — b", dry=True)
