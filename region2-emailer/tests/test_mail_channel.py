"""Plain-assert tests for the work-mail channel - no Outlook, no Railway.

The rules that matter: Claude (the home PC's key) can search, read and draft,
but a send only ever lands on the approval list; only the dashboard key turns
an approval into a real send; the switch stops Claude's commands; and the
home PC refuses to send a draft that changed after he saw it.

Run:  python region2-emailer/tests/test_mail_channel.py
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ENGINE, "cloud"))
sys.path.insert(0, ENGINE)
os.environ["DASH_KEY"] = "dash-test-key"
os.environ["AGENT_KEY"] = "agent-test-key"

import server as S                      # noqa: E402
import mail_ops as M                    # noqa: E402
import desk_client as DC                # noqa: E402
import outlook_remote as R              # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

DASH, AGENT = "dash-test-key", "agent-test-key"
_httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{_httpd.server_address[1]}"
_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None, key=DASH):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Auth": key, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with _op.open(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def fresh():
    with S._lock:
        S._mail.update(on=True, queue=[], results={}, pending=[], seen=0.0)


def answer_next(ok=True, result=None):
    """Play the home PC once: take the next mail command, answer it."""
    code, cmd = call("/api/mail/next?wait=2", key=AGENT)
    assert code == 200 and cmd.get("id"), cmd
    res = result(cmd) if callable(result) else (result or {})
    assert call("/api/mail/result", {"id": cmd["id"], "ok": ok, "result": res}, key=AGENT)[0] == 200
    return cmd


def test_keys():
    fresh()
    assert call("/api/mail/command", {"action": "search", "args": {}}, key="nope")[0] == 401
    assert call("/api/mail/next", key=DASH)[0] == 401            # only the home PC pulls mail work
    assert call("/api/mail/approve", {"id": 1, "ok": True}, key=AGENT)[0] == 401
    assert call("/api/mail/control", {"on": False}, key=AGENT)[0] == 401


def test_claude_cannot_queue_a_real_send():
    fresh()
    for action in ("send_draft", "Send", "delete", ""):
        code, body = call("/api/mail/command", {"action": action, "args": {"id": "X", "fingerprint": "f"}}, key=AGENT)
        assert code == 400, (action, code, body)
    assert S._mail["queue"] == []


def test_search_round_trip():
    fresh()
    code, body = call("/api/mail/command", {"action": "search", "args": {"query": "MAN-1"}}, key=AGENT)
    assert code == 200
    cmd = answer_next(result={"messages": [{"id": "E1", "subject": "MAN-1"}]})
    assert cmd["action"] == "search" and cmd["args"]["query"] == "MAN-1"
    code, r = call(f"/api/mail/result?id={body['id']}&wait=1", key=AGENT)
    assert r["done"] and r["ok"] and r["result"]["messages"][0]["id"] == "E1"


def test_send_waits_for_his_ok_then_sends_exactly_that_draft():
    fresh()
    code, body = call("/api/mail/command", {"action": "send", "args": {"to": "a@x", "subject": "S"}}, key=AGENT)
    assert code == 200
    answer_next(result={"id": "DRAFT1", "fingerprint": "FP", "to": "a@x", "subject": "S", "body": "hi",
                        "why": "chase the haulier"})
    code, r = call(f"/api/mail/result?id={body['id']}", key=AGENT)
    assert r["result"]["approval"] == body["id"]
    assert S._mail["queue"] == []                                  # nothing queued for sending yet
    code, p = call("/api/mail/pending", key=DASH)
    assert p["pending"][0]["state"] == "waiting" and p["pending"][0]["why"] == "chase the haulier"
    assert "entry_id" not in p["pending"][0] and "fingerprint" not in p["pending"][0]
    code, st = call("/api/status", key=DASH)
    assert st["mail_pending"] == 1
    code, a = call("/api/mail/approve", {"id": body["id"], "ok": True}, key=DASH)
    assert code == 200 and a["state"] == "sending"
    assert call("/api/mail/approve", {"id": body["id"], "ok": True}, key=DASH)[0] == 409   # once only
    cmd = answer_next(result={"said": "sent to a@x"})
    assert cmd["action"] == "send_draft" and cmd["args"] == {"id": "DRAFT1", "fingerprint": "FP", "pending": body["id"]}
    code, p = call("/api/mail/pending", key=DASH)
    assert p["pending"][0]["state"] == "sent"


def test_refused_send_queues_nothing():
    fresh()
    code, body = call("/api/mail/command", {"action": "send", "args": {}}, key=AGENT)
    answer_next(result={"id": "D2", "fingerprint": "F", "to": "b@x", "subject": "S"})
    assert call("/api/mail/approve", {"id": body["id"], "ok": False}, key=DASH)[1]["state"] == "refused"
    assert S._mail["queue"] == []


def test_failed_draft_puts_nothing_on_the_list():
    fresh()
    call("/api/mail/command", {"action": "send", "args": {}}, key=AGENT)
    answer_next(ok=False, result={"error": "A new email needs a 'to'."})
    assert S._mail["pending"] == []


def test_switch_off_stops_claude():
    fresh()
    call("/api/mail/command", {"action": "read", "args": {"id": "E"}}, key=AGENT)
    assert call("/api/mail/control", {"on": False}, key=DASH)[1]["on"] is False
    assert S._mail["queue"] == []
    assert call("/api/mail/command", {"action": "search", "args": {}}, key=AGENT)[0] == 409
    call("/api/mail/control", {"on": True}, key=DASH)


def test_unclaimed_command_expires():
    fresh()
    code, body = call("/api/mail/command", {"action": "folders", "args": {}}, key=AGENT)
    with S._lock:
        S._mail["queue"][0]["queued_at"] -= S._MAIL_TTL + 1
    code, r = call(f"/api/mail/result?id={body['id']}", key=AGENT)
    assert r["done"] and not r["ok"] and "did not pick this up" in r["result"]["error"]


def test_mail_ops_helpers():
    assert M.addr_list("a@x; ;b@y,c@z") == "a@x; b@y; c@z"
    assert M.addr_list(["a@x", "", "b@y"]) == "a@x; b@y"
    h = M.text_to_html("<b>Hi</b>\nline 2")
    assert "&lt;b&gt;" in h and "<br>" in h
    assert M.insert_top("<html><body class='x'>QUOTE</body></html>", "NEW").index("NEW") < \
        M.insert_top("<html><body class='x'>QUOTE</body></html>", "NEW").index("QUOTE")
    f = M.fingerprint("a@x", "", "", "Subj", "Body  text\r\n")
    assert f == M.fingerprint("A@X", "", "", "subj", "body text")       # whitespace/case drift is the same email
    assert f != M.fingerprint("a@x; evil@y", "", "", "Subj", "Body text")
    assert f != M.fingerprint("a@x", "", "", "Subj", "Body text changed")
    assert "''" in M.dasl_like("O'Brien") and "%" not in M.dasl_like("50%").split("LIKE")[1].strip("'%")[:2]
    assert M.clamp("x", 1, 10, 5) == 5 and M.clamp(99, 1, 10, 5) == 10


def test_send_draft_refuses_a_changed_draft():
    class Item:
        Class, Sent, To, CC, BCC, Subject, Body, EntryID = 43, False, "a@x", "", "", "S", "hello", "D1"
        Attachments = type("A", (), {"Count": 0})()
        sent = False

        def Send(self):
            self.sent = True
    it = Item()
    ns = type("NS", (), {"GetItemFromID": lambda self, i, s: it})()
    store = type("St", (), {"StoreID": "s"})()
    good = M.fingerprint("a@x", "", "", "S", "hello")
    try:
        M.do_send_draft(ns, None, store, {"id": "D1", "fingerprint": "stale"})
        raise AssertionError("sent a changed draft")
    except M.Fail:
        assert not it.sent
    try:
        M.do_send_draft(ns, None, store, {"id": "D1"})
        raise AssertionError("sent with no fingerprint")
    except M.Fail:
        assert not it.sent
    assert M.do_send_draft(ns, None, store, {"id": "D1", "fingerprint": good})["to"] == "a@x" and it.sent


def test_desk_client_order():
    old = {k: os.environ.pop(k, None) for k in ("CTMS_DESK_URL", "CTMS_DESK_KEY", "RAILWAY_TOKEN",
                                                 "RAILWAY_API_TOKEN")}
    try:
        os.environ.update(CTMS_DESK_URL="https://d.example/", CTMS_DESK_KEY="k")
        assert DC.desk() == ("https://d.example", "k")
        del os.environ["CTMS_DESK_KEY"]
        DC.from_railway, saved = (lambda: ("https://r.example", "rk")), DC.from_railway
        try:
            if not os.path.exists(os.path.join(ENGINE, "cloud.json")):
                assert DC.desk() == ("https://r.example", "rk")
        finally:
            DC.from_railway = saved
        if not os.path.exists(os.path.join(ENGINE, "cloud.json")):
            try:
                DC.desk()
                raise AssertionError("found a desk with nothing set")
            except DC.NoDesk as e:
                assert "RAILWAY_TOKEN" in str(e)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def test_outlook_remote_end_to_end():
    fresh()
    R.BASE, R.KEY = BASE, AGENT
    t = threading.Thread(target=lambda: answer_next(result={"folders": [{"path": "Inbox"}]}), daemon=True)
    t.start()
    assert R.ask("folders", {}, patience=20)["folders"][0]["path"] == "Inbox"
    t.join()
    t = threading.Thread(target=lambda: answer_next(ok=False, result={"error": "no such message"}), daemon=True)
    t.start()
    try:
        R.ask("read", {"id": "zz"}, patience=20)
        raise AssertionError("a failure came back as success")
    except R.Stop as e:
        assert e.code == 2 and "no such message" in str(e)
    t.join()


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    _httpd.shutdown()
    sys.exit(1 if failed else 0)
