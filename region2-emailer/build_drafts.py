"""
Region 2 emailer - Phase 1 draft engine.

Reads config.json, finds a Synergy Haulier Extract (latest from Outlook, or a
path you pass in), applies every agreed rule, and either previews the emails or
creates them as DRAFTS in your DHL Drafts folder. It never sends.

Usage:
    python build_drafts.py preview            # find latest extract, print emails
    python build_drafts.py preview <xlsx>     # preview a specific file
    python build_drafts.py commit             # create drafts in DHL Drafts (latest extract)
    python build_drafts.py commit <xlsx>      # create drafts from a specific file
"""
import sys, os, json, re, html as _html
from collections import defaultdict, OrderedDict
import tracker
import waitlist

DHL_SMTP = "delali.opoku@dhl.com"
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
REGION = CFG["regions"][CFG["active_region"]]
AREAS = set(REGION["postcode_areas"])
SOURCE_PREFIX = CFG["email_source"]["only_file"].lower()
BS_MARKERS = [m.lower() for m in CFG["email_source"].get("also_batches", [])]

# ---- never-email-yourself (team profiles) ----
_TEAM_CFG = None
def team_config():
    global _TEAM_CFG
    if _TEAM_CFG is None:
        try:
            from modules import profiles
            _TEAM_CFG = profiles.load_team(os.path.join(HERE, "config", "team.json"))
        except Exception:
            _TEAM_CFG = {}
    return _TEAM_CFG

def clean_to_cc(to, cc=""):
    """Strip your own DHL address (and duplicates) from To/Cc before any send, so
    the tool can never email you by mistake. Returns (to, cc, removed)."""
    try:
        from modules import profiles
        me = team_config().get("me") or DHL_SMTP
        return profiles.clean_recipients(to, cc, me=me)
    except Exception:
        return to or "", cc or "", []


def is_wanted_extract(filename, subject=""):
    """True if this attachment is a file the emailer should read: the normal
    Haulier Extract, OR a BS batch file (British Steel) identified by name or by
    the email subject. BS batches carry the same columns as the extract and hold
    real Region 2 orders, so they're processed identically. Master files and the
    other batch processes (Inframat/Rail Plan/S&C) are still ignored."""
    low = (filename or "").lower()
    if low.startswith("master"):
        return False   # a processed Master output (even "Master - ... BS"), never a source
    if low.startswith(SOURCE_PREFIX):
        return True
    if low.endswith((".xlsx", ".xlsm")):
        subj = (subject or "").lower()
        if any(m in low or m in subj for m in BS_MARKERS):
            return True
    return False

QUESTIONS = """    Date and time of delivery?
    Who will be the contact for delivery?
    Alternative delivery contact?
    Do we need to bring our own offloading? (HIAB or Moffet)
    Can artics access the site?
    Is rear steer required?
    Does the driver need PTS (Only required if within 3m of line)?
    What3Words Location?"""

SIGNATURE = """Kind regards

Delali Opoku

Transport Planner
Manufacturing Logistics
DHL Supply Chain UKI

Contact
07483621949

Out of Hours
03308 577160
07540901630

Excellence. Simply delivered.

Tell us how we did - we would greatly appreciate you taking 5 minutes to send us feedback on your delivery using the link or QR code below:
https://forms.office.com/e/hsiiNzy6B4"""

FORMS_URL = "https://forms.office.com/e/hsiiNzy6B4"
QR_PATH = os.path.join(HERE, "qr.png")

SIGNATURE_HTML = (
    "Kind regards<br><br>"
    "<b>Delali Opoku</b><br><br>"
    "<b>Transport Planner</b><br>Manufacturing Logistics<br>DHL Supply Chain UKI<br><br>"
    "<b>Contact</b><br>07483621949<br><br>"
    "<b>Out of Hours</b><br>03308 577160<br>07540901630<br><br>"
    '<span style="color:#D40511;font-weight:bold;">Excellence. Simply delivered.</span><br><br>'
    "Tell us how we did - we would greatly appreciate you taking 5 minutes to send us feedback "
    "on your delivery using the link or QR code below:<br>"
    f'<a href="{FORMS_URL}">{FORMS_URL}</a><br>'
    '<img src="cid:qrcode" alt="Feedback QR code" width="120" height="120" style="margin-top:8px;border:0;">'
)


def _bodies(name, items, dd):
    ask = "Can you please help with the details below and I can get the delivery arranged for you?"
    if len(items) == 1:
        q, pr = items[0]
        line_t = f"I've got {q}x {pr} available on {dd}. {ask}"
        line_h = f"I've got {q}x {_html.escape(pr)} available on {dd}. {ask}"
    else:
        line_t = (f"I've got the following available on {dd}:\n\n"
                  + "\n".join(f"    {q}x {pr}" for q, pr in items) + f"\n\n{ask}")
        line_h = (f"I've got the following available on {dd}:<br><br>"
                  + "".join(f"&nbsp;&nbsp;&nbsp;&nbsp;{q}x {_html.escape(pr)}<br>" for q, pr in items)
                  + f"<br>{ask}")
    greet = f"Hi {name}," if name else "Hi,"
    greet_h = f"Hi {_html.escape(name)}," if name else "Hi,"
    message = f"{greet}\n\n{line_t}\n\n{QUESTIONS}"
    text = f"{message}\n\n\n{SIGNATURE}"
    q_html = _html.escape(QUESTIONS).replace("\n", "<br>").replace("    ", "&nbsp;&nbsp;&nbsp;&nbsp;")
    html = ('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1f1f1f;">'
            f"{greet_h}<br><br>{line_h}<br><br>{q_html}<br><br>{SIGNATURE_HTML}</div>")
    return text, html, message


