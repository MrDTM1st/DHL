"""Bounce -> escalate, the moment it lands.

Delali, 05/10/2026: "if something bounces, just immediately escalate it."

A delivery-details email to a site contact that comes back undeliverable means
that contact cannot be reached by email at all. So when a hard bounce lands on
an order's own site contact, ask the Network Rail materials team that owns the
product for an alternative contact straight away - the same alt-contact
escalation the dashboard drawer composes (hauliers.MATERIALS_TEAMS).

It ESCALATES only when every one of these holds:
  * the bounced address is the order's site contact ON RECORD - a delivery
    record in the tracker / wait-list whose "to" is that address, or the
    address in the order's own contact field - and that contact field does not
    show a different (correct) address the toolkit should have used;
  * nobody else outside DHL got the same email (7115993: Lee Upson bounced,
    James Garrod got it - nothing to escalate);
  * it is a permanent failure, on a real domain (not "netwotkrail");
  * the order is not booked, its date has not gone, and its material maps to
    a team.
Everything else that matters is FLAGGED for Delali instead, never escalated:
a bounce on an escalation (would loop), a supplier collection request or a
haulier ring-round, a mistyped domain, an address our own parser cut short
(7116157 lost "Louis."), a contact who is not the one on record.

Safety: each escalation is written to the state file as "sending" BEFORE it is
sent, so a crash, a COM error or the 25-minute kill can never send it twice. A
failure before Send is queued and retried; a failure inside Send is flagged,
not retried. One escalation per order, however many of its addresses bounced.
Notices wait in the state file until the dashboard is not showing a review.

    python bounce_escalate.py [days]       DRY RUN - what it would do (default 7 days)
    python bounce_escalate.py send         what the live monitor runs
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_drafts as bd  # noqa: E402

STATE = os.path.join(HERE, "_bounce_escalations.json")
LOOKBACK = timedelta(hours=72)        # NDRs can sync in late - a fixed window, not a moving watermark
ORDER_RE = re.compile(r"\b([5-7]\d{6})\b")
FAILED_RES = (
    re.compile(r"<([^<>\s]+@[^<>\s]+)>\s*\(reason:\s*([^)]*)\)", re.I),          # sendmail / EXO relay
    re.compile(r"Your message to\s+<?([^\s<>]+@[^\s<>]+?)>?\s+couldn.t be delivered", re.I),
    re.compile(r"Delivery has failed to these recipients or groups:\s*\S*\s*\(?([^\s()<>]+@[^\s()<>]+)", re.I),
)
HARD = re.compile(r"\b5\.\d\.\d+\b|\b550\b|\b554\b|does not exist|not found|rejected|couldn.t be delivered|"
                  r"permanent|fatal error|no such user|unknown user|mailbox unavailable", re.I)
HOST_UNKNOWN = re.compile(r"host unknown|domain not found|no such domain", re.I)
SKIP_ADDR = re.compile(r"postmaster|mailer-daemon|microsoftexchange|no-?reply", re.I)
PREFIX = re.compile(r"^\s*(undeliverable|delivery has failed[^:]*|mail delivery failed[^:]*|"
                    r"returned mail[^:]*|delivery status notification \(failure\))\s*:\s*", re.I)
REFW = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.I)
RINGROUND = re.compile(r"^[\w/ \-]+\bdelivery$", re.I)                       # "7116043 Delivery"
FREEMAIL = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com",
            "live.co.uk", "msn.com", "aol.com", "aol.co.uk", "btinternet.com", "btopenworld.com",
            "yahoo.com", "yahoo.co.uk", "icloud.com", "me.com", "sky.com", "talktalk.net",
            "virginmedia.com", "ntlworld.com"}
TEAM_FOR = (
    (re.compile(r"sleeper|bearer|trough", re.I), "sleepers"),
    (re.compile(r"\brails?\b|s&c|switch|crossing", re.I), "rails"),
    (re.compile(r"ballast|aggregate|chipping|stone|sand|granite", re.I), "ballast"),
)


# ---------- state ----------
def _load():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except FileNotFoundError:
        return None
    except Exception:
        # unreadable is NOT "first run" - refuse to act rather than forget what was sent
        raise RuntimeError("bounce state file unreadable - not escalating anything until it is fixed")


def _save(d):
    tmp = f"{STATE}.{os.getpid()}.tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), indent=1, default=str)
    os.replace(tmp, STATE)


def _note(state, line):
    state.setdefault("unreported", []).append(f"{datetime.now():%d/%m %H:%M} {line}")
    state["unreported"] = state["unreported"][-60:]


def take_unreported(clear=True):
    """The notices waiting for the dashboard (the monitor posts them when no
    review is open)."""
    try:
        st = _load() or {}
    except Exception:
        return []
    lines = list(st.get("unreported") or [])
    if clear and lines:
        st["unreported"] = []
        _save(st)
    return lines


# ---------- helpers ----------
def _edit2(a, b):
    a, b = a.lower(), b.lower()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 2


def _days_ago(dd):
    try:
        return (datetime.now().date() - datetime.strptime(str(dd).strip()[:10], "%d/%m/%Y").date()).days
    except Exception:
        return 0


def _trusted_domains():
    """networkrail.co.uk plus any domain seen on 3+ recorded contacts - so one
    typo on the tracker can never make a real domain look like the typo."""
    from collections import Counter
    c = Counter()
    for fn, key in (("tracker.json", "records"), ("waitlist.json", "entries")):
        try:
            for r in json.load(open(os.path.join(HERE, fn), encoding="utf-8")).get(key, []):
                for a in re.findall(r"[\w.'\-+]+@([\w.\-]+)", str(r.get("to") or "")):
                    c[a.lower()] += 1
        except Exception:
            pass
    return {"networkrail.co.uk"} | {d for d, n in c.items() if n >= 3}


def _haulier_addresses():
    try:
        import hauliers
        d = hauliers.load()
        addrs, doms = set(), set()
        for g in ("hauliers", "couriers", "services"):
            for h in d.get(g, []):
                for e in h.get("emails") or []:
                    e = str(e).lower().strip()
                    addrs.add(e)
                    doms.add(e.split("@")[-1])
        return addrs, doms - FREEMAIL - {"dhl.com", "networkrail.co.uk"}
    except Exception:
        return set(), set()


def _supplier_addresses():
    addrs, doms = set(), set()
    for sup in (bd.CFG.get("special_collection_suppliers") or {}).values():
        for e in list(sup.get("to") or []) + list(sup.get("cc") or []):
            e = str(e).lower().strip()
            addrs.add(e)
            doms.add(e.split("@")[-1])
    return addrs, doms - FREEMAIL


def parse_ndr(it):
    """(original subject, [(address, reason)], body) from a non-delivery report."""
    subj = PREFIX.sub("", str(getattr(it, "Subject", "") or "")).strip()
    body = re.sub(r"[ \t]+", " ", str(getattr(it, "Body", "") or ""))
    failed = []
    for rx in FAILED_RES:
        for m in rx.finditer(body):
            addr = m.group(1).strip(" .,;:'\"").lower()
            reason = m.group(2) if rx.groups > 1 else body[m.end():m.end() + 160]
            if "@" in addr and not SKIP_ADDR.search(addr) and addr not in [a for a, _ in failed]:
                failed.append((addr, " ".join(str(reason).split())[:160]))
        if failed:
            break
    return subj, failed, body


def context(ns, order):
    """Everything known about the order: its delivery records (with their
    'to'), material/site/date, booked or not, and the raw contact field from
    the order's own extract line."""
    ctx = {"orders": [order], "records": [], "materials": "", "site": "", "postcode": "", "date": "",
           "booked": False, "dcon": "", "dcon_name": ""}
    for fn, key, dk in (("tracker.json", "records", "delivery_date"), ("waitlist.json", "entries", "date")):
        try:
            for r in json.load(open(os.path.join(HERE, fn), encoding="utf-8")).get(key, []):
                if order not in [str(o) for o in r.get("orders") or []]:
                    continue
                if str(r.get("kind") or "delivery") == "collection":
                    continue
                ctx["records"].append({"to": str(r.get("to") or "").lower(), "name": str(r.get("name") or "")})
                ctx["materials"] = ctx["materials"] or str(r.get("materials") or "")
                ctx["site"] = ctx["site"] or str(r.get("worksite") or r.get("site") or "")
                ctx["postcode"] = ctx["postcode"] or str(r.get("postcode") or "")
                ctx["date"] = ctx["date"] or str(r.get(dk) or "")
                if r.get("orders"):
                    ctx["orders"] = [str(o) for o in r["orders"]]
        except Exception:
            pass
    for fn in ("_booked_drops.json", "_adhoc_booked.json"):
        try:
            if order in json.dumps(json.load(open(os.path.join(HERE, fn), encoding="utf-8"))):
                ctx["booked"] = True
        except Exception:
            pass
    try:
        import send_order as so
        collected, _, _ = so.resolve_orders(ns, order)
        for r, C, _ in collected or []:
            dcon = str(r[C["dcon"]] or "") if C.get("dcon") is not None else ""
            if dcon and not ctx["dcon"]:
                ctx["dcon"] = dcon
                ctx["dcon_name"] = re.split(r"\s+email\s*:", dcon, flags=re.I)[0].strip()
            if not ctx["materials"]:
                prod = r[C["prod"]] if C.get("prod") is not None else ""
                pcode = r[C["prod_code"]] if C.get("prod_code") is not None else ""
                ctx["materials"] = f"{r[C['qty']]}x {bd.readable_product(prod, pcode)}"
            ctx["site"] = ctx["site"] or bd.worksite_of(r[C["dpoint"]] if C.get("dpoint") is not None else "") \
                or bd.clean(r[C["daddr"]])
            ctx["postcode"] = ctx["postcode"] or bd.clean(r[C["dpc"]])
            ctx["date"] = ctx["date"] or bd.fdate(r[C["date"]])
    except Exception:
        pass
    return ctx


