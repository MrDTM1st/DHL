"""
Where the dashboard is and the home PC's key - for ctms_remote.py and outlook_remote.py.

Tried in this order, the first that has both wins:

 1. CTMS_DESK_URL + CTMS_DESK_KEY in the environment
 2. cloud.json next to this file (the home PC: {"url", "agent_key"})
 3. the Railway CLI - for a Claude cloud session, which has neither. It reads
    the service's own variables: AGENT_KEY, and RAILWAY_PUBLIC_DOMAIN for the
    address (CTMS_DESK_URL still wins for the address if it is set).
    Needs RAILWAY_TOKEN (a project token for the dashboard's environment) in
    the session's environment, and backboard.railway.com allowed on its
    network. RAILWAY_SERVICE names the service if the project has more than
    one. RAILWAY_API_TOKEN (an account token) works too, with
    RAILWAY_PROJECT_ID (and RAILWAY_ENVIRONMENT, default "production") to link.
    The CLI is installed with npm the first time if it is missing.

Nothing found is kept on disk: the key lives in this process only.
"""
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


class NoDesk(Exception):
    pass


def _railway_bin():
    exe = shutil.which("railway")
    if exe:
        return exe
    npm = shutil.which("npm")
    if not npm:
        raise NoDesk("The Railway CLI is not installed and there is no npm to install it with.")
    try:
        subprocess.run([npm, "install", "-g", "@railway/cli"], capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NoDesk(f"Installing the Railway CLI failed: {e}")
    exe = shutil.which("railway")
    if not exe:
        raise NoDesk("Installing the Railway CLI (npm install -g @railway/cli) did not give a 'railway' command - "
                     "its installer fetches the binary from GitHub; is github.com reachable?")
    return exe


def _run(args, timeout=60):
    try:
        p = subprocess.run(args, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise NoDesk("The Railway CLI did not answer within a minute - is backboard.railway.com allowed "
                     "on this environment's network?")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip().splitlines()
        msg = msg[-1] if msg else f"exit {p.returncode}"
        if "403" in msg or "tunnel" in msg.lower() or "connect" in msg.lower():
            msg += " (backboard.railway.com may be blocked by this environment's network policy)"
        raise NoDesk("Railway CLI: " + msg)
    return p.stdout


def from_railway():
    """(url, key) from the dashboard service's variables, via the Railway CLI."""
    if not (os.environ.get("RAILWAY_TOKEN") or os.environ.get("RAILWAY_API_TOKEN")):
        raise NoDesk("No RAILWAY_TOKEN in this environment.")
    exe = _railway_bin()
    service = os.environ.get("RAILWAY_SERVICE", "").strip()
    project = os.environ.get("RAILWAY_PROJECT_ID", "").strip()
    if project:
        link = [exe, "link", "--project", project,
                "--environment", os.environ.get("RAILWAY_ENVIRONMENT", "production")]
        if service:
            link += ["--service", service]
        _run(link)
    cmd = [exe, "variables", "--json"]
    if service:
        cmd += ["--service", service]
    try:
        v = json.loads(_run(cmd) or "{}")
    except ValueError:
        raise NoDesk("The Railway CLI's variables were not JSON.")
    key = v.get("AGENT_KEY")
    url = os.environ.get("CTMS_DESK_URL") or ""
    if not url:
        dom = v.get("RAILWAY_PUBLIC_DOMAIN") or v.get("RAILWAY_STATIC_URL") or ""
        url = dom if dom.startswith("http") else (f"https://{dom}" if dom else "")
    if not key:
        raise NoDesk("The Railway service has no AGENT_KEY variable - wrong service? Set RAILWAY_SERVICE.")
    if not url:
        raise NoDesk("The Railway service has no public domain - set CTMS_DESK_URL to the dashboard's address.")
    return url, key


def desk():
    """(base url without the trailing slash, the home PC's key)."""
    url, key = os.environ.get("CTMS_DESK_URL"), os.environ.get("CTMS_DESK_KEY")
    if not (url and key):
        try:
            with open(os.path.join(HERE, "cloud.json"), encoding="utf-8") as f:
                cfg = json.load(f)
            url, key = url or cfg.get("url"), key or cfg.get("agent_key")
        except (OSError, ValueError):
            pass
    if not (url and key):
        try:
            url, key = from_railway()
        except NoDesk as e:
            raise NoDesk("No dashboard to talk to: no cloud.json here, no CTMS_DESK_URL / CTMS_DESK_KEY, "
                         f"and the Railway route did not work either ({e}).")
    return url.rstrip("/"), key
