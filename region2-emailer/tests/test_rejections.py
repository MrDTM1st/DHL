"""The Haulier Rejection Form's responses (rejections.py, 11/11): a Tier 1's no read from their reply, the job's
details from what the desk knows, held when anything is worked out rather than read, and sent only when the form
says it took it. Made-up orders, places and words only.

    python -m pytest tests/test_rejections.py
"""
import io
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rejections as R  # noqa: E402

NOW = datetime(2026, 11, 11, 12, 0)
TRACKER = [{"orders": ["9100001", "9100002"], "kind": "delivery", "delivery_date": "16/11/2026",
            "collection_site": "Steel Works", "collection_pc": "ZZ1 1AA", "postcode": "zz9 9zz",
            "materials": "15x rails", "product_codes": ["RAIL SHORT, 56E1, 260 GRADE, 13.716M, UNDRILLED"],
            "details": {"offloading": {"value": "HIAB"}, "rear_steer": {"value": "no"}}},
           {"orders": ["9100003"], "kind": "delivery", "delivery_date": "18/11/2026", "postcode": "ZZ8 8ZZ",
            "materials": "40x bagged ballast", "product_codes": ["BALLAST 1 TONNE BAGS"], "details": {}},
           {"orders": ["9100004"], "kind": "delivery", "delivery_date": "19/11/2026", "postcode": "ZZ7 7ZZ",
            "materials": "1x S&C panel", "product_codes": [], "details": {}}]


def _store():
    """A store of its own in a temp folder."""
    folder = tempfile.mkdtemp()
    R.PATH, R.LOCK = os.path.join(folder, "_rejections.json"), os.path.join(folder, "_rejections.json.lock")
    return folder


def test_the_directory_s_names_become_the_form_s_and_others_are_not_on_it():
    assert R.form_name("Hargreaves") == "Hargreaves Services"
    assert R.form_name("William Hamilton & Sons") == "Wm Hamilton & Sons"
    assert R.form_name("Hotspur Hire (HHL)") == "Hotspur Hire (HHL)" and R.form_name("dhl noc") == "DHL NOC"
    assert R.form_name("D.E. O'Reilly") == "DE O'Reilly" and R.form_name("DE O’Reilly") == "DE O'Reilly"
    assert R.form_name("AHT Logistics") is None and R.form_name("Some Tier Two Ltd") is None and R.form_name("") is None


def test_a_no_is_read_from_their_own_words_with_its_reason_and_a_quote_is_not_a_no():
    body = "Sorry, no HIAB available for that one.  From: Desk Sent: Monday Subject: 9100001 can you cover? Friday"
    assert R.own_words(body) == "Sorry, no HIAB available for that one."
    assert R.reason_of(R.own_words(body)) == ("No Availability - Vehicle Type", True)
    assert R.reason_of("Unfortunately we are unable to help on this occasion") == ("No Availability - General", True)
    assert R.reason_of("Can't do weekends, sorry") == ("No Availability - Night/Weekend", True)
    assert R.reason_of("No PTS drivers free, sorry") == ("No Availability - PTS", True)
    assert R.reason_of("Too short notice, can't help") == ("No Availability - Date of Job/Notice", True)
    assert R.reason_of("Can't do Friday but Monday is £450 + vat") is None          # a price: a quote
    assert R.reason_of("Yes we can do this, will confirm the driver") is None
    reason, sure = R.reason_of("Can't get a HIAB there on a Saturday")                       # two at once
    assert reason == "No Availability - Night/Weekend" and sure is False


