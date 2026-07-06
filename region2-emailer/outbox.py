"""
Outbox for everything the tool generates (filled forms, upload CSVs).

Files land in Documents\\DHL\\outbox and are deleted automatically once they
are older than 2 days - they only exist to be uploaded/checked, then the
system of record has them.

Purge runs (a) every time any tool writes here and (b) daily via a Windows
scheduled task:  python outbox.py
"""
import os, time

OUTBOX = os.path.join(os.path.expanduser("~"), "Documents", "DHL", "outbox")
MAX_AGE_HOURS = 48


def path(filename=""):
    os.makedirs(OUTBOX, exist_ok=True)
    purge()
    return os.path.join(OUTBOX, filename) if filename else OUTBOX


def purge(max_age_hours=MAX_AGE_HOURS):
    if not os.path.isdir(OUTBOX):
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for name in os.listdir(OUTBOX):
        p = os.path.join(OUTBOX, name)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
                removed += 1
        except OSError:
            pass
    return removed


if __name__ == "__main__":
    n = purge()
    print(f"outbox purge: removed {n} file(s) older than {MAX_AGE_HOURS}h from {OUTBOX}")
