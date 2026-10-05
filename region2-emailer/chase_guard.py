"""The chaser's eyes: every email in the DHL mailbox since the ask, ready for
modules/chase_rules to judge.

The old reply-finder looked at the top of the Inbox only, by subject only.
Replies get filed - 33 of the 34 wrongly-chased replies were in
Inbox/Regions/Region 2/Completed - so this reads EVERY mail folder in the DHL
store (Inbox and all its subfolders, Deleted Items, Junk) plus Sent Items for
what we sent, in one pass, and hands plain dicts to the rules.

Fail closed: if the mailbox cannot be read - a folder that will not open, a
mailbox that is not connected or has stopped syncing - the caller sends
nothing. A chaser that might be wrong is worse than one a run late.

    python chase_guard.py            show what every tracker record would get, and why
"""
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from modules import chase_rules as cr   # noqa: E402

STATE = os.path.join(HERE, "_chase_state.json")    # order|contact -> replied (never re-armed by itself)
LOG = os.path.join(HERE, "_chase_log.jsonl")       # every decision, with its evidence
TEAM = os.path.join(HERE, "config", "team.json")
MAX_LOOKBACK_DAYS = 60
STALE_HOURS = 3          # no new mail for this long in a working day = the mailbox has stopped syncing

# Default folders that are never "mail that came in": what we wrote, what is
# queued, and Outlook's own housekeeping. (Outbox especially: reading a queued
# email takes it out of the send queue.) Deleted Items and Junk ARE read - a
# reply binned once read, or filtered as junk, is still a reply.
_SKIP_DEFAULT = (16, 4, 20)          # Drafts, Outbox, Sync Issues
_OLMAIL, _OLREPORT = 43, 46
AUTO_SUBJECT = ("out of office", "automatic reply", "auto-reply", "autoreply", "auto reply",
                "on annual leave", "annual leave", "on holiday", "away from the office",
                "on leave", "out of the office")


# ---------- state ----------
def load_state():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(state):
    """Write the state - merged with what is on disk now, so a re-arm made
    while a chase run was going is not overwritten by that run."""
    disk = load_state()
    for k, v in state.items():
        d = disk.get(k) or {}
        if d.get("rearmed_at") and str(d["rearmed_at"]) > str(v.get("rearmed_at") or "") \
                and str(d["rearmed_at"]) >= str(v.get("at") or ""):
            continue                        # a newer re-arm on disk wins
        disk[k] = v
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(disk, f, indent=1)
    os.replace(tmp, STATE)


def remember_block(state, rec, dec, now):
    """Replied = blocked for every order x contact on the record, so a
    duplicate tracker record for the same order inherits it (5033605 was
    chased from a duplicate after its reply had been parsed)."""
    for o in cr.orders_of(rec):
        for c in cr.contacts_of(rec, {"me": _me(), "internal_domains": ("dhl.com",)}):
            k = f"{o}|{c}"
            if not (state.get(k) or {}).get("blocked") or state[k].get("rearmed_at"):
                state[k] = {"blocked": True, "why": dec["reason"][:160],
                            "evidence": dec.get("evidence"), "at": now.strftime("%Y-%m-%d %H:%M")}


def rearm(order):
    """Delali says: resume automatic chasing for this order, from now. Re-arms
    every order and contact on the tracker records holding it - a record for
    '6055400 / 6055402' is one job, so re-arming one number re-arms both."""
    import tracker
    order = str(order).strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    st = load_state()
    keys = {k for k in st if k.split("|", 1)[0] == order}
    ctx = {"me": _me(), "internal_domains": ("dhl.com",)}
    for r in tracker.load().get("records", []):
        if order in cr.orders_of(r):
            for o in cr.orders_of(r):
                for c in cr.contacts_of(r, ctx):
                    keys.add(f"{o}|{c}")
            keys |= {k for k in st if k.split("|", 1)[0] in cr.orders_of(r)}
    for k in keys:
        v = st.get(k) or {}
        v.pop("blocked", None)
        v["rearmed_at"] = now
        st[k] = v
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)
    return len(keys)


