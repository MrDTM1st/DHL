"""
git pull, without git. For the work PC, where git is not installed.

    python update_from_github.py             DRY RUN - shows what would change
    python update_from_github.py apply       actually updates the code

If Python cannot get out at all - proxy, TLS, policy - fetch the ZIP with the
BROWSER instead (github.com/MrDTM1st/DHL -> Code -> Download ZIP, or the
dashboard's update button) and point this at the file. No network needed:

    python update_from_github.py <path-to.zip>         DRY RUN
    python update_from_github.py <path-to.zip> apply

Downloads the repo's ZIP straight from GitHub and lays it over the working
copy. It reuses pip_here.py's proxy-from-PAC and Windows-CA-bundle logic,
because the two walls that stop pip reaching pypi.org stop urllib reaching
github.com in exactly the same way and for exactly the same reasons.

WHY THIS IS SAFE FOR YOUR DATA. A GitHub archive contains only what is
COMMITTED. Everything the engine actually knows - tracker.json, waitlist.json,
config.json, config/team.json, order_index.json, the _*.json working files,
synergy_template.xlsx, haulage_request_template.xlsx - is gitignored, so it is
not in the ZIP, so it cannot be written over by this. The set of files this can
touch and the set of files that hold your state do not intersect.

Nothing is ever deleted. A file removed upstream stays on this machine and is
reported, rather than being cleaned up behind your back.
"""
import hashlib
import os
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile

import pip_here

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)              # region2-emailer/
ROOT = os.path.dirname(ENGINE)              # the repo root, where .gitignore lives
ZIP_URL = "https://github.com/MrDTM1st/DHL/archive/refs/heads/main.zip"

# If these are not in the downloaded archive, it is not our repo - a captive
# portal's sign-in page, or the wrong branch. Never lay that over the toolkit.
EXPECT = ("region2-emailer/build_drafts.py", "region2-emailer/send_order.py")


def norm(raw):
    """Content with line endings normalised, so CRLF vs LF is not a "change".

    git checks out text as CRLF on Windows; a GitHub ZIP carries the raw blobs,
    which are LF. Compare the bytes and EVERY text file in the repo looks
    modified on every single run - the report becomes noise, and the update
    rewrites hundreds of files that did not change. Binary files (.xlsx, .png)
    are left alone: they are not decodable, and "normalising" them would
    corrupt the comparison.
    """
    try:
        return raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
    except UnicodeDecodeError:
        return raw


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(norm(f.read())).hexdigest()


def engine_running():
    """A supervisor mid-run holds .py files that are about to be replaced."""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or "
             "Name='python.exe'\" | Where-Object { $_.CommandLine -like "
             "'*supervisor.py*' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=30)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:
        return False          # can't tell - don't block on a failed check


def fetch(dest):
    print("Working out how this machine reaches the internet:")
    proxy = pip_here.proxy_from_pac()
    bundle = pip_here.write_bundle()

    if proxy:
        op = urllib.request.ProxyHandler({"http": f"http://{proxy}",
                                          "https": f"http://{proxy}"})
    else:
        op = urllib.request.ProxyHandler()          # honour system settings
    ctx = ssl.create_default_context(cafile=bundle) if bundle else None
    opener = urllib.request.build_opener(op, urllib.request.HTTPSHandler(context=ctx))

    print(f"\nDownloading {ZIP_URL}")
    with opener.open(ZIP_URL, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    size = os.path.getsize(dest)
    print(f"  {size:,} bytes")
    if size < 10000:
        raise SystemExit("  that is far too small to be the repo - almost "
                         "certainly a proxy sign-in page. Nothing changed.")
    return dest


def plan(zf, top):
    """(added, changed, unchanged) - what laying this ZIP down would do."""
    added, changed, unchanged = [], [], []
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = info.filename[len(top):].lstrip("/")
        if not rel:
            continue
        target = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.exists(target):
            added.append(rel)
            continue
        h = hashlib.sha256(norm(zf.read(info))).hexdigest()
        (unchanged if h == digest(target) else changed).append(rel)
    return added, changed, unchanged


def main():
    args = [a.strip() for a in sys.argv[1:]]
    apply = any(a.lower() == "apply" for a in args)
    local = next((a for a in args if a.lower().endswith(".zip")), None)
    print(__doc__ if not apply else "Updating.\n")

    if local and not os.path.isfile(local):
        raise SystemExit(f"  no such file: {local}")

    tmp = tempfile.mkdtemp(prefix="dhl-update-")
    try:
        # A ZIP the browser already fetched needs no network from Python at all,
        # which is the whole point on a machine where git, pip and urllib are
        # all walled off but the browser reaches github.com fine.
        if local:
            print(f"Using the ZIP you already have:\n  {local}"
                  f"  ({os.path.getsize(local):,} bytes)")
            zpath = local
        else:
            zpath = fetch(os.path.join(tmp, "main.zip"))
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            top = names[0].split("/")[0] + "/"
            for want in EXPECT:
                if not any(n == top + want for n in names):
                    raise SystemExit(f"  {want} is not in the archive - this is "
                                     "not the toolkit. Nothing changed.")
            added, changed, unchanged = plan(zf, top)

            print(f"\n  {len(added)} new, {len(changed)} changed, "
                  f"{len(unchanged)} already up to date")
            for rel in added:
                print(f"    NEW      {rel}")
            for rel in changed:
                print(f"    UPDATED  {rel}")

            if not (added or changed):
                print("\nAlready up to date. Nothing to do.")
                return 0

            if not apply:
                print("\nDRY RUN - nothing written. Re-run with 'apply' to update:")
                print("  python work_pc\\update_from_github.py apply")
                return 0

            if engine_running():
                # Replacing modules under a live supervisor is how you get a
                # half-old, half-new engine and an afternoon of confusion.
                print("\n!! The supervisor is RUNNING. Stop it before updating,")
                print("   then start it again afterwards. Nothing changed.")
                return 2

            for rel in added + changed:
                target = os.path.join(ROOT, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(top + rel) as s, open(target, "wb") as d:
                    shutil.copyfileobj(s, d)
                print(f"    ok  {rel}")

        print(f"\nUpdated {len(added) + len(changed)} file(s).")
        print("Nothing was deleted: a file removed upstream is still here.")
        print("Now run:  python work_pc\\engine_preflight.py")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