def test_product_vehicle_and_rail_length_are_worked_out_the_desk_s_way():
    assert R.product_of("15x rails", "RAIL SHORT, 56E1") == "Rail"
    assert R.product_of("15x rails", adhoc=True) == "Adhoc - Rail / S&C"
    assert R.product_of("40x bagged ballast") == "Bagged Ballast" and R.product_of("loose ballast") == "Loose Ballast"
    assert R.product_of("S&C panel") == "S&C" and R.product_of("2x sleepers") == "Sleepers"
    assert R.product_of("something else") is None
    assert R.rail_length("RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED", "13.716M") == 18.288
    assert R.vehicle_of("Rail", "HIAB", 13.716) == ("Artic Hiab", True)
    assert R.vehicle_of("Rail", "SITE/NONE", 18.288) == ("60ft Flat", True)
    assert R.vehicle_of("Rail", "HIAB", 36.0) == ("Trombone Hiab", True)
    assert R.vehicle_of("Rail", None, 13.716) == (None, False)                             # offloading not known
    assert R.vehicle_of("Bagged Ballast", quantity="8 bagged ballast") == ("Rigid Flat / Hiab", True)
    assert R.vehicle_of("Sleepers", "HIAB", artic_access="no") == ("Rigid Flat / Hiab", True)


def test_a_response_takes_the_job_s_details_and_waits_while_anything_is_worked_out():
    rec = R.make(["9100002"], ["DHL NOC"], "No Availability - Vehicle Type", tracker=TRACKER, waitlist=[], now=NOW)
    assert rec["orders"] == ["9100002"] and rec["hauliers"] == ["DHL NOC"]
    assert (rec["date"], rec["collection"], rec["postcode"], rec["product"], rec["quantity"], rec["vehicle"],
            rec["rear_steer"], rec["consolidated"]) == ("2026-11-16", "Steel Works, ZZ1 1AA", "ZZ9 9ZZ", "Rail",
                                                        "15 rails", "Artic Hiab", "No", "No")
    assert rec["unsure"] == ["date"] and rec["status"] == "held"                          # the job's day: his to say
    assert R.gaps(rec) == ["the date of the job (NOT CERTAIN)"]
    told = R.make(["9100002"], ["DHL NOC"], "No Availability - Vehicle Type", given={"date": "16/11/2026"},
                  tracker=TRACKER, waitlist=[], now=NOW)
    assert told["unsure"] == [] and told["status"] == "ready"
    nothing = R.make(["9100099"], ["Lawsons"], "No Availability - General", tracker=TRACKER, waitlist=[], now=NOW)
    assert nothing["status"] == "held" and "the product" in R.gaps(nothing) and "the vehicle" in R.gaps(nothing)


def test_the_same_job_and_reason_ticks_another_haulier_and_a_known_no_is_not_added_twice():
    d = {"items": [], "auto": False}
    a = R.make(["9100001"], ["Lawsons Haulage"], "No Availability - General", given={"date": "16/11/2026"},
               tracker=TRACKER, waitlist=[], now=NOW)
    b = R.make(["9100001"], ["Tennant Transport"], "No Availability - General", given={"date": "16/11/2026"},
               tracker=TRACKER, waitlist=[], now=NOW)
    assert R.add(d, a) is a and R.add(d, b) is a and len(d["items"]) == 1
    assert a["hauliers"] == ["Lawsons Haulage", "Tennant Transport"]                      # the form's order
    assert R.add(d, R.make(["9100001"], ["Tennant"], "No Availability - General", given={"date": "16/11/2026"},
                           tracker=TRACKER, waitlist=[], now=NOW)) is None
    a["status"] = "sent"
    assert R.add(d, R.make(["9100001"], ["Lawsons"], "No Availability - General", given={"date": "16/11/2026"},
                           tracker=TRACKER, waitlist=[], now=NOW)) is None                # sent already
    other = R.make(["9100001"], ["Lawsons"], "No Availability - Rate", given={"date": "16/11/2026"},
                   tracker=TRACKER, waitlist=[], now=NOW)
    assert R.add(d, other) is other and len(d["items"]) == 2                              # another reason: its own


