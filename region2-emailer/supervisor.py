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
            if time.time() - last_tick > 60:   # self-update emails + handover forwarding (COM)
                subprocess.Popen([sys.executable, os.path.join(HERE, "home_tick.py")],
                                 cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=CREATE_NO_WINDOW)
                last_tick = time.time()
        except Exception as e:
            log(f"error: {e}")
        time.sleep(20)


if __name__ == "__main__":
    main()
