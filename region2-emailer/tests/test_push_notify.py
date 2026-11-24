"""Phone alerts (push_notify.py, 24/11): the devices kept on the home PC, one per endpoint; an alert sent to every one,
a gone one (404/410) dropped; no pywebpush said, never raised; the key made once, only its public half on the panel;
and the agent's push_subscribe / push_test / push_unsubscribe. Made-up push addresses only, and the network is never
called - pywebpush's webpush is stood in for.

    python -m pytest tests/test_push_notify.py
"""
import json
import os
import subprocess
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import push_notify as P  # noqa: E402

FAKE_KEYS = {"private_key": "made-up-private-key", "public_key": "made-up-public-key", "made": "2026-11-24 09:00"}


def sub(n, host="fcm.googleapis.com"):
    """A browser's PushSubscription JSON, made up: a 65-byte p256dh and a 16-byte auth, as browsers give them."""
    return {"endpoint": f"https://{host}/fcm/send/device-{n}", "expirationTime": None,
            "keys": {"p256dh": P._b64u(bytes([4]) + bytes([n % 256]) * 64), "auth": P._b64u(bytes([n % 256]) * 16)}}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """The key, the devices and cloud.json in the test's own folder, and a lock of its own."""
    monkeypatch.setattr(P, "VAPID", str(tmp_path / "_vapid.json"))
    monkeypatch.setattr(P, "SUBS", str(tmp_path / "_push_subs.json"))
    monkeypatch.setattr(P, "CLOUD", str(tmp_path / "cloud.json"))
    monkeypatch.setattr(P, "LOCK", "push_notify_test_" + uuid.uuid4().hex)
    return tmp_path


def fake_keys():
    with open(P.VAPID, "w", encoding="utf-8") as f:
        json.dump(FAKE_KEYS, f)


class Gone(Exception):
    """What pywebpush raises when the push service turns it down: the answer rides on .response."""
    def __init__(self, code):
        super().__init__(f"Push failed: {code}")
        self.response = type("Response", (), {"status_code": code})()


def stand_in(monkeypatch, answers=None):
    """webpush() stood in for -> the calls it got. answers: endpoint -> the status code its push service gives."""
    calls = []

    def webpush(subscription_info, data=None, vapid_private_key=None, vapid_claims=None, **kw):
        calls.append({"sub": subscription_info, "data": json.loads(data), "key": vapid_private_key,
                      "claims": vapid_claims, **kw})
        vapid_claims["aud"] = "https://push.service.example"        # pywebpush writes this into the claims it gets
        code = (answers or {}).get(subscription_info["endpoint"])
        if code:
            raise Gone(code)
        return type("Response", (), {"status_code": 201})()

    monkeypatch.setattr(P, "_webpush", lambda: webpush)
    return calls


# ---------- the devices ----------
def test_one_device_per_endpoint_and_unsubscribe_forgets_it():
    assert P.count() == 0
    r = P.subscribe(sub(1))
    assert r["ok"] and r["new"] and r["subs"] == 1 and "1 device gets them" in r["said"]
    again = sub(1)
    again["keys"]["auth"] = P._b64u(b"\x07" * 16)                    # the same browser again, new keys
    r = P.subscribe(again)
    assert r["ok"] and not r["new"] and P.count() == 1
    kept = json.load(open(P.SUBS, encoding="utf-8"))["subs"]
    assert kept[0]["keys"]["auth"] == again["keys"]["auth"] and kept[0]["added"]
    assert P.subscribe(sub(2, "web.push.apple.com"))["subs"] == 2
    assert P.subscribe(sub(3, "updates.push.services.mozilla.com"))["subs"] == 3
    assert P.unsubscribe(sub(1)["endpoint"]) is True and P.count() == 2
    assert P.unsubscribe(sub(1)["endpoint"]) is False and P.count() == 2
    assert P.unsubscribe("") is False and P.unsubscribe(None) is False
    assert [s["endpoint"] for s in json.load(open(P.SUBS, encoding="utf-8"))["subs"]] == \
        [sub(2, "web.push.apple.com")["endpoint"], sub(3, "updates.push.services.mozilla.com")["endpoint"]]


def test_what_isnt_a_browser_push_subscription_is_refused_and_nothing_kept():
    bad_keys = sub(4)
    bad_keys["keys"]["p256dh"] = P._b64u(b"\x04" * 10)
    no_keys = sub(5)
    del no_keys["keys"]
    plain_http = sub(6)
    plain_http["endpoint"] = plain_http["endpoint"].replace("https://", "http://")
    for s in (None, "not a dict", {}, no_keys, bad_keys, plain_http, sub(7, "192.168.1.10"),
              sub(8, "evil.example"), sub(9, "googleapis.com.evil.example")):
        r = P.subscribe(s)
        assert r["ok"] is False and r["said"], s
    assert P.count() == 0 and not os.path.exists(P.SUBS)


