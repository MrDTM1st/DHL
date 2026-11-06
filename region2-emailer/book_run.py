"""
The order panel's Book, the home PC's part (his design 02/11: "book with who?", the price if it's a tier 2, "and then you
just book it in"). Every click in CTMS happens on the WORK PC (work_pc/ctms_book.py, one command to its bridge). What
follows from here:

  1. first: anything on the CTMS to-do that has to go on before the booking stops it - "if you do it after we book it,
     we'd have to then unbook it and then put it back on"
  2. the booking itself, on the work PC
  3. a *_DH carrier's row on the DigiHaul Job Tracker: next empty row, yellow cells only (his 02/11: "if the haulier is with
     DH, the manifest number and stuff has to go on that Excel sheet"), each row looked at first - a colleague's can be
     half typed, with the manifest still empty
  4. the site's email: the manifest and the delivery's start and end times (his rule, every booking) - Reply All on the
     order's site thread, an ad hoc's request forwarded so its sheet stays attached, never a price. Nothing to the other
     hauliers or NOC: "We just let the delivery site know. The hauliers already know." Parcel Pass is the one that hears:
     the manifest and the job on its own quote's thread, and no asking for an ETA (his 03/11)
  5. the order off the map, its chain filed

A stop at any point says what was done so far. Past the booking nothing undoes it: what couldn't be done is said, for him
to do by hand.

    python book_run.py run '{"record": "...", "orders": ["..."], "date": "dd/mm/yyyy", "carrier": "...", "trailer": "...",
                             "haulier": "...", "haulage": 450, "vehicles": 1, "dry": false}'
    python book_run.py batch '[{job}, ...]' [--run N]   Book approved: each in turn, stopping where CTMS needs a look
    python book_run.py retry             the timer: lost answers looked for, Outlook's failed steps tried again
    python book_run.py clear KEY [STEP]  his Done by hand / Clear

Every press goes through the booking journal (book_journal.py) first: an order it has booked is never booked again - a
press finishes what is left instead - and an answer the home PC gave up waiting for is asked for again by its id.

Prints what it does and, last, one line of JSON for the agent: {"ok", "said", "trips", "seconds", ...}.
"""
import contextlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1f1f1f;"
PLANNER = "Delali"
NOC = "DHL_NOC"
BLOCKS = ("update", "booking")     # what has to go on before a booking; a note can follow it

# The DigiHaul tracker as the work PC shows it, on the picture (1910 x 915, 02/11): the highlighted row number and column
# heading say where the cursor is; the yellow columns are read by where they sit.
GUTTER_X = 8
ROW_TOP, ROW_END = 358, 832
PICKED = (202, 234, 216)           # a highlighted heading
HEAD_Y, HEAD_A, HEAD_B, HEAD_C = 295, 100, 150, 360
CELL_B = (140, 320)
CELLS = {"C": (332, 544), "D": (556, 669), "E": (682, 835), "F": (848, 1595), "G": (1608, 1890)}
SCROLLBAR, SHEET_FOOT = 20, 83     # what the page keeps on its right and under the rows, whatever the window's size (03-04/11)
INTO_GRID = [230, 390]             # a cell of the sheet, whichever row it is: the sheet can be left scrolled sideways
PASS_CARRIER = "PASS_DH"
PASS_DOMAIN = "passlogistics"


class Stop(RuntimeError):
    """Not as expected: the words are what he is told."""


def _client():
    import ctms_remote as R
    R.OUT = os.path.join(HERE, "ctms_remote")
    R.STATE = os.path.join(R.OUT, "state.json")
    R.BASE, R.KEY = R._desk()
    return R


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **k)


# -- what the order is
def record_of(ident):
    """The panel's record, wherever it lives: {} when it has gone."""
    try:
        import tracker
        got = next((r for r in tracker.load().get("records", []) if r.get("id") == ident), None)
        if got:
            return got
    except Exception:
        pass
    try:
        with open(os.path.join(HERE, "_adhocs.json"), encoding="utf-8") as f:
            got = next((r for r in json.load(f) if r.get("id") == ident), None)
        if got:
            return got
    except Exception:
        pass
    try:
        import pins
        return next((p for p in pins.load() if p.get("id") == ident), None) or {}
    except Exception:
        return {}


def owed_first(orders, listing=None):
    """What the CTMS to-do has for these orders that has to go on before the booking."""
    import ctms_todo
    items = ctms_todo.listing() if listing is None else listing
    want = set(ctms_todo._bases(orders))
    return [i for i in items if (i.get("kind") in BLOCKS or _services(i))
            and want & set(ctms_todo._bases(i.get("orders") or []))]


def _services(item):
    """A Night / Saturday / Sunday the order needs ("Add NIGHT before it's booked"): the desk's to put on before it
    books, not his (his 06/11) - the to-do's Run adds it, as it does an update."""
    return item.get("source") == "services"


def run_owed(items):
    """The CTMS to-do's items that have to go on before this booking, run the way the to-do's Run runs them (ctms_run):
    (all done, in words). Anything it can't type - a hand-written item, a doubt only he can settle - stays undone, and
    the booking with it."""
    import ctms_run
    runnable = [i for i in items if i.get("kind") == "update" or _services(i)]
    if len(runnable) < len(items):
        other = next(i for i in items if i not in runnable)
        return False, (f"{other['what']}: that's on the CTMS to-do and has to go on before the booking, and it isn't "
                       "something Book can type. Do it, or tick it off.")
    try:
        res = _quiet(ctms_run.run, [i["id"] for i in runnable])
    except Exception as e:
        return False, f"What the CTMS to-do has for these orders couldn't be run first ({e})."
    if not res.get("ok"):
        return False, f"What the CTMS to-do has for these orders has to go on first, and it didn't all go: {res.get('said')}."
    return True, f"What the CTMS to-do had for these orders went on first: {res.get('said')}."


_QTY = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*x\b", re.I)


def quantities(rec):
    """{order: quantity} where the desk knows the order's quantity for certain, for Book's line check (his 03/11: the
    quantity must be the order's). An ad hoc's form says it; a tracked order only when it is one order of one product
    ("27x sleepers") - several products or orders on one record can't be shared out to CTMS's lines without guessing."""
    orders = [str(o) for o in rec.get("orders") or []]
    if len(orders) != 1:
        return {}
    if rec.get("kind") in ("adhoc", "dts"):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", str(rec.get("qty") or ""))
        return {orders[0]: float(m.group(1))} if m else {}
    parts = [p for p in str(rec.get("materials") or "").split(",") if p.strip()]
    if len(parts) != 1 or len(rec.get("product_codes") or []) > 1:
        return {}
    m = _QTY.match(parts[0])
    return {orders[0]: float(m.group(1))} if m else {}