def html_from_message(message):
    """Rebuild the branded HTML email from an (edited) plain-text message.
    The signature block - bolds, red strapline, QR - is appended untouched."""
    body = _html.escape(message).replace("\n", "<br>").replace("    ", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return ('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1f1f1f;">'
            f"{body}<br><br>{SIGNATURE_HTML}</div>")


def _attach_qr(mail):
    if not os.path.exists(QR_PATH):
        return
    try:
        att = mail.Attachments.Add(QR_PATH)
        pa = att.PropertyAccessor
        pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", "qrcode")   # content-id
        pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x7FFE000B", True)        # hide from attach list
    except Exception:
        pass

# ---------- helpers ----------
def clean(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()

def area(pc):
    m = re.match(r"\s*([A-Za-z]{1,2})", str(pc or ""))
    return m.group(1).upper() if m else "?"

def email_of(s):
    m = re.search(r"[\w.\-+]+@[\w.\-]+", str(s or ""))
    return m.group(0) if m else None

# leading words that are never a real first name - free-text notes ("This order
# ..."), stop-words, or generic mailboxes. When the contact field starts with one
# of these we greet from the email address instead ("Hi Anthony," not "Hi This,").
_NON_NAMES = {
    "this", "that", "these", "the", "to", "dear", "hi", "hello", "team", "and",
    "for", "with", "tbc", "na", "none", "nil", "site", "contact", "delivery",
    "order", "email", "info", "admin", "enquiries", "sales", "transport",
    "depot", "office", "logistics", "planner", "yard",
}

def _plausible_name(tok):
    """A token that could actually be someone's first name: letters only (no @,
    digits or punctuation), at least two chars, not a stop-word/mailbox word."""
    t = str(tok or "").strip().lower()
    return t.isalpha() and len(t) >= 2 and t not in _NON_NAMES

def firstname(s):
    """First name for the greeting. Prefer a real name from the contact field;
    if its leading word isn't a plausible name (free-text like 'This order...',
    a stop-word, an address/number, or a single letter) fall back to the email
    local part (anthony.clay -> Anthony). Empty when nothing usable, so the
    greeting falls back to a plain 'Hi,'."""
    field = str(s or "")
    nm = re.split(r"\s+email:", field)[0].strip()
    parts = nm.split()
    if parts and _plausible_name(parts[0]):
        return parts[0].capitalize()
    em = email_of(field)
    if em:
        local = re.split(r"[._\-+]", em.split("@")[0])[0]
        if _plausible_name(local):
            return local.capitalize()
    return ""

_NUMERIC_CODE = re.compile(r"^[\d/\-.\s]+$")   # e.g. 0057/063740/0035 - internal ref, no words

def _has_words(v):
    """True if the value reads as words a recipient can understand (has letters
    and isn't just a slash-separated number like 0057/063740/0035)."""
    s = clean(v)
    return bool(re.search(r"[A-Za-z]", s)) and not _NUMERIC_CODE.match(s)

def readable_product(prod, prod_code):
    """The product wording a recipient can actually place (e.g. 'RAIL SHORT,
    56E1, 260 GRADE, 18.288M, UNDRILLED'), never the internal numeric ref. The
    Synergy extract keeps the words in Product/Service Code; BS batch files keep
    them in Product/Description - so pick whichever of the two reads as words
    rather than trusting a fixed column."""
    a, b = clean(prod), clean(prod_code)
    if _has_words(a) and not _has_words(b):
        return a
    if _has_words(b) and not _has_words(a):
        return b
    return a or b   # both or neither look like words - keep the primary column

def base_order(o):
    return str(o).split("-")[0]

def fdate(d):
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d or "")


def _is_future(dd):
    """True if a 'dd/mm/yyyy' delivery date is today or later. Guards against
    emailing a contact to arrange a delivery whose date has already passed
    (which happens when an old batch is swept up). Fails OPEN - an unparseable
    or blank date returns True - so a genuine order is never silently dropped."""
    from datetime import datetime, date
    try:
        d = datetime.strptime(str(dd).strip()[:10], "%d/%m/%Y").date()
        return d >= date.today()
    except Exception:
        return True

def is_supplier_rail(order):
    return str(order or "")[:1].isalpha()   # order number starts with a letter

def is_stoneblower(*descs):
    """Stoneblower orders are off limits - booked in, never emailed (same rule as
    supplier rails). Detected by 'STONEBLOWER' in the product code/description;
    letters-only compare so 'stone blower' / 'stone-blower' spacing all match."""
    for d in descs:
        s = "".join(ch for ch in str(d or "").lower() if ch.isalpha())
        if "stoneblow" in s:
            return True
    return False


def is_loose_ballast(*descs):
    """Loose (tipped/bulk) ballast - needs a tipper, so Delali wants it flagged +
    prioritised. Description reads 'BALLAST ... - Loose' (vs '1 tonne bags' etc.)."""
    for d in descs:
        dl = str(d or "").lower()
        if "ballast" in dl and "loose" in dl:
            return True
    return False

def product_type(desc):
    d = (desc or "").upper()
    for key, label in (("SLEEPER", "sleepers"), ("BALLAST", "ballast"), ("RAIL", "rails"),
                       ("SWITCH", "S&C"), ("CROSSING", "S&C"), ("PAD", "pads")):
        if key in d:
            return label
    w = (desc or "").split()
    return w[0].lower() if w else "items"

def _qty(q):
    try:
        return int(float(q))
    except Exception:
        return 0

def product_summary(items):
    """items = list of (qty, description) -> readable string like '51x sleepers, 40x ballast'."""
    agg = OrderedDict()
    for qty, desc in items:
        t = product_type(desc)
        agg[t] = agg.get(t, 0) + _qty(qty)
    return ", ".join(f"{q}x {t}" for t, q in agg.items())


# ---------- consolidation (share-a-vehicle) suggestions ----------
def _outward(pc):
    pc = str(pc or "").strip().upper()
    i = pc.find(" ")
    return (pc[:i] if i > 0 else pc).strip()   # "DN16 1BP" -> "DN16"


def _pc_area(ow):
    m = re.match(r"[A-Z]+", ow or "")
    return m.group(0) if m else ow            # "DN16" -> "DN"


def consolidation_candidates(groups):
    """Two jobs delivering on the SAME DAY to the same postcode district (or a
    neighbouring district in the same area) are a chance to share one vehicle.
    Returns [(date, area, [group,...])] - 2+ DISTINCT delivery sites in the same
    area on the same future day, soonest first. Advisory only: the planner still
    checks the truck has space and the route works."""
    buckets = OrderedDict()   # (date, area) -> {site_key: group}
    for e in groups:
        if not _is_future(e.get("date")):
            continue
        # supplier rails are booked separately (never a shared road vehicle) -
        # exclude the whole job from BOTH ends of any suggested pairing.
        if any(is_supplier_rail(o) for o in e.get("orders", [])):
            continue
        # a FULL ballast load has no spare capacity, so no point consolidating.
        # Trucks: small=10 bags, large=20 - so any ballast qty that's a multiple
        # of 10 (10/20/30/40...) fills whole trucks exactly. Non-multiples leave a
        # part-truck with room, so they stay eligible.
        if e.get("only_ballast") and e.get("ballast", 0) > 0 and e.get("ballast", 0) % 10 == 0:
            continue
        ow = _outward(e.get("postcode"))
        if not ow:
            continue
        site_key = (str(e.get("site", "")).strip().lower(), ow)
        buckets.setdefault((e["date"], _pc_area(ow)), OrderedDict()).setdefault(site_key, e)
    out = [(date, area, list(sites.values()))
           for (date, area), sites in buckets.items() if len(sites) >= 2]
    out.sort(key=lambda t: (waitlist.days_until(t[0]) if waitlist.days_until(t[0]) is not None else 10**9))
    return out

# ---------- outlook ----------
def get_ns():
    import win32com.client
    return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")

def dhl_store(ns):
    for i in range(1, ns.Folders.Count + 1):
        f = ns.Folders.Item(i)
        if f.Name.lower() == DHL_SMTP:
            return f
    return None

def sub(folder, name):
    for i in range(1, folder.Folders.Count + 1):
        c = folder.Folders.Item(i)
        if c.Name.strip().lower() == name.strip().lower():
            return c
    return None

def find_inbox_extracts(ns, limit=300):
    """ALL Haulier Extracts sitting in the Inbox root (not filed subfolders) -
    unprocessed extracts live in the Inbox; there can be several per day.
    Returns [(path, filename)] newest first."""
    dhl = dhl_store(ns)
    inbox = sub(dhl, "Inbox")
    if inbox is None:
        return []
    items = inbox.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    found, seen, n = [], set(), 0
    for it in items:
        n += 1
        if n > limit:
            break
        try:
            subj = str(getattr(it, "Subject", "") or "")
            for j in range(1, it.Attachments.Count + 1):
                att = it.Attachments.Item(j)
                fn = str(att.FileName)
                if is_wanted_extract(fn, subj) and fn not in seen:
                    seen.add(fn)
                    path = os.path.join(HERE, f"_inbox_extract_{len(found)}.xlsx")
                    att.SaveAsFile(path)
                    found.append((path, fn))
        except Exception:
            pass
    return found


def find_synergy_upload(ns, days=3, bs_days=30, exclude=()):
    """Safety net for the Synergy Upload folder (Inbox > ADHOC > Synergy Upload).
    Both the normal Haulier Extract AND BS batch files sometimes get filed there
    before the daily run reads the Inbox root - Delali may drop today's emails in
    himself - so a root-only scan can miss them. That folder is ALSO the long-term
    archive (dozens of old extracts), so we only take RECENT files: a normal
    extract within `days` days (catch what you just filed), and a BS batch within
    the wider `bs_days` window (BS is sporadic and must never be missed). The
    tracker de-dup downstream stops an already-drafted batch being drafted twice,
    and `exclude` skips files already found in the Inbox root."""
    from datetime import datetime, timedelta
    dhl = dhl_store(ns)
    inbox = sub(dhl, "Inbox")
    adhoc = sub(inbox, "ADHOC") if inbox else None
    folder = sub(adhoc, "Synergy Upload") if adhoc else None
    if folder is None:
        return []
    now = datetime.now()
    hard_cutoff = now - timedelta(days=max(days, bs_days))
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    found, seen, n = [], set(), 0
    for it in items:
        n += 1
        if n > 400:
            break
        age_days = None
        try:
            rt = it.ReceivedTime
            if rt is not None:
                rtn = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute)
                if rtn < hard_cutoff:
                    break   # newest-first: past the widest window -> all older
                age_days = (now - rtn).days
        except Exception:
            pass
        try:
            subj = str(getattr(it, "Subject", "") or "")
            for j in range(1, it.Attachments.Count + 1):
                att = it.Attachments.Item(j)
                fn = str(att.FileName)
                if not is_wanted_extract(fn, subj) or fn in seen or fn in exclude:
                    continue
                low = fn.lower()
                is_bs = any(m in low or m in subj.lower() for m in BS_MARKERS)
                if age_days is not None and age_days > (bs_days if is_bs else days):
                    continue   # too old for its type (BS gets the wider window)
                seen.add(fn)
                path = os.path.join(HERE, f"_syn_up_{len(found)}.xlsx")
                att.SaveAsFile(path)
                found.append((path, fn))
        except Exception:
            pass
    return found


