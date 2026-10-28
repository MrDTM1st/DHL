r"""
CTMS bridge setup for the work PC - made for you by the Haulage Desk's CTMS page.

Download it there (CTMS page -> Set up this PC) and double-click it. If Windows
says it "protected your PC", choose More info -> Run anyway. Nothing to type.
It:

  1. gets the latest code from GitHub (github.com/MrDTM1st/DHL) into
     %USERPROFILE%\CTMS-bridge - through this PC's proxy, or with PowerShell,
     or from a DHL-main.zip you downloaded yourself if neither can get out
  2. sets the bridge up for your dashboard. The key inside this file is the
     bridge's own, made from your dashboard key: it opens the bridge's channel
     and nothing else - it cannot send email or run the desk
  3. if you ticked it, makes the bridge start by itself when you log in
  4. starts the bridge. Open CTMS in your normal Edge as always - the bridge
     finds its window by itself. Your password never touches any of this.

After that, the dashboard's Update button keeps it up to date. Run this file
again any time to change your choices or repair the install.

(cloud/server.py serves this file: it fills in CONFIG, and puts one line in
front that lets Windows run it with a double-click - python -x skips it.)
"""
import glob
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlsplit

CONFIG = {}   # filled in by the dashboard when you download this file

ZIP_URL = os.environ.get("CTMS_SETUP_ZIP") or "https://github.com/MrDTM1st/DHL/archive/refs/heads/main.zip"
HOME = os.environ.get("CTMS_BRIDGE_HOME") or os.path.join(os.path.expanduser("~"), "CTMS-bridge")
WP = os.path.join(HOME, "region2-emailer", "work_pc")
EXPECT = "region2-emailer/work_pc/ctms_bridge.py"
TEST = bool(os.environ.get("CTMS_SETUP_TEST"))      # the tests: never stop or start a real bridge
LOCK_PORT = 8792                                    # the bridge's single-instance lock


def say(msg=""):
    print(msg, flush=True)


# ---- getting the code -----------------------------------------------------------
def pac_proxy():
    """The proxy this PC's browser uses - urllib cannot read a PAC file itself."""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            def value(name):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    return None
            explicit, pac = value("ProxyServer"), value("AutoConfigURL")
    except Exception:
        return None
    if explicit:
        return str(explicit).split(";")[0].split("=")[-1]
    if not pac:
        return None
    try:
        with urllib.request.urlopen(pac, timeout=10) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    hits = re.findall(r"PROXY\s+([A-Za-z0-9_.\-]+:\d+)", body)
    # a local Zscaler agent is what the PAC's default rule hands back; else
    # the last PROXY in the file is the default rule's (see pip_here.py)
    local = [h for h in hits if h.startswith("127.0.0.1")]
    return (local or hits[-1:] or [None])[0]


def fetch_python(dest):
    host = (urlsplit(ZIP_URL).hostname or "").lower()
    if host in ("127.0.0.1", "localhost") or ZIP_URL.startswith("file:"):
        handler = urllib.request.ProxyHandler({})
    else:
        proxy = pac_proxy()
        handler = (urllib.request.ProxyHandler({"http": f"http://{proxy}", "https": f"http://{proxy}"})
                   if proxy else urllib.request.ProxyHandler())
    # Python on Windows trusts the machine's own certificate stores, which is
    # where a corporate inspection CA lives - verification stays on
    opener = urllib.request.build_opener(handler, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(ZIP_URL, timeout=180) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def fetch_powershell(dest):
    """Windows' own downloader: it reads the PAC and the certificate store by itself."""
    script = ("$ProgressPreference = 'SilentlyContinue'; "
              "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
              "[Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials; "
              f"Invoke-WebRequest -UseBasicParsing -Uri '{ZIP_URL}' -OutFile '{dest}'")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(((r.stderr or r.stdout) or "PowerShell failed").strip().splitlines()[-1][:200])


def toolkit_zip(path):
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.endswith(EXPECT) for n in z.namelist())
    except Exception:
        return False


def from_downloads():
    """A DHL-main.zip the browser fetched - the way in when Python and PowerShell cannot get out."""
    found = glob.glob(os.path.join(os.path.expanduser("~"), "Downloads", "DHL-main*.zip"))
    for path in sorted(found, key=os.path.getmtime, reverse=True):
        if toolkit_zip(path):
            return path
    return None


