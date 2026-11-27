"""
Teams on the home PC. His ask 26/11: "set up some code so where you can regularly have access to Teams, because we're
going to be integrating some things in there as well." His DHL account is signed in to the new Teams desktop app here
(ms-teams.exe) since 26/11, and Teams answers Windows' UI Automation - the screen-reader layer - once it has been asked
(the first look switches its page's accessibility on, the second sees everything):

  the chat list   a tree of entries: "Unread message Chat Pat Jones (Example Ltd) Away", "Group chat Some Team",
                  "Meeting chat Weekly Catch Up" - who, what kind, unread or not, nothing of the messages
  an open chat    a group "Message List" whose messages are groups named "<text> <sender> [N Like reaction.] Today at
                  HH:MM." with, beside each, texts "<start of the text...> by <sender>", "<sender>" and "Today at HH:MM."

The work PC's helpers do the talking (work_pc/ctms_tabs, ctms_window, ctms_teams, ctms_act: standard library only), so
nothing new is installed and sending is the work PC's proven way.

Reading never types or clicks. `chats` and `unread` only read the list - nothing is opened, so nothing is marked read.
`read` opens the chat it is given by selecting its entry in Teams' own list (no mouse) - Teams then marks that chat
read. `send` opens the chat the same way, brings Teams in front for a few seconds, and then does what the work PC's
Send in Teams does: the box must be empty (a draft of his there = nothing sent), one paste with the clipboard put back,
read back exactly, Teams' own Send button pressed (never Enter), the box empty after, the window that was in front put
back. Without --send it does all of that but Send, and empties the box again. Every message to anyone is his OK first;
dashes never go in a message (his rule for NOC), so a text with one is refused.

    python teams_home.py chats [--unread] [--json]
    python teams_home.py unread [--json]                    the chats with unread messages - opens nothing
    python teams_home.py read "<chat>" [--n 15] [--json]    opens that chat (Teams marks it read) and reads it
    python teams_home.py send "<chat>" "<text>" [--send]    dry unless --send

<chat> is the chat's name as the list shows it, or enough of it to pick one ("pat", "planning"); two matches = asked
to say which.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK_PC = os.path.join(HERE, "work_pc")
if WORK_PC not in sys.path:
    sys.path.insert(0, WORK_PC)

TREE_ITEM, GROUP, TEXT = 50024, 50026, 50020
UNREAD = "Unread message "
KINDS = ("Group chat", "Meeting chat", "Chat")          # longest first: "Group chat X" is not a "Chat"
STATUSES = ("Available", "Away", "Busy", "Do not disturb", "Offline", "Out of office", "Be right back", "Appear away",
            "Appear offline", "In a meeting", "In a call", "Presenting", "Focusing", "Off work", "(You)")
FLAGS = ("Has external participants", "Has pinned messages", "Has context menu", "Has draft", "Muted", "Pinned",
         "Personal at mention")
DAYS = r"(?:Today|Yesterday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
WHEN = re.compile(r"^" + DAYS + r"(?: at)? \d{1,2}:\d{2}\.?$")
DASHES = ("—", "–")                           # em and en dash: never in a message (his rule for NOC)
WALK_CAP = 15000                                        # UI Automation elements looked at, at most, per walk
OPEN_SECONDS = 12


class Stop(Exception):
    pass


# ---------- what the names say (no Windows needed: these are what the tests check)

def _squash(s):
    return " ".join(str(s or "").split())


def parse_chat(name):
    """A chat-list entry's name -> {"title", "kind", "unread", "status", "flags"}; None for anything that isn't a chat
    ("Mentions", "Drafts", "See more", a team or a channel)."""
    n = _squash(name)
    unread = n.startswith(UNREAD)
    if unread:
        n = n[len(UNREAD):]
    kind = next((k for k in KINDS if n.startswith(k + " ")), None)
    if not kind:
        return None
    rest, status, flags = n[len(kind) + 1:], "", []
    changed = True
    while changed:                                       # the status and flags sit at the end, in any order
        changed = False
        for word in STATUSES + FLAGS:
            if rest.endswith(" " + word) or rest == word:
                rest = rest[: -len(word)].rstrip()
                if word in STATUSES and not status:
                    status = word
                elif word in FLAGS:
                    flags.insert(0, word)
                changed = True
    if not rest:
        return None
    return {"title": rest, "kind": kind, "unread": unread, "status": status, "flags": flags}


def pick_chat(chats, want):
    """The one chat `want` names: its whole title (any case), else the one title starting with it, else the one
    containing it. -> the chat, or Stop naming the choices."""
    w = _squash(want).lower()
    if not w:
        raise Stop("Which chat?")
    for test in (lambda t: t == w, lambda t: t.startswith(w), lambda t: w in t):
        hits = [c for c in chats if test(c["title"].lower())]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise Stop(f"{len(hits)} chats match {want!r}: " + "; ".join(c["title"] for c in hits[:8]) + " - say which.")
    raise Stop(f"No chat in Teams' list matches {want!r} (the list has {len(chats)}: "
               + "; ".join(c["title"] for c in chats[:12]) + ").")


def senders_in(items):
    """The people the message list names: each message has a text "<start...> by <sender>" and a text "<sender>"."""
    texts = [_squash(n) for k, n in items if k == TEXT and n]
    alone = set(texts)
    out = set()
    for t in texts:
        if " by " in t:
            who = t.rpartition(" by ")[2].strip()
            if who in alone:                              # seen on its own too: a sender, not a message saying "by"
                out.add(who)
    return sorted(out, key=len, reverse=True)


RECEIPTS = ("Sent", "Seen", "Delivered", "Sending")    # Teams puts its delivery status before his own newest message


def parse_messages(items, me=""):
    """The open chat's messages, oldest first -> [{"sender", "when", "text", "reactions"}], out of its UI Automation
    elements (control type, name) under "Message List". A message group is named "<text> <sender> [N Like reaction.]
    Today at HH:MM." - its sender is one the list names, so text and sender part where that name ends. A deleted
    message, a date line or anything else that names nobody is left out. His own messages (`me`) lose the "Sent " /
    "Seen " Teams puts in front of the newest one."""
    senders = senders_in(items)
    out = []
    for kind, name in items:
        if kind != GROUP or not name:
            continue
        n = _squash(name)
        for who in senders:
            m = re.search(re.escape(" " + who) + r"(?: (?P<r>\d+ [^.]*? reactions?\.))? (?P<when>" + DAYS
                          + r"(?: at)? \d{1,2}:\d{2})\.?$", n)
            if m and m.start() > 0:
                text = n[:m.start()].strip()
                if me and who == me:
                    first, _, rest = text.partition(" ")
                    if first in RECEIPTS and rest:
                        text = rest
                out.append({"sender": who, "when": m.group("when"), "text": text,
                            "reactions": (m.group("r") or "").rstrip(".")})
                break
    return out


def check_text(text):
    """A message we may send: some text, not a book, no dashes. -> the text, stripped; Stop otherwise."""
    t = str(text or "").strip()
    if not t:
        raise Stop("No text to send.")
    if len(t) > 4000:
        raise Stop("Far too long for a chat message.")
    if any(d in t for d in DASHES):
        raise Stop("The text has a dash in it - plain punctuation only (his rule): nothing sent.")
    return t


def title_is(window_title, chat_title):
    """Is Teams' window showing that chat? "Chat | <title> | Microsoft Teams" - his own chat adds "(You)" after the
    name, so the middle part is the title or starts with it and a space."""
    parts = [p.strip().lower() for p in _squash(window_title).split(" | ")]
    want = _squash(chat_title).lower()
    return len(parts) >= 3 and (parts[1] == want or parts[1].startswith(want + " "))


# ---------- Teams itself (Windows only)

def _teams():
    import ctms_tabs
    import ctms_teams
    return ctms_tabs, ctms_teams


def main_window():
    """Teams' main window here -> (hwnd, title); Stop when Teams isn't up."""
    _, ctms_teams = _teams()
    wins = ctms_teams.windows()
    if not wins:
        raise Stop("Teams isn't open on this PC (no Teams window) - open the Teams app, signed in to DHL.")
    return wins[0]


class _Uia:
    """UI Automation for one job on this thread, released at the end."""

    def __enter__(self):
        ctms_tabs, _ = _teams()
        self.ole = ctms_tabs.ole32
        self.hr = self.ole.CoInitializeEx(None, 0)
        self.s = ctms_tabs._Session()
        return self.s

    def __exit__(self, *exc):
        try:
            self.s.close()
        finally:
            if self.hr >= 0:
                self.ole.CoUninitialize()
        return False


def _walk(s, root, keep, cap=WALK_CAP):
    """Breadth first from root -> [(element, control type, name)] of what `keep(type, name)` wants, in that order."""
    out, seen, level = [], 0, [root]
    while level and seen < cap:
        deeper = []
        for el in level:
            for ch in s.children(el):
                seen += 1
                kind = s.control_type(ch)
                nm = s.name(ch) or ""
                if keep(kind, nm):
                    out.append((ch, kind, nm))
                deeper.append(ch)
                if seen >= cap:
                    break
        level = deeper
    return out


def _chat_entries(s, hwnd):
    """[(element, chat)] for each chat in the list, top first."""
    found = _walk(s, s.element(hwnd), lambda k, n: k == TREE_ITEM and bool(n))
    out = []
    for el, _, nm in found:
        c = parse_chat(nm)
        if c:
            out.append((el, c))
    return out


def chats():
    """Every chat in Teams' list -> [chat]. Reads only."""
    hwnd, _ = main_window()
    with _Uia() as s:
        got = _chat_entries(s, hwnd)
        if not got:                                      # the first look switches Teams' accessibility on
            time.sleep(1.0)
            got = _chat_entries(s, hwnd)
    return [c for _, c in got]