def _already_done_orders():
    """Base order numbers already drafted/emailed, from the tracker. Lets the
    daily run skip a batch it has already handled, so re-running commit - or the
    Synergy Upload safety net overlapping the Inbox root - never produces a
    duplicate draft. Fails open (empty set) so it can only ever suppress a true
    duplicate, never hide a genuinely new order."""
    try:
        d = tracker.load()
    except Exception:
        return set()
    done = set()
    for r in d.get("records", []):
        for o in r.get("orders", []):
            done.add(str(o).strip())
    return done


PENDING_BATCH = os.path.join(HERE, "_pending_batch.json")


def save_pending_batch(emails):
    """Write today's to-send emails to a review file so the dashboard can show
    the whole batch before anything sends (mirrors send_order's _pending_email).
    Nothing is sent or drafted here."""
    slim = [{k: e.get(k) for k in ("to", "cc", "name", "subject", "message", "date",
                                   "orders", "product_codes", "materials", "site",
                                   "postcode", "source", "loose_ballast")} for e in emails]
    with open(PENDING_BATCH, "w", encoding="utf-8") as f:
        json.dump(slim, f, indent=1, default=str)
    return slim


# A reply you send in the order's own thread to say it's booked in. You always
# reply in-thread, so the order number is already in the subject and the order
# is suppressed anyway - these markers only decide whether we LABEL the skip
# "booked in" (your reply) vs "already contacted" (the tool's first outreach).
_REPLY_PREFIXES = ("re:", "re ", "fw:", "fwd:", "fw ", "aw:", "sv:")
# The exact wording you use to book an order in, e.g.
# "This order has been arranged with Lawsons." Only this phrase counts as a
# booking - not the looser words (booked/sorted/confirmed) we used before.
_BOOKED_PHRASES = ("this order has been arranged with",)
# A MAN reference (e.g. MAN-01563625) means you've arranged it with a haulier -
# that's a booking on its own, even if you never type the phrase above.
_MAN_RE = re.compile(r"\bMAN[-\s]?\d{5,}", re.I)
_QUOTE_MARKERS = ("-----original message-----", "\nfrom:", "\r\nfrom:", "\nsent:",
                  "________", " wrote:", "on behalf of")


