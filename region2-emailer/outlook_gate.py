"""One background Outlook job at a time - and none while Outlook is frozen.

Classic Outlook answers COM calls from other processes on its one UI thread,
so every script talking to it queues behind the others and behind the window
itself. On 02/10/2026 the supervisor's 60-second monitor tick was taking more
than 60 seconds, so ticks piled up - ten at once within ten minutes of a
restart - and each started its own batch build or reply check. Outlook went
"Not Responding", stopped syncing mail for over an hour (hauliers' replies
looked like silence) and sends sat waiting. Three guards stop that:

  single_instance(name)   a second copy of the same job exits at once
  background_slot(wait)   only ONE background Outlook job runs at a time;
                          if the slot stays busy past `wait`, skip this cycle
  outlook_hung()          Outlook's window is Not Responding: don't pile on

All three are Windows kernel objects or window state, so a crash or a kill
can never leave a stale lock behind - Windows frees a mutex the moment the
process holding it dies.

User-initiated work from the dashboard (sends, builds, searches) must never
go through background_slot: it would be skipped, and a skipped send is a
silent failure. At most one background job runs alongside it.

    python outlook_gate.py run [--wait SECS] [--timeout SECS] <script.py> [args...]

is the launcher for background jobs fired from timers (agent.py): it takes
the slot (waiting up to SECS, default 0), runs the script, and frees the slot
when it exits. Busy or hung -> prints SKIP and exits SKIPPED (75) without
running, so the caller can tell "did not run, try again soon" from "ran".

The names are Local\\ (this logon session). That is deliberate: a process in
another session cannot drive this session's Outlook over COM anyway.
"""
import os
import sys
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# R2_GATE_SLOT lets a test use its own slot without fighting the live toolkit.
SLOT = os.environ.get("R2_GATE_SLOT") or "Local\\R2_outlook_background_job"
JOB_TIMEOUT = 900          # a background job still running after 15 min is stuck
SKIPPED = 75               # exit code: busy / Outlook hung - nothing was run

_held = []                 # handles must stay referenced for the process lifetime


def _mutex(name, own):
    import win32event, win32api, winerror
    h = win32event.CreateMutex(None, own, name)
    existed = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    return h, existed


def single_instance(name):
    """True if this is the only copy of `name` running; hold it until exit."""
    try:
        h, existed = _mutex("Local\\R2_single_" + name, True)
    except Exception:
        return True                     # no pywin32: never block the toolkit
    if existed:
        return False
    _held.append(h)
    return True


def named_lock(name, wait=0):
    """Take the lock `name`, waiting up to `wait` seconds. Returns a handle
    (keep it) or None if someone else still holds it after the wait."""
    try:
        import win32event
        h, _ = _mutex(name if "\\" in name else "Local\\R2_lock_" + name, False)
        r = win32event.WaitForSingleObject(h, int(max(0, wait) * 1000))
    except Exception:
        return True                     # no pywin32: behave as before
    # WAIT_ABANDONED (0x80): the last holder died mid-job - the lock is ours.
    if r in (win32event.WAIT_OBJECT_0, getattr(win32event, "WAIT_ABANDONED", 0x80)):
        _held.append(h)
        return h
    return None


def background_slot(wait=0):
    """Take the one background-Outlook slot, waiting up to `wait` seconds.
    Returns a handle (keep it) or None if another background job holds it."""
    return named_lock(SLOT, wait)


def kill_tree(pid):
    """Kill a process AND everything it started. Killing only the parent left
    its child job still hammering Outlook - and, with the parent's lock gone,
    the next job started alongside it."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=30,
                       creationflags=0x08000000)
    except Exception:
        pass


def release(slot):
    """Free the slot early (it is freed anyway when the process exits)."""
    try:
        import win32event
        if slot not in (None, True):
            win32event.ReleaseMutex(slot)
    except Exception:
        pass


def self_destruct(seconds):
    """Kill this process and everything it started after `seconds`. A tick
    blocked on a COM call (behind an Outlook prompt, say) holds the slot and
    its single-instance lock until it dies; the supervisor only knows about
    ticks it started itself, so after a supervisor restart nothing would ever
    kill it. This way every tick puts a limit on itself."""
    import threading
    t = threading.Timer(seconds, kill_tree, args=(os.getpid(),))
    t.daemon = True
    t.start()


def outlook_hung():
    """True when Outlook's main window is Not Responding (no input handled for
    5s - the same test Windows uses to grey the window out). Outlook not
    running counts as not hung."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW("rctrl_renwnd32", None)
        return bool(hwnd) and bool(ctypes.windll.user32.IsHungAppWindow(hwnd))
    except Exception:
        return False


def _std(stream):
    """`stream` if it is a real file the child can inherit, else None."""
    try:
        stream.flush()
        stream.fileno()
        return stream
    except Exception:
        return None


def _run(argv):
    wait, timeout = 0.0, JOB_TIMEOUT
    while argv[:1] and argv[0] in ("--wait", "--timeout"):
        if argv[0] == "--wait":
            wait = float(argv[1])
        else:
            timeout = float(argv[1])
        argv = argv[2:]
    if not argv:
        print("usage: outlook_gate.py run [--wait SECS] [--timeout SECS] <script.py> [args...]")
        return 2
    job = " ".join(argv)
    key = "_".join(os.path.basename(a) for a in argv).replace(".", "_")
    if not single_instance("job_" + key):
        print(f"SKIP {job}: already running")
        return SKIPPED
    if outlook_hung():
        print(f"SKIP {job}: Outlook is not responding")
        return SKIPPED
    slot = background_slot(wait)
    if slot is None:
        print(f"SKIP {job}: another background Outlook job is running")
        return SKIPPED
    try:
        if outlook_hung():              # it may have frozen while we waited
            print(f"SKIP {job}: Outlook is not responding")
            return SKIPPED
        started = time.time()
        # Hand our stdout/stderr to the job EXPLICITLY. The agent runs under
        # pythonw.exe, and a windowless process does not pass its standard
        # handles on by default - the job's output vanished, so the agent never
        # saw the sweep's SWEEP_RESULT or the wait-list send's sent/missed lines.
        p = subprocess.Popen([sys.executable] + argv, cwd=HERE,
                             stdout=_std(sys.stdout), stderr=_std(sys.stderr))
        try:
            return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p.pid)
            # Keep the slot until the job has really gone: releasing it while
            # a job that would not die is still talking to Outlook puts two
            # background jobs on it at once - the thing this gate prevents.
            try:
                p.kill()
                p.wait(timeout=120)
            except Exception:
                pass
            alive = p.poll() is None
            print(f"KILLED {job}: still running after {int(time.time() - started)}s"
                  + (" - and it would not die" if alive else ""))
            return 1
    finally:
        release(slot)


if __name__ == "__main__":
    if sys.argv[1:2] == ["run"]:
        sys.exit(_run(sys.argv[2:]))
    print(__doc__)
