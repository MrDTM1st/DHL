"""
Remote updates for the work PC - and the way back if one breaks.

The bridge runs this when the dashboard or the home PC says "update". The code
only ever comes from GitHub (github.com/MrDTM1st/DHL - main, or a branch of
it). The dashboard and the home PC can say WHEN and WHICH BRANCH; they cannot
send code. So someone who got into the dashboard could, at worst, install what
is already on GitHub.

Before anything is replaced, the new code is tried in a scratch folder: every
changed .py file must compile and the bridge's own modules must import. Only
then are the files it replaces copied aside and the new ones laid down, and
the bridge restarts on them. If the new code dies before it checks in with the
dashboard, the supervisor in ctms_bridge.py puts the old files back and starts
again - a bad push cannot strand the work PC with a bridge that will not run.

    python ctms_update.py                  what an update from main would change
    python ctms_update.py --branch B       ...from branch B instead
    python ctms_update.py --rollback       put back what the last update replaced

Like update_from_github.py, nothing that holds the engine's state can be
touched (it is gitignored, so it is not in the ZIP), and nothing is deleted
except a file the update itself added, when that update is rolled back.
"""
import hashlib
import json
import os
import py_compile
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from urllib.parse import urlsplit

import pip_here
import update_from_github as ufg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))           # the repo root
REPO_ZIP = "https://github.com/MrDTM1st/DHL/archive/refs/heads/{branch}.zip"
# What an update lays down. The bridge's own folder by default; "all" is the
# whole toolkit, for the day everything runs on the work PC.
SCOPES = {"bridge": "region2-emailer/work_pc/", "all": ""}
BACKUPS = os.path.join(HERE, "_update_backups")
PENDING = os.path.join(HERE, "_update_pending.json")    # an update not yet proven to start
STAMP = os.path.join(HERE, "_code_version.json")        # which commit this folder is running
ROLLED = os.path.join(HERE, "_update_rolled_back.json") # the last update that had to be undone
KEEP_BACKUPS = 5
# What must import for the bridge to start at all.
SMOKE = ("cdp", "ctms_drive", "ctms_update", "ctms_bridge")


class UpdateError(Exception):
    """The update was not applied. The message says why."""


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write(path, obj):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def current():
    """{"commit", "branch", "at", ...} of the code in this folder, or {}."""
    return _read(STAMP) or {}


def pending():
    return _read(PENDING)


def rolled_back():
    return _read(ROLLED)


def branch_ok(branch):
    return bool(re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch or "")) and ".." not in branch


