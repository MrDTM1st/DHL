"""
Supervisor for the Region 2 emailer.

Launched at logon by Task Scheduler ("DHL Region2 dashboard"). Keeps the
control plane (dashboard) and the home agent running at all times - starts
them, watches them, restarts them if they die. Child output goes to
control_plane.log / agent.log next to this file.
"""
import os, sys, time, socket, subprocess
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8787
CREATE_NO_WINDOW = 0x08000000
LOG = os.path.join(HERE, "supervisor.log")


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200_000:
            os.remove(LOG)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%d/%m/%Y %H:%M:%S}  {msg}\n")
    except OSError:
        pass


def port_up():
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", PORT))
        s.close()
        return True
    except OSError:
        return False


def spawn(script, args, logname):
    out = open(os.path.join(HERE, logname), "a", encoding="utf-8", errors="replace")
    return subprocess.Popen([sys.executable, os.path.join(HERE, script)] + args,
                            cwd=HERE, stdout=out, stderr=out,
                            creationflags=CREATE_NO_WINDOW)


def alive(proc):
    return proc is not None and proc.poll() is None


def cloud_config():
    """Optional cloud.json next to this file: {"url": "https://...", "agent_key": "..."}.
    When present, a second agent is kept running against the hosted dashboard."""
    import json
    p = os.path.join(HERE, "cloud.json")
    if os.path.exists(p):
        try:
            c = json.load(open(p, encoding="utf-8"))
            if c.get("url") and c.get("agent_key"):
                return c
        except Exception:
            pass
    return None


TICK_MAX_AGE = 25 * 60     # a tick still alive after this is stuck on a COM call


def tick(job, running):
    """Start `job` unless its previous run is still going.

    It used to be fired every 60s regardless, and a tick that took longer
    than 60s - easily done when Outlook is busy - overlapped the next. On
    02/10/2026 ten monitor ticks were running at once, Outlook froze and
    stopped syncing mail. A tick that has been alive TICK_MAX_AGE is stuck
    (it holds the one background-Outlook slot) and is killed so the rest of
    the toolkit is not locked out behind it."""
    prev = running.get(job)
    if alive(prev):
        if time.time() - prev.started < TICK_MAX_AGE:
            return
        # The whole tree: killing only the tick left the build / reply check
        # it had started still running, with the tick's slot already freed.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(prev.pid)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
        log(f"killed stuck {job} (alive {int(time.time() - prev.started)}s)")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, job)],
                         cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=CREATE_NO_WINDOW)
    p.started = time.time()
    running[job] = p


def main():
    # single-instance lock: if another supervisor already holds 8786, exit
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 8786))
    except OSError:
        return
    log("supervisor started")
    cp = agent = cloud_agent = None
    last_tick = 0.0
    ticks = {}
    while True:
        try:
            if not port_up():
                if alive(cp):
                    cp.kill()
                cp = spawn("control_plane.py", [], "control_plane.log")
                log("started control_plane")
                time.sleep(3)
            if not alive(agent):
                agent = spawn("agent.py", ["http://127.0.0.1:8787"], "agent.log")
                log("started agent")
            cc = cloud_config()
            if cc and not alive(cloud_agent):
                cloud_agent = spawn("agent.py", [cc["url"], cc["agent_key"]], "cloud_agent.log")
                log(f"started cloud agent -> {cc['url']}")
            if time.time() - last_tick > 60:   # self-update + handover + live Outlook monitor (COM)
                for job in ("home_tick.py", "monitor_tick.py"):
                    tick(job, ticks)
                last_tick = time.time()
        except Exception as e:
            log(f"error: {e}")
        time.sleep(20)


if __name__ == "__main__":
    main()