def log_decision(rec, dec, sent=None):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "orders": rec.get("orders"), "to": rec.get("to"),
                                "action": dec["action"], "reason": dec["reason"],
                                "evidence": dec.get("evidence"), "sent": sent}) + "\n")
    except Exception:
        pass


# ---------- context ----------
def _me():
    return {"delali.opoku@dhl.com", "delali.opoku@networkrail.co.uk"}


def context(state=None):
    team = {}
    try:
        team = json.load(open(TEAM, encoding="utf-8"))
    except Exception:
        pass
    names = {str(m.get("name", "")).strip().lower() for m in team.get("members", []) if m.get("name")}
    internal = tuple(team.get("internal_domains") or ("dhl.com",))
    h_addr, h_dom = set(), set()
    try:
        import hauliers
        d = hauliers.load()
        for h in (d.get("hauliers") or []) + (d.get("couriers") or []):
            for e in h.get("emails") or []:
                e = str(e).strip().lower()
                if "@" in e:
                    h_addr.add(e)
                    if not cr.shared(cr.domain(e)):
                        h_dom.add(cr.domain(e))
    except Exception:
        pass
    # order -> when a HAULIER (one in the directory) was asked to cover it.
    # Supplier and depot requests are in that file too; they are not hauliers.
    h_orders = {}
    try:
        import haulier_asks
        for k, asks in haulier_asks.load().items():
            for a in asks or []:
                e = str(a.get("email") or "").strip().lower()
                if e in h_addr or (cr.domain(e) in h_dom and "@" in e):
                    for o in cr.ORDER_RE.findall(str(k)):
                        h_orders.setdefault(o, []).append(str(a.get("when") or ""))
    except Exception:
        pass
    hol = set()
    try:
        from services import BANK_HOLIDAYS
        hol = {datetime.strptime(h, "%Y-%m-%d").date() for h in BANK_HOLIDAYS}
    except Exception:
        pass
    return {"me": _me(), "internal_domains": internal, "team_names": names,
            "haulier_addresses": h_addr, "haulier_domains": h_dom, "haulier_orders": h_orders,
            "state": state if state is not None else load_state(), "holidays": hol}


# ---------- the mailbox index ----------
def _outlook_date(dt):
    """A date string Outlook's Restrict reads the way we mean it. Outlook parses
    filter dates with the PC's regional short-date format, so on a UK PC
    '10/02/2026' is 10 February - the trap that once made a search look at the
    wrong week. Ask Windows which order it uses rather than guess."""
    pat = "dd/MM/yyyy"
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(80)
        if ctypes.windll.kernel32.GetLocaleInfoEx(None, 0x1F, buf, 80):   # LOCALE_SSHORTDATE
            pat = buf.value or pat
    except Exception:
        pass
    p = pat.lower()
    if p.startswith("y"):
        d = dt.strftime("%Y-%m-%d")
    elif p.index("d") < p.index("m"):
        d = dt.strftime("%d/%m/%Y")
    else:
        d = dt.strftime("%m/%d/%Y")
    return d + dt.strftime(" %H:%M")


def _naive(t):
    try:
        return datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
    except Exception:
        return None


def _smtp_of_sender(it):
    """The sender's address. Never '' for a real email: '' means 'ours' to the
    rules, so an unresolvable sender keeps its raw address or becomes
    'unknown:<name>' - which the rules hold for, rather than ignore."""
    raw = ""
    try:
        raw = str(it.SenderEmailAddress or "")
        if "@" in raw:
            return raw.lower().strip()
        s = it.Sender
        ex = s.GetExchangeUser() if s is not None else None
        if ex is not None and ex.PrimarySmtpAddress:
            return str(ex.PrimarySmtpAddress).lower().strip()
    except Exception:
        pass
    try:
        smtp = it.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x5D01001F")
        if smtp and "@" in str(smtp):
            return str(smtp).lower().strip()
    except Exception:
        pass
    if raw:
        return raw.lower().strip()
    return "unknown:" + str(getattr(it, "SenderName", "") or "?").strip().lower()


