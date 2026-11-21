"""The Toolkit switch on the Dashboard (asked for 21/11, when Outlook would not even open on the home PC): off, nothing
on the home PC starts on Outlook - the supervisor's ticks, the agent's timer jobs, the outlook_gate launcher, the
work-mail channel - and every command but the switch and Update the home PC is turned down and said. A made-up
command and a temporary switch file only.

    python -m pytest -q tests/test_toolkit_switch.py
"""
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import toolkit_switch as T          # noqa: E402
import outlook_gate                 # noqa: E402


@pytest.fixture
def off(tmp_path, monkeypatch):
    """The switch file in a folder of the test's own, whatever this PC's switch says. -> a function turning it off."""
    monkeypatch.setattr(T, "FLAG", str(tmp_path / "toolkit.off"))
    return lambda: T.switch(False, by="a test", now=1795000000)


def test_off_is_a_file_that_keeps_the_time_it_first_went_off_and_on_takes_it_away(off):
    assert not T.is_off() and T.state() == {"on": True}
    assert off() is False and T.is_off()
    first = T.since()
    assert first and os.path.exists(T.FLAG)
    T.switch(False, now=1795003600)                        # off again an hour on: still off since the first time
    assert T.since() == first
    assert T.switch(True) is True and not T.is_off() and not os.path.exists(T.FLAG)
    assert T.switch(True) is True                          # on twice is no fault


def test_while_off_the_panel_says_since_when_what_is_still_finishing_and_how_outlook_is(off, monkeypatch):
    off()
    held = {"Local\\R2_single_job_phase2_py_check", "Local\\R2_single_monitor_tick"}
    monkeypatch.setattr(T, "_held", lambda name: name in held)
    monkeypatch.setattr(T, "outlook", lambda: "running with no window")
    jobs = [("phase2_check", ["phase2.py", "check"]), ("chase", ["phase2.py", "chase", "send"]),
            ("new_job", ["new_job.py"])]
    s = T.state(jobs, ["a work-mail search"])
    assert s["on"] is False and s["since"] == T.since() and s["outlook"] == "running with no window"
    assert s["busy"] == ["a work-mail search", "the reply check", "the live monitor"], s["busy"]
    held.add("Local\\R2_single_job_new_job_py")            # a job with no words of its own is said by its key
    assert "new job" in T.state(jobs)["busy"]


def test_the_lock_it_looks_at_is_the_one_outlook_gate_takes():
    assert outlook_gate.job_lock(["phase2.py", "check"]) == "job_phase2_py_check"
    assert outlook_gate.job_lock(["C:\\x\\waitlist_release.py", "send"]) == "job_waitlist_release_py_send"


def test_outlook_gate_runs_no_job_while_it_is_off(off, monkeypatch, capsys):
    off()
    ran = []
    monkeypatch.setattr(outlook_gate, "single_instance", lambda name: ran.append(name) or True)
    monkeypatch.setattr(outlook_gate.subprocess, "Popen", lambda *a, **k: ran.append(a))
    assert outlook_gate._run(["phase2.py", "check"]) == outlook_gate.SKIPPED
    assert ran == [] and "switched off" in capsys.readouterr().out


def test_the_supervisor_starts_no_tick_while_it_is_off(off, monkeypatch):
    import supervisor
    started = []
    monkeypatch.setattr(supervisor, "tick", lambda job, running: started.append(job))
    assert supervisor.fire_ticks({}) is True and started == ["home_tick.py", "monitor_tick.py"]
    started.clear()
    off()
    assert supervisor.fire_ticks({}) is False and started == []


def test_the_home_tick_goes_away_before_it_touches_outlook_while_it_is_off(off, monkeypatch):
    asked = []
    monkeypatch.setitem(sys.modules, "outlook_gate", types.SimpleNamespace(
        single_instance=lambda name: asked.append(name) or False))
    monkeypatch.delitem(sys.modules, "home_tick", raising=False)
    import home_tick
    try:
        home_tick.main()                                   # on: it goes as far as its single-instance lock
        assert asked == ["home_tick"]
        asked.clear()
        off()
        home_tick.main()
        assert asked == []
    finally:
        sys.modules.pop("home_tick", None)