def _reply_top(body):
    """Just the text you typed, above the quoted original - so a booking phrase
    in the quoted thread (e.g. the tool's own 'can this be booked in?') never
    counts as your confirmation."""
    low = str(body or "").lower()
    cut = len(low)
    for m in _QUOTE_MARKERS:
        i = low.find(m)
        if 0 <= i < cut:
            cut = i
    return low[:cut]


def _booked_ref(body):
    """The MAN booking reference in your reply (e.g. MAN-01563625), if any -
    surfaced on the 'booked in' line so you can see which ref was recognised."""
    m = _MAN_RE.search(_reply_top(body))
    return m.group(0).upper().replace(" ", "-") if m else ""


def _looks_booked(subject, body):
    """True when a Sent item is your booking confirmation: your typed text (above
    any quoted original) has the booking phrase OR a MAN reference. You send these
    as a FRESH email with the order number in the subject just as often as an
    in-thread reply, so we do NOT require a RE:/FW: subject. Sent Items only."""
    top = _reply_top(body)
    return any(p in top for p in _BOOKED_PHRASES) or bool(_MAN_RE.search(top))


def _to_tracker_dt(when):
    """Convert a 'dd/mm/YYYY HH:MM' Sent-item time to the tracker's
    'YYYY-mm-dd HH:MM' so business-day chasing counts from the real send date."""
    from datetime import datetime as _dt
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return _dt.strptime(str(when).strip(), fmt).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return None


def enrol_by_hand(skipped_sent):
    """Put the orders you emailed the delivery contact YOURSELF (found in Sent
    Items, not via the tool) onto the tracker so they get chased like the rest.
    Idempotent, dated from your actual send time. Drafts-only matches are ignored
    - nothing was sent, so there's no one to chase. Returns how many were newly
    enrolled."""
    existing = {r["id"] for r in tracker.load().get("records", [])}
    n = 0
    for e in skipped_sent:
        ev = next((v for v in e.get("_seen", {}).values() if v.get("where") == "Sent Items"), None)
        if not ev:
            continue
        rid = tracker._key(e["orders"], e["date"])
        if rid in existing:
            continue
        tracker.log(orders=e["orders"], to=e.get("to", ""), name=e.get("name", ""),
                    product_codes=e.get("product_codes", []), materials=e.get("materials", ""),
                    site=e.get("site", ""), postcode=e.get("postcode", ""),
                    delivery_date=e["date"], source="by hand", status="sent",
                    emailed_at=_to_tracker_dt(ev.get("when")), only_if_new=True,
                    kind="delivery", orig_entryid=ev.get("entryid"))
        existing.add(rid)
        n += 1
    return n


def find_already_emailed(ns, order_numbers, limit=500):
    """For each order number, look in the DHL Sent Items and Drafts for a mail
    that already references it (subject or body). This catches emails you sent
    BY HAND, which the tracker never sees - so the tool never asks you to email
    someone you've already contacted. A Sent match that is your in-thread reply
    is flagged booked=True (you've booked it in). Returns
    {order: {"where","when","to","booked"}}."""
    targets = {str(o).strip() for o in order_numbers if str(o).strip()}
    if not targets:
        return {}
    dhl = dhl_store(ns)
    found = {}
    for label, folder in (("Sent Items", sub(dhl, "Sent Items")), ("Drafts", sub(dhl, "Drafts"))):
        if folder is None:
            continue
        items = folder.Items
        try:
            items.Sort("[SentOn]" if label == "Sent Items" else "[LastModificationTime]", True)
        except Exception:
            pass
        n = 0
        for it in items:
            n += 1
            if n > limit:
                break
            try:
                subj = str(it.Subject or "")
                if re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", subj, flags=re.I).lower().startswith("collection "):
                    continue   # a collection request to a supplier is NOT a delivery email
                body = str(getattr(it, "Body", "") or "")
                blob = subj + " " + body[:6000]
                booked = (label == "Sent Items") and _looks_booked(subj, body)
                ref = _booked_ref(body) if booked else ""
                eid = str(getattr(it, "EntryID", "") or "")
                try:
                    when = (it.SentOn if label == "Sent Items"
                            else it.LastModificationTime).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    when = "?"
                to = str(getattr(it, "To", "") or "")[:40]
                for o in targets:
                    if o not in blob:
                        continue
                    if o not in found:
                        found[o] = {"where": label, "when": when, "to": to,
                                    "booked": booked, "ref": ref, "entryid": eid}
                    elif booked and not found[o].get("booked"):
                        # an EARLIER email booked this order in - upgrade the record so
                        # a later chase/forward (scanned first, newest) can't mask it
                        found[o].update(booked=True, ref=ref, entryid=eid,
                                        where=label, when=when)
            except Exception:
                pass
            # stop early only once every order is found AND known booked
            if len(found) == len(targets) and all(v.get("booked") for v in found.values()):
                break
        if len(found) == len(targets) and all(v.get("booked") for v in found.values()):
            break
    return found