def get_code(tmp):
    dest = os.path.join(tmp, "repo.zip")
    tried = []
    for how, fetch in (("through this PC's proxy", fetch_python), ("with PowerShell", fetch_powershell)):
        try:
            fetch(dest)
            if toolkit_zip(dest):
                return dest, how
            tried.append(f"{how}: what came back is not the toolkit (a proxy sign-in page?)")
        except Exception as e:
            tried.append(f"{how}: {type(e).__name__}: {str(e)[:160]}")
    z = from_downloads()
    if z:
        return z, f"from your Downloads ({os.path.basename(z)})"
    say("\nCould not get the code from GitHub:")
    for t in tried:
        say("  - " + t)
    say(f"\nDownload it in the browser instead - open this address, it saves to Downloads:\n  {ZIP_URL}\n"
        f"then run this setup again. It finds the ZIP there by itself.")
    raise SystemExit(1)


def install(zpath):
    """Lay the repo down in HOME. Settings and logs are not in the ZIP, so they stay."""
    n = 0
    with zipfile.ZipFile(zpath) as z:
        top = z.namelist()[0].split("/")[0] + "/"
        commit = z.comment.decode("ascii", "ignore").strip()[:40]
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(top):
                continue
            rel = info.filename[len(top):]
            parts = rel.split("/")
            if not rel or ".." in parts or ":" in rel:
                continue
            target = os.path.join(HOME, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(target + ".part", target)
            n += 1
    return commit, n


# ---- the bridge -----------------------------------------------------------------
def stop_bridges():
    """Close any CTMS bridge already running here, so the new install is the one that runs."""
    if TEST or os.name != "nt":
        return 0
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*ctms_bridge.py*' -and $_.ProcessId -ne {os.getpid()} }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; 'x' }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=60)
        return r.stdout.count("x")
    except Exception:
        return 0


def lock_free():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    if not CONFIG.get("key"):
        say("This is the template. Download your own setup from the dashboard's CTMS page "
            "(Set up this PC) - it comes ready made for your dashboard.")
        return 1
    say("CTMS bridge setup")
    say("=================")
    say(f"Dashboard: {CONFIG['desk']}    Made: {CONFIG.get('made', '?')}")
    say(f"Installing into: {HOME}\n")

    say("1/4  Getting the code from GitHub...")
    tmp = tempfile.mkdtemp(prefix="ctms-setup-")
    try:
        zpath, how = get_code(tmp)
        stopped = stop_bridges()
        if stopped:
            say(f"     closed the bridge that was running ({stopped} process(es)) - it restarts below")
        commit, files = install(zpath)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say(f"     done - {files} files, version {commit[:7] or '?'}, {how}")

    say("2/4  Setting the bridge up for your dashboard...")
    sys.path.insert(0, WP)
    import ctms_bridge
    import ctms_update
    old = ctms_bridge.load_config() or {}
    cfg = dict(old, url=CONFIG["desk"], key=CONFIG["key"], match=old.get("match", ""),
               allow_control=bool(CONFIG.get("allow_control")))
    ctms_bridge.save_config(cfg)
    if commit:
        ctms_update.stamp(commit, "main", "all", files)
    say("     done - " + ("Claude may act in CTMS while you switch that on from the dashboard"
                          if cfg["allow_control"] else "look only: Claude can never act in CTMS from this PC"))
    say("     checking this PC can reach the dashboard...")
    try:
        ctms_bridge.Desk(CONFIG["desk"], CONFIG["key"]).post("/api/ctms/hello", {}, timeout=30)
        say("     it can.")
    except urllib.error.HTTPError as e:
        say(f"     the dashboard answered HTTP {e.code}" + (
            " - this setup file is out of date (the dashboard key changed). Download a fresh one."
            if e.code == 401 else " - it may need redeploying."))
    except Exception as e:
        say(f"     NOT reachable from Python here ({type(e).__name__}: {str(e)[:160]}). The bridge keeps "
            f"trying and its window will say what is wrong.")

    on = bool(CONFIG.get("autostart"))
    say("3/4  Starting by itself when you log in...")
    where = ctms_bridge.set_autostart(on)
    say(f"     {'yes - ' + where if on else 'no (run this setup again, ticked, to turn it on)'}")

    say("4/4  Starting the bridge...")
    if TEST:
        say("     (test run - not started)")
    elif not lock_free():
        say("     a CTMS bridge is still running on this PC and could not be closed - close its window,\n"
            "     then run this setup again.")
        return 1
    else:
        # its own window, and nothing of this one's: a bridge holding on to this
        # window's handles would keep it from closing for as long as it runs
        subprocess.Popen([sys.executable, os.path.join(WP, "ctms_bridge.py")], cwd=WP, close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        say("     its window is opening now - leave it open (it can sit behind other windows).")
    say("\nDone. Open CTMS in your normal Edge as always - the bridge finds its window by itself.")
    say("The dashboard's CTMS page lights up by itself within a few seconds.")
    say("This file holds the bridge's key - you can delete it from Downloads now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