def _recips(it):
    to, cc = [], []
    try:
        for i in range(1, it.Recipients.Count + 1):
            r = it.Recipients.Item(i)
            a = str(r.Address or "")
            if "@" not in a:
                try:
                    ex = r.AddressEntry.GetExchangeUser()
                    if ex is not None and ex.PrimarySmtpAddress:
                        a = ex.PrimarySmtpAddress
                except Exception:
                    pass
            a = a.lower().strip()
            (cc if int(r.Type) == 2 else to).append(a)
    except Exception:
        pass
    return to, cc


def _is_auto_subject(subject):
    s = str(subject or "").lower()
    return any(k in s for k in AUTO_SUBJECT)


def _is_auto(it, subject):
    """True / False, or None if the headers could not be read."""
    if _is_auto_subject(subject):
        return True
    h = it.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x007D001F") or ""
    h = h.lower()
    return ("auto-submitted: auto-replied" in h or "x-autoreply" in h
            or "x-autorespond" in h or "precedence: auto_reply" in h)


class MailIndex:
    """Every mail in the DHL store received / sent since `since`."""

    def __init__(self, ns, since):
        import build_drafts as bd
        self.ns = ns
        self.root = bd.dhl_store(ns)                 # the mailbox's top folder
        if self.root is None:
            raise RuntimeError("DHL mailbox not found in Outlook")
        self.store_id = self.root.StoreID
        self.mails, self._seen, self._text = [], set(), {}
        self.errors, self.item_errors = [], []
        self.started_at = None
        acct = None
        try:
            import send_order
            acct = send_order.dhl_account(ns)
        except Exception:
            pass
        ds = acct.DeliveryStore if acct is not None else None
        self._skip = set()
        self._sent = None
        if ds is not None:
            for n in _SKIP_DEFAULT:
                try:
                    self._skip.add(ds.GetDefaultFolder(n).EntryID)
                except Exception:
                    pass
            try:
                self._sent = ds.GetDefaultFolder(5)
            except Exception:
                self._sent = None
        if self._sent is None:
            self._sent = bd.sub(self.root, "Sent Items")
        if self._sent is None:
            raise RuntimeError("Sent Items not found")      # fail closed
        self._skip.add(self._sent.EntryID)
        self.scan(since)
        if self.errors and not self.mails:
            raise RuntimeError("mailbox scan failed: " + "; ".join(self.errors[:3]))

    # -- scanning --
    def scan(self, since):
        """Add everything since `since` (repeatable: already-seen items are skipped)."""
        if self.started_at is None:
            self.started_at = datetime.now()
        flt = f"[ReceivedTime] >= '{_outlook_date(since)}'"
        sflt = f"[SentOn] >= '{_outlook_date(since)}'"
        self._walk(self.root, "", 0, flt, since)
        try:
            for it in self._sent.Items.Restrict(sflt):
                self._add(it, "out", "/Sent Items", since)
        except Exception as e:
            self.errors.append(f"Sent Items: {e}")
            raise RuntimeError(f"cannot read Sent Items: {e}")     # fail closed
        self.built_at = datetime.now()

    def refresh(self):
        """Everything that arrived since the FIRST scan began (less a margin),
        read again - the re-check right before a send. A reply that landed in
        a folder after that folder was walked is caught here; five of the old
        wrong chasers went out within three minutes of the reply."""
        self.scan(self.started_at - timedelta(minutes=15))

    def _walk(self, f, path, depth, flt, since):
        if depth > 8:
            self.errors.append(f"{path}: deeper than 8 folders - not read")
            return
        try:
            skip = depth > 0 and (f.EntryID in self._skip or int(f.DefaultItemType) != 0)
        except Exception as e:
            self.errors.append(f"{path}: cannot open folder ({e})")
            return
        if skip:
            return
        if depth > 0:
            try:
                for it in f.Items.Restrict(flt):
                    self._add(it, "in", path, since)
            except Exception as e:
                self.errors.append(f"{path}: {e}")
        try:
            for i in range(1, f.Folders.Count + 1):
                s = f.Folders.Item(i)
                self._walk(s, path + "/" + str(s.Name), depth + 1, flt, since)
        except Exception as e:
            self.errors.append(f"{path} subfolders: {e}")

    def _add(self, it, direction, folder, since):
        try:
            cls = int(getattr(it, "Class", 0))
            if cls not in (_OLMAIL, _OLREPORT):
                return
            eid = str(it.EntryID)
            if eid in self._seen:
                return
            mclass = str(getattr(it, "MessageClass", "") or "").upper()
            if cls == _OLREPORT and "NDR" not in mclass:
                return                     # read / delivery receipts, delay notices: not bounces
            if direction == "out":
                at = _naive(it.SentOn)
            else:
                at = _naive(getattr(it, "ReceivedTime", None)) or _naive(it.CreationTime)
            # the date filter is Outlook's local-time string; check it here too
            if at is None or at < since - timedelta(hours=1):
                return
            subject = str(getattr(it, "Subject", "") or "")
            m = {"at": at, "dir": direction, "subject": subject, "eid": eid, "folder": folder,
                 "conv": str(getattr(it, "ConversationID", "") or ""), "ndr": cls == _OLREPORT,
                 "to": [], "cc": [], "from": "", "from_name": "", "auto": False, "draft": False}
            if direction == "out":
                m["from"] = "delali.opoku@dhl.com"
                m["to"], m["cc"] = _recips(it)
            elif cls == _OLMAIL:
                try:
                    m["draft"] = not bool(it.Sent)     # SEND OUT briefs etc. - never a reply
                except Exception:
                    pass
                if not m["draft"]:
                    m["from"] = _smtp_of_sender(it)
                    m["from_name"] = str(getattr(it, "SenderName", "") or "")
                    m["auto"] = _is_auto_subject(subject)
            self._seen.add(eid)
            self.mails.append(m)
        except Exception as e:
            self.item_errors.append(f"{folder}: {e}")

    def mark_auto(self, addresses, domains=()):
        """Out-of-office check on the message headers - one MAPI read per email,
        so only for mail from people who matter to the tracked orders (and
        their companies)."""
        addresses = {a.lower() for a in addresses}
        domains = set(domains)
        for m in self.mails:
            if m["dir"] != "in" or m["auto"] or m.get("_hdr") or m.get("draft"):
                continue
            if m["from"] in addresses or cr.domain(m["from"]) in domains:
                try:
                    it = self.ns.GetItemFromID(m["eid"], self.store_id)
                    m["auto"] = bool(_is_auto(it, m["subject"]))
                    m["_hdr"] = True
                except Exception:
                    pass                    # not marked: tried again next run

    # -- bodies, only when the rules ask --
    def text_of(self, eid):
        """The email's text, or None if it could not be read (not cached, so a
        later look tries again) - the rules treat None as 'hold', never 'no'."""
        if eid in self._text:
            return self._text[eid]
        try:
            it = self.ns.GetItemFromID(eid, self.store_id)
            self._text[eid] = str(it.Body or "")[:6000]
            return self._text[eid]
        except Exception:
            return None

    def newest_inbound(self):
        ins = [m["at"] for m in self.mails if m["dir"] == "in" and not m.get("draft")]
        return max(ins) if ins else None


