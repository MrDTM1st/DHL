"""
Persistent watchdog for the DHL Haulage Desk.

A tiny, very-robust loop: every ~90 seconds it checks the supervisor (and thus
the Outlook agents + dashboard connection) is alive, and restarts it if it has
died - so a mid-day crash is recovered within a minute or two, not lost until
the next logon. Launched at logon from the Startup folder. The supervisor's
port-8786 lock makes "start when already up" a harmless no-op, and this watchdog
holds port 8785 so only one copy of it ever runs.
"""
import os, sys, time, subprocess, socket

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_SECONDS = 90


def _pythonw():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def supervisor_running():
    try:
        import win32com.client
        wmi = win32com.client.GetObject("winmgmts:")
        q = ("SELECT CommandLine FROM Win32_Process "
             "WHERE Name='pythonw.exe' OR Name='python.exe'")
        for p in wmi.ExecQuery(q):
            if "supervisor.py" in (p.CommandLine or ""):
                return True
    except Exception:
        pass
    return False


def start_supervisor():
    flags = 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen([_pythonw(), os.path.join(HERE, "supervisor.py")],
                         cwd=HERE, creationflags=flags, close_fds=True)
    except Exception:
        pass


def main():
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 8785))   # single-instance for the watchdog itself
    except OSError:
        return
    while True:
        try:
            if not supervisor_running():
                start_supervisor()
        except Exception:
            pass
        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    main()
