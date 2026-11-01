"""site_contacts: the site's phone, from the extract to the dashboard's Call button.
Made-up names and Ofcom drama-range numbers only - this repo is public."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import site_contacts as sc  # noqa: E402


class ContactOf(unittest.TestCase):
    def test_phone_column_wins(self):
        self.assertEqual(sc.contact_of("Sam Example email: sam@example.com phone: 07700900123", " 07700 900456"),
                         ("Sam Example", "07700 900456"))

    def test_cell_phone_when_column_blank(self):
        self.assertEqual(sc.contact_of("Sam Example email: sam@example.com phone: 07700900123", ""),
                         ("Sam Example", "07700900123"))

    def test_landline_and_plus44(self):
        self.assertEqual(sc.contact_of("Jo Test", "+44 (0)1632 960123")[1], "+44 (0)1632 960123")
        self.assertEqual(sc.contact_of("Jo Test phone: 01632 960123")[1], "01632 960123")

    def test_no_number_no_name(self):
        self.assertEqual(sc.contact_of("email: someone@example.com", ""), ("", ""))
        self.assertEqual(sc.contact_of(None, None), ("", ""))

    def test_order_numbers_are_not_phones(self):
        self.assertEqual(sc.contact_of("Order 6000001 for site 12/11/2026", "")[1], "")


class RememberAndEnrich(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.book = os.path.join(self.dir, "_site_phones.json")

    def test_round_trip(self):
        emails = [{"orders": ["9000001"], "site_contact": "Sam Example", "site_phone": "07700 900123"},
                  {"orders": ["9000002"], "site_contact": "No Phone", "site_phone": ""}]
        self.assertTrue(sc.remember(emails, self.book))
        self.assertFalse(sc.remember(emails, self.book))      # nothing new - file left alone
        with open(self.book, encoding="utf-8") as f:
            self.assertEqual(set(json.load(f)), {"9000001"})
        data = {"records": [
            {"orders": ["9000001"], "kind": "delivery"},
            {"orders": ["9000001"], "kind": "collection"},                     # the supplier, not the site
            {"orders": ["9000001"], "site_phone": "07700 900999"},             # already has one
            {"orders": ["9000002"]},                                           # nothing remembered
        ]}
        out = sc.enrich(data, self.book)["records"]
        self.assertEqual((out[0]["site_phone"], out[0]["site_contact"]), ("07700 900123", "Sam Example"))
        self.assertNotIn("site_phone", out[1])
        self.assertEqual(out[2]["site_phone"], "07700 900999")
        self.assertNotIn("site_phone", out[3])

    def test_line_suffix_matches_base_order(self):
        sc.remember([{"orders": ["9000003"], "site_contact": "", "site_phone": "01632 960321"}], self.book)
        rec = sc.enrich({"records": [{"orders": ["9000003-1-1"]}]}, self.book)["records"][0]
        self.assertEqual(rec["site_phone"], "01632 960321")
        self.assertNotIn("site_contact", rec)

    def test_broken_book_is_ignored(self):
        with open(self.book, "w", encoding="utf-8") as f:
            f.write("{not json")
        data = {"records": [{"orders": ["9000001"]}]}
        self.assertIs(sc.enrich(data, self.book), data)
        self.assertTrue(sc.remember([{"orders": ["9000004"], "site_phone": "07700 900111"}], self.book))


class FillContact(unittest.TestCase):
    """His rule (01/11): no site contact in the reply - the person who sent it, name and number off the sheet."""

    def test_same_person(self):
        self.assertTrue(sc.same_person("Gallimore, Sam", "Sam Gallimore"))
        self.assertTrue(sc.same_person("S Gallimore", "Sam Gallimore"))
        self.assertFalse(sc.same_person("Sam", "Sam Gallimore"))            # a lone first name is never enough
        self.assertFalse(sc.same_person("Jo Gallimore", "Sam Gallimore"))

    def test_fill(self):
        self.assertEqual(sc.fill_contact({"name": "", "phone": ""}, "Sam Example", "07700 900123"),
                         ("Sam Example", "07700 900123", "sheet"))
        self.assertEqual(sc.fill_contact({"name": "Sam Example", "phone": ""}, "Sam Example", "07700 900123"),
                         ("Sam Example", "07700 900123", "sheet phone"))
        self.assertEqual(sc.fill_contact({"name": "Jo Test", "phone": ""}, "Sam Example", "07700 900123"),
                         ("Jo Test", "", ""))                                   # someone else - not their number
        self.assertEqual(sc.fill_contact({"name": "Jo Test", "phone": ""}, "Sam Example", "07700 900123", same=True),
                         ("Jo Test", "07700 900123", "sheet phone"))           # the address we emailed replied
        self.assertEqual(sc.fill_contact({"name": "Jo Test", "phone": "07700900999"}, "Sam Example", "07700 900123"),
                         ("Jo Test", "07700900999", ""))                        # the reply's own number stands
        self.assertEqual(sc.fill_contact({}, "Sam Example", ""), ("", "", ""))   # no number on the sheet: nothing

    def test_fill_reply_from_the_book(self):
        book = os.path.join(tempfile.mkdtemp(), "_site_phones.json")
        with open(book, "w", encoding="utf-8") as f:
            json.dump({"9000005": {"name": "Sam Example", "phone": "07700 900123"}}, f)

        class Reply:
            SenderEmailAddress = "Sam.Example@example.com"
        rec = {"orders": ["9000005-1-1"], "to": "sam.example@example.com",
               "details": {"contact": {"name": "Sam E", "phone": "", "source": "sender"}}}
        self.assertTrue(sc.fill_reply(rec, Reply(), book))
        self.assertEqual(rec["details"]["contact"]["phone"], "07700900123")
        self.assertEqual(rec["details"]["contact"]["source"], "sheet phone")
        self.assertFalse(sc.fill_reply({"orders": ["9000006"], "details": {"contact": {}}}, Reply(), book))


if __name__ == "__main__":
    unittest.main()