def mailbox_fresh(ns, idx, now=None):
    """(ok, reason). Is Outlook connected and actually receiving mail? On
    02/10/2026 it said 'connected' while nothing had synced for over an hour -
    a chaser decided on a stale mailbox would miss the replies stuck upstream."""
    now = now or datetime.now()
    try:
        mode = int(ns.ExchangeConnectionMode)
        if ns.Offline or mode < 500:      # 100-400: offline / disconnected
            return False, f"Outlook is not connected to Exchange (mode {mode})"
    except Exception:
        pass
    newest = idx.newest_inbound()
    if newest and now.hour >= 10 and cr.is_working_day(now.date()) \
            and now - newest > timedelta(hours=STALE_HOURS):
        return False, (f"no new mail since {newest:%d/%m %H:%M} - the mailbox looks out of date "
                       "(restart Outlook)")
    return True, ""


def window_start(records):
    """Earliest ask among the records, capped at MAX_LOOKBACK_DAYS."""
    floor = datetime.now() - timedelta(days=MAX_LOOKBACK_DAYS)
    starts = [cr.parse_dt(r.get("emailed_at")) for r in records]
    starts = [s for s in starts if s]
    return max(floor, min(starts) - timedelta(days=21)) if starts else floor


def relevant(records, idx, ctx):
    """(addresses, domains): everyone we asked about a tracked order, everyone
    copied on what we sent, and the contacts' own companies."""
    addrs, doms = set(), set()
    for r in records:
        for c in cr.contacts_of(r, ctx):
            addrs.add(c)
            if not cr.shared(cr.domain(c)):
                doms.add(cr.domain(c))
    for m in idx.mails:
        if m["dir"] == "out":
            addrs |= set(m["to"]) | set(m["cc"])
    return addrs - set(ctx.get("me", ())), doms


