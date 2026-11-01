"""An ad hoc form off the mailbox (monitor_tick puts it straight on the map): its email rides on the map record, and
what process_form said tells the monitor whether the job made it. No Excel, no Outlook; made-up orders and names.

    python tests/test_adhoc_from_mail.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import process_form as PF               # noqa: E402


def test_a_form_off_the_mail_keeps_its_email_on_the_map_record(tmp):
    keep = PF.ADHOCS, PF.FORMS_DIR
    PF.ADHOCS, PF.FORMS_DIR = os.path.join(tmp, "_adhocs.json"), os.path.join(tmp, "forms")
    try:
        import json
        rows = [{"Customer Order No": "AH01/11/26EXEX", "Delivery Point": "Example Depot", "D Postcode": "EX1 1AA",
                 "Product Qty": 2, "Product / Description": "PALLET"}]
        mail = {"from": "Sam Example", "subject": "Haulage request", "received": "2026-11-01 21:00",
                "file": "Haulage Request Form.xlsx", "entryid": "00AB", "store": "00CD", "conversation": "99",
                "body": "never kept"}
        assert PF.save_adhocs(rows, "NR_heavy_AH_01112026210000.csv", mail=mail) == 1
        rec = json.load(open(PF.ADHOCS, encoding="utf-8"))[0]
        assert rec["mail"] == {k: v for k, v in mail.items() if k != "body"}, rec["mail"]
        assert PF.save_adhocs(rows, "NR_heavy_AH_01112026210500.csv") == 1        # dropped in by hand: no email
        assert "mail" not in json.load(open(PF.ADHOCS, encoding="utf-8"))[0]
    finally:
        PF.ADHOCS, PF.FORMS_DIR = keep


def test_what_a_run_said_tells_the_monitor_whether_the_job_is_on_the_map(tmp):
    assert PF.outcome("FORM: local file\nMAP : job saved for the dashboard map (form kept for forwarding).\n"
                      "Order AH01/11/26EXEX | Example -> Depot | qty 2 | acct NRADHOC (defaulted)\n") \
        == (True, "AH01/11/26EXEX")
    assert PF.outcome("!! INCOMPLETE ORDER NUMBER 'FS-' - the form's order-number field (e.g. Collection Ref) is "
                      "blank.\nNothing written - no usable order number on the form.\n")[0] is False
    assert PF.outcome("SKIP: AH1 is already booked in - not putting it back on the map\nMAP : NOT on the map - "
                      "every job in this form was refused, see the SKIP line(s) above.\n") \
        == (False, "SKIP: AH1 is already booked in - not putting it back on the map")
    assert PF.outcome("Traceback ...") == (False, "the form did not finish processing")


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(tmp)
                print(f"ok    {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
