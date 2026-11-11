"""Plain-assert tests for the hosted dashboard's own rules (cloud/server.py) - no browser, no work PC.

Covers: a command left from before the home PC went away is never handed out when it comes back, a Teams
message never goes round the NOC list, one that went is noted as asked, a body length that is not one is
refused unread, nothing else drives CTMS beside a Book, an Upload never answered stops blocking its CSV,
and odd input never drops the connection.

Run:  python region2-emailer/tests/test_cloud_server.py
"""
import base64
import json
import os
import socket
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

import server as S                      # noqa: E402  (reads the keys at import)
from http.server import ThreadingHTTPServer  # noqa: E402

DASH, AGENT = "dash-test-key", "agent-test-key"
BRIDGE = S.CTMS_KEY

_httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()
PORT = _httpd.server_address[1]
BASE = f"http://127.0.0.1:{PORT}"
_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None, key=DASH):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Auth": key, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with _op.open(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def fresh():
    """A cloud that has just restarted, the work PC's side of it."""
    S._ctms.update(seen=0.0, state={}, queue=[], results=[], shot=None, watch_until=0.0,
                   stop=False, captures={}, running=None, control_until=0.0, control_touched=False, payloads={},
                   asked={}, polling=0, armed_for=None, importing={}, imported={}, looked_up=None,
                   todo_run=None, rail_run=None, book_run=None)


class _Quiet:
    """Nothing on the map and no set-time look-up due, so a check-in hands out only what the test queued."""

    def __enter__(self):
        self.keep = (S._tracker, S._panel, dict(S._check_slot))
        S._tracker, S._panel = {"records": []}, {}
        S._check_slot["next_try"] = time.time() + 3600
        return self

    def __exit__(self, *a):
        S._tracker, S._panel = self.keep[0], self.keep[1]
        S._check_slot.clear()
        S._check_slot.update(self.keep[2])
        fresh()
        S._queue.clear()


def take():
    """Play the work PC's bridge once: check in and take what is waiting."""
    code, got = call("/api/ctms/poll", {"state": {"version": "1"}}, key=BRIDGE)
    assert code == 200, got
    return got["cmd"]


# ---- the home agent's queue ------------------------------------------------------------------------
def test_a_command_from_before_the_home_pc_went_away_is_not_handed_out_when_it_comes_back():
    with S._lock:
        S._queue.clear()
        S._dropped.clear()
        S._queue.append({"action": "order_send", "order": "9100001", "queued_at": time.time() - 3 * 3600})
        S._agent_seen = time.time() - 3 * 3600
    try:
        # its first request back is a heartbeat, not /api/next - that must not revive the old command
        assert call("/api/heartbeat", key=AGENT)[0] == 200
        assert call("/api/next", key=AGENT) == (200, {})
        st = call("/api/status")[1]
        assert st["state"] == "error" and "Expired unrun" in st["detail"] and "order_send" in st["detail"], st
        assert st["dropped"][-1]["action"] == "order_send" and st["queued"] == 0
        # online but busy: an old command is kept, and handed out
        with S._lock:
            S._queue.append({"action": "order_send", "order": "9100002", "queued_at": time.time() - 3 * 3600})
            S._agent_seen = time.time()
        assert call("/api/heartbeat", key=AGENT)[0] == 200
        assert call("/api/next", key=AGENT)[1].get("order") == "9100002"
    finally:
        with S._lock:
            S._queue.clear()
            S._dropped.clear()
            S._status.update(state="idle", detail="", at="", output="", email=None)


# ---- a message to DHL NOC in the work PC's Teams -------------------------------------------------
def test_a_teams_message_never_goes_round_the_noc_list():
    fresh()
    S._ctms["control_until"] = time.time() + 600            # even with the switch on
    try:
        for key in (DASH, AGENT):
            code, r = call("/api/ctms/command", {"action": "teams_send", "email": "someone@example.com",
                                                 "name": "Someone", "text": "Hi"}, key=key)
            assert code == 400 and "Send in Teams" in r["error"], (code, r)
        assert not any(c["action"] == "teams_send" for c in S._ctms["queue"])
    finally:
        fresh()


