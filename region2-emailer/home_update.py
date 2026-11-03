"""
The home PC's code brought up to date from GitHub - the dashboard's Settings > Update the home PC (his ask 03/11:
"how am I updating the home PC?", then "create like a settings button ... it says update the home PC").

The home PC is a git checkout. Until now it was a Command Prompt: git pull, then the agents killed by hand so they'd
start again on the new code. Here, from the dashboard:

  1. refused if a file git tracks was changed by hand here - nothing is pulled over his edits
  2. main fetched from GitHub and moved to by fast-forward only: the home PC's own commits are never thrown away
  3. every changed .py compiled; one that won't is the whole update put back as it was
  4. the agents told to restart: each one, once it isn't in the middle of anything, exits and the supervisor starts it
     again within 20 seconds, on the new code. Everything else (book_run, phase2, ...) starts fresh each time anyway

Work data is never touched: it's gitignored, and only tracked files move. Standard library only.

    python home_update.py            what the home PC runs now
    python home_update.py update     the update, as the dashboard's button does it
"""
import json
import os
import py_compile
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(HERE, "_restart_agents.flag")
BRANCH = "main"


def _git(repo, *args, timeout=120):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def root(start=HERE):
    code, out, _ = _git(start, "rev-parse", "--show-toplevel")
    return out if code == 0 and out else None


def version(repo=None):
    """{"branch", "commit", "subject", "when"} of what the home PC runs - {} when it isn't a git checkout."""
    repo = repo or root()
    if not repo:
        return {}
    code, out, _ = _git(repo, "log", "-1", "--format=%h%x1f%s%x1f%cd", "--date=format:%d/%m %H:%M")
    _, branch, _ = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or not out:
        return {}
    commit, subject, when = (out.split("\x1f") + ["", ""])[:3]
    return {"branch": branch, "commit": commit, "subject": subject[:120], "when": when}


def update(repo=None, branch=BRANCH, compile_py=py_compile.compile):
    """The update: {"ok", "said", "before", "after", "changed"}. Nothing is left half done: a refusal changes nothing,
    and code that won't compile is put back."""
    repo = repo or root()
    out = {"ok": False, "said": "", "before": "", "after": "", "changed": []}
    if not repo:
        out["said"] = "The home PC's code isn't a git checkout, so it can't update itself: clone the repo there."
        return out
    _, before, _ = _git(repo, "rev-parse", "HEAD")
    out["before"] = before[:7]
    code, dirty, err = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if code != 0:
        out["said"] = f"git couldn't look at the home PC's code ({err[:200]}). Nothing was changed."
        return out
    if dirty:
        files = ", ".join(line.strip().split(None, 1)[-1] for line in dirty.splitlines()[:6])
        out["said"] = (f"Files git keeps were changed by hand on the home PC ({files}), so nothing was pulled over "
                       "them. Commit or undo them there, then update again.")
        return out
    code, _, err = _git(repo, "fetch", "origin", branch, timeout=300)
    if code != 0:
        out["said"] = f"GitHub couldn't be reached from the home PC ({err[:200]}). Nothing was changed."
        return out
    _, here, _ = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if here != branch:
        code, _, err = _git(repo, "checkout", branch)
        if code != 0:
            out["said"] = f"The home PC was on {here} and couldn't go to {branch} ({err[:200]}). Nothing was changed."
            return out
    code, _, err = _git(repo, "merge", "--ff-only", f"origin/{branch}")
    if code != 0:
        _git(repo, "checkout", here)
        out["said"] = (f"The home PC's code has commits of its own that GitHub's {branch} hasn't, so it wasn't "
                       f"moved ({err[:160]}). Nothing was changed.")
        return out
    _, after, _ = _git(repo, "rev-parse", "HEAD")
    out["after"] = after[:7]
    if after == before:
        out.update(ok=True, said=f"Already up to date: {branch} at {after[:7]}.")
        return out
    _, names, _ = _git(repo, "diff", "--name-only", before, after)
    out["changed"] = [n for n in names.splitlines() if n]
    bad = []
    for n in out["changed"]:
        p = os.path.join(repo, n)
        if n.endswith(".py") and os.path.isfile(p):
            try:
                compile_py(p, doraise=True)
            except Exception as e:
                bad.append(f"{n}: {str(e).splitlines()[0][:120] if str(e) else type(e).__name__}")
    if bad:
        _git(repo, "reset", "--hard", before)             # tracked files only: his data is gitignored, never touched
        if here != branch:
            _git(repo, "checkout", here)
        out.update(after=before[:7], said="The new code didn't compile, so the home PC was put back as it was: "
                                          + "; ".join(bad[:3]))
        return out
    out.update(ok=True, said=f"Updated {before[:7]} to {after[:7]}: {len(out['changed'])} file(s).")
    return out


# -- the agents starting again on the new code
def request_restart(path=FLAG, now=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(now or time.time()))


def restart_due(started, path=FLAG):
    """Whether an update asked for the agents to start again since this one started."""
    try:
        with open(path, encoding="utf-8") as f:
            return float(f.read().strip() or 0) > started
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:2] == ["update"]:
        res = update()
        if res["ok"] and res["changed"]:
            request_restart()
        print(res["said"])
        print(json.dumps(res))
        sys.exit(0 if res["ok"] else 1)
    print(json.dumps(version()))
