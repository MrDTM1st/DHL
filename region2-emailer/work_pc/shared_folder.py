"""
Shared folders - the toolkit's upload CSVs and emailed rail plans filed where the team keeps them.

    python shared_folder.py                 where the files go, and the last one filed
    python shared_folder.py --folder PATH   file the upload CSVs into PATH from now on
    python shared_folder.py --rail PATH --map "master=FOLDER; BS=FOLDER; ..."
                                            file each emailed rail plan into its folder inside PATH
    python shared_folder.py --off           stop filing the upload CSVs (what is there stays)
    python shared_folder.py --rail-off      stop filing the rail plans (likewise)

Every upload CSV the toolkit makes (NR_*.csv), and every rail plan it emails
(Rail Plan wc DD.MM vN[ supplier].xlsx - never a preview), goes from the home
PC's outbox to the dashboard. The bridge runs this beside its check-ins: about
once a minute it asks the dashboard which of them it holds, and saves each new
one into its folder. The folders are on the work network, which only this PC
reaches - and their paths live in shared_folder.json beside this file, never in
the code (the code is on GitHub).

It only ever adds:
  - an upload CSV goes in under its own name. A file of that name already
    there with the same contents is left alone (filed by hand already); a
    different one keeps its place and this one goes in beside it as
    "name (2).csv"
  - a rail plan goes in the team's way: each email chain has its folder
    inside the Rail Plans folder (which plan goes in which is set with the
    folder, never in the code), the week's plans sit loose in it (older weeks
    go into its done folder, which this never touches), and each new issue of
    a plan is one version up. So it goes in under its own name - unless the
    folder already holds that version of the same plan, or a later one, saved
    by someone else: then it takes the next version up. The same contents
    already there, under any version, are left alone. A plan with no folder
    set is not filed
  - nothing in a folder is ever replaced, moved or deleted
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
SETTINGS = os.path.join(HERE, "shared_folder.json")     # gitignored - where the folders are, and what went in
# An upload CSV, as every maker in the toolkit names it: NR_<kind>[_<ref>]_<ddmmyyyyHHMMSS>.csv - and an
# emailed rail plan, as rail_plan.py names it: Rail Plan wc <DD.MM> v<n>[ <supplier>].xlsx (none = the
# master). Nothing else is ever written - and no name with a path in it can match.
NAME = re.compile(r"NR_[A-Za-z0-9_-]{0,120}?(\d{14})\.csv")
RAIL = re.compile(r"Rail Plan wc (\d{2})\.(\d{2}) v(\d{1,2})((?: [A-Za-z]+){0,4})\.xlsx")
RAIL_ANY_CASE = re.compile(RAIL.pattern, re.I)     # the team's own plans in the folder, however they typed it
RAIL_DAYS = 28          # a plan in the folder older than this is the same week of another year
EVERY = 60              # seconds between looks at the dashboard
FIRST = 15              # ... and before the first, so the bridge has checked in by then
KEEP_DAYS = 30          # how long a filed name is remembered (the dashboard holds one for two days)

_lock = threading.Lock()        # the settings file
_busy = threading.Lock()        # one pass at a time
_status = {"on": False, "rail": False, "ok": False, "last": "", "at": "", "error": ""}


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


def rail(name, any_case=False):
    """(week commencing 'DD.MM', version, supplier - '' for the master) of a rail plan's name, else None."""
    m = (RAIL_ANY_CASE if any_case else RAIL).fullmatch(str(name or ""))
    return (f"{m.group(1)}.{m.group(2)}", int(m.group(3)), m.group(4).strip()) if m else None


def rail_name(wc, version, supplier):
    return f"Rail Plan wc {wc} v{version}" + (f" {supplier}" if supplier else "") + ".xlsx"


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


