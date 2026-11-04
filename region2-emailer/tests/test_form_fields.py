"""Fields that went up wrong: a Word form's "MILTON KEYNES" town kept whole and a form whose postcodes do not read
refused rather than given a whole-looking reference; a contact typed with a leading space split as the database
splits it; an overdue collection on the upload notice as the most urgent thing on it; a bare outward code kept as
itself; and a quoted range logged as its lower figure. Made-up people, sites and orders only.

    python tests/test_form_fields.py
"""
import contextlib
import io
import os
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import nr_csv as N  # noqa: E402
import postcodes as P  # noqa: E402
import process_word_form as PW  # noqa: E402
import quotes as Q  # noqa: E402
import upload_notice as U  # noqa: E402


def test_an_all_caps_town_is_kept_whole_and_a_county_after_a_town_is_dropped():
    assert PW._address("Example Depot\nMILTON KEYNES MK9 1AA", "x")[3:] == ("MILTON KEYNES", "MK9 1AA")
    assert PW._address("Example Depot\n1 Example Road\nRetford NOTTINGHAMSHIRE DN22 7AA", "x")[3] == "Retford"
    assert PW._address("Example Depot\nDoncaster SOUTH YORKSHIRE DN4 5PL", "x")[3] == "Doncaster"


def test_a_word_form_whose_postcodes_do_not_read_is_refused():
    def row(cpc, dpc):
        return {"Customer Order No": PW.ah_ref(None, cpc, dpc), "Postcode": cpc, "D Postcode": dpc}
    assert PW._ref_unusable(row("", ""))           # "AH4/11/26" looks whole - it is not
    assert PW._ref_unusable(row("NE7 7XX", ""))
    assert PW._ref_unusable(row("", "S9 1AA"))
    assert not PW._ref_unusable(row("NE7 7XX", "S9 1AA"))


def test_a_contact_typed_with_a_leading_space_splits_like_any_other():
    assert (N.first_name(" John Smith"), N.last_name(" John Smith")) == ("John ", " Smith")
    assert (N.first_name("John Smith"), N.last_name("John Smith")) == ("John ", " Smith")
    assert N.first_name("") == N.first_name(None) == N.first_name("  ") == " TBA"
    o = {"Customer Order No": "AH01/01/26EXEX", "Site Name - Collection": "Example Depot",
         "Contact Name": " Sam Example", "Postcode": "EX1 1AA", "Delivery Point": "Example Siding",
         "D Contact Name": " Jo Example", "D Postcode": "EX2 2BB", "Product / Description": "Sleepers",
         "Product Qty": 2, "Raised by": "planner@example.com", "Account": "NRADHOC"}
    with contextlib.redirect_stdout(io.StringIO()):
        r = next(r for r in N.transform([o]) if r[0] == "ORDER")
    assert [r[4], r[5], r[17], r[18]] == ["Sam ", " Example", "Jo ", " Example"]


def test_an_overdue_collection_is_the_most_urgent_thing_on_the_notice():
    today = datetime(2026, 11, 4)
    assert U.urgency({"collection time": "02/11/2026 08:00"}, today) == (-2, "overdue by 2 days")
    assert U.urgency({"collection time": "03/11/2026 08:00"}, today) == (-1, "overdue by 1 day")
    assert U.urgency({"collection time": "05/11/2026 08:00"}, today) == (1, "tomorrow")
    assert U.urgency({"collection time": "08/11/2026 08:00"}, today) is None
    late = {"Customer Order No": "9100001", "collection time": "02/11/2026 08:00", "D Postcode": "G72 0AA",
            "Delivery Point": "Example Siding", "Site Name - Collection": "Example Depot"}
    soon = dict(late, **{"Customer Order No": "9100002", "collection time": "05/11/2026 08:00"})
    real = U.team_emails
    U.team_emails = lambda: ({}, "")
    try:
        email, urgent = U.build_notice([soon, late], "extract.xlsx", today=today, rota_path="/nonexistent/rota.xlsx")
    finally:
        U.team_emails = real
    assert [u["ref"] for u in urgent] == ["9100001", "9100002"]
    assert "overdue by 2 days" in email["message"] and "Nothing on this upload is urgent" not in email["message"]


def test_an_outward_code_alone_stays_itself():
    for pc, norm, out in (("DN16", "DN16", "DN16"), ("DN3", "DN3", "DN3"), ("EC1A", "EC1A", "EC1A"),
                          ("DN16 1BP", "DN16 1BP", "DN16"), ("dn161bp", "DN16 1BP", "DN16"),
                          ("DN3 1ED", "DN3 1ED", "DN3"), ("M1 1AA", "M1 1AA", "M1"), ("", "", "")):
        assert (P.norm(pc), P.outward(pc)) == (norm, out), pc
    assert P.outward("N/A") == "" and P.area("DN16") == "DN"


def test_a_quoted_range_is_logged_as_its_lower_figure():
    real = Q.PATH
    Q.PATH = os.path.join(tempfile.mkdtemp(), "_quotes.json")
    try:
        for price, want in (("£450-£500", 450.0), ("£450 - £500", 450.0), ("450 to 500", 450.0), ("£450", 450.0),
                            ("450.00", 450.0), ("450", 450.0), ("£1,250", 1250.0), ("£1,250.50-£1,400", 1250.5)):
            assert Q.add("Example Haulage", "DN16 1BP", "S9 1AA", price) == want, price
        try:
            Q.add("Example Haulage", "DN16 1BP", "S9 1AA", "tbc")
            assert False, "a price with no figure in it was logged"
        except ValueError:
            pass
    finally:
        Q.PATH = real


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
