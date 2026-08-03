"""
Move the local state between machines, without forgetting a file.

On the HOME PC, onto a USB stick:      python collect_state.py backup  D:\\dhl-state
On the WORK PC, from that same stick:  python collect_state.py restore D:\\dhl-state

The code is on GitHub; the data never is. That data is the whole difference
between an engine that runs and an engine that knows anything - contacts, the
learned corrections, the quote history, the live tracker, and `_metrics.jsonl`,
which goes back to 2026-07-19 and cannot be reconstructed from anything.

The file list is imported from engine_preflight.py rather than repeated here:
two lists is how a backup script ends up not knowing about a file the preflight
is checking for.

Nothing is deleted, ever. `restore` shows you what it is about to overwrite and
makes you confirm; anything it replaces is kept alongside as <name>.bak.
"""
import os
import shutil
import sys
from datetime import datetime

from engine_preflight import ENGINE, STATE_GROUPS

# Live state is only worth copying once nothing is writing to it - i.e. after
# the home PC engine is stopped. Copying it early gives you a tracker that is
# already stale by the time you cut over.
LIVE = "LIVE STATE"


def files_to_move(include_live=True):
    for title, entries in STATE_GROUPS:
        if not include_live and title.startswith(LIVE):
            continue
        for name, why in entries:
            yield title, name, why


def backup(dest, include_live):
    os.makedirs(dest, exist_ok=True)
    copied = skipped = 0
    for title, name, why in files_to_move(include_live):
        src = os.path.join(ENGINE, name)
        if not os.path.exists(src):
            print(f"  [--]  not on this machine: {name}")
            skipped += 1
            continue
        dst = os.path.join(dest, name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)   # config/team.json
        shutil.copy2(src, dst)
        print(f"  [OK]  {name:24} {os.path.getsize(src):>9,} bytes")
        copied += 1
    stamp = os.path.join(dest, "_collected_at.txt")
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(f"{datetime.now():%d/%m/%Y %H:%M:%S} from {os.environ.get('COMPUTERNAME', '?')}\n")
        f.write(f"live state included: {include_live}\n")
    print(f"\n  {copied} copied, {skipped} not present, into {dest}")
    if not include_live:
        print("  Live state was NOT included (--no-live). Take a second backup")
        print("  with live state once the engine here is stopped.")
    return copied


def restore(src):
    if not os.path.isdir(src):
        print(f"  nothing at {src}")
        return 0
    stamp = os.path.join(src, "_collected_at.txt")
    if os.path.exists(stamp):
        print("  backup taken: " + open(stamp, encoding="utf-8").read().strip().replace("\n", " | "))
    plan = []
    for title, name, why in files_to_move(True):
        s = os.path.join(src, name)
        if os.path.exists(s):
            plan.append((name, os.path.exists(os.path.join(ENGINE, name))))
    if not plan:
        print(f"  no known state files in {src}")
        return 0
    overwrite = [n for n, exists in plan if exists]
    print(f"\n  {len(plan)} file(s) to restore into {ENGINE}")
    if overwrite:
        # Never overwrite live operational state without showing it first - a
        # tracker.json replaced by an older one silently loses orders.
        print(f"  {len(overwrite)} of them ALREADY EXIST and will be replaced")
        print("  (the existing copy is kept as <name>.bak):")
        for n in overwrite:
            print(f"    - {n}")
        if input("\n  Type YES to go ahead: ").strip() != "YES":
            print("  nothing changed.")
            return 0
    done = 0
    for name, exists in plan:
        s, d = os.path.join(src, name), os.path.join(ENGINE, name)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if exists:
            shutil.copy2(d, d + ".bak")
        shutil.copy2(s, d)
        print(f"  [OK]  {name}")
        done += 1
    print(f"\n  {done} restored. Now run:  python work_pc\\engine_preflight.py")
    return done


def main():
    args = [a for a in sys.argv[1:] if a != "--no-live"]
    include_live = "--no-live" not in sys.argv
    if len(args) != 2 or args[0] not in ("backup", "restore"):
        print(__doc__)
        print("  backup  <folder>  [--no-live]   copy state OUT of this machine")
        print("  restore <folder>                copy state INTO this machine")
        return 2
    mode, folder = args
    folder = os.path.abspath(folder)
    if os.path.normcase(folder) == os.path.normcase(ENGINE):
        print("  refusing: that is the engine folder itself")
        return 2
    print(f"\n{mode} | engine: {ENGINE}\n")
    if mode == "backup":
        backup(folder, include_live)
    else:
        restore(folder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