def _pc_norm(pc):
    return re.sub(r"\s+", "", str(pc or "")).upper()   # "NG9 2EY" -> "NG92EY"


def find_emailed_deliveries(ns, groups, limit=500):
    """Delivery-level dedup: has a delivery already been emailed for this
    contact + postcode + date, under ANY order number? Catches a NEW order that
    joins a delivery slot already arranged under a different (maybe now aged-out)
    order. Matched on recipient + postcode + delivery date - all three, so it
    never suppresses a genuinely different delivery. Returns
    {(to, pc_norm, date): {"where","when","to","booked","ref"}}."""
    want = {}
    for e in groups:
        to = (e.get("to") or "").strip().lower()
        pc = _pc_norm(e.get("postcode"))
        date = str(e.get("date") or "").strip()
        if to and pc and date:
            want[(to, pc, date)] = e
    if not want:
        return {}
    dhl = dhl_store(ns)
    hit = {}
    for label, folder in (("Sent Items", sub(dhl, "Sent Items")), ("Drafts", sub(dhl, "Drafts"))):
        if folder is None:
            continue
        items = folder.Items
        try:
            items.Sort("[SentOn]" if label == "Sent Items" else "[LastModificationTime]", True)
        except Exception:
            pass
        n = 0
        for it in items:
            n += 1
            if n > limit:
                break
            try:
                subj = str(it.Subject or "")
                body = str(getattr(it, "Body", "") or "")
                blob = subj + " " + body[:6000]
                blobn = re.sub(r"\s+", "", blob).upper()
                low = blob.lower()
                # cheap first: which wanted deliveries have this postcode + date?
                # a slot already hit can still be UPGRADED to booked by an older
                # email - otherwise a newer chase masks the booking beneath it
                cands = [(k, e) for k, e in want.items()
                         if not (k in hit and hit[k].get("booked"))
                         and k[1] in blobn and (k[2] in blob or k[2][:5] in blob)]
                if not cands:
                    continue
                rcpts = set()
                try:
                    for j in range(1, it.Recipients.Count + 1):
                        try:
                            a = str(it.Recipients.Item(j).Address or "")
                            if "@" in a:
                                rcpts.add(a.lower())
                        except Exception:
                            pass
                except Exception:
                    pass
                for k, e in cands:
                    if not (k[0] in rcpts or k[0] in low):
                        continue          # not sent to this delivery contact
                    try:
                        when = (it.SentOn if label == "Sent Items"
                                else it.LastModificationTime).strftime("%d/%m/%Y %H:%M")
                    except Exception:
                        when = "?"
                    booked = (label == "Sent Items") and _looks_booked(subj, body)
                    if k not in hit:
                        hit[k] = {"where": label, "when": when,
                                  "to": str(getattr(it, "To", "") or "")[:40],
                                  "booked": booked, "ref": _booked_ref(body) if booked else ""}
                    elif booked and not hit[k].get("booked"):
                        hit[k].update(booked=True, ref=_booked_ref(body),
                                      where=label, when=when)
            except Exception:
                pass
            # stop early only once every slot is found AND known booked
            if len(hit) == len(want) and all(v.get("booked") for v in hit.values()):
                break
        if len(hit) == len(want) and all(v.get("booked") for v in hit.values()):
            break
    return hit


def find_collection_sent(ns, orders, limit=500):
    """Orders that already have a collection request sent/drafted (subject starts
    'Collection', contains the order number) - so a collection email to the
    supplier isn't sent twice, independently of the delivery email."""
    targets = {str(o).strip() for o in orders if str(o).strip()}
    if not targets:
        return set()
    dhl = dhl_store(ns)
    hit = set()
    for label, folder in (("Sent Items", sub(dhl, "Sent Items")), ("Drafts", sub(dhl, "Drafts"))):
        if folder is None:
            continue
        items = folder.Items
        try:
            items.Sort("[SentOn]" if label == "Sent Items" else "[LastModificationTime]", True)
        except Exception:
            pass
        n = 0
        for it in items:
            n += 1
            if n > limit:
                break
            try:
                subj = str(it.Subject or "")
                if not re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", subj, flags=re.I).lower().startswith("collection "):
                    continue
                blob = subj + " " + str(getattr(it, "Body", "") or "")[:3000]
                for o in (targets - hit):
                    if o in blob:
                        hit.add(o)
            except Exception:
                pass
            if len(hit) == len(targets):
                break
        if len(hit) == len(targets):
            break
    return hit

