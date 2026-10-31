"""
Shared folder - the toolkit's upload CSVs filed where the team keeps them.

    python shared_folder.py                 where the CSVs go, and the last one filed
    python shared_folder.py --folder PATH   file them into PATH from now on
    python shared_folder.py --off           stop filing (what is there stays)

Every upload CSV the toolkit makes (NR_*.csv) goes from the home PC's outbox to
the dashboard. The bridge runs this beside its check-ins: about once a minute
it asks the dashboard which upload CSVs it holds, and saves each new one into
the folder under its own name. The folder is on the work network, which only
this PC reaches - and its path lives in shared_folder.json beside this file,
never in the code (the code is on GitHub).

It only ever adds:
  - a file of the same name already there with the same contents is left
    alone (filed by hand already); a different one keeps its place and this
    one goes in beside it as "name (2).csv"
  - nothing in the folder is ever replaced or deleted
  - CSVs made before the folder was set stay as they were - filing starts
    with the next one made

Standard library only, like everything else in work_pc\\.
"""
import argparse
import base64
import errno
import json
import os
import re
import threading
import time
import urllib.error
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "shared_folder.json")     # gitignored - where the folder is, and what went in
# An upload CSV, as every maker in the toolkit names it: NR_<kind>[_<ref>]_<ddmmyyyyHHMMSS>.csv. Nothing
# else is ever written - and no name with a path in it can match.
NAME = re.compile(r"NR_[A-Za-z0-9_-]{0,120}?(\d{14})\.csv")
EVERY = 60              # seconds between looks at the dashboard
FIRST = 15              # ... and before the first, so the bridge has checked in by then
KEEP_DAYS = 30          # how long a filed name is remembered (the dashboard holds one for two days)

_lock = threading.Lock()        # the settings file
_busy = threading.Lock()        # one pass at a time
_status = {"on": False, "ok": False, "last": "", "at": "", "error": ""}


class DeskError(Exception):
    """The dashboard could not be asked - nothing was filed, the next pass tries again."""


def made(name):
    """When the home PC made an upload CSV (its name says) - None for any other name."""
    m = NAME.fullmatch(str(name or ""))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d%m%Y%H%M%S")
    except ValueError:
        return None


def load():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _save(cfg):
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, SETTINGS)


def _since(cfg):
    try:
        return datetime.fromisoformat(cfg["since"])
    except (KeyError, TypeError, ValueError):
        return None


def set_folder(folder, now=None):
    """File into `folder` from now on, and say what is there. ValueError if this PC cannot see it."""
    folder = str(folder or "").strip().strip('"')
    if not os.path.isabs(folder):
        raise ValueError(f"'{folder}' is not a whole path - it starts with a drive (S:\\...) or \\\\server\\...")
    if not os.path.isdir(folder):
        raise ValueError(f"This PC cannot see a folder at {folder} - check the path opens in File Explorer here.")
    now = now or datetime.now()
    with _lock:
        cfg = load()
        # the same folder again keeps its start: what was waiting to go in still goes in
        if os.path.normcase(cfg.get("folder") or "") != os.path.normcase(folder) or not _since(cfg):
            cfg["since"] = now.isoformat(timespec="seconds")
        cfg["folder"] = folder
        cfg.setdefault("filed", {})
        _save(cfg)
    _status.update(on=True, error="")
    return f"Filing upload CSVs into {folder} - each one made from {_since(cfg):%d/%m %H:%M} on. " + _peek(folder)


def _peek(folder):
    n, newest = 0, None
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.is_file() and e.name.lower().endswith(".csv"):
                    n += 1
                    t = e.stat().st_mtime
                    if newest is None or t > newest[0]:
                        newest = (t, e.name)
    except OSError as e:
        return f"It could not list what is there ({e.strerror or e})."
    return (f"It holds {n} CSV{'' if n == 1 else 's'}"
            + (f"; the newest is {newest[1]} ({datetime.fromtimestamp(newest[0]):%d/%m %H:%M})." if newest else "."))


def stop():
    with _lock:
        cfg = load()
        was = cfg.pop("folder", None)
        cfg.pop("since", None)          # switched back on later, it starts from then
        _save(cfg)
    _status.update(on=False, ok=False, error="")
    return f"Stopped filing into {was} - everything there stays." if was else "Filing was off already."


def describe():
    cfg = load()
    if not cfg.get("folder"):
        return "No shared folder set - nothing is filed. To set one:  python shared_folder.py --folder PATH"
    since = _since(cfg)
    filed = cfg.get("filed") or {}
    last = max(filed.items(), key=lambda kv: str(kv[1].get("at", "")), default=None)
    return (f"Filing upload CSVs into {cfg['folder']}"
            + (f" - each one made from {since:%d/%m %H:%M} on." if since else ".")
            + (f" Last filed: {last[1].get('as') or last[0]} at {last[1].get('at', '?')[:16].replace('T', ' ')}."
               if last else " Nothing filed yet.")
            + (f" Last try: {_status['error']}." if _status.get("error") else ""))


