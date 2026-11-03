"""Settings > Update the home PC (03/11, home_update.py): main from GitHub by fast-forward only, refused over files
changed by hand, put back when the new code won't compile, and the agents told to start again. Real git repositories
in a temp folder - a stand-in for GitHub and the home PC's checkout.

    python -m pytest -q tests/test_home_update.py
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import home_update as H  # noqa: E402


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(repo, name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(text)


@pytest.fixture
def repos(tmp_path):
    """GitHub (a bare repo), the work done elsewhere (a clone that pushes), and the home PC's checkout."""
    hub, dev, home = str(tmp_path / "hub.git"), str(tmp_path / "dev"), str(tmp_path / "home")
    git(str(tmp_path), "init", "-q", "--bare", "-b", "main", hub)
    git(str(tmp_path), "clone", "-q", hub, dev)
    for r in (dev,):
        git(r, "config", "user.email", "t@example.com")
        git(r, "config", "user.name", "t")
    write(dev, "agent.py", "x = 1\n")
    write(dev, ".gitignore", "tracker.json\n")
    git(dev, "add", ".")
    git(dev, "commit", "-q", "-m", "one")
    git(dev, "push", "-q", "origin", "HEAD:main")
    git(str(tmp_path), "clone", "-q", "-b", "main", hub, home)
    git(home, "config", "user.email", "t@example.com")
    git(home, "config", "user.name", "t")
    write(home, "tracker.json", '{"records": ["his data"]}')        # work data: gitignored, never touched
    return hub, dev, home


def push(dev, name, text, msg="two"):
    write(dev, name, text)
    git(dev, "add", ".")
    git(dev, "commit", "-q", "-m", msg)
    git(dev, "push", "-q", "origin", "HEAD:main")


def test_new_code_on_main_is_brought_in_and_his_data_left_alone(repos):
    hub, dev, home = repos
    push(dev, "book_run.py", "y = 2\n")
    res = H.update(home)
    assert res["ok"] and res["changed"] == ["book_run.py"] and res["before"] != res["after"]
    assert open(os.path.join(home, "book_run.py")).read() == "y = 2\n"
    assert "his data" in open(os.path.join(home, "tracker.json")).read()
    assert H.version(home)["commit"] == res["after"] and H.version(home)["branch"] == "main"


def test_already_up_to_date_changes_nothing(repos):
    _, _, home = repos
    res = H.update(home)
    assert res["ok"] and res["changed"] == [] and "Already up to date" in res["said"]


def test_a_file_changed_by_hand_on_the_home_pc_stops_it_with_nothing_pulled(repos):
    _, dev, home = repos
    push(dev, "book_run.py", "y = 2\n")
    write(home, "agent.py", "x = 'his edit'\n")
    res = H.update(home)
    assert not res["ok"] and "changed by hand" in res["said"] and "agent.py" in res["said"]
    assert not os.path.exists(os.path.join(home, "book_run.py"))
    assert open(os.path.join(home, "agent.py")).read() == "x = 'his edit'\n"


def test_code_that_wont_compile_is_put_back(repos):
    _, dev, home = repos
    before = git(home, "rev-parse", "--short=7", "HEAD")
    push(dev, "agent.py", "def broken(:\n")
    res = H.update(home)
    assert not res["ok"] and "didn't compile" in res["said"] and "agent.py" in res["said"]
    assert open(os.path.join(home, "agent.py")).read() == "x = 1\n"
    assert git(home, "rev-parse", "--short=7", "HEAD") == before


def test_a_home_pc_left_on_another_branch_goes_to_main(repos):
    _, dev, home = repos
    git(home, "checkout", "-q", "-b", "claude/old-branch")
    push(dev, "book_run.py", "y = 2\n")
    res = H.update(home)
    assert res["ok"] and H.version(home)["branch"] == "main" and os.path.exists(os.path.join(home, "book_run.py"))


def test_commits_of_its_own_are_never_thrown_away(repos):
    _, dev, home = repos
    write(home, "local.py", "z = 3\n")
    git(home, "add", "local.py")
    git(home, "commit", "-q", "-m", "his own")
    push(dev, "book_run.py", "y = 2\n")
    res = H.update(home)
    assert not res["ok"] and "commits of its own" in res["said"]
    assert os.path.exists(os.path.join(home, "local.py"))


def test_the_agents_start_again_only_after_an_update_asked_since_they_started(tmp_path):
    flag = str(tmp_path / "flag")
    assert H.restart_due(100.0, flag) is False
    H.request_restart(flag, now=200.0)
    assert H.restart_due(100.0, flag) is True             # an agent from before the update: starts again
    assert H.restart_due(300.0, flag) is False            # the one started after it: carries on


def test_not_a_git_checkout_says_so(tmp_path):
    res = H.update(str(tmp_path))
    assert not res["ok"]
