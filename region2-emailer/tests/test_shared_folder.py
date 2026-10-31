"""Plain-assert tests for filing the upload CSVs in the team's shared folder -
no work PC, no network share.

Covers the places a mistake would cost something real: the team's folder
(nothing there is ever replaced or deleted, nothing but an upload CSV is ever
written, no name can reach outside it, a failed write leaves no half file),
the dashboard (only the bridge's key gets the upload CSVs, and a busy Files
list cannot drop one before the work PC has it), and filing each CSV exactly
once - not again after the dashboard restarts, and never the ones made before
the folder was set.

Run:  python region2-emailer/tests/test_shared_folder.py
"""
import base64
import errno
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ENGINE, "cloud"))
sys.path.insert(0, os.path.join(ENGINE, "work_pc"))
sys.path.insert(0, ENGINE)
os.environ["DASH_KEY"] = "dash-test-key"
os.environ["AGENT_KEY"] = "agent-test-key"

import server as S                      # noqa: E402  (reads the keys at import)
import ctms_bridge as B                 # noqa: E402
import shared_folder as SF              # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

DASH, AGENT = "dash-test-key", "agent-test-key"
BRIDGE = B.bridge_key(DASH)

_httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{_httpd.server_address[1]}"
_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CSV = "NR_heavy_AH2-11-26TEST_31102026093000.csv"         # made 31/10 09:30
EARLY = "NR_heavy_AH2-11-26EARLY_31102026080000.csv"      # made 31/10 08:00
SET_AT = datetime(2026, 10, 31, 9, 0)                     # the folder was set at 09:00


def call(path, body=None, key=DASH):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Auth": key, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with _op.open(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def push(name, data=b"ORD,1\r\nORD_LINES,1\r\n"):
    """The home agent sending an outbox file up, as push_new_files does."""
    return call("/api/files", {"name": name, "size": len(data), "data": base64.b64encode(data).decode()}, key=AGENT)


class Place:
    """A fresh dashboard, a share to file into, and the work PC's settings file - all thrown away after."""

    def __enter__(self):
        S._files.clear()
        S._to_file.clear()
        self.root = tempfile.mkdtemp(prefix="sf-test-")
        self.share = os.path.join(self.root, "Exports", "Done")
        os.makedirs(self.share)
        self.keep = SF.SETTINGS, B.LOG
        SF.SETTINGS = os.path.join(self.root, "shared_folder.json")
        B.LOG = os.path.join(self.root, "bridge_log.jsonl")
        SF._status.update(on=False, ok=False, last="", at="", error="")
        self.desk = B.Desk(BASE, BRIDGE)
        return self

    def __exit__(self, *exc):
        SF.SETTINGS, B.LOG = self.keep
        shutil.rmtree(self.root, ignore_errors=True)

    def files(self):
        return sorted(os.listdir(self.share))

    def read(self, name):
        with open(os.path.join(self.share, name), "rb") as f:
            return f.read()


# ---- the dashboard -----------------------------------------------------------
def test_only_the_bridge_gets_the_upload_csvs_and_nothing_else_from_the_files_list():
    with Place():
        push(CSV, b"ours")
        push("Rail Plan wc 02-11-26 v1.xlsx")
        push("Haulage Request - AH2-11-26TEST.xlsx")
        code, body = call("/api/ctms/uploads", {}, key=BRIDGE)
        assert code == 200 and [f["name"] for f in body["files"]] == [CSV], body
        assert call("/api/ctms/upload", {"name": "Rail Plan wc 02-11-26 v1.xlsx"}, key=BRIDGE)[0] == 404
        code, body = call("/api/ctms/upload", {"name": CSV}, key=BRIDGE)
        assert code == 200 and base64.b64decode(body["data"]) == b"ours"
        for key in (DASH, AGENT, ""):                    # the bridge's endpoints are the bridge's
            assert call("/api/ctms/uploads", {}, key=key)[0] == 401
            assert call("/api/ctms/upload", {"name": CSV}, key=key)[0] == 401
        assert call("/api/files", key=BRIDGE)[0] == 401  # and its key still opens nothing else
        assert call("/api/file?name=" + CSV, key=BRIDGE)[0] == 401


