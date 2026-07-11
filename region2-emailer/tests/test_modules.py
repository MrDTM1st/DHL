"""Plain-assert tests for the feature modules — no Outlook needed.

Run:  python3 region2-emailer/tests/test_modules.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules import handover, profiles, self_update, site_matching  # noqa: E402


def test_site_matching(tmp):
    store = site_matching.SiteStore(os.path.join(tmp, "_sites.json"))
    store.add_sites(["Acme Warehouse - Leeds", "Borle Metals Ltd", "Cardiff Depot"])

    assert store.match("ACME WAREHOUSE - LEEDS") == ("Acme Warehouse - Leeds", "exact")
    site, how = store.match("Acme Warehous Leeds")          # typo -> fuzzy
    assert (site, how) == ("Acme Warehouse - Leeds", "fuzzy"), (site, how)

    site, suggestions = store.match("B.C.M. (Borle) Metals")
    assert site is None and "Borle Metals Ltd" in suggestions, suggestions

    assert store.request_decision("B.C.M. (Borle) Metals", "order 7114852") is None
    assert store.pending()[0]["raw"] == "B.C.M. (Borle) Metals"
    assert store.resolve("B.C.M. (Borle) Metals", "Borle Metals Ltd")
    assert store.pending() == []
    assert store.match("b.c.m. (borle) METALS") == ("Borle Metals Ltd", "learned")

    # store survives reload
    store2 = site_matching.SiteStore(os.path.join(tmp, "_sites.json"))
    assert store2.match("B.C.M. (Borle) Metals") == ("Borle Metals Ltd", "learned")

    # resolving to a brand-new site grows the universe
    store2.resolve("Some Raw Name", "Newport Sidings")
    assert "Newport Sidings" in store2.sites()

    # rubbish input never crashes
    assert store2.match("") == (None, [])
    assert store2.match(None) == (None, [])
    print("site_matching OK")


def test_profiles(tmp):
    team = {"me": "dee@dhl.com", "internal_domains": ["dhl.com"],
            "members": [{"name": "Dee Opoku", "email": "dee@dhl.com"},
                        {"name": "Team Mate", "email": "mate@dhl.com"}]}

    to, cc, removed = profiles.clean_recipients(
        "supplier@acme.co.uk; Dee@DHL.com, mate@dhl.com",
        cc="dee@dhl.com; supplier@acme.co.uk", me="dee@dhl.com")
    assert to == "supplier@acme.co.uk; mate@dhl.com", to
    assert cc == "", cc                                # self dropped, dup dropped
    assert len(removed) == 2, removed

    assert profiles.find_member(team, "mate@dhl.com")["name"] == "Team Mate"
    assert profiles.find_member(team, "team mate")["email"] == "mate@dhl.com"
    assert profiles.find_member(team, "mate")["email"] == "mate@dhl.com"
    assert profiles.find_member(team, "nobody@x.com") is None

    assert profiles.is_internal("a@dhl.com", team)
    assert profiles.is_internal("a@mail.dhl.com", team)
    assert not profiles.is_internal("a@notdhl.com", team)
    ints, exts = profiles.split_internal_external("a@dhl.com; b@acme.com", team)
    assert ints == ["a@dhl.com"] and exts == ["b@acme.com"]
    print("profiles OK")


def test_self_update(tmp):
    team_path = os.path.join(tmp, "team.json")
    with open(team_path, "w") as f:
        json.dump({"members": [{"name": "Dee", "email": "dee@dhl.com"}],
                   "update_email": {"subject_prefix": "R2 UPDATE",
                                    "allowed_senders": []}}, f)
    store = site_matching.SiteStore(os.path.join(tmp, "_sites.json"))
    settings_path = os.path.join(tmp, "_settings.json")
    seen_path = os.path.join(tmp, "_updates_seen.json")

    msgs = [
        {"id": "m1", "sender": "dee@dhl.com", "subject": "R2 UPDATE sites",
         "body": "site: ACME W/H LEEDS => Acme Warehouse - Leeds\n"
                 "> add site: Newport Sidings\n"
                 "team add: New Person <new.person@dhl.com>\n"
                 "setting: chase_days = 3"},
        {"id": "m2", "sender": "stranger@evil.com", "subject": "R2 UPDATE hack",
         "body": "team add: Bad Actor <bad@evil.com>"},
        {"id": "m3", "sender": "dee@dhl.com", "subject": "lunch?", "body": "site: a => b"},
    ]
    applied = self_update.process_messages(msgs, store, team_path, settings_path, seen_path)
    assert len(applied) == 4, applied
    assert store.match("acme w/h leeds")[0] == "Acme Warehouse - Leeds"
    assert "Newport Sidings" in store.sites()
    team = json.load(open(team_path))
    assert any(m["email"] == "new.person@dhl.com" for m in team["members"])
    assert not any(m.get("email") == "bad@evil.com" for m in team["members"])
    assert json.load(open(settings_path))["chase_days"] == "3"

    # replay: nothing applied twice
    assert self_update.process_messages(msgs, store, team_path, settings_path, seen_path) == []

    # newly added member may now send updates; removal works
    applied = self_update.process_messages(
        [{"id": "m4", "sender": "new.person@dhl.com", "subject": "r2 update",
          "body": "team remove: new.person@dhl.com"}],
        store, team_path, settings_path, seen_path)
    assert applied == ["team remove: new.person@dhl.com"], applied
    print("self_update OK")


def test_handover(tmp):
    path = os.path.join(tmp, "_handover.json")
    tracker = [
        {"orders": ["7114852", "7114854"], "to": "acme@x.com", "materials": "STEEL",
         "emailed_at": "2026-07-01 09:00", "chases": 1, "reply_at": "", "sendoff_ready": False},
        {"orders": ["6054999"], "to": "b@x.com",
         "emailed_at": "", "reply_at": "", "sendoff_ready": False},
        {"orders": ["7000000"], "to": "c@x.com",
         "emailed_at": "2026-07-01", "reply_at": "2026-07-02", "sendoff_ready": True},
    ]
    state = handover.start(path, days=5, cover_name="Team Mate",
                           cover_email="mate@dhl.com", notes="Ring Acme Tuesday",
                           forward=True, today="2026-07-06")
    assert state["end"] == "2026-07-11"
    assert handover.is_active(state, today="2026-07-10")
    assert not handover.is_active(state, today="2026-07-11")   # return date = back

    email = handover.build_handover_email(state, tracker, sender_name="Dee")
    assert email["to"] == "mate@dhl.com"
    assert "7114852 / 7114854" in email["message"]
    assert "chased x1" in email["message"]
    assert "6054999" in email["message"] and "email not sent yet" in email["message"]
    assert "7000000" not in email["message"]                   # finished: not handed over
    assert "Ring Acme Tuesday" in email["message"]

    ids = handover.plan_forwards(state, [
        {"id": "a", "sender": "acme@x.com"},
        {"id": "b", "sender": "mate@dhl.com"},                 # from cover: skip
        {"id": "c", "sender": "dee@dhl.com"},                  # from me: skip
    ], me="dee@dhl.com", today="2026-07-07")
    assert ids == ["a"], ids
    handover.mark_forwarded(path, ids)
    assert handover.plan_forwards(handover.load(path), [{"id": "a", "sender": "acme@x.com"}],
                                  me="dee@dhl.com", today="2026-07-07") == []

    assert handover.tick(path, today="2026-07-10") == "active"
    assert handover.tick(path, today="2026-07-11") == "ended"  # auto-stop on return date
    assert handover.tick(path, today="2026-07-12") == "off"
    handover.start(path, 3, "X", "x@dhl.com", today="2026-07-06")
    assert handover.end(path)["active"] is False               # manual stop
    ps = handover.panel_state(handover.load(path))
    assert "forwarded_ids" not in ps and ps["cover_email"] == "x@dhl.com"
    print("handover OK")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        test_site_matching(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        test_profiles(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        test_self_update(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        test_handover(tmp)
    print("ALL MODULE TESTS PASSED")