def state():
    """What the bridge's check-in says about filing."""
    return dict(_status)


def _same(p, data):
    try:
        if os.path.getsize(p) != len(data):
            return False
        with open(p, "rb") as f:
            return f.read() == data
    except OSError:
        return False


def file_one(folder, name, data):
    """One CSV into the folder, touching nothing already there: (the name it went in as, written?)."""
    stem, ext = os.path.splitext(name)
    for n in range(1, 100):
        as_ = name if n == 1 else f"{stem} ({n}){ext}"
        p = os.path.join(folder, as_)
        try:
            f = open(p, "xb")           # x: refuses a file that is already there - never a replace
        except FileExistsError:
            if _same(p, data):
                return as_, False       # these very bytes are there already - filed by hand, most likely
            continue
        try:
            with f:
                f.write(data)
        except BaseException:
            try:
                os.remove(p)            # its own half-written file, never anyone else's
            except OSError:
                pass
            raise
        return as_, True
    raise OSError(errno.EEXIST, "99 other files of that name are there already", name)


def _ask(desk, path, body):
    try:
        return desk.post(path, body, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404 and path == "/api/ctms/upload":
            return None                 # gone from the dashboard since it was listed
        raise DeskError({404: "the dashboard has no list of upload CSVs yet - it needs redeploying",
                         401: "the dashboard does not accept this bridge's key"}.get(
                             e.code, f"the dashboard answered HTTP {e.code}")) from e
    except Exception as e:
        raise DeskError(f"cannot reach the dashboard ({type(e).__name__})") from e


def tick(desk, now=None):
    """One look at the dashboard, each new upload CSV into the folder. [(name, went in as, written?)]"""
    with _busy:
        with _lock:
            cfg = load()
        folder = cfg.get("folder")
        _status["on"] = bool(folder)
        if not folder:
            _status.update(ok=False, error="")
            return []
        since, filed = _since(cfg), cfg.get("filed") or {}
        todo = []
        for f in (_ask(desk, "/api/ctms/uploads", {}) or {}).get("files") or []:
            name = str(f.get("name") or "") if isinstance(f, dict) else ""
            when = made(name)
            if when and name not in filed and (since is None or when >= since):
                todo.append((when, name))
        done = []
        for _, name in sorted(todo):    # in the order they were made
            got = _ask(desk, "/api/ctms/upload", {"name": name})
            data = base64.b64decode((got or {}).get("data") or "")
            if not data:
                continue
            if not os.path.isdir(folder):
                raise OSError(errno.ENOENT, "this PC cannot reach it just now", folder)
            as_, wrote = file_one(folder, name, data)
            at = now or datetime.now()
            _remember(name, as_, wrote, at)
            _status.update(last=as_, at=at.strftime("%d/%m %H:%M"))
            done.append((name, as_, wrote))
        _status.update(ok=True, error="")
        return done


def _remember(name, as_, wrote, now):
    with _lock:
        cfg = load()
        filed = cfg.setdefault("filed", {})
        filed[name] = {"as": as_, "at": now.isoformat(timespec="seconds"), "written": wrote}
        cutoff = now - timedelta(days=KEEP_DAYS)
        for old in [n for n in filed if (made(n) or now) < cutoff]:
            del filed[old]
        _save(cfg)


def why(e):
    if isinstance(e, DeskError):
        return str(e)
    if isinstance(e, OSError):
        return f"could not file into the shared folder - {e.strerror or e}"
    return f"{type(e).__name__}: {e}"


def start(desk, say=print, log=lambda kind, **kw: None):
    """File in the background for as long as the bridge runs - never in the way of a CTMS command."""
    _status["on"] = bool(load().get("folder"))

    def loop():
        time.sleep(FIRST)
        while True:
            failing = _status.get("error")
            try:
                for name, as_, wrote in tick(desk):
                    log("filed", name=name, saved_as=as_, written=wrote)
                    say(f"{name} was in the shared folder already - left as it was." if not wrote else
                        f"Filed {name} in the shared folder" + ("." if as_ == name else
                                                                 f" as {as_} - another file has its name."))
                if failing:
                    say("Shared folder: working again.")
                    log("filing_ok")
            except Exception as e:
                msg = why(e)
                if msg != _status.get("error"):
                    say(f"Shared folder: {msg} - trying again every minute.")
                    log("filing_error", error=msg)
                _status.update(ok=False, error=msg)
            time.sleep(EVERY)

    t = threading.Thread(target=loop, name="shared-folder", daemon=True)
    t.start()
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(description="File the toolkit's upload CSVs into the team's shared folder.")
    ap.add_argument("--folder", help="file them into this folder from now on")
    ap.add_argument("--off", action="store_true", help="stop filing (nothing already there is touched)")
    a = ap.parse_args(argv)
    try:
        print(stop() if a.off else set_folder(a.folder) if a.folder else describe())
    except ValueError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