def parse_routes(text, root):
    """Which folder, straight inside the Rail Plans folder, each plan goes in - from
    "master=Haulage; BS=British Steel": {supplier suffix as typed ('' = the master): folder name}.
    ValueError for anything but PLAN=FOLDER pairs naming folders this PC sees there."""
    routes = {}
    for pair in re.split(r"[;\n]", str(text or "")):
        if not pair.strip():
            continue
        plan, eq, sub = pair.partition("=")
        plan, sub = " ".join(plan.split()), sub.strip().strip('"')
        if not eq or not re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+){0,3}", plan):
            raise ValueError(f"'{pair.strip()}' is not PLAN=FOLDER (master=FOLDER for the master plan, BS=FOLDER ...)")
        if sub in ("", ".", "..") or re.search(r'[\\/:*?"<>|]', sub):
            raise ValueError(f"'{sub}' is not the name of a folder straight inside {root}")
        if not os.path.isdir(os.path.join(root, sub)):
            raise ValueError(f"This PC cannot see a folder called {sub} inside {root}.")
        plan = "" if plan.lower() == "master" else plan
        routes = {k: v for k, v in routes.items() if k.lower() != plan.lower()}
        routes[plan] = sub
    if not routes:
        raise ValueError("No PLAN=FOLDER pairs given.")
    return routes


def route(routes, supplier):
    """The folder a plan for this supplier ('' = the master) goes in, or None."""
    return next((sub for plan, sub in (routes or {}).items() if plan.lower() == supplier.lower()), None)


def set_folder(folder, now=None, kind="csv", routes=None):
    """File into `folder` from now on, and say what is there - kind "rail": the emailed rail plans, each into
    the folder inside it that `routes` ("master=Haulage; BS=British Steel") names for it.
    ValueError if this PC cannot see them."""
    folder = str(folder or "").strip().strip('"')
    if not os.path.isabs(folder):
        raise ValueError(f"'{folder}' is not a whole path - it starts with a drive (S:\\...) or \\\\server\\...")
    if not os.path.isdir(folder):
        raise ValueError(f"This PC cannot see a folder at {folder} - check the path opens in File Explorer here.")
    to = parse_routes(routes, folder) if kind == "rail" and str(routes or "").strip() else None
    now = now or datetime.now()
    with _lock:
        cfg = load()
        if kind == "rail":
            # only emailed plans ever reach it, so there is no start to keep - but another folder's routes go
            if os.path.normcase(cfg.get("rail") or "") != os.path.normcase(folder):
                cfg.pop("rail_routes", None)
            cfg["rail"] = folder
            if to is not None:
                cfg["rail_routes"] = to
        else:
            # the same folder again keeps its start: what was waiting to go in still goes in
            if os.path.normcase(cfg.get("folder") or "") != os.path.normcase(folder) or not _since(cfg):
                cfg["since"] = now.isoformat(timespec="seconds")
            cfg["folder"] = folder
        cfg.setdefault("filed", {})
        _save(cfg)
    if kind == "rail":
        _status.update(rail=True, error="")
        return f"Filing the rail plans that go out by email into {folder}. " + _peek_rail(folder, cfg.get("rail_routes"))
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


def _routes(routes):
    return sorted((routes or {}).items(), key=lambda kv: kv[0].lower())


def _routes_said(routes):
    return ", ".join(f"{sfx or 'master'} -> {sub}" for sfx, sub in _routes(routes))


def _peek_rail(folder, routes):
    """What is in the Rail Plans folder, and the newest plan in each folder a plan goes to - the team's
    own files, to check the routes against."""
    try:
        with os.scandir(folder) as it:
            subs = sorted((e.name for e in it if e.is_dir()), key=str.lower)
    except OSError as e:
        return f"It could not list what is there ({e.strerror or e})."
    said = f"The folders in it: {', '.join(subs) or 'none'}."
    if not routes:
        return said + (" No plan goes in yet - say which folder each one goes in: "
                       "--map \"master=FOLDER; BS=FOLDER; Inf VAS=FOLDER; AMS=FOLDER\".")
    for sfx, sub in _routes(routes):
        newest = None
        try:
            with os.scandir(os.path.join(folder, sub)) as it:
                for e in it:
                    if rail(e.name, any_case=True) and e.is_file():
                        t = e.stat().st_mtime
                        if newest is None or t > newest[0]:
                            newest = (t, e.name)
        except OSError as e:
            said += f" {sfx or 'master'} -> {sub}: cannot list it ({e.strerror or e})."
            continue
        said += (f" {sfx or 'master'} -> {sub}: " + (f"newest there {newest[1]} "
                                                     f"({datetime.fromtimestamp(newest[0]):%d/%m %H:%M})."
                                                     if newest else "no plans in it yet."))
    return said + " Any other plan is not filed."


