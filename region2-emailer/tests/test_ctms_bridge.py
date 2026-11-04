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
import array
import contextlib
import ctypes
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib
import struct
from datetime import datetime, timedelta

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
import ctms_fast as F                   # noqa: E402
import ctms_update as U                 # noqa: E402
import ctms_window as W                 # noqa: E402
import ctms_act as A                    # noqa: E402
import ctms_jab as J                    # noqa: E402
import ctms_tabs as TB                  # noqa: E402
import ctms_notes as N                  # noqa: E402
import ctms_remote as R                 # noqa: E402
import upload_weights as UW             # noqa: E402
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
                   stop=False, captures={}, running=None, control_until=0.0, control_touched=False, payloads={},
                   asked={}, polling=0, armed_for=None, importing={}, imported={}, looked_up=None)


def poll(state=None):
    return call("/api/ctms/poll", {"state": state or {"version": "1"}}, key=BRIDGE)


# ---- keys -------------------------------------------------------------------
def test_bridge_derives_the_same_key_as_the_dashboard():
    assert S.CTMS_KEY == BRIDGE
    assert B.bridge_key("  " + DASH + "\n") == BRIDGE      # pasted with stray whitespace
    assert BRIDGE not in (DASH, AGENT)


def test_the_bridge_says_how_long_the_work_pc_has_sat_unused():
    # so a job can wait for CTMS to be free instead of taking it from under him (02/11)
    fresh()
    assert poll({"version": "1", "idle": 412})[0] == 200
    st = call("/api/ctms/status", key=AGENT)[1]["state"]
    assert st["idle"] == 412 and st["idle_at"] > 0
    assert isinstance(B._idle_now(), int)                       # whole seconds, or -1 where it can't be asked


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


def test_the_switch_outlasts_the_dashboard_restarting_but_never_a_switch_off_or_its_time():
    fresh()
    call("/api/ctms/control", {"on": True, "minutes": 60})
    until = S._ctms["control_until"]
    r = poll()[1]
    assert r["control"] is True and r["ticket"]
    ticket = r["ticket"]

    def carried(t):
        return call("/api/ctms/poll", {"state": {"version": "1"}, "ticket": t}, key=BRIDGE)[1]["control"]

    fresh()                                                         # a deploy: the dashboard forgot
    assert poll()[1]["control"] is False                            # nothing handed back: off, as ever
    assert carried(ticket) is True and abs(S._ctms["control_until"] - until) < 1.5    # the same end, no later
    assert any("restarting" in x["detail"] for x in call("/api/ctms/status")[1]["results"])
    fresh()
    call("/api/ctms/control", {"on": False})                        # switched off since the restart
    assert carried(ticket) is False
    fresh()
    call("/api/ctms/stop", {})                                      # or Stop pressed
    assert carried(ticket) is False
    forged = (ticket[:-1] + ("0" if ticket[-1] != "0" else "1"), str(int(until) + 3600) + ticket[ticket.index("."):],
              B.bridge_key(DASH), "x.y", S._ctms_ticket(time.time() - 5))
    for bad in forged:                                              # not one the dashboard signed, or run out
        fresh()
        assert carried(bad) is False, bad
    # the bridge keeps it only while the switch is on
    b = B.Bridge(_Rec(), 1, "", allow_control=True)
    b.confirmed = True
    b.checked_in({}, {"control": True, "ticket": ticket})
    assert b.armed and b.ticket == ticket
    b.checked_in({}, {"control": False, "ticket": ticket})
    assert not b.armed and b.ticket == ""


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


def test_a_recipe_only_looking_which_way_to_go_is_marked_so_the_page_shows_no_failure():
    fresh()
    looking = call("/api/ctms/command", {"action": "see", "look": True}, key=AGENT)[1]["id"]
    real = call("/api/ctms/command", {"action": "see"}, key=AGENT)[1]["id"]
    for cid in (looking, real):
        call("/api/ctms/result", {"id": cid, "action": "see", "ok": False, "detail": "not on the screen"}, key=BRIDGE)
    res = {r["id"]: r for r in call("/api/ctms/status")[1]["results"]}
    assert res[looking]["look"] is True and res[real]["look"] is False, res
    # whoever asked still gets the answer they waited for
    assert call(f"/api/ctms/result?id={looking}&wait=0", key=AGENT)[1]["result"]["ok"] is False


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


def test_a_point_click_is_in_the_audit_log_with_its_time_and_its_point():
    tmp = tempfile.mkdtemp(prefix="log-test-")
    keep, B.LOG = B.LOG, os.path.join(tmp, "log.jsonl")
    try:
        B.Bridge(_Rec(), 1, "", allow_control=True).handle({"id": 9, "action": "click", "at": [0.25, 0.5]})
        with open(B.LOG, encoding="utf-8") as f:
            got = [json.loads(line) for line in f]
        cmd = [g for g in got if g["kind"] == "command"]
        assert len(cmd) == 1 and cmd[0]["point"] == [0.25, 0.5] and cmd[0]["action"] == "click", got
        assert datetime.fromisoformat(cmd[0]["at"])                 # the time is still the record's own
    finally:
        B.LOG = keep
        shutil.rmtree(tmp, ignore_errors=True)


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
            assert rc == 5 and "Only Delali can turn it on" in out, out       # the switch is off
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



# ---- CTMS's own window (Oracle Forms in IE mode, in his normal Edge) --------------------
def _bgra(rows):
    """BGRA bytes from rows of 0xAARRGGBB pixels."""
    return array.array("I", [p for row in rows for p in row]).tobytes()


def test_a_window_picture_is_a_real_png_of_exactly_those_pixels():
    red, green, blue, white = 0xFFFF0000, 0xFF00FF00, 0xFF0000FF, 0xFFFFFFFF
    data = W.png(_bgra([[red, green, blue], [white, red, green]]), 3, 2)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, depth, colour = struct.unpack(">IIBB", data[16:26])
    assert (w, h, depth, colour) == (3, 2, 8, 2)
    idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    assert raw == (b"\x00" + bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
                   + b"\x00" + bytes([255, 255, 255, 255, 0, 0, 0, 255, 0]))


def test_only_ctms_s_part_is_kept_and_an_unscaled_window_is_measured_by_what_it_drew():
    px = [[0xFF000000 + (y * 10 + x) for x in range(10)] for y in range(6)]
    part, w, h = W.crop(_bgra(px), 10, 6, (2, 1, 5, 4))
    assert (w, h) == (3, 3) and array.array("I", part)[0] == 0xFF000000 + 12
    # a window unaware of 125% scaling draws 8 of 10 columns and leaves the rest transparent
    drawn = [[(0xFF336699 if x < 8 and y < 4 else 0) for x in range(10)] for y in range(5)]
    assert W.drawn_size(_bgra(drawn), 10, 5) == (8, 4)


def test_a_picture_windows_would_not_draw_is_not_passed_off_as_ctms():
    assert W.blank(_bgra([[0xFFFFFFFF] * 50] * 50))                     # all one colour
    half = [[(0 if x < 20 else 0xFF000000 + x * 999) for x in range(50)] for _ in range(50)]
    assert W.blank(_bgra(half))                                           # 40% never drawn
    varied = [[0xFF000000 + (x * 7919 + y * 104729) % 0xFFFFFF for x in range(50)] for y in range(50)]
    assert not W.blank(_bgra(varied))


def test_the_rounded_corners_of_a_window_read_off_the_screen_are_greyed():
    out = array.array("I", W.round_corners(_bgra([[0xFF112233] * 20] * 20), 20, 20, 6))
    assert out[0] == 0xFF808080 and out[19] == 0xFF808080 and out[19 * 20] == 0xFF808080
    assert out[10 * 20 + 10] == 0xFF112233                                # the middle untouched


def test_only_a_window_ctms_can_be_in_counts_never_one_that_mentions_it():
    keep = W.TEST_CLASSES
    W.TEST_CLASSES = ()
    try:
        assert W.score("Chrome_WidgetWin_1", "Calidus TMS", 1, 1, 3) > W.score("SunAwtFrame", "x", 0, 0, 0) > 0
        assert W.score("Chrome_WidgetWin_1", "CTMS wiki - Work - Edge", 0, 0, 0) == 0     # plain web page
        assert W.score("rctrl_renwnd32", "RE: CTMS booking", 0, 0, 0) == 0               # an email about it
        assert W.score("ConsoleWindowClass", "CTMS bridge", 0, 0, 0) == 0                # the bridge itself
        assert W.score("Chrome_WidgetWin_1", "Smart Connect", 1, 0, 0) > 0               # CTMS in a back tab
        assert W.score("SunAwtFrame", "Java Console", 0, 0, 0) == 0                      # Java's own console
        assert W.score("SunAwtFrame", "Oracle Fusion Middleware Forms Services", 0, 0, 0) > 0   # CTMS's own frame
    finally:
        W.TEST_CLASSES = keep


def test_only_ctmss_tab_or_the_trackers_is_ever_brought_up_and_a_hung_edge_is_not_waited_on():
    assert TB._matches("Oracle Fusion Middleware Forms Services", "ctms")
    assert TB._matches("DigiHaul Job Tracker.xlsx - Memory usage - 19.6 MB", "page")          # Edge adds the memory
    assert not TB._matches("DigiHaul Job Tracker.xlsx", "ctms") and not TB._matches("Oracle Fusion Middleware", "page")
    for other in ("CTMS user guide - SharePoint", "Haulage Desk - CTMS", "Inbox - Outlook", ""):
        assert not TB._matches(other, "ctms") and not TB._matches(other, "page"), other
    # Edge's title is the selected tab's - how a switch is confirmed
    assert TB._matches("Oracle Fusion Middleware Forms Services and 2 more pages - Work - Microsoft​ Edge", "ctms")
    assert TB.select("elsewhere")[0] is False
    # the tracker open in two windows (29/10): the copy beside CTMS is the one brought up
    elsewhere = (1, [("inbox", "Inbox - Outlook"), ("copy", "DigiHaul Job Tracker.xlsx")])
    beside = (2, [("ctms", "Oracle Fusion Middleware Forms Services"), ("tracker", "DigiHaul Job Tracker.xlsx")])
    assert TB._pick([elsewhere, beside], "page") == (2, "tracker") and TB._pick([elsewhere, beside], "ctms") == (2, "ctms")
    assert TB._pick([elsewhere], "page") == (1, "copy") and TB._pick([elsewhere], "ctms") is None
    keep = (TB.IS_WIN, TB._select)
    TB.IS_WIN, TB._select = True, (lambda target: time.sleep(1) or (True, "too late"))
    try:
        ok, why = TB.select("ctms", timeout=0.1)
        assert ok is False and "in time" in why
    finally:
        TB.IS_WIN, TB._select = keep


def test_use_has_edge_bring_up_the_tab_only_while_claude_can_act_and_keys_wait_for_a_click():
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send, TB.select)
    ctms = dict(FAKE_WIN)
    tracker = dict(FAKE_WIN, hwnd=5151, kind="page", score=1, title="DigiHaul Job Tracker.xlsx - Work - Microsoft Edge",
                   content=[8, 90, 992, 692])
    showing, asked, sent = [tracker], [], []          # the tracker's tab is selected: CTMS's window is not there

    def bring_up(target):
        asked.append(target)
        showing[:] = [ctms] if target == "ctms" else [tracker]
        return True, "Brought up CTMS's tab in Edge."

    W.find_windows = lambda: [dict(w) for w in showing]
    drawn = _bgra([[0xFF000000 + (x * 7919 + y * 104729) % 0xFFFFFF for x in range(50)] for y in range(50)])
    W.picture = lambda win: (drawn, 50, 50, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    fronted = []
    A.to_front, A._send = (lambda hwnd: fronted.append(hwnd) or True), (lambda inputs: sent.append(1))
    TB.select = bring_up
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.handle({"id": 1, "action": "use", "target": "ctms"})         # 'Claude can act' off: Edge is left alone
        body = desk.sent[-1][1]
        assert body["ok"] is False and asked == [] and "Claude can act" in body["detail"]
        b.armed = True
        b.handle({"id": 2, "action": "use", "target": "ctms"})
        body = desk.sent[-1][1]
        assert body["ok"] and asked == ["ctms"] and b.win["hwnd"] == 4242 and "Brought up" in body["detail"]
        assert "click into the page" in body["payload"]["note"]
        assert fronted == [4242]                                    # Edge draws a tab only where it can be seen
        for i, cmd in enumerate(({"action": "key", "key": "f7"}, {"action": "type", "text": "x"})):
            b.handle(dict(cmd, id=3 + i))                              # where Edge put the focus is not known
            assert desk.sent[-1][1]["ok"] is False and "click into the page" in desk.sent[-1][1]["detail"]
        assert sent == []
        b.handle({"id": 5, "action": "click", "at": [0.5, 0.5]})
        b.handle({"id": 6, "action": "key", "key": "f7"})               # clicked into it: keys go
        assert desk.sent[-1][1]["ok"] and len(sent) == 2
        b.handle({"id": 7, "action": "use", "target": "ctms"})         # already showing: nothing asked of Edge
        assert desk.sent[-1][1]["ok"] and asked == ["ctms"]
        TB.select = lambda target: (False, "The DigiHaul Job Tracker is not open in any Edge tab.")
        b.handle({"id": 8, "action": "use", "target": "page"})         # not open: stay where we were
        body = desk.sent[-1][1]
        assert body["ok"] is False and "not open" in body["detail"] and b.target == "ctms" and b.win["hwnd"] == 4242
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send, TB.select = keep


def test_the_tracker_page_counts_only_as_the_selected_tab_and_never_above_ctms():
    keep = W.TEST_CLASSES
    W.TEST_CLASSES = ()
    page_title = "DigiHaul Job Tracker.xlsx and 2 more pages - Work - Microsoft Edge"
    try:
        assert W.score("Chrome_WidgetWin_1", page_title, 0, 0, 0) > 0                      # a window of its own
        assert W.score("Chrome_WidgetWin_1", "Inbox - Outlook - Work - Microsoft Edge", 0, 0, 0) == 0
        assert W.score("rctrl_renwnd32", "RE: DigiHaul Job Tracker", 0, 0, 0) == 0           # an email about it
        assert W.score("Chrome_WidgetWin_1", "Calidus TMS", 1, 1, 3) > W.score("Chrome_WidgetWin_1", page_title, 0, 0, 0)
    finally:
        W.TEST_CLASSES = keep
    page = dict(FAKE_WIN, kind="page", title=page_title, content=[8, 90, 992, 692])
    assert W.content_area(page) == [8, 90, 992, 692]                                        # its page, nothing more
    try:
        W.content_area(dict(page, content=None))
        assert False
    except RuntimeError as e:
        assert "tracker" in str(e)


def test_with_the_tracker_tab_selected_its_page_is_the_window_and_nothing_else():
    import types
    keep = (W.IS_WIN, W.dpi_aware, W._enum, W._cls, W._text, W._rect, W.user32, W._exe, W._frame, W._scale,
            W.TEST_CLASSES)
    top, ie, big, small, other = 100, 101, 102, 103, 200
    cls = {top: "Chrome_WidgetWin_1", ie: "Internet Explorer_Server", big: "Chrome_RenderWidgetHostHWND",
           small: "Chrome_RenderWidgetHostHWND", other: "Chrome_WidgetWin_1"}
    kids = {top: [ie, big, small], other: []}
    visible = {top: True, ie: False, big: True, small: True, other: True}
    rects = {top: [0, 0, 1000, 700], ie: [8, 120, 992, 692], big: [8, 90, 992, 692], small: [900, 90, 992, 200],
             other: [0, 0, 500, 500]}
    titles = {top: "DigiHaul Job Tracker.xlsx and 2 more pages - Work - Microsoft Edge",
              other: "Inbox - Outlook - Work - Microsoft Edge"}
    W._PAGE_AREA.clear()
    try:
        W.IS_WIN, W.TEST_CLASSES, W.dpi_aware = True, (), (lambda: None)
        W._enum = lambda parent=None: [top, other] if parent is None else kids.get(parent, [])
        W._cls, W._text, W._rect = (lambda h: cls[h]), (lambda h: titles.get(h, "")), (lambda h: rects[h])
        W.user32 = types.SimpleNamespace(IsWindowVisible=lambda h: visible[h], GetForegroundWindow=lambda: top,
                                         IsIconic=lambda h: False)
        W._exe, W._frame, W._scale = (lambda h: "msedge.exe"), (lambda h: rects[h]), (lambda h: 1.0)
        wins = W.find_windows()
        assert [w["hwnd"] for w in wins] == [top]                     # the Outlook window is never described
        assert wins[0]["kind"] == "page" and wins[0]["content"] == [8, 90, 992, 692]   # the page Edge draws
        # Edge drew the page without a window of its own (the work PC, 29/10): CTMS's hidden tab gives the area
        kids[top] = [ie]
        wins = W.find_windows()
        assert wins[0]["kind"] == "page" and wins[0]["content"] == [8, 120, 992, 692]
        rects[ie] = [8, 120, 1400, 900]                                 # gone stale past the window: kept inside
        assert W.find_windows()[0]["content"] == [8, 120, 1000, 700]
        rects[ie] = [8, 120, 992, 692]
        titles[top], visible[ie] = "Calidus TMS and 2 more pages - Work - Microsoft Edge", True   # back on CTMS
        wins = W.find_windows()
        assert wins[0]["kind"] == "edge" and wins[0]["content"] == [8, 120, 992, 692]
        # the tracker again, and now Edge keeps no window inside for either (the work PC, 29/10): the page
        # area CTMS's tab had in this window is remembered, moves with the window, and is dropped on a resize
        titles[top], kids[top] = "DigiHaul Job Tracker.xlsx and 2 more pages - Work - Microsoft Edge", []
        assert W.find_windows()[0]["content"] == [8, 120, 992, 692]
        rects[top] = [100, 50, 1100, 750]
        assert W.find_windows()[0]["content"] == [108, 170, 1092, 742]
        rects[top] = [0, 0, 1200, 800]
        assert W.find_windows()[0]["content"] is None
    finally:
        (W.IS_WIN, W.dpi_aware, W._enum, W._cls, W._text, W._rect, W.user32, W._exe, W._frame, W._scale,
         W.TEST_CLASSES) = keep


def test_the_tracker_selected_in_two_windows_is_worked_in_ctmss_own():
    import types
    keep = (W.IS_WIN, W.dpi_aware, W._enum, W._cls, W._text, W._rect, W.user32, W._exe, W._frame, W._scale,
            W.TEST_CLASSES)
    other, beside = 300, 100
    title = "DigiHaul Job Tracker.xlsx and 2 more pages - Work - Microsoft Edge"
    W._PAGE_AREA.clear()
    try:
        W.IS_WIN, W.TEST_CLASSES, W.dpi_aware = True, (), (lambda: None)
        W._enum = lambda parent=None: [other, beside] if parent is None else []
        W._cls, W._text, W._rect = (lambda h: "Chrome_WidgetWin_1"), (lambda h: title), (lambda h: [0, 0, 1000, 700])
        W.user32 = types.SimpleNamespace(IsWindowVisible=lambda h: True, GetForegroundWindow=lambda: other,
                                         IsIconic=lambda h: False)
        W._exe, W._frame, W._scale = (lambda h: "msedge.exe"), (lambda h: [0, 0, 1000, 700]), (lambda h: 1.0)
        assert [w["hwnd"] for w in W.find_windows()] == [other, beside]          # the one in front, as ever
        W._remember_area(beside, [0, 0, 1000, 700], [8, 120, 992, 692])          # CTMS has shown in this one
        assert [w["hwnd"] for w in W.find_windows()] == [beside, other]
    finally:
        (W.IS_WIN, W.dpi_aware, W._enum, W._cls, W._text, W._rect, W.user32, W._exe, W._frame, W._scale,
         W.TEST_CLASSES) = keep
        W._PAGE_AREA.clear()


def test_on_the_tracker_page_the_browsers_own_keys_are_refused():
    sent = []
    keep = (A.to_front, A._send)
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: sent.append(len(inputs)))
    try:
        for k in ("ctrl+l", "f5", "ctrl+tab", "alt+left", "ctrl+2", "F6", "ctrl+s"):
            try:
                A.press(1, k, page=True)
                assert False, k
            except A.Refused:
                pass
        assert sent == []                                              # none of them reached Windows
        for k in ("tab", "enter", "ctrl+g", "down"):
            A.press(1, k, page=True)
        assert len(sent) == 4
        A.press(1, "f5")                                               # in CTMS F5 is Forms' own key: still allowed
    finally:
        A.to_front, A._send = keep
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send)
    page = dict(FAKE_WIN, kind="page", title="DigiHaul Job Tracker.xlsx - Work - Microsoft Edge",
                content=[8, 90, 992, 692])
    W.find_windows = lambda: [dict(page)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    sent.clear()
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: sent.append(1))
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.scan_window(force=True)
        assert b.win is None                                           # every start is CTMS - not the page
        b.handle({"id": 0, "action": "use", "target": "page"})
        b.armed = True
        b.handle({"id": 1, "action": "key", "key": "ctrl+l"})          # the bridge says it is the page
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.handle({"id": 2, "action": "key", "key": "tab"})
        body = desk.sent[-1][1]
        assert body["ok"] and sent and "Tracker" in body["payload"]["note"]
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send = keep


