"""send_order after a Send: an email that has gone is counted and SEND_RESULT says so, whatever fails after it - the
tracker's record, a subject the home PC's console can't print - or the agent reads NOTHING SENT, keeps the batch, and a
resend sends it twice. A stand-in Outlook; made-up orders and addresses only.

    python -m pytest -q tests/test_send_order.py
"""
import io
import json
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
NS = types.SimpleNamespace(SendAndReceive=lambda wait: None)


@pytest.fixture
def S(tmp_path, monkeypatch):
    """send_order with build_drafts (which reads the private config at import), Outlook and the logs stood in for."""
    bd = types.ModuleType("build_drafts")
    bd.HERE, bd.PENDING_BATCH, bd.SIGNATURE, bd.DHL_SMTP = str(tmp_path), str(tmp_path / "batch.json"), "", "me@example.com"
    bd.clean_to_cc = lambda to, cc: (to, cc, [])
    bd._attach_qr = lambda m: None
    bd.html_from_message = lambda text: f"<p>{text}</p>"
    monkeypatch.setitem(sys.modules, "build_drafts", bd)
    sent = []

    class Mail:
        Attachments = types.SimpleNamespace(Add=lambda p: None)

        def Send(self):
            sent.append(self.Subject)
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda name: types.SimpleNamespace(CreateItem=lambda kind: Mail())
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "metrics", types.SimpleNamespace(log=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "haulier_asks", types.SimpleNamespace(record=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "ask_check", types.SimpleNamespace(check=lambda message, orders: []))
    monkeypatch.delitem(sys.modules, "send_order", raising=False)
    import send_order
    monkeypatch.setattr(send_order, "dhl_account", lambda ns: object())
    monkeypatch.setattr(send_order, "bind_account", lambda m, acct: True)
    send_order.sent = sent
    yield send_order
    sys.modules.pop("send_order", None)


def test_an_email_sent_is_counted_and_said_even_when_its_tracker_record_fails(S, monkeypatch, capsys):
    def locked(**k):
        raise OSError("tracker.json is in use")
    monkeypatch.setattr(S.tracker, "log", locked)
    emails = [{"to": f"site{i}@example.com", "subject": f"900000{i} Delivery", "html": "<p>x</p>", "date": "06/11/2026",
               "orders": [f"900000{i}"]} for i in (1, 2)]
    assert S.send_emails(NS, emails) == 2
    assert S.sent == ["9000001 Delivery", "9000002 Delivery"]
    assert "SENT, but the tracker's record of it failed" in capsys.readouterr().out


def test_a_haulier_request_sent_is_reported_whatever_the_console_can_show(S, monkeypatch):
    with open(S.PENDING_HAULIER, "w", encoding="utf-8") as f:
        json.dump({"to": "ops@haulier.example", "subject": "9000001 Łódź Delivery", "message": "Hi",
                   "orders": ["9000001"]}, f)
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")       # the home PC's console codepage
    monkeypatch.setattr(sys, "stdout", console)
    assert S.send_haulier(NS) == 1
    console.flush()
    assert "SEND_RESULT sent=1" in raw.getvalue().decode("cp1252")
    assert S.sent == ["9000001 Łódź Delivery"] and not os.path.exists(S.PENDING_HAULIER)


def test_the_agent_hears_send_result_from_a_child_whose_console_cant_show_a_name(monkeypatch):
    import agent as A
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    out = A.run(["-c", "print('Haulier request sent: 9000001 \\u0141\\u00f3d\\u017a'); print('SEND_RESULT sent=1')"])
    assert A.send_verdict(out) == (True, 1) and "Łódź" in out