# ---------- core ----------
def load_rows(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    def ci(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None
    C = dict(
        order=ci("customer order no"), dpc=ci("d postcode"), dcon=ci("d contact name"),
        prod=ci("product / service code"), prod_code=ci("product / description"),
        qty=ci("product qty"), date=ci("delivery date"),
        daddr=ci("d address1", "d address 1"),
        csite=ci("site name - collection"),
        instr=ci("shipping instructions", "delivery instructions"),
    )
    return rows[1:], C

def build_emails(rows, C, source=""):
    """Single-file convenience wrapper around build_emails_multi."""
    return build_emails_multi([(rows, C, source)])


_SPECIAL_SUPPLIERS = CFG.get("special_collection_suppliers", {})


def special_supplier(name):
    """If a collection site is a collect-first supplier (Anderton/BCM/Trough Tec)
    return (supplier_name, {to, cc}); else (None, None)."""
    n = str(name or "").lower()
    for sup, cfg in _SPECIAL_SUPPLIERS.items():
        if any(str(m).lower() in n for m in cfg.get("match", [])):
            return sup, cfg
    return None, None


_HS_RE = re.compile(r"BPA Release Number:\s*(HS\d+(?:-\d+)*)", re.I)


def _hs_number(instr):
    """The release/HS number Anderton uses to locate goods, from the Shipping
    Instructions column ('BPA Release Number: HS6365227-12-1')."""
    m = _HS_RE.search(str(instr or ""))
    return m.group(1) if m else ""


def _collection_body(lines):
    """Collection-request body for a supplier: the details we need to book
    transport, then each order line with its product code + release/HS number."""
    asks = CFG.get("collection_query", {}).get("asks",
             ["pallet size", "weight", "height", "double-stacked", "collection time slot"])
    out = ["Hi,", "",
           "Please could you help us arrange collection of the below? For each item we need:", ""]
    for a in asks:
        a = str(a)
        if "double" in a.lower():
            a = "whether it's double-stacked (so we can send a curtain-slider)"
        out.append("    - " + a)
    out += ["", "Items (with the release / HS number so you can locate each):"]
    for o, pc, hs in lines:
        parts = [str(o)]
        if pc:
            parts.append(pc)
        if hs:
            parts.append(hs)
        out.append("    " + "  -  ".join(parts))
    out += ["", "Once we have those we'll get transport booked in. Many thanks."]
    return "\n".join(out)


def build_emails_multi(files):
    """files = [(rows, C, source)]. Combines ALL extracts, de-duplicates
    identical rows appearing in more than one file (an 'additional' extract
    repeating an order must not double quantities), then groups by
    contact+site+date as usual."""
    groups = OrderedDict()
    skipped_rails = 0
    skipped_stoneblower = 0
    skipped_region = set()
    seen_rows = set()
    for rows, C, source in files:
        for r in rows:
            order = r[C["order"]]
            if order is None:
                continue
            dup = (str(order), clean(r[C["prod"]]), str(r[C["qty"]]),
                   fdate(r[C["date"]]), clean(r[C["dpc"]]))
            if dup in seen_rows:
                continue
            seen_rows.add(dup)
            if is_supplier_rail(order):
                skipped_rails += 1
                continue
            pcode = r[C["prod_code"]] if C.get("prod_code") is not None else ""
            if is_stoneblower(r[C["prod"]], pcode):
                skipped_stoneblower += 1
                continue
            key = (email_of(r[C["dcon"]]), clean(r[C["dpc"]]), fdate(r[C["date"]]))
            groups.setdefault(key, []).append((r, C, source))
    emails = []
    collection_emails = []
    for (em, dpc, dd), bundle in groups.items():
        if area(dpc) not in AREAS:
            skipped_region.add((dpc, dd))
            continue
        r0, C0, _ = bundle[0]
        orders = sorted(set(base_order(r[C["order"]]) for r, C, _ in bundle))
        subject = f"{' / '.join(orders)} {clean(r0[C0['daddr']])} {dpc}"
        items = [(r[C["qty"]], readable_product(
                    r[C["prod"]],
                    r[C["prod_code"]] if C.get("prod_code") is not None else ""))
                 for r, C, _ in bundle]
        ptypes = {product_type(d) for _, d in items}
        ballast_bags = sum(_qty(q) for q, d in items if product_type(d) == "ballast")
        nm = firstname(r0[C0['dcon']])
        text, html, message = _bodies(nm, items, dd)
        pcodes = sorted({clean(r[C['prod_code']]) for r, C, _ in bundle
                         if C['prod_code'] is not None and r[C['prod_code']]})
        sources = " + ".join(sorted({s for _, _, s in bundle if s}))
        emails.append(dict(to=em, cc="", name=nm, subject=subject, body=text, html=html,
                           message=message, items=len(items), date=dd, orders=orders,
                           product_codes=pcodes, materials=product_summary(items),
                           ballast=ballast_bags, only_ballast=(ptypes == {"ballast"}),
                           loose_ballast=any(is_loose_ballast(d) for _, d in items),
                           site=clean(r0[C0['daddr']]), postcode=dpc, source=sources))
        # collect-first: a SEPARATE collection request to Anderton/BCM/Trough Tec,
        # sent alongside the delivery email (both go out together).
        sup = supcfg = None
        csite_name = ""
        for r, C, _ in bundle:
            cs = str(r[C["csite"]] or "").strip() if C.get("csite") is not None else ""
            if cs:
                s, cfg = special_supplier(cs)
                if s:
                    sup, supcfg, csite_name = s, cfg, cs
                    break
        if sup:
            clines, seenl = [], set()
            for r, C, _ in bundle:
                o = base_order(r[C["order"]])
                # the readable product DESCRIPTION (e.g. "LID FOR C/1/23TTRW") -
                # NOT the numeric identifier, which means nothing to the supplier.
                # readable_product picks the words column whichever file it's from.
                desc = readable_product(
                    r[C["prod"]] if C.get("prod") is not None else "",
                    r[C["prod_code"]] if C.get("prod_code") is not None else "")
                hs = _hs_number(r[C["instr"]]) if C.get("instr") is not None else ""
                if (o, desc, hs) not in seenl:
                    seenl.add((o, desc, hs))
                    clines.append((o, desc, hs))
            cmsg = _collection_body(clines)
            town = csite_name.split(" - ")[-1].strip().title() if " - " in csite_name else ""
            csubj = f"Collection {' / '.join(orders)} - {sup}" + (f" ({town})" if town else "")
            collection_emails.append(dict(
                to="; ".join(supcfg.get("to", [])), cc="; ".join(supcfg.get("cc", [])),
                name=sup, subject=csubj[:150], body=cmsg, html=html_from_message(cmsg),
                message=cmsg, items=len(clines), date=dd, orders=orders,
                product_codes=sorted({d for _, d, _ in clines if d}),
                materials="collection details", site=csite_name,
                postcode=dpc, source=sources, kind="collection", supplier=sup))
    return emails, collection_emails, skipped_rails, skipped_stoneblower, len(skipped_region)

def create_drafts(ns, emails):
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    acct = None
    for a in ns.Accounts:
        if str(a.SmtpAddress).lower() == DHL_SMTP:
            acct = a
            break
    drafts = acct.DeliveryStore.GetDefaultFolder(16) if acct else None  # 16 = Drafts
    made = 0
    for e in emails:
        if not e["to"]:
            print(f"   ! skipped (no recipient found): {e['subject']}")
            continue
        m = outlook.CreateItem(0)  # 0 = MailItem
        m.To = e["to"]
        m.Subject = e["subject"]
        _attach_qr(m)
        m.HTMLBody = e.get("html") or e["body"]
        try:
            m._oleobj_.Invoke(64209, 0, 8, 0, acct)   # SendUsingAccount, reliably
        except Exception:
            try:
                m.SendUsingAccount = acct
            except Exception:
                pass
        m.Save()
        if drafts is not None:
            m.Move(drafts)
        tracker.log(orders=e.get("orders", []), to=e["to"], name=e.get("name", ""),
                    product_codes=e.get("product_codes", []), materials=e.get("materials", ""),
                    site=e.get("site", ""), postcode=e.get("postcode", ""), delivery_date=e["date"],
                    source=e.get("source", ""), status="drafted")
        made += 1
    return made

def week_window(which, today=None):
    """(Monday, Sunday) dates for an upcoming week. 'next' = the coming Mon-Sun,
    'after' = the week after that. Week-commencing, same convention as the rail
    plan's 'wc DD.MM'."""
    from datetime import date as _date, timedelta as _td
    today = today or _date.today()
    this_mon = today - _td(days=today.weekday())
    start = this_mon + _td(days=14 if which == "after" else 7)
    return start, start + _td(days=6)


# ---------- entry ----------
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    arg2 = sys.argv[2] if len(sys.argv) > 2 else None
    # `week next` / `week after` -> a targeted batch for an upcoming week (arg2 is
    # the week, not a file). Every other mode treats arg2 as an optional path.
    week = path = None
    week_commit = False
    if mode == "week":
        week = (arg2 or "next").strip().lower()
        week = week if week in ("next", "after") else "next"
        # `week next commit` -> create Drafts (local dashboard); otherwise a
        # reviewable pending batch (cloud dashboard preview & send).
        week_commit = len(sys.argv) > 3 and sys.argv[3].strip().lower() == "commit"
    else:
        path = arg2
    ns = None
    if path is None:
        ns = get_ns()
        extracts = find_inbox_extracts(ns)
        root_names = {fn for _, fn in extracts}
        syn_extras = find_synergy_upload(ns, days=3, bs_days=30, exclude=root_names)
        all_files = extracts + syn_extras
        if not all_files:
            print("No Haulier Extracts / BS batches in the Inbox or the Synergy Upload folder."); return
        print(f"Found {len(extracts)} extract(s) in the Inbox"
              + (f" + {len(syn_extras)} more in the Synergy Upload folder" if syn_extras else "") + ":")
        for _, fn in all_files:
            print(f"  - {fn}")
        print()
        files = []
        for p, fn in all_files:
            rows, C = load_rows(p)
            files.append((rows, C, fn))
    else:
        print(f"Using file: {path}\n")
        rows, C = load_rows(path)
        files = [(rows, C, os.path.basename(path))]

    total_rows = sum(len(rows) for rows, _, _ in files)
    emails, collection_emails, rails, stoneblowers, region = build_emails_multi(files)
    cons = consolidation_candidates(emails)   # same-day, same/near area -> share a vehicle?
    coll_kept = list(collection_emails)       # default (passed-file): send them all
    skipped_done, skipped_sent, skipped_booked, skipped_past, waitlisted = [], [], [], [], []
    other_week = []
    target = week_window(week) if week else None
    if path is None:   # daily run: a file passed by hand is always shown in full
        done = _already_done_orders()
        all_orders = {str(o).strip() for e in emails for o in e["orders"]}
        already = find_already_emailed(ns, all_orders)
        deliv_hit = find_emailed_deliveries(ns, emails)   # delivery-level dedup (any order#)
        lead = waitlist.LEAD_DAYS
        kept = []
        for e in emails:
            ords = [str(o).strip() for o in e["orders"]]
            seen = {o: already[o] for o in ords if o in already}
            dkey = ((e.get("to") or "").strip().lower(), _pc_norm(e.get("postcode")),
                    str(e.get("date") or "").strip())
            if not seen and dkey in deliv_hit:
                seen = {"_delivery": deliv_hit[dkey]}   # same delivery emailed under a different order#
            n = waitlist.days_until(e["date"])
            if ords and all(o in done for o in ords):
                skipped_done.append(e)
            elif seen:
                # a group is ONE email to one contact for one delivery (same
                # contact+site+date). If ANY of its orders was already emailed - OR
                # the delivery itself was already emailed under a different order
                # number - it's arranged, so skip it. A new order joining that slot
                # must not re-trigger the email.
                e["_seen"] = seen
                if any(v.get("booked") for v in seen.values()):
                    skipped_booked.append(e)   # your in-thread reply = booked in
                else:
                    skipped_sent.append(e)
            elif not _is_future(e["date"]):
                skipped_past.append(e)
            elif target is not None:
                # week mode: send everything DELIVERING in the chosen week (pull it
                # forward past the 14-day hold); park anything outside that week.
                dd = waitlist.parse_date(e["date"])
                if dd is not None and target[0] <= dd <= target[1]:
                    kept.append(e)
                else:
                    other_week.append(e)
            elif n is not None and n > lead:
                # too far ahead to email yet - hold on the wait list, auto-sent later
                waitlisted.append(e)
            else:
                kept.append(e)
        emails = kept
        # collection requests to Anderton/BCM/Trough Tec - sent ALONGSIDE the
        # delivery email; deduped separately (a Collection email already sent, or
        # the delivery date already passed).
        coll_sent = (find_collection_sent(ns, {o for e in collection_emails for o in e["orders"]})
                     if collection_emails else set())
        coll_kept = [e for e in collection_emails
                     if _is_future(e["date"]) and not (e["orders"] and all(o in coll_sent for o in e["orders"]))]
        enrolled = enrol_by_hand(skipped_sent)   # track by-hand emails so they get chased too
        if enrolled:
            print(f"(tracker: enrolled {enrolled} order(s) you emailed by hand, so they get chased)")
        if mode in ("commit", "waitscan"):
            added = sum(1 for e in waitlisted if waitlist.add(e))
            if added:
                print(f"(wait list: {added} far-ahead order(s) held, will auto-send ~{lead} days before delivery)")
    if target is not None:
        lbl = "week after" if week == "after" else "next week"
        print(f"Sending for week commencing {target[0].strftime('%d.%m.%Y')} "
              f"to {target[1].strftime('%d.%m.%Y')} ({lbl})"
              + (f" | {len(other_week)} order(s) outside this week left for later" if other_week else "")
              + "\n")
    print(f"Rows: {total_rows} | Region 2 emails: {len(emails)} | "
          f"supplier-rails skipped: {rails} | stoneblowers skipped: {stoneblowers} | "
          f"out-of-region groups skipped: {region}"
          + (f" | collection requests: {len(coll_kept)}" if coll_kept else "")
          + (f" | wait-listed (too far ahead): {len(waitlisted)}" if waitlisted else "")
          + (f" | booked-in skipped: {len(skipped_booked)}" if skipped_booked else "")
          + (f" | already-emailed skipped: {len(skipped_sent)}" if skipped_sent else "")
          + (f" | already-done skipped: {len(skipped_done)}" if skipped_done else "")
          + (f" | past-date skipped: {len(skipped_past)}" if skipped_past else "") + "\n")
    if cons:
        print("CONSOLIDATION - same-day deliveries near each other (could share a vehicle - check space/route):")
        for date, area, gs in cons:
            outs = {_outward(g["postcode"]) for g in gs}
            tag = "same district" if len(outs) == 1 else f"nearby districts in {area} - check the hop"
            print(f"   * {date} | {area} area ({tag}):")
            for g in gs:
                print(f"        {' / '.join(g['orders'])}  ->  {clean(g.get('site', ''))} {g['postcode']} [{_outward(g['postcode'])}]")
        print()
    if waitlisted:
        print(f"Region 2 orders WAIT-LISTED - too far ahead, will auto-send ~{waitlist.LEAD_DAYS} days before delivery:")
        for e in waitlisted:
            n = waitlist.days_until(e["date"])
            print(f"   ~ {' / '.join(e['orders'])} | {e['site']} {e['postcode']} | deliver {e['date']} "
                  f"(in {n}d) -> sends ~{n - waitlist.LEAD_DAYS}d from now")
        print()
    if skipped_booked:
        print("Region 2 orders NOT emailed - you REPLIED in the thread (booked in):")
        for e in skipped_booked:
            ev = next((v for v in e["_seen"].values() if v.get("booked")),
                      next(iter(e["_seen"].values())))
            refstr = f" ({ev['ref']})" if ev.get("ref") else ""
            print(f"   * {' / '.join(e['orders'])} | {e['site']} {e['postcode']} | "
                  f"you replied {ev['when']} to {ev['to']} - booked in{refstr}")
        print()
    if skipped_sent:
        print("Region 2 orders NOT emailed - you've ALREADY contacted them (found in Sent/Drafts):")
        for e in skipped_sent:
            ev = next(iter(e["_seen"].values()))
            print(f"   > {' / '.join(e['orders'])} | {e['site']} {e['postcode']} | "
                  f"already {ev['where']} {ev['when']} to {ev['to']}")
        print()
    if skipped_past:
        print("Region 2 orders NOT emailed - delivery date already passed (check none still need action):")
        for e in skipped_past:
            print(f"   x {' / '.join(e['orders'])} | {e['site']} {e['postcode']} | {e['date']}")
        print()
    if skipped_done:
        print("Region 2 orders skipped - already drafted/sent by the tool before:")
        for e in skipped_done:
            print(f"   = {' / '.join(e['orders'])} | {e['site']} {e['postcode']} | {e['date']}")
        print()
    if coll_kept:
        print("COLLECTION requests to suppliers (Anderton/BCM/Trough Tec) - sent ALONGSIDE the delivery email:")
        for e in coll_kept:
            print(f"   + TO {e['to']} | {e['subject']}")
        print()
    emails = emails + coll_kept   # collection requests ride in the same batch/send
    for e in emails:
        warn = ""
        if e.get("_seen"):
            ev = next(iter(e["_seen"].values()))
            warn = f"   <!! one of these orders was already emailed {ev['where']} {ev['when']}"
        print(f"  TO {e['to'] or '(none)':36} | {e['subject']} | {e['items']} item(s) {e['date']}{warn}")

    if mode == "commit":
        if ns is None:
            ns = get_ns()
        print("\nCreating drafts in DHL Drafts...")
        n = create_drafts(ns, emails)
        print(f"Done - {n} draft(s) created. Nothing sent.")
    elif mode == "waitscan":
        print("\nWait-list scan done - far-ahead orders captured. No drafts, nothing sent.")
    elif mode == "week" and week_commit:
        if ns is None:
            ns = get_ns()
        print("\nCreating drafts in DHL Drafts...")
        n = create_drafts(ns, emails)
        print(f"Done - {n} draft(s) created for the chosen week. Nothing sent.")
    elif mode in ("batch", "week"):
        save_pending_batch(emails)
        print(f"\nBatch ready - {len(emails)} email(s) prepared for review. Nothing sent yet.")
    else:
        print("\n(preview only - no drafts created. Run with 'commit' to create them.)")

if __name__ == "__main__":
    main()