def test_the_oldest_device_goes_when_the_list_is_full(monkeypatch):
    monkeypatch.setattr(P, "MAX_SUBS", 3)
    for n in range(1, 6):
        P.subscribe(sub(n))
    assert [s["endpoint"] for s in json.load(open(P.SUBS, encoding="utf-8"))["subs"]] == \
        [sub(n)["endpoint"] for n in (3, 4, 5)]


def test_a_list_that_cant_be_read_is_never_written_over():
    with open(P.SUBS, "w", encoding="utf-8") as f:
        f.write("{ half a file")
    r = P.subscribe(sub(1))
    assert r["ok"] is False and "can't be read" in r["said"]
    assert open(P.SUBS, encoding="utf-8").read() == "{ half a file" and P.count() == 0


# ---------- sending ----------
def test_notify_sends_to_every_device_drops_a_gone_one_and_counts(monkeypatch):
    fake_keys()
    for n in (1, 2, 3):
        P.subscribe(sub(n))
    with open(P.CLOUD, "w", encoding="utf-8") as f:
        json.dump({"url": "https://desk.example/", "agent_key": "x"}, f)
    calls = stand_in(monkeypatch, {sub(2)["endpoint"]: 410})
    res = P.notify("Needs you now", "Someone asks for a delivery time", "/", tag="mail-1")
    assert res == {"sent": 2, "dropped": 1, "error": None}
    assert [c["sub"]["endpoint"] for c in calls] == [sub(n)["endpoint"] for n in (1, 2, 3)]
    assert [s["endpoint"] for s in json.load(open(P.SUBS, encoding="utf-8"))["subs"]] == \
        [sub(1)["endpoint"], sub(3)["endpoint"]]
    for c in calls:
        assert c["data"] == {"title": "Needs you now", "body": "Someone asks for a delivery time", "url": "/",
                             "tag": "mail-1"}
        assert c["key"] == FAKE_KEYS["private_key"]                   # signed with the private key, on this PC
        assert c["claims"]["sub"] == "https://desk.example"           # the dashboard's own address is the contact
        assert c["ttl"] == P.TTL and c["timeout"] == P.TIMEOUT and c["headers"] == {"Urgency": "high"}
    # each device got claims of its own: the "aud" pywebpush wrote for one never went to the next
    assert len({id(c["claims"]) for c in calls}) == 3
    # a 404 is gone too
    calls = stand_in(monkeypatch, {sub(3)["endpoint"]: 404})
    assert P.notify("Again", "x") == {"sent": 1, "dropped": 1, "error": None} and P.count() == 1


def test_any_other_failure_is_said_and_the_device_kept(monkeypatch):
    fake_keys()
    P.subscribe(sub(1))
    P.subscribe(sub(2))
    stand_in(monkeypatch, {sub(1)["endpoint"]: 403, sub(2)["endpoint"]: 500})
    res = P.notify("Test alert", "Phone alerts are working")
    assert res["sent"] == 0 and res["dropped"] == 0 and "403" in res["error"] and "1 more" in res["error"]
    assert P.count() == 2

    def down(*a, **kw):
        raise ConnectionError("no network")
    monkeypatch.setattr(P, "_webpush", lambda: down)
    res = P.notify("Test alert", "Phone alerts are working")
    assert res["sent"] == 0 and "no network" in res["error"] and P.count() == 2


def test_no_devices_is_nothing_sent_and_no_fault(monkeypatch):
    fake_keys()
    calls = stand_in(monkeypatch)
    assert P.notify("Test alert", "Phone alerts are working") == {"sent": 0, "dropped": 0, "error": None}
    assert calls == []


def test_what_is_sent_stays_on_the_desk_and_inside_the_push_services_limit(monkeypatch):
    fake_keys()
    P.subscribe(sub(1))
    calls = stand_in(monkeypatch)
    P.notify("T" * 500, "é" * 5000, url="https://somewhere.example/x")
    d = calls[0]["data"]
    assert d["url"] == "/" and len(d["title"]) == 120 and "tag" not in d
    assert len(json.dumps(d, ensure_ascii=False).encode("utf-8")) <= 3000
    P.notify("T", "B", url="//somewhere.example/x")
    assert calls[1]["data"]["url"] == "/"