def stop(kind="csv"):
    with _lock:
        cfg = load()
        if kind == "rail":
            was = cfg.pop("rail", None)
            cfg.pop("rail_routes", None)    # switched back on later, it is told the routes again
        else:
            was = cfg.pop("folder", None)
            cfg.pop("since", None)      # switched back on later, it starts from then
        _save(cfg)
    _status.update({"rail" if kind == "rail" else "on": False, "error": ""})
    if not (cfg.get("folder") or cfg.get("rail")):
        _status["ok"] = False
    what = "the rail plans" if kind == "rail" else "upload CSVs"
    return f"Stopped filing {what} into {was} - everything there stays." if was else f"Filing {what} was off already."


def describe():
    cfg = load()
    if not (cfg.get("folder") or cfg.get("rail")):
        return ("No shared folder set - nothing is filed. To set one:  python shared_folder.py --folder PATH"
                "  (the rail plans: --rail PATH)")
    since = _since(cfg)
    filed = cfg.get("filed") or {}
    last = max(filed.items(), key=lambda kv: str(kv[1].get("at", "")), default=None)
    return (" ".join(([f"Filing upload CSVs into {cfg['folder']}"
                       + (f" - each one made from {since:%d/%m %H:%M} on." if since else ".")]
                      if cfg.get("folder") else [])
                     + ([f"Filing the emailed rail plans into {cfg['rail']}"
                         + (f": {_routes_said(cfg.get('rail_routes'))}." if cfg.get("rail_routes") else
                            " - but no plan has a folder there yet (--map).")] if cfg.get("rail") else []))
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


def file_one(folder, name, data, now=None):
    """One CSV into the folder, touching nothing already there: (the name it went in as, written?)."""
    stem, ext = os.path.splitext(name)
    for n in range(1, 100):
        as_ = name if n == 1 else f"{stem} ({n}){ext}"
        p = os.path.join(folder, as_)
        if _write_new(p, data):
            return as_, True
        if _same(p, data):
            return as_, False           # these very bytes are there already - filed by hand, most likely
    raise OSError(errno.EEXIST, "99 other files of that name are there already", name)


def _write_new(p, data):
    """Write a file that is not there yet - False if one is (never a replace)."""
    try:
        f = open(p, "xb")               # x: refuses a file that is already there
    except FileExistsError:
        return False
    try:
        with f:
            f.write(data)
    except BaseException:
        try:
            os.remove(p)                # its own half-written file, never anyone else's
        except OSError:
            pass
        raise
    return True


def file_rail(folder, name, data, now=None):
    """One emailed rail plan into the folder the team's way: (the name it went in as, written?).

    Under its own name - unless the folder already holds that version of the same plan (same week, same
    supplier), or a later one: then as the next version up, as whoever saved it there would have numbered
    the next issue. The same bytes already there, under any version, are left alone."""
    wc, version, supplier = rail(name)
    cutoff = ((now or datetime.now()) - timedelta(days=RAIL_DAYS)).timestamp()
    top = 0
    with os.scandir(folder) as it:
        for e in it:
            p = rail(e.name, any_case=True)
            if not p or p[0] != wc or p[2].lower() != supplier.lower():
                continue
            try:
                if not e.is_file() or e.stat().st_mtime < cutoff:
                    continue            # the same week of another year
            except OSError:
                continue
            if _same(e.path, data):
                return e.name, False    # gone out already, and in already
            top = max(top, p[1])
    for v in range(max(version, top + 1), max(version, top + 1) + 20):
        as_ = rail_name(wc, v, supplier)
        if _write_new(os.path.join(folder, as_), data):
            return as_, True            # taken by an older year's plan, or one saved this moment: one up
    raise OSError(errno.EEXIST, "20 later versions of that plan are there already", name)


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
    """One look at the dashboard, each new upload CSV and emailed rail plan into its folder.
    [(name, went in as, written?)]"""
    with _busy:
        with _lock:
            cfg = load()
        folder, plans, routes = cfg.get("folder"), cfg.get("rail"), cfg.get("rail_routes") or {}
        _status.update(on=bool(folder), rail=bool(plans))
        if not (folder or plans):
            _status.update(ok=False, error="")
            return []
        since, filed = _since(cfg), cfg.get("filed") or {}
        csvs, rails = [], []
        for f in (_ask(desk, "/api/ctms/uploads", {}) or {}).get("files") or []:
            name = str(f.get("name") or "") if isinstance(f, dict) else ""
            when = made(name)
            if when:
                if folder and name not in filed and (since is None or when >= since):
                    csvs.append((when, name, name, folder))
            elif plans and rail(name):
                sub = route(routes, rail(name)[2])      # its own chain's folder
                # a plan emailed again with other contents under the same name is a new one to file
                sha = re.sub(r"[^0-9a-f]", "", str(f.get("sha") or "").lower())[:16]
                key = f"{name}#{sha}" if sha else name
                if sub and key not in filed:            # one whose chain has no folder waits until it has
                    rails.append((name, name, key, os.path.join(plans, sub)))
        done = []
        for put, todo in ((file_one, sorted(csvs)), (file_rail, sorted(rails))):   # CSVs in the order made
            for _, name, key, target in todo:
                got = _ask(desk, "/api/ctms/upload", {"name": name})
                data = base64.b64decode((got or {}).get("data") or "")
                if not data:
                    continue
                if not os.path.isdir(target):
                    raise OSError(errno.ENOENT, "this PC cannot reach it just now", target)
                at = now or datetime.now()
                as_, wrote = put(target, name, data, at)
                _remember(key, as_, wrote, at)
                _status.update(last=as_, at=at.strftime("%d/%m %H:%M"))
                done.append((name, as_, wrote))
        _status.update(ok=True, error="")
        return done


def _remember(key, as_, wrote, now):
    with _lock:
        cfg = load()
        filed = cfg.setdefault("filed", {})
        filed[key] = {"as": as_, "at": now.isoformat(timespec="seconds"), "written": wrote}
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
        for old in [k for k, r in filed.items() if str((r or {}).get("at") or "") < cutoff]:
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
    cfg = load()
    _status.update(on=bool(cfg.get("folder")), rail=bool(cfg.get("rail")))

    def loop():
        time.sleep(FIRST)
        while True:
            failing = _status.get("error")
            try:
                for name, as_, wrote in tick(desk):
                    log("filed", name=name, saved_as=as_, written=wrote)
                    say(f"{name} was in the shared folder already" + ("" if as_ == name else f" as {as_}")
                        + " - left as it was." if not wrote else
                        f"Filed {name} in the shared folder" + ("." if as_ == name else
                                                                 f" as {as_} - that version of the plan was there "
                                                                 "already." if rail(name) else
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
    ap = argparse.ArgumentParser(description="File the toolkit's upload CSVs and emailed rail plans into "
                                             "the team's shared folders.")
    ap.add_argument("--folder", help="file the upload CSVs into this folder from now on")
    ap.add_argument("--rail", help="file the emailed rail plans into this folder from now on")
    ap.add_argument("--map", help='with --rail: which folder inside it each plan goes in, '
                                  'e.g. "master=Haulage; BS=British Steel"')
    ap.add_argument("--off", action="store_true", help="stop filing the upload CSVs (nothing there is touched)")
    ap.add_argument("--rail-off", action="store_true", help="stop filing the rail plans (likewise)")
    a = ap.parse_args(argv)
    try:
        print(stop() if a.off else stop("rail") if a.rail_off else set_folder(a.folder) if a.folder
              else set_folder(a.rail, kind="rail", routes=a.map) if a.rail else describe())
    except ValueError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
