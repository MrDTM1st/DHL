"""Escalate an unanswered site contact by itself: with four working days to go, or once the ask and a chase have gone.

The planner, 02/11/2026: "if there is 4 days to go until the delivery is due, that's when you send the
escalation. You just do it automatically. So it's not 4 days when I've sent the message, is 4 days left
until the actual delivery."

And 10/11/2026: "If we've chased twice, so we've emailed once and we then chase again ... the third chase would
have to be an escalation, no matter how long, no matter how far the order is." The chaser waits instead of a second
chase (chase_rules.assess), and this sends the escalation in its place (chase_rules.chased_out).

The email is the brief's "Can't reach X?" one, word for word: to the materials team that owns the product,
cc the contact. Sending it leaves the same trail the brief's button does: " - Escalated DO dd/mm" on the
CTMS to-do list and escalated_at on the tracker.

Whether anyone answered is decided the way the chaser decides it, against every email in the mailbox
(chase_guard + chase_rules), and read again right before each send. It fails closed: if the mailbox cannot
be read completely, nothing goes. It sends only when:
  * chase_rules.escalate_due says so (sent, no reply, due, delivery still ahead, not escalated already);
  * the chaser's rules find no reply, booking or haulier ask. An out-of-office does not stop it - a contact
    who is away is exactly who needs an alternative. "Someone else wrote about it" and "they emailed about
    something else" are held for as long as the chaser holds them;
  * CTMS was looked at today and shows no Veh Type. A cancellation, or details taken over the phone, leave
    nothing in the mailbox: only the look-up (ctms_sync) can see them, and what it saw yesterday cannot
    answer for today. No look-up today means it is held and he is told, never sent on a guess - and (11/11)
    the work PC is asked to look just those orders up at its next quiet minute, the set times' three quiet
    minutes being more than a busy day gives. The 20-minute pass (phase2.py escalate) sends it once it lands;
  * nobody has already asked for an alternative contact on that order (the brief, a bounce, or by hand);
  * the product maps to a materials team. A job of two materials goes to both teams.

Anything that needs him goes to BOTH dashboards, once a day per order: the chase job's own report only
reaches the home PC's page, and he works from the cloud one.

Each escalation is written to the state file as "sending" BEFORE it is sent, so a crash can only ever
under-send. Runs from the automatic chase job (phase2.py chase send, every 3h), so it stops if the
automatic chasers are switched off. From 10:00 only: before then mailbox_fresh does not test for a mailbox
that has stopped syncing, and the PC wakes at about 09:00 and reads Outlook's cache within the minute.

    auto_escalate.enabled    first word LIVE = send, anything else = say what it would do, no file = off

    python auto_escalate.py          DRY RUN - who would be escalated now, sends nothing
"""
import json
import os
import socket
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FLAG = os.path.join(HERE, "auto_escalate.enabled")
STATE = os.path.join(HERE, "_auto_escalations.json")
LOCK_PORT = 8793            # chase run 8790, wait-list release 8791, the CTMS bridge 8792
FROM_HOUR = 10              # the first hour chase_guard.mailbox_fresh tests for a stuck mailbox
RETRY_AFTER = timedelta(hours=1)    # long enough for an email that did go to have reached Sent Items
MAX_PER_RUN = 12            # a backstop, not a rule: the rest go on the next run, and it says so
_LOCK_SOCK = None


def mode():
    """'off' | 'shadow' | 'live'. LIVE only when the file's first word says so."""
    if not os.path.exists(FLAG):
        return "off"
    try:
        raw = open(FLAG, "rb").read(400)
    except OSError:
        return "shadow"
    text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "ignore")
    words = text.upper().split()
    return "live" if words and words[0] == "LIVE" else "shadow"


def looked_at_today(rec, now):
    from modules import chase_rules as cr
    at = cr.parse_dt(rec.get("ctms_at"))
    return bool(at) and at.date() == now.date()


def decide(rec, dec, asked_already, now):
    """(what, why) for one record the rules call due: 'escalate', 'hold' (he is told) or 'skip'."""
    from modules import chase_rules as cr
    action, reason = dec.get("action"), str(dec.get("reason") or "")
    if rec.get("ctms_veh"):
        return "skip", "Veh Type is filled in CTMS - the site's details are in, ready to book"
    if asked_already:
        return "asked", f"an alternative contact was already asked for on {asked_already['at']:%d/%m %H:%M}"
    if action in (cr.BLOCK, cr.STOP):
        return "skip", reason
    if action == cr.HOLD and not reason.startswith("out of office"):
        return "hold", reason
    if not looked_at_today(rec, now):
        return "hold", (LOOKED + ", so it could be booked, cancelled or answered by phone - the work PC looks "
                        "it up at its next quiet minute and it goes on the next pass")
    if (dec.get("evidence") or {}).get("escalate"):
        return "escalate", "no reply to the ask and a chase"
    return "escalate", "out of office" if action == cr.HOLD else "no reply"