def test_an_upload_csv_waits_for_the_work_pc_however_busy_the_files_list_gets():
    with Place():
        push(CSV)
        for i in range(S._MAX_FILES + 3):               # the Files list keeps only the newest 12
            push(f"Seasonal Tracker {i:02}.xlsx")
        assert CSV not in S._files
        assert [f["name"] for f in call("/api/ctms/uploads", {}, key=BRIDGE)[1]["files"]] == [CSV]


# ---- the folder ----------------------------------------------------------------
def test_each_new_upload_csv_goes_in_once_under_its_own_name():
    with Place() as p:
        SF.set_folder(p.share, now=SET_AT)
        push(CSV, b"ours")
        push(EARLY, b"made before the folder was set")
        assert SF.tick(p.desk) == [(CSV, CSV, True)]
        assert p.files() == [CSV] and p.read(CSV) == b"ours"
        assert SF.tick(p.desk) == []                     # remembered
        S._to_file.clear()                               # the dashboard restarts...
        push(CSV, b"ours")                               # ...and the agent's 30-minute heal sends it again
        assert SF.tick(p.desk) == [] and p.files() == [CSV]
        assert SF.state()["ok"] and SF.state()["last"] == CSV
        assert "Last filed: " + CSV in SF.describe()


def test_nothing_in_the_folder_is_ever_replaced():
    with Place() as p:
        SF.set_folder(p.share, now=SET_AT)
        other = "NR_heavy_AH2-11-26SAME_31102026094500.csv"
        with open(os.path.join(p.share, CSV), "wb") as f:
            f.write(b"someone else's")                   # a different file with its name
        with open(os.path.join(p.share, other), "wb") as f:
            f.write(b"same bytes")                       # this one, filed by hand already
        push(CSV, b"ours")
        push(other, b"same bytes")
        went = SF.tick(p.desk)
        assert went == [(CSV, CSV[:-4] + " (2).csv", True), (other, other, False)], went
        assert p.read(CSV) == b"someone else's" and p.read(CSV[:-4] + " (2).csv") == b"ours"
        assert p.read(other) == b"same bytes" and len(p.files()) == 3


def test_only_an_upload_csv_name_is_ever_written_and_never_outside_the_folder():
    class Hostile:
        """A dashboard listing names that are not upload CSVs, or reach out of the folder."""
        names = ["..\\NR_heavy_x_31102026093000.csv", "NR_heavy_..\\..\\x_31102026093000.csv",
                 "C:\\temp\\NR_heavy_x_31102026093000.csv", "NR_heavy_x_31102026093000.csv.exe",
                 "NR_heavy_x_31102026093000.csv:stream", "report_31102026093000.csv", "NR_heavy_x.csv",
                 "NR_heavy_x_99999999999999.csv"]

        def post(self, path, body, timeout=20):
            if path == "/api/ctms/uploads":
                return {"files": [{"name": n} for n in self.names]}
            return {"name": body["name"], "data": base64.b64encode(b"x").decode()}

    with Place() as p:
        SF.set_folder(p.share, now=SET_AT)
        assert SF.tick(Hostile()) == []
        assert p.files() == [] and sorted(os.listdir(p.root)) == ["Exports", "shared_folder.json"]
        assert not os.path.exists(os.path.join(os.path.dirname(p.share), "NR_heavy_x_31102026093000.csv"))


def test_a_write_that_fails_leaves_no_half_file_behind():
    real = open

    class Half:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def write(self, data):
            self.f.write(data[:2])
            raise OSError(errno.ENOSPC, "No space left on device")

    with Place() as p:
        SF.open = lambda path, mode="r", *a, **k: Half(real(path, mode)) if mode == "xb" else real(path, mode, *a, **k)
        try:
            SF.file_one(p.share, CSV, b"the whole file")
            assert False, "the failed write was not raised"
        except OSError:
            pass
        finally:
            del SF.open
        assert p.files() == []
        assert SF.file_one(p.share, CSV, b"the whole file") == (CSV, True)   # and the next pass files it whole