def test_use_switches_the_bridge_between_ctms_and_the_tracker_and_stays_put_when_it_is_not_there():
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send)
    ctms = dict(FAKE_WIN)
    tracker = dict(FAKE_WIN, hwnd=5151, kind="page", score=1, title="DigiHaul Job Tracker.xlsx - Work - Microsoft Edge",
                   content=[8, 90, 992, 692])
    open_now = [ctms, tracker]
    W.find_windows = lambda: [dict(w) for w in open_now]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: None)
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        assert b.scan_window(force=True)["hwnd"] == 4242 and b.target == "ctms"      # every start is CTMS
        b.handle({"id": 1, "action": "use", "target": "page"})                       # looking: no switch needed
        body = desk.sent[-1][1]
        assert body["ok"] and b.win["hwnd"] == 5151 and "Tracker" in body["payload"]["note"]
        assert b.state()["target"] == "page"
        b.armed = True
        b.handle({"id": 2, "action": "key", "key": "ctrl+l"})                        # the page's rails apply
        assert desk.sent[-1][1]["ok"] is False
        b.handle({"id": 3, "action": "use", "target": "ctms"})
        assert desk.sent[-1][1]["ok"] and b.win["hwnd"] == 4242
        open_now.remove(tracker)                                                     # the tracker is closed
        b.handle({"id": 4, "action": "use", "target": "page"})
        assert desk.sent[-1][1]["ok"] is False and b.target == "ctms" and b.win["hwnd"] == 4242
        b.handle({"id": 5, "action": "use", "target": "somewhere"})
        assert desk.sent[-1][1]["ok"] is False and b.target == "ctms"
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send = keep


def test_the_dashboard_queues_use_without_the_switch_and_keeps_which_window_is_worked():
    import types
    fresh()
    assert call("/api/ctms/command", {"action": "use", "target": "page"}, key=AGENT)[0] == 200      # look-only
    assert call("/api/ctms/command", {"action": "use", "target": "elsewhere"}, key=AGENT)[0] == 200
    good, bad = S._ctms["queue"][-2:]
    assert good["target"] == "page" and "target" not in bad
    poll({"version": "2", "view": "window", "target": "page",
          "window": {"found": True, "title": "DigiHaul Job Tracker.xlsx", "kind": "page", "java": 0, "showing": True}})
    assert call("/api/ctms/status")[1]["state"]["target"] == "page"
    seen = {}
    keep = (R.load_state, R.ask, R.trace)
    R.load_state = lambda: {"kind": "window", "img_w": 1000, "img_h": 500}
    R.ask = lambda action, **a: (seen.update(action=action, args=a) or ({"ok": True, "detail": "ok"}, None))
    R.trace = lambda *a, **k: None
    try:
        R.run(types.SimpleNamespace(cmd="use", target="tracker"))
    finally:
        R.load_state, R.ask, R.trace = keep
    assert seen == {"action": "use", "args": {"target": "page"}}


FAKE_WIN = {"hwnd": 4242, "title": "Calidus TMS - Work - Microsoft Edge", "class": "Chrome_WidgetWin_1",
            "process": "msedge.exe", "rect": [0, 0, 1000, 700], "frame": [8, 0, 992, 692], "scale": 1.0,
            "minimized": False, "foreground": True, "score": 8, "kind": "edge", "ie": 1, "ie_showing": True,
            "content": [8, 120, 992, 692], "java": 3, "java_classes": ["SunAwtCanvas"], "java_hwnds": [1, 2, 3]}


class _Rec:
    base = "https://desk.example"

    def __init__(self):
        self.sent = []

    def post(self, path, body, timeout=20):
        self.sent.append((path, body))
        return {}


def test_with_ctms_s_window_found_the_bridge_watches_it_ahead_of_any_tab():
    keep = (W.find_windows, W.picture, B.LOG)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.scan_window(force=True)
        st = b.state()
        assert st["attached"] is True and st["view"] == "window" and st["tab_title"].startswith("Calidus")
        assert st["window"]["found"] and st["window"]["java"] == 3 and st["error"] == ""
        b.handle({"id": 1, "action": "see"})
        path, body = desk.sent[-1]
        assert body["ok"] and body["payload"]["kind"] == "window" and body["payload"]["mime"] == "image/png"
        assert base64.b64decode(body["payload"]["img"])[:4] == b"\x89PNG"
        b.armed = True                          # scrolling in the window is still the next increment...
        b.handle({"id": 2, "action": "scroll"})
        assert desk.sent[-1][1]["ok"] is False and "next increment" in desk.sent[-1][1]["detail"]
        b.watched = True                        # ...and the live view sends CTMS's window, as a PNG
        b.send_shot(force=True)
        shot = [bd for pth, bd in desk.sent if pth == "/api/ctms/shot"][-1]
        assert shot["mime"] == "image/png" and shot["w"] == 4
        W.find_windows = lambda: []             # CTMS closed
        b.scan_window(force=True)
        st = b.state()
        assert st["attached"] is False and "open it there" in st["error"]
    finally:
        W.find_windows, W.picture, B.LOG = keep


def test_ctms_act_guards_every_key_before_any_is_sent():
    assert A._combo("Shift+Ctrl+F10")[2] == "ctrl+shift+f10"      # order-independent, canonical
    assert A.text_units_for("A") == [0x41]
    assert A.text_units_for("\U0001F600") == [0xD83D, 0xDE00]     # a character above the BMP -> a surrogate pair
    sent = []
    keep = (A.to_front, A._send)
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: sent.append(len(inputs)))
    try:
        for junk in ("alt+f4", "ctrl+w", "ctrl+v", "f11"):        # OS/browser/paste keys never reach the keyboard
            try:
                A.press(1, junk)
                assert False, junk
            except A.Refused:
                pass
        assert sent == []
        try:
            A.press(1, "f10")                                    # F10 saves the record
            assert False
        except A.NeedsCommit:
            pass
        assert sent == []
        A.press(1, "f10", commit=True)                           # ...and goes through once he has said go
        assert sent and sent[-1] == 2                            # one key: down + up
        sent.clear()
        A.type_text(1, "HS123456")                               # one batch: down/up per key (+ Shift for capitals)
        assert len(sent) == 1 and sent[-1] >= len("HS123456") * 2
        A.to_front = lambda hwnd: False                          # if CTMS will not come to the front, nothing is sent
        n = len(sent)
        try:
            A.press(1, "tab")
            assert False
        except A.Refused:
            pass
        assert len(sent) == n
    finally:
        A.to_front, A._send = keep


def test_only_a_letter_or_digit_goes_as_a_one_character_key():
    sent = []
    keep = (A.to_front, A._send, A._vk)
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: sent.append(inputs))
    A._vk = lambda vk, ext, up=False: (vk, up)
    try:
        # each of these is another key's code: - Insert (shift+- a clipboard paste), % Left, ' Right, ! PageUp,
        # " PageDown, . Delete, $ Home, { F12
        for ch in "-%'!\".${/;=[]`\\,":
            for spec in (ch, "shift+" + ch, "ctrl+" + ch):
                try:
                    A.press(1, spec)
                    assert False, spec
                except A.Refused as e:
                    assert "only letters, digits and named keys" in str(e), e
        assert sent == []
        A.press(1, "ctrl+a")
        A.press(1, "7")
        assert [vk for vk, _ in sent[0] if vk not in A.MOD_VK.values()] == [0x41, 0x41]
        assert [vk for vk, _ in sent[1]] == [0x37, 0x37]
        try:
            A.press(1, "shift+insert")                               # the named key is still refused by its name
            assert False
        except A.Refused:
            pass
    finally:
        A.to_front, A._send, A._vk = keep


def test_the_input_record_is_the_size_windows_checks_for():
    # SendInput refuses everything unless told sizeof(INPUT) exactly as Windows defines
    # it: 32 bytes instead of 40 refused every key on the work PC (28/10)
    assert ctypes.sizeof(A.INPUT) == (40 if struct.calcsize("P") == 8 else 28)


def test_in_the_window_the_bridge_types_and_presses_but_save_waits_for_go_ahead():
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    sent = []
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: sent.append(len(inputs)))
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.scan_window(force=True)
        b.handle({"id": 1, "action": "type", "text": "x"})       # acting off: not even attempted
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.armed = True
        b.handle({"id": 2, "action": "type", "text": "HS123456"})
        body = desk.sent[-1][1]
        assert body["ok"] and body["payload"]["kind"] == "window" and sent[-1] >= len("HS123456") * 2
        b.handle({"id": 3, "action": "key", "key": "tab"})       # move between fields
        assert desk.sent[-1][1]["ok"]
        b.handle({"id": 4, "action": "key", "key": "f10"})       # save waits for his go-ahead
        r = desk.sent[-1][1]
        assert r["ok"] is False and r.get("payload", {}).get("needs_commit") is True
        b.handle({"id": 5, "action": "key", "key": "f10", "commit": True})
        assert desk.sent[-1][1]["ok"]
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send = keep


def test_the_click_area_is_the_ie_content_for_edge_and_the_frame_for_a_java_window():
    assert W.content_area(dict(FAKE_WIN)) == FAKE_WIN["content"]        # Edge: the IE content only
    jwin = dict(FAKE_WIN, kind="java", content=None, frame=[0, 0, 500, 400])
    assert W.content_area(jwin) == [0, 0, 500, 400]                     # a Java window: its whole frame


def test_in_the_window_a_click_lands_on_ctms_by_a_point_on_its_picture():
    pt = {}
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    sent = []
    A.to_front = lambda hwnd: True
    A._send = lambda inputs: sent.append(len(inputs))
    A._absolute = lambda x, y: (pt.update(xy=(x, y)) or (1, 2))
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.scan_window(force=True)
        b.handle({"id": 1, "action": "click", "at": [0.5, 0.5]})        # acting off: not even attempted
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.armed = True
        # the middle of the picture -> the middle of CTMS's content rect [8,120,992,692]
        b.handle({"id": 2, "action": "click", "at": [0.5, 0.5], "double": True})
        body = desk.sent[-1][1]
        assert body["ok"] and body["payload"]["kind"] == "window"
        assert pt["xy"] == (8 + round(0.5 * (992 - 8)), 120 + round(0.5 * (692 - 120)))   # (500, 406)
        assert sent[-1] == 5                       # move + down/up + down/up for the double-click
        n = len(sent)
        b.handle({"id": 3, "action": "click", "at": [1.4, 0.5]})        # off the picture: refused, nothing sent
        assert desk.sent[-1][1]["ok"] is False and len(sent) == n
        b.handle({"id": 4, "action": "click", "ref": 1})               # no point: says how to click here
        assert desk.sent[-1][1]["ok"] is False and "point on the picture" in desk.sent[-1][1]["detail"]
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute = keep


def test_the_home_side_sends_a_window_click_as_a_fraction_of_the_picture():
    import types
    seen = {}
    keep = (R.load_state, R.ask, R.trace)
    R.load_state = lambda: {"kind": "window", "img_w": 1000, "img_h": 500}
    R.ask = lambda action, **a: (seen.update(action=action, args=a) or ({"ok": True, "detail": "Clicked"}, None))
    R.trace = lambda *a, **k: None
    try:
        R.run(types.SimpleNamespace(cmd="click", at="250,400", ref=None, double=True, commit=False))
    finally:
        R.load_state, R.ask, R.trace = keep
    assert seen["action"] == "click" and seen["args"]["double"] is True
    assert seen["args"]["at"] == [0.25, 0.8]                            # 250/1000 across, 400/500 down


def test_a_drag_presses_moves_in_steps_and_always_lets_go_on_ctms():
    sent, pts = [], []
    keep = (A.to_front, A._send, A._absolute)
    A.to_front = lambda hwnd: True
    A._send = lambda inputs: sent.append([i.u.mi.dwFlags for i in inputs])
    A._absolute = lambda x, y: (pts.append((round(x), round(y))) or (1, 2))
    try:
        A.drag(1, (0.25, 0.1), (0.75, 0.5), (0, 0, 1000, 600), steps=4)
        assert pts[0] == (250, 60) and pts[-1] == (750, 300)           # press here, let go there
        assert sent[0][-1] & A.MOUSEEVENTF_LEFTDOWN and sent[-1][-1] & A.MOUSEEVENTF_LEFTUP
        assert len(sent) == 1 + 4 + 1                                  # press, four moves, let go
        sent.clear()
        try:
            A.drag(1, (0.2, 0.2), (1.3, 0.2), (0, 0, 1000, 600))       # the end is off CTMS: nothing pressed
            assert False
        except A.Refused:
            pass
        assert sent == []
        A.to_front = lambda hwnd: False                                # CTMS will not come to the front
        try:
            A.drag(1, (0.2, 0.2), (0.4, 0.2), (0, 0, 1000, 600))
            assert False
        except A.Refused:
            pass
        assert sent == []
    finally:
        A.to_front, A._send, A._absolute = keep


def test_in_the_window_a_drag_needs_both_points_and_acting_switched_on():
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    sent = []
    A.to_front, A._send, A._absolute = (lambda hwnd: True), (lambda inputs: sent.append(1)), (lambda x, y: (1, 2))
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.scan_window(force=True)
        b.handle({"id": 1, "action": "drag", "at": [0.3, 0.1], "to": [0.6, 0.1]})   # acting off
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.armed = True
        b.handle({"id": 2, "action": "drag", "at": [0.3, 0.1], "to": [0.6, 0.1]})
        assert desk.sent[-1][1]["ok"] and "Dragged" in desk.sent[-1][1]["detail"] and sent
        b.handle({"id": 3, "action": "drag", "at": [0.3, 0.1]})                        # no end point
        assert desk.sent[-1][1]["ok"] is False and "let go" in desk.sent[-1][1]["detail"]
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute = keep