def test_the_answers_are_the_form_s_words_in_its_order_and_nothing_goes_with_a_gap():
    rec = R.make(["9100001"], ["DHL NOC"], "Other", given={"date": "16/11/2026", "other": "no driver with tickets"},
                 tracker=TRACKER, waitlist=[], now=NOW)
    out = R.answers(rec)
    assert out == [{"q": "Haulier Name", "tick": ["DHL NOC"]}, {"q": "Date of Job", "text": "11/16/2026"},
                   {"q": "Collection Site", "text": "Steel Works, ZZ1 1AA"},
                   {"q": "Delivery Postcode", "text": "ZZ9 9ZZ"}, {"q": "Consolidated Delivery", "pick": "No"},
                   {"q": "Product Type", "pick": "Rail"}, {"q": "Quantity", "text": "15 rails"},
                   {"q": "Vehicle Type", "pick": "Artic Hiab"}, {"q": "Rear-Steer", "pick": "No"},
                   {"q": "Rejection Reason", "pick": "Other", "other": "no driver with tickets"}]
    rec["product"] = ""
    try:
        R.answers(rec)
        raise AssertionError("a gap must stop it")
    except ValueError as e:
        assert "the product" in str(e)


def test_replies_make_responses_and_a_later_yes_or_a_price_takes_the_no_back():
    _store()
    asks = {"9100001": [{"name": "Lawsons Haulage", "email": "traffic@lawsons.example", "when": "10/11/2026 09:00"},
                        {"name": "A Tier Two Ltd", "email": "ops@tier2.example", "when": "10/11/2026 09:00"}],
            "9100002": [{"name": "Lawsons Haulage", "email": "traffic@lawsons.example", "when": "10/11/2026 09:00"},
                        {"name": "Tennant Transport", "email": "ops@tennant.example", "when": "10/11/2026 09:05"}],
            "9100003": [{"name": "Hargreaves", "email": "pat@hsg.example", "when": "10/11/2026 10:00"}],
            "9100004": [{"name": "JG Vesty", "email": "j@vesty.example", "when": "10/11/2026 10:00"}],
            "9100005": [{"name": "V Festa & Sons", "email": "r@festa.example", "when": "01/10/2026 10:00"}]}
    jobs = R.asked_jobs(asks, NOW)
    assert jobs[("Lawsons Haulage", "traffic@lawsons.example", "10/11/2026 09:00")] == ["9100001", "9100002"]
    assert not any(k[0] == "V Festa & Sons" for k in jobs)                               # asked too long ago
    assert not any("tier2" in k[1] for k in jobs)                                         # a Tier 2: not on the form

    def replies(_jobs):
        t = datetime(2026, 11, 10, 11, 0)
        return {("Lawsons Haulage", "traffic@lawsons.example", "10/11/2026 09:00"):
                [{"when": t, "body": "No availability that week sorry. From: Desk Sent: ..."}],
                ("Tennant Transport", "ops@tennant.example", "10/11/2026 09:05"):
                [{"when": t, "body": "Can't do it, no HIAB."},
                 {"when": t.replace(hour=12), "body": "Actually we can do it for £520 + vat"}],
                ("Hargreaves Services", "pat@hsg.example", "10/11/2026 10:00"):
                [{"when": t, "body": "Unable to cover this one, sorry"}],
                ("JG Vesty", "j@vesty.example", "10/11/2026 10:00"):
                [{"when": t, "body": "Unable to help"}]}

    keep = (R.details,)
    R.details = lambda orders, tracker=None, waitlist=None: keep[0](orders, TRACKER, [])
    try:
        assert R.refresh(asks=asks, replies=replies, now=NOW) == 2
        items = R.load()["items"]
        got = {(tuple(r["orders"]), tuple(r["hauliers"]), r["reason"]) for r in items}
        assert got == {(("9100001", "9100002"), ("Lawsons Haulage",), "No Availability - Date of Job/Notice"),
                       (("9100003",), ("Hargreaves Services",), "No Availability - General")}
        # Tennant came back with a price after their no; Vesty's job is S&C - neither is on the card
        assert R.refresh(asks=asks, replies=replies, now=NOW) == 0                        # nothing new the second time
    finally:
        R.details = keep[0]