def unread():
    return [c for c in chats() if c["unread"]]


def _open(s, hwnd, want):
    """Select the chat `want` names in Teams' list and wait for Teams to show it -> (the chat, his own name)."""
    entries = _chat_entries(s, hwnd)
    if not entries:                                      # the first look switches Teams' accessibility on
        time.sleep(1.0)
        entries = _chat_entries(s, hwnd)
    me = next((c["title"] for _, c in entries if c["status"] == "(You)"), "")
    chat = pick_chat([c for _, c in entries], want)
    el = next(e for e, c in entries if c is chat)
    import ctms_window
    if not title_is(ctms_window._text(hwnd), chat["title"]):
        if not s.select(el):
            raise Stop(f"Teams' list wouldn't open the chat {chat['title']!r} - nothing done.")
        end = time.time() + OPEN_SECONDS
        while time.time() < end and not title_is(ctms_window._text(hwnd), chat["title"]):
            time.sleep(0.4)
        if not title_is(ctms_window._text(hwnd), chat["title"]):
            raise Stop(f"Teams didn't show the chat {chat['title']!r} in time (its window reads "
                       f"{ctms_window._text(hwnd)!r}) - nothing done.")
    return chat, me


def _message_items(s, hwnd):
    """(control type, name) of everything under the open chat's "Message List", breadth first."""
    lists = _walk(s, s.element(hwnd), lambda k, n: k == GROUP and n == "Message List", cap=WALK_CAP)
    if not lists:
        return []
    return [(k, n) for _, k, n in _walk(s, lists[0][0], lambda k, n: k in (TEXT, GROUP) and bool(n))]