def team_for(materials):
    try:
        import hauliers
        teams = hauliers.MATERIALS_TEAMS
    except Exception:
        return None
    for rx, key in TEAM_FOR:
        if rx.search(materials or ""):
            return teams.get(key)
    return None


def _also_reached(ns, subj, addr, ndr_at):
    """Other outside recipients of the email that bounced on addr. The most
    recent sent item before the NDR, same subject, that went to addr."""
    try:
        sent = bd.sub(bd.dhl_store(ns), "Sent Items")
        want = REFW.sub("", subj).strip().lower()
        core = ORDER_RE.search(want) or re.search(r"[\w ]{6,30}", want)
        if not core:
            return []
        flt = '@SQL="urn:schemas:httpmail:subject" LIKE \'%' + core.group(0).replace("'", "''") + '%\''
        best = None
        for it in sent.Items.Restrict(flt):
            try:
                at = it.SentOn.replace(tzinfo=None)
            except Exception:
                continue
            if not (ndr_at - timedelta(days=3) <= at <= ndr_at + timedelta(minutes=2)):
                continue
            if REFW.sub("", str(getattr(it, "Subject", "") or "")).strip().lower() != want:
                continue
            rec = [str(it.Recipients.Item(j).Address or "").lower() for j in range(1, it.Recipients.Count + 1)]
            if addr not in rec:
                continue
            if best is None or at > best[0]:
                best = (at, rec)
        if not best:
            return []
        return [a for a in best[1] if "@" in a and not a.endswith("@dhl.com") and a != addr]
    except Exception:
        return []