# ---- the agent ---------------------------------------------------------------------------------------------------
@pytest.fixture
def A(off, monkeypatch):
    import agent
    said, sent, panels = [], [], []
    monkeypatch.setattr(agent, "report", lambda state, detail, *a, **k: said.append((state, detail)))
    monkeypatch.setattr(agent, "_req", lambda path, data=None, timeout=15: sent.append((path, data)) or {})
    monkeypatch.setattr(agent, "push_panel", lambda: panels.append(1))
    agent.said, agent.sent, agent.panels, agent.off = said, sent, panels, off
    return agent


def test_the_switch_flips_it_on_the_home_pc_and_says_so(A):
    assert A._toolkit_command({"action": "set_toolkit", "on": False}) is True
    assert T.is_off() and A.panels and A.said[-1][0] == "done" and "Toolkit OFF" in A.said[-1][1]
    assert A._toolkit_command({"action": "set_toolkit", "on": True}) is True
    assert not T.is_off() and "Toolkit ON" in A.said[-1][1]
    # an on/off that did not arrive changes nothing
    A.off()
    assert A._toolkit_command({"action": "set_toolkit", "on": None}) is True
    assert T.is_off() and A.said[-1][0] == "error"


def test_while_off_a_command_is_turned_down_and_said_and_a_run_the_dashboard_follows_is_ended(A):
    assert A._toolkit_command({"action": "extract_preview"}) is False      # on: the loop runs it as ever
    A.off()
    assert A._toolkit_command({"action": "extract_preview"}) is True
    state, detail = A.said[-1]
    assert state == "error" and "extract_preview" in detail and "switched off" in detail
    assert A.sent == []
    assert A._toolkit_command({"action": "ctms_book", "run": 7}) is True
    assert A.sent == [("/api/ctms/book/ran", {"run": 7, "ok": False, "said": T.OFF_SAID})]
    # Update the home PC is only git - it still goes; and no command at all is nothing to turn down
    assert A._toolkit_command({"action": "home_update"}) is False
    assert A._toolkit_command({}) is False


def test_while_off_the_agent_starts_no_timer_job_but_still_hears_one_end(A, monkeypatch, tmp_path):
    monkeypatch.setattr(A, "BG_TIMERS", str(tmp_path / "timers.json"))
    bg = A.BackgroundJobs()
    bg.jobs = [("phase2_check", ["phase2.py", "check"], 1, 60, lambda: True)]
    bg.last = {"phase2_check": 0.0}
    launched = []
    monkeypatch.setattr(bg, "_launch", lambda *a: launched.append(a[0]))
    A.off()
    bg.tick()
    assert launched == []
    ended = []
    bg.running = ("phase2_check", types.SimpleNamespace(poll=lambda: 0, returncode=0), 0.0, 0)
    monkeypatch.setattr(bg, "_done", lambda *a: ended.append(a[0]))
    bg.tick()
    assert ended == ["phase2_check"] and bg.running is None and launched == []
    T.switch(True)
    bg.tick()
    assert launched == ["phase2_check"]


def test_while_off_a_work_mail_ask_is_answered_without_outlook(A, monkeypatch):
    asked = []
    monkeypatch.setattr(A, "_mail_answer", lambda cmd: asked.append(cmd) or (True, {"n": 1}))
    assert A._mail_reply({"id": 1, "action": "search"}) == (True, {"n": 1}) and A._mail_job["on"] == ""
    A.off()
    ok, res = A._mail_reply({"id": 2, "action": "search"})
    assert not ok and res["error"] == T.OFF_SAID and len(asked) == 1