def is_urgent(collect, now):
    """The tracker's Urgent: "If Collecting Today/Tomorrow Morning". collect as the well shows it, dd/mm/yy HH:MM."""
    try:
        when = datetime.strptime(str(collect or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return False
    return when.date() <= now.date() or (when.date() == (now + timedelta(days=1)).date() and when.hour < 12)


# -- the DigiHaul row
def _near(c, want, tol=12):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(c, want))


def _on_picture(im, xs):
    """Those columns of pixels as far as the picture goes, short of the page's own scrollbar: the window can be any size."""
    return xs[0], min(xs[1], im.size[0] - SCROLLBAR)


def picked_row(im):
    """(top, bottom) of the row whose number is highlighted, or None."""
    ys = [y for y in range(ROW_TOP, max(ROW_END, im.size[1] - SHEET_FOOT)) if _near(im.getpixel((GUTTER_X, y)), PICKED)]
    return (ys[0], ys[-1]) if ys else None


def _dark(im, xs, ys):
    return sum(1 for y in range(*ys) for x in range(*xs) if sum(im.getpixel((x, y))[:3]) < 240)


def row_state(im):
    """Where the tracker's cursor is on a picture: None when it can't be told it is on one cell of column B; else
    {"blank": the row's yellow cells are empty, "above": the row above has a manifest}."""
    row = picked_row(im)
    if not row or not _near(im.getpixel((HEAD_B, HEAD_Y)), PICKED) or _near(im.getpixel((HEAD_C, HEAD_Y)), PICKED):
        return None
    if _near(im.getpixel((HEAD_A, HEAD_Y)), PICKED):
        return None                    # scrolled sideways: another column's wide heading is sitting where B's belongs
    top, bottom = row
    if bottom - top < 8 or im.size[0] - SCROLLBAR < CELLS["F"][1]:     # the yellow cells, up to G's edge, have to show
        return None
    band = (top + 4, bottom - 3)
    return {"blank": not any(_dark(im, _on_picture(im, xs), band) for xs in CELLS.values()) and not _dark(im, CELL_B, band),
            "above": bool(_dark(im, CELL_B, (top - 20, top - 4)))}


def row_filled(im):
    """Whether the row just pasted shows in every yellow cell that should have something (F, Notes, stays blank)."""
    row = picked_row(im)
    if not row:
        return False
    band = (row[0] + 4, row[1] - 3)
    shown = "CDEG" if im.size[0] - SCROLLBAR >= CELLS["G"][1] else "CDE"     # G's middle is off a narrower window
    return bool(_dark(im, CELL_B, band)) and all(_dark(im, CELLS[c], band) for c in shown)


def row_text(trip, carrier, now):
    """B manifest, C the carrier code, D the cost, E the planner, F left blank, G Urgent."""
    return "\t".join([trip["manifest"], carrier, str(trip.get("cost") or ""), PLANNER, "",
                      "Y" if is_urgent(trip.get("collect"), now) else "N"])


def tracker_rows(R, trips, carrier, now=None, look_only=False):
    """Each manifest on the DigiHaul tracker, a row at a time. Returns (rows written, why it stopped or "").
    look_only: gets to the row and says what it found there, nothing pasted."""
    from PIL import Image
    now = now or datetime.now()
    result, _ = _quiet(R.ask, "use", target="page")
    if not result.get("ok"):
        return 0, f"the tracker's tab wouldn't come up ({result.get('detail')})"
    done, why = 0, ""
    latest = os.path.join(R.OUT, "latest.png")
    try:
        for trip in trips:
            steps = [{"action": "click", "px": INTO_GRID}, {"action": "wait", "seconds": 0.5},
                     {"action": "key", "key": "home"}, {"action": "wait", "seconds": 0.5},     # column A, the sheet back in place
                     {"action": "key", "key": "right"}, {"action": "wait", "seconds": 0.5},    # column B
                     {"action": "key", "key": "ctrl+down"}, {"action": "wait", "seconds": 0.9},
                     {"action": "key", "key": "down"}, {"action": "wait", "seconds": 0.9}]
            for _ in range(4):
                if _quiet(R.send_batch, "tracker-row", steps):
                    return done, "the tracker didn't take the keys"
                state = row_state(Image.open(latest).convert("RGB"))
                if state is None or not state["above"]:
                    return done, "couldn't be sure of the cursor on the tracker"
                if state["blank"]:
                    break
                steps = [{"action": "key", "key": "down"}, {"action": "wait", "seconds": 0.7}]   # half typed by a colleague
            else:
                return done, "no empty row where one should be"
            if look_only:
                return done, f"would paste here: {row_text(trip, carrier, now)!r}"
            result, _ = _quiet(R.ask, "paste", text=row_text(trip, carrier, now))
            if not result.get("ok"):
                return done, f"the paste was refused ({result.get('detail')})"
            done += 1
            try:
                if _quiet(R.send_batch, "tracker-check", [{"action": "wait", "seconds": 1.0}]):
                    return done, "couldn't look at the row after the paste"
                filled = row_filled(Image.open(latest).convert("RGB"))
            except Exception as x:
                # the paste went: it stays counted, so a retry never pastes it again - only the look after it failed
                return done, f"couldn't look at {trip['manifest']}'s row after the paste ({str(x)[:80]}): check it by eye"
            if not filled:
                why = f"{trip['manifest']}'s row didn't read back as filled: look at it"
                break
    finally:
        try:
            (_, payload) = _quiet(R.ask, "use", target="ctms")
        except Exception:
            payload = None                 # what was pasted stays counted; the bridge books nothing on the tracker's tab
        if payload and payload.get("kind") == "window":
            R.save_state(payload)          # the page's picture was the last on file: what's next aims at CTMS
    return done, why


# -- the site's email
def first_name(name):
    """The name to greet: "Blake, Steven" or "Steven Blake" -> Steven."""
    name = str(name or "").strip()
    if "," in name:
        name = name.split(",", 1)[1].strip()
    word = (name.split() or [""])[0]
    return word if re.fullmatch(r"[A-Za-z][A-Za-z'-]+", word) else ""


def and_list(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


LORRIES = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def greeting(sender, sender_address, rec):
    """Who a reply greets: the name the order has for its contact, when the mail is theirs or ours; else whoever wrote it."""
    who = first_name(sender)
    if not who or who == PLANNER or str(sender_address or "").lower() == str(rec.get("to") or "").lower():
        return first_name(rec.get("name")) or ("" if who == PLANNER else who)
    return who


def words(greet, carrier, haulier, date, trips, rec, thanks=False):
    """His own wording (30/10): "Thanks. This order has been arranged with ... for <day>, delivering between ... and ....
    Here is the ref number MAN-...". The start is CTMS's, the end the site's window. Never a price."""
    day = datetime.strptime(date, "%d/%m/%Y").strftime("%A %d/%m/%Y")
    t = (rec.get("details") or {}).get("time") or {}
    start = str(trips[0].get("deliver") or "").strip()[9:14] or str(t.get("earliest") or "")
    end = str(t.get("latest") or "")
    when = f"delivering between {start} and {end}" if start and end > start else f"delivering from {start}" if start else ""
    who = "our own DHL fleet" if carrier == NOC else (haulier or carrier)
    mans = [x["manifest"] for x in trips]
    n = len(mans)
    last = f"Here is the ref number {mans[0]}" if n == 1 else (
        f"It will come on {LORRIES.get(n, n)} lorries. Here are the ref numbers: {and_list(mans)}")
    return (f"Hi {greet or 'there'},<br><br>{'Thanks. ' if thanks else ''}This order has been arranged with {who} for {day}"
            + (f", {when}" if when else "") + f". {last}<br><br>")


def _addresses(mail):
    mail.Recipients.ResolveAll()
    out = []
    for i in range(1, mail.Recipients.Count + 1):
        r = mail.Recipients.Item(i)
        a = ""
        try:
            u = r.AddressEntry.GetExchangeUser()
            a = u.PrimarySmtpAddress if u is not None else ""
        except Exception:
            pass
        out.append((i, (a or str(r.Address or "") or str(r.Name or "")).lower()))
    return out


def haulier_addresses():
    """Every address the haulier list has: a site email never goes to one."""
    try:
        import hauliers
        d = hauliers.load()
        return {str(a).lower() for h in d.get("hauliers", []) + d.get("services", []) for a in h.get("emails") or []}
    except Exception:
        return set()


def _when(item):
    for attr in ("ReceivedTime", "SentOn"):
        try:
            t = getattr(item, attr)
            return datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
        except Exception:
            pass
    return datetime(2000, 1, 1)


def _people(item):
    """The addresses on a mail, lower case: its sender's and each recipient's."""
    got = set()
    try:
        got.add(str(item.SenderEmailAddress or "").lower())
    except Exception:
        pass
    try:
        for i in range(1, item.Recipients.Count + 1):
            r = item.Recipients.Item(i)
            got.add(str(r.Address or "").lower())
            try:
                u = r.AddressEntry.GetExchangeUser()
                if u is not None:
                    got.add(str(u.PrimarySmtpAddress or "").lower())
            except Exception:
                pass
    except Exception:
        pass
    return got


def site_rank(subject, people, orders, site_topic, contact, conv=None, thread_conv=None, not_site=frozenset()):
    """How surely a mail with an order number in its subject is on the site's thread: 2 our site email's own thread, 1 the
    contact is on it and it opens with the order, 0 not at all - a haulier's cover request ("<order> Delivery") and the
    materials team's "alternative contact" chain start with the order number too."""
    import file_chain
    topic = file_chain.topic(subject)
    if people & not_site or "alternative contact" in topic:
        return 0
    if (thread_conv and conv == thread_conv) or (site_topic and topic == site_topic):
        return 2
    return 1 if contact and contact in people and any(topic.startswith(str(o).lower()) for o in orders) else 0


def site_thread(ns, rec):
    """(the newest mail of the order's site thread, how sure) - the Inbox, where he files them, or Sent Items - or (None, 0).
    Our own thread when there is one; a mail that only has the contact on it, when there isn't."""
    import build_drafts as bd
    import file_chain
    root = bd.dhl_store(ns)
    boxes = [bd.sub(root, "Inbox"), file_chain.folder(root, file_chain.DEST), bd.sub(root, "Sent Items")]
    orders = [str(o) for o in rec.get("orders") or []]
    site_topic = file_chain.topic(bd.subject_for(orders, rec.get("worksite") or "", rec.get("site") or "",
                                                 rec.get("postcode") or "", rec.get("po") or {}))
    contact = str(rec.get("to") or "").lower()
    thread_conv = ""
    if rec.get("orig_entryid"):
        try:
            thread_conv = str(ns.GetItemFromID(rec["orig_entryid"]).ConversationID or "")
        except Exception:
            pass
    not_site = haulier_addresses()
    best, how = None, 0
    for box in boxes:
        if box is None:
            continue
        for o in orders:
            for it in box.Items.Restrict('@SQL=("urn:schemas:httpmail:subject" LIKE \'%' + o.replace("'", "''") + '%\')'):
                subj = str(getattr(it, "Subject", "") or "")
                rank = site_rank(subj, _people(it), orders, site_topic, contact,
                                 str(getattr(it, "ConversationID", "") or ""), thread_conv, not_site)
                if rank and (rank, _when(it)) > (how, _when(best) if best is not None else datetime(2000, 1, 1)):
                    best, how = it, rank
    return best, how


def reaches(addresses, contact):
    """Whether a reply gets to the order's contact - the address on the order can be a letter out of the real one's."""
    who = str(contact or "").lower().split("@")[0]
    return any(str(a).lower().split("@")[0].startswith(who) for a in addresses) if who else True


def address_in_text(text, words_):
    """The address of whoever goes by these words in a mail's text: "Name <address>", the way a quoted chain has its people."""
    for who, a in re.findall(r"([^<>;:\r\n]*)<([\w.'+-]+@[\w-]+(?:\.[\w-]+)+)", str(text or "")):
        if all(w in f"{who} {a}".lower() for w in words_):
            return a.lower()
    return ""


def adhoc_address(src, name):
    """The delivery contact's address on an ad hoc's request - the form gives a name and a phone number, so only someone
    on the mail itself can be emailed: one of its recipients, or on a colleague's forward, someone in the chain it quotes.
    "" when nobody on it goes by that name."""
    words_ = [w.lower() for w in re.findall(r"[A-Za-z'-]{2,}", str(name or ""))]
    if not words_:
        return ""
    for i in range(1, src.Recipients.Count + 1):
        r = src.Recipients.Item(i)
        a = str(r.Address or "")
        try:
            u = r.AddressEntry.GetExchangeUser()
            a = (u.PrimarySmtpAddress if u is not None else "") or a
        except Exception:
            pass
        said = f"{r.Name} {a}".lower()
        if "@" in a and all(w in said for w in words_):
            return a.lower()
    return address_in_text(src.Body, words_)


def left_off_site(address, ours):
    """Who never stays on a site email: ourselves, and the DHL Road mailbox (his 03/11), whatever the chain had on it."""
    return address == ours or "dhlroad" in address


def checks(top, trips, got, mine):
    """What must be true of a site email before it goes: the words, the recipients. [] when it may."""
    bad = []
    if not got:
        bad.append("nobody to send it to")
    if any(a in mine for a in got):
        bad.append("a haulier is on it")
    for x in trips:
        if x["manifest"] not in top:
            bad.append(f"{x['manifest']} missing")
    if "£" in top:
        bad.append("a price slipped in")
    if "—" in top:
        bad.append("an em dash crept in")
    return bad


def site_email(rec, job, trips, send=True):
    """The site told. Returns (sent, what was done, in words): it never raises for want of a thread - he is told.
    send False: built, checked and thrown away, the words said back."""
    import build_drafts as bd
    import send_order
    ns = bd.get_ns()
    acct = next((ns.Accounts.Item(i) for i in range(1, ns.Accounts.Count + 1)
                 if str(getattr(ns.Accounts.Item(i), "SmtpAddress", "")).lower() == bd.DHL_SMTP.lower()), None)
    if acct is None:
        return False, "the DHL account wasn't found"
    carrier, haulier, date = job["carrier"], job.get("haulier") or "", job["date"]
    oneoff = rec.get("kind") in ("adhoc", "dts")
    thanks = False
    if oneoff:
        entry = (rec.get("mail") or {}).get("entryid")
        if not entry:
            return False, "no request email on this ad hoc to forward"
        src = ns.GetItemFromID(entry)
        contact = ((rec.get("details") or {}).get("contact") or {}).get("name") or ""
        to = job.get("site_to") or adhoc_address(src, contact)
        if not to:
            return False, f"no address for {contact or 'the delivery contact'} on the request"
        m = src.Forward()
        m.To = to
        greet = first_name(contact)
    else:
        src, _ = site_thread(ns, rec)
        if src is not None:
            m = src.ReplyAll()
            if rec.get("to") and not reaches([a for _, a in _addresses(m)], rec["to"]):
                m.Close(1)               # its last word was someone else's - a materials team's - and wouldn't reach the site
                src = None
        if src is None:
            if not rec.get("to"):
                return False, "no site thread and no contact"
            m = ns.Application.CreateItem(0)
            m.To = rec["to"]
            m.Subject = bd.subject_for(rec.get("orders") or [], rec.get("worksite") or "", rec.get("site") or "",
                                       rec.get("postcode") or "", rec.get("po") or {})
            greet = first_name(rec.get("name"))
        else:
            sender = str(getattr(src, "SenderName", "") or "")
            greet = greeting(sender, getattr(src, "SenderEmailAddress", ""), rec)
            thanks = first_name(sender) != PLANNER
    body = words(greet, carrier, haulier, date, trips, rec, thanks)
    if oneoff or src is not None:
        new, n = re.subn(r"(<body[^>]*>)", lambda mm: mm.group(1) + f'<div style="{FONT}">{body}</div>', m.HTMLBody,
                         count=1, flags=re.I)
        if n != 1:
            return False, "couldn't find where its text starts"
        m.HTMLBody = new
    else:
        m.HTMLBody = bd.html_from_message(body.replace("<br>", "\n").strip())
        bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        return False, "couldn't set the DHL account on it"
    for i, a in reversed(_addresses(m)):
        if left_off_site(a, bd.DHL_SMTP.lower()):
            m.Recipients.Remove(i)       # his own reply-all
    got = [a for _, a in _addresses(m)]
    top = re.split(r"\n\s*(?:From:|-#-#-|________________)", str(m.Body or ""))[0]
    bad = checks(top, trips, got, haulier_addresses())
    if bad and send:
        return False, "; ".join(bad)
    if not send:
        said = f"to {got} subject {m.Subject!r} problems {bad}: {re.sub(r'(\r?\n)+', ' / ', top).strip()[:500]}"
        m.Close(1)                       # thrown away
        return False, said
    m.Display(False)                     # a reply open in the reading pane refuses a plain Send
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    return True, "emailed " + and_list(got)


def _between(stamp, latest):
    """"Tuesday 03/11/2026 between 12:00 and 13:00" from the well's dd/mm/yy HH:MM and the window's end; "" with no stamp."""
    try:
        when = datetime.strptime(str(stamp or "").strip()[:14], "%d/%m/%y %H:%M")
    except ValueError:
        return ""
    start, day = when.strftime("%H:%M"), when.strftime("%A %d/%m/%Y")
    return f"{day} between {start} and {latest}" if str(latest or "") > start else f"{day} from {start}"


def collection_contact(rec):
    """The name and number on the collection end of the order's upload, which the record doesn't keep; "" without one."""
    try:
        import csv
        import outbox
        with open(outbox.path(rec["csv"]), encoding="utf-8", newline="") as f:
            row = next(r for r in csv.reader(f) if r and r[0] == "ORDER")
        return re.sub(r"\s+", " ", f"{row[4]} {row[5]} {row[12]}").strip()
    except Exception:
        return ""


def pass_words(greet, trips, rec):
    """What Parcel Pass is told when the job comes to them: the manifest and the job. Never asked for an ETA (his 03/11)."""
    d = rec.get("details") or {}
    mans = [x["manifest"] for x in trips]
    number = f"Here's the manifest number: {mans[0]}" if len(mans) == 1 else f"Here are the manifest numbers: {and_list(mans)}"
    lines = [f"Hi {greet or 'there'},", "", f"Thanks for covering this, sending it over now. {number}", ""]
    collect = _between(trips[0].get("collect"), (d.get("collection_time") or {}).get("latest"))
    deliver = _between(trips[0].get("deliver"), (d.get("time") or {}).get("latest"))
    frm = " ".join(str(rec.get(k) or "") for k in ("collection_site", "collection_pc")).strip()
    to = " ".join(str(rec.get(k) or "") for k in ("site", "postcode")).strip()
    if collect:
        lines.append(f"Collection: {collect}" + (f", {frm}" if frm else ""))
    if deliver:
        lines.append(f"Delivery: {deliver}" + (f", {to}" if to else ""))
    who = collection_contact(rec)
    if who:
        lines.append(f"Collection contact: {who}")
    contact = d.get("contact") or {}
    site = " ".join(str(contact.get(k) or "") for k in ("name", "phone")).strip()
    if site:
        lines.append(f"Site contact: {site}")
    return "<br>".join(lines) + "<br><br>"


def pass_greeting(sender):
    who = first_name(sender)
    return "" if who.isupper() else who          # the shared mailbox's name, NR, isn't anyone's


def pass_thread(ns, orders):
    """The newest mail from Parcel Pass on this order (their quote), in the Inbox or filed: None when there isn't one."""
    import build_drafts as bd
    import file_chain
    root = bd.dhl_store(ns)
    best = None
    for box in (bd.sub(root, "Inbox"), file_chain.folder(root, file_chain.DEST)):
        if box is None:
            continue
        for o in orders:
            for it in box.Items.Restrict('@SQL=("urn:schemas:httpmail:subject" LIKE \'%' + str(o).replace("'", "''") + '%\')'):
                if PASS_DOMAIN in str(getattr(it, "SenderEmailAddress", "") or "").lower() and (best is None or _when(it) > _when(best)):
                    best = it
    return best


def pass_checks(top, trips, got):
    bad = []
    if not got or not all(PASS_DOMAIN in a for a in got):
        bad.append("it isn't going to Parcel Pass alone")
    for x in trips:
        if x["manifest"] not in top:
            bad.append(f"{x['manifest']} missing")
    if re.search(r"\bETA\b", top):
        bad.append("it asks for an ETA")
    if "—" in top:
        bad.append("an em dash crept in")
    return bad


def pass_email(rec, trips, orders, send=True):
    """Parcel Pass told it's coming to them, on their own quote's thread: (sent, what was done, in words)."""
    import build_drafts as bd
    import hauliers
    import send_order
    ns = bd.get_ns()
    acct = next((ns.Accounts.Item(i) for i in range(1, ns.Accounts.Count + 1)
                 if str(getattr(ns.Accounts.Item(i), "SmtpAddress", "")).lower() == bd.DHL_SMTP.lower()), None)
    if acct is None:
        return False, "the DHL account wasn't found"
    src = pass_thread(ns, orders)
    if src is not None:
        m = src.Reply()
        body = pass_words(pass_greeting(getattr(src, "SenderName", "")), trips, rec)
        new, n = re.subn(r"(<body[^>]*>)", lambda mm: mm.group(1) + f'<div style="{FONT}">{body}</div>', m.HTMLBody,
                         count=1, flags=re.I)
        if n != 1:
            return False, "couldn't find where its text starts"
        m.HTMLBody = new
    else:
        service = next((s for s in hauliers.load().get("services", []) if PASS_DOMAIN in " ".join(s.get("emails") or []).lower()), None)
        if service is None:
            return False, "no Parcel Pass address on the list"
        m = ns.Application.CreateItem(0)
        m.To = service["emails"][0]
        m.Subject = f"{' / '.join(orders)} Delivery"
        m.HTMLBody = bd.html_from_message(pass_words("", trips, rec).replace("<br>", "\n").strip())
        bd._attach_qr(m)
    if not send_order.bind_account(m, acct):
        return False, "couldn't set the DHL account on it"
    got = [a for _, a in _addresses(m)]
    top = re.split(r"\n\s*(?:From:|-#-#-|________________)", str(m.Body or ""))[0]
    bad = pass_checks(top, trips, got)
    if bad and send:
        return False, "; ".join(bad)
    if not send:
        said = f"to {got} subject {m.Subject!r} problems {bad}: {re.sub(r'(\r?\n)+', ' / ', top).strip()[:500]}"
        m.Close(1)                       # thrown away
        return False, said
    m.Display(False)                     # a reply open in the reading pane refuses a plain Send
    m.Send()
    try:
        ns.SendAndReceive(False)
    except Exception:
        pass
    return True, "emailed " + and_list(got)


def file_away(rec):
    """The job's mail filed in Region 2 > Completed: (how many, or the reason it couldn't)."""
    import build_drafts as bd
    import file_chain
    ns = bd.get_ns()
    if rec.get("kind") in ("adhoc", "dts"):
        entry = (rec.get("mail") or {}).get("entryid")
        if not entry:
            return 0
        dest = file_chain.folder(bd.dhl_store(ns), file_chain.DEST)
        ns.GetItemFromID(entry).Move(dest)
        return 1
    return len(file_chain.file_chain(ns, rec))


def take_off(ident):
    """Off the map, the way its Booked button does it."""
    import agent
    with open(os.path.join(HERE, "cloud.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    agent.BASE, agent.KEY = cfg["url"], cfg["agent_key"]
    return agent._book_off(ident)


# -- a step done once only
SENT_LOOK = 300                  # Sent Items looked through for an email already gone, newest first
SENT_DAYS = 3


def sent_already(manifests, to_has="", to_not=""):
    """Whether an email naming every one of these manifests has gone from the DHL account in the last few days - to an
    address with to_has in it, or with no to_not in any. A retry looks first: the Send can go through and the run still
    die before the journal hears of it, and a second "it's booked" email to a site is the one mistake here that reads as
    a muddle to the customer."""
    import build_drafts as bd
    want = [m for m in manifests if m]
    if not want:
        return False
    folder = bd.sub(bd.dhl_store(bd.get_ns()), "Sent Items")
    if folder is None:
        return False
    items = folder.Items
    items.Sort("[SentOn]", True)
    since = datetime.now() - timedelta(days=SENT_DAYS)
    for n, it in enumerate(items):
        if n >= SENT_LOOK:
            break
        try:
            if datetime(*it.SentOn.timetuple()[:6]) < since:
                break
            body = str(getattr(it, "Body", "") or "")[:4000]
            if not all(m in body for m in want):
                continue
            to = " ".join(a for _, a in _addresses(it)).lower()       # only for a mail that names them: it's slow
        except Exception:
            continue
        if (not to_has or to_has in to) and not (to_not and to_not in to):
            return True
    return False


def _step(k, name, fn, auto=False):
    """One step run and written down: (ok, words). An exception is a step not done, never a run ended."""
    import book_journal as J
    try:
        ok, said = fn()
    except Exception as e:
        ok, said = False, str(e)[:160]
    J.step(k, name, ok, said, auto=auto)
    return ok, said


def follow(k, R=None, now=None, auto=False, only=None):
    """What follows a booking, each step the journal hasn't got as done - the steps, then, a press of Book, a Retry and the
    timer all share. auto: the timer, which leaves the DigiHaul row to his Retry (it needs Look mum, no hands on). only:
    these steps alone. Returns the words, step by step."""
    import book_journal as J
    now = now or datetime.now()
    e = J.get(k) or {}
    made = J.accepted(e)
    mans = [t["manifest"] for t in made]
    if not mans:
        return []                            # nothing ACCEPTED: nothing follows
    carrier = str(e.get("carrier") or "")
    job = {x: e.get(x) for x in J.JOB_KEYS if e.get(x) not in (None, "")}
    orders = [str(o) for o in e.get("orders") or []]
    rec = record_of(e.get("record")) or {"orders": orders}
    said = []
    for name in J.left(e):
        if only and name not in only:
            continue
        if auto and name not in J.AUTO:
            continue
        steps = (J.get(k) or {}).get("steps") or {}
        tried = int((steps.get(name) or {}).get("tries") or 0)
        started = bool((steps.get(name) or {}).get("started"))     # begun by a run that may have died after the Send
        if name == "digihaul":
            have = set((steps.get("digihaul") or {}).get("written") or [])
            todo = [t for t in made if t["manifest"] not in have]
            nocost = [t["manifest"] for t in todo if t.get("cost") in (None, "")]
            if nocost:
                J.step(k, name, False, f"the cost of {and_list(nocost)} isn't known here: type the row by hand")
                said.append(f"DigiHaul NOT written: the cost of {and_list(nocost)} isn't known here. By hand: "
                            + " | ".join(row_text(t, carrier, now).replace("\t", ", ") for t in todo) + ".")
                continue
            R = R or _client()
            rows, why = 0, ""
            for t in todo:                       # one at a time, each kept as it goes on: a retry never pastes it twice
                try:
                    n, why = tracker_rows(R, [t], carrier, now)
                except Exception as x:
                    n, why = 0, str(x)[:160]
                if n:
                    J.written(k, t["manifest"])
                    rows += 1
                if why or not n:
                    why = why or "the row didn't go on"
                    break
            left_ = [t for t in todo if t["manifest"] not in set(((J.get(k) or {}).get("steps") or {})
                                                                  .get("digihaul", {}).get("written") or [])]
            J.step(k, name, not left_, why)
            said.append(f"DigiHaul: {rows} row(s) written" + (f", but {why}." if why else ".") if not left_ else
                        f"DigiHaul: {rows} of {len(todo)} row(s) written, {why}. Retry, or by hand: "
                        + " | ".join(row_text(t, carrier, now).replace("\t", ", ") for t in left_) + ".")
        elif name == "pass_email":
            def go():
                if (tried or started) and sent_already(mans, to_has=PASS_DOMAIN):
                    return True, "it had gone already"
                J.begin(k, name)
                return pass_email(rec, made, orders)
            ok, how = _step(k, name, go, auto)
            said.append(f"Parcel Pass: {how}." if ok else f"Parcel Pass email NOT sent ({how}): "
                        + ("I'll try again in a few minutes." if _auto_left(k, name) else f"tell them {and_list(mans)} by hand, or Retry."))
        elif name == "site_email":
            def go():
                if (tried or started) and sent_already(mans, to_not=PASS_DOMAIN):
                    return True, "it had gone already"
                J.begin(k, name)
                return site_email(rec, job, made)
            ok, how = _step(k, name, go, auto)
            said.append(f"Site: {how}." if ok else f"Site email NOT sent ({how}): "
                        + ("I'll try again in a few minutes." if _auto_left(k, name) else f"tell them {and_list(mans)} by hand, or Retry."))
        elif name == "filed":
            if "site_email" in J.left(J.get(k) or {}):
                continue                         # the chain stays where the site email's retry can find its thread
            ok, how = _step(k, name, lambda: (True, f"{file_away(rec)} filed"), auto)
            if ok:
                said.append("Chain filed.")
        elif name == "off_map":
            def go():
                removed, _ = take_off(e.get("record"))
                return True, "off the map" if removed else "it had gone under another id"
            ok, how = _step(k, name, go, auto)
            said.append("Off the map." if ok and how == "off the map" else
                        f"Still on the map: {how}." if ok else f"Still on the map ({how}).")
    return said


def _auto_left(k, name):
    import book_journal as J
    s = ((J.get(k) or {}).get("steps") or {}).get(name) or {}
    return name in J.AUTO and s.get("next_at") is not None and not s.get("ok")


# -- what came of an ask nobody heard the answer to
def _parsed_trips(text):
    """Manifests and their status out of the bridge's words ("Booked 1 in 52s: MAN-01000001 ACCEPTED, ..."), when the
    picture-laden payload has gone: no cost, so the DigiHaul row waits for him."""
    return [{"manifest": m, "status": st} for m, st in re.findall(r"(MAN-\d+)\s+([A-Z]+)", str(text or ""))]


def recall(k, R=None):
    """An ask whose answer the home PC never had, looked for again: the dashboard by its command id, then the work PC's
    own record of what its Book made. Either answer goes into the journal as if it had come at the time. Nothing in CTMS
    is touched. Returns the journal's entry."""
    import book_journal as J
    e = J.get(k) or {}
    cid = e.get("ask_id")
    if not cid:
        # no number came back: the dashboard may still have queued it (the POST's answer lost on the way) and the work PC
        # booked it, so it is never taken for nothing made - after a while it is his to look at in CTMS
        if time.time() - float(e.get("asked_at") or 0) > J.LOST_AFTER:
            return J.lost(k, "the dashboard never said it had the command - it may have reached the work PC")
        return J.get(k)
    R = R or _client()
    try:
        result, payload = R.result_of(cid)
    except Exception:
        result, payload = None, None
    if result is not None and (payload or {}).get("trips") is not None:
        return J.answered(k, result.get("ok"), result.get("detail"), payload["trips"], e.get("carrier"))
    try:
        got, back = _quiet(R.ask, "book_recall", wait_total=45, orders=e.get("orders"), date=e.get("date"), ask=cid)
    except Exception:
        got, back = {}, None
    found = ((back or {}).get("found") or []) if got.get("ok") else None
    if found:
        f = found[0]
        return J.answered(k, f.get("ok"), f.get("said"), f.get("trips"), e.get("carrier"))
    if result is not None:
        trips = _parsed_trips(result.get("detail"))
        return J.answered(k, result.get("ok"), result.get("detail"), trips, e.get("carrier"))
    if found is not None and time.time() - float(e.get("asked_at") or 0) > J.LOST_AFTER:
        # the work PC answered and has nothing for that command: it never ran it, or died before it was done
        return J.lost(k, "the work PC has no record of booking it - it may have stopped part way")
    return J.get(k)


# -- the whole of it
LOCK_WAIT = 20


def _lock():
    """One booking run on the home PC at a time - a press of Book, a Retry, the timer: the journal is read and written by
    each, and two at once could each think a step undone."""
    try:
        import outlook_gate
        return outlook_gate.named_lock("book_run", wait=LOCK_WAIT)
    except Exception:
        return True


def book(job, R=None, now=None):
    """One press of Book: the answer the agent passes on. The journal decides first whether CTMS is asked at all."""
    import book_journal as J
    t0 = time.time()
    now = now or datetime.now()
    orders = [str(o) for o in job.get("orders") or []]
    out = {"ok": False, "said": "", "trips": [], "seconds": None}
    dry = bool(job.get("dry"))
    k = J.key(orders, job.get("date"))
    if not dry:
        if _lock() is None:
            out["said"] = "Another booking is still finishing on the home PC: press it again in a minute. Nothing was booked."
            return out
        e = J.get(k)
        if J.verdict(e) == "recall":
            e = recall(k, R)
        v = J.verdict(e)
        mans = and_list([t["manifest"] for t in J.accepted(e)]) if J.accepted(e) else ""
        if v == "recall":
            out["said"] = ("The last press of Book for this order is still waiting for the work PC's answer, so it isn't "
                           "booked again. Give it a few minutes: what it made is picked up by itself. If CTMS shows "
                           "nothing for it, Clear it on the Bookings card and press Book again.")
            out["pending"] = True
            return out
        if v == "hold":
            out["said"] = ("Not booked again: " + (f"{', '.join(e.get('short') or [])} was left short of ACCEPTED in CTMS"
                                                  if e.get("state") == "half" else
                                                  "the last press never said what it made")
                           + ". Look in CTMS, then Clear it on the Bookings card (or finish it there) and press Book again.")
            out["held"] = True
            return out
        if v == "finished":
            out.update(ok=True, said=f"Already booked: {mans}, and everything after it is done. Nothing booked again.",
                       trips=J.accepted(e))
            return out
        if v == "resume":
            said = [f"Already booked in CTMS: {mans}. Nothing booked again; finishing what was left."]
            said += follow(k, R, now)
            e = J.get(k)
            out.update(ok=True, said=" ".join(said), trips=J.accepted(e), resumed=True, total=round(time.time() - t0, 1))
            return out
    first = owed_first(orders)
    before = []
    if first and not dry:
        # his 03/11: what's missing on a line is dealt with, not gone past - the to-do's update (times, the delivery
        # comment, services, the Veh Type) is typed in first, by the same run the to-do's Run button uses
        went, how = run_owed(first)
        if not went:
            out["said"] = f"{how} Nothing was booked."
            return out
        before.append(how)
    R = R or _client()
    args = {k_: job[k_] for k_ in ("orders", "date", "carrier", "trailer", "vehicles", "dry") if job.get(k_) not in (None, "")}
    if job.get("haulage") not in (None, ""):
        args["haulage"] = float(job["haulage"])
    qty = quantities(record_of(job.get("record")) or {})
    if qty:
        args["qty"] = qty
    wait = min(780, 150 + 90 * int(job.get("vehicles") or 1) + 30 * max(1, len(orders)))
    numbered = []
    if not dry:
        J.asking(job)

        def on_id(cid):
            numbered.append(cid)             # the work PC has it from here: only its answer says what was made
            J.asked(k, cid)
        args["on_id"] = on_id
    try:
        result, payload = _quiet(R.ask_waiting, "ctms_book", wait_total=wait, **args)
    except Exception as x:
        if dry:
            raise
        if getattr(x, "code", None) == 4 or numbered:
            # a dashboard error once the command was numbered is not CTMS's answer: what it made is looked for again
            out["said"] = (("The work PC didn't answer in time" if getattr(x, "code", None) == 4 else
                            f"{x} The work PC's answer couldn't be had") + ": it may still be booking. Don't book it by "
                           "hand: press Book again in a few minutes and I'll pick up what it made rather than book it twice.")
            out["pending"] = True
            return out
        J.answered(k, False, str(x), [], job.get("carrier"))        # refused before the work PC had it: nothing made
        out["said"] = f"{x} Nothing was booked."
        out["refused"] = True
        return out
    payload = payload or {}
    trips = payload.get("trips") or []
    out.update(trips=[{k_: t.get(k_) for k_ in ("manifest", "status", "revenue", "cost")} for t in trips],
               seconds=payload.get("seconds"), stages=payload.get("stages"), ctms=result.get("detail"))
    if dry:
        out.update(ok=bool(result.get("ok")), said=str(result.get("detail") or "The work PC didn't answer."))
        return out
    e = J.answered(k, result.get("ok"), result.get("detail"), trips, job.get("carrier"))
    made = J.accepted(e)
    if not made:
        out["said"] = str(result.get("detail") or "The work PC didn't answer.")
        return out
    said = before + [f"{and_list([t['manifest'] for t in made])} ACCEPTED with {job['carrier']} in "
                     f"{payload.get('seconds')} seconds"
                     + (f" (cost {made[0].get('cost')}, revenue {made[0].get('revenue')})" if len(made) == 1 else "") + "."]
    fixed = [n for n in payload.get("notes") or []
             if "put right" in n or "put up to" in n or "PUT BACK BY HAND" in n or "split into" in n]
    if fixed:
        said.append("On the lines first: " + "; ".join(fixed) + ".")
    if not result.get("ok"):
        said.append(f"Then CTMS stopped: {result.get('detail')} What was ACCEPTED is followed up below.")
    for t in made:
        if len(t.get("lines") or []) > 1:
            said.append(f"{t['manifest']} has {len(t['lines'])} lines: {t.get('took', 1)} went on from selecting them in one go"
                        + (f", the other {len(t['lines']) - t.get('took', 1)} by Apply to Trip." if t.get("took", 1) < len(t["lines"]) else "."))
    said += follow(k, R, now)
    e = J.get(k) or {}
    out.update(ok=True, said=" ".join(said), email=bool(((e.get("steps") or {}).get("site_email") or {}).get("ok")),
               total=round(time.time() - t0, 1))
    if "pass_email" in (e.get("steps") or {}):
        out["pass_email"] = bool(e["steps"]["pass_email"].get("ok"))
    return out


# -- Book approved: his ticked list, one after another
def not_ready(rec):
    """Why an order isn't strictly ready to book, in words - "" when it is (his rule 03/11: nothing missing, nothing
    amber, the site has answered). Checked here again whatever the dashboard showed: the tracker may have moved since."""
    if not rec or not rec.get("orders"):
        return "it's no longer on the map or the tracker"
    kind = rec.get("kind")
    if kind in ("adhoc", "dts"):
        return ""                                    # its details came on the form
    if kind in ("pinned", "collection"):
        return "it isn't a delivery the desk books"
    answered = rec.get("phoned_at") or rec.get("ctms_veh")
    if not (answered or rec.get("reply_at")):
        return "the site hasn't replied"
    if not answered and rec.get("missing"):
        return "still missing: " + ", ".join(str(m) for m in rec["missing"])
    amber = [k for k, v in (rec.get("details") or {}).items() if isinstance(v, dict) and v.get("confidence") == "amber"]
    if amber:
        return "not confirmed yet: " + ", ".join(sorted(amber))
    return ""


def go_on(res):
    """Whether the next booking of the batch may start: only after one that booked, or one that stopped before touching
    anything ("Nothing was booked"). A refusal (Stop pressed, acting off), an answer still to come, a half-made trip or a
    stop part way leaves CTMS for him to look at first."""
    if res.get("refused") or res.get("pending") or res.get("held"):
        return False
    if res.get("ok"):
        return True
    return "Nothing was booked" in str(res.get("said") or "") or bool(res.get("skipped"))


def _progress(R, run_id, i, state, said="", manifests=()):
    if run_id in (None, ""):
        return
    try:
        R.http("POST", "/api/ctms/book/progress", {"run": run_id, "i": i, "state": state, "said": str(said)[:500],
                                                   "manifests": list(manifests)})
    except Exception:
        pass                             # the page told is never worth a booking


def batch(jobs, run_id=None, R=None, now=None):
    """Each approved job booked in turn, through book() and so the journal: one already booked is finished, not booked
    again. Stops at the first that leaves CTMS needing a look. Returns {ok, said, results}."""
    R = R or _client()
    t0 = time.time()
    results = []
    stopped = ""
    for i, job in enumerate(jobs):
        named = " / ".join(str(o) for o in job.get("orders") or [])
        _progress(R, run_id, i, "running")
        why = not_ready(record_of(job.get("record")))
        if why:
            res = {"ok": False, "skipped": True, "said": f"Not booked: {why}. Nothing was booked.", "trips": []}
        else:
            try:
                res = book(dict(job), R=R, now=now)
            except Exception as e:
                res = {"ok": False, "said": f"The booking failed before it finished: {e}. Look at CTMS.", "trips": []}
        mans = [t.get("manifest") for t in res.get("trips") or [] if t.get("manifest") and t.get("status") == "ACCEPTED"]
        state = "booked" if res.get("ok") else "skipped" if res.get("skipped") else "not booked"
        _progress(R, run_id, i, state, res.get("said"), mans)
        results.append({"orders": job.get("orders"), "ok": bool(res.get("ok")), "state": state, "said": res.get("said"),
                        "manifests": mans})
        if not go_on(res):
            stopped = named
            break
    booked = sum(1 for r in results if r["ok"])
    said = f"{booked} of {len(jobs)} booked"
    if stopped:
        said += (f"; stopped at {stopped} so CTMS can be looked at" + (f", {len(jobs) - len(results)} not started"
                                                                      if len(jobs) > len(results) else ""))
    skipped = [r for r in results if r["state"] != "booked"]
    if skipped:
        said += ". " + " ".join(f"{' / '.join(r['orders'] or [])}: {r['said']}" for r in skipped)
    return {"ok": bool(booked) and not stopped, "said": said, "results": results,
            "trips": [{"manifest": m, "status": "ACCEPTED"} for r in results for m in r["manifests"]],
            "seconds": round(time.time() - t0, 1)}


def retry(now=None):
    """The home PC's timer (agent.py, every few minutes): answers never heard looked for again, and Outlook's steps that
    failed tried again on their own clock. Nothing is asked of CTMS but the work PC's own record."""
    import book_journal as J
    if _lock() is None:
        return {"ok": True, "said": "a booking is running: next time", "did": []}
    did = []
    for k in J.unanswered():
        e = recall(k)
        did.append(f"{k}: {(e or {}).get('state')}")
    for k, steps in J.due():
        words = follow(k, now=now, auto=True, only=steps)
        did.append(f"{k}: " + " ".join(words))
    return {"ok": True, "said": f"{len(did)} booking(s) looked at", "did": did}


def clear(k, step=None):
    """His Done by hand / Clear on the Bookings card."""
    import book_journal as J
    e = J.by_hand(k, step)
    return {"ok": e is not None, "said": "cleared" if e is not None else "that booking is no longer on file",
            "state": (e or {}).get("state")}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if argv[:1] == ["retry"]:
        res = retry()
        print(res["said"])
        for d in res["did"]:
            print("  " + d)
        print(json.dumps(res, default=str))
        return 0
    if argv[:1] == ["batch"] and len(argv) >= 2:
        run_id = None
        if "--run" in argv:
            try:
                run_id = int(argv[argv.index("--run") + 1])
            except (IndexError, ValueError):
                run_id = None
        try:
            res = batch(json.loads(argv[1]), run_id)
        except Exception as e:
            res = {"ok": False, "said": f"The batch failed before it finished: {e}. Look at CTMS.", "results": [],
                   "trips": []}
        print(res["said"])
        print(json.dumps(res, default=str))
        return 0 if res["ok"] else 1
    if argv[:1] == ["clear"] and len(argv) >= 2:
        res = clear(argv[1], argv[2] if len(argv) > 2 else None)
        print(json.dumps(res, default=str))
        return 0 if res["ok"] else 1
    if len(argv) < 2 or argv[0] != "run":
        print(__doc__)
        return 2
    try:
        res = book(json.loads(argv[1]))
    except Exception as e:
        res = {"ok": False, "said": f"The booking run failed before it finished: {e}. Look at CTMS before pressing it again.",
               "trips": []}
    print(res["said"])
    print(json.dumps(res, default=str))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