def compose(ctx, who):
    orders = " / ".join(ctx["orders"])
    where = ", ".join(p for p in (ctx["site"], ctx["postcode"]) if p)
    what = f" - {ctx['materials']}" + (f" to {where}" if where else "") \
        + (f", delivering {ctx['date']}" if ctx["date"] else "") + " -"
    subject = re.sub(r"\s+", " ", f"{orders} {ctx['site']} {ctx['postcode']} - alternative contact needed").strip()
    message = (f"Hi,\n\nI emailed {who} about order {orders}{what} but the email bounced back as "
               f"undeliverable, so I have no way of reaching them.\n\nCould you point me to an "
               f"alternative contact for this order so I can get the delivery sorted?")
    return subject, message


# ---------- the decision for one bounce ----------
def decide(ns, it, state, refs):
    """[(kind, detail, payload)]; kind is escalate | flag | skip. At most ONE
    escalate per order, however many of its addresses bounced."""
    subj, failed, body = parse_ndr(it)
    base = REFW.sub("", subj).strip()
    if not failed:
        return [("flag", f"bounce on '{subj[:60]}' - could not read which address failed", None)]
    if "alternative contact needed" in base.lower():
        return [("flag", f"the escalation '{base[:60]}' itself bounced on {a} - check that address", None)
                for a, _ in failed]
    if base.lower().startswith("collection "):
        return [("flag", f"supplier collection email '{base[:50]}' bounced on {a} - check the supplier's address", None)
                for a, _ in failed]
    if "can you cover" in base.lower() or RINGROUND.match(base):
        return [("flag", f"haulier email '{base[:50]}' bounced on {a} - check the haulier's address", None)
                for a, _ in failed]
    orders = ORDER_RE.findall(base)
    out, cands = [], []
    for addr, reason in failed:
        dom = addr.split("@")[-1]
        if addr.endswith("@dhl.com"):
            out.append(("skip", f"{addr} is DHL", None))
        elif addr in refs["sup_a"] or dom in refs["sup_d"]:
            out.append(("flag", f"supplier {addr} bounced on '{base[:50]}' - check the supplier's address", None))
        elif addr in refs["haul_a"] or dom in refs["haul_d"]:
            out.append(("flag", f"haulier {addr} bounced on '{base[:50]}' - check the haulier's address", None))
        elif HOST_UNKNOWN.search(reason) or (dom not in refs["trusted"]
                                            and any(_edit2(dom, t) for t in refs["trusted"])):
            near = next((t for t in refs["trusted"] if t != dom and _edit2(dom, t)), "")
            out.append(("flag", f"{addr} has a mistyped domain ('{base[:50]}')"
                        + (f" - it should probably be {addr.split('@')[0]}@{near}" if near else ""), None))
        elif not HARD.search(reason + " " + body[:600]):
            out.append(("skip", f"{addr}: not a permanent failure ({reason[:60]})", None))
        elif not orders:
            out.append(("flag", f"{addr} bounced on '{base[:60]}' - no order number, escalate by hand if it matters", None))
        else:
            cands.append(addr)
    if not cands:
        return out
    order = orders[0]
    ctx = context(ns, order)
    on_record = bd.email_of(ctx["dcon"]).lower() if ctx["dcon"] and bd.email_of(ctx["dcon"]) else ""
    ndr_at = getattr(it, "CreationTime").replace(tzinfo=None)
    esc = []
    for addr in cands:
        rec = next((r for r in ctx["records"] if addr in r["to"]), None)
        if on_record and on_record != addr:
            out.append(("flag", f"{order}: {addr} bounced, but the order's contact field gives {on_record} - "
                        f"re-send to that address", None))
            continue
        if not rec and on_record != addr:
            out.append(("flag", f"{order}: {addr} bounced but is not the site contact on record - check it by hand", None))
            continue
        others = _also_reached(ns, subj, addr, ndr_at)
        if others:
            out.append(("flag", f"{order}: {addr} bounced, but {', '.join(others)} got the same email - "
                        f"check whether {addr.split('@')[0]} still matters", None))
            continue
        if f"{order}|{addr}" in state.get("done", {}):
            out.append(("skip", f"{order}|{addr} already escalated", None))
            continue
        name = (rec or {}).get("name") or (ctx["dcon_name"] if on_record == addr else "")
        esc.append((addr, name))
    if not esc:
        return out
    if ctx["booked"]:
        return out + [("skip", f"{order} is already booked - nothing to chase", None)]
    if ctx["date"] and _days_ago(ctx["date"]) > 1:
        return out + [("flag", f"{order}: {', '.join(a for a, _ in esc)} bounced but the delivery date "
                       f"{ctx['date']} has gone - check what happened", None)]
    team = team_for(ctx["materials"])
    if not team:
        return out + [("flag", f"{order}: {', '.join(a for a, _ in esc)} bounced - cannot tell which materials "
                       f"team owns '{ctx['materials'] or 'unknown product'}', escalate by hand", None)]
    who = " and ".join(f"{n} ({a})" if n else a for a, n in esc)
    subject, message = compose(ctx, who)
    out.append(("escalate", f"{order}: {', '.join(a for a, _ in esc)} bounced -> asked {team['name']} for an "
                f"alternative contact",
                {"order": order, "keys": [f"{order}|{a}" for a, _ in esc], "to": team["email"],
                 "team": team["name"], "subject": subject, "message": message,
                 "orders": ctx["orders"], "failed": [a for a, _ in esc]}))
    return out


