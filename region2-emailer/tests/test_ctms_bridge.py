"""Plain-assert tests for the CTMS bridge - no browser, no CTMS, no Outlook.

Covers the places a mistake would cost something real: the keys (the work PC
must never reach the home agent's queue, and only the dashboard can let Claude
act), the switch (nothing that clicks or types queues while it is off), what
leaves the work PC (passwords and session tokens never do), the relay that
holds a check-in open, and remote updates (tried before they replace
anything, and undone if they will not start).

Run:  python region2-emailer/tests/test_ctms_bridge.py
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ENGINE, "cloud"))
sys.path.insert(0, os.path.join(ENGINE, "work_pc"))
sys.path.insert(0, ENGINE)
os.environ["DASH_KEY"] = "dash-test-key"
os.environ["AGENT_KEY"] = "agent-test-key"

import server as S                      # noqa: E402  (reads the keys at import)
import ctms_bridge as B                 # noqa: E402
import ctms_drive as D                  # noqa: E402
import ctms_update as U                 # noqa: E402
import ctms_remote as R                 # noqa: E402
import cdp                              # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

DASH, AGENT = "dash-test-key", "agent-test-key"
BRIDGE = B.bridge_key(DASH)

_httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{_httpd.server_address[1]}"
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
    """A cloud that has just restarted."""
    S._ctms.update(seen=0.0, state={}, queue=[], results=[], shot=None, watch_until=0.0,
                   stop=False, captures={}, running=None, control_until=0.0, payloads={}, asked={},
                   polling=0)


def poll(state=None):
    return call("/api/ctms/poll", {"state": state or {"version": "1"}}, key=BRIDGE)


# ---- keys -------------------------------------------------------------------
def test_bridge_derives_the_same_key_as_the_dashboard():
    assert S.CTMS_KEY == BRIDGE
    assert B.bridge_key("  " + DASH + "\n") == BRIDGE      # pasted with stray whitespace
    assert BRIDGE not in (DASH, AGENT)


def test_bridge_key_opens_the_bridge_channel_and_nothing_else():
    fresh()
    assert poll()[0] == 200
    for path in ("/api/ctms/status", "/api/next", "/api/status", "/api/tracker", "/api/ctms/captures"):
        assert call(path, key=BRIDGE)[0] == 401, path
    assert call("/api/command", {"action": "preview"}, key=BRIDGE)[0] == 401
    assert call("/api/ctms/command", {"action": "look"}, key=BRIDGE)[0] == 401
    # and the other keys cannot pretend to be the bridge
    assert call("/api/ctms/poll", {"state": {}}, key=DASH)[0] == 401
    assert call("/api/ctms/poll", {"state": {}}, key=AGENT)[0] == 401
    assert call("/api/ctms/poll", {"state": {}}, key="")[0] == 401
    # the home PC collects captures, and Claude uses its key to look and ask...
    assert call("/api/ctms/captures", key=AGENT)[0] == 200
    assert call("/api/ctms/command", {"action": "see"}, key=AGENT)[0] == 200
    assert call("/api/ctms/status", key=AGENT)[0] == 200
    # ...but only the dashboard can let it act, or press Stop
    assert call("/api/ctms/control", {"on": True}, key=AGENT)[0] == 401
    assert call("/api/ctms/control", {"on": True}, key=BRIDGE)[0] == 401
    assert call("/api/ctms/stop", {}, key=AGENT)[0] == 401
    assert S._ctms["control_until"] == 0.0


def test_the_work_pc_checking_in_does_not_light_the_home_pc_pill():
    fresh()
    S._agent_seen = 0.0
    poll()
    st = call("/api/status")[1]
    assert st["ctms_online"] is True
    assert st["agent_online"] is False


# ---- the switch ----------------------------------------------------------------
def test_only_known_actions_queue_and_acting_waits_for_the_switch():
    fresh()
    for action in ("submit", "navigate", "book", "", "preview", "eval"):
        assert call("/api/ctms/command", {"action": action})[0] == 400, action
    # looking needs nothing switched on
    for body in ({"action": "look"}, {"action": "capture", "name": "home"}, {"action": "net", "on": True},
                 {"action": "see"}):
        assert call("/api/ctms/command", body)[0] == 200
    # acting does - for the home PC and the dashboard alike
    for key in (AGENT, DASH):
        for action in ("click", "type", "key", "select", "goto", "reload", "dialog"):
            code, body = call("/api/ctms/command", {"action": action, "ref": 3}, key=key)
            assert code == 409 and body["need"] == "control", (action, code)
    assert [c["action"] for c in S._ctms["queue"]] == ["look", "capture", "net", "see"]
    assert call("/api/ctms/control", {"on": True, "minutes": 15})[1]["control"]["armed"] is True
    assert call("/api/ctms/command", {"action": "click", "ref": 3}, key=AGENT)[0] == 200


def test_switching_off_or_stop_cancels_anything_waiting_to_act():
    fresh()
    call("/api/ctms/control", {"on": True})
    call("/api/ctms/command", {"action": "click", "ref": 1}, key=AGENT)
    call("/api/ctms/command", {"action": "see"}, key=AGENT)
    call("/api/ctms/control", {"on": False})
    assert [c["action"] for c in S._ctms["queue"]] == ["see"]          # looking survives
    st = call("/api/ctms/status")[1]
    assert st["control"]["armed"] is False
    assert any("switched off" in r["detail"] for r in st["results"])
    call("/api/ctms/control", {"on": True})
    call("/api/ctms/command", {"action": "type", "ref": 1, "text": "x"}, key=AGENT)
    call("/api/ctms/stop", {})
    assert S._ctms["queue"] == [] and S._ctms["control_until"] == 0.0
    assert poll()[1]["control"] is False


def test_the_switch_runs_out_by_itself():
    fresh()
    call("/api/ctms/control", {"on": True, "minutes": 1})     # clamped up to the 5 minute floor
    assert 290 < S._ctms["control_until"] - time.time() <= 300
    call("/api/ctms/command", {"action": "click", "ref": 1}, key=AGENT)
    S._ctms["control_until"] = time.time() - 1                # ...time passes
    st = call("/api/ctms/status")[1]
    assert st["control"]["armed"] is False and st["queued"] == []
    assert "ran out" in st["results"][0]["detail"]
    assert call("/api/ctms/command", {"action": "click", "ref": 1}, key=AGENT)[0] == 409


def test_a_work_pc_set_to_observe_only_is_not_sent_actions():
    fresh()
    poll({"version": "2", "control": False})
    call("/api/ctms/control", {"on": True})
    code, body = call("/api/ctms/command", {"action": "click", "ref": 1}, key=AGENT)
    assert code == 409 and body["need"] == "allow" and "--allow-control" in body["error"]
    assert call("/api/ctms/command", {"action": "see"}, key=AGENT)[0] == 200


def test_what_a_command_carries_is_checked_and_cut_to_size():
    fresh()
    call("/api/ctms/control", {"on": True})
    call("/api/ctms/command", {"action": "type", "ref": "7", "text": "x" * 5000, "snap": "s12",
                               "evil": "rm -rf", "commit": 1, "url": None}, key=AGENT)
    call("/api/ctms/command", {"action": "click", "ref": -4, "snap": "../x", "at": [5, "y"]}, key=AGENT)
    call("/api/ctms/command", {"action": "update", "branch": "../../etc", "scope": "everything"}, key=AGENT)
    call("/api/ctms/command", {"action": "update", "branch": "claude/ctms-bridge", "scope": "all"}, key=AGENT)
    t, c, u1, u2 = S._ctms["queue"]
    assert t["ref"] == 7 and len(t["text"]) == 2000 and t["snap"] == "s12" and t["commit"] is True
    assert "evil" not in t and "url" not in t and t["by"] == "home PC"
    assert "ref" not in c and "snap" not in c and "at" not in c
    assert "branch" not in u1 and "scope" not in u1
    assert u2["branch"] == "claude/ctms-bridge" and u2["scope"] == "all"


def test_claude_using_the_home_key_does_not_light_the_home_pc_pill():
    fresh()
    S._agent_seen = 0.0
    call("/api/ctms/command", {"action": "see"}, key=AGENT)
    call("/api/ctms/status", key=AGENT)
    assert S._agent_seen == 0.0


# ---- the relay: a check-in held open until there is work ------------------------------
def test_a_held_check_in_hands_over_a_command_the_moment_it_arrives():
    fresh()
    out = {}

    def held():
        t = time.time()
        out["r"] = call("/api/ctms/poll", {"state": {"version": "2"}, "wait": 10}, key=BRIDGE)[1]
        out["t"] = time.time() - t
    th = threading.Thread(target=held)
    th.start()
    time.sleep(0.4)
    assert call("/api/ctms/status")[1]["online"] is True          # held open = online
    cid = call("/api/ctms/command", {"action": "see"}, key=AGENT)[1]["id"]
    th.join(5)
    assert out["r"]["cmd"]["id"] == cid and out["r"]["long"] is True
    assert out["t"] < 3, out["t"]
    # with nothing to do it comes back when its time is up
    t = time.time()
    r = call("/api/ctms/poll", {"state": {}, "wait": 1}, key=BRIDGE)[1]
    assert r["cmd"] is None and 0.8 < time.time() - t < 4


def test_opening_the_page_wakes_a_held_check_in_so_pictures_start_at_once():
    fresh()
    out = {}
    th = threading.Thread(target=lambda: out.update(
        r=call("/api/ctms/poll", {"state": {}, "wait": 10, "watched": False}, key=BRIDGE)[1]))
    th.start()
    time.sleep(0.4)
    t = time.time()
    call("/api/ctms/status?watch=1")
    th.join(5)
    assert out["r"]["watch"] is True and time.time() - t < 3


def test_claude_waits_for_its_answer_and_gets_the_screen_with_it():
    fresh()
    cid = call("/api/ctms/command", {"action": "see"}, key=AGENT)[1]["id"]
    assert poll()[1]["cmd"]["id"] == cid
    shot = {"snap": "s1", "img": "QUJD", "elements": [{"n": 1, "r": "button", "l": "Search"}]}

    def answer():
        time.sleep(0.5)
        call("/api/ctms/result", {"id": cid, "action": "see", "ok": True, "detail": "Looked.",
                                  "payload": shot}, key=BRIDGE)
    threading.Thread(target=answer).start()
    t = time.time()
    w = call(f"/api/ctms/result?id={cid}&wait=10", key=AGENT)[1]
    assert w["done"] is True and time.time() - t < 3
    assert w["payload"] == shot and w["result"]["by"] == "home PC" and w["result"]["pic"] is True
    assert call(f"/api/ctms/result?id={cid}", key=BRIDGE)[0] == 401
    # an answer nobody waited for is still there to collect, but only so many are kept
    for i in range(S._CTMS_MAX_PAYLOADS + 2):
        call("/api/ctms/result", {"id": 1000 + i, "action": "see", "ok": True, "payload": {"img": "QQ"}},
             key=BRIDGE)
    assert len(S._ctms["payloads"]) == S._CTMS_MAX_PAYLOADS and cid not in S._ctms["payloads"]


def test_waiting_on_a_command_that_never_ran_says_so():
    fresh()
    cid = call("/api/ctms/command", {"action": "see"}, key=AGENT)[1]["id"]
    w = call(f"/api/ctms/result?id={cid}&wait=0", key=AGENT)[1]
    assert w["done"] is False and w["queued"] is True
    S._ctms["queue"][0]["queued_at"] -= S._CTMS_TTL + 1
    w = call(f"/api/ctms/result?id={cid}&wait=0", key=AGENT)[1]
    assert w["done"] is True and "Not run" in w["result"]["detail"]


def test_bridge_refuses_anything_outside_its_list_on_its_own_side_too():
    sent = []

    class FakeDesk:
        base = "https://desk.example"

        def post(self, path, body, timeout=20):
            sent.append((path, body))
            return {}
    keep, B.LOG = B.LOG, os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    try:
        B.Bridge(FakeDesk(), 1, "").handle({"id": 6, "action": "submit"})
        assert "not something this bridge does" in sent[-1][1]["detail"]
        observe = B.Bridge(FakeDesk(), 1, "", allow_control=False)
        observe.armed = True                     # even with the dashboard's switch on
        observe.handle({"id": 7, "action": "click", "ref": 1})
        assert "--allow-control" in sent[-1][1]["detail"]
        idle = B.Bridge(FakeDesk(), 1, "", allow_control=True)
        idle.handle({"id": 8, "action": "type", "ref": 1, "text": "x"})   # switch off
        assert "switched off" in sent[-1][1]["detail"]
    finally:
        B.LOG = keep
    assert len(sent) == 3
    assert all(p == "/api/ctms/result" and b["ok"] is False and "Refused" in b["detail"] for p, b in sent)


def test_capture_names_are_cleaned_before_they_queue():
    fresh()
    call("/api/ctms/command", {"action": "capture", "name": "../../evil<script>"})
    call("/api/ctms/command", {"action": "capture", "name": ""})
    names = [c["name"] for c in S._ctms["queue"]]
    assert names[0] == "evil-script" and "/" not in names[0], names
    assert names[1] == "screen"


def test_one_picture_request_at_a_time():
    fresh()
    a = call("/api/ctms/command", {"action": "look"})[1]["id"]
    b = call("/api/ctms/command", {"action": "look"})[1]["id"]
    assert a == b and len(S._ctms["queue"]) == 1


# ---- timing -------------------------------------------------------------------
def test_an_unclaimed_command_expires_and_says_it_did_not_run():
    fresh()
    call("/api/ctms/command", {"action": "capture", "name": "order-search"})
    S._ctms["queue"][0]["queued_at"] -= S._CTMS_TTL + 1
    st = call("/api/ctms/status")[1]
    assert st["queued"] == []
    assert st["results"][0]["ok"] is False and "Not run" in st["results"][0]["detail"]
    assert poll()[1]["cmd"] is None        # a late bridge must not run it


def test_stop_cancels_the_queue_and_reaches_the_bridge_exactly_once():
    fresh()
    call("/api/ctms/command", {"action": "capture", "name": "home"})
    call("/api/ctms/stop", {})
    st = call("/api/ctms/status")[1]
    assert st["queued"] == [] and "Cancelled" in st["results"][0]["detail"]
    first, second = poll()[1], poll()[1]
    assert first["stop"] is True and first["cmd"] is None
    assert second["stop"] is False


def test_the_running_command_shows_until_it_is_answered():
    fresh()
    cid = call("/api/ctms/command", {"action": "capture", "name": "home"})[1]["id"]
    assert poll()[1]["cmd"]["id"] == cid
    run = call("/api/ctms/status")[1]["running"]
    assert run["id"] == cid and run["name"] == "home"
    call("/api/ctms/result", {"id": cid, "action": "capture", "name": "home", "ok": True, "detail": "x"},
         key=BRIDGE)
    assert call("/api/ctms/status")[1]["running"] is None
    # a bridge that died mid-command clears it on its next check-in instead
    call("/api/ctms/command", {"action": "look"})
    poll()
    assert call("/api/ctms/status")[1]["running"] is not None
    poll()
    assert call("/api/ctms/status")[1]["running"] is None


def test_pictures_only_flow_while_someone_is_watching():
    fresh()
    assert poll()[1]["watch"] is False
    call("/api/ctms/status?watch=1")
    assert poll()[1]["watch"] is True
    S._ctms["watch_until"] = time.time() - 1
    assert poll()[1]["watch"] is False


# ---- after a restart --------------------------------------------------------------
def test_a_restarted_cloud_asks_for_everything_again():
    fresh()
    assert poll({"version": "1"})[1]["resync"] is True
    assert poll({"screens": [["home", "the landing page"]]})[1]["resync"] is False
    # "same picture as before" with no picture held: ask for the whole one
    assert call("/api/ctms/shot", {"same": True}, key=BRIDGE)[1].get("need") is True
    call("/api/ctms/shot", {"data": "AAAA", "w": 10, "h": 5, "url": "u", "title": "t"}, key=BRIDGE)
    first = S._ctms["shot"]["id"]
    assert call("/api/ctms/shot", {"same": True}, key=BRIDGE)[1].get("need") is None
    assert S._ctms["shot"]["id"] == first                  # same picture, just fresher


def test_numbering_does_not_restart_at_one():
    # a page left open across a redeploy still holds the old numbers
    assert S._ctms["next_id"] > 1_000_000_000 and S._ctms["next_shot"] > 1_000_000_000


# ---- captures --------------------------------------------------------------------
def test_capture_uploads_are_named_and_capped():
    fresh()
    for bad in ("../x.zip", "x.exe", "", "a b.zip"):
        assert call("/api/ctms/capture", {"name": bad, "data": "QQ=="}, key=BRIDGE)[0] == 400, bad
    for i in range(S._CTMS_MAX_CAPTURES + 3):
        call("/api/ctms/capture", {"name": f"20261028-0000{i:02d}_s.zip", "data": "QQ==", "size": 1}, key=BRIDGE)
    names = [c["name"] for c in call("/api/ctms/captures")[1]["captures"]]
    assert len(names) == S._CTMS_MAX_CAPTURES
    assert "20261028-000000_s.zip" not in names and names[0].endswith(f"{S._CTMS_MAX_CAPTURES + 2:02d}_s.zip")


def test_the_home_pc_collects_captures_and_a_hostile_zip_stays_in_its_folder():
    fresh()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("meta.json", "{}")
        z.writestr("../../escaped.txt", "should land inside the capture folder")
    name = "20261028-101010_home.zip"
    call("/api/ctms/capture", {"name": name, "data": base64.b64encode(buf.getvalue()).decode(), "size": 1},
         key=BRIDGE)
    sys.argv = ["agent.py"]
    import agent
    with tempfile.TemporaryDirectory() as tmp:
        agent.BASE, agent.KEY = BASE, AGENT
        agent.CTMS_CAPTURE_DIR = os.path.join(tmp, "ctms_capture")
        agent.pull_ctms_captures()
        agent.pull_ctms_captures()                         # idempotent
        got = sorted(os.listdir(agent.CTMS_CAPTURE_DIR))
        assert got == [name[:-4], name], got
        assert os.path.exists(os.path.join(agent.CTMS_CAPTURE_DIR, name[:-4], "meta.json"))
        assert not os.path.exists(os.path.join(tmp, "escaped.txt"))
        assert not os.path.exists(os.path.join(os.path.dirname(tmp), "escaped.txt"))
        agent.KEY = "wrong"
        agent.pull_ctms_captures()                         # never raises


# ---- what leaves the work PC ---------------------------------------------------------
def test_addresses_lose_their_secrets_and_keep_the_rest():
    r = B.redact_url
    assert r("https://ctms/OrderSearch.do;jsessionid=ABC123?x=1") == "https://ctms/OrderSearch.do;jsessionid=[redacted]?x=1"
    out = r("https://ctms/api?orderId=6055515&token=SEKRIT&productCode=BAG_BALLAST&sid=9")
    assert "SEKRIT" not in out and "sid=9" not in out
    assert "orderId=6055515" in out and "productCode=BAG_BALLAST" in out
    assert "hunter2" not in r("https://user:hunter2@ctms/x")
    assert "tok" not in r("https://ctms/cb#access_token=tok&x=1")


def test_request_bodies_lose_passwords_and_sign_ins_are_never_kept():
    p = B.redact_post
    assert p("https://ctms/j_security_check", "j_username=d&j_password=x") == "[not recorded - sign-in request]"
    assert p("https://ctms/Login.do", '{"user":"d"}') == "[not recorded - sign-in request]"
    js = json.loads(p("https://ctms/api/orders", '{"ref":"6055515","auth":{"password":"pw"},"items":[{"token":"t"}]}'))
    assert js["ref"] == "6055515" and js["auth"] == "[redacted]" and js["items"][0]["token"] == "[redacted]"
    form = p("https://ctms/api/booking/save", "orderId=1&csrf_token=FT&note=ok")
    assert "FT" not in form and "orderId=1" in form and "note=ok" in form
    multi = "--b\r\nContent-Disposition: form-data; name=\"userPassword\"\r\n\r\npw\r\n--b--"
    assert p("https://ctms/upload", multi) == "[not recorded - it carries a password field]"
    assert p("https://ctms/api/x", "plain text") == "plain text"


def test_page_html_loses_passwords_and_tokens_and_keeps_the_form():
    html = ('<meta name="csrf-token" content="META1"><form action="/S.do;jsessionid=SESS1">'
            '<input type="password" name="j_password" value="PW1">'
            '<input type="hidden" name="__RequestVerificationToken" value="RVT1">'
            '<input type="hidden" name="__VIEWSTATE" value="VS1">'
            '<input id="ref" name="custRef" value="6055515">'
            '<a href="/Booking.do?orderId=6055515&amp;jsessionid=SESS2">Book</a></form>')
    out = B.redact_html(html)
    for secret in ("META1", "SESS1", "PW1", "RVT1", "VS1", "SESS2"):
        assert secret not in out, secret
    assert 'value="6055515"' in out and "orderId=6055515" in out and 'name="custRef"' in out


# ---- the websocket client -------------------------------------------------------------
class _Sock:
    def __init__(self):
        self.out = b""

    def sendall(self, data):
        self.out += data


def _bare_ws():
    ws = object.__new__(cdp.WS)
    ws._buf, ws._parts, ws.s = bytearray(), b"", _Sock()
    ws.events, ws.on_event, ws.timeout = [], None, 1
    return ws


def test_a_half_arrived_frame_is_left_whole_in_the_buffer():
    ws = _bare_ws()
    payload = json.dumps({"id": 1, "result": {"ok": True}}).encode()
    frame = bytes([0x81, len(payload)]) + payload
    ws._buf += frame[:5]
    assert ws._message() is None and len(ws._buf) == 5       # nothing consumed
    ws._buf += frame[5:]
    assert ws._message() == {"id": 1, "result": {"ok": True}}
    assert len(ws._buf) == 0


def test_fragments_are_joined_and_pings_answered():
    ws = _bare_ws()
    body = json.dumps({"method": "Network.requestWillBeSent", "params": {"n": 1}}).encode()
    a, b = body[:10], body[10:]
    ws._buf += bytes([0x89, 2]) + b"hi"                     # ping first
    ws._buf += bytes([0x01, len(a)]) + a                    # text, not final
    ws._buf += bytes([0x80, len(b)]) + b                    # continuation, final
    assert ws._message()["params"] == {"n": 1}
    assert ws.s.out[:1] == bytes([0x8A])                    # pong went back
    big = b"x" * 70000                                      # 64-bit length form
    ws._buf += bytes([0x81, 127]) + len(big).to_bytes(8, "big")
    assert ws._message() is None
    ws._buf += b'"' + big[2:] + b'"'
    assert ws._message() == "x" * 69998


# ---- what Claude gets back, and what the bridge will not do ------------------------------
class _NoDesk:
    base = "https://desk.example"

    def post(self, path, body, timeout=20):
        return {}


def test_what_claude_gets_back_loses_session_ids_too():
    b = B.Bridge(_NoDesk(), 1, "")
    p = b._finish({"url": "https://ctms/x.do;jsessionid=AB12?orderId=5&token=T1",
                   "elements": [{"n": 1, "href": "/Booking.do?orderId=1&jsessionid=S2"}],
                   "text": "go to /Order.do?sid=9&ref=6055515"})
    assert "AB12" not in p["url"] and "T1" not in p["url"] and "orderId=5" in p["url"]
    assert "S2" not in p["elements"][0]["href"] and "orderId=1" in p["elements"][0]["href"]
    assert "sid=9" not in p["text"] and "ref=6055515" in p["text"]


def test_keys_that_paste_or_work_the_browser_itself_are_refused():
    d = D.Driver(None)                       # refused before anything reaches a browser
    for k in ("ctrl+v", "Ctrl+V", "shift+insert", "ctrl+w", "alt+f4", "f12", "ctrl+shift+i", "ctrl+p"):
        try:
            d.key(k)
            raise AssertionError(k + " was not refused")
        except D.Refused as e:
            assert "not allowed" in str(e), k


def test_picture_size_comes_from_the_jpeg_itself():
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + (480).to_bytes(2, "big") + (640).to_bytes(2, "big")
    assert D.jpeg_size(b"\xff\xd8" + app0 + sof + b"\x03" + b"\x00" * 9) == (640, 480)
    assert D.jpeg_size(b"not a jpeg") == (0, 0)


# ---- remote updates ------------------------------------------------------------------------
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _repo_zip(files, top="DHL-main/", comment=COMMIT):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for want in ("region2-emailer/build_drafts.py", "region2-emailer/send_order.py"):
            z.writestr(top + want, "# toolkit\n")
        for name, body in files.items():
            z.writestr(top + name, body)
        z.comment = comment.encode()
    return buf.getvalue()


@contextlib.contextmanager
def _fake_install():
    """A repo root of its own, so nothing here touches the real work_pc folder."""
    keep = {k: getattr(U, k) for k in ("ROOT", "BACKUPS", "PENDING", "STAMP", "ROLLED")}
    with tempfile.TemporaryDirectory() as tmp:
        wp = os.path.join(tmp, "region2-emailer", "work_pc")
        os.makedirs(wp)
        for n, body in (("a.py", "x = 1\n"), ("same.py", "y = 1\n")):
            with open(os.path.join(wp, n), "w", newline="\r\n") as f:     # CRLF, as git leaves it
                f.write(body)
        U.ROOT, U.BACKUPS = tmp, os.path.join(wp, "_update_backups")
        U.PENDING, U.STAMP = os.path.join(wp, "_update_pending.json"), os.path.join(wp, "_code_version.json")
        U.ROLLED = os.path.join(wp, "_update_rolled_back.json")
        try:
            yield tmp, wp
        finally:
            for k, v in keep.items():
                setattr(U, k, v)


def test_an_update_lays_down_only_what_changed_in_the_bridge_folder():
    with _fake_install() as (tmp, wp):
        z = os.path.join(tmp, "repo.zip")
        with open(z, "wb") as f:
            f.write(_repo_zip({"region2-emailer/work_pc/a.py": "x = 2\n",
                               "region2-emailer/work_pc/same.py": "y = 1\n",      # LF vs CRLF: same
                               "region2-emailer/work_pc/new.py": "z = 1\n",
                               "region2-emailer/agent.py": "# engine\n",
                               "region2-emailer/work_pc/../../escape.py": "bad\n"}))
        commit, changes = U.plan(z, "bridge")
        assert commit == COMMIT
        assert sorted(rel for rel, _ in changes) == ["region2-emailer/work_pc/a.py", "region2-emailer/work_pc/new.py"]
        assert "region2-emailer/agent.py" in [rel for rel, _ in U.plan(z, "all")[1]]
        with open(z, "wb") as f:
            f.write(_repo_zip({}, top="something-else/").replace(b"region2-emailer/send_order.py", b"region2-emailer/xxxx_order.py"))
        try:
            U.plan(z, "bridge")
            raise AssertionError("a ZIP that is not the toolkit was accepted")
        except U.UpdateError as e:
            assert "not the toolkit" in str(e)


def test_new_code_that_will_not_compile_or_start_is_never_laid_down():
    for rel, body, why in (("region2-emailer/work_pc/ctms_drive.py", "def broken(:\n", "does not compile"),
                           ("region2-emailer/work_pc/ctms_drive.py", "import no_such_module_xyz\n", "does not start")):
        try:
            U.smoke([(rel, body.encode())])
            raise AssertionError(why + " was not caught")
        except U.UpdateError as e:
            assert why in str(e), str(e)
    U.smoke([("region2-emailer/work_pc/harmless.py", b"VALUE = 1\n")])     # fine code passes


def test_an_update_that_does_not_check_in_is_put_back():
    with _fake_install() as (tmp, wp):
        changes = [("region2-emailer/work_pc/a.py", b"x = 2\n"), ("region2-emailer/work_pc/new.py", b"z = 1\n")]
        U.apply(changes, COMMIT, "main")
        assert open(os.path.join(wp, "a.py")).read() == "x = 2\n" and os.path.exists(os.path.join(wp, "new.py"))
        assert U.pending() and U.current()["commit"] == COMMIT
        try:
            U.apply(changes, COMMIT, "main")
            raise AssertionError("a second update went on top of an unproven one")
        except U.UpdateError:
            pass
        msg = U.rollback("it crashed")
        assert "Put back 1 file(s) and removed 1" in msg
        assert open(os.path.join(wp, "a.py")).read().replace("\r\n", "\n") == "x = 1\n"
        assert not os.path.exists(os.path.join(wp, "new.py"))
        assert U.pending() is None and U.current() == {} and U.rolled_back()["reason"] == "it crashed"
        # and one that does check in stays
        U.apply(changes, COMMIT, "main")
        assert U.confirm() is True and U.pending() is None and U.rolled_back() is None
        assert open(os.path.join(wp, "a.py")).read() == "x = 2\n"


# ---- the home PC's side: ctms_remote.py against a stand-in bridge ---------------------------
SCREEN = {"snap": "s5", "img": base64.b64encode(b"\xff\xd8\xff\xd9").decode(), "img_w": 10, "img_h": 5,
          "url": "https://ctms/OrderSearch.do", "title": "Order Search",
          "elements": [{"n": 1, "r": "textbox", "l": "Order ref", "v": "6055515"},
                       {"n": 2, "r": "button", "l": "Book", "c": True},
                       {"n": 3, "r": "link", "l": "Next page", "off": "below"}],
          "text": "Order Search\n\n\nOrder ref   6055515", "tabs": [{"n": 1, "title": "CTMS", "current": True}]}


def _stand_in_bridge(stop, seen):
    armed = False
    while not stop.is_set():
        r = call("/api/ctms/poll", {"state": {"version": "2", "control": True}, "wait": 0.5,
                                    "armed": armed}, key=BRIDGE)[1]
        armed = bool(r.get("control"))
        cmd = r.get("cmd")
        if not cmd:
            continue
        seen.append(cmd)
        refuse = cmd["action"] == "click" and cmd.get("ref") == 2 and not cmd.get("commit")
        call("/api/ctms/result", {"id": cmd["id"], "action": cmd["action"], "ok": not refuse,
                                  "detail": "[2] looks like it would book. Not clicked." if refuse else "Done it.",
                                  "payload": {"needs_commit": True} if refuse else SCREEN}, key=BRIDGE)


def _cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = R.main(list(argv))
    return rc, out.getvalue()


def test_claude_sees_numbers_acts_on_them_and_every_step_is_kept():
    fresh()
    stop, seen = threading.Event(), []
    th = threading.Thread(target=_stand_in_bridge, args=(stop, seen), daemon=True)
    th.start()
    keep = (R.OUT, R.STATE, os.environ.get("CTMS_DESK_URL"), os.environ.get("CTMS_DESK_KEY"))
    with tempfile.TemporaryDirectory() as tmp:
        R.OUT, R.STATE = tmp, os.path.join(tmp, "state.json")
        os.environ["CTMS_DESK_URL"], os.environ["CTMS_DESK_KEY"] = BASE, AGENT
        try:
            rc, out = _cli("see")
            assert rc == 0, out
            assert '[1] textbox "Order ref" = "6055515"' in out
            assert '[2] button "Book"  (SAVES/SUBMITS' in out and "Not in view: 1 below" in out
            assert "[3]" not in out                       # out of view: counted, not listed
            assert os.path.exists(os.path.join(tmp, "latest.jpg"))
            assert json.load(open(R.STATE))["snap"] == "s5"
            rc, out = _cli("click", "1")
            assert rc == 5 and "Only Delali can switch it on" in out, out     # the switch is off
            call("/api/ctms/control", {"on": True})
            rc, out = _cli("click", "1")
            assert rc == 0 and seen[-1]["snap"] == "s5" and seen[-1]["ref"] == 1, (rc, out, seen[-1:])
            rc, out = _cli("click", "2")
            assert rc == 3 and "ask Delali first" in out
            rc, out = _cli("find", "order")
            assert rc == 0 and "[1] textbox" in out and "Order ref" in out
            day = os.listdir(os.path.join(tmp, "trace"))[0]
            steps = os.listdir(os.path.join(tmp, "trace", day))
            assert any(n.endswith("-click.json") for n in steps) and any(n.endswith("-see.jpg") for n in steps)
        finally:
            stop.set()
            th.join(3)
            R.OUT, R.STATE = keep[0], keep[1]
            for k, v in (("CTMS_DESK_URL", keep[2]), ("CTMS_DESK_KEY", keep[3])):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v



# ---- "Set up this PC": the one file the work PC needs ----------------------------------
def _setup_text(allow="1", autostart="1", desk=None, key=DASH):
    q = f"allow={allow}&autostart={autostart}&desk=" + (desk or BASE)
    req = urllib.request.Request(BASE + "/api/ctms/setup?" + q, headers={"X-Auth": key})
    try:
        with _op.open(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_the_setup_file_is_made_for_this_dashboard_and_only_for_its_own_key():
    code, body, headers = _setup_text(allow="1", autostart="0")
    assert code == 200 and "CTMS bridge setup.cmd" in headers.get("Content-Disposition", "")
    text = body.decode("utf-8")
    first, rest = text.split("\r\n", 1)
    assert first == '@python -x "%~f0" %* & pause & goto :eof'     # what Windows runs; Python skips it
    compile(rest, "setup", "exec")                                     # the rest is the Python
    cfg = eval(next(ln for ln in rest.splitlines() if ln.startswith("CONFIG = "))[9:])
    assert cfg["desk"] == BASE and cfg["key"] == BRIDGE and cfg["key"] != DASH
    assert cfg["allow_control"] is True and cfg["autostart"] is False
    for key in (AGENT, BRIDGE, ""):
        assert _setup_text(key=key)[0] == 401
    assert call("/healthz", key="")[1]["ctms_setup"] is True          # the template is in this build
    # made only for the address the browser actually reached
    assert _setup_text(desk="https://evil.example")[0] == 400
    assert _setup_text(desk="javascript:alert(1)")[0] == 400


def test_hello_answers_the_bridge_and_hands_nothing_out():
    fresh()
    cid = call("/api/ctms/command", {"action": "see"}, key=AGENT)[1]["id"]
    assert call("/api/ctms/hello", {}, key=BRIDGE) == (200, {"ok": True})
    assert [c["id"] for c in S._ctms["queue"]] == [cid] and S._ctms["running"] is None
    for key in (DASH, AGENT, ""):
        assert call("/api/ctms/hello", {}, key=key)[0] == 401


def test_start_at_login_is_one_file_in_startup_that_comes_and_goes():
    keep = os.environ.get("APPDATA")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["APPDATA"] = tmp
        try:
            path = B.set_autostart(True)
            assert B.autostart_on() and path.startswith(tmp) and path.endswith("CTMS bridge.cmd")
            body = open(path).read()
            assert "ctms_bridge.py" in body and "/min" in body
            B.set_autostart(False)
            assert not B.autostart_on() and not os.path.exists(path)
        finally:
            if keep is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = keep


def test_the_bridge_remembers_where_ctms_lives_for_next_time():
    keep = B.CONFIG
    with tempfile.TemporaryDirectory() as tmp:
        B.CONFIG = os.path.join(tmp, "ctms_bridge.json")
        try:
            B.save_config({"url": "u", "key": "k"})
            B.remember_ctms_url("https://ctms.example/CTMS/OrderSearch.do;jsessionid=ABC?x=1")
            assert B.load_config()["ctms_url"] == "https://ctms.example/CTMS/"
            B.remember_ctms_url("https://ctms.example/index.html")
            assert B.load_config()["ctms_url"] == "https://ctms.example/"
            B.remember_ctms_url("edge://settings")                     # not a web page: ignored
            assert B.load_config()["ctms_url"] == "https://ctms.example/"
        finally:
            B.CONFIG = keep


def _toolkit_zip(path, commit=COMMIT):
    """The repo as GitHub would hand it over - the real work_pc code inside."""
    wp = os.path.join(ENGINE, "work_pc")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in os.listdir(wp):
            if n.endswith(".py"):
                z.write(os.path.join(wp, n), "DHL-main/region2-emailer/work_pc/" + n)
        z.writestr("DHL-main/region2-emailer/build_drafts.py", "# toolkit\n")
        z.writestr("DHL-main/region2-emailer/send_order.py", "# toolkit\n")
        z.comment = commit.encode()


def test_the_setup_sets_up_a_fresh_pc_and_a_second_run_changes_the_choices():
    import pathlib
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        zpath = os.path.join(tmp, "DHL-main.zip")
        _toolkit_zip(zpath)
        home, appdata = os.path.join(tmp, "CTMS-bridge"), os.path.join(tmp, "appdata")
        env = dict(os.environ, CTMS_SETUP_TEST="1", CTMS_BRIDGE_HOME=home, APPDATA=appdata,
                   CTMS_SETUP_ZIP=pathlib.Path(zpath).as_uri(), PYTHONDONTWRITEBYTECODE="1")

        def run(allow, autostart):
            cmd = os.path.join(tmp, "CTMS bridge setup.cmd")
            with open(cmd, "wb") as f:
                f.write(_setup_text(allow=allow, autostart=autostart)[1])
            r = subprocess.run([sys.executable, "-x", cmd], env=env, capture_output=True, text=True, timeout=120)
            assert r.returncode == 0, r.stdout + r.stderr
            return r.stdout
        out = run("1", "1")
        wp = os.path.join(home, "region2-emailer", "work_pc")
        cfg = json.load(open(os.path.join(wp, "ctms_bridge.json")))
        assert cfg["url"] == BASE and cfg["key"] == BRIDGE and cfg["allow_control"] is True
        assert json.load(open(os.path.join(wp, "_code_version.json")))["commit"] == COMMIT
        startup = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "CTMS bridge.cmd")
        assert os.path.isfile(startup) and wp in open(startup).read()
        assert "it can." in out and "1/4" in out and "4/4" in out, out      # reached the dashboard
        # again, with the boxes unticked: settings change, his own match word stays
        cfg["match"] = "ctms"
        json.dump(cfg, open(os.path.join(wp, "ctms_bridge.json"), "w"))
        run("0", "0")
        cfg = json.load(open(os.path.join(wp, "ctms_bridge.json")))
        assert cfg["allow_control"] is False and cfg["match"] == "ctms" and not os.path.exists(startup)



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