def test_a_teams_message_that_went_is_noted_as_asked_and_a_rehearsal_or_a_failure_is_not():
    with _Quiet():
        fresh()
        S._queue.clear()
        S._panel = {"noc_teams": [{"name": "Sam", "email": "sam.example@example.com"}]}
        body = {"email": "sam.example@example.com", "text": "Hi Sam, would you be able to cover the job below?",
                "orders": ["9100001", "9100002"], "haulier": "Our Fleet"}
        code, r = call("/api/ctms/teams", body)
        assert code == 200
        assert take()["id"] == r["id"]
        assert call("/api/ctms/result", {"id": r["id"], "action": "teams_send", "ok": True, "detail": "Sent."},
                    key=BRIDGE)[0] == 200
        note = S._queue[-1]
        assert note == dict(note, action="ask_note", orders=["9100001", "9100002"], name="Our Fleet",
                            email="sam.example@example.com"), note
        S._queue.clear()
        for extra, ok in (({"dry": True}, True), ({}, False)):
            code, r = call("/api/ctms/teams", dict(body, **extra))
            assert code == 200 and take()["id"] == r["id"]
            call("/api/ctms/result", {"id": r["id"], "action": "teams_send", "ok": ok, "detail": "x"}, key=BRIDGE)
            assert not any(c["action"] == "ask_note" for c in S._queue), (extra, ok, S._queue)


# ---- the request body ---------------------------------------------------------------------------
def _raw_post(length):
    """A POST whose Content-Length is `length`, the body never sent - the answer's status code."""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    try:
        s.sendall((f"POST /api/status HTTP/1.1\r\nHost: x\r\nX-Auth: {AGENT}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {length}\r\n\r\n").encode())
        head = s.recv(4096)                 # read(-1) would sit here until we hung up
    finally:
        s.close()
    return int(head.split()[1])


def test_a_body_length_that_is_not_one_is_refused_without_reading():
    keep = dict(S._status)
    try:
        for bad in ("-1", "-5000", "abc", "1.5", ""):
            assert _raw_post(bad) == 400, bad
        assert S._status == keep                                 # nothing was taken from it
        assert call("/api/status", {"state": "idle", "detail": "fine"}, key=AGENT)[0] == 200
    finally:
        S._status.clear()
        S._status.update(keep)


# ---- one CTMS run at a time -----------------------------------------------------------------------
def test_a_to_do_run_or_a_rail_export_waits_for_a_booking():
    fresh()
    S._queue.clear()
    S._ctms["book_run"] = {"id": 1, "state": "running", "until": time.time() + 600}
    try:
        code, r = call("/api/ctms/todo/run", {"ids": ["a1"]})
        assert code == 409 and "booking" in r["error"]
        code, r = call("/api/ctms/rail", {"week": "next"})
        assert code == 409 and "booking" in r["error"]
        assert not S._queue and S._ctms["todo_run"] is None and S._ctms["rail_run"] is None and not S._ctms_armed()
        # a Book past its time is over, whatever the home PC last said
        S._ctms["book_run"]["until"] = time.time() - 1
        assert call("/api/ctms/todo/run", {"ids": ["a1"]})[0] == 200
    finally:
        fresh()
        S._queue.clear()


