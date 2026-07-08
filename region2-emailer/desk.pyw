"""
DHL Haulage Desk - one-click launcher.

Makes sure the background desk is running (supervisor -> local control plane +
the two Outlook agents that keep the dashboard connected), then optionally opens
the dashboard. Safe to double-click any time: the supervisor holds a single-
instance lock (port 8786), so a second copy simply exits - you can never end up
with duplicate agents double-sending.

  pythonw desk.pyw          # make sure the desk is running (used at logon / by the watchdog)
  pythonw desk.pyw open     # make sure it's running, then open the dashboard
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = "https://dhlbutbetter.up.railway.app"


def _pythonw():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def desk_running():
    """True if a supervisor process is already alive."""
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


def start_desk():
    if desk_running():
        return
    # Detached + no window so it keeps running after this launcher exits and
    # after the console/Claude that started it is closed.
    flags = 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen([_pythonw(), os.path.join(HERE, "supervisor.py")],
                     cwd=HERE, creationflags=flags, close_fds=True)


def main():
    start_desk()
    if any(a.lower() == "open" for a in sys.argv[1:]):
        try:
            os.startfile(DASHBOARD)
        except Exception:
            pass


if __name__ == "__main__":
    main()