def test_without_pywebpush_notify_says_so_and_never_raises(monkeypatch):
    fake_keys()
    P.subscribe(sub(1))
    monkeypatch.setitem(sys.modules, "pywebpush", None)              # import pywebpush -> ImportError
    res = P.notify("Test alert", "Phone alerts are working")
    assert res["sent"] == 0 and res["dropped"] == 0 and "pywebpush" in res["error"]
    assert P.count() == 1                                             # the device is kept for when it is installed


def test_importing_the_module_needs_nothing_but_the_standard_library():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import push_notify; "
            "print(sorted(m for m in ('pywebpush', 'py_vapid', 'cryptography', 'requests') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code, ROOT], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "[]", out.stderr


# ---------- the key ----------
def test_the_key_is_made_once_and_only_its_public_half_goes_up():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = P.public_key()
    raw = P._unb64u(key)
    assert len(raw) == 65 and raw[0] == 4 and "=" not in key       # an uncompressed P-256 point, base64url
    assert P.public_key() == key                                     # made once, then kept
    kept = json.load(open(P.VAPID, encoding="utf-8"))
    d = int.from_bytes(P._unb64u(kept["private_key"]), "big")
    pub = ec.derive_private_key(d, ec.SECP256R1()).public_key()
    assert pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint) == raw
    panel = P.panel()
    assert panel["vapid"] == key and panel["subs"] == 0
    assert kept["private_key"] not in json.dumps(panel)


def test_a_key_file_that_cant_be_read_is_never_replaced(monkeypatch):
    with open(P.VAPID, "w", encoding="utf-8") as f:
        f.write("not json")
    assert P.public_key() == ""
    assert open(P.VAPID, encoding="utf-8").read() == "not json"
    panel = P.panel()
    assert panel["vapid"] == "" and "_vapid.json" in panel["error"]
    calls = stand_in(monkeypatch)
    P.subscribe(sub(1))
    res = P.notify("T", "B")
    assert res["sent"] == 0 and "can't be read" in res["error"] and calls == []
    assert open(P.VAPID, encoding="utf-8").read() == "not json"


def test_the_panel_says_when_pywebpush_is_missing(monkeypatch):
    fake_keys()
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "pywebpush" else object())
    assert P.panel() == {"vapid": FAKE_KEYS["public_key"], "subs": 0, "error": P.NO_PYWEBPUSH}


# ---------- the agent ----------
def _no_pywebpush():
    raise ImportError("No module named 'pywebpush'")


def test_the_agents_subscribe_test_and_unsubscribe(monkeypatch):
    import agent
    fake_keys()
    calls = stand_in(monkeypatch)
    r = agent._push_command("push_test", {})
    assert r["ok"] is False and r["said"] == "no device has alerts on - turn them on first." and calls == []
    r = agent._push_command("push_subscribe", {"data": {"sub": sub(1)}})
    assert r["ok"] and P.count() == 1
    assert agent._push_command("push_subscribe", {"data": {}})["ok"] is False
    assert agent._push_command("push_subscribe", {"data": "junk"})["ok"] is False
    r = agent._push_command("push_test", {})
    assert r["ok"] and r["said"] == "test alert sent to 1 device."
    assert calls[0]["data"] == {"title": "Test alert", "body": "Phone alerts are working", "url": "/"}
    up = agent._push()                                               # what goes up on the panel
    assert up["vapid"] == FAKE_KEYS["public_key"] and up["subs"] == 1
    r = agent._push_command("push_unsubscribe", {"data": {"endpoint": sub(1)["endpoint"]}})
    assert r["ok"] and P.count() == 0
    # the device gone at its push service: said, and off the list
    P.subscribe(sub(2))
    stand_in(monkeypatch, {sub(2)["endpoint"]: 410})
    r = agent._push_command("push_test", {})
    assert r["ok"] is False and "any more" in r["said"] and P.count() == 0
    # pywebpush missing on the home PC: said, never raised
    P.subscribe(sub(3))
    monkeypatch.setattr(P, "_webpush", _no_pywebpush)
    r = agent._push_command("push_test", {})
    assert r["ok"] is False and "pywebpush" in r["said"]


def test_the_agent_never_falls_over_push(monkeypatch):
    import agent

    def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(P, "panel", boom)
    monkeypatch.setattr(P, "subscribe", boom)
    assert agent._push() == {}
    r = agent._push_command("push_subscribe", {"data": {"sub": sub(1)}})
    assert r["ok"] is False and "disk on fire" in r["said"]