# ---- the map's Upload ---------------------------------------------------------------------------
def test_an_upload_never_answered_stops_blocking_its_csv_and_the_taken_list_is_bounded():
    up = "NR_heavy_AH31-10-2026-ONE_31102026230000.csv"
    with _Quiet():
        fresh()
        S._to_file[up] = {"data": base64.b64encode(b"ORD,1\r\n").decode(), "size": 7, "at": "31/10 23:00", "sha": ""}
        try:
            code, r = call("/api/ctms/import", {"name": up})
            assert code == 200 and take()["id"] == r["id"]
            # handed out and never answered (the bridge restarted mid-import): being uploaded, for a while...
            code, b = call("/api/ctms/import", {"name": up})
            assert code == 409 and "being uploaded already" in b["error"]
            with S._lock:
                S._ctms["importing"][r["id"]] = (up, time.time() - S._CTMS_IMPORT_STALE - 1)
            # ... not until the next redeploy
            code, r2 = call("/api/ctms/import", {"name": up})
            assert code == 200 and r["id"] not in S._ctms["importing"] and r2["id"] in S._ctms["importing"]
            # answered as taken: refused for good after that
            call("/api/ctms/result", {"id": r2["id"], "action": "import_csv", "ok": True, "detail": "Uploaded",
                                      "payload": {"imported": True}}, key=BRIDGE)
            code, b = call("/api/ctms/import", {"name": up})
            assert code == 409 and "already" in b["error"]
            with S._lock:
                for i in range(S._CTMS_MAX_IMPORTED + 30):
                    S._ctms["importing"][-1 - i] = (f"x{i}.csv", time.time())
                    S._ctms_upload_answered_locked(-1 - i, imported=True)
                taken = S._ctms["imported"]
                assert len(taken) == S._CTMS_MAX_IMPORTED and up not in taken and "x0.csv" not in taken
                assert f"x{S._CTMS_MAX_IMPORTED + 29}.csv" in taken
        finally:
            S._to_file.pop(up, None)


# ---- keys, and input that is not what it should be ----------------------------------------------
def test_a_wrong_key_is_refused_whatever_it_is_made_of():
    for key in ("", "dash-test-ke", "dash-test-keyy", "dash-test-kéy", "agent-test-kéy"):
        assert call("/api/status", key=key)[0] == 401, key
        assert call("/api/heartbeat", key=key)[0] == 401, key
    assert call("/api/status", key=DASH)[0] == 200 and call("/api/heartbeat", key=AGENT)[0] == 200


def test_odd_input_is_dropped_never_the_connection():
    a = S._ctms_args
    assert a("ctms_book", {"orders": 9100001})["orders"] == []
    assert a("ctms_book", {"orders": {"9100001": 1}})["orders"] == []
    assert a("book_recall", {"orders": 5})["orders"] == []
    it = a("ctms_item", {"item": {"lines": {"9100001-1-1": 1}, "set": {"storage": "²"}}})["item"]
    assert it["lines"] == [] and it["set"]["storage"] == 0
    it = a("ctms_item", {"item": {"lines": ["9100001-1-1"], "set": {"storage": "2"}}})["item"]
    assert it["lines"] == ["9100001-1-1"] and it["set"]["storage"] == 2
    assert "ref" not in a("click", {"ref": float("inf")}) and "ask" not in a("book_recall", {"ask": float("inf")})
    assert "seconds" not in a("wait", {"seconds": float("nan")})
    assert "at" not in a("click", {"at": [10 ** 400, 1]}) and "box" not in a("snap", {"box": [10 ** 400, 0, 1, 1]})
    assert "qty" not in a("ctms_book", {"qty": {"9100001": 10 ** 400}})
    # and through the door: an answer, never a dropped connection
    fresh()
    try:
        code, r = call("/api/ctms/command", {"action": "see", "ref": float("inf")}, key=AGENT)
        assert code == 200 and "ref" not in S._ctms["queue"][-1]
        assert call("/api/ctms/book", {"orders": 5, "date": "06/11/2026", "carrier": "ACME_DH"})[0] == 400
    finally:
        fresh()