def test_steps_run_on_the_work_pc_in_one_go_and_stop_at_the_first_refused():
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute, B.time.sleep)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    pictures = []
    W.picture = lambda win: pictures.append(1) or (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    sent = []
    A.to_front, A._send, A._absolute = (lambda hwnd: True), (lambda inputs: sent.append(1)), (lambda x, y: (1, 2))
    B.time.sleep = lambda s: None
    steps = [{"action": "click", "at": [0.5, 0.5]}, {"action": "key", "key": "home"},
             {"action": "type", "text": "977.50"}, {"action": "wait", "seconds": 1.5}, {"action": "key", "key": "tab"}]
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.handle({"id": 1, "action": "steps", "steps": steps})              # 'Claude can act' off
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.armed = True
        pictures.clear()
        b.handle({"id": 2, "action": "steps", "steps": steps})
        body = desk.sent[-1][1]
        assert body["ok"] and "Ran 5 step(s)" in body["detail"] and len(sent) == 4
        assert body["payload"]["kind"] == "window" and len(pictures) <= 2     # one look at the end, not five
        sent.clear()
        bad = [{"action": "click", "at": [0.5, 0.5]}, {"action": "key", "key": "ctrl+v"}, {"action": "key", "key": "tab"}]
        b.handle({"id": 3, "action": "steps", "steps": bad})                 # the clipboard is never pasted
        body = desk.sent[-1][1]
        assert body["ok"] is False and "step 2 of 3" in body["detail"] and len(sent) == 1 and body["payload"]
        b.handle({"id": 4, "action": "steps", "steps": [{"action": "steps"}]})
        assert desk.sent[-1][1]["ok"] is False                               # no batch inside a batch
        b.click_first = True                                                 # Edge has just switched tabs
        sent.clear()
        b.handle({"id": 5, "action": "steps", "steps": [{"action": "key", "key": "tab"}]})
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.handle({"id": 6, "action": "steps", "steps": steps})               # a click first: then keys go
        assert desk.sent[-1][1]["ok"] and b.click_first is False
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute, B.time.sleep = keep


def test_paste_puts_only_claudes_text_in_and_the_clipboard_back():
    board, sent = ["his own text"], []
    keep = (A._clip_text, A._clip_set, A.to_front, A._send, A.time.sleep)
    A._clip_text = lambda: board[0]
    A._clip_set = lambda text: board.__setitem__(0, text) or sent.append(("clip", text))
    A.to_front, A._send = (lambda hwnd: True), (lambda inputs: sent.append(("keys", [i.u.ki.wVk for i in inputs])))
    A.time.sleep = lambda s: None
    try:
        rows = "MAN-1\tPASS_DH\t325\tDelali\t\tY\nMAN-2\tAQ_DH\t895\tDelali\t\tN"
        assert A.paste_text(1, rows).startswith("Pasted 2 row(s)")
        assert sent[0] == ("clip", rows.replace("\n", "\r\n"))                      # ours, for the paste
        assert sent[1] == ("keys", [0x11, ord("V"), ord("V"), 0x11])                # Ctrl+V
        assert sent[2] == ("clip", "his own text") and board[0] == "his own text"  # and his put back
        for bad in ("", "  ", "x" * (A.PASTE_MAX + 1)):
            try:
                A.paste_text(1, bad)
                assert False, bad
            except A.Refused:
                pass
        try:
            A.press(1, "ctrl+v")                                                    # his clipboard: never
            assert False
        except A.Refused:
            pass
    finally:
        A._clip_text, A._clip_set, A.to_front, A._send, A.time.sleep = keep


def test_the_dashboard_lets_steps_and_paste_through_only_with_the_switch_and_only_window_steps():
    fresh()
    steps = [{"action": "click", "at": [0.5, 0.5], "junk": 1}, {"action": "reload"}, {"action": "steps"},
             {"action": "paste", "text": "a\tb\nc"}, "nonsense"] + [{"action": "key", "key": "tab"}] * 130
    for action, body in (("steps", {"steps": steps}), ("paste", {"text": "x"})):
        assert call("/api/ctms/command", dict(body, action=action), key=AGENT)[0] == 409   # switched off
    call("/api/ctms/control", {"on": True, "minutes": 15})
    assert call("/api/ctms/command", {"action": "steps", "steps": steps}, key=AGENT)[0] == 200
    queued = S._ctms["queue"][-1]["steps"]
    assert [s["action"] for s in queued[:3]] == ["click", "paste", "key"] and len(queued) <= 120
    assert "junk" not in queued[0] and queued[1]["text"] == "a\tb\nc"
    rows = "MAN-1\tPASS_DH\t325\tDelali\t\tY\n" * 100                            # past the 2000 a type takes
    assert call("/api/ctms/command", {"action": "paste", "text": rows}, key=AGENT)[0] == 200
    assert len(S._ctms["queue"][-1]["text"]) == min(len(rows), 6000)


def test_the_home_pc_sends_steps_as_one_batch_and_falls_back_one_by_one():
    import types
    keep = (R.load_state, R.ask, R.trace, R.save_state, R.print_screen)
    R.load_state = lambda: {"kind": "window", "img_w": 1000, "img_h": 500}
    asked = []

    def ask(action, **a):
        asked.append(action)
        if action == "steps" and old[0]:
            raise R.Stop("the CTMS bridge does not do 'steps'")
        return {"ok": True, "detail": "ok"}, None
    old = [False]
    R.ask, R.trace, R.save_state, R.print_screen = ask, (lambda *a, **k: None), (lambda p: None), (lambda *a: None)
    try:
        batch = R.parse_steps(["click 500,250", "right 100,50", "key shift+end", "type 977.50", "wait 1.5",
                               "paste MAN-1\\tPASS_DH"])
        assert batch[0] == {"action": "click", "at": [0.5, 0.5], "px": [500.0, 250.0]} and batch[1]["right"] is True
        assert batch[4] == {"action": "wait", "seconds": 1.5} and batch[5]["text"] == "MAN-1\tPASS_DH"
        for bad in (["shout 1,2"], ["click nowhere"], ["wait soon"]):
            try:
                R.parse_steps(bad)
                assert False, bad
            except R.Stop:
                pass
        assert R.run(types.SimpleNamespace(cmd="steps", items=["key tab", "key tab"], commit=False)) == 0
        assert asked == ["steps"]                                                # one round trip
        asked.clear()
        old[0] = True                                                            # a dashboard from before
        assert R.run(types.SimpleNamespace(cmd="planning-save")) == 0
        assert asked == ["steps", "click", "wait"]
    finally:
        R.load_state, R.ask, R.trace, R.save_state, R.print_screen = keep


def test_a_right_click_presses_only_the_right_button_and_only_on_ctms():
    sent = []
    keep = (A.to_front, A._send, A._absolute)
    A.to_front = lambda hwnd: True
    A._send = lambda inputs: sent.append([i.u.mi.dwFlags for i in inputs])
    A._absolute = lambda x, y: (1, 2)
    try:
        assert A.click(1, 0.5, 0.5, (0, 0, 1000, 600), right=True).startswith("Right-clicked")
        flags = sent[-1]
        assert len(flags) == 3 and flags[1] & A.MOUSEEVENTF_RIGHTDOWN and flags[2] & A.MOUSEEVENTF_RIGHTUP
        assert not any(f & (A.MOUSEEVENTF_LEFTDOWN | A.MOUSEEVENTF_LEFTUP) for f in flags)
        sent.clear()
        for fx, extra in ((1.3, {}), (0.5, {"double": True})):    # off CTMS / a right double-click
            try:
                A.click(1, fx, 0.5, (0, 0, 1000, 600), right=True, **extra)
                assert False
            except A.Refused:
                pass
        assert sent == []                                              # nothing pressed either time
    finally:
        A.to_front, A._send, A._absolute = keep


def test_the_right_flag_reaches_the_bridge_from_home_through_the_dashboard():
    import types
    seen = {}
    keep = (R.load_state, R.ask, R.trace)
    R.load_state = lambda: {"kind": "window", "img_w": 1000, "img_h": 500}
    R.ask = lambda action, **a: (seen.update(action=action, args=a) or ({"ok": True, "detail": "ok"}, None))
    R.trace = lambda *a, **k: None
    try:
        R.run(types.SimpleNamespace(cmd="click", at="250,400", ref=None, double=False, right=True, commit=False))
    finally:
        R.load_state, R.ask, R.trace = keep
    assert seen["args"]["right"] is True and seen["args"]["at"] == [0.25, 0.8]
    fresh()
    call("/api/ctms/control", {"on": True})
    assert call("/api/ctms/command", {"action": "click", "at": [0.25, 0.8], "right": True}, key=AGENT)[0] == 200
    assert S._ctms["queue"][-1]["right"] is True                       # kept, as a plain yes/no
    # and the bridge hands it to ctms_act
    keep = (W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    flags = []
    A.to_front, A._absolute = (lambda hwnd: True), (lambda x, y: (1, 2))
    A._send = lambda inputs: flags.extend(i.u.mi.dwFlags for i in inputs)
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.scan_window(force=True)
        b.armed = True
        b.handle({"id": 1, "action": "click", "at": [0.5, 0.5], "right": True})
        assert desk.sent[-1][1]["ok"] and "Right-clicked" in desk.sent[-1][1]["detail"]
        assert any(f & A.MOUSEEVENTF_RIGHTDOWN for f in flags)
    finally:
        W.find_windows, W.picture, B.LOG, A.to_front, A._send, A._absolute = keep


def test_the_dashboard_passes_a_drags_end_point_and_holds_it_until_acting_is_on():
    fresh()
    assert call("/api/ctms/command", {"action": "drag", "at": [0.3, 0.1], "to": [0.6, 0.1]}, key=AGENT)[0] == 409
    call("/api/ctms/control", {"on": True})
    assert call("/api/ctms/command", {"action": "drag", "at": [0.3, 0.1], "to": [0.6, "x"]}, key=AGENT)[0] == 200
    assert call("/api/ctms/command", {"action": "drag", "at": [0.3, 0.1], "to": [0.6, 0.1]}, key=AGENT)[0] == 200
    bad, good = S._ctms["queue"]
    assert "to" not in bad and good["to"] == [0.6, 0.1] and good["at"] == [0.3, 0.1]


def test_each_sent_site_email_owes_one_note_on_the_first_line_only():
    recs = [
        {"status": "sent", "kind": "delivery", "orders": ["1234567"], "emailed_at": "2026-10-28 09:15",
         "chases": 0},
        {"status": "sent", "kind": "delivery", "orders": ["2345678", "3456789-2-1"],
         "emailed_at": "2026-10-27 16:40", "chases": 2, "last_chased_at": "2026-10-30"},
        {"status": "drafted", "kind": "delivery", "orders": ["4567890"], "emailed_at": "2026-10-28 10:00"},
        {"status": "sent", "kind": "collection", "orders": ["5678901"], "emailed_at": "2026-10-28 11:00"},
        {"status": "sent", "kind": "delivery", "orders": ["1234567"], "emailed_at": "2026-10-28 09:15"},
    ]
    notes = N.owed(recs)
    got = [(n["ref"], n["note"]) for n in notes]
    assert got == [("2345678-1-1", " - Emailed DO 27/10"), ("3456789-1-1", " - Emailed DO 27/10"),
                   ("1234567-1-1", " - Emailed DO 28/10"),
                   ("2345678-1-1", " - Chased DO 30/10"), ("3456789-1-1", " - Chased DO 30/10")]
    # every note on the -1-1 line, never another; drafts and collection requests owe nothing
    assert all(n["ref"].endswith("-1-1") for n in notes)
    assert not any(n["order"] in ("4567890", "5678901") for n in notes)
    # once written, a note is off the list
    done = [{"ref": "1234567-1-1", "note": " - Emailed DO 28/10"}]
    assert ("1234567-1-1", " - Emailed DO 28/10") not in [(n["ref"], n["note"]) for n in N.owed(recs, done)]


def test_marking_a_note_written_is_kept_and_never_doubled():
    path = os.path.join(tempfile.mkdtemp(), "done.json")
    N.mark_done("1234567-1-1", " - Emailed DO 28/10", path)
    N.mark_done("1234567-1-1", " - Emailed DO 28/10", path)
    done = N.load_done(path)
    assert len(done) == 1 and done[0]["ref"] == "1234567-1-1"


def test_the_note_run_steps_go_in_order_and_stop_at_the_first_refusal():
    import types
    asked = []
    answers = {}
    keep = (R.load_state, R.ask, R.trace, R.save_state, R.print_screen)
    R.load_state = lambda: {"kind": "window", "img_w": 1910, "img_h": 915}

    def ask(action, **a):      # a run goes as one batch; its steps are what was asked for
        asked.extend([(s["action"], s) for s in a["steps"]] if action == "steps" else [(action, a)])
        return answers.get(action, ({"ok": True, "detail": "ok"}, None))
    R.ask = ask
    R.trace, R.save_state, R.print_screen = (lambda *a, **k: None), (lambda p: None), (lambda *a, **k: None)
    try:
        assert R.run(types.SimpleNamespace(cmd="order-find", order="1234567")) == 0
        assert [x[0] for x in asked] == ["anchor", "click", "key", "key", "type", "click", "wait"]
        assert asked[4][1]["text"] == "1234567%"                         # the order's lines, by its ref and a %
        assert asked[1][1]["px"] == [728, 123]                           # Customer Ref box, moved to wherever CTMS sits
        # the card's Clear empties the results, not the box - so the old ref is selected
        # and the new one replaces it, never appended to it (29/10 a second ref landed on the first)
        assert [x[1]["key"] for x in asked[2:4]] == ["home", "shift+end"]
        asked.clear()
        assert R.run(types.SimpleNamespace(cmd="order-note", note=" - Emailed DO 28/10")) == 0
        # the end of the whole text, not of the line clicked: a wrapped one took the note mid-text (02/11)
        assert [x[0] for x in asked] == ["anchor", "click", "key", "type"] and asked[2][1]["key"] == "ctrl+end"
        assert asked[1][1]["px"] == [1200, 682]                          # the box's bottom right
        asked.clear()
        # the work PC stops the batch at the refused step (test_steps_run_on_the_work_pc_...); here, the run says so
        answers["steps"] = ({"ok": False, "detail": "Stopped at step 2 of 3 (key): Refused: CTMS could not be "
                                                    "brought to the front"}, None)
        assert R.run(types.SimpleNamespace(cmd="order-note", note=" - Emailed DO 28/10")) == 3
    finally:
        R.load_state, R.ask, R.trace, R.save_state, R.print_screen = keep


# ---- an upload into CTMS, and the weight after it ---------------------------------------
def test_the_weight_an_upload_states_is_read_back_and_never_guessed():
    stated = {
        "Material Box Dimension  Qty 1 Weight  - 12kg-": 12,
        "Material Pallet Dimension Small box Qty 1 Weight  - 30kg-Delivery ASAP after collection": 30,
        "Weight  - 600Kgs-3.5 or 7.5ton vehicle Must have taillift": 600,     # the load, not the lorry
        "Qty X1 DRUM Weight - 400KG-DRUM W= 580MM X H 1000MM": 400,
        "Collect from stores / Weight 32 kg": 32,                             # repair_weights' wording
        "Weight - 3061kg- Del Notes 1234/567890": 3061,                       # a DTS upload's lead
        "Weight - 1 200kg-": 1200,                                            # "1,200" once commas are gone
        "Weight - approx 1.5 tonnes": 1500,
    }
    for text, want in stated.items():
        assert UW.kg(text)[0] == want, (text, UW.kg(text))
    for text in ("Weight - TBC", "Weight - 12", "Weight - 7.5ton vehicle", "Weight - 25kg each",
                 "Weight - 10-12kg", "Weight - 90000kg", "Del Notes 1234/567890", ""):
        weight, why = UW.kg(text)
        assert weight is None and why, (text, weight)                         # left to set by hand, with why


def test_each_order_in_an_upload_gets_the_weight_its_instructions_state():
    def order(ref, instr):
        r = [""] * 35
        r[0], r[1], r[27] = "ORDER", ref, instr
        return ",".join(r)
    path = os.path.join(tempfile.mkdtemp(), "NR_heavy_TEST.csv")
    with open(path, "w", encoding="cp1252", newline="") as f:
        f.write("\r\n".join([order("AH01/01/2026/AB-CD", "Material Box Dimension  Qty 1 Weight  - 12kg-"),
                             "ITEMS,Box,1" + "," * 32,
                             order("AH01/01/2026/EF-GH", "Material Pallet Dimension  Qty 2 Weight  - TBC")]) + "\r\n")
    got = UW.orders(path)
    assert [(ref, weight) for ref, weight, _ in got] == [("AH01/01/2026/AB-CD", 12), ("AH01/01/2026/EF-GH", None)]
    # the same weight on two orders of one file: each, or one load between them? Neither is set.
    with open(path, "w", encoding="cp1252", newline="") as f:
        f.write("\r\n".join([order("1234567", "Total Pallet Weight 126Kg / Alt Contact A"),
                             order("1234568", "Total Pallet Weight 126Kg / Alt Contact A")]) + "\r\n")
    got = UW.orders(path)
    assert [weight for _, weight, _ in got] == [None, None] and "same weight" in got[0][2]


def test_a_dts_upload_leads_its_instructions_with_the_weight():
    import types
    import nr_csv
    fake = types.ModuleType("dts_convert")
    fake.to_time = lambda v, end=False: "09:00"
    base = {"ref": "DTS-TEST-1", "pallets": 3, "del_notes": ["1234/567890"], "coll": {}, "deliv": {},
            "raiser_email": ""}
    keep = sys.modules.get("dts_convert")
    sys.modules["dts_convert"] = fake
    try:
        fake.parse_dts = lambda p: dict(base, weight_kg=3061)
        instr = nr_csv.dts_row("x.pdf")["Delivery Instructions"]
        assert instr == "Weight - 3061kg- Del Notes 1234/567890" and UW.kg(instr)[0] == 3061
        fake.parse_dts = lambda p: dict(base, weight_kg=0)                    # none on the DTS: none invented
        assert nr_csv.dts_row("x.pdf")["Delivery Instructions"] == "Del Notes 1234/567890"
    finally:
        if keep is None:
            sys.modules.pop("dts_convert", None)
        else:
            sys.modules["dts_convert"] = keep


def test_the_import_and_weight_runs_type_only_what_they_are_given():
    import types
    asked = []
    keep = (R.load_state, R.ask, R.trace, R.save_state, R.print_screen)
    R.load_state = lambda: {"kind": "window", "img_w": 1910, "img_h": 915}
    R.ask = lambda action, **a: (asked.extend([(s["action"], s) for s in a["steps"]] if action == "steps"
                                              else [(action, a)]) or ({"ok": True, "detail": "ok"}, None))
    R.trace, R.save_state, R.print_screen = (lambda *a, **k: None), (lambda p: None), (lambda *a, **k: None)
    try:
        path = "C:\\Downloads\\NR_heavy_AH01-01-2026-AB-CD_01012026120000.csv"
        assert R.run(types.SimpleNamespace(cmd="import-file", path=path)) == 0
        assert [x[0] for x in asked] == ["anchor", "click", "key", "key", "type"]
        assert [x[1]["key"] for x in asked[2:4]] == ["home", "shift+end"]     # the c:\temp default is replaced
        assert asked[4][1]["text"] == path and asked[1][1]["px"] == [357, 267]
        asked.clear()
        assert R.run(types.SimpleNamespace(cmd="order-weight", kg="12")) == 0
        assert [x[0] for x in asked] == ["anchor", "click", "wait", "click", "wait", "click", "key", "key", "type"]
        assert asked[-1][1]["text"] == "12" and asked[5][1]["px"] == [182, 405]
        assert not any(x[1].get("commit") for x in asked)                     # typing a weight saves nothing
        asked.clear()
        assert R.run(types.SimpleNamespace(cmd="order-weight-save")) == 0
        assert [x[1]["px"] for x in asked if x[0] == "click"] == [[182, 499],    # item Save
                                                                 [663, 499],    # item Exit
                                                                 [337, 733]]    # order Save
        # an ad hoc's ref is searched whole; an NR order by its 7-digit base
        assert R._search_ref("AH01/01/2026/AB-CD") == "AH01/01/2026/AB-CD"
        assert R._search_ref("1234567-1-1") == R._search_ref("1234567") == "1234567"
    finally:
        R.load_state, R.ask, R.trace, R.save_state, R.print_screen = keep


def test_the_probe_and_png_pictures_reach_the_dashboard_and_claude():
    fresh()
    assert call("/api/ctms/command", {"action": "probe"}, key=AGENT)[0] == 200    # looking: no switch needed
    poll({"version": "2", "view": "window",
          "window": {"found": True, "title": "Calidus TMS", "kind": "edge", "java": 3, "showing": True}})
    st = call("/api/ctms/status")[1]["state"]
    assert st["view"] == "window" and st["window"]["title"] == "Calidus TMS" and st["window"]["java"] == 3
    call("/api/ctms/shot", {"data": "iVBORw0K", "mime": "image/png", "w": 4, "h": 3}, key=BRIDGE)
    assert call("/api/ctms/shot")[1]["mime"] == "image/png"
    call("/api/ctms/shot", {"data": "AAAA", "mime": "text/html", "w": 4, "h": 3}, key=BRIDGE)
    assert call("/api/ctms/shot")[1]["mime"] == "image/jpeg"       # anything else is not trusted as-is


# ---- reading CTMS's fields through Java's Access Bridge ---------------------------------
def _n(role, name="", value=None, kids=(), hidden=False, focused=False, desc=""):
    states = {"enabled", "showing"} | (set() if hidden else {"visible"}) | ({"focused"} if focused else set())
    if role == "text":
        states.add("editable")
    n = {"role": role, "name": name, "desc": desc, "states": states, "kids": list(kids)}
    if value is not None:
        n["value"] = value
    return n


class _FakeJava:
    """CTMS's Java as the Access Bridge hands it over - counting every reference
    handed out and not given back, and every field whose contents were read."""

    def __init__(self, windows, top_level=(), titles=None):
        self.windows, self.top_level, self.titles = windows, list(top_level), titles or {}
        self.refs, self.held, self.read, self.next = {}, set(), [], 100

    def _ref(self, node):
        self.next += 1
        self.refs[self.next] = node
        self.held.add(self.next)
        return self.next

    def java_window(self, h):
        return h in self.windows

    def pid(self, h):
        return 7

    def top_windows(self):
        return list(self.top_level)

    def title(self, h):
        return self.titles.get(h, "")

    def cls(self, h):
        return "SunAwtFrame"

    def version(self, vm):
        return "1.8.0_481"

    def context(self, h):
        return 1, self._ref(self.windows[h])

    def top(self, vm, ac):
        return self._ref(self.refs[ac])

    def same(self, vm, a, b):
        return self.refs[a] is self.refs[b]

    def info(self, vm, ac):
        n = self.refs[ac]
        x, y, w, h = n.get("at", (0, 0, 10, 10))
        return {"role": n["role"], "name": n["name"], "description": n["desc"], "states": n["states"],
                "children": len(n["kids"]), "x": x, "y": y, "w": w, "h": h, "text": "value" in n}

    def child(self, vm, ac, k):
        return self._ref(self.refs[ac]["kids"][k])

    def text(self, vm, ac, most):
        self.read.append(self.refs[ac]["name"])
        return self.refs[ac]["value"][:most]

    def release(self, vm, ac):
        self.held.discard(ac)


def test_the_fields_reader_names_what_is_there_and_never_reads_a_password():
    applet = _n("frame", kids=[_n("internal frame", "Planning", kids=[
        _n("label", "Search"), _n("text", "Search", "x", focused=True),
        _n("password text", "Password", "hunter2"),
        _n("text", "Your PIN", "1234"),
        _n("panel", kids=[_n("text", "Order No", "HS1234567")]),     # an unnamed panel: looked through, not listed
        _n("panel", "hidden canvas", hidden=True, kids=[_n("text", "Gone", "nope")]),
        _n("push button", "Find")])])
    logon = _n("dialog", "Logon", kids=[_n("text", "Username", "user01"), _n("text", "Database", "proddb")])
    java = _FakeJava({11: applet, 12: applet, 20: logon}, top_level=[20, 99], titles={20: "Logon"})
    # 4242 is Edge itself (not Java); 11 and 12 are two parts of one applet; the logon box is a window of its own
    out = J.read([4242, 11, 12], api=java)
    els = out["elements"]
    assert out["java_windows"] == 3 and len(out["windows"]) == 2           # the applet read once, not twice
    search = next(e for e in els if e["r"] == "text" and e["nm"] == "Search")
    assert search["v"] == "x" and out["focus"] == search["n"] and "focused" in search["st"]
    named = {e["nm"]: e for e in els if e["r"] != "label"}
    assert named["Order No"]["v"] == "HS1234567" and named["Order No"]["lv"] == 1
    assert named["Find"]["r"] == "push button" and "Gone" not in named and "hidden canvas" not in named
    for secret in ("Password", "Your PIN", "Username", "Database"):
        assert named[secret]["secret"] and "v" not in named[secret], secret
    assert java.read == ["Search", "Order No"]          # nothing else's contents were even asked for
    assert java.held == set()                           # every Java object handed back to CTMS's Java


def test_a_huge_screen_is_cut_short_and_says_so_and_still_gives_everything_back():
    keep = J.LIMIT
    J.LIMIT = 50
    try:
        java = _FakeJava({11: _n("frame", kids=[_n("text", "", f"r{i}") for i in range(400)])})
        out = J.read([11], api=java)
        assert out["cut"] is True and len(out["elements"]) == 50
        assert java.held == set()
    finally:
        J.LIMIT = keep


def test_one_very_long_part_of_a_screen_no_longer_stops_the_rest_being_read():
    # Planning's canvas holds over 500 things: its order well's later columns went unread when one big part cut the
    # whole walk (02/11). Now that part is read up to the cap, and everything after it still is
    keep = J.KIDS
    J.KIDS = 30
    try:
        big = _n("panel", kids=[_n("text", "", f"r{i}") for i in range(60)])
        java = _FakeJava({11: _n("frame", kids=[big, _n("push button", "Order Filters")])})
        out = J.read([11], api=java)
        assert out["cut"] is False and out["partial"] is True
        assert any(e["r"] == "push button" and e["nm"] == "Order Filters" for e in out["elements"])
        assert sum(1 for e in out["elements"] if e["r"] == "text") == 30 and java.held == set()
    finally:
        J.KIDS = keep


def test_a_drop_down_that_isnt_open_is_not_walked_but_an_open_ones_rows_are_read():
    # one of Planning's holds thousands, none on the screen: most of a read's seven seconds. Open, its rows come as labels
    # with their places - how the Book button picks a carrier or a trailer by name (02/11)
    closed = _n("list", kids=[_n("label", f"hidden {i}") for i in range(30)])
    closed["at"] = (-1, -1, -1, -1)
    opened = _n("list", kids=[_n("label", "NR_ARTIC_FL")])
    opened["at"] = (853, 309, 239, 182)
    out = J.read([11], api=_FakeJava({11: _n("frame", kids=[closed, opened])}))
    names = [e["nm"] for e in out["elements"] if e["r"] == "label"]
    assert names == ["NR_ARTIC_FL"] and out["visited"] < 12


def test_a_window_whose_insides_arent_wanted_is_named_and_not_walked():
    # Planning's grid is most of a read's time, and nothing on an order's card needs it (02/11)
    frame = _n("frame", kids=[_n("internal frame", "Order details for 1", kids=[_n("text", "Customer Ref", "9100001-1-1")]),
                              _n("internal frame", "Planning", kids=[_n("text", "", f"r{i}") for i in range(30)])])
    whole = J.read([11], api=_FakeJava({11: frame}))
    out = J.read([11], api=_FakeJava({11: frame}), skip=("Planning",))
    assert [e["nm"] for e in out["elements"] if e["r"] == "internal frame"] == ["Order details for 1", "Planning"]
    assert any(e.get("v") == "9100001-1-1" for e in out["elements"]) and not any(e.get("v") == "r0" for e in out["elements"])
    assert out["visited"] < whole["visited"] - 25


def test_a_click_can_aim_at_a_screen_point_but_never_off_ctms():
    # where the Access Bridge places a field (an order well row's cell) is a screen point; taken of the picture's own
    # rectangle it is a fraction like any other - and one off CTMS is refused (02/11)
    b = B.Bridge(_Rec(), 1, "", allow_control=True)
    b.win = dict(FAKE_WIN)                                               # content [8, 120, 992, 692]
    fx, fy = b._point({"screen": [500, 406]})
    assert abs(fx - 0.5) < 1e-9 and abs(fy - 0.5) < 1e-9
    fx, fy = b._point({"screen": [2000, 406]})
    try:
        A._point(fx, fy, FAKE_WIN["content"])
        assert False, "a point off CTMS must be refused"
    except A.Refused:
        pass
    assert S._ctms_args("click", {"screen": [-40, 300.5]})["screen"] == [-40.0, 300.5]   # a second monitor


def test_the_bridge_checks_the_readers_answer_again_before_it_leaves_the_pc():
    out = {"windows": [{"w": 1, "title": "C-TMS"}, {"w": 2, "title": "Oracle Forms - Logon"}],
           "elements": [{"n": 1, "w": 1, "lv": 0, "r": "internal frame", "nm": "Sign In"},
                        {"n": 2, "w": 1, "lv": 1, "r": "text", "nm": "User", "v": "user01"},
                        {"n": 3, "w": 1, "lv": 0, "r": "internal frame", "nm": "Planning"},
                        {"n": 4, "w": 1, "lv": 1, "r": "text", "nm": "Search", "v": "x"},
                        {"n": 5, "w": 1, "lv": 1, "r": "password text", "nm": "Code", "v": "hunter2"},
                        {"n": 6, "w": 1, "lv": 1, "r": "text", "nm": "Notes", "ds": "password hint", "v": "abc"},
                        {"n": 7, "w": 2, "lv": 0, "r": "text", "nm": "Username", "v": "user01"}]}
    J.scrub(out)
    e = {x["n"]: x for x in out["elements"]}
    assert e[2]["secret"] and "v" not in e[2]            # inside a sign-in screen in the applet
    assert e[4]["v"] == "x"                              # an ordinary field keeps what is in it
    assert all("v" not in e[k] and e[k]["secret"] for k in (5, 6, 7))
    assert "hunter2" not in json.dumps(out) and "user01" not in json.dumps(out)
    assert "Logon screen" in J.summary(out)              # and the answer says where CTMS is


def test_a_dropped_ctms_session_is_called_out():
    # CTMS's session drops when left (seen in his walkthrough, 28/10): a Forms alert says so
    out = {"windows": [{"w": 1, "title": "", "class": "SunAwtCanvas"}], "took": 0.3, "focus": None,
           "elements": [{"n": 1, "w": 1, "lv": 0, "r": "label", "nm": "FRM-92102: A network error or server "
                                                                     "failure has occurred."},
                        {"n": 2, "w": 1, "lv": 0, "r": "push button", "nm": "OK"}]}
    assert "lost its connection" in J.summary(out) and "Logon" not in J.summary(out)
    assert J.VALUE_MAX >= 2000          # Special Instructions read whole: the contact note goes at the END


def test_fields_needs_its_32_bit_python_first_and_says_how_to_get_it():
    keep = (W.find_windows, W.picture, B.LOG, J.python32, J.IS_WIN)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    J.python32, J.IS_WIN = (lambda: None), True
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=False)       # reading needs nothing switched on
        b.scan_window(force=True)
        b.handle({"id": 1, "action": "fields"})
        r = desk.sent[-1][1]
        assert r["ok"] is False and "32-bit Python" in r["detail"] and "fields-setup" in r["detail"]
    finally:
        W.find_windows, W.picture, B.LOG, J.python32, J.IS_WIN = keep


def test_fields_come_back_by_name_with_the_cursor_and_secrets_held_back():
    reader = {"ok": True, "java_windows": 2, "java": "1.8.0_481", "took": 0.4, "cut": False, "focus": 2,
              "windows": [{"w": 1, "title": "", "class": "SunAwtCanvas"}],
              "elements": [{"n": 1, "w": 1, "lv": 0, "r": "internal frame", "nm": "Planning"},
                           {"n": 2, "w": 1, "lv": 1, "r": "text", "nm": "Search", "v": "x", "st": ["focused"]},
                           {"n": 3, "w": 1, "lv": 1, "r": "password text", "nm": "Password", "v": "leaked"}]}
    calls = []

    class _Done:
        returncode, stderr = 0, ""

        def __init__(self, out):
            self.stdout = out
    keep = (W.find_windows, W.picture, W.java_report, B.LOG, J.python32, J._run, J.IS_WIN)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    J.python32, J.IS_WIN = (lambda: r"C:\bridge\py32\python.exe"), True
    J._run = lambda args, timeout: calls.append(args) or _Done("noise\n" + json.dumps(reader) + "\n")
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "")
        b.scan_window(force=True)
        b.handle({"id": 1, "action": "fields"})
        r = desk.sent[-1][1]
        assert r["ok"] and "the cursor is in text 'Search' = 'x'" in r["detail"]
        p = r["payload"]
        assert p["kind"] == "fields" and p["title"].startswith("Calidus") and p["elements"][2]["secret"]
        assert "leaked" not in json.dumps(desk.sent)
        assert calls[0][1:4] == ["-I", os.path.abspath(J.__file__), "fields"]
        assert calls[0][4:] == ["4242", "1", "2", "3"]
        # CTMS's Java not answering at all: what to switch on, and how
        reader.update(java_windows=0, windows=[], elements=[])
        W.java_report = lambda: {"switched_on": False, "installs": [
            {"home": r"C:\Program Files (x86)\Java\jre1.8.0_481", "jabswitch": True}]}
        b.handle({"id": 2, "action": "fields"})
        r = desk.sent[-1][1]
        assert r["ok"] is False and r"jre1.8.0_481\bin\jabswitch.exe" in r["detail"] and "-enable" in r["detail"]
        W.java_report = lambda: {"switched_on": True, "installs": []}
        b.handle({"id": 3, "action": "fields"})
        assert "open it again" in desk.sent[-1][1]["detail"]
    finally:
        W.find_windows, W.picture, W.java_report, B.LOG, J.python32, J._run, J.IS_WIN = keep