def read(want, n=15):
    """The last `n` messages of that chat -> (chat, [message]). Opens it: Teams marks it read."""
    hwnd, _ = main_window()
    with _Uia() as s:
        chat, me = _open(s, hwnd, want)
        msgs = []
        for _ in range(4):                               # Teams draws the messages for UI Automation on asking
            msgs = parse_messages(_message_items(s, hwnd), me)
            if msgs:
                break
            time.sleep(1.0)
    return chat, msgs[-n:] if n else msgs


def locked():
    """Is this PC's screen locked? Windows' lock screen then has the keyboard, so a paste into Teams goes nowhere - though
    Teams can still be read (27/11: a send from home while he was at work). True when the desktop can't be switched to."""
    import ctypes
    u = ctypes.windll.user32
    h = u.OpenInputDesktop(0, False, 0x0100)              # DESKTOP_SWITCHDESKTOP
    if not h:
        return True
    try:
        return not u.SwitchDesktop(h)
    finally:
        u.CloseDesktop(h)


def person_of(title):
    """"Pat Jones (Example Ltd)" -> "Pat Jones": the name a one-to-one chat is titled with, its company dropped."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", _squash(title)).strip()


def email_for(title, resolve=None):
    """The address of the person a one-to-one chat is with, from his Outlook address book (DHL's directory) - the
    chat's own title first, then the bare name. "" when it doesn't resolve to exactly one person."""
    resolve = resolve or _outlook_resolve
    for name in dict.fromkeys((_squash(title), person_of(title))):
        if name:
            got = resolve(name)
            if got:
                return got
    return ""


def _outlook_resolve(name):
    try:
        import build_drafts as bd
        r = bd.get_ns().CreateRecipient(name)
        if not r.Resolve():
            return ""
        u = r.AddressEntry.GetExchangeUser()
        return str((u.PrimarySmtpAddress if u is not None else "") or "").strip().lower()
    except Exception:
        return ""


def send(want, text, dry=True):
    """Text to that chat -> {"ok", "said"}. Dry: everything but Send, the box emptied again.

    The chat is opened by Teams' own link for the person (msteams:/l/chat/0/0?users=<address>), which hands the
    message box the keyboard: opened from the list instead, Teams keeps the keyboard on the list and a paste goes
    nowhere (26/11, his own chat, tried with a click in the box too). So it is one-to-one chats only - their address
    out of his Outlook address book - and then exactly the work PC's Send in Teams (ctms_teams.send)."""
    _, ctms_teams = _teams()
    text = check_text(text)
    hwnd, _ = main_window()
    if locked():
        raise Stop("This PC is locked, so nothing can be typed into Teams until it's unlocked (reading still works) - "
                   "nothing sent.")
    with _Uia() as s:
        entries = _chat_entries(s, hwnd)
        if not entries:                                  # the first look switches Teams' accessibility on
            time.sleep(1.0)
            entries = _chat_entries(s, hwnd)
        chat = pick_chat([c for _, c in entries], want)
        if chat["kind"] != "Chat":
            raise Stop(f"{chat['title']!r} is a {chat['kind'].lower()} - sending to a group or meeting chat isn't built "
                       "yet (reading it is): nothing sent.")
        me = next((c["title"] for _, c in entries if c["status"] == "(You)"), "")
    email = email_for(chat["title"])
    if not email:
        raise Stop(f"{chat['title']!r} isn't in the Outlook address book as one person, so Teams' link for the chat "
                   "can't be made: nothing sent.")
    import ctms_window
    ctms_window.dpi_aware()
    if me and me != chat["title"]:
        # Teams' link must MOVE to the chat for the box to get the keyboard: a chat already showing, or one reached
        # after anything was selected in the list, swallows the paste (27/11, twice). His own chat by its link first -
        # opening it marks nothing read - then the person's link moves Teams to theirs.
        mine = email_for(me)
        if mine:
            os.startfile(ctms_teams.chat_link(mine))
            end = time.time() + OPEN_SECONDS
            while time.time() < end and not title_is(ctms_window._text(hwnd), me):
                time.sleep(0.3)
            time.sleep(1.0)
    for attempt in (1, 2):
        try:
            out = ctms_teams.send(email, person_of(chat["title"]), text, dry=dry)
            break
        except ctms_teams.Stop as e:
            # left idle, this PC puts Windows' lock screen over the desktop: the first keys only dismiss it, so the first
            # paste lands nowhere (27/11, three times; the next try went straight through). The box was read back empty,
            # so nothing went - one more try, and then it stops.
            if attempt == 2 or not str(e).startswith("The paste left the message box"):
                raise Stop(str(e))
            time.sleep(1.5)
    out.pop("payload", None)                             # the work PC's picture of the chat: not wanted here
    return out


# ---------- command line

def _show_chat(c):
    return (("* " if c["unread"] else "  ") + c["title"] + f"  [{c['kind']}"
            + (f", {c['status']}" if c["status"] else "") + "]")


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = list(argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if not args:
        print(__doc__)
        return 2
    cmd = args[0]
    try:
        if cmd in ("chats", "unread"):
            got = unread() if (cmd == "unread" or "--unread" in args) else chats()
            if as_json:
                print(json.dumps(got, indent=1))
            else:
                print(f"{len(got)} chat(s)" + (" with unread messages" if cmd == "unread" or "--unread" in args else "")
                      + " (* = unread):")
                for c in got:
                    print(_show_chat(c))
            return 0
        if cmd == "read" and len(args) >= 2:
            n = 15
            if "--n" in args:
                n = int(args[args.index("--n") + 1])
            chat, msgs = read(args[1], n)
            if as_json:
                print(json.dumps({"chat": chat, "messages": msgs}, indent=1))
            else:
                print(f"{chat['title']} - last {len(msgs)} message(s):")
                for m in msgs:
                    print(f"  [{m['when']}] {m['sender']}: {m['text']}" + (f"  ({m['reactions']})" if m["reactions"] else ""))
            return 0
        if cmd == "send" and len(args) >= 3:
            out = send(args[1], args[2], dry="--send" not in args)
            print(out["said"])
            return 0 if out.get("ok") else 1
    except Stop as e:
        print(f"STOPPED: {e}")
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