def test_send_goes_only_when_the_form_takes_it_and_never_with_a_gap():
    _store()
    d = R.load()
    rec = R.make(["9100001"], ["DHL NOC"], "No Availability - Vehicle Type", tracker=TRACKER, waitlist=[], now=NOW)
    R.add(d, rec)
    R.save(d)
    asked = []

    def ok(action, **args):
        asked.append((action, args))
        return {"ok": True, "detail": "Filled in 10 answer(s), every one read back, and submitted: thanks"}, {
            "submitted": True}
    out = R.send(rec["id"], ask=ok)                         # held for its date: his press of Send is his word on it
    assert out["ok"] and "Rejection form sent" in out["said"]
    assert asked[0][0] == "form_fill" and asked[0][1]["submit"] is True
    assert asked[0][1]["answers"][1] == {"q": "Date of Job", "text": "11/16/2026"}
    assert R.find(R.load(), rec["id"])["status"] == "sent"
    assert R.send(rec["id"], ask=ok)["ok"] and len(asked) == 1                            # never twice

    other = R.make(["9100003"], ["Tennant"], "No Availability - General", tracker=TRACKER, waitlist=[], now=NOW)
    d = R.load()
    R.add(d, other)
    R.save(d)

    def refused(action, **args):
        asked.append(action)
        return {"ok": False, "detail": "DHL NOC isn't ticked - so it wasn't submitted."}, {"submitted": False}
    out = R.send(other["id"], ask=refused)
    assert not out["ok"] and "wasn't submitted" in out["said"]
    assert R.find(R.load(), other["id"])["status"] == "failed"

    gap = R.make(["9100099"], ["Lawsons"], "No Availability - General", tracker=TRACKER, waitlist=[], now=NOW)
    d = R.load()
    R.add(d, gap)
    R.save(d)
    n = len(asked)
    out = R.send(gap["id"], ask=refused)
    assert not out["ok"] and "the product" in out["said"] and len(asked) == n            # the work PC never asked


def test_a_send_never_heard_back_from_shows_as_failed_and_can_go_again():
    _store()
    d = R.load()
    rec = R.make(["9100001"], ["DHL NOC"], "No Availability - General", given={"date": "16/11/2026"},
                 tracker=TRACKER, waitlist=[], now=NOW)
    R.add(d, rec)
    rec.update(status="sending", sending_ts=time.time())
    R.save(d)
    assert R.send(rec["id"], ask=lambda *a, **k: ({}, {}))["said"] == "That one is being sent already."
    d = R.load()
    R.find(d, rec["id"])["sending_ts"] = time.time() - R.SENDING_FOR - 1
    R.save(d)
    assert R.panel()["open"][0]["status"] == "failed"


def test_the_card_s_commands_add_drop_and_switch_auto():
    _store()
    keep = R.details
    R.details = lambda orders, tracker=None, waitlist=None: keep(orders, TRACKER, [])
    try:
        def run(*argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = R.main(["rejections.py", *argv])
            return code, json.loads(buf.getvalue().strip().splitlines()[-1])
        code, out = run("add", json.dumps({"orders": "9100001 / 9100002", "hauliers": ["DHL NOC"],
                                           "reason": "No Availability - Vehicle Type", "date": "16/11/2026"}))
        assert code == 0 and "ready to send" in out["said"]
        rec = R.load()["items"][0]
        assert rec["orders"] == ["9100001", "9100002"] and rec["status"] == "ready" and rec["source"] == "added"
        assert run("add", json.dumps({"orders": "9100004", "hauliers": ["DHL NOC"],
                                      "reason": "No Availability - General"}))[1]["said"].startswith("S&C")
        assert run("add", json.dumps({"orders": "", "hauliers": ["DHL NOC"], "reason": "x"}))[0] == 1
        code, out = run("edit", rec["id"], json.dumps({"vehicle": "60ft Hiab"}))
        assert code == 0 and R.load()["items"][0]["vehicle"] == "60ft Hiab"
        assert run("auto", "on")[0] == 0 and R.panel()["auto"] is True
        code, out = run("drop", rec["id"])
        assert code == 0 and R.panel()["open"] == []
    finally:
        R.details = keep