# ---------- sending ----------
def _send(ns, state, payload, results):
    """Write-ahead, then send. 'sending' on disk before Send means a crash can
    only ever under-send, never send twice."""
    import metrics
    import send_order as so
    now = f"{datetime.now():%d/%m/%Y %H:%M}"
    try:
        acct = so.dhl_account(ns)
        m = ns.Application.CreateItem(0)
        m.To = payload["to"]
        m.Subject = payload["subject"]
        bd._attach_qr(m)
        m.HTMLBody = bd.html_from_message(payload["message"])
        if acct is None or not so.bind_account(m, acct):
            raise RuntimeError("could not bind the DHL account")
    except Exception as e:                              # nothing sent: queue it for the next tick
        p = state.setdefault("pending", {})
        p[payload["order"]] = dict(payload, tries=p.get(payload["order"], {}).get("tries", 0) + 1, error=str(e)[:120])
        if p[payload["order"]]["tries"] >= 3:
            p.pop(payload["order"], None)
            _note(state, f"Bounce needs you: {payload['order']} escalation could not be prepared 3 times ({e}) - send it by hand")
        _save(state)
        return
    for k in payload["keys"]:
        state.setdefault("done", {})[k] = {"at": now, "to": payload["to"], "subject": payload["subject"], "status": "sending"}
    state.get("pending", {}).pop(payload["order"], None)
    _save(state)
    try:
        m.Send()
    except Exception as e:
        for k in payload["keys"]:
            state["done"][k]["status"] = "uncertain"
        _note(state, f"Bounce needs you: the {payload['order']} escalation to {payload['team']} may not have gone ({e}) "
                     f"- check Sent Items")
        _save(state)
        return
    for k in payload["keys"]:
        state["done"][k]["status"] = "sent"
    _note(state, f"Bounce escalated: {payload['order']} - {', '.join(payload['failed'])} bounced, asked "
                 f"{payload['team']} for an alternative contact")
    _save(state)
    try:
        metrics.log("bounce_escalated", orders=payload["orders"], to=payload["to"], failed=payload["failed"])
    except Exception:
        pass
    results.append(("escalate", f"SENT {payload['subject']} -> {payload['to']}"))