def test_the_32_bit_python_is_unpacked_only_when_its_fingerprint_matches():
    def zip_of(files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        return buf.getvalue()
    good = zip_of({"python.exe": b"MZ fake", "python312.zip": b"lib"})
    evil = zip_of({"python.exe": b"MZ", "../escaped.txt": b"x"})
    served = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    class _Opener:
        def open(self, url, timeout=None):
            return _Resp(served["data"])
    root = tempfile.mkdtemp()
    keep = (J.PY32_DIR, J.PY32_SHA256, J.bits, J.IS_WIN, U.opener_for)
    J.PY32_DIR, J.IS_WIN = os.path.join(root, "py32"), True
    U.opener_for = lambda url: _Opener()
    runs32 = (lambda exe: 32 if os.path.isfile(exe) else None)
    J.bits = runs32
    try:
        served["data"], J.PY32_SHA256 = good, hashlib.sha256(b"a proxy page").hexdigest()
        try:
            J.setup()
            assert False, "unpacked without a matching fingerprint"
        except J.SetupError as e:
            assert "fingerprint" in str(e)
        assert not os.path.exists(J.PY32_DIR)
        served["data"], J.PY32_SHA256 = evil, hashlib.sha256(evil).hexdigest()
        try:
            J.setup()
            assert False, "unpacked a path outside its folder"
        except J.SetupError as e:
            assert "outside its folder" in str(e)
        assert not os.path.exists(os.path.join(root, "escaped.txt")) and not os.path.exists(J.PY32_DIR)
        served["data"], J.PY32_SHA256 = good, hashlib.sha256(good).hexdigest()
        J.bits = lambda exe: 64
        try:
            J.setup()
            assert False, "kept a Python that is not 32-bit"
        except J.SetupError as e:
            assert "32-bit" in str(e)
        assert not os.path.exists(J.PY32_DIR) and not os.path.exists(J.PY32_DIR + ".new")
        J.bits = runs32
        assert "Fetched" in J.setup()
        assert os.path.isfile(os.path.join(J.PY32_DIR, "python.exe"))
        assert "already here" in J.setup()
    finally:
        J.PY32_DIR, J.PY32_SHA256, J.bits, J.IS_WIN, U.opener_for = keep
        shutil.rmtree(root, ignore_errors=True)


def test_reading_fields_needs_no_switch_and_its_setup_is_an_admin_job():
    fresh()
    assert call("/api/ctms/command", {"action": "fields"}, key=AGENT)[0] == 200
    assert call("/api/ctms/command", {"action": "fields_setup"}, key=AGENT)[0] == 200
    assert [c["action"] for c in S._ctms["queue"]] == ["fields", "fields_setup"]
    assert "fields" in B.READ and "fields_setup" in B.ADMIN            # the bridge's own list agrees


# ---- fast steps: where CTMS sits, waiting on the screen, snaps (ctms_fast) ---------------------
GREY = 0xFF666666                       # CTMS's menu bar, (102, 102, 102)


def _ctms_frame(w, h, top, left=15, bar_rows=30, extra=None):
    """A white picture w x h with CTMS's grey menu bar from row `top`, `bar_rows` tall, from column `left`."""
    rows = [[GREY if top <= y < top + bar_rows and x >= left else 0xFFFFFFFF for x in range(w)] for y in range(h)]
    for (x, y), p in (extra or {}).items():
        rows[y][x] = p
    return _bgra(rows)


def test_the_anchor_reads_how_far_ctms_has_moved_off_its_menu_bar():
    w, h = 320, 120
    assert F.anchor(_ctms_frame(w, h, top=21), w, h) == (0, 0)          # as measured: bottom row 50, left 15
    assert F.anchor(_ctms_frame(w, h, top=0), w, h) == (0, -21)         # page scrolled: the bar's top is gone
    assert F.anchor(_ctms_frame(w, h, top=21, left=40), w, h) == (25, 0)
    assert F.anchor(_ctms_frame(w, h, top=21, bar_rows=0), w, h) is None   # no bar: says so, never guesses


def test_the_screen_is_compared_in_blocks_and_a_blinking_caret_is_not_an_answer():
    w, h = 200, 100
    white = [[0xFFFFFFFF] * w for _ in range(h)]
    a = _bgra(white)
    assert F.changed(a, a, w, h) == 0
    caret = [row[:] for row in white]
    caret[5][5] = 0xFF000000
    assert F.changed(a, _bgra(caret), w, h) == 1 <= F.QUIET_BLOCKS
    assert F.changed(a, _bgra(caret), w, h, box=(100, 0, 200, 100)) == 0      # outside the watched box
    window = [[0xFF000000 if 40 <= x < 160 else 0xFFFFFFFF for x in range(w)] for _ in range(h)]
    assert F.changed(a, _bgra(window), w, h) > F.QUIET_BLOCKS                 # a window drawing: an answer
    assert F.shift_box([10, 20, 30, 40], (5, -21)) == [15, -1, 35, 19]
    assert F.parse_color("#00ff7F") == (0, 255, 127) and F.hex_color((0, 255, 127)) == "#00FF7F"


def test_a_fast_batch_anchors_its_points_waits_for_ctms_and_keeps_snaps():
    keep = (W.find_windows, W.picture, B.LOG, A.click, A.to_front, A._send, B.time.sleep)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    w, h = 320, 200
    base = _ctms_frame(w, h, top=0)                                     # the page scrolled: CTMS sits 21 px up
    answered = _ctms_frame(w, h, top=0, extra={(x, y): 0xFF0000FF for x in range(100, 220) for y in range(120, 160)})
    frames = {"now": base}
    W.picture = lambda win: (frames["now"], w, h, "from the window")
    clicks = []

    def click(hwnd, fx, fy, area, double=False, right=False):
        clicks.append((round(fx * w), round(fy * h)))
        frames["now"] = answered                                        # CTMS answers the click
        return "Clicked"
    A.click, A.to_front, A._send = click, (lambda hwnd: True), (lambda inputs: None)
    B.time.sleep = lambda s: None
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True
        steps = [{"action": "anchor"},
                 {"action": "click", "px": [150, 161], "at": [0.9, 0.9], "react": True, "quiet": 0.05,
                  "box": [100, 141, 220, 181]},
                 {"action": "waitfor", "px": [150, 161], "color": "#0000FF", "timeout": 1},
                 {"action": "snap", "name": "answer", "box": [100, 141, 220, 181]}]
        b.handle({"id": 1, "action": "steps", "steps": steps})
        body = desk.sent[-1][1]
        assert body["ok"], body["detail"]
        assert clicks == [(150, 140)]                    # px moved up by the anchor - the stale 'at' not used
        snap = body["payload"]["snaps"][0]
        assert snap["name"] == "answer" and (snap["w"], snap["h"]) == (120, 40) and snap["img"]
        assert len(body["payload"]["times"]) == 4 and body["payload"]["took"] is not None
        frames["now"] = base                             # a colour that is not there stops the batch, saying why
        b.handle({"id": 2, "action": "steps", "steps": [{"action": "anchor"},
                                                        {"action": "check", "px": [150, 161], "color": "#0000FF"},
                                                        {"action": "key", "key": "tab"}]})
        body = desk.sent[-1][1]
        assert body["ok"] is False and "step 2 of 3" in body["detail"] and "#FFFFFF" in body["detail"]
        A.click = lambda *a, **k: "Clicked"              # CTMS not answering: stop, never click on blind
        b.handle({"id": 3, "action": "steps", "steps": [{"action": "click", "px": [10, 10], "react": True,
                                                         "timeout": 0.2}, {"action": "key", "key": "tab"}]})
        body = desk.sent[-1][1]
        assert body["ok"] is False and "did not answer" in body["detail"] and "step 1 of 2" in body["detail"]
        b.handle({"id": 4, "action": "steps", "steps": [{"action": "snap", "box": [0, 0, 5000, 5000]}]})
        assert desk.sent[-1][1]["ok"] is False                                  # a snap is a small part
    finally:
        W.find_windows, W.picture, B.LOG, A.click, A.to_front, A._send, B.time.sleep = keep


def test_the_dashboard_lets_the_fast_steps_through_with_their_fields_and_nothing_else():
    fresh()
    call("/api/ctms/control", {"on": True, "minutes": 15})
    steps = [{"action": "anchor", "junk": 1},
             {"action": "click", "px": [150, 161], "at": [0.5, 0.5], "react": True, "box": [1, 2, 3, 4],
              "quiet": 0.4, "after": 0.1, "timeout": 12},
             {"action": "waitfor", "px": [1, 2], "color": "ffffff", "tol": 10, "not": True, "timeout": 5},
             {"action": "snap", "name": "two words!", "box": [0, 0, 10, 10]},
             {"action": "settle", "quiet": 9}]
    assert call("/api/ctms/command", {"action": "steps", "steps": steps}, key=AGENT)[0] == 200
    q = S._ctms["queue"][-1]["steps"]
    assert [s["action"] for s in q] == ["anchor", "click", "waitfor", "snap", "settle"] and "junk" not in q[0]
    assert q[1]["px"] == [150.0, 161.0] and q[1]["react"] is True and q[1]["box"] == [1.0, 2.0, 3.0, 4.0]
    assert q[1]["quiet"] == 0.4 and q[1]["after"] == 0.1 and q[1]["timeout"] == 12
    assert q[2]["color"] == "#FFFFFF" and q[2]["tol"] == 10 and q[2]["not"] is True
    assert q[3]["name"] == "two-words" and "quiet" not in q[4]          # 9 s is past what a settle may ask
    assert set(B.BATCH_STEPS) <= set(S.CTMS_STEP_ACTIONS)               # the bridge's list agrees


def test_the_home_pc_writes_the_fast_steps_and_the_order_update_recipe():
    import types
    keep = R.load_state, R.TEMPLATES
    R.load_state = lambda: {"kind": "window", "img_w": 1910, "img_h": 915}
    R.TEMPLATES = os.path.join(tempfile.gettempdir(), "ctms_templates_test.json")
    with open(R.TEMPLATES, "w", encoding="utf-8") as f:
        json.dump({n: {"w": 2, "h": 1, "rgb": "AAAAAAAA"} for n in ("os-search", "os-card")}, f)
    try:
        b = R.parse_steps(["anchor", "click 245,67 react box=440,100,1230,200 timeout=25", "key tab after=0.05",
                           "waitfor 728,122 ffffff tol=10 timeout=12", "check 5,6 #00FF00 not",
                           "snap order 15,120,1255,166", "settle quiet=0.3"])
        assert b[0] == {"action": "anchor"} and b[1]["px"] == [245.0, 67.0] and b[1]["react"] is True
        assert b[1]["box"] == [440.0, 100.0, 1230.0, 200.0] and b[1]["timeout"] == 25.0
        assert b[2] == {"action": "key", "key": "tab", "commit": False, "after": 0.05}
        assert b[3] == {"action": "waitfor", "px": [728.0, 122.0], "color": "#FFFFFF", "tol": 10, "timeout": 12.0}
        assert b[4]["not"] is True and b[5]["box"] == [15.0, 120.0, 1255.0, 166.0] and b[6]["quiet"] == 0.3
        for bad in (["click 1,2 maybe"], ["waitfor 1,2 red"], ["snap x 1,2,3"], ["anchor now"]):
            try:
                R.parse_steps(bad)
                assert False, bad
            except R.Stop:
                pass
        a = types.SimpleNamespace(order="1234567-1-1", collect="04/11/26 08:00-16:00", deliver="05/11/26 8:00-12:00",
                                  comments="05/11/26 08:00 - Sam Example 07700900123 - HIAB required")
        steps = R.parse_steps(R.order_update_items(a))
        assert len(steps) <= B.STEPS_MAX and steps[0] == {"action": "anchor"}
        assert [s["text"] for s in steps if s["action"] == "type"] == [
            "1234567-1-1", "04/11/26", "08:00", "04/11/26", "16:00", "05/11/26", "08:00", "05/11/26", "12:00",
            a.comments]                          # the deliver side's location comments - only there
        assert [288.0, 187.0] not in [s.get("px") for s in steps]       # not Add Detail's Order Comments
        pts = [s.get("px") for s in steps]
        assert pts.index([1080.0, 676.0]) < pts.index([470.0, 578.0])     # deliver-side Edit, then the box's Save
        assert [337.0, 733.0] not in [s.get("px") for s in steps]                   # the update never saves
        a.comments = "a, b"
        try:
            R.order_update_items(a)
            assert False
        except R.Stop:
            pass
    finally:
        R.load_state, R.TEMPLATES = keep


def test_the_update_starts_at_a_search_card_left_open_and_the_save_answers_the_schedule_question():
    import types
    keep = (R.load_state, R.TEMPLATES, R.ask, R.OUT)
    R.load_state = lambda: {"kind": "window", "img_w": 1910, "img_h": 915}
    R.TEMPLATES = os.path.join(tempfile.gettempdir(), "ctms_templates_test.json")
    with open(R.TEMPLATES, "w", encoding="utf-8") as f:
        json.dump({n: {"w": 2, "h": 1, "rgb": "AAAAAAAA"} for n in ("os-search", "os-card", "schedule-ask")}, f)
    R.OUT = tempfile.mkdtemp()                                         # its traces and run log, not the real ones
    try:
        a = types.SimpleNamespace(order="1234567-1-1", collect=None, deliver="05/11/26 08:00-12:00", comments=None)
        fresh = [s.get("px") for s in R.parse_steps(R.order_update_items(a))]
        left = R.parse_steps(R.order_update_items(a, card_open=True))
        pts = [s.get("px") for s in left]
        assert [121.0, 36.0] in fresh and [121.0, 36.0] not in pts       # with the card up, the menu does nothing
        assert [s["name"] for s in left if s["action"] == "find"] == ["os-card"]
        assert not any(s["action"] == "waitfor" for s in left)            # its labels, not a box's colour (31/10)
        assert pts.index([626.0, 226.0]) < pts.index([728.0, 122.0])       # Clear empties the last search first
        for asks in (True, False):                                        # "Change schedule to:" up, or not
            sent = []

            def ask(action, **kw):
                sent.append(kw["steps"])
                return {"ok": asks if kw["steps"][-1]["action"] == "find" else True, "detail": "ok"}, None
            R.ask = ask
            assert R.order_save_close() == 0
            clicks = [s["px"] for steps in sent for s in steps if s["action"] == "click"]
            assert clicks == ([[1000.0, 37.0], [337.0, 733.0]] + ([[952.0, 505.0]] if asks else [])
                              + [[1000.0, 37.0], [424.0, 733.0]])                 # Save, its OK, then Close
        with open(os.path.join(R.OUT, "runs.jsonl"), encoding="utf-8") as f:
            runs = [json.loads(line) for line in f]
        assert [(r["kind"], r["ok"]) for r in runs] == [("order-save-close", True)] * 2   # one line a save
    finally:
        R.load_state, R.TEMPLATES, R.ask, R.OUT = keep


TEAL = 0xFF364C4C                       # an active window's title bar, (54, 76, 76)


def test_the_window_anchor_reads_how_far_ctms_s_own_area_has_scrolled():
    w, h = 320, 120
    rows = lambda title_last: [[GREY if 21 <= y <= 50 and x >= 15 else
                                (TEAL if 52 <= y <= title_last else 0xFFFFFFFF) for x in range(w)] for y in range(h)]
    assert F.window_offset(_bgra(rows(75)), w, h, 50) == 0               # title bar ends 25 under the menu bar
    assert F.window_offset(_bgra(rows(67)), w, h, 50) == -8              # its area scrolled 8 px (30/10)
    assert F.window_offset(_bgra(rows(0)), w, h, 50) == 0                # no title bar: no guess
    red, light = 0xFFCA0202, 0xFFE1E1E1
    live = rows(75)
    for y in (76, 77):
        live[y] = [light] * w                                            # the window's grey border
    for y in range(78, 84):
        live[y] = [red] * w                                              # its red band
    live[84] = [TEAL] * w                                                # a button's teal edge: not the title
    assert F.window_offset(_bgra(live), w, h, 50) == 0
    dotted = rows(75)
    for y in (60, 61, 62):
        dotted[y] = [0xFFCCCCCC] * w                                     # the title bar's dotted texture
    assert F.window_offset(_bgra(dotted), w, h, 50) == 0


def test_find_spots_an_exact_picture_and_nothing_like_it():
    w, h = 60, 30
    words = [[0xFFFFFFFF] * 6, [0xFF000000, 0xFFFFFFFF, 0xFF000000, 0xFF000000, 0xFFFFFFFF, 0xFF000000],
             [0xFFFFFFFF] * 6]                                            # blank top row: the busiest row is searched
    screen = [[0xFFFFFFFF] * w for _ in range(h)]
    for r, row in enumerate(words):
        screen[12 + r][30:36] = row
    tpl = _bgra(words)
    assert F.find(_bgra(screen), w, h, (0, 0, w, h), tpl, 6, 3) == (30, 12)
    assert F.find(_bgra(screen), w, h, (0, 0, 30, h), tpl, 6, 3) is None   # outside the box: not looked at
    screen[13][32] = 0xFFFFFFFF                                           # one pixel different: not it
    assert F.find(_bgra(screen), w, h, (0, 0, w, h), tpl, 6, 3) is None
    rgb = bytes([0, 0, 255, 255, 255, 255])
    assert F.rgb_to_bgra(rgb, 2, 1) == bytes([255, 0, 0, 255, 255, 255, 255, 255])


def test_find_clicks_the_middle_of_what_it_found_and_the_window_anchor_moves_points():
    keep = (W.find_windows, W.picture, B.LOG, A.click, B.time.sleep)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    w, h = 320, 200
    words = [[0xFF000000, 0xFFFFFFFF, 0xFF000000, 0xFF000000]] * 2
    rows = [[GREY if y <= 29 and x >= 15 else (TEAL if 31 <= y <= 46 else 0xFFFFFFFF) for x in range(w)]
            for y in range(h)]                       # page scrolled 21 up, CTMS's area 8 more
    for r, row in enumerate(words):
        rows[100 + r][200:204] = row
    W.picture = lambda win: (_bgra(rows), w, h, "from the window")
    clicks = []
    A.click = lambda hwnd, fx, fy, area, double=False, right=False: clicks.append((fx * w, fy * h)) or "Clicked"
    B.time.sleep = lambda s: None
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    tpl = base64.b64encode(b"".join(bytes([(p >> 16) & 255, (p >> 8) & 255, p & 255]) for row in words for p in row))
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True
        b.handle({"id": 1, "action": "steps", "steps": [
            {"action": "anchor", "window": True},
            {"action": "find", "name": "word", "tpl": tpl.decode(), "tw": 4, "th": 2, "box": [150, 120, 300, 140],
             "click": True},
            {"action": "click", "px": [100, 129]}]})
        body = desk.sent[-1][1]
        assert body["ok"], body["detail"]
        assert b.batch["off"] == (0, -29)                          # -21 page, -8 its own area
        assert clicks[0] == (202.0, 101.0) and clicks[1] == (100.0, 100.0)
        b.handle({"id": 2, "action": "steps", "steps": [
            {"action": "find", "name": "word", "tpl": tpl.decode(), "tw": 4, "th": 2, "box": [0, 0, 100, 50],
             "click": True}]})
        body = desk.sent[-1][1]
        assert body["ok"] is False and "not on the screen" in body["detail"] and len(clicks) == 2
    finally:
        W.find_windows, W.picture, B.LOG, A.click, B.time.sleep = keep


def test_the_dashboard_passes_find_and_the_window_anchor():
    fresh()
    call("/api/ctms/control", {"on": True, "minutes": 15})
    steps = [{"action": "anchor", "window": True},
             {"action": "find", "name": "veh rigid", "tpl": "AAAA", "tw": 4, "th": 2, "box": [1, 2, 3, 4],
              "click": True, "react": True},
             {"action": "find", "name": "x", "tpl": "<script>", "tw": 999}]
    assert call("/api/ctms/command", {"action": "steps", "steps": steps}, key=AGENT)[0] == 200
    q = S._ctms["queue"][-1]["steps"]
    assert q[0] == {"action": "anchor", "window": True}
    assert q[1]["tpl"] == "AAAA" and q[1]["tw"] == 4 and q[1]["click"] is True and q[1]["name"] == "veh-rigid"
    assert "tpl" not in q[2] and "tw" not in q[2]                      # not a picture, not a size


def test_the_recipe_closes_the_card_first_and_a_rigid_never_gets_rear_steer():
    import types
    keep = (R.load_state, R.TEMPLATES)
    R.load_state = lambda: {"kind": "window", "img_w": 1910, "img_h": 915}
    R.TEMPLATES = os.path.join(tempfile.gettempdir(), "ctms_templates_test.json")
    with open(R.TEMPLATES, "w", encoding="utf-8") as f:
        json.dump({n: {"w": 2, "h": 1, "rgb": "AAAAAAAA"} for n in ("veh-rigid-40ft", "os-search", "os-card")}, f)
    try:
        a = types.SimpleNamespace(order="1234567-1-1", collect=None, deliver=None,
                                  comments="05/11/26 08:00 - Sam Example 07700900123 - HIAB required",
                                  add_service=None, remove_service_row=[2], veh="rigid")
        steps = R.parse_steps(R.order_update_items(a))
        pts = [s.get("px") for s in steps]
        assert pts.index([509.0, 226.0]) < pts.index([267.0, 238.0])     # the card shut before the order opens
        assert [174.0, 318.0] in pts and [734.0, 648.0] in pts            # row 2 picked, then Delete
        found = [s for s in steps if s["action"] == "find"]
        assert [(s["name"], bool(s.get("click"))) for s in found] == [
            ("os-search", True), ("os-card", False), ("veh-rigid-40ft", True)]     # the card only looked for
        assert len(steps) <= 120
        for bad in (dict(comments="05/11/26 - Rear steer required"), dict(add_service=["REAR STEER"])):
            b = types.SimpleNamespace(**dict(vars(a), **bad))
            try:
                R.order_update_items(b)
                assert False, bad
            except R.Stop as e:
                assert "rigid" in str(e).lower()
        b = types.SimpleNamespace(**dict(vars(a), veh="artic", add_service=["pts"], ballast=True))
        try:
            R.order_update_items(b)                                       # ballast: PTS never added
            assert False
        except R.Stop as e:
            assert "ballast" in str(e).lower()
        same = dict(vars(a), veh=None, add_service=["STORAGE"], comments=None)
        try:                                                              # same day: no storage
            R.order_update_items(types.SimpleNamespace(**dict(same, collect="05/11/26 08:00-10:00",
                                                                deliver="05/11/26 12:00-14:00")))
            assert False
        except R.Stop as e:
            assert "same day" in str(e)
        R.order_update_items(types.SimpleNamespace(**dict(same, collect="04/11/26 08:00-16:00",
                                                          deliver="05/11/26 08:00-12:00")))   # the day before: fine
    finally:
        R.load_state, R.TEMPLATES = keep


# ---- the browser's "open or save?" box after an export (31/10) -------------------------------
SAVE_BOX = {"hwnd": 77, "title": "Internet Explorer", "process": "iexplore.exe", "frame": [100, 100, 500, 300],
            "foreground": True, "words": ["Do you want to open or save short_rail_rep_x.csv?"],
            "parts": ["Button", "Static"], "buttons": [{"text": "Open", "hwnd": 81, "id": 1},
                                                       {"text": "Save", "hwnd": 82, "id": 2},
                                                       {"text": "Cancel", "hwnd": 83, "id": 3}]}


def test_only_a_standard_dialog_of_ctmss_own_browser_is_its_box():
    assert W.is_prompt("#32770", "iexplore.exe") and W.is_prompt("#32770", "MSEDGE.EXE")
    for cls, exe in (("#32770", "outlook.exe"), ("#32770", "ms-teams.exe"), ("#32770", "explorer.exe"),
                     ("Chrome_WidgetWin_1", "msedge.exe"), ("IEFrame", "iexplore.exe"), ("#32770", "")):
        assert not W.is_prompt(cls, exe), (cls, exe)


def test_the_browsers_box_is_seen_without_the_switch_and_only_ever_saved_never_opened():
    import types
    keep = (W.prompts, W.prompt_picture, W.front, W.find_windows, A.user32, B.LOG)
    boxes = [dict(SAVE_BOX)]
    W.prompts = lambda: [dict(b) for b in boxes]
    W.prompt_picture = lambda p: (_bgra([[0xFFFFFFFF] * 4] * 3), 4, 3, "from the window")
    W.front = lambda: {"process": "outlook.exe", "class": "rctrl_renwnd32", "title": ""}
    W.find_windows = lambda: []
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    sent = []
    A.user32 = types.SimpleNamespace(SendMessageTimeoutW=lambda *a: sent.append(a[:4]) or 1)
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.handle({"id": 1, "action": "prompt"})                         # looking: no switch needed
        body = desk.sent[-1][1]
        assert body["ok"] and body["payload"]["kind"] == "prompt" and body["payload"]["img"], body
        assert "Open, Save, Cancel" in body["detail"] and "short_rail_rep_x.csv" in body["detail"]
        b.handle({"id": 2, "action": "prompt_press", "option": "Save"})   # acting off: not even attempted
        assert desk.sent[-1][1]["ok"] is False and sent == []
        b.armed = True
        for name in ("Open", "Run", "", "open "):                       # an export is saved, never opened
            b.handle({"id": 3, "action": "prompt_press", "option": name})
            assert desk.sent[-1][1]["ok"] is False and sent == [], name
        b.handle({"id": 4, "action": "prompt_press", "option": "save"})
        assert desk.sent[-1][1]["ok"] and "Pressed Save" in desk.sent[-1][1]["detail"]
        assert "'Internet Explorer' (Do you want to open or save" in desk.sent[-1][1]["detail"]   # which box
        assert sent == [(77, 0x0111, 2, 82)]       # WM_COMMAND to the box: BN_CLICKED from button id 2
        clicks = []
        keep_click, A.click = A.click, lambda *a, **k: clicks.append(a) or "Clicked CTMS at 50% across, 50% down"
        try:                                       # a box with named buttons: never a point (it could be Run)
            b.handle({"id": 41, "action": "prompt_click", "at": [0.5, 0.5]})
            assert desk.sent[-1][1]["ok"] is False and "prompt-press" in desk.sent[-1][1]["detail"] and not clicks
            boxes[0]["buttons"], was = [], boxes[0]["buttons"]
            b.handle({"id": 42, "action": "prompt_click", "at": [0.5, 0.5]})
            assert desk.sent[-1][1]["ok"] and "the prompt" in desk.sent[-1][1]["detail"] and len(clicks) == 1
            assert clicks[0][0] == 77 and clicks[0][3] == [100, 100, 500, 300]   # on the box's own frame
            boxes[0]["buttons"] = was
        finally:
            A.click = keep_click
        boxes[0]["buttons"] = []                   # a box with nothing to name: says to aim on its picture
        b.handle({"id": 5, "action": "prompt_press", "option": "Save"})
        assert desk.sent[-1][1]["ok"] is False and "prompt-click" in desk.sent[-1][1]["detail"]
        boxes.clear()                              # no box: says what is in front - its program, never a title
        b.handle({"id": 6, "action": "prompt"})
        assert desk.sent[-1][1]["ok"] and "outlook.exe" in desk.sent[-1][1]["detail"]
        b.handle({"id": 7, "action": "prompt_press", "option": "Save"})
        assert desk.sent[-1][1]["ok"] is False and "No box from CTMS's browser" in desk.sent[-1][1]["detail"]
        assert len(sent) == 1
    finally:
        W.prompts, W.prompt_picture, W.front, W.find_windows, A.user32, B.LOG = keep


def test_the_dashboard_lets_the_box_be_seen_freely_and_answered_only_with_the_switch():
    fresh()
    assert call("/api/ctms/command", {"action": "prompt"}, key=AGENT)[0] == 200
    for body in ({"action": "prompt_press", "option": "Save"}, {"action": "prompt_click", "at": [0.5, 0.5]}):
        assert call("/api/ctms/command", body, key=AGENT)[0] == 409      # switched off
    call("/api/ctms/control", {"on": True, "minutes": 15})
    assert call("/api/ctms/command", {"action": "prompt_press", "option": "Save"}, key=AGENT)[0] == 200
    assert S._ctms["queue"][-1]["option"] == "Save"
    assert call("/api/ctms/command", {"action": "prompt_click", "at": [0.5, 0.25]}, key=AGENT)[0] == 200
    assert S._ctms["queue"][-1]["at"] == [0.5, 0.25]


def test_the_home_pc_aims_on_the_boxs_own_picture():
    import types
    seen = {}
    keep = (R.load_state, R.ask, R.trace)
    R.ask = lambda action, **a: (seen.update(action=action, args=a) or ({"ok": True, "detail": "ok"}, None))
    R.trace = lambda *a, **k: None
    try:
        R.load_state = lambda: {"kind": "prompt", "img_w": 400, "img_h": 200}
        assert R.run(types.SimpleNamespace(cmd="prompt-click", at="300,50")) == 0
        assert seen == {"action": "prompt_click", "args": {"at": [0.75, 0.25]}}
        assert R.run(types.SimpleNamespace(cmd="prompt-press", button="Save")) == 0
        assert seen == {"action": "prompt_press", "args": {"option": "Save"}}
        R.load_state = lambda: {"kind": "window", "img_w": 1000, "img_h": 500}   # CTMS's picture, not the box's
        try:
            R.run(types.SimpleNamespace(cmd="prompt-click", at="300,50"))
            assert False, "aimed on the wrong picture"
        except R.Stop as e:
            assert "prompt" in str(e)
    finally:
        R.load_state, R.ask, R.trace = keep


# ---- the export's file, taken from its tab's address (31/10) ------------------------------------
import ctms_export as X                 # noqa: E402
import ctms_import as CI                # noqa: E402

EXP = "https://ctms.example.com/webint/app/prd/export/short_rail_rep_2026-10-31_221330.csv"
OLD = "https://ctms.example.com/webint/app/prd/export/short_rail_rep_2026-10-31_214116.csv"


def test_only_an_https_csv_in_an_export_folder_open_in_a_tab_is_an_export():
    names = [OLD, EXP + " and 3 more pages - Work - Microsoft​ Edge", "Oracle Fusion Middleware Forms Services",
             "http://ctms.example.com/webint/export/x.csv", "https://elsewhere.example.com/files/x.csv",
             "https://ctms.example.com/export/report.pdf", "Inbox - delali - Outlook", EXP]
    assert X.urls(names) == [EXP, OLD]                    # newest first, each once
    assert X.is_export(OLD) and not X.is_export("https://ctms.example.com/export/x.csv.exe")


def test_the_export_goes_into_downloads_only_ever_adding_and_a_sign_in_page_is_never_saved():
    import types
    tmp = tempfile.mkdtemp(prefix="exp-test-")
    keep = X.DOWNLOADS, X._openers, X.fetch
    X.DOWNLOADS = tmp
    try:
        def opener(answer):
            def open_(url, timeout=60):
                if isinstance(answer, Exception):
                    raise answer
                return contextlib.closing(types.SimpleNamespace(read=lambda n=-1: answer, close=lambda: None))
            return types.SimpleNamespace(open=open_)
        X._openers = lambda: iter([("straight from CTMS's server",
                                    opener(urllib.error.HTTPError(EXP, 403, "Forbidden", {}, None))),
                                   ("through the proxy", opener(b"<!DOCTYPE html><html>Sign in</html>"))])
        try:
            X.take([EXP])
            assert False, "a sign-in page was taken as the file"
        except RuntimeError as e:
            assert "HTTP 403" in str(e) and "sign-in page" in str(e), e
        assert os.listdir(tmp) == []
        csv = b"Schedule,Trip Number,Order Reference\r\n261102,T1,A1\r\n261103,T2,A2\r\n"
        X._openers = lambda: iter([("straight from CTMS's server", opener(csv))])
        got = X.take(["Oracle Fusion Middleware Forms Services", OLD, EXP])
        assert got["name"] == "short_rail_rep_2026-10-31_221330.csv" and got["written"] and got["rows"] == 2
        assert got["header"] == "Schedule,Trip Number,Order Reference" and got["how"] == "straight from CTMS's server"
        assert open(os.path.join(tmp, got["name"]), "rb").read() == csv
        assert X.take([EXP])["written"] is False             # the same file again: left as it was
        X._openers = lambda: iter([("straight from CTMS's server", opener(csv + b"261104,T3,A3\r\n"))])
        assert X.take([EXP])["saved_as"] == "short_rail_rep_2026-10-31_221330 (2).csv"   # never replaced
        assert X.take([OLD, EXP], want="short_rail_rep_2026-10-31_214116.csv")["name"].endswith("214116.csv")
        try:
            X.take(["Oracle Fusion Middleware Forms Services"])
            assert False
        except RuntimeError as e:
            assert "press Export" in str(e)
        # the one-click rail export's own file only: one made since its Export press, never an older tab left open
        X._openers = lambda: iter([("straight from CTMS's server", opener(csv))])
        assert X.take([OLD, EXP], since="2026-10-31_221000")["name"].endswith("221330.csv")
        try:
            X.take([OLD], since="2026-10-31_221000")
            assert False, "an older export was taken"
        except RuntimeError as e:
            assert "made since Export was pressed" in str(e), e
    finally:
        X.DOWNLOADS, X._openers, X.fetch = keep
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_bridge_takes_the_export_only_with_the_switch_closes_its_tab_and_brings_ctms_back():
    keep = (W.find_windows, W.picture, W.prompts, B.LOG, TB.names, TB.close, TB.select, X.take, A.press_button)
    showing = [EXP + " and 3 more pages - Work - Microsoft Edge"]     # Edge's title: the selected tab's
    W.find_windows = lambda: [dict(FAKE_WIN, title=showing[-1])]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    tabs = [EXP, OLD, "Oracle Fusion Middleware Forms Services", "Inbox - Outlook", "Haulage Desk"]
    TB.names = lambda want, timeout=10.0: [n for n in tabs if want(n)]
    ie_box = dict(SAVE_BOX, title="Internet Explorer Download - Security Warning",
                  buttons=[{"text": t, "hwnd": 90 + i, "id": i} for i, t in enumerate(("Open", "Save", "Save as",
                                                                                      "Cancel"))])
    W.prompts = lambda: [dict(ie_box), dict(SAVE_BOX, title="Open File - Security Warning")]
    pressed, closed, selected, stuck = [], [], [], [False]
    A.press_button = lambda box, name: pressed.append((box["title"], name)) or f"Pressed {name}"

    def close(want, timeout=10.0):                     # Edge closes them - unless one will not go
        hit = [n for n in tabs if want(n)]
        closed.append(hit)
        if not stuck[0]:
            tabs[:] = [n for n in tabs if n not in hit]
            showing.append("Haulage Desk - Work - Microsoft Edge")     # Edge shows a neighbour, not necessarily CTMS
        return len(hit)
    TB.close = close
    TB.select = lambda target, timeout=10.0: (selected.append(target) or showing.append(
        "Oracle Fusion Middleware Forms Services and 2 more pages - Work - Microsoft Edge") or (True, "Brought up"))
    asked = []
    X.take = lambda names, want="", since="": (asked.append((names, want, since)) or
                                     {"name": "short_rail_rep_2026-10-31_221330.csv", "url": EXP, "saved_as":
                                      "short_rail_rep_2026-10-31_221330.csv", "written": True, "bytes": 2048,
                                      "rows": 12, "header": "Schedule,Trip Number", "how": "straight from CTMS's server",
                                      "data": b"Schedule,Trip Number\r\n261102,T1\r\n"})
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.handle({"id": 1, "action": "export_fetch"})               # acting off: not even tried
        assert desk.sent[-1][1]["ok"] is False and asked == [] and closed == []
        b.armed = True
        b.handle({"id": 2, "action": "export_fetch", "since": "2026-10-31_221000"})
        r = desk.sent[-1][1]
        assert r["ok"] and "Took short_rail_rep_2026-10-31_221330.csv straight from CTMS's server" in r["detail"], r
        assert "12 row(s)" in r["detail"] and r["payload"]["kind"] == "export"
        assert asked[0][0][0].startswith(EXP) and OLD in asked[0][0] and "Inbox - Outlook" not in asked[0][0]
        assert asked[0][2] == "2026-10-31_221000"                   # the rail export's own file, by its time
        assert closed == [[EXP]] and selected == ["ctms"]           # only the tab it took; then CTMS's tab
        assert pressed == [("Internet Explorer Download - Security Warning", "Cancel")]   # not the other box
        assert "Closed 1 export tab; CTMS's tab is the one showing again" in r["detail"], r["detail"]
        assert "builds the rail plan from it as a preview" in r["detail"] and "data" not in r["payload"]
        onward = [body for path, body in desk.sent if path == "/api/ctms/export"]
        assert onward == [{"name": "short_rail_rep_2026-10-31_221330.csv",
                           "data": base64.b64encode(b"Schedule,Trip Number\r\n261102,T1\r\n").decode()}]
        assert b.click_first is True                                # Edge put the keyboard focus where it chose
        stuck[0] = True                                             # a tab that will not close: said so
        b.handle({"id": 3, "action": "export_close"})
        assert desk.sent[-1][1]["ok"] and "The export tab did not close" in desk.sent[-1][1]["detail"]
        stuck[0] = False
        b.handle({"id": 4, "action": "export_close"})               # leftovers: every export tab, nothing else
        assert closed[-1] == [OLD] and "Closed 1 export tab" in desk.sent[-1][1]["detail"]
        assert tabs == ["Oracle Fusion Middleware Forms Services", "Inbox - Outlook", "Haulage Desk"]
        b.handle({"id": 5, "action": "export_close"})
        assert "No export tab to close" in desk.sent[-1][1]["detail"]
    finally:
        (W.find_windows, W.picture, W.prompts, B.LOG, TB.names, TB.close, TB.select, X.take,
         A.press_button) = keep
    fresh()
    for action in ("export_fetch", "export_close"):
        assert call("/api/ctms/command", {"action": action}, key=AGENT)[0] == 409       # switched off
    call("/api/ctms/control", {"on": True, "minutes": 15})
    assert call("/api/ctms/command", {"action": "export_fetch", "option": "x.csv"}, key=AGENT)[0] == 200
    assert call("/api/ctms/command", {"action": "export_close"}, key=AGENT)[0] == 200


def test_a_short_rail_report_from_the_bridge_queues_only_a_rail_plan_preview_for_the_home_pc():
    fresh()
    S._queue.clear()
    good = {"name": "short_rail_rep_2026-10-31_223746.csv", "data": base64.b64encode(b"Schedule\r\n1\r\n").decode()}
    for key in (DASH, AGENT, ""):                                   # the bridge's route alone
        assert call("/api/ctms/export", good, key=key)[0] == 401
    for bad in (dict(good, name="..\\short_rail_rep_1.csv"), dict(good, name="nr_finance_extract_1.csv"),
                dict(good, name="short_rail_rep_1.csv.exe"), dict(good, data=""), dict(good, data=None),
                dict(good, data="x" * (S._RAIL_EXPORT_MAX + 1))):
        assert call("/api/ctms/export", bad, key=BRIDGE)[0] == 400, bad["name"]
    assert S._queue == []
    assert call("/api/ctms/export", dict(good, mode="send", source="last"), key=BRIDGE)[0] == 200
    q = S._queue[-1]
    assert q["action"] == "rail_plan" and q["mode"] == "preview" and "source" not in q      # never a send
    assert q["export"] == {"name": good["name"], "data": good["data"]}
    assert call("/api/next", key=AGENT)[1]["export"]["name"] == good["name"]
    # the card's Build & send with no file: the plan last previewed, and nothing else rides through
    assert call("/api/command", {"action": "rail_plan", "mode": "send", "week": "next", "source": "last",
                                 "export": good})[0] == 200
    q = S._queue[-1]
    assert q["source"] == "last" and "export" not in q
    call("/api/command", {"action": "rail_plan", "mode": "send", "source": "anything"})
    assert S._queue[-1]["source"] is None
    S._queue.clear()


# ---- the map's Upload: an upload CSV into CTMS in one go (31/10) ------------------------------------
UP = "NR_heavy_AH31-10-2026-TEST_31102026230000.csv"


def test_the_upload_switches_acting_on_for_that_import_only_and_never_uploads_a_csv_twice():
    fresh()
    S._to_file.clear()
    S._to_file[UP] = {"data": base64.b64encode(b"ORD,1\r\n").decode(), "size": 7, "at": "31/10 23:00", "sha": ""}
    for key in (AGENT, BRIDGE, ""):                                 # the dashboard's button alone
        assert call("/api/ctms/import", {"name": UP}, key=key)[0] == 401
    assert call("/api/ctms/import", {"name": "NR_heavy_X_31102026230000.csv"})[0] == 404   # not on the dashboard
    assert call("/api/ctms/import", {"name": "..\\" + UP})[0] == 404
    code, r = call("/api/ctms/import", {"name": UP})
    assert code == 200 and S._ctms_armed() and S._ctms["armed_for"] == r["id"]
    q = S._ctms["queue"][-1]
    assert q["action"] == "import_csv" and q["option"] == UP and q["commit"] is True
    assert call("/api/ctms/import", {"name": UP})[0] == 409          # a second click while it runs
    assert call("/api/ctms/result", {"id": r["id"], "action": "import_csv", "ok": True, "detail": "Uploaded",
                                     "payload": {"imported": True}}, key=BRIDGE)[0] == 200
    assert not S._ctms_armed() and S._ctms["armed_for"] is None and UP in S._ctms["imported"]
    code, body = call("/api/ctms/import", {"name": UP})
    assert code == 409 and "already" in body["error"]                # never the same orders twice
    # switched on by him already: left on after the upload - and a stopped one is not counted as taken
    two = "NR_heavy_AH31-10-2026-TWO_31102026231000.csv"
    S._to_file[two] = dict(S._to_file[UP])
    call("/api/ctms/control", {"on": True, "minutes": 30})
    code, r2 = call("/api/ctms/import", {"name": two})
    assert code == 200 and S._ctms["armed_for"] is None
    call("/api/ctms/result", {"id": r2["id"], "action": "import_csv", "ok": False, "detail": "Stopped",
                              "payload": {"imported": False}}, key=BRIDGE)
    assert S._ctms_armed() and two not in S._ctms["imported"]
    S._ctms["state"]["control"] = False                              # the work PC set to look only
    assert call("/api/ctms/import", {"name": two})[0] == 409
    S._to_file.clear()


def test_the_import_answers_ctms_only_once_it_asks_stops_where_it_does_not_and_dry_runs_without_go():
    tmp = tempfile.mkdtemp(prefix="imp-test-")
    keep = (W.find_windows, W.picture, B.LOG, X.DOWNLOADS)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    X.DOWNLOADS = tmp

    class Desk(_Rec):
        def post(self, path, body, timeout=20):
            if path == "/api/ctms/upload":
                return {"name": body["name"], "data": base64.b64encode(b"ORD,1\r\n").decode()}
            return super().post(path, body, timeout)
    try:
        desk = Desk()
        b = B.Bridge(desk, 1, "", allow_control=True)
        ran, fail_at = [], [None]

        def step(action, args):
            what = args.get("name") or (tuple(args["px"]) if "px" in args else args.get("key") or args.get("text"))
            ran.append((action, what))
            if fail_at[0] == (action, what):
                raise RuntimeError("it is not on the screen where it should be.")
            return "ok"
        b.window_step = step
        b._batch_look = lambda times, t0: {"kind": "window", "times": times}

        def go(n, **cmd):
            ran.clear()
            b.handle(dict({"id": n, "action": "import_csv", "option": UP}, **cmd))
            return desk.sent[-1][1]
        r = go(1)                                                    # acting off: not even tried
        assert r["ok"] is False and ran == []
        b.armed = True
        r = go(2)                                                    # no go-ahead: a dry run
        assert r["ok"] and "Dry run" in r["detail"] and r["payload"]["imported"] is False, r
        assert ("click", (405, 438)) not in ran                      # Import never pressed - the card closed,
        assert ran[-2:] == [("find", "imp-close"), ("click", (1030, 139))]     # its Close seen first
        assert ("type", os.path.join(tmp, UP)) in ran and os.path.exists(os.path.join(tmp, UP))
        r = go(3, commit=True)                                       # the real thing, clean
        assert r["ok"] and "no lines failed" in r["detail"] and r["payload"]["imported"] is True, r
        i = ran.index(("click", (405, 438)))
        assert ran[i - 1] == ("find", "imp-button")                  # the button seen before it is pressed
        assert ran[i + 1:i + 5] == [("find", "imp-ask-server"), ("click", (1069, 519)),
                                    ("find", "imp-ask-now"), ("click", (953, 505))]
        assert ran[ran.index(("find", "imp-card")) + 1] == ("click", (575, 226))
        assert ran[-3:] == [("click", (1074, 519)), ("find", "imp-close"), ("click", (1030, 139))]
        fail_at[0] = ("find", "imp-button")                          # Order Filters over the Import button (31/10)
        r = go(31, commit=True)
        assert r["ok"] is False and r["payload"]["imported"] is False and ("click", (405, 438)) not in ran
        assert "Something is over the Import card's Import button" in r["detail"], r["detail"]
        assert "Nothing went into CTMS, and the Import card is closed again" in r["detail"]
        assert ran[-2:] == [("find", "imp-close"), ("click", (1030, 139))]
        fail_at[0] = ("find", "imp-failed-0")                        # a line failed: said, and still closed
        r = go(4, commit=True)
        assert r["ok"] is False and "SOME LINES FAILED" in r["detail"] and r["payload"]["imported"] is True
        assert ran[-1] == ("click", (1030, 139))
        fail_at[0] = ("find", "imp-ask-now")                         # CTMS did not ask: nothing more pressed
        r = go(5, commit=True)
        assert r["ok"] is False and "Stopped while importing" in r["detail"] and r["payload"]["imported"] is True
        assert ran[-1] == ("find", "imp-ask-now")
        fail_at[0] = ("find", "imp-card")                            # the card never came: Import never pressed
        r = go(6, commit=True)
        assert r["ok"] is False and r["payload"]["imported"] is False and ("click", (405, 438)) not in ran
        assert "Nothing went into CTMS" in r["detail"]
        fail_at[0] = None
        for bad in ("..\\" + UP, "report.csv", ""):
            r = go(7, option=bad, commit=True)
            assert r["ok"] is False and ran == [], bad
    finally:
        W.find_windows, W.picture, B.LOG, X.DOWNLOADS = keep
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_picture_that_cant_be_taken_at_the_end_never_loses_what_the_import_did():
    tmp = tempfile.mkdtemp(prefix="imp-test-")
    keep = (W.find_windows, W.picture, B.LOG, X.DOWNLOADS)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    X.DOWNLOADS = tmp

    class Desk(_Rec):
        def post(self, path, body, timeout=20):
            if path == "/api/ctms/upload":
                return {"name": body["name"], "data": base64.b64encode(b"ORD,1\r\n").decode()}
            return super().post(path, body, timeout)
    try:
        desk = Desk()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True
        b.window_step = lambda action, args: "ok"

        def no_picture():
            raise RuntimeError("CTMS is not open in your Edge, or another tab is selected in its window.")
        b.window_look = no_picture
        b.handle({"id": 1, "action": "import_csv", "option": UP, "commit": True})
        r = desk.sent[-1][1]
        assert r["ok"] and "Uploaded" in r["detail"] and r["payload"]["imported"] is True, r
        assert "another tab is selected" in r["payload"]["picture_error"] and "times" in r["payload"]
        def no_ask(action, args):
            if args.get("name") == "imp-ask-now":
                raise RuntimeError("it is not on the screen where it should be.")
            return "ok"
        b.window_step = no_ask
        b.handle({"id": 2, "action": "import_csv", "option": UP, "commit": True})
        r = desk.sent[-1][1]                                     # a stop past Import: still said to have gone in
        assert r["ok"] is False and r["payload"]["imported"] is True and "Stopped while importing" in r["detail"], r
    finally:
        W.find_windows, W.picture, B.LOG, X.DOWNLOADS = keep
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_import_templates_are_ctmss_own_words_and_every_step_has_one_it_needs():
    t = CI.templates()
    for name in ("imp-card", "imp-nrheavy", "imp-button", "imp-close", "imp-ask-server", "imp-ask-now",
                 "imp-done", "imp-failed-0", "imp-invalid-0", "of-title", "of-title-on") + CI.OF_XS:
        tp = t[name]
        assert len(base64.b64decode(tp["rgb"])) == tp["w"] * tp["h"] * 3 and tp["w"] <= 400 and tp["h"] <= 200
    # Order Filters' X in every look is the same size, its middle the X's own
    assert {(t[x]["w"], t[x]["h"]) for x in CI.OF_XS} == {(14, 14)}
    for s in CI.open_and_type("C:\\x.csv", t) + CI.import_and_answer(t) + CI.clean_checks(t) + CI.finish(t):
        assert s["action"] in B.WINDOW_STEPS + B.BATCH_STEPS, s
    # the Close is pressed only straight after its own label is seen
    assert [s.get("name") or s.get("px") for s in CI.close_card(t)] == ["imp-close", [1030, 139]]
    # every Yes comes straight after the find that sees its own question
    steps = CI.import_and_answer(t)
    for q, yes in (("imp-ask-server", [1069, 519]), ("imp-ask-now", [953, 505])):
        i = next(n for n, s in enumerate(steps) if s.get("name") == q)
        assert steps[i + 1] == {"action": "click", "px": yes, "after": 0.5}


def _of_frame(spots, w=1910, h=915):
    """CTMS's window as a picture, with Order Filters' title and X pasted where spots says: {template: (x, y)}."""
    t = CI.templates()
    buf = bytearray(b"\x40\x40\x40\xff" * (w * h))
    for name, (x, y) in spots.items():
        tpl, tw, th = CI._tpl(t, name)
        for r in range(th):
            s = ((y + r) * w + x) * 4
            buf[s:s + tw * 4] = tpl[r * tw * 4:(r + 1) * tw * 4]
    return bytes(buf), w, h


USUAL = {"of-title": (23, 398), "of-x": (393, 397)}            # bottom left, over the Import button (31/10)
FRONT = {"of-title-on": (23, 398), "of-x-on": (393, 397)}      # brought to the front by a first click


def test_order_filters_in_the_way_is_found_by_its_title_and_only_its_own_x_is_ever_pressed():
    t = CI.templates()
    assert CI.order_filters_x(*_of_frame(USUAL), t) == (400, 404)
    assert CI.order_filters_x(*_of_frame(FRONT), t) == (400, 404)
    # moved over a little, in front, the pointer resting on its X - a box round it (29/10)
    assert CI.order_filters_x(*_of_frame({"of-title-on": (63, 398), "of-x-on-hot": (433, 397)}), t) == (440, 404)
    assert CI.order_filters_x(*_of_frame({}), t) is None                                             # not open
    assert CI.order_filters_x(*_of_frame({"of-title": (1440, 398), "of-x": (1810, 397)}), t) is None   # parked right
    assert CI.order_filters_x(*_of_frame({"of-title": (23, 830), "of-x": (393, 829)}), t) is None      # below the card
    assert CI.order_filters_x(*_of_frame({"of-x": (807, 57)}), t) is None      # another window's X: never pressed
    try:                                                                       # its title, no X along its row
        CI.order_filters_x(*_of_frame({"of-title": (23, 398), "of-x": (807, 57)}), t)
        raise AssertionError("Order Filters without its X was let through")
    except RuntimeError as e:
        assert "close it yourself" in str(e)


def test_the_upload_closes_order_filters_first_when_it_is_in_the_way_and_stops_if_it_will_not_close():
    tmp = tempfile.mkdtemp(prefix="imp-test-")
    keep = (W.find_windows, W.picture, B.LOG, X.DOWNLOADS)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    X.DOWNLOADS = tmp

    class Desk(_Rec):
        def post(self, path, body, timeout=20):
            if path == "/api/ctms/upload":
                return {"name": body["name"], "data": base64.b64encode(b"ORD,1\r\n").decode()}
            return super().post(path, body, timeout)
    try:
        desk = Desk()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True
        ran, frames, xs = [], [], []

        def step(action, args):
            what = args.get("name") or (tuple(args["px"]) if "px" in args else args.get("key") or args.get("text"))
            ran.append((action, what))
            if what == "Order Filters' X":
                xs.append((round(args["at"][0] * 1910), round(args["at"][1] * 915)))
                if len(frames) > 1:
                    frames.pop(0)                       # what CTMS shows after that click
            return "ok"
        b.window_step = step
        b._batch_look = lambda times, t0: {"kind": "window", "times": times}
        b._frame = lambda: frames[0]

        def go(n, *shown, **cmd):
            ran.clear()
            xs.clear()
            frames[:] = [_of_frame(s) for s in shown]
            b.handle(dict({"id": n, "action": "import_csv", "option": UP}, **cmd))
            return desk.sent[-1][1]
        x = ("click", "Order Filters' X")
        r = go(1, USUAL, FRONT, {})                 # 31/10: the first click only brought it to the front
        assert r["ok"] and r["detail"].startswith("Order Filters was over the Import card, so it was closed first. "
                                                  "Dry run"), r["detail"]
        assert xs == [(400, 404), (400, 404)] and ran.index(x) < ran.index(("find", "imp-card"))
        r = go(2, USUAL, {})                        # closed by the first click
        assert r["ok"] and xs == [(400, 404)] and "closed first" in r["detail"]
        # a second look sees only its title - its X may have a box round it by now - and presses the same point
        r = go(3, USUAL, {"of-title-on": (23, 398)}, {})
        assert r["ok"] and xs == [(400, 404), (400, 404)]
        r = go(4, {"of-title": (1440, 398), "of-x": (1810, 397)})      # parked out of the way: left alone
        assert r["ok"] and x not in ran and r["detail"].startswith("Dry run"), r["detail"]
        r = go(5, {})                                                  # not open: nothing said about it
        assert r["ok"] and x not in ran and r["detail"].startswith("Dry run")
        r = go(6, USUAL, commit=True)                                  # it will not close: stopped before the card
        assert r["ok"] is False and r["payload"]["imported"] is False and len(xs) == 2, r["detail"]
        assert "did not close - close it yourself, then Upload again" in r["detail"]
        assert ("find", "imp-card") not in ran and ("click", (405, 438)) not in ran
        r = go(7, USUAL, FRONT, {}, commit=True)                       # the real thing, Order Filters out of the way
        assert r["ok"] and r["payload"]["imported"] is True and "closed first. Uploaded" in r["detail"]
        assert ran.index(x) < ran.index(("click", (405, 438)))
    finally:
        W.find_windows, W.picture, B.LOG, X.DOWNLOADS = keep
        shutil.rmtree(tmp, ignore_errors=True)


# ---- the map's orders looked up in CTMS (01/11) ----------------------------------------------------------------
import ctms_orders as CO                # noqa: E402


def _summary_read(rows):
    """An Access Bridge read of Order Summary with these lines, as CTMS gives it (29-30/10): each column down the
    screen, the left block a few pixels lower than the right - here bottom row first, to show order is by place."""
    els = [{"r": "internal frame", "nm": "Planning", "lv": 1}, {"r": "internal frame", "nm": "Order Summary", "lv": 1}]
    for item, key in CO.COLUMNS.items():
        y0 = 326 if item in ("SCHED_NAME", "EXTERNAL_REF", "STATUS", "DELIVERY_TYPE_ID") else 320
        for i in reversed(range(15)):
            els.append({"r": "text", "nm": "Enter value for : " + item, "lv": 2,
                        "v": rows[i][key] if i < len(rows) else "", "at": [0, y0 + 23 * i, 80, 23]})
    els += [{"r": "push button", "nm": "Close", "lv": 2}, {"r": "internal frame", "nm": "Order Search", "lv": 1}]
    return {"elements": els}


def _line(ref, status, deliver, sched="261110"):
    return {"schedule": sched, "ref": ref, "status": status, "type": "STANDARD", "ready_at": deliver,
            "deliver_by": deliver}


def test_order_summary_gives_each_line_whole_and_only_the_orders_own_count():
    rows = [_line("9100020-2-1", "UNSCHEDULED", "10/11/26 16:01"), _line("9100020-1-1", "SCHEDULED", "05/11/26 16:01"),
            _line("9100021-1-1", "UNSCHEDULED", "05/11/26 16:01")]
    got = CO.lines(_summary_read(rows))
    assert [(r["ref"], r["status"], CO.day(r["deliver_by"])) for r in got] == [
        ("9100020-2-1", "UNSCHEDULED", "10/11/2026"), ("9100020-1-1", "SCHEDULED", "05/11/2026"),
        ("9100021-1-1", "UNSCHEDULED", "05/11/2026")]
    assert CO.lines({"elements": [{"r": "internal frame", "nm": "Planning", "lv": 1}]}) is None   # not up
    assert CO.search_ref("9100020-1-1") == "9100020%" and CO.search_ref("AH01/11/2026/AB-CD") == "AH01/11/2026/AB-CD%"
    assert CO.belongs("9100020-2-1", "9100020") and not CO.belongs("9100021-1-1", "9100020")
    mine = [r for r in got if CO.belongs(r["ref"], "9100020")]
    assert CO.line_for(mine, "10/11/2026")["ref"] == "9100020-2-1"     # its own day's open line
    assert CO.line_for(mine, "05/11/2026") is None                     # that day's line is booked: nothing to open
    assert CO.line_for(mine, "07/11/2026")["ref"] == "9100020-2-1"     # moved: the one open day left
    two_days = mine + [_line("9100020-3-1", "UNSCHEDULED", "12/11/26 16:01")]
    assert CO.line_for(two_days, "07/11/2026") is None                 # moved, but to which? no telling
    # the Veh Type box: words in it, or none
    w, h = 1910, 915
    blank = bytearray(b"\xff\xff\xff\xff" * (w * h))
    assert CO.veh_filled(bytes(blank), w, h) is False
    for x in range(1080, 1130):
        for y in (308, 309):
            i = (y * w + x) * 4
            blank[i:i + 3] = b"\x10\x10\x10"
    assert CO.veh_filled(bytes(blank), w, h) is True and CO.veh_filled(bytes(blank), w, h, (0, 40)) is False
    # every open line of the day has its card opened - a delivery split over lines weighs them all
    split = [_line("9100022-1-1", "UNSCHEDULED", "10/11/26 16:01"), _line("9100022-2-1", "UNSCHEDULED", "10/11/26 16:01"),
             _line("9100022-3-1", "SCHEDULED", "10/11/26 16:01")]
    assert [r["ref"] for r in CO.open_lines(split, "10/11/2026")] == ["9100022-1-1", "9100022-2-1"]
    assert CO.open_lines(split, "10/11/2026", 1) == [CO.line_for(split, "10/11/2026")]


def _card_read(weights, carried=(), well=()):
    """An Access Bridge read with an order's card up: its lines' planned Weight cells, then the carried ones after
    Delivered - and Planning's order well behind it, with a Weight column of its own."""
    els = [{"r": "internal frame", "nm": "Order details for 11300001", "lv": 1}]
    els += [{"r": "text", "nm": "Weight", "v": v, "lv": 4} for v in weights]
    els += [{"r": "text", "nm": "Delivered", "v": "", "lv": 4}]
    els += [{"r": "text", "nm": "Weight", "v": v, "lv": 4} for v in carried]
    els += [{"r": "internal frame", "nm": "Planning", "lv": 1}]
    els += [{"r": "text", "nm": "Weight", "v": v, "lv": 3} for v in well]
    return {"elements": els}


def test_an_orders_weight_is_its_cards_planned_lines_only():
    assert CO.card_weight(_card_read(["   5,100.00", "", ""], carried=["   5,100.00"], well=["420000"])) == 5100.0
    assert CO.card_weight(_card_read(["   1,232.00", "      750.50", ""])) == 1982.5
    assert CO.card_weight(_card_read(["", ""])) is None                          # no weight on the card
    assert CO.card_weight({"elements": [{"r": "internal frame", "nm": "Planning", "lv": 1},
                                        {"r": "text", "nm": "Weight", "v": "2000", "lv": 3}]}) is None   # no card up


def test_the_ctms_look_up_reads_each_order_opens_only_an_open_line_and_saves_nothing():
    keep = (W.find_windows, W.picture, W.idle_seconds, J.read_fields, B.LOG)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    filled = bytearray(b"\xff\xff\xff\xff" * (1910 * 915))
    for x in range(1080, 1130):
        i = (309 * 1910 + x) * 4
        filled[i:i + 3] = b"\x10\x10\x10"
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True
        ran, reads, seen = [], [], {}

        def step(action, args):
            what = args.get("name") or (tuple(args["px"]) if "px" in args else args.get("key") or args.get("text"))
            ran.append((action, what, bool(args.get("double"))))
            return "ok"
        b.window_step = step
        b._batch_look = lambda times, t0: {"kind": "window", "times": times}
        b._seen = lambda t, name, box: seen.get(name, False)
        b._frame = lambda: (bytes(filled), 1910, 915)

        def read(win, skip=()):
            r = reads.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        J.read_fields = read
        orders = [{"key": "9100020|10/11/2026", "ref": "9100020", "date": "10/11/2026", "veh": True},
                  {"key": "AH01/11/2026/AB-CD|03/11/2026", "ref": "AH01/11/2026/AB-CD", "date": "03/11/2026",
                   "veh": False}]
        both = [_line("9100020-2-1", "UNSCHEDULED", "10/11/26 16:01"), _line("9100020-1-1", "SCHEDULED", "05/11/26 16:01")]

        def go(n, **cmd):
            ran.clear()
            b.handle(dict({"id": n, "action": "ctms_check", "orders": orders}, **cmd))
            return desk.sent[-1][1]
        far = {"elements": [{"r": "text", "nm": "up to", "v": "30/12/68", "lv": 2, "at": [216, 251, 67, 27]}]}
        reads[:] = [far, _summary_read(both), _summary_read(both[:1]), _card_read(["   1,232.00", ""]),
                    _summary_read([_line("AH01/11/2026/AB-CD", "SCHEDULED", "03/11/26 12:00", "261103")])]
        r = go(1)
        assert r["ok"] and "Looked up 2 of 2" in r["detail"] and "Order Summary closed again" in r["detail"], r
        assert ("find", "os-search", False) in ran and ran.index(("find", "os-search", False)) < \
            ran.index(("find", "os-card", False))                       # the card was not up: the menu first
        typed = [w for a, w, _ in ran if a == "type"]
        assert typed == ["9100020%", "9100020-2-1", "AH01/11/2026/AB-CD%"], typed   # searches only
        assert [x for x in ran if x[2]] == [("click", (267, 238), True)]           # one line opened: the open one
        i = ran.index(("find", "od-vehtype", False))
        assert ran[i + 1] == ("click", (424, 733), False)                # its Close - and never a Save (337,733)
        assert not any(w == (337, 733) for _, w, _ in ran) and ran[-1] == ("find", "os-close", False)
        path, sent = [(p, s) for p, s in desk.sent if p == "/api/ctms/orders"][-1]
        got = sent["orders"]
        assert sent["checked"] == 2 and sent["of"] == 2 and not sent["stopped"]
        assert [x["ref"] for x in got["9100020|10/11/2026"]["lines"]] == ["9100020-2-1", "9100020-1-1"]
        assert got["9100020|10/11/2026"]["veh"] == {"9100020-2-1": True}
        assert got["9100020|10/11/2026"]["weight"] == {"9100020-2-1": 1232.0} and "weight read on 1" in r["detail"]
        assert "veh" not in got["AH01/11/2026/AB-CD|03/11/2026"]
        # the card already up: straight to it; a read that fails stops the run - what was found still goes home
        seen["os-card"] = True
        reads[:] = [far, _summary_read(both[1:]), RuntimeError("CTMS's Java did not answer")]
        r = go(2)
        assert r["ok"] is False and "Stopped reading AH01/11/2026/AB-CD's lines" in r["detail"], r["detail"]
        assert ("find", "os-search", False) not in ran
        sent = [s for p, s in desk.sent if p == "/api/ctms/orders"][-1]
        assert list(sent["orders"]) == ["9100020|10/11/2026"] and sent["stopped"]
        # a set-time look-up waits for a quiet work PC
        W.idle_seconds = lambda: 30.0
        r = go(3, idle=3)
        assert r["ok"] is False and "waits for 3 quiet minutes" in r["detail"] and ran == []
    finally:
        W.find_windows, W.picture, W.idle_seconds, J.read_fields, B.LOG = keep


def test_only_a_search_ctms_gave_no_answer_to_reads_as_not_found():
    keep = (W.find_windows, W.picture, W.idle_seconds, J.read_fields, B.LOG)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    W.idle_seconds = lambda: None
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True
        fail = {}

        def step(action, args):
            what = tuple(args["px"]) if "px" in args else args.get("name") or args.get("key") or args.get("text")
            if what in fail:
                raise fail[what]
            return "ok"
        b.window_step = step
        b._batch_look = lambda times, t0: {"kind": "window", "times": times}
        b._seen = lambda t, name, box: name == "os-card"
        reads = []
        J.read_fields = lambda win, skip=(): reads.pop(0)
        orders = [{"key": "9100030|10/11/2026", "ref": "9100030", "date": "10/11/2026"},
                  {"key": "9100031|10/11/2026", "ref": "9100031", "date": "10/11/2026"}]

        def go(n):
            b.handle({"id": n, "action": "ctms_check", "orders": orders})
            return desk.sent[-1][1], [s for p, s in desk.sent if p == "/api/ctms/orders"][-1]
        # the Refresh's wait runs out with nothing changed in the list: CTMS found nothing for it
        fail[(742, 226)] = B.Unchanged("CTMS did not answer within 15s - nothing changed where it should have")
        reads[:] = [{"elements": []}, _summary_read([]), _summary_read([])]
        r, sent = go(1)
        assert r["ok"] and "2 not found" in r["detail"] and sent["checked"] == 2 and not sent["stopped"], r
        # anything else that stops the search is not "not found": the look-up says it couldn't be done
        for why in (D.Refused("CTMS could not be brought to the front, so no keys were sent"),
                    RuntimeError("CTMS did not answer within 15s - the screen never settled")):
            fail.clear()
            fail[(728, 122) if isinstance(why, D.Refused) else (742, 226)] = why
            reads[:] = [{"elements": []}]
            r, sent = go(2)
            assert r["ok"] is False and "searching for 9100030: the search couldn't be done" in r["detail"], r
            assert str(why) in r["detail"] and sent["orders"] == {} and sent["stopped"]
    finally:
        W.find_windows, W.picture, W.idle_seconds, J.read_fields, B.LOG = keep


def test_book_says_what_it_left_changed_in_ctms_and_a_missing_picture_loses_no_trip():
    keep = (W.find_windows, W.picture, B.LOG, B.ctms_book.Booking, B.book_record.keep)
    W.find_windows = lambda: [dict(FAKE_WIN)]
    W.picture = lambda win: (_bgra([[0xFF2A4A7F] * 4] * 3), 4, 3, "from the window")
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    B.book_record.keep = lambda *a, **k: None
    trip = {"manifest": "M100001", "status": "ACCEPTED", "revenue": 500, "cost": 400}
    goes = {}

    class Job:
        def __init__(self, run, read, seen, t, dry=False):
            self.trips, self.stages, self.reads, self.veh_kept, self.said = [], [], [], "", []

        def book(self, orders, date, carrier, trailer, haulage, vehicles, qty=None):
            self.said += ["9100001-1-1 split into 2", "the well's filters cleared to find it: Business Type 'Bulk'"]
            if goes.get("stop"):
                raise RuntimeError("The carrier screen didn't open.")
            self.trips.append(dict(trip))

        def back_out(self):
            pass

        def tidy(self):
            self.said.append("PUT BACK BY HAND on the well's filters: Business Type 'Bulk'")
    B.ctms_book.Booking = Job
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        b.armed = True

        def no_picture():
            raise RuntimeError("CTMS is not open in your Edge, or another tab is selected in its window.")
        b.window_look = no_picture
        cmd = {"action": "ctms_book", "orders": ["9100001"], "date": "10/11/2026", "carrier": "ACME_DH"}
        goes["stop"] = True                       # stopped: the split line and the filters left are still said
        b.handle(dict(cmd, id=1))
        r = desk.sent[-1][1]
        assert r["ok"] is False and "Stopped after" in r["detail"], r
        assert "On the lines first: 9100001-1-1 split into 2." in r["detail"], r["detail"]
        assert "PUT BACK BY HAND on the well's filters: Business Type 'Bulk'." in r["detail"], r["detail"]
        assert r["payload"]["notes"][0] == "9100001-1-1 split into 2" and "picture_error" in r["payload"]
        goes["stop"] = False                      # booked, the picture after it not taken: the trip still comes back
        b.handle(dict(cmd, id=2))
        r = desk.sent[-1][1]
        assert r["ok"] and "M100001 ACCEPTED" in r["detail"] and r["payload"]["trips"] == [trip], r
        assert r["payload"]["kind"] == "ctms_book" and "another tab is selected" in r["payload"]["picture_error"]
    finally:
        W.find_windows, W.picture, B.LOG, B.ctms_book.Booking, B.book_record.keep = keep


def test_check_ctms_now_looks_up_the_maps_orders_with_acting_on_for_that_only():
    fresh()
    day = lambda n: (datetime.now() + timedelta(days=n)).strftime("%d/%m/%Y")     # noqa: E731
    keep = (S._tracker, S._panel)
    S._tracker = {"records": [
        {"id": "9100030|x", "orders": ["9100030"], "delivery_date": day(5), "kind": "delivery"},     # chased, soon
        {"id": "9100031|x", "orders": ["9100031", "9100032"], "delivery_date": day(4), "kind": "delivery",
         "reply_at": "2026-11-01 09:00", "missing": []},                                            # ready
        {"id": "9100033|x", "orders": ["9100033"], "delivery_date": day(30), "kind": "delivery"},    # far off
        {"id": "c|x", "orders": ["9100034"], "delivery_date": "", "kind": "collection"}]}
    S._panel = {"adhocs": [{"id": "adhoc|AH01/11/2026/AB-CD|1", "orders": ["AH01/11/2026/AB-CD"],
                            "delivery_date": day(2)}], "pins": [],
                # the CTMS to-do's reply updates: looked up too (a filled Veh Type ticks them off), once each
                "ctms_todo": [{"kind": "update", "orders": ["9100035"]}, {"kind": "update", "orders": ["9100030"]},
                              {"kind": "note", "orders": ["9100036"]}]}
    try:
        for key in (AGENT, BRIDGE, ""):
            assert call("/api/ctms/check", {}, key=key)[0] == 401
        code, r = call("/api/ctms/check", {})
        assert code == 200 and r["orders"] == 6 and S._ctms_armed() and S._ctms["armed_for"] == r["id"]
        q = S._ctms["queue"][-1]
        # due within a fortnight, chased or ready alike: cards opened for the Veh Type and the weight
        assert q["action"] == "ctms_check" and [(o["ref"], o["veh"]) for o in q["orders"]] == [
            ("9100030", True), ("9100031", True), ("9100032", True), ("9100033", False), ("AH01/11/2026/AB-CD", False),
            ("9100035", True)]
        assert q["orders"][0]["key"] == "9100030|" + day(5)
        assert call("/api/ctms/check", {})[0] == 409                     # one look-up at a time
        found = {"9100030|" + day(5): {"lines": []}}
        assert call("/api/ctms/orders", {"orders": found, "checked": 1, "of": 5}, key=DASH)[0] == 401
        assert call("/api/ctms/orders", {"orders": found, "checked": 1, "of": 5, "at": "x"}, key=BRIDGE)[0] == 200
        job = S._queue[-1]
        assert job["action"] == "ctms_orders" and job["data"]["orders"] == found
        assert S._ctms["looked_up"]["checked"] == 1
        call("/api/ctms/result", {"id": r["id"], "action": "ctms_check", "ok": True, "detail": "Looked up"}, key=BRIDGE)
        assert not S._ctms_armed() and S._ctms["armed_for"] is None
        # what a command may carry: a safe ref, a real date or none
        args = S._ctms_args("ctms_check", {"orders": [{"ref": "bad ref!"}, {"ref": "9100020", "date": "1/1/26",
                                                                              "veh": 1}], "idle": 3})
        assert args["orders"] == [{"key": "", "ref": "9100020", "date": "", "veh": True}] and args["idle"] == 3
        S._tracker, S._panel = {"records": []}, {}
        assert call("/api/ctms/check", {})[0] == 404                     # nothing on the map
    finally:
        S._tracker, S._panel = keep
        S._queue.clear()


def test_the_panels_book_switches_acting_on_for_itself_and_puts_it_back():
    fresh()
    job = {"record": "9100001|06/11/2026", "orders": ["9100001", "bad ref!"], "date": "06/11/2026", "carrier": "ACME_DH",
           "haulier": "Acme Haulage", "trailer": "NR_ARTIC_FL", "haulage": 450, "vehicles": 2}
    try:
        assert call("/api/ctms/book", job, key=AGENT)[0] == 401
        assert call("/api/ctms/book", dict(job, carrier="no carrier!"))[0] == 400
        assert call("/api/ctms/book", dict(job, date="6/11/26"))[0] == 400
        assert call("/api/ctms/book", dict(job, orders=["bad ref!"]))[0] == 400
        code, r = call("/api/ctms/book", job)
        assert code == 200 and S._ctms_armed()
        sent = S._queue[-1]
        assert sent["action"] == "ctms_book" and sent["orders"] == ["9100001"] and sent["carrier"] == "ACME_DH"
        assert sent["haulage"] == 450 and sent["vehicles"] == 2 and sent["trailer"] == "NR_ARTIC_FL" and sent["dry"] is False
        assert sent["record"] == job["record"] and sent["haulier"] == "Acme Haulage" and sent["run"] == r["run"]
        assert call("/api/ctms/book", job)[0] == 409                      # one at a time
        # what goes to the work PC goes through the same gate
        args = S._ctms_args("ctms_book", dict(job, vehicles=99, haulage=-1))
        assert "vehicles" not in args and "haulage" not in args and args["orders"] == ["9100001"]
        # it ends: what it made is kept for the panel, and the switch goes back off
        done = {"run": r["run"], "ok": True, "said": "MAN-01000001 ACCEPTED", "seconds": 41,
                "trips": [{"manifest": "MAN-01000001", "status": "ACCEPTED", "revenue": "600", "cost": "450"}]}
        assert call("/api/ctms/book/ran", done, key=DASH)[0] == 401
        assert call("/api/ctms/book/ran", done, key=AGENT)[0] == 200
        assert not S._ctms_armed()
        run = S._ctms["book_run"]
        assert run["state"] == "done" and run["ok"] is True and run["seconds"] == 41 and run["trips"][0]["manifest"] == "MAN-01000001"
        # a to-do run going: book when it's done
        S._ctms["todo_run"] = {"state": "running", "until": time.time() + 60}
        assert call("/api/ctms/book", job)[0] == 409
    finally:
        S._ctms["control_until"] = 0.0
        S._ctms["book_run"] = None
        S._ctms["todo_run"] = None
        S._queue.clear()


def test_a_job_that_can_wait_asks_again_when_the_work_pc_was_busy():
    keep = R.ask
    answers = [({"ok": False, "detail": "Not run - the work PC did not pick this up within 60s, so nothing was done."}, None),
               ({"ok": False, "detail": "Not run - the work PC did not pick this up within 60s, so nothing was done."}, None),
               ({"ok": True, "detail": "done"}, {"done": True})]
    asked = []

    def ask(action, wait_total=90, **a):
        asked.append((action, a))
        return answers.pop(0)
    R.ask = ask
    try:
        result, payload = R.ask_waiting("ctms_item", item={"lines": ["x"]})
        assert result["ok"] and payload == {"done": True} and len(asked) == 3 and asked[0][1] == {"item": {"lines": ["x"]}}
        # any other answer is the answer, and patience runs out
        answers[:] = [({"ok": False, "detail": "Refused"}, None)]
        assert R.ask_waiting("ctms_item")[0]["detail"] == "Refused"
        answers[:] = [({"ok": False, "detail": "did not pick this up"}, None)]
        assert "did not pick" in R.ask_waiting("ctms_item", patience=-1)[0]["detail"]
    finally:
        R.ask = keep


def test_a_long_command_is_busy_not_offline():
    fresh()
    S._ctms["seen"] = time.time() - 200
    try:
        assert S._ctms_online() is False
        S._ctms["running"] = {"id": 1, "action": "ctms_check", "since": time.time() - 200}
        assert S._ctms_online() is True
        S._ctms["running"]["since"] = time.time() - S._CTMS_BUSY - 5      # gone quiet for longer than anything takes
        assert S._ctms_online() is False
    finally:
        S._ctms["running"] = None


def test_an_item_of_the_to_do_goes_to_the_work_pc_through_the_same_gate():
    item = {"kind": "update", "lines": ["9100001-1-1", "bad ref!"], "set": {
        "deliver": "05/11/26 08:00-12:00", "comments": "x" * 900, "veh": "rigid", "storage": 2, "anyway": True, "other": "dropped",
        "services": {"HIAB": True, "PTS": False}}}
    args = S._ctms_args("ctms_item", {"item": item, "first": 1, "last": 0})
    got = args["item"]
    assert got["kind"] == "update" and got["lines"] == ["9100001-1-1"] and args["first"] is True and args["last"] is False
    assert got["set"]["services"] == {"HIAB": True, "PTS": False} and got["set"]["storage"] == 2 and got["set"]["anyway"] is True
    assert len(got["set"]["comments"]) == 400 and "other" not in got["set"]
    note = S._ctms_args("ctms_item", {"item": {"kind": "note", "lines": ["9100001-1-1"], "set": {"note": " - Emailed DO 02/11"}}})
    assert note["item"] == {"kind": "note", "lines": ["9100001-1-1"], "set": {"note": " - Emailed DO 02/11"}}
    assert "ctms_item" in S.CTMS_DRIVE


def test_a_runs_progress_reaches_the_page_while_it_goes():
    fresh()
    try:
        code, r = call("/api/ctms/todo/run", {"ids": ["a1", "b2"]})
        assert code == 200
        step = {"run": r["run"], "on": "9100001-1-1", "results": [{"id": "a1", "ok": True, "said": "done"},
                                                                 {"id": "b2", "ok": False, "held": True, "said": "CTMS has it"}]}
        assert call("/api/ctms/todo/progress", step, key=DASH)[0] == 401
        assert call("/api/ctms/todo/progress", step, key=AGENT)[0] == 200
        run = S._ctms["todo_run"]
        assert run["state"] == "running" and run["on"] == "9100001-1-1" and [x["held"] for x in run["results"]] == [False, True]
        assert call("/api/ctms/todo/progress", dict(step, run=999), key=AGENT)[0] == 200
        assert S._ctms["todo_run"]["on"] == "9100001-1-1"              # another run's says nothing here
        assert call("/api/ctms/todo/ran", {"run": r["run"], "ok": True, "said": "2 of 2", "seconds": 40.5,
                                           "results": step["results"]}, key=AGENT)[0] == 200
        run = S._ctms["todo_run"]
        assert run["state"] == "done" and run["on"] == "" and run["seconds"] == 40.5 and run["results"][1]["held"] is True
    finally:
        S._ctms["control_until"] = 0.0
        S._ctms["todo_run"] = None
        S._queue.clear()


def test_the_ctms_to_do_run_switches_acting_on_for_itself_and_puts_it_back():
    fresh()
    try:
        # a pick from a held item's drop-down: checked, then handed to the home PC
        for body in ({"id": "t1", "field": "offloading"}, {"id": "bad id!", "field": "veh", "value": "rigid"},
                     {"id": "t1", "field": "price", "value": "500"}):
            assert call("/api/ctms/todo/answer", body)[0] == 400
        assert call("/api/ctms/todo/answer", {"id": "t1", "field": "veh", "value": "rigid"}, key=AGENT)[0] == 401
        assert call("/api/ctms/todo/answer", {"id": "t1", "field": "veh", "value": "rigid"})[0] == 200
        assert S._queue[-1]["action"] == "ctms_todo_answer" and S._queue[-1]["item"] == "t1"
        # Run: switched on for the run, the home PC told which items; one run at a time
        assert call("/api/ctms/todo/run", {"ids": []})[0] == 400
        assert call("/api/ctms/todo/run", {"ids": ["a1"]}, key=AGENT)[0] == 401
        code, r = call("/api/ctms/todo/run", {"ids": ["a1", "b2", "not ok!"]})
        assert code == 200 and S._ctms_armed()
        job = S._queue[-1]
        assert job["action"] == "ctms_todo_run" and job["ids"] == ["a1", "b2"] and job["run"] == r["run"]
        assert call("/api/ctms/todo/run", {"ids": ["c3"]})[0] == 409
        # it ends: what it did is kept for the page, and the switch goes back off
        assert call("/api/ctms/todo/ran", {"run": r["run"], "ok": True, "said": "2 of 2 done"}, key=DASH)[0] == 401
        assert call("/api/ctms/todo/ran", {"run": r["run"], "ok": True, "said": "2 of 2 done",
                                           "results": [{"id": "a1", "ok": True, "said": "added"}]}, key=AGENT)[0] == 200
        assert not S._ctms_armed()
        run = S._ctms["todo_run"]
        assert run["state"] == "done" and run["said"] == "2 of 2 done" and run["results"][0]["id"] == "a1"
        # switched on by him for longer: the run leaves it on
        S._ctms["control_until"] = time.time() + 3 * 3600
        code, r = call("/api/ctms/todo/run", {"ids": ["c3"]})
        call("/api/ctms/todo/ran", {"run": r["run"], "ok": True, "said": "1 of 1 done"}, key=AGENT)
        assert S._ctms_armed() and S._ctms["control_until"] > time.time() + 2 * 3600
    finally:
        S._ctms["control_until"] = 0.0
        S._ctms["todo_run"] = None
        S._queue.clear()


def test_the_rail_plans_ctms_export_switches_acting_on_for_itself_and_never_overlaps_a_to_do_run():
    fresh()
    try:
        assert call("/api/ctms/rail", {"week": "next"}, key=AGENT)[0] == 401
        assert call("/api/ctms/rail", {"week": "last"})[0] == 400
        code, r = call("/api/ctms/rail", {"week": "next"})
        assert code == 200 and S._ctms_armed()
        job = S._queue[-1]
        assert job == dict(job, action="ctms_rail", week="next", run=r["run"])
        assert call("/api/ctms/rail", {"week": "current"})[0] == 409                   # one at a time
        assert call("/api/ctms/todo/run", {"ids": ["a1"]})[0] == 409                   # ... nor beside a to-do run
        assert call("/api/ctms/status")[1]["rail_run"]["state"] == "running"
        assert call("/api/ctms/rail/ran", {"run": r["run"], "ok": True, "said": "Exported"}, key=DASH)[0] == 401
        assert call("/api/ctms/rail/ran", {"run": r["run"], "ok": True, "said": "Exported",
                                           "file": "short_rail_rep_2026-11-01_200000.csv"}, key=AGENT)[0] == 200
        assert not S._ctms_armed()
        run = call("/api/ctms/status")[1]["rail_run"]
        assert run["state"] == "done" and run["ok"] and run["said"] == "Exported" and "until" not in run
        # a to-do run going: no export beside it
        code, t = call("/api/ctms/todo/run", {"ids": ["a1"]})
        assert code == 200 and call("/api/ctms/rail", {"week": "next"})[0] == 409
        call("/api/ctms/todo/ran", {"run": t["run"], "ok": True, "said": "1 of 1 done"}, key=AGENT)
        # the export's file: only one made since the press, and since= rides on export_fetch alone
        assert S._ctms_args("export_fetch", {"since": "2026-11-01_195000"})["since"] == "2026-11-01_195000"
        assert "since" not in S._ctms_args("export_fetch", {"since": "yesterday"})
        assert "since" not in S._ctms_args("click", {"since": "2026-11-01_195000"})
    finally:
        S._ctms["control_until"] = 0.0
        S._ctms["todo_run"] = S._ctms["rail_run"] = None
        S._queue.clear()


# ---- a message to DHL NOC in the work PC's Teams (01/11) ---------------------------------------------
import ctms_teams as TM                 # noqa: E402


def test_teams_opens_only_that_persons_chat_and_checks_it_by_its_title():
    assert TM.chat_link("sam.example@example.com") == "msteams:/l/chat/0/0?users=sam.example@example.com"
    words = TM.name_words("sam.example@example.com", "Sam")
    assert words == ["sam", "example"]
    assert TM.is_chat_with("Chat | Sam Example | Microsoft Teams", words)
    assert TM.is_chat_with("Chat | Example, Sam (Example Co) | Microsoft Teams", words)
    for wrong in ("Chat | Sam Other | Microsoft Teams", "Chat | Jo Example | Microsoft Teams", "Sam Example",
                  "Activity | Microsoft Teams", "Chat | Sam Example | Outlook"):
        assert not TM.is_chat_with(wrong, words), wrong
    assert TM.same_text("Hi Sam, would you be able to cover the job below?\n\nOrder: 9100001",
                        "Hi Sam, would you be able\r\nto cover the job below?\nOrder: 9100001")
    assert not TM.same_text("", "Hi Sam") and not TM.same_text("Hi Jo", "Hi Sam")
    assert TM.is_box("Type a message") and TM.is_box("Type a new message") and not TM.is_box("Search")
    assert TM.is_send("Send") and TM.is_send("Send (Ctrl+Enter)")
    assert not TM.is_send("Send feedback") and not TM.is_send("Sender details") and not TM.is_send("")
    assert TM.empty("", "Type a message") and TM.empty("Type a message\n", "Type a message")    # its own prompt
    assert TM.empty("Type a new message", "") and not TM.empty("Hi Sam", "Type a message")
    # the quiet send: the box must hold this message and nothing else; copies of this same message left by an
    # earlier try are ours to clear, anything else is his draft and is left alone
    assert TM.holds_only("Hi Sam,\r\nOrder: 9100001", "Hi Sam,\nOrder: 9100001")
    assert TM.only_copies("Hi Sam,\nSecond line.Hi Sam,\nSecond line.", "Hi Sam,\nSecond line.")
    assert TM.only_copies("Hi Sam, Second line.", "Hi Sam,\nSecond line.")
    assert not TM.only_copies("Hi Sam,\nSecond line. And my own note", "Hi Sam,\nSecond line.")
    assert not TM.only_copies("", "Hi Sam") and not TM.only_copies("Hi", "Hi Sam")
    assert not TM.holds_only("an older draft Hi Sam,\nOrder: 9100001", "Hi Sam,\nOrder: 9100001")
    assert not TM.holds_only("Hi Sam,", "Hi Sam,\nOrder: 9100001") and not TM.holds_only("", "")
    # the invisible marks an editor keeps in its text (zero-width space, word joiner) are not words
    assert TM.holds_only("⁠⁠Hi Sam,\r\nOrder: 9100001​", "Hi Sam,\nOrder: 9100001")
    assert TM.only_copies("Hi Sam,\nSecond line.⁠Hi Sam,\nSecond line.﻿", "Hi Sam,\nSecond line.")
    assert TM.empty("​", "Type a message") and not TM.only_copies("​", "Hi Sam")
    assert TM._show("x" * 60).endswith(", 60 characters") and "'\\u2060'" in TM._show("⁠")


class _FakeClipboard:
    """Windows' clipboard for the paste test: formats -> bytes, each handle a real block of memory."""

    def __init__(self, formats):
        self.names, self.data, self.blocks, self.reads = {}, {}, {}, 0
        for f, b in formats.items():
            self.data[f if isinstance(f, int) else self.RegisterClipboardFormatW(f)] = b

    def RegisterClipboardFormatW(self, name):
        return self.names.setdefault(name, 0xC000 + len(self.names))

    def IsClipboardFormatAvailable(self, f):
        return f in self.data

    def _block(self, b):
        self.blocks[len(self.blocks) + 1] = ctypes.create_string_buffer(b, len(b))
        return len(self.blocks)

    def GetClipboardData(self, f):
        self.reads += 1
        return self._block(self.data[f]) if f in self.data else None

    def GlobalAlloc(self, flags, size):
        return self._block(b"\0" * size)

    def GlobalLock(self, h):
        return ctypes.addressof(self.blocks[h])

    def GlobalSize(self, h):
        return len(self.blocks[h])

    def SetClipboardData(self, f, h):
        self.data[f] = bytes(self.blocks[h])
        return h

    def EmptyClipboard(self):
        self.data = {}
        return True

    def GlobalUnlock(self, h):
        return True

    def GlobalFree(self, h):
        return None

    def CloseClipboard(self):
        return True


def test_teams_paste_borrows_the_clipboard_and_puts_it_back_as_it_was():
    import ctms_act
    keep = (TM._clip_api, ctms_act._open_clipboard)
    ours = [(13, "Hi Sam\0".encode("utf-16-le"))]
    try:
        ctms_act._open_clipboard = lambda: True
        # cells copied in Excel: the text and its look come back - not a picture of the cells, rendered for nothing
        cells = "Order\t20t\r\n\0".encode("utf-16-le")
        clip = _FakeClipboard({13: cells, "HTML Format": b"<table>cells</table>", 8: b"BMpicture"})
        TM._clip_api = lambda: (clip, clip)
        saved = TM._clip_save()
        assert sorted(f for f, _ in saved) == sorted([13, clip.names["HTML Format"]])
        assert TM._clip_put(ours) and clip.data == {13: ours[0][1]}
        assert TM._clip_put(saved) and clip.data == {13: cells, clip.names["HTML Format"]: b"<table>cells</table>"}
        # a picture alone (a screenshot), or copied files, come back too
        pic = _FakeClipboard({8: b"DIB" * 50, "PNG": b"\x89PNG-image"})
        TM._clip_api = lambda: (pic, pic)
        saved = TM._clip_save()
        assert TM._clip_put(ours) and TM._clip_put(saved)
        assert pic.data == {8: b"DIB" * 50, pic.names["PNG"]: b"\x89PNG-image"}
        files = _FakeClipboard({15: b"DROPFILES-a.xlsx", "Preferred DropEffect": b"\x01\0\0\0"})
        TM._clip_api = lambda: (files, files)
        saved = TM._clip_save()
        assert TM._clip_put(ours) and TM._clip_put(saved)
        assert files.data == {15: b"DROPFILES-a.xlsx", files.names["Preferred DropEffect"]: b"\x01\0\0\0"}
        # an empty clipboard is left empty; a password manager's copy is not even read, and not put back
        none = _FakeClipboard({})
        TM._clip_api = lambda: (none, none)
        assert TM._clip_save() == [] and TM._clip_put(ours) and TM._clip_put([]) and none.data == {}
        pw = _FakeClipboard({13: "pa55word\0".encode("utf-16-le"), "ExcludeClipboardContentFromMonitorProcessing": b""})
        TM._clip_api = lambda: (pw, pw)
        assert TM._clip_save() == [] and pw.reads == 0
        # a busy clipboard stops the paste before anything is touched
        ctms_act._open_clipboard = lambda: False
        TM._clip_api = lambda: (clip, clip)
        try:
            TM._clip_save()
            assert False, "a busy clipboard must stop it"
        except TM.Stop as e:
            assert "busy" in str(e)
        assert not TM._clip_put(ours)
    finally:
        TM._clip_api, ctms_act._open_clipboard = keep


def test_the_bridge_sends_in_teams_only_with_the_switch_and_says_why_it_stopped():
    keep = (TM.send, B.LOG)
    B.LOG = os.path.join(tempfile.gettempdir(), "ctms_bridge_test_log.jsonl")
    calls = []

    def fake(email, name, text, dry=False):
        calls.append((email, name, text, dry))
        if "stop" in text:
            raise TM.Stop("The cursor is not in Teams' message box - nothing typed.")
        return {"ok": True, "said": "Sent to Sam Example on Teams.", "payload": {"kind": "teams", "img": ""}}
    TM.send = fake
    try:
        desk = _Rec()
        b = B.Bridge(desk, 1, "", allow_control=True)
        cmd = {"id": 1, "action": "teams_send", "email": "sam.example@example.com", "name": "Sam", "text": "Hi Sam"}
        b.handle(cmd)                                                      # switched off: not even tried
        assert desk.sent[-1][1]["ok"] is False and calls == []
        b.armed = True
        b.handle(dict(cmd, id=2))
        r = desk.sent[-1][1]
        assert r["ok"] and r["detail"] == "Sent to Sam Example on Teams." and calls[-1][3] is False
        b.handle(dict(cmd, id=3, text="please stop", dry=True))
        r = desk.sent[-1][1]
        assert not r["ok"] and r["detail"].startswith("Not sent: The cursor is not in Teams") and calls[-1][3] is True
    finally:
        TM.send, B.LOG = keep


def test_send_in_teams_goes_only_to_the_noc_list_and_switches_acting_on_for_that_one_message():
    fresh()
    keep = S._panel
    S._panel = {"noc_teams": [{"name": "Sam", "email": "sam.example@example.com"}]}
    try:
        body = {"email": "sam.example@example.com", "text": "Hi Sam, would you be able to cover the job below?"}
        assert call("/api/ctms/teams", body, key=AGENT)[0] == 401
        assert call("/api/ctms/teams", dict(body, email="someone@example.com"))[0] == 400     # not on the list
        assert call("/api/ctms/teams", dict(body, text=""))[0] == 400
        code, r = call("/api/ctms/teams", dict(body, email="SAM.Example@example.com"))
        assert code == 200 and S._ctms_armed() and S._ctms["armed_for"] == r["id"]
        q = S._ctms["queue"][-1]
        assert q == dict(q, action="teams_send", email="sam.example@example.com", name="Sam", text=body["text"],
                         dry=False)
        assert call("/api/ctms/teams", body)[0] == 409                                        # one at a time
        assert call("/api/ctms/result", {"id": r["id"], "action": "teams_send", "ok": True,
                                         "detail": "Sent to Sam Example on Teams."}, key=BRIDGE)[0] == 200
        assert not S._ctms_armed()                                                            # off again
        assert S._ctms_args("teams_send", {"email": "a@b.co", "name": "A", "text": "x" * 5000, "dry": 1})             == dict(S._ctms_args("teams_send", {"email": "a@b.co", "name": "A", "text": "x" * 5000, "dry": 1}),
                    email="a@b.co", name="A", text="x" * 4000, dry=True)
    finally:
        S._panel = keep
        S._ctms["control_until"] = 0.0
        S._ctms["armed_for"] = None
        S._ctms["queue"] = []


def test_set_time_look_ups_come_at_9_12_3_and_5_on_weekdays_wait_for_a_quiet_work_pc_and_retry():
    fresh()
    keep = (S._tracker, S._panel, dict(S._check_slot))
    S._tracker = {"records": [{"id": "9100070|x", "orders": ["9100070"], "kind": "delivery",
                               "delivery_date": (datetime.now() + timedelta(days=3)).strftime("%d/%m/%Y")}]}
    S._panel = {}
    S._check_slot.update(done=[], next_try=0.0, pending=None)
    mon = datetime(2026, 11, 2, 9, 4)                                   # a Monday, just past nine
    try:
        assert S._uk_time(datetime(2026, 7, 1, 8, 0)) == datetime(2026, 7, 1, 9, 0)      # BST
        assert S._uk_time(datetime(2026, 11, 2, 8, 0)) == datetime(2026, 11, 2, 8, 0)    # GMT
        assert S._check_next(mon) == "12:00" and S._check_next(datetime(2026, 11, 6, 18, 0)) == "Mon 09:00"
        with S._lock:
            S._ctms["seen"] = time.time()                               # the bridge online
            cmd = S._ctms_due_check_locked(uk=mon)
            assert cmd and cmd["idle"] == 3 and cmd["by"] == "set time 09:00" and S._ctms["armed_for"] == cmd["id"]
            assert cmd["orders"][0]["ref"] == "9100070"
            assert S._ctms_due_check_locked(uk=mon) is None             # one at a time
        # the work PC in use: switched off again, tried again in five minutes - not before
        call("/api/ctms/result", {"id": cmd["id"], "action": "ctms_check", "ok": False, "detail": "Not looked up",
                                  "payload": {"postponed": True}}, key=BRIDGE)
        assert not S._ctms_armed()
        with S._lock:
            S._ctms["queue"].clear()
            S._ctms["seen"] = time.time()
            assert S._ctms_due_check_locked(uk=mon, now=time.time() + 60) is None
            cmd2 = S._ctms_due_check_locked(uk=mon, now=time.time() + S.CHECK_RETRY + 1)
            assert cmd2 and cmd2["id"] != cmd["id"]
        call("/api/ctms/result", {"id": cmd2["id"], "action": "ctms_check", "ok": True, "detail": "Looked up"},
             key=BRIDGE)
        later = time.time() + 2 * S.CHECK_RETRY
        with S._lock:
            S._ctms["queue"].clear()
            S._ctms["seen"] = time.time()
            assert S._ctms_due_check_locked(uk=mon.replace(hour=11, minute=30), now=later) is None   # nine is done
            cmd3 = S._ctms_due_check_locked(uk=mon.replace(hour=12, minute=1), now=later)
            assert cmd3 and cmd3["by"] == "set time 12:00"
            # gone unanswered (the bridge restarted mid-run): tried again after the wait
            S._ctms["queue"].clear()
            assert S._ctms_due_check_locked(uk=mon.replace(hour=12, minute=2), now=later) is None
            assert S._check_slot["pending"] is None
            assert S._ctms_due_check_locked(uk=mon.replace(hour=12, minute=8), now=later + S.CHECK_RETRY + 1)
            S._ctms["queue"].clear()
            S._check_slot["pending"] = None
            assert S._ctms_due_check_locked(uk=datetime(2026, 11, 7, 12, 1), now=later * 2) is None   # Saturday
            S._ctms["seen"] = 0.0                                                                     # offline
            assert S._ctms_due_check_locked(uk=mon.replace(hour=15, minute=1), now=later * 2) is None
        assert "next_check" in call("/api/ctms/status")[1]
    finally:
        S._tracker, S._panel = keep[0], keep[1]
        S._check_slot.clear()
        S._check_slot.update(keep[2])
        fresh()


def test_closing_presses_only_the_export_tabs_own_close_button():
    class Tabs:
        """Edge's tab strip, as UI Automation hands it: each tab with its close button."""
        pressed = []

        def __init__(self):
            self.held = []

        def tabs(self, hwnd):
            return [("ctms", "Oracle Fusion Middleware Forms Services"), ("exp", EXP), ("mail", "Inbox - Outlook")]

        def children(self, el):
            return [f"{el}:icon", f"{el}:close"]

        def control_type(self, el):
            return TB.BUTTON if el.endswith(":close") else 50020        # a button, or an image

        def name(self, el):
            return "Close" if el.endswith(":close") else ""

        def invoke(self, el):
            Tabs.pressed.append(el)
            return True

        def close(self):
            pass
    keep = (TB._Session, TB._edge_windows)
    TB._Session, TB._edge_windows = Tabs, (lambda: [1])
    try:
        assert TB.close(X.is_export) == 1 and Tabs.pressed == ["exp:close"]
        assert TB.close(lambda n: False) == 0 and Tabs.pressed == ["exp:close"]
    finally:
        TB._Session, TB._edge_windows = keep


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
