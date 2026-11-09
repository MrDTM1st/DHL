"""The Network Rail team email when a site asks for another day than we offered (his rule 09/11/2026): an earlier day
is asked about first and the order stays put; a day in a later week moves it and the team is told. Made-up orders.

    python -m pytest tests/test_nr_date.py -q
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctms_run_plan as P  # noqa: E402
import nr_date as N  # noqa: E402
import tracker as T  # noqa: E402

OFFERED = "20/11/2026"            # a Friday


def _rec(order="9100501", date=OFFERED, materials="60x sleepers", **kw):
    r = {"id": T._key([order], date), "orders": [order], "kind": "delivery", "delivery_date": date,
         "materials": materials, "site": "Example Yard", "worksite": "Exampleton", "postcode": "EX1 1AA",
         "orig_entryid": "SENT-EID", "reply_at": "2026-11-09 10:00", "sendoff_ready": True,
         "details": {"date": {"value": "", "confidence": "high", "options": []},
                     "time": {"earliest": "08:00", "latest": "10:00", "confidence": "high"},
                     "offloading": {"value": "HIAB", "confidence": "high", "raw": "yes"},
                     "artic_access": {"value": "yes", "confidence": "high"},
                     "contact": {"name": "sam example", "phone": "07700 900123", "confidence": "high"},
                     "what3words": {"value": "///one.two.three"}}}
    r.update(kw)
    return r


_REAL_PATH = T.PATH


def _tracker(tmp, recs):
    T.PATH = os.path.join(tmp, "tracker.json")
    T.save({"records": recs})


def teardown_function(_f):
    T.PATH = _REAL_PATH          # never leave the real tracker pointed at a temp folder


def test_earlier_later_week_or_neither():
    assert N.classify(OFFERED, "07/11/2026") == "earlier"
    assert N.classify(OFFERED, "19/11/2026") == "earlier"              # one day before is still before
    assert N.classify(OFFERED, "23/11/2026") == "later"                # the Monday after: another week commencing
    assert N.classify(OFFERED, "20/11/2026") is None
    assert N.classify("16/11/2026", "20/11/2026") is None              # later, same week: just a move
    assert N.classify(OFFERED, "next week") is None and N.classify("", "07/11/2026") is None


def test_the_team_comes_from_the_material_and_never_copies_dhl_road():
    assert N.team_for(_rec(materials="279x sleepers"))["name"] == "SCO Sleepers & Troughing"
    assert "SleeperContractManagementTeam@networkrail.co.uk" in N.team_for(_rec(materials="2x bearers"))["to"]
    assert N.team_for(_rec(materials="13x rails"))["to"] == ["SteelMaterials@networkrail.co.uk"]
    assert N.team_for(_rec(materials="80x bagged ballast"))["to"] == ["Track.Aggregates@networkrail.co.uk"]
    assert N.team_for(_rec(materials="1x S&C crossing")) is None        # no team on the list: he is asked
    assert N.team_for(_rec(materials="")) is None
    assert N._addrs("Track.Aggregates@networkrail.co.uk; DHLRoad@networkrail.co.uk") == "Track.Aggregates@networkrail.co.uk"


def test_an_earlier_day_holds_the_order_and_drafts_the_question():
    r = _rec()
    d = {"records": [r]}
    assert N.on_new_date(d, r, "07/11/2026", "the site's reply", reply_eid="REPLY-EID") is False
    assert r["delivery_date"] == OFFERED and r["id"] == T._key(["9100501"], OFFERED)     # NOT moved
    nd = r["nr_date"]
    assert (nd["kind"], nd["offered"], nd["asked"], nd["state"]) == ("earlier", OFFERED, "07/11/2026", "to_send")
    assert nd["reply_eid"] == "REPLY-EID" and "SCOSleepers&Troughing@networkrail.co.uk" in nd["to"]
    assert "allowed" in nd["message"] and "stock" in nd["message"] and "07/11" in nd["subject"]
    assert N.held(r) == OFFERED
    # the same day seen again (a re-read, his confirm) drafts nothing new
    assert N.on_new_date(d, r, "07/11/2026", "your confirm") is False and r["nr_date"]["at"] == nd["at"]


def test_a_later_week_moves_the_order_and_drafts_the_notice():
    r = _rec(materials="13x rails")
    d = {"records": [r]}
    assert N.on_new_date(d, r, "30/11/2026", "the site's reply", reply_eid="REPLY-EID") is True
    assert r["delivery_date"] == "30/11/2026" and r["date_was"] == OFFERED
    nd = r["nr_date"]
    assert nd["kind"] == "later" and nd["state"] == "to_send" and nd["to"] == "SteelMaterials@networkrail.co.uk"
    assert "30/11" in nd["message"] and "20/11" in nd["message"]
    assert N.held(r) is None


def test_a_later_day_in_the_same_week_just_moves():
    r = _rec(date="16/11/2026")
    d = {"records": [r]}
    assert N.on_new_date(d, r, "19/11/2026", "the site's reply") is True
    assert "nr_date" not in r and r["delivery_date"] == "19/11/2026"


def test_no_em_dashes_in_what_is_written():
    for kind, asked in (("earlier", "07/11/2026"), ("later", "30/11/2026")):
        subject, message = N.draft(_rec(), kind, OFFERED, asked)
        assert "—" not in subject + message and "–" not in subject + message


def test_send_then_yes_moves_it():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec()
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply", reply_eid="REPLY-EID")
        _tracker(tmp, d["records"])
        sent = []
        out = N.send(r["id"], {"message": "Hi all — edited"},
                     sender=lambda nd, to, cc, subj, msg: (sent.append((nd["reply_eid"], to, msg)) or True, "sent to " + to))
        assert out["ok"], out
        assert sent[0][0] == "REPLY-EID" and "—" not in sent[0][2]     # the trail is forwarded; no em dash
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "sent" and rec["delivery_date"] == OFFERED
        assert not N.send(r["id"], {}, sender=lambda *a: (True, ""))["ok"]   # never twice
        out = N.answer(r["id"], True)
        assert out["ok"], out
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "allowed" and rec["delivery_date"] == "07/11/2026"
        assert rec["date_moved_by"] == "Network Rail's OK"


def test_no_keeps_the_offered_day_and_the_ctms_update_types_it():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec()
        r["details"]["date"].update(value="07/11/2026", options=["07/11/2026"])
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply")
        r["nr_date"]["state"] = "sent"
        _tracker(tmp, d["records"])
        assert N.answer(r["id"], False)["ok"]
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "not_allowed" and rec["delivery_date"] == OFFERED
        assert rec["details"]["date"]["value"] == OFFERED and rec["details"]["date"]["asked"] == "07/11/2026"


def test_send_needs_someone_in_to():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec(materials="1x S&C crossing")
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply")
        assert r["nr_date"]["to"] == ""
        _tracker(tmp, d["records"])
        out = N.send(r["id"], {}, sender=lambda *a: (True, ""))
        assert not out["ok"] and "Who is the Network Rail team" in out["said"]


def test_the_ctms_run_types_nothing_while_network_rail_is_asked():
    r = _rec()
    r["details"]["date"].update(value="07/11/2026", options=["07/11/2026"])
    N.on_new_date({"records": [r]}, r, "07/11/2026", "the site's reply")
    item = {"id": "t1", "kind": "update", "orders": ["9100501"], "what": "Sam replied - update the order"}
    p = P.plan([item], [r], {})[0]
    assert p["status"] == "yours" and "Waiting on Network Rail" in p["explain"][0]
    # their no: the run goes on the day we offered, not the site's earlier one
    r["nr_date"]["state"] = "not_allowed"
    found = {f"9100501|{OFFERED}": {"lines": [{"ref": "9100501-1-1", "status": "UNSCHEDULED", "deliver_by": "20/11/26 16:01"}]}}
    p = P.plan([item], [r], found)[0]
    assert p["status"] != "yours" and p["set"].get("deliver", "").startswith("20/11/26"), p


def test_dismiss_an_earlier_day_moves_it_without_an_email():
    with tempfile.TemporaryDirectory() as tmp:
        r = _rec()
        d = {"records": [r]}
        N.on_new_date(d, r, "07/11/2026", "the site's reply")
        _tracker(tmp, d["records"])
        assert N.dismiss(r["id"])["ok"]
        rec = T.load()["records"][0]
        assert rec["nr_date"]["state"] == "dismissed" and rec["delivery_date"] == "07/11/2026"


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("ok")