def _ndrs(inbox, since):
    flt = ('@SQL=("http://schemas.microsoft.com/mapi/proptag/0x001A001F" LIKE \'REPORT.IPM.Note.NDR%\' OR '
           '"urn:schemas:httpmail:subject" LIKE \'Undeliverable%\' OR '
           '"urn:schemas:httpmail:subject" LIKE \'Delivery has failed%\' OR '
           '"urn:schemas:httpmail:subject" LIKE \'Mail delivery failed%\')')
    out = []
    for it in inbox.Items.Restrict(flt):
        try:
            at = it.CreationTime.replace(tzinfo=None)
            if at >= since:
                out.append((at, it))
        except Exception:
            pass
    return sorted(out, key=lambda t: t[0])


def run(ns=None, send=False, days=None):
    """Handle bounces. send=True is the live mode. Returns [(kind, detail)]."""
    ns = ns or bd.get_ns()
    now = datetime.now()
    state = _load()
    if state is None:
        state = {"floor": now.isoformat(timespec="seconds"), "done": {}, "seen": [], "pending": {},
                 "unreported": [], "errors": {}}
        if send:
            _save(state)            # first run: bounces already in the Inbox were handled by hand
            return []
    state.setdefault("floor", state.get("since") or now.isoformat(timespec="seconds"))
    if days:
        since = now - timedelta(days=days)
    else:
        since = max(now - LOOKBACK, datetime.fromisoformat(state["floor"]))
    refs = {"trusted": _trusted_domains()}
    refs["haul_a"], refs["haul_d"] = _haulier_addresses()
    refs["sup_a"], refs["sup_d"] = _supplier_addresses()
    inbox = bd.sub(bd.dhl_store(ns), "Inbox")
    results = []
    seen = list(state.get("seen") or [])
    try:
        if send:
            for order, payload in list((state.get("pending") or {}).items()):
                if not any(k in state.get("done", {}) for k in payload.get("keys", [])):
                    _send(ns, state, payload, results)
        for at, it in _ndrs(inbox, since):
            try:
                eid = str(it.EntryID)
                if send and eid in seen:
                    continue
                for kind, detail, payload in decide(ns, it, state, refs):
                    results.append((kind, f"[{at:%d/%m %H:%M}] {detail}"))
                    if not send:
                        continue
                    if kind == "escalate":
                        _send(ns, state, payload, results)
                    elif kind == "flag":
                        _note(state, f"Bounce needs you: {detail}")
                if send:
                    seen.append(eid)
                    state["seen"] = seen[-1000:]
                    state.get("errors", {}).pop(eid, None)
                    _save(state)
            except Exception as e:
                eid = locals().get("eid", "?")
                errs = state.setdefault("errors", {})
                errs[eid] = errs.get(eid, 0) + 1
                results.append(("flag", f"[{at:%d/%m %H:%M}] could not handle a bounce ({e})"))
                if send and errs[eid] >= 3:                 # a broken item must not flag every tick
                    seen.append(eid)
                    state["seen"] = seen[-1000:]
                    _note(state, f"Bounce needs you: a bounce from {at:%d/%m %H:%M} could not be read ({e}) - look at it by hand")
                if send:
                    _save(state)
    finally:
        if send:
            _save(state)
    return results


def main():
    args = sys.argv[1:]
    send = "send" in args
    days = next((int(a) for a in args if a.isdigit()), None if send else 7)
    res = run(send=send, days=None if send else days)
    for kind, detail in res:
        print(f"  {kind.upper():8} {detail}")
    if not send:
        print(f"\nDRY RUN over the last {days} day(s) - nothing sent. The monitor runs it with 'send'.")


if __name__ == "__main__":
    main()