LOOKED = "CTMS has not been looked at today"


def want_lookup(recs):
    """Ask the dashboard to have the work PC look these orders up in CTMS at its next quiet minute (11/11): an
    escalation held only for want of today's look-up then goes on the next 20-minute pass. Never at the run's
    expense. -> whether the dashboard took the ask."""
    import urllib.request
    orders = [{"ref": str(o), "date": r.get("delivery_date") or ""} for r in recs for o in r.get("orders") or []][:10]
    if not orders:
        return False
    try:
        with open(os.path.join(HERE, "cloud.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        req = urllib.request.Request(str(cfg["url"]).rstrip("/") + "/api/ctms/check_want",
                                     data=json.dumps({"orders": orders, "why": "an escalation held for it"}).encode(),
                                     headers={"X-Auth": cfg["agent_key"], "Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            took = resp.status == 200
    except Exception as e:
        print(f"  (could not ask for the CTMS look-up of {', '.join(o['ref'] for o in orders)}: {e})")
        return False
    print(f"  asked the work PC to look up {', '.join(o['ref'] for o in orders)} in CTMS at its next quiet minute")
    return took


def already_asked(rec, mails):
    """Our own email asking for an alternative contact on this order: the brief's sets escalated_at, but a
    bounce's or one written by hand does not, and neither should be followed by a second."""
    from modules import chase_rules as cr
    orders = cr.orders_of(rec)
    for m in mails:
        subj = str(m.get("subject") or "")
        if (m.get("dir") == "out" and orders and cr.mentions(subj, orders)
                and any(w in subj.lower() for w in ("alternative contact", "alt contact"))):
            return m
    return None


def teams_for(materials):
    """Every materials team the job's product belongs to - two for "37x rails, 516x sleepers"."""
    import bounce_escalate
    import hauliers
    out = []
    for rx, key in bounce_escalate.TEAM_FOR:
        team = hauliers.MATERIALS_TEAMS.get(key)
        if team and rx.search(materials or "") and team not in out:
            out.append(team)
    return out


def compose(rec):
    """(subject, message) - the wording the brief's "Can't reach X?" email has always had (Drawer.jsx)."""
    import re
    orders = " / ".join(str(o) for o in rec.get("orders") or [])
    site = rec.get("worksite") or rec.get("site") or ""
    who = f"{rec['name']} ({rec['to']})" if rec.get("name") else rec.get("to", "")
    where = ", ".join(x for x in (site, rec.get("postcode")) if x)
    subject = re.sub(r"\s+", " ", f"{orders} {site} {rec.get('postcode') or ''} - alternative contact needed").strip()
    date = f", delivering {rec['delivery_date']}" if rec.get("delivery_date") else ""
    message = (f"Hi,\n\nI have been trying to reach {who} (cc'd) about order {orders} - "
               f"{rec.get('materials') or 'the materials'} to {where}{date} - but I have not managed to get "
               f"hold of them after a few attempts.\n\nCould you point me to an alternative contact for this "
               f"order so I can get the delivery sorted?")
    return subject, message


def retry_ready(entry, now):
    """Whether an escalation that never reached Sent Items can go again. Only when the last try was not known
    to send, and long enough ago that it would have shown by now."""
    if not entry or entry.get("status") == "sent":
        return False
    try:
        at = datetime.strptime(str(entry.get("at")), "%d/%m/%Y %H:%M")
    except ValueError:
        return False
    return now - at >= RETRY_AFTER


# ---------- state + telling him ----------
def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"done": {}}
    except FileNotFoundError:
        return {"done": {}}
    except Exception:
        # unreadable is not "nothing sent yet" - refuse rather than forget what went
        raise RuntimeError("auto escalation state file unreadable - not escalating anything until it is fixed")


def _save(d):
    tmp = f"{STATE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
    os.replace(tmp, STATE)


def _tell(state, key, line, now):
    """Queue a line for the dashboards, once a day per order and what is being said."""
    told = state.setdefault("told", {})
    stamp = f"{now:%Y-%m-%d}|{line[:60]}"
    if told.get(key) != stamp:
        told[key] = stamp
        state.setdefault("unreported", []).append(f"{now:%d/%m %H:%M} {line}")
        state["unreported"] = state["unreported"][-60:]


def _flush(state):
    """Post what is waiting to BOTH dashboards, unless he is in a review a notice would wipe (it then waits)."""
    lines = list(state.get("unreported") or [])
    if not lines:
        return
    try:
        import monitor_tick
        if monitor_tick._review_open():
            return
        sent = sum(1 for x in lines if " escalated to " in x)
        monitor_tick.report("done", (f"Escalations: {sent} sent, {len(lines) - sent} for you to look at."
                                     if len(lines) > sent else f"Escalations: {sent} sent."), "\n".join(lines))
        state["unreported"] = []
        _save(state)
    except Exception as e:
        print(f"(could not post the escalation notice, it stays queued: {e})")


# ---------- sending ----------
def _send(ns, state, rec, teams):
    """Write-ahead, then send. Raises if it may not have gone."""
    import build_drafts as bd
    import ctms_todo
    import metrics
    import send_order as so
    import tracker
    subject, message = compose(rec)
    to, cc, _removed = bd.clean_to_cc("; ".join(t["email"] for t in teams), rec.get("to", ""))
    acct = so.dhl_account(ns)
    if not to or acct is None:
        raise RuntimeError("no recipient or no DHL account")
    m = ns.Application.CreateItem(0)
    m.To = to
    if cc:
        m.CC = cc
    m.Subject = subject
    bd._attach_qr(m)
    m.HTMLBody = bd.html_from_message(message)
    if not so.bind_account(m, acct):
        raise RuntimeError("could not bind the DHL account")
    state.setdefault("done", {})[rec["id"]] = {"at": f"{datetime.now():%d/%m/%Y %H:%M}", "orders": rec.get("orders"),
                                               "to": to, "cc": cc, "subject": subject, "status": "sending"}
    _save(state)
    m.Send()
    state["done"][rec["id"]]["status"] = "sent"
    _save(state)
    # The email has gone: nothing below may turn that into a reported failure.
    try:
        ctms_todo.escalated(rec.get("orders", []))
        tracker.escalated(rec.get("orders", []))
        metrics.log("auto_escalated", orders=rec.get("orders", []), to=to)
        ns.SendAndReceive(False)
    except Exception as e:
        print(f"(escalation {subject} IS sent; the bookkeeping after it hiccupped: {e})")


def run(ns=None, send=False):
    """Escalate whoever is due. send=False is a dry run. Returns [(what, orders, detail)]."""
    global _LOCK_SOCK
    import build_drafts as bd
    import chase_guard as guard
    import tracker
    from modules import chase_rules as cr

    live = send and mode() == "live"
    if send and mode() == "off":
        return []
    holidays = guard.context(state={})["holidays"]
    now = datetime.now()
    if send and (not cr.in_working_hours(now, holidays) or now.hour < FROM_HOUR):
        return []
    if live:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", LOCK_PORT))
        except OSError:
            print("escalations: another run is already in progress - skipping.")
            return []
        _LOCK_SOCK = s
    state = _load()
    due = [r for r in tracker.load()["records"] if cr.escalate_due(r, now, holidays)]
    if not due:
        print("escalations: nobody due.")
        if send:
            _flush(state)
        return []
    ns = ns or bd.get_ns()

    def stopped(why):
        print(f"ABORT escalations: {why} - nothing sent.")
        if send:
            for r in due:
                _tell(state, r["id"], f"ABORT {' / '.join(str(o) for o in r.get('orders') or [])}: due escalating but "
                                      f"{why} - nothing sent, it tries again next run", now)
            _save(state)
            _flush(state)

    try:
        decs, idx, ctx = guard.assess_all(ns, due)
    except Exception as e:
        stopped(f"the mailbox could not be read to check for replies ({e})")
        return []
    if live and (idx.errors or len(idx.item_errors) > 5):
        stopped("part of the mailbox could not be read, so a reply could be missed")
        return []
    if live:
        ok, why = guard.mailbox_fresh(ns, idx)
        if not ok:
            stopped(why)
            return []

    results, done_orders, sent = [], set(), 0
    look_up = []                # held only for want of today's CTMS look-up: the work PC is asked for one

    def say(what, r, detail, tell=False):
        orders = " / ".join(str(o) for o in r.get("orders") or [])
        results.append((what, orders, detail))
        print(f"  {what:<15} {orders} ({r.get('delivery_date')}) -> {detail}")
        if tell and send:
            _tell(state, r["id"], f"{what} {orders} ({r.get('delivery_date')}): {detail}", now)
            _save(state)

    # the record naming the most orders first: one that shares an order with it is then covered by its email
    order = sorted(decs, key=lambda x: (cr.parse_day(x[0].get("delivery_date")) or now.date(),
                                        -len(x[0].get("orders") or [])))
    for r, dec in order:
        orders = {str(o) for o in r.get("orders") or []}
        if orders & done_orders:
            left = orders - done_orders
            say("HOLD" if left else "SKIP", r, (f"shares an order with one escalated just now, so {', '.join(sorted(left))} "
                                                "went unnamed - escalate it by hand") if left
                else "covered by the escalation just sent", tell=bool(left))
            continue
        asked = already_asked(r, idx.mails)
        what, why = decide(r, dec, asked, now)
        if what == "skip":
            say("SKIP", r, why)
            continue
        if what == "asked":
            say("HOLD", r, f"{why} and the contact has still not replied - it needs you", tell=True)
            if live:
                try:
                    import ctms_todo
                    state.setdefault("done", {}).setdefault(r["id"], {"at": f"{asked['at']:%d/%m/%Y %H:%M}",
                                                                      "subject": asked.get("subject"), "status": "sent"})
                    _save(state)
                    ctms_todo.escalated(r.get("orders", []), when=asked["at"].strftime("%Y-%m-%d %H:%M"))
                    tracker.escalated(r.get("orders", []))       # the ask has gone: the badge stops asking for it
                except Exception as e:
                    print(f"(could not mark {sorted(orders)} as escalated: {e})")
            continue
        if what == "hold":
            say("HOLD", r, f"not escalated: {why}", tell=True)
            if why.startswith(LOOKED):
                look_up.append(r)
            continue
        teams = teams_for(r.get("materials"))
        if not teams:
            say("HOLD", r, f"no reply, but no materials team for '{r.get('materials') or 'unknown product'}' - "
                           "escalate it by hand", tell=True)
            continue
        names = " and ".join(t["name"] for t in teams)
        if not live:
            say("WOULD ESCALATE", r, f"{names}, cc {r.get('to')} ({why})")
            continue
        if sent >= MAX_PER_RUN:
            say("WAIT", r, f"over the {MAX_PER_RUN} a run backstop - next run")
            continue
        entry = state.get("done", {}).get(r["id"])
        if entry and not retry_ready(entry, now):
            if entry.get("status") == "sent":
                say("SKIP", r, f"already sent {entry.get('at')}")
            else:
                say("HOLD", r, f"the try at {entry.get('at')} may not have gone and is not in Sent Items yet - check "
                               "Sent Items, it tries again after an hour if it never shows", tell=True)
            continue
        # The last look: the tracker and the newest mail again, judged again, right now.
        try:
            fresh = next((x for x in tracker.load()["records"] if x.get("id") == r["id"]), None)
            if fresh is None or not cr.escalate_due(fresh, datetime.now(), holidays):
                say("SKIP", r, "no longer due - booked, answered or escalated while this ran")
                continue
            n_err = len(idx.errors)
            idx.refresh()
            if len(idx.errors) > n_err:
                raise RuntimeError("; ".join(idx.errors[n_err:n_err + 2]))
            full = guard.with_mailbox_facts(ns, fresh)
            idx.mark_auto(*guard.relevant([full], idx, ctx))
            what, why = decide(fresh, cr.assess(full, idx.mails, ctx, idx.text_of, datetime.now()),
                               already_asked(fresh, idx.mails), datetime.now())
        except Exception as e:
            stopped(f"the re-check could not read everything ({e})")
            break
        if what != "escalate":
            say("HOLD" if what in ("hold", "asked") else "SKIP", r, f"{why} (seen in the last-second re-check)",
                tell=what in ("hold", "asked"))
            continue
        if mode() != "live":
            print("  STOP   automatic escalations were switched off mid-run - nothing more sent")
            break
        try:
            _send(ns, state, fresh, teams)
        except Exception as e:
            done_orders |= orders       # it may have gone: nothing else about these orders this run
            entry = state.get("done", {}).get(r["id"])
            if entry and entry.get("status") == "sending":
                entry["status"] = "uncertain"
                _save(state)
                say("FAIL", r, f"may not have gone to {names} ({e}) - check Sent Items", tell=True)
            else:
                say("FAIL", r, f"not sent to {names} ({e}) - tries again next run", tell=True)
            continue
        sent += 1
        done_orders |= orders
        say("SENT", r, f"escalated to {names}, cc {r.get('to')} ({why})", tell=True)
    if live and look_up:
        want_lookup(look_up)
    print(f"escalations: {sent if live else sum(1 for x in results if x[0] == 'WOULD ESCALATE')} "
          f"{'sent' if live else 'would be sent'}, {sum(1 for x in results if x[0] == 'HOLD')} held for you, "
          f"{sum(1 for x in results if x[0] == 'SKIP')} not needed.")
    if send:
        _save(state)
        _flush(state)
    return results


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"Mode: {mode()}. DRY RUN - nothing is sent from here.")
    run(send=False)