def relevant_addresses(records, idx, ctx):
    return relevant(records, idx, ctx)[0]


def orig_info(ns, rec, cache={}):
    """(conversation ids, recipient addresses) of the original email the
    record points at. Supplier collection records hold display names
    ('Anderton Rail') in `to`; the real addresses are on that email."""
    eid = rec.get("orig_entryid")
    if not eid:
        return [], []
    if eid not in cache:
        try:
            it = ns.GetItemFromID(eid)
            to, cc = _recips(it)
            cache[eid] = ([str(it.ConversationID or "")], [a for a in to + cc if "@" in a])
        except Exception:
            cache[eid] = ([], [])
    return cache[eid]


def conv_ids_for(ns, rec):
    return orig_info(ns, rec)[0]


def with_mailbox_facts(ns, rec):
    convs, smtp = orig_info(ns, rec)
    return dict(rec, conv_ids=convs, to_smtp=smtp)


def assess_all(ns, records, idx=None, now=None):
    """[(record, decision)] for every record, from one mailbox index."""
    now = now or datetime.now()
    idx = idx or MailIndex(ns, window_start(records))
    ctx = context()
    full = [with_mailbox_facts(ns, r) for r in records]
    addrs, doms = relevant(full, idx, ctx)
    idx.mark_auto(addrs, doms)
    out = []
    for r, r2 in zip(records, full):
        out.append((r, cr.assess(r2, idx.mails, ctx, idx.text_of, now)))
    return out, idx, ctx


def main():
    import tracker
    import build_drafts as bd
    ns = bd.get_ns()
    recs = [r for r in tracker.load()["records"] if r.get("status") == "sent"]
    decs, idx, _ctx = assess_all(ns, recs)
    ok, why = mailbox_fresh(ns, idx)
    print(f"{len(idx.mails)} emails indexed since {window_start(recs):%d/%m}; "
          f"{len(idx.errors)} folder problem(s), {len(idx.item_errors)} unreadable item(s); "
          f"mailbox {'OK' if ok else 'NOT OK: ' + why}")
    for r, d in decs:
        ev = d.get("evidence") or {}
        print(f"  {d['action']:<5} {' / '.join(r.get('orders', [])):<20} {str(r.get('to', ''))[:38]:<38} "
              f"{d['reason']}")
        if ev:
            print(f"        evidence: {ev.get('at')} {ev.get('from')} | {ev.get('subject')} "
                  f"[{ev.get('folder')}]")


if __name__ == "__main__":
    main()