# ---- the rejection card (11/11) ----------------------------------------------------------------------------
def test_a_rejection_send_switches_acting_on_for_its_run_only_and_back_when_it_ends():
    fresh()
    S._queue.clear()
    S._ctms["rejection_run"] = None
    try:
        assert call("/api/ctms/rejection", {"ids": ["not-one"]})[0] == 400
        code, r = call("/api/ctms/rejection", {"ids": ["r0123abcd9", "nope", "r0123abcd8"]})
        assert code == 200 and S._ctms_armed()
        job = S._queue[-1]
        assert job["action"] == "rejection_run" and job["ids"] == ["r0123abcd9", "r0123abcd8"] and job["run"] == r["run"]
        assert call("/api/ctms/rejection", {"id": "r0123abcd9"})[0] == 409               # one run at a time
        assert call("/api/ctms/rejection/progress", {"run": r["run"], "on": "x"})[0] == 401   # the home PC's to say
        call("/api/ctms/rejection/progress", {"run": r["run"], "on": "9100002 - DHL NOC",
                                              "results": [{"id": "r0123abcd9", "ok": True, "said": "sent"}]}, key=AGENT)
        code, st = call("/api/ctms/status?visible=0")
        assert st["rejection_run"]["on"] == "9100002 - DHL NOC" and len(st["rejection_run"]["results"]) == 1
        assert "until" not in st["rejection_run"]                                         # the page's view only
        assert call("/api/ctms/rejection/ran", {"run": r["run"], "ok": True})[0] == 401   # not the dashboard's to say
        assert call("/api/ctms/rejection/ran", {"run": r["run"], "ok": False, "said": "1 of 2 sent",
                                                "results": [{"id": "r0123abcd9", "ok": True, "said": "sent"},
                                                            {"id": "r0123abcd8", "ok": False, "said": "not taken"}]},
                    key=AGENT)[0] == 200
        assert not S._ctms_armed() and S._ctms["rejection_run"]["state"] == "done"
        assert [x["ok"] for x in S._ctms["rejection_run"]["results"]] == [True, False]
        S._ctms["book_run"] = {"id": 9, "state": "running", "until": time.time() + 600}
        code, b = call("/api/ctms/rejection", {"id": "r0123abcd9"})
        assert code == 409 and "booking" in b["error"]                                    # never across a Book
    finally:
        fresh()
        S._queue.clear()
        S._ctms["rejection_run"] = None


def test_auto_sends_a_complete_response_only_while_the_work_pc_is_left_alone_and_never_twice():
    fresh()
    S._queue.clear()
    S._ctms["rejection_run"] = None
    S._rejection_tried.clear()
    keep = (S._panel, S._ctms_online, S._agent_online)
    held = {"id": "r1111111111", "status": "held", "gaps": ["the product"]}
    ready = {"id": "r2222222222", "status": "ready", "gaps": []}
    sends = lambda: [i for q in S._queue if q["action"] == "rejection_run" for i in q["ids"]]  # noqa: E731
    try:
        S._ctms_online = S._agent_online = lambda: True
        S._ctms["state"] = {"idle": 5}
        assert call("/api/panel", {"rejections": {"auto": True, "open": [held, ready]}}, key=AGENT)[0] == 200
        assert sends() == []                                                             # he's at the work PC
        S._ctms["state"] = {"idle": 120}
        call("/api/panel", {"rejections": {"auto": False, "open": [held, ready]}}, key=AGENT)
        assert sends() == []                                                             # Auto off
        call("/api/panel", {"rejections": {"auto": True, "open": [held, ready]}}, key=AGENT)
        assert sends() == ["r2222222222"] and S._ctms_armed()                            # the complete one only
        S._ctms["rejection_run"]["until"] = time.time() - 1                              # that run over
        call("/api/panel", {"rejections": {"auto": True, "open": [held, ready]}}, key=AGENT)
        assert sends() == ["r2222222222"]                                                # never started twice
    finally:
        S._panel, S._ctms_online, S._agent_online = keep
        fresh()
        S._queue.clear()
        S._ctms["rejection_run"] = None
        S._rejection_tried.clear()


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    _httpd.shutdown()
    sys.exit(1 if failed else 0)
