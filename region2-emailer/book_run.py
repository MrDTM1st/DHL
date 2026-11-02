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
     order's site thread, an ad hoc's request forwarded so its sheet stays attached, never a price. Nothing to the haulier
     or NOC: "We just let the delivery site know. The hauliers already know."
  5. the order off the map, its chain filed

A stop at any point says what was done so far. Past the booking nothing undoes it: what couldn't be done is said, for him
to do by hand.

    python book_run.py run '{"record": "...", "orders": ["..."], "date": "dd/mm/yyyy", "carrier": "...", "trailer": "...",
                             "haulier": "...", "haulage": 450, "vehicles": 1, "dry": false}'

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
HEAD_Y, HEAD_B, HEAD_C = 295, 150, 360
CELL_B = (140, 320)
CELLS = {"C": (332, 544), "D": (556, 669), "E": (682, 835), "F": (848, 1595), "G": (1608, 1890)}
INTO_GRID = [230, 390]             # a cell of column B, whichever row it is


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
    return [i for i in items if i.get("kind") in BLOCKS and want & set(ctms_todo._bases(i.get("orders") or []))]


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


def picked_row(im):
    """(top, bottom) of the row whose number is highlighted, or None."""
    ys = [y for y in range(ROW_TOP, min(ROW_END, im.size[1])) if _near(im.getpixel((GUTTER_X, y)), PICKED)]
    return (ys[0], ys[-1]) if ys else None


def _dark(im, xs, ys):
    return sum(1 for y in range(*ys) for x in range(*xs) if sum(im.getpixel((x, y))[:3]) < 240)


def row_state(im):
    """Where the tracker's cursor is on a picture: None when it can't be told it is on one cell of column B; else
    {"blank": the row's yellow cells are empty, "above": the row above has a manifest}."""
    row = picked_row(im)
    if not row or not _near(im.getpixel((HEAD_B, HEAD_Y)), PICKED) or _near(im.getpixel((HEAD_C, HEAD_Y)), PICKED):
        return None
    top, bottom = row
    if bottom - top < 8 or im.size[0] < CELLS["G"][1]:
        return None
    band = (top + 4, bottom - 3)
    return {"blank": not any(_dark(im, xs, band) for xs in CELLS.values()) and not _dark(im, CELL_B, band),
            "above": bool(_dark(im, CELL_B, (top - 20, top - 4)))}


def row_filled(im):
    """Whether the row just pasted shows in every yellow cell that should have something (F, Notes, stays blank)."""
    row = picked_row(im)
    if not row:
        return False
    band = (row[0] + 4, row[1] - 3)
    return bool(_dark(im, CELL_B, band)) and all(_dark(im, CELLS[c], band) for c in "CDEG")


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
            if _quiet(R.send_batch, "tracker-check", [{"action": "wait", "seconds": 1.0}]):
                return done, "couldn't look at the row after the paste"
            if not row_filled(Image.open(latest).convert("RGB")):
                why = f"{trip['manifest']}'s row didn't read back as filled: look at it"
                break
    finally:
        _quiet(R.ask, "use", target="ctms")
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


def adhoc_address(src, name):
    """The delivery contact's address on an ad hoc's request - the form gives a name and a phone number, so only someone
    on the mail itself can be emailed. "" when nobody on it goes by that name."""
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
    return ""


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
        if a == bd.DHL_SMTP.lower():
            m.Recipients.Remove(i)       # his own reply-all: never ourselves
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


# -- the whole of it
def book(job, R=None, now=None):
    """One press of Book: the answer the agent passes on."""
    t0 = time.time()
    now = now or datetime.now()
    orders = [str(o) for o in job.get("orders") or []]
    named = " / ".join(orders)
    out = {"ok": False, "said": "", "trips": [], "seconds": None}
    first = owed_first(orders)
    if first and not job.get("dry"):
        out["said"] = (f"{first[0]['what']}: that's still on the CTMS to-do, and it has to go on before the booking. "
                       "Run it first, or tick it off if it's done. Nothing was booked.")
        return out
    R = R or _client()
    args = {k: job[k] for k in ("orders", "date", "carrier", "trailer", "vehicles", "dry") if job.get(k) not in (None, "")}
    if job.get("haulage") not in (None, ""):
        args["haulage"] = float(job["haulage"])
    wait = min(600, 150 + 90 * int(job.get("vehicles") or 1))
    result, payload = _quiet(R.ask, "ctms_book", wait_total=wait, **args)
    payload = payload or {}
    trips = payload.get("trips") or []
    out.update(trips=[{k: t.get(k) for k in ("manifest", "status", "revenue", "cost")} for t in trips],
               seconds=payload.get("seconds"), stages=payload.get("stages"), ctms=result.get("detail"))
    if not result.get("ok"):
        out["said"] = str(result.get("detail") or "The work PC didn't answer.")
        return out
    if job.get("dry"):
        out.update(ok=True, said=str(result.get("detail")))
        return out
    made = [t for t in trips if t.get("status") == "ACCEPTED"]
    said = [f"{and_list([t['manifest'] for t in made])} ACCEPTED with {job['carrier']} in {payload.get('seconds')} seconds"
            + (f" (cost {made[0]['cost']}, revenue {made[0]['revenue']})" if len(made) == 1 else "") + "."]
    rec = record_of(job.get("record")) or {"orders": orders}
    if str(job["carrier"]).upper().endswith("_DH"):
        try:
            rows, why = tracker_rows(R, made, job["carrier"], now)
        except Exception as e:
            rows, why = 0, str(e)
        said.append(f"DigiHaul: {rows} row(s) written." if not why else
                    f"DigiHaul: {rows} of {len(made)} row(s) written, {why}. By hand: "
                    + " | ".join(row_text(t, job["carrier"], now).replace("\t", ", ") for t in made[rows:]) + ".")
    try:
        sent, how = site_email(rec, job, made)
    except Exception as e:
        sent, how = False, str(e)[:160]
    said.append(f"Site: {how}." if sent else f"Site email NOT sent ({how}): tell them {and_list([t['manifest'] for t in made])} by hand.")
    out["email"] = sent
    try:
        if file_away(rec) and sent:
            said.append("Chain filed.")
    except Exception:
        pass
    try:
        removed, _ = take_off(job.get("record"))
        said.append("Off the map." if removed else "Still on the map: it went under another id.")
    except Exception as e:
        said.append(f"Still on the map ({str(e)[:80]}).")
    out.update(ok=True, said=" ".join(said), total=round(time.time() - t0, 1))
    return out


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