def download(branch="main", url=None):
    """The branch as a ZIP, from GitHub, into a temp folder. Returns the file's path."""
    if not url:
        if not branch_ok(branch):
            raise UpdateError(f"'{branch}' is not a branch name.")
        # CTMS_UPDATE_ZIP points the tests at a ZIP served locally
        url = os.environ.get("CTMS_UPDATE_ZIP", REPO_ZIP).format(branch=branch)
    host = (urlsplit(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    else:
        # the same two walls pip hits on this PC, got round the same way:
        # the proxy out of the PAC, and the machine's own trusted roots
        proxy = pip_here.proxy_from_pac()
        bundle = pip_here.write_bundle()
        handler = (urllib.request.ProxyHandler({"http": f"http://{proxy}", "https": f"http://{proxy}"})
                   if proxy else urllib.request.ProxyHandler())
        ctx = ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()
        opener = urllib.request.build_opener(handler, urllib.request.HTTPSHandler(context=ctx))
    folder = tempfile.mkdtemp(prefix="ctms-update-")
    dest = os.path.join(folder, "repo.zip")
    try:
        with opener.open(url, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(f"GitHub answered HTTP {e.code} for {url}"
                          + (" - is that branch pushed?" if e.code == 404 else "."))
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(f"Could not download {url}: {type(e).__name__}: {e}")
    if os.path.getsize(dest) < 10000:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError("What came back is far too small to be the repo - a proxy sign-in page, most likely.")
    return dest


def plan(zpath, scope="bridge"):
    """(commit, [(path in repo, bytes)]) - the files laying this ZIP down would add or change."""
    if scope not in SCOPES:
        raise UpdateError(f"'{scope}' is not something to update.")
    prefix = SCOPES[scope]
    try:
        zf = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        raise UpdateError("The download is not a ZIP - a proxy page, most likely.")
    with zf:
        names = zf.namelist()
        if not names:
            raise UpdateError("The ZIP is empty.")
        top = names[0].split("/")[0] + "/"
        for want in ufg.EXPECT:
            if top + want not in names:
                raise UpdateError(f"{want} is not in it - this is not the toolkit.")
        # GitHub writes the commit id into an archive's comment
        commit = zf.comment.decode("ascii", "ignore").strip()[:40]
        changes = []
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith(top):
                continue
            rel = info.filename[len(top):]
            parts = rel.split("/")
            if not rel or not rel.startswith(prefix) or ".." in parts or rel.startswith("/") or ":" in rel:
                continue
            data = zf.read(info)
            target = os.path.join(ROOT, *parts)
            if os.path.isfile(target) and hashlib.sha256(ufg.norm(data)).hexdigest() == ufg.digest(target):
                continue
            changes.append((rel, data))
    return commit, changes


def _tail(text, n=600):
    text = (text or "").strip()
    return text[-n:] if len(text) > n else text


def smoke(changes):
    """Try the new code before it replaces anything. Raises UpdateError if it would not run."""
    stage = tempfile.mkdtemp(prefix="ctms-smoke-")
    try:
        for rel, data in changes:
            if not rel.endswith(".py"):
                continue
            p = os.path.join(stage, "compile", *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            try:
                py_compile.compile(p, cfile=p + "c", doraise=True)
            except py_compile.PyCompileError as e:
                raise UpdateError(f"{rel} does not compile: {_tail(e.msg, 300)}")
        # the bridge folder as it would be after the update, imported from scratch
        wp = os.path.join(stage, "work_pc")
        os.makedirs(wp)
        for n in os.listdir(HERE):
            if n.endswith(".py"):
                shutil.copy2(os.path.join(HERE, n), wp)
        for rel, data in changes:
            if rel.startswith(SCOPES["bridge"]) and rel.count("/") == 2 and rel.endswith(".py"):
                with open(os.path.join(wp, rel.rsplit("/", 1)[1]), "wb") as f:
                    f.write(data)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=wp)
        r = subprocess.run([sys.executable, "-c", "import " + ", ".join(SMOKE)], cwd=wp, env=env,
                           capture_output=True, text=True, timeout=90)
        if r.returncode:
            raise UpdateError("the new code does not start: " + _tail(r.stderr or r.stdout))
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def stamp(commit, branch, scope, files):
    _write(STAMP, {"commit": commit, "branch": branch, "scope": scope, "files": files,
                   "at": datetime.now().isoformat(timespec="seconds")})


def apply(changes, commit, branch, scope="bridge"):
    """Copy aside what is replaced, lay the new files down, mark the update unproven."""
    if scope == "all" and ufg.engine_running():
        raise UpdateError("the engine (supervisor.py) is running on this PC - replacing its modules "
                          "under it gives a half-old, half-new engine. Stop it first.")
    if pending():
        raise UpdateError("the previous update has not checked in yet - restart the bridge first.")
    bdir = os.path.join(BACKUPS, datetime.now().strftime("%Y%m%d-%H%M%S"))
    saved, added = [], []
    try:
        os.makedirs(bdir, exist_ok=True)
        for rel, _ in changes:
            target = os.path.join(ROOT, *rel.split("/"))
            if os.path.isfile(target):
                # numbered, not the repo path nested again: Windows still stops
                # at 260 characters, and a deep folder would get there
                shutil.copy2(target, os.path.join(bdir, str(len(saved))))
                saved.append(rel)
            else:
                added.append(rel)
        if os.path.isfile(STAMP):
            shutil.copy2(STAMP, os.path.join(bdir, "stamp.json"))
        manifest = {"backup": bdir, "saved": saved, "added": added, "commit": commit, "branch": branch,
                    "scope": scope, "previous": current(), "at": datetime.now().isoformat(timespec="seconds")}
        _write(os.path.join(bdir, "manifest.json"), manifest)
    except OSError as e:
        shutil.rmtree(bdir, ignore_errors=True)
        raise UpdateError(f"could not copy the current files aside ({e}) - nothing was changed.")
    _write(PENDING, manifest)               # before the first file changes: recoverable from here on
    try:
        for rel, data in changes:
            target = os.path.join(ROOT, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target + ".part", "wb") as f:
                f.write(data)
            os.replace(target + ".part", target)
    except OSError as e:
        rollback(f"could not write the new files ({e})")
        raise UpdateError(f"could not write the new files ({e}) - the previous ones are back.")
    stamp(commit, branch, scope, len(changes))
    if os.path.isfile(ROLLED):
        os.remove(ROLLED)
    _prune()
    return bdir


def confirm():
    """The new code started and checked in: it stays. True if there was one to confirm."""
    if os.path.isfile(PENDING):
        os.remove(PENDING)
        return True
    return False


def rollback(reason=""):
    """Put back the files the last update replaced. Returns a sentence saying what happened."""
    m = pending()
    if not m:
        dirs = sorted(d for d in (os.listdir(BACKUPS) if os.path.isdir(BACKUPS) else [])
                      if os.path.isfile(os.path.join(BACKUPS, d, "manifest.json")))
        if not dirs:
            raise UpdateError("there is no update to undo.")
        m = _read(os.path.join(BACKUPS, dirs[-1], "manifest.json"))
    bdir = m["backup"]
    for i, rel in enumerate(m.get("saved") or []):
        dst = os.path.join(ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(bdir, str(i)), dst)
    for rel in m.get("added") or []:
        p = os.path.join(ROOT, *rel.split("/"))
        if os.path.isfile(p):
            os.remove(p)
    old = os.path.join(bdir, "stamp.json")
    if os.path.isfile(old):
        shutil.copy2(old, STAMP)
    elif os.path.isfile(STAMP):
        os.remove(STAMP)
    if os.path.isfile(PENDING):
        os.remove(PENDING)
    note = {"commit": m.get("commit"), "branch": m.get("branch"), "reason": reason or "rolled back by hand",
            "at": datetime.now().isoformat(timespec="seconds")}
    _write(ROLLED, note)
    shutil.rmtree(bdir, ignore_errors=True)    # used up: a second rollback must not redo this one
    return (f"Put back {len(m.get('saved') or [])} file(s) and removed {len(m.get('added') or [])} new one(s) "
            f"from {m.get('branch')} {str(m.get('commit') or '')[:7]}.")


def _prune():
    if not os.path.isdir(BACKUPS):
        return
    dirs = sorted(os.listdir(BACKUPS))
    for d in dirs[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(BACKUPS, d), ignore_errors=True)


def main():
    args = sys.argv[1:]
    if "--rollback" in args:
        print(rollback())
        return 0
    branch = args[args.index("--branch") + 1] if "--branch" in args and args.index("--branch") + 1 < len(args) else "main"
    scope = "all" if "--all" in args else "bridge"
    z = download(branch)
    try:
        commit, changes = plan(z, scope)
    finally:
        shutil.rmtree(os.path.dirname(z), ignore_errors=True)
    print(f"\n{branch} is at {commit[:7] or '?'}; this folder is at "
          f"{(current().get('commit') or '?')[:7]}.")
    for rel, _ in changes:
        print("   ", rel)
    print(f"{len(changes)} file(s) would change. Nothing was written - the bridge applies updates "
          f"itself when the dashboard or the home PC asks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