def test_a_folder_out_of_reach_files_nothing_and_catches_up_once_it_is_back():
    with Place() as p:
        SF.set_folder(p.share, now=SET_AT)
        push(CSV, b"ours")
        os.rename(p.share, p.share + "-away")            # the network drops
        try:
            SF.tick(p.desk)
            assert False, "an unreachable folder was not reported"
        except OSError as e:
            assert "could not file into the shared folder" in SF.why(e)
        assert not os.path.exists(p.share)               # nothing made in its place
        os.rename(p.share + "-away", p.share)
        assert SF.tick(p.desk) == [(CSV, CSV, True)]


def test_a_dashboard_out_of_reach_or_not_yet_redeployed_says_so():
    class Old:
        def post(self, path, body, timeout=20):
            raise urllib.error.HTTPError(BASE + path, 404, "Not Found", {}, None)

    with Place() as p:
        SF.set_folder(p.share, now=SET_AT)
        for desk, words in ((Old(), "needs redeploying"), (B.Desk("http://127.0.0.1:9", BRIDGE), "cannot reach")):
            try:
                SF.tick(desk)
                assert False, "no error"
            except SF.DeskError as e:
                assert words in SF.why(e), SF.why(e)
        assert p.files() == []


# ---- setting it --------------------------------------------------------------
def test_the_folder_is_set_from_the_home_pc_and_only_a_folder_this_pc_sees_is_taken():
    class Rec:
        """The real dashboard, with the bridge's answers kept for the test."""
        base = BASE

        def __init__(self, desk):
            self.desk, self.answers = desk, []

        def post(self, path, body, timeout=20):
            if path == "/api/ctms/result":
                self.answers.append(body)
                return {}
            return self.desk.post(path, body, timeout)

    with Place() as p:
        code, r = call("/api/ctms/command", {"action": "shared_folder", "folder": "\\\\srv\\share\\" + "x" * 900},
                       key=AGENT)
        assert code == 200
        cmd = next(c for c in S._ctms["queue"] if c["id"] == r["id"])
        assert cmd["folder"].startswith("\\\\srv\\share\\") and len(cmd["folder"]) == 400
        S._ctms["queue"].clear()
        desk = Rec(p.desk)
        b = B.Bridge(desk, 1, "")
        for folder, words in (("Exports\\Done", "not a whole path"),
                              (os.path.join(p.root, "nowhere"), "cannot see a folder")):
            b.handle({"id": 1, "action": "shared_folder", "folder": folder})
            assert not desk.answers[-1]["ok"] and words in desk.answers[-1]["detail"], desk.answers[-1]
        assert not os.path.exists(SF.SETTINGS)
        push(CSV)                                        # made before it was set: stays as it was
        b.handle({"id": 2, "action": "shared_folder", "folder": p.share})
        a = desk.answers[-1]
        assert a["ok"] and "Filing upload CSVs into " + p.share in a["detail"], a
        assert "It holds 0 CSVs" in a["detail"] and "Nothing new to file yet" in a["detail"], a
        assert b.state()["filing"]["on"] is True
        b.handle({"id": 3, "action": "shared_folder"})
        assert "Nothing filed yet" in desk.answers[-1]["detail"]
        b.handle({"id": 4, "action": "shared_folder", "on": False})
        assert "Stopped filing" in desk.answers[-1]["detail"] and SF.tick(p.desk) == []
        assert p.files() == []


def test_the_check_in_carries_whether_filing_works_cut_to_size():
    S._ctms.update(state={})
    code, _ = call("/api/ctms/poll", {"state": {"filing": {"on": 1, "ok": 0, "last": "N" * 500, "at": "31/10 09:31",
                                                          "error": "e" * 900, "folder": "\\\\srv\\x"}}},
                   key=BRIDGE)
    assert code == 200
    f = S._ctms["state"]["filing"]
    assert f == {"on": True, "ok": False, "last": "N" * 160, "at": "31/10 09:31", "error": "e" * 300}, f


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
